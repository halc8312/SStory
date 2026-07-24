#!/usr/bin/env python3
"""Audit the Candidate H4 Golden-board artifact with deterministic proxies.

The automated checks intentionally do not claim that generated text is absent
or that the drawing is strictly orthographic.  Those semantic judgments remain
explicit Vision-QA hand-offs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageStat, UnidentifiedImageError


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FINAL = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-h-v4-plan-view-golden-board.png"
)
DEFAULT_RAW = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-h-v4-plan-view-golden-board-raw.png"
)
DEFAULT_PROMPT = (
    REPO_ROOT
    / "world/map-production/prompts/"
    "style-candidate-h-v4-plan-view-golden-board.generation.txt"
)
DEFAULT_REFERENCE_B1 = (
    REPO_ROOT / "world/map-production/candidates/style-candidate-b-v1.png"
)
DEFAULT_VISION_SCHEMA = REPO_ROOT / "world/map-production/schemas/qa-report.schema.json"
DEFAULT_REPORT = (
    REPO_ROOT
    / "world/map-production/qa/automated/"
    "style-candidate-h-v4-plan-view-golden-board.json"
)

EXPECTED_SHA256 = {
    "final": "b4fc951af5d29c78bb98b5ee5007395b5fc3c1addc7070d76ac8074545259837",
    "raw": "b4fc951af5d29c78bb98b5ee5007395b5fc3c1addc7070d76ac8074545259837",
    "prompt": "ab066d73cd05d3d7b9bb5abfe3d76a70ae80b814fc8af51d48ead19784548675",
    "reference_b1": (
        "4d505def78acc752ee2611cb73d112cc9a3048f611cb05233274a1eb2ae42003"
    ),
    "vision_schema": (
        "3d5aa81edf380fbe13b4fbec63ee79c523f398f00cdaec22029c8eaf05f8df5b"
    ),
}

EXPECTED_SIZE = (1536, 1024)
BOUNDARY_BAND_PX = 16
BOUNDARY_INSET_PX = 24
MAX_BOUNDARY_DOMINANT_RGB_RATIO = 0.05
MIN_BOUNDARY_UNIQUE_RGB = 256
MAX_OUTER_IDENTICAL_RUN_RATIO = 0.25
FRAME_RGB_MEAN_GAP_THRESHOLD = 18.0
FRAME_MINIMUM_SUSPICIOUS_SIDES = 2

MIN_RGB_HISTOGRAM_INTERSECTION = 0.72
MIN_HSV_HISTOGRAM_INTERSECTION = 0.62
MIN_RGB_BHATTACHARYYA = 0.90
MAX_MEAN_CHANNEL_DELTA = 12.0

REPETITION_BLOCK_SIZES = (256, 128, 64)
REPETITION_STRIDE_DIVISOR = 4

DOWNSAMPLE_THRESHOLDS = {
    0.5: {
        "minimum_entropy_retention": 0.94,
        "minimum_rms_contrast_retention": 0.82,
        "minimum_macrocell_contrast_coverage": 0.90,
    },
    0.25: {
        "minimum_entropy_retention": 0.90,
        "minimum_rms_contrast_retention": 0.68,
        "minimum_macrocell_contrast_coverage": 0.85,
    },
}
MACROCELL_GRID = (24, 16)
MACROCELL_MINIMUM_LUMA_STDDEV = 6.0

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PROFILE_CHUNKS = frozenset({"iCCP", "sRGB", "gAMA", "cHRM"})


class H4AuditError(ValueError):
    """Raised when H4 cannot satisfy its automated audit contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": _relative(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _assert_input(path: Path, expected_hash: str, label: str) -> None:
    if not path.is_file():
        raise H4AuditError(f"{label} does not exist: {path}")
    actual = sha256_file(path)
    if actual != expected_hash:
        raise H4AuditError(
            f"{label} SHA-256 mismatch: expected {expected_hash}, got {actual}"
        )


