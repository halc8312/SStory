#!/usr/bin/env python3
"""Validate, emit, or compare seals for the four preregistered candidates.

The default action is a read-only plan/source check.  Candidate construction
requires ``--emit``.  ``--compare-seals`` reads only two output manifests and
compares their four PNG hashes across distinct runtime profiles.  This module
deliberately has no evaluator, thresholds, candidate measurements, alternate
parameters, output override, or overwrite path.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, Mapping, Sequence

import cv2
import numpy as np
import PIL
from PIL import Image, UnidentifiedImageError


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_PATH = ROOT / (
    "world/map-production/spec/"
    "style-candidate-k3-golden-v3-four-candidate-derivation-preregistration-v1.json"
)
AUTHORITY_SHA256 = "16831a60572054f9ecf243304862d75483807dd67472ce9b17880fb7e85866d2"
STRICT_AUTHORITY_SHA256 = "c27b41e6336974c5ce5fe11c86cefc67ed35851650680c33379c3510444884d7"
INTERFACE = "sstory-k3-golden-v3-four-candidate-derivation-preregistration-v1"
ALGORITHM = "sstory-k3-golden-v3-four-candidate-statistical-phase-derivation-v1"
BODY_VALUES = (32, 64, 96, 128, 160, 192, 224, 255)
EXPECTED_SUPPORT_SHA256 = {
    "32": "22411dccde51d280322d6357bf3bfd7103c83316df75d5e153c4d4628e573d94",
    "64": "f528cfa39a95ea1f49c9cefaa35848f7ce7bb9b0939eab325501aabfd04f2f0e",
    "96": "5c7219a4a67dd2be266011791b7ff04e2c19e996088ebd39c61760ab0e9240c9",
    "128": "b3ff40a24077abb168a1490a1b23b8841d024243ec201a3833799bc8c7d38d81",
    "160": "b28ce325cc9a0abffafa3c4d4cf94bb85b468973fbef972cc2f082148f657ccd",
    "192": "6e2dcb974dfb2596c861916719c637df70b5a16095527abcaa9dba4f377f545a",
    "224": "df6ef1892510bf62dc55d46fbe25b365e16d9ec194284245341ebcc712ea0bc9",
}
Q30 = 1 << 30
Q16 = 1 << 16
Q16_MIN = -(1 << 31)
Q16_MAX = (1 << 31) - 1
INT64_MIN = np.iinfo(np.int64).min
INT64_MAX = np.iinfo(np.int64).max
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_RUNTIME = {
    "common": {
        "python_implementation": "CPython",
        "python_version": "3.12.10",
        "opencv_api": "4.13.0",
        "numpy": "2.3.5",
        "pillow": "12.3.0",
        "byteorder": "little",
        "opencv_threads": 1,
    },
    "allowed_profiles": [
        {
            "id": "windows-local-opencv-python-4.13.0.92",
            "platform_system": "Windows",
            "platform_machine": "AMD64",
            "opencv_distributions": [{"name": "opencv-python", "version": "4.13.0.92"}],
            "opencv_build_sha256": "8a55f551e40cf84d0fa7e2509bb9544da66782a8cbc017d7ce27a9de0ef9c1ac",
        },
        {
            "id": "windows-ci-opencv-python-headless-4.13.0.92",
            "platform_system": "Windows",
            "platform_machine": "AMD64",
            "opencv_distributions": [
                {"name": "opencv-python-headless", "version": "4.13.0.92"}
            ],
            "opencv_build_sha256": "fc048a2b6c657a1e163e8591b98100d585d65bacf1d1f1a6e28659cae3b531f1",
        },
        {
            "id": "linux-ci-opencv-python-headless-4.13.0.92",
            "platform_system": "Linux",
            "platform_machine": "x86_64",
            "opencv_distributions": [
                {"name": "opencv-python-headless", "version": "4.13.0.92"}
            ],
            "opencv_build_sha256": "9e0b6b5d3c457d7794d56f55acd3afdadd8fd4b5a8a562e78bcab4fadaf1e604",
        },
    ],
    "profile_selection": "exactly one profile must match system, machine, installed OpenCV distribution set, and OpenCV build-information SHA-256",
    "opencv_rng_seed": 0x4538,
}
EXPECTED_CANDIDATES = (
    (
        "F094-M148",
        (47, 50),
        (37, 25),
        "tmp/map-production/k3-golden-v3-preregistered-four/"
        "style-candidate-k-v3-golden-v3-F094-M148.png",
    ),
    (
        "F094-M155",
        (47, 50),
        (31, 20),
        "tmp/map-production/k3-golden-v3-preregistered-four/"
        "style-candidate-k-v3-golden-v3-F094-M155.png",
    ),
    (
        "F097-M148",
        (97, 100),
        (37, 25),
        "tmp/map-production/k3-golden-v3-preregistered-four/"
        "style-candidate-k-v3-golden-v3-F097-M148.png",
    ),
    (
        "F097-M155",
        (97, 100),
        (31, 20),
        "tmp/map-production/k3-golden-v3-preregistered-four/"
        "style-candidate-k-v3-golden-v3-F097-M155.png",
    ),
)
SEARCH_PARAMETER_KEYS: tuple[str, ...] = ()


class DerivationError(RuntimeError):
    """Raised before an unbound or non-preregistered output can be written."""


@dataclass(frozen=True)
class BodyStatistics:
    median_lab_q16: np.ndarray
    radial_power_q16: np.ndarray
    quantiles_q16: np.ndarray


@dataclass(frozen=True)
class PhaseBands:
    sub4: np.ndarray
    g4_to_g8: np.ndarray
    g8_to_g24: np.ndarray


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def array_sha256(values: np.ndarray) -> str:
    return sha256_bytes(np.ascontiguousarray(values).tobytes())


def _canonical_int_array(values: Sequence[int]) -> bytes:
    return json.dumps(list(values), separators=(",", ":")).encode("utf-8")


def _reject_duplicate_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DerivationError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _load_strict_json_object(payload: bytes, *, label: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise DerivationError(f"{label} contains forbidden constant {value!r}")

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_object_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise DerivationError(f"{label} is not strict UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise DerivationError(f"{label} must contain exactly one JSON object")
    return value


def canonical_statistics_json(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DerivationError(f"statistics firewall is not canonical JSON data: {exc}") from exc
    return rendered.encode("utf-8") + b"\n"


def _safe_relative(value: Any, *, label: str, output: bool = False) -> str:
    if not isinstance(value, str) or not value:
        raise DerivationError(f"{label} must be a nonempty repository-relative path")
    if "\\" in value or PurePosixPath(value).is_absolute():
        raise DerivationError(f"{label} is not canonical repository-relative POSIX")
    parts = PurePosixPath(value).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise DerivationError(f"{label} contains an unsafe path component")
    lowered = value.lower()
    if not output and (
        any(part.lower() == "tmp" for part in parts)
        or "temp" in PurePosixPath(value).name.lower()
        or "v246" in lowered
        or "microtexture" in lowered
    ):
        raise DerivationError(f"{label} is a prohibited derivation input")
    return value


def _require_keys(value: Any, expected: set[str], *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise DerivationError(f"{label} keys changed")
    return value


def validate_authority(authority: Mapping[str, Any]) -> None:
    """Validate the immutable plan without reading any bound source raster."""

    required_top = {
        "schema_version",
        "interface",
        "status",
        "immutable_plan",
        "strict_audit_authority",
        "runtime",
        "input_policy",
        "derivation",
        "candidates",
        "cli_contract",
    }
    _require_keys(authority, required_top, label="authority")
    if (
        authority["schema_version"] != "1.0.0"
        or authority["interface"] != INTERFACE
        or authority["status"] != "preregistered-code-only-not-generated"
        or authority["immutable_plan"] is not True
    ):
        raise DerivationError("authority identity/status changed")
    strict = authority["strict_audit_authority"]
    if (
        not isinstance(strict, dict)
        or strict.get("sha256") != STRICT_AUTHORITY_SHA256
        or set(strict) != {"path", "sha256", "policy"}
    ):
        raise DerivationError("strict audit authority reference changed")
    if authority["runtime"] != EXPECTED_RUNTIME:
        raise DerivationError("runtime authority changed")

    policy = authority["input_policy"]
    bindings = policy.get("source_bindings") if isinstance(policy, dict) else None
    if (
        not isinstance(bindings, list)
        or policy.get("exact_source_binding_count") != len(bindings)
        or policy.get("unlisted_inputs_forbidden") is not True
        or policy.get("tracked_worktree_bytes_must_match_sha256") is not True
    ):
        raise DerivationError("source binding policy changed")
    roles: set[str] = set()
    paths: set[str] = set()
    for index, record in enumerate(bindings):
        if not isinstance(record, dict) or set(record) != {"role", "path", "sha256", "use"}:
            raise DerivationError(f"source binding {index} keys changed")
        role = record["role"]
        path = _safe_relative(record["path"], label=f"source binding {index}")
        digest = record["sha256"]
        if (
            not isinstance(role, str)
            or not role
            or role in roles
            or path in paths
            or not isinstance(digest, str)
            or SHA256_PATTERN.fullmatch(digest) is None
        ):
            raise DerivationError(f"source binding {index} is not unique/SHA-bound")
        roles.add(role)
        paths.add(path)
    if "strict-audit-authority-reference-only" not in roles:
        raise DerivationError("strict authority binding is absent")
    expected_emit_roles = [
        "strict-audit-authority-reference-only",
        "v18-byte-authority",
        "v19-body-control",
        "v21-dev20-renderer-algorithm",
        "v21-foundation-v19-canonical",
        "v20-replacement-body-control",
        "v21-dev20-ridge-marks",
        "permission-mask",
        "protected-mask",
        "road-calm-mask",
        "alpha-zero-mask",
        "sealed-v19-statistics-firewall",
    ]
    if policy.get("candidate_generator_read_allowlist_roles") != expected_emit_roles:
        raise DerivationError("candidate generator read allowlist changed")
    if policy.get("candidate_generator_forbidden_calls") != [
        "v21.load_replay_inputs",
        "v21.reconstruct",
        "v21._validate_search_summary",
        "v19 replay imports or raw raster reads",
    ]:
        raise DerivationError("candidate generator forbidden-call closure changed")
    if any(role not in roles for role in expected_emit_roles[:-1]):
        raise DerivationError("candidate generator allowlist names an unbound source")
    binding_by_role = {record["role"]: record for record in bindings}
    extractor_role = "v19-statistics-firewall-extractor-provenance-only"
    if (
        extractor_role not in binding_by_role
        or binding_by_role[extractor_role]["path"]
        != "scripts/map-production/extract_style_candidate_k3_golden_v3_v19_statistics.py"
        or binding_by_role[extractor_role]["sha256"]
        != "26ea56e203ffb8b9899d8d04042bfd8e9d0e14281f2b55fe55bc99b270cca955"
        or extractor_role in expected_emit_roles
    ):
        raise DerivationError("statistics extractor binding/read firewall changed")

    derivation = authority["derivation"]
    if (
        not isinstance(derivation, dict)
        or derivation.get("algorithm") != ALGORITHM
        or derivation.get("candidate_canvas")
        != "tracked v21 foundation-v19-canonical RGB bytes outside the exact v20 eight-body union; full-canvas Lab roundtrip bytes are never retained there"
    ):
        raise DerivationError("derivation algorithm changed")
    coverage = derivation.get("coverage_anchors", {})
    if (
        coverage.get("definition")
        != "exact support geometry, never a measured candidate gate"
        or coverage.get(
            "bodies_1_through_7_support_sha256_by_control_value"
        )
        != EXPECTED_SUPPORT_SHA256
    ):
        raise DerivationError("coverage anchor definition changed")
    v19 = derivation.get("v19_statistical_authority", {})
    if (
        v19.get("raw_spatial_pixels_allowed") is not False
        or v19.get("candidate_generator_reads_v19_replay") is not False
        or v19.get("firewall_status")
        != "schema-frozen-unsealed-no-real-statistics-extracted"
        or v19.get("future_artifact_sha256") is not None
    ):
        raise DerivationError("raw v19 spatial pixels became allowed")
    schema = v19.get("artifact_schema", {})
    expected_source_hashes = {
        "v19_contour_field_array_sha256": "a9b27c4a0cc6bf3a80702794853d5053d024e22b16088597fa4b32fd06e8b022",
        "v19_final_pixel_array_sha256": "f613b6579c637b6f93f12b7ffd332fd79e0b1cba1f5f992b578bf74adcedd1c3",
        "v19_renderer_sha256": "92100794ff519fb77c7bca89af74897dcc422c9bb341582d31355d6b98cd229a",
        "v19_replay_contract_sha256": "c8a4c4f2bb50905f0904cef050218d3fdafcafc7d11172a92db613774e02b0b6",
        "v19_statistics_extractor_sha256": "26ea56e203ffb8b9899d8d04042bfd8e9d0e14281f2b55fe55bc99b270cca955",
        "v19_transitive_inputs_sha256": "50aa6962fcc59c7ffb229ad5a510f0151d7a9d2500deebad2953daec27b6390e",
    }
    if (
        schema.get("exact_top_keys")
        != ["schema_id", "record_id", "source_hashes", "body_statistics"]
        or set(schema.get("source_hashes_exact_keys", []))
        != set(expected_source_hashes)
        or schema.get("source_hashes_expected") != expected_source_hashes
        or schema.get("body_statistics_exact_keys")
        != ["32", "64", "96", "128", "160", "192", "224"]
        or schema.get("body_255_forbidden") is not True
        or set(schema.get("body_record_exact_keys", []))
        != {
            "support_sha256",
            "median_lab_q16",
            "radial_power_q16",
            "quantiles_q16",
        }
        or schema.get("radial_bin_count") != 16
        or schema.get("quantile_count") != 17
    ):
        raise DerivationError("statistics firewall schema changed")
    coarse = derivation.get("dev20_coarse_authority", {})
    if (
        coarse.get("gain") != 1.0
        or coarse.get("saved_or_exposed") is not False
        or coarse.get("search_summary_parameter_whitelist") != list(SEARCH_PARAMETER_KEYS)
    ):
        raise DerivationError("dev20 coarse authority changed")

    phase = derivation.get("phase_synthesis", {})
    if (
        phase.get("statistics_extraction_crop")
        != "the separately SHA-bound extractor derives the tight coverage-anchor bounding box and appends exactly 8 synthetic zero pixels on every side (never canvas pixels); no crop coordinates cross the firewall"
        or phase.get("candidate_phase_crop")
        != "derive the tight coverage-anchor bounding box from the tracked v20 control and append exactly 96 synthetic zero pixels on every side, equal to the G24 radius, before phase realization and G4/G8/G24 filtering"
        or phase.get("d20_g24_crop")
        != "derive the tight coverage-anchor bounding box, expand by the literal G24 radius 96, and clip to canvas"
    ):
        raise DerivationError("statistics/phase/G24 crop closure changed")
    seeds = phase.get("seeds") if isinstance(phase, dict) else None
    if not isinstance(seeds, list) or len(seeds) != len(BODY_VALUES):
        raise DerivationError("phase seed table changed")
    seed_root = phase.get("seed_root")
    seen_seed_digests: set[str] = set()
    for index, seed in enumerate(seeds, start=1):
        if not isinstance(seed, dict) or set(seed) != {"body_id", "label", "sha256"}:
            raise DerivationError(f"body-{index} seed record changed")
        expected = sha256_bytes(f"{seed_root}:{seed['label']}".encode("utf-8"))
        if seed["body_id"] != f"body-{index}" or seed["sha256"] != expected:
            raise DerivationError(f"body-{index} phase seed derivation changed")
        if expected in seen_seed_digests:
            raise DerivationError("phase seed collision")
        seen_seed_digests.add(expected)

    fixed_filters = derivation.get("fixed_filters", {})
    kernels = fixed_filters.get("kernels") if isinstance(fixed_filters, dict) else None
    if not isinstance(kernels, dict) or set(kernels) != {"G4", "G8", "G24"}:
        raise DerivationError("fixed kernel set changed")
    for name, sigma in (("G4", 4), ("G8", 8), ("G24", 24)):
        record = kernels[name]
        expected_keys = {"sigma", "radius", "q_bits", "coefficients_sha256", "coefficients"}
        if not isinstance(record, dict) or set(record) != expected_keys:
            raise DerivationError(f"{name} kernel record changed")
        coefficients = record["coefficients"]
        if (
            record["sigma"] != sigma
            or record["radius"] != sigma * 4
            or record["q_bits"] != 30
            or not isinstance(coefficients, list)
            or len(coefficients) != 2 * record["radius"] + 1
            or any(not isinstance(value, int) or value <= 0 for value in coefficients)
            or coefficients != list(reversed(coefficients))
            or sum(coefficients) != Q30
            or sha256_bytes(_canonical_int_array(coefficients))
            != record["coefficients_sha256"]
        ):
            raise DerivationError(f"{name} literal Q30 kernel changed")

    band = derivation.get("band_composition", {})
    if band.get("g4_to_g8_gain") != 1.0 or band.get("coarse_g24_gain") != 1.0:
        raise DerivationError("fixed band gain changed")
    finalization = derivation.get("finalization", {})
    if (
        not isinstance(finalization, dict)
        or "outside the exact union of the eight v20 body supports"
        not in finalization.get("foundation_realization", "")
        or "foundation has final canvas precedence"
        not in finalization.get("restore_rule", "")
    ):
        raise DerivationError("outside-union foundation byte contract changed")
    candidates = authority["candidates"]
    records = candidates.get("records") if isinstance(candidates, dict) else None
    if (
        candidates.get("exact_count") != len(EXPECTED_CANDIDATES)
        or candidates.get("parameter_changes_forbidden") is not True
        or candidates.get("extra_candidates_forbidden") is not True
        or not isinstance(records, list)
        or len(records) != len(EXPECTED_CANDIDATES)
    ):
        raise DerivationError("four-candidate closure changed")
    for index, (record, expected) in enumerate(zip(records, EXPECTED_CANDIDATES, strict=True)):
        expected_keys = {
            "candidate_id",
            "fine_retention",
            "fine_retention_rational",
            "mid_gain",
            "mid_gain_rational",
            "g4_to_g8_gain",
            "coarse_g24_gain",
            "output_path",
        }
        if not isinstance(record, dict) or set(record) != expected_keys:
            raise DerivationError(f"candidate record {index} keys changed")
        candidate_id, fine_rational, mid_rational, output = expected
        if (
            record["candidate_id"] != candidate_id
            or record["fine_retention_rational"] != list(fine_rational)
            or record["mid_gain_rational"] != list(mid_rational)
            or record["fine_retention"] != fine_rational[0] / fine_rational[1]
            or record["mid_gain"] != mid_rational[0] / mid_rational[1]
            or record["g4_to_g8_gain"] != 1.0
            or record["coarse_g24_gain"] != 1.0
            or _safe_relative(record["output_path"], label="candidate output", output=True)
            != output
        ):
            raise DerivationError(f"candidate record {index} changed")
    cli = authority["cli_contract"]
    if (
        cli.get("default_mode") != "check"
        or cli.get("parameter_overrides") != "none"
        or cli.get("output_directory")
        != "tmp/map-production/k3-golden-v3-preregistered-four"
        or cli.get("seal_path")
        != "tmp/map-production/k3-golden-v3-preregistered-four/sealed-output-sha256.json"
        or cli.get("seal_exact_top_keys")
        != [
            "schema_id",
            "authority_sha256",
            "statistics_firewall_sha256",
            "runtime_profile_id",
            "candidate_count",
            "candidates",
        ]
        or cli.get("seal_candidate_exact_keys")
        != ["candidate_id", "path", "sha256", "bytes"]
        or "exactly one trailing LF" not in cli.get("seal_serialization", "")
        or "--compare-seals LEFT RIGHT" not in cli.get("compare_seals", "")
        or "before any evaluation or audit" not in cli.get("cross_profile_gate", "")
    ):
        raise DerivationError("CLI closure changed")


def load_authority(path: Path = AUTHORITY_PATH, *, require_frozen_sha: bool = True) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise DerivationError(f"cannot read preregistration authority: {path}") from exc
    if require_frozen_sha and sha256_bytes(payload) != AUTHORITY_SHA256:
        raise DerivationError("preregistration authority SHA-256 changed")
    authority = _load_strict_json_object(payload, label="preregistration authority")
    validate_authority(authority)
    return authority


def _opencv_distributions() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for distribution in metadata.distributions():
        raw_name = distribution.metadata.get("Name")
        if not raw_name:
            continue
        name = str(raw_name).lower().replace("_", "-")
        if name.startswith("opencv-"):
            records.append({"name": name, "version": distribution.version})
    return sorted(records, key=lambda record: (record["name"], record["version"]))


def _runtime_gate() -> str:
    cv2.setNumThreads(1)
    cv2.setRNGSeed(EXPECTED_RUNTIME["opencv_rng_seed"])
    actual_common = {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "opencv_api": cv2.__version__,
        "numpy": np.__version__,
        "pillow": PIL.__version__,
        "byteorder": sys.byteorder,
        "opencv_threads": cv2.getNumThreads(),
    }
    if actual_common != EXPECTED_RUNTIME["common"]:
        raise DerivationError(f"common runtime closure changed: {actual_common}")
    actual_profile = {
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "opencv_distributions": _opencv_distributions(),
        "opencv_build_sha256": sha256_bytes(
            cv2.getBuildInformation().encode("utf-8")
        ),
    }
    matches = [
        profile["id"]
        for profile in EXPECTED_RUNTIME["allowed_profiles"]
        if {key: profile[key] for key in actual_profile} == actual_profile
    ]
    if len(matches) != 1:
        raise DerivationError(f"runtime profile closure changed: {actual_profile}")
    return matches[0]


def source_bindings(authority: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        record["role"]: record
        for record in authority["input_policy"]["source_bindings"]
    }


def check_bound_sources(
    authority: Mapping[str, Any], *, roles: set[str] | None = None
) -> None:
    """Hash only; deliberately does not decode or reconstruct any raster."""

    for record in authority["input_policy"]["source_bindings"]:
        if roles is not None and record["role"] not in roles:
            continue
        relative = _safe_relative(record["path"], label=record["role"])
        path = ROOT / relative
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise DerivationError(f"bound source is unavailable: {relative}") from exc
        if sha256_bytes(payload) != record["sha256"]:
            raise DerivationError(f"bound source SHA-256 changed: {relative}")
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            raise DerivationError(f"bound source is not tracked: {relative}")


def _import_bound_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise DerivationError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def _as_int64(values: np.ndarray | int, *, label: str) -> np.ndarray:
    raw = np.asarray(values)
    if np.issubdtype(raw.dtype, np.bool_) or not np.issubdtype(
        raw.dtype, np.integer
    ):
        raise DerivationError(f"{label} must be an integer array")
    if np.issubdtype(raw.dtype, np.unsignedinteger) and raw.size:
        if int(raw.max()) > INT64_MAX:
            raise DerivationError(f"{label} is outside signed int64")
    try:
        converted = raw.astype(np.int64, copy=False)
    except (OverflowError, TypeError, ValueError) as exc:
        raise DerivationError(f"{label} is outside signed int64") from exc
    return converted


def _safe_magnitude(values: np.ndarray, *, label: str) -> np.ndarray:
    source = _as_int64(values, label=label)
    if source.size and bool(np.any(source == INT64_MIN)):
        raise DerivationError(f"{label} contains INT64_MIN")
    return np.where(source < 0, -source, source).astype(np.int64, copy=False)


def _checked_add_int64(
    left: np.ndarray | int, right: np.ndarray | int, *, label: str
) -> np.ndarray:
    lhs, rhs = np.broadcast_arrays(
        _as_int64(left, label=f"{label} left"),
        _as_int64(right, label=f"{label} right"),
    )
    positive = rhs > 0
    negative = rhs < 0
    if bool(np.any(lhs[positive] > INT64_MAX - rhs[positive])) or bool(
        np.any(lhs[negative] < INT64_MIN - rhs[negative])
    ):
        raise DerivationError(f"{label} would overflow signed int64")
    return (lhs + rhs).astype(np.int64, copy=False)


def _checked_subtract_int64(
    left: np.ndarray | int, right: np.ndarray | int, *, label: str
) -> np.ndarray:
    lhs, rhs = np.broadcast_arrays(
        _as_int64(left, label=f"{label} left"),
        _as_int64(right, label=f"{label} right"),
    )
    positive = rhs > 0
    negative = rhs < 0
    if bool(np.any(lhs[positive] < INT64_MIN + rhs[positive])) or bool(
        np.any(lhs[negative] > INT64_MAX + rhs[negative])
    ):
        raise DerivationError(f"{label} would overflow signed int64")
    return (lhs - rhs).astype(np.int64, copy=False)


def _checked_multiply_nonnegative_int64(
    values: np.ndarray | int, multiplier: int, *, label: str
) -> np.ndarray:
    if (
        isinstance(multiplier, bool)
        or not isinstance(multiplier, int)
        or multiplier < 0
        or multiplier > INT64_MAX
    ):
        raise DerivationError(f"{label} multiplier is outside signed int64")
    source = _as_int64(values, label=label)
    magnitude = _safe_magnitude(source, label=label)
    if multiplier and source.size and int(magnitude.max()) > INT64_MAX // multiplier:
        raise DerivationError(f"{label} would overflow signed int64")
    return (source * multiplier).astype(np.int64, copy=False)


def round_divide_ties_away(values: np.ndarray | int, denominator: int) -> np.ndarray:
    """Signed integer division rounded to nearest, ties away from zero."""

    if (
        isinstance(denominator, bool)
        or not isinstance(denominator, int)
        or denominator <= 0
        or denominator > INT64_MAX
    ):
        raise DerivationError("fixed-point denominator must be positive signed int64")
    source = _as_int64(values, label="fixed-point dividend")
    magnitude = _safe_magnitude(source, label="fixed-point dividend")
    bias = denominator // 2
    if source.size and int(magnitude.max()) > INT64_MAX - bias:
        raise DerivationError("fixed-point rounding bias would overflow signed int64")
    rounded = (magnitude + bias) // denominator
    return np.where(source < 0, -rounded, rounded).astype(np.int64)


def rational_multiply(values: np.ndarray, numerator: int, denominator: int) -> np.ndarray:
    if (
        isinstance(numerator, bool)
        or not isinstance(numerator, int)
        or numerator <= 0
        or numerator > INT64_MAX
        or isinstance(denominator, bool)
        or not isinstance(denominator, int)
        or denominator <= 0
        or denominator > INT64_MAX
    ):
        raise DerivationError("factorial gain rational changed")
    product = _checked_multiply_nonnegative_int64(
        values, numerator, label="fixed-point rational multiplication"
    )
    return round_divide_ties_away(product, denominator)


def _convolve_axis_q30(
    values: np.ndarray, coefficients: np.ndarray, axis: int
) -> np.ndarray:
    source = _as_int64(values, label="Q30 convolution input")
    coefficient_array = _as_int64(coefficients, label="Q30 coefficients")
    if (
        coefficient_array.ndim != 1
        or len(coefficient_array) % 2 != 1
        or bool(np.any(coefficient_array < 0))
        or sum(int(value) for value in coefficient_array) != Q30
    ):
        raise DerivationError("Q30 coefficient closure changed")
    magnitude = _safe_magnitude(source, label="Q30 convolution input")
    if source.size and int(magnitude.max()) > INT64_MAX // Q30:
        raise DerivationError("Q30 convolution would overflow signed int64")
    radius = len(coefficient_array) // 2
    pad = [(0, 0), (0, 0)]
    pad[axis] = (radius, radius)
    padded = np.pad(source, pad, mode="symmetric")
    accumulator = np.zeros(source.shape, dtype=np.int64)
    for offset, coefficient in enumerate(coefficient_array):
        slices = [slice(None), slice(None)]
        slices[axis] = slice(offset, offset + source.shape[axis])
        product = _checked_multiply_nonnegative_int64(
            padded[tuple(slices)],
            int(coefficient),
            label="Q30 convolution coefficient product",
        )
        accumulator = _checked_add_int64(
            accumulator, product, label="Q30 convolution accumulation"
        )
    return round_divide_ties_away(accumulator, Q30)


def q30_filter(values: np.ndarray, record: Mapping[str, Any]) -> np.ndarray:
    source = np.asarray(values)
    if (
        source.ndim != 2
        or np.issubdtype(source.dtype, np.bool_)
        or not np.issubdtype(source.dtype, np.integer)
    ):
        raise DerivationError("Q30 filter input must be a signed 2D integer array")
    source = _as_int64(source, label="Q30 filter input")
    coefficients = _as_int64(record["coefficients"], label="Q30 coefficients")
    horizontal = _convolve_axis_q30(source, coefficients, axis=1)
    return _convolve_axis_q30(horizontal, coefficients, axis=0)


def radial_bins(shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    if height < 2 or width < 2:
        raise DerivationError("radial FFT canvas is too small")
    fy = np.fft.fftfreq(height)
    fx = np.fft.rfftfreq(width)
    normalized = np.hypot(fy[:, None], fx[None, :]) / np.sqrt(0.5)
    return np.minimum(15, np.floor(16.0 * normalized).astype(np.int32))


def interpolate_type7_quantiles(values: np.ndarray, target_count: int) -> np.ndarray:
    source = np.asarray(values, dtype=np.int64)
    if source.ndim != 1 or len(source) == 0 or target_count <= 0:
        raise DerivationError("fixed CDF interpolation shape changed")
    if len(source) != 17:
        raise DerivationError("fixed CDF must contain 17 Type-7 knots")
    if target_count == 1:
        return source[8:9].copy()
    result = np.empty(target_count, dtype=np.int64)
    denominator = target_count - 1
    for target_index in range(target_count):
        position_numerator = target_index * 16
        left = position_numerator // denominator
        remainder = position_numerator % denominator
        if left >= 16:
            result[target_index] = source[16]
            continue
        weighted = _checked_add_int64(
            _checked_multiply_nonnegative_int64(
                source[left],
                denominator - remainder,
                label="Type-7 left interpolation product",
            ),
            _checked_multiply_nonnegative_int64(
                source[left + 1],
                remainder,
                label="Type-7 right interpolation product",
            ),
            label="Type-7 interpolation numerator",
        )
        result[target_index] = round_divide_ties_away(weighted, denominator).item()
    return result


def aggregate_body_statistics(statistics: Sequence[BodyStatistics]) -> BodyStatistics:
    if len(statistics) != 7:
        raise DerivationError("body-8 aggregate requires exactly bodies 1-7")
    median_stack = np.stack([record.median_lab_q16 for record in statistics], axis=0)
    median_lab = np.sort(median_stack, axis=0)[3]
    profiles = np.stack([record.radial_power_q16 for record in statistics], axis=0)
    if profiles.shape != (7, 16):
        raise DerivationError("body-8 PSD aggregation shape changed")
    radial_sum = np.zeros(16, dtype=np.int64)
    for profile in profiles:
        radial_sum = _checked_add_int64(
            radial_sum, profile, label="body-8 PSD aggregation"
        )
    radial_power = round_divide_ties_away(radial_sum, 7)
    quantile_stack = np.stack([record.quantiles_q16 for record in statistics], axis=0)
    if quantile_stack.shape != (7, 17):
        raise DerivationError("body-8 quantile aggregation shape changed")
    quantile_sum = np.zeros(17, dtype=np.int64)
    for quantile_record in quantile_stack:
        quantile_sum = _checked_add_int64(
            quantile_sum, quantile_record, label="body-8 quantile aggregation"
        )
    quantiles = round_divide_ties_away(quantile_sum, 7)
    return BodyStatistics(
        median_lab_q16=median_lab.astype(np.int64),
        radial_power_q16=radial_power,
        quantiles_q16=quantiles,
    )


def phase_seed(seed_record: Mapping[str, Any]) -> int:
    digest = bytes.fromhex(seed_record["sha256"])
    return int.from_bytes(digest[:8], "big", signed=False)


def synthesize_statistical_phase(
    shape: tuple[int, int],
    body: np.ndarray,
    statistics: BodyStatistics,
    seed: int,
) -> np.ndarray:
    mask = np.asarray(body, dtype=bool)
    if mask.shape != shape:
        raise DerivationError("phase synthesis support changed")
    distribution = interpolate_type7_quantiles(
        statistics.quantiles_q16, int(mask.sum())
    )
    bins = radial_bins(shape)
    if int(bins.max()) >= len(statistics.radial_power_q16):
        raise DerivationError("radial power profile is incomplete")
    rng = np.random.Generator(np.random.PCG64(seed))
    phase_source = np.fft.rfft2(rng.standard_normal(shape, dtype=np.float64))
    magnitudes = np.abs(phase_source)
    unit_phase = np.divide(
        phase_source,
        magnitudes,
        out=np.ones_like(phase_source, dtype=np.complex128),
        where=magnitudes != 0.0,
    )
    hermitian_weight = np.full(bins.shape, 2, dtype=np.int64)
    hermitian_weight[:, 0] = 1
    if shape[1] % 2 == 0:
        hermitian_weight[:, -1] = 1
    hermitian_weight[0, 0] = 0
    bin_weight = np.bincount(
        bins.ravel(), weights=hermitian_weight.ravel(), minlength=16
    )
    normalized_bin_power = np.maximum(
        statistics.radial_power_q16.astype(np.float64) / float(Q16), 0.0
    )
    per_coefficient = normalized_bin_power[bins] / np.maximum(bin_weight[bins], 1.0)
    spectrum = np.sqrt(per_coefficient) * unit_phase
    spectrum[0, 0] = 0.0
    surrogate = np.fft.irfft2(spectrum, s=shape).astype(np.float64)
    local = surrogate[mask]
    order = np.argsort(local, kind="mergesort")
    mapped = np.empty_like(local)
    mapped[order] = distribution
    result = np.zeros(shape, dtype=np.int64)
    result[mask] = mapped
    return result


def phase_bands(
    surrogate: np.ndarray, kernels: Mapping[str, Mapping[str, Any]]
) -> PhaseBands:
    g4 = q30_filter(surrogate, kernels["G4"])
    g8 = q30_filter(surrogate, kernels["G8"])
    g24 = q30_filter(surrogate, kernels["G24"])
    return PhaseBands(
        sub4=_checked_subtract_int64(surrogate, g4, label="X minus G4X"),
        g4_to_g8=_checked_subtract_int64(g4, g8, label="G4X minus G8X"),
        g8_to_g24=_checked_subtract_int64(g8, g24, label="G8X minus G24X"),
    )


def exact_luma_equation_q16(
    median_q16: int,
    bands: PhaseBands,
    coarse_g24_q16: np.ndarray,
    fine_rational: tuple[int, int],
    mid_rational: tuple[int, int],
) -> np.ndarray:
    fine = rational_multiply(bands.sub4, *fine_rational)
    mid = rational_multiply(bands.g8_to_g24, *mid_rational)
    result = np.full(
        bands.sub4.shape,
        _as_int64(median_q16, label="body median").item(),
        dtype=np.int64,
    )
    result = _checked_add_int64(result, fine, label="median plus fine band")
    result = _checked_add_int64(
        result, bands.g4_to_g8, label="plus G4-to-G8 band"
    )
    result = _checked_add_int64(result, mid, label="plus G8-to-G24 band")
    result = _checked_add_int64(
        result, coarse_g24_q16, label="plus coarse G24 D20 field"
    )
    return result


def q16_to_u8(values: np.ndarray) -> np.ndarray:
    rounded = round_divide_ties_away(np.asarray(values, dtype=np.int64), Q16)
    return np.clip(rounded, 0, 255).astype(np.uint8)


def restore_v18_locks(
    candidate: np.ndarray,
    baseline: np.ndarray,
    permission: np.ndarray,
    protected: np.ndarray,
    road_calm: np.ndarray,
    alpha_zero: np.ndarray,
) -> np.ndarray:
    output = np.asarray(candidate).copy()
    base = np.asarray(baseline)
    if output.shape != base.shape or output.ndim != 3 or output.shape[2] != 3:
        raise DerivationError("lock restoration RGB shapes changed")
    masks = [np.asarray(value, dtype=bool) for value in (permission, protected, road_calm, alpha_zero)]
    if any(value.shape != output.shape[:2] for value in masks):
        raise DerivationError("lock restoration mask shapes changed")
    locked = ~masks[0] | masks[1] | masks[2] | masks[3]
    output[locked] = base[locked]
    if not np.array_equal(output[locked], base[locked]):
        raise DerivationError("v18 byte restoration failed")
    return output


def finalize_candidate_rgb(
    candidate: np.ndarray,
    foundation: np.ndarray,
    baseline: np.ndarray,
    permission: np.ndarray,
    protected: np.ndarray,
    road_calm: np.ndarray,
    alpha_zero: np.ndarray,
    v20_masks: Sequence[np.ndarray],
) -> np.ndarray:
    """Apply v18 locks, then restore every outside-body foundation RGB byte."""

    output = np.asarray(candidate)
    foundation_rgb = np.asarray(foundation)
    baseline_rgb = np.asarray(baseline)
    if (
        output.shape != foundation_rgb.shape
        or output.shape != baseline_rgb.shape
        or output.ndim != 3
        or output.shape[2] != 3
    ):
        raise DerivationError("candidate/foundation/v18 RGB shapes changed")
    if len(v20_masks) != len(BODY_VALUES):
        raise DerivationError("exact v20 body-union cardinality changed")
    supports = [np.asarray(mask, dtype=bool) for mask in v20_masks]
    if any(mask.shape != output.shape[:2] for mask in supports):
        raise DerivationError("exact v20 body-union support shape changed")
    support_count = np.zeros(output.shape[:2], dtype=np.uint8)
    for support in supports:
        support_count += support.astype(np.uint8)
    if bool(np.any(support_count > 1)):
        raise DerivationError("v20 body supports overlap")
    body_union = support_count == 1

    lock_masks = [
        np.asarray(value, dtype=bool)
        for value in (permission, protected, road_calm, alpha_zero)
    ]
    if any(mask.shape != output.shape[:2] for mask in lock_masks):
        raise DerivationError("finalization lock-mask shape changed")
    locked = ~lock_masks[0] | lock_masks[1] | lock_masks[2] | lock_masks[3]
    outside_union = ~body_union
    locked_outside = locked & outside_union
    if not np.array_equal(
        baseline_rgb[locked_outside], foundation_rgb[locked_outside]
    ):
        raise DerivationError(
            "v18 and foundation disagree on a locked pixel outside v20 body union"
        )

    finalized = restore_v18_locks(
        output,
        baseline_rgb,
        lock_masks[0],
        lock_masks[1],
        lock_masks[2],
        lock_masks[3],
    )
    finalized[outside_union] = foundation_rgb[outside_union]
    if not np.array_equal(finalized[outside_union], foundation_rgb[outside_union]):
        raise DerivationError("outside-union foundation RGB byte restoration failed")
    if not np.array_equal(finalized[locked], baseline_rgb[locked]):
        raise DerivationError("final v18 lock-byte restoration failed")
    return finalized


def _historical_systems(
    marks: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], Mapping[str, Any]]:
    """Extract only the renderer parameters frozen in the marks authority."""

    mark_systems = marks.get("systems")
    styles = marks.get("styles")
    if not isinstance(mark_systems, list) or len(mark_systems) != 8:
        raise DerivationError("historical dev20 parameter table changed")
    systems: list[dict[str, Any]] = []
    mark_keys = {
        "body_id",
        "value",
        "base_l_delta",
        "base_a_delta",
        "base_b_delta",
        "crest",
        "spurs",
        "valleys",
        "saddle_gap",
        "relief_scale",
        "mass_anchors",
        "noise_salt",
        "noise_major_xy",
        "noise_minor_xy",
        "noise_aspect",
    }
    for index, mark in enumerate(mark_systems):
        if not isinstance(mark, dict):
            raise DerivationError("historical dev20 system record changed")
        if mark.get("body_id") != f"body-{index:02d}":
            raise DerivationError("historical dev20 body order changed")
        system = {key: mark[key] for key in mark_keys}
        systems.append(system)
    if not isinstance(styles, dict):
        raise DerivationError("historical dev20 styles changed")
    return systems, styles


def _apply_dev20_volume_without_diagnostics(
    renderer: ModuleType,
    lab: np.ndarray,
    body: np.ndarray,
    system: Mapping[str, Any],
    styles: Mapping[str, Any],
) -> None:
    """Replay the v21 volume pixels while omitting every diagnostic calculation."""

    ys, xs = np.nonzero(body)
    if len(xs) == 0:
        raise DerivationError("dev20 volume support is empty")
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    local_body = body[y0:y1, x0:x1]
    grid_y, grid_x = np.mgrid[y0:y1, x0:x1]
    grid_x = grid_x.astype(np.float64)
    grid_y = grid_y.astype(np.float64)
    distance_inside = cv2.distanceTransform(
        local_body.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE
    ).astype(np.float64)
    mass_context = np.zeros(local_body.shape, dtype=np.float64)
    for anchor in system["mass_anchors"]:
        mass_context += renderer._wendland_mass(grid_x, grid_y, anchor)

    volume = styles["volume"]
    center_x = (x0 + x1 - 1) * 0.5
    center_y = (y0 + y1 - 1) * 0.5
    delta_x = grid_x - center_x
    delta_y = grid_y - center_y
    noise_major = np.asarray(system["noise_major_xy"], dtype=np.float64)
    noise_minor = np.asarray(system["noise_minor_xy"], dtype=np.float64)
    noise_x = delta_x * noise_major[0] + delta_y * noise_major[1]
    noise_y = (delta_x * noise_minor[0] + delta_y * noise_minor[1]) * float(
        system["noise_aspect"]
    )
    salt = int(system["noise_salt"])
    warp_scale = float(volume["domain_warp"])
    warped_x = noise_x + warp_scale * renderer._value_noise(
        noise_x, noise_y, wavelength=72, salt=salt + 4001
    )
    warped_y = noise_y + warp_scale * renderer._value_noise(
        noise_x, noise_y, wavelength=72, salt=salt + 8009
    )
    shade_terrain = np.zeros(local_body.shape, dtype=np.float64)
    for band_index, (wavelength, amplitude, frame) in enumerate(
        zip(
            volume["noise_wavelengths"],
            volume["noise_amplitudes"],
            renderer.OCTAVE_FRAMES,
            strict=True,
        )
    ):
        octave_major = np.asarray(frame[0], dtype=np.float64)
        octave_minor = np.asarray(frame[1], dtype=np.float64)
        octave_x = warped_x * octave_major[0] + warped_y * octave_major[1]
        octave_y = warped_x * octave_minor[0] + warped_y * octave_minor[1]
        shade_terrain += float(amplitude) * renderer._value_noise(
            octave_x,
            octave_y,
            wavelength=int(wavelength),
            salt=salt + band_index * 997,
        )
    field_quantum = float(volume["field_quantum"])
    shade_terrain = np.rint(shade_terrain * field_quantum) / field_quantum
    terrain = float(volume["mass_gain"]) * mass_context + shade_terrain
    terrain = np.rint(terrain * field_quantum) / field_quantum
    ordered = np.sort(terrain[local_body])
    p10 = float(ordered[int((len(ordered) - 1) * 0.10)])
    p90 = float(ordered[int((len(ordered) - 1) * 0.90)])
    span = p90 - p10
    if not np.isfinite(span) or span <= 0.0:
        raise DerivationError("dev20 terrain normalization collapsed")
    normalized_elevation = (terrain - (p10 + p90) * 0.5) / span
    shade_ordered = np.sort(shade_terrain[local_body])
    shade_p10 = float(shade_ordered[int((len(shade_ordered) - 1) * 0.10)])
    shade_p90 = float(shade_ordered[int((len(shade_ordered) - 1) * 0.90)])
    shade_span = shade_p90 - shade_p10
    if not np.isfinite(shade_span) or shade_span <= 0.0:
        raise DerivationError("dev20 shade normalization collapsed")
    normalized_shade = shade_terrain - (shade_p10 + shade_p90) * 0.5
    normalized_shade /= shade_span
    gradient_x, gradient_y = renderer._finite_gradient(normalized_shade)
    light = np.asarray(styles["lighting"]["direction_xyz"], dtype=np.float64)
    light /= float(np.linalg.norm(light))
    height_scale = float(volume["height_scale"])
    normal_x = -gradient_x * height_scale
    normal_y = -gradient_y * height_scale
    normal_z = np.ones_like(terrain, dtype=np.float64)
    normal_length = np.sqrt(
        normal_x * normal_x + normal_y * normal_y + normal_z * normal_z
    )
    lambert = (
        normal_x * light[0] + normal_y * light[1] + normal_z * light[2]
    ) / normal_length
    hillshade = (lambert - light[2]) * float(volume["hillshade_exposure"])
    hillshade *= float(system["relief_scale"])
    elevation = float(volume["elevation_gain"]) * np.tanh(normalized_elevation)
    limit = float(volume["delta_limit"])
    relief = limit * np.tanh((elevation + hillshade) / limit)
    edge = renderer._smoothstep(
        (distance_inside - float(volume["edge_zero"]))
        / (float(volume["edge_full"]) - float(volume["edge_zero"]))
    )
    relief *= edge
    shade_quantum = float(volume["shade_quantum"])
    relief = np.rint(relief * shade_quantum) / shade_quantum
    local_lab = lab[y0:y1, x0:x1]
    for channel, key in enumerate(("base_l_delta", "base_a_delta", "base_b_delta")):
        delta = float(system[key]) * edge
        local_lab[..., channel][local_body] += delta[local_body].astype(np.float32)
    local_lab[..., 0][local_body] += relief[local_body].astype(np.float32)


def reconstruct_dev20_luma_delta(
    renderer: ModuleType,
    baseline: np.ndarray,
    foundation: np.ndarray,
    v19_control: np.ndarray,
    v20_control: np.ndarray,
    marks: Mapping[str, Any],
    permission: np.ndarray,
    protected: np.ndarray,
    road_calm: np.ndarray,
    authority: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray], list[np.ndarray]]:
    """Summary-free in-memory dev20 replay; returns no diagnostic record."""

    renderer._runtime_gate()
    renderer._validate_marks(marks)
    derived = renderer.derive_v20_body_control(v19_control, marks)
    if not np.array_equal(derived, v20_control):
        raise DerivationError("v20 replacement support changed")
    v20_masks = [v20_control == value for value in BODY_VALUES]
    v19_masks = [v19_control == value for value in BODY_VALUES]
    if any(not np.array_equal(old, new) for old, new in zip(v19_masks[:7], v20_masks[:7], strict=True)):
        raise DerivationError("body 1-7 coverage anchors changed")
    if np.any(v20_masks[-1] & (~permission | protected | road_calm)):
        raise DerivationError("body-8 replacement escaped editable support")
    systems, styles = _historical_systems(marks)
    target = cv2.cvtColor(foundation, cv2.COLOR_RGB2LAB).astype(np.float32)
    for system, body in zip(systems, v20_masks, strict=True):
        _apply_dev20_volume_without_diagnostics(renderer, target, body, system, styles)
    encoded = np.clip(np.rint(target), 0, 255).astype(np.uint8)
    dev20 = cv2.cvtColor(encoded, cv2.COLOR_LAB2RGB)
    dev20[~permission] = baseline[~permission]
    locked = protected | road_calm
    dev20[locked] = baseline[locked]
    expected = authority["derivation"]["dev20_coarse_authority"]["expected_pixel_sha256"]
    if array_sha256(dev20) != expected:
        raise DerivationError("summary-free dev20 pixel reconstruction changed")
    final_l = cv2.cvtColor(dev20, cv2.COLOR_RGB2LAB)[..., 0].astype(np.int32)
    foundation_l = cv2.cvtColor(foundation, cv2.COLOR_RGB2LAB)[..., 0].astype(np.int32)
    return dev20, final_l - foundation_l, v19_masks, v20_masks


def _decode_bound_mask(path: Path, shape: tuple[int, int]) -> np.ndarray:
    try:
        with Image.open(path) as image:
            if image.mode != "L" or image.size != (shape[1], shape[0]):
                raise DerivationError(f"mask format changed: {path}")
            values = np.asarray(image, dtype=np.uint8).copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise DerivationError(f"cannot decode bound mask: {path}") from exc
    if set(int(value) for value in np.unique(values)) != {0, 255}:
        raise DerivationError(f"bound mask is not binary: {path}")
    return values == 255


def _decode_bound_rgb(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as image:
            if image.mode != "RGB":
                raise DerivationError(f"RGB source mode changed: {path}")
            return np.asarray(image, dtype=np.uint8).copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise DerivationError(f"cannot decode bound RGB source: {path}") from exc


def _decode_bound_gray(path: Path, shape: tuple[int, int]) -> np.ndarray:
    try:
        with Image.open(path) as image:
            if image.mode != "L" or image.size != (shape[1], shape[0]):
                raise DerivationError(f"indexed control format changed: {path}")
            return np.asarray(image, dtype=np.uint8).copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise DerivationError(f"cannot decode indexed control: {path}") from exc


def _load_bound_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise DerivationError(f"cannot load {label}: {path}") from exc
    return _load_strict_json_object(payload, label=label)


def _signed_q16_vector(value: Any, length: int, *, label: str) -> list[int]:
    if not isinstance(value, list) or len(value) != length:
        raise DerivationError(f"{label} must contain exactly {length} entries")
    result: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int):
            raise DerivationError(f"{label}[{index}] must be a non-bool JSON integer")
        if item < Q16_MIN or item > Q16_MAX:
            raise DerivationError(f"{label}[{index}] is outside signed Q16.16")
        result.append(item)
    return result


def parse_statistics_firewall_payload(
    payload: bytes,
    authority: Mapping[str, Any],
    *,
    expected_sha256: str | None = None,
) -> list[BodyStatistics]:
    """Parse only extractor-canonical one-dimensional statistics."""

    if expected_sha256 is not None:
        if SHA256_PATTERN.fullmatch(expected_sha256) is None:
            raise DerivationError("statistics firewall expected SHA-256 is invalid")
        if sha256_bytes(payload) != expected_sha256:
            raise DerivationError("statistics firewall SHA-256 changed")
    artifact = _load_strict_json_object(payload, label="statistics firewall")
    config = authority["derivation"]["v19_statistical_authority"]
    schema = config["artifact_schema"]
    if set(artifact) != set(schema["exact_top_keys"]):
        raise DerivationError("statistics firewall top-level key set changed")
    if (
        artifact["schema_id"] != schema["schema_id"]
        or artifact["record_id"] != schema["record_id"]
    ):
        raise DerivationError("statistics firewall identity changed")

    source_hashes = artifact["source_hashes"]
    expected_source_hashes = schema["source_hashes_expected"]
    if (
        not isinstance(source_hashes, dict)
        or set(source_hashes) != set(schema["source_hashes_exact_keys"])
        or set(source_hashes) != set(expected_source_hashes)
        or any(
            not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None
            for value in source_hashes.values()
        )
        or source_hashes != expected_source_hashes
    ):
        raise DerivationError("statistics firewall six-source identity changed")
    bindings = source_bindings(authority)
    source_role_map = {
        "v19_renderer_sha256": "v19-byte-closed-replay-module",
        "v19_replay_contract_sha256": "v19-byte-closed-replay-contract",
        "v19_statistics_extractor_sha256": (
            "v19-statistics-firewall-extractor-provenance-only"
        ),
    }
    for source_key, role in source_role_map.items():
        if source_hashes[source_key] != bindings[role]["sha256"]:
            raise DerivationError(
                f"statistics firewall {source_key} disagrees with source binding"
            )

    body_statistics = artifact["body_statistics"]
    body_keys = {str(value) for value in BODY_VALUES[:7]}
    if not isinstance(body_statistics, dict) or set(body_statistics) != body_keys:
        raise DerivationError("statistics firewall body key set changed")
    if body_keys != set(schema["body_statistics_exact_keys"]):
        raise DerivationError("authority body-statistics key set changed")
    expected_record_keys = set(schema["body_record_exact_keys"])
    expected_supports = authority["derivation"]["coverage_anchors"][
        "bodies_1_through_7_support_sha256_by_control_value"
    ]
    if expected_supports != EXPECTED_SUPPORT_SHA256:
        raise DerivationError("authority support SHA-256 table changed")
    records: list[BodyStatistics] = []
    for body_value in BODY_VALUES[:7]:
        body_key = str(body_value)
        record = body_statistics[body_key]
        label = f"statistics firewall body {body_key}"
        if not isinstance(record, dict) or set(record) != expected_record_keys:
            raise DerivationError(f"{label} key set changed")
        support_sha256 = record["support_sha256"]
        if (
            not isinstance(support_sha256, str)
            or SHA256_PATTERN.fullmatch(support_sha256) is None
            or support_sha256 != expected_supports[body_key]
        ):
            raise DerivationError(f"{label} support SHA-256 changed")
        median = _signed_q16_vector(
            record["median_lab_q16"], 3, label=f"{label} median_lab_q16"
        )
        if any(channel < 0 or channel > 255 * Q16 for channel in median):
            raise DerivationError(f"{label} median_lab_q16 is outside encoded Lab")
        radial = _signed_q16_vector(
            record["radial_power_q16"],
            int(schema["radial_bin_count"]),
            label=f"{label} radial_power_q16",
        )
        if any(value < 0 or value > Q16 for value in radial):
            raise DerivationError(f"{label} radial_power_q16 is outside [0,1]")
        radial_sum = sum(radial)
        if radial_sum != 0 and abs(radial_sum - Q16) > len(radial) // 2:
            raise DerivationError(
                f"{label} radial_power_q16 is neither zero nor normalized"
            )
        quantiles = _signed_q16_vector(
            record["quantiles_q16"],
            int(schema["quantile_count"]),
            label=f"{label} quantiles_q16",
        )
        if quantiles != sorted(quantiles):
            raise DerivationError(f"{label} quantiles_q16 is not monotone")
        records.append(
            BodyStatistics(
                median_lab_q16=np.asarray(median, dtype=np.int64),
                radial_power_q16=np.asarray(radial, dtype=np.int64),
                quantiles_q16=np.asarray(quantiles, dtype=np.int64),
            )
        )
    if canonical_statistics_json(artifact) != payload:
        raise DerivationError(
            "statistics firewall bytes are not extractor-canonical sort_keys JSON"
        )
    return records


def load_statistics_firewall(authority: Mapping[str, Any]) -> list[BodyStatistics]:
    config = authority["derivation"]["v19_statistical_authority"]
    digest = config["future_artifact_sha256"]
    if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
        raise DerivationError(
            "statistics firewall is intentionally unsealed; --emit is unavailable"
        )
    path = ROOT / _safe_relative(
        config["future_artifact_path"], label="statistics firewall"
    )
    if path.is_symlink() or not path.is_file():
        raise DerivationError("sealed statistics firewall must be a regular file")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise DerivationError("sealed statistics firewall is unavailable") from exc
    return parse_statistics_firewall_payload(
        payload, authority, expected_sha256=digest
    )


def body_crop(body: np.ndarray, padding: int = 96) -> tuple[slice, slice, np.ndarray]:
    mask = np.asarray(body, dtype=bool)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0 or padding != 96:
        raise DerivationError("deterministic body crop changed")
    y0 = max(0, int(ys.min()) - padding)
    y1 = min(mask.shape[0], int(ys.max()) + 1 + padding)
    x0 = max(0, int(xs.min()) - padding)
    x1 = min(mask.shape[1], int(xs.max()) + 1 + padding)
    return slice(y0, y1), slice(x0, x1), mask[y0:y1, x0:x1]


def phase_support_crop(body: np.ndarray) -> np.ndarray:
    mask = np.asarray(body, dtype=bool)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise DerivationError("phase support is empty")
    tight = mask[int(ys.min()) : int(ys.max()) + 1, int(xs.min()) : int(xs.max()) + 1]
    return np.pad(
        tight, ((96, 96), (96, 96)), mode="constant", constant_values=False
    )


def _validate_firewall_supports(
    authority: Mapping[str, Any],
    statistics: Sequence[BodyStatistics],
    v19_masks: Sequence[np.ndarray],
) -> None:
    expected_supports = authority["derivation"]["coverage_anchors"][
        "bodies_1_through_7_support_sha256_by_control_value"
    ]
    for value, mask in zip(BODY_VALUES[:7], v19_masks[:7], strict=True):
        expected = expected_supports[str(value)]
        if array_sha256(mask.astype(np.uint8)) != expected:
            raise DerivationError(f"body {value} firewall support SHA-256 changed")
    if len(statistics) != 7:
        raise DerivationError("statistics firewall exported body 255")


def build_payloads(authority: Mapping[str, Any]) -> list[tuple[Path, bytes]]:
    """Construct exactly four payloads in memory.  Does not write or evaluate."""

    statistics = load_statistics_firewall(authority)
    bindings = source_bindings(authority)
    renderer = _import_bound_module(
        "golden_v3_four_candidate_v21_bound",
        ROOT / bindings["v21-dev20-renderer-algorithm"]["path"],
    )
    baseline = _decode_bound_rgb(ROOT / bindings["v18-byte-authority"]["path"])
    foundation = _decode_bound_rgb(
        ROOT / bindings["v21-foundation-v19-canonical"]["path"]
    )
    if baseline.shape != foundation.shape:
        raise DerivationError("v18/foundation canvas changed")
    shape = baseline.shape[:2]
    v19_control = _decode_bound_gray(
        ROOT / bindings["v19-body-control"]["path"], shape
    )
    v20_control = _decode_bound_gray(
        ROOT / bindings["v20-replacement-body-control"]["path"], shape
    )
    marks = _load_bound_json(
        ROOT / bindings["v21-dev20-ridge-marks"]["path"], label="dev20 marks"
    )
    permission = _decode_bound_mask(ROOT / bindings["permission-mask"]["path"], shape)
    protected = _decode_bound_mask(ROOT / bindings["protected-mask"]["path"], shape)
    road_calm = _decode_bound_mask(ROOT / bindings["road-calm-mask"]["path"], shape)
    alpha_zero = _decode_bound_mask(ROOT / bindings["alpha-zero-mask"]["path"], shape)
    _, d20, v19_masks, v20_masks = reconstruct_dev20_luma_delta(
        renderer,
        baseline,
        foundation,
        v19_control,
        v20_control,
        marks,
        permission,
        protected,
        road_calm,
        authority,
    )
    _validate_firewall_supports(authority, statistics, v19_masks)
    statistics = list(statistics)
    statistics.append(aggregate_body_statistics(statistics))
    kernels = authority["derivation"]["fixed_filters"]["kernels"]
    seeds = authority["derivation"]["phase_synthesis"]["seeds"]
    prepared: list[tuple[np.ndarray, BodyStatistics, PhaseBands, np.ndarray]] = []
    for index, body in enumerate(v20_masks):
        phase_body = phase_support_crop(body)
        surrogate = synthesize_statistical_phase(
            phase_body.shape,
            phase_body,
            statistics[index],
            phase_seed(seeds[index]),
        )
        full_bands = phase_bands(surrogate, kernels)
        sampled_bands = PhaseBands(
            sub4=full_bands.sub4[phase_body],
            g4_to_g8=full_bands.g4_to_g8[phase_body],
            g8_to_g24=full_bands.g8_to_g24[phase_body],
        )
        d20_y, d20_x, d20_body = body_crop(body, padding=96)
        local_delta = np.zeros(d20_body.shape, dtype=np.int64)
        local_delta[d20_body] = d20[d20_y, d20_x][d20_body].astype(np.int64) * Q16
        coarse = q30_filter(local_delta, kernels["G24"])
        prepared.append((body, statistics[index], sampled_bands, coarse[d20_body]))
    foundation_lab = cv2.cvtColor(foundation, cv2.COLOR_RGB2LAB)
    payloads: list[tuple[Path, bytes]] = []
    for record in authority["candidates"]["records"]:
        candidate_lab_q16 = foundation_lab.astype(np.int64) * Q16
        fine = tuple(int(value) for value in record["fine_retention_rational"])
        mid = tuple(int(value) for value in record["mid_gain_rational"])
        for body, stats, bands, coarse in prepared:
            y_q16 = exact_luma_equation_q16(
                int(stats.median_lab_q16[0]), bands, coarse, fine, mid
            )
            candidate_lab_q16[..., 0][body] = y_q16
            candidate_lab_q16[..., 1][body] = int(stats.median_lab_q16[1])
            candidate_lab_q16[..., 2][body] = int(stats.median_lab_q16[2])
        encoded_lab = q16_to_u8(candidate_lab_q16)
        candidate = cv2.cvtColor(encoded_lab, cv2.COLOR_LAB2RGB)
        candidate = finalize_candidate_rgb(
            candidate,
            foundation,
            baseline,
            permission,
            protected,
            road_calm,
            alpha_zero,
            v20_masks,
        )
        payloads.append((ROOT / record["output_path"], renderer._rgb_png(candidate)))
    if len(payloads) != 4 or len({path for path, _ in payloads}) != 4:
        raise DerivationError("payload closure changed")
    return payloads


def publish_payloads_exclusive(
    authority: Mapping[str, Any],
    payloads: Sequence[tuple[Path, bytes]],
    *,
    runtime_profile_id: str,
    root: Path = ROOT,
) -> None:
    """Reserve the final directory once, then exclusively create the sealed set."""

    cli = authority["cli_contract"]
    root = Path(root)
    output_directory = root / _safe_relative(
        cli["output_directory"], label="output directory", output=True
    )
    candidate_records = authority["candidates"]["records"]
    allowed_profile_ids = {
        profile["id"] for profile in authority["runtime"]["allowed_profiles"]
    }
    if (
        not isinstance(runtime_profile_id, str)
        or runtime_profile_id not in allowed_profile_ids
    ):
        raise DerivationError("output seal runtime profile is not allowed")
    outputs = [
        root
        / _safe_relative(
            record["output_path"], label="candidate output", output=True
        )
        for record in candidate_records
    ]
    payload_list = list(payloads)
    if len(payload_list) != 4 or [path for path, _ in payload_list] != outputs:
        raise DerivationError("payload output order changed")
    if any(path.parent != output_directory for path in outputs):
        raise DerivationError("candidate output escaped fixed final directory")
    if len(set(outputs)) != 4:
        raise DerivationError("candidate output paths are not unique")
    seal_path = root / _safe_relative(
        cli["seal_path"], label="output seal", output=True
    )
    if seal_path.parent != output_directory or seal_path in outputs:
        raise DerivationError("output seal escaped fixed final directory")

    seal_records: list[dict[str, Any]] = []
    for record, (path, payload) in zip(
        candidate_records, payload_list, strict=True
    ):
        if not isinstance(payload, bytes):
            raise DerivationError("candidate payload must be immutable bytes")
        seal_records.append(
            {
                "candidate_id": record["candidate_id"],
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
            }
        )
    seal = {
        "schema_id": "sstory.k3.golden-v3.four-candidate-output-seal.v1",
        "authority_sha256": AUTHORITY_SHA256,
        "statistics_firewall_sha256": authority["derivation"][
            "v19_statistical_authority"
        ]["future_artifact_sha256"],
        "runtime_profile_id": runtime_profile_id,
        "candidate_count": 4,
        "candidates": seal_records,
    }
    if list(seal) != cli["seal_exact_top_keys"]:
        raise DerivationError("output seal schema changed")
    seal_payload = canonical_output_seal_json(seal)
    validate_output_seal_payload(seal_payload, authority)

    output_directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_directory.mkdir()
    except FileExistsError as exc:
        raise DerivationError(
            "refusing emit: final directory reservation already exists"
        ) from exc
    except OSError as exc:
        raise DerivationError("final directory reservation failed") from exc

    for path, payload in payload_list:
        try:
            with path.open("xb") as stream:
                stream.write(payload)
        except OSError as exc:
            raise DerivationError(
                f"exclusive candidate publication failed: {path.name}"
            ) from exc
        if path.read_bytes() != payload:
            raise DerivationError(f"published candidate bytes changed: {path.name}")
    try:
        with seal_path.open("xb") as stream:
            stream.write(seal_payload)
    except OSError as exc:
        raise DerivationError("exclusive output-seal publication failed") from exc
    if seal_path.read_bytes() != seal_payload:
        raise DerivationError("published output seal bytes changed")


def canonical_output_seal_json(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DerivationError(f"output seal is not canonical JSON data: {exc}") from exc
    return (rendered + "\n").encode("utf-8")


def validate_output_seal_payload(
    payload: bytes, authority: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate one seal without opening any candidate PNG."""

    seal = _load_strict_json_object(payload, label="cross-profile output seal")
    cli = authority["cli_contract"]
    if list(seal) != cli["seal_exact_top_keys"]:
        raise DerivationError("output seal top-level schema/order changed")
    if (
        seal["schema_id"]
        != "sstory.k3.golden-v3.four-candidate-output-seal.v1"
        or seal["authority_sha256"] != AUTHORITY_SHA256
    ):
        raise DerivationError("output seal authority identity changed")
    statistics_sha256 = authority["derivation"]["v19_statistical_authority"][
        "future_artifact_sha256"
    ]
    if (
        not isinstance(statistics_sha256, str)
        or SHA256_PATTERN.fullmatch(statistics_sha256) is None
        or seal["statistics_firewall_sha256"] != statistics_sha256
    ):
        raise DerivationError("output seal statistics identity changed")
    allowed_profile_ids = {
        profile["id"] for profile in authority["runtime"]["allowed_profiles"]
    }
    if (
        not isinstance(seal["runtime_profile_id"], str)
        or seal["runtime_profile_id"] not in allowed_profile_ids
    ):
        raise DerivationError("output seal runtime profile is not allowed")
    sealed_candidates = seal["candidates"]
    expected_candidates = authority["candidates"]["records"]
    if (
        isinstance(seal["candidate_count"], bool)
        or not isinstance(seal["candidate_count"], int)
        or seal["candidate_count"] != 4
        or not isinstance(sealed_candidates, list)
        or len(sealed_candidates) != 4
    ):
        raise DerivationError("output seal candidate count changed")
    for index, (sealed, expected) in enumerate(
        zip(sealed_candidates, expected_candidates, strict=True)
    ):
        if (
            not isinstance(sealed, dict)
            or list(sealed) != cli["seal_candidate_exact_keys"]
            or sealed["candidate_id"] != expected["candidate_id"]
            or sealed["path"] != expected["output_path"]
            or not isinstance(sealed["sha256"], str)
            or SHA256_PATTERN.fullmatch(sealed["sha256"]) is None
            or isinstance(sealed["bytes"], bool)
            or not isinstance(sealed["bytes"], int)
            or sealed["bytes"] <= 0
        ):
            raise DerivationError(f"output seal candidate {index} changed")
    if canonical_output_seal_json(seal) != payload:
        raise DerivationError("output seal bytes are not canonical")
    return seal


