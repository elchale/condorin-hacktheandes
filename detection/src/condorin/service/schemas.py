"""Request/response contracts: detect job (Cloud Tasks body and Pub/Sub push envelope), batches,
the internal `result.json` (Appendix B2) and the Django webhook payload (Appendix B1)."""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1


# --- jobs ---------------------------------------------------------------------------------------


class Bounds(BaseModel):
    sw: tuple[float, float]  # [lat, lon]
    ne: tuple[float, float]


class JobOptions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    return_overlay: bool = True
    gsd_m: float | None = None
    river: str | None = None
    satellite: str | None = None
    captured_at: str | None = None
    bounds: Bounds | None = None

    def meta_overrides(self) -> dict:
        return self.model_dump(
            include={"river", "satellite", "captured_at", "bounds"}, exclude_none=True
        )


class DetectJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    batch_id: str | None = None
    image_uri: str = Field(min_length=1)
    generation: str | None = None
    options: JobOptions = JobOptions()

    @field_validator("generation", mode="before")
    @classmethod
    def _gen_str(cls, v: Any) -> str | None:
        return None if v in (None, "") else str(v)


def parse_detect_body(body: Any) -> DetectJob:
    """Accept a Cloud Tasks job body, a Pub/Sub push envelope (data = job JSON or a GCS object
    notification) or a bare GCS object resource (`bucket` + `name`, e.g. an Eventarc event body)."""
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    if "message" in body and isinstance(body["message"], dict):
        msg = body["message"]
        attrs = msg.get("attributes") or {}
        raw = msg.get("data")
        data = json.loads(base64.b64decode(raw)) if raw else {}
        if not isinstance(data, dict):
            raise ValueError("Pub/Sub message data must be a JSON object")
        job_id = msg.get("messageId") or msg.get("message_id")
        if "image_uri" in data:
            return DetectJob.model_validate({"job_id": job_id, **data} if job_id else data)
        if "bucket" in data and "name" in data:
            return _from_gcs_object(data["bucket"], data["name"], data.get("generation"), job_id)
        if "bucketId" in attrs and "objectId" in attrs:
            return _from_gcs_object(
                attrs["bucketId"], attrs["objectId"], attrs.get("objectGeneration"), job_id
            )
        raise ValueError("Pub/Sub message has no image_uri and no GCS object")
    if "image_uri" not in body and "bucket" in body and "name" in body:
        return _from_gcs_object(body["bucket"], body["name"], body.get("generation"), None)
    return DetectJob.model_validate(body)


def _from_gcs_object(bucket: str, name: str, generation: Any, job_id: str | None) -> DetectJob:
    data: dict = {"image_uri": f"gs://{bucket}/{name}", "generation": generation}
    if job_id:
        data["job_id"] = job_id
    return DetectJob.model_validate(data)


# --- batches ------------------------------------------------------------------------------------


class BatchImage(BaseModel):
    uri: str = Field(min_length=1)
    options: JobOptions = JobOptions()


class BatchRequest(BaseModel):
    batch_id: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    images: list[BatchImage] | None = None
    prefix: str | None = None
    limit: int | None = Field(None, ge=1)
    options: JobOptions = JobOptions()  # applied to every image of a `prefix` batch

    @model_validator(mode="after")
    def _one_source(self) -> BatchRequest:
        if (self.images is None) == (self.prefix is None):
            raise ValueError("give exactly one of `images` or `prefix`")
        return self


# --- result.json (Appendix B2) ------------------------------------------------------------------


class ResultImage(BaseModel):
    bucket: str
    object: str
    generation: str
    width: int | None = None
    height: int | None = None
    river: str | None = None
    satellite: str | None = None
    captured_at: str | None = None
    bounds: dict | None = None


class ResultModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    name: str
    version: str
    thresholds: dict


class ResultDetection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    cls: str = Field(alias="class")
    confidence: float
    bbox_xyxy: list[float]
    lat: float | None = None
    lon: float | None = None


class ResultQC(BaseModel):
    passed: bool
    reasons: list[str] = []
    truncated_lost_fraction: float = 0.0
    gsd_checked: bool = False
    checks: dict = {}


class WebhookStatus(BaseModel):
    sent: bool = False
    reason: str | None = None
    task: str | None = None


class Result(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    schema_version: Literal[1] = SCHEMA_VERSION
    job_id: str
    batch_id: str | None = None
    created_at: str
    idempotency_key: str
    result_key: str
    image_uri: str
    image: ResultImage
    model: ResultModel
    status: Literal["ok", "rejected_qc", "failed"]
    qc: ResultQC | None = None
    decision: Literal["detected", "needs_review", "clear"] | None = None
    score: float | None = None
    positive_class: str
    audit_sample: bool = False
    detections: list[ResultDetection] = []
    artifacts: dict = {}
    webhook: WebhookStatus = WebhookStatus()
    timings_ms: dict = {}
    error: str | None = None

    def dump(self) -> dict:
        return self.model_dump(by_alias=True, mode="json")


# --- webhook payload (Appendix B1, fixed by the Django team) ------------------------------------


class WebhookImage(BaseModel):
    bucket: str
    object: str
    generation: str
    river: str | None
    satellite: str | None
    captured_at: str | None


class WebhookModel(BaseModel):
    name: str
    version: str


class WebhookDetection(BaseModel):
    lat: float | None
    lon: float | None
    confidence: float
    bbox: list[int] = Field(min_length=4, max_length=4)  # [x, y, w, h], top-left origin, px
    crop_uri: str


class WebhookPayload(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    image: WebhookImage
    model: WebhookModel
    detections: list[WebhookDetection]


class WebhookEvent(BaseModel):
    """Body of a webhook Cloud Task: `{"event": {...}}` posted to the notifier's /deliver."""

    idempotency_key: str = Field(min_length=1)
    payload: WebhookPayload
    model_version: str | None = None
    result_uri: str | None = None