def files_are_byte_identical(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as left_handle, right.open("rb") as right_handle:
        while True:
            left_chunk = left_handle.read(1024 * 1024)
            right_chunk = right_handle.read(1024 * 1024)
            if left_chunk != right_chunk:
                return False
            if not left_chunk:
                return True


def _png_chunks(path: Path) -> tuple[list[str], dict[str, int]]:
    payload = path.read_bytes()
    if not payload.startswith(PNG_SIGNATURE):
        raise H4AuditError(f"not a PNG signature: {path}")
    offset = len(PNG_SIGNATURE)
    chunk_types: list[str] = []
    ihdr: dict[str, int] | None = None
    found_iend = False
    while offset + 12 <= len(payload):
        length = int.from_bytes(payload[offset : offset + 4], "big")
        chunk_name_bytes = payload[offset + 4 : offset + 8]
        try:
            chunk_name = chunk_name_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            raise H4AuditError(f"invalid PNG chunk name in {path}") from exc
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(payload):
            raise H4AuditError(f"truncated PNG chunk {chunk_name!r}: {path}")
        chunk_data = payload[data_start:data_end]
        chunk_types.append(chunk_name)
        if chunk_name == "IHDR":
            if length != 13:
                raise H4AuditError(f"invalid IHDR length in {path}")
            ihdr = {
                "width": int.from_bytes(chunk_data[0:4], "big"),
                "height": int.from_bytes(chunk_data[4:8], "big"),
                "bit_depth": chunk_data[8],
                "color_type": chunk_data[9],
                "compression_method": chunk_data[10],
                "filter_method": chunk_data[11],
                "interlace_method": chunk_data[12],
            }
        offset = crc_end
        if chunk_name == "IEND":
            found_iend = True
            break
    if ihdr is None or not found_iend or offset != len(payload):
        raise H4AuditError(f"incomplete or trailing PNG structure: {path}")
    return chunk_types, ihdr


def inspect_png(path: Path) -> tuple[dict[str, Any], Image.Image]:
    chunk_types, ihdr = _png_chunks(path)
    try:
        with Image.open(path) as opened:
            opened.verify()
        with Image.open(path) as opened:
            opened.load()
            image_format = opened.format
            mode = opened.mode
            size = opened.size
            bands = list(opened.getbands())
            info_keys = sorted(str(key) for key in opened.info)
            transparency_present = "transparency" in opened.info or "tRNS" in chunk_types
            icc_profile = opened.info.get("icc_profile")
            rgb = opened.convert("RGB")
    except (OSError, SyntaxError, UnidentifiedImageError) as exc:
        raise H4AuditError(f"cannot decode image {path}: {exc}") from exc
    icc_sha256 = None
    if isinstance(icc_profile, bytes) and icc_profile:
        icc_sha256 = hashlib.sha256(icc_profile).hexdigest()
    alpha_present = "A" in bands or transparency_present or ihdr["color_type"] in {4, 6}
    record = {
        "format": image_format,
        "mode": mode,
        "width": size[0],
        "height": size[1],
        "bands": bands,
        "bit_depth": ihdr["bit_depth"],
        "png_color_type": ihdr["color_type"],
        "alpha_or_transparency_present": alpha_present,
        "icc_profile_present": icc_sha256 is not None,
        "icc_profile_sha256": icc_sha256,
        "profile_chunk_types": [
            chunk_name for chunk_name in chunk_types if chunk_name in PROFILE_CHUNKS
        ],
        "png_chunk_types": chunk_types,
        "pillow_info_keys": info_keys,
    }
    return record, rgb


def _profile_signature(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record["icc_profile_present"],
        record["icc_profile_sha256"],
        tuple(record["profile_chunk_types"]),
    )


def _positions(limit: int, block_size: int, stride: int) -> list[int]:
    if limit < block_size:
        return []
    positions = list(range(0, limit - block_size + 1, stride))
    final_position = limit - block_size
    if positions[-1] != final_position:
        positions.append(final_position)
    return positions


def exact_repetition_metrics(image: Image.Image) -> dict[str, Any]:
    scales: list[dict[str, Any]] = []
    all_examples: list[dict[str, Any]] = []
    total_duplicate_groups = 0
    maximum_copy_count = 1
    for block_size in REPETITION_BLOCK_SIZES:
        stride = max(1, block_size // REPETITION_STRIDE_DIVISOR)
        locations: dict[str, list[list[int]]] = defaultdict(list)
        x_positions = _positions(image.width, block_size, stride)
        y_positions = _positions(image.height, block_size, stride)
        for top in y_positions:
            for left in x_positions:
                crop = image.crop(
                    (left, top, left + block_size, top + block_size)
                )
                try:
                    digest = hashlib.sha256(crop.tobytes()).hexdigest()
                finally:
                    crop.close()
                locations[digest].append([left, top])
        duplicate_groups = [
            (digest, points) for digest, points in locations.items() if len(points) > 1
        ]
        total_duplicate_groups += len(duplicate_groups)
        if duplicate_groups:
            maximum_copy_count = max(
                maximum_copy_count,
                max(len(points) for _, points in duplicate_groups),
            )
        for digest, points in duplicate_groups[:3]:
            all_examples.append(
                {
                    "block_size_px": block_size,
                    "sha256": digest,
                    "locations": points[:4],
                    "copy_count": len(points),
                }
            )
        scales.append(
            {
                "block_size_px": block_size,
                "stride_px": stride,
                "scanned_blocks": len(x_positions) * len(y_positions),
                "unique_block_hashes": len(locations),
                "duplicate_groups": len(duplicate_groups),
                "maximum_copy_count": max(
                    (len(points) for _, points in duplicate_groups), default=1
                ),
            }
        )
    return {
        "passed": total_duplicate_groups == 0,
        "method": (
            "exact SHA-256 of overlapping RGB blocks at one-quarter-block stride; "
            "this is a large-clone proxy, not semantic motif recognition"
        ),
        "minimum_block_size_px": min(REPETITION_BLOCK_SIZES),
        "duplicate_groups": total_duplicate_groups,
        "maximum_copy_count": maximum_copy_count,
        "examples": all_examples,
        "scales": scales,
    }


def _longest_identical_run(values: list[tuple[int, int, int]]) -> int:
    longest = 0
    current = 0
    previous: tuple[int, int, int] | None = None
    for value in values:
        if value == previous:
            current += 1
        else:
            previous = value
            current = 1
        longest = max(longest, current)
    return longest


def _side_box(
    image: Image.Image,
    side: str,
    width: int,
    *,
    inset: int = 0,
) -> tuple[int, int, int, int]:
    if side == "left":
        return (inset, 0, inset + width, image.height)
    if side == "right":
        return (image.width - inset - width, 0, image.width - inset, image.height)
    if side == "top":
        return (0, inset, image.width, inset + width)
    if side == "bottom":
        return (0, image.height - inset - width, image.width, image.height - inset)
    raise H4AuditError(f"unknown image side: {side}")


def _outer_edge_values(
    image: Image.Image,
    side: str,
) -> list[tuple[int, int, int]]:
    if side == "left":
        box = (0, 0, 1, image.height)
    elif side == "right":
        box = (image.width - 1, 0, image.width, image.height)
    elif side == "top":
        box = (0, 0, image.width, 1)
    elif side == "bottom":
        box = (0, image.height - 1, image.width, image.height)
    else:
        raise H4AuditError(f"unknown image side: {side}")
    edge = image.crop(box)
    try:
        return list(edge.get_flattened_data())
    finally:
        edge.close()


def boundary_metrics(image: Image.Image) -> dict[str, Any]:
    sides: list[dict[str, Any]] = []
    solid_sides: list[str] = []
    gap_sides: list[str] = []
    for side in ("left", "top", "right", "bottom"):
        band = image.crop(_side_box(image, side, BOUNDARY_BAND_PX))
        inset_band = image.crop(
            _side_box(image, side, 4, inset=BOUNDARY_INSET_PX)
        )
        outer_mean_band = image.crop(_side_box(image, side, 4))
        try:
            colors = Counter(band.get_flattened_data())
            pixel_count = band.width * band.height
            dominant_rgb, dominant_count = colors.most_common(1)[0]
            dominant_ratio = dominant_count / pixel_count
            luma = band.convert("L")
            try:
                luma_stddev = ImageStat.Stat(luma).stddev[0]
                luma_entropy = luma.entropy()
            finally:
                luma.close()
            outer_mean = ImageStat.Stat(outer_mean_band).mean
            inset_mean = ImageStat.Stat(inset_band).mean
            mean_rgb_gap = math.sqrt(
                sum((left - right) ** 2 for left, right in zip(outer_mean, inset_mean))
            )
        finally:
            band.close()
            inset_band.close()
            outer_mean_band.close()
        edge_values = _outer_edge_values(image, side)
        longest_run = _longest_identical_run(edge_values)
        longest_run_ratio = longest_run / len(edge_values)
        solid_signal = (
            dominant_ratio > MAX_BOUNDARY_DOMINANT_RGB_RATIO
            or len(colors) < MIN_BOUNDARY_UNIQUE_RGB
            or longest_run_ratio > MAX_OUTER_IDENTICAL_RUN_RATIO
        )
        frame_gap_signal = mean_rgb_gap >= FRAME_RGB_MEAN_GAP_THRESHOLD
        if solid_signal:
            solid_sides.append(side)
        if frame_gap_signal:
            gap_sides.append(side)
        sides.append(
            {
                "side": side,
                "pixels": pixel_count,
                "unique_rgb": len(colors),
                "dominant_rgb": list(dominant_rgb),
                "dominant_exact_rgb_ratio": round(dominant_ratio, 6),
                "outer_edge_longest_identical_run_px": longest_run,
                "outer_edge_longest_identical_run_ratio": round(
                    longest_run_ratio, 6
                ),
                "luma_stddev": round(luma_stddev, 6),
                "luma_entropy_bits": round(luma_entropy, 6),
                "outer_to_inset_mean_rgb_distance": round(mean_rgb_gap, 6),
                "solid_color_signal": solid_signal,
                "frame_gap_signal": frame_gap_signal,
            }
        )
    frame_signal = len(gap_sides) >= FRAME_MINIMUM_SUSPICIOUS_SIDES
    return {
        "passed": not solid_sides and not frame_signal,
        "method": (
            "edge-band color diversity, exact-color runs, and multi-side outer/inset "
            "mean-color gap; decorative semantics still require Vision review"
        ),
        "thresholds": {
            "band_width_px": BOUNDARY_BAND_PX,
            "maximum_dominant_exact_rgb_ratio": MAX_BOUNDARY_DOMINANT_RGB_RATIO,
            "minimum_unique_rgb": MIN_BOUNDARY_UNIQUE_RGB,
            "maximum_outer_identical_run_ratio": MAX_OUTER_IDENTICAL_RUN_RATIO,
            "frame_mean_rgb_gap": FRAME_RGB_MEAN_GAP_THRESHOLD,
            "frame_minimum_suspicious_sides": FRAME_MINIMUM_SUSPICIOUS_SIDES,
        },
        "solid_color_signal_detected": bool(solid_sides),
        "solid_color_sides": solid_sides,
        "decorative_frame_proxy_detected": frame_signal,
        "frame_gap_sides": gap_sides,
        "sides": sides,
    }


def _quantized_rgb_histogram(image: Image.Image) -> list[float]:
    sample = image.resize((384, 256), Image.Resampling.LANCZOS)
    try:
        histogram = [0] * 512
        for red, green, blue in sample.get_flattened_data():
            index = (red >> 5) * 64 + (green >> 5) * 8 + (blue >> 5)
            histogram[index] += 1
    finally:
        sample.close()
    total = sum(histogram)
    return [value / total for value in histogram]


def _quantized_hsv_histogram(image: Image.Image) -> list[float]:
    sample = image.resize((384, 256), Image.Resampling.LANCZOS).convert("HSV")
    hue_bins, saturation_bins, value_bins = 24, 6, 6
    try:
        histogram = [0] * (hue_bins * saturation_bins * value_bins)
        for hue, saturation, value in sample.get_flattened_data():
            hue_index = min(hue_bins - 1, hue * hue_bins // 256)
            saturation_index = min(
                saturation_bins - 1, saturation * saturation_bins // 256
            )
            value_index = min(value_bins - 1, value * value_bins // 256)
            index = (
                (hue_index * saturation_bins + saturation_index) * value_bins
                + value_index
            )
            histogram[index] += 1
    finally:
        sample.close()
    total = sum(histogram)
    return [item / total for item in histogram]


def _histogram_intersection(left: list[float], right: list[float]) -> float:
    return sum(min(left_value, right_value) for left_value, right_value in zip(left, right))


def _bhattacharyya(left: list[float], right: list[float]) -> float:
    return sum(
        math.sqrt(left_value * right_value)
        for left_value, right_value in zip(left, right)
    )


def palette_continuity_metrics(
    candidate: Image.Image,
    reference: Image.Image,
) -> dict[str, Any]:
    candidate_rgb = _quantized_rgb_histogram(candidate)
    reference_rgb = _quantized_rgb_histogram(reference)
    candidate_hsv = _quantized_hsv_histogram(candidate)
    reference_hsv = _quantized_hsv_histogram(reference)
    candidate_mean = ImageStat.Stat(candidate).mean
    reference_mean = ImageStat.Stat(reference).mean
    mean_channel_delta = [
        abs(left - right) for left, right in zip(candidate_mean, reference_mean)
    ]
    rgb_intersection = _histogram_intersection(candidate_rgb, reference_rgb)
    hsv_intersection = _histogram_intersection(candidate_hsv, reference_hsv)
    rgb_bhattacharyya = _bhattacharyya(candidate_rgb, reference_rgb)
    maximum_mean_delta = max(mean_channel_delta)
    passed = (
        rgb_intersection >= MIN_RGB_HISTOGRAM_INTERSECTION
        and hsv_intersection >= MIN_HSV_HISTOGRAM_INTERSECTION
        and rgb_bhattacharyya >= MIN_RGB_BHATTACHARYYA
        and maximum_mean_delta <= MAX_MEAN_CHANNEL_DELTA
    )
    return {
        "passed": passed,
        "reference": "Candidate B1",
        "method": (
            "composition-tolerant palette proxy using 8x8x8 RGB and 24x6x6 HSV "
            "histograms sampled at 384x256"
        ),
        "thresholds": {
            "minimum_rgb_histogram_intersection": MIN_RGB_HISTOGRAM_INTERSECTION,
            "minimum_hsv_histogram_intersection": MIN_HSV_HISTOGRAM_INTERSECTION,
            "minimum_rgb_bhattacharyya": MIN_RGB_BHATTACHARYYA,
            "maximum_mean_channel_delta": MAX_MEAN_CHANNEL_DELTA,
        },
        "candidate_mean_rgb": [round(value, 6) for value in candidate_mean],
        "reference_mean_rgb": [round(value, 6) for value in reference_mean],
        "mean_channel_absolute_delta": [
            round(value, 6) for value in mean_channel_delta
        ],
        "maximum_mean_channel_delta": round(maximum_mean_delta, 6),
        "rgb_histogram_intersection": round(rgb_intersection, 6),
        "hsv_histogram_intersection": round(hsv_intersection, 6),
        "rgb_bhattacharyya": round(rgb_bhattacharyya, 6),
    }


def _macrocell_contrast_coverage(gray: Image.Image) -> tuple[float, float, float]:
    columns, rows = MACROCELL_GRID
    standard_deviations: list[float] = []
    for row in range(rows):
        top = row * gray.height // rows
        bottom = (row + 1) * gray.height // rows
        for column in range(columns):
            left = column * gray.width // columns
            right = (column + 1) * gray.width // columns
            cell = gray.crop((left, top, right, bottom))
            try:
                standard_deviations.append(ImageStat.Stat(cell).stddev[0])
            finally:
                cell.close()
    ordered = sorted(standard_deviations)
    coverage = sum(
        value >= MACROCELL_MINIMUM_LUMA_STDDEV for value in standard_deviations
    ) / len(standard_deviations)
    return coverage, ordered[0], ordered[len(ordered) // 2]


def _scale_readability_record(image: Image.Image, scale: float) -> dict[str, Any]:
    if scale == 1.0:
        scaled = image.copy()
    else:
        scaled = image.resize(
            (round(image.width * scale), round(image.height * scale)),
            Image.Resampling.LANCZOS,
        )
    gray = scaled.convert("L")
    try:
        luma = ImageStat.Stat(gray)
        coverage, minimum_cell_stddev, median_cell_stddev = (
            _macrocell_contrast_coverage(gray)
        )
        return {
            "scale": scale,
            "width": scaled.width,
            "height": scaled.height,
            "luma_entropy_bits": round(gray.entropy(), 6),
            "luma_rms_contrast": round(luma.stddev[0], 6),
            "macrocell_contrast_coverage": round(coverage, 6),
            "minimum_macrocell_luma_stddev": round(minimum_cell_stddev, 6),
            "median_macrocell_luma_stddev": round(median_cell_stddev, 6),
        }
    finally:
        gray.close()
        scaled.close()


def downsample_readability_metrics(image: Image.Image) -> dict[str, Any]:
    native = _scale_readability_record(image, 1.0)
    records: list[dict[str, Any]] = []
    for scale in (0.5, 0.25):
        record = _scale_readability_record(image, scale)
        entropy_retention = (
            record["luma_entropy_bits"] / native["luma_entropy_bits"]
        )
        contrast_retention = (
            record["luma_rms_contrast"] / native["luma_rms_contrast"]
        )
        thresholds = DOWNSAMPLE_THRESHOLDS[scale]
        record.update(
            {
                "entropy_retention": round(entropy_retention, 6),
                "rms_contrast_retention": round(contrast_retention, 6),
                "thresholds": thresholds,
                "passed": (
                    entropy_retention
                    >= thresholds["minimum_entropy_retention"]
                    and contrast_retention
                    >= thresholds["minimum_rms_contrast_retention"]
                    and record["macrocell_contrast_coverage"]
                    >= thresholds["minimum_macrocell_contrast_coverage"]
                ),
            }
        )
        records.append(record)
    return {
        "passed": all(record["passed"] for record in records),
        "method": (
            "LANCZOS downsample; Shannon luma entropy, global RMS contrast, and "
            "24x16 macrocell contrast coverage are readability proxies"
        ),
        "macrocell_grid": list(MACROCELL_GRID),
        "minimum_macrocell_luma_stddev": MACROCELL_MINIMUM_LUMA_STDDEV,
        "native": native,
        "scales": records,
    }


def _vision_handoff(schema_path: Path) -> dict[str, Any]:
    return {
        "status": "required",
        "schema": _artifact(schema_path),
        "automated_audit_is_not_golden_acceptance": True,
        "checks": [
            {
                "id": "generated_text_or_pseudotext",
                "status": "requires_vision_review",
                "automated_claim": None,
                "reason": (
                    "Pixel statistics cannot reliably distinguish lettering, "
                    "pseudo-writing, readable symbols, signatures, or watermarks."
                ),
            },
            {
                "id": "strict_orthographic_plan_view",
                "status": "requires_vision_review",
                "automated_claim": None,
                "reason": (
                    "Perspective, peak faces, cliff facades, cast shadows, and scenic "
                    "mountain reading require semantic visual inspection."
                ),
            },
        ],
    }


def audit(
    *,
    final_path: Path,
    raw_path: Path,
    prompt_path: Path,
    reference_b1_path: Path,
    vision_schema_path: Path,
    report_path: Path,
    replace: bool = False,
) -> dict[str, Any]:
    if report_path.exists() and not replace:
        raise H4AuditError(f"refusing to overwrite existing output: {report_path}")
    inputs = (
        (final_path, EXPECTED_SHA256["final"], "H4 final"),
        (raw_path, EXPECTED_SHA256["raw"], "H4 raw"),
        (prompt_path, EXPECTED_SHA256["prompt"], "H4 generation prompt"),
        (
            reference_b1_path,
            EXPECTED_SHA256["reference_b1"],
            "Candidate B1 reference",
        ),
        (
            vision_schema_path,
            EXPECTED_SHA256["vision_schema"],
            "Vision QA schema",
        ),
    )
    for path, expected_hash, label in inputs:
        _assert_input(path, expected_hash, label)

    try:
        prompt_text = prompt_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise H4AuditError("H4 generation prompt must be valid UTF-8") from exc
    required_prompt_phrases = (
        "strict orthographic plan view",
        "all text and pseudo-text",
        "1536x1024 landscape RGB image",
    )
    missing_prompt_phrases = [
        phrase for phrase in required_prompt_phrases if phrase not in prompt_text
    ]
    if missing_prompt_phrases:
        raise H4AuditError(
            "H4 generation prompt lacks locked requirements: "
            + ", ".join(missing_prompt_phrases)
        )

    byte_identical = files_are_byte_identical(raw_path, final_path)
    if not byte_identical:
        raise H4AuditError("H4 raw and final PNGs are not byte-identical")

    final_record, final_image = inspect_png(final_path)
    raw_record, raw_image = inspect_png(raw_path)
    reference_record, reference_image = inspect_png(reference_b1_path)
    try:
        expected_image_contract = {
            "format": "PNG",
            "mode": "RGB",
            "width": EXPECTED_SIZE[0],
            "height": EXPECTED_SIZE[1],
            "bit_depth": 8,
            "png_color_type": 2,
            "alpha_or_transparency_present": False,
        }
        image_records = {
            "final": final_record,
            "raw": raw_record,
            "reference_b1": reference_record,
        }
        record_contract_results = {
            label: all(record[key] == value for key, value in expected_image_contract.items())
            for label, record in image_records.items()
        }
        profile_matches_reference = (
            _profile_signature(final_record) == _profile_signature(reference_record)
            and _profile_signature(raw_record) == _profile_signature(reference_record)
        )
        image_contract_passed = (
            all(record_contract_results.values()) and profile_matches_reference
        )
        image_contract = {
            "passed": image_contract_passed,
            "required": expected_image_contract,
            "records_passed": record_contract_results,
            "alpha_free": not final_record["alpha_or_transparency_present"],
            "profile_matches_b1": profile_matches_reference,
            "profile_interpretation": (
                "untagged RGB matching B1"
                if not final_record["profile_chunk_types"]
                and not final_record["icc_profile_present"]
                else "embedded profile state matches B1"
            ),
            "images": image_records,
        }
        boundary = boundary_metrics(final_image)
        palette = palette_continuity_metrics(final_image, reference_image)
        repetition = exact_repetition_metrics(final_image)
        downsample = downsample_readability_metrics(final_image)
    finally:
        final_image.close()
        raw_image.close()
        reference_image.close()

    automated_gates = {
        "sha256_locked_inputs": True,
        "raw_final_byte_identity": byte_identical,
        "image_contract_alpha_profile": image_contract["passed"],
        "boundary_proxy": boundary["passed"],
        "palette_continuity_with_b1": palette["passed"],
        "no_large_exact_repetition_proxy": repetition["passed"],
        "downsample_readability_proxy": downsample["passed"],
    }
    failed_gates = [name for name, passed in automated_gates.items() if not passed]
    if failed_gates:
        raise H4AuditError("automated QA gates failed: " + ", ".join(failed_gates))

    report = {
        "schema_version": "1.0.0",
        "id": "style-candidate-h-v4-plan-view-golden-board-automated-audit",
        "status": "passed",
        "scope": "automated artifact and raster proxies only",
        "decision": "automated-gates-passed-pending-vision",
        "generated_by": _artifact(Path(__file__).resolve()),
        "artifacts": {
            "final": _artifact(final_path),
            "raw": _artifact(raw_path),
            "prompt": {
                **_artifact(prompt_path),
                "utf8": True,
                "required_phrases_present": True,
            },
            "reference_b1": _artifact(reference_b1_path),
        },
        "identity": {
            "passed": True,
            "raw_final_byte_identical": byte_identical,
            "locked_sha256": {
                key: value
                for key, value in EXPECTED_SHA256.items()
                if key != "vision_schema"
            },
        },
        "image_contract": image_contract,
        "boundary": boundary,
        "palette_continuity": palette,
        "exact_repetition": repetition,
        "downsample_readability": downsample,
        "automated_gates": automated_gates,
        "vision_handoff": _vision_handoff(vision_schema_path),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final", type=Path, default=DEFAULT_FINAL)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--reference-b1", type=Path, default=DEFAULT_REFERENCE_B1)
    parser.add_argument("--vision-schema", type=Path, default=DEFAULT_VISION_SCHEMA)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing report after re-running all checks",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit(
            final_path=args.final.resolve(),
            raw_path=args.raw.resolve(),
            prompt_path=args.prompt.resolve(),
            reference_b1_path=args.reference_b1.resolve(),
            vision_schema_path=args.vision_schema.resolve(),
            report_path=args.report.resolve(),
            replace=args.replace,
        )
    except (H4AuditError, OSError, ValueError) as exc:
        print(f"Candidate H4 automated audit failed: {exc}")
        return 1
    palette = report["palette_continuity"]
    print(
        "Candidate H4 automated audit passed: "
        f"sha256={report['artifacts']['final']['sha256']} "
        f"rgb_palette_intersection={palette['rgb_histogram_intersection']} "
        "Vision review remains required for text and strict plan view"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
