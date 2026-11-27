"""Why a Cloudflare embedding call failed, as the search log records it."""
import io
import urllib.error
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.events.semantic_search import EmbeddingError, _error_code, embed_text


def http_error(code):
    return urllib.error.HTTPError('https://api.cloudflare.com', code, 'error', {}, io.BytesIO(b''))


class ErrorCodeTests(SimpleTestCase):
    def test_each_kind_of_failure_gets_its_own_code(self):
        self.assertEqual(_error_code(http_error(429)), 'rate_limited')
        self.assertEqual(_error_code(http_error(503)), 'server_error')
        self.assertEqual(_error_code(http_error(401)), 'rejected')
        self.assertEqual(_error_code(urllib.error.URLError(TimeoutError())), 'timeout')
        self.assertEqual(_error_code(TimeoutError()), 'timeout')
        self.assertEqual(_error_code(urllib.error.URLError('name not resolved')), 'network')
        self.assertEqual(_error_code(EmbeddingError('bad', code='malformed')), 'malformed')
        self.assertEqual(EmbeddingError('offline').code, 'unavailable')

    @override_settings(CLOUDFLARE_ACCOUNT_ID='account', CLOUDFLARE_API_TOKEN='token')
    def test_embed_text_retries_once_then_reports_the_last_error(self):
        with patch('urllib.request.urlopen', side_effect=http_error(429)) as urlopen, patch('time.sleep'):
            with self.assertRaises(EmbeddingError) as raised:
                embed_text('robots')
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(raised.exception.code, 'rate_limited')

    @override_settings(CLOUDFLARE_ACCOUNT_ID='', CLOUDFLARE_API_TOKEN='')
    def test_missing_keys(self):
        with self.assertRaises(EmbeddingError) as raised:
            embed_text('robots')
        self.assertEqual(raised.exception.code, 'not_configured')
