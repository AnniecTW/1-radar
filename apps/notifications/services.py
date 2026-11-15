from django.utils import timezone

from .models import Notification

Type = Notification.Type

# Which Preferences row (accounts.selectors.NOTIFICATION_UPDATES) controls each type.
# Types not listed here, such as an organization invite, are always delivered.
PREFERENCE_FOR_TYPE = {
    Type.RSVP_CONFIRMED: 'rsvp',
    Type.REMINDER: 'reminders',
    Type.WAITLIST_JOINED: 'waitlist',
    Type.WAITLIST_PROMOTED: 'waitlist',
    Type.WAITLIST_HEADS_UP: 'waitlist',
    Type.WAITLIST_CLOSED: 'waitlist',
    Type.EVENT_UPDATED: 'changes',
    Type.EVENT_CANCELLED: 'changes',
    Type.FOLLOWED_ORG_NEW_EVENT: 'new_events',
}


def wants_in_app(user, notification_type) -> bool:
    """True unless the user switched off "In app" for this kind of update in Preferences."""
    from apps.accounts.models import Profile
    from apps.accounts.selectors import get_preferences

    key = PREFERENCE_FOR_TYPE.get(notification_type)
    if key is None:
        return True
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        return True
    return get_preferences(profile)['notifications'][key]['app']


def notify(*, user, type, event=None, organization=None, payload=None) -> Notification | None:
    """Create an in-app notification if the user's Preferences allow it; returns None when skipped."""
    if not wants_in_app(user, type):
        return None
    return Notification.objects.create(
        user=user, type=type, event=event, organization=organization, payload=payload or {}
    )


def notify_followers_of_new_event(*, event, actor=None) -> int:
    """FR-59: tell an organization's followers it published an event. Returns how many were notified.

    Skips personal events and unlisted events, muted follows, deleted accounts and the person who published it.
    """
    from apps.events.models import Event
    from apps.organizations.models import OrganizationFollow

    if not event.organization_id or event.visibility == Event.Visibility.UNLISTED:
        return 0
    follows = (
        OrganizationFollow.objects.filter(organization_id=event.organization_id, notify=True, user__is_active=True)
        .select_related('user__profile')
    )
    if actor is not None and getattr(actor, 'pk', None):
        follows = follows.exclude(user_id=actor.pk)
    rows = [
        Notification(user=follow.user, type=Type.FOLLOWED_ORG_NEW_EVENT, event=event,
                     organization_id=event.organization_id)
        for follow in follows
        if wants_in_app(follow.user, Type.FOLLOWED_ORG_NEW_EVENT)
    ]
    Notification.objects.bulk_create(rows)
    return len(rows)


def mark_notification_read(*, user, notification_id: int) -> Notification:
    """Only the owner can mark a notification; anyone else gets DoesNotExist."""
    notification = Notification.objects.select_related('event', 'organization').get(pk=notification_id, user=user)
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=['read_at'])
    return notification


def mark_all_notifications_read(*, user) -> int:
    return Notification.objects.filter(user=user, read_at__isnull=True).update(read_at=timezone.now())
