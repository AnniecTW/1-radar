from datetime import datetime

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
