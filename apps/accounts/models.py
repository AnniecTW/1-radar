import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.gis.db import models


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(max_length=254, unique=True)
    is_email_verified = models.BooleanField(default=False)
    # True when a verified email matches an active CampusDomain.
    is_campus_verified = models.BooleanField(default=False)
    # Separate campus email for users whose primary email is personal.
    campus_email = models.EmailField(max_length=254, unique=True, null=True, blank=True)
    onboarding_completed = models.BooleanField(default=False)
    last_active_at = models.DateTimeField(null=True, blank=True)

    REQUIRED_FIELDS = ['email']

    def __str__(self):
        return self.email


class CampusDomain(models.Model):
    domain = models.CharField(max_length=100, unique=True)
    campus_name = models.CharField(max_length=150)
    # Default map center.
    center_point = models.PointField(geography=True, srid=4326)
    timezone = models.CharField(max_length=50, default='America/Chicago')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.domain


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True, related_name='profile'
    )
    display_name = models.CharField(max_length=80, blank=True)
    avatar = models.CharField(max_length=255, blank=True)
    bio = models.TextField(max_length=500, blank=True)
    major = models.CharField(max_length=120, null=True, blank=True)
    graduation_year = models.PositiveSmallIntegerField(null=True, blank=True)
    notification_prefs = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.display_name or str(self.user)


class SignInPrompt(models.Model):
    class Action(models.TextChoices):
        RSVP = 'rsvp', 'RSVP'
        LIKE = 'like'
        SAVE = 'save'
        FOLLOW = 'follow'

    class TargetType(models.TextChoices):
        EVENT = 'event'
        ORGANIZATION = 'organization'

    class Outcome(models.TextChoices):
        SHOWN = 'shown'
        DISMISSED = 'dismissed'
        SIGNED_IN = 'signed_in'
        SIGNED_UP = 'signed_up'

    id = models.BigAutoField(primary_key=True)
    session_key = models.CharField(max_length=40, db_index=True)
    action = models.CharField(max_length=20, choices=Action.choices)
    target_type = models.CharField(max_length=20, choices=TargetType.choices)
    target_id = models.UUIDField()
    # Page the prompt opened on; the user is returned here after signing in.
    page_url = models.CharField(max_length=500)
    outcome = models.CharField(max_length=20, choices=Outcome.choices, default=Outcome.SHOWN)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.action} {self.target_type} ({self.outcome})'
