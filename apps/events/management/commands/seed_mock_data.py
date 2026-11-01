import secrets
from datetime import timedelta

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import CampusDomain, Profile, User
from apps.analytics.models import EventDailyStats
from apps.attendance.models import CheckIn
from apps.events.models import Event, EventInterest
from apps.interests.models import Interest
from apps.notifications.models import Notification
from apps.organizations.models import Organization, OrganizationFollow, OrganizationMembership
from apps.rsvps.models import RSVP, Ticket, TrafficSource
from apps.venues.models import Venue


class Command(BaseCommand):
    help = 'Create a small, repeatable Radar demo dataset (requires --confirm).'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Confirm writing demo records to this database.')

    def handle(self, *args, **options):
        if not options['confirm']:
            raise CommandError('This writes records to the configured database. Re-run with --confirm.')

        now = timezone.now()
        CampusDomain.objects.update_or_create(
            domain='demo.example.edu',
            defaults={
                'campus_name': 'Demo University',
                'center_point': Point(-88.2272, 40.1020, srid=4326),
                'timezone': 'America/Chicago',
                'is_active': True,
            },
        )

        users = {}
        demo_users = [
            ('owner@demo.example.edu', 'Demo Org Owner'),
            ('admin@demo.example.edu', 'Demo Org Admin'),
            ('checkin@demo.example.edu', 'Demo Check-in Staff'),
            ('attendee1@demo.example.edu', 'Demo Attendee One'),
            ('attendee2@demo.example.edu', 'Demo Attendee Two'),
        ]
        for email, display_name in demo_users:
            user, _ = User.objects.get_or_create(
                email=email,
                defaults={
                    'username': email.split('@')[0],
                    'password': '!',
                    'is_email_verified': True,
                    'is_campus_verified': True,
                },
            )
            user.is_email_verified = True
            user.is_campus_verified = True
            user.set_password('RadarDemo-Only-2026!')
            user.save()
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.display_name = display_name
            profile.save(update_fields=['display_name', 'updated_at'])
            users[email] = user

        owner = users['owner@demo.example.edu']
        admin_user = users['admin@demo.example.edu']
        staff = users['checkin@demo.example.edu']
        attendee_one = users['attendee1@demo.example.edu']
        attendee_two = users['attendee2@demo.example.edu']

        organization, _ = Organization.objects.update_or_create(
            slug='demo-robotics-club',
            defaults={
                'name': 'Demo Robotics Club',
                'org_type': Organization.OrgType.RSO,
                'description': 'Seed data for local development and permission checks.',
                'contact_email': 'robotics@demo.example.edu',
                'created_by': owner,
            },
        )
        OrganizationMembership.objects.update_or_create(
            organization=organization, user=owner,
            defaults={'role': OrganizationMembership.Role.OWNER, 'invited_by': owner},
        )
        OrganizationMembership.objects.update_or_create(
            organization=organization, user=admin_user,
            defaults={'role': OrganizationMembership.Role.ADMIN, 'invited_by': owner},
        )
        OrganizationMembership.objects.update_or_create(
            organization=organization, user=staff,
            defaults={'role': OrganizationMembership.Role.CHECKIN_STAFF, 'invited_by': owner},
        )

        venue, _ = Venue.objects.get_or_create(
            name='Demo Engineering Hall',
            defaults={
                'building_code': 'DEMO', 'aliases': ['Demo Engineering'],
                'address': '100 Demo Way',
                'location': Point(-88.2272, 40.1020, srid=4326), 'is_campus': True,
            },
        )
        interest, _ = Interest.objects.get_or_create(
            slug='demo-technology', defaults={'name': 'Demo Technology', 'group': 'Academic', 'is_active': True}
        )

        events = {}
        event_specs = [
            ('demo-capacity-event', 'Demo Capacity Event', 1, True, True, Event.Visibility.PUBLIC),
            ('demo-drop-in-event', 'Demo Drop-in Event', None, False, True, Event.Visibility.CAMPUS_ONLY),
            ('demo-unlisted-event', 'Demo Unlisted Event', None, True, True, Event.Visibility.UNLISTED),
        ]
        for slug, title, capacity, rsvp_required, waitlist_enabled, visibility in event_specs:
            event, _ = Event.objects.update_or_create(
                slug=slug,
                defaults={
                    'title': title, 'description': 'Repeatable demo event.',
                    'host_user': owner, 'organization': organization,
                    'start_at': now + timedelta(days=7), 'end_at': now + timedelta(days=7, hours=2),
                    'venue': venue, 'location_text': 'Room 101', 'location': venue.location,
                    'status': Event.Status.PUBLISHED, 'visibility': visibility,
                    'capacity': capacity, 'rsvp_required': rsvp_required,
                    'waitlist_enabled': waitlist_enabled,
                },
            )
            EventInterest.objects.get_or_create(event=event, interest=interest)
            events[slug] = event

        capacity_event = events['demo-capacity-event']
        going, _ = RSVP.objects.update_or_create(
            event=capacity_event, user=attendee_one,
            defaults={'status': RSVP.Status.GOING, 'source': TrafficSource.DIRECT},
        )
        waitlisted, _ = RSVP.objects.update_or_create(
            event=capacity_event, user=attendee_two,
            defaults={
                'status': RSVP.Status.WAITLISTED, 'waitlist_position': 1,
                'waitlisted_at': now, 'source': TrafficSource.DIRECT,
            },
        )
        ticket, _ = Ticket.objects.get_or_create(
            rsvp=going, defaults={'code': secrets.token_urlsafe(32), 'status': Ticket.Status.VALID}
        )
        CheckIn.objects.get_or_create(
            event=capacity_event, user=attendee_one,
            defaults={'ticket': ticket, 'method': CheckIn.Method.HOST_SCAN, 'checked_in_by': staff},
        )
        Ticket.objects.filter(pk=ticket.pk).update(status=Ticket.Status.USED, used_at=now)
        RSVP.objects.update_or_create(
            event=events['demo-drop-in-event'], user=attendee_two,
            defaults={'status': RSVP.Status.INTERESTED, 'source': TrafficSource.LANDING},
        )
        OrganizationFollow.objects.get_or_create(
            user=attendee_one, organization=organization,
            defaults={'source': OrganizationFollow.Source.ORG_PAGE, 'notify': True},
        )
        EventDailyStats.objects.update_or_create(
            event=capacity_event, date=now.date(),
            defaults={'views': 24, 'unique_views': 18, 'likes': 4, 'saves': 3,
                      'rsvps_going': 1, 'rsvps_waitlisted': 1, 'checkins': 1},
        )
        Notification.objects.get_or_create(
            user=attendee_two, event=capacity_event,
            type=Notification.Type.WAITLIST_JOINED,
            defaults={'payload': {'position': waitlisted.waitlist_position}},
        )
        self.stdout.write(self.style.SUCCESS('Seeded 5 users, 1 organization, 3 events, and sample engagement.'))
