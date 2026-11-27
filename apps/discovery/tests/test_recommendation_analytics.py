"""Recommendation analytics: what impressions record, the staff dashboard, the offline evaluation and the replay."""
import json
import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.discovery.evaluation import (ACTIONS, holdouts_of, load_personas, precision_at, run_evaluation, summarize,
                                       summarize_holdouts)
from apps.discovery.models import RecommendationEvaluationRun, RecommendationImpression
from apps.discovery.recommendations import ALGORITHM_VERSION, FALLBACK_ALGORITHM_VERSION, recommend_events
from apps.engagement.models import EventSave
from apps.events.models import Event
from apps.interests.models import Interest, UserInterest
from apps.search.evaluation import load_events
from apps.search.tests.test_evaluation import fake_embedding

from .test_recommendations import MUSIC, RecommendationTestCase, vector


def impression(user, event, *, rank=1, score=.5, clicked=False, dismissed=False, simulated=False, days_ago=0,
               algorithm=ALGORITHM_VERSION, reason='', load_ms=None, **parts):
    row = RecommendationImpression.objects.create(
        user=user, event=event, rank=rank, score=score, algorithm_version=algorithm, clicked=clicked,
        dismissed=dismissed, is_simulated=simulated, reason=reason, load_ms=load_ms,
        **{f'part_{name}': value for name, value in parts.items()})
    if days_ago:
        RecommendationImpression.objects.filter(pk=row.pk).update(shown_at=timezone.now() - timedelta(days=days_ago))
    return row


class ImpressionDetailTests(RecommendationTestCase):
    def test_row_logs_score_parts_reason_and_time(self):
        jazz = self.make_vector_event('Jazz Night', MUSIC, hours_away=-72)
        EventSave.objects.create(user=self.fan, event=jazz)
        open_mic = self.make_vector_event('Open Mic', MUSIC)
        self.make_vector_event('Late Show', MUSIC, hours_away=24 * 10)
        self.client.get(reverse('recommendations_row'))

        first = RecommendationImpression.objects.get(user=self.fan, event=open_mic)
        self.assertEqual((first.rank, first.reason, first.is_simulated), (1, 'similar', False))
        self.assertAlmostEqual(first.part_similarity, 1.0, places=3)
        self.assertEqual(first.part_follows, 0.0)
        self.assertIsNone(first.part_proximity)  # No location shared: nothing to measure.
        self.assertGreater(first.part_urgency, 0.8)
        self.assertIsNotNone(first.load_ms)
        second = RecommendationImpression.objects.exclude(pk=first.pk).get(user=self.fan)
        self.assertIsNone(second.load_ms)  # One measurement per row, on the first card.

    def test_similarity_is_rescaled_per_user(self):
        jazz = self.make_vector_event('Jazz Night', MUSIC, hours_away=-72)
        EventSave.objects.create(user=self.fan, event=jazz)
        self.make_vector_event('Open Mic', MUSIC)
        self.make_vector_event('Music and food', vector(0, 1))
        self.make_vector_event('Music, food and sports', vector(0, 1, 2))
        self.make_event('No vector yet')
        parts = {event.title: event.rec_similarity for event in recommend_events(self.fan, timezone.now())}
        # Raw cosine: 1, 0.707 and 0.577. Rescaled between the closest and the furthest: 1, 0.307 and 0.
        self.assertAlmostEqual(parts['Open Mic'], 1.0, places=3)
        self.assertAlmostEqual(parts['Music and food'], (.7071 - .5774) / (1 - .5774), places=3)
        self.assertAlmostEqual(parts['Music, food and sports'], 0.0, places=3)
        self.assertEqual(parts['No vector yet'], 0.0)  # Not clamped up to 1.

    def test_interest_tag_fill_in_has_no_parts(self):
        UserInterest.objects.create(user=self.fan, interest=self.music, source=UserInterest.Source.ONBOARDING)
        event = self.make_event('Untagged vectorless')
        event.interests.add(self.music)
        self.client.get(reverse('recommendations_row'))
        row = RecommendationImpression.objects.get(user=self.fan, event=event)
        self.assertEqual((row.algorithm_version, row.reason), (FALLBACK_ALGORITHM_VERSION, 'interest'))
        self.assertIsNone(row.part_similarity)


