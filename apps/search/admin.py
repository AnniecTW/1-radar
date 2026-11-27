from django.contrib import admin

from .models import SearchEvaluationRun, SearchQueryLog


@admin.register(SearchQueryLog)
class SearchQueryLogAdmin(admin.ModelAdmin):
    # Rows are anonymous on purpose (apps/search/services.py), so there is no user column.
    list_display = ('raw_query', 'outcome', 'result_count', 'clicked_event', 'latency_ms', 'error_code',
                    'is_simulated', 'created_at')
    list_filter = ('outcome', 'is_simulated', 'error_code')
    search_fields = ('raw_query',)
    ordering = ('-created_at',)
    exclude = ('user',)


@admin.register(SearchEvaluationRun)
class SearchEvaluationRunAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'embedding_model', 'min_similarity', 'query_count', 'event_count', 'note')
    readonly_fields = ('created_at',)
