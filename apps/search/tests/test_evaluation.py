"""evaluate_search: scoring, and a full run over a small labelled set with a fake embedding model."""
import hashlib
import json
import math
import re
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.events.models import Event
from apps.events.semantic_search import DIMENSIONS
from apps.search import evaluation
from apps.search.evaluation import load_events, load_queries, run_evaluation, score_query, summarize
from apps.search.models import SearchEvaluationRun


def fake_embedding(text):
    """Bag of words: texts that share words point the same way."""
    vector = [0.0] * DIMENSIONS
    for word in re.findall(r'[a-z]+', text.lower()):
        vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % DIMENSIONS] += 1
    norm = math.sqrt(sum(value * value for value in vector)) or 1
    return [value / norm for value in vector]


EVENTS = [
    {'key': 'robots', 'title': 'Robot build night', 'description': 'Build a robot.', 'interests': ['tech'],
     'location_text': 'Lab', 'is_free': True, 'price_text': '', 'days_ahead': 2},
    {'key': 'pizza', 'title': 'Pizza social', 'description': 'Free pizza.', 'interests': ['food'],
     'location_text': 'Union', 'is_free': True, 'price_text': '', 'days_ahead': 3},
]
QUERIES = [{'query': 'robot', 'relevant': ['robots']}, {'query': 'pizza', 'relevant': ['pizza']},
           {'query': 'kayak', 'relevant': []}]


class ScoringTests(SimpleTestCase):
    def test_score_query(self):
        score = score_query('q', ['a', 'b'], ['c', 'a'])
        self.assertEqual((score.hits, score.precision, score.recall, score.reciprocal_rank), (1, .5, .5, .5))
        empty = score_query('q', ['a'], [])
        self.assertEqual((empty.precision, empty.recall, empty.reciprocal_rank), (None, 0, 0))
        nothing_relevant = score_query('q', [], [])
        self.assertEqual((nothing_relevant.recall, nothing_relevant.reciprocal_rank), (None, None))

    def test_acceptable_events_neither_help_nor_hurt(self):
        score = score_query('q', ['a', 'b'], ['ok', 'a', 'c'], acceptable=['ok'])
        self.assertEqual((score.hits, score.off_target, score.precision, score.recall, score.reciprocal_rank),
                         (1, 1, .5, .5, 1.0))
        only_acceptable = score_query('q', ['a'], ['ok'], acceptable=['ok'])
        self.assertEqual((only_acceptable.precision, only_acceptable.recall), (None, 0))
        no_answer = score_query('q', [], ['ok'], acceptable=['ok'])
        self.assertEqual(summarize([no_answer])['correctly_empty_rate'], 1.0)

    def test_summarize(self):
        summary = summarize([score_query('a', ['x'], ['x']), score_query('b', ['y'], []),
                             score_query('c', [], []), score_query('d', [], ['x'])])
        self.assertEqual(summary['precision'], .5)  # Queries that showed something: 1.0 and 0.0.
        self.assertEqual(summary['recall'], .5)
        self.assertEqual(summary['zero_result_rate'], .5)
        self.assertEqual(summary['correctly_empty_rate'], .5)

    def test_shipped_labels_only_name_real_test_events(self):
        keys = {event['key'] for event in load_events()}
        self.assertEqual(len(keys), len(load_events()))
        for query in load_queries():
            self.assertLessEqual(set(query['relevant']), keys, query['query'])
            self.assertLessEqual(set(query['acceptable']), keys, query['query'])
            self.assertFalse(set(query['relevant']) & set(query['acceptable']), query['query'])


class EvaluationRunTests(TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        self.events_file, self.queries_file = folder / 'events.json', folder / 'queries.json'
        self.cache_file = folder / 'cache.json'
        self.events_file.write_text(json.dumps({'events': EVENTS}))
        self.queries_file.write_text(json.dumps({'queries': QUERIES}))
        patcher = patch('apps.events.semantic_search.embed_text', side_effect=fake_embedding)
        self.embed = patcher.start()
        self.addCleanup(patcher.stop)

    def run_it(self, **options):
        return run_evaluation(timezone.now(), events_path=self.events_file, queries_path=self.queries_file,
                              cache_path=self.cache_file, **options)

    def test_scores_both_searches_and_leaves_no_events_behind(self):
        report = self.run_it()
        self.assertFalse(Event.objects.exists())
        by_query = {row['query']: row for row in report['per_query']}
        self.assertEqual(by_query['robot']['keyword']['shown'], ['robots'])  # "robot" is in the title.
        self.assertEqual(by_query['kayak']['keyword']['shown'], [])
        self.assertEqual(report['summary']['keyword']['recall'], 1.0)
        self.assertEqual(len(report['cutoff_sweep']), len(evaluation.CUTOFFS))
        self.assertEqual(report['query_count'], 3)

    def test_embeddings_are_cached_for_the_next_run(self):
        self.run_it()
        calls = self.embed.call_count
        self.assertGreater(calls, 0)
        report = self.run_it(offline=True)
        self.assertEqual(self.embed.call_count, calls)
        self.assertEqual(report['cloudflare_calls'], 0)

    def test_command_saves_a_run(self):
        def run(now, offline=False):
            return run_evaluation(now, offline=offline, events_path=self.events_file,
                                  queries_path=self.queries_file, cache_path=self.cache_file)

        out = StringIO()
        with patch('apps.search.management.commands.evaluate_search.run_evaluation', run):
            call_command('evaluate_search', '--note', 'test run', stdout=out)
            call_command('evaluate_search', '--no-save', stdout=StringIO())
        self.assertIn('Precision', out.getvalue())
        self.assertEqual(SearchEvaluationRun.objects.get().note, 'test run')
