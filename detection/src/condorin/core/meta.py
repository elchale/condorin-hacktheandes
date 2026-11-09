"""Image metadata, geo mapping and idempotency helpers for the webhook (ported from Appendix A)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

META_FIELDS = ("river", "satellite", "captured_at", "bounds")


def idempotency_key(bucket: str, obj: str, generation: str) -> str:
    return f"{bucket}/{obj}#{generation}"  # sent as the Idempotency-Key header


_BOUNDS = re.compile(
    r"sw_(-?\d+(?:\.\d+)?)_(-?\d+(?:\.\d+)?)_ne_(-?\d+(?:\.\d+)?)_(-?\d+(?:\.\d+)?)"
)


def bounds_from_name(obj: str) -> dict | None:
    m = _BOUNDS.search(obj)
    if not m:
        return None
    s_lat, s_lon, n_lat, n_lon = map(float, m.groups())
    return {"sw": [s_lat, s_lon], "ne": [n_lat, n_lon]}  # [lat, lon]


_TS = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2})(\d{2})Z")


def captured_at_from_name(obj: str) -> str | None:
    m = _TS.search(obj)
    if not m:
        return None
    y, mo, d, h, mi = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:00Z"


def river_from_name(obj: str) -> str | None:
    return obj.split("/", 1)[0] if "/" in obj else None


def box_to_webhook(
    xyxy: tuple[float, float, float, float] | list[float], w: int, h: int, bounds: dict | None
) -> tuple[list[int], float | None, float | None]:
    """xyxy pixels -> ([x, y, w, h] ints with x,y = top-left, lat, lon of the box centre)."""
    x1, y1, x2, y2 = xyxy
    bbox = [round(x1), round(y1), round(x2 - x1), round(y2 - y1)]
    if not bounds:
        return bbox, None, None
    (s_lat, s_lon), (n_lat, n_lon) = bounds["sw"], bounds["ne"]
    cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
    lon = s_lon + cx * (n_lon - s_lon)
    lat = n_lat - cy * (n_lat - s_lat)  # image y grows downward
    return bbox, round(lat, 6), round(lon, 6)


def _parse_bounds(value: Any, obj: str = "", source: str = "") -> dict | None:
    """{"sw": [lat, lon], "ne": [lat, lon]}, or None (with a warning) when the value is unusable."""
    if value is None or value == "":
        return None

    def bad(why: str) -> None:
        log.warning(f"ignoring {source or 'invalid'} bounds: {why}",
                    extra={"fields": {"object": obj, "bounds": str(value)[:200]}})  # fmt: skip

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return bad("not valid JSON")
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    try:
        sw = [float(v) for v in value["sw"]]
        ne = [float(v) for v in value["ne"]]
    except (KeyError, TypeError, ValueError):
        return bad('expected {"sw": [lat, lon], "ne": [lat, lon]}')
    if len(sw) != 2 or len(ne) != 2:
        return bad("sw and ne must be [lat, lon]")
    if not all(-90 <= lat <= 90 for lat in (sw[0], ne[0])) or not all(
        -180 <= lon <= 180 for lon in (sw[1], ne[1])
    ):
        return bad("latitude or longitude out of range")
    if not (sw[0] < ne[0] and sw[1] < ne[1]):  # swapped corners would mirror every detection
        return bad("sw must be south-west of ne")
    return {"sw": sw, "ne": ne}


def resolve_image_meta(
    bucket: str, obj: str, object_metadata: dict | None, options: dict | None
) -> dict:
    """river, satellite, captured_at, bounds. Priority per field:
    job options > GCS object custom metadata > parsed from the object path > None."""
    options = options or {}
    md = object_metadata or {}
    parsed = {
        "river": river_from_name(obj),
        "satellite": None,
        "captured_at": captured_at_from_name(obj),
        "bounds": bounds_from_name(obj),
    }
    out: dict = {}
    for field in META_FIELDS:
        value = None
        sources = {"options": options.get(field), "metadata": md.get(field),
                   "object name": parsed[field]}  # fmt: skip
        for name, source in sources.items():
            if field == "bounds":
                source = _parse_bounds(source, obj, name)  # invalid: falls through to the next
            if source not in (None, ""):
                value = source
                break
        out[field] = value
    return out
