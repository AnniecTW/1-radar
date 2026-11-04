from django.core import signing
from django.core.mail import send_mail
from django.db import IntegrityError, transaction

from apps.interests.services import save_interests_from_preferences

from .exceptions import EmailAlreadyRegisteredError, InvalidVerificationTokenError
from .models import Profile, User
from .selectors import NOTIFICATION_UPDATES, get_campus_domain_for_email, get_user_by_id, is_email_registered

VERIFICATION_TOKEN_SALT = 'accounts.email-verification'
VERIFICATION_TOKEN_MAX_AGE_SECONDS = 3 * 24 * 60 * 60


def create_user_account(*, email: str, password: str, first_name: str, last_name: str) -> User:
    """Create a user and its profile. The email stays unverified until the link is used."""
    if is_email_registered(email):
        raise EmailAlreadyRegisteredError(email)
    try:
        with transaction.atomic():
            user = User(email=email, first_name=first_name, last_name=last_name)
            user.set_password(password)
            user.save()
            Profile.objects.create(user=user, display_name=first_name)
    except IntegrityError as error:
        # Two signups with the same email can pass the check above at the same time.
        raise EmailAlreadyRegisteredError(email) from error
    return user


def get_or_create_profile(user: User) -> Profile:
    profile, _ = Profile.objects.get_or_create(user=user, defaults={'display_name': user.first_name})
    return profile


def update_profile(*, user: User, display_name: str, bio: str, major: str, graduation_year: int | None) -> Profile:
    profile = get_or_create_profile(user)
    profile.display_name = display_name
    profile.bio = bio
    profile.major = major or None
    profile.graduation_year = graduation_year
    profile.save(update_fields=['display_name', 'bio', 'major', 'graduation_year', 'updated_at'])
    return profile


def save_feed_preferences(*, user: User, cleaned_data: dict) -> None:
    """Save interests and the settings on the Feed & notifications page."""
    profile = get_or_create_profile(user)
    notifications = {
        key: {'app': cleaned_data[f'{key}_app'], 'email': cleaned_data[f'{key}_email']}
        for key, _ in NOTIFICATION_UPDATES
    }
    feed = {'default_tab': cleaned_data['default_tab'], 'free_only': cleaned_data['free_only']}
    with transaction.atomic():
        save_interests_from_preferences(user=user, interests=cleaned_data['interests'])
        profile.notification_prefs = {**profile.notification_prefs, 'notifications': notifications, 'feed': feed}
        profile.save(update_fields=['notification_prefs', 'updated_at'])


def save_location_preferences(*, user: User, cleaned_data: dict) -> None:
    profile = get_or_create_profile(user)
    profile.notification_prefs = {**profile.notification_prefs, 'location': cleaned_data}
    profile.save(update_fields=['notification_prefs', 'updated_at'])


def make_verification_token(user: User) -> str:
    # The email is signed in so a link stops working if the address changes.
    return signing.dumps({'user_id': str(user.pk), 'email': user.email}, salt=VERIFICATION_TOKEN_SALT)


def send_verification_email(user: User, verification_url: str) -> None:
    send_mail(
        subject='Verify your RADAR email',
        message=(
            f'Hi {user.first_name or "there"},\n\n'
            f'Confirm your email to start RSVPing to events on RADAR:\n{verification_url}\n\n'
            'This link expires in 3 days. If you did not create an account, ignore this email.'
        ),
        from_email=None,
        recipient_list=[user.email],
    )


def verify_user_email(token: str) -> User:
    """Mark the email verified and flag campus members (FR-1, FR-2)."""
    try:
        payload = signing.loads(
            token, salt=VERIFICATION_TOKEN_SALT, max_age=VERIFICATION_TOKEN_MAX_AGE_SECONDS
        )
    except signing.BadSignature as error:  # SignatureExpired is a subclass
        raise InvalidVerificationTokenError from error

    user = get_user_by_id(payload.get('user_id'))
    if user is None or not user.is_active or user.email != payload.get('email'):
        raise InvalidVerificationTokenError

    user.is_email_verified = True
    user.is_campus_verified = get_campus_domain_for_email(user.email) is not None
    user.save(update_fields=['is_email_verified', 'is_campus_verified'])
    return user
