#!/usr/bin/env python3
"""Two-phase, fail-closed promotion for the exact TEMP-only K3 v20 proof.

``prepare`` persists normalized, automated-only evidence and advances the job
only through ``automated-qa``. ``accept`` requires exactly two byte-bound blind
independent reviews before recording ``vision-qa`` and ``accepted``.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from PIL import Image

import audit_style_candidate_k3_semantic_cleanup as k3_audit
from production_common import REPO_ROOT, load_json, utc_now
from release_bound_artifact import (
    BoundArtifact,
    BoundArtifactError,
    assert_bindings_unchanged,
    bind_file,
)
from release_path_safety import ReleasePathError, require_trackable_path
from reviewer_identity import (
    INDEPENDENT_VISION_REVIEW_ROLES,
    canonical_reviewer_identity,
)
from validate_manifest import schema_errors, validate_manifest


JOB_ID = "style-candidate-k-v3-semantic-cleanup"
SHEET_ID = "style-candidate-k"
EXACT_V20_RECEIPT_ID = f"{JOB_ID}-temporary-proof-v20"
EXACT_V20_STATUS = "passed-automated-pending-root-vision"
REJECTED_V18_SHA256 = (
    "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882"
)
KNOWN_NON_GOLDEN_SOURCE_SHA256 = {
    REJECTED_V18_SHA256: "rejected v18/current candidate",
    "67b9ffeca574ca144e8c54fc67b7f5c2757a02422b1fab73135efb89ad8cc156": (
        "v45 calm-spacing source"
    ),
    "98aa5a14d7b1c2ba413e604403057ec05d0787cfd35d3c9dd770e88b850488aa": (
        "v47 generated-layout source"
    ),
    "c7fcd3da5fba6fe08f10fd1e0fe16bdb2884a0a04386de828f923d660de8f1a2": (
        "v38 copperplate-material source"
    ),
    "b4fc951af5d29c78bb98b5ee5007395b5fc3c1addc7070d76ac8074545259837": (
        "H4 palette-parchment source"
    ),
    "2ae715fc2800a03adde89a26bd3d663f1bafe179ed845cef09dd616ed1453d3f": (
        "v55 generated topographic-contour source"
    ),
    "c168f1419d04ffaff313433064bab2b12844041e3845540c8bb6e29c2ef317c4": (
        "v52 eight-ridge control-atlas guide"
    ),
}
ACCEPTANCE_THRESHOLD = 94
EXPECTED_SIZE = (1536, 1024)
V20_STEM = "style-candidate-k-v3-semantic-cleanup-proof-v20"
EXACT_V19_RECEIPT_ID = "style-candidate-k-v3-sparse-ridgeline-v19-provenance"
EXACT_V19_STATUS = "passed-deterministic-reconstruction"
V19_REPLAY_INTERFACE = "sstory-k3-sparse-ridgeline-v19-replay-v2"
REQUIRED_V19_AUTHORITY_ROLES = frozenset(
    {
        "canonical-k3-spec",
        "v55-root-vision-review",
        "v55-robust-recipe-verification",
        "v52-control-atlas",
        "v55-copperplate-material-reference",
        "v55-palette-parchment-reference",
    }
)
V55_ROBUST_RECIPE_AUTHORITY_SHA256 = (
    # Keep the recipe/preflight digest isolated so future review evidence
    # updates cannot accidentally drift the other five frozen authorities.
    "64de26a0b9ee59e3a6e100297802a201d3a14db9fff022c097d6e881015a6fd3"
)
EXPECTED_V19_AUTHORITY_ARTIFACTS = {
    "canonical-k3-spec": {
        "path": "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/spec.json",
        "sha256": "ffc9c365b93d9738b8d3f0fe4985b907afc61137931715db24e16161ae609232",
    },
    "v55-root-vision-review": {
        "path": "world/map-production/qa/style-candidate-k-v3-highland-source-v55-root-vision.json",
        "sha256": "626ea739be2aa63a55d73f31064ef697301db4244a6102834b7886930e76cd90",
    },
    "v55-robust-recipe-verification": {
        "path": "world/map-production/qa/automated/style-candidate-k-v3-sparse-ridgeline-v19-preflight.json",
        "sha256": V55_ROBUST_RECIPE_AUTHORITY_SHA256,
    },
    "v52-control-atlas": {
        "path": "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/k3-v52-eight-ridge-control-atlas.png",
        "sha256": "c168f1419d04ffaff313433064bab2b12844041e3845540c8bb6e29c2ef317c4",
    },
    "v55-copperplate-material-reference": {
        "path": "world/map-production/style-assets/highland-detail-exemplar-v1.png",
        "sha256": "c7fcd3da5fba6fe08f10fd1e0fe16bdb2884a0a04386de828f923d660de8f1a2",
    },
    "v55-palette-parchment-reference": {
        "path": "world/map-production/candidates/style-candidate-h-v4-plan-view-golden-board.png",
        "sha256": "b4fc951af5d29c78bb98b5ee5007395b5fc3c1addc7070d76ac8074545259837",
    },
}
EXPECTED_V19_FIXED_SOURCE_SHA256 = {
    "reconstruction_builder": (
        "226cb468a0ea27cbac67afe3c48296d0f01445fcc0a4f48ca2384e811c161423"
    ),
    "generated_layout_control": (
        "2ae715fc2800a03adde89a26bd3d663f1bafe179ed845cef09dd616ed1453d3f"
    ),
    "control_atlas_metadata": (
        "f9a1eab4a8e417bcd688ceae8db1e8f01dc21835842e69339dda70f461eab768"
    ),
    "canonical_body_control": (
        "7527b0be4d7a042c5fd33e499b96806bcbbd6a1b614086c7c0fbdf308b83666b"
    ),
    "imagegen_prompt": (
        "6a4dc3cc69ff4b6a2f03edd76a1408c839ad32a6497726aff7c4057e81a5ac43"
    ),
    "generation_receipt": (
        "05b9c19008daf348e17850322f3052ff023652c2709e53127e9f64500478dc09"
    ),
}
EXACT_SOURCE_PATHS = {
    "builder": "scripts/map-production/build_style_candidate_k3_field_margin_cleanup_v20.py",
    "k3_builder": "scripts/map-production/build_style_candidate_k3_semantic_cleanup.py",
    "k3_audit": "scripts/map-production/audit_style_candidate_k3_semantic_cleanup.py",
}
EXACT_FIELDS_DONOR = {
    "path": "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/fields-quiet-v2.png",
    "sha256": "c8554ec066caecee9f3fd428c5c1c6ca3c784c568a1547f717883440cb83196f",
    "prompt_path": "world/map-production/prompts/style-candidate-k-v3-fields-quiet-donor-v2.generation.txt",
    "prompt_sha256": "f90c21450fba17cfc7b8e31372da95e2062c924a774a80e19fb9d96c00840334",
}

REQUIRED_V20_GATES = frozenset(
    {
        "expected_actual_change_pixels",
        "change_subset_of_exact_permission",
        "donor_canvas_subset_of_legacy_field_permissions",
        "strict_interiors_byte_exact",
        "exact_boundary_core_byte_exact",
        "road_guard_12px_byte_exact",
        "corridor_byte_exact",
        "capital_byte_exact",
        "protected_features_byte_exact",
        "all_nonfield_pixels_byte_exact",
        "baseline_cadence_contract",
        "no_immediate_boundary_rows",
        "dominant_spacing_share",
        "closed_loops_per_parcel",
        "closed_loops_total",
        "small_comma_components_total",
        "field_rows_absent",
        "continuous_furrows_absent",
        "strict_field_raster_gate",
        "corridor_exact_k2_gate",
        "low_frequency_blotch_gate",
        "four_pixel_lattice_gate",
        "donor_median_rgb_delta",
        "candidate_median_rgb_delta",
    }
)
REQUIRED_V20_ARTIFACTS = frozenset(
    {
        "candidate",
        "permission",
        "alpha",
        "actual_change",
        "contact:full_25",
        "contact:full_50",
        "contact:fields_west_200",
        "contact:fields_west_400",
        "contact:fields_east_200",
        "contact:fields_east_400",
        "contact:fields_south_200",
        "contact:fields_south_400",
    }
)


class K3GoldenPromotionError(RuntimeError):
    """Raised before any manifest can claim an invalid promotion."""


@dataclass(frozen=True)
class PromotionPaths:
    manifest: Path
    raw: Path
    final: Path
    receipt: Path
    audit: Path
    v19_parent: Path
    v18_lineage: Path
    masks_dir: Path
    evidence_dir: Path
    v19_receipt: Path | None = None
    lineage_dir: Path | None = None


@dataclass(frozen=True)
class PromotionSourceContract:
    """Exact source namespace and stable v19 reconstruction authorities."""

    v20_root: Path
    v19_candidate: Path
    v19_receipt: Path
    v19_builder: Path
    generated_layout_control: Path
    control_atlas_metadata: Path
    canonical_body_control: Path
    imagegen_prompt: Path
    generation_receipt: Path
    test_only_allow_dynamic_temp_root: bool = False
    test_only_expected_authorities: tuple[tuple[str, Path, str], ...] | None = None


@dataclass(frozen=True)
class V19Lineage:
    candidate: BoundArtifact
    receipt: BoundArtifact
    base_v18: BoundArtifact
    builder: BoundArtifact
    layout_control: BoundArtifact
    control_atlas_metadata: BoundArtifact
    canonical_body_control: BoundArtifact
    imagegen_prompt: BoundArtifact
    generation_receipt: BoundArtifact
    authorities: tuple[tuple[str, BoundArtifact], ...]

    def bindings(self) -> tuple[BoundArtifact, ...]:
        return (
            self.candidate,
            self.receipt,
            self.base_v18,
            self.builder,
            self.layout_control,
            self.control_atlas_metadata,
            self.canonical_body_control,
            self.imagegen_prompt,
            self.generation_receipt,
            *(binding for _, binding in self.authorities),
        )


DEFAULT_PATHS = PromotionPaths(
    manifest=REPO_ROOT / "world/map-production/production-manifest.json",
    raw=REPO_ROOT
    / "world/map-production/candidates/style-candidate-k-v3-semantic-cleanup-raw.png",
    final=REPO_ROOT
    / "world/map-production/candidates/style-candidate-k-v3-semantic-cleanup.png",
    receipt=REPO_ROOT
    / "world/map-production/prompts/style-candidate-k-v3-semantic-cleanup.provenance-receipt.json",
    audit=REPO_ROOT
    / "world/map-production/qa/automated/style-candidate-k-v3-semantic-cleanup.json",
    v19_parent=REPO_ROOT
    / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/highland-parent-v19.png",
    v18_lineage=REPO_ROOT
    / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/rejected-lineage-v18.png",
    masks_dir=REPO_ROOT / "world/map-production/qa/masks",
    evidence_dir=REPO_ROOT
    / "world/map-production/qa/evidence/style-candidate-k-v3-semantic-cleanup",
    v19_receipt=REPO_ROOT
    / "world/map-production/prompts/style-candidate-k-v3-sparse-ridgeline-v19.normalized-provenance.json",
    lineage_dir=REPO_ROOT
    / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/lineage",
)
DEFAULT_SOURCE_CONTRACT = PromotionSourceContract(
    v20_root=REPO_ROOT / "tmp/map-production/k3-field-margin-cleanup-proof-v20",
    v19_candidate=REPO_ROOT
    / "tmp/map-production/k3-sparse-ridgeline-v19/style-candidate-k-v3-sparse-ridgeline-v19.png",
    v19_receipt=REPO_ROOT
    / "world/map-production/prompts/style-candidate-k-v3-sparse-ridgeline-v19.provenance-receipt.json",
    v19_builder=REPO_ROOT
    / "scripts/map-production/build_style_candidate_k3_sparse_ridgeline_v19.py",
    generated_layout_control=REPO_ROOT
    / "world/map-production/style-assets/k3-v55-topographic-contour-atlas.png",
    control_atlas_metadata=REPO_ROOT
    / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/k3-v52-eight-ridge-control-atlas.json",
    canonical_body_control=REPO_ROOT
    / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/k3-v52-canonical-body-control.png",
    imagegen_prompt=REPO_ROOT
    / "world/map-production/prompts/style-candidate-k-v3-highland-contour-atlas-v55.generation.txt",
    generation_receipt=REPO_ROOT
    / "world/map-production/prompts/style-candidate-k-v3-highland-contour-atlas-v55.generation-receipt.json",
)
DEFAULT_REVIEW_A = (
    REPO_ROOT / "world/map-production/qa/style-candidate-k-v3-semantic-cleanup-review-a.json"
)
DEFAULT_REVIEW_B = (
    REPO_ROOT / "world/map-production/qa/style-candidate-k-v3-semantic-cleanup-review-b.json"
)


def _audit_authority_paths() -> dict[str, Path]:
    """Files whose bytes define persistent K3 mask/spec and audit semantics."""

    return {
        "k3-source": Path(k3_audit.k3.SOURCE),
        "k3-spec": Path(k3_audit.k3.SPEC),
        "reference-b1": Path(k3_audit.k2_audit.B1_REFERENCE),
        "reference-h4": Path(k3_audit.k2_audit.H4_REFERENCE),
        "geometry-guide": Path(k3_audit.k2_audit.GUIDE),
        "audit-h4-code": Path(k3_audit.h4.__file__).resolve(),
        "audit-h17-code": Path(k3_audit.h17.__file__).resolve(),
        "audit-k2-code": Path(k3_audit.k2_audit.__file__).resolve(),
    }


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _same_resolved_path(left: Path | str, right: Path | str) -> bool:
    def resolved(value: Path | str) -> Path:
        path = Path(value)
        return (path if path.is_absolute() else REPO_ROOT / path).resolve()

    return resolved(left) == resolved(right)


def _v20_expected_paths(contract: PromotionSourceContract) -> dict[str, Path]:
    root = contract.v20_root
    result = {
        "candidate": root / f"{V20_STEM}.png",
        "permission": root / f"{V20_STEM}.field-margin-permission.png",
        "alpha": root / f"{V20_STEM}.field-margin-alpha.png",
        "actual_change": root / f"{V20_STEM}.actual-change.png",
        "contact:full_25": root / f"{V20_STEM}.full-25.contact.png",
        "contact:full_50": root / f"{V20_STEM}.full-50.contact.png",
    }
    for crop in ("west", "east", "south"):
        for scale in (200, 400):
            result[f"contact:fields_{crop}_{scale}"] = (
                root / f"{V20_STEM}.fields-{crop}-{scale}.contact.png"
            )
    return result


def _assert_exact_source_namespace(
    source_receipt_path: Path,
    receipt: dict[str, Any],
    contract: PromotionSourceContract,
) -> None:
    temp_parent = (REPO_ROOT / "tmp/map-production").resolve()
    for label, candidate in (
        ("v20 root", contract.v20_root),
        ("v19 candidate", contract.v19_candidate),
    ):
        try:
            candidate.resolve().relative_to(temp_parent)
        except ValueError as exc:
            raise K3GoldenPromotionError(
                f"{label} must stay inside the exact TEMP namespace {temp_parent}"
            ) from exc
    if (
        not contract.test_only_allow_dynamic_temp_root
        and contract.v20_root.resolve() != DEFAULT_SOURCE_CONTRACT.v20_root.resolve()
    ):
        raise K3GoldenPromotionError(
            f"v20 source root must be the production contract root {DEFAULT_SOURCE_CONTRACT.v20_root}"
        )
    if not contract.test_only_allow_dynamic_temp_root:
        for label, field in (
            ("v19 candidate", "v19_candidate"),
            ("v19 provenance receipt", "v19_receipt"),
            ("v19 reconstruction builder", "v19_builder"),
            ("v55 generated layout control", "generated_layout_control"),
            ("v52 control-atlas metadata", "control_atlas_metadata"),
            ("v52 canonical body control", "canonical_body_control"),
            ("v55 exact ImageGen prompt", "imagegen_prompt"),
            ("v55 generation receipt", "generation_receipt"),
        ):
            actual = getattr(contract, field)
            expected_contract_path = getattr(DEFAULT_SOURCE_CONTRACT, field)
            if not _same_resolved_path(actual, expected_contract_path):
                raise K3GoldenPromotionError(
                    f"{label} must use the canonical production contract path "
                    f"{expected_contract_path}"
                )
    expected_receipt = contract.v20_root / f"{V20_STEM}.provenance-receipt.json"
    if not _same_resolved_path(source_receipt_path, expected_receipt):
        raise K3GoldenPromotionError(
            f"v20 source receipt must be the exact TEMP contract path {expected_receipt}"
        )
    expected = _v20_expected_paths(contract)
    artifacts = receipt.get("artifacts")
    assert isinstance(artifacts, dict)  # checked by _assert_exact_v20_receipt
    for role, expected_path in expected.items():
        record = artifacts.get(role)
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise K3GoldenPromotionError(f"v20 artifact {role!r} has no exact path")
        if not _same_resolved_path(record["path"], expected_path):
            raise K3GoldenPromotionError(
                f"v20 artifact {role!r} must use exact TEMP filename {expected_path}"
            )
    v19 = receipt.get("v19_input")
    if not isinstance(v19, dict) or not isinstance(v19.get("path"), str) or not _same_resolved_path(
        v19["path"], contract.v19_candidate
    ):
        raise K3GoldenPromotionError(
            f"v19 input must use exact TEMP contract path {contract.v19_candidate}"
        )


def _conditional_manifest_replace(
    path: Path, value: dict[str, Any], *, expected: BoundArtifact
) -> None:
    """Replace a manifest only while its bound expected SHA remains current."""

    lock = path.with_name(f".{path.name}.k3-promotion.lock")
    temporary = path.with_name(f".{path.name}.k3-promotion-{uuid.uuid4().hex}.tmp")
    lock_fd: int | None = None
    try:
        try:
            lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise K3GoldenPromotionError(
                f"manifest compare-and-swap lock already exists: {lock}"
            ) from exc
        os.write(lock_fd, expected.sha256.encode("ascii"))
        os.fsync(lock_fd)
        expected.assert_unchanged()
        current = bind_file(path, label="manifest compare-and-swap current", trackable=True)
        if current.sha256 != expected.sha256 or current.data != expected.data:
            raise K3GoldenPromotionError(
                "manifest compare-and-swap failed: expected snapshot was replaced"
            )
        with temporary.open("xb") as handle:
            handle.write(_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        expected.assert_unchanged()
        current = bind_file(path, label="manifest compare-and-swap final", trackable=True)
        if current.sha256 != expected.sha256 or current.data != expected.data:
            raise K3GoldenPromotionError(
                "manifest compare-and-swap failed: expected SHA-256 is no longer current"
            )
        os.replace(temporary, path)
    except BoundArtifactError as exc:
        raise K3GoldenPromotionError(str(exc)) from exc
    finally:
        temporary.unlink(missing_ok=True)
        if lock_fd is not None:
            os.close(lock_fd)
            lock.unlink(missing_ok=True)


def _assert_unchanged(bindings: Any) -> None:
    try:
        assert_bindings_unchanged(bindings)
    except BoundArtifactError as exc:
        raise K3GoldenPromotionError(str(exc)) from exc


def _write_new(path: Path, payload: bytes, *, label: str) -> str:
    try:
        resolved, relative = require_trackable_path(
            path, label=label, must_exist=False, require_file=True
        )
    except ReleasePathError as exc:
        raise K3GoldenPromotionError(str(exc)) from exc
    if resolved.exists():
        raise K3GoldenPromotionError(f"refusing to overwrite {label}: {relative}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    opened = False
    try:
        with resolved.open("xb") as handle:
            opened = True
            handle.write(payload)
    except FileExistsError as exc:
        raise K3GoldenPromotionError(f"refusing to overwrite {label}: {relative}") from exc
    except Exception:
        if opened:
            resolved.unlink(missing_ok=True)
        raise
    return relative


def _copy_new(
    binding: BoundArtifact,
    destination: Path,
    *,
    label: str,
    bound_outputs: list[BoundArtifact] | None = None,
) -> dict[str, str]:
    relative = _write_new(destination, binding.data, label=label)
    try:
        copied = bind_file(destination, label=label, trackable=True)
        if copied.sha256 != binding.sha256:
            raise K3GoldenPromotionError(f"{label} changed while it was copied")
        if bound_outputs is not None:
            bound_outputs.append(copied)
        return {"path": relative, "sha256": copied.sha256}
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _bound_record(
    record: Any, *, label: str, sha_field: str = "sha256", trackable: bool = False
) -> BoundArtifact:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise K3GoldenPromotionError(f"{label} must contain a path")
    claimed = record.get(sha_field)
    if not isinstance(claimed, str) or len(claimed) != 64 or claimed != claimed.lower():
        raise K3GoldenPromotionError(f"{label}.{sha_field} must be a lowercase SHA-256 digest")
    try:
        bound = bind_file(record["path"], label=label, trackable=trackable)
    except (BoundArtifactError, ReleasePathError) as exc:
        raise K3GoldenPromotionError(str(exc)) from exc
    if bound.sha256 != claimed:
        raise K3GoldenPromotionError(
            f"{label} SHA-256 mismatch: receipt={claimed}, actual={bound.sha256}"
        )
    if "bytes" in record and record.get("bytes") != len(bound.data):
        raise K3GoldenPromotionError(
            f"{label}.bytes mismatch: receipt={record.get('bytes')!r}, actual={len(bound.data)}"
        )
    if "mode" in record or "size" in record:
        from io import BytesIO

        try:
            with Image.open(BytesIO(bound.data)) as image:
                image.load()
                if record.get("mode") != image.mode or record.get("size") != list(image.size):
                    raise K3GoldenPromotionError(
                        f"{label} image metadata is stale: receipt mode/size="
                        f"{record.get('mode')!r}/{record.get('size')!r}, "
                        f"actual={image.mode!r}/{list(image.size)!r}"
                    )
        except OSError as exc:
            raise K3GoldenPromotionError(f"{label} is not a readable image: {exc}") from exc
    return bound


def _bind_exact_contract_record(
    record: Any,
    expected_path: Path,
    *,
    label: str,
    trackable: bool = True,
) -> BoundArtifact:
    if (
        not isinstance(record, dict)
        or not isinstance(record.get("path"), str)
        or not _same_resolved_path(record["path"], expected_path)
    ):
        raise K3GoldenPromotionError(
            f"{label}.path must be the exact contract path {expected_path}"
        )
    return _bound_record(record, label=label, trackable=trackable)


def _assert_candidate_is_not_known_non_golden_source(
    binding: BoundArtifact,
) -> None:
    source = KNOWN_NON_GOLDEN_SOURCE_SHA256.get(binding.sha256)
    if source is not None:
        raise K3GoldenPromotionError(
            f"refusing known non-Golden/source candidate bytes: {source}; "
            f"sha256={binding.sha256}"
        )


def _reject_hidden_record_paths(record: Any, *, label: str) -> None:
    if not isinstance(record, dict):
        return
    hidden = [
        key
        for key in record
        if isinstance(key, str)
        and key != "path"
        and key.casefold().endswith("_path")
    ]
    if hidden:
        raise K3GoldenPromotionError(
            f"{label} contains unenumerated path authorities: {sorted(hidden)}"
        )


def _bind_nested_authority_records(
    value: Any,
    *,
    label: str,
) -> list[BoundArtifact]:
    """Bind every path/SHA record reachable from a JSON authority."""

    result: list[BoundArtifact] = []
    seen: set[tuple[str, str]] = set()

    def visit(node: Any, location: str) -> None:
        if isinstance(node, dict):
            for key, raw_path in node.items():
                folded = key.casefold()
                if not isinstance(raw_path, str) or not (
                    folded == "path" or folded.endswith("_path")
                ):
                    continue
                hash_key = "sha256" if folded == "path" else key[: -len("_path")] + "_sha256"
                claimed = node.get(hash_key)
                if not isinstance(claimed, str):
                    raise K3GoldenPromotionError(
                        f"{location}.{key} must have a matching {hash_key} authority lock"
                    )
                binding = _bound_record(
                    {"path": raw_path, "sha256": claimed},
                    label=f"{location}.{key}",
                    trackable=True,
                )
                key = (binding.identity, binding.sha256)
                if key not in seen:
                    seen.add(key)
                    result.append(binding)
            for key, child in node.items():
                visit(child, f"{location}.{key}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{location}[{index}]")

    visit(value, label)
    return result


def _replay_v19(lineage: V19Lineage) -> None:
    scratch_parent = REPO_ROOT / "tmp/map-production"
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".k3-v19-replay-", dir=scratch_parent
    ) as raw_scratch:
        scratch = Path(raw_scratch)

        def materialize(name: str, binding: BoundArtifact) -> Path:
            suffix = binding.path.suffix or ".bin"
            target = scratch / f"{name}{suffix}"
            target.write_bytes(binding.data)
            return target

        builder = materialize("builder", lineage.builder)
        base = materialize("base-v18", lineage.base_v18)
        layout = materialize("layout-control", lineage.layout_control)
        metadata = materialize(
            "control-atlas-metadata", lineage.control_atlas_metadata
        )
        body_control = materialize(
            "canonical-body-control", lineage.canonical_body_control
        )
        prompt = materialize("imagegen-prompt", lineage.imagegen_prompt)
        generation = materialize("generation-receipt", lineage.generation_receipt)
        authority_paths = [
            {
                "role": role,
                "path": str(materialize(f"authority-{index}", binding)),
                "sha256": binding.sha256,
            }
            for index, (role, binding) in enumerate(lineage.authorities)
        ]
        replay_contract = {
            "schema_version": "1.0.0",
            "interface": V19_REPLAY_INTERFACE,
            "base_v18": {"path": str(base), "sha256": lineage.base_v18.sha256},
            "generated_layout_control": {
                "path": str(layout),
                "sha256": lineage.layout_control.sha256,
            },
            "control_atlas_metadata": {
                "path": str(metadata),
                "sha256": lineage.control_atlas_metadata.sha256,
            },
            "canonical_body_control": {
                "path": str(body_control),
                "sha256": lineage.canonical_body_control.sha256,
            },
            "imagegen_prompt": {
                "path": str(prompt),
                "sha256": lineage.imagegen_prompt.sha256,
            },
            "generation_receipt": {
                "path": str(generation),
                "sha256": lineage.generation_receipt.sha256,
            },
            "authorities": authority_paths,
        }
        replay_path = scratch / "replay-contract.json"
        replay_path.write_bytes(_json_bytes(replay_contract))
        output = scratch / "reconstructed-v19.png"
        completed = subprocess.run(
            [
                sys.executable,
                str(builder),
                "--replay-contract",
                str(replay_path),
                "--output",
                str(output),
            ],
            cwd=scratch,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0 or not output.is_file():
            detail = (completed.stderr or completed.stdout).strip()
            raise K3GoldenPromotionError(
                "exact v19 deterministic reconstruction failed"
                + (f": {detail}" if detail else "")
            )
        replayed = bind_file(output, label="replayed v19 candidate", trackable=False)
        if replayed.sha256 != lineage.candidate.sha256 or replayed.data != lineage.candidate.data:
            raise K3GoldenPromotionError(
                "exact v19 deterministic reconstruction is not byte-identical to the bound v19 candidate"
            )


def _bind_v19_lineage(
    source_receipt: dict[str, Any], contract: PromotionSourceContract
) -> V19Lineage:
    prefix = "missing exact v19 provenance contract"
    try:
        v19 = source_receipt.get("v19_input")
        if not isinstance(v19, dict) or v19.get("expected_sha256") != v19.get(
            "actual_sha256"
        ):
            raise K3GoldenPromotionError(
                "v19 input expected/actual SHA-256 binding is missing or stale"
            )
        candidate = _bind_exact_contract_record(
            {"path": v19.get("path"), "sha256": v19.get("actual_sha256")},
            contract.v19_candidate,
            label="TEMP v19 candidate",
            trackable=False,
        )
        receipt_record = v19.get("provenance_receipt")
        receipt_binding = _bind_exact_contract_record(
            receipt_record,
            contract.v19_receipt,
            label="v19 provenance receipt",
        )
        receipt = receipt_binding.json_object()
        exact_keys = {
            "schema_version",
            "id",
            "status",
            "authority_inventory_complete",
            "candidate",
            "base_v18",
            "reconstruction_builder",
            "generated_layout_control",
            "control_atlas_metadata",
            "canonical_body_control",
            "imagegen_prompt",
            "generation_receipt",
            "authorities",
            "replay",
        }
        if set(receipt) != exact_keys:
            raise K3GoldenPromotionError(
                "v19 provenance receipt must contain the exact closed reconstruction graph: "
                f"missing={sorted(exact_keys - set(receipt))}, "
                f"extra={sorted(set(receipt) - exact_keys)}"
            )
        exact = {
            "schema_version": "1.0.0",
            "id": EXACT_V19_RECEIPT_ID,
            "status": EXACT_V19_STATUS,
            "authority_inventory_complete": True,
        }
        for field, expected in exact.items():
            if receipt.get(field) != expected:
                raise K3GoldenPromotionError(
                    f"v19 provenance receipt {field} must be {expected!r}"
                )
        receipt_candidate = _bind_exact_contract_record(
            receipt.get("candidate"),
            contract.v19_candidate,
            label="v19 receipt candidate",
            trackable=False,
        )
        _reject_hidden_record_paths(receipt.get("candidate"), label="v19 receipt candidate")
        if receipt_candidate.sha256 != candidate.sha256:
            raise K3GoldenPromotionError("v19 receipt candidate SHA does not match v20 input")
        base_v18 = _bound_record(
            receipt.get("base_v18"), label="v19 base v18", trackable=False
        )
        _reject_hidden_record_paths(receipt.get("base_v18"), label="v19 base v18")
        if base_v18.sha256 != REJECTED_V18_SHA256:
            raise K3GoldenPromotionError("v19 base is not the exact frozen v18")
        builder = _bind_exact_contract_record(
            receipt.get("reconstruction_builder"),
            contract.v19_builder,
            label="v19 reconstruction builder",
        )
        _reject_hidden_record_paths(
            receipt.get("reconstruction_builder"), label="v19 reconstruction builder"
        )
        layout = _bind_exact_contract_record(
            receipt.get("generated_layout_control"),
            contract.generated_layout_control,
            label="v19 generated layout control",
        )
        _reject_hidden_record_paths(
            receipt.get("generated_layout_control"), label="v19 generated layout control"
        )
        control_atlas_metadata = _bind_exact_contract_record(
            receipt.get("control_atlas_metadata"),
            contract.control_atlas_metadata,
            label="v19 control-atlas metadata",
        )
        _reject_hidden_record_paths(
            receipt.get("control_atlas_metadata"),
            label="v19 control-atlas metadata",
        )
        canonical_body_control = _bind_exact_contract_record(
            receipt.get("canonical_body_control"),
            contract.canonical_body_control,
            label="v19 canonical body control",
        )
        _reject_hidden_record_paths(
            receipt.get("canonical_body_control"),
            label="v19 canonical body control",
        )
        prompt = _bind_exact_contract_record(
            receipt.get("imagegen_prompt"),
            contract.imagegen_prompt,
            label="v19 exact ImageGen prompt",
        )
        _reject_hidden_record_paths(receipt.get("imagegen_prompt"), label="v19 ImageGen prompt")
        generation = _bind_exact_contract_record(
            receipt.get("generation_receipt"),
            contract.generation_receipt,
            label="v19 ImageGen generation receipt",
        )
        _reject_hidden_record_paths(
            receipt.get("generation_receipt"), label="v19 generation receipt"
        )
        if not contract.test_only_allow_dynamic_temp_root:
            fixed_sources = {
                "reconstruction_builder": builder,
                "generated_layout_control": layout,
                "control_atlas_metadata": control_atlas_metadata,
                "canonical_body_control": canonical_body_control,
                "imagegen_prompt": prompt,
                "generation_receipt": generation,
            }
            for role, binding in fixed_sources.items():
                expected_sha256 = EXPECTED_V19_FIXED_SOURCE_SHA256[role]
                if binding.sha256 != expected_sha256:
                    raise K3GoldenPromotionError(
                        f"v19 {role} must have frozen SHA-256 {expected_sha256}, "
                        f"found {binding.sha256}"
                    )
        replay = receipt.get("replay")
        if not isinstance(replay, dict) or replay != {
            "interface": V19_REPLAY_INTERFACE,
            "byte_exact": True,
        }:
            raise K3GoldenPromotionError("v19 replay contract is missing or not byte-exact")
        raw_authorities = receipt.get("authorities")
        if not isinstance(raw_authorities, list):
            raise K3GoldenPromotionError("v19 authority inventory must be a list")
        roles: set[str] = set()
        for index, record in enumerate(raw_authorities):
            role = record.get("role") if isinstance(record, dict) else None
            if not isinstance(role, str) or not role.strip() or role in roles:
                raise K3GoldenPromotionError(
                    f"v19 authorities[{index}] has a missing or duplicate role"
                )
            roles.add(role)
        if roles != REQUIRED_V19_AUTHORITY_ROLES:
            raise K3GoldenPromotionError(
                "v19 authority roles must match the exact builder contract: "
                f"missing={sorted(REQUIRED_V19_AUTHORITY_ROLES - roles)}, "
                f"extra={sorted(roles - REQUIRED_V19_AUTHORITY_ROLES)}"
            )
        if (
            contract.test_only_expected_authorities is not None
            and not contract.test_only_allow_dynamic_temp_root
        ):
            raise K3GoldenPromotionError(
                "test-only v19 authority overrides require the dynamic TEMP test contract"
            )
        if contract.test_only_expected_authorities is None:
            expected_authorities = EXPECTED_V19_AUTHORITY_ARTIFACTS
        else:
            expected_authorities = {
                role: {"path": path, "sha256": sha256}
                for role, path, sha256 in contract.test_only_expected_authorities
            }
        if set(expected_authorities) != REQUIRED_V19_AUTHORITY_ROLES:
            raise K3GoldenPromotionError(
                "internal v19 expected-authority contract does not match the exact role set"
            )
        authorities: list[tuple[str, BoundArtifact]] = []
        for index, record in enumerate(raw_authorities):
            assert isinstance(record, dict)  # role shape checked above
            role = record["role"]
            expected = expected_authorities[role]
            expected_path = expected["path"]
            expected_sha256 = expected["sha256"]
            if (
                not isinstance(record.get("path"), str)
                or not _same_resolved_path(record["path"], expected_path)
                or record.get("sha256") != expected_sha256
            ):
                raise K3GoldenPromotionError(
                    f"v19 authority {role!r} must bind the exact canonical "
                    f"path/SHA-256 {expected_path}/{expected_sha256}"
                )
            _reject_hidden_record_paths(record, label=f"v19 authority {role!r}")
            authorities.append(
                (
                    role,
                    _bound_record(
                        record,
                        label=f"v19 authority {role!r}",
                        trackable=True,
                    ),
                )
            )
        metadata_document = control_atlas_metadata.json_object()
        metadata_nested = _bind_nested_authority_records(
            metadata_document, label="v19 control-atlas metadata"
        )
        authority_by_role = dict(authorities)
        allowed_metadata_bindings = {
            (binding.identity, binding.sha256)
            for binding in (
                canonical_body_control,
                authority_by_role["v52-control-atlas"],
            )
        }
        undeclared_metadata = [
            binding
            for binding in metadata_nested
            if (binding.identity, binding.sha256) not in allowed_metadata_bindings
        ]
        if undeclared_metadata:
            raise K3GoldenPromotionError(
                "v19 control-atlas metadata contains undeclared nested authority "
                "binding(s): "
                + ", ".join(binding.relative for binding in undeclared_metadata)
            )
        generation_document = generation.json_object()
        nested = _bind_nested_authority_records(
            generation_document, label="v19 generation receipt"
        )
        allowed_nested_bindings = {
            (binding.identity, binding.sha256)
            for binding in (
                base_v18,
                layout,
                control_atlas_metadata,
                canonical_body_control,
                prompt,
                *(binding for _, binding in authorities),
            )
        }
        undeclared_nested = [
            binding
            for binding in nested
            if (binding.identity, binding.sha256) not in allowed_nested_bindings
        ]
        if undeclared_nested:
            raise K3GoldenPromotionError(
                "v19 generation receipt contains undeclared nested authority "
                "binding(s): "
                + ", ".join(binding.relative for binding in undeclared_nested)
            )
        lineage = V19Lineage(
            candidate=candidate,
            receipt=receipt_binding,
            base_v18=base_v18,
            builder=builder,
            layout_control=layout,
            control_atlas_metadata=control_atlas_metadata,
            canonical_body_control=canonical_body_control,
            imagegen_prompt=prompt,
            generation_receipt=generation,
            authorities=tuple(authorities),
        )
        _replay_v19(lineage)
        return lineage
    except (
        BoundArtifactError,
        ReleasePathError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        raise K3GoldenPromotionError(f"{prefix}: {exc}") from exc
    except K3GoldenPromotionError as exc:
        if str(exc).startswith(prefix):
            raise
        raise K3GoldenPromotionError(f"{prefix}: {exc}") from exc


def _assert_native_candidate(binding: BoundArtifact) -> None:
    from io import BytesIO

    try:
        with Image.open(BytesIO(binding.data)) as image:
            image.load()
            if (
                image.format != "PNG"
                or image.mode != "RGB"
                or image.size != EXPECTED_SIZE
                or image.getbands() != ("R", "G", "B")
                or image.info.get("transparency") is not None
                or image.info.get("icc_profile")
            ):
                raise K3GoldenPromotionError(
                    "v20 candidate must be a native 1536x1024 untagged RGB PNG"
                )
    except OSError as exc:
        raise K3GoldenPromotionError(f"v20 candidate is not a readable PNG: {exc}") from exc


def _assert_exact_v20_receipt(receipt: dict[str, Any]) -> None:
    exact = {
        "schema_version": "1.0.0",
        "id": EXACT_V20_RECEIPT_ID,
        "status": EXACT_V20_STATUS,
        "temporary_review_only": True,
        "persistent_candidate_emitted": False,
        "golden_accepted": False,
    }
    for field, expected in exact.items():
        if receipt.get(field) != expected:
            raise K3GoldenPromotionError(
                f"source receipt {field} must be {expected!r}, found {receipt.get(field)!r}"
            )
    gates = receipt.get("automated_gates")
    if not isinstance(gates, dict) or set(gates) != REQUIRED_V20_GATES:
        raise K3GoldenPromotionError("source receipt has the wrong exact v20 automated gate set")
    failed = [name for name, value in gates.items() if value is not True]
    if failed or receipt.get("failed_gates") != []:
        raise K3GoldenPromotionError(f"source v20 automated gates are not all passed: {failed}")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != REQUIRED_V20_ARTIFACTS:
        raise K3GoldenPromotionError("source receipt has the wrong exact v20 artifact set")
    handoff = receipt.get("vision_handoff")
    if not isinstance(handoff, dict) or (
        handoff.get("required") is not True
        or handoff.get("acceptance_threshold") != ACCEPTANCE_THRESHOLD
        or handoff.get("candidate_must_not_be_promoted_before_acceptance") is not True
    ):
        raise K3GoldenPromotionError("source receipt has an invalid Root Vision handoff")


def _assert_persistent_graph(value: Any, *, location: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{location}.{key}"
            if key == "path" or key.endswith("_path"):
                if not isinstance(item, str):
                    raise K3GoldenPromotionError(f"{child} must be a trackable path")
                try:
                    require_trackable_path(item, label=child)
                except ReleasePathError as exc:
                    raise K3GoldenPromotionError(str(exc)) from exc
            else:
                _assert_persistent_graph(item, location=child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_persistent_graph(item, location=f"{location}[{index}]")


def _validate_projected_manifest(path: Path, manifest: dict[str, Any]) -> None:
    candidate = path.with_name(f".{path.name}.k3-promotion-validation.json")
    if candidate.exists():
        raise K3GoldenPromotionError(f"manifest validation scratch path already exists: {candidate}")
    try:
        with candidate.open("xb") as handle:
            handle.write(_json_bytes(manifest))
        _, errors = validate_manifest(candidate, check_files=True)
    finally:
        candidate.unlink(missing_ok=True)
    if errors:
        raise K3GoldenPromotionError("projected manifest is invalid: " + "; ".join(errors))


def _artifact_name(key: str) -> str:
    return key.replace(":", "-").replace("_", "-") + ".png"


def prepare_promotion(
    *,
    source_receipt_path: Path,
    authorized_by: str,
    paths: PromotionPaths = DEFAULT_PATHS,
    source_contract: PromotionSourceContract = DEFAULT_SOURCE_CONTRACT,
    audit_builder: Callable[..., dict[str, Any]] = k3_audit.persistent_v20_audit,
) -> dict[str, Any]:
    """Persist v20 evidence and stop at automated-qa; never infer Vision acceptance."""

    if not authorized_by.strip():
        raise K3GoldenPromotionError("authorized_by must be non-empty")
    try:
        manifest_binding = bind_file(
            paths.manifest, label="original production manifest", trackable=True
        )
        manifest = manifest_binding.json_object()
    except BoundArtifactError as exc:
        raise K3GoldenPromotionError(str(exc)) from exc
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list):
        raise K3GoldenPromotionError("production manifest must contain a jobs array")
    if any(isinstance(job, dict) and job.get("id") == JOB_ID for job in jobs):
        raise K3GoldenPromotionError(f"manifest job {JOB_ID!r} already exists")

    try:
        source_receipt_binding = bind_file(
            source_receipt_path, label="TEMP v20 source receipt", trackable=False
        )
        source_receipt = source_receipt_binding.json_object()
    except BoundArtifactError as exc:
        raise K3GoldenPromotionError(str(exc)) from exc
    _assert_exact_v20_receipt(source_receipt)
    _assert_exact_source_namespace(source_receipt_path, source_receipt, source_contract)

    artifacts = source_receipt["artifacts"]
    source_bindings: list[BoundArtifact] = [source_receipt_binding]
    candidate_binding = _bound_record(artifacts["candidate"], label="TEMP v20 candidate")
    source_bindings.append(candidate_binding)
    _assert_candidate_is_not_known_non_golden_source(candidate_binding)
    _assert_native_candidate(candidate_binding)

    v19_lineage = _bind_v19_lineage(source_receipt, source_contract)
    v19_binding = v19_lineage.candidate
    source_bindings.extend(v19_lineage.bindings())
    lineage = source_receipt.get("lineage")
    v18_record = lineage.get("v18_reference") if isinstance(lineage, dict) else None
    v18_binding = _bound_record(v18_record, label="rejected v18 lineage")
    source_bindings.append(v18_binding)
    if v18_binding.sha256 != REJECTED_V18_SHA256:
        raise K3GoldenPromotionError("source receipt does not bind the exact rejected v18 lineage")
    if v18_binding.data != v19_lineage.base_v18.data:
        raise K3GoldenPromotionError("v20 and v19 receipts bind different v18 lineage bytes")

    stable_source_records: dict[str, dict[str, str]] = {}
    stable_source_bindings: dict[str, BoundArtifact] = {}
    for key in ("builder", "k3_builder", "k3_audit"):
        record = source_receipt.get(key)
        if not isinstance(record, dict) or record.get("path") != EXACT_SOURCE_PATHS[key]:
            raise K3GoldenPromotionError(f"source receipt {key}.path is not the exact v20 contract")
        binding = _bound_record(record, label=f"v20 source {key}", trackable=True)
        source_bindings.append(binding)
        stable_source_bindings[key] = binding
        stable_source_records[key] = binding.artifact()
    donor = source_receipt.get("fields_donor")
    if not isinstance(donor, dict) or any(
        donor.get(field) != expected for field, expected in EXACT_FIELDS_DONOR.items()
    ):
        raise K3GoldenPromotionError("source receipt fields_donor is not the exact v20 donor contract")
    donor_binding = _bound_record(donor, label="v20 fields donor", trackable=True)
    prompt_binding = _bound_record(
        {"path": donor.get("prompt_path") if isinstance(donor, dict) else None,
         "sha256": donor.get("prompt_sha256") if isinstance(donor, dict) else None},
        label="v20 fields donor prompt",
        trackable=True,
    )
    source_bindings.extend((donor_binding, prompt_binding))

    audit_authorities: dict[str, BoundArtifact] = {}
    for role, path in _audit_authority_paths().items():
        try:
            binding = bind_file(path, label=f"persistent audit authority {role}", trackable=True)
        except BoundArtifactError as exc:
            raise K3GoldenPromotionError(str(exc)) from exc
        audit_authorities[role] = binding
        source_bindings.append(binding)

    auxiliary_bindings: dict[str, BoundArtifact] = {}
    for key, record in artifacts.items():
        if key == "candidate":
            continue
        binding = _bound_record(record, label=f"TEMP v20 artifact {key}")
        source_bindings.append(binding)
        auxiliary_bindings[key] = binding

    created: list[Path] = []
    persistent_bindings: list[BoundArtifact] = []
    try:
        raw_artifact = _copy_new(
            candidate_binding,
            paths.raw,
            label="persistent K3 raw",
            bound_outputs=persistent_bindings,
        )
        raw_output_binding = persistent_bindings[-1]
        created.append(paths.raw)
        final_artifact = _copy_new(
            candidate_binding,
            paths.final,
            label="persistent K3 final",
            bound_outputs=persistent_bindings,
        )
        final_output_binding = persistent_bindings[-1]
        created.append(paths.final)
        if (
            raw_artifact["sha256"] != final_artifact["sha256"]
            or persistent_bindings[-2].data != persistent_bindings[-1].data
        ):
            raise K3GoldenPromotionError("persistent K3 raw/final identity contract failed")
        v19_artifact = _copy_new(
            v19_binding,
            paths.v19_parent,
            label="persistent v19 parent",
            bound_outputs=persistent_bindings,
        )
        v19_output_binding = persistent_bindings[-1]
        created.append(paths.v19_parent)
        v18_artifact = _copy_new(
            v18_binding,
            paths.v18_lineage,
            label="persistent rejected v18 lineage",
            bound_outputs=persistent_bindings,
        )
        created.append(paths.v18_lineage)

        v19_receipt_path = paths.v19_receipt or paths.receipt.with_name(
            f"{JOB_ID}.v19-normalized-provenance.json"
        )
        normalized_v19_receipt = {
            "schema_version": "1.0.0",
            "id": f"{JOB_ID}-normalized-v19-reconstruction",
            "status": EXACT_V19_STATUS,
            "authority_inventory_complete": True,
            "source_v19_receipt_sha256": v19_lineage.receipt.sha256,
            "candidate": v19_artifact,
            "base_v18": v18_artifact,
            "reconstruction_builder": v19_lineage.builder.artifact(),
            "generated_layout_control": v19_lineage.layout_control.artifact(),
            "control_atlas_metadata": (
                v19_lineage.control_atlas_metadata.artifact()
            ),
            "canonical_body_control": (
                v19_lineage.canonical_body_control.artifact()
            ),
            "imagegen_prompt": v19_lineage.imagegen_prompt.artifact(),
            "generation_receipt": v19_lineage.generation_receipt.artifact(),
            "authorities": [
                {"role": role, **binding.artifact()}
                for role, binding in v19_lineage.authorities
            ],
            "replay": {"interface": V19_REPLAY_INTERFACE, "byte_exact": True},
        }
        _assert_persistent_graph(normalized_v19_receipt)
        _write_new(
            v19_receipt_path,
            _json_bytes(normalized_v19_receipt),
            label="normalized v19 reconstruction receipt",
        )
        created.append(v19_receipt_path)
        normalized_v19_binding = bind_file(
            v19_receipt_path,
            label="normalized v19 reconstruction receipt",
            trackable=True,
        )
        persistent_bindings.append(normalized_v19_binding)

        lineage_dir = paths.lineage_dir or paths.receipt.parent / f"{JOB_ID}-authorities"
        normalized_audit_authorities: dict[str, dict[str, str]] = {}
        for role, binding in sorted(audit_authorities.items()):
            suffix = ".snapshot" if binding.path.suffix.casefold() == ".json" else binding.path.suffix
            destination = lineage_dir / f"{role}{suffix}"
            normalized_audit_authorities[role] = _copy_new(
                binding,
                destination,
                label=f"normalized persistent audit authority {role}",
                bound_outputs=persistent_bindings,
            )
            created.append(destination)

        copied_evidence: dict[str, dict[str, str]] = {}
        for key, binding in auxiliary_bindings.items():
            destination = (
                paths.masks_dir / f"{JOB_ID}-v20-{_artifact_name(key)}"
                if key in {"permission", "alpha", "actual_change"}
                else paths.evidence_dir / _artifact_name(key)
            )
            copied_evidence[key] = _copy_new(
                binding,
                destination,
                label=f"persistent v20 evidence {key}",
                bound_outputs=persistent_bindings,
            )
            created.append(destination)

        normalized_receipt = {
            "schema_version": "1.0.0",
            "id": f"{JOB_ID}-persistent-v20-provenance",
            "job_id": JOB_ID,
            "status": "passed-automated-pending-blind-vision",
            "golden_accepted": False,
            "acceptance_inferred": False,
            "temporary_review_only": False,
            "source_temporary_receipt_sha256": source_receipt_binding.sha256,
            "authorized_by": authorized_by,
            "raw": raw_artifact,
            "candidate": final_artifact,
            "lineage": {
                "rejected_v18": v18_artifact,
                "highland_parent_v19": v19_artifact,
                "v19_reconstruction": normalized_v19_binding.artifact(),
            },
            "implementation": stable_source_records,
            "audit_authorities": normalized_audit_authorities,
            "fields_donor": {
                **donor_binding.artifact(),
                "prompt": prompt_binding.artifact(),
            },
            "construction": source_receipt.get("construction"),
            "metrics": source_receipt.get("metrics"),
            "automated_gates": source_receipt.get("automated_gates"),
            "failed_gates": [],
            "evidence": copied_evidence,
            "vision_handoff": {
                "required": True,
                "acceptance_threshold": ACCEPTANCE_THRESHOLD,
                "minimum_independent_reviews": 2,
                "review_mode": "blind-independent",
                "immediate_failure_policy": "zero immediate failures",
                "candidate_must_not_be_accepted_before_both_reviews": True,
            },
            "created_at": utc_now(),
        }
        _assert_persistent_graph(normalized_receipt)
        _write_new(paths.receipt, _json_bytes(normalized_receipt), label="normalized K3 receipt")
        created.append(paths.receipt)
        receipt_binding = bind_file(paths.receipt, label="normalized K3 receipt", trackable=True)
        persistent_bindings.append(receipt_binding)
        receipt_artifact = receipt_binding.artifact()

        automated_report = audit_builder(
            raw_path=paths.raw,
            final_path=paths.final,
            v19_path=paths.v19_parent,
            raw_artifact=raw_artifact,
            final_artifact=final_artifact,
            normalized_receipt=receipt_artifact,
            source_receipt_sha256=source_receipt_binding.sha256,
            source_receipt=source_receipt,
            authorized_by=authorized_by,
            authority_bindings={
                **audit_authorities,
                "fields-donor": donor_binding,
                "fields-donor-prompt": prompt_binding,
                "audit-v20-code": stable_source_bindings["builder"],
                "audit-k3-code": stable_source_bindings["k3_builder"],
                "audit-k3-main-code": stable_source_bindings["k3_audit"],
            },
            artifact_bindings={
                "raw": raw_output_binding,
                "final": final_output_binding,
                "v19": v19_output_binding,
            },
            reported_authorities={
                **normalized_audit_authorities,
                "fields-donor": donor_binding.artifact(),
                "fields-donor-prompt": prompt_binding.artifact(),
                "audit-v20-code": stable_source_bindings["builder"].artifact(),
                "audit-k3-code": stable_source_bindings["k3_builder"].artifact(),
                "audit-k3-main-code": stable_source_bindings["k3_audit"].artifact(),
            },
        )
        if automated_report.get("status") != "passed" or automated_report.get("failed_gates") != []:
            raise K3GoldenPromotionError("persistent v20 audit did not pass")
        if automated_report.get("decision_authority") is not False or automated_report.get("acceptance_inferred") is not False:
            raise K3GoldenPromotionError("persistent v20 audit must be non-authoritative")
        _assert_persistent_graph(automated_report)
        _write_new(paths.audit, _json_bytes(automated_report), label="persistent K3 automated audit")
        created.append(paths.audit)
        audit_binding = bind_file(paths.audit, label="persistent K3 automated audit", trackable=True)
        persistent_bindings.append(audit_binding)

        event_at = utc_now()
        inputs = [
            {**raw_artifact, "role": "golden-raw-output"},
            {**receipt_artifact, "role": "promotion-provenance"},
            {**audit_binding.artifact(), "role": "persistent-automated-audit"},
            {**normalized_v19_binding.artifact(), "role": "v19-reconstruction-provenance"},
            {**v19_artifact, "role": "highland-parent-v19"},
            {**v18_artifact, "role": "rejected-lineage-v18"},
            {**v19_lineage.builder.artifact(), "role": "v19-reconstruction-builder"},
            {**v19_lineage.layout_control.artifact(), "role": "v19-generated-layout-control"},
            {
                **v19_lineage.control_atlas_metadata.artifact(),
                "role": "v19-control-atlas-metadata",
            },
            {
                **v19_lineage.canonical_body_control.artifact(),
                "role": "v19-canonical-body-control",
            },
            {**v19_lineage.imagegen_prompt.artifact(), "role": "v19-exact-imagegen-prompt"},
            {**v19_lineage.generation_receipt.artifact(), "role": "v19-generation-receipt"},
            {**donor_binding.artifact(), "role": "field-margin-donor"},
            {**prompt_binding.artifact(), "role": "locked-prompt"},
        ]
        inputs.extend(
            {**binding.artifact(), "role": f"v19-authority-{role}"}
            for role, binding in v19_lineage.authorities
        )
        inputs.extend(
            {**record, "role": f"audit-authority-{role}"}
            for role, record in sorted(normalized_audit_authorities.items())
        )
        inputs.extend(
            {**record, "role": f"v20-implementation-{key}"}
            for key, record in sorted(stable_source_records.items())
        )
        inputs.extend(
            {**record, "role": f"v20-{key}"} for key, record in copied_evidence.items()
        )
        job = {
            "id": JOB_ID,
            "sheet_id": SHEET_ID,
            "status": "automated-qa",
            "bounds": {"west": 0, "south": 0, "east": 10000, "north": 10000},
            "zoom": {"min": 0, "max": 2, "native": 2},
            "acceptance_threshold": ACCEPTANCE_THRESHOLD,
            "inputs": inputs,
            "generation": {
                "model": "deterministic-v20-field-margin-cleanup",
                "prompt_path": prompt_binding.relative,
                "prompt_sha256": prompt_binding.sha256,
                "control_image_path": v19_artifact["path"],
                "attempt": 1,
            },
            "master": {
                **final_artifact,
                "width": EXPECTED_SIZE[0],
                "height": EXPECTED_SIZE[1],
                "color_profile": "untagged RGB",
            },
            "qa": {
                "automated": {
                    "status": "passed",
                    "report_path": audit_binding.relative,
                }
            },
            "history": [
                {"state": state, "at": event_at, "actor": authorized_by}
                for state in ("planned", "inputs-ready", "generated", "automated-qa")
            ],
        }
        projected = copy.deepcopy(manifest)
        projected["jobs"].append(job)
        projected["updated_at"] = event_at
        _validate_projected_manifest(paths.manifest, projected)
        _assert_unchanged((manifest_binding, *source_bindings, *persistent_bindings))
        _conditional_manifest_replace(
            paths.manifest, projected, expected=manifest_binding
        )
        return {
            "status": "automated-qa",
            "job_id": JOB_ID,
            "candidate": final_artifact,
            "raw": raw_artifact,
            "receipt": receipt_artifact,
            "audit": audit_binding.artifact(),
            "golden_accepted": False,
        }
    except Exception:
        for path in reversed(created):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _accepted_blind_review(
    binding: BoundArtifact, *, image_path: str, image_sha256: str
) -> tuple[dict[str, Any], str]:
    try:
        report = binding.json_object()
    except BoundArtifactError as exc:
        raise K3GoldenPromotionError(str(exc)) from exc
    schema = load_json(REPO_ROOT / "world/map-production/schemas/qa-report.schema.json")
    errors = schema_errors(report, schema)
    if errors:
        raise K3GoldenPromotionError(f"invalid Golden review {binding.relative}: " + "; ".join(errors))
    exact = {
        "job_id": JOB_ID,
        "image_path": image_path,
        "image_sha256": image_sha256,
        "status": "complete",
        "golden_reference": True,
        "review_mode": "blind-independent",
        "acceptance_threshold": ACCEPTANCE_THRESHOLD,
        "decision": "accepted",
    }
    for field, expected in exact.items():
        if report.get(field) != expected:
            raise K3GoldenPromotionError(
                f"Golden review {binding.relative} {field} must be {expected!r}"
            )
    if "automated" in PurePosixPath(binding.relative).parts:
        raise K3GoldenPromotionError("Golden Vision reviews may not be stored under qa/automated")
    failures = report.get("immediate_failures")
    if not isinstance(failures, list) or not failures or any(
        not isinstance(item, dict) or item.get("detected") is not False for item in failures
    ):
        raise K3GoldenPromotionError(f"Golden review {binding.relative} has an immediate failure")
    scores = report.get("scores")
    if not isinstance(scores, list) or not scores or not all(isinstance(item, dict) for item in scores):
        raise K3GoldenPromotionError(f"Golden review {binding.relative} has invalid scores")
    maxima = [item.get("maximum") for item in scores]
    values = [item.get("score") for item in scores]
    integer = lambda value: isinstance(value, int) and not isinstance(value, bool)
    if not all(integer(value) for value in maxima + values):
        raise K3GoldenPromotionError(f"Golden review {binding.relative} has incomplete scores")
    total = report.get("total_score")
    if (
        sum(maxima) != 100
        or any(value > maximum for value, maximum in zip(values, maxima))
        or total != sum(values)
        or not integer(total)
        or total < ACCEPTANCE_THRESHOLD
    ):
        raise K3GoldenPromotionError(
            f"Golden review {binding.relative} must score at least {ACCEPTANCE_THRESHOLD} under the exact score contract"
        )
    reviewer = report.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise K3GoldenPromotionError(f"Golden review {binding.relative} has no reviewer")
    return report, reviewer.strip()


def accept_promotion(
    *,
    review_paths: list[Path],
    authorized_by: str,
    manifest_path: Path = DEFAULT_PATHS.manifest,
) -> dict[str, Any]:
    """Accept only a prepared job with exactly two distinct byte-bound reviews."""

    if len(review_paths) != 2:
        raise K3GoldenPromotionError("accept requires exactly two persistent Vision reviews")
    if not authorized_by.strip():
        raise K3GoldenPromotionError("authorized_by must be non-empty")
    manifest_binding = bind_file(manifest_path, label="prepared production manifest", trackable=True)
    manifest = manifest_binding.json_object()
    jobs = manifest.get("jobs")
    matches = [job for job in jobs if isinstance(job, dict) and job.get("id") == JOB_ID] if isinstance(jobs, list) else []
    if len(matches) != 1:
        raise K3GoldenPromotionError(f"manifest must contain exactly one prepared {JOB_ID!r} job")
    job = matches[0]
    if job.get("status") != "automated-qa":
        raise K3GoldenPromotionError("K3 Golden acceptance requires a job stopped at automated-qa")
    master = job.get("master")
    if not isinstance(master, dict):
        raise K3GoldenPromotionError("prepared K3 job has no master")
    master_binding = _bound_record(master, label="prepared K3 master", trackable=True)
    prepared_input_bindings: list[BoundArtifact] = []
    for index, record in enumerate(job.get("inputs", [])):
        if not isinstance(record, dict):
            raise K3GoldenPromotionError(
                f"prepared K3 inputs[{index}] must be a hashed artifact"
            )
        prepared_input_bindings.append(
            _bound_record(
                record,
                label=f"prepared K3 input {record.get('role', index)!r}",
                trackable=True,
            )
        )
    raw_inputs = [
        item for item in job.get("inputs", [])
        if isinstance(item, dict) and item.get("role") == "golden-raw-output"
    ]
    if len(raw_inputs) != 1:
        raise K3GoldenPromotionError("prepared K3 job must contain exactly one golden-raw-output")
    raw_binding = _bound_record(raw_inputs[0], label="prepared K3 raw", trackable=True)
    if raw_binding.path == master_binding.path or raw_binding.sha256 != master_binding.sha256 or raw_binding.data != master_binding.data:
        raise K3GoldenPromotionError("prepared K3 raw/final byte-identity contract failed")
    qa = job.get("qa")
    automated = qa.get("automated") if isinstance(qa, dict) else None
    if not isinstance(automated, dict) or automated.get("status") != "passed":
        raise K3GoldenPromotionError("prepared K3 automated audit is not passed")
    audit_inputs = [
        (record, binding)
        for record, binding in zip(job.get("inputs", []), prepared_input_bindings)
        if record.get("role") == "persistent-automated-audit"
    ]
    if len(audit_inputs) != 1 or not _same_resolved_path(
        automated.get("report_path", ""), audit_inputs[0][1].path
    ):
        raise K3GoldenPromotionError(
            "prepared K3 automated audit must be a unique manifest-hashed input"
        )
    audit_binding = audit_inputs[0][1]
    audit = audit_binding.json_object()
    if (
        audit.get("status") != "passed"
        or audit.get("image_path") != master_binding.relative
        or audit.get("image_sha256") != master_binding.sha256
        or audit.get("decision_authority") is not False
        or audit.get("acceptance_inferred") is not False
    ):
        raise K3GoldenPromotionError("prepared K3 automated audit binding is invalid")

    review_bindings = [
        bind_file(path, label=f"Golden Vision review {index + 1}", trackable=True)
        for index, path in enumerate(review_paths)
    ]
    if review_bindings[0].identity == review_bindings[1].identity:
        raise K3GoldenPromotionError("accept requires two distinct review artifacts")
    reviewed = [
        _accepted_blind_review(
            binding,
            image_path=master_binding.relative,
            image_sha256=master_binding.sha256,
        )
        for binding in review_bindings
    ]
    reviewers = {canonical_reviewer_identity(reviewer) for _, reviewer in reviewed}
    if len(reviewers) != 2:
        raise K3GoldenPromotionError("accept requires two distinct blind-independent reviewers")

    projected = copy.deepcopy(manifest)
    projected_job = next(item for item in projected["jobs"] if item.get("id") == JOB_ID)
    if any(
        isinstance(item, dict)
        and isinstance(item.get("role"), str)
        and item["role"].startswith("independent-vision-review-")
        for item in projected_job.get("inputs", [])
    ):
        raise K3GoldenPromotionError("prepared K3 job already contains Vision review inputs")
    projected_job["inputs"].extend(
        {**binding.artifact(), "role": role}
        for binding, role in zip(review_bindings, INDEPENDENT_VISION_REVIEW_ROLES)
    )
    primary_report, primary_reviewer = reviewed[0]
    now = utc_now()
    projected_job["qa"]["vision"] = {
        "decision": "accepted",
        "score": primary_report["total_score"],
        "report_path": review_bindings[0].relative,
        "reviewer": primary_reviewer,
        "reviewed_at": primary_report["created_at"],
    }
    for state in ("vision-qa", "accepted"):
        projected_job["history"].append(
            {"state": state, "at": now, "actor": authorized_by}
        )
    projected_job["status"] = "accepted"
    projected["updated_at"] = now
    _validate_projected_manifest(manifest_path, projected)
    _assert_unchanged(
        (
            manifest_binding,
            master_binding,
            raw_binding,
            audit_binding,
            *prepared_input_bindings,
            *review_bindings,
        )
    )
    _conditional_manifest_replace(manifest_path, projected, expected=manifest_binding)
    return {
        "status": "accepted",
        "job_id": JOB_ID,
        "candidate": master_binding.artifact(),
        "reviews": [binding.artifact() for binding in review_bindings],
        "reviewers": [reviewer for _, reviewer in reviewed],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="persist v20 and stop at automated-qa")
    prepare.add_argument("--source-receipt", type=Path, required=True)
    prepare.add_argument("--manifest", type=Path, default=DEFAULT_PATHS.manifest)
    prepare.add_argument("--authorized-by", required=True)
    accept = subparsers.add_parser("accept", help="accept after exactly two blind reviews")
    accept.add_argument("--manifest", type=Path, default=DEFAULT_PATHS.manifest)
    accept.add_argument("--review-a", type=Path, default=DEFAULT_REVIEW_A)
    accept.add_argument("--review-b", type=Path, default=DEFAULT_REVIEW_B)
    accept.add_argument("--authorized-by", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            paths = PromotionPaths(**{**DEFAULT_PATHS.__dict__, "manifest": args.manifest})
            result = prepare_promotion(
                source_receipt_path=args.source_receipt,
                authorized_by=args.authorized_by,
                paths=paths,
            )
        else:
            result = accept_promotion(
                review_paths=[args.review_a, args.review_b],
                authorized_by=args.authorized_by,
                manifest_path=args.manifest,
            )
    except (K3GoldenPromotionError, BoundArtifactError, ReleasePathError, OSError, ValueError) as exc:
        print(f"K3 Golden promotion failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
