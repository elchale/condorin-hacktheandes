from __future__ import annotations

import pytest

from condorin.core.meta import (
    bounds_from_name,
    box_to_webhook,
    captured_at_from_name,
    idempotency_key,
    resolve_image_meta,
)

TILE = "tile_r003_c004_sw_-2.782003_-70.977122_ne_-2.772959_-70.968128.jpg"
BOUNDS = {"sw": [-2.782003, -70.977122], "ne": [-2.772959, -70.968128]}


def test_bounds_and_captured_at_from_name():
    assert bounds_from_name(TILE) == BOUNDS
    assert bounds_from_name("no_bounds.jpg") is None
    assert captured_at_from_name("yaguas/2026-10-15T1042Z_s1.jpeg") == "2026-10-15T10:42:00Z"
    assert captured_at_from_name("yaguas/img.jpeg") is None


def test_box_to_webhook_corners():
    _, lat, lon = box_to_webhook((0, 0, 2, 2), 2560, 2560, BOUNDS)  # top-left
    assert lat == pytest.approx(BOUNDS["ne"][0], abs=1e-5)
    assert lon == pytest.approx(BOUNDS["sw"][1], abs=1e-5)
    _, lat, lon = box_to_webhook((2558, 2558, 2560, 2560), 2560, 2560, BOUNDS)  # bottom-right
    assert lat == pytest.approx(BOUNDS["sw"][0], abs=1e-5)
    assert lon == pytest.approx(BOUNDS["ne"][1], abs=1e-5)


def test_box_to_webhook_bbox_and_no_bounds():
    bbox, lat, lon = box_to_webhook((412.4, 318.2, 426.3, 327.0), 2560, 2560, None)
    assert bbox == [412, 318, 14, 9] and lat is None and lon is None


def test_idempotency_key():
    key = idempotency_key("river-images", "yaguas/2026-10-15T1042Z_s1.jpeg", "1792297654023751")
    assert key == "river-images/yaguas/2026-10-15T1042Z_s1.jpeg#1792297654023751"


def test_resolve_image_meta_priority():
    obj = f"yaguas/2026-10-15T1042Z_{TILE}"
    parsed = resolve_image_meta("b", obj, None, None)
    assert parsed == {
        "river": "yaguas",
        "satellite": None,
        "captured_at": "2026-10-15T10:42:00Z",
        "bounds": BOUNDS,
    }
    md = {"river": "putumayo", "satellite": "Skyfi", "bounds": '{"sw": [1, 2], "ne": [3, 4]}'}
    from_md = resolve_image_meta("b", obj, md, None)
    assert from_md["river"] == "putumayo" and from_md["satellite"] == "Skyfi"
    assert from_md["bounds"] == {"sw": [1.0, 2.0], "ne": [3.0, 4.0]}
    opts = {"river": "napo", "bounds": {"sw": [5, 6], "ne": [7, 8]}}
    from_opts = resolve_image_meta("b", obj, md, opts)
    assert from_opts["river"] == "napo" and from_opts["satellite"] == "Skyfi"
    assert from_opts["bounds"] == {"sw": [5.0, 6.0], "ne": [7.0, 8.0]}


def test_resolve_image_meta_bad_metadata_falls_back_to_name():
    out = resolve_image_meta("b", f"x/{TILE}", {"bounds": "not json"}, None)
    assert out["bounds"] == BOUNDS
    assert resolve_image_meta("b", "flat.jpg", {}, {})["river"] is None
