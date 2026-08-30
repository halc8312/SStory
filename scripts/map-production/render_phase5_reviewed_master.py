#!/usr/bin/env python3
"""Render reviewed Phase 5 masters directly from canonical EA-WORLD-1 data.

The v2 renderer never crops or upscales the world raster.  Canonical
coordinates are projected onto the native-zoom global pixel grid and then into
each bounded sheet.  Decorative marks use a seed-locked, sheet-independent
world grid, so the same feature receives the same detail in overlapping sheets.
All symbols are orthographic plan vocabulary: no text, frames, roofs, facades,
directional highlights, shadows, cliff sides, or floating-island undersides.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from functools import cached_property
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageStat

import phase5_highland_detail_exemplar as highland_detail_exemplar
from render_world_master import (
    SOURCE_FILES,
    RenderError,
    feature_id,
    feature_mask,
    line_paths,
    load_sources,
    polygon_rings,
    sha256_file,
)
from validate_resolution_contract import validate_resolution_contract


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DIR = REPO_ROOT / "world" / "map-production" / "source"
DEFAULT_CONTRACT = (
    REPO_ROOT / "world" / "map-production" / "spec" / "resolution-contract.json"
)
DEFAULT_MAP_SHEETS = DEFAULT_SOURCE_DIR / "map-sheets.json"
DEFAULT_CANONICAL_CONTROL_INDEX = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "controls"
    / "phase5-metatiles"
    / "index.json"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "tmp" / "map-production" / "phase5-reviewed-v2"
DEFAULT_SHEET_ID = "sheet_region_soaring_mountains_region"
DEFAULT_SEED = 0xEA20260719
DEFAULT_MATERIAL_ATLAS = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "style-assets"
    / "phase5-cartographic-material-atlas-v1.png"
)
DEFAULT_GLOBAL_NEUTRAL_MATERIAL = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "candidates"
    / "phase5-neutral-land-material-h4-v1.png"
)
GLOBAL_NEUTRAL_MATERIAL_SHA256 = (
    "f848f79a6022c6bfd0341ed6d1e67de73c47b2077e8f96ae4afef208bedc3cfa"
)
GLOBAL_NEUTRAL_MATERIAL_SIZE = (1536, 1024)
MATERIAL_ATLAS_SHA256 = (
    "9b42dcce48d275d392bc28235925ac02f37690ace3418d6cb65920f4da05c6e3"
)
MATERIAL_ATLAS_SIZE = (1536, 1024)
MATERIAL_ATLAS_CROPS: dict[str, dict[str, Any]] = {
    "connected_forest": {
        "rect_px": (24, 24, 472, 472),
        "raw_rgb_sha256": (
            "81a2a305c7a957ce2b998ba83f793854b81fffc4803ba9161f8f3e21de66f5a4"
        ),
        "usage_masks": (
            "terrain:temperate_magic_forest",
            "terrain:tropical_magic_rainforest",
        ),
        "cell_world": 112.0,
        "patch_world": 235.0,
        "max_alpha": 32,
        "strength": 0.10,
        "strength_limit": 0.12,
        "feather_px": 128,
    },
    "cultivated_hatching": {
        "rect_px": (32, 600, 600, 1000),
        "raw_rgb_sha256": (
            "1fe55bfd83eaac0b91acb5e9d685c5b1ed6a98e938cab869aa166380b6539734"
        ),
        "usage_masks": ("region:agricultural_region",),
        "cell_world": 118.0,
        "patch_world": 248.0,
        "max_alpha": 25,
        "strength": 0.10,
        "strength_limit": 0.12,
        "feather_px": 128,
    },
    "wetland": {
        "rect_px": (760, 620, 1120, 1000),
        "raw_rgb_sha256": (
            "9392ead6cb954a8d1893c3012ee5001b81c90ebf593db741c4b6a9159e6d5cd1"
        ),
        "usage_masks": ("hydrography:river_system-riparian-corridor",),
        "cell_world": 104.0,
        "patch_world": 225.0,
        "max_alpha": 16,
        "strength": 0.09,
        "strength_limit": 0.12,
        "feather_px": 96,
    },
    "neutral_parchment": {
        "rect_px": (1336, 296, 1368, 328),
        "raw_rgb_sha256": (
            "63e04598ab885f0d461b2209f672ad558e43f02cfad1f7565a52c32b3a10b659"
        ),
        "usage_masks": ("land:ordinary_plan_land",),
        "cell_world": 14.0,
        "patch_world": 20.0,
        "max_alpha": 6,
        "strength": 0.035,
        "strength_limit": 0.07,
        "feather_px": 160,
    },
    "flat_rock_hachure": {
        "rect_px": (970, 210, 1070, 310),
        "raw_rgb_sha256": (
            "d090585ff5ba68d955b8fb26d4940142b8a7148290916c94e997a2a2981f59ce"
        ),
        "usage_masks": (
            "terrain:mountain_axis",
            "terrain:gorge_axis",
            "terrain:volcanic_land",
            "terrain:arcane_highlands",
            "terrain:tundra_permafrost",
        ),
        "cell_world": 48.0,
        "patch_world": 104.0,
        "max_alpha": 26,
        "strength": 0.055,
        "strength_limit": 0.07,
        "feather_px": 128,
    },
}
MATERIAL_ATLAS_EXCLUSIONS = (
    "right-side repeated grass-bundle field",
    "central dimensional or triangular peak-like rocks",
)
FULL_SPATIAL_MATERIAL_MODE = "full-spatial-quilt-preview-v1"
GLOBAL_NEUTRAL_BANDPASS_MODE = "global-neutral-bandpass-preview-v1"
RESIDUAL_MATERIAL_MODE = "signed-high-pass-v1"
MATERIAL_TRANSFER_MODES = frozenset(
    {
        RESIDUAL_MATERIAL_MODE,
        FULL_SPATIAL_MATERIAL_MODE,
        GLOBAL_NEUTRAL_BANDPASS_MODE,
    }
)
PREVIEW_ONLY_MATERIAL_MODES = frozenset(
    {FULL_SPATIAL_MATERIAL_MODE, GLOBAL_NEUTRAL_BANDPASS_MODE}
)
SEMANTIC_BOUNDARY_CONTRAST_LIMIT = 0.75
GLOBAL_NEUTRAL_BANDPASS: dict[str, Any] = {
    "fine_blur_px": 1.5,
    "broad_blur_px": 18.0,
    "fine_weight": 0.38,
    "mid_weight": 0.65,
    "bandpass_clamp_luma_levels": 18,
    "land_mean_tolerance_luma_levels": 0.25,
    "patch_world": 520.0,
    "stride_world": 210.0,
    "source_fraction": (0.55, 0.92),
    "maximum_royal_windows": 45,
    "broad_noise": (
        {"cell_world": 180.0, "amplitude_luma_levels": 3},
        {"cell_world": 420.0, "amplitude_luma_levels": 2},
    ),
    "maximum_broad_noise_luma_levels": 5,
    # A globally tiled sub-luma dither recenters the fixed Royal land sample
    # without a sheet-local offset.  Its phase is native-global pixel space,
    # so overlapping sheets retain byte-identical shared pixels.
    "world_recenter_base_luma_levels": 1,
    "world_recenter_fraction": 0.525,
    "world_recenter_period_px": 251,
}
FULL_SPATIAL_QUILT: dict[str, dict[str, Any]] = {
    # World dimensions are deliberately much larger than the decorative mark
    # grid.  Adjacent windows overlap by roughly 55-65%, so their raised-cosine
    # mattes behave like a small multiband quilt instead of a stamp field.
    "connected_forest": {
        "patch_world": 190.0,
        "stride_world": 76.0,
        "source_fraction": (0.54, 0.94),
        "output_scale": (0.82, 1.18),
        "maximum_alpha": 176,
        "semantic_feather_px": 34,
        "edge_breakup": True,
    },
    "cultivated_hatching": {
        "patch_world": 178.0,
        "stride_world": 72.0,
        "source_fraction": (0.48, 0.88),
        "output_scale": (0.80, 1.20),
        "maximum_alpha": 148,
        "semantic_feather_px": 20,
        "edge_breakup": False,
    },
    "wetland": {
        "patch_world": 164.0,
        "stride_world": 67.0,
        "source_fraction": (0.52, 0.92),
        "output_scale": (0.80, 1.18),
        "maximum_alpha": 34,
        "semantic_feather_px": 27,
        "edge_breakup": True,
    },
    "neutral_parchment": {
        "patch_world": 72.0,
        "stride_world": 29.0,
        "source_fraction": (0.62, 1.0),
        "output_scale": (0.82, 1.22),
        "maximum_alpha": 92,
        "semantic_feather_px": 14,
        "edge_breakup": False,
    },
    "flat_rock_hachure": {
        "patch_world": 126.0,
        "stride_world": 52.0,
        "source_fraction": (0.50, 0.94),
        "output_scale": (0.80, 1.18),
        "maximum_alpha": 118,
        "semantic_feather_px": 18,
        "edge_breakup": False,
    },
}
GENERATOR_ID = "sstory-map-production/render_phase5_reviewed_master.py@2.6"
PNG_OPTIONS = {"format": "PNG", "compress_level": 9, "optimize": False}

GENERATION_SHEET_TYPES = frozenset({"region", "corridor", "settlement"})
REPRESENTATIVE_SHEET_IDS = (
    "sheet_region_royal_capital_region",
    "sheet_region_soaring_mountains_region",
    "sheet_region_moonlit_forest_region",
    "sheet_region_lumiera_arch_region",
    "sheet_region_red_sea_desert_region",
    "sheet_settlement_astralis",
)
SUPPORTED_TERRAIN_TYPES = frozenset(
    {
        "temperate_plains",
        "temperate_magic_forest",
        "tropical_magic_rainforest",
        "mountain_axis",
        "hot_desert",
        "volcanic_land",
        "arcane_highlands",
        "tundra_permafrost",
        "gorge_axis",
        "floating_island_chain",
    }
)
AGRICULTURAL_REGION_TYPE = "agricultural_region"
SETTLEMENT_CELL_WORLD = {
    "capital": 1.65,
    "city": 1.90,
    "port": 2.10,
    "town": 2.35,
    "underwater_city": 2.20,
    "air_terminal": 2.50,
    "floating_island": 2.70,
}
STROKE_CAPS_PX = {
    "world": {
        "river": 3,
        "river_casing": 5,
        "road": 1,
        "road_casing": 2,
        "rail": 1,
    },
    "continent": {
        "river": 4,
        "river_casing": 6,
        "road": 2,
        "road_casing": 3,
        "rail": 2,
    },
    "region": {
        "river": 5,
        "river_casing": 7,
        "road": 2,
        "road_casing": 3,
        "rail": 2,
    },
    "corridor": {
        "river": 6,
        "river_casing": 8,
        "road": 2,
        "road_casing": 3,
        "rail": 2,
    },
    "settlement": {
        "river": 7,
        "river_casing": 9,
        "road": 3,
        "road_casing": 4,
        "rail": 2,
    },
}
FORBIDDEN_COUNTERS = (
    "generated_text",
    "frames",
    "directional_highlights",
    "tree_trunks",
    "round_canopy_stamps",
    "roof_faces",
    "facades",
    "cast_shadows",
    "cliff_side_faces",
    "floating_undersides",
    "oblique_triangle_symbols",
    "continuous_contours",
    "radial_rosettes",
)

PALETTE = {
    "ocean": "#4d7182",
    "ocean_deep": "#35596a",
    "ocean_light": "#87a0a4",
    "land": "#c1ad76",
    "land_light": "#d0bd87",
    "parchment_light": "#d8c58e",
    "ink": "#443a2d",
    "ink_soft": "#6e5a40",
    "forest": "#66704a",
    "forest_dark": "#3f4a32",
    "mountain_wash": "#8a7b61",
    "mountain_ink": "#594a39",
    "river": "#436f83",
    "river_light": "#91aeb1",
    "road": "#6b4c32",
    "road_light": "#d7c28b",
    "settlement": "#9a6844",
    "settlement_dark": "#49362a",
    "plains": "#9a8d58",
    "agriculture": "#a8874f",
    "tropical": "#4e6841",
    "desert": "#ad8555",
    "volcanic": "#735349",
    "arcane": "#68604f",
    "permafrost": "#9ca59b",
    "gorge": "#765747",
}


class ReviewedMasterError(ValueError):
    """Raised when the prototype cannot prove its rendering contract."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewedMasterError(f"could not read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReviewedMasterError(f"JSON root must be an object: {path}")
    return value


def _repo_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


@dataclass(frozen=True)
class SheetCanvasTransform:
    """Exact EA-WORLD-1 -> native global pixel -> sheet pixel transform."""

    contract: dict[str, Any]
    sheet: dict[str, Any]

    def __post_init__(self) -> None:
        bounds = self.sheet.get("bounds")
        pixel_bounds = self.sheet.get("pixel_bounds")
        if not isinstance(bounds, list) or len(bounds) != 4:
            raise ReviewedMasterError("sheet bounds must contain four values")
        if not isinstance(pixel_bounds, list) or len(pixel_bounds) != 4:
            raise ReviewedMasterError("sheet pixel_bounds must contain four values")
        if self.width != self.sheet.get("width") or self.height != self.sheet.get(
            "height"
        ):
            raise ReviewedMasterError("sheet dimensions do not match pixel_bounds")

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return tuple(float(value) for value in self.sheet["bounds"])  # type: ignore[return-value]

    @property
    def pixel_bounds(self) -> tuple[int, int, int, int]:
        return tuple(int(value) for value in self.sheet["pixel_bounds"])  # type: ignore[return-value]

    @property
    def width(self) -> int:
        left, _, right, _ = self.pixel_bounds
        return right - left

    @property
    def height(self) -> int:
        _, top, _, bottom = self.pixel_bounds
        return bottom - top

    @cached_property
    def native_scale(self) -> Fraction:
        world = self.contract["world_raster"]
        exponent = self.sheet["native_zoom"] - world["native_zoom"]
        base = self.contract["pixel_bounds_formula"]["scale_base"]
        if exponent >= 0:
            return Fraction(base**exponent, 1)
        return Fraction(1, base**-exponent)

    @cached_property
    def _pixels_per_world_x(self) -> Fraction:
        extent = self.contract["world_extent"]
        world = self.contract["world_raster"]
        return (
            Fraction(world["width_px"])
            * self.native_scale
            / (Fraction(str(extent["max_x"])) - Fraction(str(extent["min_x"])))
        )

    @cached_property
    def _pixels_per_world_y(self) -> Fraction:
        extent = self.contract["world_extent"]
        world = self.contract["world_raster"]
        return (
            Fraction(world["height_px"])
            * self.native_scale
            / (Fraction(str(extent["max_y"])) - Fraction(str(extent["min_y"])))
        )

    @cached_property
    def _pixels_per_world_mean_float(self) -> float:
        return (float(self._pixels_per_world_x) + float(self._pixels_per_world_y)) / 2

    def _global_coordinate(self, value: float, axis: str) -> Fraction:
        extent = self.contract["world_extent"]
        minimum = Fraction(str(extent[f"min_{axis}"]))
        scale = self._pixels_per_world_x if axis == "x" else self._pixels_per_world_y
        return (Fraction(str(value)) - minimum) * scale

    @staticmethod
    def _round_half_up(value: Fraction) -> int:
        return math.floor(value + Fraction(1, 2))

    def global_point(self, coordinate: Sequence[float]) -> tuple[int, int]:
        if len(coordinate) < 2:
            raise ReviewedMasterError("coordinate must contain x and y")
        x = float(coordinate[0])
        y = float(coordinate[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ReviewedMasterError("coordinate must be finite")
        extent = self.contract["world_extent"]
        if not (
            extent["min_x"] <= x <= extent["max_x"]
            and extent["min_y"] <= y <= extent["max_y"]
        ):
            raise ReviewedMasterError(f"coordinate is outside EA-WORLD-1: {[x, y]}")
        return (
            self._round_half_up(self._global_coordinate(x, "x")),
            self._round_half_up(self._global_coordinate(y, "y")),
        )

    def point(self, coordinate: Sequence[float]) -> tuple[int, int]:
        global_x, global_y = self.global_point(coordinate)
        left, top, _, _ = self.pixel_bounds
        return global_x - left, global_y - top

    def point_fast(self, coordinate: Sequence[float]) -> tuple[int, int]:
        """Project a decorative anchor using cached global float scales."""

        extent = self.contract["world_extent"]
        global_x = math.floor(
            (float(coordinate[0]) - float(extent["min_x"]))
            * float(self._pixels_per_world_x)
            + 0.5
        )
        global_y = math.floor(
            (float(coordinate[1]) - float(extent["min_y"]))
            * float(self._pixels_per_world_y)
            + 0.5
        )
        left, top, _, _ = self.pixel_bounds
        return global_x - left, global_y - top

    def nominal_width_px(self, world_width: int | float) -> int:
        x0 = self._global_coordinate(0, "x")
        x1 = self._global_coordinate(float(world_width), "x")
        y0 = self._global_coordinate(0, "y")
        y1 = self._global_coordinate(float(world_width), "y")
        mean = (abs(x1 - x0) + abs(y1 - y0)) / 2
        return max(1, self._round_half_up(mean))

    def nominal_width_px_fast(self, world_width: int | float) -> int:
        return max(
            1, math.floor(float(world_width) * self._pixels_per_world_mean_float + 0.5)
        )


def _hash_digest(seed: int, namespace: str, *parts: object) -> bytes:
    payload = "\0".join((str(seed), namespace, *(str(part) for part in parts)))
    return hashlib.sha256(payload.encode("utf-8")).digest()


def _unit(digest: bytes, offset: int) -> float:
    start = offset % (len(digest) - 3)
    return int.from_bytes(digest[start : start + 4], "big") / 0xFFFFFFFF


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _smoothstep(value: float) -> float:
    value = _clamp(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def _ea_bilinear_noise(
    world_x: float,
    world_y: float,
    *,
    cell_world: float,
    namespace: str,
    seed: int,
) -> float:
    """Return sheet-independent smooth scalar noise at an EA-WORLD-1 point."""

    grid_x = math.floor(world_x / cell_world)
    grid_y = math.floor(world_y / cell_world)
    fraction_x = _smoothstep(world_x / cell_world - grid_x)
    fraction_y = _smoothstep(world_y / cell_world - grid_y)

    def corner(offset_x: int, offset_y: int) -> float:
        return _unit(
            _hash_digest(
                seed,
                namespace,
                grid_x + offset_x,
                grid_y + offset_y,
            ),
            0,
        )

    top = corner(0, 0) * (1.0 - fraction_x) + corner(1, 0) * fraction_x
    bottom = corner(0, 1) * (1.0 - fraction_x) + corner(1, 1) * fraction_x
    return top * (1.0 - fraction_y) + bottom * fraction_y


def _style_parameter(
    style_profile: dict[str, Any] | None,
    name: str,
    default: float,
) -> float:
    if not style_profile:
        return default
    parameters = style_profile.get("derived_render_parameters")
    if not isinstance(parameters, dict):
        return default
    value = parameters.get(name)
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return default
    return float(value)


def _style_rgb(
    style_profile: dict[str, Any] | None,
    name: str,
    default: tuple[int, int, int],
) -> tuple[int, int, int]:
    if not style_profile:
        return default
    parameters = style_profile.get("derived_render_parameters")
    value = parameters.get(name) if isinstance(parameters, dict) else None
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(not isinstance(channel, int) or not 0 <= channel <= 255 for channel in value)
    ):
        return default
    return value[0], value[1], value[2]


def iter_anchored_grid(
    transform: SheetCanvasTransform,
    *,
    cell_world: float,
    namespace: str,
    seed: int,
    margin_cells: int = 2,
    world_bounds: Sequence[float] | None = None,
) -> Iterator[tuple[int, int, float, float, bytes]]:
    """Yield sheet-independent jittered EA-WORLD-1 grid anchors."""

    sheet_min_x, sheet_min_y, sheet_max_x, sheet_max_y = transform.bounds
    if world_bounds is None:
        min_x, min_y, max_x, max_y = transform.bounds
    else:
        min_x = max(sheet_min_x, float(world_bounds[0]))
        min_y = max(sheet_min_y, float(world_bounds[1]))
        max_x = min(sheet_max_x, float(world_bounds[2]))
        max_y = min(sheet_max_y, float(world_bounds[3]))
        if min_x > max_x or min_y > max_y:
            return
    first_x = math.floor(min_x / cell_world) - margin_cells
    last_x = math.ceil(max_x / cell_world) + margin_cells
    first_y = math.floor(min_y / cell_world) - margin_cells
    last_y = math.ceil(max_y / cell_world) + margin_cells
    for grid_y in range(first_y, last_y + 1):
        for grid_x in range(first_x, last_x + 1):
            digest = _hash_digest(seed, namespace, grid_x, grid_y)
            world_x = (grid_x + 0.12 + 0.76 * _unit(digest, 0)) * cell_world
            world_y = (grid_y + 0.12 + 0.76 * _unit(digest, 4)) * cell_world
            yield grid_x, grid_y, world_x, world_y, digest


def _mask_point(mask: Image.Image, point: tuple[int, int]) -> bool:
    x, y = point
    return 0 <= x < mask.width and 0 <= y < mask.height and mask.getpixel(point) >= 128


def _alpha_composite_masked(
    image: Image.Image, layer: Image.Image, mask: Image.Image
) -> None:
    alpha = ImageChops.multiply(layer.getchannel("A"), mask)
    layer.putalpha(alpha)
    image.alpha_composite(layer)


def _polygon_outline(
    draw: ImageDraw.ImageDraw,
    feature: dict[str, Any],
    transform: SheetCanvasTransform,
    *,
    fill: tuple[int, int, int, int] | str | None = None,
    outline: tuple[int, int, int, int] | str | None = None,
    width: int = 1,
) -> None:
    for rings in polygon_rings(feature.get("geometry", {}), transform):
        if fill is not None:
            draw.polygon(rings[0], fill=fill)
        if outline is not None:
            draw.line(rings[0], fill=outline, width=width, joint="curve")
        for hole in rings[1:]:
            if outline is not None:
                draw.line(hole, fill=outline, width=width, joint="curve")


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[int, int]],
    *,
    fill: tuple[int, int, int, int] | str,
    width: int,
    dash: int,
    gap: int,
) -> None:
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
                draw.line(
                    (
                        round(x1 + (x2 - x1) * a),
                        round(y1 + (y2 - y1) * a),
                        round(x1 + (x2 - x1) * b),
                        round(y1 + (y2 - y1) * b),
                    ),
                    fill=fill,
                    width=width,
                )
            consumed = next_consumed
            remaining -= step
            if remaining <= 1e-9:
                drawing = not drawing
                remaining = float(dash if drawing else gap)


def _draw_global_paper_texture(
    image: Image.Image, transform: SheetCanvasTransform, seed: int
) -> dict[str, int]:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    flecks = 0
    fibres = 0
    for _, _, world_x, world_y, digest in iter_anchored_grid(
        transform,
        cell_world=6.5,
        namespace="paper-fleck-v1",
        seed=seed,
    ):
        if _unit(digest, 8) > 0.44:
            continue
        x, y = transform.point_fast((world_x, world_y))
        shade = (62, 54, 42, 11 + int(_unit(digest, 12) * 17))
        draw.point((x, y), fill=shade)
        if _unit(digest, 16) < 0.2:
            draw.point((x + 1, y), fill=shade)
        flecks += 1
    for _, _, world_x, world_y, digest in iter_anchored_grid(
        transform,
        cell_world=34,
        namespace="paper-fibre-v1",
        seed=seed,
    ):
        if _unit(digest, 8) > 0.48:
            continue
        x, y = transform.point_fast((world_x, world_y))
        length = 4 + int(_unit(digest, 12) * 13)
        rise = -2 + int(_unit(digest, 16) * 5)
        color = (
            (236, 216, 159, 15 + int(_unit(digest, 20) * 12))
            if _unit(digest, 24) < 0.53
            else (63, 54, 42, 8 + int(_unit(digest, 20) * 10))
        )
        draw.line((x, y, x + length, y + rise), fill=color, width=1)
        fibres += 1
    image.alpha_composite(layer)
    layer.close()
    return {"paper_flecks": flecks, "paper_fibres": fibres}


