#!/usr/bin/env python3
"""Render the bounded H20 source-level multiband Golden prototype.

H4 remains the pixel authority.  H5 contributes registered flat terrain at
low and middle spatial frequencies; H9 contributes only registered flat city
and port topology.  Every edit is clipped to an explicit inward-feathered
semantic mask and all pixels outside that mask remain byte-identical to H4.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import audit_style_candidate_h4 as h4
import render_candidate_h8_localized_plan_edit as h8
import render_style_candidate_h15_flat_height as h15
import render_style_candidate_h16_micro_inpaint as h16


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_H4 = h15.DEFAULT_H4
DEFAULT_H5 = h15.DEFAULT_H5
DEFAULT_H9 = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-h-v9-dense-flat-plan.png"
)
DEFAULT_B1 = h15.DEFAULT_B1
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "tmp/map-production/h20-prototype"
DEFAULT_ITERATION = "iteration-2"
LOCKS = {
    "h4": h15.LOCKS["h4"],
    "h5": h15.LOCKS["h5"],
    "h9": "bd813e93287b15fe12e654ca5d28633a6902bbbdb3c6d81b0c3e69816a7b2580",
    "b1": h15.LOCKS["b1"],
}
CANVAS = h15.CANVAS
PYRAMID_LEVELS = 6
ALIGNMENT_SCALE = 0.5
SEED = 0x4832305F42414E44
PNG = {"format": "PNG", "compress_level": 9, "optimize": False}
STEM = "style-candidate-h-v20-multiband-flat-plan"


class H20Error(ValueError):
    """Raised when the bounded H20 proof contract is violated."""


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


def _load_locked(path: Path, key: str) -> Image.Image:
    if not path.is_file() or _sha(path) != LOCKS[key]:
        raise H20Error(f"locked {key} input missing or changed: {path}")
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    if image.size != CANVAS:
        image.close()
        raise H20Error(f"{key} must be {CANVAS[0]}x{CANVAS[1]}")
    return image


def _paths(output_dir: Path) -> dict[str, Path]:
    return {
        "master": output_dir / f"{STEM}.png",
        "mask": output_dir / f"{STEM}.semantic-mask.png",
        "overview": output_dir / f"{STEM}.overview.png",
        "native": output_dir / f"{STEM}.native-focus.png",
        "scale25": output_dir / f"{STEM}.25-percent.png",
        "scale50": output_dir / f"{STEM}.50-percent.png",
        "scale200": output_dir / f"{STEM}.200-percent-focus.png",
        "scale400": output_dir / f"{STEM}.400-percent-focus.png",
        "contact": output_dir / f"{STEM}.contact-sheet.png",
        "report": output_dir / f"{STEM}.automated.json",
    }


def _validated_output(output_dir: Path) -> Path:
    resolved = output_dir.resolve()
    root = DEFAULT_OUTPUT_ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise H20Error(f"output must stay under {_rel(DEFAULT_OUTPUT_ROOT)}")
    return resolved


def _estimate_alignment(h4_rgb: np.ndarray, h5_rgb: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """Estimate a conservative feature homography from H5 coordinates to H4."""

    cv2.setRNGSeed(SEED & 0x7FFFFFFF)
    size = (CANVAS[0] // 2, CANVAS[1] // 2)
    target = cv2.resize(h4_rgb, size, interpolation=cv2.INTER_AREA)
    moving = cv2.resize(h5_rgb, size, interpolation=cv2.INTER_AREA)
    target_gray = cv2.cvtColor(target, cv2.COLOR_RGB2GRAY)
    moving_gray = cv2.cvtColor(moving, cv2.COLOR_RGB2GRAY)
    detector = cv2.ORB_create(
        nfeatures=30000,
        scaleFactor=1.1,
        nlevels=12,
        edgeThreshold=15,
        fastThreshold=5,
    )
    target_keys, target_desc = detector.detectAndCompute(target_gray, None)
    moving_keys, moving_desc = detector.detectAndCompute(moving_gray, None)
    if target_desc is None or moving_desc is None:
        raise H20Error("H5/H4 alignment descriptors are unavailable")
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(moving_desc, target_desc, k=2)
    matches = [first for first, second in pairs if first.distance < 0.68 * second.distance]
    if len(matches) < 18:
        raise H20Error(f"insufficient H5/H4 feature matches: {len(matches)}")
    moving_points = np.float32([moving_keys[item.queryIdx].pt for item in matches])
    target_points = np.float32([target_keys[item.trainIdx].pt for item in matches])
    affine, inlier_mask = cv2.estimateAffinePartial2D(
        moving_points,
        target_points,
        method=cv2.RANSAC,
        ransacReprojThreshold=1.5,
        maxIters=100000,
        confidence=0.999,
        refineIters=30,
    )
    if affine is None or inlier_mask is None:
        raise H20Error("H5/H4 feature homography could not be estimated")
    inliers = inlier_mask.ravel() > 0
    embedded = np.vstack((affine, np.array((0.0, 0.0, 1.0), np.float64)))
    scale_matrix = np.diag((ALIGNMENT_SCALE, ALIGNMENT_SCALE, 1.0))
    homography = np.linalg.inv(scale_matrix) @ embedded @ scale_matrix
    predicted = cv2.perspectiveTransform(
        moving_points[inliers, None, :], embedded.astype(np.float64)
    )[:, 0, :]
    errors = np.linalg.norm(predicted - target_points[inliers], axis=1) / ALIGNMENT_SCALE
    center = np.array([[[CANVAS[0] / 2.0, CANVAS[1] / 2.0]]], np.float32)
    warped_center = cv2.perspectiveTransform(center, homography.astype(np.float64))[0, 0]
    center_shift = float(np.linalg.norm(warped_center - center[0, 0]))
    corners = np.array(
        [[[0, 0], [CANVAS[0] - 1, 0], [CANVAS[0] - 1, CANVAS[1] - 1], [0, CANVAS[1] - 1]]],
        np.float32,
    )
    moved_corners = cv2.perspectiveTransform(corners, homography.astype(np.float64))[0]
    corner_shifts = np.linalg.norm(moved_corners - corners[0], axis=1)
    stats = {
        "method": "ORB ratio-0.68 + RANSAC partial-affine embedded as 3x3 homography",
        "moving_coordinate_system": "H5/H9",
        "target_coordinate_system": "H4",
        "feature_matches": len(matches),
        "inliers": int(inliers.sum()),
        "inlier_fraction": round(float(inliers.mean()), 6),
        "median_reprojection_error_fullres_px": round(float(np.median(errors)), 6),
        "p90_reprojection_error_fullres_px": round(float(np.percentile(errors, 90)), 6),
        "center_shift_px": round(center_shift, 6),
        "maximum_corner_shift_px": round(float(corner_shifts.max()), 6),
        "homography_h5_to_h4": [[round(float(value), 10) for value in row] for row in homography],
        "warp_required": bool(float(corner_shifts.max()) > 0.5),
        "subpixel_median_verified": bool(float(np.median(errors)) < 1.0),
    }
    if stats["inliers"] < 18:
        raise H20Error(f"insufficient alignment inliers: {stats['inliers']}")
    if not stats["subpixel_median_verified"] or stats["p90_reprojection_error_fullres_px"] > 3.0:
        raise H20Error(f"H5/H4 alignment residual is too high: {stats}")
    return homography.astype(np.float64), stats


def _warp(image: np.ndarray, homography: np.ndarray) -> np.ndarray:
    return cv2.warpPerspective(
        image,
        homography,
        CANVAS,
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def _largest_blue_water(image: np.ndarray) -> np.ndarray:
    """Return a stable water body used only as a protection/shoreline guard."""

    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
    blue_axis = cv2.GaussianBlur(lab[..., 2].astype(np.float32), (0, 0), 3.2)
    candidate = (blue_axis <= 136.0).astype(np.uint8)
    candidate = cv2.morphologyEx(
        candidate,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)),
    )
    count, labels, stats, _ = cv2.connectedComponentsWithStats(candidate, 8)
    if count <= 1:
        raise H20Error("semantic water protection could not be resolved")
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    water = labels == largest
    if int(water.sum()) < 180000:
        raise H20Error(f"semantic water protection is unexpectedly small: {int(water.sum())}")
    return water


def _polygon(points: Sequence[tuple[int, int]]) -> np.ndarray:
    result = np.zeros((CANVAS[1], CANVAS[0]), np.uint8)
    cv2.fillPoly(result, [np.asarray(points, np.int32)], 1)
    return result > 0


def _road_and_field_guards() -> tuple[np.ndarray, np.ndarray]:
    roads = np.zeros((CANVAS[1], CANVAS[0]), np.uint8)
    paths = (
        ((900, 455), (960, 350), (1015, 205), (1085, 65), (1120, 0)),
        ((930, 495), (1110, 520), (1320, 505), (1536, 445)),
        ((900, 535), (1070, 660), (1240, 785), (1400, 900), (1536, 1005)),
        ((800, 570), (710, 670), (590, 780), (500, 850)),
    )
    for path in paths:
        cv2.polylines(roads, [np.asarray(path, np.int32)], False, 1, 20, cv2.LINE_AA)
    fields = _polygon(
        ((955, 575), (1120, 540), (1536, 570), (1536, 995), (1370, 925), (1160, 790))
    )
    return roads > 0, fields


def _forest_guard(source_image: Image.Image, water: np.ndarray, city: np.ndarray, port: np.ndarray) -> np.ndarray:
    water_image = Image.fromarray(water.astype(np.uint8) * 255, "L")
    city_image = Image.fromarray(city.astype(np.uint8) * 255, "L")
    port_image = Image.fromarray(port.astype(np.uint8) * 255, "L")
    try:
        zone, canopy = h8._infer_forest_masks(source_image, water_image, city_image, port_image)
        result = np.asarray(zone, np.uint8).copy() > 0
        zone.close()
        canopy.close()
        return result
    finally:
        water_image.close()
        city_image.close()
        port_image.close()


def _terrain_masks(source_image: Image.Image, source: np.ndarray, warped_h5: np.ndarray) -> dict[str, np.ndarray]:
    broad = h15._semantic_masks(source_image)
    city = broad["city"]
    port = broad["port"]
    water = _largest_blue_water(source)
    h5_water = _largest_blue_water(warped_h5)
    roads, fields = _road_and_field_guards()
    forest = _forest_guard(source_image, water, city, port)
    forbidden = water | city | port | roads | fields | forest

    triangle_core = np.zeros(water.shape, np.uint8)
    contours = h16._triangle_contours(source, broad["highland"] & ~forbidden)
    for contour in contours:
        cv2.drawContours(triangle_core, [cv2.convexHull(contour)], -1, 1, cv2.FILLED)
    highland = cv2.dilate(
        triangle_core,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)),
    )
    highland = cv2.morphologyEx(
        highland,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17)),
    ) > 0
    highland &= broad["highland"] & ~forbidden
    count, labels, stats, _ = cv2.connectedComponentsWithStats(highland.astype(np.uint8), 8)
    kept = np.zeros_like(highland)
    for label in range(1, count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= 128:
            kept |= labels == label
    highland = kept

    land_distance = cv2.distanceTransform((~water).astype(np.uint8), cv2.DIST_L2, 5)
    h5_land_distance = cv2.distanceTransform((~h5_water).astype(np.uint8), cv2.DIST_L2, 5)
    yy, xx = np.indices(water.shape)
    coast_geography = ((xx < 690) & (yy > 620)) | ((xx < 1030) & (yy > 785))
    coast = (
        (land_distance >= 9.0)
        & (land_distance <= 27.0)
        & (h5_land_distance >= 4.0)
        & coast_geography
        & ~forbidden
        & ~highland
    )
    shoreline_core = cv2.dilate(
        cv2.morphologyEx(water.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
    ) > 0
    coast &= ~shoreline_core
    return {
        "city": city,
        "port": port,
        "highland": highland,
        "coast": coast,
        "water": water,
        "shoreline_core": shoreline_core,
        "roads": roads,
        "fields": fields,
        "forest": forest,
        "triangle_core": triangle_core > 0,
    }


def _histogram_lut(source: np.ndarray, reference: np.ndarray) -> np.ndarray:
    source_hist = np.bincount(source, minlength=256).astype(np.float64)
    reference_hist = np.bincount(reference, minlength=256).astype(np.float64)
    source_cdf = np.cumsum(source_hist) / max(float(source_hist.sum()), 1.0)
    reference_cdf = np.cumsum(reference_hist) / max(float(reference_hist.sum()), 1.0)
    return np.clip(np.searchsorted(reference_cdf, source_cdf), 0, 255).astype(np.uint8)


def _local_histogram_match(moving: np.ndarray, reference: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if int(mask.sum()) < 256:
        raise H20Error("local histogram-match mask is too small")
    moving_lab = cv2.cvtColor(moving, cv2.COLOR_RGB2LAB)
    reference_lab = cv2.cvtColor(reference, cv2.COLOR_RGB2LAB)
    matched = moving_lab.copy()
    for channel in range(3):
        lut = _histogram_lut(moving_lab[..., channel][mask], reference_lab[..., channel][mask])
        matched[..., channel][mask] = lut[moving_lab[..., channel][mask]]
    return cv2.cvtColor(matched, cv2.COLOR_LAB2RGB)


def _gaussian_pyramid(array: np.ndarray, levels: int) -> list[np.ndarray]:
    result = [array.astype(np.float32)]
    for _ in range(levels):
        result.append(cv2.pyrDown(result[-1]))
    return result


def _laplacian_pyramid(array: np.ndarray, levels: int) -> list[np.ndarray]:
    gaussian = _gaussian_pyramid(array, levels)
    layers: list[np.ndarray] = []
    for index in range(levels):
        expanded = cv2.pyrUp(
            gaussian[index + 1],
            dstsize=(gaussian[index].shape[1], gaussian[index].shape[0]),
        )
        layers.append(gaussian[index] - expanded)
    layers.append(gaussian[-1])
    return layers


def _reconstruct(layers: Sequence[np.ndarray]) -> np.ndarray:
    current = layers[-1]
    for layer in reversed(layers[:-1]):
        current = cv2.pyrUp(current, dstsize=(layer.shape[1], layer.shape[0])) + layer
    return current


def _inward_alpha(mask: np.ndarray, transition_px: float) -> np.ndarray:
    distance = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    return np.clip(distance / transition_px, 0.0, 1.0).astype(np.float32)


def _spectral_composite(
    base: np.ndarray,
    sources: Sequence[np.ndarray],
    source_weights: Sequence[Sequence[float]],
    mask: np.ndarray,
    transition_px: float,
) -> np.ndarray:
    if len(source_weights) != PYRAMID_LEVELS + 1:
        raise H20Error("one spectral weight row is required for every pyramid band")
    base_layers = _laplacian_pyramid(base, PYRAMID_LEVELS)
    source_layers = [_laplacian_pyramid(source, PYRAMID_LEVELS) for source in sources]
    alpha_layers = _gaussian_pyramid(_inward_alpha(mask, transition_px), PYRAMID_LEVELS)
    output_layers: list[np.ndarray] = []
    for index, base_layer in enumerate(base_layers):
        weights = source_weights[index]
        if len(weights) != len(sources) or abs(sum(weights) - 1.0) > 1e-6:
            raise H20Error(f"invalid band weights at level {index}: {weights}")
        content = np.zeros_like(base_layer)
        for weight, layers in zip(weights, source_layers, strict=True):
            content += layers[index] * float(weight)
        alpha = alpha_layers[index][..., None]
        output_layers.append(base_layer * (1.0 - alpha) + content * alpha)
    reconstructed = np.clip(_reconstruct(output_layers), 0, 255).round().astype(np.uint8)
    result = base.copy()
    result[mask] = reconstructed[mask]
    return result


def _registered_triangle_signature(
    source: np.ndarray,
    candidate: np.ndarray,
    search: np.ndarray,
) -> dict[str, Any]:
    contours = h16._triangle_contours(source, search)

    def bandpass(image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32)
        return cv2.GaussianBlur(gray, (0, 0), 1.0) - cv2.GaussianBlur(gray, (0, 0), 4.0)

    before = bandpass(source)
    after = bandpass(candidate)
    correlations: list[float] = []
    radius = 10
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        cx, cy = x + width // 2, y + height // 2
        if cx - radius < 0 or cy - radius < 0 or cx + radius + 1 > CANVAS[0] or cy + radius + 1 > CANVAS[1]:
            continue
        old = before[cy - radius : cy + radius + 1, cx - radius : cx + radius + 1].ravel().copy()
        new = after[cy - radius : cy + radius + 1, cx - radius : cx + radius + 1].ravel().copy()
        old -= old.mean()
        new -= new.mean()
        denominator = float(np.linalg.norm(old) * np.linalg.norm(new))
        correlations.append(float(np.dot(old, new) / denominator) if denominator > 1e-6 else 1.0)
    values = np.asarray(correlations, np.float32)
    threshold = 0.40
    removed = int((values < threshold).sum())
    total = int(values.size)
    reduction = removed / max(total, 1)
    return {
        "method": "registered 21px band-pass structural correlation at locked H4 triangle centers",
        "correlation_threshold_for_material_removal": threshold,
        "targeted_h4_triangle_signatures": total,
        "materially_removed_signatures": removed,
        "reduction_fraction": round(reduction, 6),
        "median_residual_correlation": round(float(np.median(values)) if total else 1.0, 6),
    }


def _focus_strip(master: Image.Image, size: int, scale: int) -> Image.Image:
    centers = ((1260, 270), (1160, 910), (850, 490), (485, 835))
    panel_size = size * scale
    strip = Image.new("RGB", (panel_size * len(centers), panel_size), (24, 24, 22))
    for column, (cx, cy) in enumerate(centers):
        left = max(0, min(master.width - size, cx - size // 2))
        top = max(0, min(master.height - size, cy - size // 2))
        crop = master.crop((left, top, left + size, top + size))
        if scale != 1:
            resized = crop.resize((panel_size, panel_size), Image.Resampling.NEAREST)
            crop.close()
            crop = resized
        strip.paste(crop, (column * panel_size, 0))
        crop.close()
    return strip


def _review_views(
    source: Image.Image,
    master: Image.Image,
    semantic: Image.Image,
    paths: dict[str, Path],
) -> None:
    overview = master.resize((768, 512), Image.Resampling.LANCZOS)
    scale25 = master.resize((384, 256), Image.Resampling.LANCZOS)
    scale50 = master.resize((768, 512), Image.Resampling.LANCZOS)
    native = _focus_strip(master, 384, 1)
    scale200 = _focus_strip(master, 192, 2)
    scale400 = _focus_strip(master, 96, 4)
    source_overview = source.resize((768, 512), Image.Resampling.LANCZOS)
    semantic_small = semantic.resize((384, 256), Image.Resampling.NEAREST)
    diff = np.max(
        np.abs(np.asarray(master, np.int16) - np.asarray(source, np.int16)), axis=2
    )
    heat = np.zeros((CANVAS[1], CANVAS[0], 3), np.uint8)
    heat[..., 0] = np.clip(diff * 5, 0, 255).astype(np.uint8)
    heat[..., 1] = np.clip(diff, 0, 255).astype(np.uint8)
    heat_image = Image.fromarray(heat, "RGB").resize((384, 256), Image.Resampling.LANCZOS)

    contact = Image.new("RGB", (1536, 2048), (31, 29, 24))
    contact.paste(source_overview, (0, 0))
    contact.paste(overview, (768, 0))
    contact.paste(scale25, (0, 512))
    contact.paste(semantic_small, (384, 512))
    contact.paste(heat_image, (768, 512))
    contact.paste(scale25, (1152, 512))
    contact.paste(native, (0, 768))
    contact.paste(scale200, (0, 1152))
    contact.paste(scale400, (0, 1536))
    draw = ImageDraw.Draw(contact)
    font = ImageFont.load_default()
    labels = (
        ((8, 8), "H4 protected source / 50%"),
        ((776, 8), "H20 candidate / 50%"),
        ((8, 520), "H20 / 25%"),
        ((392, 520), "semantic edit mask"),
        ((776, 520), "absolute RGB difference"),
        ((1160, 520), "H20 / 25% duplicate check"),
        ((8, 776), "native: east | south | city | port"),
        ((8, 1160), "200%: east | south | city | port"),
        ((8, 1544), "400%: east | south | city | port"),
    )
    for position, label in labels:
        draw.rectangle((position[0] - 3, position[1] - 2, position[0] + 220, position[1] + 13), fill=(20, 20, 18))
        draw.text(position, label, fill=(244, 238, 213), font=font)

    overview.save(paths["overview"], **PNG)
    native.save(paths["native"], **PNG)
    scale25.save(paths["scale25"], **PNG)
    scale50.save(paths["scale50"], **PNG)
    scale200.save(paths["scale200"], **PNG)
    scale400.save(paths["scale400"], **PNG)
    contact.save(paths["contact"], **PNG)
    for image in (
        overview,
        scale25,
        scale50,
        native,
        scale200,
        scale400,
        source_overview,
        semantic_small,
        heat_image,
        contact,
    ):
        image.close()


def render(
    *,
    h4_path: Path = DEFAULT_H4,
    h5_path: Path = DEFAULT_H5,
    h9_path: Path = DEFAULT_H9,
    b1_path: Path = DEFAULT_B1,
    output_dir: Path = DEFAULT_OUTPUT_ROOT / DEFAULT_ITERATION,
    replace: bool = False,
    terrain_transition_px: float = 5.0,
    settlement_transition_px: float = 5.0,
) -> dict[str, Any]:
    output_dir = _validated_output(output_dir)
    paths = _paths(output_dir)
    if not replace and any(path.exists() for path in paths.values()):
        raise H20Error("refusing to overwrite an existing H20 iteration")
    source_image = _load_locked(h4_path, "h4")
    h5_image = _load_locked(h5_path, "h5")
    h9_image = _load_locked(h9_path, "h9")
    b1_image = _load_locked(b1_path, "b1")
    try:
        source = np.asarray(source_image, np.uint8).copy()
        h5 = np.asarray(h5_image, np.uint8).copy()
        h9 = np.asarray(h9_image, np.uint8).copy()
        homography, alignment = _estimate_alignment(source, h5)
        warped_h5 = _warp(h5, homography) if alignment["warp_required"] else h5.copy()
        warped_h9 = _warp(h9, homography) if alignment["warp_required"] else h9.copy()
        masks = _terrain_masks(source_image, source, warped_h5)
        terrain = masks["highland"] | masks["coast"]

        terrain_material = source.copy()
        for region in (masks["highland"], masks["coast"]):
            matched = _local_histogram_match(warped_h5, source, region)
            terrain_material[region] = matched[region]
        terrain_weights = (
            (0.03, 0.97),
            (0.00, 1.00),
            (0.00, 1.00),
            (0.00, 1.00),
            (0.00, 1.00),
            (0.00, 1.00),
            (0.00, 1.00),
        )
        candidate = _spectral_composite(
            source,
            (source, terrain_material),
            terrain_weights,
            terrain,
            terrain_transition_px,
        )

        flat_material = source.copy()
        ink_material = source.copy()
        for region in (masks["city"], masks["port"]):
            flat_matched = _local_histogram_match(warped_h9, source, region)
            ink_matched = _local_histogram_match(warped_h5, source, region)
            flat_material[region] = flat_matched[region]
            ink_material[region] = ink_matched[region]
        settlement_weights = (
            (0.40, 0.60, 0.00),
            (0.18, 0.82, 0.00),
            (0.05, 0.95, 0.00),
            (0.00, 1.00, 0.00),
            (0.00, 1.00, 0.00),
            (0.00, 1.00, 0.00),
            (0.00, 1.00, 0.00),
        )
        settlement = masks["city"] | masks["port"]
        candidate = _spectral_composite(
            candidate,
            (source, flat_material, ink_material),
            settlement_weights,
            settlement,
            settlement_transition_px,
        )

        # H4 is the final authority for water, shoreline, and detected network fabric.
        restore = masks["water"] | masks["shoreline_core"]
        candidate[restore] = source[restore]
        probe = Image.fromarray(candidate, "RGB")
        try:
            observed = np.asarray(h8._water_mask(probe), np.uint8) > 0
        finally:
            probe.close()
        original_observed = np.asarray(h8._water_mask(source_image), np.uint8) > 0
        classifier_displacement = (observed ^ original_observed) & ~masks["port"]
        candidate[classifier_displacement] = source[classifier_displacement]

        allowed = terrain | settlement
        changed = np.any(candidate != source, axis=2)
        violations = changed & ~allowed
        if violations.any():
            raise H20Error(f"protected-pixel violation: {int(violations.sum())}")
        edit_fraction = float(changed.mean())

        exact_guards = {
            "water": int((changed & masks["water"]).sum()),
            "shoreline_core": int((changed & masks["shoreline_core"]).sum()),
            "roads_outside_settlement": int((changed & masks["roads"] & ~settlement).sum()),
            "fields": int((changed & masks["fields"]).sum()),
            "forest": int((changed & masks["forest"]).sum()),
        }
        target_image = Image.fromarray(candidate, "RGB")
        semantic_rgb = np.zeros_like(candidate)
        semantic_rgb[masks["coast"]] = (60, 110, 190)
        semantic_rgb[masks["highland"]] = (150, 92, 175)
        semantic_rgb[masks["port"]] = (224, 154, 52)
        semantic_rgb[masks["city"]] = (202, 58, 50)
        semantic_image = Image.fromarray(semantic_rgb, "RGB")
        output_dir.mkdir(parents=True, exist_ok=True)
        target_image.save(paths["master"], **PNG)
        semantic_image.save(paths["mask"], **PNG)
        _review_views(source_image, target_image, semantic_image, paths)

        palette = h4.palette_continuity_metrics(target_image, b1_image)
        readability = h4.downsample_readability_metrics(target_image)
        boundary = h4.boundary_metrics(target_image)
        repetition = h4.exact_repetition_metrics(target_image)
        triangle_signature = _registered_triangle_signature(
            source, candidate, masks["highland"]
        )
        gates = {
            "alignment_subpixel_median": alignment["subpixel_median_verified"],
            "protected_exact": not violations.any(),
            "edit_fraction_below_25_percent": edit_fraction < 0.25,
            "water_shoreline_roads_fields_forest_exact": all(value == 0 for value in exact_guards.values()),
            "palette": palette["passed"],
            "readability": readability["passed"],
            "boundary": boundary["passed"],
            "exact_repetition": repetition["passed"],
            "registered_triangle_signature_reduction_at_least_90_percent": triangle_signature["reduction_fraction"] >= 0.90,
            "flat_city_port_source": True,
            "pyramid_at_least_five_bands": PYRAMID_LEVELS >= 5,
        }
        report: dict[str, Any] = {
            "schema_version": "1.0.0",
            "id": "style-candidate-h-v20-multiband-flat-plan-automated",
            "status": "iteration_2_automated_pass_pending_author_vision" if all(gates.values()) else "iteration_2_failed_automated",
            "golden_reference": False,
            "inputs": {
                "h4_protected_base": _artifact(h4_path),
                "h5_registered_flat_terrain_and_ink": _artifact(h5_path),
                "h9_registered_flat_city_port_topology": _artifact(h9_path),
                "b1_gate_reference": _artifact(b1_path),
            },
            "single_change": "registered H5 low/mid terrain plus H9 flat city/port topology through six-level inward multiband masks",
            "alignment": alignment,
            "multiband_contract": {
                "laplacian_levels": PYRAMID_LEVELS,
                "bands_including_residual": PYRAMID_LEVELS + 1,
                "terrain_band_weights_h4_h5": terrain_weights,
                "settlement_band_weights_h4_h9_h5": settlement_weights,
                "terrain_inward_transition_px": terrain_transition_px,
                "settlement_inward_transition_px": settlement_transition_px,
                "procedural_hachures_added": 0,
            },
            "full_resolution_protection": {
                "canvas_pixels": CANVAS[0] * CANVAS[1],
                "allowed_edit_pixels": int(allowed.sum()),
                "changed_pixels": int(changed.sum()),
                "changed_fraction": round(edit_fraction, 8),
                "changed_percent": round(edit_fraction * 100.0, 6),
                "protected_pixels": int((~allowed).sum()),
                "protected_violation_pixels": int(violations.sum()),
                "exact_guard_changed_pixels": exact_guards,
                "shoreline_classifier_displacement_pixels_outside_port": int(
                    ((np.asarray(h8._water_mask(target_image), np.uint8) > 0) ^ original_observed)[~masks["port"]].sum()
                ),
            },
            "semantic_masks": {
                "path": _rel(paths["mask"]),
                "counts": {
                    name: int(masks[name].sum())
                    for name in ("city", "port", "highland", "coast", "water", "shoreline_core")
                },
                "highland_connected_regions": int(
                    cv2.connectedComponents(masks["highland"].astype(np.uint8), 8)[0] - 1
                ),
            },
            "perspective_proxy": triangle_signature,
            "automated_metrics": {
                "palette": palette,
                "readability": readability,
                "boundary": boundary,
                "exact_repetition": repetition,
            },
            "gate_status": gates,
            "self_vision_review": {
                "status": "pending",
                "acceptance_authority": False,
                "reviewed_views": [],
                "immediate_failure_detected": None,
                "decision": "inspect overview/native/25/50/200/400 views before any promotion",
            },
            "outputs": {name: _artifact(path) for name, path in paths.items() if name != "report"},
        }
        paths["report"].write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return report
    finally:
        source_image.close()
        h5_image.close()
        h9_image.close()
        b1_image.close()
        for name in ("target_image", "semantic_image"):
            value = locals().get(name)
            if isinstance(value, Image.Image):
                value.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / DEFAULT_ITERATION)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--terrain-transition-px", type=float, default=5.0)
    parser.add_argument("--settlement-transition-px", type=float, default=5.0)
    args = parser.parse_args(argv)
    try:
        report = render(
            output_dir=args.output_dir,
            replace=args.replace,
            terrain_transition_px=args.terrain_transition_px,
            settlement_transition_px=args.settlement_transition_px,
        )
    except (H20Error, OSError, ValueError, cv2.error) as exc:
        print(f"H20 render failed: {exc}")
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "master": report["outputs"]["master"],
                "gates": report["gate_status"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if all(report["gate_status"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
