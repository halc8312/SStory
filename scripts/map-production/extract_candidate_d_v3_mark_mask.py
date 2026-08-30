#!/usr/bin/env python3
"""Extract Candidate D v3's forty route-like ridge marks into a narrow edit control."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from collections import deque
from pathlib import Path
from typing import Any, Iterable, Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageOps


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = REPO_ROOT / "world/map-production/candidates/style-candidate-d-v2-localized-base.png"
DEFAULT_CANDIDATE = REPO_ROOT / "world/map-production/candidates/style-candidate-d-v3-detached-fragments.png"
DEFAULT_FRAGMENT_GUIDE = REPO_ROOT / "world/map-production/controls/style-candidate-d-ridge-fragment-guide-v2.json"
DEFAULT_CONTROL = REPO_ROOT / "world/map-production/controls/style-candidate-d-v3-mark-mask-v1.json"
DEFAULT_MASK = DEFAULT_CONTROL.with_suffix(".png")
DEFAULT_REPORT = REPO_ROOT / "world/map-production/qa/automated/style-candidate-d-v3-mark-mask-v1.json"

EXPECTED_BASE_SHA256 = "7945719f6668a3e8d8967ece15a14057d5ad246321a06346e0277e7387e561f4"
EXPECTED_CANDIDATE_SHA256 = "8112f35363cc5e314e2b9793d06603bf5274a516e9a5ec72c5a06c5f421a73f8"
EXPECTED_FRAGMENT_GUIDE_SHA256 = "f63f93966258e1d7ca8150f162ff92692d3542d9959953a966ec40dcab38b352"
PARENT_EDIT_MASK = REPO_ROOT / "world/map-production/controls/style-candidate-d-ridge-edit-mask-v2.png"
EXPECTED_PARENT_EDIT_MASK_SHA256 = "13db5e135c6b7bd1beeb5c8ce4c0c2d2ed9ee80ea1cbcfb3254bcc27fdf4d83f"
CANVAS = (1536, 1024)
DARKENING_THRESHOLD = 24
REVIEWED_COMPONENT_ALLOWLIST = tuple(
    f"mark_{index:02d}" for index in range(1, 41) if index != 26
)
REVIEWED_FALSE_POSITIVES = ("mark_26",)
REVIEWED_MANUAL_STROKES = (
    {
        "id": "manual_ne_east_center",
        "points": [[1434, 158], [1446, 143]],
        "core_width": 10,
        "evidence": "400% review of missing-ne-east-source-detail.png",
    },
    {
        "id": "manual_se_north",
        "points": [[1038, 806], [1054, 795]],
        "core_width": 10,
        "evidence": "400% review of missing-se-north-source-detail.png",
    },
    {
        "id": "manual_se_under_tree",
        "points": [[1014, 879], [1038, 864]],
        "core_width": 10,
        "evidence": "400% review of missing-se-under-tree-source-detail.png",
    },
    {
        "id": "manual_se_west",
        "points": [[836, 950], [851, 937]],
        "core_width": 10,
        "evidence": "400% review of missing-839-941-source-detail.png",
    },
    {
        "id": "manual_se_east",
        "points": [[1359, 933], [1383, 936]],
        "core_width": 10,
        "evidence": "400% review of missing-se-east-source-detail.png",
    },
)


class MarkMaskError(ValueError):
    """Raised when the v3 extraction contract cannot be proven."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_input(path: Path, expected_hash: str, label: str) -> None:
    if not path.is_file():
        raise MarkMaskError(f"{label} does not exist: {path}")
    actual = sha256_file(path)
    if actual != expected_hash:
        raise MarkMaskError(f"{label} SHA-256 mismatch: expected {expected_hash}, got {actual}")


