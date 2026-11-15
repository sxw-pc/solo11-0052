"""Plan schema and YAML loading tests."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from sample_attest.codes import (
    PLAN_BAD_CHECK,
    PLAN_BAD_RANGE,
    PLAN_CONFLICT,
    PLAN_DUPLICATE_CHECK_ID,
    PLAN_FIELD_NOT_APPLICABLE,
    PLAN_FILE_NOT_FOUND,
    PLAN_MISSING_FIELD,
    PLAN_PARSE_ERROR,
    PLAN_QUOTA_SUM_MISMATCH,
    PLAN_TYPE_ERROR,
    PLAN_UNKNOWN_FIELD,
    PLAN_UNKNOWN_MODE,
)
from sample_attest.plan_loader import PlanLoadError, PlanValidationError, load_plan
from sample_attest.plan_schema import validate_plan


def codes(result):
    return [item["code"] for item in result.errors]


def test_valid_plan_and_generated_check_id(base_plan):
    raw = copy.deepcopy(base_plan)
    raw["checks"] = [{"type": "key_unique"}]
    result = validate_plan(raw)
    assert result.ok
    assert result.plan["checks"][0]["id"] == "check_001"
    assert result.plan["mode"] == "random"


@pytest.mark.parametrize(
    "field,code",
    [
        ("plan_id", PLAN_MISSING_FIELD),
        ("dataset", PLAN_MISSING_FIELD),
        ("key_field", PLAN_MISSING_FIELD),
        ("mode", PLAN_MISSING_FIELD),
        ("seed", PLAN_MISSING_FIELD),
        ("checks", PLAN_MISSING_FIELD),
    ],
)
def test_missing_required_fields(base_plan, field, code):
    raw = copy.deepcopy(base_plan)
    raw.pop(field)
    result = validate_plan(raw)
    assert code in codes(result)
    assert any(item["path"].startswith(f"plan.{field}") for item in result.errors)


def test_type_and_range_errors(base_plan):
    raw = copy.deepcopy(base_plan)
    raw["seed"] = "not-an-int"
    raw["size"] = 0
    result = validate_plan(raw)
    assert PLAN_TYPE_ERROR in codes(result)
    assert PLAN_BAD_RANGE in codes(result)


def test_size_rate_conflict(base_plan):
    raw = copy.deepcopy(base_plan)
    raw["rate"] = 0.5
    assert PLAN_CONFLICT in codes(validate_plan(raw))


def test_unknown_top_level_field(base_plan):
    raw = copy.deepcopy(base_plan)
    raw["surprise"] = True
    result = validate_plan(raw)
    assert PLAN_UNKNOWN_FIELD in codes(result)
    assert any(item["path"] == "plan.surprise" for item in result.errors)


def test_unknown_mode(base_plan):
    raw = copy.deepcopy(base_plan)
    raw["mode"] = "weighted"
    assert PLAN_UNKNOWN_MODE in codes(validate_plan(raw))


def test_stratified_requires_field(base_plan):
    raw = copy.deepcopy(base_plan)
    raw["mode"] = "stratified"
    result = validate_plan(raw)
    assert PLAN_MISSING_FIELD in codes(result)
    assert any(item["path"] == "plan.strata_field" for item in result.errors)


def test_dataset_format_rejected(base_plan):
    raw = copy.deepcopy(base_plan)
    raw["dataset"]["format"] = "parquet"
    result = validate_plan(raw)
    assert PLAN_TYPE_ERROR in codes(result)
    assert any(item["path"] == "plan.dataset.format" for item in result.errors)


def test_bad_check_type_and_unknown_param(base_plan):
    raw = copy.deepcopy(base_plan)
    raw["checks"] = [{"id": "x", "type": "mystery"}]
    assert PLAN_BAD_CHECK in codes(validate_plan(raw))
    raw["checks"] = [{"id": "x", "type": "key_unique", "threshold": 3}]
    assert PLAN_UNKNOWN_FIELD in codes(validate_plan(raw))


def test_duplicate_check_ids(base_plan):
    raw = copy.deepcopy(base_plan)
    raw["checks"] = [
        {"id": "same", "type": "key_unique"},
        {"id": "same", "type": "no_overlap"},
    ]
    assert PLAN_DUPLICATE_CHECK_ID in codes(validate_plan(raw))


def test_quota_sum_mismatch_warns(base_plan):
    raw = copy.deepcopy(base_plan)
    raw["mode"] = "stratified"
    raw["strata_field"] = "region"
    raw["size"] = 3
    raw["expected_distribution"] = {"region_A": 1, "region_B": 1}
    raw["checks"] = [{"id": "q", "type": "quota"}]
    result = validate_plan(raw)
    assert result.ok
    assert PLAN_QUOTA_SUM_MISMATCH in [item["code"] for item in result.warnings]


def test_load_real_plan_relative_dataset():
    root = Path(__file__).resolve().parents[1]
    loaded = load_plan(root / "plans" / "stratified_basic.yaml")
    assert loaded.plan_id == "stratified-basic"
    assert loaded.dataset_path == root / "fixtures" / "population_stratified.csv"
    assert "expected_distribution" in loaded.data


def test_load_missing_file():
    with pytest.raises(PlanLoadError) as exc:
        load_plan("does-not-exist.yaml")
    assert exc.value.errors[0]["code"] == PLAN_FILE_NOT_FOUND


def test_yaml_parse_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("plan_id: [unclosed\n", encoding="utf-8")
    with pytest.raises(PlanLoadError) as exc:
        load_plan(path)
    assert exc.value.errors[0]["code"] == PLAN_PARSE_ERROR


def test_validation_error_raised_on_load(yaml_plan, base_plan):
    raw = copy.deepcopy(base_plan)
    raw.pop("seed")
    path = yaml_plan("bad.yaml", raw)
    with pytest.raises(PlanValidationError) as exc:
        load_plan(path)
    assert any(item["code"] == PLAN_MISSING_FIELD for item in exc.value.errors)


def cluster_plan(**overrides):
    plan = {
        "plan_id": "cluster-substrata-schema",
        "dataset": {"path": "unused.jsonl", "format": "jsonl"},
        "key_field": "subject_id",
        "mode": "cluster",
        "seed": 5,
        "size": 6,
        "cluster_field": "cluster",
        "cluster_substrata_field": "segment",
        "cluster_substrata_weights": {
            "cluster_01": {"segment_low": 1, "segment_mid": 1, "segment_high": 1}
        },
        "checks": [{"id": "q", "type": "quota"}],
    }
    plan.update(overrides)
    return plan


def test_cluster_substrata_plan_validates_and_normalizes():
    raw = cluster_plan()
    raw["cluster_substrata_weights"] = {
        "cluster_01": {"segment_low": 2.0, "segment_mid": 1, "segment_high": 1}
    }
    result = validate_plan(raw)
    assert result.ok
    assert result.plan["cluster_substrata_field"] == "segment"
    assert result.plan["cluster_substrata_weights"]["cluster_01"]["segment_low"] == 2.0


def test_cluster_substrata_fields_are_whitelisted_top_level():
    raw = cluster_plan()
    result = validate_plan(raw)
    assert result.ok
    assert not [e for e in result.errors if e["code"] == PLAN_UNKNOWN_FIELD]


@pytest.mark.parametrize(
    "missing",
    ["cluster_substrata_field", "cluster_substrata_weights"],
)
def test_cluster_substrata_fields_require_each_other(missing):
    raw = cluster_plan()
    raw.pop(missing)
    result = validate_plan(raw)
    assert PLAN_MISSING_FIELD in codes(result)
    assert any(
        item["path"] == f"plan.{missing}" for item in result.errors
    )


@pytest.mark.parametrize("mode", ["random", "stratified", "systematic"])
def test_cluster_substrata_fields_rejected_outside_cluster(mode):
    raw = cluster_plan(mode=mode)
    if mode == "stratified":
        raw["strata_field"] = "region"
    result = validate_plan(raw)
    assert PLAN_FIELD_NOT_APPLICABLE in codes(result)
    paths = {item["path"] for item in result.errors}
    assert "plan.cluster_substrata_field" in paths
    assert "plan.cluster_substrata_weights" in paths


def test_cluster_mode_still_requires_cluster_field_with_substrata():
    raw = cluster_plan()
    raw.pop("cluster_field")
    result = validate_plan(raw)
    assert PLAN_MISSING_FIELD in codes(result)
    assert any(item["path"] == "plan.cluster_field" for item in result.errors)


@pytest.mark.parametrize(
    "weights,expected_code",
    [
        ([], PLAN_TYPE_ERROR),
        ("x", PLAN_TYPE_ERROR),
        ({"cluster_01": []}, PLAN_TYPE_ERROR),
        ({"cluster_01": {"segment_low": 0}}, PLAN_BAD_RANGE),
        ({"cluster_01": {"segment_low": -1}}, PLAN_BAD_RANGE),
        ({"cluster_01": {"segment_low": "heavy"}}, PLAN_TYPE_ERROR),
        ({"": {"segment_low": 1}}, PLAN_TYPE_ERROR),
    ],
)
def test_cluster_substrata_weights_validation(weights, expected_code):
    raw = cluster_plan(cluster_substrata_weights=weights)
    result = validate_plan(raw)
    assert expected_code in codes(result)


def test_cluster_substrata_weights_reject_unknown_nested_shape():
    raw = cluster_plan(
        cluster_substrata_weights={
            "cluster_01": {"segment_low": 1, "extra": {"nested": 2}},
        }
    )
    result = validate_plan(raw)
    assert PLAN_TYPE_ERROR in codes(result)


def test_quota_check_allowed_with_cluster_substrata_weights(base_plan):
    raw = cluster_plan()
    raw["checks"] = [{"id": "q", "type": "quota"}]
    result = validate_plan(raw)
    assert result.ok


def test_load_cluster_substrata_plan_relative_dataset():
    root = Path(__file__).resolve().parents[1]
    loaded = load_plan(root / "plans" / "cluster_substrata.yaml")
    assert loaded.plan_id == "cluster-substrata"
    assert loaded.dataset_path == root / "fixtures" / "population_cluster.jsonl"
    assert loaded.data["cluster_substrata_field"] == "segment"
