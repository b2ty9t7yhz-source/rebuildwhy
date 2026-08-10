from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rebuildwhy.errors import SpecError
from rebuildwhy.graph import TaskGraph
from rebuildwhy.spec import (
    load_config_document,
    load_pipeline,
    replace_json_pointer,
    resolve_json_pointer,
)


def test_load_pipeline_returns_deterministic_topological_order(
    pipeline_factory: Any, minimal_pipeline: dict[str, Any]
) -> None:
    pipeline = load_pipeline(pipeline_factory(minimal_pipeline))
    graph = TaskGraph.from_pipeline(pipeline)

    assert graph.topological_order == ("source", "consumer")
    assert graph.dependencies["consumer"] == ("source",)
    assert graph.affected_descendants({"source"}) == ("source", "consumer")


def test_topological_order_uses_task_id_as_stable_tie_breaker(pipeline_factory: Any) -> None:
    document = {
        "version": 1,
        "tasks": {
            "zeta": {
                "command": {"argv": ["true"]},
                "output": {"publish": "outputs/zeta", "required": ["x"]},
            },
            "alpha": {
                "command": {"argv": ["true"]},
                "output": {"publish": "outputs/alpha", "required": ["x"]},
            },
        },
    }

    graph = TaskGraph.from_pipeline(load_pipeline(pipeline_factory(document)))

    assert graph.topological_order == ("alpha", "zeta")


def test_cycle_is_rejected(pipeline_factory: Any, minimal_pipeline: dict[str, Any]) -> None:
    minimal_pipeline["tasks"]["source"]["inputs"] = {
        "artifacts": [{"task": "consumer", "path": "result.txt"}]
    }

    with pytest.raises(SpecError) as caught:
        load_pipeline(pipeline_factory(minimal_pipeline))

    assert caught.value.code == "PIPELINE_CYCLE"
    assert caught.value.details["tasks"] == ["consumer", "source"]


def test_missing_task_dependency_is_rejected(
    pipeline_factory: Any, minimal_pipeline: dict[str, Any]
) -> None:
    minimal_pipeline["tasks"]["consumer"]["inputs"]["artifacts"][0]["task"] = "missing"

    with pytest.raises(SpecError) as caught:
        load_pipeline(pipeline_factory(minimal_pipeline))

    assert caught.value.code == "MISSING_TASK_DEPENDENCY"


def test_undeclared_producer_output_is_rejected(
    pipeline_factory: Any, minimal_pipeline: dict[str, Any]
) -> None:
    minimal_pipeline["tasks"]["consumer"]["inputs"]["artifacts"][0]["path"] = "other.txt"

    with pytest.raises(SpecError) as caught:
        load_pipeline(pipeline_factory(minimal_pipeline))

    assert caught.value.code == "UNDECLARED_ARTIFACT"


def test_path_escape_is_rejected(pipeline_factory: Any, minimal_pipeline: dict[str, Any]) -> None:
    minimal_pipeline["tasks"]["source"]["inputs"]["files"] = ["../secret.txt"]

    with pytest.raises(SpecError) as caught:
        load_pipeline(pipeline_factory(minimal_pipeline))

    assert caught.value.code == "PATH_ESCAPE"


def test_overlapping_publication_paths_are_rejected(
    pipeline_factory: Any, minimal_pipeline: dict[str, Any]
) -> None:
    minimal_pipeline["tasks"]["consumer"]["output"]["publish"] = "outputs/source/nested"

    with pytest.raises(SpecError) as caught:
        load_pipeline(pipeline_factory(minimal_pipeline))

    assert caught.value.code == "OVERLAPPING_PUBLICATIONS"


def test_overlapping_required_outputs_are_rejected(
    pipeline_factory: Any, minimal_pipeline: dict[str, Any]
) -> None:
    minimal_pipeline["tasks"]["source"]["output"]["required"] = ["result", "result/data.txt"]

    with pytest.raises(SpecError) as caught:
        load_pipeline(pipeline_factory(minimal_pipeline))

    assert caught.value.code == "OVERLAPPING_REQUIRED_OUTPUTS"


def test_duplicate_config_locator_is_rejected(
    pipeline_factory: Any, minimal_pipeline: dict[str, Any]
) -> None:
    minimal_pipeline["tasks"]["source"]["inputs"] = {
        "config": [
            {"file": "config.yaml", "pointers": ["/value"]},
            {"file": "config.yaml", "pointers": ["/value"]},
        ]
    }

    with pytest.raises(SpecError) as caught:
        load_pipeline(pipeline_factory(minimal_pipeline))

    assert caught.value.code == "DUPLICATE_CONFIG_DEPENDENCY"


def test_duplicate_yaml_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.yaml"
    path.write_text(
        "version: 1\nversion: 1\ntasks: {}\n",
        encoding="utf-8",
    )

    with pytest.raises(SpecError) as caught:
        load_pipeline(path)

    assert caught.value.code == "DUPLICATE_YAML_KEY"


def test_unknown_field_is_rejected(pipeline_factory: Any, minimal_pipeline: dict[str, Any]) -> None:
    minimal_pipeline["tasks"]["source"]["retry"] = 3

    with pytest.raises(SpecError) as caught:
        load_pipeline(pipeline_factory(minimal_pipeline))

    assert caught.value.code == "UNKNOWN_FIELD"


def test_json_pointer_supports_escaped_tokens_and_lists() -> None:
    document = {"a/b": {"~key": [10, 20]}}

    assert resolve_json_pointer(document, "/a~1b/~0key/1") == 20
    replaced = replace_json_pointer(document, "/a~1b/~0key/0", 99)

    assert replaced == {"a/b": {"~key": [99, 20]}}
    assert document == {"a/b": {"~key": [10, 20]}}


def test_missing_json_pointer_is_rejected() -> None:
    with pytest.raises(SpecError) as caught:
        resolve_json_pointer({"known": 1}, "/missing")

    assert caught.value.code == "JSON_POINTER_NOT_FOUND"


def test_config_loader_rejects_non_finite_yaml(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("value: .nan\n", encoding="utf-8")

    with pytest.raises(SpecError) as caught:
        load_config_document(path)

    assert caught.value.code == "NON_FINITE_VALUE"
