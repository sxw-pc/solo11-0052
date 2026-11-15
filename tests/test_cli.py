"""CLI subcommands, exit codes and end-to-end flows."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from sample_attest.cli import main

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "plans" / "stratified_basic.yaml"
SUBJECT_PLAN = ROOT / "plans" / "stratified_subject_basic.yaml"
SUBJECT_SHORT_PLAN = ROOT / "plans" / "stratified_subject_short.yaml"
SUBJECT_SEED2_PLAN = ROOT / "plans" / "stratified_subject_seed2.yaml"
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


def test_subject_plan_dedupes_and_matches_quotas(tmp_path, capsys):
    db = tmp_path / "subject.db"
    out = tmp_path / "out"
    code = main(["run", "--plan", str(SUBJECT_PLAN), "--out", str(out),
                 "--db", str(db), "--now", NOW])
    summary = parse_json(capsys.readouterr().out)
    assert code == 0
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    metadata = report["sample"]["metadata"]
    assert metadata["subject_count"] == 11
    assert metadata["subject_rows"] == 15
    assert report["sample"]["count"] == 9
    assert sum(metadata["quotas"].values()) == report["sample"]["count"]
    # selected keys are attribution rows, one per distinct subject
    fixture = (ROOT / "fixtures" / "population_subjects.csv").read_text(encoding="utf-8")
    import csv as csv_module
    rows = list(csv_module.DictReader(fixture.splitlines()))
    key_to_subject = {row["record_id"]: row["subject_id"] for row in rows}
    selected = report["sample"]["selected_keys_sorted"]
    subjects = [key_to_subject[key] for key in selected]
    assert len(subjects) == len(set(subjects))
    assert summary["sample_fingerprint"] == report["sample"]["fingerprints"]["sample_fingerprint"]


def test_subject_plan_quota_short_reports_real_gap(tmp_path, capsys):
    db = tmp_path / "short.db"
    out = tmp_path / "out-short"
    code = main(["run", "--plan", str(SUBJECT_SHORT_PLAN), "--out", str(out),
                 "--db", str(db), "--now", NOW])
    assert code == 1
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    short = [w for w in report["sample"]["warnings"] if w["code"] == "STRATUM_QUOTA_SHORT"]
    assert len(short) == 1 and short[0]["gap"] == 1
    assert report["sample"]["count"] == 11
    assert sum(report["sample"]["metadata"]["quotas"].values()) == 11
    gaps = [e["gap"] for e in report["explanations"] if e.get("gap") is not None]
    assert gaps and all(gap == 1 for gap in gaps)


def test_subject_plan_seed_change_changes_fingerprint(tmp_path, capsys):
    db = tmp_path / "seed.db"
    first_out = tmp_path / "out1"
    second_out = tmp_path / "out2"
    assert main(["run", "--plan", str(SUBJECT_PLAN), "--out", str(first_out),
                 "--db", str(db), "--now", NOW]) == 0
    capsys.readouterr()
    assert main(["run", "--plan", str(SUBJECT_SEED2_PLAN), "--out", str(second_out),
                 "--db", str(db), "--now", NOW]) == 0
    capsys.readouterr()
    first = json.loads((first_out / "report.json").read_text(encoding="utf-8"))
    second = json.loads((second_out / "report.json").read_text(encoding="utf-8"))
    fp_one = first["sample"]["fingerprints"]["sample_fingerprint"]
    fp_two = second["sample"]["fingerprints"]["sample_fingerprint"]
    assert fp_one != fp_two
    assert first["sample"]["selected_keys_sorted"] != second["sample"]["selected_keys_sorted"]
    # same seed rerun stays reproducible
    rerun_out = tmp_path / "out3"
    assert main(["run", "--plan", str(SUBJECT_PLAN), "--out", str(rerun_out),
                 "--db", str(db), "--now", NOW]) == 0
    capsys.readouterr()
    rerun = json.loads((rerun_out / "report.json").read_text(encoding="utf-8"))
    assert rerun["sample"]["fingerprints"]["sample_fingerprint"] == fp_one
