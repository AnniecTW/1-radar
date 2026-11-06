from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.organizations.models import OrganizationMembership
from apps.organizations.permissions import user_can_manage_events
from apps.notifications.models import Notification
from apps.rsvps.models import RSVP, Ticket

from .models import Event, EventCheckInStaff, EventReport
from .permissions import user_can_edit_event


def _unique_event_slug(event):
    base = slugify(event.title)[:170].strip('-') or f'event-{event.pk.hex[:12]}'
    slug = base
    suffix = 2
    while Event.objects.filter(slug=slug).exclude(pk=event.pk).exists():
        suffix_text = f'-{suffix}'
        slug = f'{base[:170 - len(suffix_text)]}{suffix_text}'
        suffix += 1
    return slug


@transaction.atomic
def create_event(*, actor, organization=None, **fields):
    if not getattr(actor, 'is_authenticated', False) or not actor.is_campus_verified:
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied('A verified campus member is required to host events.')
    if organization and not user_can_manage_events(actor, organization):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied('You cannot create events for this organization.')
    if fields.get('status', Event.Status.DRAFT) != Event.Status.DRAFT:
        raise ValidationError('Create the event as a draft, then publish it through publish_event.')
    fields.pop('host_user', None)
    return Event.objects.create(host_user=actor, organization=organization, **fields)


@transaction.atomic
def update_event(*, actor, event_id, changes):
    event = Event.objects.select_for_update(of=('self',)).select_related('organization', 'venue').get(pk=event_id)
    if not user_can_edit_event(actor, event):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied('You cannot edit this event.')
    protected_fields = {'id', 'host_user', 'organization', 'status', 'capacity', 'published_at'}
    if protected_fields.intersection(changes):
        raise ValidationError('Use a dedicated service to change protected event fields.')
    for field, value in changes.items():
        if field not in {field.name for field in Event._meta.fields}:
            raise ValidationError({field: 'Unknown event field.'})
        setattr(event, field, value)
    if event.status == Event.Status.PUBLISHED:
        event.full_clean()
    event.save()
    return event


def assign_checkin_staff(*, actor, event_id, user_id):
    with transaction.atomic():
        event = Event.objects.select_for_update(of=('self',)).select_related('organization').get(pk=event_id)
        if not event.organization_id or not user_can_manage_events(actor, event.organization):
            raise ValidationError('Only the organization Owner or Admin can assign event staff.')
        membership = OrganizationMembership.objects.filter(
            organization=event.organization,
            user_id=user_id,
            role=OrganizationMembership.Role.CHECKIN_STAFF,
        ).first()
        if membership is None:
            raise ValidationError('The assignee must be Check-in Staff for this organization.')
        assignment, _ = EventCheckInStaff.objects.get_or_create(
            event=event, user=membership.user, defaults={'assigned_by': actor}
        )
        return assignment


def remove_checkin_staff_assignment(*, actor, event_id, user_id):
    event = Event.objects.select_related('organization').get(pk=event_id)
    if not event.organization_id or not user_can_manage_events(actor, event.organization):
        raise ValidationError('Only the organization Owner or Admin can remove event staff.')
    EventCheckInStaff.objects.filter(event=event, user_id=user_id).delete()


@transaction.atomic
def cancel_event(*, actor, event_id, reason=''):
    event = Event.objects.select_for_update(of=('self',)).select_related('organization').get(pk=event_id)
    allowed = (
        user_can_manage_events(actor, event.organization)
        if event.organization_id
        else actor.is_authenticated and event.host_user_id == actor.pk
    )
    if not allowed:
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied('You cannot cancel this event.')
    if event.status != Event.Status.PUBLISHED:
        raise ValidationError('Only a published event can be cancelled.')
    event.status = Event.Status.CANCELLED
    event.cancel_reason = reason
    event.cancelled_at = timezone.now()
    event.save(update_fields=['status', 'cancel_reason', 'cancelled_at', 'updated_at'])
    for rsvp in RSVP.objects.filter(
        event=event,
        status__in=[RSVP.Status.GOING, RSVP.Status.WAITLISTED, RSVP.Status.INTERESTED],
    ).select_related('user'):
        Notification.objects.create(
            user=rsvp.user,
            event=event,
            type=Notification.Type.EVENT_CANCELLED,
            payload={'reason': reason},
        )
        Ticket.objects.filter(rsvp=rsvp).update(status=Ticket.Status.VOID, used_at=None)
    return event


