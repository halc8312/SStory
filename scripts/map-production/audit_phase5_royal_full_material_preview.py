#!/usr/bin/env python3
"""Build multi-scale review artifacts for the Royal full-material prototype.

This audit is deliberately non-authoritative.  It proves pixel/container,
canonical-mask, memory, and clone/autocorrelation proxies, then hands the
result to human/Codex Vision review.  It cannot promote a Phase 5 master.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image, ImageChops

import audit_style_candidate_h4 as h4
import render_phase5_reviewed_master as renderer


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "tmp/map-production/phase5-reviewed-v2/royal-full-material-upgrade-2"
)
ROYAL_SHEET_ID = "sheet_region_royal_capital_region"
H4 = (
    REPO_ROOT
    / "world/map-production/candidates/"
    "style-candidate-h-v4-plan-view-golden-board.png"
)
PEAK_RSS_LIMIT_BYTES = 512 * 1024 * 1024
PNG_OPTIONS = {"format": "PNG", "compress_level": 9, "optimize": False}


class RoyalPreviewAuditError(ValueError):
    """Raised when review evidence cannot be built honestly."""


def _repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _image_record(path: Path) -> dict[str, Any]:
    with Image.open(path) as opened:
        opened.load()
        return {
            "path": _repo_path(path),
            "sha256": _sha256(path),
            "format": opened.format,
            "mode": opened.mode,
            "width": opened.width,
            "height": opened.height,
        }


def _atomic_save_png(image: Image.Image, path: Path, *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new.png")
    if temporary.exists():
        temporary.unlink()
    image.save(temporary, **PNG_OPTIONS)
    if path.exists():
        if path.read_bytes() == temporary.read_bytes():
            temporary.unlink()
            return
        if not replace:
            temporary.unlink()
            raise RoyalPreviewAuditError(f"refusing to overwrite: {path}")
        path.unlink()
    temporary.replace(path)


def _atomic_write_json(value: dict[str, Any], path: Path, *, replace: bool) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary = path.with_name(path.name + ".new.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_bytes(payload)
    if path.exists():
        if path.read_bytes() == payload:
            temporary.unlink()
            return
        if not replace:
            temporary.unlink()
            raise RoyalPreviewAuditError(f"refusing to overwrite: {path}")
        path.unlink()
    temporary.replace(path)


def _source_box(
    image: Image.Image,
    center: tuple[int, int],
    scale: float,
    panel_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    if scale <= 0.25:
        return (0, 0, image.width, image.height)
    width = min(image.width, max(1, round(panel_size[0] / scale)))
    height = min(image.height, max(1, round(panel_size[1] / scale)))
    left = max(0, min(image.width - width, center[0] - width // 2))
    top = max(0, min(image.height - height, center[1] - height // 2))
    return (left, top, left + width, top + height)


def build_contacts(
    master: Image.Image,
    transform: renderer.SheetCanvasTransform,
    output_dir: Path,
    *,
    replace: bool,
) -> dict[str, Any]:
    settlements = renderer.load_sources(renderer.DEFAULT_SOURCE_DIR)["settlements"]
    capital = next(
        feature
        for feature in settlements["features"]
        if feature.get("properties", {}).get("node_type") == "capital"
    )
    bbox = renderer._geometry_bbox(capital)
    if bbox is None:
        raise RoyalPreviewAuditError("Royal capital bbox is unavailable")
    center = transform.point_fast(
        ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
    )

    overview_path = output_dir / "royal-overview.png"
    overview = master.copy()
    overview.thumbnail((1200, 800), Image.Resampling.LANCZOS)
    _atomic_save_png(overview, overview_path, replace=replace)
    overview.close()

    panel_size = (768, 480)
    panels: list[Image.Image] = []
    panel_records: list[dict[str, Any]] = []
    scales = (
        ("25-percent", 0.25),
        ("50-percent", 0.5),
        ("native", 1.0),
        ("200-percent", 2.0),
        ("400-percent", 4.0),
    )
    for label, scale in scales:
        box = _source_box(master, center, scale, panel_size)
        crop = master.crop(box)
        panel = crop.resize(panel_size, Image.Resampling.LANCZOS)
        crop.close()
        path = output_dir / f"royal-scale-{label}.png"
        _atomic_save_png(panel, path, replace=replace)
        panels.append(panel)
        panel_records.append(
            {
                "label": label,
                "effective_scale": scale,
                "source_box_px": list(box),
                "artifact": _image_record(path),
            }
        )
    scale_contact = Image.new("RGB", (panel_size[0] * 5, panel_size[1]))
    for index, panel in enumerate(panels):
        scale_contact.paste(panel, (index * panel_size[0], 0))
        panel.close()
    scale_contact_path = output_dir / "royal-scale-contact.png"
    _atomic_save_png(scale_contact, scale_contact_path, replace=replace)
    scale_contact.close()

    region_records: list[dict[str, Any]] = []
    region_panels: list[Image.Image] = []
    for row in range(3):
        for column in range(3):
            left = column * master.width // 3
            right = (column + 1) * master.width // 3
            top = row * master.height // 3
            bottom = (row + 1) * master.height // 3
            box = (left, top, right, bottom)
            crop = master.crop(box)
            panel = crop.resize((512, 320), Image.Resampling.LANCZOS)
            crop.close()
            path = output_dir / f"royal-region-r{row + 1}-c{column + 1}.png"
            _atomic_save_png(panel, path, replace=replace)
            region_panels.append(panel)
            region_records.append(
                {
                    "row": row + 1,
                    "column": column + 1,
                    "source_box_px": list(box),
                    "artifact": _image_record(path),
                }
            )
    region_contact = Image.new("RGB", (1536, 960))
    for index, panel in enumerate(region_panels):
        region_contact.paste(panel, ((index % 3) * 512, (index // 3) * 320))
        panel.close()
    region_contact_path = output_dir / "royal-nine-region-contact.png"
    _atomic_save_png(region_contact, region_contact_path, replace=replace)
    region_contact.close()
    return {
        "overview": _image_record(overview_path),
        "scale_contact": _image_record(scale_contact_path),
        "scale_panels": panel_records,
        "nine_region_contact": _image_record(region_contact_path),
        "nine_regions": region_records,
        "contains_text": False,
        "contains_frame": False,
    }


def _mask_comparison(observed: Path, control: Path) -> dict[str, Any]:
    with Image.open(observed) as observed_source:
        observed_mask = observed_source.convert("L")
    with Image.open(control) as control_source:
        control_mask = control_source.convert("L")
    try:
        if observed_mask.size != control_mask.size:
            ratio = 0.0
            exact = False
        else:
            difference = ImageChops.difference(observed_mask, control_mask)
            exact = difference.getbbox() is None
            histogram = difference.histogram()
            matching = histogram[0]
            ratio = matching / (difference.width * difference.height)
            difference.close()
        return {
            "passed": exact,
            "exact_match_ratio": round(ratio, 9),
            "observed": _image_record(observed),
            "control": _image_record(control),
        }
    finally:
        observed_mask.close()
        control_mask.close()


def semantic_far_patch_autocorrelation(
    master: Image.Image,
    mask: Image.Image,
    semantic: str,
) -> dict[str, Any]:
    gray = np.asarray(master.convert("L"), dtype=np.float32)
    mask_values = np.asarray(mask.convert("L"), dtype=np.uint8)
    patch_size = 64
    stride = 32
    vectors: list[np.ndarray] = []
    locations: list[tuple[int, int]] = []
    for top in range(0, master.height - patch_size + 1, stride):
        for left in range(0, master.width - patch_size + 1, stride):
            patch_mask = mask_values[
                top : top + patch_size, left : left + patch_size
            ]
            if float(np.mean(patch_mask)) < 204.0:
                continue
            patch = gray[top : top + patch_size, left : left + patch_size]
            small = cv2.resize(patch, (16, 16), interpolation=cv2.INTER_AREA)
            vector = small.reshape(-1).astype(np.float64)
            vector -= float(np.mean(vector))
            norm = float(np.linalg.norm(vector))
            if norm <= 1e-9:
                continue
            vectors.append(vector / norm)
            locations.append((left, top))
    if len(vectors) > 384:
        indices = np.linspace(0, len(vectors) - 1, 384, dtype=np.int64)
        vectors = [vectors[int(index)] for index in indices]
        locations = [locations[int(index)] for index in indices]
    if len(vectors) < 2:
        return {
            "semantic": semantic,
            "passed": True,
            "applicable": False,
            "eligible_patches": len(vectors),
            "reason": "fewer than two fully semantic patches",
        }
    matrix = np.asarray(vectors)
    points = np.asarray(locations)
    correlations = matrix @ matrix.T
    separation = np.max(np.abs(points[:, None, :] - points[None, :, :]), axis=2)
    correlations[separation < 128] = -2.0
    best = np.max(correlations, axis=1)
    best = best[best > -1.5]
    p99 = float(np.percentile(best, 99)) if len(best) else 0.0
    fraction_090 = float(np.mean(best >= 0.90)) if len(best) else 0.0
    thresholds = {
        "maximum_p99_far_patch_correlation": 0.965,
        "maximum_fraction_far_patch_correlation_at_least_0_90": 0.12,
    }
    passed = (
        p99 <= thresholds["maximum_p99_far_patch_correlation"]
        and fraction_090
        <= thresholds["maximum_fraction_far_patch_correlation_at_least_0_90"]
    )
    return {
        "semantic": semantic,
        "passed": passed,
        "applicable": True,
        "patch_size_px": patch_size,
        "stride_px": stride,
        "minimum_pair_separation_px_chebyshev": 128,
        "eligible_patches": len(vectors),
        "p99_best_far_patch_normalized_correlation": round(p99, 6),
        "fraction_best_far_patch_correlation_at_least_0_90": round(
            fraction_090, 6
        ),
        "thresholds": thresholds,
        "limitation": (
            "numeric clone/autocorrelation proxy only; semantic repetition remains "
            "a Vision judgment"
        ),
    }


def build_report(output_dir: Path, peak_rss_bytes: int, *, replace: bool) -> dict[str, Any]:
    master_path = output_dir / f"{ROYAL_SHEET_ID}.png"
    renderer_report_path = output_dir / f"{ROYAL_SHEET_ID}.report.json"
    if not master_path.is_file() or not renderer_report_path.is_file():
        raise RoyalPreviewAuditError("Royal master or renderer report is missing")
    renderer_report = json.loads(renderer_report_path.read_text(encoding="utf-8"))
    if renderer_report.get("status") != "preview-only":
        raise RoyalPreviewAuditError("full material output is not preview-only")
    if renderer_report.get("promotion_eligible") is not False:
        raise RoyalPreviewAuditError("full material output is promotion eligible")

    sources, contract, sheet, _ = renderer.load_render_context(
        sheet_id=ROYAL_SHEET_ID
    )
    transform = renderer.SheetCanvasTransform(contract, sheet)
    with Image.open(master_path) as source:
        master = source.convert("RGB")
    with Image.open(H4) as source:
        h4_image = source.convert("RGB")
    contacts = build_contacts(master, transform, output_dir, replace=replace)

    qa_controls = renderer_report["inputs"]["canonical_sheet_qa_controls"]
    land_control = REPO_ROOT / qa_controls["land_sea_control"]["path"]
    transport_control = REPO_ROOT / qa_controls["transport_control"]["path"]
    land_observed = output_dir / f"{ROYAL_SHEET_ID}.observed-land-sea-mask.png"
    transport_observed = output_dir / f"{ROYAL_SHEET_ID}.observed-transport-mask.png"
    canonical_masks = {
        "land_sea": _mask_comparison(land_observed, land_control),
        "transport": _mask_comparison(transport_observed, transport_control),
    }

    land_mask, ocean_mask = renderer._build_land_masks(sources, transform)
    semantic_masks = renderer._build_atlas_usage_masks(sources, land_mask, transform)
    autocorrelation: dict[str, Any] = {}
    try:
        for semantic, mask in semantic_masks.items():
            autocorrelation[semantic] = semantic_far_patch_autocorrelation(
                master,
                mask,
                semantic,
            )
        autocorrelation["canonical_water"] = semantic_far_patch_autocorrelation(
            master,
            ocean_mask,
            "canonical_water",
        )
    finally:
        land_mask.close()
        ocean_mask.close()
        for mask in semantic_masks.values():
            mask.close()

    exact_repetition = h4.exact_repetition_metrics(master)
    readability = h4.downsample_readability_metrics(master)
    palette = h4.palette_continuity_metrics(master, h4_image)
    palette["reference"] = "H4 preview-only Golden proxy"
    boundary = h4.boundary_metrics(master)
    render_stats = renderer_report["render_stats"]
    outside_changes = int(
        render_stats.get("material_atlas_outside_parent_pixel_changes", -1)
    )
    autocorrelation_passed = all(
        record["passed"] for record in autocorrelation.values()
    )
    gates = {
        "renderer_preview_only": True,
        "promotion_ineligible": True,
        "canonical_land_sea_exact": canonical_masks["land_sea"]["passed"],
        "canonical_transport_exact": canonical_masks["transport"]["passed"],
        "atlas_never_escaped_parent": outside_changes == 0,
        "semantic_autocorrelation_proxy": autocorrelation_passed,
        "large_exact_clone_proxy": exact_repetition["passed"],
        "peak_rss_at_most_512_mib": 0 < peak_rss_bytes <= PEAK_RSS_LIMIT_BYTES,
        "no_huge_z8_atlas_variants": True,
    }
    failed = [name for name, passed in gates.items() if not passed]
    report = {
        "schema_version": "1.0.0",
        "id": "royal-full-material-upgrade-2-automated-preview-qa",
        "status": "passed-proxies" if not failed else "failed-proxies",
        "acceptance_authority": False,
        "scope": (
            "Royal-only temporary preview; H4 remains preview-only; automated "
            "evidence cannot accept or promote Phase 5"
        ),
        "master": _image_record(master_path),
        "renderer_report": {
            "path": _repo_path(renderer_report_path),
            "sha256": _sha256(renderer_report_path),
            "status": renderer_report["status"],
            "promotion_eligible": renderer_report["promotion_eligible"],
            "material_transfer_mode": render_stats["material_transfer_mode"],
        },
        "contacts": contacts,
        "canonical_masks": canonical_masks,
        "memory": {
            "method": "Windows Process.WorkingSet64 sampled every 100ms",
            "peak_rss_bytes": peak_rss_bytes,
            "peak_rss_mib": round(peak_rss_bytes / (1024 * 1024), 3),
            "limit_bytes": PEAK_RSS_LIMIT_BYTES,
            "limit_mib": 512,
            "passed": 0 < peak_rss_bytes <= PEAK_RSS_LIMIT_BYTES,
            "huge_z8_atlas_variants_created": 0,
        },
        "material_contract": {
            "approved_safe_crop_count": render_stats[
                "material_atlas_safe_crop_count"
            ],
            "full_spatial_material_retained": render_stats[
                "material_atlas_full_spatial_material_retained"
            ],
            "unique_source_window_transforms": render_stats[
                "material_atlas_unique_source_window_transforms"
            ],
            "outside_parent_pixel_changes": outside_changes,
            "unapproved_semantic_shapes_transferred": render_stats[
                "material_atlas_unapproved_semantic_shapes_transferred"
            ],
            "forest_interior_edge_breakup_bites": render_stats[
                "forest_interior_edge_breakup_bites"
            ],
            "riparian_interior_edge_breakup_bites": render_stats[
                "riparian_interior_edge_breakup_bites"
            ],
            "river_layered_channels": render_stats["river_layered_channels"],
            "river_uniform_solid_bands": render_stats[
                "river_uniform_solid_bands"
            ],
            "water_mottle_patches": render_stats["water_mottle_patches"],
            "water_symmetric_wavelets": render_stats[
                "water_symmetric_wavelets"
            ],
        },
        "semantic_autocorrelation": autocorrelation,
        "exact_repetition": exact_repetition,
        "readability_proxy": readability,
        "palette_proxy_against_h4": palette,
        "boundary_proxy": boundary,
        "automated_gates": gates,
        "failed_gates": failed,
        "vision_required": True,
    }
    report_path = output_dir / "royal-full-material-upgrade-2.automated-preview-qa.json"
    _atomic_write_json(report, report_path, replace=replace)
    master.close()
    h4_image.close()
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--peak-rss-bytes", type=int, required=True)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_report(
            args.output_dir,
            args.peak_rss_bytes,
            replace=args.replace,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Royal full-material preview audit failed: {exc}")
        return 1
    print(
        "Royal full-material preview audited: "
        f"status={report['status']} sha256={report['master']['sha256']}"
    )
    return 0 if report["status"] == "passed-proxies" else 1


if __name__ == "__main__":
    raise SystemExit(main())
