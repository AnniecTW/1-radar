"""Offline evaluation of AI search against keyword search (`manage.py evaluate_search`).

The made-up events in eval_data/events.json are added inside a transaction that is rolled back, so the
shared database never keeps them, and both searches only look at those events. Each labelled query in
eval_data/queries.json lists the events a good search should show; the scores compare what each search
shows with that list. Embeddings are cached in eval_data/embedding_cache.json, so only the first run (or a
changed event, query or model) calls Cloudflare.
"""
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.db import transaction

DATA_DIR = Path(__file__).resolve().parent / 'eval_data'
EVENTS_FILE = DATA_DIR / 'events.json'
QUERIES_FILE = DATA_DIR / 'queries.json'
CACHE_FILE = DATA_DIR / 'embedding_cache.json'
CUTOFFS = [round(0.40 + step * 0.02, 2) for step in range(21)]  # 0.40, 0.42, ... 0.80


def load_events(path: Path = EVENTS_FILE) -> list[dict]:
    return json.loads(path.read_text())['events']


def load_queries(path: Path = QUERIES_FILE) -> list[dict]:
    return json.loads(path.read_text())['queries']


class CachedEmbedder:
    """Stands in for embed_text during the run. Looks each text up in the cache file first; with
    offline=True a missing text is an error instead of a Cloudflare call."""

    def __init__(self, embed, model: str, path: Path = CACHE_FILE, offline: bool = False):
        self.embed, self.model, self.path, self.offline = embed, model, path, offline
        self.vectors = json.loads(path.read_text()) if path.exists() else {}
        self.calls = 0
        self.changed = False

    def key(self, text: str) -> str:
        return hashlib.sha256(f'{self.model}\n{text}'.encode()).hexdigest()[:20]

    def __call__(self, text: str):
        key = self.key(text)
        if key not in self.vectors:
            if self.offline:
                from apps.events.semantic_search import EmbeddingError

                raise EmbeddingError('Not in the embedding cache (run without --offline)', code='not_configured')
            self.vectors[key] = [round(value, 6) for value in self.embed(text)]
            self.calls += 1
            self.changed = True
        return self.vectors[key]

    def save(self):
        if self.changed:
            self.path.write_text(json.dumps(self.vectors, separators=(',', ':')) + '\n')


@dataclass
class QueryScore:
    query: str
    relevant: list[str]
    acceptable: list[str]  # Borderline events: ignored when shown, not needed when missing.
    shown: list[str]
    hits: int
    off_target: int  # Shown events that are neither relevant nor acceptable.
    precision: float | None  # None when nothing judged was shown.
    recall: float | None  # None when nothing is relevant.
    reciprocal_rank: float | None  # 1 / position of the first relevant result; None when nothing is relevant.

    def as_dict(self):
        return {key: getattr(self, key) for key in self.__dataclass_fields__}


def score_query(query: str, relevant: list[str], shown: list[str], acceptable: list[str] = ()) -> QueryScore:
    """Acceptable events are left out of the shown list before scoring, so they neither help nor hurt."""
    wanted = set(relevant)
    ignored = set(acceptable) - wanted
    judged = [key for key in shown if key not in ignored]
    hits = sum(key in wanted for key in judged)
    first = next((position for position, key in enumerate(judged, 1) if key in wanted), None)
    return QueryScore(
        query=query, relevant=list(relevant), acceptable=list(acceptable), shown=shown, hits=hits,
        off_target=len(judged) - hits,
        precision=round(hits / len(judged), 4) if judged else None,
        recall=round(hits / len(wanted), 4) if wanted else None,
        reciprocal_rank=(round(1 / first, 4) if first else 0.0) if wanted else None,
    )


def _mean(values):
    values = [value for value in values if value is not None]
    return round(sum(values) / len(values), 4) if values else None


def summarize(scores: list[QueryScore]) -> dict:
    """Averages over queries. Precision counts only queries that showed something; recall, MRR and the
    zero-result rate count only queries that have relevant events; the no-answer queries are scored on
    whether the search correctly showed nothing (or only acceptable events)."""
    answerable = [score for score in scores if score.relevant]
    unanswerable = [score for score in scores if not score.relevant]
    precision, recall = _mean(score.precision for score in scores), _mean(score.recall for score in answerable)
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision and recall else 0.0
    return {
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'mrr': _mean(score.reciprocal_rank for score in answerable),
        'zero_result_rate': round(sum(not score.shown for score in answerable) / len(answerable), 4)
        if answerable else None,
        'correctly_empty_rate': round(sum(not score.off_target for score in unanswerable) / len(unanswerable), 4)
        if unanswerable else None,
        'mean_shown': _mean(len(score.shown) for score in scores),
    }


