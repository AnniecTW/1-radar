from django.core.management.base import BaseCommand, CommandError
from apps.events.semantic_search import EmbeddingError, cosine, embed_text

class Command(BaseCommand):
    help = "Verify Cloudflare embedding configuration, dimensions, and cosine ranking."
    def handle(self, *args, **options):
        try:
            vector = embed_text("free food near the library tonight")
        except EmbeddingError as exc:
            raise CommandError(str(exc)) from None
        score = cosine(vector, vector)
        if len(vector) != 384 or score < .999:
            raise CommandError("Embedding validation failed")
        self.stdout.write("Cloudflare embedding and cosine checks passed (384 dimensions).")
