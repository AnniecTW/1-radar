"""Settings for the deployed site (a Docker container on Azure App Service).

Everything that differs between deployments comes from environment variables, set in App Service under
Settings > Environment variables. .env.example lists them.
"""
import os

from . import base as _base
from .base import *  # noqa: F403
from .base import DATABASES, MIDDLEWARE


def _env_list(name):
    return [item.strip() for item in os.environ.get(name, '').split(',') if item.strip()]


def _env_flag(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


DEBUG = False

# The site's host names, e.g. "radar-demo.azurewebsites.net" (comma-separated for several).
ALLOWED_HOSTS = _env_list('ALLOWED_HOSTS') or ['localhost', '127.0.0.1']
# Forms are only accepted from these origins. Defaults to https:// plus each allowed host.
CSRF_TRUSTED_ORIGINS = _env_list('CSRF_TRUSTED_ORIGINS') or [
    f'https://{host}' for host in ALLOWED_HOSTS if host not in ('localhost', '127.0.0.1')
]
# Links in notification emails. Defaults to https:// plus the first public allowed host.
_public_hosts = [host for host in ALLOWED_HOSTS if host not in ('localhost', '127.0.0.1') and not host.startswith('.')]
SITE_URL = os.environ.get('SITE_URL') or (f'https://{_public_hosts[0]}' if _public_hosts else SITE_URL)

# HTTPS. Azure ends TLS at its front end and passes the request on as plain HTTP with
# X-Forwarded-Proto, so Django has to read that header to know the visitor used HTTPS. That also makes
# absolute links in emails (verification, password reset) start with https://.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = _env_flag('SECURE_SSL_REDIRECT', True)  # Set to 0 only to try the image locally.
SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '3600')) if SECURE_SSL_REDIRECT else 0
# HSTS for subdomains and the browsers' preload list only make sense on a domain we own, not on
# Microsoft's azurewebsites.net.
SILENCED_SYSTEM_CHECKS = ['security.W005', 'security.W021']

# Static files: collected into the image at build time and served by WhiteNoise, compressed.
# Not hashed: templates already add ?v=N to bust caches, and hashing would turn a typo in a
# {% static %} path into a server error on that page.
STATIC_ROOT = BASE_DIR / 'staticfiles'  # noqa: F405
MIDDLEWARE = [MIDDLEWARE[0], 'whitenoise.middleware.WhiteNoiseMiddleware', *MIDDLEWARE[1:]]
# Uploads keep base.py's choice: Supabase Storage when its keys are set. Set them on Azure, because
# without them uploads land on the container's disk and disappear when it restarts.
STORAGES = {
    'default': getattr(_base, 'STORAGES', {}).get('default',
                                                 {'BACKEND': 'django.core.files.storage.FileSystemStorage'}),
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

# Database. Supabase's transaction pooler (port 6543) lets many app processes share a few real
# connections, so the demo and everyone's dev servers don't run out. It hands each transaction to
# whichever real connection is free, so server-side cursors can't be used. (Django already turns off
# psycopg's prepared statements, which it would also break.)
# Our connection to the pooler is kept open between requests: the database is across the country, and
# opening a new connection costs several round trips on every page. Holding it is cheap, because the
# pooler only lends us a real connection while a query runs. Health checks replace one that has dropped.
DATABASES['default']['CONN_MAX_AGE'] = int(os.environ.get('DB_CONN_MAX_AGE', '60'))
DATABASES['default']['CONN_HEALTH_CHECKS'] = True
if str(DATABASES['default'].get('PORT')) == '6543':
    DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True

# Logs go to the container's output, which App Service shows in Log stream.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}, 'discard': {'class': 'logging.NullHandler'}},
    'root': {'handlers': ['console'], 'level': os.environ.get('LOG_LEVEL', 'INFO')},
    'loggers': {
        'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
        # Bots probing the site with other host names get a 400; don't fill the log with their tracebacks.
        'django.security.DisallowedHost': {'handlers': ['discard'], 'propagate': False},
    },
}
