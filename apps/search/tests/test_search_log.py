"""The anonymous search log: what a search saves, click tracking, privacy rules and pruning."""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from apps.engagement.models import EventView
from apps.events.semantic_search import DIMENSIONS, EmbeddingError
from apps.events.tests.test_my_events import HostTestCase
from apps.search.models import SearchQueryLog
from apps.search.services import PRUNE_CACHE_KEY, click_token, mark_search_clicked, redact

VECTOR = [1.0] + [0.0] * (DIMENSIONS - 1)


class RedactTests(SimpleTestCase):
    def test_emails_and_long_numbers_are_blanked_but_years_and_courses_stay(self):
        self.assertEqual(redact('study group with jo.lee@illinois.edu'), 'study group with [email]')
        self.assertEqual(redact('call 217-555-0134 about tickets'), 'call [number] about tickets')
        self.assertEqual(redact('UIN 654321987'), 'UIN [number]')
        self.assertEqual(redact('CS 225 review 2026-2027'), 'CS 225 review 2026-2027')


class SearchLogTestCase(HostTestCase):
    def setUp(self):
        super().setUp()
        cache.delete(PRUNE_CACHE_KEY)
        patcher = patch('apps.events.semantic_search.embed_text', side_effect=EmbeddingError('offline'))
        self.embed = patcher.start()
        self.addCleanup(patcher.stop)
        self.robotics = self.make_event('Robotics Night')
        self.pizza = self.make_event('Free Pizza Social')

    def search(self, query, **params):
        return self.client.get(reverse('dashboard'), {'q': query, **params})

    def only_log(self):
        self.assertEqual(SearchQueryLog.objects.count(), 1)
        return SearchQueryLog.objects.get()


class SearchLogTests(SearchLogTestCase):
    def test_keyword_search_is_logged_without_who_searched(self):
        self.client.force_login(self.make_user('searcher'))
        self.search('robotics')
        log = self.only_log()
        self.assertIsNone(log.user)
        self.assertEqual((log.raw_query, log.used_llm, log.result_count), ('robotics', False, 1))
        self.assertEqual(log.parsed_filters, {'mode': 'keyword', 'fallback': False, 'category': None,
                                              'results': [[str(self.robotics.pk), None]]})
        self.assertIsNotNone(log.latency_ms)
        self.assertEqual((log.outcome, log.embedding_ms, log.error_code, log.is_simulated), ('keyword', None, '', False))

    def test_ai_search_logs_each_results_similarity(self):
        type(self.robotics).objects.filter(pk=self.robotics.pk).update(embedding=VECTOR)
        self.embed.side_effect = None
        self.embed.return_value = VECTOR
        self.search('build robots', semantic='1')
        log = self.only_log()
        self.assertTrue(log.used_llm)
        self.assertEqual(log.parsed_filters['mode'], 'ai')
        self.assertEqual(log.parsed_filters['results'], [[str(self.robotics.pk), 1.0]])
        self.assertEqual((log.outcome, log.candidate_count, log.top_similarity, log.error_code), ('ai_ranked', 1, 1.0, ''))
        self.assertIsNotNone(log.embedding_ms)

    def test_ai_search_with_nothing_close_enough_is_a_no_match(self):
        type(self.robotics).objects.filter(pk=self.robotics.pk).update(embedding=VECTOR)
        self.embed.side_effect = None
        self.embed.return_value = [0.0, 1.0] + [0.0] * (DIMENSIONS - 2)  # At right angles: similarity 0.
        self.search('underwater basket weaving', semantic='1')
        log = self.only_log()
        self.assertEqual((log.outcome, log.result_count, log.candidate_count, log.top_similarity),
                         ('ai_no_match', 0, 1, 0.0))

    def test_cloudflare_failure_is_logged_as_a_fallback(self):
        self.search('robotics', semantic='1')
        log = self.only_log()
        self.assertFalse(log.used_llm)
        self.assertEqual((log.parsed_filters['mode'], log.parsed_filters['fallback']), ('ai', True))
        self.assertEqual((log.outcome, log.error_code, log.candidate_count), ('fallback', 'unavailable', None))

    def test_the_cloudflare_error_code_is_logged(self):
        self.embed.side_effect = EmbeddingError('busy', code='rate_limited')
        self.search('robotics', semantic='1')
        self.assertEqual(self.only_log().error_code, 'rate_limited')

    def test_searches_that_return_nothing_are_logged_too(self):
        self.search('underwater basket weaving')
        self.assertEqual(self.only_log().result_count, 0)

    def test_personal_details_are_blanked_before_saving(self):
        self.search('meet jo.lee@illinois.edu')
        self.assertEqual(self.only_log().raw_query, 'meet [email]')

    def test_no_search_or_a_rejected_one_logs_nothing(self):
        self.client.get(reverse('dashboard'))
        self.search('   ')
        self.search('x' * 101)
        self.assertFalse(SearchQueryLog.objects.exists())


class SearchClickTests(SearchLogTestCase):
    def test_opening_a_result_marks_the_click_and_the_views_source(self):
        self.client.force_login(self.make_user('searcher'))  # The host's views of their own events aren't counted.
        response = self.search('robotics')
        log = self.only_log()
        link = reverse('event_detail', args=[self.robotics.slug]) + '?ref=search&amp;s='
        self.assertContains(response, link)
        self.client.get(reverse('event_detail', args=[self.robotics.slug]), {'ref': 'search', 's': click_token(log)})
        log.refresh_from_db()
        self.assertEqual(log.clicked_event, self.robotics)
        self.assertEqual(EventView.objects.get(event=self.robotics).source, 'search')

    def test_only_the_first_result_opened_counts(self):
        self.search('robotics')
        log = self.only_log()
        now = timezone.now()
        self.assertTrue(mark_search_clicked(click_token(log), self.robotics, now))
        self.assertFalse(mark_search_clicked(click_token(log), self.robotics, now))
        log.refresh_from_db()
        self.assertEqual(log.clicked_event, self.robotics)

    def test_forged_or_unrelated_clicks_are_ignored(self):
        self.search('robotics')
        log = self.only_log()
        now = timezone.now()
        self.assertFalse(mark_search_clicked('not-a-token', self.robotics, now))
        self.assertFalse(mark_search_clicked(click_token(log), self.pizza, now))  # Not one of its results.
        log.refresh_from_db()
        self.assertIsNone(log.clicked_event)


class SearchPruneTests(SearchLogTestCase):
    def old_log(self, days_ago):
        log = SearchQueryLog.objects.create(raw_query='old', result_count=0)
        SearchQueryLog.objects.filter(pk=log.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
        return log.pk

    def test_searching_prunes_rows_older_than_180_days_at_most_once_an_hour(self):
        old, recent = self.old_log(181), self.old_log(179)
        self.search('robotics')
        self.assertEqual(set(SearchQueryLog.objects.filter(raw_query='old').values_list('pk', flat=True)), {recent})
        another_old = self.old_log(200)
        self.search('pizza')  # Within the hour: no second prune.
        self.assertTrue(SearchQueryLog.objects.filter(pk=another_old).exists())

    def test_command(self):
        self.old_log(200)
        self.old_log(20)
        out = StringIO()
        call_command('prune_search_logs', stdout=out)
        self.assertIn('Deleted 1 searches older than 180 days', out.getvalue())
        call_command('prune_search_logs', '--days', '10', stdout=StringIO())
        self.assertFalse(SearchQueryLog.objects.exists())
