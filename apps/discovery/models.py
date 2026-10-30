from django.conf import settings
from django.db import models


class RecommendationImpression(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='+')
    # Position in the feed.
    rank = models.PositiveSmallIntegerField()
    score = models.FloatField()
    # For A/B comparisons.
    algorithm_version = models.CharField(max_length=20)
    clicked = models.BooleanField(default=False)
    # "Not interested".
    dismissed = models.BooleanField(default=False)
    shown_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'#{self.rank} {self.event} for {self.user}'
