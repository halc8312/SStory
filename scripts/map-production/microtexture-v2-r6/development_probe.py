from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_ROOT = REPO_ROOT / "scripts" / "map-production" / "microtexture-v2-r6"
DEV_ROOT = REPO_ROOT / "tmp" / "map-production" / "microtexture-v2-r6-dev-r9"
FORMAL_ROOT = REPO_ROOT / "tmp" / "map-production" / "microtexture-v2-r6-artifacts"
PRIVATE_ANALYSIS_ROOT = DEV_ROOT / "private" / "analysis"
FORMAL_ENVIRONMENT = (
    "MICROTEXTURE_V2_R6_BLIND_KEY",
    "MICROTEXTURE_V2_R6_ARTIFACT_ROOT",
)
DEVELOPMENT_EDITION = "r9"
EXPECTED_RECORDS_PER_SPLIT = 220
EXPECTED_ARTIFACT_RECORDS_PER_SPLIT = 200
EXPECTED_ARTIFACT_CLUSTERS_PER_SPLIT = 100
EXPECTED_REVIEW_PAGES_PER_SPLIT = 37
EXPECTED_CONTACT_SHEETS_PER_SPLIT = 185
REVIEW_ROWS_PER_PAGE = 6
DEVELOPMENT_POPULATION_FLOORS = {
    "clean_acceptance": 19,
    "warning_acceptance": 13,
    "reject_detection": 38,
    "severity3_detection": 6,
    "grain_reject_detection": 10,
    "tiny_speck_reject_detection": 6,
    "microblob_reject_detection": 6,
    "spot_reject_detection": 10,
    "short_line_reject_detection": 10,
    "parallel_bundle_reject_detection": 8,
}
sys.path.insert(0, str(CODE_ROOT))

import common  # noqa: E402
from control_catalog import contact_sheet_pages, expected_controls  # noqa: E402
from metrics_v2_r6 import measure  # noqa: E402


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> str:
    payload = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return _sha256(payload)


def _write_json_exclusive(path: Path, value: Any) -> str:
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"development artifact already exists: {path}")
    payload = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(payload)
    return _sha256(payload)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"development JSON root must be an object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    return _sha256(path.read_bytes())


