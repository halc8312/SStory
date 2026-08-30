#!/usr/bin/env python3
"""Create evidence-empty Golden-v2 Root or blind review drafts.

The generated files are checklists, not receipts.  Every Vision field remains
unanswered, every score remains null, and every decision remains pending until
a human reviewer actually inspects the bound views and edits the draft.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import create_qa_report
import emit_style_candidate_k3_golden_v2 as emitter
import promote_style_candidate_k3_golden_v2 as promotion
from production_common import REPO_ROOT, load_json, utc_now
from release_bound_artifact import BoundArtifactError, bind_file
from release_path_safety import (
    ReleasePathError,
    canonical_repo_relative,
    require_trackable_path,
)
from reviewer_identity import canonical_reviewer_identity
from validate_manifest import schema_errors


ROOT_REVIEW_MODE = "root-authority"
BLIND_AUDIT_VIEWS = (
    ("blind-audit-overview", "Anonymous packet: overall composition"),
    ("blind-audit-native-integrity", "Anonymous packet: native-pixel integrity"),
    ("blind-audit-scale-progression", "Anonymous packet: 25%/50% scale progression"),
    (
        "blind-audit-highland-information-gain",
        "Anonymous packet: 200%/400% highland information gain",
    ),
    ("blind-audit-artifact-sweep", "Anonymous packet: immediate-failure sweep"),
)
FAILURE_LABELS = {
    "eight-system-topology": "Exactly eight distinct ridge systems remain legible",
    "side-view-or-shared-projection": "No side view or shared-projection collapse",
    "panel-seam-or-body-halo": "No panel seam or body halo",
    "white-particle-pill-hole-or-crater": "No white particle, pill, hole, or crater",
    "root-river-vein-fingerprint-or-contour": (
        "No root, river-vein, fingerprint, or contour substitution"
    ),
    "fern-fishbone-dash-bundle-or-repetition": (
        "No fern, fishbone, dash bundle, or repetition artifact"
    ),
    "no-200-to-400-information-gain": "200% to 400% adds visible information",
    "protected-geometry-difference": "No protected-geometry difference",
}


class GoldenV2TemplateError(RuntimeError):
    """Raised before a misleading or misplaced review draft can be written."""


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or os.path.lexists(path):
        raise GoldenV2TemplateError(f"refusing to replace review draft: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(_json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def _failure_drafts() -> list[dict[str, Any]]:
    if set(FAILURE_LABELS) != set(promotion.PHASE4_IMMEDIATE_FAILURE_IDS):
        raise GoldenV2TemplateError("Phase 4 immediate-failure labels drifted")
    return [
        {
            "id": identifier,
            "detected": None,
            "evidence": "",
        }
        for identifier in promotion.PHASE4_IMMEDIATE_FAILURE_IDS
    ]


def _assert_temp_output(path: Path) -> Path:
    resolved, _ = canonical_repo_relative(path, label="Root review draft")
    temp_root = (REPO_ROOT / "tmp/map-production").resolve()
    try:
        relative = resolved.relative_to(temp_root)
    except ValueError as exc:
        raise GoldenV2TemplateError(
            f"Root review draft must stay under {temp_root}"
        ) from exc
    if not relative.parts:
        raise GoldenV2TemplateError("Root review draft may not equal the TEMP root")
    return resolved


def create_root_template(
    *, emission_path: Path, reviewer: str, output: Path
) -> dict[str, Any]:
    reviewer = reviewer.strip()
    if not reviewer:
        raise GoldenV2TemplateError("Root reviewer identity must be non-empty")
    document = emitter._self_validate(emission_path)
    views = document["views"]
    result = {
        "schema_version": "1.0.0",
        "job_id": promotion.JOB_ID,
        "created_at": utc_now(),
        "reviewer": reviewer,
        "status": "draft",
        "review_mode": ROOT_REVIEW_MODE,
        "candidate": {
            "path": document["candidate"]["path"],
            "sha256": document["candidate"]["sha256"],
        },
        "native": {
            "path": views["native"]["path"],
            "sha256": views["native"]["sha256"],
        },
        "review_views": [
            {
                "id": name,
                "path": views[name]["path"],
                "sha256": views[name]["sha256"],
                "complete": False,
                "evidence": "",
            }
            for name in promotion.VIEW_ORDER
        ],
        "immediate_failures": _failure_drafts(),
        "acceptance_threshold": promotion.ACCEPTANCE_THRESHOLD,
        "total_score": None,
        "decision": "pending",
        "authorizes_blind_review": False,
        "golden_reference": False,
        "acceptance_inferred": False,
        "summary": "",
    }
    if set(result) != set(promotion.ROOT_REVIEW_REQUIRED_KEYS):
        raise GoldenV2TemplateError("Root review draft key set drifted")
    if [item["id"] for item in result["immediate_failures"]] != list(
        promotion.PHASE4_IMMEDIATE_FAILURE_IDS
    ):
        raise GoldenV2TemplateError("Root immediate-failure order drifted")
    destination = _assert_temp_output(output)
    _write_exclusive(destination, result)
    return {
        "status": "draft",
        "review_mode": ROOT_REVIEW_MODE,
        "path": destination.relative_to(REPO_ROOT).as_posix(),
        "evidence_created": False,
        "decision": "pending",
    }


def _load_blind_packet(path: Path) -> tuple[Any, dict[str, Any]]:
    try:
        packet = bind_file(path, label="blind review packet", trackable=True)
    except (BoundArtifactError, ReleasePathError) as exc:
        raise GoldenV2TemplateError(str(exc)) from exc
    if packet.path.stem != packet.sha256:
        raise GoldenV2TemplateError(
            "blind packet filename must equal its content SHA-256"
        )
    try:
        document = packet.json_object()
    except BoundArtifactError as exc:
        raise GoldenV2TemplateError(str(exc)) from exc
    if set(document) != {"schema_version", "views"} or document.get(
        "schema_version"
    ) != "1.0.0":
        raise GoldenV2TemplateError("blind packet structure changed")
    folded = packet.data.decode("utf-8").casefold()
    if any(
        token in folded
        for token in ("candidate", "lineage", "donor", "control", "generation")
    ):
        raise GoldenV2TemplateError("blind packet discloses candidate lineage")
    views = document["views"]
    if not isinstance(views, list) or len(views) != len(
        promotion.BLIND_PACKET_VIEW_IDS
    ):
        raise GoldenV2TemplateError("blind packet must contain exactly five views")
    digests: set[str] = set()
    for expected, record in zip(promotion.BLIND_PACKET_VIEW_IDS, views):
        if not isinstance(record, dict) or set(record) != {"id", "path", "sha256"}:
            raise GoldenV2TemplateError("blind packet view structure changed")
        if record["id"] != expected:
            raise GoldenV2TemplateError("blind packet view order changed")
        try:
            view = bind_file(
                record["path"], label=f"blind packet view {expected}", trackable=True
            )
        except (BoundArtifactError, ReleasePathError) as exc:
            raise GoldenV2TemplateError(str(exc)) from exc
        if view.sha256 != record["sha256"]:
            raise GoldenV2TemplateError(f"blind packet view {expected} SHA changed")
        promotion._validate_anonymous_view_png(view, view_id=expected)
        digests.add(view.sha256)
    if len(digests) != len(promotion.BLIND_PACKET_VIEW_IDS):
        raise GoldenV2TemplateError("blind packet view PNGs must be distinct")
    return packet, document


def _blind_review_views() -> list[dict[str, Any]]:
    labels = {
        "native": "Anonymous native view",
        "full25": "Anonymous full view at 25%",
        "full50": "Anonymous full view at 50%",
        "highland200": "Anonymous highland crop at 200%",
        "highland400": "Anonymous highland crop at 400%",
    }
    pairs = [(name, labels[name]) for name in promotion.BLIND_PACKET_VIEW_IDS]
    pairs.extend(BLIND_AUDIT_VIEWS)
    return [
        {
            "id": identifier,
            "label": label,
            "complete": False,
            "evidence": "",
            "notes": "",
        }
        for identifier, label in pairs
    ]


def build_blind_report(*, packet: Any, role: str, reviewer_id: str) -> dict[str, Any]:
    """Build a schema-valid draft from an already validated packet binding."""

    if role not in {"a", "b"}:
        raise GoldenV2TemplateError("blind role must be a or b")
    normalized_id = canonical_reviewer_identity(reviewer_id)
    reviewer = f"independent-vision-review-{role}/{normalized_id}"
    failures = [
        {
            "id": identifier,
            "label": FAILURE_LABELS[identifier],
            "detected": None,
            "evidence": "",
        }
        for identifier in promotion.PHASE4_IMMEDIATE_FAILURE_IDS
    ]
    report = {
        "schema_version": "1.0.0",
        "job_id": promotion.JOB_ID,
        "image_path": packet.relative,
        "image_sha256": packet.sha256,
        "created_at": utc_now(),
        "reviewer": reviewer,
        "status": "draft",
        "golden_reference": True,
        "review_mode": "blind-independent",
        "acceptance_threshold": promotion.ACCEPTANCE_THRESHOLD,
        "review_views": _blind_review_views(),
        "immediate_failures": failures,
        "scores": [
            {
                "id": identifier,
                "label": label,
                "maximum": maximum,
                "score": None,
                "notes": "",
            }
            for identifier, label, maximum in create_qa_report.SCORE_AXES
        ],
        "total_score": None,
        "decision": "pending",
        "summary": "",
        "required_changes": [],
    }
    errors = schema_errors(report, load_json(promotion.QA_REPORT_SCHEMA))
    if errors:
        raise GoldenV2TemplateError(
            "blind review draft does not satisfy QA schema: " + "; ".join(errors)
        )
    if len(report["review_views"]) != 10:
        raise GoldenV2TemplateError("blind review draft must contain exactly ten views")
    if [item["id"] for item in failures] != list(
        promotion.PHASE4_IMMEDIATE_FAILURE_IDS
    ):
        raise GoldenV2TemplateError("blind immediate-failure order drifted")
    return report


def create_blind_template(
    *, packet_path: Path, role: str, reviewer_id: str, output: Path
) -> dict[str, Any]:
    packet, _ = _load_blind_packet(packet_path)
    destination, relative = require_trackable_path(
        output,
        label="blind review draft",
        must_exist=False,
        require_file=True,
    )
    if "automated" in (part.casefold() for part in PurePosixPath(relative).parts):
        raise GoldenV2TemplateError("blind review draft may not be stored under automated")
    report = build_blind_report(packet=packet, role=role, reviewer_id=reviewer_id)
    _write_exclusive(destination, report)
    return {
        "status": "draft",
        "review_mode": "blind-independent",
        "role": role,
        "path": relative,
        "packet_sha256": packet.sha256,
        "evidence_created": False,
        "decision": "pending",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    root = commands.add_parser("root", help="create a TEMP Root review draft")
    root.add_argument("--emission", type=Path, required=True)
    root.add_argument("--reviewer", required=True)
    root.add_argument("--output", type=Path, required=True)
    blind = commands.add_parser("blind", help="create a persistent blind review draft")
    blind.add_argument("--packet", type=Path, required=True)
    blind.add_argument("--role", choices=("a", "b"), required=True)
    blind.add_argument("--reviewer-id", required=True)
    blind.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "root":
            result = create_root_template(
                emission_path=args.emission,
                reviewer=args.reviewer,
                output=args.output,
            )
        else:
            result = create_blind_template(
                packet_path=args.packet,
                role=args.role,
                reviewer_id=args.reviewer_id,
                output=args.output,
            )
    except (
        GoldenV2TemplateError,
        emitter.GoldenV2EmissionError,
        promotion.K3GoldenPromotionV2Error,
        BoundArtifactError,
        ReleasePathError,
        OSError,
        ValueError,
    ) as exc:
        print(f"Golden-v2 review template failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
