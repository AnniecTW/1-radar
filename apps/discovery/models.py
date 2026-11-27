from django.conf import settings
from django.db import models


class RecommendationImpression(models.Model):
    class Reason(models.TextChoices):
        SIMILAR = 'similar', 'Similar to an event you engaged with'
        INTEREST = 'interest', 'Matches an interest you chose'
        FOLLOWS = 'follows', 'From an organization you follow'
        NEARBY = 'nearby', 'A short walk away'
        NONE = '', 'No reason shown'

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
    # When "Not interested" was tapped. Nullable, so code that doesn't know the column still inserts rows;
    # dismissals from before it was added have none.
    dismissed_at = models.DateTimeField(null=True, blank=True)
    shown_at = models.DateTimeField(auto_now_add=True)

    # The parts the score is built from, each 0 to 1 before weighting, for the staff dashboard's "which signals
    # drive clicks". Empty for interest-tag fallback rows (not scored) and rows from before these existed;
    # proximity is empty when the user hadn't shared a location. Every column below is nullable or has a
    # database default, so code that doesn't know them still inserts rows.
    part_similarity = models.FloatField(null=True, blank=True)
    part_follows = models.FloatField(null=True, blank=True)
    part_popularity = models.FloatField(null=True, blank=True)
    part_proximity = models.FloatField(null=True, blank=True)
    part_urgency = models.FloatField(null=True, blank=True)
    penalty = models.FloatField(null=True, blank=True)  # "Not interested" penalty subtracted from the score.
    reason = models.CharField(max_length=20, choices=Reason.choices, blank=True, default='', db_default='')
    # How long ranking the whole row took, on the rank-1 row only (one row of cards is one measurement).
    load_ms = models.PositiveIntegerField(null=True, blank=True)
    # Logged by replay_recommendation_traffic for a made-up user, not by a real person.
    is_simulated = models.BooleanField(default=False, db_default=False)

    class Meta:
        indexes = [models.Index(fields=['shown_at'], name='rec_impression_shown_idx')]

    def __str__(self):
        return f'#{self.rank} {self.event} for {self.user}'


class RecommendationEvaluationRun(models.Model):
    """One `manage.py evaluate_recommendations` run: scores for made-up students over made-up events."""
    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    algorithm_version = models.CharField(max_length=20)
    embedding_model = models.CharField(max_length=100)
    persona_count = models.PositiveIntegerField()
    event_count = models.PositiveIntegerField()
    summary = models.JSONField()  # {method: {metric: value}}
    per_persona = models.JSONField()
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Recommendation evaluation {self.created_at:%Y-%m-%d %H:%M}'
