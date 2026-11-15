"""Shared result types for verification and reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckResult:
    rule_id: str
    type: str
    status: str
    code: str | None
    message: str
    observed: Any
    expected: Any
    location: str
    entries: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "type": self.type,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "observed": self.observed,
            "expected": self.expected,
            "location": self.location,
            "entries": list(self.entries),
        }


@dataclass
class VerificationResult:
    checks: list[CheckResult]
    sample_warnings: list[dict[str, Any]]
    plan_warnings: list[dict[str, Any]]
    strict: bool
    status: str
    strict_failed: bool
    counts: dict[str, int]
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "strict": self.strict,
            "strict_failed": self.strict_failed,
            "counts": dict(self.counts),
            "checks": [check.to_dict() for check in self.checks],
            "sample_warnings": list(self.sample_warnings),
            "plan_warnings": list(self.plan_warnings),
            "warnings": list(self.warnings),
        }


