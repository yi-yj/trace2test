"""Versioned, framework-neutral Trace2Test records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tracetotest.verification.schema import VerificationResult

SCHEMA_VERSION = "1.1.0"


class TraceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc)


class RunRecord(TraceModel):
    run_id: str
    task_id: str
    suite_id: str
    agent_id: str
    framework: str
    status: Literal["running", "succeeded", "failed", "error", "truncated"]
    reward: float = 0.0
    started_at: datetime
    duration_ms: int = Field(ge=0)
    steps: int = Field(ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0)
    manifest_ref: str
    termination_reason: str | None = None

    _normalize_time = field_validator("started_at")(_utc)


class ObservationRecord(TraceModel):
    url: str = ""
    title: str | None = None
    screenshot_ref: str | None = None
    dom_ref: str | None = None
    a11y_ref: str | None = None


class DecisionRecord(TraceModel):
    current_goal: str | None = None
    evaluation_previous_goal: str | None = None
    action_reason: str | None = None
    expected_effect: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class ActionRecord(TraceModel):
    type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    coordinates: tuple[float, float] | None = None
    target_text: str | None = None
    target_element_id: str | None = None


class AfterState(TraceModel):
    url: str | None = None
    title: str | None = None
    screenshot_ref: str | None = None
    observed_effect: str | None = None
    reward: float | None = None


class StepRecord(TraceModel):
    run_id: str
    step_index: int = Field(ge=0)
    timestamp: datetime
    observation: ObservationRecord
    decision: DecisionRecord = Field(default_factory=DecisionRecord)
    action: ActionRecord
    after: AfterState = Field(default_factory=AfterState)
    error: str | None = None

    _normalize_time = field_validator("timestamp")(_utc)


class EventRecord(TraceModel):
    event_id: str
    run_id: str
    step_index: int | None = Field(default=None, ge=0)
    timestamp_ns: int = Field(ge=0)
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ArtifactRecord(TraceModel):
    artifact_id: str
    run_id: str
    type: str
    uri: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_type: str
    redacted: bool


class CanonicalTrace(TraceModel):
    schema_version: Literal["1.0.0", "1.1.0"] = SCHEMA_VERSION
    run: RunRecord
    steps: list[StepRecord]
    events: list[EventRecord] = Field(default_factory=list)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    verification: VerificationResult | None = None

    @model_validator(mode="after")
    def validate_relationships(self) -> "CanonicalTrace":
        run_id = self.run.run_id
        if self.run.steps != len(self.steps):
            raise ValueError("run.steps must equal the number of step records")
        if [step.step_index for step in self.steps] != list(range(len(self.steps))):
            raise ValueError("step_index values must be consecutive and start at zero")
        children = [*self.steps, *self.events, *self.artifacts]
        if any(record.run_id != run_id for record in children):
            raise ValueError("all child records must reference run.run_id")
        if self.verification:
            if self.verification.task_id != self.run.task_id:
                raise ValueError("verification.task_id must reference run.task_id")
            if self.verification.run_id not in (None, run_id):
                raise ValueError("verification.run_id must reference run.run_id")
        return self
