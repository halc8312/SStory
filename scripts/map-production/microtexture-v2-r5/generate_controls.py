"""Generate operationally blinded r5 calibration or authorized holdout sheets."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from common import (
    SPEC_SHA256,
    assert_head_unchanged,
    blind_commitment,
    blind_key,
    load_spec,
    operation_preflight,
    write_bytes_exclusive,
    write_json_exclusive,
)
from control_catalog import (
    bind_manifest_to_expected,
    contact_sheet_pages,
    expected_controls,
)


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _validate_private_controls(controls: list[Any]) -> None:
    if len(controls) != 140:
        raise RuntimeError("r5 generator requires exactly 140 private controls")
    roles = Counter(control.private_role for control in controls)
    if roles != Counter({"artifact": 120, "protocol-zero": 16, "duplicate-audit": 4}):
        raise RuntimeError("r5 generator private-role contract drift")
    if {control.foundation_id for control in controls} - {"v10", "v11", "v12"}:
        raise RuntimeError("r5 generator rejected foundation assignment")
    groups = Counter(
        control.duplicate_audit_group
        for control in controls
        if control.private_role == "duplicate-audit"
    )
    if groups != Counter({"clean": 2, "artifact": 2}):
        raise RuntimeError("r5 generator duplicate-audit contract drift")
    if any(
        control.duplicate_audit_group is not None
        for control in controls
        if control.private_role != "duplicate-audit"
    ):
        raise RuntimeError("r5 generator duplicate group leaked across roles")


def _labels(
    split: str,
    manifest_sha: str,
    sheets: list[dict[str, Any]],
    records: list[dict[str, Any]],
    state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "artifact": "microtexture-v2-r5-root-vision-labels",
        "schema_version": "microtexture-v2-r5-root-vision-labels/2",
        "split": split,
        "spec_sha256": SPEC_SHA256,
        "manifest_sha256": manifest_sha,
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "blind_key_commitment": state["blind_key_commitment"],
        "runtime": state["runtime"],
        "contact_sheet_bundle": sheets,
        "reviewer": "Root",
        "items": [
            {
                "anonymous_code": record["anonymous_code"],
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
            for record in sorted(records, key=lambda item: item["anonymous_code"])
        ],
    }


def generate(split: str) -> dict[str, Any]:
    if split not in {"calibration", "holdout"}:
        raise ValueError("invalid split")
    state = operation_preflight(
        require_receipt=split == "holdout",
        include_locked_clean_reference=split == "holdout",
    )
    key = blind_key()
    if blind_commitment(key) != state["blind_key_commitment"]:
        raise RuntimeError("blind key changed during generation")
    spec = load_spec()
    root = state["artifact_root"]
    split_root = root / "controls" / split
    if split_root.exists():
        raise RuntimeError(
            f"{split} generation is exclusive and directory already exists"
        )
    controls = expected_controls(spec, split, key)
    _validate_private_controls(controls)
    records = []
    for control in controls:
        records.append(
            {
                "anonymous_code": control.anonymous_code,
                "control_commitment": control.control_commitment,
                "reference_commitment": control.reference_commitment,
                "delta_commitment": control.delta_commitment,
            }
        )
    pages = contact_sheet_pages(spec, split, controls)
    for page in pages:
        write_bytes_exclusive(root, root / page.path, page.png_bytes)
    sheets = [page.manifest_entry() for page in pages]
    receipt_sha = state.get("threshold_authority_sha256")
    frozen_sha = state.get("threshold_authority", {}).get("frozen_thresholds_sha256")
    manifest = {
        "artifact": "microtexture-v2-r5-control-manifest",
        "schema_version": "microtexture-v2-r5-control-manifest/3",
        "split": split,
        "spec_sha256": SPEC_SHA256,
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "blind_key_commitment": state["blind_key_commitment"],
        "captured_git_head": state["captured_head"],
        "runtime": state["runtime"],
        "frozen_thresholds_sha256": frozen_sha,
        "threshold_authority_receipt_sha256": receipt_sha,
        "record_count": len(records),
        "records": sorted(records, key=lambda item: item["anonymous_code"]),
        "contact_sheet_bundle": sheets,
        "warning": (
            "Opaque codes and per-code, per-lane HMAC payload commitments only; "
            "no raw control/reference files, payload hashes, private role, "
            "foundation, duplicate group, or identity fields. The review surface is "
            "the contact-sheet bundle only. Private payload regeneration and reveal "
            "are forbidden until labels are sealed after the one-shot marker."
        ),
    }
    bind_manifest_to_expected(manifest, spec, split, key)
    manifest_path = split_root / "manifest.json"
    manifest_sha = write_json_exclusive(root, manifest_path, manifest)
    label_path = root / spec["labels"]["exact_artifact_paths"][split]
    write_json_exclusive(
        root, label_path, _labels(split, manifest_sha, sheets, records, state)
    )
    assert_head_unchanged(state["captured_head"])
    return {
        "split": split,
        "manifest": _relative(root, manifest_path),
        "manifest_sha256": manifest_sha,
        "labels": _relative(root, label_path),
        "blind_key_commitment": state["blind_key_commitment"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("calibration", "holdout"), required=True)
    print(generate(parser.parse_args().split))


if __name__ == "__main__":
    main()
