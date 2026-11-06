"""Numbers and chart data for the per-event analytics page (PRD 3.7, FR-35–38).

Counts come straight from the raw interaction tables so the page is right even before
the nightly EventDailyStats rollup runs.
"""
import math
from collections import Counter
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from apps.attendance.models import CheckIn
from apps.engagement.models import EventLike, EventOutboundClick, EventSave, EventView
from apps.events.models import Event
from apps.rsvps.models import RSVP, TrafficSource

AUDIENCE_MIN_GROUP = 5
CHART_LEFT, CHART_RIGHT, CHART_TOP, CHART_BOTTOM = 40, 590, 20, 190
MAX_CHECKIN_BUCKETS = 48


def get_event_kind(event: Event) -> str:
    if not event.is_free:
        return 'paid'
    if not event.rsvp_required:
        return 'drop_in'
    return 'rsvp'


def _percent(part, whole):
    return round(part * 100 / whole) if whole else None


def _nice_ceiling(value):
    if value <= 4:
        return 4
    step = 10 ** math.floor(math.log10(value))
    for multiple in (1, 2, 2.5, 5, 10):
        if value <= multiple * step:
            ceiling = multiple * step
            return int(ceiling) if ceiling == int(ceiling) else math.ceil(ceiling)
    return math.ceil(value)


def build_funnel(steps):
    """Bars on a square-root scale so small steps stay visible next to views."""
    top = max((count for _, count in steps), default=0)
    views = steps[0][1] if steps else 0
    funnel = []
    for index, (label, count) in enumerate(steps):
        funnel.append({
            'label': label,
            'count': count,
            'width': round(math.sqrt(count / top) * 100) if top and count else 0,
            # Share of views, not of the step before: people often RSVP without liking or saving first.
            'share': _percent(count, views) if index and views else None,
            'step': index,
        })
    return funnel


def build_running_total(timestamps, start_day, end_day, tz):
    """A running daily total as SVG polyline points, plus the axis labels."""
    if end_day < start_day:
        end_day = start_day
    days = (end_day - start_day).days + 1
    per_day = Counter(timezone.localtime(ts, tz).date() for ts in timestamps)
    before = sum(n for day, n in per_day.items() if day < start_day)
    totals, running = [], before
    for offset in range(days):
        running += per_day.get(start_day + timedelta(days=offset), 0)
        totals.append(running)
    if len(totals) == 1:
        totals = totals * 2
    y_max = _nice_ceiling(max(totals))
    span = len(totals) - 1
    points = ' '.join(
        f'{CHART_LEFT + i * (CHART_RIGHT - CHART_LEFT) / span:.1f},'
        f'{CHART_BOTTOM - total / y_max * (CHART_BOTTOM - CHART_TOP):.1f}'
        for i, total in enumerate(totals)
    )
    return {
        'points': points,
        'total': totals[-1],
        'y_max': y_max,
        'y_half': y_max // 2 if y_max % 2 == 0 else y_max / 2,
        'start_day': start_day,
        'middle_day': start_day + (end_day - start_day) / 2,
        'end_day': end_day,
    }


