"""Sampler registry keyed by the plan's declared sampling mode."""

from __future__ import annotations

from types import ModuleType
from typing import Any

from ..codes import PLAN_UNKNOWN_MODE
from ..plan_schema import MODES
from . import cluster, random_simple, stratified, systematic
from .base import SampleResult, make_warning

REGISTRY: dict[str, ModuleType] = {
    "random": random_simple,
    "stratified": stratified,
    "systematic": systematic,
    "cluster": cluster,
}


class UnknownModeError(Exception):
    def __init__(self, mode: str):
        self.code = PLAN_UNKNOWN_MODE
        self.mode = mode
        super().__init__(f"unknown sampling mode: {mode}")


def registered_modes() -> list[str]:
    return sorted(REGISTRY)


def get_sampler(mode: str) -> ModuleType:
    try:
        return REGISTRY[mode]
    except KeyError as exc:
        raise UnknownModeError(mode) from exc


def run_sampler(items: list[dict[str, Any]], plan: dict[str, Any]) -> SampleResult:
    mode = str(plan.get("mode", ""))
    return get_sampler(mode).sample(items, plan)


__all__ = [
    "MODES",
    "REGISTRY",
    "SampleResult",
    "UnknownModeError",
    "get_sampler",
    "make_warning",
    "registered_modes",
    "run_sampler",
]
