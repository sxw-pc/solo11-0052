"""Deterministic one-stage cluster sampling.

Clusters are selected in a seeded order until the declared row target is met.
All rows in every selected cluster are included (one-stage cluster take-all).
The final cluster may cause an overshoot; this is reported, never hidden.
"""

from __future__ import annotations

from typing import Any

from ..codes import CLUSTER_OVERSHOOT, SAMPLE_MISSING_CLUSTER_VALUE
from .base import (
    SampleResult,
    apply_fisher_yates,
    byte_sorted,
    excluded_keys,
    group_items,
    make_warning,
    resolve_target,
    sample_keys,
    seed_for,
)


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
    selected: list[str] = []
    for cluster_id in chosen_clusters:
        keys = [str(row[plan["key_field"]]) for row in groups[cluster_id]]
        selected.extend(byte_sorted(keys))
    return SampleResult(
        mode="cluster",
        selected=selected,
        excluded=excluded_keys(all_keys, selected),
        warnings=warnings,
        metadata={
            "population_size": len(all_keys),
            "target_size": target,
            "seed_effective": base_seed,
            "field": field_name,
            "cluster_sizes": {group: len(rows) for group, rows in groups.items()},
            "selected_clusters": chosen_clusters,
            "algorithm": "one-stage-take-all",
        },
    )
