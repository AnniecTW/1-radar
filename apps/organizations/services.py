from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import User
from apps.events.models import Event, EventCheckInStaff
from apps.notifications.models import Notification

from .models import Organization, OrganizationFollow, OrganizationMembership, OrganizationVerificationRequest
from .permissions import user_can_manage_members, user_can_manage_organization

MAX_OWNED_ORGANIZATIONS = 3


def add_organization_member(*, actor, organization, user, role):
    if not user_can_manage_members(actor, organization):
        raise PermissionDenied('Only the organization Owner can manage members.')
    if not user.is_campus_verified:
        raise ValidationError('Organization members must have a verified campus email.')
    if role not in {OrganizationMembership.Role.ADMIN, OrganizationMembership.Role.CHECKIN_STAFF}:
        raise ValidationError('Use ownership transfer to assign the Owner role.')
    membership, created = OrganizationMembership.objects.get_or_create(
        organization=organization,
        user=user,
        defaults={'role': role, 'invited_by': actor},
    )
    if not created:
        if membership.role == OrganizationMembership.Role.OWNER:
            raise ValidationError('The Owner is already a member. Use ownership transfer to change the Owner.')
        membership.role = role
        membership.invited_by = actor
        membership.save(update_fields=['role', 'invited_by', 'updated_at'])
    return membership


def remove_organization_member(*, actor, membership):
    if not user_can_manage_members(actor, membership.organization):
        raise PermissionDenied('Only the organization Owner can remove members.')
    if membership.role == OrganizationMembership.Role.OWNER:
        raise ValidationError('Transfer ownership before removing the Owner.')
    with transaction.atomic():
        # Check-in assignments (FR-80) only make sense for current Check-in Staff of this organization.
        EventCheckInStaff.objects.filter(
            user_id=membership.user_id, event__organization_id=membership.organization_id
        ).delete()
        membership.delete()


@transaction.atomic
def transfer_organization_ownership(*, actor, organization_id, new_owner_id):
    organization = Organization.objects.select_for_update().get(pk=organization_id)
    current_owner = OrganizationMembership.objects.select_for_update().filter(
        organization=organization, user=actor, role=OrganizationMembership.Role.OWNER
    ).first()
    if current_owner is None:
        raise PermissionDenied('Only the organization Owner can transfer ownership.')
    new_owner = OrganizationMembership.objects.select_for_update().select_related('user').filter(
        organization=organization, user_id=new_owner_id
    ).first()
    if new_owner is None:
        raise ValidationError('Choose a current member of this organization.')
    if not new_owner.user.is_campus_verified:
        raise ValidationError('The new Owner must have a verified campus email.')
    if new_owner.pk == current_owner.pk:
        return current_owner
    owned = OrganizationMembership.objects.filter(
        user_id=new_owner_id, role=OrganizationMembership.Role.OWNER
    ).count()
    if owned >= MAX_OWNED_ORGANIZATIONS:
        raise ValidationError(f'That person already owns {MAX_OWNED_ORGANIZATIONS} organizations.')

    # The unique-owner constraint allows one Owner at a time, so demote before promoting.
    current_owner.role = OrganizationMembership.Role.ADMIN
    current_owner.save(update_fields=['role', 'updated_at'])
    new_owner.role = OrganizationMembership.Role.OWNER
    new_owner.save(update_fields=['role', 'updated_at'])
    # Owners check in as hosts, so per-event staff assignments no longer apply.
    EventCheckInStaff.objects.filter(user_id=new_owner_id, event__organization=organization).delete()
    Notification.objects.create(
        user=new_owner.user, organization=organization, type=Notification.Type.ORG_INVITE,
        payload={'role': new_owner.get_role_display()},
    )
    return new_owner


@transaction.atomic
def leave_organization(*, user, organization):
    """Any non-Owner member can leave. The Owner must transfer ownership or delete the organization."""
    membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization, user=user
    ).first()
    if membership is None:
        raise ValidationError('You are not a member of this organization.')
    if membership.role == OrganizationMembership.Role.OWNER:
        raise ValidationError('Transfer ownership or delete the organization before leaving.')
    EventCheckInStaff.objects.filter(user=user, event__organization=organization).delete()
    membership.delete()


