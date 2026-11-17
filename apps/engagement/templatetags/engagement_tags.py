"""Save, Like and Follow buttons for any page: {% load engagement_tags %}{% save_button event %}."""
from django import template

from apps.engagement.models import EventLike, EventSave
from apps.organizations.models import OrganizationFollow

register = template.Library()


def _base(context, variant):
    request = context.get('request')
    user = getattr(request, 'user', None)
    return {
        'csrf_token': context.get('csrf_token'),
        'next': request.get_full_path() if request else '/',
        'signed_in': bool(user and user.is_authenticated),
        'variant': variant,
    }, user


@register.inclusion_tag('engagement/_save_button.html', takes_context=True)
def save_button(context, event, variant=''):
    data, user = _base(context, variant)
    data.update(event=event, active=data['signed_in'] and EventSave.objects.filter(user=user, event=event).exists())
    return data


@register.inclusion_tag('engagement/_like_button.html', takes_context=True)
def like_button(context, event, variant=''):
    data, user = _base(context, variant)
    data.update(
        event=event,
        active=data['signed_in'] and EventLike.objects.filter(user=user, event=event).exists(),
        count=EventLike.objects.filter(event=event).count(),
    )
    return data


@register.inclusion_tag('engagement/_follow_button.html', takes_context=True)
def follow_button(context, organization, source='org_page', variant=''):
    data, user = _base(context, variant)
    data.update(
        organization=organization,
        source=source,
        active=data['signed_in'] and OrganizationFollow.objects.filter(user=user, organization=organization).exists(),
    )
    return data
