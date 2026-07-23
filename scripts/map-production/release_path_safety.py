#!/usr/bin/env python3
"""Fail-closed path checks shared by immutable map release tooling."""

from __future__ import annotations

import hashlib
import ntpath
import os
import stat
import subprocess
from functools import lru_cache
from pathlib import Path, PurePosixPath

from production_common import REPO_ROOT


VOLATILE_ROOT_NAMES = frozenset(
    {
        ".playwright-cli",
        "build",
        "develop-eggs",
        "dist",
        "node_modules",
        "output",
    }
)
VOLATILE_MAP_PRODUCTION_NAMES = frozenset({"build", "builds", "output", "tmp"})


class ReleasePathError(RuntimeError):
    """Raised when a release artifact is not a canonical trackable repo path."""


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def same_path(first: Path, second: Path) -> bool:
    return _path_key(first) == _path_key(second)


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode) or path.is_symlink():
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if attributes & reparse_flag:
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def assert_no_reparse_components(path: Path, *, label: str) -> None:
    """Reject symlinks, junctions, and other reparse points through repo root."""

    root = Path(os.path.abspath(REPO_ROOT))
    candidate = Path(os.path.abspath(path))
    try:
        common = os.path.commonpath((os.fspath(root), os.fspath(candidate)))
    except ValueError as exc:
        raise ReleasePathError(f"{label} is outside the repository: {path}") from exc
    if os.path.normcase(common) != os.path.normcase(os.fspath(root)):
        raise ReleasePathError(f"{label} is outside the repository: {path}")

    current = candidate
    while True:
        if current.exists() or os.path.lexists(current):
            if _is_reparse_point(current):
                raise ReleasePathError(
                    f"{label} traverses a symlink, junction, or reparse point: {current}"
                )
        if same_path(current, root):
            return
        parent = current.parent
        if same_path(parent, current):
            raise ReleasePathError(f"{label} is outside the repository: {path}")
        current = parent


def canonical_repo_relative(raw_path: str | Path, *, label: str) -> tuple[Path, str]:
    """Return a canonical physical path and repo-relative POSIX spelling."""

    raw_text = os.fspath(raw_path)
    if "\x00" in raw_text:
        raise ReleasePathError(f"{label} contains a NUL byte")
    windows_drive, windows_tail = ntpath.splitdrive(raw_text)
    if windows_drive and not ntpath.isabs(raw_text):
        raise ReleasePathError(
            f"{label} may not use a Windows drive-relative path: {raw_text!r}"
        )
    # A colon is valid only as the separator in an absolute Windows drive
    # prefix.  Every colon in the remaining path denotes an NTFS alternate
    # data stream (or an ambiguous cross-platform spelling), neither of which
    # can be a release artifact.
    if ":" in windows_tail:
        raise ReleasePathError(
            f"{label} may not use an NTFS alternate data stream: {raw_text!r}"
        )

    if isinstance(raw_path, Path):
        candidate = raw_path if raw_path.is_absolute() else REPO_ROOT / raw_path
    elif isinstance(raw_path, str):
        if not raw_path or "\\" in raw_path:
            raise ReleasePathError(f"{label} must be a repository-relative POSIX path")
        lexical_parts = raw_path.split("/")
        portable = PurePosixPath(raw_path)
        if portable.is_absolute() or any(
            part in {"", ".", ".."} for part in lexical_parts
        ):
            raise ReleasePathError(f"{label} escapes the repository: {raw_path!r}")
        if portable.parts and portable.parts[0].endswith(":"):
            raise ReleasePathError(f"{label} escapes the repository: {raw_path!r}")
        candidate = REPO_ROOT.joinpath(*portable.parts)
    else:
        raise ReleasePathError(f"{label} must be a path")

    lexical = Path(os.path.abspath(candidate))
    assert_no_reparse_components(lexical, label=label)
    resolved = lexical.resolve(strict=False)
    root = REPO_ROOT.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        # ``relative_to`` on unusual Windows path spellings can be stricter
        # than the filesystem; accept only an equivalent normcase containment.
        try:
            common = os.path.commonpath((os.fspath(root), os.fspath(resolved)))
        except ValueError:
            common = ""
        if os.path.normcase(common) != os.path.normcase(os.fspath(root)):
            raise ReleasePathError(
                f"{label} must stay inside the repository: {raw_path}"
            ) from exc
        relative = Path(os.path.relpath(resolved, root))
    if relative == Path("."):
        return resolved, "."
    relative_posix = relative.as_posix()
    if ".git" in (part.casefold() for part in relative.parts):
        raise ReleasePathError(
            f"{label} may not enter the repository Git control directory: "
            f"{relative_posix}"
        )
    return resolved, relative_posix


