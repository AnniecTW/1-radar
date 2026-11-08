from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.accounts.models import CampusDomain, User
from apps.engagement.models import EventSave
from apps.events.models import Event
from apps.events.selectors import filter_discoverable_events
from apps.interests.models import Interest
from apps.organizations.models import Organization
from apps.rsvps.models import RSVP

from .constants import (
    CATEGORY_CHIP_COUNT,
    MIN_SIGNUPS_TO_SHOW,
    SIGNUP_WINDOW_DAYS,
    WEEKEND_SUMMARY_ROWS,
)

CAROUSEL_SIZE = 10
HERO_SLIDE_COUNT = 5
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


def list_recommended_events(user, now: datetime) -> list[Event]:
    """Upcoming events in the user's interests, most popular first. Empty when they picked none."""
    interest_ids = user.interests.values_list('interest_id', flat=True)
    events = list_upcoming_events(now).filter(interests__in=interest_ids).distinct()
    return list(events.order_by('-popularity_score', 'start_at')[:CAROUSEL_SIZE])


def list_saved_event_ids(user, events: list[Event]) -> set:
    """Which of these events the user saved, in one query for every card on the page."""
    event_ids = {event.pk for event in events}
    return set(EventSave.objects.filter(user=user, event_id__in=event_ids).values_list('event_id', flat=True))


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


def search_browse_events(now: datetime, category_slug: str, search_text: str) -> tuple[list[Event], bool]:
    """Rank eligible events in PostgreSQL using the pgvector cosine operator."""
    from django.conf import settings
    from pgvector.django import CosineDistance
    from apps.events.semantic_search import EmbeddingError, embed_text

    try:
        query_vector = embed_text(search_text)
    except EmbeddingError:
        import logging
        logging.getLogger(__name__).info("Semantic search unavailable; using keyword search")
        return list_browse_events(now, category_slug, search_text), True

    events = list_upcoming_events(now)
    if category_slug:
        events = events.filter(interests__slug=category_slug)
    min_similarity = getattr(settings, "CLOUDFLARE_SEMANTIC_MIN_SIMILARITY", 0.58)
    if not 0 <= min_similarity <= 1:
        min_similarity = 0.58
    import logging
    logger = logging.getLogger(__name__)
    ranked = (events.filter(embedding__isnull=False).distinct()
              .annotate(cosine_distance=CosineDistance("embedding", query_vector))
              .order_by("cosine_distance", "-popularity_score", "start_at"))
    # Record a bounded, privacy-safe sample for relevance calibration. Do not log query text.
    scored_candidates = list(ranked[:20])
    shown = [event for event in scored_candidates
             if 1 - event.cosine_distance >= min_similarity][:BROWSE_GRID_SIZE]
    shown_ids = {str(event.pk) for event in shown}
    logger.warning(
        "Semantic search scores min_similarity=%.4f candidates=%s",
        min_similarity,
        [(str(event.pk), round(1 - event.cosine_distance, 4), str(event.pk) in shown_ids)
         for event in scored_candidates],
    )
    return shown, False


def list_featured_organizations(now: datetime) -> list[Organization]:
    upcoming = filter_discoverable_events(Event.objects.filter(end_at__gt=now))
    organizations = Organization.objects.annotate(
        upcoming_event_count=Count('events', filter=Q(events__in=upcoming), distinct=True)
    )
    active = organizations.filter(Q(upcoming_event_count__gt=0) | Q(follower_count__gt=0))
    return list(active.order_by('-follower_count', '-upcoming_event_count', 'name')[:FEATURED_ORGANIZATION_COUNT])


def get_map_points(now: datetime) -> list[dict]:
    """Event positions weighted by popularity for the heat map preview, with what its popup shows."""
    rows = (
        filter_discoverable_events(Event.objects.filter(end_at__gt=now, location__isnull=False))
        .order_by('start_at')
        .values_list('title', 'slug', 'location', 'popularity_score', 'start_at', 'venue__name', 'location_text')[
            :MAP_POINT_LIMIT
        ]
    )
    return [
        {
            'title': title, 'slug': slug, 'lat': point.y, 'lng': point.x, 'weight': 1 + score,
            'start': start_at.isoformat(), 'place': venue_name or location_text or '',
        }
        for title, slug, point, score, start_at, venue_name, location_text in rows
    ]


def split_category_chips(categories: list[Interest], now: datetime) -> tuple[list[Interest], list[Interest]]:
    """The busiest categories become chips; the rest go in the "More" menu. Both keep the given objects."""
    upcoming = filter_discoverable_events(Event.objects.filter(end_at__gt=now))
    counts = dict(
        Interest.objects.filter(pk__in=[category.pk for category in categories])
        .annotate(upcoming_count=Count('events', filter=Q(events__in=upcoming), distinct=True))
        .values_list('pk', 'upcoming_count')
    )
    ordered = sorted(categories, key=lambda category: (-counts.get(category.pk, 0), category.name))
    return ordered[:CATEGORY_CHIP_COUNT], ordered[CATEGORY_CHIP_COUNT:]


def get_weekend_summary(now: datetime, campus_timezone: ZoneInfo) -> dict:
    """How many events this weekend, overall and per category, for the side panel."""
    weekend_start, weekend_end = get_weekend_window(now, campus_timezone)
    weekend_events = filter_discoverable_events(
        Event.objects.filter(end_at__gt=now, start_at__gte=weekend_start, start_at__lt=weekend_end)
    )
    rows = (
        weekend_events.filter(interests__isnull=False)
        .values('interests__slug', 'interests__name')
        .annotate(event_count=Count('id', distinct=True))
        .order_by('-event_count', 'interests__name')[:WEEKEND_SUMMARY_ROWS]
    )
    return {
        'start': weekend_start,
        'last_day': weekend_end - timedelta(days=1),
        'total': weekend_events.count(),
        'categories': [
            {'slug': row['interests__slug'], 'name': row['interests__name'], 'count': row['event_count']}
            for row in rows
        ],
    }


def count_recent_signups(now: datetime) -> int | None:
    """New accounts in the last 30 days, or None when too few to be worth showing."""
    count = User.objects.filter(is_active=True, date_joined__gte=now - timedelta(days=SIGNUP_WINDOW_DAYS)).count()
    return count if count >= MIN_SIGNUPS_TO_SHOW else None


def get_card_highlight(event: Event, now: datetime, interest_ids: set, trending_ids: set) -> str:
    """One true sentence about why an event is worth a look, shown on its card. Empty when none applies."""
    if event.start_at <= now < event.end_at:
        return 'Happening right now'
    matching = [interest.name for interest in event.interests.all() if interest.pk in interest_ids]
    if matching:
        return f'Matches your interest in {matching[0]}'
    spots_left = (event.capacity - event.going_count) if event.capacity else None
    if spots_left is not None and 0 < spots_left <= max(3, event.capacity // 5):
        return f'Filling up: {spots_left} spot{"s" if spots_left != 1 else ""} left'
    if event.pk in trending_ids:
        return 'Trending on campus'
    if event.organization:
        return f'Hosted by {event.organization.name}'
    return ''


def label_card_highlights(event_lists: list[list[Event]], now: datetime, interest_ids: set, trending_ids: set) -> None:
    for events in event_lists:
        for event in events:
            event.highlight = get_card_highlight(event, now, interest_ids, trending_ids)
