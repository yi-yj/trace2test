"""Verifier interface and framework-neutral runtime context."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from tracetotest.tasks import TaskSpec
from tracetotest.verification.schema import VerificationResult

if TYPE_CHECKING:
    from tracetotest.trace.schema import CanonicalTrace


class VerificationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    base_url: str
    download_dir: Path
    project_root: Path
    facts: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class Verifier(Protocol):
    verifier_id: str
    verifier_version: str

    def verify(
        self,
        task: TaskSpec,
        context: VerificationContext,
        trace: "CanonicalTrace | None" = None,
    ) -> VerificationResult: ...
