from apps.organizations.permissions import user_can_manage_events


def user_can_view_analytics(user, event):
    if not getattr(user, 'is_authenticated', False):
        return False
    if event.organization_id is None:
        return event.host_user_id == user.pk
    return user_can_manage_events(user, event.organization)


def user_can_export_attendees(user, event):
    if not getattr(user, 'is_authenticated', False):
        return False
    if event.organization_id is None:
        return event.host_user_id == user.pk
    from apps.organizations.permissions import user_can_manage_members

    return user_can_manage_members(user, event.organization)
