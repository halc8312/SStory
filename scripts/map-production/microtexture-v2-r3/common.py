"""Shared r3 trust root, technical blind, frozen loader, and Git preflight."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import platform
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import scipy
from PIL import __version__ as pillow_version


CODE_ROOT = Path(__file__).resolve().parent
SPEC_PATH = CODE_ROOT / "preregistered-spec.json"
SPEC_SHA256 = "166eb08f8d2f9de673c29c4c24b4d1c405f0ea3800a04b50ac4124aa84bdb0a1"
BINDINGS_PATH = CODE_ROOT / "implementation-bindings.json"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def require_exact_keys(value: Any, keys: set[str], context: str) -> None:
    actual = set(value) if isinstance(value, dict) else set()
    if not isinstance(value, dict) or actual != keys:
        raise RuntimeError(
            f"{context} keyset drift: missing={sorted(keys - actual)}, extra={sorted(actual - keys)}"
        )


def load_spec() -> dict[str, Any]:
    payload = SPEC_PATH.read_bytes()
    if sha256_bytes(payload) != SPEC_SHA256:
        raise RuntimeError("r3 preregistered spec SHA drift")
    value = json.loads(payload.decode("utf-8"))
    if not all(
        value.get(key) is True
        for key in (
            "authority",
            "created_before_control_generation",
            "created_before_metric_threshold_selection",
            "candidate_or_foundation_inputs_forbidden",
        )
    ):
        raise RuntimeError("r3 preregistration authority flag drift")
    return value


def blind_key() -> bytes:
    value = os.environ.get("MICROTEXTURE_V2_R3_BLIND_KEY")
    if value is None:
        raise RuntimeError("MICROTEXTURE_V2_R3_BLIND_KEY is required")
    if re.fullmatch(r"(?:[0-9a-f]{64}|[0-9A-F]{64})", value) is None:
        raise RuntimeError(
            "MICROTEXTURE_V2_R3_BLIND_KEY must be exactly 64 all-lowercase or all-uppercase hexadecimal characters"
        )
    decoded = bytes.fromhex(value)
    if len(decoded) != 32:
        raise RuntimeError("decoded blind key must be exactly 32 bytes")
    return decoded


def blind_commitment(key: bytes) -> str:
    message = load_spec()["blind_derivation"]["key_commitment_message"].encode("ascii")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def blind_hmac(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def runtime_fingerprint() -> dict[str, str]:
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "pillow_version": pillow_version,
        "platform": platform.platform(),
        "byteorder": sys.byteorder,
    }


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc_timestamp(value: Any, context: str) -> datetime:
    if not isinstance(value, str):
        raise RuntimeError(f"{context} must be ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError(f"{context} is not ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise RuntimeError(f"{context} must use the UTC timezone")
    return parsed.astimezone(timezone.utc)


def _git(code_root: Path, *arguments: str) -> bytes:
    environment = os.environ.copy()
    environment.pop("MICROTEXTURE_V2_R3_BLIND_KEY", None)
    result = subprocess.run(
        ["git", *arguments],
        cwd=code_root,
        check=False,
        capture_output=True,
        env=environment,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Git preflight failed: {' '.join(arguments)}: {detail}")
    return result.stdout


def repository_root() -> Path:
    return Path(
        _git(CODE_ROOT, "rev-parse", "--show-toplevel").decode().strip()
    ).resolve()


def artifact_root(repository: Path) -> Path:
    raw = os.environ.get("MICROTEXTURE_V2_R3_ARTIFACT_ROOT")
    if raw is None:
        raise RuntimeError("MICROTEXTURE_V2_R3_ARTIFACT_ROOT is required")
    actual = Path(raw).resolve()
    expected = (
        repository / "tmp/map-production/microtexture-v2-r3-artifacts"
    ).resolve()
    if actual != expected:
        raise RuntimeError(f"artifact root must be exactly {expected}")
    if actual == CODE_ROOT or CODE_ROOT in actual.parents:
        raise RuntimeError("artifact root must be separate from CODE_ROOT")
    return actual


def safe_artifact_path(root: Path, path: Path) -> Path:
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise RuntimeError(f"path escapes exact artifact root: {resolved}") from error
    return resolved


def write_bytes_exclusive(root: Path, path: Path, payload: bytes) -> None:
    checked = safe_artifact_path(root, path)
    checked.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(checked, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        checked.unlink(missing_ok=True)
        raise


def write_json_exclusive(root: Path, path: Path, value: Any) -> str:
    payload = canonical_json_bytes(value)
    write_bytes_exclusive(root, path, payload)
    return sha256_bytes(payload)


def validate_implementation_bindings() -> dict[str, Any]:
    value = json.loads(BINDINGS_PATH.read_text(encoding="utf-8"))
    require_exact_keys(
        value,
        {"artifact", "schema_version", "authority", "spec_sha256", "files"},
        "implementation bindings",
    )
    if (
        value["artifact"] != "microtexture-v2-r3-implementation-bindings"
        or value["schema_version"] != "microtexture-v2-r3-implementation-bindings/1"
        or value["authority"] is not True
        or value["spec_sha256"] != SPEC_SHA256
    ):
        raise RuntimeError("r3 implementation binding header drift")
    expected = set(load_spec()["authority_files"]) - {"implementation-bindings.json"}
    if set(value["files"]) != expected:
        raise RuntimeError("r3 implementation binding file set drift")
    for relative, expected_sha in value["files"].items():
        path = (CODE_ROOT / relative).resolve()
        if (
            CODE_ROOT not in path.parents
            or sha256_bytes(path.read_bytes()) != expected_sha
        ):
            raise RuntimeError(f"r3 implementation SHA drift: {relative}")
    return value


def _tracked_worktree_bytes(
    repository: Path, captured_head: str, relative: str
) -> bytes:
    path = (repository / relative).resolve()
    try:
        path.relative_to(repository)
    except ValueError as error:
        raise RuntimeError(f"tracked path escapes repository: {relative}") from error
    working = path.read_bytes()
    committed = _git(CODE_ROOT, "show", f"{captured_head}:{relative}")
    if working != committed:
        raise RuntimeError(f"working bytes differ from captured HEAD: {relative}")
    return working


def assert_head_unchanged(captured_head: str) -> None:
    if _git(CODE_ROOT, "rev-parse", "HEAD").decode().strip() != captured_head:
        raise RuntimeError("Git HEAD changed during r3 operation")


def operation_preflight(
    *, require_receipt: bool, include_locked_positive: bool = False
) -> dict[str, Any]:
    spec = load_spec()
    key = blind_key()
    commitment = blind_commitment(key)
    repository = repository_root()
    captured_head = _git(CODE_ROOT, "rev-parse", "HEAD").decode().strip()
    branch = (
        _git(CODE_ROOT, "symbolic-ref", "--quiet", "--short", "HEAD").decode().strip()
    )
    upstream_ref = (
        _git(
            CODE_ROOT,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            f"{branch}@{{upstream}}",
        )
        .decode()
        .strip()
    )
    upstream_head = _git(CODE_ROOT, "rev-parse", upstream_ref).decode().strip()
    if captured_head != upstream_head:
        raise RuntimeError(
            "captured HEAD is not equal to the current branch upstream ref"
        )
    try:
        code_relative_root = CODE_ROOT.relative_to(repository)
    except ValueError as error:
        raise RuntimeError("CODE_ROOT is outside repository") from error
    required_code_root = Path(spec["roots"]["code_root_required_repo_relative"])
    if code_relative_root != required_code_root:
        raise RuntimeError(f"CODE_ROOT must be exactly {required_code_root.as_posix()}")
    for relative in spec["authority_files"]:
        repo_relative = (code_relative_root / relative).as_posix()
        _tracked_worktree_bytes(repository, captured_head, repo_relative)
    bindings = validate_implementation_bindings()
    state = {
        "repository": repository,
        "artifact_root": artifact_root(repository),
        "captured_head": captured_head,
        "upstream_ref": upstream_ref,
        "runtime": runtime_fingerprint(),
        "blind_key_commitment": commitment,
        "implementation_bindings_sha256": sha256_bytes(BINDINGS_PATH.read_bytes()),
        "bindings": bindings,
    }
    if include_locked_positive:
        locked = spec["locked_positive"]
        locked_bytes = _tracked_worktree_bytes(
            repository, captured_head, locked["repo_relative_path"]
        )
        if sha256_bytes(locked_bytes) != locked["sha256"]:
            raise RuntimeError("locked-positive tracked SHA drift")
        state["locked_positive_bytes"] = locked_bytes
    if require_receipt:
        receipt, receipt_sha = load_threshold_authority_receipt(state)
        state["threshold_authority"] = receipt
        state["threshold_authority_sha256"] = receipt_sha
    assert_head_unchanged(captured_head)
    return state


THRESHOLD_KEYS = {
    "metric",
    "direction",
    "target_label",
    "adoption",
    "target_population",
    "calibration_minimum_detection",
    "holdout_minimum_detection",
    "threshold",
    "clean_false_reject_rate",
    "calibration_target_detection_rate",
    "calibration_minimum_passed",
}
FROZEN_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "spec_sha256",
    "blind_key_commitment",
    "calibration_manifest_sha256",
    "calibration_report_sha256",
    "frozen_at",
    "runtime",
    "metric_rules",
    "thresholds",
    "implementation_bindings_sha256",
    "holdout_allowed_count",
    "threshold_changes_forbidden",
}
CALIBRATION_REPORT_KEYS = {
    "artifact",
    "schema_version",
    "spec_sha256",
    "blind_key_commitment",
    "manifest_sha256",
    "labels_sha256",
    "evaluated_at",
    "runtime",
    "implementation_bindings_sha256",
    "thresholds",
    "hard_per_metric_performance",
    "warning_per_metric_performance",
    "hard_scores",
    "targets",
    "warnings_by_code",
    "passed",
    "measurements",
    "identity_reveal",
}
LOCKED_REPORT_KEYS = {
    "artifact",
    "schema_version",
    "spec_sha256",
    "blind_key_commitment",
    "frozen_thresholds_sha256",
    "locked_positive_sha256",
    "crop_xywh",
    "evaluated_at",
    "runtime",
    "implementation_bindings_sha256",
    "metrics",
    "hard_results",
    "all_hard_passed",
    "passed",
}
RECEIPT_KEYS = {
    "artifact",
    "schema_version",
    "approval",
    "reviewer_id",
    "review_mode",
    "reviewed_at",
    "spec_sha256",
    "frozen_thresholds_sha256",
    "calibration_report_sha256",
    "calibration_manifest_sha256",
    "locked_positive_report_sha256",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "runtime",
}


def _validate_thresholds(
    metric_rules: Any, thresholds: Any, spec: dict[str, Any]
) -> None:
    expected = spec["threshold_selection"]["metric_rules"]
    if (
        metric_rules != expected
        or not isinstance(thresholds, list)
        or len(thresholds) != len(expected)
    ):
        raise RuntimeError("metric rule/order or threshold count drift")
    names: list[str] = []
    for index, (threshold, rule) in enumerate(zip(thresholds, expected)):
        require_exact_keys(threshold, THRESHOLD_KEYS, f"threshold[{index}]")
        for key in rule:
            if threshold[key] != rule[key]:
                raise RuntimeError(f"threshold[{index}] rule binding drift: {key}")
        for key in (
            "threshold",
            "clean_false_reject_rate",
            "calibration_target_detection_rate",
        ):
            if not isinstance(threshold[key], (int, float)) or not math.isfinite(
                float(threshold[key])
            ):
                raise RuntimeError(f"threshold[{index}] non-finite {key}")
        if type(threshold["calibration_minimum_passed"]) is not bool:
            raise RuntimeError("threshold minimum flag drift")
        names.append(threshold["metric"])
    if len(names) != len(set(names)):
        raise RuntimeError("duplicate threshold metric")


def load_frozen_thresholds(state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    root = state["artifact_root"]
    frozen_path = safe_artifact_path(root, root / "thresholds-frozen.json")
    frozen_bytes = frozen_path.read_bytes()
    frozen_sha = sha256_bytes(frozen_bytes)
    frozen = json.loads(frozen_bytes.decode("utf-8"))
    require_exact_keys(frozen, FROZEN_KEYS, "frozen thresholds")
    spec = load_spec()
    if (
        frozen["artifact"] != "microtexture-v2-r3-thresholds-frozen"
        or frozen["schema_version"] != "microtexture-v2-r3-thresholds/1"
        or frozen["authority"] is not True
        or frozen["spec_sha256"] != SPEC_SHA256
        or frozen["blind_key_commitment"] != state["blind_key_commitment"]
        or frozen["runtime"] != state["runtime"]
        or frozen["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or frozen["holdout_allowed_count"] != 1
        or frozen["threshold_changes_forbidden"] is not True
    ):
        raise RuntimeError("frozen threshold authority/runtime/blind binding drift")
    _validate_thresholds(frozen["metric_rules"], frozen["thresholds"], spec)
    report_path = safe_artifact_path(root, root / "reports/calibration-report.json")
    report_bytes = report_path.read_bytes()
    if sha256_bytes(report_bytes) != frozen["calibration_report_sha256"]:
        raise RuntimeError("actual calibration report SHA mismatch")
    report = json.loads(report_bytes.decode("utf-8"))
    require_exact_keys(report, CALIBRATION_REPORT_KEYS, "calibration report")
    calibration_evaluated_at = parse_utc_timestamp(
        report["evaluated_at"], "calibration report evaluated_at"
    )
    frozen_at = parse_utc_timestamp(frozen["frozen_at"], "threshold frozen_at")
    if calibration_evaluated_at > frozen_at:
        raise RuntimeError("thresholds were frozen before calibration evaluation")
    if (
        report["passed"] is not True
        or report["spec_sha256"] != SPEC_SHA256
        or report["blind_key_commitment"] != state["blind_key_commitment"]
        or report["manifest_sha256"] != frozen["calibration_manifest_sha256"]
        or report["runtime"] != state["runtime"]
        or report["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or report["thresholds"] != frozen["thresholds"]
    ):
        raise RuntimeError("calibration report/frozen binding drift")
    calibration_manifest_path = safe_artifact_path(
        root, root / "controls/calibration/manifest.json"
    )
    calibration_manifest_bytes = calibration_manifest_path.read_bytes()
    if (
        sha256_bytes(calibration_manifest_bytes)
        != frozen["calibration_manifest_sha256"]
    ):
        raise RuntimeError("actual calibration manifest SHA mismatch")
    return frozen, frozen_sha


def load_threshold_authority_receipt(
    state: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    spec = load_spec()
    relative = spec["external_threshold_authority"]["receipt_repo_relative_path"]
    payload = _tracked_worktree_bytes(
        state["repository"], state["captured_head"], relative
    )
    receipt = json.loads(payload.decode("utf-8"))
    require_exact_keys(receipt, RECEIPT_KEYS, "threshold authority receipt")
    frozen, frozen_sha = load_frozen_thresholds(state)
    root = state["artifact_root"]
    locked_path = safe_artifact_path(
        root, root / spec["locked_positive"]["report_repo_relative_artifact_path"]
    )
    locked_bytes = locked_path.read_bytes()
    locked = json.loads(locked_bytes.decode("utf-8"))
    require_exact_keys(locked, LOCKED_REPORT_KEYS, "locked-positive report")
    frozen_at = parse_utc_timestamp(frozen["frozen_at"], "threshold frozen_at")
    locked_evaluated_at = parse_utc_timestamp(
        locked["evaluated_at"], "locked-positive evaluated_at"
    )
    if locked_evaluated_at < frozen_at:
        raise RuntimeError("locked-positive evaluation predates threshold freeze")
    if (
        locked["passed"] is not True
        or locked["all_hard_passed"] is not True
        or locked["spec_sha256"] != SPEC_SHA256
        or locked["runtime"] != state["runtime"]
        or locked["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or locked["frozen_thresholds_sha256"] != frozen_sha
        or locked["blind_key_commitment"] != state["blind_key_commitment"]
        or locked["locked_positive_sha256"] != spec["locked_positive"]["sha256"]
        or locked["crop_xywh"] != spec["locked_positive"]["crop_xywh"]
    ):
        raise RuntimeError("locked-positive report is not a passing frozen validation")
    expected = spec["external_threshold_authority"]
    reviewer = receipt["reviewer_id"]
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise RuntimeError("threshold authority reviewer_id must be non-empty")
    normalized_reviewer = " ".join(
        unicodedata.normalize("NFKC", reviewer).casefold().split()
    )
    eligible_reviewers = {
        " ".join(unicodedata.normalize("NFKC", value).casefold().split())
        for value in expected["eligible_reviewer_ids"]
    }
    if normalized_reviewer not in eligible_reviewers:
        raise RuntimeError("threshold authority reviewer is not preregistered/eligible")
    if receipt["review_mode"] != expected["required_review_mode"]:
        raise RuntimeError("threshold authority review mode drift")
    reviewed_at = parse_utc_timestamp(
        receipt["reviewed_at"], "threshold authority reviewed_at"
    )
    if reviewed_at < max(frozen_at, locked_evaluated_at):
        raise RuntimeError(
            "threshold authority review predates freeze/locked evaluation"
        )
    tolerance = timedelta(seconds=int(expected["clock_future_tolerance_seconds"]))
    if reviewed_at > datetime.now(timezone.utc) + tolerance:
        raise RuntimeError("threshold authority reviewed_at is in the future")
    if (
        receipt["artifact"] != "microtexture-v2-r3-threshold-authority"
        or receipt["schema_version"] != expected["schema_version"]
        or receipt["approval"] != expected["required_approval"]
        or receipt["spec_sha256"] != SPEC_SHA256
        or receipt["frozen_thresholds_sha256"] != frozen_sha
        or receipt["calibration_report_sha256"] != frozen["calibration_report_sha256"]
        or receipt["calibration_manifest_sha256"]
        != frozen["calibration_manifest_sha256"]
        or receipt["locked_positive_report_sha256"] != sha256_bytes(locked_bytes)
        or receipt["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or receipt["blind_key_commitment"] != state["blind_key_commitment"]
        or receipt["runtime"] != state["runtime"]
    ):
        raise RuntimeError(
            "external threshold authority receipt binding/approval drift"
        )
    return receipt, sha256_bytes(payload)
