#!/usr/bin/env python3
"""Build four TEMP-only highland probes from adjacent natural-ground grammar.

The frozen v18 board is the spatial authority.  Two road/city/forest/field/
highland-free neutral-ground rectangles provide the natural dry-print spatial
grammar.  Their coordinates are never pasted into the highland: independent
rotations, shifts, ImageGen-phase-driven nonlinear warps, cross-source mixing,
and middle-band projection create a new spatial field whose dominant
wavelengths are 12--45 pixels.  Locked ImageGen v15/v17 donors contribute only
registered warm-ochre colour statistics and the nonlinear displacement phase.

Every emitted raster and report stays under tmp/.  This exploration script has
no Golden, manifest, specification, control, or persistent-candidate authority.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/map-production"
OUT = ROOT / "tmp/map-production/k3-semantic-cleanup-v19-neighbor-synthesis"
V18 = (
    ROOT
    / "tmp/map-production/k3-semantic-cleanup-proof-v18"
    / "style-candidate-k-v3-semantic-cleanup-proof-v18.png"
)
V15 = (
    ROOT
    / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup"
    / "highland-planar-v15.png"
)
V17 = (
    ROOT
    / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup"
    / "highland-inverse-aquatint-v17.png"
)
P15 = (
    ROOT
    / "world/map-production/prompts"
    / "style-candidate-k-v3-highland-planar-donor-v15.generation.txt"
)
P17 = (
    ROOT
    / "world/map-production/prompts"
    / "style-candidate-k-v3-highland-inverse-aquatint-donor-v17.generation.txt"
)
HARNESS_PATH = SCRIPTS / "build_style_candidate_k3_highland_phase_synthesis.py"
K2_BUILDER_PATH = SCRIPTS / "build_style_candidate_k2_hybrid.py"

EXPECTED = {
    V18: "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882",
    V15: "5942a770e866fd1641156c141715cb55a473a65c7602a8075f0747e7b96e7602",
    V17: "4f64fcee2d5b1f0932f1d65fe460ba8bb1d4dff1b3ad68eafb75c0b7e72d9626",
    P15: "d52572ef0af1a6801e305bd507ea2c19d224fe23fb1024931ba1e7c85b2c575e",
    P17: "2483b3e00356dc51922f0130ddadfb2da098eaf306efc9008b6d228eb6436454",
    HARNESS_PATH: "22187f8ba853648c4aa8b75a8d2f7b8cf0d085c6ba49baf044f5ae6865b5a6f4",
}

TARGET_BOX = (930, 0, 1536, 560)
DONOR_BOX = (0, 47, 1254, 1206)
SOURCE_BOXES = {
    "central_southwest": (581, 641, 741, 801),
    "central_southeast": (881, 748, 1073, 940),
}
DOMINANT_WAVELENGTHS_PX = (12.0, 45.0)
PNG = {"format": "PNG", "compress_level": 9, "optimize": False}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


harness = load_module("neighbor_synthesis_harness", HARNESS_PATH)
k3 = harness.k3
k2_builder = load_module("neighbor_synthesis_k2_builder", K2_BUILDER_PATH)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def gaussian(array: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(
        array.astype(np.float32),
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REFLECT,
    )


def lab_l(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32)


def resized_rgb(rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    return cv2.resize(rgb, (width, height), interpolation=cv2.INTER_LANCZOS4)


def registered_lab(source_rgb: np.ndarray, target_lab: np.ndarray) -> np.ndarray:
    """Robustly register each donor Lab channel to the v18 highland palette."""
    source = cv2.cvtColor(source_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    result = source.copy()
    target_pixels = target_lab.reshape(-1, 3)
    source_pixels = source.reshape(-1, 3)
    for channel in range(3):
        source_q = np.quantile(source_pixels[:, channel], (0.10, 0.50, 0.90))
        target_q = np.quantile(target_pixels[:, channel], (0.10, 0.50, 0.90))
        source_span = max(float(source_q[2] - source_q[0]), 1.0)
        target_span = max(float(target_q[2] - target_q[0]), 1.0)
        scale = float(np.clip(target_span / source_span, 0.55, 2.40))
        result[..., channel] = (
            float(target_q[1])
            + (source[..., channel] - float(source_q[1])) * scale
        )
    return np.clip(result, 0.0, 255.0)


def transform_field(
    field: np.ndarray,
    angle_degrees: float,
    shift_xy: tuple[int, int],
) -> np.ndarray:
    height, width = field.shape
    matrix = cv2.getRotationMatrix2D(
        (0.5 * (width - 1), 0.5 * (height - 1)), angle_degrees, 1.0
    )
    rotated = cv2.warpAffine(
        field,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    return np.roll(rotated, shift=(shift_xy[1], shift_xy[0]), axis=(0, 1))


def band_residual(luminance: np.ndarray, fine_sigma: float, broad_sigma: float) -> np.ndarray:
    """Retain dry middle-scale material, suppressing pixels and broad clouds."""
    return gaussian(luminance, fine_sigma) - gaussian(luminance, broad_sigma)


def standardized(field: np.ndarray) -> np.ndarray:
    centered = field.astype(np.float32) - float(np.median(field))
    low, high = np.quantile(centered, (0.05, 0.95))
    scale = max(float(high - low) * 0.5, 1e-6)
    return np.clip(centered / scale, -1.75, 1.75)


def nonlinear_warp(
    field: np.ndarray,
    displacement_x: np.ndarray,
    displacement_y: np.ndarray,
    maximum_displacement_px: float,
) -> np.ndarray:
    height, width = field.shape
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    map_x = xx + maximum_displacement_px * standardized(displacement_x)
    map_y = yy + maximum_displacement_px * standardized(displacement_y)
    return cv2.remap(
        field.astype(np.float32),
        map_x,
        map_y,
        interpolation=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def warped_neighbor_score(
    authority_fields: list[np.ndarray],
    donor15_l: np.ndarray,
    donor17_l: np.ndarray,
    recipe: dict[str, Any],
) -> np.ndarray:
    """Preserve natural-ground higher-order grammar while destroying coordinates."""
    first = transform_field(
        authority_fields[0], recipe["angles"][0], recipe["shifts"][0]
    )
    second = transform_field(
        authority_fields[1], recipe["angles"][1], recipe["shifts"][1]
    )
    phase15 = transform_field(
        donor15_l,
        recipe["angles"][0] * -0.43,
        (recipe["shifts"][1][0], recipe["shifts"][0][1]),
    )
    phase17 = transform_field(
        donor17_l,
        recipe["angles"][1] * 0.37,
        (recipe["shifts"][0][0], recipe["shifts"][1][1]),
    )
    dx = gaussian(phase17, recipe["warp_sigma"]) - gaussian(
        phase17, recipe["warp_sigma"] * 3.0
    )
    dy = gaussian(phase15, recipe["warp_sigma"] * 1.17) - gaussian(
        phase15, recipe["warp_sigma"] * 3.4
    )
    first_warped = nonlinear_warp(
        first, dx, dy, recipe["maximum_displacement_px"]
    )
    second_warped = nonlinear_warp(
        second,
        np.flip(dy, axis=1),
        np.flip(dx, axis=0),
        recipe["maximum_displacement_px"] * 0.83,
    )
    weight_a, weight_b = recipe["authority_weights"]
    mixed = weight_a * first_warped + weight_b * second_warped
    return band_residual(mixed, recipe["fine_sigma"], recipe["broad_sigma"])


def palette_curve(
    baseline_lab: np.ndarray,
    registered15: np.ndarray,
    registered17: np.ndarray,
    donor_weight: float,
    contrast: float,
    entries: int = 8192,
) -> np.ndarray:
    """Blend v18 palette with registered v15/v17 empirical Lab statistics."""
    quantiles = (np.arange(entries, dtype=np.float64) + 0.5) / entries

    def curve(samples: np.ndarray) -> np.ndarray:
        pixels = samples.reshape(-1, 3).astype(np.float64)
        order = np.argsort(pixels[:, 0], kind="stable")
        pixels = pixels[order]
        source_q = (np.arange(pixels.shape[0], dtype=np.float64) + 0.5) / pixels.shape[0]
        return np.column_stack(
            [np.interp(quantiles, source_q, pixels[:, channel]) for channel in range(3)]
        )

    baseline_curve = curve(baseline_lab)
    donor_curve = 0.5 * curve(registered15) + 0.5 * curve(registered17)
    mixed = (1.0 - donor_weight) * baseline_curve + donor_weight * donor_curve
    median = np.median(baseline_lab.reshape(-1, 3), axis=0)
    return median + contrast * (mixed - median)


def rank_colourize(score: np.ndarray, curve: np.ndarray) -> np.ndarray:
    order = np.argsort(score.ravel(), kind="stable")
    ranks = np.empty(score.size, np.int64)
    ranks[order] = np.arange(score.size, dtype=np.int64)
    indices = np.minimum(
        (ranks.astype(np.float64) * curve.shape[0] / score.size).astype(np.int64),
        curve.shape[0] - 1,
    )
    lab = curve[indices].reshape((*score.shape, 3))
    return cv2.cvtColor(
        np.clip(np.rint(lab), 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB
    )


def frequency_contract(score: np.ndarray) -> dict[str, Any]:
    centered = score.astype(np.float64) - float(np.mean(score))
    transformed = np.fft.fft2(centered)
    power = np.abs(transformed) ** 2
    height, width = score.shape
    fy = np.fft.fftfreq(height)
    fx = np.fft.fftfreq(width)
    yy, xx = np.meshgrid(fy, fx, indexing="ij")
    radius = np.hypot(xx, yy)
    dominant = (radius >= 1.0 / 45.0) & (radius <= 1.0 / 12.0)
    shoulder = (radius >= 1.0 / 64.0) & (radius <= 1.0 / 8.0)
    total = float(power[radius > 0].sum())
    return {
        "dominant_wavelengths_px": [12.0, 45.0],
        "dominant_band_power_fraction": round(float(power[dominant].sum()) / total, 9),
        "supported_8_to_64px_power_fraction": round(float(power[shoulder].sum()) / total, 9),
        "passed_supported_band": bool(float(power[shoulder].sum()) / total >= 0.90),
    }


def source_clone_proxy(
    candidate_crop: np.ndarray,
    sources: dict[str, np.ndarray],
) -> dict[str, Any]:
    """Fail if any native 64px RGB block is copied exactly from an authority."""
    block = 64
    source_hashes: set[str] = set()
    for source in sources.values():
        for y in range(0, source.shape[0] - block + 1, 16):
            for x in range(0, source.shape[1] - block + 1, 16):
                source_hashes.add(hashlib.sha256(source[y:y + block, x:x + block].tobytes()).hexdigest())
    matches = 0
    for y in range(0, candidate_crop.shape[0] - block + 1, 16):
        for x in range(0, candidate_crop.shape[1] - block + 1, 16):
            digest = hashlib.sha256(candidate_crop[y:y + block, x:x + block].tobytes()).hexdigest()
            matches += int(digest in source_hashes)
    return {
        "block_px": block,
        "stride_px": 16,
        "exact_source_block_matches": matches,
        "passed": matches == 0,
    }


def safe_authority_mask() -> np.ndarray:
    semantic = k3.derive_masks()
    canonical = k2_builder.canonical_masks()
    safe = canonical["mainland"].copy()
    exclusions = (
        (canonical["river_edge"], 20),
        (canonical["road_edge"], 22),
        (canonical["city"], 22),
        (canonical["port"], 22),
        (canonical["field_union"], 22),
        (semantic["forest_shape"], 16),
        (semantic["highland_shape"], 20),
    )
    for exclusion, radius in exclusions:
        safe &= ~k3.dilate(exclusion, radius)
    safe[:30] = False
    safe[-30:] = False
    safe[:, :30] = False
    safe[:, -30:] = False
    return safe


def save_authority_contacts(sources: dict[str, np.ndarray]) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for name, source in sources.items():
        path = OUT / f"authority-{name}-400pct-nearest.png"
        preview = Image.fromarray(source, "RGB").resize(
            (source.shape[1] * 4, source.shape[0] * 4), Image.Resampling.NEAREST
        )
        preview.save(path, **PNG)
        preview.close()
        records[name] = {
            "path": relative(path),
            "sha256": sha256(path),
            "review_scale": "400% nearest-neighbour",
        }
    return records


def main() -> None:
    for path, digest in EXPECTED.items():
        if not path.is_file() or sha256(path) != digest:
            raise RuntimeError(f"frozen input missing or hash-mismatched: {path}")
    persistent = (k3.RAW, k3.FINAL, k3.RECEIPT, k3.AUDIT)
    if any(path.exists() for path in persistent):
        raise RuntimeError("persistent K3 output unexpectedly exists")

    OUT.mkdir(parents=True, exist_ok=True)
    harness.OUT = OUT
    baseline = np.asarray(Image.open(V18).convert("RGB"), np.uint8)
    masks = k3.derive_masks()
    safe = safe_authority_mask()
    sources: dict[str, np.ndarray] = {}
    source_records: dict[str, Any] = {}
    for name, (left, top, right, bottom) in SOURCE_BOXES.items():
        if not np.all(safe[top:bottom, left:right]):
            raise RuntimeError(f"neutral-ground authority is not fully safe: {name}")
        source = baseline[top:bottom, left:right].copy()
        sources[name] = source
        source_records[name] = {
            "box_xyxy": [left, top, right, bottom],
            "size": [right - left, bottom - top],
            "safe_pixels": int(safe[top:bottom, left:right].sum()),
            "total_pixels": int((right - left) * (bottom - top)),
            "source_rgb_sha256": hashlib.sha256(source.tobytes()).hexdigest(),
            "excluded_semantics": [
                "water/coast", "river", "road", "city", "port", "field",
                "forest", "highland", "outer-map edge",
            ],
        }
    authority_contacts = save_authority_contacts(sources)

    left, top, right, bottom = TARGET_BOX
    target_height = bottom - top
    target_width = right - left
    permission = masks["highland_edit"]
    permission_crop = permission[top:bottom, left:right]
    baseline_crop = baseline[top:bottom, left:right]
    baseline_lab_full = cv2.cvtColor(baseline, cv2.COLOR_RGB2LAB).astype(np.float32)
    baseline_highland_lab = baseline_lab_full[permission]

    donor_images: dict[str, np.ndarray] = {}
    for name, path in (("v15", V15), ("v17", V17)):
        opened = np.asarray(Image.open(path).convert("RGB"), np.uint8)
        dleft, dtop, dright, dbottom = DONOR_BOX
        donor_images[name] = resized_rgb(
            opened[dtop:dbottom, dleft:dright], target_width, target_height
        )
    registered15 = registered_lab(donor_images["v15"], baseline_highland_lab)
    registered17 = registered_lab(donor_images["v17"], baseline_highland_lab)

    authority_fields: list[np.ndarray] = []
    for source in sources.values():
        mapped = resized_rgb(source, target_width, target_height)
        authority_fields.append(lab_l(mapped))

    donor15_l = lab_l(donor_images["v15"])
    donor17_l = lab_l(donor_images["v17"])
    baseline_activity = float(
        harness.weave(baseline, masks["highland_edit"])["activity_fraction"]
    )
    alpha = k3.boundary_locked_alpha(
        masks["highland_edit"], full_by_px=7.0, locked_boundary_px=2.0
    )

    recipes = (
        {
            "name": "neighbor-a-natural-dry-balanced",
            "authority_weights": (0.62, 0.38),
            "angles": (19.0, -37.0),
            "shifts": ((83, 47), (-71, 109)),
            "donor_weight": 0.06,
            "contrast": 0.34,
            "warp_sigma": 20.0,
            "maximum_displacement_px": 18.0,
            "fine_sigma": 1.05,
            "broad_sigma": 24.0,
        },
        {
            "name": "neighbor-b-natural-dry-open",
            "authority_weights": (0.48, 0.52),
            "angles": (-29.0, 61.0),
            "shifts": ((-101, 67), (131, -53)),
            "donor_weight": 0.08,
            "contrast": 0.29,
            "warp_sigma": 24.0,
            "maximum_displacement_px": 22.0,
            "fine_sigma": 1.25,
            "broad_sigma": 27.0,
        },
        {
            "name": "neighbor-c-natural-mineral-coarse",
            "authority_weights": (0.72, 0.28),
            "angles": (43.0, -73.0),
            "shifts": ((59, -127), (-149, 31)),
            "donor_weight": 0.08,
            "contrast": 0.38,
            "warp_sigma": 18.0,
            "maximum_displacement_px": 16.0,
            "fine_sigma": 0.90,
            "broad_sigma": 30.0,
        },
        {
            "name": "neighbor-d-natural-warm-restrained",
            "authority_weights": (0.55, 0.45),
            "angles": (-53.0, 97.0),
            "shifts": ((-43, -137), (157, 79)),
            "donor_weight": 0.10,
            "contrast": 0.31,
            "warp_sigma": 26.0,
            "maximum_displacement_px": 24.0,
            "fine_sigma": 1.35,
            "broad_sigma": 25.0,
        },
    )

    records: dict[str, Any] = {}
    for recipe in recipes:
        score = warped_neighbor_score(
            authority_fields, donor15_l, donor17_l, recipe
        )
        curve = palette_curve(
            baseline_highland_lab,
            registered15,
            registered17,
            recipe["donor_weight"],
            recipe["contrast"],
        )
        local_plate = rank_colourize(score, curve)
        donor_canvas = baseline.copy()
        donor_canvas[top:bottom, left:right] = local_plate
        candidate = k3.composite_with_alpha(baseline, donor_canvas, alpha)
        record = harness.evaluate(
            recipe["name"], candidate, baseline, masks, baseline_activity
        )
        clone = source_clone_proxy(local_plate, sources)
        frequency = frequency_contract(score)
        if not clone["passed"] or not frequency["passed_supported_band"]:
            record["status"] = "failed-neighbor-synthesis-contract"
            for gate, passed in (
                ("no_exact_authority_patch_clone", clone["passed"]),
                ("supported_8_to_64px_power", frequency["passed_supported_band"]),
            ):
                record["automated_gates"][gate] = passed
                if not passed and gate not in record["failed_gates"]:
                    record["failed_gates"].append(gate)
            record["vision_handoff"]["required"] = False
        else:
            record["automated_gates"]["no_exact_authority_patch_clone"] = True
            record["automated_gates"]["supported_8_to_64px_power"] = True
        record["neighbor_synthesis"] = {
            "recipe": recipe,
            "frequency_contract": frequency,
            "source_clone_proxy": clone,
            "spatial_authority": list(SOURCE_BOXES),
            "direct_source_pixels_copied": False,
            "phase_or_coordinate_clone_used": False,
            "v15_v17_contribution": (
                "registered warm-ochre empirical Lab curve plus bounded phase perturbation only"
            ),
        }
        report_path = OUT / recipe["name"] / f"{recipe['name']}.full-audit.json"
        report_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        record["report"] = {
            "path": relative(report_path),
            "sha256": sha256(report_path),
        }
        records[recipe["name"]] = record

    report = {
        "schema_version": "1.0.0",
        "status": "TEMP-only neighbor synthesis; no acceptance authority",
        "temporary_review_only": True,
        "decision_authority": False,
        "golden_accepted": False,
        "persistent_outputs_emitted": False,
        "thresholds_changed": False,
        "output_boundary": relative(OUT),
        "candidate_limit": 4,
        "candidate_count": len(records),
        "inputs": {
            "v18": {"path": relative(V18), "sha256": EXPECTED[V18]},
            "v15": {"path": relative(V15), "sha256": EXPECTED[V15]},
            "v15_prompt": {"path": relative(P15), "sha256": EXPECTED[P15]},
            "v17": {"path": relative(V17), "sha256": EXPECTED[V17]},
            "v17_prompt": {"path": relative(P17), "sha256": EXPECTED[P17]},
            "unchanged_gate_harness": {
                "path": relative(HARNESS_PATH),
                "sha256": EXPECTED[HARNESS_PATH],
            },
        },
        "neutral_ground_authority": source_records,
        "authority_contacts": authority_contacts,
        "operation": {
            "semantic_change": "highland permitted interior material only",
            "target_crop_xyxy": list(TARGET_BOX),
            "dominant_wavelength_contract_px": list(DOMINANT_WAVELENGTHS_PX),
            "spatial_synthesis": (
                "two-source deterministic nonlinear phase warp and middle-band projection"
            ),
            "source_coordinates_destroyed": True,
            "source_rgb_or_patch_paste_used": False,
            "gaussian_random_field_used": False,
            "synthetic_random_noise_layer_used": False,
            "periodic_tile_used": False,
            "ImageGen_lineage": (
                "v15/v17 registered warm-ochre empirical Lab statistics and bounded phase perturbation"
            ),
            "boundary_alpha": {"locked_boundary_px": 2.0, "full_by_px": 7.0},
        },
        "records": records,
    }
    report_path = OUT / "neighbor-synthesis-search.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "report": {"path": relative(report_path), "sha256": sha256(report_path)},
                "variants": {
                    name: {
                        "status": record["status"],
                        "failed_gates": record["failed_gates"],
                        "activity": record["weave_reduction"]["candidate"]["activity_fraction"],
                        "orientation": record["weave_reduction"]["orientation"]["global_gradient_orientation_coherence"],
                        "strict_highland": record["strict_content"]["highland"],
                        "palette": record["global_gates"]["palette"],
                        "downsample": record["global_gates"]["downsample"],
                        "frequency_contract": record["neighbor_synthesis"]["frequency_contract"],
                        "candidate": record["candidate"],
                        "contacts": record["contacts"],
                    }
                    for name, record in records.items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
