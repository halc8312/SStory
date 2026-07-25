"""r5 blinded calibration, locked-clean validation, and one-shot holdout."""

from __future__ import annotations

import argparse
import io
import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage

from common import (
    CALIBRATION_MARKER_KEYS,
    FROZEN_KEYS,
    HOLDOUT_MARKER_KEYS,
    LOCKED_CLEAN_REFERENCE_MARKER_KEYS,
    ONE_SHOT_FAILURE_BINDING_KEYS,
    ONE_SHOT_FAILURE_REPORT_KEYS,
    SPEC_SHA256,
    assert_head_unchanged,
    blind_commitment,
    blind_key,
    canonical_json_bytes,
    cluster_macro_rate,
    evaluate_endpoints_from_measurements,
    exact_artifact_path_without_links,
    load_calibration_report,
    load_control_manifest,
    load_frozen_thresholds,
    load_holdout_report,
    load_locked_clean_reference_report,
    load_spec,
    operation_preflight,
    require_exact_keys,
    select_hard_threshold_from_measurements,
    sha256_bytes,
    threshold_candidates,
    utc_timestamp,
    validate_calibration_report_nested,
    validate_failure,
    validate_holdout_report_nested,
    validate_locked_clean_reference_report_nested,
    validate_private_vision_label_audits,
    validate_report_evaluation_bindings,
    validate_vision_labels_payload,
    write_bytes_exclusive,
    write_json_exclusive,
    write_stage_completion_exclusive,
)
from control_catalog import (
    ExpectedControl,
    contact_sheet_pages,
    expected_controls,
    validate_manifest_public_bindings,
)
from metrics_v2_r5 import measure


SHEET_KEYS = {
    "view_id",
    "scale_percent",
    "source_crop_xywh",
    "page_index",
    "path",
    "sha256",
    "item_codes",
}


def _decode_image_once(path: Path, expected_sha: str, mode: str) -> np.ndarray:
    payload = path.read_bytes()
    if sha256_bytes(payload) != expected_sha:
        raise RuntimeError(f"image SHA drift: {path}")
    with Image.open(io.BytesIO(payload)) as image:
        converted = image.convert(mode)
        converted.load()
        return np.asarray(converted, dtype=np.uint8).copy()


def _validate_sheet_once(
    path: Path,
    expected_bytes: bytes,
    expected_sha: str,
    expected_dimensions: tuple[int, int],
) -> None:
    payload = path.read_bytes()
    if payload != expected_bytes or sha256_bytes(payload) != expected_sha:
        raise RuntimeError(f"contact sheet exact bytes/SHA drift: {path}")
    with Image.open(io.BytesIO(payload)) as image:
        if image.mode != "L" or image.size != expected_dimensions:
            raise RuntimeError(f"contact sheet mode/dimensions drift: {path}")
        image.load()


def _load_manifest(split: str, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    return load_control_manifest(
        split,
        state,
        expected_captured_head=state["captured_head"],
        verify_payload_hashes=True,
    )


def _load_labels(
    path: Path,
    split: str,
    manifest: dict[str, Any],
    manifest_sha: str,
    state: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], str, bytes]:
    root = state["artifact_root"]
    expected_relative = load_spec()["labels"]["exact_artifact_paths"][split]
    checked = exact_artifact_path_without_links(
        root,
        path,
        expected_relative,
        must_exist=True,
    )
    payload = checked.read_bytes()
    value = json.loads(payload.decode("utf-8"))
    labels = validate_vision_labels_payload(value, split, manifest, manifest_sha, state)
    return labels, sha256_bytes(payload), payload


def _prepare_sealed_label_path(split: str, state: dict[str, Any]) -> Path:
    root = state["artifact_root"]
    relative = load_spec()["labels"]["sealed_authority_paths"][split]
    path = exact_artifact_path_without_links(
        root,
        root / relative,
        relative,
        must_exist=False,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    exact_artifact_path_without_links(
        root,
        path,
        relative,
        must_exist=False,
    )
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"{split} sealed reviewed-label authority already exists")
    return path


