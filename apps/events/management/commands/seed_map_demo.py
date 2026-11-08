"""Seed ~30 events around Champaign-Urbana so Explore Map has real-looking pins, heat and results.

Every record this creates is tagged so it can be removed again:
  python manage.py seed_map_demo --confirm          # create or refresh (safe to re-run)
  python manage.py seed_map_demo --remove --confirm # delete the seeded events, org and attendees
"""
import random
from datetime import datetime, time, timedelta

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import Profile, User
from apps.discovery.constants import UNSPLASH_PHOTO_URL
from apps.discovery.selectors import get_campus_timezone, get_weekend_window
from apps.events.models import Event, EventInterest
from apps.interests.models import Interest
from apps.organizations.models import Organization
from apps.rsvps.models import RSVP, TrafficSource
from apps.venues.models import Venue

SLUG_PREFIX = 'map-demo-'
ORGANIZATION_SLUG = 'map-demo-campus-life'
HOST_EMAIL = 'map-demo-host@demo.example.edu'
ATTENDEE_EMAIL = 'map-demo-attendee-{number}@demo.example.edu'
ATTENDEE_COUNT = 12

# Real places in Champaign-Urbana: (name, latitude, longitude, on campus).
VENUES = {
    'union': ('Illini Union', 40.1092, -88.2272, True),
    'grainger': ('Grainger Engineering Library', 40.1125, -88.2269, True),
    'siebel': ('Siebel Center for Computer Science', 40.1138, -88.2249, True),
    'design': ('Siebel Center for Design', 40.1003, -88.2238, True),
    'krannert': ('Krannert Center for the Performing Arts', 40.1080, -88.2223, True),
    'kam': ('Krannert Art Museum', 40.1025, -88.2259, True),
    'arc': ('Activities and Recreation Center (ARC)', 40.1013, -88.2360, True),
    'crce': ('Campus Recreation Center East', 40.1046, -88.2210, True),
    'quad': ('Main Quad', 40.1074, -88.2272, True),
    'foellinger': ('Foellinger Auditorium', 40.1059, -88.2272, True),
    'ugl': ('Undergraduate Library', 40.1046, -88.2272, True),
    'spurlock': ('Spurlock Museum', 40.1062, -88.2193, True),
    'japan_house': ('Japan House', 40.0937, -88.2178, True),
    'state_farm': ('State Farm Center', 40.0962, -88.2359, True),
    'research_park': ('Research Park', 40.0938, -88.2425, False),
    'downtown': ('Downtown Champaign (Neil St)', 40.1164, -88.2434, False),
    'champaign_library': ('Champaign Public Library', 40.1183, -88.2510, False),
    'lincoln_square': ('Lincoln Square, Urbana', 40.1112, -88.2077, False),
    'crystal_lake': ('Crystal Lake Park', 40.1209, -88.2045, False),
    'scott_park': ('Scott Park', 40.1150, -88.2400, False),
}

# Free Unsplash photos (https://unsplash.com/license) used as covers for some events.
COVERS = {
    'tech': '1531482615713-2afd69097998', 'study': '1523240795612-9a054b0db644',
    'sports': '1517466787929-bc90951d0974', 'music': '1501386761578-eac5c94b800a',
    'gathering': '1517457373958-b7bdd4587205', 'volunteer': '1559027615-cd4628902d4a',
    'friends': '1529156069898-49953e39b3ac', 'arts': '1757085242652-f8cd4d3de889',
    'food': '1686574086026-9f02b82f4765', 'campus': '1638616122105-804db5fbef63',
}

