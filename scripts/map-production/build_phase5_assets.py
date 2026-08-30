#!/usr/bin/env python3
"""Plan and build the bounded Phase 5 map assets without bypassing QA.

The builder deliberately separates *materialization* from *acceptance*:

* exact sheet masters with hashed, complete QA evidence may be imported as
  accepted;
* metatile assemblies, deterministic parent composites, and style-seeded
  placeholders are emitted only as ``generated`` jobs with draft QA reports;
* missing high-resolution inputs remain ``planned`` unless the caller opts in
  to visibly provisional style seeding;
* the public region-raster index and release tiles contain accepted inputs
  only.

This makes the useful deterministic parts of Phase 5 reproducible while
preventing a crop or upscale of the golden style board from being labelled as
production-ready geography.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import posixpath
import shutil
import sys
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, Sequence
from urllib.parse import urlsplit

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageStat

from create_qa_report import build_report, markdown_report
from generate_tiles import generate_pyramid
import phase5_vision_evidence as vision_evidence
from promote_phase5_renderer_outputs import (
    RendererPromotionError,
    _rename_directory_no_replace,
)
import promote_style_candidate_k3_golden_v3 as golden_v3_promotion
from release_bound_artifact import (
    BoundArtifact,
    BoundArtifactError,
    assert_bindings_unchanged,
    bind_file,
    path_identity,
)
from release_path_safety import ReleasePathError, require_trackable_path
from reviewer_identity import (
    INDEPENDENT_VISION_REVIEW_ROLES,
    canonical_reviewer_identity,
)
from production_common import (
    ID_PATTERN,
    REPO_ROOT,
    ValidationFailure,
    dump_json,
    load_json,
    parse_rfc3339,
    utc_now,
)
from validate_manifest import schema_errors, validate_manifest
from validate_resolution_contract import (
    DEFAULT_CONTRACT,
    DEFAULT_MAP_SHEETS,
    validate_resolution_contract,
)


GENERATOR_ID = "sstory-map-production/build_phase5_assets.py@2"
BUILD_REPORT_SCHEMA_VERSION = "1.1.0"
BUILDER_SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_BASE_MANIFEST = (
    REPO_ROOT / "world" / "map-production" / "production-manifest.json"
)
DEFAULT_CONTROL_MASTER = (
    REPO_ROOT / "world" / "map-production" / "controls" / "world-control-v1.png"
)
DEFAULT_SOURCE_INDEX_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-source-index.schema.json"
)
DEFAULT_QA_REPORT_SCHEMA = (
    REPO_ROOT / "world" / "map-production" / "schemas" / "qa-report.schema.json"
)
DEFAULT_GENERATION_RECEIPT_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-generation-receipt.schema.json"
)
DEFAULT_AUTOMATED_QA_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-automated-qa.schema.json"
)
DEFAULT_POSTPROCESS_REPORT_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-postprocess-report.schema.json"
)
DEFAULT_CANONICAL_RENDER_PROVENANCE_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-canonical-render-provenance.schema.json"
)
DEFAULT_CANONICAL_CONTROL_INDEX = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "controls"
    / "phase5-metatiles"
    / "index.json"
)
DEFAULT_SHEET_TILE_INDEX_SCHEMA = (
    REPO_ROOT / "world" / "map-production" / "schemas" / "sheet-tile-index.schema.json"
)
DEFAULT_TILE_MANIFEST_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "sheet-tile-manifest.schema.json"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "tmp" / "map-production" / "phase5-build-v1"
DEFAULT_PUBLIC_RELEASE_ID = "world-v3"
TARGET_STAGES = ("idx22", "idx23", "final")
EXPECTED_PHASE5_TILE_COUNT = 1350
PUBLIC_INDEX_CANONICAL_PATH = PurePosixPath("data/map/sheet-tiles-v3.json")
PUBLIC_INDEX_COMPATIBILITY_PATH = PurePosixPath("data/map/region-rasters.json")
PUBLIC_TILE_BASE = PurePosixPath("assets/images/maps/tiles")
WORLD_EXTENT = 10000.0
GENERATION_TYPES = frozenset({"region", "corridor", "settlement"})
COMPOSITE_TYPES = frozenset({"world", "continent"})
RELEASE_STATES = frozenset({"accepted", "tiled", "staging", "published"})
SHEET_TYPE_ORDER = {
    "world": 0,
    "continent": 1,
    "region": 2,
    "corridor": 3,
    "settlement": 4,
}
MINIMUM_ALLOWED_OVERLAP_SSIM = 0.90
MAXIMUM_RGB_MEAN_DIFFERENCE = 4.0
MAXIMUM_RGB_P95_DIFFERENCE = 10
MINIMUM_LAND_SEA_MATCH_RATIO = 0.98
MINIMUM_TRANSPORT_WITHIN_TOLERANCE_RATIO = 0.95
AUTOMATED_QA_GENERATOR_ID = "sstory-map-production/audit_phase5_master.py@2"
POSTPROCESS_GENERATOR_ID = "sstory-map-production/composite_phase5_protected_tile.py@1"
INTERNAL_GOLDEN_STYLE_KEY = "_phase5_golden_style"
INTERNAL_CANONICAL_CONTEXT_KEY = "_phase5_canonical_render_context"
INTERNAL_BOUND_ARTIFACTS_KEY = "_phase5_bound_artifacts"
GOLDEN_ACCEPTANCE_RECEIPT_ROLE = "golden-acceptance-receipt"
GOLDEN_BLIND_PACKET_ROLE = "blind-review-packet"
# These roles are emitted by both the legacy v1 promoter and the v2
# promoter, so none of them can prove that a job began the v2 workflow.
# Falling back to the v1 verifier is still fail-closed: a truncated v2 job
# that contains only these shared roles must independently satisfy the full
# legacy evidence graph or it is rejected there.
GOLDEN_SHARED_PREPARED_ROLES = frozenset(
    {
        "golden-raw-output",
        "promotion-provenance",
        "persistent-automated-audit",
    }
)
GOLDEN_BLIND_PACKET_VIEW_IDS = (
    "native",
    "full25",
    "full50",
    "highland200",
    "highland400",
)
# Keep legacy-v2 dispatch data inert until the verifier has selected that
# compatibility-only path.  Importing the old promoter executes its pixel
# auditor, so a module-level import would run those bytes before the active-v3
# authority has had a chance to bind its strict-audit dependency closure.
GOLDEN_V2_PREPARED_INPUT_ROLES = frozenset(
    {
        "golden-raw-output",
        "promotion-provenance",
        "root-vision-authorization",
        "persistent-automated-audit",
        "deterministic-replay-output",
        "deterministic-replay-output-2",
        GOLDEN_BLIND_PACKET_ROLE,
        *(f"root-review-view-{name}" for name in GOLDEN_BLIND_PACKET_VIEW_IDS),
    }
)
GOLDEN_V2_PREPARED_ONLY_ROLES = frozenset(
    GOLDEN_V2_PREPARED_INPUT_ROLES - GOLDEN_SHARED_PREPARED_ROLES
)
_golden_v2_promotion: Any | None = None


def _load_golden_v2_promotion() -> Any:
    """Load the compatibility-only v2 verifier after dispatch selects it."""

    global _golden_v2_promotion
    if _golden_v2_promotion is None:
        module = importlib.import_module("promote_style_candidate_k3_golden_v2")
        if frozenset(module.PREPARED_INPUT_ROLES) != GOLDEN_V2_PREPARED_INPUT_ROLES:
            raise Phase5BuildError("Golden v2 prepared-input role set changed")
        _golden_v2_promotion = module
    return _golden_v2_promotion


GOLDEN_PHASE4_IMMEDIATE_FAILURE_IDS = (
    "eight-system-topology",
    "side-view-or-shared-projection",
    "panel-seam-or-body-halo",
    "white-particle-pill-hole-or-crater",
    "root-river-vein-fingerprint-or-contour",
    "fern-fishbone-dash-bundle-or-repetition",
    "no-200-to-400-information-gain",
    "protected-geometry-difference",
)
CANONICAL_RENDER_SOURCE_KIND = "canonical_render_master"
CANONICAL_RENDER_METHOD = "deterministic-canonical-render"
CANONICAL_RENDERER_ID = "sstory-map-production/render_phase5_reviewed_master.py@2.6"
CANONICAL_RENDERER_PATH = (
    REPO_ROOT / "scripts/map-production/render_phase5_reviewed_master.py"
)
DEFAULT_PHASE5_MATERIAL_ATLAS = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "style-assets"
    / "phase5-cartographic-material-atlas-v1.png"
)
RENDERER_SOURCE_ROLE_MAP = {
    "landmasses": "landmasses",
    "regions": "regions",
    "terrain": "terrain",
    "hydrography": "hydrography",
    "settlements": "settlement-footprints",
    "transport": "transport-geometries",
}
CANONICAL_GEOJSON_SOURCES = {
    "landmasses": REPO_ROOT / "world/map-production/source/landmasses.geojson",
    "regions": REPO_ROOT / "world/map-production/source/regions.geojson",
    "terrain": REPO_ROOT / "world/map-production/source/terrain.geojson",
    "hydrography": REPO_ROOT / "world/map-production/source/hydrography.geojson",
    "settlement-footprints": (
        REPO_ROOT / "world/map-production/source/settlement-footprints.geojson"
    ),
    "transport-geometries": (
        REPO_ROOT / "world/map-production/source/transport-geometries.geojson"
    ),
}

# ``phase-plan.md`` introduces these visual ecosystems for the first time in
# this order.  Their first sheet receives the conservative 94/two-review gate;
# later sheets in an already-established ecosystem retain the normal 90 gate.
FIRST_ECOLOGY_SHEETS = frozenset(
    {
        "sheet_region_royal_capital_region",  # urban
        "sheet_region_silver_plains_region",  # plains
        "sheet_region_soaring_mountains_region",  # mountain
        "sheet_region_moonlit_forest_region",  # forest
        "sheet_region_port_zephia_region",  # port
        "sheet_region_lumiera_arch_region",  # floating islands
        "sheet_region_emerald_belt_region",  # tropical
        "sheet_region_red_sea_desert_region",  # desert
        "sheet_region_jade_oasis_region",  # oasis
        "sheet_region_marineport_region",  # ocean/subsea
        "sheet_region_time_port_region",  # spacetime
    }
)


class Phase5BuildError(RuntimeError):
    """Raised when the builder cannot preserve the production contract."""


@dataclass(frozen=True)
class TargetStageContract:
    """Exact source, output, and generation coverage for one canonical build."""

    target_stage: str
    source_sheet_ids: tuple[str, ...]
    output_sheet_ids: tuple[str, ...]
    generated_composite_sheet_ids: tuple[str, ...]
    deferred_sheet_ids: tuple[str, ...]


def target_stage_contract(
    *,
    target_stage: str,
    catalog_by_id: dict[str, dict[str, Any]],
    contracts: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    tiles_requested: bool,
    allow_provisional: bool,
) -> TargetStageContract:
    """Validate the immutable idx17 -> idx22 -> idx23 -> final transition.

    This is deliberately called before an output root or staging directory is
    created.  Coverage and source kinds identify the source-index stage even
    though the public source-index schema does not carry a mutable stage label.
    """

    if target_stage not in TARGET_STAGES:
        raise Phase5BuildError(
            f"target_stage must be one of {', '.join(TARGET_STAGES)}"
        )
    if allow_provisional:
        raise Phase5BuildError(
            "canonical target-stage builds forbid provisional style seeding"
        )
    if target_stage == "final":
        if not tiles_requested:
            raise Phase5BuildError("final target stage requires --tiles")
    elif tiles_requested:
        raise Phase5BuildError(
            f"{target_stage} target stage forbids --tiles; only final may tile"
        )

    ordered_ids = tuple(contracts)
    direct_ids = tuple(
        sheet_id
        for sheet_id in ordered_ids
        if catalog_by_id[sheet_id].get("sheet_type") in GENERATION_TYPES
    )
    continent_ids = tuple(
        sheet_id
        for sheet_id in ordered_ids
        if catalog_by_id[sheet_id].get("sheet_type") == "continent"
    )
    world_ids = tuple(
        sheet_id
        for sheet_id in ordered_ids
        if catalog_by_id[sheet_id].get("sheet_type") == "world"
    )
    if len(direct_ids) != 17 or len(continent_ids) != 5 or len(world_ids) != 1:
        raise Phase5BuildError(
            "canonical bounded catalog must contain direct17, five continents, "
            "and one world"
        )

    if target_stage == "idx22":
        source_ids = direct_ids
        generated_ids = continent_ids
        output_ids = tuple(
            sheet_id
            for sheet_id in ordered_ids
            if sheet_id in set(direct_ids) | set(continent_ids)
        )
    elif target_stage == "idx23":
        source_ids = tuple(
            sheet_id
            for sheet_id in ordered_ids
            if sheet_id in set(direct_ids) | set(continent_ids)
        )
        generated_ids = world_ids
        output_ids = ordered_ids
    else:
        source_ids = ordered_ids
        generated_ids = ()
        output_ids = ordered_ids

    expected_source_set = set(source_ids)
    actual_source_set = set(sources)
    if actual_source_set != expected_source_set:
        raise Phase5BuildError(
            f"{target_stage} requires exact source-index coverage: "
            f"missing={sorted(expected_source_set - actual_source_set)}, "
            f"extra={sorted(actual_source_set - expected_source_set)}"
        )
    if tuple(sources) != source_ids:
        raise Phase5BuildError(
            f"{target_stage} source-index order mismatch: "
            f"expected={list(source_ids)}, actual={list(sources)}"
        )
    for sheet_id in source_ids:
        sheet_type = catalog_by_id[sheet_id].get("sheet_type")
        required_kind = (
            CANONICAL_RENDER_SOURCE_KIND
            if sheet_type in GENERATION_TYPES
            else "composite_master"
        )
        actual_kind = sources[sheet_id].get("kind", "master")
        if actual_kind != required_kind:
            raise Phase5BuildError(
                f"{target_stage} source {sheet_id} requires kind "
                f"{required_kind!r}, found {actual_kind!r}"
            )

    output_set = set(output_ids)
    deferred_ids = tuple(
        sheet_id for sheet_id in ordered_ids if sheet_id not in output_set
    )
    return TargetStageContract(
        target_stage=target_stage,
        source_sheet_ids=source_ids,
        output_sheet_ids=output_ids,
        generated_composite_sheet_ids=generated_ids,
        deferred_sheet_ids=deferred_ids,
    )


@dataclass(frozen=True)
class QAEvidence:
    provenance_path: str
    automated_path: str
    vision_paths: tuple[str, ...]
    primary_score: int
    primary_reviewer: str


@dataclass
class BuiltAsset:
    sheet: dict[str, Any]
    contract: dict[str, Any]
    job_id: str
    method: str
    stage_path: Path | None
    final_manifest_path: str | None
    sha256: str | None
    accepted_evidence: QAEvidence | None = None
    source_entry: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    provisional: bool = False
    tiled_output: dict[str, Any] | None = None

    @property
    def materialized(self) -> bool:
        return self.stage_path is not None and self.sha256 is not None

    @property
    def accepted(self) -> bool:
        return self.accepted_evidence is not None


_BOUND_ARTIFACT_CONTEXT: ContextVar[dict[str, BoundArtifact] | None] = ContextVar(
    "phase5_bound_artifacts", default=None
)


def _bound_artifact_for_path(path: Path) -> BoundArtifact | None:
    registry = _BOUND_ARTIFACT_CONTEXT.get()
    if registry is None:
        return None
    return registry.get(path_identity(path))


@contextmanager
def bound_artifact_context(
    bindings: dict[str, BoundArtifact] | Iterable[BoundArtifact] | None,
) -> Iterator[None]:
    if bindings is None:
        yield
        return
    registry = (
        bindings
        if isinstance(bindings, dict)
        else {bound.identity: bound for bound in bindings}
    )
    token = _BOUND_ARTIFACT_CONTEXT.set(registry)
    try:
        yield
    finally:
        _BOUND_ARTIFACT_CONTEXT.reset(token)


def source_index_bound_artifacts(
    sources: dict[str, dict[str, Any]],
) -> tuple[BoundArtifact, ...]:
    registry: dict[str, BoundArtifact] = {}
    for entry in sources.values():
        values = entry.get(INTERNAL_BOUND_ARTIFACTS_KEY)
        if isinstance(values, dict):
            registry.update(
                {
                    key: value
                    for key, value in values.items()
                    if isinstance(value, BoundArtifact)
                }
            )
    return tuple(registry.values())


def _assert_bound_registry_unchanged(
    registry: dict[str, BoundArtifact] | None,
) -> None:
    if registry is None:
        return
    try:
        assert_bindings_unchanged(registry.values())
    except BoundArtifactError as exc:
        raise Phase5BuildError(str(exc)) from exc


def sha256_file(path: Path) -> str:
    bound = _bound_artifact_for_path(path)
    if bound is not None:
        return bound.sha256
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(path: Path, label: str) -> dict[str, Any]:
    bound = _bound_artifact_for_path(path)
    if bound is not None:
        try:
            return bound.json_object()
        except BoundArtifactError as exc:
            raise Phase5BuildError(str(exc)) from exc
    value = load_json(path)
    if not isinstance(value, dict):
        raise Phase5BuildError(f"{label} must contain a JSON object: {path}")
    return value


def repo_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise Phase5BuildError(
            f"artifact must stay inside the repository: {path}"
        ) from exc


def resolve_repo_artifact(raw_path: Any, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        raise Phase5BuildError(f"{label} must be a repository-relative POSIX path")
    portable = PurePosixPath(raw_path)
    if portable.is_absolute() or any(
        part in {"", ".", ".."} for part in portable.parts
    ):
        raise Phase5BuildError(f"{label} must stay inside the repository: {raw_path!r}")
    if portable.parts and portable.parts[0].endswith(":"):
        raise Phase5BuildError(f"{label} must stay inside the repository: {raw_path!r}")
    lexical = REPO_ROOT.joinpath(*portable.parts)
    bound = _bound_artifact_for_path(lexical)
    if bound is not None:
        return bound.path
    resolved = lexical.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise Phase5BuildError(
            f"{label} must stay inside the repository: {raw_path!r}"
        ) from exc
    if not resolved.is_file():
        raise Phase5BuildError(f"{label} does not exist as a file: {raw_path}")
    return resolved


def verify_hashed_file(spec: Any, label: str) -> tuple[Path, str]:
    if not isinstance(spec, dict):
        raise Phase5BuildError(f"{label} must be an object with path and sha256")
    path = resolve_repo_artifact(spec.get("path"), f"{label}.path")
    expected = spec.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise Phase5BuildError(f"{label}.sha256 must be a 64-character digest")
    actual = sha256_file(path)
    if actual != expected.lower():
        raise Phase5BuildError(
            f"{label}.sha256 mismatch: index={expected.lower()}, actual={actual}"
        )
    return path, actual


def job_id_for_sheet(sheet_id: str) -> str:
    core = sheet_id.removeprefix("sheet_")
    value = f"phase5-{core}-v1"
    if not ID_PATTERN.fullmatch(value):
        raise Phase5BuildError(f"derived job id is invalid: {value!r}")
    return value


def acceptance_threshold(sheet: dict[str, Any]) -> int:
    if (
        sheet.get("id") in FIRST_ECOLOGY_SHEETS
        or sheet.get("priority") == "golden_path"
    ):
        return 94
    return 90


def required_review_count(sheet: dict[str, Any]) -> int:
    return 2 if acceptance_threshold(sheet) >= 94 else 1


def load_contract(
    contract_path: Path, catalog_path: Path
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    result = validate_resolution_contract(
        contract_path, catalog_path, check_catalog=True
    )
    if result["errors"]:
        raise Phase5BuildError(
            "resolution contract is invalid: " + "; ".join(result["errors"])
        )
    catalog = _json_object(catalog_path, "map-sheets catalog")
    catalog_by_id = {
        item["id"]: item
        for item in catalog.get("sheets", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    derived = {
        item["sheet_id"]: item
        for item in result["sheets"]
        if isinstance(item, dict) and isinstance(item.get("sheet_id"), str)
    }
    if len(derived) != 23:
        raise Phase5BuildError(
            f"Phase 5 requires exactly 23 bounded sheets, found {len(derived)}"
        )
    return catalog, catalog_by_id, {"result": result, "sheets": derived}


def _phase5_json_path_references(
    value: Any,
) -> Iterable[tuple[str, str | None, str, bool]]:
    provenance_document = (
        isinstance(value, dict)
        and value.get("schema_version") in {"1.0.0", BUILD_REPORT_SCHEMA_VERSION}
        and value.get("generated_by") == GENERATOR_ID
        and isinstance(value.get("artifacts"), list)
    )
    golden_v3_generation_authority = (
        isinstance(value, dict)
        and value.get("interface")
        in {
            "sstory-k3-golden-v3-four-candidate-derivation-preregistration-v1",
            "sstory-k3-golden-v3-balanced-phase-preregistration-v2",
            "sstory-k3-golden-v3-balanced-open-phase-preregistration-v3",
        }
        and value.get("immutable_plan") is True
    )

    def walk(
        item: Any,
        location: str,
        *,
        provenance_artifact_record: bool = False,
    ) -> Iterable[tuple[str, str | None, str, bool]]:
        if isinstance(item, list):
            for index, child in enumerate(item):
                yield from walk(
                    child,
                    f"{location}[{index}]",
                    provenance_artifact_record=(
                        provenance_document and location == "$.artifacts"
                    ),
                )
            return
        if not isinstance(item, dict):
            return
        for key, raw_path in item.items():
            if not isinstance(raw_path, str):
                continue
            folded = key.casefold()
            if golden_v3_generation_authority and (
                (
                    folded == "output_path"
                    and location.startswith("$.candidates.records[")
                    and location.endswith("]")
                )
                or (folded == "seal_path" and location == "$.cli_contract")
            ):
                # These are preregistered runtime destinations, not source
                # artifacts. Accepted evidence binds candidate payloads
                # through the two embedded cross-profile seals; the seal
                # files themselves are intentionally not persisted.
                continue
            hash_key: str | None = None
            if folded == "path":
                hash_key = next(
                    (
                        candidate
                        for candidate in item
                        if candidate.casefold() == "sha256"
                    ),
                    None,
                )
            elif folded.endswith("_path"):
                wanted = folded[: -len("_path")] + "_sha256"
                hash_key = next(
                    (candidate for candidate in item if candidate.casefold() == wanted),
                    None,
                )
            if folded == "path" or folded.endswith("_path"):
                claimed = item.get(hash_key) if hash_key is not None else None
                if claimed is not None and not isinstance(claimed, str):
                    raise Phase5BuildError(
                        f"{location}.{hash_key} must be a SHA-256 string"
                    )
                yield (
                    raw_path,
                    claimed,
                    f"{location}.{key}",
                    provenance_artifact_record and folded == "path",
                )
        for key, child in item.items():
            yield from walk(child, f"{location}.{key}")

    yield from walk(value, "$")


def _bind_graph_reference(
    raw_path: str,
    *,
    document: BoundArtifact,
    label: str,
    report_relative: bool,
    known: dict[str, BoundArtifact],
) -> BoundArtifact:
    if "://" in raw_path:
        raise Phase5BuildError(f"{label} may not reference a URL")
    if report_relative:
        if not raw_path or "\\" in raw_path:
            raise Phase5BuildError(
                f"{label} must be a provenance-report-relative POSIX path"
            )
        lexical_parts = raw_path.split("/")
        portable = PurePosixPath(raw_path)
        if portable.is_absolute() or any(
            part in {"", ".", ".."} for part in lexical_parts
        ):
            raise Phase5BuildError(
                f"{label} must stay inside the provenance report directory"
            )
        candidate: str | Path = document.path.parent.joinpath(*portable.parts)
    else:
        candidate = raw_path
    try:
        resolved, relative = require_trackable_path(candidate, label=label)
        identity = path_identity(resolved)
        bound = known.get(identity)
        if bound is None:
            bound = bind_file(resolved, label=label, trackable=True)
            known[identity] = bound
    except (BoundArtifactError, ReleasePathError) as exc:
        raise Phase5BuildError(str(exc)) from exc
    if report_relative:
        try:
            bound.path.relative_to(document.path.parent.resolve())
        except ValueError as exc:
            raise Phase5BuildError(
                f"{label} escapes the provenance report directory"
            ) from exc
    return bound


def bind_phase5_artifact_graph(
    roots: Iterable[BoundArtifact],
    *,
    aggregate_boundaries: Iterable[BoundArtifact] = (),
) -> dict[str, BoundArtifact]:
    """Bind every reachable Phase 5 artifact to stable, trackable bytes."""

    registry: dict[str, BoundArtifact] = {}
    pending = list(roots)
    root_ids = {root.identity for root in pending}
    active = _BOUND_ARTIFACT_CONTEXT.get()
    known = dict(active) if active is not None else {}
    known.update({root.identity: root for root in pending})
    aggregate_boundary_ids = {
        path_identity(path)
        for path in (
            DEFAULT_MAP_SHEETS,
            DEFAULT_CONTRACT,
            DEFAULT_CANONICAL_CONTROL_INDEX,
        )
    }
    aggregate_boundary_ids.update(
        boundary.identity for boundary in aggregate_boundaries
    )
    while pending:
        document = pending.pop()
        existing = registry.get(document.identity)
        if existing is not None:
            if existing.sha256 != document.sha256:
                raise Phase5BuildError(
                    f"artifact graph bound conflicting bytes for {document.relative}"
                )
            continue
        registry[document.identity] = document
        if (
            document.identity in aggregate_boundary_ids
            or document.path.suffix.casefold() != ".json"
        ):
            continue
        try:
            value = document.json_value()
        except BoundArtifactError as exc:
            raise Phase5BuildError(str(exc)) from exc
        if (
            document.identity not in root_ids
            and isinstance(value, dict)
            and value.get("interface")
            in {
                "sstory-k3-golden-v3-four-candidate-derivation-preregistration-v1",
                "sstory-k3-golden-v3-balanced-phase-preregistration-v2",
                "sstory-k3-golden-v3-balanced-open-phase-preregistration-v3",
            }
            and value.get("immutable_plan") is True
        ):
            # A nested preregistration is already raw-SHA-bound by its parent.
            # Only a selected manifest authority root expands its own sources;
            # this avoids importing rejected historical runtime destinations.
            continue
        for (
            raw_path,
            claimed,
            location,
            report_relative,
        ) in _phase5_json_path_references(value):
            referenced = _bind_graph_reference(
                raw_path,
                document=document,
                label=f"artifact graph {document.relative} {location}",
                report_relative=report_relative,
                known=known,
            )
            if claimed is not None and claimed.lower() != referenced.sha256:
                raise Phase5BuildError(
                    f"artifact graph {document.relative} {location} hash mismatch: "
                    f"record={claimed.lower()}, actual={referenced.sha256}"
                )
            pending.append(referenced)
    return registry


def _selected_manifest_golden_job(
    manifest: dict[str, Any], golden_style: dict[str, str]
) -> dict[str, Any]:
    """Select exactly one Golden job from an already-bound manifest object."""

    jobs = manifest.get("jobs")
    if not isinstance(jobs, list):
        raise Phase5BuildError("base production manifest jobs must be an array")
    matches = [
        job
        for job in jobs
        if isinstance(job, dict) and _same_artifact(job.get("master"), golden_style)
    ]
    if len(matches) != 1:
        raise Phase5BuildError(
            "source index golden_style must match exactly one manifest job master; "
            f"found {len(matches)}"
        )
    return matches[0]


def bind_manifest_golden_evidence(
    golden_style: dict[str, str], base_manifest: BoundArtifact
) -> dict[str, BoundArtifact]:
    """Bind one selected Golden job without traversing unrelated history.

    The production manifest is an aggregate boundary: its exact bytes remain
    bound and are checked again before commit, but rejected historical jobs do
    not become dependencies of a new Phase 5 release.  Every path reachable
    from the selected Golden job is still recursively bound.  A selected
    report that points back to the manifest must match the bound manifest
    digest, and traversal stops at that aggregate boundary instead of walking
    all jobs and creating a circular dependency.
    """

    try:
        manifest = base_manifest.json_object()
    except BoundArtifactError as exc:
        raise Phase5BuildError(str(exc)) from exc
    job = _selected_manifest_golden_job(manifest, golden_style)
    job_id = job.get("id")
    if not isinstance(job_id, str):
        raise Phase5BuildError("Golden manifest job id must be a string")
    active = _BOUND_ARTIFACT_CONTEXT.get()
    known = dict(active) if active is not None else {}
    existing_manifest = known.get(base_manifest.identity)
    if (
        existing_manifest is not None
        and existing_manifest.sha256 != base_manifest.sha256
    ):
        raise Phase5BuildError(
            "Golden evidence conflicts with the bound base production manifest"
        )
    known[base_manifest.identity] = base_manifest
    roots: list[BoundArtifact] = []
    with bound_artifact_context(known):
        for (
            raw_path,
            claimed,
            location,
            report_relative,
        ) in _phase5_json_path_references(job):
            referenced = _bind_graph_reference(
                raw_path,
                document=base_manifest,
                label=f"Golden manifest job {job_id!r} {location}",
                report_relative=report_relative,
                known=known,
            )
            if claimed is not None and claimed.lower() != referenced.sha256:
                raise Phase5BuildError(
                    f"Golden manifest job {job_id!r} {location} hash mismatch: "
                    f"record={claimed.lower()}, actual={referenced.sha256}"
                )
            roots.append(referenced)
        selected = bind_phase5_artifact_graph(
            roots, aggregate_boundaries=(base_manifest,)
        )

    registry = {base_manifest.identity: base_manifest}
    for identity, bound in selected.items():
        existing = registry.get(identity)
        if existing is not None and existing.sha256 != bound.sha256:
            raise Phase5BuildError(
                f"Golden evidence bound conflicting bytes for {bound.relative}"
            )
        registry[identity] = bound
    return registry


def load_source_index(
    path: Path | None, known_sheet_ids: set[str]
) -> tuple[dict[str, dict[str, Any]], str | None, dict[str, str] | None]:
    if path is None:
        return {}, None, None
    try:
        index_binding = bind_file(path, label="Phase 5 source index", trackable=True)
        index = index_binding.json_object()
    except BoundArtifactError as exc:
        raise Phase5BuildError(str(exc)) from exc
    schema = _json_object(DEFAULT_SOURCE_INDEX_SCHEMA, "Phase 5 source index schema")
    try:
        errors = schema_errors(index, schema)
    except ValidationFailure as exc:
        raise Phase5BuildError(str(exc)) from exc
    if errors:
        raise Phase5BuildError("invalid source index: " + "; ".join(errors))
    registry = bind_phase5_artifact_graph((index_binding,))
    golden_style = index.get("golden_style")
    with bound_artifact_context(registry):
        verify_hashed_file(golden_style, "source index golden_style")
    sources = index.get("sources")
    if not isinstance(sources, list):
        raise Phase5BuildError("source index sources must be an array")
    indexed: dict[str, dict[str, Any]] = {}
    for position, entry in enumerate(sources):
        label = f"source index sources[{position}]"
        if not isinstance(entry, dict) or not isinstance(entry.get("sheet_id"), str):
            raise Phase5BuildError(f"{label} must define a string sheet_id")
        sheet_id = entry["sheet_id"]
        if sheet_id not in known_sheet_ids:
            raise Phase5BuildError(
                f"{label} references unknown bounded sheet {sheet_id!r}"
            )
        if sheet_id in indexed:
            raise Phase5BuildError(f"source index duplicates sheet_id {sheet_id!r}")
        kind = entry.get("kind", "master")
        if kind not in {
            "master",
            "metatiles",
            "composite_master",
            CANONICAL_RENDER_SOURCE_KIND,
        }:
            raise Phase5BuildError(
                f"{label}.kind must be 'master', 'metatiles', "
                "'composite_master', or 'canonical_render_master'"
            )
        indexed_entry = dict(entry)
        indexed_entry[INTERNAL_GOLDEN_STYLE_KEY] = dict(golden_style)
        indexed_entry[INTERNAL_BOUND_ARTIFACTS_KEY] = registry
        indexed[sheet_id] = indexed_entry
    return indexed, index_binding.sha256, dict(golden_style)


def _validate_schema_instance(
    value: dict[str, Any], schema_path: Path, label: str
) -> None:
    schema = _json_object(schema_path, f"{label} schema")
    try:
        errors = schema_errors(value, schema)
    except ValidationFailure as exc:
        raise Phase5BuildError(str(exc)) from exc
    if errors:
        raise Phase5BuildError(f"{label} is invalid: " + "; ".join(errors))


def _same_artifact(first: Any, second: Any) -> bool:
    return (
        isinstance(first, dict)
        and isinstance(second, dict)
        and first.get("path") == second.get("path")
        and first.get("sha256") == second.get("sha256")
    )


def verify_generation_receipts(
    entry: dict[str, Any],
    *,
    sheet_id: str,
    plan: dict[str, Any],
    golden_style: dict[str, str] | None = None,
) -> dict[tuple[int, int], str]:
    """Validate every metatile receipt and its locked generation context.

    JSON Schema closes the shape; this routine closes the relationships that a
    schema cannot express: output-to-tile identity, neighbor identity and the
    role-to-top-level artifact bindings.
    """

    tile_specs = entry.get("tiles")
    if not isinstance(tile_specs, list):
        raise Phase5BuildError(f"{sheet_id} metatiles source requires a tiles array")
    specs = {
        (spec.get("column"), spec.get("row")): spec
        for spec in tile_specs
        if isinstance(spec, dict)
    }
    receipt_paths: dict[tuple[int, int], str] = {}
    directions = {
        "north": (0, -1),
        "east": (1, 0),
        "south": (0, 1),
        "west": (-1, 0),
    }
    role_for_direction = {
        direction: f"neighbor-{direction}" for direction in directions
    }

    receipts: dict[tuple[int, int], dict[str, Any]] = {}
    resolved_receipt_paths: dict[tuple[int, int], Path] = {}
    for position in sorted(specs):
        spec = specs[position]
        label = f"{sheet_id} metatile {position} receipt"
        receipt_path, _ = verify_hashed_file(spec.get("receipt"), label)
        receipt = _json_object(receipt_path, label)
        _validate_schema_instance(receipt, DEFAULT_GENERATION_RECEIPT_SCHEMA, label)
        if receipt.get("sheet_id") != sheet_id:
            raise Phase5BuildError(f"{label}.sheet_id does not match its source sheet")
        if (receipt.get("column"), receipt.get("row")) != position:
            raise Phase5BuildError(f"{label} coordinates do not match its source tile")
        receipts[position] = receipt
        resolved_receipt_paths[position] = receipt_path

    for position in sorted(specs):
        spec = specs[position]
        label = f"{sheet_id} metatile {position} receipt"
        receipt_path = resolved_receipt_paths[position]
        receipt = receipts[position]
        if not _same_artifact(receipt.get("output"), spec):
            raise Phase5BuildError(
                f"{label}.output does not match the indexed metatile"
            )

        output_path, _ = verify_hashed_file(receipt["output"], f"{label}.output")
        raw_path, _ = verify_hashed_file(receipt["raw_output"], f"{label}.raw_output")
        if receipt["raw_output"]["path"] == receipt["output"]["path"]:
            raise Phase5BuildError(
                f"{label} raw_output and protected output must be distinct artifacts"
            )
        size, image_format, color_mode = image_properties(
            output_path, f"{label}.output"
        )
        raw_size, raw_format, raw_color_mode = image_properties(
            raw_path, f"{label}.raw_output"
        )
        expected_size = plan["metatile_size_px"]
        expected_output = {
            "width": expected_size,
            "height": expected_size,
            "format": "PNG",
            "color_mode": "RGB",
        }
        if receipt.get("requested_output") != expected_output:
            raise Phase5BuildError(
                f"{label}.requested_output must lock the exact metatile contract"
            )
        if receipt.get("actual_output") != expected_output:
            raise Phase5BuildError(
                f"{label}.actual_output must lock the exact verified output"
            )
        if size != (expected_size, expected_size):
            raise Phase5BuildError(
                f"{label}.output dimensions do not match the contract"
            )
        if image_format != "PNG" or color_mode != "RGB":
            raise Phase5BuildError(
                f"{label}.output must be a native RGB PNG protected composite"
            )
        if raw_size != (expected_size, expected_size):
            raise Phase5BuildError(
                f"{label}.raw_output dimensions do not match the contract"
            )
        if raw_format != "PNG" or raw_color_mode != "RGB":
            raise Phase5BuildError(
                f"{label}.raw_output must be the native RGB PNG ImageGen result"
            )

        for name in ("prompt", "control", "parent"):
            verify_hashed_file(receipt[name], f"{label}.{name}")
        postprocess = receipt["postprocess"]
        verify_hashed_file(postprocess["control"], f"{label}.postprocess.control")
        postprocess_report_path, _ = verify_hashed_file(
            postprocess["report"], f"{label}.postprocess.report"
        )
        postprocess_report = _json_object(
            postprocess_report_path, f"{label} postprocess report"
        )
        _validate_schema_instance(
            postprocess_report,
            DEFAULT_POSTPROCESS_REPORT_SCHEMA,
            f"{label} postprocess report",
        )
        if (
            postprocess_report.get("sheet_id") != sheet_id
            or (
                postprocess_report.get("column"),
                postprocess_report.get("row"),
            )
            != position
        ):
            raise Phase5BuildError(
                f"{label} postprocess report sheet or coordinates mismatch"
            )
        for report_field, receipt_spec in (
            ("raw_output", receipt["raw_output"]),
            ("control", postprocess["control"]),
            ("output", receipt["output"]),
        ):
            if not _same_artifact(postprocess_report.get(report_field), receipt_spec):
                raise Phase5BuildError(
                    f"{label} postprocess report {report_field} is stale or mismatched"
                )
        inputs = receipt.get("inputs")
        assert isinstance(inputs, list)  # guaranteed by the strict schema
        by_role: dict[str, dict[str, Any]] = {}
        for index, input_spec in enumerate(inputs):
            role = input_spec["role"]
            if role in by_role:
                raise Phase5BuildError(f"{label}.inputs duplicates role {role!r}")
            verify_hashed_file(input_spec, f"{label}.inputs[{index}]")
            by_role[role] = input_spec
        for role, top_level in (
            ("geometry-control", "control"),
            ("parent-context", "parent"),
        ):
            if role not in by_role or not _same_artifact(
                by_role[role], receipt[top_level]
            ):
                raise Phase5BuildError(
                    f"{label}.inputs role {role!r} must match {top_level}"
                )
        if "golden-style" not in by_role:
            raise Phase5BuildError(f"{label}.inputs must lock a golden-style artifact")
        if golden_style is not None and not _same_artifact(
            by_role["golden-style"], golden_style
        ):
            raise Phase5BuildError(
                f"{label}.inputs golden-style does not match source index golden_style"
            )

        neighbors = receipt.get("neighbors")
        assert isinstance(neighbors, dict)  # guaranteed by the strict schema
        for direction, (delta_column, delta_row) in directions.items():
            neighbor_position = (
                position[0] + delta_column,
                position[1] + delta_row,
            )
            expected_neighbor = specs.get(neighbor_position)
            claimed_neighbor = neighbors[direction]
            role = role_for_direction[direction]
            if direction in {"east", "south"}:
                future_receipt = receipts.get(neighbor_position)
                future_artifacts = [expected_neighbor]
                if future_receipt is not None:
                    future_artifacts.append(future_receipt["raw_output"])
                future_tile_used = any(
                    artifact_spec is not None
                    and _same_artifact(input_spec, artifact_spec)
                    for artifact_spec in future_artifacts
                    for input_spec in by_role.values()
                )
                if claimed_neighbor is not None or role in by_role or future_tile_used:
                    raise Phase5BuildError(
                        f"{label}.{direction} is a future row-major tile and must not "
                        "be claimed as a generation input"
                    )
                continue
            if expected_neighbor is None:
                if claimed_neighbor is not None or role in by_role:
                    raise Phase5BuildError(
                        f"{label}.{direction} must lock absence at the sheet boundary"
                    )
                continue
            if not _same_artifact(claimed_neighbor, expected_neighbor):
                raise Phase5BuildError(
                    f"{label}.{direction} does not match metatile {neighbor_position}"
                )
            if role not in by_role or not _same_artifact(
                by_role[role], claimed_neighbor
            ):
                raise Phase5BuildError(
                    f"{label}.inputs role {role!r} must match neighbors.{direction}"
                )
            verify_hashed_file(claimed_neighbor, f"{label}.neighbors.{direction}")
        receipt_paths[position] = repo_path(receipt_path)
    return receipt_paths


def _accepted_report(
    report: dict[str, Any],
    *,
    job_id: str,
    image_path: str,
    image_sha256: str,
    golden_reference: bool,
    threshold: int,
    label: str,
) -> tuple[int, str]:
    schema = _json_object(DEFAULT_QA_REPORT_SCHEMA, "Vision QA report schema")
    try:
        errors = schema_errors(report, schema)
    except ValidationFailure as exc:
        raise Phase5BuildError(str(exc)) from exc
    if errors:
        raise Phase5BuildError(f"{label} is invalid: " + "; ".join(errors))
    if report.get("job_id") != job_id:
        raise Phase5BuildError(
            f"{label}.job_id mismatch: expected={job_id!r}, actual={report.get('job_id')!r}"
        )
    if report.get("image_path") != image_path:
        raise Phase5BuildError(
            f"{label}.image_path mismatch: expected={image_path!r}, "
            f"actual={report.get('image_path')!r}"
        )
    if report.get("image_sha256") != image_sha256:
        raise Phase5BuildError(
            f"{label}.image_sha256 mismatch: expected={image_sha256!r}, "
            f"actual={report.get('image_sha256')!r}"
        )
    if report.get("review_mode") != "blind-independent":
        raise Phase5BuildError(f"{label}.review_mode must be blind-independent")
    if report.get("golden_reference") is not golden_reference:
        raise Phase5BuildError(
            f"{label}.golden_reference must be {str(golden_reference).lower()}"
        )
    if report.get("status") != "complete" or report.get("decision") != "accepted":
        raise Phase5BuildError(f"{label} must be complete and accepted")
    score = report.get("total_score")
    if not isinstance(score, int) or isinstance(score, bool) or score < threshold:
        raise Phase5BuildError(
            f"{label} score must be at least {threshold}, found {score!r}"
        )
    if report.get("acceptance_threshold") != threshold:
        raise Phase5BuildError(f"{label}.acceptance_threshold must equal {threshold}")
    scores = report.get("scores")
    if not isinstance(scores, list) or not all(
        isinstance(item, dict) for item in scores
    ):
        raise Phase5BuildError(f"{label}.scores must be a complete score array")
    maxima = [item.get("maximum") for item in scores]
    values = [item.get("score") for item in scores]
    if sum(maxima) != 100:
        raise Phase5BuildError(f"{label} score maxima must sum to 100")
    if any(value > maximum for value, maximum in zip(values, maxima)):
        raise Phase5BuildError(f"{label} contains a score above its category maximum")
    if score != sum(values):
        raise Phase5BuildError(
            f"{label} total_score {score} does not equal the score sum {sum(values)}"
        )
    failures = report.get("immediate_failures")
    if not isinstance(failures, list) or not failures:
        raise Phase5BuildError(f"{label}.immediate_failures must be a non-empty array")
    detected: list[Any] = []
    for item in failures:
        if not isinstance(item, dict):
            detected.append("invalid-entry")
        elif item.get("detected") is not False:
            detected.append(item.get("id"))
    if detected:
        raise Phase5BuildError(f"{label} has unresolved immediate failures: {detected}")
    reviewer = report.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise Phase5BuildError(f"{label}.reviewer must be non-empty")
    return score, reviewer.strip()


def _verify_manifest_golden_style_v1(
    golden_style: dict[str, str], base_manifest_path: Path
) -> dict[str, Any]:
    """Validate the frozen pre-v2 Golden evidence contract.

    This compatibility path is intentionally isolated from the anonymous v2
    packet contract below.  A job that advertises any v2 handoff artifact may
    never fall back to this older direct-master-review mechanism.
    """

    golden_path, golden_sha = verify_hashed_file(
        golden_style, "source index golden_style"
    )
    manifest = _json_object(base_manifest_path, "base production manifest")
    job = _selected_manifest_golden_job(manifest, golden_style)
    job_id = job.get("id")
    if not isinstance(job_id, str):
        raise Phase5BuildError("Golden manifest job id must be a string")
    if job.get("status") != "accepted":
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} must have status accepted"
        )
    threshold = job.get("acceptance_threshold")
    if (
        not isinstance(threshold, int)
        or isinstance(threshold, bool)
        or threshold < 94
        or threshold > 100
    ):
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} acceptance_threshold must be at least 94"
        )
    job_master_path, job_master_sha = verify_hashed_file(
        job["master"], f"Golden manifest job {job_id!r} master"
    )
    if job_master_path != golden_path or job_master_sha != golden_sha:
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} master does not match golden_style"
        )
    master_size = image_dimensions(golden_path, "Golden style master")
    if (job["master"].get("width"), job["master"].get("height")) != master_size:
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} master dimensions are stale"
        )

    qa = job.get("qa")
    vision = qa.get("vision") if isinstance(qa, dict) else None
    if not isinstance(vision, dict):
        raise Phase5BuildError(f"Golden manifest job {job_id!r} lacks Vision QA")
    if vision.get("decision") != "accepted":
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} Vision decision must be accepted"
        )
    manifest_score = vision.get("score")
    if (
        not isinstance(manifest_score, int)
        or isinstance(manifest_score, bool)
        or manifest_score < 94
    ):
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} Vision score must be at least 94"
        )
    report_path = resolve_repo_artifact(
        vision.get("report_path"), f"Golden manifest job {job_id!r} Vision report"
    )
    primary_report_artifact = {
        "path": repo_path(report_path),
        "sha256": sha256_file(report_path),
    }
    report = _json_object(report_path, f"Golden manifest job {job_id!r} Vision report")
    report_score, report_reviewer = _accepted_report(
        report,
        job_id=job_id,
        image_path=repo_path(golden_path),
        image_sha256=golden_sha,
        golden_reference=True,
        threshold=threshold,
        label=f"Golden manifest job {job_id!r} Vision report",
    )
    if manifest_score != report_score:
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} Vision score is inconsistent with its report"
        )
    manifest_reviewer = vision.get("reviewer")
    if not isinstance(manifest_reviewer, str) or (
        canonical_reviewer_identity(manifest_reviewer)
        != canonical_reviewer_identity(report_reviewer)
    ):
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} Vision reviewer is inconsistent with its report"
        )
    review_inputs: dict[str, dict[str, Any]] = {}
    raw_artifacts: list[dict[str, Any]] = []
    inputs = job.get("inputs")
    if isinstance(inputs, list):
        for input_spec in inputs:
            if not isinstance(input_spec, dict):
                continue
            role = input_spec.get("role")
            if role == "golden-raw-output":
                raw_artifacts.append(input_spec)
                continue
            if not isinstance(role, str) or not role.startswith(
                "independent-vision-review-"
            ):
                continue
            if role not in INDEPENDENT_VISION_REVIEW_ROLES:
                raise Phase5BuildError(
                    f"Golden manifest job {job_id!r} has unexpected Vision review role {role!r}"
                )
            if role in review_inputs:
                raise Phase5BuildError(
                    f"Golden manifest job {job_id!r} duplicates Vision review role {role!r}"
                )
            review_inputs[role] = input_spec
    if set(review_inputs) != set(INDEPENDENT_VISION_REVIEW_ROLES):
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} must hash exactly independent-vision-review-a and independent-vision-review-b"
        )
    manifest_review_artifacts: list[dict[str, str]] = []
    for role in INDEPENDENT_VISION_REVIEW_ROLES:
        spec = review_inputs[role]
        candidate = {"path": spec.get("path"), "sha256": spec.get("sha256")}
        verify_hashed_file(
            candidate,
            f"Golden manifest job {job_id!r} {role}",
        )
        manifest_review_artifacts.append(candidate)
    if not any(
        _same_artifact(primary_report_artifact, item)
        for item in manifest_review_artifacts
    ):
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} primary Vision report must be one of its two manifest-hashed reviews"
        )
    if len(raw_artifacts) != 1:
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} must contain exactly one golden-raw-output input"
        )
    raw_path, raw_sha = verify_hashed_file(
        raw_artifacts[0], f"Golden manifest job {job_id!r} raw output"
    )
    if raw_path == golden_path:
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} raw and final paths must be distinct"
        )
    if raw_sha != golden_sha or raw_path.read_bytes() != golden_path.read_bytes():
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} raw and final bytes must be identical"
        )

    accepted_reviewers: set[str] = set()
    for index, review_artifact in enumerate(manifest_review_artifacts):
        review_path, _ = verify_hashed_file(
            review_artifact,
            f"Golden manifest job {job_id!r} independent Vision review {index + 1}",
        )
        review = _json_object(
            review_path,
            f"Golden manifest job {job_id!r} independent Vision review {index + 1}",
        )
        _, reviewer = _accepted_report(
            review,
            job_id=job_id,
            image_path=repo_path(golden_path),
            image_sha256=golden_sha,
            golden_reference=True,
            threshold=threshold,
            label=f"Golden manifest job {job_id!r} independent Vision review {index + 1}",
        )
        accepted_reviewers.add(canonical_reviewer_identity(reviewer))
    if len(accepted_reviewers) != 2:
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} requires two distinct blind-independent reviewers"
        )
    return {
        "job_id": job_id,
        "master": {"path": repo_path(golden_path), "sha256": golden_sha},
        "vision_report": repo_path(report_path),
        "vision_report_artifact": primary_report_artifact,
        "manifest_vision_reports": manifest_review_artifacts,
        "score": report_score,
        "reviewer": report_reviewer,
        "threshold": threshold,
    }


def _exact_artifact_record(value: Any, *, label: str) -> dict[str, str]:
    """Bind one v2 receipt artifact with no unreviewed metadata."""

    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise Phase5BuildError(f"{label} must be exactly a path/SHA-256 artifact")
    path, digest = verify_hashed_file(value, label)
    if value["sha256"] != digest:
        raise Phase5BuildError(f"{label}.sha256 must be the canonical lowercase digest")
    return {"path": repo_path(path), "sha256": digest}


def _require_v2_timestamp(value: Any, *, label: str):
    if not isinstance(value, str):
        raise Phase5BuildError(f"{label} must be an RFC 3339 timestamp")
    try:
        return parse_rfc3339(value)
    except ValueError as exc:
        raise Phase5BuildError(f"{label} is invalid: {exc}") from exc


def _v2_input_roles(job: dict[str, Any], *, job_id: str) -> dict[str, dict[str, Any]]:
    inputs = job.get("inputs")
    if not isinstance(inputs, list):
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} inputs must be an array"
        )
    selected = {
        GOLDEN_ACCEPTANCE_RECEIPT_ROLE,
        GOLDEN_BLIND_PACKET_ROLE,
        *INDEPENDENT_VISION_REVIEW_ROLES,
    }
    result: dict[str, dict[str, Any]] = {}
    for item in inputs:
        if not isinstance(item, dict):
            raise Phase5BuildError(
                f"Golden manifest job {job_id!r} has an invalid input"
            )
        role = item.get("role")
        if role not in selected:
            continue
        if role in result:
            raise Phase5BuildError(
                f"Golden manifest job {job_id!r} duplicates v2 input role {role!r}"
            )
        if set(item) != {"path", "sha256", "role"}:
            raise Phase5BuildError(
                f"Golden manifest job {job_id!r} {role!r} must be exactly a role/path/SHA-256 artifact"
            )
        result[role] = item
    if set(result) != selected:
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} v2 evidence roles are incomplete"
        )
    return result


def _verify_v2_blind_packet(
    packet_spec: dict[str, Any],
    *,
    candidate: dict[str, str],
    job_id: str,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Validate the deliberately anonymous handoff packet and all five views."""

    packet = _exact_artifact_record(
        packet_spec, label=f"Golden manifest job {job_id!r} blind packet"
    )
    packet_path = resolve_repo_artifact(packet["path"], "Golden blind packet.path")
    packet_text = packet_path.read_text(encoding="utf-8")
    try:
        document = json.loads(packet_text)
    except json.JSONDecodeError as exc:
        raise Phase5BuildError(f"Golden blind packet is invalid JSON: {exc}") from exc
    if not isinstance(document, dict) or set(document) != {"schema_version", "views"}:
        raise Phase5BuildError(
            "Golden blind packet must contain only schema_version and views"
        )
    if document["schema_version"] != "1.0.0":
        raise Phase5BuildError("Golden blind packet schema_version must be 1.0.0")
    # The packet is the only artifact disclosed to blind reviewers.  Do not
    # merely trust its shape: reject a master path/digest or any lineage label
    # even if it was hidden in an otherwise harmless string.
    folded = packet_text.casefold()
    if candidate["path"].casefold() in folded or candidate["sha256"] in folded:
        raise Phase5BuildError(
            "Golden blind packet must not disclose the candidate path or SHA-256"
        )
    if any(
        token in folded
        for token in ("candidate", "lineage", "donor", "control", "generation")
    ):
        raise Phase5BuildError(
            "Golden blind packet must not disclose candidate lineage"
        )
    views = document["views"]
    if not isinstance(views, list) or len(views) != len(GOLDEN_BLIND_PACKET_VIEW_IDS):
        raise Phase5BuildError(
            "Golden blind packet must contain exactly five anonymous views"
        )
    artifacts: list[dict[str, str]] = []
    for expected_id, item in zip(GOLDEN_BLIND_PACKET_VIEW_IDS, views):
        if not isinstance(item, dict) or set(item) != {"id", "path", "sha256"}:
            raise Phase5BuildError(
                "Golden blind packet views must be exact id/path/SHA-256 records"
            )
        if item["id"] != expected_id:
            raise Phase5BuildError("Golden blind packet view order must be fixed")
        artifacts.append(
            _exact_artifact_record(
                {"path": item["path"], "sha256": item["sha256"]},
                label=f"Golden blind packet view {expected_id}",
            )
        )
    if len({item["path"] for item in artifacts}) != len(artifacts) or len(
        {item["sha256"] for item in artifacts}
    ) != len(artifacts):
        raise Phase5BuildError(
            "Golden blind packet views must be five distinct artifacts"
        )
    return packet, artifacts


