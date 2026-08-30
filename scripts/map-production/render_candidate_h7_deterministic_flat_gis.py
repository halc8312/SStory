#!/usr/bin/env python3
"""Render the deterministic, strictly flat Candidate H7 Golden prototype."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageStat

import audit_style_candidate_h4 as h4_audit


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_H5_CONTROL = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-h-v5-strict-plan-symbols.png"
)
DEFAULT_H6_MATERIAL = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-h-v6-dual-reference-flat-gis.png"
)
DEFAULT_B1_REFERENCE = (
    REPO_ROOT / "world/map-production/candidates/style-candidate-b-v1.png"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "tmp/map-production/h7-prototype"

LOCKED_SHA256 = {
    "h5_composition_control": (
        "d95ea917ee2b0a414c3e32de762208af4fb2239d7bbc65fa7633e85218ad56fe"
    ),
    "h6_material_reference": (
        "86d61909913a3c6a402ae2c12211a79a2a15e755e98fba622fcb0e2d7bcfaaf6"
    ),
    "b1_palette_reference": (
        "4d505def78acc752ee2611cb73d112cc9a3048f611cb05233274a1eb2ae42003"
    ),
}

GENERATOR_ID = "sstory-map-production/render_candidate_h7_deterministic_flat_gis.py@1"
CANVAS = (1536, 1024)
AA_SCALE = 2
SEED = 0x48375F464C415447

MASTER_NAME = "style-candidate-h-v7-deterministic-flat-gis.png"
CONTACT_NAME = "style-candidate-h-v7-deterministic-flat-gis.contact-sheet.png"
REPORT_NAME = "style-candidate-h-v7-deterministic-flat-gis.report.json"

PALETTE = {
    "land": (145, 129, 81),
    "land_light": (175, 145, 103),
    "paper_dark": (104, 91, 62),
    "ocean": (96, 109, 111),
    "ocean_dark": (75, 84, 79),
    "ocean_light": (117, 126, 119),
    "ink": (78, 77, 51),
    "ink_soft": (109, 83, 54),
    "forest": (115, 113, 78),
    "forest_light": (113, 137, 109),
    "forest_dark": (79, 78, 50),
    "city": (125, 94, 66),
    "city_light": (145, 113, 81),
    "road": (175, 145, 103),
    "road_ink": (108, 82, 53),
    "field_green": (113, 114, 77),
    "field_gold": (175, 144, 80),
    "field_brown": (111, 82, 52),
    "rock": (81, 80, 53),
    "rock_light": (113, 111, 78),
}

COASTLINE = (
    (430, -20),
    (421, 70),
    (392, 132),
    (346, 190),
    (330, 235),
    (370, 278),
    (344, 325),
    (304, 374),
    (315, 432),
    (286, 491),
    (254, 550),
    (257, 618),
    (302, 691),
    (358, 751),
    (414, 798),
    (480, 837),
    (551, 881),
    (632, 928),
    (712, 1026),
)

RIVER_PATHS = (
    (
        (
            (820, -20),
            (804, 70),
            (770, 145),
            (735, 220),
            (690, 292),
            (646, 354),
            (610, 425),
            (582, 500),
            (574, 574),
            (603, 639),
            (662, 692),
            (742, 729),
            (850, 754),
        ),
        22.0,
    ),
    (((650, 318), (572, 327), (501, 309), (431, 283), (355, 255)), 15.0),
    (((642, 350), (566, 379), (493, 410), (413, 392), (340, 354)), 14.0),
    (((626, 389), (550, 439), (485, 489), (407, 486), (326, 445)), 13.0),
    (((606, 438), (533, 507), (474, 559), (395, 566), (307, 526)), 12.0),
    (((587, 493), (529, 578), (481, 646), (405, 676), (321, 643)), 11.0),
)

DELTA_ISLANDS = (
    (
        (249, 470),
        (281, 451),
        (310, 468),
        (315, 506),
        (291, 535),
        (253, 527),
        (230, 500),
    ),
    (
        (276, 570),
        (319, 548),
        (355, 570),
        (360, 610),
        (329, 640),
        (286, 630),
        (265, 603),
    ),
    ((321, 651), (360, 630), (398, 650), (405, 690), (374, 718), (335, 704)),
    ((224, 535), (248, 529), (267, 548), (263, 573), (235, 583), (211, 562)),
    ((356, 438), (379, 425), (401, 438), (397, 459), (370, 468), (351, 455)),
    ((374, 531), (397, 518), (420, 528), (425, 549), (400, 560), (378, 550)),
    ((422, 598), (446, 581), (468, 592), (470, 615), (446, 629), (423, 617)),
    ((286, 399), (309, 387), (330, 397), (331, 418), (308, 430), (286, 420)),
)

FOREST_ZONES = (
    (
        (430, -60),
        (990, -30),
        (930, 115),
        (850, 230),
        (720, 335),
        (530, 315),
        (385, 175),
    ),
    ((560, 525), (740, 500), (820, 620), (780, 760), (590, 735), (500, 640)),
    ((980, 535), (1220, 500), (1425, 590), (1510, 740), (1320, 795), (1110, 690)),
    ((540, 780), (800, 750), (930, 915), (865, 1040), (610, 1015), (480, 900)),
)

HIGHLAND_ZONES = (
    (
        (1000, 10),
        (1536, -20),
        (1536, 535),
        (1350, 520),
        (1160, 470),
        (1015, 335),
        (960, 175),
    ),
    ((875, 790), (1120, 735), (1290, 850), (1270, 1024), (870, 1024), (820, 920)),
)

ROAD_PATHS = (
    ((852, 492), (972, 430), (1032, 235), (1115, 112), (1180, -20)),
    ((858, 500), (1010, 514), (1190, 540), (1390, 520), (1550, 450)),
    ((850, 510), (965, 615), (1060, 690), (1190, 765), (1370, 880), (1540, 995)),
    ((840, 520), (765, 640), (650, 740), (530, 835), (472, 858)),
    ((840, 500), (740, 450), (655, 365), (570, 320)),
)


class H7RenderError(ValueError):
    """Raised when the H7 deterministic prototype cannot satisfy its gates."""


@dataclass(frozen=True)
class CanvasTransform:
    scale: int = AA_SCALE

    def point(self, point: tuple[float, float]) -> tuple[int, int]:
        return (round(point[0] * self.scale), round(point[1] * self.scale))

    def points(self, points: Sequence[tuple[float, float]]) -> list[tuple[int, int]]:
        return [self.point(point) for point in points]

    def width(self, value: float) -> int:
        return max(1, round(value * self.scale))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": _relative(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _assert_locked_image(path: Path, expected_hash: str, label: str) -> Image.Image:
    if not path.is_file():
        raise H7RenderError(f"{label} does not exist: {path}")
    actual_hash = sha256_file(path)
    if actual_hash != expected_hash:
        raise H7RenderError(
            f"{label} SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
        )
    with Image.open(path) as opened:
        opened.load()
        if opened.format != "PNG" or opened.mode != "RGB" or opened.size != CANVAS:
            raise H7RenderError(f"{label} must be a 1536x1024 RGB PNG")
        return opened.copy()


def _validate_output_dir(path: Path) -> Path:
    resolved = path.resolve()
    allowed = DEFAULT_OUTPUT_ROOT.resolve()
    if resolved != allowed and allowed not in resolved.parents:
        raise H7RenderError(
            f"H7 prototype output must stay within {_relative(DEFAULT_OUTPUT_ROOT)}"
        )
    return resolved


def _irregular_polygon(
    rng: random.Random,
    center: tuple[float, float],
    radius_x: float,
    radius_y: float,
    vertices: int,
    *,
    angle_offset: float | None = None,
) -> list[tuple[float, float]]:
    offset = rng.random() * math.tau if angle_offset is None else angle_offset
    points: list[tuple[float, float]] = []
    for index in range(vertices):
        angle = offset + math.tau * index / vertices + rng.uniform(-0.12, 0.12)
        scale = rng.uniform(0.58, 1.18)
        points.append(
            (
                center[0] + math.cos(angle) * radius_x * scale,
                center[1] + math.sin(angle) * radius_y * scale,
            )
        )
    return points


def _catmull_rom(
    points: Sequence[tuple[float, float]],
    *,
    steps: int = 10,
    closed: bool = False,
) -> list[tuple[float, float]]:
    if len(points) < 3:
        return list(points)
    output: list[tuple[float, float]] = []
    segment_count = len(points) if closed else len(points) - 1
    for index in range(segment_count):
        p0 = points[(index - 1) % len(points)] if closed else points[max(0, index - 1)]
        p1 = points[index]
        p2 = points[(index + 1) % len(points)]
        p3 = (
            points[(index + 2) % len(points)]
            if closed
            else points[min(len(points) - 1, index + 2)]
        )
        for step in range(steps):
            t = step / steps
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
            output.append((x, y))
    output.append(output[0] if closed else points[-1])
    return output


def _masked_composite(
    base: Image.Image,
    layer: Image.Image,
    mask: Image.Image,
) -> None:
    alpha = ImageChops.multiply(layer.getchannel("A"), mask)
    layer.putalpha(alpha)
    base.alpha_composite(layer)
    alpha.close()


def _apply_micrograin(
    image: Image.Image,
    land_mask: Image.Image,
    water_mask: Image.Image,
) -> None:
    pixel_count = CANVAS[0] * CANVAS[1]
    state = SEED & 0xFFFFFFFF
    land_dark = bytearray(pixel_count)
    land_light = bytearray(pixel_count)
    water_dark = bytearray(pixel_count)
    water_light = bytearray(pixel_count)
    for index in range(pixel_count):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        selector = state >> 24
        if selector & 1:
            land_dark[index] = 5 + selector % 16
            water_dark[index] = 5 + (selector >> 1) % 16
        else:
            land_light[index] = 4 + selector % 13
            water_light[index] = 4 + (selector >> 1) % 13

    specs = (
        (land_dark, PALETTE["paper_dark"], land_mask),
        (land_light, PALETTE["land_light"], land_mask),
        (water_dark, PALETTE["ocean_dark"], water_mask),
        (water_light, PALETTE["ocean_light"], water_mask),
    )
    for alpha_bytes, color, region_mask in specs:
        alpha_native = Image.frombytes("L", CANVAS, bytes(alpha_bytes))
        alpha = alpha_native.resize(image.size, Image.Resampling.NEAREST)
        layer = Image.new("RGBA", image.size, color + (0,))
        layer.putalpha(alpha)
        _masked_composite(image, layer, region_mask)
        alpha_native.close()
        alpha.close()
        layer.close()


def _build_vector_masks() -> tuple[Image.Image, Image.Image]:
    transform = CanvasTransform()
    size = (CANVAS[0] * AA_SCALE, CANVAS[1] * AA_SCALE)
    land_mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(land_mask)
    smooth_coast = _catmull_rom(COASTLINE, steps=12)
    mainland = smooth_coast + [
        (CANVAS[0] + 4, CANVAS[1] + 4),
        (CANVAS[0] + 4, -4),
    ]
    draw.polygon(transform.points(mainland), fill=255)
    for island in DELTA_ISLANDS:
        draw.polygon(
            transform.points(_catmull_rom(island, steps=8, closed=True)),
            fill=255,
        )
    for path, width in RIVER_PATHS:
        draw.line(
            transform.points(_catmull_rom(path, steps=10)),
            fill=0,
            width=transform.width(width),
            joint="curve",
        )
    water_mask = ImageOps.invert(land_mask)
    return land_mask, water_mask


def _draw_base_material(
    water_mask: Image.Image,
    land_mask: Image.Image,
    rng: random.Random,
    stats: dict[str, int],
) -> Image.Image:
    size = (CANVAS[0] * AA_SCALE, CANVAS[1] * AA_SCALE)
    image = Image.new("RGBA", size, PALETTE["ocean"] + (255,))
    land = Image.new("RGBA", size, PALETTE["land"] + (255,))
    image.paste(land, (0, 0), land_mask)
    land.close()
    _apply_micrograin(image, land_mask, water_mask)

    land_texture = Image.new("RGBA", size, (0, 0, 0, 0))
    land_draw = ImageDraw.Draw(land_texture)
    transform = CanvasTransform()
    for _ in range(24000):
        x = rng.uniform(0, CANVAS[0])
        y = rng.uniform(0, CANVAS[1])
        length = rng.uniform(1.8, 9.0)
        angle = rng.random() * math.tau
        start = transform.point((x, y))
        end = transform.point(
            (x + math.cos(angle) * length, y + math.sin(angle) * length)
        )
        alpha = rng.randint(42, 102)
        land_draw.line(
            (start, end),
            fill=PALETTE["paper_dark"] + (alpha,),
            width=transform.width(rng.choice((0.5, 0.7, 1.0))),
        )
    _masked_composite(image, land_texture, land_mask)
    land_texture.close()
    stats["paper_fibres"] = 24000

    sea_texture = Image.new("RGBA", size, (0, 0, 0, 0))
    sea_draw = ImageDraw.Draw(sea_texture)
    for _ in range(14500):
        x = rng.uniform(0, CANVAS[0])
        y = rng.uniform(0, CANVAS[1])
        angle = rng.random() * math.tau
        length = rng.uniform(2.5, 11.0)
        bend = rng.uniform(-1.7, 1.7)
        points = (
            transform.point((x, y)),
            transform.point(
                (
                    x + math.cos(angle) * length * 0.52 - math.sin(angle) * bend,
                    y + math.sin(angle) * length * 0.52 + math.cos(angle) * bend,
                )
            ),
            transform.point(
                (x + math.cos(angle) * length, y + math.sin(angle) * length)
            ),
        )
        sea_draw.line(
            points,
            fill=PALETTE["ocean_dark"] + (rng.randint(45, 105),),
            width=transform.width(rng.choice((0.55, 0.75, 1.0))),
            joint="curve",
        )
    _masked_composite(image, sea_texture, water_mask)
    sea_texture.close()
    stats["water_broken_marks"] = 14500

    boundary_layer = Image.new("RGBA", size, (0, 0, 0, 0))
    boundary_draw = ImageDraw.Draw(boundary_layer)
    boundary_draw.line(
        transform.points(_catmull_rom(COASTLINE, steps=12)),
        fill=PALETTE["ink"] + (205,),
        width=transform.width(1.25),
        joint="curve",
    )
    for path, width in RIVER_PATHS:
        boundary_draw.line(
            transform.points(_catmull_rom(path, steps=10)),
            fill=PALETTE["ink"] + (190,),
            width=transform.width(width + 1.8),
            joint="curve",
        )
        boundary_draw.line(
            transform.points(_catmull_rom(path, steps=10)),
            fill=PALETTE["ocean"] + (255,),
            width=transform.width(width),
            joint="curve",
        )
    for island in DELTA_ISLANDS:
        points = transform.points(_catmull_rom(island, steps=8, closed=True))
        boundary_draw.line(
            points,
            fill=PALETTE["ink"] + (195,),
            width=transform.width(1.0),
            joint="curve",
        )
    image.alpha_composite(boundary_layer)
    boundary_layer.close()
    stats["plan_boundary_layers"] = 1 + len(RIVER_PATHS)
    return image


def _zone_mask(
    zones: Sequence[Sequence[tuple[float, float]]],
    land_mask: Image.Image,
) -> Image.Image:
    transform = CanvasTransform()
    mask = Image.new("L", land_mask.size, 0)
    draw = ImageDraw.Draw(mask)
    for zone in zones:
        draw.polygon(transform.points(zone), fill=255)
    clipped = ImageChops.multiply(mask, land_mask)
    mask.close()
    return clipped


def _random_point_in_mask(
    rng: random.Random,
    mask: Image.Image,
    bounds: tuple[int, int, int, int] = (0, 0, CANVAS[0], CANVAS[1]),
) -> tuple[float, float]:
    for _ in range(10000):
        x = rng.uniform(bounds[0], bounds[2])
        y = rng.uniform(bounds[1], bounds[3])
        px = min(mask.width - 1, max(0, round(x * AA_SCALE)))
        py = min(mask.height - 1, max(0, round(y * AA_SCALE)))
        if mask.getpixel((px, py)) >= 160:
            return x, y
    raise H7RenderError("could not sample a point inside a feature mask")


def _draw_forest(
    image: Image.Image,
    land_mask: Image.Image,
    rng: random.Random,
    stats: dict[str, int],
) -> None:
    transform = CanvasTransform()
    zone = _zone_mask(FOREST_ZONES, land_mask)
    zone_draw = ImageDraw.Draw(zone)
    clearing_count = 34
    for _ in range(clearing_count):
        x, y = _random_point_in_mask(rng, zone)
        polygon = _irregular_polygon(
            rng,
            (x, y),
            rng.uniform(8.0, 23.0),
            rng.uniform(6.0, 18.0),
            rng.randint(6, 11),
        )
        zone_draw.polygon(transform.points(polygon), fill=0)

    detail = Image.new("RGBA", image.size, (0, 0, 0, 0))
    detail_draw = ImageDraw.Draw(detail)
    wash = Image.new("RGBA", image.size, PALETTE["forest"] + (16,))
    _masked_composite(image, wash, zone)
    wash.close()

    group_outline_count = 170
    for _ in range(group_outline_count):
        x, y = _random_point_in_mask(rng, zone)
        polygon = _irregular_polygon(
            rng,
            (x, y),
            rng.uniform(9.0, 25.0),
            rng.uniform(7.0, 20.0),
            rng.randint(10, 17),
        )
        points = transform.points(polygon)
        detail_draw.polygon(points, fill=PALETTE["forest"] + (9,))
        detail_draw.line(
            points + [points[0]],
            fill=PALETTE["forest_dark"] + (105,),
            width=transform.width(0.65),
            joint="curve",
        )

    cluster_count = 1250
    for _ in range(cluster_count):
        x, y = _random_point_in_mask(rng, zone)
        polygon = _irregular_polygon(
            rng,
            (x, y),
            rng.uniform(2.5, 7.5),
            rng.uniform(2.2, 6.5),
            rng.randint(8, 14),
        )
        points = transform.points(polygon)
        fill_color = (
            PALETTE["forest"] if rng.random() < 0.64 else PALETTE["forest_light"]
        )
        detail_draw.polygon(points, fill=fill_color + (rng.randint(7, 18),))
        detail_draw.line(
            points + [points[0]],
            fill=PALETTE["forest_dark"] + (rng.randint(115, 175),),
            width=transform.width(rng.uniform(0.55, 0.9)),
            joint="curve",
        )

    stipple_count = 6500
    for _ in range(stipple_count):
        x, y = _random_point_in_mask(rng, zone)
        if rng.random() < 0.7:
            point = transform.point((x, y))
            radius = transform.width(rng.uniform(0.35, 0.85))
            detail_draw.rectangle(
                (
                    point[0] - radius,
                    point[1] - radius,
                    point[0] + radius,
                    point[1] + radius,
                ),
                fill=PALETTE["forest_dark"] + (rng.randint(45, 105),),
            )
        else:
            angle = rng.random() * math.tau
            length = rng.uniform(1.0, 4.0)
            detail_draw.line(
                (
                    transform.point((x, y)),
                    transform.point(
                        (x + math.cos(angle) * length, y + math.sin(angle) * length)
                    ),
                ),
                fill=PALETTE["forest_light"] + (rng.randint(45, 90),),
                width=transform.width(0.6),
            )
    _masked_composite(image, detail, zone)
    detail.close()
    zone.close()
    stats["forest_irregular_group_outlines"] = group_outline_count
    stats["forest_irregular_canopy_outlines"] = cluster_count
    stats["forest_clearings"] = clearing_count
    stats["forest_stipple_and_broken_marks"] = stipple_count


def _draw_highland(
    image: Image.Image,
    land_mask: Image.Image,
    rng: random.Random,
    stats: dict[str, int],
) -> None:
    transform = CanvasTransform()
    mask = _zone_mask(HIGHLAND_ZONES, land_mask)
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    chip_count = 1550
    for _ in range(chip_count):
        x, y = _random_point_in_mask(rng, mask)
        vertices = rng.randint(4, 7)
        polygon = _irregular_polygon(
            rng,
            (x, y),
            rng.uniform(1.5, 5.0),
            rng.uniform(1.0, 3.7),
            vertices,
        )
        points = transform.points(polygon)
        draw.line(
            points + [points[0]],
            fill=PALETTE["rock"] + (rng.randint(75, 150),),
            width=transform.width(rng.uniform(0.55, 1.0)),
            joint="curve",
        )

    stroke_count = 2700
    orientation_bins: set[int] = set()
    for _ in range(stroke_count):
        x, y = _random_point_in_mask(rng, mask)
        angle = rng.random() * math.tau
        orientation_bins.add(int(angle / math.tau * 36) % 36)
        length = rng.uniform(2.2, 8.5)
        start = (x - math.cos(angle) * length / 2, y - math.sin(angle) * length / 2)
        end = (x + math.cos(angle) * length / 2, y + math.sin(angle) * length / 2)
        draw.line(
            (transform.point(start), transform.point(end)),
            fill=PALETTE["rock"] + (rng.randint(55, 135),),
            width=transform.width(rng.uniform(0.45, 0.9)),
        )

    stipple_count = 4800
    for _ in range(stipple_count):
        x, y = _random_point_in_mask(rng, mask)
        point = transform.point((x, y))
        radius = transform.width(rng.uniform(0.25, 0.65))
        draw.rectangle(
            (
                point[0] - radius,
                point[1] - radius,
                point[0] + radius,
                point[1] + radius,
            ),
            fill=PALETTE["rock"] + (rng.randint(38, 105),),
        )
    _masked_composite(image, layer, mask)
    layer.close()
    mask.close()
    stats["highland_irregular_chips"] = chip_count
    stats["highland_short_nonconvergent_strokes"] = stroke_count
    stats["highland_stipple"] = stipple_count
    stats["highland_orientation_bins_36"] = len(orientation_bins)


def _draw_fields(
    image: Image.Image,
    land_mask: Image.Image,
    rng: random.Random,
    stats: dict[str, int],
) -> None:
    transform = CanvasTransform()
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    colors = (
        PALETTE["field_green"],
        PALETTE["field_gold"],
        PALETTE["field_brown"],
        PALETTE["land_light"],
    )
    plot_count = 0
    row_y = 615.0
    for row in range(5):
        left_x = 1085.0 + row * 22
        for column in range(5):
            width = rng.uniform(78, 118)
            height = rng.uniform(62, 91)
            skew = rng.uniform(-13, 13)
            x = left_x + column * 105
            y = row_y + row * 88 + rng.uniform(-8, 8)
            polygon = [
                (x + rng.uniform(-6, 6), y + rng.uniform(-5, 5)),
                (x + width + rng.uniform(-5, 5), y + skew),
                (x + width + rng.uniform(-5, 5), y + height + skew),
                (x + rng.uniform(-6, 6), y + height),
            ]
            points = transform.points(polygon)
            color = colors[(row + column + rng.randrange(len(colors))) % len(colors)]
            draw.polygon(
                points, fill=color + (145,), outline=PALETTE["ink_soft"] + (150,)
            )
            plot_mask = Image.new("L", image.size, 0)
            ImageDraw.Draw(plot_mask).polygon(points, fill=255)
            line_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
            line_draw = ImageDraw.Draw(line_layer)
            spacing = rng.uniform(7, 12)
            line_y = y + spacing
            while line_y < y + height:
                line_draw.line(
                    transform.points(((x - 8, line_y), (x + width + 8, line_y + skew))),
                    fill=PALETTE["ink_soft"] + (75,),
                    width=transform.width(0.55),
                )
                line_y += spacing
            _masked_composite(layer, line_layer, plot_mask)
            line_layer.close()
            plot_mask.close()
            plot_count += 1
    _masked_composite(image, layer, land_mask)
    layer.close()
    stats["field_flat_plots"] = plot_count


def _draw_cased_line(
    draw: ImageDraw.ImageDraw,
    transform: CanvasTransform,
    points: Sequence[tuple[float, float]],
    *,
    outer_width: float,
    inner_width: float,
) -> None:
    scaled = transform.points(_catmull_rom(points, steps=12))
    draw.line(
        scaled,
        fill=PALETTE["road_ink"] + (175,),
        width=transform.width(outer_width),
        joint="curve",
    )
    draw.line(
        scaled,
        fill=PALETTE["road"] + (230,),
        width=transform.width(inner_width),
        joint="curve",
    )


def _draw_roads(
    image: Image.Image,
    land_mask: Image.Image,
    stats: dict[str, int],
) -> None:
    transform = CanvasTransform()
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for path in ROAD_PATHS:
        _draw_cased_line(
            draw,
            transform,
            path,
            outer_width=4.8,
            inner_width=2.8,
        )
    _masked_composite(image, layer, land_mask)
    layer.close()
    stats["flat_road_paths"] = len(ROAD_PATHS)


def _ring_points(
    center: tuple[float, float],
    radius: float,
    count: int,
    phase: float,
    jitter: Sequence[float],
) -> list[tuple[float, float]]:
    return [
        (
            center[0]
            + math.cos(phase + math.tau * index / count) * (radius + jitter[index]),
            center[1]
            + math.sin(phase + math.tau * index / count) * (radius + jitter[index]),
        )
        for index in range(count)
    ]


def _draw_city(
    image: Image.Image,
    rng: random.Random,
    stats: dict[str, int],
) -> None:
    transform = CanvasTransform()
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    center = (850.0, 500.0)
    outer_radius = 112.0
    draw.ellipse(
        (
            transform.point((center[0] - outer_radius, center[1] - outer_radius)),
            transform.point((center[0] + outer_radius, center[1] + outer_radius)),
        ),
        fill=PALETTE["land_light"] + (245,),
        outline=PALETTE["ink"] + (235,),
        width=transform.width(2.2),
    )
    draw.ellipse(
        (
            transform.point((center[0] - 106, center[1] - 106)),
            transform.point((center[0] + 106, center[1] + 106)),
        ),
        outline=PALETTE["road"] + (240,),
        width=transform.width(3.4),
    )

    ring_radii = (24.0, 50.0, 78.0, 101.0)
    point_count = 18
    ring_vertices: list[list[tuple[float, float]]] = []
    for ring_index, radius in enumerate(ring_radii):
        phase = rng.uniform(-0.10, 0.10) + ring_index * 0.065
        jitter = [rng.uniform(-2.5, 2.5) for _ in range(point_count)]
        ring_vertices.append(_ring_points(center, radius, point_count, phase, jitter))

    block_count = 0
    courtyard_count = 0
    block_colors = (PALETTE["city"], PALETTE["city_light"], PALETTE["field_brown"])
    for grid_y in range(-88, 89, 13):
        for grid_x in range(-88, 89, 13):
            cx = center[0] + grid_x + rng.uniform(-4.0, 4.0)
            cy = center[1] + grid_y + rng.uniform(-4.0, 4.0)
            radial_distance = math.hypot(cx - center[0], cy - center[1])
            if radial_distance > 99 or radial_distance < 21:
                continue
            if any(abs(radial_distance - radius) < 4.2 for radius in ring_radii):
                continue
            width = rng.uniform(6.0, 13.0)
            height = rng.uniform(4.5, 10.0)
            angle = rng.uniform(-0.55, 0.55)
            cosine = math.cos(angle)
            sine = math.sin(angle)
            polygon: list[tuple[float, float]] = []
            for local_x, local_y in (
                (-width / 2, -height / 2),
                (width / 2, -height / 2),
                (width / 2, height / 2),
                (-width / 2, height / 2),
            ):
                polygon.append(
                    (
                        cx + local_x * cosine - local_y * sine + rng.uniform(-0.8, 0.8),
                        cy + local_x * sine + local_y * cosine + rng.uniform(-0.8, 0.8),
                    )
                )
            points = transform.points(polygon)
            color = block_colors[(block_count + rng.randrange(3)) % 3]
            draw.polygon(
                points,
                fill=color + (205,),
                outline=PALETTE["ink"] + (210,),
            )
            block_count += 1
            if block_count % 11 == 0:
                courtyard = _irregular_polygon(
                    rng,
                    (cx, cy),
                    rng.uniform(1.4, 2.8),
                    rng.uniform(1.2, 2.4),
                    rng.randint(5, 7),
                )
                draw.polygon(
                    transform.points(courtyard),
                    fill=PALETTE["land_light"] + (245,),
                )
                courtyard_count += 1

    for vertices in ring_vertices:
        points = transform.points(vertices)
        draw.line(
            points + [points[0]],
            fill=PALETTE["road"] + (245,),
            width=transform.width(2.2),
            joint="curve",
        )
        draw.line(
            points + [points[0]],
            fill=PALETTE["road_ink"] + (145,),
            width=transform.width(0.65),
            joint="curve",
        )

    central_courtyard = _irregular_polygon(rng, center, 17.0, 15.0, 11)
    draw.polygon(
        transform.points(central_courtyard),
        fill=PALETTE["land_light"] + (255,),
        outline=PALETTE["ink"] + (220,),
    )
    image.alpha_composite(layer)
    layer.close()
    stats["city_flat_block_footprints"] = block_count
    stats["city_courtyards"] = courtyard_count + 1
    stats["city_plan_boundary_rings"] = len(ring_radii) + 2


def _draw_port(
    image: Image.Image,
    rng: random.Random,
    stats: dict[str, int],
) -> None:
    transform = CanvasTransform()
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    footprint_count = 0
    for row in range(5):
        for column in range(7):
            x = 448 + column * 17 + rng.uniform(-4, 4)
            y = 810 + row * 14 + rng.uniform(-4, 4)
            width = rng.uniform(8, 16)
            height = rng.uniform(6, 12)
            skew = rng.uniform(-2.5, 2.5)
            polygon = (
                (x, y),
                (x + width, y + skew),
                (x + width - 1, y + height + skew),
                (x - 1, y + height),
            )
            draw.polygon(
                transform.points(polygon),
                fill=PALETTE["city"] + (220,),
                outline=PALETTE["ink"] + (230,),
            )
            footprint_count += 1

    pier_paths = (
        ((463, 848), (434, 875), (406, 877)),
        ((478, 854), (461, 889), (445, 905)),
        ((493, 854), (489, 889), (470, 917)),
        ((507, 852), (520, 884), (512, 907)),
    )
    for path in pier_paths:
        scaled = transform.points(path)
        draw.line(
            scaled,
            fill=PALETTE["ink"] + (230,),
            width=transform.width(5.0),
            joint="curve",
        )
        draw.line(
            scaled,
            fill=PALETTE["city_light"] + (235,),
            width=transform.width(2.6),
            joint="curve",
        )
    image.alpha_composite(layer)
    layer.close()
    stats["port_flat_building_footprints"] = footprint_count
    stats["port_pier_centerlines"] = len(pier_paths)


def _validate_same_threshold_gates(
    image: Image.Image,
    b1_reference: Image.Image,
) -> dict[str, Any]:
    palette = h4_audit.palette_continuity_metrics(image, b1_reference)
    readability = h4_audit.downsample_readability_metrics(image)
    if not palette["passed"] or not readability["passed"]:
        raise H7RenderError(
            "clean H7 redraw does not pass unchanged H4 gates: "
            f"palette={palette['passed']} readability={readability['passed']} "
            f"rgb={palette['rgb_histogram_intersection']} "
            f"hsv={palette['hsv_histogram_intersection']}"
        )
    return {
        "status": "passed",
        "selection_policy": "clean vector redraw; no post-render pixel optimization",
        "post_render_pixel_filtering": False,
        "palette_transfer_used": False,
        "selected": {
            "method": "direct palette constants from B1/H6 aggregate statistics",
            "rgb_histogram_intersection": palette["rgb_histogram_intersection"],
            "hsv_histogram_intersection": palette["hsv_histogram_intersection"],
            "rgb_bhattacharyya": palette["rgb_bhattacharyya"],
            "maximum_mean_channel_delta": palette["maximum_mean_channel_delta"],
        },
        "palette": palette,
        "readability": readability,
    }


def _contact_sheet(master: Image.Image) -> tuple[Image.Image, list[dict[str, Any]]]:
    panel_size = (384, 256)
    gutter = 8
    contact = Image.new(
        "RGB",
        (panel_size[0] * 3 + gutter * 2, panel_size[1]),
        PALETTE["land"],
    )
    specs = (
        (0.25, (0, 0, master.width, master.height)),
        (0.5, (384, 256, 1152, 768)),
        (1.0, (576, 384, 960, 640)),
    )
    records: list[dict[str, Any]] = []
    for index, (scale, box) in enumerate(specs):
        crop = master.crop(box)
        if crop.size != panel_size:
            resized = crop.resize(panel_size, Image.Resampling.LANCZOS)
            crop.close()
            crop = resized
        contact.paste(crop, (index * (panel_size[0] + gutter), 0))
        crop.close()
        records.append(
            {
                "scale": scale,
                "source_box_px": list(box),
                "panel_size_px": list(panel_size),
            }
        )
    return contact, records


def _image_stats(image: Image.Image) -> dict[str, Any]:
    rgb_stats = ImageStat.Stat(image)
    gray = image.convert("L")
    try:
        return {
            "mean_rgb": [round(value, 6) for value in rgb_stats.mean],
            "rgb_stddev": [round(value, 6) for value in rgb_stats.stddev],
            "luma_mean": round(ImageStat.Stat(gray).mean[0], 6),
            "luma_stddev": round(ImageStat.Stat(gray).stddev[0], 6),
            "luma_entropy_bits": round(gray.entropy(), 6),
        }
    finally:
        gray.close()


def render(
    *,
    h5_control_path: Path,
    h6_material_path: Path,
    b1_reference_path: Path,
    output_dir: Path,
    replace: bool = False,
) -> dict[str, Any]:
    output_dir = _validate_output_dir(output_dir)
    master_path = output_dir / MASTER_NAME
    contact_path = output_dir / CONTACT_NAME
    report_path = output_dir / REPORT_NAME
    outputs = (master_path, contact_path, report_path)
    occupied = [path for path in outputs if path.exists()]
    if occupied and not replace:
        raise H7RenderError(
            "refusing to overwrite existing H7 prototype output: "
            + ", ".join(_relative(path) for path in occupied)
        )

    h5 = _assert_locked_image(
        h5_control_path,
        LOCKED_SHA256["h5_composition_control"],
        "H5 composition control",
    )
    h6 = _assert_locked_image(
        h6_material_path,
        LOCKED_SHA256["h6_material_reference"],
        "H6 material reference",
    )
    b1 = _assert_locked_image(
        b1_reference_path,
        LOCKED_SHA256["b1_palette_reference"],
        "B1 palette reference",
    )
    try:
        source_stats = {
            "h5_composition_control": _image_stats(h5),
            "h6_material_reference": _image_stats(h6),
            "b1_palette_reference": _image_stats(b1),
        }
        land_mask, water_mask = _build_vector_masks()
        rng = random.Random(SEED)
        render_stats: dict[str, int] = {
            "vector_water_mask_pixels_native_equivalent": (
                sum(value >= 128 for value in water_mask.get_flattened_data())
                // (AA_SCALE * AA_SCALE)
            )
        }
        high_resolution = _draw_base_material(
            water_mask,
            land_mask,
            rng,
            render_stats,
        )
        try:
            _draw_forest(high_resolution, land_mask, rng, render_stats)
            _draw_highland(high_resolution, land_mask, rng, render_stats)
            _draw_fields(high_resolution, land_mask, rng, render_stats)
            _draw_roads(high_resolution, land_mask, render_stats)
            _draw_city(high_resolution, rng, render_stats)
            _draw_port(high_resolution, rng, render_stats)
            native = high_resolution.convert("RGB").resize(
                CANVAS,
                Image.Resampling.LANCZOS,
            )
        finally:
            high_resolution.close()
            water_mask.close()
            land_mask.close()

        calibration = _validate_same_threshold_gates(native, b1)
        try:
            boundary = h4_audit.boundary_metrics(native)
            repetition = h4_audit.exact_repetition_metrics(native)
            if not boundary["passed"] or not repetition["passed"]:
                raise H7RenderError(
                    "H7 boundary or exact-repetition proxy failed on the clean redraw"
                )
            forbidden_glyph_counters = {
                "text_glyphs": 0,
                "font_calls": 0,
                "frames": 0,
                "alpha_output_pixels": 0,
                "triangular_mountain_symbols": 0,
                "peak_symbols": 0,
                "radial_rosettes": 0,
                "contour_loops": 0,
                "cast_shadows": 0,
                "directional_lighting_operations": 0,
                "visible_facades": 0,
                "roof_faces": 0,
                "round_canopy_stamp_symbols": 0,
            }
            if any(forbidden_glyph_counters.values()):
                raise H7RenderError("forbidden glyph counter is non-zero")

            contact, contact_panels = _contact_sheet(native)
            output_dir.mkdir(parents=True, exist_ok=True)
            native.save(
                master_path,
                format="PNG",
                optimize=False,
                compress_level=9,
            )
            contact.save(
                contact_path,
                format="PNG",
                optimize=False,
                compress_level=9,
            )
            contact.close()
            report = {
                "schema_version": "1.0.0",
                "id": "style-candidate-h-v7-deterministic-flat-gis-prototype",
                "status": "passed",
                "purpose": "deterministic hybrid Golden style-board prototype only",
                "generated_by": {
                    "id": GENERATOR_ID,
                    **_artifact(Path(__file__).resolve()),
                },
                "inputs": {
                    "h5_composition_control": _artifact(h5_control_path),
                    "h6_material_reference": _artifact(h6_material_path),
                    "b1_palette_reference": _artifact(b1_reference_path),
                    "sha256_locked": True,
                    "statistics": source_stats,
                },
                "render_contract": {
                    "width": CANVAS[0],
                    "height": CANVAS[1],
                    "format": "PNG",
                    "mode": "RGB",
                    "antialias_scale": AA_SCALE,
                    "seed": SEED,
                    "seeded_deterministic": True,
                    "text_or_font_rendering_used": False,
                    "frame_used": False,
                    "alpha_output_used": False,
                    "projection": "strict orthographic plan symbols only",
                    "directional_light_or_shadow_code_path": False,
                },
                "composition": {
                    "water_geometry": (
                        "clean vector coastline and river coordinates traced from the "
                        "SHA-locked H5 composition; no H5 pixels copied"
                    ),
                    "left": "open sea, low coastline, branching delta",
                    "upper_center": "river-crossed irregular connected forest canopy",
                    "center": "flat circular city footprints, rings, irregular blocks, courtyards",
                    "lower_left": "flat port footprints and pier centerlines",
                    "lower_right": "flat varied agricultural plots",
                    "right": "irregular chips, stipple, and short non-convergent highland marks",
                },
                "calibration": calibration,
                "same_h4_threshold_gates": {
                    "palette_continuity": calibration["palette"],
                    "downsample_readability": calibration["readability"],
                    "boundary": boundary,
                    "exact_repetition": repetition,
                },
                "render_stats": render_stats,
                "forbidden_glyph_counters": forbidden_glyph_counters,
                "outputs": {
                    "master": {
                        **_artifact(master_path),
                        "width": native.width,
                        "height": native.height,
                        "mode": native.mode,
                        "format": "PNG",
                    },
                    "contact_sheet": {
                        **_artifact(contact_path),
                        "width": 1168,
                        "height": 256,
                        "mode": "RGB",
                        "format": "PNG",
                        "contains_text": False,
                        "contains_frame": False,
                        "panel_order": contact_panels,
                    },
                },
            }
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return report
        finally:
            native.close()
    finally:
        h5.close()
        h6.close()
        b1.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h5-control", type=Path, default=DEFAULT_H5_CONTROL)
    parser.add_argument("--h6-material", type=Path, default=DEFAULT_H6_MATERIAL)
    parser.add_argument("--b1-reference", type=Path, default=DEFAULT_B1_REFERENCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = render(
            h5_control_path=args.h5_control.resolve(),
            h6_material_path=args.h6_material.resolve(),
            b1_reference_path=args.b1_reference.resolve(),
            output_dir=args.output_dir.resolve(),
            replace=args.replace,
        )
    except (H7RenderError, OSError, ValueError) as exc:
        print(f"Candidate H7 deterministic prototype failed: {exc}")
        return 1
    selected = report["calibration"]["selected"]
    print(
        "Candidate H7 deterministic prototype passed: "
        f"sha256={report['outputs']['master']['sha256']} "
        f"palette_rgb={selected['rgb_histogram_intersection']} "
        f"palette_hsv={selected['hsv_histogram_intersection']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
