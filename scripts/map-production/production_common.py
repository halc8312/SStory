#!/usr/bin/env python3
"""Shared helpers for SStory's map-production command-line tools."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_MANIFEST_SCHEMA = (
    REPO_ROOT / "world" / "map-production" / "schemas" / "production-manifest.schema.json"
)

STATES = (
    "planned",
    "inputs-ready",
    "generated",
    "automated-qa",
    "vision-qa",
    "accepted",
    "revise",
    "rejected",
    "tiled",
    "staging",
    "published",
)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "planned": frozenset({"inputs-ready", "rejected"}),
    "inputs-ready": frozenset({"generated", "rejected"}),
    "generated": frozenset({"generated", "automated-qa", "revise", "rejected"}),
    "automated-qa": frozenset({"generated", "vision-qa", "revise", "rejected"}),
    "vision-qa": frozenset({"accepted", "revise", "rejected"}),
    "accepted": frozenset({"tiled", "revise"}),
    "revise": frozenset({"inputs-ready", "generated", "rejected"}),
    "rejected": frozenset({"planned"}),
    "tiled": frozenset({"staging", "revise"}),
    "staging": frozenset({"published", "tiled", "revise"}),
    "published": frozenset({"staging", "revise"}),
}

STATE_ORDER = {state: index for index, state in enumerate(STATES)}
ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")


class ValidationFailure(Exception):
    """Raised when an input artifact cannot be validated."""


def load_json(path: Path) -> Any:
    """Load UTF-8 JSON and convert common IO/parse failures into clear messages."""

    def reject_nonstandard_constant(value: str) -> None:
        raise ValueError(f"non-standard numeric constant {value!r}")

    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle, parse_constant=reject_nonstandard_constant)
    except FileNotFoundError as exc:
        raise ValidationFailure(f"File not found: {path}") from exc
    except OSError as exc:
        raise ValidationFailure(f"Cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationFailure(
            f"Invalid JSON in {path} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except ValueError as exc:
        raise ValidationFailure(f"Invalid JSON in {path}: {exc}") from exc


def dump_json(path: Path, value: Any) -> None:
    """Write stable UTF-8 JSON suitable for review and source control."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def parse_rfc3339(value: str) -> datetime:
    """Parse a timezone-aware RFC 3339 timestamp."""

    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"not a valid RFC 3339 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value!r}")
    return parsed


def utc_now() -> str:
    """Return the current UTC time in stable RFC 3339 form."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def transition_allowed(current: str, target: str) -> bool:
    """Return whether ``current -> target`` is part of the production workflow."""

    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def validate_history(job: dict[str, Any], label: str) -> list[str]:
    """Validate one job's state history and its current-state projection."""

    errors: list[str] = []
    history = job.get("history")
    if not isinstance(history, list) or not history:
        return [f"{label}.history must be a non-empty array"]

    states: list[str] = []
    timestamps: list[datetime] = []
    for index, event in enumerate(history):
        event_label = f"{label}.history[{index}]"
        if not isinstance(event, dict):
            errors.append(f"{event_label} must be an object")
            continue
        state = event.get("state")
        if not isinstance(state, str) or state not in STATES:
            errors.append(f"{event_label}.state is invalid: {state!r}")
        else:
            states.append(state)
        at = event.get("at")
        if not isinstance(at, str):
            errors.append(f"{event_label}.at must be an RFC 3339 string")
        else:
            try:
                timestamps.append(parse_rfc3339(at))
            except ValueError as exc:
                errors.append(f"{event_label}.at {exc}")

    if states and states[0] != "planned":
        errors.append(f"{label}.history must start at 'planned', found {states[0]!r}")
    if len(states) == len(history):
        for index, (current, target) in enumerate(zip(states, states[1:]), start=1):
            if not transition_allowed(current, target):
                errors.append(
                    f"{label}.history[{index - 1}:{index}] contains illegal transition "
                    f"{current!r} -> {target!r}"
                )
        status = job.get("status")
        if status != states[-1]:
            errors.append(
                f"{label}.status is {status!r}, but the final history state is {states[-1]!r}"
            )
    if len(timestamps) == len(history):
        for index, (earlier, later) in enumerate(zip(timestamps, timestamps[1:]), start=1):
            if later < earlier:
                errors.append(
                    f"{label}.history[{index}].at is earlier than the preceding event"
                )
    return errors


