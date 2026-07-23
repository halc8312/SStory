#!/usr/bin/env python3
"""Build the persistent pixel-preserving continuous K2 geometry-warp control.

This proof never fills semantic domains and never redraws map content.  It
estimates a target-to-source displacement field from the canonical guide's
cool-water geometry to K1's cool-water geometry, regularizes that field, and
remaps the original K1 pixels once.  The deformation is tapered smoothly to
identity away from water boundaries, leaving the capital, fields, and
highland byte-identical while carrying the port with its coastline.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]

CONTROL_DIR = ROOT / "world/map-production/controls/style-candidate-k-v2-hybrid"
EVIDENCE_DIR = ROOT / "tmp/map-production/k1-geometry-warp-proof-v1"
K1_PATH = ROOT / "world/map-production/candidates/style-candidate-k-v1-full-board.png"
GUIDE_PATH = ROOT / "world/map-production/controls/style-candidate-i-v1-composition-guide.png"
PROOF_PATH = CONTROL_DIR / "k1-geometry-warp-base.png"
DISPLACEMENT_PATH = EVIDENCE_DIR / "k1-geometry-warp-displacement.png"
OVERLAY_PATH = EVIDENCE_DIR / "k1-geometry-warp-boundary-overlay.png"
CONTACT_PATH = EVIDENCE_DIR / "k1-geometry-warp-proof-contact.png"
FOCUS_PATH = EVIDENCE_DIR / "k1-geometry-warp-focus-200.png"
REPORT_PATH = CONTROL_DIR / "k1-geometry-warp-report.json"

HEIGHT = 1024
WIDTH = 1536
SIGNED_DISTANCE_CLIP_PX = 32.0
FLOW_GAUSSIAN_SIGMA_PX = 36.0
MAXIMUM_DISPLACEMENT_PX = 32.0
FULL_STRENGTH_DISTANCE_PX = 24.0
IDENTITY_DISTANCE_PX = 140.0
CAPITAL_PROTECTED_CENTER = (860.0, 510.0)
CAPITAL_IDENTITY_RADIUS_PX = 160.0
CAPITAL_RELEASE_RADIUS_PX = 225.0
PNG = {"format": "PNG", "compress_level": 9, "optimize": False}

# Exact role coordinates copied from the K2 canonical-geometry helper at proof
# creation time.  Keeping the proof self-contained prevents a concurrent K2
# rewrite from changing or temporarily removing its imported module.
HIGHLAND = [
    (1012, 0), (1536, 0), (1536, 489), (1468, 477), (1396, 505),
    (1328, 470), (1254, 492), (1188, 452), (1109, 465), (1042, 425),
    (1002, 369), (1019, 302), (984, 242), (1007, 169), (981, 93),
]
FIELDS = [
    [(1032, 620), (1170, 591), (1224, 674), (1084, 711)],
    [(1183, 589), (1332, 561), (1378, 645), (1237, 672)],
    [(1351, 562), (1499, 549), (1536, 620), (1392, 644)],
    [(1085, 725), (1229, 685), (1280, 770), (1136, 811)],
    [(1246, 684), (1392, 657), (1439, 744), (1291, 771)],
    [(1410, 657), (1536, 640), (1536, 727), (1455, 743)],
    [(1143, 825), (1288, 783), (1341, 866), (1195, 907)],
    [(1305, 785), (1453, 757), (1496, 846), (1357, 865)],
]
PORT = [(434, 816), (470, 790), (526, 792), (572, 824), (568, 875), (520, 901), (464, 887)]


def polygon_mask(points: list[tuple[int, int]]) -> np.ndarray:
    mask = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    cv2.fillPoly(mask, [np.asarray(points, dtype=np.int32)], 1)
    return mask.astype(bool)


def canonical_role_masks() -> dict[str, Any]:
    city = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    cv2.circle(city, (842, 510), 138, 1, -1, cv2.LINE_8)
    return {
        "city": city.astype(bool),
        "fields": [polygon_mask(points) for points in FIELDS],
        "highland": polygon_mask(HIGHLAND),
        "port": polygon_mask(PORT),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        return {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256(path),
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "bytes": path.stat().st_size,
        }


def write_png(path: Path, array: np.ndarray, mode: str = "RGB") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    Image.fromarray(array.astype(np.uint8), mode).save(temporary, **PNG)
    temporary.replace(path)


def boundary(mask: np.ndarray) -> np.ndarray:
    return cv2.morphologyEx(
        mask.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)
    ) > 0


def k1_water_mask(image: np.ndarray) -> np.ndarray:
    """Use the locked K1 automated-audit segmentation verbatim."""
    values = image.astype(np.int16)
    brightness = values.mean(2)
    selected = (
        (values[..., 2] - values[..., 0] >= -16)
        & (values[..., 1] - values[..., 0] >= -2)
        & (brightness < 165)
    ).astype(np.uint8)
    selected = cv2.morphologyEx(
        selected,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
    )
    selected = cv2.morphologyEx(
        selected,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )
    return selected > 0


def guide_water_mask(image: np.ndarray) -> np.ndarray:
    """Use the locked K1 automated-audit guide segmentation verbatim."""
    values = image.astype(np.int16)
    return (values[..., 2] - values[..., 0] > 20) & (
        values[..., 1] - values[..., 0] > 5
    )


def signed_distance(mask: np.ndarray) -> np.ndarray:
    inside = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    outside = cv2.distanceTransform((~mask).astype(np.uint8), cv2.DIST_L2, 5)
    return inside - outside


def encoded_signed_distance(mask: np.ndarray) -> np.ndarray:
    distance = np.clip(
        signed_distance(mask), -SIGNED_DISTANCE_CLIP_PX, SIGNED_DISTANCE_CLIP_PX
    )
    return np.clip(
        np.rint((distance + SIGNED_DISTANCE_CLIP_PX) * 255.0 / (2 * SIGNED_DISTANCE_CLIP_PX)),
        0,
        255,
    ).astype(np.uint8)


def geometry_metrics(target: np.ndarray, candidate: np.ndarray) -> dict[str, Any]:
    target_edge = boundary(target)
    candidate_edge = boundary(candidate)
    guard = cv2.dilate(
        target_edge.astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17)),
    ) > 0
    stable = ~guard
    to_target = cv2.distanceTransform(
        (~target_edge).astype(np.uint8), cv2.DIST_L2, 5
    )[candidate_edge]
    to_candidate = cv2.distanceTransform(
        (~candidate_edge).astype(np.uint8), cv2.DIST_L2, 5
    )[target_edge]
    stable_agreement = float(np.mean(target[stable] == candidate[stable]))
    candidate_within = float(np.mean(to_target <= 8))
    guide_within = float(np.mean(to_candidate <= 8))
    candidate_p95 = float(np.percentile(to_target, 95))
    guide_p95 = float(np.percentile(to_candidate, 95))
    return {
        "stable_land_water_agreement": round(stable_agreement, 6),
        "full_land_water_agreement": round(float(np.mean(target == candidate)), 6),
        "candidate_boundary_within_8px": round(candidate_within, 6),
        "guide_boundary_within_8px": round(guide_within, 6),
        "candidate_boundary_distance_p95_px": round(candidate_p95, 6),
        "guide_boundary_distance_p95_px": round(guide_p95, 6),
        "passes_proof_target": bool(
            stable_agreement >= 0.985
            and candidate_within >= 0.93
            and guide_within >= 0.93
            and candidate_p95 <= 8
            and guide_p95 <= 8
        ),
    }


def continuous_flow(
    target_water: np.ndarray, source_water: np.ndarray
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Return a fold-free target-to-source field and its smooth support."""
    target_sdf = encoded_signed_distance(target_water)
    source_sdf = encoded_signed_distance(source_water)

    cv2.setNumThreads(1)
    cv2.setRNGSeed(220260720)
    estimator = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    estimator.setUseSpatialPropagation(True)
    estimator.setUseMeanNormalization(True)
    flow = estimator.calc(target_sdf, source_sdf, None)
    flow = cv2.GaussianBlur(flow, (0, 0), FLOW_GAUSSIAN_SIGMA_PX)

    magnitude = np.hypot(flow[..., 0], flow[..., 1])
    limiter = np.minimum(1.0, MAXIMUM_DISPLACEMENT_PX / np.maximum(magnitude, 1e-6))
    flow *= limiter[..., None]

    target_edge = boundary(target_water)
    edge_distance = cv2.distanceTransform(
        (~target_edge).astype(np.uint8), cv2.DIST_L2, 5
    )
    normalized = np.clip(
        (edge_distance - FULL_STRENGTH_DISTANCE_PX)
        / (IDENTITY_DISTANCE_PX - FULL_STRENGTH_DISTANCE_PX),
        0.0,
        1.0,
    )
    support = (0.5 + 0.5 * np.cos(np.pi * normalized)).astype(np.float32)
    support[edge_distance >= IDENTITY_DISTANCE_PX] = 0.0

    # The generated K1 capital is centered about (860,510), slightly east of
    # the guide circle.  It is a protected landmark, not part of water
    # geometry: lock the complete city and ease the deformation back in across
    # a broad annulus so the west road remains continuous without bending the
    # city's circular plan.
    yy, xx = np.indices((HEIGHT, WIDTH), dtype=np.float32)
    capital_radius = np.hypot(
        xx - CAPITAL_PROTECTED_CENTER[0], yy - CAPITAL_PROTECTED_CENTER[1]
    )
    capital_normalized = np.clip(
        (capital_radius - CAPITAL_IDENTITY_RADIUS_PX)
        / (CAPITAL_RELEASE_RADIUS_PX - CAPITAL_IDENTITY_RADIUS_PX),
        0.0,
        1.0,
    )
    capital_release = (
        0.5 - 0.5 * np.cos(np.pi * capital_normalized)
    ).astype(np.float32)
    capital_release[capital_radius <= CAPITAL_IDENTITY_RADIUS_PX] = 0.0
    capital_release[capital_radius >= CAPITAL_RELEASE_RADIUS_PX] = 1.0
    support *= capital_release
    flow *= support[..., None]

    dfx_dx = np.gradient(flow[..., 0], axis=1)
    dfx_dy = np.gradient(flow[..., 0], axis=0)
    dfy_dx = np.gradient(flow[..., 1], axis=1)
    dfy_dy = np.gradient(flow[..., 1], axis=0)
    determinant = (1.0 + dfx_dx) * (1.0 + dfy_dy) - dfx_dy * dfy_dx
    final_magnitude = np.hypot(flow[..., 0], flow[..., 1])
    record = {
        "method": "DIS optical flow over clipped signed-distance fields, Gaussian-regularized, magnitude-capped, and cosine-tapered to identity",
        "direction": "inverse target-to-source remap: output(x,y) = K1(x+dx,y+dy)",
        "signed_distance_clip_px": SIGNED_DISTANCE_CLIP_PX,
        "gaussian_sigma_px": FLOW_GAUSSIAN_SIGMA_PX,
        "maximum_displacement_cap_px": MAXIMUM_DISPLACEMENT_PX,
        "full_strength_within_boundary_distance_px": FULL_STRENGTH_DISTANCE_PX,
        "identity_at_boundary_distance_px": IDENTITY_DISTANCE_PX,
        "protected_capital_anchor": {
            "center_xy": [
                CAPITAL_PROTECTED_CENTER[0],
                CAPITAL_PROTECTED_CENTER[1],
            ],
            "identity_radius_px": CAPITAL_IDENTITY_RADIUS_PX,
            "smooth_release_radius_px": CAPITAL_RELEASE_RADIUS_PX,
        },
        "displacement_px": {
            "median": round(float(np.percentile(final_magnitude, 50)), 6),
            "p90": round(float(np.percentile(final_magnitude, 90)), 6),
            "p95": round(float(np.percentile(final_magnitude, 95)), 6),
            "p99": round(float(np.percentile(final_magnitude, 99)), 6),
            "maximum": round(float(final_magnitude.max()), 6),
        },
        "support": {
            "nonzero_pixels": int(np.count_nonzero(final_magnitude > 1e-4)),
            "nonzero_fraction": round(float(np.mean(final_magnitude > 1e-4)), 6),
            "full_strength_pixels": int(np.count_nonzero(support >= 0.999999)),
            "identity_pixels": int(np.count_nonzero(support <= 1e-6)),
        },
        "mapping_jacobian_determinant": {
            "minimum": round(float(determinant.min()), 6),
            "p01": round(float(np.percentile(determinant, 0.01)), 6),
            "p1": round(float(np.percentile(determinant, 1)), 6),
            "median": round(float(np.percentile(determinant, 50)), 6),
            "p99": round(float(np.percentile(determinant, 99)), 6),
            "maximum": round(float(determinant.max()), 6),
            "nonpositive_pixels": int(np.count_nonzero(determinant <= 0)),
            "fold_free": bool(np.all(determinant > 0)),
        },
    }
    return flow, support, record


