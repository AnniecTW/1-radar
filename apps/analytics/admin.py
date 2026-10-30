from django.contrib import admin

from .models import EventDailyStats


@admin.register(EventDailyStats)
class EventDailyStatsAdmin(admin.ModelAdmin):
    list_display = ('event', 'date', 'views', 'likes', 'saves', 'rsvps_going', 'checkins')
    date_hierarchy = 'date'
