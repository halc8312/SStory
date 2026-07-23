#!/usr/bin/env python3
"""Validate an SStory map-production manifest.

Validation covers the JSON Schema contract, state-history transitions, job
references, bounds/zoom invariants, QA gates, and (optionally) artifact paths.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from production_common import (
    DEFAULT_MANIFEST_SCHEMA,
    ValidationFailure,
    load_json,
    validate_manifest_semantics,
)


def schema_errors(instance: Any, schema: Any) -> list[str]:
    """Return stable, human-readable jsonschema errors."""

    try:
        import jsonschema
    except ImportError as exc:
        raise ValidationFailure(
            "jsonschema is required; install repository development dependencies"
        ) from exc

    try:
        jsonschema.Draft7Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise ValidationFailure(f"Invalid manifest schema: {exc.message}") from exc

    validator = jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker())
    errors: list[str] = []
    for error in sorted(
        validator.iter_errors(instance),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    ):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"schema violation at {location}: {error.message}")
    return errors


def validate_manifest(
    manifest_path: Path,
    schema_path: Path = DEFAULT_MANIFEST_SCHEMA,
    *,
    check_files: bool = False,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Load and validate a manifest, returning it with accumulated errors."""

    try:
        manifest = load_json(manifest_path)
        schema = load_json(schema_path)
    except ValidationFailure as exc:
        return None, [str(exc)]

    errors = schema_errors(manifest, schema)
    if isinstance(manifest, dict):
        errors.extend(
            validate_manifest_semantics(
                manifest,
                manifest_path=manifest_path,
                check_files=check_files,
            )
        )
    return manifest if isinstance(manifest, dict) else None, errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="production manifest JSON")
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_MANIFEST_SCHEMA,
        help=f"manifest schema (default: {DEFAULT_MANIFEST_SCHEMA})",
    )
    parser.add_argument(
        "--check-files",
        action="store_true",
        help="require artifacts that should exist at each job's current state",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit a machine-readable result",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest, errors = validate_manifest(
            args.manifest,
            args.schema,
            check_files=args.check_files,
        )
    except ValidationFailure as exc:
        manifest, errors = None, [str(exc)]

    jobs = manifest.get("jobs", []) if manifest else []
    counts = Counter(
        job.get("status")
        for job in jobs
        if isinstance(job, dict) and isinstance(job.get("status"), str)
    )
    result = {
        "valid": not errors,
        "manifest": str(args.manifest),
        "job_count": len(jobs) if isinstance(jobs, list) else 0,
        "states": dict(sorted(counts.items())),
        "errors": errors,
    }

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print(f"Map-production manifest validation failed: {args.manifest}", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    else:
        print(f"Map-production manifest validation passed: {args.manifest}")
        print(f"  Jobs: {result['job_count']}")
        if counts:
            print("  States: " + ", ".join(f"{state}={count}" for state, count in sorted(counts.items())))
        print(f"  Artifact paths checked: {'yes' if args.check_files else 'no'}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
