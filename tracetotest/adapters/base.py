"""Adapter contract."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from tracetotest.trace.schema import CanonicalTrace


class TraceAdapter(Protocol):
    framework: str

    def convert(self, run_dir: Path, output_dir: Path | None = None) -> CanonicalTrace: ...
