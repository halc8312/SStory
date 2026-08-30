#!/usr/bin/env python3
"""Build the root-authorized TEMP-only K3 v20 field-margin cleanup proof.

This tool deliberately has no persistent-output mode.  The caller must bind an
explicit TEMP v19 raster to its expected SHA-256 and choose an output directory
below ``tmp/map-production``.  The v19 SHA is intentionally not frozen here:
v19 does not exist until the separate highland-only review has passed.

The only v20 raster mutation is the canonical legacy field-parcel margin.  The
locked ``fields-quiet-v2`` donor is transformed by K3's existing
``procedural_fields_canvas`` at the same coordinates, then composited with a
canonical inward-distance alpha: zero through 2 px, smoothstep from 2 to 5 px,
and one from 5 px inward.  Strict interiors, the exact parcel boundary core,
the 12 px road guard, corridor, capital, protected features, and all non-field
pixels remain byte-identical to the supplied v19 base.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

import audit_style_candidate_k3_semantic_cleanup as k3_audit
import build_style_candidate_k3_semantic_cleanup as k3


ROOT = Path(__file__).resolve().parents[2]
TEMP_PARENT = ROOT / "tmp/map-production"
V18_REFERENCE = (
    ROOT
    / "world/map-production/style-assets/k3-v18-reconstruction-base.png"
)
EXPECTED_V18_SHA256 = (
    "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882"
)
EXPECTED_FIELDS_DONOR_PATH = (
    "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/"
    "fields-quiet-v2.png"
)
EXPECTED_FIELDS_DONOR_SHA256 = (
    "c8554ec066caecee9f3fd428c5c1c6ca3c784c568a1547f717883440cb83196f"
)
EXPECTED_FIELDS_PROMPT_SHA256 = (
    "f90c21450fba17cfc7b8e31372da95e2062c924a774a80e19fb9d96c00840334"
)
EXPECTED_FIELD_GEOMETRY_SHA256 = (
    "19a3bf874c40c465b7471d73e8234f14a3b1c6c41bd019e5a32552f737824620"
)

EXPECTED_LEGACY_MARGIN_PIXELS = 43_045
EXPECTED_PERMISSION_PIXELS = 40_583
EXPECTED_ALPHA_POSITIVE_PIXELS = 37_369
EXPECTED_ALPHA_FULL_PIXELS = 27_997
EXPECTED_ALPHA_PARTIAL_PIXELS = 9_372
EXPECTED_ACTUAL_CHANGE_PIXELS = 36_676
EXPECTED_BASELINE_COMMA_COMPONENTS = 475
EXPECTED_BASELINE_CLOSED_LOOPS = 167

MAXIMUM_DOMINANT_SPACING_SHARE = 0.40
MAXIMUM_CLOSED_LOOPS_PER_PARCEL = 12
MAXIMUM_TOTAL_CLOSED_LOOPS = 48
MAXIMUM_TOTAL_COMMA_COMPONENTS = 375
MAXIMUM_PARCEL_MEDIAN_RGB_DELTA = 1.0

STEM = "style-candidate-k-v3-semantic-cleanup-proof-v20"
FULL_CONTACT_SCALES = (25, 50)
FIELD_CONTACT_CROPS: dict[str, tuple[int, int, int, int]] = {
    "west": (990, 555, 1265, 820),
    "east": (1180, 530, 1536, 775),
    "south": (1110, 725, 1510, 930),
}
FIELD_CONTACT_SCALES = (200, 400)
PNG_OPTIONS = {"format": "PNG", "compress_level": 9, "optimize": False}


class V20FieldMarginError(RuntimeError):
    """Raised whenever a frozen v20 construction contract is not satisfied."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _require_unlinked_existing_ancestors(path: Path, stop: Path) -> None:
    current = path
    stop_resolved = stop.resolve()
    while True:
        if current.exists() and _is_link_or_junction(current):
            raise V20FieldMarginError(
                f"TEMP path traverses a symlink or junction: {current}"
            )
        if current.resolve() == stop_resolved:
            return
        if current.parent == current:
            raise V20FieldMarginError("TEMP path ancestry escaped its required root")
        current = current.parent


