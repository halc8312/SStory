#!/usr/bin/env python3
"""Generate or verify the frozen Golden-v2 independent pixel-audit controls.

The controls are derived only from the byte-frozen v19 replay graph.  This
tool does not inspect a Vision decision and cannot create an emission or
promote a candidate.  It reconstructs v19 twice, derives the exact masks used
by the tracked preflight, independently re-runs the Golden-v2 pixel auditor in
memory, and only then writes the control JSON and six binary masks.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

import audit_style_candidate_k3_golden_v2 as pixel_auditor
import build_style_candidate_k3_sparse_ridgeline_v19 as v19


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTROL_ROOT = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-k-v3-golden-v2"
)
REPLAY_CONTRACT = CONTROL_ROOT / "v19-replay-contract.json"
AUDIT_CONTROL = CONTROL_ROOT / "audit-control.json"
BASELINE = (
    REPO_ROOT / "world/map-production/style-assets/k3-v18-reconstruction-base.png"
)
MASK_ROOT = CONTROL_ROOT / "masks"
MASK_PATHS = {
    "measurement_inside": MASK_ROOT / "measurement-inside.png",
    "texture_reference": MASK_ROOT / "texture-reference.png",
    "permission": MASK_ROOT / "permission.png",
    "protected_features": MASK_ROOT / "protected-features.png",
    "road_calm_18px": MASK_ROOT / "road-calm-18px.png",
    "selected_components": MASK_ROOT / "selected-components.png",
}
EXPECTED_MASK_ARRAYS = {
    "measurement_inside": v19.EXPECTED_ARRAYS["inside"],
    "texture_reference": v19.EXPECTED_ARRAYS["quiet_annulus"],
    "permission": v19.EXPECTED_ARRAYS["permission"],
    "protected_features": v19.EXPECTED_ARRAYS["protected"],
    "road_calm_18px": v19.EXPECTED_ARRAYS["road_calm"],
    "selected_components": v19.EXPECTED_ARRAYS["body"],
}
EXPECTED_METRICS = {
    "coverage_50": 367,
    "coverage_25": 338,
    "quiet_fraction": 0.912177,
    "dash_bundle_pairs": 0,
    "orientation_coherence": 0.05625,
    "texture_inside_to_outside_ratio": {"4": 0.614135, "8": 0.981493},
}
EXPECTED_GEOMETRY = {"selected_component_count": 8}
EXPECTED_IDENTITY = {
    "outside_permission": 0,
    "protected_features": 0,
    "road_calm_18px": 0,
}
EXPECTED_AUDIT_CONTROL_SHA256 = (
    "7104ac37996dfdc5bc18a8a1c84bbca43e5d05fcafbd17cf4df3229348f720c8"
)
EXPECTED_MASK_PNG_SHA256 = {
    "measurement_inside": "bbf721e7bdb3dee6fd8bb999237cca3966240d477199a24bb650b7ee6815e624",
    "texture_reference": "2d9cdb96097526968df72564a6f6513703f821d4e6849becc16d4c0a08f90eea",
    "permission": "41e7fd45b2188b0ee918ed712be782fec2c58f14f1f4391089abb48d3704a535",
    "protected_features": "585f133d596f49ecea280223b814db22fed8c169ec3f9bce8544f7b7525dd607",
    "road_calm_18px": "22434242cce4af83c0ba12637124102734b818dd087b94c0b94c7dadd7cdb4bc",
    "selected_components": "c025f9f20c0a942e932fbd7e0c2d17a71a9928bcdb2400420b41c7f5dbc7d16e",
}
PNG_OPTIONS = {"format": "PNG", "compress_level": 9, "optimize": False}


class GoldenV2ControlError(RuntimeError):
    """Raised before incomplete or stale audit controls can be published."""


@dataclass(frozen=True)
class Snapshot:
    data: bytes
    sha256: str
    path: Path | None = None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot(path: Path) -> Snapshot:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise GoldenV2ControlError(f"cannot read frozen authority {path}: {exc}") from exc
    return Snapshot(data=data, sha256=_sha256(data), path=path.resolve())


def _mask_png(mask: np.ndarray) -> bytes:
    if mask.shape != (v19.HEIGHT, v19.WIDTH) or mask.dtype != np.bool_:
        raise GoldenV2ControlError("audit mask must be a native boolean v19 canvas")
    buffer = io.BytesIO()
    with Image.fromarray(mask.astype(np.uint8) * 255, mode="L") as image:
        image.save(buffer, **PNG_OPTIONS)
    return buffer.getvalue()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def _derive() -> tuple[dict[Path, bytes], dict[str, Any]]:
    first = v19.reconstruct_from_contract(REPLAY_CONTRACT)
    second = v19.reconstruct_from_contract(REPLAY_CONTRACT)
    if not np.array_equal(first.candidate, second.candidate):
        raise GoldenV2ControlError("independent v19 reconstructions differ")
    candidate_bytes = v19.png_bytes(first.candidate)
    if _sha256(candidate_bytes) != v19.EXPECTED_PNG_SHA256:
        raise GoldenV2ControlError("v19 candidate PNG SHA-256 changed")

    if not np.array_equal(first.baseline, second.baseline):
        raise GoldenV2ControlError("independent v19 baselines differ")
    baseline = _snapshot(BASELINE)
    if baseline.sha256 != v19.EXPECTED_BASE_SHA256:
        raise GoldenV2ControlError("Golden-v2 audit baseline is not frozen v18")
    try:
        with Image.open(io.BytesIO(baseline.data)) as opened:
            opened.load()
            baseline_pixels = np.asarray(opened, dtype=np.uint8).copy()
    except OSError as exc:
        raise GoldenV2ControlError("cannot decode frozen v18 audit baseline") from exc
    if not np.array_equal(baseline_pixels, first.baseline):
        raise GoldenV2ControlError("replay baseline pixels differ from frozen v18 bytes")

    controls = v19.derive_controls()
    baseline_lab = cv2.cvtColor(first.baseline, cv2.COLOR_RGB2LAB).astype(np.float32)
    _, quiet_reference = v19.paper_authority_mask(baseline_lab[..., 0], controls)
    masks = {
        "measurement_inside": first.inside,
        "texture_reference": quiet_reference,
        "permission": first.permission,
        "protected_features": first.protected,
        "road_calm_18px": first.road_calm,
        "selected_components": first.body,
    }
    if tuple(masks) != pixel_auditor.MASK_NAMES:
        raise GoldenV2ControlError("Golden-v2 mask order drifted")
    for name, mask in masks.items():
        expected_count, expected_digest = EXPECTED_MASK_ARRAYS[name]
        count = int(np.count_nonzero(mask))
        digest = v19.array_sha256(mask)
        if count != expected_count or digest != expected_digest:
            raise GoldenV2ControlError(
                f"{name} authority changed: count={count}/{expected_count}, "
                f"sha256={digest}/{expected_digest}"
            )
    if np.any(masks["measurement_inside"] & ~masks["permission"]):
        raise GoldenV2ControlError("measurement mask escaped permission")
    if np.any(masks["selected_components"] & ~masks["measurement_inside"]):
        raise GoldenV2ControlError("selected components escaped measurement support")

    mask_payloads = {name: _mask_png(mask) for name, mask in masks.items()}
    control = {
        "schema_version": pixel_auditor.SCHEMA_VERSION,
        "id": pixel_auditor.CONTROL_ID,
        "algorithm": pixel_auditor.ALGORITHM,
        "image": {"mode": "RGB", "size": [v19.WIDTH, v19.HEIGHT]},
        "candidate": {"sha256": v19.EXPECTED_PNG_SHA256},
        "baseline": {
            "reproduction_role": pixel_auditor.BASELINE_REPRODUCTION_ROLE,
            "sha256": baseline.sha256,
        },
        "masks": {
            name: {
                "reproduction_role": pixel_auditor.MASK_REPRODUCTION_ROLES[name],
                "path": MASK_PATHS[name].relative_to(CONTROL_ROOT).as_posix(),
                "sha256": _sha256(mask_payloads[name]),
            }
            for name in pixel_auditor.MASK_NAMES
        },
    }
    control_payload = _json_bytes(control)
    mask_snapshots = {
        name: Snapshot(mask_payloads[name], _sha256(mask_payloads[name]))
        for name in pixel_auditor.MASK_NAMES
    }
    report = pixel_auditor.audit_candidate(
        Snapshot(candidate_bytes, v19.EXPECTED_PNG_SHA256),
        baseline,
        Snapshot(control_payload, _sha256(control_payload)),
        mask_bindings=mask_snapshots,
    )
    if (
        report["metrics"] != EXPECTED_METRICS
        or report["geometry"] != EXPECTED_GEOMETRY
        or report["identity"] != EXPECTED_IDENTITY
        or report["failed_gates"] != []
        or report["passed"] is not True
        or not all(report["gates"].values())
    ):
        raise GoldenV2ControlError(
            "independent Golden-v2 audit did not reproduce the frozen v19 preflight: "
            f"metrics={report['metrics']!r}, geometry={report['geometry']!r}, "
            f"identity={report['identity']!r}, failed={report['failed_gates']!r}"
        )

    payloads = {AUDIT_CONTROL: control_payload}
    payloads.update({MASK_PATHS[name]: mask_payloads[name] for name in masks})
    if _sha256(control_payload) != EXPECTED_AUDIT_CONTROL_SHA256:
        raise GoldenV2ControlError("audit-control canonical bytes changed")
    observed_mask_png_sha256 = {
        name: _sha256(mask_payloads[name]) for name in pixel_auditor.MASK_NAMES
    }
    if observed_mask_png_sha256 != EXPECTED_MASK_PNG_SHA256:
        raise GoldenV2ControlError(
            "binary mask canonical PNG bytes changed: "
            f"{observed_mask_png_sha256!r}"
        )
    return payloads, report


def _write_new_or_identical(path: Path, payload: bytes, created: list[Path]) -> None:
    if path.exists():
        if path.is_file() and path.read_bytes() == payload:
            return
        raise GoldenV2ControlError(f"refusing to replace non-identical control: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.new-{uuid.uuid4().hex}")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        created.append(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_controls() -> dict[str, Any]:
    payloads, report = _derive()
    created: list[Path] = []
    try:
        for path, payload in payloads.items():
            _write_new_or_identical(path, payload, created)
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    verify_controls()
    return {
        "status": "written-and-verified",
        "candidate_sha256": v19.EXPECTED_PNG_SHA256,
        "audit_control_sha256": _sha256(payloads[AUDIT_CONTROL]),
        "metrics": report["metrics"],
        "files": {
            path.relative_to(REPO_ROOT).as_posix(): _sha256(payload)
            for path, payload in payloads.items()
        },
    }


def verify_controls() -> dict[str, Any]:
    payloads, report = _derive()
    stale = []
    for path, payload in payloads.items():
        try:
            actual = path.read_bytes()
        except OSError:
            stale.append(path.relative_to(REPO_ROOT).as_posix())
            continue
        if actual != payload:
            stale.append(path.relative_to(REPO_ROOT).as_posix())
    if stale:
        raise GoldenV2ControlError(f"missing or stale Golden-v2 controls: {stale}")
    return {
        "status": "verified",
        "candidate_sha256": v19.EXPECTED_PNG_SHA256,
        "audit_control_sha256": _sha256(payloads[AUDIT_CONTROL]),
        "metrics": report["metrics"],
        "files": {
            path.relative_to(REPO_ROOT).as_posix(): _sha256(payload)
            for path, payload in payloads.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--write", action="store_true")
    actions.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = write_controls() if args.write else verify_controls()
    except (GoldenV2ControlError, v19.ReplayError, pixel_auditor.GoldenV2PixelAuditError, OSError, ValueError) as exc:
        print(f"Golden-v2 control generation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
