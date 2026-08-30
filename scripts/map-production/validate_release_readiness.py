#!/usr/bin/env python3
"""Run the map release validator according to an explicit readiness declaration.

Normal production validation must remain usable while map sheets are still being
created.  This gate validates those in-progress artifacts without pretending they
are publishable, then switches to the existing strict release validator as soon as
the declaration enters a release state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any

import build_phase5_assets as phase5
import validate_release as release_validator
from production_common import REPO_ROOT, ValidationFailure, load_json, parse_rfc3339
from validate_manifest import schema_errors


DEFAULT_READINESS = REPO_ROOT / "world" / "map-production" / "release-readiness.json"
DEFAULT_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "release-readiness.schema.json"
)
STRICT_STATUSES = frozenset({"release-candidate", "published"})
PUBLICATION_JOB_STATES = frozenset({"staging", "published"})
PUBLIC_RELEASE_ID = "world-v3"
PUBLICATION_RECEIPT_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "publication-receipt.schema.json"
)
CANONICAL_INDEX_PATH = PurePosixPath("docs/data/map/sheet-tiles-v3.json")
COMPATIBILITY_INDEX_PATH = PurePosixPath("docs/data/map/region-rasters.json")
PUBLIC_RELEASE_TREE = PurePosixPath("docs/assets/images/maps/tiles/world-v3")
INTERACTIVE_MAP_HTML = PurePosixPath("docs/pages/interactive-map-v3.html")
BROWSER_QA_BUNDLE_PATH = PurePosixPath(
    "world/map-production/releases/world-v3-phase6-browser-qa"
)
BROWSER_QA_RECEIPT_NAME = "phase6-browser-qa-receipt.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_tree_evidence(root: Path) -> tuple[int, str]:
    hashes = {
        path.relative_to(root).as_posix(): _sha256_file(path)
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file())
    }
    digest = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return len(hashes), digest


def _browser_bundle_tree_evidence(root: Path) -> tuple[int, str]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Phase 6 browser QA bundle must be a real directory")
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(
                "Phase 6 browser QA bundle must not contain symlinks: "
                + path.relative_to(root).as_posix()
            )
        if path.is_file():
            hashes[path.relative_to(root).as_posix()] = _sha256_file(path)
        elif not path.is_dir():
            raise ValueError(
                "Phase 6 browser QA bundle contains an unsupported entry: "
                + path.relative_to(root).as_posix()
            )
    digest = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return len(hashes), digest


def _validate_browser_qa_bundle(
    owner: Any,
    *,
    repo_root: Path,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Verify the durable canonical Phase 6 receipt and its evidence tree."""

    errors: list[str] = []
    if not isinstance(owner, dict):
        return None, ["published readiness/receipt browser QA owner must be an object"]
    if owner.get("path") != BROWSER_QA_BUNDLE_PATH.as_posix():
        errors.append(
            "browser QA bundle path must be "
            f"{BROWSER_QA_BUNDLE_PATH.as_posix()!r}"
        )
    root = repo_root.resolve()
    bundle_candidate = root.joinpath(*BROWSER_QA_BUNDLE_PATH.parts)
    if bundle_candidate.is_symlink():
        return None, [*errors, "canonical Phase 6 browser QA bundle is a symlink"]
    bundle = bundle_candidate.resolve()
    try:
        bundle.relative_to(root)
    except ValueError:
        return None, [*errors, "browser QA bundle escapes the repository"]
    if not bundle.is_dir() or bundle.is_symlink():
        return None, [
            *errors,
            "canonical Phase 6 browser QA bundle does not exist as a real directory: "
            + BROWSER_QA_BUNDLE_PATH.as_posix(),
        ]
    try:
        file_count, tree_sha = _browser_bundle_tree_evidence(bundle)
    except (OSError, ValueError) as exc:
        return None, [*errors, str(exc)]
    if file_count <= 0:
        errors.append("canonical Phase 6 browser QA bundle is empty")
    if owner.get("tree_sha256") != tree_sha:
        errors.append(
            "browser QA bundle tree_sha256 mismatch: "
            f"receipt={owner.get('tree_sha256')!r}, actual={tree_sha}"
        )

    receipt_path = bundle / BROWSER_QA_RECEIPT_NAME
    if not receipt_path.is_file() or receipt_path.is_symlink():
        return None, [
            *errors,
            f"canonical browser QA receipt is missing: {BROWSER_QA_RECEIPT_NAME}",
        ]
    receipt_sha = _sha256_file(receipt_path)
    if owner.get("receipt_sha256") != receipt_sha:
        errors.append(
            "browser QA receipt_sha256 mismatch: "
            f"receipt={owner.get('receipt_sha256')!r}, actual={receipt_sha}"
        )

    try:
        import validate_phase6_browser_qa as browser_qa_validator

        browser_receipt, browser_errors = (
            browser_qa_validator.validate_persisted_browser_qa_bundle(
                receipt_path,
                repo_root=repo_root,
            )
        )
    except (OSError, ValidationFailure) as exc:
        return None, [*errors, f"persisted Phase 6 browser QA validation failed: {exc}"]
    errors.extend(
        f"persisted Phase 6 browser QA: {error}" for error in browser_errors
    )
    if isinstance(browser_receipt, dict):
        for field in ("tested_url", "completed_at"):
            if owner.get(field) != browser_receipt.get(field):
                errors.append(
                    f"browser QA {field} mismatch: owner={owner.get(field)!r}, "
                    f"receipt={browser_receipt.get(field)!r}"
                )
    else:
        errors.append("persisted Phase 6 browser QA validator returned a non-object")
        browser_receipt = None
    return browser_receipt, errors


