#!/usr/bin/env python3
"""Prove that Candidate D v4 removes the reviewed route-like marks only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageOps

import extract_candidate_d_v3_mark_mask as mark_mask


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = mark_mask.DEFAULT_BASE
DEFAULT_BEFORE = mark_mask.DEFAULT_CANDIDATE
DEFAULT_AFTER = REPO_ROOT / "world/map-production/candidates/style-candidate-d-v4-erase-route-marks.png"
DEFAULT_CONTROL = mark_mask.DEFAULT_CONTROL
DEFAULT_MASK = mark_mask.DEFAULT_MASK
DEFAULT_COMPOSITE_REPORT = (
    REPO_ROOT / "world/map-production/qa/automated/style-candidate-d-v4-composite.json"
)
DEFAULT_REPORT = (
    REPO_ROOT / "world/map-production/qa/automated/style-candidate-d-v4-removal-audit.json"
)

EXPECTED_AFTER_SHA256 = "c8c15f3e0fba49165c5d85f8369b91e7171d88d7059a58c0948e0d1339864016"
EXPECTED_CONTROL_SHA256 = "6df981917be374637c6d685023e06127db0f9ecb942b52a1f098fd5b749ab407"
EXPECTED_MASK_SHA256 = "6978665cf6acc1b466ec991d6133f66b43c47a3e4d6baea2b25e1af28f38fc3c"
EXPECTED_COMPOSITE_REPORT_SHA256 = (
    "687cf2d8503b8f560c994ade712519f68c82b43ad5e2e804164aa7dddaf16180"
)


class RemovalAuditError(ValueError):
    """Raised when the Candidate D v4 removal contract cannot be proven."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_input(path: Path, expected_hash: str, label: str) -> None:
    if not path.is_file():
        raise RemovalAuditError(f"{label} does not exist: {path}")
    actual = sha256_file(path)
    if actual != expected_hash:
        raise RemovalAuditError(
            f"{label} SHA-256 mismatch: expected {expected_hash}, got {actual}"
        )


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _component_signature(component: dict[str, Any]) -> tuple[Any, ...]:
    return (
        component["bbox"],
        component["area_px"],
        component["centroid"],
        component["covariance_eigenvalue_ratio"],
        component["centerline_endpoints"],
        component["minor_sigma_px"],
        component["_target_pixels"],
    )


def _manual_core_mask(stroke: dict[str, Any]) -> Image.Image:
    mask = Image.new("1", mark_mask.CANVAS, 0)
    draw = ImageDraw.Draw(mask)
    draw.line(
        [tuple(point) for point in stroke["points"]],
        fill=1,
        width=stroke["core_width"],
    )
    return mask


