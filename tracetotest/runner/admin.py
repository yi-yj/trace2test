"""Deterministic manual-driver acceptance runner for the local admin benchmark."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import urlopen

from apps.inventory_demo import InventoryDemoServer
from apps.inventory_demo import InventoryStore
from tracetotest.storage import ResultStore
from tracetotest.tasks import TaskSpec
from tracetotest.trace import ActionRecord, AfterState, ObservationRecord, RunRecord, StepRecord, TraceCollector, load_trace
from tracetotest.verification import VerificationContext, verifier_for


def _git_state(root: Path) -> dict[str, Any]:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True).stdout.strip())
    return {"commit": commit, "dirty": dirty}


def _record_step(collector: TraceCollector, page: Any, index: int, operation: dict[str, Any], action) -> None:
    before = collector.add_bytes(f"screenshots/step-{index}-before.png", page.screenshot(), kind="screenshot", content_type="image/png", redacted=True)
    dom = collector.add_text(f"dom/step-{index}.html", page.content(), kind="dom")
    before_url = page.url
    action()
    page.wait_for_timeout(40)
    after = collector.add_bytes(f"screenshots/step-{index}-after.png", page.screenshot(), kind="screenshot", content_type="image/png", redacted=True)
    parameters = {key: value for key, value in operation.items() if key != "action"}
    if str(operation.get("label", "")).casefold() == "password":
        parameters["value"] = "[REDACTED]"
    collector.record_step(StepRecord(
        run_id=collector.trace.run.run_id, step_index=index, timestamp=datetime.now(timezone.utc),
        observation=ObservationRecord(url=before_url, title=page.title(), screenshot_ref=before, dom_ref=dom),
        action=ActionRecord(type=str(operation["action"]), parameters=parameters, target_text=operation.get("name")),
        after=AfterState(url=page.url, title=page.title(), screenshot_ref=after),
    ))


def run_manual_task(task_path: Path, output_root: Path, database: ResultStore) -> tuple[Path, bool]:
    task_path = Path(task_path)
    root = Path(__file__).resolve().parents[2]
    task = TaskSpec.load(task_path)
    fixture_path = root / task.environment.fixture_path
    run_id = f"manual_{task.task_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"
    run_dir = output_root / "admin-acceptance" / run_id
    downloads = run_dir / "downloads"; downloads.mkdir(parents=True, exist_ok=False)
    canonical = run_dir / "canonical"
    started = datetime.now(timezone.utc)
    collector = TraceCollector(canonical, RunRecord(
        run_id=run_id, task_id=task.task_id, suite_id=task.suite_id,
        agent_id="manual-playwright-acceptance-driver", framework="playwright",
        status="running", started_at=started, duration_ms=0, steps=0,
        manifest_ref="artifact://manifest.json",
    ))
    result = None
    error = None
    final_url = ""
    with InventoryDemoServer(fixture_path, faults=task.environment.faults) as server:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                launch: dict[str, Any] = {"headless": True}
                candidates = sorted((root / ".cache/ms-playwright").glob("chromium-*/chrome-linux*/chrome"))
                if candidates: launch["executable_path"] = str(candidates[-1])
                browser = playwright.chromium.launch(**launch)
                context = browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
                page = context.new_page(); page.goto(f"{server.base_url}{task.environment.start_path}")
                for index, operation in enumerate(task.metadata.get("manual_steps", [])):
                    kind = operation["action"]
                    if kind == "fill":
                        locator = page.get_by_label(operation["label"])
                        _record_step(collector, page, index, operation, lambda locator=locator: locator.fill(str(operation["value"])))
                    elif kind == "select":
                        locator = page.get_by_label(operation["label"])
                        _record_step(collector, page, index, operation, lambda locator=locator: locator.select_option(str(operation["value"])))
                    elif kind == "click":
                        locator = page.get_by_role(operation["role"], name=operation["name"], exact=True)
                        _record_step(collector, page, index, operation, locator.click)
                    elif kind == "download":
                        locator = page.get_by_role(operation["role"], name=operation["name"], exact=True)
                        def perform_download(locator=locator, operation=operation):
                            with page.expect_download() as info: locator.click()
                            info.value.save_as(downloads / operation["filename"])
                        _record_step(collector, page, index, operation, perform_download)
                    else: raise ValueError(f"Unknown manual action: {kind}")
                final_url = page.url
                result = verifier_for(task).verify(task, VerificationContext(base_url=server.base_url, download_dir=downloads, project_root=root, facts={"final_url": final_url}), collector.trace)
                context.close(); browser.close()
        except Exception as caught:
            error = f"{type(caught).__name__}: {caught}"
    if result: collector.record_verification(result)
    passed = bool(result and result.passed and error is None)
    trace = collector.finish("succeeded" if passed else "error" if error else "failed", reward=float(passed), termination_reason="verified_success" if passed else error or "verification_failed")
    manifest = {
        "run_id": run_id, "task_id": task.task_id, "task_version": task.version,
        "task_sha256": hashlib.sha256(task_path.read_bytes()).hexdigest(),
        "fixture_id": task.environment.fixture_id, "fixture_version": task.environment.fixture_version,
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "driver": {"name": "manual-playwright-acceptance-driver", "version": "1.0.0"},
        "seed": 0,
        "budget": task.limits.model_dump(mode="json"),
        "git": _git_state(root),
        "dependency_locks": {"uv_lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest()},
        "started_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
        "final_url": final_url, "faults": task.environment.faults,
        "result": result.model_dump(mode="json", exclude_none=True) if result else {"passed": False, "error": error},
    }
    collector.set_manifest(manifest)
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    database.record(trace, canonical / "canonical_trace.json")
    return run_dir, passed


def _fault_acceptance(fixture_path: Path) -> list[dict[str, Any]]:
    cases = []
    for fault in ("response-delay", "inventory-500", "missing-export", "corrupt-export"):
        with InventoryDemoServer(fixture_path, faults=[fault]) as server:
            observed = False
            if fault == "response-delay":
                started = time.monotonic(); urlopen(f"{server.base_url}/inventory").read(); observed = time.monotonic() - started >= 0.3
            elif fault == "inventory-500":
                try: urlopen(f"{server.base_url}/inventory")
                except HTTPError as error: observed = error.code == 500
            elif fault == "missing-export":
                body = urlopen(f"{server.base_url}/inventory?max_stock=10").read().decode(); observed = 'id="export-csv"' not in body
            else:
                body = urlopen(f"{server.base_url}/export.csv?max_stock=10").read().decode(); observed = "P400" not in body
            truth = server.store.snapshot()["fault_truth"]
            cases.append({"fault": fault, "observed": observed, "truth": truth, "passed": observed and truth["configured"] == [fault] and bool(truth["events"])})
    return cases


def run_admin_acceptance(task_root: Path, output_root: Path, database: ResultStore) -> tuple[Path, bool]:
    task_paths = sorted(Path(task_root).glob("**/*.json"))
    results = []
    for task_path in task_paths:
        task = TaskSpec.load(task_path)
        if task.suite_id not in {"admin-demo-v1", "inventory-demo-v1"}: continue
        run_dir, passed = run_manual_task(task_path, output_root, database)
        results.append({"task_id": task.task_id, "passed": passed, "run_dir": str(run_dir)})
    root = Path(__file__).resolve().parents[2]
    fixture_path = root / "fixtures/inventory/inventory_v1.json"
    faults = _fault_acceptance(fixture_path)
    reset_store = InventoryStore(fixture_path)
    pristine = reset_store.checksum(); reset_store.set_stock_for_test("P100", 99)
    changed = reset_store.checksum(); reset_store.reset()
    reset_check = {"pristine": pristine, "changed": changed, "after_reset": reset_store.checksum(), "passed": pristine != changed and pristine == reset_store.checksum()}
    negative_task = TaskSpec.load(root / "tasks/admin/filter_low_inventory.json")
    with InventoryDemoServer(fixture_path) as server:
        negative = verifier_for(negative_task).verify(negative_task, VerificationContext(base_url=server.base_url, download_dir=output_root, project_root=root, facts={"final_url": f"{server.base_url}/inventory"}))
    verifier_negative_control = {"passed": not negative.passed and negative.failure_type == "agent", "result": negative.model_dump(mode="json", exclude_none=True)}
    compose_contract = {"path": "docker-compose.yml", "passed": (root / "docker-compose.yml").is_file() and "admin-demo:" in (root / "docker-compose.yml").read_text(encoding="utf-8")}
    report_dir = output_root / "acceptance" / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    report_dir.mkdir(parents=True, exist_ok=False)
    payload = {"phase": 2, "git": _git_state(root), "tasks": results, "reset_checksum": reset_check, "verifier_negative_control": verifier_negative_control, "faults": faults, "compose_contract": compose_contract, "passed": 8 <= len(results) <= 10 and all(item["passed"] for item in results) and reset_check["passed"] and verifier_negative_control["passed"] and all(item["passed"] for item in faults) and compose_contract["passed"], "database_runs": database.count()}
    (report_dir / "phase2.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_dir, bool(payload["passed"])


def run_phase3_acceptance(task_id: str, output_root: Path, database: ResultStore) -> tuple[Path, bool]:
    selected: dict[str, dict[str, Any]] = {}
    for row in database.runs():
        if row["task_id"] == task_id and row["framework"] in {"agentlab", "browser-use"}:
            selected[str(row["framework"])] = row
    frameworks = []
    task_hashes: set[str] = set()
    for name in ("agentlab", "browser-use"):
        row = selected.get(name)
        checks: dict[str, Any] = {"present": row is not None}
        if row:
            trace_path = Path(str(row["trace_path"]))
            trace = load_trace(trace_path)
            run_dir = trace_path.parents[1]
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            task_sha = str((manifest.get("task_spec") or {}).get("sha256") or "")
            if task_sha: task_hashes.add(task_sha)
            checks.update({
                "verifier_passed": bool(trace.verification and trace.verification.passed),
                "canonical_trace": trace_path.is_file(),
                "raw_trace": (run_dir / "trace.json").is_file() if name == "agentlab" else (run_dir / "raw_trace.json").is_file(),
                "steps": len(trace.steps),
                "every_step_has_action": bool(trace.steps) and all(bool(step.action.type) for step in trace.steps),
                "every_step_has_screenshot": bool(trace.steps) and all(bool(step.observation.screenshot_ref) for step in trace.steps),
                "run_id": trace.run.run_id,
                "task_spec_sha256": task_sha,
            })
        frameworks.append({"framework": name, "checks": checks, "passed": bool(checks) and all(value for key, value in checks.items() if key not in {"steps", "run_id"})})
    report_dir = output_root / "acceptance" / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    report_dir.mkdir(parents=True, exist_ok=False)
    same_task_spec = len(task_hashes) == 1
    root = Path(__file__).resolve().parents[2]
    payload = {"phase": 3, "git": _git_state(root), "task_id": task_id, "same_task_spec_sha256": next(iter(task_hashes), None) if same_task_spec else None, "same_result_database": database.location, "frameworks": frameworks, "passed": same_task_spec and all(item["passed"] for item in frameworks)}
    (report_dir / "phase3.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_dir, bool(payload["passed"])
