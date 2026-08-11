from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from rebuildwhy.cli import main

REPOSITORY_ROOT = Path(__file__).parents[2]
SCHEMA_DIRECTORY = REPOSITORY_ROOT / "schemas"


def load_schema(name: str) -> dict[str, Any]:
    value = json.loads((SCHEMA_DIRECTORY / name).read_text(encoding="utf-8"))
    return cast(dict[str, Any], value)


def copy_demo(tmp_path: Path) -> Path:
    destination = tmp_path / "demo"
    shutil.copytree(
        REPOSITORY_ROOT / "examples" / "synthetic_mri",
        destination,
        ignore=shutil.ignore_patterns(".rebuildwhy", "outputs", "__pycache__"),
    )
    return destination / "pipeline.yaml"


@pytest.mark.parametrize(
    "schema_name",
    [
        "error-report-v1.schema.json",
        "pipeline-v1.schema.json",
        "plan-report-v1.schema.json",
        "run-report-v1.schema.json",
    ],
)
def test_schema_is_valid_draft_2020_12(schema_name: str) -> None:
    Draft202012Validator.check_schema(load_schema(schema_name))


def test_example_pipeline_matches_public_schema() -> None:
    document = yaml.safe_load(
        (REPOSITORY_ROOT / "examples/synthetic_mri/pipeline.yaml").read_text(encoding="utf-8")
    )

    Draft202012Validator(load_schema("pipeline-v1.schema.json")).validate(document)


def test_cli_plan_and_run_reports_match_public_schemas(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pipeline = copy_demo(tmp_path)

    assert main(["plan", "-p", str(pipeline), "--json"]) == 0
    plan_report = json.loads(capsys.readouterr().out)
    Draft202012Validator(load_schema("plan-report-v1.schema.json")).validate(plan_report)

    assert main(["run", "-p", str(pipeline), "--json"]) == 0
    run_report = json.loads(capsys.readouterr().out)
    Draft202012Validator(load_schema("run-report-v1.schema.json")).validate(run_report)


def test_cli_error_report_matches_public_schema(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.yaml"

    assert main(["plan", "-p", str(missing), "--json"]) == 2
    error_report = json.loads(capsys.readouterr().err)

    Draft202012Validator(load_schema("error-report-v1.schema.json")).validate(error_report)


def test_pipeline_schema_rejects_reserved_paths_and_bad_pointer_escapes() -> None:
    document = cast(
        dict[str, Any],
        yaml.safe_load(
            (REPOSITORY_ROOT / "examples/synthetic_mri/pipeline.yaml").read_text(encoding="utf-8")
        ),
    )
    validator = Draft202012Validator(load_schema("pipeline-v1.schema.json"))

    reserved_path = copy.deepcopy(document)
    reserved_path["tasks"]["ingest"]["inputs"]["files"] = [".rebuildwhy/state.json"]
    with pytest.raises(ValidationError):
        validator.validate(reserved_path)

    bad_pointer = copy.deepcopy(document)
    bad_pointer["tasks"]["ingest"]["inputs"]["config"][0]["pointers"] = ["/bad~2escape"]
    with pytest.raises(ValidationError):
        validator.validate(bad_pointer)


def test_plan_schema_rejects_malformed_digest() -> None:
    report = {
        "schema_version": 1,
        "plan_id": "not-a-digest",
        "pipeline": "example",
        "mode": "current",
        "affected_task_ids": [],
        "tasks": [{"task_id": "task", "decision": "HIT", "reason_ids": []}],
        "reasons": [],
    }

    with pytest.raises(ValidationError):
        Draft202012Validator(load_schema("plan-report-v1.schema.json")).validate(report)


def test_plan_schema_requires_reasons_for_non_hit_decisions() -> None:
    report = {
        "schema_version": 1,
        "plan_id": "sha256:" + "0" * 64,
        "pipeline": "example",
        "mode": "current",
        "affected_task_ids": ["task"],
        "tasks": [{"task_id": "task", "decision": "RUN", "reason_ids": []}],
        "reasons": [],
    }

    with pytest.raises(ValidationError):
        Draft202012Validator(load_schema("plan-report-v1.schema.json")).validate(report)
