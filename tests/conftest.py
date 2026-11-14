"""Shared fixtures plus an autouse network kill-switch."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXED_NOW = "2026-01-01T00:00:00Z"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    """Any attempt to create a socket fails the test."""

    def blocked(*_args, **_kwargs):
        raise AssertionError("network access is disabled in tests")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield


@pytest.fixture
def yaml_plan(tmp_path):
    def write(name: str, data: dict) -> Path:
        path = tmp_path / name
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return path

    return write


@pytest.fixture
def small_dataset():
    from sample_attest.dataset_loader import load_dataset

    return load_dataset(ROOT / "fixtures" / "population_small.csv", "csv", "subject_id")


@pytest.fixture
def stratified_dataset():
    from sample_attest.dataset_loader import load_dataset

    return load_dataset(
        ROOT / "fixtures" / "population_stratified.csv", "csv", "subject_id"
    )


@pytest.fixture
def cluster_dataset():
    from sample_attest.dataset_loader import load_dataset

    return load_dataset(
        ROOT / "fixtures" / "population_cluster.jsonl", "jsonl", "subject_id"
    )


@pytest.fixture
def base_plan():
    return {
        "plan_id": "p-test",
        "dataset": {"path": "unused.csv", "format": "csv"},
        "key_field": "subject_id",
        "mode": "random",
        "seed": 42,
        "size": 3,
        "checks": [{"id": "keys_unique", "type": "key_unique"}],
    }
