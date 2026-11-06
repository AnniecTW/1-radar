import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.analytics.permissions import user_can_export_attendees, user_can_view_analytics

from .forms import VISIBILITY_NOTES, EventForm
from .models import Event
from .permissions import user_can_edit_event
from .selectors import (
    MY_EVENT_TABS,
    get_missing_publish_fields,
    get_my_events_summary,
    list_host_organizations,
    list_my_events,
)
from .services import cancel_event, publish_event, save_event_from_form

MAX_CANCEL_REASON_LENGTH = 500
logger = logging.getLogger(__name__)


def show_event_detail(request, slug):
    event = Event.objects.select_related('organization', 'venue', 'host_user').prefetch_related('interests').filter(slug=slug).first()
    if event is None:
        raise Http404
    if event.visibility == Event.Visibility.UNLISTED:
        pass
    elif event.status == Event.Status.DRAFT:
        if not request.user.is_authenticated or not (request.user == event.host_user or request.user.is_staff):
            raise Http404
    elif event.status not in (Event.Status.PUBLISHED, Event.Status.CANCELLED, Event.Status.COMPLETED):
        raise Http404
    counts=event.rsvps.aggregate(
        going=Count('id',filter=Q(status='going')),
        interested=Count('id',filter=Q(status='interested')),
    )
    return render(request,'events/detail.html',{'event':event,'going_count':counts['going'],
        'interested_count':counts['interested'],'now':timezone.now()})


def _decorate_hosted_event(event, user, now, tz):
    """Per-row permissions and display values for My Events."""
    event.can_manage = user_can_edit_event(user, event)
    event.can_view_analytics = user_can_view_analytics(user, event)
    event.can_export = user_can_export_attendees(user, event)
    if event.status == Event.Status.DRAFT:
        event.missing_fields = get_missing_publish_fields(event)
    if event.capacity and event.going_count:
        event.fill_percent = min(100, round(event.going_count * 100 / event.capacity))
    event.is_full = bool(event.capacity and event.going_count >= event.capacity)
    if event.status == Event.Status.PUBLISHED and event.start_at:
        if event.start_at <= now:
            event.countdown = 'Happening now'
        else:
            days = (timezone.localtime(event.start_at, tz).date() - timezone.localtime(now, tz).date()).days
            event.countdown = {0: 'Today', 1: 'Tomorrow'}.get(days, f'In {days} days')


@login_required
@require_GET
def show_my_events(request):
    """My Dashboard: events the user hosts or manages, drafts, past events, and check-in assignments."""
    from apps.accounts.views import get_account_shell_context
    from apps.discovery.selectors import get_campus_timezone

    now = timezone.now()
    tz = get_campus_timezone()
    user = request.user
    tab = request.GET.get('tab', 'upcoming')
    if tab not in dict(MY_EVENT_TABS):
        tab = 'upcoming'
    organizations = list(list_host_organizations(user))
    host = request.GET.get('host', '')
    if host not in {'', 'me', *(org.slug for org in organizations)}:
        host = ''

    lists = {key: list(list_my_events(user, key, now, host)) for key, _ in MY_EVENT_TABS}
    rows = lists[tab]
    next_up = lists['upcoming'][0] if lists['upcoming'] else None
    for event in {*rows, *([next_up] if next_up else [])}:
        _decorate_hosted_event(event, user, now, tz)

    context = {
        **get_account_shell_context(user),
        'active_nav': 'my_dashboard',
        'tab': tab,
        'tabs': [(key, label, len(lists[key])) for key, label in MY_EVENT_TABS],
        'rows': rows,
        'next_up': next_up,
        'staff_view': tab == 'staff',
        'past': tab == 'past',
        'host': host,
        'organizations': organizations,
        'upcoming_count': len(lists['upcoming']),
        'draft_count': len(lists['drafts']),
        'summary': get_my_events_summary(lists['upcoming'], lists['past']),
        'now': now,
    }
    with timezone.override(tz):
        return render(request, 'events/my_events.html', context)