def _reject_volatile_namespace(relative: str, label: str) -> None:
    parts = [part.casefold() for part in PurePosixPath(relative).parts]
    if not parts:
        raise ReleasePathError(f"{label} has no repository-relative path")
    if ".git" in parts:
        raise ReleasePathError(
            f"{label} may not enter the repository Git control directory: {relative}"
        )
    if parts[0].startswith("tmp") or parts[0] in VOLATILE_ROOT_NAMES:
        raise ReleasePathError(
            f"{label} is in a volatile or ignored repository namespace: {relative}"
        )
    volatile_components = {"build", "builds", "output", "tmp"}
    directory_parts = parts[:-1]
    if any(
        part in volatile_components
        or part.startswith("tmp-")
        or part.startswith("tmp_")
        for part in directory_parts
    ):
        raise ReleasePathError(
            f"{label} is in a temporary/build-cache namespace: {relative}"
        )
    if (
        len(parts) >= 3
        and parts[:2] == ["world", "map-production"]
        and parts[2] in VOLATILE_MAP_PRODUCTION_NAMES
    ):
        raise ReleasePathError(f"{label} is in a map build cache namespace: {relative}")
    if "node_modules" in parts or ".playwright-cli" in parts:
        raise ReleasePathError(
            f"{label} is in an ignored dependency/cache namespace: {relative}"
        )


def _ignore_file_state(path: Path) -> tuple[str, str]:
    """Return a content-sensitive state for one possible Git ignore input."""

    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return os.fspath(path), "missing"
    except OSError as exc:
        return os.fspath(path), f"unreadable:{type(exc).__name__}:{exc.errno}"
    return os.fspath(path), hashlib.sha256(data).hexdigest()


def _git_ignore_state(relative: str) -> tuple[tuple[str, str], ...]:
    """Fingerprint every ignore file that can govern this repository path."""

    parts = PurePosixPath(relative).parts
    candidates = [REPO_ROOT / ".gitignore"]
    current = REPO_ROOT
    for part in parts[:-1]:
        current /= part
        candidates.append(current / ".gitignore")
    candidates.extend(
        (
            REPO_ROOT / ".git" / "info" / "exclude",
            REPO_ROOT / ".git" / "config",
            Path.home() / ".gitconfig",
            Path.home() / ".config" / "git" / "ignore",
            Path.home() / ".gitignore_global",
        )
    )
    return tuple(_ignore_file_state(path) for path in candidates)


@lru_cache(maxsize=8192)
def _git_ignore_result_for_state(
    relative: str, ignore_state: tuple[tuple[str, str], ...]
) -> tuple[int, str]:
    del ignore_state  # The cache key binds the subprocess result to this state.
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", "--", relative],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        return 127, str(exc)
    return result.returncode, result.stderr.strip()


def _git_ignore_result(relative: str) -> tuple[int, str]:
    return _git_ignore_result_for_state(relative, _git_ignore_state(relative))


def _git_ignored(relative: str, label: str) -> bool:
    returncode, stderr = _git_ignore_result(relative)
    if returncode == 127:
        raise ReleasePathError(
            f"{label} cannot be checked against Git ignore rules: {stderr}"
        )
    if returncode == 0:
        return True
    if returncode == 1:
        return False
    diagnostic = stderr or f"exit {returncode}"
    raise ReleasePathError(
        f"{label} cannot be checked against Git ignore rules: {diagnostic}"
    )


def require_trackable_path(
    raw_path: str | Path,
    *,
    label: str,
    must_exist: bool = True,
    require_file: bool = True,
) -> tuple[Path, str]:
    """Resolve a nonignored, nonvolatile, non-reparse repository artifact."""

    resolved, relative = canonical_repo_relative(raw_path, label=label)
    if relative == ".":
        raise ReleasePathError(f"{label} may not be the repository root")
    _reject_volatile_namespace(relative, label)
    if _git_ignored(relative, label):
        raise ReleasePathError(f"{label} is ignored by Git: {relative}")
    if must_exist:
        if require_file and not resolved.is_file():
            raise ReleasePathError(f"{label} does not exist as a file: {relative}")
        if not require_file and not resolved.exists():
            raise ReleasePathError(f"{label} does not exist: {relative}")
    return resolved, relative
