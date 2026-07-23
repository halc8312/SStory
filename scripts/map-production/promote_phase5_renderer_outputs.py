#!/usr/bin/env python3
"""Safely promote reviewed Phase 5 renderer output into tracked masters.

The renderer is required to write below the ignored
``tmp/map-production/phase5-reviewed-v2`` tree.  This command fully prepares,
rewrites, re-hashes, and validates a copy before one directory rename installs
it below ``world/map-production/masters``.  It never edits source indexes,
manifest state, or QA decisions.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator, Sequence

from production_common import REPO_ROOT
from release_bound_artifact import (
    BoundArtifact,
    BoundArtifactError,
    assert_bindings_unchanged,
    bind_file,
    path_identity,
)
from release_path_safety import (
    ReleasePathError,
    assert_no_reparse_components,
    canonical_repo_relative,
    require_trackable_path,
    same_path,
)


PROMOTER_ID = "sstory-map-production/promote_phase5_renderer_outputs.py@2"
RENDERER_TMP_ROOT = REPO_ROOT / "tmp" / "map-production" / "phase5-reviewed-v2"
TRACKED_MASTER_ROOT = REPO_ROOT / "world" / "map-production" / "masters"


class RendererPromotionError(RuntimeError):
    """Raised when renderer output cannot be promoted without ambiguity."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_path(path: Path, label: str) -> str:
    try:
        _, relative = canonical_repo_relative(path, label=label)
    except ReleasePathError as exc:
        raise RendererPromotionError(str(exc)) from exc
    return relative


def _case_key(value: str) -> str:
    return value.casefold() if os.name == "nt" else value


def _relative_suffix(value: str, prefix: str) -> str | None:
    """Return a child suffix using Windows-case-insensitive path semantics."""

    value_key = _case_key(value)
    prefix_key = _case_key(prefix)
    if value_key == prefix_key:
        return ""
    marker = prefix_key + "/"
    if value_key.startswith(marker):
        return value[len(prefix) + 1 :]
    return None


def _require_descendant(path: Path, root: Path, label: str) -> Path:
    try:
        resolved, _ = require_trackable_path(
            path,
            label=label,
            must_exist=False,
            require_file=False,
        )
        root_resolved, _ = canonical_repo_relative(root, label="allowed root")
    except ReleasePathError as exc:
        raise RendererPromotionError(str(exc)) from exc
    try:
        common = os.path.commonpath((os.fspath(root_resolved), os.fspath(resolved)))
    except ValueError as exc:
        raise RendererPromotionError(
            f"{label} must stay below {_repo_path(root, 'allowed root')}"
        ) from exc
    if os.path.normcase(common) != os.path.normcase(os.fspath(root_resolved)):
        raise RendererPromotionError(
            f"{label} must stay below {_repo_path(root, 'allowed root')}"
        )
    if same_path(resolved, root_resolved):
        raise RendererPromotionError(
            f"{label} must be a versioned child of {_repo_path(root, 'allowed root')}"
        )
    return resolved


def _validate_source_root(source_root: Path) -> Path:
    try:
        resolved, _ = canonical_repo_relative(source_root, label="renderer source")
        allowed, _ = canonical_repo_relative(
            RENDERER_TMP_ROOT, label="renderer tmp root"
        )
    except ReleasePathError as exc:
        raise RendererPromotionError(str(exc)) from exc
    try:
        common = os.path.commonpath((os.fspath(allowed), os.fspath(resolved)))
    except ValueError as exc:
        raise RendererPromotionError(
            "source must be the reviewed renderer tmp root or one of its children"
        ) from exc
    if os.path.normcase(common) != os.path.normcase(os.fspath(allowed)):
        raise RendererPromotionError(
            "source must be the reviewed renderer tmp root or one of its children: "
            f"{_repo_path(RENDERER_TMP_ROOT, 'renderer tmp root')}"
        )
    if not resolved.is_dir():
        raise RendererPromotionError(
            f"renderer source directory is missing: {source_root}"
        )
    return resolved