def validate_temp_path(path: Path, *, directory: bool) -> Path:
    """Resolve a TEMP input/output without permitting a path escape or reparse."""
    candidate = path if path.is_absolute() else ROOT / path
    resolved = candidate.resolve()
    temp_parent = TEMP_PARENT.resolve()
    try:
        relative_parts = resolved.relative_to(temp_parent).parts
    except ValueError as exc:
        raise V20FieldMarginError(
            f"v20 TEMP paths must stay below {TEMP_PARENT}: {path}"
        ) from exc
    if not relative_parts:
        raise V20FieldMarginError("the broad tmp/map-production root is not a valid target")
    _require_unlinked_existing_ancestors(candidate, TEMP_PARENT)
    if directory and resolved.exists() and not resolved.is_dir():
        raise V20FieldMarginError(f"TEMP output root is not a directory: {resolved}")
    if not directory and (not resolved.is_file() or _is_link_or_junction(resolved)):
        raise V20FieldMarginError(f"TEMP v19 base is missing or unsafe: {resolved}")
    return resolved


def _validate_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise V20FieldMarginError("expected v19 SHA-256 must be exactly 64 hex digits")
    return normalized


def _load_native_rgb(path: Path, *, role: str) -> np.ndarray:
    try:
        with Image.open(path) as opened:
            opened.load()
            valid = bool(
                opened.format == "PNG"
                and opened.mode == "RGB"
                and opened.size == (k3.WIDTH, k3.HEIGHT)
                and opened.getbands() == ("R", "G", "B")
                and opened.info.get("transparency") is None
                and not opened.info.get("icc_profile")
            )
            if not valid:
                raise V20FieldMarginError(
                    f"{role} must be native {k3.WIDTH}x{k3.HEIGHT} RGB PNG "
                    "without alpha, transparency, or ICC profile"
                )
            return np.asarray(opened, np.uint8).copy()
    except V20FieldMarginError:
        raise
    except Exception as exc:
        raise V20FieldMarginError(f"cannot decode {role}: {path}") from exc


