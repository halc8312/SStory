#!/usr/bin/env python3
"""Produce fail-closed automated QA evidence for one Phase 5 map master.

This auditor does not infer geography from decorative pixels.  It requires a
hash-locked control/observed mask pair for both land/sea and transport, then
computes the locked metrics itself.  Missing evidence is therefore a hard
failure, not an implicit pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from build_phase5_assets import (
    AUTOMATED_QA_GENERATOR_ID,
    CANONICAL_RENDER_SOURCE_KIND,
    CANONICAL_GEOJSON_SOURCES,
    CANONICAL_RENDERER_PATH,
    DEFAULT_AUTOMATED_QA_SCHEMA,
    DEFAULT_BASE_MANIFEST,
    DEFAULT_CANONICAL_CONTROL_INDEX,
    DEFAULT_CONTRACT,
    DEFAULT_PHASE5_MATERIAL_ATLAS,
    DEFAULT_MAP_SHEETS,
    INTERNAL_CANONICAL_CONTEXT_KEY,
    INTERNAL_GOLDEN_STYLE_KEY,
    MAXIMUM_RGB_MEAN_DIFFERENCE,
    MAXIMUM_RGB_P95_DIFFERENCE,
    MINIMUM_ALLOWED_OVERLAP_SSIM,
    MINIMUM_LAND_SEA_MATCH_RATIO,
    MINIMUM_TRANSPORT_WITHIN_TOLERANCE_RATIO,
    Phase5BuildError,
    _validate_schema_instance,
    canonical_render_context,
    image_properties,
    job_id_for_sheet,
    land_sea_match_ratio,
    load_binary_mask,
    load_contract,
    load_source_index,
    provenance_artifact_record,
    recompute_seam_evidence,
    repo_path,
    sha256_file,
    transport_within_tolerance_ratios,
    unpainted_band_metrics,
    validate_automated_qa_report,
    verify_manifest_golden_style,
    verify_hashed_file,
    verify_master_provenance,
)
from production_common import ValidationFailure, dump_json, utc_now
from render_phase5_parent_control_masks import (
    ParentControlError,
    load_validated_parent_control_bundle,
)


SCHEMA_URL = "https://sstory.example/schemas/phase5-automated-qa.schema.json"
PARENT_CONTROL_INDEX_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-parent-control-index.schema.json"
)
PARENT_CONTROL_REPORT_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-parent-control-report.schema.json"
)
EXPECTED_PARENT_SHEET_IDS = (
    "sheet_world",
    "sheet_continent_elysion",
    "sheet_continent_lumiera",
    "sheet_continent_chaos_ria",
    "sheet_continent_atlantis",
    "sheet_continent_grimoire",
)
EXPECTED_PARENT_CONTROL_ROLES = ("land_sea_control", "transport_control")
EXPECTED_PARENT_SOURCE_ROLES = (
    "landmasses",
    "regions",
    "terrain",
    "hydrography",
    "transport",
    "settlements",
)
EXPECTED_PARENT_EXECUTABLE_ROLES = (
    "generator",
    "production-common",
    "canonical-source-contract",
    "resolution-contract-validator",
)
EXPECTED_PARENT_SCHEMA_ROLES = ("index-schema", "report-schema")
EXPECTED_PARENT_EXECUTABLE_PATHS = {
    "generator": Path(__file__).resolve().with_name(
        "render_phase5_parent_control_masks.py"
    ),
    "production-common": Path(__file__).resolve().with_name("production_common.py"),
    "canonical-source-contract": Path(__file__).resolve().with_name(
        "render_world_master.py"
    ),
    "resolution-contract-validator": Path(__file__).resolve().with_name(
        "validate_resolution_contract.py"
    ),
}
EXPECTED_PARENT_SCHEMA_PATHS = {
    "index-schema": PARENT_CONTROL_INDEX_SCHEMA,
    "report-schema": PARENT_CONTROL_REPORT_SCHEMA,
}


def artifact(path: Path) -> dict[str, str]:
    return {"path": repo_path(path), "sha256": sha256_file(path)}


def _same_artifact(first: Any, second: Any) -> bool:
    return (
        isinstance(first, dict)
        and isinstance(second, dict)
        and first.get("path") == second.get("path")
        and first.get("sha256") == second.get("sha256")
    )


def _verify_composite_observed_provenance(
    *,
    sheet_id: str,
    provenance_path: Path,
    provenance: dict[str, Any],
    child_source_index_path: Path,
    land_observed_spec: dict[str, str],
    route_observed_spec: dict[str, str],
) -> None:
    report = _load_json_object(provenance_path, f"{sheet_id} provenance report")
    inputs = report.get("inputs")
    if not isinstance(inputs, dict):
        raise Phase5BuildError(f"{sheet_id} provenance report inputs are missing")
    source_index_spec = artifact(child_source_index_path.resolve())
    if not _same_artifact(inputs.get("source_index"), source_index_spec):
        raise Phase5BuildError(
            f"{sheet_id} provenance report does not hash-bind the audited child source index"
        )
    verify_hashed_file(source_index_spec, f"{sheet_id} child source index")

    if provenance.get("kind") != "deterministic-parent-composite":
        raise Phase5BuildError(
            f"{sheet_id} observed masks require deterministic-parent-composite provenance"
        )
    observed = provenance.get("observed_masks")
    if not isinstance(observed, dict) or set(observed) != {"land_sea", "transport"}:
        raise Phase5BuildError(
            f"{sheet_id} provenance must hash-bind exactly two observed masks"
        )
    for expected, role in (
        (land_observed_spec, "land_sea"),
        (route_observed_spec, "transport"),
    ):
        if not _same_artifact(observed.get(role), expected):
            raise Phase5BuildError(
                f"{sheet_id} {role} observed mask is not the provenance-bound artifact"
            )
        verify_hashed_file(expected, f"{sheet_id} provenance-bound {role} observation")

    native_base = provenance.get("canonical_native_base")
    if not isinstance(native_base, dict):
        raise Phase5BuildError(f"{sheet_id} canonical native-base provenance is missing")
    expected_artifacts = {
        "renderer": artifact(CANONICAL_RENDERER_PATH),
        "resolution_contract": artifact(DEFAULT_CONTRACT),
        "material_atlas": artifact(DEFAULT_PHASE5_MATERIAL_ATLAS),
    }
    for role, expected in expected_artifacts.items():
        if not _same_artifact(native_base.get(role), expected):
            raise Phase5BuildError(
                f"{sheet_id} canonical native-base {role} is not the repository anchor"
            )
    canonical_sources = native_base.get("canon_sources")
    expected_sources = [
        {"role": role, **artifact(path)}
        for role, path in CANONICAL_GEOJSON_SOURCES.items()
    ]
    if canonical_sources != expected_sources:
        raise Phase5BuildError(
            f"{sheet_id} canonical native-base sources differ from repository anchors"
        )
    if (
        native_base.get("source_coordinates_modified") is not False
        or native_base.get("world_crop_or_upscale_used") is not False
    ):
        raise Phase5BuildError(
            f"{sheet_id} canonical native-base provenance permits coordinate mutation"
        )


def _verify_canonical_mask_bindings(
    *,
    sheet_id: str,
    provenance_path: Path,
    control_index_path: Path,
    land_control_spec: dict[str, str],
    land_observed_spec: dict[str, str],
    route_control_spec: dict[str, str],
    route_observed_spec: dict[str, str],
) -> None:
    try:
        control_index = json.loads(control_index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase5BuildError(
            f"cannot read canonical control index {control_index_path}: {exc}"
        ) from exc
    matches = [
        item
        for item in control_index.get("sheets", [])
        if isinstance(item, dict) and item.get("sheet_id") == sheet_id
    ]
    if len(matches) != 1:
        raise Phase5BuildError(
            f"canonical control index must contain exactly one {sheet_id!r} record"
        )
    controls = matches[0].get("qa_controls")
    if not isinstance(controls, dict):
        raise Phase5BuildError(f"{sheet_id} canonical controls are missing")
    for supplied, key, label in (
        (land_control_spec, "land_sea_control", "land/sea"),
        (route_control_spec, "transport_control", "transport"),
    ):
        expected = controls.get(key)
        if not _same_artifact(supplied, expected):
            raise Phase5BuildError(
                f"{sheet_id} {label} control is not the hash-locked control-index artifact"
            )

    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        renderer_report_spec = provenance["inputs"]["renderer_report"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise Phase5BuildError(
            f"{sheet_id} canonical provenance lacks renderer_report binding"
        ) from exc
    renderer_report_path, _ = verify_hashed_file(
        renderer_report_spec, f"{sheet_id} canonical renderer report"
    )
    try:
        renderer_report = json.loads(
            renderer_report_path.read_text(encoding="utf-8")
        )
        outputs = renderer_report["outputs"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise Phase5BuildError(
            f"{sheet_id} canonical renderer report lacks observed-mask outputs"
        ) from exc
    for supplied, key, label in (
        (land_observed_spec, "observed_land_sea_mask", "land/sea"),
        (route_observed_spec, "observed_transport_mask", "transport"),
    ):
        expected = outputs.get(key) if isinstance(outputs, dict) else None
        if not _same_artifact(supplied, expected):
            raise Phase5BuildError(
                f"{sheet_id} {label} observed mask is not the renderer output artifact"
            )
    if (
        land_control_spec["path"] == land_observed_spec["path"]
        or route_control_spec["path"] == route_observed_spec["path"]
    ):
        raise Phase5BuildError(
            f"{sheet_id} observed masks must be independently rendered paths, not control copies"
        )


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase5BuildError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Phase5BuildError(f"{label} must contain a JSON object")
    return value


def _strict_role_records(
    records: Any,
    *,
    expected_roles: tuple[str, ...],
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise Phase5BuildError(f"{label} must be an array of objects")
    actual_roles = tuple(item.get("role") for item in records)
    if actual_roles != expected_roles or len(set(actual_roles)) != len(actual_roles):
        raise Phase5BuildError(
            f"{label} role set/order mismatch: "
            f"expected={list(expected_roles)!r}, actual={list(actual_roles)!r}"
        )
    return records


def _verify_parent_index_inputs(
    inputs: Any,
    *,
    contract_path: Path,
    catalog_path: Path,
) -> None:
    if not isinstance(inputs, dict):
        raise Phase5BuildError("parent control index inputs must be an object")
    for key, expected_path, label in (
        ("resolution_contract", contract_path, "resolution contract"),
        ("map_sheets", catalog_path, "map-sheets catalog"),
    ):
        expected = artifact(expected_path.resolve())
        if not _same_artifact(inputs.get(key), expected):
            raise Phase5BuildError(
                f"parent control index {label} does not match the audited input"
            )
        verify_hashed_file(inputs[key], f"parent control index {label}")

    role_groups = (
        (
            "canonical_sources",
            EXPECTED_PARENT_SOURCE_ROLES,
            "parent control canonical sources",
        ),
        (
            "executable_inputs",
            EXPECTED_PARENT_EXECUTABLE_ROLES,
            "parent control executable inputs",
        ),
        (
            "validation_schemas",
            EXPECTED_PARENT_SCHEMA_ROLES,
            "parent control validation schemas",
        ),
    )
    for key, expected_roles, label in role_groups:
        records = _strict_role_records(
            inputs.get(key), expected_roles=expected_roles, label=label
        )
        for record in records:
            expected_paths = (
                EXPECTED_PARENT_EXECUTABLE_PATHS
                if key == "executable_inputs"
                else EXPECTED_PARENT_SCHEMA_PATHS
                if key == "validation_schemas"
                else None
            )
            if expected_paths is not None:
                expected = artifact(expected_paths[record["role"]])
                if not _same_artifact(record, expected):
                    raise Phase5BuildError(
                        f"{label}/{record['role']} is not the expected executable input"
                    )
            verify_hashed_file(record, f"{label}/{record['role']}")


def _verify_parent_mask_bindings(
    *,
    sheet_id: str,
    control_index_path: Path,
    contract_path: Path,
    catalog_path: Path,
    catalog_by_id: dict[str, dict[str, Any]],
    contracts_by_id: dict[str, dict[str, Any]],
    land_control_spec: dict[str, str],
    land_observed_spec: dict[str, str],
    route_control_spec: dict[str, str],
    route_observed_spec: dict[str, str],
) -> dict[str, dict[str, str]]:
    """Bind a composite parent to the independent six-parent control bundle."""

    control_index_path = control_index_path.resolve()
    repo_path(control_index_path)
    try:
        index, report = load_validated_parent_control_bundle(control_index_path)
    except ParentControlError as exc:
        raise Phase5BuildError(f"parent control bundle failed semantic audit: {exc}") from exc
    _validate_schema_instance(
        index, PARENT_CONTROL_INDEX_SCHEMA, "parent control index"
    )
    report_path = control_index_path.with_name("report.json")
    _validate_schema_instance(
        report, PARENT_CONTROL_REPORT_SCHEMA, "parent control report"
    )
    index_spec = artifact(control_index_path)
    if not _same_artifact(report.get("index"), index_spec):
        raise Phase5BuildError("parent control report does not hash-lock its index")
    if report.get("inputs") != index.get("inputs"):
        raise Phase5BuildError("parent control report inputs differ from its index")
    if report.get("summary") != index.get("summary"):
        raise Phase5BuildError("parent control report summary differs from its index")
    _verify_parent_index_inputs(
        index.get("inputs"),
        contract_path=contract_path,
        catalog_path=catalog_path,
    )

    sheets = index.get("sheets")
    if not isinstance(sheets, list):
        raise Phase5BuildError("parent control index sheets must be an array")
    actual_ids = tuple(
        item.get("sheet_id") if isinstance(item, dict) else None for item in sheets
    )
    if actual_ids != EXPECTED_PARENT_SHEET_IDS or len(set(actual_ids)) != len(actual_ids):
        raise Phase5BuildError(
            "parent control index sheet ID set/order mismatch: "
            f"expected={list(EXPECTED_PARENT_SHEET_IDS)!r}, actual={list(actual_ids)!r}"
        )

    outputs = report.get("outputs")
    if not isinstance(outputs, list) or not all(isinstance(item, dict) for item in outputs):
        raise Phase5BuildError("parent control report outputs must be an array")
    output_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for item in outputs:
        key = (str(item.get("sheet_id")), str(item.get("role")))
        if key in output_by_key:
            raise Phase5BuildError(f"parent control report duplicates output {key!r}")
        output_by_key[key] = item
    expected_output_keys = {
        (parent_id, role)
        for parent_id in EXPECTED_PARENT_SHEET_IDS
        for role in EXPECTED_PARENT_CONTROL_ROLES
    }
    if set(output_by_key) != expected_output_keys:
        raise Phase5BuildError(
            "parent control report output ID/role set mismatch: "
            f"missing={sorted(expected_output_keys - set(output_by_key))!r}, "
            f"extra={sorted(set(output_by_key) - expected_output_keys)!r}"
        )

    selected_controls: dict[str, dict[str, Any]] | None = None
    for record in sheets:
        assert isinstance(record, dict)
        parent_id = record["sheet_id"]
        catalog_sheet = catalog_by_id.get(parent_id)
        contract = contracts_by_id.get(parent_id)
        if not isinstance(catalog_sheet, dict) or not isinstance(contract, dict):
            raise Phase5BuildError(
                f"parent control index references unavailable sheet {parent_id!r}"
            )
        for key, actual in (
            ("sheet_type", catalog_sheet.get("sheet_type")),
            ("parent_id", catalog_sheet.get("parent_id")),
            ("source_feature_id", catalog_sheet.get("source_feature_id")),
            ("bounds", contract.get("bounds")),
            ("native_zoom", contract.get("native_zoom")),
            ("pixel_bounds", contract.get("pixel_bounds")),
            ("width", contract.get("width")),
            ("height", contract.get("height")),
        ):
            if record.get(key) != actual:
                raise Phase5BuildError(
                    f"{parent_id} parent control {key} mismatch: "
                    f"index={record.get(key)!r}, contract={actual!r}"
                )
        controls = record.get("qa_controls")
        if not isinstance(controls, dict) or tuple(controls) != EXPECTED_PARENT_CONTROL_ROLES:
            raise Phase5BuildError(
                f"{parent_id} parent control role set/order is invalid"
            )
        expected_size = (contract["width"], contract["height"])
        for role in EXPECTED_PARENT_CONTROL_ROLES:
            control = controls[role]
            if not _same_artifact(control, output_by_key[(parent_id, role)]):
                raise Phase5BuildError(
                    f"{parent_id}/{role} differs between parent index and report"
                )
            control_path, _ = verify_hashed_file(
                control, f"parent control {parent_id}/{role}"
            )
            size, image_format, color_mode = image_properties(
                control_path, f"parent control {parent_id}/{role}"
            )
            if size != expected_size or image_format != "PNG" or color_mode != "L":
                raise Phase5BuildError(
                    f"parent control {parent_id}/{role} dimensions or encoding mismatch"
                )
            if (
                control.get("width") != expected_size[0]
                or control.get("height") != expected_size[1]
                or control.get("format") != "PNG"
                or control.get("color_mode") != "L"
            ):
                raise Phase5BuildError(
                    f"parent control {parent_id}/{role} metadata is stale"
                )
        if parent_id == sheet_id:
            selected_controls = controls

    if selected_controls is None:
        raise Phase5BuildError(
            f"parent control index must contain exactly one {sheet_id!r} record"
        )
    for supplied, observed, role, label in (
        (
            land_control_spec,
            land_observed_spec,
            "land_sea_control",
            "land/sea",
        ),
        (
            route_control_spec,
            route_observed_spec,
            "transport_control",
            "transport",
        ),
    ):
        expected = selected_controls[role]
        if not _same_artifact(supplied, expected):
            raise Phase5BuildError(
                f"{sheet_id} {label} control is not the hash-locked parent-index artifact"
            )
        if (
            supplied.get("path") == observed.get("path")
            or supplied.get("sha256") == observed.get("sha256")
        ):
            raise Phase5BuildError(
                f"{sheet_id} {label} observed mask must be independently rendered, "
                "not the parent control or a byte-identical copy"
            )
        _, control_image = load_binary_mask(
            supplied,
            label=f"{sheet_id} {label} parent control identity check",
            expected_size=(
                int(selected_controls[role]["width"]),
                int(selected_controls[role]["height"]),
            ),
        )
        _, observed_image = load_binary_mask(
            observed,
            label=f"{sheet_id} {label} observed identity check",
            expected_size=control_image.size,
        )
        try:
            if control_image.tobytes() == observed_image.tobytes():
                raise Phase5BuildError(
                    f"{sheet_id} {label} observed mask decodes identically to its "
                    "parent control and is therefore control-derived"
                )
        finally:
            control_image.close()
            observed_image.close()
    return {"index": index_spec, "report": artifact(report_path)}


def audit_phase5_master(
    *,
    sheet_id: str,
    source_kind: str,
    master_path: Path,
    provenance_path: Path,
    land_sea_control_path: Path,
    land_sea_observed_path: Path,
    transport_control_path: Path,
    transport_observed_path: Path,
    transport_tolerance_px: int,
    contract_path: Path = DEFAULT_CONTRACT,
    catalog_path: Path = DEFAULT_MAP_SHEETS,
    child_source_index_path: Path | None = None,
    parent_control_index_path: Path | None = None,
    base_manifest_path: Path = DEFAULT_BASE_MANIFEST,
    canonical_control_index_path: Path = DEFAULT_CANONICAL_CONTROL_INDEX,
) -> dict[str, Any]:
    _, catalog_by_id, derived = load_contract(contract_path, catalog_path)
    if sheet_id not in catalog_by_id or sheet_id not in derived["sheets"]:
        raise Phase5BuildError(f"unknown bounded Phase 5 sheet: {sheet_id!r}")
    sheet = catalog_by_id[sheet_id]
    contract = derived["sheets"][sheet_id]
    allowed_kinds = (
        {"composite_master"}
        if sheet.get("sheet_type") in {"world", "continent"}
        else {"master", CANONICAL_RENDER_SOURCE_KIND}
    )
    if source_kind not in allowed_kinds:
        raise Phase5BuildError(
            f"{sheet_id} requires source kind in {sorted(allowed_kinds)!r}, "
            f"found {source_kind!r}"
        )
    if source_kind == "composite_master" and child_source_index_path is None:
        raise Phase5BuildError(
            "composite audit requires --child-source-index with reviewed child sources"
        )
    if source_kind == "composite_master" and parent_control_index_path is None:
        raise Phase5BuildError(
            "composite audit requires --parent-control-index with independent controls"
        )

    master_path = master_path.resolve()
    provenance_path = provenance_path.resolve()
    if not master_path.is_file() or not provenance_path.is_file():
        raise Phase5BuildError("master and provenance report must both exist")
    master_spec = artifact(master_path)
    provenance_spec = artifact(provenance_path)
    entry = {
        "sheet_id": sheet_id,
        "kind": source_kind,
        **master_spec,
        "provenance_report": provenance_spec,
    }

    if source_kind == CANONICAL_RENDER_SOURCE_KIND:
        try:
            provenance_document = json.loads(provenance_path.read_text(encoding="utf-8"))
            golden_style = provenance_document["inputs"]["golden_style"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise Phase5BuildError(
                f"{sheet_id} canonical provenance does not expose inputs.golden_style"
            ) from exc
        if not isinstance(golden_style, dict):
            raise Phase5BuildError(
                f"{sheet_id} canonical provenance inputs.golden_style must be an artifact"
            )
        golden_evidence = verify_manifest_golden_style(
            golden_style, base_manifest_path.resolve()
        )
        entry[INTERNAL_GOLDEN_STYLE_KEY] = golden_style
        entry[INTERNAL_CANONICAL_CONTEXT_KEY] = canonical_render_context(
            catalog_path=catalog_path.resolve(),
            contract_path=contract_path.resolve(),
            control_index_path=canonical_control_index_path.resolve(),
            golden_evidence=golden_evidence,
        )

    sources: dict[str, dict[str, Any]] | None = None
    if child_source_index_path is not None:
        sources, _, _ = load_source_index(
            child_source_index_path, set(derived["sheets"])
        )
    verify_master_provenance(
        entry,
        sheet=sheet,
        master_path=master_spec["path"],
        contract=contract,
        catalog_by_id=catalog_by_id,
        sources=sources,
    )

    size, image_format, color_mode = image_properties(master_path, f"{sheet_id} master")
    expected_size = (contract["width"], contract["height"])
    if size != expected_size:
        raise Phase5BuildError(
            f"{sheet_id} master dimensions mismatch: expected={expected_size}, actual={size}"
        )
    if image_format != "PNG" or color_mode != "RGB":
        raise Phase5BuildError(f"{sheet_id} master must be a native RGB PNG")

    bands = unpainted_band_metrics(master_path, f"{sheet_id} master")
    if any(bands.values()):
        raise Phase5BuildError(
            f"{sheet_id} master contains black/unpainted axis bands: {bands}"
        )
    record = provenance_artifact_record(provenance_path, sheet_id)
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        raise Phase5BuildError(f"{sheet_id} provenance lacks structured artifact details")
    seams = (
        []
        if source_kind in {"composite_master", CANONICAL_RENDER_SOURCE_KIND}
        else recompute_seam_evidence(
            provenance, label=f"{sheet_id} provenance.seams"
        )
    )

    land_control_spec = artifact(land_sea_control_path.resolve())
    land_observed_spec = artifact(land_sea_observed_path.resolve())
    route_control_spec = artifact(transport_control_path.resolve())
    route_observed_spec = artifact(transport_observed_path.resolve())
    parent_control_bundle: dict[str, dict[str, str]] | None = None
    if source_kind == "composite_master":
        assert parent_control_index_path is not None
        assert child_source_index_path is not None
        _verify_composite_observed_provenance(
            sheet_id=sheet_id,
            provenance_path=provenance_path,
            provenance=provenance,
            child_source_index_path=child_source_index_path,
            land_observed_spec=land_observed_spec,
            route_observed_spec=route_observed_spec,
        )
        parent_control_bundle = _verify_parent_mask_bindings(
            sheet_id=sheet_id,
            control_index_path=parent_control_index_path,
            contract_path=contract_path.resolve(),
            catalog_path=catalog_path.resolve(),
            catalog_by_id=catalog_by_id,
            contracts_by_id=derived["sheets"],
            land_control_spec=land_control_spec,
            land_observed_spec=land_observed_spec,
            route_control_spec=route_control_spec,
            route_observed_spec=route_observed_spec,
        )
    if source_kind == CANONICAL_RENDER_SOURCE_KIND:
        _verify_canonical_mask_bindings(
            sheet_id=sheet_id,
            provenance_path=provenance_path,
            control_index_path=canonical_control_index_path.resolve(),
            land_control_spec=land_control_spec,
            land_observed_spec=land_observed_spec,
            route_control_spec=route_control_spec,
            route_observed_spec=route_observed_spec,
        )
    _, land_control = load_binary_mask(
        land_control_spec,
        label=f"{sheet_id} land/sea control",
        expected_size=size,
    )
    _, land_observed = load_binary_mask(
        land_observed_spec,
        label=f"{sheet_id} land/sea observed",
        expected_size=size,
    )
    try:
        land_ratio = land_sea_match_ratio(land_control, land_observed)
    finally:
        land_control.close()
        land_observed.close()
    if land_ratio < MINIMUM_LAND_SEA_MATCH_RATIO:
        raise Phase5BuildError(
            f"{sheet_id} land/sea match {land_ratio:.6f} is below "
            f"{MINIMUM_LAND_SEA_MATCH_RATIO:.2f}"
        )

    _, route_control = load_binary_mask(
        route_control_spec,
        label=f"{sheet_id} transport control",
        expected_size=size,
    )
    _, route_observed = load_binary_mask(
        route_observed_spec,
        label=f"{sheet_id} transport observed",
        expected_size=size,
    )
    try:
        route_control_ratio, route_observed_ratio = transport_within_tolerance_ratios(
            route_control, route_observed, transport_tolerance_px
        )
    finally:
        route_control.close()
        route_observed.close()
    if (
        route_control_ratio < MINIMUM_TRANSPORT_WITHIN_TOLERANCE_RATIO
        or route_observed_ratio < MINIMUM_TRANSPORT_WITHIN_TOLERANCE_RATIO
    ):
        raise Phase5BuildError(
            f"{sheet_id} transport evidence is below the locked "
            f"{MINIMUM_TRANSPORT_WITHIN_TOLERANCE_RATIO:.2f} gate: "
            f"control={route_control_ratio:.6f}, observed={route_observed_ratio:.6f}"
        )

    master_sha = master_spec["sha256"]
    pixel_count = size[0] * size[1]
    report: dict[str, Any] = {
        "$schema": SCHEMA_URL,
        "schema_version": "1.0.0",
        "type": "sstory-phase5-automated-master-qa",
        "coordinate_reference_system": "EA-WORLD-1",
        "generated_by": AUTOMATED_QA_GENERATOR_ID,
        "job_id": job_id_for_sheet(sheet_id),
        "sheet_id": sheet_id,
        "status": "passed",
        "source_kind": source_kind,
        "master": {
            **master_spec,
            "width": size[0],
            "height": size[1],
            "format": image_format,
            "color_mode": color_mode,
        },
        "provenance_report": provenance_spec,
        "checks": {
            "dimensions": {
                "passed": True,
                "expected_width": expected_size[0],
                "expected_height": expected_size[1],
                "actual_width": size[0],
                "actual_height": size[1],
            },
            "encoding": {
                "passed": True,
                "expected_format": "PNG",
                "actual_format": image_format,
                "expected_color_mode": "RGB",
                "actual_color_mode": color_mode,
            },
            "digest": {
                "passed": True,
                "expected_sha256": master_sha,
                "actual_sha256": master_sha,
            },
            "coverage": {
                "passed": True,
                "algorithm": "provenance-destination-coverage-v1",
                "expected_pixel_count": pixel_count,
                "covered_pixel_count": pixel_count,
                "uncovered_pixel_count": 0,
                "overlap_pixel_count": 0,
            },
            "unpainted_bands": {
                "passed": True,
                "algorithm": "coverage-and-axis-band-scan-v1",
                "tested_fill_rgb": [0, 0, 0],
                **bands,
            },
            "seams": {
                "passed": True,
                "minimum_overlap_ssim": MINIMUM_ALLOWED_OVERLAP_SSIM,
                "maximum_rgb_mean_difference": MAXIMUM_RGB_MEAN_DIFFERENCE,
                "maximum_rgb_p95_difference": MAXIMUM_RGB_P95_DIFFERENCE,
                "expected_count": len(seams),
                "evaluated_count": len(seams),
                "minimum_observed_ssim": (
                    min(item["ssim"] for item in seams) if seams else None
                ),
                "maximum_observed_rgb_mean_difference": (
                    max(item["rgb_mean_abs_difference"] for item in seams)
                    if seams
                    else None
                ),
                "maximum_observed_rgb_p95_difference": (
                    max(item["rgb_p95_abs_difference"] for item in seams)
                    if seams
                    else None
                ),
                "evidence": seams,
            },
        },
        "geography": {
            "land_sea": {
                "passed": True,
                "control": land_control_spec,
                "observed": land_observed_spec,
                "minimum_match_ratio": MINIMUM_LAND_SEA_MATCH_RATIO,
                "match_ratio": land_ratio,
            },
            "transport": {
                "passed": True,
                "control": route_control_spec,
                "observed": route_observed_spec,
                "tolerance_px": transport_tolerance_px,
                "minimum_within_tolerance_ratio": (
                    MINIMUM_TRANSPORT_WITHIN_TOLERANCE_RATIO
                ),
                "control_within_tolerance_ratio": route_control_ratio,
                "observed_within_tolerance_ratio": route_observed_ratio,
            },
        },
        "created_at": utc_now(),
    }
    if parent_control_bundle is not None:
        report["parent_controls"] = parent_control_bundle
    _validate_schema_instance(report, DEFAULT_AUTOMATED_QA_SCHEMA, "automated QA report")
    validate_automated_qa_report(
        report,
        entry=entry,
        sheet=sheet,
        master_path=master_spec["path"],
        job_id=job_id_for_sheet(sheet_id),
        contract=contract,
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheet-id", required=True)
    parser.add_argument(
        "--source-kind",
        required=True,
        choices=("master", "composite_master", CANONICAL_RENDER_SOURCE_KIND),
    )
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--provenance-report", type=Path, required=True)
    parser.add_argument("--land-sea-control", type=Path, required=True)
    parser.add_argument("--land-sea-observed", type=Path, required=True)
    parser.add_argument("--transport-control", type=Path, required=True)
    parser.add_argument("--transport-observed", type=Path, required=True)
    parser.add_argument("--transport-tolerance-px", type=int, default=8)
    parser.add_argument("--resolution-contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--map-sheets", type=Path, default=DEFAULT_MAP_SHEETS)
    parser.add_argument("--child-source-index", type=Path)
    parser.add_argument(
        "--parent-control-index",
        type=Path,
        help="required independent six-parent control index for composite_master",
    )
    parser.add_argument("--base-manifest", type=Path, default=DEFAULT_BASE_MANIFEST)
    parser.add_argument(
        "--canonical-control-index",
        type=Path,
        default=DEFAULT_CANONICAL_CONTROL_INDEX,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = args.output.resolve()
        repo_path(output)
        if output.exists() and not args.force:
            raise Phase5BuildError(f"output already exists (use --force): {output}")
        report = audit_phase5_master(
            sheet_id=args.sheet_id,
            source_kind=args.source_kind,
            master_path=args.master,
            provenance_path=args.provenance_report,
            land_sea_control_path=args.land_sea_control,
            land_sea_observed_path=args.land_sea_observed,
            transport_control_path=args.transport_control,
            transport_observed_path=args.transport_observed,
            transport_tolerance_px=args.transport_tolerance_px,
            contract_path=args.resolution_contract,
            catalog_path=args.map_sheets,
            child_source_index_path=args.child_source_index,
            parent_control_index_path=args.parent_control_index,
            base_manifest_path=args.base_manifest,
            canonical_control_index_path=args.canonical_control_index,
        )
        dump_json(output, report)
        result = {
            "valid": True,
            "output": repo_path(output),
            "sha256": sha256_file(output),
            "sheet_id": args.sheet_id,
        }
        print(json.dumps(result, ensure_ascii=False) if args.as_json else result["output"])
        return 0
    except (OSError, Phase5BuildError, ValidationFailure, ValueError) as exc:
        result = {"valid": False, "error": str(exc)}
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