@transaction.atomic
def report_event(*, actor, event_id, reason, details=''):
    if not getattr(actor, 'is_authenticated', False):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied('Sign in before reporting an event.')
    event = Event.objects.select_for_update().get(pk=event_id)
    if event.host_user_id == actor.pk:
        raise ValidationError('You cannot report your own event.')
    already_open = EventReport.objects.filter(
        event=event, reported_by=actor, status=EventReport.Status.OPEN
    ).exists()
    if already_open:
        raise ValidationError('You already have an open report for this event.')
    report = EventReport(event=event, reported_by=actor, reason=reason, details=details)
    report.full_clean()
    report.save()
    return report


def publish_event(*, actor, event_id):
    """Validate a draft, generate its public slug, and publish it atomically."""
    with transaction.atomic():
        event = Event.objects.select_for_update(of=('self',)).select_related('organization', 'venue').get(pk=event_id)
        if event.organization_id:
            allowed = user_can_manage_events(actor, event.organization)
        else:
            allowed = actor.is_authenticated and event.host_user_id == actor.pk
        if not allowed:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied('You cannot publish this event.')
        if event.status != Event.Status.DRAFT:
            raise ValidationError('Only a draft event can be published.')

        if not event.slug:
            event.slug = _unique_event_slug(event)
        event.status = Event.Status.PUBLISHED
        event.published_at = timezone.now()
        event.full_clean()
        event.save(update_fields=['slug', 'status', 'published_at', 'updated_at'])
        return event


# Fields the Create/Edit Event form writes directly. Capacity goes through update_event_capacity.
EVENT_FORM_FIELDS = (
    'title', 'description', 'start_at', 'end_at', 'venue', 'location_text', 'location', 'cover_image',
    'visibility', 'rsvp_required', 'waitlist_enabled', 'is_free', 'price_text', 'external_url', 'contact_info',
)
# Changes attendees are told about (FR-22).
NOTIFY_ON_CHANGE = ('start_at', 'end_at', 'venue_id', 'location_text')


def set_event_interests(*, event, interests):
    from .models import EventInterest

    wanted = {interest.pk for interest in interests}
    EventInterest.objects.filter(event=event).exclude(interest_id__in=wanted).delete()
    existing = set(EventInterest.objects.filter(event=event).values_list('interest_id', flat=True))
    EventInterest.objects.bulk_create([EventInterest(event=event, interest_id=pk) for pk in wanted - existing])


@transaction.atomic
def save_event_from_form(*, actor, event=None, organization=None, fields, capacity, interests):
    """Create a draft, or update a draft or published event, from the manual form.

    Returns the saved event. Publishing stays a separate step (publish_event).
    """
    from apps.rsvps.services import update_event_capacity

    fields = {key: fields[key] for key in EVENT_FORM_FIELDS if key in fields}
    if event is None:
        event = create_event(actor=actor, organization=organization, **fields)
        before = {}
    else:
        before = {key: getattr(event, key) for key in NOTIFY_ON_CHANGE}
        event = update_event(actor=actor, event_id=event.pk, changes=fields)
    if capacity != event.capacity:
        event = update_event_capacity(actor=actor, event_id=event.pk, capacity=capacity)
    set_event_interests(event=event, interests=interests)

    changed = before and event.status == Event.Status.PUBLISHED and any(
        getattr(event, key) != value for key, value in before.items()
    )
    if changed:
        for rsvp in RSVP.objects.filter(
            event=event, status__in=[RSVP.Status.GOING, RSVP.Status.WAITLISTED, RSVP.Status.INTERESTED]
        ):
            Notification.objects.create(user_id=rsvp.user_id, event=event, type=Notification.Type.EVENT_UPDATED,
                                        payload={'changed': 'time or place'})
    return event
