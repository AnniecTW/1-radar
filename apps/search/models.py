from django.conf import settings
from django.db import models


class SearchQueryLog(models.Model):
    """One search from the home page search bar (apps/search/services.py)."""

    class Outcome(models.TextChoices):
        AI_RANKED = 'ai_ranked', 'AI ranked'
        AI_NO_MATCH = 'ai_no_match', 'AI: no close match'
        FALLBACK = 'fallback', 'AI fell back to keywords'
        KEYWORD = 'keyword', 'Keyword search'

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    raw_query = models.CharField(max_length=300)
    # The search mode and category, and the shown results with their AI similarity.
    parsed_filters = models.JSONField(null=True, blank=True)
    used_llm = models.BooleanField(default=False)
    result_count = models.PositiveIntegerField(default=0)
    clicked_event = models.ForeignKey(
        'events.Event', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    # Blank on rows logged before outcomes were recorded.
    outcome = models.CharField(max_length=20, choices=Outcome.choices, blank=True)
    # The Cloudflare embedding call alone, including a failed one. Null for keyword searches.
    embedding_ms = models.PositiveIntegerField(null=True, blank=True)
    # Why Cloudflare failed, such as timeout or rate_limited (EmbeddingError.code).
    error_code = models.CharField(max_length=30, blank=True)
    # How many events AI search scored before the similarity cutoff.
    candidate_count = models.PositiveIntegerField(null=True, blank=True)
    # The closest event's similarity, even when it was below the cutoff and not shown.
    top_similarity = models.FloatField(null=True, blank=True)
    # Made by replay_search_traffic, not by a person.
    is_simulated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['created_at'], name='search_log_created_idx')]

    def __str__(self):
        return self.raw_query


class SearchEvaluationRun(models.Model):
    """One run of `evaluate_search`: AI and keyword search scored against labelled queries."""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    embedding_model = models.CharField(max_length=100)
    min_similarity = models.FloatField()
    query_count = models.PositiveIntegerField()
    event_count = models.PositiveIntegerField()
    # {'ai': {'precision': ..., 'recall': ..., ...}, 'keyword': {...}}
    summary = models.JSONField()
    # One entry per labelled query: what each mode returned and how it scored.
    per_query = models.JSONField()
    # AI precision and recall at other similarity cutoffs: [{'cutoff': 0.5, 'precision': ..., ...}]
    cutoff_sweep = models.JSONField()
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Search evaluation {self.created_at:%Y-%m-%d %H:%M}'
