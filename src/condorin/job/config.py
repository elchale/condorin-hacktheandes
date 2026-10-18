"""Settings of the Cloud Run Job `condorin-detector`, read from environment variables."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DETECTIONS_URL = "https://api.condorin.pe/api/v1/detections"


class JobSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    # --- what to process ---
    # Set per execution by the trigger (container override), e.g. "yaguas/2026-10-18".
    prefix: str = ""
    input_bucket: str = "river-images"
    image_suffixes: tuple[str, ...] = (".jpg", ".jpeg", ".png")
    max_images: int | None = Field(None, ge=1)
    # Stop starting new images this long into the task, so the summary and the report are written
    # before Cloud Run kills the task at its --task-timeout (3600 s in deploy/gcp-setup.sh).
    # Images not started count as failed (`not_started`); re-running the prefix picks them up.
    task_budget_s: float = Field(3300, gt=0)
    # One JSON per task listing every image that was not reported, and why:
    # <bucket>/<reports_prefix>/<execution>/task-NNN.json. Empty string: no report.
    reports_prefix: str = "reports"

    # --- model / inference (field names are what build_detector reads) ---
    model_dir: str = "/models/current"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    fake_model: bool = False  # dev and tests only; never posts unless ALLOW_FAKE_POST=1
    allow_fake_post: bool = False
    torch_threads: int | None = None
    infer_batch: int = 8
    gate_enabled: bool = False
    # Boxes below this are not reported. Default: the model card's review_low.
    min_confidence: float | None = Field(None, ge=0.0, le=1.0)

    # --- crops (uploaded next to the scenes; the backend's SA can already read river-images) ---
    crops_prefix: str = "crops"
    crop_padding_px: int = 32
    crop_min_side_px: int = 128

    # --- image metadata ---
    default_satellite: str = "SkyFi"  # used when the object has no `satellite` custom metadata

    # --- backend ---
    webhook_mode: Literal["post", "log"] = "log"
    webhook_url: str = DETECTIONS_URL
    webhook_audience: str | None = None  # default: webhook_url
    # Fallback auth (Secret Manager). Without it, a Google ID token of the runtime SA is used.
    detections_shared_secret: SecretStr | None = None
    webhook_timeout_s: float = 30.0
    webhook_attempts: int = Field(4, ge=1)
    webhook_backoff_s: float = 2.0

    log_level: str = "INFO"

    @property
    def audience(self) -> str:
        return self.webhook_audience or self.webhook_url
