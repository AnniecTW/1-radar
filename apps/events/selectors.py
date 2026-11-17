from django.db.models import Count, F, Q, QuerySet

from .models import Event


def filter_discoverable_events(queryset: QuerySet[Event]) -> QuerySet[Event]:
    """The one visibility rule for feeds, landing page, map and search (FR-72).

    Unlisted events are reachable only by direct link, and drafts and cancelled events never list.
    """
    return queryset.filter(
        status=Event.Status.PUBLISHED,
        visibility__in=[Event.Visibility.PUBLIC, Event.Visibility.CAMPUS_ONLY],
    )


def list_hosted_events(user) -> QuerySet[Event]:
    """Events the user created, newest first. Drafts may not have a start time yet."""
    going = Count('rsvps', filter=Q(rsvps__status='going'), distinct=True)
    return (
        Event.objects.filter(host_user=user)
        .exclude(status=Event.Status.CANCELLED)
        .select_related('organization', 'venue')
        .annotate(going_count=going)
        .order_by(F('start_at').desc(nulls_first=True))
    )


MY_EVENT_TABS = [
    ('upcoming', 'Upcoming'),
    ('drafts', 'Drafts'),
    ('past', 'Past'),
    ('staff', 'Check-in staff'),
]


def list_host_organizations(user):
    """Organizations whose events the user can manage (Owner or Admin)."""
    from apps.organizations.models import Organization, OrganizationMembership

    return Organization.objects.filter(
        memberships__user=user,
        memberships__role__in=[OrganizationMembership.Role.OWNER, OrganizationMembership.Role.ADMIN],
    ).order_by('name')


def list_my_events(user, tab: str, now, host: str = '') -> QuerySet[Event]:
    """One My Events tab. `host` is '' for everything, 'me' for personal events, or an organization slug."""
    from apps.organizations.models import OrganizationMembership

    if tab == 'staff':
        events = Event.objects.filter(
            checkin_staff_assignments__user=user, status=Event.Status.PUBLISHED, end_at__gt=now
        )
    else:
        managed_orgs = OrganizationMembership.objects.filter(
            user=user,
            role__in=[OrganizationMembership.Role.OWNER, OrganizationMembership.Role.ADMIN],
        ).values('organization_id')
        events = Event.objects.filter(
            Q(host_user=user, organization__isnull=True) | Q(organization_id__in=managed_orgs)
        )
        if tab == 'upcoming':
            events = events.filter(status=Event.Status.PUBLISHED, end_at__gt=now)
        elif tab == 'drafts':
            events = events.filter(status=Event.Status.DRAFT)
        else:
            events = events.filter(
                Q(status=Event.Status.PUBLISHED, end_at__lte=now)
                | Q(status__in=[Event.Status.COMPLETED, Event.Status.CANCELLED])
            )

    if host == 'me':
        events = events.filter(organization__isnull=True)
    elif host:
        events = events.filter(organization__slug=host)

    ordering = {
        'drafts': ('-updated_at',),
        'past': (F('start_at').desc(nulls_last=True),),
    }.get(tab, ('start_at',))
    return (
        events.select_related('organization', 'venue')
        .annotate(
            going_count=Count('rsvps', filter=Q(rsvps__status='going'), distinct=True),
            waitlist_count=Count('rsvps', filter=Q(rsvps__status='waitlisted'), distinct=True),
            interested_count=Count('rsvps', filter=Q(rsvps__status='interested'), distinct=True),
            rsvp_total=Count('rsvps', filter=~Q(rsvps__status='cancelled'), distinct=True),
            checkin_count=Count('checkins', distinct=True),
        )
        .distinct()
        .order_by(*ordering)
    )


def get_missing_publish_fields(event: Event) -> list[str]:
    """What a draft still needs before it can publish. Mirrors Event.clean()."""
    missing = []
    if not event.title.strip():
        missing.append('title')
    if not event.start_at or not event.end_at:
        missing.append('date and time')
    if not event.venue_id and not event.location_text.strip():
        missing.append('location')
    if not event.is_free:
        if not event.price_text.strip():
            missing.append('price')
        org_contact = event.organization.contact_email if event.organization_id else ''
        if not (event.external_url or event.contact_info or org_contact):
            missing.append('ticket link or contact')
    return missing


def get_my_events_summary(upcoming, past) -> dict:
    """The number strip above the My Events tabs."""
    attended = [e for e in past if e.status != Event.Status.CANCELLED and e.rsvp_required and e.is_free and e.going_count]
    going = sum(e.going_count for e in attended)
    checked_in = sum(min(e.checkin_count, e.going_count) for e in attended)
    return {
        'upcoming_rsvps': sum(e.going_count for e in upcoming),
        'attendance_rate': round(checked_in * 100 / going) if going else None,
    }
