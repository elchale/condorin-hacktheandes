#!/usr/bin/env bash
set -euo pipefail

# Migrations run before gunicorn binds $PORT, so while they run Cloud Run's startup probe sees nothing.
# Bound them: a database that does not answer fails the revision in about two minutes with a clear log
# line instead of keeping "Creating Revision" busy until the deploy times out. The previous revision
# keeps serving either way. Set RUN_MIGRATIONS=0 when a Cloud Run job runs `manage.py migrate` instead.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    echo "entrypoint: running migrations (limit ${MIGRATE_TIMEOUT:-120}s)"
    if ! timeout "${MIGRATE_TIMEOUT:-120}" python manage.py migrate --noinput; then
        echo "entrypoint: migrate failed or timed out; is DATABASE_URL reachable?" >&2
        exit 1
    fi
fi

exec "$@"
