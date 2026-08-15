from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import secrets
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_ROOT = REPO_ROOT / "scripts" / "map-production" / "microtexture-v2-r6"
DEV_ROOT = REPO_ROOT / "tmp" / "map-production" / "microtexture-v2-r6-dev-r17"
FORMAL_ROOT = REPO_ROOT / "tmp" / "map-production" / "microtexture-v2-r6-artifacts"
PRIVATE_ANALYSIS_ROOT = DEV_ROOT / "private" / "analysis"
FORMAL_ENVIRONMENT = (
    "MICROTEXTURE_V2_R6_BLIND_KEY",
    "MICROTEXTURE_V2_R6_ARTIFACT_ROOT",
)
DEVELOPMENT_EDITION = "r17"
EXPECTED_RECORDS_PER_SPLIT = 220
EXPECTED_ARTIFACT_RECORDS_PER_SPLIT = 200
EXPECTED_ARTIFACT_CLUSTERS_PER_SPLIT = 100
EXPECTED_REVIEW_PAGES_PER_SPLIT = 37
EXPECTED_CONTACT_SHEETS_PER_SPLIT = 185
REVIEW_ROWS_PER_PAGE = 6
REVIEW_HEADER_HEIGHT = 30
REVIEW_PANEL_WIDTH = 512
REVIEW_PANEL_HEIGHT = 384
REVIEW_ROW_HEIGHT = REVIEW_HEADER_HEIGHT + REVIEW_PANEL_HEIGHT
DEVELOPMENT_POPULATION_FLOORS = {
    "clean_acceptance": 19,
    "warning_acceptance": 13,
    "reject_detection": 38,
    "severity3_detection": 6,
    "grain_reject_detection": 10,
    "tiny_speck_reject_detection": 6,
    "microblob_reject_detection": 6,
    "spot_reject_detection": 10,
    "short_line_reject_detection": 10,
    "parallel_bundle_reject_detection": 8,
}
_R17_PUBLIC_NONCES = {
    "calibration": "r6-calibration-v12",
    "holdout": "r6-holdout-v12",
}
_R17_PRIVATE_IDENTITY_DOMAINS = {
    "private_reference_transform_prefix": "private-reference-transform-v12/",
    "foundation_offset_lane": "foundation-offset-v11",
    "foundation_assignment_lane": "foundation-assignment-v11",
    "delta_lane": "delta-v11",
    "private_control_id_prefix": "microtexture-v2-r6/private-control-id/v11/",
}
_R17_PARAMETER_NONCE_BASES = {
    "calibration_artifact": 973000,
    "holdout_artifact": 983000,
    "calibration_protocol_zero": 951000,
    "holdout_protocol_zero": 961000,
    "calibration_duplicate_audit": [991000, 991001, 991002],
    "holdout_duplicate_audit": [1001000, 1001001, 1001002],
}
_R17_SCHEDULE_REVISION = "dev-r17-protocol-zero-reference-prequalification-schedule-v1"
_R17_REFERENCE_PREQUALIFICATION_REVISION = (
    "dev-r17-role-agnostic-private-reference-coefficient-prequalification-v1"
)
_R17_REFERENCE_PREQUALIFICATION_MANIFEST = {
    "revision": _R17_REFERENCE_PREQUALIFICATION_REVISION,
    "applies_to_private_roles": [
        "artifact",
        "protocol-zero",
        "duplicate-audit",
    ],
    "candidate_count": 8,
    "coefficient_grid_hw": [7, 9],
    "candidate_domain": "candidate/{index:02d}/",
    "score_lane_integer_weights": {
        "displacement-y": 7,
        "displacement-x": 7,
        "tone": 3,
    },
    "score_terms_in_lexicographic_order": [
        "maximum-weighted-orthogonal-neighbor-jump",
        "sum-weighted-orthogonal-neighbor-jumps",
        "maximum-weighted-centered-coefficient-magnitude",
        "sum-weighted-centered-coefficient-magnitudes",
        "candidate-index",
    ],
    "selection_rule": "lexicographic-minimum",
    "selection_uses_pixels": False,
    "selection_uses_requested_delta": False,
    "selection_uses_labels_or_decisions": False,
    "selection_branches_on_private_role": False,
    "selected_score_not_worse_than_candidate_zero": True,
    "truth_guarantee_claimed": False,
}
_R17_REFERENCE_PREQUALIFICATION_MANIFEST_SHA256 = (
    "a3cfdec84b58bebec38f581c03fbe9947975bf93e11741477cd3bb22f0931119"
)
_R17_PRESERVED_R16_ARTIFACT_MORPHOLOGY_SHA256 = (
    "c60917c79ae36278d17cc7ccaa93d798cac17500d2d678b41b0cdea34ff66b30"
)
_R17_INITIAL_DECISION_GATE_REVISION = (
    "dev-r17-bilateral-initial-visible-flag-intersection-gate-v1"
)
_R17_INITIAL_DECISION_GATE_MANIFEST = {
    "revision": _R17_INITIAL_DECISION_GATE_REVISION,
    "snapshot_files": {
        "root": "decisions-root.initial.dev.txt",
        "independent": "decisions-independent.initial.dev.txt",
    },
    "receipt_files": {
        "root": "decisions-root.initial.dev.txt.sha256",
        "independent": "decisions-independent.initial.dev.txt.sha256",
    },
    "receipt_format": "lowercase-sha256 two-spaces snapshot-basename newline",
    "final_files": [
        "vision-decisions.dev.txt",
        "decisions-root.dev.txt",
        "decisions-independent.dev.txt",
    ],
    "final_three_way_exact_bytes_required": True,
    "initial_snapshots_require_official_parser_coverage_and_code_binding": True,
    "visible_flags": ["g", "t", "b", "l", "p"],
    "final_visible_flag_set_relation": (
        "subset-of-root-initial-intersection-independent-initial"
    ),
    "reconciled_fields_not_restricted_by_this_gate": [
        "disposition",
        "severity_0_to_3",
        "notes",
    ],
    "private_role_input": False,
    "read_only_attribute_required_by_runner": False,
}
_R17_INITIAL_DECISION_GATE_MANIFEST_SHA256 = (
    "f042250290f80d4304923e3b564746e8311515f5c649811678db934bb3ad6ffd"
)
_R16_WARNING_ANCHOR_REVISION = (
    "dev-r16-six-per-sparse-family-direct-visible-warning-v1"
)
_R16_WARNING_CONVERSION_REVISION = (
    "dev-r16-one-clean-one-clear-per-sparse-family-v1"
)
_R16_MICROBLOB_ANCHOR_REVISION = (
    "dev-r15-calibration-quantized-microblob-reject-v1"
)
_R16_WARNING_ANCHOR_SHA256 = (
    "bfc0e95e402c4f5751212c67759940c8c01802bb0a938899304ec4db576aa5df"
)
_R16_WARNING_CONVERSION_SHA256 = (
    "0f0f4e0865249d34ff8f83537f60dcaee1c2ee0fd64836551b6aa754251fb8e7"
)
_R16_PREDECESSOR_MORPHOLOGY_SHA256 = (
    "7adf59546337cded9910d17fbff5d383fc36e1058e69f98ed633890c2dd60f5b"
)
_R16_PRESERVED_NONCONVERSION_MORPHOLOGY_SHA256 = (
    "b8e7429a62e78c6e67efbfa6ec8b3b2fb0f16fb07f61ea9c7590f83f1b637ecd"
)
_R16_PRESERVED_NONWARNING_MORPHOLOGY_SHA256 = (
    "72212f11b453526bd6cec7e11420bcb9a0df7bbae2e097168393a5ee0c9a48b4"
)
_R16_ACTIVE_MICROBLOB_ANCHOR_SHA256 = (
    "2c207dfb5249d42056e164e7553091a9a617d8b673aecfb5ea25e4d757651f0c"
)
_GENERATION_STATE_KEYS = {
    "development_edition",
    "spec_sha256",
    "public_nonces",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "captured_git_head",
    "runtime",
}
_GENERATION_START_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "formal_use_forbidden",
    "one_shot_consumed",
    "started_at",
    "development_boundary_sha256",
    "state",
}
_GENERATION_SUMMARY_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "formal_use_forbidden",
    "state",
    "split_separation",
    "splits",
}
_GENERATION_SPLIT_SEPARATION_KEYS = {
    "codes_disjoint",
    "control_ids_disjoint",
    "cluster_ids_disjoint",
    "nonzero_delta_hashes_disjoint",
    "canonical_all_zero_delta_hash_shared",
}
_GENERATION_SPLIT_RECEIPT_KEYS = {
    "split",
    "record_count",
    "contact_sheet_count",
    "review_board_count",
    "manifest_path",
    "manifest_sha256",
    "blank_labels_path",
    "blank_labels_sha256",
    "review_index_path",
    "review_index_sha256",
}
_GENERATION_SEAL_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "formal_use_forbidden",
    "generation_start_sha256",
    "generation_summary_sha256",
    "spec_sha256",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "captured_git_head",
}
_GENERATION_COMPLETION_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "formal_use_forbidden",
    "completed_at",
    "generation_start_sha256",
    "generation_summary_sha256",
    "generation_seal_sha256",
    "spec_sha256",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "captured_git_head",
}
_GENERATION_FAILURE_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "formal_use_forbidden",
    "failed_at",
    "generation_start_sha256",
    "error_type",
    "message",
    "development_closed",
}
_REVIEW_INDEX_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "formal_use_forbidden",
    "split",
    "spec_sha256",
    "views",
    "layout",
    "pages",
}
_REVIEW_INDEX_PAGE_KEYS = {"page_index", "path", "sha256", "item_codes"}
_DEVELOPMENT_MANIFEST_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "formal_use_forbidden",
    "split",
    "spec_sha256",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "captured_git_head",
    "runtime",
    "record_count",
    "records",
    "contact_sheet_bundle",
    "warning",
}
_DEVELOPMENT_MANIFEST_RECORD_KEYS = {
    "anonymous_code",
    "control_commitment",
    "reference_commitment",
    "delta_commitment",
}
_DEVELOPMENT_CONTACT_SHEET_KEYS = {
    "view_id",
    "scale_percent",
    "source_crop_xywh",
    "page_index",
    "path",
    "sha256",
    "item_codes",
}
sys.path.insert(0, str(CODE_ROOT))

import common  # noqa: E402
from control_catalog import contact_sheet_pages, expected_controls  # noqa: E402
from metrics_v2_r6 import measure  # noqa: E402


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_json_exclusive(path: Path, value: Any) -> str:
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"development artifact already exists: {path}")
    payload = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    return _sha256(payload)


def _write_bytes_exclusive(path: Path, payload: bytes) -> str:
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"development artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(payload)
    return _sha256(payload)


def _read_json(path: Path) -> dict[str, Any]:
    return _read_json_payload(path.read_bytes(), str(path))


def _read_json_payload(payload: bytes, context: str) -> dict[str, Any]:
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"development JSON root must be an object: {context}")
    return value


def _sha256_file(path: Path) -> str:
    return _sha256(path.read_bytes())


