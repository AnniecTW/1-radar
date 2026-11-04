from datetime import datetime

from django.db.models import QuerySet

from apps.discovery.selectors import list_upcoming_events
from apps.events.models import Event


def list_saved_events(user, now: datetime) -> QuerySet[Event]:
    return list_upcoming_events(now).filter(saves__user=user).order_by('start_at')
