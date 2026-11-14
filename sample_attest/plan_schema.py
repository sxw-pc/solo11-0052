"""Schema constants and validation rules for declarative sampling plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .codes import (
    PLAN_BAD_RANGE,
    PLAN_CONFLICT,
    PLAN_NOT_MAPPING,
    PLAN_DUPLICATE_CHECK_ID,
    PLAN_FIELD_NOT_APPLICABLE,
    PLAN_MISSING_FIELD,
    PLAN_QUOTA_SUM_MISMATCH,
    PLAN_TYPE_ERROR,
    PLAN_UNKNOWN_FIELD,
    PLAN_UNKNOWN_MODE,
)

MODES = ("random", "stratified", "systematic", "cluster")
FORMATS = ("csv", "jsonl")
TOP_LEVEL_FIELDS = frozenset(
    {
        "plan_id",
        "dataset",
        "key_field",
        "mode",
        "seed",
        "size",
        "rate",
        "strata_field",
        "cluster_field",
        "expected_distribution",
        "checks",
    }
)
DATASET_FIELDS = frozenset({"path", "format"})
CHECK_TYPES = ("quota", "rate_range", "coverage", "key_unique", "no_overlap")
@dataclass
class ValidationResult:
    plan: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class PlanValidationError(Exception):
    """Raised when a plan cannot be validated."""

    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__(f"{len(errors)} plan validation error(s)")


class PlanLoadError(Exception):
    """Raised when a plan file cannot be read or parsed."""

    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__(f"{len(errors)} plan loading error(s)")


def issue(code: str, path: str, message: str, **extra: Any) -> dict[str, Any]:
    item = {"code": code, "path": path, "message": message}
    item.update(extra)
    return item


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_unknown(
    data: dict[str, Any],
    allowed: frozenset[str],
    prefix: str,
    errors: list[dict[str, Any]],
) -> None:
    for key in sorted(data, key=lambda item: str(item).encode("utf-8")):
        if key not in allowed:
            errors.append(
                issue(
                    PLAN_UNKNOWN_FIELD,
                    f"{prefix}.{key}",
                    f"未知字段 {key!r}",
                )
            )


def _validate_dataset(raw: Any, errors: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        errors.append(issue(PLAN_TYPE_ERROR, "plan.dataset", "dataset 必须是映射"))
        return None
    _check_unknown(raw, DATASET_FIELDS, "plan.dataset", errors)
    for key in ("path", "format"):
        if key not in raw:
            errors.append(issue(PLAN_MISSING_FIELD, f"plan.dataset.{key}", f"缺少 {key}"))
    path = raw.get("path")
    if not isinstance(path, str) or not path.strip():
        if "path" in raw:
            errors.append(issue(PLAN_TYPE_ERROR, "plan.dataset.path", "path 必须是非空字符串"))
    fmt = raw.get("format")
    if fmt not in FORMATS:
        if "format" in raw:
            errors.append(
                issue(PLAN_TYPE_ERROR, "plan.dataset.format", "format 必须是 csv 或 jsonl")
            )
    if errors:
        return None
    return {"path": path.strip(), "format": fmt}


def validate_plan(raw: Any) -> ValidationResult:
    """Validate a raw plan mapping and return a normalized copy."""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not isinstance(raw, dict):
        return ValidationResult(
            errors=[issue(PLAN_NOT_MAPPING, "plan", "方案根节点必须是映射")]
        )
    _check_unknown(raw, TOP_LEVEL_FIELDS, "plan", errors)

    normalized: dict[str, Any] = {}
    for key in ("plan_id", "key_field"):
        value = raw.get(key)
        if key not in raw:
            errors.append(issue(PLAN_MISSING_FIELD, f"plan.{key}", f"缺少 {key}"))
        elif not isinstance(value, str) or not value.strip():
            errors.append(issue(PLAN_TYPE_ERROR, f"plan.{key}", f"{key} 必须是非空字符串"))
        else:
            normalized[key] = value.strip()

    if "dataset" not in raw:
        errors.append(issue(PLAN_MISSING_FIELD, "plan.dataset", "缺少 dataset"))
    else:
        dataset = _validate_dataset(raw["dataset"], errors)
        if dataset is not None:
            normalized["dataset"] = dataset

    mode = raw.get("mode")
    if mode not in MODES:
        errors.append(
            issue(PLAN_UNKNOWN_MODE if "mode" in raw else PLAN_MISSING_FIELD,
                  "plan.mode", "mode 必须是 random/stratified/systematic/cluster")
        )
    else:
        normalized["mode"] = mode

    seed = raw.get("seed")
    if "seed" not in raw:
        errors.append(issue(PLAN_MISSING_FIELD, "plan.seed", "缺少 seed"))
    elif not _is_int(seed):
        errors.append(issue(PLAN_TYPE_ERROR, "plan.seed", "seed 必须是整数"))
    else:
        normalized["seed"] = seed

    if "size" in raw and "rate" in raw:
        errors.append(issue(PLAN_CONFLICT, "plan.size", "size 与 rate 只能二选一"))
    elif "size" not in raw and "rate" not in raw:
        errors.append(issue(PLAN_MISSING_FIELD, "plan.size", "size 与 rate 必须提供其一"))
    if "size" in raw:
        size = raw["size"]
        if not _is_int(size):
            errors.append(issue(PLAN_TYPE_ERROR, "plan.size", "size 必须是整数"))
        elif size <= 0:
            errors.append(issue(PLAN_BAD_RANGE, "plan.size", "size 必须大于 0"))
        else:
            normalized["size"] = size
    if "rate" in raw:
        rate = raw["rate"]
        if not _is_number(rate):
            errors.append(issue(PLAN_TYPE_ERROR, "plan.rate", "rate 必须是数字"))
        elif not 0 < rate <= 1:
            errors.append(issue(PLAN_BAD_RANGE, "plan.rate", "rate 必须满足 0 < rate <= 1"))
        else:
            normalized["rate"] = float(rate)

    expected: dict[str, int] | None = None
    if "expected_distribution" in raw:
        value = raw["expected_distribution"]
        if not isinstance(value, dict) or not value:
            errors.append(
                issue(PLAN_TYPE_ERROR, "plan.expected_distribution", "必须是非空映射")
            )
        else:
            expected = {}
            for group in sorted(value, key=lambda item: str(item).encode("utf-8")):
                count = value[group]
                if not isinstance(group, str) or not group:
                    errors.append(
                        issue(PLAN_TYPE_ERROR, "plan.expected_distribution", "分组名必须是非空字符串")
                    )
                elif not _is_int(count) or count < 0:
                    errors.append(
                        issue(
                            PLAN_BAD_RANGE,
                            f"plan.expected_distribution.{group}",
                            "配额必须是非负整数",
                        )
                    )
                else:
                    expected[group] = count
            normalized["expected_distribution"] = expected

    for field_name in ("strata_field", "cluster_field"):
        if field_name in raw:
            value = raw[field_name]
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    issue(PLAN_TYPE_ERROR, f"plan.{field_name}", f"{field_name} 必须是非空字符串")
                )
            else:
                normalized[field_name] = value.strip()

    if mode == "stratified" and not normalized.get("strata_field"):
        errors.append(
            issue(PLAN_MISSING_FIELD, "plan.strata_field", "stratified 模式需要 strata_field")
        )
    if mode == "cluster" and not normalized.get("cluster_field"):
        errors.append(
            issue(PLAN_MISSING_FIELD, "plan.cluster_field", "cluster 模式需要 cluster_field")
        )
    if mode in ("random", "systematic"):
        for field_name in ("strata_field", "cluster_field", "expected_distribution"):
            if field_name in raw:
                errors.append(
                    issue(
                        PLAN_FIELD_NOT_APPLICABLE,
                        f"plan.{field_name}",
                        f"{field_name} 不适用于 {mode} 模式",
                    )
                )
    if mode == "stratified" and "cluster_field" in raw:
        errors.append(
            issue(PLAN_FIELD_NOT_APPLICABLE, "plan.cluster_field", "cluster_field 不适用于 stratified")
        )
    if mode == "cluster" and "strata_field" in raw:
        errors.append(
            issue(PLAN_FIELD_NOT_APPLICABLE, "plan.strata_field", "strata_field 不适用于 cluster")
        )
    if mode in ("stratified", "cluster") and "expected_distribution" in raw and mode != "stratified":
        errors.append(
            issue(
                PLAN_FIELD_NOT_APPLICABLE,
                "plan.expected_distribution",
                "expected_distribution 仅适用于 stratified",
            )
        )

    checks = raw.get("checks")
    normalized_checks: list[dict[str, Any]] = []
    if "checks" not in raw:
        errors.append(issue(PLAN_MISSING_FIELD, "plan.checks", "缺少 checks"))
    elif not isinstance(checks, list) or not checks:
        errors.append(issue(PLAN_TYPE_ERROR, "plan.checks", "checks 必须是非空列表"))
    else:
        for index, item in enumerate(checks):
            from .plan_checks import validate_check
            check = validate_check(item, index, expected, normalized, errors)
            if check is not None:
                normalized_checks.append(check)
        ids = [c["id"] for c in normalized_checks]
        for index, rule_id in enumerate(ids):
            if ids.count(rule_id) > 1:
                errors.append(
                    issue(
                        PLAN_DUPLICATE_CHECK_ID,
                        f"plan.checks[{index}].id",
                        f"核验项 id 重复: {rule_id}",
                    )
                )
        normalized["checks"] = normalized_checks

    if expected is not None and "size" in normalized:
        total = sum(expected.values())
        if total != normalized["size"]:
            warnings.append(
                issue(
                    PLAN_QUOTA_SUM_MISMATCH,
                    "plan.expected_distribution",
                    f"配额合计 {total} 与 size {normalized['size']} 不一致",
                    observed=total,
                    expected=normalized["size"],
                )
            )
    return ValidationResult(plan=normalized, errors=errors, warnings=warnings)
