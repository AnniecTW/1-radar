"""Mock search traffic for the search dashboard, run through the real search code.

Local mode (default) runs each search here, against the configured database's current events, and logs it
exactly as the home page does. With --url it sends the searches to a running site instead (such as the
Azure deployment), which logs them itself with its own timings; this command then finds those rows in the
shared database. Either way the rows are flagged is_simulated, spread over the last --days days, and some
get a simulated click, so the dashboard's per-day charts and click rates have something to show.
"""
import json
import random
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from unittest.mock import patch

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.search.evaluation import DATA_DIR

TRAFFIC_FILE = DATA_DIR / 'traffic.json'
OUTAGE_CODES = ['timeout', 'timeout', 'rate_limited', 'server_error', 'network']
# Searches per hour of the campus day, roughly: quiet mornings, busy afternoons and evenings.
HOUR_WEIGHTS = {hour: weight for hour, weight in zip(range(8, 24), [1, 2, 3, 3, 4, 4, 3, 3, 4, 5, 6, 6, 6, 5, 4, 2])}
CLICK_CHANCE = {'ai_ranked': 0.45, 'keyword': 0.3, 'fallback': 0.25}


def load_traffic(path=TRAFFIC_FILE) -> list[dict]:
    return json.loads(path.read_text())['traffic']


def pick_searches(traffic, count, category_share, categories, rng) -> list[dict]:
    weights = [entry['weight'] for entry in traffic]
    searches = []
    for entry in rng.choices(traffic, weights=weights, k=count):
        searches.append({
            'query': entry['query'],
            'ai': rng.random() < entry['ai_share'],
            'category': rng.choice(categories) if categories and rng.random() < category_share else '',
        })
    return searches


def spread_time(now: datetime, days: int, tz, rng) -> datetime:
    """A time in the last `days` days, at a plausible campus hour, never in the future."""
    for _ in range(20):
        day = (timezone.localtime(now, tz) - timedelta(days=rng.randrange(days))).date()
        hour = rng.choices(list(HOUR_WEIGHTS), weights=list(HOUR_WEIGHTS.values()))[0]
        moment = datetime(day.year, day.month, day.day, hour, rng.randrange(60), rng.randrange(60), tzinfo=tz)
        if moment <= now:
            return moment
    return now - timedelta(minutes=rng.randrange(1, 60))


def simulate_click(log, rng):
    """Maybe open one of the shown results; earlier results are likelier."""
    results = (log.parsed_filters or {}).get('results') or []
    if not results or rng.random() >= CLICK_CHANCE.get(log.outcome, 0.3):
        return None
    position = 0
    while position < len(results) - 1 and rng.random() < 0.45:
        position += 1
    return results[position][0]


