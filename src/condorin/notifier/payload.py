"""Map the internal result.json (Appendix B2) to the Django webhook body (Appendix B1).

ASSUMED rules (to confirm with the Django team; each is one setting away from changing):
- only `positive_class` boxes with confidence >= WEBHOOK_MIN_CONFIDENCE (default: card review_low);
- bbox = [x, y, w, h] in full-image pixels, top-left origin;
- crop_uri = the source image URI with `#generation` (CROP_URI_MODE=source);
- nothing is sent when there are no detections (SEND_EMPTY=false), for QC rejections or failures.
"""

from __future__ import annotations

import json

from condorin.core.meta import box_to_webhook
from condorin.service.schemas import WebhookPayload


def source_crop_uri(image: dict) -> str:
    return f"gs://{image['bucket']}/{image['object']}#{image['generation']}"


def build_webhook_payload(
    result: dict, min_confidence: float | None = None, send_empty: bool = False
) -> dict | None:
    if result.get("status") != "ok":
        return None
    img = result["image"]
    thr = result["model"]["thresholds"]["review_low"] if min_confidence is None else min_confidence
    crop_uri = source_crop_uri(img)
    dets = sorted(
        (
            d
            for d in result.get("detections", [])
            if d["class"] == result["positive_class"] and d["confidence"] >= thr
        ),
        key=lambda d: -d["confidence"],
    )
    if not dets and not send_empty:
        return None
    payload = {
        "image": {
            "bucket": img["bucket"],
            "object": img["object"],
            "generation": str(img["generation"]),
            "river": img.get("river"),
            "satellite": img.get("satellite"),
            "captured_at": img.get("captured_at"),
        },
        "model": {"name": result["model"]["name"], "version": result["model"]["version"]},
        "detections": [
            {
                "lat": d.get("lat"),
                "lon": d.get("lon"),
                "confidence": round(float(d["confidence"]), 4),
                "bbox": box_to_webhook(d["bbox_xyxy"], 1, 1, None)[0],
                "crop_uri": crop_uri,
            }
            for d in dets
        ],
    }
    WebhookPayload.model_validate(payload)  # contract check
    return payload


def serialize(payload: dict) -> bytes:
    """Serialise once; these exact bytes are sent."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
