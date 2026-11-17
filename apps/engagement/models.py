from django.conf import settings
from django.db import models

from apps.rsvps.models import TrafficSource


class EventLike(models.Model):
    id = models.BigAutoField(primary_key=True)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['event', 'user'], name='unique_event_like')]

    def __str__(self):
        return f'{self.user} likes {self.event}'


class EventSave(models.Model):
    id = models.BigAutoField(primary_key=True)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='saves')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saves')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['event', 'user'], name='unique_event_save')]

    def __str__(self):
        return f'{self.user} saved {self.event}'


class EventView(models.Model):
    id = models.BigAutoField(primary_key=True)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='views')
    # Null for guests; session_key de-duplicates their views.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    session_key = models.CharField(max_length=40, blank=True)
    source = models.CharField(max_length=20, choices=TrafficSource.choices, default=TrafficSource.DIRECT)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f'View of {self.event}'


class EventOutboundClick(models.Model):
    class Kind(models.TextChoices):
        TICKETS_LINK = 'tickets_link'
        CONTACT = 'contact'

    id = models.BigAutoField(primary_key=True)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='outbound_clicks')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    session_key = models.CharField(max_length=40, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f'{self.kind} click for {self.event}'
