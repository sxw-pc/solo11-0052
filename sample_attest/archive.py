"""Create and verify self-describing sampling archive directories."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .codes import (
    ARCHIVE_HASH_MISMATCH,
    ARCHIVE_MANIFEST_INVALID,
    ARCHIVE_MISSING_FILE,
    ARCHIVE_TASK_NOT_FOUND,
)
from .ledger import Ledger, TaskNotFoundError
from .reporter import report_json_text

ARCHIVE_VERSION = "1.0"
ARCHIVE_FILES = ("plan.yaml", "report.json", "report.md", "sample_keys.json")
MANIFEST_NAME = "manifest.json"


class ArchiveError(Exception):
    def __init__(self, code: str, path: str, message: str):
        self.code = code
        self.path = path
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_manifest(
    directory: Path,
    task: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for name in sorted(ARCHIVE_FILES):
        path = directory / name
        files[name] = {"sha256": _sha256(path), "size": path.stat().st_size}
    return {
        "archive_version": ARCHIVE_VERSION,
        "files": files,
        "generated_at": generated_at,
        "plan_id": task["plan_id"],
        "population_fingerprint": task["population_fingerprint"],
        "task_id": task["task_id"],
    }


def export_task(
    ledger: Ledger,
    task_id: str,
    out_dir: str | Path,
    *,
    generated_at: str,
) -> dict[str, Any]:
    try:
        task = ledger.get_latest_by_task(task_id)
    except TaskNotFoundError as exc:
        raise ArchiveError(
            ARCHIVE_TASK_NOT_FOUND, "task", f"台账中不存在任务 {task_id}"
        ) from exc
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _write(directory / "plan.yaml", task["plan_yaml"])
    _write(directory / "sample_keys.json", _json_text(task["sample_keys"]))
    _write(directory / "report.json", report_json_text(task["report"]))
    _write(directory / "report.md", task["report_markdown"])
    manifest = build_manifest(directory, task, generated_at)
    _write(directory / MANIFEST_NAME, _json_text(manifest))
    return {
        "task_id": task_id,
        "out_dir": str(directory),
        "manifest": str(directory / MANIFEST_NAME),
        "files": sorted(ARCHIVE_FILES),
    }


def _read_manifest(directory: Path) -> dict[str, Any]:
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ArchiveError(ARCHIVE_MANIFEST_INVALID, MANIFEST_NAME, "归档清单不存在")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArchiveError(ARCHIVE_MANIFEST_INVALID, MANIFEST_NAME, f"清单不可读: {exc}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        raise ArchiveError(ARCHIVE_MANIFEST_INVALID, MANIFEST_NAME, "清单缺少 files 映射")
    for name in manifest["files"]:
        if not isinstance(name, str) or Path(name).name != name or name in ("", ".", ".."):
            raise ArchiveError(ARCHIVE_MANIFEST_INVALID, MANIFEST_NAME, f"非法文件名: {name!r}")
        entry = manifest["files"][name]
        if not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str):
            raise ArchiveError(
                ARCHIVE_MANIFEST_INVALID, f"{MANIFEST_NAME}.files.{name}", "缺少 sha256"
            )
    return manifest


def verify_archive(directory: str | Path) -> dict[str, Any]:
    root = Path(directory)
    if not root.is_dir():
        return {
            "status": "INVALID",
            "errors": [
                ArchiveError(
                    ARCHIVE_MANIFEST_INVALID, "archive", f"归档目录不存在: {root}"
                ).to_dict()
            ],
        }
    try:
        manifest = _read_manifest(root)
    except ArchiveError as exc:
        return {"status": "INVALID", "errors": [exc.to_dict()]}
    errors: list[dict[str, str]] = []
    checked = 0
    for name in sorted(manifest["files"]):
        path = root / name
        if not path.is_file():
            errors.append(
                ArchiveError(ARCHIVE_MISSING_FILE, name, f"归档文件缺失: {name}").to_dict()
            )
            continue
        actual = _sha256(path)
        expected = manifest["files"][name]["sha256"]
        checked += 1
        if actual != expected:
            errors.append(
                ArchiveError(
                    ARCHIVE_HASH_MISMATCH,
                    name,
                    f"文件 {name} 哈希不匹配: expected={expected} actual={actual}",
                ).to_dict()
            )
    return {
        "status": "VALID" if not errors else "INVALID",
        "checked": checked,
        "errors": errors,
        "task_id": manifest.get("task_id"),
        "population_fingerprint": manifest.get("population_fingerprint"),
    }
