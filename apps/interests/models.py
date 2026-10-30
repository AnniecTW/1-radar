from django.conf import settings
from django.db import models
from pgvector.django import VectorField


class Interest(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(unique=True)
    group = models.CharField(max_length=40, blank=True)
    icon = models.CharField(max_length=40, blank=True)
    # Dimension depends on the embedding model.
    embedding = VectorField(dimensions=1536, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class UserInterest(models.Model):
    class Source(models.TextChoices):
        ONBOARDING = 'onboarding'
        SETTINGS = 'settings'
        INFERRED = 'inferred'

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='interests')
    interest = models.ForeignKey(Interest, on_delete=models.CASCADE)
    weight = models.FloatField(default=1.0)
    source = models.CharField(max_length=20, choices=Source.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'interest'], name='unique_user_interest')]

    def __str__(self):
        return f'{self.user} → {self.interest}'
