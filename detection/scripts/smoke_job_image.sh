#!/usr/bin/env bash
# Run a built Job image once on a synthetic scene in log mode (nothing is posted to the backend).
# Passes when the Job exits 0 and reports the scene: the model card loads, the weights load and match
# the card's classes, and inference runs inside the image.
#
#   scripts/smoke_job_image.sh IMAGE            # the model baked into the image
#   scripts/smoke_job_image.sh IMAGE --fake     # FAKE_MODEL=1 (image built without a model)
set -euo pipefail

IMAGE="${1:?usage: $0 IMAGE [--fake]}"
FAKE=0
[[ "${2:-}" == "--fake" ]] && FAKE=1

DATA="$(mktemp -d)"
trap 'rm -rf "$DATA"' EXIT
# A local folder stands in for the bucket: <river>/<YYYY-MM-DD>T<HHMM>Z_..._sw_<lat>_<lon>_ne_<lat>_<lon>
SCENE="smoke/2026-01-01T0000Z_sw_-2.80_-71.00_ne_-2.79_-70.99.jpg"
# Run as the host user so the files the container writes (crops/) can be cleaned up; that user cannot
# write /home/app, so work in /tmp (ultralytics touches runs/ under the working directory).
RUN=(docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -w /tmp -v "$DATA:/data")

# The image has numpy and Pillow: make the scene inside it (forest texture with a muddy river band).
"${RUN[@]}" --entrypoint python "$IMAGE" -c "
import os, numpy as np
from PIL import Image
rng = np.random.default_rng(0)
img = np.clip(np.full((1280, 1280, 3), (40, 90, 40)) + rng.integers(-25, 25, (1280, 1280, 3)), 0, 255)
img[420:640] = (170, 140, 100)
os.makedirs('/data/smoke', exist_ok=True)
Image.fromarray(img.astype(np.uint8)).save('/data/$SCENE', quality=92)
"

ENV=(-e WEBHOOK_MODE=log -e INPUT_BUCKET=/data -e PREFIX=smoke/)
(( FAKE )) && ENV+=(-e FAKE_MODEL=1)

set +e
"${RUN[@]}" "${ENV[@]}" "$IMAGE" > "$DATA/job.log" 2>&1
code=$?
set -e
cat "$DATA/job.log"

if (( code != 0 )); then
  echo "::error::the Job exited with $code" >&2
  exit 1
fi
if ! grep -q '"message": "done: 1 reported' "$DATA/job.log"; then
  echo "::error::the Job did not report the smoke scene" >&2
  exit 1
fi
echo "smoke test passed: $IMAGE"
