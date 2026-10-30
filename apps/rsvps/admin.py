from django.contrib import admin

from .models import RSVP, Ticket


@admin.register(RSVP)
class RSVPAdmin(admin.ModelAdmin):
    list_display = ('user', 'event', 'status', 'waitlist_position', 'source', 'created_at')
    list_filter = ('status', 'source')


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('rsvp', 'status', 'issued_at', 'used_at')
    list_filter = ('status',)
    exclude = ('code',)
