import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import validate_phase6_browser_qa as browser_qa  # noqa: E402
import run_phase6_browser_qa as browser_runner  # noqa: E402
import validate_release_readiness as readiness_gate  # noqa: E402


STARTED = "2026-07-22T03:00:00Z"
COMPLETED = "2026-07-22T03:04:00Z"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_visual_png(path: Path, size: tuple[int, int]) -> None:
    image = Image.new("RGB", size, color=(32, 48, 64))
    draw = ImageDraw.Draw(image)
    width, height = size
    for row in range(4):
        for column in range(4):
            draw.rectangle(
                (
                    column * width // 4,
                    row * height // 4,
                    (column + 1) * width // 4,
                    (row + 1) * height // 4,
                ),
                fill=(
                    24 + column * 45,
                    36 + row * 40,
                    48 + (row + column) * 20,
                ),
            )
    image.save(path, format="PNG")


def interaction_evidence(scenario_id: str, inputs: dict) -> dict:
    mobile = scenario_id == "mobile"
    search_source = next(
        artifact
        for artifact in inputs["runtime_dependencies"]["artifacts"]
        if artifact["path"] == browser_qa.SEARCH_ORACLE_SOURCE.as_posix()
    )
    focus_steps = [
        {
            "key": key,
            "expected_selector": selector,
            "selector": selector,
            "active": True,
            "visible": True,
            "within_viewport": True,
            "enabled": True,
            "not_inert": True,
            "actionable": True,
        }
        for key, selector in browser_qa.FOCUS_TRAVERSAL_STEPS[scenario_id]
    ]
    focus_transfers = [
        {
            "cause": cause,
            "expected_selector": selector,
            "selector": selector,
            "active": True,
            "visible": True,
            "within_viewport": True,
            "enabled": True,
            "not_inert": True,
            "actionable": True,
        }
        for cause, selector in browser_qa.FOCUS_TRANSFERS[scenario_id]
    ]
    return {
        "required": True,
        "mode": scenario_id,
        "focus_traversal": {
            "known_start": {"selector": "body", "active": True},
            "steps": focus_steps,
            "transfers": focus_transfers,
        },
        "keyboard": {
            "focused": True,
            "pan_key": "ArrowRight",
            "center_before": {"lat": -100.0, "lng": 200.0},
            "center_after": {"lat": -100.0, "lng": 290.0},
            "zoom_key": "Equal",
            "zoom_before": -2.0,
            "zoom_after": -1.5,
        },
        "search": {
            "query": "アストラリス王宮",
            "surface_available": True,
            "result_count": 1,
            "active_option_id": "map-search-option-0",
            "active_option_label": "アストラリス王宮",
            "active_option_key": browser_qa.SEARCH_TARGET_KEY,
            "selected_entry_key": browser_qa.SEARCH_TARGET_KEY,
            "selected_entry_kind": "poi",
            "selected_label": "アストラリス王宮",
            "result_selected": True,
            "oracle_source": search_source,
            "expected_target": {"lat": -4380.0, "lng": 5100.0},
            "runtime_target": {"lat": -4380.0, "lng": 5100.0},
            "zoom_inputs": {
                "kind": "poi",
                "fit_zoom": 0.25,
                "current_zoom": -2.0,
                "max_zoom": 8.0,
            },
            "expected_zoom": 4.0,
            "final_center": {"lat": -4300.0, "lng": 5000.0},
            "final_bounds": {
                "south": -5000.0,
                "west": 4000.0,
                "north": -3000.0,
                "east": 6000.0,
            },
            "final_zoom": 4.0,
            "target_visible": True,
            "center_target_ratio": 0.05,
            "popup": {
                "open": True,
                "lat": -4380.0,
                "lng": 5100.0,
                "label_visible": True,
            },
            "moveend_count": 2,
            "quiescent_ms": 350.0,
            "map_animating": False,
            "map_focused_after_selection": mobile,
        },
        "layer_panel": {
            "open_trigger": "Enter",
            "trigger_actionable": True,
            "opened": True,
            "close_button_focused_after_open": True,
            "close_trigger": "Enter",
            "closed": True,
            "focus_restored": True,
        },
        "mobile_search_focus": {
            "required": mobile,
            "open_trigger": "Enter",
            "opened": mobile,
            "input_focused": mobile,
            "close_button_focused": mobile,
            "close_trigger": "Enter",
            "closed": mobile,
            "focus_restored": mobile,
        },
        "errors": [],
    }