def _path_values(job: dict[str, Any]) -> Iterable[tuple[str, str, str, str]]:
    """Yield ``(field, value, minimum_state, kind)`` for materialized artifacts."""

    inputs = job.get("inputs")
    if isinstance(inputs, list):
        for index, item in enumerate(inputs):
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                yield f"inputs[{index}].path", item["path"], "inputs-ready", "file"

    generation = job.get("generation")
    if isinstance(generation, dict):
        for field in ("prompt_path", "control_image_path", "parent_image_path"):
            if isinstance(generation.get(field), str):
                yield f"generation.{field}", generation[field], "inputs-ready", "file"

    master = job.get("master")
    if isinstance(master, dict) and isinstance(master.get("path"), str):
        yield "master.path", master["path"], "generated", "file"

    qa = job.get("qa")
    if isinstance(qa, dict):
        for section, minimum_state in (("automated", "automated-qa"), ("vision", "vision-qa")):
            details = qa.get(section)
            if isinstance(details, dict) and isinstance(details.get("report_path"), str):
                yield (
                    f"qa.{section}.report_path",
                    details["report_path"],
                    minimum_state,
                    "file",
                )

    output = job.get("output")
    if isinstance(output, dict):
        if isinstance(output.get("tiles_path"), str):
            yield "output.tiles_path", output["tiles_path"], "tiled", "directory"
        if isinstance(output.get("metadata_path"), str):
            yield "output.metadata_path", output["metadata_path"], "tiled", "file"


def _state_reached(status: str, minimum_state: str) -> bool:
    """Determine whether a state requires an artifact to exist.

    Branch states (``revise``/``rejected``) deliberately do not imply that later
    publication artifacts exist.
    """

    if status in {"revise", "rejected"}:
        return minimum_state in {"inputs-ready", "generated"} and status != "rejected"
    return STATE_ORDER.get(status, -1) >= STATE_ORDER[minimum_state]


