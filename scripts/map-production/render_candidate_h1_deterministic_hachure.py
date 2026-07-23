#!/usr/bin/env python3
"""Render deterministic H1 cartographic hachure prototypes over the locked D4 base.

This is intentionally a diagnostic-only renderer.  It does not publish a style
candidate or modify the production manifest.  The G2 footprint raster is the
only edit permission, while the G3 source contributes direction ensembles and
the two open-saddle locations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = (
    REPO_ROOT
    / "world/map-production/candidates/"
    "style-candidate-d-v4-erase-route-marks.png"
)
G2_SOURCE_PATH = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-g-v2-topology-guide.json"
)
G2_RASTER_PATH = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-g-v2-topology-guide.png"
)
G3_SOURCE_PATH = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-g-v3-hachure-skeleton.json"
)
G3_RASTER_PATH = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-g-v3-hachure-skeleton.png"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "tmp/map-production/h1-prototype"
CANVAS = (1536, 1024)

LOCKED_SHA256 = {
    "base": "c8c15f3e0fba49165c5d85f8369b91e7171d88d7059a58c0948e0d1339864016",
    "g2_source": "9646d14a89dfd7fd9dccba3d1d3bd14fe9b492623d8850d2d7524c5ff42adc01",
    "g2_raster": "a6c8815d5f1a769a6ebfeda8478cf52f586fdb3fd11156c734c3e43d9b6b188f",
    "g3_source": "d6d68f39861802aa28ebf4a42fece89433da80fe616a79fdba57a34aca3baeb6",
    "g3_raster": "dc8978b184755de6ba21f10a120bfb413b0976fed642b106065eff82dee34da3",
}

ROAD_STROKES = (
    (
        "north-road",
        (
            (1085, 160),
            (1060, 180),
            (1035, 200),
            (1005, 225),
            (982, 250),
            (970, 280),
            (966, 320),
            (960, 350),
            (946, 375),
            (918, 400),
            (910, 425),
            (900, 455),
            (895, 485),
        ),
    ),
    (
        "east-road",
        ((930, 505), (1050, 515), (1180, 540), (1270, 535), (1370, 490), (1535, 450)),
    ),
    (
        "south-east-road",
        (
            (910, 558),
            (1000, 610),
            (1090, 666),
            (1180, 725),
            (1270, 785),
            (1360, 840),
            (1450, 892),
            (1535, 936),
        ),
    ),
)


class HachurePrototypeError(ValueError):
    """Raised before an invalid or nonconforming prototype can be written."""


@dataclass(frozen=True)
class Variant:
    slug: str
    description: str
    main_spacing_px: int
    foothill_spacing_px: int
    main_density: float
    foothill_density: float
    main_length_px: tuple[int, int]
    foothill_length_px: tuple[int, int]
    angle_jitter_degrees: float
    stroke_width_px: int
    stroke_delta_levels: int
    wash_delta_levels: int
    boundary_feather_px: float
    main_rise_wash_delta_levels: int = 0
    road_core_width_px: int = 16
    road_feather_px: float = 5.0
    saddle_clear_width_px: int = 20


VARIANTS = (
    Variant(
        slug="balanced",
        description="Vision-tuned hierarchy: clearly readable six-footprint relief without directional light.",
        main_spacing_px=13,
        foothill_spacing_px=12,
        main_density=0.74,
        foothill_density=0.76,
        main_length_px=(10, 22),
        foothill_length_px=(8, 18),
        angle_jitter_degrees=12.0,
        stroke_width_px=2,
        stroke_delta_levels=34,
        wash_delta_levels=6,
        boundary_feather_px=10.0,
        main_rise_wash_delta_levels=8,
    ),
    Variant(
        slug="quiet",
        description="Sparser, darker individual strokes with almost no areal wash.",
        main_spacing_px=19,
        foothill_spacing_px=17,
        main_density=0.57,
        foothill_density=0.62,
        main_length_px=(10, 20),
        foothill_length_px=(8, 16),
        angle_jitter_degrees=14.0,
        stroke_width_px=2,
        stroke_delta_levels=20,
        wash_delta_levels=1,
        boundary_feather_px=11.0,
    ),
    Variant(
        slug="textured",
        description="Denser low-contrast strokes and the strongest still-flat support wash.",
        main_spacing_px=14,
        foothill_spacing_px=13,
        main_density=0.65,
        foothill_density=0.70,
        main_length_px=(8, 18),
        foothill_length_px=(7, 15),
        angle_jitter_degrees=15.0,
        stroke_width_px=1,
        stroke_delta_levels=15,
        wash_delta_levels=3,
        boundary_feather_px=9.0,
    ),
)
VARIANT_BY_SLUG = {variant.slug: variant for variant in VARIANTS}


@dataclass
class Landform:
    identifier: str
    role: str
    mask: Image.Image
    saddle_mask: Image.Image
    groups: tuple[tuple[tuple[tuple[int, int], ...], ...], ...]
    group_centers: tuple[tuple[float, float], ...]
    center: tuple[float, float]
    area_pixels: int

    def close(self) -> None:
        self.mask.close()
        self.saddle_mask.close()


@dataclass
class Inputs:
    base: Image.Image
    permission: Image.Image
    landforms: tuple[Landform, ...]
    source_metrics: dict[str, Any]

    def close(self) -> None:
        self.base.close()
        self.permission.close()
        for landform in self.landforms:
            landform.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _read_locked_json(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise HachurePrototypeError(f"missing {label}: {path}")
    actual_sha256 = _sha256(path)
    if actual_sha256 != expected_sha256:
        raise HachurePrototypeError(
            f"{label} SHA-256 mismatch: {actual_sha256} != {expected_sha256}"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HachurePrototypeError(f"cannot decode {label}") from error
    if not isinstance(value, dict):
        raise HachurePrototypeError(f"{label} root must be an object")
    return value


def _read_locked_image(path: Path, expected_sha256: str, label: str) -> Image.Image:
    if not path.is_file():
        raise HachurePrototypeError(f"missing {label}: {path}")
    actual_sha256 = _sha256(path)
    if actual_sha256 != expected_sha256:
        raise HachurePrototypeError(
            f"{label} SHA-256 mismatch: {actual_sha256} != {expected_sha256}"
        )
    try:
        with Image.open(path) as opened:
            opened.load()
            if opened.format != "PNG" or opened.mode != "RGB" or opened.size != CANVAS:
                raise HachurePrototypeError(
                    f"{label} must be an exact {CANVAS[0]}x{CANVAS[1]} RGB PNG"
                )
            return opened.copy()
    except HachurePrototypeError:
        raise
    except (OSError, ValueError) as error:
        raise HachurePrototypeError(f"cannot decode {label}") from error


def _count_selected(mask: Image.Image) -> int:
    return sum(mask.histogram()[1:])


def _exact_color_mask(image: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    channels = image.split()
    selected: list[Image.Image] = []
    combined: Image.Image | None = None
    try:
        for channel, expected in zip(channels, color):
            selected.append(channel.point(lambda value, expected=expected: 255 if value == expected else 0))
        first_pair = ImageChops.darker(selected[0], selected[1])
        try:
            combined = ImageChops.darker(first_pair, selected[2])
            return combined.copy()
        finally:
            first_pair.close()
    finally:
        for channel in channels:
            channel.close()
        for mask in selected:
            mask.close()
        if combined is not None:
            combined.close()


def _nearest_selected(mask: Image.Image, point: tuple[int, int], radius: int = 24) -> tuple[int, int]:
    if mask.getpixel(point):
        return point
    x, y = point
    for distance in range(1, radius + 1):
        for dx in range(-distance, distance + 1):
            for dy in (-distance, distance):
                candidate = x + dx, y + dy
                if 0 <= candidate[0] < CANVAS[0] and 0 <= candidate[1] < CANVAS[1]:
                    if mask.getpixel(candidate):
                        return candidate
        for dy in range(-distance + 1, distance):
            for dx in (-distance, distance):
                candidate = x + dx, y + dy
                if 0 <= candidate[0] < CANVAS[0] and 0 <= candidate[1] < CANVAS[1]:
                    if mask.getpixel(candidate):
                        return candidate
    raise HachurePrototypeError(f"no footprint pixel near source segment point {point}")


def _isolate_component(mask: Image.Image, seed: tuple[int, int]) -> Image.Image:
    flood = mask.copy()
    selected: Image.Image | None = None
    try:
        seed = _nearest_selected(flood, seed)
        ImageDraw.floodfill(flood, seed, 128, thresh=0)
        selected = flood.point(lambda value: 255 if value == 128 else 0)
        if _count_selected(selected) == 0:
            raise HachurePrototypeError(f"empty footprint component at {seed}")
        return selected.copy()
    finally:
        flood.close()
        if selected is not None:
            selected.close()


def _mask_center(mask: Image.Image) -> tuple[float, float]:
    bounds = mask.getbbox()
    if bounds is None:
        raise HachurePrototypeError("cannot center an empty footprint")
    return (bounds[0] + bounds[2] - 1) / 2, (bounds[1] + bounds[3] - 1) / 2


def _group_center(group: tuple[tuple[tuple[int, int], ...], ...]) -> tuple[float, float]:
    midpoints = (
        ((segment[0][0] + segment[-1][0]) / 2, (segment[0][1] + segment[-1][1]) / 2)
        for segment in group
    )
    values = tuple(midpoints)
    return (
        sum(point[0] for point in values) / len(values),
        sum(point[1] for point in values) / len(values),
    )


def _organic_saddle_mask(
    box: Sequence[int] | None,
    footprint: Image.Image,
    width: int,
) -> Image.Image:
    saddle = Image.new("L", CANVAS, 0)
    if box is None:
        return saddle
    if len(box) != 4 or any(not isinstance(value, int) for value in box):
        saddle.close()
        raise HachurePrototypeError("main landform saddle_clear_box must have four integers")
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 < CANVAS[0] and 0 <= y0 < y1 < CANVAS[1]):
        saddle.close()
        raise HachurePrototypeError("main landform saddle_clear_box is outside the canvas")
    center_x = (x0 + x1) / 2
    half_width = width / 2
    left: list[tuple[int, int]] = []
    right: list[tuple[int, int]] = []
    samples = 16
    for index in range(samples + 1):
        ratio = index / samples
        y = y0 + ratio * (y1 - y0)
        bend = math.sin((ratio - 0.5) * math.pi) * min(6.0, (x1 - x0) * 0.08)
        taper = 0.82 + 0.18 * math.sin(math.pi * ratio)
        left.append((round(center_x + bend - half_width * taper), round(y)))
        right.append((round(center_x + bend + half_width * taper), round(y)))
    ImageDraw.Draw(saddle).polygon(left + list(reversed(right)), fill=255)
    clipped = ImageChops.darker(saddle, footprint)
    saddle.close()
    return clipped


def _normalize_groups(raw_groups: object, identifier: str) -> tuple[tuple[tuple[tuple[int, int], ...], ...], ...]:
    if not isinstance(raw_groups, list) or not raw_groups:
        raise HachurePrototypeError(f"{identifier} must declare at least one G3 group")
    groups: list[tuple[tuple[tuple[int, int], ...], ...]] = []
    for group in raw_groups:
        if not isinstance(group, dict) or not isinstance(group.get("segments"), list):
            raise HachurePrototypeError(f"{identifier} has an invalid G3 group")
        segments: list[tuple[tuple[int, int], ...]] = []
        for segment in group["segments"]:
            points = segment.get("points") if isinstance(segment, dict) else None
            if not isinstance(points, list) or not 2 <= len(points) <= 3:
                raise HachurePrototypeError(f"{identifier} has an invalid G3 segment")
            normalized: list[tuple[int, int]] = []
            for point in points:
                if (
                    not isinstance(point, list)
                    or len(point) != 2
                    or any(not isinstance(value, int) for value in point)
                ):
                    raise HachurePrototypeError(f"{identifier} has a malformed G3 point")
                normalized.append((point[0], point[1]))
            segments.append(tuple(normalized))
        groups.append(tuple(segments))
    return tuple(groups)


def load_inputs() -> Inputs:
    base = _read_locked_image(BASE_PATH, LOCKED_SHA256["base"], "D4 base")
    guide = _read_locked_image(G2_RASTER_PATH, LOCKED_SHA256["g2_raster"], "G2 raster")
    skeleton_raster = _read_locked_image(
        G3_RASTER_PATH, LOCKED_SHA256["g3_raster"], "G3 raster"
    )
    g2 = _read_locked_json(G2_SOURCE_PATH, LOCKED_SHA256["g2_source"], "G2 source")
    g3 = _read_locked_json(G3_SOURCE_PATH, LOCKED_SHA256["g3_source"], "G3 source")
    permission = Image.new("L", CANVAS, 0)
    landforms: list[Landform] = []
    color_masks: dict[tuple[int, int, int], Image.Image] = {}
    try:
        if g2.get("canvas") != {"width": CANVAS[0], "height": CANVAS[1]}:
            raise HachurePrototypeError("G2 source canvas differs from D4")
        if g3.get("canvas") != {"width": CANVAS[0], "height": CANVAS[1]}:
            raise HachurePrototypeError("G3 source canvas differs from D4")
        g2_shapes = g2.get("shapes")
        g3_landforms = g3.get("landforms")
        if not isinstance(g2_shapes, list) or not isinstance(g3_landforms, list):
            raise HachurePrototypeError("G2/G3 sources must declare ordered landforms")
        if len(g2_shapes) != 6 or len(g3_landforms) != 6:
            raise HachurePrototypeError("H1 requires exactly six G2/G3 landforms")

        for index, (shape, source) in enumerate(zip(g2_shapes, g3_landforms)):
            if not isinstance(shape, dict) or not isinstance(source, dict):
                raise HachurePrototypeError(f"landform {index} must be an object")
            identifier = source.get("id")
            if identifier != shape.get("id") or source.get("role") != shape.get("role"):
                raise HachurePrototypeError(f"G2/G3 identity mismatch at landform {index}")
            if not isinstance(identifier, str) or not identifier:
                raise HachurePrototypeError(f"landform {index} has no identifier")
            rgb_raw = source.get("footprint_rgb")
            if (
                not isinstance(rgb_raw, list)
                or len(rgb_raw) != 3
                or any(not isinstance(value, int) or not 0 <= value <= 255 for value in rgb_raw)
            ):
                raise HachurePrototypeError(f"{identifier} has an invalid footprint RGB")
            color = tuple(rgb_raw)
            if color != tuple(shape.get("rgb", ())):
                raise HachurePrototypeError(f"{identifier} G2/G3 footprint RGB mismatch")
            groups = _normalize_groups(source.get("groups"), identifier)
            seed = groups[0][0][0]
            if color not in color_masks:
                color_masks[color] = _exact_color_mask(guide, color)
            component = _isolate_component(color_masks[color], seed)
            for group in groups:
                for segment in group:
                    if any(component.getpixel(point) == 0 for point in segment):
                        component.close()
                        raise HachurePrototypeError(
                            f"G3 segment for {identifier} escapes its G2 footprint"
                        )
            expected_group_count = 2 if source.get("role") == "main-massif" else 1
            if len(groups) != expected_group_count:
                component.close()
                raise HachurePrototypeError(
                    f"{identifier} requires {expected_group_count} direction groups"
                )
            saddle = _organic_saddle_mask(
                source.get("saddle_clear_box"), component, width=20
            )
            landforms.append(
                Landform(
                    identifier=identifier,
                    role=str(source.get("role")),
                    mask=component,
                    saddle_mask=saddle,
                    groups=groups,
                    group_centers=tuple(_group_center(group) for group in groups),
                    center=_mask_center(component),
                    area_pixels=_count_selected(component),
                )
            )
            merged = ImageChops.lighter(permission, component)
            permission.close()
            permission = merged

        overlap_sum = sum(landform.area_pixels for landform in landforms)
        permission_pixels = _count_selected(permission)
        if overlap_sum != permission_pixels or permission_pixels != 227663:
            raise HachurePrototypeError(
                "six G2 components must be disjoint and retain 227663 permission pixels"
            )
        roles = [landform.role for landform in landforms]
        if roles.count("main-massif") != 2 or len(roles) - roles.count("main-massif") != 4:
            raise HachurePrototypeError("H1 requires two main massifs and four foothills")
        if sum(bool(landform.saddle_mask.getbbox()) for landform in landforms) != 2:
            raise HachurePrototypeError("H1 requires two nonempty saddle masks")

        source_metrics = {
            "landform_count": len(landforms),
            "main_massif_count": roles.count("main-massif"),
            "foothill_count": len(roles) - roles.count("main-massif"),
            "open_saddle_count": sum(
                bool(landform.saddle_mask.getbbox()) for landform in landforms
            ),
            "permission_pixels": permission_pixels,
            "g3_segment_count": sum(
                len(group) for landform in landforms for group in landform.groups
            ),
        }
        return Inputs(base, permission, tuple(landforms), source_metrics)
    except Exception:
        base.close()
        permission.close()
        for landform in landforms:
            landform.close()
        raise
    finally:
        guide.close()
        skeleton_raster.close()
        for mask in color_masks.values():
            mask.close()


def _stable_bytes(*values: object) -> bytes:
    payload = "|".join(str(value) for value in values).encode("utf-8")
    return hashlib.sha256(payload).digest()


def _spacing_and_density(variant: Variant, landform: Landform) -> tuple[int, float]:
    if landform.role == "main-massif":
        return variant.main_spacing_px, variant.main_density
    return variant.foothill_spacing_px, variant.foothill_density


def _length_bounds(variant: Variant, landform: Landform) -> tuple[int, int]:
    if landform.role == "main-massif":
        return variant.main_length_px
    return variant.foothill_length_px


def _cosine_to_radial(
    angle: float,
    point: tuple[float, float],
    center: tuple[float, float],
) -> float:
    radial_x = point[0] - center[0]
    radial_y = point[1] - center[1]
    radial_length = math.hypot(radial_x, radial_y)
    if radial_length < 1:
        return 0.0
    return abs(
        (math.cos(angle) * radial_x + math.sin(angle) * radial_y) / radial_length
    )


def _nonconvergent_angle(
    source_angle: float,
    jitter: float,
    point: tuple[float, float],
    centers: Iterable[tuple[float, float]],
) -> tuple[float, float]:
    offsets = (
        0.0,
        17.0,
        -19.0,
        37.0,
        -41.0,
        59.0,
        -61.0,
        79.0,
        -83.0,
        101.0,
        -103.0,
        127.0,
    )
    candidates: list[tuple[float, int, float]] = []
    for index, offset in enumerate(offsets):
        angle = source_angle + jitter + math.radians(offset)
        alignments = tuple(
            _cosine_to_radial(angle, point, center) for center in centers
        )
        safe_band_penalty = sum(
            max(0.0, 0.20 - alignment) ** 2
            + max(0.0, alignment - 0.84) ** 2
            for alignment in alignments
        )
        candidates.append((safe_band_penalty, index, angle))
    selected = min(candidates)
    angle = selected[2]
    radial_score = max(
        _cosine_to_radial(angle, point, center) for center in centers
    )
    return radial_score, angle


def _render_landform_hachures(
    landform: Landform,
    variant: Variant,
) -> tuple[Image.Image, dict[str, Any]]:
    layer = Image.new("L", CANVAS, 0)
    bounds = landform.mask.getbbox()
    if bounds is None:
        layer.close()
        raise HachurePrototypeError(f"empty mask for {landform.identifier}")
    spacing, density = _spacing_and_density(variant, landform)
    minimum_length, maximum_length = _length_bounds(variant, landform)
    offset = _stable_bytes(variant.slug, landform.identifier, "grid-offset")
    offset_x = offset[0] % spacing
    offset_y = offset[1] % spacing
    draw = ImageDraw.Draw(layer)
    declared: list[dict[str, Any]] = []
    orientation_bins: set[int] = set()
    lengths: set[int] = set()
    endpoint_buckets: dict[tuple[int, int], int] = {}
    radial_failures = 0
    tangential_alignments = 0

    for grid_y in range(bounds[1] + offset_y, bounds[3], spacing):
        for grid_x in range(bounds[0] + offset_x, bounds[2], spacing):
            noise = _stable_bytes(variant.slug, landform.identifier, grid_x, grid_y)
            jitter_radius = max(1, round(spacing * 0.36))
            x = grid_x + (noise[0] % (2 * jitter_radius + 1)) - jitter_radius
            y = grid_y + (noise[1] % (2 * jitter_radius + 1)) - jitter_radius
            if not 0 <= x < CANVAS[0] or not 0 <= y < CANVAS[1]:
                continue
            if landform.mask.getpixel((x, y)) == 0 or landform.saddle_mask.getpixel((x, y)):
                continue
            if noise[2] / 255 > density:
                continue

            group_index = min(
                range(len(landform.group_centers)),
                key=lambda index: (
                    (x - landform.group_centers[index][0]) ** 2
                    + (y - landform.group_centers[index][1]) ** 2
                ),
            )
            group = landform.groups[group_index]
            source = group[noise[3] % len(group)]
            source_angle = math.atan2(
                source[-1][1] - source[0][1], source[-1][0] - source[0][0]
            )
            jitter_degrees = (
                (noise[4] / 255) * 2 - 1
            ) * variant.angle_jitter_degrees
            radial_score, angle = _nonconvergent_angle(
                source_angle,
                math.radians(jitter_degrees),
                (x, y),
                (landform.center, landform.group_centers[group_index]),
            )
            if radial_score >= 0.9:
                radial_failures += 1
            group_alignment = _cosine_to_radial(
                angle, (x, y), landform.group_centers[group_index]
            )
            if group_alignment <= 0.12:
                tangential_alignments += 1
            length = minimum_length + noise[5] % (maximum_length - minimum_length + 1)
            half_length = length / 2
            endpoint_a = (
                round(x - math.cos(angle) * half_length),
                round(y - math.sin(angle) * half_length),
            )
            endpoint_b = (
                round(x + math.cos(angle) * half_length),
                round(y + math.sin(angle) * half_length),
            )
            draw.line(
                (endpoint_a, endpoint_b),
                fill=255,
                width=variant.stroke_width_px,
            )
            orientation_bins.add(int((math.degrees(angle) % 180) // 15))
            lengths.add(round(math.hypot(endpoint_b[0] - endpoint_a[0], endpoint_b[1] - endpoint_a[1])))
            for endpoint in (endpoint_a, endpoint_b):
                bucket = endpoint[0] // 8, endpoint[1] // 8
                endpoint_buckets[bucket] = endpoint_buckets.get(bucket, 0) + 1
            declared.append(
                {
                    "center": [x, y],
                    "endpoints": [list(endpoint_a), list(endpoint_b)],
                    "group_index": group_index,
                    "length_px": length,
                    "orientation_degrees": round(math.degrees(angle) % 180, 3),
                    "radial_alignment": round(radial_score, 6),
                }
            )

    clipped_to_footprint = ImageChops.darker(layer, landform.mask)
    not_saddle = ImageChops.invert(landform.saddle_mask)
    clipped: Image.Image | None = None
    try:
        clipped = ImageChops.darker(clipped_to_footprint, not_saddle)
        ink_pixels = _count_selected(clipped)
        if not declared or ink_pixels == 0:
            raise HachurePrototypeError(f"no H1 hachures rendered for {landform.identifier}")
        metrics = {
            "id": landform.identifier,
            "role": landform.role,
            "footprint_pixels": landform.area_pixels,
            "declared_stroke_count": len(declared),
            "ink_pixels_before_protection": ink_pixels,
            "minimum_declared_length_px": min(entry["length_px"] for entry in declared),
            "maximum_declared_length_px": max(entry["length_px"] for entry in declared),
            "unique_rendered_lengths": len(lengths),
            "orientation_bins_15_degrees": len(orientation_bins),
            "radial_convergence_failure_count": radial_failures,
            "tangential_alignment_fraction": round(
                tangential_alignments / len(declared), 6
            ),
            "maximum_radial_alignment": max(entry["radial_alignment"] for entry in declared),
            "maximum_endpoints_per_8px_bucket": max(endpoint_buckets.values(), default=0),
            "saddle_hachure_pixels_before_protection": _count_intersection(
                clipped, landform.saddle_mask
            ),
        }
        return clipped.copy(), metrics
    finally:
        layer.close()
        clipped_to_footprint.close()
        not_saddle.close()
        if clipped is not None:
            clipped.close()


def _feather_inside(binary: Image.Image, radius: float) -> Image.Image:
    softened = binary.filter(ImageFilter.GaussianBlur(radius=radius))
    try:
        return ImageChops.darker(binary, softened)
    finally:
        softened.close()


def _draw_road_core(width: int) -> Image.Image:
    core = Image.new("L", CANVAS, 0)
    draw = ImageDraw.Draw(core)
    radius = width // 2
    for _, points in ROAD_STROKES:
        draw.line(points, fill=255, width=width, joint="curve")
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    return core


def _protected_strength(core: Image.Image, feather: float) -> Image.Image:
    softened = core.filter(ImageFilter.GaussianBlur(radius=feather))
    try:
        return ImageChops.lighter(core, softened)
    finally:
        softened.close()


def detail_core(
    base: Image.Image,
    *,
    gaussian_radius_px: float = 3.0,
    high_frequency_threshold_levels: int = 18,
    dark_luminance_max: int = 105,
) -> Image.Image:
    """Return the strict high-frequency AND dark structural-detail mask."""

    luminance = base.convert("L")
    blurred = luminance.filter(ImageFilter.GaussianBlur(radius=gaussian_radius_px))
    difference = ImageChops.difference(luminance, blurred)
    high_frequency = difference.point(
        lambda value: 255 if value >= high_frequency_threshold_levels else 0
    )
    dark = luminance.point(lambda value: 255 if value <= dark_luminance_max else 0)
    try:
        return ImageChops.darker(high_frequency, dark)
    finally:
        luminance.close()
        blurred.close()
        difference.close()
        high_frequency.close()
        dark.close()


def _subtract_protection(mask: Image.Image, protection: Image.Image) -> Image.Image:
    inverse = ImageChops.invert(protection)
    try:
        return ImageChops.darker(mask, inverse)
    finally:
        inverse.close()


def _scale_mask(mask: Image.Image, maximum: int) -> Image.Image:
    return mask.point(lambda value: round(value * maximum / 255))


def _main_rise_support(landforms: Sequence[Landform]) -> Image.Image:
    """Build two broad, non-directional density lobes for each main massif."""

    union = Image.new("L", CANVAS, 0)
    for landform in landforms:
        if landform.role != "main-massif":
            continue
        bounds = landform.mask.getbbox()
        if bounds is None or len(landform.group_centers) != 2:
            union.close()
            raise HachurePrototypeError(
                f"{landform.identifier} requires two main-rise centers"
            )
        radius_x = max(62, min(108, round((bounds[2] - bounds[0]) / 4.6)))
        radius_y = max(48, min(84, round((bounds[3] - bounds[1]) * 0.29)))
        lobes = Image.new("L", CANVAS, 0)
        draw = ImageDraw.Draw(lobes)
        for center_x, center_y in landform.group_centers:
            draw.ellipse(
                (
                    round(center_x - radius_x),
                    round(center_y - radius_y),
                    round(center_x + radius_x),
                    round(center_y + radius_y),
                ),
                fill=255,
            )
        softened = lobes.filter(ImageFilter.GaussianBlur(radius=26))
        clipped_to_footprint = ImageChops.darker(softened, landform.mask)
        without_saddle = _subtract_protection(
            clipped_to_footprint, landform.saddle_mask
        )
        merged = ImageChops.lighter(union, without_saddle)
        union.close()
        union = merged
        lobes.close()
        softened.close()
        clipped_to_footprint.close()
        without_saddle.close()
    return union


def _difference_max(left: Image.Image, right: Image.Image) -> Image.Image:
    difference = ImageChops.difference(left, right)
    channels = difference.split()
    first_pair: Image.Image | None = None
    maximum: Image.Image | None = None
    try:
        first_pair = ImageChops.lighter(channels[0], channels[1])
        maximum = ImageChops.lighter(first_pair, channels[2])
        return maximum.copy()
    finally:
        difference.close()
        for channel in channels:
            channel.close()
        if first_pair is not None:
            first_pair.close()
        if maximum is not None:
            maximum.close()


def _count_intersection(left: Image.Image, right: Image.Image) -> int:
    intersection = ImageChops.darker(left, right)
    try:
        return _count_selected(intersection)
    finally:
        intersection.close()


def _masked_max(values: Image.Image, mask: Image.Image) -> int:
    selected = ImageChops.darker(values, mask)
    try:
        return selected.getextrema()[1]
    finally:
        selected.close()


def _masked_mean(values: Image.Image, mask: Image.Image) -> float:
    selected = ImageChops.darker(values, mask)
    try:
        histogram = selected.histogram()
        selected_pixels = _count_selected(mask)
        if selected_pixels == 0:
            return 0.0
        return sum(level * count for level, count in enumerate(histogram)) / selected_pixels
    finally:
        selected.close()


def _partial_pixel_count(mask: Image.Image) -> int:
    histogram = mask.histogram()
    return sum(histogram[1:255])


def _render_variant(inputs: Inputs, variant: Variant) -> tuple[Image.Image, dict[str, Any]]:
    permission_soft = _feather_inside(inputs.permission, variant.boundary_feather_px)
    road_core = _draw_road_core(variant.road_core_width_px)
    road_strength = _protected_strength(road_core, variant.road_feather_px)
    details = detail_core(inputs.base)
    hachure_union = Image.new("L", CANVAS, 0)
    rise_support = _main_rise_support(inputs.landforms)
    landform_hachures: dict[str, Image.Image] = {}
    landform_metrics: list[dict[str, Any]] = []
    line_allowed: Image.Image | None = None
    wash_allowed: Image.Image | None = None
    line_strength: Image.Image | None = None
    wash_strength: Image.Image | None = None
    rise_allowed: Image.Image | None = None
    rise_strength: Image.Image | None = None
    edit_strength: Image.Image | None = None
    delta_rgb: Image.Image | None = None
    output: Image.Image | None = None
    difference_max: Image.Image | None = None
    try:
        for landform in inputs.landforms:
            hachure, metrics = _render_landform_hachures(landform, variant)
            landform_hachures[landform.identifier] = hachure
            landform_metrics.append(metrics)
            merged = ImageChops.lighter(hachure_union, hachure)
            hachure_union.close()
            hachure_union = merged

        line_allowed = ImageChops.multiply(hachure_union, permission_soft)
        protected_line = _subtract_protection(line_allowed, road_strength)
        line_allowed.close()
        line_allowed = _subtract_protection(protected_line, details)
        protected_line.close()

        wash_allowed = _subtract_protection(permission_soft, road_strength)
        protected_wash = _subtract_protection(wash_allowed, details)
        wash_allowed.close()
        wash_allowed = protected_wash

        rise_allowed = ImageChops.multiply(rise_support, permission_soft)
        protected_rise = _subtract_protection(rise_allowed, road_strength)
        rise_allowed.close()
        rise_allowed = _subtract_protection(protected_rise, details)
        protected_rise.close()

        line_strength = _scale_mask(line_allowed, variant.stroke_delta_levels)
        wash_strength = _scale_mask(wash_allowed, variant.wash_delta_levels)
        rise_strength = _scale_mask(
            rise_allowed, variant.main_rise_wash_delta_levels
        )
        line_and_wash = ImageChops.add(line_strength, wash_strength)
        try:
            edit_strength = ImageChops.add(line_and_wash, rise_strength)
        finally:
            line_and_wash.close()
        delta_rgb = Image.merge(
            "RGB",
            (
                edit_strength.point(lambda value: round(value * 0.72)),
                edit_strength.point(lambda value: round(value * 0.84)),
                edit_strength.copy(),
            ),
        )
        output = ImageChops.subtract(inputs.base, delta_rgb)
        difference_max = _difference_max(inputs.base, output)
        changed = difference_max.point(lambda value: 255 if value else 0)
        strong_threshold = max(6, variant.stroke_delta_levels // 3)
        strong = difference_max.point(
            lambda value: 255 if value >= strong_threshold else 0
        )
        outside = ImageChops.invert(inputs.permission)
        brightening = ImageChops.subtract(output, inputs.base)
        brightening_max = _difference_max(Image.new("RGB", CANVAS, (0, 0, 0)), brightening)
        try:
            for landform, metrics in zip(inputs.landforms, landform_metrics):
                protected_hachure = ImageChops.darker(
                    line_allowed, landform_hachures[landform.identifier]
                )
                try:
                    metrics.update(
                        {
                            "visible_hachure_pixels": _count_selected(protected_hachure),
                            "visible_hachure_fraction": round(
                                _count_selected(protected_hachure) / landform.area_pixels,
                                6,
                            ),
                            "changed_pixels": _count_intersection(changed, landform.mask),
                            "strong_changed_pixels": _count_intersection(
                                strong, landform.mask
                            ),
                            "mean_max_channel_difference": round(
                                _masked_mean(difference_max, landform.mask), 6
                            ),
                            "saddle_hachure_pixels_after_protection": _count_intersection(
                                protected_hachure, landform.saddle_mask
                            ),
                        }
                    )
                finally:
                    protected_hachure.close()

            gates = {
                "outside_g2_permission": {
                    "changed_pixels": _count_intersection(changed, outside),
                    "maximum_channel_difference": _masked_max(difference_max, outside),
                },
                "road_core": {
                    "changed_pixels": _count_intersection(changed, road_core),
                    "maximum_channel_difference": _masked_max(difference_max, road_core),
                },
                "detail_core": {
                    "selection_operator": "high-frequency-and-dark",
                    "protected_pixels": _count_selected(details),
                    "changed_pixels": _count_intersection(changed, details),
                    "maximum_channel_difference": _masked_max(difference_max, details),
                },
                "non_lighting": {
                    "brightened_pixels": _count_selected(brightening_max),
                    "maximum_channel_increase": brightening_max.getextrema()[1],
                },
                "boundary_feather": {
                    "partial_alpha_pixels": _partial_pixel_count(permission_soft),
                    "radius_px": variant.boundary_feather_px,
                },
            }
            minimum_visible = {
                "main-massif": 900,
                "foothill-a": 250,
                "foothill-b": 250,
            }
            immediate_failures: list[str] = []
            for gate, values in gates.items():
                if gate in {"outside_g2_permission", "road_core", "detail_core"}:
                    if values["changed_pixels"] or values["maximum_channel_difference"]:
                        immediate_failures.append(gate)
                elif gate == "non_lighting":
                    if values["brightened_pixels"] or values["maximum_channel_increase"]:
                        immediate_failures.append(gate)
                elif values["partial_alpha_pixels"] == 0:
                    immediate_failures.append(gate)
            for metrics in landform_metrics:
                if metrics["visible_hachure_pixels"] < minimum_visible[metrics["role"]]:
                    immediate_failures.append(f"{metrics['id']}:insufficient-hachure")
                if metrics["orientation_bins_15_degrees"] < 6:
                    immediate_failures.append(f"{metrics['id']}:orientation-repetition")
                if metrics["radial_convergence_failure_count"]:
                    immediate_failures.append(f"{metrics['id']}:radial-convergence")
                if metrics["tangential_alignment_fraction"] > 0.20:
                    immediate_failures.append(f"{metrics['id']}:contour-alignment")
                if metrics["maximum_endpoints_per_8px_bucket"] > 4:
                    immediate_failures.append(f"{metrics['id']}:endpoint-convergence")
                if metrics["saddle_hachure_pixels_after_protection"]:
                    immediate_failures.append(f"{metrics['id']}:closed-saddle")
            report = {
                "slug": variant.slug,
                "status": "passed" if not immediate_failures else "failed",
                "description": variant.description,
                "parameters": asdict(variant),
                "metrics": {
                    "changed_pixels": _count_selected(changed),
                    "strong_changed_pixels": _count_selected(strong),
                    "maximum_channel_difference": difference_max.getextrema()[1],
                    "editable_pixels": _count_selected(edit_strength),
                    "opaque_editable_pixels": edit_strength.histogram()[255],
                    "road_core_pixels": _count_selected(road_core),
                    "detail_core_pixels": _count_selected(details),
                    "hachure_pixels_before_protection": _count_selected(hachure_union),
                    "hachure_pixels_after_protection": _count_selected(line_allowed),
                    "main_rise_support_pixels_before_protection": _count_selected(
                        rise_support
                    ),
                    "main_rise_support_pixels_after_protection": _count_selected(
                        rise_allowed
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
        hachure_union.close()
        rise_support.close()
        for hachure in landform_hachures.values():
            hachure.close()
        for image in (
            line_allowed,
            wash_allowed,
            line_strength,
            wash_strength,
            rise_allowed,
            rise_strength,
            edit_strength,
            delta_rgb,
            output,
            difference_max,
        ):
            if image is not None:
                image.close()


def _save_png(image: Image.Image, path: Path) -> None:
    image.save(path, format="PNG", optimize=False, compress_level=9)


def _labeled_panel(image: Image.Image, label: str, size: tuple[int, int]) -> Image.Image:
    panel = image.resize(size, Image.Resampling.LANCZOS).convert("RGB")
    draw = ImageDraw.Draw(panel)
    draw.rectangle((0, 0, min(size[0], 310), 24), fill=(26, 24, 21))
    draw.text((8, 7), label, fill=(244, 239, 222))
    return panel


def _contact_sheet(base: Image.Image, variants: Sequence[tuple[str, Image.Image]]) -> Image.Image:
    entries = [("D4 locked base", base), *variants]
    panel_size = (768, 512)
    sheet = Image.new("RGB", (panel_size[0] * 2, panel_size[1] * 2), (30, 28, 25))
    panels: list[Image.Image] = []
    try:
        for index, (label, image) in enumerate(entries):
            panel = _labeled_panel(image, label, panel_size)
            panels.append(panel)
            sheet.paste(panel, ((index % 2) * panel_size[0], (index // 2) * panel_size[1]))
        return sheet
    finally:
        for panel in panels:
            panel.close()


def _crop_comparison(
    base: Image.Image,
    variants: Sequence[tuple[str, Image.Image]],
    crop_box: tuple[int, int, int, int],
    panel_width: int,
) -> Image.Image:
    entries = [("D4", base), *variants]
    crop_width = crop_box[2] - crop_box[0]
    crop_height = crop_box[3] - crop_box[1]
    panel_height = round(crop_height * panel_width / crop_width)
    sheet = Image.new("RGB", (panel_width * len(entries), panel_height), (30, 28, 25))
    crops: list[Image.Image] = []
    panels: list[Image.Image] = []
    try:
        for index, (label, image) in enumerate(entries):
            crop = image.crop(crop_box)
            crops.append(crop)
            panel = _labeled_panel(crop, label, (panel_width, panel_height))
            panels.append(panel)
            sheet.paste(panel, (index * panel_width, 0))
        return sheet
    finally:
        for crop in crops:
            crop.close()
        for panel in panels:
            panel.close()


def _expected_outputs(output_dir: Path, slugs: Sequence[str]) -> tuple[Path, ...]:
    return (
        *(output_dir / f"h1-{slug}.png" for slug in slugs),
        output_dir / "comparison-full.png",
        output_dir / "comparison-north-east.png",
        output_dir / "comparison-south-east.png",
        output_dir / "report.json",
    )


def render_all(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    variants: Sequence[Variant] = VARIANTS,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    if not variants or len(variants) > 3:
        raise HachurePrototypeError("render one to three H1 variants")
    slugs = [variant.slug for variant in variants]
    if len(set(slugs)) != len(slugs):
        raise HachurePrototypeError("H1 variant slugs must be unique")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_outputs = _expected_outputs(output_dir, slugs)
    existing = [path for path in expected_outputs if path.exists()]
    if existing and not replace:
        raise HachurePrototypeError(
            "refusing to overwrite diagnostic output without --replace: "
            + ", ".join(_display_path(path) for path in existing)
        )

    inputs = load_inputs()
    rendered: list[tuple[str, Image.Image]] = []
    reports: list[dict[str, Any]] = []
    comparisons: list[Image.Image] = []
    try:
        for variant in variants:
            image, report = _render_variant(inputs, variant)
            output_path = output_dir / f"h1-{variant.slug}.png"
            _save_png(image, output_path)
            report["output_path"] = _display_path(output_path)
            report["output_sha256"] = _sha256(output_path)
            rendered.append((variant.slug, image))
            reports.append(report)

        full = _contact_sheet(inputs.base, rendered)
        north_east = _crop_comparison(
            inputs.base, rendered, (740, 48, 1536, 570), panel_width=560
        )
        south_east = _crop_comparison(
            inputs.base, rendered, (650, 688, 1536, 1024), panel_width=620
        )
        comparisons.extend((full, north_east, south_east))
        comparison_paths = (
            output_dir / "comparison-full.png",
            output_dir / "comparison-north-east.png",
            output_dir / "comparison-south-east.png",
        )
        for image, path in zip(comparisons, comparison_paths):
            _save_png(image, path)

        status = "passed" if all(report["status"] == "passed" for report in reports) else "failed"
        result = {
            "schema_version": "1.0.0",
            "id": "candidate-h1-deterministic-hachure-prototype",
            "status": status,
            "purpose": (
                "Diagnostic comparison only; no manifest or production candidate is modified."
            ),
            "inputs": {
                "base": {"path": _display_path(BASE_PATH), "sha256": LOCKED_SHA256["base"]},
                "g2_source": {
                    "path": _display_path(G2_SOURCE_PATH),
                    "sha256": LOCKED_SHA256["g2_source"],
                },
                "g2_raster": {
                    "path": _display_path(G2_RASTER_PATH),
                    "sha256": LOCKED_SHA256["g2_raster"],
                },
                "g3_source": {
                    "path": _display_path(G3_SOURCE_PATH),
                    "sha256": LOCKED_SHA256["g3_source"],
                },
                "g3_raster": {
                    "path": _display_path(G3_RASTER_PATH),
                    "sha256": LOCKED_SHA256["g3_raster"],
                },
            },
            "source_metrics": inputs.source_metrics,
            "global_contract": {
                "permission": "exact G2 six-component footprint only",
                "direction_source": "G3 segment orientation ensembles",
                "detail_selection_operator": "high-frequency-and-dark",
                "detail_gaussian_radius_px": 3,
                "detail_high_frequency_threshold_levels": 18,
                "detail_dark_luminance_max": 105,
                "road_core_width_px": 16,
                "render_operation": "subtractive-only non-lighting RGB delta",
                "maximum_variant_count": 3,
            },
            "variants": reports,
            "comparisons": [
                {"path": _display_path(path), "sha256": _sha256(path)}
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
        for _, image in rendered:
            image.close()
        for image in comparisons:
            image.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--variant",
        action="append",
        choices=tuple(VARIANT_BY_SLUG),
        help="Render only this variant; repeat up to three times.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace only the named H1 diagnostic files in the output directory.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    variants = (
        tuple(VARIANT_BY_SLUG[slug] for slug in args.variant)
        if args.variant
        else VARIANTS
    )
    try:
        result = render_all(args.output_dir, variants, replace=args.replace)
    except Exception as error:
        print(f"H1 deterministic hachure prototype failed: {error}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
