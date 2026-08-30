#!/usr/bin/env python3
"""Build at most four TEMP-only open-scumble highland probes.

The frozen ImageGen v15 donor supplies only the broad carrier locations and
colour target.  Its solid islands are replaced by disconnected dry-pigment
fragments whose stochastic occupancy comes from the frozen ImageGen v17
residual.  Fragment amplitudes are bounded by the residual distribution of
accepted central ground in frozen v18.  No Gaussian-blurred synthesis field is
used.  This exploration cannot write a persistent candidate, control, spec, or
manifest.
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
OUT = ROOT / "tmp/map-production/k3-semantic-cleanup-v19-open-scumble"
V18 = ROOT / (
    "world/map-production/style-assets/k3-v18-reconstruction-base.png"
)
V15 = ROOT / (
    "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/"
    "highland-planar-v15.png"
)
P15 = ROOT / (
    "world/map-production/prompts/"
    "style-candidate-k-v3-highland-planar-donor-v15.generation.txt"
)
V17 = ROOT / (
    "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/"
    "highland-inverse-aquatint-v17.png"
)
P17 = ROOT / (
    "world/map-production/prompts/"
    "style-candidate-k-v3-highland-inverse-aquatint-donor-v17.generation.txt"
)
HARNESS = SCRIPTS / "build_style_candidate_k3_highland_phase_synthesis.py"

EXPECTED = {
    V18: "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882",
    V15: "5942a770e866fd1641156c141715cb55a473a65c7602a8075f0747e7b96e7602",
    P15: "d52572ef0af1a6801e305bd507ea2c19d224fe23fb1024931ba1e7c85b2c575e",
    V17: "4f64fcee2d5b1f0932f1d65fe460ba8bb1d4dff1b3ad68eafb75c0b7e72d9626",
    P17: "2483b3e00356dc51922f0130ddadfb2da098eaf306efc9008b6d228eb6436454",
}

TARGET_BOX = (930, 0, 1536, 560)
DONOR_BOX = (0, 47, 1254, 1206)
CENTRAL_GROUND_BOX = (500, 24, 930, 700)
CANDIDATE_LIMIT = 4
PNG = {"format": "PNG", "compress_level": 9, "optimize": False}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


harness = load_module("open_scumble_harness", HARNESS)
harness.OUT = OUT
k3 = harness.k3


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def rank01(values: np.ndarray) -> np.ndarray:
    """Stable empirical rank field in [0, 1], preserving donor phase only."""
    flat = values.astype(np.float64, copy=False).ravel()
    order = np.argsort(flat, kind="stable")
    result = np.empty(flat.size, np.float32)
    if flat.size == 1:
        result[0] = 0.5
    else:
        result[order] = np.linspace(0.0, 1.0, flat.size, dtype=np.float32)
    return result.reshape(values.shape)


def quantile_field(phase: np.ndarray, samples: np.ndarray) -> np.ndarray:
    """Map source-authored phase ranks to an empirical accepted distribution."""
    values = np.sort(samples.astype(np.float32, copy=False).ravel())
    if values.size < 1024:
        raise RuntimeError("accepted central-ground residual sample is too small")
    quantiles = rank01(phase)
    indices = np.clip(
        np.rint(quantiles * (values.size - 1)).astype(np.int64),
        0,
        values.size - 1,
    )
    return values[indices]


def mapped_donor(path: Path) -> np.ndarray:
    source = np.asarray(Image.open(path).convert("RGB"), np.uint8)
    left, top, right, bottom = DONOR_BOX
    return cv2.resize(
        source[top:bottom, left:right],
        (TARGET_BOX[2] - TARGET_BOX[0], TARGET_BOX[3] - TARGET_BOX[1]),
        interpolation=cv2.INTER_AREA,
    )


def filtered_carriers(
    registered_v15: np.ndarray,
    permission: np.ndarray,
    threshold: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Recover v15's broad dark carriers without rendering a blurred field."""
    lightness = cv2.cvtColor(registered_v15, cv2.COLOR_RGB2LAB)[..., 0]
    envelope = cv2.morphologyEx(
        lightness,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61)),
    ).astype(np.int16)
    darkness = np.maximum(envelope - lightness.astype(np.int16), 0)
    raw = (darkness >= threshold).astype(np.uint8)
    joined = cv2.morphologyEx(
        raw,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
    ).astype(bool)
    joined &= permission
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        joined.astype(np.uint8), 8
    )
    carriers = np.zeros(joined.shape, bool)
    components: list[dict[str, int]] = []
    for component in range(1, count):
        area = int(stats[component, cv2.CC_STAT_AREA])
        width = int(stats[component, cv2.CC_STAT_WIDTH])
        height = int(stats[component, cv2.CC_STAT_HEIGHT])
        if 24 <= area <= 10_000:
            carriers |= labels == component
            components.append(
                {
                    "source_component": component,
                    "area_px": area,
                    "width_px": width,
                    "height_px": height,
                }
            )
    if len(components) < 40:
        raise RuntimeError("v15 carrier extraction produced too few components")
    return carriers, darkness.astype(np.float32), {
        "method": (
            "ImageGen v15 Lab-L morphological-close61 envelope minus source; "
            "threshold then close5; component area 24..10000px"
        ),
        "threshold_lab_l": threshold,
        "raw_pixels_inside_permission": int(np.count_nonzero(raw & permission)),
        "retained_pixels": int(carriers.sum()),
        "retained_fraction_of_permission": round(
            float(carriers[permission].mean()), 9
        ),
        "retained_components": len(components),
        "component_area_minimum_px": min(item["area_px"] for item in components),
        "component_area_median_px": round(
            float(np.median([item["area_px"] for item in components])), 6
        ),
        "component_area_maximum_px": max(item["area_px"] for item in components),
    }


