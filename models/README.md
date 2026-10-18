# Model artifacts

**No weights in git.** Models are published to GCS and baked into the detector image at build time.

## Layout in GCS

```
gs://<bucket>/models/<version>/
├── best.pt            # Ultralytics YOLO weights (or an exported .onnx, named in model_card.json)
└── model_card.json    # schema below; the service reads thresholds from here and never hardcodes them
```

## `model_card.json`

```json
{
  "name": "dredge-detector", "version": "2026-10-r1", "weights": "best.pt",
  "classes": ["mining_vessel", "other_vessel"], "positive_class": "mining_vessel",
  "inference": {"tile": 640, "overlap": 128, "conf_floor": 0.05, "nms_iou": 0.5},
  "thresholds": {"detect": 0.62, "review_low": 0.25},
  "qc": {"expected_gsd_m": null, "gsd_tolerance": 0.25, "min_side_px": 640,
         "max_nodata_fraction": 0.5, "max_truncated_lost_fraction": 0.2},
  "training": {"dataset": "<id>", "date": "<iso>", "ultralytics": "8.4.182", "torch": "2.14.1"},
  "metrics": {"val": {}, "test": {}}
}
```

- `classes` must be in the same order as the model's class indices; `positive_class` must be one of them.
- `thresholds.detect` is the image-level threshold picked on the validation split for target recall 0.95
  (the training toolkit's `evaluate` step writes it to `threshold.json`). `thresholds.review_low` is a lower
  threshold for higher recall (for example a 0.99 target). The card is rejected if `review_low > detect`.
- `model.name` in the webhook comes from `name` (the Django team expects `dredge-detector`).
- `inference` must match how the model was evaluated: native-resolution tiles, cross-tile class-aware NMS.
- `training.ultralytics` / `training.torch`: the versions the model was trained and evaluated with. The Job
  logs a warning when the image runs different ones. The image pins them in `pyproject.toml` (`ml` extra)
  and `docker/job.Dockerfile` (`TORCH_VERSION`); change those pins together with the model.

Check a model folder before uploading it (CI runs the same check, and refuses to build otherwise):

```bash
.venv/bin/python scripts/check_model.py path/to/model          # card, weights file, name
.venv/bin/python scripts/check_model.py path/to/model --load   # + weights' class names == card classes
```

## Publishing a new version

```bash
VERSION=v0.3
gcloud storage cp best.pt model_card.json gs://<bucket>/models/$VERSION/
gh variable set MODEL_GCS_URI --body "gs://<bucket>/models/$VERSION/"   # then push to main (or re-run CI)
```

CI copies that folder into `./model`, runs `scripts/check_model.py`, bakes it into the Job image (tagged
`condorin-detector:<git sha>-model<version>`, so every Job revision names its exact model), and runs the
image once on a synthetic scene (`scripts/smoke_job_image.sh`, log mode) before pushing and deploying it.
A model whose class names do not match the card fails there, and the Job refuses to start with it. The
`version` field is what the backend receives as `model.version`. `github-deployer` needs
`roles/storage.objectViewer` on `<bucket>`.

## Local development

No model is needed: set `FAKE_MODEL=1` and the service uses a deterministic fake detector and a built-in
placeholder card (`version: "fake-0"`, placeholder thresholds). To try real weights locally, put
`model_card.json` and the weights into a directory and set `MODEL_DIR` to it.
