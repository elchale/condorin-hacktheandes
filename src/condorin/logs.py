"""Structured JSON logs in the Cloud Logging format (`severity`, `message`, plus context fields)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

CONTEXT_FIELDS = (
    "job_id",
    "batch_id",
    "idempotency_key",
    "image_uri",
    "model_version",
    "status",
    "decision",
    "score",
    "timings_ms",
    "http_status",
    "error",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "logger": record.name,
        }
        for key in CONTEXT_FIELDS:
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            entry.update(extra)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