def _validate_v2_prepared_authority(
    job: dict[str, Any], *, master_path: Path, job_id: str
) -> tuple[
    dict[str, BoundArtifact],
    tuple[BoundArtifact, BoundArtifact, BoundArtifact, BoundArtifact],
]:
    """Re-run the promoter's complete persistent-evidence verifier.

    Accepted jobs contain the two blind reviews and final acceptance receipt in
    addition to the prepared evidence.  Feed the exact prepared-role subset
    back through the authoritative v2 validator so Phase 5 cannot trust a
    hand-written provenance/audit shell that merely has fresh hashes.
    """

    golden_v2_promotion = _load_golden_v2_promotion()

    inputs = job.get("inputs")
    if not isinstance(inputs, list):
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} inputs must be an array"
        )
    prepared_inputs = [
        item
        for item in inputs
        if isinstance(item, dict)
        and item.get("role") in golden_v2_promotion.PREPARED_INPUT_ROLES
    ]
    qa = job.get("qa")
    automated = qa.get("automated") if isinstance(qa, dict) else None
    prepared_job = {
        "inputs": prepared_inputs,
        "qa": {"automated": automated},
        "history": job.get("history", [])[:4]
        if isinstance(job.get("history"), list)
        else job.get("history"),
    }
    try:
        roles = golden_v2_promotion._prepared_role_bindings(prepared_job)
        master = bind_file(
            master_path,
            label=f"Golden manifest job {job_id!r} v2 master",
            trackable=True,
        )
        evidence = golden_v2_promotion._validate_prepared_evidence(
            prepared_job, roles, master
        )
    except (
        golden_v2_promotion.K3GoldenPromotionV2Error,
        BoundArtifactError,
        ReleasePathError,
    ) as exc:
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} v2 prepared evidence is invalid: {exc}"
        ) from exc
    return roles, evidence


def _assert_v2_packet_pixels_match_root_views(
    packet_views: list[dict[str, str]],
    prepared_roles: dict[str, BoundArtifact],
) -> None:
    """Prove each anonymous PNG is only a re-encoding of its Root view."""

    golden_v2_promotion = _load_golden_v2_promotion()

    for name, packet_record in zip(GOLDEN_BLIND_PACKET_VIEW_IDS, packet_views):
        packet_image: Image.Image | None = None
        root_image: Image.Image | None = None
        try:
            packet_binding = golden_v2_promotion._bind_trackable_record(
                packet_record, label=f"Phase 5 blind packet view {name}"
            )
            packet_image = golden_v2_promotion._image_from_binding(
                packet_binding,
                label=f"Phase 5 blind packet view {name}",
                expected_size=golden_v2_promotion.VIEW_DEFINITIONS[name][1],
            )
            root_image = golden_v2_promotion._image_from_binding(
                prepared_roles[f"root-review-view-{name}"],
                label=f"Phase 5 Root review view {name}",
                expected_size=golden_v2_promotion.VIEW_DEFINITIONS[name][1],
            )
            if packet_image.tobytes() != root_image.tobytes():
                raise Phase5BuildError(
                    f"Golden blind packet view {name} is not pixel-identical to its Root review view"
                )
        except golden_v2_promotion.K3GoldenPromotionV2Error as exc:
            raise Phase5BuildError(str(exc)) from exc
        finally:
            if packet_image is not None:
                packet_image.close()
            if root_image is not None:
                root_image.close()


