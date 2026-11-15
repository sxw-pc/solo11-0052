"""CLI subcommands, exit codes and end-to-end flows."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from sample_attest.cli import main

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "plans" / "stratified_basic.yaml"
NOW = "2026-01-01T00:00:00Z"


def parse_json(text):
    return json.loads(text)


def run_basic(tmp_path):
    db = tmp_path / "ledger.db"
    out = tmp_path / "out"
    code = main(["run", "--plan", str(PLAN), "--out", str(out), "--db", str(db), "--now", NOW])
    return code, db, out


def test_run_success_writes_reports_and_ledger(tmp_path, capsys):
    code, db, out = run_basic(tmp_path)
    captured = capsys.readouterr()
    summary = parse_json(captured.out)
    assert code == 0
    assert summary["ok"] is True
    assert summary["status"] == "pass"
    assert summary["sample_count"] == 18
    assert (out / "report.json").is_file()
    assert (out / "report.md").is_file()
    assert db.is_file()


def test_run_strict_warning_exit_code(yaml_plan, tmp_path, capsys):
    data = {
        "plan_id": "strict-warning",
        "dataset": {"path": str(ROOT / "fixtures" / "population_small.csv"), "format": "csv"},
        "key_field": "subject_id",
        "mode": "random",
        "seed": 4,
        "size": 40,
        "checks": [{"id": "u", "type": "key_unique"}],
    }
    plan = yaml_plan("strict.yaml", data)
    code = main(
        [
            "run", "--plan", str(plan), "--out", str(tmp_path / "out"),
            "--db", str(tmp_path / "db"), "--strict", "--now", NOW,
        ]
    )
    summary = parse_json(capsys.readouterr().out)
    assert code == 3
    assert summary["strict_failed"] is True
    assert summary["status"] == "fail"


def test_verify_reproducible(tmp_path, capsys):
    code, db, _ = run_basic(tmp_path)
    capsys.readouterr()
    code = main(["verify", "--plan", str(PLAN), "--db", str(db)])
    output = capsys.readouterr().out
    assert code == 0
    assert output.splitlines()[0] == "REPRODUCIBLE"
    payload = parse_json("\n".join(output.splitlines()[1:]))
    assert payload["diff"]["added_count"] == 0


def test_verify_without_baseline(tmp_path, capsys):
    code = main(
        ["verify", "--plan", str(PLAN), "--db", str(tmp_path / "empty.db")]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "VERIFY_NO_BASELINE" in captured.err


def test_verify_detects_seed_change(yaml_plan, tmp_path, capsys):
    data = {
        "plan_id": "seed-change",
        "dataset": {"path": str(ROOT / "fixtures" / "population_small.csv"), "format": "csv"},
        "key_field": "subject_id",
        "mode": "random",
        "seed": 1,
        "size": 7,
        "checks": [{"id": "u", "type": "key_unique"}],
    }
    plan = yaml_plan("seed.yaml", data)
    db = tmp_path / "ledger.db"
    assert main(["run", "--plan", str(plan), "--out", str(tmp_path / "out"), "--db", str(db), "--now", NOW]) == 0
    capsys.readouterr()
    changed = dict(data, seed=2)
    plan.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")
    code = main(["verify", "--plan", str(plan), "--db", str(db)])
    output = capsys.readouterr().out
    assert code == 4
    assert output.splitlines()[0] == "NOT_REPRODUCIBLE"
    payload = parse_json("\n".join(output.splitlines()[1:]))
    assert payload["diff_explanations"]
    assert payload["diff"]["added_count"] > 0
    assert payload["sample_fingerprint"] != payload["baseline_sample_fingerprint"]


def test_run_plan_validation_error(yaml_plan, tmp_path, capsys):
    data = {
        "plan_id": "bad",
        "dataset": {"path": "x.csv", "format": "csv"},
        "key_field": "subject_id",
        "mode": "random",
        "seed": 1,
        "size": 2,
        "checks": [],
    }
    plan = yaml_plan("invalid.yaml", data)
    code = main(["run", "--plan", str(plan), "--out", str(tmp_path / "out"), "--db", str(tmp_path / "db")])
    captured = capsys.readouterr()
    assert code == 2
    assert "PLAN_INVALID" in captured.err


def test_export_and_verify_archive_commands(tmp_path, capsys):
    code, db, _ = run_basic(tmp_path)
    capsys.readouterr()
    payload = None
    code = main(
        ["run", "--plan", str(PLAN), "--out", str(tmp_path / "out2"), "--db", str(db), "--now", NOW]
    )
    payload = parse_json(capsys.readouterr().out)
    task_id = payload["task_id"]
    archive = tmp_path / "archive"
    assert main(
        ["export", "--task", task_id, "--out", str(archive), "--db", str(db), "--now", NOW]
    ) == 0
    capsys.readouterr()
    assert main(["verify-archive", "--dir", str(archive)]) == 0
    result = parse_json(capsys.readouterr().out)
    assert result["status"] == "VALID"


def test_verify_archive_tamper_exit_code(tmp_path, capsys):
    _, db, _ = run_basic(tmp_path)
    payload = parse_json(capsys.readouterr().out)
    archive = tmp_path / "archive"
    assert main(
        ["export", "--task", payload["task_id"], "--out", str(archive), "--db", str(db), "--now", NOW]
    ) == 0
    capsys.readouterr()
    (archive / "report.json").write_text("{}", encoding="utf-8")
    assert main(["verify-archive", "--dir", str(archive)]) == 5
    result = parse_json(capsys.readouterr().out)
    assert result["errors"][0]["code"] == "ARCHIVE_HASH_MISMATCH"


def test_run_cluster_substrata_plan_reports_cluster_short_and_metadata(tmp_path, capsys):
    plan = ROOT / "plans" / "cluster_substrata.yaml"
    code = main(
        [
            "run", "--plan", str(plan), "--out", str(tmp_path / "out"),
            "--db", str(tmp_path / "db"), "--now", NOW,
        ]
    )
    summary = parse_json(capsys.readouterr().out)
    assert code == 0
    assert summary["status"] == "warn"
    assert summary["sample_count"] == 24
    report = parse_json((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    metadata = report["sample"]["metadata"]
    # Cluster boundary is untouched by within-cluster allocation.
    assert metadata["cluster_boundary_size"] == 24
    assert metadata["target_size"] == 24
    assert len(metadata["selected_clusters"]) == 4
    # Per-cluster row count, allocation target and achieved layers are recorded.
    for cluster_id in metadata["selected_clusters"]:
        record = metadata["cluster_allocations"][cluster_id]
        assert record["cluster_size"] == 6
        assert record["allocation_target"] == 6
        assert set(record["achieved"]) == {
            "segment_low",
            "segment_mid",
            "segment_high",
        }
        assert sum(record["achieved"].values()) == 6
    short = [
        warning
        for warning in report["sample"]["warnings"]
        if warning["code"] == "CLUSTER_QUOTA_SHORT"
    ]
    assert short
    assert short[0]["path"] == "cluster:cluster_02:segment_low"
    quota = next(
        check for check in report["verification"]["checks"] if check["type"] == "quota"
    )
    assert quota["status"] == "pass"


def test_run_cluster_substrata_plan_is_reproducible(tmp_path, capsys):
    plan = ROOT / "plans" / "cluster_substrata.yaml"
    db = tmp_path / "db"
    first = main(
        ["run", "--plan", str(plan), "--out", str(tmp_path / "out"), "--db", str(db), "--now", NOW]
    )
    capsys.readouterr()
    assert first == 0
    assert main(["verify", "--plan", str(plan), "--db", str(db)]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "REPRODUCIBLE"