def _validate_tree(root: Path, label: str) -> list[Path]:
    """Walk without following symlinks, junctions, or any reparse point."""

    files: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(
                os.scandir(directory), key=lambda item: item.name.casefold()
            )
        except OSError as exc:
            raise RendererPromotionError(
                f"cannot inspect {label}: {directory}: {exc}"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root)
            folded_parts = tuple(part.casefold() for part in relative.parts)
            if ".git" in folded_parts or ".gitignore" in folded_parts:
                raise RendererPromotionError(
                    f"{label} contains a forbidden Git control entry: "
                    f"{relative.as_posix()}"
                )
            try:
                assert_no_reparse_components(path, label=label)
            except ReleasePathError as exc:
                raise RendererPromotionError(str(exc)) from exc
            if entry.is_file(follow_symlinks=False):
                files.append(path)
            elif entry.is_dir(follow_symlinks=False):
                pending.append(path)
            else:
                raise RendererPromotionError(
                    f"{label} contains an unsupported filesystem entry: "
                    f"{path.relative_to(root)}"
                )
    files.sort(key=lambda item: item.relative_to(root).as_posix().casefold())
    if not files:
        raise RendererPromotionError(f"{label} contains no files: {root}")
    return files


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RendererPromotionError(
            f"{label} is not valid UTF-8 JSON: {path}: {exc}"
        ) from exc


def _load_bound_json(bound: BoundArtifact, label: str) -> Any:
    try:
        return bound.json_value()
    except BoundArtifactError as exc:
        raise RendererPromotionError(f"{label}: {exc}") from exc


def _stable_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _rewrite_exact_prefix(
    value: Any,
    source_prefix: str,
    target_prefix: str,
    canonical_suffixes: dict[str, str] | None = None,
) -> tuple[Any, int]:
    """Rewrite exact repo-path prefixes in both JSON values and object keys."""

    if isinstance(value, str):
        suffix = _relative_suffix(value, source_prefix)
        if suffix is None:
            return value, 0
        if canonical_suffixes is not None:
            suffix = canonical_suffixes.get(_case_key(suffix), suffix)
        return (
            target_prefix if not suffix else f"{target_prefix}/{suffix}",
            1,
        )
    if isinstance(value, list):
        rewritten: list[Any] = []
        count = 0
        for item in value:
            next_item, item_count = _rewrite_exact_prefix(
                item, source_prefix, target_prefix, canonical_suffixes
            )
            rewritten.append(next_item)
            count += item_count
        return rewritten, count
    if isinstance(value, dict):
        rewritten_object: dict[str, Any] = {}
        seen_keys: set[str] = set()
        count = 0
        for key, item in value.items():
            rewritten_key, key_count = _rewrite_exact_prefix(
                key, source_prefix, target_prefix, canonical_suffixes
            )
            assert isinstance(rewritten_key, str)
            collision_key = _case_key(rewritten_key)
            if collision_key in seen_keys:
                raise RendererPromotionError(
                    f"JSON key collision after canonical path rewrite: {rewritten_key!r}"
                )
            seen_keys.add(collision_key)
            next_item, item_count = _rewrite_exact_prefix(
                item, source_prefix, target_prefix, canonical_suffixes
            )
            rewritten_object[rewritten_key] = next_item
            count += key_count + item_count
        return rewritten_object, count
    return value, 0


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_strings(item)


def _is_repo_tmp_reference(value: str) -> bool:
    normalised = value.replace("\\", "/")
    folded = normalised.casefold() if os.name == "nt" else normalised
    return folded == "tmp" or folded.startswith("tmp/")


ResolvedArtifact = Path | BoundArtifact


def _resolved_path(value: ResolvedArtifact) -> Path:
    return value.path if isinstance(value, BoundArtifact) else value


def _resolved_sha256(value: ResolvedArtifact) -> str:
    return value.sha256 if isinstance(value, BoundArtifact) else sha256_file(value)


