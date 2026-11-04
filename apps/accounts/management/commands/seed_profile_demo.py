from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import CampusDomain, Profile, User
from apps.interests.models import Interest, UserInterest
from apps.organizations.models import Organization, OrganizationFollow
from apps.organizations.services import follow_organization

DEMO_PASSWORD = 'RadarDemo-Only-2026!'
DEMO_DOMAIN = 'demo.example.edu'
INTEREST_NAMES = ['Food', 'Music', 'Outdoors', 'Study', 'Tech', 'Volunteering']
ORGANIZATIONS = [
    ('demo-campus-coders', 'Campus Coders', Organization.OrgType.RSO, False),
    ('demo-career-center', 'Student Career Center', Organization.OrgType.CAMPUS_OFFICE, False),
    ('demo-open-mic-collective', 'Open Mic Collective', Organization.OrgType.RSO, True),
    ('demo-prairie-volunteers', 'Prairie Volunteers', Organization.OrgType.RSO, False),
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

        # seed_mock_data's placeholder interest shouldn't appear in the real interest picker.
        Interest.objects.filter(slug='demo-technology').update(is_active=False)
        self.stdout.write(self.style.SUCCESS(f'Seeded {student.email} with interests and {len(ORGANIZATIONS)} follows.'))

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
