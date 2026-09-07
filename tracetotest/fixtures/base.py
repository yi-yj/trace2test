"""Reusable fixture reset and checksum primitives."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class FixtureController(Protocol):
    fixture_id: str
    fixture_version: str

    def reset(self) -> None: ...

    def snapshot(self) -> dict[str, Any]: ...

    def checksum(self) -> str: ...


class JsonFixture:
    def __init__(self, path: Path):
        self.path = Path(path)
        source = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(source, dict):
            raise ValueError(f"Fixture must contain an object: {self.path}")
        self.fixture_id = str(source["fixture_id"])
        self.fixture_version = str(source["version"])
        self._pristine = source
        self._state: dict[str, Any] = {}
        self.reset()

    def reset(self) -> None:
        self._state = copy.deepcopy(self._pristine)

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self._state)

    def mutable_state(self) -> dict[str, Any]:
        return self._state

    def checksum(self) -> str:
        payload = json.dumps(self._state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def pristine_checksum(self) -> str:
        payload = json.dumps(
            self._pristine, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