def _seal_labels_after_marker(
    *,
    split: str,
    original_payload: bytes,
    expected_sha: str,
    sealed_path: Path,
    manifest: dict[str, Any],
    manifest_sha: str,
    state: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    root = state["artifact_root"]
    spec = load_spec()
    input_relative = spec["labels"]["exact_artifact_paths"][split]
    input_path = exact_artifact_path_without_links(
        root,
        root / input_relative,
        input_relative,
        must_exist=True,
    )
    if input_path.read_bytes() != original_payload:
        raise RuntimeError(f"{split} reviewed labels changed before sealing")
    if sha256_bytes(original_payload) != expected_sha:
        raise RuntimeError(f"{split} reviewed-label in-memory SHA drift")
    write_bytes_exclusive(root, sealed_path, original_payload)
    sealed_relative = spec["labels"]["sealed_authority_paths"][split]
    checked = exact_artifact_path_without_links(
        root,
        sealed_path,
        sealed_relative,
        must_exist=True,
    )
    sealed_payload = checked.read_bytes()
    if (
        sealed_payload != original_payload
        or sha256_bytes(sealed_payload) != expected_sha
    ):
        raise RuntimeError(f"{split} sealed reviewed-label bytes/SHA drift")
    value = json.loads(sealed_payload.decode("utf-8"))
    return validate_vision_labels_payload(value, split, manifest, manifest_sha, state)


def _bind_after_marker(
    manifest: dict[str, Any], split: str, key: bytes, state: dict[str, Any]
) -> dict[tuple[str, str, str, str], ExpectedControl]:
    root, spec = state["artifact_root"], load_spec()
    expected = expected_controls(spec, split, key)
    validate_manifest_public_bindings(manifest, expected)
    expected_pages = contact_sheet_pages(spec, split, expected)
    expected_bundle = [page.manifest_entry() for page in expected_pages]
    if manifest["contact_sheet_bundle"] != expected_bundle:
        raise RuntimeError(f"{split} secret-derived contact-sheet bundle drift")
    dimensions = tuple(
        int(value) for value in spec["contact_sheets"]["sheet_dimensions"]
    )
    for index, page in enumerate(expected_pages):
        require_exact_keys(
            expected_bundle[index], SHEET_KEYS, f"{split} sheet[{index}]"
        )
        _validate_sheet_once(
            exact_artifact_path_without_links(
                root, root / page.path, page.path, must_exist=True
            ),
            page.png_bytes,
            page.sha256,
            dimensions,
        )
    return {control.public_binding_tuple: control for control in expected}


def _validate_private_label_audits_after_marker(
    labels: dict[str, dict[str, Any]],
    identities: dict[tuple[str, str, str, str], ExpectedControl],
    split: str,
) -> None:
    validate_private_vision_label_audits(
        labels,
        [
            {
                "anonymous_code": control.anonymous_code,
                "private_role": control.private_role,
                "duplicate_audit_group": control.duplicate_audit_group,
            }
            for control in identities.values()
        ],
        f"{split} sealed labels",
    )


def _exact_metric_window(values: np.ndarray, spec: dict[str, Any]) -> np.ndarray:
    expected_canvas = (int(spec["canvas"]["height"]), int(spec["canvas"]["width"]))
    if values.shape != expected_canvas:
        raise RuntimeError(
            f"r5 control canvas drift: {values.shape} != {expected_canvas}"
        )
    x, y, width, height = [
        int(value) for value in spec["canvas"]["metric_window"]["xywh"]
    ]
    crop = values[y : y + height, x : x + width]
    expected = tuple(
        int(value) for value in spec["metric_definition"]["expected_shape_hw"]
    )
    if crop.shape != expected:
        raise RuntimeError("r5 exact metric-window crop drift")
    return crop


def _measure_records(
    manifest: dict[str, Any],
    identities: dict[tuple[str, str, str, str], ExpectedControl],
    state: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    spec = load_spec()
    definition = spec["metric_definition"]
    eligible_role = spec["threshold_selection"]["endpoint_eligible_private_role"]
    measured, reveal = [], []
    clusters: dict[str, str] = {}
    for record in manifest["records"]:
        identity_key = (
            record["anonymous_code"],
            record["control_commitment"],
            record["reference_commitment"],
            record["delta_commitment"],
        )
        identity = identities[identity_key]
        control = _exact_metric_window(identity.control, spec)
        reference = _exact_metric_window(identity.reference, spec)
        code = record["anonymous_code"]
        measured.append(
            {"anonymous_code": code, "metrics": measure(control, reference, definition)}
        )
        if identity.private_role == eligible_role:
            clusters[code] = identity.condition_cluster_id
        reveal.append(
            {
                "anonymous_code": code,
                "family": identity.family,
                "control_id": identity.control_id,
                "condition_cluster_id": identity.condition_cluster_id,
                "variant_index": identity.variant_index,
                "replicate": identity.replicate,
                "polarity": identity.polarity,
                "parameters": identity.parameters,
                "control_sha256": identity.control_sha256,
                "reference_sha256": identity.reference_sha256,
                "delta_float32_sha256": identity.delta_float32_sha256,
                "private_role": identity.private_role,
                "foundation_id": identity.foundation_id,
                "duplicate_audit_group": identity.duplicate_audit_group,
            }
        )
    return measured, reveal, clusters


def _fails(value: float, threshold: float, direction: str) -> bool:
    return value > threshold if direction == "maximum" else value < threshold


def _threshold_candidates(values: list[float]) -> list[float]:
    return threshold_candidates(values)


def _cluster_macro_rate(
    codes: list[str],
    rejected_by_code: dict[str, bool],
    clusters: dict[str, str],
    expected_result: str,
) -> tuple[float, int, int]:
    return cluster_macro_rate(codes, rejected_by_code, clusters, expected_result)


def _evaluate_endpoints(
    threshold: float,
    measured: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    clusters: dict[str, str],
    split: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    return evaluate_endpoints_from_measurements(
        threshold, measured, labels, clusters, split, load_spec()
    )


def _diagnostic_flags(measured: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    flags: dict[str, list[str]] = {}
    for code, record in measured.items():
        metrics = record["metrics"]
        names = []
        for metric, name in (
            ("grain_score", "grain-branch-diagnostic"),
            ("spot_score", "spot-branch-diagnostic"),
            ("finite_line_score", "finite-line-branch-diagnostic"),
            ("parallel_bundle_score", "parallel-bundle-branch-diagnostic"),
        ):
            if float(metrics[metric]) > 0.5:
                names.append(name)
        flags[code] = names
    return flags


def _select_hard_threshold(
    measured: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    clusters: dict[str, str],
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any],
    dict[str, dict[str, Any]],
    str,
    dict[str, Any],
]:
    return select_hard_threshold_from_measurements(
        measured, labels, clusters, load_spec()
    )


def _write_one_shot_failure_report(
    *,
    stage: str,
    state: dict[str, Any],
    marker_sha: str,
    bindings: dict[str, str | None],
    phase: str,
    error: BaseException,
) -> None:
    require_exact_keys(
        bindings, ONE_SHOT_FAILURE_BINDING_KEYS, f"{stage} failure bindings"
    )
    message = str(error).strip() or "exception without a message"
    message = re.sub(r"(?i)\b[0-9a-f]{64}\b", "[redacted-64-hex]", message)[:512]
    failure = {
        "phase": phase[:512] or "unknown-post-marker-phase",
        "type": type(error).__name__[:512] or "Exception",
        "message": message,
    }
    validate_failure(failure, f"{stage} one-shot failure report")
    report = {
        "artifact": "microtexture-v2-r5-one-shot-failure-report",
        "schema_version": "microtexture-v2-r5-one-shot-failure-report/2",
        "stage": stage,
        "spec_sha256": SPEC_SHA256,
        "blind_key_commitment": state["blind_key_commitment"],
        "evaluation_marker_sha256": marker_sha,
        "captured_git_head": state["captured_head"],
        "runtime": state["runtime"],
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "failed_at": utc_timestamp(),
        "one_shot_consumed": True,
        "bindings": bindings,
        "failure": failure,
    }
    require_exact_keys(report, ONE_SHOT_FAILURE_REPORT_KEYS, f"{stage} failure report")
    failure_relative = load_spec()["one_shot_failure_reporting"][
        "exception_report_paths"
    ][stage]
    write_json_exclusive(
        state["artifact_root"],
        state["artifact_root"] / failure_relative,
        report,
    )


def _record_post_marker_failure(
    *,
    stage: str,
    state: dict[str, Any],
    marker_sha: str,
    bindings: dict[str, str | None],
    phase: str,
    error: BaseException,
) -> None:
    try:
        _write_one_shot_failure_report(
            stage=stage,
            state=state,
            marker_sha=marker_sha,
            bindings=bindings,
            phase=phase,
            error=error,
        )
    except BaseException as report_error:
        try:
            error.add_note(
                "r5 failure-report persistence also failed; the exclusive marker "
                f"remains closure evidence ({type(report_error).__name__})"
            )
        except BaseException:
            pass


@contextmanager
def _one_shot_stage_guard(
    *,
    stage: str,
    state: dict[str, Any],
    marker: dict[str, Any],
    marker_relative: str,
    phase: Callable[[], str],
    bindings: Callable[[], dict[str, str | None]],
) -> Iterator[str]:
    """Write the durable marker inside the post-marker exception boundary."""

    root = state["artifact_root"]
    marker_path = exact_artifact_path_without_links(
        root, root / marker_relative, marker_relative, must_exist=False
    )
    marker_payload = canonical_json_bytes(marker)
    expected_marker_sha = sha256_bytes(marker_payload)
    try:
        marker_sha = write_json_exclusive(root, marker_path, marker)
        if marker_sha != expected_marker_sha:
            raise RuntimeError(f"{stage} marker write SHA drift")
        yield marker_sha
    except BaseException as error:
        marker_is_durable = False
        try:
            checked = exact_artifact_path_without_links(
                root, marker_path, marker_relative, must_exist=True
            )
            marker_is_durable = checked.read_bytes() == marker_payload
        except BaseException:
            marker_is_durable = False
        if marker_is_durable:
            _record_post_marker_failure(
                stage=stage,
                state=state,
                marker_sha=expected_marker_sha,
                bindings=bindings(),
                phase=phase(),
                error=error,
            )
        raise


def calibrate(labels_path: Path) -> dict[str, Any]:
    state = operation_preflight(require_receipt=False)
    key = blind_key()
    if blind_commitment(key) != state["blind_key_commitment"]:
        raise RuntimeError("blind key changed")
    manifest, manifest_sha = _load_manifest("calibration", state)
    labels, labels_sha, labels_payload = _load_labels(
        labels_path, "calibration", manifest, manifest_sha, state
    )
    sealed_label_path = _prepare_sealed_label_path("calibration", state)
    root = state["artifact_root"]
    marker = {
        "artifact": "microtexture-v2-r5-calibration-evaluation-started",
        "schema_version": "microtexture-v2-r5-calibration-marker/2",
        "spec_sha256": SPEC_SHA256,
        "blind_key_commitment": state["blind_key_commitment"],
        "manifest_sha256": manifest_sha,
        "labels_sha256": labels_sha,
        "captured_git_head": state["captured_head"],
        "runtime": state["runtime"],
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "started_at": utc_timestamp(),
        "one_shot_consumed": True,
    }
    require_exact_keys(marker, CALIBRATION_MARKER_KEYS, "calibration marker")
    frozen_sha: str | None = None
    phase = "seal-reviewed-labels"
    with _one_shot_stage_guard(
        stage="calibration",
        state=state,
        marker=marker,
        marker_relative="markers/calibration-evaluation-started.json",
        phase=lambda: phase,
        bindings=lambda: {
            "manifest_sha256": manifest_sha,
            "labels_sha256": labels_sha,
            "frozen_thresholds_sha256": frozen_sha,
            "threshold_authority_receipt_sha256": None,
        },
    ) as marker_sha:
        labels = _seal_labels_after_marker(
            split="calibration",
            original_payload=labels_payload,
            expected_sha=labels_sha,
            sealed_path=sealed_label_path,
            manifest=manifest,
            manifest_sha=manifest_sha,
            state=state,
        )
        phase = "rebuild-bind-and-decode-contact-sheets"
        identities = _bind_after_marker(manifest, "calibration", key, state)
        phase = "validate-private-label-audits"
        _validate_private_label_audits_after_marker(labels, identities, "calibration")
        phase = "measure-calibration-records"
        measurements, reveal, clusters = _measure_records(manifest, identities, state)
        measured = {record["anonymous_code"]: record for record in measurements}
        phase = "select-hard-threshold"
        hard_threshold, endpoints, results, status, threshold_audit = (
            _select_hard_threshold(measured, labels, clusters)
        )
        passed = status == "selected-and-passed"
        report = {
            "artifact": "microtexture-v2-r5-calibration-report",
            "schema_version": "microtexture-v2-r5-calibration-report/2",
            "spec_sha256": SPEC_SHA256,
            "blind_key_commitment": state["blind_key_commitment"],
            "manifest_sha256": manifest_sha,
            "labels_sha256": labels_sha,
            "evaluation_marker_sha256": marker_sha,
            "evaluated_at": utc_timestamp(),
            "captured_git_head": state["captured_head"],
            "runtime": state["runtime"],
            "implementation_bindings_sha256": state["implementation_bindings_sha256"],
            "hard_gate": load_spec()["threshold_selection"]["hard_gate"],
            "hard_threshold": hard_threshold,
            "selection_status": status,
            "endpoint_performance": endpoints,
            "results_by_code": results,
            "diagnostic_flags_by_code": _diagnostic_flags(measured),
            "passed": passed,
            "measurements": measurements,
            "identity_reveal": reveal,
            "threshold_selection_audit": threshold_audit,
            "one_shot_consumed": True,
            "failure": None,
        }
        report_spec = load_spec()
        validate_calibration_report_nested(report, report_spec)
        validate_report_evaluation_bindings(
            report, manifest, labels, "calibration", report_spec
        )
        phase = "verify-git-head-before-calibration-report"
        assert_head_unchanged(state["captured_head"])
        phase = "write-calibration-report"
        report_sha = write_json_exclusive(
            root, root / "reports/calibration-report.json", report
        )
        if passed and hard_threshold is not None:
            frozen = {
                "artifact": "microtexture-v2-r5-thresholds-frozen",
                "schema_version": "microtexture-v2-r5-thresholds/2",
                "authority": True,
                "spec_sha256": SPEC_SHA256,
                "blind_key_commitment": state["blind_key_commitment"],
                "calibration_manifest_sha256": manifest_sha,
                "calibration_report_sha256": report_sha,
                "calibration_evaluation_marker_sha256": marker_sha,
                "calibration_captured_git_head": state["captured_head"],
                "frozen_at": utc_timestamp(),
                "runtime": state["runtime"],
                "hard_gate": load_spec()["threshold_selection"]["hard_gate"],
                "hard_threshold": hard_threshold,
                "endpoint_definitions": load_spec()["threshold_selection"][
                    "endpoint_definitions"
                ],
                "implementation_bindings_sha256": state[
                    "implementation_bindings_sha256"
                ],
                "holdout_allowed_count": 1,
                "threshold_changes_forbidden": True,
            }
            require_exact_keys(frozen, FROZEN_KEYS, "frozen thresholds")
            phase = "write-frozen-thresholds"
            frozen_sha = write_json_exclusive(
                root, root / "thresholds-frozen.json", frozen
            )
        phase = "read-back-validate-calibration-before-completion"
        (
            reloaded_report,
            reloaded_report_sha,
            reloaded_frozen,
            reloaded_frozen_sha,
        ) = load_calibration_report(state, require_completion=False)
        if reloaded_report != report or reloaded_report_sha != report_sha:
            raise RuntimeError("calibration report read-back value/SHA drift")
        if reloaded_frozen_sha != frozen_sha or (passed and reloaded_frozen != frozen):
            raise RuntimeError("calibration frozen-threshold read-back drift")
        phase = "verify-git-head-before-calibration-completion"
        assert_head_unchanged(state["captured_head"])
        phase = "write-calibration-completion"
        write_stage_completion_exclusive(
            stage="calibration",
            state=state,
            marker_sha=marker_sha,
            report_sha=report_sha,
            passed=passed,
            result_status=status,
            bindings={
                "manifest_sha256": manifest_sha,
                "labels_sha256": labels_sha,
                "frozen_thresholds_sha256": frozen_sha,
                "threshold_authority_receipt_sha256": None,
                "locked_clean_reference_sha256": None,
            },
        )
        phase = "terminal-reload-calibration-with-completion"
        terminal_report, terminal_report_sha, terminal_frozen, terminal_frozen_sha = (
            load_calibration_report(state, require_completion=True)
        )
        if (
            terminal_report != report
            or terminal_report_sha != report_sha
            or terminal_frozen_sha != frozen_sha
            or (passed and terminal_frozen != frozen)
        ):
            raise RuntimeError("calibration terminal authority reload drift")
    if not passed or hard_threshold is None:
        raise RuntimeError(f"calibration failed and r5 is closed: {status}")
    return {
        "passed": True,
        "blind_key_commitment": state["blind_key_commitment"],
        "threshold": hard_threshold["threshold"],
    }


def validate_locked_clean_reference() -> dict[str, Any]:
    state = operation_preflight(
        require_receipt=False, include_locked_clean_reference=True
    )
    frozen, frozen_sha = load_frozen_thresholds(state)
    if state["captured_head"] != frozen["calibration_captured_git_head"]:
        raise RuntimeError(
            "locked-clean-reference validation must run at the exact calibration HEAD"
        )
    root, spec = state["artifact_root"], load_spec()
    marker = {
        "artifact": "microtexture-v2-r5-locked-clean-reference-validation-started",
        "schema_version": "microtexture-v2-r5-locked-clean-reference-marker/2",
        "spec_sha256": SPEC_SHA256,
        "blind_key_commitment": state["blind_key_commitment"],
        "frozen_thresholds_sha256": frozen_sha,
        "captured_git_head": state["captured_head"],
        "runtime": state["runtime"],
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "started_at": utc_timestamp(),
        "one_shot_consumed": True,
    }
    require_exact_keys(
        marker, LOCKED_CLEAN_REFERENCE_MARKER_KEYS, "locked-clean-reference marker"
    )
    phase = "decode-locked-clean-reference"
    with _one_shot_stage_guard(
        stage="locked-clean-reference",
        state=state,
        marker=marker,
        marker_relative="markers/locked-clean-reference-validation-started.json",
        phase=lambda: phase,
        bindings=lambda: {
            "manifest_sha256": None,
            "labels_sha256": None,
            "frozen_thresholds_sha256": frozen_sha,
            "threshold_authority_receipt_sha256": None,
        },
    ) as marker_sha:
        locked_spec = spec["locked_clean_reference"]
        payload = state["locked_clean_reference_bytes"]
        with Image.open(io.BytesIO(payload)) as image:
            rgb = np.asarray(image.convert("RGB"), dtype=np.float32).copy()
        if [rgb.shape[1], rgb.shape[0]] != locked_spec["source_dimensions"]:
            raise RuntimeError("locked-clean-reference dimensions drift")
        phase = "validate-locked-clean-reference-geometry"
        sx, sy, source_width, source_height = locked_spec["source_crop_xywh"]
        source_dimensions = locked_spec["source_dimensions"]
        if (
            any(
                type(value) is not int
                for value in (sx, sy, source_width, source_height)
            )
            or sx < 0
            or sy < 0
            or source_width <= 0
            or source_height <= 0
            or sx + source_width > source_dimensions[0]
            or sy + source_height > source_dimensions[1]
        ):
            raise RuntimeError("locked-clean-reference source crop escapes source")
        mx, my, width, height = locked_spec["metric_window_xywh_within_source_crop"]
        if (
            any(type(value) is not int for value in (mx, my, width, height))
            or mx < 0
            or my < 0
            or width <= 0
            or height <= 0
            or mx + width > source_width
            or my + height > source_height
        ):
            raise RuntimeError("locked-clean-reference metric crop escapes source crop")
        source_crop = rgb[sy : sy + source_height, sx : sx + source_width]
        crop = source_crop[my : my + height, mx : mx + width]
        if crop.shape[:2] != tuple(spec["metric_definition"]["expected_shape_hw"]):
            raise RuntimeError("locked-clean-reference metric-window crop drift")
        if [sx + mx, sy + my, width, height] != locked_spec["effective_source_xywh"]:
            raise RuntimeError("locked-clean-reference effective source geometry drift")
        phase = "measure-locked-clean-reference"
        luminance = (
            np.float32(0.299) * crop[:, :, 0]
            + np.float32(0.587) * crop[:, :, 1]
            + np.float32(0.114) * crop[:, :, 2]
        )
        reference = ndimage.gaussian_filter(
            luminance, sigma=24.0, mode="reflect", truncate=4.0
        ).astype(np.float32)
        metrics = measure(luminance, reference, spec["metric_definition"])
        threshold = frozen["hard_threshold"]
        accepted = not _fails(
            float(metrics[threshold["metric"]]),
            float(threshold["threshold"]),
            threshold["direction"],
        )
        report = {
            "artifact": "microtexture-v2-r5-locked-clean-reference-report",
            "schema_version": "microtexture-v2-r5-locked-clean-reference-report/2",
            "spec_sha256": SPEC_SHA256,
            "blind_key_commitment": state["blind_key_commitment"],
            "frozen_thresholds_sha256": frozen_sha,
            "locked_clean_reference_sha256": locked_spec["sha256"],
            "source_crop_xywh": locked_spec["source_crop_xywh"],
            "metric_window_xywh_within_source_crop": locked_spec[
                "metric_window_xywh_within_source_crop"
            ],
            "effective_source_xywh": locked_spec["effective_source_xywh"],
            "evaluation_marker_sha256": marker_sha,
            "evaluated_at": utc_timestamp(),
            "captured_git_head": state["captured_head"],
            "runtime": state["runtime"],
            "implementation_bindings_sha256": state["implementation_bindings_sha256"],
            "metrics": metrics,
            "hard_threshold": threshold,
            "hard_composite_accepted": accepted,
            "passed": accepted,
            "one_shot_consumed": True,
            "failure": None,
        }
        validate_locked_clean_reference_report_nested(report, spec, threshold)
        phase = "verify-git-head-before-locked-clean-reference-report"
        assert_head_unchanged(state["captured_head"])
        phase = "write-locked-clean-reference-report"
        report_sha = write_json_exclusive(
            root, root / locked_spec["report_repo_relative_artifact_path"], report
        )
        phase = "read-back-validate-locked-clean-reference-before-completion"
        (
            reloaded_report,
            reloaded_report_sha,
            _,
            reloaded_frozen_sha,
            _,
        ) = load_locked_clean_reference_report(state, require_completion=False)
        if reloaded_report != report or reloaded_report_sha != report_sha:
            raise RuntimeError("locked-clean-reference report read-back drift")
        if reloaded_frozen_sha != frozen_sha:
            raise RuntimeError("locked-clean-reference frozen SHA read-back drift")
        phase = "verify-git-head-before-locked-clean-reference-completion"
        assert_head_unchanged(state["captured_head"])
        phase = "write-locked-clean-reference-completion"
        write_stage_completion_exclusive(
            stage="locked-clean-reference",
            state=state,
            marker_sha=marker_sha,
            report_sha=report_sha,
            passed=accepted,
            result_status="accepted" if accepted else "rejected",
            bindings={
                "manifest_sha256": None,
                "labels_sha256": None,
                "frozen_thresholds_sha256": frozen_sha,
                "threshold_authority_receipt_sha256": None,
                "locked_clean_reference_sha256": locked_spec["sha256"],
            },
        )
        phase = "terminal-reload-locked-clean-reference-with-completion"
        (
            terminal_report,
            terminal_report_sha,
            _,
            terminal_frozen_sha,
            _,
        ) = load_locked_clean_reference_report(state, require_completion=True)
        if (
            terminal_report != report
            or terminal_report_sha != report_sha
            or terminal_frozen_sha != frozen_sha
        ):
            raise RuntimeError("locked-clean-reference terminal authority reload drift")
    if not accepted:
        raise RuntimeError("locked-clean-reference failed and r5 is closed")
    return {"passed": True}


def holdout(labels_path: Path) -> dict[str, Any]:
    state = operation_preflight(
        require_receipt=True, include_locked_clean_reference=True
    )
    key = blind_key()
    frozen, frozen_sha = load_frozen_thresholds(state)
    if frozen_sha != state["threshold_authority"]["frozen_thresholds_sha256"]:
        raise RuntimeError("receipt/frozen SHA changed")
    manifest, manifest_sha = _load_manifest("holdout", state)
    labels, labels_sha, labels_payload = _load_labels(
        labels_path, "holdout", manifest, manifest_sha, state
    )
    sealed_label_path = _prepare_sealed_label_path("holdout", state)
    root = state["artifact_root"]
    marker = {
        "artifact": "microtexture-v2-r5-holdout-evaluation-started",
        "schema_version": "microtexture-v2-r5-holdout-marker/2",
        "spec_sha256": SPEC_SHA256,
        "blind_key_commitment": state["blind_key_commitment"],
        "manifest_sha256": manifest_sha,
        "labels_sha256": labels_sha,
        "frozen_thresholds_sha256": frozen_sha,
        "threshold_authority_receipt_sha256": state["threshold_authority_sha256"],
        "captured_git_head": state["captured_head"],
        "runtime": state["runtime"],
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "started_at": utc_timestamp(),
        "one_shot_consumed": True,
    }
    require_exact_keys(marker, HOLDOUT_MARKER_KEYS, "holdout marker")
    phase = "seal-reviewed-labels"
    with _one_shot_stage_guard(
        stage="holdout",
        state=state,
        marker=marker,
        marker_relative="markers/holdout-evaluation-started.json",
        phase=lambda: phase,
        bindings=lambda: {
            "manifest_sha256": manifest_sha,
            "labels_sha256": labels_sha,
            "frozen_thresholds_sha256": frozen_sha,
            "threshold_authority_receipt_sha256": state["threshold_authority_sha256"],
        },
    ) as marker_sha:
        labels = _seal_labels_after_marker(
            split="holdout",
            original_payload=labels_payload,
            expected_sha=labels_sha,
            sealed_path=sealed_label_path,
            manifest=manifest,
            manifest_sha=manifest_sha,
            state=state,
        )
        phase = "rebuild-bind-and-decode-contact-sheets"
        identities = _bind_after_marker(manifest, "holdout", key, state)
        phase = "validate-private-label-audits"
        _validate_private_label_audits_after_marker(labels, identities, "holdout")
        phase = "measure-holdout-records"
        measurements, reveal, clusters = _measure_records(manifest, identities, state)
        measured = {record["anonymous_code"]: record for record in measurements}
        threshold = frozen["hard_threshold"]
        phase = "evaluate-frozen-threshold-on-holdout"
        endpoints, results = _evaluate_endpoints(
            float(threshold["threshold"]), measured, labels, clusters, "holdout"
        )
        passed = all(endpoint["passed"] for endpoint in endpoints.values())
        report = {
            "artifact": "microtexture-v2-r5-holdout-report",
            "schema_version": "microtexture-v2-r5-holdout-report/2",
            "authority": True,
            "spec_sha256": SPEC_SHA256,
            "blind_key_commitment": state["blind_key_commitment"],
            "manifest_sha256": manifest_sha,
            "labels_sha256": labels_sha,
            "evaluation_marker_sha256": marker_sha,
            "frozen_thresholds_sha256": frozen_sha,
            "threshold_authority_receipt_sha256": state["threshold_authority_sha256"],
            "evaluated_at": utc_timestamp(),
            "captured_git_head": state["captured_head"],
            "runtime": state["runtime"],
            "implementation_bindings_sha256": state["implementation_bindings_sha256"],
            "hard_gate": frozen["hard_gate"],
            "hard_threshold": threshold,
            "endpoint_performance": endpoints,
            "results_by_code": results,
            "diagnostic_flags_by_code": _diagnostic_flags(measured),
            "passed": passed,
            "measurements": measurements,
            "identity_reveal": reveal,
            "threshold_changes_authorized": False,
            "one_shot_consumed": True,
            "failure": None,
        }
        report_spec = load_spec()
        validate_holdout_report_nested(report, report_spec, threshold)
        validate_report_evaluation_bindings(
            report, manifest, labels, "holdout", report_spec
        )
        phase = "verify-git-head-before-holdout-report"
        assert_head_unchanged(state["captured_head"])
        phase = "write-holdout-report"
        report_sha = write_json_exclusive(
            root, root / "reports/holdout-report.json", report
        )
        phase = "read-back-validate-holdout-before-completion"
        reloaded_report, reloaded_report_sha = load_holdout_report(
            state, require_completion=False
        )
        if reloaded_report != report or reloaded_report_sha != report_sha:
            raise RuntimeError("holdout report read-back value/SHA drift")
        phase = "verify-git-head-before-holdout-completion"
        assert_head_unchanged(state["captured_head"])
        phase = "write-holdout-completion"
        write_stage_completion_exclusive(
            stage="holdout",
            state=state,
            marker_sha=marker_sha,
            report_sha=report_sha,
            passed=passed,
            result_status="passed" if passed else "failed",
            bindings={
                "manifest_sha256": manifest_sha,
                "labels_sha256": labels_sha,
                "frozen_thresholds_sha256": frozen_sha,
                "threshold_authority_receipt_sha256": state[
                    "threshold_authority_sha256"
                ],
                "locked_clean_reference_sha256": load_spec()["locked_clean_reference"][
                    "sha256"
                ],
            },
        )
        phase = "terminal-reload-holdout-with-completion"
        terminal_report, terminal_report_sha = load_holdout_report(
            state, require_completion=True
        )
        if terminal_report != report or terminal_report_sha != report_sha:
            raise RuntimeError("holdout terminal authority reload drift")
    if not passed:
        raise RuntimeError("holdout failed and r5 is closed")
    return {"passed": True}


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    calibration = commands.add_parser("calibrate")
    calibration.add_argument("--labels", type=Path, required=True)
    commands.add_parser("locked-clean-reference")
    holdout_parser = commands.add_parser("holdout")
    holdout_parser.add_argument("--labels", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "calibrate":
        print(calibrate(arguments.labels))
    elif arguments.command == "locked-clean-reference":
        print(validate_locked_clean_reference())
    else:
        print(holdout(arguments.labels))


if __name__ == "__main__":
    main()
