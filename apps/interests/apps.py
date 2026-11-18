from django.apps import AppConfig
from django.db.models.signals import post_migrate


class InterestsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.interests'

    def ready(self):
        from . import signals

        post_migrate.connect(signals.embed_interests_after_migrate, sender=self)