def audit(
    *,
    base_path: Path,
    before_path: Path,
    after_path: Path,
    control_path: Path,
    mask_path: Path,
    composite_report_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    if report_path.exists():
        raise RemovalAuditError(f"refusing to overwrite existing output: {report_path}")
    _assert_input(base_path, mark_mask.EXPECTED_BASE_SHA256, "localized base")
    _assert_input(before_path, mark_mask.EXPECTED_CANDIDATE_SHA256, "Candidate D v3")
    _assert_input(after_path, EXPECTED_AFTER_SHA256, "Candidate D v4")
    _assert_input(control_path, EXPECTED_CONTROL_SHA256, "reviewed removal control")
    _assert_input(mask_path, EXPECTED_MASK_SHA256, "reviewed removal mask")
    _assert_input(
        composite_report_path,
        EXPECTED_COMPOSITE_REPORT_SHA256,
        "Candidate D v4 composite report",
    )

    control = json.loads(control_path.read_text(encoding="utf-8"))
    composite_report = json.loads(composite_report_path.read_text(encoding="utf-8"))
    if control.get("reviewed_target_count") != 44:
        raise RemovalAuditError("reviewed removal control must contain exactly 44 targets")
    if composite_report.get("outside_mask_max_channel_difference") != 0:
        raise RemovalAuditError("composite report does not prove exact outside-mask preservation")

    base = mark_mask._load_gray(base_path)
    before_gray = mark_mask._load_gray(before_path)
    after_gray = mark_mask._load_gray(after_path)
    with Image.open(before_path) as opened_before:
        before_rgb = ImageOps.exif_transpose(opened_before).convert("RGB")
    with Image.open(after_path) as opened_after:
        after_rgb = ImageOps.exif_transpose(opened_after).convert("RGB")
    with Image.open(mask_path) as opened_mask:
        edit_mask = ImageOps.exif_transpose(opened_mask).convert("L")

    try:
        before_components = mark_mask.extract_components(base, before_gray)
        after_components = mark_mask.extract_components(
            base,
            after_gray,
            expected_count=None,
        )
        before_by_id = {
            component["component_id"]: component for component in before_components
        }
        false_positive = before_by_id[mark_mask.REVIEWED_FALSE_POSITIVES[0]]
        if len(after_components) != 1:
            raise RemovalAuditError(
                "post-edit detector must retain exactly the reviewed tree false-positive; "
                f"found {len(after_components)} components"
            )
        if _component_signature(after_components[0]) != _component_signature(false_positive):
            raise RemovalAuditError(
                "the sole post-edit detector component is not the byte-preserved tree false-positive"
            )

        mask_values = bytes(edit_mask.get_flattened_data())
        false_positive_pixels = false_positive["_target_pixels"]
        masked_false_positive_pixels = sum(
            mask_values[y * mark_mask.CANVAS[0] + x] != 0
            for x, y in false_positive_pixels
        )
        if masked_false_positive_pixels:
            raise RemovalAuditError("the reviewed tree false-positive intersects the edit mask")
        before_values = before_rgb.tobytes()
        after_values = after_rgb.tobytes()
        false_positive_changed_pixels = sum(
            before_values[(y * mark_mask.CANVAS[0] + x) * 3 : (y * mark_mask.CANVAS[0] + x + 1) * 3]
            != after_values[(y * mark_mask.CANVAS[0] + x) * 3 : (y * mark_mask.CANVAS[0] + x + 1) * 3]
            for x, y in false_positive_pixels
        )
        if false_positive_changed_pixels:
            raise RemovalAuditError("the reviewed tree false-positive changed")

        before_binary = mark_mask._binary_candidates(base, before_gray)
        after_binary = mark_mask._binary_candidates(base, after_gray)
        manual_results: list[dict[str, Any]] = []
        for manual in mark_mask.REVIEWED_MANUAL_STROKES:
            core_mask = _manual_core_mask(manual)
            try:
                indices = [
                    index
                    for index, selected in enumerate(core_mask.get_flattened_data())
                    if selected
                ]
            finally:
                core_mask.close()
            before_detected = sum(before_binary[index] for index in indices)
            after_detected = sum(after_binary[index] for index in indices)
            if before_detected < 1:
                raise RemovalAuditError(
                    f"manual target {manual['id']} has no pre-edit dark evidence"
                )
            if after_detected != 0:
                raise RemovalAuditError(
                    f"manual target {manual['id']} retains {after_detected} detected pixels"
                )
            manual_results.append(
                {
                    "id": manual["id"],
                    "core_pixels": len(indices),
                    "pre_edit_detected_pixels": before_detected,
                    "post_edit_detected_pixels": after_detected,
                }
            )

        difference = ImageChops.difference(after_rgb, before_rgb)
        protected = edit_mask.point(lambda value: 255 if value == 0 else 0)
        outside_difference = Image.composite(
            difference,
            Image.new("RGB", mark_mask.CANVAS),
            protected,
        )
        outside_max = max(channel[1] for channel in outside_difference.getextrema())
        changed_pixels = sum(
            any(before_values[index + channel] != after_values[index + channel] for channel in range(3))
            for index in range(0, len(before_values), 3)
        )
        difference.close()
        protected.close()
        outside_difference.close()
    finally:
        base.close()
        before_gray.close()
        after_gray.close()
        before_rgb.close()
        after_rgb.close()
        edit_mask.close()

    if outside_max != 0:
        raise RemovalAuditError("Candidate D v4 changed protected pixels outside the edit mask")
    report = {
        "schema_version": "1.0.0",
        "id": "style-candidate-d-v4-removal-audit",
        "status": "passed",
        "base_path": _relative(base_path),
        "before_path": _relative(before_path),
        "after_path": _relative(after_path),
        "control_path": _relative(control_path),
        "mask_path": _relative(mask_path),
        "composite_report_path": _relative(composite_report_path),
        "reviewed_target_count": 44,
        "automated_components_pre_edit": len(before_components),
        "reviewed_automated_targets": len(mark_mask.REVIEWED_COMPONENT_ALLOWLIST),
        "automated_route_like_components_post_edit": 0,
        "preserved_false_positive_components_post_edit": len(after_components),
        "preserved_false_positive_id": mark_mask.REVIEWED_FALSE_POSITIVES[0],
        "preserved_false_positive_bbox": after_components[0]["bbox"],
        "masked_false_positive_pixels": masked_false_positive_pixels,
        "false_positive_changed_pixels": false_positive_changed_pixels,
        "manual_targets": manual_results,
        "manual_targets_with_post_edit_detected_pixels": sum(
            result["post_edit_detected_pixels"] > 0 for result in manual_results
        ),
        "changed_pixels_inside_reviewed_mask": changed_pixels,
        "outside_mask_max_channel_difference": outside_max,
        "after_sha256": sha256_file(after_path),
        "control_sha256": sha256_file(control_path),
        "mask_sha256": sha256_file(mask_path),
        "composite_report_sha256": sha256_file(composite_report_path),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--before", type=Path, default=DEFAULT_BEFORE)
    parser.add_argument("--after", type=Path, default=DEFAULT_AFTER)
    parser.add_argument("--control", type=Path, default=DEFAULT_CONTROL)
    parser.add_argument("--mask", type=Path, default=DEFAULT_MASK)
    parser.add_argument("--composite-report", type=Path, default=DEFAULT_COMPOSITE_REPORT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit(
            base_path=args.base.resolve(),
            before_path=args.before.resolve(),
            after_path=args.after.resolve(),
            control_path=args.control.resolve(),
            mask_path=args.mask.resolve(),
            composite_report_path=args.composite_report.resolve(),
            report_path=args.report.resolve(),
        )
    except (OSError, json.JSONDecodeError, RemovalAuditError, ValueError) as exc:
        print(f"Candidate D v4 removal audit failed: {exc}")
        return 1
    print(
        "Candidate D v4 removal audit passed: "
        f"reviewed_targets={report['reviewed_target_count']} "
        f"post_edit_route_components={report['automated_route_like_components_post_edit']} "
        f"outside_mask_max_difference={report['outside_mask_max_channel_difference']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
