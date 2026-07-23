#!/usr/bin/env python3
"""Fail-closed preflight and semantic gates for K3 semantic cleanup."""

from __future__ import annotations

import argparse
import json
import math
from io import BytesIO
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

import build_style_candidate_k3_semantic_cleanup as k3
import audit_style_candidate_h17 as h17
import audit_style_candidate_h4 as h4
import audit_style_candidate_k2_hybrid as k2_audit
from production_common import utc_now


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDIDATE = ROOT / "world/map-production/candidates/style-candidate-k-v3-semantic-cleanup.png"
TEMP_REPORT = k3.TEMP_PROOF_ROOT / f"{k3.TEMP_FINAL.stem}.automated-report.json"

FOREST_QUIET_RANGE = (0.35, 0.55)
HIGHLAND_MINIMUM_QUIET = 0.85
FIELDS_MINIMUM_QUIET = 0.85
MAXIMUM_FIELD_ANGULAR_PEAK = 0.18
MAXIMUM_ORIENTATION_COHERENCE = 0.22


class K3AuditError(RuntimeError):
    pass


def persistent_v20_audit(
    *,
    raw_path: Path,
    final_path: Path,
    v19_path: Path,
    raw_artifact: dict[str, str],
    final_artifact: dict[str, str],
    normalized_receipt: dict[str, str],
    source_receipt_sha256: str,
    source_receipt: dict[str, Any],
    authorized_by: str,
    authority_bindings: dict[str, Any],
    artifact_bindings: dict[str, Any] | None = None,
    reported_authorities: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Re-run K3 gates on copied v20 bytes without retaining TEMP paths."""

    required_authorities = {
        "k3-source",
        "k3-spec",
        "reference-b1",
        "reference-h4",
        "geometry-guide",
        "fields-donor",
        "fields-donor-prompt",
        "audit-h4-code",
        "audit-h17-code",
        "audit-k2-code",
        "audit-v20-code",
        "audit-k3-code",
        "audit-k3-main-code",
    }
    if set(authority_bindings) != required_authorities:
        raise K3AuditError(
            "persistent v20 audit requires the exact bound authority set"
        )
    if reported_authorities is None or set(reported_authorities) != required_authorities:
        raise K3AuditError("persistent v20 audit requires normalized reported authorities")
    for role, binding in authority_bindings.items():
        reported = reported_authorities[role]
        if (
            not isinstance(reported, dict)
            or reported.get("sha256") != binding.sha256
            or not isinstance(reported.get("path"), str)
        ):
            raise K3AuditError(
                f"normalized persistent audit authority {role!r} does not match its bound snapshot"
            )
    if artifact_bindings is None or set(artifact_bindings) != {"raw", "final", "v19"}:
        raise K3AuditError("persistent v20 audit requires bound raw/final/v19 snapshots")
    raw_bytes = artifact_bindings["raw"].data
    final_bytes = artifact_bindings["final"].data
    v19_bytes = artifact_bindings["v19"].data
    if raw_bytes != final_bytes:
        raise K3AuditError("persistent v20 raw and final bytes are not identical")
    if artifact_bindings["raw"].sha256 != raw_artifact.get("sha256"):
        raise K3AuditError("persistent v20 raw SHA-256 is stale")
    if artifact_bindings["final"].sha256 != final_artifact.get("sha256"):
        raise K3AuditError("persistent v20 final SHA-256 is stale")
    with Image.open(BytesIO(final_bytes)) as opened:
        opened.load()
        image_contract = {
            "passed": bool(
                opened.mode == "RGB"
                and opened.size == (k3.WIDTH, k3.HEIGHT)
                and opened.getbands() == ("R", "G", "B")
                and opened.info.get("transparency") is None
                and not opened.info.get("icc_profile")
            ),
            "mode": opened.mode,
            "size": list(opened.size),
            "has_alpha": "A" in opened.getbands(),
            "has_icc_profile": bool(opened.info.get("icc_profile")),
        }
        image = np.asarray(opened.convert("RGB"), np.uint8)
    # Import locally to avoid a module-load cycle: the TEMP-only v20 builder
    # imports this audit module for its shared metrics.
    import build_style_candidate_k3_field_margin_cleanup_v20 as v20

    with Image.open(BytesIO(authority_bindings["k3-source"].data)) as opened_source:
        source_image = np.asarray(opened_source.convert("RGB"), np.uint8)
    controls = v20.derive_v20_controls(source_image=source_image)
    with Image.open(BytesIO(v19_bytes)) as opened_v19:
        base = np.asarray(opened_v19.convert("RGB"), np.uint8)
    try:
        spec = json.loads(authority_bindings["k3-spec"].data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise K3AuditError("bound K3 spec snapshot is not valid JSON") from exc
    donor_slot = spec.get("donor_slots", {}).get("fields")
    if not isinstance(donor_slot, dict):
        raise K3AuditError("bound K3 spec has no fields donor slot")
    donor_binding = authority_bindings["fields-donor"]
    prompt_binding = authority_bindings["fields-donor-prompt"]
    if (
        donor_slot.get("sha256") != donor_binding.sha256
        or donor_slot.get("prompt_sha256") != prompt_binding.sha256
    ):
        raise K3AuditError("bound K3 spec donor/prompt locks do not match snapshots")
    with Image.open(BytesIO(donor_binding.data)) as opened_donor:
        donor = np.asarray(opened_donor.convert("RGB"), np.uint8)
    donor_canvas, _, donor_record = k3.procedural_fields_canvas(
        base,
        donor,
        donor_slot,
        controls["masks"]["field_legacy_edits"],
    )
    recomputed_metrics, recomputed_v20_gates = v20._construction_metrics(
        base, image, donor_canvas, donor_record, controls
    )
    with (
        Image.open(BytesIO(final_bytes)).convert("RGB") as candidate,
        Image.open(BytesIO(authority_bindings["reference-b1"].data)).convert("RGB") as b1,
        Image.open(BytesIO(authority_bindings["reference-h4"].data)).convert("RGB") as h4_reference,
        Image.open(BytesIO(authority_bindings["geometry-guide"].data)).convert("RGB") as guide,
    ):
        unchanged = {
            "boundary": bool(h4.boundary_metrics(candidate)["passed"]),
            "palette": bool(h4.palette_continuity_metrics(candidate, b1)["passed"]),
            "exact_repetition": bool(h4.exact_repetition_metrics(candidate)["passed"]),
            "downsample": bool(h4.downsample_readability_metrics(candidate)["passed"]),
            "semantic_repetition": bool(
                h17.semantic_repetition_proxies(candidate, h4_reference)["passed"]
            ),
            "geometry": bool(k2_audit.geometry_metrics(guide, candidate)["passed"]),
        }
    source_gates = source_receipt.get("automated_gates")
    source_failed = source_receipt.get("failed_gates")
    source_metrics = source_receipt.get("metrics")
    gates = {
        "source_v20_automated_gates": bool(
            isinstance(source_gates, dict)
            and source_gates
            and all(value is True for value in source_gates.values())
            and source_failed == []
        ),
        "recomputed_v20_gate_set": bool(
            isinstance(recomputed_v20_gates, dict)
            and recomputed_v20_gates
            and all(value is True for value in recomputed_v20_gates.values())
            and recomputed_v20_gates == source_gates
        ),
        "recomputed_v20_metrics": recomputed_metrics == source_metrics,
        "raw_final_byte_identity": True,
        "native_rgb_no_alpha_profile": image_contract["passed"],
        **{f"unchanged_{name}": passed for name, passed in unchanged.items()},
    }
    failed = [name for name, passed in gates.items() if not passed]
    if failed:
        raise K3AuditError(f"persistent v20 automated gates failed: {failed}")
    return {
        "schema_version": "1.0.0",
        "id": "style-candidate-k-v3-semantic-cleanup-automated-report",
        "job_id": "style-candidate-k-v3-semantic-cleanup",
        "status": "passed",
        "image_path": final_artifact["path"],
        "image_sha256": final_artifact["sha256"],
        "decision_authority": False,
        "acceptance_inferred": False,
        "golden_accepted": False,
        "temporary_review_only": False,
        "persistent_candidate_emitted": True,
        "authorized_by": authorized_by,
        "raw": raw_artifact,
        "candidate": final_artifact,
        "provenance_receipt": normalized_receipt,
        "source_temporary_receipt_sha256": source_receipt_sha256,
        "audit_authorities": {
            role: reported_authorities[role]
            for role in sorted(reported_authorities)
        },
        "image_contract": image_contract,
        "automated_gates": gates,
        "failed_gates": [],
        "source_v20_metrics": source_metrics,
        "recomputed_v20_metrics": recomputed_metrics,
        "vision_handoff": {
            "required": True,
            "acceptance_threshold": 94,
            "minimum_independent_reviews": 2,
            "review_mode": "blind-independent",
            "immediate_failure_policy": "zero immediate failures",
        },
        "created_at": utc_now(),
    }


def gray_float(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32)


def activity_mask(image: np.ndarray, permission: np.ndarray) -> np.ndarray:
    gray = gray_float(image)
    low = cv2.GaussianBlur(gray, (0, 0), 1.6)
    high = np.abs(gray - low)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gx, gy)
    active = ((high >= 6.0) | (gradient >= 26.0)) & permission
    return cv2.dilate(active.astype(np.uint8), k3.disk(1)) > 0


def quiet_fraction(image: np.ndarray, permission: np.ndarray) -> float:
    if not np.any(permission):
        return 0.0
    active = activity_mask(image, permission)
    return float(np.mean(~active[permission]))


def forest_quiet_clearing_fraction(image: np.ndarray, permission: np.ndarray) -> dict[str, Any]:
    active = activity_mask(image, permission)
    tile = 32
    quiet = 0
    valid = 0
    shares: list[float] = []
    for top in range(0, image.shape[0], tile):
        for left in range(0, image.shape[1], tile):
            local_permission = permission[top:top + tile, left:left + tile]
            covered = int(local_permission.sum())
            if covered < tile * tile * 0.55:
                continue
            share = float(active[top:top + tile, left:left + tile][local_permission].mean())
            shares.append(share)
            valid += 1
            if share <= 0.08:
                quiet += 1
    fraction = float(quiet / valid) if valid else 0.0
    return {
        "tile_size_px": tile,
        "valid_tiles": valid,
        "quiet_tiles": quiet,
        "quiet_clearing_fraction": round(fraction, 6),
        "median_active_fraction": round(float(np.median(shares)), 6) if shares else None,
        "threshold": list(FOREST_QUIET_RANGE),
        "passed": FOREST_QUIET_RANGE[0] <= fraction <= FOREST_QUIET_RANGE[1],
    }


def closed_icon_proxy(image: np.ndarray, permission: np.ndarray) -> dict[str, Any]:
    gray = gray_float(image).astype(np.uint8)
    background = cv2.medianBlur(gray, 11)
    dark = ((background.astype(np.int16) - gray.astype(np.int16)) >= 7) & permission
    dark = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_CLOSE, k3.disk(1))
    contours, hierarchy = cv2.findContours(dark, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    icons: list[dict[str, Any]] = []
    if hierarchy is not None:
        for index, contour in enumerate(contours):
            if hierarchy[0, index, 3] < 0:
                continue
            area = float(cv2.contourArea(contour))
            x, y, width, height = cv2.boundingRect(contour)
            if 4.0 <= area <= 240.0 and 3 <= width <= 28 and 3 <= height <= 28:
                icons.append({"bbox_xywh": [x, y, width, height], "hole_area": round(area, 3)})
    return {
        "method": "closed-hole contours in locally dark 3-28px components",
        "closed_loop_tree_cell_icon_count": len(icons),
        "examples": icons[:12],
        "threshold": 0,
        "passed": len(icons) == 0,
    }


def hough_segments(image: np.ndarray, permission: np.ndarray, minimum_length: int) -> list[tuple[int, int, int, int]]:
    gray = gray_float(image).astype(np.uint8)
    local = cv2.medianBlur(gray, 9)
    ink = ((local.astype(np.int16) - gray.astype(np.int16)) >= 7) & permission
    lines = cv2.HoughLinesP(
        ink.astype(np.uint8) * 255,
        1,
        np.pi / 180,
        threshold=max(5, minimum_length // 2),
        minLineLength=minimum_length,
        maxLineGap=1,
    )
    if lines is None:
        return []
    return [tuple(int(value) for value in line[0]) for line in lines]


def dash_bundle_proxy(image: np.ndarray, permission: np.ndarray) -> dict[str, Any]:
    segments = hough_segments(image, permission, minimum_length=3)
    short: list[tuple[float, float, float]] = []
    for x0, y0, x1, y1 in segments:
        length = math.hypot(x1 - x0, y1 - y0)
        if 3 <= length <= 12:
            angle = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180
            short.append(((x0 + x1) / 2, (y0 + y1) / 2, angle))
    bundled: set[tuple[int, int]] = set()
    for first in range(len(short)):
        x0, y0, a0 = short[first]
        for second in range(first + 1, len(short)):
            x1, y1, a1 = short[second]
            angle_delta = abs(a0 - a1)
            angle_delta = min(angle_delta, 180 - angle_delta)
            if math.hypot(x1 - x0, y1 - y0) <= 11 and angle_delta <= 10:
                bundled.add((first, second))
    return {
        "method": "pairs of 3-12px Hough strokes within 11px and 10 degrees",
        "short_segment_count": len(short),
        "parallel_multi_stroke_bundle_pair_count": len(bundled),
        "threshold": 0,
        "passed": len(bundled) == 0,
    }


def orientation_coherence(image: np.ndarray, permission: np.ndarray) -> dict[str, Any]:
    gray = gray_float(image)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    active = activity_mask(image, permission) & permission
    if not np.any(active):
        coherence = 0.0
    else:
        jxx = float(np.mean(gx[active] ** 2))
        jyy = float(np.mean(gy[active] ** 2))
        jxy = float(np.mean(gx[active] * gy[active]))
        coherence = math.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / max(jxx + jyy, 1e-6)
    return {
        "global_gradient_orientation_coherence": round(coherence, 6),
        "maximum": MAXIMUM_ORIENTATION_COHERENCE,
        "woven_or_single-direction_substrate_detected": coherence > MAXIMUM_ORIENTATION_COHERENCE,
        "passed": coherence <= MAXIMUM_ORIENTATION_COHERENCE,
    }


def angular_spectrum_peak(image: np.ndarray, permission: np.ndarray) -> float:
    ys, xs = np.nonzero(permission)
    if not len(xs):
        return 1.0
    left, right = int(xs.min()), int(xs.max()) + 1
    top, bottom = int(ys.min()), int(ys.max()) + 1
    gray = gray_float(image)[top:bottom, left:right]
    mask = permission[top:bottom, left:right]
    fill = float(np.median(gray[mask]))
    centered = np.where(mask, gray - fill, 0.0)
    centered -= cv2.GaussianBlur(centered, (0, 0), 12.0)
    window = np.outer(np.hanning(centered.shape[0]), np.hanning(centered.shape[1])).astype(np.float32)
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2(centered * window))) ** 2
    fy = np.fft.fftshift(np.fft.fftfreq(centered.shape[0]))
    fx = np.fft.fftshift(np.fft.fftfreq(centered.shape[1]))
    yy, xx = np.meshgrid(fy, fx, indexing="ij")
    radius = np.hypot(xx, yy)
    band = (radius >= 1 / 32) & (radius <= 1 / 4)
    angles = np.mod(np.arctan2(yy, xx), np.pi)
    energy = spectrum[band]
    if float(energy.sum()) <= 0:
        return 0.0
    histogram, _ = np.histogram(angles[band], bins=18, range=(0, np.pi), weights=energy)
    return float(histogram.max() / histogram.sum())


def field_metrics(image: np.ndarray, permissions: list[np.ndarray]) -> dict[str, Any]:
    parcels: list[dict[str, Any]] = []
    for index, permission in enumerate(permissions, 1):
        quiet = quiet_fraction(image, permission)
        peak = angular_spectrum_peak(image, permission)
        long_segments = hough_segments(image, permission, minimum_length=18)
        cadence = peak > MAXIMUM_FIELD_ANGULAR_PEAK
        parcels.append({
            "parcel": index,
            "quiet_fraction": round(quiet, 6),
            "minimum_quiet_fraction": FIELDS_MINIMUM_QUIET,
            "angular_spectrum_peak_share": round(peak, 6),
            "maximum_angular_spectrum_peak_share": MAXIMUM_FIELD_ANGULAR_PEAK,
            "row_cadence_detected": cadence,
            "continuous_furrow_count": len(long_segments),
            "passed": quiet >= FIELDS_MINIMUM_QUIET and not cadence and len(long_segments) == 0,
        })
    return {
        "parcel_count": len(parcels),
        "parcels": parcels,
        "passed": len(parcels) == 8 and all(item["passed"] for item in parcels),
    }


def parcel_boundary_cadence_metrics(
    image: np.ndarray, masks: dict[str, Any]
) -> dict[str, Any]:
    """Record, but do not gate, small comma/loop cadence near parcel borders."""
    gray = gray_float(image).astype(np.uint8)
    background = cv2.medianBlur(gray, 11).astype(np.int16)
    local_dark = (background - gray.astype(np.int16)) >= 7
    boundary_context = k3.dilate(masks["guards"]["field_boundaries"], 8)
    parcels: list[dict[str, Any]] = []
    cadence_permissions = masks.get("field_legacy_edits", masks["field_edits"])
    for index, permission in enumerate(cadence_permissions, 1):
        band = permission & boundary_context
        marks = local_dark & band
        count, _, stats, centroids = cv2.connectedComponentsWithStats(
            marks.astype(np.uint8), 8
        )
        centers: list[tuple[float, float]] = []
        for component in range(1, count):
            area = int(stats[component, cv2.CC_STAT_AREA])
            width = int(stats[component, cv2.CC_STAT_WIDTH])
            height = int(stats[component, cv2.CC_STAT_HEIGHT])
            if 2 <= area <= 48 and width <= 12 and height <= 12:
                centers.append(tuple(float(value) for value in centroids[component]))
        nearest: list[float] = []
        for first, center in enumerate(centers):
            distances = [
                math.hypot(center[0] - other[0], center[1] - other[1])
                for second, other in enumerate(centers)
                if second != first
            ]
            if distances:
                distance = min(distances)
                if 3.0 <= distance <= 18.0:
                    nearest.append(distance)
        if nearest:
            histogram, edges = np.histogram(nearest, bins=np.arange(3.0, 20.0, 1.0))
            dominant_index = int(np.argmax(histogram))
            dominant_count = int(histogram[dominant_index])
            dominant_share = dominant_count / len(nearest)
            dominant_spacing = float((edges[dominant_index] + edges[dominant_index + 1]) / 2)
        else:
            dominant_count = 0
            dominant_share = 0.0
            dominant_spacing = 0.0
        contours, hierarchy = cv2.findContours(
            marks.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
        )
        loop_count = 0
        if hierarchy is not None:
            loop_count = sum(
                1
                for contour_index, contour in enumerate(contours)
                if hierarchy[0, contour_index, 3] >= 0
                and 1.0 <= cv2.contourArea(contour) <= 64.0
            )
        angular_peak = angular_spectrum_peak(image, band)
        immediate_row = bool(
            len(centers) >= 12
            and len(nearest) >= 8
            and dominant_share >= 0.45
            and angular_peak > MAXIMUM_FIELD_ANGULAR_PEAK
        )
        parcels.append({
            "parcel": index,
            "boundary_band_pixels": int(band.sum()),
            "small_comma_component_count": len(centers),
            "closed_loop_count": loop_count,
            "nearest_spacing_sample_count": len(nearest),
            "dominant_nearest_spacing_px": round(dominant_spacing, 6),
            "dominant_nearest_spacing_share": round(dominant_share, 6),
            "angular_spectrum_peak_share": round(angular_peak, 6),
            "immediate_row_detected": immediate_row,
        })
    return {
        "status": "diagnostic-only-recorded-for-next-control",
        "changes_applied_by_this_diagnostic": False,
        "band": "parcel interior within 8px of exact field-boundary guard",
        "small_component_contract": "local-dark>=7; area 2-48px; span <=12px",
        "immediate_row_rule": "at least 12 marks, 8 spacing samples, dominant spacing share >=0.45, and angular peak >0.18",
        "parcels": parcels,
        "immediate_row_detected": any(
            item["immediate_row_detected"] for item in parcels
        ),
        "vision_review_required": True,
    }


def highland_fully_editable_support(masks: dict[str, Any]) -> np.ndarray:
    """Return the exact production-alpha support where the donor is fully applied."""
    alpha = k3.boundary_locked_alpha(
        masks["highland_edit"],
        full_by_px=k3.HIGHLAND_ALPHA_FULL_BY_PX,
        locked_boundary_px=k3.HIGHLAND_ALPHA_LOCKED_BOUNDARY_PX,
    )
    return alpha == np.float32(1.0)


def semantic_cleanup_metrics(image: np.ndarray, masks: dict[str, Any]) -> dict[str, Any]:
    forest_clearings = forest_quiet_clearing_fraction(image, masks["forest_edit"])
    forest_icons = closed_icon_proxy(image, masks["forest_edit"])
    highland_measurement = highland_fully_editable_support(masks)
    highland_quiet = quiet_fraction(image, highland_measurement)
    highland_bundles = dash_bundle_proxy(image, highland_measurement)
    highland_orientation = orientation_coherence(image, highland_measurement)
    fields = field_metrics(image, masks["field_edits"])
    forest_passed = forest_clearings["passed"] and forest_icons["passed"]
    highland_passed = (
        highland_quiet >= HIGHLAND_MINIMUM_QUIET
        and highland_bundles["passed"]
        and highland_orientation["passed"]
    )
    return {
        "forest": {"quiet_clearings": forest_clearings, "closed_icon_proxy": forest_icons, "passed": forest_passed},
        "highland": {
            "measurement": {
                "method": (
                    "boundary_locked_alpha(highland_edit, full_by_px=5.0, "
                    "locked_boundary_px=2.0) == 1.0"
                ),
                "alpha_function": "k3.boundary_locked_alpha",
                "locked_boundary_px": k3.HIGHLAND_ALPHA_LOCKED_BOUNDARY_PX,
                "full_by_px": k3.HIGHLAND_ALPHA_FULL_BY_PX,
                "required_alpha_value": 1.0,
                "pixels": int(highland_measurement.sum()),
                "reason": (
                    "Exactly matches the production highland alpha==1 support; "
                    "locked and fractional transition pixels are excluded while "
                    "every fully editable pixel remains measured."
                ),
            },
            "quiet_fraction": round(highland_quiet, 6),
            "minimum_quiet_fraction": HIGHLAND_MINIMUM_QUIET,
            "dash_bundle_proxy": highland_bundles,
            "orientation_substrate_proxy": highland_orientation,
            "passed": highland_passed,
        },
        "fields": fields,
        "passed": forest_passed and highland_passed and fields["passed"],
        "semantic_claim": None,
        "vision_review_still_required": True,
    }


def _raster_region_metrics(
    lab_l: np.ndarray,
    strong_ink: np.ndarray,
    permission: np.ndarray,
) -> dict[str, Any]:
    core = k3.erode(permission, 5)
    local_strong = strong_ink & permission
    calm = core & ~k3.dilate(local_strong, 5)
    return {
        "permission_pixels": int(permission.sum()),
        "core_pixels": int(core.sum()),
        "median_lab_l": round(float(np.median(lab_l[permission])), 6),
        "strong_ink_fraction": round(float(local_strong[permission].mean()), 6),
        "raster_calm_fraction": round(float(calm.sum() / max(int(core.sum()), 1)), 6),
    }


def _structural_ink(
    image: np.ndarray,
    permission: np.ndarray,
    threshold: int,
) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    background = cv2.medianBlur(gray, 11).astype(np.int16)
    return (
        (background - gray.astype(np.int16) >= threshold)
        & k3.erode(permission, 3)
    )


def _binary_hough(
    ink: np.ndarray,
    minimum_length: int,
    maximum_length: int | None = None,
) -> list[tuple[int, int, int, int]]:
    lines = cv2.HoughLinesP(
        ink.astype(np.uint8) * 255,
        1,
        np.pi / 180,
        threshold=max(5, minimum_length // 2),
        minLineLength=minimum_length,
        maxLineGap=1,
    )
    if lines is None:
        return []
    result: list[tuple[int, int, int, int]] = []
    for line in lines:
        values = tuple(int(value) for value in line[0])
        if maximum_length is not None:
            x0, y0, x1, y1 = values
            if math.hypot(x1 - x0, y1 - y0) > maximum_length:
                continue
        result.append(values)
    return result


def _parallel_triple_count(
    segments: list[tuple[int, int, int, int]],
) -> int:
    records: list[tuple[float, float, float]] = []
    for x0, y0, x1, y1 in segments:
        records.append((
            (x0 + x1) / 2.0,
            (y0 + y1) / 2.0,
            math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0,
        ))
    if len(records) > 160:
        return len(records)
    triples: set[tuple[int, int, int]] = set()
    for first in range(len(records)):
        x0, y0, a0 = records[first]
        neighbors: list[int] = []
        for second in range(len(records)):
            if second == first:
                continue
            x1, y1, a1 = records[second]
            delta = min(abs(a1 - a0), 180.0 - abs(a1 - a0))
            if math.hypot(x1 - x0, y1 - y0) <= 24.0 and delta <= 12.0:
                neighbors.append(second)
        for left in range(len(neighbors)):
            for right in range(left + 1, len(neighbors)):
                triples.add(tuple(sorted((first, neighbors[left], neighbors[right]))))
    return len(triples)


def _empty_window_fraction(
    marks: np.ndarray,
    permission: np.ndarray,
    window: int,
) -> dict[str, Any]:
    valid = 0
    empty = 0
    for top in range(0, permission.shape[0] - window + 1, window):
        for left in range(0, permission.shape[1] - window + 1, window):
            local_permission = permission[top:top + window, left:left + window]
            if int(local_permission.sum()) < window * window * 0.60:
                continue
            valid += 1
            if not np.any(marks[top:top + window, left:left + window] & local_permission):
                empty += 1
    return {
        "window_px": window,
        "valid_windows": valid,
        "empty_windows": empty,
        "empty_window_fraction": round(float(empty / valid), 6) if valid else 0.0,
    }


def strict_content_metrics(image: np.ndarray, masks: dict[str, Any]) -> dict[str, Any]:
    lab_l = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32)
    strong = (cv2.GaussianBlur(lab_l, (0, 0), 4.0) - lab_l) >= 30.0

    forest = _raster_region_metrics(lab_l, strong, masks["forest_edit"])
    tile_means: list[float] = []
    tile = 32
    permission = masks["forest_edit"]
    for top in range(0, image.shape[0], tile):
        for left in range(0, image.shape[1], tile):
            local_permission = permission[top:top + tile, left:left + tile]
            if int(local_permission.sum()) < tile * tile * 0.55:
                continue
            tile_means.append(float(lab_l[top:top + tile, left:left + tile][local_permission].mean()))
    clearing_fraction = float(np.mean(np.asarray(tile_means) >= 108.0)) if tile_means else 0.0
    forest.update({
        "broad_clearing_tile_px": tile,
        "broad_clearing_lab_l_threshold": 108.0,
        "broad_clearing_valid_tiles": len(tile_means),
        "broad_clearing_fraction": round(clearing_fraction, 6),
        "recognizable_closed_loop_or_tree_icon_gate": "requires Root Vision; no automated semantic claim",
    })
    forest["passed_automated_raster"] = bool(
        forest["strong_ink_fraction"] <= 0.10
        and forest["raster_calm_fraction"] >= 0.25
        and 0.35 <= clearing_fraction <= 0.55
    )

    highland = _raster_region_metrics(lab_l, strong, masks["highland_edit"])
    highland_marks = _structural_ink(image, masks["highland_edit"], 26)
    highland_segments = _binary_hough(highland_marks, 3, 8)
    highland_triples = _parallel_triple_count(highland_segments)
    highland_empty = _empty_window_fraction(
        highland_marks, masks["highland_edit"], 64
    )
    highland.update({
        "structural_ink_threshold": 26,
        "structural_ink_pixels": int(highland_marks.sum()),
        "short_segment_count": len(highland_segments),
        "parallel_triple_count_within_24px_12deg": highland_triples,
        "empty_windows": highland_empty,
    })
    highland["passed"] = bool(
        highland["strong_ink_fraction"] <= 0.018
        and highland["raster_calm_fraction"] >= 0.65
        and highland_triples == 0
        and highland_empty["empty_window_fraction"] >= 0.50
    )

    fields: list[dict[str, Any]] = []
    for index, field_permission in enumerate(masks["field_edits"], 1):
        record = _raster_region_metrics(lab_l, strong, field_permission)
        marks = _structural_ink(image, field_permission, 30)
        long_segments = _binary_hough(marks, 18)
        empty = _empty_window_fraction(marks, field_permission, 48)
        record.update({
            "parcel": index,
            "structural_ink_threshold": 30,
            "structural_ink_pixels": int(marks.sum()),
            "continuous_furrow_segment_count": len(long_segments),
            "empty_windows": empty,
        })
        record["passed"] = bool(
            record["strong_ink_fraction"] <= 0.035
            and record["raster_calm_fraction"] >= 0.50
            and len(long_segments) == 0
            and empty["empty_window_fraction"] >= 0.35
        )
        fields.append(record)

    corridor_permission = masks["agricultural_corridor_envelope"]
    agricultural_corridor = _raster_region_metrics(lab_l, strong, corridor_permission)
    corridor_marks = _structural_ink(image, corridor_permission, 30)
    corridor_segments = _binary_hough(corridor_marks, 18)
    strong_row_ink = strong & k3.erode(corridor_permission, 3)
    strong_row_segments = _binary_hough(strong_row_ink, 18)
    corridor_empty = _empty_window_fraction(corridor_marks, corridor_permission, 24)
    agricultural_corridor.update({
        "semantic": "agricultural_corridor_envelope",
        "status": "v18 same-coordinate K2 restoration context",
        "structural_ink_threshold": 30,
        "structural_ink_pixels": int(corridor_marks.sum()),
        "continuous_furrow_segment_count": len(corridor_segments),
        "strong_ink_row_band_segment_count": len(strong_row_segments),
        "strong_ink_row_band_examples_xyxy": [list(item) for item in strong_row_segments[:12]],
        "empty_windows": corridor_empty,
    })
    base = k3.validate_source()
    agricultural_corridor["k2_exact_restoration"] = bool(
        np.array_equal(
            image[corridor_permission], base[corridor_permission]
        )
    )
    agricultural_corridor["content_metrics_diagnostic_only"] = True
    agricultural_corridor["passed"] = agricultural_corridor["k2_exact_restoration"]
    return {
        "definitions": {
            "strong_ink": "GaussianBlur(Lab_L,sigma=4)-Lab_L >= 30",
            "raster_calm": "erode(permission,5) excluding dilate(strong_ink,5)",
            "substrate_separation": "median11 local-dark threshold 26 highland / 30 fields",
        },
        "forest": forest,
        "highland": highland,
        "fields": {"parcels": fields, "passed": all(item["passed"] for item in fields)},
        "agricultural_corridor_envelope": agricultural_corridor,
        "passed_automated_raster_and_structure": bool(
            forest["passed_automated_raster"]
            and highland["passed"]
            and all(item["passed"] for item in fields)
            and agricultural_corridor["passed"]
        ),
        "semantic_claim": None,
        "vision_required_for_icons_projection_and_style": True,
    }


def low_frequency_blotch_metrics(
    image: np.ndarray,
    masks: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed on broad parcel/corridor airbrush masses, independent of legacy gates."""
    if contract is None:
        contract = k3.load_spec()["low_frequency_blotch_gate"]
    measurement = contract["measurement"]
    thresholds = contract["thresholds"]
    sigma = float(measurement["normalized_permission_gaussian_sigma_px"])
    erosion = int(measurement["permission_erosion_px"])
    q_low, q_high = [float(value) for value in measurement["robust_span_quantiles"]]
    blob_delta = float(
        measurement["large_blob_absolute_delta_from_region_median_lab_l"]
    )
    lab_l = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32)
    regions = [
        *(f"parcel_{index}" for index in range(1, 9)),
        "agricultural_corridor_envelope",
    ]
    permissions = [*masks["field_edits"], masks["agricultural_corridor_envelope"]]
    records: list[dict[str, Any]] = []
    for name, permission in zip(regions, permissions):
        weight = permission.astype(np.float32)
        denominator = cv2.GaussianBlur(weight, (0, 0), sigma)
        low_frequency = cv2.GaussianBlur(lab_l * weight, (0, 0), sigma) / np.maximum(
            denominator, 1e-6
        )
        core = k3.erode(permission, erosion)
        if not np.any(core):
            records.append({"region": name, "core_pixels": 0, "passed": False})
            continue
        values = low_frequency[core]
        robust_span = float(np.quantile(values, q_high) - np.quantile(values, q_low))
        gx = cv2.Sobel(low_frequency, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(low_frequency, cv2.CV_32F, 0, 1, ksize=3)
        maximum_gradient = float(np.max(cv2.magnitude(gx, gy)[core]))
        median = float(np.median(values))
        blob = core & (np.abs(low_frequency - median) >= blob_delta)
        count, _, stats, _ = cv2.connectedComponentsWithStats(
            blob.astype(np.uint8), 8
        )
        maximum_blob_area = int(stats[1:, cv2.CC_STAT_AREA].max()) if count > 1 else 0
        blob_fraction = maximum_blob_area / max(int(core.sum()), 1)
        passed = bool(
            robust_span
            <= float(thresholds["maximum_robust_low_frequency_span_lab_l"])
            and maximum_gradient
            <= float(thresholds["maximum_local_low_frequency_gradient"])
            and blob_fraction
            <= float(thresholds["maximum_connected_large_blob_core_fraction"])
        )
        records.append({
            "region": name,
            "core_pixels": int(core.sum()),
            "robust_p95_minus_p05_lab_l": round(robust_span, 6),
            "maximum_local_low_frequency_gradient": round(maximum_gradient, 6),
            "maximum_connected_large_blob_pixels": maximum_blob_area,
            "maximum_connected_large_blob_core_fraction": round(blob_fraction, 6),
            "passed": passed,
        })
    return {
        "version": contract["version"],
        "independent_of_existing_gates": True,
        "measurement": measurement,
        "thresholds": thresholds,
        "regions": records,
        "passed": len(records) == 9 and all(record["passed"] for record in records),
    }


def _identity_metrics(image: np.ndarray, masks: dict[str, Any]) -> dict[str, Any]:
    base = k3.validate_source()
    if (
        not k3.V17_PROOF.is_file()
        or k3.sha256(k3.V17_PROOF) != k3.EXPECTED_V17_PROOF
    ):
        raise K3AuditError("frozen TEMP v17 proof is missing or hash-mismatched")
    v17 = np.asarray(Image.open(k3.V17_PROOF).convert("RGB"), np.uint8)
    changed = np.any(image != base, axis=2)
    named = {
        name: int(np.count_nonzero(changed & guard))
        for name, guard in masks["guards"].items()
    }
    replacement = {
        "forest": round(float(changed[masks["forest_edit"]].mean()), 6),
        "highland": round(float(changed[masks["highland_edit"]].mean()), 6),
        "fields": [
            round(float(changed[permission].mean()), 6)
            for permission in masks["field_edits"]
        ],
        "agricultural_corridor_envelope": round(
            float(changed[masks["agricultural_corridor_envelope"]].mean()), 6
        ),
    }
    corridor_k2_exact = bool(np.array_equal(
        image[masks["agricultural_corridor_envelope"]],
        base[masks["agricultural_corridor_envelope"]],
    ))
    field_restore_scope = masks.get(
        "field_restore_scope",
        masks.get("field_channel_legacy_scope", masks["fields_edit"])
        & ~masks["field_parcel_edit"],
    )
    field_channel_outside_strict_k2_exact = bool(np.array_equal(
        image[field_restore_scope], base[field_restore_scope]
    ))
    strict_field_v17_exact = bool(np.array_equal(
        image[masks["field_parcel_edit"]],
        v17[masks["field_parcel_edit"]],
    ))
    v17_difference = np.any(image != v17, axis=2)
    v17_differing_outside_restore_scope = int(np.count_nonzero(
        v17_difference & ~field_restore_scope
    ))
    v17_differing_inside_restore_scope = int(np.count_nonzero(
        v17_difference & field_restore_scope
    ))
    boundary = {
        "forest": k3.boundary_delta_metrics(base, image, masks["forest_edit"]),
        "highland": k3.boundary_delta_metrics(base, image, masks["highland_edit"]),
        "fields": k3.boundary_delta_metrics(
            base, image, masks["field_parcel_legacy_edit"]
        ),
        "field_strict_interiors_diagnostic": k3.boundary_delta_metrics(
            base, image, masks["field_parcel_edit"]
        ),
        "agricultural_corridor_envelope": k3.boundary_delta_metrics(
            base, image, masks["agricultural_corridor_envelope"]
        ),
        "field_parcels": [
            k3.boundary_delta_metrics(base, image, permission)
            for permission in masks["field_legacy_edits"]
        ],
    }
    boundary_records = [
        boundary["forest"],
        boundary["highland"],
        boundary["fields"],
        boundary["agricultural_corridor_envelope"],
    ]
    passed = bool(
        not np.any(changed & ~masks["edit_union"])
        and not np.any(changed & masks["protected_features"])
        and not any(named.values())
        and replacement["forest"] >= 0.80
        and replacement["highland"] >= 0.80
        and all(value >= 0.75 for value in replacement["fields"])
        and replacement["agricultural_corridor_envelope"] == 0.0
        and corridor_k2_exact
        and field_channel_outside_strict_k2_exact
        and strict_field_v17_exact
        and v17_differing_outside_restore_scope == 0
        and v17_differing_inside_restore_scope > 0
        and all(
            item["median_channel_delta"] <= 2
            and item["p95_channel_delta"] <= 5
            for item in boundary_records
        )
    )
    return {
        "passed": passed,
        "changed_outside_union_pixels": int(np.count_nonzero(changed & ~masks["edit_union"])),
        "changed_protected_pixels": int(np.count_nonzero(changed & masks["protected_features"])),
        "changed_pixels_by_named_guard": named,
        "replacement_fraction": replacement,
        "agricultural_corridor_k2_exact_restoration": corridor_k2_exact,
        "field_channel_outside_strict_k2_exact": field_channel_outside_strict_k2_exact,
        "field_channel_restore_scope_pixels": int(field_restore_scope.sum()),
        "frozen_v17": {
            "path": k3.relative(k3.V17_PROOF),
            "sha256": k3.sha256(k3.V17_PROOF),
            "strict_field_interiors_exact": strict_field_v17_exact,
            "strict_field_interior_pixels": int(masks["field_parcel_edit"].sum()),
            "differing_pixels_outside_restore_scope": v17_differing_outside_restore_scope,
            "differing_pixels_inside_restore_scope": v17_differing_inside_restore_scope,
        },
        "boundary": boundary,
    }


def temporary_proof_audit(
    candidate_path: Path = k3.TEMP_FINAL,
    report_path: Path = TEMP_REPORT,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    if report_path.exists() and not replace:
        raise K3AuditError(f"refusing to overwrite temporary audit: {report_path}")
    if not candidate_path.is_file() or not k3.TEMP_RAW.is_file() or not k3.TEMP_RECEIPT.is_file():
        raise K3AuditError("temporary proof/raw/receipt set is incomplete")
    image = np.asarray(Image.open(candidate_path).convert("RGB"), np.uint8)
    if image.shape != (k3.HEIGHT, k3.WIDTH, 3):
        raise K3AuditError("temporary proof has the wrong native raster contract")
    masks = k3.derive_masks()
    identity = _identity_metrics(image, masks)
    content = strict_content_metrics(image, masks)
    low_frequency_blotch = low_frequency_blotch_metrics(image, masks)
    parcel_boundary_cadence = parcel_boundary_cadence_metrics(image, masks)

    with Image.open(candidate_path) as opened:
        image_contract = {
            "passed": bool(
                opened.mode == "RGB"
                and opened.size == (k3.WIDTH, k3.HEIGHT)
                and opened.getbands() == ("R", "G", "B")
                and opened.info.get("transparency") is None
                and not opened.info.get("icc_profile")
            ),
            "mode": opened.mode,
            "size": list(opened.size),
            "info_keys": sorted(opened.info),
        }
    with (
        Image.open(candidate_path).convert("RGB") as candidate,
        Image.open(k2_audit.B1_REFERENCE).convert("RGB") as b1,
        Image.open(k2_audit.H4_REFERENCE).convert("RGB") as h4_reference,
        Image.open(k2_audit.GUIDE).convert("RGB") as guide,
    ):
        unchanged = {
            "boundary": h4.boundary_metrics(candidate),
            "palette": h4.palette_continuity_metrics(candidate, b1),
            "exact_repetition": h4.exact_repetition_metrics(candidate),
            "downsample": h4.downsample_readability_metrics(candidate),
            "semantic_repetition": h17.semantic_repetition_proxies(candidate, h4_reference),
            "geometry": k2_audit.geometry_metrics(guide, candidate),
        }
    raw_final_identity = k3.TEMP_RAW.read_bytes() == candidate_path.read_bytes()
    gates = {
        "exact_k2_source_lock": k3.sha256(k3.SOURCE) == k3.EXPECTED_SOURCE,
        "temp_raw_final_byte_identity": raw_final_identity,
        "native_rgb_no_alpha_profile": image_contract["passed"],
        "permission_and_protected_byte_identity": identity["passed"],
        "strict_local_raster_and_structure": content["passed_automated_raster_and_structure"],
        "low_frequency_blotch_v1": low_frequency_blotch["passed"],
        "unchanged_boundary": unchanged["boundary"]["passed"],
        "unchanged_palette": unchanged["palette"]["passed"],
        "unchanged_exact_repetition": unchanged["exact_repetition"]["passed"],
        "unchanged_downsample": unchanged["downsample"]["passed"],
        "unchanged_semantic_repetition": unchanged["semantic_repetition"]["passed"],
        "unchanged_strict_geometry": unchanged["geometry"]["passed"],
    }
    failed = [name for name, passed in gates.items() if not passed]
    report = {
        "schema_version": "1.0.0",
        "id": f"{candidate_path.stem}-automated-report",
        "status": "passed-pending-root-vision" if not failed else "failed-pending-root-vision-decision",
        "decision_authority": False,
        "temporary_review_only": True,
        "persistent_candidate_emitted": False,
        "golden_accepted": False,
        "candidate": {"path": k3.relative(candidate_path), "sha256": k3.sha256(candidate_path)},
        "source": {"path": k3.relative(k3.SOURCE), "sha256": k3.sha256(k3.SOURCE)},
        "receipt": {"path": k3.relative(k3.TEMP_RECEIPT), "sha256": k3.sha256(k3.TEMP_RECEIPT)},
        "image_contract": image_contract,
        "identity": identity,
        "strict_content": content,
        "low_frequency_blotch": low_frequency_blotch,
        "parcel_boundary_cadence": parcel_boundary_cadence,
        "unchanged_gates": unchanged,
        "automated_gates": gates,
        "failed_gates": failed,
        "vision_handoff": {
            "required": True,
            "semantic_claim": None,
            "acceptance_threshold": 94,
            "immediate_failure_policy": "zero immediate failures",
        },
    }
    k3.atomic_json(report_path, report)
    return report


def audit_candidate(path: Path = DEFAULT_CANDIDATE) -> dict[str, Any]:
    if not path.is_file():
        raise K3AuditError(
            "persistent K3 candidate is intentionally absent; audit an explicit TEMP proof path"
        )
    image = np.asarray(Image.open(path).convert("RGB"), np.uint8)
    if image.shape != (k3.HEIGHT, k3.WIDTH, 3):
        raise K3AuditError("K3 candidate has the wrong image contract")
    masks = k3.derive_masks()
    semantic = semantic_cleanup_metrics(image, masks)
    if not semantic["passed"]:
        raise K3AuditError("K3 candidate failed strict semantic-cleanup proxies")
    blotch = low_frequency_blotch_metrics(image, masks)
    if not blotch["passed"]:
        raise K3AuditError("K3 candidate failed low-frequency blotch gate v1")
    semantic["low_frequency_blotch"] = blotch
    return semantic


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--temporary-proof", action="store_true")
    parser.add_argument("--replace-temporary-report", action="store_true")
    parser.add_argument("--preflight-root", type=Path, default=k3.PREFLIGHT_ROOT)
    args = parser.parse_args()
    if args.replace_temporary_report and not args.temporary_proof:
        parser.error("--replace-temporary-report requires --temporary-proof")
    if args.temporary_proof:
        report = temporary_proof_audit(replace=args.replace_temporary_report)
        print(json.dumps({
            "status": report["status"],
            "candidate": report["candidate"],
            "failed_gates": report["failed_gates"],
            "report": k3.relative(TEMP_REPORT),
        }, indent=2))
    elif args.candidate:
        print(json.dumps(audit_candidate(args.candidate), indent=2))
    else:
        report = k3.prepare(args.preflight_root)
        print(json.dumps({
            "status": report["status"],
            "all_donors_ready": report["all_donors_ready"],
            "candidate_emitted": report["candidate_emitted"],
            "protected_overlap_pixels": report["mask_contract"]["protected_overlap_pixels"],
        }, indent=2))


if __name__ == "__main__":
    main()
