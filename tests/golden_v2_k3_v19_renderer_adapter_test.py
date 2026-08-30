from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import render_style_candidate_k3_golden_v2 as renderer  # noqa: E402


class GoldenV2K3V19RendererAdapterTest(unittest.TestCase):
    def test_config_and_exported_inventory_are_exact(self) -> None:
        config_path = REPO_ROOT / renderer.CONFIG_PATH
        self.assertEqual(
            hashlib.sha256(config_path.read_bytes()).hexdigest(),
            renderer.CONFIG_SHA256,
        )
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["seed"], renderer.SEED)
        self.assertEqual(config["donors"], list(renderer.EXPECTED_DONORS))
        self.assertEqual(config["controls"], list(renderer.EXPECTED_CONTROLS))
        self.assertEqual(config["expected_output"], renderer.EXPECTED_OUTPUT)
        self.assertEqual(
            config["replay_contract"],
            {
                "path": renderer.REPLAY_CONTRACT_PATH,
                "sha256": renderer.REPLAY_CONTRACT_SHA256,
            },
        )
        self.assertEqual(
            config["frozen_renderer"],
            {
                "path": renderer.FROZEN_RENDERER_PATH,
                "sha256": renderer.FROZEN_RENDERER_SHA256,
            },
        )

    def test_wrong_seed_and_inventory_fail_before_output(self) -> None:
        with self.assertRaisesRegex(renderer.GoldenV2RendererError, "--seed"):
            renderer.validate_invocation(
                REPO_ROOT,
                config=Path(renderer.CONFIG_PATH),
                seed="not-the-fixed-seed",
                donors=[Path(path) for path in renderer.EXPECTED_DONORS],
                controls=[Path(path) for path in renderer.EXPECTED_CONTROLS],
            )
        with self.assertRaisesRegex(renderer.GoldenV2RendererError, "--donor"):
            renderer.validate_invocation(
                REPO_ROOT,
                config=Path(renderer.CONFIG_PATH),
                seed=renderer.SEED,
                donors=[Path(path) for path in reversed(renderer.EXPECTED_DONORS)],
                controls=[Path(path) for path in renderer.EXPECTED_CONTROLS],
            )
        with self.assertRaisesRegex(renderer.GoldenV2RendererError, "--control"):
            renderer.validate_invocation(
                REPO_ROOT,
                config=Path(renderer.CONFIG_PATH),
                seed=renderer.SEED,
                donors=[Path(path) for path in renderer.EXPECTED_DONORS],
                controls=[Path(path) for path in renderer.EXPECTED_CONTROLS[:-1]],
            )
    def test_read_closed_runner_emits_only_exact_frozen_png(self) -> None:
        missing = [
            relative
            for relative in (
                renderer.CONFIG_PATH,
                *renderer.EXPECTED_DONORS,
                *renderer.EXPECTED_CONTROLS,
            )
            if not (REPO_ROOT / relative).is_file()
        ]
        self.assertEqual(missing, [], f"missing declared renderer authorities: {missing}")

        scratch_parent = REPO_ROOT / "tmp" / "test-temp"
        scratch_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="golden-v2-v19-adapter-", dir=scratch_parent
        ) as temporary:
            scratch = Path(temporary)
            output = scratch / "candidate.png"
            command = [
                sys.executable,
                str(SCRIPT_DIR / "run_golden_v2_renderer_read_closed.py"),
                "--workspace-root",
                str(REPO_ROOT),
                "--renderer",
                "scripts/map-production/render_style_candidate_k3_golden_v2.py",
                "--output",
                str(output),
            ]
            for relative in dict.fromkeys(
                (
                    renderer.CONFIG_PATH,
                    *renderer.EXPECTED_DONORS,
                    *renderer.EXPECTED_CONTROLS,
                )
            ):
                command.extend(("--allow-read", relative))
            command.extend(("--", "--config", renderer.CONFIG_PATH))
            command.extend(("--seed", renderer.SEED))
            for relative in renderer.EXPECTED_DONORS:
                command.extend(("--donor", relative))
            for relative in renderer.EXPECTED_CONTROLS:
                command.extend(("--control", relative))
            command.extend(("--output", str(output)))

            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
            )
            self.assertEqual(
                hashlib.sha256(output.read_bytes()).hexdigest(),
                renderer.EXPECTED_PNG_SHA256,
            )
            self.assertEqual(output.stat().st_size, renderer.EXPECTED_PNG_BYTES)
            self.assertEqual([path.name for path in scratch.iterdir()], ["candidate.png"])


if __name__ == "__main__":
    unittest.main()
