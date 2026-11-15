"""Stratified attribution of cross-run verify diffs (``by_strata``)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from sample_attest.cli import main
from sample_attest.engine import run_plan, verify_plan
from sample_attest.fingerprint import key_diff

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "population_stratified.csv"
SMALL = ROOT / "fixtures" / "population_small.csv"
NOW = "2026-01-01T00:00:00Z"


def write_plan(tmp_path, data):
    path = tmp_path / "plan.yaml"
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def rewrite_plan(plan_path, data, **changes):
    plan_path.write_text(
        yaml.safe_dump(dict(data, **changes), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def stratified_plan(dataset_path, seed):
    return {
        "plan_id": "strata-diff",
        "dataset": {"path": str(dataset_path), "format": "csv"},
        "key_field": "subject_id",
        "mode": "stratified",
        "seed": seed,
        "size": 18,
        "strata_field": "region",
        "expected_distribution": {"region_A": 9, "region_B": 6, "region_C": 3},
        "checks": [{"id": "u", "type": "key_unique"}],
    }


def random_plan(seed):
    return {
        "plan_id": "plain-diff",
        "dataset": {"path": str(SMALL), "format": "csv"},
        "key_field": "subject_id",
        "mode": "random",
        "seed": seed,
        "size": 7,
        "checks": [{"id": "u", "type": "key_unique"}],
    }


def expected_status(added, missing):
    if added and missing:
        return "mixed"
    if added:
        return "added"
    if missing:
        return "missing"
    return "clean"


def assert_conservation(result):
    diff = result["diff"]
    by_strata = result["by_strata"]
    assert sum(entry["added"] for entry in by_strata) == diff["added_count"]
    assert sum(entry["missing"] for entry in by_strata) == diff["missing_count"]
    for entry in by_strata:
        assert entry["status"] == expected_status(entry["added"], entry["missing"])


def test_by_strata_conservation_under_truncation(tmp_path):
    dataset = tmp_path / "population.csv"
    dataset.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    # 相对路径：基线方案副本里的 path 需相对当前方案目录解析
    data = stratified_plan("population.csv", seed=1)
    plan = write_plan(tmp_path, data)
    db = tmp_path / "ledger.db"
    run_plan(plan, out_dir=tmp_path / "out", db_path=db, clock=NOW)
    rewrite_plan(plan, data, seed=2)

    result = verify_plan(plan, db_path=db)

    assert result["status"] == "NOT_REPRODUCIBLE"
    diff = result["diff"]
    assert diff["added_count"] > 0 and diff["missing_count"] > 0
    assert "by_strata" not in diff  # by_strata 提升到顶层，与 diff 平级
    assert_conservation(result)
    # 分层统计基于完整差异集，而非被 limit 截断的展示列表
    assert diff["truncated"] is True
    shown = len(diff["added"]) + len(diff["missing"])
    assert diff["added_count"] + diff["missing_count"] > shown
    names = {entry["stratum"] for entry in result["by_strata"]}
    assert names <= {"region_A", "region_B", "region_C"}
    strata_lines = [
        line for line in result["diff_explanations"] if line.startswith("分层 ")
    ]
    assert len(strata_lines) == len(result["by_strata"])


def test_missing_keys_absent_from_dataset_are_unclassified(tmp_path):
    dataset = tmp_path / "population.csv"
    dataset.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    data = stratified_plan(str(dataset), seed=1)
    plan = write_plan(tmp_path, data)
    db = tmp_path / "ledger.db"
    outcome = run_plan(plan, out_dir=tmp_path / "out", db_path=db, clock=NOW)
    removed = set(outcome.sample.selected[:2])

    lines = dataset.read_text(encoding="utf-8").splitlines()
    kept = [lines[0]] + [
        line for line in lines[1:] if line.split(",", 1)[0] not in removed
    ]
    dataset.write_text("\n".join(kept) + "\n", encoding="utf-8")

    result = verify_plan(plan, db_path=db)

    assert result["status"] == "NOT_REPRODUCIBLE"
    entries = {entry["stratum"]: entry for entry in result["by_strata"]}
    # 基线键已不在数据集中：归入显式 unclassified，且计入守恒
    assert "unclassified" in entries
    assert entries["unclassified"]["missing"] >= len(removed)
    assert entries["unclassified"]["added"] == 0
    assert entries["unclassified"]["status"] == "missing"
    # 仍在数据集里的缺失键仍按基线分层归因
    assert any(name.startswith("region_") for name in entries)
    assert_conservation(result)


def test_no_strata_field_degrades_to_single_group(tmp_path):
    data = random_plan(seed=1)
    plan = write_plan(tmp_path, data)
    db = tmp_path / "ledger.db"
    run_plan(plan, out_dir=tmp_path / "out", db_path=db, clock=NOW)
    rewrite_plan(plan, data, seed=2)

    result = verify_plan(plan, db_path=db)

    diff = result["diff"]
    assert diff["added_count"] > 0 and diff["missing_count"] > 0
    assert len(result["by_strata"]) == 1
    entry = result["by_strata"][0]
    assert entry["stratum"] == "all"
    assert entry["added"] == diff["added_count"]
    assert entry["missing"] == diff["missing_count"]
    assert entry["status"] == "mixed"
    assert any(line.startswith("分层 all:") for line in result["diff_explanations"])


def test_reproducible_stratified_has_empty_by_strata(tmp_path):
    data = stratified_plan(str(FIXTURE), seed=1)
    plan = write_plan(tmp_path, data)
    db = tmp_path / "ledger.db"
    run_plan(plan, out_dir=tmp_path / "out", db_path=db, clock=NOW)

    result = verify_plan(plan, db_path=db)

    assert result["status"] == "REPRODUCIBLE"
    assert result["diff"]["added_count"] == 0
    assert result["diff"]["missing_count"] == 0
    assert result["by_strata"] == []
    assert result["diff_explanations"] == []


def test_reproducible_without_strata_field_reports_clean_all_group(tmp_path):
    data = random_plan(seed=1)
    plan = write_plan(tmp_path, data)
    db = tmp_path / "ledger.db"
    run_plan(plan, out_dir=tmp_path / "out", db_path=db, clock=NOW)

    result = verify_plan(plan, db_path=db)

    assert result["status"] == "REPRODUCIBLE"
    assert result["by_strata"] == [
        {"stratum": "all", "status": "clean", "added": 0, "missing": 0}
    ]


def test_cli_verify_exit_code_and_by_strata_payload(tmp_path, capsys):
    data = stratified_plan(str(FIXTURE), seed=1)
    plan = write_plan(tmp_path, data)
    db = tmp_path / "ledger.db"
    assert main(
        ["run", "--plan", str(plan), "--out", str(tmp_path / "out"),
         "--db", str(db), "--now", NOW]
    ) == 0
    capsys.readouterr()
    rewrite_plan(plan, data, seed=2)

    code = main(["verify", "--plan", str(plan), "--db", str(db)])

    output = capsys.readouterr().out
    assert code == 4
    assert output.splitlines()[0] == "NOT_REPRODUCIBLE"
    payload = json.loads("\n".join(output.splitlines()[1:]))
    assert payload["by_strata"]
    assert (
        sum(entry["added"] for entry in payload["by_strata"])
        == payload["diff"]["added_count"]
    )
    assert (
        sum(entry["missing"] for entry in payload["by_strata"])
        == payload["diff"]["missing_count"]
    )


def test_key_diff_by_strata_uses_full_sets_not_display_lists():
    baseline = [f"k{i:03d}" for i in range(30)]
    current = [f"k{i:03d}" for i in range(15, 45)]
    added_strata = {
        f"k{i:03d}": ("even" if i % 2 == 0 else "odd") for i in range(15, 45)
    }
    missing_strata = {
        f"k{i:03d}": ("even" if i % 2 == 0 else "odd") for i in range(15)
    }
    diff = key_diff(
        baseline,
        current,
        strata_field="parity",
        added_strata=added_strata,
        missing_strata=missing_strata,
    )
    assert diff["truncated"] is True
    assert len(diff["added"]) + len(diff["missing"]) == 20
    by = {entry["stratum"]: entry for entry in diff["by_strata"]}
    assert by["even"] == {"stratum": "even", "status": "mixed", "added": 8, "missing": 8}
    assert by["odd"] == {"stratum": "odd", "status": "mixed", "added": 7, "missing": 7}
    assert sum(e["added"] for e in diff["by_strata"]) == diff["added_count"] == 15
    assert sum(e["missing"] for e in diff["by_strata"]) == diff["missing_count"] == 15


def test_key_diff_unclassified_when_key_missing_from_maps():
    diff = key_diff(
        ["a", "b"],
        ["c"],
        strata_field="region",
        added_strata={},
        missing_strata={"a": "region_A"},
    )
    by = {entry["stratum"]: entry for entry in diff["by_strata"]}
    assert by["region_A"] == {
        "stratum": "region_A",
        "status": "missing",
        "added": 0,
        "missing": 1,
    }
    assert by["unclassified"] == {
        "stratum": "unclassified",
        "status": "mixed",
        "added": 1,
        "missing": 1,
    }


def test_key_diff_without_strata_field_single_group():
    diff = key_diff(["a"], ["b", "c"])
    assert diff["by_strata"] == [
        {"stratum": "all", "status": "mixed", "added": 2, "missing": 1}
    ]
