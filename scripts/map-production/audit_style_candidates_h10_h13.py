#!/usr/bin/env python3
"""Record H10-H13 raw ImageGen trials against the unchanged H4 gates.

These candidates were rejected, so no adopted ``final`` image is minted.  The
script treats an expected gate failure as evidence to preserve, never as a
pass.  Semantic repetition and plan-view judgments remain owned by Vision QA.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

import audit_style_candidate_h4 as h4


REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_B1 = h4.DEFAULT_REFERENCE_B1
VISION_SCHEMA = h4.DEFAULT_VISION_SCHEMA
AUTOMATED_REPORT_DIR = REPO_ROOT / "world/map-production/qa/automated"


@dataclass(frozen=True)
class CandidateSpec:
    """Immutable provenance and expected H4-gate result for one raw trial."""

    number: int
    slug: str
    raw_sha256: str
    prompt_sha256: str
    receipt_sha256: str
    required_prompt_phrases: tuple[str, ...]
    input_artifacts: tuple[tuple[str, str], ...]
    expected_failed_gates: tuple[str, ...]

    @property
    def job_id(self) -> str:
        return f"style-candidate-h-v{self.number}-{self.slug}"

    @property
    def raw_path(self) -> Path:
        return REPO_ROOT / f"world/map-production/candidates/{self.job_id}-raw.png"

    @property
    def prompt_path(self) -> Path:
        return REPO_ROOT / f"world/map-production/prompts/{self.job_id}.generation.txt"

    @property
    def receipt_path(self) -> Path:
        return (
            REPO_ROOT
            / f"world/map-production/prompts/{self.job_id}.generation-receipt.json"
        )

    @property
    def report_path(self) -> Path:
        return AUTOMATED_REPORT_DIR / f"{self.job_id}.json"


CANDIDATES: dict[int, CandidateSpec] = {
    10: CandidateSpec(
        number=10,
        slug="material-restoration",
        raw_sha256="543cb36aa37b6d3f572f7d7379636205ec60760c73157caa0235034dad08d32e",
        prompt_sha256="2766465bed59fd98cafac8937aa816043eaa423f3e035689d652f0d0fc329bda",
        receipt_sha256="113c50901b52e1b6a8c4024f27212fd7f9057643b9c43babaa29911be60c8636",
        required_prompt_phrases=(
            "Exact 90-degree overhead cartographic plan view",
            "No labels, letters, numbers, pseudo-writing",
            "1536 x 1024 RGB map image",
        ),
        input_artifacts=(
            (
                "world/map-production/candidates/style-candidate-h-v9-dense-flat-plan.png",
                "bd813e93287b15fe12e654ca5d28633a6902bbbdb3c6d81b0c3e69816a7b2580",
            ),
            (
                "world/map-production/candidates/style-candidate-b-v1.png",
                h4.EXPECTED_SHA256["reference_b1"],
            ),
        ),
        expected_failed_gates=("palette_continuity_with_b1",),
    ),
    11: CandidateSpec(
        number=11,
        slug="colour-calibration",
        raw_sha256="32175b57fa82891045a3f8ffa70c3da134b33e38a790db62b14d11c0256cda75",
        prompt_sha256="7534a27b2142dc3ff8a353a40af00b01e5455fe0c2a2e45fb4342ee53cfad990",
        receipt_sha256="d47fe3aa53ffa223902fc2b41b1b9c280e73bfbf0f39bd25661c770b9a171790",
        required_prompt_phrases=(
            "strict 90-degree orthographic flat-plan appearance",
            "text, pseudo-writing, labels",
            "1536 x 1024 RGB image",
        ),
        input_artifacts=(
            (
                "world/map-production/candidates/style-candidate-h-v10-material-restoration-raw.png",
                "543cb36aa37b6d3f572f7d7379636205ec60760c73157caa0235034dad08d32e",
            ),
            (
                "world/map-production/candidates/style-candidate-b-v1.png",
                h4.EXPECTED_SHA256["reference_b1"],
            ),
        ),
        expected_failed_gates=(),
    ),
    12: CandidateSpec(
        number=12,
        slug="organic-plan-material",
        raw_sha256="13633f90ea8f9a1fda7a0102229b19402e02a7144ad7238bdc1ba558f1d01417",
        prompt_sha256="846647c628f7bf429d94792f7d1e257628b1d7d7edd1ebc6f4b2373366285f7f",
        receipt_sha256="7cbd9da17aae6a6deff9c19144ba87e2499b257e6f0e919468df1cc23ed1056e",
        required_prompt_phrases=(
            "exact 90-degree orthographic view",
            "text, pseudo-writing, labels",
            "1536 x 1024 RGB image",
        ),
        input_artifacts=(
            (
                "world/map-production/candidates/style-candidate-h-v11-colour-calibration-raw.png",
                "32175b57fa82891045a3f8ffa70c3da134b33e38a790db62b14d11c0256cda75",
            ),
        ),
        expected_failed_gates=(
            "palette_continuity_with_b1",
            "downsample_readability_proxy",
        ),
    ),
    13: CandidateSpec(
        number=13,
        slug="forest-material-refinement",
        raw_sha256="0b2083904607287c14a8b10e3d111f5d500c2904a8b1e9894bb2ca5041e10aa2",
        prompt_sha256="4f2606f5fe684df35d0286fcf83cbf2d5b79c46b221668f375826d3720977178",
        receipt_sha256="855d8859a5f94df8a1c64471a54aaf19c9b380404b7514da80cfa6395e12d687",
        required_prompt_phrases=(
            "exact 90-degree plan view",
            "text, pseudo-writing, labels",
            "1536 x 1024 RGB image",
        ),
        input_artifacts=(
            (
                "world/map-production/candidates/style-candidate-h-v12-organic-plan-material-raw.png",
                "13633f90ea8f9a1fda7a0102229b19402e02a7144ad7238bdc1ba558f1d01417",
            ),
            (
                "world/map-production/candidates/style-candidate-h-v11-colour-calibration-raw.png",
                "32175b57fa82891045a3f8ffa70c3da134b33e38a790db62b14d11c0256cda75",
            ),
        ),
        expected_failed_gates=(
            "palette_continuity_with_b1",
            "downsample_readability_proxy",
        ),
    ),
}


class CandidateAuditError(ValueError):
    """Raised when locked provenance or expected gate evidence changes."""


def _assert_input(path: Path, expected_hash: str, label: str) -> None:
    try:
        h4._assert_input(path, expected_hash, label)
    except h4.H4AuditError as exc:
        raise CandidateAuditError(str(exc)) from exc


def _repo_path(value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or "\\" in value or ":" in value or ".." in pure.parts:
        raise CandidateAuditError(f"receipt path must be repo-relative: {value!r}")
    return REPO_ROOT.joinpath(*pure.parts)


def _validate_receipt(spec: CandidateSpec) -> dict[str, Any]:
    try:
        receipt = json.loads(spec.receipt_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateAuditError(f"invalid UTF-8 receipt for H{spec.number}") from exc

    limitations = receipt.get("provenance_limitations")
    if not isinstance(limitations, dict):
        raise CandidateAuditError(f"H{spec.number} receipt lacks provenance limitations")
    expected_unknowns = {
        "exact_image_model_identifier_available": False,
        "model": "unknown",
        "model_snapshot_available": False,
        "model_snapshot": "unavailable",
        "generation_identifier_available": False,
        "generation_id": "unavailable",
        "generation_timestamp_utc": None,
    }
    for key, expected in expected_unknowns.items():
        if limitations.get(key) != expected:
            raise CandidateAuditError(
                f"H{spec.number} receipt must preserve {key}={expected!r}"
            )

    prompt = receipt.get("prompt")
    output = receipt.get("output")
    inputs = receipt.get("inputs")
    if not isinstance(prompt, dict) or not isinstance(output, dict):
        raise CandidateAuditError(f"H{spec.number} receipt prompt/output malformed")
    if not isinstance(inputs, list):
        raise CandidateAuditError(f"H{spec.number} receipt inputs malformed")
    if prompt.get("path") != h4._relative(spec.prompt_path):
        raise CandidateAuditError(f"H{spec.number} receipt prompt path mismatch")
    if prompt.get("sha256") != spec.prompt_sha256:
        raise CandidateAuditError(f"H{spec.number} receipt prompt hash mismatch")
    if output.get("path") != h4._relative(spec.raw_path):
        raise CandidateAuditError(f"H{spec.number} receipt output path mismatch")
    if output.get("sha256") != spec.raw_sha256:
        raise CandidateAuditError(f"H{spec.number} receipt output hash mismatch")
    if output.get("accepted_as_final") is not False:
        raise CandidateAuditError(f"H{spec.number} rejected raw must not be final")

    observed_inputs = tuple(
        (item.get("path"), item.get("sha256"))
        for item in inputs
        if isinstance(item, dict)
    )
    if observed_inputs != spec.input_artifacts:
        raise CandidateAuditError(f"H{spec.number} receipt input chain mismatch")

    path_values = [prompt["path"], output["path"]]
    path_values.extend(item["path"] for item in inputs)
    for value in path_values:
        if not isinstance(value, str):
            raise CandidateAuditError(f"H{spec.number} receipt contains non-string path")
        resolved = _repo_path(value)
        if not resolved.is_file():
            raise CandidateAuditError(f"H{spec.number} receipt input missing: {value}")
    return receipt


def _image_contract(
    raw_record: dict[str, Any], reference_record: dict[str, Any]
) -> dict[str, Any]:
    required = {
        "format": "PNG",
        "mode": "RGB",
        "width": h4.EXPECTED_SIZE[0],
        "height": h4.EXPECTED_SIZE[1],
        "bit_depth": 8,
        "png_color_type": 2,
        "alpha_or_transparency_present": False,
    }
    records = {"raw": raw_record, "reference_b1": reference_record}
    record_results = {
        label: all(record[key] == value for key, value in required.items())
        for label, record in records.items()
    }
    profile_matches = h4._profile_signature(raw_record) == h4._profile_signature(
        reference_record
    )
    return {
        "passed": all(record_results.values()) and profile_matches,
        "required": required,
        "records_passed": record_results,
        "alpha_free": not raw_record["alpha_or_transparency_present"],
        "profile_matches_b1": profile_matches,
        "profile_interpretation": (
            "untagged RGB matching B1"
            if not raw_record["profile_chunk_types"]
            and not raw_record["icc_profile_present"]
            else "embedded profile state matches B1"
        ),
        "images": records,
    }


def audit_candidate(
    spec: CandidateSpec, *, report_path: Path | None = None, replace: bool = False
) -> dict[str, Any]:
    """Audit one locked raw trial and emit deterministic rejection evidence."""

    destination = report_path or spec.report_path
    if destination.exists() and not replace:
        raise CandidateAuditError(f"refusing to overwrite existing output: {destination}")

    locked_inputs = (
        (spec.raw_path, spec.raw_sha256, f"H{spec.number} raw"),
        (spec.prompt_path, spec.prompt_sha256, f"H{spec.number} generation prompt"),
        (spec.receipt_path, spec.receipt_sha256, f"H{spec.number} generation receipt"),
        (
            REFERENCE_B1,
            h4.EXPECTED_SHA256["reference_b1"],
            "Candidate B1 reference",
        ),
        (
            VISION_SCHEMA,
            h4.EXPECTED_SHA256["vision_schema"],
            "Vision QA schema",
        ),
    )
    for path, expected_hash, label in locked_inputs:
        _assert_input(path, expected_hash, label)
    for relative_path, expected_hash in spec.input_artifacts:
        _assert_input(_repo_path(relative_path), expected_hash, relative_path)

    try:
        prompt_text = spec.prompt_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise CandidateAuditError(
            f"H{spec.number} generation prompt must be valid UTF-8"
        ) from exc
    missing_phrases = [
        phrase for phrase in spec.required_prompt_phrases if phrase not in prompt_text
    ]
    if missing_phrases:
        raise CandidateAuditError(
            f"H{spec.number} prompt lacks locked phrases: "
            + ", ".join(missing_phrases)
        )
    _validate_receipt(spec)

    try:
        raw_record, raw_image = h4.inspect_png(spec.raw_path)
        reference_record, reference_image = h4.inspect_png(REFERENCE_B1)
    except h4.H4AuditError as exc:
        raise CandidateAuditError(str(exc)) from exc
    try:
        image_contract = _image_contract(raw_record, reference_record)
        boundary = h4.boundary_metrics(raw_image)
        palette = h4.palette_continuity_metrics(raw_image, reference_image)
        repetition = h4.exact_repetition_metrics(raw_image)
        downsample = h4.downsample_readability_metrics(raw_image)
    finally:
        raw_image.close()
        reference_image.close()

    automated_gates = {
        "sha256_locked_inputs": True,
        "image_contract_alpha_profile": image_contract["passed"],
        "boundary_proxy": boundary["passed"],
        "palette_continuity_with_b1": palette["passed"],
        "no_large_exact_repetition_proxy": repetition["passed"],
        "downsample_readability_proxy": downsample["passed"],
    }
    failed_gates = tuple(
        name for name, passed in automated_gates.items() if not passed
    )
    if failed_gates != spec.expected_failed_gates:
        raise CandidateAuditError(
            f"H{spec.number} gate evidence changed: expected "
            f"{list(spec.expected_failed_gates)}, got {list(failed_gates)}"
        )
    status = "failed" if failed_gates else "passed"
    decision = (
        "automated-gates-failed-rejected"
        if failed_gates
        else "automated-gates-passed-pending-vision"
    )
    report = {
        "schema_version": "1.0.0",
        "id": f"{spec.job_id}-automated-audit",
        "status": status,
        "scope": "automated artifact and H4 raster proxies only",
        "decision": decision,
        "failed_gates": list(failed_gates),
        "expected_rejection_evidence": True,
        "generated_by": h4._artifact(Path(__file__).resolve()),
        "audit_engine": {
            **h4._artifact(Path(h4.__file__).resolve()),
            "threshold_policy": "unchanged H4 absolute gates; no threshold drift",
            "raw_final_identity": {
                "applicable": False,
                "passed": None,
                "reason": (
                    "This is a rejected raw ImageGen trial. No adopted final file was "
                    "minted, so raw/final identity is intentionally not claimed."
                ),
            },
        },
        "artifacts": {
            "raw": h4._artifact(spec.raw_path),
            "prompt": {
                **h4._artifact(spec.prompt_path),
                "utf8": True,
                "required_phrases_present": True,
            },
            "generation_receipt": h4._artifact(spec.receipt_path),
            "reference_b1": h4._artifact(REFERENCE_B1),
        },
        "identity": {
            "passed": True,
            "raw_only_rejected_trial": True,
            "adopted_final_exists": False,
            "locked_sha256": {
                "raw": spec.raw_sha256,
                "prompt": spec.prompt_sha256,
                "generation_receipt": spec.receipt_sha256,
                "reference_b1": h4.EXPECTED_SHA256["reference_b1"],
                "vision_schema": h4.EXPECTED_SHA256["vision_schema"],
            },
        },
        "image_contract": image_contract,
        "boundary": boundary,
        "palette_continuity": palette,
        "exact_repetition": repetition,
        "downsample_readability": downsample,
        "automated_gates": automated_gates,
        "vision_handoff": h4._vision_handoff(VISION_SCHEMA),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        choices=("10", "11", "12", "13", "all"),
        default="all",
    )
    parser.add_argument("--report-dir", type=Path, default=AUTOMATED_REPORT_DIR)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace existing automated reports after re-running every gate",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    numbers = tuple(CANDIDATES) if args.candidate == "all" else (int(args.candidate),)
    try:
        for number in numbers:
            spec = CANDIDATES[number]
            report = audit_candidate(
                spec,
                report_path=args.report_dir.resolve() / f"{spec.job_id}.json",
                replace=args.replace,
            )
            palette = report["palette_continuity"]
            print(
                f"H{number} evidence recorded: automated_status={report['status']} "
                f"failed_gates={','.join(report['failed_gates']) or 'none'} "
                f"rgb_intersection={palette['rgb_histogram_intersection']}"
            )
    except (CandidateAuditError, OSError, ValueError) as exc:
        print(f"H10-H13 audit could not run: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