class RecommendationDashboardTests(RecommendationTestCase):
    def setUp(self):
        super().setUp()
        self.host.is_staff = True
        self.host.save(update_fields=['is_staff'])
        self.client.force_login(self.host)
        self.jazz = self.make_event('Jazz Night')
        self.jazz.interests.add(self.music)
        self.pizza = self.make_event('Pizza Social')
        self.pizza.interests.add(self.food)

    def page(self, **params):
        return self.client.get(reverse('recommendation_dashboard'), params)

    def test_staff_only(self):
        self.client.force_login(self.fan)
        self.assertEqual(self.page().status_code, 404)
        self.client.logout()
        self.assertEqual(self.page().status_code, 302)

    def test_empty_dashboard_and_tabs(self):
        response = self.page(range='7', source='all')
        self.assertContains(response, 'Recommendation analytics')
        self.assertContains(response, 'python manage.py evaluate_recommendations')
        self.assertContains(response, reverse('search_dashboard') + '?range=7&amp;source=all')
        self.assertNotContains(response, 'Meanwhile in')
        search = self.client.get(reverse('search_dashboard'))
        self.assertContains(search, reverse('recommendation_dashboard') + '?range=30&amp;source=real')

    def test_counts_reactions_positions_and_signals(self):
        impression(self.fan, self.jazz, rank=1, score=.8, clicked=True, reason='similar', load_ms=120,
                   similarity=.9, urgency=.5)
        impression(self.fan, self.pizza, rank=2, score=.3, dismissed=True, reason='interest', similarity=.4,
                   urgency=.5)
        impression(self.host, self.pizza, rank=1, score=.2, load_ms=300, similarity=.5, urgency=.5)
        impression(self.host, self.jazz, rank=2, score=0, algorithm=FALLBACK_ALGORITHM_VERSION, reason='interest')
        context = self.page().context
        kpis = {kpi['label']: kpi for kpi in context['kpis']}
        self.assertEqual(kpis['Cards shown']['value'], '4')
        self.assertEqual(kpis['Cards shown']['note'], 'in 2 rows of recommendations')
        self.assertEqual(kpis['Students reached']['value'], '2')
        self.assertEqual(kpis['Click-through']['value'], '25%')
        self.assertEqual(kpis['Not interested']['value'], '25%')
        self.assertEqual(kpis['Time to rank a row']['value'], '120 ms')
        self.assertEqual(kpis['Interest-tag fill-in']['value'], '25%')
        self.assertEqual(context['positions']['first_ctr'], 50)
        similarity = context['signals']['table'][0]
        self.assertEqual((similarity['clicked'], similarity['other'], similarity['strong']), (.9, .45, True))
        self.assertEqual(context['events']['disliked'][0]['name'], self.food.name)
        self.assertEqual(context['score_buckets']['count'], 3)

    def test_real_by_default_period_and_simulated(self):
        impression(self.fan, self.jazz)
        impression(self.fan, self.pizza, simulated=True)
        impression(self.fan, self.pizza, days_ago=20)
        self.assertEqual(self.page().context['rows_count'], 2)
        self.assertEqual(self.page(range='7').context['rows_count'], 1)
        response = self.page(source='simulated')
        self.assertEqual(response.context['rows_count'], 1)
        self.assertContains(response, 'Includes simulated students')

    def test_shows_the_latest_evaluation(self):
        summary = {method: {'hit_rate': hit, 'recall': .5, 'precision_at4': .25, 'mrr': .4, 'empty_rate': 0,
                            'diversity': 3, 'coverage': .6}
                   for method, hit in (('embedding', .9), ('interest_tags', .6), ('soonest', .3))}
        RecommendationEvaluationRun.objects.create(
            algorithm_version=ALGORITHM_VERSION, embedding_model='bge', persona_count=1, event_count=2,
            summary=summary, per_persona=[{'persona': 'foodie', 'about': 'Loves food.', 'relevant': ['a', 'b'],
                                           'embedding': {'shown': ['a'], 'recall': .5}}])
        response = self.page()
        self.assertContains(response, 'Embedding ranking vs simple rules')
        self.assertContains(response, 'missed b')
        hit_rate = response.context['evaluation']['rows'][0]
        self.assertEqual([cell['best'] for cell in hit_rate['cells']], [True, False, False])


