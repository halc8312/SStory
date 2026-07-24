#!/usr/bin/env python3
"""Render independent canonical control masks for the six Phase 5 parents.

The five continent sheets and ``sheet_world`` are deterministic composites, so
their QA controls must not be copied from the composite's observed masks.  This
helper rasterizes land/sea and transport controls directly from the canonical
EA-WORLD-1 GeoJSON on each parent's exact native grid.  It deliberately has no
input for the direct-generation metatile index, an observed mask, or a rendered
master.

The output root is atomically reserved and may not already exist.  ``index.json``
hash-locks every input and PNG; ``report.json`` in turn hash-locks the index and
records the closed-world dependency audit.  ``--verify-existing`` regenerates
the complete bundle, compares decoded control rasters, and separately verifies
the committed distribution bytes recorded by the index.
"""

from __future__ import annotations

import argparse
import copy
import contextlib
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import secrets
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from jsonschema import Draft7Validator
from PIL import Image, ImageDraw, ImageFilter, PngImagePlugin

from production_common import REPO_ROOT, ValidationFailure, load_json
from render_world_master import SOURCE_FILES
from validate_resolution_contract import validate_resolution_contract


GENERATOR_ID = "sstory-map-production/render_phase5_parent_control_masks.py@3"
SCHEMA_URL = "https://sstory.example/schemas/phase5-parent-control-index.schema.json"
REPORT_SCHEMA_URL = (
    "https://sstory.example/schemas/phase5-parent-control-report.schema.json"
)
DEFAULT_SOURCE_DIR = REPO_ROOT / "world" / "map-production" / "source"
DEFAULT_CONTRACT = (
    REPO_ROOT / "world" / "map-production" / "spec" / "resolution-contract.json"
)
DEFAULT_MAP_SHEETS = DEFAULT_SOURCE_DIR / "map-sheets.json"
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "world" / "map-production" / "controls" / "phase5-parents"
)
DEFAULT_INDEX_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-parent-control-index.schema.json"
)
DEFAULT_REPORT_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-parent-control-report.schema.json"
)
GENERATOR_PATH = Path(__file__).resolve()
PRODUCTION_COMMON_PATH = GENERATOR_PATH.with_name("production_common.py")
RENDER_WORLD_MASTER_PATH = GENERATOR_PATH.with_name("render_world_master.py")
RESOLUTION_VALIDATOR_PATH = GENERATOR_PATH.with_name("validate_resolution_contract.py")
PNG_OPTIONS = {"format": "PNG", "compress_level": 9, "optimize": False}
CONTROL_FILENAMES = {
    "land_sea_control": "land-sea-control.png",
    "transport_control": "transport-control.png",
}
EXPECTED_SOURCE_ROLES = tuple(SOURCE_FILES)
EXPECTED_EXECUTABLE_ROLES = (
    "generator",
    "production-common",
    "canonical-source-contract",
    "resolution-contract-validator",
)
EXPECTED_SCHEMA_ROLES = ("index-schema", "report-schema")
EXPECTED_RUNTIME_COMPATIBILITY = {
    "python_implementation": "CPython",
    "python_series": "3.12",
    "pillow_version": "12.3.0",
    "jsonschema_version": "4.26.0",
    "png_encoding_contract": "pillow-png-l-compress9-no-optimize-v1",
}
EXPECTED_CANONICAL_HASHES = {
    "resolution-contract": "f65984a6e162e6f60eb93873aa38e0daf1a263975f89cb063092c80389bb0290",
    "map-sheets": "20204c1bf14c8cb7b1204066c1b0755a0a74f62f9c7c6418b76754540a9a3c15",
    "landmasses": "d5e9600590bf2d122f33405c1f1924a8274a76f4bac1669f35f6adaaaa854b20",
    "regions": "233053f8ed4214016d8d4c841bceeb5192f5912dfd721325ad9657313752dbb4",
    "terrain": "fd186efd744c5dd31d5abe039d23e7fc2f04ff4e689233b48dc4bd9b397ab3aa",
    "hydrography": "33e23b5c85cc41f3ac6a65ced65284b81e04664ae373d85c1afb55dc67f8677d",
    "transport": "4beabac07fbfa6c67a4340f4a45a5199cb4c536e1b081ea5d5ba20a6c19c4565",
    "settlements": "48baf5f1a4857ef9500b6aab80468356869c5e8651196718a83a78a50cb89974",
}
EXPECTED_CONTROL_SHA256 = {
    (
        "sheet_world",
        "land_sea_control",
    ): "245e3da417a630f7ec30d5a6edc86c5810a4e8eb973e378cd7a4ab7cc631c418",
    (
        "sheet_world",
        "transport_control",
    ): "0b7c46d217e408ba36bd7fd3b8c33c0af8de73c719182e16ec24a44eac60b988",
    (
        "sheet_continent_elysion",
        "land_sea_control",
    ): "a4d1560a13de7a0b1de5373d19ea6d73174710dcdd191d0850722d343182fef3",
    (
        "sheet_continent_elysion",
        "transport_control",
    ): "c32fe1979f789614daef661ae5dcb0b37216e3f04fa4584962bb70e12b16a05e",
    (
        "sheet_continent_lumiera",
        "land_sea_control",
    ): "fccc3acc869f3c92a7e10dff4f0da216a9a5f435885841e63abb7d0b9a6d4439",
    (
        "sheet_continent_lumiera",
        "transport_control",
    ): "410b7deb74b53ca384dce3f6e36fd094b108a23baeb0d53ecfd697bcab44d178",
    (
        "sheet_continent_chaos_ria",
        "land_sea_control",
    ): "b47cb3e509afddfed6a5451757c73b238fa4f2294bc553ae182bea5da30b4632",
    (
        "sheet_continent_chaos_ria",
        "transport_control",
    ): "b68a0b0f9b760990548ae745ebbe9910096d2ca222e1bb65f115ba7b7d9a087c",
    (
        "sheet_continent_atlantis",
        "land_sea_control",
    ): "a727063970d3b7bfca448315382c9a3c8e47e78d8b2a8e48b23a51d834b3f2fb",
    (
        "sheet_continent_atlantis",
        "transport_control",
    ): "e6aa8d1c2cdf7120970ba2756c88872d9bd40d9c73195b169d7469e964c725cc",
    (
        "sheet_continent_grimoire",
        "land_sea_control",
    ): "de9f6370ce76eab1df2810506fe32b073f26b92b275447f4a9c044ccc4d47834",
    (
        "sheet_continent_grimoire",
        "transport_control",
    ): "95e59580297f241ebff01dfe37c6e5ea29b1baacad0876969e8556bdf6020358",
}
EXPECTED_CONTROL_RASTER_SHA256 = {
    (
        "sheet_world",
        "land_sea_control",
    ): "c1a249d60feb00db0a13aeb90179c4893286b859e98699f40a7df4f5a11daa62",
    (
        "sheet_world",
        "transport_control",
    ): "37d5958cbac96d9cfb5975511cc671202bb7819dd91620462cdd90a8c299bfd0",
    (
        "sheet_continent_elysion",
        "land_sea_control",
    ): "5a10b7931895fa29abc2d48ba98f5e9dedd00eb49c26bf4187566c723948ee00",
    (
        "sheet_continent_elysion",
        "transport_control",
    ): "3ef57491212135d7eedefb05108810825098287f3b664daf6f6bce91fe5c8e55",
    (
        "sheet_continent_lumiera",
        "land_sea_control",
    ): "66e732d7c4f2fa3086122bc124fd6a300a2eda08d5793fa18de73b2f6c05d651",
    (
        "sheet_continent_lumiera",
        "transport_control",
    ): "9ce4939badb1488e24bb985c79308fa1317a08b15c443fe62f4fe34077182fa7",
    (
        "sheet_continent_chaos_ria",
        "land_sea_control",
    ): "75abf94c7a3a18a206b0f5516d96168da907447282e40e51bbe4c560c7ebef6a",
    (
        "sheet_continent_chaos_ria",
        "transport_control",
    ): "6d09c303f8e8bab728c715e7c31c8c3b69f02f3eb8bb74b56bdaf5c87330a591",
    (
        "sheet_continent_atlantis",
        "land_sea_control",
    ): "8b9821c9639a91de93f5efca7b4842ff6e81747039120b6458a393c009aef581",
    (
        "sheet_continent_atlantis",
        "transport_control",
    ): "16bf11991e1f610cf5bdffe70b5caa3bf026a10826a96915f846867b3fc6af69",
    (
        "sheet_continent_grimoire",
        "land_sea_control",
    ): "04f21656a3a6766062be45d9df57e57b273ebe8c901a41d1447e8264e79fc3bd",
    (
        "sheet_continent_grimoire",
        "transport_control",
    ): "2956b74f585e5ffa6b9a1ce375fc0f9dfe0d111f3b1a956d8a4fae385ac38674",
}

