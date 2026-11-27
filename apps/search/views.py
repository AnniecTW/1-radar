from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .dashboard import get_search_dashboard


@login_required
@require_GET
def show_search_dashboard(request):
    """How search is used and how well it works, from the anonymous search log and the latest offline
    evaluation. Staff only; everyone else gets a 404, as if the page didn't exist."""
    from apps.accounts.views import get_account_shell_context
    from apps.discovery.selectors import get_campus_timezone

    if not request.user.is_staff:
        raise Http404
    tz = get_campus_timezone()
    now = timezone.now()
    context = {
        **get_account_shell_context(request.user),
        'active_nav': 'search_analytics',
        'now': now,
        **get_search_dashboard(now, tz, request.GET.get('range', '30'), request.GET.get('source', 'real')),
    }
    with timezone.override(tz):
        return render(request, 'search/dashboard.html', context)
