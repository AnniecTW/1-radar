from django.db.models import QuerySet

from .models import Event


def filter_discoverable_events(queryset: QuerySet[Event]) -> QuerySet[Event]:
    """The one visibility rule for feeds, landing page, map and search (FR-72).

    Unlisted events are reachable only by direct link, and drafts and cancelled events never list.
    """
    return queryset.filter(
        status=Event.Status.PUBLISHED,
        visibility__in=[Event.Visibility.PUBLIC, Event.Visibility.CAMPUS_ONLY],
    )
