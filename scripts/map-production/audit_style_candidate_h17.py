#!/usr/bin/env python3
"""Formalize and audit H17 without claiming Vision or Golden acceptance.

The H4/B1 raster gates are imported unchanged.  Extra composition and
near-repetition measurements are deterministic proxies only; plan-view,
semantic repetition, pseudo-text, and artistic quality remain Vision work.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import audit_style_candidate_h4 as h4


REPO_ROOT = Path(__file__).resolve().parents[2]
JOB_ID = "style-candidate-h-v17-surgical-flattening"
RAW = REPO_ROOT / f"world/map-production/candidates/{JOB_ID}-raw.png"
FINAL = REPO_ROOT / f"world/map-production/candidates/{JOB_ID}.png"
PROMPT = REPO_ROOT / f"world/map-production/prompts/{JOB_ID}.generation.txt"
RECEIPT = (
    REPO_ROOT / f"world/map-production/prompts/{JOB_ID}.generation-receipt.json"
)
H4_REFERENCE = h4.DEFAULT_FINAL
B1_REFERENCE = h4.DEFAULT_REFERENCE_B1
VISION_SCHEMA = h4.DEFAULT_VISION_SCHEMA
REPORT = REPO_ROOT / f"world/map-production/qa/automated/{JOB_ID}.json"
CONTACT = (
    REPO_ROOT
    / f"tmp/map-production/h17-review/{JOB_ID}.comprehensive-contact-sheet.png"
)

EXPECTED_SHA256 = {
    "raw": "5eeee266f37ab418a4b136a6d66e67ccfe9268fa04a18cf7e96323e9b7d1506f",
    "final": "5eeee266f37ab418a4b136a6d66e67ccfe9268fa04a18cf7e96323e9b7d1506f",
    "prompt": "22810c74583192b5fb97d74e038984913a22ab387c5c24bc15b255e1a4f6a7ac",
    "receipt": "ea5ba288427c3fd55411c987bb8899dff2e0b5e91cb6175420883c7a3fc8d5a3",
    "h4": h4.EXPECTED_SHA256["final"],
    "b1": h4.EXPECTED_SHA256["reference_b1"],
    "vision_schema": h4.EXPECTED_SHA256["vision_schema"],
}
EXPECTED_FAILED_GATES = (
    "palette_continuity_with_b1",
    "downsample_readability_proxy",
)

COMPOSITION_THRESHOLDS = {
    "minimum_quarter_scale_ssim": 0.65,
    "minimum_sigma4_ssim": 0.93,
    "minimum_region_quarter_scale_ssim": 0.60,
    "minimum_good_sift_matches": 30,
    "minimum_ransac_inlier_ratio": 0.80,
    "maximum_median_inlier_displacement_px": 3.0,
    "maximum_p95_inlier_displacement_px": 6.0,
    "minimum_inlier_grid_coverage": 0.15,
    "maximum_homography_corner_displacement_px": 5.0,
    "minimum_edge_precision": 0.85,
    "minimum_edge_recall": 0.65,
    "minimum_edge_f1": 0.75,
}

COMPOSITION_REGIONS = {
    "forest": (400, 0, 1000, 360),
    "river_delta": (180, 150, 680, 720),
    "farmland": (980, 570, 1536, 940),
    "open_sea": (0, 0, 330, 1024),
    "north_river": (650, 0, 900, 400),
    "west_road_corridor": (500, 500, 900, 900),
}

FOCUS_REGIONS = {
    "capital": (690, 350, 1030, 670),
    "port": (360, 710, 700, 980),
    "east_highland": (960, 0, 1536, 550),
    "south_highland": (800, 780, 1536, 1024),
    "coast_and_delta": (120, 80, 650, 760),
    "forest": (380, 0, 1000, 400),
}


class H17AuditError(ValueError):
    """Raised when locked H17 evidence cannot be reproduced safely."""


def _assert_input(path: Path, expected: str, label: str) -> None:
    try:
        h4._assert_input(path, expected, label)
    except h4.H4AuditError as exc:
        raise H17AuditError(str(exc)) from exc


def _repo_path(value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or "\\" in value or ":" in value or ".." in pure.parts:
        raise H17AuditError(f"receipt path must be repo-relative: {value!r}")
    return REPO_ROOT.joinpath(*pure.parts)


def materialize_review_candidate(
    raw_path: Path = RAW,
    final_path: Path = FINAL,
) -> None:
    """Create a stable byte-identical review path, never overwriting drift."""

    _assert_input(raw_path, EXPECTED_SHA256["raw"], "H17 raw")
    if final_path.exists():
        if not final_path.is_file() or not h4.files_are_byte_identical(
            raw_path, final_path
        ):
            raise H17AuditError(
                f"refusing to overwrite non-identical H17 candidate: {final_path}"
            )
        return
    final_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(raw_path, final_path)
    _assert_input(final_path, EXPECTED_SHA256["final"], "H17 review candidate")


def _validate_receipt(path: Path = RECEIPT) -> dict[str, Any]:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise H17AuditError("H17 generation receipt is not valid UTF-8 JSON") from exc
    limitations = receipt.get("provenance_limitations")
    required_unknowns = {
        "exact_image_model_identifier_available": False,
        "model": "unknown",
        "model_snapshot_available": False,
        "model_snapshot": "unavailable",
        "generation_identifier_available": False,
        "generation_id": "unavailable",
        "generation_timestamp_utc": None,
    }
    if not isinstance(limitations, dict):
        raise H17AuditError("H17 receipt lacks provenance limitations")
    for key, expected in required_unknowns.items():
        if limitations.get(key) != expected:
            raise H17AuditError(f"H17 receipt must retain {key}={expected!r}")
    prompt = receipt.get("prompt")
    inputs = receipt.get("inputs")
    output = receipt.get("output")
    review = receipt.get("byte_identical_review_candidate")
    if not all(isinstance(value, dict) for value in (prompt, output, review)):
        raise H17AuditError("H17 receipt prompt/output/review candidate is malformed")
    if not isinstance(inputs, list) or len(inputs) != 1:
        raise H17AuditError("H17 receipt must retain H4 as its sole generation input")
    expected_records = (
        (prompt, PROMPT, EXPECTED_SHA256["prompt"]),
        (inputs[0], H4_REFERENCE, EXPECTED_SHA256["h4"]),
        (output, RAW, EXPECTED_SHA256["raw"]),
        (review, FINAL, EXPECTED_SHA256["final"]),
    )
    for record, expected_path, expected_hash in expected_records:
        if record.get("path") != h4._relative(expected_path):
            raise H17AuditError("H17 receipt path chain changed")
        if record.get("sha256") != expected_hash:
            raise H17AuditError("H17 receipt SHA-256 chain changed")
        resolved = _repo_path(record["path"])
        if not resolved.is_file():
            raise H17AuditError(f"H17 receipt artifact is missing: {record['path']}")
    if output.get("accepted_as_final") is not False:
        raise H17AuditError("H17 raw output must not claim final acceptance")
    if review.get("manifest_registered") is not False:
        raise H17AuditError("H17 review candidate must not claim manifest registration")
    if review.get("golden_accepted") is not False:
        raise H17AuditError("H17 review candidate must not claim Golden acceptance")
    return receipt


def _image_contract(
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    required = {
        "format": "PNG",
        "mode": "RGB",
        "width": h4.EXPECTED_SIZE[0],
        "height": h4.EXPECTED_SIZE[1],
        "bit_depth": 8,
        "png_color_type": 2,
        "alpha_or_transparency_present": False,
    }
    record_results = {
        name: all(record[key] == value for key, value in required.items())
        for name, record in records.items()
    }
    b1_profile = h4._profile_signature(records["reference_b1"])
    profile_matches = all(
        h4._profile_signature(records[name]) == b1_profile
        for name in ("raw", "final", "reference_h4")
    )
    return {
        "passed": all(record_results.values()) and profile_matches,
        "required": required,
        "records_passed": record_results,
        "profile_matches_b1": profile_matches,
        "images": records,
    }


def _ssim_mean(left: np.ndarray, right: np.ndarray) -> float:
    left_f = left.astype(np.float64)
    right_f = right.astype(np.float64)
    left_mean = cv2.GaussianBlur(left_f, (11, 11), 1.5)
    right_mean = cv2.GaussianBlur(right_f, (11, 11), 1.5)
    left_var = cv2.GaussianBlur(left_f * left_f, (11, 11), 1.5)
    left_var -= left_mean * left_mean
    right_var = cv2.GaussianBlur(right_f * right_f, (11, 11), 1.5)
    right_var -= right_mean * right_mean
    covariance = cv2.GaussianBlur(left_f * right_f, (11, 11), 1.5)
    covariance -= left_mean * right_mean
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    numerator = (2 * left_mean * right_mean + c1) * (2 * covariance + c2)
    denominator = (
        (left_mean * left_mean + right_mean * right_mean + c1)
        * (left_var + right_var + c2)
    )
    return float(np.mean(numerator / denominator))


def _feature_alignment(
    candidate: np.ndarray,
    reference: np.ndarray,
) -> dict[str, Any]:
    sift = cv2.SIFT_create(
        nfeatures=8000,
        contrastThreshold=0.02,
        edgeThreshold=12,
    )
    candidate_points, candidate_desc = sift.detectAndCompute(candidate, None)
    reference_points, reference_desc = sift.detectAndCompute(reference, None)
    if candidate_desc is None or reference_desc is None:
        raise H17AuditError("SIFT produced no descriptors")
    pairs = cv2.BFMatcher().knnMatch(candidate_desc, reference_desc, k=2)
    good = [first for first, second in pairs if first.distance < 0.75 * second.distance]
    if len(good) < 4:
        raise H17AuditError("too few H17/H4 matches for a homography")
    source = np.float32(
        [candidate_points[item.queryIdx].pt for item in good]
    )
    target = np.float32(
        [reference_points[item.trainIdx].pt for item in good]
    )
    homography, mask = cv2.findHomography(source, target, cv2.RANSAC, 4.0)
    if homography is None or mask is None:
        raise H17AuditError("H17/H4 homography could not be estimated")
    inliers = mask.ravel().astype(bool)
    displacements = np.linalg.norm(source[inliers] - target[inliers], axis=1)
    cells = {
        (min(11, int(x // 128)), min(7, int(y // 128)))
        for x, y in source[inliers]
    }
    corners = np.float32(
        [[[0, 0], [candidate.shape[1] - 1, 0],
          [candidate.shape[1] - 1, candidate.shape[0] - 1],
          [0, candidate.shape[0] - 1]]]
    )
    transformed = cv2.perspectiveTransform(corners, homography)
    corner_displacements = np.linalg.norm(transformed - corners, axis=2)[0]
    record = {
        "method": (
            "SIFT ratio matches followed by 4px RANSAC homography; displacement "
            "is measured in the unchanged 1536x1024 coordinate frame"
        ),
        "candidate_keypoints": len(candidate_points),
        "reference_keypoints": len(reference_points),
        "good_matches": len(good),
        "ransac_inliers": int(np.count_nonzero(inliers)),
        "ransac_inlier_ratio": round(float(np.mean(inliers)), 6),
        "median_inlier_displacement_px": round(
            float(np.percentile(displacements, 50)), 6
        ),
        "p95_inlier_displacement_px": round(
            float(np.percentile(displacements, 95)), 6
        ),
        "inlier_grid": [12, 8],
        "inlier_grid_coverage": round(len(cells) / 96, 6),
        "maximum_homography_corner_displacement_px": round(
            float(np.max(corner_displacements)), 6
        ),
        "homography": [
            [round(float(value), 10) for value in row]
            for row in homography.tolist()
        ],
    }
    thresholds = COMPOSITION_THRESHOLDS
    record["passed"] = (
        record["good_matches"] >= thresholds["minimum_good_sift_matches"]
        and record["ransac_inlier_ratio"]
        >= thresholds["minimum_ransac_inlier_ratio"]
        and record["median_inlier_displacement_px"]
        <= thresholds["maximum_median_inlier_displacement_px"]
        and record["p95_inlier_displacement_px"]
        <= thresholds["maximum_p95_inlier_displacement_px"]
        and record["inlier_grid_coverage"]
        >= thresholds["minimum_inlier_grid_coverage"]
        and record["maximum_homography_corner_displacement_px"]
        <= thresholds["maximum_homography_corner_displacement_px"]
    )
    return record


def _edge_alignment(
    candidate: np.ndarray,
    reference: np.ndarray,
) -> dict[str, Any]:
    candidate_blur = cv2.GaussianBlur(candidate, (0, 0), 1.2)
    reference_blur = cv2.GaussianBlur(reference, (0, 0), 1.2)
    candidate_edges = cv2.Canny(candidate_blur, 50, 120) > 0
    reference_edges = cv2.Canny(reference_blur, 50, 120) > 0
    candidate_distance = cv2.distanceTransform(
        (~candidate_edges).astype(np.uint8), cv2.DIST_L2, 3
    )
    reference_distance = cv2.distanceTransform(
        (~reference_edges).astype(np.uint8), cv2.DIST_L2, 3
    )
    tolerance = 4
    precision = float(np.mean(reference_distance[candidate_edges] <= tolerance))
    recall = float(np.mean(candidate_distance[reference_edges] <= tolerance))
    f1 = 2 * precision * recall / (precision + recall)
    record = {
        "method": (
            "native grayscale Gaussian sigma=1.2, Canny 50/120, symmetric "
            "distance-transform alignment within 4px"
        ),
        "tolerance_px": tolerance,
        "candidate_edge_fraction": round(float(np.mean(candidate_edges)), 6),
        "reference_edge_fraction": round(float(np.mean(reference_edges)), 6),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }
    thresholds = COMPOSITION_THRESHOLDS
    record["passed"] = (
        precision >= thresholds["minimum_edge_precision"]
        and recall >= thresholds["minimum_edge_recall"]
        and f1 >= thresholds["minimum_edge_f1"]
    )
    return record


def composition_preservation_metrics(
    candidate: Image.Image,
    reference: Image.Image,
) -> dict[str, Any]:
    candidate_gray = cv2.cvtColor(np.asarray(candidate), cv2.COLOR_RGB2GRAY)
    reference_gray = cv2.cvtColor(np.asarray(reference), cv2.COLOR_RGB2GRAY)
    scaled_records: list[dict[str, Any]] = []
    for scale in (1.0, 0.5, 0.25, 0.125):
        size = (
            round(candidate.width * scale),
            round(candidate.height * scale),
        )
        left = cv2.resize(candidate_gray, size, interpolation=cv2.INTER_AREA)
        right = cv2.resize(reference_gray, size, interpolation=cv2.INTER_AREA)
        scaled_records.append(
            {"scale": scale, "ssim": round(_ssim_mean(left, right), 6)}
        )
    blurred_candidate = cv2.GaussianBlur(candidate_gray, (0, 0), 4.0)
    blurred_reference = cv2.GaussianBlur(reference_gray, (0, 0), 4.0)
    sigma4_ssim = _ssim_mean(blurred_candidate, blurred_reference)
    regions: list[dict[str, Any]] = []
    for name, (left, top, right, bottom) in COMPOSITION_REGIONS.items():
        candidate_crop = candidate_gray[top:bottom, left:right]
        reference_crop = reference_gray[top:bottom, left:right]
        size = (max(1, (right - left) // 4), max(1, (bottom - top) // 4))
        candidate_crop = cv2.resize(
            candidate_crop, size, interpolation=cv2.INTER_AREA
        )
        reference_crop = cv2.resize(
            reference_crop, size, interpolation=cv2.INTER_AREA
        )
        regions.append(
            {
                "id": name,
                "box": [left, top, right, bottom],
                "quarter_scale_ssim": round(
                    _ssim_mean(candidate_crop, reference_crop), 6
                ),
            }
        )
    quarter_ssim = next(
        item["ssim"] for item in scaled_records if item["scale"] == 0.25
    )
    minimum_region = min(item["quarter_scale_ssim"] for item in regions)
    feature = _feature_alignment(candidate_gray, reference_gray)
    edge = _edge_alignment(candidate_gray, reference_gray)
    thresholds = COMPOSITION_THRESHOLDS
    low_frequency_passed = (
        quarter_ssim >= thresholds["minimum_quarter_scale_ssim"]
        and sigma4_ssim >= thresholds["minimum_sigma4_ssim"]
        and minimum_region
        >= thresholds["minimum_region_quarter_scale_ssim"]
    )
    return {
        "passed": low_frequency_passed and feature["passed"] and edge["passed"],
        "interpretation": (
            "These proxies can support coordinate/layout preservation only. They do "
            "not prove prompt-level visual identity of unaffected microdetail."
        ),
        "thresholds": COMPOSITION_THRESHOLDS,
        "multiscale_ssim": scaled_records,
        "sigma4_low_frequency_ssim": round(sigma4_ssim, 6),
        "region_quarter_scale_ssim": regions,
        "minimum_region_quarter_scale_ssim": round(minimum_region, 6),
        "low_frequency_passed": low_frequency_passed,
        "feature_alignment": feature,
        "edge_alignment": edge,
    }


def _patch_signatures(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    vectors: list[np.ndarray] = []
    hashes: list[np.ndarray] = []
    locations: list[tuple[int, int]] = []
    for top in range(0, gray.shape[0] - 64 + 1, 32):
        for left in range(0, gray.shape[1] - 64 + 1, 32):
            patch = gray[top : top + 64, left : left + 64]
            small = cv2.resize(patch, (16, 16), interpolation=cv2.INTER_AREA)
            vector = small.astype(np.float64).reshape(-1)
            vector -= np.mean(vector)
            norm = np.linalg.norm(vector)
            vectors.append(vector / norm if norm else vector)
            dct_patch = cv2.resize(
                patch, (32, 32), interpolation=cv2.INTER_AREA
            ).astype(np.float32)
            coefficients = cv2.dct(dct_patch)[:8, :8].reshape(-1)[1:]
            hashes.append(coefficients > np.median(coefficients))
            locations.append((left, top))
    return np.asarray(vectors), np.asarray(hashes), np.asarray(locations)


def _near_patch_record(gray: np.ndarray) -> dict[str, Any]:
    vectors, hashes, locations = _patch_signatures(gray)
    best_correlations: list[float] = []
    related: set[int] = set()
    close_hash_pairs = 0
    for index in range(len(vectors) - 1):
        offsets = np.max(
            np.abs(locations[index + 1 :] - locations[index]), axis=1
        )
        eligible = offsets >= 128
        correlations = vectors[index + 1 :] @ vectors[index]
        correlations[~eligible] = -2.0
        best_correlations.append(float(np.max(correlations)))
        hamming = np.count_nonzero(
            hashes[index + 1 :] != hashes[index], axis=1
        )
        matches = np.where((hamming <= 3) & eligible)[0]
        if len(matches):
            related.add(index)
            related.update((index + 1 + matches).tolist())
            close_hash_pairs += len(matches)
    ordered = np.asarray(best_correlations)
    return {
        "patch_size_px": 64,
        "stride_px": 32,
        "minimum_pair_separation_px_chebyshev": 128,
        "patches": len(vectors),
        "p99_best_normalized_correlation": round(
            float(np.percentile(ordered, 99)), 6
        ),
        "fraction_best_correlation_at_least_0_90": round(
            float(np.mean(ordered >= 0.90)), 6
        ),
        "phash_hamming_at_most_3_pairs": close_hash_pairs,
        "phash_related_patch_fraction": round(len(related) / len(vectors), 6),
    }


def _periodicity_record(gray: np.ndarray) -> dict[str, Any]:
    small = cv2.resize(gray, (384, 256), interpolation=cv2.INTER_AREA).astype(
        np.float64
    )
    high_pass = small - cv2.GaussianBlur(small, (0, 0), 3.0)
    window = np.outer(np.hanning(256), np.hanning(384))
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2(high_pass * window)))
    spectrum[120:137, 184:201] = 0
    values = np.sort(spectrum.reshape(-1))
    return {
        "sample_size": [384, 256],
        "spectral_peak_to_top100_mean": round(
            float(values[-1] / np.mean(values[-100:])), 6
        ),
    }


def semantic_repetition_proxies(
    candidate: Image.Image,
    reference: Image.Image,
) -> dict[str, Any]:
    candidate_gray = cv2.cvtColor(np.asarray(candidate), cv2.COLOR_RGB2GRAY)
    reference_gray = cv2.cvtColor(np.asarray(reference), cv2.COLOR_RGB2GRAY)
    candidate_patch = _near_patch_record(candidate_gray)
    reference_patch = _near_patch_record(reference_gray)
    candidate_period = _periodicity_record(candidate_gray)
    reference_period = _periodicity_record(reference_gray)
    thresholds = {
        "maximum_p99_best_normalized_correlation": round(
            max(
                0.80,
                reference_patch["p99_best_normalized_correlation"] + 0.10,
            ),
            6,
        ),
        "maximum_fraction_best_correlation_at_least_0_90": round(
            reference_patch["fraction_best_correlation_at_least_0_90"] + 0.01,
            6,
        ),
        "maximum_phash_related_patch_fraction": round(
            reference_patch["phash_related_patch_fraction"] + 0.01,
            6,
        ),
        "maximum_spectral_peak_to_top100_mean": round(
            max(
                2.0,
                reference_period["spectral_peak_to_top100_mean"] * 1.25,
            ),
            6,
        ),
    }
    passed = (
        candidate_patch["p99_best_normalized_correlation"]
        <= thresholds["maximum_p99_best_normalized_correlation"]
        and candidate_patch["fraction_best_correlation_at_least_0_90"]
        <= thresholds["maximum_fraction_best_correlation_at_least_0_90"]
        and candidate_patch["phash_related_patch_fraction"]
        <= thresholds["maximum_phash_related_patch_fraction"]
        and candidate_period["spectral_peak_to_top100_mean"]
        <= thresholds["maximum_spectral_peak_to_top100_mean"]
    )
    return {
        "passed": passed,
        "method": (
            "far-patch normalized correlation, 63-bit DCT perceptual hashes, and "
            "windowed high-pass spectral concentration relative to H4"
        ),
        "semantic_claim": None,
        "limitation": (
            "These statistics can flag clone-like or periodic amplification, but "
            "cannot decide whether mountains, trees, rocks, or buildings repeat "
            "semantically. That decision remains Vision-only."
        ),
        "thresholds": thresholds,
        "candidate_near_patch": candidate_patch,
        "reference_h4_near_patch": reference_patch,
        "candidate_periodicity": candidate_period,
        "reference_h4_periodicity": reference_period,
    }


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _labelled_panel(
    image: Image.Image,
    label: str,
    *,
    maximum_size: tuple[int, int] | None = None,
) -> Image.Image:
    panel_image = image.copy()
    if maximum_size is not None:
        panel_image.thumbnail(maximum_size, Image.Resampling.LANCZOS)
    label_height = 42
    panel = Image.new(
        "RGB",
        (panel_image.width + 8, panel_image.height + label_height + 8),
        (25, 28, 30),
    )
    panel.paste(panel_image, (4, label_height + 4))
    ImageDraw.Draw(panel).text((12, 8), label, fill=(238, 234, 218), font=_font(24))
    panel_image.close()
    return panel


def _row(panels: list[Image.Image], gap: int = 20) -> Image.Image:
    width = sum(panel.width for panel in panels) + gap * (len(panels) - 1)
    height = max(panel.height for panel in panels)
    row = Image.new("RGB", (width, height), (18, 20, 22))
    left = 0
    for panel in panels:
        row.paste(panel, (left, 0))
        left += panel.width + gap
    return row


def _save_png_safely(image: Image.Image, path: Path, *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new.png")
    if temporary.exists():
        temporary.unlink()
    image.save(temporary, format="PNG", optimize=False)
    if path.exists():
        if h4.files_are_byte_identical(path, temporary):
            temporary.unlink()
            return
        if not replace:
            temporary.unlink()
            raise H17AuditError(f"refusing to overwrite changed output: {path}")
        path.unlink()
    temporary.replace(path)


def build_contact_sheet(
    candidate: Image.Image,
    reference: Image.Image,
    path: Path = CONTACT,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    sections: list[Image.Image] = []
    title = Image.new("RGB", (3800, 116), (18, 20, 22))
    title_draw = ImageDraw.Draw(title)
    title_draw.text(
        (24, 16),
        "H17 automated review contact sheet — NOT Vision approval",
        fill=(244, 229, 183),
        font=_font(38),
    )
    title_draw.text(
        (24, 66),
        "H4 is shown only for comparison; candidate remains unaccepted.",
        fill=(194, 202, 205),
        font=_font(24),
    )
    sections.append(title)

    sections.append(
        _row(
            [
                _labelled_panel(reference, "H4 reference — native 100%"),
                _labelled_panel(candidate, "H17 candidate — native 100%"),
            ]
        )
    )
    scale_panels: list[Image.Image] = []
    for scale in (0.25, 0.50):
        size = (round(candidate.width * scale), round(candidate.height * scale))
        for source, name in ((reference, "H4"), (candidate, "H17")):
            scaled = source.resize(size, Image.Resampling.LANCZOS)
            scale_panels.append(
                _labelled_panel(
                    scaled,
                    f"{name} at {round(scale * 100)}% ({size[0]}x{size[1]})",
                )
            )
            scaled.close()
    sections.append(_row(scale_panels))

    region_panels: list[Image.Image] = []
    for row_index in range(3):
        top = row_index * candidate.height // 3
        bottom = (row_index + 1) * candidate.height // 3
        for column_index in range(3):
            left = column_index * candidate.width // 3
            right = (column_index + 1) * candidate.width // 3
            crop = candidate.crop((left, top, right, bottom))
            region_panels.append(
                _labelled_panel(
                    crop,
                    f"H17 region r{row_index + 1}c{column_index + 1} "
                    f"[{left},{top},{right},{bottom}]",
                )
            )
            crop.close()
    for offset in range(0, len(region_panels), 3):
        sections.append(_row(region_panels[offset : offset + 3]))

    for name, box in FOCUS_REGIONS.items():
        h4_crop = reference.crop(box)
        h17_crop = candidate.crop(box)
        panels = [
            _labelled_panel(h4_crop, f"H4 focus: {name}", maximum_size=(900, 620)),
            _labelled_panel(
                h17_crop, f"H17 focus: {name}", maximum_size=(900, 620)
            ),
        ]
        width, height = h17_crop.size
        inner_200 = h17_crop.crop(
            (width // 4, height // 4, 3 * width // 4, 3 * height // 4)
        )
        inner_400 = h17_crop.crop(
            (3 * width // 8, 3 * height // 8, 5 * width // 8, 5 * height // 8)
        )
        zoom_200 = inner_200.resize(
            (inner_200.width * 2, inner_200.height * 2),
            Image.Resampling.NEAREST,
        )
        zoom_400 = inner_400.resize(
            (inner_400.width * 4, inner_400.height * 4),
            Image.Resampling.NEAREST,
        )
        panels.extend(
            [
                _labelled_panel(
                    zoom_200, f"H17 {name} inner crop at 200%", maximum_size=(760, 620)
                ),
                _labelled_panel(
                    zoom_400, f"H17 {name} inner crop at 400%", maximum_size=(760, 620)
                ),
            ]
        )
        sections.append(_row(panels))
        h4_crop.close()
        h17_crop.close()
        inner_200.close()
        inner_400.close()
        zoom_200.close()
        zoom_400.close()

    canvas_width = max(section.width for section in sections) + 48
    canvas_height = sum(section.height for section in sections) + 24 * (
        len(sections) + 1
    )
    canvas = Image.new("RGB", (canvas_width, canvas_height), (18, 20, 22))
    top = 24
    for section in sections:
        canvas.paste(section, (24, top))
        top += section.height + 24
    try:
        _save_png_safely(canvas, path, replace=replace)
    finally:
        canvas.close()
        for section in sections:
            section.close()
        for panel in scale_panels + region_panels:
            panel.close()
    return h4._artifact(path)


def audit(
    *,
    report_path: Path = REPORT,
    contact_path: Path = CONTACT,
    replace: bool = False,
) -> dict[str, Any]:
    materialize_review_candidate()
    locked = (
        (RAW, EXPECTED_SHA256["raw"], "H17 raw"),
        (FINAL, EXPECTED_SHA256["final"], "H17 review candidate"),
        (PROMPT, EXPECTED_SHA256["prompt"], "H17 generation prompt"),
        (RECEIPT, EXPECTED_SHA256["receipt"], "H17 generation receipt"),
        (H4_REFERENCE, EXPECTED_SHA256["h4"], "H4 sole reference"),
        (B1_REFERENCE, EXPECTED_SHA256["b1"], "B1 palette-gate reference"),
        (VISION_SCHEMA, EXPECTED_SHA256["vision_schema"], "Vision schema"),
    )
    for path, expected_hash, label in locked:
        _assert_input(path, expected_hash, label)
    if report_path.exists() and not replace:
        raise H17AuditError(f"refusing to overwrite existing report: {report_path}")
    try:
        prompt_text = PROMPT.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise H17AuditError("H17 prompt is not valid UTF-8") from exc
    phrases = (
        "surgical cartographic-flattening pass",
        "H4 is the sole authority",
        "true vertical plan view",
        "1536 x 1024 RGB image",
        "map artwork only",
    )
    missing = [phrase for phrase in phrases if phrase not in prompt_text]
    if missing:
        raise H17AuditError("H17 prompt lost requirements: " + ", ".join(missing))
    _validate_receipt()
    byte_identity = h4.files_are_byte_identical(RAW, FINAL)
    if not byte_identity:
        raise H17AuditError("H17 raw and stable review candidate are not identical")

    records: dict[str, dict[str, Any]] = {}
    images: dict[str, Image.Image] = {}
    for name, path in (
        ("raw", RAW),
        ("final", FINAL),
        ("reference_h4", H4_REFERENCE),
        ("reference_b1", B1_REFERENCE),
    ):
        records[name], images[name] = h4.inspect_png(path)
    try:
        image_contract = _image_contract(records)
        boundary = h4.boundary_metrics(images["final"])
        palette = h4.palette_continuity_metrics(
            images["final"], images["reference_b1"]
        )
        exact_repetition = h4.exact_repetition_metrics(images["final"])
        downsample = h4.downsample_readability_metrics(images["final"])
        composition = composition_preservation_metrics(
            images["final"], images["reference_h4"]
        )
        semantic_proxies = semantic_repetition_proxies(
            images["final"], images["reference_h4"]
        )
        contact = build_contact_sheet(
            images["final"],
            images["reference_h4"],
            contact_path,
            replace=replace,
        )
    finally:
        for image in images.values():
            image.close()

    gates = {
        "sha256_locked_inputs": True,
        "raw_final_byte_identity": byte_identity,
        "image_contract_alpha_profile": image_contract["passed"],
        "boundary_proxy": boundary["passed"],
        "palette_continuity_with_b1": palette["passed"],
        "no_large_exact_repetition_proxy": exact_repetition["passed"],
        "downsample_readability_proxy": downsample["passed"],
        "composition_preservation_proxies_vs_h4": composition["passed"],
        "semantic_repetition_proxies_vs_h4": semantic_proxies["passed"],
    }
    failed = tuple(name for name, passed in gates.items() if not passed)
    if failed != EXPECTED_FAILED_GATES:
        raise H17AuditError(
            f"H17 gate evidence changed: expected {list(EXPECTED_FAILED_GATES)}, "
            f"got {list(failed)}"
        )
    report = {
        "schema_version": "1.0.0",
        "id": f"{JOB_ID}-automated-audit",
        "status": "failed",
        "scope": "automated artifact and raster proxies only",
        "decision": "automated-gates-failed-rejected-before-vision",
        "failed_gates": list(failed),
        "golden_accepted": False,
        "manifest_mutation": False,
        "generated_by": h4._artifact(Path(__file__).resolve()),
        "audit_engine": {
            **h4._artifact(Path(h4.__file__).resolve()),
            "threshold_policy": "unchanged H4 absolute gates plus new locked H17 proxies",
        },
        "artifacts": {
            "raw": h4._artifact(RAW),
            "final_review_candidate": {
                **h4._artifact(FINAL),
                "review_only": True,
                "accepted": False,
            },
            "prompt": h4._artifact(PROMPT),
            "generation_receipt": h4._artifact(RECEIPT),
            "reference_h4_sole_generation_input": h4._artifact(H4_REFERENCE),
            "reference_b1_automated_palette_gate_only": h4._artifact(B1_REFERENCE),
            "local_contact_sheet": {
                **contact,
                "repository_artifact": False,
                "vision_report": False,
            },
        },
        "identity": {
            "passed": True,
            "raw_final_byte_identical": byte_identity,
            "locked_sha256": EXPECTED_SHA256,
        },
        "image_contract": image_contract,
        "boundary": boundary,
        "palette_continuity": palette,
        "exact_repetition": exact_repetition,
        "downsample_readability": downsample,
        "composition_preservation": composition,
        "semantic_repetition_proxies": semantic_proxies,
        "automated_gates": gates,
        "vision_handoff": {
            "status": "not-performed",
            "vision_report_created": False,
            "automated_audit_is_not_vision": True,
            "automated_audit_is_not_golden_acceptance": True,
            "reason": (
                "Unchanged H4/B1 palette and downsample readability gates failed. "
                "Semantic plan-view, repetition, pseudo-text, seam, and artistic "
                "judgments are deliberately not claimed by this report."
            ),
            "schema": h4._artifact(VISION_SCHEMA),
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--contact", type=Path, default=CONTACT)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit(
            report_path=args.report.resolve(),
            contact_path=args.contact.resolve(),
            replace=args.replace,
        )
    except (H17AuditError, h4.H4AuditError, OSError, ValueError) as exc:
        print(f"H17 automated audit failed to record evidence: {exc}")
        return 1
    palette = report["palette_continuity"]
    quarter = next(
        item
        for item in report["downsample_readability"]["scales"]
        if item["scale"] == 0.25
    )
    print(
        "H17 formal rejection recorded: "
        f"failed_gates={','.join(report['failed_gates'])}; "
        f"rgb={palette['rgb_histogram_intersection']}; "
        f"hsv={palette['hsv_histogram_intersection']}; "
        f"quarter_macrocell={quarter['macrocell_contrast_coverage']}; "
        "Vision not performed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
