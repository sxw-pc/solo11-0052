"""Read-only local Flask entry point for ledger inspection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from . import __version__
from .codes import LEDGER_TASK_NOT_FOUND, SERVER_METHOD_NOT_ALLOWED
from .engine import DEFAULT_DB
from .ledger import Ledger, TaskNotFoundError

HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def create_app(db_path: str | Path = DEFAULT_DB) -> Flask:
    app = Flask(__name__)
    app.config.update(JSON_SORT_KEYS=True, DB_PATH=str(db_path))

    def ledger() -> Ledger:
        return Ledger(app.config["DB_PATH"])

    @app.get("/healthz")
    def healthz() -> Any:
        return jsonify(
            {
                "status": "ok",
                "service": "sample-attest",
                "version": __version__,
                "read_only": True,
            }
        )

    @app.get("/tasks")
    def list_tasks() -> Any:
        try:
            limit = int(request.args.get("limit", "100"))
        except ValueError:
            limit = 100
        return jsonify({"tasks": ledger().list_tasks(limit=limit)})

    @app.get("/tasks/<task_id>")
    def task_detail(task_id: str) -> Any:
        try:
            task = ledger().get_latest_by_task(task_id)
        except TaskNotFoundError:
            return (
                jsonify(
                    {
                        "error": {
                            "code": LEDGER_TASK_NOT_FOUND,
                            "message": f"任务不存在: {task_id}",
                        }
                    }
                ),
                404,
            )
        return jsonify(task)

    @app.errorhandler(405)
    def method_not_allowed(_error: Any) -> Any:
        return (
            jsonify(
                {
                    "error": {
                        "code": SERVER_METHOD_NOT_ALLOWED,
                        "message": "本服务为只读接口，写操作被拒绝",
                    }
                }
            ),
            405,
        )

    return app


def serve(
    db_path: str | Path = DEFAULT_DB,
    *,
    port: int = DEFAULT_PORT,
) -> None:
    if HOST != "127.0.0.1":
        raise RuntimeError("sample-attest 只允许监听回环地址")
    app = create_app(db_path)
    app.run(host=HOST, port=int(port), debug=False, use_reloader=False)
