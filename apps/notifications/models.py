from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Type(models.TextChoices):
        RSVP_CONFIRMED = 'rsvp_confirmed', 'RSVP confirmed'
        WAITLIST_JOINED = 'waitlist_joined'
        WAITLIST_PROMOTED = 'waitlist_promoted'
        WAITLIST_HEADS_UP = 'waitlist_heads_up'
        WAITLIST_CLOSED = 'waitlist_closed'
        EVENT_UPDATED = 'event_updated'
        EVENT_CANCELLED = 'event_cancelled'
        REMINDER = 'reminder'
        ORG_INVITE = 'org_invite'
        FOLLOWED_ORG_NEW_EVENT = 'followed_org_new_event'

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    type = models.CharField(max_length=40, choices=Type.choices)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    # Set for follow notifications.
    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='+'
    )
    # Template data.
    payload = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.type} for {self.user}'