def _load_gray(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("L")
    if image.size != CANVAS:
        image.close()
        raise MarkMaskError(f"{path} must be exactly {CANVAS[0]}x{CANVAS[1]}")
    return image


def _spatial_rows() -> Iterable[tuple[int, range]]:
    for y in range(0, 420):
        yield y, range(780, CANVAS[0])
    for y in range(760, CANVAS[1]):
        yield y, range(780, CANVAS[0])


def _binary_candidates(base: Image.Image, candidate: Image.Image) -> bytearray:
    base_soft = base.filter(ImageFilter.GaussianBlur(radius=0.8))
    candidate_soft = candidate.filter(ImageFilter.GaussianBlur(radius=0.8))
    local_background = candidate.filter(ImageFilter.GaussianBlur(radius=5.0))
    base_values = base_soft.tobytes()
    candidate_soft_values = candidate_soft.tobytes()
    candidate_values = candidate.tobytes()
    background_values = local_background.tobytes()
    width, height = CANVAS
    binary = bytearray(width * height)
    for y, xs in _spatial_rows():
        row = y * width
        for x in xs:
            index = row + x
            if (
                base_values[index] - candidate_soft_values[index] > DARKENING_THRESHOLD
                and background_values[index] - candidate_values[index] > 12
                and candidate_values[index] < 125
            ):
                binary[index] = 1
    base_soft.close()
    candidate_soft.close()
    local_background.close()
    return binary


def _eigenvalues_and_axis(points: list[tuple[int, int]]) -> tuple[float, float, tuple[float, float], tuple[float, float]]:
    count = len(points)
    mean_x = sum(point[0] for point in points) / count
    mean_y = sum(point[1] for point in points) / count
    denominator = max(1, count - 1)
    covariance_xx = sum((x - mean_x) ** 2 for x, _ in points) / denominator
    covariance_yy = sum((y - mean_y) ** 2 for _, y in points) / denominator
    covariance_xy = sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator
    trace = covariance_xx + covariance_yy
    root = math.sqrt(max(0.0, (covariance_xx - covariance_yy) ** 2 + 4 * covariance_xy**2))
    minimum = max(0.0, (trace - root) / 2)
    maximum = max(0.0, (trace + root) / 2)
    if abs(covariance_xy) > 1e-9:
        axis_x, axis_y = covariance_xy, maximum - covariance_xx
    elif covariance_xx >= covariance_yy:
        axis_x, axis_y = 1.0, 0.0
    else:
        axis_x, axis_y = 0.0, 1.0
    length = math.hypot(axis_x, axis_y) or 1.0
    axis_x, axis_y = axis_x / length, axis_y / length
    projections = [(x - mean_x) * axis_x + (y - mean_y) * axis_y for x, y in points]
    minimum_projection, maximum_projection = min(projections), max(projections)
    endpoints = (
        (mean_x + minimum_projection * axis_x, mean_y + minimum_projection * axis_y),
        (mean_x + maximum_projection * axis_x, mean_y + maximum_projection * axis_y),
    )
    return minimum, maximum, (mean_x, mean_y), endpoints


def extract_components(
    base: Image.Image,
    candidate: Image.Image,
    *,
    expected_count: int | None = 40,
) -> list[dict[str, Any]]:
    width, height = CANVAS
    binary = _binary_candidates(base, candidate)
    components: list[dict[str, Any]] = []
    neighbors = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))
    for y, xs in _spatial_rows():
        for x in xs:
            start = y * width + x
            if not binary[start]:
                continue
            binary[start] = 0
            queue: deque[tuple[int, int]] = deque([(x, y)])
            points: list[tuple[int, int]] = []
            while queue:
                current_x, current_y = queue.popleft()
                points.append((current_x, current_y))
                for delta_x, delta_y in neighbors:
                    next_x, next_y = current_x + delta_x, current_y + delta_y
                    if not (780 <= next_x < width and 0 <= next_y < height):
                        continue
                    if not (next_y < 420 or next_y >= 760):
                        continue
                    index = next_y * width + next_x
                    if binary[index]:
                        binary[index] = 0
                        queue.append((next_x, next_y))
            area = len(points)
            minimum_x = min(point[0] for point in points)
            maximum_x = max(point[0] for point in points)
            minimum_y = min(point[1] for point in points)
            maximum_y = max(point[1] for point in points)
            box_width = maximum_x - minimum_x + 1
            box_height = maximum_y - minimum_y + 1
            if not 25 <= area <= 120 or not 8 <= max(box_width, box_height) <= 45:
                continue
            eigen_min, eigen_max, centroid, endpoints = _eigenvalues_and_axis(points)
            elongation = (eigen_max + 0.1) / (eigen_min + 0.1)
            if elongation < 8.0:
                continue
            components.append(
                {
                    "component_id": f"mark_{len(components) + 1:02d}",
                    "bbox": [minimum_x, minimum_y, box_width, box_height],
                    "area_px": area,
                    "centroid": [round(centroid[0], 4), round(centroid[1], 4)],
                    "covariance_eigenvalue_ratio": round(elongation, 4),
                    "centerline_endpoints": [
                        [round(endpoints[0][0], 4), round(endpoints[0][1], 4)],
                        [round(endpoints[1][0], 4), round(endpoints[1][1], 4)],
                    ],
                    "minor_sigma_px": round(math.sqrt(eigen_min), 4),
                    "_target_pixels": points,
                }
            )
    components.sort(key=lambda item: (item["centroid"][1], item["centroid"][0]))
    for index, component in enumerate(components, start=1):
        component["component_id"] = f"mark_{index:02d}"
    if expected_count is not None and len(components) != expected_count:
        raise MarkMaskError(
            f"expected exactly {expected_count} accepted components, found {len(components)}"
        )
    return components


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _expanded_centerline(
    endpoints: Sequence[Sequence[float]], padding_px: float = 2.0
) -> list[list[int]]:
    first = tuple(map(float, endpoints[0]))
    second = tuple(map(float, endpoints[1]))
    delta_x, delta_y = second[0] - first[0], second[1] - first[1]
    length = math.hypot(delta_x, delta_y) or 1.0
    unit_x, unit_y = delta_x / length, delta_y / length
    return [
        [round(first[0] - unit_x * padding_px), round(first[1] - unit_y * padding_px)],
        [round(second[0] + unit_x * padding_px), round(second[1] + unit_y * padding_px)],
    ]


