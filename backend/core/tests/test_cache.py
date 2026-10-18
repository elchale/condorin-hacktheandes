"""Production's default cache is the DatabaseCache table that core 0002_cache_table creates on deploy."""
import importlib

import pytest
from django.conf import settings as django_settings
from django.core.cache.backends.db import DatabaseCache
from django.db import connection

pytestmark = pytest.mark.django_db

PROD_CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.db.DatabaseCache', 'LOCATION': 'django_cache'},
    'local': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'prod-local'},
}


def test_production_settings_share_the_database_cache():
    from backend.settings import common

    assert common.CACHES['default']['BACKEND'] == 'django.core.cache.backends.db.DatabaseCache'
    assert common.CACHES['default']['LOCATION'] == 'django_cache'
    assert common.CACHES['local']['BACKEND'].endswith('LocMemCache')
    assert django_settings.REST_FRAMEWORK['DEFAULT_THROTTLE_CLASSES'] == ['core.throttling.ScopedThrottle']


def test_the_migration_creates_the_cache_table(settings):
    settings.CACHES = PROD_CACHES
    migration = importlib.import_module('core.migrations.0002_cache_table')
    with connection.schema_editor() as editor:
        migration.create_cache_table(None, editor)
        migration.create_cache_table(None, editor)  # a second deploy finds it and does nothing
    assert 'django_cache' in connection.introspection.table_names()

    shared = DatabaseCache('django_cache', {})
    assert shared.add('otp-sent:51936282808', 1, 45)
    assert not shared.add('otp-sent:51936282808', 1, 45)  # what the 45 s resend lock relies on
    assert shared.get('otp-sent:51936282808') == 1
