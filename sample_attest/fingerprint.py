"""Deterministic seed derivation, roster hashes and sample fingerprints."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Iterable

UNCLASSIFIED_STRATUM = "unclassified"
ALL_STRATUM = "all"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def _hash_keys(keys: Iterable[str], *, sort_keys: bool) -> str:
    material = list(keys)
    if sort_keys:
        material.sort(key=lambda key: key.encode("utf-8"))
    digest = hashlib.sha256()
    for key in material:
        digest.update(key.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def population_fingerprint(keys: Iterable[str]) -> str:
    """Hash a population roster independently of source row order."""
    return _hash_keys(keys, sort_keys=True)


def sample_fingerprint_sorted(keys: Iterable[str]) -> str:
    """Order-independent sample hash; this is the canonical sample fingerprint."""
    return _hash_keys(keys, sort_keys=True)


def sample_fingerprint_ordered(keys: Iterable[str]) -> str:
    """Hash in sampler emission order, exposing ordering changes."""
    return _hash_keys(keys, sort_keys=False)


def sample_fingerprints(keys: Iterable[str]) -> dict[str, str]:
    material = list(keys)
    sorted_fp = sample_fingerprint_sorted(material)
    ordered_fp = sample_fingerprint_ordered(material)
    return {
        "sample_fingerprint": sorted_fp,
        "sample_fingerprint_sorted": sorted_fp,
        "sample_fingerprint_ordered": ordered_fp,
    }


def effective_seed(seed: int, mode: str, population_hash: str) -> int:
    """Derive a cross-machine stable RNG seed from declared inputs."""
    raw = f"{seed}|{mode}|{population_hash}".encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:16], 16)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def plan_fingerprint(plan: dict[str, Any]) -> str:
    """Fingerprint a normalized plan while ignoring runtime-only keys."""
    runtime_free = {
        key: value for key, value in plan.items() if not str(key).startswith("_")
    }
    return sha256_text(canonical_json(runtime_free))


def task_id(plan: dict[str, Any], population_hash: str) -> str:
    seed = int(plan["seed"])
    mode = str(plan["mode"])
    derived = effective_seed(seed, mode, population_hash)
    material = f"{plan_fingerprint(plan)}|{population_hash}|{derived}"
    return sha256_text(material)[:16]


def _strata_status(added: int, missing: int) -> str:
    if added and missing:
        return "mixed"
    if added:
        return "added"
    if missing:
        return "missing"
    return "clean"


def strata_breakdown(
    added: list[str],
    missing: list[str],
    *,
    strata_field: str | None,
    added_strata: Mapping[str, str] | None = None,
    missing_strata: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Attribute every diff key to a stratum; no key is ever dropped.

    Keys absent from the lookup maps land in the explicit ``unclassified``
    stratum so per-stratum counts always sum to the top-level diff counts.
    Without a ``strata_field`` the breakdown degrades to a single group
    covering the whole diff.
    """
    if not strata_field:
        return [
            {
                "stratum": ALL_STRATUM,
                "status": _strata_status(len(added), len(missing)),
                "added": len(added),
                "missing": len(missing),
            }
        ]
    buckets: dict[str, dict[str, int]] = {}
    for key in added:
        name = (added_strata or {}).get(key, UNCLASSIFIED_STRATUM)
        buckets.setdefault(name, {"added": 0, "missing": 0})["added"] += 1
    for key in missing:
        name = (missing_strata or {}).get(key, UNCLASSIFIED_STRATUM)
        buckets.setdefault(name, {"added": 0, "missing": 0})["missing"] += 1
    return [
        {
            "stratum": name,
            "status": _strata_status(counts["added"], counts["missing"]),
            "added": counts["added"],
            "missing": counts["missing"],
        }
        for name, counts in sorted(
            buckets.items(), key=lambda item: item[0].encode("utf-8")
        )
    ]


def key_diff(
    baseline: Iterable[str],
    current: Iterable[str],
    *,
    limit: int = 20,
    strata_field: str | None = None,
    added_strata: Mapping[str, str] | None = None,
    missing_strata: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Locate added/missing sample keys, capped for terminal readability.

    ``by_strata`` is computed from the complete diff sets, never from the
    truncated display lists.
    """
    left = set(baseline)
    right = set(current)
    added = sorted(right - left, key=lambda key: key.encode("utf-8"))
    missing = sorted(left - right, key=lambda key: key.encode("utf-8"))
    shown_added = added[:limit]
    shown_missing = missing[:limit - len(shown_added)] if limit > len(shown_added) else []
    return {
        "added": shown_added,
        "missing": shown_missing,
        "added_count": len(added),
        "missing_count": len(missing),
        "truncated": len(added) + len(missing) > len(shown_added) + len(shown_missing),
        "by_strata": strata_breakdown(
            added,
            missing,
            strata_field=strata_field,
            added_strata=added_strata,
            missing_strata=missing_strata,
        ),
    }
