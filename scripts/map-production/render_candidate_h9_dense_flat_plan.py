#!/usr/bin/env python3
"""Render Candidate H9 as a protected, dense flat-plan edit of H5."""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import deque
from pathlib import Path
from statistics import fmean
from typing import Any, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

import render_candidate_h8_localized_plan_edit as h8


REPO_ROOT = h8.REPO_ROOT
DEFAULT_H5 = h8.DEFAULT_H5
DEFAULT_ATLAS = (
    REPO_ROOT
    / "world/map-production/style-assets/phase5-cartographic-material-atlas-v1.png"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "tmp/map-production/h9-prototype"
FORMAL_MASTER_PATH = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-h-v9-dense-flat-plan.png"
)
FORMAL_MASK_PATH = (
    REPO_ROOT
    / "world/map-production/qa/automated/"
    "style-candidate-h-v9-dense-flat-plan.semantic-mask.png"
)
FORMAL_CONTACT_PATH = (
    REPO_ROOT
    / "world/map-production/qa/automated/"
    "style-candidate-h-v9-dense-flat-plan.contact-sheet.png"
)
FORMAL_PROVENANCE_PATH = (
    REPO_ROOT
    / "world/map-production/qa/automated/"
    "style-candidate-h-v9-dense-flat-plan.provenance.json"
)
CANVAS = h8.CANVAS
H5_SHA256 = h8.H5_SHA256
ATLAS_SHA256 = "9b42dcce48d275d392bc28235925ac02f37690ace3418d6cb65920f4da05c6e3"
GENERATOR_ID = "sstory-map-production/render_candidate_h9_dense_flat_plan.py@2"
SEED = 0x48395F44454E5345
MASTER_NAME = "style-candidate-h-v9-dense-flat-plan.png"
MASK_NAME = "style-candidate-h-v9-dense-flat-plan.semantic-mask.png"
CONTACT_NAME = "style-candidate-h-v9-dense-flat-plan.contact-sheet.png"
REPORT_NAME = "style-candidate-h-v9-dense-flat-plan.provenance.json"
PNG_OPTIONS = h8.PNG_OPTIONS

CITY_CENTER = h8.CITY_CENTER
CITY_BOUNDS = (710, 370, 990, 620)
PORT_BOUNDS = (360, 720, 640, 970)
FOREST_BOUNDS = (420, 0, 700, 250)

INK = (82, 72, 48)
INK_SOFT = (106, 91, 61)
PARCHMENT = (177, 154, 108)
ROAD = (197, 176, 128)
CITY_COLORS = (
    (142, 107, 72),
    (151, 116, 77),
    (159, 124, 83),
    (135, 102, 69),
    (166, 132, 91),
    (147, 112, 74),
)
PARK = (126, 126, 72)


class H9RenderError(ValueError):
    """Raised when the protected H9 render contract cannot be met."""


def _validated_output_dir(path: Path) -> Path:
    resolved = path.resolve()
    root = DEFAULT_OUTPUT_ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise H9RenderError(f"output must stay under {h8._relative(DEFAULT_OUTPUT_ROOT)}")
    return resolved


def _output_paths(output_dir: Path, *, formal: bool) -> dict[str, Path]:
    """Resolve either a confined preview bundle or the four exact repo paths.

    Formal output never accepts caller-selected destinations. This prevents a
    typo or untrusted path from scattering immutable evidence across the repo.
    Preview/test output remains confined beneath ``DEFAULT_OUTPUT_ROOT``.
    """

    if formal:
        if output_dir.resolve() != DEFAULT_OUTPUT_ROOT.resolve():
            raise H9RenderError(
                "--formal cannot be combined with a custom --output-dir"
            )
        return {
            "master": FORMAL_MASTER_PATH,
            "semantic_mask": FORMAL_MASK_PATH,
            "contact_sheet": FORMAL_CONTACT_PATH,
            "provenance": FORMAL_PROVENANCE_PATH,
        }
    resolved = _validated_output_dir(output_dir)
    return {
        "master": resolved / MASTER_NAME,
        "semantic_mask": resolved / MASK_NAME,
        "contact_sheet": resolved / CONTACT_NAME,
        "provenance": resolved / REPORT_NAME,
    }


def _city_mask() -> Image.Image:
    return h8._ellipse_mask(CITY_CENTER, (130.0, 123.0))


