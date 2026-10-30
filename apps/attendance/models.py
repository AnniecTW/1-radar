from django.conf import settings
from django.db import models


class CheckIn(models.Model):
    class Method(models.TextChoices):
        HOST_SCAN = 'host_scan'
        MANUAL = 'manual'
        SELF_SCAN = 'self_scan'

    id = models.BigAutoField(primary_key=True)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='checkins')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='checkins')
    # Null for walk-ins.
    ticket = models.ForeignKey('rsvps.Ticket', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    method = models.CharField(max_length=20, choices=Method.choices)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    checked_in_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'check-in'
        constraints = [models.UniqueConstraint(fields=['event', 'user'], name='unique_event_checkin')]

    def __str__(self):
        return f'{self.user} @ {self.event}'
