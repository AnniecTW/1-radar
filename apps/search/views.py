from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .dashboard import get_search_dashboard


def _render_staff_page(request, template, tab, build):
    """The staff analytics tabs share their sign-in rule, filters and layout. Staff only; everyone else gets a
    404, as if the page didn't exist."""
    from apps.accounts.views import get_account_shell_context
    from apps.discovery.selectors import get_campus_timezone

    if not request.user.is_staff:
        raise Http404
    tz = get_campus_timezone()
    now = timezone.now()
    data = build(now, tz, request.GET.get('range', '30'), request.GET.get('source', 'real'))
    context = {
        **get_account_shell_context(request.user),
        'active_nav': 'staff_analytics',
        'staff_tab': tab,
        'now': now,
        # Switching tabs keeps the period and data filters.
        'filter_query': urlencode({'range': data['range_key'], 'source': data['source']}),
        **data,
    }
    with timezone.override(tz):
        return render(request, template, context)


@login_required
@require_GET
def show_search_dashboard(request):
    """How search is used and how well it works, from the anonymous search log and the latest offline
    evaluation."""
    return _render_staff_page(request, 'search/dashboard.html', 'search', get_search_dashboard)


@login_required
@require_GET
def show_recommendation_dashboard(request):
    """How "Recommended for you" is used and how well it works, from the impression log and the latest
    offline evaluation."""
    from apps.discovery.dashboard import get_recommendation_dashboard

    return _render_staff_page(request, 'search/recommendations.html', 'recommendations', get_recommendation_dashboard)
