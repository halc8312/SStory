#!/usr/bin/env python3
"""Validate a hash-bound, fail-closed Phase 6 real-browser QA receipt.

The receipt is deliberately produced while ``world-v3`` is still selected via
``release-preview`` and readiness remains ``release-candidate``.  Publication
may consume a PASS receipt only while every tested repository byte is still
identical to the browser-tested input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Sequence
from urllib.parse import parse_qs, urlsplit

from PIL import Image, UnidentifiedImageError

import validate_release_readiness as readiness_validator
from production_common import REPO_ROOT, ValidationFailure, load_json, parse_rfc3339
from validate_manifest import schema_errors


VALIDATOR_ID = "sstory-map-production/validate_phase6_browser_qa.py@1"
RELEASE_ID = "world-v3"
BOUNDED_SHEET_COUNT = 23
PINNED_PLAYWRIGHT_CLI_VERSION = "0.1.17"
DEFAULT_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase6-browser-qa-receipt.schema.json"
)
READINESS = PurePosixPath("world/map-production/release-readiness.json")
PRODUCTION_MANIFEST = PurePosixPath("world/map-production/production-manifest.json")
CATALOG = PurePosixPath("world/map-production/source/map-sheets.json")
CANONICAL_INDEX = PurePosixPath("docs/data/map/sheet-tiles-v3.json")
COMPATIBILITY_INDEX = PurePosixPath("docs/data/map/region-rasters.json")
RELEASE_TREE = PurePosixPath("docs/assets/images/maps/tiles/world-v3")
WORLD_MANIFEST = RELEASE_TREE / "metadata.json"
HTML = PurePosixPath("docs/pages/interactive-map-v3.html")
RUNTIME_DEPENDENCIES = (
    PurePosixPath("docs/vendor/leaflet/leaflet.css"),
    PurePosixPath("docs/vendor/leaflet/leaflet.js"),
    PurePosixPath("docs/assets/css/interactive-map-v3.css"),
    PurePosixPath("docs/assets/js/interactive-map-v3-core.js"),
    PurePosixPath("docs/assets/js/interactive-map-v3.js"),
    PurePosixPath("docs/assets/images/maps/world/world-map-hires.jpg"),
    PurePosixPath("docs/data/map/nodes.json"),
    PurePosixPath("docs/data/map/routes.json"),
    PurePosixPath("docs/data/map/hazards.json"),
    PurePosixPath("docs/data/map/continents.json"),
    PurePosixPath("docs/data/map/regions.json"),
    PurePosixPath("docs/data/map/pois.json"),
    PurePosixPath("docs/data/map/pixel-mapping.json"),
)
HARNESS_ARTIFACTS = (
    PurePosixPath("scripts/map-production/run_phase6_browser_qa.py"),
    PurePosixPath("scripts/map-production/validate_phase6_browser_qa.py"),
    PurePosixPath("scripts/map-production/phase6_browser_qa_scenario.js"),
    PurePosixPath("scripts/map-production/phase6_browser_qa_collect.js"),
    PurePosixPath(
        "world/map-production/schemas/phase6-browser-qa-receipt.schema.json"
    ),
)
EXPECTED_SCENARIOS = (
    "desktop",
    "mobile",
    "slow_tiles",
    "royal_child_failure",
)
EXPECTED_VIEWPORTS = {
    "desktop": (1440, 1000),
    "mobile": (390, 844),
    "slow_tiles": (1440, 1000),
    "royal_child_failure": (1440, 1000),
}
COMMON_ASSERTIONS = frozenset(
    {
        "viewport_exact",
        "page_ready",
        "world_v3_selected",
        "index_23_bound",
        "served_html_hash_exact",
        "served_index_hash_exact",
        "served_world_manifest_hash_exact",
        "served_runtime_dependencies_exact",
        "served_tiles_hash_exact",
        "base_tiles_decoded",
        "base_tile_fallback_unused",
        "map_visible",
        "no_unexpected_console_errors",
        "no_page_errors",
        "no_unexpected_network_errors",
    }
)
SCENARIO_ASSERTIONS = {
    "desktop": COMMON_ASSERTIONS,
    "mobile": COMMON_ASSERTIONS | {"responsive_mobile_layout"},
    "slow_tiles": COMMON_ASSERTIONS
    | {
        "slow_tiles_observed",
        "slow_tiles_recovered",
        "served_parent_manifest_hash_exact",
    },
    "royal_child_failure": COMMON_ASSERTIONS
    | {
        "failure_injected",
        "nearest_parent_ready_before",
        "nearest_parent_ready_after",
        "nearest_parent_visible_after",
        "child_not_visible_after",
        "fallback_warning_exact",
        "served_parent_manifest_hash_exact",
        "served_child_manifest_hash_exact",
    },
}
ROYAL_CHILD_ID = "sheet_region_royal_capital_region"
ROYAL_PARENT_ID = "sheet_continent_elysion"


class BrowserQaValidationError(RuntimeError):
    """Raised when release-candidate evidence cannot be captured safely."""


def _repo_path(repo_root: Path, relative: PurePosixPath) -> Path:
    root = repo_root.resolve()
    path = root.joinpath(*relative.parts).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise BrowserQaValidationError(
            f"repository artifact escapes the repository: {relative.as_posix()}"
        ) from exc
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_file(repo_root: Path, relative: PurePosixPath) -> Path:
    path = _repo_path(repo_root, relative)
    if not path.is_file():
        raise BrowserQaValidationError(
            f"required Phase 6 input is missing: {relative.as_posix()}"
        )
    return path


def _artifact(relative: PurePosixPath, path: Path) -> dict[str, str]:
    return {"path": relative.as_posix(), "sha256": _sha256_file(path)}


def _artifact_set(
    repo_root: Path, relatives: Sequence[PurePosixPath]
) -> dict[str, Any]:
    artifacts = [
        _artifact(relative, _required_file(repo_root, relative))
        for relative in sorted(relatives, key=lambda value: value.as_posix())
    ]
    binding = {
        artifact["path"]: artifact["sha256"] for artifact in artifacts
    }
    aggregate = hashlib.sha256(
        json.dumps(
            binding,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {"artifacts": artifacts, "sha256": aggregate}


def _manifest_artifact(
    repo_root: Path, entry: dict[str, Any], label: str
) -> dict[str, str]:
    raw = entry.get("manifest_url")
    if (
        not isinstance(raw, str)
        or not raw
        or "\\" in raw
        or "?" in raw
        or "#" in raw
        or raw.startswith("/")
        or ":" in raw.split("/", 1)[0]
    ):
        raise BrowserQaValidationError(f"{label} has an invalid manifest_url")
    joined = PurePosixPath(
        posixpath.normpath(posixpath.join(CANONICAL_INDEX.parent.as_posix(), raw))
    )
    if (
        joined.is_absolute()
        or any(part in {"", ".", ".."} for part in joined.parts)
        or joined.parts[: len(RELEASE_TREE.parts)] != RELEASE_TREE.parts
        or joined.name != "metadata.json"
    ):
        raise BrowserQaValidationError(
            f"{label} manifest_url escapes the immutable world-v3 release"
        )
    path = _required_file(repo_root, joined)
    artifact = _artifact(joined, path)
    if entry.get("manifest_sha256") != artifact["sha256"]:
        raise BrowserQaValidationError(f"{label} manifest_sha256 is stale")
    return artifact


def _bounded_catalog_ids(repo_root: Path) -> set[str]:
    catalog = load_json(_required_file(repo_root, CATALOG))
    sheets = catalog.get("sheets") if isinstance(catalog, dict) else None
    if not isinstance(sheets, list):
        raise BrowserQaValidationError("map-sheets catalog lacks a sheets array")
    ids = {
        sheet.get("id")
        for sheet in sheets
        if isinstance(sheet, dict)
        and isinstance(sheet.get("id"), str)
        and sheet.get("review_status") != "planned"
        and sheet.get("bounds") is not None
    }
    if len(ids) != BOUNDED_SHEET_COUNT:
        raise BrowserQaValidationError(
            f"Phase 6 requires exactly {BOUNDED_SHEET_COUNT} bounded sheets, found {len(ids)}"
        )
    return ids


def _index_entries(index: Any) -> list[dict[str, Any]]:
    if not isinstance(index, dict):
        raise BrowserQaValidationError("canonical sheet index must be an object")
    root = index.get("root")
    sheets = index.get("sheets")
    if not isinstance(root, dict) or not isinstance(sheets, list):
        raise BrowserQaValidationError("canonical sheet index lacks root/sheets")
    entries = [root, *sheets]
    if (
        index.get("release_id") != RELEASE_ID
        or index.get("bounded_sheet_count") != BOUNDED_SHEET_COUNT
        or len(entries) != BOUNDED_SHEET_COUNT
    ):
        raise BrowserQaValidationError(
            "browser QA requires the exact all-23 world-v3 runtime index"
        )
    if any(
        not isinstance(entry, dict)
        or not isinstance(entry.get("sheet_id"), str)
        or entry.get("status") != "staging"
        or entry.get("review_status") != "accepted"
        for entry in entries
    ):
        raise BrowserQaValidationError(
            "browser QA requires every world-v3 index entry to be accepted/staging"
        )
    ids = [entry["sheet_id"] for entry in entries]
    if len(set(ids)) != BOUNDED_SHEET_COUNT:
        raise BrowserQaValidationError("world-v3 runtime index duplicates sheet IDs")
    return entries


def capture_release_candidate_inputs(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Recompute the exact bytes a Phase 6 browser run is permitted to test."""

    repo_root = repo_root.resolve()
    readiness_path = _required_file(repo_root, READINESS)
    readiness = load_json(readiness_path)
    if not isinstance(readiness, dict) or readiness.get("status") != "release-candidate":
        raise BrowserQaValidationError(
            "Phase 6 browser QA requires readiness status 'release-candidate'"
        )

    canonical_path = _required_file(repo_root, CANONICAL_INDEX)
    compatibility_path = _required_file(repo_root, COMPATIBILITY_INDEX)
    if canonical_path.read_bytes() != compatibility_path.read_bytes():
        raise BrowserQaValidationError(
            "canonical and compatibility world-v3 indexes must be byte-identical"
        )
    index = load_json(canonical_path)
    entries = _index_entries(index)
    bounded_ids = _bounded_catalog_ids(repo_root)
    index_ids = {entry["sheet_id"] for entry in entries}
    if index_ids != bounded_ids:
        raise BrowserQaValidationError(
            "world-v3 runtime index does not exactly cover the bounded sheet catalog"
        )

    manifest_path = _required_file(repo_root, PRODUCTION_MANIFEST)
    manifest = load_json(manifest_path)
    jobs = manifest.get("jobs") if isinstance(manifest, dict) else None
    if not isinstance(jobs, list):
        raise BrowserQaValidationError("production manifest lacks jobs")
    staged = [
        job
        for job in jobs
        if isinstance(job, dict) and job.get("sheet_id") in bounded_ids
    ]
    if (
        len(staged) != BOUNDED_SHEET_COUNT
        or {job.get("sheet_id") for job in staged} != bounded_ids
        or any(job.get("status") != "staging" for job in staged)
    ):
        raise BrowserQaValidationError(
            "browser QA requires exactly 23 bounded production jobs in staging"
        )

    release_tree = _repo_path(repo_root, RELEASE_TREE)
    if not release_tree.is_dir():
        raise BrowserQaValidationError(
            f"world-v3 release tree is missing: {RELEASE_TREE.as_posix()}"
        )
    file_count, tree_sha = readiness_validator._release_tree_evidence(release_tree)
    world_manifest_path = _required_file(repo_root, WORLD_MANIFEST)
    html_path = _required_file(repo_root, HTML)
    by_sheet = {entry["sheet_id"]: entry for entry in entries}
    try:
        royal_parent = by_sheet[ROYAL_PARENT_ID]
        royal_child = by_sheet[ROYAL_CHILD_ID]
    except KeyError as exc:
        raise BrowserQaValidationError(
            "world-v3 index lacks the exact Royal failure-probe sheets"
        ) from exc
    return {
        "readiness_status": "release-candidate",
        "bounded_sheet_count": BOUNDED_SHEET_COUNT,
        "readiness": _artifact(READINESS, readiness_path),
        "production_manifest": _artifact(PRODUCTION_MANIFEST, manifest_path),
        "canonical_index": _artifact(CANONICAL_INDEX, canonical_path),
        "compatibility_index": _artifact(COMPATIBILITY_INDEX, compatibility_path),
        "release_tree": {
            "path": RELEASE_TREE.as_posix(),
            "file_count": file_count,
            "sha256": tree_sha,
        },
        "world_manifest": _artifact(WORLD_MANIFEST, world_manifest_path),
        "html": _artifact(HTML, html_path),
        "runtime_dependencies": _artifact_set(repo_root, RUNTIME_DEPENDENCIES),
        "harness": _artifact_set(repo_root, HARNESS_ARTIFACTS),
        "royal_probe": {
            "parent": {
                "sheet_id": ROYAL_PARENT_ID,
                "manifest": _manifest_artifact(
                    repo_root, royal_parent, "Royal nearest parent"
                ),
            },
            "child": {
                "sheet_id": ROYAL_CHILD_ID,
                "manifest": _manifest_artifact(
                    repo_root, royal_child, "Royal failure child"
                ),
            },
        },
    }


