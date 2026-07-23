#!/usr/bin/env python3
"""Assemble fail-closed Phase 5 continent/world composite record bundles.

``write_phase5_source_indexes.py`` deliberately accepts a compact record
shape.  This command is the evidence boundary immediately before that writer:
it proves that a deterministic build report, the exact immutable child source
index, automated QA, and one blind independent Vision review all describe the
same native composite bytes.

The two supported transitions are intentionally fixed::

    idx22: idx17 -> five continent composite records
    idx23: idx22 -> one world composite record

Expected evidence names are ``<sheet-id>.phase5.json`` below the automated
root and ``phase5-<sheet-core>-v1[-...].json`` below the Vision root.  Masters
are selected from the shared build report, not from caller-authored record
JSON.  Every selected and transitively referenced artifact must be a
trackable repository file.  Existing outputs are never replaced without
``--force``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import build_phase5_assets as phase5
import write_phase5_source_indexes as source_index_writer
from release_bound_artifact import (
    BoundArtifact,
    BoundArtifactError,
    assert_bindings_unchanged,
    bind_file,
)
from release_path_safety import ReleasePathError, require_trackable_path, same_path
from reviewer_identity import canonical_reviewer_identity


TOOL_ID = "sstory-map-production/assemble_phase5_composite_records.py@2"
BUNDLE_SCHEMA_VERSION = "1.0.0"
STAGE_BASE = {"idx22": "idx17", "idx23": "idx22"}
STAGE_EXPECTED_TYPES = {"idx22": "continent", "idx23": "world"}
COMPOSITE_KIND = "composite_master"
COMPOSITE_REVIEW_THRESHOLD = 90
COMPOSITE_REVIEW_COUNT = 1


class CompositeRecordBundleError(RuntimeError):
    """Raised when composite evidence cannot be proven complete and immutable."""


@dataclass(frozen=True)
class _BaseContext:
    index: BoundArtifact
    sources: dict[str, dict[str, Any]]
    golden_style: dict[str, str]
    golden_reviewers: frozenset[str]
    bindings: dict[str, BoundArtifact]


def _stable_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _json_object(binding: BoundArtifact, label: str) -> dict[str, Any]:
    try:
        return binding.json_object()
    except BoundArtifactError as exc:
        raise CompositeRecordBundleError(f"{label} is not valid JSON: {exc}") from exc


def _require_directory(raw_path: Path, label: str) -> Path:
    try:
        path, _ = require_trackable_path(raw_path, label=label, require_file=False)
    except ReleasePathError as exc:
        raise CompositeRecordBundleError(str(exc)) from exc
    if not path.is_dir():
        raise CompositeRecordBundleError(f"{label} must be a directory: {path}")
    return path


def _tracked_output(raw_path: Path) -> Path:
    try:
        path, _ = require_trackable_path(
            raw_path,
            label="composite-record bundle output",
            must_exist=False,
            require_file=False,
        )
    except ReleasePathError as exc:
        raise CompositeRecordBundleError(str(exc)) from exc
    if path.exists() and not path.is_file():
        raise CompositeRecordBundleError(
            f"composite-record bundle output is not a file: {path}"
        )
    return path


def _bind(raw_path: str | Path, label: str) -> BoundArtifact:
    try:
        return bind_file(raw_path, label=label, trackable=True)
    except (BoundArtifactError, OSError) as exc:
        raise CompositeRecordBundleError(str(exc)) from exc


def _merge_bindings(
    destination: dict[str, BoundArtifact], values: Iterable[BoundArtifact]
) -> None:
    for bound in values:
        existing = destination.get(bound.identity)
        if existing is not None and existing.sha256 != bound.sha256:
            raise CompositeRecordBundleError(
                f"artifact was bound to conflicting bytes: {bound.relative}"
            )
        destination[bound.identity] = bound


def _bind_graph(
    bindings: dict[str, BoundArtifact], roots: Iterable[BoundArtifact]
) -> None:
    roots = tuple(roots)
    _merge_bindings(bindings, roots)
    try:
        with phase5.bound_artifact_context(bindings):
            graph = phase5.bind_phase5_artifact_graph(roots)
    except phase5.Phase5BuildError as exc:
        raise CompositeRecordBundleError(str(exc)) from exc
    _merge_bindings(bindings, graph.values())


def _artifact(bound: BoundArtifact) -> dict[str, str]:
    return {"path": bound.relative, "sha256": bound.sha256}


def _bind_spec(
    value: Any,
    label: str,
    bindings: dict[str, BoundArtifact],
) -> BoundArtifact:
    if not isinstance(value, dict):
        raise CompositeRecordBundleError(f"{label} must be a path/sha256 object")
    path = value.get("path")
    claimed = value.get("sha256")
    if not isinstance(path, str) or not path:
        raise CompositeRecordBundleError(f"{label}.path must be a non-empty string")
    if (
        not isinstance(claimed, str)
        or len(claimed) != 64
        or claimed != claimed.lower()
        or any(character not in "0123456789abcdef" for character in claimed)
    ):
        raise CompositeRecordBundleError(
            f"{label}.sha256 must be a lowercase 64-character digest"
        )
    bound = _bind(path, label)
    if bound.sha256 != claimed:
        raise CompositeRecordBundleError(
            f"{label}.sha256 mismatch: report={claimed}, actual={bound.sha256}"
        )
    _merge_bindings(bindings, (bound,))
    return bound


def _require_exact_artifact(
    value: Any,
    expected: BoundArtifact,
    label: str,
    bindings: dict[str, BoundArtifact],
) -> BoundArtifact:
    actual = _bind_spec(value, label, bindings)
    if not same_path(actual.path, expected.path) or actual.sha256 != expected.sha256:
        raise CompositeRecordBundleError(
            f"{label} must lock exact artifact {expected.relative}"
        )
    return actual


def _catalog_contract() -> tuple[
    dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]
]:
    try:
        catalog, catalog_by_id, derived = phase5.load_contract(
            phase5.DEFAULT_CONTRACT, phase5.DEFAULT_MAP_SHEETS
        )
    except phase5.Phase5BuildError as exc:
        raise CompositeRecordBundleError(str(exc)) from exc
    contracts = derived.get("sheets") if isinstance(derived, dict) else None
    if not isinstance(contracts, dict):
        raise CompositeRecordBundleError("resolution contract lacks sheet entries")
    return catalog, catalog_by_id, contracts


def _catalog_order(catalog: dict[str, Any], ids: set[str]) -> list[str]:
    ordered = [
        sheet.get("id")
        for sheet in catalog.get("sheets", [])
        if isinstance(sheet, dict) and sheet.get("id") in ids
    ]
    if len(ordered) != len(ids) or set(ordered) != ids:
        raise CompositeRecordBundleError(
            "canonical catalog order does not cover the required sheet set"
        )
    return [str(value) for value in ordered]


def _raw_index_order(index: dict[str, Any], label: str) -> list[str]:
    sources = index.get("sources")
    if not isinstance(sources, list):
        raise CompositeRecordBundleError(f"{label}.sources must be an array")
    ids: list[str] = []
    for position, source in enumerate(sources):
        if not isinstance(source, dict) or not isinstance(source.get("sheet_id"), str):
            raise CompositeRecordBundleError(
                f"{label}.sources[{position}] lacks a sheet_id"
            )
        ids.append(source["sheet_id"])
    return ids


def _golden_reviewers_from_direct_sources(
    *,
    sources: dict[str, dict[str, Any]],
    golden_style: dict[str, str],
    bindings: dict[str, BoundArtifact],
) -> frozenset[str]:
    direct_ids = source_index_writer.EXPECTED_DIRECT_IDS
    direct_entries = [sources[sheet_id] for sheet_id in sorted(direct_ids)]
    selected_review_locks: tuple[tuple[str, str], ...] | None = None
    selected_specs: list[dict[str, str]] | None = None
    for position, entry in enumerate(direct_entries):
        if entry.get("kind") != phase5.CANONICAL_RENDER_SOURCE_KIND:
            raise CompositeRecordBundleError(
                f"base direct source {entry.get('sheet_id')!r} has the wrong kind"
            )
        provenance = _bind_spec(
            entry.get("provenance_report"),
            f"base direct provenance[{position}]",
            bindings,
        )
        report = _json_object(provenance, f"base direct provenance[{position}]")
        inputs = report.get("inputs")
        if not isinstance(inputs, dict):
            raise CompositeRecordBundleError(
                f"base direct provenance[{position}].inputs must be an object"
            )
        golden_bound = _bind_spec(
            inputs.get("golden_style"),
            f"base direct provenance[{position}].inputs.golden_style",
            bindings,
        )
        expected_golden = _bind_spec(
            golden_style, "base source-index Golden style", bindings
        )
        if (
            not same_path(golden_bound.path, expected_golden.path)
            or golden_bound.sha256 != expected_golden.sha256
        ):
            raise CompositeRecordBundleError(
                "base direct provenance Golden lock differs from the source index"
            )
        raw_reviews = inputs.get("golden_vision_reports")
        if not isinstance(raw_reviews, list) or len(raw_reviews) != 2:
            raise CompositeRecordBundleError(
                "base direct provenance must lock exactly two Golden Vision reports"
            )
        specs: list[dict[str, str]] = []
        locks: list[tuple[str, str]] = []
        for review_index, raw in enumerate(raw_reviews):
            bound = _bind_spec(
                raw,
                (
                    f"base direct provenance[{position}].inputs."
                    f"golden_vision_reports[{review_index}]"
                ),
                bindings,
            )
            locks.append((bound.identity, bound.sha256))
            specs.append(_artifact(bound))
        canonical_locks = tuple(sorted(locks))
        if selected_review_locks is None:
            selected_review_locks = canonical_locks
            selected_specs = specs
        elif canonical_locks != selected_review_locks:
            raise CompositeRecordBundleError(
                "base direct sources do not share exact Golden review locks"
            )

    assert selected_specs is not None
    reviewers: set[str] = set()
    selected_job_id: str | None = None
    for index, spec in enumerate(selected_specs):
        bound = _bind_spec(spec, f"Golden Vision report {index + 1}", bindings)
        report = _json_object(bound, f"Golden Vision report {index + 1}")
        job_id = report.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise CompositeRecordBundleError(
                f"Golden Vision report {index + 1}.job_id must be non-empty"
            )
        if selected_job_id is None:
            selected_job_id = job_id
        elif job_id != selected_job_id:
            raise CompositeRecordBundleError(
                "Golden Vision reports do not review the same manifest job"
            )
        try:
            _, reviewer = phase5._accepted_report(
                report,
                job_id=job_id,
                image_path=golden_style["path"],
                image_sha256=golden_style["sha256"],
                golden_reference=True,
                threshold=94,
                label=f"Golden Vision report {index + 1}",
            )
            identity = canonical_reviewer_identity(reviewer)
        except (phase5.Phase5BuildError, TypeError, ValueError) as exc:
            raise CompositeRecordBundleError(str(exc)) from exc
        if identity in reviewers:
            raise CompositeRecordBundleError("Golden Vision reviewers are not distinct")
        reviewers.add(identity)
    if len(reviewers) != 2:
        raise CompositeRecordBundleError("exactly two Golden reviewers are required")
    return frozenset(reviewers)


def _load_base_context(
    *,
    base_index_path: Path,
    stage: str,
    catalog: dict[str, Any],
    catalog_by_id: dict[str, dict[str, Any]],
    contracts: dict[str, dict[str, Any]],
    canonical_bindings: dict[str, BoundArtifact],
) -> _BaseContext:
    base_stage = STAGE_BASE[stage]
    try:
        base_path, _ = require_trackable_path(base_index_path, label="base source index")
    except ReleasePathError as exc:
        raise CompositeRecordBundleError(str(exc)) from exc
    index_binding = _bind(base_path, "base source index")
    try:
        with phase5.bound_artifact_context(canonical_bindings):
            sources, index_sha256, golden_style = phase5.load_source_index(
                base_path, set(contracts)
            )
    except phase5.Phase5BuildError as exc:
        raise CompositeRecordBundleError(f"base source index is invalid: {exc}") from exc
    if index_sha256 != index_binding.sha256:
        raise CompositeRecordBundleError("base source-index parser/hash binding mismatch")
    if not isinstance(golden_style, dict):
        raise CompositeRecordBundleError("base source index must lock a Golden style")
    expected_ids = source_index_writer._expected_stage_ids(base_stage, catalog_by_id)
    if set(sources) != expected_ids:
        raise CompositeRecordBundleError(
            f"{stage} base index must be exact {base_stage} coverage: "
            f"missing={sorted(expected_ids - set(sources))}, "
            f"extra={sorted(set(sources) - expected_ids)}"
        )
    expected_order = _catalog_order(catalog, expected_ids)
    raw_index = _json_object(index_binding, "base source index")
    actual_order = _raw_index_order(raw_index, "base source index")
    if actual_order != expected_order:
        raise CompositeRecordBundleError(
            f"base source-index order mismatch: expected={expected_order}, "
            f"actual={actual_order}"
        )
    for sheet_id in expected_ids:
        expected_kind = source_index_writer._kind_for_sheet(catalog_by_id[sheet_id])
        entry = sources[sheet_id]
        if entry.get("kind") != expected_kind:
            raise CompositeRecordBundleError(
                f"base source {sheet_id} requires kind {expected_kind!r}"
            )
        if not phase5._entry_claims_acceptance(entry):
            raise CompositeRecordBundleError(
                f"base source {sheet_id} lacks complete acceptance evidence"
            )

    bindings = dict(canonical_bindings)
    _merge_bindings(bindings, (
        bound
        for bound in phase5.source_index_bound_artifacts(sources)
    ))
    _merge_bindings(bindings, (index_binding,))
    golden_reviewers = _golden_reviewers_from_direct_sources(
        sources=sources,
        golden_style=golden_style,
        bindings=bindings,
    )
    return _BaseContext(
        index=index_binding,
        sources=sources,
        golden_style={"path": golden_style["path"], "sha256": golden_style["sha256"]},
        golden_reviewers=golden_reviewers,
        bindings=bindings,
    )


def _expected_composite_ids(
    stage: str,
    *,
    catalog: dict[str, Any],
    catalog_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    ids = source_index_writer._expected_new_ids(stage, catalog_by_id)
    expected_type = STAGE_EXPECTED_TYPES[stage]
    if not ids or any(catalog_by_id[sheet_id].get("sheet_type") != expected_type for sheet_id in ids):
        raise CompositeRecordBundleError(
            f"canonical {stage} transition does not contain only {expected_type} sheets"
        )
    expected_count = 5 if stage == "idx22" else 1
    if len(ids) != expected_count:
        raise CompositeRecordBundleError(
            f"{stage} requires exactly {expected_count} composite sheets, found {len(ids)}"
        )
    return _catalog_order(catalog, ids)


def _validate_build_report(
    *,
    stage: str,
    build_report_path: Path,
    base: _BaseContext,
    expected_ids: list[str],
    expected_output_ids: list[str],
    expected_deferred_ids: list[str],
    masters_root: Path,
    bindings: dict[str, BoundArtifact],
) -> tuple[BoundArtifact, dict[str, dict[str, Any]], dict[str, BoundArtifact]]:
    report_binding = _bind(build_report_path, "composite build report")
    _bind_graph(bindings, (report_binding,))
    report = _json_object(report_binding, "composite build report")
    if report.get("schema_version") != phase5.BUILD_REPORT_SCHEMA_VERSION:
        raise CompositeRecordBundleError(
            "composite build report schema_version must be "
            f"{phase5.BUILD_REPORT_SCHEMA_VERSION!r}"
        )
    if report.get("generated_by") != phase5.GENERATOR_ID:
        raise CompositeRecordBundleError("composite build report has the wrong generator")
    if report.get("coordinate_reference_system") != "EA-WORLD-1":
        raise CompositeRecordBundleError("composite build report has the wrong CRS")
    stage_errors = phase5._build_report_stage_errors(report)
    if stage_errors:
        raise CompositeRecordBundleError(
            "composite build report violates target-stage contract: "
            + "; ".join(stage_errors)
        )
    if report.get("target_stage") != stage:
        raise CompositeRecordBundleError(
            f"composite build report target_stage must be {stage!r}"
        )
    if report.get("generated_composite_sheet_ids") != expected_ids:
        raise CompositeRecordBundleError(
            "composite build report generated_composite_sheet_ids mismatch: "
            f"expected={expected_ids}, "
            f"actual={report.get('generated_composite_sheet_ids')}"
        )
    if report.get("deferred_sheet_ids") != expected_deferred_ids:
        raise CompositeRecordBundleError(
            "composite build report deferred_sheet_ids mismatch: "
            f"expected={expected_deferred_ids}, "
            f"actual={report.get('deferred_sheet_ids')}"
        )
    if report.get("bounded_sheet_count") != len(expected_output_ids):
        raise CompositeRecordBundleError(
            f"composite build report bounded_sheet_count must be {len(expected_output_ids)}"
        )
    if report.get("tiles_requested") is not False:
        raise CompositeRecordBundleError(
            "idx22/idx23 composite build reports must not request tiles"
        )
    if report.get("public_tile_release") is not None:
        raise CompositeRecordBundleError(
            "idx22/idx23 composite build reports must not expose a public tile release"
        )
    inputs = report.get("inputs")
    if not isinstance(inputs, dict):
        raise CompositeRecordBundleError("composite build report inputs must be an object")
    _require_exact_artifact(
        inputs.get("source_index"), base.index, "composite build report child source index", bindings
    )
    canonical_catalog = _bind(phase5.DEFAULT_MAP_SHEETS, "canonical map catalog")
    canonical_contract = _bind(phase5.DEFAULT_CONTRACT, "canonical resolution contract")
    canonical_builder = _bind(phase5.BUILDER_SCRIPT_PATH, "canonical Phase 5 builder")
    _require_exact_artifact(
        inputs.get("builder_script"),
        canonical_builder,
        "composite build report builder script",
        bindings,
    )
    _require_exact_artifact(
        inputs.get("catalog"), canonical_catalog, "composite build report catalog", bindings
    )
    _require_exact_artifact(
        inputs.get("resolution_contract"),
        canonical_contract,
        "composite build report resolution contract",
        bindings,
    )

    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list):
        raise CompositeRecordBundleError("composite build report artifacts must be an array")
    if any(not isinstance(item, dict) for item in artifacts):
        raise CompositeRecordBundleError(
            "composite build report artifacts must contain only objects"
        )
    actual_artifact_ids = [item.get("sheet_id") for item in artifacts]
    if actual_artifact_ids != expected_output_ids:
        raise CompositeRecordBundleError(
            "composite build report full stage coverage/order mismatch: "
            f"expected={expected_output_ids}, actual={actual_artifact_ids}"
        )
    expected_master_files = {f"{sheet_id}.png" for sheet_id in expected_output_ids}
    actual_master_files = {
        path.relative_to(masters_root).as_posix()
        for path in masters_root.rglob("*")
        if path.is_file()
    }
    if actual_master_files != expected_master_files:
        raise CompositeRecordBundleError(
            "composite masters root has non-stage files: "
            f"missing={sorted(expected_master_files - actual_master_files)}, "
            f"extra={sorted(actual_master_files - expected_master_files)}"
        )
    selected: list[dict[str, Any]] = [
        item for item in artifacts if item.get("sheet_id") in set(expected_ids)
    ]
    actual_order = [item.get("sheet_id") for item in selected]
    if actual_order != expected_ids:
        raise CompositeRecordBundleError(
            f"composite build report coverage/order mismatch: expected={expected_ids}, "
            f"actual={actual_order}"
        )

    records: dict[str, dict[str, Any]] = {}
    masters: dict[str, BoundArtifact] = {}
    for position, item in enumerate(selected):
        sheet_id = expected_ids[position]
        if item.get("method") != "deterministic-parent-composite":
            raise CompositeRecordBundleError(
                f"{sheet_id} build report method must be deterministic-parent-composite"
            )
        raw_path = item.get("path")
        try:
            materialized = phase5._resolve_provenance_artifact(
                report_binding.path,
                raw_path,
                f"composite build report artifact {sheet_id}",
            )
        except phase5.Phase5BuildError as exc:
            raise CompositeRecordBundleError(str(exc)) from exc
        expected_path = masters_root / f"{sheet_id}.png"
        if not same_path(materialized, expected_path):
            raise CompositeRecordBundleError(
                f"{sheet_id} build report does not select {expected_path}"
            )
        master = _bind(expected_path, f"{sheet_id} composite master")
        _merge_bindings(bindings, (master,))
        if item.get("sha256") != master.sha256:
            raise CompositeRecordBundleError(f"{sheet_id} build report master hash is stale")
        records[sheet_id] = item
        masters[sheet_id] = master
    return report_binding, records, masters


def _vision_candidates(vision_root: Path, job_id: str) -> list[Path]:
    try:
        values = [
            path
            for path in vision_root.rglob("*.json")
            if path.stem == job_id or path.stem.startswith(f"{job_id}-")
        ]
    except OSError as exc:
        raise CompositeRecordBundleError(
            f"cannot scan Vision report root {vision_root}: {exc}"
        ) from exc
    return sorted(values, key=lambda path: path.as_posix().casefold())


def _vision_namespace_snapshot(vision_root: Path, job_id: str) -> tuple[str, ...]:
    return tuple(
        os.path.normcase(os.path.abspath(os.fspath(path)))
        for path in _vision_candidates(vision_root, job_id)
    )


def _validate_vision(
    *,
    sheet_id: str,
    master: BoundArtifact,
    vision_root: Path,
    golden_reviewers: frozenset[str],
    bindings: dict[str, BoundArtifact],
) -> tuple[BoundArtifact, tuple[str, ...]]:
    job_id = phase5.job_id_for_sheet(sheet_id)
    candidates = _vision_candidates(vision_root, job_id)
    if len(candidates) != COMPOSITE_REVIEW_COUNT:
        raise CompositeRecordBundleError(
            f"{sheet_id} requires exactly one manifest-bound Vision review; "
            f"found {len(candidates)}"
        )
    report_binding = _bind(candidates[0], f"{sheet_id} Vision report")
    _bind_graph(bindings, (report_binding,))
    report = _json_object(report_binding, f"{sheet_id} Vision report")
    try:
        score, reviewer = phase5._accepted_report(
            report,
            job_id=job_id,
            image_path=master.relative,
            image_sha256=master.sha256,
            golden_reference=False,
            threshold=COMPOSITE_REVIEW_THRESHOLD,
            label=f"{sheet_id} Vision report",
        )
        reviewer_key = canonical_reviewer_identity(reviewer)
    except (phase5.Phase5BuildError, TypeError, ValueError) as exc:
        raise CompositeRecordBundleError(str(exc)) from exc
    if score < COMPOSITE_REVIEW_THRESHOLD:
        raise CompositeRecordBundleError(
            f"{sheet_id} Vision score must be at least {COMPOSITE_REVIEW_THRESHOLD}"
        )
    if reviewer_key in golden_reviewers:
        raise CompositeRecordBundleError(
            f"{sheet_id} composite reviewer must be distinct from every Golden reviewer"
        )
    return report_binding, tuple(
        os.path.normcase(os.path.abspath(os.fspath(path))) for path in candidates
    )


def _assert_commit_inputs(
    *,
    bindings: dict[str, BoundArtifact],
    vision_root: Path,
    vision_namespaces: dict[str, tuple[str, ...]],
) -> None:
    try:
        assert_bindings_unchanged(bindings.values())
    except BoundArtifactError as exc:
        raise CompositeRecordBundleError(str(exc)) from exc
    for sheet_id, expected in vision_namespaces.items():
        actual = _vision_namespace_snapshot(
            vision_root, phase5.job_id_for_sheet(sheet_id)
        )
        if actual != expected:
            raise CompositeRecordBundleError(
                f"{sheet_id} Vision report namespace changed during validation: "
                f"expected={len(expected)}, actual={len(actual)}"
            )


def _install_payload(
    *,
    temporary: Path,
    output_path: Path,
    force: bool,
    payload_sha256: str,
    validate_commit_inputs: Callable[[], None],
) -> None:
    """Install atomically; preserve no-clobber and restore forced replacements."""

    backup = output_path.with_name(f".{output_path.name}.backup-{uuid.uuid4().hex}")
    backup_created = False
    installed = False
    try:
        validate_commit_inputs()
        if force:
            if output_path.exists():
                os.replace(output_path, backup)
                backup_created = True
            os.replace(temporary, output_path)
            installed = True
        else:
            try:
                # The temporary is beside the output.  A hard link therefore
                # supplies atomic same-filesystem create-if-absent semantics.
                os.link(temporary, output_path)
            except FileExistsError as exc:
                raise CompositeRecordBundleError(
                    f"composite-record bundle appeared during validation: {output_path}"
                ) from exc
            installed = True

        try:
            validate_commit_inputs()
            if hashlib.sha256(output_path.read_bytes()).hexdigest() != payload_sha256:
                raise CompositeRecordBundleError(
                    "installed composite-record bundle bytes changed during commit"
                )
        except Exception:
            if installed and output_path.exists():
                current_sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
                if current_sha != payload_sha256:
                    raise CompositeRecordBundleError(
                        "cannot safely roll back: output bytes changed after installation"
                    )
                output_path.unlink()
                installed = False
            if backup_created:
                os.replace(backup, output_path)
                backup_created = False
            raise

        if backup_created:
            backup.unlink()
            backup_created = False
    except Exception:
        if backup_created:
            if installed and output_path.exists():
                current_sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
                if current_sha == payload_sha256:
                    output_path.unlink()
                    installed = False
            if not output_path.exists():
                os.replace(backup, output_path)
                backup_created = False
        raise
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            # The committed output is a separate directory entry.  A transient
            # cleanup failure must not turn a verified commit into a reported
            # failure while leaving that commit installed.
            pass
        if backup_created and not output_path.exists():
            os.replace(backup, output_path)


def _validate_automated(
    *,
    sheet: dict[str, Any],
    contract: dict[str, Any],
    master: BoundArtifact,
    provenance: BoundArtifact,
    automated_root: Path,
    entry: dict[str, Any],
    bindings: dict[str, BoundArtifact],
) -> BoundArtifact:
    path = automated_root / f"{sheet['id']}.phase5.json"
    automated = _bind(path, f"{sheet['id']} automated report")
    _bind_graph(bindings, (automated,))
    report = _json_object(automated, f"{sheet['id']} automated report")
    if (
        report.get("status") != "passed"
        or report.get("source_kind") != COMPOSITE_KIND
        or report.get("sheet_id") != sheet["id"]
        or report.get("job_id") != phase5.job_id_for_sheet(sheet["id"])
    ):
        raise CompositeRecordBundleError(
            f"{sheet['id']} automated report is not an accepted composite audit"
        )
    reported_master = _bind_spec(
        report.get("master"), f"{sheet['id']} automated report master", bindings
    )
    reported_provenance = _bind_spec(
        report.get("provenance_report"),
        f"{sheet['id']} automated report provenance",
        bindings,
    )
    if not same_path(reported_master.path, master.path):
        raise CompositeRecordBundleError(
            f"{sheet['id']} automated report names a different master"
        )
    if not same_path(reported_provenance.path, provenance.path):
        raise CompositeRecordBundleError(
            f"{sheet['id']} automated report names a different build report"
        )
    entry["automated_report"] = _artifact(automated)
    try:
        with phase5.bound_artifact_context(bindings):
            phase5.validate_automated_qa_report(
                report,
                entry=entry,
                sheet=sheet,
                master_path=master.relative,
                job_id=phase5.job_id_for_sheet(sheet["id"]),
                contract=contract,
            )
    except phase5.Phase5BuildError as exc:
        raise CompositeRecordBundleError(str(exc)) from exc
    return automated


def _assemble_composite_record_bundle(
    *,
    stage: str,
    base_index_path: Path,
    build_report_path: Path,
    masters_root: Path,
    automated_root: Path,
    vision_root: Path,
    output_path: Path,
    force: bool,
) -> dict[str, Any]:
    if stage not in STAGE_BASE:
        raise CompositeRecordBundleError(f"unsupported composite stage: {stage!r}")
    masters_root = _require_directory(masters_root, "composite masters root")
    automated_root = _require_directory(automated_root, "automated QA root")
    vision_root = _require_directory(vision_root, "Vision QA root")
    output_path = _tracked_output(output_path)
    if output_path.exists() and not force:
        raise CompositeRecordBundleError(
            f"refusing to overwrite existing composite-record bundle: {output_path}"
        )

    canonical_bindings: dict[str, BoundArtifact] = {}
    canonical_roots = tuple(
        _bind(path, label)
        for path, label in (
            (phase5.DEFAULT_MAP_SHEETS, "canonical map catalog"),
            (phase5.DEFAULT_CONTRACT, "canonical resolution contract"),
            (phase5.DEFAULT_SOURCE_INDEX_SCHEMA, "canonical source-index schema"),
            (phase5.DEFAULT_QA_REPORT_SCHEMA, "canonical Vision QA schema"),
            (phase5.DEFAULT_AUTOMATED_QA_SCHEMA, "canonical automated QA schema"),
        )
    )
    _merge_bindings(canonical_bindings, canonical_roots)
    with phase5.bound_artifact_context(canonical_bindings):
        catalog, catalog_by_id, contracts = _catalog_contract()
    expected_ids = _expected_composite_ids(
        stage, catalog=catalog, catalog_by_id=catalog_by_id
    )
    expected_output_set = source_index_writer._expected_stage_ids(
        stage, catalog_by_id
    )
    expected_output_ids = _catalog_order(catalog, expected_output_set)
    final_ids = source_index_writer._expected_stage_ids("idx23", catalog_by_id)
    expected_deferred_ids = _catalog_order(
        catalog, final_ids - expected_output_set
    )
    base = _load_base_context(
        base_index_path=base_index_path,
        stage=stage,
        catalog=catalog,
        catalog_by_id=catalog_by_id,
        contracts=contracts,
        canonical_bindings=canonical_bindings,
    )
    bindings = dict(base.bindings)
    build_report, artifact_records, masters = _validate_build_report(
        stage=stage,
        build_report_path=build_report_path,
        base=base,
        expected_ids=expected_ids,
        expected_output_ids=expected_output_ids,
        expected_deferred_ids=expected_deferred_ids,
        masters_root=masters_root,
        bindings=bindings,
    )

    records: list[dict[str, Any]] = []
    vision_namespaces: dict[str, tuple[str, ...]] = {}
    for sheet_id in expected_ids:
        sheet = catalog_by_id[sheet_id]
        contract = contracts[sheet_id]
        master = masters[sheet_id]
        size, image_format, color_mode = phase5.image_properties(
            master.path, f"{sheet_id} composite master"
        )
        expected_size = (contract.get("width"), contract.get("height"))
        if size != expected_size:
            raise CompositeRecordBundleError(
                f"{sheet_id} composite master dimensions mismatch: "
                f"expected={expected_size}, actual={size}"
            )
        if image_format != "PNG" or color_mode != "RGB":
            raise CompositeRecordBundleError(
                f"{sheet_id} composite master must be a native RGB PNG"
            )
        artifact_record = artifact_records[sheet_id]
        if (
            artifact_record.get("width"), artifact_record.get("height")
        ) != size:
            raise CompositeRecordBundleError(
                f"{sheet_id} build report dimensions are stale"
            )
        entry: dict[str, Any] = {
            "sheet_id": sheet_id,
            "kind": COMPOSITE_KIND,
            **_artifact(master),
            "provenance_report": _artifact(build_report),
        }
        combined_sources = {**base.sources, sheet_id: entry}
        try:
            with phase5.bound_artifact_context(bindings):
                phase5.verify_master_provenance(
                    entry,
                    sheet=sheet,
                    master_path=master.relative,
                    contract=contract,
                    catalog_by_id=catalog_by_id,
                    sources=combined_sources,
                )
        except phase5.Phase5BuildError as exc:
            raise CompositeRecordBundleError(str(exc)) from exc

        automated = _validate_automated(
            sheet=sheet,
            contract=contract,
            master=master,
            provenance=build_report,
            automated_root=automated_root,
            entry=entry,
            bindings=bindings,
        )
        vision, vision_namespace = _validate_vision(
            sheet_id=sheet_id,
            master=master,
            vision_root=vision_root,
            golden_reviewers=base.golden_reviewers,
            bindings=bindings,
        )
        vision_namespaces[sheet_id] = vision_namespace
        entry["vision_reports"] = [_artifact(vision)]
        # Re-run the complete builder acceptance contract with every evidence
        # artifact now present in the exact emitted record.
        combined_sources = {**base.sources, sheet_id: entry}
        try:
            with phase5.bound_artifact_context(bindings):
                evidence = phase5.accepted_evidence(
                    entry,
                    sheet=sheet,
                    master_path=master.relative,
                    job_id=phase5.job_id_for_sheet(sheet_id),
                    contract=contract,
                    catalog_by_id=catalog_by_id,
                    sources=combined_sources,
                )
        except phase5.Phase5BuildError as exc:
            raise CompositeRecordBundleError(str(exc)) from exc
        if evidence is None or evidence.primary_score < COMPOSITE_REVIEW_THRESHOLD:
            raise CompositeRecordBundleError(
                f"{sheet_id} complete acceptance evidence was not proven"
            )
        records.append(entry)

    if [record["sheet_id"] for record in records] != expected_ids:
        raise CompositeRecordBundleError("assembled composite bundle order drifted")
    document = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "release_id": phase5.DEFAULT_PUBLIC_RELEASE_ID,
        "records": records,
    }
    # Prove compatibility with the next immutable source-index writer before
    # any bytes are installed.
    with phase5.bound_artifact_context(bindings):
        for position, record in enumerate(records):
            source_index_writer._normalise_record(record, f"records[{position}]")
    if any(same_path(output_path, bound.path) for bound in bindings.values()):
        raise CompositeRecordBundleError(
            "composite-record output may not overwrite a selected input artifact"
        )
    _assert_commit_inputs(
        bindings=bindings,
        vision_root=vision_root,
        vision_namespaces=vision_namespaces,
    )
    payload = _stable_json_bytes(document)
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _install_payload(
            temporary=temporary,
            output_path=output_path,
            force=force,
            payload_sha256=payload_sha256,
            validate_commit_inputs=lambda: _assert_commit_inputs(
                bindings=bindings,
                vision_root=vision_root,
                vision_namespaces=vision_namespaces,
            ),
        )
    except OSError as exc:
        raise CompositeRecordBundleError(
            f"cannot install composite-record bundle {output_path}: {exc}"
        ) from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return document


def assemble_composite_record_bundle(
    *,
    stage: str,
    base_index_path: Path,
    build_report_path: Path,
    masters_root: Path,
    automated_root: Path,
    vision_root: Path,
    output_path: Path,
    force: bool = False,
) -> dict[str, Any]:
    """Validate and atomically write the exact idx22 or idx23 record bundle."""

    try:
        return _assemble_composite_record_bundle(
            stage=stage,
            base_index_path=base_index_path,
            build_report_path=build_report_path,
            masters_root=masters_root,
            automated_root=automated_root,
            vision_root=vision_root,
            output_path=output_path,
            force=force,
        )
    except CompositeRecordBundleError:
        raise
    except (
        BoundArtifactError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        phase5.Phase5BuildError,
        source_index_writer.SourceIndexWriterError,
    ) as exc:
        raise CompositeRecordBundleError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=tuple(STAGE_BASE))
    parser.add_argument("--base-index", required=True, type=Path)
    parser.add_argument("--build-report", required=True, type=Path)
    parser.add_argument("--masters-root", required=True, type=Path)
    parser.add_argument("--automated-root", required=True, type=Path)
    parser.add_argument("--vision-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        document = assemble_composite_record_bundle(
            stage=args.stage,
            base_index_path=args.base_index,
            build_report_path=args.build_report,
            masters_root=args.masters_root,
            automated_root=args.automated_root,
            vision_root=args.vision_root,
            output_path=args.output,
            force=args.force,
        )
    except CompositeRecordBundleError as exc:
        print(f"Composite-record bundle assembly failed: {exc}", file=sys.stderr)
        return 1
    output, relative = require_trackable_path(args.output, label="composite-record bundle")
    summary = {
        "generated_by": TOOL_ID,
        "stage": args.stage,
        "output": relative,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "record_count": len(document["records"]),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"Wrote {summary['record_count']} validated {args.stage} composite records "
            f"to {summary['output']} ({summary['sha256']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
