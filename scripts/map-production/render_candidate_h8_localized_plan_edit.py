#!/usr/bin/env python3
"""Create the localized, protected-pixel Candidate H8 plan-view edit."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_H5 = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-h-v5-strict-plan-symbols.png"
)
DEFAULT_ATLAS = (
    REPO_ROOT
    / "tmp/map-production/texture-atlas/phase5-cartographic-material-atlas-v1.png"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "tmp/map-production/h8-prototype"
CANVAS = (1536, 1024)
H5_SHA256 = "d95ea917ee2b0a414c3e32de762208af4fb2239d7bbc65fa7633e85218ad56fe"
ATLAS_SHA256 = "9b42dcce48d275d392bc28235925ac02f37690ace3418d6cb65920f4da05c6e3"
GENERATOR_ID = "sstory-map-production/render_candidate_h8_localized_plan_edit.py@1"
SEED = 0x48385F504C414E
MASTER_NAME = "style-candidate-h-v8-h5-plan-edit.png"
MASK_NAME = "style-candidate-h-v8-h5-plan-edit.semantic-mask.png"
CONTACT_NAME = "style-candidate-h-v8-h5-plan-edit.contact-sheet.png"
REPORT_NAME = "style-candidate-h-v8-h5-plan-edit.provenance.json"
PNG_OPTIONS = {"format": "PNG", "compress_level": 9, "optimize": False}

CITY_CENTER = (850.0, 500.0)
CITY_BOUNDS = (700, 350, 980, 620)
PORT_BOUNDS = (380, 740, 570, 920)
FOREST_CROP = (430, 20, 790, 260)

INK = (82, 72, 48)
INK_SOFT = (104, 88, 58)
PARCHMENT = (174, 151, 105)
ROAD = (191, 169, 119)
CITY_COLORS = ((150, 116, 78), (157, 122, 82), (143, 108, 73), (164, 130, 88))
FOREST_INK = (83, 84, 48)
FOREST_MID = (103, 105, 59)


class H8RenderError(ValueError):
    """Raised when a protected H8 render contract cannot be met."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": _relative(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _load_locked(path: Path, digest: str, label: str) -> Image.Image:
    if not path.is_file():
        raise H8RenderError(f"{label} is missing: {path}")
    actual = sha256_file(path)
    if actual != digest:
        raise H8RenderError(f"{label} SHA-256 mismatch: expected {digest}, got {actual}")
    with Image.open(path) as opened:
        opened.load()
        if opened.format != "PNG" or opened.mode != "RGB":
            raise H8RenderError(f"{label} must be an RGB PNG")
        if label == "H5 edit target" and opened.size != CANVAS:
            raise H8RenderError(f"H5 edit target must be {CANVAS[0]}x{CANVAS[1]}")
        return opened.copy()


def _validated_output_dir(path: Path) -> Path:
    resolved = path.resolve()
    root = DEFAULT_OUTPUT_ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise H8RenderError(f"output must stay under {_relative(DEFAULT_OUTPUT_ROOT)}")
    return resolved


def _ellipse_mask(center: tuple[float, float], radii: tuple[float, float]) -> Image.Image:
    mask = Image.new("L", CANVAS, 0)
    draw = ImageDraw.Draw(mask)
    cx, cy = center
    rx, ry = radii
    draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
    return mask


def _port_mask() -> Image.Image:
    mask = Image.new("L", CANVAS, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(
        (
            (411, 807),
            (453, 764),
            (520, 766),
            (563, 808),
            (556, 873),
            (521, 915),
            (451, 914),
            (392, 876),
        ),
        fill=255,
    )
    return mask


def _water_mask(image: Image.Image) -> Image.Image:
    mask = Image.new("L", image.size)
    mask.putdata([
        255 if b >= 101 and b > r + 4 and b >= g - 18 else 0
        for r, g, b in image.get_flattened_data()
    ])
    return mask


def _mask_from_rgb(image: Image.Image, predicate: Any) -> Image.Image:
    mask = Image.new("L", image.size)
    mask.putdata([255 if predicate(pixel) else 0 for pixel in image.get_flattened_data()])
    return mask


def _manual_protection_mask() -> Image.Image:
    protected = Image.new("L", CANVAS, 0)
    draw = ImageDraw.Draw(protected)
    # Right-side rocky highland and lower rocky shoulder.
    draw.polygon(
        ((990, 0), (1536, 0), (1536, 540), (1340, 530), (1120, 455), (970, 260)),
        fill=255,
    )
    draw.polygon(((835, 780), (1100, 720), (1310, 840), (1310, 1024), (850, 1024)), fill=255)
    # Agricultural fabric must remain byte-for-byte H5.
    draw.polygon(
        ((965, 585), (1135, 540), (1536, 600), (1536, 995), (1320, 940), (1110, 790)),
        fill=255,
    )
    road_paths = (
        ((850, 500), (1010, 470), (1040, 260), (1160, 60)),
        ((850, 500), (1040, 520), (1270, 565), (1536, 470)),
        ((850, 500), (990, 640), (1190, 760), (1536, 1000)),
        ((850, 500), (760, 640), (620, 745), (500, 850)),
        ((850, 500), (730, 435), (650, 350), (560, 320)),
    )
    for path in road_paths:
        draw.line(path, fill=255, width=14, joint="curve")
    return protected


def _forest_envelope_mask() -> Image.Image:
    """Broad semantic envelopes; density still decides the actual forest pixels."""
    mask = Image.new("L", CANVAS, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(((405, 0), (1010, 0), (940, 180), (820, 350), (615, 370), (430, 250)), fill=255)
    draw.polygon(((545, 510), (825, 500), (905, 650), (805, 780), (570, 735), (485, 610)), fill=255)
    draw.polygon(((980, 505), (1260, 500), (1510, 600), (1536, 770), (1300, 805), (1080, 690)), fill=255)
    draw.polygon(((520, 755), (860, 735), (990, 900), (930, 1024), (575, 1024), (460, 885)), fill=255)
    return mask


def _infer_forest_masks(
    source: Image.Image,
    water: Image.Image,
    city: Image.Image,
    port: Image.Image,
) -> tuple[Image.Image, Image.Image]:
    canopy = _mask_from_rgb(
        source,
        lambda p: (
            65 <= p[0] <= 150
            and 70 <= p[1] <= 150
            and 35 <= p[2] <= 105
            and p[1] >= p[2] + 18
            and abs(p[0] - p[1]) <= 31
        ),
    )
    coarse = canopy.resize((96, 64), Image.Resampling.BOX)
    dense = coarse.point(lambda value: 255 if value >= 62 else 0)
    dense = dense.filter(ImageFilter.MaxFilter(3)).resize(CANVAS, Image.Resampling.NEAREST)
    coarse.close()

    protected = _manual_protection_mask()
    envelope = _forest_envelope_mask()
    expanded_water = water.filter(ImageFilter.MaxFilter(7))
    exclusion = ImageChops.lighter(expanded_water, protected)
    exclusion = ImageChops.lighter(exclusion, city)
    exclusion = ImageChops.lighter(exclusion, port)
    zone = ImageChops.multiply(dense, envelope)
    zone = ImageChops.multiply(zone, ImageOps.invert(exclusion))
    # The revision may modulate only existing dark-canopy pixels: no dilation.
    old_canopy = ImageChops.multiply(canopy, zone)
    canopy.close()
    dense.close()
    protected.close()
    envelope.close()
    expanded_water.close()
    exclusion.close()
    return zone, old_canopy


def _local_background_fill(
    source: Image.Image,
    target: Image.Image,
    mask: Image.Image,
    water: Image.Image,
    *,
    salt: int,
) -> None:
    src = source.load()
    dst = target.load()
    selected = mask.load()
    wet = water.load()
    bounds = mask.getbbox()
    if bounds is None:
        return
    offsets = (
        (-47, -31), (53, -29), (-61, 17), (67, 23), (-29, 59), (31, -67),
        (-83, -7), (89, 11), (-19, -91), (17, 97), (-113, 37), (109, -43),
        (-137, 0), (139, 0), (0, -127), (0, 131),
    )
    for y in range(bounds[1], bounds[3]):
        for x in range(bounds[0], bounds[2]):
            if selected[x, y] == 0:
                continue
            want_water = wet[x, y] > 0
            start = (x * 73856093 ^ y * 19349663 ^ salt) % len(offsets)
            replacement = src[x, y]
            for step in range(len(offsets)):
                dx, dy = offsets[(start + step) % len(offsets)]
                sx = min(CANVAS[0] - 1, max(0, x + dx))
                sy = min(CANVAS[1] - 1, max(0, y + dy))
                if selected[sx, sy] == 0 and (wet[sx, sy] > 0) == want_water:
                    replacement = src[sx, sy]
                    break
            dst[x, y] = replacement


def _rotated_footprint(
    center: tuple[float, float],
    width: float,
    height: float,
    angle: float,
    rng: random.Random,
) -> list[tuple[float, float]]:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    result: list[tuple[float, float]] = []
    for local_x, local_y in (
        (-width / 2, -height / 2),
        (width / 2, -height / 2),
        (width / 2, height / 2),
        (-width / 2, height / 2),
    ):
        result.append(
            (
                center[0] + local_x * cosine - local_y * sine + rng.uniform(-0.7, 0.7),
                center[1] + local_x * sine + local_y * cosine + rng.uniform(-0.7, 0.7),
            )
        )
    return result


def _draw_flat_city(target: Image.Image, mask: Image.Image, rng: random.Random) -> dict[str, int]:
    layer = Image.new("RGB", CANVAS, (0, 0, 0))
    layer.paste(target)
    draw = ImageDraw.Draw(layer)
    cx, cy = CITY_CENTER
    # Flat concentric boundary footprints: outlines have equal tone on all sides.
    draw.ellipse((cx - 119, cy - 112, cx + 119, cy + 112), fill=PARCHMENT, outline=INK, width=3)
    draw.ellipse((cx - 114, cy - 107, cx + 114, cy + 107), outline=INK_SOFT, width=2)
    block_count = 0
    courtyard_count = 0
    ring_specs = ((37.0, 15), (65.0, 20), (93.0, 26))
    for ring_index, (radius, sectors) in enumerate(ring_specs):
        phase = ring_index * 0.077
        for sector in range(sectors):
            base_angle = phase + math.tau * sector / sectors
            footprint_count = rng.randint(2, 4)
            for footprint_index in range(footprint_count):
                angular_offset = (footprint_index - (footprint_count - 1) / 2) * rng.uniform(0.032, 0.055)
                angle = base_angle + angular_offset + rng.uniform(-0.018, 0.018)
                local_radius = radius + rng.uniform(-5.0, 5.0)
                px = cx + math.cos(angle) * local_radius
                py = cy + math.sin(angle) * local_radius
                polygon = _rotated_footprint(
                    (px, py),
                    rng.uniform(5.0, 10.0),
                    rng.uniform(4.0, 8.5),
                    angle + math.pi / 2 + rng.uniform(-0.22, 0.22),
                    rng,
                )
                color = CITY_COLORS[(sector + ring_index + footprint_index) % len(CITY_COLORS)]
                draw.polygon(polygon, fill=color, outline=INK)
                block_count += 1
                if block_count % 13 == 0:
                    draw.ellipse((px - 1.8, py - 1.8, px + 1.8, py + 1.8), fill=PARCHMENT)
                    courtyard_count += 1
    # Ring streets and spoke streets stay light and two-dimensional.
    for radius_x, radius_y in ((52, 49), (79, 74), (107, 101)):
        draw.ellipse((cx - radius_x, cy - radius_y, cx + radius_x, cy + radius_y), outline=ROAD, width=4)
        draw.ellipse((cx - radius_x, cy - radius_y, cx + radius_x, cy + radius_y), outline=INK_SOFT, width=1)
    for spoke in range(9):
        angle = math.tau * spoke / 9 + rng.uniform(-0.035, 0.035)
        bend = rng.uniform(-0.07, 0.07)
        points = (
            (cx + math.cos(angle) * 22, cy + math.sin(angle) * 22),
            (cx + math.cos(angle + bend) * 66, cy + math.sin(angle + bend) * 62),
            (cx + math.cos(angle - bend * 0.35) * 112, cy + math.sin(angle - bend * 0.35) * 106),
        )
        draw.line(points, fill=ROAD, width=4, joint="curve")
        draw.line(points, fill=INK_SOFT, width=1, joint="curve")
    draw.ellipse((cx - 21, cy - 21, cx + 21, cy + 21), fill=PARCHMENT, outline=INK, width=2)
    draw.polygon(((842, 491), (859, 491), (861, 508), (842, 510)), fill=CITY_COLORS[2], outline=INK)
    target.paste(layer, (0, 0), mask)
    layer.close()
    return {"city_flat_footprints": block_count + 1, "city_courtyards": courtyard_count + 1}


def _draw_flat_port(target: Image.Image, mask: Image.Image, rng: random.Random) -> dict[str, int]:
    layer = target.copy()
    draw = ImageDraw.Draw(layer)
    # Shoreline quays are flat polygons, never vertical posts or facade strokes.
    quay = ((431, 833), (447, 821), (470, 819), (494, 824), (519, 829), (541, 840), (537, 848), (512, 839), (489, 834), (466, 830), (444, 834))
    draw.polygon(quay, fill=(170, 150, 104), outline=INK)
    lane_paths = (
        ((445, 818), (531, 828)),
        ((455, 798), (476, 853)),
        ((486, 790), (500, 860)),
        ((515, 799), (522, 853)),
    )
    for path in lane_paths:
        draw.line(path, fill=ROAD, width=5)
        draw.line(path, fill=INK_SOFT, width=1)
    building_count = 0
    for row in range(5):
        for column in range(7):
            x = 443 + column * 14 + rng.randint(-3, 3)
            y = 781 + row * 13 + rng.randint(-3, 3)
            width = rng.randint(6, 10)
            height = rng.randint(4, 8)
            angle = rng.uniform(-0.32, 0.32)
            poly = _rotated_footprint((x, y), width, height, angle, rng)
            draw.polygon(poly, fill=CITY_COLORS[(row + column) % 4], outline=INK)
            building_count += 1
    pier_polygons = []
    for start_x, start_y, angle, length, width in (
        (444, 837, 2.22, 38, 3.5),
        (465, 835, 1.96, 49, 4.0),
        (489, 837, 1.69, 57, 3.2),
        (514, 841, 1.42, 43, 3.7),
        (534, 846, 1.22, 32, 3.0),
    ):
        end_x = start_x + math.cos(angle) * length
        end_y = start_y + math.sin(angle) * length
        nx = -math.sin(angle) * width / 2
        ny = math.cos(angle) * width / 2
        polygon = ((start_x + nx, start_y + ny), (end_x + nx, end_y + ny), (end_x - nx, end_y - ny), (start_x - nx, start_y - ny))
        pier_polygons.append(polygon)
        draw.polygon(polygon, fill=(157, 127, 83), outline=INK)
    target.paste(layer, (0, 0), mask)
    layer.close()
    return {"port_flat_footprints": building_count, "port_quays": 1, "port_flat_piers": len(pier_polygons)}


def _atlas_high_frequency(atlas: Image.Image) -> Image.Image:
    box = (0, 0, min(512, atlas.width), min(480, atlas.height))
    crop = atlas.crop(box)
    blurred = crop.filter(ImageFilter.BoxBlur(3))
    high = ImageChops.subtract(crop, blurred, scale=1.0, offset=128)
    crop.close()
    blurred.close()
    return high


def _apply_forest_edit(
    target: Image.Image,
    old_canopy: Image.Image,
    atlas: Image.Image,
) -> tuple[Image.Image, dict[str, int]]:
    high = _atlas_high_frequency(atlas)
    tiled = Image.new("RGB", CANVAS)
    for y in range(0, CANVAS[1], high.height):
        for x in range(0, CANVAS[0], high.width):
            tile = high
            if (x // high.width + y // high.height) % 2:
                tile = ImageOps.mirror(high)
            tiled.paste(tile, (x, y))
            if tile is not high:
                tile.close()
    high.close()
    # Ten-percent modulation inside existing dark-canopy pixels only.
    base_pixels = target.load()
    texture_pixels = tiled.load()
    edit_pixels = old_canopy.load()
    bounds = old_canopy.getbbox()
    if bounds is not None:
        for y in range(bounds[1], bounds[3]):
            for x in range(bounds[0], bounds[2]):
                if edit_pixels[x, y] == 0:
                    continue
                r, g, b = base_pixels[x, y]
                tr, tg, tb = texture_pixels[x, y]
                base_pixels[x, y] = (
                    max(0, min(255, round(r + (tr - 128) * 0.10))),
                    max(0, min(255, round(g + (tg - 128) * 0.10))),
                    max(0, min(255, round(b + (tb - 128) * 0.10))),
                )
    tiled.close()
    return old_canopy.copy(), {
        "forest_new_outlines": 0,
        "forest_erased_pixels": 0,
        "forest_existing_canopy_modulation_pixels": _pixel_count(old_canopy),
    }


def _semantic_mask(city: Image.Image, port: Image.Image, forest: Image.Image) -> Image.Image:
    result = Image.new("RGB", CANVAS, (0, 0, 0))
    result.paste((58, 126, 68), (0, 0, CANVAS[0], CANVAS[1]), forest)
    result.paste((224, 154, 52), (0, 0, CANVAS[0], CANVAS[1]), port)
    result.paste((202, 58, 50), (0, 0, CANVAS[0], CANVAS[1]), city)
    return result


def _contact_sheet(master: Image.Image) -> tuple[Image.Image, list[dict[str, Any]]]:
    contact = Image.new("RGB", (1176, 768), (167, 145, 100))
    overview = master.resize((768, 512), Image.Resampling.LANCZOS)
    contact.paste(overview, (0, 0))
    overview.close()
    panels = [
        ("overview_50_percent", (0, 0, 1536, 1024), (0, 0), (768, 512)),
        ("city_native", CITY_BOUNDS, (792, 20), (280, 270)),
        ("port_native", PORT_BOUNDS, (792, 310), (190, 180)),
        ("forest_native", FOREST_CROP, (792, 510), (360, 240)),
    ]
    for _, source_box, destination, expected in panels[1:]:
        crop = master.crop(source_box)
        if crop.size != expected:
            raise H8RenderError(f"contact crop mismatch for {source_box}")
        contact.paste(crop, destination)
        crop.close()
    records = [
        {
            "id": panel_id,
            "source_box_px": list(source_box),
            "destination_px": list(destination),
            "display_size_px": list(display_size),
            "native_pixels": panel_id != "overview_50_percent",
        }
        for panel_id, source_box, destination, display_size in panels
    ]
    return contact, records


def _pixel_count(mask: Image.Image) -> int:
    histogram = mask.histogram()
    # Pillow histograms store the number of pixels in each value bucket.  The
    # sum of non-zero buckets is already a pixel count; dividing it by 255
    # incorrectly reported a 1/255 sample of the full-resolution evidence.
    return sum(histogram[1:])


def _protected_equality(source: Image.Image, output: Image.Image, allowed: Image.Image) -> dict[str, Any]:
    difference = ImageChops.difference(source, output).convert("L").point(lambda value: 255 if value else 0)
    protected = ImageOps.invert(allowed)
    violations = ImageChops.multiply(difference, protected)
    protected_pixels = _pixel_count(protected)
    violation_pixels = _pixel_count(violations)
    changed_pixels = _pixel_count(difference)
    difference.close()
    protected.close()
    violations.close()
    equality = 100.0 if protected_pixels == 0 else 100.0 * (protected_pixels - violation_pixels) / protected_pixels
    if violation_pixels:
        raise H8RenderError(f"protected-pixel equality failed at {violation_pixels} pixels")
    return {
        "protected_pixels": protected_pixels,
        "protected_equal_pixels": protected_pixels - violation_pixels,
        "protected_violation_pixels": violation_pixels,
        "protected_pixel_equality_percent": round(equality, 12),
        "changed_pixels": changed_pixels,
    }


def render(
    *,
    h5_path: Path = DEFAULT_H5,
    atlas_path: Path = DEFAULT_ATLAS,
    output_dir: Path = DEFAULT_OUTPUT_ROOT,
    replace: bool = False,
) -> dict[str, Any]:
    output_dir = _validated_output_dir(output_dir)
    paths = {
        "master": output_dir / MASTER_NAME,
        "semantic_mask": output_dir / MASK_NAME,
        "contact_sheet": output_dir / CONTACT_NAME,
        "provenance": output_dir / REPORT_NAME,
    }
    occupied = [path for path in paths.values() if path.exists()]
    if occupied and not replace:
        raise H8RenderError("refusing to overwrite: " + ", ".join(_relative(path) for path in occupied))

    source = _load_locked(h5_path, H5_SHA256, "H5 edit target")
    atlas = _load_locked(atlas_path, ATLAS_SHA256, "cartographic material atlas")
    try:
        target = source.copy()
        water = _water_mask(source)
        city = _ellipse_mask(CITY_CENTER, (126.0, 119.0))
        port = _port_mask()
        zone, old_canopy = _infer_forest_masks(source, water, city, port)
        rng = random.Random(SEED)
        try:
            _local_background_fill(source, target, city, water, salt=0xC17A)
            city_stats = _draw_flat_city(target, city, rng)
            _local_background_fill(source, target, port, water, salt=0xA011)
            port_stats = _draw_flat_port(target, port, rng)
            forest, forest_stats = _apply_forest_edit(target, old_canopy, atlas)
            try:
                allowed = ImageChops.lighter(city, port)
                allowed = ImageChops.lighter(allowed, forest)
                equality = _protected_equality(source, target, allowed)
                semantic = _semantic_mask(city, port, forest)
                contact, panels = _contact_sheet(target)
                output_dir.mkdir(parents=True, exist_ok=True)
                target.save(paths["master"], **PNG_OPTIONS)
                semantic.save(paths["semantic_mask"], **PNG_OPTIONS)
                contact.save(paths["contact_sheet"], **PNG_OPTIONS)
                semantic.close()
                contact.close()
                report = {
                    "schema_version": "1.0.0",
                    "id": "style-candidate-h-v8-h5-plan-edit-provenance",
                    "status": "preview",
                    "generated_by": {"id": GENERATOR_ID, **_artifact(Path(__file__))},
                    "inputs": {
                        "h5_edit_target": _artifact(h5_path),
                        "atlas_forest_material": _artifact(atlas_path),
                        "atlas_crop_px": [0, 0, min(512, atlas.width), min(480, atlas.height)],
                    },
                    "constraints": {
                        "localized_edit_only": True,
                        "histogram_or_rank_transfer_used": False,
                        "full_image_blur_used": False,
                        "directional_shading_used": False,
                        "side_faces_or_facades_used": False,
                        "atlas_high_frequency_strength": 0.10,
                        "h5_local_background_sampling": True,
                        "protected_water_roads_fields_highland": True,
                    },
                    "semantic_mask": {
                        "path": _relative(paths["semantic_mask"]),
                        "colors": {
                            "protected": [0, 0, 0],
                            "forest": [58, 126, 68],
                            "port": [224, 154, 52],
                            "city": [202, 58, 50],
                        },
                        "allowed_edit_pixels": _pixel_count(allowed),
                    },
                    "protected_pixel_equality": equality,
                    "render_stats": {**city_stats, **port_stats, **forest_stats},
                    "contact_panels": panels,
                    "outputs": {
                        "master": {**_artifact(paths["master"]), "width": target.width, "height": target.height, "mode": target.mode},
                        "semantic_mask": _artifact(paths["semantic_mask"]),
                        "contact_sheet": _artifact(paths["contact_sheet"]),
                    },
                }
                paths["provenance"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return report
            finally:
                forest.close()
                allowed.close()
        finally:
            target.close()
            water.close()
            city.close()
            port.close()
            zone.close()
            old_canopy.close()
    finally:
        source.close()
        atlas.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h5", type=Path, default=DEFAULT_H5)
    parser.add_argument("--atlas", type=Path, default=DEFAULT_ATLAS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = render(
            h5_path=args.h5.resolve(),
            atlas_path=args.atlas.resolve(),
            output_dir=args.output_dir.resolve(),
            replace=args.replace,
        )
    except (H8RenderError, OSError, ValueError) as exc:
        print(f"Candidate H8 localized edit failed: {exc}")
        return 1
    print(
        "Candidate H8 localized edit rendered: "
        f"sha256={report['outputs']['master']['sha256']} "
        f"protected_equal={report['protected_pixel_equality']['protected_pixel_equality_percent']}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
