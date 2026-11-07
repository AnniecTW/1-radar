import uuid

from django.conf import settings
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db.models import F, Q
from pgvector.django import HnswIndex, VectorField


class Event(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft'
        PUBLISHED = 'published'
        CANCELLED = 'cancelled'
        COMPLETED = 'completed'

    class Visibility(models.TextChoices):
        PUBLIC = 'public'
        CAMPUS_ONLY = 'campus_only'
        UNLISTED = 'unlisted'

    class Source(models.TextChoices):
        MANUAL = 'manual'
        FLYER_AI = 'flyer_ai', 'Flyer AI'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=170, unique=True, null=True, blank=True)
    title = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    host_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='hosted_events')
    # Null for events hosted by an individual.
    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.SET_NULL, null=True, blank=True, related_name='events'
    )
    start_at = models.DateTimeField(db_index=True, null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    venue = models.ForeignKey('venues.Venue', on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    # Room / free-text location.
    location_text = models.CharField(max_length=255, blank=True)
    # Required for the map; nullable so drafts can be saved first. GiST-indexed by default.
    location = models.PointField(geography=True, srid=4326, null=True, blank=True)
    cover_image = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.PUBLIC)
    # Null = unlimited.
    capacity = models.PositiveIntegerField(null=True, blank=True)
    rsvp_required = models.BooleanField(default=True)
    waitlist_enabled = models.BooleanField(default=True)
    is_free = models.BooleanField(default=True)
    # Display only; no payments in the MVP.
    price_text = models.CharField(max_length=60, blank=True)
    external_url = models.CharField(max_length=255, null=True, blank=True)
    contact_info = models.CharField(max_length=254, null=True, blank=True)
    cancel_reason = models.TextField(null=True, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    # Recomputed by a background job.
    popularity_score = models.FloatField(default=0, db_index=True)
    # Cloudflare BGE small embeddings.
    embedding = VectorField(dimensions=384, null=True, blank=True)
    search_vector = SearchVectorField(null=True, blank=True)
    # For self check-in (P1).
    checkin_qr_secret = models.CharField(max_length=64, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    interests = models.ManyToManyField('interests.Interest', through='EventInterest', related_name='events')

    class Meta:
        indexes = [
            models.Index(fields=['status', 'start_at']),
            HnswIndex(
                name='event_embedding_hnsw',
                fields=['embedding'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops'],
            ),
            GinIndex(fields=['search_vector'], name='event_search_vector_gin'),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(end_at__gt=F('start_at')), name='event_end_after_start'),
            models.CheckConstraint(
                condition=(
                    ~Q(status='published')
                    | (
                        ~Q(title='')
                        & Q(slug__isnull=False)
                        & ~Q(slug='')
                        & Q(start_at__isnull=False)
                        & Q(end_at__isnull=False)
                        & (Q(venue__isnull=False) | ~Q(location_text=''))
                    )
                ),
                name='published_event_has_required_fields',
            ),
        ]

    def clean(self):
        super().clean()
        if self.status != self.Status.PUBLISHED:
            return

        errors = {}
        if not self.title.strip():
            errors['title'] = 'A title is required to publish an event.'
        if not self.slug:
            errors['slug'] = 'A slug is generated when the event is published.'
        if not self.start_at:
            errors['start_at'] = 'A start time is required to publish an event.'
        if not self.end_at:
            errors['end_at'] = 'An end time is required to publish an event.'
        elif self.start_at and self.end_at <= self.start_at:
            errors['end_at'] = 'The end time must be later than the start time.'
        if not self.venue_id and not self.location_text.strip():
            errors['location_text'] = 'Add a venue or location description before publishing.'
        if not self.is_free:
            if not self.price_text.strip():
                errors['price_text'] = 'A price is required for paid events.'
            if not (self.external_url or self.contact_info or (self.organization and self.organization.contact_email)):
                errors['external_url'] = 'Add a ticket link or contact for paid events.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title or f'Draft {self.pk}'


class EventInterest(models.Model):
    id = models.BigAutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    interest = models.ForeignKey('interests.Interest', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['event', 'interest'], name='unique_event_interest')]

    def __str__(self):
        return f'{self.event} → {self.interest}'


class EventReport(models.Model):
    class Reason(models.TextChoices):
        SPAM = 'spam'
        INAPPROPRIATE = 'inappropriate'
        INACCURATE = 'inaccurate'
        OTHER = 'other'

    class Status(models.TextChoices):
        OPEN = 'open'
        ACTIONED = 'actioned'
        DISMISSED = 'dismissed'

    id = models.BigAutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='reports')
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    reason = models.CharField(max_length=30, choices=Reason.choices)
    details = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.reason} report on {self.event}'


class EventCheckInStaff(models.Model):
    id = models.BigAutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='checkin_staff_assignments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='checkin_assignments')
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='checkin_staff_assignments_made'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['event', 'user'], name='unique_event_checkin_staff')]

    def __str__(self):
        return f'{self.user} assigned to check in {self.event}'
