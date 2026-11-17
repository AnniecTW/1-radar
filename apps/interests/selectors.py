from django.db.models import Count, Q
from django.utils import timezone

from apps.events.models import Event
from apps.events.selectors import filter_discoverable_events
from apps.organizations.models import Organization

from .models import Interest, UserInterest

SUGGESTED_ORGANIZATION_LIMIT = 8


def list_interests_by_group() -> list[tuple[str, list[Interest]]]:
    groups: dict[str, list[Interest]] = {}
    for interest in Interest.objects.filter(is_active=True).order_by('group', 'name'):
        groups.setdefault(interest.group or 'Other', []).append(interest)
    return list(groups.items())


def get_selected_interest_ids(user) -> set[int]:
    return set(user.interests.values_list('interest_id', flat=True))


def list_suggested_organizations(user) -> list[Organization]:
    """Organizations with upcoming events matching the user's interests, not yet followed (FR-61)."""
    interest_ids = get_selected_interest_ids(user)
    if not interest_ids:
        return []
    matching = filter_discoverable_events(
        Event.objects.filter(end_at__gt=timezone.now(), interests__in=interest_ids)
    )
    return list(
        Organization.objects.exclude(follows__user=user)
        .annotate(matching_events=Count('events', filter=Q(events__in=matching), distinct=True))
        .filter(matching_events__gt=0)
        .order_by('-matching_events', '-follower_count', 'name')[:SUGGESTED_ORGANIZATION_LIMIT]
    )


def list_user_interests(user) -> list[Interest]:
    return list(Interest.objects.filter(userinterest__user=user, is_active=True).order_by('name'))
