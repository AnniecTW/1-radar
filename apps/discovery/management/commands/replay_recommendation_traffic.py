"""Mock "Recommended for you" traffic for the recommendations dashboard, run through the real recommender.

Creates made-up students (usernames starting rec-sim-, inactive, no usable password) who pick a few categories.
Each one "visits" the home page a few times over the last --days days: the real recommender ranks the current
upcoming events for them, the impressions are logged as the home page logs them (flagged is_simulated), and
some cards get a simulated click or "Not interested".

The students only pick categories. They never RSVP, save, like or view anything, so hosts' analytics and event
counts are untouched. Each has a hidden taste (mostly the categories they picked, sometimes one more or one
fewer): cards matching it, near the top of the row, or starting soon get clicked more; cards that don't match
are sometimes dismissed. The dashboard's charts on simulated data therefore show these assumptions, not real
behaviour. --clear deletes the made-up students, and with them everything they logged.
"""
import random
import secrets
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

SIM_PREFIX = 'rec-sim-'
CLICK_BASE = 0.30  # Chance the top card is clicked when it matches the student's taste and starts soon.
POSITION_DECAY = 0.82  # Each place further down keeps this share of the chance.
OFF_TASTE = 0.25  # Cards that don't match the taste are clicked this much less often...
DISMISS_CHANCE = 0.15  # ...and dismissed this often.
MAX_CLICKS_PER_VISIT = 2


def make_taste(chosen: list[str], others: list[str], rng) -> set[str]:
    """What a student really likes: what they picked, sometimes plus one more, sometimes minus one."""
    taste = set(chosen)
    if others and rng.random() < 0.5:
        taste.add(rng.choice(others))
    if len(chosen) > 1 and rng.random() < 0.3:
        taste.discard(rng.choice(chosen))
    return taste


def react(rank: int, matches: bool, urgency: float, rng) -> tuple[bool, bool]:
    """(clicked, dismissed) for one card."""
    chance = CLICK_BASE * POSITION_DECAY ** (rank - 1) * (1.0 if matches else OFF_TASTE) * (0.6 + 0.8 * urgency)
    if rng.random() < chance:
        return True, False
    return False, not matches and rng.random() < DISMISS_CHANCE


def urgency_of(event, now) -> float:
    value = getattr(event, 'rec_urgency', None)
    if value is not None:
        return float(value)
    days = (event.start_at - now).total_seconds() / 86400
    return max(0.0, min(1.0, 1 - days / 14))


class Command(BaseCommand):
    help = ('Log simulated "Recommended for you" impressions, clicks and dismissals for made-up students. '
            'Writes to the database: needs --confirm.')

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Confirm writing to this database.')
        parser.add_argument('--users', type=int, default=12, help='How many made-up students (default 12).')
        parser.add_argument('--visits', type=int, default=4, help='Home page visits per student, on average (default 4).')
        parser.add_argument('--days', type=int, default=14, help='Spread visits over the last this many days (default 14).')
        parser.add_argument('--location-share', type=float, default=0.3,
                            help='Share of students who share a location near campus (default 0.3).')
        parser.add_argument('--seed', type=int, help='Random seed, to repeat the same mix.')
        parser.add_argument('--clear', action='store_true', help='Delete every made-up student (and their rows) first.')

    def handle(self, *args, **options):
        from apps.accounts.models import User
        from apps.discovery.recommendations import log_impressions, recommend_events, round_location
        from apps.discovery.selectors import get_campus_center, get_campus_timezone
        from apps.interests.models import Interest, UserInterest
        from apps.search.management.commands.replay_search_traffic import spread_time

        if not options['confirm']:
            raise CommandError('This writes made-up students and impressions to the configured database. '
                               'Re-run with --confirm.')
        if min(options['users'], options['visits'], options['days']) < 1:
            raise CommandError('--users, --visits and --days must be at least 1.')
        if not 0 <= options['location_share'] <= 1:
            raise CommandError('--location-share must be between 0 and 1.')

        if options['clear']:
            deleted = User.objects.filter(username__startswith=SIM_PREFIX).delete()[1].get('accounts.User', 0)
            self.stdout.write(f'Deleted {deleted} made-up students and everything they logged.')

        slugs = list(Interest.objects.filter(is_active=True, embedding__isnull=False).values_list('slug', flat=True))
        if not slugs:
            raise CommandError('No category has an embedding yet; run `python manage.py embed_interests` first.')
        interests = {interest.slug: interest for interest in Interest.objects.filter(slug__in=slugs)}
        rng = random.Random(options['seed'])
        center = get_campus_center() or (40.102, -88.2272)
        now, tz = timezone.now(), get_campus_timezone()

        students = []
        for _ in range(options['users']):
            tag = secrets.token_hex(4)
            user = User(username=f'{SIM_PREFIX}{tag}', email=f'{SIM_PREFIX}{tag}@example.edu',
                        first_name='Simulated', is_active=False)
            user.set_unusable_password()
            user.save()
            chosen = rng.sample(slugs, k=min(len(slugs), rng.randint(1, 3)))
            UserInterest.objects.bulk_create([UserInterest(user=user, interest=interests[slug],
                                                           source=UserInterest.Source.ONBOARDING) for slug in chosen])
            location = None
            if rng.random() < options['location_share']:
                location = round_location(center[0] + rng.uniform(-0.01, 0.01), center[1] + rng.uniform(-0.01, 0.01))
            students.append((user, make_taste(chosen, [slug for slug in slugs if slug not in chosen], rng), location))

        visits = sorted(
            (spread_time(now, options['days'], tz, rng), index)
            for index in range(len(students))
            for _ in range(rng.randint(1, 2 * options['visits'] - 1))
        )
        shown = clicks = dismissals = empty = 0
        for number, (at, index) in enumerate(visits, 1):
            user, taste, location = students[index]
            started = time.perf_counter()
            events = recommend_events(user, timezone.now(), location)
            load_ms = round((time.perf_counter() - started) * 1000)
            if not events:
                empty += 1
                continue
            rows = log_impressions(user, events, timezone.now(), load_ms=load_ms, simulated=True)
            clicked_here = 0
            for row, event in zip(rows, events):
                matches = bool(taste & {interest.slug for interest in event.interests.all()})
                clicked, dismissed = react(row.rank, matches, urgency_of(event, now), rng)
                if clicked and clicked_here >= MAX_CLICKS_PER_VISIT:
                    clicked = False
                clicked_here += clicked
                row.clicked, row.dismissed, row.shown_at = clicked, dismissed, at
                row.dismissed_at = at if dismissed else None
                clicks, dismissals = clicks + clicked, dismissals + dismissed
            type(rows[0]).objects.bulk_update(rows, ['clicked', 'dismissed', 'dismissed_at', 'shown_at'])
            shown += len(rows)
            if number % 25 == 0:
                self.stdout.write(f'  {number}/{len(visits)} visits')

        if not shown:
            raise CommandError('Nothing was recommended: are there upcoming events with embeddings?')
        self.stdout.write(self.style.SUCCESS(
            f'{len(students)} made-up students, {len(visits)} visits over {options["days"]} days: {shown} cards shown, '
            f'{clicks} clicked, {dismissals} marked "Not interested"'
            + (f', {empty} visits with nothing to recommend' if empty else '') + '.'))
