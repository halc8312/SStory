#!/usr/bin/env python3
"""Verify that map-production artifacts are safe to publish.

This validator is intentionally separate from ``validate_manifest.py``.  The
normal manifest command accepts planned and in-progress jobs; this command
recomputes release evidence from disk and can enable the final publication
gates with ``--strict-release``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from production_common import (
    DEFAULT_MANIFEST_SCHEMA,
    REPO_ROOT,
    ValidationFailure,
    load_json,
)
from validate_manifest import schema_errors, validate_manifest
from reviewer_identity import (
    INDEPENDENT_VISION_REVIEW_ROLES,
    canonical_reviewer_identity,
)
from validate_resolution_contract import (
    DEFAULT_CONTRACT as DEFAULT_RESOLUTION_CONTRACT,
    validate_resolution_contract,
)


DEFAULT_MANIFEST = REPO_ROOT / "world" / "map-production" / "production-manifest.json"
DEFAULT_QA_SCHEMA = (
    REPO_ROOT / "world" / "map-production" / "schemas" / "qa-report.schema.json"
)
DEFAULT_QA_DIR = REPO_ROOT / "world" / "map-production" / "qa"
DEFAULT_MAP_SHEETS = REPO_ROOT / "world" / "map-production" / "source" / "map-sheets.json"

RELEASE_STATES = frozenset({"accepted", "tiled", "staging", "published"})
SHEET_STATE_COVERAGE = {
    "accepted": RELEASE_STATES,
    "tiled": frozenset({"tiled", "staging", "published"}),
    "staging": frozenset({"staging", "published"}),
    "published": frozenset({"published"}),
}
SHA256_LENGTH = 64
PUBLIC_TILE_SIZE = 512
PUBLIC_TILE_FORMAT = "webp"
VISION_QA_REPORT_MARKERS = frozenset(
    {"job_id", "created_at", "review_views", "acceptance_threshold", "scores"}
)
DIRECT17_STANDARD_REVIEW_IDS = frozenset(
    {
        "sheet_region_atlantia_region",
        "sheet_region_emerald_plains_region",
        "sheet_region_ethernia_core_region",
    }
)
DIRECT17_IDS = frozenset(
    {
        "sheet_region_royal_capital_region",
        "sheet_region_silver_plains_region",
        "sheet_region_soaring_mountains_region",
        "sheet_region_moonlit_forest_region",
        "sheet_region_emerald_plains_region",
        "sheet_region_port_zephia_region",
        "sheet_region_lumiera_arch_region",
        "sheet_region_emerald_belt_region",
        "sheet_region_red_sea_desert_region",
        "sheet_region_jade_oasis_region",
        "sheet_region_marineport_region",
        "sheet_region_atlantia_region",
        "sheet_region_time_port_region",
        "sheet_region_ethernia_core_region",
        "sheet_corridor_astralis_port_zephia",
        "sheet_settlement_astralis",
        "sheet_settlement_port_zephia",
    }
)


def sha256_file(path: Path) -> str:
    """Return a lowercase SHA-256 digest without loading a large file at once."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_path(raw_path: str, label: str, repo_root: Path) -> tuple[Path | None, list[str]]:
    """Resolve one repository-relative POSIX path without allowing traversal."""

    errors: list[str] = []
    if not raw_path or "\\" in raw_path:
        return None, [f"{label} must be a non-empty repository-relative POSIX path"]
    portable = PurePosixPath(raw_path)
    if portable.is_absolute() or any(part in {"", ".", ".."} for part in portable.parts):
        return None, [f"{label} must stay inside the repository: {raw_path}"]
    # PurePosixPath does not treat a Windows drive prefix as absolute.
    if portable.parts and portable.parts[0].endswith(":"):
        return None, [f"{label} must stay inside the repository: {raw_path}"]

    root = repo_root.resolve()
    resolved = root.joinpath(*portable.parts).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        errors.append(f"{label} must stay inside the repository: {raw_path}")
        return None, errors
    return resolved, errors


