import csv

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.attendance.models import CheckIn
from apps.events.models import Event

from .permissions import user_can_export_attendees, user_can_view_analytics
from .selectors import get_event_analytics_page
from .services import get_attendee_rows

# Spreadsheet apps run cells that start with these characters as formulas.
FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def _get_event_or_404(event_id):
    event = Event.objects.select_related('organization', 'venue').filter(pk=event_id).first()
    if event is None:
        raise Http404
    return event


@login_required
@require_GET
def show_event_analytics(request, event_id):
    """Per-event dashboard for the host and the organization's Owner and Admins (PRD 3.7)."""
    from apps.accounts.views import get_account_shell_context
    from apps.discovery.selectors import get_campus_timezone

    event = _get_event_or_404(event_id)
    if not user_can_view_analytics(request.user, event):
        raise Http404
    tz = get_campus_timezone()
    now = timezone.now()
    context = {
        **get_account_shell_context(request.user),
        'active_nav': 'my_dashboard',
        'event': event,
        'can_export': user_can_export_attendees(request.user, event),
        'now': now,
        **get_event_analytics_page(event, now, tz),
    }
    with timezone.override(tz):
        return render(request, 'analytics/event_analytics.html', context)


def _safe_cell(value):
    text = '' if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


@login_required
@require_GET
def export_attendee_csv(request, event_id):
    """Going attendees as CSV. Only the individual host or the organization Owner (FR-35, PRD 3.7)."""
    from apps.discovery.selectors import get_campus_timezone

    event = _get_event_or_404(event_id)
    try:
        rows = list(get_attendee_rows(actor=request.user, event_id=event.pk))
    except PermissionDenied:
        raise Http404
    checked_in = dict(CheckIn.objects.filter(event=event).values_list('user_id', 'checked_in_at'))
    tz = get_campus_timezone()
    stamp = lambda value: timezone.localtime(value, tz).strftime('%Y-%m-%d %H:%M') if value else ''

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{event.slug or event.pk}-attendees.csv"'
    writer = csv.writer(response)
    writer.writerow(['Name', 'Email', 'Major', 'Class year', "RSVP'd at", 'Checked in', 'Checked in at'])
    for rsvp in rows:
        profile = getattr(rsvp.user, 'profile', None)
        writer.writerow([_safe_cell(v) for v in (
            (profile.display_name if profile else '') or rsvp.user.get_full_name(),
            rsvp.user.email,
            profile.major if profile else '',
            profile.graduation_year if profile else '',
            stamp(rsvp.created_at),
            'Yes' if rsvp.user_id in checked_in else 'No',
            stamp(checked_in.get(rsvp.user_id)),
        )])
    return response