def organization_blocking_events(organization):
    """Published events that have not ended yet. Deleting the organization would orphan them mid-flight."""
    return Event.objects.filter(
        organization=organization, status=Event.Status.PUBLISHED, end_at__gt=timezone.now()
    )


def delete_organization(*, actor, organization, confirm_name):
    """Owner only, and only when no published event is upcoming or running.

    Past and draft events stay with their hosts (organization becomes null); memberships, follows and
    verification requests go with the organization.
    """
    if not user_can_manage_organization(actor, organization):
        raise PermissionDenied('Only the organization Owner can delete it.')
    if confirm_name.strip() != organization.name:
        raise ValidationError('Type the organization name exactly to confirm.')
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization.pk)
        blocking = organization_blocking_events(organization).count()
        if blocking:
            raise ValidationError(
                f'Cancel or finish its {blocking} upcoming event{"s" if blocking != 1 else ""} before deleting.'
            )
        EventCheckInStaff.objects.filter(event__organization=organization).delete()
        logo = organization.logo
        organization.delete()
    if logo:
        logo.delete(save=False)


def follow_organization(*, user, organization, source):
    """Follow once; repeat calls change nothing. Keeps the cached follower_count in step."""
    with transaction.atomic():
        _, created = OrganizationFollow.objects.get_or_create(
            user=user, organization=organization, defaults={'source': source}
        )
        if created:
            Organization.objects.filter(pk=organization.pk).update(follower_count=F('follower_count') + 1)
    return created



def unfollow_organization(*, user, organization) -> bool:
    """Unfollow once; repeat calls change nothing. Keeps the cached follower_count in step."""
    with transaction.atomic():
        deleted, _ = OrganizationFollow.objects.filter(user=user, organization=organization).delete()
        if deleted:
            Organization.objects.filter(pk=organization.pk, follower_count__gt=0).update(
                follower_count=F('follower_count') - 1
            )
    return bool(deleted)


def set_follow_notifications(*, user, organization, notify: bool) -> None:
    """Mute or unmute an organization; muted organizations stay followed (FR-59)."""
    OrganizationFollow.objects.filter(user=user, organization=organization).update(notify=notify)


def _unique_organization_slug(name):
    base = slugify(name)[:140].strip('-') or 'organization'
    slug, counter = base, 2
    while Organization.objects.filter(slug=slug).exists():
        slug = f'{base}-{counter}'
        counter += 1
    return slug


def create_organization(*, creator, name, org_type, description='', logo=None, contact_email='',
                        website_url=None, instagram_url=None):
    """FR-5: only campus members create organizations; the model makes the creator its Owner."""
    if not creator.is_campus_verified:
        raise PermissionDenied('Only campus members can create an organization.')
    with transaction.atomic():
        # Lock the user row so two simultaneous submits can't both pass the count.
        User.objects.select_for_update().get(pk=creator.pk)
        # Count Owner roles, not created_by, so transferring ownership away doesn't free a slot.
        owned = OrganizationMembership.objects.filter(
            user=creator, role=OrganizationMembership.Role.OWNER
        ).count()
        if owned >= MAX_OWNED_ORGANIZATIONS:
            raise ValidationError(f'You can own up to {MAX_OWNED_ORGANIZATIONS} organizations.')
        return Organization.objects.create(
            name=name, slug=_unique_organization_slug(name), org_type=org_type, description=description,
            logo=logo or '', contact_email=contact_email, website_url=website_url or None,
            instagram_url=instagram_url or None, created_by=creator,
        )


