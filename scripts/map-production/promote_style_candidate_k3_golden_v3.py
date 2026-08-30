#!/usr/bin/env python3
"""Promote one reviewed Golden-v3 candidate under the frozen v3 authority.

The authority contains no candidate, review, seal, or receipt binding.  This
command binds those artifacts only at runtime, independently recomputes the
strict-v3 audit, validates the anonymous review packet and three distinct
reviewers, and then creates the raw/master/receipt with exclusive-create
semantics.  The production manifest is changed last with a compare-and-swap.
There is no force, resume, or overwrite mode.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from PIL import Image

from production_common import REPO_ROOT, parse_rfc3339, utc_now
from release_bound_artifact import (
    BoundArtifact,
    BoundArtifactError,
    assert_bindings_unchanged,
    bind_file,
)
from release_path_safety import (
    ReleasePathError,
    assert_no_reparse_components,
    canonical_repo_relative,
    require_trackable_path,
    same_path,
)
from reviewer_identity import canonical_reviewer_identity
from validate_manifest import ValidationFailure, schema_errors


AUTHORITY_PATH = (
    REPO_ROOT / "world/map-production/spec/"
    "style-candidate-k3-golden-v3-promotion-authority-v1.json"
)
# fmt: off
EXPECTED_AUTHORITY_SHA256 = "ee2766c3e27c1cf2ad4f8c4bcb44eafbb2952eba1b5a4db0ad04dca17fc809a9"
EXPECTED_IMPLEMENTATION_SELF_SHA256 = "76505d9171b9998bf645aa5bcc1686bc1188ed16f6ce88563a537fc0f0bd4b65"
# fmt: on
IMPLEMENTATION_HASH_MODE = "sha256-zero-expected-authority-and-self-hashes-v1"
FOUR_CANDIDATE_AUTHORITY_PATH = REPO_ROOT / (
    "world/map-production/spec/"
    "style-candidate-k3-golden-v3-four-candidate-derivation-preregistration-v1.json"
)
BALANCED_AUTHORITY_PATH = REPO_ROOT / (
    "world/map-production/spec/"
    "style-candidate-k3-golden-v3-balanced-phase-preregistration-v2.json"
)
BALANCED_OPEN_AUTHORITY_PATH = REPO_ROOT / (
    "world/map-production/spec/"
    "style-candidate-k3-golden-v3-balanced-open-phase-preregistration-v3.json"
)
STRICT_AUDIT_IMPLEMENTATION_PATH = (
    REPO_ROOT / "scripts/map-production/audit_style_candidate_k3_golden_v3.py"
)
FOUR_CANDIDATE_MODULE_NAME = "_sstory_bound_golden_v3_four_candidate_phase_v1"
BALANCED_MODULE_NAME = "_sstory_bound_golden_v3_balanced_phase_v2"
BALANCED_OPEN_MODULE_NAME = "_sstory_bound_golden_v3_balanced_open_phase_v3"
STRICT_AUDIT_MODULE_NAME = "_sstory_bound_golden_v3_strict_audit"
STRICT_AUDIT_V2_MODULE_NAME = "audit_style_candidate_k3_golden_v2"
STRICT_AUDIT_V19_MODULE_NAME = "build_style_candidate_k3_sparse_ridgeline_v19"
STRICT_AUDIT_CORE_MODULE_NAME = "golden_v3_strict_metric_core"
derivation: ModuleType | None = None
balanced_derivation: ModuleType | None = None
balanced_open_derivation: ModuleType | None = None
strict_audit: ModuleType | None = None
strict_audit_v2: ModuleType | None = None
strict_audit_v19: ModuleType | None = None
strict_audit_core: ModuleType | None = None
manifest_cas: ModuleType | None = None
_bound_module_sha256: dict[str, str] = {}
JOB_ID = "style-candidate-k-v3-golden-v3"
FOUR_CANDIDATE_V1 = "four-candidate-v1"
BALANCED_PHASE_V2 = "balanced-phase-v2"
BALANCED_OPEN_PHASE_V3 = "balanced-open-phase-v3"
ACTIVE_GENERATION_CONTRACT_ID = BALANCED_OPEN_PHASE_V3
GENERATION_CONTRACT_IDS = (
    FOUR_CANDIDATE_V1,
    BALANCED_PHASE_V2,
    BALANCED_OPEN_PHASE_V3,
)

V3_ACCEPTANCE_RECEIPT_ROLE = "golden-v3-acceptance-receipt"
V3_PROMOTION_AUTHORITY_ROLE = "golden-v3-promotion-authority"
V3_PROMOTION_IMPLEMENTATION_ROLE = "golden-v3-promotion-implementation"
V3_DERIVATION_AUTHORITY_ROLE = "golden-v3-four-candidate-derivation-authority"
V3_DERIVATION_GENERATOR_ROLE = "golden-v3-four-candidate-generator"
V3_BALANCED_AUTHORITY_ROLE = "golden-v3-balanced-phase-v2-authority"
V3_BALANCED_GENERATOR_ROLE = "golden-v3-balanced-phase-v2-generator"
V3_BALANCED_OPEN_AUTHORITY_ROLE = "golden-v3-balanced-open-phase-v3-authority"
V3_BALANCED_OPEN_GENERATOR_ROLE = "golden-v3-balanced-open-phase-v3-generator"
V3_STRICT_AUTHORITY_ROLE = "golden-v3-strict-audit-authority"
V3_STRICT_IMPLEMENTATION_ROLE = "golden-v3-strict-audit-implementation"
V3_STRICT_REPORT_ROLE = "golden-v3-strict-audit-report"
V3_ROOT_REVIEW_ROLE = "golden-v3-root-vision-authorization"
RAW_ROLE = "golden-raw-output"
BLIND_PACKET_ROLE = "blind-review-packet"
V3_ONLY_ROLES = frozenset(
    {
        V3_ACCEPTANCE_RECEIPT_ROLE,
        V3_PROMOTION_AUTHORITY_ROLE,
        V3_PROMOTION_IMPLEMENTATION_ROLE,
        V3_DERIVATION_AUTHORITY_ROLE,
        V3_DERIVATION_GENERATOR_ROLE,
        V3_BALANCED_AUTHORITY_ROLE,
        V3_BALANCED_GENERATOR_ROLE,
        V3_BALANCED_OPEN_AUTHORITY_ROLE,
        V3_BALANCED_OPEN_GENERATOR_ROLE,
        V3_STRICT_AUTHORITY_ROLE,
        V3_STRICT_IMPLEMENTATION_ROLE,
        V3_STRICT_REPORT_ROLE,
        V3_ROOT_REVIEW_ROLE,
    }
)

DEFAULT_RAW = (
    REPO_ROOT / "world/map-production/candidates/style-candidate-k-v3-golden-v3-raw.png"
)
DEFAULT_MASTER = (
    REPO_ROOT / "world/map-production/candidates/style-candidate-k-v3-golden-v3.png"
)
DEFAULT_RECEIPT = (
    REPO_ROOT / "world/map-production/prompts/"
    "style-candidate-k-v3-golden-v3.acceptance-receipt.json"
)
DEFAULT_MANIFEST = REPO_ROOT / "world/map-production/production-manifest.json"

PACKET_KEYS = {
    "schema_version",
    "id",
    "job_id",
    "candidate_sha256",
    "candidate_bytes",
    "view_order",
    "views",
    "created_at",
}
PACKET_VIEW_KEYS = {"id", "path", "sha256"}


class GoldenV3PromotionError(RuntimeError):
    """Raised before invalid Golden-v3 evidence can be accepted."""


class GoldenV3ManifestCommitUnknownError(GoldenV3PromotionError):
    """The manifest replacement may have committed; evidence is retained."""


@dataclass(frozen=True)
class PromotionPaths:
    manifest: Path = DEFAULT_MANIFEST
    raw: Path = DEFAULT_RAW
    master: Path = DEFAULT_MASTER
    receipt: Path = DEFAULT_RECEIPT


@dataclass
class _ParentAnchor:
    path: Path
    identity: tuple[int, int]
    linux_fds: list[int]
    windows_handles: list[int]
    windows_identities: list[tuple[int, int]]

    @property
    def parent_fd(self) -> int | None:
        return self.linux_fds[-1] if self.linux_fds else None


@dataclass(frozen=True)
class _CreatedOutput:
    binding: BoundArtifact


@dataclass(frozen=True)
class AuthorityBundle:
    binding: BoundArtifact
    document: dict[str, Any]
    promotion_implementation: BoundArtifact
    promotion_implementation_sha256: str
    strict_authority: BoundArtifact
    strict_implementation: BoundArtifact
    strict_module: ModuleType
    strict_dependencies: tuple[BoundArtifact, ...]
    strict_dependency_modules: tuple[ModuleType, ...]
    derivation_authority: BoundArtifact
    derivation_generator: BoundArtifact
    derivation_module: ModuleType
    balanced_authority: BoundArtifact
    balanced_generator: BoundArtifact
    balanced_module: ModuleType
    balanced_open_authority: BoundArtifact
    balanced_open_generator: BoundArtifact
    balanced_open_module: ModuleType
    schemas: dict[str, BoundArtifact]


@dataclass(frozen=True)
class PacketEvidence:
    binding: BoundArtifact
    document: dict[str, Any]
    views: tuple[BoundArtifact, ...]


@dataclass(frozen=True)
class ReviewEvidence:
    binding: BoundArtifact
    document: dict[str, Any]
    role: str
    reviewer_identity: str
    score: int
    created_at: Any


class _WindowsFileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class _WindowsFileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", ctypes.c_uint32),
        ("creation_time", _WindowsFileTime),
        ("last_access_time", _WindowsFileTime),
        ("last_write_time", _WindowsFileTime),
        ("volume_serial", ctypes.c_uint32),
        ("file_size_high", ctypes.c_uint32),
        ("file_size_low", ctypes.c_uint32),
        ("link_count", ctypes.c_uint32),
        ("file_index_high", ctypes.c_uint32),
        ("file_index_low", ctypes.c_uint32),
    ]


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GoldenV3PromotionError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _strict_json(payload: bytes, *, label: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise GoldenV3PromotionError(
            f"{label} contains forbidden non-finite constant {value!r}"
        )

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise GoldenV3PromotionError(
            f"{label} is not strict UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise GoldenV3PromotionError(f"{label} must contain exactly one JSON object")
    return value


def _exact_json_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/int/float equivalence."""

    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            _exact_json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _exact_json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return bool(left == right)


