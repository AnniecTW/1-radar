from django.urls import reverse

from .models import Notification

Type = Notification.Type


def describe_notification(notification: Notification) -> dict:
    """The headline, detail line and link for one row, built from its type and payload."""
    event = notification.event
    organization = notification.organization
    title = event.title if event else 'an event'
    org_name = organization.name if organization else 'An organization'
    payload = notification.payload or {}
    detail = ''

    if notification.type == Type.RSVP_CONFIRMED:
        headline = f"You're going to {title}"
    elif notification.type == Type.WAITLIST_JOINED:
        headline = f"You're on the waitlist for {title}"
        if payload.get('position'):
            detail = f"Your position is {payload['position']}."
    elif notification.type == Type.WAITLIST_PROMOTED:
        headline = f"A spot opened up. You're going to {title}"
    elif notification.type == Type.WAITLIST_HEADS_UP:
        headline = f"You're still on the waitlist for {title}"
        detail = 'The event is about a day away.'
    elif notification.type == Type.WAITLIST_CLOSED:
        headline = f'The waitlist for {title} is now closed'
    elif notification.type == Type.EVENT_UPDATED:
        headline = f'{title} was updated'
        if payload.get('changed'):
            detail = f"The {payload['changed']} changed."
    elif notification.type == Type.EVENT_CANCELLED:
        headline = f'{title} was cancelled'
        detail = payload.get('reason', '')
    elif notification.type == Type.REMINDER:
        headline = f'{title} starts soon'
    elif notification.type == Type.ORG_INVITE:
        headline = f'{org_name} invited you to join their team'
    elif notification.type == Type.FOLLOWED_ORG_NEW_EVENT:
        headline = f'{org_name} posted a new event: {title}'
    else:
        headline = notification.get_type_display()

    if event:
        url = reverse('event_detail', args=[event.slug])
    elif organization:
        url = reverse('show_organization_profile', args=[organization.slug])
    else:
        url = reverse('list_notifications')
    return {
        'notification': notification,
        'headline': headline,
        'detail': detail,
        'url': url,
        'is_unread': notification.read_at is None,
    }