def build_control(
    components: list[dict[str, Any]],
    base_path: Path,
    candidate_path: Path,
    guide_path: Path,
) -> dict[str, Any]:
    by_id = {component["component_id"]: component for component in components}
    if set(by_id) != {f"mark_{index:02d}" for index in range(1, 41)}:
        raise MarkMaskError("automated component ids must remain mark_01 through mark_40")
    strokes: list[dict[str, Any]] = []
    for component_id in REVIEWED_COMPONENT_ALLOWLIST:
        component = by_id[component_id]
        box_minor_axis = min(component["bbox"][2], component["bbox"][3])
        core_width = max(8, min(18, box_minor_axis + 4))
        points = _expanded_centerline(component["centerline_endpoints"])
        strokes.extend(
            [
                {
                    "id": f"{component_id}_feather",
                    "points": points,
                    "width": core_width + 6,
                    "feather_inside_px": 2,
                    "review_role": "visually-verified-route-mark-feather",
                },
                {
                    "id": f"{component_id}_core",
                    "points": points,
                    "width": core_width,
                    "feather_inside_px": 0,
                    "review_role": "visually-verified-route-mark-opaque-core",
                },
            ]
        )
    for manual in REVIEWED_MANUAL_STROKES:
        points = manual["points"]
        core_width = manual["core_width"]
        strokes.extend(
            [
                {
                    "id": f"{manual['id']}_feather",
                    "points": points,
                    "width": core_width + 6,
                    "feather_inside_px": 2,
                    "review_role": "manually-added-route-mark-feather",
                },
                {
                    "id": f"{manual['id']}_core",
                    "points": points,
                    "width": core_width,
                    "feather_inside_px": 0,
                    "review_role": "manually-added-route-mark-opaque-core",
                },
            ]
        )
    return {
        "schema_version": "1.0.0",
        "id": "style-candidate-d-v3-mark-mask-v1",
        "coordinate_space": "source-pixels-y-down",
        "canvas": {"width": CANVAS[0], "height": CANVAS[1]},
        "source_image": _relative(candidate_path),
        "composite_base": _relative(candidate_path),
        "detection_base": {"path": _relative(base_path), "sha256": EXPECTED_BASE_SHA256},
        "fragment_role_control": {"path": _relative(guide_path), "sha256": EXPECTED_FRAGMENT_GUIDE_SHA256},
        "extraction": {
            "grayscale": "Pillow-L",
            "darkening_gaussian_radius_px": 0.8,
            "darkening_threshold": DARKENING_THRESHOLD,
            "local_background_gaussian_radius_px": 5.0,
            "local_contrast_threshold": 12,
            "candidate_luminance_maximum": 124,
            "spatial_gate": [[780, 0, 1536, 420], [780, 760, 1536, 1024]],
            "connectivity": 8,
            "area_px": [25, 120],
            "maximum_bbox_axis_px": [8, 45],
            "minimum_covariance_eigenvalue_ratio": 8.0,
        },
        "purpose": "Attempt-four erase mask restricted to forty-four visually verified dark route-like capsule marks from Candidate D v3.",
        "include_strokes": strokes,
        "exclude_strokes": [],
        "feather_inside_px": 2,
        "automated_component_count": 40,
        "reviewed_component_allowlist": list(REVIEWED_COMPONENT_ALLOWLIST),
        "reviewed_false_positives": list(REVIEWED_FALSE_POSITIVES),
        "reviewed_manual_strokes": list(REVIEWED_MANUAL_STROKES),
        "reviewed_target_count": 44,
        "review_status": "provisional",
        "notes": "Thirty-nine automated components passed 100% and 400% visual review; mark_26 was rejected as a tree, and five visually verified omissions were added manually. Each target has an opaque core plus a narrow outward feather. The v3 marks do not preserve a reliable per-ridge 3:1 role distribution, so attempt four erases the reviewed artifacts without inventing post-hoc roles.",
    }