def _draw_water_texture(
    image: Image.Image,
    ocean_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
    *,
    full_material_preview: bool = False,
) -> dict[str, int]:
    mottle_count = 0
    if full_material_preview:
        # Two very soft opposing-value fields keep broad water from reading as
        # a flat fill.  Their EA-WORLD-1 anchors, sizes, and colours are hash
        # locked; all blur spill is clipped back through the canonical water
        # mask before it can touch land.
        mottle = Image.new("RGBA", image.size, (0, 0, 0, 0))
        mottle_draw = ImageDraw.Draw(mottle)
        for _, _, world_x, world_y, digest in iter_anchored_grid(
            transform,
            cell_world=92.0,
            namespace="water-mottle-full-material-v1",
            seed=seed,
            margin_cells=3,
        ):
            point = transform.point_fast((world_x, world_y))
            if not _mask_point(ocean_mask, point):
                continue
            x, y = point
            radius_x = transform.nominal_width_px_fast(
                45.0 + 58.0 * _unit(digest, 8)
            )
            radius_y = transform.nominal_width_px_fast(
                25.0 + 44.0 * _unit(digest, 12)
            )
            if _unit(digest, 16) < 0.52:
                colour = (38, 70, 84, 15 + round(12 * _unit(digest, 20)))
            else:
                colour = (154, 174, 164, 12 + round(11 * _unit(digest, 20)))
            mottle_draw.ellipse(
                (x - radius_x, y - radius_y, x + radius_x, y + radius_y),
                fill=colour,
            )
            mottle_count += 1
        blurred = mottle.filter(
            ImageFilter.GaussianBlur(
                radius=max(12, transform.nominal_width_px_fast(15.0))
            )
        )
        _alpha_composite_masked(image, blurred, ocean_mask)
        blurred.close()
        mottle.close()

    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    count = 0
    for _, _, world_x, world_y, digest in iter_anchored_grid(
        transform,
        cell_world=17.0 if full_material_preview else 19.0,
        namespace=(
            "water-wavelet-full-material-v1"
            if full_material_preview
            else "water-wavelet-v1"
        ),
        seed=seed,
    ):
        envelope = _ea_bilinear_noise(
            world_x,
            world_y,
            cell_world=154.0,
            namespace="water-wavelet-density-full-material-v1",
            seed=seed,
        )
        probability = 0.34 + 0.48 * envelope if full_material_preview else 0.62
        if _unit(digest, 8) > probability:
            continue
        point = transform.point_fast((world_x, world_y))
        if not _mask_point(ocean_mask, point):
            continue
        x, y = point
        length = 5 + int(_unit(digest, 12) * (15 if full_material_preview else 12))
        bend = -3 + int(_unit(digest, 16) * 7)
        if full_material_preview:
            # Five mirrored points make the two arms geometrically symmetric;
            # a small EA-locked rotation prevents horizontal wallpaper rows.
            angle = -0.18 + 0.36 * _unit(digest, 24)
            cosine = math.cos(angle)
            sine = math.sin(angle)
            local = (
                (-length, 0.0),
                (-length * 0.52, bend * 0.62),
                (0.0, float(bend)),
                (length * 0.52, bend * 0.62),
                (length, 0.0),
            )
            points = [
                (
                    round(x + local_x * cosine - local_y * sine),
                    round(y + local_x * sine + local_y * cosine),
                )
                for local_x, local_y in local
            ]
            light = _unit(digest, 20) < 0.70
            fill = (
                (188, 198, 178, 31 + int(_unit(digest, 28) * 33))
                if light
                else (42, 72, 84, 25 + int(_unit(digest, 28) * 26))
            )
            draw.line(points, fill=fill, width=1, joint="curve")
            if _unit(digest, 29) < 0.27:
                inset = max(2, round(length * 0.46))
                draw.line(
                    ((x - inset, y + 3), (x, y + 3 + bend // 2), (x + inset, y + 3)),
                    fill=(177, 192, 175, 22),
                    width=1,
                    joint="curve",
                )
        else:
            draw.line(
                ((x - length, y), (x, y + bend), (x + length, y)),
                fill=(199, 205, 181, 28 + int(_unit(digest, 20) * 35)),
                width=1,
            )
        count += 1
    _alpha_composite_masked(image, layer, ocean_mask)
    layer.close()
    return {
        "water_wavelets": count,
        "water_mottle_patches": mottle_count,
        "water_symmetric_wavelets": count if full_material_preview else 0,
        "water_outside_canonical_mask_changes": 0,
    }


def _draw_region_washes(
    image: Image.Image,
    regions: Iterable[dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
) -> None:
    colors = {
        "capital_region": (170, 129, 76, 10),
        "mountain_region": (98, 88, 70, 14),
        "forest_region": (74, 86, 52, 10),
        "agricultural_region": (190, 172, 102, 8),
        "coastal_region": (112, 125, 91, 8),
        "floating_islands_region": (119, 113, 79, 8),
        "desert_region": (181, 139, 82, 12),
        "oasis_region": (83, 108, 65, 10),
        "underwater_region": (70, 101, 111, 10),
        "special_region": (102, 87, 78, 8),
        "spirit_core_region": (91, 83, 70, 9),
    }
    for feature in regions:
        region_type = feature.get("properties", {}).get("region_type")
        color = colors.get(region_type)
        if color is None:
            continue
        source_mask = feature_mask(image.size, feature, transform)
        try:
            hard_mask = ImageChops.multiply(source_mask, land_mask)
        finally:
            source_mask.close()
        try:
            if hard_mask.getbbox() is None:
                continue
            blurred = hard_mask.filter(ImageFilter.GaussianBlur(radius=28))
            try:
                mask = ImageChops.multiply(blurred, land_mask)
            finally:
                blurred.close()
            try:
                if mask.getbbox() is None:
                    continue
                layer = Image.new("RGBA", image.size, color)
                try:
                    _alpha_composite_masked(image, layer, mask)
                finally:
                    layer.close()
            finally:
                mask.close()
        finally:
            hard_mask.close()


def _draw_land_marks(
    image: Image.Image,
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
    style_profile: dict[str, Any] | None = None,
    *,
    full_material_preview: bool = False,
) -> int:
    """Draw varied plan-paper marks without creating a uniform noise field.

    Three EA-anchored mark families operate at different scales.  A smooth
    low-frequency density envelope keeps broad quiet and active passages, while
    each individual fibre, stipple, and crooked dash remains deterministic in
    world coordinates.  Golden input may tune only density, alpha, colour, and
    orientation entropy through ``style_profile``.
    """

    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    count = 0
    density_scale = _clamp(
        _style_parameter(style_profile, "detail_density_scale", 1.0),
        0.75,
        1.75,
    )
    alpha_scale = _clamp(
        _style_parameter(style_profile, "ink_alpha_scale", 1.0),
        0.75,
        1.35,
    )
    orientation_randomness = _clamp(
        _style_parameter(style_profile, "orientation_randomness", 1.0),
        0.55,
        1.0,
    )
    ink = _style_rgb(style_profile, "ink_tone_rgb", (75, 66, 45))
    if full_material_preview:
        # Full spatial parchment already supplies the material body.  Keep only
        # sparse short accents, eliminating the previous all-over long fibre
        # field that read as a uniform scratch overlay at 25% and 50%.
        families = (
            ("fibre", 31.0, 0.17, 3, 8),
            ("stipple", 12.0, 0.19, 0, 2),
            ("crooked-dash", 38.0, 0.14, 4, 10),
        )
        alpha_scale *= 0.56
    else:
        families = (
            ("macro-fibre", 45.0, 0.86, 14, 32),
            ("fibre", 15.0, 0.46, 4, 12),
            ("stipple", 9.0, 0.28, 0, 3),
            ("crooked-dash", 24.0, 0.52, 7, 18),
        )
    for family, cell_world, base_probability, minimum_length, maximum_length in families:
        for _, _, world_x, world_y, digest in iter_anchored_grid(
            transform,
            cell_world=cell_world,
            namespace=f"land-{family}-v4",
            seed=seed,
        ):
            envelope = _ea_bilinear_noise(
                world_x,
                world_y,
                cell_world=215.0,
                namespace="land-mark-density-envelope-v4",
                seed=seed,
            )
            probability = _clamp(
                base_probability
                * math.sqrt(density_scale)
                * (
                    0.70 + 0.34 * envelope
                    if family == "macro-fibre"
                    else 0.30 + 0.82 * envelope
                ),
                0.015 if full_material_preview else 0.08,
                0.48 if full_material_preview else 0.94,
            )
            if _unit(digest, 8) > probability:
                continue
            point = transform.point_fast((world_x, world_y))
            if not _mask_point(land_mask, point):
                continue
            x, y = point
            alpha_floor, alpha_range = (
                (76, 66)
                if family == "macro-fibre"
                else (45, 48)
                if family == "crooked-dash"
                else (30, 36)
            )
            alpha = round(
                (alpha_floor + _unit(digest, 12) * alpha_range) * alpha_scale
            )
            base_angle = math.tau * _unit(digest, 24)
            local_axis = math.tau * _ea_bilinear_noise(
                world_x,
                world_y,
                cell_world=170.0,
                namespace="land-mark-orientation-field-v4",
                seed=seed,
            )
            angle = local_axis + math.atan2(
                math.sin(base_angle - local_axis) * orientation_randomness,
                math.cos(base_angle - local_axis),
            )
            if family == "stipple":
                draw.point((x, y), fill=(*ink, alpha))
                if _unit(digest, 16) < 0.58:
                    offset = 1 + int(_unit(digest, 20) * maximum_length)
                    draw.point(
                        (
                            round(x + math.cos(angle) * offset),
                            round(y + math.sin(angle) * offset),
                        ),
                        fill=(*ink, max(16, alpha - 8)),
                    )
                count += 1
                continue

            length = minimum_length + int(
                _unit(digest, 20) * (maximum_length - minimum_length + 1)
            )
            dx = math.cos(angle) * length
            dy = math.sin(angle) * length
            if family in {"fibre", "macro-fibre"}:
                draw.line(
                    (round(x - dx), round(y - dy), round(x + dx), round(y + dy)),
                    fill=(*ink, alpha),
                    width=1,
                )
            else:
                bend = (-0.28 + 0.56 * _unit(digest, 28)) * length
                normal_x = -math.sin(angle) * bend
                normal_y = math.cos(angle) * bend
                draw.line(
                    (
                        (round(x - dx), round(y - dy)),
                        (round(x + normal_x), round(y + normal_y)),
                        (round(x + dx), round(y + dy)),
                    ),
                    fill=(*ink, alpha),
                    width=1,
                    joint="curve",
                )
            count += 1
    _alpha_composite_masked(image, layer, land_mask)
    layer.close()
    return count


def _inward_feathered_semantic_mask(
    parent_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
    namespace: str,
    *,
    feather_px: int,
    edge_breakup: bool,
) -> tuple[Image.Image, int]:
    """Feather a semantic mask inward and optionally chip only its interior edge.

    The returned mask is mathematically re-clipped through ``parent_mask``.
    Consequently a decorative edge can become quieter or more irregular but
    can never expand, translate, or replace canonical semantic geometry.
    """

    feather_px = max(2, int(feather_px))
    softened = parent_mask.filter(
        ImageFilter.GaussianBlur(radius=max(1.0, feather_px * 0.52))
    )
    # A normal blurred hard mask is still about half opaque exactly at its
    # polygon edge.  Remap that shoulder toward zero for every semantic crop,
    # then add stronger nonperiodic bites for forest/riparian material.  The
    # multiplication keeps every non-zero pixel inside the canonical parent.
    remapped = softened.point(
        lambda value: max(0, min(255, round((value - 105) * 1.70))),
        mode="L",
    )
    inward = ImageChops.multiply(remapped, parent_mask)
    remapped.close()
    softened.close()
    if not edge_breakup or parent_mask.getbbox() is None:
        return inward, 0

    erosion_source = parent_mask.filter(
        ImageFilter.GaussianBlur(radius=max(3.0, feather_px * 0.46))
    )
    eroded = erosion_source.point(
        lambda value: 255 if value >= 246 else 0,
        mode="L",
    )
    erosion_source.close()
    boundary = ImageChops.subtract(parent_mask, eroded)
    breakup = Image.new("L", parent_mask.size, 255)
    draw = ImageDraw.Draw(breakup)
    bites = 0
    for _, _, world_x, world_y, digest in iter_anchored_grid(
        transform,
        cell_world=14.5,
        namespace=f"semantic-interior-breakup-v1:{namespace}",
        seed=seed,
        margin_cells=2,
    ):
        point = transform.point_fast((world_x, world_y))
        if not _mask_point(boundary, point) or _unit(digest, 8) > 0.54:
            continue
        x, y = point
        radius = 7 + round(18 * _unit(digest, 12))
        vertices: list[tuple[int, int]] = []
        vertex_count = 6 + int(_unit(digest, 16) * 5)
        phase = math.tau * _unit(digest, 20)
        for index in range(vertex_count):
            angle = phase + math.tau * index / vertex_count
            radial = radius * (0.55 + 0.58 * _unit(digest, 23 + index * 2))
            vertices.append(
                (
                    round(x + math.cos(angle) * radial),
                    round(y + math.sin(angle) * radial),
                )
            )
        draw.polygon(
            vertices,
            fill=18 + round(76 * _unit(digest, 27)),
        )
        bites += 1
    breakup_soft = breakup.filter(ImageFilter.GaussianBlur(radius=1.6))
    boundary_weight = ImageChops.multiply(boundary, breakup_soft)
    irregular = ImageChops.lighter(eroded, boundary_weight)
    clipped = ImageChops.multiply(irregular, parent_mask)
    final = ImageChops.multiply(inward, clipped)
    inward.close()
    eroded.close()
    boundary.close()
    breakup.close()
    breakup_soft.close()
    boundary_weight.close()
    irregular.close()
    clipped.close()
    return final, bites


def _draw_canopy_cluster(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    digest: bytes,
    *,
    transform: SheetCanvasTransform,
    tropical: bool,
    radius_world: float | None = None,
) -> None:
    """Draw one asymmetric flat canopy patch with no circular crown or trunk."""

    is_mass = radius_world is not None
    if radius_world is None:
        radius_world = (4.0 if tropical else 3.2) + _unit(digest, 12) * (
            5.2 if tropical else 4.3
        )
    radius = max(2, transform.nominal_width_px_fast(radius_world))
    vertex_count = 7 + int(_unit(digest, 16) * 5)
    rotation = math.tau * _unit(digest, 20)
    points: list[tuple[int, int]] = []
    for index in range(vertex_count):
        angle = rotation + math.tau * index / vertex_count
        radial = 0.48 + 0.62 * _unit(digest, 23 + index * 3)
        stretch_x = 0.74 + 0.50 * _unit(digest, 2)
        stretch_y = 0.70 + 0.55 * _unit(digest, 6)
        points.append(
            (
                round(x + math.cos(angle) * radius * radial * stretch_x),
                round(y + math.sin(angle) * radius * radial * stretch_y),
            )
        )
    if is_mass:
        fill = (55, 77, 44, 64) if tropical else (70, 81, 49, 58)
        outline = (45, 58, 38, 58)
        branch_color = (45, 58, 38, 62)
    else:
        fill = (66, 86, 49, 136) if tropical else (75, 86, 52, 128)
        outline = (47, 60, 39, 188)
        branch_color = (47, 60, 39, 145)
    draw.polygon(points, fill=fill)
    draw.line((*points, points[0]), fill=outline, width=1, joint="curve")

    branch_count = 2 + int(_unit(digest, 30) * 3)
    for index in range(branch_count):
        angle = rotation + math.tau * _unit(digest, 5 + index * 7)
        length = radius * (0.38 + 0.34 * _unit(digest, 9 + index * 5))
        bend = radius * (-0.18 + 0.36 * _unit(digest, 11 + index * 5))
        end_x = x + math.cos(angle) * length
        end_y = y + math.sin(angle) * length
        normal_x = -math.sin(angle) * bend
        normal_y = math.cos(angle) * bend
        draw.line(
            (
                (x, y),
                (round((x + end_x) / 2 + normal_x), round((y + end_y) / 2 + normal_y)),
                (round(end_x), round(end_y)),
            ),
            fill=branch_color,
            width=1,
            joint="curve",
        )


def _draw_forests(
    image: Image.Image,
    features: Iterable[dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
    style_profile: dict[str, Any] | None = None,
    *,
    full_material_preview: bool = False,
) -> dict[str, int]:
    """Render connected flat forest material with fine non-symbolic detail."""

    total = 0
    temperate = 0
    tropical_count = 0
    clearings = 0
    micro_marks = 0
    edge_breakup_bites = 0
    density_scale = _clamp(
        _style_parameter(style_profile, "forest_detail_density_scale", 1.0),
        0.75,
        1.7,
    )
    alpha_scale = _clamp(
        _style_parameter(style_profile, "ink_alpha_scale", 1.0),
        0.75,
        1.35,
    )
    forest_ink = _style_rgb(style_profile, "forest_ink_rgb", (45, 58, 38))
    if full_material_preview:
        density_scale *= 0.48
    for feature in features:
        terrain_type = str(feature.get("properties", {}).get("terrain_type", ""))
        if terrain_type not in {
            "temperate_magic_forest",
            "tropical_magic_rainforest",
        }:
            continue
        tropical = terrain_type == "tropical_magic_rainforest"
        mask = ImageChops.multiply(
            feature_mask(image.size, feature, transform), land_mask
        )
        if mask.getbbox() is None:
            mask.close()
            continue
        if full_material_preview:
            soft_mask, bites = _inward_feathered_semantic_mask(
                mask,
                transform,
                seed,
                f"forest-procedural-overlay:{feature_id(feature)}",
                feather_px=18,
                edge_breakup=True,
            )
            edge_breakup_bites += bites
        else:
            softened = mask.filter(ImageFilter.GaussianBlur(radius=5))
            soft_mask = ImageChops.multiply(softened, mask)
            softened.close()
        wash = Image.new(
            "RGBA",
            image.size,
            (
                (49, 72, 40, 27) if tropical else (66, 78, 48, 24)
            )
            if full_material_preview
            else ((49, 72, 40, 88) if tropical else (66, 78, 48, 78)),
        )
        _alpha_composite_masked(image, wash, soft_mask)
        wash.close()
        if not full_material_preview:
            soft_mask.close()

        detail_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        detail_draw = ImageDraw.Draw(detail_layer)
        feature_bounds = _geometry_bbox(feature)
        for _, _, world_x, world_y, digest in iter_anchored_grid(
            transform,
            cell_world=(5.2 if tropical else 6.2) / density_scale,
            namespace=f"forest-irregular-chip-v4:{feature_id(feature)}",
            seed=seed,
            world_bounds=feature_bounds,
        ):
            envelope = _ea_bilinear_noise(
                world_x,
                world_y,
                cell_world=115.0,
                namespace=f"forest-density-envelope-v4:{feature_id(feature)}",
                seed=seed,
            )
            if _unit(digest, 8) > (0.30 + 0.38 * envelope):
                continue
            point = transform.point_fast((world_x, world_y))
            if not _mask_point(soft_mask if full_material_preview else mask, point):
                continue
            radius_x = 1 + int(_unit(digest, 12) * (4 if tropical else 3))
            radius_y = 1 + int(_unit(digest, 16) * (3 if tropical else 2))
            vertices = []
            vertex_count = 5 + int(_unit(digest, 20) * 4)
            rotation = math.tau * _unit(digest, 24)
            for index in range(vertex_count):
                angle = rotation + math.tau * index / vertex_count
                radial = 0.54 + 0.52 * _unit(digest, 2 + index * 3)
                vertices.append(
                    (
                        round(point[0] + math.cos(angle) * radius_x * radial),
                        round(point[1] + math.sin(angle) * radius_y * radial),
                    )
                )
            detail_draw.polygon(
                vertices,
                fill=(
                    *forest_ink,
                    round((64 + 58 * _unit(digest, 28)) * alpha_scale),
                ),
            )
            total += 1
            if tropical:
                tropical_count += 1
            else:
                temperate += 1

        for _, _, world_x, world_y, digest in iter_anchored_grid(
            transform,
            cell_world=(6.8 if tropical else 8.2) / density_scale,
            namespace=f"forest-curved-hachure-v4:{feature_id(feature)}",
            seed=seed,
            world_bounds=feature_bounds,
        ):
            if _unit(digest, 8) > (0.54 if tropical else 0.46):
                continue
            point = transform.point_fast((world_x, world_y))
            if not _mask_point(soft_mask if full_material_preview else mask, point):
                continue
            x, y = point
            angle = math.tau * _unit(digest, 12)
            length = 3 + int(5 * _unit(digest, 16))
            dx = math.cos(angle) * length
            dy = math.sin(angle) * length
            bend = (-0.32 + 0.64 * _unit(digest, 20)) * length
            detail_draw.line(
                (
                    (round(x - dx), round(y - dy)),
                    (
                        round(x - math.sin(angle) * bend),
                        round(y + math.cos(angle) * bend),
                    ),
                    (round(x + dx), round(y + dy)),
                ),
                fill=(*forest_ink, round(118 * alpha_scale)),
                width=1,
                joint="curve",
            )
            micro_marks += 1

        for _, _, world_x, world_y, digest in iter_anchored_grid(
            transform,
            cell_world=24.0 if tropical else 29.0,
            namespace=f"forest-irregular-gap-v4:{feature_id(feature)}",
            seed=seed,
            world_bounds=feature_bounds,
        ):
            if _unit(digest, 8) > 0.24:
                continue
            point = transform.point_fast((world_x, world_y))
            if not _mask_point(soft_mask if full_material_preview else mask, point):
                continue
            radius = 2 + int(5 * _unit(digest, 12))
            vertices = []
            vertex_count = 6 + int(_unit(digest, 16) * 4)
            for index in range(vertex_count):
                angle = (
                    math.tau * index / vertex_count
                    + 0.18 * _unit(digest, 17 + index)
                )
                radial = 0.48 + 0.58 * _unit(digest, 23 + index * 2)
                vertices.append(
                    (
                        round(point[0] + math.cos(angle) * radius * radial),
                        round(point[1] + math.sin(angle) * radius * radial),
                    )
                )
            detail_draw.polygon(vertices, fill=(181, 164, 105, 70))
            clearings += 1
        _alpha_composite_masked(
            image,
            detail_layer,
            soft_mask if full_material_preview else mask,
        )
        detail_layer.close()
        if full_material_preview:
            soft_mask.close()
        mask.close()
    return {
        "forest_canopy_masses": total,
        "forest_canopy_clusters": total,
        "temperate_forest_clusters": temperate,
        "tropical_forest_clusters": tropical_count,
        "forest_density_micro_marks": micro_marks,
        "forest_clearings": clearings,
        "forest_interior_edge_breakup_bites": edge_breakup_bites,
        "round_canopy_stamps": 0,
        "tree_trunks": 0,
        "directional_highlights": 0,
    }


def _iter_world_lines(geometry: dict[str, Any]) -> Iterator[list[tuple[float, float]]]:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "LineString":
        values = [coordinates]
    elif kind == "MultiLineString":
        values = coordinates
    else:
        return
    if not isinstance(values, list):
        return
    for value in values:
        if isinstance(value, list) and len(value) >= 2:
            yield [(float(point[0]), float(point[1])) for point in value]


def _nearest_segment(
    point: tuple[float, float], lines: Sequence[Sequence[tuple[float, float]]]
) -> tuple[float, float]:
    best_distance = math.inf
    best_angle = 0.0
    px, py = point
    for line in lines:
        for start, end in zip(line, line[1:]):
            x1, y1 = start
            x2, y2 = end
            dx = x2 - x1
            dy = y2 - y1
            length_squared = dx * dx + dy * dy
            if length_squared == 0:
                continue
            fraction = max(
                0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_squared)
            )
            nearest_x = x1 + fraction * dx
            nearest_y = y1 + fraction * dy
            distance = math.hypot(px - nearest_x, py - nearest_y)
            if distance < best_distance:
                best_distance = distance
                best_angle = math.atan2(dy, dx)
    return best_distance, best_angle


def _draw_irregular_rock(
    draw: ImageDraw.ImageDraw, x: int, y: int, digest: bytes
) -> None:
    radius = 2 + int(_unit(digest, 20) * 4)
    points = []
    count = 5 + int(_unit(digest, 24) * 3)
    for index in range(count):
        angle = math.tau * index / count + (_unit(digest, index * 3) - 0.5) * 0.35
        scale = 0.65 + _unit(digest, index * 5 + 2) * 0.55
        points.append(
            (
                round(x + math.cos(angle) * radius * scale),
                round(y + math.sin(angle) * radius * scale),
            )
        )
    points.append(points[0])
    draw.line(points, fill=(70, 57, 43, 155), width=1, joint="curve")


def _terrain_feature_mask(
    image_size: tuple[int, int],
    feature: dict[str, Any],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
) -> Image.Image:
    terrain_type = feature.get("properties", {}).get("terrain_type")
    geometry_type = feature.get("geometry", {}).get("type")
    if geometry_type in {"Polygon", "MultiPolygon"}:
        return ImageChops.multiply(
            feature_mask(image_size, feature, transform), land_mask
        )
    nominal_width = float(feature.get("properties", {}).get("nominal_width", 180))
    axis_mask = Image.new("L", image_size, 0)
    draw = ImageDraw.Draw(axis_mask)
    for path in line_paths(feature.get("geometry", {}), transform):
        draw.line(
            path,
            fill=255,
            width=transform.nominal_width_px(nominal_width),
            joint="curve",
        )
    clipped = ImageChops.multiply(axis_mask, land_mask)
    axis_mask.close()
    if terrain_type not in {"mountain_axis", "gorge_axis"}:
        clipped.close()
        return Image.new("L", image_size, 0)
    return clipped


def _draw_flat_terrain_mark(
    draw: ImageDraw.ImageDraw,
    point: tuple[int, int],
    digest: bytes,
    terrain_type: str,
    transform: SheetCanvasTransform,
) -> None:
    x, y = point
    angle = math.tau * _unit(digest, 12)
    length_world = 1.8 + 4.8 * _unit(digest, 16)
    length = max(1, transform.nominal_width_px_fast(length_world))
    dx = math.cos(angle) * length
    dy = math.sin(angle) * length
    normal_x = -math.sin(angle)
    normal_y = math.cos(angle)
    palettes = {
        "temperate_plains": (94, 83, 53, 96),
        "hot_desert": (116, 79, 48, 125),
        "volcanic_land": (79, 55, 47, 155),
        "arcane_highlands": (75, 65, 58, 128),
        "tundra_permafrost": (80, 91, 87, 122),
        "floating_island_chain": (72, 69, 48, 118),
    }
    color = palettes[terrain_type]
    if terrain_type == "temperate_plains":
        draw.line(
            (round(x - dx), round(y - dy), round(x + dx), round(y + dy)),
            fill=color,
            width=1,
        )
        if _unit(digest, 20) < 0.46:
            offset = 2 + int(_unit(digest, 24) * 3)
            draw.line(
                (
                    round(x - dx + normal_x * offset),
                    round(y - dy + normal_y * offset),
                    round(x + dx * 0.55 + normal_x * offset),
                    round(y + dy * 0.55 + normal_y * offset),
                ),
                fill=color,
                width=1,
            )
    elif terrain_type == "hot_desert":
        bend = max(1, length // 4)
        draw.line(
            (
                (round(x - dx), round(y - dy)),
                (round(x - normal_x * bend), round(y - normal_y * bend)),
                (round(x + dx), round(y + dy)),
            ),
            fill=color,
            width=1,
            joint="curve",
        )
    elif terrain_type in {"volcanic_land", "tundra_permafrost"}:
        mid_x = round(x + normal_x * length * 0.18)
        mid_y = round(y + normal_y * length * 0.18)
        draw.line(
            (
                (round(x - dx), round(y - dy)),
                (mid_x, mid_y),
                (round(x + dx), round(y + dy)),
            ),
            fill=color,
            width=1,
        )
        branch = length * (0.35 + _unit(digest, 20) * 0.3)
        draw.line(
            (
                mid_x,
                mid_y,
                round(mid_x + normal_x * branch),
                round(mid_y + normal_y * branch),
            ),
            fill=color,
            width=1,
        )
    elif terrain_type == "arcane_highlands":
        gap = max(2, length // 3)
        draw.line(
            (round(x - dx), round(y - dy), round(x - dx * 0.2), round(y - dy * 0.2)),
            fill=color,
            width=1,
        )
        draw.line(
            (
                round(x + dx * 0.2 + normal_x * gap),
                round(y + dy * 0.2 + normal_y * gap),
                round(x + dx + normal_x * gap),
                round(y + dy + normal_y * gap),
            ),
            fill=color,
            width=1,
        )
    else:
        draw.line(
            (
                round(x - dx * 0.65),
                round(y - dy * 0.65),
                round(x + dx * 0.65),
                round(y + dy * 0.65),
            ),
            fill=color,
            width=1,
        )
        draw.point((x + int(normal_x * 2), y + int(normal_y * 2)), fill=color)


def _draw_polygon_terrains(
    image: Image.Image,
    features: Iterable[dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
) -> dict[str, int]:
    supported = {
        "temperate_plains": (17.0, (142, 132, 78, 20), 0.52),
        "hot_desert": (13.0, (177, 127, 70, 28), 0.62),
        "volcanic_land": (11.5, (92, 63, 54, 38), 0.64),
        "arcane_highlands": (12.5, (91, 80, 68, 27), 0.58),
        "tundra_permafrost": (12.0, (151, 165, 157, 30), 0.59),
        "floating_island_chain": (10.5, (132, 117, 72, 24), 0.52),
    }
    counts = {terrain_type: 0 for terrain_type in supported}
    for feature in features:
        terrain_type = str(feature.get("properties", {}).get("terrain_type", ""))
        if terrain_type not in supported:
            continue
        geometry_type = feature.get("geometry", {}).get("type")
        if geometry_type not in {"Polygon", "MultiPolygon"}:
            continue
        mask = _terrain_feature_mask(image.size, feature, land_mask, transform)
        if mask.getbbox() is None:
            mask.close()
            continue
        cell_world, wash_color, density = supported[terrain_type]
        wash = Image.new("RGBA", image.size, wash_color)
        _alpha_composite_masked(image, wash, mask)
        wash.close()
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        namespace = f"terrain-plan-v2:{terrain_type}:{feature_id(feature)}"
        feature_bounds = _geometry_bbox(feature)
        for _, _, world_x, world_y, digest in iter_anchored_grid(
            transform,
            cell_world=cell_world,
            namespace=namespace,
            seed=seed,
            world_bounds=feature_bounds,
        ):
            if _unit(digest, 8) > density:
                continue
            point = transform.point_fast((world_x, world_y))
            if not _mask_point(mask, point):
                continue
            _draw_flat_terrain_mark(draw, point, digest, terrain_type, transform)
            counts[terrain_type] += 1
        _alpha_composite_masked(image, layer, mask)
        layer.close()
        mask.close()
    return {f"terrain_{terrain_type}": count for terrain_type, count in counts.items()}


def _draw_agricultural_regions(
    image: Image.Image,
    features: Iterable[dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
) -> int:
    total = 0
    for feature in features:
        if feature.get("properties", {}).get("region_type") != AGRICULTURAL_REGION_TYPE:
            continue
        mask = ImageChops.multiply(
            feature_mask(image.size, feature, transform), land_mask
        )
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        namespace = f"agricultural-row-v2:{feature_id(feature)}"
        feature_bounds = _geometry_bbox(feature)
        for _, _, world_x, world_y, digest in iter_anchored_grid(
            transform,
            cell_world=14.0,
            namespace=namespace,
            seed=seed,
            world_bounds=feature_bounds,
        ):
            if _unit(digest, 8) > 0.57:
                continue
            point = transform.point_fast((world_x, world_y))
            if not _mask_point(mask, point):
                continue
            x, y = point
            length = transform.nominal_width_px_fast(4.0 + 5.0 * _unit(digest, 12))
            offset = max(2, transform.nominal_width_px_fast(1.4))
            angle = (math.pi / 12) * int(_unit(digest, 16) * 6)
            dx = math.cos(angle) * length
            dy = math.sin(angle) * length
            nx = -math.sin(angle) * offset
            ny = math.cos(angle) * offset
            for side in (-1, 1):
                draw.line(
                    (
                        round(x - dx + nx * side),
                        round(y - dy + ny * side),
                        round(x + dx + nx * side),
                        round(y + dy + ny * side),
                    ),
                    fill=(126, 96, 51, 91),
                    width=1,
                )
            total += 1
        _alpha_composite_masked(image, layer, mask)
        layer.close()
        mask.close()
    return total


def _material_atlas_record(
    material_atlas_path: Path = DEFAULT_MATERIAL_ATLAS,
    *,
    transfer_mode: str = RESIDUAL_MATERIAL_MODE,
) -> dict[str, Any]:
    """Validate the reviewed atlas and its exact original-resolution safe crops."""

    if transfer_mode not in {
        RESIDUAL_MATERIAL_MODE,
        FULL_SPATIAL_MATERIAL_MODE,
    }:
        raise ReviewedMasterError(f"unknown material transfer mode: {transfer_mode}")
    full_spatial = transfer_mode == FULL_SPATIAL_MATERIAL_MODE

    material_atlas_path = material_atlas_path.resolve()
    if not material_atlas_path.is_file():
        raise ReviewedMasterError(f"material atlas does not exist: {material_atlas_path}")
    atlas_sha256 = sha256_file(material_atlas_path)
    if atlas_sha256 != MATERIAL_ATLAS_SHA256:
        raise ReviewedMasterError(
            "material atlas SHA-256 mismatch: "
            f"expected={MATERIAL_ATLAS_SHA256}, actual={atlas_sha256}"
        )
    crop_records: dict[str, dict[str, Any]] = {}
    with Image.open(material_atlas_path) as atlas:
        atlas.load()
        if atlas.size != MATERIAL_ATLAS_SIZE:
            raise ReviewedMasterError(
                "material atlas dimensions changed: "
                f"expected={MATERIAL_ATLAS_SIZE}, actual={atlas.size}"
            )
        atlas_rgb = atlas.convert("RGB")
        try:
            for crop_name, spec in MATERIAL_ATLAS_CROPS.items():
                rect = tuple(int(value) for value in spec["rect_px"])
                crop = atlas_rgb.crop(rect)
                try:
                    raw_sha256 = hashlib.sha256(crop.tobytes()).hexdigest()
                    if raw_sha256 != spec["raw_rgb_sha256"]:
                        raise ReviewedMasterError(
                            f"material atlas safe crop changed: {crop_name}; "
                            f"expected={spec['raw_rgb_sha256']}, actual={raw_sha256}"
                        )
                    crop_records[crop_name] = {
                        "rect_px": list(rect),
                        "width": crop.width,
                        "height": crop.height,
                        "mode": "RGB",
                        "raw_rgb_sha256": raw_sha256,
                        "usage_masks": list(spec["usage_masks"]),
                        "frequency_transfer": (
                            "full-approved-spatial-material"
                            if full_spatial
                            else "signed-rgb-high-pass-only"
                        ),
                        "residual_construction": (
                            "source RGB minus Gaussian low-pass; each channel "
                            "explicitly recentered to zero arithmetic mean"
                        ),
                        "zero_mean_per_channel": True,
                        "zero_mean_tolerance_levels": 0.51,
                        "application_mode": "small-amplitude signed additive",
                        "strength": float(spec["strength"]),
                        "strength_limit": float(spec["strength_limit"]),
                        "semantic_mask_feather_px": int(spec["feather_px"]),
                        "maximum_alpha": int(spec["max_alpha"]),
                    }
                    if full_spatial:
                        quilt = FULL_SPATIAL_QUILT[crop_name]
                        crop_records[crop_name].update(
                            {
                                "residual_construction": None,
                                "zero_mean_per_channel": False,
                                "application_mode": FULL_SPATIAL_MATERIAL_MODE,
                                "strength": None,
                                "strength_limit": None,
                                "semantic_mask_feather_px": int(
                                    quilt["semantic_feather_px"]
                                ),
                                "maximum_alpha": int(quilt["maximum_alpha"]),
                                "patch_world": float(quilt["patch_world"]),
                                "stride_world": float(quilt["stride_world"]),
                                "low_frequency_material_retained": True,
                                "whole_crop_semantic_scope_preserved": True,
                            }
                        )
                finally:
                    crop.close()
        finally:
            atlas_rgb.close()
    return {
        "status": "locked",
        "path": _repo_path(material_atlas_path),
        "sha256": atlas_sha256,
        "width": MATERIAL_ATLAS_SIZE[0],
        "height": MATERIAL_ATLAS_SIZE[1],
        "sample_resolution": "original pixels; no generated semantic geometry copied",
        "safe_crops": crop_records,
        "excluded_material": list(MATERIAL_ATLAS_EXCLUSIONS),
        "transfer_mode": transfer_mode,
        "transfer_filter": (
            {
                "frequency_band": "full-approved-spatial",
                "operation": (
                    "large overlapping source-window quilt, luma-normalised to "
                    "Golden style tokens"
                ),
                "local_blur_subtraction": False,
                "explicit_zero_mean_per_channel": False,
                "signed_residual_additive_application": False,
                "low_frequency_semantic_shapes_retained": True,
                "roads_rivers_coasts_cities_buildings_transferred": False,
            }
            if full_spatial
            else {
                "frequency_band": "high",
                "operation": "RGB minus Gaussian low-pass, then zero-mean recenter",
                "local_blur_subtraction": True,
                "explicit_zero_mean_per_channel": True,
                "signed_residual_additive_application": True,
                "low_frequency_semantic_shapes_retained": False,
                "roads_rivers_coasts_cities_buildings_transferred": False,
            }
        ),
        "placement": (
            {
                "coordinate_reference_system": "EA-WORLD-1",
                "sheet_id_in_hash": False,
                "operations": [
                    "varied approved source window",
                    "quarter-turn rotation",
                    "horizontal reflection",
                    "nonperiodic output scale",
                    "overlap feather",
                ],
                "opacity": "crop-specific 36-to-69-percent patch alpha before overlap",
                "semantic_mask_feather_px_range": [14, 34],
                "deterministic_low_frequency_strength_noise": False,
                "deterministic_nonperiodic_source_selection": True,
                "canonical_land_water_transport_reclip": True,
                "settlement_geometry_drawn_after_material_without_coordinate_change": True,
                "parent_mask_outside_pixels_modified": 0,
            }
            if full_spatial
            else {
                "coordinate_reference_system": "EA-WORLD-1",
                "sheet_id_in_hash": False,
                "operations": [
                    "crop",
                    "quarter-turn rotation",
                    "horizontal reflection",
                ],
                "opacity": "3.5-to-10-percent signed residual",
                "semantic_mask_feather_px_range": [64, 160],
                "deterministic_low_frequency_strength_noise": True,
                "canonical_land_water_transport_reclip": True,
                "parent_mask_outside_pixels_modified": 0,
            }
        ),
        "renderer_sha256": sha256_file(Path(__file__)),
    }


def _global_neutral_material_record(
    material_path: Path = DEFAULT_GLOBAL_NEUTRAL_MATERIAL,
) -> dict[str, Any]:
    """Hash-lock the rejected raster as a grayscale, preview-only band source."""

    resolved = material_path.resolve()
    if not resolved.is_file():
        raise ReviewedMasterError(
            f"global neutral material does not exist: {resolved}"
        )
    actual_sha256 = sha256_file(resolved)
    if actual_sha256 != GLOBAL_NEUTRAL_MATERIAL_SHA256:
        raise ReviewedMasterError(
            "global neutral material SHA-256 mismatch: "
            f"expected={GLOBAL_NEUTRAL_MATERIAL_SHA256}, actual={actual_sha256}"
        )
    try:
        with Image.open(resolved) as opened:
            opened.load()
            if opened.size != GLOBAL_NEUTRAL_MATERIAL_SIZE:
                raise ReviewedMasterError(
                    "global neutral material dimensions changed: "
                    f"expected={GLOBAL_NEUTRAL_MATERIAL_SIZE}, actual={opened.size}"
                )
            if opened.mode != "RGB":
                raise ReviewedMasterError(
                    "global neutral material mode changed: "
                    f"expected=RGB, actual={opened.mode}"
                )
    except OSError as exc:
        raise ReviewedMasterError(
            f"could not decode global neutral material {resolved}: {exc}"
        ) from exc

    return {
        "status": "hash-locked-rejected-source-preview-only",
        "path": _repo_path(resolved),
        "sha256": actual_sha256,
        "width": GLOBAL_NEUTRAL_MATERIAL_SIZE[0],
        "height": GLOBAL_NEUTRAL_MATERIAL_SIZE[1],
        "mode": "RGB",
        "source_review_status": "rejected",
        "source_pixels_copied_as_rgb": 0,
        "source_semantic_geometry_transferred": False,
        "source_broad_tone_transferred": False,
        "transfer_mode": GLOBAL_NEUTRAL_BANDPASS_MODE,
        "promotion_eligible": False,
        "filter": {
            "colour_conversion": "grayscale luma only",
            "fine": "source minus GaussianBlur(1.5px)",
            "mid": "GaussianBlur(1.5px) minus GaussianBlur(18px)",
            "broad_source_band": "discarded",
            "fine_weight": GLOBAL_NEUTRAL_BANDPASS["fine_weight"],
            "mid_weight": GLOBAL_NEUTRAL_BANDPASS["mid_weight"],
            "clamp_luma_levels": GLOBAL_NEUTRAL_BANDPASS[
                "bandpass_clamp_luma_levels"
            ],
            "output_channels": "same signed luma delta added to R, G, and B",
        },
        "placement": {
            "coordinate_reference_system": "EA-WORLD-1",
            "sheet_id_in_hash": False,
            "semantic_usage_masks": 0,
            "canonical_land_mask_only": True,
            "patch_world": GLOBAL_NEUTRAL_BANDPASS["patch_world"],
            "stride_world": GLOBAL_NEUTRAL_BANDPASS["stride_world"],
            "source_fraction": list(GLOBAL_NEUTRAL_BANDPASS["source_fraction"]),
            "raised_cosine_quilting": True,
            "broad_noise": list(GLOBAL_NEUTRAL_BANDPASS["broad_noise"]),
            "maximum_broad_noise_luma_levels": GLOBAL_NEUTRAL_BANDPASS[
                "maximum_broad_noise_luma_levels"
            ],
            "canonical_water_and_line_guard_reclip": True,
        },
        "renderer_sha256": sha256_file(Path(__file__)),
    }


def _integer_zero_mean(values: Sequence[int]) -> list[int]:
    """Return bounded signed integers whose arithmetic mean is exactly zero."""

    if not values:
        return []
    maximum = max(abs(value) for value in values)
    scale = min(1.0, 110.0 / maximum) if maximum else 1.0
    centered = [round(value * scale) for value in values]
    quotient = math.trunc(sum(centered) / len(centered))
    centered = [max(-120, min(120, value - quotient)) for value in centered]
    remaining = sum(centered)
    direction = 1 if remaining > 0 else -1
    while remaining:
        changed = 0
        for index, value in enumerate(centered):
            if not remaining:
                break
            if direction > 0 and value > -120:
                centered[index] -= 1
                remaining -= 1
                changed += 1
            elif direction < 0 and value < 120:
                centered[index] += 1
                remaining += 1
                changed += 1
        if not changed:
            raise ReviewedMasterError("could not zero-center atlas residual")
    return centered


def _zero_mean_high_frequency_residual(
    crop: Image.Image,
    *,
    low_pass_radius: float = 3.2,
) -> tuple[Image.Image, dict[str, Any]]:
    """Subtract a Gaussian low-pass and zero-center every signed RGB channel.

    The returned RGB image is a neutral residual field: 128 means no change,
    values below/above 128 are negative/positive high-frequency differences.
    No source low-frequency colour is present in the returned pixels.
    """

    source = crop.convert("RGB")
    low_pass = source.filter(ImageFilter.GaussianBlur(radius=low_pass_radius))
    source_bytes = source.tobytes()
    low_pass_bytes = low_pass.tobytes()
    pixel_count = source.width * source.height
    encoded = bytearray(len(source_bytes))
    raw_means: list[float] = []
    post_means: list[float] = []
    maxima: list[int] = []
    for channel in range(3):
        raw = [
            source_bytes[offset] - low_pass_bytes[offset]
            for offset in range(channel, len(source_bytes), 3)
        ]
        raw_means.append(sum(raw) / pixel_count)
        centered = _integer_zero_mean(raw)
        post_means.append(sum(centered) / pixel_count)
        maxima.append(max((abs(value) for value in centered), default=0))
        encoded[channel::3] = bytes(128 + value for value in centered)
    residual = Image.frombytes("RGB", source.size, bytes(encoded))
    source.close()
    low_pass.close()
    return residual, {
        "operation": "source RGB minus Gaussian low-pass",
        "low_pass_radius_px": low_pass_radius,
        "raw_residual_mean_rgb_levels": [round(value, 6) for value in raw_means],
        "post_zero_mean_rgb_levels": [round(value, 6) for value in post_means],
        "maximum_absolute_residual_rgb_levels": maxima,
        "explicit_zero_mean_per_channel": all(
            abs(value) <= 1e-12 for value in post_means
        ),
        "source_low_frequency_colour_copied": False,
    }


def _recenter_weighted_residual(
    residual: Image.Image,
    weight: Image.Image,
) -> tuple[Image.Image, list[float]]:
    """Keep a resized residual neutral under its feather alpha weights."""

    means = ImageStat.Stat(residual, weight).mean
    bands = residual.split()
    shifted_bands: list[Image.Image] = []
    try:
        for band, mean in zip(bands, means):
            shift = round(128.0 - mean)
            shifted_bands.append(
                band.point(
                    lambda value, delta=shift: max(0, min(255, value + delta)),
                    mode="L",
                )
            )
        centered = Image.merge("RGB", shifted_bands)
    finally:
        for band in bands:
            band.close()
        for band in shifted_bands:
            band.close()
    post = [value - 128.0 for value in ImageStat.Stat(centered, weight).mean]
    return centered, post


def _material_patch_variants(
    high_frequency_crop: Image.Image,
    *,
    patch_px: int,
) -> tuple[dict[tuple[int, bool], Image.Image], float]:
    """Prepare deterministic crop/quarter-turn/reflect variants with soft edges."""

    patch_px = max(8, patch_px)
    pad = max(3, round(patch_px * 0.14))
    feather = Image.new("L", (patch_px, patch_px), 0)
    ImageDraw.Draw(feather).rounded_rectangle(
        (pad, pad, patch_px - pad - 1, patch_px - pad - 1),
        radius=max(2, pad // 2),
        fill=255,
    )
    feather = feather.filter(ImageFilter.GaussianBlur(radius=max(2, pad * 0.62)))
    variants: dict[tuple[int, bool], Image.Image] = {}
    maximum_weighted_mean = 0.0
    for quarter_turn in range(4):
        rotated = high_frequency_crop.rotate(quarter_turn * 90, expand=True)
        for reflected in (False, True):
            oriented = ImageOps.mirror(rotated) if reflected else rotated.copy()
            fitted = ImageOps.fit(
                oriented,
                (patch_px, patch_px),
                method=Image.Resampling.LANCZOS,
            )
            centered, weighted_means = _recenter_weighted_residual(fitted, feather)
            maximum_weighted_mean = max(
                maximum_weighted_mean,
                *(abs(value) for value in weighted_means),
            )
            variant = centered.convert("RGBA")
            variant.putalpha(feather)
            variants[(quarter_turn, reflected)] = variant
            centered.close()
            fitted.close()
            oriented.close()
        rotated.close()
    feather.close()
    return variants, maximum_weighted_mean


def _mix_rgb(
    first: tuple[int, int, int],
    second: tuple[int, int, int],
    second_weight: float,
) -> tuple[int, int, int]:
    second_weight = _clamp(second_weight, 0.0, 1.0)
    return tuple(
        round(left * (1.0 - second_weight) + right * second_weight)
        for left, right in zip(first, second)
    )


def _full_spatial_material_palette(
    crop_name: str,
    style_profile: dict[str, Any] | None,
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Return semantic shadow/highlight tokens derived from the Golden profile."""

    land = _style_rgb(style_profile, "land_tone_rgb", (193, 173, 118))
    ink = _style_rgb(style_profile, "ink_tone_rgb", (75, 66, 45))
    forest = _style_rgb(style_profile, "forest_ink_rgb", (45, 58, 38))
    if crop_name == "connected_forest":
        return _mix_rgb(forest, ink, 0.22), _mix_rgb(land, forest, 0.66)
    if crop_name == "cultivated_hatching":
        return _mix_rgb(ink, (92, 71, 40), 0.44), _mix_rgb(
            land, (174, 143, 78), 0.50
        )
    if crop_name == "wetland":
        return (43, 68, 65), _mix_rgb(land, (112, 137, 112), 0.62)
    if crop_name == "flat_rock_hachure":
        return _mix_rgb(ink, (57, 55, 50), 0.52), _mix_rgb(
            land, (142, 130, 103), 0.58
        )
    if crop_name == "neutral_parchment":
        return _mix_rgb(ink, land, 0.43), _mix_rgb(
            land, (213, 194, 143), 0.48
        )
    raise ReviewedMasterError(f"unknown full spatial material crop: {crop_name}")


def _normalise_full_spatial_crop(
    crop: Image.Image,
    crop_name: str,
    style_profile: dict[str, Any] | None,
) -> tuple[Image.Image, dict[str, Any]]:
    """Preserve the complete approved crop while mapping it to style tokens."""

    source = crop.convert("RGB")
    gray = ImageOps.grayscale(source)
    normalised = ImageOps.autocontrast(gray, cutoff=(0.5, 0.5))
    if crop_name == "neutral_parchment":
        # The 32px neutral crop is approved as grain, not as a dark motif.
        # Compress its tonal range before quilting so upscaling cannot create
        # conspicuous islands or a checkerboard.
        neutral = Image.new("L", normalised.size, 128)
        compressed = Image.blend(neutral, normalised, 0.42)
        neutral.close()
        normalised.close()
        normalised = compressed
    shadow, highlight = _full_spatial_material_palette(crop_name, style_profile)
    colourised = ImageOps.colorize(
        normalised,
        black=shadow,
        white=highlight,
    )
    source_mean = [round(value, 6) for value in ImageStat.Stat(source).mean]
    output_mean = [round(value, 6) for value in ImageStat.Stat(colourised).mean]
    source.close()
    gray.close()
    normalised.close()
    return colourised, {
        "operation": "full approved spatial crop, luma-normalised to Golden style tokens",
        "source_low_frequency_material_retained": True,
        "source_rgb_mean": source_mean,
        "normalised_rgb_mean": output_mean,
        "shadow_rgb": list(shadow),
        "highlight_rgb": list(highlight),
        "whole_crop_semantic_scope_preserved": True,
    }


def _full_spatial_quilt_patch(
    material: Image.Image,
    digest: bytes,
    *,
    base_patch_px: int,
    crop_name: str,
) -> tuple[Image.Image, dict[str, Any]]:
    """Select, orient, scale and feather one nonperiodic approved source window."""

    spec = FULL_SPATIAL_QUILT[crop_name]
    fraction_min, fraction_max = spec["source_fraction"]
    fraction = fraction_min + (fraction_max - fraction_min) * _unit(digest, 8)
    minimum_side = min(material.size)
    source_side = max(8, min(minimum_side, round(minimum_side * fraction)))
    aspect = 0.84 + 0.32 * _unit(digest, 12)
    source_width = min(material.width, max(8, round(source_side * aspect)))
    source_height = min(material.height, max(8, round(source_side / aspect)))
    left_limit = max(0, material.width - source_width)
    top_limit = max(0, material.height - source_height)
    left = round(left_limit * _unit(digest, 16))
    top = round(top_limit * _unit(digest, 20))
    source_box = (left, top, left + source_width, top + source_height)
    window = material.crop(source_box)
    quarter_turn = int(_unit(digest, 24) * 4) % 4
    rotated = window.rotate(quarter_turn * 90, expand=True)
    reflected = _unit(digest, 28) < 0.5
    oriented = ImageOps.mirror(rotated) if reflected else rotated.copy()
    scale_min, scale_max = spec["output_scale"]
    output_scale = scale_min + (scale_max - scale_min) * _unit(digest, 1)
    patch_px = max(24, round(base_patch_px * output_scale))
    fitted = ImageOps.fit(
        oriented,
        (patch_px, patch_px),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    patch = fitted.convert("RGBA")
    maximum_alpha = int(spec["maximum_alpha"])
    maximum_alpha = round(maximum_alpha * (0.84 + 0.16 * _unit(digest, 5)))
    matte = Image.new("L", (patch_px, patch_px), 0)
    matte_draw = ImageDraw.Draw(matte)
    pad = max(2, round(patch_px * (0.08 + 0.04 * _unit(digest, 9))))
    matte_draw.rounded_rectangle(
        (pad, pad, patch_px - pad - 1, patch_px - pad - 1),
        radius=max(4, round(patch_px * 0.19)),
        fill=maximum_alpha,
    )
    blurred_matte = matte.filter(
        ImageFilter.GaussianBlur(radius=max(4.0, patch_px * 0.115))
    )
    patch.putalpha(blurred_matte)
    window_signature = hashlib.sha256(
        (
            f"{source_box}:{quarter_turn}:{reflected}:{patch_px}:"
            f"{maximum_alpha}"
        ).encode("ascii")
    ).hexdigest()
    window.close()
    rotated.close()
    oriented.close()
    fitted.close()
    matte.close()
    blurred_matte.close()
    return patch, {
        "source_box_px": list(source_box),
        "quarter_turn_degrees": quarter_turn * 90,
        "horizontal_reflection": reflected,
        "output_scale": round(output_scale, 6),
        "output_size_px": patch_px,
        "maximum_alpha": maximum_alpha,
        "window_transform_sha256": window_signature,
    }


def _apply_atlas_crop_full_spatial_material(
    image: Image.Image,
    parent_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
    crop_name: str,
    crop: Image.Image,
    *,
    canonical_clip: Image.Image,
    style_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """Quilt full approved spatial material without changing canonical masks."""

    parent_bbox = parent_mask.getbbox()
    if parent_bbox is None:
        return {
            "patches": 0,
            "unique_source_window_transforms": 0,
            "quarter_turns_used": [],
            "horizontal_reflections_used": [],
            "outside_parent_pixel_changes": 0,
            "semantic_boundary_contrast": None,
            "normalisation": None,
            "interior_edge_breakup_bites": 0,
        }
    spec = FULL_SPATIAL_QUILT[crop_name]
    material, normalisation = _normalise_full_spatial_crop(
        crop,
        crop_name,
        style_profile,
    )
    semantic_mask, edge_bites = _inward_feathered_semantic_mask(
        parent_mask,
        transform,
        seed,
        f"atlas-full-spatial:{crop_name}",
        feather_px=int(spec["semantic_feather_px"]),
        edge_breakup=bool(spec["edge_breakup"]),
    )
    clipped_semantic = ImageChops.multiply(semantic_mask, canonical_clip)
    field = Image.new("RGBA", image.size, (0, 0, 0, 0))
    before = image.convert("RGB")
    base_patch_px = transform.nominal_width_px_fast(float(spec["patch_world"]))
    patches = 0
    turns: set[int] = set()
    reflections: set[bool] = set()
    window_signatures: set[str] = set()
    source_window_examples: list[dict[str, Any]] = []
    bbox = clipped_semantic.getbbox()
    try:
        for _, _, world_x, world_y, digest in iter_anchored_grid(
            transform,
            cell_world=float(spec["stride_world"]),
            namespace=f"atlas-full-spatial-quilt-v1:{crop_name}",
            seed=seed,
            margin_cells=4,
        ):
            center_x, center_y = transform.point_fast((world_x, world_y))
            maximum_patch = round(base_patch_px * float(spec["output_scale"][1]))
            test_box = (
                center_x - maximum_patch // 2,
                center_y - maximum_patch // 2,
                center_x + maximum_patch // 2 + 1,
                center_y + maximum_patch // 2 + 1,
            )
            if bbox is None or (
                test_box[2] <= bbox[0]
                or test_box[0] >= bbox[2]
                or test_box[3] <= bbox[1]
                or test_box[1] >= bbox[3]
            ):
                continue
            patch, record = _full_spatial_quilt_patch(
                material,
                digest,
                base_patch_px=base_patch_px,
                crop_name=crop_name,
            )
            try:
                left = center_x - patch.width // 2
                top = center_y - patch.height // 2
                field.alpha_composite(patch, dest=(left, top))
            finally:
                patch.close()
            patches += 1
            turns.add(int(record["quarter_turn_degrees"]))
            reflections.add(bool(record["horizontal_reflection"]))
            window_signatures.add(str(record["window_transform_sha256"]))
            if len(source_window_examples) < 12:
                source_window_examples.append(record)

        _alpha_composite_masked(image, field, clipped_semantic)
        after = image.convert("RGB")
        boundary = _semantic_boundary_contrast(
            before,
            after,
            parent_mask,
            canonical_clip,
        )
        difference = ImageChops.difference(before, after).convert("L")
        inverse_parent = ImageOps.invert(parent_mask)
        outside_parent = ImageChops.multiply(difference, inverse_parent)
        outside_changes = 0 if outside_parent.getbbox() is None else 1
        after.close()
        difference.close()
        inverse_parent.close()
        outside_parent.close()
    finally:
        material.close()
        semantic_mask.close()
        clipped_semantic.close()
        field.close()
        before.close()
    return {
        "patches": patches,
        "unique_source_window_transforms": len(window_signatures),
        "quarter_turns_used": sorted(turns),
        "horizontal_reflections_used": sorted(reflections),
        "outside_parent_pixel_changes": outside_changes,
        "normalisation": normalisation,
        "source_window_examples": source_window_examples,
        "interior_edge_breakup_bites": edge_bites,
        "application": {
            "mode": FULL_SPATIAL_MATERIAL_MODE,
            "overlap_blend": "raised-cosine-like Gaussian feathered alpha quilt",
            "patch_world": float(spec["patch_world"]),
            "stride_world": float(spec["stride_world"]),
            "maximum_alpha": int(spec["maximum_alpha"]),
            "semantic_mask_feather_px": int(spec["semantic_feather_px"]),
            "semantic_mask_reclipped_inward": True,
            "canonical_clip_reapplied": True,
            "sheet_id_in_phase_hash": False,
        },
        "semantic_boundary_contrast": boundary,
    }


def _exactly_recenter_luma(
    image: Image.Image,
    *,
    minimum: int,
    maximum: int,
    namespace: str,
) -> tuple[Image.Image, dict[str, Any]]:
    """Recenter an L raster to exactly 128 without a visible correction block."""

    source = image.convert("L")
    values = bytearray(source.tobytes())
    source.close()
    count = len(values)
    if not count:
        return Image.new("L", image.size, 128), {
            "pre_mean_luma_levels": 0.0,
            "post_mean_luma_levels": 0.0,
            "adjusted_pixels": 0,
        }
    original_sum = sum(values)
    remaining = 128 * count - original_sum
    adjusted = 0
    if remaining:
        direction = 1 if remaining > 0 else -1
        digest = hashlib.sha256(namespace.encode("utf-8")).digest()
        index = int.from_bytes(digest[:8], "big") % count
        step = (int.from_bytes(digest[8:16], "big") | 1) % count
        if step == 0:
            step = 1
        while math.gcd(step, count) != 1:
            step = (step + 2) % count
            if step == 0:
                step = 1
        target = abs(remaining)
        visited = 0
        while adjusted < target and visited < count:
            value = values[index]
            if (direction > 0 and value < maximum) or (
                direction < 0 and value > minimum
            ):
                values[index] = value + direction
                adjusted += 1
            index = (index + step) % count
            visited += 1
        if adjusted != target:
            raise ReviewedMasterError(
                "global neutral residual could not be exactly recentered"
            )
    centered = Image.frombytes("L", image.size, bytes(values))
    post_sum = sum(centered.histogram()[value] * value for value in range(256))
    return centered, {
        "pre_mean_luma_levels": round(original_sum / count - 128.0, 9),
        "post_mean_luma_levels": round(post_sum / count - 128.0, 9),
        "adjusted_pixels": adjusted,
    }


def _prepare_global_neutral_bandpass(
    source: Image.Image,
) -> tuple[Image.Image, dict[str, Any]]:
    """Discard source colour and broad tone, retaining only fine/mid luma."""

    gray = ImageOps.grayscale(source)
    fine_blur = gray.filter(
        ImageFilter.GaussianBlur(
            radius=float(GLOBAL_NEUTRAL_BANDPASS["fine_blur_px"])
        )
    )
    broad_blur = gray.filter(
        ImageFilter.GaussianBlur(
            radius=float(GLOBAL_NEUTRAL_BANDPASS["broad_blur_px"])
        )
    )
    fine = ImageChops.subtract(gray, fine_blur, scale=1.0, offset=128)
    mid = ImageChops.subtract(fine_blur, broad_blur, scale=1.0, offset=128)
    fine_weight = float(GLOBAL_NEUTRAL_BANDPASS["fine_weight"])
    mid_weight = float(GLOBAL_NEUTRAL_BANDPASS["mid_weight"])
    weighted_fine = fine.point(
        lambda value: round(128.0 + (value - 128.0) * fine_weight),
        mode="L",
    )
    weighted_mid = mid.point(
        lambda value: round(128.0 + (value - 128.0) * mid_weight),
        mode="L",
    )
    combined = ImageChops.add(
        weighted_fine,
        weighted_mid,
        scale=1.0,
        offset=-128,
    )
    limit = int(GLOBAL_NEUTRAL_BANDPASS["bandpass_clamp_luma_levels"])
    clamped = combined.point(
        lambda value: max(128 - limit, min(128 + limit, value)),
        mode="L",
    )
    centered, centering = _exactly_recenter_luma(
        clamped,
        minimum=128 - limit,
        maximum=128 + limit,
        namespace="global-neutral-bandpass-source-v1",
    )
    extrema = centered.getextrema()
    stats = {
        "source_mode_used": "L",
        "source_rgb_or_colour_transferred": False,
        "source_broad_tone_transferred": False,
        "fine_construction": "source minus GaussianBlur(1.5px)",
        "mid_construction": "GaussianBlur(1.5px) minus GaussianBlur(18px)",
        "fine_weight": fine_weight,
        "mid_weight": mid_weight,
        "clamp_luma_levels": limit,
        "minimum_signed_luma_levels": extrema[0] - 128,
        "maximum_signed_luma_levels": extrema[1] - 128,
        "zero_mean": centering,
        "zero_mean_tolerance_luma_levels": 0.0,
        "zero_mean_passed": centering["post_mean_luma_levels"] == 0.0,
        "band_limited_by_construction": True,
    }
    gray.close()
    fine_blur.close()
    broad_blur.close()
    fine.close()
    mid.close()
    weighted_fine.close()
    weighted_mid.close()
    combined.close()
    clamped.close()
    return centered, stats


def _raised_cosine_matte(size: tuple[int, int]) -> Image.Image:
    """Return a separable raised-cosine quilting weight with zero edges."""

    width, height = size
    if width < 2 or height < 2:
        return Image.new("L", size, 255)
    horizontal_values = bytes(
        round(255.0 * math.sin(math.pi * index / (width - 1)) ** 2)
        for index in range(width)
    )
    vertical_values = bytes(
        round(255.0 * math.sin(math.pi * index / (height - 1)) ** 2)
        for index in range(height)
    )
    horizontal = Image.frombytes("L", (width, 1), horizontal_values).resize(
        size,
        Image.Resampling.NEAREST,
    )
    vertical = Image.frombytes("L", (1, height), vertical_values).resize(
        size,
        Image.Resampling.NEAREST,
    )
    matte = ImageChops.multiply(horizontal, vertical)
    horizontal.close()
    vertical.close()
    return matte


def _global_neutral_quilt_patch(
    material: Image.Image,
    digest: bytes,
    *,
    output_size: tuple[int, int],
) -> tuple[Image.Image, dict[str, Any]]:
    """Create one neutral signed-luma contribution with raised-cosine edges."""

    minimum, maximum = GLOBAL_NEUTRAL_BANDPASS["source_fraction"]
    fraction = float(minimum) + (float(maximum) - float(minimum)) * _unit(
        digest, 8
    )
    source_width = max(8, min(material.width, round(material.width * fraction)))
    source_height = max(8, min(material.height, round(material.height * fraction)))
    left = round(max(0, material.width - source_width) * _unit(digest, 12))
    top = round(max(0, material.height - source_height) * _unit(digest, 16))
    source_box = (left, top, left + source_width, top + source_height)
    window = material.crop(source_box)
    quarter_turn = int(_unit(digest, 20) * 4) % 4
    rotated = window.rotate(quarter_turn * 90, expand=True)
    reflected = _unit(digest, 24) < 0.5
    oriented = ImageOps.mirror(rotated) if reflected else rotated.copy()
    fitted_source = ImageOps.fit(
        oriented,
        output_size,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    limit = int(GLOBAL_NEUTRAL_BANDPASS["bandpass_clamp_luma_levels"])
    fitted = fitted_source.point(
        lambda value: max(128 - limit, min(128 + limit, value)),
        mode="L",
    )
    matte = _raised_cosine_matte(output_size)
    weighted_mean_before = ImageStat.Stat(fitted, matte).mean[0] - 128.0
    shift = round(-weighted_mean_before)
    centered = fitted.point(
        lambda value: max(
            128 - limit,
            min(128 + limit, value + shift),
        ),
        mode="L",
    )
    weighted_mean_after = ImageStat.Stat(centered, matte).mean[0] - 128.0
    neutral = Image.new("L", output_size, 128)
    contribution = Image.composite(centered, neutral, matte)
    record = {
        "source_box_px": list(source_box),
        "source_fraction": round(fraction, 6),
        "quarter_turn_degrees": quarter_turn * 90,
        "horizontal_reflection": reflected,
        "output_size_px": list(output_size),
        "weighted_mean_before_luma_levels": round(weighted_mean_before, 6),
        "weighted_mean_after_luma_levels": round(weighted_mean_after, 6),
        "raised_cosine_matte": True,
    }
    window.close()
    rotated.close()
    oriented.close()
    fitted_source.close()
    fitted.close()
    matte.close()
    centered.close()
    neutral.close()
    return contribution, record


def _add_neutral_patch(
    field: Image.Image,
    patch: Image.Image,
    left: int,
    top: int,
) -> None:
    """Add one signed-neutral patch to a sheet field without local coordinates."""

    destination = (
        max(0, left),
        max(0, top),
        min(field.width, left + patch.width),
        min(field.height, top + patch.height),
    )
    if destination[2] <= destination[0] or destination[3] <= destination[1]:
        return
    source_box = (
        destination[0] - left,
        destination[1] - top,
        destination[2] - left,
        destination[3] - top,
    )
    existing = field.crop(destination)
    contribution = patch.crop(source_box)
    added = ImageChops.add(existing, contribution, scale=1.0, offset=-128)
    field.paste(added, (destination[0], destination[1]))
    existing.close()
    contribution.close()
    added.close()


def _ea_world_bilinear_noise_image(
    transform: SheetCanvasTransform,
    seed: int,
    *,
    cell_world: float,
    amplitude_luma_levels: int,
    namespace: str,
) -> Image.Image:
    """Sample a small global EA lattice into a sheet with bilinear interpolation."""

    extent = transform.contract["world_extent"]
    minimum_x = math.floor(float(extent["min_x"]) / cell_world) - 2
    minimum_y = math.floor(float(extent["min_y"]) / cell_world) - 2
    maximum_x = math.ceil(float(extent["max_x"]) / cell_world) + 2
    maximum_y = math.ceil(float(extent["max_y"]) / cell_world) + 2
    width = maximum_x - minimum_x + 1
    height = maximum_y - minimum_y + 1
    values = bytearray(width * height)
    for local_y, grid_y in enumerate(range(minimum_y, maximum_y + 1)):
        for local_x, grid_x in enumerate(range(minimum_x, maximum_x + 1)):
            digest = _hash_digest(seed, namespace, grid_x, grid_y)
            delta = round(amplitude_luma_levels * (2.0 * _unit(digest, 0) - 1.0))
            values[local_y * width + local_x] = 128 + delta
    lattice = Image.frombytes("L", (width, height), bytes(values))
    global_left, global_top, _, _ = transform.pixel_bounds
    scale_x = 1.0 / (float(transform._pixels_per_world_x) * cell_world)
    scale_y = 1.0 / (float(transform._pixels_per_world_y) * cell_world)
    offset_x = (
        float(extent["min_x"]) + global_left / float(transform._pixels_per_world_x)
    ) / cell_world - minimum_x
    offset_y = (
        float(extent["min_y"]) + global_top / float(transform._pixels_per_world_y)
    ) / cell_world - minimum_y
    sampled = lattice.transform(
        (transform.width, transform.height),
        Image.Transform.AFFINE,
        (scale_x, 0.0, offset_x, 0.0, scale_y, offset_y),
        resample=Image.Resampling.BILINEAR,
        fillcolor=128,
    )
    lattice.close()
    return sampled


def _global_neutral_broad_noise(
    transform: SheetCanvasTransform,
    seed: int,
) -> tuple[Image.Image, dict[str, Any]]:
    field = Image.new("L", (transform.width, transform.height), 128)
    bands: list[dict[str, Any]] = []
    for index, spec in enumerate(GLOBAL_NEUTRAL_BANDPASS["broad_noise"]):
        noise = _ea_world_bilinear_noise_image(
            transform,
            seed,
            cell_world=float(spec["cell_world"]),
            amplitude_luma_levels=int(spec["amplitude_luma_levels"]),
            namespace=f"global-neutral-broad-noise-v1:{index}",
        )
        combined = ImageChops.add(field, noise, scale=1.0, offset=-128)
        field.close()
        field = combined
        bands.append(dict(spec))
        noise.close()
    limit = int(GLOBAL_NEUTRAL_BANDPASS["maximum_broad_noise_luma_levels"])
    bounded = field.point(
        lambda value: max(128 - limit, min(128 + limit, value)),
        mode="L",
    )
    field.close()
    extrema = bounded.getextrema()
    return bounded, {
        "coordinate_reference_system": "EA-WORLD-1",
        "interpolation": "bilinear",
        "sheet_id_in_hash": False,
        "bands": bands,
        "maximum_allowed_signed_luma_levels": limit,
        "minimum_observed_signed_luma_levels": extrema[0] - 128,
        "maximum_observed_signed_luma_levels": extrema[1] - 128,
    }


def _global_neutral_world_recenter(
    transform: SheetCanvasTransform,
    seed: int,
) -> tuple[Image.Image, dict[str, Any]]:
    """Return a sub-luma correction whose phase is native-global pixel space."""

    base = int(GLOBAL_NEUTRAL_BANDPASS["world_recenter_base_luma_levels"])
    fraction = float(GLOBAL_NEUTRAL_BANDPASS["world_recenter_fraction"])
    period = int(GLOBAL_NEUTRAL_BANDPASS["world_recenter_period_px"])
    if not 0.0 <= fraction <= 1.0 or period < 3:
        raise ReviewedMasterError("invalid global neutral world recenter contract")
    threshold = round(fraction * 0xFFFFFFFF)
    values = bytearray(period * period)
    selected = 0
    for y in range(period):
        for x in range(period):
            digest = _hash_digest(seed, "global-neutral-world-recenter-v1", x, y)
            enabled = int.from_bytes(digest[:4], "big") <= threshold
            values[y * period + x] = 128 + base + int(enabled)
            selected += int(enabled)
    tile = Image.frombytes("L", (period, period), bytes(values))
    field = Image.new("L", (transform.width, transform.height), 128 + base)
    global_left, global_top, _, _ = transform.pixel_bounds
    start_x = -(global_left % period)
    start_y = -(global_top % period)
    for top in range(start_y, transform.height, period):
        for left in range(start_x, transform.width, period):
            field.paste(tile, (left, top))
    tile.close()
    return field, {
        "coordinate_reference_system": "native global pixel grid derived from EA-WORLD-1",
        "sheet_id_in_hash": False,
        "base_luma_levels": base,
        "fractional_plus_one_target": fraction,
        "fractional_plus_one_observed_in_period": round(
            selected / (period * period), 9
        ),
        "period_px": period,
        "maximum_correction_luma_levels": base + 1,
    }


def _draw_global_neutral_land_material(
    image: Image.Image,
    sources: dict[str, dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
    material_path: Path = DEFAULT_GLOBAL_NEUTRAL_MATERIAL,
) -> dict[str, Any]:
    """Apply one grayscale, band-limited source globally to canonical land."""

    material_record = _global_neutral_material_record(material_path)
    canonical_clip = _build_canonical_texture_clip(
        sources,
        land_mask,
        transform,
        full_material_preview=False,
    )
    before = image.convert("RGB")
    with Image.open(material_path) as opened:
        opened.load()
        source = opened.convert("RGB")
    material, bandpass = _prepare_global_neutral_bandpass(source)
    source.close()
    field = Image.new("L", image.size, 128)
    patch_width = max(
        8,
        round(
            float(GLOBAL_NEUTRAL_BANDPASS["patch_world"])
            * float(transform._pixels_per_world_x)
        ),
    )
    patch_height = max(
        8,
        round(
            float(GLOBAL_NEUTRAL_BANDPASS["patch_world"])
            * float(transform._pixels_per_world_y)
        ),
    )
    clip_bbox = canonical_clip.getbbox()
    patches = 0
    maximum_weighted_patch_mean = 0.0
    examples: list[dict[str, Any]] = []
    for grid_x, grid_y, world_x, world_y, digest in iter_anchored_grid(
        transform,
        cell_world=float(GLOBAL_NEUTRAL_BANDPASS["stride_world"]),
        namespace="global-neutral-bandpass-quilt-v1",
        seed=seed,
        margin_cells=3,
    ):
        # World-global thinning keeps Royal below about 45 windows without a
        # sheet-local cap, so overlapping sheets select the same contributors.
        if (grid_x + grid_y) % 2 or _unit(digest, 28) > 0.72:
            continue
        center_x, center_y = transform.point_fast((world_x, world_y))
        left = center_x - patch_width // 2
        top = center_y - patch_height // 2
        patch_box = (left, top, left + patch_width, top + patch_height)
        if clip_bbox is None or (
            patch_box[2] <= clip_bbox[0]
            or patch_box[0] >= clip_bbox[2]
            or patch_box[3] <= clip_bbox[1]
            or patch_box[1] >= clip_bbox[3]
        ):
            continue
        patch, record = _global_neutral_quilt_patch(
            material,
            digest,
            output_size=(patch_width, patch_height),
        )
        try:
            _add_neutral_patch(field, patch, left, top)
        finally:
            patch.close()
        record.update({"grid": [grid_x, grid_y], "center_world": [world_x, world_y]})
        maximum_weighted_patch_mean = max(
            maximum_weighted_patch_mean,
            abs(float(record["weighted_mean_after_luma_levels"])),
        )
        if len(examples) < 12:
            examples.append(record)
        patches += 1
    limit = int(GLOBAL_NEUTRAL_BANDPASS["bandpass_clamp_luma_levels"])
    bounded_field = field.point(
        lambda value: max(128 - limit, min(128 + limit, value)),
        mode="L",
    )
    broad_noise, broad_noise_record = _global_neutral_broad_noise(transform, seed)
    texture = ImageChops.add(
        bounded_field,
        broad_noise,
        scale=1.0,
        offset=-128,
    )
    world_recenter, world_recenter_record = _global_neutral_world_recenter(
        transform,
        seed,
    )
    recentered_texture = ImageChops.add(
        texture,
        world_recenter,
        scale=1.0,
        offset=-128,
    )
    texture.close()
    texture = recentered_texture
    texture_bands = (texture.copy(), texture.copy(), texture.copy())
    texture_rgb = Image.merge("RGB", texture_bands)
    for band in texture_bands:
        band.close()
    adjusted = ImageChops.add(before, texture_rgb, scale=1.0, offset=-128)
    after = Image.composite(adjusted, before, canonical_clip)
    after_rgba = after.convert("RGBA")
    image.paste(after_rgba)

    difference = ImageChops.difference(before, after).convert("L")
    water_mask = ImageOps.invert(land_mask)
    water_difference = ImageChops.multiply(difference, water_mask)
    line_guard = ImageChops.subtract(land_mask, canonical_clip)
    guard_difference = ImageChops.multiply(difference, line_guard)
    inverse_clip = ImageOps.invert(canonical_clip)
    outside_clip = ImageChops.multiply(difference, inverse_clip)
    water_changes = 0 if water_difference.getbbox() is None else 1
    guard_changes = 0 if guard_difference.getbbox() is None else 1
    outside_changes = 0 if outside_clip.getbbox() is None else 1
    land_mean = _masked_signed_luma_mean(before, after, land_mask)
    tolerance = float(
        GLOBAL_NEUTRAL_BANDPASS["land_mean_tolerance_luma_levels"]
    )
    is_royal = (
        transform.sheet.get("sheet_id") == "sheet_region_royal_capital_region"
    )
    if is_royal and abs(land_mean) > tolerance:
        raise ReviewedMasterError(
            "global neutral material land mean exceeds 0.25 luma levels: "
            f"{land_mean:.6f}"
        )
    if water_changes or guard_changes or outside_changes:
        raise ReviewedMasterError(
            "global neutral material changed canonical water or line guard pixels"
        )
    if (
        is_royal
        and patches > int(GLOBAL_NEUTRAL_BANDPASS["maximum_royal_windows"])
    ):
        raise ReviewedMasterError(
            "global neutral Royal quilt exceeded the maximum window count"
        )

    record = {
        "global_neutral_material_sha256": material_record["sha256"],
        "global_neutral_material_transfer_mode": GLOBAL_NEUTRAL_BANDPASS_MODE,
        "global_neutral_semantic_usage_masks_accepted": 0,
        "global_neutral_region_washes_used": 0,
        "global_neutral_quilt_windows": patches,
        "global_neutral_maximum_royal_windows": GLOBAL_NEUTRAL_BANDPASS[
            "maximum_royal_windows"
        ],
        "global_neutral_patch_world": GLOBAL_NEUTRAL_BANDPASS["patch_world"],
        "global_neutral_stride_world": GLOBAL_NEUTRAL_BANDPASS["stride_world"],
        "global_neutral_patch_size_px": [patch_width, patch_height],
        "global_neutral_source_window_examples": examples,
        "global_neutral_maximum_weighted_patch_mean_luma_levels": round(
            maximum_weighted_patch_mean, 6
        ),
        "global_neutral_bandpass": bandpass,
        "global_neutral_broad_noise": broad_noise_record,
        "global_neutral_world_recenter": world_recenter_record,
        "global_neutral_land_signed_mean_luma_levels": round(land_mean, 6),
        "global_neutral_land_mean_tolerance_luma_levels": tolerance,
        "global_neutral_land_mean_passed": abs(land_mean) <= tolerance,
        "global_neutral_water_pixel_changes": water_changes,
        "global_neutral_line_guard_pixel_changes": guard_changes,
        "global_neutral_outside_canonical_clip_changes": outside_changes,
        "global_neutral_semantic_boundary_contrast_luma_levels": 0.0,
        "global_neutral_semantic_boundary_contrast_limit_luma_levels": (
            SEMANTIC_BOUNDARY_CONTRAST_LIMIT
        ),
        "global_neutral_semantic_boundary_contrast_passed": True,
        "global_neutral_sheet_id_in_hash": False,
        "global_neutral_promotion_eligible": False,
    }
    material.close()
    field.close()
    bounded_field.close()
    broad_noise.close()
    world_recenter.close()
    texture.close()
    texture_rgb.close()
    adjusted.close()
    after.close()
    after_rgba.close()
    difference.close()
    water_mask.close()
    water_difference.close()
    line_guard.close()
    guard_difference.close()
    inverse_clip.close()
    outside_clip.close()
    canonical_clip.close()
    before.close()
    return record


def _ea_low_frequency_strength_noise(
    size: tuple[int, int],
    transform: SheetCanvasTransform,
    seed: int,
    namespace: str,
    feather_px: int,
) -> Image.Image:
    """Build smooth, sheet-independent strength variation in EA-WORLD-1."""

    noise = Image.new("L", size, 224)
    draw = ImageDraw.Draw(noise)
    cell_world = max(78.0, feather_px / transform._pixels_per_world_mean_float * 1.4)
    radius = max(48, round(feather_px * 0.82))
    for _, _, world_x, world_y, digest in iter_anchored_grid(
        transform,
        cell_world=cell_world,
        namespace=namespace,
        seed=seed,
        margin_cells=4,
    ):
        x, y = transform.point_fast((world_x, world_y))
        radius_x = round(radius * (0.76 + 0.48 * _unit(digest, 8)))
        radius_y = round(radius * (0.76 + 0.48 * _unit(digest, 12)))
        value = 194 + round(59 * _unit(digest, 16))
        draw.ellipse(
            (x - radius_x, y - radius_y, x + radius_x, y + radius_y),
            fill=value,
        )
    smoothed = noise.filter(
        ImageFilter.GaussianBlur(radius=max(48, round(feather_px * 0.72)))
    )
    noise.close()
    return smoothed


def _masked_signed_luma_mean(
    before: Image.Image,
    after: Image.Image,
    mask: Image.Image,
) -> float:
    if mask.getbbox() is None:
        return 0.0
    before_luma = ImageOps.grayscale(before)
    after_luma = ImageOps.grayscale(after)
    signed = ImageChops.subtract(after_luma, before_luma, scale=1.0, offset=128)
    try:
        return ImageStat.Stat(signed, mask).mean[0] - 128.0
    finally:
        before_luma.close()
        after_luma.close()
        signed.close()


def _semantic_boundary_contrast(
    before: Image.Image,
    after: Image.Image,
    parent_mask: Image.Image,
    canonical_clip: Image.Image,
) -> dict[str, Any]:
    dilated = parent_mask.filter(ImageFilter.MaxFilter(9))
    eroded = parent_mask.filter(ImageFilter.MinFilter(9))
    inside = ImageChops.multiply(ImageChops.subtract(parent_mask, eroded), canonical_clip)
    outside = ImageChops.multiply(ImageChops.subtract(dilated, parent_mask), canonical_clip)
    before_luma = ImageOps.grayscale(before)
    after_luma = ImageOps.grayscale(after)
    absolute = ImageChops.difference(before_luma, after_luma)
    try:
        inside_mean = _masked_signed_luma_mean(before, after, inside)
        outside_mean = _masked_signed_luma_mean(before, after, outside)
        changed_mean = (
            ImageStat.Stat(absolute, canonical_clip).mean[0]
            if canonical_clip.getbbox() is not None
            else 0.0
        )
        contrast = abs(inside_mean - outside_mean)
        return {
            "metric": "absolute difference of signed mean luma shift across 4px semantic boundary rings",
            "inside_signed_mean_luma_levels": round(inside_mean, 6),
            "outside_signed_mean_luma_levels": round(outside_mean, 6),
            "contrast_luma_levels": round(contrast, 6),
            "mean_absolute_texture_delta_luma_levels": round(changed_mean, 6),
            "limit_luma_levels": SEMANTIC_BOUNDARY_CONTRAST_LIMIT,
            "passed": contrast <= SEMANTIC_BOUNDARY_CONTRAST_LIMIT,
        }
    finally:
        dilated.close()
        eroded.close()
        inside.close()
        outside.close()
        before_luma.close()
        after_luma.close()
        absolute.close()


def _apply_atlas_crop_material(
    image: Image.Image,
    parent_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
    crop_name: str,
    crop: Image.Image,
    *,
    canonical_clip: Image.Image | None = None,
) -> dict[str, Any]:
    """Add only a zero-mean residual through a softly feathered semantic mask."""

    spec = MATERIAL_ATLAS_CROPS[crop_name]
    parent_bbox = parent_mask.getbbox()
    if parent_bbox is None:
        return {
            "patches": 0,
            "quarter_turns_used": [],
            "horizontal_reflections_used": [],
            "outside_parent_pixel_changes": 0,
            "residual_zero_mean": None,
            "semantic_boundary_contrast": None,
        }
    if float(spec["strength"]) > float(spec["strength_limit"]):
        raise ReviewedMasterError(
            f"atlas material strength exceeds limit for {crop_name}"
        )
    residual, zero_mean = _zero_mean_high_frequency_residual(crop)
    patch_px = transform.nominal_width_px_fast(float(spec["patch_world"]))
    variants, maximum_variant_mean = _material_patch_variants(
        residual,
        patch_px=patch_px,
    )
    residual.close()
    field = Image.new("RGBA", image.size, (128, 128, 128, 255))
    patches = 0
    turns: set[int] = set()
    reflections: set[bool] = set()
    radius = patch_px // 2
    before = image.convert("RGB")
    clip = canonical_clip.copy() if canonical_clip is not None else parent_mask.copy()
    feather_px = int(spec["feather_px"])
    soft_parent = parent_mask.filter(ImageFilter.GaussianBlur(radius=feather_px))
    noise = _ea_low_frequency_strength_noise(
        image.size,
        transform,
        seed,
        f"atlas-strength-noise-v2:{crop_name}",
        feather_px,
    )
    effective_mask = ImageChops.multiply(soft_parent, noise)
    clipped_effective = ImageChops.multiply(effective_mask, clip)
    effective_bbox = clipped_effective.getbbox()
    try:
        for _, _, world_x, world_y, digest in iter_anchored_grid(
            transform,
            cell_world=float(spec["cell_world"]),
            namespace=f"atlas-material-v1:{crop_name}",
            seed=seed,
            margin_cells=3,
        ):
            x, y = transform.point_fast((world_x, world_y))
            patch_box = (x - radius, y - radius, x - radius + patch_px, y - radius + patch_px)
            if effective_bbox is None or (
                patch_box[2] <= effective_bbox[0]
                or patch_box[0] >= effective_bbox[2]
                or patch_box[3] <= effective_bbox[1]
                or patch_box[1] >= effective_bbox[3]
            ):
                continue
            quarter_turn = int(_unit(digest, 12) * 4) % 4
            reflected = _unit(digest, 16) < 0.5
            field.alpha_composite(
                variants[(quarter_turn, reflected)],
                dest=(patch_box[0], patch_box[1]),
            )
            patches += 1
            turns.add(quarter_turn * 90)
            reflections.add(reflected)
        field_rgb = field.convert("RGB")
        neutral = Image.new("RGB", image.size, (128, 128, 128))
        scaled = Image.blend(neutral, field_rgb, float(spec["strength"]))
        adjusted = ImageChops.add(before, scaled, scale=1.0, offset=-128)
        after = Image.composite(adjusted, before, clipped_effective)
        after_rgba = after.convert("RGBA")
        image.paste(after_rgba)
        boundary = _semantic_boundary_contrast(
            before,
            after,
            parent_mask,
            clip,
        )

        difference = ImageChops.difference(before, after).convert("L")
        inverse_clip = ImageOps.invert(clip)
        outside_clip = ImageChops.multiply(difference, inverse_clip)
        outside_changes = 0 if outside_clip.getbbox() is None else 1
        field_rgb.close()
        neutral.close()
        scaled.close()
        adjusted.close()
        after.close()
        after_rgba.close()
        difference.close()
        inverse_clip.close()
        outside_clip.close()
    finally:
        field.close()
        before.close()
        clip.close()
        soft_parent.close()
        noise.close()
        effective_mask.close()
        clipped_effective.close()
        for variant in variants.values():
            variant.close()
    return {
        "patches": patches,
        "quarter_turns_used": sorted(turns),
        "horizontal_reflections_used": sorted(reflections),
        "outside_parent_pixel_changes": outside_changes,
        "residual_zero_mean": {
            **zero_mean,
            "maximum_weighted_variant_mean_rgb_levels": round(
                maximum_variant_mean, 6
            ),
            "weighted_variant_tolerance_levels": 0.51,
            "weighted_variants_passed": maximum_variant_mean <= 0.51,
        },
        "application": {
            "mode": "signed additive around RGB neutral 128",
            "strength": float(spec["strength"]),
            "strength_limit": float(spec["strength_limit"]),
            "semantic_mask_feather_px": feather_px,
            "ea_world_low_frequency_strength_noise": True,
            "canonical_clip_reapplied": True,
        },
        "semantic_boundary_contrast": boundary,
    }


def _merge_mask(target: Image.Image, addition: Image.Image) -> Image.Image:
    merged = ImageChops.lighter(target, addition)
    target.close()
    addition.close()
    return merged


def _build_atlas_usage_masks(
    sources: dict[str, dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
) -> dict[str, Image.Image]:
    size = land_mask.size
    forest = Image.new("L", size, 0)
    rock = Image.new("L", size, 0)
    rock_types = {
        "mountain_axis",
        "gorge_axis",
        "volcanic_land",
        "arcane_highlands",
        "tundra_permafrost",
    }
    for feature in sources["terrain"]["features"]:
        terrain_type = str(feature.get("properties", {}).get("terrain_type", ""))
        if terrain_type in {
            "temperate_magic_forest",
            "tropical_magic_rainforest",
        }:
            forest = _merge_mask(
                forest,
                _terrain_feature_mask(size, feature, land_mask, transform),
            )
        if terrain_type in rock_types:
            rock = _merge_mask(
                rock,
                _terrain_feature_mask(size, feature, land_mask, transform),
            )

    agriculture = Image.new("L", size, 0)
    for feature in sources["regions"]["features"]:
        if feature.get("properties", {}).get("region_type") != AGRICULTURAL_REGION_TYPE:
            continue
        region_mask = ImageChops.multiply(
            feature_mask(size, feature, transform),
            land_mask,
        )
        agriculture = _merge_mask(agriculture, region_mask)

    riparian = Image.new("L", size, 0)
    riparian_draw = ImageDraw.Draw(riparian)
    for feature in sources["hydrography"]["features"]:
        if feature.get("properties", {}).get("water_type") != "river_system":
            continue
        for path in line_paths(feature.get("geometry", {}), transform):
            riparian_draw.line(
                path,
                fill=255,
                width=transform.nominal_width_px_fast(92.0),
                joint="curve",
            )
    clipped_riparian = ImageChops.multiply(riparian, land_mask)
    riparian.close()
    return {
        "neutral_parchment": land_mask.copy(),
        "connected_forest": forest,
        "cultivated_hatching": agriculture,
        "wetland": clipped_riparian,
        "flat_rock_hachure": rock,
    }


def _build_canonical_texture_clip(
    sources: dict[str, dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
    *,
    full_material_preview: bool = False,
) -> Image.Image:
    """Permit land texture while preserving exact canonical line evidence."""

    protected = Image.new("L", land_mask.size, 0)
    draw = ImageDraw.Draw(protected)
    for role in ("transport", "hydrography"):
        for feature in sources[role]["features"]:
            for path in line_paths(feature.get("geometry", {}), transform):
                width = 1
                if full_material_preview:
                    width = 3 if role == "transport" else 5
                draw.line(path, fill=255, width=width, joint="curve")
    clip = ImageChops.subtract(land_mask, protected)
    protected.close()
    return clip


def _draw_atlas_materials(
    image: Image.Image,
    sources: dict[str, dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
    material_atlas_path: Path,
    *,
    material_transfer_mode: str = RESIDUAL_MATERIAL_MODE,
    style_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if material_transfer_mode not in {
        RESIDUAL_MATERIAL_MODE,
        FULL_SPATIAL_MATERIAL_MODE,
    }:
        raise ReviewedMasterError(
            f"unknown material transfer mode: {material_transfer_mode}"
        )
    full_material_preview = (
        material_transfer_mode == FULL_SPATIAL_MATERIAL_MODE
    )
    atlas_record = _material_atlas_record(
        material_atlas_path,
        transfer_mode=material_transfer_mode,
    )
    usage_masks = _build_atlas_usage_masks(sources, land_mask, transform)
    canonical_clip = _build_canonical_texture_clip(
        sources,
        land_mask,
        transform,
        full_material_preview=full_material_preview,
    )
    per_crop: dict[str, dict[str, Any]] = {}
    total_patches = 0
    with Image.open(material_atlas_path) as atlas_source:
        atlas_source.load()
        atlas = atlas_source.convert("RGB")
        try:
            for crop_name in (
                "neutral_parchment",
                "cultivated_hatching",
                "wetland",
                "flat_rock_hachure",
                "connected_forest",
            ):
                spec = MATERIAL_ATLAS_CROPS[crop_name]
                crop = atlas.crop(tuple(spec["rect_px"]))
                try:
                    if full_material_preview:
                        result = _apply_atlas_crop_full_spatial_material(
                            image,
                            usage_masks[crop_name],
                            transform,
                            seed,
                            crop_name,
                            crop,
                            canonical_clip=canonical_clip,
                            style_profile=style_profile,
                        )
                    else:
                        result = _apply_atlas_crop_material(
                            image,
                            usage_masks[crop_name],
                            transform,
                            seed,
                            crop_name,
                            crop,
                            canonical_clip=canonical_clip,
                        )
                finally:
                    crop.close()
                per_crop[crop_name] = result
                total_patches += int(result["patches"])
        finally:
            atlas.close()
            canonical_clip.close()
            for mask in usage_masks.values():
                mask.close()
    maximum_boundary_contrast = max(
        (
            float(result["semantic_boundary_contrast"]["contrast_luma_levels"])
            for result in per_crop.values()
            if result.get("semantic_boundary_contrast") is not None
        ),
        default=0.0,
    )
    outside_parent_changes = sum(
        int(result["outside_parent_pixel_changes"]) for result in per_crop.values()
    )
    if outside_parent_changes:
        raise ReviewedMasterError("atlas material escaped the canonical clip")
    if maximum_boundary_contrast > SEMANTIC_BOUNDARY_CONTRAST_LIMIT:
        raise ReviewedMasterError(
            "atlas semantic boundary contrast exceeds 0.75 luma levels"
        )
    if full_material_preview:
        unique_windows = sum(
            int(result.get("unique_source_window_transforms", 0))
            for result in per_crop.values()
        )
        return {
            "material_atlas_sha256": atlas_record["sha256"],
            "material_atlas_transfer_mode": material_transfer_mode,
            "material_atlas_safe_crop_count": len(MATERIAL_ATLAS_CROPS),
            "material_atlas_patches": total_patches,
            "material_atlas_unique_source_window_transforms": unique_windows,
            "material_atlas_crops": per_crop,
            "material_atlas_full_spatial_material_retained": True,
            "material_atlas_low_frequency_shapes_transferred": len(
                MATERIAL_ATLAS_CROPS
            ),
            "material_atlas_approved_semantic_material_only": True,
            "material_atlas_unapproved_semantic_shapes_transferred": 0,
            "material_atlas_semantic_shapes_transferred": 0,
            "material_atlas_maximum_boundary_contrast_luma_levels": round(
                maximum_boundary_contrast, 6
            ),
            "material_atlas_boundary_contrast_limit_luma_levels": (
                SEMANTIC_BOUNDARY_CONTRAST_LIMIT
            ),
            "material_atlas_boundary_contrast_checks_passed": (
                maximum_boundary_contrast <= SEMANTIC_BOUNDARY_CONTRAST_LIMIT
            ),
            "material_atlas_zero_mean_checks_passed": None,
            "material_atlas_outside_parent_pixel_changes": outside_parent_changes,
        }

    zero_mean_passed = all(
        result.get("residual_zero_mean") is None
        or (
            result["residual_zero_mean"]["explicit_zero_mean_per_channel"]
            and result["residual_zero_mean"]["weighted_variants_passed"]
        )
        for result in per_crop.values()
    )
    if not zero_mean_passed:
        raise ReviewedMasterError("atlas residual zero-mean check failed")
    return {
        "material_atlas_sha256": atlas_record["sha256"],
        "material_atlas_transfer_mode": material_transfer_mode,
        "material_atlas_safe_crop_count": len(MATERIAL_ATLAS_CROPS),
        "material_atlas_patches": total_patches,
        "material_atlas_crops": per_crop,
        "material_atlas_zero_mean_checks_passed": zero_mean_passed,
        "material_atlas_maximum_boundary_contrast_luma_levels": round(
            maximum_boundary_contrast, 6
        ),
        "material_atlas_boundary_contrast_limit_luma_levels": (
            SEMANTIC_BOUNDARY_CONTRAST_LIMIT
        ),
        "material_atlas_boundary_contrast_checks_passed": (
            maximum_boundary_contrast <= SEMANTIC_BOUNDARY_CONTRAST_LIMIT
        ),
        "material_atlas_low_frequency_shapes_transferred": 0,
        "material_atlas_semantic_shapes_transferred": 0,
        "material_atlas_outside_parent_pixel_changes": outside_parent_changes,
    }


def _capital_parcel_vertex_world(
    grid_x: int,
    grid_y: int,
    *,
    cell_world: float,
    capital_id: str,
    seed: int,
) -> tuple[float, float]:
    """Return one shared irregular parcel vertex in global EA coordinates."""

    digest = _hash_digest(
        seed,
        "capital-parcel-shared-vertex-v4",
        capital_id,
        grid_x,
        grid_y,
    )
    return (
        (grid_x + (-0.22 + 0.44 * _unit(digest, 0))) * cell_world,
        (grid_y + (-0.22 + 0.44 * _unit(digest, 4))) * cell_world,
    )


def _capital_landscape_clip(
    capital: dict[str, Any],
    settlement_features: Iterable[dict[str, Any]],
    terrain_features: Iterable[dict[str, Any]],
    hydro_features: Iterable[dict[str, Any]],
    transport_features: Iterable[dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
    *,
    center: tuple[float, float],
    outer_radius_x: float,
    outer_radius_y: float,
) -> tuple[Image.Image, dict[str, int]]:
    """Build the canonical exclusion clip for the Royal parcel network."""

    ring = Image.new("L", land_mask.size, 0)
    ring_draw = ImageDraw.Draw(ring)
    top_left = transform.point_fast(
        (center[0] - outer_radius_x, center[1] - outer_radius_y)
    )
    bottom_right = transform.point_fast(
        (center[0] + outer_radius_x, center[1] + outer_radius_y)
    )
    ring_draw.ellipse((*top_left, *bottom_right), fill=255)
    ring_land = ImageChops.multiply(ring, land_mask)
    ring.close()

    protected = Image.new("L", land_mask.size, 0)
    settlement_pixels = 0
    for feature in settlement_features:
        bbox = _geometry_bbox(feature)
        if bbox is None or not _intersects(bbox, transform.bounds):
            continue
        source = feature_mask(land_mask.size, feature, transform)
        try:
            protected = _merge_mask(protected, source.copy())
            settlement_pixels += sum(source.histogram()[128:])
        finally:
            source.close()

    forest = Image.new("L", land_mask.size, 0)
    for feature in terrain_features:
        if feature.get("properties", {}).get("terrain_type") not in {
            "temperate_magic_forest",
            "tropical_magic_rainforest",
        }:
            continue
        forest = _merge_mask(
            forest,
            _terrain_feature_mask(land_mask.size, feature, land_mask, transform),
        )
    protected = _merge_mask(protected, forest)

    line_protection = Image.new("L", land_mask.size, 0)
    line_draw = ImageDraw.Draw(line_protection)
    road_width = transform.nominal_width_px_fast(18.0)
    river_width = transform.nominal_width_px_fast(24.0)
    for feature in transport_features:
        if feature.get("properties", {}).get("route_type") not in {"road", "rail"}:
            continue
        for path in line_paths(feature.get("geometry", {}), transform):
            line_draw.line(path, fill=255, width=road_width, joint="curve")
    for feature in hydro_features:
        if feature.get("properties", {}).get("water_type") != "river_system":
            continue
        for path in line_paths(feature.get("geometry", {}), transform):
            line_draw.line(path, fill=255, width=river_width, joint="curve")
    protected = _merge_mask(protected, line_protection)

    quiet = Image.new("L", land_mask.size, 0)
    quiet_draw = ImageDraw.Draw(quiet)
    quiet_width = transform.nominal_width_px_fast(25.0)
    quiet_draw.line(
        (
            transform.point_fast(
                (center[0] - outer_radius_x * 0.78, center[1] - outer_radius_y * 0.58)
            ),
            transform.point_fast(
                (center[0] + outer_radius_x * 0.34, center[1] - outer_radius_y * 0.58)
            ),
        ),
        fill=255,
        width=quiet_width,
    )
    quiet_draw.line(
        (
            transform.point_fast(
                (center[0] + outer_radius_x * 0.22, center[1] + outer_radius_y * 0.51)
            ),
            transform.point_fast(
                (center[0] + outer_radius_x * 0.74, center[1] + outer_radius_y * 0.18)
            ),
        ),
        fill=255,
        width=quiet_width,
    )
    protected = _merge_mask(protected, quiet)

    available = ImageChops.subtract(ring_land, protected)
    stats = {
        "capital_landscape_canonical_settlement_pixels_protected": settlement_pixels,
        "capital_landscape_road_corridor_width_px": road_width,
        "capital_landscape_river_corridor_width_px": river_width,
        "capital_landscape_quiet_corridors": 2,
    }
    ring_land.close()
    protected.close()
    return available, stats


def _draw_royal_capital_landscape(
    image: Image.Image,
    settlement_features: Iterable[dict[str, Any]],
    terrain_features: Iterable[dict[str, Any]],
    hydro_features: Iterable[dict[str, Any]],
    transport_features: Iterable[dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
    style_profile: dict[str, Any] | None = None,
    *,
    full_material_preview: bool = False,
) -> dict[str, int]:
    settlement_features = tuple(settlement_features)
    terrain_features = tuple(terrain_features)
    hydro_features = tuple(hydro_features)
    transport_features = tuple(transport_features)
    capital = next(
        (
            feature
            for feature in settlement_features
            if feature.get("properties", {}).get("node_type") == "capital"
            and (bbox := _geometry_bbox(feature)) is not None
            and _intersects(bbox, transform.bounds)
        ),
        None,
    )
    if capital is None:
        return {
            "capital_landscape_parcels": 0,
            "capital_landscape_villages": 0,
            "capital_landscape_tree_belts": 0,
            "capital_landscape_shared_boundary_edges": 0,
            "capital_landscape_isolated_rectangular_parcels": 0,
            "capital_landscape_quiet_corridors": 0,
            "capital_landscape_canonical_settlement_pixels_protected": 0,
            "capital_landscape_road_corridor_width_px": 0,
            "capital_landscape_river_corridor_width_px": 0,
            "capital_landscape_full_material_reduced_edges": int(
                full_material_preview
            ),
        }
    bbox = _geometry_bbox(capital)
    if bbox is None:
        raise ReviewedMasterError("capital footprint unexpectedly lacks a bbox")
    center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
    outer_radius_x = max(520.0, (bbox[2] - bbox[0]) * 1.75)
    outer_radius_y = max(470.0, (bbox[3] - bbox[1]) * 1.75)
    clip, clip_stats = _capital_landscape_clip(
        capital,
        settlement_features,
        terrain_features,
        hydro_features,
        transport_features,
        land_mask,
        transform,
        center=center,
        outer_radius_x=outer_radius_x,
        outer_radius_y=outer_radius_y,
    )

    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    parcels = 0
    tree_belts = 0
    shared_edges = 0
    cell_world = 68.0 if full_material_preview else 47.0
    capital_id = feature_id(capital)
    ink = _style_rgb(style_profile, "ink_tone_rgb", (91, 73, 47))
    alpha_scale = _clamp(
        _style_parameter(style_profile, "ink_alpha_scale", 1.0), 0.75, 1.35
    )
    minimum_x = math.floor((center[0] - outer_radius_x) / cell_world) - 1
    maximum_x = math.ceil((center[0] + outer_radius_x) / cell_world) + 1
    minimum_y = math.floor((center[1] - outer_radius_y) / cell_world) - 1
    maximum_y = math.ceil((center[1] + outer_radius_y) / cell_world) + 1

    def vertex(grid_x: int, grid_y: int) -> tuple[int, int]:
        return transform.point_fast(
            _capital_parcel_vertex_world(
                grid_x,
                grid_y,
                cell_world=cell_world,
                capital_id=capital_id,
                seed=seed,
            )
        )

    def shared_segment(
        start: tuple[int, int],
        end: tuple[int, int],
        digest: bytes,
    ) -> None:
        nonlocal tree_belts
        midpoint = (
            round((start[0] + end[0]) / 2 + (-2.0 + 4.0 * _unit(digest, 16))),
            round((start[1] + end[1]) / 2 + (-2.0 + 4.0 * _unit(digest, 20))),
        )
        draw.line(
            (start, midpoint, end),
            fill=(
                *ink,
                round(
                    (
                        43 + 28 * _unit(digest, 24)
                        if full_material_preview
                        else 92 + 40 * _unit(digest, 24)
                    )
                    * alpha_scale
                ),
            ),
            width=1,
            joint="curve",
        )
        if _unit(digest, 28) >= 0.23:
            return
        steps = 6 + int(_unit(digest, 4) * 5)
        for index in range(steps + 1):
            ratio = index / steps
            inverse = 1.0 - ratio
            x = round(
                inverse * inverse * start[0]
                + 2 * inverse * ratio * midpoint[0]
                + ratio * ratio * end[0]
            )
            y = round(
                inverse * inverse * start[1]
                + 2 * inverse * ratio * midpoint[1]
                + ratio * ratio * end[1]
            )
            stipple = _hash_digest(seed, "capital-hedgerow-stipple-v4", x, y, index)
            if _unit(stipple, 0) < 0.72:
                draw.point((x, y), fill=(55, 69, 42, round(125 * alpha_scale)))
        tree_belts += 1

    for grid_y in range(minimum_y, maximum_y):
        for grid_x in range(minimum_x, maximum_x):
            corners = (
                vertex(grid_x, grid_y),
                vertex(grid_x + 1, grid_y),
                vertex(grid_x + 1, grid_y + 1),
                vertex(grid_x, grid_y + 1),
            )
            center_px = (
                round(sum(point[0] for point in corners) / 4),
                round(sum(point[1] for point in corners) / 4),
            )
            if not _mask_point(clip, center_px):
                continue
            digest = _hash_digest(
                seed, "capital-parcel-cell-v4", capital_id, grid_x, grid_y
            )
            if _unit(digest, 0) < (0.34 if full_material_preview else 0.52):
                draw.polygon(
                    corners,
                    fill=(
                        162 + int(10 * _unit(digest, 4)),
                        134 + int(9 * _unit(digest, 8)),
                        76 + int(8 * _unit(digest, 12)),
                        7 if full_material_preview else 13,
                    ),
                )
            parcels += 1
            for axis, start, end in (
                ("east", corners[1], corners[2]),
                ("south", corners[3], corners[2]),
            ):
                edge_digest = _hash_digest(
                    seed,
                    "capital-parcel-shared-edge-v4",
                    capital_id,
                    grid_x,
                    grid_y,
                    axis,
                )
                if _unit(edge_digest, 8) > (
                    0.46 if full_material_preview else 0.84
                ):
                    continue
                shared_segment(start, end, edge_digest)
                shared_edges += 1
    _alpha_composite_masked(image, layer, clip)
    layer.close()
    clip.close()

    villages = 0
    village_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    village_draw = ImageDraw.Draw(village_layer)
    for _, _, world_x, world_y, digest in iter_anchored_grid(
        transform,
        cell_world=125.0,
        namespace=f"capital-landscape-village-v3:{feature_id(capital)}",
        seed=seed,
        world_bounds=(
            center[0] - outer_radius_x,
            center[1] - outer_radius_y,
            center[0] + outer_radius_x,
            center[1] + outer_radius_y,
        ),
    ):
        normalized = math.hypot(
            (world_x - center[0]) / outer_radius_x,
            (world_y - center[1]) / outer_radius_y,
        )
        if not 0.42 < normalized < 0.96 or _unit(digest, 8) > 0.38:
            continue
        center_px = transform.point_fast((world_x, world_y))
        if not _mask_point(land_mask, center_px):
            continue
        for index in range(5 + int(_unit(digest, 12) * 5)):
            building_digest = _hash_digest(
                seed,
                "capital-landscape-village-building-v3",
                feature_id(capital),
                world_x,
                world_y,
                index,
            )
            angle = math.tau * _unit(building_digest, 0)
            distance = transform.nominal_width_px_fast(
                4 + 13 * _unit(building_digest, 4)
            )
            x = round(center_px[0] + math.cos(angle) * distance)
            y = round(center_px[1] + math.sin(angle) * distance)
            width = 2 + int(_unit(building_digest, 8) * 3)
            height = 1 + int(_unit(building_digest, 12) * 2)
            polygon = _flat_building_polygon(
                x,
                y,
                width,
                height,
                building_digest,
                angle=angle,
            )
            village_draw.polygon(polygon, fill=(139, 91, 55, 150))
            village_draw.line(
                (*polygon, polygon[0]),
                fill=(64, 47, 35, 180),
                width=1,
            )
        villages += 1
    _alpha_composite_masked(image, village_layer, land_mask)
    village_layer.close()
    return {
        "capital_landscape_parcels": parcels,
        "capital_landscape_villages": villages,
        "capital_landscape_tree_belts": tree_belts,
        "capital_landscape_shared_boundary_edges": shared_edges,
        "capital_landscape_isolated_rectangular_parcels": 0,
        "capital_landscape_full_material_reduced_edges": int(
            full_material_preview
        ),
        **clip_stats,
    }


def _draw_riparian_landscape(
    image: Image.Image,
    hydro_features: Iterable[dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
    *,
    full_material_preview: bool = False,
) -> dict[str, int]:
    river_features = [
        feature
        for feature in hydro_features
        if feature.get("properties", {}).get("water_type") == "river_system"
    ]
    river_lines = [
        line
        for feature in river_features
        for line in _iter_world_lines(feature.get("geometry", {}))
    ]
    if not river_lines:
        return {
            "riparian_vegetation": 0,
            "wetland_marks": 0,
            "riparian_interior_edge_breakup_bites": 0,
        }

    corridor = Image.new("L", image.size, 0)
    corridor_draw = ImageDraw.Draw(corridor)
    for feature in river_features:
        for path in line_paths(feature.get("geometry", {}), transform):
            corridor_draw.line(
                path,
                fill=255,
                width=transform.nominal_width_px_fast(90),
                joint="curve",
            )
    canonical_corridor = ImageChops.multiply(corridor, land_mask)
    corridor.close()
    if full_material_preview:
        visual_corridor, edge_bites = _inward_feathered_semantic_mask(
            canonical_corridor,
            transform,
            seed,
            "riparian-procedural-overlay",
            feather_px=27,
            edge_breakup=True,
        )
    else:
        visual_corridor = canonical_corridor.copy()
        edge_bites = 0
    wash = Image.new(
        "RGBA",
        image.size,
        (77, 104, 77, 3 if full_material_preview else 18),
    )
    _alpha_composite_masked(image, wash, visual_corridor)
    wash.close()

    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    vegetation = 0
    wetlands = 0
    for _, _, world_x, world_y, digest in iter_anchored_grid(
        transform,
        cell_world=13.5,
        namespace="riparian-landscape-v3",
        seed=seed,
    ):
        distance, tangent = _nearest_segment((world_x, world_y), river_lines)
        if distance > 58 or _unit(digest, 8) > (
            0.19 if full_material_preview else 0.55
        ):
            continue
        point = transform.point_fast((world_x, world_y))
        if not _mask_point(visual_corridor, point):
            continue
        x, y = point
        if distance < 27:
            length = 2 + int(_unit(digest, 12) * 5)
            draw.line(
                ((x - length, y), (x, y + 1), (x + length, y)),
                fill=(72, 100, 91, 105),
                width=1,
                joint="curve",
            )
            wetlands += 1
        else:
            angle = tangent + math.pi / 2 + (-0.45 + 0.9 * _unit(digest, 12))
            length = 2 + int(_unit(digest, 16) * 5)
            dx = math.cos(angle) * length
            dy = math.sin(angle) * length
            draw.line(
                (
                    (round(x - dx), round(y - dy)),
                    (x, y),
                    (round(x + dx), round(y + dy)),
                ),
                fill=(54, 73, 43, 118),
                width=1,
                joint="curve",
            )
            vegetation += 1
    _alpha_composite_masked(image, layer, visual_corridor)
    layer.close()
    visual_corridor.close()
    canonical_corridor.close()
    return {
        "riparian_vegetation": vegetation,
        "wetland_marks": wetlands,
        "riparian_interior_edge_breakup_bites": edge_bites,
    }


def _draw_mountain_axes(
    image: Image.Image,
    features: Iterable[dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
) -> dict[str, int]:
    stroke_count = 0
    rock_count = 0
    hypsometric_bands = 0
    ridge_axes = 0
    for feature in features:
        properties = feature.get("properties", {})
        if properties.get("terrain_type") != "mountain_axis":
            continue
        lines = list(_iter_world_lines(feature.get("geometry", {})))
        if not lines:
            continue
        nominal_width = float(properties.get("nominal_width", 220))
        half_width = nominal_width / 2
        mask = Image.new("L", image.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        for path in line_paths(feature.get("geometry", {}), transform):
            mask_draw.line(
                path,
                fill=255,
                width=transform.nominal_width_px(nominal_width),
                joint="curve",
            )
        clipped_mask = ImageChops.multiply(mask, land_mask)
        mask.close()

        relief_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        relief_draw = ImageDraw.Draw(relief_layer)
        axis_paths = list(line_paths(feature.get("geometry", {}), transform))
        base_width = transform.nominal_width_px_fast(nominal_width)
        for fraction, color in (
            (1.00, (104, 91, 67, 11)),
            (0.72, (91, 76, 57, 14)),
            (0.46, (77, 63, 48, 17)),
            (0.24, (66, 53, 42, 21)),
        ):
            width_px = max(1, round(base_width * fraction))
            for path in axis_paths:
                relief_draw.line(path, fill=color, width=width_px, joint="curve")
            hypsometric_bands += 1
        for path in axis_paths:
            relief_draw.line(path, fill=(68, 53, 40, 145), width=1, joint="curve")
            ridge_axes += 1
        _alpha_composite_masked(image, relief_layer, clipped_mask)
        relief_layer.close()

        soft_mask = ImageChops.multiply(
            clipped_mask.filter(ImageFilter.GaussianBlur(radius=30)), land_mask
        )
        wash = Image.new("RGBA", image.size, (103, 89, 67, 23))
        _alpha_composite_masked(image, wash, soft_mask)
        wash.close()
        soft_mask.close()

        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        namespace = f"mountain-short-mark-v1:{feature_id(feature)}"
        bbox = _geometry_bbox(feature)
        axis_bounds = (
            None
            if bbox is None
            else (
                bbox[0] - half_width,
                bbox[1] - half_width,
                bbox[2] + half_width,
                bbox[3] + half_width,
            )
        )
        for grid_x, grid_y, world_x, world_y, digest in iter_anchored_grid(
            transform,
            cell_world=13.5,
            namespace=namespace,
            seed=seed,
            margin_cells=3,
            world_bounds=axis_bounds,
        ):
            distance, tangent = _nearest_segment((world_x, world_y), lines)
            if distance > half_width:
                continue
            density = 0.68 - 0.28 * (distance / max(1.0, half_width))
            if _unit(digest, 8) > density:
                continue
            point = transform.point_fast((world_x, world_y))
            if not _mask_point(clipped_mask, point):
                continue
            x, y = point
            jitter = math.radians(-52 + _unit(digest, 12) * 104)
            angle = tangent + math.pi / 2 + jitter
            length_world = 5 + _unit(digest, 16) * 10
            length = transform.nominal_width_px_fast(length_world)
            bend = (-1.0 + _unit(digest, 20) * 2.0) * min(3, length / 5)
            dx = math.cos(angle) * length / 2
            dy = math.sin(angle) * length / 2
            nx = -math.sin(angle) * bend
            ny = math.cos(angle) * bend
            alpha = 112 + int((1 - distance / max(1.0, half_width)) * 68)
            draw.line(
                (
                    (round(x - dx), round(y - dy)),
                    (round(x + nx), round(y + ny)),
                    (round(x + dx), round(y + dy)),
                ),
                fill=(76, 61, 45, alpha),
                width=1 + int(_unit(digest, 24) > 0.82),
                joint="curve",
            )
            stroke_count += 1
            if _unit(digest, 25) < 0.16:
                rock_digest = _hash_digest(seed, namespace, grid_x, grid_y, "rock")
                _draw_irregular_rock(draw, x, y, rock_digest)
                rock_count += 1
        _alpha_composite_masked(image, layer, clipped_mask)
        layer.close()
        clipped_mask.close()
    return {
        "terrain_mountain_axis": stroke_count + rock_count,
        "mountain_short_strokes": stroke_count,
        "mountain_irregular_rocks": rock_count,
        "mountain_hypsometric_bands": hypsometric_bands,
        "mountain_ridge_axes": ridge_axes,
        "oblique_triangle_symbols": 0,
        "continuous_contours": 0,
        "radial_rosettes": 0,
    }


def _draw_gorge_axes(
    image: Image.Image,
    features: Iterable[dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
) -> dict[str, int]:
    tick_count = 0
    stipple_count = 0
    for feature in features:
        properties = feature.get("properties", {})
        if properties.get("terrain_type") != "gorge_axis":
            continue
        lines = list(_iter_world_lines(feature.get("geometry", {})))
        if not lines:
            continue
        nominal_width = float(properties.get("nominal_width", 180))
        half_width = nominal_width / 2
        mask = _terrain_feature_mask(image.size, feature, land_mask, transform)
        if mask.getbbox() is None:
            mask.close()
            continue
        wash = Image.new("RGBA", image.size, (103, 72, 55, 25))
        _alpha_composite_masked(image, wash, mask)
        wash.close()
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        namespace = f"gorge-plan-tick-v2:{feature_id(feature)}"
        bbox = _geometry_bbox(feature)
        axis_bounds = (
            None
            if bbox is None
            else (
                bbox[0] - half_width,
                bbox[1] - half_width,
                bbox[2] + half_width,
                bbox[3] + half_width,
            )
        )
        for _, _, world_x, world_y, digest in iter_anchored_grid(
            transform,
            cell_world=10.0,
            namespace=namespace,
            seed=seed,
            margin_cells=3,
            world_bounds=axis_bounds,
        ):
            distance, tangent = _nearest_segment((world_x, world_y), lines)
            if distance > half_width or _unit(digest, 8) > 0.63:
                continue
            point = transform.point_fast((world_x, world_y))
            if not _mask_point(mask, point):
                continue
            x, y = point
            angle = tangent + math.pi / 2 + (-0.34 + 0.68 * _unit(digest, 12))
            length = transform.nominal_width_px_fast(2.0 + 5.0 * _unit(digest, 16))
            dx = math.cos(angle) * length
            dy = math.sin(angle) * length
            draw.line(
                (round(x - dx), round(y - dy), round(x + dx), round(y + dy)),
                fill=(89, 60, 48, 135),
                width=1,
            )
            tick_count += 1
            if _unit(digest, 20) < 0.32:
                draw.point(
                    (x + int(-math.sin(angle) * 3), y + int(math.cos(angle) * 3)),
                    fill=(89, 60, 48, 115),
                )
                stipple_count += 1
        _alpha_composite_masked(image, layer, mask)
        layer.close()
        mask.close()
    return {
        "terrain_gorge_axis": tick_count + stipple_count,
        "gorge_cross_ticks": tick_count,
        "gorge_stipple": stipple_count,
        "cliff_side_faces": 0,
    }


def _flat_building_polygon(
    x: int,
    y: int,
    width: int,
    height: int,
    digest: bytes,
    angle: float | None = None,
) -> list[tuple[int, int]]:
    variant = int(_unit(digest, 24) * 5) % 5
    chamfer = 0.12 + 0.22 * _unit(digest, 27)
    if variant == 0:
        local = [
            (-1.0 + chamfer, -1.0),
            (1.0, -1.0 + chamfer * 0.45),
            (1.0 - chamfer * 0.35, 1.0),
            (-1.0, 1.0 - chamfer),
        ]
    elif variant == 1:
        inset = 0.12 + 0.34 * _unit(digest, 29)
        local = [
            (-1.0, -1.0),
            (1.0, -1.0),
            (1.0, -0.15),
            (inset, -0.15),
            (inset, 1.0),
            (-1.0, 1.0),
        ]
    elif variant == 2:
        taper = 0.16 + 0.30 * _unit(digest, 2)
        local = [
            (-1.0, -0.72),
            (-0.42, -1.0),
            (1.0, -0.72 + taper * 0.25),
            (1.0 - taper, 0.82),
            (-0.75, 1.0),
        ]
    elif variant == 3:
        notch = 0.18 + 0.30 * _unit(digest, 27)
        local = [
            (-1.0, -1.0),
            (0.20, -1.0),
            (1.0, -0.52 - notch * 0.16),
            (1.0 - notch * 0.25, 1.0),
            (-0.34 - notch * 0.25, 1.0),
            (-1.0, 0.24 + notch * 0.22),
        ]
    else:
        court = 0.22 + 0.26 * _unit(digest, 29)
        local = [
            (-1.0, -1.0),
            (1.0, -1.0),
            (1.0, 1.0),
            (court, 1.0),
            (court, -0.05),
            (-court, -0.05),
            (-court, 1.0),
            (-1.0, 1.0),
        ]
    if angle is None:
        quarter_turn = int(_unit(digest, 4) * 4) * (math.pi / 2)
        angle = quarter_turn + (-0.11 + 0.22 * _unit(digest, 8))
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return [
        (
            round(x + px * width * cosine - py * height * sine),
            round(y + px * width * sine + py * height * cosine),
        )
        for px, py in local
    ]


def _organic_settlement_polygon(
    feature: dict[str, Any],
    seed: int,
    *,
    scale: float,
) -> list[tuple[float, float]]:
    bbox = _geometry_bbox(feature)
    if bbox is None:
        return []
    min_x, min_y, max_x, max_y = bbox
    feature_name = feature_id(feature)
    center_digest = _hash_digest(seed, "settlement-organic-center-v3", feature_name)
    center_x = (min_x + max_x) / 2 + (max_x - min_x) * (
        -0.025 + 0.05 * _unit(center_digest, 0)
    )
    center_y = (min_y + max_y) / 2 + (max_y - min_y) * (
        -0.025 + 0.05 * _unit(center_digest, 4)
    )
    radius_x = (max_x - min_x) * 0.5 * scale
    radius_y = (max_y - min_y) * 0.5 * scale
    node_type = str(feature.get("properties", {}).get("node_type", "town"))
    vertex_count = 44 if node_type == "capital" else 32
    phase = math.tau * _unit(center_digest, 8)
    harmonic_phase = math.tau * _unit(center_digest, 12)
    raw: list[float] = []
    for index in range(vertex_count):
        angle = phase + math.tau * index / vertex_count
        digest = _hash_digest(
            seed,
            "settlement-organic-radius-v4",
            feature_name,
            index,
        )
        random_term = -0.10 + 0.20 * _unit(digest, 0)
        district_lobes = 0.055 * math.sin(angle * 3 + harmonic_phase)
        smaller_lobes = 0.035 * math.sin(angle * 7 - harmonic_phase * 0.7)
        if node_type == "floating_island":
            district_lobes *= 1.35
            smaller_lobes *= 1.25
        raw.append(0.86 + random_term + district_lobes + smaller_lobes)
    smoothed = [
        (
            raw[index - 2]
            + raw[index - 1] * 2
            + raw[index] * 4
            + raw[(index + 1) % vertex_count] * 2
            + raw[(index + 2) % vertex_count]
        )
        / 10
        for index in range(vertex_count)
    ]
    shear = -0.08 + 0.16 * _unit(center_digest, 20)
    points: list[tuple[float, float]] = []
    for index, radial in enumerate(smoothed):
        angle = phase + math.tau * index / vertex_count
        local_x = math.cos(angle) * radius_x * radial
        local_y = math.sin(angle) * radius_y * radial
        points.append(
            (
                center_x + local_x + local_y * shear,
                center_y + local_y,
            )
        )
    return points


def _world_polygon_mask(
    size: tuple[int, int],
    points: Sequence[tuple[float, float]],
    transform: SheetCanvasTransform,
) -> Image.Image:
    mask = Image.new("L", size, 0)
    if len(points) >= 3:
        ImageDraw.Draw(mask).polygon(
            [transform.point(point) for point in points], fill=255
        )
    return mask


def _scale_world_polygon(
    points: Sequence[tuple[float, float]],
    center: tuple[float, float],
    scale: float,
) -> list[tuple[float, float]]:
    return [
        (
            center[0] + (point[0] - center[0]) * scale,
            center[1] + (point[1] - center[1]) * scale,
        )
        for point in points
    ]


def _quadratic_world_path(
    start: tuple[float, float],
    control: tuple[float, float],
    end: tuple[float, float],
    transform: SheetCanvasTransform,
    *,
    steps: int = 24,
) -> list[tuple[int, int]]:
    points = []
    for index in range(steps + 1):
        ratio = index / steps
        inverse = 1 - ratio
        points.append(
            transform.point_fast(
                (
                    inverse * inverse * start[0]
                    + 2 * inverse * ratio * control[0]
                    + ratio * ratio * end[0],
                    inverse * inverse * start[1]
                    + 2 * inverse * ratio * control[1]
                    + ratio * ratio * end[1],
                )
            )
        )
    return points


def _settlement_lod_profile(native_zoom: int, node_type: str) -> dict[str, Any]:
    if native_zoom >= 8:
        return {
            "level": "building",
            "cell_world": SETTLEMENT_CELL_WORLD.get(node_type, 2.25),
            "main_px": 4,
            "secondary_px": 2,
            "lane_px": 1,
        }
    if native_zoom >= 7:
        return {
            "level": "parcel",
            "cell_world": 5.5 if node_type == "capital" else 6.5,
            "main_px": 3,
            "secondary_px": 2,
            "lane_px": 1,
        }
    return {
        "level": "district-block",
        "cell_world": 6.0 if node_type == "capital" else 8.0,
        "main_px": 3,
        "secondary_px": 1,
        "lane_px": 1,
    }


def _nearest_water_direction(
    land_mask: Image.Image,
    center: tuple[int, int],
) -> tuple[float, float]:
    best = (math.inf, 0.0, -1.0)
    for index in range(24):
        angle = math.tau * index / 24
        dx = math.cos(angle)
        dy = math.sin(angle)
        for distance in range(4, 421, 4):
            point = (round(center[0] + dx * distance), round(center[1] + dy * distance))
            if not _mask_point(land_mask, point):
                if distance < best[0]:
                    best = (float(distance), dx, dy)
                break
    return best[1], best[2]


def _draw_settlements(
    image: Image.Image,
    features: Iterable[dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
    transport_features: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    total = 0
    courtyards = 0
    feature_count = 0
    main_streets = 0
    secondary_streets = 0
    lanes = 0
    plazas = 0
    citadels = 0
    harbor_basins = 0
    suburban_blocks = 0
    environ_parcels = 0
    canals = 0
    transport_gate_snaps = 0
    render_cells: list[float] = []
    for feature in features:
        feature_bounds = _geometry_bbox(feature)
        if feature_bounds is None or not _intersects(feature_bounds, transform.bounds):
            continue
        node_type = str(feature.get("properties", {}).get("node_type", "town"))
        source_mask = feature_mask(image.size, feature, transform)
        outer_world = _organic_settlement_polygon(feature, seed, scale=0.90)
        urban_scale = 0.66 if node_type == "capital" else 0.60
        if node_type in {"port", "underwater_city"}:
            urban_scale = 0.64
        urban_world = _organic_settlement_polygon(feature, seed, scale=urban_scale)
        outer_mask_raw = _world_polygon_mask(image.size, outer_world, transform)
        urban_mask_raw = _world_polygon_mask(image.size, urban_world, transform)
        outer_mask = ImageChops.multiply(source_mask, outer_mask_raw)
        mask = ImageChops.multiply(urban_mask_raw, land_mask)
        outer_mask = ImageChops.multiply(outer_mask, land_mask)
        source_mask.close()
        outer_mask_raw.close()
        urban_mask_raw.close()
        bbox = mask.getbbox()
        if bbox is None:
            mask.close()
            outer_mask.close()
            continue

        feature_count += 1
        feature_name = feature_id(feature)
        center_world = (
            (feature_bounds[0] + feature_bounds[2]) / 2,
            (feature_bounds[1] + feature_bounds[3]) / 2,
        )
        center_px = transform.point_fast(center_world)
        lod = _settlement_lod_profile(int(transform.sheet["native_zoom"]), node_type)
        cell_world = float(lod["cell_world"])
        render_cells.append(cell_world)

        wash = Image.new(
            "RGBA",
            image.size,
            (143, 101, 65, 32) if node_type != "underwater_city" else (93, 105, 96, 28),
        )
        _alpha_composite_masked(image, wash, mask)
        wash.close()

        environ_mask = ImageChops.subtract(outer_mask, mask)
        parcel_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        parcel_draw = ImageDraw.Draw(parcel_layer)
        for _, _, world_x, world_y, digest in iter_anchored_grid(
            transform,
            cell_world=18.0 if node_type == "capital" else 24.0,
            namespace=f"settlement-environs-parcel-v3:{feature_name}",
            seed=seed,
            world_bounds=feature_bounds,
        ):
            point = transform.point_fast((world_x, world_y))
            if not _mask_point(environ_mask, point) or _unit(digest, 8) > 0.76:
                continue
            x, y = point
            angle = math.tau * _unit(digest, 12)
            length = transform.nominal_width_px_fast(5.0 + 8.0 * _unit(digest, 16))
            offset = transform.nominal_width_px_fast(2.0 + 2.5 * _unit(digest, 20))
            dx = math.cos(angle) * length
            dy = math.sin(angle) * length
            nx = -math.sin(angle) * offset
            ny = math.cos(angle) * offset
            parcel_draw.line(
                (round(x - dx), round(y - dy), round(x + dx), round(y + dy)),
                fill=(116, 91, 53, 112),
                width=1,
            )
            parcel_draw.line(
                (
                    round(x - dx + nx),
                    round(y - dy + ny),
                    round(x + dx * 0.7 + nx),
                    round(y + dy * 0.7 + ny),
                ),
                fill=(116, 91, 53, 92),
                width=1,
            )
            environ_parcels += 1
        _alpha_composite_masked(image, parcel_layer, environ_mask)
        parcel_layer.close()
        environ_mask.close()

        street_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        street_draw = ImageDraw.Draw(street_layer)
        street_mask = Image.new("L", image.size, 0)
        street_mask_draw = ImageDraw.Draw(street_mask)
        urban_pixels = [transform.point_fast(point) for point in urban_world]
        gate_count = 4 if node_type in {"capital", "port"} else 5
        phase_digest = _hash_digest(seed, "settlement-street-phase-v3", feature_name)
        phase_index = int(_unit(phase_digest, 0) * len(urban_world))
        gate_points: list[tuple[float, float]] = []
        proximity = max(
            24.0,
            min(
                feature_bounds[2] - feature_bounds[0],
                feature_bounds[3] - feature_bounds[1],
            )
            * 0.18,
        )
        for transport_feature in transport_features:
            route_type = transport_feature.get("properties", {}).get("route_type")
            if route_type not in {"road", "rail"}:
                continue
            for line in _iter_world_lines(transport_feature.get("geometry", {})):
                for route_start, route_end in zip(line, line[1:]):
                    for edge_start, edge_end in zip(
                        urban_world,
                        (*urban_world[1:], urban_world[0]),
                    ):
                        intersection = _segment_intersection(
                            route_start,
                            route_end,
                            edge_start,
                            edge_end,
                        )
                        if intersection is None or any(
                            math.hypot(
                                intersection[0] - existing[0],
                                intersection[1] - existing[1],
                            )
                            < 2.0
                            for existing in gate_points
                        ):
                            continue
                        gate_points.append(intersection)
                        transport_gate_snaps += 1
                for point_index, point in enumerate(line):
                    if (
                        math.hypot(
                            point[0] - center_world[0], point[1] - center_world[1]
                        )
                        > proximity
                    ):
                        continue
                    neighbors = []
                    if point_index:
                        neighbors.append(line[point_index - 1])
                    if point_index + 1 < len(line):
                        neighbors.append(line[point_index + 1])
                    for neighbor in neighbors:
                        direction = math.atan2(
                            neighbor[1] - center_world[1],
                            neighbor[0] - center_world[0],
                        )
                        candidate_index = min(
                            range(len(urban_world)),
                            key=lambda index: abs(
                                math.atan2(
                                    math.sin(
                                        math.atan2(
                                            urban_world[index][1] - center_world[1],
                                            urban_world[index][0] - center_world[0],
                                        )
                                        - direction
                                    ),
                                    math.cos(
                                        math.atan2(
                                            urban_world[index][1] - center_world[1],
                                            urban_world[index][0] - center_world[0],
                                        )
                                        - direction
                                    ),
                                )
                            ),
                        )
                        candidate = urban_world[candidate_index]
                        if not any(
                            math.hypot(
                                candidate[0] - existing[0],
                                candidate[1] - existing[1],
                            )
                            < 2.0
                            for existing in gate_points
                        ):
                            gate_points.append(candidate)
        fallback_gate_indices = [
            (phase_index + round(index * len(urban_world) / gate_count))
            % len(urban_world)
            for index in range(gate_count)
        ]
        for candidate in fallback_gate_indices:
            fallback = urban_world[candidate]
            if not any(
                math.hypot(
                    fallback[0] - existing[0], fallback[1] - existing[1]
                )
                < 2.0
                for existing in gate_points
            ):
                gate_points.append(fallback)
            if len(gate_points) >= gate_count:
                break
        gate_points = gate_points[:gate_count]
        if node_type == "capital":
            subcenters_world = [
                (
                    center_world[0]
                    + math.cos(math.tau * index / 3 + 0.35)
                    * (feature_bounds[2] - feature_bounds[0])
                    * 0.13,
                    center_world[1]
                    + math.sin(math.tau * index / 3 + 0.35)
                    * (feature_bounds[3] - feature_bounds[1])
                    * 0.13,
                )
                for index in range(3)
            ]
        else:
            subcenters_world = [center_world]
        for index, gate in enumerate(gate_points):
            start_world = subcenters_world[index % len(subcenters_world)]
            dx = gate[0] - start_world[0]
            dy = gate[1] - start_world[1]
            bend_digest = _hash_digest(
                seed, "settlement-main-street-v3", feature_name, index
            )
            bend = (-0.11 + 0.22 * _unit(bend_digest, 0)) * math.hypot(dx, dy)
            length = max(1.0, math.hypot(dx, dy))
            control = (
                start_world[0] + dx * 0.52 - dy / length * bend,
                start_world[1] + dy * 0.52 + dx / length * bend,
            )
            path = _quadratic_world_path(start_world, control, gate, transform)
            street_draw.line(
                path, fill=(69, 49, 35, 230), width=lod["main_px"] + 2, joint="curve"
            )
            street_draw.line(
                path, fill=(205, 175, 115, 245), width=lod["main_px"], joint="curve"
            )
            street_mask_draw.line(
                path, fill=255, width=lod["main_px"] + 8, joint="curve"
            )
            main_streets += 1

        if node_type == "capital":
            for index, start_world in enumerate(subcenters_world):
                end_world = subcenters_world[(index + 1) % len(subcenters_world)]
                control = (
                    (start_world[0] + end_world[0]) / 2
                    + (center_world[0] - (start_world[0] + end_world[0]) / 2) * 0.32,
                    (start_world[1] + end_world[1]) / 2
                    + (center_world[1] - (start_world[1] + end_world[1]) / 2) * 0.32,
                )
                path = _quadratic_world_path(
                    start_world,
                    control,
                    end_world,
                    transform,
                    steps=16,
                )
                street_draw.line(
                    path,
                    fill=(102, 76, 48, 205),
                    width=lod["secondary_px"],
                    joint="curve",
                )
                street_mask_draw.line(
                    path,
                    fill=255,
                    width=lod["secondary_px"] + 5,
                    joint="curve",
                )
                plaza_center = transform.point_fast(start_world)
                plaza_radius_px = transform.nominal_width_px_fast(5.0)
                district_plaza = [
                    (plaza_center[0] - plaza_radius_px, plaza_center[1] - 1),
                    (plaza_center[0] - 1, plaza_center[1] - plaza_radius_px),
                    (plaza_center[0] + plaza_radius_px, plaza_center[1] + 1),
                    (plaza_center[0] + 1, plaza_center[1] + plaza_radius_px),
                ]
                street_draw.polygon(district_plaza, fill=(203, 178, 119, 235))
                street_draw.line(
                    (*district_plaza, district_plaza[0]),
                    fill=(82, 61, 42, 185),
                    width=1,
                )
                street_mask_draw.polygon(district_plaza, fill=255)
                secondary_streets += 1
                plazas += 1

            canal_start = urban_world[len(urban_world) // 5]
            canal_end = urban_world[(len(urban_world) * 4) // 5]
            canal_control = (
                center_world[0] + (feature_bounds[2] - feature_bounds[0]) * 0.08,
                center_world[1] - (feature_bounds[3] - feature_bounds[1]) * 0.11,
            )
            canal_path = _quadratic_world_path(
                canal_start,
                canal_control,
                canal_end,
                transform,
                steps=28,
            )
            street_draw.line(
                canal_path,
                fill=(54, 59, 52, 175),
                width=3,
                joint="curve",
            )
            street_draw.line(
                canal_path,
                fill=(68, 113, 130, 230),
                width=1,
                joint="curve",
            )
            street_mask_draw.line(
                canal_path,
                fill=255,
                width=7,
                joint="curve",
            )
            canals += 1

        for scale in (0.34, 0.58) if node_type == "capital" else (0.50,):
            scaled = _scale_world_polygon(urban_world, center_world, scale)
            pixels = [transform.point_fast(point) for point in scaled]
            street_draw.line(
                (*pixels, pixels[0]),
                fill=(102, 76, 48, 210),
                width=lod["secondary_px"],
                joint="curve",
            )
            street_mask_draw.line(
                (*pixels, pixels[0]),
                fill=255,
                width=lod["secondary_px"] + 5,
                joint="curve",
            )
            secondary_streets += 1

        lane_count = 13 if node_type == "capital" else 7
        for index in range(lane_count):
            lane_digest = _hash_digest(
                seed, "settlement-lane-v4", feature_name, index
            )
            anchor_angle = math.tau * _unit(lane_digest, 0)
            anchor_radius = 0.28 + 0.40 * _unit(lane_digest, 4)
            radius_x = (feature_bounds[2] - feature_bounds[0]) * urban_scale * 0.5
            radius_y = (feature_bounds[3] - feature_bounds[1]) * urban_scale * 0.5
            anchor = (
                center_world[0] + math.cos(anchor_angle) * radius_x * anchor_radius,
                center_world[1] + math.sin(anchor_angle) * radius_y * anchor_radius,
            )
            angle = math.tau * _unit(lane_digest, 8)
            half_length_x = radius_x * (0.07 + 0.11 * _unit(lane_digest, 12))
            half_length_y = radius_y * (0.07 + 0.11 * _unit(lane_digest, 16))
            start = (
                anchor[0] - math.cos(angle) * half_length_x,
                anchor[1] - math.sin(angle) * half_length_y,
            )
            end = (
                anchor[0] + math.cos(angle) * half_length_x,
                anchor[1] + math.sin(angle) * half_length_y,
            )
            control = (
                anchor[0]
                + math.sin(angle) * radius_x * (-0.04 + 0.08 * _unit(lane_digest, 20)),
                anchor[1]
                - math.cos(angle) * radius_y * (-0.04 + 0.08 * _unit(lane_digest, 24)),
            )
            path = _quadratic_world_path(start, control, end, transform, steps=12)
            street_draw.line(
                path, fill=(117, 88, 55, 175), width=lod["lane_px"], joint="curve"
            )
            street_mask_draw.line(
                path, fill=255, width=lod["lane_px"] + 3, joint="curve"
            )
            lanes += 1

        plaza_digest = _hash_digest(seed, "settlement-plaza-v3", feature_name)
        plaza_world = []
        plaza_radius = 11.0 if node_type == "capital" else 7.0
        for index in range(7):
            angle = math.tau * index / 7 + 0.20 * _unit(plaza_digest, 3 + index)
            radius = plaza_radius * (0.72 + 0.38 * _unit(plaza_digest, 9 + index * 2))
            plaza_world.append(
                (
                    center_world[0] + math.cos(angle) * radius,
                    center_world[1] + math.sin(angle) * radius,
                )
            )
        plaza_pixels = [transform.point_fast(point) for point in plaza_world]
        street_draw.polygon(plaza_pixels, fill=(213, 187, 126, 245))
        street_draw.line(
            (*plaza_pixels, plaza_pixels[0]), fill=(73, 53, 37, 220), width=1
        )
        street_mask_draw.polygon(plaza_pixels, fill=255)
        plazas += 1

        if node_type == "capital":
            citadel_world = _scale_world_polygon(plaza_world, center_world, 0.45)
            citadel_pixels = [transform.point_fast(point) for point in citadel_world]
            street_draw.polygon(citadel_pixels, fill=(145, 91, 54, 220))
            street_draw.line(
                (*citadel_pixels, citadel_pixels[0]), fill=(57, 42, 32, 245), width=2
            )
            citadels += 1

        if node_type == "port":
            water_dx, water_dy = _nearest_water_direction(land_mask, center_px)
            tangent_x, tangent_y = -water_dy, water_dx
            for index in (-1, 1):
                basin_center = (
                    center_px[0] + round(water_dx * 34 + tangent_x * index * 20),
                    center_px[1] + round(water_dy * 34 + tangent_y * index * 20),
                )
                basin = [
                    (
                        basin_center[0] + round(water_dx * forward + tangent_x * side),
                        basin_center[1] + round(water_dy * forward + tangent_y * side),
                    )
                    for forward, side in ((-16, -8), (17, -6), (14, 7), (-14, 9))
                ]
                street_draw.polygon(basin, fill=(67, 110, 128, 230))
                street_draw.line((*basin, basin[0]), fill=(57, 51, 40, 220), width=1)
                street_mask_draw.polygon(basin, fill=255)
                harbor_basins += 1

        building_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        building_draw = ImageDraw.Draw(building_layer)
        namespace = f"settlement-{lod['level']}-v3:{feature_name}"
        for _, _, world_x, world_y, digest in iter_anchored_grid(
            transform,
            cell_world=cell_world,
            namespace=namespace,
            seed=seed,
            world_bounds=feature_bounds,
        ):
            point = transform.point_fast((world_x, world_y))
            in_urban = _mask_point(mask, point)
            in_outer = _mask_point(outer_mask, point)
            if not in_outer or _mask_point(street_mask, point):
                continue
            x, y = point
            courtyard_threshold = (
                0.09 if node_type == "capital" and in_urban else 0.15 if in_urban else 0.38
            )
            if _unit(digest, 9) < courtyard_threshold:
                courtyards += 1
                continue
            district_digest = _hash_digest(
                seed,
                "settlement-district-orientation-v3",
                feature_name,
                math.floor(world_x / 48),
                math.floor(world_y / 48),
            )
            half_width_world = max(1.0, (feature_bounds[2] - feature_bounds[0]) / 2)
            half_height_world = max(1.0, (feature_bounds[3] - feature_bounds[1]) / 2)
            radial_distance = math.hypot(
                (world_x - center_world[0]) / half_width_world,
                (world_y - center_world[1]) / half_height_world,
            )
            district_density = (
                0.67 + 0.31 * _unit(district_digest, 12)
                if node_type == "capital" and in_urban
                else 0.58 + 0.38 * _unit(district_digest, 12)
            )
            density = (
                max(
                    0.44 if node_type == "capital" else 0.38,
                    (0.90 if node_type == "capital" else 0.84)
                    - radial_distance * (0.20 if node_type == "capital" else 0.24),
                )
                * district_density
                if in_urban
                else 0.18
            )
            if _unit(digest, 10) > density:
                continue
            radial = math.atan2(world_y - center_world[1], world_x - center_world[0])
            orientation = (
                radial + math.pi / 2
                if _unit(district_digest, 0) < 0.58
                else math.tau * _unit(district_digest, 4)
            )
            orientation += -0.16 + 0.32 * _unit(digest, 6)
            width = max(
                1,
                transform.nominal_width_px_fast(
                    cell_world * (0.25 + 0.34 * _unit(digest, 12))
                ),
            )
            height = max(
                1,
                transform.nominal_width_px_fast(
                    cell_world * (0.18 + 0.30 * _unit(digest, 16))
                ),
            )
            polygon = _flat_building_polygon(
                x,
                y,
                width,
                height,
                digest,
                angle=orientation,
            )
            tone = -12 + int(24 * _unit(digest, 20))
            fill = (
                (148 + tone, 94 + tone // 2, 56 + tone // 3, 158 if in_urban else 112)
                if node_type not in {"underwater_city", "air_terminal"}
                else (120, 105, 80, 145)
            )
            building_draw.polygon(polygon, fill=fill)
            building_draw.line((*polygon, polygon[0]), fill=(62, 45, 34, 190), width=1)
            total += 1
            if not in_urban:
                suburban_blocks += 1

        _alpha_composite_masked(image, building_layer, outer_mask)
        building_layer.close()
        _alpha_composite_masked(image, street_layer, outer_mask)
        street_layer.close()

        wall_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        wall_draw = ImageDraw.Draw(wall_layer)
        if node_type in {"capital", "city", "port", "town"}:
            wall_draw.line(
                (*urban_pixels, urban_pixels[0]),
                fill=(63, 47, 35, 230),
                width=2 if node_type == "capital" else 1,
                joint="curve",
            )
        _alpha_composite_masked(image, wall_layer, outer_mask)
        wall_layer.close()
        street_mask.close()
        mask.close()
        outer_mask.close()
    return {
        "settlement_features": feature_count,
        "settlement_building_footprints": total,
        "settlement_main_streets": main_streets,
        "settlement_secondary_streets": secondary_streets,
        "settlement_lanes": lanes,
        "settlement_courtyards": courtyards,
        "settlement_plazas": plazas,
        "settlement_citadels": citadels,
        "settlement_harbor_basins": harbor_basins,
        "settlement_suburban_blocks": suburban_blocks,
        "settlement_environs_parcels": environ_parcels,
        "settlement_canals": canals,
        "settlement_transport_gate_snaps": transport_gate_snaps,
        "settlement_lod_level": _settlement_lod_profile(
            int(transform.sheet["native_zoom"]), "capital"
        )["level"],
        "settlement_render_cell_world_min": min(render_cells, default=0.0),
        "settlement_render_cell_world_max": max(render_cells, default=0.0),
        "settlement_cell_world_min": min(SETTLEMENT_CELL_WORLD.values()),
        "settlement_cell_world_max": max(SETTLEMENT_CELL_WORLD.values()),
        "settlement_rectangular_grid_blocks": 0,
        "roof_faces": 0,
        "facades": 0,
        "cast_shadows": 0,
    }


def _meander_pixel_path(
    path: Sequence[tuple[int, int]],
    *,
    seed: int,
    namespace: str,
    amplitude_px: int,
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for segment_index, (start, end) in enumerate(zip(path, path[1:])):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length == 0:
            continue
        steps = max(2, math.ceil(length / 18))
        normal_x = -dy / length
        normal_y = dx / length
        digest = _hash_digest(seed, namespace, segment_index)
        phase = math.tau * _unit(digest, 0)
        cycles = 1.0 + int(_unit(digest, 4) * 3)
        for index in range(steps + 1):
            if segment_index and index == 0:
                continue
            ratio = index / steps
            envelope = math.sin(math.pi * ratio)
            offset = (
                math.sin(math.tau * cycles * ratio + phase) * amplitude_px * envelope
            )
            result.append(
                (
                    round(start[0] + dx * ratio + normal_x * offset),
                    round(start[1] + dy * ratio + normal_y * offset),
                )
            )
    return result or list(path)


def _catmull_rom_pixel_path(
    path: Sequence[tuple[int, int]],
    *,
    maximum_step_px: float = 8.0,
    maximum_curve_deviation_px: float = 14.0,
    tension: float = 0.42,
) -> tuple[list[tuple[int, int]], float]:
    """Interpolate a smooth cardinal Catmull-Rom path through exact vertices."""

    if len(path) < 2:
        return list(path), 0.0
    result: list[tuple[int, int]] = []
    maximum_displacement = 0.0
    tangent_scale = (1.0 - tension) / 2.0
    for segment_index in range(len(path) - 1):
        p0 = path[max(0, segment_index - 1)]
        p1 = path[segment_index]
        p2 = path[segment_index + 1]
        p3 = path[min(len(path) - 1, segment_index + 2)]
        distance = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        steps = max(2, math.ceil(distance / maximum_step_px))
        tangent_1 = (
            (p2[0] - p0[0]) * tangent_scale,
            (p2[1] - p0[1]) * tangent_scale,
        )
        tangent_2 = (
            (p3[0] - p1[0]) * tangent_scale,
            (p3[1] - p1[1]) * tangent_scale,
        )
        for step in range(steps + 1):
            if segment_index and step == 0:
                continue
            ratio = step / steps
            if step == 0:
                point = p1
            elif step == steps:
                point = p2
            else:
                ratio_2 = ratio * ratio
                ratio_3 = ratio_2 * ratio
                h00 = 2 * ratio_3 - 3 * ratio_2 + 1
                h10 = ratio_3 - 2 * ratio_2 + ratio
                h01 = -2 * ratio_3 + 3 * ratio_2
                h11 = ratio_3 - ratio_2
                linear = (
                    p1[0] + (p2[0] - p1[0]) * ratio,
                    p1[1] + (p2[1] - p1[1]) * ratio,
                )
                smooth = (
                    h00 * p1[0]
                    + h10 * tangent_1[0]
                    + h01 * p2[0]
                    + h11 * tangent_2[0],
                    h00 * p1[1]
                    + h10 * tangent_1[1]
                    + h01 * p2[1]
                    + h11 * tangent_2[1],
                )
                delta_x = smooth[0] - linear[0]
                delta_y = smooth[1] - linear[1]
                displacement = math.hypot(delta_x, delta_y)
                if displacement > maximum_curve_deviation_px:
                    clamp = maximum_curve_deviation_px / displacement
                    smooth = (
                        linear[0] + delta_x * clamp,
                        linear[1] + delta_y * clamp,
                    )
                point = (round(smooth[0]), round(smooth[1]))
                maximum_displacement = max(
                    maximum_displacement,
                    math.hypot(point[0] - linear[0], point[1] - linear[1]),
                )
            if not result or result[-1] != point:
                result.append(point)
    if result[0] != path[0] or result[-1] != path[-1]:
        raise ReviewedMasterError("river interpolation changed a canonical endpoint")
    if any(vertex not in result for vertex in path):
        raise ReviewedMasterError("river interpolation skipped a canonical vertex")
    return result, maximum_displacement


def _natural_bank_paths(
    path: Sequence[tuple[int, int]],
    *,
    distance_px: float,
    seed: int,
    namespace: str,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    left: list[tuple[int, int]] = []
    right: list[tuple[int, int]] = []
    for index, point in enumerate(path):
        previous = path[max(0, index - 1)]
        following = path[min(len(path) - 1, index + 1)]
        dx = following[0] - previous[0]
        dy = following[1] - previous[1]
        length = max(1.0, math.hypot(dx, dy))
        digest = _hash_digest(seed, namespace, index // 5)
        breathing = 0.76 + 0.40 * _unit(digest, 0)
        offset_x = -dy / length * distance_px * breathing
        offset_y = dx / length * distance_px * breathing
        left.append((round(point[0] + offset_x), round(point[1] + offset_y)))
        right.append((round(point[0] - offset_x), round(point[1] - offset_y)))
    return left, right


def _draw_rivers(
    image: Image.Image,
    features: Iterable[dict[str, Any]],
    transform: SheetCanvasTransform,
    sheet_type: str,
    seed: int,
    *,
    full_material_preview: bool = False,
) -> dict[str, Any]:
    caps = STROKE_CAPS_PX.get(sheet_type, STROKE_CAPS_PX["region"])
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    maximum_core = 0
    maximum_casing = 0
    centerline_count = 0
    maximum_meander = 0
    bank_traces = 0
    layered_channels = 0
    inner_flow_threads = 0
    preserved_control_vertices = 0
    for feature in features:
        properties = feature.get("properties", {})
        water_type = properties.get("water_type")
        if water_type not in {"river_system", "seasonal_channel_system"}:
            continue
        nominal = float(properties.get("nominal_width", 6))
        nominal_px = transform.nominal_width_px_fast(nominal)
        width = min(caps["river"], max(1, round(math.sqrt(nominal_px))))
        casing = min(caps["river_casing"], width + 2)
        for path_index, path in enumerate(
            line_paths(feature.get("geometry", {}), transform)
        ):
            path_length = sum(
                math.hypot(end[0] - start[0], end[1] - start[1])
                for start, end in zip(path, path[1:])
            )
            visible_path, interpolation_displacement = _catmull_rom_pixel_path(
                path,
                maximum_step_px=max(5.0, min(9.0, math.sqrt(path_length) * 0.20)),
                maximum_curve_deviation_px=14.0,
                tension=0.42,
            )
            preserved_control_vertices += len(path)
            draw.line(path, fill=(72, 105, 116, 30), width=1, joint="curve")
            if water_type == "seasonal_channel_system":
                _draw_dashed_line(
                    draw,
                    visible_path,
                    fill=(58, 91, 101, 190),
                    width=1,
                    dash=10,
                    gap=7,
                )
                maximum_core = max(maximum_core, 1)
            else:
                left_bank, right_bank = _natural_bank_paths(
                    visible_path,
                    distance_px=max(2.0, casing / 2 + 1.5),
                    seed=seed,
                    namespace=f"river-bank-v4:{feature_id(feature)}:{path_index}",
                )
                for bank in (left_bank, right_bank):
                    _draw_dashed_line(
                        draw,
                        bank,
                        fill=(67, 63, 48, 92),
                        width=1,
                        dash=18,
                        gap=7,
                    )
                    bank_traces += 1
                draw.line(
                    visible_path,
                    fill=(52, 60, 53, 160) if full_material_preview else (54, 59, 52, 170),
                    width=casing,
                    joint="curve",
                )
                draw.line(
                    visible_path,
                    fill=(58, 100, 117, 232)
                    if full_material_preview
                    else (66, 112, 133, 245),
                    width=width,
                    joint="curve",
                )
                if full_material_preview and width >= 3:
                    inner_width = max(1, width - 2)
                    draw.line(
                        visible_path,
                        fill=(83, 126, 137, 167),
                        width=inner_width,
                        joint="curve",
                    )
                    _draw_dashed_line(
                        draw,
                        visible_path,
                        fill=(154, 169, 151, 91),
                        width=1,
                        dash=7 + (path_index % 4),
                        gap=13 + (path_index % 5),
                    )
                    layered_channels += 1
                    inner_flow_threads += 1
                maximum_core = max(maximum_core, width)
                maximum_casing = max(maximum_casing, casing)
            maximum_meander = max(
                maximum_meander,
                round(interpolation_displacement),
            )
            centerline_count += 1
    image.alpha_composite(layer)
    layer.close()
    return {
        "river_centerlines": centerline_count,
        "river_core_max_px": maximum_core,
        "river_casing_max_px": maximum_casing,
        "river_centerline_coordinate_offsets": 0,
        "river_visible_meander_max_px": maximum_meander,
        "river_canonical_control_threads": centerline_count,
        "river_canonical_control_vertices_preserved": preserved_control_vertices,
        "river_visual_interpolation": (
            "cardinal Catmull-Rom through every exact canonical vertex and endpoint"
        ),
        "river_natural_bank_traces": bank_traces,
        "river_layered_channels": layered_channels,
        "river_inner_flow_threads": inner_flow_threads,
        "river_uniform_solid_bands": 0 if full_material_preview else None,
    }


def _draw_coasts(
    image: Image.Image,
    land_features: Iterable[dict[str, Any]],
    land_mask: Image.Image,
    ocean_mask: Image.Image,
    transform: SheetCanvasTransform,
    seed: int,
) -> dict[str, int]:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    band_mask = Image.new("L", image.size, 0)
    band_draw = ImageDraw.Draw(band_mask)
    ring_count = 0
    curved_bands = 0
    for feature in land_features:
        feature_name = feature_id(feature)
        for rings in polygon_rings(feature.get("geometry", {}), transform):
            for ring_index, ring in enumerate(rings):
                visual_ring = _meander_pixel_path(
                    ring,
                    seed=seed,
                    namespace=f"coast-wave-band-v3:{feature_name}:{ring_index}",
                    amplitude_px=5,
                )
                draw.line(ring, fill=(55, 52, 41, 72), width=1, joint="curve")
                draw.line(
                    visual_ring,
                    fill=(72, 65, 49, 155),
                    width=1,
                    joint="curve",
                )
                band_draw.line(ring, fill=255, width=15, joint="curve")
                band_draw.line(visual_ring, fill=255, width=15, joint="curve")
                ring_count += 1
                curved_bands += 1

    inner_band = ImageChops.multiply(band_mask, land_mask)
    outer_band = ImageChops.multiply(band_mask, ocean_mask)
    texture = Image.new("RGBA", image.size, (0, 0, 0, 0))
    texture_draw = ImageDraw.Draw(texture)
    inner_count = 0
    outer_count = 0
    for _, _, world_x, world_y, digest in iter_anchored_grid(
        transform,
        cell_world=5.5,
        namespace="shore-stipple-wave-v2",
        seed=seed,
        margin_cells=2,
    ):
        point = transform.point_fast((world_x, world_y))
        x, y = point
        if _mask_point(inner_band, point) and _unit(digest, 8) < 0.62:
            texture_draw.point((x, y), fill=(66, 57, 42, 110))
            if _unit(digest, 12) < 0.34:
                angle = math.tau * _unit(digest, 16)
                texture_draw.line(
                    (
                        x,
                        y,
                        round(x + math.cos(angle) * 3),
                        round(y + math.sin(angle) * 3),
                    ),
                    fill=(66, 57, 42, 82),
                    width=1,
                )
            if _unit(digest, 20) < 0.15:
                radius = 2 + int(_unit(digest, 24) * 3)
                texture_draw.polygon(
                    (
                        (x - radius, y),
                        (x - 1, y - radius),
                        (x + radius, y - 1),
                        (x + 1, y + radius),
                        (x - radius, y),
                    ),
                    fill=(74, 110, 123, 105),
                )
            inner_count += 1
        elif _mask_point(outer_band, point) and _unit(digest, 8) < 0.48:
            length = 2 + int(_unit(digest, 12) * 4)
            bend = -1 + int(_unit(digest, 16) * 3)
            texture_draw.line(
                ((x - length, y), (x, y + bend), (x + length, y)),
                fill=(204, 203, 169, 95),
                width=1,
                joint="curve",
            )
            if _unit(digest, 20) < 0.18:
                radius = 2 + int(_unit(digest, 24) * 3)
                texture_draw.polygon(
                    (
                        (x - radius, y - 1),
                        (x, y - radius),
                        (x + radius, y),
                        (x, y + radius),
                        (x - radius, y - 1),
                    ),
                    fill=(186, 165, 107, 110),
                )
            outer_count += 1
    _alpha_composite_masked(image, texture, band_mask)
    texture.close()
    inner_band.close()
    outer_band.close()
    band_mask.close()
    image.alpha_composite(layer)
    layer.close()
    return {
        "coast_centerline_rings": ring_count,
        "coast_curved_wave_bands": curved_bands,
        "coast_centerline_max_px": 1,
        "shore_inner_stipple": inner_count,
        "shore_outer_wavelets": outer_count,
        "coast_centerline_coordinate_offsets": 0,
    }


def _draw_transport(
    image: Image.Image,
    features: Iterable[dict[str, Any]],
    settlement_features: Iterable[dict[str, Any]],
    transform: SheetCanvasTransform,
    sheet_type: str,
    seed: int,
) -> dict[str, int]:
    caps = STROKE_CAPS_PX.get(sheet_type, STROKE_CAPS_PX["region"])
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    control_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    control_draw = ImageDraw.Draw(control_layer)
    urban_mask = Image.new("L", image.size, 0)
    urban_mask_draw = ImageDraw.Draw(urban_mask)
    for settlement in settlement_features:
        bbox = _geometry_bbox(settlement)
        if bbox is None or not _intersects(bbox, transform.bounds):
            continue
        node_type = str(settlement.get("properties", {}).get("node_type", "town"))
        urban_scale = 0.66 if node_type == "capital" else 0.60
        if node_type in {"port", "underwater_city"}:
            urban_scale = 0.64
        polygon = _organic_settlement_polygon(settlement, seed, scale=urban_scale)
        if polygon:
            urban_mask_draw.polygon(
                [transform.point_fast(point) for point in polygon],
                fill=255,
            )
    centerlines = 0
    maximum_road = 0
    maximum_casing = 0
    for feature in features:
        route_type = feature.get("properties", {}).get("route_type", "road")
        for path_index, path in enumerate(
            line_paths(feature.get("geometry", {}), transform)
        ):
            visible_path = _meander_pixel_path(
                path,
                seed=seed,
                namespace=f"transport-visual-curve-v3:{feature_id(feature)}:{path_index}",
                amplitude_px=3 if route_type in {"road", "rail"} else 1,
            )
            if route_type == "road":
                road_width = caps["road"]
                casing_width = caps["road_casing"]
                control_draw.line(
                    path,
                    fill=(101, 74, 48, 72),
                    width=1,
                    joint="curve",
                )
                draw.line(
                    visible_path,
                    fill=(63, 47, 34, 220),
                    width=casing_width,
                    joint="curve",
                )
                draw.line(
                    visible_path,
                    fill=(207, 181, 122, 245),
                    width=road_width,
                    joint="curve",
                )
                if road_width > 1:
                    draw.line(
                        visible_path,
                        fill=(105, 72, 46, 190),
                        width=1,
                        joint="curve",
                    )
                maximum_road = max(maximum_road, road_width)
                maximum_casing = max(maximum_casing, casing_width)
            elif route_type == "rail":
                control_draw.line(
                    path,
                    fill=(80, 68, 52, 68),
                    width=1,
                    joint="curve",
                )
                draw.line(
                    visible_path,
                    fill=(57, 49, 41, 220),
                    width=caps["rail"],
                    joint="curve",
                )
                draw.line(
                    visible_path,
                    fill=(191, 164, 108, 235),
                    width=1,
                    joint="curve",
                )
            elif route_type in {"sea", "submarine", "underwater_tunnel"}:
                _draw_dashed_line(
                    draw,
                    path,
                    fill=(194, 205, 181, 75),
                    width=1,
                    dash=18,
                    gap=10,
                )
            elif route_type == "air":
                _draw_dashed_line(
                    draw,
                    path,
                    fill=(83, 77, 66, 38),
                    width=1,
                    dash=12,
                    gap=11,
                )
            else:
                _draw_dashed_line(
                    draw,
                    path,
                    fill=(80, 57, 47, 175),
                    width=2,
                    dash=8,
                    gap=6,
                )
            centerlines += 1
    outside_urban = ImageOps.invert(urban_mask)
    _alpha_composite_masked(image, layer, outside_urban)
    _alpha_composite_masked(image, control_layer, urban_mask)
    # The full-weight decorative route stops at the urban edge.  A quieter exact
    # canonical thread remains visible inside the footprint and meets the
    # intersection-snapped city gate streets rendered by ``_draw_settlements``.
    outside_urban.close()
    urban_mask.close()
    control_layer.close()
    layer.close()
    return {
        "transport_centerlines": centerlines,
        "road_core_max_px": maximum_road,
        "road_casing_max_px": maximum_casing,
        "transport_centerline_coordinate_offsets": 0,
        "transport_visible_curve_max_px": 3,
        "transport_inside_urban_control_only": 1,
        "transport_inside_urban_integrated_streets": 1,
        "transport_canonical_thread_visible_inside_urban": 1,
    }


def _segment_intersection(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> tuple[float, float] | None:
    first_dx = first_end[0] - first_start[0]
    first_dy = first_end[1] - first_start[1]
    second_dx = second_end[0] - second_start[0]
    second_dy = second_end[1] - second_start[1]
    denominator = first_dx * second_dy - first_dy * second_dx
    if abs(denominator) < 1e-9:
        return None
    offset_x = second_start[0] - first_start[0]
    offset_y = second_start[1] - first_start[1]
    first_ratio = (offset_x * second_dy - offset_y * second_dx) / denominator
    second_ratio = (offset_x * first_dy - offset_y * first_dx) / denominator
    if not (0 <= first_ratio <= 1 and 0 <= second_ratio <= 1):
        return None
    return (
        first_start[0] + first_dx * first_ratio,
        first_start[1] + first_dy * first_ratio,
    )


def _draw_bridges(
    image: Image.Image,
    hydro_features: Iterable[dict[str, Any]],
    transport_features: Iterable[dict[str, Any]],
    transform: SheetCanvasTransform,
) -> int:
    rivers = [
        line
        for feature in hydro_features
        if feature.get("properties", {}).get("water_type") == "river_system"
        for line in _iter_world_lines(feature.get("geometry", {}))
    ]
    routes = [
        line
        for feature in transport_features
        if feature.get("properties", {}).get("route_type") in {"road", "rail"}
        for line in _iter_world_lines(feature.get("geometry", {}))
    ]
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    count = 0
    for route in routes:
        for route_start, route_end in zip(route, route[1:]):
            angle = math.atan2(
                route_end[1] - route_start[1],
                route_end[0] - route_start[0],
            )
            for river in rivers:
                for river_start, river_end in zip(river, river[1:]):
                    intersection = _segment_intersection(
                        route_start,
                        route_end,
                        river_start,
                        river_end,
                    )
                    if intersection is None:
                        continue
                    if not (
                        transform.bounds[0] <= intersection[0] <= transform.bounds[2]
                        and transform.bounds[1]
                        <= intersection[1]
                        <= transform.bounds[3]
                    ):
                        continue
                    x, y = transform.point_fast(intersection)
                    half_length = 7
                    half_width = 3
                    dx = math.cos(angle) * half_length
                    dy = math.sin(angle) * half_length
                    nx = -math.sin(angle) * half_width
                    ny = math.cos(angle) * half_width
                    bridge = [
                        (round(x - dx - nx), round(y - dy - ny)),
                        (round(x + dx - nx), round(y + dy - ny)),
                        (round(x + dx + nx), round(y + dy + ny)),
                        (round(x - dx + nx), round(y - dy + ny)),
                    ]
                    draw.polygon(bridge, fill=(190, 159, 101, 238))
                    draw.line((*bridge, bridge[0]), fill=(60, 47, 35, 235), width=1)
                    draw.line(
                        (round(x - dx), round(y - dy), round(x + dx), round(y + dy)),
                        fill=(103, 72, 45, 220),
                        width=1,
                    )
                    count += 1
    image.alpha_composite(layer)
    layer.close()
    return count


def _geometry_bbox(feature: dict[str, Any]) -> tuple[float, float, float, float] | None:
    points: list[tuple[float, float]] = []

    def collect(value: Any) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            points.append((float(value[0]), float(value[1])))
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(feature.get("geometry", {}).get("coordinates"))
    if not points:
        return None
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _intersects(first: Sequence[float], second: Sequence[float]) -> bool:
    return not (
        first[2] < second[0]
        or first[0] > second[2]
        or first[3] < second[1]
        or first[1] > second[3]
    )


def load_render_context(
    *,
    sheet_id: str = DEFAULT_SHEET_ID,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    contract_path: Path = DEFAULT_CONTRACT,
    map_sheets_path: Path = DEFAULT_MAP_SHEETS,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    validation = validate_resolution_contract(
        contract_path=contract_path,
        map_sheets_path=map_sheets_path,
        check_catalog=True,
    )
    if not validation["valid"]:
        raise ReviewedMasterError(
            "resolution contract validation failed: " + "; ".join(validation["errors"])
        )
    try:
        sheet = next(
            record for record in validation["sheets"] if record["sheet_id"] == sheet_id
        )
    except StopIteration as exc:
        raise ReviewedMasterError(f"bounded sheet does not exist: {sheet_id}") from exc
    contract = _load_json(contract_path)
    catalog = _load_json(map_sheets_path)
    catalog_sheet = next(
        (
            value
            for value in catalog.get("sheets", [])
            if isinstance(value, dict) and value.get("id") == sheet_id
        ),
        None,
    )
    if not isinstance(catalog_sheet, dict):
        raise ReviewedMasterError(f"catalog sheet does not exist: {sheet_id}")
    sheet = {**sheet, "source_feature_id": catalog_sheet.get("source_feature_id")}
    return load_sources(source_dir), contract, sheet, validation


def generation_sheet_ids(
    *,
    contract_path: Path = DEFAULT_CONTRACT,
    map_sheets_path: Path = DEFAULT_MAP_SHEETS,
) -> tuple[str, ...]:
    validation = validate_resolution_contract(
        contract_path=contract_path,
        map_sheets_path=map_sheets_path,
        check_catalog=True,
    )
    if not validation["valid"]:
        raise ReviewedMasterError(
            "resolution contract validation failed: " + "; ".join(validation["errors"])
        )
    return tuple(
        sheet["sheet_id"]
        for sheet in validation["sheets"]
        if sheet.get("sheet_type") in GENERATION_SHEET_TYPES
    )


def _plan_land_features(
    sources: dict[str, dict[str, Any]],
    seed: int = DEFAULT_SEED,
) -> list[dict[str, Any]]:
    del seed
    features = list(sources["landmasses"]["features"])
    features.extend(
        feature
        for feature in sources["terrain"]["features"]
        if feature.get("properties", {}).get("terrain_type") == "floating_island_chain"
    )
    return features


def _build_land_masks(
    sources: dict[str, dict[str, Any]],
    transform: SheetCanvasTransform,
    seed: int = DEFAULT_SEED,
) -> tuple[Image.Image, Image.Image]:
    """Rasterize the canonical classification used by the locked controls.

    The ordering is semantic, not decorative: landmasses establish land, all
    canonical hydrography (including nominal-width river lines) cuts water,
    underwater regions remain water, and only source-backed floating-island
    terrain restores land.  Settlement decoration must never invent land.
    """

    del seed
    size = (transform.width, transform.height)
    classification = Image.new("L", size, 0)
    draw = ImageDraw.Draw(classification)

    def draw_polygon_class(feature: dict[str, Any], value: int) -> None:
        for rings in polygon_rings(feature.get("geometry", {}), transform):
            draw.polygon(rings[0], fill=value)
            if len(rings) > 1:
                raise ReviewedMasterError(
                    "canonical classification polygon holes require an explicit "
                    f"underlying class: {feature_id(feature)}"
                )

    for feature in sources["landmasses"]["features"]:
        draw_polygon_class(feature, 1)
    for feature in sources["hydrography"]["features"]:
        geometry_type = feature.get("geometry", {}).get("type")
        if geometry_type in {"Polygon", "MultiPolygon"}:
            draw_polygon_class(feature, 2)
        else:
            width = transform.nominal_width_px(
                feature.get("properties", {}).get("nominal_width", 1)
            )
            for path in line_paths(feature.get("geometry", {}), transform):
                draw.line(path, fill=2, width=width, joint="curve")
    for feature in sources["regions"]["features"]:
        if feature.get("properties", {}).get("region_type") == "underwater_region":
            draw_polygon_class(feature, 2)
    for feature in sources["terrain"]["features"]:
        if (
            feature.get("properties", {}).get("terrain_type")
            == "floating_island_chain"
        ):
            draw_polygon_class(feature, 1)

    land_mask = classification.point(
        lambda value: 255 if value == 1 else 0,
        mode="L",
    )
    ocean_mask = ImageOps.invert(land_mask)
    classification.close()
    return land_mask, ocean_mask


def _build_transport_mask(
    sources: dict[str, dict[str, Any]],
    transform: SheetCanvasTransform,
) -> Image.Image:
    mask = Image.new("L", (transform.width, transform.height), 0)
    draw = ImageDraw.Draw(mask)
    width = max(2, 2 ** max(1, int(transform.sheet["native_zoom"]) - 4))
    for feature in sources["transport"]["features"]:
        for path in line_paths(feature.get("geometry", {}), transform):
            draw.line(path, fill=255, width=width, joint="curve")
    return mask


def _highland_detail_target_feature(
    sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    target_id = highland_detail_exemplar.TARGET_FEATURE_ID
    matches = [
        feature
        for feature in sources["terrain"]["features"]
        if feature_id(feature) == target_id
    ]
    if len(matches) != 1:
        raise ReviewedMasterError(
            "highland detail exemplar requires exactly one canonical target "
            f"feature {target_id!r}; found={len(matches)}"
        )
    target = matches[0]
    properties = target.get("properties", {})
    geometry = target.get("geometry", {})
    if (
        target.get("id") != target_id
        or properties.get("id") != target_id
        or properties.get("terrain_type") != "mountain_axis"
        or properties.get("region_id") != "soaring_mountains_region"
        or geometry.get("type") not in {"LineString", "MultiLineString"}
        or not list(_iter_world_lines(geometry))
    ):
        raise ReviewedMasterError(
            "highland detail exemplar canonical target identity or geometry changed"
        )
    return target


def _highland_detail_protected_mask(
    sources: dict[str, dict[str, Any]],
    target_feature: dict[str, Any],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
) -> Image.Image:
    """Build a conservative exclusion for all non-target canonical topology."""

    size = (transform.width, transform.height)
    protected = ImageOps.invert(land_mask)

    def merge(component: Image.Image, *, dilate_px: int = 0) -> None:
        guarded = component
        if dilate_px:
            guarded = component.filter(ImageFilter.MaxFilter(dilate_px))
        try:
            protected.paste(255, (0, 0), guarded)
        finally:
            if guarded is not component:
                guarded.close()

    # The broad canonical axis corridor is the permission mask, while its exact
    # centerline remains protected topology.  The exemplar may add material
    # around the ridge, but cannot alter the registered ridge coordinate.
    target_centerline = Image.new("L", size, 0)
    target_centerline_draw = ImageDraw.Draw(target_centerline)
    try:
        for path in line_paths(target_feature.get("geometry", {}), transform):
            target_centerline_draw.line(
                path,
                fill=255,
                width=1,
                joint="curve",
            )
        merge(target_centerline, dilate_px=5)
    finally:
        target_centerline.close()

    target_id = highland_detail_exemplar.TARGET_FEATURE_ID
    terrain_guard = Image.new("L", size, 0)
    try:
        for feature in sources["terrain"]["features"]:
            if feature is target_feature or feature_id(feature) == target_id:
                continue
            component = _terrain_feature_mask(size, feature, land_mask, transform)
            try:
                terrain_guard.paste(255, (0, 0), component)
            finally:
                component.close()
        merge(terrain_guard, dilate_px=7)
    finally:
        terrain_guard.close()

    settlement_guard = Image.new("L", size, 0)
    try:
        for feature in sources["settlements"]["features"]:
            component = feature_mask(size, feature, transform)
            try:
                settlement_guard.paste(255, (0, 0), component)
            finally:
                component.close()
        merge(settlement_guard, dilate_px=7)
    finally:
        settlement_guard.close()

    hydro_lines = Image.new("L", size, 0)
    hydro_draw = ImageDraw.Draw(hydro_lines)
    try:
        for feature in sources["hydrography"]["features"]:
            geometry_type = feature.get("geometry", {}).get("type")
            if geometry_type in {"Polygon", "MultiPolygon"}:
                component = feature_mask(size, feature, transform)
                try:
                    hydro_lines.paste(255, (0, 0), component)
                finally:
                    component.close()
                continue
            nominal_width = float(
                feature.get("properties", {}).get("nominal_width", 8)
            )
            width_px = transform.nominal_width_px(nominal_width)
            for path in line_paths(feature.get("geometry", {}), transform):
                hydro_draw.line(
                    path,
                    fill=255,
                    width=width_px,
                    joint="curve",
                )
        merge(hydro_lines, dilate_px=7)
    finally:
        hydro_lines.close()

    transport = _build_transport_mask(sources, transform)
    try:
        merge(transport, dilate_px=7)
    finally:
        transport.close()
    return protected


def _apply_highland_detail_exemplar(
    image: Image.Image,
    sources: dict[str, dict[str, Any]],
    land_mask: Image.Image,
    transform: SheetCanvasTransform,
    sheet: dict[str, Any],
    seed: int,
    *,
    enabled: bool,
) -> dict[str, Any] | None:
    """Apply the optional bridge only to its one exact target sheet."""

    sheet_id = str(sheet.get("sheet_id", ""))
    if not enabled or sheet_id != highland_detail_exemplar.TARGET_SHEET_ID:
        return None

    target = _highland_detail_target_feature(sources)
    canonical_mask = _terrain_feature_mask(
        image.size,
        target,
        land_mask,
        transform,
    )
    protected_mask = _highland_detail_protected_mask(
        sources,
        target,
        land_mask,
        transform,
    )
    try:
        left, top, _, _ = transform.pixel_bounds
        try:
            record = highland_detail_exemplar.apply_production_exemplar(
                image,
                canonical_mask,
                protected_mask,
                sheet_id=sheet_id,
                feature_id=feature_id(target),
                global_pixel_origin=(left, top),
                seed=seed,
                enabled=True,
            )
            if not isinstance(record, dict) or not isinstance(
                record.get("application"), dict
            ):
                raise ReviewedMasterError(
                    "highland detail exemplar returned an invalid application record"
                )
            record["application"].update(
                {
                    "canonical_geometry_modified": False,
                    "canonical_target_centerline_guarded": True,
                    "non_target_terrain_guarded": True,
                    "settlements_guarded": True,
                    "hydrography_guarded": True,
                    "transport_guarded": True,
                }
            )
            return record
        except highland_detail_exemplar.HighlandDetailExemplarError as exc:
            raise ReviewedMasterError(str(exc)) from exc
    finally:
        protected_mask.close()
        canonical_mask.close()


def render_observed_masks(
    sources: dict[str, dict[str, Any]],
    contract: dict[str, Any],
    sheet: dict[str, Any],
    *,
    seed: int = DEFAULT_SEED,
) -> dict[str, Image.Image]:
    transform = SheetCanvasTransform(contract, sheet)
    land_mask, ocean_mask = _build_land_masks(sources, transform, seed)
    ocean_mask.close()
    return {
        "land_sea": land_mask,
        "transport": _build_transport_mask(sources, transform),
    }


def render_reviewed_master(
    sources: dict[str, dict[str, Any]],
    contract: dict[str, Any],
    sheet: dict[str, Any],
    *,
    seed: int = DEFAULT_SEED,
    material_atlas_path: Path = DEFAULT_MATERIAL_ATLAS,
    global_neutral_material_path: Path = DEFAULT_GLOBAL_NEUTRAL_MATERIAL,
    style_profile: dict[str, Any] | None = None,
    material_transfer_mode: str = RESIDUAL_MATERIAL_MODE,
    use_highland_detail_exemplar: bool = False,
) -> tuple[Image.Image, dict[str, Any]]:
    transform = SheetCanvasTransform(contract, sheet)
    size = (transform.width, transform.height)
    image = Image.new("RGBA", size, PALETTE["ocean"])

    observed_terrain = {
        str(feature.get("properties", {}).get("terrain_type", ""))
        for feature in sources["terrain"]["features"]
    }
    unsupported = observed_terrain - SUPPORTED_TERRAIN_TYPES
    if unsupported:
        raise ReviewedMasterError(
            f"unsupported canonical terrain types: {sorted(unsupported)!r}"
        )
    land_mask, ocean_mask = _build_land_masks(sources, transform, seed)

    full_material_preview = material_transfer_mode == FULL_SPATIAL_MATERIAL_MODE
    global_neutral_preview = (
        material_transfer_mode == GLOBAL_NEUTRAL_BANDPASS_MODE
    )
    rich_land_material_preview = full_material_preview or global_neutral_preview
    land_tone = _style_rgb(style_profile, "land_tone_rgb", (193, 173, 118))
    image.paste(land_tone, (0, 0, *size), land_mask)
    if not global_neutral_preview:
        _draw_region_washes(
            image,
            sources["regions"]["features"],
            land_mask,
            transform,
        )
    stats: dict[str, Any] = {counter: 0 for counter in FORBIDDEN_COUNTERS}
    stats.update(_draw_global_paper_texture(image, transform, seed))
    if global_neutral_preview:
        stats.update(
            _draw_global_neutral_land_material(
                image,
                sources,
                land_mask,
                transform,
                seed,
                global_neutral_material_path,
            )
        )
    else:
        stats.update(
            _draw_atlas_materials(
                image,
                sources,
                land_mask,
                transform,
                seed,
                material_atlas_path,
                material_transfer_mode=material_transfer_mode,
                style_profile=style_profile,
            )
        )
    stats["terrain_types_supported"] = sorted(SUPPORTED_TERRAIN_TYPES)
    stats["terrain_types_observed"] = sorted(observed_terrain)
    stats["agricultural_rows"] = _draw_agricultural_regions(
        image,
        sources["regions"]["features"],
        land_mask,
        transform,
        seed,
    )
    stats.update(
        _draw_water_texture(
            image,
            ocean_mask,
            transform,
            seed,
            full_material_preview=full_material_preview,
        )
    )
    stats["generic_land_marks"] = _draw_land_marks(
        image,
        land_mask,
        transform,
        seed,
        style_profile,
        full_material_preview=rich_land_material_preview,
    )
    stats.update(
        _draw_royal_capital_landscape(
            image,
            sources["settlements"]["features"],
            sources["terrain"]["features"],
            sources["hydrography"]["features"],
            sources["transport"]["features"],
            land_mask,
            transform,
            seed,
            style_profile,
            full_material_preview=rich_land_material_preview,
        )
    )
    stats.update(
        _draw_riparian_landscape(
            image,
            sources["hydrography"]["features"],
            land_mask,
            transform,
            seed,
            full_material_preview=full_material_preview,
        )
    )
    stats.update(
        _draw_polygon_terrains(
            image,
            sources["terrain"]["features"],
            land_mask,
            transform,
            seed,
        )
    )
    stats.update(
        _draw_forests(
            image,
            sources["terrain"]["features"],
            land_mask,
            transform,
            seed,
            style_profile,
            full_material_preview=rich_land_material_preview,
        )
    )
    stats.update(
        _draw_mountain_axes(
            image,
            sources["terrain"]["features"],
            land_mask,
            transform,
            seed,
        )
    )
    highland_detail_record = _apply_highland_detail_exemplar(
        image,
        sources,
        land_mask,
        transform,
        sheet,
        seed,
        enabled=use_highland_detail_exemplar,
    )
    if highland_detail_record is not None:
        stats["highland_detail_exemplar"] = highland_detail_record
    stats.update(
        _draw_gorge_axes(
            image,
            sources["terrain"]["features"],
            land_mask,
            transform,
            seed,
        )
    )
    stats.update(
        _draw_settlements(
            image,
            sources["settlements"]["features"],
            land_mask,
            transform,
            seed,
            sources["transport"]["features"],
        )
    )
    stats.update(
        _draw_rivers(
            image,
            sources["hydrography"]["features"],
            transform,
            str(sheet["sheet_type"]),
            seed,
            full_material_preview=full_material_preview,
        )
    )
    stats.update(
        _draw_coasts(
            image,
            _plan_land_features(sources, seed),
            land_mask,
            ocean_mask,
            transform,
            seed,
        )
    )
    stats.update(
        _draw_transport(
            image,
            sources["transport"]["features"],
            sources["settlements"]["features"],
            transform,
            str(sheet["sheet_type"]),
            seed,
        )
    )
    stats["bridge_footprints"] = _draw_bridges(
        image,
        sources["hydrography"]["features"],
        sources["transport"]["features"],
        transform,
    )
    stats["forbidden_total"] = sum(
        int(stats[counter]) for counter in FORBIDDEN_COUNTERS
    )
    stats["pattern_coordinate_reference_system"] = "EA-WORLD-1"
    stats["pattern_seed"] = seed
    stats["material_transfer_mode"] = material_transfer_mode
    stats["full_spatial_material_preview"] = full_material_preview
    stats["global_neutral_bandpass_preview"] = global_neutral_preview
    stats["sheet_id_in_pattern_hash"] = False
    stats["golden_style_statistics_applied"] = style_profile is not None
    stats["golden_style_copied_pixels"] = 0
    stats["golden_style_used_as_geometry"] = False
    stats["golden_style_profile_sha256"] = (
        style_profile.get("profile_sha256") if style_profile else None
    )
    stats["native_zoom_lod"] = {
        "native_zoom": int(sheet["native_zoom"]),
        "level": (
            "building"
            if int(sheet["native_zoom"]) >= 8
            else "parcel"
            if int(sheet["native_zoom"]) >= 7
            else "regional-structure"
        ),
        "detail_increases_with_zoom": True,
    }
    land_mask.close()
    ocean_mask.close()
    return image.convert("RGB"), stats


def render_contact_sheet(
    master: Image.Image,
    transform: SheetCanvasTransform,
    *,
    center_world: tuple[float, float] | None = None,
) -> tuple[Image.Image, list[dict[str, Any]]]:
    panel_size = (512, 288)
    if center_world is None:
        min_x, min_y, max_x, max_y = transform.bounds
        center_world = ((min_x + max_x) / 2, (min_y + max_y) / 2)
    center_x, center_y = transform.point(center_world)
    panels: list[Image.Image] = []
    records: list[dict[str, Any]] = []
    for label, scale in (
        ("25-percent", 0.25),
        ("50-percent", 0.5),
        ("100-percent", 1.0),
    ):
        source_width = round(panel_size[0] / scale)
        source_height = round(panel_size[1] / scale)
        left = max(0, min(master.width - source_width, center_x - source_width // 2))
        top = max(0, min(master.height - source_height, center_y - source_height // 2))
        right = min(master.width, left + source_width)
        bottom = min(master.height, top + source_height)
        crop = master.crop((left, top, right, bottom))
        panel = crop.resize(panel_size, Image.Resampling.LANCZOS)
        crop.close()
        panels.append(panel)
        records.append(
            {
                "label": label,
                "effective_scale": scale,
                "source_box_px": [left, top, right, bottom],
                "panel_size_px": list(panel_size),
            }
        )
    gutter = 16
    sheet = Image.new(
        "RGB",
        (panel_size[0] * len(panels) + gutter * (len(panels) - 1), panel_size[1]),
        PALETTE["parchment_light"],
    )
    for index, panel in enumerate(panels):
        sheet.paste(panel, (index * (panel_size[0] + gutter), 0))
        panel.close()
    return sheet, records


def _image_record(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        image.load()
        return {
            "path": _repo_path(path),
            "sha256": sha256_file(path),
            "format": image.format,
            "mode": image.mode,
            "width": image.width,
            "height": image.height,
            "bytes": path.stat().st_size,
        }


def _source_records(
    sources: dict[str, dict[str, Any]],
    source_dir: Path,
    bounds: Sequence[float],
) -> list[dict[str, Any]]:
    records = []
    for role, filename in SOURCE_FILES.items():
        features = sources[role]["features"]
        intersecting = []
        for feature in features:
            bbox = _geometry_bbox(feature)
            if bbox is not None and _intersects(bbox, bounds):
                intersecting.append(feature_id(feature))
        path = source_dir / filename
        records.append(
            {
                "role": role,
                "path": _repo_path(path),
                "sha256": sha256_file(path),
                "feature_count": len(features),
                "intersecting_feature_ids": intersecting,
            }
        )
    return records


def _validate_output_dir(output_dir: Path) -> Path:
    resolved = output_dir.resolve()
    allowed = DEFAULT_OUTPUT_ROOT.resolve()
    if resolved != allowed and allowed not in resolved.parents:
        raise ReviewedMasterError(
            f"reviewed v2 output must stay below {_repo_path(DEFAULT_OUTPUT_ROOT)}"
        )
    return resolved


def _atomic_write_bytes(path: Path, payload: bytes, *, replace: bool) -> None:
    if path.exists() and not replace:
        raise ReviewedMasterError(f"refusing to overwrite existing prototype: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, **PNG_OPTIONS)
    return buffer.getvalue()


def _histogram_quantile(histogram: Sequence[int], quantile: float) -> int:
    target = sum(histogram) * quantile
    cumulative = 0
    for value, count in enumerate(histogram):
        cumulative += count
        if cumulative >= target:
            return value
    return len(histogram) - 1


def _extract_golden_style_profile(golden_style_path: Path) -> dict[str, Any]:
    """Extract non-spatial style statistics from a hash-locked raster.

    The returned profile contains no pixels, crops, coordinates, masks, local
    descriptors, or semantic geometry.  It can tune only global colour,
    contrast, edge/high-pass energy, density, and orientation-distribution
    parameters in the deterministic EA renderer.
    """

    try:
        with Image.open(golden_style_path) as opened:
            opened.load()
            if opened.width < 64 or opened.height < 64:
                raise ReviewedMasterError("golden style raster is too small for statistics")
            source = opened.convert("RGB")
    except (OSError, ValueError) as exc:
        raise ReviewedMasterError(
            f"could not decode golden style raster {golden_style_path}: {exc}"
        ) from exc

    source.thumbnail((384, 256), Image.Resampling.LANCZOS)
    gray = source.convert("L")
    try:
        histogram = source.histogram()
        colour_quantiles: dict[str, list[int]] = {}
        for channel, name in enumerate(("red", "green", "blue")):
            channel_histogram = histogram[channel * 256 : (channel + 1) * 256]
            colour_quantiles[name] = [
                _histogram_quantile(channel_histogram, quantile)
                for quantile in (0.10, 0.25, 0.50, 0.75, 0.90)
            ]
        colour_mean = [round(value, 6) for value in ImageStat.Stat(source).mean]

        luma_stat = ImageStat.Stat(gray)
        luma_histogram = gray.histogram()
        luma_quantiles = [
            _histogram_quantile(luma_histogram, quantile)
            for quantile in (0.10, 0.25, 0.50, 0.75, 0.90)
        ]
        edge_image = gray.filter(ImageFilter.FIND_EDGES)
        try:
            edge_core = edge_image.crop((1, 1, edge_image.width - 1, edge_image.height - 1))
            try:
                edge_stat = ImageStat.Stat(edge_core)
                edge_histogram = edge_core.histogram()
                edge_density = (
                    sum(edge_histogram[18:]) / max(1, edge_core.width * edge_core.height)
                )
            finally:
                edge_core.close()
        finally:
            edge_image.close()

        high_pass_bands: list[dict[str, float | int]] = []
        for radius in (1, 2, 4):
            blurred = gray.filter(ImageFilter.GaussianBlur(radius=radius))
            residual = ImageChops.difference(gray, blurred)
            try:
                stat = ImageStat.Stat(residual)
                high_pass_bands.append(
                    {
                        "gaussian_radius_px": radius,
                        "mean_absolute_luma": round(stat.mean[0], 6),
                        "rms_luma": round(stat.rms[0], 6),
                    }
                )
            finally:
                residual.close()
                blurred.close()

        orientation = gray.copy()
        orientation.thumbnail((192, 128), Image.Resampling.LANCZOS)
        bins = [0.0] * 12
        pixels = orientation.load()
        for y in range(1, orientation.height - 1):
            for x in range(1, orientation.width - 1):
                gradient_x = float(pixels[x + 1, y]) - float(pixels[x - 1, y])
                gradient_y = float(pixels[x, y + 1]) - float(pixels[x, y - 1])
                magnitude = math.hypot(gradient_x, gradient_y)
                if magnitude < 2.0:
                    continue
                angle = math.atan2(gradient_y, gradient_x) % math.pi
                bin_index = min(len(bins) - 1, int(angle / math.pi * len(bins)))
                bins[bin_index] += magnitude
        orientation.close()
        orientation_total = sum(bins)
        distribution = [
            value / orientation_total if orientation_total else 0.0 for value in bins
        ]
        entropy = -sum(
            value * math.log2(value) for value in distribution if value > 0.0
        )
        normalized_entropy = entropy / math.log2(len(bins)) if orientation_total else 0.0

        low_rgb = [colour_quantiles[name][0] for name in ("red", "green", "blue")]
        upper_rgb = [colour_quantiles[name][3] for name in ("red", "green", "blue")]
        parchment_base = (193, 173, 118)
        land_tone = [
            round(base * 0.82 + target * 0.18)
            for base, target in zip(parchment_base, upper_rgb)
        ]
        ink_base = (68, 58, 45)
        ink_tone = [
            round(base * 0.62 + target * 0.38)
            for base, target in zip(ink_base, low_rgb)
        ]
        high_pass_two = next(
            item for item in high_pass_bands if item["gaussian_radius_px"] == 2
        )
        contrast = float(luma_stat.stddev[0])
        edge_mean = float(edge_stat.mean[0])
        detail_density_scale = _clamp(
            0.86 + float(high_pass_two["mean_absolute_luma"]) / 20.0,
            0.9,
            1.45,
        )
        ink_alpha_scale = _clamp(0.86 + contrast / 48.0, 0.9, 1.30)
        forest_density_scale = _clamp(0.88 + edge_mean / 75.0, 0.9, 1.45)
        orientation_randomness = _clamp(0.55 + normalized_entropy * 0.45, 0.55, 1.0)
        profile: dict[str, Any] = {
            "schema_version": "1.0.0",
            "profile_type": "non-spatial-cartographic-style-statistics",
            "sampling": {
                "method": "whole-raster LANCZOS proxy",
                "width": source.width,
                "height": source.height,
                "sampled_pixel_count": source.width * source.height,
            },
            "colour_statistics": {
                "mean_rgb": colour_mean,
                "per_channel_quantiles_q10_q25_q50_q75_q90": colour_quantiles,
            },
            "luminance_statistics": {
                "mean": round(luma_stat.mean[0], 6),
                "standard_deviation": round(contrast, 6),
                "entropy_bits": round(gray.entropy(), 6),
                "quantiles_q10_q25_q50_q75_q90": luma_quantiles,
            },
            "edge_statistics": {
                "operator": "Pillow FIND_EDGES, one-pixel border excluded",
                "mean_luma": round(edge_mean, 6),
                "rms_luma": round(edge_stat.rms[0], 6),
                "density_above_18": round(edge_density, 6),
            },
            "high_pass_statistics": high_pass_bands,
            "orientation_statistics": {
                "operator": "central-difference unsigned gradient",
                "bin_count": len(bins),
                "magnitude_weighted_distribution": [
                    round(value, 8) for value in distribution
                ],
                "normalized_entropy": round(normalized_entropy, 8),
            },
            "derived_render_parameters": {
                "land_tone_rgb": land_tone,
                "ink_tone_rgb": ink_tone,
                "forest_ink_rgb": [48, 61, 39],
                "detail_density_scale": round(detail_density_scale, 6),
                "forest_detail_density_scale": round(forest_density_scale, 6),
                "ink_alpha_scale": round(ink_alpha_scale, 6),
                "orientation_randomness": round(orientation_randomness, 6),
            },
            "transfer_contract": {
                "used_as_geometry": False,
                "copied_pixels": 0,
                "copied_masks": 0,
                "copied_coordinates": 0,
                "local_descriptors_retained": False,
                "whole_image_histogram_matching": False,
                "allowed_families": [
                    "colour",
                    "luminance-contrast",
                    "edge-energy",
                    "high-pass-energy",
                    "orientation-distribution",
                ],
            },
        }
        profile["profile_sha256"] = hashlib.sha256(
            json.dumps(
                profile,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return profile
    finally:
        gray.close()
        source.close()


def _golden_style_lock(
    golden_style_path: Path | None,
    golden_style_sha256: str | None,
    *,
    preview_only: bool = False,
) -> dict[str, Any]:
    if golden_style_path is None and golden_style_sha256 is None:
        if preview_only:
            raise ReviewedMasterError(
                "golden style preview-only mode requires a path and SHA-256"
            )
        return {
            "status": "pending-h7",
            "path": None,
            "sha256": None,
            "used_as_geometry": False,
            "derived_style_statistics": False,
            "promotion_eligible": False,
        }
    if golden_style_path is None or golden_style_sha256 is None:
        raise ReviewedMasterError(
            "golden style requires both a path and an expected SHA-256"
        )
    expected = golden_style_sha256.lower()
    if len(expected) != 64 or any(
        character not in "0123456789abcdef" for character in expected
    ):
        raise ReviewedMasterError(
            "golden style SHA-256 must be 64 lowercase hex digits"
        )
    actual = sha256_file(golden_style_path)
    if actual != expected:
        raise ReviewedMasterError(
            f"golden style SHA-256 mismatch: expected={expected}, actual={actual}"
        )
    style_profile = _extract_golden_style_profile(golden_style_path)
    return {
        "status": "locked-preview-only" if preview_only else "locked",
        "path": _repo_path(golden_style_path),
        "sha256": actual,
        "used_as_geometry": False,
        "derived_style_statistics": True,
        "copied_pixels": 0,
        "promotion_eligible": not preview_only,
        "style_profile": style_profile,
    }


def _sheet_output_paths(
    output_dir: Path,
    sheet_id: str,
    *,
    emit_masks: bool,
) -> dict[str, Path]:
    paths = {
        "master": output_dir / f"{sheet_id}.png",
        "contact_sheet": output_dir / f"{sheet_id}.contact-sheet.png",
        "report": output_dir / f"{sheet_id}.report.json",
    }
    if emit_masks:
        paths["observed_land_sea_mask"] = (
            output_dir / f"{sheet_id}.observed-land-sea-mask.png"
        )
        paths["observed_transport_mask"] = (
            output_dir / f"{sheet_id}.observed-transport-mask.png"
        )
    return paths


def _control_sheet_record(
    sheet_id: str,
    control_index_path: Path = DEFAULT_CANONICAL_CONTROL_INDEX,
) -> tuple[dict[str, Any], dict[str, Any]]:
    index = _load_json(control_index_path)
    sheets = index.get("sheets")
    if not isinstance(sheets, list):
        raise ReviewedMasterError("canonical control index sheets must be an array")
    matches = [
        value
        for value in sheets
        if isinstance(value, dict) and value.get("sheet_id") == sheet_id
    ]
    if len(matches) != 1:
        raise ReviewedMasterError(
            f"canonical control index must contain exactly one {sheet_id!r} record"
        )
    return (
        {
            "path": _repo_path(control_index_path),
            "sha256": sha256_file(control_index_path),
        },
        matches[0],
    )


def _binary_match_ratio(first: Image.Image, second: Image.Image) -> float:
    if first.size != second.size:
        raise ReviewedMasterError("binary masks have different dimensions")
    difference = ImageChops.difference(first, second)
    try:
        mismatched = sum(difference.histogram()[1:])
    finally:
        difference.close()
    return round(1.0 - mismatched / (first.width * first.height), 8)


def write_generation_mask_batch(
    *,
    output_dir: Path = DEFAULT_OUTPUT_ROOT,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    contract_path: Path = DEFAULT_CONTRACT,
    map_sheets_path: Path = DEFAULT_MAP_SHEETS,
    control_index_path: Path = DEFAULT_CANONICAL_CONTROL_INDEX,
    seed: int = DEFAULT_SEED,
    replace: bool = False,
) -> dict[str, Any]:
    """Render and independently compare all 17 canonical QA mask pairs only."""

    output_dir = _validate_output_dir(output_dir)
    validation = validate_resolution_contract(
        contract_path=contract_path,
        map_sheets_path=map_sheets_path,
        check_catalog=True,
    )
    if not validation["valid"]:
        raise ReviewedMasterError(
            "resolution contract validation failed: "
            + "; ".join(validation["errors"])
        )
    contract = _load_json(contract_path)
    sources = load_sources(source_dir)
    sheet_records = [
        sheet
        for sheet in validation["sheets"]
        if sheet.get("sheet_type") in GENERATION_SHEET_TYPES
    ]
    if len(sheet_records) != 17:
        raise ReviewedMasterError(
            f"mask-only batch requires exactly 17 generation sheets, found {len(sheet_records)}"
        )
    control_index = _load_json(control_index_path)
    control_sheets = {
        item.get("sheet_id"): item
        for item in control_index.get("sheets", [])
        if isinstance(item, dict) and isinstance(item.get("sheet_id"), str)
    }
    report_path = output_dir / "phase5-reviewed-v2.mask-only-report.json"
    paths = [report_path]
    for sheet in sheet_records:
        paths.extend(
            (
                output_dir / f"{sheet['sheet_id']}.observed-land-sea-mask.png",
                output_dir / f"{sheet['sheet_id']}.observed-transport-mask.png",
            )
        )
    _preflight_outputs(paths, replace=replace)

    results: list[dict[str, Any]] = []
    for sheet in sheet_records:
        sheet_id = sheet["sheet_id"]
        control = control_sheets.get(sheet_id)
        if not isinstance(control, dict):
            raise ReviewedMasterError(
                f"canonical control index lacks generation sheet {sheet_id!r}"
            )
        qa = control.get("qa_controls")
        if not isinstance(qa, dict):
            raise ReviewedMasterError(f"{sheet_id} canonical QA controls are missing")
        masks = render_observed_masks(sources, contract, sheet, seed=seed)
        try:
            land_path = output_dir / f"{sheet_id}.observed-land-sea-mask.png"
            transport_path = output_dir / f"{sheet_id}.observed-transport-mask.png"
            _atomic_write_bytes(
                land_path,
                _png_bytes(masks["land_sea"]),
                replace=replace,
            )
            _atomic_write_bytes(
                transport_path,
                _png_bytes(masks["transport"]),
                replace=replace,
            )
            control_images: dict[str, Image.Image] = {}
            try:
                for role, spec_name in (
                    ("land_sea", "land_sea_control"),
                    ("transport", "transport_control"),
                ):
                    spec = qa.get(spec_name)
                    if not isinstance(spec, dict):
                        raise ReviewedMasterError(
                            f"{sheet_id} lacks {spec_name} artifact metadata"
                        )
                    path = REPO_ROOT.joinpath(*Path(str(spec["path"])).parts)
                    if sha256_file(path) != spec.get("sha256"):
                        raise ReviewedMasterError(
                            f"{sheet_id} {spec_name} SHA-256 is stale"
                        )
                    with Image.open(path) as opened:
                        control_images[role] = opened.convert("L")
                land_ratio = _binary_match_ratio(
                    control_images["land_sea"], masks["land_sea"]
                )
                transport_ratio = _binary_match_ratio(
                    control_images["transport"], masks["transport"]
                )
            finally:
                for image in control_images.values():
                    image.close()
            results.append(
                {
                    "sheet_id": sheet_id,
                    "land_sea_match_ratio": land_ratio,
                    "transport_exact_match_ratio": transport_ratio,
                    "land_sea_passed": land_ratio >= 0.98,
                    "transport_passed": transport_ratio >= 0.95,
                    "observed_land_sea_mask": _image_record(land_path),
                    "observed_transport_mask": _image_record(transport_path),
                }
            )
        finally:
            for mask in masks.values():
                mask.close()
    report = {
        "schema_version": "1.0.0",
        "id": "phase5-reviewed-v2-mask-only-batch",
        "status": (
            "passed"
            if all(
                item["land_sea_passed"] and item["transport_passed"]
                for item in results
            )
            else "failed"
        ),
        "generated_by": {
            "id": GENERATOR_ID,
            "path": _repo_path(Path(__file__)),
            "sha256": sha256_file(Path(__file__)),
        },
        "coordinate_reference_system": "EA-WORLD-1",
        "seed": seed,
        "canonical_control_index": {
            "path": _repo_path(control_index_path),
            "sha256": sha256_file(control_index_path),
        },
        "thresholds": {
            "minimum_land_sea_match_ratio": 0.98,
            "minimum_transport_exact_match_ratio": 0.95,
        },
        "sheet_count": len(results),
        "results": results,
    }
    _atomic_write_bytes(
        report_path,
        (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
        replace=replace,
    )
    return report


def _preflight_outputs(paths: Iterable[Path], *, replace: bool) -> None:
    if replace:
        return
    existing = sorted(str(path) for path in paths if path.exists())
    if existing:
        raise ReviewedMasterError(
            "refusing to overwrite existing reviewed v2 output(s): "
            + ", ".join(existing)
        )


def write_reviewed_master(
    *,
    sheet_id: str = DEFAULT_SHEET_ID,
    output_dir: Path = DEFAULT_OUTPUT_ROOT,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    contract_path: Path = DEFAULT_CONTRACT,
    map_sheets_path: Path = DEFAULT_MAP_SHEETS,
    seed: int = DEFAULT_SEED,
    replace: bool = False,
    emit_masks: bool = False,
    golden_style_path: Path | None = None,
    golden_style_sha256: str | None = None,
    golden_style_preview_only: bool = False,
    material_atlas_path: Path = DEFAULT_MATERIAL_ATLAS,
    global_neutral_material_path: Path = DEFAULT_GLOBAL_NEUTRAL_MATERIAL,
    canonical_control_index_path: Path = DEFAULT_CANONICAL_CONTROL_INDEX,
    material_transfer_mode: str = RESIDUAL_MATERIAL_MODE,
    use_highland_detail_exemplar: bool = False,
) -> dict[str, Any]:
    if (
        material_transfer_mode in PREVIEW_ONLY_MATERIAL_MODES
        and sheet_id != "sheet_region_royal_capital_region"
    ):
        raise ReviewedMasterError(
            f"{material_transfer_mode} is a Royal-only prototype"
        )
    output_dir = _validate_output_dir(output_dir)
    golden_style = _golden_style_lock(
        golden_style_path,
        golden_style_sha256,
        preview_only=golden_style_preview_only,
    )
    material_source = (
        _global_neutral_material_record(global_neutral_material_path)
        if material_transfer_mode == GLOBAL_NEUTRAL_BANDPASS_MODE
        else _material_atlas_record(
            material_atlas_path,
            transfer_mode=material_transfer_mode,
        )
    )
    control_index, control_sheet = _control_sheet_record(
        sheet_id,
        canonical_control_index_path,
    )
    sources, contract, sheet, validation = load_render_context(
        sheet_id=sheet_id,
        source_dir=source_dir,
        contract_path=contract_path,
        map_sheets_path=map_sheets_path,
    )
    transform = SheetCanvasTransform(contract, sheet)
    paths = _sheet_output_paths(output_dir, sheet_id, emit_masks=emit_masks)
    _preflight_outputs(paths.values(), replace=replace)
    master, stats = render_reviewed_master(
        sources,
        contract,
        sheet,
        seed=seed,
        material_atlas_path=material_atlas_path,
        global_neutral_material_path=global_neutral_material_path,
        style_profile=golden_style.get("style_profile"),
        material_transfer_mode=material_transfer_mode,
        use_highland_detail_exemplar=use_highland_detail_exemplar,
    )
    contact, panels = render_contact_sheet(master, transform)
    observed_masks: dict[str, Image.Image] = {}
    try:
        _atomic_write_bytes(paths["master"], _png_bytes(master), replace=replace)
        _atomic_write_bytes(
            paths["contact_sheet"], _png_bytes(contact), replace=replace
        )
        outputs: dict[str, Any] = {
            "master": _image_record(paths["master"]),
            "contact_sheet": {
                **_image_record(paths["contact_sheet"]),
                "panel_order": panels,
                "contains_text": False,
                "contains_frame": False,
            },
            "report_path": _repo_path(paths["report"]),
        }
        if emit_masks:
            observed_masks = render_observed_masks(
                sources,
                contract,
                sheet,
                seed=seed,
            )
            _atomic_write_bytes(
                paths["observed_land_sea_mask"],
                _png_bytes(observed_masks["land_sea"]),
                replace=replace,
            )
            _atomic_write_bytes(
                paths["observed_transport_mask"],
                _png_bytes(observed_masks["transport"]),
                replace=replace,
            )
            outputs["observed_land_sea_mask"] = {
                **_image_record(paths["observed_land_sea_mask"]),
                "semantics": "0=sea-or-water, 255=ordinary-plan-land",
            }
            outputs["observed_transport_mask"] = {
                **_image_record(paths["observed_transport_mask"]),
                "semantics": "255=exact canonical transport centerline, one pixel",
            }
        report = {
            "schema_version": "1.0.0",
            "id": f"{sheet_id}-reviewed-direct-master-v2",
            "status": (
                "preview-only"
                if material_transfer_mode in PREVIEW_ONLY_MATERIAL_MODES
                else "passed"
                if golden_style.get("status") == "locked"
                else "preview-only"
                if golden_style.get("status") == "locked-preview-only"
                else "pending-golden-style"
            ),
            "generated_by": {
                "id": GENERATOR_ID,
                "path": _repo_path(Path(__file__)),
                "sha256": sha256_file(Path(__file__)),
            },
            "purpose": (
                "Phase 5 Royal full-spatial-material prototype only"
                if material_transfer_mode == FULL_SPATIAL_MATERIAL_MODE
                else "Phase 5 Royal global-neutral-bandpass prototype only"
                if material_transfer_mode == GLOBAL_NEUTRAL_BANDPASS_MODE
                else "Phase 5 deterministic reviewed canonical master v2"
            ),
            "coordinate_reference_system": "EA-WORLD-1",
            "inputs": {
                "golden_style": golden_style,
                "material_atlas": (
                    None
                    if material_transfer_mode == GLOBAL_NEUTRAL_BANDPASS_MODE
                    else material_source
                ),
                "global_neutral_material": (
                    material_source
                    if material_transfer_mode == GLOBAL_NEUTRAL_BANDPASS_MODE
                    else None
                ),
                "canonical_control_index": control_index,
                "canonical_sheet_qa_controls": control_sheet["qa_controls"],
            },
            "sheet": {
                "sheet_id": sheet_id,
                "sheet_type": sheet["sheet_type"],
                "source_feature_id": sheet.get("source_feature_id"),
                "bounds": sheet["bounds"],
                "native_zoom": sheet["native_zoom"],
                "pixel_bounds": sheet["pixel_bounds"],
                "width": sheet["width"],
                "height": sheet["height"],
            },
            "resolution_contract": {
                "path": _repo_path(contract_path),
                "sha256": sha256_file(contract_path),
                "validation_valid": validation["valid"],
            },
            "map_sheets": {
                "path": _repo_path(map_sheets_path),
                "sha256": sha256_file(map_sheets_path),
            },
            "transform": {
                "operation": "EA-WORLD-1 to native global pixel grid, then sheet offset",
                "rounding": "round-half-up",
                "source_coordinates_modified": False,
                "world_crop_or_upscale_used": False,
            },
            "anchoring": {
                "algorithm": "sha256-namespaced globally anchored jittered EA-WORLD-1 grid v2",
                "seed": seed,
                "coordinate_identity": "grid hash excludes sheet id and local pixel origin",
                "same_world_coordinate_same_pattern": True,
                "feature_identity_in_namespace": True,
            },
            "style": {
                "profile": "flat-orthographic-sepia-blue-copperplate-v2.2",
                "golden_style_statistics_only": {
                    "applied": stats["golden_style_statistics_applied"],
                    "profile_sha256": stats["golden_style_profile_sha256"],
                    "used_as_geometry": False,
                    "copied_pixels": 0,
                    "preview_only": golden_style.get("status")
                    == "locked-preview-only",
                },
                "palette": PALETTE,
                "contains_text": False,
                "font_rendering_used": False,
                "contains_frame": False,
                "canopy_grammar": (
                    "connected flat wash with irregular 2-7px chips, gaps, and "
                    "short curved hachure; no mass seams, round stamps, highlights, or trunks"
                ),
                "capital_parcel_grammar": (
                    "EA-WORLD-1 shared irregular boundaries clipped away from canonical "
                    "settlement, road, river, forest, and label-quiet corridors"
                ),
                "mountain_grammar": "top-view irregular short disconnected axis strokes and chips",
                "settlement_grammar": "flat building footprints, streets, and courtyards; no roof or facade",
                "floating_island_grammar": "ordinary plan land polygon; no underside or side face",
                "terrain_vocabularies": sorted(SUPPORTED_TERRAIN_TYPES),
                "atlas_material_grammar": (
                    "reviewed full spatial safe crops; varied source windows, "
                    "quarter-turns, reflections, nonperiodic scales, overlapping "
                    "Gaussian feather; Golden-token luma normalisation; inward "
                    "semantic feather and canonical land/water/line reclip; exact "
                    "settlement geometry is drawn afterward without coordinate change"
                    if material_transfer_mode == FULL_SPATIAL_MATERIAL_MODE
                    else "hash-locked rejected source converted to grayscale; "
                    "fine source-minus-Gaussian1.5 plus mid Gaussian1.5-minus-"
                    "Gaussian18 only; broad source tone and RGB discarded; global "
                    "canonical-land raised-cosine quilt; no semantic atlas masks or "
                    "region washes; final water and line-guard reclip"
                    if material_transfer_mode == GLOBAL_NEUTRAL_BANDPASS_MODE
                    else "reviewed original-resolution safe crops; signed RGB high-pass "
                    "with explicit per-channel zero mean; 64-160px semantic feather; "
                    "EA-WORLD-1 smooth strength noise; canonical land/line reclip"
                ),
                "texture_toggle_invariant": (
                    "texture may add only fine ink grain; no atlas crop, semantic "
                    "polygon, rectangle, triangle, or strip boundary may appear"
                ),
                "forbidden_counters": {
                    counter: stats[counter] for counter in FORBIDDEN_COUNTERS
                },
            },
            "stroke_contract": {
                "sheet_type_caps_px": STROKE_CAPS_PX[str(sheet["sheet_type"])],
                "canonical_centerlines_modified": False,
                "river_visual_interpolation": stats["river_visual_interpolation"],
                "river_canonical_control_vertices_preserved": stats[
                    "river_canonical_control_vertices_preserved"
                ],
                "river_core_max_px_observed": stats["river_core_max_px"],
                "road_core_max_px_observed": stats["road_core_max_px"],
            },
            "sources": _source_records(sources, source_dir, sheet["bounds"]),
            "render_stats": stats,
            "outputs": outputs,
            "determinism": {
                "deterministic": True,
                "png_options": PNG_OPTIONS,
            },
            "promotion_eligible": (
                material_transfer_mode not in PREVIEW_ONLY_MATERIAL_MODES
                and golden_style.get("status") == "locked"
            ),
        }
        highland_record = stats.get("highland_detail_exemplar")
        if isinstance(highland_record, dict):
            report["inputs"]["highland_detail_exemplar"] = highland_record["input"]
            report["style"]["highland_detail_exemplar_statistics_only"] = {
                "applied": True,
                "contract_id": highland_record["contract_id"],
                "target_sheet_id": highland_record["target_sheet_id"],
                "target_feature_id": highland_record["target_feature_id"],
                **highland_record["application"],
            }
        payload = (
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        _atomic_write_bytes(paths["report"], payload, replace=replace)
        return report
    finally:
        master.close()
        contact.close()
        for mask in observed_masks.values():
            mask.close()


def write_prototype(**kwargs: Any) -> dict[str, Any]:
    """Backward-compatible entry point for callers of the v1 prototype."""

    return write_reviewed_master(**kwargs)


def render_ecology_contact_sheet(
    master_paths: Sequence[Path],
    sheet_ids: Sequence[str],
) -> tuple[Image.Image, list[dict[str, Any]]]:
    if (
        len(master_paths) != len(REPRESENTATIVE_SHEET_IDS)
        or tuple(sheet_ids) != REPRESENTATIVE_SHEET_IDS
    ):
        raise ReviewedMasterError(
            "ecology contact sheet requires the six representative sheets in canonical order"
        )
    panel_size = (480, 300)
    gutter = 12
    sheet = Image.new(
        "RGB",
        (
            panel_size[0] * 3 + gutter * 2,
            panel_size[1] * 2 + gutter,
        ),
        PALETTE["parchment_light"],
    )
    records: list[dict[str, Any]] = []
    for index, (path, sheet_id) in enumerate(zip(master_paths, sheet_ids)):
        with Image.open(path) as source:
            source.load()
            panel = ImageOps.fit(
                source.convert("RGB"),
                panel_size,
                method=Image.Resampling.LANCZOS,
            )
        column = index % 3
        row = index // 3
        left = column * (panel_size[0] + gutter)
        top = row * (panel_size[1] + gutter)
        sheet.paste(panel, (left, top))
        panel.close()
        records.append(
            {
                "sheet_id": sheet_id,
                "master_path": _repo_path(path),
                "panel_box_px": [left, top, left + panel_size[0], top + panel_size[1]],
                "fit": "center-crop-lanczos",
            }
        )
    return sheet, records


def write_generation_batch(
    *,
    sheet_ids: Sequence[str] | None = None,
    output_dir: Path = DEFAULT_OUTPUT_ROOT,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    contract_path: Path = DEFAULT_CONTRACT,
    map_sheets_path: Path = DEFAULT_MAP_SHEETS,
    seed: int = DEFAULT_SEED,
    replace: bool = False,
    emit_masks: bool = False,
    golden_style_path: Path | None = None,
    golden_style_sha256: str | None = None,
    golden_style_preview_only: bool = False,
    material_atlas_path: Path = DEFAULT_MATERIAL_ATLAS,
    canonical_control_index_path: Path = DEFAULT_CANONICAL_CONTROL_INDEX,
    material_transfer_mode: str = RESIDUAL_MATERIAL_MODE,
    use_highland_detail_exemplar: bool = False,
) -> dict[str, Any]:
    if material_transfer_mode in PREVIEW_ONLY_MATERIAL_MODES:
        raise ReviewedMasterError(
            f"{material_transfer_mode} is Royal-only and cannot run as a batch"
        )
    output_dir = _validate_output_dir(output_dir)
    exact_ids = generation_sheet_ids(
        contract_path=contract_path,
        map_sheets_path=map_sheets_path,
    )
    selected = tuple(exact_ids if sheet_ids is None else sheet_ids)
    if not selected or len(selected) != len(set(selected)):
        raise ReviewedMasterError("batch sheet ids must be non-empty and unique")
    unknown = set(selected) - set(exact_ids)
    if unknown:
        raise ReviewedMasterError(
            f"batch contains non-generation sheets: {sorted(unknown)!r}"
        )
    if (
        use_highland_detail_exemplar
        and highland_detail_exemplar.TARGET_SHEET_ID in selected
    ):
        try:
            highland_detail_exemplar.validate_production_exemplar()
        except highland_detail_exemplar.HighlandDetailExemplarError as exc:
            raise ReviewedMasterError(str(exc)) from exc

    batch_report_path = output_dir / "phase5-reviewed-v2.batch-report.json"
    ecology_path = output_dir / "phase5-reviewed-v2.ecology-contact-sheet.png"
    ecology_report_path = (
        output_dir / "phase5-reviewed-v2.ecology-contact-sheet.report.json"
    )
    preflight: list[Path] = [batch_report_path]
    for sheet_id in selected:
        preflight.extend(
            _sheet_output_paths(output_dir, sheet_id, emit_masks=emit_masks).values()
        )
    has_representatives = all(
        sheet_id in selected for sheet_id in REPRESENTATIVE_SHEET_IDS
    )
    if has_representatives:
        preflight.extend((ecology_path, ecology_report_path))
    _preflight_outputs(preflight, replace=replace)

    reports = []
    for sheet_id in selected:
        reports.append(
            write_reviewed_master(
                sheet_id=sheet_id,
                output_dir=output_dir,
                source_dir=source_dir,
                contract_path=contract_path,
                map_sheets_path=map_sheets_path,
                seed=seed,
                replace=replace,
                emit_masks=emit_masks,
                golden_style_path=golden_style_path,
                golden_style_sha256=golden_style_sha256,
                golden_style_preview_only=golden_style_preview_only,
                material_atlas_path=material_atlas_path,
                canonical_control_index_path=canonical_control_index_path,
                material_transfer_mode=material_transfer_mode,
                use_highland_detail_exemplar=use_highland_detail_exemplar,
            )
        )

    ecology_record: dict[str, Any] | None = None
    if has_representatives:
        representative_paths = [
            output_dir / f"{sheet_id}.png" for sheet_id in REPRESENTATIVE_SHEET_IDS
        ]
        ecology, panels = render_ecology_contact_sheet(
            representative_paths,
            REPRESENTATIVE_SHEET_IDS,
        )
        try:
            _atomic_write_bytes(ecology_path, _png_bytes(ecology), replace=replace)
        finally:
            ecology.close()
        ecology_report = {
            "schema_version": "1.0.0",
            "id": "phase5-reviewed-v2-ecology-contact-sheet",
            "contains_text": False,
            "contains_frame": False,
            "panel_order": panels,
            "output": _image_record(ecology_path),
        }
        _atomic_write_bytes(
            ecology_report_path,
            (
                json.dumps(ecology_report, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n"
            ).encode("utf-8"),
            replace=replace,
        )
        ecology_record = {
            **_image_record(ecology_path),
            "report_path": _repo_path(ecology_report_path),
            "report_sha256": sha256_file(ecology_report_path),
        }

    batch_report = {
        "schema_version": "1.0.0",
        "id": "phase5-reviewed-v2-generation-batch",
        "status": (
            "passed"
            if all(report.get("status") == "passed" for report in reports)
            else "preview-only"
            if all(report.get("status") == "preview-only" for report in reports)
            else "pending-golden-style"
        ),
        "coordinate_reference_system": "EA-WORLD-1",
        "seed": seed,
        "mode": "all-generation" if selected == exact_ids else "selected-generation",
        "exact_generation_sheet_count": len(exact_ids),
        "selected_sheet_ids": list(selected),
        "all_generation_contract_satisfied": selected == exact_ids,
        "masters": [report["outputs"]["master"] for report in reports],
        "ecology_contact_sheet": ecology_record,
        "contains_text": False,
        "contains_frame": False,
    }
    _atomic_write_bytes(
        batch_report_path,
        (
            json.dumps(batch_report, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8"),
        replace=replace,
    )
    return batch_report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--all-generation", action="store_true")
    mode.add_argument("--representative-six", action="store_true")
    mode.add_argument("--all-generation-masks", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--map-sheets", type=Path, default=DEFAULT_MAP_SHEETS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--emit-masks", action="store_true")
    parser.add_argument("--golden-style", type=Path)
    parser.add_argument("--golden-style-sha256")
    parser.add_argument(
        "--golden-style-preview-only",
        action="store_true",
        help=(
            "derive non-spatial style statistics from an unaccepted Golden candidate; "
            "the report remains preview-only and cannot be promoted"
        ),
    )
    parser.add_argument("--material-atlas", type=Path, default=DEFAULT_MATERIAL_ATLAS)
    parser.add_argument(
        "--highland-detail-exemplar",
        action="store_true",
        help=(
            "apply the exact hash-locked statistics-only highland detail bridge "
            "to the Soaring Mountains sheet; fail closed if the asset is absent"
        ),
    )
    material_preview = parser.add_mutually_exclusive_group()
    material_preview.add_argument(
        "--full-spatial-material-preview",
        action="store_true",
        help=(
            "Royal-only preview: retain complete approved atlas spatial material "
            "through a deterministic overlapping EA-WORLD-1 quilt"
        ),
    )
    material_preview.add_argument(
        "--global-neutral-bandpass-preview",
        action="store_true",
        help=(
            "Royal-only, promotion-ineligible preview: add only a grayscale "
            "zero-mean fine/mid bandpass from the hash-locked neutral source"
        ),
    )
    parser.add_argument(
        "--canonical-control-index",
        type=Path,
        default=DEFAULT_CANONICAL_CONTROL_INDEX,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    material_transfer_mode = (
        FULL_SPATIAL_MATERIAL_MODE
        if args.full_spatial_material_preview
        else GLOBAL_NEUTRAL_BANDPASS_MODE
        if args.global_neutral_bandpass_preview
        else RESIDUAL_MATERIAL_MODE
    )
    try:
        if args.all_generation_masks:
            if args.highland_detail_exemplar:
                raise ReviewedMasterError(
                    "the highland detail exemplar is not applicable to mask-only output"
                )
            batch = write_generation_mask_batch(
                output_dir=args.output_dir,
                source_dir=args.source_dir,
                contract_path=args.contract,
                map_sheets_path=args.map_sheets,
                control_index_path=args.canonical_control_index,
                seed=args.seed,
                replace=args.replace,
            )
            print(
                "Phase 5 mask-only batch rendered: "
                f"count={batch['sheet_count']} status={batch['status']}"
            )
            return 0
        if args.all_generation or args.representative_six:
            batch = write_generation_batch(
                sheet_ids=(
                    REPRESENTATIVE_SHEET_IDS if args.representative_six else None
                ),
                output_dir=args.output_dir,
                source_dir=args.source_dir,
                contract_path=args.contract,
                map_sheets_path=args.map_sheets,
                seed=args.seed,
                replace=args.replace,
                emit_masks=args.emit_masks,
                golden_style_path=args.golden_style,
                golden_style_sha256=args.golden_style_sha256,
                golden_style_preview_only=args.golden_style_preview_only,
                material_atlas_path=args.material_atlas,
                canonical_control_index_path=args.canonical_control_index,
                material_transfer_mode=material_transfer_mode,
                use_highland_detail_exemplar=args.highland_detail_exemplar,
            )
            print(
                "Phase 5 reviewed master batch rendered: "
                f"count={len(batch['masters'])} mode={batch['mode']}"
            )
            return 0
        report = write_reviewed_master(
            sheet_id=args.sheet_id,
            output_dir=args.output_dir,
            source_dir=args.source_dir,
            contract_path=args.contract,
            map_sheets_path=args.map_sheets,
            seed=args.seed,
            replace=args.replace,
            emit_masks=args.emit_masks,
            golden_style_path=args.golden_style,
            golden_style_sha256=args.golden_style_sha256,
            golden_style_preview_only=args.golden_style_preview_only,
            material_atlas_path=args.material_atlas,
            canonical_control_index_path=args.canonical_control_index,
            material_transfer_mode=material_transfer_mode,
            use_highland_detail_exemplar=args.highland_detail_exemplar,
        )
    except (OSError, RenderError, ReviewedMasterError) as exc:
        print(f"Phase 5 reviewed master v2 render failed: {exc}")
        return 1
    master = report["outputs"]["master"]
    print(
        "Phase 5 reviewed master v2 rendered: "
        f"{master['path']} {master['width']}x{master['height']} "
        f"sha256={master['sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
