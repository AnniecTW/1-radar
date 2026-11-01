import secrets
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.events.models import Event
from apps.notifications.models import Notification
from apps.events.permissions import user_can_edit_event

from .models import RSVP, Ticket, TrafficSource
from .permissions import user_can_manage_rsvp


class RSVPServiceError(Exception):
    """Base error for RSVP operations that cannot be completed."""


class EventFullError(RSVPServiceError):
    pass


class RSVPClosedError(RSVPServiceError):
    pass


def _cutoff_at(event):
    return event.start_at - timedelta(minutes=30)


def _notify(user, event, notification_type, **payload):
    return Notification.objects.create(
        user=user,
        event=event,
        type=notification_type,
        payload=payload,
    )


def _going_count(event):
    return RSVP.objects.filter(event=event, status=RSVP.Status.GOING).count()


def _waitlist(event, *, lock=False):
    rows = RSVP.objects.filter(event=event, status=RSVP.Status.WAITLISTED).order_by(
        'waitlisted_at', 'created_at', 'pk'
    )
    if lock:
        rows = rows.select_for_update()
    return rows


def _refresh_waitlist_positions(event):
    for position, rsvp in enumerate(_waitlist(event, lock=True).iterator(), start=1):
        if rsvp.waitlist_position != position:
            rsvp.waitlist_position = position
            rsvp.save(update_fields=['waitlist_position', 'updated_at'])


def _issue_or_refresh_ticket(rsvp):
    ticket, created = Ticket.objects.get_or_create(
        rsvp=rsvp,
        defaults={'code': secrets.token_urlsafe(32), 'status': Ticket.Status.VALID},
    )
    if not created:
        ticket.code = secrets.token_urlsafe(32)
        ticket.status = Ticket.Status.VALID
        ticket.used_at = None
        ticket.issued_at = timezone.now()
        ticket.save(update_fields=['code', 'status', 'used_at', 'issued_at'])
    return ticket


def _promote_waitlisted(event, *, limit=None):
    """Promote FIFO waitlisted RSVPs. Caller must hold the event row lock."""
    candidates = _waitlist(event, lock=True)
    if limit is not None:
        candidates = candidates[:limit]

    promoted = []
    for rsvp in candidates:
        rsvp.status = RSVP.Status.GOING
        rsvp.waitlist_position = None
        rsvp.waitlisted_at = None
        rsvp.cancelled_at = None
        rsvp.save(
            update_fields=['status', 'waitlist_position', 'waitlisted_at', 'cancelled_at', 'updated_at']
        )
        _issue_or_refresh_ticket(rsvp)
        _notify(rsvp.user, event, Notification.Type.WAITLIST_PROMOTED)
        promoted.append(rsvp)

    _refresh_waitlist_positions(event)
    return promoted


def request_rsvp(*, event_id, actor, source=TrafficSource.DIRECT):
    """Create or restore a Going, Waitlisted, or Interested RSVP safely."""
    user = actor
    if not getattr(user, 'is_authenticated', False):
        raise RSVPServiceError('Sign in before responding to an event.')
    if not user.is_email_verified:
        raise RSVPServiceError('Verify your email before responding to an event.')

    with transaction.atomic():
        event = Event.objects.select_for_update().get(pk=event_id)
        now = timezone.now()
        if event.status != Event.Status.PUBLISHED or event.end_at < now:
            raise RSVPClosedError('This event is not accepting responses.')
        if event.visibility == Event.Visibility.CAMPUS_ONLY and not user.is_campus_verified:
            raise RSVPServiceError('A verified campus email is required for this event.')
        if not event.is_free:
            raise RSVPServiceError('Paid events do not accept Radar RSVPs.')

        status = RSVP.Status.INTERESTED if not event.rsvp_required else RSVP.Status.GOING
        rsvp, created = RSVP.objects.get_or_create(
            event=event,
            user=user,
            defaults={'status': RSVP.Status.CANCELLED, 'source': source},
        )
        if rsvp.status == RSVP.Status.GOING:
            return rsvp
        if rsvp.status == RSVP.Status.INTERESTED and status == RSVP.Status.INTERESTED:
            return rsvp

        rsvp.source = source
        rsvp.cancelled_at = None
        rsvp.waitlist_position = None
        rsvp.waitlisted_at = None

        if status == RSVP.Status.INTERESTED:
            rsvp.status = status
            rsvp.save()
            return rsvp

        full = event.capacity is not None and _going_count(event) >= event.capacity
        if rsvp.status == RSVP.Status.WAITLISTED and not full:
            rsvp.status = RSVP.Status.GOING
            rsvp.save()
            _issue_or_refresh_ticket(rsvp)
            _notify(user, event, Notification.Type.WAITLIST_PROMOTED)
            _refresh_waitlist_positions(event)
            return rsvp
        if full:
            after_cutoff = now >= _cutoff_at(event)
            if after_cutoff or not event.waitlist_enabled:
                raise EventFullError('This event is full and is not accepting waitlist responses.')
            rsvp.status = RSVP.Status.WAITLISTED
            rsvp.waitlisted_at = now
            rsvp.save()
            _refresh_waitlist_positions(event)
            rsvp.refresh_from_db()
            _notify(user, event, Notification.Type.WAITLIST_JOINED, position=rsvp.waitlist_position)
            return rsvp

        rsvp.status = RSVP.Status.GOING
        rsvp.save()
        _issue_or_refresh_ticket(rsvp)
        _notify(user, event, Notification.Type.RSVP_CONFIRMED)
        return rsvp


