from django import template
from django.utils import timezone

from ..selectors import get_rsvp_state

register = template.Library()


@register.inclusion_tag('rsvps/_rsvp_button.html', takes_context=True)
def rsvp_button(context, event):
    """The RSVP control for an event. Pages load `radar/rsvp.css` for its styles."""
    request = context['request']
    return {
        'event': event,
        'next': request.get_full_path(),
        'csrf_token': context.get('csrf_token'),
        **get_rsvp_state(request.user, event, timezone.now()),
    }
