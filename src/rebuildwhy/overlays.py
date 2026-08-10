"""Non-mutating counterfactual workspace overlays."""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rebuildwhy.errors import SpecError
from rebuildwhy.models import ConfigOverlay, FileOverlay, OverlaySet, PipelineSpec
from rebuildwhy.spec import (
    load_config_document,
    normalize_relative_path,
    replace_json_pointer,
)


def parse_overlays(
    pipeline: PipelineSpec,
    *,
    set_values: list[str] | None = None,
    replace_files: list[str] | None = None,
) -> OverlaySet:
    """Parse CLI overlay expressions and validate their declared locators."""

    configs: list[ConfigOverlay] = []
    files: list[FileOverlay] = []
    seen_configs: set[tuple[str, str]] = set()
    seen_files: set[str] = set()

    for expression in set_values or []:
        locator, separator, raw_value = expression.partition("=")
        config_file, hash_mark, pointer = locator.partition("#")
        if separator != "=" or hash_mark != "#":
            raise SpecError(
                "INVALID_CONFIG_OVERLAY",
                "Config overlays must use FILE#JSON_POINTER=JSON_VALUE.",
                expression=expression,
            )
        logical_file = normalize_relative_path(config_file)
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise SpecError(
                "INVALID_CONFIG_OVERLAY_VALUE",
                "A config overlay value must be valid JSON.",
                expression=expression,
                line=error.lineno,
                column=error.colno,
            ) from error
        key = (logical_file, pointer)
        if key in seen_configs:
            raise SpecError(
                "DUPLICATE_CONFIG_OVERLAY",
                "A config field may be overlaid only once.",
                locator=f"{logical_file}#{pointer}",
            )
        seen_configs.add(key)
        configs.append(ConfigOverlay(file=logical_file, pointer=pointer, value=value))

    for expression in replace_files or []:
        logical, separator, replacement_text = expression.partition("=")
        if separator != "=" or not replacement_text:
            raise SpecError(
                "INVALID_FILE_OVERLAY",
                "File overlays must use LOGICAL_FILE=REPLACEMENT_FILE.",
                expression=expression,
            )
        logical_file = normalize_relative_path(logical)
        if logical_file in seen_files:
            raise SpecError(
                "DUPLICATE_FILE_OVERLAY",
                "A logical file may be replaced only once.",
                file=logical_file,
            )
        replacement = Path(replacement_text).expanduser()
        if not replacement.is_absolute():
            replacement = pipeline.root / replacement
        _require_regular_file(replacement, logical_file)
        replacement = replacement.resolve()
        seen_files.add(logical_file)
        files.append(FileOverlay(file=logical_file, replacement=replacement))

    overlays = OverlaySet(
        configs=tuple(sorted(configs, key=lambda item: (item.file, item.pointer))),
        files=tuple(sorted(files, key=lambda item: item.file)),
    )
    _validate_declared_locators(pipeline, overlays)
    return overlays


@dataclass(slots=True)
class WorkspaceView:
    """Read source data through an immutable logical overlay view."""

    pipeline: PipelineSpec
    overlays: OverlaySet = field(default_factory=OverlaySet)
    _documents: dict[str, Any] = field(default_factory=dict, init=False)

    def source_path(self, logical_path: str) -> Path:
        """Resolve a logical file to its real or replacement source path."""

        replacements = {overlay.file: overlay.replacement for overlay in self.overlays.files}
        if logical_path in replacements:
            return replacements[logical_path]
        path = self.pipeline.root / logical_path
        _require_regular_file(path, logical_path)
        resolved = path.resolve()
        try:
            resolved.relative_to(self.pipeline.root)
        except ValueError as error:
            raise SpecError(
                "PATH_ESCAPE",
                "A declared source resolves outside the project root.",
                logical_path=logical_path,
                path=str(resolved),
            ) from error
        return resolved

    def config_document(self, logical_path: str) -> Any:
        """Load a config document and apply matching replacements in memory."""

        if logical_path not in self._documents:
            document = load_config_document(self.source_path(logical_path))
            for overlay in self.overlays.configs:
                if overlay.file == logical_path:
                    document = replace_json_pointer(document, overlay.pointer, overlay.value)
            self._documents[logical_path] = document
        return self._documents[logical_path]


def _validate_declared_locators(pipeline: PipelineSpec, overlays: OverlaySet) -> None:
    declared_files = {
        logical
        for task in pipeline.tasks.values()
        for logical in (*task.files, *(config.file for config in task.configs))
    }
    declared_config_files = {
        dependency.file for task in pipeline.tasks.values() for dependency in task.configs
    }
    for file_overlay in overlays.files:
        if file_overlay.file not in declared_files:
            raise SpecError(
                "UNDECLARED_FILE_OVERLAY",
                "A file overlay must target a declared file or config input.",
                file=file_overlay.file,
            )
    for config_overlay in overlays.configs:
        if config_overlay.file not in declared_config_files:
            raise SpecError(
                "UNDECLARED_CONFIG_OVERLAY",
                "A config overlay must target a declared configuration file.",
                locator=f"{config_overlay.file}#{config_overlay.pointer}",
            )


def _require_regular_file(path: Path, logical_path: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise SpecError(
            "MISSING_SOURCE_INPUT",
            "A declared source input does not exist.",
            logical_path=logical_path,
            path=str(path),
        ) from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SpecError(
            "UNSUPPORTED_SOURCE_TYPE",
            "Declared source inputs must be regular files, not links or special files.",
            logical_path=logical_path,
            path=str(path),
        )
