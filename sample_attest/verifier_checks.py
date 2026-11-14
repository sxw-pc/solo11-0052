"""Individual deterministic check implementations."""

from __future__ import annotations

from typing import Any

from .codes import (
    CHECK_COVERAGE_MINIMUM_ONLY,
    CHECK_COVERAGE_MISSING,
    CHECK_DUPLICATE_KEY,
    CHECK_EMPTY_SAMPLE,
    CHECK_FIELD_NOT_FOUND,
    CHECK_KEY_OUTSIDE_POPULATION,
    CHECK_QUOTA_OVER,
    CHECK_QUOTA_SHORT,
    CHECK_RATE_AT_BOUNDARY,
    CHECK_RATE_OUT_OF_RANGE,
)
from .dataset_loader import Dataset
from .samplers.base import SampleResult, byte_sorted, make_warning
from .verification_types import CheckResult


def _status(observed: Any, expected: Any, location: str, message: str) -> CheckResult:
    return CheckResult("", "", "pass", None, message, observed, expected, location)


def _quota_check(
    check: dict[str, Any], plan: dict[str, Any], dataset: Dataset, result: SampleResult
) -> CheckResult:
    rule_id = check["id"]
    field_name = plan.get("strata_field", "")
    expected = dict(plan.get("expected_distribution") or {})
    counts: dict[str, int] = {}
    for key in result.selected:
        row = dataset.rows[dataset.key_to_row[key]]
        value = str(row.get(field_name, ""))
        counts[value] = counts.get(value, 0) + 1
    entries: list[dict[str, Any]] = []
    shortfalls = 0
    overs = 0
    for group in byte_sorted(expected):
        quota = int(expected[group])
        actual = counts.get(group, 0)
        if actual < quota:
            shortfalls += 1
            entries.append(
                make_warning(
                    CHECK_QUOTA_SHORT,
                    f"stratum:{group}",
                    f"分层 {group!r} 配额 {quota}、实得 {actual}、缺口 {quota - actual}",
                    observed=actual,
                    expected=quota,
                    gap=quota - actual,
                )
            )
        elif actual > quota:
            overs += 1
            entries.append(
                make_warning(
                    CHECK_QUOTA_OVER,
                    f"stratum:{group}",
                    f"分层 {group!r} 配额 {quota}、实得 {actual}、超出 {actual - quota}",
                    observed=actual,
                    expected=quota,
                    gap=actual - quota,
                )
            )
    if shortfalls:
        code, status, message = CHECK_QUOTA_SHORT, "fail", f"{shortfalls} 个分层配额不足"
    elif overs:
        code, status, message = CHECK_QUOTA_OVER, "warn", f"{overs} 个分层超过配额"
    else:
        code, status, message = None, "pass", "所有分层配额精确匹配"
    return CheckResult(
        rule_id, "quota", status, code, message,
        {group: counts.get(group, 0) for group in byte_sorted(expected)},
        {group: int(expected[group]) for group in byte_sorted(expected)},
        "expected_distribution", entries,
    )


def _rate_check(
    check: dict[str, Any], dataset: Dataset, result: SampleResult
) -> CheckResult:
    low = float(check["min"])
    high = float(check["max"])
    population = dataset.row_count
    observed = len(result.selected) / population if population else 0.0
    tolerance = 1e-12
    if observed < low - tolerance or observed > high + tolerance:
        code, status = CHECK_RATE_OUT_OF_RANGE, "fail"
        message = f"实际抽样率 {observed:.12g} 不在 [{low}, {high}] 内"
    elif abs(observed - low) <= tolerance or abs(observed - high) <= tolerance:
        code, status = CHECK_RATE_AT_BOUNDARY, "warn"
        message = f"实际抽样率 {observed:.12g} 恰在区间边界"
    else:
        code, status = None, "pass"
        message = f"实际抽样率 {observed:.12g} 在 [{low}, {high}] 内"
    entries = []
    if status != "pass":
        entries.append(
            make_warning(
                code, "verification.rate", message,
                observed=round(observed, 12), expected=[low, high],
            )
        )
    return CheckResult(
        check["id"], "rate_range", status, code, message,
        round(observed, 12), {"min": low, "max": high}, "rate", entries,
    )


