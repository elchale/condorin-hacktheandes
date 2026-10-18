"""Native-resolution tiling (ported exactly from the training toolkit's evaluation)."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np


def tile_starts(length: int, tile: int, overlap: int) -> list[int]:
    if length <= tile:
        return [0]
    step = max(1, tile - overlap)
    s = list(range(0, length - tile + 1, step))
    if s[-1] + tile < length:
        s.append(length - tile)  # last tile flush with the edge
    return s


def tile_offsets(height: int, width: int, tile: int, overlap: int) -> list[tuple[int, int]]:
    """(x0, y0) of every tile, row by row."""
    return [
        (x0, y0)
        for y0 in tile_starts(height, tile, overlap)
        for x0 in tile_starts(width, tile, overlap)
    ]


def iter_tiles(image: np.ndarray, tile: int, overlap: int) -> Iterator[tuple[int, int, np.ndarray]]:
    """Yield (x0, y0, crop). Crops are views; edge crops are smaller than `tile` only if the image is."""
    h, w = image.shape[:2]
    for x0, y0 in tile_offsets(h, w, tile, overlap):
        yield x0, y0, image[y0 : y0 + tile, x0 : x0 + tile]
