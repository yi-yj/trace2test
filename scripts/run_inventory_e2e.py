"""Run and deterministically verify the resettable inventory export task."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv

from apps.inventory_demo import InventoryDemoServer
from scripts.virtual_cursor import (
    install_virtual_cursor,
    move_virtual_cursor_to_point,
    remove_virtual_cursor,
    set_virtual_cursor_pressed,
    wait_for_visual_close,
)
from tracetotest.browser_fonts import configure_browser_fonts
from tracetotest.tasks import TaskSpec
from tracetotest.trace import (
    ActionRecord,
    AfterState,
    DecisionRecord,
    EventRecord,
    ObservationRecord,
    RunRecord,
    StepRecord,
    TraceCollector,
)
from tracetotest.verification import InventoryExportVerifier, VerificationContext

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASK = ROOT / "tasks/inventory/export_low_inventory.json"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, default=DEFAULT_TASK)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--slow-mo", type=int, default=0, metavar="MS")
    parser.add_argument("--no-virtual-cursor", action="store_true")
    parser.add_argument("--cursor-move-ms", type=int, default=700, metavar="MS")
    parser.add_argument("--click-display-ms", type=int, default=450, metavar="MS")
    args = parser.parse_args(argv)
    if min(args.slow_mo, args.cursor_move_ms, args.click_display_ms) < 0:
        parser.error("visualization delays must be zero or greater")
    return args


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_state() -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    return {"commit": commit, "dirty": dirty}


def _chromium_executable() -> Path | None:
    browser_root = Path(os.getenv("PLAYWRIGHT_BROWSERS_PATH", ROOT / ".cache/ms-playwright"))
    if not browser_root.is_absolute():
        browser_root = ROOT / browser_root
    candidates = sorted(browser_root.glob("chromium-*/chrome-linux/chrome"))
    candidates += sorted(browser_root.glob("chromium-*/chrome-linux64/chrome"))
    return candidates[-1] if candidates else None


def _artifact_root(value: Path | None) -> Path:
    if value:
        return value if value.is_absolute() else ROOT / value
    configured = Path(os.getenv("ARTIFACT_STORE_PATH", "artifacts"))
    return configured if configured.is_absolute() else ROOT / configured


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _visualize_locator(page: Any, locator: Any, *, move_ms: int, click_ms: int) -> None:
    """Show the shared cursor at a Playwright locator before the real action."""
    install_virtual_cursor(page)
    try:
        box = locator.bounding_box()
        if box is None:
            raise RuntimeError("Cannot visualize an element without a bounding box")
        move_virtual_cursor_to_point(
            page,
            box["x"] + box["width"] / 2,
            box["y"] + box["height"] / 2,
            duration_ms=move_ms,
        )
        set_virtual_cursor_pressed(page, True)
        page.wait_for_timeout(click_ms)
        set_virtual_cursor_pressed(page, False)
    finally:
        remove_virtual_cursor(page)


def run(argv: Sequence[str] | None = None) -> tuple[Path, bool]:
    args = _parse_args(argv)
    load_dotenv(ROOT / ".env")
    configure_browser_fonts()
    task_path = args.task if args.task.is_absolute() else ROOT / args.task
    task = TaskSpec.load(task_path)
    fixture_path = ROOT / task.environment.fixture_path
    run_id = f"inventory_e2e_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"
    run_dir = _artifact_root(args.output_root) / "inventory-e2e" / run_id
    canonical_dir = run_dir / "canonical"
    downloads_dir = run_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc)
    collector = TraceCollector(
        canonical_dir,
        RunRecord(
            run_id=run_id,
            task_id=task.task_id,
            suite_id=task.suite_id,
            agent_id="deterministic-playwright-driver",
            framework="playwright",
            status="running",
            started_at=started,
            duration_ms=0,
            steps=0,
            manifest_ref="artifact://manifest.json",
        ),
    )
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "task": {
            "id": task.task_id,
            "version": task.version,
            "sha256": _sha256(task_path),
            "instruction": task.instruction,
        },
        "fixture": {
            "id": task.environment.fixture_id,
            "version": task.environment.fixture_version,
            "sha256": _sha256(fixture_path),
        },
        "driver": "deterministic-playwright-driver",
        "playwright_version": version("playwright"),
        "git": _git_state(),
        "dependency_locks": {"uv_lock_sha256": _sha256(ROOT / "uv.lock")},
        "budget": task.limits.model_dump(mode="json"),
        "environment": {"viewport": [1280, 900], "locale": "en-US", "timezone": "UTC"},
        "visualization": {
            "headed": args.headed,
            "virtual_cursor": args.headed and not args.no_virtual_cursor,
            "cursor_move_ms": args.cursor_move_ms,
            "click_display_ms": args.click_display_ms,
        },
        "started_at": started.isoformat(),
        "result": None,
    }
    _write_manifest(run_dir / "manifest.json", manifest)
    collector.set_manifest(manifest)
    browser = None
    verification = None
    failure: str | None = None
    server: InventoryDemoServer | None = None
    try:
        from playwright.sync_api import sync_playwright

        with InventoryDemoServer(fixture_path) as server, sync_playwright() as playwright:
            launch_args: dict[str, Any] = {
                "headless": not args.headed,
                "slow_mo": args.slow_mo,
            }
            executable = _chromium_executable()
            if executable:
                launch_args["executable_path"] = str(executable)
            browser = playwright.chromium.launch(**launch_args)
            manifest["chromium_version"] = browser.version
            context = browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.goto(f"{server.base_url}{task.environment.start_path}")

            cursor_enabled = args.headed and not args.no_virtual_cursor
            if cursor_enabled:
                install_virtual_cursor(page)

            before_ref = collector.add_bytes(
                "screenshots/step-0-before.png",
                page.screenshot(),
                kind="screenshot",
                content_type="image/png",
                redacted=True,
            )
            if cursor_enabled:
                remove_virtual_cursor(page)
            dom_ref = collector.add_text("dom/step-0-before.html", page.content(), kind="dom")
            threshold_input = page.get_by_label("Stock less than")
            apply_button = page.get_by_role("button", name="Apply filter")
            if cursor_enabled:
                _visualize_locator(
                    page,
                    threshold_input,
                    move_ms=args.cursor_move_ms,
                    click_ms=args.click_display_ms,
                )
            threshold_input.fill(str(task.verifier.config["threshold"]))
            if cursor_enabled:
                _visualize_locator(
                    page,
                    apply_button,
                    move_ms=args.cursor_move_ms,
                    click_ms=args.click_display_ms,
                )
            apply_button.click()
            page.wait_for_load_state("domcontentloaded")
            if cursor_enabled:
                install_virtual_cursor(page)
            after_ref = collector.add_bytes(
                "screenshots/step-0-after.png",
                page.screenshot(),
                kind="screenshot",
                content_type="image/png",
                redacted=True,
            )
            collector.record_step(
                StepRecord(
                    run_id=run_id,
                    step_index=0,
                    timestamp=datetime.now(timezone.utc),
                    observation=ObservationRecord(
                        url=f"{server.base_url}{task.environment.start_path}",
                        title="Trace2Test Inventory",
                        screenshot_ref=before_ref,
                        dom_ref=dom_ref,
                    ),
                    decision=DecisionRecord(
                        current_goal="Filter inventory below the configured threshold",
                        expected_effect="Only products with stock below 10 remain visible",
                    ),
                    action=ActionRecord(
                        type="fill_and_submit",
                        parameters={"field": "max_stock", "value": task.verifier.config["threshold"]},
                        target_element_id="apply-filter",
                    ),
                    after=AfterState(
                        url=page.url,
                        title=page.title(),
                        screenshot_ref=after_ref,
                        observed_effect=page.locator("#result-count").inner_text(),
                    ),
                )
            )

            before_ref = collector.add_bytes(
                "screenshots/step-1-before.png",
                page.screenshot(),
                kind="screenshot",
                content_type="image/png",
                redacted=True,
            )
            if cursor_enabled:
                remove_virtual_cursor(page)
            dom_ref = collector.add_text("dom/step-1-before.html", page.content(), kind="dom")
            export_link = page.get_by_role("link", name="Export filtered CSV")
            if cursor_enabled:
                _visualize_locator(
                    page,
                    export_link,
                    move_ms=args.cursor_move_ms,
                    click_ms=args.click_display_ms,
                )
            with page.expect_download() as download_info:
                export_link.click()
            download = download_info.value
            download_path = downloads_dir / str(task.verifier.config["downloaded_file"])
            download.save_as(download_path)
            download_ref = collector.add_file(
                f"downloads/{download_path.name}",
                download_path,
                kind="download",
                content_type="text/csv; charset=utf-8",
                redacted=True,
            )
            after_ref = collector.add_bytes(
                "screenshots/step-1-after.png",
                page.screenshot(),
                kind="screenshot",
                content_type="image/png",
                redacted=True,
            )
            collector.record_step(
                StepRecord(
                    run_id=run_id,
                    step_index=1,
                    timestamp=datetime.now(timezone.utc),
                    observation=ObservationRecord(
                        url=page.url,
                        title=page.title(),
                        screenshot_ref=before_ref,
                        dom_ref=dom_ref,
                    ),
                    decision=DecisionRecord(
                        current_goal="Export the filtered rows",
                        expected_effect="A CSV containing exactly three low-stock products is downloaded",
                    ),
                    action=ActionRecord(
                        type="click",
                        parameters={"download": download_path.name},
                        target_text="Export filtered CSV",
                        target_element_id="export-csv",
                    ),
                    after=AfterState(
                        url=page.url,
                        title=page.title(),
                        screenshot_ref=after_ref,
                        observed_effect=f"Downloaded {download_path.name}",
                    ),
                )
            )
            collector.record_event(
                EventRecord(
                    event_id="evt_download",
                    run_id=run_id,
                    step_index=1,
                    timestamp_ns=time.time_ns(),
                    event_type="file_artifact",
                    payload={"artifact_ref": download_ref, "filename": download_path.name},
                )
            )
            verification = InventoryExportVerifier().verify(
                task,
                VerificationContext(
                    base_url=server.base_url,
                    download_dir=downloads_dir,
                    project_root=ROOT,
                ),
                collector.trace,
            )
            collector.record_verification(verification)
            collector.record_event(
                EventRecord(
                    event_id="evt_verification",
                    run_id=run_id,
                    step_index=1,
                    timestamp_ns=time.time_ns(),
                    event_type="verification",
                    payload=verification.model_dump(mode="json", exclude_none=True),
                )
            )
            if args.headed:
                wait_for_visual_close(page)
            context.close()
            browser.close()
            browser = None
    except Exception as error:
        failure = f"{type(error).__name__}: {error}"
        if browser:
            browser.close()

    passed = bool(verification and verification.passed and failure is None)
    verification_error = bool(
        verification and verification.failure_type in {"environment", "verifier"}
    )
    final_trace = collector.finish(
        "succeeded" if passed else "error" if failure or verification_error else "failed",
        reward=1.0 if passed else 0.0,
        termination_reason="verified_success" if passed else failure or "verification_failed",
    )
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["result"] = {
        "passed": passed,
        "status": final_trace.run.status,
        "termination_reason": final_trace.run.termination_reason,
        "verification": verification.model_dump(mode="json", exclude_none=True) if verification else None,
        "error": failure,
    }
    collector.set_manifest(manifest)
    _write_manifest(run_dir / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "canonical_trace": str(canonical_dir / "canonical_trace.json"),
                "passed": passed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return run_dir, passed


def main(argv: Sequence[str] | None = None) -> None:
    _, passed = run(argv)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
