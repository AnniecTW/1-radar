import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from apps.interests.forms import PreferredInterestsForm
from apps.interests.selectors import get_selected_interest_ids, list_interests_by_group, list_user_interests
from apps.interests.services import save_interests_from_preferences
from apps.organizations.models import OrganizationFollow
from apps.organizations.selectors import list_followed_organizations
from apps.organizations.services import set_follow_notifications, unfollow_organization

from .exceptions import EmailAlreadyRegisteredError, InvalidVerificationTokenError
from .forms import LoginForm, ProfileForm, SignupForm
from .selectors import get_initials
from .services import (
    create_user_account,
    get_or_create_profile,
    make_verification_token,
    send_verification_email,
    update_profile,
    verify_user_email,
)

logger = logging.getLogger(__name__)


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
@require_http_methods(['GET', 'POST'])
def edit_profile(request: HttpRequest) -> HttpResponse:
    """FR-4: the signed-in user's own profile. Students have no public profile page in the MVP."""
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

    follows = list_followed_organizations(request.user)
    return render(request, 'accounts/profile.html', {
        **shell,
        'form': form,
        'active_page': 'profile',
        'interests': list_user_interests(request.user),
        'following_count': follows.count(),
        'muted_count': follows.filter(notify=False).count(),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def edit_preferences(request: HttpRequest) -> HttpResponse:
    """FR-9, FR-58, FR-59: interests and the organizations the user follows."""
    form = PreferredInterestsForm(request.POST) if request.method == 'POST' else PreferredInterestsForm()
    if request.method == 'POST':
        if form.is_valid():
            save_interests_from_preferences(user=request.user, interests=form.cleaned_data['interests'])
            messages.success(request, 'Your interests are saved.')
            return redirect('preferences')
        messages.error(request, 'We could not save those interests. Please try again.')

    return render(request, 'accounts/preferences.html', {
        **get_account_shell_context(request.user),
        'active_page': 'preferences',
        'groups': list_interests_by_group(),
        'selected_ids': get_selected_interest_ids(request.user),
        'follows': list_followed_organizations(request.user),
    })


@login_required
@require_POST
def update_followed_organization(request: HttpRequest, slug: str) -> HttpResponse:
    """Mute, unmute or unfollow from the Following list."""
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
    return redirect(f"{reverse('preferences')}#following")
