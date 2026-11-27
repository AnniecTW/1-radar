"""The staff search dashboard: who can see it and what it counts."""
from datetime import timedelta

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from apps.events.tests.test_my_events import HostTestCase
from apps.search.dashboard import percentile
from apps.search.models import SearchEvaluationRun, SearchQueryLog


def log(query, *, outcome, ai=True, results=(), latency=400, embedding=None, error='', top=None, clicked=None,
        simulated=False, days_ago=0):
    row = SearchQueryLog.objects.create(
        raw_query=query, outcome=outcome, result_count=len(results), latency_ms=latency, embedding_ms=embedding,
        error_code=error, top_similarity=top, clicked_event=clicked, is_simulated=simulated,
        parsed_filters={'mode': 'ai' if ai else 'keyword', 'fallback': outcome == 'fallback', 'category': None,
                        'results': [[str(event.pk), None] for event in results]},
    )
    if days_ago:
        SearchQueryLog.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
    return row


class PercentileTests(SimpleTestCase):
    def test_nearest_rank(self):
        self.assertEqual(percentile([400, 100, 300, 200], .5), 200)
        self.assertEqual(percentile(range(1, 101), .95), 95)
        self.assertIsNone(percentile([None], .5))


class SearchDashboardTests(HostTestCase):
    def setUp(self):
        super().setUp()
        self.host.is_staff = True
        self.host.save(update_fields=['is_staff'])
        self.robotics = self.make_event('Robotics Night')

    def page(self, **params):
        return self.client.get(reverse('search_dashboard'), params)

    def test_staff_only(self):
        self.client.force_login(self.make_user('student'))
        self.assertEqual(self.page().status_code, 404)
        self.client.logout()
        self.assertEqual(self.page().status_code, 302)

    def test_empty_dashboard_explains_how_to_get_numbers(self):
        response = self.page()
        self.assertContains(response, 'Search analytics')
        self.assertContains(response, 'python manage.py evaluate_search')

    def test_counts_outcomes_rates_and_clicks(self):
        log('robots', outcome='ai_ranked', results=[self.robotics], latency=300, embedding=200, top=.8,
            clicked=self.robotics)
        log('robots', outcome='ai_ranked', results=[self.robotics], latency=500, embedding=350, top=.7)
        log('robots', outcome='fallback', results=[self.robotics], latency=900, embedding=880, error='timeout')
        log('knitting', outcome='ai_no_match', latency=250, embedding=200, top=.41)
        log('pizza', outcome='keyword', ai=False, latency=60)
        context = self.page().context
        kpis = {kpi['label']: kpi for kpi in context['kpis']}
        self.assertEqual(kpis['Searches']['value'], '5')
        self.assertEqual(kpis['Searches']['note'], '80% used AI search')
        self.assertEqual(kpis['AI search time']['value'], '300 ms')  # Median of 250, 300, 500, 900.
        self.assertEqual(kpis['Fell back to keywords']['value'], '25%')
        self.assertEqual(kpis['No results']['value'], '40%')
        self.assertEqual(kpis['Click-through']['value'], '33.3%')
        self.assertEqual(context['errors'][0]['code'], 'timeout')
        self.assertEqual(context['queries']['top'][0]['query'], 'robots')
        self.assertEqual({row['query'] for row in context['queries']['empty']}, {'knitting', 'pizza'})
        self.assertEqual(context['clicks']['positions'][0]['count'], 1)
        self.assertEqual(context['similarity']['count'], 3)

    def test_real_searches_by_default_and_simulated_on_request(self):
        log('robots', outcome='ai_ranked', results=[self.robotics])
        log('mock', outcome='keyword', ai=False, simulated=True)
        self.assertEqual(self.page().context['rows_count'], 1)
        response = self.page(source='simulated')
        self.assertEqual(response.context['rows_count'], 1)
        self.assertContains(response, 'Includes simulated searches')
        self.assertEqual(self.page(source='all').context['rows_count'], 2)

    def test_period(self):
        log('recent', outcome='keyword', ai=False, days_ago=3)
        log('older', outcome='keyword', ai=False, days_ago=20)
        self.assertEqual(self.page(range='7').context['rows_count'], 1)
        self.assertEqual(self.page(range='30').context['rows_count'], 2)
        self.assertEqual(len(self.page(range='7').context['daily']['columns']), 7)

    def test_rows_from_before_outcomes_were_saved_still_count(self):
        log('old', outcome='', results=[self.robotics])
        kpis = {kpi['label']: kpi for kpi in self.page().context['kpis']}
        self.assertEqual(kpis['Fell back to keywords']['value'], '0%')

    def test_shows_the_latest_evaluation(self):
        sweep = [{'cutoff': cutoff, 'precision': .5, 'recall': .5, 'f1': .5, 'zero_result_rate': 0}
                 for cutoff in (.4, .6, .8)]
        SearchEvaluationRun.objects.create(
            embedding_model='bge', min_similarity=.58, query_count=2, event_count=3, cutoff_sweep=sweep,
            summary={'ai': {'precision': .9, 'recall': .8, 'f1': .85, 'mrr': .9, 'zero_result_rate': 0,
                            'correctly_empty_rate': 1},
                     'keyword': {'precision': .7, 'recall': .2, 'f1': .31, 'mrr': .2, 'zero_result_rate': .7,
                                 'correctly_empty_rate': 1}},
            per_query=[{'query': 'robots', 'relevant': ['a', 'b'], 'ai': {'shown': ['a'], 'recall': .5},
                        'keyword': {'shown': [], 'recall': 0}}],
        )
        response = self.page()
        self.assertContains(response, 'AI vs keyword search')
        self.assertContains(response, 'missed b')