def sweep_cutoffs(ranked: dict[str, list[tuple[str, float]]], queries: list[dict], limit: int) -> list[dict]:
    """AI search scores at each similarity cutoff, from the same ranked candidates."""
    rows = []
    for cutoff in CUTOFFS:
        scores = [score_query(query['query'], query['relevant'],
                              [key for key, similarity in ranked[query['query']] if similarity >= cutoff][:limit],
                              query.get('acceptable', []))
                  for query in queries]
        rows.append({'cutoff': cutoff, **summarize(scores)})
    return rows


def _create_events(definitions: list[dict], now):
    """The evaluation events, published and upcoming, hosted by a throwaway user. Returns {key: event}."""
    from apps.accounts.models import User
    from apps.events.models import Event
    from apps.interests.models import Interest

    tag = secrets.token_hex(4)
    host = User.objects.create_user(username=f'search-eval-{tag}', email=f'search-eval-{tag}@example.edu',
                                    password=secrets.token_urlsafe(16))
    interests = {interest.slug: interest for interest in Interest.objects.filter(is_active=True)}
    created = {}
    for definition in definitions:
        start = (now + timedelta(days=definition['days_ahead'])).replace(hour=23, minute=0, second=0, microsecond=0)
        event = Event.objects.create(
            title=definition['title'], description=definition['description'], host_user=host,
            slug=f"search-eval-{definition['key']}-{tag}", status=Event.Status.PUBLISHED,
            visibility=Event.Visibility.PUBLIC, start_at=start, end_at=start + timedelta(hours=2),
            location_text=definition['location_text'], is_free=definition['is_free'],
            price_text=definition['price_text'],
        )
        event.interests.set([interests[slug] for slug in definition['interests'] if slug in interests])
        created[definition['key']] = event
    return created


def run_evaluation(now, *, offline: bool = False, events_path: Path = EVENTS_FILE,
                   queries_path: Path = QUERIES_FILE, cache_path: Path = CACHE_FILE) -> dict:
    """Score both searches on every labelled query. Nothing is written to the database."""
    from apps.discovery.selectors import (
        BROWSE_GRID_SIZE,
        list_browse_events,
        list_upcoming_events,
        rank_by_meaning,
        search_browse_events,
        semantic_min_similarity,
    )
    from apps.events import semantic_search

    definitions, queries = load_events(events_path), load_queries(queries_path)
    embedder = CachedEmbedder(semantic_search.embed_text, semantic_search.model_id(), cache_path, offline)
    results = {'ai': [], 'keyword': []}
    ranked = {}
    with patch('apps.events.semantic_search.embed_text', embedder), transaction.atomic():
        created = _create_events(definitions, now)
        key_of = {event.pk: key for key, event in created.items()}
        missing = [key for key, event in created.items()
                   if type(event).objects.filter(pk=event.pk, embedding__isnull=True).exists()]
        if missing:
            raise RuntimeError(f'These events have no embedding: {", ".join(missing)}')
        corpus = list_upcoming_events(now).filter(pk__in=key_of)
        for query in queries:
            text = query['query']
            ai = search_browse_events(now, '', text, events=corpus)
            if ai.fallback:
                raise RuntimeError(f'Cloudflare failed on "{text}" ({ai.error_code}); nothing was scored.')
            keyword = list_browse_events(now, '', text, events=corpus)
            acceptable = query.get('acceptable', [])
            results['ai'].append(score_query(text, query['relevant'], [key_of[event.pk] for event in ai.events],
                                             acceptable))
            results['keyword'].append(score_query(text, query['relevant'], [key_of[event.pk] for event in keyword],
                                                  acceptable))
            ranked[text] = [(key_of[event.pk], 1 - event.cosine_distance)
                            for event in rank_by_meaning(corpus, embedder(text), limit=len(created))]
        transaction.set_rollback(True)
    embedder.save()
    return {
        'embedding_model': semantic_search.model_id(),
        'min_similarity': semantic_min_similarity(),
        'event_count': len(definitions),
        'query_count': len(queries),
        'cloudflare_calls': embedder.calls,
        'summary': {mode: summarize(scores) for mode, scores in results.items()},
        'per_query': [
            {'query': ai.query, 'relevant': ai.relevant, 'acceptable': ai.acceptable,
             'ai': ai.as_dict(), 'keyword': keyword.as_dict()}
            for ai, keyword in zip(results['ai'], results['keyword'])
        ],
        'cutoff_sweep': sweep_cutoffs(ranked, queries, BROWSE_GRID_SIZE),
    }
