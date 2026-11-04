from django.db import transaction

from apps.accounts.models import Profile

from .models import UserInterest


def save_onboarding_interests(*, user, interests, major, graduation_year):
    """Replace the user's onboarding picks; inferred and settings rows are left alone."""
    with transaction.atomic():
        UserInterest.objects.filter(user=user, source=UserInterest.Source.ONBOARDING).exclude(
            interest__in=interests
        ).delete()
        for interest in interests:
            UserInterest.objects.get_or_create(
                user=user, interest=interest, defaults={'source': UserInterest.Source.ONBOARDING, 'weight': 1.0}
            )
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.major = major or None
        profile.graduation_year = graduation_year
        profile.save(update_fields=['major', 'graduation_year', 'updated_at'])


def complete_onboarding(user) -> None:
    if not user.onboarding_completed:
        user.onboarding_completed = True
        user.save(update_fields=['onboarding_completed'])


def save_interests_from_preferences(*, user, interests) -> None:
    """Make the user's interests match their picks. Unchecking removes a row whatever its source."""
    with transaction.atomic():
        UserInterest.objects.filter(user=user).exclude(interest__in=interests).delete()
        for interest in interests:
            UserInterest.objects.get_or_create(
                user=user, interest=interest, defaults={'source': UserInterest.Source.SETTINGS, 'weight': 1.0}
            )
