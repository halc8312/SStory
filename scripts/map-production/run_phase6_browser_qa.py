#!/usr/bin/env python3
"""Run the four mandatory world-v3 Phase 6 checks with Playwright CLI.

The command never changes the release.  It may run only against the exact
``release-candidate`` bytes and writes all screenshots, accessibility snapshots,
console/network diagnostics, generated Playwright configuration, and its final
receipt beneath a caller-selected output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

import validate_phase6_browser_qa as validator
from production_common import REPO_ROOT, ValidationFailure, utc_now


RUNNER_ID = "sstory-map-production/run_phase6_browser_qa.py@1"
RECEIPT_NAME = "phase6-browser-qa-receipt.json"
SCENARIO_TEMPLATE = Path(__file__).with_name("phase6_browser_qa_scenario.js")
FINAL_DIAGNOSTICS_DRIVER = Path(__file__).with_name(
    "phase6_browser_qa_collect.js"
)
SCENARIO_TEMPLATE_MARKER = "__PHASE6_OPTIONS_JSON__"
DEFAULT_DELAY_MS = 500
DEFAULT_TIMEOUT_MS = 30_000
PINNED_PLAYWRIGHT_PACKAGE = (
    f"@playwright/cli@{validator.PINNED_PLAYWRIGHT_CLI_VERSION}"
)


class BrowserQaRunError(RuntimeError):
    """Raised when the browser harness cannot produce trustworthy evidence."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _evidence(output_root: Path, path: Path) -> dict[str, str]:
    return {
        "path": path.resolve().relative_to(output_root.resolve()).as_posix(),
        "sha256": _sha256_file(path),
    }


def _cli_command() -> list[str]:
    executable = "npx.cmd" if os.name == "nt" else "npx"
    return [
        executable,
        "--yes",
        "--package",
        PINNED_PLAYWRIGHT_PACKAGE,
        "playwright-cli",
    ]


def _parse_scenario_result(output: str) -> dict[str, Any]:
    text = output.strip()
    candidates = [text]
    if text:
        candidates.extend(line.strip() for line in reversed(text.splitlines()) if line.strip())
    for candidate in candidates:
        try:
            value: Any = json.loads(candidate)
            if isinstance(value, str):
                value = json.loads(value)
            if isinstance(value, dict):
                return value
        except (json.JSONDecodeError, TypeError):
            pass
    start = text.find("{")
    while start >= 0:
        try:
            value, _end = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    raise BrowserQaRunError("Playwright scenario did not return a JSON object")


