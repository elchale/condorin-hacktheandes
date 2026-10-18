"""Cloud Tasks enqueueing (deterministic task names → idempotent enqueue) and the webhook enqueuer
with its dev modes (`direct`, `log`)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import httpx

from condorin.config import Settings
from condorin.core.meta import task_name
from condorin.io.storage import Transient

log = logging.getLogger(__name__)


class CloudTasks:
    """Thin wrapper around google-cloud-tasks: HTTP POST task with an OIDC token (roles/run.invoker)."""

    def __init__(self, settings: Settings) -> None:
        if not settings.gcp_project:
            raise RuntimeError("GCP_PROJECT is required for Cloud Tasks mode")
        if not settings.tasks_sa_email:
            raise RuntimeError("TASKS_SA_EMAIL is required for Cloud Tasks mode (OIDC token)")
        from google.cloud import tasks_v2

        self._tasks_v2 = tasks_v2
        self.client = tasks_v2.CloudTasksClient()
        self.settings = settings

    def create_http_task(self, queue: str, name: str, base_url: str, path: str, body: dict) -> bool:
        """Create the task. Returns False if a task with that name already exists (= success)."""
        from google.api_core import exceptions as gexc
        from google.protobuf import duration_pb2

        s = self.settings
        parent = self.client.queue_path(s.gcp_project, s.gcp_region, queue)
        task = {
            "name": f"{parent}/tasks/{name}",
            "http_request": {
                "http_method": self._tasks_v2.HttpMethod.POST,
                "url": base_url.rstrip("/") + path,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode(),
                # audience = the Cloud Run service URL (VERIFY against the Cloud Run auth docs)
                "oidc_token": {"service_account_email": s.tasks_sa_email, "audience": base_url},
            },
            # VERIFY: Cloud Tasks caps the HTTP dispatch deadline (30 min at the time of writing)
            "dispatch_deadline": duration_pb2.Duration(seconds=s.task_dispatch_deadline_s),
        }
        try:
            self.client.create_task(parent=parent, task=task)
            return True
        except gexc.AlreadyExists:
            return False
        except gexc.GoogleAPICallError as err:
            raise Transient(f"create_task {name}: {err}") from err


class WebhookEnqueuer:
    """Turns a webhook event into a Cloud Task (prod), an in-process delivery, or a log line."""

    def __init__(self, settings: Settings, tasks: CloudTasks | None = None) -> None:
        self.settings = settings
        self.mode = settings.webhook_mode
        self._tasks = tasks
        self._client: httpx.Client | None = None
        self.events: list[dict] = []  # last events (log/direct modes): handy in dev and tests
        if self.mode == "tasks" and not settings.notifier_url:
            raise RuntimeError("NOTIFIER_URL is required when WEBHOOK_MODE=tasks")

    @property
    def tasks(self) -> CloudTasks:
        if self._tasks is None:
            self._tasks = CloudTasks(self.settings)
        return self._tasks

    def task_name_for(self, event: dict) -> str:
        return task_name("deliver", event["idempotency_key"] + (event.get("model_version") or ""))

    def enqueue(self, event: dict) -> str:
        name = self.task_name_for(event)
        ctx = {"idempotency_key": event["idempotency_key"], "fields": {"task": name}}
        if self.mode == "tasks":
            created = self.tasks.create_http_task(
                self.settings.webhook_queue, name, self.settings.notifier_url, "/deliver",
                {"event": event},
            )  # fmt: skip
            log.info("webhook task " + ("enqueued" if created else "already exists"), extra=ctx)
            return "enqueued" if created else "duplicate"

        self.events.append(event)
        del self.events[:-100]
        if self.mode == "log":
            log.info("webhook event (WEBHOOK_MODE=log)", extra={**ctx, "fields": {"event": event}})
            return "logged"

        # direct: deliver in-process (dev only; no retries)
        from condorin.notifier.delivery import USER_AGENT, deliver

        s = self.settings
        if not s.webhook_url or s.webhook_token is None:
            log.error("WEBHOOK_MODE=direct needs WEBHOOK_URL and WEBHOOK_TOKEN", extra=ctx)
            return "not_configured"
        if self._client is None:
            self._client = httpx.Client(headers={"User-Agent": USER_AGENT})
        outcome = deliver(
            event,
            url=s.webhook_url,
            token=s.webhook_token.get_secret_value(),
            client=self._client,
            failed_prefix=s.failed_deliveries_uri_prefix,
            timeout=s.webhook_timeout_s,
        )
        return outcome.result


DetectEnqueue = Callable[[dict, str], bool]  # (job body, task name) -> created?


def cloud_tasks_detect_enqueue(settings: Settings, tasks: CloudTasks) -> DetectEnqueue:
    if not settings.detector_url:
        raise RuntimeError("DETECTOR_URL is required when DETECT_MODE=tasks")

    def enqueue(job: dict, name: str) -> bool:
        return tasks.create_http_task(
            settings.detect_queue, name, settings.detector_url, "/detect", job
        )

    return enqueue
