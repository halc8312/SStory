#!/usr/bin/env python3
"""Render deterministic Phase 5 metatile controls from reviewed coordinate sources.

The renderer deliberately does not infer geography.  It consumes only the
resolution contract, map-sheet catalog, and the six coordinate-bearing source
GeoJSON files.  Every ImageGen visual guide is paired with a hash-locked
protected-composite control.  Pixels without a source-backed land/water class,
including canvas pixels outside the bounded master, are marked unknown and must
fall back to the deterministic parent context instead of retaining raw ImageGen
output.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    from jsonschema import Draft7Validator
    from PIL import Image, ImageChops, ImageDraw, ImageOps
except ImportError as exc:  # pragma: no cover - CLI environment failure
    raise RuntimeError(
        "Pillow and jsonschema are required: python -m pip install Pillow jsonschema"
    ) from exc

from production_common import ID_PATTERN, REPO_ROOT, ValidationFailure, dump_json, load_json
from validate_resolution_contract import validate_resolution_contract


GENERATOR_ID = "sstory-map-production/render_phase5_metatile_controls.py@1"
INDEX_SCHEMA_URL = (
    "https://sstory.example/schemas/phase5-metatile-control-index.schema.json"
)
PROTECTED_SCHEMA_URL = (
    "https://sstory.example/schemas/phase5-protected-control.schema.json"
)
DEFAULT_CONTRACT = (
    REPO_ROOT / "world" / "map-production" / "spec" / "resolution-contract.json"
)
DEFAULT_CATALOG = (
    REPO_ROOT / "world" / "map-production" / "source" / "map-sheets.json"
)
DEFAULT_INDEX_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-metatile-control-index.schema.json"
)
DEFAULT_PROTECTED_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-protected-control.schema.json"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "world" / "map-production" / "controls" / "phase5-metatiles"
)
SOURCE_FILES = {
    "landmasses": REPO_ROOT
    / "world"
    / "map-production"
    / "source"
    / "landmasses.geojson",
    "regions": REPO_ROOT
    / "world"
    / "map-production"
    / "source"
    / "regions.geojson",
    "terrain": REPO_ROOT
    / "world"
    / "map-production"
    / "source"
    / "terrain.geojson",
    "hydrography": REPO_ROOT
    / "world"
    / "map-production"
    / "source"
    / "hydrography.geojson",
    "settlement-footprints": REPO_ROOT
    / "world"
    / "map-production"
    / "source"
    / "settlement-footprints.geojson",
    "transport-geometries": REPO_ROOT
    / "world"
    / "map-production"
    / "source"
    / "transport-geometries.geojson",
}
SOURCE_ROLES = tuple(SOURCE_FILES)
METATILE_SIZE = 2048
PIXEL_COUNT = METATILE_SIZE * METATILE_SIZE
PNG_SAVE_OPTIONS = {"format": "PNG", "compress_level": 9, "optimize": False}

UNKNOWN_RGB = (52, 49, 58)
UNKNOWN_HATCH_RGB = (87, 79, 92)
LAND_RGB = (196, 180, 132)
WATER_RGB = (59, 103, 132)
LAND_GUIDE_RGB = (222, 206, 157)
WATER_GUIDE_RGB = (85, 138, 164)
REGION_RGB = (118, 98, 57)
TERRAIN_RGB = (105, 122, 72)
HYDRO_RGB = (92, 160, 190)
SETTLEMENT_RGB = (150, 80, 70)
TRANSPORT_COLORS = {
    "road": (126, 73, 45),
    "rail": (88, 64, 109),
    "sea": (58, 131, 162),
    "air": (154, 101, 167),
    "caravan": (157, 105, 50),
    "submarine": (46, 103, 139),
    "underwater_tunnel": (49, 92, 120),
    "tunnel": (85, 78, 74),
    "warp": (142, 76, 153),
}
DETAIL_PROVENANCE = (
    "No reviewed raster-safe detail exists; provisional outlines remain guide-only "
    "and labels/POIs remain vector data."
)


class Phase5ControlError(ValueError):
    """Raised when inputs or generated controls fail a closed validation."""


@dataclass(frozen=True)
class CanonFeature:
    """One validated coordinate feature with immutable source provenance."""

    role: str
    feature_id: str
    geometry_type: str
    coordinates: Any
    properties: dict[str, Any]
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class TileTransform:
    """Exact EA-WORLD-1 to one native-zoom metatile transform."""

    contract: dict[str, Any]
    sheet_contract: dict[str, Any]
    canvas_origin: tuple[int, int]

    @property
    def native_scale(self) -> Fraction:
        world = self.contract["world_raster"]
        exponent = self.sheet_contract["native_zoom"] - world["native_zoom"]
        base = self.contract["pixel_bounds_formula"]["scale_base"]
        if exponent >= 0:
            return Fraction(base**exponent, 1)
        return Fraction(1, base ** -exponent)

    def _global_coordinate(self, value: float, axis: str) -> Fraction:
        extent = self.contract["world_extent"]
        world = self.contract["world_raster"]
        minimum = Fraction(str(extent[f"min_{axis}"]))
        maximum = Fraction(str(extent[f"max_{axis}"]))
        pixels = world["width_px"] if axis == "x" else world["height_px"]
        return (
            (Fraction(str(value)) - minimum)
            * pixels
            * self.native_scale
            / (maximum - minimum)
        )

    @staticmethod
    def _round_half_up(value: Fraction) -> int:
        return math.floor(value + Fraction(1, 2))

    def point(self, point: Sequence[int | float]) -> tuple[int, int]:
        pixel_bounds = self.sheet_contract["pixel_bounds"]
        x = self._global_coordinate(float(point[0]), "x")
        y = self._global_coordinate(float(point[1]), "y")
        return (
            self._round_half_up(x - pixel_bounds[0] - self.canvas_origin[0]),
            self._round_half_up(y - pixel_bounds[1] - self.canvas_origin[1]),
        )

    def canvas_world_bounds(self) -> list[float]:
        extent = self.contract["world_extent"]
        world = self.contract["world_raster"]
        pixel_bounds = self.sheet_contract["pixel_bounds"]
        left = pixel_bounds[0] + self.canvas_origin[0]
        top = pixel_bounds[1] + self.canvas_origin[1]
        right = left + METATILE_SIZE
        bottom = top + METATILE_SIZE
        x_pixels = Fraction(world["width_px"]) * self.native_scale
        y_pixels = Fraction(world["height_px"]) * self.native_scale

        def world_x(pixel: int) -> float:
            value = Fraction(str(extent["min_x"])) + Fraction(pixel) / x_pixels * (
                Fraction(str(extent["max_x"]))
                - Fraction(str(extent["min_x"]))
            )
            return round(float(value), 8)

        def world_y(pixel: int) -> float:
            value = Fraction(str(extent["min_y"])) + Fraction(pixel) / y_pixels * (
                Fraction(str(extent["max_y"]))
                - Fraction(str(extent["min_y"]))
            )
            return round(float(value), 8)

        return [world_x(left), world_y(top), world_x(right), world_y(bottom)]

    def nominal_width_px(self, world_width: int | float) -> int:
        world = self.contract["world_raster"]
        extent = self.contract["world_extent"]
        x_scale = (
            Fraction(world["width_px"])
            * self.native_scale
            / (Fraction(str(extent["max_x"])) - Fraction(str(extent["min_x"])))
        )
        y_scale = (
            Fraction(world["height_px"])
            * self.native_scale
            / (Fraction(str(extent["max_y"])) - Fraction(str(extent["min_y"])))
        )
        width = Fraction(str(world_width)) * (x_scale + y_scale) / 2
        return max(1, self._round_half_up(width))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise Phase5ControlError(f"artifact must remain inside the repository: {path}") from exc


def artifact(path: Path, *, logical_path: Path | None = None) -> dict[str, str]:
    return {
        "path": repo_path(logical_path or path),
        "sha256": sha256_file(path),
    }


def image_artifact(
    path: Path,
    *,
    logical_path: Path | None = None,
    expected_mode: str,
    expected_size: tuple[int, int] = (METATILE_SIZE, METATILE_SIZE),
) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            image.load()
            size = image.size
            image_format = image.format
            color_mode = image.mode
    except (OSError, ValueError) as exc:
        raise Phase5ControlError(f"cannot inspect generated image {path}: {exc}") from exc
    if size != expected_size or image_format != "PNG" or color_mode != expected_mode:
        raise Phase5ControlError(
            f"generated image contract mismatch for {path}: "
            f"size={size}, format={image_format}, mode={color_mode}"
        )
    return {
        **artifact(path, logical_path=logical_path),
        "width": size[0],
        "height": size[1],
        "format": image_format,
        "color_mode": color_mode,
    }


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, **PNG_SAVE_OPTIONS)


def artifact_only(value: dict[str, Any]) -> dict[str, str]:
    return {"path": value["path"], "sha256": value["sha256"]}


def validate_schema(document: Any, schema_path: Path, label: str) -> None:
    try:
        schema = load_json(schema_path)
    except ValidationFailure as exc:
        raise Phase5ControlError(str(exc)) from exc
    errors = sorted(
        Draft7Validator(schema).iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        rendered = []
        for error in errors[:20]:
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            rendered.append(f"{location}: {error.message}")
        raise Phase5ControlError(f"{label} is invalid: " + "; ".join(rendered))


def _iter_points(geometry_type: str, coordinates: Any) -> Iterable[Sequence[Any]]:
    if geometry_type == "LineString":
        yield from coordinates
    elif geometry_type == "MultiLineString":
        for line in coordinates:
            yield from line
    elif geometry_type == "Polygon":
        for ring in coordinates:
            yield from ring
    elif geometry_type == "MultiPolygon":
        for polygon in coordinates:
            for ring in polygon:
                yield from ring
    else:
        raise Phase5ControlError(f"unsupported canon geometry type: {geometry_type!r}")


def _validate_coordinate(point: Any, label: str) -> tuple[float, float]:
    if not (
        isinstance(point, list)
        and len(point) >= 2
        and all(
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            for value in point[:2]
        )
    ):
        raise Phase5ControlError(f"{label} contains an invalid coordinate")
    x, y = float(point[0]), float(point[1])
    if not (0 <= x <= 10000 and 0 <= y <= 10000):
        raise Phase5ControlError(f"{label} coordinate escapes EA-WORLD-1: {(x, y)}")
    return x, y


def load_canon_sources(
    source_files: dict[str, Path] = SOURCE_FILES,
) -> tuple[dict[str, list[CanonFeature]], list[dict[str, str]]]:
    if tuple(source_files) != SOURCE_ROLES:
        raise Phase5ControlError("canon source roles or order differ from the fixed contract")
    by_role: dict[str, list[CanonFeature]] = {}
    source_artifacts: list[dict[str, str]] = []
    for role, path in source_files.items():
        try:
            document = load_json(path)
        except ValidationFailure as exc:
            raise Phase5ControlError(str(exc)) from exc
        if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
            raise Phase5ControlError(f"{path} must be a GeoJSON FeatureCollection")
        if document.get("coordinate_reference_system") != "EA-WORLD-1":
            raise Phase5ControlError(f"{path} must declare EA-WORLD-1")
        values = document.get("features")
        if not isinstance(values, list):
            raise Phase5ControlError(f"{path}.features must be an array")
        seen: set[str] = set()
        features: list[CanonFeature] = []
        for index, value in enumerate(values):
            label = f"{path}.features[{index}]"
            if not isinstance(value, dict) or value.get("type") != "Feature":
                raise Phase5ControlError(f"{label} must be a GeoJSON Feature")
            properties = value.get("properties")
            geometry = value.get("geometry")
            if not isinstance(properties, dict) or not isinstance(geometry, dict):
                raise Phase5ControlError(f"{label} lacks properties or geometry")
            feature_id = properties.get("id")
            if not isinstance(feature_id, str) or not ID_PATTERN.fullmatch(feature_id):
                raise Phase5ControlError(f"{label}.properties.id is invalid")
            if feature_id in seen:
                raise Phase5ControlError(f"{path} duplicates feature id {feature_id!r}")
            seen.add(feature_id)
            geometry_type = geometry.get("type")
            coordinates = geometry.get("coordinates")
            points = [
                _validate_coordinate(point, label)
                for point in _iter_points(str(geometry_type), coordinates)
            ]
            if not points:
                raise Phase5ControlError(f"{label} contains no coordinates")
            if geometry_type in {"Polygon", "MultiPolygon"}:
                polygons = coordinates if geometry_type == "MultiPolygon" else [coordinates]
                for polygon in polygons:
                    for ring in polygon:
                        if len(ring) < 4 or ring[0][:2] != ring[-1][:2]:
                            raise Phase5ControlError(f"{label} contains an open polygon ring")
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            features.append(
                CanonFeature(
                    role=role,
                    feature_id=feature_id,
                    geometry_type=str(geometry_type),
                    coordinates=coordinates,
                    properties=dict(properties),
                    bbox=(min(xs), min(ys), max(xs), max(ys)),
                )
            )
        by_role[role] = features
        source_artifacts.append({"role": role, **artifact(path)})
    return by_role, source_artifacts


def load_plan_inputs(
    contract_path: Path = DEFAULT_CONTRACT,
    catalog_path: Path = DEFAULT_CATALOG,
    source_files: dict[str, Path] = SOURCE_FILES,
) -> dict[str, Any]:
    derived = validate_resolution_contract(
        contract_path,
        catalog_path,
        check_catalog=True,
    )
    if not derived["valid"]:
        raise Phase5ControlError(
            "resolution/catalog contract is invalid: " + "; ".join(derived["errors"])
        )
    try:
        contract = load_json(contract_path)
        catalog = load_json(catalog_path)
    except ValidationFailure as exc:
        raise Phase5ControlError(str(exc)) from exc
    catalog_by_id = {sheet["id"]: sheet for sheet in catalog["sheets"]}
    sheet_contracts = {
        sheet["sheet_id"]: sheet
        for sheet in derived["sheets"]
        if sheet["production_method"] == "imagegen-metatile"
    }
    if len(sheet_contracts) != 17 or sum(
        value["metatiles"]["count"] for value in sheet_contracts.values()
    ) != 99:
        raise Phase5ControlError("Phase 5 generation plan must contain 17 sheets / 99 tiles")
    features, source_artifacts = load_canon_sources(source_files)
    return {
        "contract": contract,
        "catalog": catalog,
        "catalog_by_id": catalog_by_id,
        "sheet_contracts": sheet_contracts,
        "features": features,
        "source_inputs": {
            "resolution_contract": artifact(contract_path),
            "map_sheets": artifact(catalog_path),
            "canon_sources": source_artifacts,
        },
    }


def build_metatile_plan(sheet_contract: dict[str, Any]) -> dict[str, Any]:
    profile = sheet_contract.get("metatiles")
    if not isinstance(profile, dict):
        raise Phase5ControlError(f"{sheet_contract['sheet_id']} lacks a metatile profile")
    width = sheet_contract["width"]
    height = sheet_contract["height"]
    size = profile["size_px"]
    gutter = profile["gutter_each_side_px"]
    stride = profile["stride_px"]
    if size != METATILE_SIZE:
        raise Phase5ControlError("Phase 5 controls require native 2048 px metatiles")
    tiles: list[dict[str, Any]] = []
    for row in range(profile["rows"]):
        for column in range(profile["columns"]):
            canvas_x = column * stride
            canvas_y = row * stride
            source_left = 0 if column == 0 else gutter
            source_top = 0 if row == 0 else gutter
            source_right = (
                min(size, width - canvas_x)
                if column == profile["columns"] - 1
                else size - gutter
            )
            source_bottom = (
                min(size, height - canvas_y)
                if row == profile["rows"] - 1
                else size - gutter
            )
            if source_right <= source_left or source_bottom <= source_top:
                raise Phase5ControlError(
                    f"{sheet_contract['sheet_id']} contains an empty metatile core"
                )
            tiles.append(
                {
                    "sheet_sequence": row * profile["columns"] + column,
                    "column": column,
                    "row": row,
                    "canvas_origin_px": [canvas_x, canvas_y],
                    "source_core_box_px": [
                        source_left,
                        source_top,
                        source_right,
                        source_bottom,
                    ],
                    "destination_box_px": [
                        canvas_x + source_left,
                        canvas_y + source_top,
                        canvas_x + source_right,
                        canvas_y + source_bottom,
                    ],
                    "active_box_px": [
                        0,
                        0,
                        min(size, width - canvas_x),
                        min(size, height - canvas_y),
                    ],
                }
            )
    if len(tiles) != profile["count"]:
        raise Phase5ControlError(f"{sheet_contract['sheet_id']} tile count is stale")
    area = sum(
        (tile["destination_box_px"][2] - tile["destination_box_px"][0])
        * (tile["destination_box_px"][3] - tile["destination_box_px"][1])
        for tile in tiles
    )
    if area != width * height:
        raise Phase5ControlError(f"{sheet_contract['sheet_id']} plan does not cover its master")
    return {
        "sheet_id": sheet_contract["sheet_id"],
        "master_size": [width, height],
        "metatile_size_px": size,
        "gutter_each_side_px": gutter,
        "stride_px": stride,
        "columns": profile["columns"],
        "rows": profile["rows"],
        "count": profile["count"],
        "tiles": tiles,
    }


def _polygon_sets(feature: CanonFeature) -> Iterable[Any]:
    if feature.geometry_type == "Polygon":
        yield feature.coordinates
    elif feature.geometry_type == "MultiPolygon":
        yield from feature.coordinates
    else:
        raise Phase5ControlError(
            f"{feature.role}/{feature.feature_id} is not a polygon geometry"
        )


def _line_sets(feature: CanonFeature) -> Iterable[Any]:
    if feature.geometry_type == "LineString":
        yield feature.coordinates
    elif feature.geometry_type == "MultiLineString":
        yield from feature.coordinates
    else:
        raise Phase5ControlError(
            f"{feature.role}/{feature.feature_id} is not a line geometry"
        )


def _draw_polygon(
    draw: ImageDraw.ImageDraw,
    feature: CanonFeature,
    transform: TileTransform,
    *,
    fill: int | tuple[int, int, int] | None,
    outline: int | tuple[int, int, int] | None = None,
    width: int = 1,
) -> None:
    for polygon in _polygon_sets(feature):
        exterior = [transform.point(point) for point in polygon[0]]
        draw.polygon(exterior, fill=fill, outline=outline, width=width)
        # No current source polygon has holes.  Refuse silent fabrication if a
        # future source adds one until its underlying class is explicitly known.
        if len(polygon) > 1:
            raise Phase5ControlError(
                f"polygon holes require an explicit underlying class: {feature.feature_id}"
            )


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    feature: CanonFeature,
    transform: TileTransform,
    *,
    fill: int | tuple[int, int, int],
    width: int,
) -> None:
    for line in _line_sets(feature):
        points = [transform.point(point) for point in line]
        if len(points) >= 2:
            draw.line(points, fill=fill, width=width, joint="curve")


def _active_mask(active_box: Sequence[int]) -> Image.Image:
    left, top, right, bottom = active_box
    if not (0 <= left < right <= METATILE_SIZE and 0 <= top < bottom <= METATILE_SIZE):
        raise Phase5ControlError(f"invalid active box: {list(active_box)}")
    mask = Image.new("L", (METATILE_SIZE, METATILE_SIZE), 0)
    ImageDraw.Draw(mask).rectangle((left, top, right - 1, bottom - 1), fill=255)
    return mask


def _parent_active_mask(
    transform: TileTransform,
    parent_sheets: Sequence[dict[str, Any]],
) -> Image.Image:
    mask = Image.new("L", (METATILE_SIZE, METATILE_SIZE), 0)
    draw = ImageDraw.Draw(mask)
    for parent in parent_sheets:
        bounds = parent.get("bounds")
        if not isinstance(bounds, list) or len(bounds) != 4:
            raise Phase5ControlError(f"parent sheet {parent.get('id')!r} is unbounded")
        left, top = transform.point((bounds[0], bounds[1]))
        right, bottom = transform.point((bounds[2], bounds[3]))
        if right > left and bottom > top:
            draw.rectangle((left, top, right - 1, bottom - 1), fill=255)
    return mask


def _render_classification(
    features: dict[str, list[CanonFeature]],
    transform: TileTransform,
    active: Image.Image,
) -> tuple[Image.Image, Image.Image, Image.Image, Image.Image]:
    # 0=unknown, 1=land, 2=water.  Later source-backed semantic overrides are
    # deliberate: explicit water cuts land, and floating islands restore land.
    classification = Image.new("L", (METATILE_SIZE, METATILE_SIZE), 0)
    draw = ImageDraw.Draw(classification)
    for feature in features["landmasses"]:
        _draw_polygon(draw, feature, transform, fill=1)
    for feature in features["hydrography"]:
        if feature.geometry_type in {"Polygon", "MultiPolygon"}:
            _draw_polygon(draw, feature, transform, fill=2)
        else:
            width = transform.nominal_width_px(
                feature.properties.get("nominal_width", 1)
            )
            _draw_lines(draw, feature, transform, fill=2, width=width)
    for feature in features["regions"]:
        if feature.properties.get("region_type") == "underwater_region":
            _draw_polygon(draw, feature, transform, fill=2)
    for feature in features["terrain"]:
        if feature.properties.get("terrain_type") == "floating_island_chain":
            _draw_polygon(draw, feature, transform, fill=1)

    clipped = ImageChops.multiply(classification, active)
    classification.close()
    land = clipped.point(lambda value: 255 if value == 1 else 0, mode="L")
    water = clipped.point(lambda value: 255 if value == 2 else 0, mode="L")
    known = clipped.point(lambda value: 255 if value in {1, 2} else 0, mode="L")
    unknown = ImageOps.invert(known)
    clipped.close()
    return land, water, known, unknown


def _transport_width(native_zoom: int) -> int:
    return max(2, 2 ** max(1, native_zoom - 4))


def _render_transport(
    features: dict[str, list[CanonFeature]],
    transform: TileTransform,
    active: Image.Image,
) -> tuple[Image.Image, Image.Image]:
    mask = Image.new("L", (METATILE_SIZE, METATILE_SIZE), 0)
    overlay = Image.new("RGB", (METATILE_SIZE, METATILE_SIZE), (0, 0, 0))
    mask_draw = ImageDraw.Draw(mask)
    overlay_draw = ImageDraw.Draw(overlay)
    width = _transport_width(transform.sheet_contract["native_zoom"])
    for feature in features["transport-geometries"]:
        color = TRANSPORT_COLORS.get(
            str(feature.properties.get("route_type")), (104, 76, 58)
        )
        _draw_lines(mask_draw, feature, transform, fill=255, width=width)
        _draw_lines(overlay_draw, feature, transform, fill=color, width=width)
    clipped_mask = ImageChops.multiply(mask, active)
    mask.close()
    black = Image.new("RGB", (METATILE_SIZE, METATILE_SIZE), (0, 0, 0))
    clipped_overlay = Image.composite(overlay, black, active)
    overlay.close()
    black.close()
    return clipped_mask, clipped_overlay


def _hatch_unknown(base: Image.Image, unknown: Image.Image) -> None:
    hatch = Image.new("RGB", base.size, UNKNOWN_RGB)
    draw = ImageDraw.Draw(hatch)
    for offset in range(-METATILE_SIZE, METATILE_SIZE * 2, 48):
        draw.line(
            (offset, 0, offset + METATILE_SIZE, METATILE_SIZE),
            fill=UNKNOWN_HATCH_RGB,
            width=3,
        )
    base.paste(hatch, (0, 0), unknown)
    hatch.close()


def _render_land_sea_overlay(
    land: Image.Image,
    water: Image.Image,
    unknown: Image.Image,
    parent_context: Image.Image | None,
) -> Image.Image:
    overlay = Image.new("RGB", (METATILE_SIZE, METATILE_SIZE), UNKNOWN_RGB)
    land_source = Image.new("RGB", overlay.size, LAND_GUIDE_RGB)
    water_source = Image.new("RGB", overlay.size, WATER_GUIDE_RGB)
    overlay.paste(land_source, (0, 0), land)
    overlay.paste(water_source, (0, 0), water)
    if parent_context is not None:
        overlay.paste(parent_context, (0, 0), unknown)
    else:
        _hatch_unknown(overlay, unknown)
    land_source.close()
    water_source.close()
    return overlay


def _render_visual(
    features: dict[str, list[CanonFeature]],
    transform: TileTransform,
    active: Image.Image,
    land: Image.Image,
    water: Image.Image,
    unknown: Image.Image,
) -> Image.Image:
    visual = Image.new("RGB", (METATILE_SIZE, METATILE_SIZE), UNKNOWN_RGB)
    land_source = Image.new("RGB", visual.size, LAND_RGB)
    water_source = Image.new("RGB", visual.size, WATER_RGB)
    visual.paste(land_source, (0, 0), land)
    visual.paste(water_source, (0, 0), water)
    land_source.close()
    water_source.close()
    _hatch_unknown(visual, unknown)

    guide = Image.new("RGB", visual.size, (0, 0, 0))
    guide_mask = Image.new("L", visual.size, 0)
    guide_draw = ImageDraw.Draw(guide)
    guide_mask_draw = ImageDraw.Draw(guide_mask)
    guide_width = max(2, 2 ** max(0, transform.sheet_contract["native_zoom"] - 5))

    for feature in features["regions"]:
        _draw_polygon(
            guide_draw,
            feature,
            transform,
            fill=None,
            outline=REGION_RGB,
            width=guide_width,
        )
        _draw_polygon(
            guide_mask_draw,
            feature,
            transform,
            fill=None,
            outline=255,
            width=guide_width,
        )
    for feature in features["terrain"]:
        if feature.geometry_type in {"Polygon", "MultiPolygon"}:
            _draw_polygon(
                guide_draw,
                feature,
                transform,
                fill=None,
                outline=TERRAIN_RGB,
                width=guide_width,
            )
            _draw_polygon(
                guide_mask_draw,
                feature,
                transform,
                fill=None,
                outline=255,
                width=guide_width,
            )
        else:
            _draw_lines(
                guide_draw,
                feature,
                transform,
                fill=TERRAIN_RGB,
                width=guide_width,
            )
            _draw_lines(
                guide_mask_draw,
                feature,
                transform,
                fill=255,
                width=guide_width,
            )
    for feature in features["hydrography"]:
        if feature.geometry_type in {"LineString", "MultiLineString"}:
            width = max(2, guide_width)
            _draw_lines(
                guide_draw,
                feature,
                transform,
                fill=HYDRO_RGB,
                width=width,
            )
            _draw_lines(
                guide_mask_draw,
                feature,
                transform,
                fill=255,
                width=width,
            )
    for feature in features["settlement-footprints"]:
        _draw_polygon(
            guide_draw,
            feature,
            transform,
            fill=SETTLEMENT_RGB,
            outline=SETTLEMENT_RGB,
            width=guide_width,
        )
        _draw_polygon(
            guide_mask_draw,
            feature,
            transform,
            fill=255,
            outline=255,
            width=guide_width,
        )
    clipped_guide_mask = ImageChops.multiply(guide_mask, active)
    visual.paste(guide, (0, 0), clipped_guide_mask)
    guide.close()
    guide_mask.close()
    clipped_guide_mask.close()
    transport_mask, transport_overlay = _render_transport(features, transform, active)
    visual.paste(transport_overlay, (0, 0), transport_mask)
    transport_mask.close()
    transport_overlay.close()
    return visual


def _bbox_intersects(
    first: Sequence[int | float], second: Sequence[int | float]
) -> bool:
    return not (
        first[2] < second[0]
        or first[0] > second[2]
        or first[3] < second[1]
        or first[1] > second[3]
    )


def visible_feature_ids(
    features: dict[str, list[CanonFeature]], world_bounds: Sequence[float]
) -> dict[str, list[str]]:
    return {
        role: sorted(
            feature.feature_id
            for feature in features[role]
            if _bbox_intersects(feature.bbox, world_bounds)
        )
        for role in SOURCE_ROLES
    }


def _mask_pixel_count(mask: Image.Image) -> int:
    histogram = mask.histogram()
    return sum(histogram[1:])


def partition_metrics(
    land: Image.Image,
    water: Image.Image,
    unknown: Image.Image,
) -> dict[str, Any]:
    if not (land.size == water.size == unknown.size == (METATILE_SIZE, METATILE_SIZE)):
        raise Phase5ControlError("partition masks must all be 2048x2048")
    land_count = _mask_pixel_count(land)
    water_count = _mask_pixel_count(water)
    unknown_count = _mask_pixel_count(unknown)
    land_water = ImageChops.multiply(land, water)
    land_unknown = ImageChops.multiply(land, unknown)
    water_unknown = ImageChops.multiply(water, unknown)
    try:
        overlap = (
            _mask_pixel_count(land_water)
            + _mask_pixel_count(land_unknown)
            + _mask_pixel_count(water_unknown)
        )
    finally:
        land_water.close()
        land_unknown.close()
        water_unknown.close()
    unclassified = PIXEL_COUNT - (land_count + water_count + unknown_count)
    if overlap != 0 or unclassified != 0:
        raise Phase5ControlError(
            f"land/water/unknown partition failed: overlap={overlap}, "
            f"unclassified={unclassified}"
        )
    return {
        "algorithm": "canon-land-water-unknown-partition-v1",
        "pixel_count": PIXEL_COUNT,
        "land_pixel_count": land_count,
        "water_pixel_count": water_count,
        "unknown_pixel_count": unknown_count,
        "overlap_pixel_count": 0,
        "unclassified_pixel_count": 0,
    }


def _sheet_parent_ids(sheet: dict[str, Any]) -> list[str]:
    values: list[str] = []
    parent = sheet.get("parent_id")
    if isinstance(parent, str):
        values.append(parent)
    secondary = sheet.get("secondary_parent_ids")
    if isinstance(secondary, list):
        values.extend(value for value in secondary if isinstance(value, str))
    if not values:
        raise Phase5ControlError(f"generation sheet {sheet.get('id')!r} has no parent")
    if len(values) != len(set(values)):
        raise Phase5ControlError(f"generation sheet {sheet.get('id')!r} repeats a parent")
    return values


def _tile_paths(
    physical_output: Path,
    logical_output: Path,
    sheet_id: str,
    column: int,
    row: int,
) -> tuple[Path, Path]:
    relative = Path(sheet_id) / f"c{column:02d}-r{row:02d}"
    return physical_output / relative, logical_output / relative


def _spec_for_saved(
    physical_dir: Path,
    logical_dir: Path,
    filename: str,
    *,
    mode: str,
) -> dict[str, Any]:
    return image_artifact(
        physical_dir / filename,
        logical_path=logical_dir / filename,
        expected_mode=mode,
    )


def render_tile_assets(
    *,
    plan_inputs: dict[str, Any],
    sheet: dict[str, Any],
    sheet_contract: dict[str, Any],
    tile_plan: dict[str, Any],
    physical_output: Path,
    logical_output: Path,
) -> dict[str, Any]:
    sheet_id = sheet["id"]
    column = tile_plan["column"]
    row = tile_plan["row"]
    physical_dir, logical_dir = _tile_paths(
        physical_output, logical_output, sheet_id, column, row
    )
    physical_dir.mkdir(parents=True, exist_ok=False)
    transform = TileTransform(
        contract=plan_inputs["contract"],
        sheet_contract=sheet_contract,
        canvas_origin=tuple(tile_plan["canvas_origin_px"]),
    )
    parent_ids = _sheet_parent_ids(sheet)
    try:
        parent_sheets = [plan_inputs["catalog_by_id"][value] for value in parent_ids]
    except KeyError as exc:
        raise Phase5ControlError(f"{sheet_id} references missing parent {exc.args[0]!r}") from exc

    child_active = _active_mask(tile_plan["active_box_px"])
    parent_active = _parent_active_mask(transform, parent_sheets)
    land, water, known, unknown = _render_classification(
        plan_inputs["features"], transform, child_active
    )
    parent_land, parent_water, _parent_known, parent_unknown = _render_classification(
        plan_inputs["features"], transform, parent_active
    )
    parent_context = _render_land_sea_overlay(
        parent_land,
        parent_water,
        parent_unknown,
        None,
    )
    visual = _render_visual(
        plan_inputs["features"],
        transform,
        child_active,
        land,
        water,
        unknown,
    )
    transport_mask, transport_overlay = _render_transport(
        plan_inputs["features"], transform, child_active
    )
    land_sea_overlay = _render_land_sea_overlay(
        land, water, unknown, parent_context
    )
    detail_mask = Image.new("L", (METATILE_SIZE, METATILE_SIZE), 0)
    detail_overlay = Image.new("RGB", (METATILE_SIZE, METATILE_SIZE), (0, 0, 0))
    metrics = partition_metrics(land, water, unknown)

    images = {
        "geometry-control.png": visual,
        "parent-context.png": parent_context,
        "land-mask.png": land,
        "water-mask.png": water,
        "known-mask.png": known,
        "unknown-mask.png": unknown,
        "land-sea-overlay.png": land_sea_overlay,
        "transport-mask.png": transport_mask,
        "transport-overlay.png": transport_overlay,
        "detail-mask.png": detail_mask,
        "detail-overlay.png": detail_overlay,
    }
    try:
        for filename, image in images.items():
            save_png(image, physical_dir / filename)
    finally:
        child_active.close()
        parent_active.close()
        parent_land.close()
        parent_water.close()
        _parent_known.close()
        parent_unknown.close()
        for image in images.values():
            image.close()

    specs = {
        "visual_geometry_control": _spec_for_saved(
            physical_dir, logical_dir, "geometry-control.png", mode="RGB"
        ),
        "parent_context": _spec_for_saved(
            physical_dir, logical_dir, "parent-context.png", mode="RGB"
        ),
        "land_mask": _spec_for_saved(
            physical_dir, logical_dir, "land-mask.png", mode="L"
        ),
        "water_mask": _spec_for_saved(
            physical_dir, logical_dir, "water-mask.png", mode="L"
        ),
        "known_mask": _spec_for_saved(
            physical_dir, logical_dir, "known-mask.png", mode="L"
        ),
        "unknown_mask": _spec_for_saved(
            physical_dir, logical_dir, "unknown-mask.png", mode="L"
        ),
        "land_sea_overlay": _spec_for_saved(
            physical_dir, logical_dir, "land-sea-overlay.png", mode="RGB"
        ),
        "transport_mask": _spec_for_saved(
            physical_dir, logical_dir, "transport-mask.png", mode="L"
        ),
        "transport_overlay": _spec_for_saved(
            physical_dir, logical_dir, "transport-overlay.png", mode="RGB"
        ),
        "detail_mask": _spec_for_saved(
            physical_dir, logical_dir, "detail-mask.png", mode="L"
        ),
        "detail_overlay": _spec_for_saved(
            physical_dir, logical_dir, "detail-overlay.png", mode="RGB"
        ),
    }
    world_bounds = transform.canvas_world_bounds()
    return {
        **tile_plan,
        "world_bounds": world_bounds,
        "feature_ids": visible_feature_ids(plan_inputs["features"], world_bounds),
        "parent_sheet_ids": parent_ids,
        "specs": specs,
        "partition": metrics,
        "physical_dir": physical_dir,
        "logical_dir": logical_dir,
    }


def _copy_prior_context(
    source_tile: dict[str, Any],
    current_tile: dict[str, Any],
    direction: str,
) -> dict[str, Any]:
    filename = f"neighbor-{direction}-geometry-context.png"
    source_path = source_tile["physical_dir"] / "geometry-control.png"
    physical_path = current_tile["physical_dir"] / filename
    logical_path = current_tile["logical_dir"] / filename
    shutil.copyfile(source_path, physical_path)
    context = image_artifact(
        physical_path,
        logical_path=logical_path,
        expected_mode="RGB",
    )
    if context["sha256"] != source_tile["specs"]["visual_geometry_control"]["sha256"]:
        raise Phase5ControlError("prior geometry context differs from its source tile")
    return context


def _position(column: int, row: int) -> dict[str, int]:
    return {"column": column, "row": row}


def bind_prior_contexts(
    sheet_tiles: list[dict[str, Any]],
    *,
    columns: int,
    rows: int,
) -> int:
    by_position = {(tile["column"], tile["row"]): tile for tile in sheet_tiles}
    context_count = 0
    for tile in sheet_tiles:
        prior: dict[str, Any] = {"north": None, "west": None}
        for direction, position, role in (
            ("north", (tile["column"], tile["row"] - 1), "neighbor-north"),
            ("west", (tile["column"] - 1, tile["row"]), "neighbor-west"),
        ):
            source = by_position.get(position)
            if source is None:
                continue
            context = _copy_prior_context(source, tile, direction)
            prior[direction] = {
                "direction": direction,
                "source_tile": _position(*position),
                "receipt_role": role,
                "binding": "generated-protected-output-required",
                "geometry_context": context,
            }
            context_count += 1
        future = {
            "east": (
                _position(tile["column"] + 1, tile["row"])
                if tile["column"] + 1 < columns
                else None
            ),
            "south": (
                _position(tile["column"], tile["row"] + 1)
                if tile["row"] + 1 < rows
                else None
            ),
        }
        tile["prior_neighbors"] = prior
        tile["future_seam_targets"] = future
    return context_count


def _write_protected_control(
    tile: dict[str, Any],
    *,
    sheet_id: str,
    source_inputs: dict[str, Any],
    schema_path: Path,
) -> dict[str, str]:
    specs = tile["specs"]
    prior_contexts = [
        {
            "direction": direction,
            "source_tile": value["source_tile"],
            "context": value["geometry_context"],
        }
        for direction in ("north", "west")
        if (value := tile["prior_neighbors"][direction]) is not None
    ]
    document = {
        "$schema": PROTECTED_SCHEMA_URL,
        "schema_version": "1.0.0",
        "type": "sstory-phase5-protected-metatile-control",
        "coordinate_reference_system": "EA-WORLD-1",
        "generated_by": GENERATOR_ID,
        "sheet_id": sheet_id,
        "column": tile["column"],
        "row": tile["row"],
        "dimensions": {"width": 2048, "height": 2048, "format": "PNG"},
        "visual_geometry_control": specs["visual_geometry_control"],
        "parent_context": specs["parent_context"],
        "prior_neighbor_contexts": prior_contexts,
        "land_sea": {
            "land_mask": specs["land_mask"],
            "water_mask": specs["water_mask"],
            "known_mask": specs["known_mask"],
            "unknown_mask": specs["unknown_mask"],
            "authoritative_overlay": specs["land_sea_overlay"],
            "partition": tile["partition"],
        },
        "transport": {
            "mask": specs["transport_mask"],
            "authoritative_overlay": specs["transport_overlay"],
            "feature_ids": tile["feature_ids"]["transport-geometries"],
            "rasterization": "source-lines-global-native-grid-v1",
        },
        "detail": {
            "status": "explicit-empty",
            "mask": specs["detail_mask"],
            "authoritative_overlay": specs["detail_overlay"],
            "feature_ids": [],
            "provenance": DETAIL_PROVENANCE,
        },
        "unknown_fallback": {
            "policy": "replace-raw-with-parent-context",
            "mask": specs["unknown_mask"],
            "source": specs["parent_context"],
        },
        "source_inputs": source_inputs,
    }
    validate_schema(document, schema_path, f"{sheet_id} protected control")
    physical_path = tile["physical_dir"] / "protected-control.json"
    logical_path = tile["logical_dir"] / "protected-control.json"
    dump_json(physical_path, document)
    return artifact(physical_path, logical_path=logical_path)


def _assemble_master_mask(
    sheet_tiles: Sequence[dict[str, Any]],
    *,
    spec_name: str,
    output_path: Path,
    size: tuple[int, int],
) -> None:
    master = Image.new("L", size, 0)
    coverage = Image.new("L", size, 0)
    try:
        for tile in sheet_tiles:
            source_box = tuple(tile["source_core_box_px"])
            destination = tile["destination_box_px"]
            with Image.open(tile["physical_dir"] / spec_name) as opened:
                source = opened.convert("L").crop(source_box)
            try:
                master.paste(source, (destination[0], destination[1]))
                coverage.paste(255, tuple(destination))
            finally:
                source.close()
        if coverage.getextrema() != (255, 255):
            raise Phase5ControlError(f"{output_path} master-mask coverage is incomplete")
        save_png(master, output_path)
    finally:
        master.close()
        coverage.close()


def _master_mask_spec(
    physical_path: Path,
    logical_path: Path,
    size: tuple[int, int],
) -> dict[str, Any]:
    return image_artifact(
        physical_path,
        logical_path=logical_path,
        expected_mode="L",
        expected_size=size,
    )


def _index_tile(tile: dict[str, Any]) -> dict[str, Any]:
    specs = tile["specs"]
    static_inputs = [
        {"role": "geometry-control", **artifact_only(specs["visual_geometry_control"])},
        {"role": "parent-context", **artifact_only(specs["parent_context"])},
    ]
    for direction in ("north", "west"):
        neighbor = tile["prior_neighbors"][direction]
        if neighbor is not None:
            static_inputs.append(
                {
                    "role": "continuation-reference",
                    **artifact_only(neighbor["geometry_context"]),
                }
            )
    return {
        "sheet_sequence": tile["sheet_sequence"],
        "column": tile["column"],
        "row": tile["row"],
        "canvas_origin_px": tile["canvas_origin_px"],
        "source_core_box_px": tile["source_core_box_px"],
        "destination_box_px": tile["destination_box_px"],
        "active_box_px": tile["active_box_px"],
        "world_bounds": tile["world_bounds"],
        "feature_ids": tile["feature_ids"],
        "visual_geometry_control": specs["visual_geometry_control"],
        "parent_context": specs["parent_context"],
        "protected_control": tile["protected_control"],
        "authoritative_controls": {
            "land_mask": specs["land_mask"],
            "water_mask": specs["water_mask"],
            "known_mask": specs["known_mask"],
            "unknown_mask": specs["unknown_mask"],
            "land_sea_overlay": specs["land_sea_overlay"],
            "transport_mask": specs["transport_mask"],
            "transport_overlay": specs["transport_overlay"],
            "detail_mask": specs["detail_mask"],
            "detail_overlay": specs["detail_overlay"],
            "partition": tile["partition"],
        },
        "receipt_bindings": {
            "control": artifact_only(specs["visual_geometry_control"]),
            "parent": artifact_only(specs["parent_context"]),
            "postprocess_control": tile["protected_control"],
            "static_inputs": static_inputs,
            "runtime_prior_neighbors": tile["prior_neighbors"],
            "future_seam_targets": tile["future_seam_targets"],
            "unbound_required_roles": [
                "golden-style",
                "prompt",
                "raw-output",
                "postprocess-report",
                "output",
            ],
        },
    }


def build_output(
    *,
    physical_output: Path,
    logical_output: Path,
    plan_inputs: dict[str, Any],
    index_schema_path: Path = DEFAULT_INDEX_SCHEMA,
    protected_schema_path: Path = DEFAULT_PROTECTED_SCHEMA,
) -> dict[str, Any]:
    physical_output.mkdir(parents=True, exist_ok=True)
    index_sheets: list[dict[str, Any]] = []
    total_tiles = 0
    total_prior_contexts = 0
    for sheet_id, sheet_contract in plan_inputs["sheet_contracts"].items():
        sheet = plan_inputs["catalog_by_id"][sheet_id]
        plan = build_metatile_plan(sheet_contract)
        sheet_tiles = [
            render_tile_assets(
                plan_inputs=plan_inputs,
                sheet=sheet,
                sheet_contract=sheet_contract,
                tile_plan=tile,
                physical_output=physical_output,
                logical_output=logical_output,
            )
            for tile in plan["tiles"]
        ]
        total_prior_contexts += bind_prior_contexts(
            sheet_tiles,
            columns=plan["columns"],
            rows=plan["rows"],
        )
        for tile in sheet_tiles:
            tile["protected_control"] = _write_protected_control(
                tile,
                sheet_id=sheet_id,
                source_inputs=plan_inputs["source_inputs"],
                schema_path=protected_schema_path,
            )

        physical_qa = physical_output / sheet_id / "qa"
        logical_qa = logical_output / sheet_id / "qa"
        physical_qa.mkdir(parents=True, exist_ok=False)
        size = (sheet_contract["width"], sheet_contract["height"])
        for source_name, output_name in (
            ("land-mask.png", "land-sea-control.png"),
            ("known-mask.png", "land-sea-known-mask.png"),
            ("transport-mask.png", "transport-control.png"),
        ):
            _assemble_master_mask(
                sheet_tiles,
                spec_name=source_name,
                output_path=physical_qa / output_name,
                size=size,
            )
        qa_controls = {
            "land_sea_control": _master_mask_spec(
                physical_qa / "land-sea-control.png",
                logical_qa / "land-sea-control.png",
                size,
            ),
            "land_sea_known_mask": _master_mask_spec(
                physical_qa / "land-sea-known-mask.png",
                logical_qa / "land-sea-known-mask.png",
                size,
            ),
            "transport_control": _master_mask_spec(
                physical_qa / "transport-control.png",
                logical_qa / "transport-control.png",
                size,
            ),
        }
        index_sheets.append(
            {
                "sheet_id": sheet_id,
                "sheet_type": sheet["sheet_type"],
                "source_feature_id": sheet.get("source_feature_id"),
                "parent_sheet_ids": _sheet_parent_ids(sheet),
                "bounds": sheet_contract["bounds"],
                "native_zoom": sheet_contract["native_zoom"],
                "master": {
                    "pixel_bounds": sheet_contract["pixel_bounds"],
                    "width": sheet_contract["width"],
                    "height": sheet_contract["height"],
                    "columns": plan["columns"],
                    "rows": plan["rows"],
                },
                "qa_controls": qa_controls,
                "tiles": [_index_tile(tile) for tile in sheet_tiles],
            }
        )
        total_tiles += len(sheet_tiles)

    if len(index_sheets) != 17 or total_tiles != 99 or total_prior_contexts != 120:
        raise Phase5ControlError(
            "generated control summary differs from 17 sheets / 99 tiles / "
            f"120 prior contexts: {len(index_sheets)}/{total_tiles}/{total_prior_contexts}"
        )
    index = {
        "$schema": INDEX_SCHEMA_URL,
        "schema_version": "1.0.0",
        "type": "sstory-phase5-metatile-control-index",
        "coordinate_reference_system": "EA-WORLD-1",
        "generated_by": GENERATOR_ID,
        "generation_order": "row-major",
        "inputs": plan_inputs["source_inputs"],
        "render_contract": {
            "metatile_size_px": 2048,
            "image_format": "PNG",
            "visual_color_mode": "RGB",
            "mask_color_mode": "L",
            "coordinate_quantization": "global-native-grid-round-half-up-v1",
            "unknown_policy": "raw-forbidden-parent-context-fallback",
            "detail_policy": "explicit-empty-until-reviewed-raster-detail",
            "receipt_control_binding": "visual-geometry-control",
            "postprocess_control_binding": "protected-control-json",
            "protected_layers": ["land-sea", "transport", "detail"],
        },
        "summary": {
            "sheet_count": 17,
            "metatile_count": 99,
            "protected_control_count": 99,
            "prior_neighbor_context_count": 120,
            "sheet_qa_control_count": 17,
        },
        "sheets": index_sheets,
    }
    validate_schema(index, index_schema_path, "Phase 5 metatile control index")
    dump_json(physical_output / "index.json", index)
    return index


def dry_run(
    *,
    contract_path: Path = DEFAULT_CONTRACT,
    catalog_path: Path = DEFAULT_CATALOG,
    source_files: dict[str, Path] = SOURCE_FILES,
) -> dict[str, int]:
    plan_inputs = load_plan_inputs(contract_path, catalog_path, source_files)
    sheet_count = 0
    tile_count = 0
    prior_count = 0
    for sheet_contract in plan_inputs["sheet_contracts"].values():
        plan = build_metatile_plan(sheet_contract)
        sheet_count += 1
        tile_count += plan["count"]
        prior_count += plan["rows"] * (plan["columns"] - 1)
        prior_count += plan["columns"] * (plan["rows"] - 1)
    if (sheet_count, tile_count, prior_count) != (17, 99, 120):
        raise Phase5ControlError(
            f"dry-run summary is stale: {sheet_count}/{tile_count}/{prior_count}"
        )
    return {
        "sheet_count": sheet_count,
        "metatile_count": tile_count,
        "prior_neighbor_context_count": prior_count,
    }


def _validated_output_dir(output_dir: Path) -> Path:
    resolved = output_dir.resolve()
    try:
        relative = resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise Phase5ControlError("output directory must remain inside the repository") from exc
    if not relative.parts:
        raise Phase5ControlError("output directory cannot be the repository root")
    return resolved


def generate_controls(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    contract_path: Path = DEFAULT_CONTRACT,
    catalog_path: Path = DEFAULT_CATALOG,
    source_files: dict[str, Path] = SOURCE_FILES,
    index_schema_path: Path = DEFAULT_INDEX_SCHEMA,
    protected_schema_path: Path = DEFAULT_PROTECTED_SCHEMA,
) -> dict[str, Any]:
    output = _validated_output_dir(output_dir)
    if output.exists():
        raise Phase5ControlError(f"refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.building-", dir=output.parent))
    try:
        plan_inputs = load_plan_inputs(contract_path, catalog_path, source_files)
        index = build_output(
            physical_output=stage,
            logical_output=output,
            plan_inputs=plan_inputs,
            index_schema_path=index_schema_path,
            protected_schema_path=protected_schema_path,
        )
        os.replace(stage, output)
        return index
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _first_difference(actual: Any, expected: Any, path: str = "<root>") -> str | None:
    if type(actual) is not type(expected):
        return f"{path} type differs"
    if isinstance(actual, dict):
        if list(actual) != list(expected):
            return f"{path} keys or key order differ"
        for key in actual:
            difference = _first_difference(actual[key], expected[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(actual, list):
        if len(actual) != len(expected):
            return f"{path} length differs"
        for index, (left, right) in enumerate(zip(actual, expected)):
            difference = _first_difference(left, right, f"{path}[{index}]")
            if difference:
                return difference
        return None
    if actual != expected:
        return f"{path} differs: actual={actual!r}, expected={expected!r}"
    return None


def verify_existing(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    contract_path: Path = DEFAULT_CONTRACT,
    catalog_path: Path = DEFAULT_CATALOG,
    source_files: dict[str, Path] = SOURCE_FILES,
    index_schema_path: Path = DEFAULT_INDEX_SCHEMA,
    protected_schema_path: Path = DEFAULT_PROTECTED_SCHEMA,
) -> dict[str, Any]:
    output = _validated_output_dir(output_dir)
    if not output.is_dir() or not (output / "index.json").is_file():
        raise Phase5ControlError(f"existing control output is incomplete: {output}")
    try:
        actual_index = load_json(output / "index.json")
    except ValidationFailure as exc:
        raise Phase5ControlError(str(exc)) from exc
    validate_schema(actual_index, index_schema_path, "existing control index")
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.verifying-", dir=output.parent)
    )
    expected_root = temporary / "expected"
    try:
        plan_inputs = load_plan_inputs(contract_path, catalog_path, source_files)
        expected_index = build_output(
            physical_output=expected_root,
            logical_output=output,
            plan_inputs=plan_inputs,
            index_schema_path=index_schema_path,
            protected_schema_path=protected_schema_path,
        )
        difference = _first_difference(actual_index, expected_index)
        if difference:
            raise Phase5ControlError(
                "control index is stale or contains a fabricated binding: " + difference
            )
        actual_files = {
            path.relative_to(output).as_posix(): path
            for path in output.rglob("*")
            if path.is_file()
        }
        expected_files = {
            path.relative_to(expected_root).as_posix(): path
            for path in expected_root.rglob("*")
            if path.is_file()
        }
        if set(actual_files) != set(expected_files):
            missing = sorted(set(expected_files) - set(actual_files))
            extra = sorted(set(actual_files) - set(expected_files))
            raise Phase5ControlError(
                f"control file set differs: missing={missing[:5]}, extra={extra[:5]}"
            )
        for relative, expected_path in expected_files.items():
            actual_sha = sha256_file(actual_files[relative])
            expected_sha = sha256_file(expected_path)
            if actual_sha != expected_sha:
                raise Phase5ControlError(
                    f"stale or fake control bytes at {relative}: "
                    f"actual={actual_sha}, expected={expected_sha}"
                )
        return actual_index
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--map-sheets", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--index-schema", type=Path, default=DEFAULT_INDEX_SCHEMA)
    parser.add_argument("--protected-schema", type=Path, default=DEFAULT_PROTECTED_SCHEMA)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--dry-run",
        action="store_true",
        help="validate all inputs and the complete 17-sheet/99-tile plan without writing",
    )
    modes.add_argument(
        "--verify-existing",
        action="store_true",
        help="regenerate into a temporary directory and byte-compare every control",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.dry_run:
            result = dry_run(contract_path=args.contract, catalog_path=args.map_sheets)
            print(
                "Phase 5 control dry-run passed: "
                f"{result['sheet_count']} sheets, {result['metatile_count']} metatiles, "
                f"{result['prior_neighbor_context_count']} prior contexts"
            )
        elif args.verify_existing:
            result = verify_existing(
                args.output_dir,
                contract_path=args.contract,
                catalog_path=args.map_sheets,
                index_schema_path=args.index_schema,
                protected_schema_path=args.protected_schema,
            )
            print(
                "Phase 5 controls verified byte-for-byte: "
                f"{result['summary']['sheet_count']} sheets, "
                f"{result['summary']['metatile_count']} metatiles"
            )
        else:
            result = generate_controls(
                args.output_dir,
                contract_path=args.contract,
                catalog_path=args.map_sheets,
                index_schema_path=args.index_schema,
                protected_schema_path=args.protected_schema,
            )
            print(
                f"Generated deterministic Phase 5 controls at {args.output_dir}: "
                f"{result['summary']['sheet_count']} sheets, "
                f"{result['summary']['metatile_count']} metatiles"
            )
    except Phase5ControlError as exc:
        print(f"Phase 5 control error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
