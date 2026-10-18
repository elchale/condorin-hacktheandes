from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from condorin.core.model_card import ModelCard

FAKE_TOKEN = "test-token-not-real-1234"


def make_image(w: int = 1280, h: int = 1280, seed: int = 0) -> np.ndarray:
    """Synthetic 'river scene' RGB: textured green forest with a tan river band."""
    rng = np.random.default_rng(seed)
    img = np.empty((h, w, 3), np.uint8)
    img[...] = (40, 90, 40)
    img = np.clip(img + rng.integers(-25, 25, img.shape), 0, 255).astype(np.uint8)
    y0, y1 = h // 3, h // 3 + max(h // 6, 1)
    img[y0:y1] = (170, 140, 100)
    return img


def encode(rgb: np.ndarray, fmt: str = "JPEG") -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, fmt, **({"quality": 92} if fmt == "JPEG" else {}))
    return buf.getvalue()


@pytest.fixture
def card() -> ModelCard:
    return ModelCard.placeholder()


@pytest.fixture
def jpeg_bytes() -> bytes:
    return encode(make_image())
