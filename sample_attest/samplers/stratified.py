"""Deterministic stratified sampling, including declared quota allocation."""

from __future__ import annotations

import math
from typing import Any

from ..codes import (
    SAMPLE_EMPTY_STRATUM,
    SAMPLE_MISSING_STRATUM_VALUE,
    STRATUM_GROUP_MISSING,
    STRATUM_QUOTA_SHORT,
    STRATUM_UNPLANNED_GROUP,
)
from .base import (
    SampleResult,
    apply_fisher_yates,
    byte_sorted,
    excluded_keys,
    group_items,
    group_seed,
    make_warning,
    resolve_target,
    sample_keys,
    seed_for,
)


def _proportional_quotas(sizes: dict[str, int], target: int) -> dict[str, int]:
    total = sum(sizes.values())
    if total == 0 or target == 0:
        return {group: 0 for group in sizes}
    exact = {group: target * size / total for group, size in sizes.items()}
    quotas = {group: min(sizes[group], int(math.floor(value))) for group, value in exact.items()}
    left = target - sum(quotas.values())
    order = sorted(
        sizes,
        key=lambda group: (-(exact[group] - math.floor(exact[group])), group.encode("utf-8")),
    )
    cursor = 0
    while left > 0 and order:
        group = order[cursor % len(order)]
        if quotas[group] < sizes[group]:
            quotas[group] += 1
            left -= 1
        cursor += 1
        if cursor > len(order) * (target + 1):
            break
    return quotas


def _quota_sampling(
    groups: dict[str, list[dict[str, Any]]],
    expected: dict[str, int],
    key_field: str,
    base_seed: int,
    warnings: list[dict[str, Any]],
) -> tuple[list[str], dict[str, int], dict[str, int]]:
    selected: list[str] = []
    quotas: dict[str, int] = {}
    sizes = {group: len(rows) for group, rows in groups.items()}
    for group in byte_sorted(expected):
        quota = int(expected[group])
        quotas[group] = quota
        members = groups.get(group, [])
        if not members:
            warnings.append(
                make_warning(
                    STRATUM_GROUP_MISSING,
                    f"stratum:{group}",
                    f"声明分层 {group!r} 在总体中不存在",
                    expected=quota,
                    observed=0,
                )
            )
            continue
        if len(members) < quota:
            warnings.append(
                make_warning(
                    STRATUM_QUOTA_SHORT,
                    f"stratum:{group}",
                    f"分层 {group!r} 配额 {quota}，实有 {len(members)}，缺口 {quota - len(members)}",
                    observed=len(members),
                    expected=quota,
                    gap=quota - len(members),
                )
            )
        keys = [str(row[key_field]) for row in members]
        shuffled = apply_fisher_yates(keys, group_seed(base_seed, "stratum", group))
        selected.extend(shuffled[: min(quota, len(shuffled))])
    for group in byte_sorted(groups):
        if group not in expected:
            warnings.append(
                make_warning(
                    STRATUM_UNPLANNED_GROUP,
                    f"stratum:{group}",
                    f"分层 {group!r} 未在 expected_distribution 中声明，配额为 0",
                    observed=len(groups[group]),
                    expected=0,
                )
            )
    return selected, quotas, sizes


def _attribute_subjects(
    items: list[dict[str, Any]],
    key_field: str,
    subject_field: str,
    strata_field: str,
) -> dict[str, dict[str, str]]:
    """Assign every subject a single attribution row.

    Among all rows sharing one subject value, the row with the smallest key
    in UTF-8 byte order is the attribution row; its strata value defines the
    subject's unique stratum. Every other row of the same subject is kept in
    the dataset but never consumes quota.
    """
    attribution: dict[str, dict[str, str]] = {}
    for row in items:
        subject = str(row.get(subject_field, ""))
        key = str(row[key_field])
        entry = {"key": key, "stratum": str(row.get(strata_field, ""))}
        current = attribution.get(subject)
        if current is None or key.encode("utf-8") < current["key"].encode("utf-8"):
            attribution[subject] = entry
    return attribution


def _subject_groups(
    attribution: dict[str, dict[str, str]],
) -> dict[str, list[str]]:
    """Group attribution keys by their subject's unique stratum."""
    grouped: dict[str, list[str]] = {}
    for subject in byte_sorted(attribution):
        entry = attribution[subject]
        grouped.setdefault(entry["stratum"], []).append(entry["key"])
    return {group: grouped[group] for group in byte_sorted(grouped)}


