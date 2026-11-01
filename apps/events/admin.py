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
    date_hierarchy = 'start_at'
    exclude = ('embedding', 'search_vector')
    inlines = [EventInterestInline]
    readonly_fields = tuple(field.name for field in Event._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='Unpublish selected events')
    def unpublish_events(self, request, queryset):
        queryset.filter(status=Event.Status.PUBLISHED).update(status=Event.Status.DRAFT)

    actions = [unpublish_events]

    def has_change_permission(self, request, obj=None):
        return request.method == 'POST' or super().has_change_permission(request, obj)


@admin.register(EventReport)
class EventReportAdmin(admin.ModelAdmin):
    list_display = ('event', 'reason', 'status', 'reported_by', 'created_at')
    list_filter = ('status', 'reason')