def build_checkin_buckets(event: Event, checkin_times):
    """Check-ins per 15 minutes (hourly for events longer than 8 hours)."""
    if not (event.start_at and event.end_at):
        return None
    minutes = max(1, (event.end_at - event.start_at).total_seconds() / 60)
    size = 15 if minutes <= 8 * 60 else 60
    count = min(MAX_CHECKIN_BUCKETS, math.ceil(minutes / size))
    totals = [0] * count
    for checked_in_at in checkin_times:
        index = int((checked_in_at - event.start_at).total_seconds() // (size * 60))
        totals[min(max(index, 0), count - 1)] += 1
    peak = max(totals)
    buckets = [{
        'start': event.start_at + timedelta(minutes=i * size),
        'count': n,
        'height': round(n / peak * 160) if peak else 0,
    } for i, n in enumerate(totals)]
    busiest = max(buckets, key=lambda b: b['count']) if peak else None
    return {
        'buckets': buckets,
        'size': size,
        'busiest': busiest,
        'middle': event.start_at + (event.end_at - event.start_at) / 2,
    }


def _group_small(counter: Counter):
    """Largest groups first; groups under AUDIENCE_MIN_GROUP are folded into Other."""
    rows, other = [], 0
    for label, n in counter.most_common():
        if label and n >= AUDIENCE_MIN_GROUP:
            rows.append({'label': label, 'count': n})
        else:
            other += n
    if other:
        rows.append({'label': 'Other', 'count': other})
    return rows


def get_audience(event: Event):
    """Who came (or who is going, before anyone checks in), by major and class year."""
    from apps.accounts.models import Profile

    user_ids = list(CheckIn.objects.filter(event=event).values_list('user_id', flat=True))
    based_on = 'checked-in attendees'
    if not user_ids:
        user_ids = list(RSVP.objects.filter(event=event, status=RSVP.Status.GOING).values_list('user_id', flat=True))
        based_on = 'people going'
    profiles = list(Profile.objects.filter(user_id__in=user_ids).values('major', 'graduation_year'))
    missing = len(user_ids) - len(profiles)
    majors = Counter((p['major'] or '').strip() for p in profiles)
    years = Counter(str(p['graduation_year']) if p['graduation_year'] else '' for p in profiles)
    majors[''] += missing
    years[''] += missing
    return {
        'total': len(user_ids),
        'based_on': based_on,
        'majors': _group_small(majors) if user_ids else [],
        'years': _group_small(years) if user_ids else [],
    }


def get_traffic_sources(event: Event, total_views: int):
    labels = dict(TrafficSource.choices)
    rows = EventView.objects.filter(event=event).values('source').annotate(n=Count('id')).order_by('-n')
    return [
        {'label': labels.get(row['source'], row['source']).replace('_', ' ').capitalize(), 'count': row['n'],
         'percent': _percent(row['n'], total_views)}
        for row in rows
    ]


def get_event_analytics_page(event: Event, now, tz) -> dict:
    kind = get_event_kind(event)
    views = EventView.objects.filter(event=event).count()
    like_users = set(EventLike.objects.filter(event=event).values_list('user_id', flat=True))
    save_users = set(EventSave.objects.filter(event=event).values_list('user_id', flat=True))
    engaged = len(like_users | save_users)
    rsvps = dict(
        RSVP.objects.filter(event=event).values_list('status').annotate(n=Count('id')).values_list('status', 'n')
    )
    going = rsvps.get(RSVP.Status.GOING, 0)
    waitlisted = rsvps.get(RSVP.Status.WAITLISTED, 0)
    interested = rsvps.get(RSVP.Status.INTERESTED, 0)
    checkin_times = list(CheckIn.objects.filter(event=event).values_list('checked_in_at', flat=True))
    checkins = len(checkin_times)
    clicks = dict(
        EventOutboundClick.objects.filter(event=event).values_list('kind').annotate(n=Count('id')).values_list('kind', 'n')
    )
    started = bool(event.start_at and event.start_at <= now)
    ended = bool(event.end_at and event.end_at <= now)

    kpis = [
        {'label': 'Views', 'value': views},
        {'label': 'Likes', 'value': len(like_users)},
        {'label': 'Saves', 'value': len(save_users)},
    ]
    if kind == 'rsvp':
        attendance = _percent(min(checkins, going), going) if started else None
        kpis += [
            {'label': 'RSVPs', 'value': going, 'note': 'Going'},
            {'label': 'Waitlist', 'value': waitlisted, 'note': 'Never got a spot' if ended else 'Waiting for a spot'},
            {'label': 'Check-ins', 'value': checkins},
            {'label': 'Attendance rate', 'value': f'{attendance}%' if attendance is not None else '—',
             'note': 'Check-ins ÷ going' if started else 'Shows once the event starts', 'tone': 'navy'},
            {'label': 'No-show rate', 'value': f'{100 - attendance}%' if ended and attendance is not None else '—',
             'note': 'Going but no check-in' if ended else 'Shows after the event', 'tone': 'accent'},
        ]
        funnel = build_funnel([('Views', views), ('Liked or saved', engaged), ('RSVP', going), ('Checked in', checkins)])
        line_title, line_times = 'RSVPs over time', RSVP.objects.filter(event=event, status=RSVP.Status.GOING).values_list('created_at', flat=True)
    elif kind == 'drop_in':
        kpis.append({'label': 'Interested taps', 'value': interested, 'note': 'Drop-in, no RSVP'})
        funnel = build_funnel([('Views', views), ('Liked or saved', engaged), ('Interested', interested)])
        line_title, line_times = 'Interested taps over time', RSVP.objects.filter(event=event, status=RSVP.Status.INTERESTED).values_list('created_at', flat=True)
    else:
        ticket_clicks = clicks.get(EventOutboundClick.Kind.TICKETS_LINK, 0)
        kpis += [
            {'label': 'Ticket link clicks', 'value': ticket_clicks, 'note': 'Sales happen on the host’s site'},
            {'label': 'Contact host clicks', 'value': clicks.get(EventOutboundClick.Kind.CONTACT, 0)},
        ]
        funnel = build_funnel([('Views', views), ('Liked or saved', engaged), ('Ticket clicks', ticket_clicks)])
        line_title, line_times = 'Ticket link clicks over time', EventOutboundClick.objects.filter(
            event=event, kind=EventOutboundClick.Kind.TICKETS_LINK).values_list('created_at', flat=True)

    published = event.published_at or event.created_at
    last_day = min(now, event.start_at) if event.start_at else now
    line = build_running_total(
        list(line_times), timezone.localtime(published, tz).date(), timezone.localtime(last_day, tz).date(), tz
    )

    return {
        'kind': kind,
        'started': started,
        'ended': ended,
        'kpis': kpis,
        'funnel': funnel,
        'views_tracked': views > 0,
        'line_title': line_title,
        'line': line,
        'published_at': published,
        'checkins': build_checkin_buckets(event, checkin_times) if kind == 'rsvp' else None,
        'sources': get_traffic_sources(event, views),
        'audience': get_audience(event) if kind == 'rsvp' else None,
    }
