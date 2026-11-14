"""Deterministic JSON and Markdown report rendering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .dataset_loader import Dataset
from .explain import explain_verification
from .fingerprint import sample_fingerprints
from .samplers.base import SampleResult
from .verifier import VerificationResult

COMPLIANCE_STATEMENT = (
    "本工具仅用于对本人所有或已获书面授权本地数据集进行抽样过程核验"
)


def build_report(
    plan: dict[str, Any],
    dataset: Dataset,
    sample: SampleResult,
    verification: VerificationResult,
    *,
    task_id: str,
    seed_effective: int,
    generated_at: str,
) -> dict[str, Any]:
    sorted_selected = sample.selected_sorted
    fingerprints = sample_fingerprints(sample.selected)
    explanations = explain_verification(verification)
    return {
        "schema_version": "1.0",
        "task_id": task_id,
        "plan_id": plan["plan_id"],
        "mode": plan["mode"],
        "seed": plan["seed"],
        "seed_effective": seed_effective,
        "generated_at": generated_at,
        "overall_status": verification.status,
        "compliance": COMPLIANCE_STATEMENT,
        "dataset": dataset.metadata(),
        "sample": {
            "count": len(sample.selected),
            "target_size": sample.metadata.get("target_size"),
            "selected_keys_ordered": list(sample.selected),
            "selected_keys_sorted": sorted_selected,
            "excluded_count": len(sample.excluded),
            "excluded_keys": list(sample.excluded),
            "warnings": list(sample.warnings),
            "metadata": dict(sample.metadata),
            "fingerprints": fingerprints,
        },
        "verification": verification.to_dict(),
        "explanations": explanations,
    }


def report_json_text(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _cell(value: Any, limit: int = 90) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _status_label(status: str) -> str:
    return {"pass": "通过", "warn": "警告", "fail": "失败"}.get(status, status)


def report_markdown(report: dict[str, Any]) -> str:
    dataset = report["dataset"]
    sample = report["sample"]
    verification = report["verification"]
    fingerprints = sample["fingerprints"]
    lines = [
        "# 抽样签验报告",
        "",
        f"> 合规声明：{COMPLIANCE_STATEMENT}。",
        "> 本工具不进行统计推断，仅核验方案声明与抽样执行结果的一致性。",
        "",
        f"- 任务号: `{report['task_id']}`",
        f"- 方案 ID: `{report['plan_id']}`",
        f"- 抽样模式: `{report['mode']}`",
        f"- 生成时间: `{report['generated_at']}`",
        f"- 总体名单指纹: `{dataset['population_fingerprint']}`",
        f"- 样本指纹: `{fingerprints['sample_fingerprint']}`",
        "",
        "## 总体摘要",
        "",
        "| 项目 | 值 |",
        "|---|---|",
        f"| 总体行数 | {dataset['row_count']} |",
        f"| 样本数量 | {sample['count']} |",
        f"| 目标数量 | {sample.get('target_size')} |",
        f"| 实际抽样率 | {sample['count'] / dataset['row_count']:.12g} |",
        f"| 核验状态 | {_status_label(verification['status'])} |",
        f"| 严格模式 | {'是' if verification['strict'] else '否'} |",
        f"| 通过/警告/失败 | {verification['counts'].get('pass', 0)} / "
        f"{verification['counts'].get('warn', 0)} / {verification['counts'].get('fail', 0)} |",
        "",
        "## 确定性指纹",
        "",
        f"- `sample_fingerprint`: `{fingerprints['sample_fingerprint']}`（排序后，规范指纹）",
        f"- `sample_fingerprint_sorted`: `{fingerprints['sample_fingerprint_sorted']}`",
        f"- `sample_fingerprint_ordered`: `{fingerprints['sample_fingerprint_ordered']}`（与抽样顺序相关）",
        "",
        "## 核验项",
        "",
        "| 规则 ID | 类型 | 状态 | 观测值 | 期望值 | 定位 |",
        "|---|---|---|---|---|---|",
    ]
    for check in verification["checks"]:
        lines.append(
            f"| {_cell(check['rule_id'], 40)} | {_cell(check['type'], 40)} | "
            f"{_status_label(check['status'])} | {_cell(check['observed'])} | "
            f"{_cell(check['expected'])} | {_cell(check['location'])} |"
        )
    lines.extend(["", "## 归因清单", ""])
    if report["explanations"]:
        lines.extend(
            [
                "| 规则 | 严重度 | 代码 | 定位 | 说明 | 缺口 |",
                "|---|---|---|---|---|---|",
            ]
        )
        for item in report["explanations"]:
            lines.append(
                f"| {_cell(item['rule_id'], 40)} | {item['severity']} | "
                f"{_cell(item.get('code'), 50)} | {_cell(item['location'])} | "
                f"{_cell(item['message'], 120)} | {_cell(item.get('gap', ''), 20)} |"
            )
    else:
        lines.append("无失败或警告归因。")
    lines.extend(["", "## 告警与备注", ""])
    warnings = verification.get("warnings", [])
    if warnings:
        for warning in warnings:
            lines.append(
                f"- `{warning.get('code')}` {warning.get('path', '')}: "
                f"{warning.get('message', '')}"
            )
    else:
        lines.append("无告警。")
    lines.extend(
        [
            "",
            "## 可复现性说明",
            "",
            "同一数据集、同一方案、同一声明种子重跑时，`sample_fingerprint` 必须一致。"
            "`sample_fingerprint_ordered` 额外约束抽样顺序。",
            "",
            f"> {COMPLIANCE_STATEMENT}。",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(out_dir: str | Path, report: dict[str, Any]) -> dict[str, str]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "report.json"
    markdown_path = directory / "report.md"
    json_path.write_text(report_json_text(report), encoding="utf-8", newline="\n")
    markdown_path.write_text(report_markdown(report), encoding="utf-8", newline="\n")
    return {"report_json": str(json_path), "report_markdown": str(markdown_path)}
