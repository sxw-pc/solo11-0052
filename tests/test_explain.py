"""Failure attribution tests."""

from __future__ import annotations

from sample_attest.explain import (
    explain_plan_warnings,
    explain_sample_diff,
    explain_verification,
)
from sample_attest.samplers.base import SampleResult, make_warning
from sample_attest.verifier import run_checks


def selected_for(dataset, region_counts):
    result = []
    for region, count in region_counts.items():
        rows = [row for row in dataset.rows if row["region"] == region]
        result.extend(row["subject_id"] for row in rows[:count])
    return result


def plan_with(checks):
    return {
        "plan_id": "explain-test",
        "strata_field": "region",
        "expected_distribution": {"region_A": 9, "region_B": 6, "region_C": 3},
        "checks": checks,
    }


def test_quota_short_explanation_has_location_and_gap(stratified_dataset):
    plan = plan_with([{"id": "q", "type": "quota"}])
    selected = selected_for(stratified_dataset, {"region_A": 8, "region_B": 6, "region_C": 3})
    verification = run_checks(
        plan, stratified_dataset, SampleResult("test", selected, [])
    )
    explanations = explain_verification(verification)
    assert len(explanations) == 1
    item = explanations[0]
    assert item["rule_id"] == "q"
    assert item["severity"] == "failure"
    assert item["location"] == "stratum:region_A"
    assert item["gap"] == 1
    assert "缺口 1" in item["message"]


def test_passing_checks_produce_no_explanations(stratified_dataset):
    plan = plan_with([{"id": "u", "type": "key_unique"}])
    verification = run_checks(
        plan, stratified_dataset, SampleResult("test", ["subject_1001"], [])
    )
    assert explain_verification(verification) == []


def test_warning_explanation_severity(stratified_dataset):
    plan = plan_with([{"id": "q", "type": "quota"}])
    selected = selected_for(stratified_dataset, {"region_A": 10, "region_B": 6, "region_C": 3})
    verification = run_checks(
        plan, stratified_dataset, SampleResult("test", selected, [])
    )
    explanations = explain_verification(verification)
    assert explanations[0]["severity"] == "warning"
    assert explanations[0]["gap"] == 1


def test_plan_warning_attribution():
    explanations = explain_plan_warnings(
        [make_warning("PLAN_QUOTA_SUM_MISMATCH", "plan.expected_distribution", "x")]
    )
    assert explanations[0]["check_type"] == "plan_validation"
    assert explanations[0]["location"] == "plan.expected_distribution"


def test_sample_diff_text_is_capped():
    diff = {
        "added": ["subject_0001"],
        "missing": ["subject_0002"],
        "added_count": 21,
        "missing_count": 2,
        "truncated": True,
    }
    lines = explain_sample_diff(diff)
    assert lines[0].startswith("新增样本 21 个")
    assert lines[1].startswith("缺失样本 2 个")
    assert "截断" in lines[2]