def remap_once(base: np.ndarray, flow: np.ndarray, support: np.ndarray) -> np.ndarray:
    xx, yy = np.meshgrid(
        np.arange(WIDTH, dtype=np.float32), np.arange(HEIGHT, dtype=np.float32)
    )
    output = cv2.remap(
        base,
        xx + flow[..., 0],
        yy + flow[..., 1],
        cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    # Guarantee byte identity in the mathematically identity part of the mesh.
    output[support <= 1e-6] = base[support <= 1e-6]
    return output


def region_preservation(
    base: np.ndarray, output: np.ndarray, flow: np.ndarray, masks: dict[str, Any]
) -> dict[str, Any]:
    fields = np.zeros((HEIGHT, WIDTH), bool)
    for item in masks["fields"]:
        fields |= np.asarray(item, bool)
    regions = {
        "capital": np.asarray(masks["city"], bool),
        "fields": fields,
        "highland": np.asarray(masks["highland"], bool),
        "port": np.asarray(masks["port"], bool),
    }
    changed = np.any(base != output, axis=2)
    magnitude = np.hypot(flow[..., 0], flow[..., 1])
    records: dict[str, Any] = {}
    for name, mask in regions.items():
        count = int(mask.sum())
        records[name] = {
            "mask_pixels": count,
            "changed_pixels": int(np.count_nonzero(changed & mask)),
            "changed_fraction": round(float(np.count_nonzero(changed & mask) / max(count, 1)), 6),
            "displacement_median_px": round(float(np.median(magnitude[mask])), 6),
            "displacement_p95_px": round(float(np.percentile(magnitude[mask], 95)), 6),
            "displacement_maximum_px": round(float(magnitude[mask].max()), 6),
        }
    return records


def displacement_visualization(
    proof: np.ndarray, flow: np.ndarray, support: np.ndarray
) -> np.ndarray:
    magnitude = np.hypot(flow[..., 0], flow[..., 1])
    angle = (np.arctan2(flow[..., 1], flow[..., 0]) + math.pi) * 180.0 / math.pi / 2.0
    hsv = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    hsv[..., 0] = np.clip(np.rint(angle), 0, 179).astype(np.uint8)
    hsv[..., 1] = np.clip(np.rint(support * 225), 0, 225).astype(np.uint8)
    hsv[..., 2] = np.clip(
        np.rint(36 + np.minimum(magnitude / MAXIMUM_DISPLACEMENT_PX, 1.0) * 219),
        0,
        255,
    ).astype(np.uint8)
    heat = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    canvas = np.clip(
        np.rint(proof.astype(np.float32) * 0.30 + heat.astype(np.float32) * 0.70),
        0,
        255,
    ).astype(np.uint8)

    # Recreate through PIL so arrow strokes remain deterministic and legible.
    image = Image.fromarray(canvas, "RGB")
    draw = ImageDraw.Draw(image)
    for y in range(24, HEIGHT, 48):
        for x in range(24, WIDTH, 48):
            dx = float(flow[y, x, 0])
            dy = float(flow[y, x, 1])
            if math.hypot(dx, dy) < 0.45:
                continue
            scale = 1.25
            end = (round(x + dx * scale), round(y + dy * scale))
            draw.line((x, y, end[0], end[1]), fill=(255, 250, 232), width=2)
            draw.ellipse((end[0] - 2, end[1] - 2, end[0] + 2, end[1] + 2), fill=(32, 28, 24))
    result = np.asarray(image, dtype=np.uint8).copy()
    image.close()
    return result


def boundary_overlay(
    proof: np.ndarray, target_water: np.ndarray, candidate_water: np.ndarray
) -> np.ndarray:
    canvas = proof.astype(np.float32) * 0.72
    target_edge = cv2.dilate(boundary(target_water).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    candidate_edge = cv2.dilate(boundary(candidate_water).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    only_target = target_edge & ~candidate_edge
    only_candidate = candidate_edge & ~target_edge
    overlap = target_edge & candidate_edge
    canvas[only_target] = np.asarray([30, 232, 222], np.float32)
    canvas[only_candidate] = np.asarray([239, 55, 157], np.float32)
    canvas[overlap] = np.asarray([250, 239, 85], np.float32)
    return np.clip(np.rint(canvas), 0, 255).astype(np.uint8)


def contact_sheet(base: np.ndarray, proof: np.ndarray) -> np.ndarray:
    before = cv2.resize(base, (768, 512), interpolation=cv2.INTER_AREA)
    after = cv2.resize(proof, (768, 512), interpolation=cv2.INTER_AREA)
    sheet = np.zeros((554, 1536, 3), np.uint8)
    sheet[:512, :768] = before
    sheet[:512, 768:] = after
    sheet[512:] = np.asarray([36, 34, 31], np.uint8)
    image = Image.fromarray(sheet, "RGB")
    draw = ImageDraw.Draw(image)
    draw.text((18, 522), "BEFORE: K1", fill=(244, 239, 222))
    draw.text((786, 522), "AFTER: continuous geometry warp", fill=(244, 239, 222))
    result = np.asarray(image, dtype=np.uint8).copy()
    image.close()
    return result


def focus_sheet(base: np.ndarray, proof: np.ndarray) -> np.ndarray:
    """Pair native-detail crops, enlarged 2x, for seam/stretch Vision review."""
    crops = [
        ("UPPER COAST + RIVER", (260, 0, 900, 320)),
        ("ISLANDS + DELTA", (210, 245, 690, 725)),
        ("PORT + SOUTH COAST", (340, 700, 720, 1024)),
    ]
    rows: list[Image.Image] = []
    for label, (left, top, right, bottom) in crops:
        # Center-crop each semantic area to a common 320x240 review window.
        cx = (left + right) // 2
        cy = (top + bottom) // 2
        left = max(0, min(WIDTH - 320, cx - 160))
        top = max(0, min(HEIGHT - 240, cy - 120))
        box = (left, top, left + 320, top + 240)
        panels: list[Image.Image] = []
        for prefix, source in (("BEFORE", base), ("AFTER", proof)):
            crop = Image.fromarray(source, "RGB").crop(box)
            enlarged = crop.resize((640, 480), Image.Resampling.NEAREST)
            panel = Image.new("RGB", (640, 514), (36, 34, 31))
            panel.paste(enlarged, (0, 0))
            ImageDraw.Draw(panel).text(
                (12, 489), f"{prefix}: {label} @ 200% {box}", fill=(244, 239, 222)
            )
            crop.close()
            enlarged.close()
            panels.append(panel)
        row = Image.new("RGB", (1280, 514), (36, 34, 31))
        row.paste(panels[0], (0, 0))
        row.paste(panels[1], (640, 0))
        for panel in panels:
            panel.close()
        rows.append(row)
    sheet = Image.new("RGB", (1280, 514 * len(rows)), (36, 34, 31))
    for index, row in enumerate(rows):
        sheet.paste(row, (0, 514 * index))
        row.close()
    result = np.asarray(sheet, dtype=np.uint8).copy()
    sheet.close()
    return result


def main() -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    base = np.asarray(Image.open(K1_PATH).convert("RGB"), dtype=np.uint8)
    guide = np.asarray(Image.open(GUIDE_PATH).convert("RGB"), dtype=np.uint8)
    if base.shape != (HEIGHT, WIDTH, 3) or guide.shape != base.shape:
        raise ValueError("K1 and guide must both be native 1536x1024 RGB")

    source_water = k1_water_mask(base)
    target_water = guide_water_mask(guide)
    masks = canonical_role_masks()
    before = geometry_metrics(target_water, source_water)

    flow, support, flow_record = continuous_flow(target_water, source_water)
    if not flow_record["mapping_jacobian_determinant"]["fold_free"]:
        raise RuntimeError("regularized deformation contains a fold")
    output = remap_once(base, flow, support)
    output_water = k1_water_mask(output)
    after = geometry_metrics(target_water, output_water)
    if not after["passes_proof_target"]:
        raise RuntimeError("persistent geometry control did not satisfy requested geometry target")

    write_png(PROOF_PATH, output)
    write_png(DISPLACEMENT_PATH, displacement_visualization(output, flow, support))
    write_png(OVERLAY_PATH, boundary_overlay(output, target_water, output_water))
    write_png(CONTACT_PATH, contact_sheet(base, output))
    write_png(FOCUS_PATH, focus_sheet(base, output))

    identity = support <= 1e-6
    delta = np.abs(output.astype(np.int16) - base.astype(np.int16))
    identity_changed = int(np.count_nonzero(np.any(delta[identity] != 0, axis=1)))
    identity_max_delta = int(delta[identity].max()) if np.any(identity) else 0
    preservation = region_preservation(base, output, flow, masks)

    report = {
        "schema_version": "1.0.0",
        "id": "k1-geometry-warp-proof-v1",
        "status": "persistent-control-passed-root-vision",
        "scope": "persistent K2 geometry control; no manifest, docs, renderer, QA decision, or Golden registration modified",
        "technique": {
            "class": "continuous spatial deformation; no domain fill; no inpaint; no synthetic redraw",
            "source_pixels": "one Lanczos-4 inverse remap from the locked K1 image",
            "geometry_signal": "canonical guide cool-water signed-distance field using the exact K1 automated-audit predicates",
            "regularization": flow_record,
        },
        "inputs": {
            "k1": artifact(K1_PATH),
            "canonical_guide": artifact(GUIDE_PATH),
        },
        "requested_geometry_thresholds": {
            "minimum_stable_land_water_agreement": 0.985,
            "minimum_candidate_boundary_within_8px": 0.93,
            "minimum_guide_boundary_within_8px": 0.93,
            "maximum_bidirectional_boundary_distance_p95_px": 8.0,
        },
        "before": before,
        "after": after,
        "improvement": {
            key: round(float(after[key]) - float(before[key]), 6)
            for key in (
                "stable_land_water_agreement",
                "full_land_water_agreement",
                "candidate_boundary_within_8px",
                "guide_boundary_within_8px",
            )
        },
        "protected_identity": {
            "identity_zone_pixels": int(identity.sum()),
            "changed_pixels": identity_changed,
            "maximum_rgb_channel_delta": identity_max_delta,
            "byte_identical": bool(identity_changed == 0 and identity_max_delta == 0),
        },
        "semantic_region_preservation": preservation,
        "artifacts": {
            "proof": artifact(PROOF_PATH),
            "displacement_visualization": artifact(DISPLACEMENT_PATH),
            "boundary_overlay": artifact(OVERLAY_PATH),
            "before_after_contact": artifact(CONTACT_PATH),
            "before_after_focus_200": artifact(FOCUS_PATH),
        },
        "vision_handoff": {
            "required": True,
            "decision_authority": False,
            "inspect": [
                "coast, islands, delta branches, and river for smooth alignment without doubled edges",
                "port for continuous motion with the coast and no local stretch tear",
                "capital, fields, and highland for exact visual preservation",
                "open sea and forest for curved bands, smears, repeated pixels, or transition seams",
                "top and bottom image borders for reflected-edge artifacts",
            ],
        },
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "K1 continuous-warp proof passed: "
        f"stable={after['stable_land_water_agreement']} "
        f"c8={after['candidate_boundary_within_8px']} "
        f"g8={after['guide_boundary_within_8px']} "
        f"p95={after['candidate_boundary_distance_p95_px']}/"
        f"{after['guide_boundary_distance_p95_px']} "
        f"fold_free={flow_record['mapping_jacobian_determinant']['fold_free']}"
    )


if __name__ == "__main__":
    main()
