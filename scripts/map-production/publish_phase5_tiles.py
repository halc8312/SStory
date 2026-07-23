#!/usr/bin/env python3
"""Atomically publish one validated Phase 5 schema-2 tile release into docs/."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

import build_phase5_assets as phase5


PUBLISHER_ID = "sstory-map-production/publish_phase5_tiles.py@1"


class PublicationError(RuntimeError):
    """Raised when an immutable tile release cannot be published safely."""


def _inside_repo(path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(phase5.REPO_ROOT.resolve())
    except ValueError as exc:
        raise PublicationError(f"{label} must stay inside the repository: {path}") from exc
    if resolved == phase5.REPO_ROOT.resolve():
        raise PublicationError(f"{label} may not be the repository root")
    return resolved


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): phase5.sha256_file(path)
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file())
    }


def _restore_file(path: Path, previous: bytes | None) -> None:
    if previous is None:
        if path.exists():
            path.unlink()
        return
    temporary = path.with_name(f".{path.name}.rollback")
    temporary.write_bytes(previous)
    os.replace(temporary, path)


def publish_release(
    build_root: Path,
    docs_root: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    build_root = _inside_repo(build_root, "build root")
    docs_root = _inside_repo(docs_root, "docs root")
    build_validation = phase5.validate_build_root(build_root)
    if not build_validation["valid"]:
        raise PublicationError(
            "source build failed validation: " + "; ".join(build_validation["errors"])
        )
    publication = build_validation.get("public_tile_release")
    if not isinstance(publication, dict) or not publication.get("valid"):
        raise PublicationError("source build does not contain a valid all-23 tile release")
    release_id = publication["release_id"]
    source_public = build_root / "public"
    source_release = (
        source_public
        / Path(*phase5.PUBLIC_TILE_BASE.parts)
        / release_id
    )
    destination_release = (
        docs_root
        / Path(*phase5.PUBLIC_TILE_BASE.parts)
        / release_id
    )
    if destination_release.exists():
        raise PublicationError(
            f"refusing to overwrite immutable release directory: {destination_release}"
        )
    index_relatives = (
        phase5.PUBLIC_INDEX_CANONICAL_PATH,
        phase5.PUBLIC_INDEX_COMPATIBILITY_PATH,
    )
    source_indexes = [source_public / Path(*relative.parts) for relative in index_relatives]
    if any(not path.is_file() for path in source_indexes):
        raise PublicationError("source build is missing a schema-2 runtime index")
    if dry_run:
        return {
            "valid": True,
            "dry_run": True,
            "release_id": release_id,
            "source": phase5.repo_path(source_release),
            "destination": phase5.repo_path(destination_release),
            "bounded_sheet_count": publication["bounded_sheet_count"],
            "tile_count": publication["tile_count"],
            "tile_bytes": publication["tile_bytes"],
        }

    destination_release.parent.mkdir(parents=True, exist_ok=True)
    index_directory = docs_root / "data" / "map"
    index_directory.mkdir(parents=True, exist_ok=True)
    staging_root = Path(
        tempfile.mkdtemp(
            prefix=f".{release_id}.publishing-", dir=destination_release.parent
        )
    )
    staged_release = staging_root / "release"
    staged_indexes: list[Path] = []
    installed_release = False
    target_indexes = [docs_root / Path(*relative.parts) for relative in index_relatives]
    previous_indexes = [path.read_bytes() if path.is_file() else None for path in target_indexes]
    try:
        shutil.copytree(source_release, staged_release)
        if _tree_hashes(staged_release) != _tree_hashes(source_release):
            raise PublicationError("staged release hashes do not match the validated source")
        for source_index, target_index in zip(source_indexes, target_indexes):
            staged = target_index.with_name(
                f".{target_index.name}.{release_id}.publishing"
            )
            if staged.exists():
                raise PublicationError(f"stale publication staging file exists: {staged}")
            shutil.copy2(source_index, staged)
            if phase5.sha256_file(staged) != phase5.sha256_file(source_index):
                raise PublicationError(f"staged index hash mismatch: {source_index}")
            staged_indexes.append(staged)

        os.replace(staged_release, destination_release)
        installed_release = True
        for staged, target in zip(staged_indexes, target_indexes):
            os.replace(staged, target)

        destination_validation = phase5.validate_public_tile_release(
            docs_root, release_id=release_id
        )
        if not destination_validation["valid"]:
            raise PublicationError(
                "published docs release failed verification: "
                + "; ".join(destination_validation["errors"])
            )
        return {
            "valid": True,
            "dry_run": False,
            "published_by": PUBLISHER_ID,
            "release_id": release_id,
            "destination": phase5.repo_path(destination_release),
            "canonical_index": phase5.repo_path(target_indexes[0]),
            "compatibility_index": phase5.repo_path(target_indexes[1]),
            "bounded_sheet_count": destination_validation["bounded_sheet_count"],
            "tile_count": destination_validation["tile_count"],
            "tile_bytes": destination_validation["tile_bytes"],
            "release_file_count": len(_tree_hashes(destination_release)),
            "release_tree_sha256": hashlib.sha256(
                json.dumps(
                    _tree_hashes(destination_release),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
    except Exception:
        for path, previous in zip(target_indexes, previous_indexes):
            _restore_file(path, previous)
        if installed_release and destination_release.is_dir():
            resolved_destination = destination_release.resolve()
            expected_parent = (
                docs_root / Path(*phase5.PUBLIC_TILE_BASE.parts)
            ).resolve()
            if resolved_destination.parent == expected_parent:
                shutil.rmtree(resolved_destination)
        raise
    finally:
        for staged in staged_indexes:
            if staged.exists():
                staged.unlink()
        if staging_root.exists():
            shutil.rmtree(staging_root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_root", type=Path)
    parser.add_argument("--docs-root", type=Path, default=phase5.REPO_ROOT / "docs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = publish_release(args.build_root, args.docs_root, dry_run=args.dry_run)
    except (OSError, ValueError, phase5.Phase5BuildError, PublicationError) as exc:
        result = {"valid": False, "error": str(exc)}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["valid"]:
        action = "validated" if result["dry_run"] else "published"
        print(
            f"Phase 5 tile release {action}: {result['release_id']} "
            f"({result['bounded_sheet_count']} sheets, {result['tile_count']} tiles)"
        )
    else:
        print(f"Phase 5 tile publication failed: {result['error']}", file=sys.stderr)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
