from __future__ import annotations

import ast
import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RECEIPT_PATH = ROOT / (
    "world/map-production/qa/"
    "style-candidate-k3-golden-v3-balanced-open-phase-v3-derivation-failure.json"
)
STATUS_PATH = ROOT / (
    "world/map-production/controls/style-candidate-k-v3-golden-v3/"
    "DEVELOPMENT-STATUS.md"
)
GENERATOR_PATH = ROOT / (
    "scripts/map-production/"
    "generate_style_candidate_k3_golden_v3_balanced_open_phase_v3.py"
)
RECEIPT_RAW_SHA256 = (
    "fff5e6a1e0b059a2deb98ec5dd206b326b53c576e7fc6bcdbaca671c387627ca"
)
ERROR_LINE = (
    "Balanced-open-phase-v3 derivation failed closed: construction lag "
    "certificate has too few lags for a support"
)
ERROR_LINE_SHA256 = (
    "e6548a0eee30577b3aede8854da514c4f29923751e3731f4784cc74ccc96745e"
)


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate receipt key: {key!r}")
        result[key] = value
    return result


def _load_receipt() -> dict[str, Any]:
    value = json.loads(
        RECEIPT_PATH.read_text(encoding="utf-8"),
        object_pairs_hook=_strict_object,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"forbidden JSON constant: {value}")
        ),
    )
    if not isinstance(value, dict):
        raise AssertionError("failure receipt is not an object")
    return value


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