def _verify_manifest_golden_style_v2(
    golden_style: dict[str, str], base_manifest_path: Path
) -> dict[str, Any]:
    """Revalidate the Golden v2 acceptance graph from manifest to blind QA.

    The old Golden mechanism pointed independent reviews straight at the
    master.  v2 deliberately does not: both reviews must bind the immutable
    anonymous packet, whose five fixed views are each SHA-bound here again.
    """

    golden_v2_promotion = _load_golden_v2_promotion()

    golden_path, golden_sha = verify_hashed_file(
        golden_style, "source index golden_style"
    )
    manifest = _json_object(base_manifest_path, "base production manifest")
    job = _selected_manifest_golden_job(manifest, golden_style)
    job_id = job.get("id")
    if not isinstance(job_id, str):
        raise Phase5BuildError("Golden manifest job id must be a string")
    if job_id != golden_v2_promotion.JOB_ID:
        raise Phase5BuildError(
            f"Golden v2 manifest job id must be {golden_v2_promotion.JOB_ID!r}"
        )
    if job.get("status") != "accepted" or job.get("acceptance_threshold") != 94:
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} must be accepted at threshold 94"
        )
    master = job.get("master")
    if not isinstance(master, dict):
        raise Phase5BuildError(f"Golden manifest job {job_id!r} master is missing")
    master_path, master_sha = verify_hashed_file(
        master, f"Golden manifest job {job_id!r} master"
    )
    candidate = {"path": repo_path(master_path), "sha256": master_sha}
    if candidate != {"path": repo_path(golden_path), "sha256": golden_sha}:
        raise Phase5BuildError(
            f"Golden manifest job {job_id!r} master does not match golden_style"
        )
    known_source = golden_v2_promotion.KNOWN_NON_GOLDEN_SOURCE_SHA256.get(master_sha)
    if known_source is not None:
        raise Phase5BuildError(
            f"Golden manifest master is a known non-Golden source: {known_source}"
        )

    prepared_roles, prepared_evidence = _validate_v2_prepared_authority(
        job, master_path=master_path, job_id=job_id
    )
    prepared_raw, prepared_receipt, prepared_audit, prepared_packet = prepared_evidence
    prepared_document = _json_object(
        prepared_receipt.path, "Golden prepared promotion receipt"
    )
    prepared_at = _require_v2_timestamp(
        prepared_document.get("created_at"),
        label="Golden prepared promotion receipt.created_at",
    )
    roles = _v2_input_roles(job, job_id=job_id)
    acceptance_spec = _exact_artifact_record(
        {
            "path": roles[GOLDEN_ACCEPTANCE_RECEIPT_ROLE]["path"],
            "sha256": roles[GOLDEN_ACCEPTANCE_RECEIPT_ROLE]["sha256"],
        },
        label=f"Golden manifest job {job_id!r} acceptance receipt",
    )
    acceptance_path = resolve_repo_artifact(
        acceptance_spec["path"], "Golden acceptance receipt.path"
    )
    acceptance = _json_object(acceptance_path, "Golden acceptance receipt")
    receipt_keys = {
        "schema_version",
        "id",
        "job_id",
        "status",
        "golden_reference",
        "acceptance_threshold",
        "candidate",
        "raw",
        "promotion_provenance",
        "automated_audit",
        "root_review",
        "blind_packet",
        "reviews",
        "authorized_by",
        "accepted_at",
    }
    if set(acceptance) != receipt_keys:
        raise Phase5BuildError(
            "Golden acceptance receipt keys must exactly match the v2 contract"
        )
    if (
        acceptance.get("schema_version") != "1.0.0"
        or acceptance.get("id") != f"{job_id}-golden-acceptance-v2"
        or acceptance.get("job_id") != job_id
        or acceptance.get("status") != "accepted"
        or acceptance.get("golden_reference") is not True
        or acceptance.get("acceptance_threshold") != 94
        or not isinstance(acceptance.get("authorized_by"), str)
        or not acceptance["authorized_by"].strip()
    ):
        raise Phase5BuildError(
            "Golden acceptance receipt has an invalid v2 identity or decision"
        )
    accepted_at = _require_v2_timestamp(
        acceptance.get("accepted_at"), label="Golden acceptance receipt.accepted_at"
    )
    if (
        _exact_artifact_record(
            acceptance["candidate"], label="Golden acceptance receipt.candidate"
        )
        != candidate
    ):
        raise Phase5BuildError(
            "Golden acceptance receipt candidate does not match the manifest master"
        )
    raw = _exact_artifact_record(
        acceptance["raw"], label="Golden acceptance receipt.raw"
    )
    raw_path = resolve_repo_artifact(raw["path"], "Golden acceptance raw.path")
    if (
        raw != prepared_raw.artifact()
        or raw == candidate
        or raw_path.read_bytes() != master_path.read_bytes()
    ):
        raise Phase5BuildError(
            "Golden acceptance receipt raw/final byte-identity contract failed"
        )
    prepared_acceptance_artifacts = {
        "promotion_provenance": prepared_receipt,
        "automated_audit": prepared_audit,
        "root_review": prepared_roles["root-vision-authorization"],
        "blind_packet": prepared_packet,
    }
    for field, expected in prepared_acceptance_artifacts.items():
        actual = _exact_artifact_record(
            acceptance[field], label=f"Golden acceptance receipt.{field}"
        )
        if actual != expected.artifact():
            raise Phase5BuildError(
                f"Golden acceptance receipt.{field} does not match prepared evidence"
            )
    root = _exact_artifact_record(
        acceptance["root_review"], label="Golden acceptance receipt.root_review"
    )
    root_document = _json_object(
        resolve_repo_artifact(root["path"], "Golden root review.path"),
        "Golden root review",
    )
    root_reviewer = root_document.get("reviewer")
    if not isinstance(root_reviewer, str) or not root_reviewer.strip():
        raise Phase5BuildError("Golden root review reviewer must be non-empty")
    root_at = _require_v2_timestamp(
        root_document.get("created_at"), label="Golden root review.created_at"
    )

    packet, packet_views = _verify_v2_blind_packet(
        acceptance["blind_packet"], candidate=candidate, job_id=job_id
    )
    _assert_v2_packet_pixels_match_root_views(packet_views, prepared_roles)
    if packet != _exact_artifact_record(
        {
            "path": roles[GOLDEN_BLIND_PACKET_ROLE]["path"],
            "sha256": roles[GOLDEN_BLIND_PACKET_ROLE]["sha256"],
        },
        label=f"Golden manifest job {job_id!r} blind packet input",
    ):
        raise Phase5BuildError(
            "Golden manifest blind packet does not match the acceptance receipt"
        )

    reviews = acceptance.get("reviews")
    if not isinstance(reviews, list) or len(reviews) != 2:
        raise Phase5BuildError(
            "Golden acceptance receipt must contain exactly two blind reviews"
        )
    if [
        item.get("role") if isinstance(item, dict) else None for item in reviews
    ] != list(INDEPENDENT_VISION_REVIEW_ROLES):
        raise Phase5BuildError(
            "Golden acceptance reviews must be in canonical blind role order"
        )
    review_records: dict[str, tuple[dict[str, str], dict[str, Any], str, Any]] = {}
    for item in reviews:
        required = {"role", "path", "sha256", "reviewer", "score", "created_at"}
        if not isinstance(item, dict) or set(item) != required:
            raise Phase5BuildError(
                "Golden acceptance reviews must exactly match the v2 contract"
            )
        role = item["role"]
        if role not in INDEPENDENT_VISION_REVIEW_ROLES or role in review_records:
            raise Phase5BuildError(
                "Golden acceptance reviews must use the two canonical blind roles"
            )
        artifact = _exact_artifact_record(
            {"path": item["path"], "sha256": item["sha256"]},
            label=f"Golden acceptance review {role}",
        )
        manifest_artifact = _exact_artifact_record(
            {"path": roles[role]["path"], "sha256": roles[role]["sha256"]},
            label=f"Golden manifest job {job_id!r} {role}",
        )
        if artifact != manifest_artifact:
            raise Phase5BuildError(
                "Golden acceptance review does not match its manifest input"
            )
        report = _json_object(
            resolve_repo_artifact(artifact["path"], f"Golden review {role}.path"),
            f"Golden review {role}",
        )
        score, reviewer = _accepted_report(
            report,
            job_id=job_id,
            image_path=packet["path"],
            image_sha256=packet["sha256"],
            golden_reference=True,
            threshold=94,
            label=f"Golden review {role}",
        )
        if item["score"] != score:
            raise Phase5BuildError(
                "Golden acceptance review score is inconsistent with its report"
            )
        reviewed_at = _require_v2_timestamp(
            item["created_at"], label=f"Golden acceptance review {role}.created_at"
        )
        report_at = _require_v2_timestamp(
            report.get("created_at"), label=f"Golden review {role}.created_at"
        )
        if reviewed_at != report_at:
            raise Phase5BuildError(
                "Golden acceptance review timestamp is inconsistent with its report"
            )
        prefix = f"{role}/"
        if not reviewer.startswith(prefix) or not reviewer[len(prefix) :].strip():
            raise Phase5BuildError(
                "Golden reviewer must use its canonical blind role/id form"
            )
        try:
            reviewer_identity = canonical_reviewer_identity(reviewer[len(prefix) :])
            root_identity = canonical_reviewer_identity(root_reviewer)
        except ValueError as exc:
            raise Phase5BuildError(str(exc)) from exc
        if reviewer_identity == root_identity:
            raise Phase5BuildError(
                "Golden blind reviewer must differ from the Root reviewer"
            )
        if item["reviewer"] != f"{role}/{reviewer_identity}":
            raise Phase5BuildError(
                "Golden acceptance reviewer is inconsistent with its report"
            )
        views = report.get("review_views")
        if not isinstance(views, list) or not set(GOLDEN_BLIND_PACKET_VIEW_IDS) <= {
            item.get("id") for item in views if isinstance(item, dict)
        }:
            raise Phase5BuildError(
                "Golden review must complete the five fixed blind packet views"
            )
        failures = report.get("immediate_failures")
        if (
            not isinstance(failures, list)
            or tuple(
                item.get("id") if isinstance(item, dict) else None for item in failures
            )
            != GOLDEN_PHASE4_IMMEDIATE_FAILURE_IDS
        ):
            raise Phase5BuildError(
                "Golden review immediate-failure checklist must exactly match Phase 4"
            )
        if report_at <= root_at or report_at <= prepared_at:
            raise Phase5BuildError(
                "Golden blind review must occur after Root authorization and prepared evidence"
            )
        if report_at > accepted_at:
            raise Phase5BuildError("Golden acceptance receipt predates a blind review")
        review_records[role] = (artifact, report, reviewer_identity, report_at)
    if (
        set(review_records) != set(INDEPENDENT_VISION_REVIEW_ROLES)
        or len({item[2] for item in review_records.values()}) != 2
    ):
        raise Phase5BuildError(
            "Golden acceptance requires two distinct blind-independent reviewers"
        )

    qa = job.get("qa")
    vision = qa.get("vision") if isinstance(qa, dict) else None
    primary = review_records[INDEPENDENT_VISION_REVIEW_ROLES[0]]
    if (
        not isinstance(vision, dict)
        or vision.get("decision") != "accepted"
        or vision.get("score") != primary[1].get("total_score")
        or vision.get("report_path") != primary[0]["path"]
        or vision.get("reviewer")
        != f"{INDEPENDENT_VISION_REVIEW_ROLES[0]}/{primary[2]}"
    ):
        raise Phase5BuildError(
            "Golden manifest Vision QA does not bind the primary blind review"
        )
    reviewed_at = _require_v2_timestamp(
        vision.get("reviewed_at"), label="Golden manifest Vision QA.reviewed_at"
    )
    if reviewed_at != primary[3]:
        raise Phase5BuildError(
            "Golden manifest Vision QA timestamp is inconsistent with the primary review"
        )
    history = job.get("history")
    if not isinstance(history, list) or [
        item.get("state") if isinstance(item, dict) else None for item in history
    ] != [
        "planned",
        "inputs-ready",
        "generated",
        "automated-qa",
        "vision-qa",
        "accepted",
    ]:
        raise Phase5BuildError(
            "Golden manifest history must be the exact six-state v2 sequence"
        )
    history_times = [
        _require_v2_timestamp(item.get("at"), label="Golden manifest history.at")
        for item in history
        if isinstance(item, dict)
    ]
    if len(history_times) != len(history) or any(
        later < earlier for earlier, later in zip(history_times, history_times[1:])
    ):
        raise Phase5BuildError(
            "Golden manifest history timestamps must be complete and chronological"
        )
    if history_times[-1] != accepted_at or history_times[-2] != accepted_at:
        raise Phase5BuildError(
            "Golden manifest final history timestamps must match the acceptance receipt"
        )
    if any(value != prepared_at for value in history_times[:4]):
        raise Phase5BuildError(
            "Golden manifest prepared history timestamps must match the prepared receipt"
        )
    return {
        "job_id": job_id,
        "master": candidate,
        "vision_report": primary[0]["path"],
        "vision_report_artifact": primary[0],
        "manifest_vision_reports": [item[0] for item in review_records.values()],
        "score": primary[1]["total_score"],
        "reviewer": f"{INDEPENDENT_VISION_REVIEW_ROLES[0]}/{primary[2]}",
        "threshold": 94,
        "acceptance_receipt": acceptance_spec,
        "blind_packet": packet,
        "blind_packet_views": packet_views,
    }


def _verify_manifest_golden_style_v3(
    golden_style: dict[str, str], base_manifest_path: Path
) -> dict[str, Any]:
    """Revalidate the full Golden-v3 promotion graph without legacy fallback."""

    try:
        evidence = golden_v3_promotion.verify_accepted_manifest_golden_v3(
            golden_style, base_manifest_path
        )
    except golden_v3_promotion.GoldenV3PromotionError as exc:
        raise Phase5BuildError(str(exc)) from exc
    if evidence.get("generation_contract_id") not in (
        golden_v3_promotion.FOUR_CANDIDATE_V1,
        golden_v3_promotion.BALANCED_PHASE_V2,
        golden_v3_promotion.BALANCED_OPEN_PHASE_V3,
    ):
        raise Phase5BuildError(
            "Golden v3 generation discriminator is missing or invalid"
        )
    return evidence


def verify_manifest_golden_style(
    golden_style: dict[str, str], base_manifest_path: Path
) -> dict[str, Any]:
    """Bind an accepted Golden using its declared, fail-closed evidence version."""

    manifest = _json_object(base_manifest_path, "base production manifest")
    job = _selected_manifest_golden_job(manifest, golden_style)
    inputs = job.get("inputs")
    if not isinstance(inputs, list):
        raise Phase5BuildError("Golden manifest job inputs must be an array")
    roles = [item.get("role") for item in inputs if isinstance(item, dict)]
    v3_receipt_count = roles.count(golden_v3_promotion.V3_ACCEPTANCE_RECEIPT_ROLE)
    v3_markers = set(roles) & set(golden_v3_promotion.V3_ONLY_ROLES)
    v3_declared = job.get("id") == golden_v3_promotion.JOB_ID or bool(v3_markers)
    receipt_count = roles.count(GOLDEN_ACCEPTANCE_RECEIPT_ROLE)
    v2_prepared_markers = set(roles) & set(GOLDEN_V2_PREPARED_ONLY_ROLES)
    if v3_declared:
        # The anonymous packet role is shared by v2 and v3.  Ignore only that
        # shared role while checking whether a declared v3 graph is mixed.
        v2_only_markers = v2_prepared_markers - {GOLDEN_BLIND_PACKET_ROLE}
        if (
            job.get("id") != golden_v3_promotion.JOB_ID
            or v3_receipt_count != 1
            or receipt_count
            or v2_only_markers
        ):
            raise Phase5BuildError(
                "Golden v3 evidence is incomplete or mixed; refusing legacy fallback; "
                f"job_id={job.get('id')!r}, receipt_count={v3_receipt_count}, "
                f"markers={sorted(v3_markers)}, "
                f"v2_markers={sorted(v2_only_markers)}"
            )
        return _verify_manifest_golden_style_v3(golden_style, base_manifest_path)
    if receipt_count == 1:
        return _verify_manifest_golden_style_v2(golden_style, base_manifest_path)
    if receipt_count or v2_prepared_markers:
        raise Phase5BuildError(
            "Golden v2 evidence is incomplete; refusing legacy fallback; "
            f"prepared_markers={sorted(v2_prepared_markers)}"
        )
    return _verify_manifest_golden_style_v1(golden_style, base_manifest_path)


