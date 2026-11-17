"""Snap-a-Flyer: read an event flyer with a vision model and turn it into Create Event form values.

The model only reads the flyer. Everything after that happens in code: dates are resolved against
the upload day in the campus time zone, venues and categories are matched to Radar's own lists, and
a per-field confidence is computed here (the model's own sense of confidence is never used).
"""
import base64
import difflib
import io
import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, time as dtime, timedelta

from dateutil import parser as date_parser
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

logger = logging.getLogger(__name__)

DEFAULT_MODEL = '@cf/moondream/moondream3.1-9B-A2B'
MAX_IMAGE_SIDE = 1600
MAX_CATEGORIES = 3
FIELDS = (
    'title', 'description', 'date', 'start_time', 'end_time', 'location',
    'organizer', 'price', 'registration_url', 'categories',
)
PROMPT = (
    'Read this event flyer. Reply with only a JSON object and no other text, using exactly these keys: '
    'title, description, date, start_time, end_time, location, organizer, price, registration_url, categories. '
    'Copy names, places and times as printed on the flyer. '
    'date: the event date as written, for example "Friday, Nov 21". '
    'start_time and end_time: as written, for example "7 PM". '
    'description: one or two sentences, taken from the flyer, saying what the event is. '
    'price: "free" if the event is free, otherwise the price as written. '
    'registration_url: a sign-up or ticket link printed on the flyer. '
    'categories: a list of up to 3 short topic words, such as "music" or "career". '
    'Use null for anything that is not on the flyer. Do not guess.'
)
EMPTY_VALUES = {'', 'null', 'none', 'n/a', 'na', 'unknown', 'not specified', 'not provided', 'tbd', 'tba', '-'}
# Words on flyers that point to one of Radar's categories.
CATEGORY_HINTS = {
    'Tech': ['tech', 'coding', 'code', 'hackathon', 'ai', 'software', 'programming', 'robot', 'computer', 'data'],
    'Career': ['career', 'resume', 'internship', 'job', 'recruit', 'interview', 'employer'],
    'Study': ['study', 'studying', 'tutoring', 'lecture', 'seminar', 'exam', 'academic', 'review session'],
    'Science': ['science', 'research', 'physics', 'chemistry', 'biology', 'lab', 'astronomy'],
    'Cultural': ['cultural', 'culture', 'heritage', 'festival', 'diwali', 'lunar', 'international'],
    'Food': ['food', 'pizza', 'snacks', 'dinner', 'lunch', 'breakfast', 'potluck', 'boba', 'cookies'],
    'Gaming': ['gaming', 'game', 'games', 'esports', 'board game', 'smash', 'chess'],
    'Networking': ['networking', 'mixer', 'meet and greet', 'social hour', 'alumni'],
    'Arts': ['art', 'arts', 'painting', 'drawing', 'craft', 'gallery', 'exhibit', 'theatre', 'theater'],
    'Music': ['music', 'concert', 'band', 'choir', 'jazz', 'dj', 'karaoke', 'open mic'],
    'Film': ['film', 'movie', 'screening', 'cinema'],
    'Writing': ['writing', 'poetry', 'poem', 'book club', 'literary'],
    'Sports': ['sports', 'basketball', 'soccer', 'football', 'volleyball', 'tournament', 'intramural'],
    'Wellness': ['wellness', 'yoga', 'meditation', 'mental health', 'mindfulness', 'self-care'],
    'Outdoors': ['outdoors', 'hike', 'hiking', 'camping', 'garden', 'nature'],
    'Fitness': ['fitness', 'workout', 'run', '5k', 'gym', 'zumba', 'dance'],
    'Volunteering': ['volunteer', 'volunteering', 'service', 'charity', 'fundraiser', 'donation'],
    'Faith': ['faith', 'worship', 'prayer', 'church', 'bible', 'mosque', 'temple'],
    'Entrepreneurship': ['startup', 'entrepreneur', 'pitch', 'founder', 'venture'],
    'Activism': ['activism', 'rally', 'protest', 'advocacy', 'march', 'union', 'bargaining', 'strike',
                 'picket', 'teach-in', 'speak out', 'austerity'],
}
GENERIC_PLACE_WORDS = {
    'the', 'of', 'for', 'and', 'center', 'centre', 'hall', 'building', 'auditorium', 'library', 'park',
    'museum', 'house', 'arena', 'room', 'uiuc', 'illinois', 'university',
}
FILLER_WORDS = {'at', 'in', 'on', 'inside', 'campus', 'urbana', 'champaign', 'il'}
WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
WEEKDAY_RE = re.compile(r'\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b')
MONTH_RE = re.compile(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\b')
TIME_RE = re.compile(
    r'(?P<hour>\d{1,2})(?:[:.](?P<minute>\d{2}))?\s*(?P<ampm>[ap])?\.?\s*(?:m\b\.?)?', re.IGNORECASE
)
RANGE_SPLIT_RE = re.compile(r'\s*(?:-|–|—|\bto\b|\buntil\b|\btill\b)\s*', re.IGNORECASE)


class FlyerImageError(Exception):
    """The upload isn't an image Radar can read."""


class ExtractionError(Exception):
    """The model couldn't be reached or returned something unusable."""


def model_id():
    return getattr(settings, 'CLOUDFLARE_VISION_MODEL', '') or DEFAULT_MODEL


# ---------------------------------------------------------------- image


def prepare_image(upload):
    """Return the flyer as JPEG bytes: rotated upright, at most 1600 px on its long side."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        upload.seek(0)
        image = Image.open(upload)
        image.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise FlyerImageError("That file isn't an image we can read. Upload a JPG, PNG or WebP photo.") from None
    if image.format not in ('JPEG', 'PNG', 'WEBP', 'MPO'):
        raise FlyerImageError('Upload a JPG, PNG or WebP photo.')
    image = ImageOps.exif_transpose(image)
    if image.mode != 'RGB':
        background = Image.new('RGB', image.size, 'white')
        rgba = image.convert('RGBA')
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    if min(image.size) < 200:
        raise FlyerImageError('This image is too small to read. Upload a clearer photo of the flyer.')
    output = io.BytesIO()
    image.save(output, format='JPEG', quality=85, optimize=True)
    return output.getvalue()


# ---------------------------------------------------------------- model call


def call_vision_model(jpeg_bytes):
    """Send the flyer to Cloudflare Workers AI and return the model's answer text.

    Moondream only returns its answer when streaming is on: without `stream`, Cloudflare replies
    200 with an empty `result` (checked against the live API, Nov 2026).
    """
    account = getattr(settings, 'CLOUDFLARE_ACCOUNT_ID', '')
    token = getattr(settings, 'CLOUDFLARE_API_TOKEN', '')
    if not account or not token:
        raise ExtractionError('Flyer reading is not configured (Cloudflare keys missing).')
    url = f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model_id()}'
    body = json.dumps({
        'task': 'query',
        'image': 'data:image/jpeg;base64,' + base64.b64encode(jpeg_bytes).decode(),
        'question': PROMPT,
        'reasoning': False,
        'temperature': 0,
        'max_tokens': 800,
        'stream': True,
    }).encode()
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    timeout = getattr(settings, 'FLYER_TIMEOUT', 25)
    for attempt in range(2):
        request = urllib.request.Request(url, body, headers, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                answer, usage = read_stream(response)
            if not answer.strip():
                raise ExtractionError('The model returned no answer.')
            logger.info('Flyer model used %s', usage)
            return answer
        except urllib.error.HTTPError as exc:
            # 4xx means the request itself is wrong (bad key, image too large): retrying won't help.
            if exc.code < 500 or attempt == 1:
                logger.warning('Flyer model HTTP error %s', exc.code)
                raise ExtractionError(f'Cloudflare returned HTTP {exc.code}.') from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == 1:
                logger.warning('Flyer model unavailable (%s)', type(exc).__name__)
                raise ExtractionError('The flyer reader is unavailable right now.') from None
        time.sleep(0.3)
    raise ExtractionError('The flyer reader is unavailable right now.')


def read_stream(lines):
    """Rebuild the answer from Cloudflare's server-sent events.

    Each `data:` line is JSON. Answer pieces come as {"chunk": {"answer": ...}}; on the live API each
    piece repeats the whole answer so far, but plain deltas are handled too. Returns (answer, usage).
    """
    answer, usage = '', {}
    for raw in lines:
        line = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line.startswith('data:'):
            continue
        data = line[5:].strip()
        if not data or data == '[DONE]':
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get('errors'):
            raise ExtractionError('Cloudflare reported an error while reading the flyer.')
        if isinstance(event.get('usage'), dict) and event['usage'].get('total_tokens'):
            usage = {key: event['usage'].get(key) for key in ('prompt_tokens', 'completion_tokens', 'neurons')}
        piece = (event.get('chunk') or {}).get('answer') if isinstance(event.get('chunk'), dict) else None
        if not isinstance(piece, str):
            continue
        answer = piece if piece.startswith(answer) else answer + piece
    return answer, usage


def parse_answer(answer):
    """Pull the JSON object out of the model's answer and keep only the expected keys."""
    text = re.sub(r'^```(?:json)?|```$', '', answer.strip(), flags=re.MULTILINE).strip()
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end <= start:
        raise ExtractionError('The model did not return JSON.')
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        raise ExtractionError('The model returned malformed JSON.') from None
    if not isinstance(data, dict):
        raise ExtractionError('The model returned JSON that is not an object.')
    cleaned = {}
    for key in FIELDS:
        value = data.get(key)
        if key == 'categories':
            if isinstance(value, str):
                value = re.split(r'[,#/]', value)
            cleaned[key] = [_clean(v) for v in value if _clean(v)] if isinstance(value, list) else []
        else:
            cleaned[key] = _clean(value)
    if not any(cleaned[key] for key in ('title', 'date', 'location')):
        raise ExtractionError("The model couldn't find event details on this image.")
    return cleaned


def _clean(value):
    if value is None or isinstance(value, (dict, list)):
        return ''
    text = re.sub(r'\s+', ' ', str(value)).strip().strip('"').strip()
    return '' if text.lower() in EMPTY_VALUES else text


# ---------------------------------------------------------------- normalizing


def parse_flyer_date(text, today):
    """Return (date, confidence). Flyers rarely print the year, so pick the next matching date."""
    if not text:
        return None, 0.0
    lowered = text.lower()
    if lowered in ('today', 'tonight'):
        return today, 1.0
    if lowered == 'tomorrow':
        return today + timedelta(days=1), 1.0
    # "24TH" and "3rd" confuse the parser: drop ordinal endings first.
    cleaned = re.sub(r'(\d)(st|nd|rd|th)\b', r'\1', text, flags=re.IGNORECASE)
    lowered = cleaned.lower()
    try:
        parsed = date_parser.parse(cleaned, default=datetime(today.year, today.month, today.day), fuzzy=True).date()
    except (ValueError, OverflowError):
        return None, 0.0
    confidence = 1.0
    has_year = bool(re.search(r'\b(19|20)\d{2}\b', text))
    has_month = bool(MONTH_RE.search(lowered) or re.search(r'\b\d{1,2}[/.-]\d{1,2}\b', lowered))
    printed_weekday = _weekday_in(lowered)
    if not has_month:
        # Only a weekday, e.g. "Friday": the next one from today.
        if printed_weekday is None:
            return None, 0.0
        return today + timedelta(days=(printed_weekday - today.weekday()) % 7), 0.6
    if not has_year and parsed < today - timedelta(days=7):
        parsed = parsed.replace(year=parsed.year + 1)
        confidence = 0.8
    if not has_year and parsed > today + timedelta(days=120):
        confidence = 0.5  # likely an old flyer, not an event many months away
    if printed_weekday is not None and printed_weekday != parsed.weekday():
        confidence = 0.5
    if parsed < today:
        confidence = min(confidence, 0.5)
    return parsed, confidence


def _weekday_in(lowered):
    match = WEEKDAY_RE.search(lowered)
    return WEEKDAYS.index(match.group(1)) if match else None


def _parse_time(text, default_ampm=None):
    """Return (time, had_am_pm) or (None, False)."""
    if not text:
        return None, False
    lowered = text.lower().strip()
    if 'noon' in lowered:
        return dtime(12, 0), True
    if 'midnight' in lowered:
        return dtime(0, 0), True
    match = TIME_RE.search(lowered)
    if not match:
        return None, False
    hour, minute = int(match['hour']), int(match['minute'] or 0)
    ampm = (match['ampm'] or '').lower() or default_ampm
    if minute > 59 or hour > 23:
        return None, False
    if ampm and hour <= 12:
        hour = hour % 12 + (12 if ampm == 'p' else 0)
    return dtime(hour, minute), bool(match['ampm'])


def _ampm_of(text):
    match = TIME_RE.search((text or '').lower())
    return (match['ampm'] or '').lower() if match else ''


def parse_flyer_times(start_text, end_text):
    """Return (start, end, start_confidence, end_confidence)."""
    if start_text and not end_text:
        parts = RANGE_SPLIT_RE.split(start_text, maxsplit=1)
        if len(parts) == 2 and TIME_RE.search(parts[1]):
            start_text, end_text = parts
    # "7-9 PM": the start borrows the end's am/pm.
    start, start_marked = _parse_time(start_text, default_ampm=_ampm_of(end_text) or None)
    start_conf = 0.0
    if start:
        start_conf = 1.0 if start_marked or _ampm_of(end_text) or start.hour >= 13 else 0.6
        if not start_marked and not _ampm_of(end_text) and 1 <= start.hour <= 7:
            start = dtime(start.hour + 12, start.minute)  # "7" on an event flyer almost always means evening
    end, end_marked = _parse_time(end_text, default_ampm=_ampm_of(start_text) or None)
    end_conf = 0.0
    if end:
        end_conf = 1.0 if end_marked or _ampm_of(start_text) or end.hour >= 13 else 0.6
        if start and end <= start and end.hour < 12 and dtime(end.hour + 12, end.minute) > start:
            # "7 PM - 9": the end is in the evening too.
            end = dtime(end.hour + 12, end.minute)
            end_conf = min(end_conf, 0.8)
        if start and end <= start:
            end, end_conf = None, 0.0
    return start, end, start_conf, end_conf


def _key(text):
    return re.sub(r'[^a-z0-9 ]+', ' ', text.lower()).split()


def match_venue(location, venues):
    """Return (venue, room_text, score) for the best campus building match, or (None, location, 0)."""
    if not location:
        return None, '', 0.0
    words = ' '.join(_key(location))
    best = (None, 0.0, '')
    # "Krannert Center" names one building only if a single venue starts with those words.
    prefix_hits = [venue for venue in venues if len(words) >= 6 and ' '.join(_key(venue.name)).startswith(words)]
    if len(prefix_hits) == 1:
        return prefix_hits[0], '', 0.9
    for venue in venues:
        candidates = [venue.name, *(venue.aliases or [])]
        if venue.building_code:
            candidates.append(venue.building_code)
        # "Activities and Recreation Center (ARC)": the short name counts too.
        candidates += re.findall(r'\(([^)]{2,20})\)', venue.name)
        for candidate in candidates:
            key = ' '.join(_key(candidate))
            if not key:
                continue
            if len(key) >= 3 and re.search(rf'\b{re.escape(key)}\b', words):
                score = 1.0
            else:
                score = difflib.SequenceMatcher(None, key, words).ratio()
                # A building name inside a longer string ("Room 2405, Siebel Center")
                window = difflib.SequenceMatcher(None, key, words).find_longest_match(0, len(key), 0, len(words))
                score = max(score, window.size / len(key) if len(key) >= 6 else 0)
            if score > best[1]:
                best = (venue, score, candidate)
    venue, score, candidate = best
    if venue is None or score < 0.75:
        # Last try: the distinctive words of one building's name inside the location
        # ("Outside State Farm Arena" → State Farm Center). Likely, but the host should check.
        location_words = set(words.split())
        core_hits = []
        for place in venues:
            core = [word for word in _key(re.sub(r'\(.*?\)', '', place.name)) if word not in GENERIC_PLACE_WORDS]
            if (len(core) >= 2 or (core and len(core[0]) >= 6)) and set(core) <= location_words:
                core_hits.append(place)
        if len(core_hits) == 1:
            return core_hits[0], location[:255], 0.75
        return None, location[:255], 0.0
    if score < 1.0:
        # A fuzzy match: keep the flyer's wording unless it is just the building's name.
        whole = difflib.SequenceMatcher(None, ' '.join(_key(candidate)), words).ratio()
        return venue, ('' if whole >= 0.75 else location[:255]), round(score, 2)
    # Take out every name of the building the flyer used ("SDRP ... (aka Ikenberry)"), then tidy up.
    room = location
    names = [venue.name, *(venue.aliases or []), *([venue.building_code] if venue.building_code else [])]
    names += re.findall(r'\(([^)]{2,20})\)', venue.name)
    for name in sorted(names, key=len, reverse=True):
        if len(' '.join(_key(name))) >= 3:
            room = re.sub(rf'\b{re.escape(name)}\b', '', room, flags=re.IGNORECASE)
    room = re.sub(r'\(\s*(aka|a\.k\.a\.)?[\s,]*\)', '', room, flags=re.IGNORECASE)
    room = re.sub(r'\s+([,;)])', r'\1', room)
    room = re.sub(r'\s{2,}', ' ', room)
    room = re.sub(r'^[\s,;:@()-]+|[\s,;:@()-]+$', '', room)
    leftover = [word for word in _key(room) if word not in GENERIC_PLACE_WORDS | FILLER_WORDS]
    if not leftover:
        return venue, '', 1.0  # "UIUC Smith Memorial Hall": nothing beyond the building
    if re.search(r'\d', room):
        return venue, room[:255], 1.0  # "Room 1404", "2nd floor"
    # Words like "outside ... west side" read better with the building name kept in.
    return venue, location[:255], 1.0


def match_categories(raw_categories, extra_text, interests):
    """Map the model's topic words (and words in the title) onto Radar's categories."""
    by_name = {interest.name.lower(): interest for interest in interests}
    by_slug = {interest.slug.lower(): interest for interest in interests}
    picked = []

    def add(interest):
        if interest and interest not in picked and len(picked) < MAX_CATEGORIES:
            picked.append(interest)

    for raw in raw_categories:
        word = raw.lower().lstrip('#').strip()
        add(by_name.get(word) or by_slug.get(word))
        for name, hints in CATEGORY_HINTS.items():
            if word in hints or any(_mentions(word, h) for h in hints if len(h) > 3):
                add(by_name.get(name.lower()))
        close = difflib.get_close_matches(word, list(by_name), n=1, cutoff=0.8)
        if close:
            add(by_name[close[0]])
    if not picked:
        lowered = extra_text.lower()
        for name, hints in CATEGORY_HINTS.items():
            if any(_mentions(lowered, h) for h in hints):
                add(by_name.get(name.lower()))
    return picked


def _mentions(text, hint):
    # Whole word, allowing plurals and common endings: "robot" matches "robots" and "robotics".
    return re.search(rf'\b{re.escape(hint)}(s|es|ing|ics)?\b', text) is not None


def _valid_url(text):
    if not text:
        return ''
    candidate = text if re.match(r'^https?://', text, re.IGNORECASE) else f'https://{text}'
    if ' ' in candidate or '.' not in candidate:
        return ''
    try:
        URLValidator(schemes=['http', 'https'])(candidate)
    except ValidationError:
        return ''
    return candidate[:255]


def _is_free(price):
    lowered = price.lower()
    return not price or 'free' in lowered or re.fullmatch(r'\$?\s*0+(\.0+)?', lowered) is not None


def build_form_values(raw, *, today, interests, venues, organizations):
    """Turn the model's raw fields into EventForm initial values.

    Returns (values, confidence, review). `values` is JSON-safe; `confidence` is 0–1 per form field;
    `review` maps form field names to "missing" or "check" for the highlights on the review screen.
    """
    values, confidence = {}, {}

    values['title'] = raw.get('title', '')[:150]
    confidence['title'] = 1.0 if values['title'] else 0.0

    description = raw.get('description', '')
    price = raw.get('price', '')
    url = _valid_url(raw.get('registration_url', ''))
    if url and _is_free(price):
        description = f'{description}\n\nRegister: {url}'.strip()
    values['description'] = description[:5000]
    confidence['description'] = 1.0 if raw.get('description') else 0.0

    day, confidence['date'] = parse_flyer_date(raw.get('date', ''), today)
    values['date'] = day.isoformat() if day else ''
    start, end, confidence['start_time'], confidence['end_time'] = parse_flyer_times(
        raw.get('start_time', ''), raw.get('end_time', '')
    )
    values['start_time'] = start.strftime('%H:%M') if start else ''
    values['end_time'] = end.strftime('%H:%M') if end else ''

    venue, room, score = match_venue(raw.get('location', ''), venues)
    values['venue'] = venue.pk if venue else None
    values['location_text'] = room if venue else raw.get('location', '')[:255]
    confidence['location_text'] = score if venue else (0.6 if values['location_text'] else 0.0)
    if venue and venue.location:
        values['latitude'], values['longitude'] = venue.location.y, venue.location.x

    picked = match_categories(raw.get('categories', []), f"{values['title']} {raw.get('description', '')}", interests)
    values['interests'] = [interest.pk for interest in picked]
    confidence['interests'] = 1.0 if picked and raw.get('categories') else (0.6 if picked else 0.0)

    if _is_free(price):
        values['kind'] = 'rsvp'
        confidence['kind'] = 1.0 if price else 0.6
    else:
        values['kind'] = 'paid'
        values['price_text'] = price[:60]
        values['external_url'] = url
        confidence['kind'] = 1.0
        confidence['price_text'] = 1.0
        confidence['external_url'] = 1.0 if url else 0.0

    organizer = raw.get('organizer', '')
    values['host'] = 'me'
    # Only worth a second look when the flyer names an organizer and the host runs organizations.
    confidence['host'] = 0.6 if organizer and organizations else 1.0
    for org in organizations:
        name = org.name.lower()
        if organizer and (name in organizer.lower() or difflib.SequenceMatcher(None, name, organizer.lower()).ratio() >= 0.85):
            values['host'] = org.slug
            confidence['host'] = 1.0
            break

    required = ('title', 'description', 'date', 'start_time', 'end_time', 'location_text', 'interests')
    review = {}
    for field, score in confidence.items():
        if score == 0.0 and (field in required or field == 'external_url'):
            review[field] = 'missing'
        elif score < 0.8:
            review[field] = 'check'
    return values, confidence, review