def _geometry_sha256() -> str:
    payload = json.dumps(k3.FIELDS, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def derive_v20_controls(*, source_image: np.ndarray | None = None) -> dict[str, Any]:
    """Derive and verify the exact v20 permission, distance, and alpha fields."""
    masks = k3.derive_masks(source_image=source_image)
    required_counts = {
        "field_legacy_margin_scope": EXPECTED_LEGACY_MARGIN_PIXELS,
        "field_parcel_edit": 57_529,
        "agricultural_corridor_envelope": 1_477,
        "protected_features": 305_163,
        "highland_edit": 241_773,
    }
    if _geometry_sha256() != EXPECTED_FIELD_GEOMETRY_SHA256:
        raise V20FieldMarginError("canonical K3 field geometry changed")
    for name, expected in required_counts.items():
        actual = int(masks[name].sum())
        if actual != expected:
            raise V20FieldMarginError(
                f"K3 mask contract changed for {name}: {actual} != {expected}"
            )
    if len(masks["field_shapes"]) != 8 or len(masks["field_legacy_edits"]) != 8:
        raise V20FieldMarginError("v20 requires exactly eight canonical field parcels")

    road_guard = masks["permission_exclusions"]["forest_highland_road_guard"]
    permission = (
        masks["field_legacy_margin_scope"]
        & ~road_guard
        & ~masks["protected_features"]
    )
    if int(permission.sum()) != EXPECTED_PERMISSION_PIXELS:
        raise V20FieldMarginError(
            f"v20 permission changed: {int(permission.sum())} != "
            f"{EXPECTED_PERMISSION_PIXELS}"
        )

    forbidden = {
        "strict_interiors": masks["field_parcel_edit"],
        "exact_boundary_core": masks["guards"]["field_boundaries"],
        "road_guard_12px": road_guard,
        "corridor": masks["agricultural_corridor_envelope"],
        "capital": masks["guards"]["capital"],
        "protected_features": masks["protected_features"],
    }
    overlaps = {
        name: int(np.count_nonzero(permission & mask))
        for name, mask in forbidden.items()
    }
    if any(overlaps.values()):
        raise V20FieldMarginError(f"v20 permission overlaps a byte lock: {overlaps}")
    if np.any(permission & ~masks["field_legacy_margin_scope"]):
        raise V20FieldMarginError("v20 permission escaped the legacy field margin")

    inward_distance = np.zeros((k3.HEIGHT, k3.WIDTH), np.float32)
    for field_shape in masks["field_shapes"]:
        padded = np.pad(
            field_shape.astype(np.uint8), 1, mode="constant", constant_values=0
        )
        distance = cv2.distanceTransform(padded, cv2.DIST_L2, 5)[1:-1, 1:-1]
        inward_distance = np.maximum(inward_distance, distance)
    normalized = np.clip((inward_distance - 2.0) / 3.0, 0.0, 1.0)
    alpha = (normalized * normalized * (3.0 - 2.0 * normalized)).astype(
        np.float32
    )
    alpha[~permission] = 0.0

    positive = int(np.count_nonzero(alpha > 0.0))
    full = int(np.count_nonzero(alpha == 1.0))
    partial = int(np.count_nonzero((alpha > 0.0) & (alpha < 1.0)))
    alpha_counts = {"positive": positive, "full": full, "partial": partial}
    expected_alpha_counts = {
        "positive": EXPECTED_ALPHA_POSITIVE_PIXELS,
        "full": EXPECTED_ALPHA_FULL_PIXELS,
        "partial": EXPECTED_ALPHA_PARTIAL_PIXELS,
    }
    if alpha_counts != expected_alpha_counts:
        raise V20FieldMarginError(
            f"canonical v20 alpha pixel counts changed: {alpha_counts}"
        )
    if np.any(alpha[~permission] != 0.0):
        raise V20FieldMarginError("v20 alpha escaped its exact permission")
    if np.any(alpha[inward_distance <= 2.0 + 1e-6] != 0.0):
        raise V20FieldMarginError("v20 alpha is nonzero at canonical distance <=2px")
    full_scope = permission & (inward_distance >= 5.0 - 1e-6)
    if not np.any(full_scope) or np.any(alpha[full_scope] != 1.0):
        raise V20FieldMarginError("v20 alpha is not one from 5px inward")
    partial_scope = (alpha > 0.0) & (alpha < 1.0)
    if np.any(partial_scope & ~(
        (inward_distance > 2.0) & (inward_distance < 5.0)
    )):
        raise V20FieldMarginError("v20 partial alpha escaped the 2-5px band")

    return {
        "masks": masks,
        "permission": permission,
        "forbidden": forbidden,
        "inward_distance": inward_distance,
        "alpha": alpha,
        "overlaps": overlaps,
        "alpha_counts": alpha_counts,
    }


def _load_v19_base(
    v19_path: Path,
    expected_sha256: str,
    controls: dict[str, Any],
) -> tuple[Path, np.ndarray, dict[str, Any]]:
    path = validate_temp_path(v19_path, directory=False)
    expected = _validate_sha256(expected_sha256)
    actual = sha256(path)
    if actual != expected:
        raise V20FieldMarginError(
            f"explicit v19 SHA-256 mismatch: expected {expected}, got {actual}"
        )
    base = _load_native_rgb(path, role="v19 base")

    if not V18_REFERENCE.is_file() or sha256(V18_REFERENCE) != EXPECTED_V18_SHA256:
        raise V20FieldMarginError("frozen TEMP v18 lineage reference is missing or changed")
    v18 = _load_native_rgb(V18_REFERENCE, role="v18 lineage reference")
    masks = controls["masks"]
    lineage_change = np.any(base != v18, axis=2)
    lineage_changed_pixels = int(np.count_nonzero(lineage_change))
    outside_highland = int(np.count_nonzero(lineage_change & ~masks["highland_edit"]))
    if lineage_changed_pixels == 0:
        raise V20FieldMarginError("claimed v19 is byte-identical to v18; no highland change exists")
    if outside_highland:
        raise V20FieldMarginError(
            f"claimed v19 changed {outside_highland} pixels outside the highland permission"
        )

    exact_carries = {
        "strict_field_interiors": int(np.count_nonzero(
            lineage_change & masks["field_parcel_edit"]
        )),
        "legacy_field_margins": int(np.count_nonzero(
            lineage_change & masks["field_legacy_margin_scope"]
        )),
        "exact_field_boundary_core": int(np.count_nonzero(
            lineage_change & masks["guards"]["field_boundaries"]
        )),
        "road_guard_12px": int(np.count_nonzero(
            lineage_change
            & masks["permission_exclusions"]["forest_highland_road_guard"]
        )),
        "agricultural_corridor": int(np.count_nonzero(
            lineage_change & masks["agricultural_corridor_envelope"]
        )),
        "capital": int(np.count_nonzero(
            lineage_change & masks["guards"]["capital"]
        )),
    }
    if any(exact_carries.values()):
        raise V20FieldMarginError(
            f"v19 failed byte-exact v18 carry outside highland: {exact_carries}"
        )
    return path, base, {
        "v18_reference": {
            "path": relative(V18_REFERENCE),
            "sha256": EXPECTED_V18_SHA256,
        },
        "v19_changed_pixels_vs_v18": lineage_changed_pixels,
        "v19_changed_pixels_outside_highland_permission": outside_highland,
        "v18_exact_carry_differences": exact_carries,
    }


def _load_fields_donor() -> tuple[np.ndarray, dict[str, Any]]:
    spec = k3.load_spec()
    record = spec.get("donor_slots", {}).get("fields")
    if not isinstance(record, dict):
        raise V20FieldMarginError("K3 fields donor slot is missing")
    expected_contract = {
        "path": EXPECTED_FIELDS_DONOR_PATH,
        "sha256": EXPECTED_FIELDS_DONOR_SHA256,
        "prompt_sha256": EXPECTED_FIELDS_PROMPT_SHA256,
        "native_size": [1254, 1254],
        "mode": "RGB",
        "status": "ready",
    }
    mismatches = {
        key: {"actual": record.get(key), "expected": value}
        for key, value in expected_contract.items()
        if record.get(key) != value
    }
    if mismatches:
        raise V20FieldMarginError(
            f"locked fields-quiet-v2 donor contract changed: {mismatches}"
        )
    try:
        donor = k3.validate_donor_record("fields", record)
    except Exception as exc:
        raise V20FieldMarginError("locked fields-quiet-v2 donor validation failed") from exc
    return donor, record


def _field_median_deltas(
    base: np.ndarray,
    result: np.ndarray,
    permissions: list[np.ndarray],
) -> list[list[float]]:
    return [
        [
            round(float(value), 6)
            for value in (
                np.median(result[permission], axis=0)
                - np.median(base[permission], axis=0)
            )
        ]
        for permission in permissions
    ]


def _construction_metrics(
    base: np.ndarray,
    result: np.ndarray,
    donor_canvas: np.ndarray,
    donor_record: dict[str, Any],
    controls: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bool]]:
    masks = controls["masks"]
    permission = controls["permission"]
    alpha = controls["alpha"]
    changed = np.any(result != base, axis=2)
    donor_changed = np.any(donor_canvas != base, axis=2)

    identity = {
        "actual_change_pixels": int(np.count_nonzero(changed)),
        "changed_outside_exact_permission_pixels": int(np.count_nonzero(
            changed & ~permission
        )),
        "changed_where_alpha_is_zero_pixels": int(np.count_nonzero(
            changed & (alpha == 0.0)
        )),
        "donor_canvas_changed_outside_legacy_field_permissions_pixels": int(
            np.count_nonzero(donor_changed & ~masks["field_parcel_legacy_edit"])
        ),
        "strict_field_interior_differing_pixels": int(np.count_nonzero(
            changed & masks["field_parcel_edit"]
        )),
        "exact_boundary_core_differing_pixels": int(np.count_nonzero(
            changed & masks["guards"]["field_boundaries"]
        )),
        "road_guard_12px_differing_pixels": int(np.count_nonzero(
            changed
            & masks["permission_exclusions"]["forest_highland_road_guard"]
        )),
        "corridor_differing_pixels": int(np.count_nonzero(
            changed & masks["agricultural_corridor_envelope"]
        )),
        "capital_differing_pixels": int(np.count_nonzero(
            changed & masks["guards"]["capital"]
        )),
        "protected_feature_differing_pixels": int(np.count_nonzero(
            changed & masks["protected_features"]
        )),
        "nonfield_differing_pixels": int(np.count_nonzero(
            changed & ~masks["field_parcel_legacy_edit"]
        )),
    }

    cadence_before = k3_audit.parcel_boundary_cadence_metrics(base, masks)
    cadence_after = k3_audit.parcel_boundary_cadence_metrics(result, masks)
    before_commas = sum(
        int(item["small_comma_component_count"])
        for item in cadence_before["parcels"]
    )
    before_loops = sum(
        int(item["closed_loop_count"]) for item in cadence_before["parcels"]
    )
    after_commas = sum(
        int(item["small_comma_component_count"])
        for item in cadence_after["parcels"]
    )
    after_loops = sum(
        int(item["closed_loop_count"]) for item in cadence_after["parcels"]
    )
    maximum_spacing_share = max(
        float(item["dominant_nearest_spacing_share"])
        for item in cadence_after["parcels"]
    )
    maximum_parcel_loops = max(
        int(item["closed_loop_count"]) for item in cadence_after["parcels"]
    )
    cadence = {
        "baseline": {
            **cadence_before,
            "total_small_comma_component_count": before_commas,
            "total_closed_loop_count": before_loops,
        },
        "candidate": {
            **cadence_after,
            "total_small_comma_component_count": after_commas,
            "total_closed_loop_count": after_loops,
            "maximum_dominant_nearest_spacing_share": round(
                maximum_spacing_share, 6
            ),
            "maximum_closed_loop_count_per_parcel": maximum_parcel_loops,
        },
        "thresholds": {
            "maximum_dominant_nearest_spacing_share": MAXIMUM_DOMINANT_SPACING_SHARE,
            "maximum_closed_loops_per_parcel": MAXIMUM_CLOSED_LOOPS_PER_PARCEL,
            "maximum_total_closed_loops": MAXIMUM_TOTAL_CLOSED_LOOPS,
            "maximum_total_small_comma_components": MAXIMUM_TOTAL_COMMA_COMPONENTS,
            "immediate_row_detected": False,
        },
    }

    field_semantic = k3_audit.field_metrics(result, masks["field_edits"])
    strict_content = k3_audit.strict_content_metrics(result, masks)
    low_frequency = k3_audit.low_frequency_blotch_metrics(result, masks)
    donor_median_deltas = [
        item["final_median_delta_from_k2_rgb"]
        for item in donor_record["parcel_records"]
    ]
    final_median_deltas = _field_median_deltas(
        base, result, masks["field_legacy_edits"]
    )
    maximum_donor_median_delta = max(
        abs(float(value))
        for parcel in donor_median_deltas
        for value in parcel
    )
    maximum_final_median_delta = max(
        abs(float(value))
        for parcel in final_median_deltas
        for value in parcel
    )
    lattice_passed = bool(
        len(donor_record.get("parcel_records", [])) == 8
        and all(
            item.get("lattice_diagnostic", {}).get("passed") is True
            for item in donor_record["parcel_records"]
        )
    )
    semantic = {
        "donor_procedural_fields_canvas": donor_record,
        "donor_final_median_delta_rgb_per_parcel": donor_median_deltas,
        "candidate_median_delta_rgb_per_legacy_parcel": final_median_deltas,
        "maximum_absolute_donor_median_rgb_delta": round(
            maximum_donor_median_delta, 6
        ),
        "maximum_absolute_candidate_median_rgb_delta": round(
            maximum_final_median_delta, 6
        ),
        "four_pixel_lattice_passed_all_eight": lattice_passed,
        "field_row_and_furrow_diagnostic": field_semantic,
        "strict_field_raster_and_furrow_diagnostic": strict_content["fields"],
        "corridor_identity_diagnostic": strict_content[
            "agricultural_corridor_envelope"
        ],
        "low_frequency_blotch": low_frequency,
        "parcel_boundary_cadence": cadence,
    }

    gates = {
        "expected_actual_change_pixels": (
            identity["actual_change_pixels"] == EXPECTED_ACTUAL_CHANGE_PIXELS
        ),
        "change_subset_of_exact_permission": (
            identity["changed_outside_exact_permission_pixels"] == 0
            and identity["changed_where_alpha_is_zero_pixels"] == 0
        ),
        "donor_canvas_subset_of_legacy_field_permissions": (
            identity[
                "donor_canvas_changed_outside_legacy_field_permissions_pixels"
            ]
            == 0
        ),
        "strict_interiors_byte_exact": (
            identity["strict_field_interior_differing_pixels"] == 0
        ),
        "exact_boundary_core_byte_exact": (
            identity["exact_boundary_core_differing_pixels"] == 0
        ),
        "road_guard_12px_byte_exact": (
            identity["road_guard_12px_differing_pixels"] == 0
        ),
        "corridor_byte_exact": identity["corridor_differing_pixels"] == 0,
        "capital_byte_exact": identity["capital_differing_pixels"] == 0,
        "protected_features_byte_exact": (
            identity["protected_feature_differing_pixels"] == 0
        ),
        "all_nonfield_pixels_byte_exact": identity["nonfield_differing_pixels"] == 0,
        "baseline_cadence_contract": bool(
            before_commas == EXPECTED_BASELINE_COMMA_COMPONENTS
            and before_loops == EXPECTED_BASELINE_CLOSED_LOOPS
            and cadence_before["immediate_row_detected"] is True
        ),
        "no_immediate_boundary_rows": bool(
            len(cadence_after["parcels"]) == 8
            and not cadence_after["immediate_row_detected"]
            and all(
                item["immediate_row_detected"] is False
                for item in cadence_after["parcels"]
            )
        ),
        "dominant_spacing_share": (
            maximum_spacing_share <= MAXIMUM_DOMINANT_SPACING_SHARE
        ),
        "closed_loops_per_parcel": (
            maximum_parcel_loops <= MAXIMUM_CLOSED_LOOPS_PER_PARCEL
        ),
        "closed_loops_total": after_loops <= MAXIMUM_TOTAL_CLOSED_LOOPS,
        "small_comma_components_total": (
            after_commas <= MAXIMUM_TOTAL_COMMA_COMPONENTS
        ),
        "field_rows_absent": bool(
            len(field_semantic["parcels"]) == 8
            and all(
                item["row_cadence_detected"] is False
                for item in field_semantic["parcels"]
            )
        ),
        "continuous_furrows_absent": bool(
            all(
                int(item["continuous_furrow_count"]) == 0
                for item in field_semantic["parcels"]
            )
            and all(
                int(item["continuous_furrow_segment_count"]) == 0
                for item in strict_content["fields"]["parcels"]
            )
        ),
        "strict_field_raster_gate": bool(strict_content["fields"]["passed"]),
        "corridor_exact_k2_gate": bool(
            strict_content["agricultural_corridor_envelope"]["passed"]
        ),
        "low_frequency_blotch_gate": bool(low_frequency["passed"]),
        "four_pixel_lattice_gate": lattice_passed,
        "donor_median_rgb_delta": (
            maximum_donor_median_delta <= MAXIMUM_PARCEL_MEDIAN_RGB_DELTA
        ),
        "candidate_median_rgb_delta": (
            maximum_final_median_delta <= MAXIMUM_PARCEL_MEDIAN_RGB_DELTA
        ),
    }
    return {"identity": identity, "semantic": semantic}, gates


