import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tracetotest.fixtures import JsonFixture
from tracetotest.tasks import TaskSpec
from tracetotest.trace import (
    ActionRecord,
    EventRecord,
    ObservationRecord,
    RunRecord,
    StepRecord,
    TraceCollector,
    load_trace,
)
from tracetotest.verification.schema import VerificationCheck, VerificationResult

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "tests/fixtures/traces/synthetic_v1"


def _run_record(run_id: str = "run_collector") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        task_id="task",
        suite_id="suite",
        agent_id="agent",
        framework="test",
        status="running",
        started_at=datetime.now(timezone.utc),
        duration_ms=0,
        steps=0,
        manifest_ref="artifact://manifest.json",
    )


def test_synthetic_fixture_round_trips_and_hashes_match() -> None:
    trace = load_trace(SYNTHETIC / "canonical_trace.json")
    assert trace.schema_version == "1.1.0"
    assert trace.verification and trace.verification.passed
    rebuilt = type(trace).model_validate_json(trace.model_dump_json())
    assert rebuilt == trace
    for artifact in trace.artifacts:
        path = SYNTHETIC / "artifacts" / artifact.uri.removeprefix("artifact://")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact.sha256


def test_collector_checkpoints_redacts_and_finalizes(tmp_path) -> None:
    collector = TraceCollector(tmp_path, _run_record())
    collector.set_manifest({"Authorization": "Bearer secret-secret-secret", "input_tokens": 12})
    dom_ref = collector.add_text("dom/step-0.txt", "password=do-not-store", kind="dom")
    collector.record_step(
        StepRecord(
            run_id="run_collector",
            step_index=0,
            timestamp=datetime.now(timezone.utc),
            observation=ObservationRecord(url="https://example.test", dom_ref=dom_ref),
            action=ActionRecord(type="click", parameters={"index": 2, "password": "hidden"}),
        )
    )
    collector.record_event(
        EventRecord(
            event_id="event-0",
            run_id="run_collector",
            step_index=0,
            timestamp_ns=1,
            event_type="tool",
            payload={"api_key": "sk-secret-secret-secret"},
        )
    )
    checkpoint = load_trace(tmp_path / "canonical_trace.json")
    assert checkpoint.run.status == "running"
    assert checkpoint.run.steps == 1
    assert checkpoint.steps[0].action.parameters["password"] == "[REDACTED]"
    assert checkpoint.events[0].payload["api_key"] == "[REDACTED]"
    manifest = json.loads((tmp_path / "artifacts/manifest.json").read_text(encoding="utf-8"))
    assert manifest == {"Authorization": "[REDACTED]", "input_tokens": 12}
    assert "do-not-store" not in (tmp_path / "artifacts/dom/step-0.txt").read_text(encoding="utf-8")

    result = VerificationResult(
        verifier_id="test",
        verifier_version="1",
        task_id="task",
        passed=True,
        score=1,
        checks=[VerificationCheck(name="ok", passed=True)],
        failure_type="none",
    )
    collector.record_verification(result)
    final = collector.finish("succeeded", reward=1, termination_reason="verified_success")
    assert final.run.status == "succeeded"
    assert final.run.termination_reason == "verified_success"
    assert final.verification and final.verification.run_id == "run_collector"


def test_collector_rejects_non_consecutive_steps(tmp_path) -> None:
    collector = TraceCollector(tmp_path, _run_record())
    with pytest.raises(ValueError, match="expected step_index 0"):
        collector.record_step(
            StepRecord(
                run_id="run_collector",
                step_index=1,
                timestamp=datetime.now(timezone.utc),
                observation=ObservationRecord(),
                action=ActionRecord(type="noop"),
            )
        )


def test_collector_rejects_artifact_path_traversal(tmp_path) -> None:
    collector = TraceCollector(tmp_path, _run_record())
    with pytest.raises(ValueError, match="artifact path"):
        collector.add_text("../outside.txt", "unsafe", kind="dom")


def test_task_spec_and_json_fixture_are_versioned_and_resettable() -> None:
    task = TaskSpec.load(ROOT / "tasks/inventory/export_low_inventory.json")
    fixture = JsonFixture(ROOT / task.environment.fixture_path)
    pristine = fixture.pristine_checksum
    fixture.mutable_state()["products"][0]["stock"] = 999
    assert fixture.checksum() != pristine
    fixture.reset()
    assert fixture.checksum() == pristine
    assert task.verifier.verifier_id == "inventory-export"


def test_task_spec_rejects_fixture_path_traversal() -> None:
    data = json.loads((ROOT / "tasks/inventory/export_low_inventory.json").read_text())
    data["environment"]["fixture_path"] = "../secret.json"
    with pytest.raises(ValueError, match="fixture_path"):
        TaskSpec.model_validate(data)
