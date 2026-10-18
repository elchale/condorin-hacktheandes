#!/usr/bin/env bash
set -o errexit

# Migrations run at start: Railway only exposes DATABASE_URL at run time, not during the build.
python manage.py migrate --noinput

# Sync workers plus threads: alerts go out on a background thread after the webhook responds.
exec gunicorn backend.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 60 \
    --access-logfile - --error-logfile -
