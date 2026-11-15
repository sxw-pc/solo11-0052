"""Command-line interface for sample-attest."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from . import __version__
from .archive import ArchiveError, export_task, verify_archive
from .codes import IO_ERROR, PLAN_INVALID
from .dataset_loader import DatasetLoadError
from .engine import DEFAULT_DB, VerifyError, run_plan, utc_now, verify_plan
from .ledger import Ledger, TaskNotFoundError
from .plan_loader import PlanLoadError
from .plan_schema import PlanValidationError
from .samplers import UnknownModeError
from .server import DEFAULT_PORT, serve

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_STRICT = 3
EXIT_NOT_REPRODUCIBLE = 4
EXIT_ARCHIVE_INVALID = 5


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _error_payload(code: str, errors: list[dict[str, Any]]) -> dict[str, Any]:
    return {"ok": False, "code": code, "errors": errors}


def _emit_error(code: str, errors: list[dict[str, Any]]) -> int:
    print(_json(_error_payload(code, errors)), file=sys.stderr)
    return EXIT_USAGE


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sample-attest",
        description="本地、离线、确定性的数据抽样签验工具",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="执行一次抽样并写入本地台账")
    run.add_argument("--plan", required=True, help="YAML 方案路径")
    run.add_argument("--out", default="out", help="报告输出目录（默认 out/）")
    run.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 台账路径")
    run.add_argument("--strict", action="store_true", help="任何警告即判定失败")
    run.add_argument("--now", default=None, help="覆盖时间戳（测试/归档复现用）")

    verify = sub.add_parser("verify", help="重跑并与台账最近一次结果比对指纹")
    verify.add_argument("--plan", required=True, help="YAML 方案路径")
    verify.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 台账路径")

    serve_cmd = sub.add_parser("serve", help="启动只读本地 HTTP 服务")
    serve_cmd.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口")
    serve_cmd.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 台账路径")

    export = sub.add_parser("export", help="导出任务归档目录")
    export.add_argument("--task", required=True, help="任务号")
    export.add_argument("--out", required=True, help="归档输出目录")
    export.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 台账路径")
    export.add_argument("--now", default=None, help="覆盖归档生成时间")
    export.add_argument(
        "--with-history",
        action="store_true",
        help="同时导出该 task_id 全部运行历史到 history.json",
    )

    verify_archive_cmd = sub.add_parser("verify-archive", help="复算归档清单哈希")
    verify_archive_cmd.add_argument("--dir", required=True, help="归档目录")
    return parser


def _handle_run(args: argparse.Namespace) -> int:
    outcome = run_plan(
        args.plan,
        out_dir=args.out,
        db_path=args.db,
        strict=args.strict,
        clock=args.now,
    )
    summary = {
        "ok": outcome.verification.status != "fail",
        "task_id": outcome.prepared.task_id,
        "plan_id": outcome.prepared.loaded.plan_id,
        "run_id": outcome.run_id,
        "status": outcome.verification.status,
        "strict_failed": outcome.verification.strict_failed,
        "sample_count": len(outcome.sample.selected),
        "sample_fingerprint": outcome.report["sample"]["fingerprints"]["sample_fingerprint"],
        "reports": outcome.paths,
    }
    print(_json(summary))
    if outcome.verification.strict_failed:
        return EXIT_STRICT
    if outcome.verification.status == "fail":
        return EXIT_FAILED
    return EXIT_OK


def _handle_verify(args: argparse.Namespace) -> int:
    result = verify_plan(args.plan, db_path=args.db)
    print(result["status"])
    print(_json(result))
    return EXIT_OK if result["status"] == "REPRODUCIBLE" else EXIT_NOT_REPRODUCIBLE


def _handle_serve(args: argparse.Namespace) -> int:
    serve(args.db, port=args.port)
    return EXIT_OK


def _handle_export(args: argparse.Namespace) -> int:
    ledger = Ledger(args.db)
    result = export_task(
        ledger,
        args.task,
        args.out,
        generated_at=utc_now(args.now),
        include_history=args.with_history,
    )
    print(_json({"ok": True, **result}))
    return EXIT_OK


def _handle_verify_archive(args: argparse.Namespace) -> int:
    result = verify_archive(args.dir)
    print(_json(result))
    return EXIT_OK if result["status"] == "VALID" else EXIT_ARCHIVE_INVALID


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _handle_run(args)
        if args.command == "verify":
            return _handle_verify(args)
        if args.command == "serve":
            return _handle_serve(args)
        if args.command == "export":
            return _handle_export(args)
        if args.command == "verify-archive":
            return _handle_verify_archive(args)
    except PlanValidationError as exc:
        return _emit_error(PLAN_INVALID, exc.errors)
    except PlanLoadError as exc:
        return _emit_error(exc.errors[0].get("code", "PLAN_LOAD_ERROR"), exc.errors)
    except DatasetLoadError as exc:
        return _emit_error(exc.errors[0].get("code", "DATASET_ERROR"), exc.errors)
    except UnknownModeError as exc:
        return _emit_error(exc.code, [{"code": exc.code, "path": "plan.mode", "message": str(exc)}])
    except VerifyError as exc:
        return _emit_error(
            exc.code,
            [{"code": exc.code, "path": "verify", "message": exc.message, **exc.extra}],
        )
    except ArchiveError as exc:
        return _emit_error(exc.code, [exc.to_dict()])
    except TaskNotFoundError as exc:
        return _emit_error(exc.code, [{"code": exc.code, "path": "task", "message": str(exc)}])
    except OSError as exc:
        return _emit_error(IO_ERROR, [{"code": IO_ERROR, "path": "io", "message": str(exc)}])
    parser.error(f"unsupported command: {args.command}")
    return EXIT_USAGE


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