# (title, venue, categories, when, start hour, hours, kind, capacity, popularity, cover, description)
# when: 'now' (already running), 'today', 'sat', 'sun', or '+N' days from today.
# kind: 'rsvp' (RSVP), 'dropin' (Interested), 'paid' (Contact host).
EVENTS = [
    ('Late-Night Study Jam', 'ugl', ['study'], 'now', 0, 3, 'dropin', None, 34, 'study',
     'Quiet indoor study tables with snacks. Drop in for an hour or stay all night.'),
    ('Coffee & Code Hour', 'siebel', ['tech', 'networking'], 'now', 0, 2, 'dropin', None, 22, None,
     'Bring a laptop and a side project. Indoor, relaxed, mentors around for questions.'),
    ('Intro to Arduino Workshop', 'grainger', ['tech', 'science'], 'today', 18, 2, 'rsvp', 30, 41, 'tech',
     'Build a blinking circuit and leave with your own board. No experience needed.'),
    ('Free Pizza Career Chat', 'union', ['career', 'food'], 'today', 17, 1.5, 'rsvp', 60, 47, 'food',
     'Meet alumni from local startups over free pizza. Resume questions welcome.'),
    ('Sunset Run Club', 'scott_park', ['fitness', 'outdoors'], 'today', 17, 1, 'dropin', None, 18, 'sports',
     'A friendly 5K at conversation pace. All speeds welcome.'),
    ('Board Game Night', 'union', ['gaming'], 'sat', 18, 3, 'dropin', None, 52, 'friends',
     'Hundreds of games, low-key crowd. A quiet table is reserved for anyone who prefers calm play.'),
    ('Book Club at the Union', 'union', ['writing', 'study'], 'sat', 14, 2, 'rsvp', 20, 36, None,
     'This month: a short novel and good tea. Quiet, small-group discussion indoors.'),
    ('Pottery Workshop', 'kam', ['arts'], 'sat', 13, 2, 'paid', 16, 28, 'arts',
     'Hand-build a mug with a local ceramicist. $15 materials fee; contact the host to book.'),
    ('Volleyball Meetup', 'arc', ['sports', 'fitness'], 'sat', 18, 2, 'dropin', None, 62, 'sports',
     'Casual indoor volleyball. Teams are mixed every game, so come solo.'),
    ('Indie Music Listening Night', 'downtown', ['music'], 'sun', 19, 2, 'dropin', None, 41, 'music',
     'Vinyl, headphones and a cozy back room. A quiet night of new indie records.'),
    ('Farmers Market Morning', 'lincoln_square', ['food', 'outdoors'], 'sat', 9, 3, 'dropin', None, 58, 'gathering',
     'Local produce, pastries and live acoustic music.'),
    ('Japan House Tea Ceremony', 'japan_house', ['cultural', 'wellness'], 'sun', 13, 1.5, 'rsvp', 24, 33, None,
     'A calm, quiet introduction to the Japanese tea ceremony indoors.'),
    ('Spurlock Museum Late', 'spurlock', ['cultural', 'arts'], 'sat', 18, 2, 'dropin', None, 21, 'campus',
     'Galleries open after hours with short talks from curators.'),
    ('Crystal Lake Paddle', 'crystal_lake', ['outdoors', 'fitness'], 'sun', 10, 2, 'rsvp', 18, 30, None,
     'Paddle boats and a picnic by the lake. Life jackets provided.'),
    ('Campus Cleanup Crew', 'quad', ['volunteering', 'outdoors'], 'sat', 10, 2, 'rsvp', 40, 44, 'volunteer',
     'Gloves and bags provided. Finish with coffee on the Quad.'),
    ('Open Mic at Krannert', 'krannert', ['music', 'arts'], 'sun', 20, 2, 'dropin', None, 55, 'music',
     'Poetry, songs and comedy. Sign up at the door for a five-minute slot.'),
    ('Hack Night: AI Projects', 'siebel', ['tech', 'entrepreneurship'], 'sat', 17, 4, 'rsvp', 80, 68, 'tech',
     'Team up on small AI projects. Dinner provided; demos at 9 PM.'),
    ('Startup Pitch Practice', 'research_park', ['entrepreneurship', 'career'], 'sun', 15, 2, 'rsvp', 50, 26, None,
     'Pitch your idea in three minutes and get feedback from founders.'),
    ('Mindful Mornings', 'crce', ['wellness'], 'sun', 9, 1, 'dropin', None, 15, None,
     'A quiet guided meditation and gentle stretching indoors.'),
    ('Illini Basketball Watch Party', 'state_farm', ['sports'], 'sat', 19, 3, 'paid', None, 73, 'gathering',
     'Big screens, student section energy. Tickets through the host.'),
    ('Film Club: Classic Noir', 'foellinger', ['film'], 'sun', 19, 2.5, 'dropin', None, 24, None,
     'Black-and-white classic with a short discussion afterward.'),
    ('Climate Action Teach-in', 'quad', ['activism', 'science'], '+3', 12, 2, 'dropin', None, 19, None,
     'Short talks from student groups and local organizers.'),
    ('Interfaith Dinner', 'union', ['faith', 'food'], '+4', 18, 2, 'rsvp', 50, 23, 'food',
     'Share a meal and stories with students from many traditions.'),
    ('Design Critique Night', 'design', ['arts', 'career'], '+2', 18, 2, 'rsvp', 25, 17, None,
     'Bring a portfolio piece for kind, specific feedback.'),
    ('Writing Sprint', 'champaign_library', ['writing'], '+5', 14, 2, 'dropin', None, 12, None,
     'Quiet, focused writing in 25-minute rounds. Indoor study room.'),
    ('Networking Mixer: Tech & Data', 'research_park', ['networking', 'tech'], '+6', 17, 2, 'rsvp', 120, 39, 'tech',
     'Meet engineers and data folks from Research Park companies.'),
    ('Salsa for Beginners', 'crce', ['fitness', 'cultural'], '+3', 19, 1.5, 'dropin', None, 31, 'friends',
     'No partner needed. Comfortable shoes recommended.'),
    ('Science Café', 'downtown', ['science'], '+4', 19, 1.5, 'dropin', None, 20, None,
     'A researcher explains their work over coffee. Questions encouraged.'),
    ('Food Truck Rally', 'quad', ['food'], '+5', 11, 3, 'dropin', None, 49, 'food',
     'Ten trucks, one Quad. Bring friends.'),
    ('Esports Tournament', 'union', ['gaming', 'tech'], '+6', 16, 5, 'rsvp', 64, 46, None,
     'Bracket-style tournament with prizes for the top teams.'),
]


