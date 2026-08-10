"""Strict parsing for pipeline files and JSON-compatible configuration."""

from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from rebuildwhy.errors import SpecError
from rebuildwhy.graph import TaskGraph
from rebuildwhy.models import (
    PIPELINE_SCHEMA_VERSION,
    ArtifactDependency,
    CommandSpec,
    ConfigDependency,
    OutputSpec,
    PipelineSpec,
    TaskSpec,
)

TASK_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
ENVIRONMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise SpecError(
                "NON_STRING_MAPPING_KEY",
                "YAML mapping keys must be strings.",
                line=key_node.start_mark.line + 1,
            ) from error
        if duplicate:
            raise SpecError(
                "DUPLICATE_YAML_KEY",
                "YAML mapping keys must be unique.",
                key=str(key),
                line=key_node.start_mark.line + 1,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def load_pipeline(path: str | Path) -> PipelineSpec:
    """Load, validate, and return one V1 pipeline specification."""

    pipeline_path = Path(path).expanduser().resolve()
    if not pipeline_path.is_file():
        raise SpecError(
            "PIPELINE_NOT_FOUND",
            "The pipeline file does not exist.",
            path=str(pipeline_path),
        )
    raw = _load_yaml_file(pipeline_path)
    top = _mapping(raw, "pipeline")
    _reject_unknown(top, {"version", "project", "tasks"}, "pipeline")

    version = top.get("version")
    if version != PIPELINE_SCHEMA_VERSION:
        raise SpecError(
            "UNSUPPORTED_PIPELINE_VERSION",
            "Only pipeline schema version 1 is supported.",
            received=version,
        )
    project = top.get("project", pipeline_path.parent.name)
    if not isinstance(project, str) or not project.strip():
        raise SpecError("INVALID_PROJECT_NAME", "The project name must be a non-empty string.")

    raw_tasks = _mapping(top.get("tasks"), "pipeline.tasks")
    if not raw_tasks:
        raise SpecError("EMPTY_PIPELINE", "The pipeline must define at least one task.")

    tasks: dict[str, TaskSpec] = {}
    for task_id, raw_task in raw_tasks.items():
        if not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id):
            raise SpecError(
                "INVALID_TASK_ID",
                "Task IDs must match [a-z][a-z0-9_-]*.",
                task_id=task_id,
            )
        tasks[task_id] = _parse_task(task_id, raw_task)

    pipeline = PipelineSpec(
        version=version,
        project=project.strip(),
        root=pipeline_path.parent,
        pipeline_path=pipeline_path,
        tasks=tasks,
    )
    _validate_publication_paths(pipeline)
    TaskGraph.from_pipeline(pipeline)
    return pipeline