def _bind_renderer_source_files(source_files: Sequence[Path]) -> list[BoundArtifact]:
    bindings: list[BoundArtifact] = []
    try:
        for path in source_files:
            bindings.append(
                bind_file(path, label="renderer source artifact", trackable=False)
            )
    except BoundArtifactError as exc:
        raise RendererPromotionError(str(exc)) from exc
    return bindings


def _assert_renderer_snapshot_unchanged(
    source: Path,
    source_bindings: Sequence[BoundArtifact],
    external_bindings: Iterable[BoundArtifact],
) -> None:
    expected = sorted(
        binding.path.relative_to(source).as_posix() for binding in source_bindings
    )
    actual = sorted(
        path.relative_to(source).as_posix()
        for path in _validate_tree(source, "renderer source")
    )
    if actual != expected:
        raise RendererPromotionError(
            "renderer source tree membership changed after its exact snapshot was bound"
        )
    try:
        assert_bindings_unchanged((*source_bindings, *external_bindings))
    except BoundArtifactError as exc:
        raise RendererPromotionError(str(exc)) from exc


def _source_snapshot_resolver(
    source: Path,
    source_bindings: Sequence[BoundArtifact],
    external_bindings: dict[str, BoundArtifact],
) -> Callable[[str, str], ResolvedArtifact]:
    source_by_identity = {binding.identity: binding for binding in source_bindings}
    source_root = source.resolve()

    def resolve(raw_path: str, label: str) -> ResolvedArtifact:
        try:
            resolved, _ = canonical_repo_relative(raw_path, label=label)
        except ReleasePathError as exc:
            raise RendererPromotionError(str(exc)) from exc
        identity = path_identity(resolved)
        bound = source_by_identity.get(identity)
        if bound is not None:
            return bound
        try:
            resolved.relative_to(source_root)
        except ValueError:
            pass
        else:
            raise RendererPromotionError(
                f"{label} is not present in the bound renderer source snapshot: "
                f"{raw_path}"
            )
        existing = external_bindings.get(identity)
        if existing is not None:
            return existing
        try:
            external = bind_file(resolved, label=label, trackable=True)
        except BoundArtifactError as exc:
            raise RendererPromotionError(str(exc)) from exc
        external_bindings[identity] = external
        return external

    return resolve


def _staged_resolver(
    destination_prefix: str,
    staging_root: Path,
    external_bindings: dict[str, BoundArtifact] | None = None,
) -> Callable[[str, str], ResolvedArtifact]:
    def resolve(raw_path: str, label: str) -> ResolvedArtifact:
        suffix = _relative_suffix(raw_path, destination_prefix)
        if suffix is not None:
            if not suffix:
                raise RendererPromotionError(f"{label} names a directory, not a file")
            portable = PurePosixPath(suffix)
            if any(part in {"", ".", ".."} for part in portable.parts):
                raise RendererPromotionError(f"{label} escapes the promoted tree")
            candidate = staging_root.joinpath(*portable.parts)
            try:
                assert_no_reparse_components(candidate, label=label)
            except ReleasePathError as exc:
                raise RendererPromotionError(str(exc)) from exc
            if not candidate.is_file():
                raise RendererPromotionError(
                    f"{label} does not exist in the staged promotion: {raw_path}"
                )
            return candidate
        try:
            resolved, _ = require_trackable_path(raw_path, label=label)
        except ReleasePathError as exc:
            raise RendererPromotionError(str(exc)) from exc
        if external_bindings is None:
            return resolved
        bound = external_bindings.get(path_identity(resolved))
        if bound is None:
            raise RendererPromotionError(
                f"{label} was not present in the initial external artifact snapshot"
            )
        return bound

    return resolve


