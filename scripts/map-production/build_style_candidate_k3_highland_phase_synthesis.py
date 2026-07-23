#!/usr/bin/env python3
"""Build up to six TEMP-only, donor-bound highland phase-synthesis probes.

This is an exploration tool, not an acceptance or publication path.  It keeps
the frozen v18 image byte-exact outside the existing highland permission mask
and derives all replacement phase from the locked ImageGen v14/v15 donors.
No persistent candidate, specification, manifest, or control file is written.
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
OUT = ROOT / "tmp/map-production/k3-semantic-cleanup-v19-phase-synthesis"
V18 = ROOT / "tmp/map-production/k3-semantic-cleanup-proof-v18/style-candidate-k-v3-semantic-cleanup-proof-v18.png"
V14 = ROOT / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/highland-planar-v14.png"
V15 = ROOT / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/highland-planar-v15.png"
V17 = ROOT / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/highland-inverse-aquatint-v17.png"
P14 = ROOT / "world/map-production/prompts/style-candidate-k-v3-highland-planar-donor-v14.generation.txt"
P15 = ROOT / "world/map-production/prompts/style-candidate-k-v3-highland-planar-donor-v15.generation.txt"
P17 = ROOT / "world/map-production/prompts/style-candidate-k-v3-highland-inverse-aquatint-donor-v17.generation.txt"

EXPECTED = {
    V18: "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882",
    V14: "2c8d0691bc16ad5d22410a29eea4619cfa2c2a1fa731a9b17ef123e66ffd65b0",
    V15: "5942a770e866fd1641156c141715cb55a473a65c7602a8075f0747e7b96e7602",
    V17: "4f64fcee2d5b1f0932f1d65fe460ba8bb1d4dff1b3ad68eafb75c0b7e72d9626",
    P14: "06e782e46d9f1901f351721d152bc7513ab72bc4582fb7df4d23805902c621d0",
    P15: "d52572ef0af1a6801e305bd507ea2c19d224fe23fb1024931ba1e7c85b2c575e",
    P17: "2483b3e00356dc51922f0130ddadfb2da098eaf306efc9008b6d228eb6436454",
}

PNG = {"format": "PNG", "compress_level": 9, "optimize": False}
TARGET_BOX = (930, 0, 1536, 560)
DONOR_BOX = (0, 47, 1254, 1206)
PROFILE_BOX = (130, 50, 560, 420)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


k3 = load_module(
    "phase_synthesis_k3",
    SCRIPTS / "build_style_candidate_k3_semantic_cleanup.py",
)
h4 = load_module(
    "phase_synthesis_h4", SCRIPTS / "audit_style_candidate_h4.py"
)
h17 = load_module(
    "phase_synthesis_h17", SCRIPTS / "audit_style_candidate_h17.py"
)
k2 = load_module(
    "phase_synthesis_k2", SCRIPTS / "audit_style_candidate_k2_hybrid.py"
)
audit = load_module(
    "phase_synthesis_audit",
    SCRIPTS / "audit_style_candidate_k3_semantic_cleanup.py",
)


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


def l_channel(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32)


def donor_l(path: Path) -> np.ndarray:
    source = np.asarray(Image.open(path).convert("RGB"), np.uint8)
    left, top, right, bottom = DONOR_BOX
    cropped = source[top:bottom, left:right]
    mapped = cv2.resize(cropped, (606, 560), interpolation=cv2.INTER_AREA)
    return l_channel(mapped)


def clipped_highpass(source: np.ndarray, sigma: float) -> np.ndarray:
    """Suppress donor flakes/blotches while retaining their generated phase."""
    residual = source - gaussian(source, sigma)
    low, high = np.quantile(residual, (0.12, 0.88))
    return np.clip(residual, low, high) - float(np.median(residual))


def radial_power_profile(
    residual: np.ndarray,
    bins: int = 384,
) -> tuple[np.ndarray, np.ndarray]:
    """Return normalized-frequency radial PSD from a frozen interior patch."""
    height, width = residual.shape
    window = np.outer(np.hanning(height), np.hanning(width)).astype(np.float32)
    window_energy = float(np.mean(window * window))
    transformed = np.fft.fft2((residual - float(np.mean(residual))) * window)
    fy = np.fft.fftfreq(height)
    fx = np.fft.fftfreq(width)
    yy, xx = np.meshgrid(fy, fx, indexing="ij")
    radius = np.hypot(xx, yy)
    edges = np.linspace(0.0, np.sqrt(0.5), bins + 1)
    indices = np.minimum(np.digitize(radius.ravel(), edges) - 1, bins - 1)
    power = (np.abs(transformed).ravel() ** 2) / max(
        residual.size * window_energy, 1e-12
    )
    sums = np.bincount(indices, weights=power, minlength=bins)
    counts = np.bincount(indices, minlength=bins)
    profile = sums / np.maximum(counts, 1)
    centers = (edges[:-1] + edges[1:]) * 0.5
    return centers, profile


def quantile_map(source: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Give donor-phase synthesis the frozen v18 residual distribution."""
    flat = source.ravel()
    order = np.argsort(flat, kind="stable")
    quantiles = (np.arange(flat.size, dtype=np.float64) + 0.5) / flat.size
    reference_sorted = np.sort(reference.ravel())
    reference_quantiles = (
        np.arange(reference_sorted.size, dtype=np.float64) + 0.5
    ) / reference_sorted.size
    values = np.interp(quantiles, reference_quantiles, reference_sorted)
    result = np.empty_like(flat, dtype=np.float32)
    result[order] = values.astype(np.float32)
    return result.reshape(source.shape)


