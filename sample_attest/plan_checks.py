"""Validation of individual declarative verification checks."""

from __future__ import annotations

from typing import Any

from .codes import (
    PLAN_BAD_CHECK,
    PLAN_BAD_RANGE,
    PLAN_MISSING_FIELD,
    PLAN_TYPE_ERROR,
)
from .plan_schema import CHECK_TYPES, _check_unknown, issue

CHECK_FIELDS = {
    "quota": frozenset({"id", "type"}),
    "rate_range": frozenset({"id", "type", "min", "max"}),
    "coverage": frozenset({"id", "type", "field", "groups"}),
    "key_unique": frozenset({"id", "type"}),
    "no_overlap": frozenset({"id", "type"}),
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_check(
    raw: Any,
    index: int,
    expected: dict[str, int] | None,
    plan: dict[str, Any],
    errors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    path = f"plan.checks[{index}]"
    if not isinstance(raw, dict):
        errors.append(issue(PLAN_TYPE_ERROR, path, "核验项必须是映射"))
        return None
    check_type = raw.get("type")
    if check_type not in CHECK_TYPES:
        errors.append(
            issue(
                PLAN_BAD_CHECK,
                f"{path}.type",
                "type 必须是 quota/rate_range/coverage/key_unique/no_overlap",
            )
        )
        return None
    _check_unknown(raw, CHECK_FIELDS[check_type], path, errors)
    check = dict(raw)
    rule_id = check.get("id", f"check_{index + 1:03d}")
    if not isinstance(rule_id, str) or not rule_id.strip():
        errors.append(issue(PLAN_TYPE_ERROR, f"{path}.id", "id 必须是非空字符串"))
    check["id"] = rule_id.strip() if isinstance(rule_id, str) else rule_id

    if check_type == "rate_range":
        for name in ("min", "max"):
            if name not in raw:
                errors.append(issue(PLAN_MISSING_FIELD, f"{path}.{name}", f"缺少 {name}"))
            elif not _is_number(raw[name]):
                errors.append(issue(PLAN_TYPE_ERROR, f"{path}.{name}", f"{name} 必须是数字"))
        low, high = raw.get("min"), raw.get("max")
        if _is_number(low) and _is_number(high):
            if not (0 <= low <= high <= 1):
                errors.append(
                    issue(PLAN_BAD_RANGE, f"{path}.min", "必须满足 0 <= min <= max <= 1")
                )
    elif check_type == "coverage":
        groups = raw.get("groups")
        if groups is not None:
            if not isinstance(groups, list) or not groups:
                errors.append(issue(PLAN_TYPE_ERROR, f"{path}.groups", "groups 必须是非空列表"))
            else:
                seen: set[str] = set()
                for pos, group in enumerate(groups):
                    if not isinstance(group, str) or not group:
                        errors.append(
                            issue(PLAN_TYPE_ERROR, f"{path}.groups[{pos}]", "分组名必须是非空字符串")
                        )
                    elif group in seen:
                        errors.append(
                            issue(PLAN_BAD_CHECK, f"{path}.groups[{pos}]", "分组名重复")
                        )
                    else:
                        seen.add(group)
        field_name = raw.get("field")
        if field_name is not None and (not isinstance(field_name, str) or not field_name):
            errors.append(issue(PLAN_TYPE_ERROR, f"{path}.field", "field 必须是非空字符串"))
        if field_name is None and not (
            plan.get("strata_field")
            or plan.get("cluster_substrata_field")
            or plan.get("cluster_field")
        ):
            errors.append(
                issue(PLAN_BAD_CHECK, f"{path}.field", "非分层/整群方案必须显式声明 field")
            )
        if groups is None and expected is None:
            errors.append(
                issue(PLAN_BAD_CHECK, f"{path}.groups", "需声明 groups 或 expected_distribution")
            )
    elif check_type == "quota" and expected is None:
        if not plan.get("cluster_substrata_weights"):
            errors.append(
                issue(
                    PLAN_BAD_CHECK,
                    f"{path}.type",
                    "quota 核验需要 expected_distribution 或 cluster_substrata_weights",
                )
            )
    return check if not any(e["path"].startswith(path) for e in errors) else None
