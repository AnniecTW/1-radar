"""Cloudflare BGE embedding and in-process ranking helpers."""
import json
import logging
import math
import time
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)
DIMENSIONS = 384
POOLING = 'mean'
DEFAULT_MODEL = '@cf/baai/bge-small-en-v1.5'


class EmbeddingError(Exception):
    pass


def model_id():
    return getattr(settings, 'CLOUDFLARE_EMBEDDING_MODEL', DEFAULT_MODEL)


def event_text(event):
    categories = list(event.interests.values_list('name', flat=True))
    venue = event.venue.name if event.venue_id else ''
    parts = [event.title, event.description, 'Categories: ' + ', '.join(categories),
             'Location: ' + ' '.join(filter(None, [venue, event.location_text])),
             'Price: ' + ('free' if event.is_free else event.price_text)]
    return '\n'.join(part for part in parts if part.strip())[:5000]


def _vector(payload):
    # Workers AI returns result.data as a list of vectors for text inputs.
    try:
        result = payload['result']
        values = result.get('data', result.get('embedding'))
        if isinstance(values, dict):
            values = values.get('embedding')
        if isinstance(values, list) and len(values) == 1 and isinstance(values[0], list):
            values = values[0]
        vector = [float(v) for v in values]
    except (KeyError, TypeError, ValueError):
        raise EmbeddingError('Malformed embedding response') from None
    if len(vector) != DIMENSIONS or not all(math.isfinite(v) for v in vector):
        raise EmbeddingError('Invalid embedding vector')
    return vector


def embed_text(text):
    account = getattr(settings, 'CLOUDFLARE_ACCOUNT_ID', '')
    token = getattr(settings, 'CLOUDFLARE_API_TOKEN', '')
    if not account or not token:
        raise EmbeddingError('Cloudflare embedding is not configured')
    url = f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model_id()}'
    body = json.dumps({'text': text, 'pooling': POOLING}).encode()
    timeout = getattr(settings, 'CLOUDFLARE_TIMEOUT', 5)
    for attempt in range(2):
        req = urllib.request.Request(url, body, {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read())
            if not data.get('success'):
                raise EmbeddingError('Cloudflare rejected embedding request')
            return _vector(data)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, EmbeddingError) as exc:
            if attempt == 0:
                time.sleep(.15)
                continue
            logger.warning('Cloudflare embedding unavailable (%s)', type(exc).__name__)
            raise EmbeddingError('Embedding unavailable') from None


def save_event_embedding(event, force=False):
    if not force and valid_event_vector(event):
        return False
    vector = embed_text(event_text(event))
    type(event).objects.filter(pk=event.pk).update(embedding=vector)
    event.embedding = vector
    return True


def cosine(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    denom = math.sqrt(sum(x*x for x in a) * sum(y*y for y in b))
    return dot / denom if denom else 0.0


def valid_event_vector(event):
    vector = event.embedding
    return (isinstance(vector, (list, tuple)) and len(vector) == DIMENSIONS
            and all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector))
