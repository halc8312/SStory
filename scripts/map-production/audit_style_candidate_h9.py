#!/usr/bin/env python3
"""Run the fail-closed automated audit for Candidate H9.

H9 is a protected deterministic edit of H5. The audit verifies the localized
edit contract independently at full resolution and records useful H5
non-regression diagnostics. Golden eligibility, however, retains the original
H4/B1 whole-image palette and downsample thresholds without substitution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, deque
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageStat

import audit_style_candidate_h4 as h4
import render_candidate_h9_dense_flat_plan as h9


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FINAL = h9.FORMAL_MASTER_PATH
DEFAULT_H5 = h9.DEFAULT_H5
DEFAULT_MASK = h9.FORMAL_MASK_PATH
DEFAULT_CONTACT = h9.FORMAL_CONTACT_PATH
DEFAULT_PROVENANCE = h9.FORMAL_PROVENANCE_PATH
DEFAULT_ATLAS = h9.DEFAULT_ATLAS
DEFAULT_ATLAS_RECEIPT = (
    REPO_ROOT
    / "world/map-production/prompts/"
    "phase5-cartographic-material-atlas-v1.generation-receipt.json"
)
DEFAULT_ATLAS_BRIEF = (
    REPO_ROOT
    / "world/map-production/prompts/"
    "phase5-cartographic-material-atlas-v1.normalized-generation-brief.txt"
)
DEFAULT_REFERENCE_B1 = h4.DEFAULT_REFERENCE_B1
DEFAULT_REPORT = (
    REPO_ROOT
    / "world/map-production/qa/automated/"
    "style-candidate-h-v9-dense-flat-plan.json"
)

EXPECTED_SHA256 = {
    "final": "bd813e93287b15fe12e654ca5d28633a6902bbbdb3c6d81b0c3e69816a7b2580",
    "h5": h9.H5_SHA256,
    "semantic_mask": (
        "c8b0e9350f55042245237ac3e7936b38bbf178cd4203ffc8c382d3f2d44e4deb"
    ),
    "contact_sheet": (
        "187e64221d22096ea4295b375fa81439bbcf7d8a07ddb3b47b72104f3a44c394"
    ),
    "provenance": (
        "3ac21e9273f787c13c382a3ec422203efa2fde149101b3b0cc09850ebbc8b86e"
    ),
    "atlas": h9.ATLAS_SHA256,
    "atlas_receipt": (
        "bd02d77f972ee1146e6381aa7f769fe7caf0c49b5304d7de58f6ed4ad9c1cd28"
    ),
    "atlas_brief": (
        "f585872376d79dd59afae1d51ae10a86e3271a4208074d8bef7e095241b72cd8"
    ),
    "reference_b1": h4.EXPECTED_SHA256["reference_b1"],
    "renderer": (
        "4f47a61aab66b41a484487d3ed6a75b70ccaa722d821c470184969b70b97ff46"
    ),
}

EXPECTED_MASK_COUNTS = {
    "protected": 1_479_836,
    "city": 50_611,
    "port": 29_101,
    "forest_gap_fill": 13_316,
}
EXPECTED_CHANGED_PIXELS = 92_742
EXPECTED_ALLOWED_PIXELS = 93_028
MASK_COLORS = {
    "protected": (0, 0, 0),
    "forest_gap_fill": (58, 126, 68),
    "port": (224, 154, 52),
    "city": (202, 58, 50),
}
LOCAL_ZONES = {
    "city": h9.CITY_BOUNDS,
    "port": h9.PORT_BOUNDS,
    "forest": h9.FOREST_BOUNDS,
}


class H9AuditError(ValueError):
    """Raised when H9 evidence is missing, mutable, or internally invalid."""


def _assert_locked(path: Path, expected_sha256: str, label: str) -> None:
    try:
        h4._assert_input(path, expected_sha256, label)
    except h4.H4AuditError as exc:
        raise H9AuditError(str(exc)) from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise H9AuditError(f"{label} must be valid UTF-8 JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise H9AuditError(f"{label} must be a JSON object")
    return document


def _intersects(left: Sequence[int], right: Sequence[int]) -> bool:
    return not (
        left[2] <= right[0]
        or right[2] <= left[0]
        or left[3] <= right[1]
        or right[3] <= left[1]
    )


def _validate_atlas_receipt(
    atlas: Image.Image,
    receipt: dict[str, Any],
    brief_path: Path,
) -> dict[str, Any]:
    limitations = receipt.get("provenance_limitations", {})
    required_limitations = (
        limitations.get("raw_invocation_prompt_available") is False
        and limitations.get("raw_invocation_prompt_reconstructed") is False
        and limitations.get("exact_image_model_identifier_available") is False
        and limitations.get("generation_identifier_available") is False
        and limitations.get("generation_timestamp_utc") is None
    )
    artifact = receipt.get("artifact", {})
    artifact_valid = artifact == {
        "path": h4._relative(DEFAULT_ATLAS),
        "sha256": EXPECTED_SHA256["atlas"],
        "bytes": DEFAULT_ATLAS.stat().st_size,
        "format": "PNG",
        "mode": "RGB",
        "width": 1536,
        "height": 1024,
        "alpha_or_transparency_present": False,
        "embedded_color_profile_present": False,
    }
    crops = receipt.get("accepted_crops", [])
    crop_records: list[dict[str, Any]] = []
    crop_rectangles: list[list[int]] = []
    expected_crop_ids = {
        "h9_forest_high_frequency_source",
        "connected_forest",
        "cultivated_hatching",
        "wetland",
        "neutral_parchment",
        "flat_rock_hachure",
    }
    crops_valid = (
        len(crops) == 6
        and {crop.get("id") for crop in crops} == expected_crop_ids
    )
    for crop in crops:
        rectangle = crop.get("rect_px")
        if (
            not isinstance(rectangle, list)
            or len(rectangle) != 4
            or not all(isinstance(value, int) for value in rectangle)
            or not (0 <= rectangle[0] < rectangle[2] <= atlas.width)
            or not (0 <= rectangle[1] < rectangle[3] <= atlas.height)
        ):
            crops_valid = False
            continue
        patch = atlas.crop(tuple(rectangle))
        try:
            raw_rgb_sha256 = hashlib.sha256(patch.tobytes()).hexdigest()
        finally:
            patch.close()
        width = rectangle[2] - rectangle[0]
        height = rectangle[3] - rectangle[1]
        passed = (
            crop.get("width") == width
            and crop.get("height") == height
            and crop.get("raw_rgb_sha256") == raw_rgb_sha256
            and bool(crop.get("approved_use"))
        )
        crops_valid = crops_valid and passed
        crop_rectangles.append(rectangle)
        crop_records.append(
            {
                "id": crop.get("id"),
                "rect_px": rectangle,
                "raw_rgb_sha256": raw_rgb_sha256,
                "passed": passed,
            }
        )

    rejected = receipt.get("rejected_zones", [])
    rejected_valid = len(rejected) >= 3
    rejected_records: list[dict[str, Any]] = []
    for zone in rejected:
        rectangle = zone.get("rect_px")
        in_bounds = (
            isinstance(rectangle, list)
            and len(rectangle) == 4
            and all(isinstance(value, int) for value in rectangle)
            and 0 <= rectangle[0] < rectangle[2] <= atlas.width
            and 0 <= rectangle[1] < rectangle[3] <= atlas.height
        )
        disjoint = bool(in_bounds) and not any(
            _intersects(rectangle, crop) for crop in crop_rectangles
        )
        passed = (
            in_bounds
            and disjoint
            and zone.get("policy") == "must_not_sample"
            and bool(zone.get("reason"))
        )
        rejected_valid = rejected_valid and passed
        rejected_records.append(
            {
                "id": zone.get("id"),
                "rect_px": rectangle,
                "disjoint_from_accepted_crops": disjoint,
                "passed": passed,
            }
        )

    try:
        brief = brief_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise H9AuditError("normalized atlas brief must be valid UTF-8") from exc
    required_brief_phrases = (
        "raw ImageGen invocation transcript",
        "five canonical",
        "rejected zones",
        "never be sampled",
    )
    brief_valid = all(phrase in brief for phrase in required_brief_phrases)
    whole_image = receipt.get("whole_image_acceptance", {})
    whole_image_rejected = (
        whole_image.get("accepted") is False
        and whole_image.get("decision") == "partial-material-crops-only"
    )
    passed = all(
        (
            required_limitations,
            artifact_valid,
            crops_valid,
            rejected_valid,
            brief_valid,
            whole_image_rejected,
        )
    )
    return {
        "passed": passed,
        "raw_invocation_absences_recorded_without_inference": required_limitations,
        "artifact_record_exact": artifact_valid,
        "normalized_brief_required_phrases_present": brief_valid,
        "whole_image_explicitly_rejected": whole_image_rejected,
        "accepted_crops": crop_records,
        "rejected_zones": rejected_records,
    }


def _full_resolution_protection(
    source: Image.Image,
    candidate: Image.Image,
    semantic: Image.Image,
) -> dict[str, Any]:
    mask_counts = Counter(semantic.get_flattened_data())
    unexpected_colors = [
        list(color) for color in sorted(set(mask_counts) - set(MASK_COLORS.values()))
    ]
    changed_pixels = 0
    protected_violation_pixels = 0
    changed_by_zone = {name: 0 for name in MASK_COLORS}
    zone_by_color = {color: name for name, color in MASK_COLORS.items()}
    for source_pixel, candidate_pixel, mask_pixel in zip(
        source.get_flattened_data(),
        candidate.get_flattened_data(),
        semantic.get_flattened_data(),
    ):
        if source_pixel == candidate_pixel:
            continue
        changed_pixels += 1
        zone_name = zone_by_color.get(mask_pixel)
        if zone_name is None or zone_name == "protected":
            protected_violation_pixels += 1
        else:
            changed_by_zone[zone_name] += 1
    counts = {
        name: mask_counts.get(color, 0) for name, color in MASK_COLORS.items()
    }
    allowed_pixels = sum(
        value for name, value in counts.items() if name != "protected"
    )
    passed = (
        not unexpected_colors
        and counts == EXPECTED_MASK_COUNTS
        and allowed_pixels == EXPECTED_ALLOWED_PIXELS
        and changed_pixels == EXPECTED_CHANGED_PIXELS
        and protected_violation_pixels == 0
        and changed_by_zone["city"] == 50_609
        and changed_by_zone["port"] == 28_817
        and changed_by_zone["forest_gap_fill"] == 13_316
    )
    return {
        "passed": passed,
        "method": "exact tuple comparison for every full-resolution RGB pixel",
        "canvas_pixels": candidate.width * candidate.height,
        "semantic_color_counts": counts,
        "unexpected_semantic_colors": unexpected_colors,
        "allowed_edit_pixels": allowed_pixels,
        "protected_pixels": counts["protected"],
        "changed_pixels": changed_pixels,
        "changed_pixels_by_zone": changed_by_zone,
        "protected_violation_pixels": protected_violation_pixels,
        "protected_pixel_equality_percent": (
            100.0
            if counts["protected"] == 0
            else round(
                100.0
                * (counts["protected"] - protected_violation_pixels)
                / counts["protected"],
                12,
            )
        ),
        "locked_expectations": {
            "semantic_color_counts": EXPECTED_MASK_COUNTS,
            "allowed_edit_pixels": EXPECTED_ALLOWED_PIXELS,
            "changed_pixels": EXPECTED_CHANGED_PIXELS,
            "protected_violation_pixels": 0,
        },
    }


def _component_sizes_for_colors(
    image: Image.Image,
    semantic: Image.Image,
    *,
    bounds: tuple[int, int, int, int],
    zone_color: tuple[int, int, int],
    accepted_colors: frozenset[tuple[int, int, int]],
) -> list[int]:
    left, top, right, bottom = bounds
    width = right - left
    height = bottom - top
    image_pixels = image.load()
    semantic_pixels = semantic.load()
    active = bytearray(width * height)
    for y in range(top, bottom):
        row = (y - top) * width
        for x in range(left, right):
            if (
                semantic_pixels[x, y] == zone_color
                and image_pixels[x, y] in accepted_colors
            ):
                active[row + x - left] = 1
    sizes: list[int] = []
    for index, value in enumerate(active):
        if value == 0:
            continue
        active[index] = 0
        queue: deque[int] = deque((index,))
        size = 0
        while queue:
            current = queue.popleft()
            size += 1
            x = current % width
            y = current // width
            neighbors = []
            if x:
                neighbors.append(current - 1)
            if x + 1 < width:
                neighbors.append(current + 1)
            if y:
                neighbors.append(current - width)
            if y + 1 < height:
                neighbors.append(current + width)
            for neighbor in neighbors:
                if active[neighbor]:
                    active[neighbor] = 0
                    queue.append(neighbor)
        sizes.append(size)
    return sorted(sizes)


def _urban_metrics(
    candidate: Image.Image,
    semantic: Image.Image,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    fill_colors = frozenset(h9.CITY_COLORS)
    city_sizes = _component_sizes_for_colors(
        candidate,
        semantic,
        bounds=h9.CITY_BOUNDS,
        zone_color=MASK_COLORS["city"],
        accepted_colors=fill_colors,
    )
    port_sizes = _component_sizes_for_colors(
        candidate,
        semantic,
        bounds=h9.PORT_BOUNDS,
        zone_color=MASK_COLORS["port"],
        accepted_colors=fill_colors,
    )
    city_components = [size for size in city_sizes if size >= 2]
    port_components = [size for size in port_sizes if size >= 2]
    stats = provenance.get("render_stats", {})
    district_counts = stats.get("city_district_building_counts", [])
    city_passed = (
        300 <= len(city_components) <= 450
        and max(city_components, default=0) <= 1_000
        and stats.get("city_flat_building_footprints") == 354
        and stats.get("city_district_count") == 8
        and len(district_counts) == 8
        and min(district_counts, default=0) >= 30
        and max(district_counts, default=0) <= 70
        and len(set(district_counts)) >= 6
        and stats.get("city_recursive_leaf_blocks") == 80
        and stats.get("city_ragged_ring_streets") == 3
        and stats.get("city_radial_avenues") == 8
        and stats.get("city_courtyards_markets_parks") == 7
        and stats.get("city_gate_count") == 5
        and stats.get("city_side_faces") == 0
        and stats.get("city_directional_shadows") == 0
    )
    port_passed = (
        45 <= len(port_components) <= 80
        and max(port_components, default=0) <= 100
        and stats.get("port_flat_building_footprints") == 55
        and stats.get("port_warehouse_footprints") == 5
        and stats.get("port_courtyards") == 3
        and stats.get("port_lane_paths") == 7
        and stats.get("port_flat_piers") == 8
        and stats.get("port_boat_hull_outlines") == 0
        and stats.get("port_side_faces") == 0
        and stats.get("port_directional_shadows") == 0
    )
    return {
        "passed": city_passed and port_passed,
        "city": {
            "passed": city_passed,
            "independent_exact_fill_components_area_ge_2": len(city_components),
            "independent_exact_fill_component_pixels": sum(city_components),
            "independent_largest_exact_fill_component_pixels": max(
                city_components, default=0
            ),
            "generator_stats": {
                key: value for key, value in stats.items() if key.startswith("city_")
            },
        },
        "port": {
            "passed": port_passed,
            "independent_exact_fill_components_area_ge_2": len(port_components),
            "independent_exact_fill_component_pixels": sum(port_components),
            "independent_largest_exact_fill_component_pixels": max(
                port_components, default=0
            ),
            "generator_stats": {
                key: value for key, value in stats.items() if key.startswith("port_")
            },
        },
    }


def _forest_metrics(
    source: Image.Image,
    semantic: Image.Image,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    water = h9.h8._water_mask(source)
    city = h9._city_mask()
    port = h9._port_mask()
    before, gap, after = h9._infer_canopy_edit(source, water, city, port)
    try:
        gap_pixels = gap.load()
        semantic_pixels = semantic.load()
        mask_matches = True
        gap_count = 0
        for y in range(source.height):
            for x in range(source.width):
                is_gap = gap_pixels[x, y] != 0
                is_semantic_gap = (
                    semantic_pixels[x, y] == MASK_COLORS["forest_gap_fill"]
                )
                if is_gap:
                    gap_count += 1
                if is_gap != is_semantic_gap:
                    mask_matches = False
        before_metrics = h9._component_metrics(before)
        after_metrics = h9._component_metrics(after)
    finally:
        water.close()
        city.close()
        port.close()
        before.close()
        gap.close()
        after.close()

    canopy_report = provenance.get("canopy_component_audit", {})
    stats = provenance.get("render_stats", {})
    component_reduction = (
        before_metrics["component_count"] - after_metrics["component_count"]
    )
    weighted_before = before_metrics[
        "area_weighted_component_circularity_area_ge_8"
    ]
    weighted_after = after_metrics[
        "area_weighted_component_circularity_area_ge_8"
    ]
    weighted_reduction = 100.0 * (weighted_before - weighted_after) / weighted_before
    round_key = (
        "round_stamp_like_components_area_8_to_500_circularity_ge_0_52"
    )
    round_before = before_metrics[round_key]
    round_after = after_metrics[round_key]
    round_reduction = 100.0 * (round_before - round_after) / round_before
    passed = (
        mask_matches
        and gap_count == EXPECTED_MASK_COUNTS["forest_gap_fill"]
        and before_metrics == canopy_report.get("before")
        and after_metrics == canopy_report.get("after")
        and component_reduction >= 250
        and weighted_reduction >= 20.0
        and round_reduction >= 20.0
        and stats.get("forest_gap_fill_pixels") == gap_count
        and stats.get("forest_existing_canopy_pixels_modified") == 0
        and stats.get("forest_new_round_stamps") == 0
        and stats.get("forest_new_heavy_outlines") == 0
        and stats.get("forest_atlas_high_frequency_strength") <= 0.08
    )
    return {
        "passed": passed,
        "semantic_gap_mask_matches_independent_reconstruction": mask_matches,
        "gap_fill_pixels": gap_count,
        "before": before_metrics,
        "after": after_metrics,
        "component_count_reduction": component_reduction,
        "area_weighted_circularity_reduction_percent": round(
            weighted_reduction, 6
        ),
        "round_stamp_like_component_reduction_percent": round(
            round_reduction, 6
        ),
        "thresholds": {
            "minimum_component_count_reduction": 250,
            "minimum_area_weighted_circularity_reduction_percent": 20.0,
            "minimum_round_stamp_like_component_reduction_percent": 20.0,
            "maximum_atlas_high_frequency_strength": 0.08,
        },
    }


def _local_readability_record(image: Image.Image, bounds: Sequence[int]) -> dict[str, Any]:
    crop = image.crop(tuple(bounds)).convert("L")
    try:
        result: dict[str, Any] = {
            "native": {
                "luma_entropy_bits": round(crop.entropy(), 6),
                "luma_rms_contrast": round(ImageStat.Stat(crop).stddev[0], 6),
            },
            "scales": [],
        }
        for scale in (0.5, 0.25):
            small = crop.resize(
                (round(crop.width * scale), round(crop.height * scale)),
                Image.Resampling.LANCZOS,
            )
            try:
                result["scales"].append(
                    {
                        "scale": scale,
                        "width": small.width,
                        "height": small.height,
                        "luma_entropy_bits": round(small.entropy(), 6),
                        "luma_rms_contrast": round(
                            ImageStat.Stat(small).stddev[0], 6
                        ),
                    }
                )
            finally:
                small.close()
        return result
    finally:
        crop.close()


def _edited_zone_readability(
    candidate: Image.Image,
    source: Image.Image,
) -> dict[str, Any]:
    zones: list[dict[str, Any]] = []
    for zone_id, bounds in LOCAL_ZONES.items():
        candidate_record = _local_readability_record(candidate, bounds)
        source_record = _local_readability_record(source, bounds)
        candidate_25 = candidate_record["scales"][1]
        source_25 = source_record["scales"][1]
        rms_improvement = (
            candidate_25["luma_rms_contrast"]
            - source_25["luma_rms_contrast"]
        )
        zones.append(
            {
                "id": zone_id,
                "bounds_px": list(bounds),
                "candidate": candidate_record,
                "h5_source": source_record,
                "candidate_minus_h5_25_percent_rms_contrast": round(
                    rms_improvement, 6
                ),
                "passed": rms_improvement > 0.0,
            }
        )
    return {
        "passed": all(zone["passed"] for zone in zones),
        "method": (
            "Each edited review crop must improve 25% LANCZOS luma RMS "
            "contrast over the locked H5 source. This supplemental gate does "
            "not replace the whole-image H4 Golden thresholds."
        ),
        "zones": zones,
    }


def _contact_sheet_metrics(
    candidate: Image.Image,
    contact_path: Path,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    expected, panels = h9._contact_sheet(candidate)
    with Image.open(contact_path) as opened:
        opened.load()
        actual = opened.convert("RGB")
    try:
        identical = expected.tobytes() == actual.tobytes()
        contract = {
            "format": opened.format,
            "mode": opened.mode,
            "width": opened.width,
            "height": opened.height,
        }
    finally:
        expected.close()
        actual.close()
    panels_match = panels == provenance.get("contact_panels")
    return {
        "passed": identical and panels_match and contract == {
            "format": "PNG",
            "mode": "RGB",
            "width": 912,
            "height": 1320,
        },
        "pixel_identical_to_deterministic_reconstruction": identical,
        "panel_manifest_matches_provenance": panels_match,
        "image_contract": contract,
        "panel_count": len(panels),
    }


def _validate_provenance(
    provenance: dict[str, Any],
    artifacts: dict[str, Path],
) -> dict[str, Any]:
    outputs = provenance.get("outputs", {})
    generated_by = provenance.get("generated_by", {})
    expected_outputs = {
        "master": {
            **h4._artifact(artifacts["final"]),
            "width": 1536,
            "height": 1024,
            "mode": "RGB",
        },
        "semantic_mask": h4._artifact(artifacts["semantic_mask"]),
        "contact_sheet": h4._artifact(artifacts["contact_sheet"]),
    }
    equality = provenance.get("protected_pixel_equality", {})
    passed = (
        provenance.get("status")
        == "formal_candidate_pending_automated_and_independent_vision_qa"
        and generated_by.get("id") == h9.GENERATOR_ID
        and generated_by.get("path") == h4._relative(Path(h9.__file__))
        and generated_by.get("sha256") == EXPECTED_SHA256["renderer"]
        and outputs == expected_outputs
        and provenance.get("inputs", {}).get("h5_edit_target", {}).get("sha256")
        == EXPECTED_SHA256["h5"]
        and provenance.get("inputs", {}).get("atlas_forest_material", {}).get(
            "sha256"
        )
        == EXPECTED_SHA256["atlas"]
        and provenance.get("inputs", {}).get("atlas_forest_material", {}).get(
            "path"
        )
        == h4._relative(DEFAULT_ATLAS)
        and provenance.get("inputs", {}).get("atlas_crop_px") == [0, 0, 512, 480]
        and provenance.get("semantic_mask", {}).get("allowed_edit_pixels")
        == EXPECTED_ALLOWED_PIXELS
        and equality.get("protected_pixels") == EXPECTED_MASK_COUNTS["protected"]
        and equality.get("protected_equal_pixels")
        == EXPECTED_MASK_COUNTS["protected"]
        and equality.get("protected_violation_pixels") == 0
        and equality.get("protected_pixel_equality_percent") == 100.0
        and equality.get("changed_pixels") == EXPECTED_CHANGED_PIXELS
        and provenance.get("self_vision_review", {}).get("acceptance_authority")
        is False
        and provenance.get("self_vision_review", {}).get(
            "independent_review_required"
        )
        is True
    )
    return {
        "passed": passed,
        "formal_status": provenance.get("status"),
        "generated_by": generated_by,
        "outputs_exact": outputs == expected_outputs,
        "self_review_has_no_acceptance_authority": (
            provenance.get("self_vision_review", {}).get("acceptance_authority")
            is False
        ),
    }


def audit(
    *,
    final_path: Path = DEFAULT_FINAL,
    h5_path: Path = DEFAULT_H5,
    mask_path: Path = DEFAULT_MASK,
    contact_path: Path = DEFAULT_CONTACT,
    provenance_path: Path = DEFAULT_PROVENANCE,
    atlas_path: Path = DEFAULT_ATLAS,
    atlas_receipt_path: Path = DEFAULT_ATLAS_RECEIPT,
    atlas_brief_path: Path = DEFAULT_ATLAS_BRIEF,
    reference_b1_path: Path = DEFAULT_REFERENCE_B1,
    report_path: Path = DEFAULT_REPORT,
    replace: bool = False,
) -> dict[str, Any]:
    if report_path.exists() and not replace:
        raise H9AuditError(f"refusing to overwrite existing output: {report_path}")
    inputs = {
        "final": final_path,
        "h5": h5_path,
        "semantic_mask": mask_path,
        "contact_sheet": contact_path,
        "provenance": provenance_path,
        "atlas": atlas_path,
        "atlas_receipt": atlas_receipt_path,
        "atlas_brief": atlas_brief_path,
        "reference_b1": reference_b1_path,
        "renderer": Path(h9.__file__).resolve(),
    }
    for label, path in inputs.items():
        _assert_locked(path, EXPECTED_SHA256[label], label)

    provenance = _load_json(provenance_path, "H9 provenance")
    receipt = _load_json(atlas_receipt_path, "material atlas receipt")
    try:
        final_record, candidate = h4.inspect_png(final_path)
        h5_record, source = h4.inspect_png(h5_path)
        mask_record, semantic = h4.inspect_png(mask_path)
        contact_record, contact_image = h4.inspect_png(contact_path)
        atlas_record, atlas = h4.inspect_png(atlas_path)
        b1_record, reference_b1 = h4.inspect_png(reference_b1_path)
    except h4.H4AuditError as exc:
        raise H9AuditError(str(exc)) from exc
    contact_image.close()
    try:
        required_rgb_png = {
            "format": "PNG",
            "mode": "RGB",
            "bit_depth": 8,
            "png_color_type": 2,
            "alpha_or_transparency_present": False,
        }
        expected_sizes = {
            "final": (1536, 1024),
            "h5": (1536, 1024),
            "semantic_mask": (1536, 1024),
            "contact_sheet": (912, 1320),
            "atlas": (1536, 1024),
            "reference_b1": (1536, 1024),
        }
        records = {
            "final": final_record,
            "h5": h5_record,
            "semantic_mask": mask_record,
            "contact_sheet": contact_record,
            "atlas": atlas_record,
            "reference_b1": b1_record,
        }
        record_results = {
            name: (
                all(record[key] == value for key, value in required_rgb_png.items())
                and (record["width"], record["height"]) == expected_sizes[name]
            )
            for name, record in records.items()
        }
        image_contract = {
            "passed": all(record_results.values()),
            "required": required_rgb_png,
            "expected_sizes": {
                key: list(value) for key, value in expected_sizes.items()
            },
            "records_passed": record_results,
            "records": records,
        }
        atlas_receipt = _validate_atlas_receipt(
            atlas, receipt, atlas_brief_path
        )
        formal_provenance = _validate_provenance(provenance, inputs)
        protection = _full_resolution_protection(source, candidate, semantic)
        urban = _urban_metrics(candidate, semantic, provenance)
        forest = _forest_metrics(source, semantic, provenance)
        contact_sheet = _contact_sheet_metrics(
            candidate, contact_path, provenance
        )
        boundary = h4.boundary_metrics(candidate)
        palette_b1 = h4.palette_continuity_metrics(candidate, reference_b1)
        palette_b1["reference"] = "Candidate B1 locked Golden palette reference"
        palette_h5 = h4.palette_continuity_metrics(candidate, source)
        palette_h5["reference"] = "Candidate H5 protected edit source"
        repetition = h4.exact_repetition_metrics(candidate)
        downsample = h4.downsample_readability_metrics(candidate)
        edited_zone_readability = _edited_zone_readability(candidate, source)
    finally:
        candidate.close()
        source.close()
        semantic.close()
        atlas.close()
        reference_b1.close()

    automated_gates = {
        "sha256_locked_inputs": True,
        "image_contract_alpha_profile": image_contract["passed"],
        "atlas_origin_and_crop_receipt": atlas_receipt["passed"],
        "formal_provenance_contract": formal_provenance["passed"],
        "h5_full_resolution_protected_pixel_equality": protection["passed"],
        "city_and_port_density_geometry": urban["passed"],
        "forest_gap_join_and_de_repetition": forest["passed"],
        "contact_sheet_deterministic_reconstruction": contact_sheet["passed"],
        "boundary_proxy": boundary["passed"],
        "palette_continuity_with_b1": palette_b1["passed"],
        "no_large_exact_repetition_proxy": repetition["passed"],
        "downsample_readability_proxy": downsample["passed"],
        "edited_zone_25_percent_rms_improvement": (
            edited_zone_readability["passed"]
        ),
    }
    failed_gates = [name for name, passed in automated_gates.items() if not passed]
    status = "passed" if not failed_gates else "failed"
    report = {
        "schema_version": "1.0.0",
        "id": "style-candidate-h-v9-dense-flat-plan-automated-audit",
        "status": status,
        "scope": "automated artifact, protected-edit, and raster proxies only",
        "decision": (
            "automated-gates-passed-pending-independent-vision"
            if status == "passed"
            else "automated-gates-failed-not-eligible-for-golden"
        ),
        "golden_eligible": status == "passed",
        "threshold_policy": {
            "legacy_h4_b1_golden_thresholds_unchanged": True,
            "h5_non_regression_is_supplemental_only": True,
            "failed_legacy_gates_cannot_be_overridden_by_local_improvement": True,
        },
        "failed_gates": failed_gates,
        "generated_by": h4._artifact(Path(__file__).resolve()),
        "artifacts": {
            name: h4._artifact(path) for name, path in inputs.items()
        },
        "image_contract": image_contract,
        "atlas_receipt": atlas_receipt,
        "formal_provenance": formal_provenance,
        "full_resolution_protection": protection,
        "urban_plan_metrics": urban,
        "forest_metrics": forest,
        "contact_sheet": contact_sheet,
        "boundary": boundary,
        "palette_continuity_b1_required": palette_b1,
        "palette_continuity_h5_supplemental": palette_h5,
        "exact_repetition": repetition,
        "downsample_readability_required": downsample,
        "edited_zone_readability_supplemental": edited_zone_readability,
        "automated_gates": automated_gates,
        "vision_handoff": {
            "status": (
                "required_after_automated_gates_pass"
                if status == "passed"
                else "blocked_by_required_automated_gate_failure"
            ),
            "independent_reviewer_count_required": 2,
            "minimum_score_each": 94,
            "self_review_is_not_independent_acceptance": True,
            "automated_claims_about_perspective_text_or_semantics": None,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final", type=Path, default=DEFAULT_FINAL)
    parser.add_argument("--h5", type=Path, default=DEFAULT_H5)
    parser.add_argument("--mask", type=Path, default=DEFAULT_MASK)
    parser.add_argument("--contact", type=Path, default=DEFAULT_CONTACT)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--atlas", type=Path, default=DEFAULT_ATLAS)
    parser.add_argument(
        "--atlas-receipt", type=Path, default=DEFAULT_ATLAS_RECEIPT
    )
    parser.add_argument("--atlas-brief", type=Path, default=DEFAULT_ATLAS_BRIEF)
    parser.add_argument("--reference-b1", type=Path, default=DEFAULT_REFERENCE_B1)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit(
            final_path=args.final.resolve(),
            h5_path=args.h5.resolve(),
            mask_path=args.mask.resolve(),
            contact_path=args.contact.resolve(),
            provenance_path=args.provenance.resolve(),
            atlas_path=args.atlas.resolve(),
            atlas_receipt_path=args.atlas_receipt.resolve(),
            atlas_brief_path=args.atlas_brief.resolve(),
            reference_b1_path=args.reference_b1.resolve(),
            report_path=args.report.resolve(),
            replace=args.replace,
        )
    except (H9AuditError, OSError, ValueError) as exc:
        print(f"Candidate H9 automated audit could not run: {exc}")
        return 2
    print(
        f"Candidate H9 automated audit {report['status']}: "
        f"sha256={report['artifacts']['final']['sha256']} "
        f"protected_violations="
        f"{report['full_resolution_protection']['protected_violation_pixels']} "
        f"failed_gates={','.join(report['failed_gates']) or 'none'}"
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
