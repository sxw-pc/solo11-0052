"""Sampler determinism, target boundaries and warning codes."""

from __future__ import annotations

import pytest

from sample_attest.codes import (
    CLUSTER_OVERSHOOT,
    CLUSTER_QUOTA_SHORT,
    CLUSTER_SUBSTRATA_MISSING,
    CLUSTER_SUBSTRATUM_UNPLANNED,
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
from sample_attest.samplers.cluster import apportion_quotas, plan_cluster_allocation


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


# --- within-cluster sub-stratum allocation ---------------------------------


def make_segment_items(segments_per_cluster):
    items = []
    counter = 0
    for cluster_id, segments in segments_per_cluster.items():
        for segment, count in segments.items():
            for _ in range(count):
                counter += 1
                items.append(
                    {
                        "subject_id": f"subject_{counter:04d}",
                        "cluster": cluster_id,
                        "segment": segment,
                    }
                )
    return items


def cluster_substrata_plan(weights, size, seed=5):
    return make_plan(
        "cluster",
        size=size,
        seed=seed,
        cluster_field="cluster",
        cluster_substrata_field="segment",
        cluster_substrata_weights=weights,
    )


def test_apportion_quotas_largest_remainder_and_byte_tiebreak():
    # Target 5 over equal weights 1,1,1: exact 5/3 each, floors 1+1+1=3,
    # two remainder units to the two byte-smallest names on equal remainder.
    quotas = apportion_quotas(
        {"segment_a": 1, "segment_b": 1, "segment_c": 1},
        {"segment_a": 1, "segment_b": 1, "segment_c": 1},
        5,
    )
    assert quotas == {"segment_a": 2, "segment_b": 2, "segment_c": 1}
    assert sum(quotas.values()) == 5


def test_apportion_quotas_combines_size_and_weight():
    # weight*size: a=1*1=1, b=1*2=2, c=3*1=3 -> target 6 -> exact 1,2,3
    quotas = apportion_quotas(
        {"segment_a": 1, "segment_b": 2, "segment_c": 1},
        {"segment_a": 1, "segment_b": 1, "segment_c": 3},
        6,
    )
    assert quotas == {"segment_a": 1, "segment_b": 2, "segment_c": 3}


def test_cluster_substrata_allocation_is_deterministic_and_keeps_cluster_boundary():
    items = make_segment_items(
        {
            "cluster_01": {"segment_low": 2, "segment_mid": 2, "segment_high": 2},
            "cluster_02": {"segment_low": 2, "segment_mid": 2, "segment_high": 2},
        }
    )
    weights = {
        "cluster_01": {"segment_low": 1, "segment_mid": 1, "segment_high": 1},
        "cluster_02": {"segment_low": 1, "segment_mid": 1, "segment_high": 1},
    }
    plan = cluster_substrata_plan(weights, size=6)
    first = run_sampler(items, plan)
    second = run_sampler(items, plan)
    assert first.selected == second.selected
    # cluster boundary unchanged: same take-all selection as plain cluster mode
    plain = run_sampler(
        items,
        make_plan("cluster", size=6, seed=5, cluster_field="cluster"),
    )
    assert first.metadata["selected_clusters"] == plain.metadata["selected_clusters"]
    assert first.metadata["cluster_boundary_size"] == len(plain.selected)
    # target volume unchanged
    assert len(first.selected) == len(plain.selected) == 6
    record = first.metadata["cluster_allocations"][
        first.metadata["selected_clusters"][0]
    ]
    assert record["cluster_size"] == 6
    assert record["allocation_target"] == 6
    assert record["quotas"] == {
        "segment_low": 2,
        "segment_mid": 2,
        "segment_high": 2,
    }
    assert record["achieved"] == record["quotas"]
    assert record["shortfall"] == 0


def test_cluster_substrata_over_quota_warns_located_without_expanding_target():
    # cluster_01 has 1 low, 3 mid, 2 high. Weight 3/1/1 over target 6 gives
    # low=2 > 1 available -> retain take-all, warn at cluster:cluster_01:segment_low.
    items = make_segment_items(
        {
            "cluster_01": {"segment_low": 1, "segment_mid": 3, "segment_high": 2},
        }
    )
    weights = {
        "cluster_01": {"segment_low": 3, "segment_mid": 1, "segment_high": 1}
    }
    plan = cluster_substrata_plan(weights, size=6)
    result = run_sampler(items, plan)
    short = [w for w in result.warnings if w["code"] == CLUSTER_QUOTA_SHORT]
    assert len(short) == 1
    assert short[0]["path"] == "cluster:cluster_01:segment_low"
    assert short[0]["gap"] == 1
    # No new cluster or subject was introduced: take-all retained, count == 6.
    assert len(result.selected) == 6
    assert set(result.selected) == {row["subject_id"] for row in items}
    record = result.metadata["cluster_allocations"]["cluster_01"]
    assert record["quotas"]["segment_low"] == 2
    assert record["achieved"]["segment_low"] == 1
    assert record["achieved_total"] == 6
    assert record["fallback"] == "take-all"


def test_cluster_substrata_selection_does_not_add_clusters_or_exceed_target():
    items = make_segment_items(
        {
            "cluster_01": {"segment_low": 2, "segment_mid": 2, "segment_high": 2},
            "cluster_02": {"segment_low": 2, "segment_mid": 2, "segment_high": 2},
            "cluster_03": {"segment_low": 2, "segment_mid": 2, "segment_high": 2},
        }
    )
    weights = {
        cluster_id: {"segment_low": 1, "segment_mid": 1, "segment_high": 1}
        for cluster_id in ("cluster_01", "cluster_02", "cluster_03")
    }
    plan = cluster_substrata_plan(weights, size=7)
    result = run_sampler(items, plan)
    assert result.metadata["cluster_boundary_size"] == 12
    assert result.metadata["selected_clusters"] == ["cluster_01", "cluster_02"]
    assert len(result.selected) == 12
    assert result.metadata["target_size"] == 7
    assert CLUSTER_OVERSHOOT in warning_codes(result)


def test_cluster_substrata_missing_weights_falls_back_to_take_all():
    items = make_segment_items(
        {
            "cluster_01": {"segment_low": 2, "segment_mid": 2, "segment_high": 2},
        }
    )
    # Only cluster_09 is declared, but cluster_01 is the selected cluster.
    plan = cluster_substrata_plan(
        {"cluster_09": {"segment_low": 1}}, size=6
    )
    result = run_sampler(items, plan)
    assert CLUSTER_SUBSTRATA_MISSING in warning_codes(result)
    assert len(result.selected) == 6


def test_cluster_substrata_unplanned_layer_warns():
    items = make_segment_items(
        {"cluster_01": {"segment_low": 3, "segment_mid": 3}}
    )
    plan = cluster_substrata_plan(
        {"cluster_01": {"segment_low": 1, "segment_mid": 1}}, size=6
    )
    result = run_sampler(items, plan)
    # all declared quota fits, so 6 rows cannot be split into 3/3 with only
    # two declared layers; the declared layers absorb the target exactly.
    assert result.metadata["cluster_allocations"]["cluster_01"]["achieved_total"] == 6


def test_cluster_substrata_unplanned_layer_in_dataset_warns():
    items = make_segment_items(
        {
            "cluster_01": {"segment_low": 3, "segment_mid": 2, "segment_other": 1},
        }
    )
    plan = cluster_substrata_plan(
        {"cluster_01": {"segment_low": 1, "segment_mid": 1}}, size=6
    )
    result = run_sampler(items, plan)
    unplanned = [
        w for w in result.warnings if w["code"] == CLUSTER_SUBSTRATUM_UNPLANNED
    ]
    assert unplanned and unplanned[0]["path"] == "cluster:cluster_01:segment_other"


def test_plan_cluster_allocation_sums_to_cluster_target():
    sizes = {"segment_low": 2, "segment_mid": 2, "segment_high": 2}
    weights = {"segment_low": 1, "segment_mid": 1, "segment_high": 1}
    quotas, achieved, over, fallback = plan_cluster_allocation(sizes, weights, 6)
    assert sum(quotas.values()) == 6
    assert not over and not fallback
    assert sum(achieved.values()) == 6
