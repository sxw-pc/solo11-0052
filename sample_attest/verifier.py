"""Deterministic verification of declared sampling checks."""

from __future__ import annotations

from typing import Any

from .dataset_loader import Dataset
from .samplers.base import SampleResult
from .verification_types import CheckResult, VerificationResult
from .verifier_checks import (
    _coverage_check,
    _decode_check,
    _overlap_check,
    _quota_check,
    _rate_check,
)


def run_checks(
    plan: dict[str, Any],
    dataset: Dataset,
    result: SampleResult,
    *,
    strict: bool = False,
    plan_warnings: list[dict[str, Any]] | None = None,
) -> VerificationResult:
    checks: list[CheckResult] = []
    for check in plan.get("checks", []):
        check_type = check["type"]
        if check_type == "quota":
            item = _quota_check(check, plan, dataset, result)
        elif check_type == "rate_range":
            item = _rate_check(check, dataset, result)
        elif check_type == "coverage":
            item = _coverage_check(check, plan, dataset, result)
        elif check_type == "key_unique":
            item = _decode_check(check, dataset, result)
        else:
            item = _overlap_check(check, dataset, result)
        checks.append(item)
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for item in checks:
        counts[item.status] = counts.get(item.status, 0) + 1
    plan_warnings = list(plan_warnings or [])
    sample_warnings = list(result.warnings)
    verification_warnings = [
        entry for item in checks if item.status == "warn" for entry in item.entries
    ]
    all_warnings = plan_warnings + sample_warnings + verification_warnings
    strict_failed = bool(strict and all_warnings)
    if counts.get("fail", 0) or strict_failed:
        status = "fail"
    elif counts.get("warn", 0) or all_warnings:
        status = "warn"
    else:
        status = "pass"
    return VerificationResult(
        checks=checks,
        sample_warnings=sample_warnings,
        plan_warnings=plan_warnings,
        strict=strict,
        status=status,
        strict_failed=strict_failed,
        counts=counts,
        warnings=all_warnings,
    )
