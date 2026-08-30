#!/usr/bin/env python3
"""Check or atomically record one map-production job state transition."""

from __future__ import annotations

import argparse
import copy
import os
import tempfile
from pathlib import Path

from production_common import (
    STATES,
    ValidationFailure,
    dump_json,
    transition_allowed,
    utc_now,
)
from validate_manifest import validate_manifest


def find_job(manifest: dict, job_id: str) -> dict | None:
    return next(
        (
            job
            for job in manifest.get("jobs", [])
            if isinstance(job, dict) and job.get("id") == job_id
        ),
        None,
    )


def record_atomically(path: Path, value: dict) -> None:
    """Replace a manifest only after a complete sibling temp file is written."""

    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temp_path = Path(raw_temp)
    try:
        dump_json(temp_path, value)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("job_id")
    parser.add_argument("target", choices=STATES)
    parser.add_argument("--apply", action="store_true", help="record the validated transition")
    parser.add_argument("--actor", help="actor recorded with --apply")
    parser.add_argument("--note", default="", help="optional state-history note")
    parser.add_argument("--at", help="RFC 3339 event time (defaults to current UTC time)")
    parser.add_argument("--check-files", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest, errors = validate_manifest(args.manifest, check_files=args.check_files)
    except ValidationFailure as exc:
        print(f"Current manifest could not be validated: {exc}")
        return 1
    if errors or manifest is None:
        print("Current manifest is invalid; transition not checked.")
        for error in errors:
            print(f"- {error}")
        return 1

    job = find_job(manifest, args.job_id)
    if job is None:
        print(f"Unknown job id: {args.job_id!r}")
        return 1
    current = job.get("status")
    if not isinstance(current, str) or not transition_allowed(current, args.target):
        print(f"Illegal transition for {args.job_id!r}: {current!r} -> {args.target!r}")
        return 1
    if args.apply and not args.actor:
        print("--actor is required with --apply")
        return 2

    candidate = copy.deepcopy(manifest)
    candidate_job = find_job(candidate, args.job_id)
    assert candidate_job is not None
    candidate_job["status"] = args.target
    event = {
        "state": args.target,
        "at": args.at or utc_now(),
        "actor": args.actor or "transition-check",
    }
    if args.note:
        event["note"] = args.note
    candidate_job["history"].append(event)
    candidate["updated_at"] = event["at"]

    # Validate the projected state so a legal edge cannot bypass artifact/QA gates.
    with tempfile.TemporaryDirectory(prefix="sstory-transition-") as temp_dir:
        candidate_path = Path(temp_dir) / args.manifest.name
        dump_json(candidate_path, candidate)
        _, candidate_errors = validate_manifest(
            candidate_path, check_files=args.check_files
        )
    if candidate_errors:
        print(
            f"Transition edge is legal, but target state {args.target!r} is not ready "
            f"for {args.job_id!r}:"
        )
        for error in candidate_errors:
            print(f"- {error}")
        return 1

    if args.apply:
        try:
            record_atomically(args.manifest, candidate)
        except OSError as exc:
            print(f"Could not update {args.manifest}: {exc}")
            return 1
        print(f"Recorded transition: {args.job_id}: {current} -> {args.target}")
    else:
        print(f"Transition is valid: {args.job_id}: {current} -> {args.target}")
        print("Dry run only; pass --apply --actor NAME to record it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