class Phase6BrowserQaReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".phase6-browser-qa-test-", dir=REPO_ROOT
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "output" / "playwright" / "world-v3"
        self.output.mkdir(parents=True)
        schema_target = self.root / "schema.json"
        shutil.copyfile(browser_qa.DEFAULT_SCHEMA, schema_target)
        self.schema = schema_target
        self._build_release_candidate()
        self.inputs = browser_qa.capture_release_candidate_inputs(self.root)
        self.receipt = self._build_receipt()

    def _path(self, relative):
        return self.root.joinpath(*relative.parts)

    def _build_release_candidate(self):
        write_json(
            self._path(browser_qa.READINESS),
            {
                "schema_version": "1.0.0",
                "status": "release-candidate",
                "manifest_path": browser_qa.PRODUCTION_MANIFEST.as_posix(),
            },
        )
        sheet_ids = [
            "sheet_world",
            browser_qa.ROYAL_PARENT_ID,
            browser_qa.ROYAL_CHILD_ID,
            *(f"sheet_fixture_{index:02d}" for index in range(3, 23)),
        ]
        sheets = []
        entries = []
        jobs = []
        release_tree = self._path(browser_qa.RELEASE_TREE)
        for index, sheet_id in enumerate(sheet_ids):
            sheets.append(
                {
                    "id": sheet_id,
                    "review_status": "accepted",
                    "bounds": [0, 0, 10000, 10000],
                }
            )
            jobs.append({"sheet_id": sheet_id, "status": "staging"})
            if sheet_id == "sheet_world":
                metadata = release_tree / "metadata.json"
                tile = release_tree / "0" / "0" / "0.webp"
                manifest_url = "../../assets/images/maps/tiles/world-v3/metadata.json"
            else:
                metadata = release_tree / "sheets" / sheet_id / "metadata.json"
                zoom = "4" if sheet_id == browser_qa.ROYAL_CHILD_ID else "3"
                tile = release_tree / "sheets" / sheet_id / zoom / "0" / "0.webp"
                manifest_url = (
                    "../../assets/images/maps/tiles/world-v3/sheets/"
                    f"{sheet_id}/metadata.json"
                )
            write_json(
                metadata,
                {"release_id": "world-v3", "map_id": sheet_id, "fixture": index},
            )
            tile.parent.mkdir(parents=True, exist_ok=True)
            tile.write_bytes(f"fixture-tile-{sheet_id}".encode("ascii"))
            entries.append(
                {
                    "sheet_id": sheet_id,
                    "status": "staging",
                    "review_status": "accepted",
                    "manifest_url": manifest_url,
                    "manifest_sha256": sha256(metadata),
                }
            )
        write_json(self._path(browser_qa.CATALOG), {"sheets": sheets})
        runtime_index = {
            "release_id": "world-v3",
            "bounded_sheet_count": 23,
            "root": entries[0],
            "sheets": entries[1:],
        }
        canonical = self._path(browser_qa.CANONICAL_INDEX)
        compatibility = self._path(browser_qa.COMPATIBILITY_INDEX)
        write_json(canonical, runtime_index)
        compatibility.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(canonical, compatibility)
        write_json(self._path(browser_qa.PRODUCTION_MANIFEST), {"jobs": jobs})
        html = self._path(browser_qa.HTML)
        html.parent.mkdir(parents=True, exist_ok=True)
        html.write_text("<html><body>world-v3 preview fixture</body></html>\n", encoding="utf-8")
        for relative in browser_qa.RUNTIME_DEPENDENCIES:
            target = self._path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative == browser_qa.SEARCH_ORACLE_SOURCE:
                write_json(
                    target,
                    [
                        {
                            "id": browser_qa.SEARCH_TARGET_ID,
                            "name": browser_qa.SEARCH_TARGET_LABEL,
                            "position": {"x": 5100, "y": 4380, "z": 0},
                            "status": "active",
                        }
                    ],
                )
            elif target.suffix == ".json":
                write_json(target, {"fixture": relative.as_posix()})
            else:
                target.write_text(f"/* fixture {relative.as_posix()} */\n", encoding="utf-8")
        for relative in browser_qa.HARNESS_ARTIFACTS:
            target = self._path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT.joinpath(*relative.parts), target)

    def _evidence(self, scenario_id, kind, content):
        filenames = {
            "screenshot": "screenshot.png",
            "snapshot": "snapshot.md",
            "console": "console.json",
            "network": "network.json",
            "driver": "scenario-driver.js",
            "config": "playwright-cli.json",
        }
        path = self.output / "scenarios" / scenario_id / filenames[kind]
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "screenshot":
            write_visual_png(path, content)
        elif isinstance(content, dict):
            write_json(path, content)
        elif isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_bytes(content)
        return {
            "path": path.relative_to(self.output).as_posix(),
            "sha256": sha256(path),
        }

    def _scenario(self, scenario_id):
        width, height = browser_qa.EXPECTED_VIEWPORTS[scenario_id]
        assertions = {
            name: True for name in browser_qa.SCENARIO_ASSERTIONS[scenario_id]
        }
        metrics = {
            "selected_release": "world-v3",
            "index_release_id": "world-v3",
            "bounded_sheet_count": 23,
            "browser_user_agent": "Mozilla/5.0 Chrome/140.0.0.0 Safari/537.36",
            "served_html_sha256": self.inputs["html"]["sha256"],
            "served_index_sha256": self.inputs["compatibility_index"]["sha256"],
            "served_world_manifest_sha256": self.inputs["world_manifest"]["sha256"],
            "served_runtime_sha256": {
                item["path"]: item["sha256"]
                for item in self.inputs["runtime_dependencies"]["artifacts"]
            },
            "served_probe_manifest_sha256": {},
            "configured_delay_ms": 500,
            "timeout_ms": 30000,
            "base_tiles_decoded": True,
            "base_tile_fallback_used": False,
        }
        if scenario_id in browser_qa.INTERACTION_SCENARIOS:
            metrics["interaction_evidence"] = interaction_evidence(
                scenario_id, self.inputs
            )
        diagnostics = {
            "console_errors": [],
            "page_errors": [],
            "network_errors": [],
            "expected_console_warnings": [],
            "expected_network_failures": [],
        }
        if scenario_id == "slow_tiles":
            metrics.update(
                {"delay_ms": 500, "delayed_tile_requests": 3, "elapsed_ms": 2100}
            )
            metrics["served_probe_manifest_sha256"] = {
                browser_qa.ROYAL_PARENT_ID: self.inputs["royal_probe"]["parent"][
                    "manifest"
                ]["sha256"]
            }
        if scenario_id == "royal_child_failure":
            metrics.update(
                {
                    "injected_status": 503,
                    "failed_child_id": browser_qa.ROYAL_CHILD_ID,
                    "nearest_parent_id": browser_qa.ROYAL_PARENT_ID,
                    "failure_response_count": 1,
                    "parent_status_before": "ready",
                    "parent_status_after": "ready",
                    "failed_sheet_ids": [browser_qa.ROYAL_CHILD_ID],
                    "visible_sheet_ids": [browser_qa.ROYAL_PARENT_ID],
                }
            )
            diagnostics["expected_console_warnings"] = [
                "[InteractiveMapV3] Sheet tiles unavailable; retaining nearest parent "
                "sheet_continent_elysion: sheet_region_royal_capital_region"
            ]
            royal_event = {
                "kind": "response",
                "method": "GET",
                "url": (
                    "http://127.0.0.1:8765/assets/images/maps/tiles/world-v3/"
                    "sheets/sheet_region_royal_capital_region/4/0/0.webp"
                ),
                "status": 503,
            }
            diagnostics["expected_network_failures"] = [
                json.dumps(royal_event, ensure_ascii=False, separators=(",", ":"))
            ]
            metrics["served_probe_manifest_sha256"] = {
                browser_qa.ROYAL_PARENT_ID: self.inputs["royal_probe"]["parent"][
                    "manifest"
                ]["sha256"],
                browser_qa.ROYAL_CHILD_ID: self.inputs["royal_probe"]["child"][
                    "manifest"
                ]["sha256"],
            }
        tile_sheet = (
            browser_qa.ROYAL_PARENT_ID
            if scenario_id in {"slow_tiles", "royal_child_failure"}
            else None
        )
        if tile_sheet:
            tile_path = self._path(browser_qa.RELEASE_TREE) / "sheets" / tile_sheet / "3" / "0" / "0.webp"
            tile_url = (
                "http://127.0.0.1:8765/assets/images/maps/tiles/world-v3/"
                f"sheets/{tile_sheet}/3/0/0.webp"
            )
        else:
            tile_path = self._path(browser_qa.RELEASE_TREE) / "0" / "0" / "0.webp"
            tile_url = "http://127.0.0.1:8765/assets/images/maps/tiles/world-v3/0/0/0.webp"
        metrics["served_tiles"] = [{"url_path": tile_url, "sha256": sha256(tile_path)}]

        console_events = []
        network_events = []
        if scenario_id == "royal_child_failure":
            console_events = [
                {
                    "type": "warning",
                    "text": diagnostics["expected_console_warnings"][0],
                    "location": {},
                }
            ]
            network_events = [royal_event]
        config = browser_qa.scenario_config(scenario_id)
        config_evidence = self._evidence(scenario_id, "config", config)
        driver_path = self.output / "scenarios" / scenario_id / "scenario-driver.js"
        browser_runner._write_driver(
            driver_path,
            browser_qa.build_scenario_options(
                scenario_id,
                tested_url=(
                    "http://127.0.0.1:8765/pages/interactive-map-v3.html"
                    "?release-preview=world-v3"
                ),
                inputs=self.inputs,
                delay_ms=500,
                timeout_ms=30000,
            ),
        )
        evidence = {
            "screenshot": self._evidence(scenario_id, "screenshot", (width, height)),
            "snapshot": self._evidence(
                scenario_id, "snapshot", '# Page snapshot\n- main "world-v3 map"\n'
            ),
            "console": self._evidence(
                scenario_id,
                "console",
                {"events": console_events, "page_errors": [], "playwright_cli": "fixture"},
            ),
            "network": self._evidence(
                scenario_id,
                "network",
                {"events": network_events, "playwright_cli": "fixture"},
            ),
            "driver": {
                "path": driver_path.relative_to(self.output).as_posix(),
                "sha256": sha256(driver_path),
            },
            "config": config_evidence,
        }
        return {
            "id": scenario_id,
            "result": "pass",
            "viewport": {"width": width, "height": height},
            "assertions": assertions,
            "diagnostics": diagnostics,
            "metrics": metrics,
            "evidence": evidence,
        }

    def _build_receipt(self):
        return {
            "$schema": "https://sstory.example/schemas/phase6-browser-qa-receipt.schema.json",
            "schema_version": "1.0.0",
            "type": "sstory-phase6-browser-qa-receipt",
            "release_id": "world-v3",
            "result": "pass",
            "started_at": STARTED,
            "completed_at": COMPLETED,
            "generated_by": "sstory-map-production/run_phase6_browser_qa.py@1",
            "tested_url": "http://127.0.0.1:8765/pages/interactive-map-v3.html?release-preview=world-v3",
            "playwright": {
                "cli_version": browser_qa.PINNED_PLAYWRIGHT_CLI_VERSION,
                "browser_name": "chromium",
                "browser_version": "140.0.0.0",
            },
            "inputs": self.inputs,
            "scenarios": [self._scenario(value) for value in browser_qa.EXPECTED_SCENARIOS],
            "failure_reasons": [],
        }

    def validate(self, receipt=None):
        return browser_qa.validate_browser_qa_receipt(
            receipt or self.receipt,
            repo_root=self.root,
            artifact_root=self.output,
            schema_path=self.schema,
            require_pass=True,
        )

    def test_hash_bound_four_scenario_pass_receipt_is_accepted(self):
        self.assertEqual(self.validate(), [])

    def test_index_tamper_after_browser_run_is_rejected(self):
        canonical = self._path(browser_qa.CANONICAL_INDEX)
        canonical.write_bytes(canonical.read_bytes() + b" ")
        errors = self.validate()
        self.assertTrue(any("byte-identical" in error or "input hashes" in error for error in errors))

    def test_runtime_javascript_tamper_after_browser_run_is_rejected(self):
        runtime = self._path(PurePosixPath("docs/assets/js/interactive-map-v3.js"))
        runtime.write_bytes(runtime.read_bytes() + b"\n// tampered\n")
        self.assertTrue(any("input hashes" in error for error in self.validate()))

    def test_canonical_search_oracle_coordinate_drift_is_rejected(self):
        source = self._path(browser_qa.SEARCH_ORACLE_SOURCE)
        pois = json.loads(source.read_text(encoding="utf-8"))
        pois[0]["position"]["x"] = 5099
        write_json(source, pois)
        errors = self.validate()
        self.assertTrue(
            any("coordinates changed" in error or "input hashes" in error for error in errors)
        )

    def test_missing_screenshot_is_rejected(self):
        screenshot = self.output / self.receipt["scenarios"][0]["evidence"]["screenshot"]["path"]
        screenshot.unlink()
        self.assertTrue(any("does not exist" in error for error in self.validate()))

    def test_mobile_screenshot_must_be_exact_viewport_dimensions(self):
        mobile = next(item for item in self.receipt["scenarios"] if item["id"] == "mobile")
        screenshot = self.output / mobile["evidence"]["screenshot"]["path"]
        write_visual_png(screenshot, (391, 844))
        mobile["evidence"]["screenshot"]["sha256"] = sha256(screenshot)
        self.assertTrue(any("exact 390x844" in error for error in self.validate()))

    def test_png_with_only_a_forged_header_is_rejected(self):
        desktop = self.receipt["scenarios"][0]
        screenshot = self.output / desktop["evidence"]["screenshot"]["path"]
        screenshot.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR"
            + (1440).to_bytes(4, "big")
            + (1000).to_bytes(4, "big")
        )
        desktop["evidence"]["screenshot"]["sha256"] = sha256(screenshot)
        self.assertTrue(any("viewport PNG" in error for error in self.validate()))

    def test_valid_but_blank_screenshot_is_rejected(self):
        desktop = self.receipt["scenarios"][0]
        screenshot = self.output / desktop["evidence"]["screenshot"]["path"]
        Image.new("RGB", (1440, 1000), color=(32, 48, 64)).save(
            screenshot, format="PNG"
        )
        desktop["evidence"]["screenshot"]["sha256"] = sha256(screenshot)
        self.assertTrue(any("non-blank visual" in error for error in self.validate()))

    def test_raw_console_evidence_is_rederived_not_self_attested(self):
        desktop = self.receipt["scenarios"][0]
        console = self.output / desktop["evidence"]["console"]["path"]
        write_json(
            console,
            {
                "events": [{"type": "error", "text": "forged pass", "location": {}}],
                "page_errors": [],
                "playwright_cli": "fixture",
            },
        )
        desktop["evidence"]["console"]["sha256"] = sha256(console)
        self.assertTrue(
            any("do not match raw" in error for error in self.validate())
        )

    def test_generated_scenario_driver_tamper_is_rejected(self):
        desktop = self.receipt["scenarios"][0]
        driver = self.output / desktop["evidence"]["driver"]["path"]
        driver.write_text(driver.read_text(encoding="utf-8") + "\n// bypass\n", encoding="utf-8")
        desktop["evidence"]["driver"]["sha256"] = sha256(driver)
        self.assertTrue(any("locked scenario" in error for error in self.validate()))

    def test_generated_driver_locks_real_focus_and_search_target_contracts(self):
        html = REPO_ROOT.joinpath(*browser_qa.HTML.parts).read_text(encoding="utf-8")
        styles = REPO_ROOT.joinpath(
            "docs", "assets", "css", "interactive-map-v3.css"
        ).read_text(encoding="utf-8")
        runtime = REPO_ROOT.joinpath(
            "docs", "assets", "js", "interactive-map-v3.js"
        ).read_text(encoding="utf-8")
        selectors = {
            selector
            for steps in browser_qa.FOCUS_TRAVERSAL_STEPS.values()
            for _key, selector in steps
        }
        selectors.update(
            selector
            for transfers in browser_qa.FOCUS_TRANSFERS.values()
            for _cause, selector in transfers
        )
        for selector in selectors:
            if selector.startswith("#"):
                self.assertIn(f'id="{selector[1:]}"', html)
        self.assertIn('class="skip-link"', html)
        self.assertIn('class="brand"', html)
        self.assertIn('id="layerPanelClose"', html)
        self.assertRegex(styles, r"\.map-search__toggle\s*\{[^}]*display:\s*none")
        self.assertRegex(
            styles,
            r"@media \(max-width: 760px\)[\s\S]*"
            r"\.map-search__toggle\s*\{[^}]*display:\s*inline-grid",
        )
        self.assertRegex(
            runtime,
            r"window\.setTimeout\(\(\) => \{[\s\S]*"
            r"focusTarget = open \? elements\.layerClose : elements\.layerButton;"
            r"[\s\S]*focusTarget\?\.focus\(\{ preventScroll: true \}\);"
            r"[\s\S]*\}, 50\);",
        )

        for scenario_id in browser_qa.INTERACTION_SCENARIOS:
            with self.subTest(scenario=scenario_id):
                scenario = next(
                    item for item in self.receipt["scenarios"] if item["id"] == scenario_id
                )
                driver = self.output / scenario["evidence"]["driver"]["path"]
                source = driver.read_text(encoding="utf-8")
                self.assertNotIn("page.locator", source)
                self.assertNotIn(".focus()", source)
                self.assertIn("page.keyboard.press(key)", source)
                self.assertIn("traverseFocus('Tab'", source)
                self.assertIn("traverseFocus('Shift+Tab'", source)
                self.assertIn("window.__sstoryPhase6SearchMoveTracker", source)
                self.assertIn("map.on('moveend', tracker.handler)", source)
                self.assertIn("api?.search?.targets?.get(entry.key)", source)
                self.assertIn("options.searchOracle.target", source)
                self.assertIn("'#layerPanelClose'", source)
                self.assertNotIn("core.mapSearchTargetZoom", source)
                self.assertIn(browser_qa.SEARCH_TARGET_LABEL, source)
                checked = browser_runner.subprocess.run(
                    ["node", "--check", str(driver)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_playwright_cli_version_is_pinned(self):
        self.receipt["playwright"]["cli_version"] = "0.1.18"
        self.assertTrue(any("pinned Playwright CLI" in error for error in self.validate()))

    def test_every_scenario_user_agent_must_identify_declared_browser(self):
        self.receipt["scenarios"][0]["metrics"]["browser_user_agent"] = "not Chromium"
        self.assertTrue(
            any(
                "browser_version must exactly match every scenario user agent" in error
                for error in self.validate()
            )
        )

    def test_runner_command_pins_the_exact_cli_package(self):
        command = browser_runner._cli_command()
        self.assertIn("@playwright/cli@0.1.17", command)
        self.assertNotIn("@playwright/cli", command)
        if sys.platform == "win32":
            self.assertEqual(command[0], "npx.cmd")

    def test_cli_version_probe_is_sessionless_and_uses_normal_windows_appdata(self):
        scenario_dir = self.root / "version-probe"
        with mock.patch.object(
            browser_runner.subprocess,
            "run",
            return_value=browser_runner.subprocess.CompletedProcess(
                args=[], returncode=0, stdout="0.1.17\n", stderr=""
            ),
        ) as run:
            client = browser_runner.PlaywrightCliClient(
                scenario_dir,
                session="must-not-appear",
                command=["pinned-cli"],
            )
            self.assertEqual(client.version(), "0.1.17")
        call = run.call_args
        self.assertNotIn("-s=must-not-appear", call.args[0])
        if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
            self.assertEqual(
                call.kwargs["env"]["LOCALAPPDATA"], os.environ["LOCALAPPDATA"]
            )

    def test_wrong_royal_fallback_parent_is_rejected(self):
        receipt = copy.deepcopy(self.receipt)
        royal = next(item for item in receipt["scenarios"] if item["id"] == "royal_child_failure")
        royal["metrics"]["nearest_parent_id"] = "sheet_world"
        self.assertTrue(any("wrong nearest parent" in error for error in self.validate(receipt)))

    def test_stale_http_index_hash_is_rejected_even_when_release_id_matches(self):
        receipt = copy.deepcopy(self.receipt)
        receipt["scenarios"][0]["metrics"]["served_index_sha256"] = "f" * 64
        self.assertTrue(
            any("served_index_sha256" in error for error in self.validate(receipt))
        )

    def test_base_tile_fallback_cannot_masquerade_as_world_v3_rendering(self):
        desktop = self.receipt["scenarios"][0]
        desktop["metrics"]["base_tiles_decoded"] = False
        desktop["metrics"]["base_tile_fallback_used"] = True
        self.assertTrue(
            any("base tile" in error for error in self.validate())
        )

    def test_user_interaction_metrics_are_fail_closed(self):
        cases = (
            (
                "desktop",
                ("keyboard", "center_after"),
                {"lat": -100.0, "lng": 200.0},
                "keyboard map panning",
            ),
            (
                "desktop",
                ("search", "result_selected"),
                False,
                "quiescent target/popup",
            ),
            (
                "desktop",
                ("search", "selected_entry_key"),
                "poi:forged-target",
                "quiescent target/popup",
            ),
            (
                "desktop",
                ("search", "oracle_source", "sha256"),
                "f" * 64,
                "quiescent target/popup",
            ),
            (
                "desktop",
                ("search", "popup", "lat"),
                -4000.0,
                "quiescent target/popup",
            ),
            (
                "desktop",
                ("search", "final_center"),
                {"lat": 0.0, "lng": 0.0},
                "quiescent target/popup",
            ),
            (
                "desktop",
                ("search", "quiescent_ms"),
                0.0,
                "quiescent target/popup",
            ),
            (
                "desktop",
                ("search", "moveend_count"),
                0,
                "quiescent target/popup",
            ),
            (
                "mobile",
                ("focus_traversal", "steps", 2, "actionable"),
                False,
                "Tab/Shift+Tab focus traversal",
            ),
            (
                "desktop",
                ("layer_panel", "closed"),
                False,
                "keyboard layer-panel toggle",
            ),
            (
                "mobile",
                ("mobile_search_focus", "focus_restored"),
                False,
                "mobile search focus restoration",
            ),
            (
                "desktop",
                ("errors",),
                ["fixture interaction failure"],
                "user-interaction diagnostics",
            ),
        )
        for scenario_id, path, value, expected_error in cases:
            with self.subTest(
                scenario=scenario_id, metric=".".join(map(str, path))
            ):
                receipt = copy.deepcopy(self.receipt)
                scenario = next(
                    item for item in receipt["scenarios"] if item["id"] == scenario_id
                )
                target = scenario["metrics"]["interaction_evidence"]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.assertTrue(
                    any(
                        expected_error in error
                        for error in self.validate(receipt)
                    )
                )

    def test_search_oracle_rejects_coordinated_target_and_zoom_forgery(self):
        for scenario_id in browser_qa.INTERACTION_SCENARIOS:
            with self.subTest(scenario=scenario_id, forgery="target"):
                receipt = copy.deepcopy(self.receipt)
                scenario = next(
                    item for item in receipt["scenarios"] if item["id"] == scenario_id
                )
                search = scenario["metrics"]["interaction_evidence"]["search"]
                search["expected_target"] = {"lat": 5620.0, "lng": 15100.0}
                search["runtime_target"] = {"lat": 5620.0, "lng": 15100.0}
                search["final_center"] = {"lat": 5700.0, "lng": 15000.0}
                search["final_bounds"] = {
                    "south": 5000.0,
                    "west": 14000.0,
                    "north": 7000.0,
                    "east": 16000.0,
                }
                search["popup"]["lat"] = 5620.0
                search["popup"]["lng"] = 15100.0
                self.assertTrue(
                    any(
                        "quiescent target/popup" in error
                        for error in self.validate(receipt)
                    )
                )

            with self.subTest(scenario=scenario_id, forgery="zoom"):
                receipt = copy.deepcopy(self.receipt)
                scenario = next(
                    item for item in receipt["scenarios"] if item["id"] == scenario_id
                )
                search = scenario["metrics"]["interaction_evidence"]["search"]
                search["expected_zoom"] += 1.0
                search["final_zoom"] += 1.0
                self.assertTrue(
                    any(
                        "quiescent target/popup" in error
                        for error in self.validate(receipt)
                    )
                )

    def test_duplicate_preview_parameter_is_rejected(self):
        receipt = copy.deepcopy(self.receipt)
        receipt["tested_url"] += "&release-preview=world-v3"
        self.assertTrue(any("exactly one" in error for error in self.validate(receipt)))

    def test_failed_scenario_cannot_authorize_publication(self):
        receipt = copy.deepcopy(self.receipt)
        receipt["result"] = "fail"
        receipt["failure_reasons"] = ["mobile failed"]
        receipt["scenarios"][1]["result"] = "fail"
        errors = self.validate(receipt)
        self.assertTrue(any("requires a PASS" in error for error in errors))
        self.assertTrue(any("did not all pass" in error for error in errors))

    def test_honest_failure_receipt_can_be_validated_for_diagnostics_only(self):
        receipt = copy.deepcopy(self.receipt)
        receipt["result"] = "fail"
        receipt["failure_reasons"] = ["mobile browser did not become ready"]
        mobile = next(item for item in receipt["scenarios"] if item["id"] == "mobile")
        mobile["result"] = "fail"
        mobile["assertions"] = {
            name: False for name in browser_qa.SCENARIO_ASSERTIONS["mobile"]
        }
        mobile["diagnostics"]["console_errors"] = ["fixture failure"]
        mobile["metrics"] = {
            "selected_release": None,
            "index_release_id": None,
            "bounded_sheet_count": 0,
        }
        self.assertEqual(
            browser_qa.validate_browser_qa_receipt(
                receipt,
                repo_root=self.root,
                artifact_root=self.output,
                schema_path=self.schema,
                require_pass=False,
            ),
            [],
        )

    def test_persisted_bundle_validation_skips_only_mutable_release_status(self):
        readiness = self._path(browser_qa.READINESS)
        value = json.loads(readiness.read_text(encoding="utf-8"))
        value["status"] = "published"
        write_json(readiness, value)
        receipt_path = self.output / browser_runner.RECEIPT_NAME
        write_json(receipt_path, self.receipt)
        _receipt, errors = browser_qa.validate_persisted_browser_qa_bundle(
            receipt_path,
            repo_root=self.root,
            schema_path=self.schema,
        )
        self.assertEqual(errors, [])

    def test_persisted_bundle_rejects_runtime_dependency_drift(self):
        receipt_path = self.output / browser_runner.RECEIPT_NAME
        write_json(receipt_path, self.receipt)
        runtime = self._path(PurePosixPath("docs/assets/js/interactive-map-v3.js"))
        runtime.write_bytes(runtime.read_bytes() + b"\n// post-publication drift\n")
        _receipt, errors = browser_qa.validate_persisted_browser_qa_bundle(
            receipt_path,
            repo_root=self.root,
            schema_path=self.schema,
        )
        self.assertTrue(any("changed after browser QA" in error for error in errors))

    def test_persisted_bundle_rejects_world_v3_release_tree_drift(self):
        receipt_path = self.output / browser_runner.RECEIPT_NAME
        write_json(receipt_path, self.receipt)
        tile = self._path(browser_qa.RELEASE_TREE) / "0" / "0" / "0.webp"
        tile.write_bytes(tile.read_bytes() + b"drift")
        _receipt, errors = browser_qa.validate_persisted_browser_qa_bundle(
            receipt_path,
            repo_root=self.root,
            schema_path=self.schema,
        )
        self.assertTrue(any("release tree changed" in error for error in errors))

    def test_readiness_gate_verifies_a_real_persisted_browser_bundle(self):
        receipt_path = self.output / browser_runner.RECEIPT_NAME
        write_json(receipt_path, self.receipt)
        bundle = self.root.joinpath(*readiness_gate.BROWSER_QA_BUNDLE_PATH.parts)
        bundle.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.output, bundle)
        _count, tree_sha = readiness_gate._browser_bundle_tree_evidence(bundle)
        owner = {
            "path": readiness_gate.BROWSER_QA_BUNDLE_PATH.as_posix(),
            "receipt_sha256": sha256(bundle / browser_runner.RECEIPT_NAME),
            "tree_sha256": tree_sha,
            "tested_url": self.receipt["tested_url"],
            "completed_at": self.receipt["completed_at"],
        }
        persisted, errors = readiness_gate._validate_browser_qa_bundle(
            owner,
            repo_root=self.root,
        )
        self.assertEqual(errors, [])
        self.assertEqual(persisted, self.receipt)

    def test_mocked_playwright_fixture_emits_a_valid_fail_closed_receipt(self):
        late_console_events = []

        class FakePlaywrightClient:
            def __init__(client_self, scenario_dir, *, session, command, timeout_seconds):
                client_self.scenario_dir = scenario_dir
                client_self.scenario_id = session.removeprefix("sstory-phase6-")

            def version(client_self):
                return browser_qa.PINNED_PLAYWRIGHT_CLI_VERSION

            def open(client_self, config_path):
                client_self.config_path = config_path
                config = json.loads(config_path.read_text(encoding="utf-8"))
                context = config["browser"]["contextOptions"]
                if client_self.scenario_id == "mobile":
                    if context.get("isMobile") is not True or context.get("hasTouch") is not True:
                        raise AssertionError("mobile context configuration was not passed")
                return None

            def resize(client_self, width, height):
                client_self.viewport = (width, height)

            def run_code(client_self, _driver):
                if Path(_driver).name == browser_runner.FINAL_DIAGNOSTICS_DRIVER.name:
                    return {
                        "collector_ready": True,
                        "baseTilesDecoded": True,
                        "baseTileFallbackUsed": False,
                        **client_self.final_raw,
                        "console": [
                            *client_self.final_raw["console"],
                            *late_console_events,
                        ],
                    }
                scenario_id = client_self.scenario_id
                assertions = {
                    name: True for name in browser_qa.SCENARIO_ASSERTIONS[scenario_id]
                }
                metrics = {
                    "selected_release": "world-v3",
                    "index_release_id": "world-v3",
                    "bounded_sheet_count": 23,
                    "served_html_sha256": self.inputs["html"]["sha256"],
                    "served_index_sha256": self.inputs["compatibility_index"]["sha256"],
                    "served_world_manifest_sha256": self.inputs["world_manifest"]["sha256"],
                    "served_runtime_sha256": {
                        item["path"]: item["sha256"]
                        for item in self.inputs["runtime_dependencies"]["artifacts"]
                    },
                    "served_probe_manifest_sha256": {},
                    "available_sheet_count": 22,
                    "browser_user_agent": "Mozilla/5.0 Chrome/140.0.0.0 Safari/537.36",
                    "delay_ms": 500 if scenario_id == "slow_tiles" else 0,
                    "delayed_tile_requests": 2 if scenario_id == "slow_tiles" else 0,
                    "elapsed_ms": 1800,
                    "configured_delay_ms": 500,
                    "timeout_ms": 30000,
                    "base_tiles_decoded": True,
                    "base_tile_fallback_used": False,
                    "injected_status": 503 if scenario_id == "royal_child_failure" else 0,
                    "failed_child_id": browser_qa.ROYAL_CHILD_ID if scenario_id == "royal_child_failure" else None,
                    "nearest_parent_id": browser_qa.ROYAL_PARENT_ID if scenario_id == "royal_child_failure" else None,
                    "failure_response_count": 1 if scenario_id == "royal_child_failure" else 0,
                    "parent_status_before": "ready" if scenario_id == "royal_child_failure" else None,
                    "parent_status_after": "ready" if scenario_id == "royal_child_failure" else None,
                    "failed_sheet_ids": [browser_qa.ROYAL_CHILD_ID] if scenario_id == "royal_child_failure" else [],
                    "visible_sheet_ids": [browser_qa.ROYAL_PARENT_ID] if scenario_id == "royal_child_failure" else [],
                }
                if scenario_id in browser_qa.INTERACTION_SCENARIOS:
                    metrics["interaction_evidence"] = interaction_evidence(
                        scenario_id, self.inputs
                    )
                tile_sheet = (
                    browser_qa.ROYAL_PARENT_ID
                    if scenario_id in {"slow_tiles", "royal_child_failure"}
                    else None
                )
                if tile_sheet:
                    tile_path = self._path(browser_qa.RELEASE_TREE) / "sheets" / tile_sheet / "3" / "0" / "0.webp"
                    tile_url = (
                        "http://127.0.0.1:8765/assets/images/maps/tiles/world-v3/"
                        f"sheets/{tile_sheet}/3/0/0.webp"
                    )
                else:
                    tile_path = self._path(browser_qa.RELEASE_TREE) / "0" / "0" / "0.webp"
                    tile_url = (
                        "http://127.0.0.1:8765/assets/images/maps/tiles/world-v3/0/0/0.webp"
                    )
                metrics["served_tiles"] = [
                    {"url_path": tile_url, "sha256": sha256(tile_path)}
                ]
                if scenario_id in {"slow_tiles", "royal_child_failure"}:
                    metrics["served_probe_manifest_sha256"][browser_qa.ROYAL_PARENT_ID] = (
                        self.inputs["royal_probe"]["parent"]["manifest"]["sha256"]
                    )
                if scenario_id == "royal_child_failure":
                    metrics["served_probe_manifest_sha256"][browser_qa.ROYAL_CHILD_ID] = (
                        self.inputs["royal_probe"]["child"]["manifest"]["sha256"]
                    )
                warning = (
                    "[InteractiveMapV3] Sheet tiles unavailable; retaining nearest parent "
                    "sheet_continent_elysion: sheet_region_royal_capital_region"
                )
                royal_event = {
                    "kind": "response",
                    "method": "GET",
                    "url": (
                        "http://127.0.0.1:8765/assets/images/maps/tiles/world-v3/"
                        "sheets/sheet_region_royal_capital_region/4/0/0.webp"
                    ),
                    "status": 503,
                }
                console_events = (
                    [{"type": "warning", "text": warning, "location": {}}]
                    if scenario_id == "royal_child_failure"
                    else []
                )
                network_events = (
                    [royal_event] if scenario_id == "royal_child_failure" else []
                )
                client_self.final_raw = {
                    "console": console_events,
                    "pageErrors": [],
                    "network": network_events,
                }
                return {
                    "id": scenario_id,
                    "result": "pass",
                    "viewport": {
                        "width": client_self.viewport[0],
                        "height": client_self.viewport[1],
                    },
                    "assertions": assertions,
                    "diagnostics": {
                        "console_errors": [],
                        "page_errors": [],
                        "network_errors": [],
                        "expected_console_warnings": [warning] if scenario_id == "royal_child_failure" else [],
                        "expected_network_failures": [
                            json.dumps(
                                royal_event,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                        ] if scenario_id == "royal_child_failure" else [],
                    },
                    "metrics": metrics,
                    "raw": dict(client_self.final_raw),
                }

            def snapshot(client_self, filename):
                filename.write_text("# mocked accessibility snapshot\n", encoding="utf-8")
                return "snapshot"

            def screenshot(client_self, filename):
                width, height = client_self.viewport
                write_visual_png(filename, (width, height))
                return "screenshot"

            def console(client_self):
                return "No console errors"

            def network(client_self):
                return "No unexpected network errors"

            def close(client_self):
                return None

        output = self.root / "mocked-browser-output"
        result = browser_runner.run_browser_qa(
            tested_url="http://127.0.0.1:8765/pages/interactive-map-v3.html?release-preview=world-v3",
            output_dir=output,
            repo_root=self.root,
            client_factory=FakePlaywrightClient,
        )
        self.assertTrue(result["valid"])
        receipt_path = Path(result["receipt"])
        receipt, errors = browser_qa.validate_browser_qa_receipt_file(
            receipt_path,
            repo_root=self.root,
            schema_path=self.schema,
            require_pass=True,
        )
        self.assertEqual(errors, [])
        self.assertEqual(receipt["result"], "pass")
        self.assertEqual(len(receipt["scenarios"]), 4)

        late_console_events.append(
            {"type": "error", "text": "late screenshot failure", "location": {}}
        )
        late_output = self.root / "mocked-browser-output-with-late-error"
        late_result = browser_runner.run_browser_qa(
            tested_url="http://127.0.0.1:8765/pages/interactive-map-v3.html?release-preview=world-v3",
            output_dir=late_output,
            repo_root=self.root,
            client_factory=FakePlaywrightClient,
        )
        self.assertFalse(late_result["valid"])
        late_receipt = json.loads(
            Path(late_result["receipt"]).read_text(encoding="utf-8")
        )
        self.assertEqual(late_receipt["result"], "fail")
        self.assertTrue(
            all(
                "late screenshot failure"
                in scenario["diagnostics"]["console_errors"][0]
                for scenario in late_receipt["scenarios"]
            )
        )


if __name__ == "__main__":
    unittest.main()
