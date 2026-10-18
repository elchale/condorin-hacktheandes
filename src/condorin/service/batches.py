"""Batches of up to BATCH_SIZE (100) images: one detect task per image, a manifest, and a summary."""

from __future__ import annotations

import logging
import uuid
from collections import Counter

from condorin.core.meta import task_name
from condorin.io import storage
from condorin.notifier.delivery import failed_delivery_uri
from condorin.service.pipeline import Pipeline, canonical_uri, now_iso
from condorin.service.schemas import BatchImage, BatchRequest
from condorin.service.tasks import DetectEnqueue

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")  # cheap prefix filter; QC still checks magic bytes


class BatchTooLarge(ValueError):
    pass


class BatchService:
    def __init__(self, pipeline: Pipeline, enqueue_detect: DetectEnqueue | None) -> None:
        self.pipeline = pipeline
        self.settings = pipeline.settings
        self.enqueue_detect = enqueue_detect

    def manifest_uri(self, batch_id: str) -> str:
        return storage.join(self.settings.batches_uri_prefix, batch_id, "manifest.json")

    def _images(self, req: BatchRequest) -> list[BatchImage]:
        max_n = self.settings.batch_size
        if req.images is not None:
            images = req.images
        else:
            limit = req.limit or max_n
            if limit > max_n:
                raise BatchTooLarge(f"limit {limit} exceeds BATCH_SIZE={max_n}")
            uris = [
                u
                for u in storage.list_uris(req.prefix, limit=None)
                if u.lower().endswith(IMAGE_EXTENSIONS)
            ][:limit]
            images = [BatchImage(uri=u, options=req.options) for u in uris]
        if not images:
            raise BatchTooLarge("batch has no images")
        if len(images) > max_n:
            raise BatchTooLarge(f"{len(images)} images exceeds BATCH_SIZE={max_n}")
        return images

    def submit(self, req: BatchRequest) -> dict:
        if self.enqueue_detect is None:
            raise RuntimeError("BatchService.submit needs an enqueue function")
        images = self._images(req)
        batch_id = req.batch_id or uuid.uuid4().hex[:16]
        version = self.pipeline.card.version
        items, to_enqueue = [], []
        for i, img in enumerate(images):
            item: dict = {"uri": img.uri}
            try:
                uri = canonical_uri(img.uri)
                gen = storage.generation(uri)  # pin the bytes now: retries process the same version
            except storage.PermanentError as err:
                item.update(state="not_found", error=f"{type(err).__name__}: {err}")
                items.append(item)
                continue
            key = self.pipeline.key_for(uri, gen)
            item.update(uri=uri, generation=gen, key=key, result_uri=self.pipeline.result_uri(key))
            if storage.exists(item["result_uri"]):
                item["state"] = "skipped_existing"
            else:
                item["state"] = "enqueued"
                job = {
                    "job_id": f"{batch_id}-{i:03d}",
                    "batch_id": batch_id,
                    "image_uri": uri,
                    "generation": gen,
                    "options": img.options.model_dump(mode="json", exclude_none=True),
                }
                to_enqueue.append((job, task_name("detect", key + version)))
            items.append(item)

        manifest = {
            "batch_id": batch_id,
            "created_at": now_iso(),
            "model_version": version,
            "items": items,
        }
        storage.write_json(self.manifest_uri(batch_id), manifest)
        for job, name in to_enqueue:  # after the manifest, so GET /batches/{id} always works
            self.enqueue_detect(job, name)
        states = Counter(it["state"] for it in items)
        log.info("batch accepted", extra={"batch_id": batch_id, "fields": dict(states)})
        return {
            "batch_id": batch_id,
            "total": len(items),
            "accepted": states["enqueued"],
            "skipped_existing": states["skipped_existing"],
            "not_found": states["not_found"],
        }

    def summary(self, batch_id: str) -> dict:
        manifest = storage.read_json(self.manifest_uri(batch_id))  # NotFound → 404
        counts: Counter = Counter()
        out_items = []
        for it in manifest["items"]:
            row = {"uri": it["uri"], "state": it["state"]}
            if it["state"] == "not_found":
                counts["failed"] += 1
                out_items.append(row)
                continue
            if not storage.exists(it["result_uri"]):
                counts["pending"] += 1
                row["state"] = "pending"
                out_items.append(row)
                continue
            r = storage.read_json(it["result_uri"])
            counts["done"] += 1
            counts[r["status"]] += 1
            if r.get("decision"):
                counts[r["decision"]] += 1
            if r.get("audit_sample"):
                counts["audit_sample"] += 1
            wh = r.get("webhook") or {}
            if wh.get("sent"):
                counts["webhook_sent"] += 1
                prefix = self.settings.failed_deliveries_uri_prefix
                if prefix and storage.exists(failed_delivery_uri(prefix, r["idempotency_key"])):
                    counts["webhook_failed"] += 1
            row.update(state="done", status=r["status"], decision=r.get("decision"),
                       score=r.get("score"), result_uri=it["result_uri"], webhook=wh)  # fmt: skip
            out_items.append(row)
        keys = ("done", "pending", "ok", "rejected_qc", "failed", "detected", "needs_review",
                "clear", "audit_sample", "webhook_sent", "webhook_failed")  # fmt: skip
        return {
            "batch_id": batch_id,
            "created_at": manifest["created_at"],
            "model_version": manifest["model_version"],
            "total": len(manifest["items"]),
            "complete": counts["pending"] == 0,
            "counts": {k: counts[k] for k in keys},
            "items": out_items,
        }
