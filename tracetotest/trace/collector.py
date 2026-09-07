"""Incremental canonical trace collection with crash-tolerant checkpoints."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Literal

from tracetotest.trace.artifacts import LocalArtifactStore
from tracetotest.trace.exporter import export_trace
from tracetotest.trace.redaction import redact
from tracetotest.trace.schema import CanonicalTrace, EventRecord, RunRecord, StepRecord
from tracetotest.verification.schema import VerificationResult

FinalStatus = Literal["succeeded", "failed", "error", "truncated"]


class TraceCollector:
    """Persist each accepted record immediately and finalize one canonical trace."""

    def __init__(self, output_dir: Path, run: RunRecord):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run = run.model_copy(update={"status": "running", "steps": 0})
        self.steps: list[StepRecord] = []
        self.events: list[EventRecord] = []
        self.verification: VerificationResult | None = None
        self.artifacts = LocalArtifactStore(self.output_dir / "artifacts", self.run.run_id)
        self._started_monotonic = time.monotonic()
        self._checkpoint()

    @property
    def trace(self) -> CanonicalTrace:
        current_run = self.run.model_copy(update={"steps": len(self.steps)})
        return CanonicalTrace(
            run=current_run,
            steps=self.steps,
            events=self.events,
            artifacts=self.artifacts.records,
            verification=self.verification,
        )

    def add_bytes(
        self, relative: str, data: bytes, *, kind: str, content_type: str, redacted: bool
    ) -> str:
        ref = self.artifacts.add_bytes(
            relative, data, kind=kind, content_type=content_type, redacted=redacted
        )
        self._checkpoint()
        return ref

    def add_text(self, relative: str, value: str, *, kind: str) -> str:
        ref = self.artifacts.add_text(relative, value, kind=kind)
        self._checkpoint()
        return ref

    def add_json(self, relative: str, value: Any, *, kind: str) -> str:
        ref = self.artifacts.add_json(relative, value, kind=kind)
        self._checkpoint()
        return ref

    def add_file(
        self,
        relative: str,
        source: Path,
        *,
        kind: str,
        content_type: str,
        redacted: bool,
    ) -> str:
        ref = self.artifacts.add_file(
            relative, source, kind=kind, content_type=content_type, redacted=redacted
        )
        self._checkpoint()
        return ref

    def set_manifest(self, manifest: dict[str, Any]) -> str:
        ref = self.add_json("manifest.json", manifest, kind="manifest")
        self.run = self.run.model_copy(update={"manifest_ref": ref})
        self._checkpoint()
        return ref

    def record_step(self, step: StepRecord) -> None:
        expected = len(self.steps)
        if step.run_id != self.run.run_id:
            raise ValueError("step.run_id must match the collector run_id")
        if step.step_index != expected:
            raise ValueError(f"expected step_index {expected}, got {step.step_index}")
        safe_step = StepRecord.model_validate(redact(step.model_dump(mode="python")))
        self.steps.append(safe_step)
        self._checkpoint()

    def record_event(self, event: EventRecord) -> None:
        if event.run_id != self.run.run_id:
            raise ValueError("event.run_id must match the collector run_id")
        if event.step_index is not None and event.step_index >= len(self.steps):
            raise ValueError("event.step_index must reference an existing step")
        safe_event = EventRecord.model_validate(redact(event.model_dump(mode="python")))
        self.events.append(safe_event)
        self._checkpoint()

    def record_verification(self, result: VerificationResult) -> None:
        if result.task_id != self.run.task_id:
            raise ValueError("verification.task_id must match the collector task_id")
        if result.run_id not in (None, self.run.run_id):
            raise ValueError("verification.run_id must match the collector run_id")
        safe_result = VerificationResult.model_validate(redact(result.model_dump(mode="python")))
        self.verification = safe_result.model_copy(update={"run_id": self.run.run_id})
        self._checkpoint()

    def finish(
        self,
        status: FinalStatus,
        *,
        reward: float | None = None,
        termination_reason: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        estimated_cost: float | None = None,
    ) -> CanonicalTrace:
        updates: dict[str, Any] = {
            "status": status,
            "steps": len(self.steps),
            "duration_ms": max(0, int((time.monotonic() - self._started_monotonic) * 1000)),
            "termination_reason": termination_reason,
        }
        for name, value in (
            ("reward", reward),
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
            ("estimated_cost", estimated_cost),
        ):
            if value is not None:
                updates[name] = value
        run_data = self.run.model_dump(mode="python")
        run_data.update(updates)
        self.run = RunRecord.model_validate(run_data)
        return self._checkpoint()

    def _checkpoint(self) -> CanonicalTrace:
        trace = self.trace
        export_trace(trace, self.output_dir)
        return trace
