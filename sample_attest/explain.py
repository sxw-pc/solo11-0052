"""Turn verification failures and warnings into located attribution entries."""

from __future__ import annotations

from typing import Any

from .verifier import VerificationResult


def explain_verification(verification: VerificationResult) -> list[dict[str, Any]]:
    explanations: list[dict[str, Any]] = []
    for check in verification.checks:
        if check.status == "pass":
            continue
        if check.entries:
            for entry in check.entries:
                item = {
                    "rule_id": check.rule_id,
                    "check_type": check.type,
                    "severity": "failure" if check.status == "fail" else "warning",
                    "code": entry.get("code", check.code),
                    "location": entry.get("path", check.location),
                    "message": entry.get("message", check.message),
                    "observed": entry.get("observed", check.observed),
                    "expected": entry.get("expected", check.expected),
                }
                if "gap" in entry:
                    item["gap"] = entry["gap"]
                explanations.append(item)
        else:
            explanations.append(
                {
                    "rule_id": check.rule_id,
                    "check_type": check.type,
                    "severity": "failure" if check.status == "fail" else "warning",
                    "code": check.code,
                    "location": check.location,
                    "message": check.message,
                    "observed": check.observed,
                    "expected": check.expected,
                }
            )
    return explanations


def explain_plan_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": "plan",
            "check_type": "plan_validation",
            "severity": "warning",
            "code": item.get("code"),
            "location": item.get("path", "plan"),
            "message": item.get("message", ""),
            "observed": item.get("observed"),
            "expected": item.get("expected"),
        }
        for item in warnings
    ]


def explain_sample_diff(diff: dict[str, Any]) -> list[str]:
    """Produce short human-readable locality lines for reproducibility diffs."""
    lines: list[str] = []
    if diff.get("added_count"):
        shown = ", ".join(diff.get("added", []))
        lines.append(f"新增样本 {diff['added_count']} 个: {shown}")
    if diff.get("missing_count"):
        shown = ", ".join(diff.get("missing", []))
        lines.append(f"缺失样本 {diff['missing_count']} 个: {shown}")
    if diff.get("truncated"):
        lines.append("差异条目已截断，仅展示前 20 条")
    return lines
