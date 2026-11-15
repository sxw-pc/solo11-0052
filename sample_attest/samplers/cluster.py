"""Deterministic one-stage cluster sampling.

Clusters are selected in a seeded order until the declared row target is met.
All rows in every selected cluster are included (one-stage cluster take-all).
The final cluster may cause an overshoot; this is reported, never hidden.

When a plan declares ``cluster_substrata_field`` and
``cluster_substrata_weights``, the set of selected clusters is unchanged.  For
each selected cluster its row count becomes the within-cluster target, which is
apportioned to the declared sub-strata in proportion to ``weight * stratum
size`` with a largest-remainder integer allocation and UTF-8 byte-order
tie-breaks.  A sub-stratum quota that exceeds that stratum's actual row count
is never filled by adding another cluster or another subject: the available
rows are kept, the shortfall is reported as ``CLUSTER_QUOTA_SHORT`` located at
``cluster:<cluster>:<substratum>``, and every per-cluster allocation is written
to ``sample.metadata``.  The total sample count therefore equals the target
volume the selected cluster boundary can actually accommodate (the take-all
row count when every quota fits), and the declared target is never enlarged to
satisfy sub-stratum quotas.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from ..codes import (
    CLUSTER_OVERSHOOT,
    CLUSTER_QUOTA_SHORT,
    CLUSTER_SUBSTRATA_MISSING,
    CLUSTER_SUBSTRATUM_UNPLANNED,
    SAMPLE_MISSING_CLUSTER_VALUE,
    SAMPLE_MISSING_STRATUM_VALUE,
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


def apportion_quotas(
    sizes: dict[str, int],
    weights: dict[str, Any],
    target: int,
) -> dict[str, int]:
    """Apportion ``target`` over declared groups by ``weight * group size``.

    Shares are ``target * weight * size / sum(weight * size)`` in exact
    rational arithmetic.  Floors are taken first, then the remaining units go
    to the largest fractional remainders; equal remainders are broken by the
    group name's UTF-8 byte order.  Quotas are *not* capped at available size
    here: the caller reports an over-quota as a shortfall rather than silently
    redistributing it outside the cluster.
    """
    declared = byte_sorted(weights)
    weighted = {
        group: Fraction(weights[group]) * sizes.get(group, 0) for group in declared
    }
    denominator = sum(weighted.values(), Fraction(0))
    if target <= 0 or denominator <= 0 or not declared:
        return {group: 0 for group in declared}
    exact = {
        group: Fraction(target) * weighted[group] / denominator for group in declared
    }
    quotas = {
        group: exact[group].numerator // exact[group].denominator for group in declared
    }
    remainder = target - sum(quotas.values())
    order = sorted(
        declared,
        key=lambda group: (-(exact[group] - quotas[group]), group.encode("utf-8")),
    )
    cursor = 0
    while remainder > 0 and order:
        quotas[order[cursor % len(order)]] += 1
        cursor += 1
        remainder -= 1
    return quotas


def plan_cluster_allocation(
    sizes: dict[str, int],
    weights: dict[str, Any],
    target: int,
) -> tuple[dict[str, int], dict[str, int], list[str], bool]:
    """Derive ``(quotas, achieved, over_quota_groups, fallback)`` for a cluster.

    ``quotas`` is the largest-remainder apportionment of the cluster's row
    target.  If any quota exceeds that sub-stratum's actual row count, the
    declared allocation cannot be met: the whole-cluster take-all result is
    retained instead (``achieved`` becomes every declared sub-stratum's
    available size) and ``fallback`` is true.  The same fallback applies when
    the declared sub-strata cannot absorb the cluster target at all (for
    example every declared layer is empty).  In the normal case ``achieved``
    sums to ``target``, so the overall sample stays equal to the target volume
    the selected cluster boundary can accommodate.
    """
    quotas = apportion_quotas(sizes, weights, target)
    over_quota = [
        group for group in byte_sorted(weights) if quotas[group] > sizes.get(group, 0)
    ]
    fallback = bool(over_quota) or (
        target > 0 and sum(quotas.values()) < target
    )
    if fallback:
        achieved = {group: sizes.get(group, 0) for group in byte_sorted(weights)}
    else:
        achieved = {group: quotas[group] for group in byte_sorted(weights)}
    return quotas, achieved, over_quota, fallback


def _allocate_cluster(
    rows: list[dict[str, Any]],
    plan: dict[str, Any],
    cluster_id: str,
    weights: dict[str, Any],
    base_seed: int,
    warnings: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    """Apportion a selected cluster's rows and return its audit record."""
    key_field = plan["key_field"]
    substrata_field = plan["cluster_substrata_field"]
    members = group_items(rows, substrata_field)
    sizes = {group: len(group_rows) for group, group_rows in members.items()}
    target = len(rows)
    quotas, allocation, over_quota, fallback = plan_cluster_allocation(
        sizes, weights, target
    )
    selected: list[str] = []
    for group in byte_sorted(weights):
        available = sizes.get(group, 0)
        quota = quotas[group]
        if quota > available:
            warnings.append(
                make_warning(
                    CLUSTER_QUOTA_SHORT,
                    f"cluster:{cluster_id}:{group}",
                    f"整群 {cluster_id!r} 的次级分层 {group!r} 配额 {quota}、"
                    f"实有 {available}、缺口 {quota - available}；"
                    "保留整群 take-all 结果，未补选新群或新主体",
                    observed=available,
                    expected=quota,
                    gap=quota - available,
                    cluster=cluster_id,
                    substratum=group,
                )
            )
    for group in byte_sorted(members):
        if group not in weights:
            warnings.append(
                make_warning(
                    CLUSTER_SUBSTRATUM_UNPLANNED,
                    f"cluster:{cluster_id}:{group}",
                    f"整群 {cluster_id!r} 的次级分层 {group!r} 未声明权重，配额为 0",
                    observed=sizes[group],
                    expected=0,
                    cluster=cluster_id,
                    substratum=group,
                )
            )
    if fallback:
        selected.extend(byte_sorted(str(row[key_field]) for row in rows))
    else:
        for group in byte_sorted(weights):
            taken = allocation[group]
            if taken and members.get(group):
                keys = [str(row[key_field]) for row in members[group]]
                shuffled = apply_fisher_yates(
                    keys,
                    group_seed(base_seed, "cluster_substratum", f"{cluster_id}|{group}"),
                )
                selected.extend(shuffled[:taken])
    selected_set = set(selected)
    layer_names = byte_sorted(set(sizes) | set(weights))
    achieved = {
        group: sum(
            1
            for row in members.get(group, [])
            if str(row[key_field]) in selected_set
        )
        for group in layer_names
    }
    record = {
        "cluster_size": target,
        "allocation_target": target,
        "substrata_sizes": sizes,
        "quotas": quotas,
        "achieved": achieved,
        "achieved_total": len(selected),
        "shortfall": sum(
            max(0, quotas[group] - achieved.get(group, 0)) for group in quotas
        ),
        "over_quota": byte_sorted(over_quota),
        "fallback": "take-all" if fallback else None,
    }
    return selected, record


