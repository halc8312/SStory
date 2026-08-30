#!/usr/bin/env python3
"""Fail-closed final-pixel auditor for the preregistered K3 Golden-v3 gates.

The authority deliberately contains no candidate binding.  ``--candidate`` is
bound at runtime, decoded once, and reported by SHA-256.  This command does not
promote, copy, designate, or otherwise mutate a candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import struct
import sys
import zlib
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import cv2
import numpy as np
import PIL
from PIL import Image, UnidentifiedImageError

import audit_style_candidate_k3_golden_v2 as v2
import build_style_candidate_k3_sparse_ridgeline_v19 as v19
import golden_v3_strict_metric_core as strict


AUTHORITY_PATH = Path(
    "world/map-production/spec/style-candidate-k3-golden-v3-strict-audit-authority.json"
)
EXPECTED_AUTHORITY_SHA256 = "c27b41e6336974c5ce5fe11c86cefc67ed35851650680c33379c3510444884d7"
REPORT_ID = "style-candidate-k-v3-golden-v3-strict-independent-pixel-audit"
ALGORITHM = "sstory-k3-golden-v3-strict-independent-pixel-audit-v1"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CANDIDATE_PNG_CONTRACT = {
    "signature_hex": PNG_SIGNATURE.hex(),
    "ihdr": {
        "bit_depth": 8,
        "color_type": 2,
        "compression_method": 0,
        "filter_method": 0,
        "allowed_interlace_methods": [0, 1],
    },
    "single_frame": True,
    "forbidden_chunks": [
        "acTL",
        "cHRM",
        "cICP",
        "cLLi",
        "eXIf",
        "fcTL",
        "fdAT",
        "gAMA",
        "iCCP",
        "mDCv",
        "sBIT",
        "sRGB",
        "tRNS",
    ],
    "all_chunk_crc_required": True,
    "trailing_bytes_after_iend_allowed": False,
}
FORBIDDEN_CANDIDATE_CHUNKS = frozenset(
    name.encode("ascii") for name in CANDIDATE_PNG_CONTRACT["forbidden_chunks"]
)
REQUIRED_AUTHORITY_KEYS = {
    "schema_version",
    "id",
    "status",
    "candidate_binding",
    "candidate_evaluations_before_freeze",
    "threshold_selection_from_candidate_values",
    "canvas",
    "runtime",
    "runtime_bindings",
    "pixel_references",
    "mask_bindings",
    "alpha_zero_derivation",
    "body_control",
    "luma",
    "signal_definition",
    "integer_gaussian",
    "primary_thresholds",
    "strict_field_contract",
    "closed_loop_contract",
    "white_crest_contract",
    "identity_contract",
    "v2_metric_value_source",
    "strict_core_binding",
    "failure_policy",
}


class GoldenV3StrictAuditError(RuntimeError):
    """Raised when strict evidence cannot be trusted or measured."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path, *, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise GoldenV3StrictAuditError(f"cannot read {label}: {path}") from exc


