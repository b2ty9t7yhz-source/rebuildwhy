from __future__ import annotations

import json
from pathlib import Path

import pytest

from rebuildwhy.canonical import (
    atomic_write_json,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    sha256_value,
)
from rebuildwhy.errors import SpecError


def test_canonical_json_sorts_mapping_keys() -> None:
    left = canonical_json_bytes({"b": 2, "a": [3, 1]})
    right = canonical_json_bytes({"a": [3, 1], "b": 2})

    assert left == right == b'{"a":[3,1],"b":2}'


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(SpecError, match="NaN and Infinity"):
        canonical_json_bytes({"value": value})


def test_sha256_helpers_use_tagged_digests(tmp_path: Path) -> None:
    path = tmp_path / "input.bin"
    path.write_bytes(b"abc")

    digest, size = sha256_file(path)

    assert digest == sha256_bytes(b"abc")
    assert digest.startswith("sha256:")
    assert len(digest) == 71
    assert size == 3
    assert sha256_value({"x": 1}) == sha256_bytes(b'{"x":1}')


def test_atomic_write_json_replaces_complete_document(tmp_path: Path) -> None:
    path = tmp_path / "state" / "record.json"
    atomic_write_json(path, {"version": 1})
    atomic_write_json(path, {"version": 2, "complete": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "complete": True,
        "version": 2,
    }