class _MapMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}
        self.duplicates: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "meta":
            return
        values = {key.casefold(): value for key, value in attrs if value is not None}
        name = values.get("name")
        content = values.get("content")
        if not name or content is None or not name.startswith("ea-map-"):
            return
        if name in self.values:
            self.duplicates.add(name)
        self.values[name] = content


def _receipt_artifact_errors(
    owner: Any,
    *,
    expected_path: PurePosixPath,
    label: str,
    repo_root: Path,
) -> tuple[Path | None, list[str]]:
    if not isinstance(owner, dict):
        return None, [f"publication receipt {label} must be an object"]
    raw_path = owner.get("path")
    if raw_path != expected_path.as_posix():
        return None, [
            f"publication receipt {label}.path must be {expected_path.as_posix()!r}"
        ]
    path, errors = _resolve_repo_path(raw_path, label=f"receipt.{label}.path", repo_root=repo_root)
    if path is not None and path.is_file():
        actual = _sha256_file(path)
        if owner.get("sha256") != actual:
            errors.append(
                f"publication receipt {label}.sha256 mismatch: "
                f"receipt={owner.get('sha256')!r}, actual={actual}"
            )
    return path, errors


def _validate_published_runtime(
    readiness: dict[str, Any],
    *,
    repo_root: Path,
    receipt_schema_path: Path = PUBLICATION_RECEIPT_SCHEMA,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Recompute the public world-v3 boundary and its last-written receipt."""

    errors: list[str] = []
    browser_owner = readiness.get("browser_qa_bundle")
    _browser_receipt, browser_errors = _validate_browser_qa_bundle(
        browser_owner,
        repo_root=repo_root,
    )
    errors.extend(browser_errors)
    raw_receipt_path = readiness.get("publication_receipt_path")
    if not isinstance(raw_receipt_path, str):
        return None, [*errors, "published readiness requires publication_receipt_path"]
    receipt_path, path_errors = _resolve_repo_path(
        raw_receipt_path,
        label="publication_receipt_path",
        repo_root=repo_root,
    )
    errors.extend(path_errors)
    if receipt_path is None or not receipt_path.is_file():
        return None, errors
    if receipt_path.name != "world-v3-publication-receipt.json":
        errors.append(
            "publication receipt filename must be world-v3-publication-receipt.json"
        )

    try:
        receipt = load_json(receipt_path)
    except ValidationFailure as exc:
        return None, [*errors, str(exc)]
    errors.extend(
        validate_publication_receipt(
            receipt,
            repo_root=repo_root,
            receipt_schema_path=receipt_schema_path,
        )
    )
    if isinstance(receipt, dict) and receipt.get("browser_qa") != browser_owner:
        errors.append(
            "publication receipt browser_qa must exactly match published readiness "
            "browser_qa_bundle"
        )
    return receipt if isinstance(receipt, dict) else None, errors


def validate_publication_receipt(
    receipt: Any,
    *,
    repo_root: Path,
    receipt_schema_path: Path = PUBLICATION_RECEIPT_SCHEMA,
) -> list[str]:
    """Recompute and validate one in-memory world-v3 publication receipt.

    Keeping this boundary independent from receipt-path loading lets the
    publication writer validate its candidate before the first durable write,
    while the normal readiness validator applies the exact same checks to the
    persisted receipt.
    """

    errors: list[str] = []
    if not isinstance(receipt, dict):
        return ["publication receipt must contain a JSON object"]
    try:
        receipt_schema = load_json(receipt_schema_path)
        errors.extend(
            f"publication receipt: {error}"
            for error in schema_errors(receipt, receipt_schema)
        )
    except ValidationFailure as exc:
        errors.append(str(exc))

    _browser_receipt, browser_errors = _validate_browser_qa_bundle(
        receipt.get("browser_qa"),
        repo_root=repo_root,
    )
    errors.extend(browser_errors)
    browser_owner = receipt.get("browser_qa")
    browser_completed_at = (
        browser_owner.get("completed_at") if isinstance(browser_owner, dict) else None
    )
    try:
        published_at = parse_rfc3339(receipt.get("published_at", ""))
        browser_completed = parse_rfc3339(browser_completed_at or "")
    except (TypeError, ValueError) as exc:
        errors.append(f"publication/browser QA timestamp is invalid: {exc}")
    else:
        if published_at < browser_completed:
            errors.append(
                "publication receipt published_at precedes Phase 6 browser QA completion"
            )

    canonical, canonical_errors = _receipt_artifact_errors(
        receipt.get("canonical_index"),
        expected_path=CANONICAL_INDEX_PATH,
        label="canonical_index",
        repo_root=repo_root,
    )
    compatibility, compatibility_errors = _receipt_artifact_errors(
        receipt.get("compatibility_index"),
        expected_path=COMPATIBILITY_INDEX_PATH,
        label="compatibility_index",
        repo_root=repo_root,
    )
    html_path, html_errors = _receipt_artifact_errors(
        receipt.get("html"),
        expected_path=INTERACTIVE_MAP_HTML,
        label="html",
        repo_root=repo_root,
    )
    errors.extend(canonical_errors)
    errors.extend(compatibility_errors)
    errors.extend(html_errors)
    if canonical is not None and compatibility is not None:
        if canonical.read_bytes() != compatibility.read_bytes():
            errors.append(
                "published sheet-tiles-v3.json and region-rasters.json must be byte-identical"
            )

    tree_owner = receipt.get("release_tree")
    release_tree = repo_root.joinpath(*PUBLIC_RELEASE_TREE.parts).resolve()
    try:
        release_tree.relative_to(repo_root.resolve())
    except ValueError:
        errors.append("published release tree escapes the repository")
    if not release_tree.is_dir():
        errors.append(f"published release tree does not exist: {PUBLIC_RELEASE_TREE}")
    elif isinstance(tree_owner, dict):
        if tree_owner.get("path") != PUBLIC_RELEASE_TREE.as_posix():
            errors.append(
                f"publication receipt release_tree.path must be {PUBLIC_RELEASE_TREE.as_posix()!r}"
            )
        file_count, tree_sha = _release_tree_evidence(release_tree)
        if tree_owner.get("file_count") != file_count:
            errors.append(
                "publication receipt release_tree.file_count mismatch: "
                f"receipt={tree_owner.get('file_count')!r}, actual={file_count}"
            )
        if tree_owner.get("sha256") != tree_sha:
            errors.append(
                "publication receipt release_tree.sha256 mismatch: "
                f"receipt={tree_owner.get('sha256')!r}, actual={tree_sha}"
            )
    else:
        errors.append("publication receipt release_tree must be an object")

    docs_root = repo_root / "docs"
    try:
        public_validation = phase5.validate_public_tile_release(
            docs_root,
            release_id=PUBLIC_RELEASE_ID,
            verify_tiles=True,
        )
    except (OSError, ValueError, ValidationFailure, phase5.Phase5BuildError) as exc:
        errors.append(f"published public release validation failed: {exc}")
        public_validation = None
    else:
        errors.extend(
            f"published public release: {error}"
            for error in public_validation.get("errors", [])
        )
        if public_validation.get("valid") is not True and not public_validation.get("errors"):
            errors.append("published public release validation failed without diagnostics")
        declared_validation = receipt.get("validation")
        if isinstance(declared_validation, dict):
            for field in ("bounded_sheet_count", "tile_count", "tile_bytes"):
                if declared_validation.get(field) != public_validation.get(field):
                    errors.append(
                        f"publication receipt validation.{field} mismatch: "
                        f"receipt={declared_validation.get(field)!r}, "
                        f"actual={public_validation.get(field)!r}"
                    )

    runtime = receipt.get("runtime")
    if html_path is not None and html_path.is_file() and isinstance(runtime, dict):
        parser = _MapMetaParser()
        parser.feed(html_path.read_text(encoding="utf-8"))
        if parser.duplicates:
            errors.append(
                "interactive map HTML has duplicate release metadata: "
                + ", ".join(sorted(parser.duplicates))
            )
        expected_meta = {
            "ea-map-world-release": runtime.get("active_release"),
            "ea-map-world-target-release": runtime.get("target_release"),
            "ea-map-world-fallback-releases": ",".join(
                runtime.get("fallback_releases", [])
                if isinstance(runtime.get("fallback_releases"), list)
                else []
            ),
            "ea-map-cache-key": runtime.get("cache_key"),
            "ea-map-world-v3-manifest": runtime.get("world_v3_manifest"),
            "ea-map-sheet-tile-index": runtime.get("sheet_tile_index"),
        }
        for name, expected in expected_meta.items():
            if parser.values.get(name) != expected:
                errors.append(
                    f"interactive map HTML {name} mismatch: "
                    f"receipt={expected!r}, html={parser.values.get(name)!r}"
                )

    staging_patterns = (
        repo_root / "docs" / "data" / "map",
        repo_root / "docs" / "assets" / "images" / "maps" / "tiles",
        repo_root / "world" / "map-production" / "releases",
    )
    stale = sorted(
        path.relative_to(repo_root).as_posix()
        for directory in staging_patterns
        if directory.is_dir()
        for path in directory.glob("*world-v3*publishing*")
    )
    if stale:
        errors.append(
            "stale/partial world-v3 publication staging artifacts exist: "
            + ", ".join(stale)
        )
    return errors


def _resolve_repo_path(
    raw_path: str,
    *,
    label: str,
    repo_root: Path,
) -> tuple[Path | None, list[str]]:
    """Resolve a repository-relative POSIX file path without allowing escape."""

    if not raw_path or "\\" in raw_path:
        return None, [f"{label} must be a non-empty repository-relative POSIX path"]
    portable = PurePosixPath(raw_path)
    if (
        portable.is_absolute()
        or any(part in {"", ".", ".."} for part in portable.parts)
        or (portable.parts and portable.parts[0].endswith(":"))
    ):
        return None, [f"{label} must stay inside the repository: {raw_path}"]

    root = repo_root.resolve()
    resolved = root.joinpath(*portable.parts).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, [f"{label} must stay inside the repository: {raw_path}"]
    if not resolved.is_file():
        return resolved, [f"{label} does not exist as a file: {raw_path}"]
    return resolved, []


def _publication_jobs(manifest: Any) -> list[str]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("jobs"), list):
        return []
    return sorted(
        str(job.get("id"))
        for job in manifest["jobs"]
        if isinstance(job, dict) and job.get("status") in PUBLICATION_JOB_STATES
    )


def validate_release_readiness(
    readiness_path: Path = DEFAULT_READINESS,
    *,
    schema_path: Path = DEFAULT_SCHEMA,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Validate the declaration and execute the appropriate release checks."""

    errors: list[str] = []
    status: str | None = None
    manifest_path: Path | None = None
    release_result: dict[str, Any] | None = None
    coverage_result: dict[str, Any] | None = None
    publication_receipt: dict[str, Any] | None = None

    try:
        readiness = load_json(readiness_path)
        schema = load_json(schema_path)
    except ValidationFailure as exc:
        return {
            "valid": False,
            "readiness": str(readiness_path),
            "status": None,
            "manifest": None,
            "strict_release_required": False,
            "strict_release_executed": False,
            "errors": [str(exc)],
        }

    try:
        errors.extend(schema_errors(readiness, schema))
    except ValidationFailure as exc:
        errors.append(str(exc))
    if isinstance(readiness, dict):
        raw_status = readiness.get("status")
        status = raw_status if isinstance(raw_status, str) else None
        raw_manifest = readiness.get("manifest_path")
        if isinstance(raw_manifest, str):
            manifest_path, path_errors = _resolve_repo_path(
                raw_manifest,
                label="manifest_path",
                repo_root=repo_root,
            )
            errors.extend(path_errors)

    strict_required = status in STRICT_STATUSES
    if not errors and manifest_path is not None:
        try:
            release_result = release_validator.validate_release(
                manifest_path,
                repo_root=repo_root,
                strict_release=strict_required,
                sheet_minimum_state="published" if status == "published" else "accepted",
            )
        except (OSError, ValidationFailure) as exc:
            errors.append(str(exc))
        else:
            errors.extend(
                f"release validation: {error}"
                for error in release_result.get("errors", [])
            )
            if release_result.get("valid") is not True and not release_result.get("errors"):
                errors.append("release validation failed without diagnostic details")

        if status == "published" and not errors:
            publication_receipt, publication_errors = _validate_published_runtime(
                readiness,
                repo_root=repo_root,
            )
            errors.extend(publication_errors)

        if not strict_required:
            try:
                manifest = load_json(manifest_path)
            except ValidationFailure as exc:
                errors.append(str(exc))
            else:
                published_jobs = _publication_jobs(manifest)
                if published_jobs:
                    errors.append(
                        "readiness status 'in-progress' cannot defer strict validation "
                        "after jobs enter staging/published: " + ", ".join(published_jobs)
                    )

            # A complete accepted-sheet set is itself a release-readiness signal.
            # Probe coverage without propagating the expected per-sheet errors
            # while production is partial; the normal release result above has
            # already enforced all non-coverage integrity checks.
            try:
                coverage_result = release_validator.validate_release(
                    manifest_path,
                    repo_root=repo_root,
                    require_sheet_coverage=True,
                    sheet_minimum_state="accepted",
                )
            except (OSError, ValidationFailure) as exc:
                errors.append(f"cannot determine bounded-sheet coverage: {exc}")
            else:
                required = coverage_result.get("required_sheets")
                covered = coverage_result.get("covered_sheets")
                if not isinstance(required, int) or required <= 0:
                    errors.append(
                        "cannot determine a non-empty bounded-sheet release scope"
                    )
                elif covered == required:
                    errors.append(
                        "readiness status 'in-progress' cannot defer strict validation "
                        f"after all {required} bounded sheets reach accepted or later"
                    )

    evidence_result = coverage_result or release_result or {}

    return {
        "valid": not errors,
        "readiness": str(readiness_path),
        "status": status,
        "manifest": str(manifest_path) if manifest_path is not None else None,
        "strict_release_required": strict_required,
        "strict_release_executed": strict_required and release_result is not None,
        "published_runtime_checked": status == "published" and publication_receipt is not None,
        "publication_receipt": (
            str(readiness.get("publication_receipt_path"))
            if isinstance(readiness, dict)
            and isinstance(readiness.get("publication_receipt_path"), str)
            else None
        ),
        "jobs_checked": (release_result or {}).get("jobs_checked", 0),
        "required_sheets": evidence_result.get("required_sheets", 0),
        "covered_sheets": evidence_result.get("covered_sheets", 0),
        "errors": errors,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "declaration",
        type=Path,
        nargs="?",
        default=DEFAULT_READINESS,
        help=f"release readiness JSON (default: {DEFAULT_READINESS})",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help=f"readiness schema (default: {DEFAULT_SCHEMA})",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_release_readiness(
        args.declaration,
        schema_path=args.schema,
        repo_root=args.repo_root,
    )

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["valid"] and result["strict_release_executed"]:
        print(f"Strict map release validation passed: {result['manifest']}")
        print(
            f"  Sheet coverage={result['covered_sheets']}/{result['required_sheets']}"
        )
    elif result["valid"]:
        print("Map release remains in progress; strict publication checks are deferred.")
        print(
            f"  Non-strict artifact validation passed for {result['jobs_checked']} job(s)."
        )
        print(
            f"  Accepted bounded-sheet coverage="
            f"{result['covered_sheets']}/{result['required_sheets']}"
        )
    else:
        print(f"Map release readiness validation failed: {args.declaration}", file=sys.stderr)
        for error in result["errors"]:
            print(f"- {error}", file=sys.stderr)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