def _load_composite_module() -> Any:
    module_path = REPO_ROOT / "scripts/map-production/composite_masked_edit.py"
    module_spec = importlib.util.spec_from_file_location("candidate_d_composite", module_path)
    if module_spec is None or module_spec.loader is None:
        raise MarkMaskError(f"cannot load composite module: {module_path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def render_audit_crops(
    candidate_path: Path,
    mask_path: Path,
    components: list[dict[str, Any]],
    output_directory: Path,
) -> None:
    """Render numbered diagnostic crops; never use these rasters as generation input."""

    annotated_targets = {
        "north-east-components.png": (780, 0, 1536, 420),
        "south-east-components.png": (780, 760, 1536, 1024),
    }
    overlay_targets = {
        "north-east-mask-overlay.png": (780, 0, 1536, 420),
        "south-east-mask-overlay.png": (780, 760, 1536, 1024),
        "ne-overlay-q1.png": (780, 0, 1160, 210),
        "ne-overlay-q2.png": (1150, 0, 1536, 210),
        "ne-overlay-q3.png": (780, 200, 1160, 420),
        "ne-overlay-q4.png": (1150, 200, 1536, 420),
        "se-overlay-q1.png": (780, 760, 1160, 900),
        "se-overlay-q2.png": (1150, 760, 1536, 900),
        "se-overlay-q3.png": (780, 890, 1160, 1024),
        "se-overlay-q4.png": (1150, 890, 1536, 1024),
    }
    raw_targets = {
        "mark-26-source-detail.png": (980, 800, 1060, 890),
        "missing-839-941-source-detail.png": (800, 900, 880, 985),
        "missing-ne-east-source-detail.png": (1400, 100, 1485, 190),
        "missing-se-north-source-detail.png": (1000, 760, 1080, 830),
        "missing-se-under-tree-source-detail.png": (990, 840, 1070, 910),
        "missing-se-east-source-detail.png": (1320, 900, 1410, 980),
    }
    existing = [
        output_directory / name
        for name in (*annotated_targets, *overlay_targets, *raw_targets)
        if (output_directory / name).exists()
    ]
    if existing:
        raise MarkMaskError(f"refusing to overwrite existing audit crop: {existing[0]}")
    with Image.open(candidate_path) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
    annotated = source.copy()
    draw = ImageDraw.Draw(annotated)
    for component in components:
        x, y, width, height = component["bbox"]
        label = component["component_id"].removeprefix("mark_")
        draw.rectangle((x - 3, y - 3, x + width + 2, y + height + 2), outline="#FF1A1A", width=2)
        label_box = (x - 3, max(0, y - 16), x + 18, max(12, y - 2))
        draw.rectangle(label_box, fill="#FFF37A", outline="#111111", width=1)
        draw.text((x, max(0, y - 15)), label, fill="#111111")
    output_directory.mkdir(parents=True, exist_ok=True)
    for name, box in annotated_targets.items():
        crop = annotated.crop(box)
        enlarged = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.NEAREST)
        enlarged.save(output_directory / name, format="PNG", compress_level=9, optimize=False)
        enlarged.close()
        crop.close()
    with Image.open(mask_path) as opened_mask:
        mask = ImageOps.exif_transpose(opened_mask).convert("L")
    alpha = mask.point(lambda value: round(value * 0.72))
    color = Image.new("RGBA", CANVAS, (0, 245, 255, 0))
    color.putalpha(alpha)
    overlay = Image.alpha_composite(source.convert("RGBA"), color).convert("RGB")
    for name, box in overlay_targets.items():
        crop = overlay.crop(box)
        enlarged = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.NEAREST)
        enlarged.save(output_directory / name, format="PNG", compress_level=9, optimize=False)
        enlarged.close()
        crop.close()
    overlay.close()
    color.close()
    alpha.close()
    mask.close()
    for name, box in raw_targets.items():
        crop = source.crop(box)
        enlarged = crop.resize((crop.width * 8, crop.height * 8), Image.Resampling.NEAREST)
        enlarged.save(output_directory / name, format="PNG", compress_level=9, optimize=False)
        enlarged.close()
        crop.close()
    annotated.close()
    source.close()


