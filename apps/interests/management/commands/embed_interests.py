from django.core.management.base import BaseCommand

from apps.events.semantic_search import EmbeddingError
from apps.interests.embeddings import save_interest_embedding
from apps.interests.models import Interest


class Command(BaseCommand):
    help = 'Build or rebuild Cloudflare BGE embeddings for interests, from their descriptions.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Rebuild even valid current embeddings')

    def handle(self, *args, **options):
        failed = 0
        for interest in Interest.objects.filter(is_active=True).order_by('pk'):
            try:
                if save_interest_embedding(interest, force=options['force']):
                    self.stdout.write(f'Embedded "{interest.name}"')
            except EmbeddingError:
                failed += 1
                self.stderr.write(f'Failed interest "{interest.name}"; safe to rerun')
        self.stdout.write(f'Finished; failed: {failed}')
