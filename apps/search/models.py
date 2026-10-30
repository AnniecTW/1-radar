from django.conf import settings
from django.db import models


class SearchQueryLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    raw_query = models.CharField(max_length=300)
    # The LLM's interpretation of the query.
    parsed_filters = models.JSONField(null=True, blank=True)
    used_llm = models.BooleanField(default=False)
    result_count = models.PositiveIntegerField(default=0)
    clicked_event = models.ForeignKey(
        'events.Event', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.raw_query