def _path_hash_pairs(value: Any, location: str = "$") -> Iterable[tuple[str, str, str]]:
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _path_hash_pairs(item, f"{location}[{index}]")
        return
    if not isinstance(value, dict):
        return
    for key, raw_path in value.items():
        if not isinstance(raw_path, str):
            continue
        hash_key: str | None = None
        if key == "path" and "sha256" in value:
            hash_key = "sha256"
        elif key.endswith("_path"):
            candidate = key[: -len("_path")] + "_sha256"
            if candidate in value:
                hash_key = candidate
        if hash_key is not None:
            digest = value.get(hash_key)
            if not isinstance(digest, str):
                raise RendererPromotionError(
                    f"{location}.{hash_key} must be a SHA-256 string"
                )
            yield raw_path, digest, f"{location}.{key}"
    for key, item in value.items():
        yield from _path_hash_pairs(item, f"{location}.{key}")


def _path_field_values(value: Any, location: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _path_field_values(item, f"{location}[{index}]")
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if isinstance(item, str):
            folded = key.casefold()
            if folded == "path" or folded.endswith("_path"):
                yield item, f"{location}.{key}"
        yield from _path_field_values(item, f"{location}.{key}")


def _verify_all_path_fields(
    value: Any,
    label: str,
    *,
    resolver: Callable[[str, str], ResolvedArtifact],
) -> None:
    for raw_path, location in _path_field_values(value):
        resolver(raw_path, f"{label} {location}")


def _verify_json_hash_references(
    value: Any,
    label: str,
    *,
    resolver: Callable[[str, str], ResolvedArtifact],
) -> None:
    for raw_path, expected, location in _path_hash_pairs(value):
        if len(expected) != 64 or any(
            character not in "0123456789abcdef" for character in expected
        ):
            raise RendererPromotionError(
                f"{label} {location} has an invalid lowercase SHA-256 digest"
            )
        resolved = resolver(raw_path, f"{label} {location}")
        actual = _resolved_sha256(resolved)
        if actual != expected:
            raise RendererPromotionError(
                f"{label} {location} hash mismatch: record={expected}, actual={actual}"
            )


def _refresh_hash_pairs(
    value: Any,
    *,
    document_path: Path,
    resolver: Callable[[str, str], ResolvedArtifact],
    location: str = "$",
) -> bool:
    changed = False
    if isinstance(value, list):
        for index, item in enumerate(value):
            changed |= _refresh_hash_pairs(
                item,
                document_path=document_path,
                resolver=resolver,
                location=f"{location}[{index}]",
            )
        return changed
    if not isinstance(value, dict):
        return False
    for key, raw_path in list(value.items()):
        if not isinstance(raw_path, str):
            continue
        hash_key: str | None = None
        if key == "path" and "sha256" in value:
            hash_key = "sha256"
        elif key.endswith("_path"):
            candidate = key[: -len("_path")] + "_sha256"
            if candidate in value:
                hash_key = candidate
        if hash_key is None:
            continue
        target = resolver(raw_path, f"{location}.{key}")
        if same_path(_resolved_path(target), document_path):
            raise RendererPromotionError(
                f"{location}.{key} forms an impossible self-hash reference"
            )
        actual = _resolved_sha256(target)
        if value.get(hash_key) != actual:
            value[hash_key] = actual
            changed = True
    for key, item in value.items():
        changed |= _refresh_hash_pairs(
            item,
            document_path=document_path,
            resolver=resolver,
            location=f"{location}.{key}",
        )
    return changed


def _refresh_json_tree(
    json_paths: Sequence[Path],
    *,
    resolver: Callable[[str, str], ResolvedArtifact],
) -> None:
    maximum_passes = len(json_paths) + 2
    for _ in range(maximum_passes):
        changed_any = False
        for path in json_paths:
            value = _load_json(path, "promoted JSON")
            changed = _refresh_hash_pairs(value, document_path=path, resolver=resolver)
            payload = _stable_json_bytes(value)
            if changed or path.read_bytes() != payload:
                path.write_bytes(payload)
                changed_any = True
        if not changed_any:
            return
    raise RendererPromotionError(
        "JSON hash references did not converge; cyclic report hashes are forbidden"
    )


def _tree_hashes(root: Path) -> dict[str, str]:
    files = _validate_tree(root, "promotion tree")
    return {path.relative_to(root).as_posix(): sha256_file(path) for path in files}


def _rename_directory_no_replace(source: Path, destination: Path) -> None:
    """Atomically rename a directory while refusing every existing target."""

    if os.name == "nt":
        # Windows MoveFileEx semantics used by os.rename are no-replace.
        os.rename(source, destination)
        return
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise RendererPromotionError(
                "atomic no-replace directory rename is unavailable on this Linux runtime"
            )
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100,  # AT_FDCWD
            os.fsencode(source),
            -100,
            os.fsencode(destination),
            1,  # RENAME_NOREPLACE
        )
        if result == 0:
            return
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(error_number, os.strerror(error_number), destination)
        raise OSError(error_number, os.strerror(error_number), destination)
    raise RendererPromotionError(
        "atomic no-replace directory rename is unsupported on this platform"
    )


