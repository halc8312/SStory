import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import validate_release_readiness  # noqa: E402
import validate_phase6_browser_qa  # noqa: E402
import write_publication_receipt  # noqa: E402


READINESS_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "release-readiness.schema.json"
)
RECEIPT_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "publication-receipt.schema.json"
)
TIMESTAMP = "2026-07-20T12:34:56Z"
PUBLISHER = "unit-test/publication-writer"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def strict_result(**overrides):
    result = {
        "valid": True,
        "errors": [],
        "jobs_checked": 24,
        "required_sheets": 23,
        "covered_sheets": 23,
    }
    result.update(overrides)
    return result


def public_result(**overrides):
    result = {
        "valid": True,
        "release_id": "world-v3",
        "bounded_sheet_count": 23,
        "tile_count": 1350,
        "tile_bytes": 987654,
        "errors": [],
    }
    result.update(overrides)
    return result


class PublicationReceiptWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".publication-receipt-writer-test-", dir=REPO_ROOT
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.readiness = (
            self.root / "world" / "map-production" / "release-readiness.json"
        )
        self.manifest = (
            self.root / "world" / "map-production" / "production-manifest.json"
        )
        self.receipt = (
            self.root
            / "world"
            / "map-production"
            / "releases"
            / "world-v3-publication-receipt.json"
        )
        browser_bundle = self.root.joinpath(
            *validate_release_readiness.BROWSER_QA_BUNDLE_PATH.parts
        )
        self.browser_receipt = (
            browser_bundle / validate_release_readiness.BROWSER_QA_RECEIPT_NAME
        )
        self.browser_receipt_payload = {
            "release_id": "world-v3",
            "result": "pass",
            "tested_url": "http://127.0.0.1:8765/pages/interactive-map-v3.html?release-preview=world-v3",
            "completed_at": "2026-07-20T12:00:00Z",
        }
        write_json(self.browser_receipt, self.browser_receipt_payload)
        _browser_file_count, browser_tree_sha = (
            validate_release_readiness._browser_bundle_tree_evidence(browser_bundle)
        )
        self.browser_owner = {
            "path": validate_release_readiness.BROWSER_QA_BUNDLE_PATH.as_posix(),
            "receipt_sha256": validate_release_readiness._sha256_file(
                self.browser_receipt
            ),
            "tree_sha256": browser_tree_sha,
            "tested_url": self.browser_receipt_payload["tested_url"],
            "completed_at": self.browser_receipt_payload["completed_at"],
        }
        write_json(self.manifest, {"jobs": []})
        self.write_readiness("published")

        canonical = self.root / "docs" / "data" / "map" / "sheet-tiles-v3.json"
        compatibility = (
            self.root / "docs" / "data" / "map" / "region-rasters.json"
        )
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_bytes(b'{"release_id":"world-v3"}\n')
        compatibility.write_bytes(canonical.read_bytes())

        release_tree = (
            self.root
            / "docs"
            / "assets"
            / "images"
            / "maps"
            / "tiles"
            / "world-v3"
        )
        release_tree.mkdir(parents=True, exist_ok=True)
        for index in range(24):
            (release_tree / f"artifact-{index:02d}.bin").write_bytes(
                f"artifact-{index}\n".encode()
            )

        html = self.root / "docs" / "pages" / "interactive-map-v3.html"
        html.parent.mkdir(parents=True, exist_ok=True)
        html.write_text(
            """<!doctype html><html><head>
<meta name="ea-map-world-release" content="world-v3">
<meta name="ea-map-world-target-release" content="world-v3">
<meta name="ea-map-world-fallback-releases" content="world-v2,world-v1">
<meta name="ea-map-world-v3-manifest" content="../assets/images/maps/tiles/world-v3/metadata.json">
<meta name="ea-map-sheet-tile-index" content="../data/map/region-rasters.json">
<meta name="ea-map-cache-key" content="world-v3-unit-test">
</head><body></body></html>
""",
            encoding="utf-8",
        )

        self.strict_patch = mock.patch.object(
            validate_release_readiness.release_validator,
            "validate_release",
            return_value=strict_result(),
        )
        self.public_patch = mock.patch.object(
            validate_release_readiness.phase5,
            "validate_public_tile_release",
            return_value=public_result(),
        )
        self.browser_patch = mock.patch.object(
            validate_phase6_browser_qa,
            "validate_persisted_browser_qa_bundle",
            return_value=(self.browser_receipt_payload, []),
        )
        self.strict_validator = self.strict_patch.start()
        self.public_validator = self.public_patch.start()
        self.browser_validator = self.browser_patch.start()
        self.addCleanup(self.strict_patch.stop)
        self.addCleanup(self.public_patch.stop)
        self.addCleanup(self.browser_patch.stop)

    def write_readiness(self, status: str) -> None:
        declaration = {
            "$schema": "schemas/release-readiness.schema.json",
            "schema_version": "1.0.0",
            "status": status,
            "manifest_path": "world/map-production/production-manifest.json",
        }
        if status == "published":
            declaration["publication_receipt_path"] = (
                "world/map-production/releases/world-v3-publication-receipt.json"
            )
            declaration["browser_qa_bundle"] = self.browser_owner
        write_json(self.readiness, declaration)

    def write_receipt(self, **overrides):
        arguments = {
            "readiness_path": self.readiness,
            "readiness_schema_path": READINESS_SCHEMA,
            "receipt_schema_path": RECEIPT_SCHEMA,
            "repo_root": self.root,
            "published_by": PUBLISHER,
            "published_at": TIMESTAMP,
        }
        arguments.update(overrides)
        return write_publication_receipt.write_publication_receipt(**arguments)

    def test_writes_exact_recomputed_receipt_after_all_strict_gates(self):
        result = self.write_receipt()

        self.assertTrue(result["valid"])
        self.assertTrue(result["written"])
        receipt = json.loads(self.receipt.read_text(encoding="utf-8"))
        canonical = self.root / "docs" / "data" / "map" / "sheet-tiles-v3.json"
        release_tree = (
            self.root
            / "docs"
            / "assets"
            / "images"
            / "maps"
            / "tiles"
            / "world-v3"
        )
        file_count, tree_sha = validate_release_readiness._release_tree_evidence(
            release_tree
        )
        self.assertEqual(
            receipt["canonical_index"]["sha256"],
            validate_release_readiness._sha256_file(canonical),
        )
        self.assertEqual(receipt["release_tree"]["file_count"], file_count)
        self.assertEqual(receipt["release_tree"]["sha256"], tree_sha)
        self.assertEqual(receipt["browser_qa"], self.browser_owner)
        self.assertEqual(receipt["validation"]["bounded_sheet_count"], 23)
        self.assertEqual(receipt["validation"]["tile_count"], 1350)
        self.assertEqual(receipt["validation"]["tile_bytes"], 987654)
        self.assertEqual(receipt["runtime"]["active_release"], "world-v3")
        for call in self.strict_validator.call_args_list:
            self.assertTrue(call.kwargs["strict_release"])
            self.assertEqual(call.kwargs["sheet_minimum_state"], "published")

    def test_identical_existing_receipt_is_a_verified_noop(self):
        first = self.write_receipt()
        original = self.receipt.read_bytes()

        second = self.write_receipt(published_at=None)

        self.assertTrue(first["written"])
        self.assertFalse(second["written"])
        self.assertEqual(self.receipt.read_bytes(), original)
        self.assertEqual(second["published_at"], TIMESTAMP)

    def test_non_identical_existing_receipt_is_never_overwritten(self):
        self.write_receipt()
        original = self.receipt.read_bytes()

        with self.assertRaisesRegex(
            write_publication_receipt.PublicationReceiptError,
            "non-identical publication receipt",
        ):
            self.write_receipt(published_by="different-publisher")

        self.assertEqual(self.receipt.read_bytes(), original)

    def test_in_progress_readiness_cannot_fabricate_a_receipt(self):
        self.write_readiness("in-progress")

        with self.assertRaisesRegex(
            write_publication_receipt.PublicationReceiptError,
            "requires readiness status 'published'",
        ):
            self.write_receipt()

        self.assertFalse(self.receipt.exists())
        self.strict_validator.assert_not_called()
        self.public_validator.assert_not_called()

    def test_strict_published_manifest_failure_leaves_no_receipt(self):
        self.strict_validator.return_value = strict_result(
            valid=False,
            errors=["one sheet remains staging"],
            covered_sheets=22,
        )

        with self.assertRaisesRegex(
            write_publication_receipt.PublicationReceiptError,
            "one sheet remains staging",
        ):
            self.write_receipt()

        self.assertFalse(self.receipt.exists())

    def test_partial_alias_swap_leaves_no_receipt(self):
        compatibility = (
            self.root / "docs" / "data" / "map" / "region-rasters.json"
        )
        compatibility.write_bytes(compatibility.read_bytes() + b" ")

        with self.assertRaisesRegex(
            write_publication_receipt.PublicationReceiptError,
            "must be byte-identical",
        ):
            self.write_receipt()

        self.assertFalse(self.receipt.exists())

    def test_wrong_html_release_metadata_leaves_no_receipt(self):
        html = self.root / "docs" / "pages" / "interactive-map-v3.html"
        html.write_bytes(
            html.read_bytes().replace(
                b'content="world-v3"', b'content="world-v2"', 1
            )
        )

        with self.assertRaisesRegex(
            write_publication_receipt.PublicationReceiptError,
            "active_release",
        ):
            self.write_receipt()

        self.assertFalse(self.receipt.exists())

    def test_stale_publication_staging_artifact_leaves_no_receipt(self):
        stale = (
            self.root
            / "world"
            / "map-production"
            / "releases"
            / ".world-v3-publication-receipt.json.crashed.publishing"
        )
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("partial", encoding="utf-8")

        with self.assertRaisesRegex(
            write_publication_receipt.PublicationReceiptError,
            "staging artifacts",
        ):
            self.write_receipt()

        self.assertFalse(self.receipt.exists())

    def test_tampered_browser_qa_bundle_leaves_no_publication_receipt(self):
        bundle = self.root.joinpath(
            *validate_release_readiness.BROWSER_QA_BUNDLE_PATH.parts
        )
        (bundle / "tampered.txt").write_text("tamper\n", encoding="utf-8")

        with self.assertRaisesRegex(
            write_publication_receipt.PublicationReceiptError,
            "browser QA bundle tree_sha256 mismatch",
        ):
            self.write_receipt()

        self.assertFalse(self.receipt.exists())

    def test_published_at_cannot_precede_browser_qa_completion(self):
        with self.assertRaisesRegex(
            write_publication_receipt.PublicationReceiptError,
            "must not precede Phase 6 browser QA completion",
        ):
            self.write_receipt(published_at="2026-07-20T11:59:59Z")

        self.assertFalse(self.receipt.exists())

    def test_post_install_readiness_failure_removes_new_receipt(self):
        with mock.patch.object(
            validate_release_readiness,
            "validate_release_readiness",
            return_value={"valid": False, "errors": ["raced HTML mutation"]},
        ):
            with self.assertRaisesRegex(
                write_publication_receipt.PublicationReceiptError,
                "raced HTML mutation",
            ):
                self.write_receipt()

        self.assertFalse(self.receipt.exists())


if __name__ == "__main__":
    unittest.main()
