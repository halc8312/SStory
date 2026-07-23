#!/usr/bin/env python3
"""Render one deterministic H15 edit: remove H4 pictorial-height grammar."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw

import audit_style_candidate_h4 as h4
import render_candidate_h9_dense_flat_plan as h9


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_H4 = REPO_ROOT / "world/map-production/candidates/style-candidate-h-v4-plan-view-golden-board.png"
DEFAULT_H5 = REPO_ROOT / "world/map-production/candidates/style-candidate-h-v5-strict-plan-symbols.png"
DEFAULT_B1 = REPO_ROOT / "world/map-production/candidates/style-candidate-b-v1.png"
DEFAULT_OUTPUT = REPO_ROOT / "tmp/map-production/h15-prototype/iteration-1"
LOCKS = {
    "h4": "b4fc951af5d29c78bb98b5ee5007395b5fc3c1addc7070d76ac8074545259837",
    "h5": "d95ea917ee2b0a414c3e32de762208af4fb2239d7bbc65fa7633e85218ad56fe",
    "b1": "4d505def78acc752ee2611cb73d112cc9a3048f611cb05233274a1eb2ae42003",
}
CANVAS = (1536, 1024)
SEED = 0x4831355F464C4154
MASTER = "style-candidate-h-v15-flat-height.png"
MASK = "style-candidate-h-v15-flat-height.semantic-mask.png"
CONTACT = "style-candidate-h-v15-flat-height.contact-sheet.png"
REPORT = "style-candidate-h-v15-flat-height.automated.json"
PNG = {"format": "PNG", "compress_level": 9, "optimize": False}


class H15Error(ValueError):
    pass


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _artifact(path: Path) -> dict[str, Any]:
    return {"path": _rel(path), "sha256": _sha(path), "bytes": path.stat().st_size}


def _load(path: Path, key: str) -> Image.Image:
    if not path.is_file() or _sha(path) != LOCKS[key]:
        raise H15Error(f"locked {key} input missing or changed: {path}")
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    if image.size != CANVAS:
        image.close()
        raise H15Error(f"{key} must be 1536x1024")
    return image


def _mask_polygon(points: Sequence[tuple[int, int]]) -> np.ndarray:
    mask = np.zeros((CANVAS[1], CANVAS[0]), np.uint8)
    cv2.fillPoly(mask, [np.asarray(points, np.int32)], 1)
    return mask.astype(bool)


def _semantic_masks(source: Image.Image) -> dict[str, np.ndarray]:
    city_image = h9._city_mask()
    port_image = h9._port_mask()
    water_image = h9.h8._water_mask(source)
    try:
        city = np.asarray(city_image, np.uint8).copy() > 0
        port = np.asarray(port_image, np.uint8).copy() > 0
        water = np.asarray(water_image, np.uint8).copy() > 0
    finally:
        city_image.close()
        port_image.close()
        water_image.close()

    ne = _mask_polygon(((1010, 0), (1536, 0), (1536, 535), (1390, 515),
                        (1210, 535), (1030, 475), (930, 365), (955, 165)))
    south = _mask_polygon(((540, 825), (720, 785), (920, 770), (1080, 820),
                           (1200, 880), (1536, 970), (1536, 1024), (560, 1024)))
    fields = _mask_polygon(((955, 575), (1120, 540), (1536, 570), (1536, 995),
                            (1370, 925), (1160, 790)))
    network = np.zeros_like(water, np.uint8)
    roads = (
        ((900, 455), (960, 350), (1015, 205), (1085, 65), (1120, 0)),
        ((930, 495), (1110, 520), (1320, 505), (1536, 445)),
        ((900, 535), (1070, 660), (1240, 785), (1400, 900), (1536, 1005)),
        ((800, 570), (710, 670), (590, 780), (500, 850)),
    )
    for road in roads:
        cv2.polylines(network, [np.asarray(road, np.int32)], False, 1, 20, cv2.LINE_AA)
    highland = (ne | south) & ~fields & ~(network > 0) & ~water & ~city & ~port

    dilated = cv2.dilate(water.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    eroded = cv2.erode(water.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    boundary = dilated ^ eroded
    band = cv2.dilate(boundary.astype(np.uint8), np.ones((23, 23), np.uint8)) > 0
    yy, xx = np.indices(water.shape)
    geography = (xx < 650) | (yy > 785)
    coast = band & geography & ~boundary & ~city & ~port
    return {"city": city, "port": port, "highland": highland, "coast": coast,
            "water": water, "shoreline_core": boundary}


def _match_mask_stats(candidate: np.ndarray, source: np.ndarray, mask: np.ndarray) -> None:
    for channel in range(3):
        old = source[..., channel][mask].astype(np.float32)
        new = candidate[..., channel][mask].astype(np.float32)
        if new.size == 0:
            continue
        scaled = (new - new.mean()) * (old.std() / max(float(new.std()), 1e-6)) + old.mean()
        candidate[..., channel][mask] = np.clip(scaled, 0, 255).round().astype(np.uint8)


def _flatten_highland(source: np.ndarray, h5: np.ndarray, target: np.ndarray,
                      mask: np.ndarray) -> dict[str, Any]:
    source_f = source.astype(np.float32)
    h5_f = h5.astype(np.float32)
    low = cv2.GaussianBlur(source_f, (0, 0), 10.0)
    h5_high = h5_f - cv2.GaussianBlur(h5_f, (0, 0), 4.2)
    # Shift high-frequency plan vocabulary so H5 low-frequency geometry cannot transfer.
    h5_high = np.roll(h5_high, shift=(83, 157), axis=(0, 1))
    rng = np.random.default_rng(SEED)
    white = rng.normal(0.0, 1.0, mask.shape).astype(np.float32)
    micro = white - cv2.GaussianBlur(white, (0, 0), 1.2)
    plate = low + h5_high * 0.62 + micro[..., None] * np.array([2.4, 2.2, 1.8])
    result = np.clip(plate, 0, 255).round().astype(np.uint8)

    # Independent, angle-balanced short marks cannot form a shared triangular peak.
    draw_image = Image.fromarray(result, "RGB")
    draw = ImageDraw.Draw(draw_image)
    ys, xs = np.where(mask)
    rng_py = random.Random(SEED ^ 0x48414348)
    bins = [0] * 12
    strokes = min(15000, max(1, len(xs) // 25))
    for index in range(strokes):
        pick = rng_py.randrange(len(xs))
        x, y = int(xs[pick]), int(ys[pick])
        angle_bin = index % 12
        angle = math.pi * (angle_bin + rng_py.uniform(0.15, 0.85)) / 12.0
        length = rng_py.uniform(1.5, 6.5)
        x2 = round(x + math.cos(angle) * length)
        y2 = round(y + math.sin(angle) * length)
        if 0 <= x2 < CANVAS[0] and 0 <= y2 < CANVAS[1] and mask[y2, x2]:
            base = result[y, x].astype(int)
            colour = tuple(np.clip(base - rng_py.randint(22, 49), 26, 210).tolist())
            draw.line((x, y, x2, y2), fill=colour, width=1)
            bins[angle_bin] += 1
    result = np.asarray(draw_image, np.uint8).copy()
    draw_image.close()
    _match_mask_stats(result, source, mask)

    # Feather only inward; every changed pixel stays inside the semantic mask.
    distance = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    alpha = np.clip(distance / 5.0, 0.0, 1.0)[..., None]
    blended = source * (1.0 - alpha) + result * alpha
    target[mask] = np.clip(blended, 0, 255).round().astype(np.uint8)[mask]
    return {"short_hachures": int(sum(bins)), "angle_bins": bins,
            "angle_bin_max_min_ratio": round(max(bins) / max(1, min(bins)), 6),
            "closed_peak_polygons_drawn": 0, "directional_shading_used": False}


def _flatten_coast(source_image: Image.Image, target_image: Image.Image,
                   masks: dict[str, np.ndarray]) -> dict[str, Any]:
    coast_image = Image.fromarray((masks["coast"].astype(np.uint8) * 255), "L")
    water_image = Image.fromarray((masks["water"].astype(np.uint8) * 255), "L")
    try:
        h9.h8._local_background_fill(source_image, target_image, coast_image, water_image,
                                     salt=0xC0457)
    finally:
        coast_image.close()
        water_image.close()
    target = np.asarray(target_image, np.uint8).copy()
    source = np.asarray(source_image, np.uint8)
    wet = masks["coast"] & masks["water"]
    dry = masks["coast"] & ~masks["water"]
    _match_mask_stats(target, source, wet)
    _match_mask_stats(target, source, dry)
    # Exact H4 interface pixels are the coastline authority; no displacement is possible.
    target[masks["shoreline_core"]] = source[masks["shoreline_core"]]
    target_image.paste(Image.fromarray(target, "RGB"))
    return {"wet_band_pixels": int(wet.sum()), "dry_band_pixels": int(dry.sum()),
            "shoreline_core_pixels_restored_exact": int(masks["shoreline_core"].sum()),
            "cliff_facades_drawn": 0}


def _triangle_proxy(image: np.ndarray, mask: np.ndarray) -> int:
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    local = cv2.GaussianBlur(gray, (0, 0), 3.0)
    dark = ((gray.astype(np.int16) < local.astype(np.int16) - 10) & mask).astype(np.uint8)
    contours, _ = cv2.findContours(dark, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    count = 0
    for contour in contours:
        area = cv2.contourArea(contour)
        if 3 <= area <= 180:
            approx = cv2.approxPolyDP(contour, 0.11 * cv2.arcLength(contour, True), True)
            if len(approx) == 3:
                count += 1
    return count


def _contact(master: Image.Image) -> Image.Image:
    centers = ((850, 500), (490, 840), (1270, 280), (850, 910), (650, 170))
    contact = Image.new("RGB", (768, 1792), master.getpixel((900, 700)))
    overview = master.resize((768, 512), Image.Resampling.LANCZOS)
    contact.paste(overview, (0, 0))
    overview.close()
    for row, (cx, cy) in enumerate(centers):
        for column, zoom in enumerate((1, 2, 4)):
            size = 256 // zoom
            left = max(0, min(master.width - size, cx - size // 2))
            top = max(0, min(master.height - size, cy - size // 2))
            crop = master.crop((left, top, left + size, top + size))
            panel = crop.resize((256, 256), Image.Resampling.NEAREST)
            contact.paste(panel, (column * 256, 512 + row * 256))
            crop.close()
            panel.close()
    return contact


def render(*, h4_path: Path = DEFAULT_H4, h5_path: Path = DEFAULT_H5,
           b1_path: Path = DEFAULT_B1, output_dir: Path = DEFAULT_OUTPUT,
           replace: bool = False) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    try:
        output_dir.relative_to(DEFAULT_OUTPUT.parent.resolve())
    except ValueError as exc:
        raise H15Error("output must stay under tmp/map-production/h15-prototype") from exc
    paths = {"master": output_dir / MASTER, "mask": output_dir / MASK,
             "contact": output_dir / CONTACT, "report": output_dir / REPORT}
    if not replace and any(path.exists() for path in paths.values()):
        raise H15Error("refusing to overwrite H15 iteration")

    source = _load(h4_path, "h4")
    h5_image = _load(h5_path, "h5")
    b1 = _load(b1_path, "b1")
    try:
        masks = _semantic_masks(source)
        target_image = source.copy()
        coast_stats = _flatten_coast(source, target_image, masks)
        source_array = np.asarray(source, np.uint8)
        target = np.asarray(target_image, np.uint8).copy()
        highland_stats = _flatten_highland(source_array, np.asarray(h5_image, np.uint8),
                                            target, masks["highland"])
        target_image.close()
        target_image = Image.fromarray(target, "RGB")
        water_image = Image.fromarray((masks["water"].astype(np.uint8) * 255), "L")
        city_image = Image.fromarray((masks["city"].astype(np.uint8) * 255), "L")
        port_image = Image.fromarray((masks["port"].astype(np.uint8) * 255), "L")
        rng = random.Random(SEED)
        try:
            h9.h8._local_background_fill(source, target_image, city_image, water_image, salt=0xC179)
            city_stats = h9._draw_flat_city(target_image, city_image, rng)
            h9.h8._local_background_fill(source, target_image, port_image, water_image, salt=0xA019)
            port_stats = h9._draw_flat_port(target_image, port_image, water_image, rng)
        finally:
            water_image.close()
            city_image.close()
            port_image.close()
        candidate = np.asarray(target_image, np.uint8).copy()
        allowed = masks["city"] | masks["port"] | masks["highland"] | masks["coast"]
        changed = np.any(candidate != source_array, axis=2)
        violations = changed & ~allowed
        if violations.any():
            raise H15Error(f"protected-pixel violation: {int(violations.sum())}")

        semantic = np.zeros((CANVAS[1], CANVAS[0], 3), np.uint8)
        semantic[masks["coast"]] = (60, 110, 190)
        semantic[masks["highland"]] = (150, 92, 175)
        semantic[masks["port"]] = (224, 154, 52)
        semantic[masks["city"]] = (202, 58, 50)
        semantic_image = Image.fromarray(semantic, "RGB")
        contact = _contact(target_image)
        output_dir.mkdir(parents=True, exist_ok=True)
        target_image.save(paths["master"], **PNG)
        semantic_image.save(paths["mask"], **PNG)
        contact.save(paths["contact"], **PNG)

        palette = h4.palette_continuity_metrics(target_image, b1)
        readability = h4.downsample_readability_metrics(target_image)
        boundary = h4.boundary_metrics(target_image)
        repetition = h4.exact_repetition_metrics(target_image)
        before_triangles = _triangle_proxy(source_array, masks["highland"])
        after_triangles = _triangle_proxy(candidate, masks["highland"])
        triangle_ratio = after_triangles / max(before_triangles, 1)
        output_water = np.asarray(h9.h8._water_mask(target_image), np.uint8) > 0
        displacement_area = ~(cv2.dilate(masks["port"].astype(np.uint8), np.ones((5, 5), np.uint8)) > 0)
        shoreline_displacement = int(((output_water ^ masks["water"]) & displacement_area).sum())
        gate_status = {
            "protected_exact": not violations.any(), "palette": palette["passed"],
            "readability": readability["passed"], "boundary": boundary["passed"],
            "exact_repetition": repetition["passed"],
            "triangle_proxy_material_reduction": triangle_ratio <= 0.70,
            "shoreline_displacement_zero": shoreline_displacement == 0,
            "flat_city_port": city_stats["city_side_faces"] == 0 and port_stats["port_side_faces"] == 0,
        }
        report = {
            "schema_version": "1.0.0", "id": "style-candidate-h-v15-flat-height-automated",
            "status": "iteration_1_automated_pass_pending_author_vision" if all(gate_status.values()) else "iteration_1_failed_automated",
            "golden_reference": False,
            "inputs": {"h4_protected_base": _artifact(h4_path), "h5_high_frequency_vocabulary": _artifact(h5_path),
                       "b1_gate_reference": _artifact(b1_path)},
            "single_change": "remove pictorial height grammar inside city, port, rocky highland, and coastline masks",
            "full_resolution_protection": {"canvas_pixels": CANVAS[0] * CANVAS[1], "allowed_edit_pixels": int(allowed.sum()),
                "protected_pixels": int((~allowed).sum()), "changed_pixels": int(changed.sum()),
                "protected_violation_pixels": int(violations.sum()), "protected_pixel_equality_percent": 100.0},
            "semantic_mask": {"path": _rel(paths["mask"]), "counts": {name: int(masks[name].sum()) for name in ("city", "port", "highland", "coast")}},
            "perspective_proxies": {"triangular_A_like_components_before_h4": before_triangles,
                "triangular_A_like_components_after_h15": after_triangles, "remaining_ratio": round(triangle_ratio, 6),
                "city_flat_footprints": city_stats["city_flat_building_footprints"],
                "port_flat_footprints": port_stats["port_flat_building_footprints"],
                "city_side_faces": 0, "port_side_faces": 0, "directional_shadows": 0,
                "shoreline_displacement_pixels_outside_port": shoreline_displacement},
            "render_stats": {**highland_stats, **coast_stats},
            "automated_metrics": {"palette": palette, "readability": readability, "boundary": boundary, "exact_repetition": repetition},
            "gate_status": gate_status,
            "self_vision_review": {"status": "pending", "acceptance_authority": False,
                "reviewed_views": [], "immediate_failure_detected": None, "decision": "inspect generated contact before promotion"},
            "outputs": {"master": _artifact(paths["master"]), "semantic_mask": _artifact(paths["mask"]), "contact_sheet": _artifact(paths["contact"])},
        }
        paths["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report
    finally:
        source.close()
        h5_image.close()
        b1.close()
        for name in ("target_image", "semantic_image", "contact"):
            value = locals().get(name)
            if isinstance(value, Image.Image):
                value.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = render(output_dir=args.output_dir, replace=args.replace)
    except (H15Error, OSError, ValueError) as exc:
        print(f"H15 render failed: {exc}")
        return 2
    print(json.dumps({"status": report["status"], "master": report["outputs"]["master"], "gates": report["gate_status"]}, ensure_ascii=False))
    return 0 if all(report["gate_status"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
