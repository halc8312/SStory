#!/usr/bin/env python3
"""Emit a deterministic TEMP-only exact-five Phase 5 vision review bundle.

The source binding linearizes at its final check immediately before the
anchored directory rename.  A successful transaction linearizes at the single
installed bundle snapshot after that rename; the success path performs no
further file read.  Failures preserve owned TEMP debris instead of recursively
deleting through a pathname whose parent identity might have changed.

On Linux, the already-existing output parent is a caller-provisioned trust
boundary: it must be owned by the effective user, mode 0700, and carry no POSIX
ACL.  Other processes running as that same credential are therefore inside the
trust boundary.  Windows does not need that contract because NtCreateFile
atomically creates the staging directory and returns its pinned handle.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import ntpath
import os
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, PngImagePlugin, UnidentifiedImageError

from production_common import REPO_ROOT
from release_bound_artifact import BoundArtifact, BoundArtifactError, bind_file
from release_path_safety import (
    ReleasePathError,
    require_trackable_path,
)


SCHEMA_VERSION = "1.0.0"
BUNDLE_TYPE = "sstory-phase5-root-vision-view-bundle"
VIEW_ORDER = ("native", "full25", "full50", "focus200", "focus400")
VIEW_FILENAMES = {view_id: f"{view_id}.png" for view_id in VIEW_ORDER}
RECEIPT_FILENAME = "receipt.json"
PNG_OPTIONS: dict[str, Any] = {
    "format": "PNG",
    "compress_level": 9,
    "optimize": False,
}
ROUNDING_RULE = "positive-integer-round-half-up-minimum-1"
INTERPOLATION = "Pillow.Image.Resampling.LANCZOS"


class Phase5VisionViewsError(RuntimeError):
    """Raised when the exact-five review-bundle contract cannot be met."""


class Phase5EvidenceIOError(Phase5VisionViewsError):
    """Raised when an OS-backed publication-evidence read fails."""


class Phase5ContentInvalidError(Phase5VisionViewsError):
    """Raised when stable bytes violate the bundle content contract."""


class PublicationState(str, Enum):
    PROVEN_UNCOMMITTED = "proven-uncommitted"
    COMMITTED = "committed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PhysicalIdentity:
    device: int
    inode: int
    file_type: int


@dataclass(frozen=True)
class PreparedParent:
    path: Path
    allowed_root: Path
    identity: PhysicalIdentity
    allowed_root_identity: PhysicalIdentity


@dataclass
class ParentAnchor:
    prepared: PreparedParent
    linux_fds: list[int]
    windows_handles: list[int]
    windows_identities: list[tuple[int, int]]

    @property
    def parent_fd(self) -> int | None:
        return self.linux_fds[-1] if self.linux_fds else None


@dataclass
class OwnedStaging:
    path: Path
    name: str
    rollback_name: str
    identity: PhysicalIdentity
    anchor: ParentAnchor
    directory_fd: int | None
    windows_handle: int | None
    name_owned: bool = True
    installed: bool = False
    publication_state: PublicationState = PublicationState.PROVEN_UNCOMMITTED


@dataclass(frozen=True)
class BundleSnapshot:
    tree_hashes: tuple[tuple[str, str], ...]
    pixel_hashes: tuple[tuple[str, str], ...]


@dataclass
class PinnedBundleEntry:
    name: str
    descriptor: int | None
    windows_handle: int | None
    handle_identity: tuple[int, int]
    handle_signature: tuple[int, ...]
    path_signature: tuple[int, int, int, int]


def _before_parent_anchor_open_hook(*, output: Path, parent: PreparedParent) -> None:
    """Race-test hook immediately before existing-parent anchor acquisition."""

    del output, parent


def _before_commit_validation_hook(
    *, source: BoundArtifact, staging: Path, output: Path
) -> None:
    """Race-test hook immediately before the closed commit-boundary checks."""

    del source, staging, output


def _before_anchored_rename_hook(
    *, source: BoundArtifact, staging: Path, output: Path, parent: PreparedParent
) -> None:
    """Race-test hook at the final parent-identity-to-rename boundary."""

    del source, staging, output, parent


def _before_rename_syscall_hook(
    *, staging: Path, source_name: str, destination_name: str
) -> None:
    """Race-test hook immediately before the guarded output rename syscall."""

    del staging, source_name, destination_name


def _staging_create_boundary_hook(*, staging: Path, atomic_handle: bool) -> None:
    """Race-test hook at the first observable post-mkdir/create boundary."""

    del staging, atomic_handle


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _stat_signature(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _read_stable_file(path: Path, *, label: str) -> bytes:
    if _is_reparse_point(path):
        raise Phase5VisionViewsError(f"{label} may not be a reparse point: {path}")
    try:
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            payload = stream.read()
            after = os.fstat(stream.fileno())
        current = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise Phase5VisionViewsError(f"cannot bind {label}: {path}: {exc}") from exc
    if (
        _stat_signature(before) != _stat_signature(after)
        or _stat_signature(after) != _stat_signature(current)
        or len(payload) != after.st_size
    ):
        raise Phase5VisionViewsError(f"{label} changed while its bytes were bound")
    return payload


def _stable_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=False,
        )
        + "\n"
    ).encode("utf-8")


def _validate_sha256(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value.lower())
    ):
        raise Phase5VisionViewsError(
            "--source-sha256 must be a 64-character SHA-256 digest"
        )
    return value.lower()


def _assert_git_tracked(relative: str) -> None:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise Phase5VisionViewsError(
            f"source tracking state cannot be checked: {exc}"
        ) from exc
    if result.returncode != 0:
        diagnostic = result.stderr.strip()
        if diagnostic:
            diagnostic = f" ({diagnostic})"
        raise Phase5VisionViewsError(
            f"source must already be tracked by Git: {relative}{diagnostic}"
        )


def _bind_source(
    source: str, expected_sha256: str
) -> tuple[BoundArtifact, Image.Image]:
    if not isinstance(source, str):
        raise Phase5VisionViewsError(
            "source must be a tracked repository-relative POSIX path"
        )
    try:
        resolved, relative = require_trackable_path(source, label="source")
    except ReleasePathError as exc:
        raise Phase5VisionViewsError(str(exc)) from exc
    if resolved.suffix.casefold() != ".png":
        raise Phase5VisionViewsError("source must have a .png filename extension")
    _assert_git_tracked(relative)
    try:
        bound = bind_file(relative, label="source", trackable=True)
    except BoundArtifactError as exc:
        raise Phase5VisionViewsError(str(exc)) from exc
    if bound.sha256 != expected_sha256:
        raise Phase5VisionViewsError(
            "source SHA-256 mismatch: "
            f"expected={expected_sha256}, actual={bound.sha256}"
        )
    try:
        with bound.open_binary() as stream, Image.open(stream) as opened:
            opened.load()
            if opened.format != "PNG":
                raise Phase5VisionViewsError("source bytes must encode a PNG image")
            if opened.mode != "RGB":
                raise Phase5VisionViewsError(
                    f"source PNG mode must be RGB, received {opened.mode}"
                )
            image = opened.copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise Phase5VisionViewsError(f"source is not a readable PNG: {exc}") from exc
    image.info.clear()
    return bound, image


def _validate_focus_box(
    focus_box: Sequence[int], source_size: tuple[int, int]
) -> tuple[int, int, int, int]:
    if len(focus_box) != 4 or any(
        isinstance(value, bool) or not isinstance(value, int) for value in focus_box
    ):
        raise Phase5VisionViewsError(
            "--focus-box requires exactly four integers in x0,y0,x1,y1 syntax"
        )
    x0, y0, x1, y1 = focus_box
    width, height = source_size
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise Phase5VisionViewsError(
            "--focus-box must be nonempty and fully inside the source image: "
            f"box={[x0, y0, x1, y1]}, source_size={[width, height]}"
        )
    return x0, y0, x1, y1


def _same_or_descendant(path: Path, root: Path) -> bool:
    try:
        common = os.path.commonpath((os.fspath(path), os.fspath(root)))
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(os.fspath(root))


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


def _assert_no_reparse_descendants(root: Path, target: Path) -> None:
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise Phase5VisionViewsError(
            f"output path escaped its approved TEMP root: {target}"
        ) from exc
    current = root
    if os.path.lexists(current) and _is_reparse_point(current):
        raise Phase5VisionViewsError(
            f"output TEMP root is a symlink, junction, or reparse point: {current}"
        )
    for part in relative.parts:
        current /= part
        if os.path.lexists(current) and _is_reparse_point(current):
            raise Phase5VisionViewsError(
                "output path traverses a symlink, junction, or reparse point: "
                f"{current}"
            )


def _validate_output_path(raw_output: str | Path) -> tuple[Path, Path]:
    raw_text = os.fspath(raw_output)
    if not raw_text or "\x00" in raw_text:
        raise Phase5VisionViewsError("output path is empty or contains a NUL byte")
    drive, _ = ntpath.splitdrive(raw_text)
    if drive and not ntpath.isabs(raw_text):
        raise Phase5VisionViewsError(
            f"output may not use a Windows drive-relative path: {raw_text!r}"
        )
    candidate = Path(raw_text)
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    lexical = Path(os.path.abspath(candidate))
    if os.path.lexists(lexical):
        raise Phase5VisionViewsError(f"output already exists: {lexical}")
    resolved = lexical.resolve(strict=False)
    allowed_roots = (
        (REPO_ROOT / "tmp").resolve(strict=False),
        Path(tempfile.gettempdir()).resolve(strict=False),
    )
    root = next(
        (
            allowed
            for allowed in allowed_roots
            if resolved != allowed and _same_or_descendant(resolved, allowed)
        ),
        None,
    )
    if root is None:
        raise Phase5VisionViewsError(
            "output must be a strict descendant of the repository tmp directory "
            "or the operating-system temp directory"
        )
    _assert_no_reparse_descendants(root, resolved.parent)
    return resolved, root


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(
        os.path.abspath(second)
    )


def _physical_directory_identity(path: Path, *, label: str) -> PhysicalIdentity:
    if not os.path.lexists(path):
        raise Phase5VisionViewsError(f"{label} disappeared: {path}")
    if _is_reparse_point(path):
        raise Phase5VisionViewsError(
            f"{label} is a symlink, junction, or reparse point: {path}"
        )
    try:
        resolved = path.resolve(strict=True)
        metadata = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise Phase5EvidenceIOError(f"cannot stat {label}: {path}: {exc}") from exc
    if not _same_path(resolved, path) or not stat.S_ISDIR(metadata.st_mode):
        raise Phase5VisionViewsError(
            f"{label} is not the expected physical directory: {path}"
        )
    return PhysicalIdentity(
        device=metadata.st_dev,
        inode=metadata.st_ino,
        file_type=stat.S_IFMT(metadata.st_mode),
    )


def _assert_prepared_parent(parent: PreparedParent) -> None:
    root_identity = _physical_directory_identity(
        parent.allowed_root, label="approved TEMP root"
    )
    if root_identity != parent.allowed_root_identity:
        raise Phase5VisionViewsError(
            "approved TEMP root physical identity changed during transaction"
        )
    if not _same_or_descendant(parent.path, parent.allowed_root):
        raise Phase5VisionViewsError(
            f"output parent escaped the approved TEMP root: {parent.path}"
        )
    _assert_no_reparse_descendants(parent.allowed_root, parent.path)
    identity = _physical_directory_identity(parent.path, label="output parent")
    if identity != parent.identity:
        raise Phase5VisionViewsError(
            "output parent physical identity changed during transaction"
        )


def _prepare_output_parent(output: Path, allowed_root: Path) -> PreparedParent:
    # Parent creation through an unanchored pathname is not part of this
    # transaction.  Callers must provision the parent first; until its handle
    # chain is anchored, even creating an otherwise harmless empty directory
    # could be redirected through a concurrent junction/symlink exchange.
    if not os.path.lexists(output.parent):
        raise Phase5VisionViewsError(
            f"output parent must already exist before the transaction: {output.parent}"
        )
    try:
        physical_parent = output.parent.resolve(strict=True)
    except OSError as exc:
        raise Phase5VisionViewsError(
            f"cannot resolve existing output parent: {output.parent}: {exc}"
        ) from exc
    if not _same_path(physical_parent, output.parent) or not _same_or_descendant(
        physical_parent, allowed_root
    ):
        raise Phase5VisionViewsError(
            f"output parent changed physical identity during preparation: {output.parent}"
        )
    _assert_no_reparse_descendants(allowed_root, physical_parent)
    prepared = PreparedParent(
        path=physical_parent,
        allowed_root=allowed_root,
        identity=_physical_directory_identity(physical_parent, label="output parent"),
        allowed_root_identity=_physical_directory_identity(
            allowed_root, label="approved TEMP root"
        ),
    )
    _assert_prepared_parent(prepared)
    if os.path.lexists(output):
        raise Phase5VisionViewsError(f"output already exists: {output}")
    return prepared


def _identity_from_stat(metadata: os.stat_result) -> PhysicalIdentity:
    return PhysicalIdentity(
        device=metadata.st_dev,
        inode=metadata.st_ino,
        file_type=stat.S_IFMT(metadata.st_mode),
    )


def _windows_open_directory(path: Path, *, delete_access: bool = False) -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    handle = create_file(
        os.fspath(path),
        0x0001 | (0x00010000 if delete_access else 0),
        # FILE_LIST_DIRECTORY | optional DELETE
        0x0001 | 0x0002,  # FILE_SHARE_READ | FILE_SHARE_WRITE; no DELETE share
        None,
        3,  # OPEN_EXISTING
        0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in {None, invalid}:
        error_number = ctypes.get_last_error()
        raise OSError(error_number, ctypes.FormatError(error_number), path)
    return int(handle)


class _WindowsUnicodeString(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ushort),
        ("maximum_length", ctypes.c_ushort),
        ("buffer", ctypes.c_void_p),
    ]


class _WindowsObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ulong),
        ("root_directory", ctypes.c_void_p),
        ("object_name", ctypes.POINTER(_WindowsUnicodeString)),
        ("attributes", ctypes.c_ulong),
        ("security_descriptor", ctypes.c_void_p),
        ("security_quality_of_service", ctypes.c_void_p),
    ]


class _WindowsIoStatusBlock(ctypes.Structure):
    _fields_ = [
        ("status_or_pointer", ctypes.c_void_p),
        ("information", ctypes.c_size_t),
    ]


def _windows_create_directory_handle(parent_handle: int, name: str) -> int:
    """Atomically create one directory and return its no-delete-share handle."""

    name_buffer = ctypes.create_unicode_buffer(name)
    encoded_length = len(name.encode("utf-16-le"))
    object_name = _WindowsUnicodeString(
        length=encoded_length,
        maximum_length=encoded_length + 2,
        buffer=ctypes.cast(name_buffer, ctypes.c_void_p),
    )
    object_attributes = _WindowsObjectAttributes(
        length=ctypes.sizeof(_WindowsObjectAttributes),
        root_directory=ctypes.c_void_p(parent_handle),
        object_name=ctypes.pointer(object_name),
        attributes=0x40,  # OBJ_CASE_INSENSITIVE
        security_descriptor=None,
        security_quality_of_service=None,
    )
    io_status = _WindowsIoStatusBlock()
    handle = ctypes.c_void_p()
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    create_file = ntdll.NtCreateFile
    create_file.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_ulong,
        ctypes.POINTER(_WindowsObjectAttributes),
        ctypes.POINTER(_WindowsIoStatusBlock),
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
    ]
    create_file.restype = ctypes.c_long
    status = create_file(
        ctypes.byref(handle),
        0x00110081,  # SYNCHRONIZE | DELETE | READ_ATTRIBUTES | LIST_DIRECTORY
        ctypes.byref(object_attributes),
        ctypes.byref(io_status),
        None,
        0x80,  # FILE_ATTRIBUTE_NORMAL
        0x0001 | 0x0002,  # FILE_SHARE_READ | FILE_SHARE_WRITE; no DELETE share
        2,  # FILE_CREATE: fail if the name already exists
        0x0001 | 0x0020 | 0x00200000,
        # FILE_DIRECTORY_FILE | SYNCHRONOUS_IO_NONALERT | OPEN_REPARSE_POINT
        None,
        0,
    )
    if status >= 0 and handle.value is not None:
        return int(handle.value)

    to_dos_error = ntdll.RtlNtStatusToDosError
    to_dos_error.argtypes = [ctypes.c_long]
    to_dos_error.restype = ctypes.c_ulong
    error_number = int(to_dos_error(status))
    if error_number in {80, 183}:  # ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS
        raise FileExistsError(error_number, ctypes.FormatError(error_number), name)
    raise OSError(error_number, ctypes.FormatError(error_number), name)


def _windows_close_handle(handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    if not close_handle(ctypes.c_void_p(handle)):
        error_number = ctypes.get_last_error()
        raise OSError(error_number, ctypes.FormatError(error_number))


class _WindowsFileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class _WindowsFileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", ctypes.c_uint32),
        ("creation_time", _WindowsFileTime),
        ("last_access_time", _WindowsFileTime),
        ("last_write_time", _WindowsFileTime),
        ("volume_serial", ctypes.c_uint32),
        ("file_size_high", ctypes.c_uint32),
        ("file_size_low", ctypes.c_uint32),
        ("link_count", ctypes.c_uint32),
        ("file_index_high", ctypes.c_uint32),
        ("file_index_low", ctypes.c_uint32),
    ]


def _windows_get_file_information(handle: int) -> _WindowsFileInformation:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_WindowsFileInformation),
    ]
    get_information.restype = ctypes.c_int
    information = _WindowsFileInformation()
    if not get_information(ctypes.c_void_p(handle), ctypes.byref(information)):
        error_number = ctypes.get_last_error()
        raise OSError(error_number, ctypes.FormatError(error_number))
    return information


def _windows_handle_identity(handle: int) -> tuple[int, int]:
    information = _windows_get_file_information(handle)
    inode = (information.file_index_high << 32) | information.file_index_low
    return information.volume_serial, inode


def _windows_file_signature(handle: int) -> tuple[int, ...]:
    information = _windows_get_file_information(handle)
    inode = (information.file_index_high << 32) | information.file_index_low
    size = (information.file_size_high << 32) | information.file_size_low
    last_write = (
        information.last_write_time.high << 32
    ) | information.last_write_time.low
    return (
        information.volume_serial,
        inode,
        information.attributes,
        size,
        last_write,
        information.link_count,
    )


def _windows_open_file_for_snapshot(path: Path) -> int:
    """Open one file for read while denying concurrent write/delete access."""

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    handle = create_file(
        os.fspath(path),
        0x80000000,  # GENERIC_READ
        0x0001,  # FILE_SHARE_READ only: deny write and delete while pinned
        None,
        3,  # OPEN_EXISTING
        0x00200000 | 0x08000000,
        # FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_SEQUENTIAL_SCAN
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in {None, invalid}:
        error_number = ctypes.get_last_error()
        raise OSError(error_number, ctypes.FormatError(error_number), path)
    return int(handle)


def _windows_read_file_handle(handle: int) -> bytes:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    read_file = kernel32.ReadFile
    read_file.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    read_file.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(1024 * 1024)
    chunks: list[bytes] = []
    while True:
        count = ctypes.c_uint32()
        if not read_file(
            ctypes.c_void_p(handle),
            buffer,
            len(buffer),
            ctypes.byref(count),
            None,
        ):
            error_number = ctypes.get_last_error()
            raise OSError(error_number, ctypes.FormatError(error_number))
        if count.value == 0:
            return b"".join(chunks)
        chunks.append(buffer.raw[: count.value])


class _WindowsFileRenameInfo(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("root_directory", ctypes.c_void_p),
        ("file_name_length", ctypes.c_uint32),
        ("file_name", ctypes.c_wchar * 1),
    ]


def _windows_rename_directory_handle_no_replace(handle: int, destination: Path) -> None:
    """Rename the exact open directory handle without replacing a target."""

    encoded_name = os.fspath(destination).encode("utf-16-le")
    filename_offset = _WindowsFileRenameInfo.file_name.offset
    # Keep the structure's declared WCHAR placeholder and trailing alignment
    # in the API buffer.  Using only ``FileName.offset + byte_length`` lets
    # Windows consume one uninitialised UTF-16 code unit on some builds.
    buffer = ctypes.create_string_buffer(
        ctypes.sizeof(_WindowsFileRenameInfo) + len(encoded_name)
    )
    information = _WindowsFileRenameInfo.from_buffer(buffer)
    information.flags = 0  # ReplaceIfExists = FALSE
    information.root_directory = None
    information.file_name_length = len(encoded_name)
    ctypes.memmove(
        ctypes.addressof(buffer) + filename_offset,
        encoded_name,
        len(encoded_name),
    )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    set_information.restype = ctypes.c_int
    if set_information(
        ctypes.c_void_p(handle),
        3,  # FileRenameInfo
        ctypes.byref(buffer),
        len(buffer),
    ):
        return
    error_number = ctypes.get_last_error()
    if error_number in {80, 183}:  # ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS
        raise FileExistsError(
            error_number, ctypes.FormatError(error_number), destination
        )
    raise OSError(error_number, ctypes.FormatError(error_number), destination)


def _anchor_directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _open_parent_anchor(parent: PreparedParent) -> ParentAnchor:
    _assert_prepared_parent(parent)
    anchor = ParentAnchor(
        prepared=parent,
        linux_fds=[],
        windows_handles=[],
        windows_identities=[],
    )
    try:
        relative = parent.path.relative_to(parent.allowed_root)
        if os.name == "nt":
            current = parent.allowed_root
            handle = _windows_open_directory(current)
            anchor.windows_handles.append(handle)
            anchor.windows_identities.append(_windows_handle_identity(handle))
            if anchor.windows_identities[-1][1] != parent.allowed_root_identity.inode:
                raise Phase5VisionViewsError(
                    "approved TEMP root handle identity differs from preparation"
                )
            for part in relative.parts:
                current /= part
                handle = _windows_open_directory(current)
                anchor.windows_handles.append(handle)
                anchor.windows_identities.append(_windows_handle_identity(handle))
            if anchor.windows_identities[-1][1] != parent.identity.inode:
                raise Phase5VisionViewsError(
                    "output parent handle identity differs from preparation"
                )
        elif sys.platform.startswith("linux"):
            current_fd = os.open(parent.allowed_root, _anchor_directory_flags())
            anchor.linux_fds.append(current_fd)
            if (
                _identity_from_stat(os.fstat(current_fd))
                != parent.allowed_root_identity
            ):
                raise Phase5VisionViewsError(
                    "approved TEMP root handle identity differs from preparation"
                )
            for part in relative.parts:
                current_fd = os.open(
                    part,
                    _anchor_directory_flags(),
                    dir_fd=current_fd,
                )
                anchor.linux_fds.append(current_fd)
            if _identity_from_stat(os.fstat(current_fd)) != parent.identity:
                raise Phase5VisionViewsError(
                    "output parent handle identity differs from preparation"
                )
        else:
            raise Phase5VisionViewsError(
                "anchored TEMP transactions require Windows or Linux"
            )
        _assert_anchor_visible(anchor)
        return anchor
    except BaseException:
        _close_parent_anchor(anchor, suppress_errors=True)
        raise


def _close_parent_anchor(
    anchor: ParentAnchor, *, suppress_errors: bool = False
) -> None:
    errors: list[BaseException] = []
    while anchor.linux_fds:
        descriptor = anchor.linux_fds.pop()
        try:
            os.close(descriptor)
        except OSError as exc:
            errors.append(exc)
    while anchor.windows_handles:
        handle = anchor.windows_handles.pop()
        try:
            _windows_close_handle(handle)
        except OSError as exc:
            errors.append(exc)
    anchor.windows_identities.clear()
    if errors and not suppress_errors:
        raise Phase5VisionViewsError(f"cannot close parent anchor: {errors[0]}")


def _assert_anchor_handle_identity(anchor: ParentAnchor) -> None:
    if anchor.parent_fd is not None:
        if (
            _identity_from_stat(os.fstat(anchor.linux_fds[0]))
            != anchor.prepared.allowed_root_identity
            or _identity_from_stat(os.fstat(anchor.parent_fd))
            != anchor.prepared.identity
        ):
            raise Phase5VisionViewsError(
                "anchored TEMP directory handle identity changed"
            )
    elif not anchor.windows_handles:
        raise Phase5VisionViewsError("anchored TEMP directory handles are closed")
    elif [
        _windows_handle_identity(handle) for handle in anchor.windows_handles
    ] != anchor.windows_identities:
        raise Phase5VisionViewsError(
            "anchored Windows directory handle identity changed"
        )


def _assert_anchor_visible(anchor: ParentAnchor) -> None:
    _assert_anchor_handle_identity(anchor)
    _assert_prepared_parent(anchor.prepared)


def _assert_linux_private_parent(anchor: ParentAnchor) -> None:
    if anchor.parent_fd is None:
        return
    metadata = os.fstat(anchor.parent_fd)
    # POSIX has no mkdir-and-return-fd primitive.  This strict, pre-provisioned
    # parent contract excludes untrusted credentials from the mkdir -> stat ->
    # open interval; the captured identity still rejects any later exchange
    # before the first bundle byte is written.
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise Phase5VisionViewsError(
            "Linux output parent must be a caller-provisioned private directory "
            "owned by the effective user with mode 0700"
        )
    ignored_errors = {
        getattr(errno, "ENODATA", 61),
        getattr(errno, "ENOTSUP", 95),
        getattr(errno, "EOPNOTSUPP", 95),
    }
    for attribute in ("system.posix_acl_access", "system.posix_acl_default"):
        try:
            payload = os.getxattr(anchor.parent_fd, attribute)
        except OSError as exc:
            if exc.errno in ignored_errors:
                continue
            raise Phase5VisionViewsError(
                f"cannot validate Linux output-parent ACL contract: {exc}"
            ) from exc
        if payload:
            raise Phase5VisionViewsError(
                "Linux output parent may not carry POSIX access/default ACLs"
            )


def _create_owned_staging(*, output: Path, anchor: ParentAnchor) -> OwnedStaging:
    _assert_anchor_visible(anchor)
    _assert_linux_private_parent(anchor)
    if os.path.lexists(output):
        raise Phase5VisionViewsError(f"output already exists: {output}")
    for _ in range(64):
        name = f".{output.name}.staging-{uuid.uuid4().hex}"
        path = anchor.prepared.path / name
        try:
            if anchor.parent_fd is not None:
                os.mkdir(name, mode=0o700, dir_fd=anchor.parent_fd)
                created_identity = _identity_from_stat(
                    os.stat(
                        name,
                        dir_fd=anchor.parent_fd,
                        follow_symlinks=False,
                    )
                )
                _staging_create_boundary_hook(
                    staging=path,
                    atomic_handle=False,
                )
                directory_fd = None
                try:
                    directory_fd = os.open(
                        name,
                        _anchor_directory_flags(),
                        dir_fd=anchor.parent_fd,
                    )
                    descriptor_identity = _identity_from_stat(os.fstat(directory_fd))
                    entry_identity = _identity_from_stat(
                        os.stat(
                            name,
                            dir_fd=anchor.parent_fd,
                            follow_symlinks=False,
                        )
                    )
                    if (
                        descriptor_identity != created_identity
                        or entry_identity != created_identity
                    ):
                        raise Phase5VisionViewsError(
                            "staging directory was exchanged before its first "
                            "dirfd acquisition; no bundle bytes were written"
                        )
                except BaseException:
                    if directory_fd is not None:
                        try:
                            os.close(directory_fd)
                        except BaseException:
                            pass
                    raise
                identity = created_identity
                windows_handle = None
            else:
                directory_fd = None
                if not anchor.windows_handles:
                    raise Phase5VisionViewsError(
                        "Windows parent anchor handle is unavailable"
                    )
                windows_handle = _windows_create_directory_handle(
                    anchor.windows_handles[-1],
                    name,
                )
                try:
                    handle_identity = _windows_handle_identity(windows_handle)
                    _staging_create_boundary_hook(
                        staging=path,
                        atomic_handle=True,
                    )
                    identity = _physical_directory_identity(
                        path,
                        label="staging directory",
                    )
                    if handle_identity[1] != identity.inode:
                        raise Phase5VisionViewsError(
                            "atomic staging handle identity differs from its "
                            "directory entry"
                        )
                except BaseException:
                    try:
                        _windows_close_handle(windows_handle)
                    except BaseException:
                        pass
                    raise
        except FileExistsError:
            continue
        owned = OwnedStaging(
            path=path,
            name=name,
            rollback_name=name,
            identity=identity,
            anchor=anchor,
            directory_fd=directory_fd,
            windows_handle=windows_handle,
        )
        _assert_owned_staging(owned, require_visible=True)
        return owned
    raise Phase5VisionViewsError("cannot allocate a unique staging directory")


def _assert_owned_staging(
    staging: OwnedStaging,
    *,
    require_visible: bool,
    allow_unbound_name: bool = False,
) -> None:
    if not staging.name_owned and not allow_unbound_name:
        raise Phase5VisionViewsError(
            "owned staging no longer has a verified anchored directory entry"
        )
    if require_visible:
        _assert_anchor_visible(staging.anchor)
    else:
        _assert_anchor_handle_identity(staging.anchor)
    if staging.directory_fd is not None:
        descriptor_identity = _identity_from_stat(os.fstat(staging.directory_fd))
        entry_identity = _identity_from_stat(
            os.stat(
                staging.name,
                dir_fd=staging.anchor.parent_fd,
                follow_symlinks=False,
            )
        )
        if (
            descriptor_identity != staging.identity
            or entry_identity != staging.identity
        ):
            raise Phase5VisionViewsError(
                "staging directory identity differs from its anchored entry"
            )
    else:
        identity = _physical_directory_identity(
            staging.path, label="owned staging directory"
        )
        handle_identity = (
            _windows_handle_identity(staging.windows_handle)
            if staging.windows_handle is not None
            else None
        )
        if (
            identity != staging.identity
            or handle_identity is None
            or handle_identity[1] != staging.identity.inode
        ):
            raise Phase5VisionViewsError("staging physical identity changed")


def _round_half_up_scaled(value: int, numerator: int, denominator: int) -> int:
    doubled = 2 * value * numerator
    return max(1, (doubled + denominator) // (2 * denominator))


def _scaled_size(
    size: tuple[int, int], numerator: int, denominator: int
) -> tuple[int, int]:
    width, height = size
    return (
        _round_half_up_scaled(width, numerator, denominator),
        _round_half_up_scaled(height, numerator, denominator),
    )


def _parse_focus_box(value: str) -> tuple[int, int, int, int]:
    parts = value.split(",")
    if len(parts) != 4 or any(not part for part in parts):
        raise argparse.ArgumentTypeError(
            "focus box must use x0,y0,x1,y1 integer syntax"
        )
    try:
        x0, y0, x1, y1 = (int(part, 10) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "focus box must use x0,y0,x1,y1 integer syntax"
        ) from exc
    return x0, y0, x1, y1


def _encode_png(image: Image.Image) -> bytes:
    if image.mode != "RGB":
        raise Phase5VisionViewsError(
            f"internal view mode must be RGB before encoding: {image.mode}"
        )
    image.info.clear()
    metadata = PngImagePlugin.PngInfo()
    encoded = BytesIO()
    image.save(encoded, pnginfo=metadata, **PNG_OPTIONS)
    return encoded.getvalue()


def _png_integrity_payload(
    view_id: str, filename: str, payload: bytes
) -> tuple[dict[str, Any], str]:
    try:
        with Image.open(BytesIO(payload)) as image:
            image.load()
            if image.format != "PNG" or image.mode != "RGB":
                raise Phase5VisionViewsError(
                    f"encoded view {view_id} is not an RGB PNG"
                )
            if image.info:
                raise Phase5VisionViewsError(
                    f"encoded view {view_id} contains forbidden PNG metadata: "
                    f"{sorted(image.info)}"
                )
            size = list(image.size)
            pixel_sha256 = _sha256_bytes(image.tobytes())
    except (OSError, UnidentifiedImageError) as exc:
        raise Phase5ContentInvalidError(
            f"encoded view {view_id} cannot be reopened: {exc}"
        ) from exc
    return (
        {
            "id": view_id,
            "path": filename,
            "sha256": _sha256_bytes(payload),
            "bytes": len(payload),
            "mode": "RGB",
            "size": size,
        },
        pixel_sha256,
    )


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write while emitting review bundle")
        view = view[written:]


def _write_owned_file(staging: OwnedStaging, name: str, payload: bytes) -> None:
    if "/" in name or "\\" in name or name in {"", ".", ".."}:
        raise Phase5VisionViewsError(f"invalid bundle filename: {name!r}")
    _assert_owned_staging(staging, require_visible=True)
    if staging.directory_fd is not None:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(name, flags, 0o600, dir_fd=staging.directory_fd)
    else:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(staging.path / name, flags, 0o600)
    try:
        _write_all(descriptor, payload)
    except BaseException:
        try:
            os.close(descriptor)
        except BaseException:
            pass
        raise
    else:
        os.close(descriptor)


def _render_views(
    source: Image.Image,
    focus_box: tuple[int, int, int, int],
    staging: OwnedStaging,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []

    def render(view_id: str, image: Image.Image) -> None:
        try:
            filename = VIEW_FILENAMES[view_id]
            payload = _encode_png(image)
            _write_owned_file(staging, filename, payload)
            artifact, _ = _png_integrity_payload(view_id, filename, payload)
            artifacts.append(artifact)
        finally:
            image.close()

    render("native", source.copy())
    render(
        "full25",
        source.resize(_scaled_size(source.size, 1, 4), Image.Resampling.LANCZOS),
    )
    render(
        "full50",
        source.resize(_scaled_size(source.size, 1, 2), Image.Resampling.LANCZOS),
    )
    crop = source.crop(focus_box)
    try:
        render(
            "focus200",
            crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS),
        )
        render(
            "focus400",
            crop.resize((crop.width * 4, crop.height * 4), Image.Resampling.LANCZOS),
        )
    finally:
        crop.close()
    if [artifact["id"] for artifact in artifacts] != list(VIEW_ORDER):
        raise Phase5VisionViewsError("internal exact-five view order drifted")
    return artifacts


def _build_receipt(
    *,
    source: BoundArtifact,
    source_size: tuple[int, int],
    focus_box: tuple[int, int, int, int],
    views: list[dict[str, Any]],
) -> dict[str, Any]:
    x0, y0, x1, y1 = focus_box
    return {
        "schema_version": SCHEMA_VERSION,
        "type": BUNDLE_TYPE,
        "view_order": list(VIEW_ORDER),
        "source": {
            "path": source.relative,
            "sha256": source.sha256,
            "bytes": source.signature[2],
            "mode": "RGB",
            "size": list(source_size),
        },
        "focus": {
            "box_px": list(focus_box),
            "crop_size": [x1 - x0, y1 - y0],
            "coordinate_convention": "left-top-inclusive_right-bottom-exclusive",
        },
        "rendering": {
            "full_size_rounding": ROUNDING_RULE,
            "full_size_rounding_formula": (
                "max(1,floor(source_dimension*numerator/denominator+0.5))"
            ),
            "interpolation": {
                "native": "none",
                "full25": INTERPOLATION,
                "full50": INTERPOLATION,
                "focus200": INTERPOLATION,
                "focus400": INTERPOLATION,
            },
            "transforms": {
                "native": {"kind": "identity"},
                "full25": {"kind": "full-frame-resize", "scale": [1, 4]},
                "full50": {"kind": "full-frame-resize", "scale": [1, 2]},
                "focus200": {
                    "kind": "focus-crop-resize",
                    "scale": [2, 1],
                },
                "focus400": {
                    "kind": "focus-crop-resize",
                    "scale": [4, 1],
                },
            },
            "png": {
                "format": "PNG",
                "mode": "RGB",
                "compress_level": 9,
                "optimize": False,
                "metadata": {},
            },
        },
        "views": views,
    }


def _owned_entry_names(staging: OwnedStaging) -> list[str]:
    if staging.directory_fd is not None:
        return os.listdir(staging.directory_fd)
    return [path.name for path in staging.path.iterdir()]


def _assert_exact_bundle_inventory(
    staging: OwnedStaging, expected_inventory: Sequence[str]
) -> None:
    if sorted(_owned_entry_names(staging)) != sorted(expected_inventory):
        raise Phase5VisionViewsError(
            "bundle inventory must contain exactly five physical PNG files and one JSON"
        )


def _pin_owned_entry(staging: OwnedStaging, name: str) -> PinnedBundleEntry:
    if "/" in name or "\\" in name or name in {"", ".", ".."}:
        raise Phase5VisionViewsError(f"invalid bundle filename: {name!r}")
    descriptor: int | None = None
    windows_handle: int | None = None
    try:
        if staging.directory_fd is not None:
            descriptor = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=staging.directory_fd,
            )
            handle_metadata = os.fstat(descriptor)
            path_metadata = os.stat(
                name,
                dir_fd=staging.directory_fd,
                follow_symlinks=False,
            )
            handle_identity = (
                handle_metadata.st_dev,
                handle_metadata.st_ino,
            )
            handle_signature = _stat_signature(handle_metadata)
            if (
                not stat.S_ISREG(handle_metadata.st_mode)
                or not stat.S_ISREG(path_metadata.st_mode)
                or handle_identity != (path_metadata.st_dev, path_metadata.st_ino)
                or handle_signature != _stat_signature(path_metadata)
            ):
                raise Phase5VisionViewsError(
                    f"bundle entry {name} is not one stable regular file"
                )
        else:
            windows_handle = _windows_open_file_for_snapshot(staging.path / name)
            handle_signature = _windows_file_signature(windows_handle)
            handle_identity = (handle_signature[0], handle_signature[1])
            path_metadata = os.stat(staging.path / name, follow_symlinks=False)
            attributes = handle_signature[2]
            if (
                attributes & (0x10 | 0x400)
                or not stat.S_ISREG(path_metadata.st_mode)
                or path_metadata.st_ino != handle_identity[1]
                or path_metadata.st_size != handle_signature[3]
            ):
                raise Phase5VisionViewsError(
                    f"bundle entry {name} is not one stable regular file"
                )
        return PinnedBundleEntry(
            name=name,
            descriptor=descriptor,
            windows_handle=windows_handle,
            handle_identity=handle_identity,
            handle_signature=handle_signature,
            path_signature=_stat_signature(path_metadata),
        )
    except OSError as exc:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException:
                pass
        if windows_handle is not None:
            try:
                _windows_close_handle(windows_handle)
            except BaseException:
                pass
        raise Phase5EvidenceIOError(f"cannot pin bundle entry {name}: {exc}") from exc
    except BaseException:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException:
                pass
        if windows_handle is not None:
            try:
                _windows_close_handle(windows_handle)
            except BaseException:
                pass
        raise


def _assert_pinned_entry(staging: OwnedStaging, entry: PinnedBundleEntry) -> None:
    if entry.descriptor is not None:
        handle_metadata = os.fstat(entry.descriptor)
        path_metadata = os.stat(
            entry.name,
            dir_fd=staging.directory_fd,
            follow_symlinks=False,
        )
        handle_identity = (handle_metadata.st_dev, handle_metadata.st_ino)
        handle_signature = _stat_signature(handle_metadata)
        path_identity = (path_metadata.st_dev, path_metadata.st_ino)
        valid = (
            stat.S_ISREG(handle_metadata.st_mode)
            and stat.S_ISREG(path_metadata.st_mode)
            and handle_identity == entry.handle_identity
            and handle_signature == entry.handle_signature
            and path_identity == entry.handle_identity
            and _stat_signature(path_metadata) == entry.path_signature
        )
    else:
        if entry.windows_handle is None:
            raise Phase5VisionViewsError(
                f"bundle entry {entry.name} pin closed before validation"
            )
        handle_signature = _windows_file_signature(entry.windows_handle)
        path_metadata = os.stat(
            staging.path / entry.name,
            follow_symlinks=False,
        )
        valid = (
            not handle_signature[2] & (0x10 | 0x400)
            and stat.S_ISREG(path_metadata.st_mode)
            and handle_signature == entry.handle_signature
            and path_metadata.st_ino == entry.handle_identity[1]
            and _stat_signature(path_metadata) == entry.path_signature
        )
    if not valid:
        raise Phase5VisionViewsError(
            f"bundle entry {entry.name} changed while the six-file snapshot was pinned"
        )


def _read_owned_entry(staging: OwnedStaging, entry: PinnedBundleEntry) -> bytes:
    if entry.descriptor is not None:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(entry.descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        payload = b"".join(chunks)
        expected_size = entry.handle_signature[2]
    elif entry.windows_handle is not None:
        payload = _windows_read_file_handle(entry.windows_handle)
        expected_size = entry.handle_signature[3]
    else:
        raise Phase5VisionViewsError(
            f"bundle entry {entry.name} pin closed before its bytes were read"
        )
    if len(payload) != expected_size:
        raise Phase5VisionViewsError(
            f"bundle entry {entry.name} changed while its bytes were read"
        )
    return payload


def _close_pinned_entries(
    entries: Sequence[PinnedBundleEntry], *, suppress_errors: bool
) -> None:
    first_error: BaseException | None = None
    for entry in reversed(entries):
        descriptor = entry.descriptor
        entry.descriptor = None
        if descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        windows_handle = entry.windows_handle
        entry.windows_handle = None
        if windows_handle is not None:
            try:
                _windows_close_handle(windows_handle)
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
    if first_error is not None and not suppress_errors:
        raise Phase5EvidenceIOError(
            f"cannot close pinned bundle snapshot: {first_error}"
        ) from first_error


def _assert_closed_entry_path(staging: OwnedStaging, entry: PinnedBundleEntry) -> None:
    if staging.directory_fd is not None:
        metadata = os.stat(
            entry.name,
            dir_fd=staging.directory_fd,
            follow_symlinks=False,
        )
        path_identity = (metadata.st_dev, metadata.st_ino)
        same_identity = path_identity == entry.handle_identity
    else:
        metadata = os.stat(staging.path / entry.name, follow_symlinks=False)
        same_identity = metadata.st_ino == entry.handle_identity[1]
    if (
        not stat.S_ISREG(metadata.st_mode)
        or not same_identity
        or _stat_signature(metadata) != entry.path_signature
    ):
        raise Phase5VisionViewsError(
            f"bundle entry {entry.name} changed after the pinned snapshot closed"
        )


def _read_pinned_bundle(
    staging: OwnedStaging, expected_inventory: Sequence[str]
) -> tuple[list[PinnedBundleEntry], dict[str, bytes]]:
    entries: list[PinnedBundleEntry] = []
    try:
        try:
            _assert_exact_bundle_inventory(staging, expected_inventory)
            for name in expected_inventory:
                entries.append(_pin_owned_entry(staging, name))
            # Only after every entry is pinned may any bytes be consumed.
            _assert_owned_staging(staging, require_visible=False)
            _assert_exact_bundle_inventory(staging, expected_inventory)
            for entry in entries:
                _assert_pinned_entry(staging, entry)
            payloads = {
                entry.name: _read_owned_entry(staging, entry) for entry in entries
            }
        except OSError as exc:
            raise Phase5EvidenceIOError(
                f"cannot read pinned six-file bundle snapshot: {exc}"
            ) from exc
    except BaseException:
        _close_pinned_entries(entries, suppress_errors=True)
        raise
    return entries, payloads


def _snapshot_bundle(
    staging: OwnedStaging,
    expected_receipt: dict[str, Any],
    receipt_payload: bytes,
) -> BundleSnapshot:
    _assert_owned_staging(staging, require_visible=False)
    expected_inventory = sorted([*VIEW_FILENAMES.values(), RECEIPT_FILENAME])
    entries, payloads = _read_pinned_bundle(staging, expected_inventory)
    primary_error: BaseException | None = None
    try:
        actual_receipt_payload = payloads[RECEIPT_FILENAME]
        if actual_receipt_payload != receipt_payload:
            raise Phase5VisionViewsError("bundle receipt changed after it was prepared")
        try:
            parsed_receipt = json.loads(actual_receipt_payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise Phase5ContentInvalidError(
                f"bundle receipt is not canonical UTF-8 JSON: {exc}"
            ) from exc
        if (
            not isinstance(parsed_receipt, dict)
            or parsed_receipt != expected_receipt
            or _stable_json_bytes(parsed_receipt) != actual_receipt_payload
        ):
            raise Phase5VisionViewsError(
                "bundle receipt is not self-consistent canonical JSON"
            )
        views = parsed_receipt.get("views")
        if not isinstance(views, list) or [
            view.get("id") if isinstance(view, dict) else None for view in views
        ] != list(VIEW_ORDER):
            raise Phase5VisionViewsError("bundle receipt exact-five view order drifted")
        pixel_hashes: list[tuple[str, str]] = []
        for expected in views:
            view_payload = payloads[expected["path"]]
            actual, pixel_sha256 = _png_integrity_payload(
                expected["id"], expected["path"], view_payload
            )
            if actual != expected:
                raise Phase5VisionViewsError(
                    f"bundle view changed after receipt binding: {expected['id']}"
                )
            pixel_hashes.append((expected["id"], pixel_sha256))
        tree_hashes = tuple(
            sorted(
                [
                    *(
                        (view["path"], _sha256_bytes(payloads[view["path"]]))
                        for view in views
                    ),
                    (RECEIPT_FILENAME, _sha256_bytes(actual_receipt_payload)),
                ]
            )
        )

        # Content validation above deliberately runs with every handle/fd
        # retained.  This final recheck is the handle-backed snapshot boundary.
        try:
            _assert_owned_staging(staging, require_visible=False)
            _assert_exact_bundle_inventory(staging, expected_inventory)
            for entry in entries:
                _assert_pinned_entry(staging, entry)
        except OSError as exc:
            raise Phase5EvidenceIOError(
                f"cannot finalize pinned six-file bundle snapshot: {exc}"
            ) from exc
        snapshot = BundleSnapshot(
            tree_hashes=tree_hashes,
            pixel_hashes=tuple(pixel_hashes),
        )
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        _close_pinned_entries(entries, suppress_errors=primary_error is not None)

    # Linux fds do not deny a same-credential rename/write.  Revalidate every
    # path once more after all six pins close.  Windows receives the same final
    # path handoff check after its deny-write/delete handles are released.
    try:
        _assert_owned_staging(staging, require_visible=False)
        _assert_exact_bundle_inventory(staging, expected_inventory)
        for entry in entries:
            _assert_closed_entry_path(staging, entry)
    except OSError as exc:
        raise Phase5EvidenceIOError(
            f"cannot revalidate closed six-file bundle snapshot: {exc}"
        ) from exc
    return snapshot


def _linux_rename_anchor_no_replace(
    anchor: ParentAnchor,
    source_name: str,
    destination_name: str,
) -> None:
    if anchor.parent_fd is None:
        raise Phase5VisionViewsError("Linux anchored rename requires a parent dirfd")
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise Phase5VisionViewsError(
            "Linux renameat2 is required for anchored no-replace installation"
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
        anchor.parent_fd,
        os.fsencode(source_name),
        anchor.parent_fd,
        os.fsencode(destination_name),
        1,  # RENAME_NOREPLACE
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(error_number, os.strerror(error_number), destination_name)
    raise OSError(error_number, os.strerror(error_number), destination_name)


def _rename_anchor_no_replace(
    staging: OwnedStaging,
    destination_name: str,
    *,
    invoke_fault_hook: bool = False,
    source: BoundArtifact | None = None,
) -> None:
    anchor = staging.anchor
    source_name = staging.name
    _assert_anchor_handle_identity(anchor)
    if invoke_fault_hook:
        _before_rename_syscall_hook(
            staging=staging.path,
            source_name=source_name,
            destination_name=destination_name,
        )
        if source is None:
            raise Phase5VisionViewsError(
                "guarded output rename requires a final source binding"
            )
        # This is the last file validation before the rename syscall.  The
        # fault hook deliberately precedes it so no test/production callback
        # can invalidate the source after its linearizing check.
        _assert_source_unchanged(source)
    if anchor.parent_fd is not None:
        _linux_rename_anchor_no_replace(anchor, source_name, destination_name)
        return
    if staging.windows_handle is None:
        raise Phase5VisionViewsError(
            "owned Windows staging handle is closed before guarded rename"
        )
    _windows_rename_directory_handle_no_replace(
        staging.windows_handle,
        anchor.prepared.path / destination_name,
    )


def _close_windows_staging_handle(staging: OwnedStaging) -> None:
    if staging.windows_handle is not None:
        handle = staging.windows_handle
        staging.windows_handle = None
        _windows_close_handle(handle)


def _claim_owned_staging(staging: OwnedStaging) -> None:
    """Move the public staging name behind a fresh guarded transaction claim."""

    _assert_owned_staging(staging, require_visible=True)
    claim_name = f".{staging.rollback_name.removeprefix('.')}-{uuid.uuid4().hex}"
    try:
        _rename_anchor_no_replace(
            staging,
            claim_name,
        )
    except BaseException:
        # A fault at the syscall boundary may have detached the original name.
        # Preserve its open handle/fd and never mutate whatever now occupies it.
        try:
            _assert_owned_staging(staging, require_visible=False)
        except BaseException:
            staging.name_owned = False
        raise
    staging.name = claim_name
    staging.path = staging.anchor.prepared.path / claim_name
    staging.name_owned = False
    try:
        _assert_owned_staging(
            staging,
            require_visible=False,
            allow_unbound_name=True,
        )
    except BaseException as exc:
        raise Phase5VisionViewsError(
            "guarded staging claim captured a foreign directory; no entry was "
            "installed at the output name"
        ) from exc
    staging.name_owned = True


def _is_evidence_io_failure(error: BaseException) -> bool:
    # Deliberately do not walk ``__cause__``/``__context__``: Pillow reports
    # stable corrupt content with OSError, which the decoder converts to the
    # non-retryable Phase5ContentInvalidError contract.
    return isinstance(error, (OSError, Phase5EvidenceIOError))


def _retry_evidence_read(operation: Any, *, attempts: int = 3) -> Any:
    """Retry only OS-backed evidence reads; never retry logical mismatches."""

    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            if not _is_evidence_io_failure(exc) or attempt + 1 == attempts:
                raise
    raise AssertionError("evidence retry loop exhausted without returning or raising")


def _install_owned_staging(
    staging: OwnedStaging,
    output: Path,
    *,
    source: BoundArtifact,
) -> None:
    _assert_owned_staging(staging, require_visible=False)
    source_name = staging.name
    _rename_anchor_no_replace(
        staging,
        output.name,
        invoke_fault_hook=True,
        source=source,
    )
    staging.name = output.name
    staging.path = output
    windows_exact_handle_rename = staging.directory_fd is None
    if windows_exact_handle_rename:
        # SetFileInformationByHandle renamed the exact retained directory
        # object.  Record that authoritative outcome before any fallible path
        # evidence read so a read error cannot be mistaken for no commit.
        staging.publication_state = PublicationState.COMMITTED
        staging.installed = True
        staging.name_owned = True
    else:
        # renameat2 is name-based.  Until dirfd and destination entry agree,
        # publication outcome is unknown and no recovery rename is allowed.
        staging.publication_state = PublicationState.UNKNOWN
        staging.installed = False
        staging.name_owned = False
    try:
        _retry_evidence_read(
            lambda: _assert_owned_staging(
                staging,
                require_visible=False,
                allow_unbound_name=True,
            )
        )
    except BaseException as identity_error:
        if windows_exact_handle_rename:
            staging.publication_state = PublicationState.UNKNOWN
            raise Phase5VisionViewsError(
                "Windows exact-handle rename committed, but destination identity "
                "evidence remained unreadable; publication state is unknown and "
                "final/staging evidence was preserved without rename or deletion"
            ) from identity_error
        if _is_evidence_io_failure(identity_error):
            # renameat2 succeeded, but unreadable destination evidence cannot
            # prove either our dirfd identity or a logical foreign mismatch.
            # Keep UNKNOWN and do not perform any recovery rename/delete.
            raise Phase5VisionViewsError(
                "Linux anchored rename returned success, but destination identity "
                "evidence remained unreadable; publication state is unknown and "
                "final/staging evidence was preserved without rename or deletion"
            ) from identity_error
        if staging.anchor.parent_fd is not None:
            quarantine_name = f".{output.name}.foreign-{uuid.uuid4().hex}"
            try:
                _linux_rename_anchor_no_replace(
                    staging.anchor,
                    output.name,
                    quarantine_name,
                )
            except BaseException as quarantine_error:
                raise Phase5VisionViewsError(
                    "guarded install encountered a foreign directory at the "
                    "output name and could not quarantine it: "
                    f"{quarantine_error}"
                ) from identity_error
            staging.publication_state = PublicationState.PROVEN_UNCOMMITTED
        staging.name = source_name
        staging.path = staging.anchor.prepared.path / source_name
        raise Phase5VisionViewsError(
            "guarded install rejected a foreign staging-name replacement; the "
            "foreign directory was not retained at the output name"
        ) from identity_error
    staging.publication_state = PublicationState.COMMITTED
    staging.installed = True
    staging.name_owned = True


def _rollback_to_preserved_staging(staging: OwnedStaging) -> None:
    if (
        staging.publication_state is not PublicationState.COMMITTED
        or not staging.installed
        or not staging.name_owned
    ):
        return
    if staging.directory_fd is not None:
        _assert_owned_staging(staging, require_visible=False)
    _rename_anchor_no_replace(staging, staging.rollback_name)
    staging.name = staging.rollback_name
    staging.path = staging.anchor.prepared.path / staging.rollback_name
    staging.name_owned = False
    staging.installed = False
    staging.publication_state = PublicationState.UNKNOWN
    _retry_evidence_read(
        lambda: _assert_owned_staging(
            staging,
            require_visible=False,
            allow_unbound_name=True,
        )
    )
    staging.name_owned = True
    staging.publication_state = PublicationState.PROVEN_UNCOMMITTED


def _close_owned_staging(staging: OwnedStaging) -> None:
    _close_windows_staging_handle(staging)
    if staging.directory_fd is not None:
        descriptor = staging.directory_fd
        staging.directory_fd = None
        os.close(descriptor)


def _assert_source_unchanged(source: BoundArtifact) -> None:
    try:
        source.assert_unchanged()
    except BoundArtifactError as exc:
        raise Phase5VisionViewsError(str(exc)) from exc


def emit_phase5_vision_views(
    source: str,
    output: str | Path,
    *,
    source_sha256: str,
    focus_box: Sequence[int],
) -> dict[str, Any]:
    """Build and atomically install one deterministic exact-five review bundle."""

    expected_sha256 = _validate_sha256(source_sha256)
    bound, source_image = _bind_source(source, expected_sha256)
    try:
        validated_focus = _validate_focus_box(focus_box, source_image.size)
        output_path, allowed_root = _validate_output_path(output)
        prepared_parent = _prepare_output_parent(output_path, allowed_root)
        parent_anchor: ParentAnchor | None = None
        owned_staging: OwnedStaging | None = None
        try:
            _before_parent_anchor_open_hook(
                output=output_path,
                parent=prepared_parent,
            )
            parent_anchor = _open_parent_anchor(prepared_parent)
            owned_staging = _create_owned_staging(
                output=output_path, anchor=parent_anchor
            )
            views = _render_views(source_image, validated_focus, owned_staging)
            receipt = _build_receipt(
                source=bound,
                source_size=source_image.size,
                focus_box=validated_focus,
                views=views,
            )
            receipt_payload = _stable_json_bytes(receipt)
            _write_owned_file(owned_staging, RECEIPT_FILENAME, receipt_payload)

            # Every Git subprocess and race-test callback precedes the closed
            # commit sequence. Source bytes linearize at the final pre-rename
            # assertion. Overall success linearizes at the single installed
            # snapshot below; after it, the success path performs no file read.
            _assert_git_tracked(bound.relative)
            _before_commit_validation_hook(
                source=bound,
                staging=owned_staging.path,
                output=output_path,
            )
            _assert_anchor_visible(parent_anchor)
            _assert_owned_staging(owned_staging, require_visible=True)
            _claim_owned_staging(owned_staging)
            _before_anchored_rename_hook(
                source=bound,
                staging=owned_staging.path,
                output=output_path,
                parent=prepared_parent,
            )
            prepared_snapshot = _snapshot_bundle(
                owned_staging, receipt, receipt_payload
            )

            receipt_sha256 = _sha256_bytes(receipt_payload)
            result = {
                "valid": True,
                "output_dir": os.fspath(output_path),
                "receipt": {
                    "path": os.fspath(output_path / RECEIPT_FILENAME),
                    "sha256": receipt_sha256,
                },
                "view_order": list(VIEW_ORDER),
            }
            _install_owned_staging(
                owned_staging,
                output_path,
                source=bound,
            )
            try:
                _retry_evidence_read(lambda: _assert_anchor_visible(parent_anchor))
                installed_snapshot = _retry_evidence_read(
                    lambda: _snapshot_bundle(
                        owned_staging,
                        receipt,
                        receipt_payload,
                    )
                )
            except BaseException as evidence_error:
                if _is_evidence_io_failure(evidence_error):
                    owned_staging.publication_state = PublicationState.UNKNOWN
                raise
            if installed_snapshot != prepared_snapshot:
                raise Phase5VisionViewsError(
                    "installed bundle differs from the prepared byte/pixel snapshot"
                )
            return result
        except BaseException as original_error:
            if (
                owned_staging is not None
                and owned_staging.publication_state is PublicationState.UNKNOWN
            ):
                raise Phase5VisionViewsError(
                    "vision bundle publication state is unknown after the commit "
                    "boundary; final/staging evidence was preserved without "
                    "rename or deletion so verification/recovery can resume: "
                    f"{original_error}"
                ) from original_error
            if (
                owned_staging is not None
                and owned_staging.publication_state is PublicationState.COMMITTED
                and owned_staging.installed
                and owned_staging.name_owned
            ):
                try:
                    _rollback_to_preserved_staging(owned_staging)
                except BaseException as rollback_error:
                    raise Phase5VisionViewsError(
                        "vision bundle failed; anchored rollback also failed, so "
                        "transaction debris was preserved in place: "
                        f"{rollback_error}"
                    ) from original_error
            if owned_staging is not None and not owned_staging.name_owned:
                raise Phase5VisionViewsError(
                    "vision bundle transaction failed after its staging name was "
                    "exchanged; no foreign directory was installed by the guarded "
                    "claim, and transaction debris was preserved without deletion: "
                    f"{original_error}"
                ) from original_error
            if owned_staging is not None:
                raise Phase5VisionViewsError(
                    "vision bundle transaction failed; owned TEMP debris was "
                    f"preserved without recursive deletion: {owned_staging.path}: "
                    f"{original_error}"
                ) from original_error
            raise
        finally:
            try:
                if owned_staging is not None:
                    _close_owned_staging(owned_staging)
            except BaseException:
                pass
            if parent_anchor is not None:
                try:
                    _close_parent_anchor(parent_anchor, suppress_errors=True)
                except BaseException:
                    pass
    finally:
        try:
            source_image.close()
        except BaseException:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        help="tracked repository-relative RGB PNG source path",
    )
    parser.add_argument(
        "output",
        type=Path,
        help=(
            "new output directory below repo tmp or OS temp; its parent must "
            "already exist (and on Linux must be private mode 0700 without ACL)"
        ),
    )
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument(
        "--focus-box",
        required=True,
        type=_parse_focus_box,
        metavar="X0,Y0,X1,Y1",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = emit_phase5_vision_views(
            args.source,
            args.output,
            source_sha256=args.source_sha256,
            focus_box=args.focus_box,
        )
    except (
        BoundArtifactError,
        OSError,
        Phase5VisionViewsError,
        ReleasePathError,
        ValueError,
    ) as exc:
        result = {"valid": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