def _is_link_like(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or bool(is_junction and is_junction(path))


def _assert_no_link_like_ancestors(path: Path, lexical_root: Path) -> None:
    candidate = Path(os.path.abspath(path))
    root = Path(os.path.abspath(lexical_root))
    if candidate != root and root not in candidate.parents:
        raise RuntimeError(f"development path escapes lexical root: {path}")
    while True:
        if _is_link_like(candidate):
            raise RuntimeError(
                f"development path contains a symlink or junction: {candidate}"
            )
        if candidate == root:
            break
        candidate = candidate.parent


def _assert_development_boundary(*, root_must_not_exist: bool) -> None:
    configured = [name for name in FORMAL_ENVIRONMENT if os.environ.get(name)]
    if configured:
        raise RuntimeError(f"formal r6 environment is set: {configured}")
    if FORMAL_ROOT.exists() or _is_link_like(FORMAL_ROOT):
        raise RuntimeError("exact formal r6 artifact root already exists")
    resolved_repo = REPO_ROOT.resolve()
    resolved_dev = DEV_ROOT.resolve()
    resolved_formal = FORMAL_ROOT.resolve()
    if (
        resolved_dev == resolved_repo
        or resolved_repo not in resolved_dev.parents
        or resolved_repo not in resolved_formal.parents
        or resolved_dev == resolved_formal
        or resolved_dev in resolved_formal.parents
        or resolved_formal in resolved_dev.parents
    ):
        raise RuntimeError("development/formal root boundary is unsafe")
    _assert_no_link_like_ancestors(DEV_ROOT, REPO_ROOT)
    if root_must_not_exist and (DEV_ROOT.exists() or _is_link_like(DEV_ROOT)):
        raise RuntimeError(f"development root already exists: {DEV_ROOT}")


def _assert_private_analysis_boundary(*, analysis_must_exist: bool) -> None:
    _assert_development_boundary(root_must_not_exist=False)
    resolved_dev = DEV_ROOT.resolve(strict=True)
    expected_parent = (DEV_ROOT / "private").resolve(strict=True)
    resolved_parent = PRIVATE_ANALYSIS_ROOT.parent.resolve(strict=True)
    if (
        expected_parent != resolved_parent
        or resolved_dev not in resolved_parent.parents
    ):
        raise RuntimeError("development private-analysis parent escapes DEV_ROOT")
    _assert_no_link_like_ancestors(PRIVATE_ANALYSIS_ROOT.parent, REPO_ROOT)
    if analysis_must_exist:
        if not PRIVATE_ANALYSIS_ROOT.is_dir():
            raise RuntimeError("development private-analysis root is not a directory")
        _assert_no_link_like_ancestors(PRIVATE_ANALYSIS_ROOT, REPO_ROOT)
        resolved_analysis = PRIVATE_ANALYSIS_ROOT.resolve(strict=True)
        if (
            resolved_dev not in resolved_analysis.parents
            or resolved_analysis.parent != resolved_parent
        ):
            raise RuntimeError("development private-analysis root escapes DEV_ROOT")


def _validate_dev_r17_spec_authority(value: dict[str, Any]) -> None:
    sparse_families = (
        "artifact-speck",
        "artifact-microblob",
        "artifact-short-dash",
        "artifact-parallel-bundle",
    )
    public_nonces = {
        split: value.get("splits", {}).get(split, {}).get("public_nonce")
        for split in ("calibration", "holdout")
    }
    cluster_prefix = value.get("independent_condition_clusters", {}).get(
        "message_prefix"
    )
    private_domains = value.get("control_catalog_authority", {}).get(
        "private_identity_domains"
    )
    blind = value.get("blind_derivation", {})
    rendering = value.get("rendering", {})
    schedule = value.get("population_anchor_schedule", {})
    expected_rotations = {
        "calibration": {
            "artifact-fine-grain": 2,
            "artifact-speck": 4,
            "artifact-microblob": 6,
            "artifact-short-dash": 8,
            "artifact-parallel-bundle": 10,
        },
        "holdout": {
            "artifact-fine-grain": 3,
            "artifact-speck": 5,
            "artifact-microblob": 7,
            "artifact-short-dash": 9,
            "artifact-parallel-bundle": 11,
        },
    }
    fine_grain_tiers = {
        "clean-candidate": 5,
        "warning-candidate": 4,
        "clear-reject-candidate": 7,
        "dominant-reject-candidate": 4,
    }
    sparse_tiers = {
        "clean-candidate": 4,
        "warning-candidate": 6,
        "clear-reject-candidate": 6,
        "dominant-reject-candidate": 4,
    }
    expected_tiers = {
        "artifact-fine-grain": fine_grain_tiers,
        **{family: sparse_tiers for family in sparse_families},
    }
    expected_conversion_sources = {
        family: {"clean-candidate": 1, "clear-reject-candidate": 1}
        for family in sparse_families
    }
    if (
        public_nonces != _R17_PUBLIC_NONCES
        or cluster_prefix != "microtexture-v2-r6/private-condition-cluster/v12/"
        or private_domains != _R17_PRIVATE_IDENTITY_DOMAINS
        or blind.get("key_commitment_message")
        != "microtexture-v2-r6/key-commitment/v11"
        or blind.get("seed_message_prefix") != "microtexture-v2-r6/render-seed/v12/"
        or blind.get("code_message_prefix") != "microtexture-v2-r6/opaque-code/v12/"
        or rendering.get("public_commitment_domain")
        != "microtexture-v2-r6/public-payload-commitment/v13/"
        "{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}"
        or schedule.get("revision") != _R17_SCHEDULE_REVISION
        or schedule.get("fresh_from_closed_dev_r16") is not True
        or schedule.get("r16_parameter_nonce_reuse_forbidden") is not True
        or schedule.get("r17_per_family_residue_rotation") != expected_rotations
        or schedule.get("tier_counts_per_artifact_family") != expected_tiers
        or schedule.get("inherited_warning_acceptance_anchor_revision")
        != "dev-r14-quantized-direct-visible-sparse-warning-v1"
        or schedule.get("inherited_warning_acceptance_anchor_conditions_per_split")
        != 16
        or schedule.get("inherited_warning_acceptance_anchor_schedule_sha256")
        != "5e997df4c7d4e0c6106b3060437235a7f665b08a6b02e00a86f4a4f024dc77e6"
        or schedule.get("warning_acceptance_anchor_revision")
        != _R16_WARNING_ANCHOR_REVISION
        or schedule.get("warning_acceptance_anchor_schedule_sha256")
        != _R16_WARNING_ANCHOR_SHA256
        or schedule.get("calibration_microblob_clear_reject_anchor_manifest", {}).get(
            "revision"
        )
        != _R16_MICROBLOB_ANCHOR_REVISION
        or schedule.get("r17_parameter_nonce_bases") != _R17_PARAMETER_NONCE_BASES
        or schedule.get("private_reference_prequalification_manifest")
        != _R17_REFERENCE_PREQUALIFICATION_MANIFEST
        or schedule.get("private_reference_prequalification_manifest_sha256")
        != _R17_REFERENCE_PREQUALIFICATION_MANIFEST_SHA256
        or _sha256(
            common.canonical_json_bytes(
                schedule.get("private_reference_prequalification_manifest")
            )
        )
        != _R17_REFERENCE_PREQUALIFICATION_MANIFEST_SHA256
        or schedule.get("initial_decision_gate_manifest")
        != _R17_INITIAL_DECISION_GATE_MANIFEST
        or schedule.get("initial_decision_gate_manifest_sha256")
        != _R17_INITIAL_DECISION_GATE_MANIFEST_SHA256
        or _sha256(
            common.canonical_json_bytes(schedule.get("initial_decision_gate_manifest"))
        )
        != _R17_INITIAL_DECISION_GATE_MANIFEST_SHA256
        or schedule.get("preserved_r16_artifact_morphology_conditions_across_splits")
        != 200
        or schedule.get("preserved_r16_artifact_morphology_sha256")
        != _R17_PRESERVED_R16_ARTIFACT_MORPHOLOGY_SHA256
        or schedule.get("r17_exact_morphology_change_count_across_splits") != 0
        or schedule.get("warning_conversion_revision")
        != _R16_WARNING_CONVERSION_REVISION
        or schedule.get("warning_conversion_conditions_per_split") != 8
        or schedule.get("warning_conversion_source_tiers_per_sparse_family")
        != expected_conversion_sources
        or schedule.get("warning_conversion_schedule_sha256")
        != _R16_WARNING_CONVERSION_SHA256
        or schedule.get("exact_morphology_change_count_across_splits") != 16
        or schedule.get("nonconversion_morphology_change_forbidden") is not True
        or schedule.get("predecessor_full_morphology_sha256")
        != _R16_PREDECESSOR_MORPHOLOGY_SHA256
        or schedule.get("preserved_nonconversion_morphology_conditions_across_splits")
        != 184
        or schedule.get("preserved_nonconversion_morphology_sha256")
        != _R16_PRESERVED_NONCONVERSION_MORPHOLOGY_SHA256
        or schedule.get("preserved_nonwarning_morphology_conditions_across_splits")
        != 144
        or schedule.get("preserved_nonwarning_morphology_sha256")
        != _R16_PRESERVED_NONWARNING_MORPHOLOGY_SHA256
        or schedule.get("warning_acceptance_anchor_conditions_per_split") != 24
        or schedule.get("warning_acceptance_anchor_conditions_per_family")
        != {family: 6 for family in sparse_families}
        or schedule.get(
            "warning_acceptance_anchor_structural_miss_budget_against_development_floor"
        )
        != 11
        or schedule.get("calibration_microblob_clear_reject_anchor_conditions") != 7
        or schedule.get("calibration_microblob_clear_reject_anchor_schedule_sha256")
        != "dd2ce7fd13f624bd065e8c7a6bacc2ab8bd593821dec8d46250a40e57ef64833"
        or schedule.get("calibration_microblob_clear_reject_active_indices")
        != [1, 2, 9, 13, 17, 18]
        or schedule.get("calibration_microblob_clear_reject_active_conditions") != 6
        or schedule.get("calibration_microblob_clear_reject_converted_to_warning_index")
        != 16
        or schedule.get("calibration_microblob_clear_reject_active_schedule_sha256")
        != _R16_ACTIVE_MICROBLOB_ANCHOR_SHA256
        or schedule.get("speck_reject_source_anchor_conditions_per_split") != 11
        or schedule.get("speck_reject_active_anchor_conditions_per_split") != 10
        or schedule.get(
            "speck_reject_anchor_structural_miss_budget_against_development_floor"
        )
        != 4
    ):
        raise RuntimeError("development dev-r17 spec/domain authority drift")


def _load_spec() -> tuple[dict[str, Any], str]:
    payload = (CODE_ROOT / "preregistered-spec.json").read_bytes()
    digest = _sha256(payload)
    if digest != common.SPEC_SHA256:
        raise RuntimeError("development preregistered spec SHA drift")
    value = json.loads(payload.decode("utf-8"))
    common.validate_preregistered_spec(value)
    _validate_dev_r17_spec_authority(value)
    return value, digest


def _public_nonces(spec: dict[str, Any]) -> dict[str, str]:
    nonces: dict[str, str] = {}
    for split in ("calibration", "holdout"):
        split_spec = spec.get("splits", {}).get(split)
        nonce = split_spec.get("public_nonce") if isinstance(split_spec, dict) else None
        if not isinstance(nonce, str) or not nonce:
            raise RuntimeError(f"{split} public nonce is missing from the spec")
        nonces[split] = nonce
    if len(set(nonces.values())) != len(nonces):
        raise RuntimeError("development split public nonces must be distinct")
    return nonces


def _validate_expected_control_population(controls: list[Any], split: str) -> None:
    if len(controls) != EXPECTED_RECORDS_PER_SPLIT:
        raise RuntimeError(f"{split} development control record-count drift")
    artifact_controls = [
        control for control in controls if control.private_role == "artifact"
    ]
    artifact_clusters = {control.condition_cluster_id for control in artifact_controls}
    cluster_counts = Counter(
        control.condition_cluster_id for control in artifact_controls
    )
    if (
        len(artifact_controls) != EXPECTED_ARTIFACT_RECORDS_PER_SPLIT
        or len(artifact_clusters) != EXPECTED_ARTIFACT_CLUSTERS_PER_SPLIT
        or any(count != 2 for count in cluster_counts.values())
    ):
        raise RuntimeError(f"{split} development artifact population drift")


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def _validate_development_key_git_boundary(
    spec: dict[str, Any], captured_head: str
) -> Path:
    handling = spec["development_probe_secret_handling"]
    key_relative = str(handling["ignored_private_key_required_repo_relative"])
    key_path = (REPO_ROOT / key_relative).resolve()
    required_path = (DEV_ROOT / "private" / "development-key.bin").resolve()
    if key_path != required_path:
        raise RuntimeError("development private-key path contract drift")

    gitignore_relative = str(handling["gitignore_required_repo_relative"])
    common._tracked_worktree_bytes(REPO_ROOT, captured_head, gitignore_relative)

    head_entry = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", captured_head, "--", key_relative],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if head_entry.returncode != 0:
        raise RuntimeError("development private-key HEAD inspection failed")
    if head_entry.stdout.strip():
        raise RuntimeError("development private-key path exists in captured HEAD")

    index_entry = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", key_relative],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if index_entry.returncode == 0:
        raise RuntimeError("development private-key path is tracked in the Git index")
    if index_entry.returncode != 1:
        raise RuntimeError("development private-key index inspection failed")

    ignored = subprocess.run(
        ["git", "check-ignore", "-v", "--no-index", "--", key_relative],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if ignored.returncode != 0:
        raise RuntimeError("development private-key path is not Git-ignored")
    metadata, separator, matched_path = ignored.stdout.rstrip("\r\n").rpartition("\t")
    source, first_colon, remainder = metadata.partition(":")
    line_number, second_colon, pattern = remainder.partition(":")
    if (
        separator != "\t"
        or matched_path != key_relative
        or first_colon != ":"
        or second_colon != ":"
        or source.replace("\\", "/") != gitignore_relative
        or not line_number.isdigit()
        or int(line_number) < 1
        or pattern != handling["gitignore_required_pattern"]
    ):
        raise RuntimeError(
            "development private-key ignore is not provided by the tracked root .gitignore"
        )
    common.assert_head_unchanged(captured_head)
    return key_path


def _tracked_input_preflight(spec: dict[str, Any], spec_sha: str) -> tuple[str, str]:
    captured_head = _git_head()
    branch = subprocess.check_output(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    upstream_ref = subprocess.check_output(
        [
            "git",
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            f"{branch}@{{upstream}}",
        ],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    upstream_head = subprocess.check_output(
        ["git", "rev-parse", upstream_ref], cwd=REPO_ROOT, text=True
    ).strip()
    if captured_head != upstream_head:
        raise RuntimeError("development HEAD is not equal to its upstream ref")
    repository = common.repository_root()
    code_relative = CODE_ROOT.relative_to(repository)
    if code_relative.as_posix() != spec["roots"]["code_root_required_repo_relative"]:
        raise RuntimeError("development CODE_ROOT contract drift")
    for relative in spec["authority_files"]:
        common._tracked_worktree_bytes(
            repository, captured_head, (code_relative / relative).as_posix()
        )
    bindings = common.validate_implementation_bindings()
    if bindings["spec_sha256"] != spec_sha:
        raise RuntimeError("development implementation/spec binding drift")
    common.verify_tracked_development_history(repository, captured_head, spec)
    common.verify_tracked_foundation_corpus_provenance(
        repository, captured_head, spec["foundation_corpus"]
    )
    _validate_development_key_git_boundary(spec, captured_head)
    common.assert_head_unchanged(captured_head)
    return captured_head, _sha256_file(CODE_ROOT / "implementation-bindings.json")


def _review_board_payload(
    controls: list[Any],
    views: list[dict[str, Any]],
    page_index: int,
) -> tuple[list[str], bytes]:
    panel_width, panel_height = 512, REVIEW_PANEL_HEIGHT
    header_height = REVIEW_HEADER_HEIGHT
    rows = REVIEW_ROWS_PER_PAGE
    selected = controls[(page_index - 1) * rows : page_index * rows]
    canvas = Image.new(
        "L", (panel_width * len(views), (panel_height + header_height) * rows), 32
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=16)
    for row, control in enumerate(selected):
        for column, view in enumerate(views):
            left, top, width, height = [int(item) for item in view["source_crop_xywh"]]
            crop = Image.fromarray(control.control).crop(
                (left, top, left + width, top + height)
            )
            display = crop.resize(
                (panel_width, panel_height), resample=Image.Resampling.NEAREST
            )
            x = column * panel_width
            y = row * (panel_height + header_height)
            draw.text(
                (x + 6, y + 14),
                f"ROW {row + 1}  {control.anonymous_code}  {view['id']}",
                fill=255,
                font=font,
            )
            canvas.paste(display, (x, y + header_height))
    stream = io.BytesIO()
    canvas.save(stream, format="PNG", compress_level=6, optimize=False)
    return [item.anonymous_code for item in selected], stream.getvalue()


def _review_board(
    controls: list[Any],
    views: list[dict[str, Any]],
    page_index: int,
    output: Path,
) -> tuple[list[str], str]:
    codes, payload = _review_board_payload(controls, views, page_index)
    return codes, _write_bytes_exclusive(output, payload)


def _generate_split(
    spec: dict[str, Any],
    split: str,
    key: bytes,
    state: dict[str, Any],
) -> dict[str, Any]:
    controls = sorted(
        expected_controls(spec, split, key), key=lambda item: item.anonymous_code
    )
    _validate_expected_control_population(controls, split)
    pages = contact_sheet_pages(spec, split, controls)
    page_counts = Counter(page.view_id for page in pages)
    expected_views = {str(view["id"]) for view in spec["contact_sheets"]["views"]}
    if (
        len(pages) != EXPECTED_CONTACT_SHEETS_PER_SPLIT
        or set(page_counts) != expected_views
        or any(
            count != EXPECTED_REVIEW_PAGES_PER_SPLIT for count in page_counts.values()
        )
    ):
        raise RuntimeError(f"{split} development contact-sheet count drift")
    public_root = DEV_ROOT / "public" / split
    sheet_root = public_root / "contact-sheets"
    sheet_root.mkdir(parents=True, exist_ok=False)
    sheet_bundle: list[dict[str, Any]] = []
    for page in pages:
        name = Path(page.path).name
        target = sheet_root / name
        _write_bytes_exclusive(target, page.png_bytes)
        entry = page.manifest_entry()
        entry["path"] = target.relative_to(DEV_ROOT).as_posix()
        sheet_bundle.append(entry)

    records = [
        {
            "anonymous_code": control.anonymous_code,
            "control_commitment": control.control_commitment,
            "reference_commitment": control.reference_commitment,
            "delta_commitment": control.delta_commitment,
        }
        for control in controls
    ]
    manifest = {
        "artifact": "microtexture-v2-r6-development-control-manifest",
        "schema_version": "microtexture-v2-r6-development-control-manifest/1",
        "authority": False,
        "formal_use_forbidden": True,
        "split": split,
        "spec_sha256": state["spec_sha256"],
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "blind_key_commitment": state["blind_key_commitment"],
        "captured_git_head": state["captured_git_head"],
        "runtime": state["runtime"],
        "record_count": len(records),
        "records": records,
        "contact_sheet_bundle": sheet_bundle,
        "warning": "DEVELOPMENT ONLY; not a formal r6 manifest or authority artifact.",
    }
    manifest_path = public_root / "manifest.dev.json"
    manifest_sha = _write_json_exclusive(manifest_path, manifest)
    labels = {
        "artifact": "microtexture-v2-r6-root-vision-labels",
        "schema_version": "microtexture-v2-r6-root-vision-labels/2",
        "split": split,
        "spec_sha256": state["spec_sha256"],
        "manifest_sha256": manifest_sha,
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "blind_key_commitment": state["blind_key_commitment"],
        "runtime": state["runtime"],
        "contact_sheet_bundle": sheet_bundle,
        "reviewer": "Root",
        "items": [
            {
                "anonymous_code": control.anonymous_code,
                "disposition": None,
                "grain_visible": None,
                "tiny_speck_visible": None,
                "microblob_visible": None,
                "short_line_visible": None,
                "parallel_bundle_visible": None,
                "severity_0_to_3": None,
                "reviewed_at_200_percent": None,
                "reviewed_at_all_400_percent_quadrants": None,
                "notes": "",
            }
            for control in controls
        ],
    }
    labels_sha = _write_json_exclusive(public_root / "labels.blank.dev.json", labels)

    board_root = public_root / "review-boards"
    review_pages = []
    for page_index in range(1, EXPECTED_REVIEW_PAGES_PER_SPLIT + 1):
        target = board_root / f"review-page-{page_index:03d}.png"
        codes, digest = _review_board(
            controls, spec["contact_sheets"]["views"], page_index, target
        )
        review_pages.append(
            {
                "page_index": page_index,
                "path": target.relative_to(DEV_ROOT).as_posix(),
                "sha256": digest,
                "item_codes": codes,
            }
        )
    review_index = {
        "artifact": "microtexture-v2-r6-development-review-index",
        "schema_version": "microtexture-v2-r6-development-review-index/1",
        "authority": False,
        "formal_use_forbidden": True,
        "split": split,
        "spec_sha256": state["spec_sha256"],
        "views": [view["id"] for view in spec["contact_sheets"]["views"]],
        "layout": "one anonymous code per row with a black header above its panels; full-200 plus all four 400-percent quadrants",
        "pages": review_pages,
    }
    review_index_sha = _write_json_exclusive(
        public_root / "review-index.dev.json", review_index
    )
    return {
        "split": split,
        "record_count": len(controls),
        "contact_sheet_count": len(pages),
        "review_board_count": len(review_pages),
        "manifest_path": manifest_path.relative_to(DEV_ROOT).as_posix(),
        "manifest_sha256": manifest_sha,
        "blank_labels_path": (public_root / "labels.blank.dev.json")
        .relative_to(DEV_ROOT)
        .as_posix(),
        "blank_labels_sha256": labels_sha,
        "review_index_path": (public_root / "review-index.dev.json")
        .relative_to(DEV_ROOT)
        .as_posix(),
        "review_index_sha256": review_index_sha,
        "codes": [control.anonymous_code for control in controls],
        "control_ids": [control.control_id for control in controls],
        "cluster_ids": [control.condition_cluster_id for control in controls],
        "nonzero_delta_hashes": [
            control.delta_float32_sha256
            for control in controls
            if control.requested_delta.any()
        ],
        "zero_delta_hashes": [
            control.delta_float32_sha256
            for control in controls
            if not control.requested_delta.any()
        ],
    }


_FLAG_FIELDS = {
    "g": "grain_visible",
    "t": "tiny_speck_visible",
    "b": "microblob_visible",
    "l": "short_line_visible",
    "p": "parallel_bundle_visible",
}


def _checked_dev_file(relative: str, context: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise RuntimeError(f"{context} development path is invalid")
    path = DEV_ROOT / Path(relative)
    resolved_root = DEV_ROOT.resolve()
    resolved = path.resolve()
    if resolved_root not in resolved.parents or not path.is_file() or path.is_symlink():
        raise RuntimeError(f"{context} development path escaped or is not a file")
    return path


def _require_sha256(value: Any, context: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise RuntimeError(f"{context} must be a lowercase SHA-256 digest")


def _sanitized_error_message(error: BaseException) -> str:
    message = str(error).strip() or "exception without a message"
    message = re.sub(
        r"(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])",
        "[redacted-key-like-value]",
        message,
    )
    return re.sub(
        r"(?i)(?<![0-9a-f])[0-9a-f]{24}(?![0-9a-f])",
        "[redacted-opaque-code]",
        message,
    )[:512]


def _expected_generation_split_paths(split: str) -> dict[str, str]:
    prefix = f"public/{split}"
    return {
        "manifest_path": f"{prefix}/manifest.dev.json",
        "blank_labels_path": f"{prefix}/labels.blank.dev.json",
        "review_index_path": f"{prefix}/review-index.dev.json",
    }


def _validate_generation_summary(
    summary: dict[str, Any], state: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    common.require_exact_keys(
        summary, _GENERATION_SUMMARY_KEYS, "development generation summary"
    )
    if (
        summary.get("artifact")
        != "microtexture-v2-r6-development-generation-summary"
        or summary.get("schema_version")
        != "microtexture-v2-r6-development-generation-summary/1"
        or summary.get("authority") is not False
        or summary.get("formal_use_forbidden") is not True
        or summary.get("state") != state
    ):
        raise RuntimeError("development generation summary metadata drift")

    separation = summary.get("split_separation")
    common.require_exact_keys(
        separation,
        _GENERATION_SPLIT_SEPARATION_KEYS,
        "development generation split separation",
    )
    if any(separation[field] is not True for field in _GENERATION_SPLIT_SEPARATION_KEYS):
        raise RuntimeError("development generation split separation drift")

    raw_receipts = summary.get("splits")
    if not isinstance(raw_receipts, list) or len(raw_receipts) != 2:
        raise RuntimeError("development generation split receipt count drift")
    if [receipt.get("split") for receipt in raw_receipts if isinstance(receipt, dict)] != [
        "calibration",
        "holdout",
    ]:
        raise RuntimeError("development generation split receipt order drift")
    receipts: dict[str, dict[str, Any]] = {}
    for index, receipt in enumerate(raw_receipts):
        context = f"development generation split receipt[{index}]"
        common.require_exact_keys(receipt, _GENERATION_SPLIT_RECEIPT_KEYS, context)
        split = receipt.get("split")
        if split not in {"calibration", "holdout"} or split in receipts:
            raise RuntimeError(f"{context} split drift")
        expected_paths = _expected_generation_split_paths(split)
        if (
            type(receipt.get("record_count")) is not int
            or receipt.get("record_count") != EXPECTED_RECORDS_PER_SPLIT
            or type(receipt.get("contact_sheet_count")) is not int
            or receipt.get("contact_sheet_count")
            != EXPECTED_CONTACT_SHEETS_PER_SPLIT
            or type(receipt.get("review_board_count")) is not int
            or receipt.get("review_board_count")
            != EXPECTED_REVIEW_PAGES_PER_SPLIT
            or any(receipt.get(field) != value for field, value in expected_paths.items())
        ):
            raise RuntimeError(f"{context} count/path drift")
        for field in (
            "manifest_sha256",
            "blank_labels_sha256",
            "review_index_sha256",
        ):
            _require_sha256(receipt.get(field), f"{context}.{field}")
        receipts[split] = receipt
    if set(receipts) != {"calibration", "holdout"}:
        raise RuntimeError("development generation split receipt coverage drift")
    return receipts


def _verify_public_generation_receipt(
    split: str, receipt: dict[str, Any]
) -> dict[str, bytes]:
    expected_paths = _expected_generation_split_paths(split)
    captured: dict[str, bytes] = {}
    for path_field, expected_relative in expected_paths.items():
        if receipt.get(path_field) != expected_relative:
            raise RuntimeError(f"{split} generation receipt path drift: {path_field}")
        sha_field = path_field.replace("_path", "_sha256")
        path = _checked_dev_file(expected_relative, f"{split} generation receipt")
        payload = path.read_bytes()
        if _sha256(payload) != receipt.get(sha_field):
            raise RuntimeError(f"{split} generation receipt SHA drift: {path_field}")
        captured[path_field] = payload
    return captured


def _load_generation_state(
    spec: dict[str, Any], spec_sha: str
) -> tuple[
    dict[str, Any], dict[str, dict[str, Any]], dict[str, str]
]:
    boundary_path = DEV_ROOT / "DEV-ONLY.json"
    start_path = DEV_ROOT / "generation-start.dev.json"
    summary_path = DEV_ROOT / "generation-summary.dev.json"
    seal_path = DEV_ROOT / "generation-seal.dev.json"
    completion_path = DEV_ROOT / "generation-completion.dev.json"
    failure_path = DEV_ROOT / "generation-failure.dev.json"
    if failure_path.exists() or failure_path.is_symlink():
        raise RuntimeError("development generation is failed and closed")
    required_paths = (
        boundary_path,
        start_path,
        summary_path,
        seal_path,
        completion_path,
    )
    if any(not path.is_file() or path.is_symlink() for path in required_paths):
        raise RuntimeError("development generation terminal artifacts are incomplete")
    boundary_payload = boundary_path.read_bytes()
    start_payload = start_path.read_bytes()
    summary_payload = summary_path.read_bytes()
    seal_payload = seal_path.read_bytes()
    completion_payload = completion_path.read_bytes()
    boundary = _read_json_payload(boundary_payload, str(boundary_path))
    start = _read_json_payload(start_payload, str(start_path))
    summary = _read_json_payload(summary_payload, str(summary_path))
    seal = _read_json_payload(seal_payload, str(seal_path))
    completion = _read_json_payload(completion_payload, str(completion_path))
    generation_start_sha = _sha256(start_payload)
    generation_summary_sha = _sha256(summary_payload)
    generation_seal_sha = _sha256(seal_payload)
    generation_completion_sha = _sha256(completion_payload)
    state = summary.get("state")
    if not isinstance(state, dict):
        raise RuntimeError("development generation state is missing")
    common.require_exact_keys(state, _GENERATION_STATE_KEYS, "development generation state")
    common.require_exact_keys(start, _GENERATION_START_KEYS, "development generation start")
    common.require_exact_keys(
        boundary,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "formal_cli_invoked",
            "formal_marker_created",
            "formal_threshold_created",
            "locked_clean_v18_decoded_or_measured",
            "exact_formal_root_absent_before_generation",
            "formal_environment_absent_before_generation",
            *_GENERATION_STATE_KEYS,
        },
        "development generation boundary",
    )
    common.require_exact_keys(seal, _GENERATION_SEAL_KEYS, "development generation seal")
    common.require_exact_keys(
        completion,
        _GENERATION_COMPLETION_KEYS,
        "development generation completion",
    )
    expected_bindings_sha = _sha256_file(CODE_ROOT / "implementation-bindings.json")
    if (
        boundary.get("artifact")
        != "microtexture-v2-r6-development-only-boundary"
        or boundary.get("schema_version")
        != "microtexture-v2-r6-development-only-boundary/1"
        or boundary.get("authority") is not False
        or boundary.get("formal_use_forbidden") is not True
        or boundary.get("formal_cli_invoked") is not False
        or boundary.get("formal_marker_created") is not False
        or boundary.get("formal_threshold_created") is not False
        or boundary.get("locked_clean_v18_decoded_or_measured") is not False
        or boundary.get("exact_formal_root_absent_before_generation") is not True
        or boundary.get("formal_environment_absent_before_generation") is not True
        or state.get("development_edition") != DEVELOPMENT_EDITION
        or state.get("spec_sha256") != spec_sha
        or state.get("public_nonces") != _public_nonces(spec)
        or state.get("implementation_bindings_sha256") != expected_bindings_sha
        or not isinstance(state.get("runtime"), dict)
        or {field: boundary[field] for field in _GENERATION_STATE_KEYS} != state
    ):
        raise RuntimeError("development generation boundary/state drift")
    if (
        start.get("artifact")
        != "microtexture-v2-r6-development-generation-start"
        or start.get("schema_version")
        != "microtexture-v2-r6-development-generation-start/1"
        or start.get("authority") is not False
        or start.get("formal_use_forbidden") is not True
        or start.get("one_shot_consumed") is not True
        or start.get("development_boundary_sha256") != _sha256(boundary_payload)
        or start.get("state") != state
    ):
        raise RuntimeError("development generation start drift")
    started_at = common.parse_utc_timestamp(
        start.get("started_at"), "development generation start.started_at"
    )
    for field in (
        "spec_sha256",
        "implementation_bindings_sha256",
        "blind_key_commitment",
    ):
        _require_sha256(state.get(field), f"development generation state.{field}")
    if (
        seal.get("artifact") != "microtexture-v2-r6-development-generation-seal"
        or seal.get("schema_version")
        != "microtexture-v2-r6-development-generation-seal/1"
        or seal.get("authority") is not False
        or seal.get("formal_use_forbidden") is not True
        or seal.get("generation_start_sha256") != generation_start_sha
        or seal.get("generation_summary_sha256") != generation_summary_sha
        or seal.get("spec_sha256") != state["spec_sha256"]
        or seal.get("implementation_bindings_sha256")
        != state["implementation_bindings_sha256"]
        or seal.get("blind_key_commitment") != state["blind_key_commitment"]
        or seal.get("captured_git_head") != state["captured_git_head"]
    ):
        raise RuntimeError("development generation seal drift")
    for field in ("generation_start_sha256", "generation_summary_sha256"):
        _require_sha256(
            seal.get(field),
            f"development generation seal.{field}",
        )
    if (
        completion.get("artifact")
        != "microtexture-v2-r6-development-generation-completion"
        or completion.get("schema_version")
        != "microtexture-v2-r6-development-generation-completion/1"
        or completion.get("authority") is not False
        or completion.get("formal_use_forbidden") is not True
        or completion.get("generation_start_sha256") != generation_start_sha
        or completion.get("generation_summary_sha256") != generation_summary_sha
        or completion.get("generation_seal_sha256") != generation_seal_sha
        or completion.get("spec_sha256") != state["spec_sha256"]
        or completion.get("implementation_bindings_sha256")
        != state["implementation_bindings_sha256"]
        or completion.get("blind_key_commitment") != state["blind_key_commitment"]
        or completion.get("captured_git_head") != state["captured_git_head"]
    ):
        raise RuntimeError("development generation completion drift")
    completed_at = common.parse_utc_timestamp(
        completion.get("completed_at"),
        "development generation completion.completed_at",
    )
    if completed_at < started_at:
        raise RuntimeError("development generation timestamp order drift")
    for field in (
        "generation_start_sha256",
        "generation_summary_sha256",
        "generation_seal_sha256",
    ):
        _require_sha256(
            completion.get(field),
            f"development generation completion.{field}",
        )
    receipts = _validate_generation_summary(summary, state)
    return state, receipts, {
        "generation_start_sha256": generation_start_sha,
        "generation_summary_sha256": generation_summary_sha,
        "generation_seal_sha256": generation_seal_sha,
        "generation_completion_sha256": generation_completion_sha,
    }


def _parse_decisions_payload(
    payload: bytes, context: str
) -> dict[tuple[int, int], dict[str, Any]]:
    decisions: dict[tuple[int, int], dict[str, Any]] = {}
    for line_number, raw_line in enumerate(
        payload.decode("utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=6)
        if len(parts) != 7:
            raise RuntimeError(f"decision DSL field drift: {context}:{line_number}")
        (
            page_text,
            row_text,
            anonymous_code,
            disposition,
            severity_text,
            flags_text,
            notes,
        ) = parts
        if (
            not page_text.isdigit()
            or not row_text.isdigit()
            or not severity_text.isdigit()
        ):
            raise RuntimeError(f"decision DSL numeric drift: {context}:{line_number}")
        page, row, severity = int(page_text), int(row_text), int(severity_text)
        key = (page, row)
        if key in decisions:
            raise RuntimeError(f"duplicate decision: {context}:{page_text}/{row_text}")
        if len(anonymous_code) != 24 or any(
            character not in "0123456789abcdef" for character in anonymous_code
        ):
            raise RuntimeError(
                f"decision DSL anonymous-code drift: {context}:{line_number}"
            )
        if flags_text == "-":
            flags: set[str] = set()
        else:
            flag_tokens = flags_text.split(",")
            flags = set(flag_tokens)
            canonical_flag_tokens = [flag for flag in _FLAG_FIELDS if flag in flags]
            if (
                "" in flags
                or not flags.issubset(_FLAG_FIELDS)
                or flag_tokens != canonical_flag_tokens
            ):
                raise RuntimeError(f"decision DSL flag drift: {context}:{line_number}")
        consistent = (
            (disposition == "clean" and severity == 0 and not flags)
            or (disposition == "warning" and severity == 1 and bool(flags))
            or (disposition == "reject" and severity in {2, 3} and bool(flags))
        )
        if not consistent or not notes:
            raise RuntimeError(f"decision DSL semantic drift: {context}:{line_number}")
        decision = {
            "anonymous_code": anonymous_code,
            "disposition": disposition,
            "severity_0_to_3": severity,
            **{field: flag in flags for flag, field in _FLAG_FIELDS.items()},
            "reviewed_at_200_percent": True,
            "reviewed_at_all_400_percent_quadrants": True,
            "notes": notes,
        }
        common._validate_vision_evidence_notes(decision, context, anonymous_code)
        decisions[key] = decision
    return decisions


def _validate_r17_initial_decision_gate_manifest() -> None:
    manifest = _R17_INITIAL_DECISION_GATE_MANIFEST
    if (
        manifest.get("revision") != _R17_INITIAL_DECISION_GATE_REVISION
        or manifest.get("snapshot_files")
        != {
            "root": "decisions-root.initial.dev.txt",
            "independent": "decisions-independent.initial.dev.txt",
        }
        or manifest.get("receipt_files")
        != {
            "root": "decisions-root.initial.dev.txt.sha256",
            "independent": "decisions-independent.initial.dev.txt.sha256",
        }
        or manifest.get("receipt_format")
        != "lowercase-sha256 two-spaces snapshot-basename newline"
        or manifest.get("final_files")
        != [
            "vision-decisions.dev.txt",
            "decisions-root.dev.txt",
            "decisions-independent.dev.txt",
        ]
        or manifest.get("final_three_way_exact_bytes_required") is not True
        or manifest.get(
            "initial_snapshots_require_official_parser_coverage_and_code_binding"
        )
        is not True
        or manifest.get("visible_flags") != ["g", "t", "b", "l", "p"]
        or manifest.get("final_visible_flag_set_relation")
        != "subset-of-root-initial-intersection-independent-initial"
        or manifest.get("reconciled_fields_not_restricted_by_this_gate")
        != ["disposition", "severity_0_to_3", "notes"]
        or manifest.get("private_role_input") is not False
        or manifest.get("read_only_attribute_required_by_runner") is not False
        or _sha256(common.canonical_json_bytes(manifest))
        != _R17_INITIAL_DECISION_GATE_MANIFEST_SHA256
    ):
        raise RuntimeError("development r17 initial-decision gate manifest drift")


def _read_verified_initial_decision_snapshot(
    split: str,
    reviewer: str,
) -> tuple[bytes, dict[tuple[int, int], dict[str, Any]], str, str]:
    snapshot_name = _R17_INITIAL_DECISION_GATE_MANIFEST["snapshot_files"].get(reviewer)
    receipt_name = _R17_INITIAL_DECISION_GATE_MANIFEST["receipt_files"].get(reviewer)
    if not isinstance(snapshot_name, str) or not isinstance(receipt_name, str):
        raise RuntimeError(f"{split} invalid initial-decision reviewer: {reviewer}")
    snapshot_relative = f"public/{split}/{snapshot_name}"
    receipt_relative = f"public/{split}/{receipt_name}"
    snapshot_path = _checked_dev_file(
        snapshot_relative,
        f"{split} {reviewer} initial Vision decisions",
    )
    receipt_path = _checked_dev_file(
        receipt_relative,
        f"{split} {reviewer} initial Vision decision receipt",
    )
    snapshot_payload = snapshot_path.read_bytes()
    snapshot_sha = _sha256(snapshot_payload)
    receipt_payload = receipt_path.read_bytes()
    expected_receipt = f"{snapshot_sha}  {snapshot_name}\n".encode("ascii")
    if receipt_payload != expected_receipt:
        raise RuntimeError(f"{split} {reviewer} initial Vision decision receipt drift")
    decisions = _parse_decisions_payload(
        snapshot_payload,
        str(snapshot_path),
    )
    return snapshot_payload, decisions, snapshot_sha, _sha256(receipt_payload)


def _verify_bundle_files(entries: Any, context: str) -> dict[str, bytes]:
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"{context} bundle is empty")
    seen_paths: set[str] = set()
    captured: dict[str, bytes] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RuntimeError(f"{context} bundle entry drift: {index}")
        relative, expected_sha = entry.get("path"), entry.get("sha256")
        if not isinstance(relative, str) or relative in seen_paths:
            raise RuntimeError(f"{context} duplicate/invalid path: {index}")
        seen_paths.add(relative)
        path = _checked_dev_file(relative, f"{context}[{index}]")
        payload = path.read_bytes()
        if _sha256(payload) != expected_sha:
            raise RuntimeError(f"{context} SHA drift: {relative}")
        captured[relative] = payload
    return captured


def _verify_contact_sheet_layout(
    entries: list[dict[str, Any]],
    spec: dict[str, Any],
    split: str,
    expected_codes: list[str],
) -> None:
    configured_views = spec["contact_sheets"]["views"]
    expected_views = [str(view["id"]) for view in configured_views]
    if len(expected_views) != 5 or len(set(expected_views)) != 5:
        raise RuntimeError(f"{split} development contact-sheet view drift")
    by_view_page: dict[tuple[str, int], list[str]] = {}
    for entry_index, entry in enumerate(entries):
        common.require_exact_keys(
            entry,
            _DEVELOPMENT_CONTACT_SHEET_KEYS,
            f"{split} development contact sheet[{entry_index}]",
        )
        expected_view_position = entry_index // EXPECTED_REVIEW_PAGES_PER_SPLIT
        expected_page_index = entry_index % EXPECTED_REVIEW_PAGES_PER_SPLIT + 1
        expected_view = configured_views[expected_view_position]
        expected_view_id = str(expected_view["id"])
        view_id = entry.get("view_id")
        page_index = entry.get("page_index")
        item_codes = entry.get("item_codes")
        key = (view_id, page_index)
        expected_path = (
            f"public/{split}/contact-sheets/"
            f"{expected_view_id}-page-{expected_page_index:03d}.png"
        )
        if (
            view_id != expected_view_id
            or type(page_index) is not int
            or page_index != expected_page_index
            or entry.get("scale_percent") != int(expected_view["scale_percent"])
            or entry.get("source_crop_xywh")
            != [int(value) for value in expected_view["source_crop_xywh"]]
            or entry.get("path") != expected_path
            or key in by_view_page
            or not isinstance(item_codes, list)
        ):
            raise RuntimeError(f"{split} development contact-sheet layout drift")
        _require_sha256(
            entry.get("sha256"),
            f"{split} development contact sheet[{entry_index}].sha256",
        )
        remaining = EXPECTED_RECORDS_PER_SPLIT - (
            (page_index - 1) * REVIEW_ROWS_PER_PAGE
        )
        expected_count = min(REVIEW_ROWS_PER_PAGE, remaining)
        expected_item_codes = expected_codes[
            (page_index - 1) * REVIEW_ROWS_PER_PAGE : page_index
            * REVIEW_ROWS_PER_PAGE
        ]
        if len(item_codes) != expected_count or item_codes != expected_item_codes:
            raise RuntimeError(
                f"{split}/{view_id} contact-sheet code-order drift: {page_index}"
            )
        by_view_page[key] = item_codes
    expected_keys = {
        (view_id, page_index)
        for view_id in expected_views
        for page_index in range(1, EXPECTED_REVIEW_PAGES_PER_SPLIT + 1)
    }
    if set(by_view_page) != expected_keys:
        raise RuntimeError(f"{split} development contact-sheet coverage drift")
    for page_index in range(1, EXPECTED_REVIEW_PAGES_PER_SPLIT + 1):
        code_orders = {
            tuple(by_view_page[(view_id, page_index)]) for view_id in expected_views
        }
        if len(code_orders) != 1:
            raise RuntimeError(
                f"{split} development contact-sheet cross-view order drift: "
                f"{page_index}"
            )


def _validate_blank_labels(
    value: dict[str, Any],
    split: str,
    manifest: dict[str, Any],
    manifest_sha: str,
    state: dict[str, Any],
    expected_codes: list[str],
) -> None:
    context = f"{split} development blank labels"
    common.require_exact_keys(value, common.VISION_LABEL_KEYS, context)
    common._forbid_public_identity(value, context)
    if (
        value.get("artifact") != "microtexture-v2-r6-root-vision-labels"
        or value.get("schema_version")
        != "microtexture-v2-r6-root-vision-labels/2"
        or value.get("split") != split
        or value.get("spec_sha256") != state["spec_sha256"]
        or value.get("manifest_sha256") != manifest_sha
        or value.get("implementation_bindings_sha256")
        != state["implementation_bindings_sha256"]
        or value.get("blind_key_commitment") != state["blind_key_commitment"]
        or value.get("runtime") != state["runtime"]
        or value.get("runtime") != manifest["runtime"]
        or value.get("contact_sheet_bundle") != manifest["contact_sheet_bundle"]
        or value.get("reviewer") != "Root"
    ):
        raise RuntimeError(f"{context} metadata/binding drift")
    items = value.get("items")
    if not isinstance(items, list) or len(items) != EXPECTED_RECORDS_PER_SPLIT:
        raise RuntimeError(f"{context} item-count drift")
    null_fields = (
        "disposition",
        "grain_visible",
        "tiny_speck_visible",
        "microblob_visible",
        "short_line_visible",
        "parallel_bundle_visible",
        "severity_0_to_3",
        "reviewed_at_200_percent",
        "reviewed_at_all_400_percent_quadrants",
    )
    for index, (item, expected_code) in enumerate(zip(items, expected_codes)):
        common.require_exact_keys(
            item,
            common.VISION_LABEL_ITEM_KEYS,
            f"{context}[{index}]",
        )
        if (
            item.get("anonymous_code") != expected_code
            or any(item.get(field) is not None for field in null_fields)
            or item.get("notes") != ""
        ):
            raise RuntimeError(f"{context} code/order/null-state drift: {index}")


def _prepare_public_split(
    spec: dict[str, Any],
    state: dict[str, Any],
    split: str,
    generation_receipt: dict[str, Any],
    *,
    require_completed_decisions: bool = True,
) -> dict[str, Any]:
    public_root = DEV_ROOT / "public" / split
    manifest_path = public_root / "manifest.dev.json"
    blank_labels_path = public_root / "labels.blank.dev.json"
    review_index_path = public_root / "review-index.dev.json"
    decisions_path = public_root / "vision-decisions.dev.txt"
    root_decisions_path = public_root / "decisions-root.dev.txt"
    independent_decisions_path = public_root / "decisions-independent.dev.txt"
    generation_payloads = _verify_public_generation_receipt(split, generation_receipt)
    manifest_payload = generation_payloads["manifest_path"]
    blank_labels_payload = generation_payloads["blank_labels_path"]
    review_index_payload = generation_payloads["review_index_path"]
    manifest = _read_json_payload(manifest_payload, str(manifest_path))
    blank_labels = _read_json_payload(blank_labels_payload, str(blank_labels_path))
    review_index = _read_json_payload(review_index_payload, str(review_index_path))
    manifest_sha = _sha256(manifest_payload)
    common.require_exact_keys(
        manifest, _DEVELOPMENT_MANIFEST_KEYS, f"{split} development manifest"
    )
    records = manifest.get("records")
    if (
        manifest.get("artifact") != "microtexture-v2-r6-development-control-manifest"
        or manifest.get("schema_version")
        != "microtexture-v2-r6-development-control-manifest/1"
        or manifest.get("authority") is not False
        or manifest.get("formal_use_forbidden") is not True
        or manifest.get("split") != split
        or manifest.get("spec_sha256") != state["spec_sha256"]
        or manifest.get("implementation_bindings_sha256")
        != state["implementation_bindings_sha256"]
        or manifest.get("blind_key_commitment") != state["blind_key_commitment"]
        or manifest.get("captured_git_head") != state["captured_git_head"]
        or manifest.get("runtime") != state["runtime"]
        or manifest.get("warning")
        != "DEVELOPMENT ONLY; not a formal r6 manifest or authority artifact."
        or not isinstance(records, list)
        or len(records) != EXPECTED_RECORDS_PER_SPLIT
        or type(manifest.get("record_count")) is not int
        or manifest.get("record_count") != EXPECTED_RECORDS_PER_SPLIT
        or not isinstance(manifest.get("contact_sheet_bundle"), list)
        or len(manifest["contact_sheet_bundle"]) != EXPECTED_CONTACT_SHEETS_PER_SPLIT
    ):
        raise RuntimeError(f"{split} development manifest drift")
    codes: list[str] = []
    for index, record in enumerate(records):
        common.require_exact_keys(
            record,
            _DEVELOPMENT_MANIFEST_RECORD_KEYS,
            f"{split} development manifest record[{index}]",
        )
        code = record.get("anonymous_code")
        if (
            not isinstance(code, str)
            or len(code) != 24
            or any(character not in "0123456789abcdef" for character in code)
        ):
            raise RuntimeError(f"{split} development manifest code format drift")
        for field in (
            "control_commitment",
            "reference_commitment",
            "delta_commitment",
        ):
            _require_sha256(
                record.get(field),
                f"{split} development manifest record[{index}].{field}",
            )
        codes.append(code)
    if (
        len(codes) != EXPECTED_RECORDS_PER_SPLIT
        or len(set(codes)) != EXPECTED_RECORDS_PER_SPLIT
        or codes != sorted(codes)
    ):
        raise RuntimeError(f"{split} development manifest code drift")
    _validate_blank_labels(
        blank_labels,
        split,
        manifest,
        manifest_sha,
        state,
        codes,
    )
    contact_sheet_payloads = _verify_bundle_files(
        manifest["contact_sheet_bundle"], f"{split} contact sheet"
    )
    _verify_contact_sheet_layout(manifest["contact_sheet_bundle"], spec, split, codes)

    common.require_exact_keys(
        review_index, _REVIEW_INDEX_KEYS, f"{split} development review-index"
    )
    pages = review_index.get("pages")
    expected_review_views = [
        str(view["id"]) for view in spec["contact_sheets"]["views"]
    ]
    if (
        review_index.get("artifact") != "microtexture-v2-r6-development-review-index"
        or review_index.get("schema_version")
        != "microtexture-v2-r6-development-review-index/1"
        or review_index.get("authority") is not False
        or review_index.get("formal_use_forbidden") is not True
        or review_index.get("split") != split
        or review_index.get("spec_sha256") != state["spec_sha256"]
        or review_index.get("views") != expected_review_views
        or review_index.get("layout")
        != "one anonymous code per row with a black header above its panels; full-200 plus all four 400-percent quadrants"
        or not isinstance(pages, list)
        or len(pages) != EXPECTED_REVIEW_PAGES_PER_SPLIT
    ):
        raise RuntimeError(f"{split} development review-index drift")
    page_rows: dict[tuple[int, int], str] = {}
    indexed_codes: list[str] = []
    review_board_payloads: dict[str, bytes] = {}
    for expected_page, page in enumerate(pages, start=1):
        common.require_exact_keys(
            page,
            _REVIEW_INDEX_PAGE_KEYS,
            f"{split} review page[{expected_page}]",
        )
        if (
            type(page.get("page_index")) is not int
            or page.get("page_index") != expected_page
        ):
            raise RuntimeError(f"{split} review page ordering drift")
        item_codes = page.get("item_codes")
        remaining = EXPECTED_RECORDS_PER_SPLIT - (
            (expected_page - 1) * REVIEW_ROWS_PER_PAGE
        )
        expected_count = min(REVIEW_ROWS_PER_PAGE, remaining)
        expected_page_codes = codes[
            (expected_page - 1) * REVIEW_ROWS_PER_PAGE : expected_page
            * REVIEW_ROWS_PER_PAGE
        ]
        if (
            not isinstance(item_codes, list)
            or len(item_codes) != expected_count
            or item_codes != expected_page_codes
        ):
            raise RuntimeError(f"{split} review page row-count drift: {expected_page}")
        relative = page.get("path")
        expected_relative = (
            f"public/{split}/review-boards/review-page-{expected_page:03d}.png"
        )
        if relative != expected_relative:
            raise RuntimeError(f"{split} review page path drift: {expected_page}")
        path = _checked_dev_file(relative, f"{split} review page {expected_page}")
        _require_sha256(page.get("sha256"), f"{split} review page SHA")
        payload = path.read_bytes()
        if _sha256(payload) != page.get("sha256"):
            raise RuntimeError(f"{split} review page SHA drift: {expected_page}")
        review_board_payloads[relative] = payload
        for row, code in enumerate(item_codes, start=1):
            page_rows[(expected_page, row)] = code
            indexed_codes.append(code)
    if (
        len(indexed_codes) != EXPECTED_RECORDS_PER_SPLIT
        or len(set(indexed_codes)) != EXPECTED_RECORDS_PER_SPLIT
        or set(indexed_codes) != set(codes)
    ):
        raise RuntimeError(f"{split} review-index code coverage drift")

    if not require_completed_decisions:
        return {
            "split": split,
            "manifest": manifest,
            "manifest_sha256": manifest_sha,
            "blank_labels": blank_labels,
            "blank_labels_sha256": _sha256(blank_labels_payload),
            "review_index": review_index,
            "review_index_sha256": _sha256(review_index_payload),
            "contact_sheet_payloads": contact_sheet_payloads,
            "review_board_payloads": review_board_payloads,
        }

    _validate_r17_initial_decision_gate_manifest()
    decision_relatives = {
        "canonical": f"public/{split}/vision-decisions.dev.txt",
        "root": f"public/{split}/decisions-root.dev.txt",
        "independent": f"public/{split}/decisions-independent.dev.txt",
    }
    decision_payloads = {
        reviewer: _checked_dev_file(
            relative, f"{split} {reviewer} Vision decisions"
        ).read_bytes()
        for reviewer, relative in decision_relatives.items()
    }
    if not (
        decision_payloads["canonical"]
        == decision_payloads["root"]
        == decision_payloads["independent"]
    ):
        raise RuntimeError(
            f"{split} final Vision decisions are not exact three-way bytes"
        )
    initial_snapshots = {
        reviewer: _read_verified_initial_decision_snapshot(split, reviewer)
        for reviewer in ("root", "independent")
    }
    decisions = _parse_decisions_payload(
        decision_payloads["canonical"], str(decisions_path)
    )
    root_decisions = _parse_decisions_payload(
        decision_payloads["root"], str(root_decisions_path)
    )
    independent_decisions = _parse_decisions_payload(
        decision_payloads["independent"], str(independent_decisions_path)
    )
    root_initial_decisions = initial_snapshots["root"][1]
    independent_initial_decisions = initial_snapshots["independent"][1]
    for reviewer, reviewed in (
        ("canonical Root", decisions),
        ("Root", root_decisions),
        ("independent", independent_decisions),
        ("initial Root", root_initial_decisions),
        ("initial independent", independent_initial_decisions),
    ):
        if set(reviewed) != set(page_rows):
            raise RuntimeError(f"{split} {reviewer} Vision decision coverage drift")
        if any(
            decision["anonymous_code"] != page_rows[key]
            for key, decision in reviewed.items()
        ):
            raise RuntimeError(f"{split} {reviewer} Vision printed-code binding drift")
    if decisions != root_decisions:
        raise RuntimeError(f"{split} canonical decisions are not exact Root decisions")
    logical_difference_count = sum(
        root_decisions[key] != independent_decisions[key]
        for key in sorted(root_decisions)
    )
    if logical_difference_count != 0:
        raise RuntimeError(
            f"{split} Root/independent Vision decisions are not reconciled"
        )
    visible_fields = tuple(_FLAG_FIELDS.values())
    for key in sorted(decisions):
        unsupported_final_flags = {
            field
            for field in visible_fields
            if decisions[key][field]
            and not (
                root_initial_decisions[key][field]
                and independent_initial_decisions[key][field]
            )
        }
        if unsupported_final_flags:
            raise RuntimeError(
                f"{split} final visible flags lack bilateral initial support"
            )
    by_code = {decision["anonymous_code"]: decision for decision in decisions.values()}
    completed = deepcopy(blank_labels)
    items = completed.get("items")
    if (
        completed.get("manifest_sha256") != manifest_sha
        or completed.get("spec_sha256") != state["spec_sha256"]
        or not isinstance(items, list)
        or len(items) != EXPECTED_RECORDS_PER_SPLIT
    ):
        raise RuntimeError(f"{split} blank label binding drift")
    for item in items:
        code = item.get("anonymous_code") if isinstance(item, dict) else None
        if code not in by_code:
            raise RuntimeError(f"{split} blank label code drift")
        item.update(by_code[code])
    labels = common.validate_vision_labels_payload(
        completed, split, manifest, manifest_sha, state
    )
    return {
        "split": split,
        "manifest": manifest,
        "manifest_sha256": manifest_sha,
        "blank_labels_sha256": _sha256(blank_labels_payload),
        "review_index": review_index,
        "contact_sheet_payloads": contact_sheet_payloads,
        "review_board_payloads": review_board_payloads,
        "completed_labels": completed,
        "labels": labels,
        "completed_labels_sha256": _sha256(_json_bytes(completed)),
        "review_index_sha256": _sha256(review_index_payload),
        "decisions_sha256": _sha256(decision_payloads["canonical"]),
        "root_decisions_sha256": _sha256(decision_payloads["root"]),
        "independent_decisions_sha256": _sha256(decision_payloads["independent"]),
        "root_initial_decisions_sha256": initial_snapshots["root"][2],
        "root_initial_decisions_receipt_sha256": initial_snapshots["root"][3],
        "independent_initial_decisions_sha256": initial_snapshots["independent"][2],
        "independent_initial_decisions_receipt_sha256": initial_snapshots[
            "independent"
        ][3],
        "initial_decision_gate_manifest_sha256": (
            _R17_INITIAL_DECISION_GATE_MANIFEST_SHA256
        ),
        "root_independent_logical_difference_count": logical_difference_count,
        "dispositions": dict(Counter(item["disposition"] for item in labels.values())),
    }


def _generation_preflight() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, str],
    dict[str, dict[str, Any]],
]:
    _assert_development_boundary(root_must_not_exist=False)
    spec, spec_sha = _load_spec()
    state, generation_receipts, generation_binding = _load_generation_state(
        spec, spec_sha
    )
    captured_head, bindings_sha = _tracked_input_preflight(spec, spec_sha)
    if (
        state.get("captured_git_head") != captured_head
        or state.get("implementation_bindings_sha256") != bindings_sha
        or state.get("runtime") != common.runtime_fingerprint()
    ):
        raise RuntimeError(
            "development captured authority or runtime changed after generation"
        )
    return spec, state, generation_binding, generation_receipts


def _public_preflight() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, str], dict[str, Any]
]:
    spec, state, generation_binding, generation_receipts = _generation_preflight()
    prepared = {
        split: _prepare_public_split(
            spec, state, split, generation_receipts[split]
        )
        for split in ("calibration", "holdout")
    }
    return spec, state, generation_binding, prepared


def _review_preflight() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, str], dict[str, Any]
]:
    spec, state, generation_binding, generation_receipts = _generation_preflight()
    prepared = {
        split: _prepare_public_split(
            spec,
            state,
            split,
            generation_receipts[split],
            require_completed_decisions=False,
        )
        for split in ("calibration", "holdout")
    }
    return spec, state, generation_binding, prepared


def preflight() -> None:
    _spec, _state, _generation_binding, prepared = _public_preflight()
    _assert_development_boundary(root_must_not_exist=False)
    print(
        json.dumps(
            {
                "authority": False,
                "formal_use_forbidden": True,
                "formal_root_absent": True,
                "key_read": False,
                "labels_written": False,
                "splits": {
                    split: {
                        "record_count": len(result["labels"]),
                        "completed_labels_sha256": result["completed_labels_sha256"],
                        "dispositions": result["dispositions"],
                    }
                    for split, result in prepared.items()
                },
            },
            ensure_ascii=False,
        )
    )


def _regenerate_controls(
    spec: dict[str, Any], key: bytes, split: str, manifest: dict[str, Any]
) -> list[Any]:
    controls = sorted(
        expected_controls(spec, split, key), key=lambda item: item.anonymous_code
    )
    _validate_expected_control_population(controls, split)
    by_code = {control.anonymous_code: control for control in controls}
    if (
        len(controls) != EXPECTED_RECORDS_PER_SPLIT
        or len(by_code) != EXPECTED_RECORDS_PER_SPLIT
    ):
        raise RuntimeError(f"{split} regenerated control coverage drift")
    manifest_codes: set[str] = set()
    for record in manifest["records"]:
        code = record["anonymous_code"]
        control = by_code.get(code)
        if (
            control is None
            or record.get("control_commitment") != control.control_commitment
            or record.get("reference_commitment") != control.reference_commitment
            or record.get("delta_commitment") != control.delta_commitment
        ):
            raise RuntimeError(f"{split} regenerated public commitment drift")
        manifest_codes.add(code)
    if manifest_codes != set(by_code):
        raise RuntimeError(f"{split} regenerated manifest code drift")
    return controls


def _verify_regenerated_review_surfaces(
    spec: dict[str, Any],
    split: str,
    controls: list[Any],
    manifest: dict[str, Any],
    review_index: dict[str, Any],
    contact_sheet_payloads: dict[str, bytes],
    review_board_payloads: dict[str, bytes],
) -> None:
    regenerated_sheets = contact_sheet_pages(spec, split, controls)
    recorded_sheets = manifest.get("contact_sheet_bundle")
    if (
        not isinstance(recorded_sheets, list)
        or len(recorded_sheets) != EXPECTED_CONTACT_SHEETS_PER_SPLIT
        or len(regenerated_sheets) != EXPECTED_CONTACT_SHEETS_PER_SPLIT
    ):
        raise RuntimeError(f"{split} regenerated contact-sheet coverage drift")
    expected_sheet_paths: set[str] = set()
    for index, (regenerated, recorded) in enumerate(
        zip(regenerated_sheets, recorded_sheets, strict=True)
    ):
        expected_entry = regenerated.manifest_entry()
        expected_entry["path"] = (
            f"public/{split}/contact-sheets/{Path(regenerated.path).name}"
        )
        if recorded != expected_entry:
            raise RuntimeError(
                f"{split} regenerated contact-sheet manifest drift: {index}"
            )
        expected_sheet_paths.add(expected_entry["path"])
        if contact_sheet_payloads.get(expected_entry["path"]) != regenerated.png_bytes:
            raise RuntimeError(
                f"{split} regenerated contact-sheet byte drift: {index}"
            )
    if set(contact_sheet_payloads) != expected_sheet_paths:
        raise RuntimeError(f"{split} regenerated contact-sheet capture drift")

    recorded_boards = review_index.get("pages")
    if (
        not isinstance(recorded_boards, list)
        or len(recorded_boards) != EXPECTED_REVIEW_PAGES_PER_SPLIT
    ):
        raise RuntimeError(f"{split} regenerated review-board coverage drift")
    expected_board_paths: set[str] = set()
    for page_index, recorded in enumerate(recorded_boards, start=1):
        codes, payload = _review_board_payload(
            controls, spec["contact_sheets"]["views"], page_index
        )
        expected_path = f"public/{split}/review-boards/review-page-{page_index:03d}.png"
        if (
            type(recorded.get("page_index")) is not int
            or recorded.get("page_index") != page_index
            or recorded.get("path") != expected_path
            or recorded.get("sha256") != _sha256(payload)
            or recorded.get("item_codes") != codes
        ):
            raise RuntimeError(
                f"{split} regenerated review-board index drift: {page_index}"
            )
        expected_board_paths.add(expected_path)
        if review_board_payloads.get(expected_path) != payload:
            raise RuntimeError(
                f"{split} regenerated review-board byte drift: {page_index}"
            )
    if set(review_board_payloads) != expected_board_paths:
        raise RuntimeError(f"{split} regenerated review-board capture drift")


def _eligible_clusters(controls: list[Any], spec: dict[str, Any]) -> dict[str, str]:
    eligible_role = spec["threshold_selection"]["endpoint_eligible_private_role"]
    clusters = {
        control.anonymous_code: control.condition_cluster_id
        for control in controls
        if control.private_role == eligible_role
    }
    if not clusters:
        raise RuntimeError("development eligible cluster set is empty")
    return clusters


def _exact_metric_window(values: np.ndarray, spec: dict[str, Any]) -> np.ndarray:
    expected_canvas = (int(spec["canvas"]["height"]), int(spec["canvas"]["width"]))
    if values.shape != expected_canvas:
        raise RuntimeError(f"development control canvas drift: {values.shape}")
    x, y, width, height = [
        int(value) for value in spec["canvas"]["metric_window"]["xywh"]
    ]
    crop = values[y : y + height, x : x + width]
    expected = tuple(
        int(value) for value in spec["metric_definition"]["expected_shape_hw"]
    )
    if crop.shape != expected:
        raise RuntimeError("development exact metric-window crop drift")
    return crop


def _measure_split(
    controls: list[Any], clusters: dict[str, str], spec: dict[str, Any], split: str
) -> dict[str, dict[str, Any]]:
    measured: dict[str, dict[str, Any]] = {}
    controls_by_code = {control.anonymous_code: control for control in controls}
    for index, control in enumerate(controls, start=1):
        metrics = measure(
            _exact_metric_window(control.control, spec),
            _exact_metric_window(control.reference, spec),
            spec["metric_definition"],
        )
        common.validate_metric_values(metrics, spec, f"{split} development metric")
        if control.private_role == "protocol-zero" and any(
            value != 0 for name, value in metrics.items() if name != "eligible_pixels"
        ):
            raise RuntimeError(f"{split} protocol-zero metric drift")
        measured[control.anonymous_code] = {
            "anonymous_code": control.anonymous_code,
            "metrics": metrics,
        }
        if index % 20 == 0 or index == len(controls):
            print(f"{split}: measured {index}/{len(controls)}", flush=True)
    members: dict[str, list[str]] = {}
    for code, cluster_id in clusters.items():
        members.setdefault(cluster_id, []).append(code)
    for cluster_id, codes in members.items():
        if (
            len(codes) != 2
            or measured[codes[0]]["metrics"] != measured[codes[1]]["metrics"]
        ):
            raise RuntimeError(
                f"{split} full metric-equivalent polarity-pair drift: {cluster_id}"
            )
    if set(measured) != set(controls_by_code):
        raise RuntimeError(f"{split} measurement coverage drift")
    return measured


def _population_audit(
    labels: dict[str, dict[str, Any]],
    clusters: dict[str, str],
    spec: dict[str, Any],
    split: str,
) -> dict[str, Any]:
    counts = Counter(clusters.values())
    exact_pairs = bool(counts) and all(count == 2 for count in counts.values())
    endpoint_audit = common.endpoint_population_count_audit(labels, clusters, spec)
    frozen_floors = spec.get("population_anchor_schedule", {}).get(
        "development_premeasurement_safety_floors"
    )
    if frozen_floors != DEVELOPMENT_POPULATION_FLOORS:
        raise RuntimeError(f"{split} development safety-floor authority drift")
    if set(endpoint_audit["endpoints"]) != set(DEVELOPMENT_POPULATION_FLOORS):
        raise RuntimeError(f"{split} development endpoint set drift")
    development_endpoints = {
        endpoint_id: {
            "unique_cluster_count": endpoint_audit["endpoints"][endpoint_id][
                "unique_cluster_count"
            ],
            "development_minimum_unique_clusters": minimum,
            "count_passed": endpoint_audit["endpoints"][endpoint_id][
                "unique_cluster_count"
            ]
            >= minimum,
        }
        for endpoint_id, minimum in DEVELOPMENT_POPULATION_FLOORS.items()
    }
    development_audit = {
        "passed": all(item["count_passed"] for item in development_endpoints.values()),
        "endpoints": development_endpoints,
    }
    return {
        "split": split,
        "condition_cluster_count": len(counts),
        "all_condition_clusters_exact_polarity_pairs": exact_pairs,
        **endpoint_audit,
        "formal_endpoint_minimums_passed": endpoint_audit["passed"],
        "development_safety_floor_audit": development_audit,
        "passed": exact_pairs
        and endpoint_audit["passed"]
        and development_audit["passed"],
    }


def _regenerate_and_audit_population(
    spec: dict[str, Any],
    key: bytes,
    prepared: dict[str, dict[str, Any]],
) -> tuple[
    dict[str, list[Any]],
    dict[str, dict[str, str]],
    dict[str, Any],
]:
    controls: dict[str, list[Any]] = {}
    for split, result in prepared.items():
        split_controls = _regenerate_controls(spec, key, split, result["manifest"])
        controls[split] = split_controls
        _verify_regenerated_review_surfaces(
            spec,
            split,
            split_controls,
            result["manifest"],
            result["review_index"],
            result["contact_sheet_payloads"],
            result["review_board_payloads"],
        )

    clusters: dict[str, dict[str, str]] = {}
    for split, result in prepared.items():
        split_controls = controls[split]
        common.validate_private_vision_label_audits(
            result["labels"],
            [
                {
                    "anonymous_code": control.anonymous_code,
                    "private_role": control.private_role,
                    "duplicate_audit_group": control.duplicate_audit_group,
                }
                for control in split_controls
            ],
            f"{split} development sealed labels",
        )
        clusters[split] = _eligible_clusters(split_controls, spec)

    population: dict[str, Any] = {}
    for split, result in prepared.items():
        population[split] = _population_audit(
            result["labels"], clusters[split], spec, split
        )
    return controls, clusters, population


def analyze() -> None:
    spec, state, generation_binding, prepared = _public_preflight()
    _assert_private_analysis_boundary(analysis_must_exist=False)
    if PRIVATE_ANALYSIS_ROOT.exists() or PRIVATE_ANALYSIS_ROOT.is_symlink():
        raise RuntimeError(
            "development analysis was already started; do not rerun or revise labels"
        )
    PRIVATE_ANALYSIS_ROOT.mkdir(parents=True, exist_ok=False)
    _assert_private_analysis_boundary(analysis_must_exist=True)
    measurement_started = False
    try:
        sealed: dict[str, Any] = {}
        for split, result in prepared.items():
            relative = Path("sealed-labels") / f"{split}.completed.dev.json"
            digest = _write_json_exclusive(
                PRIVATE_ANALYSIS_ROOT / relative, result["completed_labels"]
            )
            if digest != result["completed_labels_sha256"]:
                raise RuntimeError(f"{split} completed-label seal SHA drift")
            sealed[split] = {
                "path": relative.as_posix(),
                "sha256": digest,
                "manifest_sha256": result["manifest_sha256"],
                "blank_labels_sha256": result["blank_labels_sha256"],
                "review_index_sha256": result["review_index_sha256"],
                "decisions_sha256": result["decisions_sha256"],
                "root_decisions_sha256": result["root_decisions_sha256"],
                "independent_decisions_sha256": result["independent_decisions_sha256"],
                "root_initial_decisions_sha256": result[
                    "root_initial_decisions_sha256"
                ],
                "root_initial_decisions_receipt_sha256": result[
                    "root_initial_decisions_receipt_sha256"
                ],
                "independent_initial_decisions_sha256": result[
                    "independent_initial_decisions_sha256"
                ],
                "independent_initial_decisions_receipt_sha256": result[
                    "independent_initial_decisions_receipt_sha256"
                ],
                "initial_decision_gate_manifest_sha256": result[
                    "initial_decision_gate_manifest_sha256"
                ],
                "root_independent_logical_difference_count": result[
                    "root_independent_logical_difference_count"
                ],
                "record_count": len(result["labels"]),
                "dispositions": result["dispositions"],
            }
        seal_receipt = {
            "artifact": "microtexture-v2-r6-development-label-seal",
            "schema_version": "microtexture-v2-r6-development-label-seal/3",
            "authority": False,
            "formal_use_forbidden": True,
            "root_vision_blind_during_all_decisions": True,
            "private_key_read_after_both_label_files_sealed": True,
            "spec_sha256": state["spec_sha256"],
            "implementation_bindings_sha256": state["implementation_bindings_sha256"],
            "blind_key_commitment": state["blind_key_commitment"],
            **generation_binding,
            "splits": sealed,
        }
        seal_sha = _write_json_exclusive(
            PRIVATE_ANALYSIS_ROOT / "label-seal-receipt.dev.json", seal_receipt
        )

        key = (DEV_ROOT / "private" / "development-key.bin").read_bytes()
        if (
            len(key) != 32
            or common.blind_commitment(key) != state["blind_key_commitment"]
        ):
            raise RuntimeError("development blind-key commitment drift")

        controls, clusters, population = _regenerate_and_audit_population(
            spec, key, prepared
        )
        population_artifact = {
            "artifact": "microtexture-v2-r6-development-premeasurement-population-audit",
            "schema_version": "microtexture-v2-r6-development-premeasurement-population-audit/1",
            "authority": False,
            "formal_use_forbidden": True,
            "measurement_started": False,
            "label_seal_receipt_sha256": seal_sha,
            "splits": population,
            "passed": all(item["passed"] for item in population.values()),
        }
        _write_json_exclusive(
            PRIVATE_ANALYSIS_ROOT / "population-audit.dev.json", population_artifact
        )
        if not population_artifact["passed"]:
            raise RuntimeError(
                "development endpoint population premeasurement audit failed"
            )
        for split, result in prepared.items():
            common.validate_endpoint_population_counts(
                result["labels"], clusters[split], spec
            )

        measurement_started = True
        measured = {
            split: _measure_split(controls[split], clusters[split], spec, split)
            for split in ("calibration", "holdout")
        }
        for split, values in measured.items():
            _write_json_exclusive(
                PRIVATE_ANALYSIS_ROOT / f"{split}-measurements.dev.json",
                {
                    "artifact": "microtexture-v2-r6-development-measurements",
                    "schema_version": "microtexture-v2-r6-development-measurements/1",
                    "authority": False,
                    "formal_use_forbidden": True,
                    "split": split,
                    "label_seal_receipt_sha256": seal_sha,
                    "measurements": [values[code] for code in sorted(values)],
                },
            )

        hard_threshold, calibration_endpoints, _calibration_results, status, audit = (
            common.select_hard_threshold_from_measurements(
                measured["calibration"],
                prepared["calibration"]["labels"],
                clusters["calibration"],
                spec,
            )
        )
        holdout_endpoints: dict[str, Any] | None = None
        if hard_threshold is not None:
            holdout_endpoints, _holdout_results = (
                common.evaluate_endpoints_from_measurements(
                    float(hard_threshold["threshold"]),
                    measured["holdout"],
                    prepared["holdout"]["labels"],
                    clusters["holdout"],
                    "holdout",
                    spec,
                )
            )
        passed = hard_threshold is not None and holdout_endpoints is not None
        passed = bool(
            passed
            and all(item["passed"] for item in calibration_endpoints.values())
            and all(item["passed"] for item in holdout_endpoints.values())
        )
        result_artifact = {
            "artifact": "microtexture-v2-r6-development-probe-result",
            "schema_version": "microtexture-v2-r6-development-probe-result/1",
            "authority": False,
            "formal_use_forbidden": True,
            "development_threshold_not_formal_authority": True,
            "formal_cli_invoked": False,
            "formal_marker_created": False,
            "locked_clean_v18_decoded_or_measured": False,
            "label_seal_receipt_sha256": seal_sha,
            "result_status": status,
            "passed": passed,
            "development_hard_threshold": hard_threshold,
            "calibration_endpoint_performance": calibration_endpoints,
            "holdout_endpoint_performance": holdout_endpoints,
            "threshold_selection_audit": audit,
        }
        _write_json_exclusive(
            PRIVATE_ANALYSIS_ROOT / "analysis-result.dev.json", result_artifact
        )
        if not passed:
            raise RuntimeError(
                "development metric schedule did not pass calibration and holdout"
            )
        _assert_development_boundary(root_must_not_exist=False)
        print(
            json.dumps(
                {
                    "authority": False,
                    "formal_use_forbidden": True,
                    "formal_root_absent": True,
                    "passed": True,
                    "result_status": status,
                    "development_threshold_not_formal_authority": True,
                    "calibration_endpoint_performance": calibration_endpoints,
                    "holdout_endpoint_performance": holdout_endpoints,
                },
                ensure_ascii=False,
            )
        )
    except BaseException as error:
        _assert_private_analysis_boundary(analysis_must_exist=True)
        failure_path = PRIVATE_ANALYSIS_ROOT / "FAILED.dev.json"
        if not failure_path.exists() and not failure_path.is_symlink():
            _write_json_exclusive(
                failure_path,
                {
                    "artifact": "microtexture-v2-r6-development-analysis-failure",
                    "schema_version": "microtexture-v2-r6-development-analysis-failure/1",
                    "authority": False,
                    "formal_use_forbidden": True,
                    "development_edition": DEVELOPMENT_EDITION,
                    "development_closed": True,
                    "measurement_started": measurement_started,
                    "error_type": type(error).__name__,
                    "message": _sanitized_error_message(error),
                },
            )
        _assert_development_boundary(root_must_not_exist=False)
        raise


def postmortem() -> None:
    """Read-only reveal for a closed development probe; never emits key material."""
    failure = PRIVATE_ANALYSIS_ROOT / "FAILED.dev.json"
    if not failure.is_file():
        raise RuntimeError("development postmortem requires a closed failed probe")
    spec, state, _generation_binding, prepared = _public_preflight()
    key = (DEV_ROOT / "private" / "development-key.bin").read_bytes()
    if len(key) != 32 or common.blind_commitment(key) != state["blind_key_commitment"]:
        raise RuntimeError("development blind-key commitment drift")
    findings: dict[str, Any] = {}
    for split, result in prepared.items():
        controls = _regenerate_controls(spec, key, split, result["manifest"])
        page_by_code: dict[str, dict[str, int]] = {}
        index = _read_json(DEV_ROOT / "public" / split / "review-index.dev.json")
        for page in index["pages"]:
            for row, code in enumerate(page["item_codes"], start=1):
                page_by_code[code] = {"page": page["page_index"], "row": row}
        revealed = []
        speck_artifacts = []
        role_counts: Counter[str] = Counter()
        role_dispositions: dict[str, Counter[str]] = {}
        for control in controls:
            role_counts[control.private_role] += 1
            label = result["labels"][control.anonymous_code]
            role_dispositions.setdefault(control.private_role, Counter())[
                label["disposition"]
            ] += 1
            if control.private_role != "artifact":
                revealed.append(
                    {
                        **page_by_code[control.anonymous_code],
                        "private_role": control.private_role,
                        "duplicate_audit_group": control.duplicate_audit_group,
                        "disposition": label["disposition"],
                        "severity": label["severity_0_to_3"],
                        "visible_flags": [
                            flag for flag, field in _FLAG_FIELDS.items() if label[field]
                        ],
                        "notes": label["notes"],
                    }
                )
            elif control.family == "artifact-speck":
                speck_artifacts.append(
                    {
                        **page_by_code[control.anonymous_code],
                        "family": control.family,
                        "polarity": control.polarity,
                        "variant_index": control.variant_index,
                        "disposition": label["disposition"],
                        "severity": label["severity_0_to_3"],
                        "visible_flags": [
                            flag for flag, field in _FLAG_FIELDS.items() if label[field]
                        ],
                        "notes": label["notes"],
                    }
                )
        findings[split] = {
            "role_counts": dict(role_counts),
            "role_dispositions": {
                role: dict(counts) for role, counts in role_dispositions.items()
            },
            "non_artifact_rows": sorted(
                revealed, key=lambda item: (item["page"], item["row"])
            ),
            "artifact_speck_rows": sorted(
                speck_artifacts, key=lambda item: (item["page"], item["row"])
            ),
        }
    _assert_development_boundary(root_must_not_exist=False)
    print(
        json.dumps(
            {
                "authority": False,
                "formal_use_forbidden": True,
                "closed_development_probe_only": True,
                "findings": findings,
            },
            ensure_ascii=False,
        )
    )


def generate() -> None:
    _assert_development_boundary(root_must_not_exist=True)
    spec, spec_sha = _load_spec()
    captured_head, bindings_sha = _tracked_input_preflight(spec, spec_sha)
    key_path = _validate_development_key_git_boundary(spec, captured_head)
    DEV_ROOT.mkdir(parents=True, exist_ok=False)
    (DEV_ROOT / "private").mkdir()
    # The root is the earliest durable consumed-edition evidence. Sample the key
    # only after it exists so an interruption can never silently resample r17.
    key = secrets.token_bytes(32)
    state = {
        "development_edition": DEVELOPMENT_EDITION,
        "spec_sha256": spec_sha,
        "public_nonces": _public_nonces(spec),
        "implementation_bindings_sha256": bindings_sha,
        "blind_key_commitment": common.blind_commitment(key),
        "captured_git_head": captured_head,
        "runtime": common.runtime_fingerprint(),
    }
    with key_path.open("xb") as output:
        output.write(key)
        output.flush()
        os.fsync(output.fileno())
    boundary = {
        "artifact": "microtexture-v2-r6-development-only-boundary",
        "schema_version": "microtexture-v2-r6-development-only-boundary/1",
        "authority": False,
        "formal_use_forbidden": True,
        "formal_cli_invoked": False,
        "formal_marker_created": False,
        "formal_threshold_created": False,
        "locked_clean_v18_decoded_or_measured": False,
        "exact_formal_root_absent_before_generation": True,
        "formal_environment_absent_before_generation": True,
        **state,
    }
    boundary_sha = _write_json_exclusive(DEV_ROOT / "DEV-ONLY.json", boundary)
    generation_start_sha = _write_json_exclusive(
        DEV_ROOT / "generation-start.dev.json",
        {
            "artifact": "microtexture-v2-r6-development-generation-start",
            "schema_version": "microtexture-v2-r6-development-generation-start/1",
            "authority": False,
            "formal_use_forbidden": True,
            "one_shot_consumed": True,
            "started_at": common.utc_timestamp(),
            "development_boundary_sha256": boundary_sha,
            "state": state,
        },
    )
    try:
        results = [
            _generate_split(spec, split, key, state)
            for split in ("calibration", "holdout")
        ]
        calibration, holdout = results
        for field in ("codes", "control_ids", "cluster_ids", "nonzero_delta_hashes"):
            if set(calibration[field]) & set(holdout[field]):
                raise RuntimeError(f"development split separation failed: {field}")
        calibration_zero = set(calibration["zero_delta_hashes"])
        holdout_zero = set(holdout["zero_delta_hashes"])
        if len(calibration_zero) != 1 or calibration_zero != holdout_zero:
            raise RuntimeError("canonical all-zero requested-delta hash contract drift")
        public_results = [
            {
                key: value
                for key, value in result.items()
                if key
                not in {
                    "codes",
                    "control_ids",
                    "cluster_ids",
                    "nonzero_delta_hashes",
                    "zero_delta_hashes",
                }
            }
            for result in results
        ]
        generation_summary = {
            "artifact": "microtexture-v2-r6-development-generation-summary",
            "schema_version": "microtexture-v2-r6-development-generation-summary/1",
            "authority": False,
            "formal_use_forbidden": True,
            "state": state,
            "split_separation": {
                "codes_disjoint": True,
                "control_ids_disjoint": True,
                "cluster_ids_disjoint": True,
                "nonzero_delta_hashes_disjoint": True,
                "canonical_all_zero_delta_hash_shared": True,
            },
            "splits": public_results,
        }
        generation_summary_sha = _write_json_exclusive(
            DEV_ROOT / "generation-summary.dev.json", generation_summary
        )
        generation_seal_sha = _write_json_exclusive(
            DEV_ROOT / "generation-seal.dev.json",
            {
                "artifact": "microtexture-v2-r6-development-generation-seal",
                "schema_version": "microtexture-v2-r6-development-generation-seal/1",
                "authority": False,
                "formal_use_forbidden": True,
                "generation_start_sha256": generation_start_sha,
                "generation_summary_sha256": generation_summary_sha,
                "spec_sha256": state["spec_sha256"],
                "implementation_bindings_sha256": state[
                    "implementation_bindings_sha256"
                ],
                "blind_key_commitment": state["blind_key_commitment"],
                "captured_git_head": state["captured_git_head"],
            },
        )
        _assert_development_boundary(root_must_not_exist=False)
        generation_completion_sha = _write_json_exclusive(
            DEV_ROOT / "generation-completion.dev.json",
            {
                "artifact": "microtexture-v2-r6-development-generation-completion",
                "schema_version": (
                    "microtexture-v2-r6-development-generation-completion/1"
                ),
                "authority": False,
                "formal_use_forbidden": True,
                "completed_at": common.utc_timestamp(),
                "generation_start_sha256": generation_start_sha,
                "generation_summary_sha256": generation_summary_sha,
                "generation_seal_sha256": generation_seal_sha,
                "spec_sha256": state["spec_sha256"],
                "implementation_bindings_sha256": state[
                    "implementation_bindings_sha256"
                ],
                "blind_key_commitment": state["blind_key_commitment"],
                "captured_git_head": state["captured_git_head"],
            },
        )
        (
            verified_spec,
            verified_state,
            verified_generation_binding,
            verified_surfaces,
        ) = _review_preflight()
        expected_generation_binding = {
            "generation_start_sha256": generation_start_sha,
            "generation_summary_sha256": generation_summary_sha,
            "generation_seal_sha256": generation_seal_sha,
            "generation_completion_sha256": generation_completion_sha,
        }
        if (
            verified_spec != spec
            or verified_state != state
            or verified_generation_binding != expected_generation_binding
            or set(verified_surfaces) != {"calibration", "holdout"}
        ):
            raise RuntimeError("development generation post-completion reload drift")
    except BaseException as error:
        try:
            _write_json_exclusive(
                DEV_ROOT / "generation-failure.dev.json",
                {
                    "artifact": "microtexture-v2-r6-development-generation-failure",
                    "schema_version": (
                        "microtexture-v2-r6-development-generation-failure/1"
                    ),
                    "authority": False,
                    "formal_use_forbidden": True,
                    "failed_at": common.utc_timestamp(),
                    "generation_start_sha256": generation_start_sha,
                    "error_type": type(error).__name__,
                    "message": _sanitized_error_message(error),
                    "development_closed": True,
                },
            )
        except BaseException as reporting_error:
            try:
                error.add_note(
                    "generation failure reporting also failed: "
                    f"{type(reporting_error).__name__}: {reporting_error}"
                )
            except BaseException:
                pass
        raise
    print(
        json.dumps(
            {
                "development_root": str(DEV_ROOT),
                "authority": False,
                "formal_root_absent": True,
                "generation_start_sha256": generation_start_sha,
                "generation_summary_sha256": generation_summary_sha,
                "generation_seal_sha256": generation_seal_sha,
                "generation_completion_sha256": generation_completion_sha,
                "splits": public_results,
            },
            ensure_ascii=False,
        )
    )


def review_crops(split: str, page_index: int) -> None:
    if (
        split not in {"calibration", "holdout"}
        or not 1 <= page_index <= EXPECTED_REVIEW_PAGES_PER_SPLIT
    ):
        raise RuntimeError("review crop split/page drift")
    _spec, _state, _generation_binding, prepared = _review_preflight()
    relative = (
        f"public/{split}/review-boards/review-page-{page_index:03d}.png"
    )
    payload = prepared[split]["review_board_payloads"][relative]
    with Image.open(io.BytesIO(payload)) as board:
        if board.size != (2560, REVIEW_ROW_HEIGHT * REVIEW_ROWS_PER_PAGE):
            raise RuntimeError("review board dimensions drift")
        output_root = DEV_ROOT / "public" / split / "review-crops"
        output_root.mkdir(parents=True, exist_ok=True)
        evidence = board.convert("RGB")
        evidence_draw = ImageDraw.Draw(evidence)
        evidence_font = ImageFont.load_default(size=14)
        quadrant_ids = ("NW", "NE", "SW", "SE")
        for row_index in range(REVIEW_ROWS_PER_PAGE):
            image_top = row_index * REVIEW_ROW_HEIGHT + REVIEW_HEADER_HEIGHT
            for quadrant_column, quadrant_id in enumerate(quadrant_ids, start=1):
                panel_left = quadrant_column * 512
                for division in (1, 2):
                    x = panel_left + round(512 * division / 3)
                    y = image_top + 128 * division
                    evidence_draw.line(
                        (x, image_top, x, image_top + 383),
                        fill=(220, 32, 96),
                        width=2,
                    )
                    evidence_draw.line(
                        (panel_left, y, panel_left + 511, y),
                        fill=(220, 32, 96),
                        width=2,
                    )
                for sector_row in range(1, 4):
                    for sector_column in range(1, 4):
                        label = f"{quadrant_id}-R{sector_row}C{sector_column}"
                        label_x = panel_left + round(512 * (sector_column - 1) / 3) + 4
                        label_y = image_top + 128 * (sector_row - 1) + 4
                        evidence_draw.text(
                            (label_x + 1, label_y + 1),
                            label,
                            fill=(255, 255, 255),
                            font=evidence_font,
                        )
                        evidence_draw.text(
                            (label_x, label_y),
                            label,
                            fill=(190, 0, 70),
                            font=evidence_font,
                        )
        evidence.save(
            output_root / f"evidence-page-{page_index:03d}.png",
            format="PNG",
            compress_level=6,
            optimize=False,
        )
        for row in range(1, REVIEW_ROWS_PER_PAGE + 1):
            top = (row - 1) * REVIEW_ROW_HEIGHT
            output = output_root / f"review-page-{page_index:03d}-row-{row}.png"
            board.crop((0, top, 2560, top + REVIEW_ROW_HEIGHT)).save(
                output, format="PNG", compress_level=6, optimize=False
            )
            native_output = (
                output_root
                / f"review-page-{page_index:03d}-row-{row}-full-200-native.png"
            )
            board.crop(
                (
                    0,
                    top + REVIEW_HEADER_HEIGHT,
                    REVIEW_PANEL_WIDTH,
                    top + REVIEW_ROW_HEIGHT,
                )
            ).save(
                native_output, format="PNG", compress_level=6, optimize=False
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("generate", "preflight", "analyze", "postmortem", "review-crops"),
    )
    parser.add_argument("--split", choices=("calibration", "holdout"))
    parser.add_argument("--page", type=int)
    arguments = parser.parse_args()
    if arguments.command == "generate":
        generate()
    elif arguments.command == "preflight":
        preflight()
    elif arguments.command == "analyze":
        analyze()
    elif arguments.command == "review-crops":
        if arguments.split is None or arguments.page is None:
            parser.error("review-crops requires --split and --page")
        review_crops(arguments.split, arguments.page)
    else:
        postmortem()


if __name__ == "__main__":
    main()
