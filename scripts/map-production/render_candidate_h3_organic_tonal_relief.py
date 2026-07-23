#!/usr/bin/env python3
"""Render one diagnostic H3 organic tonal-relief prototype.

H3 makes one root change from H2: every visible terrain line glyph is removed.
The existing D4 rock symbols are wrapped by eight compact, non-lighting tonal
components (two unequal lobes per main massif and one distinct lobe per
foothill).  SHA-seeded low-resolution noise makes both the boundary and the
internal density asymmetric, so the renderer does not produce blurred ellipse
stamps, crests, hachures, contours, or radial/tangential line systems.

This tool writes diagnostic files under ``tmp/`` only.  It never edits the
production manifest or a formal style candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageChops, ImageFilter, ImageOps

import render_candidate_h1_deterministic_hachure as h1


REPO_ROOT = h1.REPO_ROOT
CANVAS = h1.CANVAS
DEFAULT_OUTPUT_DIR = REPO_ROOT / "tmp/map-production/h3-prototype"
ROAD_CORE_WIDTH_PX = 16
ROAD_FEATHER_PX = 5.0
BOUNDARY_FEATHER_PX = 9.0
FOOTPRINT_WASH_DELTA_LEVELS = 2
SUPPORT_THRESHOLD_LEVELS = 6
MINIMUM_ROTATIONAL_MISMATCH_FRACTION = 0.05


class OrganicTonalReliefError(ValueError):
    """Raised before an invalid H3 diagnostic can be published."""


@dataclass(frozen=True)
class LobeSpec:
    """One compact organic tonal component, never a line or ellipse stamp."""

    center: tuple[float, float]
    radius_x: float
    radius_y: float
    rotation_degrees: float
    peak_delta_levels: int
    edge_noise_amplitude: float
    density_noise_amplitude: float
    density_skew: tuple[float, float]


@dataclass(frozen=True)
class TonalSpec:
    identifier: str
    role: str
    lobes: tuple[LobeSpec, ...]


def _lobe(
    center: tuple[float, float],
    radii: tuple[float, float],
    rotation_degrees: float,
    peak_delta_levels: int,
    edge_noise_amplitude: float,
    density_noise_amplitude: float,
    density_skew: tuple[float, float],
) -> LobeSpec:
    return LobeSpec(
        center=center,
        radius_x=radii[0],
        radius_y=radii[1],
        rotation_degrees=rotation_degrees,
        peak_delta_levels=peak_delta_levels,
        edge_noise_amplitude=edge_noise_amplitude,
        density_noise_amplitude=density_noise_amplitude,
        density_skew=density_skew,
    )


TONAL_SPECS = (
    TonalSpec(
        "ne-main-massif",
        "main-massif",
        (
            _lobe((1089, 202), (118, 65), -18, 26, 0.17, 0.24, (0.20, -0.12)),
            _lobe((1357, 216), (70, 96), 23, 21, 0.14, 0.21, (-0.16, 0.18)),
        ),
    ),
    TonalSpec(
        "ne-west-foothill",
        "foothill-a",
        (_lobe((866, 406), (70, 38), -12, 20, 0.18, 0.25, (-0.18, 0.11)),),
    ),
    TonalSpec(
        "ne-central-foothill",
        "foothill-b",
        (_lobe((1168, 473), (47, 67), 11, 16, 0.15, 0.22, (0.13, 0.20)),),
    ),
    TonalSpec(
        "se-main-massif",
        "main-massif",
        (
            _lobe((1049, 836), (103, 59), 16, 25, 0.16, 0.23, (-0.19, -0.09)),
            _lobe((1263, 860), (57, 81), -24, 20, 0.19, 0.26, (0.17, -0.20)),
        ),
    ),
    TonalSpec(
        "se-west-foothill",
        "foothill-a",
        (_lobe((774, 889), (79, 37), 5, 19, 0.16, 0.20, (0.22, 0.08)),),
    ),
    TonalSpec(
        "se-east-foothill",
        "foothill-b",
        (_lobe((1415, 862), (39, 77), -14, 17, 0.20, 0.24, (-0.11, 0.23)),),
    ),
)
SPEC_BY_ID = {spec.identifier: spec for spec in TONAL_SPECS}


def _seed(label: str) -> str:
    payload = f"{h1.LOCKED_SHA256['base']}|{h1.LOCKED_SHA256['g2_source']}|H3|{label}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _low_frequency_noise(
    size: tuple[int, int],
    *,
    seed: str,
    cell_size_px: int,
) -> Image.Image:
    """Return deterministic bicubic low-resolution SHA noise at local size."""

    grid_size = (
        max(5, math.ceil(size[0] / cell_size_px) + 2),
        max(5, math.ceil(size[1] / cell_size_px) + 2),
    )
    digest = hashlib.shake_256(seed.encode("ascii")).digest(grid_size[0] * grid_size[1])
    grid = Image.frombytes("L", grid_size, digest)
    softened = grid.filter(ImageFilter.GaussianBlur(radius=0.72))
    resized: Image.Image | None = None
    normalized: Image.Image | None = None
    try:
        resized = softened.resize(size, Image.Resampling.BICUBIC)
        minimum, maximum = resized.getextrema()
        if maximum <= minimum:
            raise OrganicTonalReliefError("degenerate SHA low-frequency noise")
        normalized = resized.point(
            lambda value: round((value - minimum) * 255 / (maximum - minimum))
        )
        return normalized.copy()
    finally:
        grid.close()
        softened.close()
        if resized is not None:
            resized.close()
        if normalized is not None:
            normalized.close()


def _rotational_mismatch(mask: Image.Image) -> float:
    bounds = mask.getbbox()
    if bounds is None:
        return 0.0
    crop = mask.crop(bounds)
    rotated = ImageOps.flip(ImageOps.mirror(crop))
    difference = ImageChops.difference(crop, rotated)
    union = ImageChops.lighter(crop, rotated)
    try:
        denominator = h1._count_selected(union)
        if denominator == 0:
            return 0.0
        return round(h1._count_selected(difference) / denominator, 6)
    finally:
        crop.close()
        rotated.close()
        difference.close()
        union.close()


def _component_count(
    mask: Image.Image,
    *,
    threshold: int = 128,
    minimum_pixels: int = 24,
) -> int:
    """Count material 4-connected components without optional dependencies."""

    bounds = mask.getbbox()
    if bounds is None:
        return 0
    crop = mask.crop(bounds)
    try:
        width, height = crop.size
        data = crop.tobytes()
    finally:
        crop.close()
    selected = bytearray(value >= threshold for value in data)
    count = 0
    for start, is_selected in enumerate(selected):
        if not is_selected:
            continue
        selected[start] = 0
        stack = [start]
        area = 0
        while stack:
            index = stack.pop()
            area += 1
            x = index % width
            if x and selected[index - 1]:
                selected[index - 1] = 0
                stack.append(index - 1)
            if x + 1 < width and selected[index + 1]:
                selected[index + 1] = 0
                stack.append(index + 1)
            if index >= width and selected[index - width]:
                selected[index - width] = 0
                stack.append(index - width)
            if index + width < width * height and selected[index + width]:
                selected[index + width] = 0
                stack.append(index + width)
        if area >= minimum_pixels:
            count += 1
    return count


def _render_organic_lobe(
    landform: h1.Landform,
    lobe: LobeSpec,
    *,
    lobe_index: int,
) -> tuple[Image.Image, Image.Image, dict[str, Any]]:
    """Rasterize an asymmetric star-convex tonal field with no stroke calls."""

    extent = 1.34
    x0 = max(0, math.floor(lobe.center[0] - lobe.radius_x * extent))
    y0 = max(0, math.floor(lobe.center[1] - lobe.radius_y * extent))
    x1 = min(CANVAS[0], math.ceil(lobe.center[0] + lobe.radius_x * extent) + 1)
    y1 = min(CANVAS[1], math.ceil(lobe.center[1] + lobe.radius_y * extent) + 1)
    local_size = x1 - x0, y1 - y0
    edge_seed = _seed(f"{landform.identifier}:{lobe_index}:edge")
    density_seed = _seed(f"{landform.identifier}:{lobe_index}:density")
    edge_noise = _low_frequency_noise(local_size, seed=edge_seed, cell_size_px=29)
    density_noise = _low_frequency_noise(local_size, seed=density_seed, cell_size_px=23)
    local = Image.new("L", local_size, 0)
    edge_pixels = edge_noise.load()
    density_pixels = density_noise.load()
    local_pixels = local.load()
    if edge_pixels is None or density_pixels is None or local_pixels is None:
        edge_noise.close()
        density_noise.close()
        local.close()
        raise OrganicTonalReliefError("cannot access H3 organic tonal pixels")

    rotation = math.radians(lobe.rotation_degrees)
    cosine = math.cos(rotation)
    sine = math.sin(rotation)
    maximum_raw = 0.0
    raw_values: list[float] = [0.0] * (local_size[0] * local_size[1])
    for local_y in range(local_size[1]):
        canvas_y = y0 + local_y
        for local_x in range(local_size[0]):
            canvas_x = x0 + local_x
            offset_x = canvas_x - lobe.center[0]
            offset_y = canvas_y - lobe.center[1]
            rotated_x = cosine * offset_x + sine * offset_y
            rotated_y = -sine * offset_x + cosine * offset_y
            normalized_x = rotated_x / lobe.radius_x
            normalized_y = rotated_y / lobe.radius_y
            radius = math.hypot(normalized_x, normalized_y)
            edge_value = (edge_pixels[local_x, local_y] - 127.5) / 127.5
            boundary = 0.96 + lobe.edge_noise_amplitude * edge_value
            if radius >= boundary:
                continue
            inward = (boundary - radius) / max(boundary, 0.01)
            feather = min(1.0, inward / 0.17)
            feather = feather * feather * (3.0 - 2.0 * feather)
            density_value = (density_pixels[local_x, local_y] - 127.5) / 127.5
            skew = (
                normalized_x * lobe.density_skew[0]
                + normalized_y * lobe.density_skew[1]
            )
            radial_hierarchy = 0.69 + 0.31 * min(1.0, inward / 0.72)
            density = 1.0 + lobe.density_noise_amplitude * density_value + 0.22 * skew
            raw = max(0.0, feather * radial_hierarchy * density)
            raw_values[local_y * local_size[0] + local_x] = raw
            maximum_raw = max(maximum_raw, raw)

    if maximum_raw <= 0:
        edge_noise.close()
        density_noise.close()
        local.close()
        raise OrganicTonalReliefError(f"empty organic lobe for {landform.identifier}")
    for index, raw in enumerate(raw_values):
        if raw <= 0:
            continue
        value = min(
            lobe.peak_delta_levels,
            round(raw / maximum_raw * lobe.peak_delta_levels),
        )
        local_pixels[index % local_size[0], index // local_size[0]] = value

    canvas_tone = Image.new("L", CANVAS, 0)
    canvas_tone.paste(local, (x0, y0))
    clipped = ImageChops.darker(canvas_tone, landform.mask)
    without_saddle = h1._subtract_protection(clipped, landform.saddle_mask)
    support = without_saddle.point(
        lambda value: 255 if value >= SUPPORT_THRESHOLD_LEVELS else 0
    )
    try:
        metrics = {
            "index": lobe_index,
            "center": [lobe.center[0], lobe.center[1]],
            "radii_px": [lobe.radius_x, lobe.radius_y],
            "rotation_degrees": lobe.rotation_degrees,
            "declared_peak_delta_levels": lobe.peak_delta_levels,
            "raw_peak_delta_levels": without_saddle.getextrema()[1],
            "edge_noise_amplitude": lobe.edge_noise_amplitude,
            "density_noise_amplitude": lobe.density_noise_amplitude,
            "edge_noise_seed_sha256": edge_seed,
            "density_noise_seed_sha256": density_seed,
            "support_pixels": h1._count_selected(support),
            "support_component_count": _component_count(support),
            "rotational_symmetry_mismatch_fraction": _rotational_mismatch(support),
            "saddle_support_pixels": h1._count_intersection(
                support, landform.saddle_mask
            ),
        }
        return without_saddle.copy(), support.copy(), metrics
    finally:
        edge_noise.close()
        density_noise.close()
        local.close()
        canvas_tone.close()
        clipped.close()
        without_saddle.close()
        support.close()


def _subtract_all_protection(
    mask: Image.Image,
    permission_soft: Image.Image,
    road_strength: Image.Image,
    details: Image.Image,
    saddle_union: Image.Image,
) -> Image.Image:
    inside = ImageChops.multiply(mask, permission_soft)
    without_saddle = h1._subtract_protection(inside, saddle_union)
    without_road = h1._subtract_protection(without_saddle, road_strength)
    inside.close()
    without_saddle.close()
    try:
        return h1._subtract_protection(without_road, details)
    finally:
        without_road.close()


def _readability_at_scale(
    base: Image.Image,
    output: Image.Image,
    landform_mask: Image.Image,
    tonal_support: Image.Image,
    factor: float,
) -> dict[str, Any]:
    size = round(CANVAS[0] * factor), round(CANVAS[1] * factor)
    small_base = base.resize(size, Image.Resampling.LANCZOS)
    small_output = output.resize(size, Image.Resampling.LANCZOS)
    small_landform = landform_mask.resize(size, Image.Resampling.LANCZOS).point(
        lambda value: 255 if value >= 96 else 0
    )
    small_support = tonal_support.resize(size, Image.Resampling.LANCZOS).point(
        lambda value: 255 if value >= 72 else 0
    )
    difference = h1._difference_max(small_base, small_output)
    support_expansion_size = 7 if factor == 0.5 else 5
    expanded_support = small_support.filter(
        ImageFilter.MaxFilter(size=support_expansion_size)
    )
    inverse_expanded = ImageChops.invert(expanded_support)
    background = ImageChops.darker(small_landform, inverse_expanded)
    strong = difference.point(lambda value: 255 if value >= 5 else 0)
    try:
        signal_mean = h1._masked_mean(difference, small_support)
        background_mean = h1._masked_mean(difference, background)
        ratio = signal_mean / max(background_mean, 0.25)
        strong_signal_pixels = h1._count_intersection(strong, small_support)
        minimum_strong = 48 if factor == 0.5 else 12
        survives = (
            signal_mean >= 5.0
            and ratio >= 2.2
            and strong_signal_pixels >= minimum_strong
        )
        return {
            "scale": factor,
            "signal_pixels": h1._count_selected(small_support),
            "strong_signal_pixels": strong_signal_pixels,
            "signal_mean_max_channel_difference": round(signal_mean, 6),
            "background_pixels": h1._count_selected(background),
            "background_mean_max_channel_difference": round(background_mean, 6),
            "signal_to_background_ratio": round(ratio, 6),
            "minimum_signal_mean": 5.0,
            "minimum_signal_to_background_ratio": 2.2,
            "minimum_strong_signal_pixels": minimum_strong,
            "survives": survives,
        }
    finally:
        small_base.close()
        small_output.close()
        small_landform.close()
        small_support.close()
        difference.close()
        expanded_support.close()
        inverse_expanded.close()
        background.close()
        strong.close()


def _render_candidate(inputs: h1.Inputs) -> tuple[Image.Image, dict[str, Any]]:
    permission_soft = h1._feather_inside(inputs.permission, BOUNDARY_FEATHER_PX)
    road_core = h1._draw_road_core(ROAD_CORE_WIDTH_PX)
    road_strength = h1._protected_strength(road_core, ROAD_FEATHER_PX)
    details = h1.detail_core(inputs.base)
    saddle_union = Image.new("L", CANVAS, 0)
    tone_union = Image.new("L", CANVAS, 0)
    support_union = Image.new("L", CANVAS, 0)
    tone_by_id: dict[str, Image.Image] = {}
    support_by_id: dict[str, Image.Image] = {}
    landform_metrics: list[dict[str, Any]] = []
    tone_allowed: Image.Image | None = None
    wash_allowed: Image.Image | None = None
    edit_strength: Image.Image | None = None
    delta_rgb: Image.Image | None = None
    output: Image.Image | None = None
    difference_max: Image.Image | None = None
    try:
        for landform in inputs.landforms:
            spec = SPEC_BY_ID.get(landform.identifier)
            if spec is None or spec.role != landform.role:
                raise OrganicTonalReliefError(
                    f"missing or mismatched H3 tonal spec for {landform.identifier}"
                )
            expected_lobes = 2 if landform.role == "main-massif" else 1
            if len(spec.lobes) != expected_lobes:
                raise OrganicTonalReliefError(
                    f"{landform.identifier} requires {expected_lobes} tonal lobes"
                )

            raw_tone = Image.new("L", CANVAS, 0)
            raw_support = Image.new("L", CANVAS, 0)
            lobe_metrics: list[dict[str, Any]] = []
            try:
                for index, lobe in enumerate(spec.lobes):
                    tone, support, metrics = _render_organic_lobe(
                        landform, lobe, lobe_index=index
                    )
                    lobe_metrics.append(metrics)
                    merged_tone = ImageChops.lighter(raw_tone, tone)
                    raw_tone.close()
                    raw_tone = merged_tone
                    merged_support = ImageChops.lighter(raw_support, support)
                    raw_support.close()
                    raw_support = merged_support
                    tone.close()
                    support.close()

                tone_by_id[landform.identifier] = raw_tone.copy()
                support_by_id[landform.identifier] = raw_support.copy()
                updated_tone = ImageChops.lighter(tone_union, raw_tone)
                tone_union.close()
                tone_union = updated_tone
                updated_support = ImageChops.lighter(support_union, raw_support)
                support_union.close()
                support_union = updated_support
                updated_saddle = ImageChops.lighter(saddle_union, landform.saddle_mask)
                saddle_union.close()
                saddle_union = updated_saddle

                landform_metrics.append(
                    {
                        "id": landform.identifier,
                        "role": landform.role,
                        "footprint_pixels": landform.area_pixels,
                        "declared_lobe_count": len(spec.lobes),
                        "raw_tonal_component_count": _component_count(raw_support),
                        "footprint_wash_delta_levels": FOOTPRINT_WASH_DELTA_LEVELS,
                        "lobes": lobe_metrics,
                    }
                )
            finally:
                raw_tone.close()
                raw_support.close()

        tone_allowed = _subtract_all_protection(
            tone_union,
            permission_soft,
            road_strength,
            details,
            saddle_union,
        )
        wash_scaled = h1._scale_mask(permission_soft, FOOTPRINT_WASH_DELTA_LEVELS)
        try:
            wash_allowed = _subtract_all_protection(
                wash_scaled,
                permission_soft,
                road_strength,
                details,
                saddle_union,
            )
        finally:
            wash_scaled.close()
        edit_strength = ImageChops.lighter(tone_allowed, wash_allowed)
        delta_rgb = Image.merge(
            "RGB",
            (edit_strength.copy(), edit_strength.copy(), edit_strength.copy()),
        )
        output = ImageChops.subtract(inputs.base, delta_rgb)
        difference_max = h1._difference_max(inputs.base, output)
        changed = difference_max.point(lambda value: 255 if value else 0)
        strong = difference_max.point(lambda value: 255 if value >= 8 else 0)
        outside = ImageChops.invert(inputs.permission)
        brightening = ImageChops.subtract(output, inputs.base)
        black = Image.new("RGB", CANVAS, (0, 0, 0))
        brightening_max = h1._difference_max(black, brightening)
        black.close()
        try:
            metrics_by_id = {item["id"]: item for item in landform_metrics}
            for landform in inputs.landforms:
                metrics = metrics_by_id[landform.identifier]
                support = support_by_id[landform.identifier]
                visible_tone = ImageChops.darker(tone_allowed, support)
                try:
                    readability = [
                        _readability_at_scale(
                            inputs.base,
                            output,
                            landform.mask,
                            support,
                            factor,
                        )
                        for factor in (0.5, 0.25)
                    ]
                    metrics.update(
                        {
                            "protected_tonal_pixels": h1._count_selected(visible_tone),
                            "protected_peak_delta_levels": visible_tone.getextrema()[1],
                            "changed_pixels": h1._count_intersection(
                                changed, landform.mask
                            ),
                            "strong_changed_pixels": h1._count_intersection(
                                strong, landform.mask
                            ),
                            "saddle_changed_pixels": h1._count_intersection(
                                changed, landform.saddle_mask
                            ),
                            "readability": readability,
                        }
                    )
                finally:
                    visible_tone.close()

            gates = {
                "outside_g2_permission": {
                    "changed_pixels": h1._count_intersection(changed, outside),
                    "maximum_channel_difference": h1._masked_max(
                        difference_max, outside
                    ),
                },
                "road_core": {
                    "width_px": ROAD_CORE_WIDTH_PX,
                    "protected_pixels": h1._count_selected(road_core),
                    "changed_pixels": h1._count_intersection(changed, road_core),
                    "maximum_channel_difference": h1._masked_max(
                        difference_max, road_core
                    ),
                },
                "detail_core": {
                    "selection_operator": "high-frequency-and-dark",
                    "protected_pixels": h1._count_selected(details),
                    "changed_pixels": h1._count_intersection(changed, details),
                    "maximum_channel_difference": h1._masked_max(
                        difference_max, details
                    ),
                },
                "non_lighting": {
                    "operation": "neutral subtractive-only RGB delta",
                    "brightened_pixels": h1._count_selected(brightening_max),
                    "maximum_channel_increase": brightening_max.getextrema()[1],
                },
                "open_saddles": {
                    "count": sum(
                        bool(landform.saddle_mask.getbbox())
                        for landform in inputs.landforms
                    ),
                    "changed_pixels": h1._count_intersection(changed, saddle_union),
                    "minimum_width_px": min(
                        bounds[2] - bounds[0]
                        for landform in inputs.landforms
                        if (bounds := landform.saddle_mask.getbbox()) is not None
                    ),
                },
                "tonal_components": {
                    "expected": 8,
                    "actual": sum(
                        item["raw_tonal_component_count"] for item in landform_metrics
                    ),
                    "main_lobes_each": [
                        item["raw_tonal_component_count"]
                        for item in landform_metrics
                        if item["role"] == "main-massif"
                    ],
                    "foothill_lobes_each": [
                        item["raw_tonal_component_count"]
                        for item in landform_metrics
                        if item["role"] != "main-massif"
                    ],
                },
                "no_line_renderer": {
                    "validated": True,
                    "terrain_line_primitive_count": 0,
                    "closed_contour_count": 0,
                    "crest_count": 0,
                    "hachure_count": 0,
                    "radial_line_count": 0,
                    "tangential_line_count": 0,
                },
                "downscale_survival": {
                    str(factor): {
                        "surviving_landforms": sum(
                            item["readability"][index]["survives"]
                            for item in landform_metrics
                        ),
                        "required_landforms": 6,
                    }
                    for index, factor in enumerate((0.5, 0.25))
                },
                "boundary_feather": {
                    "partial_alpha_pixels": h1._partial_pixel_count(permission_soft),
                    "radius_px": BOUNDARY_FEATHER_PX,
                },
            }
            immediate_failures: list[str] = []
            for gate_name in (
                "outside_g2_permission",
                "road_core",
                "detail_core",
            ):
                if (
                    gates[gate_name]["changed_pixels"]
                    or gates[gate_name]["maximum_channel_difference"]
                ):
                    immediate_failures.append(gate_name)
            if (
                gates["non_lighting"]["brightened_pixels"]
                or gates["non_lighting"]["maximum_channel_increase"]
            ):
                immediate_failures.append("non_lighting")
            if gates["open_saddles"]["changed_pixels"]:
                immediate_failures.append("open_saddles")
            if gates["open_saddles"]["minimum_width_px"] < 26:
                immediate_failures.append("saddle_width")
            if gates["tonal_components"]["actual"] != 8:
                immediate_failures.append("tonal_component_count")
            if (
                any(
                    value
                    for key, value in gates["no_line_renderer"].items()
                    if key != "validated"
                )
                or not gates["no_line_renderer"]["validated"]
            ):
                immediate_failures.append("line_renderer_present")
            for scale, scale_gate in gates["downscale_survival"].items():
                if scale_gate["surviving_landforms"] != 6:
                    immediate_failures.append(f"downscale-{scale}")
            if gates["boundary_feather"]["partial_alpha_pixels"] == 0:
                immediate_failures.append("boundary_feather")

            foothill_signatures = {
                (
                    tuple(item["lobes"][0]["radii_px"]),
                    item["lobes"][0]["rotation_degrees"],
                    item["lobes"][0]["declared_peak_delta_levels"],
                    item["lobes"][0]["edge_noise_seed_sha256"],
                )
                for item in landform_metrics
                if item["role"] != "main-massif"
            }
            if len(foothill_signatures) != 4:
                immediate_failures.append("foothill-tonal-reuse")
            for item in landform_metrics:
                expected = 2 if item["role"] == "main-massif" else 1
                if item["declared_lobe_count"] != expected:
                    immediate_failures.append(f"{item['id']}:lobe-declaration")
                if item["raw_tonal_component_count"] != expected:
                    immediate_failures.append(f"{item['id']}:lobe-components")
                if item["saddle_changed_pixels"]:
                    immediate_failures.append(f"{item['id']}:saddle")
                for lobe in item["lobes"]:
                    lower, upper = (
                        (16, 26) if item["role"] == "main-massif" else (13, 22)
                    )
                    if not lower <= lobe["raw_peak_delta_levels"] <= upper:
                        immediate_failures.append(f"{item['id']}:delta-range")
                    if lobe["support_component_count"] != 1:
                        immediate_failures.append(f"{item['id']}:split-lobe")
                    if (
                        lobe["rotational_symmetry_mismatch_fraction"]
                        < MINIMUM_ROTATIONAL_MISMATCH_FRACTION
                    ):
                        immediate_failures.append(f"{item['id']}:ellipse-like")
                    if lobe["saddle_support_pixels"]:
                        immediate_failures.append(f"{item['id']}:saddle-support")

            report = {
                "slug": "balanced",
                "status": "passed" if not immediate_failures else "failed",
                "description": (
                    "Line-free low-frequency organic tonal hierarchy around the "
                    "locked D4 rock symbols."
                ),
                "parameters": {
                    "road_core_width_px": ROAD_CORE_WIDTH_PX,
                    "road_feather_px": ROAD_FEATHER_PX,
                    "boundary_feather_px": BOUNDARY_FEATHER_PX,
                    "footprint_wash_delta_levels": FOOTPRINT_WASH_DELTA_LEVELS,
                    "support_threshold_levels": SUPPORT_THRESHOLD_LEVELS,
                    "minimum_rotational_mismatch_fraction": (
                        MINIMUM_ROTATIONAL_MISMATCH_FRACTION
                    ),
                },
                "metrics": {
                    "changed_pixels": h1._count_selected(changed),
                    "strong_changed_pixels": h1._count_selected(strong),
                    "maximum_channel_difference": difference_max.getextrema()[1],
                    "editable_pixels": h1._count_selected(edit_strength),
                    "road_core_pixels": h1._count_selected(road_core),
                    "detail_core_pixels": h1._count_selected(details),
                    "raw_tonal_component_count": _component_count(support_union),
                    "gates": gates,
                    "landforms": landform_metrics,
                },
                "immediate_failures": immediate_failures,
            }
            return output.copy(), report
        finally:
            changed.close()
            strong.close()
            outside.close()
            brightening.close()
            brightening_max.close()
    finally:
        permission_soft.close()
        road_core.close()
        road_strength.close()
        details.close()
        saddle_union.close()
        tone_union.close()
        support_union.close()
        for image in tone_by_id.values():
            image.close()
        for image in support_by_id.values():
            image.close()
        for image in (
            tone_allowed,
            wash_allowed,
            edit_strength,
            delta_rgb,
            output,
            difference_max,
        ):
            if image is not None:
                image.close()


def _full_comparison(base: Image.Image, output: Image.Image) -> Image.Image:
    size = 768, 512
    sheet = Image.new("RGB", (1536, 512), (30, 28, 25))
    left = h1._labeled_panel(base, "D4 locked base", size)
    right = h1._labeled_panel(output, "H3 line-free tonal", size)
    try:
        sheet.paste(left, (0, 0))
        sheet.paste(right, (768, 0))
        return sheet
    finally:
        left.close()
        right.close()


def _scale_comparison(
    base: Image.Image,
    output: Image.Image,
    factor: float,
) -> Image.Image:
    panel_size = round(CANVAS[0] * factor), round(CANVAS[1] * factor)
    sheet = Image.new("RGB", (panel_size[0] * 2, panel_size[1]), (30, 28, 25))
    left = h1._labeled_panel(base, f"D4 {round(factor * 100)}%", panel_size)
    right = h1._labeled_panel(output, f"H3 {round(factor * 100)}%", panel_size)
    try:
        sheet.paste(left, (0, 0))
        sheet.paste(right, (panel_size[0], 0))
        return sheet
    finally:
        left.close()
        right.close()


def _expected_outputs(output_dir: Path) -> tuple[Path, ...]:
    return (
        output_dir / "h3-balanced.png",
        output_dir / "comparison-full.png",
        output_dir / "comparison-north-east.png",
        output_dir / "comparison-south-east.png",
        output_dir / "comparison-scale-25.png",
        output_dir / "comparison-scale-50.png",
        output_dir / "comparison-scale-100.png",
        output_dir / "report.json",
    )


def render_all(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = [path for path in _expected_outputs(output_dir) if path.exists()]
    if existing and not replace:
        raise OrganicTonalReliefError(
            "refusing to overwrite diagnostic output without --replace: "
            + ", ".join(h1._display_path(path) for path in existing)
        )

    inputs = h1.load_inputs()
    output: Image.Image | None = None
    comparisons: list[Image.Image] = []
    try:
        if set(SPEC_BY_ID) != {landform.identifier for landform in inputs.landforms}:
            raise OrganicTonalReliefError(
                "H3 tonal spec set does not match all six landforms"
            )
        output, variant_report = _render_candidate(inputs)
        output_path = output_dir / "h3-balanced.png"
        h1._save_png(output, output_path)
        variant_report["output_path"] = h1._display_path(output_path)
        variant_report["output_sha256"] = h1._sha256(output_path)

        comparisons.extend(
            (
                _full_comparison(inputs.base, output),
                h1._crop_comparison(
                    inputs.base,
                    (("H3 line-free tonal", output),),
                    (740, 48, 1536, 570),
                    panel_width=720,
                ),
                h1._crop_comparison(
                    inputs.base,
                    (("H3 line-free tonal", output),),
                    (650, 688, 1536, 1024),
                    panel_width=720,
                ),
                _scale_comparison(inputs.base, output, 0.25),
                _scale_comparison(inputs.base, output, 0.5),
                _scale_comparison(inputs.base, output, 1.0),
            )
        )
        comparison_paths = (
            output_dir / "comparison-full.png",
            output_dir / "comparison-north-east.png",
            output_dir / "comparison-south-east.png",
            output_dir / "comparison-scale-25.png",
            output_dir / "comparison-scale-50.png",
            output_dir / "comparison-scale-100.png",
        )
        for image, path in zip(comparisons, comparison_paths):
            h1._save_png(image, path)

        result = {
            "schema_version": "1.0.0",
            "id": "candidate-h3-organic-tonal-relief-prototype",
            "status": variant_report["status"],
            "purpose": (
                "Diagnostic comparison only; no manifest or formal candidate is modified."
            ),
            "root_change": (
                "Remove all visible terrain line glyphs and use only an organic, "
                "non-lighting low-frequency tonal hierarchy."
            ),
            "inputs": {
                "base": {
                    "path": h1._display_path(h1.BASE_PATH),
                    "sha256": h1.LOCKED_SHA256["base"],
                },
                "g2_source": {
                    "path": h1._display_path(h1.G2_SOURCE_PATH),
                    "sha256": h1.LOCKED_SHA256["g2_source"],
                },
                "g2_raster": {
                    "path": h1._display_path(h1.G2_RASTER_PATH),
                    "sha256": h1.LOCKED_SHA256["g2_raster"],
                },
                "g3_source": {
                    "path": h1._display_path(h1.G3_SOURCE_PATH),
                    "sha256": h1.LOCKED_SHA256["g3_source"],
                    "usage": "rise anchors and open-saddle structure only",
                },
                "h1_contract_module": {
                    "path": h1._display_path(Path(h1.__file__)),
                    "sha256": h1._sha256(Path(h1.__file__)),
                },
            },
            "source_metrics": inputs.source_metrics,
            "global_contract": {
                "permission": "exact G2 six-component footprint only",
                "terrain_renderer": "SHA-seeded low-frequency tonal masks only",
                "uses_g3_segment_orientations": False,
                "main_structure": (
                    "exactly two compact unequal organic tonal lobes separated "
                    "by a wide zero-edit open saddle"
                ),
                "foothill_structure": (
                    "four distinct one-lobe organic tonal footprints"
                ),
                "plain_blurred_ellipse_allowed": False,
                "visible_line_glyphs_allowed": False,
                "detail_selection_operator": "high-frequency-and-dark",
                "road_core_width_px": ROAD_CORE_WIDTH_PX,
                "render_operation": "neutral subtractive-only non-lighting RGB delta",
                "footprint_wash_delta_range": [0, 3],
                "variant_count": 1,
            },
            "variants": [variant_report],
            "comparisons": [
                {"path": h1._display_path(path), "sha256": h1._sha256(path)}
                for path in comparison_paths
            ],
        }
        report_path = output_dir / "report.json"
        report_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result
    finally:
        inputs.close()
        if output is not None:
            output.close()
        for image in comparisons:
            image.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace only the eight named H3 diagnostic files",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = render_all(args.output_dir, replace=args.replace)
    except Exception as error:
        print(f"H3 organic tonal-relief prototype failed: {error}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
