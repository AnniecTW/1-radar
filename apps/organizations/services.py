from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils.text import slugify

from .models import Organization, OrganizationFollow, OrganizationMembership
from .permissions import user_can_manage_members, user_can_manage_organization


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
        membership.role = role
        membership.invited_by = actor
        membership.save(update_fields=['role', 'invited_by', 'updated_at'])
    return membership


def remove_organization_member(*, actor, membership):
    if not user_can_manage_members(actor, membership.organization):
        raise PermissionDenied('Only the organization Owner can remove members.')
    if membership.role == OrganizationMembership.Role.OWNER:
        raise ValidationError('Transfer ownership before removing the Owner.')
    membership.delete()


@transaction.atomic
def transfer_organization_ownership(*, actor, organization_id, new_owner_id):
    organization = Organization.objects.select_for_update().get(pk=organization_id)
    current_owner = OrganizationMembership.objects.select_for_update().get(
        organization=organization, user=actor, role=OrganizationMembership.Role.OWNER
    )
    new_owner = OrganizationMembership.objects.select_for_update().get(
        organization=organization, user_id=new_owner_id
    )
    if not new_owner.user.is_campus_verified:
        raise ValidationError('The new Owner must have a verified campus email.')
    if new_owner.pk == current_owner.pk:
        return current_owner

    current_owner.role = OrganizationMembership.Role.ADMIN
    current_owner.save(update_fields=['role', 'updated_at'])
    new_owner.role = OrganizationMembership.Role.OWNER
    new_owner.save(update_fields=['role', 'updated_at'])
    return new_owner


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
