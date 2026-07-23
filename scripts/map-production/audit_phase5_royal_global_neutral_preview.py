#!/usr/bin/env python3
"""Build non-authoritative QA for the Royal global-neutral preview."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from PIL import Image

import audit_phase5_royal_full_material_preview as shared
import audit_style_candidate_h4 as h4
import render_phase5_reviewed_master as renderer


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "tmp"
    / "map-production"
    / "phase5-reviewed-v2"
    / "royal-global-neutral-bandpass-preview-v1"
)
ROYAL_SHEET_ID = "sheet_region_royal_capital_region"
H4 = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "candidates"
    / "style-candidate-h-v4-plan-view-golden-board.png"
)
PEAK_RSS_LIMIT_BYTES = 512 * 1024 * 1024


class GlobalNeutralAuditError(ValueError):
    """Raised when preview evidence is missing or contradicts the contract."""


def _readability_scale(
    readability: dict[str, Any],
    scale: float,
) -> dict[str, Any]:
    return next(
        record
        for record in readability["scales"]
        if float(record["scale"]) == scale
    )


def build_report(
    output_dir: Path,
    peak_rss_bytes: int,
    *,
    replace: bool,
) -> dict[str, Any]:
    master_path = output_dir / f"{ROYAL_SHEET_ID}.png"
    renderer_report_path = output_dir / f"{ROYAL_SHEET_ID}.report.json"
    if not master_path.is_file() or not renderer_report_path.is_file():
        raise GlobalNeutralAuditError("Royal master or renderer report is missing")
    renderer_report = json.loads(renderer_report_path.read_text(encoding="utf-8"))
    stats = renderer_report.get("render_stats", {})
    if renderer_report.get("status") != "preview-only":
        raise GlobalNeutralAuditError("global neutral output is not preview-only")
    if renderer_report.get("promotion_eligible") is not False:
        raise GlobalNeutralAuditError("global neutral output is promotion eligible")
    if (
        stats.get("material_transfer_mode")
        != renderer.GLOBAL_NEUTRAL_BANDPASS_MODE
    ):
        raise GlobalNeutralAuditError("renderer used the wrong material mode")

    sources, contract, sheet, _ = renderer.load_render_context(
        sheet_id=ROYAL_SHEET_ID
    )
    transform = renderer.SheetCanvasTransform(contract, sheet)
    with Image.open(master_path) as opened:
        master = opened.convert("RGB")
    with Image.open(H4) as opened:
        h4_image = opened.convert("RGB")
    contacts = shared.build_contacts(
        master,
        transform,
        output_dir,
        replace=replace,
    )

    controls = renderer_report["inputs"]["canonical_sheet_qa_controls"]
    land_observed = output_dir / f"{ROYAL_SHEET_ID}.observed-land-sea-mask.png"
    transport_observed = (
        output_dir / f"{ROYAL_SHEET_ID}.observed-transport-mask.png"
    )
    canonical_masks = {
        "land_sea": shared._mask_comparison(
            land_observed,
            REPO_ROOT / controls["land_sea_control"]["path"],
        ),
        "transport": shared._mask_comparison(
            transport_observed,
            REPO_ROOT / controls["transport_control"]["path"],
        ),
    }

    land_mask, ocean_mask = renderer._build_land_masks(sources, transform)
    try:
        autocorrelation = {
            "canonical_land": shared.semantic_far_patch_autocorrelation(
                master,
                land_mask,
                "canonical_land",
            ),
            "canonical_water": shared.semantic_far_patch_autocorrelation(
                master,
                ocean_mask,
                "canonical_water",
            ),
        }
    finally:
        land_mask.close()
        ocean_mask.close()

    exact_repetition = h4.exact_repetition_metrics(master)
    readability = h4.downsample_readability_metrics(master)
    readability_25 = _readability_scale(readability, 0.25)
    palette = h4.palette_continuity_metrics(master, h4_image)
    palette["reference"] = "H4 preview-only Golden proxy"
    boundary = h4.boundary_metrics(master)
    source_record = renderer_report["inputs"]["global_neutral_material"]
    bandpass = stats["global_neutral_bandpass"]
    semantic_contrast = float(
        stats["global_neutral_semantic_boundary_contrast_luma_levels"]
    )
    autocorrelation_passed = all(
        record["passed"] for record in autocorrelation.values()
    )
    gates = {
        "renderer_preview_only": renderer_report["status"] == "preview-only",
        "promotion_ineligible": renderer_report["promotion_eligible"] is False,
        "rejected_source_hash_locked": (
            source_record["sha256"]
            == renderer.GLOBAL_NEUTRAL_MATERIAL_SHA256
            and source_record["source_review_status"] == "rejected"
        ),
        "no_semantic_material_masks": (
            int(stats["global_neutral_semantic_usage_masks_accepted"]) == 0
        ),
        "no_region_washes": int(stats["global_neutral_region_washes_used"]) == 0,
        "source_zero_mean_and_band_limited": (
            bandpass["zero_mean_passed"]
            and bandpass["band_limited_by_construction"]
            and not bandpass["source_rgb_or_colour_transferred"]
            and not bandpass["source_broad_tone_transferred"]
        ),
        "land_mean_at_most_0_25_luma": (
            abs(float(stats["global_neutral_land_signed_mean_luma_levels"]))
            <= 0.25
        ),
        "canonical_water_pixels_unchanged_by_material": (
            int(stats["global_neutral_water_pixel_changes"]) == 0
        ),
        "canonical_line_guard_pixels_unchanged_by_material": (
            int(stats["global_neutral_line_guard_pixel_changes"]) == 0
        ),
        "canonical_clip_never_escaped": (
            int(stats["global_neutral_outside_canonical_clip_changes"]) == 0
        ),
        "royal_quilt_window_cap": (
            int(stats["global_neutral_quilt_windows"])
            <= int(stats["global_neutral_maximum_royal_windows"])
        ),
        "semantic_boundary_contrast_at_most_0_75": (
            semantic_contrast <= renderer.SEMANTIC_BOUNDARY_CONTRAST_LIMIT
        ),
        "canonical_land_sea_exact": canonical_masks["land_sea"]["passed"],
        "canonical_transport_exact": canonical_masks["transport"]["passed"],
        "far_patch_autocorrelation_proxy": autocorrelation_passed,
        "large_exact_clone_proxy": exact_repetition["passed"],
        "readability_proxy": readability["passed"],
        "twenty_five_percent_macro_coverage_at_least_0_85": (
            float(readability_25["macrocell_contrast_coverage"]) >= 0.85
        ),
        "h4_palette_proxy": palette["passed"],
        "boundary_proxy": boundary["passed"],
        "peak_rss_at_most_512_mib": (
            0 < peak_rss_bytes <= PEAK_RSS_LIMIT_BYTES
        ),
    }
    failed = [name for name, passed in gates.items() if not passed]
    report = {
        "schema_version": "1.0.0",
        "id": "royal-global-neutral-bandpass-preview-v1-automated-qa",
        "status": "passed-proxies" if not failed else "failed-proxies",
        "acceptance_authority": False,
        "scope": (
            "Royal-only promotion-ineligible preview; automated evidence cannot "
            "accept or promote Phase 5"
        ),
        "master": shared._image_record(master_path),
        "renderer_report": {
            "path": shared._repo_path(renderer_report_path),
            "sha256": shared._sha256(renderer_report_path),
            "status": renderer_report["status"],
            "promotion_eligible": renderer_report["promotion_eligible"],
            "material_transfer_mode": stats["material_transfer_mode"],
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
        },
        "material_contract": {
            "source": source_record,
            "bandpass": bandpass,
            "broad_noise": stats["global_neutral_broad_noise"],
            "world_recenter": stats["global_neutral_world_recenter"],
            "semantic_usage_masks_accepted": stats[
                "global_neutral_semantic_usage_masks_accepted"
            ],
            "region_washes_used": stats["global_neutral_region_washes_used"],
            "quilt_windows": stats["global_neutral_quilt_windows"],
            "maximum_royal_windows": stats[
                "global_neutral_maximum_royal_windows"
            ],
            "land_signed_mean_luma_levels": stats[
                "global_neutral_land_signed_mean_luma_levels"
            ],
            "water_pixel_changes": stats["global_neutral_water_pixel_changes"],
            "line_guard_pixel_changes": stats[
                "global_neutral_line_guard_pixel_changes"
            ],
            "outside_canonical_clip_changes": stats[
                "global_neutral_outside_canonical_clip_changes"
            ],
            "semantic_boundary_contrast_luma_levels": semantic_contrast,
            "semantic_boundary_contrast_limit_luma_levels": (
                renderer.SEMANTIC_BOUNDARY_CONTRAST_LIMIT
            ),
        },
        "far_patch_autocorrelation": autocorrelation,
        "exact_repetition": exact_repetition,
        "readability_proxy": readability,
        "palette_proxy_against_h4": palette,
        "boundary_proxy": boundary,
        "automated_gates": gates,
        "failed_gates": failed,
        "vision_required": True,
        "vision_immediate_reject_signals": [
            "swirly or pseudo-writing fine marks",
            "visible patch seams",
            "giant forest, rock, wetland, or agricultural material polygons",
            "uniform scratch wallpaper",
            "palette drift",
        ],
    }
    report_path = (
        output_dir
        / "royal-global-neutral-bandpass-preview-v1.automated-preview-qa.json"
    )
    shared._atomic_write_json(report, report_path, replace=replace)
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
        print(f"Royal global-neutral preview audit failed: {exc}")
        return 1
    print(
        "Royal global-neutral preview audited: "
        f"status={report['status']} sha256={report['master']['sha256']}"
    )
    return 0 if report["status"] == "passed-proxies" else 1


if __name__ == "__main__":
    raise SystemExit(main())
