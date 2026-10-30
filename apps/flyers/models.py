import uuid

from django.conf import settings
from django.db import models


class FlyerUpload(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending'
        PROCESSING = 'processing'
        SUCCEEDED = 'succeeded'
        FAILED = 'failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='flyer_uploads')
    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    image = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    extracted_data = models.JSONField(null=True, blank=True)
    # Per-field confidence, 0–1.
    confidence = models.JSONField(null=True, blank=True)
    # Raw model output, kept for debugging.
    raw_response = models.JSONField(null=True, blank=True)
    model_name = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    # Set when the draft is published.
    event = models.ForeignKey('events.Event', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    # For the extraction-acceptance metric.
    fields_edited_count = models.PositiveSmallIntegerField(default=0)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Flyer {self.id} ({self.status})'
