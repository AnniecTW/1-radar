from django.contrib import admin

from .models import RecommendationEvaluationRun, RecommendationImpression


@admin.register(RecommendationImpression)
class RecommendationImpressionAdmin(admin.ModelAdmin):
    list_display = ('user', 'event', 'rank', 'score', 'algorithm_version', 'reason', 'clicked', 'dismissed',
                    'dismissed_at', 'shown_at', 'is_simulated')
    list_filter = ('algorithm_version', 'reason', 'clicked', 'dismissed', 'is_simulated')


@admin.register(RecommendationEvaluationRun)
class RecommendationEvaluationRunAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'algorithm_version', 'persona_count', 'event_count', 'note')
    readonly_fields = ('created_at',)
