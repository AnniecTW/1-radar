from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.events.models import Event
from apps.rsvps.models import RSVP, Ticket

from .models import CheckIn
from .permissions import user_can_check_in_attendees


@transaction.atomic
def check_in_with_ticket(*, actor, event_id, ticket_code):
    event = Event.objects.select_for_update().get(pk=event_id)
    if not user_can_check_in_attendees(actor, event):
        raise PermissionDenied('You are not assigned to check in this event.')
    ticket = Ticket.objects.select_for_update().select_related('rsvp__user', 'rsvp__event').get(
        code=ticket_code
    )
    if ticket.rsvp.event_id != event.pk:
        raise ValidationError('This ticket is for a different event.')
    if ticket.status != Ticket.Status.VALID:
        raise ValidationError('This ticket is no longer valid.')
    checkin, created = CheckIn.objects.get_or_create(
        event=event,
        user=ticket.rsvp.user,
        defaults={
            'ticket': ticket,
            'method': CheckIn.Method.HOST_SCAN,
            'checked_in_by': actor,
        },
    )
    if not created:
        raise ValidationError('This attendee is already checked in.')
    ticket.status = Ticket.Status.USED
    ticket.used_at = timezone.now()
    ticket.save(update_fields=['status', 'used_at'])
    return checkin


@transaction.atomic
def manual_check_in(*, actor, event_id, attendee_id):
    event = Event.objects.select_for_update().get(pk=event_id)
    if not user_can_check_in_attendees(actor, event):
        raise PermissionDenied('You are not assigned to check in this event.')
    rsvp = RSVP.objects.select_for_update().filter(
        event=event, user_id=attendee_id, status=RSVP.Status.GOING
    ).first()
    if rsvp is None:
        raise ValidationError('The attendee must have a Going RSVP.')
    ticket = Ticket.objects.filter(rsvp=rsvp).first()
    checkin, created = CheckIn.objects.get_or_create(
        event=event,
        user_id=attendee_id,
        defaults={
            'ticket': ticket,
            'method': CheckIn.Method.MANUAL,
            'checked_in_by': actor,
        },
    )
    if not created:
        raise ValidationError('This attendee is already checked in.')
    if checkin.ticket_id:
        Ticket.objects.filter(pk=checkin.ticket_id).update(
            status=Ticket.Status.USED, used_at=timezone.now()
        )
    return checkin
