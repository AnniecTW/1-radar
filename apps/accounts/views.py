import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from apps.attendance.selectors import count_events_attended, get_semester_attendance
from apps.discovery.selectors import get_campus_timezone
from apps.engagement.selectors import list_saved_events
from apps.engagement.services import remove_saved_event
from apps.events.selectors import list_hosted_events
from apps.interests.selectors import get_selected_interest_ids, list_interests_by_group, list_user_interests
from apps.organizations.models import OrganizationFollow
from apps.organizations.selectors import list_followed_organizations
from apps.organizations.services import set_follow_notifications, unfollow_organization
from apps.rsvps.selectors import list_past_rsvps, list_upcoming_tickets

from .exceptions import EmailAlreadyRegisteredError, InvalidVerificationTokenError
from .forms import FeedPreferencesForm, LocationPreferencesForm, LoginForm, ProfileForm, SignupForm
from .selectors import NOTIFICATION_UPDATES, get_initials, get_preferences
from .services import (
    create_user_account,
    get_or_create_profile,
    make_verification_token,
    save_feed_preferences,
    save_location_preferences,
    send_verification_email,
    update_profile,
    verify_user_email,
)

logger = logging.getLogger(__name__)

PROFILE_TABS = (
    ('overview', 'Overview'),
    ('tickets', 'My Tickets'),
    ('saved', 'Saved'),
    ('following', 'Following'),
    ('hosting', 'Hosting'),
    ('past', 'Past events'),
)


def get_safe_next_url(request: HttpRequest) -> str:
    """Return the `next` URL only if it stays on this site; otherwise the dashboard."""
    next_url = request.POST.get('next') or request.GET.get('next') or ''
    is_safe = url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    )
    return next_url if is_safe else reverse('dashboard')


def get_onboarding_url(next_url: str) -> str:
    return f"{reverse('onboarding_interests')}?{urlencode({'next': next_url})}"


def get_account_shell_context(user) -> dict:
    """The name and initials the sidebar layout's top bar shows."""
    profile = get_or_create_profile(user)
    display_name = profile.display_name or user.get_full_name() or user.email
    return {'profile': profile, 'display_name': display_name, 'initials': get_initials(display_name)}


def send_verification_email_to(request: HttpRequest) -> bool:
    """Return False instead of raising, so a mail outage never turns signup into a 500."""
    token = make_verification_token(request.user)
    verification_url = request.build_absolute_uri(reverse('verify_email', args=[token]))
    try:
        send_verification_email(request.user, verification_url)
    except Exception:
        logger.exception('Could not send verification email to user %s', request.user.pk)
        messages.error(request, 'We could not send the verification email. Please try resending it.')
        return False
    return True


@require_http_methods(['GET', 'POST'])
def login_user(request: HttpRequest) -> HttpResponse:
    next_url = get_safe_next_url(request)
    if request.user.is_authenticated:
        return redirect(next_url)

    form = LoginForm(request.POST) if request.method == 'POST' else LoginForm()
    if request.method == 'POST' and form.is_valid():
        user = authenticate(
            request, username=form.cleaned_data['email'], password=form.cleaned_data['password']
        )
        if user is None:
            # One message for unknown email and wrong password so neither is revealed.
            form.add_error(None, 'Incorrect email or password.')
        else:
            login(request, user)
            if not form.cleaned_data['remember']:
                request.session.set_expiry(0)
            return redirect(next_url if user.onboarding_completed else get_onboarding_url(next_url))
    return render(request, 'accounts/login.html', {'form': form, 'next': next_url})


