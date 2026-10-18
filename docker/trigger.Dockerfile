# syntax=docker/dockerfile:1
# Cloud Run service `condorin-detector-trigger`: tiny, no torch, no ultralytics.
#
#   docker build -f docker/trigger.Dockerfile -t condorin-detector-trigger:dev .

ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY pyproject.toml README.md LICENSE /build/
COPY src /build/src
RUN pip install "/build[trigger]" \
    && python -c "import condorin.trigger.app" \
    && ! python -c "import torch" 2>/dev/null

FROM ${PYTHON_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/sergtello/condorin-detection" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.title="condorin-detector-trigger"
RUN useradd --create-home --uid 10001 app
COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PORT=8080
USER app
WORKDIR /home/app
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn condorin.trigger.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
