"""Content-addressed metadata for run-local artifacts."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from tracetotest.trace.redaction import redact, redact_text
from tracetotest.trace.schema import ArtifactRecord


class LocalArtifactStore:
    def __init__(self, root: Path, run_id: str):
        self.root = root
        self.run_id = run_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.records: list[ArtifactRecord] = []

    def _record(self, relative: Path, kind: str, content_type: str, redacted: bool) -> str:
        target = self.root / relative
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        ref = f"artifact://{relative.as_posix()}"
        self.records.append(
            ArtifactRecord(
                artifact_id=f"art_{len(self.records):05d}",
                run_id=self.run_id,
                type=kind,
                uri=ref,
                sha256=digest,
                content_type=content_type,
                redacted=redacted,
            )
        )
        return ref

    def add_bytes(
        self, relative: str, data: bytes, *, kind: str, content_type: str, redacted: bool
    ) -> str:
        path = Path(relative)
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return self._record(path, kind, content_type, redacted)

    def add_text(self, relative: str, value: str, *, kind: str) -> str:
        return self.add_bytes(
            relative,
            redact_text(value).encode("utf-8"),
            kind=kind,
            content_type="text/plain; charset=utf-8",
            redacted=True,
        )

    def add_json(self, relative: str, value: Any, *, kind: str) -> str:
        data = json.dumps(redact(value), ensure_ascii=False, indent=2).encode("utf-8")
        return self.add_bytes(
            relative, data, kind=kind, content_type="application/json", redacted=True
        )

    def add_file(
        self, relative: str, source: Path, *, kind: str, content_type: str, redacted: bool
    ) -> str:
        path = Path(relative)
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return self._record(path, kind, content_type, redacted)
