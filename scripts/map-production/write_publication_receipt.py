#!/usr/bin/env python3
"""Write the hash-locked world-v3 publication receipt after strict validation.

This command is intentionally the last publication step.  It refuses to create
the receipt unless the readiness declaration is already ``published``, every
production job passes the strict published-state gate, the complete public tile
release validates from bytes on disk, both runtime indexes are byte-identical,
the active HTML metadata names the same immutable release, and the canonical
Phase 6 browser-QA evidence bundle still matches published readiness exactly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

import build_phase5_assets as phase5
import validate_release_readiness as readiness_validator
from production_common import (
    REPO_ROOT,
    ValidationFailure,
    load_json,
    parse_rfc3339,
    utc_now,
)
from validate_manifest import schema_errors


WRITER_ID = "sstory-map-production/write_publication_receipt.py@1"
RECEIPT_RELATIVE_PATH = PurePosixPath(
    "world/map-production/releases/world-v3-publication-receipt.json"
)
EXPECTED_SHEET_COUNT = 23


class PublicationReceiptError(RuntimeError):
    """Raised when the final receipt cannot be issued without ambiguity."""


def _stable_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _raise_errors(label: str, errors: Sequence[str]) -> None:
    if errors:
        raise PublicationReceiptError(f"{label}: " + "; ".join(errors))


def _load_published_inputs(
    readiness_path: Path,
    *,
    readiness_schema_path: Path,
    repo_root: Path,
) -> tuple[dict[str, Any], Path, Path]:
    """Load the declaration and require the exact final published boundary."""

    try:
        readiness = load_json(readiness_path)
        readiness_schema = load_json(readiness_schema_path)
    except ValidationFailure as exc:
        raise PublicationReceiptError(str(exc)) from exc
    if not isinstance(readiness, dict):
        raise PublicationReceiptError("release readiness must contain a JSON object")
    try:
        errors = schema_errors(readiness, readiness_schema)
    except ValidationFailure as exc:
        raise PublicationReceiptError(str(exc)) from exc
    _raise_errors("release readiness schema validation failed", errors)
    if readiness.get("status") != "published":
        raise PublicationReceiptError(
            "publication receipt requires readiness status 'published'"
        )
    if readiness.get("publication_receipt_path") != RECEIPT_RELATIVE_PATH.as_posix():
        raise PublicationReceiptError(
            "published readiness must name the canonical receipt path "
            f"{RECEIPT_RELATIVE_PATH.as_posix()!r}"
        )

    manifest_path, path_errors = readiness_validator._resolve_repo_path(
        readiness.get("manifest_path"),
        label="manifest_path",
        repo_root=repo_root,
    )
    _raise_errors("published manifest path is invalid", path_errors)
    if manifest_path is None:
        raise PublicationReceiptError("published manifest path could not be resolved")

    root = repo_root.resolve()
    receipt_path = root.joinpath(*RECEIPT_RELATIVE_PATH.parts).resolve()
    try:
        receipt_path.relative_to(root)
    except ValueError as exc:
        raise PublicationReceiptError("publication receipt escapes the repository") from exc
    return readiness, manifest_path, receipt_path


def _validate_strict_published_manifest(
    manifest_path: Path,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Execute the same strict manifest gate used by published readiness."""

    try:
        result = readiness_validator.release_validator.validate_release(
            manifest_path,
            repo_root=repo_root,
            strict_release=True,
            sheet_minimum_state="published",
        )
    except (OSError, ValidationFailure) as exc:
        raise PublicationReceiptError(
            f"strict published release validation failed: {exc}"
        ) from exc
    if not isinstance(result, dict):
        raise PublicationReceiptError(
            "strict published release validator returned a non-object result"
        )
    errors = result.get("errors")
    if not isinstance(errors, list):
        raise PublicationReceiptError(
            "strict published release validator omitted its errors array"
        )
    if result.get("valid") is not True:
        details = errors or ["validator failed without diagnostic details"]
        _raise_errors("strict published release validation failed", details)
    if errors:
        _raise_errors("strict published release validation returned errors", errors)
    if (
        result.get("required_sheets") != EXPECTED_SHEET_COUNT
        or result.get("covered_sheets") != EXPECTED_SHEET_COUNT
    ):
        raise PublicationReceiptError(
            "strict published release must cover exactly "
            f"{EXPECTED_SHEET_COUNT}/{EXPECTED_SHEET_COUNT} bounded sheets; "
            f"got {result.get('covered_sheets')!r}/{result.get('required_sheets')!r}"
        )
    return result