def _canonical_implementation_payload(payload: bytes) -> bytes:
    canonical = payload
    for name in (
        b"EXPECTED_AUTHORITY_SHA256",
        b"EXPECTED_IMPLEMENTATION_SELF_SHA256",
    ):
        pattern = re.compile(rb"(?m)^" + re.escape(name) + rb' = "[0-9a-f]{64}"$')
        replacement = name + b' = "' + (b"0" * 64) + b'"'
        canonical, count = pattern.subn(replacement, canonical)
        if count != 1:
            raise GoldenV3PromotionError(
                f"Golden-v3 promotion implementation {name.decode('ascii')} marker changed"
            )
    return canonical


def _implementation_self_sha256(payload: bytes) -> str:
    return hashlib.sha256(_canonical_implementation_payload(payload)).hexdigest()


def _load_bound_module(binding: BoundArtifact, *, name: str) -> ModuleType:
    global derivation, balanced_derivation, balanced_open_derivation
    global strict_audit, strict_audit_v2, strict_audit_v19, strict_audit_core
    public_names = {
        FOUR_CANDIDATE_MODULE_NAME: "derivation",
        BALANCED_MODULE_NAME: "balanced_derivation",
        BALANCED_OPEN_MODULE_NAME: "balanced_open_derivation",
        STRICT_AUDIT_MODULE_NAME: "strict_audit",
        STRICT_AUDIT_V2_MODULE_NAME: "strict_audit_v2",
        STRICT_AUDIT_V19_MODULE_NAME: "strict_audit_v19",
        STRICT_AUDIT_CORE_MODULE_NAME: "strict_audit_core",
    }
    if name not in public_names:
        raise GoldenV3PromotionError("unknown bound Golden-v3 module name")
    cached = globals()[public_names[name]]
    if cached is not None and _bound_module_sha256.get(name) == binding.sha256:
        return cached
    try:
        source = binding.data.decode("utf-8")
        code = compile(source, os.fspath(binding.path), "exec", dont_inherit=True)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise GoldenV3PromotionError(
            f"cannot compile bound Golden-v3 module {binding.relative}: {exc}"
        ) from exc
    module = ModuleType(name)
    module.__file__ = os.fspath(binding.path)
    module.__package__ = ""
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        exec(code, module.__dict__)
    except BaseException:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        raise
    globals()[public_names[name]] = module
    _bound_module_sha256[name] = binding.sha256
    return module


def _implementation_artifact(authority: AuthorityBundle) -> dict[str, str]:
    return _artifact(authority.promotion_implementation)


def _require_active_generation_contract(
    authority: AuthorityBundle, generation_contract_id: str
) -> None:
    active = authority.document["freeze_scope"]["active_generation_contract_id"]
    if active != ACTIVE_GENERATION_CONTRACT_ID:
        raise GoldenV3PromotionError("Golden-v3 active generation contract changed")
    if generation_contract_id != active:
        raise GoldenV3PromotionError(
            "new Golden-v3 promotion is restricted to the active "
            f"{active} contract; legacy contracts are verification-only"
        )


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GoldenV3PromotionError(
            f"document is not canonical JSON data: {exc}"
        ) from exc


def _parse_timestamp(value: Any, *, label: str) -> Any:
    try:
        return parse_rfc3339(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise GoldenV3PromotionError(f"{label} is not RFC 3339: {exc}") from exc


def _artifact(binding: BoundArtifact) -> dict[str, str]:
    return {"path": binding.relative, "sha256": binding.sha256}


def _bind(path: str | Path, *, label: str, trackable: bool = True) -> BoundArtifact:
    try:
        return bind_file(path, label=label, trackable=trackable)
    except (BoundArtifactError, ReleasePathError) as exc:
        raise GoldenV3PromotionError(str(exc)) from exc


def _bind_record(value: Any, *, label: str) -> BoundArtifact:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "sha256"}
        or not isinstance(value.get("path"), str)
        or not isinstance(value.get("sha256"), str)
    ):
        raise GoldenV3PromotionError(f"{label} must be an exact path/sha256 record")
    binding = _bind(value["path"], label=label)
    if binding.sha256 != value["sha256"]:
        raise GoldenV3PromotionError(
            f"{label} SHA-256 mismatch: record={value['sha256']}, actual={binding.sha256}"
        )
    return binding


def _schema_errors(
    document: dict[str, Any], schema: BoundArtifact, *, label: str
) -> None:
    schema_document = _strict_json(schema.data, label=f"{label} schema")
    try:
        errors = schema_errors(document, schema_document)
    except ValidationFailure as exc:
        raise GoldenV3PromotionError(str(exc)) from exc
    if errors:
        raise GoldenV3PromotionError(f"{label} schema failed: " + "; ".join(errors))


def load_authority() -> AuthorityBundle:
    global manifest_cas
    authority = _bind(AUTHORITY_PATH, label="Golden-v3 promotion authority")
    if authority.sha256 != EXPECTED_AUTHORITY_SHA256:
        raise GoldenV3PromotionError(
            "Golden-v3 promotion authority changed: "
            f"expected={EXPECTED_AUTHORITY_SHA256}, actual={authority.sha256}"
        )
    document = _strict_json(authority.data, label="Golden-v3 promotion authority")
    schemas_raw = document.get("bound_schemas")
    if not isinstance(schemas_raw, dict) or set(schemas_raw) != {
        "authority",
        "acceptance_receipt",
        "qa_report",
        "production_manifest",
    }:
        raise GoldenV3PromotionError("Golden-v3 bound schema set changed")
    schemas = {
        name: _bind_record(record, label=f"Golden-v3 {name} schema")
        for name, record in schemas_raw.items()
    }
    _schema_errors(document, schemas["authority"], label="Golden-v3 authority")
    implementation_record = document.get("promotion_implementation")
    if (
        not isinstance(implementation_record, dict)
        or set(implementation_record) != {"path", "canonical_self_sha256", "hash_mode"}
        or implementation_record.get("hash_mode") != IMPLEMENTATION_HASH_MODE
        or implementation_record.get("canonical_self_sha256")
        != EXPECTED_IMPLEMENTATION_SELF_SHA256
    ):
        raise GoldenV3PromotionError(
            "Golden-v3 promotion implementation self-binding changed"
        )
    promotion_implementation = _bind(
        implementation_record["path"],
        label="Golden-v3 promotion implementation",
    )
    if promotion_implementation.path != Path(__file__).resolve():
        raise GoldenV3PromotionError("Golden-v3 promotion implementation path changed")
    implementation_sha256 = _implementation_self_sha256(promotion_implementation.data)
    if implementation_sha256 != implementation_record["canonical_self_sha256"]:
        raise GoldenV3PromotionError(
            "Golden-v3 promotion implementation canonical SHA-256 changed"
        )
    authorities = document.get("authorities")
    if not isinstance(authorities, dict) or set(authorities) != {
        "strict_audit",
        "strict_audit_implementation",
        "four_candidate_derivation",
        "four_candidate_generator",
        "balanced_phase_v2",
        "balanced_phase_v2_generator",
        "balanced_open_phase_v3",
        "balanced_open_phase_v3_generator",
    }:
        raise GoldenV3PromotionError("Golden-v3 authority reference set changed")
    strict_authority = _bind_record(
        authorities["strict_audit"], label="Golden-v3 strict audit authority"
    )
    strict_implementation = _bind_record(
        authorities["strict_audit_implementation"],
        label="Golden-v3 strict audit implementation",
    )
    derivation_authority = _bind_record(
        authorities["four_candidate_derivation"],
        label="Golden-v3 four-candidate derivation authority",
    )
    derivation_generator = _bind_record(
        authorities["four_candidate_generator"],
        label="Golden-v3 four-candidate generator",
    )
    balanced_authority = _bind_record(
        authorities["balanced_phase_v2"],
        label="Golden-v3 balanced-phase-v2 authority",
    )
    balanced_generator = _bind_record(
        authorities["balanced_phase_v2_generator"],
        label="Golden-v3 balanced-phase-v2 generator",
    )
    balanced_open_authority = _bind_record(
        authorities["balanced_open_phase_v3"],
        label="Golden-v3 balanced-open-phase-v3 authority",
    )
    balanced_open_generator = _bind_record(
        authorities["balanced_open_phase_v3_generator"],
        label="Golden-v3 balanced-open-phase-v3 generator",
    )
    strict_document = _strict_json(
        strict_authority.data, label="Golden-v3 strict audit authority"
    )
    alpha_record = strict_document.get("alpha_zero_derivation")
    v2_record = strict_document.get("v2_metric_value_source")
    core_record = strict_document.get("strict_core_binding")
    if not all(
        isinstance(record, dict) for record in (alpha_record, v2_record, core_record)
    ):
        raise GoldenV3PromotionError(
            "Golden-v3 strict audit local dependency records changed"
        )
    dependency_specs = (
        (
            {
                "path": alpha_record.get("source_path"),
                "sha256": alpha_record.get("source_sha256"),
            },
            "Golden-v3 strict audit v19 dependency",
            STRICT_AUDIT_V19_MODULE_NAME,
            "scripts/map-production/build_style_candidate_k3_sparse_ridgeline_v19.py",
        ),
        (
            {"path": v2_record.get("path"), "sha256": v2_record.get("sha256")},
            "Golden-v3 strict audit v2 dependency",
            STRICT_AUDIT_V2_MODULE_NAME,
            "scripts/map-production/audit_style_candidate_k3_golden_v2.py",
        ),
        (
            {"path": core_record.get("path"), "sha256": core_record.get("sha256")},
            "Golden-v3 strict audit core dependency",
            STRICT_AUDIT_CORE_MODULE_NAME,
            "scripts/map-production/golden_v3_strict_metric_core.py",
        ),
    )
    strict_dependencies = tuple(
        _bind_record(record, label=label) for record, label, _, _ in dependency_specs
    )
    for binding, (_, label, _, expected_path) in zip(
        strict_dependencies, dependency_specs, strict=True
    ):
        if binding.relative != expected_path:
            raise GoldenV3PromotionError(f"{label} path changed")
    strict_dependency_modules = tuple(
        _load_bound_module(binding, name=module_name)
        for binding, (_, _, module_name, _) in zip(
            strict_dependencies, dependency_specs, strict=True
        )
    )
    if any(
        Path(module.__file__).resolve() != binding.path
        for binding, module in zip(
            strict_dependencies, strict_dependency_modules, strict=True
        )
    ):
        raise GoldenV3PromotionError("Golden-v3 strict audit dependency path changed")
    if strict_implementation.path != STRICT_AUDIT_IMPLEMENTATION_PATH.resolve():
        raise GoldenV3PromotionError("strict-v3 audit implementation path changed")
    strict_module = _load_bound_module(
        strict_implementation,
        name=STRICT_AUDIT_MODULE_NAME,
    )
    if Path(strict_module.__file__).resolve() != strict_implementation.path:
        raise GoldenV3PromotionError("strict-v3 audit implementation path changed")
    if (REPO_ROOT / strict_module.AUTHORITY_PATH).resolve() != strict_authority.path:
        raise GoldenV3PromotionError("strict-v3 audit module authority path changed")
    if strict_authority.sha256 != strict_module.EXPECTED_AUTHORITY_SHA256:
        raise GoldenV3PromotionError("strict-v3 authority identity changed")
    if strict_module.v19 is not strict_dependency_modules[0]:
        raise GoldenV3PromotionError("strict-v3 v19 dependency snapshot changed")
    if strict_module.v2 is not strict_dependency_modules[1]:
        raise GoldenV3PromotionError("strict-v3 v2 dependency snapshot changed")
    if strict_module.strict is not strict_dependency_modules[2]:
        raise GoldenV3PromotionError("strict-v3 core dependency snapshot changed")
    if manifest_cas is None:
        manifest_cas = importlib.import_module("promote_style_candidate_k3_golden_v2")
    if derivation_authority.path != FOUR_CANDIDATE_AUTHORITY_PATH.resolve():
        raise GoldenV3PromotionError("four-candidate derivation authority path changed")
    derivation_module = _load_bound_module(
        derivation_generator,
        name=FOUR_CANDIDATE_MODULE_NAME,
    )
    if Path(derivation_module.__file__).resolve() != derivation_generator.path:
        raise GoldenV3PromotionError("four-candidate generator path changed")
    if Path(derivation_module.AUTHORITY_PATH).resolve() != derivation_authority.path:
        raise GoldenV3PromotionError("four-candidate module authority path changed")
    if derivation_authority.sha256 != derivation_module.AUTHORITY_SHA256:
        raise GoldenV3PromotionError(
            "four-candidate derivation authority identity changed"
        )
    if balanced_authority.path != BALANCED_AUTHORITY_PATH.resolve():
        raise GoldenV3PromotionError("balanced-phase-v2 authority path changed")
    balanced_module = _load_bound_module(
        balanced_generator,
        name=BALANCED_MODULE_NAME,
    )
    if Path(balanced_module.__file__).resolve() != balanced_generator.path:
        raise GoldenV3PromotionError("balanced-phase-v2 generator path changed")
    if Path(balanced_module.AUTHORITY_PATH).resolve() != balanced_authority.path:
        raise GoldenV3PromotionError("balanced-phase-v2 module authority path changed")
    balanced_document = _strict_json(
        balanced_authority.data, label="Golden-v3 balanced-phase-v2 authority"
    )
    try:
        balanced_module.validate_authority(balanced_document)
    except balanced_module.DerivationError as exc:
        raise GoldenV3PromotionError(
            f"balanced-phase-v2 authority validation failed: {exc}"
        ) from exc
    if balanced_open_authority.path != BALANCED_OPEN_AUTHORITY_PATH.resolve():
        raise GoldenV3PromotionError("balanced-open-phase-v3 authority path changed")
    balanced_open_module = _load_bound_module(
        balanced_open_generator,
        name=BALANCED_OPEN_MODULE_NAME,
    )
    if Path(balanced_open_module.__file__).resolve() != balanced_open_generator.path:
        raise GoldenV3PromotionError("balanced-open-phase-v3 module path changed")
    if (
        Path(balanced_open_module.AUTHORITY_PATH).resolve()
        != balanced_open_authority.path
    ):
        raise GoldenV3PromotionError(
            "balanced-open-phase-v3 module authority path changed"
        )
    balanced_open_document = _strict_json(
        balanced_open_authority.data,
        label="Golden-v3 balanced-open-phase-v3 authority",
    )
    try:
        balanced_open_module.validate_authority(balanced_open_document)
    except balanced_open_module.DerivationError as exc:
        raise GoldenV3PromotionError(
            f"balanced-open-phase-v3 authority validation failed: {exc}"
        ) from exc
    return AuthorityBundle(
        binding=authority,
        document=document,
        promotion_implementation=promotion_implementation,
        promotion_implementation_sha256=implementation_sha256,
        strict_authority=strict_authority,
        strict_implementation=strict_implementation,
        strict_module=strict_module,
        strict_dependencies=strict_dependencies,
        strict_dependency_modules=strict_dependency_modules,
        derivation_authority=derivation_authority,
        derivation_generator=derivation_generator,
        derivation_module=derivation_module,
        balanced_authority=balanced_authority,
        balanced_generator=balanced_generator,
        balanced_module=balanced_module,
        balanced_open_authority=balanced_open_authority,
        balanced_open_generator=balanced_open_generator,
        balanced_open_module=balanced_open_module,
        schemas=schemas,
    )


