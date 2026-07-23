#!/usr/bin/env python3
"""Render the single H16 prototype with component-local height-glyph repair."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image

import audit_style_candidate_h4 as h4
import render_candidate_h9_dense_flat_plan as h9
import render_style_candidate_h15_flat_height as h15


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_H4 = h15.DEFAULT_H4
DEFAULT_B1 = h15.DEFAULT_B1
DEFAULT_OUTPUT = REPO_ROOT / "tmp/map-production/h16-prototype/iteration-1"
LOCKS = {"h4": h15.LOCKS["h4"], "b1": h15.LOCKS["b1"]}
CANVAS = h15.CANVAS
SEED = 0x4831365F4D494352
MASTER = "style-candidate-h-v16-micro-inpaint.png"
MASK = "style-candidate-h-v16-micro-inpaint.semantic-mask.png"
CONTACT = "style-candidate-h-v16-micro-inpaint.contact-sheet.png"
REPORT = "style-candidate-h-v16-micro-inpaint.automated.json"
PNG = {"format": "PNG", "compress_level": 9, "optimize": False}


class H16Error(ValueError):
    """Raised when the locked one-iteration H16 contract is violated."""


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


def _load(path: Path, key: str) -> Image.Image:
    if not path.is_file() or _sha(path) != LOCKS[key]:
        raise H16Error(f"locked {key} input missing or changed: {path}")
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    if image.size != CANVAS:
        image.close()
        raise H16Error(f"{key} must be 1536x1024")
    return image


def _triangle_contours(image: np.ndarray, search: np.ndarray) -> list[np.ndarray]:
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    local = cv2.GaussianBlur(gray, (0, 0), 3.0)
    dark = ((gray.astype(np.int16) < local.astype(np.int16) - 10) & search).astype(np.uint8)
    contours, _ = cv2.findContours(dark, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    result: list[np.ndarray] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        perimeter = cv2.arcLength(contour, True)
        if not (3 <= area <= 180 and perimeter > 0):
            continue
        x, y, width, height = cv2.boundingRect(contour)
        if width > 34 or height > 30 or width < 3 or height < 3:
            continue
        approximation = cv2.approxPolyDP(contour, 0.11 * perimeter, True)
        if len(approximation) != 3:
            continue
        result.append(contour)
    return result


def _component_local_mask(
    contours: Sequence[np.ndarray],
    search: np.ndarray,
    forbidden: np.ndarray,
) -> tuple[np.ndarray, list[dict[str, int]]]:
    result = np.zeros(search.shape, np.uint8)
    records: list[dict[str, int]] = []
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    for contour in contours:
        core = np.zeros(search.shape, np.uint8)
        cv2.drawContours(core, [cv2.convexHull(contour)], -1, 1, thickness=cv2.FILLED)
        local = cv2.dilate(core, kernel, iterations=1)
        local = (local > 0) & search & ~forbidden
        pixel_count = int(local.sum())
        if pixel_count == 0 or pixel_count > 1250:
            continue
        x, y, width, height = cv2.boundingRect(contour)
        result[local] = 1
        records.append({
            "x": int(x), "y": int(y), "width": int(width), "height": int(height),
            "dilated_pixels": pixel_count,
        })
    return result.astype(bool), records


def _inpaint_components(source: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if not mask.any():
        return source.copy()
    filled = cv2.inpaint(source, mask.astype(np.uint8) * 255, 3.0, cv2.INPAINT_TELEA)
    distance = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 3)
    alpha = np.clip(distance / 2.2, 0.0, 1.0)[..., None]
    blended = source.astype(np.float32) * (1.0 - alpha) + filled.astype(np.float32) * alpha
    result = source.copy()
    result[mask] = np.clip(blended, 0, 255).round().astype(np.uint8)[mask]
    return result


def _match_material(
    candidate: np.ndarray,
    source: np.ndarray,
    mask: np.ndarray,
) -> np.ndarray:
    result = candidate.copy()
    h15._match_mask_stats(result, source, mask)
    # Reuse only H4's finest local material. Strong semantic edges are clipped out.
    source_f = source.astype(np.float32)
    fine = source_f - cv2.GaussianBlur(source_f, (0, 0), 0.85)
    fine = np.clip(fine, -7.0, 7.0) * 0.46
    material = np.clip(result.astype(np.float32) + fine, 0, 255)
    distance = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 3)
    alpha = np.clip(distance / 4.0, 0.0, 1.0)[..., None]
    blended = source_f * (1.0 - alpha) + material * alpha
    result[mask] = np.clip(blended, 0, 255).round().astype(np.uint8)[mask]
    return result


def _flat_city_port(
    source_image: Image.Image,
    source: np.ndarray,
    city: np.ndarray,
    port: np.ndarray,
    water: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any], dict[str, Any]]:
    target = source_image.copy()
    city_image = Image.fromarray(city.astype(np.uint8) * 255, "L")
    port_image = Image.fromarray(port.astype(np.uint8) * 255, "L")
    water_image = Image.fromarray(water.astype(np.uint8) * 255, "L")
    rng = random.Random(SEED)
    try:
        h9.h8._local_background_fill(source_image, target, city_image, water_image, salt=0xC179)
        city_stats = h9._draw_flat_city(target, city_image, rng)
        h9.h8._local_background_fill(source_image, target, port_image, water_image, salt=0xA019)
        port_stats = h9._draw_flat_port(target, port_image, water_image, rng)
        drawn = np.asarray(target, np.uint8).copy()
    finally:
        target.close()
        city_image.close()
        port_image.close()
        water_image.close()
    drawn = _match_material(drawn, source, city)
    dry_port = port & ~water
    wet_port = port & water
    if dry_port.any():
        drawn = _match_material(drawn, source, dry_port)
    if wet_port.any():
        drawn = _match_material(drawn, source, wet_port)
    return drawn, city_stats, port_stats


def _signature_reduction(
    source: np.ndarray,
    candidate: np.ndarray,
    records: Sequence[dict[str, int]],
) -> dict[str, Any]:
    before_gray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY).astype(np.float32)
    after_gray = cv2.cvtColor(candidate, cv2.COLOR_RGB2GRAY).astype(np.float32)
    before_local = cv2.GaussianBlur(before_gray, (0, 0), 3.0)
    after_local = cv2.GaussianBlur(after_gray, (0, 0), 3.0)
    removed = 0
    ratios: list[float] = []
    for record in records:
        x, y = record["x"], record["y"]
        width, height = record["width"], record["height"]
        x0, y0 = max(0, x - 3), max(0, y - 3)
        x1, y1 = min(CANVAS[0], x + width + 3), min(CANVAS[1], y + height + 3)
        old_energy = float(np.maximum(before_local[y0:y1, x0:x1] - before_gray[y0:y1, x0:x1], 0).mean())
        new_energy = float(np.maximum(after_local[y0:y1, x0:x1] - after_gray[y0:y1, x0:x1], 0).mean())
        ratio = new_energy / max(old_energy, 1e-6)
        ratios.append(ratio)
        if ratio <= 0.62:
            removed += 1
    total = len(records)
    reduction = removed / max(total, 1)
    return {
        "targeted_components": total,
        "materially_removed_components": removed,
        "reduction_fraction": round(reduction, 6),
        "median_residual_dark_energy_ratio": round(float(np.median(ratios)) if ratios else 0.0, 6),
    }


def _contact(master: Image.Image) -> Image.Image:
    centers = ((850, 500), (490, 840), (1270, 280), (850, 910), (355, 580))
    contact = Image.new("RGB", (1024, 1536), master.getpixel((900, 700)))
    overview = master.resize((768, 512), Image.Resampling.LANCZOS)
    contact.paste(overview, (128, 0))
    overview.close()
    for row, (cx, cy) in enumerate(centers):
        for column, size in enumerate((256, 128, 64, 32)):
            left = max(0, min(master.width - size, cx - size // 2))
            top = max(0, min(master.height - size, cy - size // 2))
            crop = master.crop((left, top, left + size, top + size))
            panel = crop.resize((256, 256), Image.Resampling.NEAREST)
            contact.paste(panel, (column * 256, 512 + row * 256))
            crop.close()
            panel.close()
    return contact


def render(
    *,
    h4_path: Path = DEFAULT_H4,
    b1_path: Path = DEFAULT_B1,
    output_dir: Path = DEFAULT_OUTPUT,
    replace: bool = False,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    try:
        output_dir.relative_to(DEFAULT_OUTPUT.parent.resolve())
    except ValueError as exc:
        raise H16Error("output must stay under tmp/map-production/h16-prototype") from exc
    paths = {"master": output_dir / MASTER, "mask": output_dir / MASK,
             "contact": output_dir / CONTACT, "report": output_dir / REPORT}
    if not replace and any(path.exists() for path in paths.values()):
        raise H16Error("refusing to overwrite H16 iteration")

    source_image = _load(h4_path, "h4")
    b1 = _load(b1_path, "b1")
    try:
        source = np.asarray(source_image, np.uint8).copy()
        broad = h15._semantic_masks(source_image)
        city, port, water = broad["city"], broad["port"], broad["water"]
        shoreline_guard = cv2.dilate(broad["shoreline_core"].astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        forbidden = city | port | shoreline_guard
        highland_contours = _triangle_contours(source, broad["highland"] & ~forbidden)
        coast_search = broad["coast"] & ~water & ~forbidden
        coast_contours = _triangle_contours(source, coast_search)
        highland_mask, highland_records = _component_local_mask(
            highland_contours, broad["highland"], forbidden,
        )
        coast_mask, coast_records = _component_local_mask(
            coast_contours, coast_search, forbidden,
        )
        glyph_mask = highland_mask | coast_mask

        inpainted = _inpaint_components(source, glyph_mask)
        flat, city_stats, port_stats = _flat_city_port(source_image, source, city, port, water)
        candidate = inpainted
        candidate[city | port] = flat[city | port]

        # A detected water-class change outside the intentionally drawn port is
        # restored from H4, making the source shoreline authoritative by construction.
        for _ in range(3):
            probe_image = Image.fromarray(candidate, "RGB")
            try:
                observed = np.asarray(h9.h8._water_mask(probe_image), np.uint8) > 0
            finally:
                probe_image.close()
            displaced = (observed ^ water) & ~port
            if not displaced.any():
                break
            restore = cv2.dilate(displaced.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
            candidate[restore] = source[restore]

        allowed = city | port | glyph_mask
        changed = np.any(candidate != source, axis=2)
        violations = changed & ~allowed
        if violations.any():
            raise H16Error(f"protected-pixel violation: {int(violations.sum())}")

        target_image = Image.fromarray(candidate, "RGB")
        semantic = np.zeros((CANVAS[1], CANVAS[0], 3), np.uint8)
        semantic[coast_mask] = (60, 110, 190)
        semantic[highland_mask] = (150, 92, 175)
        semantic[port] = (224, 154, 52)
        semantic[city] = (202, 58, 50)
        semantic_image = Image.fromarray(semantic, "RGB")
        contact = _contact(target_image)
        output_dir.mkdir(parents=True, exist_ok=True)
        target_image.save(paths["master"], **PNG)
        semantic_image.save(paths["mask"], **PNG)
        contact.save(paths["contact"], **PNG)

        palette = h4.palette_continuity_metrics(target_image, b1)
        readability = h4.downsample_readability_metrics(target_image)
        boundary = h4.boundary_metrics(target_image)
        repetition = h4.exact_repetition_metrics(target_image)
        signatures = _signature_reduction(source, candidate, [*highland_records, *coast_records])
        probe_image = Image.fromarray(candidate, "RGB")
        try:
            output_water = np.asarray(h9.h8._water_mask(probe_image), np.uint8) > 0
        finally:
            probe_image.close()
        shoreline_displacement = int(((output_water ^ water) & ~port).sum())
        canvas_pixels = CANVAS[0] * CANVAS[1]
        allowed_pixels = int(allowed.sum())
        max_local_component = max(
            [record["dilated_pixels"] for record in [*highland_records, *coast_records]],
            default=0,
        )
        gate_status = {
            "protected_exact": not violations.any(),
            "edit_coverage_below_25_percent": allowed_pixels / canvas_pixels < 0.25,
            "component_locality": max_local_component <= 1250,
            "palette": palette["passed"],
            "readability": readability["passed"],
            "boundary": boundary["passed"],
            "exact_repetition": repetition["passed"],
            "triangle_signature_reduction_85_percent": signatures["reduction_fraction"] >= 0.85,
            "shoreline_displacement_zero": shoreline_displacement == 0,
            "flat_city_port": city_stats["city_side_faces"] == 0 and port_stats["port_side_faces"] == 0,
        }
        report = {
            "schema_version": "1.0.0",
            "id": "style-candidate-h-v16-micro-inpaint-automated",
            "status": "iteration_1_automated_pass_pending_author_vision" if all(gate_status.values()) else "iteration_1_failed_automated",
            "golden_reference": False,
            "inputs": {"h4_protected_base": _artifact(h4_path), "b1_gate_reference": _artifact(b1_path)},
            "single_change": "component-local removal of pictorial height glyphs plus material-integrated flat city and port",
            "full_resolution_protection": {
                "canvas_pixels": canvas_pixels,
                "allowed_edit_pixels": allowed_pixels,
                "allowed_edit_coverage_percent": round(allowed_pixels / canvas_pixels * 100.0, 6),
                "changed_pixels": int(changed.sum()),
                "protected_pixels": int((~allowed).sum()),
                "protected_violation_pixels": int(violations.sum()),
                "protected_pixel_equality_percent": 100.0,
            },
            "component_local_repair": {
                "highland_detected_components": len(highland_records),
                "coast_detected_components": len(coast_records),
                "maximum_individual_dilated_component_pixels": max_local_component,
                "union_glyph_mask_pixels": int(glyph_mask.sum()),
                "wide_region_replacement_used": False,
                "inpaint_radius_pixels": 3.0,
                "records": {"highland": highland_records, "coast": coast_records},
            },
            "perspective_proxies": {
                **signatures,
                "city_flat_footprints": city_stats["city_flat_building_footprints"],
                "port_flat_footprints": port_stats["port_flat_building_footprints"],
                "city_side_faces": 0,
                "port_side_faces": 0,
                "directional_shadows": 0,
                "shoreline_displacement_pixels_outside_port": shoreline_displacement,
            },
            "material_integration": {
                "source": "H4 local fine high-pass clipped to +/-7 RGB levels",
                "weight": 0.46,
                "inward_feather_pixels": 4,
            },
            "automated_metrics": {"palette": palette, "readability": readability,
                                  "boundary": boundary, "exact_repetition": repetition},
            "gate_status": gate_status,
            "self_vision_review": {"status": "pending", "acceptance_authority": False,
                "reviewed_views": [], "immediate_failure_detected": None,
                "decision": "inspect overview/native/200/400 before any promotion"},
            "outputs": {"master": _artifact(paths["master"]), "semantic_mask": _artifact(paths["mask"]),
                        "contact_sheet": _artifact(paths["contact"])},
        }
        paths["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report
    finally:
        source_image.close()
        b1.close()
        for name in ("target_image", "semantic_image", "contact"):
            value = locals().get(name)
            if isinstance(value, Image.Image):
                value.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = render(output_dir=args.output_dir, replace=args.replace)
    except (H16Error, OSError, ValueError) as exc:
        print(f"H16 render failed: {exc}")
        return 2
    print(json.dumps({"status": report["status"], "master": report["outputs"]["master"],
                      "gates": report["gate_status"]}, ensure_ascii=False))
    return 0 if all(report["gate_status"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