def _atomic_force_supported() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        return getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None) is not None
    except OSError:
        return False


def _exchange_directories(source: Path, destination: Path) -> None:
    """Atomically exchange two existing directories or fail closed."""

    if not _atomic_force_supported():
        raise RendererPromotionError(
            "--force requires atomic directory exchange; this platform/runtime "
            "does not provide it"
        )
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = libc.renameat2
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        2,  # RENAME_EXCHANGE
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    raise RendererPromotionError(
        "atomic directory exchange failed: "
        f"{os.strerror(error_number)} ({error_number})"
    )


def _filesystem_identity(path: Path) -> tuple[int, int]:
    metadata = os.stat(path, follow_symlinks=False)
    return metadata.st_dev, metadata.st_ino


@contextmanager
def _exclusive_destination_lock(destination: Path) -> Iterator[None]:
    lock_path = destination.with_name(f".{destination.name}.promotion.lock")
    descriptor: int | None = None
    lock_created = False
    try:
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise RendererPromotionError(
                f"another promotion owns the destination lock: {lock_path}"
            ) from exc
        lock_created = True
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if lock_created:
            lock_path.unlink(missing_ok=True)


def _promotion_transaction_debris(destination: Path) -> list[Path]:
    """Find debris from every transaction owner, not only this process."""

    prefixes = tuple(
        f".{destination.name}{suffix}".casefold()
        for suffix in (
            ".promoting-",
            ".promotion-backup-",
            ".promotion-retired-",
            ".promotion-rollback-",
        )
    )
    try:
        entries = os.scandir(destination.parent)
    except OSError as exc:
        raise RendererPromotionError(
            f"cannot inspect promotion transaction directory: {destination.parent}: {exc}"
        ) from exc
    with entries:
        return sorted(
            (
                Path(entry.path)
                for entry in entries
                if entry.name.casefold().startswith(prefixes)
            ),
            key=lambda path: path.name.casefold(),
        )