def _require_output_root(path: Path, raw_root: str, *, label: str) -> Path:
    try:
        resolved, relative = require_trackable_path(
            path, label=label, must_exist=False, require_file=True
        )
        root, root_relative = require_trackable_path(
            raw_root, label=f"{label} allowed root", must_exist=True, require_file=False
        )
    except ReleasePathError as exc:
        raise GoldenV3PromotionError(str(exc)) from exc
    try:
        inside = resolved.relative_to(root)
    except ValueError as exc:
        raise GoldenV3PromotionError(
            f"{label} must stay below {root_relative}: {relative}"
        ) from exc
    if inside == Path("."):
        raise GoldenV3PromotionError(f"{label} must name a file below {root_relative}")
    return resolved


def _resolve_output_paths(
    paths: PromotionPaths, authority: AuthorityBundle
) -> tuple[Path, Path, Path]:
    contract = authority.document["output_contract"]
    raw = _require_output_root(paths.raw, contract["raw_root"], label="Golden-v3 raw")
    master = _require_output_root(
        paths.master, contract["master_root"], label="Golden-v3 master"
    )
    receipt = _require_output_root(
        paths.receipt, contract["receipt_root"], label="Golden-v3 acceptance receipt"
    )
    if len({os.path.normcase(os.fspath(item)) for item in (raw, master, receipt)}) != 3:
        raise GoldenV3PromotionError("Golden-v3 outputs must use three distinct paths")
    if raw.suffix.casefold() != ".png" or master.suffix.casefold() != ".png":
        raise GoldenV3PromotionError(
            "Golden-v3 raw and master outputs must be PNG paths"
        )
    if receipt.suffix.casefold() != ".json":
        raise GoldenV3PromotionError("Golden-v3 receipt output must be a JSON path")
    return raw, master, receipt


def _validate_output_paths(paths: PromotionPaths, authority: AuthorityBundle) -> None:
    raw, master, receipt = _resolve_output_paths(paths, authority)
    existing = [item for item in (raw, master, receipt) if os.path.lexists(item)]
    if existing:
        raise GoldenV3PromotionError(
            "Golden-v3 promotion never overwrites an existing output: "
            + ", ".join(os.fspath(item) for item in existing)
        )


def _generation_context(
    authority: AuthorityBundle, generation_contract_id: str
) -> tuple[dict[str, Any], BoundArtifact, BoundArtifact]:
    contracts = authority.document["generation_contract"]["contracts"]
    if generation_contract_id not in GENERATION_CONTRACT_IDS:
        raise GoldenV3PromotionError("Golden-v3 generation contract id is not allowed")
    contract = contracts[generation_contract_id]
    if generation_contract_id == FOUR_CANDIDATE_V1:
        return contract, authority.derivation_authority, authority.derivation_generator
    if generation_contract_id == BALANCED_PHASE_V2:
        return contract, authority.balanced_authority, authority.balanced_generator
    return (
        contract,
        authority.balanced_open_authority,
        authority.balanced_open_generator,
    )


def _validate_generation_payload(
    payload: bytes,
    *,
    authority: AuthorityBundle,
    generation_contract_id: str,
) -> tuple[dict[str, Any], str]:
    contract, generation_authority, _ = _generation_context(
        authority, generation_contract_id
    )
    document = _strict_json(
        generation_authority.data,
        label=f"Golden-v3 {generation_contract_id} authority",
    )
    try:
        if generation_contract_id == FOUR_CANDIDATE_V1:
            seal = authority.derivation_module.validate_output_seal_payload(
                payload, document
            )
            profile = seal["runtime_profile_id"]
        elif generation_contract_id == BALANCED_PHASE_V2:
            seal = authority.balanced_module.validate_output_seal_payload(
                payload, document
            )
            profile = seal["runtime_attestation"]["profile_id"]
        else:
            seal = authority.balanced_open_module.validate_output_seal_payload(
                payload, document
            )
            profile = seal["runtime_attestation"]["profile_id"]
    except (
        authority.derivation_module.DerivationError,
        authority.balanced_module.DerivationError,
        authority.balanced_open_module.DerivationError,
    ) as exc:
        raise GoldenV3PromotionError(str(exc)) from exc
    if seal.get("schema_id") != contract["seal_schema_id"]:
        raise GoldenV3PromotionError("Golden-v3 generation seal schema changed")
    return seal, profile


def _generation_comparable(
    seal: Mapping[str, Any], generation_contract_id: str
) -> dict[str, Any]:
    excluded = (
        "runtime_profile_id"
        if generation_contract_id == FOUR_CANDIDATE_V1
        else "runtime_attestation"
    )
    return {key: value for key, value in seal.items() if key != excluded}


def _validate_generation_set(
    seals: Sequence[dict[str, Any]],
    profiles: Sequence[str],
    *,
    authority: AuthorityBundle,
    generation_contract_id: str,
    candidate_id: str,
    candidate: BoundArtifact,
    require_source_path: bool,
) -> None:
    contract, _, _ = _generation_context(authority, generation_contract_id)
    expected_profiles = contract["required_runtime_profile_ids"]
    if expected_profiles is None:
        if len(set(profiles)) != contract["generation_seal_count"]:
            raise GoldenV3PromotionError(
                "generation seals must use distinct runtime profiles"
            )
    elif set(profiles) != set(expected_profiles) or len(set(profiles)) != len(profiles):
        raise GoldenV3PromotionError(
            "balanced generation seals must use the exact Windows/Linux profiles"
        )
    comparable = [
        _generation_comparable(seal, generation_contract_id) for seal in seals
    ]
    if any(value != comparable[0] for value in comparable[1:]):
        raise GoldenV3PromotionError("cross-profile generation seals disagree")
    candidates = seals[0]["candidates"]
    if [item.get("candidate_id") for item in candidates] != contract["candidate_ids"]:
        raise GoldenV3PromotionError("generation seal candidate ordering changed")
    if [item.get("path") for item in candidates] != contract["output_paths"]:
        raise GoldenV3PromotionError("generation seal output path ordering changed")
    if len({item["candidate_id"] for item in candidates}) != len(candidates):
        raise GoldenV3PromotionError("generation seal candidate ids are not unique")
    if len({item["path"] for item in candidates}) != len(candidates):
        raise GoldenV3PromotionError("generation seal candidate paths are not unique")
    if len({item["sha256"] for item in candidates}) != len(candidates):
        raise GoldenV3PromotionError(
            "generation seal candidate payloads are not unique"
        )
    selected = [item for item in candidates if item["candidate_id"] == candidate_id]
    if len(selected) != 1:
        raise GoldenV3PromotionError("candidate id is not exactly one sealed candidate")
    record = selected[0]
    if (
        (require_source_path and record["path"] != candidate.relative)
        or record["sha256"] != candidate.sha256
        or record["bytes"] != len(candidate.data)
    ):
        raise GoldenV3PromotionError(
            "candidate bytes do not match both generation seals"
        )