def load_config_document(path: Path) -> Any:
    """Load a JSON-compatible YAML or JSON configuration document."""

    if not path.is_file():
        raise SpecError(
            "MISSING_SOURCE_INPUT",
            "A declared configuration file does not exist.",
            path=str(path),
        )
    if path.suffix.lower() == ".json":
        try:
            with path.open("r", encoding="utf-8") as stream:
                value = json.load(stream, object_pairs_hook=_unique_json_pairs)
        except json.JSONDecodeError as error:
            raise SpecError(
                "INVALID_CONFIG",
                "The JSON configuration document is invalid.",
                path=str(path),
                line=error.lineno,
                column=error.colno,
            ) from error
    else:
        value = _load_yaml_file(path)
    _validate_json_compatible(value, str(path))
    return value


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve one RFC 6901 JSON Pointer and return a deep copy of its value."""

    current = document
    for token in _pointer_tokens(pointer):
        if isinstance(current, dict):
            if token not in current:
                raise SpecError(
                    "JSON_POINTER_NOT_FOUND",
                    "A declared JSON Pointer does not resolve.",
                    pointer=pointer,
                    missing_token=token,
                )
            current = current[token]
        elif isinstance(current, list):
            if token == "-" or not token.isdigit():
                raise SpecError(
                    "JSON_POINTER_NOT_FOUND",
                    "A JSON Pointer list token must be an existing non-negative index.",
                    pointer=pointer,
                    token=token,
                )
            index = int(token)
            if index >= len(current):
                raise SpecError(
                    "JSON_POINTER_NOT_FOUND",
                    "A JSON Pointer list index is out of range.",
                    pointer=pointer,
                    index=index,
                )
            current = current[index]
        else:
            raise SpecError(
                "JSON_POINTER_NOT_FOUND",
                "A JSON Pointer traverses through a scalar value.",
                pointer=pointer,
                token=token,
            )
    return copy.deepcopy(current)


def replace_json_pointer(document: Any, pointer: str, value: Any) -> Any:
    """Return a deep-copied document with one existing pointer replaced."""

    _validate_json_compatible(value, f"overlay:{pointer}")
    if pointer == "":
        return copy.deepcopy(value)
    result = copy.deepcopy(document)
    tokens = _pointer_tokens(pointer)
    parent = result
    for token in tokens[:-1]:
        parent = _descend_pointer(parent, token, pointer)
    final = tokens[-1]
    if isinstance(parent, dict) and final in parent:
        parent[final] = copy.deepcopy(value)
    elif isinstance(parent, list) and final.isdigit() and int(final) < len(parent):
        parent[int(final)] = copy.deepcopy(value)
    else:
        raise SpecError(
            "JSON_POINTER_NOT_FOUND",
            "A counterfactual overlay may replace only an existing value.",
            pointer=pointer,
        )
    return result


def _parse_task(task_id: str, raw: Any) -> TaskSpec:
    task = _mapping(raw, f"tasks.{task_id}")
    _reject_unknown(task, {"command", "inputs", "output"}, f"tasks.{task_id}")

    command_raw = _mapping(task.get("command"), f"tasks.{task_id}.command")
    _reject_unknown(command_raw, {"argv", "working_directory"}, f"tasks.{task_id}.command")
    argv = _string_list(command_raw.get("argv"), f"tasks.{task_id}.command.argv")
    if not argv:
        raise SpecError("EMPTY_COMMAND", "A task command must contain at least one argument.")
    working_directory = normalize_relative_path(
        command_raw.get("working_directory", "."), allow_dot=True
    )

    inputs = _mapping(task.get("inputs", {}), f"tasks.{task_id}.inputs")
    _reject_unknown(
        inputs,
        {"files", "config", "environment", "artifacts"},
        f"tasks.{task_id}.inputs",
    )
    files = tuple(
        sorted(
            _unique(
                normalize_relative_path(item)
                for item in _string_list(inputs.get("files", []), "files")
            )
        )
    )

    configs: list[ConfigDependency] = []
    config_locators: set[tuple[str, str]] = set()
    for index, raw_config in enumerate(_list(inputs.get("config", []), "config")):
        config = _mapping(raw_config, f"config[{index}]")
        _reject_unknown(config, {"file", "pointers"}, f"config[{index}]")
        config_file = normalize_relative_path(_string(config.get("file"), "config.file"))
        pointers = tuple(
            sorted(
                _unique(
                    _json_pointer(item) for item in _string_list(config.get("pointers"), "pointers")
                )
            )
        )
        if not pointers:
            raise SpecError(
                "EMPTY_CONFIG_DEPENDENCY",
                "A config dependency must declare at least one JSON Pointer.",
                task_id=task_id,
                file=config_file,
            )
        duplicates = sorted(
            locator
            for locator in ((config_file, pointer) for pointer in pointers)
            if locator in config_locators
        )
        if duplicates:
            raise SpecError(
                "DUPLICATE_CONFIG_DEPENDENCY",
                "Config file and JSON Pointer locators must be unique per task.",
                task_id=task_id,
                locators=[f"{file}#{pointer}" for file, pointer in duplicates],
            )
        config_locators.update((config_file, pointer) for pointer in pointers)
        configs.append(ConfigDependency(file=config_file, pointers=pointers))

    environment = tuple(
        sorted(
            _unique(
                _environment_name(item)
                for item in _string_list(inputs.get("environment", []), "environment")
            )
        )
    )

    artifacts: list[ArtifactDependency] = []
    for index, raw_artifact in enumerate(_list(inputs.get("artifacts", []), "artifacts")):
        artifact = _mapping(raw_artifact, f"artifacts[{index}]")
        _reject_unknown(artifact, {"task", "path"}, f"artifacts[{index}]")
        artifacts.append(
            ArtifactDependency(
                task=_string(artifact.get("task"), "artifact.task"),
                path=normalize_relative_path(_string(artifact.get("path"), "artifact.path")),
            )
        )
    if len(set(artifacts)) != len(artifacts):
        raise SpecError(
            "DUPLICATE_ARTIFACT_DEPENDENCY",
            "Artifact dependencies must be unique.",
            task_id=task_id,
        )

    output_raw = _mapping(task.get("output"), f"tasks.{task_id}.output")
    _reject_unknown(output_raw, {"publish", "required"}, f"tasks.{task_id}.output")
    publish = normalize_relative_path(_string(output_raw.get("publish"), "output.publish"))
    required = tuple(
        sorted(
            _unique(
                normalize_relative_path(item)
                for item in _string_list(output_raw.get("required"), "output.required")
            )
        )
    )
    if not required:
        raise SpecError(
            "EMPTY_OUTPUT_CONTRACT",
            "A task must declare at least one required output file.",
            task_id=task_id,
        )
    required_paths = [PurePosixPath(path) for path in required]
    for index, left in enumerate(required_paths):
        for right in required_paths[index + 1 :]:
            if left in right.parents or right in left.parents:
                raise SpecError(
                    "OVERLAPPING_REQUIRED_OUTPUTS",
                    "Required output files may not contain one another.",
                    task_id=task_id,
                    first=str(left),
                    second=str(right),
                )

    return TaskSpec(
        task_id=task_id,
        command=CommandSpec(argv=tuple(argv), working_directory=working_directory),
        files=files,
        configs=tuple(sorted(configs, key=lambda item: item.file)),
        environment=environment,
        artifacts=tuple(sorted(artifacts, key=lambda item: (item.task, item.path))),
        output=OutputSpec(publish=publish, required=required),
    )


def normalize_relative_path(value: Any, *, allow_dot: bool = False) -> str:
    path_text = _string(value, "path")
    if "\\" in path_text:
        raise SpecError(
            "INVALID_PATH",
            "Pipeline paths must use POSIX separators.",
            path=path_text,
        )
    path = PurePosixPath(path_text)
    if path.is_absolute() or ".." in path.parts:
        raise SpecError(
            "PATH_ESCAPE",
            "Pipeline paths must stay below the project root.",
            path=path_text,
        )
    normalized = str(path)
    if normalized in {"", "."}:
        if allow_dot:
            return "."
        raise SpecError("INVALID_PATH", "A declared path cannot be empty or '.'.", path=path_text)
    if path.parts[0] == ".rebuildwhy":
        raise SpecError(
            "RESERVED_PATH",
            "The .rebuildwhy directory is reserved for engine state.",
            path=path_text,
        )
    return normalized


def _validate_publication_paths(pipeline: PipelineSpec) -> None:
    publications = {
        task.task_id: PurePosixPath(task.output.publish) for task in pipeline.tasks.values()
    }
    items = sorted(publications.items())
    for index, (left_id, left_path) in enumerate(items):
        for right_id, right_path in items[index + 1 :]:
            overlaps = (
                left_path == right_path
                or left_path in right_path.parents
                or right_path in left_path.parents
            )
            if overlaps:
                raise SpecError(
                    "OVERLAPPING_PUBLICATIONS",
                    "Task publication directories must not overlap.",
                    first_task=left_id,
                    second_task=right_id,
                )

    for task in pipeline.tasks.values():
        source_paths = list(task.files) + [config.file for config in task.configs]
        for source in source_paths:
            source_path = PurePosixPath(source)
            for producer_id, publication in publications.items():
                if source_path == publication or publication in source_path.parents:
                    raise SpecError(
                        "PUBLICATION_AS_SOURCE",
                        "Published task data must be consumed through an artifact dependency.",
                        task_id=task.task_id,
                        producer=producer_id,
                        path=source,
                    )


def _load_yaml_file(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = yaml.load(stream, Loader=UniqueKeyLoader)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        details: dict[str, Any] = {"path": str(path)}
        if mark is not None:
            details.update(line=mark.line + 1, column=mark.column + 1)
        raise SpecError("INVALID_YAML", "The YAML document is invalid.", **details) from error
    _validate_json_compatible(value, str(path))
    return value


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SpecError("DUPLICATE_JSON_KEY", "JSON mapping keys must be unique.", key=key)
        result[key] = value
    return result


def _validate_json_compatible(value: Any, location: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise SpecError(
            "NON_FINITE_VALUE",
            "NaN and Infinity are not supported in configuration values.",
            location=location,
        )
    if value is None or isinstance(value, str | bool | int | float):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_compatible(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SpecError(
                    "NON_STRING_MAPPING_KEY",
                    "Configuration mapping keys must be strings.",
                    location=location,
                )
            _validate_json_compatible(item, f"{location}.{key}")
        return
    raise SpecError(
        "NON_JSON_VALUE",
        "YAML values must be compatible with the JSON data model.",
        location=location,
        value_type=type(value).__name__,
    )


def _pointer_tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise SpecError(
            "INVALID_JSON_POINTER",
            "A JSON Pointer must be empty or begin with '/'.",
            pointer=pointer,
        )
    tokens: list[str] = []
    for raw_token in pointer[1:].split("/"):
        index = 0
        decoded = ""
        while index < len(raw_token):
            if raw_token[index] == "~":
                if index + 1 >= len(raw_token) or raw_token[index + 1] not in {"0", "1"}:
                    raise SpecError(
                        "INVALID_JSON_POINTER",
                        "JSON Pointer '~' escapes must be '~0' or '~1'.",
                        pointer=pointer,
                    )
                decoded += "~" if raw_token[index + 1] == "0" else "/"
                index += 2
            else:
                decoded += raw_token[index]
                index += 1
        tokens.append(decoded)
    return tokens


def _descend_pointer(parent: Any, token: str, pointer: str) -> Any:
    if isinstance(parent, dict) and token in parent:
        return parent[token]
    if isinstance(parent, list) and token.isdigit() and int(token) < len(parent):
        return parent[int(token)]
    raise SpecError(
        "JSON_POINTER_NOT_FOUND",
        "A counterfactual overlay may replace only an existing value.",
        pointer=pointer,
        token=token,
    )


def _json_pointer(value: str) -> str:
    _pointer_tokens(value)
    return value


def _environment_name(value: str) -> str:
    if not ENVIRONMENT_PATTERN.fullmatch(value):
        raise SpecError(
            "INVALID_ENVIRONMENT_NAME",
            "Environment dependency names must be portable variable names.",
            name=value,
        )
    return value


def _mapping(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SpecError("EXPECTED_MAPPING", "A YAML mapping is required.", location=location)
    if not all(isinstance(key, str) for key in value):
        raise SpecError(
            "NON_STRING_MAPPING_KEY",
            "YAML mapping keys must be strings.",
            location=location,
        )
    return value


def _list(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise SpecError("EXPECTED_LIST", "A YAML list is required.", location=location)
    return value


def _string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise SpecError("EXPECTED_STRING", "A non-empty string is required.", location=location)
    return value


def _string_list(value: Any, location: str) -> list[str]:
    return [
        _string(item, f"{location}[{index}]") for index, item in enumerate(_list(value, location))
    ]


def _unique(values: Any) -> list[Any]:
    result: list[Any] = []
    seen: set[Any] = set()
    for value in values:
        if value in seen:
            raise SpecError("DUPLICATE_VALUE", "List values must be unique.", value=value)
        seen.add(value)
        result.append(value)
    return result


def _reject_unknown(mapping: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise SpecError(
            "UNKNOWN_FIELD",
            "The specification contains unsupported fields.",
            location=location,
            fields=unknown,
        )