def _is_link_like(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or bool(is_junction and is_junction(path))


def _assert_no_link_like_ancestors(path: Path, lexical_root: Path) -> None:
    candidate = Path(os.path.abspath(path))
    root = Path(os.path.abspath(lexical_root))
    if candidate != root and root not in candidate.parents:
        raise RuntimeError(f"development path escapes lexical root: {path}")
    while True:
        if _is_link_like(candidate):
            raise RuntimeError(
                f"development path contains a symlink or junction: {candidate}"
            )
        if candidate == root:
            break
        candidate = candidate.parent


def _assert_development_boundary(*, root_must_not_exist: bool) -> None:
    configured = [name for name in FORMAL_ENVIRONMENT if os.environ.get(name)]
    if configured:
        raise RuntimeError(f"formal r6 environment is set: {configured}")
    if FORMAL_ROOT.exists() or _is_link_like(FORMAL_ROOT):
        raise RuntimeError("exact formal r6 artifact root already exists")
    resolved_repo = REPO_ROOT.resolve()
    resolved_dev = DEV_ROOT.resolve()
    resolved_formal = FORMAL_ROOT.resolve()
    if (
        resolved_dev == resolved_repo
        or resolved_repo not in resolved_dev.parents
        or resolved_repo not in resolved_formal.parents
        or resolved_dev == resolved_formal
        or resolved_dev in resolved_formal.parents
        or resolved_formal in resolved_dev.parents
    ):
        raise RuntimeError("development/formal root boundary is unsafe")
    _assert_no_link_like_ancestors(DEV_ROOT, REPO_ROOT)
    if root_must_not_exist and (DEV_ROOT.exists() or _is_link_like(DEV_ROOT)):
        raise RuntimeError(f"development root already exists: {DEV_ROOT}")


def _assert_private_analysis_boundary(*, analysis_must_exist: bool) -> None:
    _assert_development_boundary(root_must_not_exist=False)
    resolved_dev = DEV_ROOT.resolve(strict=True)
    expected_parent = (DEV_ROOT / "private").resolve(strict=True)
    resolved_parent = PRIVATE_ANALYSIS_ROOT.parent.resolve(strict=True)
    if (
        expected_parent != resolved_parent
        or resolved_dev not in resolved_parent.parents
    ):
        raise RuntimeError("development private-analysis parent escapes DEV_ROOT")
    _assert_no_link_like_ancestors(PRIVATE_ANALYSIS_ROOT.parent, REPO_ROOT)
    if analysis_must_exist:
        if not PRIVATE_ANALYSIS_ROOT.is_dir():
            raise RuntimeError("development private-analysis root is not a directory")
        _assert_no_link_like_ancestors(PRIVATE_ANALYSIS_ROOT, REPO_ROOT)
        resolved_analysis = PRIVATE_ANALYSIS_ROOT.resolve(strict=True)
        if (
            resolved_dev not in resolved_analysis.parents
            or resolved_analysis.parent != resolved_parent
        ):
            raise RuntimeError("development private-analysis root escapes DEV_ROOT")


def _load_spec() -> tuple[dict[str, Any], str]:
    payload = (CODE_ROOT / "preregistered-spec.json").read_bytes()
    digest = _sha256(payload)
    common.SPEC_SHA256 = digest
    value = json.loads(payload.decode("utf-8"))
    common.validate_preregistered_spec(value)
    return value, digest


def _public_nonces(spec: dict[str, Any]) -> dict[str, str]:
    nonces: dict[str, str] = {}
    for split in ("calibration", "holdout"):
        split_spec = spec.get("splits", {}).get(split)
        nonce = split_spec.get("public_nonce") if isinstance(split_spec, dict) else None
        if not isinstance(nonce, str) or not nonce:
            raise RuntimeError(f"{split} public nonce is missing from the spec")
        nonces[split] = nonce
    if len(set(nonces.values())) != len(nonces):
        raise RuntimeError("development split public nonces must be distinct")
    return nonces


def _validate_expected_control_population(controls: list[Any], split: str) -> None:
    if len(controls) != EXPECTED_RECORDS_PER_SPLIT:
        raise RuntimeError(f"{split} development control record-count drift")
    artifact_controls = [
        control for control in controls if control.private_role == "artifact"
    ]
    artifact_clusters = {control.condition_cluster_id for control in artifact_controls}
    cluster_counts = Counter(
        control.condition_cluster_id for control in artifact_controls
    )
    if (
        len(artifact_controls) != EXPECTED_ARTIFACT_RECORDS_PER_SPLIT
        or len(artifact_clusters) != EXPECTED_ARTIFACT_CLUSTERS_PER_SPLIT
        or any(count != 2 for count in cluster_counts.values())
    ):
        raise RuntimeError(f"{split} development artifact population drift")


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def _validate_development_key_git_boundary(
    spec: dict[str, Any], captured_head: str
) -> Path:
    handling = spec["development_probe_secret_handling"]
    key_relative = str(handling["ignored_private_key_required_repo_relative"])
    key_path = (REPO_ROOT / key_relative).resolve()
    required_path = (DEV_ROOT / "private" / "development-key.bin").resolve()
    if key_path != required_path:
        raise RuntimeError("development private-key path contract drift")

    gitignore_relative = str(handling["gitignore_required_repo_relative"])
    common._tracked_worktree_bytes(REPO_ROOT, captured_head, gitignore_relative)

    head_entry = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", captured_head, "--", key_relative],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if head_entry.returncode != 0:
        raise RuntimeError("development private-key HEAD inspection failed")
    if head_entry.stdout.strip():
        raise RuntimeError("development private-key path exists in captured HEAD")

    index_entry = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", key_relative],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if index_entry.returncode == 0:
        raise RuntimeError("development private-key path is tracked in the Git index")
    if index_entry.returncode != 1:
        raise RuntimeError("development private-key index inspection failed")

    ignored = subprocess.run(
        ["git", "check-ignore", "-v", "--no-index", "--", key_relative],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if ignored.returncode != 0:
        raise RuntimeError("development private-key path is not Git-ignored")
    metadata, separator, matched_path = ignored.stdout.rstrip("\r\n").rpartition("\t")
    source, first_colon, remainder = metadata.partition(":")
    line_number, second_colon, pattern = remainder.partition(":")
    if (
        separator != "\t"
        or matched_path != key_relative
        or first_colon != ":"
        or second_colon != ":"
        or source.replace("\\", "/") != gitignore_relative
        or not line_number.isdigit()
        or int(line_number) < 1
        or pattern != handling["gitignore_required_pattern"]
    ):
        raise RuntimeError(
            "development private-key ignore is not provided by the tracked root .gitignore"
        )
    common.assert_head_unchanged(captured_head)
    return key_path


def _tracked_input_preflight(spec: dict[str, Any], spec_sha: str) -> tuple[str, str]:
    captured_head = _git_head()
    branch = subprocess.check_output(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    upstream_ref = subprocess.check_output(
        [
            "git",
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            f"{branch}@{{upstream}}",
        ],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    upstream_head = subprocess.check_output(
        ["git", "rev-parse", upstream_ref], cwd=REPO_ROOT, text=True
    ).strip()
    if captured_head != upstream_head:
        raise RuntimeError("development HEAD is not equal to its upstream ref")
    repository = common.repository_root()
    code_relative = CODE_ROOT.relative_to(repository)
    if code_relative.as_posix() != spec["roots"]["code_root_required_repo_relative"]:
        raise RuntimeError("development CODE_ROOT contract drift")
    for relative in spec["authority_files"]:
        common._tracked_worktree_bytes(
            repository, captured_head, (code_relative / relative).as_posix()
        )
    bindings = common.validate_implementation_bindings()
    if bindings["spec_sha256"] != spec_sha:
        raise RuntimeError("development implementation/spec binding drift")
    common.verify_tracked_development_history(repository, captured_head, spec)
    common.verify_tracked_foundation_corpus_provenance(
        repository, captured_head, spec["foundation_corpus"]
    )
    _validate_development_key_git_boundary(spec, captured_head)
    common.assert_head_unchanged(captured_head)
    return captured_head, _sha256_file(CODE_ROOT / "implementation-bindings.json")


def _review_board(
    controls: list[Any],
    views: list[dict[str, Any]],
    page_index: int,
    output: Path,
) -> tuple[list[str], str]:
    panel_width, panel_height = 512, 384
    header_height = 36
    rows = REVIEW_ROWS_PER_PAGE
    selected = controls[(page_index - 1) * rows : page_index * rows]
    canvas = Image.new(
        "L", (panel_width * len(views), (panel_height + header_height) * rows), 32
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=16)
    for row, control in enumerate(selected):
        for column, view in enumerate(views):
            left, top, width, height = [int(item) for item in view["source_crop_xywh"]]
            crop = Image.fromarray(control.control).crop(
                (left, top, left + width, top + height)
            )
            display = crop.resize(
                (panel_width, panel_height), resample=Image.Resampling.NEAREST
            )
            x = column * panel_width
            y = row * (panel_height + header_height)
            draw.text(
                (x + 6, y + 14),
                f"ROW {row + 1}  {control.anonymous_code}  {view['id']}",
                fill=255,
                font=font,
            )
            canvas.paste(display, (x, y + header_height))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", compress_level=6, optimize=False)
    payload = output.read_bytes()
    return [item.anonymous_code for item in selected], _sha256(payload)


def _generate_split(
    spec: dict[str, Any],
    split: str,
    key: bytes,
    state: dict[str, Any],
) -> dict[str, Any]:
    controls = sorted(
        expected_controls(spec, split, key), key=lambda item: item.anonymous_code
    )
    _validate_expected_control_population(controls, split)
    pages = contact_sheet_pages(spec, split, controls)
    page_counts = Counter(page.view_id for page in pages)
    expected_views = {str(view["id"]) for view in spec["contact_sheets"]["views"]}
    if (
        len(pages) != EXPECTED_CONTACT_SHEETS_PER_SPLIT
        or set(page_counts) != expected_views
        or any(
            count != EXPECTED_REVIEW_PAGES_PER_SPLIT for count in page_counts.values()
        )
    ):
        raise RuntimeError(f"{split} development contact-sheet count drift")
    public_root = DEV_ROOT / "public" / split
    sheet_root = public_root / "contact-sheets"
    sheet_root.mkdir(parents=True, exist_ok=False)
    sheet_bundle: list[dict[str, Any]] = []
    for page in pages:
        name = Path(page.path).name
        target = sheet_root / name
        target.write_bytes(page.png_bytes)
        entry = page.manifest_entry()
        entry["path"] = target.relative_to(DEV_ROOT).as_posix()
        sheet_bundle.append(entry)

    records = [
        {
            "anonymous_code": control.anonymous_code,
            "control_commitment": control.control_commitment,
            "reference_commitment": control.reference_commitment,
            "delta_commitment": control.delta_commitment,
        }
        for control in controls
    ]
    manifest = {
        "artifact": "microtexture-v2-r6-development-control-manifest",
        "schema_version": "microtexture-v2-r6-development-control-manifest/1",
        "authority": False,
        "formal_use_forbidden": True,
        "split": split,
        "spec_sha256": state["spec_sha256"],
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "blind_key_commitment": state["blind_key_commitment"],
        "captured_git_head": state["captured_git_head"],
        "runtime": state["runtime"],
        "record_count": len(records),
        "records": records,
        "contact_sheet_bundle": sheet_bundle,
        "warning": "DEVELOPMENT ONLY; not a formal r6 manifest or authority artifact.",
    }
    manifest_path = public_root / "manifest.dev.json"
    manifest_sha = _write_json(manifest_path, manifest)
    labels = {
        "artifact": "microtexture-v2-r6-root-vision-labels",
        "schema_version": "microtexture-v2-r6-root-vision-labels/2",
        "split": split,
        "spec_sha256": state["spec_sha256"],
        "manifest_sha256": manifest_sha,
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "blind_key_commitment": state["blind_key_commitment"],
        "runtime": state["runtime"],
        "contact_sheet_bundle": sheet_bundle,
        "reviewer": "Root",
        "items": [
            {
                "anonymous_code": control.anonymous_code,
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
            for control in controls
        ],
    }
    labels_sha = _write_json(public_root / "labels.blank.dev.json", labels)

    board_root = public_root / "review-boards"
    review_pages = []
    for page_index in range(1, EXPECTED_REVIEW_PAGES_PER_SPLIT + 1):
        target = board_root / f"review-page-{page_index:03d}.png"
        codes, digest = _review_board(
            controls, spec["contact_sheets"]["views"], page_index, target
        )
        review_pages.append(
            {
                "page_index": page_index,
                "path": target.relative_to(DEV_ROOT).as_posix(),
                "sha256": digest,
                "item_codes": codes,
            }
        )
    review_index = {
        "artifact": "microtexture-v2-r6-development-review-index",
        "schema_version": "microtexture-v2-r6-development-review-index/1",
        "authority": False,
        "formal_use_forbidden": True,
        "split": split,
        "spec_sha256": state["spec_sha256"],
        "views": [view["id"] for view in spec["contact_sheets"]["views"]],
        "layout": "one anonymous code per row with a black header above its panels; full-200 plus all four 400-percent quadrants",
        "pages": review_pages,
    }
    review_index_sha = _write_json(public_root / "review-index.dev.json", review_index)
    return {
        "split": split,
        "record_count": len(controls),
        "contact_sheet_count": len(pages),
        "review_board_count": len(review_pages),
        "manifest_path": manifest_path.relative_to(DEV_ROOT).as_posix(),
        "manifest_sha256": manifest_sha,
        "blank_labels_path": (public_root / "labels.blank.dev.json")
        .relative_to(DEV_ROOT)
        .as_posix(),
        "blank_labels_sha256": labels_sha,
        "review_index_path": (public_root / "review-index.dev.json")
        .relative_to(DEV_ROOT)
        .as_posix(),
        "review_index_sha256": review_index_sha,
        "codes": [control.anonymous_code for control in controls],
        "control_ids": [control.control_id for control in controls],
        "cluster_ids": [control.condition_cluster_id for control in controls],
        "nonzero_delta_hashes": [
            control.delta_float32_sha256
            for control in controls
            if control.requested_delta.any()
        ],
        "zero_delta_hashes": [
            control.delta_float32_sha256
            for control in controls
            if not control.requested_delta.any()
        ],
    }


_FLAG_FIELDS = {
    "g": "grain_visible",
    "t": "tiny_speck_visible",
    "b": "microblob_visible",
    "l": "short_line_visible",
    "p": "parallel_bundle_visible",
}


def _checked_dev_file(relative: str, context: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise RuntimeError(f"{context} development path is invalid")
    path = DEV_ROOT / Path(relative)
    resolved_root = DEV_ROOT.resolve()
    resolved = path.resolve()
    if resolved_root not in resolved.parents or not path.is_file() or path.is_symlink():
        raise RuntimeError(f"{context} development path escaped or is not a file")
    return path


def _load_generation_state(spec: dict[str, Any], spec_sha: str) -> dict[str, Any]:
    boundary = _read_json(DEV_ROOT / "DEV-ONLY.json")
    summary = _read_json(DEV_ROOT / "generation-summary.dev.json")
    state = summary.get("state")
    if not isinstance(state, dict):
        raise RuntimeError("development generation state is missing")
    expected_bindings_sha = _sha256_file(CODE_ROOT / "implementation-bindings.json")
    if (
        boundary.get("authority") is not False
        or boundary.get("formal_use_forbidden") is not True
        or boundary.get("formal_cli_invoked") is not False
        or boundary.get("formal_marker_created") is not False
        or boundary.get("formal_threshold_created") is not False
        or boundary.get("locked_clean_v18_decoded_or_measured") is not False
        or state.get("development_edition") != DEVELOPMENT_EDITION
        or boundary.get("development_edition") != DEVELOPMENT_EDITION
        or state.get("spec_sha256") != spec_sha
        or state.get("public_nonces") != _public_nonces(spec)
        or state.get("implementation_bindings_sha256") != expected_bindings_sha
        or boundary.get("spec_sha256") != spec_sha
        or boundary.get("public_nonces") != state.get("public_nonces")
        or boundary.get("implementation_bindings_sha256") != expected_bindings_sha
        or boundary.get("blind_key_commitment") != state.get("blind_key_commitment")
    ):
        raise RuntimeError("development generation boundary/state drift")
    return state


def _parse_decisions(path: Path) -> dict[tuple[int, int], dict[str, Any]]:
    decisions: dict[tuple[int, int], dict[str, Any]] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=6)
        if len(parts) != 7:
            raise RuntimeError(f"decision DSL field drift: {path}:{line_number}")
        (
            page_text,
            row_text,
            anonymous_code,
            disposition,
            severity_text,
            flags_text,
            notes,
        ) = parts
        if (
            not page_text.isdigit()
            or not row_text.isdigit()
            or not severity_text.isdigit()
        ):
            raise RuntimeError(f"decision DSL numeric drift: {path}:{line_number}")
        page, row, severity = int(page_text), int(row_text), int(severity_text)
        key = (page, row)
        if key in decisions:
            raise RuntimeError(f"duplicate decision: {path}:{page_text}/{row_text}")
        if len(anonymous_code) != 24 or any(
            character not in "0123456789abcdef" for character in anonymous_code
        ):
            raise RuntimeError(
                f"decision DSL anonymous-code drift: {path}:{line_number}"
            )
        if flags_text == "-":
            flags: set[str] = set()
        else:
            flags = set(flags_text.split(","))
            if "" in flags or not flags.issubset(_FLAG_FIELDS):
                raise RuntimeError(f"decision DSL flag drift: {path}:{line_number}")
        consistent = (
            (disposition == "clean" and severity == 0 and not flags)
            or (disposition == "warning" and severity == 1 and bool(flags))
            or (disposition == "reject" and severity in {2, 3} and bool(flags))
        )
        if not consistent or not notes:
            raise RuntimeError(f"decision DSL semantic drift: {path}:{line_number}")
        decisions[key] = {
            "anonymous_code": anonymous_code,
            "disposition": disposition,
            "severity_0_to_3": severity,
            **{field: flag in flags for flag, field in _FLAG_FIELDS.items()},
            "reviewed_at_200_percent": True,
            "reviewed_at_all_400_percent_quadrants": True,
            "notes": notes,
        }
    return decisions


def _verify_bundle_files(entries: Any, context: str) -> None:
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"{context} bundle is empty")
    seen_paths: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RuntimeError(f"{context} bundle entry drift: {index}")
        relative, expected_sha = entry.get("path"), entry.get("sha256")
        if not isinstance(relative, str) or relative in seen_paths:
            raise RuntimeError(f"{context} duplicate/invalid path: {index}")
        seen_paths.add(relative)
        path = _checked_dev_file(relative, f"{context}[{index}]")
        if _sha256_file(path) != expected_sha:
            raise RuntimeError(f"{context} SHA drift: {relative}")


def _verify_contact_sheet_layout(
    entries: list[dict[str, Any]], spec: dict[str, Any], split: str
) -> None:
    expected_views = [str(view["id"]) for view in spec["contact_sheets"]["views"]]
    if len(expected_views) != 5 or len(set(expected_views)) != 5:
        raise RuntimeError(f"{split} development contact-sheet view drift")
    by_view_page: dict[tuple[str, int], list[str]] = {}
    for entry in entries:
        view_id = entry.get("view_id")
        page_index = entry.get("page_index")
        item_codes = entry.get("item_codes")
        key = (view_id, page_index)
        if (
            view_id not in expected_views
            or type(page_index) is not int
            or not 1 <= page_index <= EXPECTED_REVIEW_PAGES_PER_SPLIT
            or key in by_view_page
            or not isinstance(item_codes, list)
        ):
            raise RuntimeError(f"{split} development contact-sheet layout drift")
        remaining = EXPECTED_RECORDS_PER_SPLIT - (
            (page_index - 1) * REVIEW_ROWS_PER_PAGE
        )
        expected_count = min(REVIEW_ROWS_PER_PAGE, remaining)
        if len(item_codes) != expected_count:
            raise RuntimeError(
                f"{split}/{view_id} contact-sheet row-count drift: {page_index}"
            )
        by_view_page[key] = item_codes
    expected_keys = {
        (view_id, page_index)
        for view_id in expected_views
        for page_index in range(1, EXPECTED_REVIEW_PAGES_PER_SPLIT + 1)
    }
    if set(by_view_page) != expected_keys:
        raise RuntimeError(f"{split} development contact-sheet coverage drift")
    for page_index in range(1, EXPECTED_REVIEW_PAGES_PER_SPLIT + 1):
        code_orders = {
            tuple(by_view_page[(view_id, page_index)]) for view_id in expected_views
        }
        if len(code_orders) != 1:
            raise RuntimeError(
                f"{split} development contact-sheet cross-view order drift: "
                f"{page_index}"
            )


def _prepare_public_split(
    spec: dict[str, Any], state: dict[str, Any], split: str
) -> dict[str, Any]:
    public_root = DEV_ROOT / "public" / split
    manifest_path = public_root / "manifest.dev.json"
    blank_labels_path = public_root / "labels.blank.dev.json"
    review_index_path = public_root / "review-index.dev.json"
    decisions_path = public_root / "vision-decisions.dev.txt"
    root_decisions_path = public_root / "decisions-root.dev.txt"
    independent_decisions_path = public_root / "decisions-independent.dev.txt"
    manifest = _read_json(manifest_path)
    blank_labels = _read_json(blank_labels_path)
    review_index = _read_json(review_index_path)
    manifest_sha = _sha256_file(manifest_path)
    records = manifest.get("records")
    if (
        manifest.get("authority") is not False
        or manifest.get("formal_use_forbidden") is not True
        or manifest.get("split") != split
        or manifest.get("spec_sha256") != state["spec_sha256"]
        or manifest.get("implementation_bindings_sha256")
        != state["implementation_bindings_sha256"]
        or manifest.get("blind_key_commitment") != state["blind_key_commitment"]
        or not isinstance(records, list)
        or len(records) != EXPECTED_RECORDS_PER_SPLIT
        or manifest.get("record_count") != EXPECTED_RECORDS_PER_SPLIT
        or not isinstance(manifest.get("contact_sheet_bundle"), list)
        or len(manifest["contact_sheet_bundle"]) != EXPECTED_CONTACT_SHEETS_PER_SPLIT
    ):
        raise RuntimeError(f"{split} development manifest drift")
    codes = [
        record.get("anonymous_code") for record in records if isinstance(record, dict)
    ]
    if (
        len(codes) != EXPECTED_RECORDS_PER_SPLIT
        or len(set(codes)) != EXPECTED_RECORDS_PER_SPLIT
    ):
        raise RuntimeError(f"{split} development manifest code drift")
    _verify_bundle_files(manifest["contact_sheet_bundle"], f"{split} contact sheet")
    _verify_contact_sheet_layout(manifest["contact_sheet_bundle"], spec, split)

    pages = review_index.get("pages")
    if (
        review_index.get("authority") is not False
        or review_index.get("formal_use_forbidden") is not True
        or review_index.get("split") != split
        or review_index.get("spec_sha256") != state["spec_sha256"]
        or not isinstance(pages, list)
        or len(pages) != EXPECTED_REVIEW_PAGES_PER_SPLIT
    ):
        raise RuntimeError(f"{split} development review-index drift")
    page_rows: dict[tuple[int, int], str] = {}
    indexed_codes: list[str] = []
    for expected_page, page in enumerate(pages, start=1):
        if not isinstance(page, dict) or page.get("page_index") != expected_page:
            raise RuntimeError(f"{split} review page ordering drift")
        item_codes = page.get("item_codes")
        remaining = EXPECTED_RECORDS_PER_SPLIT - (
            (expected_page - 1) * REVIEW_ROWS_PER_PAGE
        )
        expected_count = min(REVIEW_ROWS_PER_PAGE, remaining)
        if not isinstance(item_codes, list) or len(item_codes) != expected_count:
            raise RuntimeError(f"{split} review page row-count drift: {expected_page}")
        relative = page.get("path")
        path = _checked_dev_file(relative, f"{split} review page {expected_page}")
        if _sha256_file(path) != page.get("sha256"):
            raise RuntimeError(f"{split} review page SHA drift: {expected_page}")
        for row, code in enumerate(item_codes, start=1):
            page_rows[(expected_page, row)] = code
            indexed_codes.append(code)
    if (
        len(indexed_codes) != EXPECTED_RECORDS_PER_SPLIT
        or len(set(indexed_codes)) != EXPECTED_RECORDS_PER_SPLIT
        or set(indexed_codes) != set(codes)
    ):
        raise RuntimeError(f"{split} review-index code coverage drift")

    decisions = _parse_decisions(decisions_path)
    root_decisions = _parse_decisions(root_decisions_path)
    independent_decisions = _parse_decisions(independent_decisions_path)
    for reviewer, reviewed in (
        ("canonical Root", decisions),
        ("Root", root_decisions),
        ("independent", independent_decisions),
    ):
        if set(reviewed) != set(page_rows):
            raise RuntimeError(f"{split} {reviewer} Vision decision coverage drift")
        if any(
            decision["anonymous_code"] != page_rows[key]
            for key, decision in reviewed.items()
        ):
            raise RuntimeError(f"{split} {reviewer} Vision printed-code binding drift")
    if decisions != root_decisions:
        raise RuntimeError(f"{split} canonical decisions are not exact Root decisions")
    logical_difference_count = sum(
        root_decisions[key] != independent_decisions[key]
        for key in sorted(root_decisions)
    )
    if logical_difference_count != 0:
        raise RuntimeError(
            f"{split} Root/independent Vision decisions are not reconciled"
        )
    by_code = {decision["anonymous_code"]: decision for decision in decisions.values()}
    completed = deepcopy(blank_labels)
    items = completed.get("items")
    if (
        completed.get("manifest_sha256") != manifest_sha
        or completed.get("spec_sha256") != state["spec_sha256"]
        or not isinstance(items, list)
        or len(items) != EXPECTED_RECORDS_PER_SPLIT
    ):
        raise RuntimeError(f"{split} blank label binding drift")
    for item in items:
        code = item.get("anonymous_code") if isinstance(item, dict) else None
        if code not in by_code:
            raise RuntimeError(f"{split} blank label code drift")
        item.update(by_code[code])
    labels = common.validate_vision_labels_payload(
        completed, split, manifest, manifest_sha, state
    )
    return {
        "split": split,
        "manifest": manifest,
        "manifest_sha256": manifest_sha,
        "completed_labels": completed,
        "labels": labels,
        "completed_labels_sha256": _sha256(_json_bytes(completed)),
        "review_index_sha256": _sha256_file(review_index_path),
        "decisions_sha256": _sha256_file(decisions_path),
        "root_decisions_sha256": _sha256_file(root_decisions_path),
        "independent_decisions_sha256": _sha256_file(independent_decisions_path),
        "root_independent_logical_difference_count": logical_difference_count,
        "dispositions": dict(Counter(item["disposition"] for item in labels.values())),
    }


def _public_preflight() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    _assert_development_boundary(root_must_not_exist=False)
    spec, spec_sha = _load_spec()
    state = _load_generation_state(spec, spec_sha)
    captured_head, bindings_sha = _tracked_input_preflight(spec, spec_sha)
    if (
        state.get("captured_git_head") != captured_head
        or state.get("implementation_bindings_sha256") != bindings_sha
    ):
        raise RuntimeError("development captured authority changed after generation")
    prepared = {
        split: _prepare_public_split(spec, state, split)
        for split in ("calibration", "holdout")
    }
    return spec, state, prepared


def preflight() -> None:
    _spec, _state, prepared = _public_preflight()
    _assert_development_boundary(root_must_not_exist=False)
    print(
        json.dumps(
            {
                "authority": False,
                "formal_use_forbidden": True,
                "formal_root_absent": True,
                "key_read": False,
                "labels_written": False,
                "splits": {
                    split: {
                        "record_count": len(result["labels"]),
                        "completed_labels_sha256": result["completed_labels_sha256"],
                        "dispositions": result["dispositions"],
                    }
                    for split, result in prepared.items()
                },
            },
            ensure_ascii=False,
        )
    )


def _regenerate_controls(
    spec: dict[str, Any], key: bytes, split: str, manifest: dict[str, Any]
) -> list[Any]:
    controls = sorted(
        expected_controls(spec, split, key), key=lambda item: item.anonymous_code
    )
    _validate_expected_control_population(controls, split)
    by_code = {control.anonymous_code: control for control in controls}
    if (
        len(controls) != EXPECTED_RECORDS_PER_SPLIT
        or len(by_code) != EXPECTED_RECORDS_PER_SPLIT
    ):
        raise RuntimeError(f"{split} regenerated control coverage drift")
    manifest_codes: set[str] = set()
    for record in manifest["records"]:
        code = record["anonymous_code"]
        control = by_code.get(code)
        if (
            control is None
            or record.get("control_commitment") != control.control_commitment
            or record.get("reference_commitment") != control.reference_commitment
            or record.get("delta_commitment") != control.delta_commitment
        ):
            raise RuntimeError(f"{split} regenerated public commitment drift")
        manifest_codes.add(code)
    if manifest_codes != set(by_code):
        raise RuntimeError(f"{split} regenerated manifest code drift")
    return controls


def _eligible_clusters(controls: list[Any], spec: dict[str, Any]) -> dict[str, str]:
    eligible_role = spec["threshold_selection"]["endpoint_eligible_private_role"]
    clusters = {
        control.anonymous_code: control.condition_cluster_id
        for control in controls
        if control.private_role == eligible_role
    }
    if not clusters:
        raise RuntimeError("development eligible cluster set is empty")
    return clusters


def _exact_metric_window(values: np.ndarray, spec: dict[str, Any]) -> np.ndarray:
    expected_canvas = (int(spec["canvas"]["height"]), int(spec["canvas"]["width"]))
    if values.shape != expected_canvas:
        raise RuntimeError(f"development control canvas drift: {values.shape}")
    x, y, width, height = [
        int(value) for value in spec["canvas"]["metric_window"]["xywh"]
    ]
    crop = values[y : y + height, x : x + width]
    expected = tuple(
        int(value) for value in spec["metric_definition"]["expected_shape_hw"]
    )
    if crop.shape != expected:
        raise RuntimeError("development exact metric-window crop drift")
    return crop


def _measure_split(
    controls: list[Any], clusters: dict[str, str], spec: dict[str, Any], split: str
) -> dict[str, dict[str, Any]]:
    measured: dict[str, dict[str, Any]] = {}
    controls_by_code = {control.anonymous_code: control for control in controls}
    for index, control in enumerate(controls, start=1):
        metrics = measure(
            _exact_metric_window(control.control, spec),
            _exact_metric_window(control.reference, spec),
            spec["metric_definition"],
        )
        common.validate_metric_values(metrics, spec, f"{split} development metric")
        if control.private_role == "protocol-zero" and any(
            value != 0 for name, value in metrics.items() if name != "eligible_pixels"
        ):
            raise RuntimeError(f"{split} protocol-zero metric drift")
        measured[control.anonymous_code] = {
            "anonymous_code": control.anonymous_code,
            "metrics": metrics,
        }
        if index % 20 == 0 or index == len(controls):
            print(f"{split}: measured {index}/{len(controls)}", flush=True)
    members: dict[str, list[str]] = {}
    for code, cluster_id in clusters.items():
        members.setdefault(cluster_id, []).append(code)
    for cluster_id, codes in members.items():
        if (
            len(codes) != 2
            or measured[codes[0]]["metrics"] != measured[codes[1]]["metrics"]
        ):
            raise RuntimeError(
                f"{split} full metric-equivalent polarity-pair drift: {cluster_id}"
            )
    if set(measured) != set(controls_by_code):
        raise RuntimeError(f"{split} measurement coverage drift")
    return measured


def _population_audit(
    labels: dict[str, dict[str, Any]],
    clusters: dict[str, str],
    spec: dict[str, Any],
    split: str,
) -> dict[str, Any]:
    counts = Counter(clusters.values())
    exact_pairs = bool(counts) and all(count == 2 for count in counts.values())
    endpoint_audit = common.endpoint_population_count_audit(labels, clusters, spec)
    frozen_floors = spec.get("population_anchor_schedule", {}).get(
        "development_premeasurement_safety_floors"
    )
    if frozen_floors != DEVELOPMENT_POPULATION_FLOORS:
        raise RuntimeError(f"{split} development safety-floor authority drift")
    if set(endpoint_audit["endpoints"]) != set(DEVELOPMENT_POPULATION_FLOORS):
        raise RuntimeError(f"{split} development endpoint set drift")
    development_endpoints = {
        endpoint_id: {
            "unique_cluster_count": endpoint_audit["endpoints"][endpoint_id][
                "unique_cluster_count"
            ],
            "development_minimum_unique_clusters": minimum,
            "count_passed": endpoint_audit["endpoints"][endpoint_id][
                "unique_cluster_count"
            ]
            >= minimum,
        }
        for endpoint_id, minimum in DEVELOPMENT_POPULATION_FLOORS.items()
    }
    development_audit = {
        "passed": all(item["count_passed"] for item in development_endpoints.values()),
        "endpoints": development_endpoints,
    }
    return {
        "split": split,
        "condition_cluster_count": len(counts),
        "all_condition_clusters_exact_polarity_pairs": exact_pairs,
        **endpoint_audit,
        "formal_endpoint_minimums_passed": endpoint_audit["passed"],
        "development_safety_floor_audit": development_audit,
        "passed": exact_pairs
        and endpoint_audit["passed"]
        and development_audit["passed"],
    }


def analyze() -> None:
    spec, state, prepared = _public_preflight()
    _assert_private_analysis_boundary(analysis_must_exist=False)
    if PRIVATE_ANALYSIS_ROOT.exists() or PRIVATE_ANALYSIS_ROOT.is_symlink():
        raise RuntimeError(
            "development analysis was already started; do not rerun or revise labels"
        )
    PRIVATE_ANALYSIS_ROOT.mkdir(parents=True, exist_ok=False)
    _assert_private_analysis_boundary(analysis_must_exist=True)
    measurement_started = False
    try:
        sealed: dict[str, Any] = {}
        for split, result in prepared.items():
            relative = Path("sealed-labels") / f"{split}.completed.dev.json"
            digest = _write_json_exclusive(
                PRIVATE_ANALYSIS_ROOT / relative, result["completed_labels"]
            )
            if digest != result["completed_labels_sha256"]:
                raise RuntimeError(f"{split} completed-label seal SHA drift")
            sealed[split] = {
                "path": relative.as_posix(),
                "sha256": digest,
                "manifest_sha256": result["manifest_sha256"],
                "review_index_sha256": result["review_index_sha256"],
                "decisions_sha256": result["decisions_sha256"],
                "root_decisions_sha256": result["root_decisions_sha256"],
                "independent_decisions_sha256": result["independent_decisions_sha256"],
                "root_independent_logical_difference_count": result[
                    "root_independent_logical_difference_count"
                ],
                "record_count": len(result["labels"]),
                "dispositions": result["dispositions"],
            }
        seal_receipt = {
            "artifact": "microtexture-v2-r6-development-label-seal",
            "schema_version": "microtexture-v2-r6-development-label-seal/1",
            "authority": False,
            "formal_use_forbidden": True,
            "root_vision_blind_during_all_decisions": True,
            "private_key_read_after_both_label_files_sealed": True,
            "spec_sha256": state["spec_sha256"],
            "implementation_bindings_sha256": state["implementation_bindings_sha256"],
            "blind_key_commitment": state["blind_key_commitment"],
            "splits": sealed,
        }
        seal_sha = _write_json_exclusive(
            PRIVATE_ANALYSIS_ROOT / "label-seal-receipt.dev.json", seal_receipt
        )

        key = (DEV_ROOT / "private" / "development-key.bin").read_bytes()
        if (
            len(key) != 32
            or common.blind_commitment(key) != state["blind_key_commitment"]
        ):
            raise RuntimeError("development blind-key commitment drift")

        controls: dict[str, list[Any]] = {}
        clusters: dict[str, dict[str, str]] = {}
        population: dict[str, Any] = {}
        for split, result in prepared.items():
            split_controls = _regenerate_controls(spec, key, split, result["manifest"])
            controls[split] = split_controls
            common.validate_private_vision_label_audits(
                result["labels"],
                [
                    {
                        "anonymous_code": control.anonymous_code,
                        "private_role": control.private_role,
                        "duplicate_audit_group": control.duplicate_audit_group,
                    }
                    for control in split_controls
                ],
                f"{split} development sealed labels",
            )
            clusters[split] = _eligible_clusters(split_controls, spec)
            population[split] = _population_audit(
                result["labels"], clusters[split], spec, split
            )
        population_artifact = {
            "artifact": "microtexture-v2-r6-development-premeasurement-population-audit",
            "schema_version": "microtexture-v2-r6-development-premeasurement-population-audit/1",
            "authority": False,
            "formal_use_forbidden": True,
            "measurement_started": False,
            "label_seal_receipt_sha256": seal_sha,
            "splits": population,
            "passed": all(item["passed"] for item in population.values()),
        }
        _write_json_exclusive(
            PRIVATE_ANALYSIS_ROOT / "population-audit.dev.json", population_artifact
        )
        if not population_artifact["passed"]:
            raise RuntimeError(
                "development endpoint population premeasurement audit failed"
            )
        for split, result in prepared.items():
            common.validate_endpoint_population_counts(
                result["labels"], clusters[split], spec
            )

        measurement_started = True
        measured = {
            split: _measure_split(controls[split], clusters[split], spec, split)
            for split in ("calibration", "holdout")
        }
        for split, values in measured.items():
            _write_json_exclusive(
                PRIVATE_ANALYSIS_ROOT / f"{split}-measurements.dev.json",
                {
                    "artifact": "microtexture-v2-r6-development-measurements",
                    "schema_version": "microtexture-v2-r6-development-measurements/1",
                    "authority": False,
                    "formal_use_forbidden": True,
                    "split": split,
                    "label_seal_receipt_sha256": seal_sha,
                    "measurements": [values[code] for code in sorted(values)],
                },
            )

        hard_threshold, calibration_endpoints, _calibration_results, status, audit = (
            common.select_hard_threshold_from_measurements(
                measured["calibration"],
                prepared["calibration"]["labels"],
                clusters["calibration"],
                spec,
            )
        )
        holdout_endpoints: dict[str, Any] | None = None
        if hard_threshold is not None:
            holdout_endpoints, _holdout_results = (
                common.evaluate_endpoints_from_measurements(
                    float(hard_threshold["threshold"]),
                    measured["holdout"],
                    prepared["holdout"]["labels"],
                    clusters["holdout"],
                    "holdout",
                    spec,
                )
            )
        passed = hard_threshold is not None and holdout_endpoints is not None
        passed = bool(
            passed
            and all(item["passed"] for item in calibration_endpoints.values())
            and all(item["passed"] for item in holdout_endpoints.values())
        )
        result_artifact = {
            "artifact": "microtexture-v2-r6-development-probe-result",
            "schema_version": "microtexture-v2-r6-development-probe-result/1",
            "authority": False,
            "formal_use_forbidden": True,
            "development_threshold_not_formal_authority": True,
            "formal_cli_invoked": False,
            "formal_marker_created": False,
            "locked_clean_v18_decoded_or_measured": False,
            "label_seal_receipt_sha256": seal_sha,
            "result_status": status,
            "passed": passed,
            "development_hard_threshold": hard_threshold,
            "calibration_endpoint_performance": calibration_endpoints,
            "holdout_endpoint_performance": holdout_endpoints,
            "threshold_selection_audit": audit,
        }
        _write_json_exclusive(
            PRIVATE_ANALYSIS_ROOT / "analysis-result.dev.json", result_artifact
        )
        if not passed:
            raise RuntimeError(
                "development metric schedule did not pass calibration and holdout"
            )
        _assert_development_boundary(root_must_not_exist=False)
        print(
            json.dumps(
                {
                    "authority": False,
                    "formal_use_forbidden": True,
                    "formal_root_absent": True,
                    "passed": True,
                    "result_status": status,
                    "development_threshold_not_formal_authority": True,
                    "calibration_endpoint_performance": calibration_endpoints,
                    "holdout_endpoint_performance": holdout_endpoints,
                },
                ensure_ascii=False,
            )
        )
    except BaseException as error:
        _assert_private_analysis_boundary(analysis_must_exist=True)
        failure_path = PRIVATE_ANALYSIS_ROOT / "FAILED.dev.json"
        if not failure_path.exists() and not failure_path.is_symlink():
            _write_json_exclusive(
                failure_path,
                {
                    "artifact": "microtexture-v2-r6-development-analysis-failure",
                    "schema_version": "microtexture-v2-r6-development-analysis-failure/1",
                    "authority": False,
                    "formal_use_forbidden": True,
                    "development_edition": DEVELOPMENT_EDITION,
                    "development_closed": True,
                    "measurement_started": measurement_started,
                    "error_type": type(error).__name__,
                    "message": str(error)[:512] or "exception without a message",
                },
            )
        _assert_development_boundary(root_must_not_exist=False)
        raise


def postmortem() -> None:
    """Read-only reveal for a closed development probe; never emits key material."""
    failure = PRIVATE_ANALYSIS_ROOT / "FAILED.dev.json"
    if not failure.is_file():
        raise RuntimeError("development postmortem requires a closed failed probe")
    spec, state, prepared = _public_preflight()
    key = (DEV_ROOT / "private" / "development-key.bin").read_bytes()
    if len(key) != 32 or common.blind_commitment(key) != state["blind_key_commitment"]:
        raise RuntimeError("development blind-key commitment drift")
    findings: dict[str, Any] = {}
    for split, result in prepared.items():
        controls = _regenerate_controls(spec, key, split, result["manifest"])
        page_by_code: dict[str, dict[str, int]] = {}
        index = _read_json(DEV_ROOT / "public" / split / "review-index.dev.json")
        for page in index["pages"]:
            for row, code in enumerate(page["item_codes"], start=1):
                page_by_code[code] = {"page": page["page_index"], "row": row}
        revealed = []
        speck_artifacts = []
        role_counts: Counter[str] = Counter()
        role_dispositions: dict[str, Counter[str]] = {}
        for control in controls:
            role_counts[control.private_role] += 1
            label = result["labels"][control.anonymous_code]
            role_dispositions.setdefault(control.private_role, Counter())[
                label["disposition"]
            ] += 1
            if control.private_role != "artifact":
                revealed.append(
                    {
                        **page_by_code[control.anonymous_code],
                        "private_role": control.private_role,
                        "duplicate_audit_group": control.duplicate_audit_group,
                        "disposition": label["disposition"],
                        "severity": label["severity_0_to_3"],
                        "visible_flags": [
                            flag for flag, field in _FLAG_FIELDS.items() if label[field]
                        ],
                        "notes": label["notes"],
                    }
                )
            elif control.family == "artifact-speck":
                speck_artifacts.append(
                    {
                        **page_by_code[control.anonymous_code],
                        "family": control.family,
                        "polarity": control.polarity,
                        "variant_index": control.variant_index,
                        "disposition": label["disposition"],
                        "severity": label["severity_0_to_3"],
                        "visible_flags": [
                            flag for flag, field in _FLAG_FIELDS.items() if label[field]
                        ],
                        "notes": label["notes"],
                    }
                )
        findings[split] = {
            "role_counts": dict(role_counts),
            "role_dispositions": {
                role: dict(counts) for role, counts in role_dispositions.items()
            },
            "non_artifact_rows": sorted(
                revealed, key=lambda item: (item["page"], item["row"])
            ),
            "artifact_speck_rows": sorted(
                speck_artifacts, key=lambda item: (item["page"], item["row"])
            ),
        }
    _assert_development_boundary(root_must_not_exist=False)
    print(
        json.dumps(
            {
                "authority": False,
                "formal_use_forbidden": True,
                "closed_development_probe_only": True,
                "findings": findings,
            },
            ensure_ascii=False,
        )
    )


def generate() -> None:
    _assert_development_boundary(root_must_not_exist=True)
    spec, spec_sha = _load_spec()
    captured_head, bindings_sha = _tracked_input_preflight(spec, spec_sha)
    key_path = _validate_development_key_git_boundary(spec, captured_head)
    key = secrets.token_bytes(32)
    state = {
        "development_edition": DEVELOPMENT_EDITION,
        "spec_sha256": spec_sha,
        "public_nonces": _public_nonces(spec),
        "implementation_bindings_sha256": bindings_sha,
        "blind_key_commitment": common.blind_commitment(key),
        "captured_git_head": captured_head,
        "runtime": common.runtime_fingerprint(),
    }
    DEV_ROOT.mkdir(parents=True, exist_ok=False)
    (DEV_ROOT / "private").mkdir()
    key_path.write_bytes(key)
    boundary = {
        "artifact": "microtexture-v2-r6-development-only-boundary",
        "schema_version": "microtexture-v2-r6-development-only-boundary/1",
        "authority": False,
        "formal_use_forbidden": True,
        "formal_cli_invoked": False,
        "formal_marker_created": False,
        "formal_threshold_created": False,
        "locked_clean_v18_decoded_or_measured": False,
        "exact_formal_root_absent_before_generation": True,
        "formal_environment_absent_before_generation": True,
        **state,
    }
    _write_json(DEV_ROOT / "DEV-ONLY.json", boundary)
    results = [
        _generate_split(spec, split, key, state) for split in ("calibration", "holdout")
    ]
    calibration, holdout = results
    for field in ("codes", "control_ids", "cluster_ids", "nonzero_delta_hashes"):
        if set(calibration[field]) & set(holdout[field]):
            raise RuntimeError(f"development split separation failed: {field}")
    calibration_zero = set(calibration["zero_delta_hashes"])
    holdout_zero = set(holdout["zero_delta_hashes"])
    if len(calibration_zero) != 1 or calibration_zero != holdout_zero:
        raise RuntimeError("canonical all-zero requested-delta hash contract drift")
    public_results = [
        {
            key: value
            for key, value in result.items()
            if key
            not in {
                "codes",
                "control_ids",
                "cluster_ids",
                "nonzero_delta_hashes",
                "zero_delta_hashes",
            }
        }
        for result in results
    ]
    _write_json(
        DEV_ROOT / "generation-summary.dev.json",
        {
            "artifact": "microtexture-v2-r6-development-generation-summary",
            "schema_version": "microtexture-v2-r6-development-generation-summary/1",
            "authority": False,
            "formal_use_forbidden": True,
            "state": state,
            "split_separation": {
                "codes_disjoint": True,
                "control_ids_disjoint": True,
                "cluster_ids_disjoint": True,
                "nonzero_delta_hashes_disjoint": True,
                "canonical_all_zero_delta_hash_shared": True,
            },
            "splits": public_results,
        },
    )
    _assert_development_boundary(root_must_not_exist=False)
    print(
        json.dumps(
            {
                "development_root": str(DEV_ROOT),
                "authority": False,
                "formal_root_absent": True,
                "splits": public_results,
            },
            ensure_ascii=False,
        )
    )


def review_crops(split: str, page_index: int) -> None:
    _assert_development_boundary(root_must_not_exist=False)
    if (
        split not in {"calibration", "holdout"}
        or not 1 <= page_index <= EXPECTED_REVIEW_PAGES_PER_SPLIT
    ):
        raise RuntimeError("review crop split/page drift")
    source = (
        DEV_ROOT
        / "public"
        / split
        / "review-boards"
        / f"review-page-{page_index:03d}.png"
    )
    with Image.open(source) as board:
        if board.size != (2560, 2520):
            raise RuntimeError("review board dimensions drift")
        output_root = DEV_ROOT / "public" / split / "review-crops"
        output_root.mkdir(parents=True, exist_ok=True)
        evidence = board.convert("RGB")
        evidence_draw = ImageDraw.Draw(evidence)
        evidence_font = ImageFont.load_default(size=14)
        quadrant_ids = ("NW", "NE", "SW", "SE")
        for row_index in range(REVIEW_ROWS_PER_PAGE):
            image_top = row_index * 420 + 36
            for quadrant_column, quadrant_id in enumerate(quadrant_ids, start=1):
                panel_left = quadrant_column * 512
                for division in (1, 2):
                    x = panel_left + round(512 * division / 3)
                    y = image_top + 128 * division
                    evidence_draw.line(
                        (x, image_top, x, image_top + 383),
                        fill=(220, 32, 96),
                        width=2,
                    )
                    evidence_draw.line(
                        (panel_left, y, panel_left + 511, y),
                        fill=(220, 32, 96),
                        width=2,
                    )
                for sector_row in range(1, 4):
                    for sector_column in range(1, 4):
                        label = f"{quadrant_id}-R{sector_row}C{sector_column}"
                        label_x = panel_left + round(512 * (sector_column - 1) / 3) + 4
                        label_y = image_top + 128 * (sector_row - 1) + 4
                        evidence_draw.text(
                            (label_x + 1, label_y + 1),
                            label,
                            fill=(255, 255, 255),
                            font=evidence_font,
                        )
                        evidence_draw.text(
                            (label_x, label_y),
                            label,
                            fill=(190, 0, 70),
                            font=evidence_font,
                        )
        evidence.save(
            output_root / f"evidence-page-{page_index:03d}.png",
            format="PNG",
            compress_level=6,
            optimize=False,
        )
        for row in range(1, REVIEW_ROWS_PER_PAGE + 1):
            top = (row - 1) * 420
            output = output_root / f"review-page-{page_index:03d}-row-{row}.png"
            board.crop((0, top, 2560, top + 420)).save(
                output, format="PNG", compress_level=6, optimize=False
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("generate", "preflight", "analyze", "postmortem", "review-crops"),
    )
    parser.add_argument("--split", choices=("calibration", "holdout"))
    parser.add_argument("--page", type=int)
    arguments = parser.parse_args()
    if arguments.command == "generate":
        generate()
    elif arguments.command == "preflight":
        preflight()
    elif arguments.command == "analyze":
        analyze()
    elif arguments.command == "review-crops":
        if arguments.split is None or arguments.page is None:
            parser.error("review-crops requires --split and --page")
        review_crops(arguments.split, arguments.page)
    else:
        postmortem()


if __name__ == "__main__":
    main()
