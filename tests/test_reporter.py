"""JSON/Markdown report rendering tests."""

from __future__ import annotations

import json

from sample_attest.reporter import (
    COMPLIANCE_STATEMENT,
    build_report,
    report_json_text,
    report_markdown,
    write_reports,
)
from sample_attest.samplers.base import SampleResult
from sample_attest.verifier import run_checks


def make_report(dataset, quota_ok=True):
    counts = {"region_A": 9, "region_B": 6, "region_C": 3}
    if not quota_ok:
        counts = {"region_A": 8, "region_B": 6, "region_C": 3}
    selected = []
    for region, count in counts.items():
        rows = [row for row in dataset.rows if row["region"] == region]
        selected.extend(row["subject_id"] for row in rows[:count])
    plan = {
        "plan_id": "report-plan",
        "mode": "stratified",
        "seed": 3,
        "strata_field": "region",
        "expected_distribution": {"region_A": 9, "region_B": 6, "region_C": 3},
        "checks": [{"id": "q", "type": "quota"}],
    }
    sample = SampleResult("stratified", selected, [], metadata={"target_size": 18})
    verification = run_checks(plan, dataset, sample)
    return build_report(
        plan,
        dataset,
        sample,
        verification,
        task_id="task-report",
        seed_effective=99,
        generated_at="2026-01-01T00:00:00Z",
    )


def test_report_json_contains_audit_fields(stratified_dataset):
    report = make_report(stratified_dataset)
    assert report["task_id"] == "task-report"
    assert report["compliance"] == COMPLIANCE_STATEMENT
    assert report["dataset"]["row_count"] == 60
    assert report["sample"]["count"] == 18
    assert report["seed_effective"] == 99
    assert report["verification"]["status"] == "pass"
    assert report["explanations"] == []


def test_report_json_is_deterministic(stratified_dataset):
    report = make_report(stratified_dataset)
    assert report_json_text(report) == report_json_text(json.loads(json.dumps(report)))
    assert report_json_text(report).endswith("\n")
    parsed = json.loads(report_json_text(report))
    assert list(parsed) == sorted(parsed)


def test_markdown_has_mandatory_compliance_and_ids(stratified_dataset):
    report = make_report(stratified_dataset)
    markdown = report_markdown(report)
    assert COMPLIANCE_STATEMENT in markdown
    assert "task-report" in markdown
    assert report["dataset"]["population_fingerprint"] in markdown
    assert "本工具不进行统计推断" in markdown


def test_markdown_lists_attribution_for_failure(stratified_dataset):
    report = make_report(stratified_dataset, quota_ok=False)
    markdown = report_markdown(report)
    assert "归因清单" in markdown
    assert "stratum:region_A" in markdown
    assert "缺口 1" in markdown
    assert report["verification"]["status"] == "fail"


def test_write_reports(tmp_path, stratified_dataset):
    report = make_report(stratified_dataset)
    paths = write_reports(tmp_path / "out", report)
    assert (tmp_path / "out" / "report.json").is_file()
    assert (tmp_path / "out" / "report.md").is_file()
    assert paths["report_json"].endswith("report.json")
    assert json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))["task_id"] == "task-report"
    assert COMPLIANCE_STATEMENT in (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
