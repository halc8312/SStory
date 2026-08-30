#!/usr/bin/env python3
"""Stable byte bindings for fail-closed map release artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import atexit
import shutil
import tempfile
import threading
import uuid
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterable, Iterator

from release_path_safety import (
    ReleasePathError,
    assert_no_reparse_components,
    canonical_repo_relative,
    require_trackable_path,
)
from production_common import REPO_ROOT


class BoundArtifactError(RuntimeError):
    """Raised when an artifact cannot be bound to one stable byte snapshot."""


MEMORY_SNAPSHOT_LIMIT = 4 * 1024 * 1024
SNAPSHOT_PARENT = REPO_ROOT / "tmp" / "map-production"
SNAPSHOT_PREFIX = ".phase5-bound-snapshots-"
SNAPSHOT_MARKER = ".phase5-bound-artifacts-owned.json"
_SNAPSHOT_LOCK = threading.RLock()
_SNAPSHOT_ROOT: Path | None = None
_SNAPSHOT_TOKEN = uuid.uuid4().hex


def _snapshot_root() -> Path:
    global _SNAPSHOT_ROOT
    with _SNAPSHOT_LOCK:
        if _SNAPSHOT_ROOT is not None:
            return _SNAPSHOT_ROOT
        SNAPSHOT_PARENT.mkdir(parents=True, exist_ok=True)
        assert_no_reparse_components(SNAPSHOT_PARENT, label="snapshot parent")
        root = Path(
            tempfile.mkdtemp(
                prefix=f"{SNAPSHOT_PREFIX}{os.getpid()}-",
                dir=SNAPSHOT_PARENT,
            )
        )
        assert_no_reparse_components(root, label="snapshot root")
        marker = {
            "schema_version": "1.0.0",
            "owned_by": "sstory-map-production/release_bound_artifact.py@1",
            "pid": os.getpid(),
            "token": _SNAPSHOT_TOKEN,
        }
        (root / SNAPSHOT_MARKER).write_text(
            json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8"
        )
        _SNAPSHOT_ROOT = root
        return root


def snapshot_transaction_debris() -> tuple[Path, ...]:
    """List snapshot arenas left by other or abnormally terminated processes."""

    if not SNAPSHOT_PARENT.is_dir():
        return ()
    assert_no_reparse_components(SNAPSHOT_PARENT, label="snapshot parent")
    own = _SNAPSHOT_ROOT
    return tuple(
        sorted(
            (
                child
                for child in SNAPSHOT_PARENT.iterdir()
                if child.name.startswith(SNAPSHOT_PREFIX)
                and (own is None or path_identity(child) != path_identity(own))
            ),
            key=lambda item: item.name.casefold(),
        )
    )


def cleanup_snapshot_arena() -> None:
    """Delete only this process's marker-authenticated snapshot arena."""

    global _SNAPSHOT_ROOT
    with _SNAPSHOT_LOCK:
        root = _SNAPSHOT_ROOT
        if root is None:
            return
        try:
            assert_no_reparse_components(root, label="snapshot cleanup root")
            marker = json.loads((root / SNAPSHOT_MARKER).read_text(encoding="utf-8"))
            if (
                marker.get("token") != _SNAPSHOT_TOKEN
                or marker.get("pid") != os.getpid()
            ):
                return
            shutil.rmtree(root)
            _SNAPSHOT_ROOT = None
        except (FileNotFoundError, OSError, json.JSONDecodeError, ReleasePathError):
            # Cleanup is best effort and must never turn a committed release
            # into a reported failure.  The debris scanner exposes leftovers.
            return


atexit.register(cleanup_snapshot_arena)


