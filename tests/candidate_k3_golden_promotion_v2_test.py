from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, PngImagePlugin


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import build_phase5_assets as phase5  # noqa: E402
import audit_style_candidate_k3_golden_v2 as pixel_auditor  # noqa: E402
import create_qa_report  # noqa: E402
import promote_style_candidate_k3_golden_v2 as promotion  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def artifact(path: Path) -> dict[str, object]:
    with Image.open(path) as image:
        image.load()
        return {
            "path": relative(path),
            "sha256": digest(path),
            "bytes": path.stat().st_size,
            "mode": image.mode,
            "size": list(image.size),
        }


def reference(path: Path) -> dict[str, str]:
    return {"path": relative(path), "sha256": digest(path)}


class PromotionFixture:
    def __init__(self) -> None:
        source_parent = REPO_ROOT / "tmp" / "map-production"
        source_parent.mkdir(parents=True, exist_ok=True)
        self.source_temp = tempfile.TemporaryDirectory(
            prefix="k3-golden-v2-source-test-", dir=source_parent
        )
        self.persistent_temp = tempfile.TemporaryDirectory(
            prefix=".k3-golden-v2-test-", dir=REPO_ROOT
        )
        self.source_root = Path(self.source_temp.name)
        self.root = Path(self.persistent_temp.name)
        self.manifest = self.root / "production-manifest.json"
        self.paths = promotion.PromotionPaths(
            manifest=self.manifest,
            raw=self.root / "candidates" / "golden-raw.png",
            final=self.root / "candidates" / "golden-final.png",
            receipt=self.root / "prompts" / "promotion-receipt.json",
            root_review=self.root / "qa" / "root-review.json",
            audit=self.root / "qa" / "automated" / "audit.json",
            evidence_dir=self.root / "qa" / "evidence",
            final_receipt=self.root / "prompts" / "acceptance-receipt.json",
            blind_packet_dir=self.root
            / "world/map-production/qa/blind-packets/phase4-k3-v2",
        )
        self.write_manifest([])

        self.candidate = self.source_root / "candidate.png"
        width, height = promotion.EXPECTED_SIZE
        yy, xx = np.indices((height, width))
        checker = ((xx // 4 + yy // 4) % 2).astype(np.uint8)
        gray = np.where(checker == 0, 74, 186).astype(np.uint8)
        candidate_values = np.repeat(gray[..., None], 3, axis=2)
        candidate_values[400:448, 688:752] = np.uint8(130)
        candidate_values[424, 720] = np.uint8(92)
        self.candidate_image = Image.fromarray(candidate_values, mode="RGB")
        self.candidate_image.save(self.candidate, format="PNG", compress_level=9)
        self.replay = self.source_root / "replay.png"
        self.replay.write_bytes(self.candidate.read_bytes())
        self.renderer = self.root / "renderer.py"
        self.config = self.root / "renderer-config.json"
        self.donor = self.root / "donor-template.png"
        self.donor.write_bytes(self.candidate.read_bytes())
        self.renderer.write_text(
            "import argparse\n"
            "import shutil\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('--config', required=True)\n"
            "parser.add_argument('--seed', required=True)\n"
            "parser.add_argument('--donor', action='append', required=True)\n"
            "parser.add_argument('--control', action='append', required=True)\n"
            "parser.add_argument('--output', required=True)\n"
            "args = parser.parse_args()\n"
            "if args.seed != 'fixture-seed':\n"
            "    raise SystemExit('wrong seed')\n"
            "shutil.copyfile(args.donor[0], args.output)\n",
            encoding="utf-8",
        )
        self.config.write_text('{"seed":"fixture-seed"}\n', encoding="utf-8")

        audit_root = self.root / "pixel-audit"
        audit_root.mkdir(parents=True)
        self.audit_baseline = audit_root / "baseline.png"
        measurement = np.zeros((height, width), dtype=bool)
        measurement[412:436, 700:740] = True
        selected = np.zeros_like(measurement)
        for selected_y in (416, 428):
            for selected_x in (704, 712, 720, 728):
                selected[selected_y : selected_y + 2, selected_x : selected_x + 2] = (
                    True
                )
        baseline_values = candidate_values.copy()
        baseline_values[selected] = np.array([131, 130, 128], dtype=np.uint8)
        with Image.fromarray(baseline_values, mode="RGB") as baseline_image:
            baseline_image.save(
                self.audit_baseline,
                format="PNG",
                compress_level=9,
                optimize=False,
            )
        permission = measurement.copy()
        permission[404:408, 692:696] = True
        protected = np.zeros_like(measurement)
        protected[404:406, 692:694] = True
        road_calm = np.zeros_like(measurement)
        road_calm[406:408, 694:696] = True
        mask_values = {
            "measurement_inside": measurement,
            "texture_reference": measurement.copy(),
            "permission": permission,
            "protected_features": protected,
            "road_calm_18px": road_calm,
            "selected_components": selected,
        }
        self.audit_masks: dict[str, Path] = {}
        for name in pixel_auditor.MASK_NAMES:
            mask_path = audit_root / f"{name}.png"
            encoded = np.where(mask_values[name], 255, 0).astype(np.uint8)
            with Image.fromarray(encoded, mode="L") as image:
                image.save(mask_path, format="PNG", compress_level=9, optimize=False)
            self.audit_masks[name] = mask_path
        self.control = audit_root / "control.json"
        self.control.write_text(
            json.dumps(
                {
                    "schema_version": pixel_auditor.SCHEMA_VERSION,
                    "id": pixel_auditor.CONTROL_ID,
                    "algorithm": pixel_auditor.ALGORITHM,
                    "image": {"mode": "RGB", "size": [width, height]},
                    "candidate": {"sha256": digest(self.candidate)},
                    "baseline": {
                        "reproduction_role": pixel_auditor.BASELINE_REPRODUCTION_ROLE,
                        "sha256": digest(self.audit_baseline),
                    },
                    "masks": {
                        name: {
                            "reproduction_role": pixel_auditor.MASK_REPRODUCTION_ROLES[
                                name
                            ],
                            "path": self.audit_masks[name]
                            .relative_to(audit_root)
                            .as_posix(),
                            "sha256": digest(self.audit_masks[name]),
                        }
                        for name in pixel_auditor.MASK_NAMES
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.pixel_report = pixel_auditor.audit_candidate(
            self.candidate,
            self.audit_baseline,
            self.control,
            mask_bindings=self.audit_masks,
        )

        self.views: dict[str, Path] = {}
        for name, (crop, size) in promotion.VIEW_DEFINITIONS.items():
            working = (
                self.candidate_image.crop(crop)
                if crop is not None
                else self.candidate_image.copy()
            )
            rendered = working.resize(size, Image.Resampling.LANCZOS)
            path = self.source_root / f"view-{name}.png"
            rendered.save(path, format="PNG", compress_level=9)
            rendered.close()
            working.close()
            self.views[name] = path
        # Exercise the exact leak condition: the native source view uses the
        # candidate's identical PNG encoding and therefore identical SHA-256.
        self.views["native"].write_bytes(self.candidate.read_bytes())

        self.render_controls = [
            self.audit_baseline,
            self.control,
            *(self.audit_masks[name] for name in pixel_auditor.MASK_NAMES),
        ]

        self.emission_path = self.source_root / "emission.json"
        self.root_review_path = self.source_root / "root-review.json"
        self.emission = {
            "schema_version": "1.0.0",
            "id": "style-candidate-k-v3-generic-emission-test",
            "job_id": promotion.JOB_ID,
            "status": promotion.EMISSION_STATUS,
            "created_at": "2000-01-01T00:00:00Z",
            "temporary_review_only": True,
            "previously_accepted": False,
            "golden_accepted": False,
            "candidate": artifact(self.candidate),
            "views": {name: artifact(path) for name, path in self.views.items()},
            "metrics": copy.deepcopy(self.pixel_report["metrics"]),
            "geometry": copy.deepcopy(self.pixel_report["geometry"]),
            "identity": copy.deepcopy(self.pixel_report["identity"]),
            "determinism": {
                "independent_in_memory_builds": 2,
                "replay": artifact(self.replay),
                "byte_identical": True,
                "passed": True,
            },
            "reproduction": {
                "renderer": reference(self.renderer),
                "config": reference(self.config),
                "seed": "fixture-seed",
                "donors": [reference(self.donor)],
                "controls": [reference(path) for path in self.render_controls],
                "argv": [
                    promotion.PYTHON_RUNTIME_TOKEN,
                    relative(self.renderer),
                    "--config",
                    relative(self.config),
                    "--seed",
                    "fixture-seed",
                    "--donor",
                    relative(self.donor),
                    *(
                        item
                        for path in self.render_controls
                        for item in ("--control", relative(path))
                    ),
                    "--output",
                    promotion.OUTPUT_TOKEN,
                ],
                "environment": dict(promotion.FIXED_RENDERER_ENVIRONMENT),
                "timeout_seconds": promotion.RENDERER_TIMEOUT_SECONDS,
                "read_closure_runner": reference(promotion.READ_CLOSURE_RUNNER_PATH),
                "pixel_auditor": reference(Path(pixel_auditor.__file__).resolve()),
                "pixel_audit": {
                    "baseline": reference(self.audit_baseline),
                    "control": reference(self.control),
                    "masks": {
                        name: reference(self.audit_masks[name])
                        for name in pixel_auditor.MASK_NAMES
                    },
                },
            },
        }
        self.root_review = {
            "schema_version": "1.0.0",
            "job_id": promotion.JOB_ID,
            "created_at": "2000-01-01T00:10:00Z",
            "reviewer": "Root Vision Authority",
            "status": "complete",
            "review_mode": "root-authority",
            "candidate": reference(self.candidate),
            "native": reference(self.views["native"]),
            "review_views": [
                {
                    "id": name,
                    **reference(self.views[name]),
                    "complete": True,
                    "evidence": f"visually inspected {name}",
                }
                for name in promotion.VIEW_ORDER
            ],
            "immediate_failures": [
                {"id": identifier, "detected": False, "evidence": "not detected"}
                for identifier in promotion.PHASE4_IMMEDIATE_FAILURE_IDS
            ],
            "acceptance_threshold": 94,
            "total_score": 96,
            "decision": "accepted",
            "authorizes_blind_review": True,
            "golden_reference": False,
            "acceptance_inferred": False,
            "summary": "Root view pass authorizes blind review only.",
        }
        self.persist_emission()
        self.persist_root_review()

    def write_manifest(self, jobs: list[dict[str, object]]) -> None:
        self.manifest.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "project_id": "k3-golden-v2-test",
                    "map_id": "eternal-arcadia",
                    "coordinate_system": "EA-WORLD-1",
                    "jobs": jobs,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def persist_emission(self) -> None:
        self.emission_path.write_text(
            json.dumps(self.emission, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def persist_root_review(self) -> None:
        self.root_review_path.write_text(
            json.dumps(self.root_review, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def prepare(self) -> dict[str, object]:
        with mock.patch.object(
            promotion, "utc_now", return_value="2000-01-01T00:20:00Z"
        ):
            return promotion.prepare_promotion(
                emission_path=self.emission_path,
                root_review_path=self.root_review_path,
                authorized_by="Promotion Test",
                paths=self.paths,
            )

    def build_review(self, path: Path, reviewer: str) -> dict[str, object]:
        report = create_qa_report.build_report(
            promotion.JOB_ID,
            relative(
                self.paths.blind_packet_dir
                / next(self.paths.blind_packet_dir.glob("*.json")).name
            ),
            reviewer=reviewer,
            golden=True,
            threshold=94,
            image_sha256=digest(next(self.paths.blind_packet_dir.glob("*.json"))),
            review_mode="blind-independent",
        )
        report["status"] = "complete"
        report["decision"] = "accepted"
        report["created_at"] = "2000-01-01T00:30:00Z"
        report["summary"] = "Complete blind review of the exact final bytes."
        report["review_views"] = [
            {
                "id": identifier,
                "label": identifier,
                "complete": True,
                "evidence": "inspected independently",
                "notes": "packet",
            }
            for identifier in (
                *promotion.BLIND_PACKET_VIEW_IDS,
                "blind-audit-1",
                "blind-audit-2",
                "blind-audit-3",
                "blind-audit-4",
                "blind-audit-5",
            )
        ]
        report["immediate_failures"] = [
            {
                "id": identifier,
                "label": identifier,
                "detected": False,
                "evidence": "not detected",
            }
            for identifier in promotion.PHASE4_IMMEDIATE_FAILURE_IDS
        ]
        for failure in report["immediate_failures"]:
            failure["detected"] = False
            failure["evidence"] = "not detected"
        for score in report["scores"]:
            score["score"] = score["maximum"]
            score["notes"] = "meets contract"
        report["total_score"] = 100
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report) + "\n", encoding="utf-8")
        return report

    def cleanup(self) -> None:
        self.candidate_image.close()
        self.persistent_temp.cleanup()
        self.source_temp.cleanup()


class CandidateK3GoldenPromotionV2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = PromotionFixture()

    def tearDown(self) -> None:
        self.fixture.cleanup()

    @staticmethod
    def _refresh_existing_reference_hashes(value: object) -> None:
        """Rehash an otherwise coherent persistent graph after fixture tampering."""

        if isinstance(value, list):
            for item in value:
                CandidateK3GoldenPromotionV2Test._refresh_existing_reference_hashes(
                    item
                )
            return
        if not isinstance(value, dict):
            return
        for key, raw_path in tuple(value.items()):
            if not isinstance(raw_path, str):
                continue
            folded = key.casefold()
            if folded == "path":
                hash_key = "sha256"
            elif folded.endswith("_path"):
                hash_key = key[: -len("_path")] + "_sha256"
            else:
                continue
            if hash_key not in value:
                continue
            path = Path(raw_path)
            resolved = path if path.is_absolute() else REPO_ROOT / path
            if resolved.is_file():
                value[hash_key] = digest(resolved)
        for child in value.values():
            CandidateK3GoldenPromotionV2Test._refresh_existing_reference_hashes(child)

    def _rewrite_json_with_current_reference_hashes(self, path: Path) -> None:
        document = json.loads(path.read_text(encoding="utf-8"))
        self._refresh_existing_reference_hashes(document)
        path.write_text(json.dumps(document) + "\n", encoding="utf-8")

    @staticmethod
    def _inject_manifest_replace_fault(stack: ExitStack, scenario: str) -> None:
        original_replace = promotion.os.replace
        original_bind_file = promotion.bind_file

        def replace_then_append_whitespace(
            source: str | Path, destination: str | Path
        ) -> None:
            original_replace(source, destination)
            destination_path = Path(destination)
            destination_path.write_bytes(destination_path.read_bytes() + b" \n")
            raise OSError("injected error after replace and whitespace append")

        def replace_then_raise(source: str | Path, destination: str | Path) -> None:
            original_replace(source, destination)
            raise OSError("injected error after successful replace")

        def fail_without_replace(source: str | Path, destination: str | Path) -> None:
            del source, destination
            raise OSError("injected error before replace")

        def fail_post_replace_confirmation(
            raw_path: str | Path,
            *,
            label: str,
            trackable: bool = True,
        ) -> promotion.BoundArtifact:
            if label == "manifest post-replace confirmation":
                raise OSError("injected post-replace confirmation read failure")
            return original_bind_file(raw_path, label=label, trackable=trackable)

        if scenario == "replace-then-whitespace":
            replacement = replace_then_append_whitespace
        elif scenario == "replace-then-confirmation-read-failure":
            replacement = replace_then_raise
            stack.enter_context(
                mock.patch.object(
                    promotion,
                    "bind_file",
                    side_effect=fail_post_replace_confirmation,
                )
            )
        elif scenario == "replace-fails-before-commit":
            replacement = fail_without_replace
        else:  # pragma: no cover - test helper invariant
            raise AssertionError(f"unknown manifest replacement scenario: {scenario}")
        stack.enter_context(
            mock.patch.object(promotion.os, "replace", side_effect=replacement)
        )

    def test_interface_fixed_views_gates_and_known_donors(self) -> None:
        self.assertEqual(
            promotion.EMISSION_REQUIRED_KEYS,
            {
                "schema_version",
                "id",
                "job_id",
                "status",
                "created_at",
                "temporary_review_only",
                "previously_accepted",
                "golden_accepted",
                "candidate",
                "views",
                "metrics",
                "geometry",
                "identity",
                "determinism",
                "reproduction",
            },
        )
        self.assertEqual(
            promotion.SOURCE_ARTIFACT_KEYS,
            {"path", "sha256", "bytes", "mode", "size"},
        )
        self.assertEqual(
            set(self.fixture.emission), set(promotion.EMISSION_REQUIRED_KEYS)
        )
        self.assertEqual(
            set(self.fixture.root_review), set(promotion.ROOT_REVIEW_REQUIRED_KEYS)
        )
        self.assertEqual(
            promotion.VIEW_DEFINITIONS,
            {
                "native": (None, (1536, 1024)),
                "full25": (None, (384, 256)),
                "full50": (None, (768, 512)),
                "highland200": ((930, 0, 1536, 560), (1212, 1120)),
                "highland400": ((930, 0, 1536, 560), (2424, 2240)),
            },
        )
        self.assertEqual(promotion.ACCEPTANCE_THRESHOLD, 94)
        self.assertEqual(len(promotion.AUTOMATED_GATE_NAMES), 15)
        expected_donors = {
            "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882",
            "cce887425642637e0b031c4cc527f59c019f8693d233abbaaf257cadb700201e",
            "79d8396575b3a046e39656fbc614648e3e28a930cb3de4c64620d62c34bab656",
            "d576ed7ec0e5dfc7ff4806c7e35ebb93a4a7a25dc98abf1aaeee84c6af349aab",
            "8cb7792a725896bab24e032c8d9fadf8cbdf1bf1372f6901de182bf20f493b02",
            "152fe9231812e6acbc6292181de40e17fedceac3adc01a46a288fd873546d5ff",
            "e69deee1e5ba91c1bbcb9aa35dda036c8a7ae1cd07b90c94d1aede0beb957b4a",
            "4a1e7d35729546a4f111ccdf52e198fe936f8087b12e565757c9792e8945052f",
        }
        self.assertTrue(
            expected_donors <= set(promotion.KNOWN_NON_GOLDEN_SOURCE_SHA256)
        )
        default_blind_path = relative(
            promotion.DEFAULT_PATHS.blind_packet_dir
        ).casefold()
        self.assertFalse(
            any(
                token in default_blind_path
                for token in ("candidate", "lineage", "donor", "control", "generation")
            )
        )
        self.assertEqual(promotion.PYTHON_RUNTIME_TOKEN, "{python}")

        parser = promotion.build_parser()
        prepared = parser.parse_args(
            [
                "prepare",
                "--emission",
                "emission.json",
                "--root-review",
                "root.json",
                "--authorized-by",
                "Operator",
            ]
        )
        self.assertEqual(prepared.command, "prepare")
        accepted = parser.parse_args(
            [
                "accept",
                "--review-a",
                "a.json",
                "--review-b",
                "b.json",
                "--authorized-by",
                "Operator",
            ]
        )
        self.assertEqual(accepted.command, "accept")

    def test_prepare_persists_normalized_graph_and_stops_at_automated_qa(self) -> None:
        replay_root = REPO_ROOT / "tmp/map-production/k3-golden-v2-replay"
        before = set(replay_root.glob("run-*")) if replay_root.exists() else set()
        result = self.fixture.prepare()
        self.assertEqual(
            set(replay_root.glob("run-*")) if replay_root.exists() else set(), before
        )
        self.assertEqual(result["status"], "automated-qa")
        self.assertFalse(result["golden_accepted"])
        self.assertEqual(
            self.fixture.paths.raw.read_bytes(), self.fixture.paths.final.read_bytes()
        )
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["jobs"]), 1)
        job = manifest["jobs"][0]
        self.assertEqual(job["id"], promotion.JOB_ID)
        self.assertEqual(job["status"], "automated-qa")
        self.assertEqual(
            [event["state"] for event in job["history"]],
            ["planned", "inputs-ready", "generated", "automated-qa"],
        )
        self.assertNotIn("vision", job["qa"])
        self.assertEqual(
            {item["role"] for item in job["inputs"]},
            set(promotion.PREPARED_INPUT_ROLES),
        )
        for path in (
            self.fixture.paths.receipt,
            self.fixture.paths.root_review,
            self.fixture.paths.audit,
        ):
            document = json.loads(path.read_text(encoding="utf-8"))
            serialized = json.dumps(document)
            self.assertNotIn("tmp/", serialized)
            self.assertNotIn("F:/", serialized)
            promotion._assert_persistent_graph(document)
        receipt = json.loads(self.fixture.paths.receipt.read_text(encoding="utf-8"))
        self.assertFalse(
            receipt["vision_handoff"]["root_review_is_acceptance_authority"]
        )
        self.assertEqual(receipt["failed_gates"], [])
        self.assertTrue(all(receipt["automated_gates"].values()))
        self.assertFalse(self.fixture.paths.final_receipt.exists())

    def test_persistent_root_validator_preserves_the_exact_source_contract(
        self,
    ) -> None:
        self.fixture.prepare()
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        job = manifest["jobs"][0]
        roles = promotion._prepared_role_bindings(job)
        master = promotion._bind_trackable_record(
            job["master"], label="test persistent master"
        )
        views = {
            name: roles[f"root-review-view-{name}"] for name in promotion.VIEW_ORDER
        }
        document = json.loads(
            self.fixture.paths.root_review.read_text(encoding="utf-8")
        )
        mutations = {
            "keys must be exact": lambda value: value.__setitem__("unreviewed", True),
            "score must be 94..100": lambda value: value.__setitem__(
                "total_score", 101
            ),
            "summary must be non-empty": lambda value: value.__setitem__(
                "summary", " "
            ),
            "lacks evidence": lambda value: value["immediate_failures"][0].__setitem__(
                "evidence", ""
            ),
        }
        for expected, mutate in mutations.items():
            with self.subTest(expected=expected):
                forged = copy.deepcopy(document)
                mutate(forged)
                with self.assertRaisesRegex(
                    promotion.K3GoldenPromotionV2Error, expected
                ):
                    promotion._validate_normalized_root(
                        forged, candidate=master, views=views
                    )

    def test_accept_rejects_rehashed_blind_png_with_lineage_metadata(self) -> None:
        self.fixture.prepare()
        packet_path = next(self.fixture.paths.blind_packet_dir.glob("*.json"))
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        for view_record in packet["views"]:
            binding = promotion._bind_trackable_record(
                view_record, label=f"test anonymous view {view_record['id']}"
            )
            promotion._validate_anonymous_view_png(binding, view_id=view_record["id"])

        native_record = packet["views"][0]
        native_path = REPO_ROOT / native_record["path"]
        with Image.open(native_path) as opened:
            native_pixels = opened.copy()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("sstory-blind-contract", "phase4-v2")
        metadata.add_text("sstory-blind-view", "native")
        metadata.add_text("lineage", "forbidden-source")
        try:
            native_pixels.save(
                native_path,
                format="PNG",
                compress_level=9,
                optimize=False,
                pnginfo=metadata,
            )
        finally:
            native_pixels.close()
        native_record["sha256"] = digest(native_path)
        packet_payload = promotion._json_bytes(packet)
        packet_sha = hashlib.sha256(packet_payload).hexdigest()
        forged_packet = packet_path.with_name(f"{packet_sha}.json")
        forged_packet.write_bytes(packet_payload)
        packet_artifact = reference(forged_packet)

        receipt = json.loads(self.fixture.paths.receipt.read_text(encoding="utf-8"))
        receipt["blind_packet"] = packet_artifact
        self.fixture.paths.receipt.write_text(
            json.dumps(receipt) + "\n", encoding="utf-8"
        )
        audit = json.loads(self.fixture.paths.audit.read_text(encoding="utf-8"))
        audit["blind_packet"] = packet_artifact
        audit["provenance_receipt"]["sha256"] = digest(self.fixture.paths.receipt)
        self.fixture.paths.audit.write_text(json.dumps(audit) + "\n", encoding="utf-8")
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        rewritten = {
            "blind-review-packet": packet_artifact,
            "promotion-provenance": {"sha256": digest(self.fixture.paths.receipt)},
            "persistent-automated-audit": {"sha256": digest(self.fixture.paths.audit)},
        }
        for item in manifest["jobs"][0]["inputs"]:
            if item["role"] in rewritten:
                item.update(rewritten[item["role"]])
        self.fixture.manifest.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionV2Error,
            "anonymous PNG metadata/chunk contract",
        ):
            promotion.accept_promotion(
                review_paths=[
                    self.fixture.root / "unused-review-a.json",
                    self.fixture.root / "unused-review-b.json",
                ],
                authorized_by="Acceptance Test",
                paths=self.fixture.paths,
            )

    def test_prepare_rejects_generated_blind_png_with_lineage_metadata(self) -> None:
        original_png_info = promotion.PngImagePlugin.PngInfo

        class LineagePngInfo(original_png_info):
            def add_text(
                self,
                key: object,
                value: object,
                zip: bool = False,
            ) -> None:
                super().add_text(key, value, zip=zip)
                if key == "sstory-blind-view":
                    super().add_text("lineage", "forbidden-source", zip=False)

        with mock.patch.object(promotion.PngImagePlugin, "PngInfo", LineagePngInfo):
            with self.assertRaisesRegex(
                promotion.K3GoldenPromotionV2Error,
                "metadata/chunk contract",
            ):
                self.fixture.prepare()

        self.assertFalse(self.fixture.paths.raw.exists())
        self.assertFalse(self.fixture.paths.final.exists())
        self.assertFalse(self.fixture.paths.receipt.exists())
        self.assertEqual(
            json.loads(self.fixture.manifest.read_text(encoding="utf-8"))["jobs"], []
        )

    def test_old_probe_or_extra_source_schema_is_not_a_promotion_contract(self) -> None:
        self.fixture.emission["probe"] = {
            "status": "passed",
            "note": "legacy producer-only evidence",
        }
        self.fixture.persist_emission()
        original_manifest = self.fixture.manifest.read_bytes()
        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionV2Error, "keys must be exact"
        ):
            self.fixture.prepare()
        self.assertEqual(self.fixture.manifest.read_bytes(), original_manifest)
        self.assertFalse(self.fixture.paths.raw.exists())

    def test_reproduction_argv_is_portable_exact_and_seed_bound(self) -> None:
        original_manifest = self.fixture.manifest.read_bytes()
        # Keep the cases as a list because all must fail through the same
        # exact-grammar diagnostic.
        mutations = [
            (
                lambda reproduction: reproduction["argv"].__setitem__(
                    0, sys.executable
                ),
                "portable declared-input grammar",
            ),
            (
                lambda reproduction: reproduction["argv"].insert(
                    -2, "world/map-production/unbound-input.png"
                ),
                "portable declared-input grammar",
            ),
            (
                lambda reproduction: reproduction.__setitem__("seed", "other-seed"),
                "portable declared-input grammar",
            ),
            (
                lambda reproduction: reproduction["environment"].__setitem__(
                    "UNDECLARED_PARENT_VALUE", "forbidden"
                ),
                "fixed renderer environment",
            ),
            (
                lambda reproduction: reproduction.__setitem__(
                    "timeout_seconds", promotion.RENDERER_TIMEOUT_SECONDS + 1
                ),
                "timeout_seconds",
            ),
        ]
        for mutate, pattern in mutations:
            with self.subTest(pattern=pattern):
                reproduction = self.fixture.emission["reproduction"]
                original = copy.deepcopy(reproduction)
                mutate(reproduction)
                self.fixture.persist_emission()
                with self.assertRaisesRegex(
                    promotion.K3GoldenPromotionV2Error,
                    pattern,
                ):
                    self.fixture.prepare()
                self.fixture.emission["reproduction"] = original
        self.assertEqual(self.fixture.manifest.read_bytes(), original_manifest)

    def test_prepare_rejects_incomplete_mocked_pixel_audit_report(self) -> None:
        forged_report = {
            "metrics": copy.deepcopy(self.fixture.emission["metrics"]),
            "geometry": copy.deepcopy(self.fixture.emission["geometry"]),
            "identity": copy.deepcopy(self.fixture.emission["identity"]),
            "gates": {"forged-only": True},
            "failed_gates": [],
            "passed": True,
        }
        with mock.patch.object(
            pixel_auditor, "audit_candidate", return_value=forged_report
        ):
            with self.assertRaisesRegex(
                promotion.K3GoldenPromotionV2Error,
                "pixel audit report keys must be exact",
            ):
                self.fixture.prepare()
        self.assertFalse(self.fixture.paths.raw.exists())
        self.assertEqual(
            json.loads(self.fixture.manifest.read_text(encoding="utf-8"))["jobs"], []
        )

    def test_prepare_rejects_renderer_read_of_undeclared_workspace_data(self) -> None:
        undeclared = self.fixture.root / "undeclared-renderer-input.png"
        undeclared.write_bytes(self.fixture.candidate.read_bytes())
        renderer = self.fixture.renderer.read_text(encoding="utf-8")
        renderer = renderer.replace(
            "shutil.copyfile(args.donor[0], args.output)",
            f"open({relative(undeclared)!r}, 'rb').read(1)\n"
            "shutil.copyfile(args.donor[0], args.output)",
        )
        self.fixture.renderer.write_text(renderer, encoding="utf-8")
        self.fixture.emission["reproduction"]["renderer"] = reference(
            self.fixture.renderer
        )
        self.fixture.persist_emission()

        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionV2Error,
            "fresh deterministic replay 1 failed",
        ):
            self.fixture.prepare()
        self.assertFalse(self.fixture.paths.raw.exists())
        self.assertEqual(
            json.loads(self.fixture.manifest.read_text(encoding="utf-8"))["jobs"], []
        )

    def test_prepare_rejects_external_reads_writes_discovery_and_network(
        self,
    ) -> None:
        original_renderer = self.fixture.renderer.read_text(encoding="utf-8")
        # The suite deliberately pins TEMP below the repository on Windows so
        # Python subprocesses stay on one drive.  Anchor this fixture at the
        # repository parent instead of assuming the process TEMP is external.
        with tempfile.TemporaryDirectory(
            prefix="golden-v2-external-", dir=REPO_ROOT.parent
        ) as temporary:
            external_root = Path(temporary).resolve()
            with self.assertRaises(ValueError):
                external_root.relative_to(REPO_ROOT.resolve())
            external_input = external_root / "undeclared-input.png"
            external_input.write_bytes(self.fixture.candidate.read_bytes())
            external_code = external_root / "undeclared-source.py"
            external_code.write_text("SECRET = 1\n", encoding="utf-8")
            external_output = external_root / "undeclared-output.bin"
            external_directory = external_root / "undeclared-directory"
            cases = {
                "read": f"open({str(external_input)!r}, 'rb').read(1)",
                "read-code": f"open({str(external_code)!r}, 'rb').read(1)",
                "write": f"open({str(external_output)!r}, 'wb').write(b'x')",
                "mkdir": f"__import__('os').mkdir({str(external_directory)!r})",
                "listdir": "__import__('os').listdir('.')",
                "scandir": "list(__import__('os').scandir('.'))",
                "socket": "__import__('socket').socket()",
            }
            for operation, statement in cases.items():
                with self.subTest(operation=operation):
                    renderer = original_renderer.replace(
                        "shutil.copyfile(args.donor[0], args.output)",
                        f"{statement}\nshutil.copyfile(args.donor[0], args.output)",
                    )
                    self.fixture.renderer.write_text(renderer, encoding="utf-8")
                    self.fixture.emission["reproduction"]["renderer"] = reference(
                        self.fixture.renderer
                    )
                    self.fixture.persist_emission()
                    with self.assertRaisesRegex(
                        promotion.K3GoldenPromotionV2Error,
                        "fresh deterministic replay 1 failed",
                    ):
                        self.fixture.prepare()
                    self.assertFalse(self.fixture.paths.raw.exists())
                    self.assertFalse(external_output.exists())
                    self.assertFalse(external_directory.exists())
                    self.assertEqual(
                        json.loads(self.fixture.manifest.read_text(encoding="utf-8"))[
                            "jobs"
                        ],
                        [],
                    )

    def test_prepare_rejects_nonregular_device_and_linux_proc_reads(self) -> None:
        original_renderer = self.fixture.renderer.read_text(encoding="utf-8")
        pseudo_files = [os.devnull]
        if sys.platform.startswith("linux"):
            pseudo_files.extend(("/proc/self/environ", "/dev/urandom"))
        for pseudo_file in pseudo_files:
            with self.subTest(pseudo_file=pseudo_file):
                renderer = original_renderer.replace(
                    "shutil.copyfile(args.donor[0], args.output)",
                    f"open({pseudo_file!r}, 'rb').read(1)\n"
                    "shutil.copyfile(args.donor[0], args.output)",
                )
                self.fixture.renderer.write_text(renderer, encoding="utf-8")
                self.fixture.emission["reproduction"]["renderer"] = reference(
                    self.fixture.renderer
                )
                self.fixture.persist_emission()
                with self.assertRaisesRegex(
                    promotion.K3GoldenPromotionV2Error,
                    "fresh deterministic replay 1 failed",
                ):
                    self.fixture.prepare()
                self.assertFalse(self.fixture.paths.raw.exists())
                self.assertEqual(
                    json.loads(self.fixture.manifest.read_text(encoding="utf-8"))[
                        "jobs"
                    ],
                    [],
                )

    def test_renderer_environment_is_fixed_and_numpy_cv2_pillow_import(self) -> None:
        renderer = self.fixture.renderer.read_text(encoding="utf-8")
        renderer = (
            "import cv2\nimport numpy\nimport PIL\nimport os\n"
            + renderer.replace(
                "shutil.copyfile(args.donor[0], args.output)",
                "assert os.environ.get('PYTHONHASHSEED') == '0'\n"
                "assert os.environ.get('TZ') == 'UTC'\n"
                "assert 'SSTORY_UNDECLARED_PARENT_ENV' not in os.environ\n"
                "shutil.copyfile(args.donor[0], args.output)",
            )
        )
        self.fixture.renderer.write_text(renderer, encoding="utf-8")
        self.fixture.emission["reproduction"]["renderer"] = reference(
            self.fixture.renderer
        )
        self.fixture.persist_emission()

        with mock.patch.dict(
            os.environ,
            {"SSTORY_UNDECLARED_PARENT_ENV": "must-not-cross-boundary"},
        ):
            result = self.fixture.prepare()
        self.assertEqual(result["status"], "automated-qa")
        self.assertEqual(result["manifest_commit"]["cleanup_status"], "complete")

    def test_second_fresh_replay_failure_cleans_every_temporary_run(self) -> None:
        replay_root = REPO_ROOT / "tmp/map-production/k3-golden-v2-replay"
        before = set(replay_root.glob("run-*")) if replay_root.exists() else set()
        original_run = promotion.subprocess.run
        calls = 0

        def fail_second(*args: object, **kwargs: object) -> object:
            nonlocal calls
            command = args[0]
            if not (
                isinstance(command, list)
                and len(command) >= 2
                and command[0] == sys.executable
                and command[1] == relative(promotion.READ_CLOSURE_RUNNER_PATH)
            ):
                return original_run(*args, **kwargs)
            calls += 1
            if calls == 2:
                raise promotion.subprocess.CalledProcessError(9, command)
            return original_run(*args, **kwargs)

        with mock.patch.object(promotion.subprocess, "run", side_effect=fail_second):
            with self.assertRaisesRegex(
                promotion.K3GoldenPromotionV2Error,
                "fresh deterministic replay 2 failed",
            ):
                self.fixture.prepare()
        self.assertEqual(calls, 2)
        self.assertEqual(
            set(replay_root.glob("run-*")) if replay_root.exists() else set(), before
        )
        self.assertFalse(self.fixture.paths.raw.exists())
        self.assertEqual(
            json.loads(self.fixture.manifest.read_text(encoding="utf-8"))["jobs"], []
        )

    def test_fresh_replay_timeout_fails_closed_and_cleans_temporary_run(self) -> None:
        replay_root = REPO_ROOT / "tmp/map-production/k3-golden-v2-replay"
        before = set(replay_root.glob("run-*")) if replay_root.exists() else set()
        original_run = promotion.subprocess.run

        def timeout_renderer(*args: object, **kwargs: object) -> object:
            command = args[0]
            if (
                isinstance(command, list)
                and len(command) >= 2
                and command[0] == sys.executable
                and command[1] == relative(promotion.READ_CLOSURE_RUNNER_PATH)
            ):
                self.assertEqual(
                    kwargs.get("timeout"), promotion.RENDERER_TIMEOUT_SECONDS
                )
                raise promotion.subprocess.TimeoutExpired(
                    command, promotion.RENDERER_TIMEOUT_SECONDS
                )
            return original_run(*args, **kwargs)

        with mock.patch.object(
            promotion.subprocess, "run", side_effect=timeout_renderer
        ):
            with self.assertRaisesRegex(
                promotion.K3GoldenPromotionV2Error,
                "timed out after 300 seconds",
            ):
                self.fixture.prepare()
        self.assertEqual(
            set(replay_root.glob("run-*")) if replay_root.exists() else set(), before
        )
        self.assertFalse(self.fixture.paths.raw.exists())
        self.assertEqual(
            json.loads(self.fixture.manifest.read_text(encoding="utf-8"))["jobs"], []
        )

    def test_accept_rejects_coherently_rehashed_master_tamper(self) -> None:
        self.fixture.prepare()
        with Image.open(self.fixture.paths.final) as opened:
            tampered = opened.copy()
        original = tampered.getpixel((0, 0))
        tampered.putpixel((0, 0), tuple(255 - value for value in original))
        tampered.save(self.fixture.paths.final, format="PNG", compress_level=9)
        tampered_payload = self.fixture.paths.final.read_bytes()
        self.fixture.paths.raw.write_bytes(tampered_payload)
        promotion._replay_output_path(self.fixture.paths).write_bytes(tampered_payload)
        promotion._second_replay_output_path(self.fixture.paths).write_bytes(
            tampered_payload
        )
        for name, destination in promotion._view_output_paths(
            self.fixture.paths
        ).items():
            view = promotion._expected_view(tampered, name)
            try:
                view.save(destination, format="PNG", compress_level=9)
            finally:
                view.close()
        tampered.close()

        # Rewrite every downstream path/SHA edge.  The immutable pixel-audit
        # control still binds the original candidate, so coherent graph
        # rehashing cannot bless modified master pixels.
        for document_path in (
            self.fixture.paths.root_review,
            self.fixture.paths.receipt,
            self.fixture.paths.audit,
            self.fixture.manifest,
        ):
            self._rewrite_json_with_current_reference_hashes(document_path)

        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionV2Error,
            "candidate SHA-256 does not match audit control",
        ):
            promotion.accept_promotion(
                review_paths=[
                    self.fixture.root / "unused-review-a.json",
                    self.fixture.root / "unused-review-b.json",
                ],
                authorized_by="Acceptance Test",
                paths=self.fixture.paths,
            )

    def test_accept_rejects_coherently_rehashed_renderer_output_drift(self) -> None:
        self.fixture.prepare()
        renderer = self.fixture.renderer.read_text(encoding="utf-8")
        self.fixture.renderer.write_text(
            renderer.replace(
                "shutil.copyfile(args.donor[0], args.output)",
                "open(args.output, 'wb').write(b'not-a-png')",
            ),
            encoding="utf-8",
        )
        for document_path in (
            self.fixture.paths.receipt,
            self.fixture.paths.audit,
            self.fixture.manifest,
        ):
            self._rewrite_json_with_current_reference_hashes(document_path)

        # Re-hashing a tracked renderer is valid new provenance when its
        # output remains byte-identical.  This mutation changes output bytes,
        # so the two fresh executions must reject it despite a coherent graph.
        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionV2Error,
            "fresh deterministic replay 1 is not a readable PNG",
        ):
            promotion.accept_promotion(
                review_paths=[
                    self.fixture.root / "unused-review-a.json",
                    self.fixture.root / "unused-review-b.json",
                ],
                authorized_by="Acceptance Test",
                paths=self.fixture.paths,
            )

    def test_prepare_replaces_only_nonaccepted_exact_job(self) -> None:
        old = {
            "id": promotion.JOB_ID,
            "sheet_id": promotion.SHEET_ID,
            "status": "rejected",
            "bounds": {"west": 0, "south": 0, "east": 1, "north": 1},
            "zoom": {"min": 0, "max": 0, "native": 0},
            "history": [
                {"state": "planned", "at": "2026-07-23T00:00:00Z", "actor": "old"},
                {"state": "rejected", "at": "2026-07-23T00:01:00Z", "actor": "old"},
            ],
        }
        self.fixture.write_manifest([old])
        self.fixture.prepare()
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["jobs"]), 1)
        self.assertEqual(manifest["jobs"][0]["status"], "automated-qa")

    def test_prepare_fixed_gate_root_and_prior_acceptance_fail_closed(self) -> None:
        original_manifest = self.fixture.manifest.read_bytes()

        metric_cases = {
            "coverage_50": 359,
            "coverage_25": 333,
            "quiet_fraction": 0.904999,
            "dash_bundle_pairs": 1,
            "orientation_coherence": 0.160001,
        }
        for field, bad_value in metric_cases.items():
            with self.subTest(metric=field):
                original = self.fixture.emission["metrics"][field]
                self.fixture.emission["metrics"][field] = bad_value
                self.fixture.persist_emission()
                with self.assertRaisesRegex(
                    promotion.K3GoldenPromotionV2Error,
                    "independently recomputed pixels",
                ):
                    self.fixture.prepare()
                self.fixture.emission["metrics"][field] = original
                self.fixture.persist_emission()
                self.assertEqual(self.fixture.manifest.read_bytes(), original_manifest)
                self.assertFalse(self.fixture.paths.raw.exists())

        self.fixture.root_review["review_views"][2]["complete"] = False
        self.fixture.persist_root_review()
        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionV2Error, "order/completion"
        ):
            self.fixture.prepare()
        self.fixture.root_review["review_views"][2]["complete"] = True
        self.fixture.persist_root_review()

        accepted = {
            "id": "already-accepted-test",
            "sheet_id": "accepted-test",
            "status": "accepted",
            "bounds": {"west": 0, "south": 0, "east": 1, "north": 1},
            "zoom": {"min": 0, "max": 0, "native": 0},
            "master": {
                "path": relative(self.fixture.candidate),
                "sha256": digest(self.fixture.candidate),
                "width": 1536,
                "height": 1024,
            },
            "qa": {
                "automated": {
                    "status": "passed",
                    "report_path": relative(self.fixture.emission_path),
                },
                "vision": {
                    "decision": "accepted",
                    "score": 94,
                    "report_path": relative(self.fixture.root_review_path),
                    "reviewer": "old",
                    "reviewed_at": "2026-07-23T00:00:00Z",
                },
            },
            "history": [
                {"state": state, "at": "2026-07-23T00:00:00Z", "actor": "old"}
                for state in (
                    "planned",
                    "inputs-ready",
                    "generated",
                    "automated-qa",
                    "vision-qa",
                    "accepted",
                )
            ],
        }
        self.fixture.write_manifest([accepted])
        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionV2Error, "previously accepted"
        ):
            self.fixture.prepare()
        self.assertFalse(self.fixture.paths.raw.exists())

    def test_prepare_rejects_donor_bad_view_and_nonidentical_replay(self) -> None:
        original_manifest = self.fixture.manifest.read_bytes()
        donor = (
            REPO_ROOT
            / "world/map-production/style-assets/k3-v169-direction-neutral-microterrain-donor.png"
        )
        self.fixture.candidate.write_bytes(donor.read_bytes())
        self.fixture.emission["candidate"] = artifact(self.fixture.candidate)
        self.fixture.persist_emission()
        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionV2Error, "known non-Golden"
        ):
            self.fixture.prepare()
        self.assertEqual(self.fixture.manifest.read_bytes(), original_manifest)

        # Restore the candidate and then make one declared view valid PNG bytes
        # that are not the canonical resize.
        self.fixture.candidate_image.save(
            self.fixture.candidate, format="PNG", compress_level=9
        )
        self.fixture.emission["candidate"] = artifact(self.fixture.candidate)
        bad_view = Image.new("RGB", promotion.VIEW_DEFINITIONS["full25"][1], (1, 2, 3))
        bad_view.save(self.fixture.views["full25"], format="PNG")
        bad_view.close()
        self.fixture.emission["views"]["full25"] = artifact(
            self.fixture.views["full25"]
        )
        self.fixture.persist_emission()
        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionV2Error, "not the exact canonical"
        ):
            self.fixture.prepare()

        # Restore the view, then provide a second valid but non-identical build.
        crop, size = promotion.VIEW_DEFINITIONS["full25"]
        working = (
            self.fixture.candidate_image.copy()
            if crop is None
            else self.fixture.candidate_image.crop(crop)
        )
        rendered = working.resize(size, Image.Resampling.LANCZOS)
        rendered.save(self.fixture.views["full25"], format="PNG")
        working.close()
        rendered.close()
        self.fixture.emission["views"]["full25"] = artifact(
            self.fixture.views["full25"]
        )
        replay = Image.new("RGB", promotion.EXPECTED_SIZE, (3, 2, 1))
        replay.save(self.fixture.replay, format="PNG")
        replay.close()
        self.fixture.emission["determinism"]["replay"] = artifact(self.fixture.replay)
        self.fixture.persist_emission()
        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionV2Error, "not byte-identical"
        ):
            self.fixture.prepare()
        self.assertEqual(self.fixture.manifest.read_bytes(), original_manifest)
        self.assertFalse(self.fixture.paths.raw.exists())

    def test_accept_rejects_nonindependent_incomplete_or_failing_reviews(self) -> None:
        self.fixture.prepare()
        review_a = self.fixture.root / "qa" / "review-a.json"
        review_b = self.fixture.root / "qa" / "review-b.json"
        base_a = self.fixture.build_review(
            review_a, "independent-vision-review-a/Reviewer Alpha"
        )
        base_b = self.fixture.build_review(
            review_b, "independent-vision-review-b/Reviewer Beta"
        )
        prepared_manifest = self.fixture.manifest.read_bytes()

        def attempt(report: dict[str, object], pattern: str | None = None) -> None:
            review_b.write_text(json.dumps(report) + "\n", encoding="utf-8")
            context = (
                self.assertRaisesRegex(promotion.K3GoldenPromotionV2Error, pattern)
                if pattern
                else self.assertRaises(promotion.K3GoldenPromotionV2Error)
            )
            with context:
                promotion.accept_promotion(
                    review_paths=[review_a, review_b],
                    authorized_by="Acceptance Test",
                    paths=self.fixture.paths,
                )
            self.assertEqual(self.fixture.manifest.read_bytes(), prepared_manifest)
            self.assertFalse(self.fixture.paths.final_receipt.exists())

        duplicate = copy.deepcopy(base_b)
        duplicate["reviewer"] = (
            "independent-vision-review-b/Ｒｅｖｉｅｗｅｒ\u3000Ａｌｐｈａ"
        )
        attempt(duplicate, "canonically distinct")
        incomplete = copy.deepcopy(base_b)
        incomplete["review_views"][0]["complete"] = False
        attempt(incomplete)
        failure = copy.deepcopy(base_b)
        failure["immediate_failures"][0]["detected"] = True
        attempt(failure, "immediate failure")
        low = copy.deepcopy(base_b)
        low["scores"][-1]["score"] = 3
        low["total_score"] = 93
        attempt(low, "at least 94")
        stale = copy.deepcopy(base_b)
        stale["image_sha256"] = "0" * 64
        attempt(stale, "image_sha256")
        review_a.write_text(json.dumps(base_a) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(promotion.K3GoldenPromotionV2Error, "exactly two"):
            promotion.accept_promotion(
                review_paths=[review_a],
                authorized_by="Acceptance Test",
                paths=self.fixture.paths,
            )

    def test_two_valid_reviews_accept_write_receipt_and_bind_phase5(self) -> None:
        self.assertEqual(
            digest(self.fixture.candidate), digest(self.fixture.views["native"])
        )
        prepared = self.fixture.prepare()
        packet_path = REPO_ROOT / prepared["blind_packet"]["path"]
        packet_text = packet_path.read_text(encoding="utf-8")
        packet = json.loads(packet_text)
        candidate_sha = digest(self.fixture.paths.final)
        self.assertNotIn(candidate_sha, packet_text)
        self.assertNotIn(relative(self.fixture.paths.final), packet_text)
        self.assertEqual(
            len({item["sha256"] for item in packet["views"]}),
            len(promotion.BLIND_PACKET_VIEW_IDS),
        )
        self.assertNotIn(candidate_sha, {item["sha256"] for item in packet["views"]})
        review_a = self.fixture.root / "qa" / "review-a.json"
        review_b = self.fixture.root / "qa" / "review-b.json"
        self.fixture.build_review(
            review_a, "independent-vision-review-a/Reviewer Alpha"
        )
        self.fixture.build_review(review_b, "independent-vision-review-b/Reviewer Beta")
        result = promotion.accept_promotion(
            review_paths=[review_a, review_b],
            authorized_by="Acceptance Test",
            paths=self.fixture.paths,
        )
        self.assertEqual(result["status"], "accepted")
        self.assertTrue(self.fixture.paths.final_receipt.is_file())
        acceptance = json.loads(
            self.fixture.paths.final_receipt.read_text(encoding="utf-8")
        )
        self.assertEqual(acceptance["status"], "accepted")
        self.assertEqual(len(acceptance["reviews"]), 2)
        promotion._assert_persistent_graph(acceptance)

        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        job = manifest["jobs"][0]
        self.assertEqual(job["status"], "accepted")
        self.assertEqual(
            [event["state"] for event in job["history"]][-2:],
            ["vision-qa", "accepted"],
        )
        self.assertEqual(
            {
                item["role"]
                for item in job["inputs"]
                if item["role"].startswith("independent-vision-review-")
            },
            set(promotion.INDEPENDENT_VISION_REVIEW_ROLES),
        )
        evidence = phase5.verify_manifest_golden_style(
            job["master"], self.fixture.manifest
        )
        self.assertEqual(evidence["job_id"], promotion.JOB_ID)
        self.assertEqual(len(evidence["manifest_vision_reports"]), 2)

    def test_accept_maps_reversed_review_arguments_by_declared_role(self) -> None:
        self.fixture.prepare()
        review_a = self.fixture.root / "qa" / "review-a.json"
        review_b = self.fixture.root / "qa" / "review-b.json"
        self.fixture.build_review(
            review_a, "independent-vision-review-a/Reviewer Alpha"
        )
        self.fixture.build_review(review_b, "independent-vision-review-b/Reviewer Beta")
        result = promotion.accept_promotion(
            review_paths=[review_b, review_a],
            authorized_by="Acceptance Test",
            paths=self.fixture.paths,
        )
        self.assertEqual(
            result["reviewers"],
            [
                "independent-vision-review-a/reviewer alpha",
                "independent-vision-review-b/reviewer beta",
            ],
        )
        evidence = phase5.verify_manifest_golden_style(
            artifact(self.fixture.paths.final), self.fixture.manifest
        )
        self.assertEqual(len(evidence["manifest_vision_reports"]), 2)

    def test_accept_rejects_future_dated_blind_review(self) -> None:
        self.fixture.prepare()
        review_a = self.fixture.root / "qa" / "review-a.json"
        review_b = self.fixture.root / "qa" / "review-b.json"
        self.fixture.build_review(
            review_a, "independent-vision-review-a/Reviewer Alpha"
        )
        report_b = self.fixture.build_review(
            review_b, "independent-vision-review-b/Reviewer Beta"
        )
        report_b["created_at"] = "2999-01-01T00:00:00Z"
        review_b.write_text(json.dumps(report_b) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionV2Error, "must not predate a blind review"
        ):
            promotion.accept_promotion(
                review_paths=[review_a, review_b],
                authorized_by="Acceptance Test",
                paths=self.fixture.paths,
            )
        self.assertFalse(self.fixture.paths.final_receipt.exists())

    def test_late_mutation_rolls_back_prepare_and_accept_receipt(self) -> None:
        original_validate = promotion._validate_projected_manifest
        original_manifest = self.fixture.manifest.read_bytes()

        def tamper_prepare(path: Path, projected: dict[str, object]) -> None:
            original_validate(path, projected)
            self.fixture.paths.evidence_dir.joinpath(
                "review-highland400.png"
            ).write_bytes(b"late mutation")

        with mock.patch.object(
            promotion, "_validate_projected_manifest", side_effect=tamper_prepare
        ):
            with self.assertRaisesRegex(promotion.K3GoldenPromotionV2Error, "changed"):
                self.fixture.prepare()
        self.assertEqual(self.fixture.manifest.read_bytes(), original_manifest)
        self.assertFalse(self.fixture.paths.raw.exists())

        self.fixture.prepare()
        review_a = self.fixture.root / "qa" / "review-a.json"
        review_b = self.fixture.root / "qa" / "review-b.json"
        self.fixture.build_review(
            review_a, "independent-vision-review-a/Reviewer Alpha"
        )
        self.fixture.build_review(review_b, "independent-vision-review-b/Reviewer Beta")
        prepared_manifest = self.fixture.manifest.read_bytes()
        audit_bytes = self.fixture.paths.audit.read_bytes()

        def tamper_accept(path: Path, projected: dict[str, object]) -> None:
            original_validate(path, projected)
            self.fixture.paths.audit.write_bytes(audit_bytes + b"late mutation")

        try:
            with mock.patch.object(
                promotion, "_validate_projected_manifest", side_effect=tamper_accept
            ):
                with self.assertRaisesRegex(
                    promotion.K3GoldenPromotionV2Error, "changed"
                ):
                    promotion.accept_promotion(
                        review_paths=[review_a, review_b],
                        authorized_by="Acceptance Test",
                        paths=self.fixture.paths,
                    )
        finally:
            self.fixture.paths.audit.write_bytes(audit_bytes)
        self.assertEqual(self.fixture.manifest.read_bytes(), prepared_manifest)
        self.assertFalse(self.fixture.paths.final_receipt.exists())

    def test_manifest_replace_tri_state_prepare_retains_only_indeterminate_evidence(
        self,
    ) -> None:
        scenarios = (
            (
                "replace-then-whitespace",
                "post-replace-manifest-bytes-indeterminate",
            ),
            (
                "replace-then-confirmation-read-failure",
                "post-replace-manifest-read-failed",
            ),
            ("replace-fails-before-commit", None),
        )
        for index, (scenario, unknown_reason) in enumerate(scenarios):
            fixture = self.fixture if index == 0 else PromotionFixture()
            try:
                with self.subTest(scenario=scenario), ExitStack() as stack:
                    self._inject_manifest_replace_fault(stack, scenario)
                    if unknown_reason is None:
                        with self.assertRaisesRegex(
                            OSError, "injected error before replace"
                        ):
                            fixture.prepare()
                    else:
                        with self.assertRaises(
                            promotion.ManifestCommitStateUnknownError
                        ) as caught:
                            fixture.prepare()

                manifest = json.loads(fixture.manifest.read_text(encoding="utf-8"))
                if unknown_reason is not None:
                    self.assertEqual(caught.exception.status, "unknown")
                    self.assertEqual(caught.exception.reason, unknown_reason)
                    self.assertEqual(caught.exception.cleanup_failures, ())
                    self.assertEqual(manifest["jobs"][0]["status"], "automated-qa")
                    self.assertTrue(fixture.paths.raw.is_file())
                    self.assertTrue(fixture.paths.final.is_file())
                    self.assertTrue(fixture.paths.receipt.is_file())
                    self.assertTrue(fixture.paths.audit.is_file())
                    for item in manifest["jobs"][0]["inputs"]:
                        evidence = REPO_ROOT / item["path"]
                        self.assertTrue(evidence.is_file(), item["role"])
                        self.assertEqual(digest(evidence), item["sha256"], item["role"])
                else:
                    self.assertEqual(manifest["jobs"], [])
                    self.assertFalse(fixture.paths.raw.exists())
                    self.assertFalse(fixture.paths.final.exists())
                    self.assertFalse(fixture.paths.receipt.exists())
                    self.assertFalse(fixture.paths.audit.exists())

                retried = fixture.prepare()
                self.assertEqual(retried["status"], "automated-qa")
                self.assertEqual(
                    retried["manifest_commit"]["cleanup_status"], "complete"
                )
                retried_manifest = json.loads(
                    fixture.manifest.read_text(encoding="utf-8")
                )
                self.assertEqual(len(retried_manifest["jobs"]), 1)
                self.assertEqual(retried_manifest["jobs"][0]["status"], "automated-qa")
            finally:
                if fixture is not self.fixture:
                    fixture.cleanup()

    def test_manifest_replace_tri_state_accept_preserves_phase5_truth(
        self,
    ) -> None:
        scenarios = (
            (
                "replace-then-whitespace",
                "post-replace-manifest-bytes-indeterminate",
            ),
            (
                "replace-then-confirmation-read-failure",
                "post-replace-manifest-read-failed",
            ),
            ("replace-fails-before-commit", None),
        )
        for index, (scenario, unknown_reason) in enumerate(scenarios):
            fixture = self.fixture if index == 0 else PromotionFixture()
            try:
                fixture.prepare()
                review_a = fixture.root / "qa" / "review-a.json"
                review_b = fixture.root / "qa" / "review-b.json"
                fixture.build_review(
                    review_a, "independent-vision-review-a/Reviewer Alpha"
                )
                fixture.build_review(
                    review_b, "independent-vision-review-b/Reviewer Beta"
                )
                prepared_manifest = fixture.manifest.read_bytes()

                with self.subTest(scenario=scenario), ExitStack() as stack:
                    self._inject_manifest_replace_fault(stack, scenario)
                    if unknown_reason is None:
                        with self.assertRaisesRegex(
                            OSError, "injected error before replace"
                        ):
                            promotion.accept_promotion(
                                review_paths=[review_a, review_b],
                                authorized_by="Acceptance Test",
                                paths=fixture.paths,
                            )
                    else:
                        with self.assertRaises(
                            promotion.ManifestCommitStateUnknownError
                        ) as caught:
                            promotion.accept_promotion(
                                review_paths=[review_a, review_b],
                                authorized_by="Acceptance Test",
                                paths=fixture.paths,
                            )

                manifest = json.loads(fixture.manifest.read_text(encoding="utf-8"))
                if unknown_reason is not None:
                    self.assertEqual(caught.exception.status, "unknown")
                    self.assertEqual(caught.exception.reason, unknown_reason)
                    self.assertEqual(caught.exception.cleanup_failures, ())
                    self.assertTrue(fixture.paths.final_receipt.is_file())
                    receipt_sha256 = digest(fixture.paths.final_receipt)
                    job = manifest["jobs"][0]
                    self.assertEqual(job["status"], "accepted")
                    evidence = phase5.verify_manifest_golden_style(
                        job["master"], fixture.manifest
                    )
                    self.assertEqual(evidence["job_id"], promotion.JOB_ID)

                    # A blind retry reports that reconciliation already found
                    # acceptance, while preserving the receipt and Phase 5 truth.
                    with self.assertRaisesRegex(
                        promotion.K3GoldenPromotionV2Error,
                        "threshold-94 automated-qa",
                    ):
                        promotion.accept_promotion(
                            review_paths=[review_a, review_b],
                            authorized_by="Acceptance Test",
                            paths=fixture.paths,
                        )
                    self.assertEqual(
                        digest(fixture.paths.final_receipt), receipt_sha256
                    )
                    reconciled = phase5.verify_manifest_golden_style(
                        job["master"], fixture.manifest
                    )
                    self.assertEqual(reconciled["job_id"], promotion.JOB_ID)
                else:
                    self.assertEqual(fixture.manifest.read_bytes(), prepared_manifest)
                    self.assertEqual(manifest["jobs"][0]["status"], "automated-qa")
                    self.assertFalse(fixture.paths.final_receipt.exists())
                    retried = promotion.accept_promotion(
                        review_paths=[review_a, review_b],
                        authorized_by="Acceptance Test",
                        paths=fixture.paths,
                    )
                    self.assertEqual(retried["status"], "accepted")
                    accepted_manifest = json.loads(
                        fixture.manifest.read_text(encoding="utf-8")
                    )
                    accepted_job = accepted_manifest["jobs"][0]
                    evidence = phase5.verify_manifest_golden_style(
                        accepted_job["master"], fixture.manifest
                    )
                    self.assertEqual(evidence["job_id"], promotion.JOB_ID)
            finally:
                if fixture is not self.fixture:
                    fixture.cleanup()

    def test_lock_cleanup_failure_after_commit_preserves_prepare_and_accept(
        self,
    ) -> None:
        lock = self.fixture.manifest.with_name(
            f".{self.fixture.manifest.name}.k3-golden-v2.lock"
        )
        original_unlink = Path.unlink

        def fail_manifest_lock_unlink(
            target: Path, *args: object, **kwargs: object
        ) -> None:
            if target == lock:
                raise PermissionError("injected manifest lock cleanup failure")
            original_unlink(target, *args, **kwargs)

        with mock.patch.object(Path, "unlink", fail_manifest_lock_unlink):
            prepared = self.fixture.prepare()
        self.assertEqual(
            prepared["manifest_commit"],
            {
                "status": "committed",
                "cleanup_status": "debris",
                "debris": [relative(lock)],
                "cleanup_failures": ["manifest-lock-unlink"],
            },
        )
        self.assertTrue(lock.is_file())
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["jobs"][0]["status"], "automated-qa")
        for item in manifest["jobs"][0]["inputs"]:
            evidence = REPO_ROOT / item["path"]
            self.assertTrue(evidence.is_file(), item["role"])
            self.assertEqual(digest(evidence), item["sha256"], item["role"])
        original_unlink(lock, missing_ok=True)

        review_a = self.fixture.root / "qa" / "review-a.json"
        review_b = self.fixture.root / "qa" / "review-b.json"
        self.fixture.build_review(
            review_a, "independent-vision-review-a/Reviewer Alpha"
        )
        self.fixture.build_review(review_b, "independent-vision-review-b/Reviewer Beta")
        with mock.patch.object(Path, "unlink", fail_manifest_lock_unlink):
            accepted = promotion.accept_promotion(
                review_paths=[review_a, review_b],
                authorized_by="Acceptance Test",
                paths=self.fixture.paths,
            )
        try:
            self.assertEqual(accepted["manifest_commit"]["status"], "committed")
            self.assertEqual(accepted["manifest_commit"]["cleanup_status"], "debris")
            self.assertEqual(accepted["manifest_commit"]["debris"], [relative(lock)])
            self.assertTrue(lock.is_file())
            self.assertTrue(self.fixture.paths.final_receipt.is_file())
            manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
            self.assertEqual(manifest["jobs"][0]["status"], "accepted")
            evidence = phase5.verify_manifest_golden_style(
                manifest["jobs"][0]["master"], self.fixture.manifest
            )
            self.assertEqual(evidence["job_id"], promotion.JOB_ID)
        finally:
            original_unlink(lock, missing_ok=True)

    def test_interrupted_prepare_and_accept_resume_from_identical_immutable_files(
        self,
    ) -> None:
        def interrupted(*args: object, **kwargs: object) -> None:
            raise KeyboardInterrupt("simulated process interruption")

        with mock.patch.object(
            promotion, "_conditional_manifest_replace", side_effect=interrupted
        ):
            with self.assertRaises(KeyboardInterrupt):
                self.fixture.prepare()
        self.assertTrue(self.fixture.paths.receipt.exists())
        self.assertEqual(
            json.loads(self.fixture.manifest.read_text(encoding="utf-8"))["jobs"], []
        )

        self.fixture.prepare()
        review_a = self.fixture.root / "qa" / "review-a.json"
        review_b = self.fixture.root / "qa" / "review-b.json"
        self.fixture.build_review(
            review_a, "independent-vision-review-a/Reviewer Alpha"
        )
        self.fixture.build_review(review_b, "independent-vision-review-b/Reviewer Beta")
        with mock.patch.object(
            promotion, "_conditional_manifest_replace", side_effect=interrupted
        ):
            with self.assertRaises(KeyboardInterrupt):
                promotion.accept_promotion(
                    review_paths=[review_a, review_b],
                    authorized_by="Acceptance Test",
                    paths=self.fixture.paths,
                )
        self.assertTrue(self.fixture.paths.final_receipt.exists())
        result = promotion.accept_promotion(
            review_paths=[review_a, review_b],
            authorized_by="Acceptance Test",
            paths=self.fixture.paths,
        )
        self.assertEqual(result["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
