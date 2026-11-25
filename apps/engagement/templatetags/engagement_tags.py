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
    # A page listing several organizations can pass followed_organization_ids, found in one query, instead
    # of one query per button.
    followed_ids = context.get('followed_organization_ids')
    if not data['signed_in']:
        active = False
    elif followed_ids is not None:
        active = organization.pk in followed_ids
    else:
        active = OrganizationFollow.objects.filter(user=user, organization=organization).exists()
    data.update(organization=organization, source=source, active=active)
    return data