def _png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, **PNG_OPTIONS)
    return buffer.getvalue()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".new-{os.getpid()}")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _write_png(path: Path, array: np.ndarray, mode: str) -> None:
    image = Image.fromarray(array.astype(np.uint8), mode)
    try:
        _atomic_bytes(path, _png_bytes(image))
    finally:
        image.close()


def _comparison_contact(
    base: Image.Image,
    result: Image.Image,
    *,
    scale_percent: int,
    crop: tuple[int, int, int, int] | None,
    title: str,
) -> Image.Image:
    if crop is None:
        source_panel = base.copy()
        result_panel = result.copy()
        resampling = Image.Resampling.LANCZOS
    else:
        source_panel = base.crop(crop)
        result_panel = result.crop(crop)
        resampling = Image.Resampling.NEAREST
    try:
        factor = scale_percent / 100.0
        size = (
            max(1, int(round(source_panel.width * factor))),
            max(1, int(round(source_panel.height * factor))),
        )
        before = source_panel.resize(size, resampling)
        after = result_panel.resize(size, resampling)
        try:
            header = 32
            contact = Image.new("RGB", (size[0] * 2, size[1] + header), (31, 29, 24))
            contact.paste(before, (0, header))
            contact.paste(after, (size[0], header))
            draw = ImageDraw.Draw(contact)
            draw.text((8, 8), f"v19 | {title}", fill=(236, 225, 194))
            draw.text((size[0] + 8, 8), f"v20 | {scale_percent}%", fill=(236, 225, 194))
            return contact
        finally:
            before.close()
            after.close()
    finally:
        source_panel.close()
        result_panel.close()