def _prepare_promotion(
    source: Path,
    destination: Path,
    source_bindings: Sequence[BoundArtifact],
    external_bindings: dict[str, BoundArtifact],
) -> tuple[Path, dict[str, str], int, int]:
    """Prepare and validate complete final bytes without exposing destination."""

    source_prefix = _repo_path(source, "renderer source")
    destination_prefix = _repo_path(destination, "destination")
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.promoting-", dir=destination.parent
        )
    )
    rewrite_count = 0
    rewritten_json_count = 0
    canonical_suffixes = {"": ""}
    for source_binding in source_bindings:
        relative = source_binding.path.relative_to(source)
        canonical_suffixes[_case_key(relative.as_posix())] = relative.as_posix()
        for parent in relative.parents:
            if parent != Path("."):
                canonical_suffixes[_case_key(parent.as_posix())] = parent.as_posix()
    try:
        for source_binding in source_bindings:
            source_path = source_binding.path
            relative = source_path.relative_to(source)
            expected_final = destination / relative
            try:
                require_trackable_path(
                    expected_final,
                    label=f"promoted artifact {relative.as_posix()}",
                    must_exist=False,
                )
            except ReleasePathError as exc:
                raise RendererPromotionError(str(exc)) from exc
            target_path = staging / relative
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if source_path.suffix.casefold() == ".json":
                value = _load_bound_json(source_binding, "renderer JSON")
                rewritten, count = _rewrite_exact_prefix(
                    value,
                    source_prefix,
                    destination_prefix,
                    canonical_suffixes,
                )
                rewrite_count += count
                rewritten_json_count += int(count > 0)
                target_path.write_bytes(_stable_json_bytes(rewritten))
            else:
                source_binding.copy_to(target_path)

        json_paths = sorted(
            (
                path
                for path in staging.rglob("*")
                if path.is_file() and path.suffix.casefold() == ".json"
            ),
            key=lambda item: item.relative_to(staging).as_posix().casefold(),
        )
        resolver = _staged_resolver(destination_prefix, staging, external_bindings)
        _refresh_json_tree(json_paths, resolver=resolver)
        for path in json_paths:
            value = _load_json(path, "promoted JSON")
            remaining = sorted(
                {item for item in _walk_strings(value) if _is_repo_tmp_reference(item)},
                key=str.casefold,
            )
            if remaining:
                raise RendererPromotionError(
                    "promoted JSON retains tmp references in "
                    f"{path.relative_to(staging).as_posix()}: {remaining}"
                )
            _verify_json_hash_references(
                value,
                f"promoted JSON {path.relative_to(staging).as_posix()}",
                resolver=resolver,
            )
            _verify_all_path_fields(
                value,
                f"promoted JSON {path.relative_to(staging).as_posix()}",
                resolver=resolver,
            )
        hashes = _tree_hashes(staging)
        if len(hashes) != len(source_bindings):
            raise RendererPromotionError(
                "promoted file count differs from the renderer source tree"
            )
        return staging, hashes, rewrite_count, rewritten_json_count
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def promote_renderer_outputs(
    source_root: Path,
    destination_root: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    source = _validate_source_root(source_root)
    destination = _require_descendant(
        destination_root, TRACKED_MASTER_ROOT, "destination"
    )
    source_files = _validate_tree(source, "renderer source")
    source_bindings = _bind_renderer_source_files(source_files)
    external_bindings: dict[str, BoundArtifact] = {}
    initial_resolver = _source_snapshot_resolver(
        source, source_bindings, external_bindings
    )

    # Source reports must be internally sound before any repair/rewrite.  Tmp
    # references are allowed here only because this is the renderer scratch tree.
    for source_binding in (
        binding
        for binding in source_bindings
        if binding.path.suffix.casefold() == ".json"
    ):
        value = _load_bound_json(source_binding, "renderer JSON")
        _verify_json_hash_references(
            value,
            f"renderer JSON {source_binding.path.relative_to(source).as_posix()}",
            resolver=initial_resolver,
        )
        _verify_all_path_fields(
            value,
            f"renderer JSON {source_binding.path.relative_to(source).as_posix()}",
            resolver=initial_resolver,
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_destination_lock(destination):
        debris = _promotion_transaction_debris(destination)
        if debris:
            raise RendererPromotionError(
                "stale promotion backup or transaction debris exists: "
                + ", ".join(str(path) for path in debris)
            )
        if destination.exists() and not destination.is_dir():
            raise RendererPromotionError(
                f"renderer promotion destination must be a directory: {destination}"
            )
        if destination.exists() and not force:
            raise RendererPromotionError(
                f"refusing to overwrite immutable renderer promotion: {destination}"
            )
        if destination.exists() and force and not _atomic_force_supported():
            raise RendererPromotionError(
                "--force requires atomic directory exchange; this platform/runtime "
                "does not provide it"
            )

        staging, prepared_hashes, rewrite_count, rewritten_json_count = (
            _prepare_promotion(
                source,
                destination,
                source_bindings,
                external_bindings,
            )
        )
        _assert_renderer_snapshot_unchanged(
            source, source_bindings, external_bindings.values()
        )
        prepared_identity = _filesystem_identity(staging)
        replacement = False
        exchange_attempted = False
        installed = False
        install_attempted = False
        committed = False
        preserve_staging = False
        try:
            if destination.exists():
                if not force:
                    raise RendererPromotionError(
                        "destination appeared during no-clobber promotion; refusing to replace it"
                    )
                replacement = True
                exchange_attempted = True
                _exchange_directories(staging, destination)
            else:
                install_attempted = True
                try:
                    _rename_directory_no_replace(staging, destination)
                except FileExistsError as exc:
                    raise RendererPromotionError(
                        "destination appeared during atomic no-clobber promotion"
                    ) from exc
            installed = True
            installed_hashes = _tree_hashes(destination)
            if installed_hashes != prepared_hashes:
                raise RendererPromotionError(
                    "installed promotion bytes differ from the fully validated staging tree"
                )
            _assert_renderer_snapshot_unchanged(
                source, source_bindings, external_bindings.values()
            )
            destination_prefix = _repo_path(destination, "destination")
            result = {
                "valid": True,
                "committed": True,
                "promoted_by": PROMOTER_ID,
                "source": _repo_path(source, "renderer source"),
                "destination": destination_prefix,
                "file_count": len(installed_hashes),
                "json_file_count": sum(
                    relative.casefold().endswith(".json")
                    for relative in installed_hashes
                ),
                "rewritten_json_file_count": rewritten_json_count,
                "path_rewrite_count": rewrite_count,
                "artifacts": [
                    {
                        "path": f"{destination_prefix}/{relative}",
                        "sha256": digest,
                    }
                    for relative, digest in installed_hashes.items()
                ],
                "cleanup": {"complete": True},
            }
            committed = True
            if replacement and os.path.lexists(staging):
                try:
                    shutil.rmtree(staging)
                except BaseException as cleanup_error:
                    preserve_staging = True
                    result["cleanup"] = {
                        "complete": False,
                        "path": _repo_path(staging, "committed cleanup debris"),
                        "error": str(cleanup_error),
                    }
            return result
        except BaseException as original_error:
            if committed:
                # Post-commit cleanup is handled above and reported as a
                # committed success.  No validation may reach this branch.
                return result
            if not installed and os.path.lexists(destination):
                try:
                    destination_is_prepared = (
                        _filesystem_identity(destination) == prepared_identity
                    )
                except OSError:
                    destination_is_prepared = False
                if (
                    exchange_attempted or install_attempted
                ) and destination_is_prepared:
                    installed = True
            try:
                if replacement and installed:
                    # The old destination has remained continuously available
                    # at ``staging``.  Exchange restores it with no gap.
                    _exchange_directories(staging, destination)
                    installed = False
                elif installed and os.path.lexists(destination):
                    _rename_directory_no_replace(destination, staging)
                    installed = False
            except BaseException as rollback_error:
                recovery_paths = [
                    path for path in (destination, staging) if os.path.lexists(path)
                ]
                raise RendererPromotionError(
                    "promotion failed and automatic rollback could not complete; "
                    "recovery state remains at "
                    f"{', '.join(str(path) for path in recovery_paths)}: "
                    f"{rollback_error}"
                ) from original_error
            raise
        finally:
            if staging.exists() and not preserve_staging:
                shutil.rmtree(staging, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        type=Path,
        help=("renderer output directory below tmp/map-production/phase5-reviewed-v2"),
    )
    parser.add_argument(
        "destination",
        type=Path,
        help="versioned tracked directory below world/map-production/masters",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="explicitly replace an existing destination with rollback protection",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = promote_renderer_outputs(
            args.source,
            args.destination,
            force=args.force,
        )
    except (OSError, ValueError, RendererPromotionError) as exc:
        result = {"valid": False, "error": str(exc)}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result.get("valid"):
        print(
            "Phase 5 renderer promotion created: "
            f"{result['destination']} ({result['file_count']} files)"
        )
        for artifact in result["artifacts"]:
            print(f"  {artifact['sha256']}  {artifact['path']}")
    else:
        print(f"Phase 5 renderer promotion failed: {result['error']}", file=sys.stderr)
    return 0 if result.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
