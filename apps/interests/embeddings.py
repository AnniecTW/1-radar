"""Interest embeddings: the same Cloudflare BGE model as events, so interests and events can be compared."""
import logging
import math

logger = logging.getLogger(__name__)


def interest_text(interest) -> str:
    """The text an interest is embedded from: its internal description, or its name and group if it has none."""
    description = (interest.description or '').strip()
    if description:
        return description
    return f'{interest.name} ({interest.group})' if interest.group else interest.name


def has_valid_vector(interest) -> bool:
    from apps.events.semantic_search import DIMENSIONS

    vector = interest.embedding
    return (vector is not None and len(vector) == DIMENSIONS
            and all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector))


def save_interest_embedding(interest, force=False) -> bool:
    """Embed one interest. Returns False when it already had a valid vector. Raises EmbeddingError on failure."""
    from apps.events.semantic_search import embed_text

    if not force and has_valid_vector(interest):
        return False
    vector = embed_text(interest_text(interest))
    type(interest).objects.filter(pk=interest.pk).update(embedding=vector)
    interest.embedding = vector
    return True


def embed_missing_interests(report=None) -> tuple[int, bool]:
    """Embed active interests that have no vector yet. Stops at the first failure so a Cloudflare outage
    can't hold up `migrate`. `report` is called with a line per interest. Returns (how many were embedded,
    whether every one succeeded)."""
    from apps.events.semantic_search import EmbeddingError

    from .models import Interest

    embedded = 0
    for interest in Interest.objects.filter(is_active=True, embedding__isnull=True).order_by('pk'):
        try:
            save_interest_embedding(interest, force=True)
        except EmbeddingError:
            logger.warning('Interest embedding deferred; run embed_interests (interest_id=%s)', interest.pk)
            return embedded, False
        embedded += 1
        if report:
            report(f'Embedded interest "{interest.name}"')
    return embedded, True
