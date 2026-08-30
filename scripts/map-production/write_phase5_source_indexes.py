#!/usr/bin/env python3
"""Write immutable, hash-locked world-v3 Phase 5 source indexes.

The Phase 5 dependency chain is deliberately incremental:

``idx17``
    The fourteen region, one corridor, and two settlement canonical-render
    masters.
``idx22``
    ``idx17`` plus five independently reviewed continent composites.
``idx23``
    ``idx22`` plus the independently reviewed world composite.

Each invocation writes exactly one schema-1.3 source index.  Later stages must
name the previous immutable index with ``--base-index`` and may add only the
expected next records.  Artifact hashes are calculated from repository bytes;
an input hash, when supplied, is treated as a lock and must already match.

Before installation, the candidate is parsed by ``build_phase5_assets`` using
the checked-in schema, bound to the accepted Golden manifest entry, and every
source is run through the builder's full provenance/automated/Vision preflight.
Existing output files are never overwritten unless ``--force`` is explicit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, Sequence

import build_phase5_assets as phase5
from release_bound_artifact import (
    BoundArtifact as _BoundRepoFile,
    BoundArtifactError,
    assert_bindings_unchanged,
    bind_file,
    merge_bindings,
    path_identity,
)
from release_path_safety import (
    ReleasePathError,
    canonical_repo_relative,
    require_trackable_path,
    same_path,
)


WRITER_ID = "sstory-map-production/write_phase5_source_indexes.py@2"
DEFAULT_OUTPUT_DIR = (
    phase5.REPO_ROOT
    / "world"
    / "map-production"
    / "releases"
    / "world-v3-source-indexes"
)
TRACKED_RELEASE_ROOT = phase5.REPO_ROOT / "world" / "map-production" / "releases"
STAGE_FILENAMES = {
    "idx17": "world-v3-source-index-idx17.json",
    "idx22": "world-v3-source-index-idx22.json",
    "idx23": "world-v3-source-index-idx23.json",
}
STAGE_COUNTS = {"idx17": 17, "idx22": 22, "idx23": 23}
DIRECT_TYPES = frozenset({"region", "corridor", "settlement"})
EXPECTED_REGION_IDS = frozenset(
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
    }
)
EXPECTED_CORRIDOR_IDS = frozenset({"sheet_corridor_astralis_port_zephia"})
EXPECTED_SETTLEMENT_IDS = frozenset(
    {"sheet_settlement_astralis", "sheet_settlement_port_zephia"}
)
EXPECTED_CONTINENT_IDS = frozenset(
    {
        "sheet_continent_elysion",
        "sheet_continent_lumiera",
        "sheet_continent_chaos_ria",
        "sheet_continent_atlantis",
        "sheet_continent_grimoire",
    }
)
EXPECTED_WORLD_IDS = frozenset({"sheet_world"})
EXPECTED_DIRECT_IDS = (
    EXPECTED_REGION_IDS | EXPECTED_CORRIDOR_IDS | EXPECTED_SETTLEMENT_IDS
)


class SourceIndexWriterError(RuntimeError):
    """Raised when an immutable source index cannot be proven valid."""


@dataclass(frozen=True)
class _CanonicalInputBindings:
    catalog: _BoundRepoFile
    contract: _BoundRepoFile
    control_index: _BoundRepoFile
    canon_sources: dict[str, _BoundRepoFile]

    def all_files(self) -> tuple[_BoundRepoFile, ...]:
        return (
            self.catalog,
            self.contract,
            self.control_index,
            *(self.canon_sources[role] for role in phase5.CANONICAL_GEOJSON_SOURCES),
        )


def _bind_repo_file(path: Path, label: str) -> _BoundRepoFile:
    """Read once and prove the pathname still names exactly those bytes."""

    try:
        return bind_file(path, label=label, trackable=True)
    except BoundArtifactError as exc:
        raise SourceIndexWriterError(f"cannot bind {label}: {exc}") from exc


def _assert_bound_files_unchanged(bindings: Iterable[_BoundRepoFile]) -> None:
    try:
        assert_bindings_unchanged(bindings)
    except BoundArtifactError as exc:
        raise SourceIndexWriterError(str(exc)) from exc


def _bind_canonical_inputs(
    catalog_path: Path,
    contract_path: Path,
    control_index_path: Path,
) -> _CanonicalInputBindings:
    return _CanonicalInputBindings(
        catalog=_bind_repo_file(catalog_path, "map catalog"),
        contract=_bind_repo_file(contract_path, "resolution contract"),
        control_index=_bind_repo_file(control_index_path, "canonical control index"),
        canon_sources={
            role: _bind_repo_file(path, f"canonical {role} source")
            for role, path in phase5.CANONICAL_GEOJSON_SOURCES.items()
        },
    )


def _load_bound_contract(
    bindings: _CanonicalInputBindings, *, scratch_parent: Path
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    """Derive the contract only from the exact bytes used in its hash lock."""

    try:
        with tempfile.TemporaryDirectory(
            prefix=".phase5-contract-snapshot-", dir=scratch_parent
        ) as temporary_name:
            snapshot_root = Path(temporary_name)
            catalog_snapshot = snapshot_root / "map-sheets.json"
            contract_snapshot = snapshot_root / "resolution-contract.json"
            catalog_snapshot.write_bytes(bindings.catalog.data)
            contract_snapshot.write_bytes(bindings.contract.data)
            return phase5.load_contract(contract_snapshot, catalog_snapshot)
    except (OSError, BoundArtifactError, phase5.Phase5BuildError) as exc:
        raise SourceIndexWriterError(str(exc)) from exc


def _canonical_render_context_from_bindings(
    bindings: _CanonicalInputBindings,
    golden_evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "golden_evidence": golden_evidence,
        "map_catalog": bindings.catalog.artifact(),
        "resolution_contract": bindings.contract.artifact(),
        "control_index": bindings.control_index.artifact(),
        "canon_sources": {
            role: bindings.canon_sources[role].artifact()
            for role in phase5.CANONICAL_GEOJSON_SOURCES
        },
    }


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


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceIndexWriterError(
            f"{label} is not valid UTF-8 JSON: {path}: {exc}"
        ) from exc


def _tracked_output_path(path: Path) -> Path:
    try:
        resolved, _ = require_trackable_path(
            path,
            label="source-index output",
            must_exist=False,
            require_file=False,
        )
        root, _ = canonical_repo_relative(
            TRACKED_RELEASE_ROOT, label="tracked release root"
        )
    except ReleasePathError as exc:
        raise SourceIndexWriterError(str(exc)) from exc
    try:
        common = os.path.commonpath((os.fspath(root), os.fspath(resolved)))
    except ValueError as exc:
        raise SourceIndexWriterError(
            "output must stay below the tracked release root "
            f"{phase5.repo_path(TRACKED_RELEASE_ROOT)}"
        ) from exc
    if os.path.normcase(common) != os.path.normcase(os.fspath(root)):
        raise SourceIndexWriterError(
            "output must stay below the tracked release root "
            f"{phase5.repo_path(TRACKED_RELEASE_ROOT)}"
        )
    if same_path(resolved, root):
        raise SourceIndexWriterError("output may not replace the release root itself")
    return resolved


def _artifact_path(value: Any, label: str) -> tuple[Path, str | None]:
    if isinstance(value, Path):
        raw_path: str | Path = value
        claimed = None
    elif isinstance(value, str):
        raw_path = value
        claimed = None
    elif isinstance(value, dict):
        unknown = set(value) - {"path", "sha256"}
        if unknown:
            raise SourceIndexWriterError(
                f"{label} has unsupported fields: {sorted(unknown)!r}"
            )
        raw_path = value.get("path")
        claimed = value.get("sha256")
        if claimed is not None and not isinstance(claimed, str):
            raise SourceIndexWriterError(f"{label}.sha256 must be a string")
    else:
        raise SourceIndexWriterError(
            f"{label} must be a repo-relative path or path/sha256 object"
        )
    try:
        path, _ = require_trackable_path(raw_path, label=label)
    except ReleasePathError as exc:
        raise SourceIndexWriterError(str(exc)) from exc
    return path, claimed


def _lock_artifact(value: Any, label: str) -> dict[str, str]:
    path, claimed = _artifact_path(value, label)
    actual = phase5.sha256_file(path)
    if claimed is not None and claimed.lower() != actual:
        raise SourceIndexWriterError(
            f"{label}.sha256 mismatch: record={claimed.lower()}, actual={actual}"
        )
    return {"path": phase5.repo_path(path), "sha256": actual}


def _normalise_record(raw: Any, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SourceIndexWriterError(f"{label} must be an object")
    allowed = {
        "sheet_id",
        "kind",
        "path",
        "sha256",
        "provenance_report",
        "automated_report",
        "vision_reports",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise SourceIndexWriterError(
            f"{label} has unsupported fields: {sorted(unknown)!r}"
        )
    sheet_id = raw.get("sheet_id")
    if not isinstance(sheet_id, str) or not sheet_id:
        raise SourceIndexWriterError(f"{label}.sheet_id must be a non-empty string")
    kind = raw.get("kind")
    if kind not in {phase5.CANONICAL_RENDER_SOURCE_KIND, "composite_master"}:
        raise SourceIndexWriterError(
            f"{label}.kind must be canonical_render_master or composite_master"
        )
    if "path" not in raw:
        raise SourceIndexWriterError(f"{label}.path is required")
    master_value: Any = {"path": raw["path"]}
    if "sha256" in raw:
        master_value["sha256"] = raw["sha256"]
    locked_master = _lock_artifact(master_value, f"{label}.master")
    for field in ("provenance_report", "automated_report"):
        if field not in raw:
            raise SourceIndexWriterError(f"{label}.{field} is required")
    vision = raw.get("vision_reports")
    if not isinstance(vision, list) or not vision:
        raise SourceIndexWriterError(
            f"{label}.vision_reports must contain at least one report"
        )
    return {
        "sheet_id": sheet_id,
        "kind": kind,
        **locked_master,
        "provenance_report": _lock_artifact(
            raw["provenance_report"], f"{label}.provenance_report"
        ),
        "automated_report": _lock_artifact(
            raw["automated_report"], f"{label}.automated_report"
        ),
        "vision_reports": [
            _lock_artifact(item, f"{label}.vision_reports[{index}]")
            for index, item in enumerate(vision)
        ],
    }


def _record_values(path: Path) -> Iterable[Any]:
    try:
        path, _ = require_trackable_path(path, label="sheet record file")
    except ReleasePathError as exc:
        raise SourceIndexWriterError(str(exc)) from exc
    value = _load_json(path, "sheet record file")
    if isinstance(value, list):
        yield from value
        return
    if isinstance(value, dict) and "records" in value:
        unknown = set(value) - {"schema_version", "release_id", "records"}
        if unknown:
            raise SourceIndexWriterError(
                f"sheet record bundle has unsupported fields: {sorted(unknown)!r}"
            )
        if value.get("schema_version") not in {None, "1.0.0"}:
            raise SourceIndexWriterError(
                "sheet record bundle schema_version must be '1.0.0'"
            )
        if value.get("release_id") not in {None, phase5.DEFAULT_PUBLIC_RELEASE_ID}:
            raise SourceIndexWriterError(
                f"sheet record bundle release_id must be {phase5.DEFAULT_PUBLIC_RELEASE_ID!r}"
            )
        records = value["records"]
        if not isinstance(records, list):
            raise SourceIndexWriterError("sheet record bundle records must be an array")
        yield from records
        return
    yield value


def load_records(paths: Sequence[Path]) -> dict[str, dict[str, Any]]:
    if not paths:
        raise SourceIndexWriterError("at least one --records file is required")
    records: dict[str, dict[str, Any]] = {}
    position = 0
    for path in paths:
        for raw in _record_values(path):
            record = _normalise_record(raw, f"records[{position}]")
            sheet_id = record["sheet_id"]
            if sheet_id in records:
                raise SourceIndexWriterError(
                    f"sheet records duplicate sheet_id {sheet_id!r}"
                )
            records[sheet_id] = record
            position += 1
    return records


def _expected_stage_ids(
    stage: str, catalog_by_id: dict[str, dict[str, Any]]
) -> set[str]:
    regions = {
        sheet_id
        for sheet_id, sheet in catalog_by_id.items()
        if sheet.get("sheet_type") == "region"
    }
    corridors = {
        sheet_id
        for sheet_id, sheet in catalog_by_id.items()
        if sheet.get("sheet_type") == "corridor"
    }
    settlements = {
        sheet_id
        for sheet_id, sheet in catalog_by_id.items()
        if sheet.get("sheet_type") == "settlement"
    }
    continents = {
        sheet_id
        for sheet_id, sheet in catalog_by_id.items()
        if sheet.get("sheet_type") == "continent"
    }
    worlds = {
        sheet_id
        for sheet_id, sheet in catalog_by_id.items()
        if sheet.get("sheet_type") == "world"
    }
    expected_groups = (
        ("regions", regions, EXPECTED_REGION_IDS),
        ("corridors", corridors, EXPECTED_CORRIDOR_IDS),
        ("settlements", settlements, EXPECTED_SETTLEMENT_IDS),
        ("continents", continents, EXPECTED_CONTINENT_IDS),
        ("worlds", worlds, EXPECTED_WORLD_IDS),
    )
    mismatches = [
        f"{label}: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        for label, actual, expected in expected_groups
        if actual != expected
    ]
    if mismatches:
        raise SourceIndexWriterError(
            "canonical bounded catalog composition mismatch: " + "; ".join(mismatches)
        )
    direct = regions | corridors | settlements
    if stage == "idx17":
        return direct
    if stage == "idx22":
        return direct | continents
    if stage == "idx23":
        return direct | continents | worlds
    raise SourceIndexWriterError(f"unsupported source-index stage: {stage!r}")


def _expected_new_ids(stage: str, catalog_by_id: dict[str, dict[str, Any]]) -> set[str]:
    current = _expected_stage_ids(stage, catalog_by_id)
    if stage == "idx17":
        return current
    previous = _expected_stage_ids(
        "idx17" if stage == "idx22" else "idx22", catalog_by_id
    )
    return current - previous


def _kind_for_sheet(sheet: dict[str, Any]) -> str:
    if sheet.get("sheet_type") in DIRECT_TYPES:
        return phase5.CANONICAL_RENDER_SOURCE_KIND
    return "composite_master"


def _load_base_index(
    path: Path,
    *,
    expected_ids: set[str],
    known_ids: set[str],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, str],
    dict[str, _BoundRepoFile],
]:
    try:
        indexed, index_sha256, golden = phase5.load_source_index(path, known_ids)
    except phase5.Phase5BuildError as exc:
        raise SourceIndexWriterError(f"base source index is invalid: {exc}") from exc
    if golden is None:
        raise SourceIndexWriterError("base source index does not lock a Golden style")
    if set(indexed) != expected_ids:
        raise SourceIndexWriterError(
            "base source index has the wrong immutable stage coverage: "
            f"missing={sorted(expected_ids - set(indexed))}, "
            f"extra={sorted(set(indexed) - expected_ids)}"
        )
    bindings = {
        bound.identity: bound for bound in phase5.source_index_bound_artifacts(indexed)
    }
    index_binding = bindings.get(path_identity(path))
    if index_binding is None or index_binding.sha256 != index_sha256:
        raise SourceIndexWriterError(
            "base source index parser/hash binding is incomplete or inconsistent"
        )
    normalised: dict[str, dict[str, Any]] = {}
    with phase5.bound_artifact_context(bindings):
        for position, sheet_id in enumerate(sorted(indexed)):
            public = {
                key: value
                for key, value in indexed[sheet_id].items()
                if not key.startswith("_phase5_")
            }
            normalised[sheet_id] = _normalise_record(
                public, f"base sources[{position}]"
            )
    return normalised, golden, bindings


def _ordered_sources(
    records: dict[str, dict[str, Any]],
    catalog: dict[str, Any],
) -> list[dict[str, Any]]:
    order = {
        sheet["id"]: position
        for position, sheet in enumerate(catalog.get("sheets", []))
        if isinstance(sheet, dict) and isinstance(sheet.get("id"), str)
    }
    return [records[sheet_id] for sheet_id in sorted(records, key=order.__getitem__)]


def _require_canonical_build_input(actual: Path, expected: Path, label: str) -> Path:
    try:
        actual_resolved, _ = require_trackable_path(actual, label=label)
        expected_resolved, _ = require_trackable_path(
            expected, label=f"canonical {label}"
        )
    except ReleasePathError as exc:
        raise SourceIndexWriterError(str(exc)) from exc
    if not same_path(actual_resolved, expected_resolved):
        raise SourceIndexWriterError(
            f"{label} must be the checked-in canonical input "
            f"{phase5.repo_path(expected_resolved)}"
        )
    return actual_resolved


def _resolve_evidence_reference(
    raw_path: str,
    document_path: Path,
    label: str,
    *,
    report_relative: bool,
) -> Path:
    if "://" in raw_path:
        raise SourceIndexWriterError(
            f"{label} must be a hashable repository artifact, not a URL"
        )
    if report_relative:
        if not raw_path or "\\" in raw_path:
            raise SourceIndexWriterError(
                f"{label} must be a provenance-report-relative POSIX path"
            )
        lexical_parts = raw_path.split("/")
        portable = PurePosixPath(raw_path)
        if portable.is_absolute() or any(
            part in {"", ".", ".."} for part in lexical_parts
        ):
            raise SourceIndexWriterError(
                f"{label} must stay inside the provenance report directory"
            )
        candidate: str | Path = document_path.parent.joinpath(*portable.parts)
    else:
        # Every schema field other than Phase 5 provenance artifacts[].path
        # uses the builder's explicit repository-root-relative convention.
        candidate = raw_path
    try:
        resolved, _ = require_trackable_path(candidate, label=label)
    except ReleasePathError as exc:
        scope = "report-relative" if report_relative else "repository-relative"
        raise SourceIndexWriterError(
            f"{label} is not a trackable {scope} artifact: {exc}"
        ) from exc
    if report_relative:
        report_root = document_path.parent.resolve()
        try:
            resolved.relative_to(report_root)
        except ValueError as exc:
            raise SourceIndexWriterError(
                f"{label} escapes the provenance report directory"
            ) from exc
    return resolved


def _json_path_references(
    value: Any, location: str = "$"
) -> Iterable[tuple[str, str | None, str, bool]]:
    """Yield path locks with their schema-defined resolution semantics."""

    provenance_document = (
        isinstance(value, dict)
        and value.get("schema_version") == "1.0.0"
        and value.get("generated_by") == phase5.GENERATOR_ID
        and isinstance(value.get("artifacts"), list)
    )

    def walk(
        item: Any,
        item_location: str,
        *,
        provenance_artifact_record: bool = False,
    ) -> Iterable[tuple[str, str | None, str, bool]]:
        if isinstance(item, list):
            for index, child in enumerate(item):
                yield from walk(
                    child,
                    f"{item_location}[{index}]",
                    provenance_artifact_record=(
                        provenance_document and item_location == "$.artifacts"
                    ),
                )
            return
        if not isinstance(item, dict):
            return
        for key, raw_path in item.items():
            if not isinstance(raw_path, str):
                continue
            folded_key = key.casefold()
            if folded_key == "path":
                hash_key = next(
                    (
                        candidate
                        for candidate in item
                        if candidate.casefold() == "sha256"
                    ),
                    None,
                )
            elif folded_key.endswith("_path"):
                wanted = folded_key[: -len("_path")] + "_sha256"
                hash_key = next(
                    (candidate for candidate in item if candidate.casefold() == wanted),
                    None,
                )
            else:
                hash_key = None
            if folded_key == "path" or folded_key.endswith("_path"):
                claimed = item.get(hash_key) if hash_key is not None else None
                if claimed is not None and not isinstance(claimed, str):
                    raise SourceIndexWriterError(
                        f"{item_location}.{hash_key} must be a SHA-256 string"
                    )
                yield (
                    raw_path,
                    claimed,
                    f"{item_location}.{key}",
                    provenance_artifact_record and folded_key == "path",
                )
        for key, child in item.items():
            yield from walk(child, f"{item_location}.{key}")

    yield from walk(value, location)


def _audit_artifact_graph(
    root_specs: Iterable[dict[str, str]],
) -> dict[str, _BoundRepoFile]:
    """Bind every reachable artifact to the exact bytes accepted by the audit."""

    roots: list[_BoundRepoFile] = []
    for index, spec in enumerate(root_specs):
        path, claimed = _artifact_path(spec, f"artifact graph roots[{index}]")
        bound = _bind_repo_file(path, f"artifact graph roots[{index}]")
        if claimed is not None and claimed.lower() != bound.sha256:
            raise SourceIndexWriterError(
                f"artifact graph roots[{index}].sha256 mismatch: "
                f"record={claimed.lower()}, actual={bound.sha256}"
            )
        roots.append(bound)
    try:
        return phase5.bind_phase5_artifact_graph(roots)
    except phase5.Phase5BuildError as exc:
        raise SourceIndexWriterError(str(exc)) from exc


@contextmanager
def _exclusive_output_lock(output: Path) -> Iterator[None]:
    lock_path = output.with_name(f".{output.name}.source-index.lock")
    descriptor: int | None = None
    lock_created = False
    try:
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise SourceIndexWriterError(
                f"another writer owns the output lock: {lock_path}"
            ) from exc
        lock_created = True
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if lock_created:
            lock_path.unlink(missing_ok=True)


def _source_index_transaction_debris(output: Path) -> list[Path]:
    """Find candidate/backup debris from every historical transaction."""

    prefixes = tuple(
        f".{output.name}{suffix}".casefold() for suffix in (".backup-", ".rollback-")
    )
    candidate_prefix = f".{output.name}.".casefold()
    try:
        entries = os.scandir(output.parent)
    except OSError as exc:
        raise SourceIndexWriterError(
            f"cannot inspect source-index transaction directory: {output.parent}: {exc}"
        ) from exc
    with entries:
        return sorted(
            (
                Path(entry.path)
                for entry in entries
                if entry.name.casefold().startswith(prefixes)
                or (
                    entry.name.casefold().startswith(candidate_prefix)
                    and entry.name.casefold().endswith(".candidate")
                )
            ),
            key=lambda path: path.name.casefold(),
        )


def _validate_candidate(
    path: Path,
    *,
    golden_style: dict[str, str],
    base_manifest: _BoundRepoFile,
    canonical_inputs: _CanonicalInputBindings,
    catalog_by_id: dict[str, dict[str, Any]],
    contracts: dict[str, dict[str, Any]],
) -> dict[str, _BoundRepoFile]:
    known_ids = set(contracts)
    try:
        indexed, _, loaded_golden = phase5.load_source_index(path, known_ids)
        if loaded_golden != golden_style:
            raise SourceIndexWriterError(
                "candidate Golden style changed during schema/parser validation"
            )
        candidate_bindings = {
            bound.identity: bound
            for bound in phase5.source_index_bound_artifacts(indexed)
        }
        with phase5.bound_artifact_context(candidate_bindings):
            base_bindings = phase5.bind_manifest_golden_evidence(
                golden_style, base_manifest
            )
        canonical_bindings = phase5.bind_phase5_artifact_graph(
            canonical_inputs.all_files()
        )
        all_bindings = merge_bindings(
            (
                *candidate_bindings.values(),
                *base_bindings.values(),
                *canonical_bindings.values(),
            )
        )
        with phase5.bound_artifact_context(all_bindings):
            golden_evidence = phase5.verify_manifest_golden_style(
                golden_style, base_manifest.path
            )
            canonical_context = _canonical_render_context_from_bindings(
                canonical_inputs, golden_evidence
            )
            for entry in indexed.values():
                entry[phase5.INTERNAL_BOUND_ARTIFACTS_KEY] = all_bindings
                if entry.get("kind") == phase5.CANONICAL_RENDER_SOURCE_KIND:
                    entry[phase5.INTERNAL_CANONICAL_CONTEXT_KEY] = canonical_context
            for sheet_id in indexed:
                phase5.preflight_source_entry(
                    indexed[sheet_id],
                    sheet=catalog_by_id[sheet_id],
                    contract=contracts[sheet_id],
                    catalog_by_id=catalog_by_id,
                    sources=indexed,
                )
        _assert_bound_files_unchanged(all_bindings.values())
        return all_bindings
    except (OSError, BoundArtifactError, phase5.Phase5BuildError) as exc:
        raise SourceIndexWriterError(
            f"build_phase5_assets rejected the candidate source index: {exc}"
        ) from exc


def _write_source_index_locked(
    *,
    stage: str,
    record_paths: Sequence[Path],
    output_path: Path,
    golden_style_path: Path | None = None,
    base_index_path: Path | None = None,
    base_manifest_path: Path = phase5.DEFAULT_BASE_MANIFEST,
    catalog_path: Path = phase5.DEFAULT_MAP_SHEETS,
    contract_path: Path = phase5.DEFAULT_CONTRACT,
    control_index_path: Path = phase5.DEFAULT_CANONICAL_CONTROL_INDEX,
    force: bool = False,
) -> dict[str, Any]:
    if stage not in STAGE_FILENAMES:
        raise SourceIndexWriterError(f"unsupported source-index stage: {stage!r}")
    output = _tracked_output_path(output_path)
    if output.exists() and not output.is_file():
        raise SourceIndexWriterError(
            f"source-index output must be a file path: {output}"
        )
    if output.exists() and not force:
        raise SourceIndexWriterError(
            f"refusing to overwrite immutable source index: {output}"
        )
    catalog_path = _require_canonical_build_input(
        catalog_path, phase5.DEFAULT_MAP_SHEETS, "map catalog"
    )
    contract_path = _require_canonical_build_input(
        contract_path, phase5.DEFAULT_CONTRACT, "resolution contract"
    )
    control_index_path = _require_canonical_build_input(
        control_index_path,
        phase5.DEFAULT_CANONICAL_CONTROL_INDEX,
        "canonical control index",
    )
    canonical_inputs = _bind_canonical_inputs(
        catalog_path, contract_path, control_index_path
    )
    base_manifest = _bind_repo_file(base_manifest_path, "base production manifest")
    catalog, catalog_by_id, derived = _load_bound_contract(
        canonical_inputs, scratch_parent=output.parent
    )
    contracts = derived["sheets"]
    expected_ids = _expected_stage_ids(stage, catalog_by_id)
    expected_new_ids = _expected_new_ids(stage, catalog_by_id)
    known_ids = set(contracts)
    base_index_bindings: dict[str, _BoundRepoFile] = {}

    if stage == "idx17":
        if base_index_path is not None:
            raise SourceIndexWriterError("idx17 may not use --base-index")
        if golden_style_path is None:
            raise SourceIndexWriterError("idx17 requires --golden-style")
        golden_style = _lock_artifact(golden_style_path, "golden_style")
        base_records: dict[str, dict[str, Any]] = {}
    else:
        if base_index_path is None:
            raise SourceIndexWriterError(f"{stage} requires --base-index")
        try:
            base_index_path, _ = require_trackable_path(
                base_index_path, label="base source index"
            )
        except ReleasePathError as exc:
            raise SourceIndexWriterError(str(exc)) from exc
        if same_path(base_index_path, output):
            raise SourceIndexWriterError(
                "a later stage may not replace its immutable base source index"
            )
        previous_stage = "idx17" if stage == "idx22" else "idx22"
        base_records, golden_style, base_index_bindings = _load_base_index(
            base_index_path,
            expected_ids=_expected_stage_ids(previous_stage, catalog_by_id),
            known_ids=known_ids,
        )
        if golden_style_path is not None:
            explicit_golden = _lock_artifact(golden_style_path, "golden_style")
            if explicit_golden != golden_style:
                raise SourceIndexWriterError(
                    "explicit Golden style does not match the immutable base index"
                )

    new_records = load_records(record_paths)
    if set(new_records) != expected_new_ids:
        raise SourceIndexWriterError(
            f"{stage} requires exactly its next-stage sheet records: "
            f"missing={sorted(expected_new_ids - set(new_records))}, "
            f"extra={sorted(set(new_records) - expected_new_ids)}"
        )
    combined = {**base_records, **new_records}
    if set(combined) != expected_ids or len(combined) != STAGE_COUNTS[stage]:
        raise SourceIndexWriterError(
            f"{stage} must cover exactly {STAGE_COUNTS[stage]} bounded sheets"
        )
    for sheet_id, record in combined.items():
        expected_kind = _kind_for_sheet(catalog_by_id[sheet_id])
        if record["kind"] != expected_kind:
            raise SourceIndexWriterError(
                f"{sheet_id} requires kind {expected_kind!r}, found {record['kind']!r}"
            )

    document = {
        "schema_version": "1.3.0",
        "coordinate_reference_system": "EA-WORLD-1",
        "golden_style": golden_style,
        "sources": _ordered_sources(combined, catalog),
    }
    artifact_bindings = _audit_artifact_graph(
        [
            golden_style,
            *(
                spec
                for source in document["sources"]
                for spec in (
                    {"path": source["path"], "sha256": source["sha256"]},
                    source["provenance_report"],
                    source["automated_report"],
                    *source["vision_reports"],
                )
            ),
        ]
    )
    debris = _source_index_transaction_debris(output)
    if debris:
        raise SourceIndexWriterError(
            "stale source-index backup or transaction debris exists: "
            + ", ".join(str(path) for path in debris)
        )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".candidate", dir=output.parent
    )
    temporary = Path(temporary_name)
    transaction_id = uuid.uuid4().hex
    backup = output.with_name(f".{output.name}.backup-{transaction_id}")
    backup_created = False
    installed = False
    install_attempted = False
    force_replacement = False
    committed = False
    prepared_sha256: str | None = None
    execution_registry = merge_bindings(
        (
            *canonical_inputs.all_files(),
            base_manifest,
            *base_index_bindings.values(),
            *artifact_bindings.values(),
        )
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_stable_json_bytes(document))
        prepared_sha256 = phase5.sha256_file(temporary)
        candidate_identity = (
            os.stat(temporary, follow_symlinks=False).st_dev,
            os.stat(temporary, follow_symlinks=False).st_ino,
        )
        _assert_bound_files_unchanged(execution_registry.values())
        with phase5.bound_artifact_context(execution_registry):
            initial_validation = _validate_candidate(
                temporary,
                golden_style=golden_style,
                base_manifest=base_manifest,
                canonical_inputs=canonical_inputs,
                catalog_by_id=catalog_by_id,
                contracts=contracts,
            )
        if isinstance(initial_validation, dict):
            execution_registry = merge_bindings(
                (
                    *execution_registry.values(),
                    *(
                        bound
                        for bound in initial_validation.values()
                        if bound.identity != path_identity(temporary)
                    ),
                )
            )
        _assert_bound_files_unchanged(execution_registry.values())
        if output.exists():
            if not force:
                raise SourceIndexWriterError(
                    "output appeared during no-clobber source-index creation"
                )
            os.link(output, backup)
            backup_created = True
            force_replacement = True
        install_attempted = True
        if force_replacement:
            # os.replace is one filesystem operation on the same volume: the
            # old pathname is never unlinked before the new bytes become live.
            os.replace(temporary, output)
        else:
            try:
                os.link(temporary, output)
            except FileExistsError as exc:
                raise SourceIndexWriterError(
                    "output appeared during atomic no-clobber source-index installation"
                ) from exc
        installed = True
        if phase5.sha256_file(output) != prepared_sha256:
            raise SourceIndexWriterError(
                "installed source-index bytes differ from the validated candidate"
            )
        # Keep the backup until every fallible installed-path check completes.
        with phase5.bound_artifact_context(execution_registry):
            installed_validation = _validate_candidate(
                output,
                golden_style=golden_style,
                base_manifest=base_manifest,
                canonical_inputs=canonical_inputs,
                catalog_by_id=catalog_by_id,
                contracts=contracts,
            )
        if isinstance(installed_validation, dict):
            execution_registry = merge_bindings(
                (*execution_registry.values(), *installed_validation.values())
            )
        _assert_bound_files_unchanged(execution_registry.values())
        output_binding = execution_registry.get(path_identity(output))
        if output_binding is None or output_binding.sha256 != prepared_sha256:
            raise SourceIndexWriterError(
                "installed source-index parser/hash binding is incomplete"
            )
        base_index_binding = (
            execution_registry.get(path_identity(base_index_path))
            if base_index_path is not None
            else None
        )
        if base_index_path is not None and base_index_binding is None:
            raise SourceIndexWriterError(
                "base source index disappeared from the final byte binding"
            )
        result = {
            "valid": True,
            "committed": True,
            "written_by": WRITER_ID,
            "stage": stage,
            "source_count": len(document["sources"]),
            "output": phase5.repo_path(output),
            "sha256": output_binding.sha256,
            "golden_style": golden_style,
            "base_index": (
                {
                    "path": phase5.repo_path(base_index_path.resolve()),
                    "sha256": base_index_binding.sha256,
                }
                if base_index_path is not None and base_index_binding is not None
                else None
            ),
        }
        _assert_bound_files_unchanged(execution_registry.values())
        # Result construction and all installed-path validation are complete.
        # All remaining cleanup is post-commit and can never trigger rollback.
        committed = True
        cleanup_errors: list[str] = []
        for cleanup_path in (backup if backup_created else None, temporary):
            if cleanup_path is None or not os.path.lexists(cleanup_path):
                continue
            try:
                cleanup_path.unlink()
                if same_path(cleanup_path, backup):
                    backup_created = False
            except BaseException as exc:
                cleanup_errors.append(f"{cleanup_path}: {exc}")
        result["cleanup"] = {
            "complete": not cleanup_errors,
            "errors": cleanup_errors,
        }
        return result
    except BaseException:
        if committed:
            return result
        if install_attempted and not installed and os.path.lexists(output):
            try:
                metadata = os.stat(output, follow_symlinks=False)
                installed = (metadata.st_dev, metadata.st_ino) == candidate_identity
            except OSError:
                installed = False
        if force_replacement and backup_created and os.path.lexists(backup):
            if installed:
                os.replace(backup, output)
                backup_created = False
            else:
                backup.unlink()
                backup_created = False
        elif installed and os.path.lexists(output):
            try:
                if os.path.samefile(output, temporary):
                    output.unlink()
            except OSError:
                pass
        raise
    finally:
        if not committed and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def write_source_index(
    *,
    stage: str,
    record_paths: Sequence[Path],
    output_path: Path,
    golden_style_path: Path | None = None,
    base_index_path: Path | None = None,
    base_manifest_path: Path = phase5.DEFAULT_BASE_MANIFEST,
    catalog_path: Path = phase5.DEFAULT_MAP_SHEETS,
    contract_path: Path = phase5.DEFAULT_CONTRACT,
    control_index_path: Path = phase5.DEFAULT_CANONICAL_CONTROL_INDEX,
    force: bool = False,
) -> dict[str, Any]:
    output = _tracked_output_path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        require_trackable_path(
            output,
            label="source-index output",
            must_exist=False,
            require_file=False,
        )
    except ReleasePathError as exc:
        raise SourceIndexWriterError(str(exc)) from exc
    with _exclusive_output_lock(output):
        return _write_source_index_locked(
            stage=stage,
            record_paths=record_paths,
            output_path=output,
            golden_style_path=golden_style_path,
            base_index_path=base_index_path,
            base_manifest_path=base_manifest_path,
            catalog_path=catalog_path,
            contract_path=contract_path,
            control_index_path=control_index_path,
            force=force,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=tuple(STAGE_FILENAMES), required=True)
    parser.add_argument(
        "--records",
        action="append",
        type=Path,
        required=True,
        help=(
            "JSON record, record array, or {schema_version, release_id, records} "
            "bundle; repeatable"
        ),
    )
    parser.add_argument(
        "--golden-style",
        type=Path,
        help="required for idx17; optional exact-match assertion for later stages",
    )
    parser.add_argument(
        "--base-index",
        type=Path,
        help="required idx17 source index for idx22 or idx22 source index for idx23",
    )
    parser.add_argument(
        "--base-manifest", type=Path, default=phase5.DEFAULT_BASE_MANIFEST
    )
    parser.add_argument("--catalog", type=Path, default=phase5.DEFAULT_MAP_SHEETS)
    parser.add_argument("--contract", type=Path, default=phase5.DEFAULT_CONTRACT)
    parser.add_argument(
        "--canonical-control-index",
        type=Path,
        default=phase5.DEFAULT_CANONICAL_CONTROL_INDEX,
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="immutable output path below world/map-production/releases",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output or DEFAULT_OUTPUT_DIR / STAGE_FILENAMES[args.stage]
    try:
        result = write_source_index(
            stage=args.stage,
            record_paths=args.records,
            output_path=output,
            golden_style_path=args.golden_style,
            base_index_path=args.base_index,
            base_manifest_path=args.base_manifest,
            catalog_path=args.catalog,
            contract_path=args.contract,
            control_index_path=args.canonical_control_index,
            force=args.force,
        )
    except (OSError, ValueError, SourceIndexWriterError) as exc:
        result = {"valid": False, "error": str(exc)}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result.get("valid"):
        print(
            f"Phase 5 {result['stage']} source index created: "
            f"{result['output']} sha256={result['sha256']}"
        )
    else:
        print(f"Phase 5 source-index writer failed: {result['error']}", file=sys.stderr)
    return 0 if result.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
