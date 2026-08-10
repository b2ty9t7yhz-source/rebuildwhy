"""Command-line interface for planning, execution, and determinism checks."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from rebuildwhy import __version__
from rebuildwhy.canonical import canonical_json_text
from rebuildwhy.errors import RebuildWhyError
from rebuildwhy.executor import Executor
from rebuildwhy.overlays import parse_overlays
from rebuildwhy.planner import Planner
from rebuildwhy.spec import load_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rebuildwhy",
        description="Explain and execute trusted local content-addressed task pipelines.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Compute a current or hypothetical plan.")
    _pipeline_argument(plan)
    plan.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="FILE#POINTER=JSON",
        help="Replace one declared config value in memory.",
    )
    plan.add_argument(
        "--replace-file",
        action="append",
        default=[],
        metavar="LOGICAL=REPLACEMENT",
        help="Hash replacement bytes under one declared logical file path.",
    )
    plan.add_argument("--json", action="store_true", help="Emit canonical JSON.")

    run = subparsers.add_parser("run", help="Execute or restore every required task.")
    _pipeline_argument(run)
    run.add_argument(
        "--check-determinism",
        action="store_true",
        help="Run every cache miss twice before recording it.",
    )
    run.add_argument("--json", action="store_true", help="Emit canonical JSON.")

    verify = subparsers.add_parser(
        "verify-determinism", help="Run one task twice and compare its manifests."
    )
    _pipeline_argument(verify)
    verify.add_argument("task_id", help="Task to execute twice.")
    verify.add_argument("--json", action="store_true", help="Emit canonical JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    wants_json = "--json" in arguments
    try:
        options = build_parser().parse_args(arguments)
        pipeline = load_pipeline(options.pipeline)
        if options.command == "plan":
            overlays = parse_overlays(
                pipeline,
                set_values=options.set,
                replace_files=options.replace_file,
            )
            body = Planner(pipeline).plan(overlays).report.to_dict()
            _emit(body, json_output=options.json, kind="plan")
        elif options.command == "run":
            body = Executor(pipeline).run(check_determinism=options.check_determinism).to_dict()
            _emit(body, json_output=options.json, kind="run")
        else:
            body = Executor(pipeline).verify_determinism(options.task_id).to_dict()
            _emit(body, json_output=options.json, kind="run")
        return 0
    except RebuildWhyError as error:
        if wants_json:
            sys.stderr.write(canonical_json_text(error.to_dict()) + "\n")
        else:
            sys.stderr.write(f"error [{error.code}]: {error.message}\n")
            for key, value in sorted(error.details.items()):
                sys.stderr.write(f"  {key}: {value}\n")
        return error.exit_code


def _pipeline_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-p", "--pipeline", default="pipeline.yaml", help="Pipeline YAML path.")


def _emit(body: dict[str, Any], *, json_output: bool, kind: str) -> None:
    if json_output:
        sys.stdout.write(canonical_json_text(body) + "\n")
    elif kind == "plan":
        _render_plan(body)
    else:
        _render_run(body)


def _render_plan(body: dict[str, Any]) -> None:
    print(f"RebuildWhy plan: {body['pipeline']} ({body['mode']})")
    reasons = {reason["reason_id"]: reason for reason in body["reasons"]}
    for task in body["tasks"]:
        print(f"{task['task_id']} {task['decision']}")
        rendered: set[str] = set()
        for reason_id in task["reason_ids"]:
            _render_reason(reason_id, reasons, rendered, depth=1)


def _render_reason(
    reason_id: str,
    reasons: dict[str, dict[str, Any]],
    rendered: set[str],
    *,
    depth: int,
) -> None:
    indent = "  " * depth
    reason = reasons[reason_id]
    if reason_id in rendered:
        print(f"{indent}- {reason['code']}: {reason['subject']} (already shown)")
        return
    rendered.add(reason_id)
    print(f"{indent}- {reason['code']}: {reason['subject']}")
    for cause in reason["caused_by"]:
        _render_reason(cause, reasons, rendered, depth=depth + 1)


def _render_run(body: dict[str, Any]) -> None:
    print(f"RebuildWhy run: {body['pipeline']}")
    for event in body["events"]:
        print(f"{event['task_id']} {event['decision']} {event['manifest_digest']}")


if __name__ == "__main__":
    raise SystemExit(main())
