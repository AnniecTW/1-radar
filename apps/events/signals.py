import logging
from django.db.models.signals import post_save, pre_save, m2m_changed
from django.dispatch import receiver
from .models import Event

logger = logging.getLogger(__name__)

@receiver(pre_save, sender=Event)
def detect_searchable_event_change(sender, instance, raw=False, **kwargs):
    if raw: return
    if not instance.pk:
        instance._semantic_text_changed = True
        return
    old = Event.objects.filter(pk=instance.pk).first()
    if old is None:
        instance._semantic_text_changed = True
        return
    from .semantic_search import event_text
    instance._semantic_text_changed = event_text(old) != event_text(instance)

def _refresh(event_id, force=False):
    from .semantic_search import EmbeddingError, save_event_embedding
    event = Event.objects.filter(pk=event_id).first()
    if not event: return
    try: save_event_embedding(event, force=force)
    except EmbeddingError: logger.warning("Event embedding deferred; retry with rebuild_event_embeddings (event_id=%s)", event_id)

@receiver(post_save, sender=Event)
def embed_event_after_save(sender, instance, raw=False, created=False, **kwargs):
    if not raw and (created or getattr(instance, "_semantic_text_changed", False)):
        _refresh(instance.pk, force=True)

@receiver(m2m_changed, sender=Event.interests.through)
def embed_event_categories(sender, instance, action, **kwargs):
    if action in ("post_add", "post_remove", "post_clear"):
        _refresh(instance.pk, force=True)
