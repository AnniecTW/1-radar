from django.core.management.base import BaseCommand
from apps.events.models import Event
from apps.events.semantic_search import EmbeddingError, save_event_embedding


class Command(BaseCommand):
    help = 'Build or rebuild saved Cloudflare BGE embeddings for events.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Rebuild even valid current embeddings')
        parser.add_argument('--all', action='store_true', help='Include drafts and ended events')

    def handle(self, *args, **options):
        qs = Event.objects.all().prefetch_related('interests').select_related('venue')
        if not options['all']:
            qs = qs.filter(status=Event.Status.PUBLISHED)
        failed = 0
        for event in qs.iterator(chunk_size=50):
            try:
                changed = save_event_embedding(event, force=options['force'])
                if changed:
                    self.stdout.write(f'Embedded {event.pk}')
            except EmbeddingError:
                failed += 1
                self.stderr.write(f'Failed event {event.pk}; safe to rerun')
        self.stdout.write(f'Finished; failed: {failed}')
