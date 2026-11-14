"""Load YAML sampling plans and resolve their dataset paths."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .codes import PLAN_FILE_NOT_FOUND, PLAN_PARSE_ERROR
from .plan_schema import (
    PlanLoadError,
    PlanValidationError,
    ValidationResult,
    issue,
    validate_plan,
)


@dataclass
class LoadedPlan:
    data: dict[str, Any]
    path: Path
    warnings: list[dict[str, Any]]

    @property
    def plan_id(self) -> str:
        return self.data["plan_id"]

    @property
    def dataset_path(self) -> Path:
        raw = Path(self.data["dataset"]["path"])
        if raw.is_absolute():
            return raw
        return (self.path.parent / raw).resolve()

    def canonical(self) -> dict[str, Any]:
        """Return a runtime-free copy suitable for hashing and archiving."""
        return json.loads(json.dumps(self.data, sort_keys=True, ensure_ascii=False))

    def yaml_text(self) -> str:
        return yaml.safe_dump(
            self.data,
            allow_unicode=True,
            sort_keys=True,
            default_flow_style=False,
        )


def load_plan(path: str | Path) -> LoadedPlan:
    plan_path = Path(path)
    if not plan_path.exists() or not plan_path.is_file():
        raise PlanLoadError(
            [
                issue(
                    PLAN_FILE_NOT_FOUND,
                    "plan.path",
                    f"方案文件不存在: {plan_path}",
                    observed=str(plan_path),
                )
            ]
        )
    try:
        text = plan_path.read_text(encoding="utf-8-sig")
        raw = yaml.safe_load(text)
    except (OSError, UnicodeError) as exc:
        raise PlanLoadError(
            [issue(PLAN_PARSE_ERROR, "plan.path", f"无法读取方案: {exc}")]
        ) from exc
    except yaml.YAMLError as exc:
        raise PlanLoadError(
            [issue(PLAN_PARSE_ERROR, "plan", f"YAML 解析失败: {exc}")]
        ) from exc

    result: ValidationResult = validate_plan(raw)
    if result.errors:
        raise PlanValidationError(result.errors)
    return LoadedPlan(data=result.plan, path=plan_path.resolve(), warnings=result.warnings)
