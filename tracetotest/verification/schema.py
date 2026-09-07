"""Structured verifier output, independent from any Agent framework."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VerificationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerificationCheck(VerificationModel):
    name: str
    passed: bool
    expected: Any = None
    actual: Any = None
    evidence_refs: list[str] = Field(default_factory=list)
    message: str | None = None


class VerificationResult(VerificationModel):
    verifier_id: str
    verifier_version: str
    task_id: str
    run_id: str | None = None
    passed: bool
    score: float = Field(ge=0, le=1)
    checks: list[VerificationCheck] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    failure_type: Literal["none", "agent", "environment", "verifier"]
    error: str | None = None
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: int = Field(default=0, ge=0)

    @field_validator("verified_at")
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("verified_at must include a timezone")
        return value.astimezone(timezone.utc)