class Command(BaseCommand):
    help = 'Log mock searches (flagged simulated) for the search dashboard. Writes to the database: needs --confirm.'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Confirm writing search log rows to this database.')
        parser.add_argument('--count', type=int, default=150, help='How many searches (default 150).')
        parser.add_argument('--days', type=int, default=14, help='Spread them over the last this many days (default 14).')
        parser.add_argument('--fail-rate', type=float,
                            help='Share of AI searches given a fake Cloudflare outage, local mode only (default 0.1).')
        parser.add_argument('--category-share', type=float, default=0.15,
                            help='Share of searches with a category filter (default 0.15).')
        parser.add_argument('--url', default='', help='Send the searches to this site instead, e.g. the Azure URL.')
        parser.add_argument('--seed', type=int, help='Random seed, to repeat the same mix.')
        parser.add_argument('--clear', action='store_true', help='Delete every simulated search first.')

    def handle(self, *args, **options):
        from apps.discovery.selectors import get_campus_timezone
        from apps.interests.models import Interest
        from apps.search.models import SearchQueryLog

        if not options['confirm']:
            raise CommandError('This writes search log rows to the configured database. Re-run with --confirm.')
        if options['count'] < 1 or options['days'] < 1:
            raise CommandError('--count and --days must be at least 1.')
        if options['url'] and options['fail_rate'] is not None:
            raise CommandError("--fail-rate only works in local mode: the live site can't be told to fail.")
        fail_rate = 0.1 if options['fail_rate'] is None else options['fail_rate']
        if not 0 <= fail_rate <= 1 or not 0 <= options['category_share'] <= 1:
            raise CommandError('--fail-rate and --category-share must be between 0 and 1.')

        if options['clear']:
            deleted, _ = SearchQueryLog.objects.filter(is_simulated=True).delete()
            self.stdout.write(f'Deleted {deleted} simulated searches.')

        rng = random.Random(options['seed'])
        categories = list(Interest.objects.filter(is_active=True).values_list('slug', flat=True))
        searches = pick_searches(load_traffic(), options['count'], options['category_share'], categories, rng)
        if options['url']:
            logs = self.replay_remote(options['url'].rstrip('/'), searches)
        else:
            logs = self.replay_local(searches, fail_rate, rng)

        now, tz = timezone.now(), get_campus_timezone()
        clicks = 0
        for log in logs:
            clicked = simulate_click(log, rng)
            clicks += clicked is not None
            SearchQueryLog.objects.filter(pk=log.pk).update(
                is_simulated=True, created_at=spread_time(now, options['days'], tz, rng), clicked_event_id=clicked)
        outcomes = {}
        for log in logs:
            outcomes[log.outcome or 'unknown'] = outcomes.get(log.outcome or 'unknown', 0) + 1
        self.stdout.write(self.style.SUCCESS(
            f'Logged {len(logs)} simulated searches over {options["days"]} days, {clicks} with a click. '
            f'Outcomes: {", ".join(f"{name} {count}" for name, count in sorted(outcomes.items()))}.'))

    def replay_local(self, searches, fail_rate, rng):
        from apps.discovery.selectors import list_browse_events, search_browse_events
        from apps.events.semantic_search import EmbeddingError
        from apps.search.services import log_search

        logs = []
        for number, search in enumerate(searches, 1):
            now = timezone.now()
            outage = search['ai'] and rng.random() < fail_rate
            started = time.perf_counter()
            semantic = None
            if search['ai'] and outage:
                error = EmbeddingError('Simulated outage', code=rng.choice(OUTAGE_CODES))
                with patch('apps.events.semantic_search.embed_text', side_effect=error):
                    semantic = search_browse_events(now, search['category'], search['query'])
                events = semantic.events
            elif search['ai']:
                semantic = search_browse_events(now, search['category'], search['query'])
                events = semantic.events
            else:
                events = list_browse_events(now, search['category'], search['query'])
            log = log_search(query=search['query'], ai=search['ai'], semantic=semantic, category=search['category'],
                             events=events, latency_ms=round((time.perf_counter() - started) * 1000), now=now,
                             simulated=True)
            if log is None:
                raise CommandError('A search log row could not be saved; see the error above.')
            logs.append(log)
            if number % 25 == 0:
                self.stdout.write(f'  {number}/{len(searches)} searches')
        return logs

    def replay_remote(self, base_url, searches):
        from apps.search.models import SearchQueryLog
        from apps.search.services import redact

        started_at = timezone.now() - timedelta(seconds=60)  # Room for the two clocks to differ a little.
        sent = []
        for number, search in enumerate(searches, 1):
            params = {'q': search['query']}
            if search['ai']:
                params['semantic'] = '1'
            if search['category']:
                params['category'] = search['category']
            request = urllib.request.Request(f'{base_url}/?{urllib.parse.urlencode(params)}',
                                             headers={'User-Agent': 'Radar search replay'})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    response.read()
            except OSError as exc:
                raise CommandError(f'Search {number} failed ({exc}); {len(sent)} were sent.') from exc
            sent.append(redact(search['query']))
            if number % 25 == 0:
                self.stdout.write(f'  {number}/{len(searches)} searches sent')

        # Pair each search sent with the site's row for it, in order. Only unflagged rows logged since the
        # run began whose text matches a mock query are touched, so a real search is never flagged.
        candidates = list(SearchQueryLog.objects.filter(created_at__gte=started_at, is_simulated=False,
                                                        raw_query__in=set(sent)).order_by('created_at', 'pk'))
        logs = []
        for query in sent:
            match = next((row for row in candidates if row.raw_query == query), None)
            if match is not None:
                candidates.remove(match)
                logs.append(match)
        if len(logs) < len(sent):
            self.stdout.write(self.style.WARNING(
                f'Found {len(logs)} of {len(sent)} searches in the log. Is the site running this version, and '
                'using this database?'))
        return logs
