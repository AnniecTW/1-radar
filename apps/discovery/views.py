from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

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
    search_text = request.GET.get('q', '').strip()[:MAX_SEARCH_LENGTH]

    context = {
        'happening_today': get_happening_today_events(now, campus_timezone),
        'this_weekend': get_weekend_events(now, campus_timezone),
        'trending': get_trending_events(now),
        'categories': categories,
        'selected_category': category_slug,
        'search_text': search_text,
        'browse_events': list_browse_events(now, category_slug, search_text),
        'featured_organizations': list_featured_organizations(now),
        'map_points': get_map_points(now),
        'map_center': get_campus_center(),
    }
    # Dates render in campus time, not the server's UTC.
    with timezone.override(campus_timezone):
        return render(request, 'discovery/landing.html', context)
