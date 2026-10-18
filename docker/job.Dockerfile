# syntax=docker/dockerfile:1
# Cloud Run Job `condorin-detector` (CPU). The model (model_card.json + weights) is pre-fetched
# into ./model by CI and baked in at /models/current. With an empty ./model the image builds, but
# the Job exits with "no model_card.json" (and FAKE_MODEL=1 never posts to the backend).
#
#   mkdir -p model && docker build -f docker/job.Dockerfile -t condorin-detector:dev .
#   docker run --rm -e FAKE_MODEL=1 -e PREFIX=yaguas/ -e INPUT_BUCKET=/data \
#     -v "$PWD/out/smoke/images:/data" condorin-detector:dev

ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS builder
# Keep in step with the `ml` extra in pyproject.toml and the versions the model was trained with.
ARG TORCH_VERSION=2.14.1
ARG TORCHVISION_VERSION=0.29.1
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
# torch from the PyTorch CPU index, not from PyPI
RUN pip install "torch==${TORCH_VERSION}" "torchvision==${TORCHVISION_VERSION}" \
    --index-url https://download.pytorch.org/whl/cpu
COPY pyproject.toml README.md LICENSE /build/
COPY src /build/src
RUN pip install "/build[job,ml]" \
    # ultralytics pulls the GUI opencv build; keep only the headless one (both own the cv2 package)
    && V=$(pip show opencv-python-headless | awk '/^Version:/{print $2}') \
    && pip uninstall -y opencv-python opencv-python-headless \
    && pip install "opencv-python-headless==${V}" \
    && python -c "import cv2, torch, ultralytics, condorin.job.runner; print('torch', torch.__version__)"

FROM ${PYTHON_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/sergtello/condorin-detection" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.title="condorin-detector"
RUN useradd --create-home --uid 10001 app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app model/ /models/current/
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    MODEL_DIR=/models/current \
    YOLO_CONFIG_DIR=/tmp/ultralytics
USER app
WORKDIR /home/app
CMD ["python", "-m", "condorin.job"]
