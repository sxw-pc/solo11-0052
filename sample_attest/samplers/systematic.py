"""Systematic sampling over a byte-sorted roster."""

from __future__ import annotations

import random
from typing import Any

from ..codes import SAMPLE_DUPLICATE_POSITION, SAMPLE_SYSTEMATIC_WRAP
from .base import (
    SampleResult,
    excluded_keys,
    make_warning,
    resolve_target,
    sample_keys,
    seed_for,
)


def sample(items: list[dict[str, Any]], plan: dict[str, Any]) -> SampleResult:
    warnings: list[dict[str, Any]] = []
    keys = sample_keys(items, plan)
    target = resolve_target(plan, len(keys), warnings)
    if target == 0:
        return SampleResult(
            "systematic", [], keys, warnings,
            {"population_size": len(keys), "target_size": 0},
        )
    population_size = len(keys)
    interval = population_size // target
    rng = random.Random(seed_for(plan, items))
    start = rng.randrange(interval) if interval > 1 else 0
    selected: list[str] = []
    seen: set[str] = set()
    wrapped = False
    for offset in range(target):
        position = start + offset * interval
        if position >= population_size:
            position -= population_size
            wrapped = True
        key = keys[position]
        if key in seen:
            warnings.append(
                make_warning(
                    SAMPLE_DUPLICATE_POSITION,
                    f"position:{position}",
                    f"系统抽样位置 {position} 产生重复主键 {key!r}，已剔除",
                    key=key,
                )
            )
            continue
        seen.add(key)
        selected.append(key)
    if wrapped:
        warnings.append(
            make_warning(
                SAMPLE_SYSTEMATIC_WRAP,
                "sampling.systematic",
                "系统抽样发生了一次越界回绕",
            )
        )
    return SampleResult(
        mode="systematic",
        selected=selected,
        excluded=excluded_keys(keys, selected),
        warnings=warnings,
        metadata={
            "population_size": population_size,
            "target_size": target,
            "interval": interval,
            "start": start,
            "seed_effective": seed_for(plan, items),
            "algorithm": "systematic",
        },
    )