def _load_output_seal(path: Path, authority: Mapping[str, Any]) -> dict[str, Any]:
    manifest = Path(path)
    if manifest.is_symlink() or not manifest.is_file():
        raise DerivationError("cross-profile seal must be a regular non-symlink file")
    try:
        payload = manifest.read_bytes()
    except OSError as exc:
        raise DerivationError(f"cannot read cross-profile seal: {manifest}") from exc
    return validate_output_seal_payload(payload, authority)


def compare_profile_seals(
    authority: Mapping[str, Any], left_path: Path, right_path: Path
) -> tuple[str, str]:
    """Compare exactly two manifests; never decode or inspect a PNG."""

    left = _load_output_seal(left_path, authority)
    right = _load_output_seal(right_path, authority)
    left_profile = left["runtime_profile_id"]
    right_profile = right["runtime_profile_id"]
    if left_profile == right_profile:
        raise DerivationError("cross-profile seals must name distinct runtime profiles")
    comparable_keys = (
        "schema_id",
        "authority_sha256",
        "statistics_firewall_sha256",
        "candidate_count",
        "candidates",
    )
    if any(left[key] != right[key] for key in comparable_keys):
        raise DerivationError(
            "cross-profile four-candidate PNG payload hashes/bytes differ"
        )
    return left_profile, right_profile


