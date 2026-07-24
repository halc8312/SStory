#!/usr/bin/env python3
"""Run one Golden-v2 Python renderer with a portable workspace read closure.

The renderer may read only itself plus its declared config, donors, and
controls. Standard-library/site-package import code is allowed, and the single
declared output may be written. Other file/device reads, directory discovery,
network access, filesystem mutations, and child processes fail closed.

This is a CPython audit boundary, not an OS sandbox. CPython cannot report
arbitrary direct syscalls made inside a native extension, nor does this runner
virtualize host, clock, randomness, or process APIs. Those remain explicit
limits of the mechanism; the approved renderer and this runner are therefore
both SHA-256-bound.
"""

from __future__ import annotations

import argparse
import importlib
import os
import runpy
import sys
import sysconfig
from pathlib import Path
from typing import Any


CODE_SUFFIXES = frozenset(
    {".py", ".pyc", ".pyo", ".pyd", ".so", ".dll", ".pth", ".zip"}
)
FORBIDDEN_CHILD_EVENTS = frozenset(
    {
        "subprocess.Popen",
        "os.exec",
        "os.fork",
        "os.forkpty",
        "os.system",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.spawn",
        "os.startfile",
    }
)
FORBIDDEN_MUTATION_EVENTS = frozenset(
    {
        "os.chdir",
        "os.chmod",
        "os.chown",
        "os.link",
        "os.mkdir",
        "os.mknod",
        "os.remove",
        "os.removexattr",
        "os.rename",
        "os.rmdir",
        "os.setxattr",
        "os.symlink",
        "os.truncate",
        "os.utime",
        "os.putenv",
        "os.unsetenv",
    }
)
FORBIDDEN_DISCOVERY_EVENTS = frozenset({"os.listdir", "os.scandir", "os.walk"})
OPEN_ACCESS_MASK = os.O_WRONLY | os.O_RDWR


class ReadClosureViolation(RuntimeError):
    """Raised when renderer code escapes its declared workspace file closure."""


def _identity(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _is_read(flags: Any, mode: Any) -> bool:
    if isinstance(flags, int):
        return flags & OPEN_ACCESS_MASK != os.O_WRONLY
    return not isinstance(mode, str) or "r" in mode or "+" in mode


def _is_write(flags: Any, mode: Any) -> bool:
    if isinstance(flags, int):
        return flags & OPEN_ACCESS_MASK != os.O_RDONLY
    return isinstance(mode, str) and any(
        token in mode for token in ("w", "a", "x", "+")
    )


def _runtime_code_roots() -> tuple[str, ...]:
    """Return actual stdlib/site-package roots, never an arbitrary code path."""

    configured = sysconfig.get_paths()
    roots = {
        _identity(configured[name])
        for name in ("stdlib", "platstdlib", "purelib", "platlib")
        if configured.get(name)
    }
    for prefix in {sys.prefix, sys.base_prefix, sys.exec_prefix}:
        roots.add(_identity(Path(prefix) / "DLLs"))
    return tuple(sorted(roots))


def _preload_approved_runtime() -> None:
    """Load the renderer's fixed binary stack before closing discovery APIs."""

    for module_name in ("cv2", "numpy", "PIL", "PIL.Image"):
        importlib.import_module(module_name)


def install_read_closure(*, allowed_reads: list[Path], output: Path) -> None:
    allowed_identities = {_identity(path) for path in allowed_reads}
    output_identity = _identity(output)
    runtime_code_roots = _runtime_code_roots()

    def audit(event: str, arguments: tuple[Any, ...]) -> None:
        if event in FORBIDDEN_CHILD_EVENTS:
            raise ReadClosureViolation(
                f"renderer may not spawn an unmonitored child process: {event}"
            )
        if event in FORBIDDEN_MUTATION_EVENTS:
            raise ReadClosureViolation(
                f"renderer may not mutate any path except by writing its declared output: {event}"
            )
        if event in FORBIDDEN_DISCOVERY_EVENTS:
            raise ReadClosureViolation(
                f"renderer may not discover undeclared directory contents: {event}"
            )
        if event.startswith("socket."):
            raise ReadClosureViolation(
                f"renderer may not access sockets or networks: {event}"
            )
        if event != "open" or not arguments:
            return
        raw_path = arguments[0]
        if isinstance(raw_path, int):
            return
        try:
            path_text = os.fsdecode(raw_path)
        except TypeError:
            return
        path_identity = _identity(path_text)
        mode = arguments[1] if len(arguments) > 1 else None
        flags = arguments[2] if len(arguments) > 2 else None
        wants_read = _is_read(flags, mode)
        wants_write = _is_write(flags, mode)
        if path_identity == output_identity:
            return
        if path_identity in allowed_identities and wants_read and not wants_write:
            return
        suffix = Path(path_text).suffix.casefold()
        if (
            suffix in CODE_SUFFIXES
            and wants_read
            and not wants_write
            and any(_inside(path_identity, root) for root in runtime_code_roots)
        ):
            return
        operation = (
            "read/write"
            if wants_read and wants_write
            else "write"
            if wants_write
            else "read"
        )
        raise ReadClosureViolation(
            "undeclared file/device access rejected: "
            f"operation={operation}, path={path_text}"
        )

    sys.addaudithook(audit)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--renderer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-read", type=Path, action="append", default=[])
    parser.add_argument("renderer_argv", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    workspace_root = args.workspace_root.resolve()
    renderer = (
        args.renderer if args.renderer.is_absolute() else workspace_root / args.renderer
    ).resolve()
    output = (
        args.output if args.output.is_absolute() else workspace_root / args.output
    ).resolve()
    allowed_reads = [
        (path if path.is_absolute() else workspace_root / path).resolve()
        for path in args.allow_read
    ]
    renderer_argv = list(args.renderer_argv)
    if renderer_argv and renderer_argv[0] == "--":
        renderer_argv.pop(0)
    if not renderer.is_file():
        parser.error(f"renderer is not a regular file: {renderer}")
    if not all(path.is_file() for path in allowed_reads):
        parser.error("every declared read must be an existing regular file")
    if not _inside(_identity(renderer), _identity(workspace_root)):
        parser.error("renderer must stay inside the workspace")
    if not _inside(_identity(output), _identity(workspace_root)):
        parser.error("output must stay inside the workspace")

    _preload_approved_runtime()
    os.chdir(workspace_root)
    install_read_closure(
        allowed_reads=[renderer, *allowed_reads],
        output=output,
    )
    sys.argv = [os.fspath(renderer), *renderer_argv]
    try:
        runpy.run_path(os.fspath(renderer), run_name="__main__")
    except ReadClosureViolation as exc:
        parser.exit(73, f"Golden-v2 renderer read closure failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
