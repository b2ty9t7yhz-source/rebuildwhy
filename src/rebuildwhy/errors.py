"""Structured errors used by the library and command-line interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RebuildWhyError(Exception):
    """A stable, machine-readable project error."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    exit_code: int = 2

    def __post_init__(self) -> None:
        # ``dataclass(slots=True)`` creates a replacement class object. A
        # zero-argument ``super()`` can keep the pre-slots ``__class__`` cell
        # on Python 3.13, so initialize the Exception base explicitly.
        Exception.__init__(self, self.message)

    def to_dict(self) -> dict[str, Any]:
        """Return the public error envelope used by JSON CLI output."""

        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class SpecError(RebuildWhyError):
    """Raised when a pipeline or configuration document is invalid."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(code=code, message=message, details=details, exit_code=2)


class IntegrityError(RebuildWhyError):
    """Raised when immutable cache data fails verification."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(code=code, message=message, details=details, exit_code=3)


class ExecutionError(RebuildWhyError):
    """Raised when a trusted task cannot complete or publish."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(code=code, message=message, details=details, exit_code=4)
