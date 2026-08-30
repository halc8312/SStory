#!/usr/bin/env python3
"""Fail-closed, statistics-only Phase 5 highland detail exemplar bridge.

The locked raster is never sampled into the destination.  It contributes only
whole-raster scalar measurements of fine-scale luminance energy and density.
Destination detail is synthesized from the renderer seed and native global
pixel coordinates, then clipped to caller-supplied canonical and protected
masks.  Consequently no source pixel, geometry, coordinate, label, topology,
or colour palette can cross this bridge.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageStat


REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET_SHEET_ID = "sheet_region_soaring_mountains_region"
TARGET_FEATURE_ID = "elysion_soaring_mountains_axis"
DEFAULT_EXEMPLAR_PATH = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "style-assets"
    / "highland-detail-exemplar-v1.png"
)
EXPECTED_EXEMPLAR_SHA256 = (
    "c7fcd3da5fba6fe08f10fd1e0fe16bdb2884a0a04386de828f923d660de8f1a2"
)
EXPECTED_EXEMPLAR_SIZE = (1536, 1024)
PROMPT_PATH = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "prompts"
    / "highland-detail-exemplar-v1.generation.txt"
)
EXPECTED_PROMPT_SHA256 = (
    "588ccd983683e6280e2cf31bec2c4beb8bca248ca789e733fcc33fec5f361154"
)
PROVENANCE_RECEIPT_PATH = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "prompts"
    / "highland-detail-exemplar-v1.provenance-receipt.json"
)
EXPECTED_PROVENANCE_RECEIPT_SHA256 = (
    "e406ab65578a00d9102285b9a3ac7c985d313109bbd3648aef6605cd44f87218"
)
ROOT_VISION_REVIEW_PATH = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "qa"
    / "highland-detail-exemplar-v1-root-vision.json"
)
EXPECTED_ROOT_VISION_REVIEW_SHA256 = (
    "f72986e7167b8ec81872da97746828e8b84266ffd575f23241a62c4a69f6194e"
)
CONTRACT_ID = "sstory-phase5-highland-detail-exemplar-v1"
PROFILE_METHOD = "whole-raster-luma-high-pass-scalar-statistics-v1"


class HighlandDetailExemplarError(ValueError):
    """Raised when the optional exemplar cannot prove its exact contract."""


def _read_locked_payload(path: Path) -> tuple[bytes, str]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise HighlandDetailExemplarError(
            f"could not read highland detail exemplar {path}: {exc}"
        ) from exc
    return payload, hashlib.sha256(payload).hexdigest()


def _bind_provenance_file(
    path: Path,
    expected_sha256: str,
    *,
    label: str,
) -> tuple[bytes, dict[str, str]]:
    resolved = path.resolve()
    if not resolved.is_file() or path.is_symlink():
        raise HighlandDetailExemplarError(
            f"{label} must be a regular non-symlink file: {resolved}"
        )
    payload, actual_sha256 = _read_locked_payload(resolved)
    if actual_sha256 != expected_sha256:
        raise HighlandDetailExemplarError(
            f"{label} SHA-256 mismatch: expected={expected_sha256}, "
            f"actual={actual_sha256}"
        )
    return payload, {"path": _repo_path(resolved), "sha256": actual_sha256}


def _load_json_document(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighlandDetailExemplarError(
            f"{label} must be valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise HighlandDetailExemplarError(f"{label} must contain one JSON object")
    return value


def _validate_provenance_graph() -> dict[str, dict[str, str]]:
    _, prompt = _bind_provenance_file(
        PROMPT_PATH,
        EXPECTED_PROMPT_SHA256,
        label="highland detail exemplar prompt",
    )
    receipt_payload, receipt = _bind_provenance_file(
        PROVENANCE_RECEIPT_PATH,
        EXPECTED_PROVENANCE_RECEIPT_SHA256,
        label="highland detail exemplar provenance receipt",
    )
    review_payload, review = _bind_provenance_file(
        ROOT_VISION_REVIEW_PATH,
        EXPECTED_ROOT_VISION_REVIEW_SHA256,
        label="highland detail exemplar Root Vision review",
    )
    receipt_document = _load_json_document(
        receipt_payload,
        label="highland detail exemplar provenance receipt",
    )
    review_document = _load_json_document(
        review_payload,
        label="highland detail exemplar Root Vision review",
    )
    if (
        receipt_document.get("id") != "highland-detail-exemplar-v1-generation"
        or receipt_document.get("status") != "accepted-material-authority"
        or receipt_document.get("authority_inventory_complete") is not True
        or receipt_document.get("prompt")
        != {**prompt, "exact_prompt_preserved": True}
        or receipt_document.get("output")
        != {
            "path": _repo_path(DEFAULT_EXEMPLAR_PATH),
            "sha256": EXPECTED_EXEMPLAR_SHA256,
            "bytes": 4_222_690,
            "size": [EXPECTED_EXEMPLAR_SIZE[0], EXPECTED_EXEMPLAR_SIZE[1]],
            "mode": "RGB",
        }
        or receipt_document.get("root_vision_review", {}).get("path")
        != review["path"]
        or receipt_document.get("root_vision_review", {}).get("sha256")
        != review["sha256"]
        or receipt_document.get("root_vision_review", {}).get("vision_score")
        != 94
    ):
        raise HighlandDetailExemplarError(
            "highland detail exemplar provenance receipt graph changed"
        )
    source = review_document.get("source", {})
    decision = review_document.get("decision", {})
    if (
        review_document.get("status")
        != "accepted-as-high-zoom-material-authority"
        or review_document.get("decision_authority") is not True
        or source.get("path") != _repo_path(DEFAULT_EXEMPLAR_PATH)
        or source.get("sha256") != EXPECTED_EXEMPLAR_SHA256
        or source.get("size")
        != [EXPECTED_EXEMPLAR_SIZE[0], EXPECTED_EXEMPLAR_SIZE[1]]
        or source.get("mode") != "RGB"
        or decision.get("vision_score") != 94
    ):
        raise HighlandDetailExemplarError(
            "highland detail exemplar Root Vision contract changed"
        )
    return {
        "prompt": prompt,
        "generation_receipt": receipt,
        "root_vision_review": review,
    }


def _repo_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _extract_scalar_profile(source: Image.Image) -> dict[str, Any]:
    """Return aggregate detail statistics with no transferable spatial data."""

    sample = source.convert("L")
    sample.thumbnail((384, 256), Image.Resampling.LANCZOS)
    try:
        bands: list[dict[str, float | int]] = []
        for radius in (1, 2, 4):
            blurred = sample.filter(ImageFilter.GaussianBlur(radius=radius))
            residual = ImageChops.difference(sample, blurred)
            try:
                stat = ImageStat.Stat(residual)
                bands.append(
                    {
                        "gaussian_radius_px": radius,
                        "mean_absolute_luma_levels": round(stat.mean[0], 6),
                        "rms_luma_levels": round(stat.rms[0], 6),
                    }
                )
            finally:
                residual.close()
                blurred.close()

        edges = sample.filter(ImageFilter.FIND_EDGES)
        try:
            if edges.width > 2 and edges.height > 2:
                edge_core = edges.crop((1, 1, edges.width - 1, edges.height - 1))
            else:
                edge_core = edges.copy()
            try:
                histogram = edge_core.histogram()
                edge_density = sum(histogram[18:]) / max(
                    1, edge_core.width * edge_core.height
                )
            finally:
                edge_core.close()
        finally:
            edges.close()

        fine_rms = float(bands[1]["rms_luma_levels"])
        fine_mean = float(bands[1]["mean_absolute_luma_levels"])
        # Deliberately narrow limits prevent the exemplar from importing broad
        # tone or becoming a new palette.  These two scalars control only the
        # amplitude and occupancy of newly synthesized luma micro-detail.
        amplitude = max(1, min(4, int(math.floor(fine_rms * 0.22 + 0.5))))
        occupancy = max(0.12, min(0.34, 0.12 + fine_mean / 72.0))
        profile: dict[str, Any] = {
            "method": PROFILE_METHOD,
            "whole_raster_aggregate_only": True,
            "luma_high_pass_bands": bands,
            "edge_density_over_18_luma_levels": round(edge_density, 8),
            "derived_luma_amplitude_levels": amplitude,
            "derived_occupancy_fraction": round(occupancy, 8),
            "source_pixels_retained": 0,
            "source_geometry_retained": False,
            "source_coordinates_retained": False,
            "source_palette_retained": False,
            "source_labels_retained": False,
        }
        profile_payload = json.dumps(
            profile, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        profile["profile_sha256"] = hashlib.sha256(profile_payload).hexdigest()
        return profile
    finally:
        sample.close()


def validate_production_exemplar() -> dict[str, Any]:
    """Validate and summarize the one exact production exemplar.

    This function intentionally accepts no path or digest override.  Production
    callers can therefore either use the reviewed asset at the reviewed path or
    fail closed.  Tests may patch module constants without widening the public
    contract.
    """

    path = DEFAULT_EXEMPLAR_PATH.resolve()
    if not path.is_file():
        raise HighlandDetailExemplarError(
            f"highland detail exemplar does not exist: {path}"
        )
    if path.is_symlink():
        raise HighlandDetailExemplarError(
            f"highland detail exemplar must be a regular file, not a symlink: {path}"
        )
    payload, actual_sha256 = _read_locked_payload(path)
    if actual_sha256 != EXPECTED_EXEMPLAR_SHA256:
        raise HighlandDetailExemplarError(
            "highland detail exemplar SHA-256 mismatch: "
            f"expected={EXPECTED_EXEMPLAR_SHA256}, actual={actual_sha256}"
        )

    try:
        with Image.open(io.BytesIO(payload)) as opened:
            opened.load()
            if opened.format != "PNG":
                raise HighlandDetailExemplarError(
                    f"highland detail exemplar format must be PNG, got {opened.format}"
                )
            if opened.mode != "RGB":
                raise HighlandDetailExemplarError(
                    f"highland detail exemplar mode must be RGB, got {opened.mode}"
                )
            if opened.size != EXPECTED_EXEMPLAR_SIZE:
                raise HighlandDetailExemplarError(
                    "highland detail exemplar dimensions changed: "
                    f"expected={EXPECTED_EXEMPLAR_SIZE}, actual={opened.size}"
                )
            if opened.info.get("transparency") is not None:
                raise HighlandDetailExemplarError(
                    "highland detail exemplar must not contain transparency"
                )
            if opened.info.get("icc_profile"):
                raise HighlandDetailExemplarError(
                    "highland detail exemplar must not contain an ICC profile"
                )
            profile = _extract_scalar_profile(opened)
    except HighlandDetailExemplarError:
        raise
    except (OSError, ValueError) as exc:
        raise HighlandDetailExemplarError(
            f"could not decode highland detail exemplar {path}: {exc}"
        ) from exc

    provenance = _validate_provenance_graph()
    return {
        "status": "locked",
        "contract_id": CONTRACT_ID,
        "path": _repo_path(path),
        "sha256": actual_sha256,
        "format": "PNG",
        "mode": "RGB",
        "width": EXPECTED_EXEMPLAR_SIZE[0],
        "height": EXPECTED_EXEMPLAR_SIZE[1],
        "profile": profile,
        "provenance": provenance,
        "allowed_transfer": "aggregate-material-detail-statistics-only",
        "copied_pixels": 0,
        "source_geometry_used": False,
        "source_absolute_coordinates_used": False,
        "source_global_palette_used": False,
        "source_labels_used": False,
    }


def _mask_pixel_count(mask: Image.Image) -> int:
    histogram = mask.histogram()
    return sum(histogram[128:])


def _mixed_coordinate_word(global_x: int, global_y: int, seed_word: int) -> int:
    """Return a stable 64-bit word without referring to source coordinates."""

    mask = 0xFFFFFFFFFFFFFFFF
    value = (
        (global_x & mask) * 0x9E3779B185EBCA87
        ^ (global_y & mask) * 0xC2B2AE3D27D4EB4F
        ^ seed_word
    ) & mask
    value ^= value >> 30
    value = (value * 0xBF58476D1CE4E5B9) & mask
    value ^= value >> 27
    value = (value * 0x94D049BB133111EB) & mask
    value ^= value >> 31
    return value & mask


def apply_production_exemplar(
    image: Image.Image,
    canonical_mountain_mask: Image.Image,
    protected_mask: Image.Image,
    *,
    sheet_id: str,
    feature_id: str,
    global_pixel_origin: tuple[int, int],
    seed: int,
    enabled: bool,
) -> dict[str, Any] | None:
    """Apply deterministic luma micro-detail under the exact production gate.

    Disabled and non-target sheets return before touching the exemplar path.
    The destination is modified in place only after every lock and mask
    invariant has been proven.
    """

    if not enabled or sheet_id != TARGET_SHEET_ID:
        return None
    if feature_id != TARGET_FEATURE_ID:
        raise HighlandDetailExemplarError(
            "highland detail exemplar target feature mismatch: "
            f"expected={TARGET_FEATURE_ID}, actual={feature_id}"
        )
    if image.mode not in {"RGB", "RGBA"}:
        raise HighlandDetailExemplarError(
            f"highland detail destination must be RGB or RGBA, got {image.mode}"
        )
    if canonical_mountain_mask.mode != "L" or protected_mask.mode != "L":
        raise HighlandDetailExemplarError("highland detail masks must use mode L")
    if not (
        image.size == canonical_mountain_mask.size == protected_mask.size
    ):
        raise HighlandDetailExemplarError(
            "highland detail destination and masks must have identical dimensions"
        )
    if (
        not isinstance(global_pixel_origin, tuple)
        or len(global_pixel_origin) != 2
        or any(not isinstance(value, int) for value in global_pixel_origin)
    ):
        raise HighlandDetailExemplarError(
            "highland detail global pixel origin must be an integer pair"
        )

    lock = validate_production_exemplar()
    profile = lock["profile"]
    provenance = lock.get("provenance")
    if (
        lock.get("status") != "locked"
        or lock.get("contract_id") != CONTRACT_ID
        or lock.get("sha256") != EXPECTED_EXEMPLAR_SHA256
        or lock.get("allowed_transfer")
        != "aggregate-material-detail-statistics-only"
        or lock.get("copied_pixels") != 0
        or not isinstance(provenance, dict)
        or provenance.get("prompt", {}).get("sha256")
        != EXPECTED_PROMPT_SHA256
        or provenance.get("generation_receipt", {}).get("sha256")
        != EXPECTED_PROVENANCE_RECEIPT_SHA256
        or provenance.get("root_vision_review", {}).get("sha256")
        != EXPECTED_ROOT_VISION_REVIEW_SHA256
        or any(
            lock.get(field) is not False
            for field in (
                "source_geometry_used",
                "source_absolute_coordinates_used",
                "source_global_palette_used",
                "source_labels_used",
            )
        )
    ):
        raise HighlandDetailExemplarError(
            "highland detail exemplar lock is not statistics-only"
        )
    if (
        profile.get("method") != PROFILE_METHOD
        or profile.get("whole_raster_aggregate_only") is not True
        or profile.get("source_pixels_retained") != 0
        or any(
            profile.get(field) is not False
            for field in (
                "source_geometry_retained",
                "source_coordinates_retained",
                "source_palette_retained",
                "source_labels_retained",
            )
        )
    ):
        raise HighlandDetailExemplarError(
            "highland detail exemplar profile method is not production-safe"
        )
    amplitude = profile.get("derived_luma_amplitude_levels")
    occupancy = profile.get("derived_occupancy_fraction")
    if (
        not isinstance(amplitude, int)
        or not 1 <= amplitude <= 4
        or not isinstance(occupancy, (int, float))
        or not 0.12 <= float(occupancy) <= 0.34
    ):
        raise HighlandDetailExemplarError(
            "highland detail exemplar derived parameters are out of contract"
        )

    safe_mask = ImageChops.subtract(canonical_mountain_mask, protected_mask)
    try:
        canonical_pixels = _mask_pixel_count(canonical_mountain_mask)
        safe_pixels = _mask_pixel_count(safe_mask)
        protected_intersection = ImageChops.multiply(
            canonical_mountain_mask, protected_mask
        )
        try:
            protected_overlap = _mask_pixel_count(protected_intersection)
        finally:
            protected_intersection.close()
        if canonical_pixels == 0:
            raise HighlandDetailExemplarError(
                "canonical highland detail mountain mask is empty"
            )
        if safe_pixels == 0:
            raise HighlandDetailExemplarError(
                "protected topology leaves no safe highland detail pixels"
            )

        namespace_digest = hashlib.sha256(
            f"{CONTRACT_ID}\0{seed}".encode("utf-8")
        ).digest()
        seed_word = int.from_bytes(namespace_digest[:8], "big")
        threshold = int(float(occupancy) * 65536)
        left, top = global_pixel_origin
        safe = safe_mask.load()
        changed_pixels = 0
        bbox = safe_mask.getbbox()
        if bbox is None:
            raise HighlandDetailExemplarError(
                "protected topology leaves no safe highland detail bounds"
            )
        candidate = image.copy()
        try:
            pixels = candidate.load()
            for y in range(bbox[1], bbox[3]):
                global_y = top + y
                for x in range(bbox[0], bbox[2]):
                    if safe[x, y] < 128:
                        continue
                    word = _mixed_coordinate_word(left + x, global_y, seed_word)
                    if (word & 0xFFFF) >= threshold:
                        continue
                    magnitude = 1 + ((word >> 16) % amplitude)
                    delta = magnitude if ((word >> 24) & 1) else -magnitude
                    pixel = pixels[x, y]
                    channels = pixel[:3]
                    if any(not 0 <= channel + delta <= 255 for channel in channels):
                        continue
                    changed = tuple(channel + delta for channel in channels)
                    if image.mode == "RGBA":
                        pixels[x, y] = (*changed, pixel[3])
                    else:
                        pixels[x, y] = changed
                    changed_pixels += 1
            if changed_pixels == 0:
                raise HighlandDetailExemplarError(
                    "highland detail exemplar produced no destination changes"
                )
            image.paste(candidate)
        finally:
            candidate.close()
    finally:
        safe_mask.close()

    return {
        "status": "applied",
        "contract_id": CONTRACT_ID,
        "target_sheet_id": TARGET_SHEET_ID,
        "target_feature_id": TARGET_FEATURE_ID,
        "input": lock,
        "application": {
            "mode": "deterministic-native-global-luma-microdetail",
            "canonical_mountain_mask_pixels": canonical_pixels,
            "protected_overlap_pixels": protected_overlap,
            "safe_mask_pixels": safe_pixels,
            "changed_pixels": changed_pixels,
            "changes_outside_canonical_mountain_mask": 0,
            "changes_inside_protected_mask": 0,
            "source_pixels_copied": 0,
            "source_geometry_used": False,
            "source_absolute_coordinates_used": False,
            "source_global_palette_used": False,
            "labels_transferred": False,
            "roads_transferred": False,
            "water_transferred": False,
            "protected_topology_transferred": False,
            "destination_chroma_modified": False,
            "destination_alpha_modified": False,
            "destination_native_global_coordinates_used": True,
            "canonical_mountain_mask_enforced": True,
        },
    }
