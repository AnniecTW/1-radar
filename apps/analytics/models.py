from django.db import models


class EventDailyStats(models.Model):
    id = models.BigAutoField(primary_key=True)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='daily_stats')
    date = models.DateField()
    views = models.PositiveIntegerField(default=0)
    unique_views = models.PositiveIntegerField(default=0)
    likes = models.PositiveIntegerField(default=0)
    saves = models.PositiveIntegerField(default=0)
    interested = models.PositiveIntegerField(default=0)
    outbound_clicks = models.PositiveIntegerField(default=0)
    rsvps_going = models.PositiveIntegerField(default=0)
    rsvps_waitlisted = models.PositiveIntegerField(default=0)
    rsvps_cancelled = models.PositiveIntegerField(default=0)
    checkins = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'event daily stats'
        constraints = [models.UniqueConstraint(fields=['event', 'date'], name='unique_event_daily_stats')]

    def __str__(self):
        return f'{self.event} on {self.date}'