EVENTS = [
    {'key': 'jazz', 'title': 'Jazz concert', 'description': 'Live jazz music.', 'interests': ['music'],
     'location_text': 'Hall', 'is_free': True, 'price_text': '', 'days_ahead': 2},
    {'key': 'open-mic', 'title': 'Open mic music night', 'description': 'Sing music.', 'interests': ['music'],
     'location_text': 'Cafe', 'is_free': True, 'price_text': '', 'days_ahead': 3},
    {'key': 'pizza', 'title': 'Pizza social', 'description': 'Free pizza food.', 'interests': ['food'],
     'location_text': 'Union', 'is_free': True, 'price_text': '', 'days_ahead': 1},
]
PERSONAS = [
    {'key': 'music-fan', 'about': 'Likes music.', 'interests': ['music'],
     'history': [{'event': 'jazz', 'action': 'rsvp', 'days_ago': 2},
                 {'event': 'pizza', 'action': 'dismiss', 'days_ago': 1}],
     'relevant': ['open-mic'], 'acceptable': []},
    {'key': 'no-taste', 'about': 'Nothing yet.', 'interests': [], 'history': [], 'relevant': [], 'acceptable': []},
]


class EvaluationTests(RecommendationTestCase):
    def setUp(self):
        super().setUp()
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        self.paths = {'events_path': folder / 'events.json', 'personas_path': folder / 'personas.json',
                      'cache_path': folder / 'cache.json'}
        self.paths['events_path'].write_text(json.dumps({'events': EVENTS}))
        self.paths['personas_path'].write_text(json.dumps({'personas': PERSONAS}))
        patcher = patch('apps.events.semantic_search.embed_text', side_effect=fake_embedding)
        self.embed = patcher.start()
        self.addCleanup(patcher.stop)

    def test_scores_three_methods_and_leaves_nothing_behind(self):
        users, events = User.objects.count(), Event.objects.count()
        report = run_evaluation(timezone.now(), **self.paths)
        self.assertEqual((User.objects.count(), Event.objects.count()), (users, events))
        fan = report['per_persona'][0]
        self.assertEqual(fan['embedding']['shown'][0], 'open-mic')  # jazz is RSVP'd, so it's left out.
        self.assertNotIn('jazz', fan['soonest']['shown'])
        self.assertEqual(report['summary']['embedding']['hit_rate'], 1.0)
        self.assertEqual(report['per_persona'][1]['interest_tags']['shown'], [])
        self.assertEqual(report['per_persona'][1]['embedding']['shown'], [])  # Nothing to go on.

        # Hold-out: without the RSVP, jazz is a candidate again and should come back.
        (hidden,) = fan['holdouts']
        self.assertEqual((hidden['event'], hidden['action']), ('jazz', 'rsvp'))
        self.assertIsNotNone(hidden['embedding'])
        self.assertEqual((hidden['interest_tags'], hidden['soonest']), (1, 1))  # Pizza was dismissed.
        self.assertNotIn('pizza', fan['soonest']['shown'])
        self.assertEqual(report['per_persona'][1]['holdouts'], [])
        self.assertEqual(report['summary']['soonest']['holdout_mrr'], 1.0)

        calls = self.embed.call_count
        self.assertEqual(run_evaluation(timezone.now(), offline=True, **self.paths)['cloudflare_calls'], 0)
        self.assertEqual(self.embed.call_count, calls)

    def test_command_saves_a_run(self):
        def run(now, offline=False):
            return run_evaluation(now, offline=offline, **self.paths)

        out = StringIO()
        with patch('apps.discovery.management.commands.evaluate_recommendations.run_evaluation', run):
            call_command('evaluate_recommendations', '--note', 'test', '--personas', stdout=out)
        self.assertIn('Hit rate', out.getvalue())
        self.assertEqual(RecommendationEvaluationRun.objects.get().note, 'test')

    def test_shipped_personas_use_real_events_and_categories(self):
        keys = {event['key'] for event in load_events()}
        slugs = set(Interest.objects.filter(is_active=True).values_list('slug', flat=True))
        for persona in load_personas():
            history = {item['event'] for item in persona['history']}
            self.assertLessEqual(set(persona['relevant']) | set(persona['acceptable']) | history, keys, persona['key'])
            self.assertLessEqual(set(persona['interests']), slugs, persona['key'])
            self.assertFalse(set(persona['relevant']) & (set(persona['acceptable']) | history), persona['key'])
            self.assertLessEqual({item['action'] for item in persona['history']}, ACTIONS, persona['key'])


