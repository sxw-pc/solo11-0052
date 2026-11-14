"""Read-only Flask API and bind-address tests."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from sample_attest import server
from sample_attest.engine import run_plan
from sample_attest.server import HOST, create_app, serve

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "plans" / "stratified_basic.yaml"


def populated_db(tmp_path):
    run = run_plan(
        PLAN,
        out_dir=tmp_path / "out",
        db_path=tmp_path / "ledger.db",
        clock="2026-01-01T00:00:00Z",
    )
    return tmp_path / "ledger.db", run.prepared.task_id


def test_healthz_read_only(tmp_path):
    app = create_app(tmp_path / "ledger.db")
    response = app.test_client().get("/healthz")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert body["read_only"] is True
    assert body["version"] == "0.1.0"


def test_tasks_list_and_detail(tmp_path):
    db, task_id = populated_db(tmp_path)
    client = create_app(db).test_client()
    tasks = client.get("/tasks").get_json()["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == task_id
    detail = client.get(f"/tasks/{task_id}")
    assert detail.status_code == 200
    body = detail.get_json()
    assert body["task_id"] == task_id
    assert body["sample_keys"]
    assert body["report"]["plan_id"] == "stratified-basic"
    assert body["run_count"] == 1


def test_task_not_found_json(tmp_path):
    response = create_app(tmp_path / "ledger.db").test_client().get("/tasks/absent")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "LEDGER_TASK_NOT_FOUND"


def test_post_is_method_not_allowed(tmp_path):
    client = create_app(tmp_path / "ledger.db").test_client()
    response = client.post("/tasks", json={"plan": "x"})
    assert response.status_code == 405
    assert response.get_json()["error"]["code"] == "SERVER_METHOD_NOT_ALLOWED"


def test_put_task_is_method_not_allowed(tmp_path):
    client = create_app(tmp_path / "ledger.db").test_client()
    assert client.put("/tasks/anything").status_code == 405
    assert client.delete("/tasks/anything").status_code == 405


def test_bind_address_is_loopback():
    assert HOST == "127.0.0.1"


def test_serve_pins_loopback_and_port(monkeypatch):
    captured = {}

    class FakeApp:
        def run(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(server, "create_app", lambda db: FakeApp())
    serve("unused.db", port=8899)
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8899
    assert captured["debug"] is False
    assert captured["use_reloader"] is False


def test_socket_is_blocked_by_test_harness():
    with pytest.raises(AssertionError):
        socket.socket()