def accepted_ground_residuals(
    baseline: np.ndarray,
    masks: dict[str, Any],
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Extract only protected-feature-free central-ground residual samples."""
    lab = cv2.cvtColor(baseline, cv2.COLOR_RGB2LAB).astype(np.int16)
    median = np.stack(
        [cv2.medianBlur(lab[..., channel].astype(np.uint8), 7) for channel in range(3)],
        axis=2,
    ).astype(np.int16)
    residual = lab - median
    left, top, right, bottom = CENTRAL_GROUND_BOX
    window = np.zeros(lab.shape[:2], bool)
    window[top:bottom, left:right] = True
    excluded = masks["edit_union"] | masks["protected_features"]
    excluded = cv2.dilate(
        excluded.astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)),
        iterations=1,
    ).astype(bool)
    eligible = window & ~excluded
    if int(eligible.sum()) < 10_000:
        raise RuntimeError("accepted central-ground residual mask is too small")
    samples: dict[str, np.ndarray] = {}
    diagnostics: dict[str, Any] = {}
    for channel, name in enumerate(("lab_l", "lab_a", "lab_b")):
        values = residual[..., channel][eligible].astype(np.float32)
        low, high = np.quantile(values, (0.03, 0.97))
        clipped = np.clip(values, low, high)
        samples[name] = clipped
        diagnostics[name] = {
            "raw_p03": round(float(low), 6),
            "raw_p50": round(float(np.median(values)), 6),
            "raw_p97": round(float(high), 6),
            "clipped_minimum": round(float(clipped.min()), 6),
            "clipped_maximum": round(float(clipped.max()), 6),
        }
    return samples, {
        "source": "frozen v18 accepted central ground",
        "box_xyxy": list(CENTRAL_GROUND_BOX),
        "exclusion": "dilate5(edit_union | protected_features)",
        "eligible_pixels": int(eligible.sum()),
        "local_residual_operator": "per-channel source minus median7(source)",
        "rendered_spatial_geometry_copied": False,
        "empirical_residual_distribution_only": True,
        "channels": diagnostics,
    }


def donor_phase_fields(v17: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Break v17's long motifs by intersecting independent source transforms."""
    lightness = cv2.cvtColor(v17, cv2.COLOR_RGB2LAB)[..., 0]
    local = cv2.medianBlur(lightness, 11).astype(np.float32)
    dark = local - lightness.astype(np.float32)
    first = rank01(dark)
    second = rank01(np.roll(np.flip(dark, axis=1), shift=(73, 109), axis=(0, 1)))
    rotated = cv2.rotate(dark, cv2.ROTATE_90_CLOCKWISE)
    rotated = cv2.resize(
        rotated,
        (dark.shape[1], dark.shape[0]),
        interpolation=cv2.INTER_AREA,
    )
    third = rank01(np.roll(rotated, shift=(131, 47), axis=(0, 1)))
    # The minimum destroys a curve unless two unrelated donor coordinates
    # independently contain ink.  A 3px median gathers only tiny ragged units.
    fragment = cv2.medianBlur(np.minimum(first, second).astype(np.float32), 3)
    breaker = np.minimum(second, third)
    base_phase = (0.46 * first + 0.31 * second + 0.23 * third).astype(np.float32)
    return fragment, breaker, base_phase


def filter_open_fragments(mask: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """Keep small ragged, hole-free components and reject solid spot bodies."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), 8
    )
    result = np.zeros(mask.shape, bool)
    accepted: list[dict[str, Any]] = []
    rejected = {"area_span": 0, "solid_shape": 0, "hole": 0}
    for component in range(1, count):
        area = int(stats[component, cv2.CC_STAT_AREA])
        width = int(stats[component, cv2.CC_STAT_WIDTH])
        height = int(stats[component, cv2.CC_STAT_HEIGHT])
        span = max(width, height)
        if not (2 <= area <= 96 and span <= 24):
            rejected["area_span"] += 1
            continue
        left = int(stats[component, cv2.CC_STAT_LEFT])
        top = int(stats[component, cv2.CC_STAT_TOP])
        local = labels[top : top + height, left : left + width] == component
        fill = area / max(width * height, 1)
        aspect = max(width, height) / max(min(width, height), 1)
        if fill > 0.82 and aspect < 1.30 and area >= 5:
            rejected["solid_shape"] += 1
            continue
        contours, hierarchy = cv2.findContours(
            local.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
        )
        if hierarchy is not None and any(int(item[3]) >= 0 for item in hierarchy[0]):
            rejected["hole"] += 1
            continue
        result[top : top + height, left : left + width] |= local
        accepted.append(
            {
                "area_px": area,
                "span_px": span,
                "fill_fraction": round(fill, 6),
                "aspect": round(aspect, 6),
            }
        )
    return result, {
        "source_components": count - 1,
        "accepted_components": len(accepted),
        "accepted_pixels": int(result.sum()),
        "component_area_range_px": [2, 96],
        "maximum_component_span_px": 24,
        "maximum_near_square_fill_fraction": 0.82,
        "holes_allowed": False,
        "observed_maximum_component_area_px": max(
            (item["area_px"] for item in accepted), default=0
        ),
        "observed_maximum_component_span_px": max(
            (item["span_px"] for item in accepted), default=0
        ),
        "rejections": rejected,
    }


def choose_open_mask(
    fragment_phase: np.ndarray,
    breaker: np.ndarray,
    allowed: np.ndarray,
    target_pixels: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Choose a filtered donor-derived fragment population near target mass."""
    combined = fragment_phase * (0.70 + 0.30 * breaker)
    values = combined[allowed]
    if values.size < target_pixels:
        raise RuntimeError("open-scumble support is smaller than target population")
    best_mask: np.ndarray | None = None
    best_record: dict[str, Any] | None = None
    best_error = 1 << 60
    # More raw pixels are requested than the target because singleton, solid,
    # and overgrown components are rejected.  This is a fixed bounded search,
    # not an extra visual candidate loop.
    for raw_factor in np.linspace(1.15, 2.80, 18):
        raw_target = min(int(round(target_pixels * raw_factor)), values.size - 1)
        threshold = float(np.partition(values, values.size - raw_target)[values.size - raw_target])
        raw = allowed & (combined >= threshold) & (breaker >= 0.16)
        filtered, record = filter_open_fragments(raw)
        error = abs(int(filtered.sum()) - target_pixels)
        if error < best_error:
            best_error = error
            best_mask = filtered
            best_record = {
                **record,
                "raw_factor": round(float(raw_factor), 6),
                "combined_threshold": round(threshold, 9),
                "target_pixels": target_pixels,
                "absolute_pixel_error": error,
            }
    if best_mask is None or best_record is None:
        raise RuntimeError("open fragment search produced no result")
    return best_mask, best_record


def compose_plate(
    registered_v15: np.ndarray,
    v17: np.ndarray,
    permission: np.ndarray,
    central_samples: dict[str, np.ndarray],
    recipe: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    carriers, darkness, carrier_record = filtered_carriers(
        registered_v15, permission, int(recipe["carrier_threshold"])
    )
    edge_width = int(recipe["edge_width_px"])
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * edge_width + 1, 2 * edge_width + 1)
    )
    support = cv2.dilate(carriers.astype(np.uint8), kernel).astype(bool) & permission
    outside_distance = cv2.distanceTransform((~carriers).astype(np.uint8), cv2.DIST_L2, 5)
    fragment_phase, breaker, base_phase = donor_phase_fields(v17)
    # A donor-derived stochastic erosion removes a wide, nonuniform portion of
    # the nominal support.  No smooth alpha or blurred carrier colour is drawn.
    normalized_distance = np.clip(outside_distance / max(edge_width, 1), 0.0, 1.0)
    edge_keep = breaker >= (
        float(recipe["edge_breaker_floor"])
        + float(recipe["edge_breaker_rise"]) * normalized_distance
    )
    allowed = support & edge_keep
    target_pixels = int(round(float(recipe["target_active_fraction"]) * permission.sum()))
    active, fragment_record = choose_open_mask(
        fragment_phase, breaker, allowed, target_pixels
    )

    # Begin with a continuous, very low-amplitude material made from accepted
    # central-ground residual values ordered by de-correlated v17 phase.  This
    # is not a Gaussian random field and imports no source geography.
    v15_lab = cv2.cvtColor(registered_v15, cv2.COLOR_RGB2LAB).astype(np.float32)
    background = permission & ~carriers
    center = np.median(v15_lab[background], axis=0)
    base_lab = np.empty(v15_lab.shape, np.float32)
    for channel, name in enumerate(("lab_l", "lab_a", "lab_b")):
        phase = np.roll(base_phase, shift=(37 * channel, 53 * channel), axis=(0, 1))
        residual = quantile_field(phase, central_samples[name])
        gain = float(recipe["base_residual_gain_l"] if channel == 0 else recipe["base_residual_gain_ab"])
        cap = float(recipe["base_residual_cap_l"] if channel == 0 else recipe["base_residual_cap_ab"])
        base_lab[..., channel] = center[channel] + gain * np.clip(residual, -cap, cap)

    # Conserve v15's broad carrier darkness as disconnected ink mass.  The
    # maximum local mark delta stays below the unchanged 26-L structural gate.
    propagated = cv2.dilate(darkness, kernel)
    decay = np.clip(1.0 - normalized_distance, 0.0, 1.0)
    raw_mark = (7.0 + propagated * (0.54 + 0.46 * decay))[active]
    target_mass = float(darkness[carriers].sum()) * float(recipe["carrier_mass_gain"])
    scale = target_mass / max(float(raw_mark.sum()), 1e-6)
    mark_delta = np.clip(raw_mark * scale, 7.0, float(recipe["maximum_mark_delta_l"]))
    rendered_mass = float(mark_delta.sum())
    local = base_lab.copy()
    local[..., 0][active] -= mark_delta
    carrier_ab = np.median(v15_lab[carriers], axis=0)[1:]
    background_ab = center[1:]
    chroma_delta = (carrier_ab - background_ab) * float(recipe["carrier_chroma_gain"])
    local[..., 1][active] += chroma_delta[0]
    local[..., 2][active] += chroma_delta[1]
    local = np.clip(np.rint(local), 0, 255).astype(np.uint8)
    plate = cv2.cvtColor(local, cv2.COLOR_LAB2RGB)

    # Numeric evidence that no filled spot body survived the conversion.
    solid_five = cv2.erode(active.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    component_count, _, component_stats, _ = cv2.connectedComponentsWithStats(
        active.astype(np.uint8), 8
    )
    largest = int(component_stats[1:, cv2.CC_STAT_AREA].max()) if component_count > 1 else 0
    carrier_count, carrier_labels, carrier_stats, _ = cv2.connectedComponentsWithStats(
        carriers.astype(np.uint8), 8
    )
    represented = 0
    for component in range(1, carrier_count):
        component_mask = carrier_labels == component
        local_support = cv2.dilate(component_mask.astype(np.uint8), kernel).astype(bool)
        if int(np.count_nonzero(active & local_support)) >= 2:
            represented += 1
    representation_fraction = represented / max(carrier_count - 1, 1)
    mass_ratio = rendered_mass / max(float(darkness[carriers].sum()), 1e-6)
    contract = {
        "passed": bool(
            active.sum() >= 0.85 * target_pixels
            and active.sum() <= 1.15 * target_pixels
            and not solid_five.any()
            and largest <= 96
            and representation_fraction >= 0.90
            and 0.72 <= mass_ratio <= 1.18
        ),
        "active_pixels": int(active.sum()),
        "target_active_pixels": target_pixels,
        "active_fraction_of_permission": round(float(active[permission].mean()), 9),
        "solid_5x5_core_pixels": int(solid_five.sum()),
        "largest_connected_fragment_px": largest,
        "carrier_components": carrier_count - 1,
        "carrier_components_represented": represented,
        "carrier_representation_fraction": round(representation_fraction, 9),
        "v15_carrier_darkness_mass": round(float(darkness[carriers].sum()), 6),
        "rendered_fragment_darkness_mass": round(rendered_mass, 6),
        "rendered_to_v15_carrier_mass_ratio": round(mass_ratio, 9),
        "immediate_failure_proxies": {
            "filled_spot_body_detected": bool(solid_five.any()),
            "overgrown_fragment_detected": largest > 96,
            "unrepresented_carrier_population": representation_fraction < 0.90,
        },
    }
    return plate, active, {
        "carrier_extraction": carrier_record,
        "edge_dissolution": {
            "method": (
                "distance-bounded support intersected by transformed ImageGen v17 "
                "residual rank; discrete fragments only, no rendered continuous alpha"
            ),
            "edge_width_px": edge_width,
            "support_pixels": int(support.sum()),
            "allowed_after_stochastic_edge_dissolution_pixels": int(allowed.sum()),
            "gaussian_blurred_field_used": False,
        },
        "fragment_selection": fragment_record,
        "base_material": {
            "lab_center_from_v15_noncarrier": [round(float(value), 6) for value in center],
            "source": "accepted central-ground empirical residual distribution",
            "phase": "three de-correlated transforms of ImageGen v17 median11 residual ranks",
            "rendered_geography_copied": False,
            "gaussian_blurred_field_used": False,
        },
        "pigment": {
            "maximum_mark_delta_lab_l": float(recipe["maximum_mark_delta_l"]),
            "unclipped_mass_scale": round(float(scale), 9),
            "carrier_chroma_delta_lab_ab": [round(float(value), 6) for value in chroma_delta],
        },
        "open_scumble_contract": contract,
    }


def rewrite_candidate_report(record: dict[str, Any]) -> None:
    report_path = ROOT / record["report"]["path"]
    payload = dict(record)
    payload.pop("report", None)
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    record["report"] = {"path": relative(report_path), "sha256": sha256(report_path)}


def main() -> None:
    for path, digest in EXPECTED.items():
        if not path.is_file() or sha256(path) != digest:
            raise RuntimeError(f"frozen input missing or hash-mismatched: {path}")
    persistent = (k3.RAW, k3.FINAL, k3.RECEIPT, k3.AUDIT)
    if any(path.exists() for path in persistent):
        raise RuntimeError("persistent K3 output unexpectedly exists")
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty TEMP exploration: {OUT}")

    baseline = np.asarray(Image.open(V18).convert("RGB"), np.uint8)
    masks = k3.derive_masks()
    left, top, right, bottom = TARGET_BOX
    permission_crop = masks["highland_edit"][top:bottom, left:right]
    baseline_crop = baseline[top:bottom, left:right]
    donor15 = mapped_donor(V15)
    donor17 = mapped_donor(V17)
    donor_center = np.median(donor15.reshape(-1, 3), axis=0)
    target_center = np.median(baseline[masks["highland_edit"]], axis=0)
    registered15 = np.clip(
        np.rint(donor15.astype(np.float32) + (target_center - donor_center)),
        0,
        255,
    ).astype(np.uint8)
    registered17 = np.clip(
        np.rint(
            donor17.astype(np.float32)
            + (target_center - np.median(donor17.reshape(-1, 3), axis=0))
        ),
        0,
        255,
    ).astype(np.uint8)
    central_samples, central_record = accepted_ground_residuals(baseline, masks)

    recipes = (
        {
            "name": "open-scumble-a-t16-e18-f150-m090",
            "carrier_threshold": 16,
            "edge_width_px": 18,
            "edge_breaker_floor": 0.08,
            "edge_breaker_rise": 0.34,
            "target_active_fraction": 0.150,
            "carrier_mass_gain": 0.90,
            "maximum_mark_delta_l": 24.0,
            "carrier_chroma_gain": 1.0,
            "base_residual_gain_l": 0.70,
            "base_residual_gain_ab": 0.40,
            "base_residual_cap_l": 4.0,
            "base_residual_cap_ab": 2.0,
        },
        {
            "name": "open-scumble-b-t16-e24-f165-m095",
            "carrier_threshold": 16,
            "edge_width_px": 24,
            "edge_breaker_floor": 0.06,
            "edge_breaker_rise": 0.30,
            "target_active_fraction": 0.165,
            "carrier_mass_gain": 0.95,
            "maximum_mark_delta_l": 24.0,
            "carrier_chroma_gain": 1.0,
            "base_residual_gain_l": 0.72,
            "base_residual_gain_ab": 0.42,
            "base_residual_cap_l": 4.0,
            "base_residual_cap_ab": 2.0,
        },
        {
            "name": "open-scumble-c-t18-e28-f160-m100",
            "carrier_threshold": 18,
            "edge_width_px": 28,
            "edge_breaker_floor": 0.05,
            "edge_breaker_rise": 0.28,
            "target_active_fraction": 0.160,
            "carrier_mass_gain": 1.00,
            "maximum_mark_delta_l": 24.0,
            "carrier_chroma_gain": 1.04,
            "base_residual_gain_l": 0.75,
            "base_residual_gain_ab": 0.44,
            "base_residual_cap_l": 4.0,
            "base_residual_cap_ab": 2.0,
        },
        {
            "name": "open-scumble-d-t18-e34-f175-m105",
            "carrier_threshold": 18,
            "edge_width_px": 34,
            "edge_breaker_floor": 0.04,
            "edge_breaker_rise": 0.25,
            "target_active_fraction": 0.175,
            "carrier_mass_gain": 1.05,
            "maximum_mark_delta_l": 24.0,
            "carrier_chroma_gain": 1.06,
            "base_residual_gain_l": 0.78,
            "base_residual_gain_ab": 0.46,
            "base_residual_cap_l": 4.0,
            "base_residual_cap_ab": 2.0,
        },
    )
    if len(recipes) > CANDIDATE_LIMIT:
        raise RuntimeError("candidate limit exceeded")

    OUT.mkdir(parents=True, exist_ok=True)
    baseline_weave = harness.weave(baseline, masks["highland_edit"])
    baseline_activity = float(baseline_weave["activity_fraction"])
    alpha = k3.boundary_locked_alpha(
        masks["highland_edit"], full_by_px=7.0, locked_boundary_px=2.0
    )
    original_save_contacts = harness.save_contacts
    records: dict[str, Any] = {}
    try:
        # Contacts are emitted only after the unchanged full numeric gates and
        # this control's open-scumble contract have both passed.
        harness.save_contacts = lambda candidate, directory: {}
        for recipe in recipes:
            local_plate, active, operation = compose_plate(
                registered15,
                registered17,
                permission_crop,
                central_samples,
                recipe,
            )
            donor_canvas = baseline.copy()
            donor_canvas[top:bottom, left:right] = local_plate
            candidate = k3.composite_with_alpha(baseline, donor_canvas, alpha)
            record = harness.evaluate(
                str(recipe["name"]), candidate, baseline, masks, baseline_activity
            )
            open_passed = operation["open_scumble_contract"]["passed"]
            record["automated_gates"]["open_scumble_contract"] = open_passed
            record["failed_gates"] = [
                name
                for name, passed in record["automated_gates"].items()
                if not passed
            ]
            passed = not record["failed_gates"]
            record["status"] = (
                "passed-automated-gates-pending-root-vision"
                if passed
                else "failed-automated-gates"
            )
            record["vision_handoff"]["required"] = passed
            record["contacts"] = (
                original_save_contacts(
                    candidate, OUT / str(recipe["name"]) / "contacts"
                )
                if passed
                else {}
            )
            record["recipe"] = recipe
            record["operation"] = operation
            record["active_fragment_mask"] = {
                "pixels": int(active.sum()),
                "review_only_not_saved_as_persistent_control": True,
            }
            rewrite_candidate_report(record)
            records[str(recipe["name"])] = record
    finally:
        harness.save_contacts = original_save_contacts

    aggregate = {
        "schema_version": "1.0.0",
        "status": "TEMP-only v15 open-scumble exploration; no acceptance authority",
        "temporary_review_only": True,
        "decision_authority": False,
        "persistent_outputs_emitted": False,
        "thresholds_changed": False,
        "candidate_limit": CANDIDATE_LIMIT,
        "candidate_count": len(records),
        "inputs": {
            "v18": {"path": relative(V18), "sha256": EXPECTED[V18]},
            "imagegen_v15": {"path": relative(V15), "sha256": EXPECTED[V15]},
            "imagegen_v15_exact_prompt": {
                "path": relative(P15),
                "sha256": EXPECTED[P15],
            },
            "imagegen_v17": {"path": relative(V17), "sha256": EXPECTED[V17]},
            "imagegen_v17_exact_prompt": {
                "path": relative(P17),
                "sha256": EXPECTED[P17],
            },
            "full_gate_harness": {
                "path": relative(HARNESS),
                "sha256": sha256(HARNESS),
            },
        },
        "operation": {
            "semantic_change": "highland permitted interior material only",
            "target_crop_xyxy": list(TARGET_BOX),
            "donor_crop_xyxy": list(DONOR_BOX),
            "v15_authority": "macro carrier locations, tonal mass, and palette",
            "v17_authority": "de-correlated stochastic micro-ink occupancy phase",
            "accepted_central_ground_authority": central_record,
            "solid_carrier_pixels_directly_rendered": False,
            "continuous_carrier_alpha_rendered": False,
            "gaussian_blurred_synthesis_field_used": False,
            "spatial_pixel_reassignment_used": True,
            "sorting_or_distribution_remap_used": True,
            "boundary_alpha": {"locked_boundary_px": 2.0, "full_by_px": 7.0},
        },
        "v18_weave": baseline_weave,
        "records": records,
    }
    report_path = OUT / "open-scumble-search.json"
    report_path.write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "report": {"path": relative(report_path), "sha256": sha256(report_path)},
                "variants": {
                    name: {
                        "status": record["status"],
                        "failed_gates": record["failed_gates"],
                        "activity": record["weave_reduction"]["candidate"][
                            "activity_fraction"
                        ],
                        "orientation": record["weave_reduction"]["orientation"][
                            "global_gradient_orientation_coherence"
                        ],
                        "strict_highland": record["strict_content"]["highland"],
                        "palette": record["global_gates"]["palette"],
                        "downsample": record["global_gates"]["downsample"],
                        "open_scumble_contract": record["operation"][
                            "open_scumble_contract"
                        ],
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