def sample(items: list[dict[str, Any]], plan: dict[str, Any]) -> SampleResult:
    warnings: list[dict[str, Any]] = []
    all_keys = sample_keys(items, plan)
    target = resolve_target(plan, len(all_keys), warnings)
    field_name = str(plan["cluster_field"])
    groups = group_items(items, field_name)
    if not items:
        return SampleResult("cluster", [], [], warnings, {"clusters": {}})
    if "" in groups:
        warnings.append(
            make_warning(
                SAMPLE_MISSING_CLUSTER_VALUE,
                f"field:{field_name}",
                "部分记录的群字段为空，已归入空群",
                count=len(groups[""]),
            )
        )
    if target == 0:
        return SampleResult(
            "cluster", [], all_keys, warnings,
            {"population_size": len(all_keys), "target_size": 0, "clusters": {}},
        )
    base_seed = seed_for(plan, items)
    cluster_ids = byte_sorted(groups)
    shuffled_clusters = apply_fisher_yates(cluster_ids, base_seed)
    chosen_clusters: list[str] = []
    chosen_count = 0
    for cluster_id in shuffled_clusters:
        if chosen_count >= target:
            break
        chosen_clusters.append(cluster_id)
        chosen_count += len(groups[cluster_id])
    if chosen_count > target and target < len(all_keys):
        warnings.append(
            make_warning(
                CLUSTER_OVERSHOOT,
                "sampling.cluster",
                f"末群整群纳入导致样本 {chosen_count} 超过目标 {target}",
                observed=chosen_count,
                expected=target,
                overshoot=chosen_count - target,
            )
        )
    substrata_field = plan.get("cluster_substrata_field")
    substrata_weights = plan.get("cluster_substrata_weights")
    selected: list[str] = []
    allocations: dict[str, Any] = {}
    if substrata_field and isinstance(substrata_weights, dict) and substrata_weights:
        if "" in group_items(items, str(substrata_field)):
            warnings.append(
                make_warning(
                    SAMPLE_MISSING_STRATUM_VALUE,
                    f"field:{substrata_field}",
                    "部分记录的群内次级分层字段为空，已归入空分层",
                    count=len(group_items(items, str(substrata_field))[""]),
                )
            )
        for cluster_id in chosen_clusters:
            weights = substrata_weights.get(cluster_id)
            if not isinstance(weights, dict) or not weights:
                warnings.append(
                    make_warning(
                        CLUSTER_SUBSTRATA_MISSING,
                        f"cluster:{cluster_id}",
                        f"已选整群 {cluster_id!r} 未声明群内次级配额权重，"
                        "按整群 take-all 保留全部记录",
                        cluster=cluster_id,
                        observed=len(groups[cluster_id]),
                    )
                )
                keys = [str(row[plan["key_field"]]) for row in groups[cluster_id]]
                selected.extend(byte_sorted(keys))
                allocations[cluster_id] = {
                    "cluster_size": len(groups[cluster_id]),
                    "allocation_target": len(groups[cluster_id]),
                    "substrata_sizes": {
                        group: len(group_rows)
                        for group, group_rows in group_items(
                            groups[cluster_id], str(substrata_field)
                        ).items()
                    },
                    "quotas": {},
                    "achieved": {},
                    "achieved_total": len(groups[cluster_id]),
                    "shortfall": 0,
                    "fallback": "take-all",
                }
                continue
            cluster_keys, record = _allocate_cluster(
                groups[cluster_id], plan, cluster_id, weights, base_seed, warnings
            )
            selected.extend(cluster_keys)
            allocations[cluster_id] = record
        metadata = {
            "population_size": len(all_keys),
            "target_size": target,
            "seed_effective": base_seed,
            "field": field_name,
            "cluster_sizes": {group: len(rows) for group, rows in groups.items()},
            "selected_clusters": chosen_clusters,
            "cluster_boundary_size": chosen_count,
            "algorithm": "one-stage-take-all+substrata-largest-remainder",
            "substrata_field": str(substrata_field),
            "substrata_weights": {
                cluster_id: dict(substrata_weights[cluster_id])
                for cluster_id in chosen_clusters
                if isinstance(substrata_weights.get(cluster_id), dict)
            },
            "cluster_allocations": allocations,
        }
    else:
        for cluster_id in chosen_clusters:
            keys = [str(row[plan["key_field"]]) for row in groups[cluster_id]]
            selected.extend(byte_sorted(keys))
        metadata = {
            "population_size": len(all_keys),
            "target_size": target,
            "seed_effective": base_seed,
            "field": field_name,
            "cluster_sizes": {group: len(rows) for group, rows in groups.items()},
            "selected_clusters": chosen_clusters,
            "algorithm": "one-stage-take-all",
        }
    return SampleResult(
        mode="cluster",
        selected=selected,
        excluded=excluded_keys(all_keys, selected),
        warnings=warnings,
        metadata=metadata,
    )