def canonical_render_context(
    *,
    catalog_path: Path,
    contract_path: Path,
    control_index_path: Path,
    golden_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Build the exact execution lock expected by canonical-render provenance."""

    def checked(path: Path, label: str) -> dict[str, str]:
        resolved = path.resolve()
        if not resolved.is_file():
            raise Phase5BuildError(f"{label} does not exist: {resolved}")
        return {"path": repo_path(resolved), "sha256": sha256_file(resolved)}

    return {
        "golden_evidence": golden_evidence,
        "map_catalog": checked(catalog_path, "canonical render map catalog"),
        "resolution_contract": checked(
            contract_path, "canonical render resolution contract"
        ),
        "control_index": checked(
            control_index_path, "canonical render metatile control index"
        ),
        "canon_sources": {
            role: checked(path, f"canonical render {role} source")
            for role, path in CANONICAL_GEOJSON_SOURCES.items()
        },
    }


def _renderer_report_sources(
    report: dict[str, Any], *, label: str
) -> dict[str, dict[str, str]]:
    values = report.get("sources")
    if not isinstance(values, list):
        raise Phase5BuildError(f"{label}.sources must lock all six canonical sources")
    result: dict[str, dict[str, str]] = {}
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise Phase5BuildError(f"{label}.sources[{index}] must be an object")
        report_role = value.get("role")
        canonical_role = RENDERER_SOURCE_ROLE_MAP.get(str(report_role))
        if canonical_role is None or canonical_role in result:
            raise Phase5BuildError(
                f"{label}.sources[{index}] has an unknown or duplicate role"
            )
        spec = {"path": value.get("path"), "sha256": value.get("sha256")}
        verify_hashed_file(spec, f"{label}.sources[{index}]")
        result[canonical_role] = spec
    if set(result) != set(CANONICAL_GEOJSON_SOURCES):
        raise Phase5BuildError(f"{label}.sources must lock all six canonical sources")
    return result


def _verify_renderer_report_binding(
    report_inputs: dict[str, Any],
    artifact_record: dict[str, Any],
    *,
    sheet_id: str,
    label: str,
) -> None:
    report_path, _ = verify_hashed_file(
        report_inputs.get("renderer_report"), f"{label}.inputs.renderer_report"
    )
    renderer_report = _json_object(report_path, f"{label} renderer report")
    if renderer_report.get("status") != "passed":
        raise Phase5BuildError(
            f"{label} renderer report is pending; accepted Golden style is required"
        )
    if renderer_report.get("coordinate_reference_system") != "EA-WORLD-1":
        raise Phase5BuildError(f"{label} renderer report uses the wrong CRS")
    sheet = renderer_report.get("sheet")
    if not isinstance(sheet, dict) or sheet.get("sheet_id") != sheet_id:
        raise Phase5BuildError(f"{label} renderer report sheet_id mismatch")
    generated_by = renderer_report.get("generated_by")
    if (
        not isinstance(generated_by, dict)
        or generated_by.get("id") != CANONICAL_RENDERER_ID
    ):
        raise Phase5BuildError(f"{label} renderer report has the wrong generator id")
    renderer_spec = {
        "path": generated_by.get("path"),
        "sha256": generated_by.get("sha256"),
    }
    if not _same_artifact(renderer_spec, report_inputs.get("renderer")):
        raise Phase5BuildError(
            f"{label}.inputs.renderer does not match the renderer execution report"
        )
    verify_hashed_file(renderer_spec, f"{label} renderer execution artifact")

    renderer_inputs = renderer_report.get("inputs")
    if not isinstance(renderer_inputs, dict):
        raise Phase5BuildError(f"{label} renderer report inputs are missing")
    golden = renderer_inputs.get("golden_style")
    if not isinstance(golden, dict) or golden.get("status") != "locked":
        raise Phase5BuildError(
            f"{label} renderer report Golden style is not hash-locked"
        )
    if not _same_artifact(golden, report_inputs.get("golden_style")):
        raise Phase5BuildError(
            f"{label}.inputs.golden_style does not match the renderer report"
        )
    atlas = renderer_inputs.get("material_atlas")
    if not isinstance(atlas, dict) or atlas.get("status") != "locked":
        raise Phase5BuildError(f"{label} renderer material atlas is not locked")
    if not _same_artifact(atlas, report_inputs.get("material_atlas")):
        raise Phase5BuildError(
            f"{label}.inputs.material_atlas does not match the renderer report"
        )
    verify_hashed_file(
        report_inputs["material_atlas"], f"{label}.inputs.material_atlas"
    )

    for report_key, provenance_key in (
        ("map_sheets", "map_catalog"),
        ("resolution_contract", "resolution_contract"),
    ):
        renderer_spec_value = renderer_report.get(report_key)
        if not _same_artifact(renderer_spec_value, report_inputs.get(provenance_key)):
            raise Phase5BuildError(
                f"{label}.inputs.{provenance_key} does not match the renderer report"
            )
    if not _same_artifact(
        renderer_inputs.get("canonical_control_index"),
        report_inputs.get("control_index"),
    ):
        raise Phase5BuildError(
            f"{label}.inputs.control_index does not match the renderer report"
        )

    renderer_sources = _renderer_report_sources(renderer_report, label=label)
    provenance_sources = {
        value.get("role"): {
            "path": value.get("path"),
            "sha256": value.get("sha256"),
        }
        for value in report_inputs.get("canon_sources", [])
        if isinstance(value, dict)
    }
    if set(provenance_sources) != set(renderer_sources):
        raise Phase5BuildError(f"{label} canonical source role coverage mismatch")
    for role, spec in renderer_sources.items():
        if not _same_artifact(spec, provenance_sources.get(role)):
            raise Phase5BuildError(
                f"{label}.inputs.canon_sources[{role!r}] does not match the renderer report"
            )

    renderer_settings = report_inputs.get("renderer_settings")
    anchoring = renderer_report.get("anchoring")
    if (
        not isinstance(renderer_settings, dict)
        or not isinstance(anchoring, dict)
        or renderer_settings.get("seed") != anchoring.get("seed")
    ):
        raise Phase5BuildError(f"{label} renderer seed lock mismatch")
    transform = renderer_report.get("transform")
    if (
        not isinstance(transform, dict)
        or transform.get("source_coordinates_modified") is not False
        or transform.get("world_crop_or_upscale_used") is not False
    ):
        raise Phase5BuildError(
            f"{label} renderer report does not prove immutable source coordinates"
        )

    outputs = renderer_report.get("outputs")
    master = outputs.get("master") if isinstance(outputs, dict) else None
    if not isinstance(master, dict):
        raise Phase5BuildError(f"{label} renderer report master output is missing")
    if (
        master.get("sha256") != artifact_record.get("sha256")
        or master.get("width") != artifact_record.get("width")
        or master.get("height") != artifact_record.get("height")
        or master.get("format") != "PNG"
        or master.get("mode") != "RGB"
    ):
        raise Phase5BuildError(
            f"{label} renderer report output does not match the provenance artifact"
        )
    for key in ("observed_land_sea_mask", "observed_transport_mask"):
        mask = outputs.get(key)
        mask_path, _ = verify_hashed_file(mask, f"{label} renderer {key}")
        mask_size, mask_format, mask_mode = image_properties(
            mask_path, f"{label} renderer {key}"
        )
        if (
            mask_size != (artifact_record.get("width"), artifact_record.get("height"))
            or mask_format != "PNG"
            or mask_mode not in {"1", "L"}
        ):
            raise Phase5BuildError(
                f"{label} renderer {key} must be a same-size binary PNG mask"
            )


def write_canonical_render_provenance(
    *,
    renderer_report_path: Path,
    output_path: Path,
    base_manifest_path: Path = DEFAULT_BASE_MANIFEST,
    catalog_path: Path = DEFAULT_MAP_SHEETS,
    contract_path: Path = DEFAULT_CONTRACT,
    control_index_path: Path = DEFAULT_CANONICAL_CONTROL_INDEX,
    created_at: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Promote one locked renderer execution report into canonical provenance.

    A pending renderer report is deliberately ineligible.  The function binds
    the accepted Golden and both independent Golden reviews through the base
    manifest, then locks the renderer, run report, seed/config, atlas, controls,
    all six GeoJSON sources, and the exact RGB PNG output.
    """

    renderer_report_path = renderer_report_path.resolve()
    output_path = output_path.resolve()
    repo_path(renderer_report_path)
    repo_path(output_path)
    if output_path.exists() and not force:
        raise Phase5BuildError(f"canonical provenance already exists: {output_path}")
    renderer_report = _json_object(renderer_report_path, "canonical renderer report")
    if renderer_report.get("status") != "passed":
        raise Phase5BuildError(
            "canonical renderer report is pending; accepted Golden style is required"
        )
    sheet = renderer_report.get("sheet")
    if not isinstance(sheet, dict) or not isinstance(sheet.get("sheet_id"), str):
        raise Phase5BuildError("canonical renderer report lacks sheet identity")
    sheet_id = sheet["sheet_id"]
    renderer_inputs = renderer_report.get("inputs")
    generated_by = renderer_report.get("generated_by")
    outputs = renderer_report.get("outputs")
    if not all(
        isinstance(value, dict) for value in (renderer_inputs, generated_by, outputs)
    ):
        raise Phase5BuildError("canonical renderer report lacks execution locks")
    golden = renderer_inputs.get("golden_style")
    if not isinstance(golden, dict) or golden.get("status") != "locked":
        raise Phase5BuildError("canonical renderer report Golden style is pending")
    golden_spec = {"path": golden.get("path"), "sha256": golden.get("sha256")}
    golden_evidence = verify_manifest_golden_style(
        golden_spec, base_manifest_path.resolve()
    )
    if len(golden_evidence.get("manifest_vision_reports", [])) < 2:
        raise Phase5BuildError(
            "canonical renderer provenance requires two Golden Vision reports"
        )

    renderer_spec = {
        "path": generated_by.get("path"),
        "sha256": generated_by.get("sha256"),
    }
    if generated_by.get("id") != CANONICAL_RENDERER_ID:
        raise Phase5BuildError("canonical renderer report has the wrong generator id")
    verify_hashed_file(renderer_spec, "canonical renderer")
    atlas = renderer_inputs.get("material_atlas")
    if not isinstance(atlas, dict) or atlas.get("status") != "locked":
        raise Phase5BuildError("canonical renderer material atlas is not locked")
    atlas_spec = {"path": atlas.get("path"), "sha256": atlas.get("sha256")}
    verify_hashed_file(atlas_spec, "canonical renderer material atlas")

    master = outputs.get("master")
    if not isinstance(master, dict):
        raise Phase5BuildError("canonical renderer report master output is missing")
    master_spec = {"path": master.get("path"), "sha256": master.get("sha256")}
    master_path, _ = verify_hashed_file(master_spec, "canonical renderer master")
    size, image_format, color_mode = image_properties(
        master_path, "canonical renderer master"
    )
    if image_format != "PNG" or color_mode != "RGB":
        raise Phase5BuildError("canonical renderer master must be an RGB PNG")
    if size != (master.get("width"), master.get("height")):
        raise Phase5BuildError("canonical renderer master dimensions are stale")
    for key in ("observed_land_sea_mask", "observed_transport_mask"):
        mask = outputs.get(key)
        mask_path, _ = verify_hashed_file(mask, f"canonical renderer {key}")
        mask_size, mask_format, mask_mode = image_properties(
            mask_path, f"canonical renderer {key}"
        )
        if mask_size != size or mask_format != "PNG" or mask_mode not in {"1", "L"}:
            raise Phase5BuildError(
                f"canonical renderer {key} must be a same-size binary PNG mask"
            )
    try:
        artifact_path = master_path.relative_to(output_path.parent).as_posix()
    except ValueError as exc:
        raise Phase5BuildError(
            "canonical renderer master must be inside the provenance build root"
        ) from exc

    context = canonical_render_context(
        catalog_path=catalog_path.resolve(),
        contract_path=contract_path.resolve(),
        control_index_path=control_index_path.resolve(),
        golden_evidence=golden_evidence,
    )
    for report_key, context_key in (
        ("map_sheets", "map_catalog"),
        ("resolution_contract", "resolution_contract"),
    ):
        if not _same_artifact(renderer_report.get(report_key), context[context_key]):
            raise Phase5BuildError(
                f"canonical renderer report {report_key} does not match the build input"
            )
    if not _same_artifact(
        renderer_inputs.get("canonical_control_index"), context["control_index"]
    ):
        raise Phase5BuildError(
            "canonical renderer report control index does not match the build input"
        )
    renderer_sources = _renderer_report_sources(
        renderer_report, label="canonical renderer report"
    )
    for role, expected in context["canon_sources"].items():
        if not _same_artifact(renderer_sources.get(role), expected):
            raise Phase5BuildError(
                f"canonical renderer report source {role!r} does not match the build input"
            )

    anchoring = renderer_report.get("anchoring")
    transform = renderer_report.get("transform")
    if not isinstance(anchoring, dict) or not isinstance(anchoring.get("seed"), int):
        raise Phase5BuildError("canonical renderer report lacks an integer seed")
    if not isinstance(transform, dict):
        raise Phase5BuildError("canonical renderer report lacks transform evidence")
    document: dict[str, Any] = {
        "$schema": (
            "https://sstory.example/schemas/"
            "phase5-canonical-render-provenance.schema.json"
        ),
        "schema_version": "1.0.0",
        "type": "sstory-phase5-deterministic-canonical-render-provenance",
        "generated_by": GENERATOR_ID,
        "coordinate_reference_system": "EA-WORLD-1",
        "sheet_id": sheet_id,
        "inputs": {
            "golden_style": golden_spec,
            "golden_vision_reports": golden_evidence["manifest_vision_reports"],
            "renderer": renderer_spec,
            "renderer_report": {
                "path": repo_path(renderer_report_path),
                "sha256": sha256_file(renderer_report_path),
            },
            "renderer_settings": {
                "seed": anchoring["seed"],
                "parameters": {
                    "generator_id": generated_by["id"],
                    "png_options": renderer_report.get("determinism", {}).get(
                        "png_options"
                    ),
                    "coordinate_quantization": transform.get("rounding"),
                    "source_coordinates_modified": transform.get(
                        "source_coordinates_modified"
                    ),
                    "world_crop_or_upscale_used": transform.get(
                        "world_crop_or_upscale_used"
                    ),
                },
            },
            "material_atlas": atlas_spec,
            "map_catalog": context["map_catalog"],
            "resolution_contract": context["resolution_contract"],
            "control_index": context["control_index"],
            "canon_sources": [
                {"role": role, **renderer_sources[role]}
                for role in CANONICAL_GEOJSON_SOURCES
            ],
        },
        "artifacts": [
            {
                "sheet_id": sheet_id,
                "path": artifact_path,
                "sha256": master["sha256"],
                "width": size[0],
                "height": size[1],
                "format": "PNG",
                "color_mode": "RGB",
                "method": CANONICAL_RENDER_METHOD,
                "provenance": {
                    "kind": CANONICAL_RENDER_METHOD,
                    "acceptance_inferred": False,
                },
            }
        ],
        "created_at": created_at or utc_now(),
    }
    _validate_schema_instance(
        document,
        DEFAULT_CANONICAL_RENDER_PROVENANCE_SCHEMA,
        "canonical render provenance",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dump_json(output_path, document)
    return document


def _verify_canonical_render_provenance(
    report: dict[str, Any],
    *,
    entry: dict[str, Any],
    sheet: dict[str, Any],
    label: str,
) -> None:
    """Validate every semantic and file lock unique to a canonical render."""

    _validate_schema_instance(
        report,
        DEFAULT_CANONICAL_RENDER_PROVENANCE_SCHEMA,
        label,
    )
    if report.get("sheet_id") != sheet.get("id"):
        raise Phase5BuildError(f"{label}.sheet_id does not match the source sheet")
    context = entry.get(INTERNAL_CANONICAL_CONTEXT_KEY)
    if not isinstance(context, dict):
        raise Phase5BuildError(
            f"{label} lacks the checked canonical-render execution context"
        )
    inputs = report["inputs"]
    golden_style = entry.get(INTERNAL_GOLDEN_STYLE_KEY)
    golden_evidence = context.get("golden_evidence")
    if not isinstance(golden_style, dict) or not isinstance(golden_evidence, dict):
        raise Phase5BuildError(f"{label} lacks checked Golden style evidence")
    if not _same_artifact(inputs["golden_style"], golden_style) or not _same_artifact(
        inputs["golden_style"], golden_evidence.get("master")
    ):
        raise Phase5BuildError(
            f"{label}.inputs.golden_style does not match the manifest Golden artifact"
        )
    verify_hashed_file(inputs["golden_style"], f"{label}.inputs.golden_style")

    for key in ("map_catalog", "resolution_contract", "control_index"):
        expected = context.get(key)
        if not _same_artifact(inputs[key], expected):
            raise Phase5BuildError(
                f"{label}.inputs.{key} does not match the build input"
            )
        verify_hashed_file(inputs[key], f"{label}.inputs.{key}")

    expected_sources = context.get("canon_sources")
    if not isinstance(expected_sources, dict):
        raise Phase5BuildError(f"{label} lacks canonical GeoJSON execution locks")
    reported_sources: dict[str, dict[str, Any]] = {}
    for index, spec in enumerate(inputs["canon_sources"]):
        role = spec.get("role")
        if role in reported_sources:
            raise Phase5BuildError(f"{label}.inputs.canon_sources duplicates {role!r}")
        reported_sources[role] = spec
        verify_hashed_file(spec, f"{label}.inputs.canon_sources[{index}]")
    if set(reported_sources) != set(CANONICAL_GEOJSON_SOURCES):
        raise Phase5BuildError(
            f"{label}.inputs.canon_sources must lock all six canonical GeoJSON roles"
        )
    for role, expected in expected_sources.items():
        if not _same_artifact(reported_sources.get(role), expected):
            raise Phase5BuildError(
                f"{label}.inputs.canon_sources[{role!r}] does not match the canonical source"
            )

    renderer_path, _ = verify_hashed_file(
        inputs["renderer"], f"{label}.inputs.renderer"
    )
    if renderer_path.suffix.casefold() not in {".py", ".js", ".mjs", ".ts"}:
        raise Phase5BuildError(
            f"{label}.inputs.renderer must identify an executable source artifact"
        )

    manifest_reports = golden_evidence.get("manifest_vision_reports")
    if not isinstance(manifest_reports, list) or len(manifest_reports) != 2:
        raise Phase5BuildError(
            f"{label} Golden manifest must lock exactly two independent Vision reports"
        )
    primary_report = golden_evidence.get("vision_report_artifact")
    reviewers: set[str] = set()
    reported_review_specs = inputs["golden_vision_reports"]
    if not isinstance(reported_review_specs, list) or len(reported_review_specs) != 2:
        raise Phase5BuildError(
            f"{label}.inputs.golden_vision_reports must contain exactly two reports"
        )
    if not any(_same_artifact(spec, primary_report) for spec in reported_review_specs):
        raise Phase5BuildError(
            f"{label}.inputs.golden_vision_reports must include the manifest primary report"
        )
    for index, spec in enumerate(reported_review_specs):
        if not any(_same_artifact(spec, item) for item in manifest_reports):
            raise Phase5BuildError(
                f"{label}.inputs.golden_vision_reports[{index}] is not locked by the Golden manifest"
            )
        report_path, _ = verify_hashed_file(
            spec, f"{label}.inputs.golden_vision_reports[{index}]"
        )
        vision = _json_object(report_path, f"{label} Golden Vision report {index + 1}")
        _, reviewer = _accepted_report(
            vision,
            job_id=golden_evidence["job_id"],
            image_path=golden_evidence["master"]["path"],
            image_sha256=golden_evidence["master"]["sha256"],
            golden_reference=True,
            threshold=golden_evidence["threshold"],
            label=f"{label} Golden Vision report {index + 1}",
        )
        if vision.get("golden_reference") is not True:
            raise Phase5BuildError(
                f"{label} Golden Vision report {index + 1} must set golden_reference true"
            )
        reviewer_key = canonical_reviewer_identity(reviewer)
        if reviewer_key in reviewers:
            raise Phase5BuildError(
                f"{label} Golden Vision reports duplicate reviewer {reviewer!r}"
            )
        reviewers.add(reviewer_key)
    if len(reviewers) != 2:
        raise Phase5BuildError(
            f"{label} Golden style requires two independent accepted Vision reviews"
        )


def _entry_claims_acceptance(entry: dict[str, Any]) -> bool:
    vision = entry.get("vision_reports")
    return (
        entry.get("provenance_report") is not None
        and entry.get("automated_report") is not None
        and isinstance(vision, list)
        and bool(vision)
    )


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _resolve_provenance_artifact(report_path: Path, raw_path: Any, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        raise Phase5BuildError(f"{label} must be a build-root-relative POSIX path")
    portable = PurePosixPath(raw_path)
    if portable.is_absolute() or any(
        part in {"", ".", ".."} for part in portable.parts
    ):
        raise Phase5BuildError(f"{label} must stay inside the provenance build root")
    lexical = report_path.parent.joinpath(*portable.parts)
    bound = _bound_artifact_for_path(lexical)
    if bound is not None:
        return bound.path
    resolved = lexical.resolve()
    try:
        resolved.relative_to(report_path.parent.resolve())
    except ValueError as exc:
        raise Phase5BuildError(f"{label} escapes the provenance build root") from exc
    if not resolved.is_file():
        raise Phase5BuildError(f"{label} does not exist: {raw_path}")
    return resolved


@contextmanager
def _bound_directory_snapshot(directory: Path, label: str) -> Iterator[Path]:
    """Materialize one recursive logical bundle from active bound bytes."""

    registry = _BOUND_ARTIFACT_CONTEXT.get()
    if registry is None:
        raise Phase5BuildError(f"{label} lacks an immutable artifact registry")
    logical_root = Path(os.path.abspath(directory))
    members: list[tuple[BoundArtifact, Path]] = []
    for bound in registry.values():
        try:
            relative = bound.path.relative_to(logical_root)
        except ValueError:
            continue
        if not relative.parts or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            raise Phase5BuildError(f"{label} contains an escaping bundle member")
        members.append((bound, relative))
    if not members:
        bound_directories = sorted(
            {bound.path.parent.as_posix() for bound in registry.values()}
        )
        raise Phase5BuildError(
            f"{label} has no files in its bound artifact registry for "
            f"{logical_root}; bound directory count={len(bound_directories)}, "
            f"sample={bound_directories[:8]}"
        )
    snapshot_parent = REPO_ROOT / "tmp" / "map-production"
    snapshot_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".phase5-parent-control-snapshot-", dir=snapshot_parent
    ) as temporary_name:
        physical_root = Path(temporary_name)
        seen: set[str] = set()
        for bound, relative in members:
            spelling = relative.as_posix()
            folded = spelling.casefold() if os.name == "nt" else spelling
            if folded in seen:
                raise Phase5BuildError(f"{label} has colliding bundle filenames")
            seen.add(folded)
            bound.copy_to(physical_root / relative)
        yield physical_root


def _verify_report_input_hashes(report: dict[str, Any], label: str) -> None:
    inputs = report.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise Phase5BuildError(f"{label}.inputs must be a non-empty object")
    for role, spec in inputs.items():
        if spec is None:
            continue
        verify_hashed_file(spec, f"{label}.inputs.{role}")


def _verify_assembly_provenance(
    provenance: dict[str, Any],
    *,
    sheet_id: str,
    contract: dict[str, Any] | None,
    label: str,
    golden_style: dict[str, str] | None = None,
) -> None:
    inputs = provenance.get("inputs")
    seams = provenance.get("seams")
    if not isinstance(inputs, list) or not inputs:
        raise Phase5BuildError(f"{label}.inputs must list the source metatiles")
    if not isinstance(seams, list):
        raise Phase5BuildError(f"{label}.seams must be an array")
    positions: set[tuple[int, int]] = set()
    for index, spec in enumerate(inputs):
        if not isinstance(spec, dict):
            raise Phase5BuildError(f"{label}.inputs[{index}] must be an object")
        position = (spec.get("column"), spec.get("row"))
        if not all(
            isinstance(value, int) and not isinstance(value, bool) for value in position
        ):
            raise Phase5BuildError(f"{label}.inputs[{index}] has an invalid position")
        if position in positions:
            raise Phase5BuildError(f"{label} duplicates metatile {position}")
        positions.add(position)
        verify_hashed_file(spec, f"{label}.inputs[{index}]")
        if spec.get("receipt") is None:
            raise Phase5BuildError(
                f"{label}.inputs[{index}] must lock its generation receipt"
            )

    if contract is not None:
        plan = metatile_plan(contract)
        if plan is None:
            raise Phase5BuildError(f"{sheet_id} has no metatile resolution contract")
        expected_positions = {
            (record["column"], record["row"]) for record in plan["tiles"]
        }
        if positions != expected_positions:
            raise Phase5BuildError(
                f"{label} metatile coverage mismatch: "
                f"missing={sorted(expected_positions - positions)}, "
                f"extra={sorted(positions - expected_positions)}"
            )
        expected_seam_boxes: dict[tuple[str, int, int], list[int]] = {}
        for record in plan["tiles"]:
            column = record["column"]
            row = record["row"]
            source_left, source_top, source_right, source_bottom = record[
                "source_core_box_px"
            ]
            if column + 1 < plan["columns"]:
                expected_seam_boxes[("x", column, row)] = [
                    plan["stride_px"],
                    source_top,
                    plan["metatile_size_px"],
                    source_bottom,
                ]
            if row + 1 < plan["rows"]:
                expected_seam_boxes[("y", column, row)] = [
                    source_left,
                    plan["stride_px"],
                    source_right,
                    plan["metatile_size_px"],
                ]
        actual_seams: dict[tuple[str, int, int], dict[str, Any]] = {}
        for index, seam in enumerate(seams):
            if not isinstance(seam, dict):
                raise Phase5BuildError(f"{label}.seams[{index}] must be an object")
            identity = (seam.get("axis"), seam.get("column"), seam.get("row"))
            if (
                identity[0] not in {"x", "y"}
                or not isinstance(identity[1], int)
                or isinstance(identity[1], bool)
                or not isinstance(identity[2], int)
                or isinstance(identity[2], bool)
            ):
                raise Phase5BuildError(
                    f"{label}.seams[{index}] has an invalid identity"
                )
            if identity in actual_seams:
                raise Phase5BuildError(f"{label} duplicates effective seam {identity}")
            actual_seams[identity] = seam
        expected_identities = set(expected_seam_boxes)
        actual_identities = set(actual_seams)
        if actual_identities != expected_identities:
            raise Phase5BuildError(
                f"{label} effective seam coverage mismatch: "
                f"missing={sorted(expected_identities - actual_identities)}, "
                f"extra={sorted(actual_identities - expected_identities)}"
            )
        for identity, expected_box in expected_seam_boxes.items():
            if actual_seams[identity].get("effective_box_px") != expected_box:
                raise Phase5BuildError(
                    f"{label} seam {identity} effective_box_px does not match the plan"
                )
    else:
        plan = {"metatile_size_px": 2048}
    verify_generation_receipts(
        {"tiles": inputs},
        sheet_id=sheet_id,
        plan=plan,
        golden_style=golden_style,
    )

    minimum_ssim = provenance.get("minimum_overlap_ssim")
    maximum_mean = provenance.get("maximum_rgb_mean_difference")
    maximum_p95 = provenance.get("maximum_rgb_p95_difference")
    if (
        not _finite_number(minimum_ssim)
        or minimum_ssim < MINIMUM_ALLOWED_OVERLAP_SSIM
        or minimum_ssim > 1.0
    ):
        raise Phase5BuildError(
            f"{label}.minimum_overlap_ssim must be at least "
            f"{MINIMUM_ALLOWED_OVERLAP_SSIM}"
        )
    if (
        not _finite_number(maximum_mean)
        or maximum_mean < 0
        or maximum_mean > MAXIMUM_RGB_MEAN_DIFFERENCE
    ):
        raise Phase5BuildError(
            f"{label}.maximum_rgb_mean_difference must be at most "
            f"{MAXIMUM_RGB_MEAN_DIFFERENCE}"
        )
    if (
        not _finite_number(maximum_p95)
        or maximum_p95 < 0
        or maximum_p95 > MAXIMUM_RGB_P95_DIFFERENCE
    ):
        raise Phase5BuildError(
            f"{label}.maximum_rgb_p95_difference must be at most "
            f"{MAXIMUM_RGB_P95_DIFFERENCE}"
        )
    for index, seam in enumerate(seams):
        if not isinstance(seam, dict):
            raise Phase5BuildError(f"{label}.seams[{index}] must be an object")
        ssim = seam.get("ssim")
        rgb_mean = seam.get("rgb_mean_abs_difference")
        rgb_p95 = seam.get("rgb_p95_abs_difference")
        if not _finite_number(ssim) or ssim < minimum_ssim:
            raise Phase5BuildError(f"{label}.seams[{index}] fails the SSIM gate")
        if not _finite_number(rgb_mean) or rgb_mean > maximum_mean:
            raise Phase5BuildError(f"{label}.seams[{index}] fails the RGB mean gate")
        if not _finite_number(rgb_p95) or rgb_p95 > maximum_p95:
            raise Phase5BuildError(f"{label}.seams[{index}] fails the RGB p95 gate")


def _expected_composite_children(
    sheet: dict[str, Any], catalog_by_id: dict[str, dict[str, Any]]
) -> set[str]:
    if sheet.get("sheet_type") == "world":
        return {
            sheet_id
            for sheet_id, item in catalog_by_id.items()
            if item.get("sheet_type") == "continent"
        }

    target_id = sheet.get("id")

    def descends_from_target(item: dict[str, Any]) -> bool:
        parent_id = item.get("parent_id")
        visited: set[str] = set()
        while isinstance(parent_id, str) and parent_id not in visited:
            if parent_id == target_id:
                return True
            visited.add(parent_id)
            parent = catalog_by_id.get(parent_id)
            parent_id = parent.get("parent_id") if isinstance(parent, dict) else None
        return False

    return {
        sheet_id
        for sheet_id, item in catalog_by_id.items()
        if item.get("sheet_type") in GENERATION_TYPES and descends_from_target(item)
    }


def _verify_composite_provenance(
    provenance: dict[str, Any],
    *,
    sheet: dict[str, Any],
    catalog_by_id: dict[str, dict[str, Any]] | None,
    sources: dict[str, dict[str, Any]] | None,
    label: str,
) -> None:
    children = provenance.get("children")
    if not isinstance(children, list) or not children:
        raise Phase5BuildError(f"{label}.children must be a non-empty array")
    child_records: dict[str, dict[str, Any]] = {}
    for index, child in enumerate(children):
        if not isinstance(child, dict) or not isinstance(child.get("sheet_id"), str):
            raise Phase5BuildError(f"{label}.children[{index}] is invalid")
        child_id = child["sheet_id"]
        if child_id in child_records:
            raise Phase5BuildError(f"{label} duplicates child {child_id!r}")
        verify_hashed_file(child, f"{label}.children[{index}]")
        child_records[child_id] = child

    if catalog_by_id is None or sources is None:
        return
    expected = _expected_composite_children(sheet, catalog_by_id)
    actual = set(child_records)
    if actual != expected:
        raise Phase5BuildError(
            f"{label} child coverage mismatch: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )
    for child_id in sorted(expected):
        source = sources.get(child_id)
        if source is None or not _entry_claims_acceptance(source):
            raise Phase5BuildError(
                f"{label} child {child_id!r} must be supplied with complete acceptance evidence"
            )
        if source.get("sha256") != child_records[child_id].get("sha256"):
            raise Phase5BuildError(
                f"{label} child {child_id!r} hash does not match its reviewed source"
            )

    native_base = provenance.get("canonical_native_base")
    observed_masks = provenance.get("observed_masks")
    composition = provenance.get("composition")
    native_contract_claimed = any(
        value is not None for value in (native_base, observed_masks, composition)
    )
    if native_contract_claimed:
        if not all(
            isinstance(value, dict)
            for value in (native_base, observed_masks, composition)
        ):
            raise Phase5BuildError(
                f"{label} canonical native composite contract is incomplete"
            )
        child_zooms = {
            child_id: child_records[child_id].get("native_zoom") for child_id in actual
        }
        if not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in child_zooms.values()
        ):
            raise Phase5BuildError(
                f"{label} canonical native composite lacks child native_zoom locks"
            )
        expected_child_order = sorted(
            actual, key=lambda child_id: (child_zooms[child_id], child_id)
        )
        if (
            native_base.get("source_coordinates_modified") is not False
            or native_base.get("world_crop_or_upscale_used") is not False
            or composition.get("resampling") != "LANCZOS-downsample-only"
            or composition.get("upscaled_child_count") != 0
            or composition.get("base_rendered_at_parent_native_resolution") is not True
            or composition.get("child_order") != expected_child_order
        ):
            raise Phase5BuildError(
                f"{label} canonical native composite permits coordinate changes or upscale"
            )
        for key in ("renderer", "resolution_contract", "material_atlas"):
            verify_hashed_file(native_base.get(key), f"{label}.{key}")
        canonical_sources = native_base.get("canon_sources")
        if not isinstance(canonical_sources, list):
            raise Phase5BuildError(f"{label}.canon_sources must be an array")
        by_role = {
            spec.get("role"): spec
            for spec in canonical_sources
            if isinstance(spec, dict)
        }
        if set(by_role) != set(CANONICAL_GEOJSON_SOURCES):
            raise Phase5BuildError(
                f"{label}.canon_sources must lock all six canonical sources"
            )
        for role, spec in by_role.items():
            verify_hashed_file(spec, f"{label}.canon_sources[{role!r}]")
        for role in ("land_sea", "transport"):
            verify_hashed_file(
                observed_masks.get(role), f"{label}.observed_masks.{role}"
            )


def verify_master_provenance(
    entry: dict[str, Any],
    *,
    sheet: dict[str, Any],
    master_path: str,
    contract: dict[str, Any] | None = None,
    catalog_by_id: dict[str, dict[str, Any]] | None = None,
    sources: dict[str, dict[str, Any]] | None = None,
) -> str:
    spec = entry.get("provenance_report")
    if spec is None:
        raise Phase5BuildError(f"{sheet['id']} acceptance requires provenance_report")
    report_path, _ = verify_hashed_file(spec, f"{sheet['id']}.provenance_report")
    report = _json_object(report_path, f"{sheet['id']} provenance report")
    label = f"{sheet['id']} provenance report"
    kind = entry.get("kind", "master")
    # Direct/canonical provenance keeps its dedicated 1.0 schema.  Only
    # composite masters are emitted by the stage-aware build report and must
    # therefore carry the newer stage-contract schema.
    expected_schema_version = (
        BUILD_REPORT_SCHEMA_VERSION if kind == "composite_master" else "1.0.0"
    )
    if report.get("schema_version") != expected_schema_version:
        raise Phase5BuildError(
            f"{label}.schema_version must be {expected_schema_version!r}"
        )
    if report.get("generated_by") != GENERATOR_ID:
        raise Phase5BuildError(f"{label}.generated_by is not the Phase 5 builder")
    if report.get("coordinate_reference_system") != "EA-WORLD-1":
        raise Phase5BuildError(f"{label} uses the wrong coordinate reference system")
    if kind == CANONICAL_RENDER_SOURCE_KIND:
        _verify_canonical_render_provenance(
            report,
            entry=entry,
            sheet=sheet,
            label=label,
        )
    else:
        _verify_report_input_hashes(report, label)

    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list):
        raise Phase5BuildError(f"{label}.artifacts must be an array")
    matches = [
        record
        for record in artifacts
        if isinstance(record, dict) and record.get("sheet_id") == sheet["id"]
    ]
    if len(matches) != 1:
        raise Phase5BuildError(
            f"{label} must contain exactly one artifact for {sheet['id']!r}"
        )
    record = matches[0]
    source_path = resolve_repo_artifact(master_path, f"{sheet['id']} reviewed master")
    source_sha = sha256_file(source_path)
    if record.get("sha256") != source_sha:
        raise Phase5BuildError(
            f"{label} master hash does not match the reviewed source"
        )
    actual_size = image_dimensions(source_path, f"{sheet['id']} reviewed master")
    if (record.get("width"), record.get("height")) != actual_size:
        raise Phase5BuildError(
            f"{label} master dimensions do not match the reviewed source"
        )
    if contract is not None and actual_size != (contract["width"], contract["height"]):
        raise Phase5BuildError(
            f"{label} master dimensions do not match the resolution contract"
        )
    built_path = _resolve_provenance_artifact(
        report_path, record.get("path"), f"{label}.artifacts[{sheet['id']}].path"
    )
    if sha256_file(built_path) != source_sha:
        raise Phase5BuildError(f"{label} materialized artifact hash is stale")

    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        raise Phase5BuildError(f"{label} artifact lacks structured provenance")
    if kind == "composite_master":
        expected_method = "deterministic-parent-composite"
    elif kind == CANONICAL_RENDER_SOURCE_KIND:
        expected_method = CANONICAL_RENDER_METHOD
    else:
        expected_method = "guarded-metatile-assembly"
    if (
        record.get("method") != expected_method
        or provenance.get("kind") != expected_method
    ):
        raise Phase5BuildError(
            f"{label} must prove method {expected_method!r}, "
            f"found record={record.get('method')!r}, provenance={provenance.get('kind')!r}"
        )
    if kind == CANONICAL_RENDER_SOURCE_KIND:
        _verify_renderer_report_binding(
            report["inputs"],
            record,
            sheet_id=sheet["id"],
            label=label,
        )
    if kind == "composite_master":
        _verify_composite_provenance(
            provenance,
            sheet=sheet,
            catalog_by_id=catalog_by_id,
            sources=sources,
            label=f"{label}.provenance",
        )
    elif kind != CANONICAL_RENDER_SOURCE_KIND:
        _verify_assembly_provenance(
            provenance,
            sheet_id=sheet["id"],
            contract=contract,
            label=f"{label}.provenance",
            golden_style=entry.get(INTERNAL_GOLDEN_STYLE_KEY),
        )
    return repo_path(report_path)


def provenance_artifact_record(provenance_path: Path, sheet_id: str) -> dict[str, Any]:
    report = _json_object(provenance_path, f"{sheet_id} provenance report")
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list):
        raise Phase5BuildError(
            f"{sheet_id} provenance report artifacts must be an array"
        )
    matches = [
        record
        for record in artifacts
        if isinstance(record, dict) and record.get("sheet_id") == sheet_id
    ]
    if len(matches) != 1:
        raise Phase5BuildError(
            f"{sheet_id} provenance report must contain exactly one matching artifact"
        )
    return matches[0]


@contextmanager
def _open_bound_image(path: Path) -> Iterator[Image.Image]:
    """Open image bytes from the active immutable binding when available."""

    bound = _bound_artifact_for_path(path)
    if bound is None:
        with Image.open(path) as image:
            yield image
        return
    with bound.open_binary() as handle, Image.open(handle) as image:
        yield image


def unpainted_band_metrics(path: Path, label: str) -> dict[str, int]:
    """Find exact black axis bands left by an unpainted assembly canvas."""

    try:
        with _open_bound_image(path) as opened:
            image = opened.convert("RGB")
        channels = image.split()
        try:
            red_green = ImageChops.lighter(channels[0], channels[1])
            try:
                non_black = ImageChops.lighter(red_green, channels[2])
                try:
                    column_projection, row_projection = non_black.getprojection()
                finally:
                    non_black.close()
            finally:
                red_green.close()
        finally:
            for channel in channels:
                channel.close()
            image.close()
    except (OSError, ValueError) as exc:
        raise Phase5BuildError(
            f"{label} cannot be scanned for unpainted bands: {exc}"
        ) from exc

    black_columns = sum(value == 0 for value in column_projection)
    black_rows = sum(value == 0 for value in row_projection)

    def runs(projection: Sequence[int]) -> int:
        count = 0
        inside = False
        for value in projection:
            if value == 0 and not inside:
                count += 1
                inside = True
            elif value != 0:
                inside = False
        return count

    return {
        "fully_black_row_count": black_rows,
        "fully_black_column_count": black_columns,
        "black_band_count": runs(row_projection) + runs(column_projection),
        "unpainted_band_count": runs(row_projection) + runs(column_projection),
    }


def load_binary_mask(
    spec: dict[str, Any], *, label: str, expected_size: tuple[int, int]
) -> tuple[Path, Image.Image]:
    path, _ = verify_hashed_file(spec, label)
    size, image_format, color_mode = image_properties(path, label)
    if size != expected_size:
        raise Phase5BuildError(
            f"{label} dimensions must match the audited master: "
            f"expected={expected_size}, actual={size}"
        )
    if image_format != "PNG" or color_mode not in {"1", "L"}:
        raise Phase5BuildError(f"{label} must be a PNG mask in mode '1' or 'L'")
    with _open_bound_image(path) as opened:
        mask = opened.convert("L").point(
            lambda value: 255 if value >= 128 else 0, mode="L"
        )
    return path, mask


def land_sea_match_ratio(control: Image.Image, observed: Image.Image) -> float:
    if control.size != observed.size:
        raise Phase5BuildError("land/sea masks have different dimensions")
    difference = ImageChops.difference(control, observed)
    try:
        histogram = difference.histogram()
        mismatched = sum(histogram[1:])
    finally:
        difference.close()
    return round(1.0 - mismatched / (control.width * control.height), 8)


def transport_within_tolerance_ratios(
    control: Image.Image, observed: Image.Image, tolerance_px: int
) -> tuple[float, float]:
    if control.size != observed.size:
        raise Phase5BuildError("transport masks have different dimensions")
    if isinstance(tolerance_px, bool) or not isinstance(tolerance_px, int):
        raise Phase5BuildError("transport tolerance must be an integer")
    if not 0 <= tolerance_px <= 8:
        raise Phase5BuildError("transport tolerance must be between 0 and 8 pixels")

    # The canonical renderer intentionally emits the same source-backed route
    # raster as the control pipeline.  Avoid two large 17x17 max filters when
    # the masks are already byte-for-byte equal; this is an exact fast path,
    # not a relaxed metric or a changed acceptance threshold.
    exact_difference = ImageChops.difference(control, observed)
    try:
        if exact_difference.getbbox() is None:
            marked = sum(control.histogram()[1:])
            if marked == 0:
                raise Phase5BuildError(
                    "transport masks must each contain marked route pixels"
                )
            return 1.0, 1.0
    finally:
        exact_difference.close()

    control_count = sum(control.histogram()[1:])
    observed_count = sum(observed.histogram()[1:])
    if control_count == 0 or observed_count == 0:
        raise Phase5BuildError("transport masks must each contain marked route pixels")
    filter_size = tolerance_px * 2 + 1
    if tolerance_px == 0:
        dilated_control = control.copy()
        dilated_observed = observed.copy()
    else:
        dilated_control = control.filter(ImageFilter.MaxFilter(filter_size))
        dilated_observed = observed.filter(ImageFilter.MaxFilter(filter_size))
    try:
        matched_control_image = ImageChops.multiply(control, dilated_observed)
        matched_observed_image = ImageChops.multiply(observed, dilated_control)
        try:
            matched_control = sum(matched_control_image.histogram()[1:])
            matched_observed = sum(matched_observed_image.histogram()[1:])
        finally:
            matched_control_image.close()
            matched_observed_image.close()
    finally:
        dilated_control.close()
        dilated_observed.close()
    return (
        round(matched_control / control_count, 8),
        round(matched_observed / observed_count, 8),
    )


def recompute_seam_evidence(
    provenance: dict[str, Any], *, label: str
) -> list[dict[str, Any]]:
    inputs = provenance.get("inputs")
    seams = provenance.get("seams")
    if not isinstance(inputs, list) or not isinstance(seams, list):
        raise Phase5BuildError(f"{label} lacks metatile inputs or seam metrics")
    by_position = {
        (item.get("column"), item.get("row")): item
        for item in inputs
        if isinstance(item, dict)
    }
    evidence: list[dict[str, Any]] = []
    for index, seam in enumerate(seams):
        if not isinstance(seam, dict):
            raise Phase5BuildError(f"{label}.seams[{index}] must be an object")
        axis = seam.get("axis")
        position = (seam.get("column"), seam.get("row"))
        neighbor_position = (
            (position[0] + 1, position[1])
            if axis == "x"
            else (position[0], position[1] + 1)
        )
        source_a = by_position.get(position)
        source_b = by_position.get(neighbor_position)
        box = seam.get("effective_box_px")
        if (
            source_a is None
            or source_b is None
            or not (
                isinstance(box, list)
                and len(box) == 4
                and all(
                    isinstance(value, int) and not isinstance(value, bool)
                    for value in box
                )
            )
        ):
            raise Phase5BuildError(f"{label}.seams[{index}] is not tied to two inputs")
        path_a, _ = verify_hashed_file(source_a, f"{label}.seams[{index}].source_a")
        path_b, _ = verify_hashed_file(source_b, f"{label}.seams[{index}].source_b")
        with (
            _open_bound_image(path_a) as opened_a,
            _open_bound_image(path_b) as opened_b,
        ):
            first_image = opened_a.convert("RGB")
            second_image = opened_b.convert("RGB")
        try:
            if axis == "x":
                overlap = box[2] - box[0]
                first = first_image.crop(tuple(box))
                second = second_image.crop((0, box[1], overlap, box[3]))
            elif axis == "y":
                overlap = box[3] - box[1]
                first = first_image.crop(tuple(box))
                second = second_image.crop((box[0], 0, box[2], overlap))
            else:
                raise Phase5BuildError(f"{label}.seams[{index}].axis is invalid")
            try:
                ssim, rgb_mean, rgb_p95 = overlap_similarity(first, second)
            finally:
                first.close()
                second.close()
        finally:
            first_image.close()
            second_image.close()
        recomputed = {
            "axis": axis,
            "column": position[0],
            "row": position[1],
            "source_a": {"path": source_a["path"], "sha256": source_a["sha256"]},
            "source_b": {"path": source_b["path"], "sha256": source_b["sha256"]},
            "effective_box_px": box,
            "ssim": round(ssim, 6),
            "rgb_mean_abs_difference": round(rgb_mean, 4),
            "rgb_p95_abs_difference": rgb_p95,
        }
        for metric in (
            "ssim",
            "rgb_mean_abs_difference",
            "rgb_p95_abs_difference",
        ):
            if seam.get(metric) != recomputed[metric]:
                raise Phase5BuildError(
                    f"{label}.seams[{index}].{metric} does not match recomputation"
                )
        if (
            recomputed["ssim"] < MINIMUM_ALLOWED_OVERLAP_SSIM
            or recomputed["rgb_mean_abs_difference"] > MAXIMUM_RGB_MEAN_DIFFERENCE
            or recomputed["rgb_p95_abs_difference"] > MAXIMUM_RGB_P95_DIFFERENCE
        ):
            raise Phase5BuildError(f"{label}.seams[{index}] fails a locked seam gate")
        evidence.append(recomputed)
    return evidence


