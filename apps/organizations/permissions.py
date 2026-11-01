from .models import OrganizationMembership


def organization_role(user, organization):
    if not getattr(user, 'is_authenticated', False):
        return None
    membership = OrganizationMembership.objects.filter(
        organization=organization, user=user
    ).values_list('role', flat=True).first()
    return membership


def user_can_manage_members(user, organization):
    return organization_role(user, organization) == OrganizationMembership.Role.OWNER


def user_can_manage_organization(user, organization):
    return organization_role(user, organization) == OrganizationMembership.Role.OWNER


def user_can_manage_events(user, organization):
    return organization_role(user, organization) in {
        OrganizationMembership.Role.OWNER,
        OrganizationMembership.Role.ADMIN,
    }


def user_is_checkin_staff(user, organization):
    return organization_role(user, organization) == OrganizationMembership.Role.CHECKIN_STAFF