class GoldenV3BalancedOpenFailureEvidenceTest(unittest.TestCase):
    def test_receipt_is_duplicate_free_canonical_json_with_fixed_raw_hash(self) -> None:
        raw = RECEIPT_PATH.read_bytes()
        receipt = _load_receipt()

        self.assertEqual(raw, _canonical_json(receipt))
        self.assertEqual(_digest(raw), RECEIPT_RAW_SHA256)
        self.assertEqual(receipt["schema_version"], "1.0.0")
        self.assertEqual(receipt["status"], "failed-closed-terminal")
        self.assertFalse(receipt["authority"])
        self.assertTrue(receipt["formal_use_forbidden"])

    def test_frozen_pr_and_ci_gates_and_source_hashes_are_exact(self) -> None:
        receipt = _load_receipt()
        generation = receipt["source_gates"]["generation_preregistration"]
        promotion = receipt["source_gates"]["promotion"]

        self.assertEqual(generation["pr_number"], 154)
        self.assertEqual(
            generation["commit_sha"],
            "ddb23055486683f031c72ab32cc71ac22f597e00",
        )
        self.assertEqual(
            generation["ci_gate"]["run_url"],
            "https://github.com/halc8312/SStory/actions/runs/33335397719",
        )
        self.assertEqual(promotion["pr_number"], 155)
        self.assertEqual(
            promotion["commit_sha"],
            "f76e4dc89734af68409da7eacb45b851c872f994",
        )
        self.assertEqual(
            promotion["ci_gate"]["run_url"],
            "https://github.com/halc8312/SStory/actions/runs/33343482403",
        )
        for gate in (generation, promotion):
            self.assertTrue(gate["ci_gate"]["required_before_emit"])
            self.assertEqual(
                gate["ci_gate"]["jobs"],
                [
                    {"conclusion": "success", "name": "Ubuntu"},
                    {"conclusion": "success", "name": "Windows"},
                ],
            )

        generation_files = {
            "authority_raw_sha256": (
                "world/map-production/spec/"
                "style-candidate-k3-golden-v3-balanced-open-"
                "phase-preregistration-v3.json"
            ),
            "generator_raw_sha256": (
                "scripts/map-production/"
                "generate_style_candidate_k3_golden_v3_"
                "balanced_open_phase_v3.py"
            ),
            "strict_audit_authority_raw_sha256": (
                "world/map-production/spec/"
                "style-candidate-k3-golden-v3-strict-audit-authority.json"
            ),
            "strict_auditor_raw_sha256": (
                "scripts/map-production/audit_style_candidate_k3_golden_v3.py"
            ),
            "synthetic_tests_raw_sha256": (
                "tests/golden_v3_balanced_open_phase_preregistration_test.py"
            ),
        }
        promotion_files = {
            "promotion_authority_raw_sha256": (
                "world/map-production/spec/"
                "style-candidate-k3-golden-v3-promotion-authority-v1.json"
            ),
            "promotion_implementation_raw_sha256": (
                "scripts/map-production/promote_style_candidate_k3_golden_v3.py"
            ),
            "promotion_tests_raw_sha256": (
                "tests/candidate_k3_golden_promotion_v3_test.py"
            ),
        }
        for field, relative in generation_files.items():
            self.assertEqual(
                _digest((ROOT / relative).read_bytes()),
                generation["source_hashes"][field],
            )
        for field, relative in promotion_files.items():
            self.assertEqual(
                _digest((ROOT / relative).read_bytes()),
                promotion["source_hashes"][field],
            )

        authority = json.loads(
            (ROOT / generation_files["authority_raw_sha256"]).read_text(
                encoding="utf-8"
            )
        )
        normalized = copy.deepcopy(authority)
        normalized["canonical_self_sha256"] = "0" * 64
        self.assertEqual(
            _digest(_canonical_json(normalized)),
            generation["source_hashes"]["authority_canonical_self_sha256"],
        )

    def test_each_platform_attempted_once_and_failed_with_exit_two(self) -> None:
        execution = _load_receipt()["execution"]
        cross_platform = execution["cross_platform"]

        self.assertEqual(cross_platform["platform_count"], 2)
        self.assertEqual(cross_platform["attempt_count"], 2)
        self.assertEqual(cross_platform["attempts_per_platform"], 1)
        self.assertFalse(cross_platform["retry_performed"])
        for platform in ("windows", "linux"):
            attempt = execution[platform]
            self.assertTrue(attempt["attempted_exactly_once"])
            self.assertEqual(attempt["exit_code"], 2)
            self.assertEqual(
                attempt["normalized_error_line_sha256"], ERROR_LINE_SHA256
            )

        windows = execution["windows"]
        self.assertEqual(
            windows["guard"]["path"],
            "tmp/map-production/"
            ".once-ddb23055486683f031c72ab32cc71ac22f597e00-"
            "windows-balanced-open-emit",
        )
        self.assertTrue(windows["guard"]["exists"])
        self.assertEqual(windows["guard"]["length_bytes"], 41)
        self.assertIsNone(windows["process_finish_timestamp_utc"])

        container = execution["linux"]["container"]
        self.assertEqual(
            container["name"],
            "sstory-golden-v3-balanced-open-emit-ddb2305-v2",
        )
        self.assertEqual(
            container["id"],
            "7e2a5dc891afa4616d0454f345f986052abb21f38937df62dc9189316005e77c",
        )
        self.assertEqual(
            container["image_id"],
            "sha256:8df1cf507e6fdc1d376843233d471f2f10bb3272b60a8482bed617c093d374aa",
        )
        self.assertEqual(container["state"]["status"], "exited")
        self.assertEqual(container["state"]["exit_code"], 2)
        self.assertEqual(container["restart_count"], 0)
        self.assertFalse(container["state"]["oom_killed"])
        self.assertEqual(container["state"]["error"], "")
        self.assertEqual(container["restart_policy"], "no")
        self.assertTrue(container["rootfs_read_only"])
        self.assertEqual(container["network_mode"], "none")
        self.assertEqual(execution["linux"]["pre_error_hash_checks"]["ok_count"], 5)

    def test_failure_location_is_explicitly_unknown_not_inferred(self) -> None:
        execution = _load_receipt()["execution"]
        locator = execution["failure_locator"]
        observed = execution["observed_failure"]
        expected_unknown = [
            "candidate_id",
            "body_index",
            "construction_stage",
            "support_erosion_px",
            "eligible_records",
        ]

        self.assertEqual(locator["unreported_fields"], expected_unknown)
        for field in expected_unknown:
            self.assertIsNone(locator[field])
            self.assertIsNone(observed[field])
        normalized_error = execution["normalized_error"]
        self.assertTrue(normalized_error["line_content_recorded"])
        self.assertEqual(normalized_error["line"], ERROR_LINE)
        self.assertEqual(_digest(ERROR_LINE.encode("utf-8")), ERROR_LINE_SHA256)
        self.assertEqual(
            normalized_error["sha256"], ERROR_LINE_SHA256
        )
        self.assertEqual(observed["certificate"], "lag_certificate")
        self.assertEqual(
            observed["condition"],
            "support_eligible < minimum_eligible_lags_per_support",
        )
        self.assertEqual(
            observed["minimum_eligible_lags_per_support"],
            4,
        )

    def test_failed_publication_closes_phase_and_forbids_downstream_claims(self) -> None:
        receipt = _load_receipt()
        phase = receipt["phase"]
        postconditions = receipt["execution"]["postconditions"]
        publication = receipt["publication_state"]

        self.assertTrue(phase["closed"])
        self.assertFalse(phase["retry_or_parameter_change_authorized"])
        self.assertFalse(phase["golden_designation_performed"])
        for artifact in ("output_directory", "staging_directory", "seal"):
            self.assertFalse(postconditions[artifact]["windows_exists"])
            self.assertFalse(postconditions[artifact]["linux_exists"])
        for claim in (
            "audit_started",
            "candidate_png_opened",
            "profile_seals_compared",
            "promotion_started",
            "visual_inspection_started",
        ):
            self.assertFalse(postconditions[claim])
        self.assertFalse(
            receipt["source_gates"]["promotion"]["merge_performed"]
        )
        self.assertEqual(
            publication,
            {
                "audit_performed": False,
                "in_memory_candidate_count": None,
                "promotion_performed": False,
                "published_candidate_file_count": 0,
                "seal_published": False,
                "view_performed": False,
            },
        )

    def test_closed_v3_requires_a_new_blind_ci_gated_successor(self) -> None:
        receipt = _load_receipt()

        self.assertTrue(receipt["phase"]["closed"])
        self.assertEqual(
            receipt["successor_constraints"],
            {
                "candidate_blind_frozen_preregistration_required": True,
                "exact_cross_platform_ci_before_emit_required": True,
                "phase_v3_authority_mutation_forbidden": True,
                "phase_v3_retry_forbidden": True,
                "phase_v3_tuning_forbidden": True,
                "successor_new_identity_required": True,
            },
        )

    def test_generator_ast_builds_before_publish_and_maps_errors_to_exit_two(self) -> None:
        tree = ast.parse(GENERATOR_PATH.read_text(encoding="utf-8"))
        main = next(
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "main"
        )
        emit_if = next(
            node
            for node in ast.walk(main)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Attribute)
            and node.test.attr == "emit"
        )
        emit_calls = {
            name: node.lineno
            for node in ast.walk(ast.Module(body=emit_if.body, type_ignores=[]))
            if isinstance(node, ast.Call)
            if (name := _call_name(node)) is not None
        }
        ordered = [
            "preflight",
            "_runtime_gate",
            "build_payloads",
            "publish_payloads_exclusive",
        ]
        self.assertEqual(sorted(ordered, key=emit_calls.__getitem__), ordered)

        guarded_try = next(node for node in main.body if isinstance(node, ast.Try))
        handler = next(
            item
            for item in guarded_try.handlers
            if isinstance(item.type, ast.Tuple)
            and {
                value.id
                for value in item.type.elts
                if isinstance(value, ast.Name)
            }
            == {"DerivationError", "OSError", "ValueError"}
        )
        exit_call = next(
            node
            for node in ast.walk(ast.Module(body=handler.body, type_ignores=[]))
            if isinstance(node, ast.Call) and _call_name(node) == "exit"
        )
        self.assertEqual(ast.literal_eval(exit_call.args[0]), 2)
        error_literals = "".join(
            value.value
            for value in ast.walk(exit_call.args[1])
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        )
        self.assertIn("Balanced-open-phase-v3 derivation failed closed: ", error_literals)

    def test_development_status_names_terminal_receipt_and_raw_hash(self) -> None:
        status = STATUS_PATH.read_text(encoding="utf-8")

        self.assertIn("## Balanced-open phase-v3 terminal derivation failure", status)
        self.assertIn(ERROR_LINE, status)
        self.assertIn(RECEIPT_PATH.relative_to(ROOT).as_posix(), status)
        self.assertIn(RECEIPT_RAW_SHA256, status)


if __name__ == "__main__":
    unittest.main()
