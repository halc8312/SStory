#!/usr/bin/env python3
"""Render one diagnostic H2 organic ridge-glyph prototype.

H2 makes one root change from H1: the G3-derived broad direction field is not
used for drawing.  Six hand-authored, landform-specific open ridge glyphs are
rendered inside the exact G2 permission masks.  G3 remains locked only to
verify the two rise anchors and the two open-saddle locations.

This tool writes diagnostic files under ``tmp/`` only.  It never edits the
production manifest or a formal style candidate.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter

import render_candidate_h1_deterministic_hachure as h1


REPO_ROOT = h1.REPO_ROOT
CANVAS = h1.CANVAS
DEFAULT_OUTPUT_DIR = REPO_ROOT / "tmp/map-production/h2-prototype"
SUPERSAMPLE = 3
ROAD_CORE_WIDTH_PX = 16
ROAD_FEATHER_PX = 5.0
BOUNDARY_FEATHER_PX = 9.0
CREST_DELTA_LEVELS = 44
HACHURE_DELTA_LEVELS = 42
COMPACT_LOBE_DELTA_LEVELS = 10
MAIN_LOBE_BLUR_PX = 18.0
FOOTHILL_LOBE_BLUR_PX = 10.0


class RidgeGlyphPrototypeError(ValueError):
    """Raised before an invalid H2 diagnostic can be published."""


@dataclass(frozen=True)
class SpineSpec:
    """One open curved crest and its deterministic local hachures."""

    rise_index: int
    points: tuple[tuple[int, int], ...]
    hachure_count: int
    hachure_side: int
    hachure_length_px: tuple[int, int]
    phase: int
    partial_two_px_every: int


@dataclass(frozen=True)
class GlyphSpec:
    identifier: str
    role: str
    spines: tuple[SpineSpec, ...]


def _spine(
    rise_index: int,
    points: Sequence[tuple[int, int]],
    hachure_count: int,
    hachure_side: int,
    lengths: tuple[int, int],
    phase: int,
    partial_two_px_every: int,
) -> SpineSpec:
    return SpineSpec(
        rise_index=rise_index,
        points=tuple(points),
        hachure_count=hachure_count,
        hachure_side=hachure_side,
        hachure_length_px=lengths,
        phase=phase,
        partial_two_px_every=partial_two_px_every,
    )


GLYPHS = (
    GlyphSpec(
        "ne-main-massif",
        "main-massif",
        (
            _spine(
                0,
                ((1058, 218), (1072, 205), (1088, 200)),
                0,
                0,
                (0, 0),
                1,
                5,
            ),
            _spine(
                0,
                ((1095, 176), (1108, 188), (1118, 205)),
                0,
                0,
                (0, 0),
                3,
                4,
            ),
            _spine(0, ((1070, 238), (1088, 232), (1106, 239)), 0, 0, (0, 0), 5, 6),
            _spine(
                1,
                ((1320, 220), (1336, 210), (1352, 213)),
                0,
                0,
                (0, 0),
                2,
                5,
            ),
            _spine(
                1,
                ((1360, 182), (1374, 194), (1380, 212)),
                0,
                0,
                (0, 0),
                4,
                6,
            ),
            _spine(1, ((1335, 240), (1352, 248), (1368, 242)), 0, 0, (0, 0), 6, 4),
        ),
    ),
    GlyphSpec(
        "ne-west-foothill",
        "foothill-a",
        (
            _spine(
                0,
                ((852, 411), (865, 397), (881, 401)),
                3,
                1,
                (10, 16),
                2,
                5,
            ),
        ),
    ),
    GlyphSpec(
        "ne-central-foothill",
        "foothill-b",
        (
            _spine(
                0,
                ((1145, 483), (1160, 468), (1178, 474)),
                3,
                -1,
                (12, 18),
                5,
                4,
            ),
        ),
    ),
    GlyphSpec(
        "se-main-massif",
        "main-massif",
        (
            _spine(
                0,
                ((1027, 842), (1043, 831), (1060, 834)),
                0,
                0,
                (0, 0),
                0,
                5,
            ),
            _spine(
                0,
                ((1060, 800), (1072, 814), (1075, 831)),
                0,
                0,
                (0, 0),
                3,
                6,
            ),
            _spine(0, ((1018, 872), (1035, 865), (1051, 872)), 0, 0, (0, 0), 6, 4),
            _spine(
                1,
                ((1235, 842), (1250, 830), (1266, 833)),
                0,
                0,
                (0, 0),
                1,
                4,
            ),
            _spine(
                1,
                ((1267, 858), (1280, 845), (1284, 828)),
                0,
                0,
                (0, 0),
                4,
                5,
            ),
            _spine(1, ((1242, 878), (1258, 884), (1274, 878)), 0, 0, (0, 0), 7, 6),
        ),
    ),
    GlyphSpec(
        "se-west-foothill",
        "foothill-a",
        (
            _spine(
                0,
                ((760, 895), (776, 880), (794, 886)),
                4,
                1,
                (9, 15),
                7,
                6,
            ),
        ),
    ),
    GlyphSpec(
        "se-east-foothill",
        "foothill-b",
        (
            _spine(
                0,
                ((1398, 880), (1404, 861), (1422, 851)),
                3,
                -1,
                (12, 18),
                9,
                3,
            ),
        ),
    ),
)
GLYPH_BY_ID = {glyph.identifier: glyph for glyph in GLYPHS}


def _stable_bytes(*values: object) -> bytes:
    return h1._stable_bytes("h2-organic-ridge-v1", *values)


def _catmull_rom(
    points: Sequence[tuple[int, int]], samples_per_segment: int = 12
) -> tuple[tuple[float, float], ...]:
    if len(points) < 3:
        raise RidgeGlyphPrototypeError(
            "an organic ridge spine needs at least three points"
        )
    values = [points[0], *points, points[-1]]
    sampled: list[tuple[float, float]] = []
    for index in range(1, len(values) - 2):
        p0, p1, p2, p3 = values[index - 1 : index + 3]
        for sample in range(samples_per_segment):
            t = sample / samples_per_segment
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * (
                2 * p1[0]
                + (-p0[0] + p2[0]) * t
                + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
            )
            y = 0.5 * (
                2 * p1[1]
                + (-p0[1] + p2[1]) * t
                + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
            )
            sampled.append((x, y))
    sampled.append((float(points[-1][0]), float(points[-1][1])))
    return tuple(sampled)


def _point_and_tangent(
    path: Sequence[tuple[float, float]], ratio: float
) -> tuple[tuple[float, float], tuple[float, float]]:
    lengths = [
        math.hypot(second[0] - first[0], second[1] - first[1])
        for first, second in zip(path, path[1:])
    ]
    total = sum(lengths)
    if total <= 0:
        raise RidgeGlyphPrototypeError("ridge spine has zero length")
    target = min(max(ratio, 0.0), 1.0) * total
    traversed = 0.0
    for index, length in enumerate(lengths):
        if traversed + length >= target or index == len(lengths) - 1:
            local = 0.0 if length == 0 else (target - traversed) / length
            first, second = path[index], path[index + 1]
            x = first[0] + (second[0] - first[0]) * local
            y = first[1] + (second[1] - first[1]) * local
            return (x, y), (
                (second[0] - first[0]) / length,
                (second[1] - first[1]) / length,
            )
        traversed += length
    raise AssertionError("unreachable path interpolation")


def _scaled_points(
    points: Sequence[tuple[float, float]],
) -> tuple[tuple[int, int], ...]:
    return tuple(
        (round(point[0] * SUPERSAMPLE), round(point[1] * SUPERSAMPLE))
        for point in points
    )


def _draw_round_polyline(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[float, float]],
    *,
    width_highres: int,
) -> None:
    scaled = _scaled_points(points)
    draw.line(scaled, fill=255, width=width_highres, joint="curve")
    radius = max(1, width_highres // 2)
    for x, y in (scaled[0], scaled[-1]):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)


def _native_antialiased(high_resolution: Image.Image) -> Image.Image:
    return high_resolution.resize(CANVAS, Image.Resampling.LANCZOS)


def _bearing(points: Sequence[tuple[int, int]]) -> float:
    return round(
        math.degrees(
            math.atan2(points[-1][1] - points[0][1], points[-1][0] - points[0][0])
        )
        % 180,
        3,
    )


def _render_glyph(
    landform: h1.Landform, glyph: GlyphSpec
) -> tuple[Image.Image, Image.Image, dict[str, Any]]:
    if glyph.identifier != landform.identifier or glyph.role != landform.role:
        raise RidgeGlyphPrototypeError(
            f"glyph identity mismatch for {landform.identifier}"
        )
    high_size = CANVAS[0] * SUPERSAMPLE, CANVAS[1] * SUPERSAMPLE
    crest_high = Image.new("L", high_size, 0)
    hachure_high = Image.new("L", high_size, 0)
    crest_draw = ImageDraw.Draw(crest_high)
    hachure_draw = ImageDraw.Draw(hachure_high)
    declared_hachures: list[dict[str, Any]] = []
    endpoint_buckets: dict[tuple[int, int], int] = {}
    orientation_bins: set[int] = set()
    spine_lengths: list[float] = []
    rise_counts: dict[int, int] = {}
    open_spines = 0
    try:
        for spine_index, spine in enumerate(glyph.spines):
            if spine.points[0] == spine.points[-1]:
                raise RidgeGlyphPrototypeError(
                    f"{glyph.identifier} contains a closed crest"
                )
            path = _catmull_rom(spine.points)
            crest_width = 5 if (spine_index + spine.phase) % 3 else 6
            _draw_round_polyline(crest_draw, path, width_highres=crest_width)
            spine_length = sum(
                math.hypot(second[0] - first[0], second[1] - first[1])
                for first, second in zip(path, path[1:])
            )
            spine_lengths.append(spine_length)
            crest_bearing = _bearing(spine.points)
            orientation_bins.add(int(crest_bearing // 15))
            for endpoint in (path[0], path[-1]):
                bucket = int(endpoint[0]) // 8, int(endpoint[1]) // 8
                endpoint_buckets[bucket] = endpoint_buckets.get(bucket, 0) + 1
            open_spines += 1
            rise_counts[spine.rise_index] = rise_counts.get(spine.rise_index, 0) + 1

            for index in range(spine.hachure_count):
                noise = _stable_bytes(glyph.identifier, spine_index, index)
                jitter = ((noise[0] / 255) * 2 - 1) * 0.018
                ratio = min(
                    0.94,
                    max(0.06, (index + 1) / (spine.hachure_count + 1) + jitter),
                )
                anchor, tangent = _point_and_tangent(path, ratio)
                normal = -tangent[1], tangent[0]
                if spine.hachure_side == 0:
                    side = 1 if (index + spine.phase) % 2 == 0 else -1
                else:
                    side = spine.hachure_side
                lean = ((noise[1] / 255) * 2 - 1) * 0.52
                vector_x = side * normal[0] + lean * tangent[0]
                vector_y = side * normal[1] + lean * tangent[1]
                vector_length = math.hypot(vector_x, vector_y)
                vector_x /= vector_length
                vector_y /= vector_length
                minimum, maximum = spine.hachure_length_px
                length = minimum + noise[2] % (maximum - minimum + 1)
                start_offset = 2.0 + (noise[3] % 3) * 0.65
                bend = ((noise[4] % 9) - 4) * 0.38
                start = (
                    anchor[0] + vector_x * start_offset,
                    anchor[1] + vector_y * start_offset,
                )
                middle = (
                    anchor[0] + vector_x * length * 0.56 + tangent[0] * bend,
                    anchor[1] + vector_y * length * 0.56 + tangent[1] * bend,
                )
                end = (
                    anchor[0] + vector_x * length + tangent[0] * bend * 1.65,
                    anchor[1] + vector_y * length + tangent[1] * bend * 1.65,
                )
                width = (
                    5 if (index + spine.phase) % spine.partial_two_px_every == 0 else 3
                )
                _draw_round_polyline(
                    hachure_draw,
                    _catmull_rom((start, middle, end), samples_per_segment=7),
                    width_highres=width,
                )
                bearing = (
                    math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])) % 180
                )
                orientation_bins.add(int(bearing // 15))
                for endpoint in (start, end):
                    bucket = int(endpoint[0]) // 8, int(endpoint[1]) // 8
                    endpoint_buckets[bucket] = endpoint_buckets.get(bucket, 0) + 1
                declared_hachures.append(
                    {
                        "spine_index": spine_index,
                        "side": side,
                        "length_px": length,
                        "bearing_degrees": round(bearing, 3),
                    }
                )

        crest_native = _native_antialiased(crest_high)
        hachure_native = _native_antialiased(hachure_high)
        not_saddle = ImageChops.invert(landform.saddle_mask)
        crest_in_footprint = ImageChops.darker(crest_native, landform.mask)
        hachure_in_footprint = ImageChops.darker(hachure_native, landform.mask)
        try:
            crest = ImageChops.darker(crest_in_footprint, not_saddle)
            hachure = ImageChops.darker(hachure_in_footprint, not_saddle)
        finally:
            crest_native.close()
            hachure_native.close()
            not_saddle.close()
            crest_in_footprint.close()
            hachure_in_footprint.close()

        expected_rises = 2 if glyph.role == "main-massif" else 1
        ordered_rise_counts = [
            rise_counts.get(index, 0) for index in range(expected_rises)
        ]
        combined_ink = ImageChops.lighter(crest, hachure)
        hachure_lengths = [item["length_px"] for item in declared_hachures]
        try:
            saddle_ink_pixels = h1._count_intersection(
                combined_ink, landform.saddle_mask
            )
        finally:
            combined_ink.close()
        metrics = {
            "id": glyph.identifier,
            "role": glyph.role,
            "footprint_pixels": landform.area_pixels,
            "open_crest_count": open_spines,
            "closed_contour_count": 0,
            "rise_spine_counts": ordered_rise_counts,
            "crest_bearings_degrees": [
                _bearing(spine.points) for spine in glyph.spines
            ],
            "crest_lengths_px": [round(length, 3) for length in spine_lengths],
            "maximum_crest_length_px": round(max(spine_lengths), 3),
            "long_outline_count": sum(length > 45 for length in spine_lengths),
            "declared_hachure_count": len(declared_hachures),
            "declared_hachure_length_range_px": [
                min(hachure_lengths, default=0),
                max(hachure_lengths, default=0),
            ],
            "hachure_orientation_bins_15_degrees": len(orientation_bins),
            "maximum_endpoints_per_8px_bucket": max(
                endpoint_buckets.values(), default=0
            ),
            "one_sided_hachures": glyph.role != "main-massif",
            "crest_pixels_before_protection": h1._count_selected(crest),
            "hachure_pixels_before_protection": h1._count_selected(hachure),
            "saddle_ink_pixels_before_protection": saddle_ink_pixels,
        }
        return crest, hachure, metrics
    finally:
        crest_high.close()
        hachure_high.close()


def _allowed_line(
    mask: Image.Image,
    permission_soft: Image.Image,
    road_strength: Image.Image,
    details: Image.Image,
) -> Image.Image:
    inside = ImageChops.multiply(mask, permission_soft)
    without_road = h1._subtract_protection(inside, road_strength)
    inside.close()
    try:
        return h1._subtract_protection(without_road, details)
    finally:
        without_road.close()


def _organic_blob(
    center: tuple[float, float],
    *,
    radius_x: float,
    radius_y: float,
    blur_radius: float,
    seed: str,
) -> Image.Image:
    binary = Image.new("L", CANVAS, 0)
    points: list[tuple[int, int]] = []
    for index in range(18):
        noise = _stable_bytes(seed, index)
        angle = 2 * math.pi * index / 18
        radius_scale = 0.86 + noise[0] / 255 * 0.22
        x = center[0] + math.cos(angle) * radius_x * radius_scale
        y = center[1] + math.sin(angle) * radius_y * radius_scale
        points.append((round(x), round(y)))
    ImageDraw.Draw(binary).polygon(points, fill=255)
    softened = binary.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    binary.close()
    return softened


def _compact_lobe_support(landforms: Sequence[h1.Landform]) -> Image.Image:
    """Build compact non-directional tonal lobes without outline strokes."""

    union = Image.new("L", CANVAS, 0)
    for landform in landforms:
        glyph = GLYPH_BY_ID[landform.identifier]
        if landform.role == "main-massif":
            centers = landform.group_centers
            radius_x, radius_y = 64.0, 50.0
            blur = MAIN_LOBE_BLUR_PX
        else:
            points = glyph.spines[0].points
            centers = (
                (
                    sum(point[0] for point in points) / len(points),
                    sum(point[1] for point in points) / len(points),
                ),
            )
            radius_x, radius_y = 38.0, 29.0
            blur = FOOTHILL_LOBE_BLUR_PX
        for index, center in enumerate(centers):
            blob = _organic_blob(
                center,
                radius_x=radius_x,
                radius_y=radius_y,
                blur_radius=blur,
                seed=f"{landform.identifier}:{index}",
            )
            clipped = ImageChops.darker(blob, landform.mask)
            without_saddle = h1._subtract_protection(clipped, landform.saddle_mask)
            updated = ImageChops.lighter(union, without_saddle)
            union.close()
            union = updated
            blob.close()
            clipped.close()
            without_saddle.close()
    return union


def _resize_readability(
    base: Image.Image,
    output: Image.Image,
    mask: Image.Image,
    factor: float,
) -> dict[str, Any]:
    size = round(CANVAS[0] * factor), round(CANVAS[1] * factor)
    small_base = base.resize(size, Image.Resampling.LANCZOS)
    small_output = output.resize(size, Image.Resampling.LANCZOS)
    small_mask = mask.resize(size, Image.Resampling.LANCZOS).point(
        lambda value: 255 if value >= 32 else 0
    )
    difference = h1._difference_max(small_base, small_output)
    visible = difference.point(lambda value: 255 if value >= 2 else 0)
    strong = difference.point(lambda value: 255 if value >= 5 else 0)
    try:
        return {
            "scale": factor,
            "visible_pixels": h1._count_intersection(visible, small_mask),
            "strong_pixels": h1._count_intersection(strong, small_mask),
            "maximum_channel_difference": h1._masked_max(difference, small_mask),
            "mean_max_channel_difference": round(
                h1._masked_mean(difference, small_mask), 6
            ),
        }
    finally:
        small_base.close()
        small_output.close()
        small_mask.close()
        difference.close()
        visible.close()
        strong.close()


def _render_balanced(inputs: h1.Inputs) -> tuple[Image.Image, dict[str, Any]]:
    permission_soft = h1._feather_inside(inputs.permission, BOUNDARY_FEATHER_PX)
    road_core = h1._draw_road_core(ROAD_CORE_WIDTH_PX)
    road_strength = h1._protected_strength(road_core, ROAD_FEATHER_PX)
    details = h1.detail_core(inputs.base)
    saddle_union = Image.new("L", CANVAS, 0)
    crest_union = Image.new("L", CANVAS, 0)
    hachure_union = Image.new("L", CANVAS, 0)
    raw_masks: dict[str, tuple[Image.Image, Image.Image]] = {}
    landform_metrics: list[dict[str, Any]] = []
    crest_allowed: Image.Image | None = None
    hachure_allowed: Image.Image | None = None
    support_allowed: Image.Image | None = None
    edit_strength: Image.Image | None = None
    delta_rgb: Image.Image | None = None
    output: Image.Image | None = None
    difference_max: Image.Image | None = None
    try:
        for landform in inputs.landforms:
            glyph = GLYPH_BY_ID.get(landform.identifier)
            if glyph is None:
                raise RidgeGlyphPrototypeError(
                    f"missing H2 glyph for {landform.identifier}"
                )
            crest, hachure, metrics = _render_glyph(landform, glyph)
            raw_masks[landform.identifier] = crest, hachure
            landform_metrics.append(metrics)
            updated_crest = ImageChops.lighter(crest_union, crest)
            crest_union.close()
            crest_union = updated_crest
            updated_hachure = ImageChops.lighter(hachure_union, hachure)
            hachure_union.close()
            hachure_union = updated_hachure
            updated_saddle = ImageChops.lighter(saddle_union, landform.saddle_mask)
            saddle_union.close()
            saddle_union = updated_saddle

        crest_allowed = _allowed_line(
            crest_union, permission_soft, road_strength, details
        )
        hachure_allowed = _allowed_line(
            hachure_union, permission_soft, road_strength, details
        )
        compact_support = _compact_lobe_support(inputs.landforms)
        try:
            support_allowed = _allowed_line(
                compact_support, permission_soft, road_strength, details
            )
        finally:
            compact_support.close()

        crest_strength = h1._scale_mask(crest_allowed, CREST_DELTA_LEVELS)
        hachure_strength = h1._scale_mask(hachure_allowed, HACHURE_DELTA_LEVELS)
        support_strength = h1._scale_mask(support_allowed, COMPACT_LOBE_DELTA_LEVELS)
        primary_strength = ImageChops.lighter(crest_strength, hachure_strength)
        try:
            edit_strength = ImageChops.add(primary_strength, support_strength)
        finally:
            crest_strength.close()
            hachure_strength.close()
            support_strength.close()
            primary_strength.close()

        delta_rgb = Image.merge(
            "RGB",
            (
                edit_strength.point(lambda value: round(value * 0.72)),
                edit_strength.point(lambda value: round(value * 0.84)),
                edit_strength.copy(),
            ),
        )
        output = ImageChops.subtract(inputs.base, delta_rgb)
        difference_max = h1._difference_max(inputs.base, output)
        changed = difference_max.point(lambda value: 255 if value else 0)
        strong = difference_max.point(lambda value: 255 if value >= 10 else 0)
        outside = ImageChops.invert(inputs.permission)
        brightening = ImageChops.subtract(output, inputs.base)
        black = Image.new("RGB", CANVAS, (0, 0, 0))
        brightening_max = h1._difference_max(black, brightening)
        black.close()
        try:
            metrics_by_id = {metrics["id"]: metrics for metrics in landform_metrics}
            for landform in inputs.landforms:
                metrics = metrics_by_id[landform.identifier]
                crest, hachure = raw_masks[landform.identifier]
                visible_crest = ImageChops.darker(crest_allowed, crest)
                visible_hachure = ImageChops.darker(hachure_allowed, hachure)
                try:
                    visible_line = ImageChops.lighter(visible_crest, visible_hachure)
                    metrics.update(
                        {
                            "crest_pixels_after_protection": h1._count_selected(
                                visible_crest
                            ),
                            "hachure_pixels_after_protection": h1._count_selected(
                                visible_hachure
                            ),
                            "changed_pixels": h1._count_intersection(
                                changed, landform.mask
                            ),
                            "changed_fraction": round(
                                h1._count_intersection(changed, landform.mask)
                                / landform.area_pixels,
                                6,
                            ),
                            "line_coverage_fraction": round(
                                h1._count_selected(visible_line) / landform.area_pixels,
                                6,
                            ),
                            "strong_changed_pixels": h1._count_intersection(
                                strong, landform.mask
                            ),
                            "strong_changed_fraction": round(
                                h1._count_intersection(strong, landform.mask)
                                / landform.area_pixels,
                                6,
                            ),
                            "saddle_changed_pixels": h1._count_intersection(
                                changed, landform.saddle_mask
                            ),
                            "readability": [
                                _resize_readability(
                                    inputs.base,
                                    output,
                                    landform.mask,
                                    factor,
                                )
                                for factor in (0.5, 0.25)
                            ],
                        }
                    )
                    visible_line.close()
                finally:
                    visible_crest.close()
                    visible_hachure.close()

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
                    "brightened_pixels": h1._count_selected(brightening_max),
                    "maximum_channel_increase": brightening_max.getextrema()[1],
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
            if gates["boundary_feather"]["partial_alpha_pixels"] == 0:
                immediate_failures.append("boundary_feather")

            for metrics in landform_metrics:
                if metrics["closed_contour_count"]:
                    immediate_failures.append(f"{metrics['id']}:closed-contour")
                if metrics["long_outline_count"]:
                    immediate_failures.append(f"{metrics['id']}:long-outline")
                if metrics["saddle_changed_pixels"]:
                    immediate_failures.append(f"{metrics['id']}:closed-saddle")
                if metrics["role"] == "main-massif":
                    if len(metrics["rise_spine_counts"]) != 2 or any(
                        not 2 <= count <= 3 for count in metrics["rise_spine_counts"]
                    ):
                        immediate_failures.append(
                            f"{metrics['id']}:invalid-two-rise-spines"
                        )
                    if metrics["declared_hachure_count"] != 0:
                        immediate_failures.append(
                            f"{metrics['id']}:unexpected-main-comb-hachures"
                        )
                    if metrics["crest_pixels_after_protection"] < 300:
                        immediate_failures.append(
                            f"{metrics['id']}:insufficient-main-crest"
                        )
                    if metrics["readability"][1]["strong_pixels"] < 80:
                        immediate_failures.append(
                            f"{metrics['id']}:quarter-scale-unreadable"
                        )
                else:
                    if metrics["open_crest_count"] != 1:
                        immediate_failures.append(
                            f"{metrics['id']}:foothill-crest-count"
                        )
                    if not metrics["one_sided_hachures"]:
                        immediate_failures.append(
                            f"{metrics['id']}:foothill-not-one-sided"
                        )
                    if not 2 <= metrics["declared_hachure_count"] <= 4:
                        immediate_failures.append(
                            f"{metrics['id']}:foothill-hachure-count"
                        )
                    if metrics["crest_pixels_after_protection"] < 120:
                        immediate_failures.append(
                            f"{metrics['id']}:insufficient-foothill-crest"
                        )
                    if metrics["readability"][1]["strong_pixels"] < 12:
                        immediate_failures.append(
                            f"{metrics['id']}:quarter-scale-unreadable"
                        )
                if metrics["maximum_endpoints_per_8px_bucket"] > 4:
                    immediate_failures.append(f"{metrics['id']}:endpoint-convergence")
                if (
                    metrics["line_coverage_fraction"] > 0.08
                    or metrics["strong_changed_fraction"] > 0.15
                ):
                    immediate_failures.append(f"{metrics['id']}:broad-direction-field")

            foothill_signatures = {
                (
                    tuple(metrics["crest_bearings_degrees"]),
                    metrics["declared_hachure_count"],
                    tuple(metrics["declared_hachure_length_range_px"]),
                )
                for metrics in landform_metrics
                if metrics["role"] != "main-massif"
            }
            if len(foothill_signatures) != 4:
                immediate_failures.append("foothill-symbol-reuse")

            report = {
                "slug": "balanced",
                "status": "passed" if not immediate_failures else "failed",
                "description": (
                    "Compact non-directional tonal lobes with disconnected short "
                    "ridge marks; foothills use one kinked crest and two-to-four "
                    "one-sided hachures."
                ),
                "parameters": {
                    "supersample": SUPERSAMPLE,
                    "road_core_width_px": ROAD_CORE_WIDTH_PX,
                    "road_feather_px": ROAD_FEATHER_PX,
                    "boundary_feather_px": BOUNDARY_FEATHER_PX,
                    "crest_delta_levels": CREST_DELTA_LEVELS,
                    "hachure_delta_levels": HACHURE_DELTA_LEVELS,
                    "compact_lobe_delta_levels": COMPACT_LOBE_DELTA_LEVELS,
                    "main_lobe_blur_px": MAIN_LOBE_BLUR_PX,
                    "foothill_lobe_blur_px": FOOTHILL_LOBE_BLUR_PX,
                },
                "metrics": {
                    "changed_pixels": h1._count_selected(changed),
                    "strong_changed_pixels": h1._count_selected(strong),
                    "maximum_channel_difference": difference_max.getextrema()[1],
                    "editable_pixels": h1._count_selected(edit_strength),
                    "road_core_pixels": h1._count_selected(road_core),
                    "detail_core_pixels": h1._count_selected(details),
                    "crest_pixels_after_protection": h1._count_selected(crest_allowed),
                    "hachure_pixels_after_protection": h1._count_selected(
                        hachure_allowed
                    ),
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
        crest_union.close()
        hachure_union.close()
        for crest, hachure in raw_masks.values():
            crest.close()
            hachure.close()
        for image in (
            crest_allowed,
            hachure_allowed,
            support_allowed,
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
    right = h1._labeled_panel(output, "H2 balanced", size)
    try:
        sheet.paste(left, (0, 0))
        sheet.paste(right, (768, 0))
        return sheet
    finally:
        left.close()
        right.close()


def _expected_outputs(output_dir: Path) -> tuple[Path, ...]:
    return (
        output_dir / "h2-balanced.png",
        output_dir / "comparison-full.png",
        output_dir / "comparison-north-east.png",
        output_dir / "comparison-south-east.png",
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
        raise RidgeGlyphPrototypeError(
            "refusing to overwrite diagnostic output without --replace: "
            + ", ".join(h1._display_path(path) for path in existing)
        )

    inputs = h1.load_inputs()
    output: Image.Image | None = None
    comparisons: list[Image.Image] = []
    try:
        if set(GLYPH_BY_ID) != {landform.identifier for landform in inputs.landforms}:
            raise RidgeGlyphPrototypeError(
                "H2 glyph set does not match all six landforms"
            )
        output, variant_report = _render_balanced(inputs)
        output_path = output_dir / "h2-balanced.png"
        h1._save_png(output, output_path)
        variant_report["output_path"] = h1._display_path(output_path)
        variant_report["output_sha256"] = h1._sha256(output_path)

        full = _full_comparison(inputs.base, output)
        north_east = h1._crop_comparison(
            inputs.base,
            (("H2 balanced", output),),
            (740, 48, 1536, 570),
            panel_width=720,
        )
        south_east = h1._crop_comparison(
            inputs.base,
            (("H2 balanced", output),),
            (650, 688, 1536, 1024),
            panel_width=720,
        )
        comparisons.extend((full, north_east, south_east))
        comparison_paths = (
            output_dir / "comparison-full.png",
            output_dir / "comparison-north-east.png",
            output_dir / "comparison-south-east.png",
        )
        for image, path in zip(comparisons, comparison_paths):
            h1._save_png(image, path)

        result = {
            "schema_version": "1.0.0",
            "id": "candidate-h2-organic-ridge-glyph-prototype",
            "status": variant_report["status"],
            "purpose": (
                "Diagnostic comparison only; no manifest or formal candidate is modified."
            ),
            "root_change": (
                "Replace the G3-derived broad direction field with six "
                "landform-specific organic non-convergent ridge glyphs."
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
                "direction_source": "hand-authored per-landform open ridge glyphs",
                "uses_g3_segment_orientations": False,
                "main_structure": (
                    "two compact non-directional tonal lobes, three disconnected "
                    "20-45px ridge marks per rise, open saddle"
                ),
                "foothill_structure": (
                    "one <=45px kinked crest with two-to-four one-sided short hachures"
                ),
                "maximum_outline_length_px": 45,
                "detail_selection_operator": "high-frequency-and-dark",
                "road_core_width_px": ROAD_CORE_WIDTH_PX,
                "render_operation": "subtractive-only non-lighting RGB delta",
                "closed_contours_allowed": False,
                "broad_direction_fields_allowed": False,
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
        help="replace only the five named H2 diagnostic files",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = render_all(args.output_dir, replace=args.replace)
    except Exception as error:
        print(f"H2 organic ridge-glyph prototype failed: {error}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
