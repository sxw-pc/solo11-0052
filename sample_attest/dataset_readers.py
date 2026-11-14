"""CSV and JSONL row readers used by :mod:`dataset_loader`."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .codes import (
    DATASET_BLANK_LINE,
    DATASET_EMPTY,
    DATASET_ENCODING_ERROR,
    DATASET_MISSING_KEY,
    DATASET_MISSING_KEY_FIELD,
    DATASET_PARSE_ERROR,
)
from .dataset_loader import (
    Dataset,
    DatasetLoadError,
    _finalize,
    _register_row,
    issue,
    normalize_key,
)


def load_csv(path: Path, key_field: str) -> Dataset:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    rows: list[dict[str, str]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration:
                raise DatasetLoadError(
                    [issue(DATASET_EMPTY, "dataset", "CSV 文件为空")]
                )
            fieldnames = [name.strip() for name in header]
            if not fieldnames or any(not name for name in fieldnames):
                raise DatasetLoadError(
                    [issue(DATASET_PARSE_ERROR, "dataset.header", "CSV 表头为空或含空字段名")]
                )
            if len(set(fieldnames)) != len(fieldnames):
                raise DatasetLoadError(
                    [issue(DATASET_PARSE_ERROR, "dataset.header", "CSV 表头字段名重复")]
                )
            if key_field not in fieldnames:
                raise DatasetLoadError(
                    [
                        issue(
                            DATASET_MISSING_KEY_FIELD,
                            f"dataset.{key_field}",
                            f"数据集中不存在主键字段 {key_field}",
                        )
                    ]
                )
            seen: dict[str, int] = {}
            for raw_row in reader:
                line = reader.line_num
                if not raw_row or all(cell.strip() == "" for cell in raw_row):
                    warnings.append(
                        issue(
                            DATASET_BLANK_LINE,
                            "dataset.line",
                            f"第 {line} 行为空行，已跳过",
                            line=line,
                        )
                    )
                    continue
                if len(raw_row) != len(fieldnames):
                    errors.append(
                        issue(
                            DATASET_PARSE_ERROR,
                            "dataset.row",
                            f"第 {line} 行字段数为 {len(raw_row)}，期望 {len(fieldnames)}",
                            line=line,
                        )
                    )
                    continue
                row = dict(zip(fieldnames, raw_row, strict=True))
                _register_row(row, line, key_field, seen, errors)
                rows.append(row)
    except UnicodeDecodeError as exc:
        raise DatasetLoadError(
            [issue(DATASET_ENCODING_ERROR, "dataset.path", f"CSV 编码不是 UTF-8: {exc}")]
        ) from exc
    if errors:
        raise DatasetLoadError(errors)
    if not rows:
        raise DatasetLoadError([issue(DATASET_EMPTY, "dataset", "CSV 没有数据行")])
    return _finalize(path, "csv", key_field, rows, fieldnames, warnings)


def load_jsonl(path: Path, key_field: str) -> Dataset:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    rows: list[dict[str, str]] = []
    fieldnames: list[str] = []
    seen: dict[str, int] = {}
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line, raw in enumerate(handle, start=1):
                if not raw.strip():
                    warnings.append(
                        issue(
                            DATASET_BLANK_LINE,
                            "dataset.line",
                            f"第 {line} 行为空行，已跳过",
                            line=line,
                        )
                    )
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError as exc:
                    errors.append(
                        issue(
                            DATASET_PARSE_ERROR,
                            "dataset.line",
                            f"第 {line} 行 JSON 解析失败: {exc.msg}",
                            line=line,
                        )
                    )
                    continue
                if not isinstance(obj, dict):
                    errors.append(
                        issue(
                            DATASET_PARSE_ERROR,
                            "dataset.line",
                            f"第 {line} 行不是 JSON 对象",
                            line=line,
                        )
                    )
                    continue
                row: dict[str, str] = {}
                for name, value in obj.items():
                    if name not in fieldnames:
                        fieldnames.append(name)
                    if value is None:
                        row[name] = ""
                    elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
                        row[name] = str(value)
                    elif isinstance(value, bool):
                        row[name] = "true" if value else "false"
                    else:
                        row[name] = json.dumps(value, sort_keys=True, ensure_ascii=False)
                if key_field not in obj:
                    errors.append(
                        issue(
                            DATASET_MISSING_KEY_FIELD,
                            f"dataset.{key_field}",
                            f"第 {line} 行不存在主键字段 {key_field}",
                            line=line,
                        )
                    )
                    continue
                key = normalize_key(obj.get(key_field))
                if key is None or key == "":
                    errors.append(
                        issue(
                            DATASET_MISSING_KEY,
                            f"dataset.{key_field}",
                            f"第 {line} 行主键为空或不是标量",
                            line=line,
                        )
                    )
                    continue
                row[key_field] = key
                _register_row(row, line, key_field, seen, errors)
                rows.append(row)
    except UnicodeDecodeError as exc:
        raise DatasetLoadError(
            [issue(DATASET_ENCODING_ERROR, "dataset.path", f"JSONL 编码不是 UTF-8: {exc}")]
        ) from exc
    if errors:
        raise DatasetLoadError(errors)
    if not rows:
        raise DatasetLoadError([issue(DATASET_EMPTY, "dataset", "JSONL 没有数据行")])
    return _finalize(path, "jsonl", key_field, rows, fieldnames, warnings)


