from django.contrib import admin

from .models import SearchQueryLog


@admin.register(SearchQueryLog)
class SearchQueryLogAdmin(admin.ModelAdmin):
    list_display = ('raw_query', 'user', 'used_llm', 'result_count', 'latency_ms', 'created_at')
    list_filter = ('used_llm',)
    search_fields = ('raw_query',)
