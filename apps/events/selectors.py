from django.db.models import Count, F, Q, QuerySet

from .models import Event


def filter_discoverable_events(queryset: QuerySet[Event]) -> QuerySet[Event]:
    """The one visibility rule for feeds, landing page, map and search (FR-72).

    Unlisted events are reachable only by direct link, and drafts and cancelled events never list.
    """
    return queryset.filter(
        status=Event.Status.PUBLISHED,
        visibility__in=[Event.Visibility.PUBLIC, Event.Visibility.CAMPUS_ONLY],
    )


def list_hosted_events(user) -> QuerySet[Event]:
    """Events the user created, newest first. Drafts may not have a start time yet."""
    going = Count('rsvps', filter=Q(rsvps__status='going'), distinct=True)
    return (
        Event.objects.filter(host_user=user)
        .exclude(status=Event.Status.CANCELLED)
        .select_related('organization', 'venue')
        .annotate(going_count=going)
        .order_by(F('start_at').desc(nulls_first=True))
    )
