#!/usr/bin/env python3
"""Prototype H19 with sharp, component-local H4 exemplar repair.

The first required stage is a bounded east-highland A/B proof.  It does not
render or write a full candidate.  Only after that proof has passed author
Vision review may ``--mode full`` be used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw

import render_style_candidate_h15_flat_height as h15
import render_style_candidate_h16_micro_inpaint as h16


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_H4 = h15.DEFAULT_H4
DEFAULT_H5 = h15.DEFAULT_H5
DEFAULT_H17 = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-h-v17-surgical-flattening-raw.png"
)
DEFAULT_B1 = h15.DEFAULT_B1
DEFAULT_OUTPUT = REPO_ROOT / "tmp/map-production/h19-prototype"
DEFAULT_PROOF_ITERATION = "proof-2"
LOCKS = {
    "h4": h15.LOCKS["h4"],
    "h5": h15.LOCKS["h5"],
    "h17": "852afaf37942f40a65e6c92fbe20496200ec27216960e76fbbf09486f51f4a72",
    "b1": h15.LOCKS["b1"],
}
CANVAS = h15.CANVAS
SEED = 0x4831395F5155494C
PROOF_ROI = (1050, 110, 1450, 450)
PATCH_SIZE = 63
PNG = {"format": "PNG", "compress_level": 9, "optimize": False}

PROOF_SOURCE = "style-candidate-h-v19-highland-proof-a-h4.png"
PROOF_REPAIRED = "style-candidate-h-v19-highland-proof-b-repaired.png"
PROOF_MASK = "style-candidate-h-v19-highland-proof-mask.png"
PROOF_CONTACT = "style-candidate-h-v19-highland-proof-contact.png"
PROOF_REPORT = "style-candidate-h-v19-highland-proof.json"


class H19Error(ValueError):
    """Raised when the locked H19 prototype contract is violated."""


@dataclass(frozen=True)
class RepairComponent:
    component_id: int
    x: int
    y: int
    width: int
    height: int
    area: int
    mask: np.ndarray

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


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
        raise H19Error(f"locked {key} input missing or changed: {path}")
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    if image.size != CANVAS:
        image.close()
        raise H19Error(f"{key} must be {CANVAS[0]}x{CANVAS[1]}")
    return image


def _inside_roi(component: RepairComponent, roi: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = roi
    return (
        component.x >= left
        and component.y >= top
        and component.x + component.width <= right
        and component.y + component.height <= bottom
    )


def _repair_components(
    source: np.ndarray,
    search: np.ndarray,
    forbidden: np.ndarray,
) -> list[RepairComponent]:
    """Group adjacent triangle strokes into small, non-overlapping glyph units."""

    contours = h16._triangle_contours(source, search & ~forbidden)
    core = np.zeros(search.shape, np.uint8)
    for contour in contours:
        cv2.drawContours(core, [cv2.convexHull(contour)], -1, 1, cv2.FILLED)

    # Three pixels group the two or three strokes of one pictorial glyph without
    # turning the dense highland into a region fill.
    grouped = cv2.dilate(
        core,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        iterations=1,
    )
    count, labels, stats, _ = cv2.connectedComponentsWithStats(grouped, 8)
    components: list[RepairComponent] = []
    expansion = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
    next_id = 1
    for label in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[label])
        if area < 6 or width > 49 or height > 49:
            continue
        local = (labels == label).astype(np.uint8)
        local = cv2.dilate(local, expansion, iterations=1) > 0
        local &= search & ~forbidden
        if not local.any() or int(local.sum()) > 2500:
            continue
        ys, xs = np.where(local)
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        components.append(
            RepairComponent(
                component_id=next_id,
                x=x0,
                y=y0,
                width=x1 - x0,
                height=y1 - y0,
                area=int(local.sum()),
                mask=local,
            )
        )
        next_id += 1
    return sorted(components, key=lambda item: (item.y, item.x, item.component_id))


def _donor_valid_mask(masks: dict[str, np.ndarray]) -> np.ndarray:
    """Return hand-bounded H4 flat scrub/parchment zones only."""

    valid = np.zeros((CANVAS[1], CANVAS[0]), np.uint8)
    rectangles = (
        (600, 535, 790, 770),
        (770, 575, 970, 785),
        (955, 520, 1125, 760),
        (1120, 520, 1500, 610),
        (790, 80, 980, 355),
        (470, 555, 675, 750),
    )
    for left, top, right, bottom in rectangles:
        valid[top:bottom, left:right] = 1
    excluded = (
        masks["highland"]
        | masks["water"]
        | masks["city"]
        | masks["port"]
        | masks["coast"]
    )
    valid[excluded] = 0
    return valid.astype(bool)


def _integral(binary: np.ndarray) -> np.ndarray:
    return cv2.integral(binary.astype(np.uint8), sdepth=cv2.CV_32S)


def _box_sum(integral: np.ndarray, left: int, top: int, right: int, bottom: int) -> int:
    return int(
        integral[bottom, right]
        - integral[top, right]
        - integral[bottom, left]
        + integral[top, left]
    )


def _candidate_donors(
    source: np.ndarray,
    valid: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Build unique sharp H4 donor patches with no detected height glyphs."""

    half = PATCH_SIZE // 2
    valid_integral = _integral(valid)
    gray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
    local = cv2.GaussianBlur(gray, (0, 0), 3.0)
    dark = local.astype(np.int16) - gray.astype(np.int16)
    low = cv2.GaussianBlur(source.astype(np.float32), (0, 0), 7.0)
    high = source.astype(np.float32) - cv2.GaussianBlur(
        source.astype(np.float32), (0, 0), 3.1
    )
    gx = cv2.Sobel(low, cv2.CV_32F, 1, 0, ksize=3) / 8.0
    gy = cv2.Sobel(low, cv2.CV_32F, 0, 1, ksize=3) / 8.0

    donor_triangles = h16._triangle_contours(source, valid)
    triangle_pixels = np.zeros(valid.shape, np.uint8)
    for contour in donor_triangles:
        cv2.drawContours(triangle_pixels, [cv2.convexHull(contour)], -1, 1, cv2.FILLED)
    triangle_integral = _integral(triangle_pixels > 0)

    centers: list[tuple[int, int]] = []
    features: list[list[float]] = []
    full_area = PATCH_SIZE * PATCH_SIZE
    for y in range(half, CANVAS[1] - half, 5):
        top, bottom = y - half, y + half + 1
        for x in range(half, CANVAS[0] - half, 5):
            left, right = x - half, x + half + 1
            if _box_sum(valid_integral, left, top, right, bottom) < round(full_area * 0.90):
                continue
            # H4 paper grain itself produces a few tiny triangular contours.
            # Staying in the lowest quartile of the locked flat zones avoids
            # deliberate mountain glyphs without selecting unnaturally blank paper.
            if _box_sum(triangle_integral, left, top, right, bottom) > 240:
                continue
            patch_dark = dark[top:bottom, left:right]
            dark_fraction = float((patch_dark > 11).mean())
            if not 0.17 <= dark_fraction <= 0.31:
                continue
            high_std = float(high[top:bottom, left:right].std())
            if not 15.0 <= high_std <= 23.0:
                continue
            centers.append((x, y))
            features.append(
                [
                    *low[y, x].tolist(),
                    *gx[y, x].tolist(),
                    *gy[y, x].tolist(),
                    high_std,
                    dark_fraction * 100.0,
                ]
            )
    if len(centers) < 256:
        raise H19Error(f"insufficient approved H4 donor patches: {len(centers)}")
    return (
        np.asarray(centers, np.int32),
        np.asarray(features, np.float32),
        {
            "approved_patch_centers": len(centers),
            "patch_size_pixels": PATCH_SIZE,
            "source": "H4 flat scrub/parchment zones",
            "maximum_triangle_proxy_pixels_per_patch": 240,
            "minimum_valid_zone_fraction": 0.90,
        },
    )


