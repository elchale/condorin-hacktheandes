"""Service settings, read from environment variables (BUILD_INSTRUCTIONS.md Appendix D)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    # --- model / inference (detector) ---
    model_dir: str = "/models/current"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    fake_model: bool = False  # dev and tests only
    torch_threads: int | None = None
    infer_batch: int = 8
    gate_enabled: bool = False
    audit_rate: float = Field(0.01, ge=0.0, le=1.0)
    request_budget_s: float = 840.0  # must stay below the Cloud Run request timeout (900 s)

    # --- storage ---
    results_uri_prefix: str = "out/results"
    overlay_uri_prefix: str = "out/overlays"
    batches_uri_prefix: str = "out/batches"
    failed_deliveries_uri_prefix: str = "out/failed_deliveries"

    # --- queues (detector) ---
    webhook_mode: Literal["tasks", "direct", "log"] = "log"
    detect_mode: Literal["tasks", "direct"] = "direct"
    gcp_project: str | None = None
    gcp_region: str = "southamerica-west1"
    detect_queue: str = "detect"
    webhook_queue: str = "webhook"
    detector_url: str | None = None  # base URL of this service, target of detect tasks
    notifier_url: str | None = None  # base URL of the notifier, target of webhook tasks
    tasks_sa_email: str | None = None  # service account used for the OIDC token on tasks
    task_dispatch_deadline_s: int = 900

    # --- webhook (payload rules in the detector, delivery in the notifier) ---
    webhook_url: str | None = None  # https://api.condorin.pe/api/v1/detections in production
    webhook_token: SecretStr | None = None  # from Secret Manager; never log it
    webhook_timeout_s: float = 10.0
    webhook_min_confidence: float | None = None  # default: the model card's review_low
    send_empty: bool = False
    crop_uri_mode: Literal["source"] = "source"

    # --- batches ---
    batch_size: int = Field(100, ge=1)

    # --- misc ---
    log_level: str = "INFO"
    source_url: str = "https://github.com/sergtello/condorin-detection"


@lru_cache
def get_settings() -> Settings:
    return Settings()
