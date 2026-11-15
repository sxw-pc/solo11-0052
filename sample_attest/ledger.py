"""Append-only local SQLite ledger for sampling runs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .codes import LEDGER_TASK_NOT_FOUND

SCHEMA = """
CREATE TABLE IF NOT EXISTS task_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    population_fingerprint TEXT NOT NULL,
    sample_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    strict INTEGER NOT NULL,
    checks_summary TEXT NOT NULL,
    plan_yaml TEXT NOT NULL,
    sample_keys_json TEXT NOT NULL,
    report_json TEXT NOT NULL,
    report_md TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_runs_task ON task_runs(task_id, run_id);
CREATE INDEX IF NOT EXISTS idx_task_runs_plan ON task_runs(plan_id, run_id);
"""


class TaskNotFoundError(Exception):
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.code = LEDGER_TASK_NOT_FOUND
        super().__init__(f"task not found: {task_id}")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


class Ledger:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.db_path), timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(SCHEMA)

    def record_run(
        self,
        *,
        report: dict[str, Any],
        plan_yaml: str,
        sample_keys: list[str],
        report_markdown: str,
        created_at: str,
    ) -> int:
        verification = report["verification"]
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO task_runs (
                    task_id, plan_id, population_fingerprint, sample_fingerprint,
                    status, strict, checks_summary, plan_yaml, sample_keys_json,
                    report_json, report_md, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report["task_id"],
                    report["plan_id"],
                    report["dataset"]["population_fingerprint"],
                    report["sample"]["fingerprints"]["sample_fingerprint"],
                    report["overall_status"],
                    1 if verification.get("strict") else 0,
                    json.dumps(verification.get("counts", {}), sort_keys=True),
                    plan_yaml,
                    _canonical(sample_keys),
                    _canonical(report),
                    report_markdown,
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

    def _parse_task(self, row: sqlite3.Row, run_count: int = 1) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "task_id": row["task_id"],
            "plan_id": row["plan_id"],
            "population_fingerprint": row["population_fingerprint"],
            "sample_fingerprint": row["sample_fingerprint"],
            "status": row["status"],
            "strict": bool(row["strict"]),
            "checks_summary": json.loads(row["checks_summary"]),
            "created_at": row["created_at"],
            "plan_yaml": row["plan_yaml"],
            "sample_keys": json.loads(row["sample_keys_json"]),
            "report": json.loads(row["report_json"]),
            "report_markdown": row["report_md"],
            "run_count": run_count,
        }

    def get_latest_by_task(self, task_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM task_runs WHERE task_id = ? ORDER BY run_id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if row is None:
                raise TaskNotFoundError(task_id)
            count = connection.execute(
                "SELECT COUNT(*) FROM task_runs WHERE task_id = ?", (task_id,)
            ).fetchone()[0]
        return self._parse_task(row, int(count))

    def list_runs_by_task(self, task_id: str) -> list[dict[str, Any]]:
        """Return every run of a task_id in chronological order (run_id asc)."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM task_runs WHERE task_id = ? ORDER BY run_id ASC",
                (task_id,),
            ).fetchall()
        return [self._parse_task(row) for row in rows]

    def get_latest_by_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM task_runs WHERE plan_id = ? ORDER BY run_id DESC LIMIT 1",
                (plan_id,),
            ).fetchone()
        return self._parse_task(row) if row is not None else None

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM task_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._parse_task(row) if row is not None else None

    def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT t.*,
                    (SELECT COUNT(*) FROM task_runs c WHERE c.task_id = t.task_id) AS run_count
                FROM task_runs t
                WHERE t.run_id = (
                    SELECT MAX(run_id) FROM task_runs m WHERE m.task_id = t.task_id
                )
                ORDER BY t.run_id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "task_id": row["task_id"],
                "plan_id": row["plan_id"],
                "population_fingerprint": row["population_fingerprint"],
                "sample_fingerprint": row["sample_fingerprint"],
                "status": row["status"],
                "strict": bool(row["strict"]),
                "checks_summary": json.loads(row["checks_summary"]),
                "created_at": row["created_at"],
                "run_count": row["run_count"],
            }
            for row in rows
        ]

    def count_runs(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0])
