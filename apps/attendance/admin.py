from django.contrib import admin

from .models import CheckIn


@admin.register(CheckIn)
class CheckInAdmin(admin.ModelAdmin):
    list_display = ('user', 'event', 'method', 'checked_in_at')
    list_filter = ('method',)
