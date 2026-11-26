from django.utils import timezone

from .emails import send_after_commit
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


def wants(user, notification_type, channel: str) -> bool:
    """True unless the user switched this kind of update off in Preferences. `channel` is 'app' or 'email'.

    Types with no Preferences row, such as an organization invite, are in-app only. Without a saved
    profile the Preferences defaults apply: everything on, except email for new events.
    """
    from apps.accounts.models import Profile
    from apps.accounts.selectors import get_preferences

    key = PREFERENCE_FOR_TYPE.get(notification_type)
    if key is None:
        return channel == 'app'
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        profile = Profile(user=user)  # unsaved: the Preferences defaults
    return get_preferences(profile)['notifications'][key][channel]


def wants_in_app(user, notification_type) -> bool:
    return wants(user, notification_type, 'app')


def wants_email(user, notification_type) -> bool:
    return wants(user, notification_type, 'email')


def notify(*, user, type, event=None, organization=None, payload=None) -> Notification | None:
    """Send one update the ways the user's Preferences allow: an in-app notification and/or an email.

    Returns the in-app notification, or None when "In app" is off (an email may still go out).
    """
    fields = dict(user=user, type=type, event=event, organization=organization, payload=payload or {})
    notification = Notification.objects.create(**fields) if wants_in_app(user, type) else None
    if wants_email(user, type):
        send_after_commit([(user, notification or Notification(**fields))])
    return notification


def notify_followers_of_new_event(*, event, actor=None) -> int:
    """FR-59: tell an organization's followers it published an event. Returns how many in-app notifications.

    Skips personal events and unlisted events, muted follows, deleted accounts and the person who published it.
    Followers who turned on email for new events also get an email.
    """
    from apps.events.models import Event
    from apps.organizations.models import OrganizationFollow

    if not event.organization_id or event.visibility == Event.Visibility.UNLISTED:
        return 0
    follows = (
        OrganizationFollow.objects.filter(organization_id=event.organization_id, notify=True, user__is_active=True)
        .select_related('user__profile', 'organization')
    )
    if actor is not None and getattr(actor, 'pk', None):
        follows = follows.exclude(user_id=actor.pk)
    rows, emails = [], []
    for follow in follows:
        notification = Notification(user=follow.user, type=Type.FOLLOWED_ORG_NEW_EVENT, event=event,
                                    organization=follow.organization)
        if wants_in_app(follow.user, Type.FOLLOWED_ORG_NEW_EVENT):
            rows.append(notification)
        if wants_email(follow.user, Type.FOLLOWED_ORG_NEW_EVENT):
            emails.append((follow.user, notification))
    Notification.objects.bulk_create(rows)
    send_after_commit(emails)
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