def generate(
    *, base_path: Path, candidate_path: Path, fragment_guide_path: Path,
    control_path: Path, mask_path: Path, report_path: Path,
) -> dict[str, Any]:
    outputs = (control_path, mask_path, report_path)
    existing = [path for path in outputs if path.exists()]
    if existing:
        raise MarkMaskError(f"refusing to overwrite existing output: {existing[0]}")
    _assert_input(base_path, EXPECTED_BASE_SHA256, "localized base")
    _assert_input(candidate_path, EXPECTED_CANDIDATE_SHA256, "Candidate D v3")
    _assert_input(fragment_guide_path, EXPECTED_FRAGMENT_GUIDE_SHA256, "fragment guide")
    _assert_input(PARENT_EDIT_MASK, EXPECTED_PARENT_EDIT_MASK_SHA256, "parent ridge-edit mask")
    fragment_guide = json.loads(fragment_guide_path.read_text(encoding="utf-8"))
    base = _load_gray(base_path)
    candidate = _load_gray(candidate_path)
    try:
        components = extract_components(base, candidate)
    finally:
        base.close()
        candidate.close()
    control = build_control(components, base_path, candidate_path, fragment_guide_path)
    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
    control_path.write_text(
        json.dumps(control, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    composite_module = _load_composite_module()
    mask = composite_module.build_mask(control)
    try:
        mask.save(mask_path, format="PNG", optimize=True)
        mask_values = bytes(mask.get_flattened_data())
        mask_pixels = sum(value > 0 for value in mask_values)
        opaque_pixels = sum(value == 255 for value in mask_values)
        by_id = {component["component_id"]: component for component in components}
        target_pixels = [
            point
            for component_id in REVIEWED_COMPONENT_ALLOWLIST
            for point in by_id[component_id]["_target_pixels"]
        ]
        uncovered_target_pixels = [
            point for point in target_pixels if mask_values[point[1] * CANVAS[0] + point[0]] != 255
        ]
        false_positive_pixels = [
            point
            for component_id in REVIEWED_FALSE_POSITIVES
            for point in by_id[component_id]["_target_pixels"]
        ]
        masked_false_positive_pixels = [
            point for point in false_positive_pixels if mask_values[point[1] * CANVAS[0] + point[0]] != 0
        ]
        manual_core_failures = []
        for manual in REVIEWED_MANUAL_STROKES:
            for point in manual["points"]:
                if mask_values[point[1] * CANVAS[0] + point[0]] != 255:
                    manual_core_failures.append({"id": manual["id"], "point": point})
        with Image.open(PARENT_EDIT_MASK) as opened_parent_mask:
            parent_mask = ImageOps.exif_transpose(opened_parent_mask).convert("L")
            parent_values = bytes(parent_mask.get_flattened_data())
            parent_mask.close()
        outside_parent_edit_mask_pixels = sum(
            value > 0 and parent_values[index] == 0
            for index, value in enumerate(mask_values)
        )
    finally:
        mask.close()
    if uncovered_target_pixels:
        raise MarkMaskError(
            f"reviewed target mask lacks a 255 core at {len(uncovered_target_pixels)} pixels"
        )
    if masked_false_positive_pixels:
        raise MarkMaskError(
            f"tree false-positive pixels intersect the mask at {len(masked_false_positive_pixels)} pixels"
        )
    if manual_core_failures:
        raise MarkMaskError(f"manual target endpoints lack a 255 core: {manual_core_failures}")
    if outside_parent_edit_mask_pixels:
        raise MarkMaskError(
            f"reviewed mask leaves the parent ridge-edit control at {outside_parent_edit_mask_pixels} pixels"
        )
    report = {
        "schema_version": "1.0.0",
        "id": "style-candidate-d-v3-mark-mask-v1",
        "base_path": _relative(base_path),
        "candidate_path": _relative(candidate_path),
        "fragment_guide_path": _relative(fragment_guide_path),
        "control_path": _relative(control_path),
        "mask_path": _relative(mask_path),
        "automated_component_count": len(components),
        "regional_component_counts": {
            "north_east": sum(component["centroid"][1] < 420 for component in components),
            "south_east": sum(component["centroid"][1] >= 760 for component in components),
        },
        "role_assignment": "not-claimed-because-v3-does-not-preserve-four-marks-per-ridge",
        "reviewed_component_allowlist": list(REVIEWED_COMPONENT_ALLOWLIST),
        "reviewed_false_positives": list(REVIEWED_FALSE_POSITIVES),
        "reviewed_manual_strokes": list(REVIEWED_MANUAL_STROKES),
        "reviewed_target_count": 44,
        "extraction": control["extraction"],
        "mask_pixels": mask_pixels,
        "opaque_mask_pixels": opaque_pixels,
        "reviewed_detected_target_pixels": len(target_pixels),
        "reviewed_detected_target_pixels_without_opaque_core": len(uncovered_target_pixels),
        "masked_false_positive_pixels": len(masked_false_positive_pixels),
        "manual_endpoint_core_failures": manual_core_failures,
        "outside_parent_edit_mask_pixels": outside_parent_edit_mask_pixels,
        "control_sha256": sha256_file(control_path),
        "mask_sha256": sha256_file(mask_path),
        "components": [
            {key: value for key, value in component.items() if not key.startswith("_")}
            for component in components
        ],
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--fragment-guide", type=Path, default=DEFAULT_FRAGMENT_GUIDE)
    parser.add_argument("--control", type=Path, default=DEFAULT_CONTROL)
    parser.add_argument("--mask", type=Path, default=DEFAULT_MASK)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--audit-dir", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = generate(base_path=args.base.resolve(), candidate_path=args.candidate.resolve(), fragment_guide_path=args.fragment_guide.resolve(), control_path=args.control.resolve(), mask_path=args.mask.resolve(), report_path=args.report.resolve())
    except (OSError, json.JSONDecodeError, MarkMaskError, ValueError) as exc:
        print(f"Candidate D v3 mark-mask extraction failed: {exc}")
        return 1
    if args.audit_dir is not None:
        try:
            render_audit_crops(
                args.candidate.resolve(),
                args.mask.resolve(),
                report["components"],
                args.audit_dir.resolve(),
            )
        except (OSError, MarkMaskError) as exc:
            print(f"Candidate D v3 mark-mask audit render failed: {exc}")
            return 1
    print(
        "Candidate D v3 mark mask extracted: "
        f"automated_components={report['automated_component_count']} "
        f"reviewed_targets={report['reviewed_target_count']} "
        f"mask_pixels={report['mask_pixels']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