def validate_manifest_semantics(
    manifest: dict[str, Any],
    *,
    manifest_path: Path | None = None,
    check_files: bool = False,
) -> list[str]:
    """Validate cross-record invariants not expressible cleanly in JSON Schema."""

    errors: list[str] = []
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list):
        return ["jobs must be an array"]

    job_by_id: dict[str, dict[str, Any]] = {}
    for index, job in enumerate(jobs):
        label = f"jobs[{index}]"
        if not isinstance(job, dict):
            continue
        job_id = job.get("id")
        if not isinstance(job_id, str):
            continue
        if job_id in job_by_id:
            errors.append(f"duplicate job id: {job_id!r}")
        else:
            job_by_id[job_id] = job
        errors.extend(validate_history(job, label))

        status = job.get("status")
        master = job.get("master")
        qa = job.get("qa") if isinstance(job.get("qa"), dict) else {}
        automated = qa.get("automated") if isinstance(qa.get("automated"), dict) else None
        vision = qa.get("vision") if isinstance(qa.get("vision"), dict) else None
        output = job.get("output")
        acceptance_threshold = job.get("acceptance_threshold", 90)

        states_requiring_master = {
            "generated",
            "automated-qa",
            "vision-qa",
            "accepted",
            "tiled",
            "staging",
            "published",
        }
        if status in states_requiring_master and not isinstance(master, dict):
            errors.append(f"{label}.master is required in state {status!r}")

        if status in {"vision-qa", "accepted", "tiled", "staging", "published"}:
            if automated is None:
                errors.append(f"{label}.qa.automated is required before state {status!r}")
            elif automated.get("status") != "passed":
                errors.append(f"{label}.qa.automated.status must be 'passed' before {status!r}")

        if status in {"accepted", "tiled", "staging", "published"}:
            if vision is None:
                errors.append(f"{label}.qa.vision is required before state {status!r}")
            else:
                if vision.get("decision") != "accepted":
                    errors.append(f"{label}.qa.vision.decision must be 'accepted' before {status!r}")
                score = vision.get("score")
                if (
                    isinstance(acceptance_threshold, int)
                    and isinstance(score, int)
                    and score < acceptance_threshold
                ):
                    errors.append(
                        f"{label}.qa.vision.score {score} is below acceptance_threshold "
                        f"{acceptance_threshold}"
                    )

        if status in {"tiled", "staging", "published"} and not isinstance(output, dict):
            errors.append(f"{label}.output is required in state {status!r}")

        bounds = job.get("bounds")
        if isinstance(bounds, dict):
            west, south, east, north = (
                bounds.get("west"),
                bounds.get("south"),
                bounds.get("east"),
                bounds.get("north"),
            )
            if all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in (west, south, east, north)
            ):
                if west >= east:
                    errors.append(f"{label}.bounds.west must be less than east")
                if south >= north:
                    errors.append(f"{label}.bounds.south must be less than north")

        zoom = job.get("zoom")
        if isinstance(zoom, dict):
            minimum, maximum, native = zoom.get("min"), zoom.get("max"), zoom.get("native")
            if all(isinstance(value, int) and not isinstance(value, bool) for value in (minimum, maximum, native)):
                if not minimum <= native <= maximum:
                    errors.append(f"{label}.zoom must satisfy min <= native <= max")

    for index, job in enumerate(jobs):
        if not isinstance(job, dict) or not isinstance(job.get("id"), str):
            continue
        label = f"jobs[{index}]"
        job_id = job["id"]
        related: list[tuple[str, Any]] = [("parent_job_id", job.get("parent_job_id"))]
        neighbors = job.get("neighbors")
        if isinstance(neighbors, dict):
            related.extend((f"neighbors.{direction}", value) for direction, value in neighbors.items())
        for field, referenced in related:
            if referenced is None:
                continue
            if referenced == job_id:
                errors.append(f"{label}.{field} cannot reference itself")
            elif isinstance(referenced, str) and referenced not in job_by_id:
                errors.append(f"{label}.{field} references unknown job {referenced!r}")

    # Detect parent cycles separately so a valid-looking graph cannot recurse forever.
    for job_id in job_by_id:
        seen: set[str] = set()
        current: str | None = job_id
        while current in job_by_id:
            if current in seen:
                errors.append(f"parent_job_id cycle detected from job {job_id!r}")
                break
            seen.add(current)
            parent = job_by_id[current].get("parent_job_id")
            current = parent if isinstance(parent, str) else None

    if check_files and manifest_path is not None:
        # Manifest paths are repository-relative POSIX paths. Resolving them from
        # the manifest's own directory makes sibling paths such as
        # ``world/map-production/masters/...`` impossible to validate and behaves
        # differently depending on where the manifest happens to be stored.
        base_dir = REPO_ROOT.resolve()
        style_guide_path = manifest.get("style_guide_path")
        if isinstance(style_guide_path, str):
            style_resolved = (base_dir / style_guide_path).resolve()
            try:
                style_resolved.relative_to(base_dir)
            except ValueError:
                errors.append(
                    "style_guide_path must resolve inside the repository: "
                    f"{style_guide_path}"
                )
            else:
                if not style_resolved.is_file():
                    errors.append(
                        f"style_guide_path does not exist as a file: {style_guide_path}"
                    )
        for index, job in enumerate(jobs):
            if not isinstance(job, dict):
                continue
            status = job.get("status")
            if not isinstance(status, str):
                continue
            for field, raw_path, minimum_state, expected_kind in _path_values(job):
                if not _state_reached(status, minimum_state):
                    continue
                candidate = Path(raw_path)
                resolved = candidate.resolve() if candidate.is_absolute() else (base_dir / candidate).resolve()
                try:
                    resolved.relative_to(base_dir)
                except ValueError:
                    errors.append(
                        f"jobs[{index}].{field} must resolve inside the repository: {raw_path}"
                    )
                    continue
                if not resolved.exists():
                    errors.append(f"jobs[{index}].{field} does not exist: {raw_path}")
                elif expected_kind == "file" and not resolved.is_file():
                    errors.append(f"jobs[{index}].{field} must be a file: {raw_path}")
                elif expected_kind == "directory" and not resolved.is_dir():
                    errors.append(f"jobs[{index}].{field} must be a directory: {raw_path}")

    return errors
