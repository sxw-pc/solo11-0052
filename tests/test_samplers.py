"""Sampler determinism, target boundaries and warning codes."""

from __future__ import annotations

import pytest

from sample_attest.codes import (
    CLUSTER_OVERSHOOT,
    SAMPLE_EMPTY_POPULATION,
    SAMPLE_SIZE_EXCEEDS_POPULATION,
    SAMPLE_TARGET_ZERO,
    STRATUM_GROUP_MISSING,
    STRATUM_QUOTA_SHORT,
)
from sample_attest.samplers import (
    UnknownModeError,
    get_sampler,
    registered_modes,
    run_sampler,
)


def make_items(keys, region="region_A", cluster="cluster_01"):
    return [
        {"subject_id": key, "region": region, "cluster": cluster}
        for key in keys
    ]


def make_plan(mode="random", **overrides):
    plan = {
        "plan_id": "sampler-test",
        "dataset": {"path": "unused.csv", "format": "csv"},
        "key_field": "subject_id",
        "mode": mode,
        "seed": 17,
        "size": 2,
        "checks": [{"id": "u", "type": "key_unique"}],
    }
    plan.update(overrides)
    return plan


def warning_codes(result):
    return [item["code"] for item in result.warnings]


def test_registry_and_unknown_mode():
    assert registered_modes() == ["cluster", "random", "stratified", "systematic"]
    assert get_sampler("random").__name__.endswith("random_simple")
    with pytest.raises(UnknownModeError) as exc:
        get_sampler("weighted")
    assert exc.value.code == "PLAN_UNKNOWN_MODE"


def test_random_is_byte_for_byte_reproducible():
    items = make_items([f"subject_{i:04d}" for i in range(1, 11)])
    plan = make_plan(size=4)
    runs = [run_sampler(items, plan) for _ in range(3)]
    assert runs[0].selected == runs[1].selected == runs[2].selected
    assert all(len(run.selected) == 4 for run in runs)
    assert set(runs[0].selected).isdisjoint(runs[0].excluded)


def test_rate_only_plan_targets_ceiling():
    items = make_items([f"subject_{i:04d}" for i in range(1, 8)])
    plan = make_plan(rate=0.5)
    plan.pop("size")
    result = run_sampler(items, plan)
    assert result.metadata["target_size"] == 4
    assert len(result.selected) == 4


def test_size_equals_population_returns_all():
    items = make_items(["subject_0001", "subject_0002", "subject_0003"])
    result = run_sampler(items, make_plan(size=3))
    assert sorted(result.selected) == sorted([row["subject_id"] for row in items])
    assert result.excluded == []


def test_size_exceeds_population_warns_and_clamps():
    items = make_items(["subject_0001", "subject_0002"])
    result = run_sampler(items, make_plan(size=9))
    assert SAMPLE_SIZE_EXCEEDS_POPULATION in warning_codes(result)
    assert len(result.selected) == 2
    assert result.excluded == []


def test_direct_zero_size_rate_and_rate_over_one():
    items = make_items(["subject_0001", "subject_0002", "subject_0003"])
    zero_size = run_sampler(items, make_plan(size=0))
    assert SAMPLE_TARGET_ZERO in warning_codes(zero_size)
    plan = make_plan(rate=0)
    plan.pop("size")
    zero_rate = run_sampler(items, plan)
    assert SAMPLE_TARGET_ZERO in warning_codes(zero_rate)
    plan = make_plan(rate=1.5)
    plan.pop("size")
    over = run_sampler(items, plan)
    assert SAMPLE_SIZE_EXCEEDS_POPULATION in warning_codes(over)
    assert len(over.selected) == 3


def test_rate_one_returns_all_without_warning():
    items = make_items(["subject_0001", "subject_0002", "subject_0003"])
    plan = make_plan(rate=1)
    plan.pop("size")
    result = run_sampler(items, plan)
    assert len(result.selected) == 3
    assert warning_codes(result) == []


def test_systematic_interval_and_reproducibility():
    items = make_items([f"subject_{i:04d}" for i in range(1, 13)])
    plan = make_plan("systematic", size=4)
    first = run_sampler(items, plan)
    second = run_sampler(items, plan)
    assert first.selected == second.selected
    assert first.metadata["interval"] == 3
    assert len(first.selected) == 4


@pytest.mark.parametrize("mode", ["random", "stratified", "systematic", "cluster"])
def test_empty_population_is_explicit(mode):
    plan = make_plan(mode, size=2, strata_field="region", cluster_field="cluster")
    result = run_sampler([], plan)
    assert result.selected == []
    assert SAMPLE_EMPTY_POPULATION in warning_codes(result)


def test_stratified_quota_exact_and_order_deterministic():
    items = (
        make_items(["subject_0001", "subject_0002", "subject_0003"], "region_A")
        + make_items(["subject_0004", "subject_0005"], "region_B")
        + make_items(["subject_0006"], "region_C")
    )
    plan = make_plan(
        "stratified",
        size=4,
        strata_field="region",
        expected_distribution={"region_A": 2, "region_B": 1, "region_C": 1},
    )
    first = run_sampler(items, plan)
    second = run_sampler(items, plan)
    assert first.selected == second.selected
    assert first.metadata["quotas"] == {"region_A": 2, "region_B": 1, "region_C": 1}
    assert len(first.selected) == 4


def test_stratified_quota_short_warns_with_gap():
    items = (
        make_items(["subject_0001", "subject_0002"], "region_A")
        + make_items(["subject_0003"], "region_B")
    )
    plan = make_plan(
        "stratified",
        size=3,
        strata_field="region",
        expected_distribution={"region_A": 3, "region_B": 0},
    )
    result = run_sampler(items, plan)
    short = [w for w in result.warnings if w["code"] == STRATUM_QUOTA_SHORT]
    assert short and short[0]["gap"] == 1


def test_stratified_missing_expected_group_warns():
    items = make_items(["subject_0001", "subject_0002"], "region_A")
    plan = make_plan(
        "stratified",
        size=2,
        strata_field="region",
        expected_distribution={"region_A": 1, "region_Z": 1},
    )
    result = run_sampler(items, plan)
    assert STRATUM_GROUP_MISSING in warning_codes(result)


def test_cluster_take_all_and_overshoot_warning():
    items = (
        make_items(["subject_0001", "subject_0002", "subject_0003"], cluster="cluster_01")
        + make_items(["subject_0004", "subject_0005", "subject_0006"], cluster="cluster_02")
        + make_items(["subject_0007", "subject_0008", "subject_0009"], cluster="cluster_03")
    )
    plan = make_plan("cluster", size=5, cluster_field="cluster")
    result = run_sampler(items, plan)
    assert len(result.selected) == 6
    assert CLUSTER_OVERSHOOT in warning_codes(result)
    assert result.metadata["selected_clusters"]
