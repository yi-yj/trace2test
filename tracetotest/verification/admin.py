"""Deterministic verifier for the resettable admin benchmark tasks."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

from tracetotest.tasks import TaskSpec
from tracetotest.verification.base import VerificationContext
from tracetotest.verification.schema import VerificationCheck, VerificationResult


def _resolve(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(path)
    return current


class AdminStateVerifier:
    verifier_id = "admin-state"
    verifier_version = "1.0.0"

    def verify(self, task: TaskSpec, context: VerificationContext, trace=None) -> VerificationResult:
        started = time.monotonic()
        run_id = trace.run.run_id if trace else None
        parsed = urlparse(context.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.username:
            return self._result(task, run_id, started, [], "verifier", "admin verifier only accepts localhost HTTP")
        try:
            with urlopen(f"{context.base_url.rstrip('/')}/api/state", timeout=3) as response:
                state = json.load(response)
        except Exception as error:
            return self._result(task, run_id, started, [], "environment", f"Cannot read app state: {error}")

        checks: list[VerificationCheck] = []
        for configured in task.verifier.config.get("state_checks", []):
            name = str(configured.get("name") or configured["path"])
            try:
                actual = _resolve(state, str(configured["path"]))
                expected = configured.get("equals")
                passed = actual == expected
            except (KeyError, IndexError, ValueError, TypeError) as error:
                actual, expected, passed = f"unavailable: {error}", configured.get("equals"), False
            checks.append(VerificationCheck(name=name, passed=passed, expected=expected, actual=actual))

        expected_url = task.verifier.config.get("url_contains")
        if expected_url:
            actual_url = str(context.facts.get("final_url") or "")
            checks.append(VerificationCheck(name="url_contains", passed=str(expected_url).casefold() in actual_url.casefold(), expected=expected_url, actual=actual_url))

        download = task.verifier.config.get("download")
        if download:
            path = context.download_dir / Path(str(download["filename"])).name
            rows: list[dict[str, str]] = []
            header: list[str] = []
            error = None
            try:
                with path.open("r", encoding="utf-8", newline="") as stream:
                    reader = csv.DictReader(stream); header = list(reader.fieldnames or []); rows = list(reader)
            except (OSError, UnicodeError, csv.Error) as caught:
                error = str(caught)
            checks.extend([
                VerificationCheck(name="download_exists", passed=path.is_file(), expected=path.name, actual=path.name if path.is_file() else None),
                VerificationCheck(name="csv_parseable", passed=path.is_file() and error is None, expected="valid UTF-8 CSV", actual=error or "valid"),
                VerificationCheck(name="csv_header", passed=header == download["header"], expected=download["header"], actual=header),
                VerificationCheck(name="csv_exact_rows", passed=rows == download["rows"], expected=download["rows"], actual=rows),
            ])
        return self._result(task, run_id, started, checks, "none" if checks and all(item.passed for item in checks) else "agent")

    def _result(self, task: TaskSpec, run_id: str | None, started: float, checks: list[VerificationCheck], failure_type: str, error: str | None = None) -> VerificationResult:
        passed = bool(checks) and all(item.passed for item in checks) and error is None
        return VerificationResult(
            verifier_id=self.verifier_id,
            verifier_version=self.verifier_version,
            task_id=task.task_id,
            run_id=run_id,
            passed=passed,
            score=sum(item.passed for item in checks) / len(checks) if checks else 0,
            checks=checks,
            failure_type=failure_type,
            error=error,
            duration_ms=int((time.monotonic() - started) * 1000),
        )


def verifier_for(task: TaskSpec):
    if task.verifier.verifier_id == AdminStateVerifier.verifier_id:
        return AdminStateVerifier()
    if task.verifier.verifier_id == "inventory-export":
        from tracetotest.verification.inventory import InventoryExportVerifier
        return InventoryExportVerifier()
    raise ValueError(f"Unsupported verifier: {task.verifier.verifier_id}")
