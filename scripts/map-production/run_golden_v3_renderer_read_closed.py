#!/usr/bin/env python3
"""Run the v21 renderer through the portable Golden read closure.

The closure implementation remains the established Golden-v2 boundary.  This
v3 entry point preloads v21's complete fixed Python/Pillow module surface
before the boundary is installed, preventing import-time directory discovery
from being mistaken for a renderer data read.
"""

from __future__ import annotations

import importlib

import run_golden_v2_renderer_read_closed as closure


PRELOAD_MODULES = (
    "argparse",
    "binascii",
    "dataclasses",
    "hashlib",
    "io",
    "json",
    "os",
    "platform",
    "re",
    "struct",
    "sys",
    "pathlib",
    "typing",
    "cv2",
    "numpy",
    "numpy.ma",
    "PIL",
    "PIL.Image",
    "PIL.ImageFile",
    "PIL.ImageMode",
    "PIL.ImagePalette",
    "PIL.PngImagePlugin",
)


def _preload_v21_runtime() -> None:
    for module_name in PRELOAD_MODULES:
        importlib.import_module(module_name)


def main() -> int:
    closure._preload_approved_runtime = _preload_v21_runtime
    return closure.main()


if __name__ == "__main__":
    raise SystemExit(main())
