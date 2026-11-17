from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.events.models import Event

from apps.events.selectors import filter_discoverable_events

from .models import OrganizationFollow, OrganizationMembership, OrganizationVerificationRequest


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


def list_user_memberships(user) -> QuerySet[OrganizationMembership]:
    return OrganizationMembership.objects.filter(user=user).select_related('organization').order_by('organization__name')


def list_organization_events(organization, now):
    """FR-56: the public page lists discoverable events only (FR-72); unlisted and drafts never show."""
    events = filter_discoverable_events(Event.objects.filter(organization=organization))
    upcoming = events.filter(end_at__gt=now).order_by('start_at')
    past = events.filter(end_at__lte=now).order_by('-start_at')[:12]
    return list(upcoming), list(past)


def get_latest_verification_request(organization):
    return OrganizationVerificationRequest.objects.filter(organization=organization).order_by('-created_at').first()


def list_organization_members(organization) -> QuerySet[OrganizationMembership]:
    """Owner first, then Admins, then Check-in Staff, each by name."""
    from django.db.models import Case, IntegerField, Value, When
    rank = Case(
        When(role=OrganizationMembership.Role.OWNER, then=Value(0)),
        When(role=OrganizationMembership.Role.ADMIN, then=Value(1)),
        default=Value(2), output_field=IntegerField(),
    )
    return (
        OrganizationMembership.objects.filter(organization=organization)
        .select_related('user', 'user__profile').annotate(role_rank=rank).order_by('role_rank', 'user__first_name', 'user__email')
    )
