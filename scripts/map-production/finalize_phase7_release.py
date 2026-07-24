#!/usr/bin/env python3
"""Finalize the world-v3 release boundary without writing its receipt.

This command deliberately has two transitions:

``release-candidate``
    Copies the validated Phase 5 build manifest into the canonical manifest,
    rewrites the 23 bounded jobs to the already-published docs tile paths, and
    advances the jobs/index/readiness from ``tiled`` to ``staging``.

``published``
    Requires that release-candidate state and a current-byte-bound PASS receipt
    from the four-scenario Phase 6 real-browser harness, advances exactly those
    23 jobs and index entries to ``published``, and activates world-v3 in the
    runtime HTML.  It first copies and revalidates the receipt-declared QA
    evidence into the canonical repository bundle, then records that bundle's
    receipt/tree hashes and the canonical publication-receipt path in readiness.
    It never creates the final receipt; ``write_publication_receipt.py`` remains
    the mandatory last step.

Every durable target is written through a same-directory temporary file.  The
readiness declaration is replaced last, so it is the commit pointer for the
multi-file transition; ordinary exceptions restore every prior byte string.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

import build_phase5_assets as phase5
import validate_phase6_browser_qa as browser_qa_validator
import validate_release as release_validator
from production_common import REPO_ROOT, ValidationFailure, load_json, parse_rfc3339, utc_now
from validate_manifest import schema_errors


FINALIZER_ID = "sstory-map-production/finalize_phase7_release.py@1"
RELEASE_ID = "world-v3"
BOUNDED_SHEET_COUNT = 23
EXPECTED_SHEET_TYPES = {
    "world": 1,
    "continent": 5,
    "region": 14,
    "corridor": 1,
    "settlement": 2,
}
RECEIPT_RELATIVE_PATH = PurePosixPath(
    "world/map-production/releases/world-v3-publication-receipt.json"
)
BROWSER_QA_BUNDLE_RELATIVE_PATH = PurePosixPath(
    "world/map-production/releases/world-v3-phase6-browser-qa"
)
BROWSER_QA_RECEIPT_NAME = "phase6-browser-qa-receipt.json"
MANIFEST_RELATIVE_PATH = PurePosixPath(
    "world/map-production/production-manifest.json"
)
READINESS_RELATIVE_PATH = PurePosixPath(
    "world/map-production/release-readiness.json"
)
CATALOG_RELATIVE_PATH = PurePosixPath(
    "world/map-production/source/map-sheets.json"
)
MANIFEST_SCHEMA_RELATIVE_PATH = PurePosixPath(
    "world/map-production/schemas/production-manifest.schema.json"
)
READINESS_SCHEMA_RELATIVE_PATH = PurePosixPath(
    "world/map-production/schemas/release-readiness.schema.json"
)
QA_SCHEMA_RELATIVE_PATH = PurePosixPath(
    "world/map-production/schemas/qa-report.schema.json"
)
QA_DIR_RELATIVE_PATH = PurePosixPath("world/map-production/qa")
RESOLUTION_CONTRACT_RELATIVE_PATH = PurePosixPath(
    "world/map-production/spec/resolution-contract.json"
)
INDEX_SCHEMA_RELATIVE_PATH = PurePosixPath(
    "world/map-production/schemas/sheet-tile-index.schema.json"
)
CANONICAL_INDEX_RELATIVE_PATH = PurePosixPath(
    "docs/data/map/sheet-tiles-v3.json"
)
COMPATIBILITY_INDEX_RELATIVE_PATH = PurePosixPath(
    "docs/data/map/region-rasters.json"
)
HTML_RELATIVE_PATH = PurePosixPath("docs/pages/interactive-map-v3.html")
PUBLIC_RELEASE_RELATIVE_PATH = PurePosixPath(
    "docs/assets/images/maps/tiles/world-v3"
)
HTML_REQUIRED_META = {
    "ea-map-world-target-release": "world-v3",
    "ea-map-world-fallback-releases": "world-v2,world-v1",
    "ea-map-world-v3-manifest": (
        "../assets/images/maps/tiles/world-v3/metadata.json"
    ),
    "ea-map-world-v2-manifest": (
        "../assets/images/maps/tiles/world-v2/metadata.json"
    ),
    "ea-map-world-v1-manifest": (
        "../assets/images/maps/tiles/world-v1/metadata.json"
    ),
    "ea-map-sheet-tile-index": "../data/map/region-rasters.json",
}


class ReleaseFinalizationError(RuntimeError):
    """Raised when a Phase 7 state transition cannot be proven safe."""


def _repo_path(repo_root: Path, relative: PurePosixPath) -> Path:
    return repo_root.joinpath(*relative.parts)


def _inside_repo(path: Path, repo_root: Path, label: str) -> Path:
    resolved = path.resolve()
    root = repo_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReleaseFinalizationError(
            f"{label} must stay inside the repository: {path}"
        ) from exc
    if resolved == root:
        raise ReleaseFinalizationError(f"{label} may not be the repository root")
    return resolved


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = load_json(path)
    except ValidationFailure as exc:
        raise ReleaseFinalizationError(f"{label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseFinalizationError(f"{label} must contain a JSON object")
    return value


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_tree_evidence(root: Path) -> tuple[int, str]:
    """Return a deterministic file-count/tree hash and reject symlink ambiguity."""

    if not root.is_dir() or root.is_symlink():
        raise ReleaseFinalizationError(f"browser QA bundle is not a real directory: {root}")
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ReleaseFinalizationError(
                f"browser QA bundle must not contain symlinks: {path}"
            )
        if path.is_file():
            hashes[path.relative_to(root).as_posix()] = _sha256_file(path)
        elif not path.is_dir():
            raise ReleaseFinalizationError(
                f"browser QA bundle contains an unsupported filesystem entry: {path}"
            )
    digest = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return len(hashes), digest


def _validated_timestamp(value: str | None) -> str:
    timestamp = value or utc_now()
    try:
        parse_rfc3339(timestamp)
    except ValueError as exc:
        raise ReleaseFinalizationError(str(exc)) from exc
    return timestamp


def _bounded_catalog(repo_root: Path) -> tuple[dict[str, dict[str, Any]], Counter[str]]:
    catalog = _object(
        _repo_path(repo_root, CATALOG_RELATIVE_PATH), "map-sheets catalog"
    )
    sheets = catalog.get("sheets")
    if not isinstance(sheets, list):
        raise ReleaseFinalizationError("map-sheets catalog must contain a sheets array")
    bounded: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for index, sheet in enumerate(sheets):
        if not isinstance(sheet, dict) or not isinstance(sheet.get("id"), str):
            raise ReleaseFinalizationError(
                f"map-sheets.sheets[{index}] must define a string id"
            )
        if sheet.get("review_status") == "planned" or sheet.get("bounds") is None:
            continue
        sheet_id = sheet["id"]
        if sheet_id in bounded:
            raise ReleaseFinalizationError(
                f"map-sheets catalog duplicates bounded sheet {sheet_id!r}"
            )
        bounded[sheet_id] = sheet
        counts[str(sheet.get("sheet_type"))] += 1
    if len(bounded) != BOUNDED_SHEET_COUNT or dict(counts) != EXPECTED_SHEET_TYPES:
        raise ReleaseFinalizationError(
            "Phase 7 requires exactly all 23 bounded sheets "
            f"({EXPECTED_SHEET_TYPES}), found {dict(counts)}"
        )
    return bounded, counts


def _load_readiness(repo_root: Path, expected_status: str) -> dict[str, Any]:
    path = _repo_path(repo_root, READINESS_RELATIVE_PATH)
    readiness = _object(path, "release readiness declaration")
    schema = _object(
        _repo_path(repo_root, READINESS_SCHEMA_RELATIVE_PATH),
        "release readiness schema",
    )
    errors = schema_errors(readiness, schema)
    if errors:
        raise ReleaseFinalizationError(
            "release readiness schema failed: " + "; ".join(errors)
        )
    if readiness.get("status") != expected_status:
        raise ReleaseFinalizationError(
            f"release readiness must transition from {expected_status!r}, "
            f"found {readiness.get('status')!r}"
        )
    if readiness.get("manifest_path") != MANIFEST_RELATIVE_PATH.as_posix():
        raise ReleaseFinalizationError("release readiness names the wrong canonical manifest")
    if "publication_receipt_path" in readiness:
        raise ReleaseFinalizationError(
            "pre-publication readiness must not contain publication_receipt_path"
        )
    if "browser_qa_bundle" in readiness:
        raise ReleaseFinalizationError(
            "pre-publication readiness must not contain browser_qa_bundle"
        )
    receipt_path = _repo_path(repo_root, RECEIPT_RELATIVE_PATH)
    if receipt_path.exists():
        raise ReleaseFinalizationError(
            "a publication receipt already exists; refusing to reuse or overwrite it"
        )
    browser_bundle = _repo_path(repo_root, BROWSER_QA_BUNDLE_RELATIVE_PATH)
    browser_staging = browser_bundle.with_name(
        f".{browser_bundle.name}.phase7.publishing"
    )
    if browser_bundle.exists() or browser_staging.exists():
        raise ReleaseFinalizationError(
            "a Phase 6 browser QA bundle or stale staging bundle already exists; "
            "refusing to reuse or overwrite it"
        )
    return readiness


def _read_index_pair(repo_root: Path) -> tuple[dict[str, Any], bytes]:
    canonical_path = _repo_path(repo_root, CANONICAL_INDEX_RELATIVE_PATH)
    compatibility_path = _repo_path(repo_root, COMPATIBILITY_INDEX_RELATIVE_PATH)
    if not canonical_path.is_file() or not compatibility_path.is_file():
        raise ReleaseFinalizationError(
            "published docs must contain both world-v3 runtime indexes"
        )
    canonical_bytes = canonical_path.read_bytes()
    if canonical_bytes != compatibility_path.read_bytes():
        raise ReleaseFinalizationError(
            "canonical and compatibility runtime indexes must be byte-identical"
        )
    index = _object(canonical_path, "canonical world-v3 runtime index")
    schema = _object(
        _repo_path(repo_root, INDEX_SCHEMA_RELATIVE_PATH), "sheet tile index schema"
    )
    errors = schema_errors(index, schema)
    if errors:
        raise ReleaseFinalizationError(
            "world-v3 runtime index schema failed: " + "; ".join(errors)
        )
    return index, canonical_bytes


def _index_entries(
    index: dict[str, Any],
    bounded: dict[str, dict[str, Any]],
    *,
    expected_status: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    root = index.get("root")
    descendants = index.get("sheets")
    if not isinstance(root, dict) or not isinstance(descendants, list):
        raise ReleaseFinalizationError("world-v3 index lacks root/sheets collections")
    entries = [root, *descendants]
    by_sheet: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("sheet_id"), str):
            raise ReleaseFinalizationError("world-v3 index contains an invalid sheet entry")
        sheet_id = entry["sheet_id"]
        if sheet_id in by_sheet:
            raise ReleaseFinalizationError(
                f"world-v3 index duplicates sheet_id {sheet_id!r}"
            )
        by_sheet[sheet_id] = entry
    if (
        index.get("release_id") != RELEASE_ID
        or index.get("bounded_sheet_count") != BOUNDED_SHEET_COUNT
        or len(entries) != BOUNDED_SHEET_COUNT
        or set(by_sheet) != set(bounded)
    ):
        raise ReleaseFinalizationError(
            "world-v3 index must contain exactly the canonical 23 bounded sheets"
        )
    wrong = sorted(
        sheet_id
        for sheet_id, entry in by_sheet.items()
        if entry.get("status") != expected_status
    )
    if wrong:
        raise ReleaseFinalizationError(
            f"world-v3 index entries must all be {expected_status!r}: "
            + ", ".join(wrong)
        )
    if any(entry.get("review_status") != "accepted" for entry in entries):
        raise ReleaseFinalizationError(
            "world-v3 index contains a sheet without accepted review_status"
        )
    return entries, by_sheet


def _metadata_path(repo_root: Path, manifest_url: Any) -> Path:
    if (
        not isinstance(manifest_url, str)
        or not manifest_url
        or "\\" in manifest_url
        or "?" in manifest_url
        or "#" in manifest_url
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", manifest_url)
        or manifest_url.startswith("/")
    ):
        raise ReleaseFinalizationError(f"invalid world-v3 manifest URL: {manifest_url!r}")
    joined = posixpath.normpath(
        posixpath.join(CANONICAL_INDEX_RELATIVE_PATH.parent.as_posix(), manifest_url)
    )
    portable = PurePosixPath(joined)
    if (
        portable.is_absolute()
        or any(part in {"", ".", ".."} for part in portable.parts)
        or portable.suffix != ".json"
    ):
        raise ReleaseFinalizationError(
            f"world-v3 manifest URL escapes the public root: {manifest_url!r}"
        )
    expected_prefix = PUBLIC_RELEASE_RELATIVE_PATH.parts
    if portable.parts[: len(expected_prefix)] != expected_prefix:
        raise ReleaseFinalizationError(
            f"world-v3 manifest URL resolves outside {PUBLIC_RELEASE_RELATIVE_PATH}"
        )
    return _inside_repo(_repo_path(repo_root, portable), repo_root, "tile metadata")


def _verify_entry_metadata(
    repo_root: Path,
    entries: Sequence[dict[str, Any]],
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for entry in entries:
        sheet_id = entry["sheet_id"]
        path = _metadata_path(repo_root, entry.get("manifest_url"))
        if not path.is_file():
            raise ReleaseFinalizationError(
                f"published tile metadata is missing for {sheet_id}: {path}"
            )
        actual_sha = _sha256_file(path)
        if entry.get("manifest_sha256") != actual_sha:
            raise ReleaseFinalizationError(
                f"published tile metadata SHA-256 mismatch for {sheet_id}"
            )
        metadata = _object(path, f"{sheet_id} published tile metadata")
        if metadata.get("release_id") != RELEASE_ID or metadata.get("map_id") != sheet_id:
            raise ReleaseFinalizationError(
                f"published tile metadata identity mismatch for {sheet_id}"
            )
        if metadata.get("tile_set_sha256") != entry.get("tile_set_sha256"):
            raise ReleaseFinalizationError(
                f"published tile-set SHA-256 mismatch for {sheet_id}"
            )
        master = metadata.get("master")
        if not isinstance(master, dict) or master.get("sha256") != entry.get(
            "master_sha256"
        ):
            raise ReleaseFinalizationError(
                f"published master SHA-256 mismatch for {sheet_id}"
            )
        paths[sheet_id] = path
    return paths


def _job_map(
    manifest: dict[str, Any],
    bounded: dict[str, dict[str, Any]],
    *,
    expected_status: str,
) -> dict[str, dict[str, Any]]:
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list):
        raise ReleaseFinalizationError("production manifest must contain a jobs array")
    by_sheet: dict[str, dict[str, Any]] = {}
    for job in jobs:
        if not isinstance(job, dict):
            raise ReleaseFinalizationError("production manifest contains a non-object job")
        sheet_id = job.get("sheet_id")
        if sheet_id not in bounded:
            continue
        if sheet_id in by_sheet:
            raise ReleaseFinalizationError(
                f"production manifest duplicates bounded sheet {sheet_id!r}"
            )
        by_sheet[sheet_id] = job
    if len(by_sheet) != BOUNDED_SHEET_COUNT or set(by_sheet) != set(bounded):
        raise ReleaseFinalizationError(
            "production manifest must contain exactly one job for each of the 23 bounded sheets"
        )
    wrong = sorted(
        sheet_id
        for sheet_id, job in by_sheet.items()
        if job.get("status") != expected_status
    )
    if wrong:
        raise ReleaseFinalizationError(
            f"bounded manifest jobs must all be {expected_status!r}: "
            + ", ".join(wrong)
        )
    return by_sheet


def _historical_manifest_matches(
    canonical: dict[str, Any],
    source: dict[str, Any],
    bounded: dict[str, dict[str, Any]],
) -> None:
    for key in set(canonical) | set(source):
        if key in {"jobs", "updated_at"}:
            continue
        if canonical.get(key) != source.get(key):
            raise ReleaseFinalizationError(
                f"build manifest changed canonical top-level field {key!r}"
            )
    canonical_jobs = canonical.get("jobs")
    source_jobs = source.get("jobs")
    if not isinstance(canonical_jobs, list) or not isinstance(source_jobs, list):
        raise ReleaseFinalizationError("production manifests must contain jobs arrays")
    source_history = [
        job
        for job in source_jobs
        if isinstance(job, dict) and job.get("sheet_id") not in bounded
    ]
    if canonical_jobs != source_history:
        raise ReleaseFinalizationError(
            "build manifest does not preserve the canonical pre-build job history exactly"
        )


def _job_projection_errors(
    job: dict[str, Any],
    entry: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    sheet_id = entry["sheet_id"]
    master = job.get("master")
    if not isinstance(master, dict) or master.get("sha256") != entry.get("master_sha256"):
        errors.append(f"{sheet_id} job/index master SHA-256 mismatch")
    output = job.get("output")
    if not isinstance(output, dict) or output.get("tile_set_sha256") != entry.get(
        "tile_set_sha256"
    ):
        errors.append(f"{sheet_id} job/index tile-set SHA-256 mismatch")
    bounds = job.get("bounds")
    projected_bounds = (
        [bounds.get("west"), bounds.get("south"), bounds.get("east"), bounds.get("north")]
        if isinstance(bounds, dict)
        else None
    )
    if projected_bounds != entry.get("bounds"):
        errors.append(f"{sheet_id} job/index bounds mismatch")
    zoom = job.get("zoom")
    projected_zoom = (
        [zoom.get("min"), zoom.get("max")]
        if isinstance(zoom, dict)
        else None
    )
    if projected_zoom != entry.get("zoom_range") or (
        not isinstance(zoom, dict) or zoom.get("native") != entry.get("native_zoom")
    ):
        errors.append(f"{sheet_id} job/index zoom mismatch")
    return errors


def _append_state(job: dict[str, Any], state: str, at: str) -> None:
    history = job.get("history")
    if not isinstance(history, list) or not history:
        raise ReleaseFinalizationError(
            f"bounded job {job.get('id')!r} lacks non-empty state history"
        )
    final = history[-1]
    if not isinstance(final, dict) or final.get("state") != job.get("status"):
        raise ReleaseFinalizationError(
            f"bounded job {job.get('id')!r} history does not project its status"
        )
    last_at = final.get("at")
    if not isinstance(last_at, str):
        raise ReleaseFinalizationError(
            f"bounded job {job.get('id')!r} final history timestamp is invalid"
        )
    try:
        if parse_rfc3339(at) < parse_rfc3339(last_at):
            raise ReleaseFinalizationError(
                f"transition timestamp precedes {job.get('id')!r} history"
            )
    except ValueError as exc:
        raise ReleaseFinalizationError(str(exc)) from exc
    job["status"] = state
    history.append(
        {
            "state": state,
            "at": at,
            "actor": FINALIZER_ID,
            "note": (
                "Bounded world-v3 release promoted only after strict manifest, "
                "public tile, index-alias, and runtime-boundary validation."
            ),
        }
    )


def _promote_manifest(
    manifest: dict[str, Any],
    bounded: dict[str, dict[str, Any]],
    entries_by_sheet: dict[str, dict[str, Any]],
    metadata_paths: dict[str, Path],
    *,
    repo_root: Path,
    expected_status: str,
    target_status: str,
    at: str,
) -> dict[str, Any]:
    previous_updated_at = manifest.get("updated_at")
    if isinstance(previous_updated_at, str):
        try:
            if parse_rfc3339(at) < parse_rfc3339(previous_updated_at):
                raise ReleaseFinalizationError(
                    "transition timestamp precedes production manifest updated_at"
                )
        except ValueError as exc:
            raise ReleaseFinalizationError(str(exc)) from exc
    jobs_by_sheet = _job_map(manifest, bounded, expected_status=expected_status)
    errors: list[str] = []
    for sheet_id, job in jobs_by_sheet.items():
        entry = entries_by_sheet[sheet_id]
        metadata_path = metadata_paths[sheet_id]
        errors.extend(_job_projection_errors(job, entry))
        output = job.get("output")
        if isinstance(output, dict):
            output["tiles_path"] = metadata_path.parent.relative_to(
                repo_root.resolve()
            ).as_posix()
            output["metadata_path"] = metadata_path.relative_to(
                repo_root.resolve()
            ).as_posix()
            output["tile_set_sha256"] = entry["tile_set_sha256"]
        _append_state(job, target_status, at)
    if errors:
        raise ReleaseFinalizationError("; ".join(errors))
    manifest["updated_at"] = at
    return manifest


def _promote_index(
    index: dict[str, Any], entries: Sequence[dict[str, Any]], target_status: str
) -> bytes:
    for entry in entries:
        entry["status"] = target_status
    return _json_bytes(index)


def _meta_values(html: str) -> tuple[dict[str, str], set[str]]:
    values: dict[str, str] = {}
    duplicates: set[str] = set()
    for tag in re.findall(r"<meta\b[^>]*>", html, flags=re.IGNORECASE):
        attrs = {
            key.casefold(): value
            for key, _quote, value in re.findall(
                r"([:\w-]+)\s*=\s*([\"'])(.*?)\2", tag, flags=re.DOTALL
            )
        }
        name = attrs.get("name")
        if not name or not name.startswith("ea-map-") or "content" not in attrs:
            continue
        if name in values:
            duplicates.add(name)
        values[name] = attrs["content"]
    return values, duplicates


def _replace_meta(html: str, name: str, value: str) -> str:
    matches: list[tuple[int, int, str]] = []
    for match in re.finditer(r"<meta\b[^>]*>", html, flags=re.IGNORECASE):
        tag = match.group(0)
        name_match = re.search(
            r"\bname\s*=\s*([\"'])(.*?)\1", tag, flags=re.IGNORECASE | re.DOTALL
        )
        if name_match and name_match.group(2).casefold() == name.casefold():
            matches.append((match.start(), match.end(), tag))
    if len(matches) != 1:
        raise ReleaseFinalizationError(
            f"interactive map HTML must contain exactly one {name!r} meta tag"
        )
    start, end, tag = matches[0]
    content_matches = list(
        re.finditer(
            r"\bcontent\s*=\s*([\"'])(.*?)\1",
            tag,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    if len(content_matches) != 1:
        raise ReleaseFinalizationError(
            f"interactive map HTML {name!r} must contain exactly one content attribute"
        )
    content = content_matches[0]
    quote = content.group(1)
    escaped = value.replace("&", "&amp;").replace(quote, "&quot;" if quote == '"' else "&#39;")
    replacement = tag[: content.start(2)] + escaped + tag[content.end(2) :]
    return html[:start] + replacement + html[end:]


def _release_cache_key(status: str, index_bytes: bytes) -> str:
    digest = _sha256_bytes(index_bytes)[:16]
    if status == "release-candidate":
        return f"world-v3-rc-{digest}"
    if status == "published":
        return f"world-v3-{digest}"
    raise ReleaseFinalizationError(f"unsupported HTML cache-key state: {status!r}")


def _transition_html(
    repo_root: Path,
    *,
    target: str,
    index_bytes: bytes,
    current_index_bytes: bytes,
) -> bytes:
    path = _repo_path(repo_root, HTML_RELATIVE_PATH)
    if not path.is_file():
        raise ReleaseFinalizationError("interactive-map-v3.html is missing")
    html = path.read_text(encoding="utf-8")
    values, duplicates = _meta_values(html)
    if duplicates:
        raise ReleaseFinalizationError(
            "interactive map HTML has duplicate release metadata: "
            + ", ".join(sorted(duplicates))
        )
    if values.get("ea-map-world-release") != "world-v1":
        raise ReleaseFinalizationError(
            f"world-v3 {target} transition requires the rollback-safe world-v1 active release"
        )
    for name, expected in HTML_REQUIRED_META.items():
        if values.get(name) != expected:
            raise ReleaseFinalizationError(
                f"interactive map HTML {name} must remain {expected!r} before activation"
            )
    current_cache_key = values.get("ea-map-cache-key")
    if not current_cache_key:
        raise ReleaseFinalizationError("interactive map HTML lacks a non-empty cache key")
    if target == "published":
        expected_candidate_key = _release_cache_key(
            "release-candidate", current_index_bytes
        )
        if current_cache_key != expected_candidate_key:
            raise ReleaseFinalizationError(
                "published transition requires the exact release-candidate HTML cache key"
            )
        html = _replace_meta(html, "ea-map-world-release", RELEASE_ID)
    elif target != "release-candidate":
        raise ReleaseFinalizationError(f"unsupported HTML transition target: {target!r}")
    cache_key = _release_cache_key(target, index_bytes)
    html = _replace_meta(html, "ea-map-cache-key", cache_key)
    after, duplicates = _meta_values(html)
    expected_active_release = RELEASE_ID if target == "published" else "world-v1"
    if (
        duplicates
        or after.get("ea-map-world-release") != expected_active_release
        or after.get("ea-map-cache-key") != cache_key
    ):
        raise ReleaseFinalizationError(
            f"world-v3 {target} HTML transition did not round-trip"
        )
    for name, expected in HTML_REQUIRED_META.items():
        if after.get(name) != expected:
            raise ReleaseFinalizationError(
                f"world-v3 {target} transition changed rollback metadata {name}"
            )
    return html.encode("utf-8")


def _readiness_bytes(
    status: str,
    *,
    repo_root: Path,
    browser_qa_bundle: dict[str, str] | None = None,
) -> bytes:
    value: dict[str, Any] = {
        "$schema": "schemas/release-readiness.schema.json",
        "schema_version": "1.0.0",
        "status": status,
        "manifest_path": MANIFEST_RELATIVE_PATH.as_posix(),
        "notes": (
            "world-v3 passed strict 23-sheet release validation and is staged for "
            "activation."
            if status == "release-candidate"
            else "world-v3 is activated; the hash-locked publication receipt must be written last."
        ),
    }
    if status == "published":
        if browser_qa_bundle is None:
            raise ReleaseFinalizationError(
                "published readiness requires canonical Phase 6 browser QA evidence"
            )
        value["publication_receipt_path"] = RECEIPT_RELATIVE_PATH.as_posix()
        value["browser_qa_bundle"] = dict(browser_qa_bundle)
    elif browser_qa_bundle is not None:
        raise ReleaseFinalizationError(
            "pre-publication readiness cannot record a browser QA bundle"
        )
    schema = _object(
        _repo_path(repo_root, READINESS_SCHEMA_RELATIVE_PATH),
        "release readiness schema",
    )
    errors = schema_errors(value, schema)
    if errors:
        raise ReleaseFinalizationError(
            "generated release readiness schema failed: " + "; ".join(errors)
        )
    return _json_bytes(value)


def _validate_candidate_manifest(
    manifest_bytes: bytes,
    *,
    repo_root: Path,
    minimum_state: str,
) -> dict[str, Any]:
    manifest_path = _repo_path(repo_root, MANIFEST_RELATIVE_PATH)
    temporary = manifest_path.with_name(
        f".{manifest_path.name}.{minimum_state}.phase7-validating"
    )
    if temporary.exists():
        raise ReleaseFinalizationError(
            f"stale Phase 7 validation artifact exists: {temporary}"
        )
    try:
        temporary.write_bytes(manifest_bytes)
        result = release_validator.validate_release(
            temporary,
            manifest_schema_path=_repo_path(repo_root, MANIFEST_SCHEMA_RELATIVE_PATH),
            qa_schema_path=_repo_path(repo_root, QA_SCHEMA_RELATIVE_PATH),
            qa_dir=_repo_path(repo_root, QA_DIR_RELATIVE_PATH),
            map_sheets_path=_repo_path(repo_root, CATALOG_RELATIVE_PATH),
            resolution_contract_path=_repo_path(
                repo_root, RESOLUTION_CONTRACT_RELATIVE_PATH
            ),
            repo_root=repo_root,
            strict_release=True,
            sheet_minimum_state=minimum_state,
        )
    except (OSError, ValidationFailure) as exc:
        raise ReleaseFinalizationError(
            f"strict {minimum_state} manifest validation failed: {exc}"
        ) from exc
    finally:
        if temporary.exists():
            temporary.unlink()
    if not isinstance(result, dict):
        raise ReleaseFinalizationError("strict release validator returned a non-object")
    errors = result.get("errors")
    if not isinstance(errors, list):
        raise ReleaseFinalizationError("strict release validator omitted its errors array")
    if result.get("valid") is not True or errors:
        details = "; ".join(str(error) for error in errors) or "validator returned invalid"
        raise ReleaseFinalizationError(
            f"strict {minimum_state} manifest validation failed: {details}"
        )
    if (
        result.get("required_sheets") != BOUNDED_SHEET_COUNT
        or result.get("covered_sheets") != BOUNDED_SHEET_COUNT
    ):
        raise ReleaseFinalizationError(
            f"strict {minimum_state} validation must cover exactly 23 bounded sheets"
        )
    return result


def _validate_public_release(repo_root: Path) -> dict[str, Any]:
    try:
        result = phase5.validate_public_tile_release(
            repo_root / "docs", release_id=RELEASE_ID, verify_tiles=True
        )
    except (OSError, ValueError, ValidationFailure, phase5.Phase5BuildError) as exc:
        raise ReleaseFinalizationError(
            f"published world-v3 tile validation failed: {exc}"
        ) from exc
    if not isinstance(result, dict):
        raise ReleaseFinalizationError("public tile validator returned a non-object")
    errors = result.get("errors")
    if not isinstance(errors, list):
        raise ReleaseFinalizationError("public tile validator omitted its errors array")
    if result.get("valid") is not True or errors:
        details = "; ".join(str(error) for error in errors) or "validator returned invalid"
        raise ReleaseFinalizationError(
            f"published world-v3 tile validation failed: {details}"
        )
    if result.get("release_id") != RELEASE_ID or result.get(
        "bounded_sheet_count"
    ) != BOUNDED_SHEET_COUNT:
        raise ReleaseFinalizationError(
            "published tile release must be world-v3 with exactly 23 bounded sheets"
        )
    return result


def _validate_build(build_root: Path, repo_root: Path) -> dict[str, Any]:
    build_root = _inside_repo(build_root, repo_root, "Phase 5 build root")
    try:
        result = phase5.validate_build_root(build_root)
    except (OSError, ValueError, ValidationFailure, phase5.Phase5BuildError) as exc:
        raise ReleaseFinalizationError(f"Phase 5 build validation failed: {exc}") from exc
    if not isinstance(result, dict) or result.get("valid") is not True:
        errors = result.get("errors", []) if isinstance(result, dict) else []
        raise ReleaseFinalizationError(
            "Phase 5 build validation failed: "
            + ("; ".join(str(error) for error in errors) or "validator returned invalid")
        )
    public = result.get("public_tile_release")
    if (
        not isinstance(public, dict)
        or public.get("valid") is not True
        or public.get("release_id") != RELEASE_ID
        or public.get("bounded_sheet_count") != BOUNDED_SHEET_COUNT
    ):
        raise ReleaseFinalizationError(
            "Phase 5 build lacks a valid all-23 world-v3 public tile release"
        )
    return result


def _validate_browser_qa_receipt(
    receipt_path: Path | None, repo_root: Path
) -> tuple[dict[str, Any], Path, str]:
    """Require current-byte-bound real-browser evidence before publication."""

    if receipt_path is None:
        raise ReleaseFinalizationError(
            "published transition requires a Phase 6 browser QA PASS receipt"
        )
    path = receipt_path.resolve()
    if not path.is_file():
        raise ReleaseFinalizationError(
            f"Phase 6 browser QA receipt does not exist as a file: {path}"
        )
    receipt_bytes = path.read_bytes()
    try:
        receipt, errors = browser_qa_validator.validate_browser_qa_receipt_file(
            path,
            repo_root=repo_root,
            require_pass=True,
        )
    except (OSError, ValidationFailure) as exc:
        raise ReleaseFinalizationError(
            f"Phase 6 browser QA receipt validation failed: {exc}"
        ) from exc
    if errors:
        raise ReleaseFinalizationError(
            "Phase 6 browser QA receipt validation failed: " + "; ".join(errors)
        )
    if path.read_bytes() != receipt_bytes:
        raise ReleaseFinalizationError(
            "Phase 6 browser QA receipt changed while it was being validated"
        )
    if (
        not isinstance(receipt, dict)
        or receipt.get("release_id") != RELEASE_ID
        or receipt.get("result") != "pass"
        or not isinstance(receipt.get("scenarios"), list)
        or len(receipt["scenarios"]) != 4
    ):
        raise ReleaseFinalizationError(
            "Phase 6 browser QA receipt must be a four-scenario world-v3 PASS"
        )
    return receipt, path, _sha256_bytes(receipt_bytes)


def _browser_qa_evidence_paths(receipt: dict[str, Any]) -> list[PurePosixPath]:
    """Collect the receipt-declared evidence closure copied into publication."""

    paths: set[PurePosixPath] = set()
    scenarios = receipt.get("scenarios")
    if not isinstance(scenarios, list):
        raise ReleaseFinalizationError("Phase 6 browser QA receipt lacks scenarios")
    for scenario in scenarios:
        evidence = scenario.get("evidence") if isinstance(scenario, dict) else None
        if not isinstance(evidence, dict):
            raise ReleaseFinalizationError(
                "Phase 6 browser QA scenario lacks an evidence object"
            )
        for owner in evidence.values():
            raw_path = owner.get("path") if isinstance(owner, dict) else None
            if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
                raise ReleaseFinalizationError(
                    "Phase 6 browser QA evidence path must be relative POSIX text"
                )
            portable = PurePosixPath(raw_path)
            if portable.is_absolute() or any(
                part in {"", ".", ".."} for part in portable.parts
            ):
                raise ReleaseFinalizationError(
                    f"Phase 6 browser QA evidence path escapes its bundle: {raw_path!r}"
                )
            paths.add(portable)
    return sorted(paths)


def _stage_browser_qa_bundle(
    receipt: dict[str, Any],
    source_receipt: Path,
    expected_receipt_sha256: str,
    *,
    repo_root: Path,
    publication_at: str,
) -> tuple[Path, Path, dict[str, str], bool]:
    """Copy and revalidate the declared QA closure in a repository-local stage."""

    source_candidate = source_receipt.absolute()
    if source_candidate.is_symlink() or source_candidate.parent.is_symlink():
        raise ReleaseFinalizationError(
            "Phase 6 browser QA receipt and bundle root must not be symlinks"
        )
    source_receipt = source_candidate.resolve()
    if source_receipt.name != BROWSER_QA_RECEIPT_NAME:
        raise ReleaseFinalizationError(
            f"Phase 6 browser QA receipt must be named {BROWSER_QA_RECEIPT_NAME!r}"
        )
    source_root = source_receipt.parent
    if _sha256_file(source_receipt) != expected_receipt_sha256:
        raise ReleaseFinalizationError(
            "Phase 6 browser QA receipt changed before bundle staging"
        )

    tested_url = receipt.get("tested_url")
    completed_at = receipt.get("completed_at")
    if not isinstance(tested_url, str) or not tested_url:
        raise ReleaseFinalizationError("Phase 6 browser QA receipt lacks tested_url")
    if not isinstance(completed_at, str) or not completed_at:
        raise ReleaseFinalizationError("Phase 6 browser QA receipt lacks completed_at")
    try:
        if parse_rfc3339(publication_at) < parse_rfc3339(completed_at):
            raise ReleaseFinalizationError(
                "publication timestamp precedes Phase 6 browser QA completion"
            )
    except ValueError as exc:
        raise ReleaseFinalizationError(str(exc)) from exc

    target = _inside_repo(
        _repo_path(repo_root, BROWSER_QA_BUNDLE_RELATIVE_PATH),
        repo_root,
        "canonical Phase 6 browser QA bundle",
    )
    stage = target.with_name(f".{target.name}.phase7.publishing")
    if target.exists() or stage.exists():
        raise ReleaseFinalizationError(
            "canonical Phase 6 browser QA bundle already exists or has stale staging"
        )
    parent_created = not target.parent.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    stage.mkdir()
    try:
        relative_files = [PurePosixPath(BROWSER_QA_RECEIPT_NAME)]
        relative_files.extend(_browser_qa_evidence_paths(receipt))
        if len(relative_files) != len(set(relative_files)):
            raise ReleaseFinalizationError(
                "Phase 6 browser QA receipt duplicates its receipt/evidence path"
            )
        for relative in relative_files:
            source_candidate = source_root / Path(*relative.parts)
            if any(
                candidate.is_symlink()
                for candidate in (
                    source_candidate,
                    *source_candidate.parents[: len(relative.parts) - 1],
                )
            ):
                raise ReleaseFinalizationError(
                    f"Phase 6 browser QA evidence path traverses a symlink: {relative}"
                )
            source = source_candidate.resolve()
            try:
                source.relative_to(source_root.resolve())
            except ValueError as exc:
                raise ReleaseFinalizationError(
                    f"Phase 6 browser QA evidence escapes its source bundle: {relative}"
                ) from exc
            if not source.is_file():
                raise ReleaseFinalizationError(
                    f"Phase 6 browser QA evidence is missing or is a symlink: {relative}"
                )
            destination = stage / Path(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            if destination.read_bytes() != source.read_bytes():
                raise ReleaseFinalizationError(
                    f"Phase 6 browser QA evidence changed while copying: {relative}"
                )

        staged_receipt = stage / BROWSER_QA_RECEIPT_NAME
        copied_receipt, copied_path, copied_sha256 = _validate_browser_qa_receipt(
            staged_receipt, repo_root
        )
        if (
            copied_path != staged_receipt.resolve()
            or copied_sha256 != expected_receipt_sha256
            or copied_receipt != receipt
        ):
            raise ReleaseFinalizationError(
                "copied Phase 6 browser QA receipt does not match the validated source"
            )
        file_count, tree_sha256 = _directory_tree_evidence(stage)
        if file_count != len(relative_files):
            raise ReleaseFinalizationError(
                "copied Phase 6 browser QA bundle contains undeclared files"
            )
        owner = {
            "path": BROWSER_QA_BUNDLE_RELATIVE_PATH.as_posix(),
            "receipt_sha256": copied_sha256,
            "tree_sha256": tree_sha256,
            "tested_url": tested_url,
            "completed_at": completed_at,
        }
        return stage, target, owner, parent_created
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        if parent_created and target.parent.is_dir() and not any(target.parent.iterdir()):
            target.parent.rmdir()
        raise


def _assert_browser_bundle_owner(
    root: Path,
    owner: dict[str, str],
    *,
    label: str,
) -> int:
    file_count, tree_sha = _directory_tree_evidence(root)
    receipt_path = root / BROWSER_QA_RECEIPT_NAME
    if (
        file_count <= 0
        or tree_sha != owner.get("tree_sha256")
        or not receipt_path.is_file()
        or _sha256_file(receipt_path) != owner.get("receipt_sha256")
    ):
        raise ReleaseFinalizationError(
            f"Phase 6 browser QA bundle changed {label}"
        )
    return file_count


def _atomic_replace_files(
    replacements: Sequence[tuple[Path, bytes]],
    *,
    repo_root: Path,
    browser_bundle_stage: Path | None = None,
    browser_bundle_target: Path | None = None,
    browser_bundle_owner: dict[str, str] | None = None,
    browser_bundle_parent_created: bool = False,
) -> None:
    staged: list[tuple[Path, Path]] = []
    originals: dict[Path, bytes] = {}
    installed: list[Path] = []
    bundle_installed = False
    try:
        for target, content in replacements:
            target = _inside_repo(target, repo_root, "Phase 7 target")
            if not target.is_file():
                raise ReleaseFinalizationError(
                    f"Phase 7 target must already exist: {target}"
                )
            temporary = target.with_name(f".{target.name}.phase7.publishing")
            if temporary.exists():
                raise ReleaseFinalizationError(
                    f"stale Phase 7 publication artifact exists: {temporary}"
                )
            originals[target] = target.read_bytes()
            temporary.write_bytes(content)
            if temporary.read_bytes() != content:
                raise ReleaseFinalizationError(
                    f"staged Phase 7 bytes did not round-trip: {target}"
                )
            staged.append((target, temporary))
        if browser_bundle_stage is not None:
            if browser_bundle_target is None or browser_bundle_owner is None:
                raise ReleaseFinalizationError(
                    "Phase 6 browser QA bundle transaction is incomplete"
                )
            stage_count = _assert_browser_bundle_owner(
                browser_bundle_stage,
                browser_bundle_owner,
                label="before canonical installation",
            )
            if browser_bundle_target.exists():
                raise ReleaseFinalizationError(
                    "canonical Phase 6 browser QA bundle appeared during publication"
                )
            os.replace(browser_bundle_stage, browser_bundle_target)
            bundle_installed = True
            target_count = _assert_browser_bundle_owner(
                browser_bundle_target,
                browser_bundle_owner,
                label="during canonical installation",
            )
            if target_count != stage_count:
                raise ReleaseFinalizationError(
                    "installed Phase 6 browser QA bundle failed byte verification"
                )
        for target, temporary in staged:
            if (
                bundle_installed
                and browser_bundle_target is not None
                and browser_bundle_owner is not None
                and target == _repo_path(repo_root, READINESS_RELATIVE_PATH).resolve()
            ):
                _assert_browser_bundle_owner(
                    browser_bundle_target,
                    browser_bundle_owner,
                    label="before the readiness commit",
                )
            os.replace(temporary, target)
            installed.append(target)
        if (
            bundle_installed
            and browser_bundle_target is not None
            and browser_bundle_owner is not None
        ):
            _assert_browser_bundle_owner(
                browser_bundle_target,
                browser_bundle_owner,
                label="after the readiness commit",
            )
    except Exception:
        for target in reversed(installed):
            rollback = target.with_name(f".{target.name}.phase7.rollback")
            rollback.write_bytes(originals[target])
            os.replace(rollback, target)
        if bundle_installed and browser_bundle_target is not None:
            shutil.rmtree(browser_bundle_target)
        if (
            browser_bundle_parent_created
            and browser_bundle_target is not None
            and browser_bundle_target.parent.is_dir()
            and not any(browser_bundle_target.parent.iterdir())
        ):
            browser_bundle_target.parent.rmdir()
        raise
    finally:
        for _target, temporary in staged:
            if temporary.exists():
                temporary.unlink()
        if browser_bundle_stage is not None and browser_bundle_stage.exists():
            shutil.rmtree(browser_bundle_stage)
        if (
            browser_bundle_parent_created
            and browser_bundle_target is not None
            and not browser_bundle_target.exists()
            and browser_bundle_target.parent.is_dir()
            and not any(browser_bundle_target.parent.iterdir())
        ):
            browser_bundle_target.parent.rmdir()


def finalize_release(
    target: str,
    *,
    repo_root: Path = REPO_ROOT,
    build_root: Path | None = None,
    browser_qa_receipt: Path | None = None,
    at: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute one fail-closed Phase 7 transition."""

    repo_root = repo_root.resolve()
    timestamp = _validated_timestamp(at)
    if target not in {"release-candidate", "published"}:
        raise ReleaseFinalizationError(f"unsupported Phase 7 target: {target!r}")
    expected_readiness = "in-progress" if target == "release-candidate" else "release-candidate"
    expected_job_status = "tiled" if target == "release-candidate" else "staging"
    target_job_status = "staging" if target == "release-candidate" else "published"
    _load_readiness(repo_root, expected_readiness)
    bounded, _counts = _bounded_catalog(repo_root)
    public_validation = _validate_public_release(repo_root)
    index, current_index_bytes = _read_index_pair(repo_root)
    entries, entries_by_sheet = _index_entries(
        index, bounded, expected_status=expected_job_status
    )
    metadata_paths = _verify_entry_metadata(repo_root, entries)

    canonical_manifest_path = _repo_path(repo_root, MANIFEST_RELATIVE_PATH)
    canonical_manifest = _object(canonical_manifest_path, "canonical production manifest")
    if target == "release-candidate":
        if browser_qa_receipt is not None:
            raise ReleaseFinalizationError(
                "release-candidate transition does not consume browser QA evidence"
            )
        if build_root is None:
            raise ReleaseFinalizationError(
                "release-candidate transition requires a Phase 5 build root"
            )
        build_root = _inside_repo(build_root, repo_root, "Phase 5 build root")
        _validate_build(build_root, repo_root)
        source_manifest = _object(
            build_root / "production-manifest.phase5.json", "Phase 5 build manifest"
        )
        _historical_manifest_matches(canonical_manifest, source_manifest, bounded)
        manifest = source_manifest
    else:
        if build_root is not None:
            raise ReleaseFinalizationError(
                "published transition uses the canonical release-candidate manifest; "
                "do not pass a build root"
            )
        browser_qa, browser_qa_path, browser_qa_sha256 = _validate_browser_qa_receipt(
            browser_qa_receipt, repo_root
        )
        manifest = canonical_manifest

    manifest = _promote_manifest(
        manifest,
        bounded,
        entries_by_sheet,
        metadata_paths,
        repo_root=repo_root,
        expected_status=expected_job_status,
        target_status=target_job_status,
        at=timestamp,
    )
    index_bytes = _promote_index(index, entries, target_job_status)
    manifest_bytes = _json_bytes(manifest)
    strict_validation = _validate_candidate_manifest(
        manifest_bytes, repo_root=repo_root, minimum_state=target_job_status
    )

    canonical_index_path = _repo_path(repo_root, CANONICAL_INDEX_RELATIVE_PATH)
    compatibility_index_path = _repo_path(
        repo_root, COMPATIBILITY_INDEX_RELATIVE_PATH
    )
    transitioned_html_bytes = _transition_html(
        repo_root,
        target=target,
        index_bytes=index_bytes,
        current_index_bytes=current_index_bytes,
    )
    browser_bundle_stage: Path | None = None
    browser_bundle_target: Path | None = None
    browser_bundle_owner: dict[str, str] | None = None
    browser_bundle_parent_created = False
    if target == "published":
        (
            browser_bundle_stage,
            browser_bundle_target,
            browser_bundle_owner,
            browser_bundle_parent_created,
        ) = _stage_browser_qa_bundle(
            browser_qa,
            browser_qa_path,
            browser_qa_sha256,
            repo_root=repo_root,
            publication_at=timestamp,
        )
    try:
        replacements: list[tuple[Path, bytes]] = [
            (canonical_index_path, index_bytes),
            (compatibility_index_path, index_bytes),
            (canonical_manifest_path, manifest_bytes),
            (_repo_path(repo_root, HTML_RELATIVE_PATH), transitioned_html_bytes),
        ]
        # Readiness is the transaction commit pointer and is always installed last.
        replacements.append(
            (
                _repo_path(repo_root, READINESS_RELATIVE_PATH),
                _readiness_bytes(
                    target,
                    repo_root=repo_root,
                    browser_qa_bundle=browser_bundle_owner,
                ),
            )
        )
        if not dry_run:
            _atomic_replace_files(
                replacements,
                repo_root=repo_root,
                browser_bundle_stage=browser_bundle_stage,
                browser_bundle_target=browser_bundle_target,
                browser_bundle_owner=browser_bundle_owner,
                browser_bundle_parent_created=browser_bundle_parent_created,
            )
    finally:
        if browser_bundle_stage is not None and browser_bundle_stage.exists():
            shutil.rmtree(browser_bundle_stage)
        if (
            browser_bundle_parent_created
            and browser_bundle_target is not None
            and not browser_bundle_target.exists()
            and browser_bundle_target.parent.is_dir()
            and not any(browser_bundle_target.parent.iterdir())
        ):
            browser_bundle_target.parent.rmdir()

    return {
        "valid": True,
        "dry_run": dry_run,
        "target": target,
        "release_id": RELEASE_ID,
        "bounded_sheet_count": BOUNDED_SHEET_COUNT,
        "manifest_job_state": target_job_status,
        "strict_manifest_coverage": strict_validation["covered_sheets"],
        "tile_count": public_validation.get("tile_count"),
        "tile_bytes": public_validation.get("tile_bytes"),
        "receipt_created": False,
        "receipt_required": target == "published",
        "receipt_path": (
            RECEIPT_RELATIVE_PATH.as_posix() if target == "published" else None
        ),
        "browser_qa_receipt": (
            str(browser_qa_path) if target == "published" else None
        ),
        "browser_qa_receipt_sha256": (
            browser_qa_sha256 if target == "published" else None
        ),
        "browser_qa_bundle": (
            browser_bundle_owner if target == "published" else None
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--at", help="RFC 3339 transition timestamp (defaults to now)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    subparsers = parser.add_subparsers(dest="target", required=True)
    candidate = subparsers.add_parser(
        "release-candidate", help="install the all-23 staged release candidate"
    )
    candidate.add_argument("build_root", type=Path)
    published = subparsers.add_parser(
        "published", help="activate world-v3 and require the final receipt writer"
    )
    published.add_argument(
        "browser_qa_receipt",
        type=Path,
        help="PASS receipt emitted by run_phase6_browser_qa.py",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = finalize_release(
            args.target,
            repo_root=args.repo_root,
            build_root=getattr(args, "build_root", None),
            browser_qa_receipt=getattr(args, "browser_qa_receipt", None),
            at=args.at,
            dry_run=args.dry_run,
        )
    except (
        OSError,
        ValueError,
        ValidationFailure,
        ReleaseFinalizationError,
        phase5.Phase5BuildError,
    ) as exc:
        result = {"valid": False, "error": str(exc)}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["valid"]:
        action = "validated" if result["dry_run"] else "installed"
        print(
            f"Phase 7 {result['target']} {action}: {result['release_id']} "
            f"({result['bounded_sheet_count']} bounded sheets)"
        )
        if result["receipt_required"]:
            print(
                "Publication receipt was not created; run "
                "write_publication_receipt.py as the final step."
            )
    else:
        print(f"Phase 7 release finalization failed: {result['error']}", file=sys.stderr)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
