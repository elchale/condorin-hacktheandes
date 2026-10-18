PY ?= .venv/bin/python
PORT ?= 8080
TAG ?= dev
MODEL_VERSION ?= fake

.PHONY: install test lint fmt run-job run-trigger build-job build-trigger

install:
	uv venv .venv --python 3.12
	uv pip install --python .venv torch torchvision --index-url https://download.pytorch.org/whl/cpu
	uv pip install --python .venv -e ".[job,ml,trigger,dev]"

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

# Job with the fake model over a local folder standing in for the bucket; payloads are only logged.
BUCKET ?= out/bucket
PREFIX ?= yaguas/
run-job:
	FAKE_MODEL=1 WEBHOOK_MODE=log INPUT_BUCKET=$(BUCKET) PREFIX=$(PREFIX) $(PY) -m condorin.job

run-trigger:
	$(PY) -m uvicorn condorin.trigger.app:app --host 127.0.0.1 --port $(PORT)

build-job:
	mkdir -p model
	docker build -f docker/job.Dockerfile -t condorin-detector:$(TAG)-model$(MODEL_VERSION) .

build-trigger:
	docker build -f docker/trigger.Dockerfile -t condorin-detector-trigger:$(TAG) .
