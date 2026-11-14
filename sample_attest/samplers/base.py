"""Shared sampler types and deterministic helper routines."""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..codes import (
    SAMPLE_EMPTY_POPULATION,
    SAMPLE_SIZE_EXCEEDS_POPULATION,
    SAMPLE_TARGET_ZERO,
)
from ..fingerprint import effective_seed, population_fingerprint


def byte_sorted(values: Iterable[str]) -> list[str]:
    return sorted(values, key=lambda value: value.encode("utf-8"))


@dataclass
class SampleResult:
    mode: str
    selected: list[str]
    excluded: list[str]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def selected_sorted(self) -> list[str]:
        return byte_sorted(self.selected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "selected": list(self.selected),
            "excluded": list(self.excluded),
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }


def make_warning(code: str, path: str, message: str, **details: Any) -> dict[str, Any]:
    warning: dict[str, Any] = {"code": code, "path": path, "message": message}
    warning.update(details)
    return warning


def sample_keys(items: list[dict[str, Any]], plan: dict[str, Any]) -> list[str]:
    field_name = plan["key_field"]
    return byte_sorted(str(item[field_name]) for item in items)


def seed_for(plan: dict[str, Any], items: list[dict[str, Any]]) -> int:
    runtime = plan.get("_runtime") or {}
    if isinstance(runtime.get("seed_effective"), int):
        return runtime["seed_effective"]
    pop_hash = runtime.get("population_fingerprint")
    if not pop_hash:
        pop_hash = population_fingerprint(sample_keys(items, plan))
    return effective_seed(int(plan["seed"]), str(plan["mode"]), pop_hash)


def resolve_target(
    plan: dict[str, Any],
    population_size: int,
    warnings: list[dict[str, Any]],
) -> int:
    if population_size == 0:
        warnings.append(
            make_warning(SAMPLE_EMPTY_POPULATION, "dataset", "总体为空，样本为空")
        )
        return 0
    if "size" in plan:
        target = int(plan["size"])
    else:
        target = math.ceil(population_size * float(plan["rate"]))
    if target <= 0:
        warnings.append(
            make_warning(SAMPLE_TARGET_ZERO, "plan.size", "目标样本量为 0，样本为空")
        )
        return 0
    if target > population_size:
        warnings.append(
            make_warning(
                SAMPLE_SIZE_EXCEEDS_POPULATION,
                "plan.size",
                f"目标样本量 {target} 超过总体 {population_size}，已截断",
                observed=target,
                expected=population_size,
            )
        )
        return population_size
    return target


def apply_fisher_yates(keys: list[str], seed: int) -> list[str]:
    """Return a randomized copy using an explicit Fisher-Yates shuffle."""
    material = list(keys)
    rng = random.Random(seed)
    for index in range(len(material) - 1, 0, -1):
        swap = rng.randrange(index + 1)
        material[index], material[swap] = material[swap], material[index]
    return material


def group_items(
    items: list[dict[str, Any]],
    field_name: str,
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        value = str(item.get(field_name, ""))
        groups.setdefault(value, []).append(item)
    return {key: groups[key] for key in byte_sorted(groups)}


def group_seed(base_seed: int, label: str, value: str) -> int:
    material = f"{base_seed}|{label}|{value}".encode("utf-8")
    return int(hashlib.sha256(material).hexdigest()[:16], 16)


def excluded_keys(all_keys: Iterable[str], selected: Iterable[str]) -> list[str]:
    chosen = set(selected)
    return [key for key in byte_sorted(all_keys) if key not in chosen]


def empty_result(
    mode: str, warnings: list[dict[str, Any]], metadata: dict[str, Any] | None = None
) -> SampleResult:
    return SampleResult(
        mode=mode,
        selected=[],
        excluded=[],
        warnings=warnings,
        metadata=metadata or {},
    )