def _subject_quota_sampling(
    groups: dict[str, list[str]],
    expected: dict[str, int],
    base_seed: int,
    warnings: list[dict[str, Any]],
) -> tuple[list[str], dict[str, int], dict[str, int]]:
    selected: list[str] = []
    realized: dict[str, int] = {}
    sizes = {group: len(keys) for group, keys in groups.items()}
    for group in byte_sorted(expected):
        quota = int(expected[group])
        members = groups.get(group, [])
        if not members:
            warnings.append(
                make_warning(
                    STRATUM_GROUP_MISSING,
                    f"stratum:{group}",
                    f"声明分层 {group!r} 在总体中不存在",
                    expected=quota,
                    observed=0,
                )
            )
            realized[group] = 0
            continue
        if len(members) < quota:
            warnings.append(
                make_warning(
                    STRATUM_QUOTA_SHORT,
                    f"stratum:{group}",
                    f"分层 {group!r} 配额 {quota}，归属主体 {len(members)}，缺口 {quota - len(members)}",
                    observed=len(members),
                    expected=quota,
                    gap=quota - len(members),
                )
            )
        shuffled = apply_fisher_yates(members, group_seed(base_seed, "stratum", group))
        picked = shuffled[: min(quota, len(shuffled))]
        selected.extend(picked)
        realized[group] = len(picked)
    for group in byte_sorted(groups):
        if group not in expected:
            warnings.append(
                make_warning(
                    STRATUM_UNPLANNED_GROUP,
                    f"stratum:{group}",
                    f"分层 {group!r} 未在 expected_distribution 中声明，配额为 0",
                    observed=len(groups[group]),
                    expected=0,
                )
            )
    return selected, realized, sizes


def _sample_by_subject(
    items: list[dict[str, Any]],
    plan: dict[str, Any],
    all_keys: list[str],
    subject_field: str,
    warnings: list[dict[str, Any]],
) -> SampleResult:
    if not items:
        resolve_target(plan, 0, warnings)
        return SampleResult("stratified", [], [], warnings, {"strata": {}})
    field_name = str(plan["strata_field"])
    key_field = str(plan["key_field"])
    attribution = _attribute_subjects(items, key_field, subject_field, field_name)
    subject_count = len(attribution)
    target = resolve_target(plan, subject_count, warnings)
    groups = _subject_groups(attribution)
    if "" in groups:
        warnings.append(
            make_warning(
                SAMPLE_MISSING_STRATUM_VALUE,
                f"field:{field_name}",
                "部分主体归属行的分层字段为空，已归入空分层",
                count=len(groups[""]),
            )
        )
    base_seed = seed_for(plan, items)
    expected = plan.get("expected_distribution")
    if isinstance(expected, dict) and expected:
        selected, quotas, sizes = _subject_quota_sampling(
            groups, expected, base_seed, warnings
        )
        algorithm = "subject-quota"
    else:
        sizes = {group: len(keys) for group, keys in groups.items()}
        quotas = _proportional_quotas(sizes, target)
        selected = []
        for group in byte_sorted(groups):
            shuffled = apply_fisher_yates(
                groups[group], group_seed(base_seed, "stratum", group)
            )
            picked = shuffled[: quotas[group]]
            selected.extend(picked)
            quotas[group] = len(picked)
        algorithm = "subject-proportional-largest-remainder"
    return SampleResult(
        mode="stratified",
        selected=selected,
        excluded=excluded_keys(all_keys, selected),
        warnings=warnings,
        metadata={
            "population_size": len(all_keys),
            "target_size": target,
            "seed_effective": base_seed,
            "field": field_name,
            "strata_sizes": sizes,
            "quotas": quotas,
            "algorithm": algorithm,
            "subject_field": subject_field,
            "subject_count": subject_count,
            "subject_rows": len(items),
        },
    )


def sample(items: list[dict[str, Any]], plan: dict[str, Any]) -> SampleResult:
    warnings: list[dict[str, Any]] = []
    all_keys = sample_keys(items, plan)
    subject_field = plan.get("subject_field")
    if subject_field:
        return _sample_by_subject(items, plan, all_keys, str(subject_field), warnings)
    target = resolve_target(plan, len(all_keys), warnings)
    field_name = str(plan["strata_field"])
    groups = group_items(items, field_name)
    if not items:
        return SampleResult("stratified", [], [], warnings, {"strata": {}})
    if "" in groups:
        warnings.append(
            make_warning(
                SAMPLE_MISSING_STRATUM_VALUE,
                f"field:{field_name}",
                "部分记录的分层字段为空，已归入空分层",
                count=len(groups[""]),
            )
        )
    if any(not rows for rows in groups.values()):
        warnings.append(
            make_warning(SAMPLE_EMPTY_STRATUM, "stratum", "存在空分层")
        )
    base_seed = seed_for(plan, items)
    expected = plan.get("expected_distribution")
    if isinstance(expected, dict) and expected:
        selected, quotas, sizes = _quota_sampling(
            groups, expected, plan["key_field"], base_seed, warnings
        )
    else:
        sizes = {group: len(rows) for group, rows in groups.items()}
        quotas = _proportional_quotas(sizes, target)
        selected = []
        for group in byte_sorted(groups):
            keys = [str(row[plan["key_field"]]) for row in groups[group]]
            shuffled = apply_fisher_yates(keys, group_seed(base_seed, "stratum", group))
            selected.extend(shuffled[: quotas[group]])
    return SampleResult(
        mode="stratified",
        selected=selected,
        excluded=excluded_keys(all_keys, selected),
        warnings=warnings,
        metadata={
            "population_size": len(all_keys),
            "target_size": target,
            "seed_effective": base_seed,
            "field": field_name,
            "strata_sizes": sizes,
            "quotas": quotas,
            "algorithm": "quota" if expected else "proportional-largest-remainder",
        },
    )
