#!/usr/bin/env python3
"""Validate, preflight, emit, or compare the sealed balanced-open-v3 family.

The default action is validate-only and reads only the preregistration and its
text bindings.  ``--preflight`` additionally verifies the inherited v1 emit-read
closure without decoding a raster.  Candidate construction requires the
explicit ``--emit`` flag.  This module contains construction-only transforms;
it has no acceptance evaluator, threshold override, output override, retry,
or visual-review path.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import heapq
import io
import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, Mapping, Sequence

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_RELATIVE = (
    "world/map-production/spec/"
    "style-candidate-k3-golden-v3-balanced-open-phase-preregistration-v3.json"
)
AUTHORITY_PATH = ROOT / AUTHORITY_RELATIVE
V1_AUTHORITY_RELATIVE = (
    "world/map-production/spec/"
    "style-candidate-k3-golden-v3-four-candidate-derivation-preregistration-v1.json"
)
V1_HELPER_RELATIVE = (
    "scripts/map-production/"
    "generate_style_candidate_k3_golden_v3_four_candidate_phase_v1.py"
)
INTERFACE = "sstory-k3-golden-v3-balanced-open-phase-preregistration-v3"
ALGORITHM = "sstory-k3-golden-v3-balanced-open-independent-band-phase-v3"
SELF_HASH_ZERO = "0" * 64
SHA256_PATTERN = __import__("re").compile(r"^[0-9a-f]{64}$")
Q12 = 1 << 12
Q16 = 1 << 16
Q20 = 1 << 20
Q30 = 1 << 30
MASKED_NUMERATOR_EXTRA = 1 << 2
INT64_MIN = np.iinfo(np.int64).min
INT64_MAX = np.iinfo(np.int64).max
BODY_VALUES = (32, 64, 96, 128, 160, 192, 224, 255)
BODY_IDS = tuple(f"body-{index:02d}" for index in range(1, 9))
G2_COEFFICIENTS = (
    71_851,
    468_526,
    2_379_372,
    9_410_600,
    28_986_689,
    69_535_452,
    129_909_328,
    189_016_957,
    214_184_274,
    189_016_957,
    129_909_328,
    69_535_452,
    28_986_689,
    9_410_600,
    2_379_372,
    468_526,
    71_851,
)
G2_CANONICAL_SHA256 = "b3506b745d252cc4df42172297897ff52cc88ea41726a7bf5c56839c02a543fd"
SEED_ROOT = "sstory-k3-golden-v3-balanced-open-phase-v3"
BAND_IDS = ("g2-g4", "g4-g8", "g8-g24", "amplitude-envelope", "unit-whitening")
CONSTRUCTION_LAGS = (
    (32, 0),
    (0, 32),
    (32, 32),
    (32, -32),
    (64, 0),
    (0, 64),
    (64, 64),
    (64, -64),
    (128, 0),
    (0, 128),
    (128, 128),
    (128, -128),
    (256, 0),
    (0, 256),
)
CONSTRUCTION_SUPPORT_EROSIONS = (0, 12, 24)
REQUIRED_COMPARISON_PROFILES = (
    "windows-local-opencv-python-4.13.0.92",
    "linux-ci-opencv-python-headless-4.13.0.92",
)
EXPECTED_SEED_RULE = {
    "hash_algorithm": "SHA-256",
    "label_encoding": "UTF-8",
    "label_format": "seed_root:body-id:band-id",
    "body_id_format": "body-{one-based-index:02d}",
    "digest_byte_range": [0, 8],
    "integer_byteorder": "big",
    "integer_signed": False,
    "test_vectors": [
        {
            "body_id": "body-01",
            "band_id": "g2-g4",
            "label": "sstory-k3-golden-v3-balanced-open-phase-v3:body-01:g2-g4",
            "sha256": "e67cf421e7a9537f7da8102f9ca77a012dddeca715169a3f2f7a5dd3bb70f9bf",
            "uint64": 16_608_417_952_293_278_591,
        },
        {
            "body_id": "body-08",
            "band_id": "unit-whitening",
            "label": "sstory-k3-golden-v3-balanced-open-phase-v3:body-08:unit-whitening",
            "sha256": "42c4e113dbe4a3e0882835bcbcd0fd611d40a295c0fd00690c7a7a99e7bdea60",
            "uint64": 4_811_217_777_348_355_040,
        },
    ],
}
EXPECTED_CANDIDATES = (
    (
        "E150-M500",
        (3, 20),
        (5, 1),
        "tmp/map-production/k3-golden-v3-balanced-open-phase-v3/"
        "style-candidate-k-v3-golden-v3-E150-M500.png",
    ),
    (
        "E150-M550",
        (3, 20),
        (11, 2),
        "tmp/map-production/k3-golden-v3-balanced-open-phase-v3/"
        "style-candidate-k-v3-golden-v3-E150-M550.png",
    ),
    (
        "E200-M500",
        (1, 5),
        (5, 1),
        "tmp/map-production/k3-golden-v3-balanced-open-phase-v3/"
        "style-candidate-k-v3-golden-v3-E200-M500.png",
    ),
    (
        "E200-M550",
        (1, 5),
        (11, 2),
        "tmp/map-production/k3-golden-v3-balanced-open-phase-v3/"
        "style-candidate-k-v3-golden-v3-E200-M550.png",
    ),
)
TEXT_ONLY_ROLES = {
    "v1-derivation-authority",
    "v1-helper-module",
    "balanced-open-phase-v3-generator",
    "balanced-open-phase-v3-synthetic-tests",
    "sealed-v19-statistics-firewall",
}
V1_EMIT_REFERENCE_ONLY_ROLES = {"strict-audit-authority-reference-only"}
EXPECTED_BINDING_ROLES = (
    "v1-derivation-authority",
    "v1-helper-module",
    "balanced-open-phase-v3-generator",
    "balanced-open-phase-v3-synthetic-tests",
    "sealed-v19-statistics-firewall",
)
EXPECTED_BINDING_PATHS = {
    "v1-derivation-authority": V1_AUTHORITY_RELATIVE,
    "v1-helper-module": V1_HELPER_RELATIVE,
    "balanced-open-phase-v3-generator": (
        "scripts/map-production/"
        "generate_style_candidate_k3_golden_v3_balanced_open_phase_v3.py"
    ),
    "balanced-open-phase-v3-synthetic-tests": (
        "tests/golden_v3_balanced_open_phase_preregistration_test.py"
    ),
    "sealed-v19-statistics-firewall": (
        "world/map-production/controls/style-candidate-k-v3-golden-v3/"
        "v19-statistics-firewall.json"
    ),
}


class DerivationError(RuntimeError):
    """Raised before an unbound or non-preregistered output can be written."""


@dataclass(frozen=True)
class IndependentBands:
    g2_to_g4: np.ndarray
    g4_to_g8: np.ndarray
    g8_to_g24: np.ndarray


@dataclass(frozen=True)
class FinalFields:
    total_q12: np.ndarray
    amplitude_q12: np.ndarray
    unit_q12: np.ndarray


@dataclass(frozen=True)
class LagCertificate:
    eligible_records: int
    maximum_numerator: int
    maximum_variance_product: int
    maximum_correlation_q20: int


@dataclass(frozen=True)
class ConstructionReceipt:
    amplitude_matching_iterations: int
    amplitude_certificate: LagCertificate
    unit_certificate: LagCertificate
    quiet_clipped_pixels: int
    short_dark_repairs: int
    short_dark_pixels: int
    topology_repairs: int
    topology_pixels: int


@dataclass(frozen=True)
class CandidatePayload:
    path: Path
    payload: bytes
    receipt: ConstructionReceipt


def combine_lag_certificates(
    records: Sequence[LagCertificate],
) -> LagCertificate:
    if not records:
        raise DerivationError("construction certificate set is empty")
    maximum = records[0]
    for record in records[1:]:
        if (
            record.maximum_numerator**2 * maximum.maximum_variance_product
            > maximum.maximum_numerator**2 * record.maximum_variance_product
        ):
            maximum = record
    correlation_q20 = math.isqrt(
        (maximum.maximum_numerator * maximum.maximum_numerator << 40)
        // maximum.maximum_variance_product
    )
    return LagCertificate(
        eligible_records=sum(record.eligible_records for record in records),
        maximum_numerator=maximum.maximum_numerator,
        maximum_variance_product=maximum.maximum_variance_product,
        maximum_correlation_q20=correlation_q20,
    )


def construction_receipt_json(receipt: ConstructionReceipt) -> dict[str, Any]:
    def certificate(value: LagCertificate) -> dict[str, int]:
        return {
            "eligible_records": value.eligible_records,
            "maximum_numerator": value.maximum_numerator,
            "maximum_variance_product": value.maximum_variance_product,
            "maximum_correlation_q20": value.maximum_correlation_q20,
        }

    return {
        "amplitude_matching_iterations": receipt.amplitude_matching_iterations,
        "amplitude_lag_certificate": certificate(receipt.amplitude_certificate),
        "unit_lag_certificate": certificate(receipt.unit_certificate),
        "quiet_clipped_pixels": receipt.quiet_clipped_pixels,
        "short_dark_repairs": receipt.short_dark_repairs,
        "short_dark_pixels": receipt.short_dark_pixels,
        "topology_repairs": receipt.topology_repairs,
        "topology_pixels": receipt.topology_pixels,
    }


@dataclass(frozen=True)
class PreparedBody:
    mask: np.ndarray
    statistics: Any
    bands: IndependentBands
    coarse_q16: np.ndarray
    amplitude_seed: int
    unit_seed: int


@dataclass(frozen=True)
class BoundInputSnapshot:
    """Immutable, SHA-verified bytes used throughout one emit attempt."""

    records: tuple[tuple[str, str, bytes], ...]

    def payload(self, role: str) -> bytes:
        matches = [
            payload for found_role, _, payload in self.records if found_role == role
        ]
        if len(matches) != 1:
            raise DerivationError(f"snapshot role is absent or duplicated: {role}")
        return matches[0]

    def path(self, role: str) -> str:
        matches = [path for found_role, path, _ in self.records if found_role == role]
        if len(matches) != 1:
            raise DerivationError(f"snapshot role is absent or duplicated: {role}")
        return matches[0]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _exact_json_equal(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return list(actual) == list(expected) and all(
            _exact_json_equal(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _exact_json_equal(left, right)
            for left, right in zip(actual, expected, strict=True)
        )
    return actual == expected


def canonical_json(value: Any, *, pretty: bool = False) -> bytes:
    try:
        if pretty:
            rendered = json.dumps(
                value,
                indent=2,
                ensure_ascii=True,
                allow_nan=False,
            )
        else:
            rendered = json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
    except (TypeError, ValueError) as exc:
        raise DerivationError(f"value is not canonical JSON data: {exc}") from exc
    return (rendered + "\n").encode("utf-8")


def _reject_duplicate_object_pairs(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DerivationError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_strict_json(payload: bytes, *, label: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise DerivationError(f"{label} contains forbidden constant {value!r}")

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_object_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DerivationError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise DerivationError(f"{label} must be a JSON object")
    return value


def authority_self_hash(authority: Mapping[str, Any]) -> str:
    normalized = copy.deepcopy(dict(authority))
    normalized["canonical_self_sha256"] = SELF_HASH_ZERO
    return sha256_bytes(canonical_json(normalized))


def _safe_relative(value: Any, *, label: str, output: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise DerivationError(f"{label} must be a non-empty POSIX path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise DerivationError(f"{label} must stay repository-relative")
    if output and not value.startswith("tmp/map-production/"):
        raise DerivationError(f"{label} must stay under tmp/map-production")
    return value


def _require_exact_keys(
    value: Any, expected: set[str], *, label: str
) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise DerivationError(f"{label} keys changed")
    return value


def source_bindings(authority: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    records = authority["input_policy"]["source_bindings"]
    return {record["role"]: record for record in records}


def derive_seed(body_index: int, band_id: str) -> tuple[int, str]:
    if body_index < 0 or body_index >= len(BODY_VALUES) or band_id not in BAND_IDS:
        raise DerivationError("phase seed request escaped the fixed table")
    label = f"{SEED_ROOT}:{BODY_IDS[body_index]}:{band_id}"
    digest = hashlib.sha256(label.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False), digest.hex()


def validate_authority(authority: Mapping[str, Any]) -> None:
    _require_exact_keys(
        authority,
        {
            "schema_version",
            "interface",
            "status",
            "immutable_plan",
            "canonical_self_sha256",
            "strict_audit_authority",
            "runtime",
            "input_policy",
            "derivation",
            "candidates",
            "cli_contract",
        },
        label="authority",
    )
    if (
        authority["schema_version"] != "3.0.0"
        or authority["interface"] != INTERFACE
        or authority["status"] != "preregistered-candidates-not-generated"
        or authority["immutable_plan"] is not True
    ):
        raise DerivationError("authority identity/status changed")
    self_hash = authority["canonical_self_sha256"]
    if (
        not isinstance(self_hash, str)
        or SHA256_PATTERN.fullmatch(self_hash) is None
        or self_hash == SELF_HASH_ZERO
        or authority_self_hash(authority) != self_hash
    ):
        raise DerivationError("authority canonical self-hash changed")

    strict = _require_exact_keys(
        authority["strict_audit_authority"],
        {"path", "sha256", "policy"},
        label="strict authority reference",
    )
    if (
        strict["path"]
        != "world/map-production/spec/"
        "style-candidate-k3-golden-v3-strict-audit-authority.json"
        or strict["sha256"]
        != "c27b41e6336974c5ce5fe11c86cefc67ed35851650680c33379c3510444884d7"
        or strict["policy"]
        != "unchanged independent post-seal audit; never imported or read during emit"
    ):
        raise DerivationError("strict audit authority binding changed")

    policy = _require_exact_keys(
        authority["input_policy"],
        {
            "unlisted_inputs_forbidden",
            "tracked_worktree_bytes_must_match_sha256",
            "transitive_v1_construction_closure_required_for_emit",
            "emit_reference_only_roles_excluded",
            "emit_read_snapshot",
            "candidate_generator_forbidden_reads",
            "validate_only_roles",
            "source_bindings",
        },
        label="input policy",
    )
    if (
        policy["unlisted_inputs_forbidden"] is not True
        or policy["tracked_worktree_bytes_must_match_sha256"] is not True
        or policy["transitive_v1_construction_closure_required_for_emit"] is not True
        or policy["emit_reference_only_roles_excluded"]
        != ["strict-audit-authority-reference-only"]
        or policy["emit_read_snapshot"]
        != (
            "snapshot each inherited v1 construction source, excluding the frozen "
            "reference-only role, from one read that verifies its bound SHA-256 and "
            "tracked identity; subsequent decode or import uses only those immutable bytes"
        )
        or policy["validate_only_roles"] != list(EXPECTED_BINDING_ROLES)
        or policy["candidate_generator_forbidden_reads"]
        != [
            "candidate PNGs",
            "tmp outputs",
            "rejection reports",
            "development status",
            "measurement-inside mask",
            "texture-reference mask",
            "strict audit implementation",
            "strict metric core",
        ]
    ):
        raise DerivationError("input/read closure changed")
    records = policy["source_bindings"]
    if not isinstance(records, list) or len(records) != len(TEXT_ONLY_ROLES):
        raise DerivationError("source binding count changed")
    roles: set[str] = set()
    paths: set[str] = set()
    ordered_roles: list[str] = []
    for index, raw in enumerate(records):
        record = _require_exact_keys(
            raw, {"role", "path", "sha256", "use"}, label=f"binding {index}"
        )
        role = record["role"]
        path = _safe_relative(record["path"], label=f"binding {index} path")
        digest = record["sha256"]
        if (
            not isinstance(role, str)
            or role in roles
            or path in paths
            or not isinstance(digest, str)
            or SHA256_PATTERN.fullmatch(digest) is None
            or digest == SELF_HASH_ZERO
            or not isinstance(record["use"], str)
            or not record["use"]
        ):
            raise DerivationError(f"binding {index} changed")
        roles.add(role)
        paths.add(path)
        ordered_roles.append(role)
        if EXPECTED_BINDING_PATHS.get(role) != path:
            raise DerivationError(f"binding {index} path changed")
    if roles != TEXT_ONLY_ROLES or ordered_roles != list(EXPECTED_BINDING_ROLES):
        raise DerivationError("source binding role set changed")
    bindings = source_bindings(authority)
    if (
        bindings["v1-derivation-authority"]["path"] != V1_AUTHORITY_RELATIVE
        or bindings["v1-helper-module"]["path"] != V1_HELPER_RELATIVE
        or bindings["balanced-open-phase-v3-generator"]["path"]
        != Path(__file__).resolve().relative_to(ROOT).as_posix()
    ):
        raise DerivationError("bound implementation paths changed")
    runtime = authority["runtime"]
    if (
        not isinstance(runtime, dict)
        or set(runtime)
        != {
            "common",
            "allowed_profiles",
            "profile_selection",
            "opencv_rng_seed",
        }
        or type(runtime["opencv_rng_seed"]) is not int
        or runtime["opencv_rng_seed"] != 17_720
        or not isinstance(runtime["allowed_profiles"], list)
        or len(runtime["allowed_profiles"]) != 3
        or not isinstance(runtime["common"], dict)
        or type(runtime["common"].get("opencv_threads")) is not int
        or runtime["common"].get("opencv_threads") != 1
    ):
        raise DerivationError("runtime closure changed")

    derivation = _require_exact_keys(
        authority["derivation"],
        {
            "algorithm",
            "seed_root",
            "seed_rule",
            "band_ids",
            "phase_policy",
            "filters",
            "amplitude_construction",
            "unit_whitening",
            "quiet_reserve",
            "construction_repair",
            "final_certificate",
            "fixed_gains",
            "body_8_policy",
            "finalization",
        },
        label="derivation",
    )
    if (
        derivation["algorithm"] != ALGORITHM
        or derivation["seed_root"] != SEED_ROOT
        or derivation["band_ids"] != list(BAND_IDS)
        or not _exact_json_equal(derivation["seed_rule"], EXPECTED_SEED_RULE)
        or derivation["body_8_policy"]
        != "unchanged v1 equal-body aggregate; no body-255 statistic"
    ):
        raise DerivationError("derivation identity changed")
    phase_policy = _require_exact_keys(
        derivation["phase_policy"],
        {
            "independent_surrogate_per_band",
            "rank_map_count_per_surrogate",
            "same_phase_table_for_all_candidates",
            "post_filter_remap",
            "sub2_gain",
        },
        label="phase policy",
    )
    if not _exact_json_equal(
        phase_policy,
        {
            "independent_surrogate_per_band": True,
            "rank_map_count_per_surrogate": 1,
            "same_phase_table_for_all_candidates": True,
            "post_filter_remap": False,
            "sub2_gain": [0, 1],
        },
    ):
        raise DerivationError("phase policy changed")
    filters = _require_exact_keys(
        derivation["filters"],
        {"G2", "G4_G8_G24", "construction_boxes", "masked_normalization"},
        label="filters",
    )
    g2 = _require_exact_keys(
        filters["G2"],
        {"q_bits", "radius", "coefficients", "canonical_sha256"},
        label="G2",
    )
    if not _exact_json_equal(
        g2,
        {
            "q_bits": 30,
            "radius": 8,
            "coefficients": list(G2_COEFFICIENTS),
            "canonical_sha256": G2_CANONICAL_SHA256,
        },
    ):
        raise DerivationError("G2 kernel changed")
    boxes = filters["construction_boxes"]
    if not _exact_json_equal(
        boxes,
        {
            "widths": [5, 17, 33],
            "q_bits": 30,
            "coefficient_rule": "floor(2^30/width), distribute remainder center-out symmetrically",
            "border": "half-sample-symmetric-reflect",
            "rounding": "nearest-ties-away-after-each-pass",
        },
    ):
        raise DerivationError("construction box filters changed")
    if filters["G4_G8_G24"] != (
        "literal inherited kernels from the SHA-bound v1 authority"
    ):
        raise DerivationError("inherited Gaussian filter identity changed")
    if not _exact_json_equal(
        filters["masked_normalization"],
        {
            "mask_q_bits": 20,
            "numerator_extra_q_bits": 2,
            "rounding": "nearest-ties-away-from-zero after each convolution and division",
        },
    ):
        raise DerivationError("masked Gaussian normalization changed")
    lag_contract = {
        "lags_xy": [list(pair) for pair in CONSTRUCTION_LAGS],
        "support_erosions_px": list(CONSTRUCTION_SUPPORT_EROSIONS),
        "minimum_pairs_per_record": 512,
        "minimum_eligible_lags_per_support": 4,
        "maximum_absolute_correlation_rational": [1, 128],
        "fixed_sweeps": 16,
        "regression_clip_rational": [1, 2],
        "correction_gain_rational": [12, 1],
        "renormalize_each_sweep": True,
        "sweep_parity_order": {
            "even": {
                "support_erosions": "listed order",
                "lags": "listed order and listed direction",
            },
            "odd": {
                "support_erosions": "reverse listed order",
                "lags": "reverse listed order, then negate dx and dy",
            },
        },
        "early_success_forbidden": True,
    }
    amplitude = derivation["amplitude_construction"]
    if not _exact_json_equal(
        amplitude,
        {
            "hash": "splitmix64-coordinate",
            "initial_band": "masked box17 minus masked box33",
            "field_clip_q16": [-Q16, Q16],
            "lag_decorrelation": lag_contract,
            "target_multiplier": "1 + candidate amplitude_depth_rational * certified field",
            "minimum_multiplier_rational": [4, 5],
            "maximum_multiplier_rational": [6, 5],
            "matching_filter": "inherited masked G8",
            "matching_iterations_exact": 4,
            "minimum_actual_amplitude_q16": Q16,
            "rounding": "nearest-ties-away-from-zero",
        },
    ):
        raise DerivationError("amplitude construction contract changed")
    unit_whitening = derivation["unit_whitening"]
    if not _exact_json_equal(
        unit_whitening,
        {
            "definition": "body-centered residual divided by inherited masked-G8 RMS",
            "seeded_dither": "body seed splitmix64-coordinate Q16 field divided by 64",
            "lag_decorrelation": lag_contract,
            "reconstruction": "certified unit carrier times pre-whitening G8 amplitude",
            "rounding": "nearest-ties-away-from-zero",
        },
    ):
        raise DerivationError("unit whitening contract changed")
    if not _exact_json_equal(
        derivation["quiet_reserve"],
        {
            "filter": "inherited masked G4",
            "highpass_clip_l_q16": 4 * Q16,
            "iterations_exact": 1,
            "order": "after unit reconstruction and before four amplitude matches",
            "purpose": "construction reserve only; no measurement mask or audit threshold read",
        },
    ):
        raise DerivationError("quiet reserve contract changed")
    repair = derivation["construction_repair"]
    expected_repair = {
        "short_dark": {
            "local_mean_width": 5,
            "floor_l_q16": 5 * Q16,
            "connectivity": 8,
            "area_range": [3, 128],
            "max_bbox_dimension_range": [3, 16],
            "minimum_aspect_rational": [2, 1],
            "replacement_dilation_radius": 2,
        },
        "open_topology": {
            "signal_q_bits": 12,
            "sigma_order": [4, 8],
            "polarity_order": [-1, 1],
            "body_core_erosion_px": 12,
            "floor_l_q12": 9 * Q12 // 2,
            "closing": "one 3x3 cross iteration",
            "background_connectivity": 4,
            "minimum_hole_area_pixels": 4,
            "path_connectivity": 4,
            "path_replacement_radius": 2,
            "repair_selection_order": [
                "sigma",
                "polarity",
                "hole_min_y",
                "hole_min_x",
            ],
            "path_tie_order": ["cost", "y", "x"],
            "replacement": "set body-centered residual to the active inherited Gaussian lowpass",
            "final_rgb_rounds_exact": 4,
        },
        "maximum_repairs_per_stage_per_body": 128,
        "per_stage_pixel_budget_rational": [1, 50],
        "combined_pixel_budget_rational": [3, 100],
        "failure_policy": "fail entire derivation; no resample, retry, or partial emit",
    }
    if not _exact_json_equal(repair, expected_repair):
        raise DerivationError("construction repair contract changed")
    if not _exact_json_equal(
        derivation["final_certificate"],
        {
            "source": "final in-memory RGB integer luma minus frozen foundation luma",
            "signal_q_bits": 12,
            "fields": "body-centered total; inherited masked-G8 amplitude; unit carrier",
            "repetition_field": "field minus inherited masked G4",
            "support_erosions_px": [0, 12, 24],
            "maximum_absolute_correlation_rational": [1, 128],
            "timing": "after byte locks and final RGB topology repair; before PNG encoding",
            "failure_policy": "fail all four before publication; no retry or relaxation",
        },
    ):
        raise DerivationError("final construction certificate contract changed")
    if not _exact_json_equal(
        derivation["fixed_gains"],
        {
            "g2_to_g4": [1, 1],
            "g4_to_g8": [7, 4],
            "statistical_overall": [41, 40],
            "dev20_g24": [1, 1],
            "sub2": [0, 1],
        },
    ):
        raise DerivationError("fixed gain contract changed")
    if not _exact_json_equal(
        derivation["finalization"],
        {
            "chroma": "constant v1 firewall body median a/b",
            "restore": (
                "unchanged v1 outside-foundation precedence and four v18 byte locks"
            ),
            "png": "unchanged v1-bound manual filter-0 encoder",
        },
    ):
        raise DerivationError("finalization contract changed")

    candidates = _require_exact_keys(
        authority["candidates"],
        {
            "exact_count",
            "ordering",
            "parameter_changes_forbidden",
            "extra_candidates_forbidden",
            "records",
        },
        label="candidates",
    )
    candidate_records = candidates["records"]
    if (
        type(candidates["exact_count"]) is not int
        or candidates["exact_count"] != 4
        or candidates["ordering"] != "listed order only"
        or candidates["parameter_changes_forbidden"] is not True
        or candidates["extra_candidates_forbidden"] is not True
        or not isinstance(candidate_records, list)
        or len(candidate_records) != 4
    ):
        raise DerivationError("four-candidate closure changed")
    for index, (record, expected) in enumerate(
        zip(candidate_records, EXPECTED_CANDIDATES, strict=True)
    ):
        _require_exact_keys(
            record,
            {
                "candidate_id",
                "amplitude_depth_rational",
                "sub2_gain_rational",
                "g2_to_g4_gain_rational",
                "g4_to_g8_gain_rational",
                "g8_to_g24_gain_rational",
                "statistical_overall_gain_rational",
                "dev20_g24_gain_rational",
                "output_path",
            },
            label=f"candidate {index}",
        )
        candidate_id, amplitude_depth, band824, output = expected
        if not _exact_json_equal(
            record,
            {
                "candidate_id": candidate_id,
                "amplitude_depth_rational": list(amplitude_depth),
                "sub2_gain_rational": [0, 1],
                "g2_to_g4_gain_rational": [1, 1],
                "g4_to_g8_gain_rational": [7, 4],
                "g8_to_g24_gain_rational": list(band824),
                "statistical_overall_gain_rational": [41, 40],
                "dev20_g24_gain_rational": [1, 1],
                "output_path": output,
            },
        ):
            raise DerivationError(f"candidate {index} changed")
        _safe_relative(record["output_path"], label="candidate output", output=True)

    cli = authority["cli_contract"]
    if cli != {
        "default_mode": "validate-only",
        "preflight": "hash inherited v1 emit-read closure without raster decode",
        "emit": (
            "explicit --emit only; exact four in memory; publication independently "
            "obtains the actual SHA-bound v1 runtime attestation; no evaluation"
        ),
        "compare_seals": (
            "compare canonical structured attestations for exactly the two required "
            "profiles without PNG reads"
        ),
        "required_comparison_profile_ids": list(REQUIRED_COMPARISON_PROFILES),
        "runtime_attestation_schema": {
            "exact_keys": ["profile_id", "common", "profile"],
            "common": (
                "exact actual values equal to runtime.common after the SHA-bound v1 "
                "runtime gate"
            ),
            "profile": (
                "exact actual values equal to the allowed_profiles record selected by "
                "the SHA-bound v1 runtime gate"
            ),
        },
        "output_directory": "tmp/map-production/k3-golden-v3-balanced-open-phase-v3",
        "staging_directory": "tmp/map-production/k3-golden-v3-balanced-open-phase-v3.staging",
        "seal_path": "tmp/map-production/k3-golden-v3-balanced-open-phase-v3/sealed-output-sha256.json",
        "overwrite": (
            "exclusive same-parent staging, verified complete, then atomic no-replace "
            "rename; existing staging or final directory rejected"
        ),
        "parameter_overrides": "none",
    }:
        raise DerivationError("CLI contract changed")


def load_authority(path: Path = AUTHORITY_PATH) -> dict[str, Any]:
    try:
        payload = Path(path).read_bytes()
    except OSError as exc:
        raise DerivationError(f"cannot read preregistration authority: {path}") from exc
    authority = load_strict_json(payload, label="balanced-open-phase-v3 authority")
    validate_authority(authority)
    if canonical_json(authority, pretty=True) != payload:
        raise DerivationError("authority bytes are not canonical pretty JSON")
    return authority


def check_bound_sources(
    authority: Mapping[str, Any],
    *,
    roles: set[str] | None = None,
    root: Path = ROOT,
    require_tracked: bool = True,
) -> None:
    for record in authority["input_policy"]["source_bindings"]:
        if roles is not None and record["role"] not in roles:
            continue
        _read_bound_record(record, root=Path(root), require_tracked=require_tracked)


def _read_bound_record(
    record: Mapping[str, Any],
    *,
    root: Path = ROOT,
    require_tracked: bool = True,
) -> bytes:
    relative = _safe_relative(record["path"], label=record["role"])
    path = Path(root) / relative
    if path.is_symlink() or not path.is_file():
        raise DerivationError(f"bound source is not a regular file: {relative}")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise DerivationError(f"bound source is unavailable: {relative}") from exc
    if sha256_bytes(payload) != record["sha256"]:
        raise DerivationError(f"bound source SHA-256 changed: {relative}")
    if require_tracked:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            raise DerivationError(f"bound source is not tracked: {relative}")
    return payload


def _import_module_bytes(name: str, path: Path, payload: bytes) -> ModuleType:
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    sys.modules[name] = module
    try:
        exec(compile(payload, str(path), "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def load_v1_helper(authority: Mapping[str, Any]) -> ModuleType:
    bindings = source_bindings(authority)
    helper = bindings["v1-helper-module"]
    path = ROOT / helper["path"]
    payload = _read_bound_record(helper)
    return _import_module_bytes("golden_v3_balanced_phase_v1_bound", path, payload)


def load_v1_authority(
    authority: Mapping[str, Any], v1: ModuleType
) -> Mapping[str, Any]:
    record = source_bindings(authority)["v1-derivation-authority"]
    payload = _read_bound_record(record)
    if v1.sha256_bytes(payload) != v1.AUTHORITY_SHA256:
        raise DerivationError("v1 authority frozen SHA-256 changed")
    v1_authority = v1._load_strict_json_object(
        payload, label="bound v1 preregistration authority"
    )
    v1.validate_authority(v1_authority)
    return v1_authority


def _validated_v1_context(
    authority: Mapping[str, Any],
) -> tuple[ModuleType, Mapping[str, Any]]:
    check_bound_sources(authority, roles=TEXT_ONLY_ROLES)
    v1 = load_v1_helper(authority)
    v1_authority = load_v1_authority(authority, v1)
    if not _exact_json_equal(authority["runtime"], v1.EXPECTED_RUNTIME):
        raise DerivationError("runtime differs from the SHA-bound v1 runtime")
    return v1, v1_authority


def snapshot_v1_emit_inputs(
    v1_authority: Mapping[str, Any],
    *,
    root: Path = ROOT,
    require_tracked: bool = True,
) -> BoundInputSnapshot:
    bindings = v1_authority["input_policy"]["source_bindings"]
    binding_by_role = {record["role"]: record for record in bindings}
    inherited_roles = v1_authority["input_policy"][
        "candidate_generator_read_allowlist_roles"
    ]
    if (
        not isinstance(inherited_roles, list)
        or len(inherited_roles) != len(set(inherited_roles))
        or not V1_EMIT_REFERENCE_ONLY_ROLES.issubset(inherited_roles)
    ):
        raise DerivationError("v1 emit-read allowlist is invalid")
    roles = [
        role for role in inherited_roles if role not in V1_EMIT_REFERENCE_ONLY_ROLES
    ]
    records: list[tuple[str, str, bytes]] = []
    for role in roles:
        record = binding_by_role.get(role)
        if record is None:
            raise DerivationError(f"v1 emit-read role is unbound: {role}")
        payload = _read_bound_record(
            record, root=Path(root), require_tracked=require_tracked
        )
        records.append((role, record["path"], payload))
    return BoundInputSnapshot(tuple(records))


def validate_only(authority: Mapping[str, Any]) -> None:
    _validated_v1_context(authority)


def preflight(
    authority: Mapping[str, Any],
) -> tuple[ModuleType, Mapping[str, Any], BoundInputSnapshot]:
    v1, v1_authority = _validated_v1_context(authority)
    snapshot = snapshot_v1_emit_inputs(v1_authority)
    return v1, v1_authority, snapshot


def _uniform_q30_coefficients(width: int) -> tuple[int, ...]:
    if width <= 0 or width % 2 != 1:
        raise DerivationError("construction box width must be positive and odd")
    quotient, remainder = divmod(Q30, width)
    result = [quotient] * width
    center = width // 2
    if remainder % 2:
        result[center] += 1
        remainder -= 1
    distance = 1
    while remainder:
        if center - distance < 0 or center + distance >= width:
            raise DerivationError("construction box remainder distribution failed")
        result[center - distance] += 1
        result[center + distance] += 1
        remainder -= 2
        distance += 1
    if sum(result) != Q30 or result != result[::-1]:
        raise DerivationError("construction box coefficients are invalid")
    return tuple(result)


def box_filter_q30(values: np.ndarray, width: int, v1: ModuleType) -> np.ndarray:
    return v1.q30_filter(
        np.asarray(values, dtype=np.int64),
        {"coefficients": list(_uniform_q30_coefficients(width))},
    )


def _round_divide_arrays(
    numerators: np.ndarray, denominators: np.ndarray
) -> np.ndarray:
    numerator = np.asarray(numerators, dtype=np.int64)
    denominator = np.asarray(denominators, dtype=np.int64)
    if numerator.shape != denominator.shape or np.any(denominator <= 0):
        raise DerivationError("array division shape/denominator changed")
    if np.any(numerator == INT64_MIN):
        raise DerivationError("array division cannot abs INT64_MIN")
    absolute = np.abs(numerator)
    bias = denominator // 2
    if np.any(absolute > INT64_MAX - bias):
        raise DerivationError("array division rounding bias would overflow")
    quotient = (absolute + bias) // denominator
    return np.where(numerator < 0, -quotient, quotient).astype(np.int64)


def masked_box_filter_q30(
    values: np.ndarray,
    mask: np.ndarray,
    width: int,
    v1: ModuleType,
) -> np.ndarray:
    source = np.asarray(values, dtype=np.int64)
    selected = np.asarray(mask, dtype=bool)
    if source.shape != selected.shape:
        raise DerivationError("masked construction filter shape changed")
    numerator_source = np.zeros(source.shape, dtype=np.int64)
    numerator_source[selected] = source[selected]
    numerator = box_filter_q30(numerator_source, width, v1)
    weight = box_filter_q30(selected.astype(np.int64) * Q16, width, v1)
    result = np.zeros(source.shape, dtype=np.int64)
    if np.any(weight[selected] <= 0):
        raise DerivationError("masked construction filter support collapsed")
    selected_numerator = numerator[selected]
    if np.any(selected_numerator == INT64_MIN) or (
        np.any(selected_numerator != 0)
        and np.any(np.abs(selected_numerator) > INT64_MAX // Q16)
    ):
        raise DerivationError("masked construction filter normalization overflow")
    scaled = numerator[selected] * np.int64(Q16)
    result[selected] = _round_divide_arrays(scaled, weight[selected])
    return result


def splitmix64_coordinate_field(shape: tuple[int, int], seed: int) -> np.ndarray:
    height, width = shape
    yy, xx = np.indices((height, width), dtype=np.uint64)
    with np.errstate(over="ignore"):
        state = (
            np.uint64(seed)
            ^ (yy * np.uint64(0x9E3779B97F4A7C15))
            ^ (xx * np.uint64(0xD1B54A32D192ED03))
        )
        state = state + np.uint64(0x9E3779B97F4A7C15)
        state = (state ^ (state >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        state = (state ^ (state >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        state ^= state >> np.uint64(31)
    return (((state >> np.uint64(48)).astype(np.int64) - 32_768) * 2).astype(np.int64)


def _rms_q16(values: np.ndarray, mask: np.ndarray, v1: ModuleType) -> int:
    selected = np.asarray(mask, dtype=bool)
    samples = np.asarray(values, dtype=np.int64)[selected]
    if samples.size == 0:
        raise DerivationError("construction RMS support is empty")
    if np.any(samples == INT64_MIN):
        raise DerivationError("construction RMS cannot abs INT64_MIN")
    maximum = int(np.max(np.abs(samples)))
    if maximum > math.isqrt(INT64_MAX // int(samples.size)):
        raise DerivationError("construction RMS accumulation would overflow")
    mean_square = v1.round_divide_ties_away(
        np.asarray([int(np.sum(samples * samples, dtype=np.int64))], dtype=np.int64),
        int(samples.size),
    )[0]
    return math.isqrt(max(int(mean_square), 0))


def _round_divide_scalar(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise DerivationError("construction scalar denominator must be positive")
    absolute = abs(int(numerator))
    quotient = (absolute + denominator // 2) // denominator
    return -quotient if numerator < 0 else quotient


def masked_kernel_filter_q30(
    values: np.ndarray,
    mask: np.ndarray,
    kernel: Mapping[str, Any],
    *,
    v1: ModuleType,
) -> np.ndarray:
    source = np.asarray(values, dtype=np.int64)
    selected = np.asarray(mask, dtype=bool)
    if source.shape != selected.shape or not np.any(selected):
        raise DerivationError("masked inherited filter support changed")
    numerator_source = np.zeros(source.shape, dtype=np.int64)
    if np.any(source[selected] == INT64_MIN) or (
        np.any(source[selected])
        and int(np.max(np.abs(source[selected]))) > INT64_MAX // MASKED_NUMERATOR_EXTRA
    ):
        raise DerivationError("masked inherited filter numerator would overflow")
    numerator_source[selected] = source[selected] * np.int64(MASKED_NUMERATOR_EXTRA)
    numerator = v1.q30_filter(numerator_source, kernel)
    weight = v1.q30_filter(selected.astype(np.int64) * Q20, kernel)
    if np.any(weight[selected] <= 0):
        raise DerivationError("masked inherited filter denominator collapsed")
    if np.any(numerator[selected] == INT64_MIN) or (
        np.any(numerator[selected])
        and int(np.max(np.abs(numerator[selected]))) > INT64_MAX // Q20
    ):
        raise DerivationError("masked inherited filter normalization overflow")
    scaled = numerator[selected] * np.int64(Q20)
    result = np.zeros(source.shape, dtype=np.int64)
    denominator = weight[selected] * np.int64(MASKED_NUMERATOR_EXTRA)
    result[selected] = _round_divide_arrays(scaled, denominator)
    return result


def center_q16(values: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, int]:
    source = np.asarray(values, dtype=np.int64)
    selected = np.asarray(mask, dtype=bool)
    count = int(np.count_nonzero(selected))
    if source.shape != selected.shape or count == 0:
        raise DerivationError("construction centering support changed")
    mean = _round_divide_scalar(int(np.sum(source[selected], dtype=np.int64)), count)
    result = np.zeros(source.shape, dtype=np.int64)
    result[selected] = source[selected] - mean
    return result, mean


def disk_erode(mask: np.ndarray, radius: int) -> np.ndarray:
    selected = np.asarray(mask, dtype=bool)
    if radius < 0:
        raise DerivationError("construction erosion radius changed")
    if radius == 0:
        return selected.copy()
    return (
        cv2.erode(
            selected.astype(np.uint8),
            _disk(radius),
            iterations=1,
            borderType=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        > 0
    )


def derive_amplitude_q16(
    values: np.ndarray,
    mask: np.ndarray,
    kernel_g8: Mapping[str, Any],
    *,
    v1: ModuleType,
) -> tuple[np.ndarray, np.ndarray]:
    total, _ = center_q16(values, mask)
    selected = np.asarray(mask, dtype=bool)
    maximum = int(np.max(np.abs(total[selected])))
    if maximum > math.isqrt(INT64_MAX // Q16):
        raise DerivationError("construction amplitude square would overflow")
    squared_q16 = np.zeros(total.shape, dtype=np.int64)
    squared_q16[selected] = v1.round_divide_ties_away(
        total[selected] * total[selected], Q16
    )
    mean_square = masked_kernel_filter_q30(squared_q16, selected, kernel_g8, v1=v1)
    amplitude = np.zeros(total.shape, dtype=np.int64)
    amplitude[selected] = np.fromiter(
        (math.isqrt(max(int(value), 0) * Q16) for value in mean_square[selected]),
        dtype=np.int64,
        count=int(np.count_nonzero(selected)),
    )
    return total, amplitude


def derive_unit_q16(
    values: np.ndarray,
    mask: np.ndarray,
    kernel_g8: Mapping[str, Any],
    *,
    v1: ModuleType,
) -> tuple[np.ndarray, np.ndarray]:
    total, amplitude = derive_amplitude_q16(values, mask, kernel_g8, v1=v1)
    selected = np.asarray(mask, dtype=bool)
    denominator = np.maximum(amplitude[selected], Q16)
    unit = np.zeros(total.shape, dtype=np.int64)
    unit[selected] = _round_divide_arrays(total[selected] * np.int64(Q16), denominator)
    unit, _ = center_q16(unit, selected)
    rms = _rms_q16(unit, selected, v1)
    if rms <= 0:
        raise DerivationError("construction unit RMS collapsed")
    unit[selected] = _round_divide_arrays(
        unit[selected] * np.int64(Q16),
        np.full(int(np.count_nonzero(selected)), rms, dtype=np.int64),
    )
    return unit, amplitude


def _shift_slices(
    shape: tuple[int, int], dx: int, dy: int
) -> tuple[tuple[slice, slice], tuple[slice, slice]]:
    height, width = shape
    if abs(dx) >= width or abs(dy) >= height or (dx == 0 and dy == 0):
        raise DerivationError("construction lag escaped the field")
    return (
        (
            slice(max(0, dy), min(height, height + dy)),
            slice(max(0, dx), min(width, width + dx)),
        ),
        (
            slice(max(0, -dy), min(height, height - dy)),
            slice(max(0, -dx), min(width, width - dx)),
        ),
    )


def _pearson_components(
    field: np.ndarray,
    support: np.ndarray,
    dx: int,
    dy: int,
    *,
    minimum_pairs: int,
) -> tuple[int, int, int, tuple[slice, slice], np.ndarray] | None:
    left_slice, right_slice = _shift_slices(field.shape, dx, dy)
    pair = (
        np.asarray(support, dtype=bool)[left_slice]
        & np.asarray(support, dtype=bool)[right_slice]
    )
    count = int(np.count_nonzero(pair))
    if count < minimum_pairs:
        return None
    left = np.asarray(field, dtype=np.int64)[left_slice][pair]
    right = np.asarray(field, dtype=np.int64)[right_slice][pair]
    if np.any(left == INT64_MIN) or np.any(right == INT64_MIN):
        raise DerivationError("construction correlation cannot abs INT64_MIN")
    maximum_left = int(np.max(np.abs(left)))
    maximum_right = int(np.max(np.abs(right)))
    if (
        maximum_left > math.isqrt(INT64_MAX // count)
        or maximum_right > math.isqrt(INT64_MAX // count)
        or (maximum_left and maximum_right > INT64_MAX // count // maximum_left)
    ):
        raise DerivationError("construction correlation accumulation would overflow")
    sum_left = int(np.sum(left, dtype=np.int64))
    sum_right = int(np.sum(right, dtype=np.int64))
    covariance = (
        count * int(np.sum(left * right, dtype=np.int64)) - sum_left * sum_right
    )
    variance_left = (
        count * int(np.sum(left * left, dtype=np.int64)) - sum_left * sum_left
    )
    variance_right = (
        count * int(np.sum(right * right, dtype=np.int64)) - sum_right * sum_right
    )
    if variance_left <= 0 or variance_right <= 0:
        return None
    return covariance, variance_left, variance_right, left_slice, pair


def lag_certificate(
    values: np.ndarray,
    mask: np.ndarray,
    kernel_g4: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    v1: ModuleType,
) -> LagCertificate:
    selected = np.asarray(mask, dtype=bool)
    centered, _ = center_q16(values, selected)
    metric = v1._checked_subtract_int64(
        centered,
        masked_kernel_filter_q30(centered, selected, kernel_g4, v1=v1),
        label="construction lag field minus inherited G4",
    )
    eligible = 0
    maximum_numerator = 0
    maximum_variance_product = 1
    minimum_per_support = int(config["minimum_eligible_lags_per_support"])
    for erosion in config["support_erosions_px"]:
        support = disk_erode(selected, int(erosion))
        support_eligible = 0
        for dx, dy in config["lags_xy"]:
            record = _pearson_components(
                metric,
                support,
                int(dx),
                int(dy),
                minimum_pairs=int(config["minimum_pairs_per_record"]),
            )
            if record is None:
                continue
            covariance, variance_left, variance_right, _, _ = record
            numerator = abs(covariance)
            variance_product = variance_left * variance_right
            eligible += 1
            support_eligible += 1
            if (
                numerator**2 * maximum_variance_product
                > maximum_numerator**2 * variance_product
            ):
                maximum_numerator = numerator
                maximum_variance_product = variance_product
        if support_eligible < minimum_per_support:
            raise DerivationError(
                "construction lag certificate has too few lags for a support"
            )
    limit_numerator, limit_denominator = (
        int(value) for value in config["maximum_absolute_correlation_rational"]
    )
    if (
        maximum_numerator**2 * limit_denominator**2
        > maximum_variance_product * limit_numerator**2
    ):
        raise DerivationError("construction lag decorrelation certificate exceeded")
    correlation_q20 = math.isqrt(
        (maximum_numerator * maximum_numerator << 40) // maximum_variance_product
    )
    return LagCertificate(
        eligible_records=eligible,
        maximum_numerator=maximum_numerator,
        maximum_variance_product=maximum_variance_product,
        maximum_correlation_q20=correlation_q20,
    )


def whiten_lagged_field(
    values: np.ndarray,
    mask: np.ndarray,
    kernel_g4: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    v1: ModuleType,
    clip_q16: tuple[int, int] | None = None,
) -> tuple[np.ndarray, LagCertificate]:
    selected = np.asarray(mask, dtype=bool)
    result, _ = center_q16(values, selected)
    rms = _rms_q16(result, selected, v1)
    if rms <= 0:
        raise DerivationError("construction lag-whitening input collapsed")
    result[selected] = _round_divide_arrays(
        result[selected] * np.int64(Q16),
        np.full(int(np.count_nonzero(selected)), rms, dtype=np.int64),
    )
    clip_numerator, clip_denominator = (
        int(value) for value in config["regression_clip_rational"]
    )
    gain_numerator, gain_denominator = (
        int(value) for value in config["correction_gain_rational"]
    )
    if gain_numerator <= 0 or gain_denominator <= 0:
        raise DerivationError("construction whitening correction gain changed")
    for sweep in range(int(config["fixed_sweeps"])):
        low = masked_kernel_filter_q30(result, selected, kernel_g4, v1=v1)
        metric = v1._checked_subtract_int64(
            result, low, label="construction whitening highpass"
        )
        accumulated = np.zeros(result.shape, dtype=np.int64)
        counts = np.zeros(result.shape, dtype=np.int64)
        erosions = list(config["support_erosions_px"])
        lags = [tuple(int(value) for value in pair) for pair in config["lags_xy"]]
        if sweep % 2:
            erosions.reverse()
            lags = [(-dx, -dy) for dx, dy in reversed(lags)]
        for erosion in erosions:
            support = disk_erode(selected, int(erosion))
            for dx, dy in lags:
                record = _pearson_components(
                    metric,
                    support,
                    int(dx),
                    int(dy),
                    minimum_pairs=int(config["minimum_pairs_per_record"]),
                )
                if record is None:
                    continue
                covariance, _, variance_right, left_slice, pair = record
                beta_q16 = _round_divide_scalar(covariance * Q16, variance_right)
                limit_q16 = _round_divide_scalar(clip_numerator * Q16, clip_denominator)
                beta_q16 = max(-limit_q16, min(limit_q16, beta_q16))
                if beta_q16 == 0:
                    continue
                _, right_slice = _shift_slices(metric.shape, int(dx), int(dy))
                right = metric[right_slice][pair]
                correction = _round_divide_arrays(
                    right * np.int64(beta_q16),
                    np.full(len(right), Q16, dtype=np.int64),
                )
                local_accumulated = accumulated[left_slice]
                local_counts = counts[left_slice]
                local_accumulated[pair] += correction
                local_counts[pair] += 1
        changed = counts > 0
        if np.any(changed):
            averaged = _round_divide_arrays(accumulated[changed], counts[changed])
            if np.any(averaged == INT64_MIN) or (
                np.any(averaged)
                and int(np.max(np.abs(averaged))) > INT64_MAX // gain_numerator
            ):
                raise DerivationError("construction whitening gain would overflow")
            correction = _round_divide_arrays(
                averaged * np.int64(gain_numerator),
                np.full(len(averaged), gain_denominator, dtype=np.int64),
            )
            result[changed] = v1._checked_subtract_int64(
                result[changed], correction, label="snapshot lag regression correction"
            )
        result, _ = center_q16(result, selected)
        if config["renormalize_each_sweep"]:
            rms = _rms_q16(result, selected, v1)
            if rms <= 0:
                raise DerivationError("construction whitening sweep RMS collapsed")
            result[selected] = _round_divide_arrays(
                result[selected] * np.int64(Q16),
                np.full(int(np.count_nonzero(selected)), rms, dtype=np.int64),
            )
        if clip_q16 is not None:
            result[selected] = np.clip(result[selected], *clip_q16)
    return result, lag_certificate(result, selected, kernel_g4, config, v1=v1)


def construct_target_amplitude(
    values: np.ndarray,
    mask: np.ndarray,
    seed: int,
    depth: Sequence[int],
    kernel_g4: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    v1: ModuleType,
) -> tuple[np.ndarray, LagCertificate]:
    selected = np.asarray(mask, dtype=bool)
    raw = splitmix64_coordinate_field(selected.shape, seed)
    band = masked_box_filter_q30(raw, selected, 17, v1) - masked_box_filter_q30(
        raw, selected, 33, v1
    )
    band[~selected] = 0
    certified, certificate = whiten_lagged_field(
        band,
        selected,
        kernel_g4,
        config["lag_decorrelation"],
        v1=v1,
        clip_q16=(-Q16, Q16),
    )
    certified[selected] = np.clip(certified[selected], -Q16, Q16)
    base_rms = _rms_q16(values, selected, v1)
    modulation = v1.rational_multiply(certified, int(depth[0]), int(depth[1]))
    multiplier = np.clip(Q16 + modulation, 4 * Q16 // 5, 6 * Q16 // 5)
    target = np.zeros(values.shape, dtype=np.int64)
    target[selected] = _round_divide_arrays(
        np.full(int(np.count_nonzero(selected)), base_rms, dtype=np.int64)
        * multiplier[selected],
        np.full(int(np.count_nonzero(selected)), Q16, dtype=np.int64),
    )
    return target, certificate


def whiten_unit_carrier(
    values: np.ndarray,
    mask: np.ndarray,
    seed: int,
    kernel_g4: Mapping[str, Any],
    kernel_g8: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    v1: ModuleType,
) -> tuple[np.ndarray, LagCertificate]:
    selected = np.asarray(mask, dtype=bool)
    unit, amplitude = derive_unit_q16(values, selected, kernel_g8, v1=v1)
    dither = splitmix64_coordinate_field(selected.shape, seed)
    unit[selected] += v1.round_divide_ties_away(dither[selected], 64)
    certified, certificate = whiten_lagged_field(
        unit,
        selected,
        kernel_g4,
        config["lag_decorrelation"],
        v1=v1,
    )
    result = np.zeros(values.shape, dtype=np.int64)
    result[selected] = _round_divide_arrays(
        certified[selected] * amplitude[selected],
        np.full(int(np.count_nonzero(selected)), Q16, dtype=np.int64),
    )
    result, _ = center_q16(result, selected)
    return result, certificate


def apply_quiet_reserve(
    values: np.ndarray,
    mask: np.ndarray,
    kernel_g4: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    v1: ModuleType,
) -> tuple[np.ndarray, int]:
    selected = np.asarray(mask, dtype=bool)
    centered, mean = center_q16(values, selected)
    low = masked_kernel_filter_q30(centered, selected, kernel_g4, v1=v1)
    high = v1._checked_subtract_int64(centered, low, label="quiet reserve G4 highpass")
    cap = int(config["highpass_clip_l_q16"])
    clipped = np.clip(high, -cap, cap)
    result = np.zeros(values.shape, dtype=np.int64)
    result[selected] = low[selected] + clipped[selected] + mean
    return result, int(np.count_nonzero((high != clipped) & selected))


def match_target_amplitude(
    values: np.ndarray,
    target: np.ndarray,
    mask: np.ndarray,
    kernel_g8: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    v1: ModuleType,
) -> np.ndarray:
    selected = np.asarray(mask, dtype=bool)
    result = np.asarray(values, dtype=np.int64).copy()
    iterations = int(config["matching_iterations_exact"])
    if iterations != 4:
        raise DerivationError("amplitude matching iteration count changed")
    for _ in range(iterations):
        centered, amplitude = derive_amplitude_q16(result, selected, kernel_g8, v1=v1)
        denominator = np.maximum(
            amplitude[selected], int(config["minimum_actual_amplitude_q16"])
        )
        centered[selected] = _round_divide_arrays(
            centered[selected] * target[selected], denominator
        )
        result = centered
    return result


def _disk(radius: int) -> np.ndarray:
    coordinates = np.arange(-radius, radius + 1, dtype=np.int32)
    yy, xx = np.meshgrid(coordinates, coordinates, indexing="ij")
    return ((xx * xx + yy * yy) <= radius * radius).astype(np.uint8)


def _budget_pixels(total: int, rational: Sequence[int]) -> int:
    numerator, denominator = (int(value) for value in rational)
    if numerator < 0 or denominator <= 0:
        raise DerivationError("repair budget rational changed")
    return max(1, total * numerator // denominator)


def repair_short_dark_components(
    values: np.ndarray,
    mask: np.ndarray,
    config: Mapping[str, Any],
    *,
    maximum_repairs: int,
    pixel_budget: int,
    v1: ModuleType,
    mutable: np.ndarray | None = None,
) -> tuple[np.ndarray, int, np.ndarray]:
    result = np.asarray(values, dtype=np.int64).copy()
    selected = np.asarray(mask, dtype=bool)
    modifiable = selected if mutable is None else np.asarray(mutable, dtype=bool)
    if modifiable.shape != selected.shape or np.any(modifiable & ~selected):
        raise DerivationError("short-dark mutable support changed")
    touched = np.zeros(selected.shape, dtype=bool)
    repairs = 0
    while True:
        local = masked_box_filter_q30(
            result, selected, int(config["local_mean_width"]), v1
        )
        contrast = v1._checked_subtract_int64(
            local, result, label="short-dark local mean minus residual"
        )
        dark = (contrast >= int(config["floor_l_q16"])) & selected
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            dark.astype(np.uint8),
            connectivity=int(config["connectivity"]),
            ltype=cv2.CV_32S,
        )
        candidates: list[tuple[int, int, int]] = []
        for component in range(1, count):
            area = int(stats[component, cv2.CC_STAT_AREA])
            width = int(stats[component, cv2.CC_STAT_WIDTH])
            height = int(stats[component, cv2.CC_STAT_HEIGHT])
            maximum_dimension = max(width, height)
            minimum_dimension = max(1, min(width, height))
            if (
                int(config["area_range"][0]) <= area <= int(config["area_range"][1])
                and int(config["max_bbox_dimension_range"][0])
                <= maximum_dimension
                <= int(config["max_bbox_dimension_range"][1])
                and maximum_dimension * int(config["minimum_aspect_rational"][1])
                >= minimum_dimension * int(config["minimum_aspect_rational"][0])
            ):
                ys, xs = np.nonzero(labels == component)
                candidates.append((int(ys.min()), int(xs.min()), component))
        if not candidates:
            return result, repairs, touched
        if repairs >= maximum_repairs:
            raise DerivationError("short-dark construction repair did not converge")
        _, _, component = min(candidates)
        region = labels == component
        radius = int(config["replacement_dilation_radius"])
        replacement = cv2.dilate(region.astype(np.uint8), _disk(radius)) > 0
        replacement &= selected & modifiable
        if not np.any(replacement):
            raise DerivationError("short-dark component is fully locked")
        proposed = touched | replacement
        if int(np.count_nonzero(proposed)) > pixel_budget:
            raise DerivationError(
                "short-dark construction repair exceeded pixel budget"
            )
        result[replacement] = local[replacement]
        touched = proposed
        repairs += 1


def _body_boundary(mask: np.ndarray) -> np.ndarray:
    selected = np.asarray(mask, dtype=bool)
    cross = np.asarray([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)
    eroded = (
        cv2.erode(
            selected.astype(np.uint8),
            cross,
            iterations=1,
            borderType=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        > 0
    )
    return selected & ~eroded


def _cross_close(excursion: np.ndarray) -> np.ndarray:
    cross = np.asarray([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)
    return (
        cv2.morphologyEx(
            np.asarray(excursion, dtype=np.uint8),
            cv2.MORPH_CLOSE,
            cross,
            iterations=1,
        )
        > 0
    )


def _first_enclosed_background(
    excursion: np.ndarray,
    mask: np.ndarray,
    connectivity: int,
    *,
    close_cross: bool = False,
    minimum_area: int = 1,
) -> np.ndarray | None:
    selected = np.asarray(mask, dtype=bool)
    visible = np.asarray(excursion, dtype=bool) & selected
    if close_cross:
        visible = _cross_close(visible)
    background = selected & ~visible
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        background.astype(np.uint8), connectivity=connectivity, ltype=cv2.CV_32S
    )
    boundary = _body_boundary(selected)
    candidates: list[tuple[int, int, int]] = []
    for component in range(1, count):
        component_mask = labels == component
        if int(stats[component, cv2.CC_STAT_AREA]) < minimum_area or np.any(
            component_mask & boundary
        ):
            continue
        ys, xs = np.nonzero(component_mask)
        if len(xs):
            candidates.append((int(ys.min()), int(xs.min()), component))
    if not candidates:
        return None
    return labels == min(candidates)[2]


def _minimum_cost_path_to_boundary(
    hole: np.ndarray,
    mask: np.ndarray,
    contrast: np.ndarray,
    signal_scale: int,
    forbidden: np.ndarray | None = None,
) -> list[tuple[int, int]]:
    selected = np.asarray(mask, dtype=bool)
    excluded = (
        np.zeros(selected.shape, dtype=bool)
        if forbidden is None
        else np.asarray(forbidden, dtype=bool)
    )
    if excluded.shape != selected.shape or np.any(excluded & ~selected):
        raise DerivationError("open-topology forbidden support changed")
    boundary = _body_boundary(selected)
    height, width = selected.shape
    distance = np.full((height, width), INT64_MAX, dtype=np.int64)
    predecessor_y = np.full((height, width), -1, dtype=np.int32)
    predecessor_x = np.full((height, width), -1, dtype=np.int32)
    queue: list[tuple[int, int, int]] = []
    ys, xs = np.nonzero(hole)
    for y, x in sorted(zip(ys.tolist(), xs.tolist(), strict=True)):
        distance[y, x] = 0
        heapq.heappush(queue, (0, y, x))
    target: tuple[int, int] | None = None
    contrast_values = np.asarray(contrast, dtype=np.int64)
    if np.any(contrast_values[selected] == INT64_MIN):
        raise DerivationError("open-topology path cannot abs INT64_MIN")
    if signal_scale <= 0:
        raise DerivationError("open-topology signal scale changed")
    for_cost = np.abs(contrast_values) // signal_scale + 1
    while queue:
        cost, y, x = heapq.heappop(queue)
        if cost != int(distance[y, x]):
            continue
        if boundary[y, x] and not hole[y, x]:
            target = (y, x)
            break
        for dy, dx in ((-1, 0), (0, -1), (0, 1), (1, 0)):
            ny, nx = y + dy, x + dx
            if not (
                0 <= ny < height
                and 0 <= nx < width
                and selected[ny, nx]
                and not excluded[ny, nx]
            ):
                continue
            step_cost = int(for_cost[ny, nx])
            if cost > INT64_MAX - step_cost:
                raise DerivationError("open-topology path cost would overflow")
            new_cost = cost + step_cost
            old_parent = (
                int(predecessor_y[ny, nx]),
                int(predecessor_x[ny, nx]),
            )
            if new_cost < int(distance[ny, nx]) or (
                new_cost == int(distance[ny, nx])
                and (old_parent[0] < 0 or (y, x) < old_parent)
            ):
                distance[ny, nx] = new_cost
                predecessor_y[ny, nx] = y
                predecessor_x[ny, nx] = x
                heapq.heappush(queue, (new_cost, ny, nx))
    if target is None:
        raise DerivationError("open-topology path cannot reach body boundary")
    path: list[tuple[int, int]] = []
    y, x = target
    while True:
        path.append((y, x))
        py, px = int(predecessor_y[y, x]), int(predecessor_x[y, x])
        if py < 0 or px < 0:
            break
        y, x = py, px
    return path


def repair_open_topology(
    values: np.ndarray,
    mask: np.ndarray,
    config: Mapping[str, Any],
    kernels: Mapping[str, Mapping[str, Any]],
    *,
    maximum_repairs: int,
    pixel_budget: int,
    v1: ModuleType,
    mutable: np.ndarray | None = None,
) -> tuple[np.ndarray, int, np.ndarray]:
    result = np.asarray(values, dtype=np.int64).copy()
    selected = np.asarray(mask, dtype=bool)
    modifiable = selected if mutable is None else np.asarray(mutable, dtype=bool)
    if modifiable.shape != selected.shape or np.any(modifiable & ~selected):
        raise DerivationError("open-topology mutable support changed")
    touched = np.zeros(selected.shape, dtype=bool)
    repairs = 0
    while True:
        centered, body_mean = center_q16(result, selected)
        core = disk_erode(selected, int(config["body_core_erosion_px"]))
        if not np.any(core):
            raise DerivationError("open-topology body core collapsed")
        chosen: tuple[np.ndarray, np.ndarray, int, int, np.ndarray] | None = None
        if int(config["signal_q_bits"]) != 12:
            raise DerivationError("open-topology signal fixed point changed")
        floor = int(config["floor_l_q12"])
        for sigma in config["sigma_order"]:
            low = masked_kernel_filter_q30(
                centered, selected, kernels[f"G{int(sigma)}"], v1=v1
            )
            contrast = v1._checked_subtract_int64(
                centered, low, label="open-topology inherited-Gaussian detail"
            )
            for polarity in config["polarity_order"]:
                excursion = (int(polarity) * contrast >= floor) & core
                closed_excursion = _cross_close(excursion) & core
                selected_hole = _first_enclosed_background(
                    closed_excursion,
                    core,
                    int(config["background_connectivity"]),
                    close_cross=False,
                    minimum_area=int(config["minimum_hole_area_pixels"]),
                )
                if selected_hole is not None:
                    chosen = (
                        selected_hole,
                        low,
                        int(sigma),
                        int(polarity),
                        closed_excursion,
                    )
                    break
            if chosen is not None:
                break
        if chosen is None:
            return result, repairs, touched
        if repairs >= maximum_repairs:
            raise DerivationError("open-topology construction repair did not converge")
        selected_hole, low, _, _, closed_excursion = chosen
        path = _minimum_cost_path_to_boundary(
            selected_hole,
            core,
            contrast,
            1 << int(config["signal_q_bits"]),
            forbidden=closed_excursion & ~modifiable,
        )
        path_mask = np.zeros(selected.shape, dtype=np.uint8)
        for y, x in path:
            path_mask[y, x] = 1
        replacement = (
            cv2.dilate(path_mask, _disk(int(config["path_replacement_radius"]))) > 0
        )
        replacement &= core & modifiable
        if not np.any(replacement):
            raise DerivationError("open-topology path is fully locked")
        proposed = touched | replacement
        if int(np.count_nonzero(proposed)) > pixel_budget:
            raise DerivationError(
                "open-topology construction repair exceeded pixel budget"
            )
        result[replacement] = low[replacement] + body_mean
        touched = proposed
        repairs += 1


def construction_luma_u8(rgb: np.ndarray) -> np.ndarray:
    source = np.asarray(rgb, dtype=np.uint8).astype(np.int64)
    if source.ndim != 3 or source.shape[2] != 3:
        raise DerivationError("construction luma expects RGB")
    return (
        (
            19_595 * source[..., 0]
            + 38_470 * source[..., 1]
            + 7_471 * source[..., 2]
            + 32_768
        )
        >> 16
    ).astype(np.int16)


def derive_final_fields_q12(
    delta_luma: np.ndarray,
    mask: np.ndarray,
    kernel_g8: Mapping[str, Any],
    *,
    v1: ModuleType,
) -> FinalFields:
    selected = np.asarray(mask, dtype=bool)
    delta = np.asarray(delta_luma, dtype=np.int64)
    if delta.shape != selected.shape or not np.any(selected):
        raise DerivationError("final construction field support changed")
    total = np.zeros(delta.shape, dtype=np.int64)
    total[selected] = delta[selected] * np.int64(Q12)
    total, _ = center_q16(total, selected)
    if np.any(total[selected] == INT64_MIN):
        raise DerivationError("final construction total cannot abs INT64_MIN")
    maximum = int(np.max(np.abs(total[selected])))
    if maximum > math.isqrt(INT64_MAX):
        raise DerivationError("final construction amplitude square would overflow")
    squared_q12 = np.zeros(total.shape, dtype=np.int64)
    squared_q12[selected] = v1.round_divide_ties_away(
        total[selected] * total[selected], Q12
    )
    amplitude_square = masked_kernel_filter_q30(squared_q12, selected, kernel_g8, v1=v1)
    if np.any(amplitude_square[selected] > INT64_MAX // Q12):
        raise DerivationError("final construction amplitude sqrt would overflow")
    amplitude = np.zeros(total.shape, dtype=np.int64)
    amplitude[selected] = np.fromiter(
        (math.isqrt(max(int(value), 0) * Q12) for value in amplitude_square[selected]),
        dtype=np.int64,
        count=int(np.count_nonzero(selected)),
    )
    amplitude_centered, _ = center_q16(amplitude, selected)
    denominator = np.maximum(amplitude[selected], Q12)
    if np.any(np.abs(total[selected]) > INT64_MAX // Q12):
        raise DerivationError("final construction unit division would overflow")
    unit = np.zeros(total.shape, dtype=np.int64)
    unit[selected] = _round_divide_arrays(total[selected] * np.int64(Q12), denominator)
    unit, _ = center_q16(unit, selected)
    rms = _rms_q16(unit, selected, v1)
    if rms <= 0:
        raise DerivationError("final construction unit RMS collapsed")
    if np.any(np.abs(unit[selected]) > INT64_MAX // Q12):
        raise DerivationError("final construction unit normalization would overflow")
    unit[selected] = _round_divide_arrays(
        unit[selected] * np.int64(Q12),
        np.full(int(np.count_nonzero(selected)), rms, dtype=np.int64),
    )
    return FinalFields(
        total_q12=total,
        amplitude_q12=amplitude_centered,
        unit_q12=unit,
    )


def topology_hole_count(
    values: np.ndarray,
    mask: np.ndarray,
    config: Mapping[str, Any],
    kernels: Mapping[str, Mapping[str, Any]],
    *,
    v1: ModuleType,
) -> int:
    selected = np.asarray(mask, dtype=bool)
    centered, _ = center_q16(values, selected)
    core = disk_erode(selected, int(config["body_core_erosion_px"]))
    if int(config["signal_q_bits"]) != 12:
        raise DerivationError("topology certificate signal fixed point changed")
    floor = int(config["floor_l_q12"])
    holes = 0
    for sigma in config["sigma_order"]:
        low = masked_kernel_filter_q30(
            centered, selected, kernels[f"G{int(sigma)}"], v1=v1
        )
        detail = v1._checked_subtract_int64(
            centered, low, label="topology certificate inherited-Gaussian detail"
        )
        for polarity in config["polarity_order"]:
            visible = (int(polarity) * detail >= floor) & core
            while True:
                hole = _first_enclosed_background(
                    visible,
                    core,
                    int(config["background_connectivity"]),
                    close_cross=True,
                    minimum_area=int(config["minimum_hole_area_pixels"]),
                )
                if hole is None:
                    break
                holes += 1
                visible[hole] = True
    return holes


def repair_final_rgb_topology(
    candidate: np.ndarray,
    foundation: np.ndarray,
    bodies: Sequence[np.ndarray],
    mutable: np.ndarray,
    prior_touched: Sequence[np.ndarray],
    config: Mapping[str, Any],
    kernels: Mapping[str, Mapping[str, Any]],
    *,
    v1: ModuleType,
) -> tuple[np.ndarray, int, int]:
    result = np.asarray(candidate, dtype=np.uint8).copy()
    reference_luma = construction_luma_u8(foundation)
    modifiable = np.asarray(mutable, dtype=bool)
    repairs = 0
    touched_union = np.zeros(reference_luma.shape, dtype=bool)
    topology_touched = [np.zeros(reference_luma.shape, dtype=bool) for _ in bodies]
    repairs_per_body = [0 for _ in bodies]
    if len(prior_touched) != len(bodies) or any(
        np.asarray(touched).shape != reference_luma.shape for touched in prior_touched
    ):
        raise DerivationError("final topology prior-repair support changed")
    maximum = int(config["maximum_repairs_per_stage_per_body"])
    for _ in range(int(config["open_topology"]["final_rgb_rounds_exact"])):
        for body_index, body in enumerate(bodies):
            selected = np.asarray(body, dtype=bool)
            delta = (
                construction_luma_u8(result).astype(np.int64)
                - reference_luma.astype(np.int64)
            ) * Q12
            budget = _budget_pixels(
                int(np.count_nonzero(selected)),
                config["per_stage_pixel_budget_rational"],
            )
            repaired, count, touched = repair_open_topology(
                delta,
                selected,
                config["open_topology"],
                kernels,
                maximum_repairs=maximum - repairs_per_body[body_index],
                pixel_budget=budget,
                v1=v1,
                mutable=modifiable & selected,
            )
            repairs += count
            repairs_per_body[body_index] += count
            topology_touched[body_index] |= touched
            touched_union |= touched
            target_delta = np.zeros(delta.shape, dtype=np.int64)
            target_delta[selected] = np.fromiter(
                (_round_divide_scalar(int(value), Q12) for value in repaired[selected]),
                dtype=np.int64,
                count=int(np.count_nonzero(selected)),
            )
            current_delta = construction_luma_u8(result).astype(
                np.int64
            ) - reference_luma.astype(np.int64)
            shift = target_delta - current_delta
            apply = touched & modifiable
            if np.any(apply):
                updated = result.astype(np.int64)
                updated[apply] += shift[apply][:, None]
                if np.any(updated[apply] < 0) or np.any(updated[apply] > 255):
                    raise DerivationError("final-luma topology repair would clip RGB")
                result[apply] = updated[apply].astype(np.uint8)
            per_stage_budget = _budget_pixels(
                int(np.count_nonzero(selected)),
                config["per_stage_pixel_budget_rational"],
            )
            if int(np.count_nonzero(topology_touched[body_index])) > per_stage_budget:
                raise DerivationError(
                    "final RGB topology repair exceeded per-stage pixel budget"
                )
    final_delta = (
        construction_luma_u8(result).astype(np.int64) - reference_luma.astype(np.int64)
    ) * Q12
    for body in bodies:
        if topology_hole_count(
            final_delta,
            body,
            config["open_topology"],
            kernels,
            v1=v1,
        ):
            raise DerivationError("final RGB topology repair did not converge")
    for body_index, body in enumerate(bodies):
        selected = np.asarray(body, dtype=bool)
        previous = np.asarray(prior_touched[body_index], dtype=bool)
        if np.any(previous & ~selected):
            raise DerivationError("prior construction repair escaped its body")
        combined_budget = _budget_pixels(
            int(np.count_nonzero(selected)), config["combined_pixel_budget_rational"]
        )
        if (
            int(np.count_nonzero(previous | topology_touched[body_index]))
            > combined_budget
        ):
            raise DerivationError("combined construction repair exceeded pixel budget")
    touched_count = int(np.count_nonzero(touched_union))
    return result, repairs, touched_count


def synthesize_independent_bands(
    shape: tuple[int, int],
    body: np.ndarray,
    statistics: Any,
    body_index: int,
    kernels: Mapping[str, Mapping[str, Any]],
    *,
    v1: ModuleType,
) -> IndependentBands:
    selected = np.asarray(body, dtype=bool)

    def surrogate_for(band_id: str) -> np.ndarray:
        seed, _ = derive_seed(body_index, band_id)
        return v1.synthesize_statistical_phase(shape, selected, statistics, seed)

    x24 = surrogate_for("g2-g4")
    x48 = surrogate_for("g4-g8")
    x824 = surrogate_for("g8-g24")
    g2_x24 = v1.q30_filter(x24, kernels["G2"])
    g4_x24 = v1.q30_filter(x24, kernels["G4"])
    g4_x48 = v1.q30_filter(x48, kernels["G4"])
    g8_x48 = v1.q30_filter(x48, kernels["G8"])
    g8_x824 = v1.q30_filter(x824, kernels["G8"])
    g24_x824 = v1.q30_filter(x824, kernels["G24"])
    return IndependentBands(
        g2_to_g4=v1._checked_subtract_int64(g2_x24, g4_x24, label="G2X24 minus G4X24"),
        g4_to_g8=v1._checked_subtract_int64(g4_x48, g8_x48, label="G4X48 minus G8X48"),
        g8_to_g24=v1._checked_subtract_int64(
            g8_x824, g24_x824, label="G8X824 minus G24X824"
        ),
    )


def compose_statistical_field(
    bands: IndependentBands,
    record: Mapping[str, Any],
    *,
    v1: ModuleType,
) -> np.ndarray:
    if record["sub2_gain_rational"] != [0, 1]:
        raise DerivationError("sub2 construction path must remain absent")
    result = v1.rational_multiply(bands.g2_to_g4, *record["g2_to_g4_gain_rational"])
    result = v1._checked_add_int64(
        result,
        v1.rational_multiply(bands.g4_to_g8, *record["g4_to_g8_gain_rational"]),
        label="plus independent G4-to-G8 band",
    )
    result = v1._checked_add_int64(
        result,
        v1.rational_multiply(bands.g8_to_g24, *record["g8_to_g24_gain_rational"]),
        label="plus independent G8-to-G24 band",
    )
    return result


def _decode_snapshot_image(
    snapshot: BoundInputSnapshot,
    role: str,
    *,
    mode: str,
    shape: tuple[int, int] | None = None,
    binary: bool = False,
) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(snapshot.payload(role))) as image:
            if image.mode != mode:
                raise DerivationError(f"snapshot image mode changed: {role}")
            if shape is not None and image.size != (shape[1], shape[0]):
                raise DerivationError(f"snapshot image dimensions changed: {role}")
            values = np.asarray(image, dtype=np.uint8).copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise DerivationError(f"cannot decode snapshotted input: {role}") from exc
    if binary:
        if set(int(value) for value in np.unique(values)) != {0, 255}:
            raise DerivationError(f"snapshotted mask is not binary: {role}")
        return values == 255
    return values


def _prepare_bodies(
    authority: Mapping[str, Any],
    v1: ModuleType,
    v1_authority: Mapping[str, Any],
    snapshot: BoundInputSnapshot,
) -> tuple[
    list[PreparedBody],
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    list[np.ndarray],
    ModuleType,
    dict[str, Mapping[str, Any]],
]:
    bindings = v1.source_bindings(v1_authority)
    statistics_binding = bindings["sealed-v19-statistics-firewall"]
    statistics = v1.parse_statistics_firewall_payload(
        snapshot.payload("sealed-v19-statistics-firewall"),
        v1_authority,
        expected_sha256=statistics_binding["sha256"],
    )
    renderer = _import_module_bytes(
        "golden_v3_inherited_dev20_renderer_bound",
        ROOT / bindings["v21-dev20-renderer-algorithm"]["path"],
        snapshot.payload("v21-dev20-renderer-algorithm"),
    )
    baseline = _decode_snapshot_image(snapshot, "v18-byte-authority", mode="RGB")
    foundation = _decode_snapshot_image(
        snapshot, "v21-foundation-v19-canonical", mode="RGB"
    )
    if baseline.shape != foundation.shape:
        raise DerivationError("v18/foundation canvas changed")
    shape = baseline.shape[:2]
    v19_control = _decode_snapshot_image(
        snapshot, "v19-body-control", mode="L", shape=shape
    )
    v20_control = _decode_snapshot_image(
        snapshot, "v20-replacement-body-control", mode="L", shape=shape
    )
    marks = v1._load_strict_json_object(
        snapshot.payload("v21-dev20-ridge-marks"), label="snapshotted dev20 marks"
    )
    permission = _decode_snapshot_image(
        snapshot, "permission-mask", mode="L", shape=shape, binary=True
    )
    protected = _decode_snapshot_image(
        snapshot, "protected-mask", mode="L", shape=shape, binary=True
    )
    road_calm = _decode_snapshot_image(
        snapshot, "road-calm-mask", mode="L", shape=shape, binary=True
    )
    alpha_zero = _decode_snapshot_image(
        snapshot, "alpha-zero-mask", mode="L", shape=shape, binary=True
    )
    _, d20, v19_masks, v20_masks = v1.reconstruct_dev20_luma_delta(
        renderer,
        baseline,
        foundation,
        v19_control,
        v20_control,
        marks,
        permission,
        protected,
        road_calm,
        v1_authority,
    )
    v1._validate_firewall_supports(v1_authority, statistics, v19_masks)
    statistics = list(statistics)
    statistics.append(v1.aggregate_body_statistics(statistics))
    kernels = copy.deepcopy(v1_authority["derivation"]["fixed_filters"]["kernels"])
    kernels["G2"] = {
        "coefficients": authority["derivation"]["filters"]["G2"]["coefficients"]
    }
    prepared: list[PreparedBody] = []
    for body_index, body in enumerate(v20_masks):
        phase_body = v1.phase_support_crop(body)
        phase_bands = synthesize_independent_bands(
            phase_body.shape,
            phase_body,
            statistics[body_index],
            body_index,
            kernels,
            v1=v1,
        )
        full_bands = IndependentBands(
            g2_to_g4=np.zeros(shape, dtype=np.int64),
            g4_to_g8=np.zeros(shape, dtype=np.int64),
            g8_to_g24=np.zeros(shape, dtype=np.int64),
        )
        full_bands.g2_to_g4[body] = phase_bands.g2_to_g4[phase_body]
        full_bands.g4_to_g8[body] = phase_bands.g4_to_g8[phase_body]
        full_bands.g8_to_g24[body] = phase_bands.g8_to_g24[phase_body]
        d20_y, d20_x, d20_body = v1.body_crop(body, padding=96)
        local_delta = np.zeros(d20_body.shape, dtype=np.int64)
        local_delta[d20_body] = d20[d20_y, d20_x][d20_body].astype(np.int64) * Q16
        coarse_local = v1.q30_filter(local_delta, kernels["G24"])
        coarse = np.zeros(shape, dtype=np.int64)
        coarse[body] = coarse_local[d20_body]
        prepared.append(
            PreparedBody(
                mask=body,
                statistics=statistics[body_index],
                bands=full_bands,
                coarse_q16=coarse,
                amplitude_seed=derive_seed(body_index, "amplitude-envelope")[0],
                unit_seed=derive_seed(body_index, "unit-whitening")[0],
            )
        )
    return (
        prepared,
        foundation,
        baseline,
        permission,
        protected,
        road_calm,
        alpha_zero,
        v20_masks,
        renderer,
        kernels,
    )


def build_payloads(
    authority: Mapping[str, Any],
    *,
    v1: ModuleType | None = None,
    v1_authority: Mapping[str, Any] | None = None,
    snapshot: BoundInputSnapshot | None = None,
) -> list[CandidatePayload]:
    """Construct exactly four payloads in memory without evaluating them."""

    supplied = (v1 is not None, v1_authority is not None, snapshot is not None)
    if any(supplied) and not all(supplied):
        raise DerivationError(
            "prepared v1 helper, authority, and input snapshot must be supplied together"
        )
    if v1 is None or v1_authority is None or snapshot is None:
        v1, v1_authority, snapshot = preflight(authority)
    (
        prepared,
        foundation,
        baseline,
        permission,
        protected,
        road_calm,
        alpha_zero,
        v20_masks,
        renderer,
        kernels,
    ) = _prepare_bodies(authority, v1, v1_authority, snapshot)
    foundation_lab = cv2.cvtColor(foundation, cv2.COLOR_RGB2LAB)
    repair_config = authority["derivation"]["construction_repair"]
    amplitude_config = authority["derivation"]["amplitude_construction"]
    unit_config = authority["derivation"]["unit_whitening"]
    quiet_config = authority["derivation"]["quiet_reserve"]
    mutable = (
        np.logical_or.reduce(v20_masks)
        & permission
        & ~protected
        & ~road_calm
        & ~alpha_zero
    )
    payloads: list[CandidatePayload] = []
    for record in authority["candidates"]["records"]:
        candidate_lab_q16 = foundation_lab.astype(np.int64) * Q16
        quiet_clipped = 0
        short_repairs = 0
        short_pixels = 0
        short_touched_by_body: list[np.ndarray] = []
        for body_record in prepared:
            statistical = compose_statistical_field(body_record.bands, record, v1=v1)
            statistical = v1.rational_multiply(
                statistical, *record["statistical_overall_gain_rational"]
            )
            coarse = v1.rational_multiply(
                body_record.coarse_q16, *record["dev20_g24_gain_rational"]
            )
            residual = v1._checked_add_int64(
                statistical, coarse, label="statistical plus dev20 G24"
            )
            target, _ = construct_target_amplitude(
                residual,
                body_record.mask,
                body_record.amplitude_seed,
                record["amplitude_depth_rational"],
                kernels["G4"],
                amplitude_config,
                v1=v1,
            )
            residual, _ = whiten_unit_carrier(
                residual,
                body_record.mask,
                body_record.unit_seed,
                kernels["G4"],
                kernels["G8"],
                unit_config,
                v1=v1,
            )
            residual, clipped = apply_quiet_reserve(
                residual,
                body_record.mask,
                kernels["G4"],
                quiet_config,
                v1=v1,
            )
            residual = match_target_amplitude(
                residual,
                target,
                body_record.mask,
                kernels["G8"],
                amplitude_config,
                v1=v1,
            )
            repair_budget = _budget_pixels(
                int(np.count_nonzero(body_record.mask)),
                repair_config["per_stage_pixel_budget_rational"],
            )
            residual, short_count, short_touched = repair_short_dark_components(
                residual,
                body_record.mask,
                repair_config["short_dark"],
                maximum_repairs=int(
                    repair_config["maximum_repairs_per_stage_per_body"]
                ),
                pixel_budget=repair_budget,
                v1=v1,
                mutable=mutable & body_record.mask,
            )
            quiet_clipped += clipped
            short_repairs += short_count
            short_pixels += int(np.count_nonzero(short_touched))
            short_touched_by_body.append(short_touched)
            body = body_record.mask
            candidate_lab_q16[..., 0][body] = v1._checked_add_int64(
                residual[body],
                np.full(
                    int(np.count_nonzero(body)),
                    int(body_record.statistics.median_lab_q16[0]),
                    dtype=np.int64,
                ),
                label="body median plus balanced residual",
            )
            candidate_lab_q16[..., 1][body] = int(
                body_record.statistics.median_lab_q16[1]
            )
            candidate_lab_q16[..., 2][body] = int(
                body_record.statistics.median_lab_q16[2]
            )
        encoded_lab = v1.q16_to_u8(candidate_lab_q16)
        candidate = cv2.cvtColor(encoded_lab, cv2.COLOR_LAB2RGB)
        candidate = v1.finalize_candidate_rgb(
            candidate,
            foundation,
            baseline,
            permission,
            protected,
            road_calm,
            alpha_zero,
            v20_masks,
        )
        candidate, topology_repairs, topology_pixels = repair_final_rgb_topology(
            candidate,
            foundation,
            v20_masks,
            mutable,
            short_touched_by_body,
            repair_config,
            kernels,
            v1=v1,
        )
        final_delta_luma = construction_luma_u8(candidate).astype(
            np.int64
        ) - construction_luma_u8(foundation).astype(np.int64)
        amplitude_certificates: list[LagCertificate] = []
        unit_certificates: list[LagCertificate] = []
        for body in v20_masks:
            fields = derive_final_fields_q12(
                final_delta_luma,
                body,
                kernels["G8"],
                v1=v1,
            )
            amplitude_certificates.append(
                lag_certificate(
                    fields.amplitude_q12,
                    body,
                    kernels["G4"],
                    amplitude_config["lag_decorrelation"],
                    v1=v1,
                )
            )
            unit_certificates.append(
                lag_certificate(
                    fields.unit_q12,
                    body,
                    kernels["G4"],
                    unit_config["lag_decorrelation"],
                    v1=v1,
                )
            )
        receipt = ConstructionReceipt(
            amplitude_matching_iterations=4,
            amplitude_certificate=combine_lag_certificates(amplitude_certificates),
            unit_certificate=combine_lag_certificates(unit_certificates),
            quiet_clipped_pixels=quiet_clipped,
            short_dark_repairs=short_repairs,
            short_dark_pixels=short_pixels,
            topology_repairs=topology_repairs,
            topology_pixels=topology_pixels,
        )
        payloads.append(
            CandidatePayload(
                path=ROOT / record["output_path"],
                payload=renderer._rgb_png(candidate),
                receipt=receipt,
            )
        )
    if len(payloads) != 4 or len({item.path for item in payloads}) != 4:
        raise DerivationError("payload closure changed")
    return payloads


def canonical_output_seal_json(value: Any) -> bytes:
    return canonical_json(value, pretty=True)


def _authority_identity(authority: Mapping[str, Any]) -> str:
    identity = authority["canonical_self_sha256"]
    if authority_self_hash(authority) != identity:
        raise DerivationError("authority identity changed before sealing")
    return identity


def expected_runtime_attestation(
    authority: Mapping[str, Any], profile_id: str
) -> dict[str, Any]:
    matches = [
        profile
        for profile in authority["runtime"]["allowed_profiles"]
        if profile.get("id") == profile_id
    ]
    if len(matches) != 1:
        raise DerivationError("runtime attestation profile is not uniquely allowed")
    return {
        "profile_id": profile_id,
        "common": copy.deepcopy(authority["runtime"]["common"]),
        "profile": copy.deepcopy(matches[0]),
    }


def validate_runtime_attestation(
    attestation: Any, authority: Mapping[str, Any]
) -> Mapping[str, Any]:
    if not isinstance(attestation, dict) or list(attestation) != [
        "profile_id",
        "common",
        "profile",
    ]:
        raise DerivationError("runtime attestation schema/order changed")
    profile_id = attestation["profile_id"]
    if not isinstance(profile_id, str):
        raise DerivationError("runtime attestation profile id changed")
    expected = expected_runtime_attestation(authority, profile_id)
    if not _exact_json_equal(attestation, expected):
        raise DerivationError("runtime attestation does not match its allowed profile")
    return attestation


def obtain_runtime_attestation(authority: Mapping[str, Any]) -> dict[str, Any]:
    """Re-load the SHA-bound v1 helper and attest the actual gated runtime."""

    v1, _ = _validated_v1_context(authority)
    profile_id = v1._runtime_gate()
    actual = {
        "profile_id": profile_id,
        "common": {
            "python_implementation": v1.platform.python_implementation(),
            "python_version": v1.platform.python_version(),
            "opencv_api": v1.cv2.__version__,
            "numpy": v1.np.__version__,
            "pillow": v1.PIL.__version__,
            "byteorder": v1.sys.byteorder,
            "opencv_threads": v1.cv2.getNumThreads(),
        },
        "profile": {
            "id": profile_id,
            "platform_system": v1.platform.system(),
            "platform_machine": v1.platform.machine(),
            "opencv_distributions": v1._opencv_distributions(),
            "opencv_build_sha256": v1.sha256_bytes(
                v1.cv2.getBuildInformation().encode("utf-8")
            ),
        },
    }
    validate_runtime_attestation(actual, authority)
    return actual


def validate_output_seal_payload(
    payload: bytes, authority: Mapping[str, Any]
) -> dict[str, Any]:
    seal = load_strict_json(payload, label="balanced-open-phase-v3 output seal")
    expected_keys = [
        "schema_id",
        "authority_self_sha256",
        "statistics_firewall_sha256",
        "runtime_attestation",
        "candidate_count",
        "candidates",
    ]
    if list(seal) != expected_keys:
        raise DerivationError("output seal top-level schema/order changed")
    if seal[
        "schema_id"
    ] != "sstory.k3.golden-v3.balanced-open-phase-v3-output-seal.v1" or seal[
        "authority_self_sha256"
    ] != _authority_identity(authority):
        raise DerivationError("output seal authority identity changed")
    firewall_sha = source_bindings(authority)["sealed-v19-statistics-firewall"][
        "sha256"
    ]
    if seal["statistics_firewall_sha256"] != firewall_sha:
        raise DerivationError("output seal firewall identity changed")
    validate_runtime_attestation(seal["runtime_attestation"], authority)
    records = seal["candidates"]
    expected_records = authority["candidates"]["records"]
    if (
        type(seal["candidate_count"]) is not int
        or seal["candidate_count"] != 4
        or not isinstance(records, list)
        or len(records) != 4
    ):
        raise DerivationError("output seal candidate count changed")
    for index, (record, expected) in enumerate(
        zip(records, expected_records, strict=True)
    ):
        if (
            not isinstance(record, dict)
            or list(record)
            != ["candidate_id", "path", "sha256", "bytes", "construction_receipt"]
            or record["candidate_id"] != expected["candidate_id"]
            or record["path"] != expected["output_path"]
            or not isinstance(record["sha256"], str)
            or SHA256_PATTERN.fullmatch(record["sha256"]) is None
            or isinstance(record["bytes"], bool)
            or not isinstance(record["bytes"], int)
            or record["bytes"] <= 0
        ):
            raise DerivationError(f"output seal candidate {index} changed")
        receipt = record["construction_receipt"]
        if not isinstance(receipt, dict) or list(receipt) != [
            "amplitude_matching_iterations",
            "amplitude_lag_certificate",
            "unit_lag_certificate",
            "quiet_clipped_pixels",
            "short_dark_repairs",
            "short_dark_pixels",
            "topology_repairs",
            "topology_pixels",
        ]:
            raise DerivationError(f"output seal candidate {index} receipt changed")
        if (
            type(receipt["amplitude_matching_iterations"]) is not int
            or receipt["amplitude_matching_iterations"] != 4
        ):
            raise DerivationError(
                f"output seal candidate {index} iteration receipt changed"
            )
        for certificate_name in ("amplitude_lag_certificate", "unit_lag_certificate"):
            certificate = receipt[certificate_name]
            if not isinstance(certificate, dict) or list(certificate) != [
                "eligible_records",
                "maximum_numerator",
                "maximum_variance_product",
                "maximum_correlation_q20",
            ]:
                raise DerivationError(
                    f"output seal candidate {index} certificate changed"
                )
            if any(
                type(value) is not int or value < 0 for value in certificate.values()
            ):
                raise DerivationError(
                    f"output seal candidate {index} certificate value changed"
                )
            if not 8 * 12 <= certificate["eligible_records"] <= 8 * 3 * 14:
                raise DerivationError(
                    f"output seal candidate {index} certificate coverage changed"
                )
            numerator = certificate["maximum_numerator"]
            variance_product = certificate["maximum_variance_product"]
            if variance_product <= 0:
                raise DerivationError(
                    f"output seal candidate {index} certificate variance changed"
                )
            exact_q20 = math.isqrt((numerator * numerator << 40) // variance_product)
            if certificate["maximum_correlation_q20"] != exact_q20:
                raise DerivationError(
                    f"output seal candidate {index} certificate ratio changed"
                )
            if numerator**2 * 128**2 > variance_product:
                raise DerivationError(
                    f"output seal candidate {index} certificate limit changed"
                )
        for count_name in (
            "quiet_clipped_pixels",
            "short_dark_repairs",
            "short_dark_pixels",
            "topology_repairs",
            "topology_pixels",
        ):
            if type(receipt[count_name]) is not int or receipt[count_name] < 0:
                raise DerivationError(
                    f"output seal candidate {index} receipt count changed"
                )
    if canonical_output_seal_json(seal) != payload:
        raise DerivationError("output seal bytes are not canonical")
    return seal


def _write_exclusive_file(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
    if path.read_bytes() != payload:
        raise DerivationError(f"staged bytes changed: {path.name}")


def _is_link_or_junction(path: Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.is_symlink() or (
            hasattr(candidate, "is_junction") and candidate.is_junction()
        )
    except OSError as exc:
        raise DerivationError(f"cannot inspect path identity: {candidate}") from exc


def _prepare_secure_root(root: Path) -> tuple[Path, Path]:
    absolute = Path(os.path.abspath(os.fspath(root)))
    link_or_junction = _is_link_or_junction(absolute)
    if not absolute.exists() and not link_or_junction:
        absolute.mkdir(parents=True)
    if link_or_junction or not absolute.is_dir():
        raise DerivationError("publication root must be a real directory")
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise DerivationError("publication root cannot be resolved") from exc
    return absolute, resolved


def _assert_secure_containment(
    root: Path,
    resolved_root: Path,
    target: Path,
    *,
    label: str,
) -> Path:
    absolute_target = Path(os.path.abspath(os.fspath(target)))
    try:
        relative = absolute_target.relative_to(root)
    except ValueError as exc:
        raise DerivationError(f"{label} escaped publication root") from exc
    current = root
    for index, part in enumerate(relative.parts):
        current /= part
        link_or_junction = _is_link_or_junction(current)
        if not current.exists() and not link_or_junction:
            continue
        if link_or_junction:
            raise DerivationError(f"{label} contains a link or junction ancestor")
        if index < len(relative.parts) - 1 and not current.is_dir():
            raise DerivationError(f"{label} ancestor is not a directory")
        try:
            resolved = current.resolve(strict=True)
            resolved.relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise DerivationError(
                f"{label} real path escaped publication root"
            ) from exc
    return absolute_target


def _enumerate_secure_staging(
    root: Path,
    resolved_root: Path,
    staging_directory: Path,
) -> dict[str, Path]:
    staging = _assert_secure_containment(
        root,
        resolved_root,
        staging_directory,
        label="staging directory",
    )
    if _is_link_or_junction(staging) or not staging.is_dir():
        raise DerivationError("staging directory is not a real directory")
    entries: dict[str, Path] = {}
    stack = [staging]
    while stack:
        directory = stack.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            raise DerivationError("cannot enumerate staging directory") from exc
        for child in children:
            relative = child.relative_to(staging).as_posix()
            if relative in entries:
                raise DerivationError("staging entry identity is duplicated")
            if _is_link_or_junction(child):
                raise DerivationError("staging contains a link or junction")
            _assert_secure_containment(
                root,
                resolved_root,
                child,
                label="staging entry",
            )
            entries[relative] = child
            if child.is_dir():
                stack.append(child)
            elif not child.is_file():
                raise DerivationError("staging contains a non-regular entry")
            elif child.stat().st_nlink != 1:
                raise DerivationError("staging contains a linked regular file")
    return entries


def _verify_staging_before_rename(
    authority: Mapping[str, Any],
    root: Path,
    resolved_root: Path,
    staging_directory: Path,
    staged_outputs: Sequence[Path],
    payloads: Sequence[CandidatePayload],
    staged_seal: Path,
    seal_payload: bytes,
) -> None:
    entries = _enumerate_secure_staging(root, resolved_root, staging_directory)
    expected_paths = [*staged_outputs, staged_seal]
    expected_names = {
        path.relative_to(staging_directory).as_posix() for path in expected_paths
    }
    if set(entries) != expected_names or len(entries) != 5:
        raise DerivationError("staging file closure changed")
    for staged, item in zip(staged_outputs, payloads, strict=True):
        relative = staged.relative_to(staging_directory).as_posix()
        actual = entries[relative].read_bytes()
        if len(actual) != len(item.payload) or sha256_bytes(actual) != sha256_bytes(
            item.payload
        ):
            raise DerivationError(f"staged candidate bytes changed: {staged.name}")
    seal_relative = staged_seal.relative_to(staging_directory).as_posix()
    actual_seal = entries[seal_relative].read_bytes()
    if actual_seal != seal_payload:
        raise DerivationError("staged canonical seal bytes changed")
    validate_output_seal_payload(actual_seal, authority)


def _remove_staging_entry_nofollow(path: Path) -> None:
    candidate = Path(path)
    if candidate.is_symlink():
        candidate.unlink()
        return
    if hasattr(candidate, "is_junction") and candidate.is_junction():
        candidate.rmdir()
        return
    if candidate.is_dir():
        for child in candidate.iterdir():
            _remove_staging_entry_nofollow(child)
        candidate.rmdir()
        return
    if candidate.exists():
        candidate.unlink()


def _rollback_staging(directory: Path) -> None:
    try:
        _remove_staging_entry_nofollow(directory)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise DerivationError("failed to roll back exclusive staging") from exc


def _rename_directory_noreplace(source: Path, target: Path) -> None:
    """Atomically publish a directory while refusing an existing target."""

    if sys.platform == "linux":
        try:
            renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
        except AttributeError as exc:
            raise DerivationError(
                "Linux atomic no-replace rename is unavailable"
            ) from exc
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        at_fdcwd = -100
        rename_noreplace = 1
        if (
            renameat2(
                at_fdcwd,
                os.fsencode(source),
                at_fdcwd,
                os.fsencode(target),
                rename_noreplace,
            )
            != 0
        ):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(target))
        return
    if sys.platform == "win32":
        source.rename(target)
        return
    raise DerivationError("atomic no-replace rename is unavailable on this platform")


def publish_payloads_exclusive(
    authority: Mapping[str, Any],
    payloads: Sequence[CandidatePayload],
    *,
    root: Path = ROOT,
) -> Path:
    root, resolved_root = _prepare_secure_root(Path(root))
    cli = authority["cli_contract"]
    output_directory = _assert_secure_containment(
        root,
        resolved_root,
        root
        / _safe_relative(
            cli["output_directory"], label="output directory", output=True
        ),
        label="output directory",
    )
    staging_directory = _assert_secure_containment(
        root,
        resolved_root,
        root
        / _safe_relative(
            cli["staging_directory"], label="staging directory", output=True
        ),
        label="staging directory",
    )
    if (
        staging_directory.parent != output_directory.parent
        or staging_directory == output_directory
    ):
        raise DerivationError("staging directory escaped the final directory parent")
    records = authority["candidates"]["records"]
    outputs = [root / record["output_path"] for record in records]
    payload_list = list(payloads)
    if len(payload_list) != 4 or [item.path for item in payload_list] != outputs:
        raise DerivationError("payload output order changed")
    if (
        any(path.parent != output_directory for path in outputs)
        or len(set(outputs)) != 4
    ):
        raise DerivationError("candidate output path closure changed")
    runtime_attestation = obtain_runtime_attestation(authority)
    seal_path = root / _safe_relative(
        cli["seal_path"], label="output seal", output=True
    )
    if seal_path.parent != output_directory or seal_path in outputs:
        raise DerivationError("output seal escaped fixed directory")
    seal_records = []
    for record, item in zip(records, payload_list, strict=True):
        path, payload = item.path, item.payload
        if not isinstance(payload, bytes):
            raise DerivationError("candidate payload must be immutable bytes")
        seal_records.append(
            {
                "candidate_id": record["candidate_id"],
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
                "construction_receipt": construction_receipt_json(item.receipt),
            }
        )
    seal = {
        "schema_id": "sstory.k3.golden-v3.balanced-open-phase-v3-output-seal.v1",
        "authority_self_sha256": _authority_identity(authority),
        "statistics_firewall_sha256": source_bindings(authority)[
            "sealed-v19-statistics-firewall"
        ]["sha256"],
        "runtime_attestation": runtime_attestation,
        "candidate_count": 4,
        "candidates": seal_records,
    }
    seal_payload = canonical_output_seal_json(seal)
    validate_output_seal_payload(seal_payload, authority)
    output_parent = _assert_secure_containment(
        root,
        resolved_root,
        output_directory.parent,
        label="output parent",
    )
    output_parent.mkdir(parents=True, exist_ok=True)
    _assert_secure_containment(
        root,
        resolved_root,
        output_parent,
        label="output parent",
    )
    if output_directory.exists() or output_directory.is_symlink():
        raise DerivationError("final output directory reservation already exists")
    try:
        staging_directory.mkdir()
    except FileExistsError as exc:
        raise DerivationError("exclusive staging directory already exists") from exc
    except OSError as exc:
        raise DerivationError("exclusive staging directory reservation failed") from exc
    _assert_secure_containment(
        root,
        resolved_root,
        staging_directory,
        label="staging directory",
    )
    staged_outputs = [staging_directory / path.name for path in outputs]
    staged_seal = staging_directory / seal_path.name
    try:
        for staged, item in zip(staged_outputs, payload_list, strict=True):
            _write_exclusive_file(staged, item.payload)
        _write_exclusive_file(staged_seal, seal_payload)
        if output_directory.exists() or output_directory.is_symlink():
            raise DerivationError("final output directory appeared during staging")
        _assert_secure_containment(
            root,
            resolved_root,
            output_directory,
            label="output directory",
        )
        _verify_staging_before_rename(
            authority,
            root,
            resolved_root,
            staging_directory,
            staged_outputs,
            payload_list,
            staged_seal,
            seal_payload,
        )
        _rename_directory_noreplace(staging_directory, output_directory)
    except Exception as exc:
        try:
            _rollback_staging(staging_directory)
        except DerivationError as cleanup_exc:
            raise DerivationError(
                f"staged publication failed and cleanup failed: {cleanup_exc}"
            ) from exc
        if isinstance(exc, DerivationError):
            raise
        raise DerivationError("exclusive staged publication failed") from exc
    return output_directory / seal_path.name


def _load_output_seal(path: Path, authority: Mapping[str, Any]) -> dict[str, Any]:
    manifest = Path(path)
    expected_name = PurePosixPath(authority["cli_contract"]["seal_path"]).name
    if manifest.name != expected_name:
        raise DerivationError("profile seal must use the fixed manifest filename")
    if manifest.is_symlink() or not manifest.is_file():
        raise DerivationError("profile seal must be a regular non-symlink file")
    return validate_output_seal_payload(manifest.read_bytes(), authority)


def compare_profile_seals(
    authority: Mapping[str, Any], left_path: Path, right_path: Path
) -> tuple[str, str]:
    _validated_v1_context(authority)
    left = _load_output_seal(left_path, authority)
    right = _load_output_seal(right_path, authority)
    left_profile = left["runtime_attestation"]["profile_id"]
    right_profile = right["runtime_attestation"]["profile_id"]
    required_profiles = authority["cli_contract"]["required_comparison_profile_ids"]
    if {left_profile, right_profile} != set(required_profiles):
        raise DerivationError("profile seals do not contain the two required profiles")
    comparable = (
        "schema_id",
        "authority_self_sha256",
        "statistics_firewall_sha256",
        "candidate_count",
        "candidates",
    )
    if any(left[key] != right[key] for key in comparable):
        raise DerivationError("cross-profile payload hashes/bytes differ")
    return left_profile, right_profile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--validate-only",
        action="store_true",
        help="validate authority and text bindings only (default)",
    )
    mode.add_argument(
        "--preflight",
        action="store_true",
        help="hash the inherited emit-read closure without raster decode",
    )
    mode.add_argument(
        "--emit",
        action="store_true",
        help="explicitly construct and exclusively publish exactly four payloads",
    )
    mode.add_argument(
        "--compare-seals",
        nargs=2,
        metavar=("LEFT", "RIGHT"),
        type=Path,
        help="compare two profile seals without opening PNGs",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        authority = load_authority()
        if args.compare_seals is not None:
            left, right = compare_profile_seals(
                authority, args.compare_seals[0], args.compare_seals[1]
            )
            print(f"balanced-open-phase-v3 profile seals match: {left} / {right}")
        elif args.emit:
            v1, v1_authority, snapshot = preflight(authority)
            v1._runtime_gate()
            payloads = build_payloads(
                authority,
                v1=v1,
                v1_authority=v1_authority,
                snapshot=snapshot,
            )
            publish_payloads_exclusive(authority, payloads)
            print(
                "emitted exactly four balanced-open-phase-v3 payloads; no audit was run"
            )
        elif args.preflight:
            v1, _, _ = preflight(authority)
            runtime_profile = v1._runtime_gate()
            print(
                "balanced-open-phase-v3 inherited emit-read preflight passed without raster "
                f"decode: {runtime_profile}"
            )
        else:
            validate_only(authority)
            print("balanced-open-phase-v3 authority and text bindings are valid")
        return 0
    except (DerivationError, OSError, ValueError) as exc:
        parser.exit(2, f"Balanced-open-phase-v3 derivation failed closed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