@require_http_methods(['GET', 'POST'])
def signup_user(request: HttpRequest) -> HttpResponse:
    next_url = get_safe_next_url(request)
    if request.user.is_authenticated:
        return redirect(next_url)

    form = SignupForm(request.POST) if request.method == 'POST' else SignupForm()
    if request.method == 'POST' and form.is_valid():
        try:
            user = create_user_account(
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password1'],
                first_name=form.cleaned_data['first_name'],
                last_name=form.cleaned_data['last_name'],
            )
        except EmailAlreadyRegisteredError:
            form.add_error('email', 'An account with this email already exists.')
        else:
            login(request, user)
            send_verification_email_to(request)
            return redirect(f"{reverse('verification_sent')}?{urlencode({'next': get_onboarding_url(next_url)})}")
    return render(request, 'accounts/signup.html', {'form': form, 'next': next_url})


@require_POST
def logout_user(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect('dashboard')


@login_required
@require_http_methods(['GET'])
def show_verification_sent(request: HttpRequest) -> HttpResponse:
    return render(request, 'accounts/verification.html', {
        'state': 'verified' if request.user.is_email_verified else 'sent',
        'next': get_safe_next_url(request),
    })


@login_required
@require_POST
def resend_verification_email(request: HttpRequest) -> HttpResponse:
    next_url = get_safe_next_url(request)
    if not request.user.is_email_verified:
        if send_verification_email_to(request):
            messages.info(request, 'We sent you a new verification link.')
    return redirect(f"{reverse('verification_sent')}?{urlencode({'next': next_url})}")


@require_http_methods(['GET'])
def verify_email(request: HttpRequest, token: str) -> HttpResponse:
    """Works without a session: people often open the link on a different device."""
    try:
        user = verify_user_email(token)
    except InvalidVerificationTokenError:
        return render(request, 'accounts/verification.html', {'state': 'invalid'}, status=400)
    next_url = reverse('dashboard') if user.onboarding_completed else get_onboarding_url(reverse('dashboard'))
    return render(request, 'accounts/verification.html', {'state': 'verified', 'next': next_url})


@login_required
@require_http_methods(['GET'])
def show_profile(request: HttpRequest) -> HttpResponse:
    """The signed-in user's dashboard. Students have no public profile page in the MVP (FR-4)."""
    now = timezone.now()
    user = request.user
    tab = request.GET.get('tab', 'overview')
    if tab not in dict(PROFILE_TABS):
        tab = 'overview'

    tickets = list(list_upcoming_tickets(user, now))
    saved_events = list(list_saved_events(user, now))
    follows = list(list_followed_organizations(user))
    context = {
        **get_account_shell_context(user),
        'active_page': 'profile',
        'tab': tab,
        'tabs': PROFILE_TABS,
        'tickets': tickets,
        'saved_events': saved_events,
        'follows': follows,
        'attended_count': count_events_attended(user),
        'interests': list_user_interests(user),
        'semester': get_semester_attendance(user, now),
    }
    if tab == 'hosting':
        context['hosted_events'] = list_hosted_events(user)
    elif tab == 'past':
        context['past_rsvps'] = list_past_rsvps(user, now)
    # Dates render in campus time, not the server's UTC.
    with timezone.override(get_campus_timezone()):
        return render(request, 'accounts/profile.html', context)


@login_required
@require_http_methods(['GET', 'POST'])
def edit_profile(request: HttpRequest) -> HttpResponse:
    shell = get_account_shell_context(request.user)
    profile = shell['profile']
    form = ProfileForm(request.POST) if request.method == 'POST' else ProfileForm(initial={
        'display_name': shell['display_name'],
        'bio': profile.bio,
        'major': profile.major or '',
        'graduation_year': profile.graduation_year,
    })
    if request.method == 'POST' and form.is_valid():
        update_profile(user=request.user, **form.cleaned_data)
        messages.success(request, 'Your profile is saved.')
        return redirect('profile')
    return render(request, 'accounts/profile_edit.html', {**shell, 'form': form, 'active_page': 'profile'})


@login_required
@require_http_methods(['GET', 'POST'])
def edit_preferences(request: HttpRequest) -> HttpResponse:
    """Feed & notifications: interests (FR-9), delivery settings, and the Following list (FR-58, FR-59)."""
    shell = get_account_shell_context(request.user)
    saved = get_preferences(shell['profile'])
    form = FeedPreferencesForm(request.POST) if request.method == 'POST' else FeedPreferencesForm()
    if request.method == 'POST' and form.is_valid():
        save_feed_preferences(user=request.user, cleaned_data=form.cleaned_data)
        messages.success(request, 'Your preferences are saved.')
        return redirect('preferences')

    if form.is_bound:
        # Keep what the person just chose on screen when the form has errors.
        selected_ids = {int(pk) for pk in request.POST.getlist('interests') if pk.isdigit()}
        is_on = lambda name: name in request.POST
        default_tab = request.POST.get('default_tab', saved['feed']['default_tab'])
        free_only = is_on('free_only')
    else:
        selected_ids = get_selected_interest_ids(request.user)
        is_on = lambda name: saved['notifications'][name.rsplit('_', 1)[0]][name.rsplit('_', 1)[1]]
        default_tab = saved['feed']['default_tab']
        free_only = saved['feed']['free_only']
    return render(request, 'accounts/preferences.html', {
        **shell,
        'form': form,
        'active_page': 'profile',
        'preferences_page': 'feed',
        'groups': list_interests_by_group(),
        'selected_ids': selected_ids,
        'notifications': [
            {'key': key, 'label': label, 'app': is_on(f'{key}_app'), 'email': is_on(f'{key}_email')}
            for key, label in NOTIFICATION_UPDATES
        ],
        'default_tab': default_tab,
        'free_only': free_only,
        'follows': list_followed_organizations(request.user),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def edit_account_preferences(request: HttpRequest) -> HttpResponse:
    """Account & privacy: location and map settings, sign-in details, and privacy notes."""
    shell = get_account_shell_context(request.user)
    form = LocationPreferencesForm(request.POST) if request.method == 'POST' else LocationPreferencesForm()
    if request.method == 'POST':
        if form.is_valid():
            save_location_preferences(user=request.user, cleaned_data=form.cleaned_data)
            messages.success(request, 'Your preferences are saved.')
            return redirect('account_preferences')
        messages.error(request, 'We could not save those settings. Please try again.')
    return render(request, 'accounts/preferences_account.html', {
        **shell,
        'active_page': 'profile',
        'preferences_page': 'account',
        'location': get_preferences(shell['profile'])['location'],
    })


@login_required
@require_http_methods(['GET', 'POST'])
def change_password(request: HttpRequest) -> HttpResponse:
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        # Changing the password would otherwise sign this session out.
        update_session_auth_hash(request, user)
        messages.success(request, 'Your password is changed.')
        return redirect('account_preferences')
    return render(request, 'accounts/password_change.html', {
        **get_account_shell_context(request.user), 'form': form, 'active_page': 'profile',
    })


@login_required
@require_POST
def update_followed_organization(request: HttpRequest, slug: str) -> HttpResponse:
    """Mute, unmute or unfollow from any Following list."""
    follow = get_object_or_404(
        OrganizationFollow.objects.select_related('organization'), user=request.user, organization__slug=slug
    )
    organization = follow.organization
    action = request.POST.get('action')
    if action == 'mute':
        set_follow_notifications(user=request.user, organization=organization, notify=False)
        messages.success(request, f'{organization.name} is muted. You still follow it.')
    elif action == 'unmute':
        set_follow_notifications(user=request.user, organization=organization, notify=True)
        messages.success(request, f'Notifications from {organization.name} are back on.')
    elif action == 'unfollow':
        unfollow_organization(user=request.user, organization=organization)
        messages.success(request, f'You unfollowed {organization.name}.')
    return redirect(get_safe_next_url(request))


@login_required
@require_POST
def remove_from_saved(request: HttpRequest, event_id) -> HttpResponse:
    remove_saved_event(user=request.user, event_id=event_id)
    messages.success(request, 'Removed from your saved events.')
    return redirect(get_safe_next_url(request))