def _back_to_my_events(request):
    next_url = request.POST.get('next', '')
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect(reverse('my_events'))


@login_required
@require_POST
def cancel_hosted_event(request, event_id):
    reason = request.POST.get('reason', '').strip()[:MAX_CANCEL_REASON_LENGTH]
    try:
        event = cancel_event(actor=request.user, event_id=event_id, reason=reason)
    except Event.DoesNotExist:
        raise Http404
    except PermissionDenied:
        messages.error(request, "You can't cancel this event.")
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    else:
        messages.success(request, f'{event.title} is cancelled. Everyone who RSVP’d will be notified.')
    return _back_to_my_events(request)


@login_required
@require_POST
def publish_draft_event(request, event_id):
    try:
        event = publish_event(actor=request.user, event_id=event_id)
    except Event.DoesNotExist:
        raise Http404
    except PermissionDenied:
        messages.error(request, "You can't publish this event.")
    except ValidationError as error:
        messages.error(request, 'Not ready to publish: ' + ' '.join(error.messages))
    else:
        messages.success(request, f'{event.title} is live on the feed and map.')
    return _back_to_my_events(request)


def _save_cover(upload):
    import os
    import uuid

    from django.core.files.storage import default_storage

    extension = os.path.splitext(upload.name)[1].lower()[:10] or '.jpg'
    name = default_storage.save(f'event_covers/{uuid.uuid4().hex}{extension}', upload)
    return default_storage.url(name)


def _form_fields(data, event):
    from django.contrib.gis.geos import Point

    if data.get('latitude') is not None and data.get('longitude') is not None:
        location = Point(data['longitude'], data['latitude'], srid=4326)
    elif data.get('venue'):
        location = data['venue'].location
    else:
        location = None
    cover_image = event.cover_image if event else ''
    if data.get('cover'):
        cover_image = _save_cover(data['cover'])
    elif data.get('remove_cover'):
        cover_image = ''
    return {
        'title': (data.get('title') or '').strip(),
        'description': (data.get('description') or '').strip(),
        'start_at': data.get('start_at'),
        'end_at': data.get('end_at'),
        'venue': data.get('venue'),
        'location_text': (data.get('location_text') or '').strip(),
        'location': location,
        'cover_image': cover_image,
        'visibility': data.get('visibility') or Event.Visibility.PUBLIC,
        'rsvp_required': data.get('kind') != 'drop_in',
        'waitlist_enabled': bool(data.get('waitlist_enabled')),
        'is_free': data.get('kind') != 'paid',
        'price_text': (data.get('price_text') or '').strip(),
        'external_url': data.get('external_url') or None,
        'contact_info': (data.get('contact_info') or '').strip() or None,
    }


def _apply_service_errors(form, error):
    if hasattr(error, 'error_dict'):
        for field, messages_list in error.message_dict.items():
            target = {'start_at': 'date', 'end_at': 'end_time', 'venue': 'location_text', 'slug': None}.get(field, field)
            form.add_error(target if target in form.fields else None, messages_list)
    else:
        form.add_error(None, error.messages)


def _save(request, form, event, organizations):
    """Save the form as a draft (or into a published event). Returns the event, or None with form errors added."""
    data = form.cleaned_data
    organization = None
    if event is None and data['host'] != 'me':
        organization = next(org for org in organizations if org.slug == data['host'])
    try:
        fields = _form_fields(data, event)
    except Exception:
        # Image storage misconfigured or unreachable: keep the form instead of a crash page.
        logger.exception('Event cover upload failed')
        form.add_error('cover', "The image couldn't be uploaded right now. Save without it, or try again later.")
        return None
    try:
        return save_event_from_form(
            actor=request.user, event=event, organization=organization,
            fields=fields, capacity=data.get('capacity'), interests=data.get('interests', []),
        )
    except ValidationError as error:
        _apply_service_errors(form, error)
    except PermissionDenied:
        form.add_error(None, "You can't host events for this organization.")
    return None


