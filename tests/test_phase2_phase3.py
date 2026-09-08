import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
import yaml

from apps.inventory_demo import InventoryDemoServer, InventoryStore
from tracetotest.cli import _load_task, _parser
from tracetotest.storage import ResultStore
from tracetotest.tasks import TaskSpec
from tracetotest.trace import ActionRecord, CanonicalTrace, ObservationRecord, RunRecord, StepRecord
from tracetotest.verification import AdminStateVerifier, VerificationContext

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/inventory/inventory_v1.json"


def _trace(run_id: str, framework: str) -> CanonicalTrace:
    return CanonicalTrace(run=RunRecord(
        run_id=run_id, task_id="filter-low-inventory", suite_id="admin-demo-v1",
        agent_id=framework, framework=framework, status="succeeded", reward=1,
        started_at=datetime.now(timezone.utc), duration_ms=1, steps=1,
        manifest_ref="artifact://manifest.json",
    ), steps=[StepRecord(
        run_id=run_id, step_index=0, timestamp=datetime.now(timezone.utc),
        observation=ObservationRecord(url="http://localhost/inventory", screenshot_ref="artifact://screenshots/0.png"),
        action=ActionRecord(type="click"),
    )])


def test_admin_suite_has_ten_versioned_tasks_covering_required_features() -> None:
    tasks = [TaskSpec.load(path) for path in sorted((ROOT / "tasks").glob("**/*.json"))]
    assert len(tasks) == 10
    assert len({task.task_id for task in tasks}) == 10
    families = {task.metadata["task_family"] for task in tasks}
    assert {"login", "inventory", "orders", "data_export"} <= families
    assert all(task.version == "1.0.0" and task.metadata["deterministic"] for task in tasks)


def test_task_spec_populates_unified_run_arguments() -> None:
    args = _parser().parse_args(["run", "--framework", "agentlab", "--task", "tasks/admin/filter_low_inventory.json"])
    task, path = _load_task(args)
    assert path == ROOT / "tasks/admin/filter_low_inventory.json"
    assert args.task_id == task.task_id == "filter-low-inventory"
    assert args.max_steps == task.limits.max_steps
    assert args.expected_url_contains == "/inventory?max_stock=10"


def test_admin_reset_restores_checksum_and_runtime_state() -> None:
    store = InventoryStore(FIXTURE)
    pristine = store.checksum()
    assert store.login("operator@example.test", "demo-pass")
    assert store.update_order("O100", "shipped")
    assert store.checksum() != pristine
    store.reset()
    state = store.snapshot()
    assert store.checksum() == pristine
    assert state["authenticated_user"] is None
    assert state["database_mutations"] == 0


@pytest.mark.parametrize("fault", ["response-delay", "inventory-500", "missing-export", "corrupt-export"])
def test_fault_injections_have_truth_records(fault: str) -> None:
    with InventoryDemoServer(FIXTURE, faults=[fault]) as server:
        if fault == "inventory-500":
            with pytest.raises(HTTPError): urlopen(f"{server.base_url}/inventory")
        elif fault == "missing-export":
            urlopen(f"{server.base_url}/inventory?max_stock=10").read()
        elif fault == "corrupt-export":
            urlopen(f"{server.base_url}/export.csv?max_stock=10").read()
        else:
            urlopen(f"{server.base_url}/inventory").read()
        truth = server.store.snapshot()["fault_truth"]
        assert truth["configured"] == [fault]
        assert truth["events"]
        assert len(truth["truth_sha256"]) == 64


def test_admin_verifier_distinguishes_success_and_agent_failure(tmp_path) -> None:
    task = TaskSpec.load(ROOT / "tasks/admin/filter_low_inventory.json")
    with InventoryDemoServer(FIXTURE) as server:
        urlopen(f"{server.base_url}/inventory?max_stock=10").read()
        context = VerificationContext(base_url=server.base_url, download_dir=tmp_path, project_root=ROOT, facts={"final_url": f"{server.base_url}/inventory?max_stock=10"})
        assert AdminStateVerifier().verify(task, context).passed
        server.store.reset()
        failed = AdminStateVerifier().verify(task, context)
        assert not failed.passed and failed.failure_type == "agent"


def test_result_database_accepts_both_frameworks(tmp_path) -> None:
    store = ResultStore(tmp_path / "results.sqlite3")
    for framework in ("agentlab", "browser-use"):
        trace = _trace(f"run-{framework}", framework)
        path = tmp_path / f"{framework}.json"; path.write_text(trace.model_dump_json())
        store.record(trace, path)
    rows = store.runs()
    assert store.count() == 2
    assert {row["framework"] for row in rows} == {"agentlab", "browser-use"}


def test_compose_starts_admin_service_contract() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    service = compose["services"]["admin-demo"]
    assert service["ports"] == ["127.0.0.1:8080:8080"]
    assert "healthcheck" in service