def _load_object(path: Path, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        value = load_json(path)
    except ValidationFailure as exc:
        return None, [f"{label}: {exc}"]
    if not isinstance(value, dict):
        return None, [f"{label} must contain a JSON object"]
    return value, []


def _verify_hash(
    raw_path: str,
    expected: Any,
    label: str,
    repo_root: Path,
    *,
    require_hash: bool,
) -> tuple[Path | None, list[str]]:
    resolved, errors = _portable_path(raw_path, f"{label}.path", repo_root)
    if resolved is None:
        return None, errors
    if not resolved.is_file():
        errors.append(f"{label}.path does not exist as a file: {raw_path}")
        return resolved, errors
    if expected is None:
        if require_hash:
            errors.append(f"{label}.sha256 is required for release evidence")
        return resolved, errors
    if not isinstance(expected, str) or len(expected) != SHA256_LENGTH:
        errors.append(f"{label}.sha256 must be a 64-character digest")
        return resolved, errors
    actual = sha256_file(resolved)
    if actual != expected.lower():
        errors.append(f"{label}.sha256 mismatch: manifest={expected}, actual={actual}")
    return resolved, errors


def _image_dimensions(path: Path, label: str) -> tuple[tuple[int, int] | None, list[str]]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValidationFailure(
            "Pillow is required to recalculate release image dimensions"
        ) from exc

    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return image.size, []
    except (OSError, ValueError) as exc:
        return None, [f"{label} is not a readable image: {exc}"]


def validate_job_artifacts(
    job: dict[str, Any], index: int, repo_root: Path
) -> tuple[Path | None, list[str]]:
    """Recompute hashes and master dimensions for one materialized job."""

    errors: list[str] = []
    label = f"jobs[{index}]"
    status = job.get("status")
    materialized = status not in {"planned", "inputs-ready"}

    inputs = job.get("inputs")
    if isinstance(inputs, list):
        for input_index, artifact in enumerate(inputs):
            if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
                continue
            _, artifact_errors = _verify_hash(
                artifact["path"],
                artifact.get("sha256"),
                f"{label}.inputs[{input_index}]",
                repo_root,
                require_hash=materialized,
            )
            errors.extend(artifact_errors)

    generation = job.get("generation")
    if isinstance(generation, dict):
        prompt_path = generation.get("prompt_path")
        prompt_sha = generation.get("prompt_sha256")
        if isinstance(prompt_path, str) and prompt_sha is not None:
            _, prompt_errors = _verify_hash(
                prompt_path,
                prompt_sha,
                f"{label}.generation.prompt",
                repo_root,
                require_hash=materialized,
            )
            errors.extend(prompt_errors)

    master_path: Path | None = None
    master = job.get("master")
    if isinstance(master, dict) and isinstance(master.get("path"), str):
        master_path, master_errors = _verify_hash(
            master["path"],
            master.get("sha256"),
            f"{label}.master",
            repo_root,
            require_hash=True,
        )
        errors.extend(master_errors)
        if master_path is not None and master_path.is_file():
            dimensions, dimension_errors = _image_dimensions(master_path, f"{label}.master")
            errors.extend(dimension_errors)
            if dimensions is not None:
                expected = (master.get("width"), master.get("height"))
                if dimensions != expected:
                    errors.append(
                        f"{label}.master dimensions mismatch: manifest={expected[0]}x{expected[1]}, "
                        f"actual={dimensions[0]}x{dimensions[1]}"
                    )
    return master_path, errors


def _qa_schema_errors(report: Any, schema: Any, label: str) -> list[str]:
    return [f"{label}: {error}" for error in schema_errors(report, schema)]


def _uses_vision_qa_report_schema(report: dict[str, Any]) -> bool:
    """Distinguish scored job reviews from auxiliary Vision decision records."""

    return bool(VISION_QA_REPORT_MARKERS.intersection(report))


def _load_qa_reports(
    qa_dir: Path,
    qa_schema: dict[str, Any],
    repo_root: Path,
    *,
    required_vision_paths: set[Path] | None = None,
) -> tuple[
    dict[Path, dict[str, Any]],
    dict[Path, dict[str, Any]],
    list[str],
]:
    """Load QA JSON recursively and separately identify Vision reports.

    ``qa/automated/**`` intentionally contains machine-produced reports with
    several task-specific schemas.  The QA root also contains auxiliary Root
    Vision source-authority and derivation records.  Every JSON document is
    parsed and remains available for manifest-reference checks, but only a
    manifest-bound Vision report or a document with scored job-review markers
    is checked against ``qa-report.schema.json`` and allowed to count as an
    independent visual review.
    """

    reports: dict[Path, dict[str, Any]] = {}
    vision_reports: dict[Path, dict[str, Any]] = {}
    errors: list[str] = []
    required_vision_paths = required_vision_paths or set()
    qa_root = qa_dir.resolve()
    try:
        qa_root.relative_to(repo_root.resolve())
    except ValueError:
        return {}, {}, [f"QA directory must stay inside the repository: {qa_dir}"]
    if not qa_dir.is_dir():
        return {}, {}, [f"QA directory does not exist: {qa_dir}"]

    for path in sorted(qa_dir.rglob("*.json")):
        resolved = path.resolve()
        try:
            qa_relative = resolved.relative_to(qa_root)
        except ValueError:
            errors.append(f"QA report escapes the configured QA directory: {path}")
            continue
        report, report_errors = _load_object(path, f"QA report {path}")
        errors.extend(report_errors)
        if report is None:
            continue
        reports[resolved] = report
        try:
            relative = resolved.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            relative = str(path)
        if "automated" in qa_relative.parts:
            continue
        if (
            resolved not in required_vision_paths
            and not _uses_vision_qa_report_schema(report)
        ):
            continue

        vision_reports[resolved] = report
        errors.extend(_qa_schema_errors(report, qa_schema, f"QA report {relative}"))
        scores = report.get("scores")
        if isinstance(scores, list) and all(isinstance(item, dict) for item in scores):
            maxima = [item.get("maximum") for item in scores]
            values = [item.get("score") for item in scores]
            if all(isinstance(value, int) and not isinstance(value, bool) for value in maxima):
                if sum(maxima) != 100:
                    errors.append(f"QA report {relative}: score maxima must sum to 100")
            if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
                total = report.get("total_score")
                if total != sum(values):
                    errors.append(
                        f"QA report {relative}: total_score {total!r} does not equal "
                        f"the score sum {sum(values)}"
                    )
                if all(
                    isinstance(maximum, int) and not isinstance(maximum, bool)
                    for maximum in maxima
                ):
                    over = [
                        item.get("id")
                        for item, value, maximum in zip(scores, values, maxima)
                        if value > maximum
                    ]
                    if over:
                        errors.append(
                            f"QA report {relative}: scores exceed category maxima: {over}"
                        )
    return reports, vision_reports, errors


def _referenced_qa_paths(job: dict[str, Any]) -> Iterable[tuple[str, str]]:
    qa = job.get("qa")
    if not isinstance(qa, dict):
        return
    for section in ("automated", "vision"):
        details = qa.get(section)
        if isinstance(details, dict) and isinstance(details.get("report_path"), str):
            yield section, details["report_path"]


def validate_job_qa(
    job: dict[str, Any],
    index: int,
    reports: dict[Path, dict[str, Any]],
    vision_reports: dict[Path, dict[str, Any]],
    repo_root: Path,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Match manifest Vision fields to the referenced, schema-valid report."""

    errors: list[str] = []
    label = f"jobs[{index}]"
    master = job.get("master")
    master_path = master.get("path") if isinstance(master, dict) else None
    master_sha256 = master.get("sha256") if isinstance(master, dict) else None
    vision_report: dict[str, Any] | None = None

    for section, raw_path in _referenced_qa_paths(job):
        resolved, path_errors = _portable_path(
            raw_path, f"{label}.qa.{section}.report_path", repo_root
        )
        errors.extend(path_errors)
        if resolved is None:
            continue
        report = reports.get(resolved)
        if report is None:
            if not resolved.is_file():
                errors.append(f"{label}.qa.{section}.report_path does not exist: {raw_path}")
            else:
                errors.append(
                    f"{label}.qa.{section}.report_path is outside the configured QA directory "
                    f"or could not be validated: {raw_path}"
                )
            continue
        if section == "vision" and resolved not in vision_reports:
            errors.append(
                f"{label}.qa.vision.report_path points to automated QA evidence, "
                f"not a Vision review: {raw_path}"
            )
            continue
        if (
            section == "automated"
            and job.get("status") in RELEASE_STATES
            and "automated" not in PurePosixPath(raw_path).parts
        ):
            errors.append(
                f"{label}.qa.automated.report_path must be stored under a qa/automated/ "
                f"subdirectory for release-state jobs: {raw_path}"
            )
        if report.get("job_id") != job.get("id"):
            # Automated reports predate a common schema.  When they expose a
            # job_id, bind it; Vision reports always require one via schema.
            if section == "vision" or "job_id" in report:
                errors.append(
                    f"{label}.qa.{section}: job_id mismatch: manifest={job.get('id')!r}, "
                    f"report={report.get('job_id')!r}"
                )
        if master_path is not None and report.get("image_path") != master_path:
            if section == "vision" or "image_path" in report:
                errors.append(
                    f"{label}.qa.{section}: image_path mismatch: manifest={master_path!r}, "
                    f"report={report.get('image_path')!r}"
                )
        if (
            section == "vision"
            and report.get("image_sha256") is not None
            and report.get("image_sha256") != master_sha256
        ):
            errors.append(
                f"{label}.qa.vision: image_sha256 mismatch: "
                f"manifest={master_sha256!r}, report={report.get('image_sha256')!r}"
            )
        if section == "automated" and job.get("status") in RELEASE_STATES:
            if report.get("status") != "passed":
                errors.append(
                    f"{label}.qa.automated report must have status 'passed' "
                    f"for release-state jobs"
                )
        if section == "vision":
            vision_report = report

    qa = job.get("qa")
    vision = qa.get("vision") if isinstance(qa, dict) else None
    if isinstance(vision, dict) and vision_report is not None:
        comparisons = (
            ("decision", vision.get("decision"), vision_report.get("decision")),
            ("score", vision.get("score"), vision_report.get("total_score")),
        )
        for field, manifest_value, report_value in comparisons:
            if manifest_value != report_value:
                errors.append(
                    f"{label}.qa.vision.{field} mismatch: manifest={manifest_value!r}, "
                    f"report={report_value!r}"
                )
        manifest_reviewer = vision.get("reviewer")
        report_reviewer = vision_report.get("reviewer")
        try:
            reviewer_matches = (
                isinstance(manifest_reviewer, str)
                and isinstance(report_reviewer, str)
                and canonical_reviewer_identity(manifest_reviewer)
                == canonical_reviewer_identity(report_reviewer)
            )
        except ValueError:
            reviewer_matches = False
        if not reviewer_matches:
            errors.append(
                f"{label}.qa.vision.reviewer mismatch: manifest={manifest_reviewer!r}, "
                f"report={report_reviewer!r}"
            )
        threshold = job.get("acceptance_threshold", 90)
        if vision_report.get("acceptance_threshold") != threshold:
            errors.append(
                f"{label}.qa.vision acceptance_threshold mismatch: manifest={threshold!r}, "
                f"report={vision_report.get('acceptance_threshold')!r}"
            )
        if vision_report.get("status") != "complete":
            errors.append(f"{label}.qa.vision report must have status 'complete'")
        failures = vision_report.get("immediate_failures")
        if vision_report.get("decision") == "accepted" and isinstance(failures, list):
            detected = [item.get("id") for item in failures if isinstance(item, dict) and item.get("detected")]
            if detected:
                errors.append(
                    f"{label}.qa.vision accepted report has immediate failures: "
                    + ", ".join(str(item) for item in detected)
                )
    return vision_report, errors


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _optional_bytes(
    owner: dict[str, Any], actual: int, label: str, errors: list[str]
) -> None:
    for field in ("bytes", "byte_size", "total_bytes"):
        if field in owner and owner[field] != actual:
            errors.append(f"{label}.{field} mismatch: metadata={owner[field]!r}, actual={actual}")


def _tile_set_digest(tile_digests: Iterable[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for relative, tile_digest in sorted(tile_digests):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(tile_digest.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _tile_pixel_contract_errors(
    image: Any,
    *,
    level_width: int,
    level_height: int,
    column: int,
    row: int,
    tile_size: int,
    label: str,
) -> list[str]:
    """Validate one sheet-local tile's content rectangle and transparent padding."""

    errors: list[str] = []
    content_width = min(tile_size, level_width - column * tile_size)
    content_height = min(tile_size, level_height - row * tile_size)
    if content_width <= 0 or content_height <= 0:
        return [f"{label} lies outside the declared sheet-local level extent"]

    alpha = image.convert("RGBA").getchannel("A")
    content = alpha.crop((0, 0, content_width, content_height))
    if content.getbbox() is None:
        errors.append(f"{label} has no visible pixels inside its declared content rectangle")

    if content_width < tile_size:
        right_padding = alpha.crop((content_width, 0, tile_size, tile_size))
        if right_padding.getbbox() is not None:
            errors.append(
                f"{label} right-edge padding must have RGBA alpha=0 "
                f"from x={content_width} through {tile_size - 1}"
            )
    if content_height < tile_size:
        bottom_padding = alpha.crop((0, content_height, tile_size, tile_size))
        if bottom_padding.getbbox() is not None:
            errors.append(
                f"{label} bottom-edge padding must have RGBA alpha=0 "
                f"from y={content_height} through {tile_size - 1}"
            )
    return errors


def validate_tile_output(
    job: dict[str, Any],
    index: int,
    repo_root: Path,
    coordinate_system: str | None = None,
) -> tuple[int, int, list[str]]:
    """Verify metadata, expected XYZ files, byte counts, and tile-set digest."""

    output = job.get("output")
    if not isinstance(output, dict):
        return 0, 0, []
    errors: list[str] = []
    label = f"jobs[{index}].output"
    tiles_raw = output.get("tiles_path")
    metadata_raw = output.get("metadata_path")
    if not isinstance(tiles_raw, str) or not isinstance(metadata_raw, str):
        return 0, 0, [f"{label} must define tiles_path and metadata_path"]
    tiles_path, tile_path_errors = _portable_path(tiles_raw, f"{label}.tiles_path", repo_root)
    metadata_path, metadata_path_errors = _portable_path(
        metadata_raw, f"{label}.metadata_path", repo_root
    )
    errors.extend(tile_path_errors)
    errors.extend(metadata_path_errors)
    if tiles_path is None or metadata_path is None:
        return 0, 0, errors
    if not tiles_path.is_dir():
        errors.append(f"{label}.tiles_path does not exist as a directory: {tiles_raw}")
        return 0, 0, errors
    if not metadata_path.is_file():
        errors.append(f"{label}.metadata_path does not exist as a file: {metadata_raw}")
        return 0, 0, errors
    try:
        metadata_path.relative_to(tiles_path)
    except ValueError:
        errors.append(f"{label}.metadata_path must be inside tiles_path")

    metadata, load_errors = _load_object(metadata_path, f"{label}.metadata")
    errors.extend(load_errors)
    if metadata is None:
        return 0, 0, errors

    tile_format = metadata.get("format")
    tile_size = metadata.get("tile_size")
    levels = metadata.get("levels")
    if metadata.get("scheme") != "xyz":
        errors.append(f"{label}.metadata.scheme must be 'xyz'")
    for field, expected in (
        ("coordinate_scope", "sheet-local"),
        ("tile_origin", "top-left"),
        ("x_axis", "right"),
        ("y_axis", "down"),
        ("edge_padding", "transparent"),
    ):
        if metadata.get(field) != expected:
            errors.append(
                f"{label}.metadata.{field} must be {expected!r} for sheet-local XYZ"
            )
    templates = metadata.get("tiles")
    if (
        not isinstance(templates, list)
        or not templates
        or not all(
            isinstance(template, str)
            and all(token in template for token in ("{z}", "{x}", "{y}"))
            for template in templates
        )
    ):
        errors.append(
            f"{label}.metadata.tiles must contain XYZ URL template(s) with {{z}}, {{x}}, and {{y}}"
        )
    if coordinate_system is not None:
        metadata_crs = metadata.get(
            "coordinate_reference_system", metadata.get("coordinate_system")
        )
        if metadata_crs != coordinate_system:
            errors.append(
                f"{label}.metadata coordinate system mismatch: "
                f"manifest={coordinate_system!r}, metadata={metadata_crs!r}"
            )
    if not isinstance(tile_format, str) or not tile_format.isalnum():
        errors.append(f"{label}.metadata.format must be an alphanumeric extension")
        return 0, 0, errors
    if not _integer(tile_size) or tile_size <= 0:
        errors.append(f"{label}.metadata.tile_size must be a positive integer")
        return 0, 0, errors
    if tile_format.lower() != PUBLIC_TILE_FORMAT:
        errors.append(f"{label}.metadata.format must be 'webp' for public release tiles")
    if tile_size != PUBLIC_TILE_SIZE:
        errors.append(f"{label}.metadata.tile_size must be 512 for public release tiles")
    if not isinstance(levels, list) or not levels:
        errors.append(f"{label}.metadata.levels must be a non-empty array")
        return 0, 0, errors

    expected_paths: set[str] = set()
    level_metadata: dict[int, dict[str, Any]] = {}
    zooms: list[int] = []
    for level_index, level in enumerate(levels):
        level_label = f"{label}.metadata.levels[{level_index}]"
        if not isinstance(level, dict):
            errors.append(f"{level_label} must be an object")
            continue
        zoom, columns, rows = level.get("zoom"), level.get("columns"), level.get("rows")
        if not all(_integer(value) and value >= 0 for value in (zoom, columns, rows)):
            errors.append(f"{level_label} zoom/columns/rows must be non-negative integers")
            continue
        if columns == 0 or rows == 0:
            errors.append(f"{level_label} columns and rows must be positive")
            continue
        if zoom in level_metadata:
            errors.append(f"{level_label} duplicates zoom {zoom}")
            continue
        count = columns * rows
        if level.get("tile_count") != count:
            errors.append(
                f"{level_label}.tile_count mismatch: metadata={level.get('tile_count')!r}, "
                f"expected={count}"
            )
        paths = {
            f"{zoom}/{x}/{y}.{tile_format}"
            for x in range(columns)
            for y in range(rows)
        }
        expected_paths.update(paths)
        level_metadata[zoom] = level
        zooms.append(zoom)
        width, height = level.get("width"), level.get("height")
        if not all(_integer(value) and value > 0 for value in (width, height)):
            errors.append(f"{level_label} width and height must be positive integers")
        else:
            if not (tile_size * (columns - 1) < width <= tile_size * columns):
                errors.append(
                    f"{level_label}.width {width} is inconsistent with {columns} column(s) "
                    f"at {tile_size}px"
                )
            if not (tile_size * (rows - 1) < height <= tile_size * rows):
                errors.append(
                    f"{level_label}.height {height} is inconsistent with {rows} row(s) "
                    f"at {tile_size}px"
                )

        metadata_master = metadata.get("master")
        native_zoom = metadata.get("native_zoom")
        if (
            isinstance(metadata_master, dict)
            and _integer(metadata_master.get("width"))
            and _integer(metadata_master.get("height"))
            and _integer(native_zoom)
            and zoom <= native_zoom
        ):
            factor = 2 ** (native_zoom - zoom)
            expected_width = max(1, (metadata_master["width"] + factor - 1) // factor)
            expected_height = max(1, (metadata_master["height"] + factor - 1) // factor)
            if width != expected_width or height != expected_height:
                errors.append(
                    f"{level_label} sheet-local dimensions mismatch: "
                    f"expected={expected_width}x{expected_height}, actual={width}x{height}"
                )

    if zooms:
        ordered = sorted(zooms)
        if ordered != list(range(ordered[0], ordered[-1] + 1)):
            errors.append(f"{label}.metadata levels must use a contiguous zoom range")
        for field, expected in (("minzoom", ordered[0]), ("maxzoom", ordered[-1])):
            if metadata.get(field) != expected:
                errors.append(
                    f"{label}.metadata.{field} mismatch: metadata={metadata.get(field)!r}, "
                    f"levels={expected}"
                )
    if metadata.get("tile_count") != len(expected_paths):
        errors.append(
            f"{label}.metadata.tile_count mismatch: metadata={metadata.get('tile_count')!r}, "
            f"expected={len(expected_paths)}"
        )

    actual_paths = {
        path.relative_to(tiles_path).as_posix()
        for path in tiles_path.rglob(f"*.{tile_format}")
        if path.is_file()
    }
    for missing in sorted(expected_paths - actual_paths):
        errors.append(f"{label} missing tile: {missing}")
    for unexpected in sorted(actual_paths - expected_paths):
        errors.append(f"{label} unexpected tile: {unexpected}")

    tile_digests: list[tuple[str, str]] = []
    total_bytes = 0
    bytes_by_level: Counter[int] = Counter()
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValidationFailure("Pillow is required to inspect release tiles") from exc

    for relative in sorted(expected_paths & actual_paths):
        tile_path = tiles_path.joinpath(*PurePosixPath(relative).parts)
        byte_size = tile_path.stat().st_size
        total_bytes += byte_size
        zoom = int(PurePosixPath(relative).parts[0])
        bytes_by_level[zoom] += byte_size
        if byte_size <= 0:
            errors.append(f"{label} tile is empty: {relative}")
        tile_digests.append((relative, sha256_file(tile_path)))
        try:
            with Image.open(tile_path) as image:
                actual_size = image.size
                actual_format = (image.format or "").lower()
                pixel_errors = []
                parts = PurePosixPath(relative).parts
                level = level_metadata.get(zoom)
                if (
                    actual_size == (tile_size, tile_size)
                    and isinstance(level, dict)
                    and _integer(level.get("width"))
                    and _integer(level.get("height"))
                ):
                    pixel_errors = _tile_pixel_contract_errors(
                        image,
                        level_width=level["width"],
                        level_height=level["height"],
                        column=int(parts[1]),
                        row=int(PurePosixPath(parts[2]).stem),
                        tile_size=tile_size,
                        label=f"{label} tile {relative}",
                    )
            if actual_size != (tile_size, tile_size):
                errors.append(
                    f"{label} tile dimensions mismatch at {relative}: "
                    f"expected={tile_size}x{tile_size}, actual={actual_size[0]}x{actual_size[1]}"
                )
            if actual_format != tile_format.lower():
                errors.append(
                    f"{label} tile format mismatch at {relative}: "
                    f"metadata={tile_format}, actual={actual_format or 'unknown'}"
                )
            errors.extend(pixel_errors)
        except (OSError, ValueError) as exc:
            errors.append(f"{label} tile is unreadable at {relative}: {exc}")

    _optional_bytes(metadata, total_bytes, f"{label}.metadata", errors)
    for zoom, level in level_metadata.items():
        _optional_bytes(level, bytes_by_level[zoom], f"{label}.metadata.levels[z{zoom}]", errors)

    actual_set_hash = _tile_set_digest(tile_digests) if len(tile_digests) == len(expected_paths) else None
    metadata_set_hash = metadata.get("tile_set_sha256")
    if actual_set_hash is not None and metadata_set_hash != actual_set_hash:
        errors.append(
            f"{label}.metadata.tile_set_sha256 mismatch: metadata={metadata_set_hash!r}, "
            f"actual={actual_set_hash}"
        )
    manifest_set_hash = output.get("tile_set_sha256")
    if manifest_set_hash is None:
        errors.append(f"{label}.tile_set_sha256 is required for release evidence")
    elif metadata_set_hash != manifest_set_hash:
        errors.append(
            f"{label}.tile_set_sha256 mismatch: manifest={manifest_set_hash!r}, "
            f"metadata={metadata_set_hash!r}"
        )

    master = job.get("master")
    metadata_master = metadata.get("master")
    if isinstance(master, dict) and isinstance(metadata_master, dict):
        for field in ("path", "sha256", "width", "height"):
            if master.get(field) != metadata_master.get(field):
                errors.append(
                    f"{label}.metadata.master.{field} mismatch: "
                    f"manifest={master.get(field)!r}, metadata={metadata_master.get(field)!r}"
                )
    else:
        errors.append(f"{label}.metadata.master must match the manifest master")

    zoom = job.get("zoom")
    if isinstance(zoom, dict):
        for manifest_field, metadata_field in (
            ("min", "minzoom"),
            ("max", "maxzoom"),
            ("native", "native_zoom"),
        ):
            if zoom.get(manifest_field) != metadata.get(metadata_field):
                errors.append(
                    f"{label}.metadata.{metadata_field} mismatch: "
                    f"manifest={zoom.get(manifest_field)!r}, metadata={metadata.get(metadata_field)!r}"
                )
    bounds = job.get("bounds")
    if isinstance(bounds, dict):
        expected_bounds = [
            bounds.get("west"),
            bounds.get("south"),
            bounds.get("east"),
            bounds.get("north"),
        ]
        if metadata.get("bounds") != expected_bounds:
            errors.append(
                f"{label}.metadata.bounds mismatch: manifest={expected_bounds!r}, "
                f"metadata={metadata.get('bounds')!r}"
            )
    return len(tile_digests), total_bytes, errors


def _accepted_report(report: dict[str, Any], threshold: int) -> bool:
    failures = report.get("immediate_failures")
    no_failures = isinstance(failures, list) and all(
        isinstance(item, dict) and item.get("detected") is False for item in failures
    )
    score = report.get("total_score")
    scores = report.get("scores")
    score_contract = False
    if isinstance(scores, list) and scores and all(isinstance(item, dict) for item in scores):
        maxima = [item.get("maximum") for item in scores]
        values = [item.get("score") for item in scores]
        if all(_integer(value) for value in maxima + values):
            score_contract = (
                sum(maxima) == 100
                and all(value <= maximum for value, maximum in zip(values, maxima))
                and score == sum(values)
            )
    return (
        report.get("status") == "complete"
        and report.get("decision") == "accepted"
        and isinstance(score, int)
        and not isinstance(score, bool)
        and score >= threshold
        and report.get("acceptance_threshold") == threshold
        and score_contract
        and no_failures
    )


def validate_direct17_review_gate(
    job: dict[str, Any],
    index: int,
    vision_reports: dict[Path, dict[str, Any]],
    repo_root: Path,
) -> list[str]:
    """Independently prove release-state Direct17 Vision evidence."""

    sheet_id = job.get("sheet_id")
    if job.get("status") not in RELEASE_STATES or sheet_id not in DIRECT17_IDS:
        return []
    label = f"jobs[{index}] Direct17 {sheet_id!r}"
    errors: list[str] = []
    threshold = 90 if sheet_id in DIRECT17_STANDARD_REVIEW_IDS else 94
    required = 1 if sheet_id in DIRECT17_STANDARD_REVIEW_IDS else 2
    if job.get("acceptance_threshold") != threshold:
        errors.append(
            f"{label}.acceptance_threshold must be exactly {threshold}"
        )

    master = job.get("master")
    master_path = master.get("path") if isinstance(master, dict) else None
    master_sha = master.get("sha256") if isinstance(master, dict) else None
    if (
        not isinstance(master_path, str)
        or not isinstance(master_sha, str)
        or len(master_sha) != SHA256_LENGTH
        or master_sha != master_sha.lower()
    ):
        errors.append(f"{label}.master must carry an exact lowercase SHA-256 binding")

    expected_roles = set(INDEPENDENT_VISION_REVIEW_ROLES[:required])
    by_role: dict[str, dict[str, Any]] = {}
    for spec in job.get("inputs", []):
        if not isinstance(spec, dict) or not isinstance(spec.get("role"), str):
            continue
        role = spec["role"]
        if not role.startswith("independent-vision-review-"):
            continue
        if role not in expected_roles:
            errors.append(f"{label} has unexpected Vision review role {role!r}")
            continue
        if role in by_role:
            errors.append(f"{label} duplicates Vision review role {role!r}")
            continue
        by_role[role] = spec
    if set(by_role) != expected_roles:
        errors.append(
            f"{label} must hash exactly {sorted(expected_roles)!r}"
        )

    bound_reports: dict[Path, dict[str, Any]] = {}
    for role in INDEPENDENT_VISION_REVIEW_ROLES[:required]:
        spec = by_role.get(role)
        if spec is None:
            continue
        path, artifact_errors = _verify_hash(
            spec.get("path"),
            spec.get("sha256"),
            f"{label} {role}",
            repo_root,
            require_hash=True,
        )
        errors.extend(artifact_errors)
        if path is None or artifact_errors:
            continue
        if path in bound_reports:
            errors.append(f"{label} binds the same Vision report more than once")
            continue
        report = vision_reports.get(path)
        if report is None:
            errors.append(f"{label} {role} is not a validated Vision report")
            continue
        bound_reports[path] = report

    qa = job.get("qa")
    vision = qa.get("vision") if isinstance(qa, dict) else None
    primary_path: Path | None = None
    if isinstance(vision, dict) and isinstance(vision.get("report_path"), str):
        primary_path, path_errors = _portable_path(
            vision["report_path"], f"{label}.qa.vision.report_path", repo_root
        )
        errors.extend(path_errors)
    if primary_path not in bound_reports:
        errors.append(
            f"{label} primary qa.vision report must be one of its manifest-hashed review inputs"
        )

    reviewers: set[str] = set()
    for path, report in bound_reports.items():
        exact = {
            "job_id": job.get("id"),
            "image_path": master_path,
            "image_sha256": master_sha,
            "golden_reference": False,
            "review_mode": "blind-independent",
            "acceptance_threshold": threshold,
        }
        for field, expected in exact.items():
            if report.get(field) != expected:
                errors.append(
                    f"{label} review {path.name} {field} must be {expected!r}"
                )
        if not _accepted_report(report, threshold):
            errors.append(
                f"{label} review {path.name} is not accepted at score >= {threshold}"
            )
        reviewer = report.get("reviewer")
        if isinstance(reviewer, str):
            try:
                key = canonical_reviewer_identity(reviewer)
            except ValueError:
                errors.append(f"{label} review {path.name} has an empty reviewer")
            else:
                if key in reviewers:
                    errors.append(
                        f"{label} review {path.name} duplicates a reviewer identity"
                    )
                reviewers.add(key)
        else:
            errors.append(f"{label} review {path.name} has no reviewer")
    if len(reviewers) != required:
        errors.append(
            f"{label} has {len(reviewers)} distinct accepted reviewer(s); exactly {required} required"
        )
    return errors


def _golden_raw_binding_errors(
    job: dict[str, Any], repo_root: Path
) -> list[str]:
    """Require a distinct raw path whose exact bytes equal the Golden master."""

    job_id = job.get("id")
    master = job.get("master")
    if not isinstance(master, dict):
        return [f"golden job {job_id!r} has no master artifact"]
    raw_inputs = [
        item
        for item in job.get("inputs", [])
        if isinstance(item, dict) and item.get("role") == "golden-raw-output"
    ]
    if len(raw_inputs) != 1:
        return [
            f"golden job {job_id!r} must contain exactly one golden-raw-output input"
        ]
    raw = raw_inputs[0]
    errors: list[str] = []
    if raw.get("path") == master.get("path"):
        errors.append(
            f"golden job {job_id!r} raw and final artifacts must use distinct paths"
        )
    if raw.get("sha256") != master.get("sha256"):
        errors.append(
            f"golden job {job_id!r} raw and final SHA-256 digests must be identical"
        )
    raw_path, raw_errors = _verify_hash(
        raw.get("path"),
        raw.get("sha256"),
        f"golden job {job_id!r} golden-raw-output",
        repo_root,
        require_hash=True,
    )
    errors.extend(raw_errors)
    master_path, master_errors = _verify_hash(
        master.get("path"),
        master.get("sha256"),
        f"golden job {job_id!r} master",
        repo_root,
        require_hash=True,
    )
    errors.extend(master_errors)
    if (
        raw_path is not None
        and master_path is not None
        and raw_path.is_file()
        and master_path.is_file()
        and raw_path.read_bytes() != master_path.read_bytes()
    ):
        errors.append(f"golden job {job_id!r} raw and final bytes differ")
    return errors


def _golden_review_bindings(
    job: dict[str, Any], repo_root: Path, *, minimum: int
) -> tuple[dict[Path, str], list[str]]:
    """Return only manifest-hashed independent Vision review artifacts."""

    job_id = job.get("id")
    errors: list[str] = []
    records_by_role: dict[str, dict[str, Any]] = {}
    for item in job.get("inputs", []):
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            continue
        role = item["role"]
        if not role.startswith("independent-vision-review-"):
            continue
        if role not in INDEPENDENT_VISION_REVIEW_ROLES:
            errors.append(f"golden job {job_id!r} has unexpected Vision review role {role!r}")
            continue
        if role in records_by_role:
            errors.append(f"golden job {job_id!r} duplicates Vision review role {role!r}")
            continue
        records_by_role[role] = item
    missing = set(INDEPENDENT_VISION_REVIEW_ROLES) - set(records_by_role)
    if missing:
        errors.append(
            f"golden job {job_id!r} must hash exactly independent-vision-review-a and independent-vision-review-b"
        )
    records = [
        records_by_role[role]
        for role in INDEPENDENT_VISION_REVIEW_ROLES
        if role in records_by_role
    ]
    bound: dict[Path, str] = {}
    for index, record in enumerate(records):
        path, artifact_errors = _verify_hash(
            record.get("path"),
            record.get("sha256"),
            f"golden job {job_id!r} independent Vision review input {index + 1}",
            repo_root,
            require_hash=True,
        )
        errors.extend(artifact_errors)
        if (
            artifact_errors
            or path is None
            or not path.is_file()
            or not isinstance(record.get("sha256"), str)
        ):
            continue
        if path in bound:
            errors.append(
                f"golden job {job_id!r} binds the same Vision review path more than once"
            )
        else:
            bound[path] = record["sha256"]
    if len(bound) != 2:
        errors.append(
            f"golden job {job_id!r} has {len(bound)} valid manifest-bound independent "
            "Vision review artifact(s); exactly 2 required"
        )
    return bound, errors


def validate_golden_gate(
    manifest: dict[str, Any],
    vision_reports: dict[Path, dict[str, Any]],
    repo_root: Path,
    *,
    minimum_independent_reviews: int,
) -> tuple[str | None, int, list[str]]:
    """Require one accepted golden asset and distinct accepted reviewers."""

    errors: list[str] = []
    candidates: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    binding_errors: list[str] = []
    maximum_matching_reviewers = 0
    jobs = manifest.get("jobs", [])
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, dict) or job.get("status") not in RELEASE_STATES:
            continue
        job_id = job.get("id")
        master = job.get("master")
        image_path = master.get("path") if isinstance(master, dict) else None
        image_sha256 = master.get("sha256") if isinstance(master, dict) else None
        threshold = job.get("acceptance_threshold", 90)
        qa = job.get("qa")
        vision = qa.get("vision") if isinstance(qa, dict) else None
        primary_report: dict[str, Any] | None = None
        primary_path: Path | None = None
        if isinstance(vision, dict) and isinstance(vision.get("report_path"), str):
            primary_path, _ = _portable_path(
                vision["report_path"], "golden qa.vision.report_path", repo_root
            )
            if primary_path is not None:
                primary_report = vision_reports.get(primary_path)
        if (
            not isinstance(threshold, int)
            or threshold < 94
            or primary_report is None
            or primary_report.get("golden_reference") is not True
        ):
            continue
        review_bindings, review_binding_errors = _golden_review_bindings(
            job, repo_root, minimum=minimum_independent_reviews
        )
        if primary_path not in review_bindings:
            review_binding_errors.append(
                f"golden job {job_id!r} primary qa.vision report must be one of its two manifest-hashed reviews"
            )
        matching = [
            report
            for report_path, report in vision_reports.items()
            if report_path in review_bindings
            and report.get("job_id") == job_id
            and report.get("image_path") == image_path
            and report.get("image_sha256") == image_sha256
            and report.get("golden_reference") is True
            and report.get("review_mode") == "blind-independent"
            and _accepted_report(report, threshold)
        ]
        maximum_matching_reviewers = max(
            maximum_matching_reviewers,
            len(
                {
                    canonical_reviewer_identity(report["reviewer"])
                    for report in matching
                    if isinstance(report.get("reviewer"), str)
                    and report["reviewer"].strip()
                }
            ),
        )
        primary_is_golden = any(report is primary_report for report in matching)
        raw_errors = _golden_raw_binding_errors(job, repo_root)
        candidate_binding_errors = review_binding_errors + raw_errors
        if candidate_binding_errors:
            binding_errors.extend(candidate_binding_errors)
        elif matching and primary_is_golden:
            candidates.append((job, matching))

    if not candidates:
        return None, maximum_matching_reviewers, binding_errors or [
            "release requires an accepted blind-independent golden-reference job "
            "bound to the exact master SHA-256, with score >= 94 and no immediate failures"
        ]

    best_job, best_reports = max(
        candidates,
        key=lambda item: len(
            {
                canonical_reviewer_identity(report["reviewer"])
                for report in item[1]
                if isinstance(report.get("reviewer"), str)
            }
        ),
    )
    reviewers = {
        canonical_reviewer_identity(report["reviewer"])
        for report in best_reports
        if isinstance(report.get("reviewer"), str) and report["reviewer"].strip()
    }
    if len(reviewers) < minimum_independent_reviews:
        errors.append(
            f"golden job {best_job.get('id')!r} has {len(reviewers)} independent accepted "
            f"reviewer(s); {minimum_independent_reviews} required"
        )
    return best_job.get("id"), len(reviewers), errors


def _required_sheets(
    catalog: dict[str, Any],
    *,
    sheet_types: set[str],
    include_planned: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    sheets = catalog.get("sheets")
    if not isinstance(sheets, list):
        return [], ["map-sheets.json must contain a sheets array"]
    required: list[dict[str, Any]] = []
    seen: set[str] = set()
    available_types: set[str] = set()
    for index, sheet in enumerate(sheets):
        label = f"map-sheets.sheets[{index}]"
        if not isinstance(sheet, dict) or not isinstance(sheet.get("id"), str):
            errors.append(f"{label} must define a string id")
            continue
        sheet_id = sheet["id"]
        if sheet_id in seen:
            errors.append(f"map-sheets contains duplicate id {sheet_id!r}")
        seen.add(sheet_id)
        sheet_type = sheet.get("sheet_type")
        if isinstance(sheet_type, str):
            available_types.add(sheet_type)
        if sheet_types and sheet_type not in sheet_types:
            continue
        if not include_planned and (sheet.get("review_status") == "planned" or sheet.get("bounds") is None):
            continue
        required.append(sheet)
    for unknown_type in sorted(sheet_types - available_types):
        errors.append(f"required sheet type is not present in map-sheets: {unknown_type!r}")
    if not required:
        errors.append("map-sheets selection contains no eligible required sheets")
    return required, errors


def _job_resolution_contract_errors(
    job: dict[str, Any],
    index: int,
    expected_sheet: dict[str, Any],
    tile_profile: dict[str, Any],
    repo_root: Path,
) -> list[str]:
    """Compare one current release-state job with its derived sheet contract."""

    errors: list[str] = []
    label = f"jobs[{index}] ({job.get('id')!r})"
    bounds = job.get("bounds")
    actual_bounds = (
        [
            bounds.get("west"),
            bounds.get("south"),
            bounds.get("east"),
            bounds.get("north"),
        ]
        if isinstance(bounds, dict)
        else None
    )
    expected_bounds = expected_sheet["bounds"]
    if actual_bounds != expected_bounds:
        errors.append(
            f"{label} resolution contract bounds mismatch: "
            f"manifest={actual_bounds!r}, contract={expected_bounds!r}"
        )

    zoom = job.get("zoom")
    actual_zoom = (
        [zoom.get("min"), zoom.get("max"), zoom.get("native")]
        if isinstance(zoom, dict)
        else None
    )
    expected_zoom = [
        expected_sheet["zoom_range"][0],
        expected_sheet["zoom_range"][1],
        expected_sheet["native_zoom"],
    ]
    if actual_zoom != expected_zoom:
        errors.append(
            f"{label} resolution contract zoom mismatch: "
            f"manifest={actual_zoom!r}, contract={expected_zoom!r}"
        )

    master = job.get("master")
    actual_dimensions = (
        [master.get("width"), master.get("height")]
        if isinstance(master, dict)
        else None
    )
    expected_dimensions = [expected_sheet["width"], expected_sheet["height"]]
    if actual_dimensions != expected_dimensions:
        errors.append(
            f"{label} resolution contract master dimensions mismatch: "
            f"manifest={actual_dimensions!r}, contract={expected_dimensions!r}"
        )

    # Accepted jobs do not have to be tiled yet.  Once a current release-state
    # job has tile output, its public tile profile is part of sheet coverage.
    output = job.get("output")
    if isinstance(output, dict):
        metadata_raw = output.get("metadata_path")
        metadata: dict[str, Any] | None = None
        if isinstance(metadata_raw, str):
            metadata_path, _ = _portable_path(
                metadata_raw, f"{label}.output.metadata_path", repo_root
            )
            if metadata_path is not None and metadata_path.is_file():
                metadata, _ = _load_object(
                    metadata_path, f"{label}.output.metadata"
                )
        if metadata is None:
            errors.append(
                f"{label} resolution contract tiled metadata could not be validated"
            )
        else:
            for metadata_field, contract_field in (
                ("tile_size", "tile_size_px"),
                ("format", "public_format"),
            ):
                actual = metadata.get(metadata_field)
                expected = tile_profile.get(contract_field)
                if actual != expected:
                    errors.append(
                        f"{label} resolution contract tiled metadata {metadata_field} "
                        f"mismatch: metadata={actual!r}, contract={expected!r}"
                    )
    elif "output" in job or job.get("status") in {"tiled", "staging", "published"}:
        errors.append(
            f"{label} resolution contract tiled metadata could not be validated"
        )
    return errors


def validate_sheet_coverage(
    manifest: dict[str, Any],
    catalog: dict[str, Any],
    *,
    sheet_types: set[str],
    include_planned: bool,
    minimum_state: str,
    resolution_sheets: dict[str, dict[str, Any]] | None = None,
    tile_profile: dict[str, Any] | None = None,
    repo_root: Path = REPO_ROOT,
) -> tuple[int, int, list[str]]:
    required, errors = _required_sheets(
        catalog,
        sheet_types=sheet_types,
        include_planned=include_planned,
    )
    accepted_states = SHEET_STATE_COVERAGE[minimum_state]
    jobs = manifest.get("jobs", [])
    indexed_jobs = list(enumerate(jobs)) if isinstance(jobs, list) else []
    covered: set[str] = set()
    for sheet in required:
        sheet_id = sheet["id"]
        candidates = [
            (index, job)
            for index, job in indexed_jobs
            if isinstance(job, dict)
            and job.get("sheet_id") == sheet_id
            and job.get("status") in accepted_states
        ]
        candidate_errors: list[str] = []
        if resolution_sheets is None:
            if candidates:
                covered.add(sheet_id)
        else:
            expected_sheet = resolution_sheets.get(sheet_id)
            if expected_sheet is None:
                candidate_errors.append(
                    f"required sheet {sheet_id!r} has no derived bounded resolution contract"
                )
            else:
                for index, job in candidates:
                    contract_errors = _job_resolution_contract_errors(
                        job,
                        index,
                        expected_sheet,
                        tile_profile or {},
                        repo_root,
                    )
                    if not contract_errors:
                        covered.add(sheet_id)
                        break
                    candidate_errors.extend(contract_errors)
        if sheet_id not in covered:
            errors.extend(candidate_errors)
            contract_qualifier = (
                " matching the resolution contract" if resolution_sheets is not None else ""
            )
            errors.append(
                f"required sheet {sheet_id!r} ({sheet.get('sheet_type')}) has no "
                f"manifest job{contract_qualifier} at state {minimum_state!r} or later"
            )
    return len(required), sum(sheet["id"] in covered for sheet in required), errors


def validate_release(
    manifest_path: Path,
    *,
    manifest_schema_path: Path = DEFAULT_MANIFEST_SCHEMA,
    qa_schema_path: Path = DEFAULT_QA_SCHEMA,
    qa_dir: Path = DEFAULT_QA_DIR,
    map_sheets_path: Path = DEFAULT_MAP_SHEETS,
    resolution_contract_path: Path = DEFAULT_RESOLUTION_CONTRACT,
    repo_root: Path = REPO_ROOT,
    require_golden_accepted: bool = False,
    minimum_independent_reviews: int = 0,
    require_sheet_coverage: bool = False,
    required_sheet_types: set[str] | None = None,
    include_planned_sheets: bool = False,
    sheet_minimum_state: str = "accepted",
    strict_release: bool = False,
) -> dict[str, Any]:
    """Run release-integrity checks and return a JSON-serializable result."""

    if strict_release:
        require_golden_accepted = True
        minimum_independent_reviews = max(minimum_independent_reviews, 2)
        require_sheet_coverage = True

    errors: list[str] = []
    try:
        manifest, manifest_errors = validate_manifest(
            manifest_path,
            manifest_schema_path,
            check_files=False,
        )
    except ValidationFailure as exc:
        manifest, manifest_errors = None, [str(exc)]
    errors.extend(manifest_errors)

    result: dict[str, Any] = {
        "valid": False,
        "manifest": str(manifest_path),
        "jobs_checked": 0,
        "qa_reports_checked": 0,
        "tiles_checked": 0,
        "tile_bytes_checked": 0,
        "golden_job_id": None,
        "independent_reviews": 0,
        "required_sheets": 0,
        "covered_sheets": 0,
        "resolution_contract": str(resolution_contract_path),
        "resolution_contract_checked": strict_release and require_sheet_coverage,
        "errors": errors,
    }
    if manifest is None:
        return result

    jobs = manifest.get("jobs", [])
    automated_reference_paths: set[Path] = set()
    required_vision_paths: set[Path] = set()
    if isinstance(jobs, list):
        for job in jobs:
            if not isinstance(job, dict):
                continue
            for section, raw_path in _referenced_qa_paths(job):
                resolved, _ = _portable_path(
                    raw_path, f"qa.{section}.report_path", repo_root
                )
                if resolved is None:
                    continue
                if section == "automated":
                    automated_reference_paths.add(resolved)
                else:
                    required_vision_paths.add(resolved)
            inputs = job.get("inputs")
            if not isinstance(inputs, list):
                continue
            for artifact in inputs:
                if not isinstance(artifact, dict):
                    continue
                role = artifact.get("role")
                raw_path = artifact.get("path")
                if not (
                    isinstance(role, str)
                    and role.startswith("independent-vision-review-")
                    and isinstance(raw_path, str)
                ):
                    continue
                resolved, _ = _portable_path(
                    raw_path, f"inputs.{role}.path", repo_root
                )
                if resolved is not None:
                    required_vision_paths.add(resolved)

    qa_schema, qa_schema_errors = _load_object(qa_schema_path, "QA report schema")
    errors.extend(qa_schema_errors)
    reports: dict[Path, dict[str, Any]] = {}
    vision_reports: dict[Path, dict[str, Any]] = {}
    if qa_schema is not None:
        reports, vision_reports, report_errors = _load_qa_reports(
            qa_dir,
            qa_schema,
            repo_root,
            required_vision_paths=required_vision_paths,
        )
        errors.extend(report_errors)
    result["qa_reports_checked"] = len(reports)

    independent_vision_reports = {
        path: report
        for path, report in vision_reports.items()
        if path not in automated_reference_paths
    }
    if isinstance(jobs, list):
        for index, job in enumerate(jobs):
            if not isinstance(job, dict):
                continue
            result["jobs_checked"] += 1
            _, artifact_errors = validate_job_artifacts(job, index, repo_root)
            errors.extend(artifact_errors)
            _, qa_errors = validate_job_qa(
                job, index, reports, vision_reports, repo_root
            )
            errors.extend(qa_errors)
            errors.extend(
                validate_direct17_review_gate(
                    job, index, independent_vision_reports, repo_root
                )
            )
            tiles, tile_bytes, tile_errors = validate_tile_output(
                job,
                index,
                repo_root,
                manifest.get("coordinate_system")
                if isinstance(manifest.get("coordinate_system"), str)
                else None,
            )
            result["tiles_checked"] += tiles
            result["tile_bytes_checked"] += tile_bytes
            errors.extend(tile_errors)

    if require_golden_accepted or minimum_independent_reviews:
        golden_id, review_count, golden_errors = validate_golden_gate(
            manifest,
            independent_vision_reports,
            repo_root,
            minimum_independent_reviews=minimum_independent_reviews,
        )
        result["golden_job_id"] = golden_id
        result["independent_reviews"] = review_count
        errors.extend(golden_errors)

    if require_sheet_coverage:
        resolution_sheets: dict[str, dict[str, Any]] | None = None
        tile_profile: dict[str, Any] | None = None
        if strict_release:
            contract_result = validate_resolution_contract(
                resolution_contract_path,
                map_sheets_path,
                check_catalog=True,
            )
            errors.extend(
                f"resolution contract: {error}"
                for error in contract_result["errors"]
            )
            resolution_sheets = {
                sheet["sheet_id"]: sheet
                for sheet in contract_result["sheets"]
                if isinstance(sheet, dict) and isinstance(sheet.get("sheet_id"), str)
            }
            contract, _ = _load_object(
                resolution_contract_path, "resolution contract"
            )
            if contract is not None and isinstance(contract.get("tile_profile"), dict):
                tile_profile = contract["tile_profile"]

        catalog, catalog_errors = _load_object(map_sheets_path, "map-sheets catalog")
        errors.extend(catalog_errors)
        if catalog is not None:
            if catalog.get("coordinate_reference_system") != manifest.get("coordinate_system"):
                errors.append(
                    "map-sheets coordinate_reference_system does not match manifest "
                    f"coordinate_system: {catalog.get('coordinate_reference_system')!r} != "
                    f"{manifest.get('coordinate_system')!r}"
                )
            required, covered, coverage_errors = validate_sheet_coverage(
                manifest,
                catalog,
                sheet_types=required_sheet_types or set(),
                include_planned=include_planned_sheets,
                minimum_state=sheet_minimum_state,
                resolution_sheets=resolution_sheets,
                tile_profile=tile_profile,
                repo_root=repo_root,
            )
            result["required_sheets"] = required
            result["covered_sheets"] = covered
            errors.extend(coverage_errors)

    result["valid"] = not errors
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--manifest-schema", type=Path, default=DEFAULT_MANIFEST_SCHEMA)
    parser.add_argument("--qa-schema", type=Path, default=DEFAULT_QA_SCHEMA)
    parser.add_argument("--qa-dir", type=Path, default=DEFAULT_QA_DIR)
    parser.add_argument("--map-sheets", type=Path, default=DEFAULT_MAP_SHEETS)
    parser.add_argument(
        "--resolution-contract",
        type=Path,
        default=DEFAULT_RESOLUTION_CONTRACT,
        help="resolution contract enforced by --strict-release",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--require-golden-accepted",
        action="store_true",
        help="require an accepted golden-reference job scoring at least 94",
    )
    parser.add_argument(
        "--minimum-independent-reviews",
        type=int,
        default=0,
        metavar="COUNT",
        help="require COUNT distinct accepted reviewers for the golden image",
    )
    parser.add_argument(
        "--require-sheet-coverage",
        action="store_true",
        help="require every eligible map-sheets entry to have an accepted-or-later job",
    )
    parser.add_argument(
        "--required-sheet-type",
        action="append",
        default=[],
        metavar="TYPE",
        help="limit sheet coverage to TYPE (repeatable; default: every eligible type)",
    )
    parser.add_argument(
        "--include-planned-sheets",
        action="store_true",
        help="also require blocked/planned map sheets that have no production bounds",
    )
    parser.add_argument(
        "--sheet-minimum-state",
        choices=tuple(SHEET_STATE_COVERAGE),
        default="accepted",
    )
    parser.add_argument(
        "--strict-release",
        action="store_true",
        help=(
            "enable golden acceptance, two independent reviews, and "
            "resolution-contract sheet coverage"
        ),
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.minimum_independent_reviews < 0:
        parser.error("--minimum-independent-reviews must be non-negative")

    require_golden = args.require_golden_accepted or args.strict_release
    minimum_reviews = args.minimum_independent_reviews
    require_coverage = args.require_sheet_coverage or args.strict_release
    if args.strict_release:
        minimum_reviews = max(minimum_reviews, 2)

    try:
        result = validate_release(
            args.manifest,
            manifest_schema_path=args.manifest_schema,
            qa_schema_path=args.qa_schema,
            qa_dir=args.qa_dir,
            map_sheets_path=args.map_sheets,
            resolution_contract_path=args.resolution_contract,
            repo_root=args.repo_root,
            require_golden_accepted=require_golden,
            minimum_independent_reviews=minimum_reviews,
            require_sheet_coverage=require_coverage,
            required_sheet_types=set(args.required_sheet_type),
            include_planned_sheets=args.include_planned_sheets,
            sheet_minimum_state=args.sheet_minimum_state,
            strict_release=args.strict_release,
        )
    except (OSError, ValidationFailure) as exc:
        result = {
            "valid": False,
            "manifest": str(args.manifest),
            "errors": [str(exc)],
        }

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["valid"]:
        print(f"Map release validation passed: {args.manifest}")
        print(
            f"  Jobs={result['jobs_checked']}, QA reports={result['qa_reports_checked']}, "
            f"tiles={result['tiles_checked']}, bytes={result['tile_bytes_checked']}"
        )
        if require_golden:
            print(
                f"  Golden={result['golden_job_id']}, "
                f"independent reviews={result['independent_reviews']}"
            )
        if require_coverage:
            print(
                f"  Sheet coverage={result['covered_sheets']}/{result['required_sheets']} "
                f"at {args.sheet_minimum_state}+"
            )
    else:
        print(f"Map release validation failed: {args.manifest}", file=sys.stderr)
        for error in result["errors"]:
            print(f"- {error}", file=sys.stderr)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
