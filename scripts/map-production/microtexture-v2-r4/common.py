"""Shared r4 trust root, technical blind, one-shot loaders, and Git preflight."""

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
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import numpy._core._multiarray_umath as numpy_core_binary
import scipy
import scipy.ndimage._nd_image as scipy_ndimage_binary
from PIL import _imaging as pillow_imaging_binary
from PIL import __version__ as pillow_version


CODE_ROOT = Path(__file__).resolve().parent
SPEC_PATH = CODE_ROOT / "preregistered-spec.json"
# Replaced with the final byte hash only after every authority file is frozen.
SPEC_SHA256 = "983ebd87618e7f05a82fb95027eb0fdbb9ca1fd0664015c1f2a28a97b3df6642"
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
            f"{context} keyset drift: missing={sorted(keys - actual)}, "
            f"extra={sorted(actual - keys)}"
        )


def require_exact_int(value: Any, context: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise RuntimeError(f"{context} must be an exact integer >= {minimum}")
    return value


def require_exact_real(
    value: Any,
    context: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise RuntimeError(f"{context} must be a finite real number (bool forbidden)")
    result = float(value)
    if minimum is not None and result < minimum:
        raise RuntimeError(f"{context} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise RuntimeError(f"{context} must be <= {maximum}")
    return result


ENDPOINT_DEFINITION_KEYS = {
    "id",
    "population",
    "expected_result",
    "minimum_unique_clusters",
    "calibration_minimum",
    "holdout_minimum",
}
EXPECTED_ENDPOINT_IDS = [
    "clean_acceptance",
    "warning_acceptance",
    "reject_detection",
    "severity3_detection",
    "grain_reject_detection",
    "tiny_speck_reject_detection",
    "microblob_reject_detection",
    "spot_reject_detection",
    "short_line_reject_detection",
    "parallel_bundle_reject_detection",
]
CONTACT_SHEET_VIEW_KEYS = {"id", "scale_percent", "source_crop_xywh"}


def validate_contact_sheet_view_partition(
    settings: Any, metric_window_xywh: Any
) -> None:
    context = "r4 contact-sheet views"
    if (
        not isinstance(metric_window_xywh, list)
        or len(metric_window_xywh) != 4
        or any(type(value) is not int for value in metric_window_xywh)
    ):
        raise RuntimeError(f"{context} metric window must use exact integers")
    mx, my, metric_width, metric_height = metric_window_xywh
    if (
        mx < 0
        or my < 0
        or metric_width <= 0
        or metric_height <= 0
        or metric_width % 2
        or metric_height % 2
    ):
        raise RuntimeError(f"{context} metric window cannot be quartered exactly")
    if not isinstance(settings, dict):
        raise RuntimeError(f"{context} settings must be an object")
    views = settings.get("views")
    if not isinstance(views, list) or len(views) != 5:
        raise RuntimeError(f"{context} must contain exactly five views")
    half_width, half_height = metric_width // 2, metric_height // 2
    expected = [
        ("full-200", 200, [mx, my, metric_width, metric_height]),
        ("northwest-400", 400, [mx, my, half_width, half_height]),
        (
            "northeast-400",
            400,
            [mx + half_width, my, half_width, half_height],
        ),
        (
            "southwest-400",
            400,
            [mx, my + half_height, half_width, half_height],
        ),
        (
            "southeast-400",
            400,
            [mx + half_width, my + half_height, half_width, half_height],
        ),
    ]
    normalized: list[tuple[str, int, list[int]]] = []
    for index, view in enumerate(views):
        require_exact_keys(view, CONTACT_SHEET_VIEW_KEYS, f"{context}[{index}]")
        view_id = view["id"]
        scale = view["scale_percent"]
        crop = view["source_crop_xywh"]
        if (
            not isinstance(view_id, str)
            or not view_id
            or type(scale) is not int
            or not isinstance(crop, list)
            or len(crop) != 4
            or any(type(value) is not int for value in crop)
        ):
            raise RuntimeError(f"{context}[{index}] exact type contract drift")
        normalized.append((view_id, scale, crop))
    if normalized != expected:
        raise RuntimeError(f"{context} exact id/order/scale/crop drift")
    panel = settings.get("panel_dimensions")
    if (
        not isinstance(panel, list)
        or len(panel) != 2
        or any(type(value) is not int or value <= 0 for value in panel)
    ):
        raise RuntimeError(f"{context} panel dimensions must be exact integers")
    panel_width, panel_height = panel
    for view_id, scale, (_, _, width, height) in normalized:
        if width * scale != panel_width * 100 or height * scale != panel_height * 100:
            raise RuntimeError(f"{context} {view_id} does not exactly fill its panel")
    if (
        settings.get("resize") != "nearest"
        or settings.get("all_four_400_percent_quadrants_required") is not True
    ):
        raise RuntimeError(f"{context} resize/quadrant requirement drift")
    coverage = np.zeros((metric_height, metric_width), dtype=np.uint8)
    for view_id, _, (left, top, width, height) in normalized[1:]:
        relative_left, relative_top = left - mx, top - my
        if (
            relative_left < 0
            or relative_top < 0
            or relative_left + width > metric_width
            or relative_top + height > metric_height
        ):
            raise RuntimeError(f"{context} {view_id} escapes the metric window")
        coverage[
            relative_top : relative_top + height,
            relative_left : relative_left + width,
        ] += 1
    if coverage.size != metric_width * metric_height or not np.all(coverage == 1):
        raise RuntimeError(f"{context} quadrants have overlap or gaps")


def validate_preregistered_spec(value: dict[str, Any]) -> None:
    selection = value.get("threshold_selection")
    if not isinstance(selection, dict):
        raise RuntimeError("r4 threshold_selection must be an object")
    gate = selection.get("hard_gate")
    require_exact_keys(
        gate,
        {"metric", "direction", "threshold_count", "complete_hard_composite"},
        "r4 hard gate spec",
    )
    if (
        gate["metric"] != "microartifact_occupancy_per_mp"
        or gate["direction"] != "maximum"
        or require_exact_int(gate["threshold_count"], "hard threshold_count", 1) != 1
        or not isinstance(gate["complete_hard_composite"], str)
    ):
        raise RuntimeError("r4 single hard-gate contract drift")
    admissibility = selection.get("admissibility")
    require_exact_keys(
        admissibility,
        {
            "clean_cluster_acceptance_minimum",
            "warning_cluster_acceptance_minimum",
        },
        "r4 threshold admissibility",
    )
    for field in (
        "clean_cluster_acceptance_minimum",
        "warning_cluster_acceptance_minimum",
    ):
        require_exact_real(
            admissibility[field],
            f"threshold admissibility {field}",
            minimum=0.0,
            maximum=1.0,
        )
    if selection.get("selection_status_state_machine") != {
        "no-admissible-threshold": {
            "hard_threshold": None,
            "passed": False,
            "freeze_forbidden": True,
        },
        "selected-but-endpoint-failed": {
            "hard_threshold": "selected nonnegative scalar",
            "passed": False,
            "freeze_forbidden": True,
        },
        "selected-and-passed": {
            "hard_threshold": "selected nonnegative scalar",
            "passed": True,
            "freeze_required": True,
        },
    }:
        raise RuntimeError("r4 selection status state-machine drift")
    if (
        not isinstance(selection.get("no_admissible_report_binding"), str)
        or not selection["no_admissible_report_binding"]
    ):
        raise RuntimeError("r4 no-admissible report binding is missing")
    endpoints = selection.get("endpoint_definitions")
    if not isinstance(endpoints, list) or [item.get("id") for item in endpoints] != (
        EXPECTED_ENDPOINT_IDS
    ):
        raise RuntimeError("r4 endpoint id/order contract drift")
    populations: set[str] = set()
    for index, endpoint in enumerate(endpoints):
        require_exact_keys(endpoint, ENDPOINT_DEFINITION_KEYS, f"endpoint[{index}]")
        if (
            not isinstance(endpoint["population"], str)
            or not endpoint["population"]
            or endpoint["population"] in populations
            or endpoint["expected_result"] not in {"accept", "reject"}
        ):
            raise RuntimeError(f"endpoint[{index}] population/result contract drift")
        populations.add(endpoint["population"])
        require_exact_int(
            endpoint["minimum_unique_clusters"],
            f"endpoint[{index}] minimum_unique_clusters",
            1,
        )
        for split in ("calibration", "holdout"):
            require_exact_real(
                endpoint[f"{split}_minimum"],
                f"endpoint[{index}] {split}_minimum",
                minimum=0.0,
                maximum=1.0,
            )
    contact = value.get("contact_sheets")
    if not isinstance(contact, dict) or not isinstance(contact.get("views"), list):
        raise RuntimeError("r4 contact-sheet spec must define views")
    validate_contact_sheet_view_partition(
        contact, value["canvas"]["metric_window"]["xywh"]
    )
    for field, expected in (
        ("expected_controls_per_split", 140),
        ("expected_pages_per_view", 24),
        ("expected_pages_per_split", 120),
    ):
        if (
            require_exact_int(contact.get(field), f"contact_sheets.{field}", 1)
            != expected
        ):
            raise RuntimeError(f"contact_sheets.{field} contract drift")
    label_paths = value.get("labels", {}).get("exact_artifact_paths")
    if label_paths != {
        "calibration": "controls/calibration/labels-calibration.json",
        "holdout": "controls/holdout/labels-holdout.json",
    }:
        raise RuntimeError("r4 exact reviewed-label artifact paths drift")
    sealed_label_paths = value.get("labels", {}).get("sealed_authority_paths")
    if sealed_label_paths != {
        "calibration": "sealed-inputs/calibration-reviewed-labels.json",
        "holdout": "sealed-inputs/holdout-reviewed-labels.json",
    }:
        raise RuntimeError("r4 sealed reviewed-label authority paths drift")
    one_shot = value.get("one_shot_failure_reporting", {})
    if (
        one_shot.get("completion_report_schema")
        != "microtexture-v2-r4-stage-completion/2"
        or one_shot.get("completion_report_paths")
        != {
            "calibration": "completions/calibration.json",
            "locked-clean-reference": "completions/locked-clean-reference.json",
            "holdout": "completions/holdout.json",
        }
        or one_shot.get("completion_exact_binding_fields")
        != [
            "manifest_sha256",
            "labels_sha256",
            "frozen_thresholds_sha256",
            "threshold_authority_receipt_sha256",
            "locked_clean_reference_sha256",
        ]
        or one_shot.get("completion_is_exclusive_final_stage_operation") is not True
        or one_shot.get("normal_endpoint_failure_writes_passed_false_completion")
        is not True
        or one_shot.get(
            "authority_loaders_require_completion_and_reject_failure_coexistence"
        )
        is not True
    ):
        raise RuntimeError("r4 final stage-completion contract drift")
    if (
        value.get("holdout_pass_targets", {}).get(
            "terminal_report_authority_reload_required"
        )
        is not True
        or value.get("public_identity_policy", {}).get(
            "authority_reload_secret_rebinding_required"
        )
        is not True
    ):
        raise RuntimeError("r4 terminal authority reload contract drift")
    locked_revalidation = value.get("locked_clean_reference", {}).get(
        "holdout_preflight_revalidation"
    )
    require_exact_keys(
        locked_revalidation,
        {
            "required_at",
            "exact_path_fields",
            "requirements",
            "numeric_measurement_forbidden",
        },
        "locked-clean holdout preflight revalidation",
    )
    if (
        locked_revalidation["required_at"]
        != ["holdout-control-generation", "holdout-evaluation-before-marker"]
        or locked_revalidation["exact_path_fields"]
        != [
            "repo_relative_path",
            "generation_chain",
            "generation_receipt",
            "root_vision_review",
            "independent_vision_review",
        ]
        or locked_revalidation["requirements"]
        != [
            "tracked at the current receipt HEAD",
            "working bytes identical to that HEAD",
            "SHA-256 identical to this preregistration",
        ]
        or locked_revalidation["numeric_measurement_forbidden"] is not True
    ):
        raise RuntimeError("locked-clean holdout preflight contract drift")
    cluster = value.get("independent_condition_clusters")
    if not isinstance(cluster, dict):
        raise RuntimeError("private cluster contract must be an object")
    for field, expected in (
        ("expected_unique_clusters_per_split", 80),
        ("expected_clean_clusters_per_split", 20),
        ("expected_artifact_clusters_per_split", 60),
        ("expected_artifact_clusters_per_family", 10),
    ):
        if require_exact_int(cluster.get(field), field, 1) != expected:
            raise RuntimeError(f"private cluster contract drift: {field}")
    metric_window = value["canvas"]["metric_window"]
    if (
        metric_window.get("xywh") != [128, 96, 256, 192]
        or require_exact_int(metric_window.get("pixels"), "metric-window pixels", 1)
        != 49152
        or value["metric_definition"].get("expected_shape_hw") != [192, 256]
    ):
        raise RuntimeError("r4 metric-window contract drift")


def load_spec() -> dict[str, Any]:
    payload = SPEC_PATH.read_bytes()
    if sha256_bytes(payload) != SPEC_SHA256:
        raise RuntimeError("r4 preregistered spec SHA drift")
    value = json.loads(payload.decode("utf-8"))
    if value.get(
        "schema_version"
    ) != "microtexture-v2-r4-preregistered-spec/2" or not all(
        value.get(key) is True
        for key in (
            "authority",
            "created_before_control_generation",
            "created_before_metric_threshold_selection",
            "candidate_or_foundation_inputs_forbidden",
        )
    ):
        raise RuntimeError("r4 preregistration authority flag/schema drift")
    validate_preregistered_spec(value)
    return value


def blind_key() -> bytes:
    value = os.environ.get("MICROTEXTURE_V2_R4_BLIND_KEY")
    if value is None:
        raise RuntimeError("MICROTEXTURE_V2_R4_BLIND_KEY is required")
    if re.fullmatch(r"(?:[0-9a-f]{64}|[0-9A-F]{64})", value) is None:
        raise RuntimeError(
            "MICROTEXTURE_V2_R4_BLIND_KEY must be exactly 64 all-lowercase "
            "or all-uppercase hexadecimal characters"
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
    components = {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "pillow_version": pillow_version,
        "zlib_version": zlib.ZLIB_VERSION,
        "zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
        "platform": platform.platform(),
        "byteorder": sys.byteorder,
        "python_executable_sha256": sha256_bytes(Path(sys.executable).read_bytes()),
        "numpy_core_binary_sha256": sha256_bytes(
            Path(numpy_core_binary.__file__).read_bytes()
        ),
        "scipy_ndimage_binary_sha256": sha256_bytes(
            Path(scipy_ndimage_binary.__file__).read_bytes()
        ),
        "pillow_imaging_binary_sha256": sha256_bytes(
            Path(pillow_imaging_binary.__file__).read_bytes()
        ),
    }
    return {
        **components,
        "fingerprint_sha256": sha256_bytes(canonical_json_bytes(components)),
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
    environment.pop("MICROTEXTURE_V2_R4_BLIND_KEY", None)
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
    raw = os.environ.get("MICROTEXTURE_V2_R4_ARTIFACT_ROOT")
    if raw is None:
        raise RuntimeError("MICROTEXTURE_V2_R4_ARTIFACT_ROOT is required")
    required_relative = "tmp/map-production/microtexture-v2-r4-artifacts"
    actual = Path(os.path.abspath(raw))
    expected = Path(os.path.abspath(os.fspath(repository / required_relative)))
    if os.path.normcase(os.fspath(actual)) != os.path.normcase(os.fspath(expected)):
        raise RuntimeError(f"artifact root must be exactly {expected}")
    exact_artifact_path_without_links(
        repository,
        actual,
        required_relative,
        must_exist=False,
    )
    if actual == CODE_ROOT or CODE_ROOT in actual.parents:
        raise RuntimeError("artifact root must be separate from CODE_ROOT")
    return actual


def exact_artifact_path_without_links(
    root: Path,
    provided: Path,
    expected_relative: str,
    *,
    must_exist: bool,
) -> Path:
    root_lexical = Path(os.path.abspath(os.fspath(root)))
    actual = Path(os.path.abspath(os.fspath(provided)))
    expected = Path(os.path.abspath(os.fspath(root_lexical / expected_relative)))
    if os.path.normcase(os.fspath(actual)) != os.path.normcase(os.fspath(expected)):
        raise RuntimeError(
            f"artifact path must be exactly {expected}; aliases are forbidden"
        )
    try:
        relative = actual.relative_to(root_lexical)
    except ValueError as error:
        raise RuntimeError(f"path escapes exact artifact root: {actual}") from error
    current = root_lexical
    components = [current]
    for part in relative.parts:
        current = current / part
        components.append(current)
    for component in components:
        try:
            component_stat = os.lstat(component)
        except FileNotFoundError:
            continue
        junction_probe = getattr(component, "is_junction", None)
        is_junction = bool(junction_probe()) if callable(junction_probe) else False
        attributes = getattr(component_stat, "st_file_attributes", 0)
        is_reparse = bool(attributes & 0x400)
        if component.is_symlink() or is_junction or is_reparse:
            raise RuntimeError(
                f"artifact path contains a link/reparse point: {component}"
            )
    if must_exist and (not actual.exists() or not actual.is_file()):
        raise RuntimeError(f"exact artifact input is not a regular file: {actual}")
    return actual


def write_bytes_exclusive(root: Path, path: Path, payload: bytes) -> None:
    root_lexical = Path(os.path.abspath(os.fspath(root)))
    path_lexical = Path(os.path.abspath(os.fspath(path)))
    try:
        relative = path_lexical.relative_to(root_lexical).as_posix()
    except ValueError as error:
        raise RuntimeError(
            f"path escapes exact artifact root: {path_lexical}"
        ) from error
    checked = exact_artifact_path_without_links(
        root, path_lexical, relative, must_exist=False
    )
    checked.parent.mkdir(parents=True, exist_ok=True)
    checked = exact_artifact_path_without_links(
        root, path_lexical, relative, must_exist=False
    )
    if checked.exists() or checked.is_symlink():
        raise FileExistsError(f"exclusive artifact already exists: {checked}")
    descriptor = os.open(checked, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        verified = exact_artifact_path_without_links(
            root, path_lexical, relative, must_exist=True
        )
        if verified.read_bytes() != payload:
            raise RuntimeError(f"exclusive artifact post-write byte drift: {verified}")
    except BaseException:
        try:
            cleanup = exact_artifact_path_without_links(
                root, path_lexical, relative, must_exist=False
            )
            if cleanup.exists() and cleanup.is_file():
                cleanup.unlink()
        except BaseException:
            pass
        raise


def write_json_exclusive(root: Path, path: Path, value: Any) -> str:
    payload = canonical_json_bytes(value)
    write_bytes_exclusive(root, path, payload)
    return sha256_bytes(payload)


def _stage_artifact_paths(stage: str) -> tuple[str, str]:
    if stage not in {"calibration", "locked-clean-reference", "holdout"}:
        raise RuntimeError(f"invalid one-shot stage: {stage}")
    settings = load_spec()["one_shot_failure_reporting"]
    return (
        settings["completion_report_paths"][stage],
        settings["exception_report_paths"][stage],
    )


def validate_stage_completion_structure(value: Any, context: str) -> None:
    require_exact_keys(value, STAGE_COMPLETION_KEYS, context)
    require_exact_keys(value["bindings"], STAGE_COMPLETION_BINDING_KEYS, context)
    if (
        value["artifact"] != "microtexture-v2-r4-stage-completion"
        or value["schema_version"] != "microtexture-v2-r4-stage-completion/2"
        or value["stage"] not in {"calibration", "locked-clean-reference", "holdout"}
        or re.fullmatch(r"[0-9a-f]{64}", value["spec_sha256"] or "") is None
        or re.fullmatch(r"[0-9a-f]{64}", value["blind_key_commitment"] or "") is None
        or re.fullmatch(r"[0-9a-f]{64}", value["evaluation_marker_sha256"] or "")
        is None
        or re.fullmatch(r"[0-9a-f]{64}", value["normal_report_sha256"] or "") is None
        or re.fullmatch(r"[0-9a-f]{40}", value["captured_git_head"] or "") is None
        or not isinstance(value["runtime"], dict)
        or re.fullmatch(r"[0-9a-f]{64}", value["implementation_bindings_sha256"] or "")
        is None
        or type(value["one_shot_consumed"]) is not bool
        or value["one_shot_consumed"] is not True
        or type(value["passed"]) is not bool
        or not isinstance(value["result_status"], str)
        or not value["result_status"]
    ):
        raise RuntimeError(f"{context} header/type drift")
    for field, digest in value["bindings"].items():
        if digest is not None and re.fullmatch(r"[0-9a-f]{64}", digest or "") is None:
            raise RuntimeError(f"{context} invalid binding: {field}")
    parse_utc_timestamp(value["completed_at"], f"{context} completed_at")


def write_stage_completion_exclusive(
    *,
    stage: str,
    state: dict[str, Any],
    marker_sha: str,
    report_sha: str,
    passed: bool,
    result_status: str,
    bindings: dict[str, str | None],
) -> None:
    require_exact_keys(bindings, STAGE_COMPLETION_BINDING_KEYS, f"{stage} completion")
    completion = {
        "artifact": "microtexture-v2-r4-stage-completion",
        "schema_version": "microtexture-v2-r4-stage-completion/2",
        "stage": stage,
        "spec_sha256": SPEC_SHA256,
        "blind_key_commitment": state["blind_key_commitment"],
        "evaluation_marker_sha256": marker_sha,
        "normal_report_sha256": report_sha,
        "captured_git_head": state["captured_head"],
        "runtime": state["runtime"],
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "completed_at": utc_timestamp(),
        "one_shot_consumed": True,
        "passed": passed,
        "result_status": result_status,
        "bindings": bindings,
    }
    validate_stage_completion_structure(completion, f"{stage} completion")
    completion_relative, failure_relative = _stage_artifact_paths(stage)
    root = state["artifact_root"]
    failure_path = exact_artifact_path_without_links(
        root,
        root / failure_relative,
        failure_relative,
        must_exist=False,
    )
    if failure_path.exists():
        raise RuntimeError(f"{stage} failure report precludes normal completion")
    completion_path = exact_artifact_path_without_links(
        root,
        root / completion_relative,
        completion_relative,
        must_exist=False,
    )
    payload = canonical_json_bytes(completion)
    write_bytes_exclusive(root, completion_path, payload)


def load_stage_completion(
    *,
    stage: str,
    state: dict[str, Any],
    expected_marker_sha: str,
    expected_report_sha: str,
    expected_captured_head: str,
    expected_passed: bool,
    expected_result_status: str,
    expected_bindings: dict[str, str | None],
    marker_started_at: datetime,
    report_evaluated_at: datetime,
    frozen_at: datetime | None = None,
) -> tuple[dict[str, Any], str]:
    require_exact_keys(
        expected_bindings,
        STAGE_COMPLETION_BINDING_KEYS,
        f"{stage} expected completion bindings",
    )
    completion_relative, failure_relative = _stage_artifact_paths(stage)
    root = state["artifact_root"]
    failure_path = exact_artifact_path_without_links(
        root,
        root / failure_relative,
        failure_relative,
        must_exist=False,
    )
    if failure_path.exists():
        raise RuntimeError(f"{stage} failure report coexists with normal completion")
    completion_path = exact_artifact_path_without_links(
        root,
        root / completion_relative,
        completion_relative,
        must_exist=True,
    )
    payload = completion_path.read_bytes()
    completion = json.loads(payload.decode("utf-8"))
    validate_stage_completion_structure(completion, f"{stage} completion")
    if (
        completion["stage"] != stage
        or completion["spec_sha256"] != SPEC_SHA256
        or completion["blind_key_commitment"] != state["blind_key_commitment"]
        or completion["evaluation_marker_sha256"] != expected_marker_sha
        or completion["normal_report_sha256"] != expected_report_sha
        or completion["captured_git_head"] != expected_captured_head
        or completion["runtime"] != state["runtime"]
        or completion["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or completion["passed"] is not expected_passed
        or completion["result_status"] != expected_result_status
        or completion["bindings"] != expected_bindings
    ):
        raise RuntimeError(f"{stage} completion trust-chain binding drift")
    completed_at = parse_utc_timestamp(
        completion["completed_at"], f"{stage} completion completed_at"
    )
    if marker_started_at > report_evaluated_at or report_evaluated_at > completed_at:
        raise RuntimeError(f"{stage} marker/report/completion timestamp order drift")
    if frozen_at is not None and frozen_at > completed_at:
        raise RuntimeError(f"{stage} frozen/completion timestamp order drift")
    return completion, sha256_bytes(payload)


def validate_implementation_bindings() -> dict[str, Any]:
    value = json.loads(BINDINGS_PATH.read_text(encoding="utf-8"))
    require_exact_keys(
        value,
        {"artifact", "schema_version", "authority", "spec_sha256", "files"},
        "implementation bindings",
    )
    if (
        value["artifact"] != "microtexture-v2-r4-implementation-bindings"
        or value["schema_version"] != "microtexture-v2-r4-implementation-bindings/2"
        or value["authority"] is not True
        or value["spec_sha256"] != SPEC_SHA256
    ):
        raise RuntimeError("r4 implementation binding header drift")
    expected = set(load_spec()["authority_files"]) - {"implementation-bindings.json"}
    if set(value["files"]) != expected:
        raise RuntimeError("r4 implementation binding file set drift")
    for relative, expected_sha in value["files"].items():
        path = (CODE_ROOT / relative).resolve()
        if (
            CODE_ROOT not in path.parents
            or sha256_bytes(path.read_bytes()) != expected_sha
        ):
            raise RuntimeError(f"r4 implementation SHA drift: {relative}")
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
        raise RuntimeError("Git HEAD changed during r4 operation")


def assert_git_ancestor(ancestor: str, descendant: str) -> None:
    try:
        _git(CODE_ROOT, "merge-base", "--is-ancestor", ancestor, descendant)
    except RuntimeError as error:
        raise RuntimeError(
            "formal calibration HEAD is not an ancestor of the current r4 HEAD"
        ) from error


def verify_tracked_locked_clean_reference_provenance(
    repository: Path, captured_head: str, locked: dict[str, Any]
) -> bytes:
    bindings = (
        ("repo_relative_path", "sha256"),
        ("generation_chain", "generation_chain_sha256"),
        ("generation_receipt", "generation_receipt_sha256"),
        ("root_vision_review", "root_vision_review_sha256"),
        ("independent_vision_review", "independent_vision_review_sha256"),
    )
    payloads: dict[str, bytes] = {}
    for path_field, hash_field in bindings:
        payload = _tracked_worktree_bytes(repository, captured_head, locked[path_field])
        if sha256_bytes(payload) != locked[hash_field]:
            raise RuntimeError(f"locked-clean-reference {path_field} tracked SHA drift")
        payloads[path_field] = payload
    return payloads["repo_relative_path"]


def operation_preflight(
    *, require_receipt: bool, include_locked_clean_reference: bool = False
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
        _tracked_worktree_bytes(
            repository, captured_head, (code_relative_root / relative).as_posix()
        )
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
    if include_locked_clean_reference:
        locked = spec["locked_clean_reference"]
        locked_bytes = verify_tracked_locked_clean_reference_provenance(
            repository, captured_head, locked
        )
        state["locked_clean_reference_bytes"] = locked_bytes
    if require_receipt:
        receipt, receipt_sha = load_threshold_authority_receipt(state)
        state["threshold_authority"] = receipt
        state["threshold_authority_sha256"] = receipt_sha
    assert_head_unchanged(captured_head)
    return state


HARD_THRESHOLD_KEYS = {
    "metric",
    "direction",
    "threshold",
    "calibration_clean_cluster_acceptance",
    "calibration_warning_cluster_acceptance",
    "calibration_reject_cluster_detection",
    "calibration_severity3_cluster_detection",
    "selection_objective",
}
FROZEN_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "spec_sha256",
    "blind_key_commitment",
    "calibration_manifest_sha256",
    "calibration_report_sha256",
    "calibration_evaluation_marker_sha256",
    "calibration_captured_git_head",
    "frozen_at",
    "runtime",
    "hard_gate",
    "hard_threshold",
    "endpoint_definitions",
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
    "evaluation_marker_sha256",
    "evaluated_at",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "hard_gate",
    "hard_threshold",
    "selection_status",
    "endpoint_performance",
    "results_by_code",
    "diagnostic_flags_by_code",
    "passed",
    "measurements",
    "identity_reveal",
    "threshold_selection_audit",
    "one_shot_consumed",
    "failure",
}
LOCKED_CLEAN_REFERENCE_REPORT_KEYS = {
    "artifact",
    "schema_version",
    "spec_sha256",
    "blind_key_commitment",
    "frozen_thresholds_sha256",
    "locked_clean_reference_sha256",
    "source_crop_xywh",
    "metric_window_xywh_within_source_crop",
    "effective_source_xywh",
    "evaluation_marker_sha256",
    "evaluated_at",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "metrics",
    "hard_threshold",
    "hard_composite_accepted",
    "passed",
    "one_shot_consumed",
    "failure",
}
HOLDOUT_REPORT_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "spec_sha256",
    "blind_key_commitment",
    "manifest_sha256",
    "labels_sha256",
    "evaluation_marker_sha256",
    "frozen_thresholds_sha256",
    "threshold_authority_receipt_sha256",
    "evaluated_at",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "hard_gate",
    "hard_threshold",
    "endpoint_performance",
    "results_by_code",
    "diagnostic_flags_by_code",
    "passed",
    "measurements",
    "identity_reveal",
    "threshold_changes_authorized",
    "one_shot_consumed",
    "failure",
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
    "locked_clean_reference_report_sha256",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "runtime",
    "calibration_captured_git_head",
    "locked_clean_reference_captured_git_head",
}
VISION_LABEL_KEYS = {
    "artifact",
    "schema_version",
    "split",
    "spec_sha256",
    "manifest_sha256",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "runtime",
    "contact_sheet_bundle",
    "reviewer",
    "items",
}
VISION_LABEL_ITEM_KEYS = {
    "anonymous_code",
    "disposition",
    "grain_visible",
    "tiny_speck_visible",
    "microblob_visible",
    "short_line_visible",
    "parallel_bundle_visible",
    "severity_0_to_3",
    "reviewed_at_200_percent",
    "reviewed_at_all_400_percent_quadrants",
    "notes",
}
CONTROL_MANIFEST_KEYS = {
    "artifact",
    "schema_version",
    "split",
    "spec_sha256",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "captured_git_head",
    "runtime",
    "frozen_thresholds_sha256",
    "threshold_authority_receipt_sha256",
    "record_count",
    "records",
    "contact_sheet_bundle",
    "warning",
}
CONTROL_RECORD_KEYS = {
    "anonymous_code",
    "control_png",
    "reference_png",
    "control_sha256",
    "reference_sha256",
    "delta_float32_sha256",
}
CONTROL_SHEET_KEYS = {
    "view_id",
    "scale_percent",
    "source_crop_xywh",
    "page_index",
    "path",
    "sha256",
    "item_codes",
}
FORBIDDEN_PUBLIC_IDENTITY_FIELDS = {
    "family",
    "family_id",
    "control_id",
    "variant",
    "variant_id",
    "role",
    "polarity",
    "parameters",
    "cluster_id",
    "condition_cluster_id",
}

CALIBRATION_MARKER_KEYS = {
    "artifact",
    "schema_version",
    "spec_sha256",
    "blind_key_commitment",
    "manifest_sha256",
    "labels_sha256",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "started_at",
    "one_shot_consumed",
}
LOCKED_CLEAN_REFERENCE_MARKER_KEYS = {
    "artifact",
    "schema_version",
    "spec_sha256",
    "blind_key_commitment",
    "frozen_thresholds_sha256",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "started_at",
    "one_shot_consumed",
}
HOLDOUT_MARKER_KEYS = {
    "artifact",
    "schema_version",
    "spec_sha256",
    "blind_key_commitment",
    "manifest_sha256",
    "labels_sha256",
    "frozen_thresholds_sha256",
    "threshold_authority_receipt_sha256",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "started_at",
    "one_shot_consumed",
}
FAILURE_KEYS = {"phase", "type", "message"}
ONE_SHOT_FAILURE_REPORT_KEYS = {
    "artifact",
    "schema_version",
    "stage",
    "spec_sha256",
    "blind_key_commitment",
    "evaluation_marker_sha256",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "failed_at",
    "one_shot_consumed",
    "bindings",
    "failure",
}
ONE_SHOT_FAILURE_BINDING_KEYS = {
    "manifest_sha256",
    "labels_sha256",
    "frozen_thresholds_sha256",
    "threshold_authority_receipt_sha256",
}
STAGE_COMPLETION_KEYS = {
    "artifact",
    "schema_version",
    "stage",
    "spec_sha256",
    "blind_key_commitment",
    "evaluation_marker_sha256",
    "normal_report_sha256",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "completed_at",
    "one_shot_consumed",
    "passed",
    "result_status",
    "bindings",
}
STAGE_COMPLETION_BINDING_KEYS = {
    "manifest_sha256",
    "labels_sha256",
    "frozen_thresholds_sha256",
    "threshold_authority_receipt_sha256",
    "locked_clean_reference_sha256",
}
ENDPOINT_PERFORMANCE_KEYS = {
    "record_count",
    "unique_cluster_count",
    "minimum_unique_clusters",
    "cluster_macro_rate",
    "minimum_rate",
    "count_passed",
    "rate_passed",
    "passed",
}
RESULT_KEYS = {"passed", "failed_hard_gate", "hard_metric_value"}
MEASUREMENT_KEYS = {"anonymous_code", "metrics"}
METRIC_KEYS = {
    "eligible_pixels",
    "microartifact_occupancy_per_mp",
    "microartifact_excess_energy_per_mp",
    "highpass_rms_l",
    "sparse_blob_score",
    "sparse_blob_peak_l",
    "sparse_blob_occupancy_pixels",
    "finite_line_score",
    "finite_line_peak_l",
    "finite_line_occupancy_pixels",
    "parallel_pair_ratio",
    "parallel_pair_peak_l",
    "parallel_valid_pair_count",
}
METRIC_INTEGER_KEYS = {
    "eligible_pixels",
    "sparse_blob_occupancy_pixels",
    "finite_line_occupancy_pixels",
    "parallel_valid_pair_count",
}
IDENTITY_REVEAL_KEYS = {
    "anonymous_code",
    "family",
    "control_id",
    "condition_cluster_id",
    "variant_index",
    "replicate",
    "polarity",
    "parameters",
    "control_sha256",
    "reference_sha256",
    "delta_float32_sha256",
}
THRESHOLD_AUDIT_KEYS = {
    "candidate_count",
    "admissible_candidate_count",
    "selected_threshold",
    "selected_objective",
    "candidates",
}
THRESHOLD_AUDIT_CANDIDATE_KEYS = {
    "threshold",
    "admissible",
    "inadmissible_reasons",
    "objective",
    "clean_cluster_count",
    "warning_cluster_count",
    "clean_cluster_acceptance",
    "warning_cluster_acceptance",
    "all_endpoints_passed",
}


def _forbid_public_identity(value: Any, context: str) -> None:
    if isinstance(value, dict):
        leaked = set(value) & FORBIDDEN_PUBLIC_IDENTITY_FIELDS
        if leaked:
            raise RuntimeError(f"identity leak in {context}: {sorted(leaked)}")
        for child in value.values():
            _forbid_public_identity(child, context)
    elif isinstance(value, list):
        for child in value:
            _forbid_public_identity(child, context)


def validate_vision_labels_payload(
    value: Any,
    split: str,
    manifest: dict[str, Any],
    manifest_sha: str,
    state: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    context = f"{split} labels"
    require_exact_keys(value, VISION_LABEL_KEYS, context)
    _forbid_public_identity(value, context)
    if (
        value["artifact"] != "microtexture-v2-r4-root-vision-labels"
        or value["schema_version"] != "microtexture-v2-r4-root-vision-labels/2"
        or value["split"] != split
        or value["spec_sha256"] != SPEC_SHA256
        or value["manifest_sha256"] != manifest_sha
        or value["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or value["blind_key_commitment"] != state["blind_key_commitment"]
        or value["runtime"] != manifest["runtime"]
        or value["contact_sheet_bundle"] != manifest["contact_sheet_bundle"]
        or value["reviewer"] != "Root"
    ):
        raise RuntimeError(f"{context} authority/manifest/sheet drift")
    expected_codes = {record["anonymous_code"] for record in manifest["records"]}
    items = value["items"]
    if not isinstance(items, list) or len(items) != len(expected_codes):
        raise RuntimeError(f"{context} item count drift")
    labels: dict[str, dict[str, Any]] = {}
    visible_fields = (
        "grain_visible",
        "tiny_speck_visible",
        "microblob_visible",
        "short_line_visible",
        "parallel_bundle_visible",
    )
    boolean_fields = (
        *visible_fields,
        "reviewed_at_200_percent",
        "reviewed_at_all_400_percent_quadrants",
    )
    for index, item in enumerate(items):
        require_exact_keys(item, VISION_LABEL_ITEM_KEYS, f"{context}[{index}]")
        code, disposition = item["anonymous_code"], item["disposition"]
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[0-9a-f]{24}", code) is None
            or code in labels
            or disposition not in {"clean", "warning", "reject"}
        ):
            raise RuntimeError(f"{context} invalid code/disposition")
        for name in boolean_fields:
            if type(item[name]) is not bool:
                raise RuntimeError(f"{context} incomplete boolean: {code}/{name}")
        if (
            not item["reviewed_at_200_percent"]
            or not item["reviewed_at_all_400_percent_quadrants"]
        ):
            raise RuntimeError(
                f"{context} full-200 and all four 400-percent quadrants required: {code}"
            )
        severity = item["severity_0_to_3"]
        visible = any(item[name] for name in visible_fields)
        consistent = (
            (disposition == "clean" and severity == 0 and not visible)
            or (disposition == "warning" and severity == 1 and visible)
            or (disposition == "reject" and severity in {2, 3} and visible)
        )
        if (
            type(severity) is not int
            or not consistent
            or not isinstance(item["notes"], str)
        ):
            raise RuntimeError(
                f"{context} disposition/severity/visibility contradiction: {code}"
            )
        labels[code] = item
    if set(labels) != expected_codes:
        raise RuntimeError(f"{context} label coverage drift")
    return labels


def load_control_manifest(
    split: str,
    state: dict[str, Any],
    *,
    expected_captured_head: str,
    verify_payload_hashes: bool,
) -> tuple[dict[str, Any], str]:
    if split not in {"calibration", "holdout"}:
        raise RuntimeError("invalid control-manifest split")
    root, spec = state["artifact_root"], load_spec()
    relative = f"controls/{split}/manifest.json"
    path = exact_artifact_path_without_links(
        root, root / relative, relative, must_exist=True
    )
    payload = path.read_bytes()
    manifest = json.loads(payload.decode("utf-8"))
    require_exact_keys(manifest, CONTROL_MANIFEST_KEYS, f"{split} manifest")
    _forbid_public_identity(manifest, f"{split} manifest")
    expected_receipt_sha = (
        state.get("threshold_authority_sha256") if split == "holdout" else None
    )
    expected_frozen_sha = (
        state.get("threshold_authority", {}).get("frozen_thresholds_sha256")
        if split == "holdout"
        else None
    )
    if (
        manifest["artifact"] != "microtexture-v2-r4-control-manifest"
        or manifest["schema_version"] != "microtexture-v2-r4-control-manifest/2"
        or manifest["split"] != split
        or manifest["spec_sha256"] != SPEC_SHA256
        or manifest["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or manifest["blind_key_commitment"] != state["blind_key_commitment"]
        or manifest["captured_git_head"] != expected_captured_head
        or manifest["runtime"] != state["runtime"]
        or manifest["frozen_thresholds_sha256"] != expected_frozen_sha
        or manifest["threshold_authority_receipt_sha256"] != expected_receipt_sha
        or not isinstance(manifest["warning"], str)
        or not manifest["warning"]
    ):
        raise RuntimeError(f"{split} manifest trust-chain drift")
    expected_count = int(spec["contact_sheets"]["expected_controls_per_split"])
    records = manifest["records"]
    if (
        not isinstance(records, list)
        or require_exact_int(manifest["record_count"], f"{split} record_count", 1)
        != expected_count
        or len(records) != expected_count
    ):
        raise RuntimeError(f"{split} manifest record count drift")
    codes: list[str] = []
    for index, record in enumerate(records):
        require_exact_keys(record, CONTROL_RECORD_KEYS, f"{split} record[{index}]")
        code = record["anonymous_code"]
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[0-9a-f]{24}", code) is None
            or any(
                re.fullmatch(r"[0-9a-f]{64}", record[field] or "") is None
                for field in (
                    "control_sha256",
                    "reference_sha256",
                    "delta_float32_sha256",
                )
            )
        ):
            raise RuntimeError(f"{split} manifest record identity/hash drift")
        codes.append(code)
        control_relative = f"controls/{split}/items/{code}/control.png"
        reference_relative = f"controls/{split}/items/{code}/reference.png"
        if (
            record["control_png"] != control_relative
            or record["reference_png"] != reference_relative
        ):
            raise RuntimeError(f"{split} manifest exact item path drift: {code}")
        if verify_payload_hashes:
            for path_field, hash_field, expected_relative in (
                ("control_png", "control_sha256", control_relative),
                ("reference_png", "reference_sha256", reference_relative),
            ):
                item_path = exact_artifact_path_without_links(
                    root,
                    root / record[path_field],
                    expected_relative,
                    must_exist=True,
                )
                if sha256_bytes(item_path.read_bytes()) != record[hash_field]:
                    raise RuntimeError(f"{split} actual {path_field} SHA drift: {code}")
    if codes != sorted(codes) or len(codes) != len(set(codes)):
        raise RuntimeError(f"{split} manifest code order/collision drift")
    sheets = manifest["contact_sheet_bundle"]
    expected_sheet_count = int(spec["contact_sheets"]["expected_pages_per_split"])
    if not isinstance(sheets, list) or len(sheets) != expected_sheet_count:
        raise RuntimeError(f"{split} contact-sheet bundle count drift")
    per_page = int(spec["contact_sheets"]["columns"]) * int(
        spec["contact_sheets"]["rows_per_page"]
    )
    code_pages = [
        codes[start : start + per_page] for start in range(0, len(codes), per_page)
    ]
    expected_entries = []
    for view in spec["contact_sheets"]["views"]:
        for page_index, item_codes in enumerate(code_pages, 1):
            expected_entries.append(
                {
                    "view_id": view["id"],
                    "scale_percent": view["scale_percent"],
                    "source_crop_xywh": view["source_crop_xywh"],
                    "page_index": page_index,
                    "path": (
                        f"controls/{split}/contact-sheets/{view['id']}-"
                        f"page-{page_index:03d}.png"
                    ),
                    "item_codes": item_codes,
                }
            )
    for index, (sheet, expected) in enumerate(zip(sheets, expected_entries)):
        require_exact_keys(sheet, CONTROL_SHEET_KEYS, f"{split} sheet[{index}]")
        if (
            any(sheet[key] != value for key, value in expected.items())
            or re.fullmatch(r"[0-9a-f]{64}", sheet["sha256"] or "") is None
        ):
            raise RuntimeError(f"{split} contact-sheet binding drift: {index}")
        if verify_payload_hashes:
            sheet_path = exact_artifact_path_without_links(
                root,
                root / sheet["path"],
                sheet["path"],
                must_exist=True,
            )
            if sha256_bytes(sheet_path.read_bytes()) != sheet["sha256"]:
                raise RuntimeError(f"{split} actual contact-sheet SHA drift: {index}")
    return manifest, sha256_bytes(payload)


def validate_secret_catalog_report_binding(
    report: dict[str, Any],
    manifest: dict[str, Any],
    split: str,
    state: dict[str, Any],
) -> None:
    from control_catalog import (  # Imported lazily to avoid a module cycle.
        contact_sheet_pages,
        expected_controls,
        validate_manifest_public_bindings,
    )

    spec = load_spec()
    key = blind_key()
    if blind_commitment(key) != state["blind_key_commitment"]:
        raise RuntimeError(f"{split} blind key changed during authority reload")
    expected = expected_controls(spec, split, key)
    validate_manifest_public_bindings(manifest, expected)
    expected_pages = contact_sheet_pages(spec, split, expected)
    expected_bundle = [page.manifest_entry() for page in expected_pages]
    if manifest["contact_sheet_bundle"] != expected_bundle:
        raise RuntimeError(f"{split} secret-derived contact-sheet bundle drift")
    expected_by_public_tuple = {
        control.public_hash_tuple: control for control in expected
    }
    expected_reveal: dict[str, dict[str, Any]] = {}
    for record in manifest["records"]:
        public_tuple = (
            record["anonymous_code"],
            record["control_sha256"],
            record["reference_sha256"],
            record["delta_float32_sha256"],
        )
        control = expected_by_public_tuple[public_tuple]
        expected_reveal[control.anonymous_code] = {
            "anonymous_code": control.anonymous_code,
            "family": control.family,
            "control_id": control.control_id,
            "condition_cluster_id": control.condition_cluster_id,
            "variant_index": control.variant_index,
            "replicate": control.replicate,
            "polarity": control.polarity,
            "parameters": control.parameters,
            "control_sha256": control.control_sha256,
            "reference_sha256": control.reference_sha256,
            "delta_float32_sha256": control.delta_float32_sha256,
        }
    actual_reveal = {item["anonymous_code"]: item for item in report["identity_reveal"]}
    if actual_reveal != expected_reveal:
        raise RuntimeError(f"{split} secret-derived identity reveal drift")


def endpoint_population_codes(
    population: str, labels: dict[str, dict[str, Any]]
) -> list[str]:
    predicates = {
        "disposition_clean": lambda label: label["disposition"] == "clean",
        "disposition_warning": lambda label: label["disposition"] == "warning",
        "disposition_reject": lambda label: label["disposition"] == "reject",
        "severity_3": lambda label: label["severity_0_to_3"] == 3,
        "grain_visible_reject": lambda label: label["disposition"] == "reject"
        and label["grain_visible"],
        "tiny_speck_visible_reject": lambda label: label["disposition"] == "reject"
        and label["tiny_speck_visible"],
        "microblob_visible_reject": lambda label: label["disposition"] == "reject"
        and label["microblob_visible"],
        "spot_visible_reject": lambda label: label["disposition"] == "reject"
        and (label["tiny_speck_visible"] or label["microblob_visible"]),
        "short_line_visible_reject": lambda label: label["disposition"] == "reject"
        and label["short_line_visible"],
        "parallel_bundle_visible_reject": lambda label: label["disposition"] == "reject"
        and label["parallel_bundle_visible"],
    }
    if population not in predicates:
        raise RuntimeError(f"unknown endpoint population: {population}")
    return [code for code, label in labels.items() if predicates[population](label)]


def cluster_macro_rate(
    codes: list[str],
    rejected_by_code: dict[str, bool],
    clusters: dict[str, str],
    expected_result: str,
) -> tuple[float, int, int]:
    grouped: dict[str, list[float]] = {}
    for code in codes:
        cluster_id = clusters[code]
        grouped.setdefault(cluster_id, [])
        observed = rejected_by_code[code]
        correct = observed if expected_result == "reject" else not observed
        grouped[cluster_id].append(float(correct))
    if not grouped:
        return 0.0, 0, 0
    cluster_scores = [sum(values) / len(values) for values in grouped.values()]
    return float(sum(cluster_scores) / len(cluster_scores)), len(codes), len(grouped)


def evaluate_endpoints_from_measurements(
    threshold: float,
    measured: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    clusters: dict[str, str],
    split: str,
    spec: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if split not in {"calibration", "holdout"}:
        raise RuntimeError("invalid endpoint-evaluation split")
    if set(measured) != set(labels) or set(measured) != set(clusters):
        raise RuntimeError(f"{split} endpoint input code coverage drift")
    gate = spec["threshold_selection"]["hard_gate"]
    metric, direction = gate["metric"], gate["direction"]
    rejected = {
        code: (
            float(record["metrics"][metric]) > threshold
            if direction == "maximum"
            else float(record["metrics"][metric]) < threshold
        )
        for code, record in measured.items()
    }
    results = {
        code: {
            "passed": not failed,
            "failed_hard_gate": bool(failed),
            "hard_metric_value": float(measured[code]["metrics"][metric]),
        }
        for code, failed in rejected.items()
    }
    performance: dict[str, Any] = {}
    for endpoint in spec["threshold_selection"]["endpoint_definitions"]:
        codes = endpoint_population_codes(endpoint["population"], labels)
        rate, record_count, cluster_count = cluster_macro_rate(
            codes, rejected, clusters, endpoint["expected_result"]
        )
        minimum = float(endpoint[f"{split}_minimum"])
        minimum_clusters = int(endpoint["minimum_unique_clusters"])
        performance[endpoint["id"]] = {
            "record_count": record_count,
            "unique_cluster_count": cluster_count,
            "minimum_unique_clusters": minimum_clusters,
            "cluster_macro_rate": rate,
            "minimum_rate": minimum,
            "count_passed": cluster_count >= minimum_clusters,
            "rate_passed": rate >= minimum,
            "passed": cluster_count >= minimum_clusters and rate >= minimum,
        }
    return performance, results


def threshold_candidates(values: list[float]) -> list[float]:
    unique = sorted(set(float(value) for value in values))
    if not unique or any(not math.isfinite(value) for value in unique):
        raise RuntimeError("threshold metric values must be finite")
    epsilon = max(abs(unique[0]), abs(unique[-1]), 1.0) * 1e-9
    return sorted(
        {
            max(0.0, unique[0] - epsilon),
            *((left + right) / 2 for left, right in zip(unique, unique[1:])),
            unique[-1] + epsilon,
        }
    )


def select_hard_threshold_from_measurements(
    measured: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    clusters: dict[str, str],
    spec: dict[str, Any],
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any],
    dict[str, dict[str, Any]],
    str,
    dict[str, Any],
]:
    selection = spec["threshold_selection"]
    metric = selection["hard_gate"]["metric"]
    direction = selection["hard_gate"]["direction"]
    candidates: list[
        tuple[tuple[float, ...], float, dict[str, Any], dict[str, Any]]
    ] = []
    last_performance: dict[str, Any] = {}
    last_results: dict[str, dict[str, Any]] = {}
    candidate_audit: list[dict[str, Any]] = []
    for threshold in threshold_candidates(
        [float(record["metrics"][metric]) for record in measured.values()]
    ):
        performance, results = evaluate_endpoints_from_measurements(
            threshold, measured, labels, clusters, "calibration", spec
        )
        last_performance, last_results = performance, results
        clean = performance["clean_acceptance"]
        warning = performance["warning_acceptance"]
        inadmissible_reasons = []
        if not clean["count_passed"]:
            inadmissible_reasons.append("clean-cluster-count")
        if not warning["count_passed"]:
            inadmissible_reasons.append("warning-cluster-count")
        if clean["cluster_macro_rate"] < float(
            selection["admissibility"]["clean_cluster_acceptance_minimum"]
        ):
            inadmissible_reasons.append("clean-acceptance-rate")
        if warning["cluster_macro_rate"] < float(
            selection["admissibility"]["warning_cluster_acceptance_minimum"]
        ):
            inadmissible_reasons.append("warning-acceptance-rate")
        objective = tuple(_selected_objective(performance, float(threshold), direction))
        candidate_audit.append(
            {
                "threshold": float(threshold),
                "admissible": not inadmissible_reasons,
                "inadmissible_reasons": inadmissible_reasons,
                "objective": list(objective) if not inadmissible_reasons else None,
                "clean_cluster_count": clean["unique_cluster_count"],
                "warning_cluster_count": warning["unique_cluster_count"],
                "clean_cluster_acceptance": clean["cluster_macro_rate"],
                "warning_cluster_acceptance": warning["cluster_macro_rate"],
                "all_endpoints_passed": all(
                    endpoint["passed"] for endpoint in performance.values()
                ),
            }
        )
        if not inadmissible_reasons:
            candidates.append((objective, float(threshold), performance, results))
    audit = {
        "candidate_count": len(candidate_audit),
        "admissible_candidate_count": len(candidates),
        "selected_threshold": None,
        "selected_objective": None,
        "candidates": candidate_audit,
    }
    if not candidates:
        return None, last_performance, last_results, "no-admissible-threshold", audit
    selected_objective, threshold, performance, results = max(
        candidates, key=lambda item: item[0]
    )
    audit["selected_threshold"] = threshold
    audit["selected_objective"] = list(selected_objective)
    hard_threshold = {
        "metric": metric,
        "direction": direction,
        "threshold": threshold,
        "calibration_clean_cluster_acceptance": performance["clean_acceptance"][
            "cluster_macro_rate"
        ],
        "calibration_warning_cluster_acceptance": performance["warning_acceptance"][
            "cluster_macro_rate"
        ],
        "calibration_reject_cluster_detection": performance["reject_detection"][
            "cluster_macro_rate"
        ],
        "calibration_severity3_cluster_detection": performance["severity3_detection"][
            "cluster_macro_rate"
        ],
        "selection_objective": selection["objective_order"],
    }
    require_exact_keys(hard_threshold, HARD_THRESHOLD_KEYS, "selected hard threshold")
    validate_hard_threshold(hard_threshold, spec)
    status = (
        "selected-and-passed"
        if all(endpoint["passed"] for endpoint in performance.values())
        else "selected-but-endpoint-failed"
    )
    return hard_threshold, performance, results, status, audit


def validate_report_evaluation_bindings(
    report: dict[str, Any],
    manifest: dict[str, Any],
    labels: dict[str, dict[str, Any]],
    split: str,
    spec: dict[str, Any],
) -> None:
    context = f"{split} report evaluation bindings"
    records = manifest.get("records")
    if not isinstance(records, list):
        raise RuntimeError(f"{context} manifest records must be a list")
    records_by_code: dict[str, dict[str, Any]] = {}
    for record in records:
        code = record.get("anonymous_code") if isinstance(record, dict) else None
        if not isinstance(code, str) or code in records_by_code:
            raise RuntimeError(f"{context} manifest code drift")
        records_by_code[code] = record
    reveal_by_code = {
        item["anonymous_code"]: item for item in report["identity_reveal"]
    }
    if set(records_by_code) != set(reveal_by_code):
        raise RuntimeError(f"{context} manifest/reveal code coverage drift")
    for code, record in records_by_code.items():
        reveal = reveal_by_code[code]
        for field in (
            "control_sha256",
            "reference_sha256",
            "delta_float32_sha256",
        ):
            if record.get(field) != reveal[field]:
                raise RuntimeError(f"{context} manifest/reveal {field} drift")
    measured = {item["anonymous_code"]: item for item in report["measurements"]}
    clusters = {
        item["anonymous_code"]: item["condition_cluster_id"]
        for item in report["identity_reveal"]
    }
    if split == "calibration":
        expected_threshold, expected_endpoints, expected_results, status, audit = (
            select_hard_threshold_from_measurements(measured, labels, clusters, spec)
        )
        if (
            report["hard_threshold"] != expected_threshold
            or report["endpoint_performance"] != expected_endpoints
            or report["results_by_code"] != expected_results
            or report["selection_status"] != status
            or report["threshold_selection_audit"] != audit
            or report["passed"] is not (status == "selected-and-passed")
        ):
            raise RuntimeError(f"{context} full selector recomputation drift")
    elif split == "holdout":
        threshold = float(report["hard_threshold"]["threshold"])
        expected_endpoints, expected_results = evaluate_endpoints_from_measurements(
            threshold, measured, labels, clusters, split, spec
        )
        if (
            report["endpoint_performance"] != expected_endpoints
            or report["results_by_code"] != expected_results
            or report["passed"]
            is not all(endpoint["passed"] for endpoint in expected_endpoints.values())
        ):
            raise RuntimeError(f"{context} endpoint recomputation drift")
    else:
        raise RuntimeError(f"{context} invalid split")


def validate_failure(value: Any, context: str) -> None:
    if value is None:
        return
    require_exact_keys(value, FAILURE_KEYS, f"{context} failure")
    for key in FAILURE_KEYS:
        if not isinstance(value[key], str) or not value[key] or len(value[key]) > 512:
            raise RuntimeError(f"{context} failure field is invalid: {key}")


def validate_metric_values(metrics: Any, spec: dict[str, Any], context: str) -> None:
    require_exact_keys(metrics, METRIC_KEYS, context)
    expected_pixels = int(spec["canvas"]["metric_window"]["pixels"])
    for key in METRIC_INTEGER_KEYS:
        require_exact_int(metrics[key], f"{context}.{key}", 0)
    if metrics["eligible_pixels"] != expected_pixels:
        raise RuntimeError(f"{context}.eligible_pixels contract drift")
    for key in METRIC_KEYS - METRIC_INTEGER_KEYS:
        require_exact_real(metrics[key], f"{context}.{key}", minimum=0.0)
    require_exact_real(
        metrics["parallel_pair_ratio"],
        f"{context}.parallel_pair_ratio",
        minimum=0.0,
        maximum=1.0,
    )


def validate_endpoint_performance(
    value: Any, spec: dict[str, Any], split: str, context: str
) -> None:
    definitions = {
        endpoint["id"]: endpoint
        for endpoint in spec["threshold_selection"]["endpoint_definitions"]
    }
    require_exact_keys(value, set(definitions), context)
    for endpoint_id, endpoint in value.items():
        definition = definitions[endpoint_id]
        require_exact_keys(
            endpoint, ENDPOINT_PERFORMANCE_KEYS, f"{context}.{endpoint_id}"
        )
        record_count = require_exact_int(
            endpoint["record_count"], f"{context}.{endpoint_id}.record_count", 0
        )
        cluster_count = require_exact_int(
            endpoint["unique_cluster_count"],
            f"{context}.{endpoint_id}.unique_cluster_count",
            0,
        )
        minimum_clusters = require_exact_int(
            endpoint["minimum_unique_clusters"],
            f"{context}.{endpoint_id}.minimum_unique_clusters",
            1,
        )
        if cluster_count > record_count:
            raise RuntimeError(f"{context}.{endpoint_id} cluster count exceeds records")
        expected_minimum_clusters = definition["minimum_unique_clusters"]
        if minimum_clusters != expected_minimum_clusters:
            raise RuntimeError(f"{context}.{endpoint_id} minimum cluster drift")
        rate = require_exact_real(
            endpoint["cluster_macro_rate"],
            f"{context}.{endpoint_id}.cluster_macro_rate",
            minimum=0.0,
            maximum=1.0,
        )
        minimum_rate = require_exact_real(
            endpoint["minimum_rate"],
            f"{context}.{endpoint_id}.minimum_rate",
            minimum=0.0,
            maximum=1.0,
        )
        if minimum_rate != float(definition[f"{split}_minimum"]):
            raise RuntimeError(f"{context}.{endpoint_id} minimum rate drift")
        for key in ("count_passed", "rate_passed", "passed"):
            if type(endpoint[key]) is not bool:
                raise RuntimeError(f"{context}.{endpoint_id}.{key} must be exact bool")
        count_passed = cluster_count >= minimum_clusters
        rate_passed = rate >= minimum_rate
        if (
            endpoint["count_passed"] is not count_passed
            or endpoint["rate_passed"] is not rate_passed
            or endpoint["passed"] is not (count_passed and rate_passed)
        ):
            raise RuntimeError(f"{context}.{endpoint_id} pass recomputation drift")


def validate_threshold_selection_audit(
    value: Any, spec: dict[str, Any], context: str
) -> None:
    require_exact_keys(value, THRESHOLD_AUDIT_KEYS, context)
    candidates = value["candidates"]
    if not isinstance(candidates, list):
        raise RuntimeError(f"{context}.candidates must be a list")
    candidate_count = require_exact_int(value["candidate_count"], context, 1)
    admissible_count = require_exact_int(
        value["admissible_candidate_count"], context, 0
    )
    if candidate_count != len(candidates):
        raise RuntimeError(f"{context} candidate count drift")
    observed_admissible = 0
    observed_thresholds: list[float] = []
    admissible_objectives: list[tuple[float, ...]] = []
    allowed_reasons = {
        "clean-cluster-count",
        "warning-cluster-count",
        "clean-acceptance-rate",
        "warning-acceptance-rate",
    }
    for index, candidate in enumerate(candidates):
        item_context = f"{context}.candidates[{index}]"
        require_exact_keys(candidate, THRESHOLD_AUDIT_CANDIDATE_KEYS, item_context)
        observed_thresholds.append(
            require_exact_real(
                candidate["threshold"], f"{item_context}.threshold", minimum=0.0
            )
        )
        if (
            type(candidate["admissible"]) is not bool
            or type(candidate["all_endpoints_passed"]) is not bool
        ):
            raise RuntimeError(f"{item_context} booleans must be exact")
        reasons = candidate["inadmissible_reasons"]
        if not isinstance(reasons, list) or any(
            not isinstance(reason, str) or not reason for reason in reasons
        ):
            raise RuntimeError(f"{item_context} reasons must be non-empty strings")
        if len(reasons) != len(set(reasons)) or any(
            reason not in allowed_reasons for reason in reasons
        ):
            raise RuntimeError(f"{item_context} inadmissible reasons drift")
        objective = candidate["objective"]
        if candidate["admissible"]:
            observed_admissible += 1
            if (
                reasons
                or not isinstance(objective, list)
                or len(objective) != len(spec["threshold_selection"]["objective_order"])
            ):
                raise RuntimeError(f"{item_context} admissible objective drift")
            normalized_objective = tuple(
                require_exact_real(component, f"{item_context}.objective")
                for component in objective
            )
            for component in normalized_objective[:6]:
                if not 0.0 <= component <= 1.0:
                    raise RuntimeError(f"{item_context} objective rate drift")
            admissible_objectives.append(normalized_objective)
        elif not reasons or objective is not None:
            raise RuntimeError(f"{item_context} inadmissible audit drift")
        for key in ("clean_cluster_count", "warning_cluster_count"):
            require_exact_int(candidate[key], f"{item_context}.{key}", 0)
        for key in ("clean_cluster_acceptance", "warning_cluster_acceptance"):
            require_exact_real(
                candidate[key], f"{item_context}.{key}", minimum=0.0, maximum=1.0
            )
    if observed_admissible != admissible_count:
        raise RuntimeError(f"{context} admissible count drift")
    if observed_thresholds != sorted(set(observed_thresholds)):
        raise RuntimeError(f"{context} thresholds must be unique and increasing")
    if admissible_count == 0:
        if (
            value["selected_threshold"] is not None
            or value["selected_objective"] is not None
        ):
            raise RuntimeError(f"{context} selected an inadmissible threshold")
    else:
        require_exact_real(
            value["selected_threshold"], f"{context}.selected_threshold", minimum=0.0
        )
        selected_objective = value["selected_objective"]
        if not isinstance(selected_objective, list) or len(selected_objective) != len(
            spec["threshold_selection"]["objective_order"]
        ):
            raise RuntimeError(f"{context}.selected_objective drift")
        for component in selected_objective:
            require_exact_real(component, f"{context}.selected_objective")
        selected_threshold = float(value["selected_threshold"])
        matching = [
            candidate
            for candidate in candidates
            if candidate["admissible"]
            and float(candidate["threshold"]) == selected_threshold
        ]
        if (
            len(matching) != 1
            or matching[0]["objective"] != selected_objective
            or tuple(float(component) for component in selected_objective)
            != max(admissible_objectives)
        ):
            raise RuntimeError(f"{context} selected candidate/objective drift")


def validate_results_measurements_and_reveal(
    report: dict[str, Any],
    spec: dict[str, Any],
    split: str,
    context: str,
    hard_threshold: dict[str, Any] | None,
) -> None:
    if split not in {"calibration", "holdout"}:
        raise RuntimeError(f"{context} invalid split")
    measurements = report["measurements"]
    reveal = report["identity_reveal"]
    results = report["results_by_code"]
    diagnostics = report["diagnostic_flags_by_code"]
    expected_count = int(spec["contact_sheets"]["expected_controls_per_split"])
    if not isinstance(measurements, list) or len(measurements) != expected_count:
        raise RuntimeError(f"{context} measurement count drift")
    measurement_by_code: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(measurements):
        require_exact_keys(item, MEASUREMENT_KEYS, f"{context}.measurements[{index}]")
        code = item["anonymous_code"]
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[0-9a-f]{24}", code) is None
            or code in measurement_by_code
        ):
            raise RuntimeError(f"{context} invalid/duplicate measurement code")
        validate_metric_values(item["metrics"], spec, f"{context}.metrics[{code}]")
        measurement_by_code[code] = item["metrics"]
    codes = set(measurement_by_code)
    require_exact_keys(results, codes, f"{context}.results_by_code")
    require_exact_keys(diagnostics, codes, f"{context}.diagnostic_flags_by_code")
    allowed_flags = {
        "sparse-blob-diagnostic",
        "finite-line-diagnostic",
        "parallel-pair-diagnostic",
    }
    for code in codes:
        result = results[code]
        require_exact_keys(result, RESULT_KEYS, f"{context}.result[{code}]")
        if (
            type(result["passed"]) is not bool
            or type(result["failed_hard_gate"]) is not bool
        ):
            raise RuntimeError(f"{context}.result[{code}] booleans must be exact")
        metric_value = require_exact_real(
            result["hard_metric_value"],
            f"{context}.result[{code}].hard_metric_value",
            minimum=0.0,
        )
        hard_metric = spec["threshold_selection"]["hard_gate"]["metric"]
        if metric_value != float(measurement_by_code[code][hard_metric]):
            raise RuntimeError(f"{context}.result[{code}] metric binding drift")
        if result["passed"] is not (not result["failed_hard_gate"]):
            raise RuntimeError(f"{context}.result[{code}] pass complement drift")
        if hard_threshold is not None:
            threshold = float(hard_threshold["threshold"])
            failed = (
                metric_value > threshold
                if hard_threshold["direction"] == "maximum"
                else metric_value < threshold
            )
            if result["failed_hard_gate"] is not failed:
                raise RuntimeError(
                    f"{context}.result[{code}] threshold recomputation drift"
                )
        flags = diagnostics[code]
        if (
            not isinstance(flags, list)
            or len(flags) != len(set(flags))
            or any(flag not in allowed_flags for flag in flags)
        ):
            raise RuntimeError(f"{context}.diagnostic_flags[{code}] drift")
        levels = spec["metric_definition"][
            "diagnostic_reference_levels_development_only"
        ]
        expected_flags: list[str] = []
        metrics = measurement_by_code[code]
        if float(metrics["sparse_blob_score"]) > float(levels["sparse_blob_score"]):
            expected_flags.append("sparse-blob-diagnostic")
        finite_line_visible = float(metrics["finite_line_score"]) > float(
            levels["finite_line_score"]
        )
        if finite_line_visible:
            expected_flags.append("finite-line-diagnostic")
        if finite_line_visible and float(metrics["parallel_pair_ratio"]) > float(
            levels["parallel_pair_ratio"]
        ):
            expected_flags.append("parallel-pair-diagnostic")
        if flags != expected_flags:
            raise RuntimeError(
                f"{context}.diagnostic_flags[{code}] recomputation drift"
            )
    if not isinstance(reveal, list) or len(reveal) != expected_count:
        raise RuntimeError(f"{context} identity reveal count drift")
    reveal_codes: set[str] = set()
    control_ids: set[str] = set()
    cluster_ids: set[str] = set()
    family_specs = {family["id"]: family for family in spec["control_families"]}
    allowed_families = set(family_specs)
    cluster_members: dict[str, list[dict[str, Any]]] = {}
    for index, item in enumerate(reveal):
        require_exact_keys(item, IDENTITY_REVEAL_KEYS, f"{context}.identity[{index}]")
        code = item["anonymous_code"]
        if code not in codes or code in reveal_codes:
            raise RuntimeError(f"{context} identity code drift")
        reveal_codes.add(code)
        for field in ("control_id", "condition_cluster_id"):
            if re.fullmatch(r"[0-9a-f]{24}", item[field] or "") is None:
                raise RuntimeError(f"{context}.identity[{index}].{field} drift")
        if item["control_id"] in control_ids:
            raise RuntimeError(f"{context} duplicate control identity")
        control_ids.add(item["control_id"])
        cluster_ids.add(item["condition_cluster_id"])
        cluster_members.setdefault(item["condition_cluster_id"], []).append(item)
        for field in ("control_sha256", "reference_sha256", "delta_float32_sha256"):
            if re.fullmatch(r"[0-9a-f]{64}", item[field] or "") is None:
                raise RuntimeError(f"{context}.identity[{index}].{field} drift")
        if (
            item["family"] not in allowed_families
            or require_exact_int(item["variant_index"], "variant_index", 0) < 0
            or require_exact_int(item["replicate"], "replicate", 0) < 0
            or type(item["polarity"]) is not int
            or item["polarity"] not in {-1, 1}
            or not isinstance(item["parameters"], dict)
        ):
            raise RuntimeError(f"{context}.identity[{index}] type drift")
        family = family_specs[item["family"]]
        variants = family[f"{split}_variants"]
        if (
            item["variant_index"] >= len(variants)
            or item["parameters"] != variants[item["variant_index"]]
            or item["replicate"] >= int(spec["splits"][split]["replicates_per_variant"])
            or item["polarity"] not in family["polarities"]
        ):
            raise RuntimeError(f"{context}.identity[{index}] catalog binding drift")
    if reveal_codes != codes:
        raise RuntimeError(f"{context} identity reveal coverage drift")
    expected_clusters = int(
        spec["independent_condition_clusters"]["expected_unique_clusters_per_split"]
    )
    if len(control_ids) != expected_count or len(cluster_ids) != expected_clusters:
        raise RuntimeError(f"{context} identity cardinality drift")
    observed_clusters_per_family = {family_id: 0 for family_id in family_specs}
    replicates = int(spec["splits"][split]["replicates_per_variant"])
    for cluster_id, members in cluster_members.items():
        private_identities = {
            (
                item["family"],
                item["variant_index"],
                canonical_json_bytes(item["parameters"]),
            )
            for item in members
        }
        if len(private_identities) != 1:
            raise RuntimeError(
                f"{context} cluster private-identity drift: {cluster_id}"
            )
        family_id = members[0]["family"]
        family = family_specs[family_id]
        expected_polarities = sorted(
            polarity for polarity in family["polarities"] for _ in range(replicates)
        )
        if sorted(item["polarity"] for item in members) != expected_polarities:
            raise RuntimeError(
                f"{context} cluster polarity/replicate drift: {cluster_id}"
            )
        if len({item["reference_sha256"] for item in members}) != 1:
            raise RuntimeError(f"{context} paired reference SHA drift: {cluster_id}")
        observed_clusters_per_family[family_id] += 1
    expected_clusters_per_family = {
        family_id: len(family[f"{split}_variants"])
        for family_id, family in family_specs.items()
    }
    if observed_clusters_per_family != expected_clusters_per_family:
        raise RuntimeError(f"{context} per-family cluster cardinality drift")


def _validate_normal_report_flags(report: dict[str, Any], context: str) -> None:
    validate_failure(report["failure"], context)
    if report["failure"] is not None:
        raise RuntimeError(f"{context} normal report cannot contain a failure")
    for key in ("passed", "one_shot_consumed"):
        if type(report[key]) is not bool:
            raise RuntimeError(f"{context}.{key} must be exact bool")
    if report["one_shot_consumed"] is not True:
        raise RuntimeError(f"{context} must record the consumed one-shot")
    parse_utc_timestamp(report["evaluated_at"], f"{context} evaluated_at")


def _calibration_candidate_thresholds(
    report: dict[str, Any], spec: dict[str, Any]
) -> list[float]:
    metric = spec["threshold_selection"]["hard_gate"]["metric"]
    return threshold_candidates(
        [float(item["metrics"][metric]) for item in report["measurements"]]
    )


def _selected_objective(
    endpoints: dict[str, Any], threshold: float, direction: str
) -> list[float]:
    artifact_rates = [
        float(endpoints[name]["cluster_macro_rate"])
        for name in (
            "grain_reject_detection",
            "tiny_speck_reject_detection",
            "microblob_reject_detection",
            "short_line_reject_detection",
            "parallel_bundle_reject_detection",
        )
    ]
    return [
        min(artifact_rates),
        float(endpoints["spot_reject_detection"]["cluster_macro_rate"]),
        float(endpoints["reject_detection"]["cluster_macro_rate"]),
        float(endpoints["severity3_detection"]["cluster_macro_rate"]),
        float(endpoints["clean_acceptance"]["cluster_macro_rate"]),
        float(endpoints["warning_acceptance"]["cluster_macro_rate"]),
        -threshold if direction == "maximum" else threshold,
    ]


def _validate_current_candidate_binding(
    candidate: dict[str, Any], endpoints: dict[str, Any], context: str
) -> None:
    clean = endpoints["clean_acceptance"]
    warning = endpoints["warning_acceptance"]
    expected = {
        "clean_cluster_count": clean["unique_cluster_count"],
        "warning_cluster_count": warning["unique_cluster_count"],
        "clean_cluster_acceptance": clean["cluster_macro_rate"],
        "warning_cluster_acceptance": warning["cluster_macro_rate"],
        "all_endpoints_passed": all(
            endpoint["passed"] for endpoint in endpoints.values()
        ),
    }
    if any(candidate[key] != value for key, value in expected.items()):
        raise RuntimeError(f"{context} endpoint/candidate binding drift")


def validate_calibration_report_nested(report: Any, spec: dict[str, Any]) -> None:
    context = "calibration report"
    require_exact_keys(report, CALIBRATION_REPORT_KEYS, context)
    if (
        report["artifact"] != "microtexture-v2-r4-calibration-report"
        or report["schema_version"] != "microtexture-v2-r4-calibration-report/2"
        or report["spec_sha256"] != SPEC_SHA256
    ):
        raise RuntimeError(f"{context} identity/schema drift")
    _validate_normal_report_flags(report, context)
    gate = spec["threshold_selection"]["hard_gate"]
    if report["hard_gate"] != gate:
        raise RuntimeError(f"{context} hard-gate drift")
    validate_endpoint_performance(
        report["endpoint_performance"], spec, "calibration", context
    )
    validate_threshold_selection_audit(
        report["threshold_selection_audit"],
        spec,
        f"{context}.threshold_selection_audit",
    )
    audit = report["threshold_selection_audit"]
    expected_candidates = _calibration_candidate_thresholds(report, spec)
    actual_candidates = [float(item["threshold"]) for item in audit["candidates"]]
    if actual_candidates != expected_candidates:
        raise RuntimeError(f"{context} threshold candidate derivation drift")
    endpoints = report["endpoint_performance"]
    all_endpoints_passed = all(endpoint["passed"] for endpoint in endpoints.values())
    status = report["selection_status"]
    threshold = report["hard_threshold"]
    if status == "no-admissible-threshold":
        if (
            threshold is not None
            or audit["admissible_candidate_count"] != 0
            or report["passed"] is not False
        ):
            raise RuntimeError(f"{context} no-admissible status drift")
        current_candidate = audit["candidates"][-1]
        evaluation_threshold = {
            "metric": gate["metric"],
            "direction": gate["direction"],
            "threshold": current_candidate["threshold"],
        }
    elif status in {"selected-and-passed", "selected-but-endpoint-failed"}:
        validate_hard_threshold(threshold, spec)
        if audit["admissible_candidate_count"] < 1 or float(
            threshold["threshold"]
        ) != float(audit["selected_threshold"]):
            raise RuntimeError(f"{context} selected threshold/audit drift")
        current_candidate = next(
            (
                item
                for item in audit["candidates"]
                if float(item["threshold"]) == float(threshold["threshold"])
            ),
            None,
        )
        if current_candidate is None or not current_candidate["admissible"]:
            raise RuntimeError(f"{context} selected candidate missing/inadmissible")
        expected_objective = _selected_objective(
            endpoints, float(threshold["threshold"]), threshold["direction"]
        )
        if audit["selected_objective"] != expected_objective:
            raise RuntimeError(f"{context} selected objective recomputation drift")
        rate_bindings = {
            "calibration_clean_cluster_acceptance": "clean_acceptance",
            "calibration_warning_cluster_acceptance": "warning_acceptance",
            "calibration_reject_cluster_detection": "reject_detection",
            "calibration_severity3_cluster_detection": "severity3_detection",
        }
        if any(
            float(threshold[target]) != float(endpoints[source]["cluster_macro_rate"])
            for target, source in rate_bindings.items()
        ):
            raise RuntimeError(f"{context} hard-threshold endpoint binding drift")
        expected_status = (
            "selected-and-passed"
            if all_endpoints_passed
            else "selected-but-endpoint-failed"
        )
        if status != expected_status or report["passed"] is not all_endpoints_passed:
            raise RuntimeError(f"{context} selected status/pass drift")
        evaluation_threshold = threshold
    else:
        raise RuntimeError(f"{context} selection status drift")
    _validate_current_candidate_binding(current_candidate, endpoints, context)
    validate_results_measurements_and_reveal(
        report, spec, "calibration", context, evaluation_threshold
    )


def validate_holdout_report_nested(
    report: Any,
    spec: dict[str, Any],
    expected_hard_threshold: dict[str, Any] | None = None,
) -> None:
    context = "holdout report"
    require_exact_keys(report, HOLDOUT_REPORT_KEYS, context)
    if (
        report["artifact"] != "microtexture-v2-r4-holdout-report"
        or report["schema_version"] != "microtexture-v2-r4-holdout-report/2"
        or report["authority"] is not True
        or report["spec_sha256"] != SPEC_SHA256
    ):
        raise RuntimeError(f"{context} identity/schema/authority drift")
    _validate_normal_report_flags(report, context)
    if (
        type(report["threshold_changes_authorized"]) is not bool
        or report["threshold_changes_authorized"] is not False
    ):
        raise RuntimeError(f"{context} threshold-change authorization drift")
    if report["hard_gate"] != spec["threshold_selection"]["hard_gate"]:
        raise RuntimeError(f"{context} hard-gate drift")
    validate_hard_threshold(report["hard_threshold"], spec)
    if (
        expected_hard_threshold is not None
        and report["hard_threshold"] != expected_hard_threshold
    ):
        raise RuntimeError(f"{context} frozen hard-threshold drift")
    validate_endpoint_performance(
        report["endpoint_performance"], spec, "holdout", context
    )
    all_endpoints_passed = all(
        endpoint["passed"] for endpoint in report["endpoint_performance"].values()
    )
    if report["passed"] is not all_endpoints_passed:
        raise RuntimeError(f"{context} endpoint/pass recomputation drift")
    validate_results_measurements_and_reveal(
        report, spec, "holdout", context, report["hard_threshold"]
    )


def validate_locked_clean_reference_report_nested(
    report: Any,
    spec: dict[str, Any],
    expected_hard_threshold: dict[str, Any] | None = None,
) -> None:
    context = "locked-clean-reference report"
    require_exact_keys(report, LOCKED_CLEAN_REFERENCE_REPORT_KEYS, context)
    if (
        report["artifact"] != "microtexture-v2-r4-locked-clean-reference-report"
        or report["schema_version"]
        != "microtexture-v2-r4-locked-clean-reference-report/2"
        or report["spec_sha256"] != SPEC_SHA256
    ):
        raise RuntimeError(f"{context} identity/schema drift")
    _validate_normal_report_flags(report, context)
    for key in ("hard_composite_accepted",):
        if type(report[key]) is not bool:
            raise RuntimeError(f"{context}.{key} must be exact bool")
    validate_metric_values(report["metrics"], spec, f"{context}.metrics")
    validate_hard_threshold(report["hard_threshold"], spec)
    if (
        expected_hard_threshold is not None
        and report["hard_threshold"] != expected_hard_threshold
    ):
        raise RuntimeError(f"{context} frozen hard-threshold drift")
    threshold = report["hard_threshold"]
    metric_value = float(report["metrics"][threshold["metric"]])
    limit = float(threshold["threshold"])
    failed = (
        metric_value > limit
        if threshold["direction"] == "maximum"
        else metric_value < limit
    )
    accepted = not failed
    if (
        report["hard_composite_accepted"] is not accepted
        or report["passed"] is not accepted
    ):
        raise RuntimeError(f"{context} threshold/pass recomputation drift")


def validate_hard_threshold(value: Any, spec: dict[str, Any]) -> None:
    require_exact_keys(value, HARD_THRESHOLD_KEYS, "hard threshold")
    gate = spec["threshold_selection"]["hard_gate"]
    if value["metric"] != gate["metric"] or value["direction"] != gate["direction"]:
        raise RuntimeError("hard-threshold gate binding drift")
    for key in (
        "threshold",
        "calibration_clean_cluster_acceptance",
        "calibration_warning_cluster_acceptance",
        "calibration_reject_cluster_detection",
        "calibration_severity3_cluster_detection",
    ):
        if not isinstance(value[key], (int, float)) or not math.isfinite(
            float(value[key])
        ):
            raise RuntimeError(f"hard threshold non-finite {key}")
    if type(value["threshold"]) not in {int, float} or float(value["threshold"]) < 0:
        raise RuntimeError("hard threshold must be a non-negative real number")
    for key in (
        "calibration_clean_cluster_acceptance",
        "calibration_warning_cluster_acceptance",
        "calibration_reject_cluster_detection",
        "calibration_severity3_cluster_detection",
    ):
        if type(value[key]) not in {int, float} or not 0.0 <= float(value[key]) <= 1.0:
            raise RuntimeError(f"hard threshold rate is outside 0..1: {key}")
    if value["selection_objective"] != spec["threshold_selection"]["objective_order"]:
        raise RuntimeError("hard-threshold objective binding drift")


def _verify_marker(
    root: Path,
    relative: str,
    expected_sha: str,
    expected_keys: set[str],
    expected_values: dict[str, Any],
) -> dict[str, Any]:
    marker_path = exact_artifact_path_without_links(
        root, root / relative, relative, must_exist=True
    )
    payload = marker_path.read_bytes()
    if sha256_bytes(payload) != expected_sha:
        raise RuntimeError(f"one-shot marker SHA drift: {relative}")
    marker = json.loads(payload.decode("utf-8"))
    require_exact_keys(marker, expected_keys, f"one-shot marker {relative}")
    for key, expected in expected_values.items():
        if marker[key] != expected:
            raise RuntimeError(f"one-shot marker binding drift: {relative}/{key}")
    if marker["one_shot_consumed"] is not True:
        raise RuntimeError(f"one-shot marker is not consumed: {relative}")
    parse_utc_timestamp(marker["started_at"], f"one-shot marker {relative} started_at")
    return marker


def load_calibration_report(
    state: dict[str, Any], *, require_completion: bool = True
) -> tuple[dict[str, Any], str, dict[str, Any] | None, str | None]:
    root, spec = state["artifact_root"], load_spec()
    _, failure_relative = _stage_artifact_paths("calibration")
    failure_path = exact_artifact_path_without_links(
        root,
        root / failure_relative,
        failure_relative,
        must_exist=False,
    )
    if failure_path.exists():
        raise RuntimeError(
            "calibration failure report exists; normal report is not authority"
        )
    report_relative = "reports/calibration-report.json"
    report_path = exact_artifact_path_without_links(
        root, root / report_relative, report_relative, must_exist=True
    )
    report_bytes = report_path.read_bytes()
    report_sha = sha256_bytes(report_bytes)
    report = json.loads(report_bytes.decode("utf-8"))
    validate_calibration_report_nested(report, spec)
    if (
        report["spec_sha256"] != SPEC_SHA256
        or report["blind_key_commitment"] != state["blind_key_commitment"]
        or report["runtime"] != state["runtime"]
        or report["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or report["hard_gate"] != spec["threshold_selection"]["hard_gate"]
    ):
        raise RuntimeError("calibration report trust-chain binding drift")
    marker = _verify_marker(
        root,
        "markers/calibration-evaluation-started.json",
        report["evaluation_marker_sha256"],
        CALIBRATION_MARKER_KEYS,
        {
            "artifact": "microtexture-v2-r4-calibration-evaluation-started",
            "schema_version": "microtexture-v2-r4-calibration-marker/2",
            "spec_sha256": SPEC_SHA256,
            "blind_key_commitment": state["blind_key_commitment"],
            "manifest_sha256": report["manifest_sha256"],
            "labels_sha256": report["labels_sha256"],
            "captured_git_head": report["captured_git_head"],
            "runtime": state["runtime"],
            "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        },
    )
    marker_started_at = parse_utc_timestamp(
        marker["started_at"], "calibration marker started_at"
    )
    evaluated_at = parse_utc_timestamp(
        report["evaluated_at"], "calibration report evaluated_at"
    )
    if marker_started_at > evaluated_at:
        raise RuntimeError("calibration report predates its one-shot marker")
    assert_git_ancestor(report["captured_git_head"], state["captured_head"])
    manifest, manifest_sha = load_control_manifest(
        "calibration",
        state,
        expected_captured_head=report["captured_git_head"],
        verify_payload_hashes=True,
    )
    if manifest_sha != report["manifest_sha256"]:
        raise RuntimeError("actual calibration manifest SHA mismatch")
    labels_relative = spec["labels"]["sealed_authority_paths"]["calibration"]
    labels_path = exact_artifact_path_without_links(
        root,
        root / labels_relative,
        labels_relative,
        must_exist=True,
    )
    labels_bytes = labels_path.read_bytes()
    labels_sha = sha256_bytes(labels_bytes)
    if labels_sha != report["labels_sha256"]:
        raise RuntimeError("actual calibration labels SHA mismatch")
    labels_payload = json.loads(labels_bytes.decode("utf-8"))
    labels = validate_vision_labels_payload(
        labels_payload,
        "calibration",
        manifest,
        manifest_sha,
        state,
    )
    validate_report_evaluation_bindings(report, manifest, labels, "calibration", spec)
    validate_secret_catalog_report_binding(report, manifest, "calibration", state)

    frozen_relative = "thresholds-frozen.json"
    frozen_path = exact_artifact_path_without_links(
        root, root / frozen_relative, frozen_relative, must_exist=False
    )
    frozen: dict[str, Any] | None = None
    frozen_sha: str | None = None
    frozen_at: datetime | None = None
    if report["passed"]:
        frozen_path = exact_artifact_path_without_links(
            root, root / frozen_relative, frozen_relative, must_exist=True
        )
        frozen_bytes = frozen_path.read_bytes()
        frozen_sha = sha256_bytes(frozen_bytes)
        frozen = json.loads(frozen_bytes.decode("utf-8"))
        require_exact_keys(frozen, FROZEN_KEYS, "frozen thresholds")
        if (
            frozen["artifact"] != "microtexture-v2-r4-thresholds-frozen"
            or frozen["schema_version"] != "microtexture-v2-r4-thresholds/2"
            or frozen["authority"] is not True
            or frozen["spec_sha256"] != SPEC_SHA256
            or frozen["blind_key_commitment"] != state["blind_key_commitment"]
            or frozen["runtime"] != state["runtime"]
            or frozen["implementation_bindings_sha256"]
            != state["implementation_bindings_sha256"]
            or frozen["hard_gate"] != spec["threshold_selection"]["hard_gate"]
            or frozen["endpoint_definitions"]
            != spec["threshold_selection"]["endpoint_definitions"]
            or frozen["holdout_allowed_count"] != 1
            or frozen["threshold_changes_forbidden"] is not True
            or frozen["calibration_manifest_sha256"] != manifest_sha
            or frozen["calibration_report_sha256"] != report_sha
            or frozen["calibration_evaluation_marker_sha256"]
            != report["evaluation_marker_sha256"]
            or frozen["calibration_captured_git_head"] != report["captured_git_head"]
            or frozen["hard_gate"] != report["hard_gate"]
            or frozen["hard_threshold"] != report["hard_threshold"]
            or report["selection_status"] != "selected-and-passed"
        ):
            raise RuntimeError("calibration report/frozen binding drift")
        validate_hard_threshold(frozen["hard_threshold"], spec)
        frozen_at = parse_utc_timestamp(frozen["frozen_at"], "threshold frozen_at")
        if evaluated_at > frozen_at:
            raise RuntimeError("thresholds were frozen before calibration evaluation")
    elif frozen_path.exists():
        raise RuntimeError("failed calibration must not produce frozen thresholds")

    if require_completion:
        load_stage_completion(
            stage="calibration",
            state=state,
            expected_marker_sha=report["evaluation_marker_sha256"],
            expected_report_sha=report_sha,
            expected_captured_head=report["captured_git_head"],
            expected_passed=report["passed"],
            expected_result_status=report["selection_status"],
            expected_bindings={
                "manifest_sha256": manifest_sha,
                "labels_sha256": labels_sha,
                "frozen_thresholds_sha256": frozen_sha,
                "threshold_authority_receipt_sha256": None,
                "locked_clean_reference_sha256": None,
            },
            marker_started_at=marker_started_at,
            report_evaluated_at=evaluated_at,
            frozen_at=frozen_at,
        )
    return report, report_sha, frozen, frozen_sha


def load_frozen_thresholds(state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    report, _, frozen, frozen_sha = load_calibration_report(state)
    if report["passed"] is not True or frozen is None or frozen_sha is None:
        raise RuntimeError("calibration did not produce passing frozen authority")
    return frozen, frozen_sha


def load_locked_clean_reference_report(
    state: dict[str, Any], *, require_completion: bool = True
) -> tuple[
    dict[str, Any],
    str,
    dict[str, Any],
    str,
    dict[str, Any] | None,
]:
    spec = load_spec()
    frozen, frozen_sha = load_frozen_thresholds(state)
    root = state["artifact_root"]
    _, failure_relative = _stage_artifact_paths("locked-clean-reference")
    locked_failure = exact_artifact_path_without_links(
        root,
        root / failure_relative,
        failure_relative,
        must_exist=False,
    )
    if locked_failure.exists():
        raise RuntimeError(
            "locked-clean-reference failure report exists; normal report is not authority"
        )
    locked_spec = spec["locked_clean_reference"]
    locked_relative = locked_spec["report_repo_relative_artifact_path"]
    locked_path = exact_artifact_path_without_links(
        root,
        root / locked_relative,
        locked_relative,
        must_exist=True,
    )
    locked_bytes = locked_path.read_bytes()
    locked_sha = sha256_bytes(locked_bytes)
    locked = json.loads(locked_bytes.decode("utf-8"))
    validate_locked_clean_reference_report_nested(
        locked, spec, frozen["hard_threshold"]
    )
    locked_marker = _verify_marker(
        root,
        "markers/locked-clean-reference-validation-started.json",
        locked["evaluation_marker_sha256"],
        LOCKED_CLEAN_REFERENCE_MARKER_KEYS,
        {
            "artifact": "microtexture-v2-r4-locked-clean-reference-validation-started",
            "schema_version": "microtexture-v2-r4-locked-clean-reference-marker/2",
            "spec_sha256": SPEC_SHA256,
            "blind_key_commitment": state["blind_key_commitment"],
            "frozen_thresholds_sha256": frozen_sha,
            "captured_git_head": frozen["calibration_captured_git_head"],
            "runtime": state["runtime"],
            "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        },
    )
    frozen_at = parse_utc_timestamp(frozen["frozen_at"], "threshold frozen_at")
    locked_evaluated_at = parse_utc_timestamp(
        locked["evaluated_at"], "locked-clean-reference evaluated_at"
    )
    if locked_evaluated_at < frozen_at:
        raise RuntimeError(
            "locked-clean-reference evaluation predates threshold freeze"
        )
    locked_started_at = parse_utc_timestamp(
        locked_marker["started_at"], "locked-clean-reference marker started_at"
    )
    if locked_started_at < frozen_at:
        raise RuntimeError("locked-clean-reference marker predates threshold freeze")
    if locked_started_at > locked_evaluated_at:
        raise RuntimeError("locked-clean-reference report predates its marker")
    if (
        locked["artifact"] != "microtexture-v2-r4-locked-clean-reference-report"
        or locked["schema_version"]
        != "microtexture-v2-r4-locked-clean-reference-report/2"
        or locked["spec_sha256"] != SPEC_SHA256
        or locked["runtime"] != state["runtime"]
        or locked["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or locked["frozen_thresholds_sha256"] != frozen_sha
        or locked["blind_key_commitment"] != state["blind_key_commitment"]
        or locked["locked_clean_reference_sha256"] != locked_spec["sha256"]
        or locked["source_crop_xywh"] != locked_spec["source_crop_xywh"]
        or locked["metric_window_xywh_within_source_crop"]
        != locked_spec["metric_window_xywh_within_source_crop"]
        or locked["effective_source_xywh"] != locked_spec["effective_source_xywh"]
        or locked["hard_threshold"] != frozen["hard_threshold"]
        or locked["captured_git_head"] != frozen["calibration_captured_git_head"]
    ):
        raise RuntimeError("locked-clean-reference report trust-chain binding drift")
    completion = None
    if require_completion:
        completion, _ = load_stage_completion(
            stage="locked-clean-reference",
            state=state,
            expected_marker_sha=locked["evaluation_marker_sha256"],
            expected_report_sha=locked_sha,
            expected_captured_head=locked["captured_git_head"],
            expected_passed=locked["passed"],
            expected_result_status=(
                "accepted" if locked["hard_composite_accepted"] else "rejected"
            ),
            expected_bindings={
                "manifest_sha256": None,
                "labels_sha256": None,
                "frozen_thresholds_sha256": frozen_sha,
                "threshold_authority_receipt_sha256": None,
                "locked_clean_reference_sha256": locked_spec["sha256"],
            },
            marker_started_at=locked_started_at,
            report_evaluated_at=locked_evaluated_at,
            frozen_at=frozen_at,
        )
    return locked, locked_sha, frozen, frozen_sha, completion


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
    locked, locked_sha, frozen, frozen_sha, completion = (
        load_locked_clean_reference_report(state)
    )
    if (
        locked["passed"] is not True
        or locked["failure"] is not None
        or locked["one_shot_consumed"] is not True
        or locked["hard_composite_accepted"] is not True
        or completion is None
        or completion["passed"] is not True
    ):
        raise RuntimeError("locked-clean-reference report is not a passing validation")
    frozen_at = parse_utc_timestamp(frozen["frozen_at"], "threshold frozen_at")
    locked_evaluated_at = parse_utc_timestamp(
        locked["evaluated_at"], "locked-clean-reference evaluated_at"
    )
    locked_completed_at = parse_utc_timestamp(
        completion["completed_at"], "locked-clean-reference completion completed_at"
    )
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
    if reviewed_at < max(frozen_at, locked_evaluated_at, locked_completed_at):
        raise RuntimeError(
            "threshold authority review predates freeze/locked completion"
        )
    tolerance = timedelta(seconds=int(expected["clock_future_tolerance_seconds"]))
    if reviewed_at > datetime.now(timezone.utc) + tolerance:
        raise RuntimeError("threshold authority reviewed_at is in the future")
    if (
        receipt["artifact"] != "microtexture-v2-r4-threshold-authority"
        or receipt["schema_version"] != expected["schema_version"]
        or receipt["approval"] != expected["required_approval"]
        or receipt["spec_sha256"] != SPEC_SHA256
        or receipt["frozen_thresholds_sha256"] != frozen_sha
        or receipt["calibration_report_sha256"] != frozen["calibration_report_sha256"]
        or receipt["calibration_manifest_sha256"]
        != frozen["calibration_manifest_sha256"]
        or receipt["locked_clean_reference_report_sha256"] != locked_sha
        or receipt["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or receipt["blind_key_commitment"] != state["blind_key_commitment"]
        or receipt["runtime"] != state["runtime"]
        or receipt["calibration_captured_git_head"]
        != frozen["calibration_captured_git_head"]
        or receipt["locked_clean_reference_captured_git_head"]
        != locked["captured_git_head"]
    ):
        raise RuntimeError(
            "external threshold authority receipt binding/approval drift"
        )
    return receipt, sha256_bytes(payload)


def load_holdout_report(
    state: dict[str, Any], *, require_completion: bool = True
) -> tuple[dict[str, Any], str]:
    if "threshold_authority" not in state or "threshold_authority_sha256" not in state:
        raise RuntimeError(
            "holdout report reload requires validated threshold authority"
        )
    root, spec = state["artifact_root"], load_spec()
    _, failure_relative = _stage_artifact_paths("holdout")
    failure_path = exact_artifact_path_without_links(
        root,
        root / failure_relative,
        failure_relative,
        must_exist=False,
    )
    if failure_path.exists():
        raise RuntimeError(
            "holdout failure report exists; normal report is not authority"
        )
    frozen, frozen_sha = load_frozen_thresholds(state)
    if frozen_sha != state["threshold_authority"]["frozen_thresholds_sha256"]:
        raise RuntimeError("holdout reload receipt/frozen SHA drift")
    manifest, manifest_sha = load_control_manifest(
        "holdout",
        state,
        expected_captured_head=state["captured_head"],
        verify_payload_hashes=True,
    )
    report_relative = "reports/holdout-report.json"
    report_path = exact_artifact_path_without_links(
        root,
        root / report_relative,
        report_relative,
        must_exist=True,
    )
    report_bytes = report_path.read_bytes()
    report_sha = sha256_bytes(report_bytes)
    report = json.loads(report_bytes.decode("utf-8"))
    validate_holdout_report_nested(report, spec, frozen["hard_threshold"])
    if (
        report["spec_sha256"] != SPEC_SHA256
        or report["blind_key_commitment"] != state["blind_key_commitment"]
        or report["manifest_sha256"] != manifest_sha
        or report["frozen_thresholds_sha256"] != frozen_sha
        or report["threshold_authority_receipt_sha256"]
        != state["threshold_authority_sha256"]
        or report["captured_git_head"] != state["captured_head"]
        or report["runtime"] != state["runtime"]
        or report["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or report["hard_gate"] != frozen["hard_gate"]
        or report["hard_threshold"] != frozen["hard_threshold"]
    ):
        raise RuntimeError("holdout report trust-chain binding drift")
    marker = _verify_marker(
        root,
        "markers/holdout-evaluation-started.json",
        report["evaluation_marker_sha256"],
        HOLDOUT_MARKER_KEYS,
        {
            "artifact": "microtexture-v2-r4-holdout-evaluation-started",
            "schema_version": "microtexture-v2-r4-holdout-marker/2",
            "spec_sha256": SPEC_SHA256,
            "blind_key_commitment": state["blind_key_commitment"],
            "manifest_sha256": manifest_sha,
            "labels_sha256": report["labels_sha256"],
            "frozen_thresholds_sha256": frozen_sha,
            "threshold_authority_receipt_sha256": state["threshold_authority_sha256"],
            "captured_git_head": state["captured_head"],
            "runtime": state["runtime"],
            "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        },
    )
    marker_started_at = parse_utc_timestamp(
        marker["started_at"], "holdout marker started_at"
    )
    evaluated_at = parse_utc_timestamp(report["evaluated_at"], "holdout evaluated_at")
    reviewed_at = parse_utc_timestamp(
        state["threshold_authority"]["reviewed_at"], "threshold authority reviewed_at"
    )
    if reviewed_at > marker_started_at or marker_started_at > evaluated_at:
        raise RuntimeError("holdout receipt/marker/report timestamp order drift")
    labels_relative = spec["labels"]["sealed_authority_paths"]["holdout"]
    labels_path = exact_artifact_path_without_links(
        root,
        root / labels_relative,
        labels_relative,
        must_exist=True,
    )
    labels_bytes = labels_path.read_bytes()
    labels_sha = sha256_bytes(labels_bytes)
    if labels_sha != report["labels_sha256"]:
        raise RuntimeError("actual sealed holdout labels SHA mismatch")
    labels_payload = json.loads(labels_bytes.decode("utf-8"))
    labels = validate_vision_labels_payload(
        labels_payload, "holdout", manifest, manifest_sha, state
    )
    validate_report_evaluation_bindings(report, manifest, labels, "holdout", spec)
    validate_secret_catalog_report_binding(report, manifest, "holdout", state)
    if require_completion:
        load_stage_completion(
            stage="holdout",
            state=state,
            expected_marker_sha=report["evaluation_marker_sha256"],
            expected_report_sha=report_sha,
            expected_captured_head=report["captured_git_head"],
            expected_passed=report["passed"],
            expected_result_status="passed" if report["passed"] else "failed",
            expected_bindings={
                "manifest_sha256": manifest_sha,
                "labels_sha256": labels_sha,
                "frozen_thresholds_sha256": frozen_sha,
                "threshold_authority_receipt_sha256": state[
                    "threshold_authority_sha256"
                ],
                "locked_clean_reference_sha256": spec["locked_clean_reference"][
                    "sha256"
                ],
            },
            marker_started_at=marker_started_at,
            report_evaluated_at=evaluated_at,
            frozen_at=parse_utc_timestamp(frozen["frozen_at"], "threshold frozen_at"),
        )
    return report, report_sha
