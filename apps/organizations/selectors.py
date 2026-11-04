from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.events.models import Event

from .models import OrganizationFollow


def list_followed_organizations(user) -> QuerySet[OrganizationFollow]:
    """The user's follows with each organization's upcoming event count (FR-58)."""
    upcoming = Count(
        'organization__events',
        filter=Q(
            organization__events__status=Event.Status.PUBLISHED,
            organization__events__visibility__in=[Event.Visibility.PUBLIC, Event.Visibility.CAMPUS_ONLY],
            organization__events__end_at__gt=timezone.now(),
        ),
        distinct=True,
    )
    return (
        OrganizationFollow.objects.filter(user=user)
        .select_related('organization')
        .annotate(upcoming_count=upcoming)
        .order_by('organization__name')
    )