def _coverage_check(
    check: dict[str, Any], plan: dict[str, Any], dataset: Dataset, result: SampleResult
) -> CheckResult:
    field_name = check.get("field") or plan.get("strata_field") or plan.get("cluster_field")
    if not field_name or field_name not in dataset.fieldnames:
        message = f"覆盖字段 {field_name!r} 不存在于数据集"
        return CheckResult(
            check["id"], "coverage", "fail", CHECK_FIELD_NOT_FOUND, message,
            None, field_name, f"field:{field_name}",
            [make_warning(CHECK_FIELD_NOT_FOUND, f"field:{field_name}", message)],
        )
    declared = check.get("groups")
    if declared is None and plan.get("expected_distribution"):
        declared = list(plan["expected_distribution"])
    if declared is None:
        declared = sorted({str(row.get(field_name, "")) for row in dataset.rows})
    declared = byte_sorted(str(group) for group in declared)
    counts: dict[str, int] = {group: 0 for group in declared}
    for key in result.selected:
        row = dataset.rows[dataset.key_to_row[key]]
        group = str(row.get(field_name, ""))
        if group in counts:
            counts[group] += 1
    entries: list[dict[str, Any]] = []
    missing: list[str] = []
    minimum_only: list[str] = []
    for group in declared:
        if counts[group] == 0:
            missing.append(group)
            entries.append(
                make_warning(
                    CHECK_COVERAGE_MISSING,
                    f"{field_name}:{group}",
                    f"声明分组 {group!r} 未被抽中",
                    observed=0, expected=1,
                )
            )
        elif counts[group] == 1:
            minimum_only.append(group)
            entries.append(
                make_warning(
                    CHECK_COVERAGE_MINIMUM_ONLY,
                    f"{field_name}:{group}",
                    f"声明分组 {group!r} 仅抽中 1 条，覆盖处于边界",
                    observed=1, expected=">=2 (recommended)", group=group,
                )
            )
    if missing:
        code, status = CHECK_COVERAGE_MISSING, "fail"
        message = f"{len(missing)} 个声明分组未被覆盖"
    elif minimum_only:
        code, status = CHECK_COVERAGE_MINIMUM_ONLY, "warn"
        message = f"{len(minimum_only)} 个分组仅抽中 1 条"
    else:
        code, status = None, "pass"
        message = "所有声明分组均被覆盖"
    return CheckResult(
        check["id"], "coverage", status, code, message,
        counts, {group: ">=1" for group in declared}, f"field:{field_name}", entries,
    )


def _decode_check(
    check: dict[str, Any], dataset: Dataset, result: SampleResult
) -> CheckResult:
    selected = list(result.selected)
    unique = len(set(selected))
    if unique != len(selected):
        seen: set[str] = set()
        duplicates: list[str] = []
        for key in selected:
            if key in seen and key not in duplicates:
                duplicates.append(key)
            seen.add(key)
        duplicates = byte_sorted(duplicates)
        entries = [
            make_warning(
                CHECK_DUPLICATE_KEY, "sample.keys",
                f"样本主键 {key!r} 重复", key=key,
            )
            for key in duplicates
        ]
        return CheckResult(
            check["id"], "key_unique", "fail", CHECK_DUPLICATE_KEY,
            f"样本含 {len(selected) - unique} 个重复主键", selected, "unique",
            "sample.keys", entries,
        )
    if not selected and dataset.row_count:
        message = "样本为空，无法检验主键唯一性"
        return CheckResult(
            check["id"], "key_unique", "warn", CHECK_EMPTY_SAMPLE, message,
            [], "non-empty", "sample.keys",
            [make_warning(CHECK_EMPTY_SAMPLE, "sample.keys", message)],
        )
    return CheckResult(
        check["id"], "key_unique", "pass", None, "样本主键唯一",
        len(selected), "unique", "sample.keys",
    )


def _overlap_check(
    check: dict[str, Any], dataset: Dataset, result: SampleResult
) -> CheckResult:
    outside = byte_sorted({key for key in result.selected if key not in dataset.key_set})
    if outside:
        entries = [
            make_warning(
                CHECK_KEY_OUTSIDE_POPULATION, "sample.keys",
                f"样本键 {key!r} 不属于总体", key=key,
            )
            for key in outside
        ]
        return CheckResult(
            check["id"], "no_overlap", "fail", CHECK_KEY_OUTSIDE_POPULATION,
            f"{len(outside)} 个样本键不属于总体", outside, "subset", "sample.keys", entries,
        )
    if not result.selected and dataset.row_count:
        message = "样本为空，无法检验总体包含关系"
        return CheckResult(
            check["id"], "no_overlap", "warn", CHECK_EMPTY_SAMPLE, message,
            [], "subset", "sample.keys",
            [make_warning(CHECK_EMPTY_SAMPLE, "sample.keys", message)],
        )
    return CheckResult(
        check["id"], "no_overlap", "pass", None, "所有样本键均属于总体",
        len(result.selected), "subset", "sample.keys",
    )


