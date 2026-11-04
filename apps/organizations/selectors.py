from django.db.models import QuerySet

from .models import OrganizationFollow


def list_followed_organizations(user) -> QuerySet[OrganizationFollow]:
    """The user's follows with their organizations, for the Following list (FR-58)."""
    return OrganizationFollow.objects.filter(user=user).select_related('organization').order_by('organization__name')
