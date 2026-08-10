from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from rebuildwhy.errors import SpecError
from rebuildwhy.executor import Executor
from rebuildwhy.overlays import parse_overlays
from rebuildwhy.planner import Planner
from rebuildwhy.spec import load_pipeline

REPOSITORY_ROOT = Path(__file__).parents[2]
SCHEMA_ROOT = REPOSITORY_ROOT / "schemas"


def load_validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.fixture
def schema_demo(tmp_path: Path) -> Path:
    destination = tmp_path / "schema-demo"
    shutil.copytree(
        REPOSITORY_ROOT / "examples" / "synthetic_mri",
        destination,
        ignore=shutil.ignore_patterns(".rebuildwhy", "outputs", "__pycache__"),
    )
    return destination / "pipeline.yaml"


def test_bundled_pipeline_matches_published_schema() -> None:
    document = yaml.safe_load(
        (REPOSITORY_ROOT / "examples/synthetic_mri/pipeline.yaml").read_text(encoding="utf-8")
    )

    load_validator("pipeline-v1.schema.json").validate(document)


def test_real_reports_match_published_schemas(schema_demo: Path) -> None:
    pipeline = load_pipeline(schema_demo)
    plan_validator = load_validator("plan-report-v1.schema.json")
    run_validator = load_validator("run-report-v1.schema.json")
    error_validator = load_validator("error-report-v1.schema.json")

    current_plan = Planner(pipeline).plan().report.to_dict()
    plan_validator.validate(current_plan)

    run_report = Executor(pipeline).run().to_dict()
    run_validator.validate(run_report)

    hit_report = Executor(pipeline).run().to_dict()
    run_validator.validate(hit_report)

    publication = pipeline.root / "outputs/report"
    publication.unlink()
    restore_plan = Planner(pipeline).plan().report.to_dict()
    plan_validator.validate(restore_plan)
    restore_report = Executor(pipeline).run().to_dict()
    run_validator.validate(restore_report)

    overlays = parse_overlays(
        pipeline,
        set_values=["config/pipeline.yaml#/image/spacing=[1.0,1.0,2.0]"],
    )
    counterfactual_plan = Planner(pipeline).plan(overlays).report.to_dict()
    plan_validator.validate(counterfactual_plan)

    error_validator.validate(
        SpecError(
            "PIPELINE_NOT_FOUND",
            "The pipeline file does not exist.",
            path="missing.yaml",
        ).to_dict()
    )


def test_plan_schema_requires_reasons_for_non_hit_decisions(schema_demo: Path) -> None:
    report = Planner(load_pipeline(schema_demo)).plan().report.to_dict()
    invalid_report: dict[str, Any] = copy.deepcopy(report)
    invalid_report["tasks"][0]["reason_ids"] = []

    with pytest.raises(ValidationError):
        load_validator("plan-report-v1.schema.json").validate(invalid_report)
