"""Archive export, manifest and tamper-detection tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sample_attest.archive import (
    HISTORY_NAME,
    MANIFEST_NAME,
    ArchiveError,
    _sha256,
    export_task,
    verify_archive,
)
from sample_attest.engine import run_plan
from sample_attest.fingerprint import (
    sample_fingerprint_ordered,
    sample_fingerprint_sorted,
)
from sample_attest.ledger import Ledger

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "plans" / "stratified_basic.yaml"
NOW = "2026-01-02T00:00:00Z"
HISTORY_FIELDS = {
    "run_id",
    "created_at",
    "status",
    "sample_fingerprint",
    "check_counts",
    "diff",
}
DIFF_FIELDS = {"added", "missing"}


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


def _forked_report(run, *, task_id, sample_keys, status, created_at, counts):
    report = copy.deepcopy(run.report)
    ordered = list(sample_keys)
    sorted_fp = sample_fingerprint_sorted(sample_keys)
    report["task_id"] = task_id
    report["overall_status"] = status
    report["generated_at"] = created_at
    report["sample"]["count"] = len(sample_keys)
    report["sample"]["selected_keys_ordered"] = ordered
    report["sample"]["selected_keys_sorted"] = sorted(sample_keys)
    report["sample"]["fingerprints"] = {
        "sample_fingerprint": sorted_fp,
        "sample_fingerprint_sorted": sorted_fp,
        "sample_fingerprint_ordered": sample_fingerprint_ordered(sample_keys),
    }
    report["verification"]["counts"] = counts
    return report


@pytest.fixture
def forked_setup(tmp_path):
    """Two same-seed reruns plus one seeded fork, all under one task_id."""
    first = run_plan(
        PLAN,
        out_dir=tmp_path / "out1",
        db_path=tmp_path / "ledger.db",
        clock="2026-01-01T00:00:00Z",
    )
    second = run_plan(
        PLAN,
        out_dir=tmp_path / "out2",
        db_path=tmp_path / "ledger.db",
        clock="2026-01-01T01:00:00Z",
    )
    assert first.prepared.task_id == second.prepared.task_id
    task_id = first.prepared.task_id
    ledger = Ledger(tmp_path / "ledger.db")

    original_keys = list(first.sample.selected_sorted)
    forked_keys = sorted(set(original_keys[2:]) | {"subject_fork_1", "subject_fork_2"})
    forked = _forked_report(
        first,
        task_id=task_id,
        sample_keys=forked_keys,
        status="warn",
        created_at="2026-01-01T02:00:00Z",
        counts={"pass": 3, "warn": 2, "fail": 0},
    )
    fork_run_id = ledger.record_run(
        report=forked,
        plan_yaml=first.prepared.loaded.yaml_text(),
        sample_keys=forked_keys,
        report_markdown="# forked report\n",
        created_at="2026-01-01T02:00:00Z",
    )
    return {
        "tmp_path": tmp_path,
        "task_id": task_id,
        "ledger": ledger,
        "run_ids": [first.run_id, second.run_id, fork_run_id],
        "original_keys": original_keys,
        "forked_keys": forked_keys,
        "original_fp": first.report["sample"]["fingerprints"]["sample_fingerprint"],
        "forked_fp": forked["sample"]["fingerprints"]["sample_fingerprint"],
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


def test_default_export_is_byte_identical_to_legacy_layout(task_setup, tmp_path):
    """Without the switch the archive must remain the four legacy files only."""
    export_task(
        task_setup["ledger"],
        task_setup["task_id"],
        tmp_path / "archive",
        generated_at=NOW,
    )
    names = sorted(p.name for p in (tmp_path / "archive").iterdir())
    assert names == ["manifest.json", "plan.yaml", "report.json", "report.md", "sample_keys.json"]
    manifest = json.loads((tmp_path / "archive" / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert sorted(manifest["files"]) == ["plan.yaml", "report.json", "report.md", "sample_keys.json"]
    assert HISTORY_NAME not in manifest["files"]
    result = verify_archive(tmp_path / "archive")
    assert result["status"] == "VALID"
    assert result["checked"] == 4
    assert "history" not in result


def test_export_with_history_writes_registered_history_file(forked_setup, tmp_path):
    result = export_task(
        forked_setup["ledger"],
        forked_setup["task_id"],
        tmp_path / "archive",
        generated_at=NOW,
        include_history=True,
    )
    assert result["files"] == [
        HISTORY_NAME,
        "plan.yaml",
        "report.json",
        "report.md",
        "sample_keys.json",
    ]
    history_path = tmp_path / "archive" / HISTORY_NAME
    assert history_path.is_file()
    manifest = json.loads((tmp_path / "archive" / MANIFEST_NAME).read_text(encoding="utf-8"))
    entry = manifest["files"][HISTORY_NAME]
    assert entry["sha256"] == _sha256(history_path)
    assert entry["size"] == history_path.stat().st_size


def test_history_payload_order_fields_and_diff_semantics(forked_setup, tmp_path):
    export_task(
        forked_setup["ledger"],
        forked_setup["task_id"],
        tmp_path / "archive",
        generated_at=NOW,
        include_history=True,
    )
    history = json.loads((tmp_path / "archive" / HISTORY_NAME).read_text(encoding="utf-8"))
    assert history["task_id"] == forked_setup["task_id"]
    runs = history["runs"]
    assert [run["run_id"] for run in runs] == forked_setup["run_ids"]
    assert [set(run) for run in runs] == [HISTORY_FIELDS] * len(runs)
    assert [set(run["diff"]) for run in runs] == [DIFF_FIELDS] * len(runs)
    # First run has no predecessor: empty diffs.
    assert runs[0]["diff"] == {"added": [], "missing": []}
    # Same-seed rerun: identical roster, empty diffs and identical fingerprint.
    assert runs[1]["diff"] == {"added": [], "missing": []}
    assert runs[1]["sample_fingerprint"] == runs[0]["sample_fingerprint"]
    # Seeded fork: full added/missing keys versus the previous run.
    expected_added = sorted(
        set(forked_setup["forked_keys"]) - set(forked_setup["original_keys"]),
        key=lambda key: key.encode("utf-8"),
    )
    expected_missing = sorted(
        set(forked_setup["original_keys"]) - set(forked_setup["forked_keys"]),
        key=lambda key: key.encode("utf-8"),
    )
    assert runs[2]["diff"] == {"added": expected_added, "missing": expected_missing}
    assert runs[2]["sample_fingerprint"] == forked_setup["forked_fp"]
    assert runs[2]["check_counts"] == {"pass": 3, "warn": 2, "fail": 0}
    assert runs[2]["status"] == "warn"
    assert runs[0]["check_counts"] == {"pass": 5, "warn": 0, "fail": 0}


def test_history_export_is_byte_identical_across_runs(forked_setup, tmp_path):
    export_task(
        forked_setup["ledger"],
        forked_setup["task_id"],
        tmp_path / "a",
        generated_at=NOW,
        include_history=True,
    )
    export_task(
        forked_setup["ledger"],
        forked_setup["task_id"],
        tmp_path / "b",
        generated_at=NOW,
        include_history=True,
    )
    for name in (
        "plan.yaml",
        "report.json",
        "report.md",
        "sample_keys.json",
        HISTORY_NAME,
        MANIFEST_NAME,
    ):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_verify_history_archive_reports_consistent_runs(task_setup, tmp_path):
    # A second identical run keeps the same task_id and sample fingerprint.
    run_plan(
        PLAN,
        out_dir=tmp_path / "out2",
        db_path=tmp_path / "ledger.db",
        clock="2026-01-01T01:00:00Z",
    )
    export_task(
        task_setup["ledger"],
        task_setup["task_id"],
        tmp_path / "archive",
        generated_at=NOW,
        include_history=True,
    )
    result = verify_archive(tmp_path / "archive")
    assert result["status"] == "VALID"
    assert result["checked"] == 5
    assert result["errors"] == []
    assert result["history"]["run_count"] == 2
    assert result["history"]["reproducibility"] == "CONSISTENT"
    assert result["history"]["forks"] == []


def test_verify_history_archive_locates_fingerprint_fork(forked_setup, tmp_path):
    export_task(
        forked_setup["ledger"],
        forked_setup["task_id"],
        tmp_path / "archive",
        generated_at=NOW,
        include_history=True,
    )
    result = verify_archive(tmp_path / "archive")
    # A fork is an audit finding, not archive tampering: hashes still verify.
    assert result["status"] == "VALID"
    assert result["errors"] == []
    history = result["history"]
    assert history["reproducibility"] == "FORKED"
    assert len(history["forks"]) == 1
    fork = history["forks"][0]
    assert fork["code"] == "ARCHIVE_REPRODUCIBILITY_FORK"
    assert (fork["previous_run_id"], fork["run_id"]) == tuple(
        forked_setup["run_ids"][1:]
    )
    assert fork["previous_sample_fingerprint"] == forked_setup["original_fp"]
    assert fork["sample_fingerprint"] == forked_setup["forked_fp"]
    assert sorted(history["distinct_sample_fingerprints"]) == sorted(
        [forked_setup["original_fp"], forked_setup["forked_fp"]]
    )


def test_tampered_history_file_is_hash_mismatch_not_fork(forked_setup, tmp_path):
    export_task(
        forked_setup["ledger"],
        forked_setup["task_id"],
        tmp_path / "archive",
        generated_at=NOW,
        include_history=True,
    )
    target = tmp_path / "archive" / HISTORY_NAME
    target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
    result = verify_archive(tmp_path / "archive")
    assert result["status"] == "INVALID"
    assert result["errors"][0]["code"] == "ARCHIVE_HASH_MISMATCH"
    assert result["errors"][0]["path"] == HISTORY_NAME
    assert "history" not in result


def test_missing_history_file_listed_in_manifest(forked_setup, tmp_path):
    export_task(
        forked_setup["ledger"],
        forked_setup["task_id"],
        tmp_path / "archive",
        generated_at=NOW,
        include_history=True,
    )
    (tmp_path / "archive" / HISTORY_NAME).unlink()
    result = verify_archive(tmp_path / "archive")
    assert result["status"] == "INVALID"
    assert result["errors"][0]["code"] == "ARCHIVE_MISSING_FILE"
    assert result["errors"][0]["path"] == HISTORY_NAME


def test_malformed_history_after_valid_hash(forked_setup, tmp_path):
    archive = tmp_path / "archive"
    export_task(
        forked_setup["ledger"],
        forked_setup["task_id"],
        archive,
        generated_at=NOW,
        include_history=True,
    )
    manifest_path = archive / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    (archive / HISTORY_NAME).write_text(
        json.dumps({"task_id": manifest["task_id"], "runs": []}), encoding="utf-8"
    )
    manifest["files"][HISTORY_NAME]["sha256"] = _sha256(archive / HISTORY_NAME)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = verify_archive(archive)
    assert result["status"] == "VALID"
    assert result["history"] == {
        "run_count": 0,
        "reproducibility": "CONSISTENT",
        "forks": [],
        "distinct_sample_fingerprints": [],
    }

    (archive / HISTORY_NAME).write_text(
        json.dumps({"task_id": manifest["task_id"], "runs": [{"run_id": "x"}]}),
        encoding="utf-8",
    )
    manifest["files"][HISTORY_NAME]["sha256"] = _sha256(archive / HISTORY_NAME)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = verify_archive(archive)
    assert result["status"] == "INVALID"
    assert result["errors"][0]["code"] == "ARCHIVE_HISTORY_INVALID"
    assert result["errors"][0]["path"] == HISTORY_NAME


def test_history_task_id_mismatch_is_invalid(forked_setup, tmp_path):
    archive = tmp_path / "archive"
    export_task(
        forked_setup["ledger"],
        forked_setup["task_id"],
        archive,
        generated_at=NOW,
        include_history=True,
    )
    manifest_path = archive / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    history_path = archive / HISTORY_NAME
    history = json.loads(history_path.read_text(encoding="utf-8"))
    history["task_id"] = "0" * 16
    history_path.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["files"][HISTORY_NAME]["sha256"] = _sha256(history_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = verify_archive(archive)
    assert result["status"] == "INVALID"
    assert result["errors"][0]["code"] == "ARCHIVE_HISTORY_INVALID"
