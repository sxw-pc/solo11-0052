"""Deterministic CSV / JSONL loading and population-roster fingerprinting."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .codes import (
    DATASET_DUPLICATE_KEY,
    DATASET_FILE_NOT_FOUND,
    DATASET_INVALID_FORMAT,
    DATASET_MISSING_KEY,
    DATASET_MISSING_SUBJECT,
    DATASET_MISSING_SUBJECT_FIELD,
)
from .fingerprint import population_fingerprint


@dataclass
class Dataset:
    path: str
    format: str
    key_field: str
    rows: list[dict[str, str]]
    fieldnames: list[str]
    keys: list[str]
    population_fingerprint: str
    blank_value_rows: int
    warnings: list[dict[str, Any]] = field(default_factory=list)
    key_to_row: dict[str, int] = field(default_factory=dict)
    subject_field: str | None = None
    subject_counts: dict[str, int] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def key_set(self) -> set[str]:
        return set(self.keys)

    def metadata(self) -> dict[str, Any]:
        data = {
            "path": self.path,
            "format": self.format,
            "row_count": self.row_count,
            "fieldnames": list(self.fieldnames),
            "population_fingerprint": self.population_fingerprint,
            "blank_value_rows": self.blank_value_rows,
        }
        if self.subject_field:
            data["subject_field"] = self.subject_field
            data["subject_count"] = len(self.subject_counts)
        return data


class DatasetLoadError(Exception):
    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__(f"{len(errors)} dataset loading error(s)")


def issue(code: str, path: str, message: str, line: int | None = None, **extra: Any) -> dict:
    item: dict[str, Any] = {"code": code, "path": path, "message": message}
    if line is not None:
        item["line"] = line
    item.update(extra)
    return item


def normalize_key(value: Any) -> str | None:
    """Normalize scalar keys without relying on locale or JSON ordering."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    return None


def _finalize(
    path: Path,
    fmt: str,
    key_field: str,
    rows: list[dict[str, str]],
    fieldnames: list[str],
    warnings: list[dict[str, Any]],
    subject_field: str | None = None,
) -> Dataset:
    keys = [row[key_field] for row in rows]
    blank_value_rows = sum(
        1 for row in rows if any(row.get(name, "") == "" for name in fieldnames)
    )
    ordered = sorted(keys, key=lambda k: k.encode("utf-8"))
    key_to_row = {row[key_field]: index for index, row in enumerate(rows)}
    subject_counts: dict[str, int] = {}
    if subject_field is not None:
        for row in rows:
            value = row.get(subject_field, "")
            if value != "":
                subject_counts[value] = subject_counts.get(value, 0) + 1
    return Dataset(
        path=str(path),
        format=fmt,
        key_field=key_field,
        rows=rows,
        fieldnames=fieldnames,
        keys=ordered,
        population_fingerprint=population_fingerprint(keys),
        blank_value_rows=blank_value_rows,
        warnings=warnings,
        key_to_row=key_to_row,
        subject_field=subject_field,
        subject_counts=subject_counts,
    )


def _register_subject(
    row: dict[str, str],
    line: int,
    subject_field: str,
    errors: list[dict[str, Any]],
) -> None:
    """Validate a subject identity value; repeated values are intentionally allowed."""
    if row.get(subject_field, "") == "":
        errors.append(
            issue(
                DATASET_MISSING_SUBJECT,
                f"dataset.{subject_field}",
                f"第 {line} 行缺少业务主体 {subject_field}",
                line=line,
            )
        )


def _register_row(
    row: dict[str, str],
    line: int,
    key_field: str,
    seen: dict[str, int],
    errors: list[dict[str, Any]],
) -> None:
    key = row.get(key_field, "")
    if key == "":
        errors.append(
            issue(
                DATASET_MISSING_KEY,
                f"dataset.{key_field}",
                f"第 {line} 行缺少主键 {key_field}",
                line=line,
            )
        )
        return
    if key in seen:
        errors.append(
            issue(
                DATASET_DUPLICATE_KEY,
                f"dataset.{key_field}",
                f"第 {line} 行主键 {key!r} 与第 {seen[key]} 行重复",
                line=line,
                key=key,
                previous_line=seen[key],
            )
        )
        return
    seen[key] = line


def load_dataset(
    path: str | Path,
    fmt: str,
    key_field: str,
    subject_field: str | None = None,
) -> Dataset:
    dataset_path = Path(path)
    fmt = str(fmt).lower()
    if fmt not in ("csv", "jsonl"):
        raise DatasetLoadError(
            [
                issue(
                    DATASET_INVALID_FORMAT,
                    "plan.dataset.format",
                    f"不支持的数据格式: {fmt}",
                )
            ]
        )
    if not dataset_path.exists() or not dataset_path.is_file():
        raise DatasetLoadError(
            [
                issue(
                    DATASET_FILE_NOT_FOUND,
                    "plan.dataset.path",
                    f"数据集文件不存在: {dataset_path}",
                )
            ]
        )
    from .dataset_readers import load_csv, load_jsonl

    if fmt == "csv":
        return load_csv(dataset_path, key_field, subject_field)
    return load_jsonl(dataset_path, key_field, subject_field)