def _validate_generation_seals(
    seal_paths: Sequence[Path],
    *,
    authority: AuthorityBundle,
    generation_contract_id: str,
    candidate_id: str,
    candidate: BoundArtifact,
) -> tuple[tuple[BoundArtifact, ...], list[dict[str, str]]]:
    contract, _, _ = _generation_context(authority, generation_contract_id)
    expected_count = contract["generation_seal_count"]
    if len(seal_paths) != expected_count:
        raise GoldenV3PromotionError(
            f"Golden-v3 promotion requires exactly {expected_count} generation seals"
        )
    bindings: list[BoundArtifact] = []
    seals: list[dict[str, Any]] = []
    profiles: list[str] = []
    for index, path in enumerate(seal_paths):
        binding = _bind(
            path, label=f"Golden-v3 generation seal {index + 1}", trackable=False
        )
        seal, profile = _validate_generation_payload(
            binding.data,
            authority=authority,
            generation_contract_id=generation_contract_id,
        )
        bindings.append(binding)
        seals.append(seal)
        profiles.append(profile)
    _validate_generation_set(
        seals,
        profiles,
        authority=authority,
        generation_contract_id=generation_contract_id,
        candidate_id=candidate_id,
        candidate=candidate,
        require_source_path=True,
    )
    summaries = sorted(
        (
            {
                "runtime_profile_id": profile,
                "sha256": binding.sha256,
                "payload_utf8": binding.data.decode("utf-8"),
            }
            for binding, profile in zip(bindings, profiles, strict=True)
        ),
        key=lambda item: item["runtime_profile_id"],
    )
    return tuple(bindings), summaries


def _validate_embedded_generation_seals(
    seals: Any,
    *,
    generation_contract_id: str,
    candidate_id: str,
    master: BoundArtifact,
    authority: AuthorityBundle,
) -> None:
    contract, _, _ = _generation_context(authority, generation_contract_id)
    expected_count = contract["generation_seal_count"]
    if not isinstance(seals, list) or len(seals) != expected_count:
        raise GoldenV3PromotionError("Golden-v3 receipt generation seal count changed")
    documents: list[dict[str, Any]] = []
    profiles: list[str] = []
    for index, summary in enumerate(seals):
        if not isinstance(summary, dict) or set(summary) != {
            "runtime_profile_id",
            "sha256",
            "payload_utf8",
        }:
            raise GoldenV3PromotionError(
                f"Golden-v3 embedded generation seal {index + 1} field set changed"
            )
        payload_text = summary.get("payload_utf8")
        if not isinstance(payload_text, str):
            raise GoldenV3PromotionError(
                f"Golden-v3 embedded generation seal {index + 1} is not UTF-8 text"
            )
        payload = payload_text.encode("utf-8")
        if hashlib.sha256(payload).hexdigest() != summary.get("sha256"):
            raise GoldenV3PromotionError(
                f"Golden-v3 embedded generation seal {index + 1} SHA-256 changed"
            )
        try:
            document, profile = _validate_generation_payload(
                payload,
                authority=authority,
                generation_contract_id=generation_contract_id,
            )
        except GoldenV3PromotionError as exc:
            raise GoldenV3PromotionError(
                f"Golden-v3 embedded generation seal {index + 1} failed: {exc}"
            ) from exc
        if summary.get("runtime_profile_id") != profile:
            raise GoldenV3PromotionError(
                f"Golden-v3 embedded generation seal {index + 1} profile changed"
            )
        documents.append(document)
        profiles.append(profile)
    try:
        _validate_generation_set(
            documents,
            profiles,
            authority=authority,
            generation_contract_id=generation_contract_id,
            candidate_id=candidate_id,
            candidate=master,
            require_source_path=False,
        )
    except GoldenV3PromotionError as exc:
        raise GoldenV3PromotionError(f"Golden-v3 embedded {exc}") from exc


def _recomputed_strict_report(
    candidate_path: Path, *, authority: AuthorityBundle
) -> dict[str, Any]:
    strict_module = authority.strict_module
    try:
        return strict_module.audit_candidate(candidate_path, root=REPO_ROOT)
    except strict_module.GoldenV3StrictAuditError as exc:
        raise GoldenV3PromotionError(f"strict-v3 recomputation failed: {exc}") from exc


def _validate_strict_report(
    binding: BoundArtifact,
    *,
    candidate: BoundArtifact,
    authority: AuthorityBundle,
) -> dict[str, Any]:
    report = _strict_json(binding.data, label="Golden-v3 strict audit report")
    contract = authority.document["strict_audit_contract"]
    exact = {
        "schema_version": contract["report_schema_version"],
        "id": contract["report_id"],
        "algorithm": contract["algorithm"],
        "authority_sha256": authority.strict_authority.sha256,
        "passed": True,
        "failed_gates": [],
        "promotion_or_golden_designation_performed": False,
    }
    for key, expected in exact.items():
        if not _exact_json_equal(report.get(key), expected):
            raise GoldenV3PromotionError(
                f"Golden-v3 strict audit report {key} must be {expected!r}"
            )
    candidate_record = report.get("candidate")
    expected_candidate = {
        "binding": "runtime-only",
        "sha256": candidate.sha256,
        "bytes": len(candidate.data),
        "path_recorded": False,
    }
    if not _exact_json_equal(candidate_record, expected_candidate):
        raise GoldenV3PromotionError(
            "Golden-v3 strict audit candidate binding does not match the selected bytes"
        )
    gates = report.get("gates")
    if (
        not isinstance(gates, dict)
        or not gates
        or not all(value is True for value in gates.values())
    ):
        raise GoldenV3PromotionError("Golden-v3 strict audit gate map is not all-pass")
    if authority.strict_module.canonical_json(report) != binding.data:
        raise GoldenV3PromotionError(
            "Golden-v3 strict audit report bytes are not canonical"
        )
    strict_authority_document = _strict_json(
        authority.strict_authority.data, label="Golden-v3 strict audit authority"
    )
    allowed_profiles = {
        item.get("id")
        for item in strict_authority_document.get("runtime", {}).get(
            "allowed_profiles", []
        )
        if isinstance(item, dict)
    }
    if report.get("runtime_profile") not in allowed_profiles:
        raise GoldenV3PromotionError(
            "Golden-v3 strict audit report runtime profile is not authorized"
        )
    recomputed = _recomputed_strict_report(candidate.path, authority=authority)
    stored_comparable = dict(report)
    recomputed_comparable = dict(recomputed)
    stored_comparable.pop("runtime_profile", None)
    recomputed_comparable.pop("runtime_profile", None)
    if not _exact_json_equal(stored_comparable, recomputed_comparable):
        raise GoldenV3PromotionError(
            "Golden-v3 strict audit report does not equal independently recomputed pixels"
        )
    return report


def _validate_packet(
    binding: BoundArtifact,
    *,
    candidate: BoundArtifact,
    authority: AuthorityBundle,
) -> PacketEvidence:
    packet = _strict_json(binding.data, label="Golden-v3 blind packet")
    if set(packet) != PACKET_KEYS:
        raise GoldenV3PromotionError("Golden-v3 blind packet field set changed")
    review_contract = authority.document["review_contract"]
    packet_contract = review_contract["packet_contract"]
    view_derivation = review_contract["view_derivation"]
    view_specs = view_derivation["views"]
    view_ids = review_contract["exact_five_view_ids"]
    if [item.get("id") for item in view_specs] != view_ids:
        raise GoldenV3PromotionError("Golden-v3 view derivation order changed")
    if (
        packet.get("schema_version") != packet_contract["schema_version"]
        or packet.get("id") != packet_contract["id"]
        or packet.get("job_id") != JOB_ID
        or packet.get("candidate_sha256") != candidate.sha256
        or not _exact_json_equal(packet.get("candidate_bytes"), len(candidate.data))
        or not _exact_json_equal(packet.get("view_order"), view_ids)
    ):
        raise GoldenV3PromotionError("Golden-v3 blind packet identity changed")
    if _canonical_json(packet) != binding.data:
        raise GoldenV3PromotionError("Golden-v3 blind packet bytes are not canonical")
    _parse_timestamp(
        packet.get("created_at"), label="Golden-v3 blind packet created_at"
    )
    views = packet.get("views")
    if not isinstance(views, list) or len(views) != len(view_ids):
        raise GoldenV3PromotionError(
            "Golden-v3 blind packet must contain exact five views"
        )
    bindings: list[BoundArtifact] = []
    for expected_id, record in zip(view_ids, views, strict=True):
        if (
            not isinstance(record, dict)
            or set(record) != PACKET_VIEW_KEYS
            or record.get("id") != expected_id
        ):
            raise GoldenV3PromotionError("Golden-v3 blind packet view order changed")
        bindings.append(
            _bind_record(
                {"path": record["path"], "sha256": record["sha256"]},
                label=f"Golden-v3 blind view {expected_id}",
            )
        )
    if len({item.identity for item in bindings}) != len(bindings):
        raise GoldenV3PromotionError("Golden-v3 blind packet duplicates a view path")
    if len({item.sha256 for item in bindings}) != len(bindings):
        raise GoldenV3PromotionError("Golden-v3 blind packet duplicates a view payload")
    identity = authority.document["identity"]
    source_size = (identity["canvas_width"], identity["canvas_height"])
    strict_module = authority.strict_module
    try:
        source_pixels = strict_module._decode_rgb(
            candidate.data,
            size=source_size,
            label="Golden-v3 promoted master",
            strict_candidate=True,
        )
    except strict_module.GoldenV3StrictAuditError as exc:
        raise GoldenV3PromotionError(
            f"Golden-v3 promoted master PNG contract failed: {exc}"
        ) from exc
    with Image.fromarray(source_pixels) as source_image:
        for spec, view in zip(view_specs, bindings, strict=True):
            crop = spec["crop"]
            working = (
                source_image.copy() if crop is None else source_image.crop(tuple(crop))
            )
            try:
                rendered = working.resize(tuple(spec["size"]), Image.Resampling.LANCZOS)
                try:
                    expected_pixels = np.asarray(rendered, dtype=np.uint8)
                    try:
                        actual_pixels = strict_module._decode_rgb(
                            view.data,
                            size=tuple(spec["size"]),
                            label=f"Golden-v3 blind view {spec['id']}",
                            strict_candidate=True,
                        )
                    except strict_module.GoldenV3StrictAuditError as exc:
                        raise GoldenV3PromotionError(
                            f"Golden-v3 blind view {spec['id']} PNG contract failed: {exc}"
                        ) from exc
                    if not np.array_equal(actual_pixels, expected_pixels):
                        raise GoldenV3PromotionError(
                            f"Golden-v3 blind view {spec['id']} is not derived from the promoted master"
                        )
                finally:
                    rendered.close()
            finally:
                working.close()
    return PacketEvidence(binding=binding, document=packet, views=tuple(bindings))


