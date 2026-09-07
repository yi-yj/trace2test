"""Canonical JSON and JSONL exporters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel

from tracetotest.trace.schema import CanonicalTrace


def _write_jsonl(path: Path, records: Iterable[BaseModel]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(record.model_dump_json(exclude_none=True) + "\n")


def export_trace(trace: CanonicalTrace, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "canonical_trace.json"
    target.write_text(
        json.dumps(trace.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_jsonl(output_dir / "run.jsonl", [trace.run])
    _write_jsonl(output_dir / "steps.jsonl", trace.steps)
    _write_jsonl(output_dir / "events.jsonl", trace.events)
    _write_jsonl(output_dir / "artifacts.jsonl", trace.artifacts)
    return target