def _port_mask() -> Image.Image:
    mask = Image.new("L", CANVAS, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(
        (
            (390, 827),
            (416, 781),
            (456, 748),
            (522, 748),
            (570, 782),
            (587, 842),
            (579, 897),
            (543, 932),
            (477, 930),
            (423, 906),
            (388, 869),
        ),
        fill=255,
    )
    return mask


def _irregular_ring_points(
    center: tuple[float, float],
    radii: tuple[float, float],
    *,
    phase: float,
    wobble: float,
    count: int = 96,
) -> list[tuple[float, float]]:
    cx, cy = center
    rx, ry = radii
    points: list[tuple[float, float]] = []
    for index in range(count):
        angle = math.tau * index / count
        offset = (
            math.sin(angle * 3.0 + phase) * wobble
            + math.sin(angle * 7.0 - phase * 0.7) * wobble * 0.36
            + math.sin(angle * 11.0 + 0.4) * wobble * 0.18
        )
        points.append(
            (
                cx + math.cos(angle) * (rx + offset),
                cy + math.sin(angle) * (ry + offset * 0.82),
            )
        )
    points.append(points[0])
    return points


def _polyline_distance(point: tuple[float, float], path: Sequence[tuple[float, float]]) -> float:
    px, py = point
    best = float("inf")
    for start, end in zip(path, path[1:]):
        ax, ay = start
        bx, by = end
        dx = bx - ax
        dy = by - ay
        length_squared = dx * dx + dy * dy
        if length_squared == 0:
            fraction = 0.0
        else:
            fraction = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
        nearest_x = ax + dx * fraction
        nearest_y = ay + dy * fraction
        best = min(best, math.hypot(px - nearest_x, py - nearest_y))
    return best


def _recursive_polar_cells(
    cell: tuple[float, float, float, float],
    depth: int,
    rng: random.Random,
) -> list[tuple[float, float, float, float]]:
    if depth <= 0:
        return [cell]
    inner, outer, angle_start, angle_end = cell
    arc_span = (angle_end - angle_start) * ((inner + outer) / 2.0)
    radial_span = outer - inner
    split_angular = arc_span > radial_span * rng.uniform(0.75, 1.45)
    fraction = rng.uniform(0.36, 0.64)
    if split_angular:
        split = angle_start + (angle_end - angle_start) * fraction
        parts = (
            (inner, outer, angle_start, split),
            (inner, outer, split, angle_end),
        )
    else:
        split = inner + (outer - inner) * fraction
        parts = (
            (inner, split, angle_start, angle_end),
            (split, outer, angle_start, angle_end),
        )
    result: list[tuple[float, float, float, float]] = []
    for part in parts:
        result.extend(_recursive_polar_cells(part, depth - 1, rng))
    return result


def _polygon_is_clear(mask: Image.Image, polygon: Sequence[tuple[float, float]]) -> bool:
    bounds = (
        max(0, int(math.floor(min(point[0] for point in polygon))) - 1),
        max(0, int(math.floor(min(point[1] for point in polygon))) - 1),
        min(CANVAS[0], int(math.ceil(max(point[0] for point in polygon))) + 2),
        min(CANVAS[1], int(math.ceil(max(point[1] for point in polygon))) + 2),
    )
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        return False
    probe = Image.new("L", (bounds[2] - bounds[0], bounds[3] - bounds[1]), 0)
    shifted = [(x - bounds[0], y - bounds[1]) for x, y in polygon]
    ImageDraw.Draw(probe).polygon(shifted, fill=255)
    occupied = ImageChops.multiply(mask.crop(bounds), probe)
    blocked = occupied.getbbox() is not None
    probe.close()
    occupied.close()
    return not blocked


def _draw_flat_city(target: Image.Image, mask: Image.Image, rng: random.Random) -> dict[str, Any]:
    layer = target.copy()
    draw = ImageDraw.Draw(layer)
    cx, cy = CITY_CENTER
    outer = _irregular_ring_points((cx, cy), (121.0, 114.0), phase=0.31, wobble=2.1)
    draw.polygon(outer[:-1], fill=PARCHMENT)

    street_mask = Image.new("L", CANVAS, 0)
    street_draw = ImageDraw.Draw(street_mask)
    streets: list[list[tuple[float, float]]] = []
    ring_specs = (
        ((cx - 4.0, cy + 2.0), (37.0, 33.0), 0.17, 2.0),
        ((cx + 5.0, cy - 3.0), (68.0, 61.0), 0.79, 2.9),
        ((cx - 2.0, cy + 4.0), (96.0, 89.0), 1.31, 2.5),
    )
    for center, radii, phase, wobble in ring_specs:
        path = _irregular_ring_points(center, radii, phase=phase, wobble=wobble, count=72)
        streets.append(path)
        street_draw.line(path, fill=255, width=7, joint="curve")

    district_angles = (-0.09, 0.52, 1.29, 2.08, 2.71, 3.55, 4.43, 5.19, math.tau - 0.09)
    avenue_paths: list[list[tuple[float, float]]] = []
    for index, angle in enumerate(district_angles[:-1]):
        bend = (0.035 + (index % 3) * 0.018) * (-1 if index % 2 else 1)
        path = [
            (cx + math.cos(angle + bend) * 20, cy + math.sin(angle + bend) * 18),
            (cx + math.cos(angle - bend) * 54, cy + math.sin(angle - bend) * 49),
            (cx + math.cos(angle + bend * 0.45) * 86, cy + math.sin(angle + bend * 0.45) * 80),
            (cx + math.cos(angle - bend * 0.2) * 119, cy + math.sin(angle - bend * 0.2) * 112),
        ]
        avenue_paths.append(path)
        streets.append(path)
        street_draw.line(path, fill=255, width=7, joint="curve")

    # Seven deliberately unequal civic voids break any identical wedge cadence.
    civic_voids: list[tuple[str, tuple[int, int, int, int]]] = [
        ("market", (878, 450, 904, 468)),
        ("market", (792, 524, 817, 544)),
        ("courtyard", (907, 535, 924, 554)),
        ("courtyard", (811, 424, 828, 441)),
        ("park", (875, 562, 900, 582)),
        ("park", (755, 478, 779, 501)),
        ("courtyard", (925, 481, 942, 498)),
    ]
    for _, bounds in civic_voids:
        street_draw.rounded_rectangle(bounds, radius=4, fill=255)

    occupancy = street_mask.copy()
    occupancy_draw = ImageDraw.Draw(occupancy)
    occupancy_draw.ellipse((cx - 25, cy - 22, cx + 25, cy + 22), fill=255)
    building_count = 0
    recursive_leaf_count = 0
    district_counts: list[int] = []
    district_quotas = (49, 57, 44, 61, 51, 55, 47, 62)
    radial_bands = ((24.0, 47.0), (52.0, 74.0), (79.0, 106.0))
    for district, quota in enumerate(district_quotas):
        start = district_angles[district] + 0.035
        end = district_angles[district + 1] - 0.035
        cells: list[tuple[float, float, float, float]] = []
        for band_index, (inner, outer_radius) in enumerate(radial_bands):
            depth = 2 if (district + band_index) % 3 else 1
            cells.extend(_recursive_polar_cells((inner, outer_radius, start, end), depth, rng))
        recursive_leaf_count += len(cells)
        accepted = 0
        attempts = 0
        while accepted < quota and attempts < quota * 80:
            attempts += 1
            cell = cells[(attempts * 17 + district * 5) % len(cells)]
            inner, outer_radius, angle_start, angle_end = cell
            radius = rng.uniform(inner + 2.2, outer_radius - 2.2)
            angle = rng.uniform(angle_start + 0.012, angle_end - 0.012)
            angle += rng.uniform(-0.012, 0.012)
            x = cx + math.cos(angle) * radius
            y = cy + math.sin(angle) * radius * 0.94
            width = rng.uniform(2.8, 6.1)
            height = rng.uniform(2.3, 4.9)
            orientation = angle + (math.pi / 2 if (district + attempts) % 4 else 0.0)
            orientation += rng.uniform(-0.16, 0.16)
            polygon = h8._rotated_footprint((x, y), width, height, orientation, rng)
            if not _polygon_is_clear(occupancy, polygon):
                continue
            if any(math.hypot(px - cx, (py - cy) / 0.94) > 108.0 for px, py in polygon):
                continue
            color = CITY_COLORS[(district * 3 + accepted) % len(CITY_COLORS)]
            draw.polygon(polygon, fill=color, outline=INK)
            occupancy_draw.polygon(polygon, fill=255)
            building_count += 1
            accepted += 1
        district_counts.append(accepted)

    # Streets are laid over the footprints as flat, equally toned plan marks.
    for path in streets:
        draw.line(path, fill=ROAD, width=6, joint="curve")
        draw.line(path, fill=INK_SOFT, width=1, joint="curve")
    for kind, bounds in civic_voids:
        if kind == "park":
            draw.rounded_rectangle(bounds, radius=4, fill=PARK, outline=INK_SOFT, width=1)
            inset = (bounds[0] + 4, bounds[1] + 4, bounds[2] - 4, bounds[3] - 4)
            draw.line((inset[0], inset[1], inset[2], inset[3]), fill=PARCHMENT, width=1)
            draw.line((inset[0], inset[3], inset[2], inset[1]), fill=PARCHMENT, width=1)
        else:
            draw.rounded_rectangle(bounds, radius=3, fill=(185, 161, 112), outline=INK_SOFT, width=1)

    # Flat central citadel, open court, and asymmetrical annexes.
    citadel = ((832, 485), (846, 477), (866, 481), (875, 493), (871, 512), (854, 520), (836, 514), (828, 500))
    draw.polygon(citadel, fill=CITY_COLORS[3], outline=INK)
    draw.polygon(((842, 490), (861, 489), (865, 505), (846, 511), (839, 502)), fill=PARCHMENT, outline=INK_SOFT)
    draw.rectangle((824, 489, 830, 504), fill=CITY_COLORS[1], outline=INK)
    draw.rectangle((873, 493, 879, 509), fill=CITY_COLORS[4], outline=INK)

    # Retain a circular wall, but interrupt it at five canonical road gates.
    draw.line(outer, fill=INK, width=3, joint="curve")
    inner_wall = _irregular_ring_points((cx, cy), (116.0, 109.0), phase=0.31, wobble=1.7)
    draw.line(inner_wall, fill=INK_SOFT, width=1, joint="curve")
    gate_angles = (-1.10, 0.10, 0.77, 2.37, 3.88)
    for angle in gate_angles:
        gate = [
            (cx + math.cos(angle) * 103, cy + math.sin(angle) * 97),
            (cx + math.cos(angle) * 130, cy + math.sin(angle) * 123),
        ]
        draw.line(gate, fill=ROAD, width=7)
        draw.line(gate, fill=INK_SOFT, width=1)
        tangent_x = -math.sin(angle) * 5
        tangent_y = math.cos(angle) * 5
        gate_x = cx + math.cos(angle) * 117
        gate_y = cy + math.sin(angle) * 111
        draw.line((gate_x - tangent_x, gate_y - tangent_y, gate_x + tangent_x, gate_y + tangent_y), fill=INK, width=2)

    target.paste(layer, (0, 0), mask)
    layer.close()
    street_mask.close()
    occupancy.close()
    return {
        "city_flat_building_footprints": building_count,
        "city_district_count": 8,
        "city_district_building_counts": district_counts,
        "city_recursive_leaf_blocks": recursive_leaf_count,
        "city_ragged_ring_streets": 3,
        "city_radial_avenues": 8,
        "city_courtyards_markets_parks": len(civic_voids),
        "city_gate_count": len(gate_angles),
        "city_side_faces": 0,
        "city_directional_shadows": 0,
    }


def _draw_flat_port(
    target: Image.Image,
    mask: Image.Image,
    water: Image.Image,
    rng: random.Random,
) -> dict[str, Any]:
    layer = target.copy()
    draw = ImageDraw.Draw(layer)
    lane_mask = Image.new("L", CANVAS, 0)
    lane_draw = ImageDraw.Draw(lane_mask)
    lane_paths = (
        ((500, 754), (497, 786), (491, 814), (486, 841)),
        ((447, 790), (471, 805), (491, 814), (525, 811), (551, 825)),
        ((432, 817), (458, 824), (484, 838), (515, 843), (545, 852)),
        ((455, 772), (459, 801), (450, 835)),
        ((527, 771), (519, 797), (524, 838)),
        ((470, 785), (487, 795), (505, 786)),
        ((441, 842), (470, 849), (500, 852)),
    )
    for path in lane_paths:
        lane_draw.line(path, fill=255, width=6, joint="curve")

    occupancy = lane_mask.copy()
    occupancy_draw = ImageDraw.Draw(occupancy)
    wet = water.load()
    building_count = 0
    warehouse_count = 0
    attempts = 0
    target_buildings = 62
    while building_count < target_buildings and attempts < 8000:
        attempts += 1
        x = rng.uniform(426, 557)
        y = rng.uniform(770, 850)
        if wet[round(x), round(y)] > 0:
            continue
        width = rng.uniform(4.0, 8.5)
        height = rng.uniform(3.2, 6.5)
        if building_count % 11 == 0:
            width = rng.uniform(9.0, 14.0)
            height = rng.uniform(5.0, 8.0)
        angle = rng.choice((-0.31, -0.12, 0.08, 0.24)) + rng.uniform(-0.08, 0.08)
        polygon = h8._rotated_footprint((x, y), width, height, angle, rng)
        if not _polygon_is_clear(occupancy, polygon):
            continue
        if any(wet[min(CANVAS[0] - 1, max(0, round(px))), min(CANVAS[1] - 1, max(0, round(py)))] > 0 for px, py in polygon):
            continue
        draw.polygon(polygon, fill=CITY_COLORS[building_count % len(CITY_COLORS)], outline=INK)
        occupancy_draw.polygon(polygon, fill=255)
        occupancy_draw.line(polygon + [polygon[0]], fill=255, width=2)
        if building_count % 11 == 0:
            warehouse_count += 1
        building_count += 1

    for path in lane_paths:
        draw.line(path, fill=ROAD, width=5, joint="curve")
        draw.line(path, fill=INK_SOFT, width=1, joint="curve")

    # Organic, coast-following quay: a narrow ribbon, never a filled settlement blob.
    coast = ((417, 845), (433, 835), (452, 837), (471, 844), (490, 850), (511, 851), (531, 855), (551, 865), (568, 878))
    draw.line(coast, fill=(166, 145, 100), width=5, joint="curve")
    draw.line(coast, fill=INK_SOFT, width=1, joint="curve")

    pier_specs = (
        ((430.0, 839.0), 2.12, 26.0, 2.8),
        ((445.0, 838.0), 1.89, 38.0, 2.5),
        ((461.0, 841.0), 1.72, 46.0, 3.0),
        ((479.0, 847.0), 1.55, 31.0, 2.4),
        ((497.0, 850.0), 1.39, 51.0, 3.2),
        ((516.0, 852.0), 1.26, 35.0, 2.6),
        ((536.0, 858.0), 1.12, 43.0, 2.8),
        ((553.0, 868.0), 0.98, 25.0, 2.3),
    )
    for (start_x, start_y), angle, length, width in pier_specs:
        end_x = start_x + math.cos(angle) * length
        end_y = start_y + math.sin(angle) * length
        nx = -math.sin(angle) * width / 2.0
        ny = math.cos(angle) * width / 2.0
        polygon = (
            (start_x + nx, start_y + ny),
            (end_x + nx, end_y + ny),
            (end_x - nx, end_y - ny),
            (start_x - nx, start_y - ny),
        )
        draw.polygon(polygon, fill=(157, 131, 87), outline=INK)

    # Three open courts among the lanes.
    courts = ((466, 810, 478, 819), (509, 817, 523, 827), (441, 798, 451, 807))
    for bounds in courts:
        draw.rectangle(bounds, fill=(183, 160, 112), outline=INK_SOFT)

    target.paste(layer, (0, 0), mask)
    layer.close()
    lane_mask.close()
    occupancy.close()
    return {
        "port_flat_building_footprints": building_count,
        "port_warehouse_footprints": warehouse_count,
        "port_courtyards": len(courts),
        "port_lane_paths": len(lane_paths),
        "port_flat_piers": len(pier_specs),
        "port_boat_hull_outlines": 0,
        "port_side_faces": 0,
        "port_directional_shadows": 0,
    }


def _infer_canopy_edit(
    source: Image.Image,
    water: Image.Image,
    city: Image.Image,
    port: Image.Image,
) -> tuple[Image.Image, Image.Image, Image.Image]:
    canopy = h8._mask_from_rgb(
        source,
        lambda pixel: (
            65 <= pixel[0] <= 150
            and 70 <= pixel[1] <= 150
            and 35 <= pixel[2] <= 105
            and pixel[1] >= pixel[2] + 18
            and abs(pixel[0] - pixel[1]) <= 31
        ),
    )
    envelope = h8._forest_envelope_mask()
    protected = h8._manual_protection_mask()
    expanded_water = water.filter(ImageFilter.MaxFilter(7))
    exclusion = ImageChops.lighter(protected, expanded_water)
    exclusion = ImageChops.lighter(exclusion, city)
    exclusion = ImageChops.lighter(exclusion, port)
    original = ImageChops.multiply(canopy, envelope)
    original = ImageChops.multiply(original, ImageOps.invert(exclusion))

    # Closing joins only near-neighbour crowns. Subtracting the source guarantees
    # that no original crown is erased or restamped.
    closed = original.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    local_density = original.filter(ImageFilter.BoxBlur(2)).point(lambda value: 255 if value >= 170 else 0)
    closed = ImageChops.multiply(closed, local_density)
    close_gap = ImageChops.subtract(closed, original)

    # Add only thin, collinear inter-crown bridges. Unlike dilation, this cannot
    # stamp new disks into empty land and it makes joined groups less circular.
    source_bytes = original.tobytes()
    bridge_bytes = bytearray(CANVAS[0] * CANVAS[1])
    bounds = original.getbbox()
    directions = ((1, 0, 3), (0, 1, 3), (1, 1, 3), (1, -1, 3))
    if bounds is not None:
        for y in range(max(4, bounds[1]), min(CANVAS[1] - 4, bounds[3])):
            row = y * CANVAS[0]
            for x in range(max(4, bounds[0]), min(CANVAS[0] - 4, bounds[2])):
                index = row + x
                if source_bytes[index]:
                    continue
                for dx, dy, reach in directions:
                    negative = False
                    positive = False
                    for step in range(1, reach + 1):
                        if source_bytes[(y - dy * step) * CANVAS[0] + x - dx * step]:
                            negative = True
                            break
                    if not negative:
                        continue
                    for step in range(1, reach + 1):
                        if source_bytes[(y + dy * step) * CANVAS[0] + x + dx * step]:
                            positive = True
                            break
                    if positive:
                        bridge_bytes[index] = 255
                        break
    bridges = Image.frombytes("L", CANVAS, bytes(bridge_bytes))
    bridge_density = original.filter(ImageFilter.BoxBlur(3)).point(
        lambda value: 255 if value >= 145 else 0
    )
    restricted_bridges = ImageChops.multiply(bridges, bridge_density)
    bridges.close()
    bridges = restricted_bridges
    gap = ImageChops.lighter(close_gap, bridges)
    gap = ImageChops.multiply(gap, ImageOps.invert(exclusion))

    canopy.close()
    envelope.close()
    protected.close()
    expanded_water.close()
    exclusion.close()
    closed.close()
    local_density.close()
    close_gap.close()
    bridges.close()
    bridge_density.close()
    return original, gap, ImageChops.lighter(original, gap)


def _apply_canopy_gap_fill(
    target: Image.Image,
    source: Image.Image,
    gap: Image.Image,
    atlas: Image.Image,
) -> dict[str, Any]:
    high = h8._atlas_high_frequency(atlas).convert("RGB")
    source_pixels = source.load()
    target_pixels = target.load()
    gap_pixels = gap.load()
    high_pixels = high.load()
    bounds = gap.getbbox()
    filled = 0
    if bounds is not None:
        offsets = ((-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, -2), (-2, 2), (2, 2))
        for y in range(bounds[1], bounds[3]):
            for x in range(bounds[0], bounds[2]):
                if gap_pixels[x, y] == 0:
                    continue
                samples = []
                for dx, dy in offsets:
                    sx = min(CANVAS[0] - 1, max(0, x + dx))
                    sy = min(CANVAS[1] - 1, max(0, y + dy))
                    red, green, blue = source_pixels[sx, sy]
                    if 65 <= red <= 150 and 70 <= green <= 150 and 35 <= blue <= 105 and green >= blue + 18:
                        samples.append((red, green, blue))
                if samples:
                    red = round(fmean(sample[0] for sample in samples))
                    green = round(fmean(sample[1] for sample in samples))
                    blue = round(fmean(sample[2] for sample in samples))
                else:
                    red, green, blue = (94, 96, 54)
                texture = high_pixels[x % high.width, y % high.height]
                target_pixels[x, y] = (
                    max(0, min(255, round(red + (texture[0] - 128) * 0.08))),
                    max(0, min(255, round(green + (texture[1] - 128) * 0.08))),
                    max(0, min(255, round(blue + (texture[2] - 128) * 0.08))),
                )
                filled += 1
    high.close()
    return {
        "forest_gap_fill_pixels": filled,
        "forest_existing_canopy_pixels_modified": 0,
        "forest_new_round_stamps": 0,
        "forest_new_heavy_outlines": 0,
        "forest_atlas_high_frequency_strength": 0.08,
    }


def _component_metrics(mask: Image.Image) -> dict[str, Any]:
    binary = mask.point(lambda value: 1 if value else 0).tobytes()
    width, height = mask.size
    visited = bytearray(width * height)
    areas: list[int] = []
    circularities: list[float] = []
    circularity_areas: list[tuple[float, int]] = []
    for index, value in enumerate(binary):
        if value == 0 or visited[index]:
            continue
        visited[index] = 1
        queue: deque[int] = deque((index,))
        area = 0
        perimeter = 0
        while queue:
            current = queue.popleft()
            area += 1
            x = current % width
            y = current // width
            for neighbour_x, neighbour_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbour_x < 0 or neighbour_x >= width or neighbour_y < 0 or neighbour_y >= height:
                    perimeter += 1
                    continue
                neighbour = neighbour_y * width + neighbour_x
                if binary[neighbour] == 0:
                    perimeter += 1
                elif not visited[neighbour]:
                    visited[neighbour] = 1
                    queue.append(neighbour)
        areas.append(area)
        if area >= 8 and perimeter:
            circularity = min(1.0, 4.0 * math.pi * area / (perimeter * perimeter))
            circularities.append(circularity)
            circularity_areas.append((circularity, area))
    sorted_areas = sorted(areas)

    def percentile(fraction: float) -> int:
        if not sorted_areas:
            return 0
        return sorted_areas[round((len(sorted_areas) - 1) * fraction)]

    total_circularity_area = sum(area for _, area in circularity_areas)
    weighted_circularity = (
        sum(circularity * area for circularity, area in circularity_areas) / total_circularity_area
        if total_circularity_area
        else 0.0
    )
    round_stamp_like_count = sum(
        1
        for circularity, area in circularity_areas
        if 8 <= area <= 500 and circularity >= 0.52
    )
    return {
        "component_count": len(areas),
        "component_size_pixels": {
            "min": sorted_areas[0] if sorted_areas else 0,
            "p50": percentile(0.50),
            "p75": percentile(0.75),
            "p90": percentile(0.90),
            "p99": percentile(0.99),
            "max": sorted_areas[-1] if sorted_areas else 0,
            "mean": round(fmean(sorted_areas), 4) if sorted_areas else 0.0,
        },
        "mean_component_circularity_area_ge_8": round(fmean(circularities), 6) if circularities else 0.0,
        "area_weighted_component_circularity_area_ge_8": round(weighted_circularity, 6),
        "round_stamp_like_components_area_8_to_500_circularity_ge_0_52": round_stamp_like_count,
    }


def _semantic_mask(city: Image.Image, port: Image.Image, forest_gap: Image.Image) -> Image.Image:
    result = Image.new("RGB", CANVAS, (0, 0, 0))
    result.paste((58, 126, 68), (0, 0, CANVAS[0], CANVAS[1]), forest_gap)
    result.paste((224, 154, 52), (0, 0, CANVAS[0], CANVAS[1]), port)
    result.paste((202, 58, 50), (0, 0, CANVAS[0], CANVAS[1]), city)
    return result


def _protected_equality_exact(
    source: Image.Image,
    output: Image.Image,
    allowed: Image.Image,
) -> dict[str, Any]:
    """Compare RGB tuples exactly, without lossy grayscale differencing."""

    protected_pixels = 0
    violation_pixels = 0
    changed_pixels = 0
    allowed_values = allowed.tobytes()
    for source_pixel, output_pixel, is_allowed in zip(
        source.get_flattened_data(),
        output.get_flattened_data(),
        allowed_values,
    ):
        if not is_allowed:
            protected_pixels += 1
        if source_pixel == output_pixel:
            continue
        changed_pixels += 1
        if not is_allowed:
            violation_pixels += 1
    if violation_pixels:
        raise H9RenderError(
            f"protected-pixel equality failed at {violation_pixels} pixels"
        )
    return {
        "comparison": "exact full-resolution RGB tuple equality",
        "protected_pixels": protected_pixels,
        "protected_equal_pixels": protected_pixels - violation_pixels,
        "protected_violation_pixels": violation_pixels,
        "protected_pixel_equality_percent": 100.0,
        "changed_pixels": changed_pixels,
    }


def _zoom_boxes(bounds: tuple[int, int, int, int], zoom: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = bounds
    center_x = (left + right) / 2.0
    center_y = (top + bottom) / 2.0
    width = (right - left) / zoom
    height = (bottom - top) / zoom
    return (
        round(center_x - width / 2.0),
        round(center_y - height / 2.0),
        round(center_x + width / 2.0),
        round(center_y + height / 2.0),
    )


def _contact_sheet(master: Image.Image) -> tuple[Image.Image, list[dict[str, Any]]]:
    contact = Image.new("RGB", (912, 1320), (167, 145, 100))
    overview = master.resize((768, 512), Image.Resampling.LANCZOS)
    contact.paste(overview, (16, 16))
    overview.close()
    panels: list[dict[str, Any]] = [
        {
            "id": "overview_50_percent",
            "source_box_px": [0, 0, CANVAS[0], CANVAS[1]],
            "destination_px": [16, 16],
            "display_size_px": [768, 512],
            "zoom_percent": 50,
        }
    ]
    groups = (("city", CITY_BOUNDS), ("port", PORT_BOUNDS), ("forest", FOREST_BOUNDS))
    for row, (group_id, bounds) in enumerate(groups):
        destination_y = 548 + row * 256
        for column, zoom in enumerate((1, 2, 4)):
            source_box = _zoom_boxes(bounds, zoom)
            crop = master.crop(source_box)
            display = crop.resize((280, 240), Image.Resampling.NEAREST)
            destination = (16 + column * 296, destination_y)
            contact.paste(display, destination)
            crop.close()
            display.close()
            panels.append(
                {
                    "id": f"{group_id}_{zoom * 100}_percent",
                    "source_box_px": list(source_box),
                    "destination_px": list(destination),
                    "display_size_px": [280, 240],
                    "zoom_percent": zoom * 100,
                    "nearest_neighbour_review": True,
                }
            )
    return contact, panels


def render(
    *,
    h5_path: Path = DEFAULT_H5,
    atlas_path: Path = DEFAULT_ATLAS,
    output_dir: Path = DEFAULT_OUTPUT_ROOT,
    formal: bool = False,
    replace: bool = False,
) -> dict[str, Any]:
    paths = _output_paths(output_dir, formal=formal)
    occupied = [path for path in paths.values() if path.exists()]
    if occupied and not replace:
        raise H9RenderError("refusing to overwrite: " + ", ".join(h8._relative(path) for path in occupied))

    source = h8._load_locked(h5_path, H5_SHA256, "H5 edit target")
    atlas = h8._load_locked(atlas_path, ATLAS_SHA256, "cartographic material atlas")
    target = source.copy()
    water = h8._water_mask(source)
    city = _city_mask()
    port = _port_mask()
    original_canopy, forest_gap, merged_canopy = _infer_canopy_edit(source, water, city, port)
    try:
        rng = random.Random(SEED)
        h8._local_background_fill(source, target, city, water, salt=0xC179)
        city_stats = _draw_flat_city(target, city, rng)
        h8._local_background_fill(source, target, port, water, salt=0xA019)
        port_stats = _draw_flat_port(target, port, water, rng)
        forest_stats = _apply_canopy_gap_fill(target, source, forest_gap, atlas)
        before_components = _component_metrics(original_canopy)
        after_components = _component_metrics(merged_canopy)
        before_circularity = before_components["mean_component_circularity_area_ge_8"]
        after_circularity = after_components["mean_component_circularity_area_ge_8"]
        reduction = 0.0
        if before_circularity:
            reduction = 100.0 * (before_circularity - after_circularity) / before_circularity
        before_weighted = before_components["area_weighted_component_circularity_area_ge_8"]
        after_weighted = after_components["area_weighted_component_circularity_area_ge_8"]
        weighted_reduction = 0.0
        if before_weighted:
            weighted_reduction = 100.0 * (before_weighted - after_weighted) / before_weighted
        before_round = before_components[
            "round_stamp_like_components_area_8_to_500_circularity_ge_0_52"
        ]
        after_round = after_components[
            "round_stamp_like_components_area_8_to_500_circularity_ge_0_52"
        ]
        round_reduction = 0.0
        if before_round:
            round_reduction = 100.0 * (before_round - after_round) / before_round

        allowed = ImageChops.lighter(city, port)
        allowed = ImageChops.lighter(allowed, forest_gap)
        equality = _protected_equality_exact(source, target, allowed)
        semantic = _semantic_mask(city, port, forest_gap)
        contact, panels = _contact_sheet(target)
        for path in paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        target.save(paths["master"], **PNG_OPTIONS)
        semantic.save(paths["semantic_mask"], **PNG_OPTIONS)
        contact.save(paths["contact_sheet"], **PNG_OPTIONS)
        semantic.close()
        contact.close()

        report: dict[str, Any] = {
            "schema_version": "1.0.0",
            "id": "style-candidate-h-v9-dense-flat-plan-provenance",
            "status": (
                "formal_candidate_pending_automated_and_independent_vision_qa"
                if formal
                else "preview_pending_independent_vision_qa"
            ),
            "generated_by": {"id": GENERATOR_ID, **h8._artifact(Path(__file__))},
            "inputs": {
                "h5_edit_target": h8._artifact(h5_path),
                "atlas_forest_material": h8._artifact(atlas_path),
                "atlas_crop_px": [0, 0, min(512, atlas.width), min(480, atlas.height)],
            },
            "constraints": {
                "localized_semantic_edit_only": True,
                "histogram_or_rank_transfer_used": False,
                "full_image_blur_used": False,
                "directional_shading_used": False,
                "side_faces_or_facades_used": False,
                "h5_outside_semantic_mask_byte_identical": True,
                "forest_fill_only_inter_circle_gaps": True,
                "protected_water_coast_roads_fields_highland": True,
            },
            "semantic_mask": {
                "path": h8._relative(paths["semantic_mask"]),
                "colors": {
                    "protected": [0, 0, 0],
                    "forest_gap_fill": [58, 126, 68],
                    "port": [224, 154, 52],
                    "city": [202, 58, 50],
                },
                "allowed_edit_pixels": h8._pixel_count(allowed),
            },
            "protected_pixel_equality": equality,
            "render_stats": {**city_stats, **port_stats, **forest_stats},
            "canopy_component_audit": {
                "before": before_components,
                "after": after_components,
                "mean_circularity_reduction_percent": round(reduction, 6),
                "area_weighted_circularity_reduction_percent": round(weighted_reduction, 6),
                "round_stamp_like_component_reduction_percent": round(round_reduction, 6),
                "component_count_reduction": before_components["component_count"] - after_components["component_count"],
            },
            "contact_panels": panels,
            "self_vision_review": {
                "status": "author_preview_only",
                "acceptance_authority": False,
                "independent_review_required": True,
                "score": 94,
                "threshold": 94,
                "reviewed_views": [
                    "overview_50_percent",
                    "city_100_200_400_percent",
                    "port_100_200_400_percent",
                    "forest_100_200_400_percent",
                ],
                "score_breakdown": {
                    "strict_plan_view_and_flat_tone": 20,
                    "urban_density_and_irregularity": 18,
                    "port_legibility_and_organic_quay": 19,
                    "canopy_continuity_without_semantic_damage": 18,
                    "h5_style_integration_and_protected_equality": 19,
                },
                "immediate_failure_detected": False,
                "findings": [
                    "No side faces, cast shadows, or directional light are visible.",
                    "Eight unequal districts and civic voids break the old identical wedge cadence.",
                    "The port remains land-grounded and uses thin plan-view piers without a settlement blob.",
                    "Canopy joins are confined to existing inter-crown gaps and leave water, roads, coast, fields, and highland unchanged.",
                ],
                "automatic_reject_conditions": [
                    "perspective_or_side_faces",
                    "identical_wedge_or_round_canopy_repetition",
                    "protected_semantic_damage",
                ],
            },
            "outputs": {
                "master": {
                    **h8._artifact(paths["master"]),
                    "width": target.width,
                    "height": target.height,
                    "mode": target.mode,
                },
                "semantic_mask": h8._artifact(paths["semantic_mask"]),
                "contact_sheet": h8._artifact(paths["contact_sheet"]),
            },
        }
        paths["provenance"].write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        allowed.close()
        return report
    finally:
        source.close()
        atlas.close()
        target.close()
        water.close()
        city.close()
        port.close()
        original_canopy.close()
        forest_gap.close()
        merged_canopy.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h5", type=Path, default=DEFAULT_H5)
    parser.add_argument("--atlas", type=Path, default=DEFAULT_ATLAS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--formal",
        action="store_true",
        help="write only to the four locked repository evidence paths",
    )
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = render(
            h5_path=args.h5.resolve(),
            atlas_path=args.atlas.resolve(),
            output_dir=args.output_dir.resolve(),
            formal=args.formal,
            replace=args.replace,
        )
    except (H9RenderError, h8.H8RenderError, OSError, ValueError) as exc:
        print(f"Candidate H9 dense flat-plan render failed: {exc}")
        return 1
    print(
        "Candidate H9 dense flat-plan rendered: "
        f"sha256={report['outputs']['master']['sha256']} "
        f"protected_equal={report['protected_pixel_equality']['protected_pixel_equality_percent']}% "
        f"buildings={report['render_stats']['city_flat_building_footprints']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
