from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from .models import Event


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
