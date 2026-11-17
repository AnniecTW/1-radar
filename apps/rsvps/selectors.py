from datetime import datetime, timedelta

from django.db.models import Exists, OuterRef, QuerySet

from apps.attendance.models import CheckIn
from apps.events.models import Event

from .models import RSVP


def list_upcoming_tickets(user, now: datetime) -> QuerySet[RSVP]:
    """The user's Going and Waitlisted RSVPs for events that haven't ended, soonest first."""
    return (
        RSVP.objects.filter(
            user=user,
            status__in=[RSVP.Status.GOING, RSVP.Status.WAITLISTED],
            event__status=Event.Status.PUBLISHED,
            event__end_at__gt=now,
        )
        .select_related('event', 'event__organization', 'event__venue')
        .order_by('event__start_at')
    )


def list_past_rsvps(user, now: datetime) -> QuerySet[RSVP]:
    """Going RSVPs for ended events, newest first, each marked with whether the user checked in."""
    checked_in = CheckIn.objects.filter(user=user, event=OuterRef('event'))
    return (
        RSVP.objects.filter(user=user, status=RSVP.Status.GOING, event__end_at__lte=now)
        .select_related('event', 'event__organization', 'event__venue')
        .annotate(attended=Exists(checked_in))
        .order_by('-event__start_at')
    )


# Automatic waitlist promotion stops this long before an event starts (FR-82).
WAITLIST_CUTOFF = timedelta(minutes=30)


def get_rsvp_state(user, event: Event, now: datetime) -> dict:
    """Which RSVP button a person sees for an event (FR-76). Shared by every page that shows one."""
    if event.status == Event.Status.CANCELLED:
        return {'state': 'cancelled'}
    if event.status != Event.Status.PUBLISHED or event.end_at <= now:
        return {'state': 'ended'}
    if not event.is_free:
        return {'state': 'paid'}
    if not user.is_authenticated:
        return {'state': 'guest'}

    rsvp = RSVP.objects.filter(event=event, user=user).first()
    if rsvp and rsvp.status == RSVP.Status.GOING:
        return {'state': 'going'}
    if rsvp and rsvp.status == RSVP.Status.WAITLISTED:
        return {'state': 'waitlisted', 'position': rsvp.waitlist_position}
    if rsvp and rsvp.status == RSVP.Status.INTERESTED:
        return {'state': 'interested'}

    if not user.is_email_verified:
        return {'state': 'unverified'}
    if event.visibility == Event.Visibility.CAMPUS_ONLY and not user.is_campus_verified:
        return {'state': 'campus_required'}
    if not event.rsvp_required:
        return {'state': 'drop_in'}
    going = RSVP.objects.filter(event=event, status=RSVP.Status.GOING).count()
    if event.capacity is not None and going >= event.capacity:
        if event.waitlist_enabled and now < event.start_at - WAITLIST_CUTOFF:
            return {'state': 'join_waitlist'}
        return {'state': 'full'}
    return {'state': 'rsvp'}
