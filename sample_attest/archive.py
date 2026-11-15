"""Create and verify self-describing sampling archive directories."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .codes import (
    ARCHIVE_HASH_MISMATCH,
    ARCHIVE_HISTORY_INVALID,
    ARCHIVE_MANIFEST_INVALID,
    ARCHIVE_MISSING_FILE,
    ARCHIVE_REPRODUCIBILITY_FORK,
    ARCHIVE_TASK_NOT_FOUND,
)
from .ledger import Ledger, TaskNotFoundError
from .reporter import report_json_text

ARCHIVE_VERSION = "1.0"
ARCHIVE_FILES = ("plan.yaml", "report.json", "report.md", "sample_keys.json")
HISTORY_NAME = "history.json"
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


def _archive_files(include_history: bool) -> tuple[str, ...]:
    if include_history:
        return tuple(sorted((*ARCHIVE_FILES, HISTORY_NAME)))
    return ARCHIVE_FILES


def build_manifest(
    directory: Path,
    task: dict[str, Any],
    generated_at: str,
    *,
    include_history: bool = False,
) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for name in _archive_files(include_history):
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


def _sorted_keys(keys: Any) -> list[str]:
    return sorted(keys, key=lambda key: key.encode("utf-8"))


def _sample_key_diff(previous: list[str], current: list[str]) -> dict[str, list[str]]:
    """Full added/missing sample-key diff of a run versus its predecessor."""
    before = set(previous)
    after = set(current)
    return {
        "added": _sorted_keys(after - before),
        "missing": _sorted_keys(before - after),
    }


def build_history(task_id: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble the fixed-order run-history payload for a task_id."""
    entries: list[dict[str, Any]] = []
    previous_keys: list[str] | None = None
    for run in runs:
        keys = list(run["sample_keys"])
        if previous_keys is None:
            diff: dict[str, list[str]] = {"added": [], "missing": []}
        else:
            diff = _sample_key_diff(previous_keys, keys)
        entries.append(
            {
                "run_id": run["run_id"],
                "created_at": run["created_at"],
                "status": run["status"],
                "sample_fingerprint": run["sample_fingerprint"],
                "check_counts": dict(run["checks_summary"]),
                "diff": diff,
            }
        )
        previous_keys = keys
    return {"task_id": task_id, "runs": entries}


def export_task(
    ledger: Ledger,
    task_id: str,
    out_dir: str | Path,
    *,
    generated_at: str,
    include_history: bool = False,
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
    if include_history:
        runs = ledger.list_runs_by_task(task_id)
        _write(directory / HISTORY_NAME, _json_text(build_history(task_id, runs)))
    manifest = build_manifest(directory, task, generated_at, include_history=include_history)
    _write(directory / MANIFEST_NAME, _json_text(manifest))
    return {
        "task_id": task_id,
        "out_dir": str(directory),
        "manifest": str(directory / MANIFEST_NAME),
        "files": list(_archive_files(include_history)),
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


def _analyze_history(
    directory: Path, task_id: Any
) -> tuple[dict[str, Any] | None, ArchiveError | None]:
    """Parse a hash-verified history.json and locate fingerprint forks."""
    path = directory / HISTORY_NAME
    try:
        history = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, ArchiveError(
            ARCHIVE_HISTORY_INVALID, HISTORY_NAME, f"历史记录不可读: {exc}"
        )
    if not isinstance(history, dict) or not isinstance(history.get("runs"), list):
        return None, ArchiveError(
            ARCHIVE_HISTORY_INVALID, HISTORY_NAME, "历史记录缺少 runs 数组"
        )
    if task_id is not None and history.get("task_id") != task_id:
        return None, ArchiveError(
            ARCHIVE_HISTORY_INVALID,
            HISTORY_NAME,
            f"历史记录 task_id={history.get('task_id')!r} 与清单 {task_id!r} 不一致",
        )
    runs = history["runs"]
    forks: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    fingerprints: set[str] = set()
    for run in runs:
        if (
            not isinstance(run, dict)
            or not isinstance(run.get("run_id"), int)
            or isinstance(run.get("run_id"), bool)
            or not isinstance(run.get("sample_fingerprint"), str)
        ):
            return None, ArchiveError(
                ARCHIVE_HISTORY_INVALID,
                HISTORY_NAME,
                "历史记录条目缺少 run_id 或 sample_fingerprint",
            )
        fingerprint = run["sample_fingerprint"]
        fingerprints.add(fingerprint)
        if previous is not None and fingerprint != previous["sample_fingerprint"]:
            forks.append(
                {
                    "code": ARCHIVE_REPRODUCIBILITY_FORK,
                    "previous_run_id": previous["run_id"],
                    "run_id": run["run_id"],
                    "previous_sample_fingerprint": previous["sample_fingerprint"],
                    "sample_fingerprint": fingerprint,
                }
            )
        previous = run
    return (
        {
            "run_count": len(runs),
            "reproducibility": "FORKED" if forks else "CONSISTENT",
            "forks": forks,
            "distinct_sample_fingerprints": sorted(fingerprints),
        },
        None,
    )


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
    result: dict[str, Any] = {
        "status": "VALID" if not errors else "INVALID",
        "checked": checked,
        "errors": errors,
        "task_id": manifest.get("task_id"),
        "population_fingerprint": manifest.get("population_fingerprint"),
    }
    # History is interpreted only after its on-disk hash has been verified;
    # a tampered history.json stays an ARCHIVE_HASH_MISMATCH, never a fork.
    if not errors and HISTORY_NAME in manifest["files"] and (root / HISTORY_NAME).is_file():
        history, history_error = _analyze_history(root, manifest.get("task_id"))
        if history_error is not None:
            result["status"] = "INVALID"
            result["errors"] = [*errors, history_error.to_dict()]
        else:
            result["history"] = history
    return result
