import hashlib

from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.discovery.models import RecommendationImpression
from apps.engagement.models import EventLike, EventOutboundClick, EventSave, EventView
from apps.events.models import Event, EventCheckInStaff
from apps.flyers.models import FlyerUpload
from apps.interests.models import UserInterest
from apps.interests.services import save_interests_from_preferences
from apps.notifications.models import Notification
from apps.organizations.models import OrganizationFollow
from apps.organizations.services import unfollow_organization
from apps.rsvps.models import RSVP
from apps.rsvps.services import cancel_rsvp
from apps.search.models import SearchQueryLog

from .exceptions import AccountDeletionBlockedError, EmailAlreadyRegisteredError, InvalidPasswordResetLinkError, InvalidVerificationTokenError
from .models import Profile, User
from .selectors import (
    NOTIFICATION_UPDATES, get_account_deletion_blockers, get_campus_domain_for_email, get_user_by_id,
    is_email_registered,
)

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


# Password reset (FR-67). Link life is PASSWORD_RESET_TIMEOUT; the token stops working once the
# password changes, so each link is single-use. Changing the password also signs out other sessions.
RESET_REQUESTS_PER_EMAIL = 3
RESET_REQUESTS_PER_IP = 10
RESET_WINDOW_SECONDS = 60 * 60


def _hit_rate_limit(key: str, limit: int, window: int = RESET_WINDOW_SECONDS) -> bool:
    """Count this request; True once the count passes the limit inside the window."""
    cache.add(key, 0, window)
    try:
        return cache.incr(key) > limit
    except ValueError:  # key expired between add and incr
        cache.set(key, 1, window)
        return False


def make_password_reset_parts(user: User) -> tuple[str, str]:
    return urlsafe_base64_encode(force_bytes(user.pk)), default_token_generator.make_token(user)


def request_password_reset(*, email: str, ip_address: str, build_reset_url) -> bool:
    """Email a reset link if the address has an active account. Returns whether one was sent.

    Callers show the same confirmation either way, so neither unknown emails nor rate limits are revealed.
    """
    email = email.strip().lower()
    email_hash = hashlib.sha256(email.encode()).hexdigest()
    limited_by_ip = _hit_rate_limit(f'pwreset:ip:{ip_address}', RESET_REQUESTS_PER_IP)
    limited_by_email = _hit_rate_limit(f'pwreset:email:{email_hash}', RESET_REQUESTS_PER_EMAIL)
    if limited_by_ip or limited_by_email:
        return False
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is None:
        return False
    uid, token = make_password_reset_parts(user)
    send_mail(
        subject='Reset your RADAR password',
        message=(
            f'Hi {user.first_name or "there"},\n\n'
            f'Use this link to choose a new password:\n{build_reset_url(uid, token)}\n\n'
            'This link works once and expires in 1 hour. If you did not ask for it, ignore this email: '
            'your password has not changed.'
        ),
        from_email=None,
        recipient_list=[user.email],
    )
    return True


def get_user_for_password_reset(uidb64: str, token: str) -> User:
    try:
        user = get_user_by_id(force_str(urlsafe_base64_decode(uidb64)))
    except (ValueError, TypeError, OverflowError):
        user = None
    if user is None or not user.is_active or not default_token_generator.check_token(user, token):
        raise InvalidPasswordResetLinkError
    return user


def reset_user_password(*, user: User, new_password: str) -> None:
    user.set_password(new_password)
    user.save(update_fields=['password'])


# Login rate limit. Failures are counted per email and per IP whether or not the account exists, so the
# lockout reveals nothing about which emails are registered. A lockout also blocks the correct password.
LOGIN_FAILURES_PER_EMAIL = 5
LOGIN_FAILURES_PER_IP = 20
LOGIN_WINDOW_SECONDS = 15 * 60


def _login_keys(email: str, ip_address: str) -> tuple[str, str]:
    email_hash = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    return f'login:email:{email_hash}', f'login:ip:{ip_address}'


def is_login_locked(*, email: str, ip_address: str) -> bool:
    email_key, ip_key = _login_keys(email, ip_address)
    return (cache.get(email_key, 0) >= LOGIN_FAILURES_PER_EMAIL
            or cache.get(ip_key, 0) >= LOGIN_FAILURES_PER_IP)


def record_failed_login(*, email: str, ip_address: str) -> None:
    email_key, ip_key = _login_keys(email, ip_address)
    _hit_rate_limit(email_key, LOGIN_FAILURES_PER_EMAIL, LOGIN_WINDOW_SECONDS)
    _hit_rate_limit(ip_key, LOGIN_FAILURES_PER_IP, LOGIN_WINDOW_SECONDS)


def clear_login_failures(*, email: str) -> None:
    """A successful sign-in resets that email's count. The IP count keeps running."""
    cache.delete(_login_keys(email, '')[0])


# Account deletion (FR-6, FR-68 to FR-70). The row is anonymized, not deleted, so past events,
# memberships, check-ins and reports keep pointing at a user who now has no personal data.
def delete_account(*, user: User, password: str) -> None:
    if not user.check_password(password):
        raise ValidationError('That password is not correct.')
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        if get_account_deletion_blockers(user)['has_blockers']:
            raise AccountDeletionBlockedError

        # Cancel upcoming RSVPs one by one so each frees its spot for the waitlist.
        upcoming = RSVP.objects.filter(
            user=user, event__end_at__gt=timezone.now(),
            status__in=[RSVP.Status.GOING, RSVP.Status.WAITLISTED, RSVP.Status.INTERESTED],
        ).values_list('event_id', flat=True)
        for event_id in list(upcoming):
            cancel_rsvp(event_id=event_id, actor=user)

        for follow in OrganizationFollow.objects.filter(user=user).select_related('organization'):
            unfollow_organization(user=user, organization=follow.organization)
        for model in (EventLike, EventSave, UserInterest, Notification, RecommendationImpression, EventCheckInStaff):
            model.objects.filter(user=user).delete()
        FlyerUpload.objects.filter(uploaded_by=user).delete()
        # Drafts have no attendees and no one else can see them.
        Event.objects.filter(host_user=user, status=Event.Status.DRAFT, organization__isnull=True).delete()
        # Keep the counts, drop the link to a person.
        for model in (EventView, EventOutboundClick, SearchQueryLog):
            model.objects.filter(user=user).update(user=None)

        profile = get_or_create_profile(user)
        profile.display_name = profile.avatar = profile.bio = ''
        profile.major = profile.graduation_year = None
        profile.notification_prefs = {}
        profile.save()

        user.email = f'deleted-{user.pk.hex}@deleted.invalid'
        user.username = f'deleted_{user.pk.hex}'
        user.first_name = user.last_name = ''
        user.campus_email = None
        user.is_active = False
        user.is_email_verified = user.is_campus_verified = False
        user.set_unusable_password()
        user.save()
