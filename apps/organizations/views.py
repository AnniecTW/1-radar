from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.views import get_account_shell_context
from apps.discovery.selectors import get_campus_timezone

from .forms import OrganizationForm
from .models import Organization
from .permissions import organization_role, user_can_manage_organization
from .selectors import list_organization_events, list_user_memberships
from .services import create_organization, update_organization_profile


@login_required
@require_http_methods(['GET'])
def list_my_organizations(request: HttpRequest) -> HttpResponse:
    return render(request, 'organizations/list.html', {
        **get_account_shell_context(request.user),
        'memberships': list_user_memberships(request.user),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def create_organization_profile(request: HttpRequest) -> HttpResponse:
    if not request.user.is_campus_verified:
        messages.error(request, 'Verify a campus email to create an organization.')
        return redirect('list_my_organizations')
    form = OrganizationForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        data = {key: value for key, value in form.cleaned_data.items() if key != 'clear_logo'}
        organization = create_organization(creator=request.user, **data)
        messages.success(request, f'{organization.name} is created. You are its Owner.')
        return redirect('show_organization_profile', slug=organization.slug)
    return render(request, 'organizations/form.html', {
        **get_account_shell_context(request.user), 'form': form, 'organization': None,
    })


@require_http_methods(['GET'])
def show_organization_profile(request: HttpRequest, slug: str) -> HttpResponse:
    """FR-56: public to guests and everyone else. Only the Owner sees the edit control."""
    organization = get_object_or_404(Organization, slug=slug)
    upcoming, past = list_organization_events(organization, timezone.now())
    context = {
        'organization': organization,
        'upcoming_events': upcoming,
        'past_events': past,
        'role': organization_role(request.user, organization),
        'can_edit': user_can_manage_organization(request.user, organization),
    }
    if request.user.is_authenticated:
        context.update(get_account_shell_context(request.user))
    with timezone.override(get_campus_timezone()):
        return render(request, 'organizations/profile.html', context)


@login_required
@require_http_methods(['GET', 'POST'])
def edit_organization_profile(request: HttpRequest, slug: str) -> HttpResponse:
    organization = get_object_or_404(Organization, slug=slug)
    if not user_can_manage_organization(request.user, organization):
        # FR-64: only the Owner edits; everyone else is sent back to the public page.
        return redirect('show_organization_profile', slug=slug)
    initial = {
        'name': organization.name, 'org_type': organization.org_type, 'description': organization.description,
        'contact_email': organization.contact_email, 'website_url': organization.website_url or '',
        'instagram_url': organization.instagram_url or '',
    }
    form = OrganizationForm(request.POST, request.FILES) if request.method == 'POST' else OrganizationForm(initial=initial)
    if request.method == 'POST' and form.is_valid():
        update_organization_profile(actor=request.user, organization=organization, **form.cleaned_data)
        messages.success(request, 'Organization profile saved.')
        return redirect('show_organization_profile', slug=organization.slug)
    return render(request, 'organizations/form.html', {
        **get_account_shell_context(request.user), 'form': form, 'organization': organization,
    })
