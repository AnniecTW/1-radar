from urllib.parse import urlencode

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.organizations.models import Organization, OrganizationFollow
from apps.organizations.services import follow_organization, unfollow_organization

from .models import EventLike, EventOutboundClick, EventSave
from .services import get_engageable_event, record_outbound_click, set_event_liked, set_event_saved


def _wants_json(request):
    return 'application/json' in request.headers.get('Accept', '')


def _next_url(request):
    from apps.accounts.views import get_safe_next_url

    return get_safe_next_url(request)


def _sign_in_first(request):
    """Guests go to sign in, then come back to the page they were on (PRD guest gate)."""
    login_url = f"{reverse('login')}?{urlencode({'next': _next_url(request)})}"
    if _wants_json(request):
        return JsonResponse({'login_url': login_url}, status=401)
    return redirect(login_url)


def _reply(request, payload, message):
    if _wants_json(request):
        return JsonResponse(payload)
    messages.success(request, message)
    return redirect(_next_url(request))


@require_POST
def save_event(request, event_id):
    if not request.user.is_authenticated:
        return _sign_in_first(request)
    event = get_engageable_event(event_id)
    saved = set_event_saved(user=request.user, event=event, saved=request.POST.get('saved') == '1')
    return _reply(request, {'active': saved},
                  f'Saved {event.title}. Find it on your Profile.' if saved else f'Removed {event.title} from saved.')


@require_POST
def like_event(request, event_id):
    if not request.user.is_authenticated:
        return _sign_in_first(request)
    event = get_engageable_event(event_id)
    liked = set_event_liked(user=request.user, event=event, liked=request.POST.get('liked') == '1')
    count = EventLike.objects.filter(event=event).count()
    return _reply(request, {'active': liked, 'count': count}, f'You liked {event.title}.' if liked else 'Like removed.')


@require_POST
def follow_organization_view(request, slug):
    if not request.user.is_authenticated:
        return _sign_in_first(request)
    organization = get_object_or_404(Organization, slug=slug)
    following = request.POST.get('following') == '1'
    if following:
        source = request.POST.get('source', '')
        if source not in OrganizationFollow.Source.values:
            source = OrganizationFollow.Source.ORG_PAGE
        follow_organization(user=request.user, organization=organization, source=source)
    else:
        unfollow_organization(user=request.user, organization=organization)
    count = Organization.objects.values_list('follower_count', flat=True).get(pk=organization.pk)
    return _reply(request, {'active': following, 'count': count},
                  f'You follow {organization.name}.' if following else f'You unfollowed {organization.name}.')


@require_GET
def go_to_tickets(request, event_id):
    """Count the "Get tickets" click, then send the person to the host's own ticket page (FR-35)."""
    event = get_engageable_event(event_id)
    url = event.external_url or ''
    if event.is_free or not url.lower().startswith(('https://', 'http://')):
        raise Http404
    if not request.session.session_key and not request.user.is_authenticated:
        request.session.save()
    record_outbound_click(
        event=event, user=request.user if request.user.is_authenticated else None,
        session_key=request.session.session_key or '', kind=EventOutboundClick.Kind.TICKETS_LINK,
    )
    return redirect(url)