class Command(BaseCommand):
    help = 'Seed ~30 Champaign-Urbana events for Explore Map (requires --confirm). Use --remove to delete them.'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Confirm writing to the configured database.')
        parser.add_argument('--remove', action='store_true', help='Delete everything this command created.')

    def handle(self, *args, **options):
        if not options['confirm']:
            raise CommandError('This writes to the configured database. Re-run with --confirm.')
        with transaction.atomic():
            if options['remove']:
                self.remove()
            else:
                self.seed()

    def remove(self):
        events = Event.objects.filter(slug__startswith=SLUG_PREFIX)
        RSVP.objects.filter(event__in=events).delete()
        removed_events = events.delete()[0]
        Organization.objects.filter(slug=ORGANIZATION_SLUG).delete()
        removed_users = User.objects.filter(email__startswith='map-demo-', email__endswith='@demo.example.edu').delete()[0]
        self.stdout.write(self.style.SUCCESS(f'Removed {removed_events} event records and {removed_users} user records.'))

    def seed(self):
        now = timezone.now()
        campus_timezone = get_campus_timezone()
        today = now.astimezone(campus_timezone).date()
        saturday = get_weekend_window(now, campus_timezone)[0].date()
        rng = random.Random(490)  # same counts every run

        host = self.get_user(HOST_EMAIL, 'Campus Life (demo)')
        attendees = [self.get_user(ATTENDEE_EMAIL.format(number=n), f'Demo Attendee {n}') for n in range(1, ATTENDEE_COUNT + 1)]
        organization, _ = Organization.objects.update_or_create(
            slug=ORGANIZATION_SLUG,
            defaults={
                'name': 'Campus Life (demo)', 'org_type': Organization.OrgType.RSO,
                'description': 'Demo events for Explore Map.', 'contact_email': HOST_EMAIL, 'created_by': host,
            },
        )
        venues = {
            key: Venue.objects.get_or_create(
                name=name, defaults={'location': Point(lng, lat, srid=4326), 'is_campus': on_campus},
            )[0]
            for key, (name, lat, lng, on_campus) in VENUES.items()
        }
        interests = {interest.slug: interest for interest in Interest.objects.filter(is_active=True)}

        for spec in EVENTS:
            event = self.save_event(spec, now, today, saturday, campus_timezone, host, organization, venues)
            for slug in spec[2]:
                if slug in interests:
                    EventInterest.objects.get_or_create(event=event, interest=interests[slug])
            self.save_rsvps(event, spec, attendees, rng)
        self.stdout.write(self.style.SUCCESS(f'Seeded {len(EVENTS)} events around Champaign-Urbana.'))

    def get_user(self, email: str, display_name: str) -> User:
        user, created = User.objects.get_or_create(
            email=email, defaults={'username': email.split('@')[0], 'is_email_verified': True},
        )
        if created:
            user.set_unusable_password()  # demo accounts nobody can sign in to
            user.save(update_fields=['password'])
        Profile.objects.update_or_create(user=user, defaults={'display_name': display_name})
        return user

    def start_time(self, when: str, hour: float, now, today, saturday, campus_timezone) -> datetime:
        if when == 'now':
            return now - timedelta(minutes=45)
        day = {'today': today, 'sat': saturday, 'sun': saturday + timedelta(days=1)}.get(when)
        if day is None:
            day = today + timedelta(days=int(when.lstrip('+')))
        hours, minutes = int(hour), int((hour % 1) * 60)
        return datetime.combine(day, time(hours, minutes), tzinfo=campus_timezone)

    def save_event(self, spec, now, today, saturday, campus_timezone, host, organization, venues) -> Event:
        title, venue_key, _, when, hour, hours, kind, capacity, popularity, cover, description = spec
        venue = venues[venue_key]
        start_at = self.start_time(when, hour, now, today, saturday, campus_timezone)
        if when == 'today' and start_at < now:  # keep "today" events upcoming whenever the seed runs
            start_at = now + timedelta(hours=1)
        slug = SLUG_PREFIX + slugify(title)
        event, _ = Event.objects.update_or_create(
            slug=slug,
            defaults={
                'title': title, 'description': description, 'host_user': host, 'organization': organization,
                'start_at': start_at, 'end_at': start_at + timedelta(hours=hours),
                'venue': venue, 'location_text': '', 'location': venue.location,
                'cover_image': UNSPLASH_PHOTO_URL.format(photo_id=COVERS[cover]).replace('w=1600', 'w=800') if cover else '',
                'status': Event.Status.PUBLISHED, 'visibility': Event.Visibility.PUBLIC, 'published_at': now,
                'capacity': capacity, 'rsvp_required': kind == 'rsvp', 'waitlist_enabled': capacity is not None,
                'is_free': kind != 'paid', 'price_text': '$15' if kind == 'paid' else '',
                'contact_info': HOST_EMAIL if kind == 'paid' else None, 'external_url': None,
                'popularity_score': popularity,
            },
        )
        return event

    def save_rsvps(self, event: Event, spec, attendees, rng: random.Random) -> None:
        kind, capacity = spec[6], spec[7]
        if kind == 'paid':
            return
        limit = min(len(attendees), capacity or len(attendees))
        chosen = rng.sample(attendees, rng.randint(2, limit))
        status = RSVP.Status.GOING if kind == 'rsvp' else RSVP.Status.INTERESTED
        for attendee in chosen:
            RSVP.objects.update_or_create(
                event=event, user=attendee, defaults={'status': status, 'source': TrafficSource.DIRECT},
            )
