#!/usr/bin/env python3
"""Assemble the fail-closed Phase 5 direct-master record bundle.

The immutable ``idx17`` writer accepts a compact schema-1.0 record bundle, but
assembling that bundle by hand is unsafe: the compact record does not carry
dimensions and cannot itself prove that its provenance, automated audit, and
Vision reviews all describe the same native master.  This command closes that
gap before ``write_phase5_source_indexes.py --stage idx17 --records``.

The command deliberately does not consult the production manifest or decide
whether the referenced Golden style is accepted.  Canonical provenance still
has to hash-lock the Golden bytes and its two review artifacts, while the
source-index writer remains the later authority that binds those artifacts to
the accepted Golden manifest entry.

Expected input names are deterministic::

    <masters-root>/<sheet-id>.png
    <masters-root>/<sheet-id>.canonical-provenance.json
    <automated-root>/<sheet-id>.phase5.json
    <vision-root>/**/phase5-<sheet-core>-v1[-...].json

Every input and nested artifact must be a nonignored repository file outside
temporary/build namespaces.  Existing outputs are never overwritten unless
``--force`` is explicit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import build_phase5_assets as phase5
import write_phase5_source_indexes as source_index_writer
from reviewer_identity import canonical_reviewer_identity
from release_path_safety import (
    ReleasePathError,
    canonical_repo_relative,
    require_trackable_path,
    same_path,
)


TOOL_ID = "sstory-map-production/assemble_phase5_direct_records.py@1"
BUNDLE_SCHEMA_VERSION = "1.0.0"
EXPECTED_DIRECT_IDS = source_index_writer.EXPECTED_DIRECT_IDS
EXPECTED_STANDARD_REVIEW_IDS = frozenset(
    {
        "sheet_region_atlantia_region",
        "sheet_region_emerald_plains_region",
        "sheet_region_ethernia_core_region",
    }
)
EXPECTED_STRICT_REVIEW_IDS = EXPECTED_DIRECT_IDS - EXPECTED_STANDARD_REVIEW_IDS


class DirectRecordBundleError(RuntimeError):
    """Raised when the direct-master evidence cannot be proven complete."""


def _stat_signature(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


@dataclass(frozen=True)
class _FileBinding:
    """A repository path bound to the bytes and metadata read from one handle."""

    path: Path
    relative: str
    sha256: str
    signature: tuple[int, int, int, int]

    @property
    def identity(self) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(self.path)))

    def artifact(self) -> dict[str, str]:
        return {"path": self.relative, "sha256": self.sha256}


@dataclass(frozen=True)
class _GoldenLock:
    """The Golden bytes and review artifacts named by canonical provenance."""

    style: tuple[str, str]
    reviews: tuple[tuple[str, str], ...]


class _BindingRegistry:
    """Track every file used to decide the emitted immutable record bundle."""

    def __init__(self) -> None:
        self._bindings: dict[str, _FileBinding] = {}

    @staticmethod
    def _digest_and_signature(path: Path, label: str) -> tuple[str, tuple[int, int, int, int]]:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                before = os.fstat(handle.fileno())
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                after = os.fstat(handle.fileno())
            current = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise DirectRecordBundleError(f"cannot read {label}: {path}: {exc}") from exc
        if (
            _stat_signature(before) != _stat_signature(after)
            or _stat_signature(after) != _stat_signature(current)
        ):
            raise DirectRecordBundleError(f"{label} changed while its bytes were read")
        return digest.hexdigest(), _stat_signature(current)

    def add(
        self,
        raw_path: str | Path,
        label: str,
        *,
        claimed_sha256: str | None = None,
    ) -> _FileBinding:
        try:
            path, relative = require_trackable_path(raw_path, label=label)
        except ReleasePathError as exc:
            raise DirectRecordBundleError(str(exc)) from exc
        identity = os.path.normcase(os.path.abspath(os.fspath(path)))
        binding = self._bindings.get(identity)
        if binding is None:
            digest, signature = self._digest_and_signature(path, label)
            binding = _FileBinding(path, relative, digest, signature)
            self._bindings[identity] = binding
        if claimed_sha256 is not None:
            if (
                not isinstance(claimed_sha256, str)
                or len(claimed_sha256) != 64
                or any(character not in "0123456789abcdef" for character in claimed_sha256)
            ):
                raise DirectRecordBundleError(
                    f"{label}.sha256 must be a lowercase 64-character digest"
                )
            if claimed_sha256 != binding.sha256:
                raise DirectRecordBundleError(
                    f"{label}.sha256 mismatch: report={claimed_sha256}, "
                    f"actual={binding.sha256}"
                )
        return binding

    def add_artifact(self, value: Any, label: str) -> _FileBinding:
        if not isinstance(value, dict):
            raise DirectRecordBundleError(f"{label} must be a path/sha256 object")
        raw_path = value.get("path")
        claimed = value.get("sha256")
        if not isinstance(raw_path, str) or not raw_path:
            raise DirectRecordBundleError(f"{label}.path must be a non-empty string")
        if not isinstance(claimed, str):
            raise DirectRecordBundleError(f"{label}.sha256 is required")
        return self.add(raw_path, label, claimed_sha256=claimed)

    def load_json_object(
        self, raw_path: str | Path, label: str
    ) -> tuple[_FileBinding, dict[str, Any]]:
        binding = self.add(raw_path, label)
        try:
            data = binding.path.read_bytes()
            value = json.loads(data.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DirectRecordBundleError(
                f"{label} is not valid UTF-8 JSON: {binding.relative}: {exc}"
            ) from exc
        if hashlib.sha256(data).hexdigest() != binding.sha256:
            raise DirectRecordBundleError(f"{label} changed after its bytes were bound")
        if not isinstance(value, dict):
            raise DirectRecordBundleError(f"{label} must contain a JSON object")
        return binding, value

    def assert_unchanged(self) -> None:
        for binding in self._bindings.values():
            try:
                path, relative = require_trackable_path(
                    binding.path, label=f"bound input {binding.relative}"
                )
            except ReleasePathError as exc:
                raise DirectRecordBundleError(str(exc)) from exc
            digest, signature = self._digest_and_signature(
                path, f"bound input {relative}"
            )
            if digest != binding.sha256 or signature != binding.signature:
                raise DirectRecordBundleError(
                    f"bound input changed after validation: {binding.relative}"
                )


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


def _require_directory(raw_path: Path, label: str) -> Path:
    try:
        path, _ = require_trackable_path(
            raw_path, label=label, require_file=False
        )
    except ReleasePathError as exc:
        raise DirectRecordBundleError(str(exc)) from exc
    if not path.is_dir():
        raise DirectRecordBundleError(f"{label} must be a directory: {path}")
    return path


def _tracked_output(raw_path: Path) -> Path:
    try:
        path, _ = require_trackable_path(
            raw_path,
            label="direct-record bundle output",
            must_exist=False,
            require_file=False,
        )
    except ReleasePathError as exc:
        raise DirectRecordBundleError(str(exc)) from exc
    if path.exists() and not path.is_file():
        raise DirectRecordBundleError(
            f"direct-record bundle output is not a file: {path}"
        )
    return path


def _same_artifact_path(
    value: Any,
    expected_path: Path,
    label: str,
    bindings: _BindingRegistry,
) -> _FileBinding:
    actual = bindings.add_artifact(value, label)
    expected = bindings.add(expected_path, f"canonical {label}")
    if not same_path(actual.path, expected.path) or actual.sha256 != expected.sha256:
        raise DirectRecordBundleError(
            f"{label} must lock canonical artifact {expected.relative}"
        )
    return actual


def _relative_provenance_artifact(
    report_path: Path,
    value: Any,
    label: str,
    bindings: _BindingRegistry,
) -> _FileBinding:
    if not isinstance(value, dict):
        raise DirectRecordBundleError(f"{label} must be an object")
    raw_path = value.get("path")
    claimed = value.get("sha256")
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        raise DirectRecordBundleError(f"{label}.path must be a relative POSIX path")
    portable = PurePosixPath(raw_path)
    if portable.is_absolute() or any(part in {"", ".", ".."} for part in portable.parts):
        raise DirectRecordBundleError(f"{label}.path escapes its provenance root")
    return bindings.add(
        report_path.parent.joinpath(*portable.parts),
        label,
        claimed_sha256=claimed,
    )


def _bind_renderer_report_artifacts(
    report: dict[str, Any],
    *,
    master: _FileBinding,
    label: str,
    bindings: _BindingRegistry,
) -> None:
    generated_by = report.get("generated_by")
    if not isinstance(generated_by, dict):
        raise DirectRecordBundleError(f"{label}.generated_by must be an object")
    bindings.add_artifact(generated_by, f"{label}.generated_by")

    inputs = report.get("inputs")
    if not isinstance(inputs, dict):
        raise DirectRecordBundleError(f"{label}.inputs must be an object")
    for key in ("golden_style", "material_atlas", "canonical_control_index"):
        bindings.add_artifact(inputs.get(key), f"{label}.inputs.{key}")
    bindings.add_artifact(report.get("map_sheets"), f"{label}.map_sheets")
    bindings.add_artifact(
        report.get("resolution_contract"), f"{label}.resolution_contract"
    )
    sources = report.get("sources")
    if not isinstance(sources, list):
        raise DirectRecordBundleError(f"{label}.sources must be an array")
    for index, source in enumerate(sources):
        bindings.add_artifact(source, f"{label}.sources[{index}]")

    outputs = report.get("outputs")
    if not isinstance(outputs, dict):
        raise DirectRecordBundleError(f"{label}.outputs must be an object")
    reported_master = bindings.add_artifact(
        outputs.get("master"), f"{label}.outputs.master"
    )
    if not same_path(reported_master.path, master.path):
        raise DirectRecordBundleError(
            f"{label}.outputs.master does not name the selected direct master"
        )
    for key in ("observed_land_sea_mask", "observed_transport_mask"):
        bindings.add_artifact(outputs.get(key), f"{label}.outputs.{key}")


def _validate_canonical_provenance(
    provenance_path: Path,
    *,
    sheet: dict[str, Any],
    contract: dict[str, Any],
    master: _FileBinding,
    size: tuple[int, int],
    bindings: _BindingRegistry,
) -> tuple[_FileBinding, _GoldenLock]:
    label = f"{sheet['id']} canonical provenance"
    provenance_binding, report = bindings.load_json_object(provenance_path, label)
    phase5._validate_schema_instance(
        report, phase5.DEFAULT_CANONICAL_RENDER_PROVENANCE_SCHEMA, label
    )
    if report.get("sheet_id") != sheet["id"]:
        raise DirectRecordBundleError(f"{label}.sheet_id mismatch")

    inputs = report["inputs"]
    _same_artifact_path(
        inputs["map_catalog"], phase5.DEFAULT_MAP_SHEETS, f"{label}.inputs.map_catalog", bindings
    )
    _same_artifact_path(
        inputs["resolution_contract"],
        phase5.DEFAULT_CONTRACT,
        f"{label}.inputs.resolution_contract",
        bindings,
    )
    _same_artifact_path(
        inputs["control_index"],
        phase5.DEFAULT_CANONICAL_CONTROL_INDEX,
        f"{label}.inputs.control_index",
        bindings,
    )
    golden_style = bindings.add_artifact(
        inputs["golden_style"], f"{label}.inputs.golden_style"
    )
    golden_reviews: list[_FileBinding] = []
    for index, report_spec in enumerate(inputs["golden_vision_reports"]):
        golden_reviews.append(
            bindings.add_artifact(
                report_spec, f"{label}.inputs.golden_vision_reports[{index}]"
            )
        )
    if len({review.identity for review in golden_reviews}) != len(golden_reviews):
        raise DirectRecordBundleError(
            f"{label}.inputs.golden_vision_reports contains duplicate artifacts"
        )
    bindings.add_artifact(inputs["renderer"], f"{label}.inputs.renderer")
    renderer_report_binding = bindings.add_artifact(
        inputs["renderer_report"], f"{label}.inputs.renderer_report"
    )
    bindings.add_artifact(
        inputs["material_atlas"], f"{label}.inputs.material_atlas"
    )

    canonical_sources = {
        item.get("role"): item
        for item in inputs["canon_sources"]
        if isinstance(item, dict)
    }
    if set(canonical_sources) != set(phase5.CANONICAL_GEOJSON_SOURCES):
        raise DirectRecordBundleError(
            f"{label}.inputs.canon_sources must cover all six canonical roles"
        )
    for role, expected_path in phase5.CANONICAL_GEOJSON_SOURCES.items():
        _same_artifact_path(
            canonical_sources[role],
            expected_path,
            f"{label}.inputs.canon_sources[{role}]",
            bindings,
        )

    artifacts = report["artifacts"]
    matches = [
        item
        for item in artifacts
        if isinstance(item, dict) and item.get("sheet_id") == sheet["id"]
    ]
    if len(matches) != 1:
        raise DirectRecordBundleError(
            f"{label} must contain exactly one artifact for {sheet['id']}"
        )
    artifact_record = matches[0]
    materialized = _relative_provenance_artifact(
        provenance_binding.path,
        artifact_record,
        f"{label}.artifacts[0]",
        bindings,
    )
    if not same_path(materialized.path, master.path):
        raise DirectRecordBundleError(
            f"{label}.artifacts[0] does not name the selected direct master"
        )
    if (
        artifact_record.get("sha256") != master.sha256
        or (artifact_record.get("width"), artifact_record.get("height")) != size
        or size != (contract["width"], contract["height"])
    ):
        raise DirectRecordBundleError(
            f"{label} master hash or dimensions do not match the selected master contract"
        )

    _, renderer_report = bindings.load_json_object(
        renderer_report_binding.path, f"{label} renderer report"
    )
    _bind_renderer_report_artifacts(
        renderer_report,
        master=master,
        label=f"{label} renderer report",
        bindings=bindings,
    )
    phase5._verify_renderer_report_binding(
        inputs,
        artifact_record,
        sheet_id=sheet["id"],
        label=label,
    )
    golden_lock = _GoldenLock(
        style=(golden_style.identity, golden_style.sha256),
        reviews=tuple(
            sorted(
                ((review.identity, review.sha256) for review in golden_reviews),
                key=lambda item: item[0],
            )
        ),
    )
    return provenance_binding, golden_lock


def _bind_automated_report_artifacts(
    report: dict[str, Any],
    *,
    master: _FileBinding,
    provenance: _FileBinding,
    label: str,
    bindings: _BindingRegistry,
) -> None:
    reported_master = bindings.add_artifact(report.get("master"), f"{label}.master")
    if not same_path(reported_master.path, master.path):
        raise DirectRecordBundleError(f"{label}.master does not name the selected master")
    reported_provenance = bindings.add_artifact(
        report.get("provenance_report"), f"{label}.provenance_report"
    )
    if not same_path(reported_provenance.path, provenance.path):
        raise DirectRecordBundleError(
            f"{label}.provenance_report does not name the selected provenance"
        )
    geography = report.get("geography")
    if not isinstance(geography, dict):
        raise DirectRecordBundleError(f"{label}.geography must be an object")
    for group in ("land_sea", "transport"):
        values = geography.get(group)
        if not isinstance(values, dict):
            raise DirectRecordBundleError(f"{label}.geography.{group} must be an object")
        for role in ("control", "observed"):
            bindings.add_artifact(
                values.get(role), f"{label}.geography.{group}.{role}"
            )
    seams = report.get("checks", {}).get("seams", {}).get("evidence", [])
    if not isinstance(seams, list):
        raise DirectRecordBundleError(f"{label}.checks.seams.evidence must be an array")
    for index, seam in enumerate(seams):
        if not isinstance(seam, dict):
            raise DirectRecordBundleError(
                f"{label}.checks.seams.evidence[{index}] must be an object"
            )
        for role in ("source_a", "source_b"):
            bindings.add_artifact(
                seam.get(role), f"{label}.checks.seams.evidence[{index}].{role}"
            )


def _validate_automated_report(
    automated_path: Path,
    *,
    sheet: dict[str, Any],
    contract: dict[str, Any],
    master: _FileBinding,
    provenance: _FileBinding,
    bindings: _BindingRegistry,
) -> _FileBinding:
    label = f"{sheet['id']} automated report"
    automated_binding, report = bindings.load_json_object(automated_path, label)
    _bind_automated_report_artifacts(
        report,
        master=master,
        provenance=provenance,
        label=label,
        bindings=bindings,
    )
    entry = {
        "sheet_id": sheet["id"],
        "kind": phase5.CANONICAL_RENDER_SOURCE_KIND,
        **master.artifact(),
        "provenance_report": provenance.artifact(),
    }
    phase5.validate_automated_qa_report(
        report,
        entry=entry,
        sheet=sheet,
        master_path=master.relative,
        job_id=phase5.job_id_for_sheet(sheet["id"]),
        contract=contract,
    )
    return automated_binding


def _vision_candidates(vision_root: Path, job_id: str) -> list[Path]:
    matches: list[Path] = []
    try:
        candidates = vision_root.rglob("*.json")
        for candidate in candidates:
            stem = candidate.stem
            if stem == job_id or stem.startswith(f"{job_id}-"):
                matches.append(candidate)
    except OSError as exc:
        raise DirectRecordBundleError(
            f"cannot scan Vision report root {vision_root}: {exc}"
        ) from exc
    return sorted(matches, key=lambda path: path.as_posix().casefold())


def _validate_vision_reports(
    vision_root: Path,
    *,
    sheet: dict[str, Any],
    master: _FileBinding,
    threshold: int,
    required_reviews: int,
    bindings: _BindingRegistry,
) -> list[_FileBinding]:
    job_id = phase5.job_id_for_sheet(sheet["id"])
    candidates = _vision_candidates(vision_root, job_id)
    if not candidates:
        raise DirectRecordBundleError(
            f"{sheet['id']} has no Vision report matching {job_id}[-...].json"
        )
    reviewers: set[str] = set()
    validated: list[_FileBinding] = []
    for index, path in enumerate(candidates):
        label = f"{sheet['id']} Vision report {index + 1}"
        binding, report = bindings.load_json_object(path, label)
        score, reviewer = phase5._accepted_report(
            report,
            job_id=job_id,
            image_path=master.relative,
            image_sha256=master.sha256,
            golden_reference=False,
            threshold=threshold,
            label=label,
        )
        if score < threshold:  # Defensive clarity; _accepted_report also enforces this.
            raise DirectRecordBundleError(
                f"{label} score must be at least {threshold}, found {score}"
            )
        reviewer_key = canonical_reviewer_identity(reviewer)
        if reviewer_key in reviewers:
            raise DirectRecordBundleError(
                f"{sheet['id']} Vision reports duplicate reviewer {reviewer!r}"
            )
        reviewers.add(reviewer_key)
        validated.append(binding)
    if len(reviewers) < required_reviews:
        raise DirectRecordBundleError(
            f"{sheet['id']} requires {required_reviews} distinct accepted Vision "
            f"review(s) at score >= {threshold}; found {len(reviewers)}"
        )
    return sorted(validated, key=lambda binding: binding.relative.casefold())


def _load_direct_contract() -> tuple[
    dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[str]
]:
    catalog, catalog_by_id, derived = phase5.load_contract(
        phase5.DEFAULT_CONTRACT, phase5.DEFAULT_MAP_SHEETS
    )
    contracts = derived.get("sheets") if isinstance(derived, dict) else None
    if not isinstance(contracts, dict):
        raise DirectRecordBundleError("resolution contract lacks derived sheet entries")
    catalog_ids = [
        item.get("id")
        for item in catalog.get("sheets", [])
        if isinstance(item, dict)
        and item.get("sheet_type") in source_index_writer.DIRECT_TYPES
    ]
    actual = {sheet_id for sheet_id in catalog_ids if isinstance(sheet_id, str)}
    if len(catalog_ids) != len(actual) or actual != EXPECTED_DIRECT_IDS:
        raise DirectRecordBundleError(
            "canonical catalog must contain exactly the 17 expected direct sheets: "
            f"missing={sorted(EXPECTED_DIRECT_IDS - actual)}, "
            f"extra={sorted(actual - EXPECTED_DIRECT_IDS)}"
        )
    missing_contracts = EXPECTED_DIRECT_IDS - set(contracts)
    if missing_contracts:
        raise DirectRecordBundleError(
            f"resolution contract lacks direct sheets: {sorted(missing_contracts)}"
        )
    return catalog, catalog_by_id, contracts, [str(value) for value in catalog_ids]


def _review_policy(sheet_id: str, sheet: dict[str, Any]) -> tuple[int, int]:
    threshold = 90 if sheet_id in EXPECTED_STANDARD_REVIEW_IDS else 94
    required = 1 if sheet_id in EXPECTED_STANDARD_REVIEW_IDS else 2
    if (
        phase5.acceptance_threshold(sheet) != threshold
        or phase5.required_review_count(sheet) != required
    ):
        raise DirectRecordBundleError(
            f"canonical review policy drift for {sheet_id}: expected "
            f"threshold={threshold}, reviews={required}"
        )
    return threshold, required


def _assert_unique(
    seen: dict[str, str], binding: _FileBinding, label: str
) -> None:
    previous = seen.get(binding.identity)
    if previous is not None:
        raise DirectRecordBundleError(
            f"duplicate selected artifact: {label} reuses {previous}"
        )
    seen[binding.identity] = label


def _assemble_direct_record_bundle(
    *,
    masters_root: Path,
    automated_root: Path,
    vision_root: Path,
    output_path: Path,
    force: bool,
) -> dict[str, Any]:
    masters_root = _require_directory(masters_root, "direct masters root")
    automated_root = _require_directory(automated_root, "automated QA root")
    vision_root = _require_directory(vision_root, "Vision QA root")
    output_path = _tracked_output(output_path)
    if output_path.exists() and not force:
        raise DirectRecordBundleError(
            f"refusing to overwrite existing direct-record bundle: {output_path}"
        )

    _, catalog_by_id, contracts, ordered_ids = _load_direct_contract()
    bindings = _BindingRegistry()
    # Bind the contract bytes whose derived dimensions govern every master.
    bindings.add(phase5.DEFAULT_MAP_SHEETS, "canonical map catalog")
    bindings.add(phase5.DEFAULT_CONTRACT, "canonical resolution contract")

    selected_paths: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    selected_golden: _GoldenLock | None = None
    for sheet_id in ordered_ids:
        sheet = catalog_by_id[sheet_id]
        contract = contracts[sheet_id]
        threshold, required_reviews = _review_policy(sheet_id, sheet)

        master = bindings.add(
            masters_root / f"{sheet_id}.png", f"{sheet_id} direct master"
        )
        _assert_unique(selected_paths, master, f"{sheet_id} master")
        size, image_format, color_mode = phase5.image_properties(
            master.path, f"{sheet_id} direct master"
        )
        expected_size = (contract.get("width"), contract.get("height"))
        if size != expected_size:
            raise DirectRecordBundleError(
                f"{sheet_id} direct master dimensions mismatch: "
                f"expected={expected_size}, actual={size}"
            )
        if image_format != "PNG" or color_mode != "RGB":
            raise DirectRecordBundleError(
                f"{sheet_id} direct master must be a native RGB PNG"
            )

        provenance, golden_lock = _validate_canonical_provenance(
            masters_root / f"{sheet_id}.canonical-provenance.json",
            sheet=sheet,
            contract=contract,
            master=master,
            size=size,
            bindings=bindings,
        )
        if selected_golden is None:
            selected_golden = golden_lock
        elif golden_lock != selected_golden:
            raise DirectRecordBundleError(
                f"{sheet_id} canonical provenance does not use the same locked "
                "Golden style and review artifacts as the other direct masters"
            )
        _assert_unique(selected_paths, provenance, f"{sheet_id} provenance")
        automated = _validate_automated_report(
            automated_root / f"{sheet_id}.phase5.json",
            sheet=sheet,
            contract=contract,
            master=master,
            provenance=provenance,
            bindings=bindings,
        )
        _assert_unique(selected_paths, automated, f"{sheet_id} automated report")
        vision_reports = _validate_vision_reports(
            vision_root,
            sheet=sheet,
            master=master,
            threshold=threshold,
            required_reviews=required_reviews,
            bindings=bindings,
        )
        for index, report in enumerate(vision_reports):
            _assert_unique(
                selected_paths, report, f"{sheet_id} Vision report {index + 1}"
            )

        records.append(
            {
                "sheet_id": sheet_id,
                "kind": phase5.CANONICAL_RENDER_SOURCE_KIND,
                **master.artifact(),
                "provenance_report": provenance.artifact(),
                "automated_report": automated.artifact(),
                "vision_reports": [report.artifact() for report in vision_reports],
            }
        )

    if {record["sheet_id"] for record in records} != EXPECTED_DIRECT_IDS:
        raise DirectRecordBundleError("assembled bundle does not contain exact idx17 coverage")

    document = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "release_id": phase5.DEFAULT_PUBLIC_RELEASE_ID,
        "records": records,
    }
    bindings.assert_unchanged()
    payload = _stable_json_bytes(document)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if output_path.exists() and not force:
            raise DirectRecordBundleError(
                f"direct-record bundle appeared during validation: {output_path}"
            )
        os.replace(temporary, output_path)
    except OSError as exc:
        raise DirectRecordBundleError(
            f"cannot install direct-record bundle {output_path}: {exc}"
        ) from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return document


def assemble_direct_record_bundle(
    *,
    masters_root: Path,
    automated_root: Path,
    vision_root: Path,
    output_path: Path,
    force: bool = False,
) -> dict[str, Any]:
    """Validate all direct evidence and atomically write one idx17 record bundle."""

    try:
        return _assemble_direct_record_bundle(
            masters_root=masters_root,
            automated_root=automated_root,
            vision_root=vision_root,
            output_path=output_path,
            force=force,
        )
    except DirectRecordBundleError:
        raise
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        phase5.Phase5BuildError,
        source_index_writer.SourceIndexWriterError,
    ) as exc:
        raise DirectRecordBundleError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
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
        document = assemble_direct_record_bundle(
            masters_root=args.masters_root,
            automated_root=args.automated_root,
            vision_root=args.vision_root,
            output_path=args.output,
            force=args.force,
        )
    except DirectRecordBundleError as exc:
        print(f"Direct-record bundle assembly failed: {exc}", file=sys.stderr)
        return 1
    output, relative = canonical_repo_relative(args.output, label="direct-record bundle output")
    summary = {
        "generated_by": TOOL_ID,
        "output": relative,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "record_count": len(document["records"]),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"Wrote {summary['record_count']} validated direct records to "
            f"{summary['output']} ({summary['sha256']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
