"""Small helpers for the synthetic task protocol."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def context() -> dict[str, Any]:
    """Read the execution context supplied by RebuildWhy."""

    return json.loads(Path(os.environ["REBUILDWHY_CONTEXT"]).read_text(encoding="utf-8"))


def read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(directory: str, name: str, value: Any) -> None:
    path = Path(directory) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
