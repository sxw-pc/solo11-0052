"""SQLite ledger persistence and retrieval tests."""

from __future__ import annotations

import pytest

from sample_attest.ledger import Ledger, TaskNotFoundError


def report(task_id="task_0001", plan_id="plan-a", status="pass", strict=False):
    return {
        "task_id": task_id,
        "plan_id": plan_id,
        "overall_status": status,
        "generated_at": "2026-01-01T00:00:00Z",
        "dataset": {"population_fingerprint": "pop-hash"},
        "sample": {"fingerprints": {"sample_fingerprint": "sample-hash"}},
        "verification": {"strict": strict, "counts": {"pass": 1, "warn": 0, "fail": 0}},
    }


def record(ledger, **overrides):
    values = {
        "report": report(),
        "plan_yaml": "plan_id: plan-a\n",
        "sample_keys": ["subject_0002", "subject_0001"],
        "report_markdown": "# report\n",
        "created_at": "2026-01-01T00:00:00Z",
    }
    values.update(overrides)
    return ledger.record_run(**values)


def test_record_and_get_task(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    run_id = record(ledger)
    assert run_id == 1
    task = ledger.get_latest_by_task("task_0001")
    assert task["run_id"] == 1
    assert task["plan_id"] == "plan-a"
    assert task["sample_keys"] == ["subject_0002", "subject_0001"]
    assert task["report"]["dataset"]["population_fingerprint"] == "pop-hash"
    assert task["report_markdown"] == "# report\n"
    assert task["run_count"] == 1


def test_latest_run_and_run_count(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    record(ledger, sample_keys=["subject_0001"], report_markdown="# first\n")
    record(ledger, sample_keys=["subject_0002"], report_markdown="# second\n")
    task = ledger.get_latest_by_task("task_0001")
    assert task["run_id"] == 2
    assert task["sample_keys"] == ["subject_0002"]
    assert task["run_count"] == 2
    assert ledger.count_runs() == 2


def test_get_latest_by_plan(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    record(ledger, report=report(task_id="a", plan_id="same-plan"))
    record(ledger, report=report(task_id="b", plan_id="same-plan"))
    latest = ledger.get_latest_by_plan("same-plan")
    assert latest["task_id"] == "b"
    assert ledger.get_latest_by_plan("absent") is None


def test_task_not_found(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    with pytest.raises(TaskNotFoundError) as exc:
        ledger.get_latest_by_task("absent")
    assert exc.value.code == "LEDGER_TASK_NOT_FOUND"


def test_list_tasks_returns_latest_per_task_and_limits(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    record(ledger, report=report(task_id="task-a", plan_id="p1"))
    record(ledger, report=report(task_id="task-a", plan_id="p1"))
    record(ledger, report=report(task_id="task-b", plan_id="p2"))
    tasks = ledger.list_tasks()
    assert [item["task_id"] for item in tasks] == ["task-b", "task-a"]
    assert tasks[1]["run_count"] == 2
    assert len(ledger.list_tasks(limit=1)) == 1


def test_strict_flag_round_trip(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    record(
        ledger,
        report=report(status="fail", strict=True),
    )
    task = ledger.get_latest_by_task("task_0001")
    assert task["strict"] is True
    assert task["status"] == "fail"
