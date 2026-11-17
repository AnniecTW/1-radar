from apps.events.models import EventCheckInStaff
from apps.organizations.permissions import user_can_manage_events


def user_can_check_in_attendees(user, event):
    if not getattr(user, 'is_authenticated', False):
        return False
    if event.organization_id is None:
        return event.host_user_id == user.pk
    if user_can_manage_events(user, event.organization):
        return True
    return EventCheckInStaff.objects.filter(event=event, user=user).exists()