# This is intentionally a versioned closed set, not a dynamic selection.  A
# geography/layout change must be reviewed and accompanied by a generator bump.
EXPECTED_PARENT_LAYOUT: tuple[dict[str, Any], ...] = (
    {
        "sheet_id": "sheet_world",
        "sheet_type": "world",
        "parent_id": None,
        "source_feature_id": None,
        "bounds": [0, 0, 10000, 10000],
        "zoom_range": [0, 3],
        "native_zoom": 3,
        "pixel_bounds": [0, 0, 4096, 2730],
        "width": 4096,
        "height": 2730,
    },
    {
        "sheet_id": "sheet_continent_elysion",
        "sheet_type": "continent",
        "parent_id": "sheet_world",
        "source_feature_id": "elysion",
        "bounds": [2800, 3000, 6300, 6550],
        "zoom_range": [3, 4],
        "native_zoom": 4,
        "pixel_bounds": [2293, 1638, 5161, 3577],
        "width": 2868,
        "height": 1939,
    },
    {
        "sheet_id": "sheet_continent_lumiera",
        "sheet_type": "continent",
        "parent_id": "sheet_world",
        "source_feature_id": "lumiera",
        "bounds": [6350, 2050, 9950, 7050],
        "zoom_range": [3, 4],
        "native_zoom": 4,
        "pixel_bounds": [5201, 1119, 8152, 3850],
        "width": 2951,
        "height": 2731,
    },
    {
        "sheet_id": "sheet_continent_chaos_ria",
        "sheet_type": "continent",
        "parent_id": "sheet_world",
        "source_feature_id": "chaos_ria",
        "bounds": [2950, 4800, 6600, 9650],
        "zoom_range": [3, 4],
        "native_zoom": 4,
        "pixel_bounds": [2416, 2620, 5407, 5269],
        "width": 2991,
        "height": 2649,
    },
    {
        "sheet_id": "sheet_continent_atlantis",
        "sheet_type": "continent",
        "parent_id": "sheet_world",
        "source_feature_id": "atlantis",
        "bounds": [50, 1700, 2950, 7300],
        "zoom_range": [3, 4],
        "native_zoom": 4,
        "pixel_bounds": [40, 928, 2417, 3986],
        "width": 2377,
        "height": 3058,
    },
    {
        "sheet_id": "sheet_continent_grimoire",
        "sheet_type": "continent",
        "parent_id": "sheet_world",
        "source_feature_id": "grimoire",
        "bounds": [3150, 750, 6150, 3000],
        "zoom_range": [3, 4],
        "native_zoom": 4,
        "pixel_bounds": [2580, 409, 5039, 1638],
        "width": 2459,
        "height": 1229,
    },
)
EXPECTED_PARENT_IDS = tuple(item["sheet_id"] for item in EXPECTED_PARENT_LAYOUT)
EXPECTED_WORLD_RASTER = {"width_px": 4096, "height_px": 2730, "native_zoom": 3}
EXPECTED_WORLD_EXTENT = {"min_x": 0, "min_y": 0, "max_x": 10000, "max_y": 10000}


class ParentControlError(ValueError):
    """Raised when a canonical input or generated parent control is unsafe."""


@dataclass(frozen=True)
class OutputReservation:
    root: Path
    marker: Path
    token: str
    root_identity: tuple[int, int]
    marker_identity: tuple[int, int]


@dataclass
class ReservationGuard:
    root_descriptor: int | None = None
    windows_root_handle: int | None = None
    windows_marker_handle: int | None = None
    marker_delete_committed: bool = False


EXPECTED_FEATURE_COUNTS = {
    "landmasses": 5,
    "regions": 14,
    "terrain": 11,
    "hydrography": 7,
    "transport": 33,
    "settlements": 22,
}
ALLOWED_GEOMETRY_TYPES = {
    "landmasses": {"Polygon", "MultiPolygon"},
    "regions": {"Polygon", "MultiPolygon"},
    "terrain": {"LineString", "MultiLineString", "Polygon", "MultiPolygon"},
    "hydrography": {"LineString", "MultiLineString", "Polygon", "MultiPolygon"},
    "transport": {"LineString", "MultiLineString"},
    "settlements": {"Polygon", "MultiPolygon"},
}


@dataclass(frozen=True)
class ParentNativeTransform:
    """Independent EA-WORLD-1 to parent-native pixel projection."""

    contract: Mapping[str, Any]
    sheet: Mapping[str, Any]

    def __post_init__(self) -> None:
        pixel_bounds = self.sheet.get("pixel_bounds")
        if not (
            isinstance(pixel_bounds, list)
            and len(pixel_bounds) == 4
            and all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in pixel_bounds
            )
        ):
            raise ParentControlError(
                "parent sheet pixel_bounds must contain four integers"
            )
        if self.width != self.sheet.get("width") or self.height != self.sheet.get(
            "height"
        ):
            raise ParentControlError(
                "parent sheet dimensions do not match pixel_bounds"
            )

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

    @property
    def native_scale(self) -> Fraction:
        world = self.contract["world_raster"]
        exponent = int(self.sheet["native_zoom"]) - int(world["native_zoom"])
        base = int(self.contract["pixel_bounds_formula"]["scale_base"])
        if exponent >= 0:
            return Fraction(base**exponent, 1)
        return Fraction(1, base**-exponent)

    def _pixels_per_world(self, axis: str) -> Fraction:
        extent = self.contract["world_extent"]
        world = self.contract["world_raster"]
        numerator = world["width_px"] if axis == "x" else world["height_px"]
        return (
            Fraction(int(numerator))
            * self.native_scale
            / (
                Fraction(str(extent[f"max_{axis}"]))
                - Fraction(str(extent[f"min_{axis}"]))
            )
        )

    @staticmethod
    def _round_half_up(value: Fraction) -> int:
        return math.floor(value + Fraction(1, 2))

    def _global_coordinate(self, value: float, axis: str) -> Fraction:
        minimum = Fraction(str(self.contract["world_extent"][f"min_{axis}"]))
        return (Fraction(str(value)) - minimum) * self._pixels_per_world(axis)

    def point(self, coordinate: Sequence[Any]) -> tuple[int, int]:
        x, y = _coordinate_pair(coordinate, "canonical geometry")
        left, top, _, _ = self.pixel_bounds
        return (
            self._round_half_up(self._global_coordinate(x, "x")) - left,
            self._round_half_up(self._global_coordinate(y, "y")) - top,
        )

    def nominal_width_px(self, world_width: Any) -> int:
        if (
            isinstance(world_width, bool)
            or not isinstance(world_width, (int, float))
            or not math.isfinite(float(world_width))
            or float(world_width) <= 0
        ):
            raise ParentControlError(
                f"canonical nominal_width is invalid: {world_width!r}"
            )
        mean = (
            Fraction(str(float(world_width)))
            * (self._pixels_per_world("x") + self._pixels_per_world("y"))
            / 2
        )
        return max(1, self._round_half_up(mean))


def _coordinate_pair(value: Any, label: str) -> tuple[float, float]:
    if not (
        isinstance(value, list)
        and len(value) >= 2
        and all(
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(float(item))
            for item in value[:2]
        )
    ):
        raise ParentControlError(f"{label} contains an invalid coordinate")
    x, y = float(value[0]), float(value[1])
    if not 0 <= x <= 10000 or not 0 <= y <= 10000:
        raise ParentControlError(f"{label} coordinate escapes EA-WORLD-1: {(x, y)}")
    return x, y