def _safe_relative(root: Path, value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise GoldenV3StrictAuditError(f"{label} path must be a nonempty string")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or value != pure.as_posix():
        raise GoldenV3StrictAuditError(f"{label} path must be canonical repository-relative POSIX")
    path = (root / Path(*pure.parts)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise GoldenV3StrictAuditError(f"{label} path escaped repository root") from exc
    return path


def _bind_record(root: Path, record: Any, *, label: str) -> tuple[Path, bytes]:
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise GoldenV3StrictAuditError(f"{label} binding field set drifted")
    expected = record["sha256"]
    if not isinstance(expected, str) or len(expected) != 64:
        raise GoldenV3StrictAuditError(f"{label} SHA-256 is invalid")
    path = _safe_relative(root, record["path"], label=label)
    payload = _read(path, label=label)
    if sha256(payload) != expected:
        raise GoldenV3StrictAuditError(f"{label} SHA-256 mismatch")
    return path, payload


def _require_imported_source(module: Any, bound_path: Path, *, label: str) -> None:
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str) or Path(module_file).resolve() != bound_path:
        raise GoldenV3StrictAuditError(f"imported {label} is not the SHA-bound source path")


def load_authority(root: Path, path: Path = AUTHORITY_PATH) -> tuple[dict[str, Any], str]:
    resolved = path if path.is_absolute() else root / path
    resolved = resolved.resolve()
    if resolved != (root / AUTHORITY_PATH).resolve():
        raise GoldenV3StrictAuditError(f"authority path must equal {AUTHORITY_PATH.as_posix()}")
    payload = _read(resolved, label="strict-v3 authority")
    digest = sha256(payload)
    if digest != EXPECTED_AUTHORITY_SHA256:
        raise GoldenV3StrictAuditError("strict-v3 authority SHA-256 mismatch")
    try:
        authority = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoldenV3StrictAuditError("strict-v3 authority is not canonical UTF-8 JSON") from exc
    if not isinstance(authority, dict) or set(authority) != REQUIRED_AUTHORITY_KEYS:
        raise GoldenV3StrictAuditError("strict-v3 authority field set drifted")
    if (
        authority["schema_version"] != "1.0.0"
        or authority["id"] != "sstory-k3-golden-v3-strict-audit-authority-v1"
        or authority["status"] != "frozen-before-candidate-evaluation"
        or authority["candidate_binding"] is not None
        or authority["candidate_evaluations_before_freeze"] != 0
        or authority["threshold_selection_from_candidate_values"] is not False
    ):
        raise GoldenV3StrictAuditError("strict-v3 preregistration state drifted")
    canvas = authority["canvas"]
    if not isinstance(canvas, dict) or canvas.get("candidate_png_contract") != CANDIDATE_PNG_CONTRACT:
        raise GoldenV3StrictAuditError("strict-v3 candidate PNG contract drifted")
    return authority, digest


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


def _runtime_gate(authority: Mapping[str, Any]) -> str:
    expected = authority["runtime"]
    if not isinstance(expected, dict) or set(expected) != {
        "common",
        "allowed_profiles",
        "profile_selection",
    }:
        raise GoldenV3StrictAuditError("strict-v3 runtime contract field set drifted")
    if expected["profile_selection"] != (
        "exactly one profile must match system, machine, installed OpenCV distribution set, "
        "and OpenCV build-information SHA-256"
    ):
        raise GoldenV3StrictAuditError("strict-v3 runtime profile-selection rule drifted")
    cv2.setNumThreads(1)
    cv2.setRNGSeed(0x4538)
    actual_common = {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "opencv_api": cv2.__version__,
        "numpy": np.__version__,
        "pillow": PIL.__version__,
        "byteorder": sys.byteorder,
        "opencv_threads": cv2.getNumThreads(),
    }
    if actual_common != expected["common"]:
        raise GoldenV3StrictAuditError(
            f"strict-v3 common runtime mismatch: expected={expected['common']}, actual={actual_common}"
        )
    actual_profile = {
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "opencv_distributions": _opencv_distributions(),
        "opencv_build_sha256": sha256(cv2.getBuildInformation().encode("utf-8")),
    }
    profiles = expected["allowed_profiles"]
    if not isinstance(profiles, list) or not profiles:
        raise GoldenV3StrictAuditError("strict-v3 allowed runtime profiles are missing")
    matches: list[str] = []
    for profile in profiles:
        if not isinstance(profile, dict) or set(profile) != {"id", *actual_profile}:
            raise GoldenV3StrictAuditError("strict-v3 runtime profile field set drifted")
        if not isinstance(profile["id"], str) or not profile["id"]:
            raise GoldenV3StrictAuditError("strict-v3 runtime profile id is invalid")
        if {key: profile[key] for key in actual_profile} == actual_profile:
            matches.append(profile["id"])
    if len(matches) != 1:
        raise GoldenV3StrictAuditError(
            f"strict-v3 runtime profile mismatch: actual={actual_profile}"
        )
    return matches[0]


def _inspect_candidate_png(payload: bytes, *, size: tuple[int, int]) -> None:
    if not payload.startswith(PNG_SIGNATURE):
        raise GoldenV3StrictAuditError("candidate PNG signature is invalid")
    offset = len(PNG_SIGNATURE)
    chunk_index = 0
    seen_ihdr = False
    seen_idat = False
    idat_ended = False
    seen_iend = False
    while offset < len(payload):
        if len(payload) - offset < 12:
            raise GoldenV3StrictAuditError("candidate PNG chunk framing is truncated")
        length = struct.unpack_from(">I", payload, offset)[0]
        end = offset + 12 + length
        if end > len(payload):
            raise GoldenV3StrictAuditError("candidate PNG chunk payload is truncated")
        chunk_type = payload[offset + 4 : offset + 8]
        if len(chunk_type) != 4 or any(
            not (65 <= byte <= 90 or 97 <= byte <= 122) for byte in chunk_type
        ):
            raise GoldenV3StrictAuditError("candidate PNG chunk type is invalid")
        data = payload[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack_from(">I", payload, offset + 8 + length)[0]
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(data, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise GoldenV3StrictAuditError("candidate PNG chunk CRC mismatch")
        if chunk_index == 0 and chunk_type != b"IHDR":
            raise GoldenV3StrictAuditError("candidate PNG IHDR must be first")
        if chunk_type in FORBIDDEN_CANDIDATE_CHUNKS:
            name = chunk_type.decode("ascii")
            raise GoldenV3StrictAuditError(f"candidate PNG chunk {name} is forbidden")
        if chunk_type == b"IHDR":
            if seen_ihdr or length != 13:
                raise GoldenV3StrictAuditError("candidate PNG IHDR is duplicated or malformed")
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", data
            )
            ihdr = CANDIDATE_PNG_CONTRACT["ihdr"]
            if (
                (width, height) != size
                or bit_depth != ihdr["bit_depth"]
                or color_type != ihdr["color_type"]
                or compression != ihdr["compression_method"]
                or filter_method != ihdr["filter_method"]
                or interlace not in ihdr["allowed_interlace_methods"]
            ):
                raise GoldenV3StrictAuditError(
                    "candidate PNG IHDR must be exact-size 8-bit truecolor RGB"
                )
            seen_ihdr = True
        elif chunk_type == b"IDAT":
            if not seen_ihdr or idat_ended:
                raise GoldenV3StrictAuditError("candidate PNG IDAT ordering is invalid")
            seen_idat = True
        elif chunk_type == b"IEND":
            if length != 0 or not seen_idat:
                raise GoldenV3StrictAuditError("candidate PNG IEND is malformed")
            seen_iend = True
            offset = end
            if offset != len(payload):
                raise GoldenV3StrictAuditError("candidate PNG has trailing bytes after IEND")
            break
        else:
            if seen_idat:
                idat_ended = True
            if chunk_type[0] & 0x20 == 0 and chunk_type not in {b"PLTE"}:
                raise GoldenV3StrictAuditError("candidate PNG has an unknown critical chunk")
        offset = end
        chunk_index += 1
    if not (seen_ihdr and seen_idat and seen_iend):
        raise GoldenV3StrictAuditError("candidate PNG required chunk sequence is incomplete")


def _decode_rgb(payload: bytes, *, size: tuple[int, int], label: str, strict_candidate: bool) -> np.ndarray:
    if strict_candidate:
        _inspect_candidate_png(payload, size=size)
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            opened.load()
            if opened.format != "PNG" or opened.mode != "RGB" or opened.size != size:
                raise GoldenV3StrictAuditError(f"{label} must be exact {size[0]}x{size[1]} RGB PNG")
            if strict_candidate and (
                getattr(opened, "n_frames", 1) != 1
                or getattr(opened, "is_animated", False)
                or "transparency" in opened.info
                or "icc_profile" in opened.info
                or "gamma" in opened.info
                or "srgb" in opened.info
                or "chromaticity" in opened.info
                or "exif" in opened.info
                or "A" in opened.getbands()
            ):
                raise GoldenV3StrictAuditError(
                    "candidate animation/alpha/color-profile/EXIF metadata is forbidden"
                )
            return np.asarray(opened, dtype=np.uint8).copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise GoldenV3StrictAuditError(f"cannot decode {label} PNG") from exc


def _decode_gray(payload: bytes, *, size: tuple[int, int], label: str) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            opened.load()
            if opened.format != "PNG" or opened.mode != "L" or opened.size != size:
                raise GoldenV3StrictAuditError(f"{label} must be exact {size[0]}x{size[1]} grayscale PNG")
            return np.asarray(opened, dtype=np.uint8).copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise GoldenV3StrictAuditError(f"cannot decode {label} PNG") from exc


def _decode_binary(payload: bytes, *, size: tuple[int, int], label: str) -> np.ndarray:
    values = _decode_gray(payload, size=size, label=label)
    if not set(int(value) for value in np.unique(values)).issubset({0, 255}):
        raise GoldenV3StrictAuditError(f"{label} must contain only 0/255")
    return values == np.uint8(255)


def _validate_alpha_zero(
    root: Path,
    authority: Mapping[str, Any],
    bound_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    record = authority["alpha_zero_derivation"]
    required = {"source_path", "source_sha256", "formula", "true_pixels", "uint8_array_sha256"}
    if not isinstance(record, dict) or set(record) != required:
        raise GoldenV3StrictAuditError("alpha-zero derivation field set drifted")
    source_path = _safe_relative(root, record["source_path"], label="alpha-zero source")
    if sha256(_read(source_path, label="alpha-zero source")) != record["source_sha256"]:
        raise GoldenV3StrictAuditError("alpha-zero source SHA-256 mismatch")
    _require_imported_source(v19, source_path, label="v19 module")
    controls = v19.derive_controls()
    alpha = controls["alpha"]
    recomputed = alpha == np.float32(0.0)
    if (
        not np.array_equal(recomputed, bound_mask)
        or int(np.count_nonzero(recomputed)) != int(record["true_pixels"])
        or sha256(np.ascontiguousarray(recomputed.astype(np.uint8)).tobytes())
        != record["uint8_array_sha256"]
    ):
        raise GoldenV3StrictAuditError("alpha-zero bound mask differs from v19 derivation")
    return recomputed, alpha == np.float32(1.0)


def audit_candidate(candidate_path: Path, *, root: Path | None = None) -> dict[str, Any]:
    repository = (root or Path.cwd()).resolve()
    authority, authority_sha = load_authority(repository)
    runtime_bindings = authority["runtime_bindings"]
    if not isinstance(runtime_bindings, dict) or set(runtime_bindings) != {
        "dependency_lock",
        "ci_workflow",
        "synthetic_golden_vector_test",
    }:
        raise GoldenV3StrictAuditError("strict-v3 runtime binding set drifted")
    runtime_binding_sha: dict[str, str] = {}
    for name, record in runtime_bindings.items():
        _bind_record(repository, record, label=f"runtime {name}")
        runtime_binding_sha[name] = record["sha256"]
    runtime_profile = _runtime_gate(authority)
    strict_core_path, _ = _bind_record(
        repository,
        authority["strict_core_binding"],
        label="strict integer core",
    )
    _require_imported_source(strict, strict_core_path, label="strict core")
    strict.validate_authority_contract(authority)
    width = int(authority["canvas"]["width"])
    height = int(authority["canvas"]["height"])
    size = (width, height)

    candidate_resolved = candidate_path if candidate_path.is_absolute() else repository / candidate_path
    candidate_resolved = candidate_resolved.resolve()
    candidate_payload = _read(candidate_resolved, label="runtime-bound candidate")
    candidate_sha = sha256(candidate_payload)
    candidate = _decode_rgb(candidate_payload, size=size, label="candidate", strict_candidate=True)

    references: dict[str, np.ndarray] = {}
    reference_sha: dict[str, str] = {}
    for name, record in authority["pixel_references"].items():
        _, payload = _bind_record(repository, record, label=name)
        references[name] = _decode_rgb(payload, size=size, label=name, strict_candidate=False)
        reference_sha[name] = record["sha256"]
    foundation = references["foundation_v19"]
    baseline = references["baseline_v18"]

    masks: dict[str, np.ndarray] = {}
    mask_sha: dict[str, str] = {}
    for name, record in authority["mask_bindings"].items():
        _, payload = _bind_record(repository, record, label=f"mask {name}")
        masks[name] = _decode_binary(payload, size=size, label=f"mask {name}")
        mask_sha[name] = record["sha256"]
    body_record = authority["body_control"]
    if not isinstance(body_record, dict) or not {"path", "sha256"}.issubset(body_record):
        raise GoldenV3StrictAuditError("body control binding is invalid")
    _, body_payload = _bind_record(
        repository,
        {"path": body_record["path"], "sha256": body_record["sha256"]},
        label="body control",
    )
    body_control = _decode_gray(body_payload, size=size, label="body control")
    bodies, body_union = strict.decode_body_masks(body_control)
    if not np.array_equal(body_union, masks["selected_components"]):
        raise GoldenV3StrictAuditError("selected-components mask differs from indexed body union")
    if np.any(masks["measurement_inside"] & ~masks["permission"]):
        raise GoldenV3StrictAuditError("measurement mask escaped permission")
    if np.any(body_union & ~masks["measurement_inside"]):
        raise GoldenV3StrictAuditError("body union escaped measurement mask")
    alpha_zero, full_alpha = _validate_alpha_zero(repository, authority, masks["alpha_zero"])

    v2_source = authority["v2_metric_value_source"]
    if not isinstance(v2_source, dict) or not {"path", "sha256"}.issubset(v2_source):
        raise GoldenV3StrictAuditError("v2 metric-value source binding is invalid")
    v2_path = _safe_relative(repository, v2_source["path"], label="v2 metric-value source")
    if sha256(_read(v2_path, label="v2 metric-value source")) != v2_source["sha256"]:
        raise GoldenV3StrictAuditError("v2 metric-value source SHA-256 mismatch")
    _require_imported_source(v2, v2_path, label="v2 metric module")

    coverage_50, coverage_25 = v2._coverage(candidate)
    metrics = {
        "coverage_50": coverage_50,
        "coverage_25": coverage_25,
        "quiet_fraction": v2._quiet_fraction(candidate, masks["measurement_inside"]),
        "dash_bundle_pairs": v2._dash_bundle_pairs(candidate, masks["measurement_inside"]),
        "orientation_coherence": v2._orientation_coherence(candidate, masks["measurement_inside"]),
        "texture_inside_to_outside_ratio": v2._texture_ratios(
            candidate,
            baseline,
            masks["measurement_inside"],
            masks["texture_reference"],
        ),
    }
    geometry, geometry_proof = v2._pixel_derived_geometry(body_union, candidate, baseline)
    primary = strict.primary_gates(metrics, authority["primary_thresholds"])

    kernels = strict.load_kernels(authority)
    delta_luma = strict.luma_u8(candidate).astype(np.int16) - strict.luma_u8(foundation).astype(np.int16)
    strict_metrics, fields, cores = strict.measure_strict_fields(
        delta_luma,
        bodies,
        kernels,
        authority["strict_field_contract"],
    )
    field_gates = strict.strict_field_gates(
        strict_metrics, authority["strict_field_contract"]
    )
    loop_contract = authority["closed_loop_contract"]
    loop = strict.closed_loop_count(
        [record["total"] for record in fields],
        bodies,
        cores,
        kernels,
        floor_l_q=int(round(float(loop_contract["absolute_floor_l"]) * strict.Q_SIGNAL)),
        minimum_hole_area=int(loop_contract["minimum_hole_area_pixels"]),
    )
    crest_contract = authority["white_crest_contract"]
    crest = strict.white_crest_particle_count(
        candidate,
        foundation,
        [record["total"] for record in fields],
        bodies,
        cores,
        kernels[4],
        local_floor_l_q=int(round(float(crest_contract["local_positive_floor_l"]) * strict.Q_SIGNAL)),
        minimum_delta_luma=int(crest_contract["minimum_candidate_minus_foundation_luma"]),
        minimum_candidate_luma=int(crest_contract["minimum_candidate_luma"]),
        maximum_rgb_range=int(crest_contract["maximum_candidate_rgb_range"]),
    )
    identity = strict.lock_counts(
        candidate,
        baseline,
        permission=masks["permission"],
        protected=masks["protected_features"],
        road_calm=masks["road_calm_18px"],
        alpha_zero=alpha_zero,
    )
    identity["body_outside_full_alpha"] = int(np.count_nonzero(body_union & ~full_alpha))
    identity_thresholds = authority["identity_contract"]
    expected_identity_keys = {
        "outside_permission": "outside_permission_max",
        "protected_features": "protected_features_max",
        "road_calm_18px": "road_calm_18px_max",
        "alpha_zero": "alpha_zero_max",
        "body_outside_full_alpha": "body_outside_full_alpha_max",
    }
    if set(identity) != set(expected_identity_keys) or set(identity_thresholds) != set(expected_identity_keys.values()):
        raise GoldenV3StrictAuditError("identity authority/result field set drifted")
    identity_gates = {
        f"{name}_max_{identity_thresholds[threshold_key]}": value
        <= int(identity_thresholds[threshold_key])
        for name, threshold_key in expected_identity_keys.items()
        for value in (identity[name],)
    }
    topology_gates = {
        "selected_component_count_exact_8": geometry["selected_component_count"] == 8,
        "closed_loop_count_zero": loop["count"] == int(loop_contract["maximum_count"]),
        "white_crest_particle_count_zero": crest["count"] == int(crest_contract["maximum_count"]),
    }
    gates = {**primary, **field_gates, **identity_gates, **topology_gates}
    failed = sorted(name for name, passed in gates.items() if not passed)
    return {
        "schema_version": "1.0.0",
        "id": REPORT_ID,
        "algorithm": ALGORITHM,
        "authority_sha256": authority_sha,
        "runtime_profile": runtime_profile,
        "runtime_binding_sha256": runtime_binding_sha,
        "candidate": {
            "binding": "runtime-only",
            "sha256": candidate_sha,
            "bytes": len(candidate_payload),
            "path_recorded": False,
        },
        "reference_sha256": reference_sha,
        "mask_sha256": mask_sha,
        "body_control_sha256": authority["body_control"]["sha256"],
        "strict_core_sha256": authority["strict_core_binding"]["sha256"],
        "primary_metrics": metrics,
        "strict_metrics": strict_metrics,
        "geometry": geometry,
        "geometry_proof": geometry_proof,
        "identity": identity,
        "closed_loop": loop,
        "white_crest_particle": crest,
        "gates": gates,
        "failed_gates": failed,
        "passed": not failed,
        "promotion_or_golden_designation_performed": False,
    }


def canonical_json(report: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--authority", type=Path, default=AUTHORITY_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.authority != AUTHORITY_PATH:
        parser.exit(2, f"--authority must equal {AUTHORITY_PATH.as_posix()}\n")
    try:
        report = audit_candidate(args.candidate)
        payload = canonical_json(report)
    except (GoldenV3StrictAuditError, strict.StrictMetricError, v2.GoldenV2PixelAuditError) as exc:
        parser.exit(2, f"Golden-v3 strict audit failed closed: {exc}\n")
    if args.output is None:
        sys.stdout.buffer.write(payload)
    else:
        output = args.output.resolve()
        root = Path.cwd().resolve()
        try:
            output.relative_to(root)
        except ValueError:
            parser.exit(2, "--output must stay inside the repository\n")
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output.open("xb") as stream:
                stream.write(payload)
        except FileExistsError:
            parser.exit(2, "--output already exists; refusal prevents evidence overwrite\n")
        except OSError as exc:
            parser.exit(2, f"cannot create --output exclusively: {exc}\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
