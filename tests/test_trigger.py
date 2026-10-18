from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient

from condorin.trigger import app as trigger


@pytest.fixture
def client(monkeypatch):
    calls = {"run": [], "count": [], "images": 450}

    def fake_count(bucket, prefix, suffixes):
        calls["count"].append((bucket, prefix, suffixes))
        return 0 if prefix == "yaguas/1999-01-01" else calls["images"]

    def fake_run(settings, prefix, tasks):
        calls["run"].append((settings.job_path, prefix, tasks))
        return {
            "name": "projects/p/locations/us-central1/operations/op-1",
            "metadata": {
                "name": "projects/p/locations/us-central1/jobs/condorin-detector/executions/condorin-detector-abc"
            },
        }

    monkeypatch.setattr(trigger, "count_images", fake_count)
    monkeypatch.setattr(trigger, "run_job", fake_run)
    return TestClient(trigger.app), calls


def test_procesar_starts_job_with_prefix(client):
    c, calls = client
    r = c.post("/procesar", json={"prefix": "yaguas/2026-10-18"})
    assert r.status_code == 202
    assert r.json()["execution"].endswith("/executions/condorin-detector-abc")
    assert r.json()["prefix"] == "yaguas/2026-10-18"
    path, prefix, tasks = calls["run"][0]
    assert path == "projects/wisecai-consultor-prod/locations/us-central1/jobs/condorin-detector"
    assert prefix == "yaguas/2026-10-18"
    assert tasks == 3 and r.json()["images"] == 450 and r.json()["tasks"] == 3  # 450 / 200 per task
    assert calls["count"][0][2] == (".jpg", ".jpeg", ".png")


def test_procesar_accepts_full_gs_uri(client):
    c, calls = client
    r = c.post("/procesar", json={"prefix": "gs://river-images/yaguas/2026-10-18T0645Z_s1.jpeg"})
    assert r.status_code == 202 and calls["run"][0][1] == "yaguas/2026-10-18T0645Z_s1.jpeg"


@pytest.mark.parametrize(
    "prefix",
    ["", "../etc", "yaguas/../x", "crops/yaguas", "Yaguas/2026", "yaguas/a b", "gs://other/yaguas"],
)
def test_procesar_rejects_bad_prefixes(client, prefix):
    c, calls = client
    assert c.post("/procesar", json={"prefix": prefix}).status_code == 422
    assert calls["run"] == []


def test_procesar_404_on_empty_prefix(client):
    c, calls = client
    assert c.post("/procesar", json={"prefix": "yaguas/1999-01-01"}).status_code == 404
    assert calls["run"] == []


def test_procesar_502_when_job_cannot_start(client, monkeypatch):
    c, _ = client

    def boom(settings, prefix, tasks):
        raise RuntimeError("Cloud Run API answered 403")

    monkeypatch.setattr(trigger, "run_job", boom)
    r = c.post("/procesar", json={"prefix": "yaguas/2026-10-18"})
    assert r.status_code == 502 and "403" not in r.text


def test_health(client):
    c, _ = client
    assert c.get("/health").json() == {"ok": True}
    assert c.get("/healthz").status_code == 404  # reserved by Cloud Run; must not be relied on


@pytest.mark.parametrize("images,tasks", [(1, 1), (200, 1), (201, 2), (1999, 10), (50_000, 10)])
def test_task_count_is_sized_to_the_prefix(images, tasks):
    assert trigger.task_count(images, trigger.TriggerSettings()) == tasks


def test_procesar_explicit_tasks(client):
    c, calls = client
    r = c.post("/procesar", json={"prefix": "yaguas/2026-10-18", "tasks": 4})
    assert r.status_code == 202 and calls["run"][0][2] == 4
    assert c.post("/procesar", json={"prefix": "yaguas/2026-10-18", "tasks": 11}).status_code == 422
    assert c.post("/procesar", json={"prefix": "yaguas/2026-10-18", "tasks": 0}).status_code == 422


def test_run_job_sends_prefix_and_task_count(monkeypatch):
    sent = {}

    class FakeSession:
        def __init__(self, creds):
            pass

        def post(self, url, json, timeout):
            sent.update(url=url, body=json)
            return types.SimpleNamespace(status_code=200, json=lambda: {"name": "op"})

    import google.auth
    import google.auth.transport.requests

    monkeypatch.setattr(google.auth, "default", lambda scopes: (object(), "p"))
    monkeypatch.setattr(google.auth.transport.requests, "AuthorizedSession", FakeSession)
    assert trigger.run_job(trigger.TriggerSettings(), "yaguas/2026-10-18", 3) == {"name": "op"}
    assert sent["url"].endswith("/jobs/condorin-detector:run")
    assert sent["body"] == {"overrides": {
        "containerOverrides": [{"env": [{"name": "PREFIX", "value": "yaguas/2026-10-18"}]}],
        "taskCount": 3}}  # fmt: skip
