from django.contrib import admin

from .models import RecommendationImpression


@admin.register(RecommendationImpression)
class RecommendationImpressionAdmin(admin.ModelAdmin):
    list_display = ('user', 'event', 'rank', 'score', 'algorithm_version', 'clicked', 'dismissed', 'shown_at')
    list_filter = ('algorithm_version', 'clicked', 'dismissed')
