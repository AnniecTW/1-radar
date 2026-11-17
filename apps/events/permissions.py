from apps.organizations.permissions import user_can_manage_events


def user_can_edit_event(user, event):
    if not getattr(user, 'is_authenticated', False):
        return False
    if event.organization_id is None:
        return event.host_user_id == user.pk
    return user_can_manage_events(user, event.organization)


def user_can_assign_checkin_staff(user, event):
    return bool(event.organization_id and user_can_manage_events(user, event.organization))
