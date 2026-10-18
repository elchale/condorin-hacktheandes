"""Optional river/water gate: skip tiles with no river. OFF by default (GATE_ENABLED=false).

Heuristic ported from the labeling toolkit. It is tuned for muddy, tan rivers only: black-water and clear
rivers would be silently missed. Enable only after measuring that it keeps ~100% of vessel tiles.
"""

from __future__ import annotations

import cv2
import numpy as np

HUE_RANGE = (5, 32)  # OpenCV HSV scale (0-179)
MIN_SAT = 30
MIN_VAL = 50
MAX_LOCAL_STD = 10.0
STD_WINDOW = 9
OPEN_KERNEL = 5
MIN_COMPONENT_FRACTION = 0.01
WET_TILE_FRACTION = 0.02


def water_mask(image_bgr: np.ndarray) -> np.ndarray:
    """Boolean HxW mask of (muddy) water pixels."""
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    color = (h >= HUE_RANGE[0]) & (h <= HUE_RANGE[1]) & (s >= MIN_SAT) & (v >= MIN_VAL)

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    k = (STD_WINDOW, STD_WINDOW)
    mean = cv2.blur(gray, k)
    sq_mean = cv2.blur(gray * gray, k)
    std = np.sqrt(np.maximum(sq_mean - mean * mean, 0))
    smooth = std < MAX_LOCAL_STD

    mask = (color & smooth).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((OPEN_KERNEL, OPEN_KERNEL), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    min_area = MIN_COMPONENT_FRACTION * mask.size
    keep = np.zeros(n, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    return keep[labels]


def tiles_with_water(image_bgr: np.ndarray, tiles: list[tuple[int, int, int, int]]) -> np.ndarray:
    """Keep mask for tiles given as (x0, y0, x1, y1): True if >= 2% of the tile's pixels are water."""
    mask = water_mask(image_bgr)
    keep = np.zeros(len(tiles), dtype=bool)
    for i, (x0, y0, x1, y1) in enumerate(tiles):
        sub = mask[y0:y1, x0:x1]
        keep[i] = sub.size > 0 and float(sub.mean()) >= WET_TILE_FRACTION
    return keep
