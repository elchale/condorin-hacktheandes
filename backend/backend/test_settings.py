"""Settings for pytest. Same Postgres server as DATABASE_URL, where Django creates a separate
`test_condorin` database for the run and drops it after. Refuses to load when that server is Neon (production):
use scripts/check.sh, which starts a throwaway Postgres in Docker.
Nothing goes out: WhatsApp is logged, email stays in memory, GCS is off."""
from backend.settings import *  # noqa: F403

DEBUG = False
SECURE_SSL_REDIRECT = False
WA_SEND_ENABLED = False
ALERTS_INLINE = True
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
GCS_CREDENTIALS_JSON = ''
GCS_EXPEDIENTES_BUCKET = ''
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

# Neon's pooler (PgBouncer) keeps idle server sessions on test_condorin after the run, so the next run
# cannot drop and recreate it. Tests talk to the direct endpoint instead (same host without -pooler).
DATABASES['default']['HOST'] = DATABASES['default'].get('HOST', '').replace('-pooler.', '.')  # noqa: F405

# Never the production server: pytest creates and drops databases on whatever DATABASE_URL names, and Neon is prod.
# Run the tests with scripts/check.sh (a throwaway Postgres in Docker) or a local Postgres.
if 'neon.tech' in DATABASES['default']['HOST']:  # noqa: F405
    raise RuntimeError('backend.test_settings: DATABASE_URL points at Neon (production). '
                       'Run scripts/check.sh, or set DATABASE_URL to a local Postgres.')

# Tests that touch no database clear the caches too (conftest), so both are in memory here. The shared
# DatabaseCache of production is covered by core/tests/test_cache.py.
CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'test-default'},
    'local': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'test-local'},
}
