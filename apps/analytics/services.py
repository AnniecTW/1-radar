from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum

from apps.events.models import Event
from apps.rsvps.models import RSVP

from .models import EventDailyStats
from .permissions import user_can_export_attendees, user_can_view_analytics


def get_event_analytics(*, actor, event_id):
    event = Event.objects.select_related('organization').get(pk=event_id)
    if not user_can_view_analytics(actor, event):
        raise PermissionDenied('You cannot view this event analytics.')
    daily_totals = EventDailyStats.objects.filter(event=event).aggregate(
        views=Sum('views'), unique_views=Sum('unique_views'), likes=Sum('likes'),
        saves=Sum('saves'), interested=Sum('interested'),
        outbound_clicks=Sum('outbound_clicks'), checkins=Sum('checkins'),
    )
    rsvp_counts = {
        row['status']: row['total']
        for row in RSVP.objects.filter(event=event).values('status').order_by().annotate(total=Count('id'))
    }
    return {'event': event, 'daily_totals': daily_totals, 'rsvp_counts': rsvp_counts}


def get_attendee_rows(*, actor, event_id):
    event = Event.objects.select_related('organization').get(pk=event_id)
    if not user_can_export_attendees(actor, event):
        raise PermissionDenied('You cannot export attendees for this event.')
    return RSVP.objects.filter(event=event, status=RSVP.Status.GOING).select_related('user', 'user__profile')
