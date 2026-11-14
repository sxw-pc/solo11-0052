"""Archive export, manifest and tamper-detection tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sample_attest.archive import ArchiveError, export_task, verify_archive
from sample_attest.engine import run_plan
from sample_attest.ledger import Ledger

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "plans" / "stratified_basic.yaml"
NOW = "2026-01-02T00:00:00Z"


@pytest.fixture
def task_setup(tmp_path):
    run = run_plan(
        PLAN,
        out_dir=tmp_path / "out",
        db_path=tmp_path / "ledger.db",
        clock="2026-01-01T00:00:00Z",
    )
    return {
        "tmp_path": tmp_path,
        "task_id": run.prepared.task_id,
        "ledger": Ledger(tmp_path / "ledger.db"),
        "run": run,
    }


def test_export_writes_all_files(task_setup, tmp_path):
    result = export_task(
        task_setup["ledger"],
        task_setup["task_id"],
        tmp_path / "archive",
        generated_at=NOW,
    )
    for name in ("plan.yaml", "report.json", "report.md", "sample_keys.json", "manifest.json"):
        assert (tmp_path / "archive" / name).is_file()
    assert result["files"] == ["plan.yaml", "report.json", "report.md", "sample_keys.json"]
    keys = json.loads((tmp_path / "archive" / "sample_keys.json").read_text(encoding="utf-8"))
    assert keys == task_setup["run"].sample.selected_sorted


def test_verify_valid_archive(task_setup, tmp_path):
    export_task(task_setup["ledger"], task_setup["task_id"], tmp_path / "archive", generated_at=NOW)
    result = verify_archive(tmp_path / "archive")
    assert result["status"] == "VALID"
    assert result["checked"] == 4
    assert result["errors"] == []
    assert result["task_id"] == task_setup["task_id"]


def test_manifest_fields_and_hashes_are_sorted(task_setup, tmp_path):
    export_task(task_setup["ledger"], task_setup["task_id"], tmp_path / "archive", generated_at=NOW)
    text = (tmp_path / "archive" / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(text)
    assert list(manifest) == sorted(manifest)
    assert list(manifest["files"]) == sorted(manifest["files"])
    for name, entry in manifest["files"].items():
        assert len(entry["sha256"]) == 64
        assert entry["size"] > 0
    assert manifest["generated_at"] == NOW
    assert manifest["population_fingerprint"] == task_setup["run"].prepared.dataset.population_fingerprint


def test_tampered_file_is_located(task_setup, tmp_path):
    export_task(task_setup["ledger"], task_setup["task_id"], tmp_path / "archive", generated_at=NOW)
    target = tmp_path / "archive" / "report.md"
    target.write_text(target.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8")
    result = verify_archive(tmp_path / "archive")
    assert result["status"] == "INVALID"
    assert result["errors"][0]["code"] == "ARCHIVE_HASH_MISMATCH"
    assert result["errors"][0]["path"] == "report.md"


def test_missing_file_is_located(task_setup, tmp_path):
    export_task(task_setup["ledger"], task_setup["task_id"], tmp_path / "archive", generated_at=NOW)
    (tmp_path / "archive" / "sample_keys.json").unlink()
    result = verify_archive(tmp_path / "archive")
    assert result["errors"][0]["code"] == "ARCHIVE_MISSING_FILE"
    assert result["errors"][0]["path"] == "sample_keys.json"


def test_invalid_manifest_and_absent_directory(task_setup, tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    assert verify_archive(archive)["errors"][0]["code"] == "ARCHIVE_MANIFEST_INVALID"
    absent = verify_archive(tmp_path / "absent")
    assert absent["status"] == "INVALID"
    assert absent["errors"][0]["code"] == "ARCHIVE_MANIFEST_INVALID"


def test_export_unknown_task(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    with pytest.raises(ArchiveError) as exc:
        export_task(ledger, "missing", tmp_path / "archive", generated_at=NOW)
    assert exc.value.code == "ARCHIVE_TASK_NOT_FOUND"


def test_fixed_clock_export_is_byte_identical(task_setup, tmp_path):
    export_task(task_setup["ledger"], task_setup["task_id"], tmp_path / "a", generated_at=NOW)
    export_task(task_setup["ledger"], task_setup["task_id"], tmp_path / "b", generated_at=NOW)
    for name in ("plan.yaml", "report.json", "report.md", "sample_keys.json", "manifest.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_manifest_generated_at_is_the_only_time_variant(task_setup, tmp_path):
    export_task(task_setup["ledger"], task_setup["task_id"], tmp_path / "a", generated_at=NOW)
    export_task(
        task_setup["ledger"],
        task_setup["task_id"],
        tmp_path / "b",
        generated_at="2026-02-02T00:00:00Z",
    )
    left = json.loads((tmp_path / "a" / "manifest.json").read_text(encoding="utf-8"))
    right = json.loads((tmp_path / "b" / "manifest.json").read_text(encoding="utf-8"))
    assert left["generated_at"] != right["generated_at"]
    left.pop("generated_at")
    right.pop("generated_at")
    assert left == right