def radial_phase_synthesis(
    reference_residual: np.ndarray,
    phase_source: np.ndarray,
) -> np.ndarray:
    """Use v18 radial power and donor phase, then restore v18 residual CDF."""
    x0, y0, x1, y1 = PROFILE_BOX
    patch = reference_residual[y0:y1, x0:x1]
    centers, profile = radial_power_profile(patch)
    height, width = phase_source.shape
    transformed = np.fft.fft2(phase_source - float(np.mean(phase_source)))
    unit_phase = transformed / np.maximum(np.abs(transformed), 1e-12)
    fy = np.fft.fftfreq(height)
    fx = np.fft.fftfreq(width)
    yy, xx = np.meshgrid(fy, fx, indexing="ij")
    radius = np.hypot(xx, yy)
    density = np.interp(radius.ravel(), centers, profile).reshape(radius.shape)
    amplitude = np.sqrt(np.maximum(density, 0.0) * phase_source.size)
    amplitude[0, 0] = 0.0
    synthesized = np.fft.ifft2(amplitude * unit_phase).real.astype(np.float32)
    return quantile_map(synthesized, patch)


def mixed_phase(first: np.ndarray, second: np.ndarray, weight: float) -> np.ndarray:
    """Blend two real donor residuals before extracting a Hermitian phase."""
    shifted = np.roll(np.flip(second, axis=1), shift=(73, 113), axis=(0, 1))
    first_scale = max(float(np.std(first)), 1e-6)
    second_scale = max(float(np.std(shifted)), 1e-6)
    return first / first_scale + weight * shifted / second_scale


def make_luminance_plate(
    baseline_crop: np.ndarray,
    base_sigma: float,
    phase_source: np.ndarray,
    gain: float,
) -> np.ndarray:
    lab = cv2.cvtColor(baseline_crop, cv2.COLOR_RGB2LAB)
    target_l = lab[..., 0].astype(np.float32)
    base = gaussian(target_l, base_sigma)
    reference = target_l - base
    synthesized = radial_phase_synthesis(reference, phase_source)
    local = lab.copy()
    local[..., 0] = np.clip(np.rint(base + gain * synthesized), 0, 255).astype(
        np.uint8
    )
    return cv2.cvtColor(local, cv2.COLOR_LAB2RGB)


def make_multiscale_plate(
    baseline_crop: np.ndarray,
    fine_phase: np.ndarray,
    middle_phase: np.ndarray,
    fine_gain: float,
    middle_gain: float,
) -> np.ndarray:
    lab = cv2.cvtColor(baseline_crop, cv2.COLOR_RGB2LAB)
    target_l = lab[..., 0].astype(np.float32)
    low = gaussian(target_l, 5.0)
    middle_reference = gaussian(target_l, 1.55) - low
    fine_reference = target_l - gaussian(target_l, 1.55)
    fine = radial_phase_synthesis(fine_reference, fine_phase)
    middle = radial_phase_synthesis(middle_reference, middle_phase)
    local = lab.copy()
    local[..., 0] = np.clip(
        np.rint(low + fine_gain * fine + middle_gain * middle), 0, 255
    ).astype(np.uint8)
    return cv2.cvtColor(local, cv2.COLOR_LAB2RGB)


