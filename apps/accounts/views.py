import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from .exceptions import EmailAlreadyRegisteredError, InvalidVerificationTokenError
from .forms import LoginForm, SignupForm
from .services import (
    create_user_account,
    make_verification_token,
    send_verification_email,
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
