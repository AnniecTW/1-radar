import secrets
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import CampusDomain, Profile, User
from apps.attendance.models import CheckIn
from apps.engagement.models import EventSave
from apps.events.models import Event, EventInterest
from apps.interests.models import Interest, UserInterest
from apps.organizations.models import Organization, OrganizationFollow
from apps.organizations.services import follow_organization
from apps.rsvps.models import RSVP, Ticket

DEMO_PASSWORD = 'RadarDemo-Only-2026!'
DEMO_DOMAIN = 'demo.example.edu'
INTEREST_NAMES = ['Food', 'Music', 'Outdoors', 'Study', 'Tech', 'Volunteering']
ORGANIZATIONS = [
    ('demo-campus-coders', 'Campus Coders', Organization.OrgType.RSO, False),
    ('demo-career-center', 'Student Career Center', Organization.OrgType.CAMPUS_OFFICE, False),
    ('demo-open-mic-collective', 'Open Mic Collective', Organization.OrgType.RSO, True),
    ('demo-prairie-volunteers', 'Prairie Volunteers', Organization.OrgType.RSO, False),
]

# (slug, title, organization slug, days from now, location, interest, what the student did)
EVENTS = [
    ('demo-python-study-jam', 'Python Study Jam', 'demo-campus-coders', 1, 'Grainger Library, Rm 314', 'Study', 'going'),
    ('demo-build-with-llms', 'AI Workshop: Build with LLMs', 'demo-campus-coders', 3, 'Siebel Center, Rm 1404', 'Tech', 'going'),
    ('demo-listening-night', 'Indie Music Listening Night', 'demo-open-mic-collective', 2, 'The Cafe, Urbana', 'Music', 'waitlisted'),
    ('demo-creek-cleanup', 'Boneyard Creek Cleanup', 'demo-prairie-volunteers', 4, 'Boneyard Creek Trail', 'Volunteering', 'saved'),
    ('demo-resume-review', 'Resume Review Night', 'demo-career-center', 6, 'Illini Union, Rm 210', 'Career', 'saved'),
    ('demo-food-truck-social', 'Food Truck Social', 'demo-prairie-volunteers', 8, 'Main Quad', 'Food', 'saved'),
    ('demo-intro-to-git', 'Intro to Git Workshop', 'demo-campus-coders', -40, 'Siebel Center, Rm 1302', 'Tech', 'attended'),
    ('demo-open-mic-fall', 'Fall Open Mic', 'demo-open-mic-collective', -25, 'Illini Union', 'Music', 'attended'),
    ('demo-park-cleanup', 'Park Cleanup Day', 'demo-prairie-volunteers', -12, 'Crystal Lake Park', 'Volunteering', 'attended'),
    ('demo-career-fair', 'Campus Career Fair', 'demo-career-center', -5, 'ARC Gym', 'Career', 'missed'),
]


class Command(BaseCommand):
    help = 'Create a demo student for the Profile and Preferences pages (requires --confirm).'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Confirm writing demo records to this database.')

    def handle(self, *args, **options):
        if not options['confirm']:
            raise CommandError('This writes records to the configured database. Re-run with --confirm.')
        if not CampusDomain.objects.filter(domain=DEMO_DOMAIN).exists():
            raise CommandError(f'Run seed_mock_data --confirm first: {DEMO_DOMAIN} is missing.')

        host = self._save_demo_user('profile-demo-host', 'Demo Host')
        student = self._save_demo_user('alex.chen', 'Alex Chen')
        student.first_name, student.last_name = 'Alex', 'Chen'
        student.save(update_fields=['first_name', 'last_name'])
        Profile.objects.filter(user=student).update(
            bio='CS junior who likes hackathons, open mics, and finding free food on the Quad.',
            major='Computer Science',
            graduation_year=2028,
        )

        interests = Interest.objects.filter(name__in=INTEREST_NAMES)
        UserInterest.objects.filter(user=student).exclude(interest__in=interests).delete()
        for interest in interests:
            UserInterest.objects.get_or_create(
                user=student, interest=interest, defaults={'source': UserInterest.Source.ONBOARDING}
            )

        for slug, name, org_type, muted in ORGANIZATIONS:
            organization, _ = Organization.objects.update_or_create(
                slug=slug,
                defaults={'name': name, 'org_type': org_type, 'created_by': host, 'is_verified': True},
            )
            follow_organization(user=student, organization=organization, source=OrganizationFollow.Source.ONBOARDING)
            OrganizationFollow.objects.filter(user=student, organization=organization).update(notify=not muted)

        self._save_demo_events(student, host)

        # seed_mock_data's placeholder interest shouldn't appear in the real interest picker.
        Interest.objects.filter(slug='demo-technology').update(is_active=False)
        self.stdout.write(self.style.SUCCESS(f'Seeded {student.email} with {len(ORGANIZATIONS)} follows and {len(EVENTS)} events.'))

    def _save_demo_user(self, local_part, display_name):
        email = f'{local_part}@{DEMO_DOMAIN}'
        user = User.objects.filter(email=email).first() or User(email=email, username=local_part)
        user.is_email_verified = True
        user.is_campus_verified = True
        user.onboarding_completed = True
        user.set_password(DEMO_PASSWORD)
        user.save()
        Profile.objects.update_or_create(user=user, defaults={'display_name': display_name})
        return user

    def _save_demo_events(self, student, host):
        now = timezone.now()
        organizations = {organization.slug: organization for organization in Organization.objects.filter(
            slug__in=[row[0] for row in ORGANIZATIONS]
        )}
        for slug, title, organization_slug, days, location, interest_name, action in EVENTS:
            start = now + timedelta(days=days)
            event, _ = Event.objects.update_or_create(
                slug=slug,
                defaults={
                    'title': title,
                    'description': 'Demo event for the Profile dashboard.',
                    'host_user': host,
                    'organization': organizations[organization_slug],
                    'start_at': start,
                    'end_at': start + timedelta(hours=2),
                    'location_text': location,
                    'status': Event.Status.PUBLISHED,
                    'published_at': now,
                    # One spot, taken by the host, is what puts the student on the waitlist.
                    'capacity': 1 if action == 'waitlisted' else None,
                },
            )
            interest = Interest.objects.filter(name=interest_name).first()
            if interest:
                EventInterest.objects.get_or_create(event=event, interest=interest)
            RSVP.objects.update_or_create(event=event, user=host, defaults={'status': RSVP.Status.GOING})
            self._apply_student_action(event, student, action, now)

    def _apply_student_action(self, event, student, action, now):
        if action == 'saved':
            EventSave.objects.get_or_create(event=event, user=student)
        elif action == 'waitlisted':
            RSVP.objects.update_or_create(event=event, user=student, defaults={
                'status': RSVP.Status.WAITLISTED, 'waitlist_position': 1, 'waitlisted_at': now,
            })
        else:
            rsvp, _ = RSVP.objects.update_or_create(event=event, user=student, defaults={'status': RSVP.Status.GOING})
            ticket, _ = Ticket.objects.get_or_create(rsvp=rsvp, defaults={'code': secrets.token_urlsafe(32)})
            if action == 'attended':
                CheckIn.objects.get_or_create(event=event, user=student, defaults={
                    'ticket': ticket, 'method': CheckIn.Method.MANUAL,
                })
