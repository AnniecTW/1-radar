import logging
import os
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.views import get_account_shell_context
from apps.discovery.selectors import get_campus_timezone

from .forms import AddMemberForm, DeleteOrganizationForm, MemberRoleForm, OrganizationForm, VerificationRequestForm
from .models import Organization, OrganizationMembership
from .permissions import organization_role, user_can_manage_members, user_can_manage_organization
from .selectors import (
    get_latest_verification_request, list_organization_events, list_organization_members, list_user_memberships,
)
from .services import (
    add_member_by_email, change_member_role, create_organization, delete_organization, leave_organization,
    organization_blocking_events, remove_organization_member, request_organization_verification,
    transfer_organization_ownership, update_organization_profile,
)

logger = logging.getLogger(__name__)


def _profile_fields(form):
    """Form data for the services: a new upload wins, else the logo kept from an earlier try."""
    data = {key: value for key, value in form.cleaned_data.items() if key != 'pending_logo'}
    data['logo'] = data.get('logo') or form.cleaned_data.get('pending_logo') or None
    return data


def _pending_logo(form):
    """After a failed submit, keep the logo the person chose so they don't have to pick it again."""
    from django.core import signing
    from django.core.files.storage import default_storage

    from .forms import PENDING_LOGO_SALT

    if not form.is_bound or form.data.get('clear_logo'):
        return None
    cleaned = getattr(form, 'cleaned_data', None) or {}
    name = cleaned.get('pending_logo') or ''
    upload = cleaned.get('logo')
    if upload:
        extension = os.path.splitext(upload.name)[1].lower()[:10] or '.png'
        try:
            name = default_storage.save(f'organization_logos/{uuid.uuid4().hex}{extension}', upload)
        except Exception:
            logger.exception('Organization logo upload failed')
            return None
    if not name:
        return None
    return {'url': default_storage.url(name), 'token': signing.dumps(name, salt=PENDING_LOGO_SALT)}


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
        data = {key: value for key, value in _profile_fields(form).items() if key != 'clear_logo'}
        try:
            organization = create_organization(creator=request.user, **data)
        except ValidationError as error:
            form.add_error(None, error.messages[0])
        else:
            messages.success(request, f'{organization.name} is created. You are its Owner.')
            return redirect('show_organization_profile', slug=organization.slug)
    return render(request, 'organizations/form.html', {
        **get_account_shell_context(request.user), 'form': form, 'organization': None,
        'pending_logo': _pending_logo(form) if request.method == 'POST' else None,
    })


@require_http_methods(['GET'])
def show_organization_profile(request: HttpRequest, slug: str) -> HttpResponse:
    """FR-56: public to guests and everyone else. Only the Owner sees the edit control."""
    organization = get_object_or_404(Organization, slug=slug)
    upcoming, past = list_organization_events(organization, timezone.now())
    can_edit = user_can_manage_organization(request.user, organization)
    context = {
        'organization': organization,
        'verification_request': get_latest_verification_request(organization) if can_edit else None,
        'upcoming_events': upcoming,
        'past_events': past,
        'role': organization_role(request.user, organization),
        'can_edit': can_edit,
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
        update_organization_profile(actor=request.user, organization=organization, **_profile_fields(form))
        messages.success(request, 'Organization profile saved.')
        return redirect('show_organization_profile', slug=organization.slug)
    return render(request, 'organizations/form.html', {
        **get_account_shell_context(request.user), 'form': form, 'organization': organization,
        'pending_logo': _pending_logo(form) if request.method == 'POST' else None,
    })


@login_required
@require_POST
def request_verification(request: HttpRequest, slug: str) -> HttpResponse:
    organization = get_object_or_404(Organization, slug=slug)
    form = VerificationRequestForm(request.POST)
    if not user_can_manage_organization(request.user, organization) or not form.is_valid():
        return redirect('show_organization_profile', slug=slug)
    try:
        request_organization_verification(
            actor=request.user, organization=organization, note=form.cleaned_data['note']
        )
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, 'Verification requested. A Radar admin will review it.')
    return redirect('show_organization_profile', slug=slug)