def _evidence_path(
    artifact_root: Path, owner: Any, label: str
) -> tuple[Path | None, list[str]]:
    if not isinstance(owner, dict):
        return None, [f"{label} must be an object"]
    raw_path = owner.get("path")
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        return None, [f"{label}.path must be a relative POSIX path"]
    portable = PurePosixPath(raw_path)
    if portable.is_absolute() or any(part in {"", ".", ".."} for part in portable.parts):
        return None, [f"{label}.path must stay inside the receipt artifact root"]
    root = artifact_root.resolve()
    path = root.joinpath(*portable.parts).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None, [f"{label}.path escapes the receipt artifact root"]
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"{label}.path does not exist: {raw_path}")
    elif path.stat().st_size == 0:
        errors.append(f"{label}.path is empty: {raw_path}")
    elif owner.get("sha256") != _sha256_file(path):
        errors.append(f"{label}.sha256 does not match {raw_path}")
    return path, errors


def _png_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.format != "PNG":
                return None
            return image.size
    except (
        OSError,
        SyntaxError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ):
        return None


def _png_has_visual_content(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            sample = image.convert("RGB")
            sample.thumbnail((128, 128))
            colors = sample.getcolors(maxcolors=128 * 128 + 1)
            extrema = sample.getextrema()
    except (
        OSError,
        SyntaxError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ):
        return False
    return bool(
        colors
        and len(colors) >= 8
        and sum(high - low for low, high in extrema) >= 48
    )


def _web_path(tested_url: str, repository_path: str) -> str:
    pathname = urlsplit(tested_url).path
    suffix = "/pages/interactive-map-v3.html"
    if not pathname.endswith(suffix):
        raise BrowserQaValidationError(
            f"tested_url path must end with {suffix}"
        )
    if not repository_path.startswith("docs/"):
        raise BrowserQaValidationError(
            f"browser-served artifact is outside docs/: {repository_path}"
        )
    prefix = pathname[: -len(suffix)]
    return f"{prefix}/{repository_path.removeprefix('docs/')}"


def build_scenario_options(
    scenario_id: str,
    *,
    tested_url: str,
    inputs: dict[str, Any],
    delay_ms: int,
    timeout_ms: int,
) -> dict[str, Any]:
    """Build the exact, hash-bound browser driver options for one scenario."""

    width, height = EXPECTED_VIEWPORTS[scenario_id]
    responses: list[dict[str, str]] = []

    def add_response(label: str, artifact: dict[str, str]) -> None:
        responses.append(
            {
                "label": label,
                "repositoryPath": artifact["path"],
                "pathname": _web_path(tested_url, artifact["path"]),
                "sha256": artifact["sha256"],
            }
        )

    add_response("html", inputs["html"])
    add_response("index", inputs["compatibility_index"])
    add_response("worldManifest", inputs["world_manifest"])
    runtime_artifacts = inputs["runtime_dependencies"]["artifacts"]
    for position, artifact in enumerate(runtime_artifacts):
        add_response(f"runtime:{position:02d}", artifact)
    parent = inputs["royal_probe"]["parent"]
    child = inputs["royal_probe"]["child"]
    add_response("royalParentManifest", parent["manifest"])
    add_response("royalChildManifest", child["manifest"])
    return {
        "mode": scenario_id,
        "testedUrl": tested_url,
        "expectedResponses": responses,
        "runtimeResponseLabels": [
            item["label"] for item in responses if item["label"].startswith("runtime:")
        ],
        "viewport": {"width": width, "height": height},
        "delayMs": delay_ms,
        "navigationTimeoutMs": timeout_ms,
        "readinessTimeoutMs": timeout_ms,
        "royalChildId": ROYAL_CHILD_ID,
        "royalParentId": ROYAL_PARENT_ID,
    }


def scenario_config(scenario_id: str) -> dict[str, Any]:
    width, height = EXPECTED_VIEWPORTS[scenario_id]
    return {
        "browser": {
            "launchOptions": {"headless": True},
            "contextOptions": {
                "viewport": {"width": width, "height": height},
                "reducedMotion": "reduce",
                **(
                    {"isMobile": True, "hasTouch": True}
                    if scenario_id == "mobile"
                    else {}
                ),
            },
        }
    }


def _runtime_hashes(inputs: dict[str, Any]) -> dict[str, str]:
    owner = inputs.get("runtime_dependencies")
    artifacts = owner.get("artifacts") if isinstance(owner, dict) else None
    if not isinstance(artifacts, list):
        return {}
    return {
        artifact.get("path"): artifact.get("sha256")
        for artifact in artifacts
        if isinstance(artifact, dict)
        and isinstance(artifact.get("path"), str)
        and isinstance(artifact.get("sha256"), str)
    }


def _declared_artifact_set_errors(
    owner: Any,
    *,
    label: str,
    expected_paths: Sequence[PurePosixPath],
) -> list[str]:
    if not isinstance(owner, dict) or not isinstance(owner.get("artifacts"), list):
        return [f"{label} must declare an artifacts array"]
    artifacts = owner["artifacts"]
    actual_paths = [
        item.get("path") for item in artifacts if isinstance(item, dict)
    ]
    expected = sorted(path.as_posix() for path in expected_paths)
    errors: list[str] = []
    if actual_paths != expected:
        errors.append(f"{label} must contain the exact locked artifact paths in order")
    binding = {
        item.get("path"): item.get("sha256")
        for item in artifacts
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and isinstance(item.get("sha256"), str)
    }
    aggregate = hashlib.sha256(
        json.dumps(
            binding,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if len(binding) != len(expected) or owner.get("sha256") != aggregate:
        errors.append(f"{label}.sha256 does not bind its exact artifact map")
    return errors


def _persisted_invariant_input_errors(
    inputs: Any,
    *,
    repo_root: Path,
) -> list[str]:
    """Recheck bytes that publication does not intentionally mutate."""

    if not isinstance(inputs, dict):
        return ["persisted browser QA inputs must be an object"]
    errors: list[str] = []
    runtime = inputs.get("runtime_dependencies")
    artifacts = runtime.get("artifacts") if isinstance(runtime, dict) else None
    if not isinstance(artifacts, list):
        errors.append("persisted runtime dependency artifacts are missing")
    else:
        for position, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict) or not isinstance(
                artifact.get("path"), str
            ):
                errors.append(
                    f"persisted runtime dependency [{position}] is malformed"
                )
                continue
            relative = PurePosixPath(artifact["path"])
            try:
                path = _required_file(repo_root, relative)
            except (OSError, BrowserQaValidationError) as exc:
                errors.append(f"persisted runtime dependency is unavailable: {exc}")
                continue
            if artifact.get("sha256") != _sha256_file(path):
                errors.append(
                    "persisted runtime dependency changed after browser QA: "
                    + relative.as_posix()
                )

    release_owner = inputs.get("release_tree")
    release_root = _repo_path(repo_root, RELEASE_TREE)
    if not isinstance(release_owner, dict) or not release_root.is_dir():
        errors.append("persisted world-v3 release tree is unavailable")
    else:
        try:
            file_count, tree_sha = readiness_validator._release_tree_evidence(
                release_root
            )
        except OSError as exc:
            errors.append(f"cannot hash persisted world-v3 release tree: {exc}")
        else:
            if (
                release_owner.get("path") != RELEASE_TREE.as_posix()
                or release_owner.get("file_count") != file_count
                or release_owner.get("sha256") != tree_sha
            ):
                errors.append(
                    "world-v3 release tree changed after the Phase 6 browser QA"
                )
    return errors


def _compact_event(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def _royal_tile_url(url: Any) -> bool:
    if not isinstance(url, str):
        return False
    try:
        pathname = urlsplit(url).path
    except ValueError:
        return False
    return (
        f"/sheets/{ROYAL_CHILD_ID}/" in pathname
        and pathname.endswith(".webp")
        and "/tiles/world-v3/" in pathname
    )


def _classify_diagnostics(
    scenario_id: str,
    console_document: Any,
    network_document: Any,
) -> tuple[dict[str, list[str]] | None, list[str]]:
    errors: list[str] = []
    if not isinstance(console_document, dict):
        return None, ["console evidence must be a JSON object"]
    if not isinstance(network_document, dict):
        return None, ["network evidence must be a JSON object"]
    console_events = console_document.get("events")
    page_errors = console_document.get("page_errors")
    network_events = network_document.get("events")
    if not isinstance(console_events, list) or any(
        not isinstance(item, dict) for item in console_events
    ):
        errors.append("console evidence events must be an array of objects")
        console_events = []
    if not isinstance(page_errors, list) or any(
        not isinstance(item, str) for item in page_errors
    ):
        errors.append("console evidence page_errors must be an array of strings")
        page_errors = []
    if not isinstance(network_events, list) or any(
        not isinstance(item, dict) for item in network_events
    ):
        errors.append("network evidence events must be an array of objects")
        network_events = []

    exact_warning = (
        "[InteractiveMapV3] Sheet tiles unavailable; retaining nearest parent "
        f"{ROYAL_PARENT_ID}: {ROYAL_CHILD_ID}"
    )
    def is_exact_fallback_warning(item: dict[str, Any]) -> bool:
        text = item.get("text")
        return (
            item.get("type") == "warning"
            and isinstance(text, str)
            and (text == exact_warning or text.startswith(exact_warning + " "))
        )

    expected_warnings = [
        item.get("text")
        for item in console_events
        if scenario_id == "royal_child_failure"
        and is_exact_fallback_warning(item)
    ]
    unexpected_console = [
        f"{item.get('type')}: {item.get('text')}"
        for item in console_events
        if item.get("type") == "error"
        or (
            item.get("type") == "warning"
            and not (
                scenario_id == "royal_child_failure"
                and is_exact_fallback_warning(item)
            )
        )
    ]
    expected_network = [
        _compact_event(item)
        for item in network_events
        if scenario_id == "royal_child_failure"
        and item.get("kind") == "response"
        and item.get("status") == 503
        and _royal_tile_url(item.get("url"))
    ]
    unexpected_network = [
        _compact_event(item)
        for item in network_events
        if not (
            scenario_id == "royal_child_failure"
            and item.get("kind") == "response"
            and item.get("status") == 503
            and _royal_tile_url(item.get("url"))
        )
    ]
    return (
        {
            "console_errors": unexpected_console,
            "page_errors": page_errors,
            "network_errors": unexpected_network,
            "expected_console_warnings": expected_warnings,
            "expected_network_failures": expected_network,
        },
        errors,
    )


def _release_tile_path(repo_root: Path, url_path: Any) -> Path | None:
    if not isinstance(url_path, str):
        return None
    marker = "/assets/images/maps/tiles/world-v3/"
    try:
        pathname = urlsplit(url_path).path
    except ValueError:
        return None
    position = pathname.find(marker)
    if position < 0 or not pathname.endswith(".webp"):
        return None
    relative = PurePosixPath("docs" + pathname[position:])
    if any(part in {"", ".", ".."} for part in relative.parts):
        return None
    try:
        path = _repo_path(repo_root, relative)
    except BrowserQaValidationError:
        return None
    try:
        path.relative_to(_repo_path(repo_root, RELEASE_TREE))
    except ValueError:
        return None
    return path


def _tested_url_errors(value: Any) -> list[str]:
    if not isinstance(value, str):
        return ["tested_url must be a string"]
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ["tested_url must be a valid absolute HTTP(S) URL"]
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ["tested_url must be an absolute HTTP(S) URL"]
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        return ["tested_url must not contain credentials or a fragment"]
    values = parse_qs(parsed.query, keep_blank_values=True).get("release-preview", [])
    if values != [RELEASE_ID]:
        return ["tested_url must contain exactly one release-preview=world-v3 parameter"]
    if not parsed.path.endswith("/pages/interactive-map-v3.html"):
        return ["tested_url must target /pages/interactive-map-v3.html"]
    return []


def validate_browser_qa_receipt(
    receipt: Any,
    *,
    repo_root: Path = REPO_ROOT,
    artifact_root: Path,
    schema_path: Path = DEFAULT_SCHEMA,
    require_pass: bool = True,
    verify_current_inputs: bool = True,
) -> list[str]:
    """Validate structure, evidence files, semantics, and current byte identity."""

    errors: list[str] = []
    if not isinstance(receipt, dict):
        return ["Phase 6 browser QA receipt must be a JSON object"]
    try:
        schema = load_json(schema_path)
        errors.extend(
            f"browser QA receipt: {error}" for error in schema_errors(receipt, schema)
        )
    except ValidationFailure as exc:
        errors.append(str(exc))

    errors.extend(_tested_url_errors(receipt.get("tested_url")))
    if require_pass:
        playwright = receipt.get("playwright")
        if (
            not isinstance(playwright, dict)
            or playwright.get("cli_version") != PINNED_PLAYWRIGHT_CLI_VERSION
        ):
            errors.append(
                "PASS browser QA receipt requires pinned Playwright CLI "
                f"{PINNED_PLAYWRIGHT_CLI_VERSION}"
            )
        if not isinstance(playwright, dict) or playwright.get("browser_version") in {
            None,
            "",
            "unknown",
            "unavailable",
        }:
            errors.append("PASS browser QA receipt requires an identified Chromium version")
    try:
        started = parse_rfc3339(receipt.get("started_at", ""))
        completed = parse_rfc3339(receipt.get("completed_at", ""))
        if completed < started:
            errors.append("completed_at precedes started_at")
    except (TypeError, ValueError) as exc:
        errors.append(f"browser QA receipt timestamp is invalid: {exc}")

    if verify_current_inputs:
        try:
            expected_inputs = capture_release_candidate_inputs(repo_root)
        except (OSError, ValidationFailure, BrowserQaValidationError) as exc:
            errors.append(f"cannot recompute browser QA inputs: {exc}")
        else:
            if receipt.get("inputs") != expected_inputs:
                errors.append(
                    "browser QA input hashes do not exactly match the current release-candidate"
                )
    else:
        errors.extend(
            _persisted_invariant_input_errors(
                receipt.get("inputs"),
                repo_root=repo_root,
            )
        )

    scenarios = receipt.get("scenarios")
    if not isinstance(scenarios, list):
        scenarios = []
    ids = [scenario.get("id") for scenario in scenarios if isinstance(scenario, dict)]
    if sorted(ids) != sorted(EXPECTED_SCENARIOS) or len(ids) != len(set(ids)):
        errors.append("browser QA receipt must contain each of the four scenarios exactly once")

    declared_inputs = receipt.get("inputs")
    declared_inputs = declared_inputs if isinstance(declared_inputs, dict) else {}
    errors.extend(
        _declared_artifact_set_errors(
            declared_inputs.get("runtime_dependencies"),
            label="inputs.runtime_dependencies",
            expected_paths=RUNTIME_DEPENDENCIES,
        )
    )
    errors.extend(
        _declared_artifact_set_errors(
            declared_inputs.get("harness"),
            label="inputs.harness",
            expected_paths=HARNESS_ARTIFACTS,
        )
    )
    expected_served_hashes = {
        "served_html_sha256": (
            declared_inputs.get("html", {}).get("sha256")
            if isinstance(declared_inputs.get("html"), dict)
            else None
        ),
        "served_index_sha256": (
            declared_inputs.get("compatibility_index", {}).get("sha256")
            if isinstance(declared_inputs.get("compatibility_index"), dict)
            else None
        ),
        "served_world_manifest_sha256": (
            declared_inputs.get("world_manifest", {}).get("sha256")
            if isinstance(declared_inputs.get("world_manifest"), dict)
            else None
        ),
    }
    expected_runtime_hashes = _runtime_hashes(declared_inputs)
    royal_probe = declared_inputs.get("royal_probe")
    royal_probe = royal_probe if isinstance(royal_probe, dict) else {}
    expected_probe_hashes = {
        owner.get("sheet_id"): owner.get("manifest", {}).get("sha256")
        for owner in royal_probe.values()
        if isinstance(owner, dict) and isinstance(owner.get("manifest"), dict)
    }
    evidence_paths_seen: set[str] = set()

    for scenario in scenarios:
        if not isinstance(scenario, dict):
            errors.append("browser QA scenario must be an object")
            continue
        scenario_id = scenario.get("id")
        label = f"scenario[{scenario_id!r}]"
        expected_viewport = EXPECTED_VIEWPORTS.get(scenario_id)
        viewport = scenario.get("viewport")
        if expected_viewport and (
            not isinstance(viewport, dict)
            or (viewport.get("width"), viewport.get("height")) != expected_viewport
        ):
            errors.append(
                f"{label} viewport must be {expected_viewport[0]}x{expected_viewport[1]}"
            )
        assertions = scenario.get("assertions")
        required_assertions = SCENARIO_ASSERTIONS.get(scenario_id, frozenset())
        scenario_requires_pass = require_pass or scenario.get("result") == "pass"
        if not isinstance(assertions, dict):
            errors.append(f"{label}.assertions must be an object")
        elif scenario_requires_pass:
            if set(assertions) != set(required_assertions):
                errors.append(f"{label}.assertions must contain the exact locked checks")
            failed = sorted(
                name for name in required_assertions if assertions.get(name) is not True
            )
            if failed:
                errors.append(f"{label} failed required assertions: {', '.join(failed)}")

        diagnostics = scenario.get("diagnostics")
        if scenario_requires_pass and isinstance(diagnostics, dict):
            for key in ("console_errors", "page_errors", "network_errors"):
                value = diagnostics.get(key)
                if isinstance(value, list) and value:
                    errors.append(f"{label}.{key} must be empty for a PASS")
        metrics = scenario.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        if scenario_requires_pass and metrics.get("selected_release") != RELEASE_ID:
            errors.append(f"{label} did not select world-v3")
        if scenario_requires_pass and metrics.get("index_release_id") != RELEASE_ID:
            errors.append(f"{label} did not bind the world-v3 sheet index")
        if scenario_requires_pass and metrics.get("bounded_sheet_count") != BOUNDED_SHEET_COUNT:
            errors.append(f"{label} did not observe all 23 bounded sheets")
        if scenario_requires_pass and not isinstance(metrics.get("browser_user_agent"), str):
            errors.append(f"{label} did not record its browser user agent")
        if scenario_requires_pass and scenario.get("error") is not None:
            errors.append(f"{label} PASS must not contain a harness error")
        if scenario_requires_pass:
            if metrics.get("base_tiles_decoded") is not True:
                errors.append(f"{label} did not prove a decoded world-v3 base tile")
            if metrics.get("base_tile_fallback_used") is not False:
                errors.append(f"{label} observed a world-v3 base tile decode failure")
            for metric_name, expected_hash in expected_served_hashes.items():
                if metrics.get(metric_name) != expected_hash:
                    errors.append(
                        f"{label}.{metric_name} does not match the browser-tested repository input"
                    )
            if metrics.get("served_runtime_sha256") != expected_runtime_hashes:
                errors.append(
                    f"{label}.served_runtime_sha256 does not bind every runtime dependency"
                )
            served_tiles = metrics.get("served_tiles")
            if not isinstance(served_tiles, list) or not served_tiles:
                errors.append(f"{label} did not hash any served world-v3 tile bytes")
            else:
                valid_tile_count = 0
                parent_tile_count = 0
                for position, tile in enumerate(served_tiles):
                    if not isinstance(tile, dict):
                        errors.append(f"{label}.served_tiles[{position}] must be an object")
                        continue
                    url_path = tile.get("url_path")
                    tile_path = _release_tile_path(repo_root, url_path)
                    if tile_path is None or not tile_path.is_file():
                        errors.append(
                            f"{label}.served_tiles[{position}] is not an immutable world-v3 tile"
                        )
                        continue
                    if tile.get("sha256") != _sha256_file(tile_path):
                        errors.append(
                            f"{label}.served_tiles[{position}] differs from repository bytes"
                        )
                        continue
                    valid_tile_count += 1
                    if f"/sheets/{ROYAL_PARENT_ID}/" in urlsplit(str(url_path)).path:
                        parent_tile_count += 1
                if valid_tile_count < 1:
                    errors.append(f"{label} has no valid hash-bound served tile")
                if scenario_id in {"slow_tiles", "royal_child_failure"} and parent_tile_count < 1:
                    errors.append(f"{label} did not hash a served Elysion parent tile")
            probe_hashes = metrics.get("served_probe_manifest_sha256")
            probe_hashes = probe_hashes if isinstance(probe_hashes, dict) else {}
            if scenario_id in {"slow_tiles", "royal_child_failure"} and probe_hashes.get(
                ROYAL_PARENT_ID
            ) != expected_probe_hashes.get(ROYAL_PARENT_ID):
                errors.append(f"{label} did not hash the exact Elysion parent manifest")
            if scenario_id == "royal_child_failure" and probe_hashes.get(
                ROYAL_CHILD_ID
            ) != expected_probe_hashes.get(ROYAL_CHILD_ID):
                errors.append(f"{label} did not hash the exact Royal child manifest")
        if scenario_requires_pass and scenario_id == "slow_tiles":
            if not isinstance(metrics.get("delay_ms"), int) or metrics.get("delay_ms", 0) < 400:
                errors.append("slow_tiles.delay_ms must be at least 400")
            if not isinstance(metrics.get("delayed_tile_requests"), int) or metrics.get(
                "delayed_tile_requests", 0
            ) < 1:
                errors.append("slow_tiles must delay at least one world-v3 tile request")
        if scenario_requires_pass and scenario_id == "royal_child_failure":
            if metrics.get("injected_status") != 503:
                errors.append("royal_child_failure must inject HTTP 503")
            if metrics.get("failed_child_id") != ROYAL_CHILD_ID:
                errors.append("royal_child_failure targeted the wrong child sheet")
            if metrics.get("nearest_parent_id") != ROYAL_PARENT_ID:
                errors.append("royal_child_failure retained the wrong nearest parent")
            if not isinstance(metrics.get("failure_response_count"), int) or metrics.get(
                "failure_response_count", 0
            ) < 1:
                errors.append("royal_child_failure did not observe a failed child tile response")
            if metrics.get("parent_status_before") != "ready" or metrics.get(
                "parent_status_after"
            ) != "ready":
                errors.append(
                    "royal_child_failure must prove the exact nearest parent ready before/after"
                )
            failed_sheet_ids = metrics.get("failed_sheet_ids")
            if not isinstance(failed_sheet_ids, list) or ROYAL_CHILD_ID not in failed_sheet_ids:
                errors.append("royal_child_failure did not bind failure to the Royal child ID")
            visible_sheet_ids = metrics.get("visible_sheet_ids")
            if (
                not isinstance(visible_sheet_ids, list)
                or ROYAL_PARENT_ID not in visible_sheet_ids
                or ROYAL_CHILD_ID in visible_sheet_ids
            ):
                errors.append(
                    "royal_child_failure must retain only the exact visible Elysion parent"
                )
            if not isinstance(diagnostics, dict) or not diagnostics.get(
                "expected_console_warnings"
            ):
                errors.append("royal_child_failure lacks the exact fallback warning")
            if not isinstance(diagnostics, dict) or not diagnostics.get(
                "expected_network_failures"
            ):
                errors.append("royal_child_failure lacks the injected 503 evidence")

        evidence = scenario.get("evidence")
        if scenario.get("result") == "pass" or require_pass:
            if not isinstance(evidence, dict):
                errors.append(f"{label} PASS requires screenshot/snapshot/diagnostic evidence")
            else:
                evidence_files = {
                    "screenshot": "screenshot.png",
                    "snapshot": "snapshot.md",
                    "console": "console.json",
                    "network": "network.json",
                    "driver": "scenario-driver.js",
                    "config": "playwright-cli.json",
                }
                resolved: dict[str, Path] = {}
                for kind, filename in evidence_files.items():
                    owner = evidence.get(kind)
                    expected_relative = f"scenarios/{scenario_id}/{filename}"
                    if not isinstance(owner, dict) or owner.get("path") != expected_relative:
                        errors.append(
                            f"{label}.evidence.{kind}.path must be exactly {expected_relative}"
                        )
                    evidence_path, evidence_errors = _evidence_path(
                        artifact_root, owner, f"{label}.evidence.{kind}"
                    )
                    errors.extend(evidence_errors)
                    if isinstance(owner, dict) and isinstance(owner.get("path"), str):
                        if owner["path"] in evidence_paths_seen:
                            errors.append(
                                f"{label}.evidence.{kind}.path is reused by another artifact"
                            )
                        evidence_paths_seen.add(owner["path"])
                    if evidence_path is not None and evidence_path.is_file():
                        resolved[kind] = evidence_path
                    if (
                        kind == "screenshot"
                        and evidence_path is not None
                        and evidence_path.is_file()
                        and expected_viewport is not None
                        and _png_dimensions(evidence_path) != expected_viewport
                    ):
                        errors.append(
                            f"{label}.evidence.screenshot must be an exact "
                            f"{expected_viewport[0]}x{expected_viewport[1]} viewport PNG"
                        )
                    if (
                        kind == "screenshot"
                        and evidence_path is not None
                        and evidence_path.is_file()
                        and not _png_has_visual_content(evidence_path)
                    ):
                        errors.append(
                            f"{label}.evidence.screenshot must contain non-blank visual evidence"
                        )
                snapshot_path = resolved.get("snapshot")
                if snapshot_path is not None:
                    try:
                        snapshot_text = snapshot_path.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        errors.append(f"{label}.evidence.snapshot must be UTF-8 text")
                    else:
                        if len(snapshot_text.strip()) < 16:
                            errors.append(
                                f"{label}.evidence.snapshot lacks a meaningful page snapshot"
                            )

                config_path = resolved.get("config")
                if config_path is not None:
                    expected_config = (
                        json.dumps(
                            scenario_config(str(scenario_id)),
                            ensure_ascii=False,
                            indent=2,
                            allow_nan=False,
                        )
                        + "\n"
                    )
                    try:
                        actual_config = config_path.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        actual_config = ""
                    if actual_config != expected_config:
                        errors.append(f"{label}.evidence.config is not the locked context config")

                driver_path = resolved.get("driver")
                if driver_path is not None and verify_current_inputs:
                    configured_delay = metrics.get("configured_delay_ms")
                    timeout_ms = metrics.get("timeout_ms")
                    if not isinstance(configured_delay, int) or not isinstance(timeout_ms, int):
                        errors.append(
                            f"{label} must record configured_delay_ms and timeout_ms"
                        )
                    else:
                        try:
                            template_path = _required_file(
                                repo_root,
                                PurePosixPath(
                                    "scripts/map-production/phase6_browser_qa_scenario.js"
                                ),
                            )
                            template = template_path.read_text(encoding="utf-8")
                            options = build_scenario_options(
                                str(scenario_id),
                                tested_url=str(receipt.get("tested_url")),
                                inputs=declared_inputs,
                                delay_ms=configured_delay,
                                timeout_ms=timeout_ms,
                            )
                            expected_driver = template.replace(
                                "__PHASE6_OPTIONS_JSON__",
                                json.dumps(
                                    options,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            )
                        except (
                            OSError,
                            BrowserQaValidationError,
                            KeyError,
                            TypeError,
                            ValueError,
                            IndexError,
                        ) as exc:
                            errors.append(f"{label} cannot reconstruct locked driver: {exc}")
                        else:
                            if template.count("__PHASE6_OPTIONS_JSON__") != 1:
                                errors.append(
                                    f"{label} scenario template marker is not unique"
                                )
                            else:
                                try:
                                    actual_driver = driver_path.read_text(encoding="utf-8")
                                except (OSError, UnicodeDecodeError):
                                    actual_driver = ""
                                if actual_driver != expected_driver:
                                    errors.append(
                                        f"{label}.evidence.driver differs from the locked scenario"
                                    )

                console_path = resolved.get("console")
                network_path = resolved.get("network")
                if console_path is not None and network_path is not None:
                    try:
                        console_document = json.loads(
                            console_path.read_text(encoding="utf-8")
                        )
                        network_document = json.loads(
                            network_path.read_text(encoding="utf-8")
                        )
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                        errors.append(f"{label} diagnostic evidence is invalid JSON: {exc}")
                    else:
                        derived, diagnostic_errors = _classify_diagnostics(
                            str(scenario_id), console_document, network_document
                        )
                        errors.extend(f"{label}: {error}" for error in diagnostic_errors)
                        if derived is not None and diagnostics != derived:
                            errors.append(
                                f"{label}.diagnostics do not match raw console/network evidence"
                            )
                        if scenario_id == "royal_child_failure" and derived is not None:
                            if metrics.get("failure_response_count") != len(
                                derived["expected_network_failures"]
                            ):
                                errors.append(
                                    "royal_child_failure response count differs from raw evidence"
                                )
                            for encoded in derived["expected_network_failures"]:
                                try:
                                    event = json.loads(encoded)
                                except json.JSONDecodeError:
                                    errors.append(
                                        "royal_child_failure expected network evidence is malformed"
                                    )
                                    continue
                                child_path = _release_tile_path(repo_root, event.get("url"))
                                if child_path is None or not child_path.is_file():
                                    errors.append(
                                        "royal_child_failure injected URL is not a declared child tile"
                                    )

    failure_reasons = receipt.get("failure_reasons")
    if require_pass:
        browser_versions: list[str | None] = []
        for scenario in scenarios:
            metrics = scenario.get("metrics") if isinstance(scenario, dict) else None
            user_agent = (
                metrics.get("browser_user_agent") if isinstance(metrics, dict) else None
            )
            if isinstance(user_agent, str):
                match = re.search(r"(?:Chrome|Chromium)/([0-9.]+)", user_agent)
                if match:
                    browser_versions.append(match.group(1))
                    continue
            browser_versions.append(None)
        playwright = receipt.get("playwright")
        declared_browser = (
            playwright.get("browser_version") if isinstance(playwright, dict) else None
        )
        if (
            len(browser_versions) != len(EXPECTED_SCENARIOS)
            or any(version != declared_browser for version in browser_versions)
        ):
            errors.append(
                "Playwright browser_version must exactly match every scenario user agent"
            )
        if receipt.get("result") != "pass":
            errors.append("Phase 7 publication requires a PASS browser QA receipt")
        if failure_reasons != []:
            errors.append("PASS browser QA receipt must have no failure_reasons")
        failed_ids = [
            scenario.get("id")
            for scenario in scenarios
            if isinstance(scenario, dict) and scenario.get("result") != "pass"
        ]
        if failed_ids:
            errors.append("browser QA scenarios did not all pass: " + ", ".join(failed_ids))
    elif receipt.get("result") == "pass":
        if failure_reasons != [] or any(
            isinstance(scenario, dict) and scenario.get("result") != "pass"
            for scenario in scenarios
        ):
            errors.append("PASS browser QA receipt is inconsistent with its failures")
    elif receipt.get("result") == "fail":
        if not isinstance(failure_reasons, list) or not failure_reasons:
            errors.append("FAIL browser QA receipt requires at least one failure reason")
    return errors


def validate_browser_qa_receipt_file(
    receipt_path: Path,
    *,
    repo_root: Path = REPO_ROOT,
    schema_path: Path = DEFAULT_SCHEMA,
    require_pass: bool = True,
    verify_current_inputs: bool = True,
) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        receipt = load_json(receipt_path)
    except ValidationFailure as exc:
        return None, [str(exc)]
    errors = validate_browser_qa_receipt(
        receipt,
        repo_root=repo_root,
        artifact_root=receipt_path.resolve().parent,
        schema_path=schema_path,
        require_pass=require_pass,
        verify_current_inputs=verify_current_inputs,
    )
    return receipt if isinstance(receipt, dict) else None, errors


def validate_persisted_browser_qa_bundle(
    receipt_path: Path,
    *,
    repo_root: Path = REPO_ROOT,
    schema_path: Path = DEFAULT_SCHEMA,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate an immutable published bundle without requiring RC status.

    Publication changes readiness, index statuses, and active-release HTML after
    the source bundle has already been current-byte validated.  Persisted
    validation therefore skips only that mutable repository recapture; schema,
    browser assertions, served hashes, tile bytes, and every evidence file stay
    mandatory.
    """

    return validate_browser_qa_receipt_file(
        receipt_path,
        repo_root=repo_root,
        schema_path=schema_path,
        require_pass=True,
        verify_current_inputs=False,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--allow-fail", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    receipt, errors = validate_browser_qa_receipt_file(
        args.receipt,
        repo_root=args.repo_root,
        schema_path=args.schema,
        require_pass=not args.allow_fail,
    )
    result = {
        "valid": not errors,
        "validator": VALIDATOR_ID,
        "receipt": str(args.receipt),
        "release_id": receipt.get("release_id") if receipt else None,
        "result": receipt.get("result") if receipt else None,
        "scenario_count": len(receipt.get("scenarios", [])) if receipt else 0,
        "errors": errors,
    }
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print(f"Phase 6 browser QA receipt failed: {args.receipt}", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    else:
        print(f"Phase 6 browser QA receipt passed: {args.receipt}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
