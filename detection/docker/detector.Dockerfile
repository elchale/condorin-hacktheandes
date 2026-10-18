# syntax=docker/dockerfile:1
# Detector service image. CPU only for now (VARIANT=cpu). The model is pre-fetched into ./model
# (model_card.json + weights) by Cloud Build and baked in at /models/current.
# An empty ./model directory still builds; run it with FAKE_MODEL=1.
#
#   docker build -f docker/detector.Dockerfile --build-arg VARIANT=cpu -t detector:dev .

ARG PYTHON_IMAGE=python:3.11-slim

FROM ${PYTHON_IMAGE} AS builder
ARG VARIANT=cpu
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# torch is installed from the PyTorch wheel index, not from pyproject.
#  cpu: CPU wheels.
#  gpu: later phase. Cloud Run's GPU driver is 580.x (CUDA 13.0): use a torch build for CUDA <= 13.0
#       and never install a driver in the image. Index URL below is a placeholder. VERIFY before use.
RUN if [ "$VARIANT" = "cpu" ]; then \
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu; \
    elif [ "$VARIANT" = "gpu" ]; then \
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128; \
    else echo "unknown VARIANT=$VARIANT" >&2; exit 1; fi

COPY pyproject.toml README.md LICENSE /build/
COPY src /build/src
RUN pip install "/build[serve]" \
    # ultralytics pulls the GUI opencv build; keep only the headless one (both own the cv2 package)
    && V=$(pip show opencv-python-headless | awk '/^Version:/{print $2}') \
    && pip uninstall -y opencv-python opencv-python-headless \
    && pip install "opencv-python-headless==${V}" \
    && python -c "import cv2, torch, ultralytics, condorin; print('cv2', cv2.__version__, 'torch', torch.__version__)"

FROM ${PYTHON_IMAGE}
ARG VARIANT=cpu
LABEL org.opencontainers.image.source="https://github.com/sergtello/condorin-detection" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.title="condorin-detector-${VARIANT}"
RUN useradd --create-home --uid 10001 app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app model/ /models/current/
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    MODEL_DIR=/models/current \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    PORT=8080
USER app
WORKDIR /home/app
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn condorin.service.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