class PlaywrightCliClient:
    """Small subprocess boundary around the skill-mandated Playwright CLI."""

    def __init__(
        self,
        scenario_dir: Path,
        *,
        session: str,
        command: Sequence[str] | None = None,
        timeout_seconds: int = 90,
    ) -> None:
        self.scenario_dir = scenario_dir.resolve()
        self.session = session
        self.command = list(command or _cli_command())
        self.timeout_seconds = timeout_seconds
        runtime = self.scenario_dir / ".runtime"
        shared_runtime = self.scenario_dir.parents[1] / ".runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        shared_runtime.mkdir(parents=True, exist_ok=True)
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "TEMP": str(runtime / "tmp"),
                "TMP": str(runtime / "tmp"),
                "PWTEST_DAEMON_SESSION_DIR": str(runtime / "daemon"),
                "XDG_CACHE_HOME": str(runtime / "cache"),
                "npm_config_cache": str(shared_runtime / "npm-cache"),
            }
        )
        # Playwright CLI and Chromium both use LOCALAPPDATA on Windows even
        # when TEMP is redirected.  Keep their disposable state with the
        # caller-selected evidence directory so a full system drive cannot
        # turn a valid map result into an ambiguous half-run.
        if os.name == "nt":
            self.environment["LOCALAPPDATA"] = str(runtime / "local-app-data")
        for name in ("tmp", "daemon", "cache", "local-app-data"):
            (runtime / name).mkdir(parents=True, exist_ok=True)
        (shared_runtime / "npm-cache").mkdir(parents=True, exist_ok=True)

    def _run(
        self,
        *arguments: str,
        check: bool = True,
        timeout_seconds: int | None = None,
        use_session: bool = True,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            *self.command,
            *([f"-s={self.session}"] if use_session else []),
            *arguments,
        ]
        try:
            result = subprocess.run(
                command,
                cwd=self.scenario_dir,
                env=environment or self.environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds or self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BrowserQaRunError(f"Playwright CLI failed to execute: {exc}") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise BrowserQaRunError(
                f"Playwright CLI {' '.join(arguments[:1])} failed ({result.returncode}): {detail}"
            )
        return result

    def version(self) -> str:
        # @playwright/cli 0.1.17 can crash in libuv after printing --version
        # when a daemon session or redirected LOCALAPPDATA is present on
        # Windows. Version probing neither needs nor creates browser state, so
        # keep it sessionless and use the process's normal LOCALAPPDATA.
        probe_environment = self.environment.copy()
        if os.name == "nt":
            original_local_app_data = os.environ.get("LOCALAPPDATA")
            if original_local_app_data:
                probe_environment["LOCALAPPDATA"] = original_local_app_data
            else:
                probe_environment.pop("LOCALAPPDATA", None)
        result = self._run(
            "--version",
            use_session=False,
            environment=probe_environment,
        )
        value = (result.stdout or result.stderr).strip()
        if not value:
            raise BrowserQaRunError("Playwright CLI did not report a version")
        reported = value.splitlines()[-1].strip()
        match = re.search(r"(?:^|\s)([0-9]+(?:\.[0-9]+){2})(?:\s|$)", reported)
        version = match.group(1) if match else reported
        if version != validator.PINNED_PLAYWRIGHT_CLI_VERSION:
            raise BrowserQaRunError(
                "Playwright CLI version drift: expected "
                f"{validator.PINNED_PLAYWRIGHT_CLI_VERSION}, got {reported!r}"
            )
        return version

    def open(self, config_path: Path) -> None:
        self._run(
            "open",
            "about:blank",
            "--config",
            str(config_path.resolve()),
        )

    def resize(self, width: int, height: int) -> None:
        self._run("resize", str(width), str(height))

    def run_code(self, filename: Path) -> dict[str, Any]:
        result = self._run(
            "--raw",
            "run-code",
            "--filename",
            str(filename.resolve()),
            timeout_seconds=max(self.timeout_seconds, 120),
        )
        return _parse_scenario_result(result.stdout)

    def snapshot(self, filename: Path) -> str:
        result = self._run("snapshot", "--filename", str(filename.resolve()))
        return result.stdout

    def screenshot(self, filename: Path) -> str:
        result = self._run(
            "screenshot", "--filename", str(filename.resolve())
        )
        return result.stdout

    def console(self) -> str:
        return self._run("console", "warning", check=False).stdout

    def network(self) -> str:
        return self._run("requests", check=False).stdout

    def close(self) -> None:
        self._run("close", check=False, timeout_seconds=30)


def _scenario_options(
    scenario_id: str,
    *,
    tested_url: str,
    inputs: dict[str, Any],
    delay_ms: int,
    timeout_ms: int,
) -> dict[str, Any]:
    return validator.build_scenario_options(
        scenario_id,
        tested_url=tested_url,
        inputs=inputs,
        delay_ms=delay_ms,
        timeout_ms=timeout_ms,
    )


def _failed_scenario(scenario_id: str, error: str) -> dict[str, Any]:
    width, height = validator.EXPECTED_VIEWPORTS[scenario_id]
    return {
        "id": scenario_id,
        "result": "fail",
        "viewport": {"width": width, "height": height},
        "assertions": {
            name: False for name in validator.SCENARIO_ASSERTIONS[scenario_id]
        },
        "diagnostics": {
            "console_errors": [error],
            "page_errors": [],
            "network_errors": [],
            "expected_console_warnings": [],
            "expected_network_failures": [],
        },
        "metrics": {
            "selected_release": None,
            "index_release_id": None,
            "bounded_sheet_count": 0,
        },
        "error": error,
    }


def _write_driver(path: Path, options: dict[str, Any]) -> None:
    try:
        template = SCENARIO_TEMPLATE.read_text(encoding="utf-8")
    except OSError as exc:
        raise BrowserQaRunError(f"cannot read scenario template: {exc}") from exc
    if template.count(SCENARIO_TEMPLATE_MARKER) != 1:
        raise BrowserQaRunError("scenario template must contain exactly one options marker")
    payload = json.dumps(options, ensure_ascii=False, separators=(",", ":"))
    path.write_text(template.replace(SCENARIO_TEMPLATE_MARKER, payload), encoding="utf-8")


def _run_scenario(
    scenario_id: str,
    *,
    output_root: Path,
    tested_url: str,
    inputs: dict[str, Any],
    delay_ms: int,
    timeout_ms: int,
    command: Sequence[str],
    client_factory: Callable[..., PlaywrightCliClient] = PlaywrightCliClient,
) -> tuple[dict[str, Any], str]:
    scenario_dir = output_root / "scenarios" / scenario_id
    scenario_dir.mkdir(parents=True, exist_ok=False)
    width, height = validator.EXPECTED_VIEWPORTS[scenario_id]
    config = validator.scenario_config(scenario_id)
    config_path = scenario_dir / "playwright-cli.json"
    _write_json(config_path, config)
    driver = scenario_dir / "scenario-driver.js"
    _write_driver(
        driver,
        _scenario_options(
            scenario_id,
            tested_url=tested_url,
            inputs=inputs,
            delay_ms=delay_ms,
            timeout_ms=timeout_ms,
        ),
    )
    client: PlaywrightCliClient | None = None
    cli_version = "unknown"
    try:
        client = client_factory(
            scenario_dir,
            session=f"sstory-phase6-{scenario_id}",
            command=command,
            timeout_seconds=max(90, timeout_ms // 1000 + 30),
        )
        cli_version = client.version()
        client.open(config_path)
        client.resize(width, height)
        scenario = client.run_code(driver)
        if scenario.get("id") != scenario_id:
            raise BrowserQaRunError(
                f"scenario identity mismatch: expected {scenario_id}, got {scenario.get('id')!r}"
            )
        snapshot_path = scenario_dir / "snapshot.md"
        screenshot_path = scenario_dir / "screenshot.png"
        early_raw = scenario.pop("raw", {})
        client.snapshot(snapshot_path)
        client.screenshot(screenshot_path)
        cli_console = client.console()
        cli_network = client.network()
        raw = client.run_code(FINAL_DIAGNOSTICS_DRIVER)
        if raw.get("collector_ready") is not True:
            raise BrowserQaRunError("final browser diagnostics collector is unavailable")
        for key in ("console", "pageErrors", "network"):
            early_events = early_raw.get(key, []) if isinstance(early_raw, dict) else []
            final_events = raw.get(key)
            if (
                not isinstance(early_events, list)
                or not isinstance(final_events, list)
                or final_events[: len(early_events)] != early_events
            ):
                raise BrowserQaRunError(
                    f"final browser diagnostics lost or rewrote early {key} events"
                )
        console_path = scenario_dir / "console.json"
        network_path = scenario_dir / "network.json"
        console_document = {
            "events": raw["console"],
            "page_errors": raw["pageErrors"],
            "playwright_cli": cli_console,
        }
        network_document = {
            "events": raw["network"],
            "playwright_cli": cli_network,
        }
        derived_diagnostics, diagnostic_errors = validator._classify_diagnostics(
            scenario_id,
            console_document,
            network_document,
        )
        if diagnostic_errors or derived_diagnostics is None:
            raise BrowserQaRunError(
                "final browser diagnostics are malformed: "
                + "; ".join(diagnostic_errors or ["classification failed"])
            )
        scenario["diagnostics"] = derived_diagnostics
        assertions = scenario.get("assertions")
        if not isinstance(assertions, dict):
            raise BrowserQaRunError("scenario assertions are missing")
        assertions["no_unexpected_console_errors"] = not derived_diagnostics[
            "console_errors"
        ]
        assertions["no_page_errors"] = not derived_diagnostics["page_errors"]
        assertions["no_unexpected_network_errors"] = not derived_diagnostics[
            "network_errors"
        ]
        assertions["base_tiles_decoded"] = raw.get("baseTilesDecoded") is True
        assertions["base_tile_fallback_unused"] = (
            raw.get("baseTileFallbackUsed") is False
        )
        metrics = scenario.get("metrics")
        if not isinstance(metrics, dict):
            raise BrowserQaRunError("scenario metrics are missing")
        metrics["base_tiles_decoded"] = raw.get("baseTilesDecoded") is True
        metrics["base_tile_fallback_used"] = raw.get("baseTileFallbackUsed") is not False
        if scenario_id == "royal_child_failure":
            expected_warnings = derived_diagnostics["expected_console_warnings"]
            expected_failures = derived_diagnostics["expected_network_failures"]
            assertions["fallback_warning_exact"] = bool(expected_warnings)
            assertions["failure_injected"] = bool(expected_failures)
            metrics["failure_response_count"] = len(expected_failures)
        scenario["result"] = (
            "pass" if all(value is True for value in assertions.values()) else "fail"
        )
        _write_json(
            console_path,
            console_document,
        )
        _write_json(
            network_path,
            network_document,
        )
        for required in (snapshot_path, screenshot_path, console_path, network_path):
            if not required.is_file() or required.stat().st_size == 0:
                raise BrowserQaRunError(f"Playwright evidence is missing/empty: {required.name}")
        scenario["evidence"] = {
            "screenshot": _evidence(output_root, screenshot_path),
            "snapshot": _evidence(output_root, snapshot_path),
            "console": _evidence(output_root, console_path),
            "network": _evidence(output_root, network_path),
            "driver": _evidence(output_root, driver),
            "config": _evidence(output_root, config_path),
        }
        return scenario, cli_version
    except Exception as exc:  # preserve all scenario diagnostics in a FAIL receipt
        error = f"{type(exc).__name__}: {exc}"
        _write_json(scenario_dir / "harness-error.json", {"error": error})
        return _failed_scenario(scenario_id, error), cli_version
    finally:
        if client is not None:
            client.close()


def _browser_version(scenarios: Sequence[dict[str, Any]]) -> str:
    for scenario in scenarios:
        metrics = scenario.get("metrics")
        user_agent = metrics.get("browser_user_agent") if isinstance(metrics, dict) else None
        if isinstance(user_agent, str):
            match = re.search(r"(?:Chrome|Chromium)/([0-9.]+)", user_agent)
            if match:
                return match.group(1)
    return "unavailable"


def run_browser_qa(
    *,
    tested_url: str,
    output_dir: Path,
    repo_root: Path = REPO_ROOT,
    delay_ms: int = DEFAULT_DELAY_MS,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    command: Sequence[str] | None = None,
    client_factory: Callable[..., PlaywrightCliClient] = PlaywrightCliClient,
) -> dict[str, Any]:
    """Run all scenarios and atomically write one PASS or FAIL receipt."""

    url_errors = validator._tested_url_errors(tested_url)
    if url_errors:
        raise BrowserQaRunError("; ".join(url_errors))
    if delay_ms < 400:
        raise BrowserQaRunError("slow tile delay must be at least 400 ms")
    if timeout_ms < 10_000:
        raise BrowserQaRunError("browser readiness timeout must be at least 10000 ms")
    output_dir = output_dir.resolve()
    repo_root = repo_root.resolve()
    if output_dir == repo_root:
        raise BrowserQaRunError("output directory may not be the repository root")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BrowserQaRunError(
            f"output directory must be absent or empty; refusing overwrite: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = output_dir / RECEIPT_NAME
    started_at = utc_now()
    try:
        before_inputs = validator.capture_release_candidate_inputs(repo_root)
    except (OSError, ValidationFailure, validator.BrowserQaValidationError) as exc:
        raise BrowserQaRunError(str(exc)) from exc

    cli = list(command or _cli_command())
    scenarios: list[dict[str, Any]] = []
    cli_versions: list[str] = []
    for scenario_id in validator.EXPECTED_SCENARIOS:
        scenario, cli_version = _run_scenario(
            scenario_id,
            output_root=output_dir,
            tested_url=tested_url,
            inputs=before_inputs,
            delay_ms=delay_ms,
            timeout_ms=timeout_ms,
            command=cli,
            client_factory=client_factory,
        )
        scenarios.append(scenario)
        cli_versions.append(cli_version)

    failure_reasons = [
        f"{scenario['id']}: {scenario.get('error', 'required assertion failed')}"
        for scenario in scenarios
        if scenario.get("result") != "pass"
    ]
    try:
        after_inputs = validator.capture_release_candidate_inputs(repo_root)
    except (OSError, ValidationFailure, validator.BrowserQaValidationError) as exc:
        after_inputs = None
        failure_reasons.append(f"post-run release-candidate validation failed: {exc}")
    if after_inputs != before_inputs:
        failure_reasons.append("release-candidate bytes changed during browser QA")

    receipt = {
        "$schema": "https://sstory.example/schemas/phase6-browser-qa-receipt.schema.json",
        "schema_version": "1.0.0",
        "type": "sstory-phase6-browser-qa-receipt",
        "release_id": validator.RELEASE_ID,
        "result": "fail" if failure_reasons else "pass",
        "started_at": started_at,
        "completed_at": utc_now(),
        "generated_by": RUNNER_ID,
        "tested_url": tested_url,
        "playwright": {
            "cli_version": next(
                (value for value in cli_versions if value and value != "unknown"),
                "unavailable",
            ),
            "browser_name": "chromium",
            "browser_version": _browser_version(scenarios),
        },
        "inputs": before_inputs,
        "scenarios": scenarios,
        "failure_reasons": sorted(set(failure_reasons)),
    }

    if receipt["result"] == "pass":
        validation_errors = validator.validate_browser_qa_receipt(
            receipt,
            repo_root=repo_root,
            artifact_root=output_dir,
            require_pass=True,
        )
        if validation_errors:
            receipt["result"] = "fail"
            receipt["failure_reasons"] = [
                f"receipt validation: {error}" for error in validation_errors
            ]

    temporary = receipt_path.with_name(f".{receipt_path.name}.writing")
    if temporary.exists():
        raise BrowserQaRunError(f"stale receipt staging file exists: {temporary}")
    _write_json(temporary, receipt)
    os.replace(temporary, receipt_path)
    return {
        "valid": receipt["result"] == "pass",
        "receipt": str(receipt_path),
        "result": receipt["result"],
        "scenario_count": len(scenarios),
        "failure_reasons": receipt["failure_reasons"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, dest="tested_url")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--delay-ms", type=int, default=DEFAULT_DELAY_MS)
    parser.add_argument("--timeout-ms", type=int, default=DEFAULT_TIMEOUT_MS)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_browser_qa(
            tested_url=args.tested_url,
            output_dir=args.output_dir,
            repo_root=args.repo_root,
            delay_ms=args.delay_ms,
            timeout_ms=args.timeout_ms,
            command=_cli_command(),
        )
    except (OSError, ValueError, BrowserQaRunError) as exc:
        result = {
            "valid": False,
            "receipt": None,
            "result": "fail",
            "scenario_count": 0,
            "failure_reasons": [str(exc)],
        }
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["valid"]:
        print(f"Phase 6 browser QA passed: {result['receipt']}")
    else:
        print("Phase 6 browser QA failed", file=sys.stderr)
        for error in result["failure_reasons"]:
            print(f"- {error}", file=sys.stderr)
        if result["receipt"]:
            print(f"Failure receipt: {result['receipt']}", file=sys.stderr)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
