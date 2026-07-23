#!/usr/bin/env python3
"""Audit Golden candidate I1 without claiming independent Vision approval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from PIL import Image, ImageDraw, ImageFont

import audit_style_candidate_h4 as h4
import audit_style_candidate_h17 as h17


REPO_ROOT = Path(__file__).resolve().parents[2]
JOB_ID = "style-candidate-i-v1-flat-styleboard"
RAW = REPO_ROOT / f"world/map-production/candidates/{JOB_ID}-raw.png"
FINAL = REPO_ROOT / f"world/map-production/candidates/{JOB_ID}.png"
PROMPT = REPO_ROOT / f"world/map-production/prompts/{JOB_ID}.generation.txt"
RECEIPT = REPO_ROOT / f"world/map-production/prompts/{JOB_ID}.generation-receipt.json"
GUIDE = REPO_ROOT / "world/map-production/controls/style-candidate-i-v1-composition-guide.png"
GUIDE_JSON = GUIDE.with_suffix(".json")
ROYAL = REPO_ROOT / "world/map-production/candidates/phase5-royal-subtile1-x0000-y0000-raw.png"
H4 = h4.DEFAULT_FINAL
B1 = h4.DEFAULT_REFERENCE_B1
VISION_SCHEMA = h4.DEFAULT_VISION_SCHEMA
REPORT = REPO_ROOT / f"world/map-production/qa/automated/{JOB_ID}.json"
CONTACT_DIR = REPO_ROOT / "tmp/map-production/i1-review"

EXPECTED_SHA256 = {
    "raw": "bf48605572a312f0acb4aa7b950b6f9a7981b32f73e1d4df1df159789195fed1",
    "final": "bf48605572a312f0acb4aa7b950b6f9a7981b32f73e1d4df1df159789195fed1",
    "prompt": "320eee9b1d4a617d45bd82276b719023dabfe5a3a8437d8f41e92726cf57c86f",
    "receipt": "58d1145c9d6cb6cab2434c0a33d721fe923f1a8438ca3065b4bdb2b31c83c7ec",
    "guide": "52f85e45b61bf889de709d8ea9601bd5865d6021bfbc617473a9e957a6ab8bbc",
    "guide_json": "d3d58d040e880cf26164933e69cc1b0de9d032792564dbcba27985ad1fc5a2c4",
    "royal": "ec9eafe3796ec509abd11cedcf507a483f5ebe01fdc5f399d40105720aa09003",
    "h4": h4.EXPECTED_SHA256["final"],
    "b1": h4.EXPECTED_SHA256["reference_b1"],
    "vision_schema": h4.EXPECTED_SHA256["vision_schema"],
}

FOCUS_REGIONS = {
    "open-sea": (0, 100, 360, 620),
    "forest": (370, 0, 965, 365),
    "delta-and-river": (210, 260, 690, 760),
    "capital": (650, 325, 1040, 700),
    "port": (350, 735, 650, 1015),
    "highland": (965, 0, 1536, 510),
    "fields": (1040, 545, 1536, 910),
}


class I1AuditError(ValueError):
    """Raised when I1 evidence cannot be reproduced safely."""


def _assert(path: Path, digest: str, label: str) -> None:
    try:
        h4._assert_input(path, digest, label)
    except h4.H4AuditError as exc:
        raise I1AuditError(str(exc)) from exc


def _repo_path(value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or "\\" in value or ":" in value or ".." in pure.parts:
        raise I1AuditError(f"receipt path must be repo-relative: {value!r}")
    return REPO_ROOT.joinpath(*pure.parts)


def _validate_receipt() -> dict[str, Any]:
    try:
        receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise I1AuditError("I1 generation receipt is not valid UTF-8 JSON") from exc
    policy = receipt.get("generation_policy")
    if policy != {
        "calls_authorized": 1,
        "calls_performed": 1,
        "retry_performed": False,
        "tool_mode": "OpenAI ImageGen through Codex built-in image generation",
    }:
        raise I1AuditError("I1 receipt lost the one-call/no-retry policy")
    limitations = receipt.get("provenance_limitations")
    required_unknowns = {
        "exact_image_model_identifier_available": False,
        "model": "unknown",
        "model_snapshot_available": False,
        "model_snapshot": "unavailable",
        "generation_identifier_available": False,
        "generation_id": "unavailable",
        "generation_timestamp_utc": None,
    }
    if not isinstance(limitations, dict):
        raise I1AuditError("I1 receipt lacks provenance limitations")
    for key, expected in required_unknowns.items():
        if limitations.get(key) != expected:
            raise I1AuditError(f"I1 receipt must retain {key}={expected!r}")
    prompt = receipt.get("prompt")
    inputs = receipt.get("inputs")
    control = receipt.get("input_control_metadata")
    output = receipt.get("output")
    review = receipt.get("byte_identical_review_candidate")
    if not isinstance(inputs, list) or len(inputs) != 2:
        raise I1AuditError("I1 receipt must retain exactly two role-separated inputs")
    records = (
        (prompt, PROMPT, EXPECTED_SHA256["prompt"]),
        (inputs[0], GUIDE, EXPECTED_SHA256["guide"]),
        (inputs[1], ROYAL, EXPECTED_SHA256["royal"]),
        (control, GUIDE_JSON, EXPECTED_SHA256["guide_json"]),
        (output, RAW, EXPECTED_SHA256["raw"]),
        (review, FINAL, EXPECTED_SHA256["final"]),
    )
    for record, expected_path, digest in records:
        if not isinstance(record, dict):
            raise I1AuditError("I1 receipt artifact record is malformed")
        if record.get("path") != h4._relative(expected_path):
            raise I1AuditError("I1 receipt artifact path chain changed")
        if record.get("sha256") != digest:
            raise I1AuditError("I1 receipt SHA-256 chain changed")
        if not _repo_path(record["path"]).is_file():
            raise I1AuditError(f"I1 receipt artifact missing: {record['path']}")
    if output.get("accepted_as_final") is not False:
        raise I1AuditError("I1 raw output must remain unaccepted")
    if review.get("manifest_registered") is not False:
        raise I1AuditError("I1 review candidate must remain unregistered")
    if review.get("golden_accepted") is not False:
        raise I1AuditError("I1 review candidate must remain non-Golden")
    return receipt


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _panel(
    image: Image.Image,
    label: str,
    *,
    size: tuple[int, int] | None = None,
) -> Image.Image:
    rendered = image.copy()
    if size is not None:
        rendered = rendered.resize(size, Image.Resampling.LANCZOS)
    header = 38
    panel = Image.new("RGB", (rendered.width + 8, rendered.height + header + 8), (19, 21, 22))
    panel.paste(rendered, (4, header + 4))
    ImageDraw.Draw(panel).text((10, 7), label, fill=(238, 231, 208), font=_font(21))
    rendered.close()
    return panel


def _row(panels: Sequence[Image.Image], gap: int = 16) -> Image.Image:
    width = sum(panel.width for panel in panels) + gap * (len(panels) - 1)
    height = max(panel.height for panel in panels)
    row = Image.new("RGB", (width, height), (14, 16, 17))
    left = 0
    for panel in panels:
        row.paste(panel, (left, 0))
        left += panel.width + gap
    return row


def _column(rows: Sequence[Image.Image], gap: int = 16) -> Image.Image:
    width = max(row.width for row in rows)
    height = sum(row.height for row in rows) + gap * (len(rows) - 1)
    column = Image.new("RGB", (width, height), (14, 16, 17))
    top = 0
    for row in rows:
        column.paste(row, (0, top))
        top += row.height + gap
    return column


def _save(image: Image.Image, path: Path, *, replace: bool) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new.png")
    if temporary.exists():
        temporary.unlink()
    image.save(temporary, format="PNG", optimize=False)
    if path.exists():
        if h4.files_are_byte_identical(path, temporary):
            temporary.unlink()
            return h4._artifact(path)
        if not replace:
            temporary.unlink()
            raise I1AuditError(f"refusing to overwrite changed contact: {path}")
        path.unlink()
    temporary.replace(path)
    return h4._artifact(path)


def build_contacts(
    candidate: Image.Image,
    guide: Image.Image,
    royal: Image.Image,
    *,
    directory: Path,
    replace: bool,
) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}

    overview_panels = [
        _panel(guide, "Image 1: geometry-only guide", size=(768, 512)),
        _panel(royal, "Image 2: sole style/material authority", size=(768, 512)),
        _panel(candidate, "I1 candidate overview", size=(768, 512)),
    ]
    overview = _row(overview_panels)
    outputs["overview"] = _save(
        overview, directory / f"{JOB_ID}.overview-contact.png", replace=replace
    )
    overview.close()
    for panel in overview_panels:
        panel.close()

    scale_panels = [
        _panel(candidate, "I1 at 25% (384x256)", size=(384, 256)),
        _panel(candidate, "I1 at 50% (768x512)", size=(768, 512)),
        _panel(candidate, "I1 at native 100% (1536x1024)"),
    ]
    scales = _column([_row(scale_panels[:2]), scale_panels[2]])
    outputs["scales_25_50_native"] = _save(
        scales, directory / f"{JOB_ID}.25-50-native-contact.png", replace=replace
    )
    scales.close()
    for panel in scale_panels:
        panel.close()

    zoom_rows: list[Image.Image] = []
    for name, box in FOCUS_REGIONS.items():
        crop = candidate.crop(box)
        width, height = crop.size
        crop_200 = crop.crop((width // 4, height // 4, 3 * width // 4, 3 * height // 4))
        crop_400 = crop.crop((3 * width // 8, 3 * height // 8, 5 * width // 8, 5 * height // 8))
        zoom_200 = crop_200.resize((crop_200.width * 2, crop_200.height * 2), Image.Resampling.NEAREST)
        zoom_400 = crop_400.resize((crop_400.width * 4, crop_400.height * 4), Image.Resampling.NEAREST)
        panels = [
            _panel(zoom_200, f"{name}: inner crop at 200%"),
            _panel(zoom_400, f"{name}: inner crop at 400%"),
        ]
        zoom_rows.append(_row(panels))
        for item in (crop, crop_200, crop_400, zoom_200, zoom_400, *panels):
            item.close()
    zooms = _column(zoom_rows)
    outputs["zooms_200_400"] = _save(
        zooms, directory / f"{JOB_ID}.200-400-contact.png", replace=replace
    )
    zooms.close()
    for row in zoom_rows:
        row.close()

    region_rows: list[Image.Image] = []
    for row_index in range(3):
        panels: list[Image.Image] = []
        top = row_index * candidate.height // 3
        bottom = (row_index + 1) * candidate.height // 3
        for column_index in range(3):
            left = column_index * candidate.width // 3
            right = (column_index + 1) * candidate.width // 3
            crop = candidate.crop((left, top, right, bottom))
            panels.append(
                _panel(crop, f"I1 r{row_index + 1}c{column_index + 1} [{left},{top},{right},{bottom}]")
            )
            crop.close()
        region_rows.append(_row(panels))
        for panel in panels:
            panel.close()
    regions = _column(region_rows)
    outputs["nine_regions"] = _save(
        regions, directory / f"{JOB_ID}.nine-region-contact.png", replace=replace
    )
    regions.close()
    for row in region_rows:
        row.close()
    return outputs


def _image_contract(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    required = {
        "format": "PNG",
        "mode": "RGB",
        "width": h4.EXPECTED_SIZE[0],
        "height": h4.EXPECTED_SIZE[1],
        "bit_depth": 8,
        "png_color_type": 2,
        "alpha_or_transparency_present": False,
    }
    record_results = {
        name: all(record[key] == expected for key, expected in required.items())
        for name, record in records.items()
    }
    b1_profile = h4._profile_signature(records["reference_b1"])
    profile_matches = all(
        h4._profile_signature(records[name]) == b1_profile
        for name in ("raw", "final", "reference_h4", "style_royal")
    )
    return {
        "passed": all(record_results.values()) and profile_matches,
        "required": required,
        "records_passed": record_results,
        "profile_matches_b1": profile_matches,
        "images": records,
    }


def audit(*, report_path: Path, contact_dir: Path, replace: bool) -> dict[str, Any]:
    locked = (
        (RAW, EXPECTED_SHA256["raw"], "I1 raw"),
        (FINAL, EXPECTED_SHA256["final"], "I1 review candidate"),
        (PROMPT, EXPECTED_SHA256["prompt"], "I1 prompt"),
        (RECEIPT, EXPECTED_SHA256["receipt"], "I1 receipt"),
        (GUIDE, EXPECTED_SHA256["guide"], "I1 composition guide"),
        (GUIDE_JSON, EXPECTED_SHA256["guide_json"], "I1 guide metadata"),
        (ROYAL, EXPECTED_SHA256["royal"], "I1 sole style authority"),
        (H4, EXPECTED_SHA256["h4"], "H4 comparison reference"),
        (B1, EXPECTED_SHA256["b1"], "B1 palette reference"),
        (VISION_SCHEMA, EXPECTED_SHA256["vision_schema"], "Vision schema"),
    )
    for path, digest, label in locked:
        _assert(path, digest, label)
    if report_path.exists() and not replace:
        raise I1AuditError(f"refusing to overwrite existing report: {report_path}")
    prompt_text = PROMPT.read_text(encoding="utf-8")
    required_phrases = (
        "Image 1 is geometry and composition only",
        "Image 2 is the sole authority for visual style",
        "True vertical orthographic plan view everywhere",
        "No labels, letters, numbers",
        "1536 x 1024 RGB landscape map artwork",
    )
    missing = [phrase for phrase in required_phrases if phrase not in prompt_text]
    if missing:
        raise I1AuditError("I1 prompt lost requirements: " + ", ".join(missing))
    _validate_receipt()
    if not h4.files_are_byte_identical(RAW, FINAL):
        raise I1AuditError("I1 raw and review candidate are not byte-identical")

    records: dict[str, dict[str, Any]] = {}
    images: dict[str, Image.Image] = {}
    for name, path in (
        ("raw", RAW),
        ("final", FINAL),
        ("reference_h4", H4),
        ("reference_b1", B1),
        ("style_royal", ROYAL),
    ):
        records[name], images[name] = h4.inspect_png(path)
    guide_image = Image.open(GUIDE).convert("RGB")
    try:
        contract = _image_contract(records)
        boundary = h4.boundary_metrics(images["final"])
        palette_b1 = h4.palette_continuity_metrics(images["final"], images["reference_b1"])
        palette_royal = h4.palette_continuity_metrics(images["final"], images["style_royal"])
        exact_repetition = h4.exact_repetition_metrics(images["final"])
        downsample = h4.downsample_readability_metrics(images["final"])
        semantic_repetition = h17.semantic_repetition_proxies(
            images["final"], images["reference_h4"]
        )
        contacts = build_contacts(
            images["final"], guide_image, images["style_royal"], directory=contact_dir, replace=replace
        )
    finally:
        guide_image.close()
        for image in images.values():
            image.close()

    gates = {
        "sha256_locked_inputs": True,
        "one_imagegen_call_no_retry_receipt": True,
        "raw_final_byte_identity": True,
        "image_contract_alpha_profile": contract["passed"],
        "boundary_proxy": boundary["passed"],
        "palette_continuity_with_b1": palette_b1["passed"],
        "no_large_exact_repetition_proxy": exact_repetition["passed"],
        "downsample_readability_proxy": downsample["passed"],
        "semantic_repetition_proxies_vs_h4": semantic_repetition["passed"],
    }
    failed = [name for name, passed in gates.items() if not passed]
    report = {
        "schema_version": "1.0.0",
        "id": f"{JOB_ID}-automated-audit",
        "status": "passed" if not failed else "failed",
        "scope": "automated artifact and raster proxies plus local review contacts only",
        "decision": (
            "automated-gates-passed-pending-self-vision-and-two-independent-vision-reviews"
            if not failed
            else "automated-gates-failed-rejected-before-independent-vision"
        ),
        "failed_gates": failed,
        "golden_accepted": False,
        "manifest_mutation": False,
        "generated_by": h4._artifact(Path(__file__).resolve()),
        "artifacts": {
            "raw": h4._artifact(RAW),
            "final_review_candidate": {**h4._artifact(FINAL), "review_only": True, "accepted": False},
            "prompt": h4._artifact(PROMPT),
            "generation_receipt": h4._artifact(RECEIPT),
            "geometry_only_guide": h4._artifact(GUIDE),
            "guide_metadata": h4._artifact(GUIDE_JSON),
            "sole_style_material_projection_authority": h4._artifact(ROYAL),
            "reference_h4_for_repetition_proxy_only": h4._artifact(H4),
            "reference_b1_for_palette_gate_only": h4._artifact(B1),
            "local_review_contacts": {
                name: {**record, "repository_artifact": False, "vision_report": False}
                for name, record in contacts.items()
            },
        },
        "image_contract": contract,
        "boundary": boundary,
        "palette_continuity_with_b1": palette_b1,
        "palette_continuity_with_royal_style_authority_diagnostic": palette_royal,
        "exact_repetition": exact_repetition,
        "downsample_readability": downsample,
        "semantic_repetition_proxies_vs_h4": semantic_repetition,
        "automated_gates": gates,
        "vision_handoff": {
            "status": "pending-self-vision" if not failed else "self-vision-for-rejection-evidence-only",
            "automated_audit_is_not_vision": True,
            "automated_audit_is_not_golden_acceptance": True,
            "required_focus": [
                "pseudo-writing or text-like marks",
                "strict vertical plan view and absence of side faces",
                "dark-water wave grammar repetition",
                "forest and rocky-ground semantic motif repetition",
                "directional relief or raised-side reading in the upper-right highland",
                "city, port, coast, river, road, and field composition completeness",
                "seams, pasted patches, frames, and abrupt material boundaries",
            ],
            "schema": h4._artifact(VISION_SCHEMA),
            "independent_reviewer_threshold": "two blind reviews, each score >= 94 and no immediate-failure trigger",
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--contact-dir", type=Path, default=CONTACT_DIR)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit(
            report_path=args.report.resolve(),
            contact_dir=args.contact_dir.resolve(),
            replace=args.replace,
        )
    except (I1AuditError, h4.H4AuditError, OSError, ValueError) as exc:
        print(f"I1 automated audit failed to record evidence: {exc}")
        return 1
    palette = report["palette_continuity_with_b1"]
    quarter = next(
        item for item in report["downsample_readability"]["scales"] if item["scale"] == 0.25
    )
    print(
        f"I1 status={report['status']} failed_gates={','.join(report['failed_gates']) or 'none'} "
        f"rgb={palette['rgb_histogram_intersection']} "
        f"hsv={palette['hsv_histogram_intersection']} "
        f"quarter_macrocell={quarter['macrocell_contrast_coverage']} "
        "Golden remains false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
