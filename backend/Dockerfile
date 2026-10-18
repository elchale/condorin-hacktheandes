# Two stage build: the builder installs deps into /install, the runtime copies them
# with the source and runs as an unprivileged user.

FROM python:3.13-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /build
COPY requirements.txt ./
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DJANGO_SETTINGS_MODULE=backend.settings PORT=8000
RUN groupadd --system --gid 1000 app && useradd --system --uid 1000 --gid app app
WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=app:app . .
# collectstatic only loads settings: placeholder secrets, no database connection.
RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh \
    && DJANGO_SECRET_KEY=build DATABASE_URL=sqlite:////tmp/build.db python manage.py collectstatic --noinput
USER app
EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
# No --access-logfile: core.middleware.AccessLogsMiddleware logs every request with the alert tokens redacted.
CMD gunicorn backend.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 60 \
    --error-logfile -
