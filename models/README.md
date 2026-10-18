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
  "training": {"dataset": "<id>", "date": "<iso>"},
  "metrics": {"val": {}, "test": {}}
}
```

- `classes` must be in the same order as the model's class indices; `positive_class` must be one of them.
- `thresholds.detect` is the image-level threshold picked on the validation split for target recall 0.95
  (the training toolkit's `evaluate` step writes it to `threshold.json`). `thresholds.review_low` is a lower
  threshold for higher recall (for example a 0.99 target). The card is rejected if `review_low > detect`.
- `model.name` in the webhook comes from `name` (the Django team expects `dredge-detector`).
- `inference` must match how the model was evaluated: native-resolution tiles, cross-tile class-aware NMS.

The card is validated by `condorin.core.model_card.ModelCard`; check it locally before publishing:

```bash
.venv/bin/python -c "from condorin.core.model_card import load_model_card; print(load_model_card('path/to/dir'))"
```

## Publishing a new version

```bash
VERSION=2026-10-r1
gcloud storage cp best.pt model_card.json gs://<bucket>/models/$VERSION/
# Then build + deploy with that version (see docs/runbook.md):
gcloud builds submit --config deploy/cloudbuild.yaml --substitutions=_MODEL_VERSION=$VERSION,...
```

The image tag is `<code-version>-model<model-version>`, so every deployed revision names its exact model.

## Local development

No model is needed: set `FAKE_MODEL=1` and the service uses a deterministic fake detector and a built-in
placeholder card (`version: "fake-0"`, placeholder thresholds). To try real weights locally, put
`model_card.json` and the weights into a directory and set `MODEL_DIR` to it.
