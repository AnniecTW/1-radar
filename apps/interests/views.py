from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.views import get_safe_next_url
from apps.organizations.models import Organization, OrganizationFollow
from apps.organizations.services import follow_organization

from .forms import InterestsForm
from .selectors import get_selected_interest_ids, list_interests_by_group, list_suggested_organizations
from .services import complete_onboarding, save_onboarding_interests


def with_next(url_name: str, next_url: str) -> str:
    return f"{reverse(url_name)}?{urlencode({'next': next_url})}"


@login_required
@require_http_methods(['GET', 'POST'])
def pick_interests(request: HttpRequest) -> HttpResponse:
    """Step 1 (FR-8): at least 3 interests plus optional major and graduation year."""
    next_url = get_safe_next_url(request)
    form = InterestsForm(request.POST) if request.method == 'POST' else InterestsForm()
    if request.method == 'POST' and form.is_valid():
        save_onboarding_interests(
            user=request.user,
            interests=form.cleaned_data['interests'],
            major=form.cleaned_data['major'],
            graduation_year=form.cleaned_data['graduation_year'],
        )
        return redirect(with_next('onboarding_organizations', next_url))

    profile = request.user.profile
    selected_ids = (
        {interest.pk for interest in form.cleaned_data.get('interests', [])}
        if request.method == 'POST'
        else get_selected_interest_ids(request.user)
    )
    return render(request, 'onboarding/interests.html', {
        'form': form,
        'next': next_url,
        'groups': list_interests_by_group(),
        'selected_ids': selected_ids,
        'major': request.POST.get('major', profile.major or '') if request.method == 'POST' else profile.major or '',
        'graduation_year': request.POST.get('graduation_year', profile.graduation_year or '')
        if request.method == 'POST' else profile.graduation_year or '',
    })


@login_required
@require_http_methods(['GET', 'POST'])
def suggest_organizations(request: HttpRequest) -> HttpResponse:
    """Step 2 (FR-61): optional follows. Posting here finishes onboarding."""
    next_url = get_safe_next_url(request)
    if request.method == 'POST':
        chosen = Organization.objects.filter(pk__in=request.POST.getlist('organizations'))
        for organization in chosen:
            follow_organization(
                user=request.user, organization=organization, source=OrganizationFollow.Source.ONBOARDING
            )
        complete_onboarding(request.user)
        return redirect(next_url)
    return render(request, 'onboarding/organizations.html', {
        'next': next_url,
        'organizations': list_suggested_organizations(request.user),
    })


@login_required
@require_POST
def skip_onboarding(request: HttpRequest) -> HttpResponse:
    """FR-9: skipping leaves recommendations on popularity; interests stay editable later."""
    complete_onboarding(request.user)
    return redirect(get_safe_next_url(request))
