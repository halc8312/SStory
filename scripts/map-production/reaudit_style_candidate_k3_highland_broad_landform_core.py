#!/usr/bin/env python3
"""Re-audit three frozen broad-landform probes with the alpha-aligned core.

Inputs are the existing v2 Lab-L 0.65/0.75 and v3 sigma-4 TEMP candidates.
No raster is recomposed.  The updated production audit measures highland
quiet/dash/orientation only on ``erode(highland_edit, 7)``, matching the
2px-locked/7px-full boundary alpha.  Every threshold is unchanged and the
highland semantic result remains a hard gate.  Contacts are emitted only after
all hard gates pass.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/map-production"
OUT = ROOT / (
    "tmp/map-production/"
    "k3-semantic-cleanup-v19-broad-landform-core-reaudit"
)
V18 = ROOT / (
    "tmp/map-production/k3-semantic-cleanup-proof-v18/"
    "style-candidate-k-v3-semantic-cleanup-proof-v18.png"
)
V2_REPORT = ROOT / (
    "tmp/map-production/"
    "k3-semantic-cleanup-v19-broad-landform-contrast-refinement/"
    "broad-landform-contrast-search.json"
)
V3_REPORT = ROOT / (
    "tmp/map-production/"
    "k3-semantic-cleanup-v19-broad-landform-lowpass-refinement/"
    "broad-landform-lowpass-search.json"
)
BASE_PROBE = SCRIPTS / "probe_style_candidate_k3_highland_broad_landform.py"
HARNESS = SCRIPTS / "build_style_candidate_k3_highland_phase_synthesis.py"
AUDIT = SCRIPTS / "audit_style_candidate_k3_semantic_cleanup.py"

CANDIDATES = {
    "v2-lcontrast-065": {
        "path": ROOT / (
            "tmp/map-production/"
            "k3-semantic-cleanup-v19-broad-landform-contrast-refinement/"
            "broad-landform-d-lcontrast-065/"
            "broad-landform-d-lcontrast-065.png"
        ),
        "sha256": "20ee2a0f75a9a65213d2882347292ee76f4125a95adf217e4428d7bc9af1ff22",
        "source_report": V2_REPORT,
    },
    "v2-lcontrast-075": {
        "path": ROOT / (
            "tmp/map-production/"
            "k3-semantic-cleanup-v19-broad-landform-contrast-refinement/"
            "broad-landform-d-lcontrast-075/"
            "broad-landform-d-lcontrast-075.png"
        ),
        "sha256": "d2854dee78659500c340930ab1fbe6bc644325ef250b0db11143db561b3df3d3",
        "source_report": V2_REPORT,
    },
    "v3-lowpass-sigma04-l065": {
        "path": ROOT / (
            "tmp/map-production/"
            "k3-semantic-cleanup-v19-broad-landform-lowpass-refinement/"
            "broad-landform-lowpass-sigma04-l065/"
            "broad-landform-lowpass-sigma04-l065.png"
        ),
        "sha256": "c66d696598f8477a0728e86c877d1e483d79ac84a9c22538278cc80f4d18569b",
        "source_report": V3_REPORT,
    },
}

EXPECTED = {
    V18: "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882",
    V2_REPORT: "87ecf4771a9db6c9d7f6b384656a92a8ef63ac0d86b82d9cbed9220db23d97de",
    V3_REPORT: "7148c7300c7ee309c2fad6867162ccb30d8481a124dcf095b6ac18f8d59eab0b",
    AUDIT: "3ae2981c6e20de68c512c9a4e63fe4c544f5361fbd6ea9335f2071d3027e8dc7",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base_probe = load_module("broad_landform_core_reaudit_authority", BASE_PROBE)
harness = load_module("broad_landform_core_reaudit_harness", HARNESS)
harness.OUT = OUT
k3 = harness.k3


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def locked(path: Path, digest: str) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(f"frozen input missing: {path}")
    actual = sha256(path)
    if actual != digest:
        raise RuntimeError(f"frozen input hash mismatch: {path}: {actual}")
    return {"path": relative(path), "sha256": actual}


def rewrite_candidate_report(record: dict[str, Any]) -> None:
    report_path = ROOT / record["report"]["path"]
    payload = dict(record)
    payload.pop("report", None)
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    record["report"] = {
        "path": relative(report_path),
        "sha256": sha256(report_path),
    }


def main() -> None:
    frozen = {relative(path): locked(path, digest) for path, digest in EXPECTED.items()}
    frozen_candidates = {
        name: locked(record["path"], record["sha256"])
        for name, record in CANDIDATES.items()
    }
    persistent = (k3.RAW, k3.FINAL, k3.RECEIPT, k3.AUDIT)
    if any(path.exists() for path in persistent):
        raise RuntimeError("persistent K3 output unexpectedly exists")
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty TEMP re-audit: {OUT}")

    spec_bytes_before = k3.SPEC.read_bytes()
    spec_sha_before = sha256(k3.SPEC)
    baseline = np.asarray(Image.open(V18).convert("RGB"), np.uint8)
    k3.validate_source()
    masks = k3.derive_masks()
    baseline_weave = harness.weave(baseline, masks["highland_edit"])
    baseline_activity = float(baseline_weave["activity_fraction"])
    records: dict[str, Any] = {}
    original_save_contacts = harness.save_contacts
    try:
        harness.save_contacts = lambda candidate, directory: {}
        for name, candidate_input in CANDIDATES.items():
            candidate = np.asarray(
                Image.open(candidate_input["path"]).convert("RGB"), np.uint8
            )
            identity = base_probe.guard_identity(candidate, baseline, masks)
            record = harness.evaluate(
                name,
                candidate,
                baseline,
                masks,
                baseline_activity,
            )
            highland_semantic = record["semantic_diagnostic"]["highland"]
            if highland_semantic["measurement"]["erosion_px"] != 7:
                raise RuntimeError("updated highland semantic erosion is not 7px")
            record["schema_version"] = "1.0.0"
            record["persistent_candidate_emitted"] = False
            record["lineage"] = {
                "candidate": frozen_candidates[name],
                "source_report": frozen[relative(candidate_input["source_report"])],
                "frozen_v18": frozen[relative(V18)],
                "production_audit": frozen[relative(AUDIT)],
            }
            record["method"] = {
                "operation": "read-only re-audit; candidate pixels not recomposed",
                "highland_semantic_measurement": highland_semantic["measurement"],
                "thresholds_changed": False,
            }
            record["road_guard_protected_outside_identity"] = identity
            record["automated_gates"]["exact_k2_source_lock"] = bool(
                sha256(k3.SOURCE) == k3.EXPECTED_SOURCE
            )
            record["automated_gates"][
                "road_guard_protected_outside_byte_exact"
            ] = identity["passed"]
            record["automated_gates"][
                "highland_semantic_cleanup_proxies"
            ] = bool(highland_semantic["passed"])
            record["failed_gates"] = [
                gate
                for gate, passed in record["automated_gates"].items()
                if not passed
            ]
            passed = not record["failed_gates"]
            record["status"] = (
                "passed-automated-gates-pending-root-vision"
                if passed
                else "failed-automated-gates"
            )
            record["vision_handoff"]["required"] = passed
            record["vision_handoff"][
                "contacts_emitted_only_after_all_hard_gates"
            ] = True
            record["contacts"] = (
                original_save_contacts(candidate, OUT / name / "contacts")
                if passed
                else {}
            )
            rewrite_candidate_report(record)
            records[name] = record
    finally:
        harness.save_contacts = original_save_contacts

    if k3.SPEC.read_bytes() != spec_bytes_before or sha256(k3.SPEC) != spec_sha_before:
        raise RuntimeError("persistent K3 specification changed during re-audit")
    if any(path.exists() for path in persistent):
        raise RuntimeError("TEMP re-audit emitted a persistent K3 output")

    aggregate = {
        "schema_version": "1.0.0",
        "status": "TEMP-only alpha-aligned highland-core re-audit; no acceptance authority",
        "temporary_review_only": True,
        "decision_authority": False,
        "persistent_outputs_emitted": False,
        "thresholds_changed": False,
        "candidate_count": len(records),
        "inputs": {
            "frozen_v18": frozen[relative(V18)],
            "v2_report": frozen[relative(V2_REPORT)],
            "v3_report": frozen[relative(V3_REPORT)],
            "production_audit": frozen[relative(AUDIT)],
            "full_gate_harness": {
                "path": relative(HARNESS),
                "sha256": sha256(HARNESS),
            },
            "candidates": frozen_candidates,
        },
        "measurement_contract": {
            "highland_permission": "erode(highland_edit, 7)",
            "erosion_px": 7,
            "reason": (
                "Matches boundary alpha full_by_px=7; excludes locked and "
                "fractional transition pixels from quiet/dash/orientation only."
            ),
            "thresholds_changed": False,
        },
        "v18_weave": baseline_weave,
        "records": records,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    report_path = OUT / "broad-landform-core-reaudit.json"
    report_path.write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": {
                    "path": relative(report_path),
                    "sha256": sha256(report_path),
                },
                "variants": {
                    name: {
                        "status": record["status"],
                        "failed_gates": record["failed_gates"],
                        "activity": record["weave_reduction"]["candidate"][
                            "activity_fraction"
                        ],
                        "activity_ratio": record["weave_reduction"][
                            "candidate_to_v18_activity_ratio"
                        ],
                        "highland_semantic": record["semantic_diagnostic"][
                            "highland"
                        ],
                        "palette": record["global_gates"]["palette"],
                        "downsample": record["global_gates"]["downsample"],
                        "candidate": record["candidate"],
                        "contacts": record["contacts"],
                    }
                    for name, record in records.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
