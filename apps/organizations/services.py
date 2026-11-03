from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F

from .models import Organization, OrganizationFollow, OrganizationMembership
from .permissions import user_can_manage_members


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

