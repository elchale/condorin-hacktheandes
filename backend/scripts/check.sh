#!/usr/bin/env bash
# What CI runs (ruff, Django check, migrations check, pytest), against a throwaway local Postgres in
# Docker, so it takes seconds instead of the many minutes a test database on Neon takes.
# Usage: scripts/check.sh [pytest args]. The .githooks/pre-push hook runs it before every push.
set -euo pipefail
# CHECK_DIR: the tree to check (the pre-push hook passes a temporary worktree of the pushed commit).
cd "${CHECK_DIR:-$(dirname "$0")/..}"

# CHECK_PYTHON lets the pre-push hook reuse the main clone's .venv from a temporary worktree.
PY=${CHECK_PYTHON:-python}
if [ -z "${CHECK_PYTHON:-}" ]; then
  [ -x .venv/Scripts/python.exe ] && PY=.venv/Scripts/python.exe
  [ -x .venv/bin/python ] && PY=.venv/bin/python
fi

# Git Bash on Windows would rewrite the container paths below into C:/ paths.
export MSYS_NO_PATHCONV=1

CONTAINER=condorin-test-pg
PORT=54329

if ! docker info >/dev/null 2>&1; then
  echo "check.sh: Docker is not running. Start Docker Desktop and push again." >&2
  echo "          (Emergency only: git push --no-verify skips this, and CI still blocks the deploy.)" >&2
  exit 1
fi
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  docker run -d --name "$CONTAINER" -p "$PORT:5432" \
    -e POSTGRES_DB=condorin -e POSTGRES_USER=condorin -e POSTGRES_PASSWORD=condorin \
    --tmpfs /var/lib/postgresql/data postgres:16 >/dev/null
fi
for _ in $(seq 1 30); do
  docker exec "$CONTAINER" pg_isready -U condorin >/dev/null 2>&1 && break
  sleep 1
done

export DJANGO_SECRET_KEY=local-check-secret-key-not-for-production
export DATABASE_URL="postgres://condorin:condorin@localhost:$PORT/condorin"
# One database per run: two checks at once (two sessions, two pushes) must not drop each other's.
export TEST_DB_NAME="test_condorin_$$_${RANDOM}"

"$PY" -m ruff check .
"$PY" manage.py check --settings=backend.test_settings
"$PY" manage.py makemigrations --check --dry-run --settings=backend.test_settings
"$PY" -m pytest --tb=short -q --create-db "$@"