def update_organization_profile(*, actor, organization, name, org_type, description='', logo=None,
                                clear_logo=False, contact_email='', website_url=None, instagram_url=None):
    """FR-64: only the Owner edits the profile. The slug stays fixed so links keep working."""
    if not user_can_manage_organization(actor, organization):
        raise PermissionDenied('Only the organization Owner can edit the profile.')
    organization.name = name
    organization.org_type = org_type
    organization.description = description
    organization.contact_email = contact_email
    organization.website_url = website_url or None
    organization.instagram_url = instagram_url or None
    if logo:
        organization.logo = logo
    elif clear_logo:
        organization.logo = ''
    organization.save()
    return organization


def request_organization_verification(*, actor, organization, note=''):
    """Owner asks Platform Admins to verify the organization. One pending request at a time."""
    if not user_can_manage_organization(actor, organization):
        raise PermissionDenied('Only the organization Owner can request verification.')
    if organization.is_verified:
        raise ValidationError('This organization is already verified.')
    if not organization.contact_email or not (organization.website_url or organization.instagram_url):
        raise ValidationError('Add an organization email and a website or social media link first.')
    try:
        with transaction.atomic():
            return OrganizationVerificationRequest.objects.create(
                organization=organization, requested_by=actor, note=note
            )
    except IntegrityError:
        raise ValidationError('A verification request is already pending.') from None


@transaction.atomic
def review_verification_request(*, reviewer, verification_request, approve, review_note=''):
    """Platform Admin decision (FR-66). Approving sets the organization's verified badge."""
    if not reviewer.is_staff:
        raise PermissionDenied('Only Platform Admins review verification requests.')
    locked = OrganizationVerificationRequest.objects.select_for_update().get(pk=verification_request.pk)
    if locked.status != OrganizationVerificationRequest.Status.PENDING:
        raise ValidationError('This request was already reviewed.')
    locked.status = (
        OrganizationVerificationRequest.Status.APPROVED if approve else OrganizationVerificationRequest.Status.REJECTED
    )
    locked.reviewed_by = reviewer
    locked.reviewed_at = timezone.now()
    locked.review_note = review_note
    locked.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_note'])
    if approve:
        Organization.objects.filter(pk=locked.organization_id).update(is_verified=True)
    return locked


def add_member_by_email(*, actor, organization, email, role):
    """Owner adds an existing campus-verified account. There are no pending invites to expire or revoke."""
    if not user_can_manage_members(actor, organization):
        raise PermissionDenied('Only the organization Owner can manage members.')
    email = email.strip().lower()
    user = User.objects.filter(is_active=True).filter(Q(email__iexact=email) | Q(campus_email__iexact=email)).first()
    if user is None:
        raise ValidationError('No Radar account uses that email. Ask them to sign up first.')
    if not user.is_campus_verified:
        raise ValidationError('That account has no verified campus email, so it cannot join an organization.')
    already = OrganizationMembership.objects.filter(organization=organization, user=user).exists()
    if already:
        raise ValidationError('That person is already a member. Change their role from the list instead.')
    with transaction.atomic():
        membership = add_organization_member(actor=actor, organization=organization, user=user, role=role)
        Notification.objects.create(
            user=user, organization=organization, type=Notification.Type.ORG_INVITE,
            payload={'role': membership.get_role_display()},
        )
    return membership


@transaction.atomic
def change_member_role(*, actor, membership, role):
    """Promote or demote between Admin and Check-in Staff. The Owner's role only changes by transfer."""
    if not user_can_manage_members(actor, membership.organization):
        raise PermissionDenied('Only the organization Owner can manage members.')
    if role not in {OrganizationMembership.Role.ADMIN, OrganizationMembership.Role.CHECKIN_STAFF}:
        raise ValidationError('Choose Admin or Check-in Staff.')
    if membership.role == OrganizationMembership.Role.OWNER:
        raise ValidationError('Transfer ownership to change the Owner.')
    if membership.role == role:
        return membership
    if role == OrganizationMembership.Role.ADMIN:
        # Admins check in as hosts, so per-event staff assignments no longer apply.
        EventCheckInStaff.objects.filter(
            user_id=membership.user_id, event__organization_id=membership.organization_id
        ).delete()
    membership.role = role
    membership.save(update_fields=['role', 'updated_at'])
    return membership