def path_identity(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _stat_signature(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


@dataclass(frozen=True)
class BoundArtifact:
    """One physical pathname bound to the exact bytes read from one handle."""

    label: str
    path: Path
    relative: str
    _data: bytes | None
    snapshot_path: Path | None
    snapshot_signature: tuple[int, int, int, int] | None
    sha256: str
    signature: tuple[int, int, int, int]
    trackable: bool
    _finalizer: Any = None

    @property
    def data(self) -> bytes:
        if self._data is not None:
            return self._data
        try:
            with self.open_binary() as handle:
                return handle.read()
        except (OSError, BoundArtifactError) as exc:
            raise BoundArtifactError(
                f"cannot read bound snapshot for {self.label}: {exc}"
            ) from exc

    @contextmanager
    def open_binary(self) -> Iterator[BinaryIO]:
        if self._data is not None:
            from io import BytesIO

            with BytesIO(self._data) as handle:
                yield handle
            return
        if self.snapshot_path is None:
            raise BoundArtifactError(f"{self.label} has no byte snapshot")
        with self.snapshot_path.open("rb") as handle:
            if _stat_signature(os.fstat(handle.fileno())) != self.snapshot_signature:
                raise BoundArtifactError(
                    f"internal byte snapshot changed for {self.label}"
                )
            yield handle

    def copy_to(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.open_binary() as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)

    @property
    def identity(self) -> str:
        return path_identity(self.path)

    def artifact(self) -> dict[str, str]:
        return {"path": self.relative, "sha256": self.sha256}

    def json_value(self) -> Any:
        try:
            return json.loads(self.data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise BoundArtifactError(
                f"{self.label} is not valid UTF-8 JSON: {self.path}: {exc}"
            ) from exc

    def json_object(self) -> dict[str, Any]:
        value = self.json_value()
        if not isinstance(value, dict):
            raise BoundArtifactError(
                f"{self.label} must contain a JSON object: {self.path}"
            )
        return value

    def assert_unchanged(self) -> None:
        try:
            if self.trackable:
                resolved, _ = require_trackable_path(self.path, label=self.label)
            else:
                resolved, _ = canonical_repo_relative(self.path, label=self.label)
            digest = hashlib.sha256()
            with resolved.open("rb") as handle:
                before = os.fstat(handle.fileno())
                bytes_read = 0
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                    bytes_read += len(chunk)
                after = os.fstat(handle.fileno())
            current = os.stat(resolved, follow_symlinks=False)
        except (OSError, ReleasePathError) as exc:
            raise BoundArtifactError(
                f"cannot recheck bound {self.label}: {exc}"
            ) from exc
        if (
            _stat_signature(before) != _stat_signature(after)
            or _stat_signature(after) != _stat_signature(current)
            or bytes_read != after.st_size
            or _stat_signature(after) != self.signature
            or digest.hexdigest() != self.sha256
        ):
            raise BoundArtifactError(
                f"{self.label} changed after its exact byte snapshot was bound"
            )


def _discard_snapshot(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def bind_file(
    raw_path: str | Path,
    *,
    label: str,
    trackable: bool = True,
) -> BoundArtifact:
    """Read a repository file once and bind path identity, bytes, and digest."""

    try:
        if trackable:
            resolved, relative = require_trackable_path(raw_path, label=label)
        else:
            resolved, relative = canonical_repo_relative(raw_path, label=label)
            if not resolved.is_file():
                raise ReleasePathError(f"{label} does not exist as a file: {relative}")
        with resolved.open("rb") as handle:
            before = os.fstat(handle.fileno())
            in_memory = before.st_size <= MEMORY_SNAPSHOT_LIMIT
            data_buffer = bytearray() if in_memory else None
            snapshot_path: Path | None = None
            snapshot_handle: BinaryIO | None = None
            if not in_memory:
                descriptor, snapshot_name = tempfile.mkstemp(
                    prefix="artifact-", suffix=".snapshot", dir=_snapshot_root()
                )
                snapshot_path = Path(snapshot_name)
                snapshot_handle = os.fdopen(descriptor, "wb")
            digest = hashlib.sha256()
            bytes_read = 0
            try:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                    bytes_read += len(chunk)
                    if data_buffer is not None:
                        data_buffer.extend(chunk)
                    else:
                        assert snapshot_handle is not None
                        snapshot_handle.write(chunk)
            finally:
                if snapshot_handle is not None:
                    snapshot_handle.close()
            after = os.fstat(handle.fileno())
        current = os.stat(resolved, follow_symlinks=False)
    except (OSError, ReleasePathError) as exc:
        if "snapshot_path" in locals() and snapshot_path is not None:
            _discard_snapshot(snapshot_path)
        raise BoundArtifactError(f"cannot bind {label}: {exc}") from exc
    if (
        _stat_signature(before) != _stat_signature(after)
        or _stat_signature(after) != _stat_signature(current)
        or bytes_read != after.st_size
    ):
        if snapshot_path is not None:
            _discard_snapshot(snapshot_path)
        raise BoundArtifactError(f"{label} changed while it was being bound")
    bound = BoundArtifact(
        label=label,
        path=resolved,
        relative=relative,
        _data=bytes(data_buffer) if data_buffer is not None else None,
        snapshot_path=snapshot_path,
        snapshot_signature=(
            _stat_signature(os.stat(snapshot_path, follow_symlinks=False))
            if snapshot_path is not None
            else None
        ),
        sha256=digest.hexdigest(),
        signature=_stat_signature(after),
        trackable=trackable,
    )
    if snapshot_path is not None:
        object.__setattr__(
            bound,
            "_finalizer",
            weakref.finalize(bound, _discard_snapshot, snapshot_path),
        )
    return bound


def bind_hashed_spec(
    spec: Any,
    *,
    label: str,
    resolver: Callable[[str, str], BoundArtifact] | None = None,
) -> BoundArtifact:
    if not isinstance(spec, dict):
        raise BoundArtifactError(f"{label} must be an object with path and sha256")
    raw_path = spec.get("path")
    if not isinstance(raw_path, str):
        raise BoundArtifactError(f"{label}.path must be a string")
    expected = spec.get("sha256")
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected.lower())
    ):
        raise BoundArtifactError(f"{label}.sha256 must be a 64-character digest")
    bound = (
        resolver(raw_path, f"{label}.path")
        if resolver is not None
        else bind_file(raw_path, label=f"{label}.path", trackable=True)
    )
    if bound.sha256 != expected.lower():
        raise BoundArtifactError(
            f"{label}.sha256 mismatch: index={expected.lower()}, actual={bound.sha256}"
        )
    return bound


def merge_bindings(
    bindings: Iterable[BoundArtifact],
) -> dict[str, BoundArtifact]:
    result: dict[str, BoundArtifact] = {}
    for bound in bindings:
        existing = result.get(bound.identity)
        if existing is not None and existing.sha256 != bound.sha256:
            raise BoundArtifactError(
                f"artifact was bound to conflicting bytes: {bound.relative}"
            )
        result[bound.identity] = bound
    return result


def assert_bindings_unchanged(bindings: Iterable[BoundArtifact]) -> None:
    seen: set[str] = set()
    for bound in bindings:
        if bound.identity in seen:
            continue
        seen.add(bound.identity)
        bound.assert_unchanged()
