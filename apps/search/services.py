"""Anonymous search log, for finding searches that come up empty and tuning AI search.

Privacy rules: a row never records who searched, email addresses and long numbers (phone numbers,
student IDs) are blanked out before saving, and rows are deleted after 180 days.
"""
import logging
import re
from datetime import datetime, timedelta

from django.core import signing
from django.core.cache import cache
from django.db import DatabaseError

from .models import SearchQueryLog

logger = logging.getLogger(__name__)

RETENTION_DAYS = 180
PRUNE_EVERY_SECONDS = 3600  # Pruning runs on the first search after this long, not on every search.
PRUNE_CACHE_KEY = 'search-log-pruned'
CLICK_WINDOW = timedelta(days=1)  # A result opened later than this isn't counted as a click on that search.
TOKEN_SALT = 'search.query-log'

EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
# Nine or more digits, optionally separated: phone numbers and student IDs, but not years or course numbers.
LONG_NUMBER = re.compile(r'(?:\d[ ().-]?){8,}\d')


def redact(text: str) -> str:
    return LONG_NUMBER.sub('[number]', EMAIL.sub('[email]', text))


def search_outcome(ai: bool, fallback: bool, result_count: int) -> str:
    if not ai:
        return SearchQueryLog.Outcome.KEYWORD
    if fallback:
        return SearchQueryLog.Outcome.FALLBACK
    return SearchQueryLog.Outcome.AI_RANKED if result_count else SearchQueryLog.Outcome.AI_NO_MATCH


def log_search(*, query: str, ai: bool, category: str, events: list, latency_ms: int, now: datetime,
               semantic=None, simulated: bool = False) -> SearchQueryLog | None:
    """Save one search, with the shown results in order (event ID, and the AI similarity when there is one).
    `semantic` is the SemanticSearch of an AI search (apps/discovery/selectors.py). Never raises: a failed
    log must not break the search page."""
    fallback = bool(semantic and semantic.fallback)
    try:
        prune_now_and_then(now)
        return SearchQueryLog.objects.create(
            raw_query=redact(query),
            used_llm=ai and not fallback,  # True only when the embedding model actually ranked the results.
            parsed_filters={
                'mode': 'ai' if ai else 'keyword',
                'fallback': fallback,
                'category': category or None,
                'results': [
                    [str(event.pk), _similarity(event)] for event in events
                ],
            },
            result_count=len(events),
            latency_ms=latency_ms,
            outcome=search_outcome(ai, fallback, len(events)),
            embedding_ms=semantic.embedding_ms if semantic else None,
            error_code=semantic.error_code if semantic else '',
            candidate_count=semantic.candidate_count if semantic and not fallback else None,
            top_similarity=semantic.top_similarity if semantic else None,
            is_simulated=simulated,
        )
    except DatabaseError:
        logger.exception('Search log not saved')
        return None


def _similarity(event):
    distance = getattr(event, 'cosine_distance', None)
    return None if distance is None else round(1 - distance, 4)


def click_token(log: SearchQueryLog) -> str:
    """Goes in result links, so a click can be tied back to its search without knowing who searched."""
    return signing.dumps(log.pk, salt=TOKEN_SALT)


def mark_search_clicked(token: str, event, now: datetime) -> bool:
    """Record the first result opened from a search. Ignores forged or old tokens and events that weren't
    among that search's results."""
    try:
        log_id = signing.loads(token, salt=TOKEN_SALT, max_age=CLICK_WINDOW)
    except signing.BadSignature:  # Also covers expired tokens.
        return False
    log = SearchQueryLog.objects.filter(pk=log_id, clicked_event__isnull=True).first()
    if log is None:
        return False
    shown = [event_id for event_id, _ in (log.parsed_filters or {}).get('results', [])]
    if str(event.pk) not in shown:
        return False
    return bool(SearchQueryLog.objects.filter(pk=log.pk, clicked_event__isnull=True).update(clicked_event=event))


def prune_search_logs(now: datetime, days: int = RETENTION_DAYS) -> int:
    """Delete searches older than `days`. Returns how many rows were deleted."""
    deleted, _ = SearchQueryLog.objects.filter(created_at__lt=now - timedelta(days=days)).delete()
    return deleted


def prune_now_and_then(now: datetime) -> None:
    """Rows have no user to prune by, so prune the whole table, at most once an hour per server process."""
    if cache.add(PRUNE_CACHE_KEY, True, timeout=PRUNE_EVERY_SECONDS):
        prune_search_logs(now)
