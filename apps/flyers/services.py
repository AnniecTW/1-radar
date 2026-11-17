"""Upload a flyer, read it, and connect the result to the event the host publishes."""
import logging
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

from .extraction import (
    ExtractionError,
    FlyerImageError,
    build_form_values,
    call_vision_model,
    model_id,
    parse_answer,
    prepare_image,
)
from .models import FlyerUpload

logger = logging.getLogger(__name__)
ALLOWED_CONTENT_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
# Form fields compared at publish time for the "drafts published with ≤ 2 fields edited" metric.
TRACKED_FIELDS = (
    'host', 'title', 'description', 'date', 'start_time', 'end_time', 'venue', 'location_text',
    'interests', 'kind', 'price_text', 'external_url',
)


class FlyerUploadError(Exception):
    """A problem the host can fix, shown on the upload page."""


def daily_limit():
    return getattr(settings, 'FLYER_DAILY_LIMIT', 10)


def uploads_left_today(user):
    since = timezone.now() - timedelta(hours=24)
    used = FlyerUpload.objects.filter(uploaded_by=user, created_at__gte=since).count()
    return max(0, daily_limit() - used)


def _check_file(upload):
    max_bytes = getattr(settings, 'FLYER_MAX_BYTES', 10 * 1024 * 1024)
    if upload.size > max_bytes:
        raise FlyerUploadError(f'Choose an image under {max_bytes // (1024 * 1024)} MB.')
    content_type = (getattr(upload, 'content_type', '') or '').split(';')[0].strip().lower()
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise FlyerUploadError('Upload a JPG, PNG or WebP photo of the flyer.')


def _organizations_for(user):
    from apps.events.selectors import list_host_organizations

    return list(list_host_organizations(user))


def process_flyer(*, user, upload, today=None):
    """Store the flyer, read it with the vision model, and return the FlyerUpload.

    Raises FlyerUploadError for problems the host can fix (file type, size, daily limit).
    A failed model call is not an error here: the FlyerUpload is marked failed and the host
    continues with the manual form, with the flyer attached as the cover image.
    """
    from apps.discovery.selectors import get_campus_timezone
    from apps.interests.models import Interest
    from apps.venues.models import Venue

    if not getattr(user, 'is_campus_verified', False):
        raise PermissionDenied('A verified campus member is required to host events.')
    if uploads_left_today(user) <= 0:
        raise FlyerUploadError(
            f"You've read {daily_limit()} flyers in the last 24 hours, the daily limit. "
            'Create this event with the form instead.'
        )
    _check_file(upload)
    try:
        jpeg = prepare_image(upload)
    except FlyerImageError as error:
        raise FlyerUploadError(str(error)) from None

    try:
        name = default_storage.save(f'flyers/{uuid.uuid4().hex}.jpg', ContentFile(jpeg))
        image_url = default_storage.url(name)
    except Exception:
        logger.exception('Flyer image upload failed')
        raise FlyerUploadError("The image couldn't be saved right now. Try again, or use the form.") from None

    flyer = FlyerUpload.objects.create(
        uploaded_by=user, image=image_url, status=FlyerUpload.Status.PROCESSING, model_name=model_id(),
    )
    started = time.monotonic()
    answer = None
    try:
        answer = call_vision_model(jpeg)
        raw = parse_answer(answer)
        tz = get_campus_timezone()
        values, confidence, review = build_form_values(
            raw,
            today=today or timezone.localtime(timezone.now(), tz).date(),
            interests=list(Interest.objects.filter(is_active=True)),
            venues=list(Venue.objects.filter(is_campus=True)),
            organizations=_organizations_for(user),
        )
    except ExtractionError as error:
        flyer.status = FlyerUpload.Status.FAILED
        flyer.error_message = str(error)
    else:
        flyer.status = FlyerUpload.Status.SUCCEEDED
        flyer.extracted_data = {'raw': raw, 'form': values, 'review': review}
        flyer.confidence = confidence
    flyer.raw_response = {'answer': answer} if answer is not None else None
    flyer.latency_ms = round((time.monotonic() - started) * 1000)
    flyer.processed_at = timezone.now()
    flyer.save()
    logger.info('Flyer %s %s in %s ms', flyer.pk, flyer.status, flyer.latency_ms)
    return flyer


def get_flyer_for_review(user, flyer_id):
    """The host's own flyer that hasn't become an event yet, or None."""
    try:
        flyer_uuid = uuid.UUID(str(flyer_id))
    except (TypeError, ValueError):
        return None
    return FlyerUpload.objects.filter(pk=flyer_uuid, uploaded_by=user, event__isnull=True).first()


def form_initial(flyer, host_choices):
    """EventForm initial values from a successful extraction."""
    from datetime import date, time as dtime

    if flyer.status != FlyerUpload.Status.SUCCEEDED or not flyer.extracted_data:
        return {}
    values = dict(flyer.extracted_data.get('form') or {})
    if values.get('host') not in {value for value, _ in host_choices}:
        values['host'] = 'me'
    if values.get('date'):
        values['date'] = date.fromisoformat(values['date'])
    for key in ('start_time', 'end_time'):
        if values.get(key):
            values[key] = dtime.fromisoformat(values[key])
    return {key: value for key, value in values.items() if value not in (None, '', [])}


def _comparable(key, value):
    if key == 'interests':
        return sorted(getattr(item, 'pk', item) for item in (value or []))
    if key == 'venue':
        return getattr(value, 'pk', value)
    if hasattr(value, 'isoformat'):
        return value.isoformat()[:5] if key.endswith('_time') else value.isoformat()
    return (value or '').strip() if isinstance(value, str) or value is None else value


def link_flyer_to_event(*, flyer, event, cleaned_data):
    """Mark the event as created from a flyer and record how many fields the host changed."""
    from apps.events.models import Event

    extracted = (flyer.extracted_data or {}).get('form') or {}
    edited = 0
    if flyer.status == FlyerUpload.Status.SUCCEEDED:
        for key in TRACKED_FIELDS:
            before = _comparable(key, extracted.get(key, 'me' if key == 'host' else None))
            after = _comparable(key, cleaned_data.get(key))
            if key == 'kind' and before is None:
                before = 'rsvp'
            if (before or None) != (after or None):
                edited += 1
    Event.objects.filter(pk=event.pk).update(source=Event.Source.FLYER_AI)
    event.source = Event.Source.FLYER_AI
    flyer.event = event
    flyer.organization = event.organization
    flyer.fields_edited_count = edited
    flyer.save(update_fields=['event', 'organization', 'fields_edited_count', 'updated_at'])
    return flyer