def cancel_rsvp(*, event_id, actor):
    """Cancel an active RSVP and promote the FIFO queue before the cutoff."""
    if not getattr(actor, 'is_authenticated', False):
        raise PermissionDenied('Sign in before cancelling an RSVP.')
    with transaction.atomic():
        event = Event.objects.select_for_update().get(pk=event_id)
        rsvp = RSVP.objects.select_for_update().get(event=event, user=actor)
        if not user_can_manage_rsvp(actor, rsvp):
            raise PermissionDenied('You cannot cancel another attendee RSVP.')
        if rsvp.status == RSVP.Status.CANCELLED:
            return rsvp

        was_going = rsvp.status == RSVP.Status.GOING
        rsvp.status = RSVP.Status.CANCELLED
        rsvp.cancelled_at = timezone.now()
        rsvp.waitlist_position = None
        rsvp.waitlisted_at = None
        rsvp.save(
            update_fields=['status', 'cancelled_at', 'waitlist_position', 'waitlisted_at', 'updated_at']
        )
        Ticket.objects.filter(rsvp=rsvp).update(status=Ticket.Status.VOID)

        if was_going and timezone.now() < _cutoff_at(event) and event.capacity is not None:
            _promote_waitlisted(event, limit=1)
        else:
            _refresh_waitlist_positions(event)
        return rsvp


def update_event_capacity(*, actor, event_id, capacity):
    """Update capacity and promote eligible waitlisted users in the same transaction."""
    if capacity is not None and capacity < 0:
        raise ValidationError({'capacity': 'Capacity cannot be negative.'})

    with transaction.atomic():
        event = Event.objects.select_for_update(of=('self',)).select_related('organization').get(pk=event_id)
        if not user_can_edit_event(actor, event):
            raise PermissionDenied('You cannot change this event capacity.')
        going = _going_count(event)
        if capacity is not None and capacity < going:
            raise ValidationError(
                {'capacity': f'{going} people are already going; capacity cannot be lower than {going}.'}
            )

        old_capacity = event.capacity
        event.capacity = capacity
        event.save(update_fields=['capacity', 'updated_at'])

        if capacity is None:
            _promote_waitlisted(event)
        elif (old_capacity is None or capacity > old_capacity) and timezone.now() < _cutoff_at(event):
            new_slots = capacity - going
            if old_capacity is not None:
                new_slots = capacity - old_capacity
            if new_slots > 0:
                _promote_waitlisted(event, limit=new_slots)
        return event


def send_waitlist_heads_up(*, event_id):
    """Notify people who were waitlisted at the 24-hour reminder point."""
    with transaction.atomic():
        event = Event.objects.select_for_update().get(pk=event_id)
        scheduled_at = event.start_at - timedelta(hours=24)
        waitlisted = _waitlist(event, lock=True).filter(waitlisted_at__lte=scheduled_at)
        for rsvp in waitlisted:
            already_sent = Notification.objects.filter(
                user=rsvp.user,
                event=event,
                type=Notification.Type.WAITLIST_HEADS_UP,
            ).exists()
            if not already_sent:
                _notify(rsvp.user, event, Notification.Type.WAITLIST_HEADS_UP)


def close_waitlist(*, event_id):
    """Send the one-time cutoff notice; waiting RSVPs remain in place but won't auto-promote."""
    with transaction.atomic():
        event = Event.objects.select_for_update().get(pk=event_id)
        for rsvp in _waitlist(event, lock=True):
            already_sent = Notification.objects.filter(
                user=rsvp.user,
                event=event,
                type=Notification.Type.WAITLIST_CLOSED,
            ).exists()
            if not already_sent:
                _notify(rsvp.user, event, Notification.Type.WAITLIST_CLOSED)
