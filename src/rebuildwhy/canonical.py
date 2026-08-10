"""Canonical encoding, hashing, and atomic metadata writes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

from rebuildwhy.errors import SpecError


def _reject_non_finite(value: Any, location: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise SpecError(
            "NON_FINITE_VALUE",
            "NaN and Infinity are not supported in canonical values.",
            location=location,
        )
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_non_finite(item, f"{location}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_non_finite(item, f"{location}.{key}")


def canonical_json_bytes(value: Any) -> bytes:
    """Encode JSON-compatible data deterministically as UTF-8 bytes."""

    _reject_non_finite(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_text(value: Any, *, pretty: bool = False) -> str:
    """Encode JSON-compatible data deterministically for display or storage."""

    _reject_non_finite(value)
    if pretty:
        return (
            json.dumps(
                value,
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )
    return canonical_json_bytes(value).decode("utf-8")


def sha256_bytes(data: bytes) -> str:
    """Return a tagged SHA-256 digest."""

    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def sha256_value(value: Any) -> str:
    """Hash a canonical JSON value."""

    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: Path) -> tuple[str, int]:
    """Hash a regular file without loading it all into memory."""

    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return f"sha256:{digest.hexdigest()}", size


def digest_hex(tagged_digest: str) -> str:
    """Return the hexadecimal portion of a tagged SHA-256 digest."""

    prefix, separator, hexadecimal = tagged_digest.partition(":")
    if separator != ":" or prefix != "sha256" or len(hexadecimal) != 64:
        raise ValueError(f"Invalid tagged SHA-256 digest: {tagged_digest!r}")
    int(hexadecimal, 16)
    return hexadecimal


def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o644) -> None:
    """Atomically replace one metadata file on its existing filesystem."""

    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, value: Any) -> None:
    """Atomically write canonical JSON metadata."""

    atomic_write_bytes(path, canonical_json_bytes(value))


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
