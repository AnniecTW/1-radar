from datetime import timedelta
from urllib.parse import urlparse

from django.http import Http404

from apps.events.models import Event
from apps.rsvps.models import TrafficSource

from .models import EventLike, EventOutboundClick, EventSave, EventView

# A viewer who reloads or comes back within this window counts as one view.
VIEW_DEDUPE_WINDOW = timedelta(minutes=30)


def remove_saved_event(*, user, event_id) -> None:
    EventSave.objects.filter(user=user, event_id=event_id).delete()


def get_engageable_event(event_id) -> Event:
    """Saves, likes and ticket clicks only make sense on a live event."""
    event = Event.objects.filter(pk=event_id, status=Event.Status.PUBLISHED).first()
    if event is None:
        raise Http404
    return event


def set_event_saved(*, user, event, saved: bool) -> bool:
    """Save or unsave. Taking the wanted state (not a toggle) makes double clicks harmless."""
    if saved:
        EventSave.objects.get_or_create(user=user, event=event)
    else:
        EventSave.objects.filter(user=user, event=event).delete()
    return saved


def set_event_liked(*, user, event, liked: bool) -> bool:
    if liked:
        EventLike.objects.get_or_create(user=user, event=event)
    else:
        EventLike.objects.filter(user=user, event=event).delete()
    return liked


def guess_view_source(referer: str, host: str) -> str:
    """Where a visit came from, for the host's "Where views came from" chart (FR-37)."""
    if not referer:
        return TrafficSource.DIRECT
    parsed = urlparse(referer)
    if parsed.netloc and parsed.netloc != host:
        return TrafficSource.DIRECT
    path, query = parsed.path or '/', parsed.query
    if path.startswith('/explore') or path.startswith('/api/map-events'):
        return TrafficSource.MAP
    if 'q=' in query:
        return TrafficSource.SEARCH
    if path.startswith('/organizations/'):
        return TrafficSource.ORG_PAGE
    if path.startswith('/accounts/profile') and 'tab=following' in query:
        return TrafficSource.FOLLOWING
    if path == '/':
        return TrafficSource.FEED
    return TrafficSource.DIRECT


def record_event_view(*, event, user, session_key, source, now) -> bool:
    """Log one view. Returns False when it's a repeat from the same viewer within the window."""
    viewer = {'user': user} if user else {'user__isnull': True, 'session_key': session_key}
    recent = EventView.objects.filter(event=event, created_at__gte=now - VIEW_DEDUPE_WINDOW, **viewer)
    if recent.exists():
        return False
    EventView.objects.create(event=event, user=user, session_key='' if user else session_key, source=source)
    return True


def record_outbound_click(*, event, user, session_key, kind) -> None:
    EventOutboundClick.objects.create(
        event=event, user=user, session_key='' if user else session_key, kind=kind
    )