def _artifact_record(path: Path) -> dict[str, Any]:
    with Image.open(path) as opened:
        opened.load()
        return {
            "path": relative(path),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "mode": opened.mode,
            "size": list(opened.size),
        }


def _output_paths(output_root: Path) -> dict[str, Path]:
    contacts: dict[str, Path] = {
        f"full_{scale}": output_root / f"{STEM}.full-{scale}.contact.png"
        for scale in FULL_CONTACT_SCALES
    }
    for crop_name in FIELD_CONTACT_CROPS:
        for scale in FIELD_CONTACT_SCALES:
            contacts[f"fields_{crop_name}_{scale}"] = (
                output_root / f"{STEM}.fields-{crop_name}-{scale}.contact.png"
            )
    return {
        "candidate": output_root / f"{STEM}.png",
        "permission": output_root / f"{STEM}.field-margin-permission.png",
        "alpha": output_root / f"{STEM}.field-margin-alpha.png",
        "actual_change": output_root / f"{STEM}.actual-change.png",
        "receipt": output_root / f"{STEM}.provenance-receipt.json",
        **{f"contact:{name}": path for name, path in contacts.items()},
    }


def build_temporary_v20(
    *,
    v19_path: Path,
    expected_v19_sha256: str,
    output_root: Path,
    v19_provenance_receipt: Path | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Build one fully bound TEMP v20 proof and its automated review handoff."""
    persistent = (k3.RAW, k3.FINAL, k3.RECEIPT, k3.AUDIT)
    if any(path.exists() for path in persistent):
        raise V20FieldMarginError(
            "persistent K3 artifacts exist; the TEMP-only v20 tool is no longer eligible"
        )
    resolved_output = validate_temp_path(output_root, directory=True)
    resolved_v19 = validate_temp_path(v19_path, directory=False)
    lineage_receipt_record: dict[str, str] | None = None
    if v19_provenance_receipt is not None:
        candidate = (
            v19_provenance_receipt
            if v19_provenance_receipt.is_absolute()
            else ROOT / v19_provenance_receipt
        ).resolve()
        try:
            candidate.relative_to(ROOT.resolve())
        except ValueError as exc:
            raise V20FieldMarginError(
                "v19 provenance receipt must stay inside the repository"
            ) from exc
        if not candidate.is_file() or _is_link_or_junction(candidate):
            raise V20FieldMarginError("v19 provenance receipt is missing or unsafe")
        lineage_receipt_record = {
            "path": relative(candidate),
            "sha256": sha256(candidate),
        }
    try:
        resolved_output.relative_to(resolved_v19.parent)
    except ValueError:
        pass
    else:
        if resolved_output == resolved_v19.parent:
            raise V20FieldMarginError("v20 output root cannot overwrite the v19 input directory")

    paths = _output_paths(resolved_output)
    existing = [path for path in paths.values() if path.exists()]
    if existing and not replace:
        raise V20FieldMarginError(
            "refusing to overwrite existing TEMP v20 artifacts without "
            f"--replace-temporary: {[relative(path) for path in existing]}"
        )

    controls = derive_v20_controls()
    base_path, base, lineage = _load_v19_base(
        resolved_v19, expected_v19_sha256, controls
    )
    donor, donor_slot = _load_fields_donor()
    masks = controls["masks"]
    if k3.permission_outside_crop_pixels(
        masks["field_parcel_legacy_edit"], donor_slot
    ):
        raise V20FieldMarginError("legacy field permissions escape the donor crop")
    try:
        donor_canvas, shifts, donor_record = k3.procedural_fields_canvas(
            base,
            donor,
            donor_slot,
            masks["field_legacy_edits"],
        )
    except Exception as exc:
        raise V20FieldMarginError(
            "same-coordinate procedural_fields_canvas construction failed"
        ) from exc
    if donor_record.get("texture_authority") != "fields-quiet-v2":
        raise V20FieldMarginError("procedural field canvas changed texture authority")
    if donor_record.get("spatial_pixel_reassignment_used") is not False:
        raise V20FieldMarginError("procedural field canvas used spatial reassignment")
    if donor_record.get("sorting_or_distribution_remap_used") is not False:
        raise V20FieldMarginError("procedural field canvas used distribution remapping")

    result = k3.composite_with_alpha(base, donor_canvas, controls["alpha"])
    metrics, gates = _construction_metrics(
        base, result, donor_canvas, donor_record, controls
    )
    failed = [name for name, passed in gates.items() if not passed]
    if failed:
        raise V20FieldMarginError(
            f"TEMP v20 automated gates failed; no artifacts emitted: {failed}"
        )

    resolved_output.mkdir(parents=True, exist_ok=True)
    _write_png(paths["candidate"], result, "RGB")
    _write_png(paths["permission"], controls["permission"].astype(np.uint8) * 255, "L")
    _write_png(paths["alpha"], np.rint(controls["alpha"] * 255.0), "L")
    changed = np.any(result != base, axis=2)
    _write_png(paths["actual_change"], changed.astype(np.uint8) * 255, "L")

    base_image = Image.fromarray(base, "RGB")
    result_image = Image.fromarray(result, "RGB")
    try:
        for scale in FULL_CONTACT_SCALES:
            contact = _comparison_contact(
                base_image,
                result_image,
                scale_percent=scale,
                crop=None,
                title="full",
            )
            try:
                _atomic_bytes(paths[f"contact:full_{scale}"], _png_bytes(contact))
            finally:
                contact.close()
        for crop_name, crop in FIELD_CONTACT_CROPS.items():
            for scale in FIELD_CONTACT_SCALES:
                contact = _comparison_contact(
                    base_image,
                    result_image,
                    scale_percent=scale,
                    crop=crop,
                    title=f"fields-{crop_name}",
                )
                try:
                    _atomic_bytes(
                        paths[f"contact:fields_{crop_name}_{scale}"],
                        _png_bytes(contact),
                    )
                finally:
                    contact.close()
    finally:
        base_image.close()
        result_image.close()

    artifact_keys = [key for key in paths if key != "receipt"]
    artifacts = {key: _artifact_record(paths[key]) for key in artifact_keys}
    receipt = {
        "schema_version": "1.0.0",
        "id": "style-candidate-k-v3-semantic-cleanup-temporary-proof-v20",
        "status": "passed-automated-pending-root-vision",
        "temporary_review_only": True,
        "persistent_candidate_emitted": False,
        "golden_accepted": False,
        "v19_input": {
            "path": relative(base_path),
            "expected_sha256": _validate_sha256(expected_v19_sha256),
            "actual_sha256": sha256(base_path),
            "caller_bound_at_invocation": True,
            "provenance_receipt": lineage_receipt_record,
        },
        "lineage": lineage,
        "builder": {
            "path": relative(Path(__file__).resolve()),
            "sha256": sha256(Path(__file__).resolve()),
        },
        "k3_builder": {
            "path": relative(Path(k3.__file__).resolve()),
            "sha256": sha256(Path(k3.__file__).resolve()),
        },
        "k3_audit": {
            "path": relative(Path(k3_audit.__file__).resolve()),
            "sha256": sha256(Path(k3_audit.__file__).resolve()),
        },
        "fields_donor": {
            "path": donor_slot["path"],
            "sha256": donor_slot["sha256"],
            "prompt_path": donor_slot["prompt_path"],
            "prompt_sha256": donor_slot["prompt_sha256"],
            "validated_by_existing_k3_donor_contract": True,
        },
        "construction": {
            "semantic_change": "legacy field-parcel margin cadence cleanup only",
            "permission_definition": (
                "field_legacy_margin_scope & ~forest_highland_road_guard "
                "& ~protected_features"
            ),
            "permission_pixels": int(controls["permission"].sum()),
            "canonical_inward_alpha": {
                "distance_source": "maximum per-pixel OpenCV L2 distance inside each canonical field polygon",
                "zero_through_px_inclusive": 2.0,
                "transition": "smoothstep",
                "full_from_px_inclusive": 5.0,
                "positive_pixels": controls["alpha_counts"]["positive"],
                "partial_pixels": controls["alpha_counts"]["partial"],
                "full_pixels": controls["alpha_counts"]["full"],
            },
            "procedural_fields_canvas_color_match_shifts": shifts,
            "spatial_pixel_reassignment_used": False,
            "sorting_or_distribution_remap_used": False,
            "global_transform_applied": False,
        },
        "metrics": metrics,
        "automated_gates": gates,
        "failed_gates": [],
        "artifacts": artifacts,
        "vision_handoff": {
            "required": True,
            "decision_authority": "Root Vision",
            "acceptance_threshold": 94,
            "immediate_failure_policy": "zero immediate failures",
            "review_views": [
                artifacts[key]
                for key in artifacts
                if key.startswith("contact:")
            ],
            "candidate_must_not_be_promoted_before_acceptance": True,
        },
    }
    _atomic_bytes(
        paths["receipt"],
        (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v19-base", type=Path, required=True)
    parser.add_argument("--v19-sha256", required=True)
    parser.add_argument("--temporary-output-root", type=Path, required=True)
    parser.add_argument(
        "--v19-provenance-receipt",
        type=Path,
        help=(
            "stable exact v19 reconstruction receipt; promotion remains fail-closed "
            "when this is omitted"
        ),
    )
    parser.add_argument(
        "--replace-temporary",
        action="store_true",
        help="atomically replace this tool's fixed files in the explicit TEMP root",
    )
    args = parser.parse_args()
    receipt = build_temporary_v20(
        v19_path=args.v19_base,
        expected_v19_sha256=args.v19_sha256,
        output_root=args.temporary_output_root,
        v19_provenance_receipt=args.v19_provenance_receipt,
        replace=args.replace_temporary,
    )
    candidate = receipt["artifacts"]["candidate"]
    print(json.dumps({
        "status": receipt["status"],
        "path": candidate["path"],
        "sha256": candidate["sha256"],
        "receipt": relative(
            validate_temp_path(args.temporary_output_root, directory=True)
            / f"{STEM}.provenance-receipt.json"
        ),
        "persistent_candidate_emitted": False,
    }, indent=2))


if __name__ == "__main__":
    main()