def _polygon_sets(geometry: Mapping[str, Any], label: str) -> Iterator[list[Any]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon":
        polygons = [coordinates]
    elif geometry_type == "MultiPolygon":
        polygons = coordinates
    else:
        raise ParentControlError(f"{label} is not a polygon geometry")
    if not isinstance(polygons, list) or not polygons:
        raise ParentControlError(f"{label} polygon coordinates are invalid")
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ParentControlError(f"{label} polygon is empty")
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                raise ParentControlError(f"{label} polygon ring is invalid")
            points = [_coordinate_pair(point, label) for point in ring]
            if points[0] != points[-1]:
                raise ParentControlError(f"{label} polygon ring is open")
        yield polygon


def _line_sets(geometry: Mapping[str, Any], label: str) -> Iterator[list[Any]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString":
        lines = [coordinates]
    elif geometry_type == "MultiLineString":
        lines = coordinates
    else:
        raise ParentControlError(f"{label} is not a line geometry")
    if not isinstance(lines, list) or not lines:
        raise ParentControlError(f"{label} line coordinates are invalid")
    for line in lines:
        if not isinstance(line, list) or len(line) < 2:
            raise ParentControlError(f"{label} line is invalid")
        for point in line:
            _coordinate_pair(point, label)
        yield line


def _feature_id(feature: Mapping[str, Any], label: str) -> str:
    properties = feature.get("properties")
    value = feature.get("id")
    if value is None and isinstance(properties, Mapping):
        value = properties.get("id")
    if not isinstance(value, str) or not value:
        raise ParentControlError(f"{label} lacks a non-empty feature ID")
    return value


def _validate_feature_geometry(
    feature: Mapping[str, Any], role: str, label: str
) -> None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, Mapping):
        raise ParentControlError(f"{label} lacks a geometry object")
    geometry_type = geometry.get("type")
    if geometry_type not in ALLOWED_GEOMETRY_TYPES[role]:
        raise ParentControlError(
            f"{label} geometry type is unexpected for {role}: {geometry_type!r}"
        )
    if geometry_type in {"Polygon", "MultiPolygon"}:
        list(_polygon_sets(geometry, label))
    else:
        list(_line_sets(geometry, label))


def load_canonical_sources(source_dir: Path) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    for role, filename in SOURCE_FILES.items():
        path = (source_dir / filename).resolve()
        document = _json_object(path, f"canonical source {role}")
        if document.get("type") != "FeatureCollection":
            raise ParentControlError(f"{path} must be a GeoJSON FeatureCollection")
        if document.get("coordinate_reference_system") != "EA-WORLD-1":
            raise ParentControlError(f"{path} must declare EA-WORLD-1")
        features = document.get("features")
        if not isinstance(features, list):
            raise ParentControlError(f"{path}.features must be an array")
        if len(features) != EXPECTED_FEATURE_COUNTS[role]:
            raise ParentControlError(
                f"{path} feature count is unexpected: "
                f"expected={EXPECTED_FEATURE_COUNTS[role]}, actual={len(features)}"
            )
        seen: set[str] = set()
        for position, feature in enumerate(features):
            label = f"{path}.features[{position}]"
            if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
                raise ParentControlError(f"{label} must be a GeoJSON Feature")
            feature_id = _feature_id(feature, label)
            if feature_id in seen:
                raise ParentControlError(f"{path} duplicates feature ID {feature_id!r}")
            seen.add(feature_id)
            properties = feature.get("properties")
            if not isinstance(properties, Mapping):
                raise ParentControlError(f"{label}.properties must be an object")
            _validate_feature_geometry(feature, role, label)
        sources[role] = document
    if tuple(sources) != EXPECTED_SOURCE_ROLES:
        raise ParentControlError("canonical source role set/order is unexpected")
    return sources


def _draw_polygon_class(
    draw: ImageDraw.ImageDraw,
    feature: Mapping[str, Any],
    transform: ParentNativeTransform,
    *,
    fill: int,
    label: str,
) -> None:
    geometry = feature["geometry"]
    assert isinstance(geometry, Mapping)
    for polygon in _polygon_sets(geometry, label):
        if len(polygon) != 1:
            raise ParentControlError(
                f"{label} polygon holes require an explicit underlying class"
            )
        exterior = [transform.point(point) for point in polygon[0]]
        draw.polygon(exterior, fill=fill)


def _draw_feature_lines(
    draw: ImageDraw.ImageDraw,
    feature: Mapping[str, Any],
    transform: ParentNativeTransform,
    *,
    fill: int,
    width: int,
    label: str,
) -> None:
    geometry = feature["geometry"]
    assert isinstance(geometry, Mapping)
    for line in _line_sets(geometry, label):
        draw.line(
            [transform.point(point) for point in line],
            fill=fill,
            width=width,
            joint="curve",
        )


def render_land_sea_control(
    sources: Mapping[str, dict[str, Any]], transform: ParentNativeTransform
) -> Image.Image:
    """Rasterize canonical classification without calling the observed renderer."""

    classification = Image.new("L", (transform.width, transform.height), 0)
    draw = ImageDraw.Draw(classification)
    for feature in sources["landmasses"]["features"]:
        _draw_polygon_class(
            draw,
            feature,
            transform,
            fill=1,
            label=f"landmasses/{_feature_id(feature, 'landmass')}",
        )
    for feature in sources["hydrography"]["features"]:
        label = f"hydrography/{_feature_id(feature, 'hydrography')}"
        geometry = feature["geometry"]
        if geometry["type"] in {"Polygon", "MultiPolygon"}:
            _draw_polygon_class(draw, feature, transform, fill=2, label=label)
        else:
            _draw_feature_lines(
                draw,
                feature,
                transform,
                fill=2,
                width=transform.nominal_width_px(
                    feature["properties"].get("nominal_width", 1)
                ),
                label=label,
            )
    for feature in sources["regions"]["features"]:
        if feature["properties"].get("region_type") == "underwater_region":
            _draw_polygon_class(
                draw,
                feature,
                transform,
                fill=2,
                label=f"regions/{_feature_id(feature, 'region')}",
            )
    for feature in sources["terrain"]["features"]:
        if feature["properties"].get("terrain_type") == "floating_island_chain":
            _draw_polygon_class(
                draw,
                feature,
                transform,
                fill=1,
                label=f"terrain/{_feature_id(feature, 'terrain')}",
            )
    land = classification.point(lambda value: 255 if value == 1 else 0, mode="L")
    classification.close()
    # A one-pixel conservative interior is deliberately independent from the
    # observed renderer's edge-inclusive polygon fill.  It stays within the
    # canonical land class while ensuring a re-encoded control can never pose
    # as independently observed evidence.
    conservative = land.filter(ImageFilter.MinFilter(3))
    land.close()
    return conservative


def render_transport_control(
    sources: Mapping[str, dict[str, Any]], transform: ParentNativeTransform
) -> Image.Image:
    """Rasterize canonical routes through an independent line walker."""

    mask = Image.new("L", (transform.width, transform.height), 0)
    draw = ImageDraw.Draw(mask)
    # The control is the canonical centerline, while the observed renderer
    # paints a wider route corridor.  QA's locked spatial tolerance compares
    # them without making the decoded control and observation interchangeable.
    width = 1
    for feature in sources["transport"]["features"]:
        _draw_feature_lines(
            draw,
            feature,
            transform,
            fill=255,
            width=width,
            label=f"transport/{_feature_id(feature, 'transport')}",
        )
    return mask


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def raster_semantic_sha256(image: Image.Image) -> str:
    """Hash mode, dimensions, and decoded pixels without PNG container bytes."""

    digest = hashlib.sha256()
    digest.update(b"sstory-raster-semantic-v1\0")
    digest.update(image.mode.encode("ascii"))
    digest.update(b"\0")
    digest.update(image.width.to_bytes(8, "big"))
    digest.update(image.height.to_bytes(8, "big"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def raster_semantic_sha256_file(path: Path) -> str:
    try:
        with Image.open(path) as opened:
            opened.load()
            return raster_semantic_sha256(opened)
    except (OSError, ValueError) as exc:
        raise ParentControlError(f"cannot decode control raster {path}: {exc}") from exc


def _json_lf_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _dump_json_lf(path: Path, value: Any) -> None:
    """Write canonical JSON bytes with LF newlines on every supported host."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_lf_bytes(value)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ParentControlError(
            f"refusing to overwrite generated JSON: {path}"
        ) from exc


def _repo_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise ParentControlError(f"path escapes the repository: {path}") from exc
    if not relative.parts:
        raise ParentControlError("an artifact path cannot be the repository root")
    return relative.as_posix()


def _file_identity(info: os.stat_result) -> tuple[int, int]:
    return int(info.st_dev), int(info.st_ino)


def _stat_is_reparse(info: os.stat_result) -> bool:
    windows_attributes = int(getattr(info, "st_file_attributes", 0))
    return stat.S_ISLNK(info.st_mode) or bool(windows_attributes & 0x400)


def _assert_no_reparse_components(path: Path, label: str) -> None:
    lexical = Path(os.path.abspath(os.fspath(path)))
    chain: list[Path] = []
    current = lexical
    while True:
        chain.append(current)
        if current.parent == current:
            break
        current = current.parent
    for component in reversed(chain):
        if not os.path.lexists(component):
            continue
        try:
            info = os.lstat(component)
        except OSError as exc:
            raise ParentControlError(
                f"cannot inspect {label} component {component}: {exc}"
            ) from exc
        if _stat_is_reparse(info):
            raise ParentControlError(
                f"{label} may not traverse a symlink or reparse point: {component}"
            )


def _artifact(physical_path: Path, logical_path: Path | None = None) -> dict[str, str]:
    if not physical_path.is_file():
        raise ParentControlError(f"artifact does not exist: {physical_path}")
    return {
        "path": _repo_path(logical_path or physical_path),
        "sha256": sha256_file(physical_path),
    }


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = load_json(path)
    except ValidationFailure as exc:
        raise ParentControlError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ParentControlError(f"{label} must contain a JSON object")
    return value


def _validate_schema(document: Any, schema_path: Path, label: str) -> None:
    schema = _json_object(
        _validated_repo_file(schema_path, f"{label} schema"),
        f"{label} schema",
    )
    errors = sorted(
        Draft7Validator(schema).iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        rendered = []
        for error in errors[:20]:
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            rendered.append(f"{location}: {error.message}")
        raise ParentControlError(f"{label} is invalid: " + "; ".join(rendered))


def _validated_repo_file(path: Path, label: str) -> Path:
    _assert_no_reparse_components(path, label)
    resolved = path.resolve()
    _repo_path(resolved)
    if not resolved.is_file():
        raise ParentControlError(f"{label} does not exist: {resolved}")
    return resolved


def _require_canonical_artifact(
    path: Path,
    *,
    expected_path: Path,
    expected_sha256: str,
    label: str,
) -> Path:
    resolved = _validated_repo_file(path, label)
    if resolved != expected_path.resolve():
        raise ParentControlError(
            f"{label} must use the canonical repository path: {expected_path.resolve()}"
        )
    actual = sha256_file(resolved)
    if actual != expected_sha256:
        raise ParentControlError(
            f"{label} canonical sha256 mismatch: "
            f"expected={expected_sha256}, actual={actual}"
        )
    return resolved


def _validated_source_dir(path: Path) -> Path:
    _assert_no_reparse_components(path, "canonical source directory")
    resolved = path.resolve()
    _repo_path(resolved)
    if resolved != DEFAULT_SOURCE_DIR.resolve():
        raise ParentControlError(
            f"canonical source directory must use {DEFAULT_SOURCE_DIR.resolve()}"
        )
    if not resolved.is_dir():
        raise ParentControlError(
            f"canonical source directory does not exist: {resolved}"
        )
    for filename in SOURCE_FILES.values():
        candidate = (resolved / filename).resolve()
        try:
            candidate.relative_to(resolved)
        except ValueError as exc:  # pragma: no cover - fixed filenames are defensive
            raise ParentControlError(
                f"canonical source path escapes source root: {filename}"
            ) from exc
        if not candidate.is_file():
            raise ParentControlError(
                f"required canonical source does not exist: {candidate}"
            )
    for role, filename in SOURCE_FILES.items():
        candidate = (resolved / filename).resolve()
        actual = sha256_file(candidate)
        expected = EXPECTED_CANONICAL_HASHES[role]
        if actual != expected:
            raise ParentControlError(
                f"canonical source {role} sha256 mismatch: "
                f"expected={expected}, actual={actual}"
            )
    return resolved


def _validated_output_root(path: Path, *, must_exist: bool = False) -> Path:
    _assert_no_reparse_components(path, "output root")
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise ParentControlError(
            "output root must remain inside the repository"
        ) from exc
    if not relative.parts:
        raise ParentControlError("output root cannot be the repository root")
    if relative.parts[0].lower() == ".git":
        raise ParentControlError("output root cannot be inside .git")
    if must_exist:
        if not resolved.is_dir():
            raise ParentControlError(f"existing output root is missing: {resolved}")
    elif resolved.exists():
        raise ParentControlError(f"refusing to overwrite existing output: {resolved}")
    return resolved


def _reserve_output_root(output: Path) -> OutputReservation:
    """Acquire the exact final directory and a random, identity-bound marker."""

    _assert_no_reparse_components(output.parent, "output parent")
    created_root = False
    marker: Path | None = None
    marker_acquired = False
    root_identity: tuple[int, int] | None = None
    marker_identity: tuple[int, int] | None = None
    try:
        try:
            output.mkdir(parents=False, exist_ok=False)
        except FileExistsError as exc:
            raise ParentControlError(
                f"output reservation lost; refusing raced path rather than overwriting: {output}"
            ) from exc
        created_root = True
        root_info = os.lstat(output)
        if not stat.S_ISDIR(root_info.st_mode) or _stat_is_reparse(root_info):
            raise ParentControlError("reserved output root is not a plain directory")
        root_identity = _file_identity(root_info)
        token = secrets.token_hex(32)
        marker = output / ".phase5-parent-control-reservation"
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(marker, flags, 0o600)
        marker_acquired = True
        try:
            marker_info = os.fstat(descriptor)
            marker_identity = _file_identity(marker_info)
            payload = f"{GENERATOR_ID}\n{token}\n".encode("ascii")
            if os.write(descriptor, payload) != len(payload):
                raise ParentControlError("reservation marker write was incomplete")
            os.fsync(descriptor)
            marker_info = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if not stat.S_ISREG(marker_info.st_mode) or _stat_is_reparse(marker_info):
            raise ParentControlError("reservation marker is not a plain file")
        return OutputReservation(
            root=output,
            marker=marker,
            token=token,
            root_identity=root_identity,
            marker_identity=marker_identity,
        )
    except BaseException:
        # Cleanup is limited to objects acquired by this call.  Identity and
        # emptiness checks prevent deleting a path swapped in by another actor.
        if (
            marker is not None
            and marker_acquired
            and marker_identity is not None
            and root_identity is not None
        ):
            try:
                current_root = os.lstat(output)
                current_marker = os.lstat(marker)
                if (
                    _file_identity(current_root) == root_identity
                    and not _stat_is_reparse(current_root)
                    and stat.S_ISDIR(current_root.st_mode)
                    and stat.S_ISREG(current_marker.st_mode)
                    and not _stat_is_reparse(current_marker)
                    and _file_identity(current_marker) == marker_identity
                    and list(output.iterdir()) == [marker]
                ):
                    marker.unlink()
            except OSError:
                pass
        if created_root and root_identity is not None:
            try:
                current_root = os.lstat(output)
                if (
                    _file_identity(current_root) == root_identity
                    and stat.S_ISDIR(current_root.st_mode)
                    and not _stat_is_reparse(current_root)
                    and not any(output.iterdir())
                ):
                    output.rmdir()
            except OSError:
                pass
        raise


def _validate_reservation(
    reservation: OutputReservation,
    *,
    installed_names: set[str] | None = None,
) -> None:
    installed_names = installed_names or set()
    _assert_no_reparse_components(reservation.root, "reserved output root")
    try:
        root_info = os.lstat(reservation.root)
        marker_info = os.lstat(reservation.marker)
    except OSError as exc:
        raise ParentControlError(f"output reservation disappeared: {exc}") from exc
    if (
        _file_identity(root_info) != reservation.root_identity
        or not stat.S_ISDIR(root_info.st_mode)
        or _stat_is_reparse(root_info)
    ):
        raise ParentControlError("reserved output root identity changed")
    if (
        _file_identity(marker_info) != reservation.marker_identity
        or not stat.S_ISREG(marker_info.st_mode)
        or _stat_is_reparse(marker_info)
    ):
        raise ParentControlError("reservation marker identity changed")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(reservation.marker, flags)
    try:
        payload = os.read(descriptor, 4096).decode("ascii")
        opened_identity = _file_identity(os.fstat(descriptor))
    except (OSError, UnicodeDecodeError) as exc:
        raise ParentControlError(f"cannot verify reservation marker: {exc}") from exc
    finally:
        os.close(descriptor)
    if opened_identity != reservation.marker_identity:
        raise ParentControlError("reservation marker was swapped while opening")
    expected_payload = f"{GENERATOR_ID}\n{reservation.token}\n"
    if payload != expected_payload:
        raise ParentControlError("reservation token does not match the acquisition")
    actual_names = {path.name for path in reservation.root.iterdir()}
    expected_names = {reservation.marker.name, *installed_names}
    if actual_names != expected_names:
        raise ParentControlError(
            "reserved output contents changed during installation: "
            f"expected={sorted(expected_names)!r}, actual={sorted(actual_names)!r}"
        )


def _windows_open_reservation_handle(
    path: Path, *, directory: bool, delete_access: bool
) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    generic_read = 0x80000000
    delete = 0x00010000
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    open_existing = 3
    open_reparse_point = 0x00200000
    backup_semantics = 0x02000000
    desired_access = generic_read | (delete if delete_access else 0)
    share_mode = file_share_read | (file_share_write if directory else 0)
    flags = open_reparse_point | (backup_semantics if directory else 0)
    handle = create_file(
        str(path),
        desired_access,
        share_mode,
        None,
        open_existing,
        flags,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise OSError(ctypes.get_last_error(), f"cannot lock reservation path {path}")
    return int(handle)


def _windows_close_handle(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    if not close_handle(wintypes.HANDLE(handle)):
        raise OSError(ctypes.get_last_error(), "cannot close reservation handle")


def _windows_commit_marker_delete(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    class FileDispositionInfo(ctypes.Structure):
        _fields_ = (("delete_file", wintypes.BOOL),)

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    set_information.restype = wintypes.BOOL
    disposition = FileDispositionInfo(True)
    if not set_information(
        wintypes.HANDLE(handle),
        4,  # FileDispositionInfo
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        raise OSError(
            ctypes.get_last_error(), "cannot atomically commit reservation marker"
        )


def _windows_read_handle(handle: int, limit: int = 4096) -> str:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    read_file = kernel32.ReadFile
    read_file.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    read_file.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(limit)
    count = wintypes.DWORD()
    if not read_file(wintypes.HANDLE(handle), buffer, limit, ctypes.byref(count), None):
        raise OSError(ctypes.get_last_error(), "cannot read reservation marker handle")
    try:
        return buffer.raw[: count.value].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ParentControlError("reservation marker is not ASCII") from exc


def _restore_posix_reservation_marker(
    reservation: OutputReservation, guard: ReservationGuard
) -> None:
    """Restore the invalid-output marker through the identity-bound directory fd."""

    if guard.root_descriptor is None:  # pragma: no cover - caller is POSIX-only
        raise ParentControlError(
            "cannot restore marker without a reserved root descriptor"
        )
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(
        reservation.marker.name,
        flags,
        0o600,
        dir_fd=guard.root_descriptor,
    )
    try:
        payload = f"{GENERATOR_ID}\n{reservation.token}\n".encode("ascii")
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise ParentControlError(
                    "restored reservation marker write was incomplete"
                )
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _reservation_root_is_current(reservation: OutputReservation) -> bool:
    try:
        root_info = os.lstat(reservation.root)
    except OSError:
        return False
    return (
        _file_identity(root_info) == reservation.root_identity
        and stat.S_ISDIR(root_info.st_mode)
        and not _stat_is_reparse(root_info)
    )


@contextlib.contextmanager
def _locked_reservation(
    reservation: OutputReservation,
) -> Iterator[ReservationGuard]:
    """Hold identity-bound handles so the reserved root cannot be swapped."""

    _validate_reservation(reservation)
    guard = ReservationGuard()
    try:
        if os.name == "nt":
            guard.windows_root_handle = _windows_open_reservation_handle(
                reservation.root, directory=True, delete_access=False
            )
            guard.windows_marker_handle = _windows_open_reservation_handle(
                reservation.marker, directory=False, delete_access=False
            )
        else:
            flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                flags |= os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            guard.root_descriptor = os.open(reservation.root, flags)
            if (
                _file_identity(os.fstat(guard.root_descriptor))
                != reservation.root_identity
            ):
                raise ParentControlError("reserved output root changed while locking")
        _validate_reservation(reservation)
        yield guard
    finally:
        close_errors: list[OSError] = []
        if guard.windows_marker_handle is not None:
            try:
                _windows_close_handle(guard.windows_marker_handle)
            except OSError as exc:
                close_errors.append(exc)
        if guard.windows_root_handle is not None:
            try:
                _windows_close_handle(guard.windows_root_handle)
            except OSError as exc:
                close_errors.append(exc)
        if guard.root_descriptor is not None:
            try:
                os.close(guard.root_descriptor)
            except OSError as exc:
                close_errors.append(exc)
        if (
            close_errors
            and not guard.marker_delete_committed
            and sys.exc_info()[0] is None
        ):
            raise ParentControlError(
                f"cannot release reservation guard: {close_errors[0]}"
            )


def _move_into_reservation(
    source: Path,
    name: str,
    reservation: OutputReservation,
    guard: ReservationGuard,
) -> None:
    if guard.root_descriptor is not None:
        os.rename(source, name, dst_dir_fd=guard.root_descriptor)
    else:
        os.rename(source, reservation.root / name)


def _commit_reservation(
    reservation: OutputReservation,
    guard: ReservationGuard,
) -> None:
    if guard.windows_marker_handle is not None:
        _windows_close_handle(guard.windows_marker_handle)
        guard.windows_marker_handle = None
        guard.windows_marker_handle = _windows_open_reservation_handle(
            reservation.marker, directory=False, delete_access=True
        )
        marker_info = os.lstat(reservation.marker)
        if (
            _file_identity(marker_info) != reservation.marker_identity
            or _stat_is_reparse(marker_info)
            or not stat.S_ISREG(marker_info.st_mode)
        ):
            raise ParentControlError("reservation marker changed at commit")
        expected_payload = f"{GENERATOR_ID}\n{reservation.token}\n"
        if _windows_read_handle(guard.windows_marker_handle) != expected_payload:
            raise ParentControlError("reservation token changed at commit")
        _windows_commit_marker_delete(guard.windows_marker_handle)
        _windows_close_handle(guard.windows_marker_handle)
        guard.windows_marker_handle = None
        if os.path.lexists(reservation.marker):
            raise ParentControlError("reservation marker remained after commit")
        guard.marker_delete_committed = True
    elif guard.root_descriptor is not None:
        os.unlink(reservation.marker.name, dir_fd=guard.root_descriptor)
        if not _reservation_root_is_current(reservation):
            try:
                _restore_posix_reservation_marker(reservation, guard)
            except (OSError, ParentControlError) as exc:
                raise ParentControlError(
                    "reserved output root changed during POSIX commit and its "
                    f"marker could not be restored: {exc}"
                ) from exc
            raise ParentControlError(
                "reserved output root changed during POSIX commit; restored the "
                "incomplete-output marker"
            )
        guard.marker_delete_committed = True
    else:  # pragma: no cover - every supported platform selects a guarded path
        raise ParentControlError("reservation guard does not support marker commit")


def _install_reserved_output(stage: Path, reservation: OutputReservation) -> None:
    installed: set[str] = set()
    with _locked_reservation(reservation) as guard:
        _validate_reservation(reservation, installed_names=installed)
        sources = {path.name: path for path in stage.iterdir()}
        ordered_names = sorted(
            name for name in sources if name not in {"index.json", "report.json"}
        ) + ["index.json", "report.json"]
        if set(ordered_names) != set(sources):
            raise ParentControlError("staged output lacks index.json or report.json")
        for name in ordered_names:
            _validate_reservation(reservation, installed_names=installed)
            source = sources[name]
            destination = reservation.root / name
            if os.path.lexists(destination):
                raise ParentControlError(
                    f"refusing to overwrite raced output entry: {destination}"
                )
            _move_into_reservation(source, name, reservation, guard)
            installed.add(name)
        stage.rmdir()
        _validate_reservation(reservation, installed_names=installed)
        if _file_identity(os.lstat(reservation.root)) != reservation.root_identity:
            raise ParentControlError("installed output root identity changed at commit")
        _load_bundle_documents(
            reservation.root,
            allow_reservation_marker=True,
        )
        _validate_reservation(reservation, installed_names=installed)
        _commit_reservation(reservation, guard)


def _validate_contract_anchor(contract: Mapping[str, Any]) -> None:
    if contract.get("coordinate_reference_system") != "EA-WORLD-1":
        raise ParentControlError("resolution contract CRS must be EA-WORLD-1")
    if contract.get("world_extent") != EXPECTED_WORLD_EXTENT:
        raise ParentControlError("resolution contract world extent is unexpected")
    if contract.get("world_raster") != EXPECTED_WORLD_RASTER:
        raise ParentControlError(
            "resolution contract world raster dimensions are unexpected"
        )
    lod = contract.get("lod_by_sheet_type")
    if not isinstance(lod, dict):
        raise ParentControlError("resolution contract lacks LOD definitions")
    for sheet_type, zoom_range, native_zoom in (
        ("world", [0, 3], 3),
        ("continent", [3, 4], 4),
    ):
        expected = {
            "zoom_range": zoom_range,
            "native_zoom": native_zoom,
            "production_method": "deterministic-composite",
        }
        if lod.get(sheet_type) != expected:
            raise ParentControlError(
                f"resolution contract {sheet_type} LOD is unexpected"
            )


def _catalog_by_id(catalog: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if catalog.get("coordinate_reference_system") != "EA-WORLD-1":
        raise ParentControlError("map-sheets CRS must be EA-WORLD-1")
    sheets = catalog.get("sheets")
    if not isinstance(sheets, list):
        raise ParentControlError("map-sheets.sheets must be an array")
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(sheets):
        if not isinstance(value, dict) or not isinstance(value.get("id"), str):
            raise ParentControlError(f"map-sheets.sheets[{index}] is invalid")
        sheet_id = value["id"]
        if sheet_id in result:
            raise ParentControlError(
                f"map-sheets contains duplicate sheet ID {sheet_id!r}"
            )
        result[sheet_id] = value
    actual_parent_ids = tuple(
        value["id"]
        for value in sheets
        if value.get("sheet_type") in {"world", "continent"}
    )
    if actual_parent_ids != EXPECTED_PARENT_IDS:
        raise ParentControlError(
            "parent sheet IDs/order are unexpected: "
            f"expected={list(EXPECTED_PARENT_IDS)!r}, actual={list(actual_parent_ids)!r}"
        )
    return result


def _validate_parent_layout(
    catalog_by_id: Mapping[str, Mapping[str, Any]],
    derived_sheets: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    derived_by_id = {str(value.get("sheet_id")): value for value in derived_sheets}
    actual_derived_ids = tuple(
        str(value.get("sheet_id"))
        for value in derived_sheets
        if value.get("sheet_type") in {"world", "continent"}
    )
    if actual_derived_ids != EXPECTED_PARENT_IDS:
        raise ParentControlError(
            "derived parent sheet IDs/order are unexpected: "
            f"expected={list(EXPECTED_PARENT_IDS)!r}, actual={list(actual_derived_ids)!r}"
        )

    result: list[dict[str, Any]] = []
    for expected in EXPECTED_PARENT_LAYOUT:
        sheet_id = expected["sheet_id"]
        catalog = catalog_by_id.get(sheet_id)
        derived = derived_by_id.get(sheet_id)
        if not isinstance(catalog, Mapping) or not isinstance(derived, Mapping):
            raise ParentControlError(f"required parent sheet is missing: {sheet_id}")
        for key in (
            "sheet_type",
            "parent_id",
            "source_feature_id",
            "bounds",
            "zoom_range",
            "native_zoom",
        ):
            if catalog.get(key) != expected[key]:
                raise ParentControlError(
                    f"{sheet_id} catalog {key} is unexpected: "
                    f"expected={expected[key]!r}, actual={catalog.get(key)!r}"
                )
        if catalog.get("secondary_parent_ids") not in (None, []):
            raise ParentControlError(
                f"{sheet_id} must not have secondary parent sheets"
            )
        for key in (
            "sheet_type",
            "bounds",
            "native_zoom",
            "pixel_bounds",
            "width",
            "height",
        ):
            if derived.get(key) != expected[key]:
                raise ParentControlError(
                    f"{sheet_id} derived {key} is unexpected: "
                    f"expected={expected[key]!r}, actual={derived.get(key)!r}"
                )
        if derived.get("production_method") != "deterministic-composite":
            raise ParentControlError(
                f"{sheet_id} must use deterministic-composite production"
            )
        result.append(
            {
                **dict(derived),
                "sheet_id": sheet_id,
                "sheet_type": expected["sheet_type"],
                "parent_id": expected["parent_id"],
                "source_feature_id": expected["source_feature_id"],
            }
        )
    return result


def _runtime_compatibility() -> dict[str, str]:
    actual_versions = {
        "python_implementation": platform.python_implementation(),
        "python_series": f"{sys.version_info.major}.{sys.version_info.minor}",
        "pillow_version": importlib.metadata.version("Pillow"),
        "jsonschema_version": importlib.metadata.version("jsonschema"),
    }
    expected_versions = {
        key: value
        for key, value in EXPECTED_RUNTIME_COMPATIBILITY.items()
        if key != "png_encoding_contract"
    }
    if actual_versions != expected_versions:
        raise ParentControlError(
            "runtime compatibility mismatch: "
            f"expected={expected_versions!r}, actual={actual_versions!r}"
        )
    if PNG_OPTIONS != {"format": "PNG", "compress_level": 9, "optimize": False}:
        raise ParentControlError(
            "PNG encoding options differ from the reviewed contract"
        )
    return dict(EXPECTED_RUNTIME_COMPATIBILITY)


def load_parent_inputs(
    *,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    contract_path: Path = DEFAULT_CONTRACT,
    map_sheets_path: Path = DEFAULT_MAP_SHEETS,
) -> dict[str, Any]:
    source_dir = _validated_source_dir(source_dir)
    contract_path = _require_canonical_artifact(
        contract_path,
        expected_path=DEFAULT_CONTRACT,
        expected_sha256=EXPECTED_CANONICAL_HASHES["resolution-contract"],
        label="resolution contract",
    )
    map_sheets_path = _require_canonical_artifact(
        map_sheets_path,
        expected_path=DEFAULT_MAP_SHEETS,
        expected_sha256=EXPECTED_CANONICAL_HASHES["map-sheets"],
        label="map-sheets catalog",
    )
    contract = _json_object(contract_path, "resolution contract")
    catalog = _json_object(map_sheets_path, "map-sheets catalog")
    _validate_contract_anchor(contract)
    catalog_by_id = _catalog_by_id(catalog)

    validation = validate_resolution_contract(
        contract_path=contract_path,
        map_sheets_path=map_sheets_path,
        check_catalog=True,
    )
    if not validation["valid"]:
        raise ParentControlError(
            "resolution/catalog contract is invalid: " + "; ".join(validation["errors"])
        )
    parent_sheets = _validate_parent_layout(catalog_by_id, validation["sheets"])
    sources = load_canonical_sources(source_dir)

    landmass_ids = {
        str(feature.get("id") or feature.get("properties", {}).get("id"))
        for feature in sources["landmasses"]["features"]
    }
    expected_landmass_ids = {
        str(item["source_feature_id"])
        for item in EXPECTED_PARENT_LAYOUT
        if item["source_feature_id"] is not None
    }
    if landmass_ids != expected_landmass_ids:
        raise ParentControlError(
            "canonical landmass IDs are unexpected: "
            f"expected={sorted(expected_landmass_ids)!r}, actual={sorted(landmass_ids)!r}"
        )

    source_artifacts = []
    for role, filename in SOURCE_FILES.items():
        path = (source_dir / filename).resolve()
        source_artifacts.append({"role": role, **_artifact(path)})
    executable_inputs = [
        {"role": "generator", **_artifact(GENERATOR_PATH)},
        {"role": "production-common", **_artifact(PRODUCTION_COMMON_PATH)},
        {
            "role": "canonical-source-contract",
            **_artifact(RENDER_WORLD_MASTER_PATH),
        },
        {
            "role": "resolution-contract-validator",
            **_artifact(RESOLUTION_VALIDATOR_PATH),
        },
    ]
    validation_schemas = [
        {"role": "index-schema", **_artifact(DEFAULT_INDEX_SCHEMA)},
        {"role": "report-schema", **_artifact(DEFAULT_REPORT_SCHEMA)},
    ]
    inputs = {
        "resolution_contract": _artifact(contract_path),
        "map_sheets": _artifact(map_sheets_path),
        "canonical_sources": source_artifacts,
        "executable_inputs": executable_inputs,
        "validation_schemas": validation_schemas,
        "runtime_compatibility": _runtime_compatibility(),
    }
    _validate_input_role_sets(inputs)
    return {
        "contract": contract,
        "sources": sources,
        "parent_sheets": parent_sheets,
        "inputs": inputs,
    }


def _save_mask(image: Image.Image, path: Path) -> None:
    if path.exists():
        raise ParentControlError(f"refusing to overwrite generated mask: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("sstory-control-origin", "independent-parent-canonical-raster-v1")
    image.save(path, pnginfo=metadata, **PNG_OPTIONS)


def _mask_record(
    physical_path: Path,
    logical_path: Path,
    *,
    expected_size: tuple[int, int],
) -> tuple[dict[str, Any], int]:
    try:
        with Image.open(physical_path) as opened:
            opened.load()
            size = opened.size
            image_format = opened.format
            mode = opened.mode
            histogram = opened.histogram()
    except (OSError, ValueError) as exc:
        raise ParentControlError(
            f"cannot inspect generated mask {physical_path}: {exc}"
        ) from exc
    if size != expected_size:
        raise ParentControlError(
            f"generated mask dimensions are unexpected for {physical_path}: "
            f"expected={expected_size}, actual={size}"
        )
    if image_format != "PNG" or mode != "L":
        raise ParentControlError(
            f"generated mask encoding is unexpected for {physical_path}: "
            f"format={image_format}, mode={mode}"
        )
    populated_values = [index for index, count in enumerate(histogram) if count]
    if any(value not in {0, 255} for value in populated_values):
        raise ParentControlError(f"generated mask is not binary: {physical_path}")
    record = {
        **_artifact(physical_path, logical_path),
        "width": size[0],
        "height": size[1],
        "format": image_format,
        "color_mode": mode,
        "binary_values": populated_values,
        "on_pixel_count": histogram[255],
    }
    return record, histogram[255]


def _render_sheet(
    *,
    sources: dict[str, dict[str, Any]],
    contract: dict[str, Any],
    sheet: dict[str, Any],
    physical_root: Path,
    logical_root: Path,
) -> dict[str, Any]:
    sheet_id = sheet["sheet_id"]
    physical_dir = physical_root / sheet_id / "qa"
    logical_dir = logical_root / sheet_id / "qa"
    physical_dir.mkdir(parents=True, exist_ok=False)
    transform = ParentNativeTransform(contract, sheet)
    expected_size = (sheet["width"], sheet["height"])
    land_mask: Image.Image | None = None
    transport_mask: Image.Image | None = None
    try:
        land_mask = render_land_sea_control(sources, transform)
        transport_mask = render_transport_control(sources, transform)
        if land_mask.size != expected_size:
            raise ParentControlError(
                f"{sheet_id} land/sea renderer returned wrong dimensions"
            )
        if transport_mask.size != expected_size:
            raise ParentControlError(
                f"{sheet_id} transport renderer returned wrong dimensions"
            )
        land_path = physical_dir / "land-sea-control.png"
        transport_path = physical_dir / "transport-control.png"
        _save_mask(land_mask, land_path)
        _save_mask(transport_mask, transport_path)
    except ValueError as exc:
        if isinstance(exc, ParentControlError):
            raise
        raise ParentControlError(
            f"{sheet_id} canonical mask render failed: {exc}"
        ) from exc
    finally:
        for image in (land_mask, transport_mask):
            if image is not None:
                image.close()

    land_record, land_pixels = _mask_record(
        land_path,
        logical_dir / "land-sea-control.png",
        expected_size=expected_size,
    )
    transport_record, transport_pixels = _mask_record(
        transport_path,
        logical_dir / "transport-control.png",
        expected_size=expected_size,
    )
    total_pixels = expected_size[0] * expected_size[1]
    return {
        "sheet_id": sheet_id,
        "sheet_type": sheet["sheet_type"],
        "parent_id": sheet["parent_id"],
        "source_feature_id": sheet["source_feature_id"],
        "bounds": sheet["bounds"],
        "native_zoom": sheet["native_zoom"],
        "pixel_bounds": sheet["pixel_bounds"],
        "width": expected_size[0],
        "height": expected_size[1],
        "qa_controls": {
            "land_sea_control": land_record,
            "transport_control": transport_record,
        },
        "metrics": {
            "total_pixel_count": total_pixels,
            "land_pixel_count": land_pixels,
            "water_pixel_count": total_pixels - land_pixels,
            "transport_pixel_count": transport_pixels,
        },
    }


def _role_tuple(records: Any, label: str) -> tuple[str, ...]:
    if not isinstance(records, list) or not all(
        isinstance(record, Mapping) and isinstance(record.get("role"), str)
        for record in records
    ):
        raise ParentControlError(f"{label} must be an array of role-bearing objects")
    return tuple(str(record["role"]) for record in records)


def _validate_input_role_sets(inputs: Mapping[str, Any]) -> None:
    expected_sets = (
        ("canonical source", inputs.get("canonical_sources"), EXPECTED_SOURCE_ROLES),
        (
            "executable input",
            inputs.get("executable_inputs"),
            EXPECTED_EXECUTABLE_ROLES,
        ),
        ("validation schema", inputs.get("validation_schemas"), EXPECTED_SCHEMA_ROLES),
    )
    for label, records, expected in expected_sets:
        actual = _role_tuple(records, label)
        if actual != expected or len(set(actual)) != len(actual):
            raise ParentControlError(
                f"{label} role set/order is unexpected: "
                f"expected={list(expected)!r}, actual={list(actual)!r}"
            )


def _input_artifact_count(inputs: Mapping[str, Any]) -> int:
    return (
        2
        + len(inputs["canonical_sources"])
        + len(inputs["executable_inputs"])
        + len(inputs["validation_schemas"])
    )


def build_output(
    *,
    physical_root: Path,
    logical_root: Path,
    plan_inputs: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    physical_root = physical_root.resolve()
    logical_root = logical_root.resolve()
    _repo_path(physical_root)
    _repo_path(logical_root)
    physical_root.mkdir(parents=True, exist_ok=True)
    if any(physical_root.iterdir()):
        raise ParentControlError(f"physical build root must be empty: {physical_root}")
    _validate_input_role_sets(plan_inputs["inputs"])

    sheets = [
        _render_sheet(
            sources=plan_inputs["sources"],
            contract=plan_inputs["contract"],
            sheet=sheet,
            physical_root=physical_root,
            logical_root=logical_root,
        )
        for sheet in plan_inputs["parent_sheets"]
    ]
    if tuple(item["sheet_id"] for item in sheets) != EXPECTED_PARENT_IDS:
        raise ParentControlError(
            "rendered parent sheet set differs from the fixed contract"
        )

    index = {
        "$schema": SCHEMA_URL,
        "schema_version": "1.1.0",
        "type": "sstory-phase5-parent-control-index",
        "coordinate_reference_system": "EA-WORLD-1",
        "generated_by": GENERATOR_ID,
        "render_contract": {
            "sheet_ids": list(EXPECTED_PARENT_IDS),
            "sheet_types": ["world", "continent"],
            "image_format": "PNG",
            "mask_color_mode": "L",
            "land_sea_semantics": "255=canonical-conservative-land-interior;0=water-or-boundary",
            "transport_semantics": "255=canonical-route-centerline;0=no-canonical-route",
            "coordinate_quantization": "global-native-grid-round-half-up-v1",
            "control_rasterizer": "independent-parent-canonical-raster-v1",
            "source_policy": "canonical-ea-world-1-only",
            "direct17_control_index_required": False,
            "observed_renderer_builders_consumed": False,
            "parent_observed_masks_consumed": False,
            "composited_masters_consumed": False,
        },
        "inputs": plan_inputs["inputs"],
        "summary": {
            "sheet_count": 6,
            "world_sheet_count": 1,
            "continent_sheet_count": 5,
            "control_mask_count": 12,
            "input_artifact_count": _input_artifact_count(plan_inputs["inputs"]),
        },
        "sheets": sheets,
    }
    _validate_schema(index, DEFAULT_INDEX_SCHEMA, "parent control index")
    index_path = physical_root / "index.json"
    if index_path.exists():
        raise ParentControlError(f"refusing to overwrite generated index: {index_path}")
    _dump_json_lf(index_path, index)

    control_artifacts = [
        {
            "sheet_id": sheet["sheet_id"],
            "role": role,
            "path": record["path"],
            "sha256": record["sha256"],
        }
        for sheet in sheets
        for role, record in sheet["qa_controls"].items()
    ]
    report = {
        "$schema": REPORT_SCHEMA_URL,
        "schema_version": "1.1.0",
        "type": "sstory-phase5-parent-control-report",
        "coordinate_reference_system": "EA-WORLD-1",
        "generated_by": GENERATOR_ID,
        "status": "passed",
        "index": _artifact(index_path, logical_root / "index.json"),
        "inputs": plan_inputs["inputs"],
        "outputs": control_artifacts,
        "summary": index["summary"],
        "checks": {
            "exact_parent_sheet_set": {
                "passed": True,
                "expected": list(EXPECTED_PARENT_IDS),
                "actual": [sheet["sheet_id"] for sheet in sheets],
            },
            "native_dimensions": {
                "passed": True,
                "sheets": [
                    {
                        "sheet_id": sheet["sheet_id"],
                        "width": sheet["width"],
                        "height": sheet["height"],
                        "pixel_bounds": sheet["pixel_bounds"],
                    }
                    for sheet in sheets
                ],
            },
            "binary_png_controls": {"passed": True, "mask_count": 12},
            "hash_locked_artifacts": {
                "passed": True,
                "input_count": _input_artifact_count(plan_inputs["inputs"]),
                "output_count": len(control_artifacts),
                "index_locked": True,
            },
            "independent_control_path": {
                "passed": True,
                "source_policy": "canonical-ea-world-1-only",
                "control_rasterizer": "independent-parent-canonical-raster-v1",
                "direct17_control_index_consumed": False,
                "observed_renderer_builders_consumed": False,
                "parent_observed_masks_consumed": False,
                "composited_masters_consumed": False,
            },
        },
    }
    _validate_schema(report, DEFAULT_REPORT_SCHEMA, "parent control report")
    report_path = physical_root / "report.json"
    if report_path.exists():
        raise ParentControlError(
            f"refusing to overwrite generated report: {report_path}"
        )
    _dump_json_lf(report_path, report)
    return index, report


def generate_parent_controls(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    contract_path: Path = DEFAULT_CONTRACT,
    map_sheets_path: Path = DEFAULT_MAP_SHEETS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = _validated_output_root(output_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.building-", dir=output.parent)
    )
    try:
        plan_inputs = load_parent_inputs(
            source_dir=source_dir,
            contract_path=contract_path,
            map_sheets_path=map_sheets_path,
        )
        index, report = build_output(
            physical_root=stage,
            logical_root=output,
            plan_inputs=plan_inputs,
        )
        reservation = _reserve_output_root(output)
        _install_reserved_output(stage, reservation)
        return index, report
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _plain_bundle_entries(
    output: Path, *, allow_reservation_marker: bool = False
) -> tuple[set[str], dict[str, Path]]:
    expected_directories = {
        relative
        for sheet_id in EXPECTED_PARENT_IDS
        for relative in (sheet_id, f"{sheet_id}/qa")
    }
    expected_files = {
        "index.json",
        "report.json",
        *(
            f"{sheet_id}/qa/{filename}"
            for sheet_id in EXPECTED_PARENT_IDS
            for filename in ("land-sea-control.png", "transport-control.png")
        ),
    }
    if allow_reservation_marker:
        expected_files.add(".phase5-parent-control-reservation")
    actual_directories: set[str] = set()
    actual_files: dict[str, Path] = {}
    pending = [output]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise ParentControlError(
                f"cannot inspect parent control bundle: {exc}"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(output).as_posix()
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ParentControlError(
                    f"cannot inspect bundle entry {path}: {exc}"
                ) from exc
            if _stat_is_reparse(info):
                raise ParentControlError(
                    f"parent control bundle contains a symlink or reparse point: {path}"
                )
            if stat.S_ISDIR(info.st_mode):
                actual_directories.add(relative)
                pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                actual_files[relative] = path
            else:
                raise ParentControlError(
                    f"parent control bundle contains a non-regular entry: {path}"
                )
    if (
        actual_directories != expected_directories
        or set(actual_files) != expected_files
    ):
        raise ParentControlError(
            "parent control bundle has a non-canonical file tree: "
            f"missing_dirs={sorted(expected_directories - actual_directories)!r}, "
            f"extra_dirs={sorted(actual_directories - expected_directories)!r}, "
            f"missing_files={sorted(expected_files - set(actual_files))!r}, "
            f"extra_files={sorted(set(actual_files) - expected_files)!r}"
        )
    return actual_directories, actual_files


def _validate_expected_control_hashes(index: Mapping[str, Any]) -> None:
    actual: dict[tuple[str, str], str] = {}
    for sheet in index["sheets"]:
        sheet_id = str(sheet["sheet_id"])
        for role, record in sheet["qa_controls"].items():
            actual[(sheet_id, str(role))] = str(record["sha256"])
    if actual != EXPECTED_CONTROL_SHA256:
        mismatches = {
            f"{sheet_id}/{role}": {
                "expected": EXPECTED_CONTROL_SHA256.get((sheet_id, role)),
                "actual": actual.get((sheet_id, role)),
            }
            for sheet_id, role in sorted(set(EXPECTED_CONTROL_SHA256) | set(actual))
            if EXPECTED_CONTROL_SHA256.get((sheet_id, role))
            != actual.get((sheet_id, role))
        }
        raise ParentControlError(
            f"parent control hashes differ from the reviewed canonical set: {mismatches!r}"
        )


def _control_records(index: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    records: dict[tuple[str, str], Mapping[str, Any]] = {}
    for sheet in index["sheets"]:
        sheet_id = str(sheet["sheet_id"])
        for role, record in sheet["qa_controls"].items():
            key = (sheet_id, str(role))
            if key in records:
                raise ParentControlError(f"duplicate parent control record: {key!r}")
            records[key] = record
    return records


def _control_raster_hashes(
    index: Mapping[str, Any], files: Mapping[str, Path]
) -> dict[tuple[str, str], str]:
    hashes: dict[tuple[str, str], str] = {}
    for key, record in _control_records(index).items():
        sheet_id, role = key
        filename = CONTROL_FILENAMES.get(role)
        if filename is None:
            raise ParentControlError(f"unexpected parent control role: {role}")
        relative = f"{sheet_id}/qa/{filename}"
        path = files.get(relative)
        if path is None:
            raise ParentControlError(f"parent control raster is missing: {relative}")
        try:
            with Image.open(path) as opened:
                opened.load()
                expected_size = (int(record["width"]), int(record["height"]))
                if (
                    opened.format != "PNG"
                    or opened.mode != "L"
                    or opened.size != expected_size
                ):
                    raise ParentControlError(
                        "parent control index semantic fields disagree with the "
                        f"raster contract at {relative}: "
                        f"format={opened.format}, mode={opened.mode}, size={opened.size}"
                    )
                hashes[key] = raster_semantic_sha256(opened)
        except ParentControlError:
            raise
        except (OSError, ValueError) as exc:
            raise ParentControlError(
                f"cannot decode parent control raster {relative}: {exc}"
            ) from exc
    return hashes


def _validate_expected_control_rasters(
    index: Mapping[str, Any], files: Mapping[str, Path]
) -> None:
    actual = _control_raster_hashes(index, files)
    if actual != EXPECTED_CONTROL_RASTER_SHA256:
        mismatches = {
            f"{sheet_id}/{role}": {
                "expected": EXPECTED_CONTROL_RASTER_SHA256.get((sheet_id, role)),
                "actual": actual.get((sheet_id, role)),
            }
            for sheet_id, role in sorted(
                set(EXPECTED_CONTROL_RASTER_SHA256) | set(actual)
            )
            if EXPECTED_CONTROL_RASTER_SHA256.get((sheet_id, role))
            != actual.get((sheet_id, role))
        }
        raise ParentControlError(
            "parent control decoded rasters differ from the reviewed canonical set: "
            f"{mismatches!r}"
        )


def _validate_distribution_bindings(
    index: Mapping[str, Any],
    report: Mapping[str, Any],
    files: Mapping[str, Path],
) -> None:
    records = _control_records(index)
    expected_outputs: dict[tuple[str, str], dict[str, str]] = {}
    for (sheet_id, role), record in records.items():
        filename = CONTROL_FILENAMES[role]
        relative = f"{sheet_id}/qa/{filename}"
        actual_sha = sha256_file(files[relative])
        if actual_sha != record["sha256"]:
            raise ParentControlError(
                f"parent control distribution SHA-256 mismatch at {relative}: "
                f"index={record['sha256']}, actual={actual_sha}"
            )
        expected_outputs[(sheet_id, role)] = {
            "sheet_id": sheet_id,
            "role": role,
            "path": str(record["path"]),
            "sha256": str(record["sha256"]),
        }
    actual_outputs = {
        (str(record["sheet_id"]), str(record["role"])): dict(record)
        for record in report["outputs"]
    }
    if actual_outputs != expected_outputs:
        raise ParentControlError(
            "parent control report output bindings differ from the index"
        )


def _semantic_index_document(index: Mapping[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(index)
    for record in _control_records(normalized).values():
        record["sha256"] = "0" * 64
    return normalized


def _semantic_report_document(report: Mapping[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(report)
    normalized["index"]["sha256"] = "0" * 64
    for record in normalized["outputs"]:
        record["sha256"] = "0" * 64
    return normalized


def _load_bundle_documents(
    output: Path,
    *,
    logical_root: Path | None = None,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    contract_path: Path = DEFAULT_CONTRACT,
    map_sheets_path: Path = DEFAULT_MAP_SHEETS,
    allow_reservation_marker: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = _validated_output_root(output, must_exist=True)
    logical_root = (logical_root or output).resolve()
    _repo_path(logical_root)
    _, actual_files = _plain_bundle_entries(
        output,
        allow_reservation_marker=allow_reservation_marker,
    )
    index_path = actual_files["index.json"]
    report_path = actual_files["report.json"]
    index = _json_object(index_path, "parent control index")
    report = _json_object(report_path, "parent control report")
    if index.get("type") != "sstory-phase5-parent-control-index":
        raise ParentControlError("existing parent control index type is invalid")
    if report.get("type") != "sstory-phase5-parent-control-report":
        raise ParentControlError("existing parent control report type is invalid")
    _validate_schema(index, DEFAULT_INDEX_SCHEMA, "existing parent control index")
    _validate_schema(report, DEFAULT_REPORT_SCHEMA, "existing parent control report")
    expected_index = _artifact(index_path, logical_root / "index.json")
    if report.get("index") != expected_index:
        raise ParentControlError("parent control report does not hash-lock its index")
    _validate_distribution_bindings(index, report, actual_files)
    _validate_expected_control_hashes(index)
    _validate_expected_control_rasters(index, actual_files)

    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.semantic-audit-", dir=output.parent)
    )
    expected_root = temporary / "expected"
    try:
        plan_inputs = load_parent_inputs(
            source_dir=source_dir,
            contract_path=contract_path,
            map_sheets_path=map_sheets_path,
        )
        expected_index_document, expected_report_document = build_output(
            physical_root=expected_root,
            logical_root=logical_root,
            plan_inputs=plan_inputs,
        )
        _, expected_files = _plain_bundle_entries(expected_root)
        _validate_expected_control_rasters(expected_index_document, expected_files)
        if _semantic_index_document(index) != _semantic_index_document(
            expected_index_document
        ):
            raise ParentControlError(
                "parent control index semantic fields are stale or fabricated"
            )
        if _semantic_report_document(report) != _semantic_report_document(
            expected_report_document
        ):
            raise ParentControlError(
                "parent control report semantic fields are stale or fabricated"
            )
        for relative, expected_path in expected_files.items():
            if not relative.endswith(".png"):
                continue
            actual_hash = raster_semantic_sha256_file(actual_files[relative])
            expected_hash = raster_semantic_sha256_file(expected_path)
            if actual_hash != expected_hash:
                raise ParentControlError(
                    f"parent control decoded raster differs at {relative}: "
                    f"actual={actual_hash}, expected={expected_hash}"
                )
        return index, report
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def load_validated_parent_control_bundle(
    index_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load a fully regenerated, closed-world parent control bundle."""

    index_path = _validated_repo_file(index_path, "parent control index")
    expected_index_path = (DEFAULT_OUTPUT_ROOT / "index.json").resolve()
    if index_path != expected_index_path:
        raise ParentControlError(
            "production parent controls must use the canonical repository path: "
            f"{expected_index_path}"
        )
    if index_path.name != "index.json":
        raise ParentControlError("parent control index must be named index.json")
    return _load_bundle_documents(index_path.parent)


def load_validated_parent_control_bundle_snapshot(
    physical_snapshot_root: Path,
    *,
    logical_root: Path = DEFAULT_OUTPUT_ROOT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Audit immutable snapshot bytes under the canonical logical namespace.

    ``physical_snapshot_root`` must contain the exact closed 14-file bundle.
    Artifact paths inside its index/report remain anchored to ``logical_root``;
    no parent-control file is reopened through that logical pathname.
    """

    _assert_no_reparse_components(logical_root, "logical parent control root")
    logical_root = logical_root.resolve()
    expected_root = DEFAULT_OUTPUT_ROOT.resolve()
    if logical_root != expected_root:
        raise ParentControlError(
            "parent control snapshot must retain the canonical logical root: "
            f"{expected_root}"
        )
    return _load_bundle_documents(
        physical_snapshot_root,
        logical_root=logical_root,
    )


def verify_existing(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    contract_path: Path = DEFAULT_CONTRACT,
    map_sheets_path: Path = DEFAULT_MAP_SHEETS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return _load_bundle_documents(
        output_root,
        source_dir=source_dir,
        contract_path=contract_path,
        map_sheets_path=map_sheets_path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--map-sheets", type=Path, default=DEFAULT_MAP_SHEETS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--verify-existing",
        action="store_true",
        help=(
            "regenerate and compare decoded control rasters while verifying "
            "the existing distribution hashes"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify_existing:
            index, _ = verify_existing(
                args.output_root,
                source_dir=args.source_dir,
                contract_path=args.contract,
                map_sheets_path=args.map_sheets,
            )
            action = "verified"
        else:
            index, _ = generate_parent_controls(
                args.output_root,
                source_dir=args.source_dir,
                contract_path=args.contract,
                map_sheets_path=args.map_sheets,
            )
            action = "generated"
    except (OSError, ParentControlError) as exc:
        print(f"Phase 5 parent control error: {exc}", file=sys.stderr)
        return 1
    print(
        f"Phase 5 parent controls {action}: "
        f"{index['summary']['sheet_count']} sheets / "
        f"{index['summary']['control_mask_count']} masks at {args.output_root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