def _target_feature(
    source: np.ndarray,
    low: np.ndarray,
    gx: np.ndarray,
    gy: np.ndarray,
    component: RepairComponent,
) -> np.ndarray:
    cx, cy = component.center
    half = PATCH_SIZE // 2
    left, top = cx - half, cy - half
    right, bottom = left + PATCH_SIZE, top + PATCH_SIZE
    patch = source[top:bottom, left:right].astype(np.float32)
    patch_low = cv2.GaussianBlur(patch, (0, 0), 3.1)
    return np.asarray(
        [
            *low[cy, cx].tolist(),
            *gx[cy, cx].tolist(),
            *gy[cy, cx].tolist(),
            float((patch - patch_low).std()),
            float(
                (
                    cv2.GaussianBlur(
                        cv2.cvtColor(patch.astype(np.uint8), cv2.COLOR_RGB2GRAY),
                        (0, 0),
                        3.0,
                    ).astype(np.int16)
                    - cv2.cvtColor(patch.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(
                        np.int16
                    )
                    > 11
                ).mean()
                * 100.0
            ),
        ],
        np.float32,
    )


def _choose_donor(
    component: RepairComponent,
    feature: np.ndarray,
    centers: np.ndarray,
    features: np.ndarray,
    used: set[int],
) -> int:
    scales = np.asarray([8, 8, 8, 1.8, 1.8, 1.8, 1.8, 1.8, 1.8, 3.0, 2.2], np.float32)
    delta = (features - feature) / scales
    score = np.square(delta).sum(axis=1)
    cx, cy = component.center
    distance = np.hypot(centers[:, 0] - cx, centers[:, 1] - cy)
    score += distance / 420.0
    if used:
        score[np.fromiter(used, dtype=np.int32)] = np.inf
    ranked = np.argsort(score, kind="stable")
    finite = ranked[np.isfinite(score[ranked])]
    if not len(finite):
        raise H19Error("exhausted unique H4 donor patches")
    # A deterministic choice within the tightly matched first 12 avoids a
    # spatial cadence while retaining color/gradient fit.
    window = finite[: min(12, len(finite))]
    position = (component.component_id * 7 + component.x * 3 + component.y) % len(window)
    return int(window[position])


def _local_component_patch(
    component: RepairComponent,
    center: tuple[int, int],
) -> tuple[int, int, int, int, np.ndarray]:
    cx, cy = component.center
    half = PATCH_SIZE // 2
    left, top = cx - half, cy - half
    right, bottom = left + PATCH_SIZE, top + PATCH_SIZE
    if left < 0 or top < 0 or right > CANVAS[0] or bottom > CANVAS[1]:
        raise H19Error(f"component {component.component_id} is too near canvas edge")
    local_mask = component.mask[top:bottom, left:right].astype(np.uint8) * 255
    if not local_mask.any():
        raise H19Error(f"empty local mask for component {component.component_id}")
    return left, top, right, bottom, local_mask


def _matched_donor_patch(
    source: np.ndarray,
    destination: np.ndarray,
    donor_center: tuple[int, int],
    target_box: tuple[int, int, int, int],
    local_mask: np.ndarray,
) -> np.ndarray:
    half = PATCH_SIZE // 2
    sx, sy = donor_center
    donor = source[sy - half : sy + half + 1, sx - half : sx + half + 1].astype(
        np.float32
    )
    donor_low = cv2.GaussianBlur(donor, (0, 0), 3.1)
    donor_high = donor - donor_low

    left, top, right, bottom = target_box
    target = destination[top:bottom, left:right].astype(np.float32)
    outside = local_mask == 0
    yy, xx = np.indices((PATCH_SIZE, PATCH_SIZE), dtype=np.float32)
    plane_inputs = np.column_stack(
        (
            np.ones(int(outside.sum()), np.float32),
            xx[outside] - half,
            yy[outside] - half,
        )
    )
    plane = np.empty_like(target)
    for channel in range(3):
        values = target[..., channel][outside]
        coefficients, *_ = np.linalg.lstsq(plane_inputs, values, rcond=None)
        plane[..., channel] = (
            coefficients[0]
            + coefficients[1] * (xx - half)
            + coefficients[2] * (yy - half)
        )

    target_high = target - cv2.GaussianBlur(target, (0, 0), 3.1)
    ring = cv2.dilate((local_mask > 0).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    ring &= local_mask == 0
    target_scale = float(target_high[ring].std()) if ring.any() else float(target_high.std())
    donor_scale = max(float(donor_high.std()), 1e-6)
    scale = float(np.clip(target_scale / donor_scale, 0.78, 1.22))
    return np.clip(plane + donor_high * scale, 0, 255).round().astype(np.uint8)


def _draw_flat_marks(
    candidate: np.ndarray,
    components: Sequence[RepairComponent],
) -> dict[str, Any]:
    """Add sparse, unique plan-view chips/hachures inside repaired components."""

    overlay = Image.fromarray(candidate, "RGB")
    draw = ImageDraw.Draw(overlay, "RGBA")
    rng = random.Random(SEED ^ 0x524F434B)
    chips = 0
    hachures = 0
    angle_bins = [0] * 12
    signatures: set[tuple[int, ...]] = set()
    for component in components:
        if rng.random() > 0.34:
            continue
        ys, xs = np.where(component.mask)
        if not len(xs):
            continue
        index = rng.randrange(len(xs))
        x, y = int(xs[index]), int(ys[index])
        base = candidate[y, x].astype(int)
        ink = tuple(int(value) for value in np.clip(base - rng.randint(18, 39), 24, 210))
        angle_bin = rng.randrange(12)
        angle = math.pi * (angle_bin + rng.uniform(0.08, 0.92)) / 12.0
        length = rng.uniform(2.2, min(9.0, max(3.0, component.width * 0.55)))
        if rng.random() < 0.47 and component.width >= 7 and component.height >= 7:
            vertices = rng.randint(5, 8)
            radius_x = rng.uniform(2.0, min(5.6, component.width * 0.28))
            radius_y = rng.uniform(1.2, min(3.8, component.height * 0.25))
            points: list[tuple[int, int]] = []
            signature: list[int] = [vertices, round(radius_x * 10), round(radius_y * 10)]
            for vertex in range(vertices):
                theta = angle + 2.0 * math.pi * vertex / vertices
                jitter = rng.uniform(0.68, 1.28)
                px = round(x + math.cos(theta) * radius_x * jitter)
                py = round(y + math.sin(theta) * radius_y * jitter)
                if not (0 <= px < CANVAS[0] and 0 <= py < CANVAS[1]) or not component.mask[py, px]:
                    points = []
                    break
                points.append((px, py))
                signature.extend((px - x, py - y))
            if points and tuple(signature) not in signatures:
                signatures.add(tuple(signature))
                draw.polygon(points, fill=(*ink, rng.randint(70, 118)))
                chips += 1
                angle_bins[angle_bin] += 1
                continue
        x2 = round(x + math.cos(angle) * length)
        y2 = round(y + math.sin(angle) * length)
        if 0 <= x2 < CANVAS[0] and 0 <= y2 < CANVAS[1] and component.mask[y2, x2]:
            draw.line((x, y, x2, y2), fill=(*ink, rng.randint(105, 165)), width=1)
            hachures += 1
            angle_bins[angle_bin] += 1
    result = np.asarray(overlay, np.uint8).copy()
    overlay.close()
    mark_allowed = np.zeros(candidate.shape[:2], bool)
    for component in components:
        mark_allowed |= component.mask
    candidate[mark_allowed] = result[mark_allowed]
    return {
        "irregular_chips": chips,
        "short_hachures": hachures,
        "unique_chip_signatures": len(signatures),
        "angle_bins": angle_bins,
        "angle_bin_max_min_nonzero_ratio": round(
            max(angle_bins) / max(1, min(value for value in angle_bins if value)), 6
        )
        if any(angle_bins)
        else 0.0,
        "periodic_grid_used": False,
        "exact_group_cloning_used": False,
    }


def _repair(
    source: np.ndarray,
    masks: dict[str, np.ndarray],
    components: Sequence[RepairComponent],
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    candidate = source.copy()
    valid = _donor_valid_mask(masks)
    centers, features, donor_audit = _candidate_donors(source, valid)
    low = cv2.GaussianBlur(source.astype(np.float32), (0, 0), 7.0)
    gx = cv2.Sobel(low, cv2.CV_32F, 1, 0, ksize=3) / 8.0
    gy = cv2.Sobel(low, cv2.CV_32F, 0, 1, ksize=3) / 8.0
    used: set[int] = set()
    allowed = np.zeros(masks["highland"].shape, bool)
    records: list[dict[str, Any]] = []
    hashes: set[str] = set()
    for component in components:
        left, top, right, bottom, local_mask = _local_component_patch(component, component.center)
        feature = _target_feature(source, low, gx, gy, component)
        donor_index = _choose_donor(component, feature, centers, features, used)
        used.add(donor_index)
        donor_center = tuple(int(value) for value in centers[donor_index])
        donor_patch = _matched_donor_patch(
            source,
            candidate,
            donor_center,
            (left, top, right, bottom),
            local_mask,
        )
        patch_hash = hashlib.sha256(donor_patch.tobytes()).hexdigest()
        if patch_hash in hashes:
            raise H19Error("exact matched donor patch repetition detected")
        hashes.add(patch_hash)
        target_patch = candidate[top:bottom, left:right].copy()
        authoritative_mask = local_mask.copy()
        cloned_patch = cv2.seamlessClone(
            donor_patch,
            target_patch,
            local_mask.copy(),
            (PATCH_SIZE // 2, PATCH_SIZE // 2),
            cv2.NORMAL_CLONE,
        )
        # Poisson supplies the boundary seam; the sharp matched H4 donor is kept
        # in the interior so mountain gradients cannot survive the solve.
        distance = cv2.distanceTransform(authoritative_mask, cv2.DIST_L2, 3)
        interior = distance >= 2.75
        local_result = cloned_patch
        local_result[interior] = donor_patch[interior]
        destination = candidate[top:bottom, left:right]
        destination[authoritative_mask > 0] = local_result[authoritative_mask > 0]
        allowed |= component.mask
        clone_violations = np.any(candidate != source, axis=2) & ~allowed
        if clone_violations.any():
            violation_y, violation_x = np.where(clone_violations)
            raise H19Error(
                "component-local clone escaped mask at "
                f"component {component.component_id} box="
                f"{component.x},{component.y},{component.width},{component.height}: "
                f"{int(clone_violations.sum())} pixels bounds="
                f"{int(violation_x.min())},{int(violation_y.min())},"
                f"{int(violation_x.max())},{int(violation_y.max())}"
            )
        score = float(np.square((features[donor_index] - feature)).sum())
        records.append(
            {
                "component_id": component.component_id,
                "target_box_px": [component.x, component.y, component.width, component.height],
                "target_pixels": component.area,
                "donor_center_px": list(donor_center),
                "donor_patch_sha256": patch_hash,
                "raw_feature_squared_error": round(score, 6),
            }
        )
    mark_stats = _draw_flat_marks(candidate, components)
    changed = np.any(candidate != source, axis=2)
    violations = changed & ~allowed
    if violations.any():
        raise H19Error(f"protected-pixel violation: {int(violations.sum())}")
    return candidate, allowed, records, donor_audit, mark_stats


def _proof_contact(source_crop: Image.Image, repaired_crop: Image.Image) -> Image.Image:
    width, height = source_crop.size
    contact = Image.new("RGB", (width * 4, height * 7), source_crop.getpixel((0, 0)))
    draw = ImageDraw.Draw(contact)
    contact.paste(source_crop, (0, 30))
    contact.paste(repaired_crop, (width, 30))
    draw.text((8, 8), "A  H4 source (native)", fill=(235, 225, 190))
    draw.text((width + 8, 8), "B  H19 exemplar repair (native)", fill=(235, 225, 190))
    two_a = source_crop.resize((width * 2, height * 2), Image.Resampling.NEAREST)
    two_b = repaired_crop.resize((width * 2, height * 2), Image.Resampling.NEAREST)
    contact.paste(two_a, (0, height + 60))
    contact.paste(two_b, (width * 2, height + 60))
    two_a.close()
    two_b.close()
    inset_box = (110, 70, 310, 240)
    four_a = source_crop.crop(inset_box).resize((800, 680), Image.Resampling.NEAREST)
    four_b = repaired_crop.crop(inset_box).resize((800, 680), Image.Resampling.NEAREST)
    base_y = height * 3 + 90
    contact.paste(four_a, (0, base_y))
    contact.paste(four_b, (800, base_y))
    four_a.close()
    four_b.close()
    draw.text((8, height + 40), "200% nearest-neighbour A / B", fill=(235, 225, 190))
    draw.text((8, base_y - 20), "400% central A / B", fill=(235, 225, 190))
    return contact


def _triangle_count(image: np.ndarray, mask: np.ndarray) -> int:
    return len(h16._triangle_contours(image, mask))


def render_proof(
    *,
    h4_path: Path = DEFAULT_H4,
    output_dir: Path = DEFAULT_OUTPUT / DEFAULT_PROOF_ITERATION,
    replace: bool = False,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    try:
        output_dir.relative_to(DEFAULT_OUTPUT.resolve())
    except ValueError as exc:
        raise H19Error("proof output must stay below tmp/map-production/h19-prototype") from exc
    paths = {
        "source": output_dir / PROOF_SOURCE,
        "repaired": output_dir / PROOF_REPAIRED,
        "mask": output_dir / PROOF_MASK,
        "contact": output_dir / PROOF_CONTACT,
        "report": output_dir / PROOF_REPORT,
    }
    if not replace and any(path.exists() for path in paths.values()):
        raise H19Error("refusing to overwrite existing H19 proof")

    source_image = _load_locked(h4_path, "h4")
    try:
        source = np.asarray(source_image, np.uint8).copy()
        masks = h15._semantic_masks(source_image)
        forbidden = masks["city"] | masks["port"] | masks["water"]
        components = [
            component
            for component in _repair_components(source, masks["highland"], forbidden)
            if _inside_roi(component, PROOF_ROI)
        ]
        if len(components) < 40:
            raise H19Error(f"proof did not find enough components: {len(components)}")
        candidate, allowed, records, donor_audit, mark_stats = _repair(
            source, masks, components
        )
        left, top, right, bottom = PROOF_ROI
        roi_mask = np.zeros_like(allowed)
        roi_mask[top:bottom, left:right] = masks["highland"][top:bottom, left:right]
        before = _triangle_count(source, roi_mask)
        after = _triangle_count(candidate, roi_mask)
        reduction = 1.0 - after / max(before, 1)
        changed = np.any(candidate != source, axis=2)
        violations = changed & ~allowed
        roi_pixels = (right - left) * (bottom - top)

        source_crop = source_image.crop(PROOF_ROI)
        repaired_image = Image.fromarray(candidate, "RGB")
        repaired_crop = repaired_image.crop(PROOF_ROI)
        mask_crop = Image.fromarray(
            allowed[top:bottom, left:right].astype(np.uint8) * 255, "L"
        )
        contact = _proof_contact(source_crop, repaired_crop)
        output_dir.mkdir(parents=True, exist_ok=True)
        source_crop.save(paths["source"], **PNG)
        repaired_crop.save(paths["repaired"], **PNG)
        mask_crop.save(paths["mask"], **PNG)
        contact.save(paths["contact"], **PNG)

        donor_hashes = [record["donor_patch_sha256"] for record in records]
        gates = {
            "proof_only_no_full_master_written": True,
            "protected_exact": int(violations.sum()) == 0,
            "allowed_edit_coverage_below_20_percent_of_canvas": float(allowed.mean()) < 0.20,
            "triangle_proxy_reduction_at_least_90_percent": reduction >= 0.90,
            "unique_donor_for_every_component": len(set(donor_hashes)) == len(records),
            "no_broad_fill_blur_or_inpaint": True,
        }
        report = {
            "schema_version": "1.0.0",
            "id": "style-candidate-h-v19-highland-exemplar-proof",
            "status": "proof_rejected_author_vision",
            "golden_reference": False,
            "scope": {
                "stage": "mandatory small crop proof before full render",
                "iteration": 2,
                "roi_px": list(PROOF_ROI),
                "roi_pixels": roi_pixels,
                "full_master_written": False,
            },
            "input": _artifact(h4_path),
            "method": {
                "operation": "component-local sharp H4 exemplar transfer with NORMAL_CLONE",
                "broad_region_fill_used": False,
                "blur_or_inpaint_used_for_repair": False,
                "shoreline_touched": False,
                "patch_size_pixels": PATCH_SIZE,
                "detected_component_count": len(components),
                "patch_source_count": len(records),
                "unique_patch_source_count": len(set(donor_hashes)),
                "donor_pool": donor_audit,
                "flat_mark_vocabulary": mark_stats,
            },
            "exact_protection": {
                "allowed_edit_pixels_full_canvas": int(allowed.sum()),
                "allowed_edit_coverage_percent_full_canvas": round(float(allowed.mean() * 100.0), 6),
                "changed_pixels": int(changed.sum()),
                "protected_violation_pixels": int(violations.sum()),
                "protected_pixel_equality_percent": 100.0,
            },
            "perspective_proxy": {
                "triangular_A_like_components_before": before,
                "triangular_A_like_components_after": after,
                "reduction_fraction": round(reduction, 6),
            },
            "gates": gates,
            "component_records": records,
            "self_vision_review": {
                "status": "rejected",
                "acceptance_authority": False,
                "reviewed_views": [
                    "native_A_B",
                    "200_percent_nearest_A_B",
                    "400_percent_central_nearest_A_B",
                ],
                "score": 38,
                "threshold": 94,
                "immediate_failure_detected": True,
                "decision": "reject and stop H19 before any full-master render",
                "findings": [
                    "large pictorial mountain forms remain visibly intact",
                    "transferred donors form repeated short striped fragments",
                    "component boundaries read as quilting seams at 200 and 400 percent",
                    "the repaired texture is busier and less coherent than locked H4",
                ],
                "reject_if": [
                    "patch_repetition",
                    "quilting_seams",
                    "blur_or_pockmarks",
                    "residual_pictorial_height",
                    "paper_microdetail_loss",
                ],
            },
            "outputs": {name: _artifact(path) for name, path in paths.items() if name != "report"},
        }
        paths["report"].write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return report
    finally:
        source_image.close()
        for name in ("source_crop", "repaired_image", "repaired_crop", "mask_crop", "contact"):
            value = locals().get(name)
            if isinstance(value, Image.Image):
                value.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("proof", "full"), default="proof")
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT / DEFAULT_PROOF_ITERATION
    )
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode == "full":
        print("H19 full render is locked until the crop proof passes author Vision review")
        return 2
    try:
        report = render_proof(output_dir=args.output_dir, replace=args.replace)
    except (H19Error, OSError, ValueError, cv2.error) as exc:
        print(f"H19 proof failed: {exc}")
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "components": report["method"]["detected_component_count"],
                "patch_sources": report["method"]["patch_source_count"],
                "triangle_reduction": report["perspective_proxy"]["reduction_fraction"],
                "contact": report["outputs"]["contact"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if all(report["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
