from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from apps.events.semantic_search import DIMENSIONS, EmbeddingError, _vector, cosine, embed_text


class SemanticSearchHelpersTests(SimpleTestCase):
    def test_cosine_ranks_aligned_vectors(self):
        self.assertAlmostEqual(cosine([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertAlmostEqual(cosine([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_response_vector_dimensions_are_checked(self):
        with self.assertRaises(EmbeddingError):
            _vector({'result': {'data': [[0.0] * (DIMENSIONS - 1)]}})

    @override_settings(CLOUDFLARE_ACCOUNT_ID='', CLOUDFLARE_API_TOKEN='')
    def test_missing_configuration_fails_closed(self):
        with self.assertRaises(EmbeddingError):
            embed_text('query')
