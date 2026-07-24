#!/usr/bin/env python3
"""Create paired Markdown/JSON templates for repeatable map Vision QA."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from production_common import ID_PATTERN, REPO_ROOT, dump_json, utc_now
from validate_manifest import validate_manifest
from release_bound_artifact import BoundArtifact, BoundArtifactError, bind_file
from release_path_safety import ReleasePathError
import phase5_vision_evidence as vision_evidence


REVIEW_VIEWS = (
    ("overview", "全体構図"),
    ("original", "原寸100%"),
    ("zoom", "200%・400%拡大"),
    ("nine_regions", "中央・四隅・四辺の9領域"),
    ("control_overlay", "制御図との半透明重ね合わせ"),
    ("parent_zoom", "親ズーム画像との比較"),
    ("neighbor_seams", "四方向の隣接合成"),
    ("vector_overlay", "ベクターラベル・道路・POI重畳"),
    ("desktop", "Leafletデスクトップ表示"),
    ("mobile", "Leafletモバイル表示"),
)

IMMEDIATE_FAILURES = (
    ("geometry_shift", "海岸線・河川・主要道路・城壁の移動"),
    ("missing_required", "必須地点の欠落"),
    ("noncanon_major", "正典外の主要都市・施設"),
    ("generated_text", "AI生成文字・記号"),
    ("visible_seam", "目視できる継ぎ目"),
    ("modern_or_watermark", "現代物・透かし・署名"),
    ("perspective_jump", "遠近法化・縮尺の急変"),
    ("repetition", "建物・樹木・岩の不自然な反復"),
)

SCORE_AXES = (
    ("canon_geometry", "正典・地形形状との一致", 25),
    ("parent_continuity", "親子ズームの連続性", 15),
    ("seam_continuity", "隣接画像の継ぎ目", 15),
    ("style_consistency", "画風・色・線密度", 15),
    ("detail_density", "縮尺相応の情報量", 10),
    ("artifact_integrity", "生成破綻・反復模様", 10),
    ("vector_readability", "ベクター重畳時の可読性", 10),
)

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _assert_git_index_matches(binding: BoundArtifact) -> None:
    """Require the Git index to contain the exact receipt bytes just bound."""

    try:
        result = subprocess.run(
            ["git", "show", f":{binding.relative}"],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise BoundArtifactError(
            f"cannot inspect Git index for {binding.label}: {exc}"
        ) from exc
    if result.returncode != 0:
        diagnostic = result.stderr.decode("utf-8", errors="replace").strip()
        suffix = f" ({diagnostic})" if diagnostic else ""
        raise BoundArtifactError(
            f"{binding.label} must already be staged in the Git index: "
            f"{binding.relative}{suffix}"
        )
    if result.stdout != binding.data:
        raise BoundArtifactError(
            f"Git index bytes do not match the bound {binding.label}: "
            f"{binding.relative}"
        )


def build_report(
    job_id: str,
    image_path: str,
    *,
    reviewer: str,
    golden: bool,
    threshold: int | None = None,
    image_sha256: str | None = None,
    review_mode: str | None = None,
    vision_bundle_receipt: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not ID_PATTERN.fullmatch(job_id):
        raise ValueError("job_id must use lowercase kebab/snake case")
    acceptance_threshold = (
        threshold if threshold is not None else (94 if golden else 90)
    )
    if not 90 <= acceptance_threshold <= 100:
        raise ValueError("acceptance threshold must be between 90 and 100")
    selected_mode = review_mode or ("blind-independent" if golden else "standard")
    if selected_mode not in {"standard", "self", "blind-independent"}:
        raise ValueError("review_mode must be standard, self, or blind-independent")
    if golden and selected_mode != "blind-independent":
        raise ValueError("golden reports require review_mode='blind-independent'")
    if image_sha256 is not None and not SHA256_PATTERN.fullmatch(image_sha256):
        raise ValueError("image_sha256 must be a lowercase 64-character SHA-256 digest")
    if golden and image_sha256 is None:
        raise ValueError("golden reports require image_sha256")
    report = {
        "schema_version": "1.0.0",
        "job_id": job_id,
        "image_path": image_path,
        "created_at": utc_now(),
        "reviewer": reviewer,
        "status": "draft",
        "golden_reference": golden,
        "review_mode": selected_mode,
        "acceptance_threshold": acceptance_threshold,
        "review_views": [
            {
                "id": identifier,
                "label": label,
                "complete": False,
                "evidence": "",
                "notes": "",
            }
            for identifier, label in REVIEW_VIEWS
        ],
        "immediate_failures": [
            {"id": identifier, "label": label, "detected": None, "evidence": ""}
            for identifier, label in IMMEDIATE_FAILURES
        ],
        "scores": [
            {
                "id": identifier,
                "label": label,
                "maximum": maximum,
                "score": None,
                "notes": "",
            }
            for identifier, label, maximum in SCORE_AXES
        ],
        "total_score": None,
        "decision": "pending",
        "summary": "",
        "required_changes": [],
    }
    if image_sha256 is not None:
        report["image_sha256"] = image_sha256
    if vision_bundle_receipt is not None:
        if (
            not isinstance(vision_bundle_receipt, dict)
            or set(vision_bundle_receipt) != {"path", "sha256"}
            or not isinstance(vision_bundle_receipt.get("path"), str)
            or not SHA256_PATTERN.fullmatch(
                str(vision_bundle_receipt.get("sha256", ""))
            )
        ):
            raise ValueError("vision_bundle_receipt must contain exact path and sha256")
        report["vision_bundle"] = {
            "receipt": dict(vision_bundle_receipt),
            "reviewer_confirmed_exact_five": False,
        }
    return report


def markdown_report(report: dict[str, Any]) -> str:
    created_date = str(report["created_at"])[:10]
    yaml_title = json.dumps(f"Map Vision QA: {report['job_id']}", ensure_ascii=False)
    yaml_author = json.dumps(str(report["reviewer"]), ensure_ascii=False)
    yaml_scope = json.dumps(
        f"Map-production image {report['job_id']}", ensure_ascii=False
    )
    lines = [
        "---",
        'type: "analysis"',
        'category: "analysis"',
        f"title: {yaml_title}",
        'version: "1.0.0"',
        f'created: "{created_date}"',
        f'last_updated: "{created_date}"',
        f"author: {yaml_author}",
        'tags: ["maps", "vision-qa", "image-generation", "quality"]',
        'status: "draft"',
        'analysis_type: "feature-evaluation"',
        f"scope: {yaml_scope}",
        'methodology: "Codex Vision QA review views, immediate-failure gates, and weighted scoring"',
        "---",
        "",
        f"# Map Vision QA: {report['job_id']}",
        "",
        f"- Image: `{report['image_path']}`",
        f"- Image SHA-256: `{report.get('image_sha256', 'not bound')}`",
        f"- Reviewer: {report['reviewer']}",
        f"- Created: {report['created_at']}",
        f"- Acceptance threshold: {report['acceptance_threshold']}/100",
        f"- Golden reference: {'yes' if report['golden_reference'] else 'no'}",
        f"- Review mode: {report.get('review_mode', 'standard')}",
        (
            "- Exact-five receipt: `"
            + str(
                report.get("vision_bundle", {})
                .get("receipt", {})
                .get("path", "not bound")
            )
            + "`"
        ),
        (
            "- Exact-five reviewer confirmation: "
            + (
                "yes"
                if report.get("vision_bundle", {}).get("reviewer_confirmed_exact_five")
                is True
                else "no"
            )
        ),
        "",
        "## Review views",
        "",
    ]
    lines.extend(
        f"- [ ] {item['label']} — evidence: _TBD_" for item in report["review_views"]
    )
    lines.extend(["", "## Immediate-failure gate", ""])
    lines.extend(
        f"- [ ] Not detected: {item['label']} — evidence: _TBD_"
        for item in report["immediate_failures"]
    )
    lines.extend(
        [
            "",
            "## Score",
            "",
            "| Axis | Score | Maximum | Evidence / notes |",
            "|---|---:|---:|---|",
        ]
    )
    lines.extend(
        f"| {item['label']} | — | {item['maximum']} | — |" for item in report["scores"]
    )
    lines.extend(
        [
            "| **Total** | **—** | **100** | |",
            "",
            "## Automated QA evidence",
            "",
            "- Land/sea mask match (target ≥ 0.98): _TBD_",
            "- Boundary within 8 px (target ≥ 0.95): _TBD_",
            "- Neighbor overlap SSIM (target ≥ 0.90): _TBD_",
            "",
            "## Decision",
            "",
            "- Decision: `pending`",
            "- Summary: _TBD_",
            "- Required changes: _TBD_",
            "",
            "A score alone cannot override an immediate failure. Complete every review view and attach evidence before acceptance.",
            "",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--image", help="candidate image path")
    parser.add_argument("--manifest", type=Path, help="optional production manifest")
    parser.add_argument(
        "--output", required=True, type=Path, help="output stem or .md/.json path"
    )
    parser.add_argument(
        "--format", choices=("both", "markdown", "json"), default="both"
    )
    parser.add_argument("--reviewer", default="Codex Vision QA")
    parser.add_argument("--golden", action="store_true")
    parser.add_argument(
        "--image-sha256", help="lowercase SHA-256 digest of the reviewed image"
    )
    parser.add_argument(
        "--vision-bundle-receipt",
        type=Path,
        help=(
            "tracked Phase 5 exact-five view-bundle.json; the generated draft "
            "keeps reviewer confirmation false until all five views are inspected"
        ),
    )
    parser.add_argument(
        "--review-mode",
        choices=("standard", "self", "blind-independent"),
        help="review independence mode (Golden reports require blind-independent)",
    )
    parser.add_argument("--threshold", type=int)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    image = args.image
    threshold = args.threshold
    image_sha256 = args.image_sha256
    vision_bundle_receipt: dict[str, str] | None = None
    vision_bundle_binding: BoundArtifact | None = None
    if args.manifest:
        manifest, errors = validate_manifest(args.manifest)
        if errors or manifest is None:
            print("Cannot create QA report from an invalid manifest.", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        job = next(
            (item for item in manifest["jobs"] if item.get("id") == args.job_id), None
        )
        if job is None:
            print(f"Unknown manifest job: {args.job_id!r}", file=sys.stderr)
            return 1
        master = job.get("master")
        if image is None and isinstance(master, dict):
            image = master.get("path")
        if threshold is None:
            threshold = job.get("acceptance_threshold")
        if (
            image_sha256 is None
            and isinstance(master, dict)
            and image == master.get("path")
        ):
            image_sha256 = master.get("sha256")
    if not image:
        print(
            "--image is required when the manifest job has no master.path",
            file=sys.stderr,
        )
        return 2
    if args.vision_bundle_receipt is not None:
        try:
            receipt = bind_file(
                args.vision_bundle_receipt,
                label="Phase 5 exact-five Vision receipt",
                trackable=True,
            )
            _assert_git_index_matches(receipt)
            receipt_document = receipt.json_object()
        except (BoundArtifactError, ReleasePathError) as exc:
            print(f"Vision bundle binding failed: {exc}", file=sys.stderr)
            return 2
        receipt_source = receipt_document.get("source")
        if (
            receipt_document.get("schema_version")
            != vision_evidence.CANONICAL_RECEIPT_SCHEMA_VERSION
            or receipt_document.get("type") != vision_evidence.BUNDLE_TYPE
            or not isinstance(receipt_source, dict)
            or receipt_source.get("path") != image
            or (
                image_sha256 is not None
                and receipt_source.get("sha256") != image_sha256
            )
        ):
            print(
                "Vision bundle receipt does not bind the selected image bytes",
                file=sys.stderr,
            )
            return 2
        vision_bundle_receipt = receipt.artifact()
        vision_bundle_binding = receipt
    try:
        report = build_report(
            args.job_id,
            image,
            reviewer=args.reviewer,
            golden=args.golden,
            threshold=threshold,
            image_sha256=image_sha256,
            review_mode=args.review_mode,
            vision_bundle_receipt=vision_bundle_receipt,
        )
    except ValueError as exc:
        print(f"QA report creation failed: {exc}", file=sys.stderr)
        return 2

    if vision_bundle_binding is not None:
        try:
            _assert_git_index_matches(vision_bundle_binding)
            vision_bundle_binding.assert_unchanged()
        except BoundArtifactError as exc:
            print(f"Vision bundle binding failed: {exc}", file=sys.stderr)
            return 2

    base = (
        args.output.with_suffix("")
        if args.output.suffix.lower() in {".md", ".json"}
        else args.output
    )
    outputs: list[tuple[Path, str]] = []
    if args.format in {"both", "markdown"}:
        outputs.append((base.with_suffix(".md"), markdown_report(report)))
    if args.format in {"both", "json"}:
        outputs.append((base.with_suffix(".json"), ""))
    existing = [path for path, _ in outputs if path.exists()]
    if existing and not args.overwrite:
        print(
            "Refusing to overwrite existing report(s): "
            + ", ".join(map(str, existing)),
            file=sys.stderr,
        )
        return 1
    for path, content in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".json":
            dump_json(path, report)
        else:
            path.write_text(content, encoding="utf-8")
        print(f"Created QA report template: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
