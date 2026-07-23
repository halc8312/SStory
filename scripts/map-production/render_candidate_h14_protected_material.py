#!/usr/bin/env python3
"""Render the deterministic H14 protected-material prototype.

H14 keeps Candidate H9 as the sole geometry authority.  H11 and Candidate B1
are read only as whole-image colour populations; their pixels are never sampled
by coordinate.  Forest material is synthesized from the approved connected-
forest atlas crop with random phase, so it has the crop's frequency vocabulary
without copying or repeating its semantic drawing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image

import audit_style_candidate_h4 as h4
import render_candidate_h9_dense_flat_plan as h9


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_H9 = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-h-v9-dense-flat-plan.png"
)
DEFAULT_ATLAS = (
    REPO_ROOT
    / "world/map-production/style-assets/phase5-cartographic-material-atlas-v1.png"
)
DEFAULT_H11 = (
    REPO_ROOT
    / "tmp/map-production/h11-prototype/"
    "style-candidate-h-v11-colour-calibration-raw.png"
)
DEFAULT_B1 = REPO_ROOT / "world/map-production/candidates/style-candidate-b-v1.png"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "tmp/map-production/h14-prototype"

LOCKED_SHA256 = {
    "h9_geometry_authority": (
        "bd813e93287b15fe12e654ca5d28633a6902bbbdb3c6d81b0c3e69816a7b2580"
    ),
    "atlas_material_source": (
        "9b42dcce48d275d392bc28235925ac02f37690ace3418d6cb65920f4da05c6e3"
    ),
    "h11_palette_population": (
        "32175b57fa82891045a3f8ffa70c3da134b33e38a790db62b14d11c0256cda75"
    ),
    "b1_palette_gate_reference": (
        "4d505def78acc752ee2611cb73d112cc9a3048f611cb05233274a1eb2ae42003"
    ),
}

CANVAS = (1536, 1024)
SEED = 0x4831345F4541
GENERATOR_ID = "sstory-map-production/render_candidate_h14_protected_material.py@1"
ATLAS_FOREST_CROP = (24, 24, 472, 472)

MASTER_NAME = "style-candidate-h-v14-protected-material.png"
MASK_NAME = "style-candidate-h-v14-protected-material.semantic-mask.png"
OVERVIEW_NAME = "style-candidate-h-v14-protected-material.overview.png"
NATIVE_NAME = "style-candidate-h-v14-protected-material.native-review.png"
ZOOM_200_NAME = "style-candidate-h-v14-protected-material.200-review.png"
ZOOM_400_NAME = "style-candidate-h-v14-protected-material.400-review.png"
CONTACT_NAME = "style-candidate-h-v14-protected-material.contact-sheet.png"
REPORT_NAME = "style-candidate-h-v14-protected-material.provenance.json"

PNG_OPTIONS = {"format": "PNG", "optimize": False, "compress_level": 9}
MASK_COLORS = {
    "protected_from_forest_edit": (0, 0, 0),
    "removed_round_canopy_only": (202, 58, 50),
    "new_connected_canopy_only": (58, 126, 68),
    "removed_and_replaced_canopy": (224, 154, 52),
}


class H14RenderError(ValueError):
    """Raised when a locked H14 input or invariant is invalid."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": _relative(path),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _load_locked(path: Path, expected_sha256: str, label: str) -> Image.Image:
    if not path.is_file():
        raise H14RenderError(f"{label} is missing: {path}")
    actual = _sha256(path)
    if actual != expected_sha256:
        raise H14RenderError(
            f"{label} SHA-256 mismatch: expected {expected_sha256}, got {actual}"
        )
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    if image.size != CANVAS:
        image.close()
        raise H14RenderError(f"{label} must be {CANVAS[0]}x{CANVAS[1]}")
    return image


def _output_paths(output_dir: Path) -> dict[str, Path]:
    resolved = output_dir.resolve()
    root = DEFAULT_OUTPUT_ROOT.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise H14RenderError(
            f"H14 preview outputs must stay under {_relative(root)}"
        ) from exc
    return {
        "master": resolved / MASTER_NAME,
        "semantic_mask": resolved / MASK_NAME,
        "overview": resolved / OVERVIEW_NAME,
        "native_review": resolved / NATIVE_NAME,
        "zoom_200_review": resolved / ZOOM_200_NAME,
        "zoom_400_review": resolved / ZOOM_400_NAME,
        "contact_sheet": resolved / CONTACT_NAME,
        "provenance": resolved / REPORT_NAME,
    }


