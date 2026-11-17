import uuid

from django.conf import settings
from django.db import models


class TrafficSource(models.TextChoices):
    LANDING = 'landing'
    FEED = 'feed'
    FOLLOWING = 'following'
    MAP = 'map'
    SEARCH = 'search'
    RECOMMENDATION = 'recommendation'
    ORG_PAGE = 'org_page'
    DIRECT = 'direct'


class RSVP(models.Model):
    class Status(models.TextChoices):
        GOING = 'going'
        WAITLISTED = 'waitlisted'
        INTERESTED = 'interested'
        CANCELLED = 'cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='rsvps')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='rsvps')
    status = models.CharField(max_length=20, choices=Status.choices)
    waitlist_position = models.PositiveIntegerField(null=True, blank=True)
    waitlisted_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=20, choices=TrafficSource.choices, default=TrafficSource.DIRECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'RSVP'
        constraints = [models.UniqueConstraint(fields=['event', 'user'], name='unique_event_rsvp')]

    def __str__(self):
        return f'{self.user} → {self.event} ({self.status})'


class Ticket(models.Model):
    class Status(models.TextChoices):
        VALID = 'valid'
        USED = 'used'
        VOID = 'void'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rsvp = models.OneToOneField(RSVP, on_delete=models.CASCADE, related_name='ticket')
    # Random URL-safe token; the QR encodes a signed ticket_id:code payload.
    code = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.VALID)
    issued_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'Ticket for {self.rsvp}'
