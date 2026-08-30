#!/usr/bin/env python3
"""Validate the exact 23-sheet canonical Phase 5 Vision focus registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from phase5_vision_evidence import (
    DEFAULT_FOCUS_REGISTRY,
    Phase5VisionEvidenceError,
    load_focus_registry,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_FOCUS_REGISTRY)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        registry = load_focus_registry(args.registry)
        result = {
            "valid": True,
            "registry": registry.binding.relative,
            "sha256": registry.binding.sha256,
            "sheet_count": len(registry.ordered_sheet_ids),
            "sheet_ids": list(registry.ordered_sheet_ids),
        }
    except Phase5VisionEvidenceError as exc:
        result = {"valid": False, "error": str(exc)}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("valid" if result["valid"] else f"invalid: {result['error']}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
