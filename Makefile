PY ?= .venv/bin/python
PORT ?= 8080
TAG ?= dev
MODEL_VERSION ?= fake
VARIANT ?= cpu

.PHONY: install test lint fmt run-local run-notifier build-detector build-notifier smoke django-test

install:
	uv venv .venv --python 3.12
	uv pip install --python .venv torch torchvision --index-url https://download.pytorch.org/whl/cpu
	uv pip install --python .venv -e ".[serve,dev]"

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

# Local detector with the fake model, local results dir, webhook events only logged.
run-local:
	FAKE_MODEL=1 WEBHOOK_MODE=log DETECT_MODE=direct \
	RESULTS_URI_PREFIX=out/results OVERLAY_URI_PREFIX=out/overlays BATCHES_URI_PREFIX=out/batches \
	$(PY) -m uvicorn condorin.service.app:app --host 127.0.0.1 --port $(PORT)

run-notifier:
	$(PY) -m uvicorn condorin.notifier.app:app --host 127.0.0.1 --port 8081

# Expects the model artifacts (model_card.json + weights) pre-fetched into ./model.
# With no ./model directory the image still builds and runs with FAKE_MODEL=1.
build-detector:
	mkdir -p model
	docker build -f docker/detector.Dockerfile --build-arg VARIANT=$(VARIANT) \
		-t condorin-detector:$(TAG)-model$(MODEL_VERSION) .

build-notifier:
	docker build -f docker/notifier.Dockerfile -t condorin-notifier:$(TAG) .

# Runs against a detector started with `make run-local` (generates fake images in out/smoke).
smoke:
	$(PY) scripts/smoke_test.py --base-url http://127.0.0.1:$(PORT) --make-images 5

django-test:
	cd docs/examples/django_webhook_receiver && $(PY) runtests.py
