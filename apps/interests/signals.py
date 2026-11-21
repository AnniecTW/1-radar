import logging
import sys

from django.conf import settings
from django.db.models.signals import post_migrate, post_save, pre_save
from django.dispatch import receiver

from .models import Interest

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Interest)
def detect_interest_text_change(sender, instance, raw=False, **kwargs):
    if raw or not settings.INTEREST_AUTO_EMBED:
        return
    from .embeddings import interest_text

    old = Interest.objects.filter(pk=instance.pk).first() if instance.pk else None
    instance._embedding_text_changed = old is None or interest_text(old) != interest_text(instance)


@receiver(post_save, sender=Interest)
def embed_interest_after_save(sender, instance, raw=False, **kwargs):
    """New or reworded interests (for example, added by a platform admin) get a fresh vector."""
    if raw or not getattr(instance, '_embedding_text_changed', False):
        return
    from apps.events.semantic_search import EmbeddingError

    from .embeddings import save_interest_embedding

    try:
        save_interest_embedding(instance, force=True)
    except EmbeddingError:
        logger.warning('Interest embedding deferred; run embed_interests (interest_id=%s)', instance.pk)


def embed_interests_after_migrate(sender, plan=None, verbosity=1, **kwargs):
    """Seeded interests are created inside migrations, where model signals don't run, so embed any that are
    still missing a vector once `migrate` has applied an interests migration."""
    if not settings.INTEREST_AUTO_EMBED:
        return  # Off in test runs: test databases are rebuilt every run, so never call Cloudflare while creating one.
    if not plan or not any(migration.app_label == 'interests' and not backwards for migration, backwards in plan):
        return
    from .embeddings import embed_missing_interests

    report = (lambda line: sys.stdout.write(f'  {line}\n')) if verbosity > 1 else None
    embedded, finished = embed_missing_interests(report)
    if verbosity:
        if finished:
            sys.stdout.write(f'Interest embeddings: {embedded} added.\n')
        else:
            sys.stdout.write(
                f'Interest embeddings: {embedded} added, then Cloudflare was unavailable. '
                'Run `python manage.py embed_interests` to finish.\n'
            )
