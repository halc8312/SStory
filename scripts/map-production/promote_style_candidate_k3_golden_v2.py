#!/usr/bin/env python3
"""Generic two-phase, fail-closed Phase 4 K3 Golden promotion.

``prepare`` consumes one TEMP-only emission and its Root Vision authorization,
persists a normalized evidence graph, and stops at ``automated-qa``. ``accept``
requires exactly two persistent, blind-independent Golden QA reports before it
records ``vision-qa`` and ``accepted``.

This path is intentionally independent of the frozen v20-specific promoter.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import uuid
import zlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from PIL import Image, PngImagePlugin

import audit_style_candidate_k3_golden_v2 as pixel_auditor
from production_common import (
    ID_PATTERN,
    REPO_ROOT,
    ValidationFailure,
    load_json,
    parse_rfc3339,
    utc_now,
)
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
ACCEPTANCE_THRESHOLD = 94
EXPECTED_SIZE = (1536, 1024)
EMISSION_STATUS = "passed-automated-pending-root-vision"
PREPARED_STATUS = "passed-automated-pending-blind-vision"
PYTHON_RUNTIME_TOKEN = "{python}"
OUTPUT_TOKEN = "{output}"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
BLIND_PNG_TEXT_METADATA = (
    ("sstory-blind-contract", "phase4-v2"),
    ("sstory-blind-view", None),
)
QA_REPORT_SCHEMA = REPO_ROOT / "world/map-production/schemas/qa-report.schema.json"
READ_CLOSURE_RUNNER_PATH = (
    REPO_ROOT / "scripts/map-production/run_golden_v2_renderer_read_closed.py"
)
RENDERER_TIMEOUT_SECONDS = 300
FIXED_RENDERER_ENVIRONMENT = {
    "LANG": "C",
    "LC_ALL": "C",
    "MKL_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONNOUSERSITE": "1",
    "PYTHONSAFEPATH": "1",
    "PYTHONUTF8": "1",
    "TZ": "UTC",
}
PLATFORM_RUNTIME_ENVIRONMENT_KEYS = ("SYSTEMROOT", "WINDIR") if os.name == "nt" else ()

VIEW_DEFINITIONS: dict[
    str, tuple[tuple[int, int, int, int] | None, tuple[int, int]]
] = {
    "native": (None, (1536, 1024)),
    "full25": (None, (384, 256)),
    "full50": (None, (768, 512)),
    "highland200": ((930, 0, 1536, 560), (1212, 1120)),
    "highland400": ((930, 0, 1536, 560), (2424, 2240)),
}
VIEW_ORDER = tuple(VIEW_DEFINITIONS)

SOURCE_ARTIFACT_KEYS = frozenset({"path", "sha256", "bytes", "mode", "size"})
EMISSION_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "id",
        "job_id",
        "status",
        "created_at",
        "temporary_review_only",
        "previously_accepted",
        "golden_accepted",
        "candidate",
        "views",
        "metrics",
        "geometry",
        "identity",
        "determinism",
        "reproduction",
    }
)
PROVENANCE_ARTIFACT_KEYS = frozenset({"path", "sha256"})
REPRODUCTION_REQUIRED_KEYS = frozenset(
    {
        "renderer",
        "config",
        "seed",
        "donors",
        "controls",
        "argv",
        "environment",
        "timeout_seconds",
        "read_closure_runner",
        "pixel_auditor",
        "pixel_audit",
    }
)
PERSISTENT_RECEIPT_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "id",
        "job_id",
        "status",
        "source_temporary_emission_sha256",
        "source_emission_created_at",
        "authorized_by",
        "created_at",
        "temporary_review_only",
        "previously_accepted",
        "golden_accepted",
        "acceptance_inferred",
        "raw",
        "candidate",
        "views",
        "blind_packet",
        "metrics",
        "geometry",
        "identity",
        "pixel_audit",
        "reproduction",
        "independent_replay_2",
        "determinism",
        "root_review",
        "automated_gates",
        "failed_gates",
        "vision_handoff",
    }
)
PERSISTENT_AUDIT_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "id",
        "job_id",
        "status",
        "image_path",
        "image_sha256",
        "acceptance_threshold",
        "decision_authority",
        "acceptance_inferred",
        "golden_accepted",
        "raw",
        "candidate",
        "provenance_receipt",
        "root_review",
        "views",
        "blind_packet",
        "metrics",
        "geometry",
        "identity",
        "pixel_audit",
        "reproduction",
        "independent_replay_2",
        "determinism",
        "automated_gates",
        "failed_gates",
        "authorized_by",
        "source_emission_created_at",
        "created_at",
    }
)
BLIND_PACKET_VIEW_IDS = (
    "native",
    "full25",
    "full50",
    "highland200",
    "highland400",
)
PHASE4_IMMEDIATE_FAILURE_IDS = (
    "eight-system-topology",
    "side-view-or-shared-projection",
    "panel-seam-or-body-halo",
    "white-particle-pill-hole-or-crater",
    "root-river-vein-fingerprint-or-contour",
    "fern-fishbone-dash-bundle-or-repetition",
    "no-200-to-400-information-gain",
    "protected-geometry-difference",
)
BLIND_REVIEW_ROLE_PREFIXES = (
    "independent-vision-review-a/",
    "independent-vision-review-b/",
)
ROOT_REVIEW_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "job_id",
        "created_at",
        "reviewer",
        "status",
        "review_mode",
        "candidate",
        "native",
        "review_views",
        "immediate_failures",
        "acceptance_threshold",
        "total_score",
        "decision",
        "authorizes_blind_review",
        "golden_reference",
        "acceptance_inferred",
        "summary",
    }
)
ROOT_REVIEW_VIEW_KEYS = frozenset({"id", "path", "sha256", "complete", "evidence"})

METRIC_THRESHOLDS = {
    "coverage_50_min": 360,
    "coverage_25_min": 334,
    "quiet_fraction_min": 0.905,
    "dash_bundle_pairs_exact": 0,
    "orientation_coherence_max": 0.16,
    "texture_ratio_4_min": 0.61,
    "texture_ratio_8_min": 0.75,
    "texture_ratio_8_max": 1.22,
}

AUTOMATED_GATE_NAMES = frozenset(
    {
        "coverage_50_min_360",
        "coverage_25_min_334",
        "quiet_fraction_min_0_905",
        "dash_bundle_pairs_zero",
        "orientation_coherence_max_0_16",
        "texture_ratio_4_min_0_61",
        "texture_ratio_8_range_0_75_1_22",
        "selected_component_count_exact_8",
        "outside_permission_zero",
        "protected_features_zero",
        "road_calm_18px_zero",
        "deterministic_replay_byte_exact",
        "root_review_accepted_94_no_failures",
        "candidate_not_known_non_golden",
        "candidate_not_previously_accepted",
    }
)

# Every item below is an authority, donor, rejected candidate, or control image;
# none is itself eligible to become the full-map Golden master.
KNOWN_NON_GOLDEN_SOURCE_SHA256 = {
    "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882": (
        "rejected v18/current candidate"
    ),
    "67b9ffeca574ca144e8c54fc67b7f5c2757a02422b1fab73135efb89ad8cc156": (
        "v45 calm-spacing source"
    ),
    "98aa5a14d7b1c2ba413e604403057ec05d0787cfd35d3c9dd770e88b850488aa": (
        "v47 generated-layout source"
    ),
    "c7fcd3da5fba6fe08f10fd1e0fe16bdb2884a0a04386de828f923d660de8f1a2": (
        "v38 copperplate material source"
    ),
    "b4fc951af5d29c78bb98b5ee5007395b5fc3c1addc7070d76ac8074545259837": (
        "H4 palette/parchment source"
    ),
    "2ae715fc2800a03adde89a26bd3d663f1bafe179ed845cef09dd616ed1453d3f": (
        "v55 topographic contour source"
    ),
    "c168f1419d04ffaff313433064bab2b12844041e3845540c8bb6e29c2ef317c4": (
        "v52 eight-ridge control atlas"
    ),
    "cce887425642637e0b031c4cc527f59c019f8693d233abbaaf257cadb700201e": (
        "v64 integrated-relief donor"
    ),
    "79d8396575b3a046e39656fbc614648e3e28a930cb3de4c64620d62c34bab656": (
        "v159 scalar-relief donor"
    ),
    "d576ed7ec0e5dfc7ff4806c7e35ebb93a4a7a25dc98abf1aaeee84c6af349aab": (
        "v169 direction-neutral microterrain donor"
    ),
    "8cb7792a725896bab24e032c8d9fadf8cbdf1bf1372f6901de182bf20f493b02": (
        "v170 quiet integrated-ground donor"
    ),
    "152fe9231812e6acbc6292181de40e17fedceac3adc01a46a288fd873546d5ff": (
        "v171 clean scalar-relief donor"
    ),
    "e69deee1e5ba91c1bbcb9aa35dda036c8a7ae1cd07b90c94d1aede0beb957b4a": (
        "v172 natural-highland relief donor"
    ),
    "4a1e7d35729546a4f111ccdf52e198fe936f8087b12e565757c9792e8945052f": (
        "v174 detailed scalar-relief donor"
    ),
    "c8554ec066caecee9f3fd428c5c1c6ca3c784c568a1547f717883440cb83196f": (
        "field-margin donor v2"
    ),
}


class K3GoldenPromotionV2Error(RuntimeError):
    """Raised before invalid evidence can change the production manifest."""


class ManifestCommitStateUnknownError(K3GoldenPromotionV2Error):
    """Raised when manifest replacement may have committed but cannot be proven."""

    def __init__(
        self,
        *,
        manifest: str,
        reason: str,
        debris: tuple[str, ...],
        cleanup_failures: tuple[str, ...],
    ) -> None:
        self.status = "unknown"
        self.manifest = manifest
        self.reason = reason
        self.debris = debris
        self.cleanup_failures = cleanup_failures
        cleanup_status = "complete" if not cleanup_failures else "debris"
        super().__init__(
            "manifest commit state is unknown; persistent evidence was retained "
            "for manual reconciliation: "
            f"manifest={manifest}, reason={reason}, "
            f"cleanup_status={cleanup_status}, debris={list(debris)!r}, "
            f"cleanup_failures={list(cleanup_failures)!r}"
        )


@dataclass(frozen=True)
class PromotionPaths:
    manifest: Path
    raw: Path
    final: Path
    receipt: Path
    root_review: Path
    audit: Path
    evidence_dir: Path
    final_receipt: Path
    blind_packet_dir: Path


@dataclass(frozen=True)
class ManifestCommitResult:
    """Outcome after the manifest replacement has crossed its commit point."""

    cleanup_status: str
    debris: tuple[str, ...]
    cleanup_failures: tuple[str, ...]

    def document(self) -> dict[str, Any]:
        return {
            "status": "committed",
            "cleanup_status": self.cleanup_status,
            "debris": list(self.debris),
            "cleanup_failures": list(self.cleanup_failures),
        }


@dataclass(frozen=True)
class ValidatedEmission:
    emission: BoundArtifact
    document: dict[str, Any]
    candidate: BoundArtifact
    replay: BoundArtifact
    views: dict[str, BoundArtifact]
    root_review: BoundArtifact
    root_document: dict[str, Any]
    reproduction: dict[str, Any]
    pixel_audit: dict[str, Any]

    def source_bindings(self) -> tuple[BoundArtifact, ...]:
        return (
            self.emission,
            self.candidate,
            self.replay,
            *self.views.values(),
            self.root_review,
            self.reproduction["renderer"],
            self.reproduction["config"],
            self.reproduction["read_closure_runner"],
            self.reproduction["pixel_auditor"],
            *self.reproduction["donors"],
            *self.reproduction["controls"],
        )


DEFAULT_PATHS = PromotionPaths(
    manifest=REPO_ROOT / "world/map-production/production-manifest.json",
    raw=REPO_ROOT
    / "world/map-production/candidates/style-candidate-k-v3-golden-v2-raw.png",
    final=REPO_ROOT
    / "world/map-production/candidates/style-candidate-k-v3-golden-v2.png",
    receipt=REPO_ROOT
    / "world/map-production/prompts/style-candidate-k-v3-golden-v2.provenance-receipt.json",
    root_review=REPO_ROOT
    / "world/map-production/qa/style-candidate-k-v3-golden-v2-root-review.json",
    audit=REPO_ROOT
    / "world/map-production/qa/automated/style-candidate-k-v3-golden-v2.json",
    evidence_dir=REPO_ROOT
    / "world/map-production/qa/evidence/style-candidate-k-v3-golden-v2",
    final_receipt=REPO_ROOT
    / "world/map-production/prompts/style-candidate-k-v3-golden-v2.acceptance-receipt.json",
    blind_packet_dir=REPO_ROOT / "world/map-production/qa/blind-packets/phase4-k3-v2",
)
DEFAULT_REVIEW_A = (
    REPO_ROOT / "world/map-production/qa/style-candidate-k-v3-golden-v2-review-a.json"
)
DEFAULT_REVIEW_B = (
    REPO_ROOT / "world/map-production/qa/style-candidate-k-v3-golden-v2-review-b.json"
)


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def _strict_json_object(binding: BoundArtifact, *, label: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-standard numeric constant {value!r}")

    try:
        value = json.loads(binding.data.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise K3GoldenPromotionV2Error(
            f"{label} is not strict UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise K3GoldenPromotionV2Error(f"{label} must contain a JSON object")
    return value


def _require_exact_keys(
    value: Any, expected: set[str], *, label: str
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise K3GoldenPromotionV2Error(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise K3GoldenPromotionV2Error(
            f"{label} keys must be exact; missing={missing}, extra={extra}"
        )
    return value


def _require_timestamp(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise K3GoldenPromotionV2Error(f"{label} must be an RFC 3339 string")
    try:
        parse_rfc3339(value)
    except ValueError as exc:
        raise K3GoldenPromotionV2Error(f"{label} {exc}") from exc
    return value


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _same_path(left: str | Path, right: str | Path) -> bool:
    def resolve(value: str | Path) -> Path:
        path = Path(value)
        return (path if path.is_absolute() else REPO_ROOT / path).resolve()

    return os.path.normcase(os.fspath(resolve(left))) == os.path.normcase(
        os.fspath(resolve(right))
    )


def _assert_temp_binding(binding: BoundArtifact, *, label: str) -> None:
    temp_root = (REPO_ROOT / "tmp/map-production").resolve()
    try:
        binding.path.resolve().relative_to(temp_root)
    except ValueError as exc:
        raise K3GoldenPromotionV2Error(
            f"{label} must stay under TEMP namespace {temp_root}"
        ) from exc


def _bind_source_record(record: Any, *, label: str) -> BoundArtifact:
    record = _require_exact_keys(record, set(SOURCE_ARTIFACT_KEYS), label=label)
    raw_path = record["path"]
    digest = record["sha256"]
    if not isinstance(raw_path, str):
        raise K3GoldenPromotionV2Error(f"{label}.path must be a string")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or digest != digest.lower()
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise K3GoldenPromotionV2Error(f"{label}.sha256 must be a lowercase SHA-256")
    try:
        binding = bind_file(raw_path, label=label, trackable=False)
    except (BoundArtifactError, ReleasePathError) as exc:
        raise K3GoldenPromotionV2Error(str(exc)) from exc
    _assert_temp_binding(binding, label=label)
    if binding.sha256 != digest:
        raise K3GoldenPromotionV2Error(
            f"{label} SHA-256 mismatch: emission={digest}, actual={binding.sha256}"
        )
    if record["bytes"] != len(binding.data):
        raise K3GoldenPromotionV2Error(f"{label}.bytes is stale")
    if record["mode"] != "RGB":
        raise K3GoldenPromotionV2Error(f"{label}.mode must be RGB")
    return binding


def _bind_provenance_record(record: Any, *, label: str) -> BoundArtifact:
    """Bind one tracked renderer/config/input authority by path and SHA-256."""

    record = _require_exact_keys(record, set(PROVENANCE_ARTIFACT_KEYS), label=label)
    path, digest = _artifact_reference(record, label=label)
    try:
        binding = bind_file(path, label=label, trackable=True)
    except (BoundArtifactError, ReleasePathError) as exc:
        raise K3GoldenPromotionV2Error(str(exc)) from exc
    if binding.sha256 != digest:
        raise K3GoldenPromotionV2Error(
            f"{label} SHA-256 mismatch: record={digest}, actual={binding.sha256}"
        )
    return binding


def _canonical_reproduction_argv(
    *,
    renderer: BoundArtifact,
    config: BoundArtifact,
    seed: str | int,
    donors: list[BoundArtifact],
    controls: list[BoundArtifact],
) -> list[str]:
    """Return the only accepted, portable renderer command grammar."""

    argv = [
        PYTHON_RUNTIME_TOKEN,
        renderer.relative,
        "--config",
        config.relative,
        "--seed",
        str(seed),
    ]
    for donor in donors:
        argv.extend(("--donor", donor.relative))
    for control in controls:
        argv.extend(("--control", control.relative))
    argv.extend(("--output", OUTPUT_TOKEN))
    return argv


def _validate_reproduction_contract(document: dict[str, Any]) -> dict[str, Any]:
    """Validate the complete, shell-free renderer invocation authority.

    The emission may live in TEMP, but every authority required to make it must
    already be an immutable repository artifact.  This is deliberately strict:
    a candidate is not reproducible merely because its output/replay files match.
    """

    reproduction = _require_exact_keys(
        document["reproduction"],
        set(REPRODUCTION_REQUIRED_KEYS),
        label="reproduction",
    )
    renderer = _bind_provenance_record(reproduction["renderer"], label="renderer")
    config = _bind_provenance_record(reproduction["config"], label="renderer config")
    seed = reproduction["seed"]
    if not isinstance(seed, (str, int)) or isinstance(seed, bool) or not str(seed):
        raise K3GoldenPromotionV2Error(
            "reproduction.seed must be a non-empty string or integer"
        )
    if reproduction["environment"] != FIXED_RENDERER_ENVIRONMENT:
        raise K3GoldenPromotionV2Error(
            "reproduction.environment must equal the fixed renderer environment"
        )
    timeout_seconds = reproduction["timeout_seconds"]
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or timeout_seconds != RENDERER_TIMEOUT_SECONDS
    ):
        raise K3GoldenPromotionV2Error(
            f"reproduction.timeout_seconds must equal {RENDERER_TIMEOUT_SECONDS}"
        )

    groups: dict[str, list[BoundArtifact]] = {}
    for group in ("donors", "controls"):
        records = reproduction[group]
        if not isinstance(records, list) or not records:
            raise K3GoldenPromotionV2Error(
                f"reproduction.{group} must be a non-empty array"
            )
        bindings = [
            _bind_provenance_record(record, label=f"reproduction.{group}[{index}]")
            for index, record in enumerate(records)
        ]
        if len({binding.identity for binding in bindings}) != len(bindings):
            raise K3GoldenPromotionV2Error(
                f"reproduction.{group} may not repeat an input"
            )
        groups[group] = bindings

    auditor_binding = _bind_provenance_record(
        reproduction["pixel_auditor"], label="independent pixel auditor"
    )
    if not _same_path(auditor_binding.path, Path(pixel_auditor.__file__).resolve()):
        raise K3GoldenPromotionV2Error(
            "reproduction.pixel_auditor must bind the executing independent auditor"
        )
    read_closure_runner = _bind_provenance_record(
        reproduction["read_closure_runner"], label="renderer read-closure runner"
    )
    if not _same_path(read_closure_runner.path, READ_CLOSURE_RUNNER_PATH):
        raise K3GoldenPromotionV2Error(
            "reproduction.read_closure_runner must bind the executing tracked runner"
        )
    audit_inputs = _require_exact_keys(
        reproduction["pixel_audit"],
        {"baseline", "control", "masks"},
        label="reproduction.pixel_audit",
    )
    audit_baseline = _bind_provenance_record(
        audit_inputs["baseline"], label="independent audit baseline"
    )
    audit_control = _bind_provenance_record(
        audit_inputs["control"], label="independent audit control"
    )
    audit_mask_records = _require_exact_keys(
        audit_inputs["masks"],
        set(pixel_auditor.MASK_NAMES),
        label="reproduction.pixel_audit.masks",
    )
    audit_masks = {
        name: _bind_provenance_record(
            audit_mask_records[name], label=f"independent audit mask {name}"
        )
        for name in pixel_auditor.MASK_NAMES
    }
    declared_control_identities = {binding.identity for binding in groups["controls"]}
    required_audit_inputs = {audit_baseline.identity, audit_control.identity} | {
        binding.identity for binding in audit_masks.values()
    }
    if not required_audit_inputs <= declared_control_identities:
        raise K3GoldenPromotionV2Error(
            "independent audit baseline/control/masks must all be declared renderer controls"
        )

    argv = reproduction["argv"]
    if not isinstance(argv, list) or not all(
        isinstance(item, str) and item for item in argv
    ):
        raise K3GoldenPromotionV2Error(
            "reproduction.argv must be a non-empty string argv"
        )
    if renderer.path.suffix.casefold() != ".py":
        raise K3GoldenPromotionV2Error(
            "reproduction.renderer must be a workspace Python renderer"
        )
    expected_argv = _canonical_reproduction_argv(
        renderer=renderer,
        config=config,
        seed=seed,
        donors=groups["donors"],
        controls=groups["controls"],
    )
    if argv != expected_argv:
        raise K3GoldenPromotionV2Error(
            "reproduction.argv must exactly match the portable declared-input grammar; "
            f"expected={expected_argv!r}"
        )
    return {
        "renderer": renderer,
        "config": config,
        "seed": seed,
        "donors": groups["donors"],
        "controls": groups["controls"],
        "argv": list(argv),
        "environment": dict(FIXED_RENDERER_ENVIRONMENT),
        "timeout_seconds": timeout_seconds,
        "read_closure_runner": read_closure_runner,
        "pixel_auditor": auditor_binding,
        "pixel_audit": {
            "baseline": audit_baseline,
            "control": audit_control,
            "masks": audit_masks,
        },
    }


def _execute_fresh_replays(
    reproduction: dict[str, Any], *, candidate: BoundArtifact
) -> tuple[BoundArtifact, BoundArtifact]:
    """Run the approved renderer twice, in fresh TEMP paths, and bind both bytes."""

    output_root = REPO_ROOT / "tmp/map-production/k3-golden-v2-replay"
    output_root.mkdir(parents=True, exist_ok=True)
    outputs: list[BoundArtifact] = []
    temporary_runs: list[tempfile.TemporaryDirectory[str]] = []
    try:
        for index in range(2):
            temporary = tempfile.TemporaryDirectory(
                prefix=f"run-{index + 1}-", dir=output_root
            )
            temporary_runs.append(temporary)
            output = Path(temporary.name) / "replay.png"
            renderer_argv = list(reproduction["argv"][2:])
            # The validated grammar fixes {output} to the final position.
            # Positional replacement preserves a seed whose literal value
            # happens to equal either reserved token.
            renderer_argv[-1] = str(output)
            argv = [
                sys.executable,
                reproduction["read_closure_runner"].relative,
                "--workspace-root",
                str(REPO_ROOT),
                "--renderer",
                reproduction["renderer"].relative,
                "--output",
                str(output),
            ]
            for declared_read in (
                reproduction["config"],
                *reproduction["donors"],
                *reproduction["controls"],
            ):
                argv.extend(("--allow-read", declared_read.relative))
            argv.extend(("--", *renderer_argv))
            environment = dict(reproduction["environment"])
            # Windows needs these two installation roots to initialize parts
            # of the runtime. No user/session/application variables cross the
            # renderer boundary.
            for key in PLATFORM_RUNTIME_ENVIRONMENT_KEYS:
                value = os.environ.get(key)
                if value:
                    environment[key] = value
            try:
                subprocess.run(
                    argv,
                    cwd=REPO_ROOT,
                    check=True,
                    shell=False,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    timeout=reproduction["timeout_seconds"],
                )
            except subprocess.TimeoutExpired as exc:
                raise K3GoldenPromotionV2Error(
                    f"fresh deterministic replay {index + 1} timed out after "
                    f"{reproduction['timeout_seconds']} seconds"
                ) from exc
            except (OSError, subprocess.CalledProcessError) as exc:
                raise K3GoldenPromotionV2Error(
                    f"fresh deterministic replay {index + 1} failed: {exc}"
                ) from exc
            try:
                binding = bind_file(
                    output,
                    label=f"fresh deterministic replay {index + 1}",
                    trackable=False,
                )
            except (BoundArtifactError, ReleasePathError) as exc:
                raise K3GoldenPromotionV2Error(str(exc)) from exc
            _assert_temp_binding(
                binding, label=f"fresh deterministic replay {index + 1}"
            )
            _image_from_binding(
                binding,
                label=f"fresh deterministic replay {index + 1}",
                expected_size=EXPECTED_SIZE,
            ).close()
            if binding.sha256 != candidate.sha256 or binding.data != candidate.data:
                raise K3GoldenPromotionV2Error(
                    f"fresh deterministic replay {index + 1} is not byte-identical to the candidate"
                )
            outputs.append(binding)
    finally:
        for temporary in reversed(temporary_runs):
            temporary.cleanup()
    return outputs[0], outputs[1]


def _independent_pixel_audit(
    candidate: BoundArtifact, reproduction: dict[str, Any]
) -> dict[str, Any]:
    """Recompute every fixed pixel claim with the separately SHA-bound auditor."""

    audit_inputs = reproduction["pixel_audit"]
    try:
        report = pixel_auditor.audit_candidate(
            candidate,
            audit_inputs["baseline"],
            audit_inputs["control"],
            mask_bindings=audit_inputs["masks"],
        )
    except pixel_auditor.GoldenV2PixelAuditError as exc:
        raise K3GoldenPromotionV2Error(
            f"independent Golden-v2 pixel audit failed: {exc}"
        ) from exc
    report = _require_exact_keys(
        report,
        set(pixel_auditor.REPORT_REQUIRED_KEYS),
        label="independent Golden-v2 pixel audit report",
    )
    expected_identity = {
        "schema_version": pixel_auditor.SCHEMA_VERSION,
        "id": pixel_auditor.REPORT_ID,
        "algorithm": pixel_auditor.ALGORITHM,
        "control_sha256": audit_inputs["control"].sha256,
        "candidate_sha256": candidate.sha256,
        "baseline_sha256": audit_inputs["baseline"].sha256,
    }
    for field, expected in expected_identity.items():
        if report[field] != expected:
            raise K3GoldenPromotionV2Error(
                f"independent Golden-v2 pixel audit {field} is not bound to its input"
            )
    expected_mask_sha256 = {
        name: audit_inputs["masks"][name].sha256 for name in pixel_auditor.MASK_NAMES
    }
    if report["mask_sha256"] != expected_mask_sha256:
        raise K3GoldenPromotionV2Error(
            "independent Golden-v2 pixel audit masks are not bound to their inputs"
        )
    report_geometry = _require_exact_keys(
        report["geometry"],
        {"selected_component_count"},
        label="independent Golden-v2 geometry",
    )
    geometry_proof = _require_exact_keys(
        report["geometry_proof"],
        {
            "algorithm",
            "thresholds",
            "mask_component_count",
            "valid_component_count",
            "components",
        },
        label="independent Golden-v2 geometry proof",
    )
    if (
        geometry_proof["algorithm"] != pixel_auditor.GEOMETRY_ALGORITHM
        or geometry_proof["thresholds"] != pixel_auditor.GEOMETRY_THRESHOLDS
    ):
        raise K3GoldenPromotionV2Error(
            "independent Golden-v2 geometry proof algorithm/thresholds drifted"
        )
    components = geometry_proof["components"]
    if (
        not isinstance(components, list)
        or geometry_proof["mask_component_count"] != len(components)
        or geometry_proof["valid_component_count"]
        != report_geometry["selected_component_count"]
    ):
        raise K3GoldenPromotionV2Error(
            "independent Golden-v2 geometry proof component totals are inconsistent"
        )
    valid_components = 0
    for component_id, component in enumerate(components, start=1):
        component = _require_exact_keys(
            component,
            {
                "component_id",
                "mask_pixels",
                "changed_pixels",
                "changed_fraction",
                "mask_bbox_xyxy",
                "changed_bbox_xyxy",
                "changed_x_span_fraction",
                "changed_y_span_fraction",
                "peak_channel_delta",
                "valid",
            },
            label=f"independent Golden-v2 geometry component {component_id}",
        )
        mask_pixels = component["mask_pixels"]
        changed_pixels = component["changed_pixels"]
        peak_delta = component["peak_channel_delta"]
        mask_bbox = component["mask_bbox_xyxy"]
        changed_bbox = component["changed_bbox_xyxy"]
        if (
            not isinstance(mask_bbox, list)
            or len(mask_bbox) != 4
            or any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in mask_bbox
            )
            or mask_bbox[0] < 0
            or mask_bbox[1] < 0
            or mask_bbox[2] <= mask_bbox[0]
            or mask_bbox[3] <= mask_bbox[1]
        ):
            raise K3GoldenPromotionV2Error(
                "independent Golden-v2 geometry component mask bbox is invalid"
            )
        if changed_pixels:
            if (
                not isinstance(changed_bbox, list)
                or len(changed_bbox) != 4
                or any(
                    not isinstance(value, int) or isinstance(value, bool)
                    for value in changed_bbox
                )
                or changed_bbox[0] < mask_bbox[0]
                or changed_bbox[1] < mask_bbox[1]
                or changed_bbox[2] > mask_bbox[2]
                or changed_bbox[3] > mask_bbox[3]
                or changed_bbox[2] <= changed_bbox[0]
                or changed_bbox[3] <= changed_bbox[1]
            ):
                raise K3GoldenPromotionV2Error(
                    "independent Golden-v2 geometry component changed bbox is invalid"
                )
            changed_x_span_fraction = (changed_bbox[2] - changed_bbox[0]) / (
                mask_bbox[2] - mask_bbox[0]
            )
            changed_y_span_fraction = (changed_bbox[3] - changed_bbox[1]) / (
                mask_bbox[3] - mask_bbox[1]
            )
        else:
            if changed_bbox is not None:
                raise K3GoldenPromotionV2Error(
                    "independent Golden-v2 empty component delta has a bbox"
                )
            changed_x_span_fraction = 0.0
            changed_y_span_fraction = 0.0
        if (
            component["component_id"] != component_id
            or not isinstance(mask_pixels, int)
            or isinstance(mask_pixels, bool)
            or mask_pixels <= 0
            or not isinstance(changed_pixels, int)
            or isinstance(changed_pixels, bool)
            or not 0 <= changed_pixels <= mask_pixels
            or not isinstance(peak_delta, int)
            or isinstance(peak_delta, bool)
            or peak_delta < 0
            or component["changed_fraction"] != round(changed_pixels / mask_pixels, 6)
            or component["changed_x_span_fraction"] != round(changed_x_span_fraction, 6)
            or component["changed_y_span_fraction"] != round(changed_y_span_fraction, 6)
            or not isinstance(component["valid"], bool)
        ):
            raise K3GoldenPromotionV2Error(
                "independent Golden-v2 geometry component evidence is invalid"
            )
        expected_valid = (
            changed_pixels
            >= pixel_auditor.GEOMETRY_THRESHOLDS["minimum_changed_pixels"]
            and changed_pixels / mask_pixels
            >= pixel_auditor.GEOMETRY_THRESHOLDS["minimum_changed_fraction"]
            and changed_x_span_fraction
            >= pixel_auditor.GEOMETRY_THRESHOLDS["minimum_changed_x_span_fraction"]
            and changed_y_span_fraction
            >= pixel_auditor.GEOMETRY_THRESHOLDS["minimum_changed_y_span_fraction"]
            and peak_delta
            >= pixel_auditor.GEOMETRY_THRESHOLDS["minimum_peak_channel_delta"]
        )
        if component["valid"] is not expected_valid:
            raise K3GoldenPromotionV2Error(
                "independent Golden-v2 geometry component validity is inconsistent"
            )
        valid_components += int(expected_valid)
    if valid_components != geometry_proof["valid_component_count"]:
        raise K3GoldenPromotionV2Error(
            "independent Golden-v2 geometry proof valid total is inconsistent"
        )
    if report.get("passed") is not True or report.get("failed_gates") != []:
        raise K3GoldenPromotionV2Error(
            "independent Golden-v2 pixel audit did not pass every fixed gate: "
            f"{report.get('failed_gates')!r}"
        )
    if (
        not isinstance(report.get("gates"), dict)
        or set(report["gates"]) != set(pixel_auditor.GATE_NAMES)
        or not all(value is True for value in report["gates"].values())
    ):
        raise K3GoldenPromotionV2Error(
            "independent Golden-v2 pixel audit gate map is incomplete"
        )
    return report


def _assert_pixel_claims_match(
    document: dict[str, Any], report: dict[str, Any], *, label: str
) -> None:
    for field in ("metrics", "geometry", "identity"):
        if document.get(field) != report[field]:
            raise K3GoldenPromotionV2Error(
                f"{label}.{field} does not equal independently recomputed pixels"
            )


def _image_from_binding(
    binding: BoundArtifact,
    *,
    label: str,
    expected_size: tuple[int, int],
) -> Image.Image:
    try:
        with Image.open(BytesIO(binding.data)) as opened:
            opened.load()
            if opened.format != "PNG":
                raise K3GoldenPromotionV2Error(f"{label} must be PNG")
            if opened.mode != "RGB" or opened.getbands() != ("R", "G", "B"):
                raise K3GoldenPromotionV2Error(f"{label} must be native RGB")
            if opened.size != expected_size:
                raise K3GoldenPromotionV2Error(
                    f"{label} size must be {expected_size}, found {opened.size}"
                )
            if opened.info.get("icc_profile") is not None:
                raise K3GoldenPromotionV2Error(f"{label} must be untagged RGB")
            if "transparency" in opened.info:
                raise K3GoldenPromotionV2Error(f"{label} may not contain transparency")
            return opened.copy()
    except OSError as exc:
        raise K3GoldenPromotionV2Error(f"{label} is not a readable PNG: {exc}") from exc


def _assert_source_image_record(
    record: dict[str, Any],
    binding: BoundArtifact,
    *,
    label: str,
    expected_size: tuple[int, int],
) -> Image.Image:
    if record.get("size") != list(expected_size):
        raise K3GoldenPromotionV2Error(f"{label}.size must be {list(expected_size)!r}")
    return _image_from_binding(binding, label=label, expected_size=expected_size)


def _expected_view(candidate: Image.Image, name: str) -> Image.Image:
    crop, size = VIEW_DEFINITIONS[name]
    working = candidate.crop(crop) if crop is not None else candidate.copy()
    try:
        return working.resize(size, Image.Resampling.LANCZOS)
    finally:
        working.close()


def _assert_exact_view_pixels(
    candidate: Image.Image,
    name: str,
    view: Image.Image,
) -> None:
    expected = _expected_view(candidate, name)
    try:
        if view.size != expected.size or view.tobytes() != expected.tobytes():
            raise K3GoldenPromotionV2Error(
                f"emission view {name!r} is not the exact canonical candidate view"
            )
    finally:
        expected.close()


def _artifact_reference(record: Any, *, label: str) -> tuple[str, str]:
    if not isinstance(record, dict):
        raise K3GoldenPromotionV2Error(f"{label} must be an artifact object")
    path = record["path"]
    digest = record["sha256"]
    if not isinstance(path, str):
        raise K3GoldenPromotionV2Error(f"{label}.path must be a string")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or digest != digest.lower()
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise K3GoldenPromotionV2Error(f"{label}.sha256 must be a lowercase SHA-256")
    return path, digest


def _assert_reference_matches(
    record: Any, binding: BoundArtifact, *, label: str
) -> None:
    path, digest = _artifact_reference(record, label=label)
    if not _same_path(path, binding.path) or digest != binding.sha256:
        raise K3GoldenPromotionV2Error(f"{label} does not bind the expected artifact")


def _assert_metric_contract(
    *,
    metrics: Any,
    geometry: Any,
    identity: Any,
    determinism: Any,
    replay: BoundArtifact,
    candidate: BoundArtifact,
    persistent: bool,
) -> None:
    metrics = _require_exact_keys(
        metrics,
        {
            "coverage_50",
            "coverage_25",
            "quiet_fraction",
            "dash_bundle_pairs",
            "orientation_coherence",
            "texture_inside_to_outside_ratio",
        },
        label="metrics",
    )
    for key in (
        "coverage_50",
        "coverage_25",
        "quiet_fraction",
        "dash_bundle_pairs",
        "orientation_coherence",
    ):
        if not _is_number(metrics[key]):
            raise K3GoldenPromotionV2Error(
                f"metrics.{key} must be finite numeric evidence"
            )
    texture = _require_exact_keys(
        metrics["texture_inside_to_outside_ratio"], {"4", "8"}, label="texture ratios"
    )
    if not all(_is_number(texture[key]) for key in ("4", "8")):
        raise K3GoldenPromotionV2Error("texture ratios must be finite numeric evidence")
    gates = {
        "coverage_50": metrics["coverage_50"] >= 360,
        "coverage_25": metrics["coverage_25"] >= 334,
        "quiet_fraction": metrics["quiet_fraction"] >= 0.905,
        "dash_bundle_pairs": metrics["dash_bundle_pairs"] == 0,
        "orientation_coherence": metrics["orientation_coherence"] <= 0.16,
        "texture_ratio_4": texture["4"] >= 0.61,
        "texture_ratio_8": 0.75 <= texture["8"] <= 1.22,
    }
    failed = sorted(name for name, passed in gates.items() if not passed)
    if failed:
        raise K3GoldenPromotionV2Error(f"fixed robust metric gates failed: {failed}")

    geometry = _require_exact_keys(
        geometry, {"selected_component_count"}, label="geometry"
    )
    count = geometry["selected_component_count"]
    if not isinstance(count, int) or isinstance(count, bool) or count != 8:
        raise K3GoldenPromotionV2Error(
            "geometry.selected_component_count must be exactly 8"
        )

    identity = _require_exact_keys(
        identity,
        {"outside_permission", "protected_features", "road_calm_18px"},
        label="identity",
    )
    for key, value in identity.items():
        if not isinstance(value, int) or isinstance(value, bool) or value != 0:
            raise K3GoldenPromotionV2Error(f"identity.{key} must be exactly zero")

    determinism = _require_exact_keys(
        determinism,
        {"independent_in_memory_builds", "replay", "byte_identical", "passed"},
        label="determinism",
    )
    if determinism["independent_in_memory_builds"] != 2:
        raise K3GoldenPromotionV2Error(
            "determinism.independent_in_memory_builds must be exactly 2"
        )
    if determinism["byte_identical"] is not True or determinism["passed"] is not True:
        raise K3GoldenPromotionV2Error(
            "deterministic replay must be passed and byte-identical"
        )
    if persistent:
        _require_exact_keys(
            determinism["replay"],
            {"path", "sha256"},
            label="determinism.replay",
        )
        _assert_reference_matches(
            determinism["replay"], replay, label="determinism.replay"
        )
    else:
        record = determinism["replay"]
        if not isinstance(record, dict):
            raise K3GoldenPromotionV2Error(
                "determinism.replay must be an artifact record"
            )
        if record.get("sha256") != replay.sha256 or not _same_path(
            record.get("path", ""), replay.path
        ):
            raise K3GoldenPromotionV2Error(
                "determinism.replay does not bind replay bytes"
            )
    if replay.sha256 != candidate.sha256 or replay.data != candidate.data:
        raise K3GoldenPromotionV2Error(
            "independent deterministic replay is not byte-identical to the candidate"
        )


def _validate_root_review(
    binding: BoundArtifact,
    document: dict[str, Any],
    *,
    candidate: BoundArtifact,
    views: dict[str, BoundArtifact],
) -> None:
    _require_exact_keys(document, set(ROOT_REVIEW_REQUIRED_KEYS), label="Root review")
    exact = {
        "schema_version": "1.0.0",
        "job_id": JOB_ID,
        "status": "complete",
        "review_mode": "root-authority",
        "acceptance_threshold": ACCEPTANCE_THRESHOLD,
        "decision": "accepted",
        "authorizes_blind_review": True,
        "golden_reference": False,
        "acceptance_inferred": False,
    }
    for field, expected in exact.items():
        if document.get(field) != expected:
            raise K3GoldenPromotionV2Error(f"Root review {field} must be {expected!r}")
    _require_timestamp(document["created_at"], label="Root review.created_at")
    if not isinstance(document["reviewer"], str) or not document["reviewer"].strip():
        raise K3GoldenPromotionV2Error("Root review.reviewer must be non-empty")
    if not isinstance(document["summary"], str) or not document["summary"].strip():
        raise K3GoldenPromotionV2Error("Root review.summary must be non-empty")
    score = document["total_score"]
    if (
        not isinstance(score, int)
        or isinstance(score, bool)
        or score < 94
        or score > 100
    ):
        raise K3GoldenPromotionV2Error("Root review.total_score must be 94..100")
    _require_exact_keys(
        document["candidate"], {"path", "sha256"}, label="Root review.candidate"
    )
    _require_exact_keys(
        document["native"], {"path", "sha256"}, label="Root review.native"
    )
    _assert_reference_matches(
        document["candidate"], candidate, label="Root review.candidate"
    )
    _assert_reference_matches(
        document["native"], views["native"], label="Root review.native"
    )

    review_views = document["review_views"]
    if not isinstance(review_views, list) or len(review_views) != len(VIEW_ORDER):
        raise K3GoldenPromotionV2Error(
            "Root review must contain exactly five review views"
        )
    for expected_name, item in zip(VIEW_ORDER, review_views):
        item = _require_exact_keys(
            item,
            set(ROOT_REVIEW_VIEW_KEYS),
            label=f"Root review view {expected_name}",
        )
        if item["id"] != expected_name or item["complete"] is not True:
            raise K3GoldenPromotionV2Error(
                f"Root review view order/completion is invalid at {expected_name}"
            )
        if not isinstance(item["evidence"], str) or not item["evidence"].strip():
            raise K3GoldenPromotionV2Error(
                f"Root review view {expected_name} requires evidence"
            )
        _assert_reference_matches(
            item, views[expected_name], label=f"Root review view {expected_name}"
        )

    failures = document["immediate_failures"]
    if not isinstance(failures, list) or not failures:
        raise K3GoldenPromotionV2Error(
            "Root review.immediate_failures must be non-empty"
        )
    identifiers: list[str] = []
    for index, item in enumerate(failures):
        item = _require_exact_keys(
            item,
            {"id", "detected", "evidence"},
            label=f"Root review immediate_failures[{index}]",
        )
        if (
            not isinstance(item["id"], str)
            or not item["id"].strip()
            or item["id"] in identifiers
        ):
            raise K3GoldenPromotionV2Error(
                "Root review immediate failure ids must be unique"
            )
        identifiers.append(item["id"])
        if item["detected"] is not False:
            raise K3GoldenPromotionV2Error("Root review contains an immediate failure")
        if not isinstance(item["evidence"], str) or not item["evidence"].strip():
            raise K3GoldenPromotionV2Error(
                "Root review immediate failures require evidence"
            )
    if tuple(identifiers) != PHASE4_IMMEDIATE_FAILURE_IDS:
        raise K3GoldenPromotionV2Error(
            "Root review immediate-failure checklist must exactly match Phase 4"
        )
    _assert_temp_binding(binding, label="Root review")


def _validate_emission(
    emission_path: Path,
    root_review_path: Path,
) -> ValidatedEmission:
    try:
        emission_binding = bind_file(
            emission_path, label="source emission", trackable=False
        )
        root_binding = bind_file(
            root_review_path, label="source Root review", trackable=False
        )
    except (BoundArtifactError, ReleasePathError) as exc:
        raise K3GoldenPromotionV2Error(str(exc)) from exc
    _assert_temp_binding(emission_binding, label="source emission")
    _assert_temp_binding(root_binding, label="source Root review")
    document = _strict_json_object(emission_binding, label="source emission")
    _require_exact_keys(
        document,
        set(EMISSION_REQUIRED_KEYS),
        label="source emission",
    )
    exact = {
        "schema_version": "1.0.0",
        "job_id": JOB_ID,
        "status": EMISSION_STATUS,
        "temporary_review_only": True,
        "previously_accepted": False,
        "golden_accepted": False,
    }
    for field, expected in exact.items():
        if document.get(field) != expected:
            raise K3GoldenPromotionV2Error(
                f"source emission {field} must be {expected!r}"
            )
    if not isinstance(document["id"], str) or not ID_PATTERN.fullmatch(document["id"]):
        raise K3GoldenPromotionV2Error(
            "source emission.id must be a production identifier"
        )
    _require_timestamp(document["created_at"], label="source emission.created_at")
    reproduction = _validate_reproduction_contract(document)

    candidate_record = document["candidate"]
    candidate = _bind_source_record(candidate_record, label="source candidate")
    candidate_image = _assert_source_image_record(
        candidate_record,
        candidate,
        label="source candidate",
        expected_size=EXPECTED_SIZE,
    )
    source = KNOWN_NON_GOLDEN_SOURCE_SHA256.get(candidate.sha256)
    if source is not None:
        candidate_image.close()
        raise K3GoldenPromotionV2Error(
            f"refusing known non-Golden donor/source bytes: {source}; sha256={candidate.sha256}"
        )
    pixel_audit_report = _independent_pixel_audit(candidate, reproduction)
    _assert_pixel_claims_match(document, pixel_audit_report, label="source emission")

    views_document = _require_exact_keys(
        document["views"], set(VIEW_ORDER), label="source emission.views"
    )
    view_bindings: dict[str, BoundArtifact] = {}
    try:
        for name in VIEW_ORDER:
            record = views_document[name]
            binding = _bind_source_record(record, label=f"source view {name}")
            view = _assert_source_image_record(
                record,
                binding,
                label=f"source view {name}",
                expected_size=VIEW_DEFINITIONS[name][1],
            )
            try:
                _assert_exact_view_pixels(candidate_image, name, view)
            finally:
                view.close()
            view_bindings[name] = binding

        determinism = _require_exact_keys(
            document["determinism"],
            {"independent_in_memory_builds", "replay", "byte_identical", "passed"},
            label="determinism",
        )
        # TEMP replay evidence is intentionally not trusted: prepare runs both
        # fresh renderer invocations after all candidate/input hashes are bound.
        replay_record = determinism["replay"]
        replay = _bind_source_record(replay_record, label="source legacy replay")
        _assert_source_image_record(
            replay_record,
            replay,
            label="source legacy replay",
            expected_size=EXPECTED_SIZE,
        ).close()
        _assert_metric_contract(
            metrics=document["metrics"],
            geometry=document["geometry"],
            identity=document["identity"],
            determinism=determinism,
            replay=replay,
            candidate=candidate,
            persistent=False,
        )
        root_document = _strict_json_object(root_binding, label="source Root review")
        _validate_root_review(
            root_binding,
            root_document,
            candidate=candidate,
            views=view_bindings,
        )
        if parse_rfc3339(root_document["created_at"]) < parse_rfc3339(
            document["created_at"]
        ):
            raise K3GoldenPromotionV2Error(
                "Root review must not predate the source emission"
            )
    finally:
        candidate_image.close()

    return ValidatedEmission(
        emission=emission_binding,
        document=document,
        candidate=candidate,
        replay=replay,
        views=view_bindings,
        root_review=root_binding,
        root_document=root_document,
        reproduction=reproduction,
        pixel_audit=pixel_audit_report,
    )


def _assert_not_previously_accepted(
    jobs: Any,
    candidate: BoundArtifact,
) -> None:
    if not isinstance(jobs, list):
        raise K3GoldenPromotionV2Error("production manifest must contain a jobs array")
    accepted_states = {"accepted", "tiled", "staging", "published"}
    for index, job in enumerate(jobs):
        if not isinstance(job, dict):
            continue
        master = job.get("master")
        same_sha = isinstance(master, dict) and master.get("sha256") == candidate.sha256
        history = job.get("history")
        was_accepted = isinstance(history, list) and any(
            isinstance(event, dict) and event.get("state") == "accepted"
            for event in history
        )
        if same_sha and (job.get("status") in accepted_states or was_accepted):
            raise K3GoldenPromotionV2Error(
                f"candidate SHA-256 was previously accepted by jobs[{index}]"
            )
    matches = [job for job in jobs if isinstance(job, dict) and job.get("id") == JOB_ID]
    if len(matches) > 1:
        raise K3GoldenPromotionV2Error(f"manifest duplicates exact JOB_ID {JOB_ID!r}")
    if matches:
        existing = matches[0]
        history = existing.get("history")
        was_accepted = isinstance(history, list) and any(
            isinstance(event, dict) and event.get("state") == "accepted"
            for event in history
        )
        if existing.get("status") in accepted_states or was_accepted:
            raise K3GoldenPromotionV2Error(
                f"refusing to replace previously accepted exact JOB_ID {JOB_ID!r}"
            )


def _write_new(path: Path, payload: bytes, *, label: str) -> str:
    try:
        resolved, relative = require_trackable_path(
            path, label=label, must_exist=False, require_file=True
        )
    except ReleasePathError as exc:
        raise K3GoldenPromotionV2Error(str(exc)) from exc
    if resolved.exists():
        if resolved.is_file() and resolved.read_bytes() == payload:
            return relative
        raise K3GoldenPromotionV2Error(
            f"refusing to overwrite non-identical {label}: {relative}"
        )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    opened = False
    try:
        with resolved.open("xb") as handle:
            opened = True
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise K3GoldenPromotionV2Error(
            f"refusing to overwrite {label}: {relative}"
        ) from exc
    except Exception:
        if opened:
            resolved.unlink(missing_ok=True)
        raise
    return relative


def _copy_new(
    source: BoundArtifact,
    destination: Path,
    *,
    label: str,
    bound_outputs: list[BoundArtifact],
    created_outputs: list[Path],
) -> dict[str, str]:
    existed = destination.exists()
    relative = _write_new(destination, source.data, label=label)
    try:
        copied = bind_file(destination, label=label, trackable=True)
        if copied.sha256 != source.sha256 or copied.data != source.data:
            raise K3GoldenPromotionV2Error(f"{label} changed during persistent copy")
        bound_outputs.append(copied)
        if not existed:
            created_outputs.append(destination)
        return {"path": relative, "sha256": copied.sha256}
    except Exception:
        if not existed:
            destination.unlink(missing_ok=True)
        raise


def _view_output_paths(paths: PromotionPaths) -> dict[str, Path]:
    return {name: paths.evidence_dir / f"review-{name}.png" for name in VIEW_ORDER}


def _replay_output_path(paths: PromotionPaths) -> Path:
    return paths.evidence_dir / "deterministic-replay.png"


def _second_replay_output_path(paths: PromotionPaths) -> Path:
    return paths.evidence_dir / "deterministic-replay-2.png"


def _bind_trackable_record(record: Any, *, label: str) -> BoundArtifact:
    path, digest = _artifact_reference(record, label=label)
    try:
        binding = bind_file(path, label=label, trackable=True)
    except (BoundArtifactError, ReleasePathError) as exc:
        raise K3GoldenPromotionV2Error(str(exc)) from exc
    if binding.sha256 != digest:
        raise K3GoldenPromotionV2Error(
            f"{label} SHA-256 mismatch: record={digest}, actual={binding.sha256}"
        )
    return binding


def _assert_persistent_graph(value: Any) -> tuple[BoundArtifact, ...]:
    """Bind every persistent path reference and reject TEMP/absolute aliases."""

    bindings: dict[str, BoundArtifact] = {}

    def visit(node: Any, location: str) -> None:
        if isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{location}[{index}]")
            return
        if not isinstance(node, dict):
            return
        for key, raw_path in node.items():
            folded = key.casefold()
            if not isinstance(raw_path, str) or not (
                folded == "path" or folded.endswith("_path")
            ):
                continue
            hash_key = (
                "sha256" if folded == "path" else key[: -len("_path")] + "_sha256"
            )
            claimed = node.get(hash_key)
            if not isinstance(claimed, str):
                raise K3GoldenPromotionV2Error(
                    f"{location}.{key} requires matching {hash_key} authority"
                )
            binding = _bind_trackable_record(
                {"path": raw_path, "sha256": claimed}, label=f"{location}.{key}"
            )
            existing = bindings.get(binding.identity)
            if existing is not None and existing.sha256 != binding.sha256:
                raise K3GoldenPromotionV2Error(
                    f"persistent graph binds conflicting bytes for {binding.relative}"
                )
            bindings[binding.identity] = binding
        for key, child in node.items():
            visit(child, f"{location}.{key}")

    visit(value, "persistent document")
    return tuple(bindings.values())


def _conditional_manifest_replace(
    path: Path,
    value: dict[str, Any],
    *,
    expected: BoundArtifact,
) -> ManifestCommitResult:
    """Atomically replace the manifest with a fail-closed three-state result.

    Only exact old manifest bytes prove that replacement did not commit and
    allow the caller to roll back newly created evidence. Exact replacement
    bytes prove commit. Unreadable or third-state bytes are explicitly unknown
    and retain all persistent evidence for manual reconciliation.
    """

    lock = path.with_name(f".{path.name}.k3-golden-v2.lock")
    temporary = path.with_name(f".{path.name}.k3-golden-v2-{uuid.uuid4().hex}.tmp")
    replacement_payload = _json_bytes(value)
    lock_fd: int | None = None
    commit_state = "uncommitted"
    failure: BaseException | None = None
    unknown_reason: str | None = None
    unknown_cause: BaseException | None = None
    try:
        try:
            lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise K3GoldenPromotionV2Error(
                f"manifest compare-and-swap lock already exists: {lock}"
            ) from exc
        os.write(lock_fd, expected.sha256.encode("ascii"))
        os.fsync(lock_fd)
        expected.assert_unchanged()
        current = bind_file(
            path, label="manifest compare-and-swap current", trackable=True
        )
        if current.sha256 != expected.sha256 or current.data != expected.data:
            raise K3GoldenPromotionV2Error(
                "manifest compare-and-swap failed: expected snapshot was replaced"
            )
        with temporary.open("xb") as handle:
            handle.write(replacement_payload)
            handle.flush()
            os.fsync(handle.fileno())
        expected.assert_unchanged()
        current = bind_file(
            path, label="manifest compare-and-swap final", trackable=True
        )
        if current.sha256 != expected.sha256 or current.data != expected.data:
            raise K3GoldenPromotionV2Error(
                "manifest compare-and-swap failed: expected SHA-256 is no longer current"
            )
        try:
            os.replace(temporary, path)
        except BaseException as replace_exc:
            # A signal or platform error can be delivered after the rename
            # syscall has committed. Only exact old bytes prove rollback is
            # safe. Unreadable or third-state bytes are explicitly unknown.
            try:
                committed_manifest = bind_file(
                    path, label="manifest post-replace confirmation", trackable=True
                )
            except BaseException as confirmation_exc:
                commit_state = "unknown"
                unknown_reason = "post-replace-manifest-read-failed"
                unknown_cause = confirmation_exc
            else:
                if committed_manifest.data == replacement_payload:
                    commit_state = "committed"
                elif committed_manifest.data == expected.data:
                    failure = replace_exc
                else:
                    commit_state = "unknown"
                    unknown_reason = "post-replace-manifest-bytes-indeterminate"
                    unknown_cause = replace_exc
        else:
            commit_state = "committed"
    except BaseException as exc:
        failure = exc

    debris: list[str] = []
    cleanup_failures: list[str] = []

    def debris_path(target: Path) -> str:
        try:
            return target.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        except BaseException:
            return os.fspath(target)

    try:
        temporary.unlink(missing_ok=True)
    except BaseException:
        debris.append(debris_path(temporary))
        cleanup_failures.append("manifest-temporary-unlink")
    if lock_fd is not None:
        try:
            os.close(lock_fd)
        except BaseException:
            cleanup_failures.append("manifest-lock-close")
        try:
            lock.unlink(missing_ok=True)
        except BaseException:
            debris.append(debris_path(lock))
            cleanup_failures.append("manifest-lock-unlink")

    if commit_state == "unknown":
        unknown = ManifestCommitStateUnknownError(
            manifest=debris_path(path),
            reason=unknown_reason or "post-replace-state-indeterminate",
            debris=tuple(debris),
            cleanup_failures=tuple(cleanup_failures),
        )
        if unknown_cause is not None:
            raise unknown from unknown_cause
        raise unknown
    if failure is not None:
        if cleanup_failures:
            failure.add_note(
                "manifest CAS cleanup was incomplete before commit: "
                + ", ".join(cleanup_failures)
            )
        if isinstance(failure, BoundArtifactError):
            converted = K3GoldenPromotionV2Error(str(failure))
            if cleanup_failures:
                converted.add_note(
                    "manifest CAS cleanup was incomplete before commit: "
                    + ", ".join(cleanup_failures)
                )
            raise converted from failure
        raise failure
    if commit_state != "committed":  # pragma: no cover - defensive state invariant
        raise K3GoldenPromotionV2Error("manifest CAS ended without a commit result")
    return ManifestCommitResult(
        cleanup_status="complete" if not cleanup_failures else "debris",
        debris=tuple(debris),
        cleanup_failures=tuple(cleanup_failures),
    )


def _assert_unchanged(bindings: Iterable[BoundArtifact]) -> None:
    try:
        assert_bindings_unchanged(bindings)
    except BoundArtifactError as exc:
        raise K3GoldenPromotionV2Error(str(exc)) from exc


def _validate_projected_manifest(path: Path, manifest: dict[str, Any]) -> None:
    scratch_parent = REPO_ROOT / "tmp/map-production"
    scratch_parent.mkdir(parents=True, exist_ok=True)
    scratch = scratch_parent / f".k3-golden-v2-manifest-{uuid.uuid4().hex}.json"
    try:
        with scratch.open("xb") as handle:
            handle.write(_json_bytes(manifest))
        _, errors = validate_manifest(scratch, check_files=True)
    finally:
        scratch.unlink(missing_ok=True)
    if errors:
        raise K3GoldenPromotionV2Error(
            "projected manifest is invalid: " + "; ".join(errors)
        )


def _replace_exact_job(jobs: list[Any], job: dict[str, Any]) -> list[Any]:
    result = list(jobs)
    matches = [
        index
        for index, item in enumerate(result)
        if isinstance(item, dict) and item.get("id") == JOB_ID
    ]
    if len(matches) > 1:
        raise K3GoldenPromotionV2Error(f"manifest duplicates exact JOB_ID {JOB_ID!r}")
    if matches:
        result[matches[0]] = job
    else:
        result.append(job)
    return result


def _normalized_root_review(
    source: ValidatedEmission,
    *,
    candidate: dict[str, str],
    views: dict[str, dict[str, str]],
) -> dict[str, Any]:
    document = source.root_document
    return {
        "schema_version": "1.0.0",
        "id": f"{JOB_ID}-root-authorization-v2",
        "job_id": JOB_ID,
        "created_at": document["created_at"],
        "reviewer": document["reviewer"].strip(),
        "status": "complete",
        "review_mode": "root-authority",
        "source_temporary_root_review_sha256": source.root_review.sha256,
        "candidate": candidate,
        "native": views["native"],
        "review_views": [
            {
                "id": name,
                **views[name],
                "complete": True,
                "evidence": document["review_views"][index]["evidence"],
            }
            for index, name in enumerate(VIEW_ORDER)
        ],
        "immediate_failures": copy.deepcopy(document["immediate_failures"]),
        "acceptance_threshold": ACCEPTANCE_THRESHOLD,
        "total_score": document["total_score"],
        "decision": "accepted",
        "authorizes_blind_review": True,
        "golden_reference": False,
        "acceptance_inferred": False,
        "summary": document["summary"],
    }


def _persistent_reproduction(reproduction: dict[str, Any]) -> dict[str, Any]:
    def record(binding: BoundArtifact) -> dict[str, str]:
        return {"path": binding.relative, "sha256": binding.sha256}

    return {
        "renderer": record(reproduction["renderer"]),
        "config": record(reproduction["config"]),
        "seed": reproduction["seed"],
        "donors": [record(item) for item in reproduction["donors"]],
        "controls": [record(item) for item in reproduction["controls"]],
        "argv": list(reproduction["argv"]),
        "environment": dict(reproduction["environment"]),
        "timeout_seconds": reproduction["timeout_seconds"],
        "read_closure_runner": record(reproduction["read_closure_runner"]),
        "pixel_auditor": record(reproduction["pixel_auditor"]),
        "pixel_audit": {
            "baseline": record(reproduction["pixel_audit"]["baseline"]),
            "control": record(reproduction["pixel_audit"]["control"]),
            "masks": {
                name: record(reproduction["pixel_audit"]["masks"][name])
                for name in pixel_auditor.MASK_NAMES
            },
        },
    }


def _validate_anonymous_view_png(binding: BoundArtifact, *, view_id: str) -> None:
    """Require the exact anonymous PNG chunk and text-metadata contract."""

    payload = binding.data
    if not payload.startswith(PNG_SIGNATURE):
        raise K3GoldenPromotionV2Error(
            f"anonymous PNG metadata/chunk contract failed for {view_id}: signature"
        )
    chunks: list[tuple[str, bytes]] = []
    offset = len(PNG_SIGNATURE)
    while offset < len(payload):
        if offset + 12 > len(payload):
            raise K3GoldenPromotionV2Error(
                f"anonymous PNG metadata/chunk contract failed for {view_id}: truncated chunk"
            )
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type_bytes = payload[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(payload):
            raise K3GoldenPromotionV2Error(
                f"anonymous PNG metadata/chunk contract failed for {view_id}: invalid length"
            )
        chunk_data = payload[offset + 8 : offset + 8 + length]
        claimed_crc = struct.unpack(">I", payload[offset + 8 + length : chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type_bytes + chunk_data) & 0xFFFFFFFF
        try:
            chunk_type = chunk_type_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            raise K3GoldenPromotionV2Error(
                f"anonymous PNG metadata/chunk contract failed for {view_id}: chunk type"
            ) from exc
        if claimed_crc != actual_crc:
            raise K3GoldenPromotionV2Error(
                f"anonymous PNG metadata/chunk contract failed for {view_id}: CRC"
            )
        chunks.append((chunk_type, chunk_data))
        offset = chunk_end
        if chunk_type == "IEND":
            break
    if offset != len(payload):
        raise K3GoldenPromotionV2Error(
            f"anonymous PNG metadata/chunk contract failed for {view_id}: trailing bytes"
        )
    chunk_types = [chunk_type for chunk_type, _ in chunks]
    if (
        len(chunks) < 5
        or chunk_types[0] != "IHDR"
        or chunk_types[1:3] != ["tEXt", "tEXt"]
        or not all(chunk_type == "IDAT" for chunk_type in chunk_types[3:-1])
        or chunk_types[-1] != "IEND"
    ):
        raise K3GoldenPromotionV2Error(
            f"anonymous PNG metadata/chunk contract failed for {view_id}: exact chunk sequence"
        )
    if len(chunks[0][1]) != 13:
        raise K3GoldenPromotionV2Error(
            f"anonymous PNG metadata/chunk contract failed for {view_id}: IHDR"
        )
    width, height, bit_depth, color_type, compression, filtering, interlace = (
        struct.unpack(">IIBBBBB", chunks[0][1])
    )
    expected_size = VIEW_DEFINITIONS[view_id][1]
    if (width, height) != expected_size or (
        bit_depth,
        color_type,
        compression,
        filtering,
        interlace,
    ) != (8, 2, 0, 0, 0):
        raise K3GoldenPromotionV2Error(
            f"anonymous PNG metadata/chunk contract failed for {view_id}: IHDR values"
        )
    observed_text: list[tuple[str, str]] = []
    for _, chunk_data in chunks[1:3]:
        keyword, separator, value = chunk_data.partition(b"\0")
        if separator != b"\0" or b"\0" in value:
            raise K3GoldenPromotionV2Error(
                f"anonymous PNG metadata/chunk contract failed for {view_id}: tEXt encoding"
            )
        try:
            observed_text.append((keyword.decode("latin-1"), value.decode("latin-1")))
        except UnicodeDecodeError as exc:  # pragma: no cover - latin-1 is total
            raise K3GoldenPromotionV2Error(
                f"anonymous PNG metadata/chunk contract failed for {view_id}: tEXt value"
            ) from exc
    expected_text = [
        (key, view_id if value is None else value)
        for key, value in BLIND_PNG_TEXT_METADATA
    ]
    if observed_text != expected_text:
        raise K3GoldenPromotionV2Error(
            f"anonymous PNG metadata/chunk contract failed for {view_id}: exact metadata"
        )
    if chunks[-1][1] != b"":
        raise K3GoldenPromotionV2Error(
            f"anonymous PNG metadata/chunk contract failed for {view_id}: IEND payload"
        )


def _create_blind_packet(
    *,
    views: dict[str, dict[str, str]],
    candidate: dict[str, str],
    paths: PromotionPaths,
    persistent_bindings: list[BoundArtifact],
    created: list[Path],
) -> BoundArtifact:
    """Persist anonymous fixed views and a content-addressed review packet.

    The packet deliberately contains no master path, candidate digest, donor,
    control, or generation lineage.  Reviewers receive only this packet.
    """

    anonymous: list[dict[str, str]] = []
    anonymous_digests: set[str] = set()
    for name in BLIND_PACKET_VIEW_IDS:
        source = _bind_trackable_record(views[name], label=f"blind source view {name}")
        source_image = _image_from_binding(
            source,
            label=f"blind source view {name}",
            expected_size=VIEW_DEFINITIONS[name][1],
        )
        encoded = BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("sstory-blind-contract", "phase4-v2")
        metadata.add_text("sstory-blind-view", name)
        source_pixels = source_image.tobytes()
        try:
            source_image.save(
                encoded,
                format="PNG",
                compress_level=9,
                optimize=False,
                pnginfo=metadata,
            )
        finally:
            source_image.close()
        payload = encoded.getvalue()
        digest = hashlib.sha256(payload).hexdigest()
        if digest == candidate["sha256"]:
            raise K3GoldenPromotionV2Error(
                f"anonymous blind view {name} must not reuse the candidate SHA-256"
            )
        if digest in anonymous_digests:
            raise K3GoldenPromotionV2Error(
                "anonymous blind views must have five distinct encoded SHA-256 values"
            )
        anonymous_digests.add(digest)
        destination = paths.blind_packet_dir / "views" / f"{name}-{digest}.png"
        existed = destination.exists()
        relative = _write_new(
            destination, payload, label=f"anonymous blind view {name}"
        )
        if not existed:
            created.append(destination)
        bound = bind_file(
            destination, label=f"anonymous blind view {name}", trackable=True
        )
        encoded_image = _image_from_binding(
            bound,
            label=f"anonymous blind view {name}",
            expected_size=VIEW_DEFINITIONS[name][1],
        )
        try:
            if encoded_image.tobytes() != source_pixels:
                raise K3GoldenPromotionV2Error(
                    f"anonymous blind view {name} changed canonical view pixels"
                )
        finally:
            encoded_image.close()
        _validate_anonymous_view_png(bound, view_id=name)
        persistent_bindings.append(bound)
        artifact = {"path": relative, "sha256": bound.sha256}
        anonymous.append({"id": name, **artifact})
    packet = {"schema_version": "1.0.0", "views": anonymous}
    payload = _json_bytes(packet)
    folded = payload.decode("utf-8").casefold()
    if candidate["path"].casefold() in folded or candidate["sha256"] in folded:
        raise K3GoldenPromotionV2Error(
            "blind packet must not disclose the candidate path or SHA-256"
        )
    if any(
        token in folded
        for token in ("candidate", "lineage", "donor", "control", "generation")
    ):
        raise K3GoldenPromotionV2Error(
            "blind packet must not disclose candidate lineage"
        )
    packet_path = paths.blind_packet_dir / f"{hashlib.sha256(payload).hexdigest()}.json"
    existed = packet_path.exists()
    _write_new(packet_path, payload, label="content-addressed blind packet")
    if not existed:
        created.append(packet_path)
    binding = bind_file(
        packet_path, label="content-addressed blind packet", trackable=True
    )
    _validate_blind_packet(
        binding,
        candidate_path=candidate["path"],
        candidate_sha256=candidate["sha256"],
    )
    persistent_bindings.append(binding)
    return binding


def _all_automated_gates() -> dict[str, bool]:
    return {name: True for name in sorted(AUTOMATED_GATE_NAMES)}


def prepare_promotion(
    *,
    emission_path: Path,
    root_review_path: Path,
    authorized_by: str,
    paths: PromotionPaths = DEFAULT_PATHS,
) -> dict[str, Any]:
    """Persist a validated generic emission and stop at automated QA."""

    actor = authorized_by.strip()
    if not actor:
        raise K3GoldenPromotionV2Error("authorized_by must be non-empty")
    try:
        manifest_binding = bind_file(
            paths.manifest, label="original production manifest", trackable=True
        )
    except (BoundArtifactError, ReleasePathError) as exc:
        raise K3GoldenPromotionV2Error(str(exc)) from exc
    manifest = _strict_json_object(
        manifest_binding, label="original production manifest"
    )
    jobs = manifest.get("jobs")
    source = _validate_emission(emission_path, root_review_path)
    _assert_not_previously_accepted(jobs, source.candidate)
    fresh_replay, fresh_replay_second = _execute_fresh_replays(
        source.reproduction, candidate=source.candidate
    )

    created: list[Path] = []
    persistent_bindings: list[BoundArtifact] = []
    view_destinations = _view_output_paths(paths)
    replay_destination = _replay_output_path(paths)
    replay_second_destination = _second_replay_output_path(paths)
    try:
        raw = _copy_new(
            source.candidate,
            paths.raw,
            label="persistent Golden raw candidate",
            bound_outputs=persistent_bindings,
            created_outputs=created,
        )
        candidate = _copy_new(
            source.candidate,
            paths.final,
            label="persistent Golden final candidate",
            bound_outputs=persistent_bindings,
            created_outputs=created,
        )
        if raw["sha256"] != candidate["sha256"]:
            raise K3GoldenPromotionV2Error(
                "persistent raw/final SHA-256 identity failed"
            )

        replay = _copy_new(
            fresh_replay,
            replay_destination,
            label="persistent deterministic replay",
            bound_outputs=persistent_bindings,
            created_outputs=created,
        )
        replay_second = _copy_new(
            fresh_replay_second,
            replay_second_destination,
            label="persistent deterministic replay second run",
            bound_outputs=persistent_bindings,
            created_outputs=created,
        )
        views: dict[str, dict[str, str]] = {}
        for name in VIEW_ORDER:
            views[name] = _copy_new(
                source.views[name],
                view_destinations[name],
                label=f"persistent review view {name}",
                bound_outputs=persistent_bindings,
                created_outputs=created,
            )
        blind_packet = _create_blind_packet(
            views=views,
            candidate=candidate,
            paths=paths,
            persistent_bindings=persistent_bindings,
            created=created,
        )

        root_document = _normalized_root_review(
            source, candidate=candidate, views=views
        )
        _assert_persistent_graph(root_document)
        root_existed = paths.root_review.exists()
        _write_new(
            paths.root_review,
            _json_bytes(root_document),
            label="persistent Root review",
        )
        if not root_existed:
            created.append(paths.root_review)
        root_binding = bind_file(
            paths.root_review, label="persistent Root review", trackable=True
        )
        persistent_bindings.append(root_binding)

        if paths.receipt.exists():
            existing_receipt = _strict_json_object(
                bind_file(
                    paths.receipt, label="existing promotion receipt", trackable=True
                ),
                label="existing promotion receipt",
            )
            now = _require_timestamp(
                existing_receipt.get("created_at"),
                label="existing promotion receipt.created_at",
            )
        else:
            now = utc_now()
        emission_at = parse_rfc3339(source.document["created_at"])
        root_at = parse_rfc3339(source.root_document["created_at"])
        prepared_at = parse_rfc3339(now)
        if emission_at > root_at or root_at > prepared_at:
            raise K3GoldenPromotionV2Error(
                "promotion timeline must satisfy emission <= Root <= prepared"
            )
        receipt = {
            "schema_version": "1.0.0",
            "id": f"{JOB_ID}-generic-promotion-v2-provenance",
            "job_id": JOB_ID,
            "status": PREPARED_STATUS,
            "source_temporary_emission_sha256": source.emission.sha256,
            "source_emission_created_at": source.document["created_at"],
            "authorized_by": actor,
            "created_at": now,
            "temporary_review_only": False,
            "previously_accepted": False,
            "golden_accepted": False,
            "acceptance_inferred": False,
            "raw": raw,
            "candidate": candidate,
            "views": views,
            "blind_packet": blind_packet.artifact(),
            "metrics": copy.deepcopy(source.document["metrics"]),
            "geometry": copy.deepcopy(source.document["geometry"]),
            "identity": copy.deepcopy(source.document["identity"]),
            "pixel_audit": copy.deepcopy(source.pixel_audit),
            "reproduction": _persistent_reproduction(source.reproduction),
            "independent_replay_2": replay_second,
            "determinism": {
                "independent_in_memory_builds": 2,
                "replay": replay,
                "byte_identical": True,
                "passed": True,
            },
            "root_review": root_binding.artifact(),
            "automated_gates": _all_automated_gates(),
            "failed_gates": [],
            "vision_handoff": {
                "required": True,
                "acceptance_threshold": ACCEPTANCE_THRESHOLD,
                "minimum_independent_reviews": 2,
                "review_mode": "blind-independent",
                "root_review_is_acceptance_authority": False,
                "candidate_must_remain_unaccepted_until_accept": True,
            },
        }
        _assert_persistent_graph(receipt)
        receipt_existed = paths.receipt.exists()
        _write_new(
            paths.receipt, _json_bytes(receipt), label="persistent source receipt"
        )
        if not receipt_existed:
            created.append(paths.receipt)
        receipt_binding = bind_file(
            paths.receipt, label="persistent source receipt", trackable=True
        )
        persistent_bindings.append(receipt_binding)

        audit = {
            "schema_version": "1.0.0",
            "id": f"{JOB_ID}-generic-promotion-v2-automated-audit",
            "job_id": JOB_ID,
            "status": "passed",
            "image_path": candidate["path"],
            "image_sha256": candidate["sha256"],
            "acceptance_threshold": ACCEPTANCE_THRESHOLD,
            "decision_authority": False,
            "acceptance_inferred": False,
            "golden_accepted": False,
            "raw": raw,
            "candidate": candidate,
            "provenance_receipt": receipt_binding.artifact(),
            "root_review": root_binding.artifact(),
            "views": views,
            "blind_packet": blind_packet.artifact(),
            "metrics": copy.deepcopy(source.document["metrics"]),
            "geometry": copy.deepcopy(source.document["geometry"]),
            "identity": copy.deepcopy(source.document["identity"]),
            "pixel_audit": copy.deepcopy(source.pixel_audit),
            "reproduction": _persistent_reproduction(source.reproduction),
            "independent_replay_2": replay_second,
            "determinism": {
                "independent_in_memory_builds": 2,
                "replay": replay,
                "byte_identical": True,
                "passed": True,
            },
            "automated_gates": _all_automated_gates(),
            "failed_gates": [],
            "authorized_by": actor,
            "source_emission_created_at": source.document["created_at"],
            "created_at": now,
        }
        _assert_persistent_graph(audit)
        audit_existed = paths.audit.exists()
        _write_new(paths.audit, _json_bytes(audit), label="persistent automated audit")
        if not audit_existed:
            created.append(paths.audit)
        audit_binding = bind_file(
            paths.audit, label="persistent automated audit", trackable=True
        )
        persistent_bindings.append(audit_binding)

        inputs = [
            {**raw, "role": "golden-raw-output"},
            {**receipt_binding.artifact(), "role": "promotion-provenance"},
            {**root_binding.artifact(), "role": "root-vision-authorization"},
            {**audit_binding.artifact(), "role": "persistent-automated-audit"},
            {**replay, "role": "deterministic-replay-output"},
            {**replay_second, "role": "deterministic-replay-output-2"},
            {**blind_packet.artifact(), "role": "blind-review-packet"},
        ]
        inputs.extend(
            {**views[name], "role": f"root-review-view-{name}"} for name in VIEW_ORDER
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
                "model": "generic-phase4-golden-emission-v2",
                "attempt": 1,
            },
            "master": {
                **candidate,
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
                {"state": state, "at": now, "actor": actor}
                for state in ("planned", "inputs-ready", "generated", "automated-qa")
            ],
        }
        projected = copy.deepcopy(manifest)
        projected["jobs"] = _replace_exact_job(list(jobs), job)
        projected["updated_at"] = now
        _validate_projected_manifest(paths.manifest, projected)
        _assert_unchanged(
            (
                manifest_binding,
                *source.source_bindings(),
                *persistent_bindings,
            )
        )
        manifest_commit = _conditional_manifest_replace(
            paths.manifest, projected, expected=manifest_binding
        )
        return {
            "status": "automated-qa",
            "job_id": JOB_ID,
            "candidate": candidate,
            "raw": raw,
            "receipt": receipt_binding.artifact(),
            "root_review": root_binding.artifact(),
            "audit": audit_binding.artifact(),
            "blind_packet": blind_packet.artifact(),
            "golden_accepted": False,
            "manifest_commit": manifest_commit.document(),
        }
    except ManifestCommitStateUnknownError:
        # The new manifest may already reference every created artifact. Keep
        # them intact until a retry or manual reconciliation proves otherwise.
        raise
    except Exception:
        for path in reversed(created):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


PREPARED_INPUT_ROLES = frozenset(
    {
        "golden-raw-output",
        "promotion-provenance",
        "root-vision-authorization",
        "persistent-automated-audit",
        "deterministic-replay-output",
        "deterministic-replay-output-2",
        "blind-review-packet",
        *(f"root-review-view-{name}" for name in VIEW_ORDER),
    }
)


def _prepared_role_bindings(job: dict[str, Any]) -> dict[str, BoundArtifact]:
    inputs = job.get("inputs")
    if not isinstance(inputs, list):
        raise K3GoldenPromotionV2Error("prepared job.inputs must be an array")
    result: dict[str, BoundArtifact] = {}
    for index, record in enumerate(inputs):
        if not isinstance(record, dict):
            raise K3GoldenPromotionV2Error(
                f"prepared inputs[{index}] must be an artifact"
            )
        role = record.get("role")
        if not isinstance(role, str) or role in result:
            raise K3GoldenPromotionV2Error(
                "prepared input roles must be non-empty and unique"
            )
        extra = set(record) - {"path", "sha256", "role"}
        if extra:
            raise K3GoldenPromotionV2Error(
                f"prepared input {role!r} has extra keys {sorted(extra)}"
            )
        result[role] = _bind_trackable_record(record, label=f"prepared input {role}")
    if set(result) != PREPARED_INPUT_ROLES:
        raise K3GoldenPromotionV2Error(
            f"prepared input roles are not exact: {sorted(result)}"
        )
    return result


def _validate_blind_packet(
    packet: BoundArtifact, *, candidate_path: str, candidate_sha256: str
) -> None:
    if packet.path.stem != packet.sha256:
        raise K3GoldenPromotionV2Error(
            "blind review packet filename must equal its content SHA-256"
        )
    text = packet.data.decode("utf-8")
    folded = text.casefold()
    if candidate_path.casefold() in folded or candidate_sha256 in folded:
        raise K3GoldenPromotionV2Error(
            "blind review packet discloses the candidate path or SHA-256"
        )
    if any(
        token in folded
        for token in ("candidate", "lineage", "donor", "control", "generation")
    ):
        raise K3GoldenPromotionV2Error(
            "blind review packet discloses candidate lineage"
        )
    document = _strict_json_object(packet, label="blind review packet")
    _require_exact_keys(
        document, {"schema_version", "views"}, label="blind review packet"
    )
    if document["schema_version"] != "1.0.0":
        raise K3GoldenPromotionV2Error("blind review packet schema_version is invalid")
    views = document["views"]
    if not isinstance(views, list) or len(views) != len(BLIND_PACKET_VIEW_IDS):
        raise K3GoldenPromotionV2Error(
            "blind review packet must contain exactly five views"
        )
    view_digests: set[str] = set()
    for expected, record in zip(BLIND_PACKET_VIEW_IDS, views):
        record = _require_exact_keys(
            record, {"id", "path", "sha256"}, label="blind packet view"
        )
        if record["id"] != expected:
            raise K3GoldenPromotionV2Error("blind review packet view order is invalid")
        view = _bind_trackable_record(record, label=f"blind packet view {expected}")
        _validate_anonymous_view_png(view, view_id=expected)
        if view.sha256 == candidate_sha256:
            raise K3GoldenPromotionV2Error(
                f"blind packet view {expected} reuses the candidate SHA-256"
            )
        view_digests.add(view.sha256)
    if len(view_digests) != len(BLIND_PACKET_VIEW_IDS):
        raise K3GoldenPromotionV2Error("blind review packet views must be distinct")


def _record_matches_binding(
    record: Any,
    binding: BoundArtifact,
    *,
    label: str,
    exact: bool = False,
) -> None:
    if exact:
        _require_exact_keys(record, {"path", "sha256"}, label=label)
    _assert_reference_matches(record, binding, label=label)


def _validate_normalized_root(
    document: dict[str, Any],
    *,
    candidate: BoundArtifact,
    views: dict[str, BoundArtifact],
) -> None:
    _require_exact_keys(
        document,
        set(ROOT_REVIEW_REQUIRED_KEYS) | {"id", "source_temporary_root_review_sha256"},
        label="prepared Root review",
    )
    exact = {
        "schema_version": "1.0.0",
        "id": f"{JOB_ID}-root-authorization-v2",
        "job_id": JOB_ID,
        "status": "complete",
        "review_mode": "root-authority",
        "acceptance_threshold": ACCEPTANCE_THRESHOLD,
        "decision": "accepted",
        "authorizes_blind_review": True,
        "golden_reference": False,
        "acceptance_inferred": False,
    }
    for field, expected in exact.items():
        if document.get(field) != expected:
            raise K3GoldenPromotionV2Error(f"prepared Root review {field} is invalid")
    _require_timestamp(
        document.get("created_at"), label="prepared Root review.created_at"
    )
    source_digest = document.get("source_temporary_root_review_sha256")
    if (
        not isinstance(source_digest, str)
        or len(source_digest) != 64
        or source_digest != source_digest.lower()
        or any(character not in "0123456789abcdef" for character in source_digest)
    ):
        raise K3GoldenPromotionV2Error("prepared Root review source SHA-256 is invalid")
    reviewer = document.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise K3GoldenPromotionV2Error(
            "prepared Root review reviewer must be non-empty"
        )
    summary = document.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise K3GoldenPromotionV2Error("prepared Root review summary must be non-empty")
    score = document.get("total_score")
    if (
        not isinstance(score, int)
        or isinstance(score, bool)
        or score < 94
        or score > 100
    ):
        raise K3GoldenPromotionV2Error("prepared Root review score must be 94..100")
    _require_exact_keys(
        document.get("candidate"), {"path", "sha256"}, label="prepared Root candidate"
    )
    _require_exact_keys(
        document.get("native"), {"path", "sha256"}, label="prepared Root native"
    )
    _record_matches_binding(
        document.get("candidate"), candidate, label="prepared Root candidate"
    )
    _record_matches_binding(
        document.get("native"), views["native"], label="prepared Root native"
    )
    review_views = document.get("review_views")
    if not isinstance(review_views, list) or len(review_views) != 5:
        raise K3GoldenPromotionV2Error(
            "prepared Root review does not contain exactly five views"
        )
    for name, item in zip(VIEW_ORDER, review_views):
        item = _require_exact_keys(
            item, set(ROOT_REVIEW_VIEW_KEYS), label=f"prepared Root view {name}"
        )
        if item.get("id") != name or item.get("complete") is not True:
            raise K3GoldenPromotionV2Error(f"prepared Root view {name} is incomplete")
        if not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
            raise K3GoldenPromotionV2Error(f"prepared Root view {name} lacks evidence")
        _record_matches_binding(item, views[name], label=f"prepared Root view {name}")
    failures = document.get("immediate_failures")
    if not isinstance(failures, list) or len(failures) != len(
        PHASE4_IMMEDIATE_FAILURE_IDS
    ):
        raise K3GoldenPromotionV2Error(
            "prepared Root immediate-failure checklist is incomplete"
        )
    for expected, item in zip(PHASE4_IMMEDIATE_FAILURE_IDS, failures):
        item = _require_exact_keys(
            item,
            {"id", "detected", "evidence"},
            label=f"prepared Root immediate failure {expected}",
        )
        if item["id"] != expected or item["detected"] is not False:
            raise K3GoldenPromotionV2Error(
                "prepared Root review has an immediate failure"
            )
        if not isinstance(item["evidence"], str) or not item["evidence"].strip():
            raise K3GoldenPromotionV2Error(
                f"prepared Root immediate failure {expected} lacks evidence"
            )


def _validate_prepared_evidence(
    job: dict[str, Any],
    roles: dict[str, BoundArtifact],
    master: BoundArtifact,
) -> tuple[BoundArtifact, BoundArtifact, BoundArtifact, BoundArtifact]:
    known_source = KNOWN_NON_GOLDEN_SOURCE_SHA256.get(master.sha256)
    if known_source is not None:
        raise K3GoldenPromotionV2Error(
            f"prepared Golden master is a known non-Golden source: {known_source}"
        )
    raw = roles["golden-raw-output"]
    if (
        raw.identity == master.identity
        or raw.sha256 != master.sha256
        or raw.data != master.data
    ):
        raise K3GoldenPromotionV2Error(
            "prepared raw/final byte-identity contract failed"
        )
    candidate_image = _image_from_binding(
        master, label="prepared Golden master", expected_size=EXPECTED_SIZE
    )
    replay = roles["deterministic-replay-output"]
    _image_from_binding(
        replay, label="prepared deterministic replay", expected_size=EXPECTED_SIZE
    ).close()
    replay_second = roles["deterministic-replay-output-2"]
    _image_from_binding(
        replay_second,
        label="prepared deterministic replay second run",
        expected_size=EXPECTED_SIZE,
    ).close()
    if (
        replay.identity == replay_second.identity
        or replay_second.sha256 != master.sha256
        or replay_second.data != master.data
    ):
        raise K3GoldenPromotionV2Error(
            "prepared deterministic replays must be distinct artifacts byte-identical to master"
        )
    views = {name: roles[f"root-review-view-{name}"] for name in VIEW_ORDER}
    try:
        for name, binding in views.items():
            view = _image_from_binding(
                binding,
                label=f"prepared review view {name}",
                expected_size=VIEW_DEFINITIONS[name][1],
            )
            try:
                _assert_exact_view_pixels(candidate_image, name, view)
            finally:
                view.close()
    finally:
        candidate_image.close()

    root = roles["root-vision-authorization"]
    root_document = _strict_json_object(root, label="prepared Root review")
    _validate_normalized_root(root_document, candidate=master, views=views)
    root_created_at = parse_rfc3339(root_document["created_at"])

    receipt = roles["promotion-provenance"]
    receipt_document = _strict_json_object(receipt, label="prepared promotion receipt")
    _require_exact_keys(
        receipt_document,
        set(PERSISTENT_RECEIPT_REQUIRED_KEYS),
        label="prepared promotion receipt",
    )
    exact_receipt = {
        "schema_version": "1.0.0",
        "id": f"{JOB_ID}-generic-promotion-v2-provenance",
        "job_id": JOB_ID,
        "status": PREPARED_STATUS,
        "temporary_review_only": False,
        "previously_accepted": False,
        "golden_accepted": False,
        "acceptance_inferred": False,
    }
    for field, expected in exact_receipt.items():
        if receipt_document.get(field) != expected:
            raise K3GoldenPromotionV2Error(
                f"prepared promotion receipt {field} is invalid"
            )
    source_emission_sha256 = receipt_document["source_temporary_emission_sha256"]
    if (
        not isinstance(source_emission_sha256, str)
        or len(source_emission_sha256) != 64
        or source_emission_sha256 != source_emission_sha256.lower()
        or any(
            character not in "0123456789abcdef" for character in source_emission_sha256
        )
    ):
        raise K3GoldenPromotionV2Error(
            "prepared promotion receipt source emission SHA-256 is invalid"
        )
    if (
        not isinstance(receipt_document["authorized_by"], str)
        or not receipt_document["authorized_by"].strip()
    ):
        raise K3GoldenPromotionV2Error(
            "prepared promotion receipt authorized_by must be non-empty"
        )
    source_emission_created_at = parse_rfc3339(
        _require_timestamp(
            receipt_document.get("source_emission_created_at"),
            label="prepared promotion receipt.source_emission_created_at",
        )
    )
    prepared_created_at = parse_rfc3339(
        _require_timestamp(
            receipt_document.get("created_at"),
            label="prepared promotion receipt.created_at",
        )
    )
    if not source_emission_created_at <= root_created_at <= prepared_created_at:
        raise K3GoldenPromotionV2Error(
            "prepared timeline must satisfy emission <= Root <= prepared"
        )
    _record_matches_binding(
        receipt_document.get("raw"), raw, label="receipt.raw", exact=True
    )
    _record_matches_binding(
        receipt_document.get("candidate"),
        master,
        label="receipt.candidate",
        exact=True,
    )
    _record_matches_binding(
        receipt_document.get("root_review"),
        root,
        label="receipt.root_review",
        exact=True,
    )
    receipt_views = receipt_document.get("views")
    if not isinstance(receipt_views, dict) or set(receipt_views) != set(VIEW_ORDER):
        raise K3GoldenPromotionV2Error("prepared receipt views are not exact")
    for name in VIEW_ORDER:
        _record_matches_binding(
            receipt_views[name],
            views[name],
            label=f"receipt.views.{name}",
            exact=True,
        )
    blind_packet = roles["blind-review-packet"]
    _record_matches_binding(
        receipt_document.get("blind_packet"),
        blind_packet,
        label="receipt.blind_packet",
        exact=True,
    )
    _validate_blind_packet(
        blind_packet,
        candidate_path=master.relative,
        candidate_sha256=master.sha256,
    )
    reproduction = _validate_reproduction_contract(receipt_document)
    recomputed_pixel_audit = _independent_pixel_audit(master, reproduction)
    _assert_pixel_claims_match(
        receipt_document,
        recomputed_pixel_audit,
        label="prepared promotion receipt",
    )
    if receipt_document.get("pixel_audit") != recomputed_pixel_audit:
        raise K3GoldenPromotionV2Error(
            "prepared promotion receipt pixel audit is not the independent recomputation"
        )
    _execute_fresh_replays(reproduction, candidate=master)
    _record_matches_binding(
        receipt_document.get("independent_replay_2"),
        replay_second,
        label="receipt.independent_replay_2",
        exact=True,
    )
    _assert_metric_contract(
        metrics=receipt_document.get("metrics"),
        geometry=receipt_document.get("geometry"),
        identity=receipt_document.get("identity"),
        determinism=receipt_document.get("determinism"),
        replay=replay,
        candidate=master,
        persistent=True,
    )
    if (
        receipt_document.get("automated_gates") != _all_automated_gates()
        or receipt_document.get("failed_gates") != []
    ):
        raise K3GoldenPromotionV2Error(
            "prepared receipt automated gates are incomplete"
        )
    expected_handoff = {
        "required": True,
        "acceptance_threshold": ACCEPTANCE_THRESHOLD,
        "minimum_independent_reviews": 2,
        "review_mode": "blind-independent",
        "root_review_is_acceptance_authority": False,
        "candidate_must_remain_unaccepted_until_accept": True,
    }
    if receipt_document["vision_handoff"] != expected_handoff:
        raise K3GoldenPromotionV2Error(
            "prepared promotion receipt vision handoff is not exact"
        )

    audit = roles["persistent-automated-audit"]
    audit_document = _strict_json_object(audit, label="prepared automated audit")
    _require_exact_keys(
        audit_document,
        set(PERSISTENT_AUDIT_REQUIRED_KEYS),
        label="prepared automated audit",
    )
    audit_exact = {
        "schema_version": "1.0.0",
        "id": f"{JOB_ID}-generic-promotion-v2-automated-audit",
        "job_id": JOB_ID,
        "status": "passed",
        "image_path": master.relative,
        "image_sha256": master.sha256,
        "acceptance_threshold": ACCEPTANCE_THRESHOLD,
        "decision_authority": False,
        "acceptance_inferred": False,
        "golden_accepted": False,
    }
    for field, expected in audit_exact.items():
        if audit_document.get(field) != expected:
            raise K3GoldenPromotionV2Error(
                f"prepared automated audit {field} is invalid"
            )
    audit_created_at = parse_rfc3339(
        _require_timestamp(
            audit_document.get("created_at"),
            label="prepared automated audit.created_at",
        )
    )
    if audit_created_at != prepared_created_at or audit_document.get(
        "source_emission_created_at"
    ) != receipt_document.get("source_emission_created_at"):
        raise K3GoldenPromotionV2Error(
            "prepared automated audit timeline does not match the promotion receipt"
        )
    _record_matches_binding(
        audit_document.get("raw"), raw, label="audit.raw", exact=True
    )
    _record_matches_binding(
        audit_document.get("candidate"),
        master,
        label="audit.candidate",
        exact=True,
    )
    _record_matches_binding(
        audit_document.get("provenance_receipt"),
        receipt,
        label="audit.receipt",
        exact=True,
    )
    _record_matches_binding(
        audit_document.get("root_review"),
        root,
        label="audit.root_review",
        exact=True,
    )
    _record_matches_binding(
        audit_document.get("blind_packet"),
        blind_packet,
        label="audit.blind_packet",
        exact=True,
    )
    audit_views = audit_document.get("views")
    if not isinstance(audit_views, dict) or set(audit_views) != set(VIEW_ORDER):
        raise K3GoldenPromotionV2Error("prepared automated audit views are not exact")
    for name in VIEW_ORDER:
        _record_matches_binding(
            audit_views[name],
            views[name],
            label=f"audit.views.{name}",
            exact=True,
        )
    _record_matches_binding(
        audit_document.get("independent_replay_2"),
        replay_second,
        label="audit.independent_replay_2",
        exact=True,
    )
    if (
        audit_document.get("automated_gates") != _all_automated_gates()
        or audit_document.get("failed_gates") != []
    ):
        raise K3GoldenPromotionV2Error("prepared automated audit gates are incomplete")
    if audit_document.get("reproduction") != receipt_document.get("reproduction"):
        raise K3GoldenPromotionV2Error(
            "prepared audit reproduction graph does not match the promotion receipt"
        )
    _assert_pixel_claims_match(
        audit_document,
        recomputed_pixel_audit,
        label="prepared automated audit",
    )
    if audit_document.get("pixel_audit") != recomputed_pixel_audit:
        raise K3GoldenPromotionV2Error(
            "prepared automated audit pixel evidence is not the independent recomputation"
        )
    _assert_metric_contract(
        metrics=audit_document.get("metrics"),
        geometry=audit_document.get("geometry"),
        identity=audit_document.get("identity"),
        determinism=audit_document.get("determinism"),
        replay=replay,
        candidate=master,
        persistent=True,
    )
    shared_evidence_fields = (
        "raw",
        "candidate",
        "root_review",
        "views",
        "blind_packet",
        "metrics",
        "geometry",
        "identity",
        "pixel_audit",
        "reproduction",
        "independent_replay_2",
        "determinism",
        "automated_gates",
        "failed_gates",
        "authorized_by",
        "source_emission_created_at",
        "created_at",
    )
    for field in shared_evidence_fields:
        if audit_document[field] != receipt_document[field]:
            raise K3GoldenPromotionV2Error(
                f"prepared receipt/audit evidence differs at {field}"
            )
    qa = job.get("qa")
    automated = qa.get("automated") if isinstance(qa, dict) else None
    if (
        not isinstance(automated, dict)
        or automated.get("status") != "passed"
        or not _same_path(automated.get("report_path", ""), audit.path)
        or "vision" in qa
    ):
        raise K3GoldenPromotionV2Error(
            "prepared manifest automated QA binding is invalid"
        )
    history = job.get("history")
    if (
        not isinstance(history, list)
        or len(history) != 4
        or [item.get("state") if isinstance(item, dict) else None for item in history]
        != ["planned", "inputs-ready", "generated", "automated-qa"]
    ):
        raise K3GoldenPromotionV2Error(
            "prepared manifest history is not the exact four-state handoff"
        )
    history_times = [
        parse_rfc3339(
            _require_timestamp(item.get("at"), label=f"prepared history[{index}].at")
        )
        for index, item in enumerate(history)
    ]
    if any(value != prepared_created_at for value in history_times):
        raise K3GoldenPromotionV2Error(
            "prepared manifest history must match the prepared receipt timestamp"
        )
    return raw, receipt, audit, blind_packet


def _accepted_blind_review(
    binding: BoundArtifact,
    *,
    blind_packet: BoundArtifact,
    root_reviewer: str,
    root_created_at: str,
    prepared_created_at: str,
) -> tuple[dict[str, Any], str, str]:
    report = _strict_json_object(binding, label=f"Golden review {binding.relative}")
    try:
        qa_schema = load_json(QA_REPORT_SCHEMA)
        errors = schema_errors(report, qa_schema)
    except (OSError, ValidationFailure, ValueError) as exc:
        raise K3GoldenPromotionV2Error(
            f"cannot validate Golden review schema: {exc}"
        ) from exc
    if errors:
        raise K3GoldenPromotionV2Error(
            f"Golden review {binding.relative} is invalid: " + "; ".join(errors)
        )
    exact = {
        "job_id": JOB_ID,
        "image_path": blind_packet.relative,
        "image_sha256": blind_packet.sha256,
        "status": "complete",
        "golden_reference": True,
        "review_mode": "blind-independent",
        "acceptance_threshold": ACCEPTANCE_THRESHOLD,
        "decision": "accepted",
    }
    for field, expected in exact.items():
        if report.get(field) != expected:
            raise K3GoldenPromotionV2Error(
                f"Golden review {binding.relative} {field} must be {expected!r}"
            )
    if "automated" in (
        part.casefold() for part in PurePosixPath(binding.relative).parts
    ):
        raise K3GoldenPromotionV2Error(
            "Golden reviews may not be stored under qa/automated"
        )
    views = report.get("review_views")
    if not isinstance(views, list):
        raise K3GoldenPromotionV2Error("Golden review has no review views")
    view_ids: set[str] = set()
    for view in views:
        if (
            not isinstance(view, dict)
            or view.get("complete") is not True
            or not isinstance(view.get("evidence"), str)
            or not view["evidence"].strip()
            or not isinstance(view.get("id"), str)
            or view["id"] in view_ids
        ):
            raise K3GoldenPromotionV2Error(
                "every Golden review view must be complete, evidenced, and unique"
            )
        view_ids.add(view["id"])
    if not set(BLIND_PACKET_VIEW_IDS) <= view_ids:
        raise K3GoldenPromotionV2Error(
            "Golden review must complete the five fixed blind packet views"
        )
    failures = report.get("immediate_failures")
    if (
        not isinstance(failures, list)
        or not failures
        or any(
            not isinstance(item, dict) or item.get("detected") is not False
            for item in failures
        )
    ):
        raise K3GoldenPromotionV2Error("Golden review has an immediate failure")
    failure_ids = [item.get("id") for item in failures]
    if tuple(failure_ids) != PHASE4_IMMEDIATE_FAILURE_IDS:
        raise K3GoldenPromotionV2Error(
            "Golden immediate-failure checklist must exactly match Phase 4"
        )
    scores = report.get("scores")
    if not isinstance(scores, list) or len(scores) != 7:
        raise K3GoldenPromotionV2Error(
            "Golden review must contain exactly seven scores"
        )

    def integer(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    maxima = [item.get("maximum") for item in scores if isinstance(item, dict)]
    values = [item.get("score") for item in scores if isinstance(item, dict)]
    score_ids = [item.get("id") for item in scores if isinstance(item, dict)]
    total = report.get("total_score")
    if (
        len(maxima) != 7
        or not all(integer(value) for value in maxima + values)
        or sum(maxima) != 100
        or any(value < 0 or value > maximum for value, maximum in zip(values, maxima))
        or len(set(score_ids)) != 7
        or not integer(total)
        or total != sum(values)
        or total < 94
    ):
        raise K3GoldenPromotionV2Error(
            "Golden review score contract must total at least 94/100"
        )
    reviewer = report.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise K3GoldenPromotionV2Error("Golden review reviewer must be non-empty")
    matching = [
        prefix for prefix in BLIND_REVIEW_ROLE_PREFIXES if reviewer.startswith(prefix)
    ]
    if len(matching) != 1 or not reviewer[len(matching[0]) :].strip():
        raise K3GoldenPromotionV2Error(
            "Golden reviewer must use canonical blind role/id form"
        )
    reviewer_id = canonical_reviewer_identity(reviewer[len(matching[0]) :])
    if reviewer_id == canonical_reviewer_identity(root_reviewer):
        raise K3GoldenPromotionV2Error(
            "Golden blind reviewer must differ from Root reviewer"
        )
    reviewed_at = parse_rfc3339(
        _require_timestamp(report.get("created_at"), label="Golden review.created_at")
    )
    if reviewed_at <= parse_rfc3339(root_created_at):
        raise K3GoldenPromotionV2Error(
            "Golden blind review must be created after Root authorization"
        )
    if reviewed_at <= parse_rfc3339(prepared_created_at):
        raise K3GoldenPromotionV2Error(
            "Golden blind review must be created after prepared evidence"
        )
    role = matching[0][:-1]
    return report, f"{role}/{reviewer_id}", role


def accept_promotion(
    *,
    review_paths: list[Path],
    authorized_by: str,
    paths: PromotionPaths = DEFAULT_PATHS,
) -> dict[str, Any]:
    """Accept only an exact prepared job and two independent Golden reviews."""

    if len(review_paths) != 2:
        raise K3GoldenPromotionV2Error("accept requires exactly two persistent reviews")
    actor = authorized_by.strip()
    if not actor:
        raise K3GoldenPromotionV2Error("authorized_by must be non-empty")
    try:
        manifest_binding = bind_file(
            paths.manifest, label="prepared production manifest", trackable=True
        )
    except (BoundArtifactError, ReleasePathError) as exc:
        raise K3GoldenPromotionV2Error(str(exc)) from exc
    manifest = _strict_json_object(
        manifest_binding, label="prepared production manifest"
    )
    jobs = manifest.get("jobs")
    matches = (
        [job for job in jobs if isinstance(job, dict) and job.get("id") == JOB_ID]
        if isinstance(jobs, list)
        else []
    )
    if len(matches) != 1:
        raise K3GoldenPromotionV2Error(
            f"manifest must contain exactly one prepared {JOB_ID!r} job"
        )
    job = matches[0]
    if job.get("status") != "automated-qa" or job.get("acceptance_threshold") != 94:
        raise K3GoldenPromotionV2Error(
            "Golden acceptance requires threshold-94 automated-qa"
        )
    history = job.get("history")
    if not isinstance(history, list) or [
        item.get("state") for item in history if isinstance(item, dict)
    ] != ["planned", "inputs-ready", "generated", "automated-qa"]:
        raise K3GoldenPromotionV2Error(
            "prepared Golden history is not the exact four-state handoff"
        )
    master_record = job.get("master")
    if not isinstance(master_record, dict):
        raise K3GoldenPromotionV2Error("prepared Golden job has no master")
    master = _bind_trackable_record(master_record, label="prepared Golden master")
    if (
        master_record.get("width") != EXPECTED_SIZE[0]
        or master_record.get("height") != EXPECTED_SIZE[1]
        or master_record.get("color_profile") != "untagged RGB"
    ):
        raise K3GoldenPromotionV2Error("prepared Golden master metadata is invalid")
    if master.sha256 in KNOWN_NON_GOLDEN_SOURCE_SHA256:
        raise K3GoldenPromotionV2Error(
            "prepared Golden master is a known non-Golden source"
        )
    roles = _prepared_role_bindings(job)
    raw, receipt, audit, blind_packet = _validate_prepared_evidence(job, roles, master)
    root_document = _strict_json_object(
        roles["root-vision-authorization"], label="prepared Root review"
    )
    receipt_document = _strict_json_object(receipt, label="prepared promotion receipt")

    try:
        review_bindings = [
            bind_file(path, label=f"Golden review {index + 1}", trackable=True)
            for index, path in enumerate(review_paths)
        ]
    except (BoundArtifactError, ReleasePathError) as exc:
        raise K3GoldenPromotionV2Error(str(exc)) from exc
    if review_bindings[0].identity == review_bindings[1].identity:
        raise K3GoldenPromotionV2Error("accept requires two distinct review artifacts")
    reviewed_by_role: dict[str, tuple[BoundArtifact, dict[str, Any], str]] = {}
    for binding in review_bindings:
        report, reviewer, role = _accepted_blind_review(
            binding,
            blind_packet=blind_packet,
            root_reviewer=root_document["reviewer"],
            root_created_at=root_document["created_at"],
            prepared_created_at=receipt_document["created_at"],
        )
        if role in reviewed_by_role:
            raise K3GoldenPromotionV2Error(
                f"accept duplicates canonical blind review role {role!r}"
            )
        reviewed_by_role[role] = (binding, report, reviewer)
    if set(reviewed_by_role) != set(INDEPENDENT_VISION_REVIEW_ROLES):
        raise K3GoldenPromotionV2Error(
            "accept requires the two canonical blind reviewer roles"
        )
    try:
        identities = [
            canonical_reviewer_identity(reviewer.split("/", maxsplit=1)[1])
            for _, _, reviewer in reviewed_by_role.values()
        ]
    except ValueError as exc:
        raise K3GoldenPromotionV2Error(str(exc)) from exc
    if len(set(identities)) != 2:
        raise K3GoldenPromotionV2Error(
            "accept requires two canonically distinct blind-independent reviewers"
        )
    if paths.final_receipt.exists():
        existing_acceptance = _strict_json_object(
            bind_file(
                paths.final_receipt,
                label="existing final Golden acceptance receipt",
                trackable=True,
            ),
            label="existing final Golden acceptance receipt",
        )
        now = _require_timestamp(
            existing_acceptance.get("accepted_at"),
            label="existing final Golden acceptance receipt.accepted_at",
        )
    else:
        now = utc_now()
    accepted_at = parse_rfc3339(now)
    if any(
        parse_rfc3339(report["created_at"]) > accepted_at
        for _, report, _ in reviewed_by_role.values()
    ):
        raise K3GoldenPromotionV2Error(
            "Golden acceptance timestamp must not predate a blind review"
        )
    acceptance_receipt = {
        "schema_version": "1.0.0",
        "id": f"{JOB_ID}-golden-acceptance-v2",
        "job_id": JOB_ID,
        "status": "accepted",
        "golden_reference": True,
        "acceptance_threshold": ACCEPTANCE_THRESHOLD,
        "candidate": master.artifact(),
        "raw": raw.artifact(),
        "promotion_provenance": receipt.artifact(),
        "automated_audit": audit.artifact(),
        "root_review": roles["root-vision-authorization"].artifact(),
        "blind_packet": blind_packet.artifact(),
        "reviews": [
            {
                "role": role,
                **binding.artifact(),
                "reviewer": reviewer,
                "score": report["total_score"],
                "created_at": report["created_at"],
            }
            for role in INDEPENDENT_VISION_REVIEW_ROLES
            for binding, report, reviewer in (reviewed_by_role[role],)
        ],
        "authorized_by": actor,
        "accepted_at": now,
    }
    _assert_persistent_graph(acceptance_receipt)
    created = False
    try:
        created = not paths.final_receipt.exists()
        _write_new(
            paths.final_receipt,
            _json_bytes(acceptance_receipt),
            label="final Golden acceptance receipt",
        )
        final_receipt = bind_file(
            paths.final_receipt,
            label="final Golden acceptance receipt",
            trackable=True,
        )
        projected = copy.deepcopy(manifest)
        projected_job = next(
            item
            for item in projected["jobs"]
            if isinstance(item, dict) and item.get("id") == JOB_ID
        )
        projected_job["inputs"].extend(
            {**reviewed_by_role[role][0].artifact(), "role": role}
            for role in INDEPENDENT_VISION_REVIEW_ROLES
        )
        projected_job["inputs"].append(
            {**final_receipt.artifact(), "role": "golden-acceptance-receipt"}
        )
        _, primary, primary_reviewer = reviewed_by_role[
            INDEPENDENT_VISION_REVIEW_ROLES[0]
        ]
        projected_job["qa"]["vision"] = {
            "decision": "accepted",
            "score": primary["total_score"],
            "report_path": reviewed_by_role[INDEPENDENT_VISION_REVIEW_ROLES[0]][
                0
            ].relative,
            "reviewer": primary_reviewer,
            "reviewed_at": primary["created_at"],
        }
        for state in ("vision-qa", "accepted"):
            projected_job["history"].append({"state": state, "at": now, "actor": actor})
        projected_job["status"] = "accepted"
        projected["updated_at"] = now
        _validate_projected_manifest(paths.manifest, projected)
        _assert_unchanged(
            (
                manifest_binding,
                master,
                *roles.values(),
                *review_bindings,
                final_receipt,
            )
        )
        manifest_commit = _conditional_manifest_replace(
            paths.manifest, projected, expected=manifest_binding
        )
        return {
            "status": "accepted",
            "job_id": JOB_ID,
            "candidate": master.artifact(),
            "reviews": [
                reviewed_by_role[role][0].artifact()
                for role in INDEPENDENT_VISION_REVIEW_ROLES
            ],
            "reviewers": [
                reviewed_by_role[role][2] for role in INDEPENDENT_VISION_REVIEW_ROLES
            ],
            "receipt": final_receipt.artifact(),
            "manifest_commit": manifest_commit.document(),
        }
    except ManifestCommitStateUnknownError:
        # An accepted manifest may already reference the final receipt.
        # Unknown commit state must never trigger destructive rollback.
        raise
    except Exception:
        if created:
            paths.final_receipt.unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser(
        "prepare", help="persist a generic emission and stop at automated-qa"
    )
    prepare.add_argument("--emission", type=Path, required=True)
    prepare.add_argument("--root-review", type=Path, required=True)
    prepare.add_argument("--authorized-by", required=True)
    prepare.add_argument("--manifest", type=Path, default=DEFAULT_PATHS.manifest)
    accept = subparsers.add_parser(
        "accept", help="accept after exactly two blind-independent reviews"
    )
    accept.add_argument("--review-a", type=Path, default=DEFAULT_REVIEW_A)
    accept.add_argument("--review-b", type=Path, default=DEFAULT_REVIEW_B)
    accept.add_argument("--authorized-by", required=True)
    accept.add_argument("--manifest", type=Path, default=DEFAULT_PATHS.manifest)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = PromotionPaths(**{**DEFAULT_PATHS.__dict__, "manifest": args.manifest})
    try:
        if args.command == "prepare":
            result = prepare_promotion(
                emission_path=args.emission,
                root_review_path=args.root_review,
                authorized_by=args.authorized_by,
                paths=paths,
            )
        else:
            result = accept_promotion(
                review_paths=[args.review_a, args.review_b],
                authorized_by=args.authorized_by,
                paths=paths,
            )
    except (
        K3GoldenPromotionV2Error,
        BoundArtifactError,
        ReleasePathError,
        OSError,
        ValueError,
    ) as exc:
        print(f"K3 Golden v2 promotion failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
