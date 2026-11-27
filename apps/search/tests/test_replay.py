"""replay_search_traffic: mock searches through the real search code, flagged simulated."""
from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.events.semantic_search import DIMENSIONS, EmbeddingError
from apps.events.tests.test_my_events import HostTestCase
from apps.search.models import SearchQueryLog

VECTOR = [1.0] + [0.0] * (DIMENSIONS - 1)


class ReplayTests(HostTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch('apps.events.semantic_search.embed_text', side_effect=EmbeddingError('offline'))
        self.embed = patcher.start()
        self.addCleanup(patcher.stop)
        self.pizza = self.make_event('Free Pizza Social')
        type(self.pizza).objects.filter(pk=self.pizza.pk).update(embedding=VECTOR)
        self.embed.side_effect = None
        self.embed.return_value = VECTOR

    def replay(self, *args):
        call_command('replay_search_traffic', '--confirm', '--seed', '7', *args, stdout=StringIO())

    def test_needs_confirm(self):
        with self.assertRaises(CommandError):
            call_command('replay_search_traffic', stdout=StringIO())

    def test_logs_simulated_searches_spread_over_the_period(self):
        self.replay('--count', '40', '--days', '5', '--fail-rate', '0.5')
        logs = SearchQueryLog.objects.all()
        self.assertEqual(logs.count(), 40)
        self.assertFalse(logs.filter(is_simulated=False).exists())
        oldest = timezone.now() - timedelta(days=6)
        self.assertFalse(logs.filter(created_at__lt=oldest).exists())
        self.assertFalse(logs.filter(created_at__gt=timezone.now()).exists())
        outcomes = set(logs.values_list('outcome', flat=True))
        self.assertIn('fallback', outcomes)
        self.assertIn('ai_ranked', outcomes)
        self.assertTrue(logs.filter(outcome='fallback').exclude(error_code='').exists())
        for clicked in logs.exclude(clicked_event=None):
            self.assertIn(str(clicked.clicked_event_id), [event_id for event_id, _ in clicked.parsed_filters['results']])

    def test_clear_removes_only_simulated_searches(self):
        SearchQueryLog.objects.create(raw_query='real search', result_count=0)
        self.replay('--count', '5')
        self.replay('--count', '3', '--clear')
        self.assertEqual(SearchQueryLog.objects.filter(is_simulated=True).count(), 3)
        self.assertTrue(SearchQueryLog.objects.filter(raw_query='real search').exists())

    def test_remote_mode_flags_the_sites_rows_but_not_real_searches(self):
        def fake_site(request, timeout):
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(request.full_url).query)['q'][0]
            SearchQueryLog.objects.create(raw_query=query, result_count=0, outcome='keyword')
            return MagicMock()

        SearchQueryLog.objects.create(raw_query='a real person searching', result_count=0)
        with patch('urllib.request.urlopen', side_effect=fake_site):
            self.replay('--count', '6', '--url', 'https://radar.example.net/')
        self.assertEqual(SearchQueryLog.objects.filter(is_simulated=True).count(), 6)
        self.assertFalse(SearchQueryLog.objects.get(raw_query='a real person searching').is_simulated)

    def test_fail_rate_is_local_only(self):
        with self.assertRaises(CommandError):
            self.replay('--url', 'https://radar.example.net', '--fail-rate', '0.2')
