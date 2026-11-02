from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.accounts.models import CampusDomain
from apps.events.models import Event
from apps.events.selectors import filter_discoverable_events
from apps.interests.models import Interest
from apps.organizations.models import Organization
from apps.rsvps.models import RSVP

CAROUSEL_SIZE = 10
BROWSE_GRID_SIZE = 12
FEATURED_ORGANIZATION_COUNT = 6
TRENDING_WINDOW_DAYS = 14
MAP_POINT_LIMIT = 300
SATURDAY = 5


def get_active_campus_domain() -> CampusDomain | None:
    return CampusDomain.objects.filter(is_active=True).order_by('id').first()


def get_campus_timezone() -> ZoneInfo:
    campus_domain = get_active_campus_domain()
    return ZoneInfo(campus_domain.timezone if campus_domain else settings.TIME_ZONE)


def get_campus_center() -> tuple[float, float] | None:
    """Return (latitude, longitude) of the campus map center."""
    campus_domain = get_active_campus_domain()
    if campus_domain is None or campus_domain.center_point is None:
        return None
    return campus_domain.center_point.y, campus_domain.center_point.x


def list_upcoming_events(now: datetime) -> QuerySet[Event]:
    """Discoverable events that have not ended yet, with the counts the cards show."""
    going = Count('rsvps', filter=Q(rsvps__status=RSVP.Status.GOING), distinct=True)
    interested = Count('rsvps', filter=Q(rsvps__status=RSVP.Status.INTERESTED), distinct=True)
    return (
        filter_discoverable_events(Event.objects.filter(end_at__gt=now))
        .select_related('organization', 'venue')
        .prefetch_related('interests')
        .annotate(going_count=going, interested_count=interested)
    )


def get_happening_today_events(now: datetime, campus_timezone: ZoneInfo) -> list[Event]:
    """Events that start today (campus time) or are already running, by start time."""
    local_now = now.astimezone(campus_timezone)
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    starts_today = Q(start_at__gte=day_start, start_at__lt=day_end)
    already_running = Q(start_at__lte=now)
    events = list_upcoming_events(now).filter(starts_today | already_running).order_by('start_at')
    return list(events[:CAROUSEL_SIZE])


def get_weekend_window(now: datetime, campus_timezone: ZoneInfo) -> tuple[datetime, datetime]:
    """Saturday 00:00 to Monday 00:00 of the current weekend, or the coming one."""
    local_now = now.astimezone(campus_timezone)
    days_until_saturday = SATURDAY - local_now.weekday()
    # Sunday is weekday 6, so this reaches back to the Saturday that just passed.
    saturday = local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        days=days_until_saturday
    )
    return saturday, saturday + timedelta(days=2)


def get_weekend_events(now: datetime, campus_timezone: ZoneInfo) -> list[Event]:
    weekend_start, weekend_end = get_weekend_window(now, campus_timezone)
    events = list_upcoming_events(now).filter(
        start_at__gte=weekend_start, start_at__lt=weekend_end
    ).order_by('start_at')
    return list(events[:CAROUSEL_SIZE])


def get_trending_events(now: datetime) -> list[Event]:
    """Most popular events starting in the next 14 days, so far-off events don't crowd out near ones."""
    window_end = now + timedelta(days=TRENDING_WINDOW_DAYS)
    events = list_upcoming_events(now).filter(start_at__gt=now, start_at__lt=window_end).order_by(
        '-popularity_score', 'start_at'
    )
    return list(events[:CAROUSEL_SIZE])


def list_category_interests() -> list[Interest]:
    return list(Interest.objects.filter(is_active=True).order_by('name'))


def list_browse_events(now: datetime, category_slug: str, search_text: str) -> list[Event]:
    """Grid below the category chips. Keyword matching until AI search is built (FR-47)."""
    events = list_upcoming_events(now)
    if category_slug:
        events = events.filter(interests__slug=category_slug)
    if search_text:
        events = events.filter(
            Q(title__icontains=search_text)
            | Q(description__icontains=search_text)
            | Q(location_text__icontains=search_text)
            | Q(venue__name__icontains=search_text)
            | Q(organization__name__icontains=search_text)
            | Q(interests__name__icontains=search_text)
        )
    return list(events.distinct().order_by('start_at')[:BROWSE_GRID_SIZE])


def list_featured_organizations(now: datetime) -> list[Organization]:
    upcoming = filter_discoverable_events(Event.objects.filter(end_at__gt=now))
    organizations = Organization.objects.annotate(
        upcoming_event_count=Count('events', filter=Q(events__in=upcoming), distinct=True)
    )
    active = organizations.filter(Q(upcoming_event_count__gt=0) | Q(follower_count__gt=0))
    return list(active.order_by('-follower_count', '-upcoming_event_count', 'name')[:FEATURED_ORGANIZATION_COUNT])


def get_map_points(now: datetime) -> list[dict]:
    """Event positions weighted by popularity for the heat map preview."""
    rows = (
        filter_discoverable_events(Event.objects.filter(end_at__gt=now, location__isnull=False))
        .order_by('start_at')
        .values_list('title', 'location', 'popularity_score')[:MAP_POINT_LIMIT]
    )
    return [
        {'title': title, 'lat': point.y, 'lng': point.x, 'weight': 1 + score}
        for title, point, score in rows
    ]
