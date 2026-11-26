"""Notification emails (FR-48, FR-59).

Each email repeats the in-app headline, adds the event's time and place, and links to the event and to
Preferences. Emails go out after the database transaction commits, so a rolled-back RSVP or edit never
sends one, and a mail server problem is logged instead of breaking the page.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMessage, mailers
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .presentation import describe_notification

logger = logging.getLogger(__name__)


def absolute_url(path: str) -> str:
    return settings.SITE_URL.rstrip('/') + path


def _when_and_where(event) -> list[str]:
    from apps.discovery.selectors import get_campus_timezone

    lines = []
    if event.start_at:
        start = timezone.localtime(event.start_at, get_campus_timezone())
        lines.append(f"When: {start:%a, %b} {start.day} · {start.hour % 12 or 12}:{start:%M %p}")
    place = ', '.join(part for part in [event.venue.name if event.venue else '', event.location_text.strip()] if part)
    if place:
        lines.append(f'Where: {place}')
    return lines


def build_email(user, notification) -> EmailMessage:
    """One email for one (possibly unsaved) Notification."""
    described = describe_notification(notification)
    lines = [f"Hi {user.first_name or 'there'},", '', described['headline'] + '.']
    if described['detail']:
        lines.append(described['detail'])
    if notification.event is not None:
        lines += [''] + _when_and_where(notification.event)
    lines += [
        '',
        f"Open it on Radar: {absolute_url(described['url'])}",
        '',
        '—',
        f"You get this email because of your Radar notification settings. Change them: "
        f"{absolute_url(reverse('account_preferences'))}",
    ]
    return EmailMessage(subject=described['headline'], body='\n'.join(lines), to=[user.email])


def can_email(user) -> bool:
    return bool(user.is_active and user.email and user.is_email_verified)


def send_after_commit(pairs) -> None:
    """Email each (user, notification) pair once the current transaction commits, over one connection."""
    pairs = [(user, notification) for user, notification in pairs if can_email(user)]
    if pairs:
        transaction.on_commit(lambda: _send(pairs), robust=True)


def _send(pairs) -> None:
    messages = [build_email(user, notification) for user, notification in pairs]
    try:
        mailers.default.send_messages(messages)
    except Exception:
        logger.exception('Could not send %d notification email(s)', len(messages))
        return
    saved_ids = [notification.pk for _, notification in pairs if notification.pk]
    if saved_ids:
        from .models import Notification

        Notification.objects.filter(pk__in=saved_ids).update(emailed_at=timezone.now())
