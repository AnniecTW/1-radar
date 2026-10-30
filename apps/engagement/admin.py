from django.contrib import admin

from .models import EventLike, EventSave, EventView


@admin.register(EventLike, EventSave)
class EventReactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'event', 'created_at')


@admin.register(EventView)
class EventViewAdmin(admin.ModelAdmin):
    list_display = ('event', 'user', 'source', 'created_at')
    list_filter = ('source',)