def _owner_organization_or_none(request: HttpRequest, slug: str):
    """The organization, or None when the viewer is not its Owner (FR-64)."""
    organization = get_object_or_404(Organization, slug=slug)
    return organization if user_can_manage_members(request.user, organization) else None


@login_required
@require_http_methods(['GET'])
def manage_members(request: HttpRequest, slug: str) -> HttpResponse:
    organization = _owner_organization_or_none(request, slug)
    if organization is None:
        return redirect('show_organization_profile', slug=slug)
    return render(request, 'organizations/members.html', {
        **get_account_shell_context(request.user),
        'organization': organization,
        'members': list_organization_members(organization),
        'add_form': AddMemberForm(),
        'blocking_event_count': organization_blocking_events(organization).count(),
    })


@login_required
@require_POST
def add_member(request: HttpRequest, slug: str) -> HttpResponse:
    organization = _owner_organization_or_none(request, slug)
    if organization is None:
        return redirect('show_organization_profile', slug=slug)
    form = AddMemberForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Enter an email and choose a role.')
    else:
        try:
            membership = add_member_by_email(actor=request.user, organization=organization, **form.cleaned_data)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, f'{membership.user.email} was added as {membership.get_role_display()}.')
    return redirect('manage_organization_members', slug=slug)


@login_required
@require_POST
def set_member_role(request: HttpRequest, slug: str, membership_id: int) -> HttpResponse:
    organization = _owner_organization_or_none(request, slug)
    if organization is None:
        return redirect('show_organization_profile', slug=slug)
    membership = get_object_or_404(OrganizationMembership, pk=membership_id, organization=organization)
    form = MemberRoleForm(request.POST)
    if form.is_valid():
        try:
            change_member_role(actor=request.user, membership=membership, role=form.cleaned_data['role'])
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, f'{membership.user.email} is now {membership.get_role_display()}.')
    return redirect('manage_organization_members', slug=slug)


@login_required
@require_POST
def remove_member(request: HttpRequest, slug: str, membership_id: int) -> HttpResponse:
    organization = _owner_organization_or_none(request, slug)
    if organization is None:
        return redirect('show_organization_profile', slug=slug)
    membership = get_object_or_404(OrganizationMembership, pk=membership_id, organization=organization)
    try:
        remove_organization_member(actor=request.user, membership=membership)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, f'{membership.user.email} was removed.')
    return redirect('manage_organization_members', slug=slug)


@login_required
@require_POST
def make_owner(request: HttpRequest, slug: str, membership_id: int) -> HttpResponse:
    organization = _owner_organization_or_none(request, slug)
    if organization is None:
        return redirect('show_organization_profile', slug=slug)
    membership = get_object_or_404(OrganizationMembership, pk=membership_id, organization=organization)
    try:
        transfer_organization_ownership(
            actor=request.user, organization_id=organization.pk, new_owner_id=membership.user_id
        )
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect('manage_organization_members', slug=slug)
    messages.success(request, f'{membership.user.email} is now the Owner. You are an Admin.')
    return redirect('show_organization_profile', slug=slug)


@login_required
@require_POST
def leave(request: HttpRequest, slug: str) -> HttpResponse:
    organization = get_object_or_404(Organization, slug=slug)
    try:
        leave_organization(user=request.user, organization=organization)
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect('show_organization_profile', slug=slug)
    messages.success(request, f'You left {organization.name}.')
    return redirect('list_my_organizations')


@login_required
@require_POST
def delete(request: HttpRequest, slug: str) -> HttpResponse:
    organization = _owner_organization_or_none(request, slug)
    if organization is None:
        return redirect('show_organization_profile', slug=slug)
    form = DeleteOrganizationForm(request.POST)
    try:
        if not form.is_valid():
            raise ValidationError('Type the organization name to confirm.')
        delete_organization(actor=request.user, organization=organization, **form.cleaned_data)
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect('manage_organization_members', slug=slug)
    messages.success(request, f'{organization.name} was deleted.')
    return redirect('list_my_organizations')
