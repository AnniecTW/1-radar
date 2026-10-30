from django.contrib.gis.db import models
from django.contrib.postgres.fields import ArrayField


class Venue(models.Model):
    name = models.CharField(max_length=150)
    building_code = models.CharField(max_length=20, null=True, blank=True)
    # Alternate names used to match flyer locations.
    aliases = ArrayField(models.CharField(max_length=150), default=list, blank=True)
    address = models.CharField(max_length=255, blank=True)
    # GiST-indexed by default.
    location = models.PointField(geography=True, srid=4326)
    is_campus = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