def _event_form_page(request, event):
    """Shared by Create Event and Edit Event (FR-17, FR-22)."""
    from apps.accounts.views import get_account_shell_context
    from apps.discovery.selectors import get_campus_center, get_campus_timezone

    user = request.user
    tz = get_campus_timezone()
    shell = get_account_shell_context(user)
    context = {**shell, 'active_nav': 'create_event' if event is None else 'my_dashboard', 'event': event}
    if not user.is_campus_verified:
        context['needs_campus'] = True
        return render(request, 'events/event_form.html', context)

    organizations = list(list_host_organizations(user))
    choices = [('me', f"Myself ({shell['display_name']})")] + [(org.slug, org.name) for org in organizations]
    action = request.POST.get('action', 'save')
    is_published = bool(event and event.status == Event.Status.PUBLISHED)
    form_kwargs = {'host_choices': choices, 'tz': tz}

    if request.method == 'POST':
        publishing = action == 'publish' or is_published
        form = EventForm(request.POST, request.FILES, publishing=publishing, **form_kwargs)
        if event:
            form.fields['host'].disabled = True
            form.fields['host'].initial = 'me' if not event.organization_id else event.organization.slug
        if form.is_valid():
            saved = _save(request, form, event, organizations)
            if saved and is_published:
                messages.success(request, f'Changes to {saved.title} are saved.')
                return redirect('my_events')
            if saved and action == 'publish':
                try:
                    saved = publish_event(actor=user, event_id=saved.pk)
                except ValidationError as error:
                    messages.error(request, 'Draft saved, but it is not ready to publish: ' + ' '.join(error.messages))
                    return redirect('edit_event', event_id=saved.pk)
                messages.success(request, f'{saved.title} is live on the feed and map.')
                return redirect('event_detail', slug=saved.slug)
            if saved:
                messages.success(request, 'Draft saved. Find it any time under My Dashboard › Drafts.')
                return redirect('edit_event', event_id=saved.pk)
        elif publishing and not is_published:
            # Keep the work: save what's there as a draft, then show what publishing still needs.
            draft = EventForm(request.POST, request.FILES, publishing=False, **form_kwargs)
            if event:
                draft.fields['host'].disabled = True
                draft.fields['host'].initial = form.fields['host'].initial
            if draft.is_valid():
                saved = _save(request, draft, event, organizations)
                if saved:
                    event = saved
                    context['event'] = saved
                    context['saved_as_draft'] = True
    else:
        initial = EventForm.initial_from_event(event, tz) if event else {}
        if not event and request.GET.get('host') in dict(choices):
            initial['host'] = request.GET['host']
        form = EventForm(initial=initial, **form_kwargs)
        if event:
            form.fields['host'].disabled = True

    center = get_campus_center()
    context.update({
        'form': form,
        'is_published': is_published,
        'organizations': organizations,
        'verified_slugs': [org.slug for org in organizations if org.is_verified],
        'visibility_notes': VISIBILITY_NOTES,
        'map_center': {'lat': center[0], 'lng': center[1]} if center else {'lat': 40.1020, 'lng': -88.2272},
        'venue_points': {
            str(venue.pk): {'lat': venue.location.y, 'lng': venue.location.x}
            for venue in form.fields['venue'].queryset if venue.location
        },
    })
    with timezone.override(tz):
        return render(request, 'events/event_form.html', context)


@login_required
@require_http_methods(['GET', 'POST'])
def create_event_page(request):
    return _event_form_page(request, None)


@login_required
@require_http_methods(['GET', 'POST'])
def edit_event_page(request, event_id):
    event = Event.objects.select_related('organization', 'venue').filter(pk=event_id).first()
    if event is None or not user_can_edit_event(request.user, event):
        raise Http404
    if event.status == Event.Status.PUBLISHED and event.start_at and event.start_at <= timezone.now():
        messages.error(request, "This event has already started, so it can't be edited.")
        return redirect('my_events')
    if event.status not in (Event.Status.DRAFT, Event.Status.PUBLISHED):
        messages.error(request, "Cancelled and finished events can't be edited.")
        return redirect('my_events')
    return _event_form_page(request, event)
