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
