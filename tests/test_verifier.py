"""Verification checks, tri-state outcomes and strict mode."""

from __future__ import annotations

from sample_attest.codes import (
    CHECK_COVERAGE_MINIMUM_ONLY,
    CHECK_COVERAGE_MISSING,
    CHECK_DUPLICATE_KEY,
    CHECK_EMPTY_SAMPLE,
    CHECK_KEY_OUTSIDE_POPULATION,
    CHECK_QUOTA_OVER,
    CHECK_QUOTA_SHORT,
    CHECK_RATE_AT_BOUNDARY,
    CHECK_RATE_OUT_OF_RANGE,
)
from sample_attest.samplers.base import SampleResult
from sample_attest.verifier import run_checks


def sample(selected, warnings=None):
    return SampleResult(
        mode="test",
        selected=list(selected),
        excluded=[],
        warnings=list(warnings or []),
    )


def keys_by_region(dataset, counts):
    result = []
    for region, count in counts.items():
        rows = [row for row in dataset.rows if row["region"] == region]
        result.extend(row["subject_id"] for row in rows[:count])
    return result


def plan_with(checks, **extra):
    plan = {
        "plan_id": "verify-test",
        "strata_field": "region",
        "expected_distribution": {"region_A": 9, "region_B": 6, "region_C": 3},
        **extra,
    }
    plan["checks"] = checks
    return plan


def check_by_type(verification, check_type):
    return [item for item in verification.checks if item.type == check_type][0]


def test_quota_short_fails_with_gap(stratified_dataset):
    selected = keys_by_region(stratified_dataset, {"region_A": 8, "region_B": 6, "region_C": 3})
    plan = plan_with([{"id": "q", "type": "quota"}])
    quota = check_by_type(run_checks(plan, stratified_dataset, sample(selected)), "quota")
    assert quota.status == "fail"
    assert quota.code == CHECK_QUOTA_SHORT
    assert quota.entries[0]["gap"] == 1


def test_quota_over_warns(stratified_dataset):
    selected = keys_by_region(stratified_dataset, {"region_A": 10, "region_B": 6, "region_C": 3})
    plan = plan_with([{"id": "q", "type": "quota"}])
    verification = run_checks(plan, stratified_dataset, sample(selected))
    quota = check_by_type(verification, "quota")
    assert quota.status == "warn"
    assert quota.code == CHECK_QUOTA_OVER
    assert verification.status == "warn"


def test_rate_pass_fail_and_boundary(stratified_dataset):
    plan = plan_with([{"id": "r", "type": "rate_range", "min": 0.25, "max": 0.35}])
    passing = keys_by_region(stratified_dataset, {"region_A": 9, "region_B": 6, "region_C": 3})
    assert check_by_type(run_checks(plan, stratified_dataset, sample(passing)), "rate_range").status == "pass"
    assert check_by_type(
        run_checks(plan, stratified_dataset, sample(passing[:3])), "rate_range"
    ).code == CHECK_RATE_OUT_OF_RANGE
    boundary = keys_by_region(stratified_dataset, {"region_A": 9, "region_B": 6})[:15]
    boundary_check = check_by_type(
        run_checks(plan, stratified_dataset, sample(boundary)), "rate_range"
    )
    assert boundary_check.status == "warn"
    assert boundary_check.code == CHECK_RATE_AT_BOUNDARY


def test_coverage_missing_fails(stratified_dataset):
    selected = keys_by_region(stratified_dataset, {"region_A": 2, "region_B": 2})
    plan = plan_with(
        [
            {
                "id": "c",
                "type": "coverage",
                "field": "region",
                "groups": ["region_A", "region_B", "region_C"],
            }
        ]
    )
    coverage = check_by_type(run_checks(plan, stratified_dataset, sample(selected)), "coverage")
    assert coverage.status == "fail"
    assert coverage.code == CHECK_COVERAGE_MISSING
    assert coverage.entries[0]["path"] == "region:region_C"


def test_coverage_minimum_only_warns(stratified_dataset):
    selected = keys_by_region(stratified_dataset, {"region_A": 1, "region_B": 1, "region_C": 1})
    plan = plan_with(
        [
            {
                "id": "c",
                "type": "coverage",
                "field": "region",
                "groups": ["region_A", "region_B", "region_C"],
            }
        ]
    )
    coverage = check_by_type(run_checks(plan, stratified_dataset, sample(selected)), "coverage")
    assert coverage.status == "warn"
    assert coverage.code == CHECK_COVERAGE_MINIMUM_ONLY


def test_key_unique_duplicate_fails(stratified_dataset):
    plan = plan_with([{"id": "u", "type": "key_unique"}])
    result = check_by_type(
        run_checks(plan, stratified_dataset, sample(["subject_0001", "subject_0001"])),
        "key_unique",
    )
    assert result.status == "fail"
    assert result.code == CHECK_DUPLICATE_KEY


def test_key_unique_pass_and_empty_warning(stratified_dataset):
    plan = plan_with([{"id": "u", "type": "key_unique"}])
    assert check_by_type(
        run_checks(plan, stratified_dataset, sample(["subject_0001"])), "key_unique"
    ).status == "pass"
    empty = check_by_type(
        run_checks(plan, stratified_dataset, sample([])), "key_unique"
    )
    assert empty.code == CHECK_EMPTY_SAMPLE
    assert empty.status == "warn"


def test_no_overlap_fail_and_empty_warning(stratified_dataset):
    plan = plan_with([{"id": "o", "type": "no_overlap"}])
    outside = check_by_type(
        run_checks(plan, stratified_dataset, sample(["subject_9999"])), "no_overlap"
    )
    assert outside.status == "fail"
    assert outside.code == CHECK_KEY_OUTSIDE_POPULATION
    empty = check_by_type(run_checks(plan, stratified_dataset, sample([])), "no_overlap")
    assert empty.status == "warn"
    assert empty.code == CHECK_EMPTY_SAMPLE


def test_all_five_checks_report_rule_ids(stratified_dataset):
    plan = plan_with(
        [
            {"id": "q", "type": "quota"},
            {"id": "r", "type": "rate_range", "min": 0.2, "max": 0.4},
            {
                "id": "c",
                "type": "coverage",
                "field": "region",
                "groups": ["region_A", "region_B", "region_C"],
            },
            {"id": "u", "type": "key_unique"},
            {"id": "o", "type": "no_overlap"},
        ]
    )
    selected = keys_by_region(stratified_dataset, {"region_A": 9, "region_B": 6, "region_C": 3})
    verification = run_checks(plan, stratified_dataset, sample(selected))
    assert [item.rule_id for item in verification.checks] == ["q", "r", "c", "u", "o"]
    assert verification.counts == {"pass": 5, "warn": 0, "fail": 0}


def test_strict_mode_turns_warning_into_failure(stratified_dataset):
    plan = plan_with([{"id": "r", "type": "rate_range", "min": 0.25, "max": 0.25}])
    selected = keys_by_region(stratified_dataset, {"region_A": 9, "region_B": 6})
    normal = run_checks(plan, stratified_dataset, sample(selected[:15]))
    assert normal.status == "warn"
    strict = run_checks(plan, stratified_dataset, sample(selected[:15]), strict=True)
    assert strict.status == "fail"
    assert strict.strict_failed is True
