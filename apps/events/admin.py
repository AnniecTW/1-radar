from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import Event, EventInterest, EventReport


class EventInterestInline(admin.TabularInline):
    model = EventInterest
    extra = 0


@admin.register(Event)
class EventAdmin(GISModelAdmin):
    list_display = ('title', 'organization', 'start_at', 'status', 'visibility', 'capacity', 'popularity_score')
    list_filter = ('status', 'visibility', 'source', 'is_free')
    search_fields = ('title', 'description', 'location_text')
    prepopulated_fields = {'slug': ('title',)}
    date_hierarchy = 'start_at'
    exclude = ('embedding', 'search_vector')
    inlines = [EventInterestInline]


@admin.register(EventReport)
class EventReportAdmin(admin.ModelAdmin):
    list_display = ('event', 'reason', 'status', 'reported_by', 'created_at')
    list_filter = ('status', 'reason')