def make_donor_residual_plate(
    baseline_crop: np.ndarray,
    base_sigma: float,
    donor_bands: list[tuple[np.ndarray, float, float]],
    phase_source: np.ndarray,
    phase_gain: float,
) -> np.ndarray:
    """Keep v18's broad plate and add bounded ImageGen donor residual bands."""
    lab = cv2.cvtColor(baseline_crop, cv2.COLOR_RGB2LAB)
    target_l = lab[..., 0].astype(np.float32)
    base = gaussian(target_l, base_sigma)
    composed = base.copy()
    if phase_gain != 0.0:
        fine_reference = target_l - gaussian(target_l, 1.55)
        fine = radial_phase_synthesis(fine_reference, phase_source)
        composed += phase_gain * fine
    for donor, sigma, gain in donor_bands:
        residual = donor - gaussian(donor, sigma)
        low, high = np.quantile(residual, (0.01, 0.99))
        residual = np.clip(residual, low, high)
        residual -= float(np.median(residual))
        composed += gain * residual
    local = lab.copy()
    local[..., 0] = np.clip(np.rint(composed), 0, 255).astype(np.uint8)
    return cv2.cvtColor(local, cv2.COLOR_LAB2RGB)


def donor_fragments(
    donor: np.ndarray,
    sigma: float,
    threshold: float,
    minimum_area: int,
    maximum_area: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Retain bounded donor-authored fragments while rejecting stain masses."""
    residual = donor - gaussian(donor, sigma)
    seeds = residual <= threshold
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        seeds.astype(np.uint8), 8
    )
    selected = np.zeros(seeds.shape, bool)
    components: list[dict[str, int]] = []
    for component in range(1, count):
        area = int(stats[component, cv2.CC_STAT_AREA])
        width = int(stats[component, cv2.CC_STAT_WIDTH])
        height = int(stats[component, cv2.CC_STAT_HEIGHT])
        if (
            minimum_area <= area <= maximum_area
            and max(width, height) <= 32
        ):
            selected |= labels == component
            components.append({"area": area, "width": width, "height": height})
    matte = np.clip(residual, -24.0, 0.0)
    matte[~selected] = 0.0
    return matte, {
        "sigma": sigma,
        "threshold": threshold,
        "minimum_area": minimum_area,
        "maximum_area": maximum_area,
        "maximum_span": 32,
        "component_count": len(components),
        "selected_pixels": int(selected.sum()),
        "area_minimum_observed": min(
            (item["area"] for item in components), default=0
        ),
        "area_maximum_observed": max(
            (item["area"] for item in components), default=0
        ),
    }


def make_fragment_plate(
    baseline_crop: np.ndarray,
    base_sigma: float,
    fragments: list[tuple[np.ndarray, float]],
    phase_source: np.ndarray,
    phase_gain: float,
) -> np.ndarray:
    """Compose sparse ImageGen mineral fragments over v18 broad substrate."""
    lab = cv2.cvtColor(baseline_crop, cv2.COLOR_RGB2LAB)
    target_l = lab[..., 0].astype(np.float32)
    base = gaussian(target_l, base_sigma)
    fine_reference = target_l - gaussian(target_l, 1.55)
    fine = radial_phase_synthesis(fine_reference, phase_source)
    composed = base + phase_gain * fine
    for fragment_field, gain in fragments:
        composed += gain * fragment_field
    local = lab.copy()
    local[..., 0] = np.clip(np.rint(composed), 0, 255).astype(np.uint8)
    return cv2.cvtColor(local, cv2.COLOR_LAB2RGB)


def make_shrink_fragment_plate(
    baseline_crop: np.ndarray,
    base_sigma: float,
    tail_threshold: float,
    tail_gain: float,
    tail_mode: str,
    fragments: list[tuple[np.ndarray, float]],
) -> np.ndarray:
    """Restore only strong dry v18 pigment tails over a quiet mid-band."""
    lab = cv2.cvtColor(baseline_crop, cv2.COLOR_RGB2LAB)
    target_l = lab[..., 0].astype(np.float32)
    base = gaussian(target_l, base_sigma)
    residual = target_l - base
    if tail_mode == "both":
        tail = (
            np.sign(residual)
            * np.maximum(np.abs(residual) - tail_threshold, 0.0)
            * tail_gain
        )
    elif tail_mode == "dark":
        tail = np.minimum(residual + tail_threshold, 0.0) * tail_gain
    else:
        raise ValueError(f"unsupported tail mode: {tail_mode}")
    composed = base + tail
    for fragment_field, gain in fragments:
        composed += gain * fragment_field
    local = lab.copy()
    local[..., 0] = np.clip(np.rint(composed), 0, 255).astype(np.uint8)
    return cv2.cvtColor(local, cv2.COLOR_LAB2RGB)


def donor_amplitude_phase_synthesis(
    amplitude_source: np.ndarray,
    phase_source: np.ndarray,
    highpass_sigma: float,
    reference_residual: np.ndarray,
) -> np.ndarray:
    """Destroy v17 motifs: keep its radial power, use only v14/v15 phase."""
    amplitude_residual = amplitude_source - gaussian(
        amplitude_source, highpass_sigma
    )
    x0, y0, x1, y1 = PROFILE_BOX
    centers, profile = radial_power_profile(amplitude_residual[y0:y1, x0:x1])
    transformed = np.fft.fft2(phase_source - float(np.mean(phase_source)))
    unit_phase = transformed / np.maximum(np.abs(transformed), 1e-12)
    height, width = phase_source.shape
    fy = np.fft.fftfreq(height)
    fx = np.fft.fftfreq(width)
    yy, xx = np.meshgrid(fy, fx, indexing="ij")
    radius = np.hypot(xx, yy)
    density = np.interp(radius.ravel(), centers, profile).reshape(radius.shape)
    amplitude = np.sqrt(np.maximum(density, 0.0) * phase_source.size)
    amplitude[0, 0] = 0.0
    synthesized = np.fft.ifft2(amplitude * unit_phase).real.astype(np.float32)
    # v18's non-Gaussian residual CDF prevents a featureless Gaussian field.
    x0, y0, x1, y1 = PROFILE_BOX
    return quantile_map(synthesized, reference_residual[y0:y1, x0:x1])


def make_v17_amplitude_plate(
    baseline_crop: np.ndarray,
    v17: np.ndarray,
    phase_source: np.ndarray,
    base_sigma: float,
    highpass_sigma: float,
    gain: float,
) -> np.ndarray:
    lab = cv2.cvtColor(baseline_crop, cv2.COLOR_RGB2LAB)
    target_l = lab[..., 0].astype(np.float32)
    base = gaussian(target_l, base_sigma)
    reference = target_l - gaussian(target_l, 1.55)
    synthesized = donor_amplitude_phase_synthesis(
        v17, phase_source, highpass_sigma, reference
    )
    local = lab.copy()
    local[..., 0] = np.clip(np.rint(base + gain * synthesized), 0, 255).astype(
        np.uint8
    )
    return cv2.cvtColor(local, cv2.COLOR_LAB2RGB)


def weave(image: np.ndarray, permission: np.ndarray) -> dict[str, Any]:
    core = k3.erode(permission, 28)
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32)
    highpass = np.abs(gray - gaussian(gray, 1.6))
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gx, gy)
    active = ((highpass >= 6.0) | (gradient >= 26.0)) & core
    return {
        "core_pixels": int(core.sum()),
        "activity_fraction": round(float(active[core].mean()), 9),
        "highpass_p95": round(float(np.percentile(highpass[core], 95)), 6),
        "gradient_p95": round(float(np.percentile(gradient[core], 95)), 6),
    }


def save_contacts(candidate: np.ndarray, directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    source = Image.fromarray(candidate, "RGB")
    definitions = (
        ("full25-lanczos.png", None, (384, 256)),
        ("full50-lanczos.png", None, (768, 512)),
        ("highland200-lanczos.png", TARGET_BOX, (1212, 1120)),
        ("highland400-lanczos.png", TARGET_BOX, (2424, 2240)),
    )
    records: dict[str, Any] = {}
    for name, crop_box, size in definitions:
        working = source.crop(crop_box) if crop_box is not None else source.copy()
        rendered = working.resize(size, Image.Resampling.LANCZOS)
        path = directory / name
        rendered.save(path, **PNG)
        rendered.close()
        working.close()
        records[name] = {
            "path": relative(path),
            "sha256": sha256(path),
            "size": list(size),
            "resampling": "Pillow LANCZOS; review derivative only",
        }
    source.close()
    return records


def image_contract(path: Path) -> dict[str, Any]:
    with Image.open(path) as opened:
        passed = bool(
            opened.mode == "RGB"
            and opened.size == (k3.WIDTH, k3.HEIGHT)
            and opened.getbands() == ("R", "G", "B")
            and opened.info.get("transparency") is None
            and not opened.info.get("icc_profile")
        )
        return {
            "passed": passed,
            "mode": opened.mode,
            "size": list(opened.size),
            "bands": list(opened.getbands()),
            "info_keys": sorted(opened.info),
        }


def evaluate(
    name: str,
    candidate: np.ndarray,
    baseline: np.ndarray,
    masks: dict[str, Any],
    baseline_activity: float,
) -> dict[str, Any]:
    directory = OUT / name
    directory.mkdir(parents=True, exist_ok=True)
    candidate_path = directory / f"{name}.png"
    Image.fromarray(candidate, "RGB").save(candidate_path, **PNG)
    changed = np.any(candidate != baseline, axis=2)
    strict = audit.strict_content_metrics(candidate, masks)
    semantic = audit.semantic_cleanup_metrics(candidate, masks)
    blotch = audit.low_frequency_blotch_metrics(candidate, masks)
    cadence = audit.parcel_boundary_cadence_metrics(candidate, masks)
    with (
        Image.open(candidate_path).convert("RGB") as candidate_pil,
        Image.open(k2.B1_REFERENCE).convert("RGB") as b1,
        Image.open(k2.H4_REFERENCE).convert("RGB") as h4_reference,
        Image.open(k2.GUIDE).convert("RGB") as guide,
    ):
        global_gates = {
            "boundary": h4.boundary_metrics(candidate_pil),
            "palette": h4.palette_continuity_metrics(candidate_pil, b1),
            "exact_repetition": h4.exact_repetition_metrics(candidate_pil),
            "downsample": h4.downsample_readability_metrics(candidate_pil),
            "semantic_repetition": h17.semantic_repetition_proxies(
                candidate_pil, h4_reference
            ),
            "geometry": k2.geometry_metrics(guide, candidate_pil),
        }
    candidate_weave = weave(candidate, masks["highland_edit"])
    activity = float(candidate_weave["activity_fraction"])
    orientation = semantic["highland"]["orientation_substrate_proxy"]
    identity = {
        "differing_pixels_vs_v18": int(changed.sum()),
        "differing_pixels_inside_highland_edit": int(
            np.count_nonzero(changed & masks["highland_edit"])
        ),
        "differing_pixels_outside_highland_edit": int(
            np.count_nonzero(changed & ~masks["highland_edit"])
        ),
        "differing_protected_feature_pixels": int(
            np.count_nonzero(changed & masks["protected_features"])
        ),
    }
    automated_gates = {
        "native_rgb_no_alpha_profile": image_contract(candidate_path)["passed"],
        "v18_highland_only_spatial_identity": bool(
            identity["differing_pixels_inside_highland_edit"] > 0
            and identity["differing_pixels_outside_highland_edit"] == 0
            and identity["differing_protected_feature_pixels"] == 0
        ),
        "strict_local_raster_and_structure": strict[
            "passed_automated_raster_and_structure"
        ],
        "low_frequency_blotch_v1": blotch["passed"],
        "measurable_weave_reduction_and_orientation": bool(
            activity <= 0.15
            and activity <= 0.25 * baseline_activity
            and orientation["passed"]
        ),
        "unchanged_boundary": global_gates["boundary"]["passed"],
        "unchanged_palette": global_gates["palette"]["passed"],
        "unchanged_exact_repetition": global_gates["exact_repetition"]["passed"],
        "unchanged_downsample": global_gates["downsample"]["passed"],
        "unchanged_semantic_repetition": global_gates["semantic_repetition"][
            "passed"
        ],
        "unchanged_strict_geometry": global_gates["geometry"]["passed"],
    }
    passed = all(automated_gates.values())
    record: dict[str, Any] = {
        "status": (
            "passed-automated-gates-pending-root-vision"
            if passed
            else "failed-automated-gates"
        ),
        "temporary_review_only": True,
        "decision_authority": False,
        "golden_accepted": False,
        "candidate": {"path": relative(candidate_path), "sha256": sha256(candidate_path)},
        "image_contract": image_contract(candidate_path),
        "identity": identity,
        "weave_reduction": {
            "candidate": candidate_weave,
            "candidate_to_v18_activity_ratio": round(
                activity / max(baseline_activity, 1e-12), 9
            ),
            "thresholds": {
                "maximum_candidate_activity_fraction": 0.15,
                "maximum_candidate_to_v18_activity_ratio": 0.25,
                "maximum_orientation_coherence": audit.MAXIMUM_ORIENTATION_COHERENCE,
            },
            "orientation": orientation,
        },
        "strict_content": strict,
        "semantic_diagnostic": semantic,
        "low_frequency_blotch": blotch,
        "parcel_boundary_cadence_diagnostic": cadence,
        "global_gates": global_gates,
        "automated_gates": automated_gates,
        "failed_gates": [
            gate for gate, gate_passed in automated_gates.items() if not gate_passed
        ],
        "contacts": {},
        "vision_handoff": {
            "required": passed,
            "semantic_claim": None,
            "candidate_only_not_frozen": True,
        },
    }
    if passed:
        record["contacts"] = save_contacts(candidate, directory / "contacts")
    report_path = directory / f"{name}.full-audit.json"
    report_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    record["report"] = {"path": relative(report_path), "sha256": sha256(report_path)}
    return record


def main() -> None:
    for path, digest in EXPECTED.items():
        if not path.is_file() or sha256(path) != digest:
            raise RuntimeError(f"frozen input missing or hash-mismatched: {path}")
    persistent = (k3.RAW, k3.FINAL, k3.RECEIPT, k3.AUDIT)
    if any(path.exists() for path in persistent):
        raise RuntimeError("persistent K3 output unexpectedly exists")

    baseline = np.asarray(Image.open(V18).convert("RGB"), np.uint8)
    masks = k3.derive_masks()
    left, top, right, bottom = TARGET_BOX
    baseline_crop = baseline[top:bottom, left:right]
    permission_crop = masks["highland_edit"][top:bottom, left:right]
    x0, y0, x1, y1 = PROFILE_BOX
    if not np.all(permission_crop[y0:y1, x0:x1]):
        raise RuntimeError("frozen radial-profile patch left highland permission")

    donor14 = donor_l(V14)
    donor15 = donor_l(V15)
    donor17 = donor_l(V17)
    phase14_fine = clipped_highpass(donor14, 1.25)
    phase15_fine = clipped_highpass(donor15, 1.25)
    phase_dual_fine = mixed_phase(phase14_fine, phase15_fine, 0.62)

    v14_fragments_a, v14_fragments_a_record = donor_fragments(
        donor14, 20.0, -5.0, 25, 240
    )
    v14_fragments_b, v14_fragments_b_record = donor_fragments(
        donor14, 20.0, -4.0, 15, 180
    )
    v15_fragments_a, v15_fragments_a_record = donor_fragments(
        donor15, 20.0, -5.0, 25, 240
    )

    recipes: list[tuple[str, np.ndarray, dict[str, Any]]] = []
    recipe_specs = (
        ("shrink-s145-t15-g050-f100-both", 1.45, 15.0, 0.50, "both", v14_fragments_b, 1.00, 1.00),
        ("shrink-s140-t10-g060-f100-dark", 1.40, 10.0, 0.60, "dark", v14_fragments_b, 1.00, 1.00),
        ("shrink-s145-t08-g050-f100-dark", 1.45, 8.0, 0.50, "dark", v14_fragments_b, 1.00, 1.00),
        ("shrink-s145-t10-g060-f100-dark", 1.45, 10.0, 0.60, "dark", v14_fragments_b, 1.00, 1.00),
        ("shrink-s150-t10-g070-f100-dark", 1.50, 10.0, 0.70, "dark", v14_fragments_b, 1.00, 1.00),
        ("shrink-s145-t10-g060-a085-dark", 1.45, 10.0, 0.60, "dark", v14_fragments_a, 0.85, 0.90),
    )
    for (
        name,
        sigma,
        tail_threshold,
        tail_gain,
        tail_mode,
        field14,
        gain14,
        gain15,
    ) in recipe_specs:
        record14 = (
            v14_fragments_a_record
            if field14 is v14_fragments_a
            else v14_fragments_b_record
        )
        recipes.append((
            name,
            make_shrink_fragment_plate(
                baseline_crop,
                sigma,
                tail_threshold,
                tail_gain,
                tail_mode,
                [(field14, gain14), (v15_fragments_a, gain15)],
            ),
            {
                "kind": "soft-threshold-v18-dry-tail-plus-bounded-fragments",
                "base_sigma": sigma,
                "tail_threshold": tail_threshold,
                "tail_gain": tail_gain,
                "tail_mode": tail_mode,
                "fragments": [
                    {"donor": "v14", "gain": gain14, **record14},
                    {"donor": "v15", "gain": gain15, **v15_fragments_a_record},
                ],
            },
        ))

    OUT.mkdir(parents=True, exist_ok=True)
    baseline_weave = weave(baseline, masks["highland_edit"])
    baseline_activity = float(baseline_weave["activity_fraction"])
    records: dict[str, Any] = {}
    alpha = k3.boundary_locked_alpha(
        masks["highland_edit"], full_by_px=7.0, locked_boundary_px=2.0
    )
    for name, local_plate, recipe in recipes:
        donor_canvas = baseline.copy()
        donor_canvas[top:bottom, left:right] = local_plate
        candidate = k3.composite_with_alpha(baseline, donor_canvas, alpha)
        record = evaluate(
            name, candidate, baseline, masks, baseline_activity
        )
        record["recipe"] = recipe
        records[name] = record

    report = {
        "schema_version": "1.0.0",
        "status": "TEMP-only phase synthesis exploration; no acceptance authority",
        "temporary_review_only": True,
        "decision_authority": False,
        "persistent_outputs_emitted": False,
        "thresholds_changed": False,
        "inputs": {
            "v18": {"path": relative(V18), "sha256": EXPECTED[V18]},
            "v14": {"path": relative(V14), "sha256": EXPECTED[V14]},
            "v14_prompt": {"path": relative(P14), "sha256": EXPECTED[P14]},
            "v15": {"path": relative(V15), "sha256": EXPECTED[V15]},
            "v15_prompt": {"path": relative(P15), "sha256": EXPECTED[P15]},
            "v17": {"path": relative(V17), "sha256": EXPECTED[V17]},
            "v17_prompt": {"path": relative(P17), "sha256": EXPECTED[P17]},
        },
        "operation": {
            "semantic_change": "highland permitted interior material only",
            "target_crop_xyxy": list(TARGET_BOX),
            "donor_crop_xyxy": list(DONOR_BOX),
            "v18_radial_power_profile_patch_xyxy_in_target_crop": list(PROFILE_BOX),
            "radial_power": "v18 or locked ImageGen v17 normalized-frequency radial PSD, per recipe",
            "phase": "locked ImageGen v14/v15 donor high-pass phase only; v17 phase is never used",
            "distribution": "bounded direct donor fragments or deterministic quantile map to frozen v18 interior residual, per recipe",
            "synthetic_random_noise_used": False,
            "gaussian_random_field_used": False,
            "spatial_pixel_reassignment_used": True,
            "sorting_or_distribution_remap_used": True,
            "donor_raster_directly_pasted": False,
            "boundary_alpha": {"locked_boundary_px": 2.0, "full_by_px": 7.0},
        },
        "candidate_limit": 6,
        "candidate_count": len(records),
        "v18_weave": baseline_weave,
        "records": records,
    }
    report_path = OUT / "phase-synthesis-search.json"
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
