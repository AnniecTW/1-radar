"""Offline evaluation of "Recommended for you" (`manage.py evaluate_recommendations`).

Made-up students (eval_data/personas.json) pick interests and act on the made-up events that evaluate_search
uses (apps/search/eval_data/events.json). Everything is created inside a transaction that is rolled back, so the
shared database never keeps it, and recommendations only draw from those test events. Each persona lists the
events it would want; the scores compare each method's top 10 with that list:

- embedding: the real recommender (recommend_events), including its interest-tag fill-in.
- interest_tags: upcoming events in the persona's chosen categories, most popular then soonest (the old fallback).
- soonest: the same upcoming events for everyone, soonest first. Not personalised: the floor to beat.

Two tests per method:

- Labelled: each persona lists the events it would want (relevant) and borderline ones (acceptable); the scores
  compare the top 10 with that list. Events the persona already acted on are left out of these scores: RSVP'd and
  saved ones are never recommended, and liked or viewed ones are already part of the profile.
- Hold-out: for each event a persona RSVP'd to or saved, the persona is created again without that action, and
  the test checks whether the event comes back in the top 10, and where. The recommender hides RSVP'd and saved
  events, so the action has to be removed for the event to be a candidate at all.

Embeddings come from the same cache file as evaluate_search, so a rerun makes no Cloudflare calls. Interests are
re-embedded through the cache too, so a run never depends on the vectors stored in the shared database.
"""
import json
import secrets
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.db import transaction

from apps.search.evaluation import CACHE_FILE, EVENTS_FILE, load_events

DATA_DIR = Path(__file__).resolve().parent / 'eval_data'
PERSONAS_FILE = DATA_DIR / 'personas.json'
METHODS = ['embedding', 'interest_tags', 'soonest']
PRECISION_AT = 4  # Precision is measured on the first this many cards.
ACTIONS = {'rsvp', 'save', 'like', 'view', 'dismiss'}  # dismiss: "Not interested" on a Recommended card.
HOLD_OUT_ACTIONS = {'rsvp', 'save'}  # The actions that hide an event from Recommended.


def load_personas(path: Path = PERSONAS_FILE) -> list[dict]:
    return json.loads(path.read_text())['personas']


def _mean(values):
    values = [value for value in values if value is not None]
    return round(sum(values) / len(values), 4) if values else None


def summarize(scores: list[dict], event_count: int) -> dict:
    """Averages over personas. Precision@4, recall@10, hit rate and MRR count personas with relevant events
    (a persona shown nothing scores 0). Diversity is the categories in a list; coverage, the share of test events
    recommended to anyone."""
    answerable = [score for score in scores if score['relevant']]
    shown = {key for score in scores for key in score['shown']}
    return {
        'precision_at4': _mean(score['precision_at4'] for score in answerable),
        'recall': _mean(score['recall'] for score in answerable),
        'hit_rate': round(sum(score['hits'] > 0 for score in answerable) / len(answerable), 4) if answerable else None,
        'mrr': _mean(score['reciprocal_rank'] for score in answerable),
        'empty_rate': round(sum(not score['shown'] for score in scores) / len(scores), 4) if scores else None,
        'diversity': _mean(score['categories'] for score in scores if score['shown']),
        'coverage': round(len(shown) / event_count, 4) if event_count else None,
        'mean_shown': _mean(len(score['shown']) for score in scores),
    }


def summarize_holdouts(ranks: list) -> dict:
    """ranks: where each hidden event came back in the top 10, or None. Hit rate and MRR over all hidden events."""
    if not ranks:
        return {'holdout_hit_rate': None, 'holdout_mrr': None}
    return {
        'holdout_hit_rate': round(sum(rank is not None for rank in ranks) / len(ranks), 4),
        'holdout_mrr': round(sum(1 / rank for rank in ranks if rank) / len(ranks), 4),
    }


def holdouts_of(persona: dict) -> list[tuple[dict, dict]]:
    """(persona without one RSVP or save, that history item), for each RSVP or save in its history."""
    history = persona['history']
    return [({**persona, 'key': f"{persona['key']}-minus-{item['event']}",
              'history': history[:index] + history[index + 1:]}, item)
            for index, item in enumerate(history) if item['action'] in HOLD_OUT_ACTIONS]


def precision_at(relevant, shown: list[str], ignored, k: int = PRECISION_AT) -> float | None:
    """Share of the first k cards that is wanted. Divided by k even when fewer cards were shown, so a method
    can't score higher by showing less; an ignored (acceptable or already acted on) card in the first k is left
    out of both counts. Precision over all 10 would punish filling the row when a student wants 2-5 events."""
    top = shown[:k]
    slots = k - sum(key in set(ignored) - set(relevant) for key in top)
    return round(sum(key in relevant for key in top) / slots, 4) if slots else None


def score_list(persona: dict, shown: list[str], interests_of: dict) -> dict:
    """Score one top-10 list. History events are ignored like acceptable ones: having acted on an event
    already, seeing it again is neither a hit nor a miss."""
    from apps.search.evaluation import score_query

    ignored = list(persona['acceptable']) + [item['event'] for item in persona['history']]
    score = score_query(persona['key'], persona['relevant'], shown, ignored).as_dict()
    score['acceptable'] = list(persona['acceptable'])
    score['precision_at4'] = precision_at(persona['relevant'], shown, ignored)
    score['categories'] = len({slug for key in shown for slug in interests_of[key]})
    return score