def _rgb_covariance_transfer(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Apply a coordinate-free RGB population transform.

    This is a 3x3 covariance/mean LUT target, not a coordinate composite.  It
    cannot carry H11 roads, coastlines, settlements, or relief geometry.
    """

    source_pixels = source.reshape(-1, 3).astype(np.float64)
    target_pixels = target.reshape(-1, 3).astype(np.float64)
    source_mean = source_pixels.mean(axis=0)
    target_mean = target_pixels.mean(axis=0)
    source_covariance = np.cov(source_pixels, rowvar=False)
    target_covariance = np.cov(target_pixels, rowvar=False)

    def matrix_power(matrix: np.ndarray, exponent: float) -> np.ndarray:
        values, vectors = np.linalg.eigh(matrix)
        powered = np.power(np.clip(values, 1e-8, None), exponent)
        return (vectors * powered) @ vectors.T

    transform = matrix_power(source_covariance, -0.5) @ matrix_power(
        target_covariance, 0.5
    )
    transferred = (source_pixels - source_mean) @ transform + target_mean
    return np.clip(transferred, 0.0, 255.0).reshape(source.shape).astype(np.float32)


def _palette_population_sorted(image: Image.Image) -> np.ndarray:
    """Return a coordinate-free 384x256 palette population sorted by RGB."""

    sample = np.asarray(
        image.resize((384, 256), Image.Resampling.LANCZOS), dtype=np.uint8
    ).reshape(-1, 3)
    order = np.lexsort((sample[:, 2], sample[:, 1], sample[:, 0]))
    return sample[order]


def _calibration_provenance(
    source: np.ndarray,
    h11_target: np.ndarray,
    h11: Image.Image,
    b1: Image.Image,
) -> dict[str, Any]:
    source_pixels = source.reshape(-1, 3).astype(np.float64)
    target_pixels = h11_target.reshape(-1, 3).astype(np.float64)
    return {
        "method": "coordinate-free RGB mean/covariance population transform",
        "source_mean_rgb": source_pixels.mean(axis=0).round(6).tolist(),
        "target_mean_rgb": target_pixels.mean(axis=0).round(6).tolist(),
        "source_covariance_rgb": np.cov(source_pixels, rowvar=False).round(6).tolist(),
        "target_covariance_rgb": np.cov(target_pixels, rowvar=False).round(6).tolist(),
        "h11_sorted_palette_population_sha256": hashlib.sha256(
            _palette_population_sorted(h11).tobytes()
        ).hexdigest(),
        "b1_sorted_palette_population_sha256": hashlib.sha256(
            _palette_population_sorted(b1).tobytes()
        ).hexdigest(),
        "h11_or_b1_coordinate_sampling_used": False,
        "semantic_geometry_transfer_possible": False,
    }


def _forest_masks(source: Image.Image) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Detect H9 round canopy and construct the protected forest-edit zone."""

    source_array = np.asarray(source, dtype=np.uint8)
    red = source_array[..., 0]
    green = source_array[..., 1]
    blue = source_array[..., 2]
    canopy = (
        (red >= 65)
        & (red <= 150)
        & (green >= 70)
        & (green <= 150)
        & (blue >= 35)
        & (blue <= 105)
        & (green.astype(np.int16) >= blue.astype(np.int16) + 18)
        & (np.abs(red.astype(np.int16) - green.astype(np.int16)) <= 31)
    )

    water_image = h9.h8._water_mask(source)
    city_image = h9._city_mask()
    port_image = h9._port_mask()
    manual_image = h9.h8._manual_protection_mask()
    envelope_image = h9.h8._forest_envelope_mask()
    try:
        water = np.asarray(water_image, dtype=np.uint8) > 0
        city = np.asarray(city_image, dtype=np.uint8) > 0
        port = np.asarray(port_image, dtype=np.uint8) > 0
        manual = np.asarray(manual_image, dtype=np.uint8) > 0
        envelope = np.asarray(envelope_image, dtype=np.uint8) > 0
    finally:
        water_image.close()
        city_image.close()
        port_image.close()
        manual_image.close()
        envelope_image.close()

    expanded_water = cv2.dilate(water.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    exclusion = expanded_water | city | port | manual
    zone = envelope & ~exclusion
    detected = canopy & zone
    return detected, zone, exclusion


def _random_phase_texture(atlas: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Synthesize nonperiodic atlas-spectrum RGB residuals at EA coordinates."""

    left, top, right, bottom = ATLAS_FOREST_CROP
    patch = atlas[top:bottom, left:right].astype(np.float32)
    height, width = shape
    rng = np.random.default_rng(SEED)
    common_phase = rng.uniform(-math.pi, math.pi, size=(height, width))
    result = np.empty((height, width, 3), dtype=np.float32)
    for channel in range(3):
        channel_patch = patch[..., channel]
        low = cv2.GaussianBlur(channel_patch, (0, 0), sigmaX=3.2, sigmaY=3.2)
        high = channel_patch - low
        amplitude = np.abs(np.fft.fftshift(np.fft.fft2(high)))
        amplitude = cv2.resize(amplitude, (width, height), interpolation=cv2.INTER_LINEAR)
        phase = common_phase + rng.normal(0.0, 0.07, size=(height, width))
        spectrum = np.fft.ifftshift(amplitude * np.exp(1j * phase))
        synthesized = np.fft.ifft2(spectrum).real
        median = np.median(synthesized)
        deviation = np.percentile(np.abs(synthesized - median), 84.13)
        result[..., channel] = (synthesized - median) / max(float(deviation), 1e-6)
    # Retain the atlas crop's channel covariance while constraining outliers.
    return np.clip(result, -3.0, 3.0)


def _remove_small_components(mask: np.ndarray, minimum_area: int) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    keep = np.zeros(count, dtype=np.uint8)
    if count > 1:
        keep[1:] = (stats[1:, cv2.CC_STAT_AREA] >= minimum_area).astype(np.uint8)
    return keep[labels] > 0


def _irregular_connected_canopy(
    detected: np.ndarray,
    zone: np.ndarray,
    atlas_texture: np.ndarray,
) -> np.ndarray:
    height, width = detected.shape
    rng = np.random.default_rng(SEED ^ 0x43414E4F5059)
    density_near = cv2.GaussianBlur(
        detected.astype(np.float32), (0, 0), sigmaX=11.0, sigmaY=11.0
    )
    density_far = cv2.GaussianBlur(
        detected.astype(np.float32), (0, 0), sigmaX=34.0, sigmaY=34.0
    )
    white = rng.normal(0.0, 1.0, size=(height, width)).astype(np.float32)
    low = cv2.GaussianBlur(white, (0, 0), sigmaX=31.0, sigmaY=31.0)
    mid = cv2.GaussianBlur(white, (0, 0), sigmaX=8.0, sigmaY=8.0)
    low /= max(float(low.std()), 1e-6)
    mid /= max(float(mid.std()), 1e-6)
    etched = cv2.GaussianBlur(atlas_texture.mean(axis=2), (0, 0), sigmaX=4.0)
    etched /= max(float(etched.std()), 1e-6)
    field = density_near * 0.72 + density_far * 0.58 + low * 0.075 + mid * 0.035
    field += etched * 0.018
    occupancy = (field > 0.235) & zone
    occupancy = _remove_small_components(occupancy, minimum_area=180)
    # A noncircular cross close joins narrow gaps without stamping round kernels.
    cross = np.array(
        [[0, 0, 1, 0, 0], [0, 0, 1, 0, 0], [1, 1, 1, 1, 1],
         [0, 0, 1, 0, 0], [0, 0, 1, 0, 0]],
        dtype=np.uint8,
    )
    occupancy = cv2.morphologyEx(
        occupancy.astype(np.uint8), cv2.MORPH_CLOSE, cross, iterations=1
    ) > 0
    occupancy &= zone
    return _remove_small_components(occupancy, minimum_area=220)


def _forest_composite(
    calibrated: np.ndarray,
    detected: np.ndarray,
    occupancy: np.ndarray,
    zone: np.ndarray,
    atlas_texture: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Erase circular H9 crowns and install flat connected etched material."""

    source_u8 = np.clip(calibrated, 0, 255).round().astype(np.uint8)
    erase = cv2.dilate(detected.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    erase &= zone
    inpainted = cv2.inpaint(
        cv2.cvtColor(source_u8, cv2.COLOR_RGB2BGR),
        (erase.astype(np.uint8) * 255),
        7.0,
        cv2.INPAINT_TELEA,
    )
    ground = cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB).astype(np.float32)
    ground_low = cv2.GaussianBlur(ground, (0, 0), sigmaX=2.4, sigmaY=2.4)
    ground_material = ground_low + atlas_texture * np.array([2.8, 2.5, 1.9])

    # Flat copperplate canopy: local ground colour shifted toward the approved
    # atlas forest population, with signed high-frequency residuals only.
    canopy_material = ground_low.copy()
    canopy_material[..., 0] -= 23.0
    canopy_material[..., 1] -= 20.0
    canopy_material[..., 2] -= 17.0
    canopy_material += atlas_texture * np.array([8.2, 7.4, 5.8])

    # Two crossed derivative plates create direction-neutral engraved linework.
    texture_gray = atlas_texture.mean(axis=2)
    grad_x = cv2.Sobel(texture_gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(texture_gray, cv2.CV_32F, 0, 1, ksize=3)
    etched_lines = np.tanh((np.abs(grad_x) + np.abs(grad_y)) * 0.42)
    canopy_material -= etched_lines[..., None] * np.array([10.0, 9.0, 7.0])

    output = calibrated.copy()
    output[erase] = ground_material[erase]
    feather = cv2.GaussianBlur(
        occupancy.astype(np.float32), (0, 0), sigmaX=0.85, sigmaY=0.85
    )
    feather *= occupancy.astype(np.float32)
    feather = feather[..., None]
    blended = output * (1.0 - feather) + canopy_material * feather
    output[occupancy] = blended[occupancy]
    return np.clip(output, 0, 255), erase


def _semantic_mask(erase: np.ndarray, occupancy: np.ndarray) -> Image.Image:
    result = np.zeros((CANVAS[1], CANVAS[0], 3), dtype=np.uint8)
    removed_only = erase & ~occupancy
    new_only = occupancy & ~erase
    overlap = erase & occupancy
    result[removed_only] = MASK_COLORS["removed_round_canopy_only"]
    result[new_only] = MASK_COLORS["new_connected_canopy_only"]
    result[overlap] = MASK_COLORS["removed_and_replaced_canopy"]
    return Image.fromarray(result, "RGB")


def _exact_forest_edit_protection(
    calibrated: np.ndarray,
    candidate: np.ndarray,
    allowed: np.ndarray,
) -> dict[str, Any]:
    changed = np.any(
        np.clip(calibrated, 0, 255).round().astype(np.uint8) != candidate,
        axis=2,
    )
    violations = changed & ~allowed
    protected_pixels = int((~allowed).sum())
    violation_pixels = int(violations.sum())
    if violation_pixels:
        raise H14RenderError(
            f"forest edit changed {violation_pixels} protected calibrated pixels"
        )
    return {
        "comparison": "exact full-resolution RGB tuple equality after palette stage",
        "canvas_pixels": CANVAS[0] * CANVAS[1],
        "allowed_forest_edit_pixels": int(allowed.sum()),
        "protected_pixels": protected_pixels,
        "protected_equal_pixels": protected_pixels,
        "protected_violation_pixels": 0,
        "protected_pixel_equality_percent": 100.0,
        "changed_pixels": int(changed.sum()),
    }


def _component_metrics(mask: np.ndarray) -> dict[str, Any]:
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    areas = stats[1:, cv2.CC_STAT_AREA].astype(int).tolist() if count > 1 else []
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    circularities: list[tuple[float, float]] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        perimeter = float(cv2.arcLength(contour, True))
        if area >= 8.0 and perimeter > 0.0:
            circularities.append((min(1.0, 4.0 * math.pi * area / perimeter**2), area))
    total_area = sum(area for _circularity, area in circularities)
    weighted = (
        sum(circularity * area for circularity, area in circularities) / total_area
        if total_area
        else 0.0
    )
    round_count = sum(
        1
        for circularity, area in circularities
        if 8.0 <= area <= 500.0 and circularity >= 0.52
    )
    return {
        "component_count": len(areas),
        "component_pixels": int(sum(areas)),
        "largest_component_pixels": max(areas, default=0),
        "area_weighted_circularity": round(weighted, 6),
        "round_stamp_like_components": round_count,
    }


def _autocorrelation_metrics(
    image: np.ndarray, mask: np.ndarray
) -> dict[str, Any]:
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32)
    high = gray - cv2.GaussianBlur(gray, (0, 0), sigmaX=4.0, sigmaY=4.0)
    records: list[dict[str, Any]] = []
    for dx, dy in (
        (32, 0), (0, 32), (64, 0), (0, 64), (128, 0), (0, 128),
        (256, 0), (0, 256), (64, 64), (128, 128),
    ):
        left = high[max(0, dy): high.shape[0], max(0, dx): high.shape[1]]
        right = high[: high.shape[0] - dy, : high.shape[1] - dx]
        active = mask[max(0, dy): mask.shape[0], max(0, dx): mask.shape[1]]
        active &= mask[: mask.shape[0] - dy, : mask.shape[1] - dx]
        left_values = left[active]
        right_values = right[active]
        if left_values.size < 1024 or left_values.std() < 1e-6 or right_values.std() < 1e-6:
            correlation = 0.0
        else:
            correlation = float(np.corrcoef(left_values, right_values)[0, 1])
        records.append({"lag_px": [dx, dy], "correlation": round(correlation, 6)})
    maximum = max(abs(record["correlation"]) for record in records)
    return {
        "method": "masked high-pass Pearson autocorrelation",
        "maximum_absolute_correlation": round(maximum, 6),
        "lags": records,
    }


def _crop_review(
    master: Image.Image, center: tuple[int, int], zoom: int
) -> Image.Image:
    display = (768, 512)
    source_width = display[0] // zoom
    source_height = display[1] // zoom
    left = max(0, min(master.width - source_width, center[0] - source_width // 2))
    top = max(0, min(master.height - source_height, center[1] - source_height // 2))
    crop = master.crop((left, top, left + source_width, top + source_height))
    if zoom == 1:
        return crop
    review = crop.resize(display, Image.Resampling.NEAREST)
    crop.close()
    return review


def _review_artifacts(master: Image.Image) -> dict[str, Image.Image]:
    overview = master.resize((768, 512), Image.Resampling.LANCZOS)
    center = (680, 225)
    native = _crop_review(master, center, 1)
    zoom_200 = _crop_review(master, center, 2)
    zoom_400 = _crop_review(master, center, 4)
    contact = Image.new("RGB", (1552, 1056), (117, 103, 76))
    contact.paste(overview, (8, 8))
    contact.paste(native, (776, 8))
    contact.paste(zoom_200, (8, 536))
    contact.paste(zoom_400, (776, 536))
    return {
        "overview": overview,
        "native_review": native,
        "zoom_200_review": zoom_200,
        "zoom_400_review": zoom_400,
        "contact_sheet": contact,
    }


def _metric_bundle(candidate: Image.Image, b1: Image.Image) -> dict[str, Any]:
    return {
        "palette_continuity_b1": h4.palette_continuity_metrics(candidate, b1),
        "downsample_readability": h4.downsample_readability_metrics(candidate),
        "boundary": h4.boundary_metrics(candidate),
        "exact_repetition": h4.exact_repetition_metrics(candidate),
    }


def render(
    *,
    h9_path: Path = DEFAULT_H9,
    atlas_path: Path = DEFAULT_ATLAS,
    h11_path: Path = DEFAULT_H11,
    b1_path: Path = DEFAULT_B1,
    output_dir: Path = DEFAULT_OUTPUT_ROOT,
    replace: bool = False,
) -> dict[str, Any]:
    paths = _output_paths(output_dir)
    occupied = [path for path in paths.values() if path.exists()]
    if occupied and not replace:
        raise H14RenderError(
            "refusing to overwrite: " + ", ".join(_relative(path) for path in occupied)
        )

    source = _load_locked(h9_path, LOCKED_SHA256["h9_geometry_authority"], "H9")
    atlas = _load_locked(
        atlas_path, LOCKED_SHA256["atlas_material_source"], "material atlas"
    )
    h11 = _load_locked(
        h11_path, LOCKED_SHA256["h11_palette_population"], "H11 palette source"
    )
    b1 = _load_locked(
        b1_path, LOCKED_SHA256["b1_palette_gate_reference"], "B1 reference"
    )
    try:
        source_array = np.asarray(source, dtype=np.uint8)
        h11_array = np.asarray(h11, dtype=np.uint8)
        atlas_array = np.asarray(atlas, dtype=np.uint8)
        calibrated = _rgb_covariance_transfer(source_array, h11_array)
        calibration = _calibration_provenance(source_array, h11_array, h11, b1)
        detected, zone, exclusion = _forest_masks(source)
        atlas_texture = _random_phase_texture(
            atlas_array, (source.height, source.width)
        )
        occupancy = _irregular_connected_canopy(detected, zone, atlas_texture)
        composited, erase = _forest_composite(
            calibrated, detected, occupancy, zone, atlas_texture
        )

        # H9's authored city and port remain literally unchanged.  This also
        # demonstrates that the material operation never needs H11 geometry.
        city_image = h9._city_mask()
        port_image = h9._port_mask()
        try:
            city = np.asarray(city_image, dtype=np.uint8).copy() > 0
            port = np.asarray(port_image, dtype=np.uint8).copy() > 0
        finally:
            city_image.close()
            port_image.close()
        composited[city | port] = source_array[city | port]

        candidate_array = np.clip(composited, 0, 255).round().astype(np.uint8)
        allowed = erase | occupancy
        allowed &= ~(city | port | exclusion)
        # Because city/port/exclusion do not intersect the synthesized edit,
        # the post-calibration protection comparison is exact outside allowed.
        forest_protection = _exact_forest_edit_protection(
            np.where((city | port)[..., None], source_array, calibrated),
            candidate_array,
            allowed,
        )
        semantic = _semantic_mask(erase & allowed, occupancy & allowed)
        candidate = Image.fromarray(candidate_array, "RGB")
        reviews = _review_artifacts(candidate)
        before_components = _component_metrics(detected)
        after_components = _component_metrics(occupancy)
        before_autocorrelation = _autocorrelation_metrics(source_array, detected)
        after_autocorrelation = _autocorrelation_metrics(candidate_array, occupancy)
        gates = _metric_bundle(candidate, b1)

        gate_status = {
            "palette_continuity_b1": gates["palette_continuity_b1"]["passed"],
            "downsample_readability": gates["downsample_readability"]["passed"],
            "boundary": gates["boundary"]["passed"],
            "exact_repetition": gates["exact_repetition"]["passed"],
            "forest_edit_full_resolution_protection": forest_protection[
                "protected_violation_pixels"
            ]
            == 0,
            "round_stamp_component_reduction": after_components[
                "round_stamp_like_components"
            ]
            <= before_components["round_stamp_like_components"] * 0.35,
            "component_circularity_reduction": after_components[
                "area_weighted_circularity"
            ]
            <= before_components["area_weighted_circularity"] * 0.75,
        }

        for path in paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        candidate.save(paths["master"], **PNG_OPTIONS)
        semantic.save(paths["semantic_mask"], **PNG_OPTIONS)
        for key, review in reviews.items():
            review.save(paths[key], **PNG_OPTIONS)

        mask_array = np.asarray(semantic, dtype=np.uint8)
        mask_counts = {
            name: int(np.all(mask_array == color, axis=2).sum())
            for name, color in MASK_COLORS.items()
        }
        circularity_reduction = 100.0 * (
            before_components["area_weighted_circularity"]
            - after_components["area_weighted_circularity"]
        ) / max(before_components["area_weighted_circularity"], 1e-9)
        round_reduction = 100.0 * (
            before_components["round_stamp_like_components"]
            - after_components["round_stamp_like_components"]
        ) / max(before_components["round_stamp_like_components"], 1)

        report: dict[str, Any] = {
            "schema_version": "1.0.0",
            "id": "style-candidate-h-v14-protected-material-provenance",
            "status": "preview_rejected_automated_and_author_vision",
            "golden_reference": False,
            "generated_by": {"id": GENERATOR_ID, **_artifact(Path(__file__))},
            "inputs": {
                "h9_geometry_authority": _artifact(h9_path),
                "atlas_material_source": _artifact(atlas_path),
                "atlas_connected_forest_crop_px": list(ATLAS_FOREST_CROP),
                "h11_palette_population_only": _artifact(h11_path),
                "b1_fixed_palette_qa_reference_only": _artifact(b1_path),
            },
            "single_root_change": (
                "replace H9 washed/repetitive forest material vocabulary with "
                "nonrepeating flat copperplate material"
            ),
            "geometry_contract": {
                "geometry_authority": "H9 only",
                "resampling_or_coordinate_warp_of_h9": False,
                "h11_or_b1_semantic_geometry_copied": False,
                "coast_river_road_city_port_field_highland_edges_moved": False,
                "city_and_port_restored_byte_identical_to_h9": True,
                "forest_edit_excludes_water_routes_city_port_fields_highland": True,
            },
            "palette_calibration": calibration,
            "material_synthesis": {
                "method": "atlas Fourier magnitude plus EA-seeded random phase",
                "periodic_tiling_used": False,
                "grid_or_stamp_placement_used": False,
                "circle_diamond_triangle_tree_glyphs_added": False,
                "global_hue_shift_only": False,
                "atlas_high_frequency_source_crop_px": list(ATLAS_FOREST_CROP),
                "seed": SEED,
            },
            "semantic_mask": {
                "path": _relative(paths["semantic_mask"]),
                "colors": {name: list(color) for name, color in MASK_COLORS.items()},
                "full_resolution_counts": mask_counts,
            },
            "full_resolution_forest_edit_protection": forest_protection,
            "forest_shape_metrics": {
                "before_h9_detected_canopy": before_components,
                "after_h14_connected_canopy": after_components,
                "area_weighted_circularity_reduction_percent": round(
                    circularity_reduction, 6
                ),
                "round_stamp_like_component_reduction_percent": round(
                    round_reduction, 6
                ),
                "before_autocorrelation": before_autocorrelation,
                "after_autocorrelation": after_autocorrelation,
            },
            "unchanged_h4_absolute_thresholds": {
                "minimum_rgb_histogram_intersection": h4.MIN_RGB_HISTOGRAM_INTERSECTION,
                "minimum_hsv_histogram_intersection": h4.MIN_HSV_HISTOGRAM_INTERSECTION,
                "minimum_rgb_bhattacharyya": h4.MIN_RGB_BHATTACHARYYA,
                "maximum_mean_channel_delta": h4.MAX_MEAN_CHANNEL_DELTA,
                "minimum_25_percent_macrocoverage": h4.DOWNSAMPLE_THRESHOLDS[0.25][
                    "minimum_macrocell_contrast_coverage"
                ],
            },
            "automated_metrics": gates,
            "automated_gate_status": gate_status,
            "self_vision_review": {
                "status": "rejected_immediate_failure",
                "acceptance_authority": False,
                "independent_review_required": False,
                "reviewed_views": ["overview", "native", "200_percent", "400_percent"],
                "score": 28,
                "minimum_score": 94,
                "immediate_failure_detected": True,
                "findings": [
                    "Large muddy planar blobs cover the northern forest and southwest land.",
                    "Polygon-like feather seams remain visible at forest boundaries.",
                    "River-adjacent masking creates conspicuous edge bands.",
                    "Connected canopy interiors lose the atlas's legible copperplate detail.",
                    "The overview, native, 200%, and 400% views are all visually worse than H9.",
                ],
                "decision": "do_not_promote_or_request_independent_acceptance_review",
            },
            "outputs": {},
        }
        for key, path in paths.items():
            if key == "provenance":
                continue
            record = _artifact(path)
            with Image.open(path) as opened:
                record.update(
                    {"width": opened.width, "height": opened.height, "mode": opened.mode}
                )
            report["outputs"][key] = record
        paths["provenance"].write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return report
    finally:
        source.close()
        atlas.close()
        h11.close()
        b1.close()
        for local_name in ("semantic", "candidate"):
            local = locals().get(local_name)
            if isinstance(local, Image.Image):
                local.close()
        for review in locals().get("reviews", {}).values():
            review.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h9", type=Path, default=DEFAULT_H9)
    parser.add_argument("--atlas", type=Path, default=DEFAULT_ATLAS)
    parser.add_argument("--h11", type=Path, default=DEFAULT_H11)
    parser.add_argument("--b1", type=Path, default=DEFAULT_B1)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = render(
            h9_path=args.h9.resolve(),
            atlas_path=args.atlas.resolve(),
            h11_path=args.h11.resolve(),
            b1_path=args.b1.resolve(),
            output_dir=args.output_dir.resolve(),
            replace=args.replace,
        )
    except (H14RenderError, OSError, ValueError) as exc:
        print(f"Candidate H14 could not render: {exc}")
        return 2
    metrics = report["automated_metrics"]["palette_continuity_b1"]
    print(
        f"Candidate H14 {report['status']}: "
        f"sha256={report['outputs']['master']['sha256']} "
        f"RGB={metrics['rgb_histogram_intersection']} "
        f"HSV={metrics['hsv_histogram_intersection']}"
    )
    return 0 if all(report["automated_gate_status"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
