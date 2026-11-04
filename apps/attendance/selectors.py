from datetime import datetime

from django.db.models import Count

from apps.interests.models import Interest
from apps.rsvps.selectors import list_past_rsvps

from .models import CheckIn

TOP_INTEREST_COUNT = 3


def count_events_attended(user) -> int:
    return CheckIn.objects.filter(user=user).count()


def get_semester_start(now: datetime) -> datetime:
    """Spring starts in January, summer in June and fall in August."""
    start_month = 8 if now.month >= 8 else 6 if now.month >= 6 else 1
    return now.replace(month=start_month, day=1, hour=0, minute=0, second=0, microsecond=0)


def get_semester_attendance(user, now: datetime) -> dict:
    """How many of this semester's past RSVPs the user checked in to, and for which interests."""
    start = get_semester_start(now)
    rsvps = list_past_rsvps(user, now).filter(event__start_at__gte=start)
    total = rsvps.count()
    attended = rsvps.filter(attended=True).count()
    top_interests = (
        Interest.objects.filter(events__checkins__user=user, events__start_at__gte=start)
        .annotate(attended_count=Count('events', distinct=True))
        .order_by('-attended_count', 'name')[:TOP_INTEREST_COUNT]
    )
    return {
        'total': total,
        'attended': attended,
        'percent': round(attended / total * 100) if total else 0,
        'top_interests': list(top_interests),
    }
