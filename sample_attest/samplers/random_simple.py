"""Simple random sampling with an explicitly seeded Fisher-Yates shuffle."""

from __future__ import annotations

from typing import Any

from .base import (
    SampleResult,
    apply_fisher_yates,
    excluded_keys,
    resolve_target,
    sample_keys,
    seed_for,
)


def sample(items: list[dict[str, Any]], plan: dict[str, Any]) -> SampleResult:
    keys = sample_keys(items, plan)
    warnings: list[dict[str, Any]] = []
    target = resolve_target(plan, len(keys), warnings)
    if target == 0:
        return SampleResult(
            mode="random",
            selected=[],
            excluded=keys,
            warnings=warnings,
            metadata={"population_size": len(keys), "target_size": 0, "seed_effective": seed_for(plan, items)},
        )
    shuffled = apply_fisher_yates(keys, seed_for(plan, items))
    selected = shuffled[:target]
    return SampleResult(
        mode="random",
        selected=selected,
        excluded=excluded_keys(keys, selected),
        warnings=warnings,
        metadata={
            "population_size": len(keys),
            "target_size": target,
            "seed_effective": seed_for(plan, items),
            "algorithm": "fisher-yates",
        },
    )