def _validate_review(
    binding: BoundArtifact,
    *,
    role: str,
    review_image_path: str,
    review_image_sha256: str,
    packet: PacketEvidence,
    authority: AuthorityBundle,
) -> ReviewEvidence:
    report = _strict_json(binding.data, label=f"Golden-v3 review {role}")
    _schema_errors(
        report, authority.schemas["qa_report"], label=f"Golden-v3 review {role}"
    )
    if "automated" in (
        part.casefold() for part in PurePosixPath(binding.relative).parts
    ):
        raise GoldenV3PromotionError(
            "Golden-v3 human review may not be stored under automated QA"
        )
    review_contract = authority.document["review_contract"]
    root = role == review_contract["root_role"]
    threshold = review_contract["acceptance_threshold"]
    exact = {
        "job_id": JOB_ID,
        "image_path": review_image_path,
        "image_sha256": review_image_sha256,
        "status": "complete",
        "golden_reference": not root,
        "review_mode": "self" if root else "blind-independent",
        "acceptance_threshold": threshold,
        "decision": "accepted",
        "required_changes": [],
    }
    for key, expected in exact.items():
        if not _exact_json_equal(report.get(key), expected):
            raise GoldenV3PromotionError(
                f"Golden-v3 review {role} {key} must be {expected!r}"
            )
    expected_packet_attestation = {
        "receipt": _artifact(packet.binding),
        "reviewer_confirmed_exact_five": True,
    }
    if not _exact_json_equal(report.get("vision_bundle"), expected_packet_attestation):
        raise GoldenV3PromotionError(
            f"Golden-v3 review {role} must attest the exact blind packet path/SHA-256"
        )
    reviewer = report.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise GoldenV3PromotionError(f"Golden-v3 review {role} reviewer is empty")
    prefix = f"{role}/"
    if not reviewer.startswith(prefix) or not reviewer[len(prefix) :].strip():
        raise GoldenV3PromotionError(
            f"Golden-v3 reviewer must use canonical {prefix}<id> form"
        )
    try:
        reviewer_identity = canonical_reviewer_identity(reviewer[len(prefix) :])
    except ValueError as exc:
        raise GoldenV3PromotionError(
            f"Golden-v3 review {role} reviewer identity is invalid: {exc}"
        ) from exc
    review_views = report.get("review_views")
    if not isinstance(review_views, list):
        raise GoldenV3PromotionError("Golden-v3 review has no review views")
    seen: set[str] = set()
    ordered_view_ids: list[str] = []
    for view in review_views:
        if (
            not isinstance(view, dict)
            or not isinstance(view.get("id"), str)
            or view["id"] in seen
            or view.get("complete") is not True
            or not isinstance(view.get("evidence"), str)
            or not view["evidence"].strip()
        ):
            raise GoldenV3PromotionError(
                "every Golden-v3 review view must be unique, complete, and evidenced"
            )
        seen.add(view["id"])
        ordered_view_ids.append(view["id"])
    expected_review_views = authority.document["review_contract"]["review_view_ids"]
    if ordered_view_ids != expected_review_views:
        raise GoldenV3PromotionError(
            "Golden-v3 review view order does not equal the frozen review contract"
        )
    failures = report.get("immediate_failures")
    expected_failures = authority.document["review_contract"]["immediate_failure_ids"]
    if (
        not isinstance(failures, list)
        or [item.get("id") if isinstance(item, dict) else None for item in failures]
        != expected_failures
        or any(
            item.get("detected") is not False
            or not isinstance(item.get("evidence"), str)
            or not item["evidence"].strip()
            for item in failures
            if isinstance(item, dict)
        )
    ):
        raise GoldenV3PromotionError(
            "Golden-v3 review immediate-failure evidence failed"
        )
    scores = report.get("scores")
    review_contract = authority.document["review_contract"]
    expected_axes = review_contract["score_axes"]
    axis_count = review_contract["score_axis_count"]
    if (
        not isinstance(scores, list)
        or len(scores) != axis_count
        or not all(isinstance(item, dict) for item in scores)
    ):
        raise GoldenV3PromotionError("Golden-v3 review score axis count changed")
    maxima = [item.get("maximum") for item in scores]
    values = [item.get("score") for item in scores]
    ids = [item.get("id") for item in scores]
    notes = [item.get("notes") for item in scores]
    integer_values = maxima + values
    total = report.get("total_score")
    if (
        not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in integer_values
        )
        or [
            {"id": identifier, "maximum": maximum}
            for identifier, maximum in zip(ids, maxima, strict=True)
        ]
        != expected_axes
        or sum(maxima) != review_contract["score_maximum_total"]
        or not all(isinstance(note, str) and note.strip() for note in notes)
        or any(
            value < 0 or value > maximum
            for value, maximum in zip(values, maxima, strict=True)
        )
        or not isinstance(total, int)
        or isinstance(total, bool)
        or total != sum(values)
        or total < threshold
    ):
        raise GoldenV3PromotionError("Golden-v3 review score contract failed")
    created_at = _parse_timestamp(
        report.get("created_at"), label=f"Golden-v3 review {role} created_at"
    )
    return ReviewEvidence(
        binding=binding,
        document=report,
        role=role,
        reviewer_identity=reviewer_identity,
        score=total,
        created_at=created_at,
    )


def _review_receipt_record(review: ReviewEvidence) -> dict[str, Any]:
    return {
        "role": review.role,
        "path": review.binding.relative,
        "sha256": review.binding.sha256,
        "reviewer": review.document["reviewer"],
        "score": review.score,
        "created_at": review.document["created_at"],
    }


def _validate_review_set(
    root: ReviewEvidence,
    blind: Sequence[ReviewEvidence],
    *,
    packet: PacketEvidence,
    authority: AuthorityBundle,
) -> None:
    contract = authority.document["review_contract"]
    blind_roles = tuple(contract["blind_role_order"])
    if (
        contract["root_review_count"] != 1
        or len(blind) != contract["blind_review_count"]
        or tuple(item.role for item in blind) != blind_roles
    ):
        raise GoldenV3PromotionError(
            "Golden-v3 blind reviews are not in exact role order"
        )
    identities = {root.reviewer_identity, *(item.reviewer_identity for item in blind)}
    reviewer_count = contract["root_review_count"] + contract["blind_review_count"]
    if len(identities) != reviewer_count:
        raise GoldenV3PromotionError(
            "Golden-v3 Root and blind reviewer identities must all be distinct"
        )
    packet_time = _parse_timestamp(
        packet.document["created_at"], label="Golden-v3 blind packet created_at"
    )
    if root.created_at < packet_time:
        raise GoldenV3PromotionError("Golden-v3 Root review predates its blind packet")
    if any(item.created_at <= root.created_at for item in blind):
        raise GoldenV3PromotionError(
            "Golden-v3 blind reviews must occur after Root review"
        )
    if len({item.binding.identity for item in blind}) != contract["blind_review_count"]:
        raise GoldenV3PromotionError(
            "Golden-v3 blind reviews must be distinct artifacts"
        )


def _receipt_document(
    *,
    authority: AuthorityBundle,
    generation_contract_id: str,
    candidate_id: str,
    candidate: BoundArtifact,
    raw: BoundArtifact,
    master: BoundArtifact,
    generation_seals: list[dict[str, str]],
    strict_report: BoundArtifact,
    root_review: ReviewEvidence,
    packet: PacketEvidence,
    blind_reviews: Sequence[ReviewEvidence],
    authorized_by: str,
    accepted_at: str,
) -> dict[str, Any]:
    threshold = authority.document["review_contract"]["acceptance_threshold"]
    _, generation_authority, generation_generator = _generation_context(
        authority, generation_contract_id
    )
    return {
        "$schema": "https://sstory.example/schemas/style-candidate-k3-golden-v3-acceptance-receipt.schema.json",
        "schema_version": "3.0.0",
        "id": "sstory-k3-golden-v3-acceptance-receipt-v3",
        "job_id": JOB_ID,
        "status": "accepted",
        "acceptance_threshold": threshold,
        "candidate_id": candidate_id,
        "candidate": {**_artifact(master), "bytes": len(candidate.data)},
        "raw": _artifact(raw),
        "promotion_authority": _artifact(authority.binding),
        "promotion_implementation": _implementation_artifact(authority),
        "generation_contract_id": generation_contract_id,
        "generation_authority": _artifact(generation_authority),
        "generation_generator": _artifact(generation_generator),
        "generation_seals": generation_seals,
        "strict_audit_authority": _artifact(authority.strict_authority),
        "strict_audit_implementation": _artifact(authority.strict_implementation),
        "strict_audit_report": _artifact(strict_report),
        "root_review": _review_receipt_record(root_review),
        "blind_packet": _artifact(packet.binding),
        "reviews": [_review_receipt_record(item) for item in blind_reviews],
        "authorized_by": authorized_by,
        "accepted_at": accepted_at,
        "promotion_performed": True,
    }


def _input_record(binding: BoundArtifact, role: str) -> dict[str, str]:
    return {**_artifact(binding), "role": role}