def _create_persona(persona: dict, events: dict, interests: dict, now, tag: str):
    from apps.accounts.models import User
    from apps.engagement.models import EventLike, EventSave, EventView
    from apps.interests.models import UserInterest
    from apps.rsvps.models import RSVP

    user = User.objects.create_user(username=f'rec-eval-{persona["key"]}-{tag}'[:150],
                                    email=f'rec-eval-{persona["key"]}-{tag}@example.edu',
                                    password=secrets.token_urlsafe(16))
    for slug in persona['interests']:
        UserInterest.objects.create(user=user, interest=interests[slug], source=UserInterest.Source.ONBOARDING)
    from .models import RecommendationImpression
    from .recommendations import ALGORITHM_VERSION

    for item in persona['history']:
        event, at = events[item['event']], now - timedelta(days=item['days_ago'])
        if item['action'] not in ACTIONS:
            raise RuntimeError(f'Persona {persona["key"]} has an unknown action: {item["action"]}')
        if item['action'] == 'dismiss':
            row = RecommendationImpression.objects.create(user=user, event=event, rank=1, score=0.0,
                                                          algorithm_version=ALGORITHM_VERSION, dismissed=True,
                                                          dismissed_at=at)
            RecommendationImpression.objects.filter(pk=row.pk).update(shown_at=at)
            continue
        model, fields = {
            'rsvp': (RSVP, {'status': RSVP.Status.GOING}),
            'save': (EventSave, {}),
            'like': (EventLike, {}),
            'view': (EventView, {}),
        }[item['action']]
        row = model.objects.create(user=user, event=event, **fields)
        model.objects.filter(pk=row.pk).update(created_at=at)
    return user


def run_evaluation(now, *, offline: bool = False, personas_path: Path = PERSONAS_FILE,
                   events_path: Path = EVENTS_FILE, cache_path: Path = CACHE_FILE) -> dict:
    """Score the three methods for every persona, labelled and hold-out. Nothing is written to the database."""
    from apps.events import semantic_search
    from apps.interests.embeddings import save_interest_embedding
    from apps.interests.models import Interest
    from apps.search.evaluation import CachedEmbedder, _create_events

    from .recommendations import ALGORITHM_VERSION, CAROUSEL_SIZE, exclude_for_user, recommend_events
    from .selectors import list_upcoming_events

    definitions, personas = load_events(events_path), load_personas(personas_path)
    interests_of = {definition['key']: definition['interests'] for definition in definitions}
    embedder = CachedEmbedder(semantic_search.embed_text, semantic_search.model_id(), cache_path, offline)
    results = {method: [] for method in METHODS}
    holdouts = []  # Per persona: one dict per hidden event, with its rank under each method.
    with patch('apps.events.semantic_search.embed_text', embedder), transaction.atomic():
        created = _create_events(definitions, now)
        key_of = {event.pk: key for key, event in created.items()}
        if type(next(iter(created.values()))).objects.filter(pk__in=key_of, embedding__isnull=True).exists():
            raise RuntimeError('Some test events have no embedding; is Cloudflare reachable?')
        interests = {}
        for interest in Interest.objects.filter(is_active=True):
            save_interest_embedding(interest, force=True)
            interests[interest.slug] = interest
        unknown = {slug for persona in personas for slug in persona['interests']} - set(interests)
        if unknown:
            raise RuntimeError(f'Personas use categories that are not active: {", ".join(sorted(unknown))}')

        corpus = list_upcoming_events(now).filter(pk__in=key_of)
        tag = secrets.token_hex(4)

        def top_lists(persona):
            user = _create_persona(persona, created, interests, now, tag)
            candidates = exclude_for_user(corpus, user)
            chosen = [interests[slug].pk for slug in persona['interests']]
            lists = {
                'embedding': recommend_events(user, now, events=corpus),
                'interest_tags': list(candidates.filter(interests__in=chosen).distinct()
                                      .order_by('-popularity_score', 'start_at')[:CAROUSEL_SIZE]) if chosen else [],
                'soonest': list(candidates.order_by('start_at')[:CAROUSEL_SIZE]),
            }
            return {method: [key_of[event.pk] for event in events] for method, events in lists.items()}

        for persona in personas:
            for method, shown in top_lists(persona).items():
                results[method].append(score_list(persona, shown, interests_of))
            persona_holdouts = []
            for without, item in holdouts_of(persona):
                lists = top_lists(without)
                persona_holdouts.append({
                    'event': item['event'], 'action': item['action'],
                    **{method: lists[method].index(item['event']) + 1 if item['event'] in lists[method] else None
                       for method in METHODS},
                })
            holdouts.append(persona_holdouts)
        transaction.set_rollback(True)
    embedder.save()
    return {
        'algorithm_version': ALGORITHM_VERSION,
        'embedding_model': semantic_search.model_id(),
        'persona_count': len(personas),
        'event_count': len(definitions),
        'cloudflare_calls': embedder.calls,
        'summary': {method: {**summarize(scores, len(definitions)),
                             **summarize_holdouts([item[method] for rows in holdouts for item in rows])}
                    for method, scores in results.items()},
        'per_persona': [
            {'persona': persona['key'], 'about': persona['about'], 'relevant': persona['relevant'],
             'holdouts': holdouts[index], **{method: results[method][index] for method in METHODS}}
            for index, persona in enumerate(personas)
        ],
    }
