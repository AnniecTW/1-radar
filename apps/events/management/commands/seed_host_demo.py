"""Demo data for My Dashboard and event analytics, hosted by the alex.chen demo student.

Run seed_mock_data and seed_profile_demo first. Re-running replaces the earlier demo host data;
--remove deletes it all (events, demo attendees and the demo organization).
"""
import random
import secrets
from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import Profile, User
from apps.attendance.models import CheckIn
from apps.engagement.models import EventLike, EventOutboundClick, EventSave, EventView
from apps.events.models import Event, EventCheckInStaff
from apps.organizations.models import Organization, OrganizationMembership
from apps.rsvps.models import RSVP, Ticket

DEMO_DOMAIN = 'demo.example.edu'
HOST_EMAIL = f'alex.chen@{DEMO_DOMAIN}'
ORG_SLUG = 'demo-illini-robotics'
STAFF_ORG_SLUG = 'demo-campus-coders'
SLUG_PREFIX = 'demo-host-'
ATTENDEE_PREFIX = 'demo.attendee'
ATTENDEE_COUNT = 70
MAJORS = ['Computer Science'] * 7 + ['Electrical Engineering'] * 4 + ['Mechanical Engineering'] * 3 + [
    'Physics', 'Mathematics', 'Industrial Design', 'Economics', 'Information Sciences']
SOURCES = ['feed', 'map', 'recommendation', 'search', 'direct', 'following', 'org_page']
SOURCE_WEIGHTS = [34, 22, 16, 11, 8, 6, 3]

# key, title, days from now, hours long, place, organization?, kind, plan
EVENTS = [
    ('robotics-night', 'Robotics Night', 9, 3, 'Siebel Center, Rm 1404', True, 'rsvp',
     {'capacity': 60, 'going': 46, 'waitlisted': 0, 'views': 380, 'likes': 41, 'saves': 33}),
    ('intro-to-arduino', 'Intro to Arduino Workshop', 4, 2, 'Grainger Library, Rm 330', True, 'rsvp',
     {'capacity': 20, 'going': 20, 'waitlisted': 6, 'views': 260, 'likes': 30, 'saves': 27}),
    ('pickup-volleyball', 'Pickup Volleyball', 12, 2, 'ARC Court 3', False, 'drop_in',
     {'interested': 18, 'views': 140, 'likes': 15, 'saves': 9}),
    ('halloween-hack-night', 'Halloween Hack Night', -7, 4, 'Siebel Center, Rm 2405', True, 'rsvp',
     {'capacity': 70, 'going': 58, 'waitlisted': 0, 'checked_in': 44, 'views': 520, 'likes': 66, 'saves': 48}),
    ('fall-kickoff-social', 'Fall Kickoff Social', -24, 2, 'Main Quad', True, 'rsvp',
     {'capacity': None, 'going': 40, 'waitlisted': 0, 'checked_in': 27, 'views': 310, 'likes': 35, 'saves': 22}),
    ('engineering-gala', 'Engineering Gala', -14, 3, 'Illini Union Ballroom', True, 'paid',
     {'views': 640, 'likes': 70, 'saves': 51, 'ticket_clicks': 132, 'contact_clicks': 9}),
    ('soldering-101', 'Soldering 101', 2, 2, 'ECEB, Rm 2017', True, 'cancelled',
     {'capacity': 25, 'going': 14, 'waitlisted': 0}),
]


