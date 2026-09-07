import json
from pathlib import Path
from urllib.request import urlopen

from apps.inventory_demo import InventoryDemoServer, InventoryStore
from scripts.run_inventory_e2e import run
from tracetotest.cli import _parser
from tracetotest.tasks import TaskSpec
from tracetotest.trace import load_trace
from tracetotest.verification import InventoryExportVerifier, VerificationContext, Verifier

ROOT = Path(__file__).resolve().parents[1]
TASK_PATH = ROOT / "tasks/inventory/export_low_inventory.json"
FIXTURE_PATH = ROOT / "fixtures/inventory/inventory_v1.json"


def test_inventory_cli_visualization_defaults() -> None:
    args = _parser().parse_args(["inventory-e2e", "--headed"])
    assert args.headed is True
    assert args.no_virtual_cursor is False
    assert args.cursor_move_ms == 700
    assert args.click_display_ms == 450


def test_inventory_store_reset_restores_checksum() -> None:
    store = InventoryStore(FIXTURE_PATH)
    pristine = store.checksum()
    store.set_stock_for_test("P100", 100)
    assert store.checksum() != pristine
    assert store.snapshot()["database_mutations"] == 1
    store.reset()
    assert store.checksum() == pristine
    assert store.snapshot()["database_mutations"] == 0


def test_inventory_verifier_distinguishes_success_and_agent_failure(tmp_path) -> None:
    task = TaskSpec.load(TASK_PATH)
    verifier = InventoryExportVerifier()
    assert isinstance(verifier, Verifier)
    with InventoryDemoServer(FIXTURE_PATH) as server:
        with urlopen(f"{server.base_url}/inventory?max_stock=10"):
            pass
        with urlopen(f"{server.base_url}/export.csv?max_stock=10") as response:
            (tmp_path / "low-inventory.csv").write_bytes(response.read())
        context = VerificationContext(
            base_url=server.base_url,
            download_dir=tmp_path,
            project_root=ROOT,
        )
        result = verifier.verify(task, context)
        assert result.passed
        assert result.failure_type == "none"

        (tmp_path / "low-inventory.csv").write_text("sku,name,stock\nP200,Keyboard,12\n")
        failure = verifier.verify(task, context)
        assert not failure.passed
        assert failure.failure_type == "agent"
        assert {item.name for item in failure.checks if not item.passed} >= {
            "csv_exact_rows",
            "every_row_below_threshold",
        }


def test_inventory_export_full_browser_e2e(tmp_path) -> None:
    run_dir, passed = run(["--output-root", str(tmp_path)])
    assert passed
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    trace = load_trace(run_dir / "canonical/canonical_trace.json")
    assert manifest["result"]["passed"] is True
    assert trace.run.status == "succeeded"
    assert trace.run.termination_reason == "verified_success"
    assert trace.verification and trace.verification.passed
    assert [step.action.type for step in trace.steps] == ["fill_and_submit", "click"]
    assert {event.event_type for event in trace.events} == {"file_artifact", "verification"}
