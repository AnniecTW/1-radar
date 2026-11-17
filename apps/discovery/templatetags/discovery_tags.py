"""Category icons/colours and short date labels for event cards: {% load discovery_tags %}."""
from datetime import datetime

from django import template
from django.utils import timezone

from ..constants import (
    CATEGORY_HERO_PHOTOS,
    CATEGORY_STYLES,
    DEFAULT_CATEGORY_STYLE,
    DEFAULT_HERO_PHOTO,
    UNSPLASH_PHOTO_URL,
)

register = template.Library()


@register.filter
def category_icon(slug: str) -> str:
    return CATEGORY_STYLES.get(slug, DEFAULT_CATEGORY_STYLE)[0]


@register.filter
def category_tone(slug: str) -> str:
    return CATEGORY_STYLES.get(slug, DEFAULT_CATEGORY_STYLE)[1]


@register.filter
def relative_day(start_at: datetime) -> str:
    """'Today', 'Tomorrow', 'This Fri' within the week, otherwise 'Sat, Nov 8'. Uses the active (campus) timezone."""
    if not start_at:
        return ''
    local_start = timezone.localtime(start_at).date()
    today = timezone.localtime(timezone.now()).date()
    days_away = (local_start - today).days
    if days_away <= 0:
        return 'Today'
    if days_away == 1:
        return 'Tomorrow'
    if days_away < 7 and local_start.weekday() > today.weekday():
        return f'This {local_start.strftime("%a")}'
    return f'{local_start.strftime("%a, %b")} {local_start.day}'


@register.filter
def hero_image(event) -> str:
    """The event's own cover, or a free stock photo matching its first known category."""
    if event.cover_image:
        return event.cover_image
    photo_id = next(
        (CATEGORY_HERO_PHOTOS[interest.slug] for interest in event.interests.all() if interest.slug in CATEGORY_HERO_PHOTOS),
        DEFAULT_HERO_PHOTO,
    )
    return UNSPLASH_PHOTO_URL.format(photo_id=photo_id)