class Command(BaseCommand):
    help = 'Create hosted demo events with RSVPs, check-ins and views for My Dashboard (requires --confirm).'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Confirm writing demo records to this database.')
        parser.add_argument('--remove', action='store_true', help='Delete the demo host data instead of creating it.')

    def handle(self, *args, **options):
        if not options['confirm']:
            raise CommandError('This writes records to the configured database. Re-run with --confirm.')
        host = User.objects.filter(email=HOST_EMAIL).first()
        if host is None:
            raise CommandError('Run seed_profile_demo --confirm first: the alex.chen demo student is missing.')
        with transaction.atomic():
            self._remove(host)
            if options['remove']:
                Organization.objects.filter(slug=ORG_SLUG).delete()
                User.objects.filter(email__startswith=ATTENDEE_PREFIX, email__endswith=f'@{DEMO_DOMAIN}').delete()
                self.stdout.write(self.style.SUCCESS('Removed the demo host data.'))
                return
            self._seed(host)
        self.stdout.write(self.style.SUCCESS(
            f'Seeded My Dashboard for {HOST_EMAIL}: {len(EVENTS)} events, 2 drafts, 1 check-in staff assignment.'
        ))

    def _remove(self, host):
        Event.objects.filter(
            Q(slug__startswith=SLUG_PREFIX) | Q(organization__slug=ORG_SLUG) | Q(host_user=host, organization__isnull=True)
        ).delete()

    def _seed(self, host):
        rng = random.Random(490)
        now = timezone.now()
        org, _ = Organization.objects.update_or_create(slug=ORG_SLUG, defaults={
            'name': 'Illini Robotics Club', 'org_type': Organization.OrgType.RSO, 'created_by': host, 'is_verified': True,
            'contact_email': f'robotics@{DEMO_DOMAIN}',
        })
        OrganizationMembership.objects.update_or_create(
            organization=org, user=host, defaults={'role': OrganizationMembership.Role.OWNER}
        )
        attendees = self._attendees(rng)

        for key, title, days, hours, place, use_org, kind, plan in EVENTS:
            start = (now + timedelta(days=days)).replace(hour=18, minute=0, second=0, microsecond=0)
            published = start - timedelta(days=16)
            event = Event.objects.create(
                slug=SLUG_PREFIX + key, title=title, host_user=host, organization=org if use_org else None,
                description=f'{title}: demo event for the My Dashboard and analytics pages.',
                start_at=start, end_at=start + timedelta(hours=hours), location_text=place,
                status=Event.Status.PUBLISHED, published_at=min(published, now),
                capacity=plan.get('capacity'), rsvp_required=kind != 'drop_in', is_free=kind != 'paid',
                price_text='$25' if kind == 'paid' else '', external_url='https://example.com/tickets' if kind == 'paid' else None,
            )
            crowd = rng.sample(attendees, len(attendees))
            window = (event.published_at, min(start, now))
            self._rsvps(event, crowd, plan, window, rng)
            self._engagement(event, crowd, plan, window, rng)
            if plan.get('checked_in'):
                self._checkins(event, plan['checked_in'], rng)
            if kind == 'cancelled':
                Event.objects.filter(pk=event.pk).update(
                    status=Event.Status.CANCELLED, cancel_reason='The room is no longer available.', cancelled_at=now)
                # Like cancel_event: RSVPs stay, tickets stop working.
                Ticket.objects.filter(rsvp__event=event).update(status=Ticket.Status.VOID)

        Event.objects.create(title='Winter Build Showcase', host_user=host, organization=org,
                             description='Show off what members built this semester.',
                             start_at=now + timedelta(days=28), end_at=now + timedelta(days=28, hours=2))
        draft_start = (now + timedelta(days=20)).replace(hour=19, minute=0, second=0, microsecond=0)
        Event.objects.create(title='Robot Battle Night', host_user=host, organization=org, location_text='Siebel Center, Rm 1404',
                             start_at=draft_start, end_at=draft_start + timedelta(hours=2))

        self._staff_assignment(host, now)

    def _attendees(self, rng):
        users = []
        for number in range(1, ATTENDEE_COUNT + 1):
            email = f'{ATTENDEE_PREFIX}{number:02d}@{DEMO_DOMAIN}'
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User(email=email, username=f'{ATTENDEE_PREFIX}{number:02d}',
                            is_email_verified=True, is_campus_verified=True, onboarding_completed=True)
                user.set_unusable_password()
                user.save()
            Profile.objects.update_or_create(user=user, defaults={
                'display_name': f'Demo Attendee {number}',
                'major': MAJORS[number % len(MAJORS)],
                'graduation_year': 2026 + number % 4,
            })
            users.append(user)
        return users

    @staticmethod
    def _spread(window, rng, front_loaded=True):
        """A time inside the window, busier right after publishing and right before the event."""
        start, end = window
        span = max((end - start).total_seconds(), 3600)
        position = rng.betavariate(0.8, 0.9) if front_loaded else rng.random()
        return start + timedelta(seconds=position * span)

    def _set_times(self, model, times, field):
        by_time = defaultdict(list)
        for pk, moment in times:
            by_time[moment.replace(minute=0, second=0, microsecond=0)].append(pk)
        for moment, pks in by_time.items():
            model.objects.filter(pk__in=pks).update(**{field: moment})

    def _rsvps(self, event, crowd, plan, window, rng):
        times = []
        going = crowd[:plan.get('going', 0)]
        for user in going:
            rsvp = RSVP.objects.create(event=event, user=user, status=RSVP.Status.GOING)
            Ticket.objects.create(rsvp=rsvp, code=secrets.token_urlsafe(32))
            times.append((rsvp.pk, self._spread(window, rng)))
        waitlisted = crowd[len(going):len(going) + plan.get('waitlisted', 0)]
        for position, user in enumerate(waitlisted, start=1):
            moment = window[1] - timedelta(hours=rng.randint(6, 60))
            rsvp = RSVP.objects.create(event=event, user=user, status=RSVP.Status.WAITLISTED,
                                       waitlist_position=position, waitlisted_at=moment)
            times.append((rsvp.pk, moment))
        for user in crowd[:plan.get('interested', 0)]:
            rsvp = RSVP.objects.create(event=event, user=user, status=RSVP.Status.INTERESTED)
            times.append((rsvp.pk, self._spread(window, rng)))
        self._set_times(RSVP, times, 'created_at')

    def _engagement(self, event, crowd, plan, window, rng):
        views = EventView.objects.bulk_create([
            EventView(event=event, user=rng.choice(crowd) if rng.random() < 0.7 else None,
                      session_key='' if rng.random() < 0.7 else secrets.token_hex(16),
                      source=rng.choices(SOURCES, SOURCE_WEIGHTS)[0])
            for _ in range(plan.get('views', 0))
        ])
        self._set_times(EventView, [(v.pk, self._spread(window, rng)) for v in views], 'created_at')
        for model, count in ((EventLike, plan.get('likes', 0)), (EventSave, plan.get('saves', 0))):
            model.objects.bulk_create([model(event=event, user=user) for user in rng.sample(crowd, count)])
        clicks = [EventOutboundClick(event=event, kind=EventOutboundClick.Kind.TICKETS_LINK, user=rng.choice(crowd))
                  for _ in range(plan.get('ticket_clicks', 0))]
        clicks += [EventOutboundClick(event=event, kind=EventOutboundClick.Kind.CONTACT, user=rng.choice(crowd))
                   for _ in range(plan.get('contact_clicks', 0))]
        clicks = EventOutboundClick.objects.bulk_create(clicks)
        self._set_times(EventOutboundClick, [(c.pk, self._spread(window, rng)) for c in clicks], 'created_at')

    def _checkins(self, event, count, rng):
        going = list(RSVP.objects.filter(event=event, status=RSVP.Status.GOING).select_related('ticket')[:count])
        times = []
        for rsvp in going:
            checkin = CheckIn.objects.create(event=event, user=rsvp.user, ticket=rsvp.ticket, method=CheckIn.Method.HOST_SCAN)
            Ticket.objects.filter(pk=rsvp.ticket.pk).update(status=Ticket.Status.USED)
            minutes = min(abs(rng.gauss(30, 28)), (event.end_at - event.start_at).total_seconds() / 60 - 5)
            times.append((checkin.pk, event.start_at - timedelta(minutes=10) + timedelta(minutes=minutes)))
        for pk, moment in times:
            CheckIn.objects.filter(pk=pk).update(checked_in_at=moment)

    def _staff_assignment(self, host, now):
        org = Organization.objects.filter(slug=STAFF_ORG_SLUG).first()
        if org is None:
            return
        OrganizationMembership.objects.get_or_create(
            organization=org, user=host, defaults={'role': OrganizationMembership.Role.CHECKIN_STAFF})
        start = (now + timedelta(days=6)).replace(hour=17, minute=0, second=0, microsecond=0)
        event = Event.objects.create(
            slug=SLUG_PREFIX + 'hackathon-kickoff', title='Hackathon Kickoff', host_user=org.created_by,
            organization=org, start_at=start, end_at=start + timedelta(hours=3), location_text='Siebel Center Atrium',
            status=Event.Status.PUBLISHED, published_at=now - timedelta(days=5), capacity=150,
        )
        EventCheckInStaff.objects.create(event=event, user=host, assigned_by=org.created_by)
