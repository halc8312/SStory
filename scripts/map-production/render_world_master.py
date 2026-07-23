#!/usr/bin/env python3
"""Render the canonical EA-WORLD-1 generation-control master.

The renderer deliberately contains no font or text drawing path.  Canonical
GeoJSON is transformed directly from the 0..10000 EA-WORLD-1 extent into the
requested raster size; seeded decoration is clipped to those source shapes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
except ImportError as exc:  # pragma: no cover - exercised by the CLI environment
    raise RuntimeError("Pillow is required: py -m pip install Pillow") from exc


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DIR = REPO_ROOT / "world" / "map-production" / "source"
DEFAULT_OUTPUT = (
    REPO_ROOT / "world" / "map-production" / "controls" / "world-control-v1.png"
)
GENERATOR_ID = "sstory-map-production/render_world_master.py@1"
DEFAULT_WIDTH = 8192
DEFAULT_HEIGHT = 5460
DEFAULT_SEED = 0xEA20260719
WORLD_BOUNDS = (0.0, 0.0, 10000.0, 10000.0)

SOURCE_FILES = {
    "landmasses": "landmasses.geojson",
    "regions": "regions.geojson",
    "terrain": "terrain.geojson",
    "hydrography": "hydrography.geojson",
    "transport": "transport-geometries.geojson",
    "settlements": "settlement-footprints.geojson",
}

PALETTE = {
    "ocean": "#536f70",
    "ocean_deep": "#435e62",
    "ocean_ink": "#314c50",
    "water_highlight": "#8da7a0",
    "land": "#b7a56f",
    "land_light": "#c7b982",
    "parchment": "#c9b77b",
    "forest": "#667044",
    "forest_dark": "#404b32",
    "mountain": "#777367",
    "mountain_dark": "#4a4842",
    "desert": "#bd9860",
    "volcanic": "#765b47",
    "tundra": "#b9baa6",
    "river": "#486d75",
    "river_highlight": "#91aaa5",
    "road": "#745536",
    "road_light": "#d2bd80",
    "settlement": "#8b633d",
    "settlement_dark": "#4a382b",
    "ink": "#3f3c32",
}


class RenderError(ValueError):
    """Raised when canonical source or output safety checks fail."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_seed(seed: int, *parts: str) -> int:
    payload = "\0".join((str(seed), *parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _strict_json_constant(value: str) -> None:
    raise RenderError(f"non-standard numeric constant in source JSON: {value}")


def load_sources(source_dir: Path) -> dict[str, dict[str, Any]]:
    source_dir = source_dir.resolve()
    loaded: dict[str, dict[str, Any]] = {}
    for key, filename in SOURCE_FILES.items():
        path = source_dir / filename
        if not path.is_file():
            raise RenderError(f"required canonical source does not exist: {path}")
        try:
            value = json.loads(
                path.read_text(encoding="utf-8"), parse_constant=_strict_json_constant
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise RenderError(f"could not read canonical source {path}: {exc}") from exc
        if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
            raise RenderError(f"{path} must be a GeoJSON FeatureCollection")
        if value.get("coordinate_reference_system") != "EA-WORLD-1":
            raise RenderError(f"{path} must use coordinate_reference_system EA-WORLD-1")
        features = value.get("features")
        if not isinstance(features, list):
            raise RenderError(f"{path} features must be an array")
        ids = [feature_id(feature) for feature in features]
        if len(ids) != len(set(ids)):
            raise RenderError(f"{path} contains duplicate feature ids")
        loaded[key] = value

    required_counts = {"landmasses": 5, "regions": 14, "transport": 33}
    for key, expected in required_counts.items():
        actual = len(loaded[key]["features"])
        if actual != expected:
            raise RenderError(
                f"{SOURCE_FILES[key]} must contain {expected} canonical features, got {actual}"
            )
    return loaded


def feature_id(feature: dict[str, Any]) -> str:
    properties = feature.get("properties")
    value = feature.get("id")
    if value is None and isinstance(properties, dict):
        value = properties.get("id")
    if not isinstance(value, str) or not value:
        raise RenderError("every source feature must have a non-empty string id")
    return value


class CanvasTransform:
    """Direct EA-WORLD-1 -> raster transform; it never modifies source points."""

    def __init__(self, width: int, height: int) -> None:
        if width < 256 or height < 256:
            raise RenderError("width and height must each be at least 256 pixels")
        if width > 32768 or height > 32768:
            raise RenderError("width and height must not exceed 32768 pixels")
        self.width = width
        self.height = height
        self.scale_x = (width - 1) / 10000.0
        self.scale_y = (height - 1) / 10000.0
        self.detail_scale = min(width / DEFAULT_WIDTH, height / DEFAULT_HEIGHT)

    def point(self, coordinate: Sequence[float]) -> tuple[int, int]:
        if len(coordinate) < 2:
            raise RenderError("coordinate must have at least two ordinates")
        x, y = float(coordinate[0]), float(coordinate[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise RenderError("coordinates must be finite")
        if not 0 <= x <= 10000 or not 0 <= y <= 10000:
            raise RenderError(f"coordinate {[x, y]} is outside EA-WORLD-1 bounds")
        # Divide first so canonical midpoint coordinates land exactly on the
        # mathematical half-pixel instead of drifting through a pre-rounded
        # binary scale factor.
        return (
            round((x / 10000.0) * (self.width - 1)),
            round((y / 10000.0) * (self.height - 1)),
        )

    def width_px(self, canonical_width: float, minimum: int = 1) -> int:
        mean_scale = (self.scale_x + self.scale_y) / 2
        return max(minimum, round(canonical_width * mean_scale))

    def design_px(self, full_size_pixels: float, minimum: int = 1) -> int:
        return max(minimum, round(full_size_pixels * self.detail_scale))


def polygon_rings(
    geometry: dict[str, Any], transform: CanvasTransform
) -> Iterator[list[list[tuple[int, int]]]]:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Polygon":
        polygons = [coordinates]
    elif kind == "MultiPolygon":
        polygons = coordinates
    else:
        return
    if not isinstance(polygons, list):
        raise RenderError(f"invalid {kind} coordinates")
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise RenderError(f"invalid {kind} polygon")
        yield [[transform.point(point) for point in ring] for ring in polygon]


def line_paths(
    geometry: dict[str, Any], transform: CanvasTransform
) -> Iterator[list[tuple[int, int]]]:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "LineString":
        lines = [coordinates]
    elif kind == "MultiLineString":
        lines = coordinates
    else:
        return
    if not isinstance(lines, list):
        raise RenderError(f"invalid {kind} coordinates")
    for line in lines:
        if not isinstance(line, list) or len(line) < 2:
            raise RenderError(f"invalid {kind} line")
        yield [transform.point(point) for point in line]


def feature_mask(
    size: tuple[int, int], feature: dict[str, Any], transform: CanvasTransform
) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for rings in polygon_rings(feature.get("geometry", {}), transform):
        draw.polygon(rings[0], fill=255)
        for hole in rings[1:]:
            draw.polygon(hole, fill=0)
    return mask


def collection_mask(
    size: tuple[int, int], features: Iterable[dict[str, Any]], transform: CanvasTransform
) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for feature in features:
        for rings in polygon_rings(feature.get("geometry", {}), transform):
            draw.polygon(rings[0], fill=255)
            for hole in rings[1:]:
                draw.polygon(hole, fill=0)
    return mask


def apply_color(image: Image.Image, color: str, mask: Image.Image, alpha: int = 255) -> None:
    if alpha < 255:
        mask = mask.point(lambda value: value * alpha // 255)
    image.paste(color, (0, 0, image.width, image.height), mask)


def intersect_masks(first: Image.Image, second: Image.Image) -> Image.Image:
    return ImageChops.multiply(first, second)


def soften_inside_land(
    mask: Image.Image, land_mask: Image.Image, radius: int
) -> Image.Image:
    if radius <= 0:
        return intersect_masks(mask, land_mask)
    return intersect_masks(mask.filter(ImageFilter.GaussianBlur(radius=radius)), land_mask)


def _draw_polygon_outlines(
    draw: ImageDraw.ImageDraw,
    feature: dict[str, Any],
    transform: CanvasTransform,
    *,
    fill: str | tuple[int, int, int, int] | None = None,
    outline: str | tuple[int, int, int, int] | None = None,
    width: int = 1,
) -> None:
    for rings in polygon_rings(feature.get("geometry", {}), transform):
        draw.polygon(rings[0], fill=fill)
        if outline:
            draw.line(rings[0], fill=outline, width=width, joint="curve")
        for hole in rings[1:]:
            if outline:
                draw.line(hole, fill=outline, width=width, joint="curve")


def draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[int, int]],
    *,
    fill: str | tuple[int, int, int, int],
    width: int,
    dash: int,
    gap: int,
) -> None:
    if len(points) < 2:
        return
    phase = 0.0
    drawing = True
    remaining = float(dash)
    for start, end in zip(points, points[1:]):
        x1, y1 = start
        x2, y2 = end
        length = math.hypot(x2 - x1, y2 - y1)
        if length == 0:
            continue
        consumed = 0.0
        while consumed < length:
            step = min(remaining, length - consumed)
            next_consumed = consumed + step
            if drawing:
                a = consumed / length
                b = next_consumed / length
                segment = [
                    (round(x1 + (x2 - x1) * a), round(y1 + (y2 - y1) * a)),
                    (round(x1 + (x2 - x1) * b), round(y1 + (y2 - y1) * b)),
                ]
                draw.line(segment, fill=fill, width=width)
            consumed = next_consumed
            remaining -= step
            if remaining <= 1e-9:
                drawing = not drawing
                remaining = float(dash if drawing else gap)
        phase += length


def add_seeded_texture(image: Image.Image, seed: int, transform: CanvasTransform) -> None:
    """Add one canvas-wide non-tiled grain field and sparse paper fibres."""
    sample_width = max(64, image.width // 5)
    sample_height = max(64, image.height // 5)
    rng = random.Random(stable_seed(seed, "canvas-grain"))
    raw = rng.randbytes(sample_width * sample_height)
    noise = Image.frombytes("L", (sample_width, sample_height), raw)
    noise = noise.filter(ImageFilter.GaussianBlur(radius=0.65))
    noise = noise.resize(image.size, Image.Resampling.BICUBIC)
    texture = ImageOps.colorize(
        noise, black="#6a624f", white="#d8c994"
    ).convert(image.mode)
    image.paste(Image.blend(image, texture, 0.085))

    fibres = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(fibres)
    count = max(80, min(4800, image.width * image.height // 14000))
    line_width = transform.design_px(1)
    for _ in range(count):
        x = rng.randrange(image.width)
        y = rng.randrange(image.height)
        length = rng.randint(transform.design_px(8), transform.design_px(58))
        rise = rng.randint(-transform.design_px(2), transform.design_px(2))
        shade = (236, 218, 160, rng.randint(5, 13)) if rng.random() < 0.55 else (54, 51, 43, rng.randint(3, 9))
        draw.line((x, y, min(image.width - 1, x + length), y + rise), fill=shade, width=line_width)
    image.alpha_composite(fibres)


def draw_water(
    image: Image.Image,
    hydrography: list[dict[str, Any]],
    transform: CanvasTransform,
    seed: int,
) -> None:
    for feature in hydrography:
        water_type = feature.get("properties", {}).get("water_type")
        if water_type not in {"sea", "ocean"}:
            continue
        mask = feature_mask(image.size, feature, transform)
        color = PALETTE["ocean_deep"] if water_type == "ocean" else "#5c7773"
        # Named water polygons are canonical masks, not political regions.  A
        # very quiet wash distinguishes them without exposing low-vertex mask
        # edges at overview zooms.
        apply_color(image, color, mask, 24 if water_type == "ocean" else 18)

    # Fine wave marks are clipped to the inverse land mask later by the caller.
    rng = random.Random(stable_seed(seed, "ocean-wavelets"))
    waves = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(waves)
    count = max(180, min(5000, image.width * image.height // 10000))
    width = transform.design_px(1)
    for _ in range(count):
        x = rng.randrange(image.width)
        y = rng.randrange(image.height)
        length = rng.randint(transform.design_px(7), transform.design_px(30))
        bend = rng.choice((-1, 0, 1)) * transform.design_px(1)
        draw.line(
            [(x, y), (min(image.width - 1, x + length // 2), y + bend), (min(image.width - 1, x + length), y)],
            fill=(184, 194, 170, rng.randint(25, 60)),
            width=width,
        )
    image.alpha_composite(waves)


def draw_regions(
    image: Image.Image,
    features: list[dict[str, Any]],
    land_mask: Image.Image,
    transform: CanvasTransform,
) -> None:
    colors = {
        "capital_region": "#c4aa72",
        "agricultural_region": "#c4b77d",
        "mountain_region": "#878276",
        "forest_region": "#71754b",
        "coastal_region": "#a9a674",
        "floating_islands_region": "#8c9160",
        "desert_region": "#c09861",
        "oasis_region": "#7d8b55",
        "underwater_region": "#557b78",
        "special_region": "#8e7c72",
        "spirit_core_region": "#847a68",
        "region": "#b5a36d",
    }
    for feature in features:
        properties = feature.get("properties", {})
        mask = soften_inside_land(
            feature_mask(image.size, feature, transform),
            land_mask,
            transform.design_px(28),
        )
        # Region masks guide a gentle terrain wash only.  Deliberately omit
        # political-looking boundary strokes; labels/borders belong to vectors.
        apply_color(
            image,
            colors.get(properties.get("region_type"), PALETTE["land"]),
            mask,
            24,
        )


def draw_generic_land_detail(
    image: Image.Image,
    land_features: list[dict[str, Any]],
    transform: CanvasTransform,
    seed: int,
) -> None:
    """Add map-scale scrub, rock and grass marks without altering coast masks."""
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    total_target = max(180, min(7000, transform.design_px(5200)))
    per_feature = max(25, total_target // max(1, len(land_features)))
    for feature in land_features:
        rng = random.Random(stable_seed(seed, "land-detail", feature_id(feature)))
        mask = feature_mask(image.size, feature, transform)
        for x, y in _random_points_in_mask(mask, rng, per_feature):
            roll = rng.random()
            if roll < 0.48:
                radius = rng.randint(transform.design_px(1), transform.design_px(3))
                draw.ellipse(
                    (x - radius, y - radius // 2, x + radius, y + radius // 2),
                    fill=(65, 62, 46, rng.randint(45, 105)),
                )
            elif roll < 0.82:
                length = rng.randint(transform.design_px(2), transform.design_px(6))
                draw.line(
                    (x - length, y + transform.design_px(1), x, y - transform.design_px(2)),
                    fill=(67, 72, 44, rng.randint(55, 115)),
                    width=transform.design_px(1),
                )
                draw.line(
                    (x, y - transform.design_px(2), x + length, y + transform.design_px(1)),
                    fill=(67, 72, 44, rng.randint(55, 115)),
                    width=transform.design_px(1),
                )
            else:
                length = rng.randint(transform.design_px(3), transform.design_px(9))
                draw.line(
                    (x - length, y, x + length, y),
                    fill=(83, 71, 43, rng.randint(35, 80)),
                    width=transform.design_px(1),
                )
    image.alpha_composite(layer)


def _random_points_in_mask(
    mask: Image.Image, rng: random.Random, count: int
) -> Iterator[tuple[int, int]]:
    bbox = mask.getbbox()
    if bbox is None:
        return
    left, top, right, bottom = bbox
    accepted = 0
    attempts = 0
    maximum_attempts = max(100, count * 24)
    while accepted < count and attempts < maximum_attempts:
        x = rng.randrange(left, max(left + 1, right))
        y = rng.randrange(top, max(top + 1, bottom))
        attempts += 1
        if mask.getpixel((x, y)) >= 128:
            accepted += 1
            yield x, y


def _mask_density_count(mask: Image.Image, divisor: int, minimum: int, maximum: int) -> int:
    histogram = mask.histogram()
    approximate_area = sum(index * count for index, count in enumerate(histogram)) // 255
    return max(minimum, min(maximum, approximate_area // max(1, divisor)))


def _draw_tree(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, rng: random.Random) -> None:
    dark = PALETTE["forest_dark"]
    mid = PALETTE["forest"]
    draw.line((x, y, x, y + max(1, size // 2)), fill="#51452f", width=max(1, size // 5))
    jitter = rng.randint(-max(1, size // 5), max(1, size // 5))
    draw.ellipse((x - size, y - size + jitter, x + size, y + size), fill=mid, outline=dark, width=max(1, size // 5))
    draw.ellipse((x - size // 2, y - size, x + size // 2, y), fill="#7b7d4c")


def _draw_mountain(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, rng: random.Random) -> None:
    height = round(size * rng.uniform(1.2, 1.75))
    left = (x - size, y + size // 2)
    peak = (x + rng.randint(-max(1, size // 5), max(1, size // 5)), y - height)
    right = (x + size, y + size // 2)
    draw.polygon((left, peak, right), fill=PALETTE["mountain"], outline=PALETTE["mountain_dark"])
    draw.polygon(
        (peak, (x, y - height // 3), (x + size // 2, y + size // 2), right),
        fill="#5b5952",
    )
    snow = max(2, size // 3)
    draw.polygon(
        (peak, (peak[0] - snow, peak[1] + snow), (peak[0], peak[1] + snow // 2), (peak[0] + snow, peak[1] + snow)),
        fill="#b7ae8c",
    )


def _sample_polyline(points: Sequence[tuple[int, int]], spacing: int) -> Iterator[tuple[int, int]]:
    carry = 0.0
    for start, end in zip(points, points[1:]):
        x1, y1 = start
        x2, y2 = end
        length = math.hypot(x2 - x1, y2 - y1)
        if length == 0:
            continue
        distance = max(0.0, spacing - carry)
        while distance <= length:
            ratio = distance / length
            yield round(x1 + (x2 - x1) * ratio), round(y1 + (y2 - y1) * ratio)
            distance += spacing
        carry = (carry + length) % spacing


def draw_terrain(
    image: Image.Image,
    features: list[dict[str, Any]],
    land_mask: Image.Image,
    transform: CanvasTransform,
    seed: int,
) -> None:
    symbol_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(symbol_layer)
    for feature in features:
        feature_key = feature_id(feature)
        properties = feature.get("properties", {})
        terrain_type = properties.get("terrain_type", "")
        rng = random.Random(stable_seed(seed, "terrain", feature_key))
        geometry = feature.get("geometry", {})
        if geometry.get("type") in {"Polygon", "MultiPolygon"}:
            mask = soften_inside_land(
                feature_mask(image.size, feature, transform),
                land_mask,
                transform.design_px(22),
            )
            if "forest" in terrain_type:
                apply_color(image, PALETTE["forest"], mask, 105)
                count = _mask_density_count(
                    mask,
                    max(30, transform.design_px(1800)),
                    8,
                    max(30, transform.design_px(1900)),
                )
                for x, y in _random_points_in_mask(mask, rng, count):
                    _draw_tree(draw, x, y, rng.randint(transform.design_px(3), transform.design_px(8)), rng)
            elif terrain_type == "hot_desert":
                apply_color(image, PALETTE["desert"], mask, 150)
                count = _mask_density_count(mask, max(60, transform.design_px(5000)), 5, 900)
                for x, y in _random_points_in_mask(mask, rng, count):
                    radius = rng.randint(transform.design_px(5), transform.design_px(15))
                    draw.arc((x - radius, y - radius // 2, x + radius, y + radius // 2), 190, 345, fill=(100, 72, 43, 125), width=transform.design_px(1))
            elif terrain_type == "volcanic_land":
                apply_color(image, PALETTE["volcanic"], mask, 150)
                for x, y in _random_points_in_mask(mask, rng, _mask_density_count(mask, 9000, 4, 240)):
                    _draw_mountain(draw, x, y, rng.randint(transform.design_px(4), transform.design_px(9)), rng)
            elif terrain_type == "tundra_permafrost":
                apply_color(image, PALETTE["tundra"], mask, 130)
                for x, y in _random_points_in_mask(mask, rng, _mask_density_count(mask, 6000, 5, 500)):
                    length = rng.randint(transform.design_px(4), transform.design_px(13))
                    draw.line((x - length, y, x + length, y), fill=(92, 99, 91, 105), width=transform.design_px(1))
            elif terrain_type in {"arcane_highlands", "floating_island_chain"}:
                apply_color(image, "#8b8566", mask, 105)
                for x, y in _random_points_in_mask(mask, rng, _mask_density_count(mask, 7500, 4, 400)):
                    _draw_mountain(draw, x, y, rng.randint(transform.design_px(3), transform.design_px(7)), rng)
            elif terrain_type == "temperate_plains":
                apply_color(image, PALETTE["land_light"], mask, 85)
                for x, y in _random_points_in_mask(mask, rng, _mask_density_count(mask, 14000, 3, 260)):
                    length = rng.randint(transform.design_px(9), transform.design_px(24))
                    spacing = transform.design_px(3)
                    for offset in range(-spacing * 2, spacing * 3, spacing):
                        draw.line((x - length, y + offset, x + length, y + offset), fill=(105, 87, 46, 90), width=transform.design_px(1))

        if geometry.get("type") in {"LineString", "MultiLineString"}:
            for path in line_paths(geometry, transform):
                if terrain_type == "mountain_axis":
                    spacing = transform.design_px(20)
                    for x, y in _sample_polyline(path, spacing):
                        _draw_mountain(draw, x + rng.randint(-spacing // 2, spacing // 2), y + rng.randint(-spacing // 2, spacing // 2), rng.randint(transform.design_px(7), transform.design_px(14)), rng)
                elif terrain_type == "gorge_axis":
                    draw.line(
                        path,
                        fill=(77, 48, 38, 165),
                        width=transform.design_px(7),
                        joint="curve",
                    )
                    draw.line(
                        path,
                        fill=(181, 125, 71, 145),
                        width=transform.design_px(2),
                        joint="curve",
                    )
    image.alpha_composite(symbol_layer)


def draw_rivers(
    image: Image.Image,
    features: list[dict[str, Any]],
    transform: CanvasTransform,
) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for feature in features:
        properties = feature.get("properties", {})
        water_type = properties.get("water_type")
        if water_type not in {"river_system", "seasonal_channel_system"}:
            continue
        width = transform.width_px(float(properties.get("nominal_width", 30)), 2)
        for path in line_paths(feature.get("geometry", {}), transform):
            if water_type == "seasonal_channel_system":
                draw_dashed_line(draw, path, fill=(66, 91, 88, 210), width=width, dash=transform.design_px(14), gap=transform.design_px(7))
            else:
                draw.line(path, fill=(177, 183, 147, 190), width=width + transform.design_px(4), joint="curve")
                draw.line(path, fill=PALETTE["river"], width=width, joint="curve")
                draw.line(path, fill=(145, 166, 157, 175), width=max(1, width // 3), joint="curve")
    image.alpha_composite(layer)


def draw_coasts(
    image: Image.Image, features: list[dict[str, Any]], transform: CanvasTransform
) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for feature in features:
        for rings in polygon_rings(feature.get("geometry", {}), transform):
            for ring in rings:
                draw.line(ring, fill=(47, 52, 43, 230), width=transform.design_px(7), joint="curve")
                draw.line(ring, fill=(202, 181, 124, 220), width=transform.design_px(4), joint="curve")
                draw.line(ring, fill=(58, 55, 44, 235), width=transform.design_px(2), joint="curve")
            outer = rings[0]
            signed_area = sum(
                first[0] * second[1] - second[0] * first[1]
                for first, second in zip(outer, outer[1:])
            )
            spacing = transform.design_px(24)
            inset_start = transform.design_px(4)
            inset_end = transform.design_px(13)
            for start, end in zip(outer, outer[1:]):
                dx = end[0] - start[0]
                dy = end[1] - start[1]
                length = math.hypot(dx, dy)
                if length < 1:
                    continue
                # GeoJSON exterior ring orientation decides which normal is
                # inward.  The canonical coast itself remains the dark center
                # stroke; these are only traditional copperplate hachures.
                if signed_area >= 0:
                    nx, ny = -dy / length, dx / length
                else:
                    nx, ny = dy / length, -dx / length
                distance = spacing / 2
                while distance < length:
                    ratio = distance / length
                    x = start[0] + dx * ratio
                    y = start[1] + dy * ratio
                    draw.line(
                        (
                            round(x + nx * inset_start),
                            round(y + ny * inset_start),
                            round(x + nx * inset_end),
                            round(y + ny * inset_end),
                        ),
                        fill=(68, 62, 46, 115),
                        width=transform.design_px(1),
                    )
                    distance += spacing
    image.alpha_composite(layer)


def draw_transport(
    image: Image.Image,
    features: list[dict[str, Any]],
    transform: CanvasTransform,
) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for feature in features:
        route_type = feature.get("properties", {}).get("route_type", "road")
        for path in line_paths(feature.get("geometry", {}), transform):
            if route_type == "road":
                draw.line(path, fill=(62, 49, 34, 210), width=transform.design_px(7), joint="curve")
                draw.line(path, fill=(214, 188, 124, 245), width=transform.design_px(4), joint="curve")
                draw.line(path, fill=(112, 77, 45, 235), width=transform.design_px(1), joint="curve")
            elif route_type == "caravan":
                draw_dashed_line(draw, path, fill=(78, 53, 33, 230), width=transform.design_px(3), dash=transform.design_px(11), gap=transform.design_px(6))
            elif route_type == "rail":
                draw.line(path, fill=(50, 45, 37, 230), width=transform.design_px(6), joint="curve")
                draw.line(path, fill=(191, 167, 105, 240), width=transform.design_px(2), joint="curve")
                for x, y in _sample_polyline(path, transform.design_px(10)):
                    radius = transform.design_px(3)
                    draw.line((x - radius, y - radius, x + radius, y + radius), fill=(52, 46, 37, 210), width=transform.design_px(1))
            elif route_type in {"sea", "submarine", "underwater_tunnel"}:
                color = (197, 205, 175, 215) if route_type == "sea" else (62, 101, 104, 215)
                draw_dashed_line(draw, path, fill=(44, 70, 72, 180), width=transform.design_px(5), dash=transform.design_px(17), gap=transform.design_px(8))
                draw_dashed_line(draw, path, fill=color, width=transform.design_px(2), dash=transform.design_px(17), gap=transform.design_px(8))
            elif route_type == "air":
                draw_dashed_line(draw, path, fill=(198, 184, 139, 55), width=transform.design_px(2), dash=transform.design_px(13), gap=transform.design_px(10))
                draw_dashed_line(draw, path, fill=(76, 74, 59, 50), width=transform.design_px(1), dash=transform.design_px(13), gap=transform.design_px(10))
            elif route_type in {"tunnel", "warp"}:
                color = (99, 64, 93, 225) if route_type == "warp" else (60, 52, 43, 225)
                draw_dashed_line(draw, path, fill=color, width=transform.design_px(4), dash=transform.design_px(7), gap=transform.design_px(5))
    image.alpha_composite(layer)


def _polygon_bbox(feature: dict[str, Any], transform: CanvasTransform) -> tuple[int, int, int, int] | None:
    points: list[tuple[int, int]] = []
    for rings in polygon_rings(feature.get("geometry", {}), transform):
        points.extend(rings[0])
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def draw_settlements(
    image: Image.Image,
    features: list[dict[str, Any]],
    transform: CanvasTransform,
    seed: int,
) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for feature in features:
        rng = random.Random(stable_seed(seed, "settlement", feature_id(feature)))
        node_type = feature.get("properties", {}).get("node_type", "city")
        bbox = _polygon_bbox(feature, transform)
        if bbox is None:
            continue
        # Preserve the full canonical footprint as a quiet QA/control outline,
        # while the map-readable settlement mark stays a constant visual size.
        for rings in polygon_rings(feature.get("geometry", {}), transform):
            draw.line(
                rings[0],
                fill=(58, 43, 31, 58),
                width=transform.design_px(1),
                joint="curve",
            )

        left, top, right, bottom = bbox
        center_x = (left + right) // 2
        center_y = (top + bottom) // 2
        design_sizes = {
            "capital": 18,
            "city": 10,
            "town": 8,
            "port": 11,
            "air_terminal": 12,
            "floating_island": 13,
            "underwater_city": 13,
        }
        radius = transform.design_px(design_sizes.get(node_type, 9), 2)
        ink = (49, 37, 28, 245)
        warm_fill = (194 + rng.randint(-6, 6), 148, 78, 235)
        if node_type == "capital":
            draw.ellipse(
                (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
                fill=warm_fill,
                outline=ink,
                width=transform.design_px(3),
            )
            draw.ellipse(
                (center_x - radius // 3, center_y - radius // 3, center_x + radius // 3, center_y + radius // 3),
                fill=(94, 65, 41, 245),
            )
        elif node_type in {"city", "town"}:
            draw.ellipse(
                (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
                fill=warm_fill,
                outline=ink,
                width=transform.design_px(2),
            )
        elif node_type == "port":
            draw.ellipse(
                (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
                fill=(105, 106, 79, 225),
                outline=ink,
                width=transform.design_px(2),
            )
            draw.line((center_x - radius, center_y, center_x + radius, center_y), fill=ink, width=transform.design_px(2))
            draw.line((center_x, center_y - radius, center_x, center_y + radius), fill=ink, width=transform.design_px(2))
        elif node_type == "air_terminal":
            draw.polygon(
                ((center_x, center_y - radius), (center_x + radius, center_y), (center_x, center_y + radius), (center_x - radius, center_y)),
                fill=(176, 157, 100, 230),
                outline=ink,
            )
        elif node_type == "floating_island":
            draw.ellipse(
                (center_x - radius, center_y - radius // 2, center_x + radius, center_y + radius // 2),
                fill=(117, 120, 75, 230),
                outline=ink,
                width=transform.design_px(2),
            )
            draw.polygon(
                ((center_x - radius, center_y), (center_x + radius, center_y), (center_x, center_y + radius * 2)),
                fill=(64, 57, 45, 220),
                outline=ink,
            )
        elif node_type == "underwater_city":
            draw.ellipse(
                (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
                fill=(70, 112, 112, 190),
                outline=(177, 194, 169, 245),
                width=transform.design_px(3),
            )
            inner = max(1, radius // 2)
            draw.ellipse(
                (center_x - inner, center_y - inner, center_x + inner, center_y + inner),
                outline=ink,
                width=transform.design_px(1),
            )
    image.alpha_composite(layer)


def _clip_ocean_details(
    textured_image: Image.Image,
    before_water: Image.Image,
    land_mask: Image.Image,
) -> Image.Image:
    """Keep wave marks off land while retaining the base water rendering."""
    ocean_mask = ImageOps.invert(land_mask)
    return Image.composite(textured_image, before_water, ocean_mask)


def render_master(
    sources: dict[str, dict[str, Any]],
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    seed: int = DEFAULT_SEED,
) -> Image.Image:
    transform = CanvasTransform(width, height)
    image = Image.new("RGBA", (width, height), PALETTE["ocean"])
    add_seeded_texture(image, seed, transform)

    land_features = sources["landmasses"]["features"]
    land_mask = collection_mask(image.size, land_features, transform)
    before_water = image.copy()
    draw_water(image, sources["hydrography"]["features"], transform, seed)
    water_render = image
    image = _clip_ocean_details(water_render, before_water, land_mask)
    water_render.close()
    before_water.close()

    apply_color(image, PALETTE["land"], land_mask)
    # A second, low-opacity canvas-wide grain makes land feel like candidate B
    # while still using one non-repeating source texture.
    untextured = image.copy()
    add_seeded_texture(image, stable_seed(seed, "land-grain"), transform)
    image = Image.composite(image, untextured, land_mask)
    untextured.close()
    draw_regions(image, sources["regions"]["features"], land_mask, transform)
    draw_generic_land_detail(image, land_features, transform, seed)
    draw_terrain(image, sources["terrain"]["features"], land_mask, transform, seed)
    draw_rivers(image, sources["hydrography"]["features"], transform)
    draw_coasts(image, land_features, transform)
    draw_transport(image, sources["transport"]["features"], transform)
    draw_settlements(image, sources["settlements"]["features"], transform, seed)
    return image.convert("RGB")


def source_metadata(
    sources: dict[str, dict[str, Any]], source_dir: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_records: dict[str, Any] = {}
    for key, filename in SOURCE_FILES.items():
        features = sources[key]["features"]
        source_records[key] = {
            "path": _repo_relative_or_absolute(source_dir / filename),
            "sha256": sha256_file(source_dir / filename),
            "feature_count": len(features),
            "feature_ids": [feature_id(feature) for feature in features],
        }
    inventory = {
        "continents": {
            "count": len(sources["landmasses"]["features"]),
            "ids": [feature_id(feature) for feature in sources["landmasses"]["features"]],
        },
        "regions": {
            "count": len(sources["regions"]["features"]),
            "ids": [feature_id(feature) for feature in sources["regions"]["features"]],
        },
        "routes": {
            "count": len(sources["transport"]["features"]),
            "ids": [feature_id(feature) for feature in sources["transport"]["features"]],
        },
        "settlement_footprints": {
            "count": len(sources["settlements"]["features"]),
            "ids": [feature_id(feature) for feature in sources["settlements"]["features"]],
        },
    }
    return source_records, inventory


def _repo_relative_or_absolute(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _copy_exclusive(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_handle, destination.open("xb") as output_handle:
        shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)


def write_master(
    output_path: Path,
    metadata_path: Path,
    *,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    output_path = output_path.resolve()
    metadata_path = metadata_path.resolve()
    if output_path == metadata_path:
        raise RenderError("PNG and metadata paths must be different")
    for target in (output_path, metadata_path):
        if target.exists():
            raise RenderError(f"refusing to overwrite existing output: {target}")
        if target.resolve() in {REPO_ROOT.resolve(), Path.home().resolve(), Path(target.anchor).resolve()}:
            raise RenderError(f"refusing broad output target: {target}")

    sources = load_sources(source_dir)
    image = render_master(sources, width=width, height=height, seed=seed)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_png_name = tempfile.mkstemp(prefix=f".{output_path.stem}.", suffix=".png", dir=output_path.parent)
    os.close(fd)
    temp_png = Path(temp_png_name)
    temp_json = temp_png.with_suffix(".json")
    installed_png = False
    installed_json = False
    try:
        image.save(temp_png, format="PNG", compress_level=6, optimize=False)
        png_sha256 = sha256_file(temp_png)
        sources_record, inventory = source_metadata(sources, source_dir)
        metadata: dict[str, Any] = {
            "schema_version": "1.0.0",
            "type": "sstory-world-generation-control",
            "generated_by": GENERATOR_ID,
            "artifact_role": "canonical-generation-control-and-qa-overlay",
            "publication": {
                "public_basemap": False,
                "adoption_status": "control-only",
                "reason": "Low-vertex canonical masks are authoritative controls, not final illustrative cartography.",
            },
            "coordinate_reference_system": "EA-WORLD-1",
            "world_bounds": list(WORLD_BOUNDS),
            "canvas": {"width": width, "height": height, "aspect_ratio": width / height},
            "canonical_transform": {
                "operation": "direct-linear-rasterization",
                "x": "round(ea_x / 10000 * (width - 1))",
                "y": "round(ea_y / 10000 * (height - 1))",
                "source_coordinates_modified": False,
            },
            "style": {
                "profile": "style-candidate-b-v1",
                "description": "candidate-B-inspired control palette: muted parchment, teal sea, olive forest, grey mountains, high-clarity roads and rivers",
                "palette": PALETTE,
                "contains_text": False,
                "font_rendering_used": False,
            },
            "microdetail": {
                "seed": seed,
                "algorithm": "sha256-namespaced MT19937 with one non-tiled canvas grain field",
                "deterministic": True,
                "canonical_geometry_is_decoration_boundary": True,
            },
            "canonical_inventory": inventory,
            "sources": sources_record,
            "output": {
                "path": _repo_relative_or_absolute(output_path),
                "metadata_path": _repo_relative_or_absolute(metadata_path),
                "format": "PNG",
                "mode": "RGB",
                "width": width,
                "height": height,
                "bytes": temp_png.stat().st_size,
                "sha256": png_sha256,
            },
        }
        temp_json.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        # Exclusive creation is used instead of replace/rename so a racing or
        # pre-existing user asset can never be overwritten.
        _copy_exclusive(temp_png, output_path)
        installed_png = True
        try:
            _copy_exclusive(temp_json, metadata_path)
            installed_json = True
        except Exception:
            output_path.unlink(missing_ok=True)
            installed_png = False
            raise
        return metadata
    finally:
        image.close()
        temp_png.unlink(missing_ok=True)
        temp_json.unlink(missing_ok=True)
        # Only files created by this invocation are candidates for cleanup.
        if installed_png and not installed_json:
            output_path.unlink(missing_ok=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--metadata",
        type=Path,
        help="metadata JSON path (default: PNG path with .json suffix)",
    )
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    metadata_path = args.metadata or args.output.with_suffix(".json")
    try:
        metadata = write_master(
            args.output,
            metadata_path,
            source_dir=args.source_dir,
            width=args.width,
            height=args.height,
            seed=args.seed,
        )
    except (OSError, RenderError) as exc:
        print(f"world control render failed: {exc}")
        return 1
    print(
        "world control rendered: "
        f"{metadata['output']['path']} "
        f"{metadata['output']['width']}x{metadata['output']['height']} "
        f"sha256={metadata['output']['sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
