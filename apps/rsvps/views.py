from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.views import get_safe_next_url
from apps.events.models import Event

from .models import RSVP
from .services import RSVPServiceError, cancel_rsvp, request_rsvp

SUCCESS_MESSAGES = {
    RSVP.Status.GOING: "You're going! It's on your Profile under My Tickets.",
    RSVP.Status.INTERESTED: 'Marked as interested.',
}


@require_POST
def rsvp_to_event_or_cancel(request: HttpRequest, event_id) -> HttpResponse:
    """RSVP, join the waitlist, tap Interested, or cancel. HTML forms can't send DELETE, so `action` picks."""
    next_url = get_safe_next_url(request)
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?{urlencode({'next': next_url})}")
    event = get_object_or_404(Event, pk=event_id)

    if request.POST.get('action') == 'cancel':
        try:
            rsvp = cancel_rsvp(event_id=event.pk, actor=request.user)
        except (RSVP.DoesNotExist, PermissionDenied):
            messages.error(request, "You don't have an RSVP for this event.")
        else:
            messages.success(request, 'Your RSVP is cancelled.')
        return redirect(next_url)

    try:
        rsvp = request_rsvp(event_id=event.pk, actor=request.user)
    except RSVPServiceError as error:
        messages.error(request, str(error))
    else:
        if rsvp.status == RSVP.Status.WAITLISTED:
            messages.success(request, f"This event is full. You're #{rsvp.waitlist_position} on the waitlist.")
        else:
            messages.success(request, SUCCESS_MESSAGES[rsvp.status])
    return redirect(next_url)
