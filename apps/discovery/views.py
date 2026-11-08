from django.http import HttpRequest, HttpResponse
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from datetime import timedelta

from radar.views import dashboard

from .selectors import (
    get_campus_center,
    get_campus_timezone,
    get_happening_today_events,
    get_map_points,
    get_trending_events,
    get_weekend_events,
    list_browse_events,
    list_category_interests,
    list_featured_organizations,
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
    if request.GET.get('walk') == '1':
        try:
            lat, lng = float(request.GET['lat']), float(request.GET['lng'])
            if not (-90 <= lat <= 90 and -180 <= lng <= 180): raise ValueError
            walk_center = (lat, lng)
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
        qs = qs.filter(location__within=f' SRID=4326;POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))')
    ordering = ('-popularity_score','start_at') if request.GET.get('sort') == 'popular' else ('start_at',)
    return qs.select_related('organization','venue').prefetch_related('interests').annotate(
        going_count=Count('rsvps',filter=Q(rsvps__status=RSVP.Status.GOING),distinct=True),
        interested_count=Count('rsvps',filter=Q(rsvps__status=RSVP.Status.INTERESTED),distinct=True),
    ).distinct().order_by(*ordering)[:300]


@require_GET
def show_explore_map(request):
    from .selectors import get_campus_center, list_category_interests
    selected_date = request.GET.get('date', 'weekend')
    now = timezone.now()
    events = list(_map_events(request))
    points = [{'id':str(e.pk),'title':e.title,'slug':e.slug,'lat':e.location.y,'lng':e.location.x,
        'start':e.start_at.isoformat(),'venue':e.venue.name if e.venue else e.location_text,
        'going':e.going_count,'popularity':e.popularity_score,'cover':e.cover_image,
        'categories':[i.name for i in e.interests.all()]} for e in events]
    return render(request,'discovery/explore_map.html',{
        'events':events,'map_points':points,'map_center':get_campus_center() or (40.102,-88.2272),'active_nav':'explore_map',
        'categories':list_category_interests(),'selected_category':request.GET.get('category',''),
        'selected_date':selected_date,
        'date_filter_captions':{key:_map_date_filter_caption(key, now) for key in ('today','weekend','week','all')},
        'date_filter_caption':_map_date_filter_caption(selected_date, now),
        'search_text':request.GET.get('q','')[:MAX_SEARCH_LENGTH], 'free_only':request.GET.get('free') == '1',
        'walk_only':request.GET.get('walk') == '1', 'popular_sort':request.GET.get('sort') == 'popular',
        'maptiler_key':__import__('django.conf').conf.settings.MAPTILER_API_KEY,
    })


@require_GET
def events_in_map_bounds(request):
    from django.contrib.gis.geos import Polygon
    raw=request.GET.get('bbox','').split(',')
    if len(raw)!=4: return JsonResponse({'error':'bbox required'},status=400)
    try: bounds=tuple(map(float,raw))
    except ValueError: return JsonResponse({'error':'invalid bbox'},status=400)
    events=list(_map_events(request,bounds))
    return JsonResponse({'events':[{'id':str(e.pk),'title':e.title,'slug':e.slug,'lat':e.location.y,'lng':e.location.x,
      'start':e.start_at.isoformat(),'venue':e.venue.name if e.venue else e.location_text,'going':e.going_count,
      'popularity':e.popularity_score,'cover':e.cover_image,'categories':[i.name for i in e.interests.all()]} for e in events]})


@require_http_methods(['GET'])
def show_landing_page(request: HttpRequest) -> HttpResponse:
    """Public landing page for guests (FR-50). Signed-in users keep the dashboard until For You exists."""
    if request.user.is_authenticated:
        return dashboard(request)

    now = timezone.now()
    campus_timezone = get_campus_timezone()
    categories = list_category_interests()
    category_slug = request.GET.get('category', '')
    if category_slug not in {interest.slug for interest in categories}:
        category_slug = ''
    raw_search_text = request.GET.get('q', '').strip()
    search_text = raw_search_text[:MAX_SEARCH_LENGTH]
    if request.GET.get('q') and not raw_search_text:
        search_error = 'Enter a search phrase.'
    elif len(raw_search_text) > MAX_SEARCH_LENGTH:
        search_error = f'Searches must be {MAX_SEARCH_LENGTH} characters or fewer.'
        search_text = ''
    else:
        search_error = ''
    semantic_search = request.GET.get('semantic') == '1'
    if search_text and semantic_search:
        from .selectors import search_browse_events
        browse_events, keyword_fallback = search_browse_events(now, category_slug, search_text)
    else:
        browse_events, keyword_fallback = list_browse_events(now, category_slug, search_text), False

    context = {
        'happening_today': get_happening_today_events(now, campus_timezone),
        'this_weekend': get_weekend_events(now, campus_timezone),
        'trending': get_trending_events(now),
        'categories': categories,
        'selected_category': category_slug,
        'search_text': search_text,
        'semantic_search': semantic_search,
        'browse_events': browse_events,
        'search_error': search_error,
        'keyword_fallback': keyword_fallback,
        'featured_organizations': list_featured_organizations(now),
        'map_points': get_map_points(now),
        'map_center': get_campus_center(),
    }
    # Dates render in campus time, not the server's UTC.
    with timezone.override(campus_timezone):
        return render(request, 'discovery/landing.html', context)
