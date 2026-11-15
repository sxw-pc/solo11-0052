"""End-to-end orchestration shared by the CLI and tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .codes import VERIFY_NO_BASELINE, VERIFY_NOT_REPRODUCIBLE
from .dataset_loader import Dataset, load_dataset
from .explain import explain_sample_diff
from .fingerprint import (
    effective_seed,
    key_diff,
    sample_fingerprint_sorted,
    sample_fingerprints,
    task_id,
)
from .ledger import Ledger
from .plan_loader import LoadedPlan, load_plan
from .reporter import build_report, report_markdown, write_reports
from .samplers import run_sampler
from .verifier import run_checks

DEFAULT_DB = Path(".sample_attest") / "ledger.db"


class VerifyError(Exception):
    def __init__(self, code: str, message: str, **extra: Any):
        self.code = code
        self.message = message
        self.extra = extra
        super().__init__(message)


@dataclass
class Prepared:
    loaded: LoadedPlan
    plan: dict[str, Any]
    dataset: Dataset
    seed_effective: int
    task_id: str


@dataclass
class RunOutcome:
    report: dict[str, Any]
    report_markdown: str
    paths: dict[str, str]
    run_id: int
    prepared: Prepared
    sample: Any
    verification: Any


def utc_now(clock: str | datetime | None = None) -> str:
    if isinstance(clock, str):
        return clock
    if isinstance(clock, datetime):
        value = clock
    else:
        value = datetime.now(timezone.utc)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def prepare(plan_path: str | Path) -> Prepared:
    loaded = load_plan(plan_path)
    dataset = load_dataset(
        loaded.dataset_path,
        loaded.data["dataset"]["format"],
        loaded.data["key_field"],
        loaded.data.get("subject_field"),
    )
    seed = effective_seed(
        int(loaded.data["seed"]), str(loaded.data["mode"]), dataset.population_fingerprint
    )
    plan = dict(loaded.data)
    plan["_runtime"] = {
        "population_fingerprint": dataset.population_fingerprint,
        "seed_effective": seed,
    }
    ident = task_id(loaded.data, dataset.population_fingerprint)
    return Prepared(loaded=loaded, plan=plan, dataset=dataset, seed_effective=seed, task_id=ident)


def run_plan(
    plan_path: str | Path,
    *,
    out_dir: str | Path,
    db_path: str | Path = DEFAULT_DB,
    strict: bool = False,
    clock: str | datetime | None = None,
) -> RunOutcome:
    prepared = prepare(plan_path)
    sample = run_sampler(prepared.dataset.rows, prepared.plan)
    verification = run_checks(
        prepared.plan,
        prepared.dataset,
        sample,
        strict=strict,
        plan_warnings=prepared.loaded.warnings,
    )
    generated_at = utc_now(clock)
    report = build_report(
        prepared.plan,
        prepared.dataset,
        sample,
        verification,
        task_id=prepared.task_id,
        seed_effective=prepared.seed_effective,
        generated_at=generated_at,
    )
    markdown = report_markdown(report)
    paths = write_reports(out_dir, report)
    ledger = Ledger(db_path)
    run_id = ledger.record_run(
        report=report,
        plan_yaml=prepared.loaded.yaml_text(),
        sample_keys=sample.selected_sorted,
        report_markdown=markdown,
        created_at=generated_at,
    )
    return RunOutcome(
        report=report,
        report_markdown=markdown,
        paths=paths,
        run_id=run_id,
        prepared=prepared,
        sample=sample,
        verification=verification,
    )


def verify_plan(
    plan_path: str | Path,
    *,
    db_path: str | Path = DEFAULT_DB,
) -> dict[str, Any]:
    prepared = prepare(plan_path)
    sample = run_sampler(prepared.dataset.rows, prepared.plan)
    current_fp = sample_fingerprint_sorted(sample.selected)
    ledger = Ledger(db_path)
    baseline = ledger.get_latest_by_plan(prepared.loaded.plan_id)
    if baseline is None:
        raise VerifyError(
            VERIFY_NO_BASELINE,
            f"台账中没有 plan_id={prepared.loaded.plan_id} 的历史记录",
            plan_id=prepared.loaded.plan_id,
        )
    diff = key_diff(baseline["sample_keys"], sample.selected)
    reproducible = current_fp == baseline["sample_fingerprint"]
    fingerprints = sample_fingerprints(sample.selected)
    return {
        "status": "REPRODUCIBLE" if reproducible else "NOT_REPRODUCIBLE",
        "code": None if reproducible else VERIFY_NOT_REPRODUCIBLE,
        "plan_id": prepared.loaded.plan_id,
        "task_id": prepared.task_id,
        "baseline_task_id": baseline["task_id"],
        "baseline_run_id": baseline["run_id"],
        "sample_fingerprint": current_fp,
        "baseline_sample_fingerprint": baseline["sample_fingerprint"],
        "fingerprints": fingerprints,
        "sample_count": len(sample.selected),
        "diff": diff,
        "diff_explanations": explain_sample_diff(diff),
    }