def validate_automated_qa_report(
    report: dict[str, Any],
    *,
    entry: dict[str, Any],
    sheet: dict[str, Any],
    master_path: str,
    job_id: str,
    contract: dict[str, Any] | None,
) -> None:
    label = f"{sheet['id']} automated report"
    _validate_schema_instance(report, DEFAULT_AUTOMATED_QA_SCHEMA, label)
    kind = entry.get("kind", "master")
    if report.get("job_id") != job_id or report.get("sheet_id") != sheet["id"]:
        raise Phase5BuildError(f"{label} job or sheet identity mismatch")
    if report.get("source_kind") != kind:
        raise Phase5BuildError(f"{label}.source_kind does not match the source index")
    if not _same_artifact(
        report.get("provenance_report"), entry.get("provenance_report")
    ):
        raise Phase5BuildError(
            f"{label}.provenance_report is not the reviewed provenance"
        )

    source_path = resolve_repo_artifact(master_path, f"{sheet['id']} reviewed master")
    actual_sha = sha256_file(source_path)
    size, image_format, color_mode = image_properties(source_path, label)
    master = report["master"]
    if master.get("path") != master_path or master.get("sha256") != actual_sha:
        raise Phase5BuildError(f"{label}.master path or digest mismatch")
    if entry.get("sha256") != actual_sha:
        raise Phase5BuildError(f"{label} does not match the indexed master digest")
    if (master.get("width"), master.get("height")) != size:
        raise Phase5BuildError(f"{label}.master dimensions mismatch")
    if image_format != "PNG" or color_mode != "RGB":
        raise Phase5BuildError(f"{label} master must be a native RGB PNG")
    expected_size = (
        (contract["width"], contract["height"]) if contract is not None else size
    )
    checks = report["checks"]
    if checks["dimensions"] != {
        "passed": True,
        "expected_width": expected_size[0],
        "expected_height": expected_size[1],
        "actual_width": size[0],
        "actual_height": size[1],
    }:
        raise Phase5BuildError(f"{label}.checks.dimensions is inconsistent")
    if checks["encoding"] != {
        "passed": True,
        "expected_format": "PNG",
        "actual_format": image_format,
        "expected_color_mode": "RGB",
        "actual_color_mode": color_mode,
    }:
        raise Phase5BuildError(f"{label}.checks.encoding is inconsistent")
    if checks["digest"] != {
        "passed": True,
        "expected_sha256": entry["sha256"],
        "actual_sha256": actual_sha,
    }:
        raise Phase5BuildError(f"{label}.checks.digest is inconsistent")

    pixel_count = size[0] * size[1]
    coverage = checks["coverage"]
    expected_coverage = {
        "passed": True,
        "algorithm": "provenance-destination-coverage-v1",
        "expected_pixel_count": pixel_count,
        "covered_pixel_count": pixel_count,
        "uncovered_pixel_count": 0,
        "overlap_pixel_count": 0,
    }
    if coverage != expected_coverage:
        raise Phase5BuildError(f"{label}.checks.coverage is inconsistent")
    band_metrics = unpainted_band_metrics(source_path, label)
    expected_bands = {
        "passed": True,
        "algorithm": "coverage-and-axis-band-scan-v1",
        "tested_fill_rgb": [0, 0, 0],
        **band_metrics,
    }
    if checks["unpainted_bands"] != expected_bands:
        raise Phase5BuildError(f"{label}.checks.unpainted_bands is inconsistent")
    if any(band_metrics.values()):
        raise Phase5BuildError(f"{label} master contains black/unpainted axis bands")

    provenance_path, _ = verify_hashed_file(
        entry["provenance_report"], f"{sheet['id']}.provenance_report"
    )
    record = provenance_artifact_record(provenance_path, sheet["id"])
    provenance = record.get("provenance")
    assert isinstance(provenance, dict)  # verified before this function is called
    provenance_report = _json_object(
        provenance_path, f"{sheet['id']} provenance report"
    )
    if kind == "composite_master":
        provenance_inputs = provenance_report.get("inputs")
        source_index_spec = (
            provenance_inputs.get("source_index")
            if isinstance(provenance_inputs, dict)
            else None
        )
        verify_hashed_file(source_index_spec, f"{label}.provenance.source_index")
    seam_evidence = (
        []
        if kind in {"composite_master", CANONICAL_RENDER_SOURCE_KIND}
        else recompute_seam_evidence(provenance, label=f"{label}.seams")
    )
    seam_check = checks["seams"]
    expected_seams = {
        "passed": True,
        "minimum_overlap_ssim": MINIMUM_ALLOWED_OVERLAP_SSIM,
        "maximum_rgb_mean_difference": MAXIMUM_RGB_MEAN_DIFFERENCE,
        "maximum_rgb_p95_difference": MAXIMUM_RGB_P95_DIFFERENCE,
        "expected_count": len(seam_evidence),
        "evaluated_count": len(seam_evidence),
        "minimum_observed_ssim": (
            min(item["ssim"] for item in seam_evidence) if seam_evidence else None
        ),
        "maximum_observed_rgb_mean_difference": (
            max(item["rgb_mean_abs_difference"] for item in seam_evidence)
            if seam_evidence
            else None
        ),
        "maximum_observed_rgb_p95_difference": (
            max(item["rgb_p95_abs_difference"] for item in seam_evidence)
            if seam_evidence
            else None
        ),
        "evidence": seam_evidence,
    }
    if seam_check != expected_seams:
        raise Phase5BuildError(f"{label}.checks.seams is inconsistent")

    selected_parent_controls: dict[str, Any] | None = None
    if kind == "composite_master":
        parent_controls = report.get("parent_controls")
        if not isinstance(parent_controls, dict) or set(parent_controls) != {
            "index",
            "report",
        }:
            raise Phase5BuildError(
                f"{label} must lock the parent control index and report"
            )
        index_path, _ = verify_hashed_file(
            parent_controls["index"], f"{label}.parent_controls.index"
        )
        report_path, _ = verify_hashed_file(
            parent_controls["report"], f"{label}.parent_controls.report"
        )
        if report_path != index_path.with_name("report.json"):
            raise Phase5BuildError(
                f"{label} parent control report is not paired with its index"
            )
        try:
            from render_phase5_parent_control_masks import (
                ParentControlError,
                load_validated_parent_control_bundle,
                load_validated_parent_control_bundle_snapshot,
            )

            if _BOUND_ARTIFACT_CONTEXT.get() is None:
                parent_index, parent_report = load_validated_parent_control_bundle(
                    index_path
                )
            else:
                with _bound_directory_snapshot(
                    index_path.parent, f"{label}.parent_controls"
                ) as snapshot_root:
                    parent_index, parent_report = (
                        load_validated_parent_control_bundle_snapshot(
                            snapshot_root, logical_root=index_path.parent
                        )
                    )
        except (ImportError, ParentControlError) as exc:
            raise Phase5BuildError(
                f"{label} parent control bundle failed semantic audit: {exc}"
            ) from exc
        if not _same_artifact(parent_report.get("index"), parent_controls["index"]):
            raise Phase5BuildError(
                f"{label} parent control report does not lock the selected index"
            )
        matches = [
            item
            for item in parent_index.get("sheets", [])
            if isinstance(item, dict) and item.get("sheet_id") == sheet["id"]
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("qa_controls"), dict):
            raise Phase5BuildError(
                f"{label} parent control bundle lacks exactly one selected sheet"
            )
        selected_parent_controls = matches[0]["qa_controls"]
    elif report.get("parent_controls") is not None:
        raise Phase5BuildError(
            f"{label} non-composite evidence may not claim parent controls"
        )

    geography = report["geography"]
    land_sea = geography["land_sea"]
    if kind == "composite_master":
        provenance_observed = provenance.get("observed_masks")
        if not isinstance(provenance_observed, dict) or not _same_artifact(
            land_sea["observed"], provenance_observed.get("land_sea")
        ):
            raise Phase5BuildError(
                f"{label}.land_sea.observed is not hash-bound by provenance"
            )
    if selected_parent_controls is not None and not _same_artifact(
        land_sea["control"], selected_parent_controls.get("land_sea_control")
    ):
        raise Phase5BuildError(
            f"{label}.land_sea.control is not selected from the locked parent bundle"
        )
    _, land_control = load_binary_mask(
        land_sea["control"], label=f"{label}.land_sea.control", expected_size=size
    )
    _, land_observed = load_binary_mask(
        land_sea["observed"], label=f"{label}.land_sea.observed", expected_size=size
    )
    try:
        if (
            kind == "composite_master"
            and land_control.tobytes() == land_observed.tobytes()
        ):
            raise Phase5BuildError(
                f"{label} land/sea observation decodes identically to its control"
            )
        land_ratio = land_sea_match_ratio(land_control, land_observed)
    finally:
        land_control.close()
        land_observed.close()
    if (
        land_ratio < MINIMUM_LAND_SEA_MATCH_RATIO
        or land_sea["match_ratio"] != land_ratio
    ):
        raise Phase5BuildError(f"{label} land/sea mask evidence fails or is stale")

    transport = geography["transport"]
    if kind == "composite_master":
        provenance_observed = provenance.get("observed_masks")
        if not isinstance(provenance_observed, dict) or not _same_artifact(
            transport["observed"], provenance_observed.get("transport")
        ):
            raise Phase5BuildError(
                f"{label}.transport.observed is not hash-bound by provenance"
            )
    if selected_parent_controls is not None and not _same_artifact(
        transport["control"], selected_parent_controls.get("transport_control")
    ):
        raise Phase5BuildError(
            f"{label}.transport.control is not selected from the locked parent bundle"
        )
    _, route_control = load_binary_mask(
        transport["control"], label=f"{label}.transport.control", expected_size=size
    )
    _, route_observed = load_binary_mask(
        transport["observed"], label=f"{label}.transport.observed", expected_size=size
    )
    try:
        if (
            kind == "composite_master"
            and route_control.tobytes() == route_observed.tobytes()
        ):
            raise Phase5BuildError(
                f"{label} transport observation decodes identically to its control"
            )
        control_ratio, observed_ratio = transport_within_tolerance_ratios(
            route_control, route_observed, transport["tolerance_px"]
        )
    finally:
        route_control.close()
        route_observed.close()
    if (
        control_ratio < MINIMUM_TRANSPORT_WITHIN_TOLERANCE_RATIO
        or observed_ratio < MINIMUM_TRANSPORT_WITHIN_TOLERANCE_RATIO
        or transport["control_within_tolerance_ratio"] != control_ratio
        or transport["observed_within_tolerance_ratio"] != observed_ratio
    ):
        raise Phase5BuildError(f"{label} transport mask evidence fails or is stale")


def accepted_evidence(
    entry: dict[str, Any],
    *,
    sheet: dict[str, Any],
    master_path: str,
    job_id: str,
    contract: dict[str, Any] | None = None,
    catalog_by_id: dict[str, dict[str, Any]] | None = None,
    sources: dict[str, dict[str, Any]] | None = None,
) -> QAEvidence | None:
    automated_spec = entry.get("automated_report")
    vision_specs = entry.get("vision_reports")
    if automated_spec is None and vision_specs is None:
        return None
    if automated_spec is None or not isinstance(vision_specs, list):
        raise Phase5BuildError(
            f"{sheet['id']} acceptance evidence requires automated_report and vision_reports"
        )
    provenance_path = verify_master_provenance(
        entry,
        sheet=sheet,
        master_path=master_path,
        contract=contract,
        catalog_by_id=catalog_by_id,
        sources=sources,
    )
    threshold = acceptance_threshold(sheet)
    required = required_review_count(sheet)
    if len(vision_specs) != required:
        raise Phase5BuildError(
            f"{sheet['id']} requires exactly {required} manifest-bound Vision review(s), "
            f"found {len(vision_specs)}"
        )
    automated_path, _ = verify_hashed_file(
        automated_spec, f"{sheet['id']}.automated_report"
    )
    automated_raw = _json_object(automated_path, f"{sheet['id']} automated report")
    validate_automated_qa_report(
        automated_raw,
        entry=entry,
        sheet=sheet,
        master_path=master_path,
        job_id=job_id,
        contract=contract,
    )
    reviewers: set[str] = set()
    vision_paths: list[str] = []
    primary_score: int | None = None
    primary_reviewer: str | None = None
    reviewed_master = resolve_repo_artifact(
        master_path, f"{sheet['id']} reviewed master"
    )
    reviewed_master_sha256 = sha256_file(reviewed_master)
    for index, spec in enumerate(vision_specs):
        report_path, _ = verify_hashed_file(
            spec, f"{sheet['id']}.vision_reports[{index}]"
        )
        report = _json_object(report_path, f"{sheet['id']} vision report {index + 1}")
        score, reviewer = _accepted_report(
            report,
            job_id=job_id,
            image_path=master_path,
            image_sha256=reviewed_master_sha256,
            golden_reference=False,
            threshold=threshold,
            label=f"{sheet['id']} vision report {index + 1}",
        )
        try:
            vision_evidence.validate_report_vision_bundle(
                report,
                sheet_id=sheet["id"],
                master_path=reviewed_master,
                master_sha256=reviewed_master_sha256,
            )
        except vision_evidence.Phase5VisionEvidenceError as exc:
            raise Phase5BuildError(
                f"{sheet['id']} vision report {index + 1}: {exc}"
            ) from exc
        reviewer_key = canonical_reviewer_identity(reviewer)
        if reviewer_key in reviewers:
            raise Phase5BuildError(
                f"{sheet['id']} vision reports duplicate reviewer {reviewer!r}"
            )
        reviewers.add(reviewer_key)
        vision_paths.append(repo_path(report_path))
        if primary_score is None:
            primary_score = score
            primary_reviewer = reviewer
    if len(reviewers) != required:
        raise Phase5BuildError(
            f"{sheet['id']} requires {required} independent accepted review(s), "
            f"found {len(reviewers)}"
        )
    assert primary_score is not None and primary_reviewer is not None
    return QAEvidence(
        provenance_path=provenance_path,
        automated_path=repo_path(automated_path),
        vision_paths=tuple(vision_paths),
        primary_score=primary_score,
        primary_reviewer=primary_reviewer,
    )


def image_properties(path: Path, label: str) -> tuple[tuple[int, int], str, str]:
    try:
        with _open_bound_image(path) as image:
            image.verify()
        with _open_bound_image(path) as image:
            return image.size, image.format or "", image.mode
    except (OSError, ValueError) as exc:
        raise Phase5BuildError(f"{label} is not a readable image: {exc}") from exc


def image_dimensions(path: Path, label: str) -> tuple[int, int]:
    size, _, _ = image_properties(path, label)
    return size