def _project_job(
    *,
    authority: AuthorityBundle,
    generation_contract_id: str,
    raw: BoundArtifact,
    master: BoundArtifact,
    strict_report: BoundArtifact,
    root_review: ReviewEvidence,
    packet: PacketEvidence,
    blind_reviews: Sequence[ReviewEvidence],
    receipt: BoundArtifact,
    authorized_by: str,
    accepted_at: str,
) -> dict[str, Any]:
    prepared_at = packet.document["created_at"]
    primary = blind_reviews[0]
    roles = authority.document["manifest_contract"]["input_role_orders"][
        generation_contract_id
    ]
    identity = authority.document["identity"]
    threshold = authority.document["review_contract"]["acceptance_threshold"]
    manifest_contract = authority.document["manifest_contract"]
    _, generation_authority, generation_generator = _generation_context(
        authority, generation_contract_id
    )
    bindings: list[BoundArtifact | None] = [
        raw,
        authority.binding,
        None,
        generation_authority,
    ]
    bindings.append(generation_generator)
    bindings.extend(
        (
            authority.strict_authority,
            authority.strict_implementation,
            strict_report,
            root_review.binding,
            packet.binding,
            blind_reviews[0].binding,
            blind_reviews[1].binding,
            receipt,
        )
    )
    inputs = [
        (
            {**_implementation_artifact(authority), "role": role}
            if binding is None
            else _input_record(binding, role)
        )
        for binding, role in zip(bindings, roles, strict=True)
    ]
    if inputs[2]["role"] != V3_PROMOTION_IMPLEMENTATION_ROLE:
        raise GoldenV3PromotionError(
            "Golden-v3 promotion implementation manifest role changed"
        )
    history_states = authority.document["manifest_contract"]["history_state_order"]
    return {
        "id": JOB_ID,
        "sheet_id": identity["sheet_id"],
        "status": "accepted",
        "bounds": dict(manifest_contract["bounds"]),
        "zoom": dict(manifest_contract["zoom"]),
        "acceptance_threshold": threshold,
        "inputs": inputs,
        "generation": dict(
            manifest_contract["generation_by_contract"][generation_contract_id]
        ),
        "master": {
            **_artifact(master),
            "width": identity["canvas_width"],
            "height": identity["canvas_height"],
            "color_profile": identity["color_profile"],
        },
        "qa": {
            "automated": {"status": "passed", "report_path": strict_report.relative},
            "vision": {
                "decision": "accepted",
                "score": primary.score,
                "report_path": primary.binding.relative,
                "reviewer": primary.document["reviewer"],
                "reviewed_at": primary.document["created_at"],
            },
        },
        "history": [
            {
                "state": state,
                "at": prepared_at if index < 4 else accepted_at,
                "actor": authorized_by,
            }
            for index, state in enumerate(history_states)
        ],
        "notes": manifest_contract["notes"],
    }


def _manifest_roles(job: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    inputs = job.get("inputs")
    if not isinstance(inputs, list):
        raise GoldenV3PromotionError("Golden-v3 manifest inputs must be an array")
    roles: list[str] = []
    by_role: dict[str, Any] = {}
    for item in inputs:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "role"}:
            raise GoldenV3PromotionError(
                "Golden-v3 manifest inputs must be exact artifacts"
            )
        role = item.get("role")
        if not isinstance(role, str) or role in by_role:
            raise GoldenV3PromotionError(
                "Golden-v3 manifest input roles must be unique"
            )
        roles.append(role)
        by_role[role] = item
    return roles, by_role


def _same_artifact(left: Any, right: Any) -> bool:
    return (
        isinstance(left, dict)
        and isinstance(right, dict)
        and left.get("path") == right.get("path")
        and left.get("sha256") == right.get("sha256")
    )


def _validate_receipt_links(
    receipt: dict[str, Any],
    *,
    authority: AuthorityBundle,
    generation_contract_id: str,
    master: BoundArtifact,
    raw: BoundArtifact,
    strict_report: BoundArtifact,
    root_review: ReviewEvidence,
    packet: PacketEvidence,
    blind_reviews: Sequence[ReviewEvidence],
) -> None:
    _schema_errors(
        receipt,
        authority.schemas["acceptance_receipt"],
        label="Golden-v3 acceptance receipt",
    )
    receipt_contract = authority.document["receipt_contract"]
    expected_header = {
        "schema_version": receipt_contract["schema_version"],
        "id": receipt_contract["id"],
        "status": receipt_contract["status"],
        "promotion_performed": receipt_contract["promotion_performed"],
        "job_id": JOB_ID,
        "acceptance_threshold": authority.document["review_contract"][
            "acceptance_threshold"
        ],
    }
    if any(
        not _exact_json_equal(receipt.get(key), expected)
        for key, expected in expected_header.items()
    ):
        raise GoldenV3PromotionError("Golden-v3 receipt frozen header changed")
    _, generation_authority, generation_generator = _generation_context(
        authority, generation_contract_id
    )
    exact_artifacts = {
        "candidate": _artifact(master),
        "raw": _artifact(raw),
        "promotion_authority": _artifact(authority.binding),
        "promotion_implementation": _implementation_artifact(authority),
        "generation_authority": _artifact(generation_authority),
        "strict_audit_authority": _artifact(authority.strict_authority),
        "strict_audit_implementation": _artifact(authority.strict_implementation),
        "strict_audit_report": _artifact(strict_report),
        "blind_packet": _artifact(packet.binding),
    }
    for key, expected in exact_artifacts.items():
        actual = receipt.get(key)
        if key == "candidate" and isinstance(actual, dict):
            actual = {name: actual.get(name) for name in ("path", "sha256")}
        if not _exact_json_equal(actual, expected):
            raise GoldenV3PromotionError(f"Golden-v3 receipt {key} binding changed")
    expected_generator = _artifact(generation_generator)
    if receipt.get("generation_contract_id") != generation_contract_id:
        raise GoldenV3PromotionError(
            "Golden-v3 receipt generation discriminator changed"
        )
    if not _exact_json_equal(receipt.get("generation_generator"), expected_generator):
        raise GoldenV3PromotionError("Golden-v3 receipt generation generator changed")
    candidate_bytes = receipt["candidate"].get("bytes")
    if type(candidate_bytes) is not int or candidate_bytes != len(master.data):
        raise GoldenV3PromotionError("Golden-v3 receipt candidate byte count changed")
    expected_root = _review_receipt_record(root_review)
    expected_reviews = [_review_receipt_record(item) for item in blind_reviews]
    if not _exact_json_equal(
        receipt.get("root_review"), expected_root
    ) or not _exact_json_equal(receipt.get("reviews"), expected_reviews):
        raise GoldenV3PromotionError("Golden-v3 receipt review summary changed")


def _validate_accepted_job(
    golden_style: Mapping[str, str],
    manifest: Mapping[str, Any],
    *,
    authority: AuthorityBundle,
) -> dict[str, Any]:
    _schema_errors(
        dict(manifest),
        authority.schemas["production_manifest"],
        label="production manifest",
    )
    jobs = manifest.get("jobs")
    matches = (
        [job for job in jobs if isinstance(job, dict) and job.get("id") == JOB_ID]
        if isinstance(jobs, list)
        else []
    )
    if len(matches) != 1:
        raise GoldenV3PromotionError(
            "production manifest must contain exactly one Golden-v3 job"
        )
    job = matches[0]
    master_record = job.get("master")
    identity = authority.document["identity"]
    threshold = authority.document["review_contract"]["acceptance_threshold"]
    manifest_contract = authority.document["manifest_contract"]
    if not _same_artifact(master_record, golden_style):
        raise GoldenV3PromotionError(
            "Golden-v3 manifest master does not match golden_style"
        )
    if (
        job.get("sheet_id") != identity["sheet_id"]
        or job.get("status") != "accepted"
        or not _exact_json_equal(job.get("acceptance_threshold"), threshold)
        or not _exact_json_equal(job.get("bounds"), manifest_contract["bounds"])
        or not _exact_json_equal(job.get("zoom"), manifest_contract["zoom"])
        or job.get("notes") != manifest_contract["notes"]
        or not isinstance(master_record, dict)
        or not _exact_json_equal(master_record.get("width"), identity["canvas_width"])
        or not _exact_json_equal(master_record.get("height"), identity["canvas_height"])
        or master_record.get("color_profile") != identity["color_profile"]
    ):
        raise GoldenV3PromotionError("Golden-v3 manifest accepted identity changed")
    roles, by_role = _manifest_roles(job)
    role_orders = authority.document["manifest_contract"]["input_role_orders"]
    matches = [
        contract_id
        for contract_id in GENERATION_CONTRACT_IDS
        if roles == role_orders[contract_id]
    ]
    if len(matches) != 1:
        raise GoldenV3PromotionError("Golden-v3 manifest input role order changed")
    generation_contract_id = matches[0]
    if not _exact_json_equal(
        job.get("generation"),
        manifest_contract["generation_by_contract"][generation_contract_id],
    ):
        raise GoldenV3PromotionError("Golden-v3 manifest generation identity changed")
    bound = {
        role: _bind_record(
            {"path": record["path"], "sha256": record["sha256"]},
            label=f"Golden-v3 manifest {role}",
        )
        for role, record in by_role.items()
        if role != V3_PROMOTION_IMPLEMENTATION_ROLE
    }
    if bound[V3_PROMOTION_AUTHORITY_ROLE].sha256 != authority.binding.sha256:
        raise GoldenV3PromotionError("Golden-v3 manifest promotion authority changed")
    implementation_record = by_role[V3_PROMOTION_IMPLEMENTATION_ROLE]
    if {
        "path": implementation_record["path"],
        "sha256": implementation_record["sha256"],
    } != _implementation_artifact(authority):
        raise GoldenV3PromotionError(
            "Golden-v3 manifest promotion implementation changed"
        )
    contract, generation_authority, generation_generator = _generation_context(
        authority, generation_contract_id
    )
    authority_role = contract["manifest_authority_role"]
    if bound[authority_role].sha256 != generation_authority.sha256:
        raise GoldenV3PromotionError("Golden-v3 manifest generation authority changed")
    generator_role = contract["manifest_generator_role"]
    if (
        not isinstance(generator_role, str)
        or bound[generator_role].sha256 != generation_generator.sha256
    ):
        raise GoldenV3PromotionError("Golden-v3 manifest generation generator changed")
    if bound[V3_STRICT_AUTHORITY_ROLE].sha256 != authority.strict_authority.sha256:
        raise GoldenV3PromotionError("Golden-v3 manifest strict authority changed")
    if (
        bound[V3_STRICT_IMPLEMENTATION_ROLE].sha256
        != authority.strict_implementation.sha256
    ):
        raise GoldenV3PromotionError("Golden-v3 manifest strict implementation changed")
    master = _bind_record(
        {"path": master_record["path"], "sha256": master_record["sha256"]},
        label="Golden-v3 manifest master",
    )
    raw = bound[RAW_ROLE]
    receipt_binding = bound[V3_ACCEPTANCE_RECEIPT_ROLE]
    _resolve_output_paths(
        PromotionPaths(raw=raw.path, master=master.path, receipt=receipt_binding.path),
        authority,
    )
    if (
        same_path(raw.path, master.path)
        or raw.sha256 != master.sha256
        or raw.data != master.data
    ):
        raise GoldenV3PromotionError(
            "Golden-v3 raw/master byte identity contract failed"
        )
    strict_report = bound[V3_STRICT_REPORT_ROLE]
    _validate_strict_report(strict_report, candidate=master, authority=authority)
    packet = _validate_packet(
        bound[BLIND_PACKET_ROLE],
        candidate=master,
        authority=authority,
    )
    root_review = _validate_review(
        bound[V3_ROOT_REVIEW_ROLE],
        role=V3_ROOT_REVIEW_ROLE,
        review_image_path=master.relative,
        review_image_sha256=master.sha256,
        packet=packet,
        authority=authority,
    )
    blind_reviews = tuple(
        _validate_review(
            bound[role],
            role=role,
            review_image_path=master.relative,
            review_image_sha256=master.sha256,
            packet=packet,
            authority=authority,
        )
        for role in authority.document["review_contract"]["blind_role_order"]
    )
    _validate_review_set(root_review, blind_reviews, packet=packet, authority=authority)
    receipt = _strict_json(receipt_binding.data, label="Golden-v3 acceptance receipt")
    if _canonical_json(receipt) != receipt_binding.data:
        raise GoldenV3PromotionError(
            "Golden-v3 acceptance receipt bytes are not canonical"
        )
    _validate_receipt_links(
        receipt,
        authority=authority,
        generation_contract_id=generation_contract_id,
        master=master,
        raw=raw,
        strict_report=strict_report,
        root_review=root_review,
        packet=packet,
        blind_reviews=blind_reviews,
    )
    generation_document = _strict_json(
        generation_authority.data,
        label=f"Golden-v3 {generation_contract_id} authority",
    )
    candidate_ids = {
        item.get("candidate_id")
        for item in generation_document.get("candidates", {}).get("records", [])
        if isinstance(item, dict)
    }
    candidate_id = receipt.get("candidate_id")
    if candidate_id not in candidate_ids:
        raise GoldenV3PromotionError(
            "Golden-v3 receipt candidate id is not preregistered"
        )
    _validate_embedded_generation_seals(
        receipt.get("generation_seals"),
        generation_contract_id=generation_contract_id,
        candidate_id=candidate_id,
        master=master,
        authority=authority,
    )
    accepted_at = _parse_timestamp(
        receipt.get("accepted_at"), label="Golden-v3 acceptance receipt accepted_at"
    )
    if any(review.created_at > accepted_at for review in blind_reviews):
        raise GoldenV3PromotionError("Golden-v3 acceptance predates a blind review")
    qa = job.get("qa")
    automated = qa.get("automated") if isinstance(qa, dict) else None
    vision = qa.get("vision") if isinstance(qa, dict) else None
    primary = blind_reviews[0]
    if (
        not isinstance(automated, dict)
        or not _exact_json_equal(
            automated,
            {"status": "passed", "report_path": strict_report.relative},
        )
        or not isinstance(vision, dict)
        or vision.get("decision") != "accepted"
        or not _exact_json_equal(vision.get("score"), primary.score)
        or vision.get("report_path") != primary.binding.relative
        or vision.get("reviewer") != primary.document["reviewer"]
        or vision.get("reviewed_at") != primary.document["created_at"]
    ):
        raise GoldenV3PromotionError("Golden-v3 manifest QA projection changed")
    history = job.get("history")
    expected_states = authority.document["manifest_contract"]["history_state_order"]
    if (
        not isinstance(history, list)
        or [item.get("state") if isinstance(item, dict) else None for item in history]
        != expected_states
    ):
        raise GoldenV3PromotionError("Golden-v3 manifest history state order changed")
    history_times = [
        _parse_timestamp(item.get("at"), label="Golden-v3 manifest history timestamp")
        for item in history
    ]
    if any(later < earlier for earlier, later in zip(history_times, history_times[1:])):
        raise GoldenV3PromotionError("Golden-v3 manifest history is not chronological")
    packet_time = _parse_timestamp(
        packet.document["created_at"], label="Golden-v3 blind packet created_at"
    )
    if any(value != packet_time for value in history_times[:4]):
        raise GoldenV3PromotionError(
            "Golden-v3 pre-Vision history timestamps must equal the blind packet"
        )
    if history_times[-1] != accepted_at or history_times[-2] != accepted_at:
        raise GoldenV3PromotionError("Golden-v3 manifest acceptance timestamp changed")
    if any(item.get("actor") != receipt.get("authorized_by") for item in history):
        raise GoldenV3PromotionError(
            "Golden-v3 manifest history actor differs from the acceptance receipt"
        )
    return {
        "evidence_contract_version": "v3",
        "generation_contract_id": generation_contract_id,
        "job_id": JOB_ID,
        "master": _artifact(master),
        "vision_report": primary.binding.relative,
        "vision_report_artifact": _artifact(primary.binding),
        "manifest_vision_reports": [_artifact(item.binding) for item in blind_reviews],
        "review_target": _artifact(master),
        "score": primary.score,
        "reviewer": primary.document["reviewer"],
        "threshold": threshold,
        "acceptance_receipt": _artifact(receipt_binding),
        "blind_packet": _artifact(packet.binding),
        "blind_packet_views": [_artifact(item) for item in packet.views],
    }