def emit(authority: Mapping[str, Any], runtime_profile_id: str) -> None:
    payloads = build_payloads(authority)
    publish_payloads_exclusive(
        authority, payloads, runtime_profile_id=runtime_profile_id
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="validate the fixed plan and source hashes without raster decode/replay",
    )
    mode.add_argument(
        "--emit",
        action="store_true",
        help="explicitly emit exactly the four preregistered non-overwriting PNGs",
    )
    mode.add_argument(
        "--compare-seals",
        nargs=2,
        metavar=("LEFT", "RIGHT"),
        type=Path,
        help="compare two profile seals without opening candidate PNGs",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        authority = load_authority()
        runtime_profile_id = _runtime_gate()
        if args.emit:
            allowed = set(
                authority["input_policy"]["candidate_generator_read_allowlist_roles"]
            )
            allowed.discard("sealed-v19-statistics-firewall")
            check_bound_sources(authority, roles=allowed)
            emit(authority, runtime_profile_id)
            print("emitted exactly four preregistered candidates; no audit was run")
        elif args.compare_seals is not None:
            left_profile, right_profile = compare_profile_seals(
                authority, args.compare_seals[0], args.compare_seals[1]
            )
            print(
                "cross-profile seals match for exactly four PNG payloads: "
                f"{left_profile} / {right_profile}; no audit was run"
            )
        else:
            check_bound_sources(authority)
            print("four-candidate preregistration and tracked source bindings are valid")
        return 0
    except (DerivationError, OSError, ValueError) as exc:
        parser.exit(2, f"Golden-v3 four-candidate derivation failed closed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
