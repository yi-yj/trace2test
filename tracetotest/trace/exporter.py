"""Canonical JSON and JSONL exporters."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel

from tracetotest.trace.schema import CanonicalTrace


def _write_jsonl(path: Path, records: Iterable[BaseModel]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(record.model_dump_json(exclude_none=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _write_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def export_trace(trace: CanonicalTrace, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "canonical_trace.json"
    _write_text(
        target,
        json.dumps(trace.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2),
    )
    _write_jsonl(output_dir / "run.jsonl", [trace.run])
    _write_jsonl(output_dir / "steps.jsonl", trace.steps)
    _write_jsonl(output_dir / "events.jsonl", trace.events)
    _write_jsonl(output_dir / "artifacts.jsonl", trace.artifacts)
    return target


def load_trace(path: Path) -> CanonicalTrace:
    """Load and validate a canonical trace, including older supported schema versions."""
    return CanonicalTrace.model_validate_json(Path(path).read_text(encoding="utf-8"))
