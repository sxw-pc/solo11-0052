"""Seed derivation, fingerprints and diff-locality tests."""

from __future__ import annotations

import hashlib

from sample_attest.fingerprint import (
    effective_seed,
    key_diff,
    population_fingerprint,
    sample_fingerprint_ordered,
    sample_fingerprint_sorted,
    sample_fingerprints,
    task_id,
)


def test_effective_seed_matches_documented_formula():
    expected = int(
        hashlib.sha256("42|random|abc123".encode()).hexdigest()[:16], 16
    )
    assert effective_seed(42, "random", "abc123") == expected


def test_sample_sorted_fingerprint_is_order_independent():
    keys = ["subject_0003", "subject_0001", "subject_0002"]
    assert sample_fingerprint_sorted(keys) == sample_fingerprint_sorted(reversed(keys))


def test_ordered_fingerprint_detects_sequence_change():
    first = ["subject_0001", "subject_0002", "subject_0003"]
    second = ["subject_0003", "subject_0002", "subject_0001"]
    assert sample_fingerprint_ordered(first) != sample_fingerprint_ordered(second)
    assert sample_fingerprint_sorted(first) == sample_fingerprint_sorted(second)


def test_fingerprint_aliases():
    keys = ["subject_0001", "subject_0002"]
    values = sample_fingerprints(keys)
    assert values["sample_fingerprint"] == values["sample_fingerprint_sorted"]
    assert values["sample_fingerprint"] == sample_fingerprint_sorted(keys)
    assert values["sample_fingerprint_ordered"] == sample_fingerprint_ordered(keys)


def test_empty_fingerprints_are_stable():
    assert sample_fingerprint_sorted([]) == hashlib.sha256(b"").hexdigest()
    assert population_fingerprint([]) == sample_fingerprint_sorted([])


def test_task_id_is_stable_and_seed_sensitive():
    plan = {
        "plan_id": "same-plan",
        "mode": "random",
        "seed": 1,
        "size": 2,
        "key_field": "subject_id",
        "dataset": {"path": "x.csv", "format": "csv"},
        "checks": [{"id": "u", "type": "key_unique"}],
    }
    first = task_id(plan, "population")
    assert first == task_id(dict(plan), "population")
    changed = dict(plan, seed=2)
    assert task_id(changed, "population") != first


def test_key_diff_caps_at_twenty_and_counts_all():
    baseline = [f"subject_{i:04d}" for i in range(1, 31)]
    current = [f"subject_{i:04d}" for i in range(21, 51)]
    diff = key_diff(baseline, current)
    assert diff["added_count"] == 20
    assert diff["missing_count"] == 20
    assert len(diff["added"]) + len(diff["missing"]) == 20
    assert diff["truncated"] is True
    assert diff["added"] == sorted(diff["added"])
