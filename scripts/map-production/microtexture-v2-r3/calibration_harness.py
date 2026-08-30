"""r3 blinded calibration, locked-positive validation, and one-shot holdout."""

from __future__ import annotations

import argparse
import io
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage

from common import (
    CALIBRATION_REPORT_KEYS,
    FROZEN_KEYS,
    LOCKED_REPORT_KEYS,
    SPEC_SHA256,
    THRESHOLD_KEYS,
    assert_head_unchanged,
    blind_commitment,
    blind_key,
    load_frozen_thresholds,
    load_spec,
    operation_preflight,
    require_exact_keys,
    safe_artifact_path,
    sha256_bytes,
    utc_timestamp,
    write_json_exclusive,
)
from control_catalog import (
    ExpectedControl,
    bind_manifest_to_expected,
    contact_sheet_pages,
    expected_controls,
    validate_manifest_public_bindings,
)
from metrics_v2_r3 import measure


MANIFEST_KEYS = {
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
RECORD_KEYS = {
    "anonymous_code",
    "control_png",
    "reference_png",
    "control_sha256",
    "reference_sha256",
    "delta_float32_sha256",
}
SHEET_KEYS = {"scale_percent", "page_index", "path", "sha256", "item_codes"}
LABEL_KEYS = {
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
LABEL_ITEM_KEYS = {
    "anonymous_code",
    "disposition",
    "grain_visible",
    "speck_visible",
    "short_line_visible",
    "parallel_bundle_visible",
    "severity_0_to_3",
    "reviewed_at_200_percent",
    "reviewed_at_400_percent",
    "notes",
}
FORBIDDEN_PUBLIC_FIELDS = {
    "family",
    "family_id",
    "control_id",
    "variant",
    "variant_id",
    "role",
    "polarity",
    "parameters",
}


def _forbid_identity(value: Any, context: str) -> None:
    if isinstance(value, dict):
        leaked = set(value) & FORBIDDEN_PUBLIC_FIELDS
        if leaked:
            raise RuntimeError(f"identity leak in {context}: {sorted(leaked)}")
        for child in value.values():
            _forbid_identity(child, context)
    elif isinstance(value, list):
        for child in value:
            _forbid_identity(child, context)


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


def _load_manifest(
    split: str, state: dict[str, Any], key: bytes
) -> tuple[dict[str, Any], str]:
    root = state["artifact_root"]
    path = safe_artifact_path(root, root / "controls" / split / "manifest.json")
    payload = path.read_bytes()
    manifest = json.loads(payload.decode("utf-8"))
    require_exact_keys(manifest, MANIFEST_KEYS, f"{split} manifest")
    _forbid_identity(manifest, f"{split} manifest")
    receipt_sha = state.get("threshold_authority_sha256")
    frozen_sha = state.get("threshold_authority", {}).get("frozen_thresholds_sha256")
    if (
        manifest["artifact"] != "microtexture-v2-r3-control-manifest"
        or manifest["schema_version"] != "microtexture-v2-r3-control-manifest/1"
        or manifest["split"] != split
        or manifest["spec_sha256"] != SPEC_SHA256
        or manifest["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or manifest["blind_key_commitment"] != state["blind_key_commitment"]
        or manifest["captured_git_head"] != state["captured_head"]
        or manifest["runtime"] != state["runtime"]
        or manifest["frozen_thresholds_sha256"] != frozen_sha
        or manifest["threshold_authority_receipt_sha256"] != receipt_sha
    ):
        raise RuntimeError(f"{split} manifest trust-chain drift")
    if manifest["record_count"] != len(manifest["records"]):
        raise RuntimeError(f"{split} record count drift")
    codes = []
    for index, record in enumerate(manifest["records"]):
        require_exact_keys(record, RECORD_KEYS, f"{split} record[{index}]")
        code = record["anonymous_code"]
        if not isinstance(code, str) or re.fullmatch(r"[0-9a-f]{24}", code) is None:
            raise RuntimeError(f"{split} invalid opaque code")
        codes.append(code)
        expected_control_path = f"controls/{split}/items/{code}/control.png"
        expected_reference_path = f"controls/{split}/items/{code}/reference.png"
        if (
            record["control_png"] != expected_control_path
            or record["reference_png"] != expected_reference_path
        ):
            raise RuntimeError(f"{split} exact item path drift: {code}")
        safe_artifact_path(root, root / expected_control_path)
        safe_artifact_path(root, root / expected_reference_path)
    if len(codes) != len(set(codes)):
        raise RuntimeError(f"{split} duplicate opaque code")
    spec = load_spec()
    expected = expected_controls(spec, split, key)
    validate_manifest_public_bindings(manifest, expected)
    expected_pages = contact_sheet_pages(spec, split, expected)
    expected_bundle = [page.manifest_entry() for page in expected_pages]
    if manifest["contact_sheet_bundle"] != expected_bundle:
        raise RuntimeError(f"{split} secret-derived contact-sheet bundle drift")
    sheet_dimensions = tuple(
        int(value) for value in spec["contact_sheets"]["sheet_dimensions"]
    )
    for index, page in enumerate(expected_pages):
        require_exact_keys(
            expected_bundle[index], SHEET_KEYS, f"{split} sheet[{index}]"
        )
        sheet_path = safe_artifact_path(root, root / page.path)
        _validate_sheet_once(sheet_path, page.png_bytes, page.sha256, sheet_dimensions)
    return manifest, sha256_bytes(payload)


def _load_labels(
    path: Path,
    split: str,
    manifest: dict[str, Any],
    manifest_sha: str,
    state: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], str]:
    root = state["artifact_root"]
    checked = safe_artifact_path(root, path.resolve())
    payload = checked.read_bytes()
    value = json.loads(payload.decode("utf-8"))
    require_exact_keys(value, LABEL_KEYS, f"{split} labels")
    _forbid_identity(value, f"{split} labels")
    if (
        value["artifact"] != "microtexture-v2-r3-root-vision-labels"
        or value["schema_version"] != "microtexture-v2-r3-root-vision-labels/1"
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
        raise RuntimeError(f"{split} label authority/manifest/sheet drift")
    expected_codes = {record["anonymous_code"] for record in manifest["records"]}
    labels: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value["items"]):
        require_exact_keys(item, LABEL_ITEM_KEYS, f"{split} label[{index}]")
        code, disposition = item["anonymous_code"], item["disposition"]
        if code in labels or disposition not in {"clean", "warning", "reject"}:
            raise RuntimeError(f"{split} invalid code/disposition")
        for name in (
            "grain_visible",
            "speck_visible",
            "short_line_visible",
            "parallel_bundle_visible",
            "reviewed_at_200_percent",
            "reviewed_at_400_percent",
        ):
            if type(item[name]) is not bool:
                raise RuntimeError(f"{split} incomplete boolean: {code}/{name}")
        if not item["reviewed_at_200_percent"] or not item["reviewed_at_400_percent"]:
            raise RuntimeError(f"{split} both scales required: {code}")
        severity = item["severity_0_to_3"]
        visible = any(
            item[name]
            for name in (
                "grain_visible",
                "speck_visible",
                "short_line_visible",
                "parallel_bundle_visible",
            )
        )
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
                f"{split} disposition/severity/visibility contradiction: {code}"
            )
        labels[code] = item
    if set(labels) != expected_codes:
        raise RuntimeError(f"{split} label coverage drift")
    return labels, sha256_bytes(payload)


def _bind_after_marker(
    manifest: dict[str, Any], split: str, key: bytes
) -> dict[tuple[str, str, str, str], ExpectedControl]:
    return bind_manifest_to_expected(manifest, load_spec(), split, key)


def _measure_records(
    manifest: dict[str, Any],
    identities: dict[tuple[str, str, str, str], ExpectedControl],
    state: dict[str, Any],
    key: bytes,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root, definition = state["artifact_root"], load_spec()["metric_definition"]
    measured, reveal = [], []
    for record in manifest["records"]:
        identity_key = (
            record["anonymous_code"],
            record["control_sha256"],
            record["reference_sha256"],
            record["delta_float32_sha256"],
        )
        identity = identities[identity_key]
        control = _decode_image_once(
            safe_artifact_path(root, root / record["control_png"]),
            record["control_sha256"],
            "L",
        )
        reference = _decode_image_once(
            safe_artifact_path(root, root / record["reference_png"]),
            record["reference_sha256"],
            "L",
        )
        measured.append(
            {
                "anonymous_code": record["anonymous_code"],
                "metrics": measure(control, reference, definition),
            }
        )
        reveal.append(
            {
                "anonymous_code": record["anonymous_code"],
                "family": identity.family,
                "control_id": identity.control_id,
                "variant_index": identity.variant_index,
                "replicate": identity.replicate,
                "polarity": identity.polarity,
                "parameters": identity.parameters,
                "control_sha256": identity.control_sha256,
                "reference_sha256": identity.reference_sha256,
                "delta_float32_sha256": identity.delta_float32_sha256,
            }
        )
    return measured, reveal


def _fails(value: float, threshold: float, direction: str) -> bool:
    return value > threshold if direction == "maximum" else value < threshold


def _rate(numerator: int, denominator: int, context: str) -> float:
    if denominator <= 0:
        raise RuntimeError(f"no controls for {context}")
    return numerator / denominator


def _target_codes(rule: dict[str, Any], labels: dict[str, dict[str, Any]]) -> list[str]:
    return [
        code
        for code, label in labels.items()
        if label[rule["target_label"]]
        and (
            rule["target_population"] == "visible_all"
            or label["disposition"] == "reject"
        )
    ]


def _threshold_candidates(values: list[float]) -> list[float]:
    unique = sorted(set(float(value) for value in values))
    if not unique or any(not math.isfinite(value) for value in unique):
        raise RuntimeError("threshold metric values must be finite")
    epsilon = max(abs(unique[0]), abs(unique[-1]), 1.0) * 1e-9
    return [
        unique[0] - epsilon,
        *[(left + right) / 2 for left, right in zip(unique, unique[1:])],
        unique[-1] + epsilon,
    ]


def _select_threshold(
    rule: dict[str, Any],
    measured: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    clean_frr_maximum: float,
) -> dict[str, Any]:
    metric, direction = rule["metric"], rule["direction"]
    clean = [code for code, label in labels.items() if label["disposition"] == "clean"]
    targets = _target_codes(rule, labels)
    candidates = []
    for threshold in _threshold_candidates(
        [record["metrics"][metric] for record in measured.values()]
    ):
        clean_frr = _rate(
            sum(
                _fails(float(measured[code]["metrics"][metric]), threshold, direction)
                for code in clean
            ),
            len(clean),
            f"{metric} clean",
        )
        detection = _rate(
            sum(
                _fails(float(measured[code]["metrics"][metric]), threshold, direction)
                for code in targets
            ),
            len(targets),
            f"{metric} target",
        )
        if clean_frr <= clean_frr_maximum:
            candidates.append((threshold, clean_frr, detection))
    if not candidates:
        raise RuntimeError(f"no admissible threshold: {metric}")
    candidates.sort(
        key=lambda item: (
            -item[2],
            item[1],
            item[0] if direction == "maximum" else -item[0],
        )
    )
    threshold, clean_frr, detection = candidates[0]
    result = {
        **rule,
        "threshold": float(threshold),
        "clean_false_reject_rate": float(clean_frr),
        "calibration_target_detection_rate": float(detection),
        "calibration_minimum_passed": detection
        >= float(rule["calibration_minimum_detection"]),
    }
    require_exact_keys(result, THRESHOLD_KEYS, f"selected {metric}")
    return result


def _per_metric(
    thresholds: list[dict[str, Any]],
    measured: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    split: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    hard, warning = {}, {}
    for threshold in thresholds:
        targets = _target_codes(threshold, labels)
        detection = _rate(
            sum(
                _fails(
                    float(measured[code]["metrics"][threshold["metric"]]),
                    float(threshold["threshold"]),
                    threshold["direction"],
                )
                for code in targets
            ),
            len(targets),
            f"{split}/{threshold['metric']}",
        )
        minimum = float(threshold[f"{split}_minimum_detection"])
        record = {
            "target_count": len(targets),
            "detection_rate": detection,
            "minimum": minimum,
            "passed": detection >= minimum,
        }
        (hard if threshold["adoption"] == "hard" else warning)[threshold["metric"]] = (
            record
        )
    return hard, warning


def _score_hard(
    thresholds: list[dict[str, Any]],
    measured: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    hard = [threshold for threshold in thresholds if threshold["adoption"] == "hard"]
    warning = [
        threshold for threshold in thresholds if threshold["adoption"] == "warning"
    ]
    hard_results = {}
    warnings_by_code = {}
    for code, record in measured.items():
        failed = [
            threshold["metric"]
            for threshold in hard
            if _fails(
                float(record["metrics"][threshold["metric"]]),
                float(threshold["threshold"]),
                threshold["direction"],
            )
        ]
        warned = [
            threshold["metric"]
            for threshold in warning
            if _fails(
                float(record["metrics"][threshold["metric"]]),
                float(threshold["threshold"]),
                threshold["direction"],
            )
        ]
        hard_results[code] = {"passed": not failed, "failed_metrics": failed}
        warnings_by_code[code] = warned
    clean = [code for code, label in labels.items() if label["disposition"] == "clean"]
    reject = [
        code for code, label in labels.items() if label["disposition"] == "reject"
    ]
    warning_disposition = [
        code for code, label in labels.items() if label["disposition"] == "warning"
    ]
    severe = [code for code, label in labels.items() if label["severity_0_to_3"] == 3]
    scores = {
        "clean_count": len(clean),
        "warning_count": len(warning_disposition),
        "warning_acceptance_applicable": bool(warning_disposition),
        "reject_count": len(reject),
        "severity3_count": len(severe),
        "clean_acceptance": _rate(
            sum(hard_results[code]["passed"] for code in clean),
            len(clean),
            "hard clean",
        ),
        "warning_acceptance": (
            _rate(
                sum(hard_results[code]["passed"] for code in warning_disposition),
                len(warning_disposition),
                "hard warning-disposition",
            )
            if warning_disposition
            else 1.0
        ),
        "reject_detection": _rate(
            sum(not hard_results[code]["passed"] for code in reject),
            len(reject),
            "hard reject",
        ),
        "severity3_detection": _rate(
            sum(not hard_results[code]["passed"] for code in severe),
            len(severe),
            "hard severity3",
        ),
        "results_by_code": hard_results,
    }
    return scores, warnings_by_code


def _hard_targets(spec: dict[str, Any], split: str) -> dict[str, float]:
    source = (
        spec["threshold_selection"]
        if split == "calibration"
        else spec["holdout_pass_targets"]
    )
    return {
        "clean_acceptance_minimum": float(
            source["hard_composite_clean_acceptance_minimum"]
        ),
        "warning_acceptance_minimum": float(
            source["hard_composite_warning_acceptance_minimum"]
        ),
        "reject_detection_minimum": float(
            source["hard_composite_reject_detection_minimum"]
        ),
        "severity3_detection_minimum": float(
            source["hard_composite_severity3_detection_minimum"]
        ),
    }


def _scores_pass(scores: dict[str, Any], targets: dict[str, float]) -> bool:
    return (
        scores["clean_acceptance"] >= targets["clean_acceptance_minimum"]
        and scores["warning_acceptance"] >= targets["warning_acceptance_minimum"]
        and scores["reject_detection"] >= targets["reject_detection_minimum"]
        and scores["severity3_detection"] >= targets["severity3_detection_minimum"]
    )


def calibrate(labels_path: Path) -> dict[str, Any]:
    state = operation_preflight(require_receipt=False)
    key = blind_key()
    if blind_commitment(key) != state["blind_key_commitment"]:
        raise RuntimeError("blind key changed")
    manifest, manifest_sha = _load_manifest("calibration", state, key)
    labels, labels_sha = _load_labels(
        labels_path, "calibration", manifest, manifest_sha, state
    )
    root = state["artifact_root"]
    write_json_exclusive(
        root,
        root / "markers/calibration-evaluation-started.json",
        {
            "artifact": "microtexture-v2-r3-calibration-evaluation-started",
            "spec_sha256": SPEC_SHA256,
            "blind_key_commitment": state["blind_key_commitment"],
            "manifest_sha256": manifest_sha,
            "labels_sha256": labels_sha,
            "one_shot_consumed": True,
        },
    )
    identities = _bind_after_marker(manifest, "calibration", key)
    measurements, reveal = _measure_records(manifest, identities, state, key)
    measured = {record["anonymous_code"]: record for record in measurements}
    spec, selection = load_spec(), load_spec()["threshold_selection"]
    thresholds = [
        _select_threshold(
            rule,
            measured,
            labels,
            float(selection["calibration_clean_false_reject_maximum"]),
        )
        for rule in selection["metric_rules"]
    ]
    hard_per_metric, warning_per_metric = _per_metric(
        thresholds, measured, labels, "calibration"
    )
    scores, warnings = _score_hard(thresholds, measured, labels)
    targets = _hard_targets(spec, "calibration")
    passed = all(item["passed"] for item in hard_per_metric.values()) and _scores_pass(
        scores, targets
    )
    report = {
        "artifact": "microtexture-v2-r3-calibration-report",
        "schema_version": "microtexture-v2-r3-calibration-report/1",
        "spec_sha256": SPEC_SHA256,
        "blind_key_commitment": state["blind_key_commitment"],
        "manifest_sha256": manifest_sha,
        "labels_sha256": labels_sha,
        "evaluated_at": utc_timestamp(),
        "runtime": state["runtime"],
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "thresholds": thresholds,
        "hard_per_metric_performance": hard_per_metric,
        "warning_per_metric_performance": warning_per_metric,
        "hard_scores": scores,
        "targets": targets,
        "warnings_by_code": warnings,
        "passed": passed,
        "measurements": measurements,
        "identity_reveal": reveal,
    }
    require_exact_keys(report, CALIBRATION_REPORT_KEYS, "calibration report")
    report_path = root / "reports/calibration-report.json"
    report_sha = write_json_exclusive(root, report_path, report)
    if not passed:
        raise RuntimeError("calibration failed; thresholds not frozen")
    frozen = {
        "artifact": "microtexture-v2-r3-thresholds-frozen",
        "schema_version": "microtexture-v2-r3-thresholds/1",
        "authority": True,
        "spec_sha256": SPEC_SHA256,
        "blind_key_commitment": state["blind_key_commitment"],
        "calibration_manifest_sha256": manifest_sha,
        "calibration_report_sha256": report_sha,
        "frozen_at": utc_timestamp(),
        "runtime": state["runtime"],
        "metric_rules": selection["metric_rules"],
        "thresholds": thresholds,
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "holdout_allowed_count": 1,
        "threshold_changes_forbidden": True,
    }
    require_exact_keys(frozen, FROZEN_KEYS, "frozen thresholds")
    write_json_exclusive(root, root / "thresholds-frozen.json", frozen)
    assert_head_unchanged(state["captured_head"])
    return {"passed": True, "blind_key_commitment": state["blind_key_commitment"]}


def validate_locked_positive() -> dict[str, Any]:
    state = operation_preflight(require_receipt=False, include_locked_positive=True)
    frozen, frozen_sha = load_frozen_thresholds(state)
    root, spec = state["artifact_root"], load_spec()
    write_json_exclusive(
        root,
        root / "markers/locked-positive-validation-started.json",
        {
            "artifact": "microtexture-v2-r3-locked-positive-validation-started",
            "spec_sha256": SPEC_SHA256,
            "blind_key_commitment": state["blind_key_commitment"],
            "frozen_thresholds_sha256": frozen_sha,
            "one_shot_consumed": True,
        },
    )
    payload = state["locked_positive_bytes"]
    with Image.open(io.BytesIO(payload)) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.float32).copy()
    if [rgb.shape[1], rgb.shape[0]] != spec["locked_positive"]["source_dimensions"]:
        raise RuntimeError("locked-positive dimensions drift")
    x, y, width, height = spec["locked_positive"]["crop_xywh"]
    crop = rgb[y : y + height, x : x + width]
    luminance = (
        np.float32(0.299) * crop[:, :, 0]
        + np.float32(0.587) * crop[:, :, 1]
        + np.float32(0.114) * crop[:, :, 2]
    )
    reference = ndimage.gaussian_filter(
        luminance, sigma=24.0, mode="reflect", truncate=4.0
    ).astype(np.float32)
    metrics = measure(luminance, reference, spec["metric_definition"])
    hard_results = {
        threshold["metric"]: {
            "passed": not _fails(
                float(metrics[threshold["metric"]]),
                float(threshold["threshold"]),
                threshold["direction"],
            )
        }
        for threshold in frozen["thresholds"]
        if threshold["adoption"] == "hard"
    }
    all_hard_passed = bool(hard_results) and all(
        result["passed"] for result in hard_results.values()
    )
    report = {
        "artifact": "microtexture-v2-r3-locked-positive-report",
        "schema_version": "microtexture-v2-r3-locked-positive-report/1",
        "spec_sha256": SPEC_SHA256,
        "blind_key_commitment": state["blind_key_commitment"],
        "frozen_thresholds_sha256": frozen_sha,
        "locked_positive_sha256": spec["locked_positive"]["sha256"],
        "crop_xywh": spec["locked_positive"]["crop_xywh"],
        "evaluated_at": utc_timestamp(),
        "runtime": state["runtime"],
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "metrics": metrics,
        "hard_results": hard_results,
        "all_hard_passed": all_hard_passed,
        "passed": all_hard_passed,
    }
    require_exact_keys(report, LOCKED_REPORT_KEYS, "locked-positive report")
    write_json_exclusive(
        root,
        root / spec["locked_positive"]["report_repo_relative_artifact_path"],
        report,
    )
    assert_head_unchanged(state["captured_head"])
    return {"passed": all_hard_passed}


def holdout(labels_path: Path) -> dict[str, Any]:
    state = operation_preflight(require_receipt=True)
    key = blind_key()
    frozen, frozen_sha = load_frozen_thresholds(state)
    if frozen_sha != state["threshold_authority"]["frozen_thresholds_sha256"]:
        raise RuntimeError("receipt/frozen SHA changed")
    manifest, manifest_sha = _load_manifest("holdout", state, key)
    labels, labels_sha = _load_labels(
        labels_path, "holdout", manifest, manifest_sha, state
    )
    root = state["artifact_root"]
    write_json_exclusive(
        root,
        root / "markers/holdout-evaluation-started.json",
        {
            "artifact": "microtexture-v2-r3-holdout-evaluation-started",
            "spec_sha256": SPEC_SHA256,
            "blind_key_commitment": state["blind_key_commitment"],
            "manifest_sha256": manifest_sha,
            "labels_sha256": labels_sha,
            "frozen_thresholds_sha256": frozen_sha,
            "threshold_authority_receipt_sha256": state["threshold_authority_sha256"],
            "one_shot_consumed": True,
        },
    )
    identities = _bind_after_marker(manifest, "holdout", key)
    measurements, reveal = _measure_records(manifest, identities, state, key)
    measured = {record["anonymous_code"]: record for record in measurements}
    hard_per_metric, warning_per_metric = _per_metric(
        frozen["thresholds"], measured, labels, "holdout"
    )
    scores, warnings = _score_hard(frozen["thresholds"], measured, labels)
    targets = _hard_targets(load_spec(), "holdout")
    passed = all(item["passed"] for item in hard_per_metric.values()) and _scores_pass(
        scores, targets
    )
    report = {
        "artifact": "microtexture-v2-r3-holdout-report",
        "schema_version": "microtexture-v2-r3-holdout-report/1",
        "authority": True,
        "spec_sha256": SPEC_SHA256,
        "blind_key_commitment": state["blind_key_commitment"],
        "manifest_sha256": manifest_sha,
        "labels_sha256": labels_sha,
        "frozen_thresholds_sha256": frozen_sha,
        "threshold_authority_receipt_sha256": state["threshold_authority_sha256"],
        "runtime": state["runtime"],
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "hard_per_metric_performance": hard_per_metric,
        "warning_per_metric_performance": warning_per_metric,
        "hard_scores": scores,
        "targets": targets,
        "warnings_by_code": warnings,
        "passed": passed,
        "measurements": measurements,
        "identity_reveal": reveal,
        "threshold_changes_authorized": False,
    }
    write_json_exclusive(root, root / "reports/holdout-report.json", report)
    assert_head_unchanged(state["captured_head"])
    return {"passed": passed}


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    calibration = commands.add_parser("calibrate")
    calibration.add_argument("--labels", type=Path, required=True)
    commands.add_parser("locked-positive")
    holdout_parser = commands.add_parser("holdout")
    holdout_parser.add_argument("--labels", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "calibrate":
        print(calibrate(arguments.labels))
    elif arguments.command == "locked-positive":
        print(validate_locked_positive())
    else:
        print(holdout(arguments.labels))


if __name__ == "__main__":
    main()