def _artifact_path(repo_root: Path, relative: PurePosixPath, label: str) -> Path:
    path = repo_root.resolve().joinpath(*relative.parts).resolve()
    try:
        path.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise PublicationReceiptError(f"{label} escapes the repository") from exc
    if not path.is_file():
        raise PublicationReceiptError(f"{label} is missing: {relative.as_posix()}")
    return path


def _runtime_from_html(html_path: Path) -> dict[str, Any]:
    parser = readiness_validator._MapMetaParser()
    try:
        parser.feed(html_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise PublicationReceiptError(
            f"cannot read interactive map HTML metadata: {exc}"
        ) from exc
    if parser.duplicates:
        raise PublicationReceiptError(
            "interactive map HTML has duplicate release metadata: "
            + ", ".join(sorted(parser.duplicates))
        )

    names = {
        "active_release": "ea-map-world-release",
        "target_release": "ea-map-world-target-release",
        "fallback_releases": "ea-map-world-fallback-releases",
        "cache_key": "ea-map-cache-key",
        "world_v3_manifest": "ea-map-world-v3-manifest",
        "sheet_tile_index": "ea-map-sheet-tile-index",
    }
    missing = sorted(name for name in names.values() if name not in parser.values)
    if missing:
        raise PublicationReceiptError(
            "interactive map HTML is missing release metadata: " + ", ".join(missing)
        )
    fallback_value = parser.values[names["fallback_releases"]]
    runtime = {
        "active_release": parser.values[names["active_release"]],
        "target_release": parser.values[names["target_release"]],
        "fallback_releases": fallback_value.split(",") if fallback_value else [],
        "cache_key": parser.values[names["cache_key"]],
        "world_v3_manifest": parser.values[names["world_v3_manifest"]],
        "sheet_tile_index": parser.values[names["sheet_tile_index"]],
    }
    return runtime


def build_publication_receipt(
    *,
    published_by: str,
    published_at: str,
    browser_qa: dict[str, Any],
    repo_root: Path = REPO_ROOT,
    receipt_schema_path: Path = readiness_validator.PUBLICATION_RECEIPT_SCHEMA,
) -> dict[str, Any]:
    """Recompute public evidence and return a schema-valid receipt candidate."""

    if not isinstance(published_by, str) or not published_by.strip():
        raise PublicationReceiptError("published_by must be a non-empty identifier")
    if not isinstance(published_at, str) or not published_at:
        raise PublicationReceiptError("published_at must be an RFC 3339 timestamp")
    if not isinstance(browser_qa, dict):
        raise PublicationReceiptError("browser_qa must be an evidence object")
    try:
        publication_time = parse_rfc3339(published_at)
        browser_completion = parse_rfc3339(str(browser_qa.get("completed_at", "")))
    except (TypeError, ValueError) as exc:
        raise PublicationReceiptError(
            f"publication/browser QA timestamp is invalid: {exc}"
        ) from exc
    if publication_time < browser_completion:
        raise PublicationReceiptError(
            "published_at must not precede Phase 6 browser QA completion"
        )

    canonical_path = _artifact_path(
        repo_root,
        readiness_validator.CANONICAL_INDEX_PATH,
        "canonical sheet tile index",
    )
    compatibility_path = _artifact_path(
        repo_root,
        readiness_validator.COMPATIBILITY_INDEX_PATH,
        "compatibility sheet tile index",
    )
    if canonical_path.read_bytes() != compatibility_path.read_bytes():
        raise PublicationReceiptError(
            "canonical and compatibility sheet tile indexes must be byte-identical"
        )

    html_path = _artifact_path(
        repo_root,
        readiness_validator.INTERACTIVE_MAP_HTML,
        "interactive map HTML",
    )
    runtime = _runtime_from_html(html_path)

    release_tree = repo_root.resolve().joinpath(
        *readiness_validator.PUBLIC_RELEASE_TREE.parts
    ).resolve()
    try:
        release_tree.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise PublicationReceiptError("world-v3 release tree escapes the repository") from exc
    if not release_tree.is_dir():
        raise PublicationReceiptError(
            "immutable world-v3 release tree is missing: "
            + readiness_validator.PUBLIC_RELEASE_TREE.as_posix()
        )
    file_count, tree_sha = readiness_validator._release_tree_evidence(release_tree)

    try:
        public_validation = phase5.validate_public_tile_release(
            repo_root / "docs",
            release_id=readiness_validator.PUBLIC_RELEASE_ID,
            verify_tiles=True,
        )
    except (OSError, ValueError, ValidationFailure, phase5.Phase5BuildError) as exc:
        raise PublicationReceiptError(
            f"published public release validation failed: {exc}"
        ) from exc
    if not isinstance(public_validation, dict):
        raise PublicationReceiptError(
            "published public release validator returned a non-object result"
        )
    public_errors = public_validation.get("errors")
    if not isinstance(public_errors, list):
        raise PublicationReceiptError(
            "published public release validator omitted its errors array"
        )
    if public_validation.get("valid") is not True:
        _raise_errors(
            "published public release validation failed",
            public_errors or ["validator failed without diagnostic details"],
        )
    if public_errors:
        _raise_errors("published public release validation returned errors", public_errors)
    if public_validation.get("release_id") != readiness_validator.PUBLIC_RELEASE_ID:
        raise PublicationReceiptError(
            "published public release identity mismatch: "
            f"{public_validation.get('release_id')!r}"
        )
    if public_validation.get("bounded_sheet_count") != EXPECTED_SHEET_COUNT:
        raise PublicationReceiptError(
            "published public release must contain exactly "
            f"{EXPECTED_SHEET_COUNT} bounded sheets"
        )
    for field in ("tile_count", "tile_bytes"):
        value = public_validation.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise PublicationReceiptError(
                f"published public release {field} must be a positive integer"
            )

    receipt = {
        "$schema": "https://sstory.example/schemas/publication-receipt.schema.json",
        "schema_version": "1.0.0",
        "type": "sstory-map-publication-receipt",
        "release_id": readiness_validator.PUBLIC_RELEASE_ID,
        "published_at": published_at,
        "published_by": published_by,
        "canonical_index": {
            "path": readiness_validator.CANONICAL_INDEX_PATH.as_posix(),
            "sha256": readiness_validator._sha256_file(canonical_path),
        },
        "compatibility_index": {
            "path": readiness_validator.COMPATIBILITY_INDEX_PATH.as_posix(),
            "sha256": readiness_validator._sha256_file(compatibility_path),
        },
        "release_tree": {
            "path": readiness_validator.PUBLIC_RELEASE_TREE.as_posix(),
            "file_count": file_count,
            "sha256": tree_sha,
        },
        "browser_qa": dict(browser_qa),
        "html": {
            "path": readiness_validator.INTERACTIVE_MAP_HTML.as_posix(),
            "sha256": readiness_validator._sha256_file(html_path),
        },
        "runtime": runtime,
        "validation": {
            "bounded_sheet_count": public_validation["bounded_sheet_count"],
            "tile_count": public_validation["tile_count"],
            "tile_bytes": public_validation["tile_bytes"],
        },
    }
    errors = readiness_validator.validate_publication_receipt(
        receipt,
        repo_root=repo_root,
        receipt_schema_path=receipt_schema_path,
    )
    _raise_errors("publication receipt candidate validation failed", errors)
    return receipt


def _existing_timestamp(receipt_path: Path) -> str | None:
    if not receipt_path.is_file():
        return None
    try:
        existing = load_json(receipt_path)
    except ValidationFailure as exc:
        raise PublicationReceiptError(
            f"existing publication receipt is unreadable; refusing overwrite: {exc}"
        ) from exc
    if not isinstance(existing, dict) or not isinstance(existing.get("published_at"), str):
        raise PublicationReceiptError(
            "existing publication receipt lacks published_at; refusing overwrite"
        )
    return existing["published_at"]


def _atomic_install_once(path: Path, payload: bytes) -> bool:
    """Install ``payload`` atomically, refusing every non-identical overwrite."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise PublicationReceiptError(
            f"publication receipt writer lock already exists: {lock_path}"
        ) from exc

    temporary: Path | None = None
    try:
        os.close(lock_fd)
        if path.exists():
            if not path.is_file() or path.read_bytes() != payload:
                raise PublicationReceiptError(
                    "refusing to overwrite a non-identical publication receipt"
                )
            return False

        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".publishing",
            dir=path.parent,
            delete=False,
        )
        temporary = Path(handle.name)
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        if temporary.read_bytes() != payload:
            raise PublicationReceiptError("temporary publication receipt verification failed")
        os.replace(temporary, path)
        temporary = None
        if path.read_bytes() != payload:
            raise PublicationReceiptError("installed publication receipt verification failed")
        return True
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
        if lock_path.exists():
            lock_path.unlink()


def write_publication_receipt(
    *,
    readiness_path: Path = readiness_validator.DEFAULT_READINESS,
    readiness_schema_path: Path = readiness_validator.DEFAULT_SCHEMA,
    receipt_schema_path: Path = readiness_validator.PUBLICATION_RECEIPT_SCHEMA,
    repo_root: Path = REPO_ROOT,
    published_by: str = WRITER_ID,
    published_at: str | None = None,
) -> dict[str, Any]:
    """Validate the complete release and atomically issue its final receipt."""

    readiness, manifest_path, receipt_path = _load_published_inputs(
        readiness_path,
        readiness_schema_path=readiness_schema_path,
        repo_root=repo_root,
    )
    _validate_strict_published_manifest(manifest_path, repo_root=repo_root)

    effective_timestamp = published_at
    if effective_timestamp is None:
        effective_timestamp = _existing_timestamp(receipt_path) or utc_now()
    receipt = build_publication_receipt(
        published_by=published_by,
        published_at=effective_timestamp,
        browser_qa=readiness["browser_qa_bundle"],
        repo_root=repo_root,
        receipt_schema_path=receipt_schema_path,
    )
    payload = _stable_json_bytes(receipt)
    written = _atomic_install_once(receipt_path, payload)

    # Re-run the normal production entry point against the durable receipt.  If
    # an external mutation raced the install, never leave a newly issued invalid
    # receipt behind.
    result = readiness_validator.validate_release_readiness(
        readiness_path,
        schema_path=readiness_schema_path,
        repo_root=repo_root,
    )
    if result.get("valid") is not True:
        if written and receipt_path.is_file() and receipt_path.read_bytes() == payload:
            receipt_path.unlink()
        errors = result.get("errors")
        details = errors if isinstance(errors, list) and errors else ["unknown failure"]
        _raise_errors("durable published readiness validation failed", details)

    return {
        "valid": True,
        "written": written,
        "receipt": RECEIPT_RELATIVE_PATH.as_posix(),
        "release_id": receipt["release_id"],
        "published_at": receipt["published_at"],
        "published_by": receipt["published_by"],
        "bounded_sheet_count": receipt["validation"]["bounded_sheet_count"],
        "tile_count": receipt["validation"]["tile_count"],
        "tile_bytes": receipt["validation"]["tile_bytes"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--readiness",
        type=Path,
        default=readiness_validator.DEFAULT_READINESS,
    )
    parser.add_argument(
        "--readiness-schema",
        type=Path,
        default=readiness_validator.DEFAULT_SCHEMA,
    )
    parser.add_argument(
        "--receipt-schema",
        type=Path,
        default=readiness_validator.PUBLICATION_RECEIPT_SCHEMA,
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--published-by", default=WRITER_ID)
    parser.add_argument("--published-at")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = write_publication_receipt(
            readiness_path=args.readiness,
            readiness_schema_path=args.readiness_schema,
            receipt_schema_path=args.receipt_schema,
            repo_root=args.repo_root,
            published_by=args.published_by,
            published_at=args.published_at,
        )
    except (OSError, ValueError, ValidationFailure, PublicationReceiptError) as exc:
        result = {"valid": False, "error": str(exc)}

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["valid"]:
        action = "written" if result["written"] else "already verified"
        print(
            f"world-v3 publication receipt {action}: {result['receipt']} "
            f"({result['bounded_sheet_count']} sheets, {result['tile_count']} tiles)"
        )
    else:
        print(f"Publication receipt was not written: {result['error']}", file=sys.stderr)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