def _preflight_source_entry_bound(
    entry: dict[str, Any],
    *,
    sheet: dict[str, Any],
    contract: dict[str, Any],
    catalog_by_id: dict[str, dict[str, Any]] | None = None,
    sources: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Verify source hashes, dimensions, positions, and any claimed QA in dry-run."""

    sheet_id = sheet["id"]
    kind = entry.get("kind", "master")
    if kind in {
        "master",
        "composite_master",
        CANONICAL_RENDER_SOURCE_KIND,
    }:
        path, _ = verify_hashed_file(entry, f"{sheet_id} master source")
        expected = (contract["width"], contract["height"])
        actual = image_dimensions(path, f"{sheet_id} master source")
        if actual != expected:
            raise Phase5BuildError(
                f"{sheet_id} source dimensions must match the resolution contract exactly: "
                f"expected={expected[0]}x{expected[1]}, actual={actual[0]}x{actual[1]}; "
                "blind upscale is forbidden"
            )
        accepted_evidence(
            entry,
            sheet=sheet,
            master_path=repo_path(path),
            job_id=job_id_for_sheet(sheet_id),
            contract=contract,
            catalog_by_id=catalog_by_id,
            sources=sources,
        )
        return

    plan = metatile_plan(contract)
    if plan is None:
        raise Phase5BuildError(f"{sheet_id} does not have a metatile contract")
    tile_specs = entry.get("tiles")
    if not isinstance(tile_specs, list):
        raise Phase5BuildError(f"{sheet_id} metatiles source requires a tiles array")
    positions: set[tuple[int, int]] = set()
    for index, spec in enumerate(tile_specs):
        if not isinstance(spec, dict):
            raise Phase5BuildError(f"{sheet_id} tiles[{index}] must be an object")
        position = (spec.get("column"), spec.get("row"))
        if not all(
            isinstance(value, int) and not isinstance(value, bool) for value in position
        ):
            raise Phase5BuildError(f"{sheet_id} tiles[{index}] has invalid position")
        if position in positions:
            raise Phase5BuildError(f"{sheet_id} duplicates metatile {position}")
        positions.add(position)
        path, _ = verify_hashed_file(spec, f"{sheet_id} metatile {position}")
        actual = image_dimensions(path, f"{sheet_id} metatile {position}")
        size = plan["metatile_size_px"]
        if actual != (size, size):
            raise Phase5BuildError(
                f"{sheet_id} metatile {position} must be {size}x{size}, "
                f"found {actual[0]}x{actual[1]}"
            )
    expected_positions = {(tile["column"], tile["row"]) for tile in plan["tiles"]}
    if positions != expected_positions:
        raise Phase5BuildError(
            f"{sheet_id} metatile coverage mismatch: "
            f"missing={sorted(expected_positions - positions)}, "
            f"extra={sorted(positions - expected_positions)}"
        )
    verify_generation_receipts(
        entry,
        sheet_id=sheet_id,
        plan=plan,
        golden_style=entry.get(INTERNAL_GOLDEN_STYLE_KEY),
    )


def preflight_source_entry(
    entry: dict[str, Any],
    *,
    sheet: dict[str, Any],
    contract: dict[str, Any],
    catalog_by_id: dict[str, dict[str, Any]] | None = None,
    sources: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Preflight one source exclusively from its source-index byte bindings."""

    registry = entry.get(INTERNAL_BOUND_ARTIFACTS_KEY)
    bindings = registry if isinstance(registry, dict) else None
    with bound_artifact_context(bindings):
        _preflight_source_entry_bound(
            entry,
            sheet=sheet,
            contract=contract,
            catalog_by_id=catalog_by_id,
            sources=sources,
        )


def verify_control_master(path: Path) -> str:
    if not path.is_file():
        raise Phase5BuildError(f"world control master does not exist: {path}")
    metadata_path = path.with_suffix(".json")
    if not metadata_path.is_file():
        raise Phase5BuildError(
            f"world control metadata does not exist: {metadata_path}"
        )
    metadata = _json_object(metadata_path, "world control metadata")
    expected = metadata.get("output", {}).get("sha256")
    actual = sha256_file(path)
    if expected != actual:
        raise Phase5BuildError(
            f"world control hash mismatch: metadata={expected!r}, actual={actual}"
        )
    expected_size = (
        metadata.get("output", {}).get("width"),
        metadata.get("output", {}).get("height"),
    )
    if image_dimensions(path, "world control master") != expected_size:
        raise Phase5BuildError("world control dimensions do not match metadata")
    return actual


def metatile_plan(sheet_contract: dict[str, Any]) -> dict[str, Any] | None:
    profile = sheet_contract.get("metatiles")
    if not isinstance(profile, dict):
        return None
    width, height = sheet_contract["width"], sheet_contract["height"]
    size = profile["size_px"]
    gutter = profile["gutter_each_side_px"]
    stride = profile["stride_px"]
    records: list[dict[str, Any]] = []
    for row in range(profile["rows"]):
        for column in range(profile["columns"]):
            # Adjacent 2048px canvases begin one 1536px stride apart.  Only
            # interior sides lose their 256px half-overlap; the outer sides
            # retain their gutter so the contract's coverage formula remains
            # true and narrow final rows/columns cannot become black bands.
            canvas_x = column * stride
            canvas_y = row * stride
            source_left = 0 if column == 0 else gutter
            source_top = 0 if row == 0 else gutter
            source_right = (
                min(size, width - canvas_x)
                if column == profile["columns"] - 1
                else size - gutter
            )
            source_bottom = (
                min(size, height - canvas_y)
                if row == profile["rows"] - 1
                else size - gutter
            )
            if source_right <= source_left or source_bottom <= source_top:
                raise Phase5BuildError(
                    f"{sheet_contract['sheet_id']} contract contains an empty metatile core"
                )
            destination_left = canvas_x + source_left
            destination_top = canvas_y + source_top
            destination_right = canvas_x + source_right
            destination_bottom = canvas_y + source_bottom
            records.append(
                {
                    "column": column,
                    "row": row,
                    "canvas_origin_px": [canvas_x, canvas_y],
                    "source_core_box_px": [
                        source_left,
                        source_top,
                        source_right,
                        source_bottom,
                    ],
                    "destination_box_px": [
                        destination_left,
                        destination_top,
                        destination_right,
                        destination_bottom,
                    ],
                }
            )
    if len(records) != profile["count"]:
        raise Phase5BuildError(f"{sheet_contract['sheet_id']} metatile count mismatch")
    covered_area = 0
    destinations: list[tuple[int, int, int, int]] = []
    for record in records:
        left, top, right, bottom = record["destination_box_px"]
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise Phase5BuildError(
                f"{sheet_contract['sheet_id']} metatile destination escapes the master"
            )
        box = (left, top, right, bottom)
        for other in destinations:
            overlap_width = min(right, other[2]) - max(left, other[0])
            overlap_height = min(bottom, other[3]) - max(top, other[1])
            if overlap_width > 0 and overlap_height > 0:
                raise Phase5BuildError(
                    f"{sheet_contract['sheet_id']} metatile destinations overlap"
                )
        destinations.append(box)
        covered_area += (right - left) * (bottom - top)
    if covered_area != width * height:
        raise Phase5BuildError(
            f"{sheet_contract['sheet_id']} metatile destinations do not cover the master: "
            f"covered={covered_area}, expected={width * height}"
        )
    return {
        "sheet_id": sheet_contract["sheet_id"],
        "master_size": [width, height],
        "metatile_size_px": size,
        "gutter_each_side_px": gutter,
        "stride_px": stride,
        "columns": profile["columns"],
        "rows": profile["rows"],
        "count": profile["count"],
        "tiles": records,
    }


def overlap_similarity(
    first: Image.Image, second: Image.Image
) -> tuple[float, float, int]:
    if first.size != second.size:
        raise Phase5BuildError("overlap strips have different dimensions")
    first_rgb = first.convert("RGB")
    second_rgb = second.convert("RGB")
    first_l = first_rgb.convert("L")
    second_l = second_rgb.convert("L")
    try:
        rgb_difference = ImageChops.difference(first_rgb, second_rgb)
        try:
            channel_means = ImageStat.Stat(rgb_difference).mean
            rgb_mean = sum(channel_means) / len(channel_means)
            histogram = rgb_difference.histogram()
            target = math.ceil(first_rgb.width * first_rgb.height * 3 * 0.95)
            cumulative = 0
            rgb_p95 = 255
            for value in range(256):
                cumulative += sum(
                    histogram[channel * 256 + value] for channel in range(3)
                )
                if cumulative >= target:
                    rgb_p95 = value
                    break
        finally:
            rgb_difference.close()

        luminance_difference = ImageChops.difference(first_l, second_l)
        try:
            luminance_mae = ImageStat.Stat(luminance_difference).mean[0]
        finally:
            luminance_difference.close()
        if luminance_mae == 0:
            return 1.0, rgb_mean, rgb_p95

        # Compute covariance on a bounded deterministic sample.  Pillow's
        # multiply operation quantizes products back to eight bits and can
        # make identical high-contrast strips appear negatively correlated.
        # A 256x256 LANCZOS sample is sufficient for the low-frequency seam
        # gate while keeping 99-metatile builds inexpensive.
        sample_size = (
            min(256, first_l.width),
            min(256, first_l.height),
        )
        sampled_first = (
            first_l
            if first_l.size == sample_size
            else first_l.resize(sample_size, Image.Resampling.LANCZOS)
        )
        sampled_second = (
            second_l
            if second_l.size == sample_size
            else second_l.resize(sample_size, Image.Resampling.LANCZOS)
        )
        try:
            first_values = list(sampled_first.getdata())
            second_values = list(sampled_second.getdata())
            count = len(first_values)
            mu_first = sum(first_values) / count
            mu_second = sum(second_values) / count
            var_first = sum((value - mu_first) ** 2 for value in first_values) / count
            var_second = (
                sum((value - mu_second) ** 2 for value in second_values) / count
            )
            covariance = (
                sum(
                    (left - mu_first) * (right - mu_second)
                    for left, right in zip(first_values, second_values)
                )
                / count
            )
        finally:
            if sampled_first is not first_l:
                sampled_first.close()
            if sampled_second is not second_l:
                sampled_second.close()
        c1 = (0.01 * 255) ** 2
        c2 = (0.03 * 255) ** 2
        denominator = (mu_first**2 + mu_second**2 + c1) * (var_first + var_second + c2)
        ssim = (
            ((2 * mu_first * mu_second + c1) * (2 * covariance + c2)) / denominator
            if denominator
            else 1.0
        )
        return max(-1.0, min(1.0, ssim)), rgb_mean, rgb_p95
    finally:
        first_l.close()
        second_l.close()
        first_rgb.close()
        second_rgb.close()


def _stitch_metatiles_bound(
    entry: dict[str, Any],
    plan: dict[str, Any],
    output_path: Path,
    *,
    minimum_ssim: float,
) -> dict[str, Any]:
    if minimum_ssim < MINIMUM_ALLOWED_OVERLAP_SSIM:
        raise Phase5BuildError(
            f"minimum overlap SSIM cannot be lower than {MINIMUM_ALLOWED_OVERLAP_SSIM}"
        )
    tile_specs = entry.get("tiles")
    if not isinstance(tile_specs, list):
        raise Phase5BuildError(
            f"{plan['sheet_id']} metatiles source requires a tiles array"
        )
    specs: dict[tuple[int, int], dict[str, Any]] = {}
    for index, spec in enumerate(tile_specs):
        if not isinstance(spec, dict):
            raise Phase5BuildError(
                f"{plan['sheet_id']} tiles[{index}] must be an object"
            )
        position = (spec.get("column"), spec.get("row"))
        if not all(
            isinstance(value, int) and not isinstance(value, bool) for value in position
        ):
            raise Phase5BuildError(
                f"{plan['sheet_id']} tiles[{index}] has invalid position"
            )
        if position in specs:
            raise Phase5BuildError(f"{plan['sheet_id']} duplicates metatile {position}")
        specs[position] = spec
    expected_positions = {(tile["column"], tile["row"]) for tile in plan["tiles"]}
    if set(specs) != expected_positions:
        missing = sorted(expected_positions - set(specs))
        extra = sorted(set(specs) - expected_positions)
        raise Phase5BuildError(
            f"{plan['sheet_id']} metatile coverage mismatch: missing={missing}, extra={extra}"
        )

    size = plan["metatile_size_px"]
    stride = plan["stride_px"]
    overlap = size - stride
    opened: dict[tuple[int, int], Image.Image] = {}
    input_hashes: list[dict[str, Any]] = []
    try:
        for position in sorted(specs):
            path, digest = verify_hashed_file(
                specs[position], f"{plan['sheet_id']} metatile {position}"
            )
            if _bound_artifact_for_path(path) is None:
                raise Phase5BuildError(
                    f"{plan['sheet_id']} metatile {position} is missing its "
                    "immutable source-index byte binding"
                )
            with _open_bound_image(path) as source_image:
                image = ImageOps.exif_transpose(source_image).convert("RGB")
            if image.size != (size, size):
                image.close()
                raise Phase5BuildError(
                    f"{plan['sheet_id']} metatile {position} must be {size}x{size}, "
                    f"found {image.width}x{image.height}"
                )
            opened[position] = image
            input_record = {
                "column": position[0],
                "row": position[1],
                "path": repo_path(path),
                "sha256": digest,
            }
            if isinstance(specs[position].get("receipt"), dict):
                input_record["receipt"] = dict(specs[position]["receipt"])
            input_hashes.append(input_record)

        seam_metrics: list[dict[str, Any]] = []
        plan_records = {
            (record["column"], record["row"]): record for record in plan["tiles"]
        }
        for column, row in sorted(opened):
            current = opened[(column, row)]
            record = plan_records[(column, row)]
            source_left, source_top, source_right, source_bottom = record[
                "source_core_box_px"
            ]
            right = opened.get((column + 1, row))
            if right is not None:
                # Compare only the perpendicular span that this row contributes
                # to the master.  Discarded top/bottom context must not make a
                # visible seam pass or fail.
                first = current.crop((stride, source_top, size, source_bottom))
                second = right.crop((0, source_top, overlap, source_bottom))
                try:
                    ssim, rgb_mean, rgb_p95 = overlap_similarity(first, second)
                finally:
                    first.close()
                    second.close()
                seam_metrics.append(
                    {
                        "axis": "x",
                        "column": column,
                        "row": row,
                        "effective_box_px": [
                            stride,
                            source_top,
                            size,
                            source_bottom,
                        ],
                        "ssim": round(ssim, 6),
                        "rgb_mean_abs_difference": round(rgb_mean, 4),
                        "rgb_p95_abs_difference": rgb_p95,
                    }
                )
            below = opened.get((column, row + 1))
            if below is not None:
                first = current.crop((source_left, stride, source_right, size))
                second = below.crop((source_left, 0, source_right, overlap))
                try:
                    ssim, rgb_mean, rgb_p95 = overlap_similarity(first, second)
                finally:
                    first.close()
                    second.close()
                seam_metrics.append(
                    {
                        "axis": "y",
                        "column": column,
                        "row": row,
                        "effective_box_px": [
                            source_left,
                            stride,
                            source_right,
                            size,
                        ],
                        "ssim": round(ssim, 6),
                        "rgb_mean_abs_difference": round(rgb_mean, 4),
                        "rgb_p95_abs_difference": rgb_p95,
                    }
                )
        failed = [
            metric
            for metric in seam_metrics
            if metric["ssim"] < minimum_ssim
            or metric["rgb_mean_abs_difference"] > MAXIMUM_RGB_MEAN_DIFFERENCE
            or metric["rgb_p95_abs_difference"] > MAXIMUM_RGB_P95_DIFFERENCE
        ]
        if failed:
            worst = max(
                failed,
                key=lambda metric: max(
                    minimum_ssim - metric["ssim"],
                    metric["rgb_mean_abs_difference"] - MAXIMUM_RGB_MEAN_DIFFERENCE,
                    metric["rgb_p95_abs_difference"] - MAXIMUM_RGB_P95_DIFFERENCE,
                ),
            )
            raise Phase5BuildError(
                f"{plan['sheet_id']} overlap quality gate failed: "
                f"minimum_ssim={minimum_ssim}, "
                f"maximum_rgb_mean={MAXIMUM_RGB_MEAN_DIFFERENCE}, "
                f"maximum_rgb_p95={MAXIMUM_RGB_P95_DIFFERENCE}, worst={worst}"
            )

        canvas = Image.new("RGB", tuple(plan["master_size"]), (0, 0, 0))
        try:
            for record in plan["tiles"]:
                tile = opened[(record["column"], record["row"])]
                core = tile.crop(tuple(record["source_core_box_px"]))
                try:
                    canvas.paste(core, tuple(record["destination_box_px"][:2]))
                finally:
                    core.close()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            canvas.save(output_path, format="PNG", compress_level=6, optimize=False)
        finally:
            canvas.close()
        return {
            "inputs": input_hashes,
            "seams": seam_metrics,
            "minimum_overlap_ssim": minimum_ssim,
            "maximum_rgb_mean_difference": MAXIMUM_RGB_MEAN_DIFFERENCE,
            "maximum_rgb_p95_difference": MAXIMUM_RGB_P95_DIFFERENCE,
        }
    finally:
        for image in opened.values():
            image.close()


def stitch_metatiles(
    entry: dict[str, Any],
    plan: dict[str, Any],
    output_path: Path,
    *,
    minimum_ssim: float,
) -> dict[str, Any]:
    """Assemble metatiles from the exact bytes bound with the source index."""

    registry = entry.get(INTERNAL_BOUND_ARTIFACTS_KEY)
    if not isinstance(registry, dict):
        raise Phase5BuildError(
            f"{plan['sheet_id']} metatile assembly requires immutable "
            "source-index byte bindings"
        )
    with bound_artifact_context(registry):
        return _stitch_metatiles_bound(
            entry,
            plan,
            output_path,
            minimum_ssim=minimum_ssim,
        )


def _world_crop(
    source: Image.Image,
    bounds: Sequence[float],
    target_size: tuple[int, int],
) -> Image.Image:
    source_width, source_height = source.size
    extent = (
        bounds[0] / WORLD_EXTENT * (source_width - 1),
        bounds[1] / WORLD_EXTENT * (source_height - 1),
        bounds[2] / WORLD_EXTENT * (source_width - 1),
        bounds[3] / WORLD_EXTENT * (source_height - 1),
    )
    return source.transform(
        target_size,
        Image.Transform.EXTENT,
        data=extent,
        resample=Image.Resampling.BICUBIC,
    )


def provisional_seed(
    control_master: Path,
    style_master: Path | None,
    *,
    bounds: Sequence[float],
    target_size: tuple[int, int],
) -> Image.Image:
    with Image.open(control_master) as opened:
        control = _world_crop(
            ImageOps.exif_transpose(opened).convert("RGB"), bounds, target_size
        )
    if style_master is None:
        return control
    with Image.open(style_master) as opened:
        style = _world_crop(
            ImageOps.exif_transpose(opened).convert("RGB"), bounds, target_size
        )
    try:
        seeded = Image.blend(control, style, 0.62)
    finally:
        control.close()
        style.close()
    return seeded


def _intersection(
    first: Sequence[float], second: Sequence[float]
) -> tuple[float, float, float, float] | None:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    return (left, top, right, bottom) if left < right and top < bottom else None


def _mapped_box(
    intersection: Sequence[float], bounds: Sequence[float], size: tuple[int, int]
) -> tuple[int, int, int, int]:
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    return (
        max(0, math.floor((intersection[0] - bounds[0]) / width * size[0])),
        max(0, math.floor((intersection[1] - bounds[1]) / height * size[1])),
        min(size[0], math.ceil((intersection[2] - bounds[0]) / width * size[0])),
        min(size[1], math.ceil((intersection[3] - bounds[1]) / height * size[1])),
    )


def _feather_mask(size: tuple[int, int]) -> Image.Image:
    radius = max(1, min(24, size[0] // 12, size[1] // 12))
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    right = max(radius, size[0] - radius - 1)
    bottom = max(radius, size[1] - radius - 1)
    draw.rectangle((radius, radius, right, bottom), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius=max(1, radius / 2)))


def composite_children(
    base: Image.Image,
    target_bounds: Sequence[float],
    children: Sequence[BuiltAsset],
) -> list[str]:
    used: list[str] = []
    for child in sorted(
        children,
        key=lambda asset: (
            int(asset.contract.get("native_zoom", -1)),
            asset.sheet["id"],
        ),
    ):
        if child.stage_path is None:
            continue
        if child.sha256 is None or sha256_file(child.stage_path) != child.sha256:
            raise Phase5BuildError(
                f"{child.sheet['id']} composite child SHA-256 is missing or stale"
            )
        child_bounds = child.sheet.get("bounds")
        if not isinstance(child_bounds, list):
            continue
        overlap = _intersection(target_bounds, child_bounds)
        if overlap is None:
            continue
        destination = _mapped_box(overlap, target_bounds, base.size)
        if destination[0] >= destination[2] or destination[1] >= destination[3]:
            continue
        with Image.open(child.stage_path) as opened:
            child_image = ImageOps.exif_transpose(opened).convert("RGB")
            source = _mapped_box(overlap, child_bounds, child_image.size)
            cropped = child_image.crop(source)
        try:
            destination_size = (
                destination[2] - destination[0],
                destination[3] - destination[1],
            )
            if (
                destination_size[0] > cropped.width
                or destination_size[1] > cropped.height
            ):
                raise Phase5BuildError(
                    f"{child.sheet['id']} would be upscaled during parent composition: "
                    f"source={cropped.size}, destination={destination_size}"
                )
            rendered = cropped.resize(
                destination_size,
                Image.Resampling.LANCZOS,
            )
        finally:
            cropped.close()
        mask = _feather_mask(rendered.size)
        try:
            base.paste(rendered, destination[:2], mask)
        finally:
            rendered.close()
            mask.close()
        used.append(child.sheet["id"])
    return used


def _canonical_parent_base_and_masks(
    *,
    sheet: dict[str, Any],
    contract: dict[str, Any],
    resolution_contract_path: Path,
    material_atlas_path: Path,
) -> tuple[Image.Image, dict[str, Any], dict[str, Image.Image]]:
    """Render a parent at its own native grid; no world/style raster is resized."""

    from render_phase5_reviewed_master import (  # imported lazily to avoid a cycle
        DEFAULT_SEED,
        load_sources as load_renderer_sources,
        render_observed_masks,
        render_reviewed_master,
    )

    raw_contract = _json_object(
        resolution_contract_path.resolve(), "parent resolution contract"
    )
    sources = load_renderer_sources(REPO_ROOT / "world" / "map-production" / "source")
    render_sheet = {
        **contract,
        "sheet_id": sheet["id"],
        "sheet_type": sheet["sheet_type"],
        "bounds": list(sheet["bounds"]),
        "source_feature_id": sheet.get("source_feature_id"),
    }
    base, stats = render_reviewed_master(
        sources,
        raw_contract,
        render_sheet,
        seed=DEFAULT_SEED,
        material_atlas_path=material_atlas_path.resolve(),
    )
    masks = render_observed_masks(
        sources,
        raw_contract,
        render_sheet,
        seed=DEFAULT_SEED,
    )
    return base, stats, masks


def _copy_image_as_png(source: Path, destination: Path) -> None:
    bound = _bound_artifact_for_path(source)
    if bound is not None:
        bound.copy_to(destination)
        return
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="PNG", compress_level=6, optimize=False)


def _build_imported_master_asset_bound(
    *,
    sheet: dict[str, Any],
    contract: dict[str, Any],
    source_entry: dict[str, Any],
    staging_root: Path,
    final_root: Path,
    catalog_by_id: dict[str, dict[str, Any]] | None = None,
    sources: dict[str, dict[str, Any]] | None = None,
    require_accepted: bool = False,
) -> BuiltAsset:
    sheet_id = sheet["id"]
    job_id = job_id_for_sheet(sheet_id)
    destination = staging_root / "masters" / f"{sheet_id}.png"
    final_manifest_path = repo_path(final_root / "masters" / f"{sheet_id}.png")
    source_path, source_digest = verify_hashed_file(
        source_entry, f"{sheet_id} master source"
    )
    expected_size = (contract["width"], contract["height"])
    actual_size = image_dimensions(source_path, f"{sheet_id} master source")
    if actual_size != expected_size:
        raise Phase5BuildError(
            f"{sheet_id} source dimensions must match the resolution contract exactly: "
            f"expected={expected_size[0]}x{expected_size[1]}, "
            f"actual={actual_size[0]}x{actual_size[1]}; blind upscale is forbidden"
        )
    evidence = accepted_evidence(
        source_entry,
        sheet=sheet,
        master_path=repo_path(source_path),
        job_id=job_id,
        contract=contract,
        catalog_by_id=catalog_by_id,
        sources=sources,
    )
    indexed_kind = source_entry.get("kind", "master")
    if (
        require_accepted or indexed_kind == CANONICAL_RENDER_SOURCE_KIND
    ) and evidence is None:
        raise Phase5BuildError(f"{sheet_id} reviewed source lacks acceptance evidence")
    _copy_image_as_png(source_path, destination)
    if evidence is not None:
        manifest_path = repo_path(source_path)
        digest = source_digest
    else:
        manifest_path = final_manifest_path
        digest = sha256_file(destination)
    source_kind = indexed_kind
    if source_kind == "composite_master":
        method = "verified-composite-master-import"
    elif source_kind == CANONICAL_RENDER_SOURCE_KIND:
        method = CANONICAL_RENDER_METHOD
    else:
        method = "verified-master-import" if evidence else "unreviewed-master-import"
    return BuiltAsset(
        sheet=sheet,
        contract=contract,
        job_id=job_id,
        method=method,
        stage_path=destination,
        final_manifest_path=manifest_path,
        sha256=digest,
        accepted_evidence=evidence,
        source_entry=source_entry,
        provenance={
            "kind": (
                "reviewed-composite-import"
                if source_kind == "composite_master"
                else (
                    CANONICAL_RENDER_METHOD
                    if source_kind == CANONICAL_RENDER_SOURCE_KIND
                    else "exact-master-import"
                )
            ),
            "source": {
                "path": repo_path(source_path),
                "sha256": source_digest,
            },
            "provenance_report": (
                evidence.provenance_path if evidence is not None else None
            ),
            "acceptance_evidence_hash_locked": evidence is not None,
        },
    )


def build_imported_master_asset(
    *,
    sheet: dict[str, Any],
    contract: dict[str, Any],
    source_entry: dict[str, Any],
    staging_root: Path,
    final_root: Path,
    catalog_by_id: dict[str, dict[str, Any]] | None = None,
    sources: dict[str, dict[str, Any]] | None = None,
    require_accepted: bool = False,
) -> BuiltAsset:
    """Build an imported master from the same bytes accepted by preflight."""

    registry = source_entry.get(INTERNAL_BOUND_ARTIFACTS_KEY)
    bindings = registry if isinstance(registry, dict) else None
    with bound_artifact_context(bindings):
        result = _build_imported_master_asset_bound(
            sheet=sheet,
            contract=contract,
            source_entry=source_entry,
            staging_root=staging_root,
            final_root=final_root,
            catalog_by_id=catalog_by_id,
            sources=sources,
            require_accepted=require_accepted,
        )
    return result


def build_generation_asset(
    *,
    sheet: dict[str, Any],
    contract: dict[str, Any],
    source_entry: dict[str, Any] | None,
    staging_root: Path,
    final_root: Path,
    control_master: Path,
    style_master: Path | None,
    allow_provisional: bool,
    minimum_ssim: float,
    catalog_by_id: dict[str, dict[str, Any]] | None = None,
    sources: dict[str, dict[str, Any]] | None = None,
) -> BuiltAsset:
    sheet_id = sheet["id"]
    job_id = job_id_for_sheet(sheet_id)
    destination = staging_root / "masters" / f"{sheet_id}.png"
    final_manifest_path = repo_path(final_root / "masters" / f"{sheet_id}.png")
    if source_entry is not None and source_entry.get("kind", "master") in {
        "master",
        CANONICAL_RENDER_SOURCE_KIND,
    }:
        source_kind = source_entry.get("kind", "master")
        return build_imported_master_asset(
            sheet=sheet,
            contract=contract,
            source_entry=source_entry,
            staging_root=staging_root,
            final_root=final_root,
            catalog_by_id=catalog_by_id,
            sources=sources,
            require_accepted=source_kind == CANONICAL_RENDER_SOURCE_KIND,
        )

    if source_entry is not None and source_entry.get("kind") == "metatiles":
        plan = metatile_plan(contract)
        if plan is None:
            raise Phase5BuildError(f"{sheet_id} does not have a metatile contract")
        assembly_report = stitch_metatiles(
            source_entry,
            plan,
            destination,
            minimum_ssim=minimum_ssim,
        )
        return BuiltAsset(
            sheet=sheet,
            contract=contract,
            job_id=job_id,
            method="guarded-metatile-assembly",
            stage_path=destination,
            final_manifest_path=final_manifest_path,
            sha256=sha256_file(destination),
            source_entry=source_entry,
            provenance={"kind": "guarded-metatile-assembly", **assembly_report},
        )

    if allow_provisional:
        seeded = provisional_seed(
            control_master,
            style_master,
            bounds=sheet["bounds"],
            target_size=(contract["width"], contract["height"]),
        )
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            seeded.save(destination, format="PNG", compress_level=6, optimize=False)
        finally:
            seeded.close()
        return BuiltAsset(
            sheet=sheet,
            contract=contract,
            job_id=job_id,
            method="provisional-style-seed",
            stage_path=destination,
            final_manifest_path=final_manifest_path,
            sha256=sha256_file(destination),
            provenance={
                "kind": "provisional-style-seed",
                "acceptance_inferred": False,
            },
            provisional=True,
        )

    return BuiltAsset(
        sheet=sheet,
        contract=contract,
        job_id=job_id,
        method="blocked-missing-high-resolution-source",
        stage_path=None,
        final_manifest_path=None,
        sha256=None,
    )


def build_composite_asset(
    *,
    sheet: dict[str, Any],
    contract: dict[str, Any],
    children: Sequence[BuiltAsset],
    staging_root: Path,
    final_root: Path,
    control_master: Path,
    style_master: Path | None,
    expected_child_ids: set[str] | None = None,
    resolution_contract_path: Path = DEFAULT_CONTRACT,
    material_atlas_path: Path = DEFAULT_PHASE5_MATERIAL_ATLAS,
) -> BuiltAsset:
    del control_master, style_master
    sheet_id = sheet["id"]
    destination = staging_root / "masters" / f"{sheet_id}.png"
    actual_child_ids = {child.sheet["id"] for child in children}
    if expected_child_ids is not None and actual_child_ids != expected_child_ids:
        raise Phase5BuildError(
            f"{sheet_id} composite child coverage mismatch: "
            f"missing={sorted(expected_child_ids - actual_child_ids)}, "
            f"extra={sorted(actual_child_ids - expected_child_ids)}"
        )
    incomplete = sorted(
        child.sheet["id"] for child in children if not child.materialized
    )
    if incomplete:
        raise Phase5BuildError(
            f"{sheet_id} cannot compose before all children are materialized: "
            + ", ".join(incomplete)
        )
    if not children:
        raise Phase5BuildError(f"{sheet_id} composite requires child masters")

    base, render_stats, observed_masks = _canonical_parent_base_and_masks(
        sheet=sheet,
        contract=contract,
        resolution_contract_path=resolution_contract_path,
        material_atlas_path=material_atlas_path,
    )
    qa_dir = staging_root / "qa" / "observed-masks"
    land_mask_path = qa_dir / f"{sheet_id}.land-sea.png"
    transport_mask_path = qa_dir / f"{sheet_id}.transport.png"
    try:
        used = composite_children(base, sheet["bounds"], children)
        destination.parent.mkdir(parents=True, exist_ok=True)
        base.save(destination, format="PNG", compress_level=6, optimize=False)
        qa_dir.mkdir(parents=True, exist_ok=True)
        observed_masks["land_sea"].save(
            land_mask_path, format="PNG", compress_level=9, optimize=False
        )
        observed_masks["transport"].save(
            transport_mask_path, format="PNG", compress_level=9, optimize=False
        )
    finally:
        base.close()
        for mask in observed_masks.values():
            mask.close()
    if set(used) != actual_child_ids:
        raise Phase5BuildError(
            f"{sheet_id} composition did not place every child: "
            f"missing={sorted(actual_child_ids - set(used))}"
        )
    used_set = set(used)
    child_provenance = [
        {
            "sheet_id": child.sheet["id"],
            "path": child.final_manifest_path,
            "sha256": child.sha256,
            "native_zoom": child.contract.get("native_zoom"),
        }
        for child in sorted(
            children,
            key=lambda item: (
                int(item.contract.get("native_zoom", -1)),
                item.sheet["id"],
            ),
        )
        if child.sheet["id"] in used_set
        and child.final_manifest_path is not None
        and child.sha256 is not None
    ]
    return BuiltAsset(
        sheet=sheet,
        contract=contract,
        job_id=job_id_for_sheet(sheet_id),
        method="deterministic-parent-composite",
        stage_path=destination,
        final_manifest_path=repo_path(final_root / "masters" / f"{sheet_id}.png"),
        sha256=sha256_file(destination),
        source_entry={"composite_children": used},
        provenance={
            "kind": "deterministic-parent-composite",
            "children": child_provenance,
            "canonical_native_base": {
                "renderer": {
                    "path": repo_path(CANONICAL_RENDERER_PATH),
                    "sha256": sha256_file(CANONICAL_RENDERER_PATH),
                },
                "resolution_contract": {
                    "path": repo_path(resolution_contract_path.resolve()),
                    "sha256": sha256_file(resolution_contract_path.resolve()),
                },
                "material_atlas": {
                    "path": repo_path(material_atlas_path.resolve()),
                    "sha256": sha256_file(material_atlas_path.resolve()),
                },
                "canon_sources": [
                    {"role": role, "path": repo_path(path), "sha256": sha256_file(path)}
                    for role, path in CANONICAL_GEOJSON_SOURCES.items()
                ],
                "render_stats_sha256": hashlib.sha256(
                    json.dumps(
                        render_stats,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "source_coordinates_modified": False,
                "world_crop_or_upscale_used": False,
            },
            "observed_masks": {
                "land_sea": {
                    "path": repo_path(
                        final_root
                        / "qa"
                        / "observed-masks"
                        / f"{sheet_id}.land-sea.png"
                    ),
                    "sha256": sha256_file(land_mask_path),
                },
                "transport": {
                    "path": repo_path(
                        final_root
                        / "qa"
                        / "observed-masks"
                        / f"{sheet_id}.transport.png"
                    ),
                    "sha256": sha256_file(transport_mask_path),
                },
            },
            "composition": {
                "child_order": used,
                "resampling": "LANCZOS-downsample-only",
                "upscaled_child_count": 0,
                "base_rendered_at_parent_native_resolution": True,
            },
            "acceptance_inferred": False,
        },
        # A deterministic composite is a new visual artifact and must receive
        # its own QA.  It is never accepted merely because children were.
        provisional=True,
    )


def _artifact(path: Path, role: str) -> dict[str, str]:
    return {"path": repo_path(path), "sha256": sha256_file(path), "role": role}


def _bound_input_artifact(spec: Any, label: str, role: str) -> dict[str, str]:
    """Build one job input record exclusively from its active byte binding."""

    path, _ = verify_hashed_file(spec, label)
    bound = _bound_artifact_for_path(path)
    if bound is None:
        raise Phase5BuildError(
            f"{label} is missing its immutable source-index byte binding"
        )
    return {**bound.artifact(), "role": role}


def _history(states: Sequence[str], note: str) -> list[dict[str, str]]:
    timestamp = utc_now()
    return [
        {"state": state, "at": timestamp, "actor": GENERATOR_ID, "note": note}
        for state in states
    ]


def _create_job_bound(
    asset: BuiltAsset,
    *,
    assets_by_sheet: dict[str, BuiltAsset],
    catalog_path: Path,
    contract_path: Path,
    control_master: Path,
    style_master: Path | None,
) -> dict[str, Any]:
    sheet = asset.sheet
    threshold = acceptance_threshold(sheet)
    parent_id = sheet.get("parent_id")
    inputs = [
        _artifact(catalog_path, "canonical-map-sheet-catalog"),
        _artifact(contract_path, "finite-resolution-contract"),
        _artifact(control_master, "canonical-world-generation-control"),
    ]
    if style_master is not None:
        inputs.append(
            _artifact(style_master, "visual-style-reference-not-acceptance-evidence")
        )
    if asset.source_entry is not None and asset.source_entry.get("kind") in {
        "master",
        "composite_master",
        CANONICAL_RENDER_SOURCE_KIND,
    }:
        inputs.append(
            _bound_input_artifact(
                asset.source_entry,
                f"{sheet['id']} manifest source",
                "sheet-raster-source",
            )
        )
        provenance_spec = asset.source_entry.get("provenance_report")
        if isinstance(provenance_spec, dict):
            inputs.append(
                _bound_input_artifact(
                    provenance_spec,
                    f"{sheet['id']} manifest provenance",
                    "hash-locked-master-provenance",
                )
            )
    elif (
        asset.source_entry is not None and asset.source_entry.get("kind") == "metatiles"
    ):
        for index, spec in enumerate(asset.source_entry.get("tiles", [])):
            inputs.append(
                _bound_input_artifact(
                    spec,
                    f"{sheet['id']} metatile input {index}",
                    "guarded-imagegen-metatile",
                )
            )
    elif asset.source_entry is not None and isinstance(
        asset.source_entry.get("composite_children"), list
    ):
        for child_id in asset.source_entry["composite_children"]:
            child = assets_by_sheet.get(child_id)
            if (
                child is not None
                and child.final_manifest_path is not None
                and child.sha256 is not None
            ):
                inputs.append(
                    {
                        "path": child.final_manifest_path,
                        "sha256": child.sha256,
                        "role": "child-sheet-master",
                    }
                )

    job: dict[str, Any] = {
        "id": asset.job_id,
        "sheet_id": sheet["id"],
        "status": "planned",
        "bounds": {
            "west": sheet["bounds"][0],
            "south": sheet["bounds"][1],
            "east": sheet["bounds"][2],
            "north": sheet["bounds"][3],
        },
        "zoom": {
            "min": sheet["zoom_range"][0],
            "max": sheet["zoom_range"][1],
            "native": sheet["native_zoom"],
        },
        "acceptance_threshold": threshold,
        "inputs": inputs,
        "history": _history(
            ["planned"],
            "Phase 5 bounded-sheet job scaffolded; no acceptance is inferred from generation.",
        ),
        "notes": (
            f"Build method={asset.method}. Acceptance requires complete QA at "
            f"{threshold}+ and {required_review_count(sheet)} independent review(s)."
        ),
    }
    if isinstance(parent_id, str) and parent_id in assets_by_sheet:
        job["parent_job_id"] = assets_by_sheet[parent_id].job_id
    if not asset.materialized:
        return job

    assert asset.final_manifest_path is not None and asset.sha256 is not None
    job["generation"] = {
        "model": GENERATOR_ID,
        "control_image_path": repo_path(control_master),
        "attempt": 1,
    }
    parent_asset = (
        assets_by_sheet.get(parent_id) if isinstance(parent_id, str) else None
    )
    if parent_asset is not None and parent_asset.final_manifest_path is not None:
        job["generation"]["parent_image_path"] = parent_asset.final_manifest_path
    job["master"] = {
        "path": asset.final_manifest_path,
        "sha256": asset.sha256,
        "width": asset.contract["width"],
        "height": asset.contract["height"],
        "color_profile": "sRGB",
    }
    job["status"] = "generated"
    job["history"] = _history(
        ["planned", "inputs-ready", "generated"],
        f"Materialized by {asset.method}; QA remains mandatory.",
    )
    if asset.accepted_evidence is not None:
        evidence = asset.accepted_evidence
        for index, review_path in enumerate(evidence.vision_paths):
            inputs.append(
                {
                    **_evidence_artifact(
                        review_path,
                        f"{sheet['id']} manifest Vision review {index + 1}",
                    ),
                    "role": INDEPENDENT_VISION_REVIEW_ROLES[index],
                }
            )
        job["qa"] = {
            "automated": {
                "status": "passed",
                "report_path": evidence.automated_path,
            },
            "vision": {
                "decision": "accepted",
                "score": evidence.primary_score,
                "report_path": evidence.vision_paths[0],
                "reviewer": evidence.primary_reviewer,
                "reviewed_at": utc_now(),
            },
        }
        job["status"] = "accepted"
        job["history"] = _history(
            [
                "planned",
                "inputs-ready",
                "generated",
                "automated-qa",
                "vision-qa",
                "accepted",
            ],
            "Imported only after hashes, exact dimensions, automated QA, Vision QA, and reviewer independence were verified.",
        )
        if asset.tiled_output is not None:
            job["output"] = asset.tiled_output
            job["status"] = "tiled"
            job["history"].append(
                {
                    "state": "tiled",
                    "at": utc_now(),
                    "actor": GENERATOR_ID,
                    "note": "Generated deterministic 512px WebP pyramid after acceptance.",
                }
            )
    return job


def create_job(
    asset: BuiltAsset,
    *,
    assets_by_sheet: dict[str, BuiltAsset],
    catalog_path: Path,
    contract_path: Path,
    control_master: Path,
    style_master: Path | None,
) -> dict[str, Any]:
    """Create a job while preserving source-index byte identity."""

    source_entry = asset.source_entry
    source_kind = source_entry.get("kind") if isinstance(source_entry, dict) else None
    if source_kind in {
        "master",
        "composite_master",
        CANONICAL_RENDER_SOURCE_KIND,
        "metatiles",
    }:
        registry = source_entry.get(INTERNAL_BOUND_ARTIFACTS_KEY)
        if (
            not isinstance(registry, dict)
            or not registry
            or any(
                not isinstance(identity, str)
                or not isinstance(bound, BoundArtifact)
                or identity != bound.identity
                for identity, bound in registry.items()
            )
        ):
            raise Phase5BuildError(
                f"{asset.sheet['id']} job inputs require immutable "
                "source-index byte bindings"
            )
        with bound_artifact_context(registry):
            return _create_job_bound(
                asset,
                assets_by_sheet=assets_by_sheet,
                catalog_path=catalog_path,
                contract_path=contract_path,
                control_master=control_master,
                style_master=style_master,
            )
    return _create_job_bound(
        asset,
        assets_by_sheet=assets_by_sheet,
        catalog_path=catalog_path,
        contract_path=contract_path,
        control_master=control_master,
        style_master=style_master,
    )


def write_qa_scaffolds(assets: Iterable[BuiltAsset], staging_root: Path) -> list[str]:
    written: list[str] = []
    qa_dir = staging_root / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        if not asset.materialized or asset.accepted:
            continue
        assert asset.final_manifest_path is not None
        count = required_review_count(asset.sheet)
        for review_number in range(1, count + 1):
            report = build_report(
                asset.job_id,
                asset.final_manifest_path,
                reviewer=f"Unassigned independent reviewer {review_number}",
                golden=False,
                threshold=acceptance_threshold(asset.sheet),
                image_sha256=asset.sha256,
                review_mode="blind-independent",
            )
            stem = qa_dir / f"{asset.job_id}-review{review_number}"
            dump_json(stem.with_suffix(".json"), report)
            stem.with_suffix(".md").write_text(
                markdown_report(report), encoding="utf-8"
            )
            written.extend(
                [
                    stem.with_suffix(".json").relative_to(staging_root).as_posix(),
                    stem.with_suffix(".md").relative_to(staging_root).as_posix(),
                ]
            )
    return written


def _public_manifest_path(sheet: dict[str, Any], release_id: str) -> PurePosixPath:
    release_root = PUBLIC_TILE_BASE / release_id
    if sheet.get("sheet_type") == "world":
        return release_root / "metadata.json"
    return release_root / "sheets" / sheet["id"] / "metadata.json"


def _public_manifest_url(sheet: dict[str, Any], release_id: str) -> str:
    manifest_path = _public_manifest_path(sheet, release_id)
    return posixpath.relpath(
        manifest_path.as_posix(), PUBLIC_INDEX_CANONICAL_PATH.parent.as_posix()
    )


def _release_timestamp(base_manifest: dict[str, Any]) -> str:
    value = base_manifest.get("updated_at")
    if isinstance(value, str) and value:
        return value
    # The timestamp is metadata, not an input clock.  Keeping the fallback
    # constant makes two builds from the same legacy manifest byte-identical.
    return "1970-01-01T00:00:00Z"


def _require_complete_tile_release(assets: Sequence[BuiltAsset]) -> None:
    expected_counts = {
        "world": 1,
        "continent": 5,
        "region": 14,
        "corridor": 1,
        "settlement": 2,
    }
    counts = {
        sheet_type: sum(asset.sheet.get("sheet_type") == sheet_type for asset in assets)
        for sheet_type in expected_counts
    }
    if len(assets) != 23 or counts != expected_counts:
        raise Phase5BuildError(
            "tile publication requires exactly all 23 bounded sheets "
            f"({expected_counts}), found {counts}"
        )
    incomplete = sorted(
        asset.sheet["id"]
        for asset in assets
        if not asset.accepted or not asset.materialized
    )
    if incomplete:
        raise Phase5BuildError(
            "tile publication is fail-closed until all 23 masters are QA-accepted: "
            + ", ".join(incomplete)
        )


def _evidence_artifact(path_value: str, label: str) -> dict[str, str]:
    path = resolve_repo_artifact(path_value, label)
    bound = _bound_artifact_for_path(path)
    if bound is None:
        raise Phase5BuildError(f"{label} is missing its immutable byte binding")
    return bound.artifact()


def _tile_index_evidence(asset: BuiltAsset) -> dict[str, Any]:
    evidence = asset.accepted_evidence
    if evidence is None:
        raise Phase5BuildError(f"{asset.sheet['id']} lacks accepted QA evidence")
    return {
        "provenance": _evidence_artifact(
            evidence.provenance_path, f"{asset.sheet['id']} publication provenance"
        ),
        "automated_qa": _evidence_artifact(
            evidence.automated_path, f"{asset.sheet['id']} publication automated QA"
        ),
        "vision_reviews": [
            _evidence_artifact(
                path, f"{asset.sheet['id']} publication Vision review {index}"
            )
            for index, path in enumerate(evidence.vision_paths, start=1)
        ],
    }


def _tile_index_entry(
    asset: BuiltAsset,
    *,
    staging_root: Path,
    release_id: str,
) -> dict[str, Any]:
    sheet = asset.sheet
    sheet_id = sheet["id"]
    relative_manifest = _public_manifest_path(sheet, release_id)
    metadata_path = staging_root / "public" / Path(*relative_manifest.parts)
    metadata = _json_object(metadata_path, f"{sheet_id} public tile manifest")
    golden_bonus = 50 if sheet.get("priority") == "golden_path" else 0
    priority = int(asset.contract["native_zoom"]) * 1000 + golden_bonus
    entry = {
        "id": sheet_id,
        "sheet_id": sheet_id,
        "name": sheet.get("name", sheet_id),
        "sheet_type": sheet["sheet_type"],
        "parent_id": sheet.get("parent_id"),
        "secondary_parent_ids": list(sheet.get("secondary_parent_ids", [])),
        "source_feature_id": sheet.get("source_feature_id"),
        "bounds": list(sheet["bounds"]),
        "zoom_range": list(asset.contract["zoom_range"]),
        "native_zoom": asset.contract["native_zoom"],
        # Phase 6 reads review_status; status records the later publication state.
        "review_status": "accepted",
        "status": "tiled",
        "manifest_url": _public_manifest_url(sheet, release_id),
        "priority": priority,
        "master_sha256": metadata["master"]["sha256"],
        "manifest_sha256": sha256_file(metadata_path),
        "tile_set_sha256": metadata["tile_set_sha256"],
        "tile_count": metadata["tile_count"],
        "evidence": _tile_index_evidence(asset),
    }
    return entry


def build_sheet_tile_index(
    assets: Sequence[BuiltAsset],
    staging_root: Path,
    *,
    release_id: str,
    generated_at: str,
) -> dict[str, Any]:
    """Build the Phase 6 schema-2 index without exposing a full master WebP.

    The world is represented by ``root`` because the browser loads it as the
    rollback-capable base release.  The runtime ``sheets`` collection contains
    its 22 descendants.  Together they cover all 23 bounded Phase 5 sheets.
    """

    _require_complete_tile_release(assets)
    entries = [
        _tile_index_entry(asset, staging_root=staging_root, release_id=release_id)
        for asset in assets
    ]
    roots = [entry for entry in entries if entry["sheet_type"] == "world"]
    if len(roots) != 1:
        raise Phase5BuildError("sheet tile index requires exactly one world root")
    root = roots[0]
    descendants = sorted(
        (entry for entry in entries if entry["sheet_type"] != "world"),
        key=lambda entry: (SHEET_TYPE_ORDER[entry["sheet_type"]], entry["sheet_id"]),
    )
    index = {
        "$schema": "https://sstory.example/schemas/sheet-tile-index.schema.json",
        "schema_version": "2.0.0",
        "type": "sstory-sheet-tile-index",
        "coordinate_reference_system": "EA-WORLD-1",
        "bounds_order": ["min_x", "min_y", "max_x", "max_y"],
        "generated_by": GENERATOR_ID,
        "generated_at": generated_at,
        "release_id": release_id,
        "bounded_sheet_count": 23,
        "root_id": root["sheet_id"],
        "root": root,
        "description": (
            "All 23 hash-verified, QA-accepted bounded sheets. The root is the "
            "rollback-capable world base; sheets contains its 22 tiled descendants."
        ),
        "sheets": descendants,
    }
    _validate_schema_instance(
        index, DEFAULT_SHEET_TILE_INDEX_SCHEMA, "sheet tile publication index"
    )
    public_root = staging_root / "public"
    canonical_path = public_root / Path(*PUBLIC_INDEX_CANONICAL_PATH.parts)
    compatibility_path = public_root / Path(*PUBLIC_INDEX_COMPATIBILITY_PATH.parts)
    dump_json(canonical_path, index)
    # Keep the existing HTML pointer working.  This is an exact schema-2 alias,
    # not the retired full-WebP region index.
    shutil.copyfile(canonical_path, compatibility_path)
    return index


def build_tiles_for_accepted(
    assets: Sequence[BuiltAsset],
    staging_root: Path,
    final_root: Path,
    *,
    webp_quality: int,
    release_id: str,
    generated_at: str,
) -> None:
    _require_complete_tile_release(assets)
    for asset in assets:
        assert asset.final_manifest_path is not None
        authoritative_master = resolve_repo_artifact(
            asset.final_manifest_path,
            f"{asset.sheet['id']} accepted master",
        )
        relative_manifest = _public_manifest_path(asset.sheet, release_id)
        output = staging_root / "public" / Path(*relative_manifest.parent.parts)
        metadata = generate_pyramid(
            authoritative_master,
            output,
            map_id=asset.sheet["id"],
            min_zoom=asset.contract["zoom_range"][0],
            max_zoom=asset.contract["native_zoom"],
            tile_size=512,
            quality=webp_quality,
            bounds=tuple(asset.sheet["bounds"]),
            coordinate_system="EA-WORLD-1",
            url_template="{z}/{x}/{y}.webp",
        )
        metadata["generated_at"] = generated_at
        metadata["release_id"] = release_id
        metadata.update(
            {
                "coordinate_scope": "sheet-local",
                "tile_origin": "top-left",
                "x_axis": "right",
                "y_axis": "down",
                "edge_padding": "transparent",
            }
        )
        dump_json(output / "metadata.json", metadata)
        final_tile_root = final_root / "public" / Path(*relative_manifest.parent.parts)
        asset.tiled_output = {
            "tiles_path": repo_path(final_tile_root),
            "metadata_path": repo_path(final_tile_root / "metadata.json"),
            "tile_set_sha256": metadata["tile_set_sha256"],
        }


def _resolve_public_url(index_path: PurePosixPath, value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise Phase5BuildError("public manifest URL must be a non-empty POSIX URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or parsed.path.startswith("/")
    ):
        raise Phase5BuildError("public manifest URL must be a relative static path")
    normalized = posixpath.normpath(
        posixpath.join(index_path.parent.as_posix(), parsed.path)
    )
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise Phase5BuildError("public manifest URL escapes the public root")
    return PurePosixPath(normalized)


def _tile_set_digest(tile_digests: Sequence[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for relative, tile_digest in sorted(tile_digests):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(tile_digest.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _sheet_local_tile_pixel_errors(
    tile: Image.Image,
    *,
    level_width: int,
    level_height: int,
    column: int,
    row: int,
    tile_size: int = 512,
    label: str,
) -> list[str]:
    """Return violations of the sheet-local XYZ content/padding contract."""

    content_width = min(tile_size, level_width - column * tile_size)
    content_height = min(tile_size, level_height - row * tile_size)
    if content_width <= 0 or content_height <= 0:
        return [f"{label} lies outside the declared sheet-local level extent"]

    errors: list[str] = []
    alpha = tile.convert("RGBA").getchannel("A")
    if alpha.crop((0, 0, content_width, content_height)).getbbox() is None:
        errors.append(f"{label} has no visible pixels inside its content rectangle")
    if content_width < tile_size:
        if alpha.crop((content_width, 0, tile_size, tile_size)).getbbox() is not None:
            errors.append(
                f"{label} right-edge padding must have RGBA alpha=0 from "
                f"x={content_width} through {tile_size - 1}"
            )
    if content_height < tile_size:
        if alpha.crop((0, content_height, tile_size, tile_size)).getbbox() is not None:
            errors.append(
                f"{label} bottom-edge padding must have RGBA alpha=0 from "
                f"y={content_height} through {tile_size - 1}"
            )
    return errors


def _bounds_contain(outer: Sequence[Any], inner: Sequence[Any]) -> bool:
    if len(outer) != 4 or len(inner) != 4:
        return False
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


def validate_public_tile_release(
    public_root: Path,
    *,
    release_id: str | None = None,
    verify_tiles: bool = True,
) -> dict[str, Any]:
    """Recompute the complete schema-2 publication boundary.

    This validator intentionally mirrors the fail-closed Phase 6 normalizers and
    adds filesystem, SHA-256, hierarchy, and exact-contract checks that cannot be
    expressed by JSON Schema alone.
    """

    public_root = public_root.resolve()
    errors: list[str] = []
    canonical_path = public_root / Path(*PUBLIC_INDEX_CANONICAL_PATH.parts)
    compatibility_path = public_root / Path(*PUBLIC_INDEX_COMPATIBILITY_PATH.parts)
    if not canonical_path.is_file():
        return {
            "valid": False,
            "release_id": release_id,
            "bounded_sheet_count": 0,
            "tile_count": 0,
            "tile_bytes": 0,
            "errors": [f"missing canonical sheet tile index: {canonical_path}"],
        }
    try:
        index = _json_object(canonical_path, "canonical sheet tile index")
    except (Phase5BuildError, ValidationFailure) as exc:
        return {
            "valid": False,
            "release_id": release_id,
            "bounded_sheet_count": 0,
            "tile_count": 0,
            "tile_bytes": 0,
            "errors": [str(exc)],
        }
    if not compatibility_path.is_file():
        errors.append(f"missing compatibility sheet tile index: {compatibility_path}")
    elif canonical_path.read_bytes() != compatibility_path.read_bytes():
        errors.append(
            "region-rasters.json must be an exact schema-2 compatibility alias"
        )
    try:
        index_schema = _json_object(
            DEFAULT_SHEET_TILE_INDEX_SCHEMA, "sheet tile index schema"
        )
        errors.extend(
            f"sheet tile index schema: {error}"
            for error in schema_errors(index, index_schema)
        )
    except (Phase5BuildError, ValidationFailure) as exc:
        errors.append(str(exc))

    actual_release_id = index.get("release_id")
    if release_id is not None and actual_release_id != release_id:
        errors.append(
            f"release_id mismatch: expected={release_id!r}, actual={actual_release_id!r}"
        )
    if not isinstance(actual_release_id, str) or not ID_PATTERN.fullmatch(
        actual_release_id
    ):
        errors.append(f"invalid release_id: {actual_release_id!r}")
        actual_release_id = release_id or "invalid-release"

    try:
        _, catalog_by_id, derived = load_contract(DEFAULT_CONTRACT, DEFAULT_MAP_SHEETS)
        contracts = derived["sheets"]
    except Phase5BuildError as exc:
        errors.append(str(exc))
        catalog_by_id = {}
        contracts = {}

    root_entry = index.get("root")
    descendants = index.get("sheets")
    entries = [root_entry] if isinstance(root_entry, dict) else []
    if isinstance(descendants, list):
        entries.extend(entry for entry in descendants if isinstance(entry, dict))
    else:
        errors.append("sheet tile index sheets must be an array")
    by_id = {
        entry.get("sheet_id"): entry
        for entry in entries
        if isinstance(entry.get("sheet_id"), str)
    }
    expected_ids = set(contracts)
    actual_ids = set(by_id)
    missing_ids = sorted(expected_ids - actual_ids)
    extra_ids = sorted(actual_ids - expected_ids)
    if missing_ids:
        errors.append(
            "sheet tile index misses bounded sheets: " + ", ".join(missing_ids)
        )
    if extra_ids:
        errors.append("sheet tile index has unknown sheets: " + ", ".join(extra_ids))
    if len(entries) != len(by_id):
        errors.append("sheet tile index contains duplicate or malformed sheet IDs")
    if index.get("root_id") != "sheet_world":
        errors.append("sheet tile index root_id must be sheet_world")
    if root_entry is not by_id.get("sheet_world"):
        errors.append("sheet tile index root must describe sheet_world")
    if any(entry.get("sheet_type") == "world" for entry in (descendants or [])):
        errors.append("runtime sheets must exclude the separately loaded world root")

    tile_count = 0
    tile_bytes = 0
    for sheet_id in sorted(expected_ids & actual_ids):
        entry = by_id[sheet_id]
        sheet = catalog_by_id[sheet_id]
        contract = contracts[sheet_id]
        for field, expected in (
            ("id", sheet_id),
            ("sheet_id", sheet_id),
            ("sheet_type", sheet["sheet_type"]),
            ("parent_id", sheet.get("parent_id")),
            ("bounds", sheet["bounds"]),
            ("zoom_range", contract["zoom_range"]),
            ("native_zoom", contract["native_zoom"]),
            ("review_status", "accepted"),
        ):
            if entry.get(field) != expected:
                errors.append(
                    f"{sheet_id}.{field} mismatch: expected={expected!r}, "
                    f"actual={entry.get(field)!r}"
                )
        expected_secondary = list(sheet.get("secondary_parent_ids", []))
        if entry.get("secondary_parent_ids") != expected_secondary:
            errors.append(f"{sheet_id}.secondary_parent_ids mismatch")
        if entry.get("status") not in {"tiled", "staging", "published"}:
            errors.append(f"{sheet_id}.status must be tiled or later")
        parent_id = sheet.get("parent_id")
        if parent_id is not None:
            parent = by_id.get(parent_id)
            if parent is None:
                errors.append(f"{sheet_id} lacks accepted parent {parent_id}")
            else:
                if not _bounds_contain(
                    parent.get("bounds", []), entry.get("bounds", [])
                ):
                    errors.append(f"{sheet_id} bounds escape parent {parent_id}")
                if entry.get("native_zoom", -1) <= parent.get("native_zoom", -1):
                    errors.append(
                        f"{sheet_id} native zoom is not deeper than {parent_id}"
                    )

        try:
            relative_manifest = _resolve_public_url(
                PUBLIC_INDEX_CANONICAL_PATH, entry.get("manifest_url")
            )
        except Phase5BuildError as exc:
            errors.append(f"{sheet_id}: {exc}")
            continue
        expected_manifest = _public_manifest_path(sheet, actual_release_id)
        if relative_manifest != expected_manifest:
            errors.append(
                f"{sheet_id}.manifest_url resolves to {relative_manifest}, "
                f"expected {expected_manifest}"
            )
        manifest_path = public_root / Path(*relative_manifest.parts)
        try:
            manifest_path.resolve().relative_to(public_root)
        except ValueError:
            errors.append(f"{sheet_id} manifest escapes the public root")
            continue
        if not manifest_path.is_file():
            errors.append(f"{sheet_id} tile manifest is missing: {relative_manifest}")
            continue
        manifest_sha = sha256_file(manifest_path)
        if entry.get("manifest_sha256") != manifest_sha:
            errors.append(f"{sheet_id}.manifest_sha256 mismatch")
        try:
            manifest = _json_object(manifest_path, f"{sheet_id} tile manifest")
            manifest_schema = _json_object(
                DEFAULT_TILE_MANIFEST_SCHEMA, "sheet tile manifest schema"
            )
            errors.extend(
                f"{sheet_id} tile manifest schema: {error}"
                for error in schema_errors(manifest, manifest_schema)
            )
        except (Phase5BuildError, ValidationFailure) as exc:
            errors.append(str(exc))
            continue

        for field, expected in (
            ("release_id", actual_release_id),
            ("generated_at", index.get("generated_at")),
            ("map_id", sheet_id),
            ("coordinate_reference_system", "EA-WORLD-1"),
            ("bounds", sheet["bounds"]),
            ("minzoom", contract["zoom_range"][0]),
            ("maxzoom", contract["native_zoom"]),
            ("native_zoom", contract["native_zoom"]),
            ("tile_size", 512),
            ("scheme", "xyz"),
            ("format", "webp"),
            ("tiles", ["{z}/{x}/{y}.webp"]),
            ("coordinate_scope", "sheet-local"),
            ("tile_origin", "top-left"),
            ("x_axis", "right"),
            ("y_axis", "down"),
            ("edge_padding", "transparent"),
        ):
            if manifest.get(field) != expected:
                errors.append(f"{sheet_id} manifest {field} mismatch")
        master = manifest.get("master", {})
        if (
            master.get("width") != contract["width"]
            or master.get("height") != contract["height"]
        ):
            errors.append(f"{sheet_id} manifest master dimensions mismatch")
        if entry.get("master_sha256") != master.get("sha256"):
            errors.append(f"{sheet_id}.master_sha256 mismatch")
        master_path_value = master.get("path")
        try:
            master_path = resolve_repo_artifact(
                master_path_value, f"{sheet_id} published master evidence"
            )
            if sha256_file(master_path) != master.get("sha256"):
                errors.append(f"{sheet_id} published master SHA-256 mismatch")
        except Phase5BuildError as exc:
            errors.append(str(exc))

        levels = (
            manifest.get("levels") if isinstance(manifest.get("levels"), list) else []
        )
        expected_tile_paths: list[str] = []
        expected_level_count = contract["native_zoom"] - contract["zoom_range"][0] + 1
        if len(levels) != expected_level_count:
            errors.append(f"{sheet_id} manifest levels do not cover the zoom range")
        by_zoom = {
            level.get("zoom"): level for level in levels if isinstance(level, dict)
        }
        for zoom in range(contract["zoom_range"][0], contract["native_zoom"] + 1):
            level = by_zoom.get(zoom)
            factor = 2 ** (contract["native_zoom"] - zoom)
            width = max(1, math.ceil(contract["width"] / factor))
            height = max(1, math.ceil(contract["height"] / factor))
            columns = math.ceil(width / 512)
            rows = math.ceil(height / 512)
            expected_level = {
                "zoom": zoom,
                "width": width,
                "height": height,
                "columns": columns,
                "rows": rows,
                "tile_count": columns * rows,
            }
            if level != expected_level:
                errors.append(f"{sheet_id} level z{zoom} dimensions/count mismatch")
            expected_tile_paths.extend(
                f"{zoom}/{column}/{row}.webp"
                for column in range(columns)
                for row in range(rows)
            )
        if manifest.get("tile_count") != len(expected_tile_paths):
            errors.append(f"{sheet_id} manifest tile_count mismatch")
        if entry.get("tile_count") != len(expected_tile_paths):
            errors.append(f"{sheet_id} index tile_count mismatch")
        if entry.get("tile_set_sha256") != manifest.get("tile_set_sha256"):
            errors.append(f"{sheet_id} index/manifest tile_set_sha256 mismatch")
        if not verify_tiles:
            tile_count += len(expected_tile_paths)
        else:
            tile_digests: list[tuple[str, str]] = []
            for relative in expected_tile_paths:
                tile_path = manifest_path.parent / Path(*PurePosixPath(relative).parts)
                if not tile_path.is_file():
                    errors.append(f"{sheet_id} missing tile {relative}")
                    continue
                try:
                    with Image.open(tile_path) as tile:
                        if tile.format != "WEBP" or tile.size != (512, 512):
                            errors.append(
                                f"{sheet_id} tile {relative} must be 512px WebP"
                            )
                        else:
                            zoom_text, column_text, filename = PurePosixPath(
                                relative
                            ).parts
                            level = by_zoom.get(int(zoom_text))
                            if isinstance(level, dict):
                                errors.extend(
                                    _sheet_local_tile_pixel_errors(
                                        tile,
                                        level_width=level["width"],
                                        level_height=level["height"],
                                        column=int(column_text),
                                        row=int(PurePosixPath(filename).stem),
                                        label=f"{sheet_id} tile {relative}",
                                    )
                                )
                except OSError as exc:
                    errors.append(f"{sheet_id} unreadable tile {relative}: {exc}")
                    continue
                tile_digests.append((relative, sha256_file(tile_path)))
                tile_count += 1
                tile_bytes += tile_path.stat().st_size
            tile_roots = [
                child
                for child in manifest_path.parent.iterdir()
                if child.is_dir() and child.name.isdigit()
            ]
            actual_webps = {
                path.relative_to(manifest_path.parent).as_posix()
                for tile_root in tile_roots
                for path in tile_root.rglob("*.webp")
            }
            actual_webps.update(
                path.name for path in manifest_path.parent.glob("*.webp")
            )
            extras = sorted(actual_webps - set(expected_tile_paths))
            if extras:
                errors.append(f"{sheet_id} has unexpected tiles: {', '.join(extras)}")
            tile_set_sha = _tile_set_digest(tile_digests)
            if tile_set_sha != manifest.get("tile_set_sha256"):
                errors.append(f"{sheet_id} manifest tile_set_sha256 mismatch")
            if tile_set_sha != entry.get("tile_set_sha256"):
                errors.append(f"{sheet_id} index tile_set_sha256 mismatch")

        evidence = entry.get("evidence")
        if isinstance(evidence, dict):
            evidence_specs = [evidence.get("provenance"), evidence.get("automated_qa")]
            reviews = evidence.get("vision_reviews")
            if isinstance(reviews, list):
                evidence_specs.extend(reviews)
            for position, spec in enumerate(evidence_specs):
                try:
                    verify_hashed_file(
                        spec, f"{sheet_id} publication evidence {position}"
                    )
                except Phase5BuildError as exc:
                    errors.append(str(exc))

    return {
        "valid": not errors,
        "release_id": actual_release_id,
        "bounded_sheet_count": len(entries),
        "tile_count": tile_count,
        "tile_bytes": tile_bytes,
        "index_path": canonical_path.as_posix(),
        "errors": errors,
    }


def _manifest(
    base_manifest: dict[str, Any],
    jobs: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    existing = base_manifest.get("jobs")
    if not isinstance(existing, list):
        raise Phase5BuildError("base manifest jobs must be an array")
    existing_ids = {item.get("id") for item in existing if isinstance(item, dict)}
    duplicate = sorted(job["id"] for job in jobs if job["id"] in existing_ids)
    if duplicate:
        raise Phase5BuildError(
            "base manifest already contains Phase 5 job id(s): " + ", ".join(duplicate)
        )
    result = dict(base_manifest)
    result["updated_at"] = utc_now()
    result["jobs"] = [*existing, *jobs]
    return result


def plan_actions(
    catalog_by_id: dict[str, dict[str, Any]],
    contracts: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    *,
    allow_provisional: bool,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for sheet_id, contract in contracts.items():
        sheet = catalog_by_id[sheet_id]
        source = sources.get(sheet_id)
        if sheet["sheet_type"] in COMPOSITE_TYPES:
            action = (
                "verified-composite-master-import"
                if source is not None and source.get("kind") == "composite_master"
                else "deterministic-parent-composite"
            )
        elif source is not None:
            if source.get("kind") == "metatiles":
                action = "guarded-metatile-assembly"
            elif source.get("kind") == CANONICAL_RENDER_SOURCE_KIND:
                action = "verified-canonical-render-master-import"
            else:
                action = "verified-master-import"
        elif allow_provisional:
            action = "provisional-style-seed"
        else:
            action = "blocked-missing-high-resolution-source"
        actions.append(
            {
                "sheet_id": sheet_id,
                "sheet_type": sheet["sheet_type"],
                "action": action,
                "bounds": sheet["bounds"],
                "master_size": [contract["width"], contract["height"]],
                "zoom_range": contract["zoom_range"],
                "native_zoom": contract["native_zoom"],
                "acceptance_threshold": acceptance_threshold(sheet),
                "independent_reviews_required": required_review_count(sheet),
                "metatiles": contract.get("metatiles"),
            }
        )
    return actions


def _preflight_output_root(path: Path) -> Path:
    final_root = path.resolve()
    try:
        final_root.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise Phase5BuildError("output root must stay inside the repository") from exc
    if final_root.exists():
        raise Phase5BuildError(
            f"refusing to overwrite existing output root: {final_root}; choose a new versioned path"
        )
    try:
        require_trackable_path(
            final_root,
            label="Phase 5 output root",
            must_exist=False,
            require_file=False,
        )
    except ReleasePathError as exc:
        raise Phase5BuildError(str(exc)) from exc
    return final_root


def _prepare_output_root(path: Path) -> tuple[Path, Path, Path, tuple[int, int]]:
    final_root = _preflight_output_root(path)
    final_root.parent.mkdir(parents=True, exist_ok=True)
    lock_path = final_root.with_name(f".{final_root.name}.phase5-build.lock")
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise Phase5BuildError(
                f"another Phase 5 build owns the output lock: {lock_path}"
            ) from exc
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.close(descriptor)
        descriptor = None
        lock_identity = _directory_identity(lock_path)
        # Recheck after taking the cooperative lock; installation itself also
        # uses an atomic no-replace rename against non-cooperating writers.
        _preflight_output_root(final_root)
        staging_root = Path(
            tempfile.mkdtemp(
                prefix=f".{final_root.name}.building-", dir=final_root.parent
            )
        )
        return final_root, staging_root, lock_path, lock_identity
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        lock_path.unlink(missing_ok=True)
        raise


def _directory_identity(path: Path) -> tuple[int, int]:
    metadata = os.stat(path, follow_symlinks=False)
    return metadata.st_dev, metadata.st_ino


def _install_staged_output(staging_root: Path, final_root: Path) -> tuple[int, int]:
    prepared_identity = _directory_identity(staging_root)
    try:
        _rename_directory_no_replace(staging_root, final_root)
    except (FileExistsError, RendererPromotionError) as exc:
        raise Phase5BuildError(
            "output root appeared during atomic no-clobber installation"
        ) from exc
    return prepared_identity


def _rollback_installed_output(
    final_root: Path,
    staging_root: Path,
    prepared_identity: tuple[int, int],
) -> None:
    if not os.path.lexists(final_root):
        return
    if _directory_identity(final_root) != prepared_identity:
        raise Phase5BuildError(
            "installed output identity changed; refusing destructive rollback"
        )
    _rename_directory_no_replace(final_root, staging_root)


def materialize_target_stage_assets(
    *,
    stage_contract: TargetStageContract,
    contracts: dict[str, dict[str, Any]],
    catalog_by_id: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    staging_root: Path,
    final_root: Path,
    control_master: Path,
    style_master: Path | None,
    minimum_ssim: float,
    resolution_contract_path: Path,
) -> dict[str, BuiltAsset]:
    """Materialize only the sheets authorized by ``stage_contract``."""

    output_ids = set(stage_contract.output_sheet_ids)
    generated_ids = set(stage_contract.generated_composite_sheet_ids)
    assets_by_sheet: dict[str, BuiltAsset] = {}

    # Every direct sheet is an accepted canonical-render import at all three
    # stages.  target_stage_contract has already rejected missing or legacy
    # source kinds, so this path can never fall back to provisional generation.
    for sheet_id, contract in contracts.items():
        sheet = catalog_by_id[sheet_id]
        if sheet_id not in output_ids or sheet["sheet_type"] not in GENERATION_TYPES:
            continue
        source_entry = sources.get(sheet_id)
        if source_entry is None:
            raise Phase5BuildError(
                f"{stage_contract.target_stage} lacks imported direct source {sheet_id}"
            )
        assets_by_sheet[sheet_id] = build_generation_asset(
            sheet=sheet,
            contract=contract,
            source_entry=source_entry,
            staging_root=staging_root,
            final_root=final_root,
            control_master=control_master,
            style_master=style_master,
            allow_provisional=False,
            minimum_ssim=minimum_ssim,
            catalog_by_id=catalog_by_id,
            sources=sources,
        )

    # idx22 creates continents only; idx23 imports those continents and creates
    # world only; final imports every composite and creates none.
    actually_generated: list[str] = []
    for sheet_type in ("continent", "world"):
        for sheet_id, contract in contracts.items():
            sheet = catalog_by_id[sheet_id]
            if sheet_id not in output_ids or sheet["sheet_type"] != sheet_type:
                continue
            source_entry = sources.get(sheet_id)
            if source_entry is not None:
                if sheet_id in generated_ids:
                    raise Phase5BuildError(
                        f"{stage_contract.target_stage} must generate {sheet_id}, "
                        "not import it"
                    )
                assets_by_sheet[sheet_id] = build_imported_master_asset(
                    sheet=sheet,
                    contract=contract,
                    source_entry=source_entry,
                    staging_root=staging_root,
                    final_root=final_root,
                    catalog_by_id=catalog_by_id,
                    sources=sources,
                    require_accepted=True,
                )
                continue
            if sheet_id not in generated_ids:
                raise Phase5BuildError(
                    f"{stage_contract.target_stage} may not generate composite {sheet_id}"
                )
            expected_child_ids = _expected_composite_children(sheet, catalog_by_id)
            children = [
                assets_by_sheet[child_id]
                for child_id in expected_child_ids
                if child_id in assets_by_sheet
            ]
            assets_by_sheet[sheet_id] = build_composite_asset(
                sheet=sheet,
                contract=contract,
                children=children,
                staging_root=staging_root,
                final_root=final_root,
                control_master=control_master,
                style_master=style_master,
                expected_child_ids=expected_child_ids,
                resolution_contract_path=resolution_contract_path,
            )
            actually_generated.append(sheet_id)

    if set(assets_by_sheet) != output_ids:
        raise Phase5BuildError(
            f"{stage_contract.target_stage} materialized wrong sheet coverage: "
            f"missing={sorted(output_ids - set(assets_by_sheet))}, "
            f"extra={sorted(set(assets_by_sheet) - output_ids)}"
        )
    if tuple(actually_generated) != stage_contract.generated_composite_sheet_ids:
        raise Phase5BuildError(
            f"{stage_contract.target_stage} generated composite order mismatch: "
            f"expected={list(stage_contract.generated_composite_sheet_ids)}, "
            f"actual={actually_generated}"
        )
    return assets_by_sheet


def _expected_stage_inventory_paths(
    stage_contract: TargetStageContract,
    catalog_by_id: dict[str, dict[str, Any]],
) -> tuple[set[str], set[str], set[str]]:
    masters = {
        f"masters/{sheet_id}.png" for sheet_id in stage_contract.output_sheet_ids
    }
    masks = {
        f"qa/observed-masks/{sheet_id}.{mask_name}.png"
        for sheet_id in stage_contract.generated_composite_sheet_ids
        for mask_name in ("land-sea", "transport")
    }
    scaffolds: set[str] = set()
    for sheet_id in stage_contract.generated_composite_sheet_ids:
        for review_number in range(
            1, required_review_count(catalog_by_id[sheet_id]) + 1
        ):
            stem = f"qa/{job_id_for_sheet(sheet_id)}-review{review_number}"
            scaffolds.update({f"{stem}.json", f"{stem}.md"})
    return masters, masks, scaffolds


def _assert_stage_inventory(
    *,
    staging_root: Path,
    stage_contract: TargetStageContract,
    catalog_by_id: dict[str, dict[str, Any]],
    qa_scaffolds: Sequence[str],
) -> None:
    expected_masters, expected_masks, expected_scaffolds = (
        _expected_stage_inventory_paths(stage_contract, catalog_by_id)
    )
    actual_masters = {
        path.relative_to(staging_root).as_posix()
        for path in (staging_root / "masters").rglob("*")
        if path.is_file()
    }
    observed_root = staging_root / "qa" / "observed-masks"
    actual_masks = (
        {
            path.relative_to(staging_root).as_posix()
            for path in observed_root.rglob("*")
            if path.is_file()
        }
        if observed_root.exists()
        else set()
    )
    qa_root = staging_root / "qa"
    actual_scaffolds = (
        {
            path.relative_to(staging_root).as_posix()
            for path in qa_root.iterdir()
            if path.is_file()
        }
        if qa_root.exists()
        else set()
    )
    mismatches = []
    for label, actual, expected in (
        ("master", actual_masters, expected_masters),
        ("observed-mask", actual_masks, expected_masks),
        ("QA scaffold", actual_scaffolds, expected_scaffolds),
        ("reported QA scaffold", set(qa_scaffolds), expected_scaffolds),
    ):
        if actual != expected:
            mismatches.append(
                f"{label}: missing={sorted(expected - actual)}, "
                f"extra={sorted(actual - expected)}"
            )
    if mismatches:
        raise Phase5BuildError(
            f"{stage_contract.target_stage} staged filesystem inventory mismatch: "
            + "; ".join(mismatches)
        )


def execute_build(args: argparse.Namespace) -> dict[str, Any]:
    catalog_path = args.catalog.resolve()
    contract_path = args.contract.resolve()
    base_manifest_path = args.base_manifest.resolve()
    control_master = args.control_master.resolve()
    style_master = args.style_master.resolve() if args.style_master else None
    # Reject an existing or out-of-repository destination before inspecting
    # any build input.  This read-only check is repeated under a lock before
    # staging creation.
    if not args.dry_run:
        _preflight_output_root(args.output_root)
    if style_master is not None and not style_master.is_file():
        raise Phase5BuildError(f"style master does not exist: {style_master}")
    if not ID_PATTERN.fullmatch(args.release_id):
        raise Phase5BuildError(
            f"release_id must use lowercase kebab/snake case: {args.release_id!r}"
        )
    try:
        base_manifest_binding = bind_file(
            base_manifest_path, label="base production manifest", trackable=True
        )
        base_manifest = base_manifest_binding.json_object()
    except BoundArtifactError as exc:
        raise Phase5BuildError(str(exc)) from exc
    release_timestamp = _release_timestamp(base_manifest)
    control_sha = verify_control_master(control_master)
    catalog, catalog_by_id, derived = load_contract(contract_path, catalog_path)
    contracts = derived["sheets"]
    sources, source_index_sha, golden_style = load_source_index(
        args.source_index.resolve() if args.source_index else None,
        set(contracts),
    )
    requested_target_stage = getattr(args, "target_stage", None)
    stage_contract = (
        target_stage_contract(
            target_stage=requested_target_stage,
            catalog_by_id=catalog_by_id,
            contracts=contracts,
            sources=sources,
            tiles_requested=bool(args.tiles),
            allow_provisional=bool(args.allow_provisional_style_seed),
        )
        if requested_target_stage is not None
        else None
    )
    if not args.dry_run and stage_contract is None:
        raise Phase5BuildError("build requires --target-stage")
    source_registry = {
        bound.identity: bound for bound in source_index_bound_artifacts(sources)
    }
    # The manifest is an exact aggregate snapshot.  Rejected historical jobs
    # are not release dependencies; when a source index names a Golden, bind
    # only that selected job and its complete transitive evidence below.
    base_registry = {base_manifest_binding.identity: base_manifest_binding}
    for identity, bound in base_registry.items():
        existing = source_registry.get(identity)
        if existing is not None and existing.sha256 != bound.sha256:
            raise Phase5BuildError(
                f"conflicting source/base binding for {bound.relative}"
            )
        source_registry[identity] = bound
    if golden_style is not None:
        with bound_artifact_context(source_registry):
            golden_registry = bind_manifest_golden_evidence(
                golden_style, base_manifest_binding
            )
        for identity, bound in golden_registry.items():
            existing = source_registry.get(identity)
            if existing is not None and existing.sha256 != bound.sha256:
                raise Phase5BuildError(
                    f"conflicting Golden/base binding for {bound.relative}"
                )
            source_registry[identity] = bound
    with bound_artifact_context(source_registry):
        golden_evidence = (
            verify_manifest_golden_style(golden_style, base_manifest_path)
            if golden_style is not None
            else None
        )
        canonical_sources = [
            entry
            for entry in sources.values()
            if entry.get("kind") == CANONICAL_RENDER_SOURCE_KIND
        ]
        if canonical_sources:
            if golden_evidence is None:
                raise Phase5BuildError(
                    "canonical_render_master requires checked Golden manifest evidence"
                )
            canonical_context = canonical_render_context(
                catalog_path=catalog_path,
                contract_path=contract_path,
                control_index_path=args.canonical_control_index.resolve(),
                golden_evidence=golden_evidence,
            )
            for entry in canonical_sources:
                entry[INTERNAL_CANONICAL_CONTEXT_KEY] = canonical_context
    for sheet_id, entry in sources.items():
        sheet_type = catalog_by_id[sheet_id]["sheet_type"]
        kind = entry.get("kind", "master")
        if kind == CANONICAL_RENDER_SOURCE_KIND and sheet_type not in GENERATION_TYPES:
            raise Phase5BuildError(
                f"{sheet_id} canonical_render_master is allowed only for "
                "region, corridor, or settlement sheets"
            )
        if sheet_type in COMPOSITE_TYPES and kind != "composite_master":
            raise Phase5BuildError(
                f"{sheet_id} may be supplied only as a reviewed composite_master"
            )
        if sheet_type in GENERATION_TYPES and kind == "composite_master":
            raise Phase5BuildError(
                f"{sheet_id} is an ImageGen-resolution sheet and cannot use composite_master"
            )
        preflight_source_entry(
            entry,
            sheet=catalog_by_id[sheet_id],
            contract=contracts[sheet_id],
            catalog_by_id=catalog_by_id,
            sources=sources,
        )
    actions = plan_actions(
        catalog_by_id,
        contracts,
        sources,
        allow_provisional=args.allow_provisional_style_seed,
    )
    if stage_contract is not None:
        allowed_action_ids = set(stage_contract.output_sheet_ids)
        actions = [
            action for action in actions if action["sheet_id"] in allowed_action_ids
        ]
    plan_result = {
        "valid": True,
        "dry_run": bool(args.dry_run),
        "bounded_sheet_count": len(actions),
        "generation_metatile_count": derived["result"]["generation_metatile_count"],
        "actions": actions,
        "blocked_sheet_ids": [
            action["sheet_id"]
            for action in actions
            if action["action"].startswith("blocked-")
        ],
    }
    if stage_contract is not None:
        plan_result.update(
            {
                "target_stage": stage_contract.target_stage,
                "generated_composite_sheet_ids": list(
                    stage_contract.generated_composite_sheet_ids
                ),
                "deferred_sheet_ids": list(stage_contract.deferred_sheet_ids),
            }
        )
    if golden_evidence is not None:
        plan_result["golden_style_job_id"] = golden_evidence["job_id"]
    if args.dry_run:
        _assert_bound_registry_unchanged(source_registry)
        return plan_result

    (
        final_root,
        staging_root,
        output_lock_path,
        output_lock_identity,
    ) = _prepare_output_root(args.output_root)
    prepared_identity_key = _directory_identity(staging_root)
    installed = False
    build_binding_token = _BOUND_ARTIFACT_CONTEXT.set(source_registry)
    try:
        plans = [
            plan
            for contract in contracts.values()
            if (plan := metatile_plan(contract)) is not None
        ]
        dump_json(
            staging_root / "metatile-plan.json",
            {
                "schema_version": "1.0.0",
                "generated_by": GENERATOR_ID,
                "coordinate_reference_system": "EA-WORLD-1",
                "metatile_count": sum(plan["count"] for plan in plans),
                "sheets": plans,
            },
        )

        assert stage_contract is not None
        assets_by_sheet = materialize_target_stage_assets(
            stage_contract=stage_contract,
            contracts=contracts,
            catalog_by_id=catalog_by_id,
            sources=sources,
            staging_root=staging_root,
            final_root=final_root,
            control_master=control_master,
            style_master=style_master,
            minimum_ssim=args.minimum_overlap_ssim,
            resolution_contract_path=contract_path,
        )
        ordered_assets = [
            assets_by_sheet[sheet_id] for sheet_id in stage_contract.output_sheet_ids
        ]
        sheet_tile_index: dict[str, Any] | None = None
        staged_publication_validation: dict[str, Any] | None = None
        if args.tiles:
            build_tiles_for_accepted(
                ordered_assets,
                staging_root,
                final_root,
                webp_quality=args.webp_quality,
                release_id=args.release_id,
                generated_at=release_timestamp,
            )
            sheet_tile_index = build_sheet_tile_index(
                ordered_assets,
                staging_root,
                release_id=args.release_id,
                generated_at=release_timestamp,
            )
            staged_publication_validation = validate_public_tile_release(
                staging_root / "public", release_id=args.release_id
            )
            if not staged_publication_validation["valid"]:
                raise Phase5BuildError(
                    "staged public tile release failed validation: "
                    + "; ".join(staged_publication_validation["errors"])
                )
            if (
                staged_publication_validation["tile_count"]
                != EXPECTED_PHASE5_TILE_COUNT
            ):
                raise Phase5BuildError(
                    "final public tile release must contain exactly "
                    f"{EXPECTED_PHASE5_TILE_COUNT} tiles, found "
                    f"{staged_publication_validation['tile_count']}"
                )

        jobs = [
            create_job(
                asset,
                assets_by_sheet=assets_by_sheet,
                catalog_path=catalog_path,
                contract_path=contract_path,
                control_master=control_master,
                style_master=style_master,
            )
            for asset in ordered_assets
        ]
        manifest = _manifest(base_manifest, jobs)
        manifest_path = staging_root / "production-manifest.phase5.json"
        dump_json(manifest_path, manifest)
        qa_files = write_qa_scaffolds(ordered_assets, staging_root)
        _assert_stage_inventory(
            staging_root=staging_root,
            stage_contract=stage_contract,
            catalog_by_id=catalog_by_id,
            qa_scaffolds=qa_files,
        )

        artifact_records: list[dict[str, Any]] = []
        for asset in ordered_assets:
            if asset.stage_path is None:
                continue
            record = {
                "sheet_id": asset.sheet["id"],
                "path": asset.stage_path.relative_to(staging_root).as_posix(),
                "manifest_path": asset.final_manifest_path,
                "sha256": sha256_file(asset.stage_path),
                "width": asset.contract["width"],
                "height": asset.contract["height"],
                "method": asset.method,
                "accepted": asset.accepted,
                "provisional": asset.provisional,
            }
            if asset.provenance is not None:
                record["provenance"] = asset.provenance
            artifact_records.append(record)
        report = {
            "schema_version": BUILD_REPORT_SCHEMA_VERSION,
            "generated_by": GENERATOR_ID,
            "generated_at": utc_now(),
            "coordinate_reference_system": "EA-WORLD-1",
            "target_stage": stage_contract.target_stage,
            "generated_composite_sheet_ids": list(
                stage_contract.generated_composite_sheet_ids
            ),
            "deferred_sheet_ids": list(stage_contract.deferred_sheet_ids),
            "inputs": {
                "builder_script": {
                    "path": repo_path(BUILDER_SCRIPT_PATH),
                    "sha256": sha256_file(BUILDER_SCRIPT_PATH),
                },
                "catalog": {
                    "path": repo_path(catalog_path),
                    "sha256": sha256_file(catalog_path),
                },
                "resolution_contract": {
                    "path": repo_path(contract_path),
                    "sha256": sha256_file(contract_path),
                },
                "base_manifest": {
                    "path": repo_path(base_manifest_path),
                    "sha256": sha256_file(base_manifest_path),
                },
                "control_master": {
                    "path": repo_path(control_master),
                    "sha256": control_sha,
                },
                "canonical_control_index": (
                    {
                        "path": repo_path(args.canonical_control_index.resolve()),
                        "sha256": sha256_file(args.canonical_control_index.resolve()),
                    }
                    if canonical_sources
                    else None
                ),
                "style_master": (
                    {
                        "path": repo_path(style_master),
                        "sha256": sha256_file(style_master),
                    }
                    if style_master is not None
                    else None
                ),
                "source_index": (
                    {
                        "path": repo_path(args.source_index.resolve()),
                        "sha256": source_index_sha,
                    }
                    if args.source_index is not None
                    else None
                ),
            },
            "bounded_sheet_count": len(ordered_assets),
            "materialized_master_count": sum(
                asset.materialized for asset in ordered_assets
            ),
            "accepted_master_count": sum(asset.accepted for asset in ordered_assets),
            "provisional_master_count": sum(
                asset.provisional for asset in ordered_assets
            ),
            "planned_only_count": sum(
                not asset.materialized for asset in ordered_assets
            ),
            "generation_metatile_count": derived["result"]["generation_metatile_count"],
            "tiles_requested": bool(args.tiles),
            "public_tile_release": (
                {
                    "release_id": args.release_id,
                    "bounded_sheet_count": sheet_tile_index["bounded_sheet_count"],
                    "runtime_sheet_count": len(sheet_tile_index["sheets"]),
                    "tile_count": staged_publication_validation["tile_count"],
                    "tile_bytes": staged_publication_validation["tile_bytes"],
                    "canonical_index": (
                        staging_root
                        / "public"
                        / Path(*PUBLIC_INDEX_CANONICAL_PATH.parts)
                    )
                    .relative_to(staging_root)
                    .as_posix(),
                    "compatibility_index": (
                        staging_root
                        / "public"
                        / Path(*PUBLIC_INDEX_COMPATIBILITY_PATH.parts)
                    )
                    .relative_to(staging_root)
                    .as_posix(),
                }
                if sheet_tile_index is not None
                else None
            ),
            # Retained as a report key for old tooling; these are tiled sheets,
            # never full-master WebP overlays.
            "region_raster_count": (
                len(sheet_tile_index["sheets"]) if sheet_tile_index is not None else 0
            ),
            "qa_scaffolds": qa_files,
            "artifacts": artifact_records,
            "fail_closed": {
                "blind_upscale_never_accepted": True,
                "composites_require_new_qa": True,
                "target_stage_coverage_locked": True,
                "future_composites_not_materialized": True,
                "public_index_acceptance_only": True,
                "tiles_acceptance_only": True,
                "all_23_required_before_runtime_index": True,
                "full_master_webp_index_retired": True,
            },
        }
        dump_json(staging_root / "build-report.json", report)
        dump_json(
            staging_root / ".phase5-build-owned.json",
            {"generated_by": GENERATOR_ID, "build_report": "build-report.json"},
        )
        _assert_bound_registry_unchanged(source_registry)
        prepared_identity_key = _install_staged_output(staging_root, final_root)
        installed = True
        # Re-run normal manifest validation after installation so every
        # generated path is checked at its final repository location.
        _, manifest_errors = validate_manifest(
            final_root / "production-manifest.phase5.json",
            check_files=True,
        )
        if manifest_errors:
            raise Phase5BuildError(
                "built manifest failed validation: " + "; ".join(manifest_errors)
            )
        installed_validation = validate_build_root(final_root)
        if not installed_validation["valid"]:
            raise Phase5BuildError(
                "installed Phase 5 build failed validation: "
                + "; ".join(installed_validation["errors"])
            )
        _assert_bound_registry_unchanged(source_registry)
        return {
            **plan_result,
            "dry_run": False,
            "output_root": repo_path(final_root),
            "build_report": repo_path(final_root / "build-report.json"),
            "manifest": repo_path(final_root / "production-manifest.phase5.json"),
            "sheet_tile_index": (
                repo_path(
                    final_root / "public" / Path(*PUBLIC_INDEX_CANONICAL_PATH.parts)
                )
                if sheet_tile_index is not None
                else None
            ),
            "region_rasters": (
                repo_path(
                    final_root / "public" / Path(*PUBLIC_INDEX_COMPATIBILITY_PATH.parts)
                )
                if sheet_tile_index is not None
                else None
            ),
            "materialized_master_count": report["materialized_master_count"],
            "accepted_master_count": report["accepted_master_count"],
            "provisional_master_count": report["provisional_master_count"],
        }
    except BaseException as original_error:
        if installed and os.path.lexists(final_root):
            try:
                _rollback_installed_output(
                    final_root, staging_root, prepared_identity_key
                )
                installed = False
            except BaseException as rollback_error:
                raise Phase5BuildError(
                    "Phase 5 build failed and automatic rollback could not restore "
                    f"an absent destination; recovery paths: {final_root}, "
                    f"{staging_root}: {rollback_error}"
                ) from original_error
        if staging_root.exists():
            try:
                shutil.rmtree(staging_root)
            except BaseException as cleanup_error:
                raise Phase5BuildError(
                    "Phase 5 build rollback left staging debris at "
                    f"{staging_root}: {cleanup_error}"
                ) from original_error
        raise
    finally:
        _BOUND_ARTIFACT_CONTEXT.reset(build_binding_token)
        try:
            if (
                os.path.lexists(output_lock_path)
                and _directory_identity(output_lock_path) == output_lock_identity
            ):
                output_lock_path.unlink()
        except OSError:
            # The build result is already committed or rolled back.  A lock
            # cleanup failure must not misreport that transactional outcome.
            pass


def _build_report_stage_errors(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != BUILD_REPORT_SCHEMA_VERSION:
        errors.append(
            f"build report schema_version must be {BUILD_REPORT_SCHEMA_VERSION!r}"
        )
    if report.get("generated_by") != GENERATOR_ID:
        errors.append("build report generated_by is not the current Phase 5 builder")
    if report.get("coordinate_reference_system") != "EA-WORLD-1":
        errors.append("build report coordinate_reference_system must be 'EA-WORLD-1'")
    inputs = report.get("inputs")
    expected_builder = {
        "path": repo_path(BUILDER_SCRIPT_PATH),
        "sha256": sha256_file(BUILDER_SCRIPT_PATH),
    }
    if not isinstance(inputs, dict) or inputs.get("builder_script") != expected_builder:
        errors.append("build report must hash-lock the exact builder script")
    target_stage = report.get("target_stage")
    if target_stage not in TARGET_STAGES:
        return [
            *errors,
            "build report target_stage must be one of " + ", ".join(TARGET_STAGES),
        ]
    try:
        _, catalog_by_id, derived = load_contract(DEFAULT_CONTRACT, DEFAULT_MAP_SHEETS)
    except Phase5BuildError as exc:
        return [f"cannot validate target-stage coverage: {exc}"]
    contracts = derived["sheets"]
    ordered_ids = tuple(contracts)
    direct_ids = tuple(
        sheet_id
        for sheet_id in ordered_ids
        if catalog_by_id[sheet_id].get("sheet_type") in GENERATION_TYPES
    )
    continent_ids = tuple(
        sheet_id
        for sheet_id in ordered_ids
        if catalog_by_id[sheet_id].get("sheet_type") == "continent"
    )
    world_ids = tuple(
        sheet_id
        for sheet_id in ordered_ids
        if catalog_by_id[sheet_id].get("sheet_type") == "world"
    )
    if target_stage == "idx22":
        expected_output = tuple(
            sheet_id
            for sheet_id in ordered_ids
            if sheet_id in set(direct_ids) | set(continent_ids)
        )
        expected_generated = continent_ids
        expected_deferred = world_ids
        expected_tiles = False
    elif target_stage == "idx23":
        expected_output = ordered_ids
        expected_generated = world_ids
        expected_deferred = ()
        expected_tiles = False
    else:
        expected_output = ordered_ids
        expected_generated = ()
        expected_deferred = ()
        expected_tiles = True

    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("build report artifacts must be an array")
        artifacts = []
    actual_ids = [
        item.get("sheet_id") if isinstance(item, dict) else None for item in artifacts
    ]
    if actual_ids != list(expected_output):
        errors.append(
            f"{target_stage} artifact coverage/order mismatch: "
            f"expected={list(expected_output)}, actual={actual_ids}"
        )
    if report.get("bounded_sheet_count") != len(expected_output):
        errors.append(
            f"{target_stage} bounded_sheet_count must be {len(expected_output)}"
        )
    if report.get("generated_composite_sheet_ids") != list(expected_generated):
        errors.append(
            f"{target_stage} generated_composite_sheet_ids must be "
            f"{list(expected_generated)}"
        )
    if report.get("deferred_sheet_ids") != list(expected_deferred):
        errors.append(
            f"{target_stage} deferred_sheet_ids must be {list(expected_deferred)}"
        )
    if bool(report.get("tiles_requested")) is not expected_tiles:
        errors.append(
            f"{target_stage} tiles_requested must be {str(expected_tiles).lower()}"
        )
    by_id = {item.get("sheet_id"): item for item in artifacts if isinstance(item, dict)}
    generated_set = set(expected_generated)
    for sheet_id in expected_output:
        sheet_type = catalog_by_id[sheet_id].get("sheet_type")
        expected_method = (
            CANONICAL_RENDER_METHOD
            if sheet_type in GENERATION_TYPES
            else (
                "deterministic-parent-composite"
                if sheet_id in generated_set
                else "verified-composite-master-import"
            )
        )
        record = by_id.get(sheet_id, {})
        if record.get("method") != expected_method:
            errors.append(
                f"{target_stage} artifact {sheet_id} method must be {expected_method}"
            )
        expected_accepted = sheet_id not in generated_set
        if record.get("accepted") is not expected_accepted:
            errors.append(
                f"{target_stage} artifact {sheet_id} accepted must be "
                f"{str(expected_accepted).lower()}"
            )
        expected_provisional = sheet_id in generated_set
        if record.get("provisional") is not expected_provisional:
            errors.append(
                f"{target_stage} artifact {sheet_id} provisional must be "
                f"{str(expected_provisional).lower()}"
            )
    expected_accepted_count = len(expected_output) - len(expected_generated)
    for key, expected_value in (
        ("materialized_master_count", len(expected_output)),
        ("accepted_master_count", expected_accepted_count),
        ("provisional_master_count", len(expected_generated)),
        ("planned_only_count", 0),
    ):
        if report.get(key) != expected_value:
            errors.append(f"{target_stage} {key} must be {expected_value}")
    return errors


def _installed_stage_inventory_errors(root: Path, report: dict[str, Any]) -> list[str]:
    target_stage = report.get("target_stage")
    if target_stage not in TARGET_STAGES:
        return []
    try:
        _, catalog_by_id, _ = load_contract(DEFAULT_CONTRACT, DEFAULT_MAP_SHEETS)
    except Phase5BuildError as exc:
        return [f"cannot validate installed stage inventory: {exc}"]
    artifacts = report.get("artifacts")
    generated = report.get("generated_composite_sheet_ids")
    deferred = report.get("deferred_sheet_ids")
    if (
        not isinstance(artifacts, list)
        or not isinstance(generated, list)
        or not isinstance(deferred, list)
    ):
        return []
    output_ids = tuple(
        item.get("sheet_id")
        for item in artifacts
        if isinstance(item, dict) and isinstance(item.get("sheet_id"), str)
    )
    if len(output_ids) != len(artifacts):
        return []
    contract = TargetStageContract(
        target_stage=target_stage,
        source_sheet_ids=(),
        output_sheet_ids=output_ids,
        generated_composite_sheet_ids=tuple(generated),
        deferred_sheet_ids=tuple(deferred),
    )
    expected_masters, expected_masks, expected_scaffolds = (
        _expected_stage_inventory_paths(contract, catalog_by_id)
    )
    masters_root = root / "masters"
    qa_root = root / "qa"
    actual_masters = (
        {
            path.relative_to(root).as_posix()
            for path in masters_root.rglob("*")
            if path.is_file()
        }
        if masters_root.exists()
        else set()
    )
    actual_qa = (
        {
            path.relative_to(root).as_posix()
            for path in qa_root.rglob("*")
            if path.is_file()
        }
        if qa_root.exists()
        else set()
    )
    expected_qa = expected_masks | expected_scaffolds
    errors: list[str] = []
    if actual_masters != expected_masters:
        errors.append(
            "installed master inventory mismatch: "
            f"missing={sorted(expected_masters - actual_masters)}, "
            f"extra={sorted(actual_masters - expected_masters)}"
        )
    if actual_qa != expected_qa:
        errors.append(
            "installed QA inventory mismatch: "
            f"missing={sorted(expected_qa - actual_qa)}, "
            f"extra={sorted(actual_qa - expected_qa)}"
        )
    if set(report.get("qa_scaffolds", [])) != expected_scaffolds:
        errors.append("build report qa_scaffolds does not match target stage")
    return errors


def validate_build_root(root: Path) -> dict[str, Any]:
    root = root.resolve()
    marker_path = root / ".phase5-build-owned.json"
    if not marker_path.is_file():
        raise Phase5BuildError(f"build root is not owned by this pipeline: {root}")
    marker = _json_object(marker_path, "build marker")
    if marker.get("generated_by") != GENERATOR_ID:
        raise Phase5BuildError(
            f"unexpected build owner: {marker.get('generated_by')!r}"
        )
    report = _json_object(root / "build-report.json", "build report")
    errors = _build_report_stage_errors(report)
    errors.extend(_installed_stage_inventory_errors(root, report))
    for record in report.get("artifacts", []):
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            errors.append("build report contains an invalid artifact record")
            continue
        path = root.joinpath(*PurePosixPath(record["path"]).parts)
        if not path.is_file():
            errors.append(f"missing artifact: {record['path']}")
            continue
        actual_hash = sha256_file(path)
        if actual_hash != record.get("sha256"):
            errors.append(
                f"artifact hash mismatch: {record['path']} report={record.get('sha256')}, actual={actual_hash}"
            )
        actual_size = image_dimensions(path, record["path"])
        expected_size = (record.get("width"), record.get("height"))
        if actual_size != expected_size:
            errors.append(
                f"artifact dimensions mismatch: {record['path']} report={expected_size}, actual={actual_size}"
            )
    _, manifest_errors = validate_manifest(
        root / "production-manifest.phase5.json",
        check_files=True,
    )
    errors.extend(manifest_errors)
    public_release = report.get("public_tile_release")
    publication: dict[str, Any] | None = None
    if report.get("tiles_requested"):
        if not isinstance(public_release, dict):
            errors.append("tiled build lacks public_tile_release metadata")
        else:
            publication = validate_public_tile_release(
                root / "public", release_id=public_release.get("release_id")
            )
            errors.extend(publication["errors"])
            if publication.get("tile_count") != EXPECTED_PHASE5_TILE_COUNT:
                errors.append(
                    "final public tile release must contain exactly "
                    f"{EXPECTED_PHASE5_TILE_COUNT} tiles"
                )
    elif public_release is not None:
        errors.append("non-tiled build must not claim a public_tile_release")
    for relative in (PUBLIC_INDEX_CANONICAL_PATH, PUBLIC_INDEX_COMPATIBILITY_PATH):
        path = root / "public" / Path(*relative.parts)
        if not report.get("tiles_requested") and path.exists():
            errors.append(f"non-tiled build exposes a runtime index: {relative}")
    return {
        "valid": not errors,
        "root": repo_path(root),
        "artifacts_checked": len(report.get("artifacts", [])),
        "manifest_jobs": len(
            _json_object(root / "production-manifest.phase5.json", "manifest").get(
                "jobs", []
            )
        ),
        "region_rasters": (
            publication["bounded_sheet_count"] - 1 if publication is not None else 0
        ),
        "public_tile_release": publication,
        "errors": errors,
    }


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--catalog", type=Path, default=DEFAULT_MAP_SHEETS)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--base-manifest", type=Path, default=DEFAULT_BASE_MANIFEST)
    parser.add_argument("--control-master", type=Path, default=DEFAULT_CONTROL_MASTER)
    parser.add_argument(
        "--canonical-control-index",
        type=Path,
        default=DEFAULT_CANONICAL_CONTROL_INDEX,
        help=("hash-locked Phase 5 control index required by canonical_render_master"),
    )
    parser.add_argument("--style-master", type=Path)
    parser.add_argument("--source-index", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--release-id",
        default=DEFAULT_PUBLIC_RELEASE_ID,
        help=(f"immutable public tile version (default: {DEFAULT_PUBLIC_RELEASE_ID})"),
    )
    parser.add_argument(
        "--allow-provisional-style-seed",
        action="store_true",
        help=(
            "materialize missing sheets from control/style references for review only; "
            "these outputs remain generated and can never enter accepted indexes"
        ),
    )
    parser.add_argument("--minimum-overlap-ssim", type=float, default=0.90)
    parser.add_argument("--webp-quality", type=int, default=88)
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=argparse.SUPPRESS,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser(
        "plan", help="validate inputs and print a no-write plan"
    )
    add_common_arguments(plan)
    plan.add_argument(
        "--target-stage",
        choices=TARGET_STAGES,
        help="optionally preflight exact idx22, idx23, or final coverage",
    )
    plan.add_argument(
        "--tiles",
        action="store_true",
        help="required with --target-stage final; no files are written by plan",
    )
    plan.set_defaults(dry_run=True)
    build = subparsers.add_parser(
        "build", help="materialize a new versioned build root"
    )
    add_common_arguments(build)
    build.add_argument(
        "--target-stage",
        choices=TARGET_STAGES,
        required=True,
        help=(
            "required fail-closed transition: idx22 generates only continents, "
            "idx23 only world, final only tiles accepted idx23 inputs"
        ),
    )
    build.add_argument("--dry-run", action="store_true")
    build.add_argument(
        "--tiles",
        action="store_true",
        help=(
            "generate the all-23 schema-2 public tile release; fails until every "
            "bounded master has hash-verified QA acceptance"
        ),
    )
    validate = subparsers.add_parser(
        "validate", help="recompute hashes and manifest checks"
    )
    validate.add_argument("root", type=Path)
    validate.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=argparse.SUPPRESS,
    )
    provenance = subparsers.add_parser(
        "canonical-provenance",
        help="promote one accepted-Golden renderer report into canonical provenance",
    )
    provenance.add_argument("--renderer-report", type=Path, required=True)
    provenance.add_argument("--output", type=Path, required=True)
    provenance.add_argument("--base-manifest", type=Path, default=DEFAULT_BASE_MANIFEST)
    provenance.add_argument("--catalog", type=Path, default=DEFAULT_MAP_SHEETS)
    provenance.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    provenance.add_argument(
        "--canonical-control-index",
        type=Path,
        default=DEFAULT_CANONICAL_CONTROL_INDEX,
    )
    provenance.add_argument("--created-at")
    provenance.add_argument("--force", action="store_true")
    provenance.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=argparse.SUPPRESS,
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            result = validate_build_root(args.root)
        elif args.command == "canonical-provenance":
            document = write_canonical_render_provenance(
                renderer_report_path=args.renderer_report,
                output_path=args.output,
                base_manifest_path=args.base_manifest,
                catalog_path=args.catalog,
                contract_path=args.contract,
                control_index_path=args.canonical_control_index,
                created_at=args.created_at,
                force=args.force,
            )
            result = {
                "valid": True,
                "sheet_id": document["sheet_id"],
                "output": repo_path(args.output.resolve()),
                "sha256": sha256_file(args.output.resolve()),
            }
        else:
            if not MINIMUM_ALLOWED_OVERLAP_SSIM <= args.minimum_overlap_ssim <= 1.0:
                parser.error(
                    "--minimum-overlap-ssim must be between "
                    f"{MINIMUM_ALLOWED_OVERLAP_SSIM} and 1"
                )
            if not 1 <= args.webp_quality <= 100:
                parser.error("--webp-quality must be between 1 and 100")
            result = execute_build(args)
    except (OSError, ValueError, Phase5BuildError) as exc:
        result = {"valid": False, "error": str(exc)}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result.get("valid"):
        if args.command == "validate":
            print(
                f"Phase 5 build validation passed: {result['root']} "
                f"({result['artifacts_checked']} masters, "
                f"{result['region_rasters']} lazy sheet tile sets)"
            )
        elif args.command == "canonical-provenance":
            print(
                "Phase 5 canonical provenance created: "
                f"{result['output']} sha256={result['sha256']}"
            )
        elif result.get("dry_run"):
            print(
                f"Phase 5 dry-run passed: {result['bounded_sheet_count']} bounded sheets, "
                f"{result['generation_metatile_count']} ImageGen metatiles"
            )
            if result["blocked_sheet_ids"]:
                print(
                    "  Blocked without high-resolution sources: "
                    + ", ".join(result["blocked_sheet_ids"])
                )
        else:
            print(f"Phase 5 build created: {result['output_root']}")
            print(
                f"  Masters={result['materialized_master_count']}, "
                f"accepted={result['accepted_master_count']}, "
                f"provisional={result['provisional_master_count']}"
            )
            print(f"  Manifest: {result['manifest']}")
            if result["sheet_tile_index"]:
                print(f"  Sheet tile index: {result['sheet_tile_index']}")
            else:
                print("  Sheet tile index: not emitted (build was not --tiles)")
    else:
        print(
            f"Phase 5 pipeline failed: {result.get('error') or result.get('errors')}",
            file=sys.stderr,
        )
    return 0 if result.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
