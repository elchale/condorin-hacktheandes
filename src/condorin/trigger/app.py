"""Cloud Run service `condorin-detector-trigger`: `POST /procesar {"prefix": "yaguas/2026-10-18"}`.

Validates the prefix, checks that it has at least one object, starts an execution of the Cloud Run
Job `condorin-detector` with `PREFIX` as a container override (`run.jobs.runWithOverrides`) and
answers 202 with the execution name. It never waits for the Job.

Authentication is Cloud Run IAM (deployed with --no-allow-unauthenticated): only principals with
roles/run.invoker on this service reach the app.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from condorin.logs import setup_logging

log = logging.getLogger(__name__)

RUN_API = "https://run.googleapis.com/v2"
# <river slug>/<anything a scene name uses>; the first segment is the river.
_PREFIX = re.compile(r"^[a-z0-9][a-z0-9_-]*(/[A-Za-z0-9_.:+-]*)*$")


class TriggerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    gcp_project: str = "wisecai-consultor-prod"
    gcp_region: str = "us-central1"
    job_name: str = "condorin-detector"
    input_bucket: str = "river-images"
    crops_prefix: str = "crops"
    check_prefix: bool = True  # 404 when the prefix has no objects
    log_level: str = "INFO"

    @property
    def job_path(self) -> str:
        return f"projects/{self.gcp_project}/locations/{self.gcp_region}/jobs/{self.job_name}"


@lru_cache
def get_settings() -> TriggerSettings:
    return TriggerSettings()


class ProcesarRequest(BaseModel):
    prefix: str = Field(min_length=1, max_length=512)

    @field_validator("prefix")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = v.strip()
        bucket = get_settings().input_bucket
        for head in (f"gs://{bucket}/", "/"):
            if v.startswith(head):
                v = v[len(head) :]
        if ".." in v or not _PREFIX.match(v):
            raise ValueError(
                "prefix must look like <river>/<YYYY-MM-DD>... (e.g. yaguas/2026-10-18)"
            )
        if v.split("/", 1)[0] == get_settings().crops_prefix:
            raise ValueError("the crops folder is not processed")
        return v


def prefix_has_objects(bucket: str, prefix: str) -> bool:
    from google.cloud import storage

    blobs = storage.Client().list_blobs(bucket, prefix=prefix, max_results=1)
    return any(True for _ in blobs)


def run_job(settings: TriggerSettings, prefix: str) -> dict:
    """POST .../jobs/{job}:run with a PREFIX env override. Returns the long-running operation."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    body = {"overrides": {"containerOverrides": [{"env": [{"name": "PREFIX", "value": prefix}]}]}}
    resp = AuthorizedSession(creds).post(
        f"{RUN_API}/{settings.job_path}:run", json=body, timeout=30
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Cloud Run API answered {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(title="condorin-detector-trigger", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.post("/procesar", status_code=202)
    def procesar(req: ProcesarRequest) -> dict:
        prefix = req.prefix
        if settings.check_prefix and not prefix_has_objects(settings.input_bucket, prefix):
            raise HTTPException(404, f"no objects under gs://{settings.input_bucket}/{prefix}")
        try:
            op = run_job(settings, prefix)
        except Exception as err:
            log.exception("could not start the job", extra={"fields": {"prefix": prefix}})
            raise HTTPException(502, "could not start the detector job") from err
        execution = (op.get("metadata") or {}).get("name") or op.get("name")
        log.info("job started", extra={"fields": {"prefix": prefix, "execution": execution}})
        return {
            "execution": execution,
            "job": settings.job_name,
            "prefix": prefix,
            "bucket": settings.input_bucket,
        }

    return app


app = create_app()
