from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml


@pytest.fixture
def pipeline_factory(tmp_path: Path) -> Callable[[dict[str, Any]], Path]:
    def create(document: dict[str, Any]) -> Path:
        pipeline_path = tmp_path / "pipeline.yaml"
        pipeline_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return pipeline_path

    return create


@pytest.fixture
def minimal_pipeline() -> dict[str, Any]:
    return {
        "version": 1,
        "project": "test-project",
        "tasks": {
            "source": {
                "command": {"argv": ["python", "source.py"]},
                "inputs": {"files": ["source.py"]},
                "output": {"publish": "outputs/source", "required": ["value.txt"]},
            },
            "consumer": {
                "command": {"argv": ["python", "consumer.py"]},
                "inputs": {
                    "files": ["consumer.py"],
                    "artifacts": [{"task": "source", "path": "value.txt"}],
                },
                "output": {"publish": "outputs/consumer", "required": ["result.txt"]},
            },
        },
    }