def verify_accepted_manifest_golden_v3(
    golden_style: Mapping[str, str], manifest_path: Path
) -> dict[str, Any]:
    authority = load_authority()
    manifest_binding = _bind(manifest_path, label="Golden-v3 production manifest")
    manifest = _strict_json(
        manifest_binding.data, label="Golden-v3 production manifest"
    )
    return _validate_accepted_job(golden_style, manifest, authority=authority)


def _stat_signature(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _stat_is_reparse(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def _windows_open_directory(path: Path) -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    handle = create_file(
        os.fspath(path),
        0x0001 | 0x0080,  # FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES
        0x0001 | 0x0002,  # share read/write, but never delete
        None,
        3,  # OPEN_EXISTING
        0x02000000 | 0x00200000,
        # FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in {None, invalid}:
        error_number = ctypes.get_last_error()
        raise OSError(error_number, ctypes.FormatError(error_number), path)
    return int(handle)


def _windows_directory_identity(handle: int) -> tuple[int, int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_WindowsFileInformation),
    ]
    get_information.restype = ctypes.c_int
    information = _WindowsFileInformation()
    if not get_information(ctypes.c_void_p(handle), ctypes.byref(information)):
        error_number = ctypes.get_last_error()
        raise OSError(error_number, ctypes.FormatError(error_number))
    if not information.attributes & 0x10 or information.attributes & 0x400:
        raise GoldenV3PromotionError(
            "Golden-v3 output ancestor is not a plain directory"
        )
    inode = (information.file_index_high << 32) | information.file_index_low
    return information.volume_serial, inode


def _windows_close_handle(handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    if not close_handle(ctypes.c_void_p(handle)):
        error_number = ctypes.get_last_error()
        raise OSError(error_number, ctypes.FormatError(error_number))


def _close_parent_anchor(anchor: _ParentAnchor) -> None:
    first_error: OSError | None = None
    while anchor.linux_fds:
        try:
            os.close(anchor.linux_fds.pop())
        except OSError as exc:
            first_error = first_error or exc
    while anchor.windows_handles:
        try:
            _windows_close_handle(anchor.windows_handles.pop())
        except OSError as exc:
            first_error = first_error or exc
    if first_error is not None:
        raise first_error


def _open_parent_anchor(parent: Path, *, label: str) -> _ParentAnchor:
    if not os.path.lexists(parent):
        raise GoldenV3PromotionError(
            f"{label} parent must already exist before promotion: {parent}"
        )
    try:
        assert_no_reparse_components(parent, label=f"{label} parent")
        lexical_parent = Path(os.path.abspath(os.fspath(parent)))
        resolved_parent = lexical_parent.resolve(strict=True)
        root = REPO_ROOT.resolve(strict=True)
        relative = resolved_parent.relative_to(root)
        metadata = os.lstat(lexical_parent)
    except (OSError, ValueError, ReleasePathError) as exc:
        raise GoldenV3PromotionError(f"cannot anchor {label} parent: {exc}") from exc
    if (
        not same_path(lexical_parent, resolved_parent)
        or not stat.S_ISDIR(metadata.st_mode)
        or _stat_is_reparse(metadata)
    ):
        raise GoldenV3PromotionError(f"{label} parent is not a plain directory")
    anchor = _ParentAnchor(
        path=resolved_parent,
        identity=(metadata.st_dev, metadata.st_ino),
        linux_fds=[],
        windows_handles=[],
        windows_identities=[],
    )
    try:
        if sys.platform.startswith("linux"):
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(root, flags)
            anchor.linux_fds.append(descriptor)
            for part in relative.parts:
                descriptor = os.open(part, flags, dir_fd=descriptor)
                anchor.linux_fds.append(descriptor)
            opened = os.fstat(anchor.parent_fd)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != anchor.identity
            ):
                raise GoldenV3PromotionError(f"{label} parent identity changed")
        elif os.name == "nt":
            current = root
            for part in (None, *relative.parts):
                if part is not None:
                    current /= part
                handle = _windows_open_directory(current)
                anchor.windows_handles.append(handle)
                anchor.windows_identities.append(_windows_directory_identity(handle))
            if anchor.windows_identities[-1][1] != anchor.identity[1]:
                raise GoldenV3PromotionError(f"{label} parent identity changed")
        else:
            raise GoldenV3PromotionError(
                "Golden-v3 anchored writes require Windows or Linux"
            )
        _assert_parent_anchor(anchor, label=label)
        return anchor
    except BaseException:
        try:
            _close_parent_anchor(anchor)
        except OSError:
            pass
        raise


def _assert_parent_anchor(anchor: _ParentAnchor, *, label: str) -> None:
    try:
        assert_no_reparse_components(anchor.path, label=f"{label} parent")
        metadata = os.lstat(anchor.path)
    except (OSError, ReleasePathError) as exc:
        raise GoldenV3PromotionError(
            f"{label} parent anchor disappeared: {exc}"
        ) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or _stat_is_reparse(metadata)
        or (metadata.st_dev, metadata.st_ino) != anchor.identity
    ):
        raise GoldenV3PromotionError(f"{label} parent anchor identity changed")
    if anchor.parent_fd is not None:
        opened = os.fstat(anchor.parent_fd)
        if (opened.st_dev, opened.st_ino) != anchor.identity:
            raise GoldenV3PromotionError(f"{label} parent handle identity changed")
    elif anchor.windows_handles:
        current = [
            _windows_directory_identity(handle) for handle in anchor.windows_handles
        ]
        if current != anchor.windows_identities:
            raise GoldenV3PromotionError(f"{label} ancestor handle identity changed")


def _before_output_open_hook(path: Path) -> None:
    """Test seam invoked only while the output parent chain is anchored."""


def _lstat_from_anchor(anchor: _ParentAnchor, name: str) -> os.stat_result:
    if anchor.parent_fd is not None:
        return os.stat(name, dir_fd=anchor.parent_fd, follow_symlinks=False)
    return os.stat(anchor.path / name, follow_symlinks=False)


def _open_from_anchor(anchor: _ParentAnchor, name: str, flags: int) -> int:
    if anchor.parent_fd is not None:
        return os.open(name, flags, 0o600, dir_fd=anchor.parent_fd)
    return os.open(anchor.path / name, flags, 0o600)


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("short write while creating Golden-v3 output")
        remaining = remaining[written:]


def _write_exclusive(path: Path, payload: bytes, *, label: str) -> _CreatedOutput:
    try:
        resolved, _ = require_trackable_path(
            path, label=label, must_exist=False, require_file=True
        )
    except ReleasePathError as exc:
        raise GoldenV3PromotionError(str(exc)) from exc
    anchor = _open_parent_anchor(resolved.parent, label=label)
    descriptor: int | None = None
    signature: tuple[int, int, int, int] | None = None
    try:
        _before_output_open_hook(resolved)
        _assert_parent_anchor(anchor, label=label)
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = _open_from_anchor(anchor, resolved.name, flags)
        initial = os.fstat(descriptor)
        if (
            not stat.S_ISREG(initial.st_mode)
            or _stat_is_reparse(initial)
            or initial.st_nlink != 1
        ):
            raise GoldenV3PromotionError(f"{label} is not a new plain file")
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        final = os.fstat(descriptor)
        visible = _lstat_from_anchor(anchor, resolved.name)
        signature = _stat_signature(final)
        if (
            not stat.S_ISREG(final.st_mode)
            or _stat_is_reparse(final)
            or final.st_nlink != 1
            or signature != _stat_signature(visible)
            or final.st_size != len(payload)
        ):
            raise GoldenV3PromotionError(f"{label} changed during exclusive creation")
        os.close(descriptor)
        descriptor = None
        _assert_parent_anchor(anchor, label=label)
        binding = _bind(resolved, label=label)
        if binding.signature != signature or binding.data != payload:
            raise GoldenV3PromotionError(
                f"{label} bytes changed after exclusive creation"
            )
        return _CreatedOutput(binding=binding)
    except FileExistsError as exc:
        raise GoldenV3PromotionError(f"refusing to overwrite existing {label}") from exc
    finally:
        if descriptor is not None:
            try:
                final = os.fstat(descriptor)
                signature = _stat_signature(final)
            except OSError:
                pass
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            _close_parent_anchor(anchor)
        except OSError:
            pass


def _cleanup_created(created: Sequence[_CreatedOutput]) -> None:
    # Completed output names are predictable. Once their creation handles are
    # closed, no portable unlink-by-name operation can prove that the visible
    # basename is still the inode created by this transaction at the instant
    # of deletion. Retain fail-closed debris rather than risk deleting an
    # exchanged user file; every future attempt refuses to overwrite it.
    del created


def promote_candidate(
    *,
    generation_contract_id: str,
    candidate_id: str,
    candidate_path: Path,
    generation_seal_paths: Sequence[Path],
    strict_audit_report_path: Path,
    root_review_path: Path,
    blind_packet_path: Path,
    review_paths: Sequence[Path],
    authorized_by: str,
    paths: PromotionPaths = PromotionPaths(),
) -> dict[str, Any]:
    actor = authorized_by.strip()
    if not actor:
        raise GoldenV3PromotionError("authorized_by must be non-empty")
    authority = load_authority()
    _require_active_generation_contract(authority, generation_contract_id)
    _generation_context(authority, generation_contract_id)
    blind_roles = tuple(authority.document["review_contract"]["blind_role_order"])
    if len(review_paths) != authority.document["review_contract"]["blind_review_count"]:
        raise GoldenV3PromotionError(
            f"Golden-v3 promotion requires exactly {len(blind_roles)} blind reviews"
        )
    _validate_output_paths(paths, authority)
    manifest_binding = _bind(paths.manifest, label="Golden-v3 production manifest")
    manifest = _strict_json(
        manifest_binding.data, label="Golden-v3 production manifest"
    )
    _schema_errors(
        manifest, authority.schemas["production_manifest"], label="production manifest"
    )
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list):
        raise GoldenV3PromotionError("production manifest jobs must be an array")
    if any(isinstance(job, dict) and job.get("id") == JOB_ID for job in jobs):
        raise GoldenV3PromotionError(
            "refusing to replace an existing Golden-v3 manifest job"
        )
    candidate = _bind(
        candidate_path, label="runtime Golden-v3 candidate", trackable=False
    )
    if any(
        isinstance(job, dict)
        and job.get("status") in {"accepted", "tiled", "staging", "published"}
        and isinstance(job.get("master"), dict)
        and job["master"].get("sha256") == candidate.sha256
        for job in jobs
    ):
        raise GoldenV3PromotionError("candidate SHA-256 was previously accepted")
    seal_bindings, seal_summaries = _validate_generation_seals(
        generation_seal_paths,
        authority=authority,
        generation_contract_id=generation_contract_id,
        candidate_id=candidate_id,
        candidate=candidate,
    )
    strict_report = _bind(
        strict_audit_report_path, label="Golden-v3 strict audit report"
    )
    _validate_strict_report(strict_report, candidate=candidate, authority=authority)
    packet_binding = _bind(blind_packet_path, label="Golden-v3 blind packet")
    packet = _validate_packet(
        packet_binding,
        candidate=candidate,
        authority=authority,
    )
    root_binding = _bind(root_review_path, label="Golden-v3 Root review")
    root_review = _validate_review(
        root_binding,
        role=V3_ROOT_REVIEW_ROLE,
        review_image_path=canonical_repo_relative(
            paths.master, label="Golden-v3 planned master"
        )[1],
        review_image_sha256=candidate.sha256,
        packet=packet,
        authority=authority,
    )
    blind_reviews = tuple(
        _validate_review(
            _bind(path, label=f"Golden-v3 blind review {role}"),
            role=role,
            review_image_path=canonical_repo_relative(
                paths.master, label="Golden-v3 planned master"
            )[1],
            review_image_sha256=candidate.sha256,
            packet=packet,
            authority=authority,
        )
        for path, role in zip(review_paths, blind_roles, strict=True)
    )
    _validate_review_set(root_review, blind_reviews, packet=packet, authority=authority)
    accepted_at = utc_now()
    accepted_datetime = _parse_timestamp(
        accepted_at, label="Golden-v3 system acceptance time"
    )
    if any(review.created_at > accepted_datetime for review in blind_reviews):
        raise GoldenV3PromotionError("system acceptance time predates a blind review")

    created: list[_CreatedOutput] = []
    commit_started = False
    try:
        raw_output = _write_exclusive(paths.raw, candidate.data, label="Golden-v3 raw")
        raw = raw_output.binding
        created.append(raw_output)
        master_output = _write_exclusive(
            paths.master, candidate.data, label="Golden-v3 master"
        )
        master = master_output.binding
        created.append(master_output)
        receipt_document = _receipt_document(
            authority=authority,
            generation_contract_id=generation_contract_id,
            candidate_id=candidate_id,
            candidate=candidate,
            raw=raw,
            master=master,
            generation_seals=seal_summaries,
            strict_report=strict_report,
            root_review=root_review,
            packet=packet,
            blind_reviews=blind_reviews,
            authorized_by=actor,
            accepted_at=accepted_at,
        )
        _schema_errors(
            receipt_document,
            authority.schemas["acceptance_receipt"],
            label="Golden-v3 acceptance receipt",
        )
        receipt_payload = _canonical_json(receipt_document)
        receipt_output = _write_exclusive(
            paths.receipt, receipt_payload, label="Golden-v3 acceptance receipt"
        )
        receipt = receipt_output.binding
        created.append(receipt_output)
        job = _project_job(
            authority=authority,
            generation_contract_id=generation_contract_id,
            raw=raw,
            master=master,
            strict_report=strict_report,
            root_review=root_review,
            packet=packet,
            blind_reviews=blind_reviews,
            receipt=receipt,
            authorized_by=actor,
            accepted_at=accepted_at,
        )
        projected = dict(manifest)
        projected["jobs"] = [*jobs, job]
        projected["updated_at"] = accepted_at
        _validate_accepted_job(_artifact(master), projected, authority=authority)
        all_bindings: Iterable[BoundArtifact] = (
            manifest_binding,
            authority.binding,
            authority.promotion_implementation,
            authority.strict_authority,
            authority.strict_implementation,
            *authority.strict_dependencies,
            authority.derivation_authority,
            authority.derivation_generator,
            authority.balanced_authority,
            authority.balanced_generator,
            authority.balanced_open_authority,
            authority.balanced_open_generator,
            *authority.schemas.values(),
            candidate,
            *seal_bindings,
            strict_report,
            packet.binding,
            *packet.views,
            root_review.binding,
            *(item.binding for item in blind_reviews),
            raw,
            master,
            receipt,
        )
        try:
            assert_bindings_unchanged(all_bindings)
        except BoundArtifactError as exc:
            raise GoldenV3PromotionError(str(exc)) from exc
        try:
            commit_started = True
            commit = manifest_cas._conditional_manifest_replace(
                paths.manifest, projected, expected=manifest_binding
            )
        except manifest_cas.ManifestCommitStateUnknownError as exc:
            raise GoldenV3ManifestCommitUnknownError(str(exc)) from exc
        except manifest_cas.K3GoldenPromotionV2Error as exc:
            raise GoldenV3PromotionError(str(exc)) from exc
        return {
            "status": "accepted",
            "job_id": JOB_ID,
            "candidate_id": candidate_id,
            "generation_contract_id": generation_contract_id,
            "master": _artifact(master),
            "receipt": _artifact(receipt),
            "review_target": _artifact(master),
            "reviews": [_artifact(item.binding) for item in blind_reviews],
            "manifest_commit": {
                "status": "committed",
                "cleanup_status": commit.cleanup_status,
                "debris": list(commit.debris),
                "cleanup_failures": list(commit.cleanup_failures),
            },
        }
    except GoldenV3ManifestCommitUnknownError:
        raise
    except BaseException:
        if not commit_started:
            _cleanup_created(created)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generation-contract",
        required=True,
        choices=(ACTIVE_GENERATION_CONTRACT_ID,),
        dest="generation_contract_id",
    )
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument(
        "--generation-seal",
        required=True,
        action="append",
        type=Path,
        dest="generation_seals",
        help="exactly two distinct-runtime output seals",
    )
    parser.add_argument("--strict-audit-report", required=True, type=Path)
    parser.add_argument("--root-review", required=True, type=Path)
    parser.add_argument("--blind-packet", required=True, type=Path)
    parser.add_argument("--review-a", required=True, type=Path)
    parser.add_argument("--review-b", required=True, type=Path)
    parser.add_argument("--authorized-by", required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = promote_candidate(
            generation_contract_id=args.generation_contract_id,
            candidate_id=args.candidate_id,
            candidate_path=args.candidate,
            generation_seal_paths=args.generation_seals,
            strict_audit_report_path=args.strict_audit_report,
            root_review_path=args.root_review,
            blind_packet_path=args.blind_packet,
            review_paths=(args.review_a, args.review_b),
            authorized_by=args.authorized_by,
            paths=PromotionPaths(manifest=args.manifest),
        )
    except GoldenV3PromotionError as exc:
        parser.exit(2, f"Golden-v3 promotion failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
