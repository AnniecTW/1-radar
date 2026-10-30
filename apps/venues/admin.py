from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import Venue


@admin.register(Venue)
class VenueAdmin(GISModelAdmin):
    list_display = ('name', 'building_code', 'address', 'is_campus')
    search_fields = ('name', 'building_code')
