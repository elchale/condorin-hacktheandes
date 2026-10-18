"""Cloud Run service `condorin-detector-trigger`: `POST /procesar {"prefix": "yaguas/2026-10-18"}`.

Validates the prefix, counts the images under it, starts an execution of the Cloud Run Job
`condorin-detector` with `PREFIX` as a container override and a task count sized to the prefix
(`run.jobs.runWithOverrides`), and answers 202 with the execution name. It never waits for the Job.

Each task processes every N-th image within its own timeout, so a large prefix is spread over
ceil(images / IMAGES_PER_TASK) tasks (at most MAX_TASKS) instead of timing out in one.

Authentication is Cloud Run IAM (deployed with --no-allow-unauthenticated): only principals with
roles/run.invoker on this service reach the app.
"""

from __future__ import annotations

import logging
import math
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
    check_prefix: bool = (
        True  # count the images (404 when none); off: one task unless `tasks` is given
    )
    image_suffixes: tuple[str, ...] = (".jpg", ".jpeg", ".png")  # same filter as the Job
    # Images one task can process within the Job's task timeout. Set it from scripts/benchmark.py:
    # (task timeout - margin) / seconds per image. 200 assumes ~15 s per image in a 1 h task.
    images_per_task: int = Field(200, ge=1)
    max_tasks: int = Field(10, ge=1)  # each task is a 4 vCPU instance; also bounds backend load
    log_level: str = "INFO"

    @property
    def job_path(self) -> str:
        return f"projects/{self.gcp_project}/locations/{self.gcp_region}/jobs/{self.job_name}"


@lru_cache
def get_settings() -> TriggerSettings:
    return TriggerSettings()


class ProcesarRequest(BaseModel):
    prefix: str = Field(min_length=1, max_length=512)
    tasks: int | None = Field(None, ge=1)  # optional: override the computed task count

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


def count_images(bucket: str, prefix: str, suffixes: tuple[str, ...]) -> int:
    """Images under the prefix, with the Job's suffix filter (crops/ is never a valid prefix)."""
    from google.cloud import storage

    blobs = storage.Client().list_blobs(bucket, prefix=prefix, fields="items(name),nextPageToken")
    return sum(1 for b in blobs if b.name.lower().endswith(suffixes))


def task_count(images: int, settings: TriggerSettings) -> int:
    return min(max(math.ceil(images / settings.images_per_task), 1), settings.max_tasks)


def run_job(settings: TriggerSettings, prefix: str, tasks: int) -> dict:
    """POST .../jobs/{job}:run with PREFIX and taskCount overrides. Returns the long-running op."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    body = {
        "overrides": {
            "containerOverrides": [{"env": [{"name": "PREFIX", "value": prefix}]}],
            "taskCount": tasks,
        }
    }
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
        images = None
        if settings.check_prefix:
            images = count_images(settings.input_bucket, prefix, settings.image_suffixes)
            if not images:
                raise HTTPException(404, f"no images under gs://{settings.input_bucket}/{prefix}")
        if req.tasks is not None and req.tasks > settings.max_tasks:
            raise HTTPException(422, f"tasks must be <= {settings.max_tasks}")
        tasks = req.tasks or (task_count(images, settings) if images else 1)
        if images and images > tasks * settings.images_per_task:
            log.warning("more images than the tasks can process in one run; re-run the prefix",
                        extra={"fields": {"prefix": prefix, "images": images, "tasks": tasks}})  # fmt: skip
        try:
            op = run_job(settings, prefix, tasks)
        except Exception as err:
            log.exception("could not start the job", extra={"fields": {"prefix": prefix}})
            raise HTTPException(502, "could not start the detector job") from err
        execution = (op.get("metadata") or {}).get("name") or op.get("name")
        log.info("job started", extra={"fields": {"prefix": prefix, "execution": execution,
                                                  "images": images, "tasks": tasks}})  # fmt: skip
        return {
            "execution": execution,
            "job": settings.job_name,
            "prefix": prefix,
            "bucket": settings.input_bucket,
            "images": images,
            "tasks": tasks,
        }

    return app


app = create_app()
