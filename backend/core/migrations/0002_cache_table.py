"""The DatabaseCache table (`django_cache`, settings.CACHES['default']), created on deploy with the migrations."""
from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    # Idempotent: createcachetable skips a table that already exists.
    call_command('createcachetable', database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_cache_table, migrations.RunPython.noop),
    ]
