"""Verified local content-addressed cache and publication views."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from rebuildwhy.canonical import (
    atomic_write_json,
    canonical_json_bytes,
    digest_hex,
    sha256_bytes,
    sha256_file,
    sha256_value,
)
from rebuildwhy.errors import IntegrityError, SpecError
from rebuildwhy.models import ReasonCode, TaskSpec

Failpoint = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class CacheInspection:
    """The result of verifying one action-cache entry."""

    record: dict[str, Any] | None
    reason: ReasonCode | None = None

    @property
    def valid(self) -> bool:
        return self.record is not None


class CacheStore:
    """A project-local cache whose reusable entries are verified on every read."""

    def __init__(self, root: Path, *, failpoint: Failpoint | None = None) -> None:
        self.project_root = root.resolve()
        self.root = self.project_root / ".rebuildwhy"
        self.objects = self.root / "objects" / "sha256"
        self.manifests = self.root / "manifests"
        self.actions = self.root / "actions"
        self.state = self.root / "state"
        self.artifacts = self.root / "artifacts"
        self.temporary = self.root / "tmp"
        self.quarantine = self.root / "quarantine"
        self._failpoint = failpoint

    def initialize(self) -> None:
        """Create cache directories without changing any reusable entry."""

        for directory in (
            self.objects,
            self.manifests,
            self.actions,
            self.state,
            self.artifacts,
            self.temporary,
            self.quarantine,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def action_path(self, action_key: str) -> Path:
        return self.actions / f"{digest_hex(action_key)}.json"

    def manifest_path(self, manifest_digest: str) -> Path:
        return self.manifests / f"{digest_hex(manifest_digest)}.json"

    def object_path(self, object_digest: str) -> Path:
        return self.objects / digest_hex(object_digest)

    def artifact_path(self, manifest_digest: str) -> Path:
        return self.artifacts / digest_hex(manifest_digest)

    def inspect_action(self, action_key: str) -> CacheInspection:
        """Return a verified action record or a stable cache failure reason."""

        path = self.action_path(action_key)
        if not path.is_file():
            return CacheInspection(None, ReasonCode.ACTION_RECORD_MISSING)
        try:
            record = self._read_json(path, "ACTION_RECORD_CORRUPT")
            self._validate_action(record, action_key)
            self.verify_manifest(record["manifest_digest"])
        except IntegrityError as error:
            return CacheInspection(None, _integrity_reason(error.code))
        return CacheInspection(record)

    def load_baseline(self, task_id: str) -> CacheInspection:
        """Load the last successfully published action for a task."""

        path = self.state / f"{task_id}.json"
        if not path.is_file():
            return CacheInspection(None, ReasonCode.ACTION_RECORD_MISSING)
        try:
            state = self._read_json(path, "ACTION_RECORD_CORRUPT")
            if not isinstance(state, dict) or state.get("task_id") != task_id:
                raise IntegrityError(
                    "ACTION_RECORD_CORRUPT",
                    "The task state record has an invalid identity.",
                    task_id=task_id,
                )
            action_key = state.get("action_key")
            if not isinstance(action_key, str):
                raise IntegrityError(
                    "ACTION_RECORD_CORRUPT",
                    "The task state record has no action key.",
                    task_id=task_id,
                )
            try:
                digest_hex(action_key)
            except ValueError as error:
                raise IntegrityError(
                    "ACTION_RECORD_CORRUPT",
                    "The task state record contains an invalid action key.",
                    task_id=task_id,
                ) from error
        except IntegrityError as error:
            return CacheInspection(None, _integrity_reason(error.code))
        inspection = self.inspect_action(action_key)
        record = inspection.record
        if record is not None and record["task_id"] != task_id:
            return CacheInspection(None, ReasonCode.ACTION_RECORD_CORRUPT)
        return inspection

    def verify_manifest(self, manifest_digest: str) -> dict[str, Any]:
        """Verify a manifest and every immutable file object it references."""

        path = self.manifest_path(manifest_digest)
        if not path.is_file():
            raise IntegrityError(
                "CACHE_MANIFEST_MISSING",
                "A referenced artifact manifest is missing.",
                manifest_digest=manifest_digest,
            )
        try:
            data = path.read_bytes()
        except OSError as error:
            raise IntegrityError(
                "CACHE_MANIFEST_CORRUPT",
                "An artifact manifest cannot be read.",
                manifest_digest=manifest_digest,
            ) from error
        if sha256_bytes(data) != manifest_digest:
            raise IntegrityError(
                "CACHE_MANIFEST_CORRUPT",
                "An artifact manifest digest does not match its contents.",
                manifest_digest=manifest_digest,
            )
        try:
            manifest_value = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise IntegrityError(
                "CACHE_MANIFEST_CORRUPT",
                "An artifact manifest is not valid canonical JSON.",
                manifest_digest=manifest_digest,
            ) from error
        self._validate_manifest(manifest_value)
        manifest = cast(dict[str, Any], manifest_value)
        if canonical_json_bytes(manifest) != data:
            raise IntegrityError(
                "CACHE_MANIFEST_CORRUPT",
                "An artifact manifest is not canonically encoded.",
                manifest_digest=manifest_digest,
            )
        for entry in manifest["files"]:
            object_path = self.object_path(entry["digest"])
            if not object_path.is_file():
                raise IntegrityError(
                    "CACHE_OBJECT_MISSING",
                    "A file object referenced by a manifest is missing.",
                    digest=entry["digest"],
                    path=entry["path"],
                )
            actual_digest, actual_size = sha256_file(object_path)
            if actual_digest != entry["digest"] or actual_size != entry["size"]:
                raise IntegrityError(
                    "CACHE_OBJECT_CORRUPT",
                    "A cached file object's bytes do not match its digest.",
                    digest=entry["digest"],
                    path=entry["path"],
                )
        return manifest

    def output_view_valid(self, task: TaskSpec, manifest_digest: str) -> bool:
        """Return whether a task's publication link targets the expected bundle."""

        publication = self.project_root / task.output.publish
        try:
            publication.parent.resolve().relative_to(self.project_root)
        except ValueError as error:
            raise SpecError(
                "PATH_ESCAPE",
                "The publication parent resolves outside the project root.",
                task_id=task.task_id,
                path=str(publication.parent),
            ) from error
        if not publication.is_symlink():
            return False
        manifest = self.verify_manifest(manifest_digest)
        expected_bundle = self.artifact_path(manifest_digest)
        try:
            correct_target = publication.resolve(strict=True) == expected_bundle.resolve(
                strict=True
            )
        except FileNotFoundError:
            return False
        return correct_target and self._bundle_matches(expected_bundle, manifest)

    def artifact_entry(self, manifest_digest: str, relative_path: str) -> dict[str, Any]:
        """Return one verified manifest file record."""

        manifest = self.verify_manifest(manifest_digest)
        for entry in manifest["files"]:
            if entry["path"] == relative_path:
                return cast(dict[str, Any], entry)
        raise IntegrityError(
            "CACHE_MANIFEST_CORRUPT",
            "A required artifact is absent from its manifest.",
            manifest_digest=manifest_digest,
            path=relative_path,
        )

    def write_bundle(
        self,
        *,
        task: TaskSpec,
        action_key: str,
        snapshot: dict[str, Any],
        staging_output: Path,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """Store all immutable data and atomically create the complete action record."""

        self.initialize()
        for entry in manifest["files"]:
            self._store_object(staging_output / entry["path"], entry)
        self._hit("after_objects")

        manifest_bytes = canonical_json_bytes(manifest)
        manifest_digest = sha256_bytes(manifest_bytes)
        self._store_immutable(self.manifest_path(manifest_digest), manifest_bytes)
        self._hit("after_manifest")
        self._materialize_bundle(manifest_digest, manifest)

        record = {
            "schema_version": 1,
            "complete": True,
            "task_id": task.task_id,
            "action_key": action_key,
            "manifest_digest": manifest_digest,
            "snapshot": snapshot,
        }
        action_path = self.action_path(action_key)
        if action_path.exists():
            inspection = self.inspect_action(action_key)
            if inspection.valid:
                if inspection.record != record:
                    raise IntegrityError(
                        "ACTION_RECORD_CONFLICT",
                        "An action key already maps to a different verified result.",
                        action_key=action_key,
                    )
                return record
            self._quarantine(action_path)
        self._hit("before_action_record")
        atomic_write_json(action_path, record)
        return record

    def publish(self, task: TaskSpec, record: dict[str, Any]) -> None:
        """Atomically switch a managed output symlink and then update task state."""

        manifest_digest = record["manifest_digest"]
        manifest = self.verify_manifest(manifest_digest)
        self._materialize_bundle(manifest_digest, manifest)
        publication = self.project_root / task.output.publish
        publication.parent.mkdir(parents=True, exist_ok=True)
        try:
            publication.parent.resolve().relative_to(self.project_root)
        except ValueError as error:
            raise SpecError(
                "PATH_ESCAPE",
                "The publication parent resolves outside the project root.",
                task_id=task.task_id,
                path=str(publication.parent),
            ) from error
        if publication.exists() and not publication.is_symlink():
            raise SpecError(
                "OUTPUT_PATH_CONFLICT",
                "RebuildWhy will not replace an unmanaged output file or directory.",
                task_id=task.task_id,
                path=str(publication),
            )
        if publication.is_symlink() and self.output_view_valid(task, manifest_digest):
            self._write_state(task.task_id, record)
            return

        temporary_link = publication.parent / f".{publication.name}.{uuid.uuid4().hex}.tmp"
        target = self.artifact_path(manifest_digest)
        relative_target = os.path.relpath(target, publication.parent)
        self._hit("before_publish")
        try:
            temporary_link.symlink_to(relative_target, target_is_directory=True)
            os.replace(temporary_link, publication)
        finally:
            temporary_link.unlink(missing_ok=True)
        self._hit("after_publish_before_state")
        self._write_state(task.task_id, record)

    def restore(self, task: TaskSpec, record: dict[str, Any]) -> None:
        """Rematerialize a verified action result without executing its command."""

        self.publish(task, record)

    def new_staging_directory(self, task_id: str) -> Path:
        """Create one isolated execution directory below the cache root."""

        self.initialize()
        return Path(tempfile.mkdtemp(prefix=f"{task_id}-", dir=self.temporary))

    def _write_state(self, task_id: str, record: dict[str, Any]) -> None:
        atomic_write_json(
            self.state / f"{task_id}.json",
            {
                "schema_version": 1,
                "task_id": task_id,
                "action_key": record["action_key"],
                "manifest_digest": record["manifest_digest"],
            },
        )

    def _store_object(self, source: Path, entry: dict[str, Any]) -> None:
        destination = self.object_path(entry["digest"])
        if destination.exists():
            actual_digest, actual_size = sha256_file(destination)
            if actual_digest == entry["digest"] and actual_size == entry["size"]:
                return
            self._quarantine(destination)
        descriptor, temporary_name = tempfile.mkstemp(prefix="object-", dir=self.temporary)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as target, source.open("rb") as origin:
                shutil.copyfileobj(origin, target)
                target.flush()
                os.fsync(target.fileno())
            digest, size = sha256_file(temporary_path)
            if digest != entry["digest"] or size != entry["size"]:
                raise IntegrityError(
                    "OUTPUT_CHANGED_DURING_HASH",
                    "An output changed while it was entering the cache.",
                    path=entry["path"],
                )
            os.chmod(temporary_path, 0o444)
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _store_immutable(self, destination: Path, data: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() == data:
                return
            self._quarantine(destination)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_path, 0o444)
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _materialize_bundle(self, manifest_digest: str, manifest: dict[str, Any]) -> None:
        destination = self.artifact_path(manifest_digest)
        if destination.exists():
            try:
                if self._bundle_matches(destination, manifest):
                    return
            except OSError:
                pass
            self._quarantine(destination)
        temporary = Path(tempfile.mkdtemp(prefix="bundle-", dir=self.temporary))
        try:
            for entry in manifest["files"]:
                output = temporary / entry["path"]
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.object_path(entry["digest"]), output)
                os.chmod(output, 0o555 if entry["executable"] else 0o444)
            os.replace(temporary, destination)
            for directory, _, _ in os.walk(destination, topdown=False):
                os.chmod(directory, 0o555)
        finally:
            if temporary.exists():
                for directory, _, _ in os.walk(temporary, topdown=False):
                    os.chmod(directory, 0o755)
                shutil.rmtree(temporary)

    def _bundle_matches(self, bundle: Path, manifest: dict[str, Any]) -> bool:
        if bundle.is_symlink() or not bundle.is_dir():
            return False
        expected = {entry["path"]: entry for entry in manifest["files"]}
        actual: set[str] = set()
        for path in bundle.rglob("*"):
            relative = path.relative_to(bundle).as_posix()
            metadata = path.lstat()
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode) or relative not in expected:
                return False
            actual.add(relative)
            digest, size = sha256_file(path)
            entry = expected[relative]
            if digest != entry["digest"] or size != entry["size"]:
                return False
            if bool(metadata.st_mode & 0o111) != entry["executable"]:
                return False
        return actual == set(expected)

    def _quarantine(self, path: Path) -> None:
        self.quarantine.mkdir(parents=True, exist_ok=True)
        destination = self.quarantine / f"{path.name}.{uuid.uuid4().hex}"
        if path.is_dir() and not path.is_symlink():
            os.chmod(path, 0o755)
        os.replace(path, destination)

    def _read_json(self, path: Path, code: str) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IntegrityError(code, "Cached metadata is invalid.", path=str(path)) from error

    def _validate_action(self, record: Any, action_key: str) -> None:
        valid = (
            isinstance(record, dict)
            and record.get("schema_version") == 1
            and record.get("complete") is True
            and record.get("action_key") == action_key
            and isinstance(record.get("task_id"), str)
            and isinstance(record.get("manifest_digest"), str)
            and isinstance(record.get("snapshot"), dict)
        )
        if not valid:
            raise IntegrityError(
                "ACTION_RECORD_CORRUPT",
                "An action record is incomplete or inconsistent.",
                action_key=action_key,
            )
        try:
            digest_hex(record["action_key"])
            digest_hex(record["manifest_digest"])
        except ValueError as error:
            raise IntegrityError(
                "ACTION_RECORD_CORRUPT",
                "An action record contains an invalid digest.",
                action_key=action_key,
            ) from error
        try:
            snapshot_action_key = sha256_value(record["snapshot"])
        except SpecError as error:
            raise IntegrityError(
                "ACTION_RECORD_CORRUPT",
                "An action record contains a non-canonical snapshot.",
                action_key=action_key,
            ) from error
        if snapshot_action_key != action_key:
            raise IntegrityError(
                "ACTION_RECORD_CORRUPT",
                "An action record snapshot does not match its action key.",
                action_key=action_key,
            )

    def _validate_manifest(self, manifest: Any) -> None:
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise IntegrityError("CACHE_MANIFEST_CORRUPT", "Invalid artifact manifest.")
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise IntegrityError("CACHE_MANIFEST_CORRUPT", "Invalid artifact file list.")
        seen: set[str] = set()
        for entry in files:
            if not isinstance(entry, dict):
                raise IntegrityError("CACHE_MANIFEST_CORRUPT", "Invalid artifact entry.")
            path = entry.get("path")
            pure = PurePosixPath(path) if isinstance(path, str) else None
            valid = (
                pure is not None
                and not pure.is_absolute()
                and ".." not in pure.parts
                and str(pure) not in {"", "."}
                and path not in seen
                and isinstance(entry.get("digest"), str)
                and isinstance(entry.get("size"), int)
                and entry["size"] >= 0
                and isinstance(entry.get("executable"), bool)
            )
            if not valid:
                raise IntegrityError("CACHE_MANIFEST_CORRUPT", "Invalid artifact entry.")
            assert isinstance(path, str)
            try:
                digest_hex(entry["digest"])
            except ValueError as error:
                raise IntegrityError(
                    "CACHE_MANIFEST_CORRUPT", "Invalid artifact digest."
                ) from error
            seen.add(path)
        if [entry["path"] for entry in files] != sorted(seen):
            raise IntegrityError(
                "CACHE_MANIFEST_CORRUPT", "Artifact entries are not canonically sorted."
            )

    def _hit(self, name: str) -> None:
        if self._failpoint is not None:
            self._failpoint(name)


def _integrity_reason(code: str) -> ReasonCode:
    mapping = {
        "ACTION_RECORD_CORRUPT": ReasonCode.ACTION_RECORD_CORRUPT,
        "CACHE_MANIFEST_MISSING": ReasonCode.CACHE_MANIFEST_MISSING,
        "CACHE_MANIFEST_CORRUPT": ReasonCode.CACHE_MANIFEST_CORRUPT,
        "CACHE_OBJECT_MISSING": ReasonCode.CACHE_OBJECT_MISSING,
        "CACHE_OBJECT_CORRUPT": ReasonCode.CACHE_OBJECT_CORRUPT,
    }
    return mapping.get(code, ReasonCode.ACTION_RECORD_CORRUPT)
