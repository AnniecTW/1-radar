import math
import time
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from datetime import timedelta
from django.db.models import prefetch_related_objects

from apps.organizations.models import OrganizationFollow

from .recommendations import (
    LOCATION_COOKIE, discard_replaced_impressions, dismiss_recommendation, log_impressions, read_location,
    recommend_events, remember_location, round_location, undo_dismissal,
)
from .selectors import (
    get_campus_center,
    get_campus_timezone,
    get_home_event_lists,
    get_map_points,
    get_trending_events,
    HERO_SLIDE_COUNT,
    list_browse_events,
    list_category_interests,
    list_featured_organizations,
    list_saved_event_ids,
    count_recent_signups,
    get_weekend_summary,
    label_card_highlights,
    split_category_chips,
)

MAX_SEARCH_LENGTH = 100


def _map_date_filter_caption(date_filter, now):
    """Return a compact date range matching the map's existing date filters."""
    from .selectors import get_campus_timezone, get_weekend_window

    def format_range(start, end):
        if start.month == end.month and start.year == end.year:
            return f'{start.strftime("%b")} {start.day}–{end.day}'
        return f'{start.strftime("%b")} {start.day}–{end.strftime("%b")} {end.day}'

    if date_filter == 'today':
        date = timezone.localtime(now).date()
        return f'{date.strftime("%b")} {date.day}'
    if date_filter == 'weekend':
        start, end = get_weekend_window(now, get_campus_timezone())
        last_day = (end - timedelta(days=1)).date()
        return format_range(start.date(), last_day)
    if date_filter == 'week':
        campus_timezone = get_campus_timezone()
        local_now = now.astimezone(campus_timezone)
        week_start = (local_now - timedelta(days=local_now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        friday = (week_start + timedelta(days=4)).date()
        return format_range(week_start.date(), friday)
    return ''


def _map_events(request, bounds=None):
    from django.db.models import Count, Q
    from apps.events.models import Event
    from apps.events.selectors import filter_discoverable_events
    from apps.rsvps.models import RSVP

    now = timezone.now()
    qs = filter_discoverable_events(Event.objects.filter(end_at__gt=now, location__isnull=False))
    from django.contrib.gis.geos import Point
    from django.contrib.gis.measure import D
    from .selectors import get_campus_center
    walk_center = None
    if request.GET.get('walk') == '1' and _location_state(request, now)[0]:
        try:
            lat, lng = float(request.GET['lat']), float(request.GET['lng'])
            if not (-90 <= lat <= 90 and -180 <= lng <= 180): raise ValueError
            walk_center = round_location(lat, lng)  # The browser already snaps it; never trust that alone.
        except (KeyError, ValueError):
            walk_center = get_campus_center()
        if walk_center:
            qs = qs.filter(location__distance_lte=(Point(walk_center[1], walk_center[0], srid=4326), D(m=1250)))
    search_text = request.GET.get('q', '').strip()[:MAX_SEARCH_LENGTH]
    if search_text:
        from django.db.models import Q
        qs = qs.filter(Q(title__icontains=search_text) | Q(description__icontains=search_text)
            | Q(location_text__icontains=search_text) | Q(venue__name__icontains=search_text)
            | Q(organization__name__icontains=search_text) | Q(interests__name__icontains=search_text))
    if request.GET.get('free') == '1':
        qs = qs.filter(is_free=True)
    # Quick filters match keywords until events carry these as real attributes.
    for param, keyword in (('indoors', 'indoor'), ('quiet', 'quiet')):
        if request.GET.get(param) == '1':
            qs = qs.filter(Q(title__icontains=keyword) | Q(description__icontains=keyword)
                | Q(interests__name__icontains=keyword))
    category = request.GET.get('category', '')
    if category:
        qs = qs.filter(interests__slug=category)
    date = request.GET.get('date', 'weekend')
    if date == 'today':
        qs = qs.filter(start_at__date=now.date())
    elif date == 'weekend':
        from .selectors import get_weekend_window, get_campus_timezone
        start, end = get_weekend_window(now, get_campus_timezone())
        qs = qs.filter(start_at__gte=start, start_at__lt=end)
    elif date == 'week':
        from .selectors import get_campus_timezone
        campus_timezone = get_campus_timezone()
        local_now = now.astimezone(campus_timezone)
        week_start = (local_now - timezone.timedelta(days=local_now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        week_end = week_start + timezone.timedelta(days=5)
        qs = qs.filter(start_at__gte=week_start, start_at__lt=week_end)
    if bounds:
        west, south, east, north = bounds
        from django.contrib.gis.geos import Polygon
        visible_area = Polygon.from_bbox((west, south, east, north))
        visible_area.srid = 4326
        qs = qs.filter(location__within=visible_area)
    ordering = ('-popularity_score','start_at') if request.GET.get('sort') == 'popular' else ('start_at',)
    return qs.select_related('organization','venue').prefetch_related('interests').annotate(
        going_count=Count('rsvps',filter=Q(rsvps__status=RSVP.Status.GOING),distinct=True),
        interested_count=Count('rsvps',filter=Q(rsvps__status=RSVP.Status.INTERESTED),distinct=True),
    ).distinct().order_by(*ordering)[:300]


def _map_point(event) -> dict:
    """What a map pin needs: position, popularity, and the colour/icon of its first styled category."""
    from .constants import CATEGORY_STYLES, DEFAULT_CATEGORY_STYLE

    interests = list(event.interests.all())
    styled = next((interest for interest in interests if interest.slug in CATEGORY_STYLES), None)
    icon, tone = CATEGORY_STYLES[styled.slug] if styled else DEFAULT_CATEGORY_STYLE
    return {
        'id': str(event.pk), 'title': event.title, 'slug': event.slug,
        'lat': event.location.y, 'lng': event.location.x, 'start': event.start_at.isoformat(),
        'venue': event.venue.name if event.venue else event.location_text,
        'going': event.going_count, 'popularity': event.popularity_score,
        'icon': icon, 'tone': tone, 'category': styled.name if styled else (interests[0].name if interests else ''),
    }


def _map_results_context(request, events: list) -> dict:
    saved_event_ids = list_saved_event_ids(request.user, events) if request.user.is_authenticated else set()
    return {'events': events, 'saved_event_ids': saved_event_ids}


@require_GET
def show_explore_map(request):
    from .selectors import get_campus_center, list_category_interests
    selected_date = request.GET.get('date', 'weekend')
    now = timezone.now()
    location_allowed, shared_location = _location_state(request, now)
    events = list(_map_events(request))
    shell = {}
    if request.user.is_authenticated:
        from apps.accounts.views import get_account_shell_context
        shell = get_account_shell_context(request.user)
    with timezone.override(get_campus_timezone()):
        response = render(request,'discovery/explore_map.html',{
            **shell,
            **_map_results_context(request, events),
            'map_points':[_map_point(event) for event in events],
            'map_center':get_campus_center() or (40.102,-88.2272),'active_nav':'explore_map',
            'categories':list_category_interests(),'selected_category':request.GET.get('category',''),
            'selected_date':selected_date,
            'date_filter_captions':{key:_map_date_filter_caption(key, now) for key in ('today','weekend','week','all')},
            'date_filter_caption':_map_date_filter_caption(selected_date, now),
            'search_text':request.GET.get('q','')[:MAX_SEARCH_LENGTH], 'free_only':request.GET.get('free') == '1',
            'indoors_only':request.GET.get('indoors') == '1', 'quiet_only':request.GET.get('quiet') == '1',
            'walk_only':request.GET.get('walk') == '1' and location_allowed,
            'popular_sort':request.GET.get('sort') == 'popular',
            'maptiler_key':__import__('django.conf').conf.settings.MAPTILER_API_KEY,
            # "Don't use my location" greys out the crosshair and walk filter; otherwise the map opens on
            # the approximate location the user shared anywhere in Radar.
            'location_allowed':location_allowed, 'shared_location':shared_location,
        })
    return _forget_location_if_off(request, response, location_allowed)


@require_GET
def events_in_map_bounds(request):
    """Events inside the visible map area, as pins plus the result cards rendered by the same template as the page."""
    from django.template.loader import render_to_string
    raw=request.GET.get('bbox','').split(',')
    if len(raw)!=4: return JsonResponse({'error':'bbox required'},status=400)
    try: bounds=tuple(map(float,raw))
    except ValueError: return JsonResponse({'error':'invalid bbox'},status=400)
    events=list(_map_events(request,bounds))
    with timezone.override(get_campus_timezone()):
        cards_html = render_to_string('discovery/_map_results.html', _map_results_context(request, events), request=request)
    return JsonResponse({'events':[_map_point(event) for event in events], 'cards_html': cards_html})


def _log_search(search_text, ai, semantic, category_slug, events, started, now) -> str:
    """Log the search anonymously (apps/search/services.py) and return the query string for its result links,
    so opening a result can be counted as a click on this search."""
    from apps.search.services import click_token, log_search

    log = log_search(query=search_text, ai=ai, semantic=semantic, category=category_slug, events=events,
                     latency_ms=round((time.perf_counter() - started) * 1000), now=now)
    return '?' + urlencode({'ref': 'search', 's': click_token(log)}) if log else ''


def _read_search_request(request: HttpRequest) -> tuple[str, str]:
    """Return (search_text, search_error) from the hero search bar."""
    raw_search_text = request.GET.get('q', '').strip()
    if request.GET.get('q') and not raw_search_text:
        return '', 'Enter a search phrase.'
    if len(raw_search_text) > MAX_SEARCH_LENGTH:
        return '', f'Searches must be {MAX_SEARCH_LENGTH} characters or fewer.'
    return raw_search_text, ''


def _signed_in_context(request: HttpRequest, now, shown_events: list) -> dict:
    """The extras a signed-in user sees: the top bar's name, their location, and which cards they saved.
    "Recommended for you" isn't here: the page loads it afterwards (show_recommendations_row)."""
    from apps.accounts.selectors import location_is_allowed
    from apps.accounts.views import get_account_shell_context

    shell = get_account_shell_context(request.user)
    location_allowed = location_is_allowed(shell['profile'])
    return {
        **shell,
        'user_location': read_location(request, now) if location_allowed else None,
        'location_allowed': location_allowed,
        'interest_ids': set(request.user.interests.values_list('interest_id', flat=True)),
        'saved_event_ids': list_saved_event_ids(request.user, shown_events),
    }


def _render_recommendations_row(request: HttpRequest, now, location, location_allowed: bool,
                                replace: bool = False) -> str:
    """Rank, log the impressions and render "Recommended for you" with its location banner. `replace` drops
    the impressions of the row this one replaces (a quiet refresh right after the row loaded)."""
    recommended = recommend_events(request.user, now, location)
    if replace:
        discard_replaced_impressions(request.user, now)
    log_impressions(request.user, recommended, now)
    interest_ids = set(request.user.interests.values_list('interest_id', flat=True))
    label_card_highlights([recommended], now, interest_ids, {event.pk for event in get_trending_events(now)})
    context = {
        'recommended': recommended,
        'user_location': location,
        'location_allowed': location_allowed,
        'interest_ids': interest_ids,
        'saved_event_ids': list_saved_event_ids(request.user, recommended),
    }
    with timezone.override(get_campus_timezone()):
        return render_to_string('discovery/_recommendations.html', context, request=request)


@login_required
@require_GET
@never_cache
def show_recommendations_row(request: HttpRequest) -> HttpResponse:
    """The "Recommended for you" row as HTML, which the home page fetches once it is on screen
    (recommendations-row.js). Ranking takes about ten database queries; the rest of the page doesn't wait."""
    now = timezone.now()
    location_allowed, location = _location_state(request, now)
    return HttpResponse(_render_recommendations_row(request, now, location, location_allowed))


def _location_state(request: HttpRequest, now) -> tuple[bool, tuple[float, float] | None]:
    """(may Radar use location, the approximate location this user shared). Guests can always use the
    map's own location controls; only signed-in users have a setting and a shared location."""
    if not request.user.is_authenticated:
        return True, None
    from apps.accounts.selectors import location_is_allowed
    from apps.accounts.services import get_or_create_profile

    if not location_is_allowed(get_or_create_profile(request.user)):
        return False, None
    return True, read_location(request, now)


def _forget_location_if_off(request: HttpRequest, response: HttpResponse, location_allowed: bool) -> HttpResponse:
    """Location was turned off after it was shared: remove what this browser still holds."""
    if not location_allowed and LOCATION_COOKIE in request.COOKIES:
        response.delete_cookie(LOCATION_COOKIE)
    return response


def _location_off_response() -> JsonResponse:
    response = JsonResponse({'error': 'location is turned off'}, status=403)
    response.delete_cookie(LOCATION_COOKIE)
    return response


def _read_coordinates(request: HttpRequest) -> tuple[float, float] | None:
    try:
        latitude, longitude = float(request.POST['lat']), float(request.POST['lng'])
    except (KeyError, ValueError):
        return None
    if not (math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90
            and -180 <= longitude <= 180):
        return None
    return latitude, longitude


@login_required
@require_POST
def share_location(request: HttpRequest) -> JsonResponse:
    """Share once, used everywhere: the Explore Map's crosshair and walk filter save the same approximate
    location as the home page's banner, so recommendations use it too."""
    now = timezone.now()
    if not _location_state(request, now)[0]:
        return _location_off_response()
    coordinates = _read_coordinates(request)
    if coordinates is None:
        return JsonResponse({'error': 'valid lat and lng are required'}, status=400)
    location = round_location(*coordinates)
    response = JsonResponse({'location': {'lat': location[0], 'lng': location[1]}})
    remember_location(response, request, location, now)
    return response


@login_required
@require_POST
def set_recommendation_location(request: HttpRequest) -> JsonResponse:
    """The browser shares the user's location for "Recommended for you". It is snapped to a ~500 m grid and
    kept in a six-hour cookie on the user's device, and the re-ranked row comes back as HTML to swap in place.
    `replace=1` marks a quiet refresh right after page load, whose new row replaces the impressions that page
    just logged. Refused when the user chose "Don't use my location"."""
    now = timezone.now()
    if not _location_state(request, now)[0]:
        return _location_off_response()
    coordinates = _read_coordinates(request)
    if coordinates is None:
        return JsonResponse({'error': 'valid lat and lng are required'}, status=400)
    location = round_location(*coordinates)
    html = _render_recommendations_row(request, now, location, True, replace=request.POST.get('replace') == '1')
    response = JsonResponse({'html': html, 'location': {'lat': location[0], 'lng': location[1]}})
    remember_location(response, request, location, now)
    return response


@login_required
@require_POST
def dismiss_recommendation_view(request: HttpRequest, event_id) -> HttpResponse:
    """"Not interested" on a Recommended card (FR-43), or `undo=1` from the "Hidden" message.
    recommendation-dismiss.js sends it in the background; without JavaScript the form posts and lands back
    on the home page, where the row no longer has the event."""
    from apps.events.models import Event

    event = get_object_or_404(Event, pk=event_id)
    undo = request.POST.get('undo') == '1'
    if undo:
        undo_dismissal(request.user, event)
    else:
        try:
            rank = max(0, min(int(request.POST.get('rank', 0)), 32767))
        except ValueError:
            rank = 0
        dismiss_recommendation(request.user, event, timezone.now(), rank)
    if 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({'dismissed': not undo})
    return redirect(f"{reverse('dashboard')}#recommendations")


@login_required
@require_POST
def turn_off_recommendation_location(request: HttpRequest) -> JsonResponse:
    """"Don't ask again" on the location banner: switches Account & privacy to "Don't use my location"."""
    from apps.accounts.services import turn_off_location

    turn_off_location(user=request.user)
    response = JsonResponse({'location': 'off'})
    response.delete_cookie(LOCATION_COOKIE)
    return response


@require_http_methods(['GET'])
def show_landing_page(request: HttpRequest) -> HttpResponse:
    """The home page (FR-50). Guests and signed-in users share one layout; only the actions differ."""
    now = timezone.now()
    campus_timezone = get_campus_timezone()
    categories = list_category_interests()
    category_slug = request.GET.get('category', '')
    if category_slug not in {interest.slug for interest in categories}:
        category_slug = ''
    search_text, search_error = _read_search_request(request)
    semantic_search = request.GET.get('semantic') == '1'
    home_lists = get_home_event_lists(now, campus_timezone, category_slug, include_browse=not search_text)
    started = time.perf_counter()
    semantic = None
    if search_text and semantic_search:
        from .selectors import search_browse_events
        semantic = search_browse_events(now, category_slug, search_text)
        browse_events = semantic.events
    else:
        browse_events = home_lists['browse'] if 'browse' in home_lists else list_browse_events(now, category_slug, search_text)
    keyword_fallback = bool(semantic and semantic.fallback)
    search_link_query = ''
    if search_text:
        search_link_query = _log_search(search_text, semantic_search, semantic, category_slug,
                                        browse_events, started, now)

    trending = home_lists['trending']
    chip_categories, more_categories = split_category_chips(categories, now)
    context = {
        'active_nav': 'discover',
        'featured_events': trending[:HERO_SLIDE_COUNT],
        'happening_today': home_lists['today'],
        'this_weekend': home_lists['weekend'],
        'trending': trending,
        'chip_categories': chip_categories,
        'more_categories': more_categories,
        'selected_category': next((interest for interest in categories if interest.slug == category_slug), None),
        'search_text': search_text,
        'semantic_search': semantic_search,
        # Keeps the top bar's search filled in with what produced these results.
        'topbar_search': {'q': search_text, 'semantic': semantic_search, 'category': category_slug},
        'browse_events': browse_events,
        'search_error': search_error,
        'keyword_fallback': keyword_fallback,
        'search_link_query': search_link_query,
        'featured_organizations': list_featured_organizations(now),
        'map_points': get_map_points(now),
        'map_center': get_campus_center(),
        'maptiler_key': settings.MAPTILER_API_KEY,
        'weekend_summary': get_weekend_summary(now, campus_timezone),
        'recent_signups': count_recent_signups(now),
    }
    # The carousels and the grid share many events, so their interest chips are loaded in one query.
    prefetch_related_objects(context['happening_today'] + context['this_weekend'] + trending + browse_events, 'interests')
    if request.user.is_authenticated:
        shown_events = context['happening_today'] + context['this_weekend'] + trending + browse_events
        context.update(_signed_in_context(request, now, shown_events))
        # One query for every Follow button in "Organizations to follow", not one per button.
        context['followed_organization_ids'] = set(
            OrganizationFollow.objects.filter(user=request.user, organization__in=context['featured_organizations'])
            .values_list('organization_id', flat=True)
        )
    card_lists = [context['happening_today'], context['this_weekend'], trending, browse_events]
    label_card_highlights(card_lists, now, context.get('interest_ids', set()), {event.pk for event in trending})
    # Dates render in campus time, not the server's UTC.
    with timezone.override(campus_timezone):
        response = render(request, 'discovery/landing.html', context)
    return _forget_location_if_off(request, response, context.get('location_allowed', True))