class SummaryTests(SimpleTestCase):
    def test_summary(self):
        scores = [{'relevant': ['a'], 'shown': ['a', 'b'], 'hits': 1, 'precision_at4': .25, 'recall': 1.0,
                   'reciprocal_rank': 1.0, 'categories': 2},
                  {'relevant': ['c'], 'shown': [], 'hits': 0, 'precision_at4': 0.0, 'recall': 0.0,
                   'reciprocal_rank': 0.0, 'categories': 0}]
        summary = summarize(scores, event_count=4)
        self.assertEqual((summary['hit_rate'], summary['recall'], summary['precision_at4']), (.5, .5, .125))
        self.assertEqual((summary['empty_rate'], summary['coverage'], summary['diversity']), (.5, .5, 2))

    def test_precision_at_4(self):
        self.assertEqual(precision_at(['a', 'b'], ['a', 'x', 'b', 'y', 'z'], []), .5)  # The 5th card doesn't count.
        self.assertEqual(precision_at(['a'], ['a'], []), .25)  # A short row: empty slots are misses.
        self.assertEqual(precision_at(['a'], ['a', 'seen', 'x'], ['seen']), round(1 / 3, 4))  # Ignored: 3 slots.
        self.assertEqual(precision_at(['a'], [], []), 0.0)

    def test_holdouts(self):
        self.assertEqual(summarize_holdouts([1, 4, None, None]), {'holdout_hit_rate': .5, 'holdout_mrr': .3125})
        self.assertEqual(summarize_holdouts([]), {'holdout_hit_rate': None, 'holdout_mrr': None})
        persona = {'key': 'p', 'history': [{'event': 'a', 'action': 'rsvp'}, {'event': 'b', 'action': 'like'},
                                           {'event': 'c', 'action': 'save'}]}
        hidden = holdouts_of(persona)
        self.assertEqual([item['event'] for _, item in hidden], ['a', 'c'])  # Likes don't hide an event.
        self.assertEqual([entry['event'] for entry in hidden[0][0]['history']], ['b', 'c'])


class ReplayTests(RecommendationTestCase):
    def setUp(self):
        super().setUp()
        Interest.objects.filter(is_active=True).update(embedding=None)
        Interest.objects.filter(pk__in=[self.music.pk, self.food.pk]).update(embedding=MUSIC)
        for title in ('Jazz Night', 'Open Mic', 'Choir'):
            self.make_vector_event(title, MUSIC, interests=[self.music])

    def test_needs_confirm(self):
        with self.assertRaises(CommandError):
            call_command('replay_recommendation_traffic', stdout=StringIO())

    def test_logs_simulated_impressions_for_made_up_students_and_clears_them(self):
        out = StringIO()
        call_command('replay_recommendation_traffic', '--confirm', '--users', '3', '--visits', '2', '--seed', '4',
                     stdout=out)
        students = User.objects.filter(username__startswith='rec-sim-')
        self.assertEqual(students.count(), 3)
        self.assertFalse(students.filter(is_active=True).exists())
        rows = RecommendationImpression.objects.filter(user__in=students)
        self.assertTrue(rows.exists())
        self.assertFalse(rows.filter(is_simulated=False).exists())
        self.assertLessEqual(max(rows.values_list('shown_at', flat=True)), timezone.now())
        self.assertIn('made-up students', out.getvalue())
        self.assertFalse(EventSave.objects.filter(user__in=students).exists())  # Hosts' numbers stay untouched.

        call_command('replay_recommendation_traffic', '--confirm', '--clear', '--users', '1', '--seed', '4',
                     stdout=StringIO())
        self.assertEqual(User.objects.filter(username__startswith='rec-sim-').count(), 1)
