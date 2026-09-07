"""Deterministic verifier for the resettable inventory CSV export task."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from urllib.request import urlopen

from tracetotest.fixtures import JsonFixture
from tracetotest.tasks import TaskSpec
from tracetotest.verification.base import VerificationContext
from tracetotest.verification.schema import VerificationCheck, VerificationResult


class InventoryExportVerifier:
    verifier_id = "inventory-export"
    verifier_version = "1.0.0"

    def verify(self, task: TaskSpec, context: VerificationContext, trace=None) -> VerificationResult:
        started = time.monotonic()
        run_id = trace.run.run_id if trace else None
        if task.verifier.verifier_id != self.verifier_id:
            return self._error(
                task, run_id, started, "verifier", f"Unsupported verifier: {task.verifier.verifier_id}"
            )
        try:
            config = task.verifier.config
            threshold = int(config["threshold"])
            expected_file = str(config["downloaded_file"])
            if Path(expected_file).name != expected_file:
                raise ValueError("downloaded_file must be a filename, not a path")
            expected_header = [str(item) for item in config["expected_header"]]
            expected_skus = [str(item) for item in config["expected_skus"]]
            fixture_path = (context.project_root / task.environment.fixture_path).resolve()
            if not fixture_path.is_relative_to(context.project_root.resolve()):
                raise ValueError("fixture_path escapes project_root")
            fixture = JsonFixture(fixture_path)
            expected_rows = [
                {key: str(item[key]) for key in expected_header}
                for item in fixture.snapshot()["products"]
                if int(item["stock"]) < threshold
            ]
            if [row["sku"] for row in expected_rows] != expected_skus:
                raise ValueError("Task expected_skus do not match the versioned fixture")
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
            return self._error(task, run_id, started, "verifier", str(error))

        parsed_url = urlparse(context.base_url)
        if (
            parsed_url.scheme != "http"
            or parsed_url.hostname not in {"127.0.0.1", "localhost"}
            or parsed_url.username
        ):
            return self._error(
                task, run_id, started, "verifier", "inventory verifier only accepts a localhost HTTP URL"
            )
        try:
            with urlopen(f"{context.base_url.rstrip('/')}/api/state", timeout=3) as response:
                state = json.load(response)
        except Exception as error:
            return self._error(task, run_id, started, "environment", f"Cannot read app state: {error}")

        checks: list[VerificationCheck] = []
        download = context.download_dir / expected_file
        checks.append(
            VerificationCheck(
                name="download_exists",
                passed=download.is_file(),
                expected=expected_file,
                actual=expected_file if download.is_file() else None,
                evidence_refs=[f"artifact://downloads/{expected_file}"] if download.is_file() else [],
            )
        )
        rows: list[dict[str, str]] = []
        actual_header: list[str] = []
        parse_error = None
        if download.is_file():
            try:
                with download.open("r", encoding="utf-8", newline="") as stream:
                    reader = csv.DictReader(stream)
                    actual_header = list(reader.fieldnames or [])
                    rows = list(reader)
            except (OSError, UnicodeError, csv.Error) as error:
                parse_error = str(error)
        checks.append(
            VerificationCheck(
                name="csv_parseable",
                passed=download.is_file() and parse_error is None,
                expected="valid UTF-8 CSV",
                actual=parse_error or "valid",
            )
        )
        checks.append(
            VerificationCheck(
                name="csv_header",
                passed=actual_header == expected_header,
                expected=expected_header,
                actual=actual_header,
            )
        )
        actual_skus = [row.get("sku", "") for row in rows]
        checks.append(
            VerificationCheck(
                name="csv_exact_rows",
                passed=actual_skus == expected_skus,
                expected=expected_skus,
                actual=actual_skus,
            )
        )
        normalized_rows = [{key: str(row.get(key, "")) for key in expected_header} for row in rows]
        checks.append(
            VerificationCheck(
                name="csv_exact_content",
                passed=normalized_rows == expected_rows,
                expected=expected_rows,
                actual=normalized_rows,
            )
        )
        invalid_stocks = []
        for row in rows:
            try:
                if int(row.get("stock", threshold)) >= threshold:
                    invalid_stocks.append(row)
            except (TypeError, ValueError):
                invalid_stocks.append(row)
        checks.append(
            VerificationCheck(
                name="every_row_below_threshold",
                passed=bool(rows) and not invalid_stocks,
                expected=f"stock < {threshold}",
                actual=invalid_stocks,
            )
        )
        checks.extend(
            [
                VerificationCheck(
                    name="backend_filter",
                    passed=state.get("active_max_stock") == threshold,
                    expected=threshold,
                    actual=state.get("active_max_stock"),
                ),
                VerificationCheck(
                    name="single_export",
                    passed=state.get("export_count") == 1,
                    expected=1,
                    actual=state.get("export_count"),
                ),
                VerificationCheck(
                    name="backend_export_rows",
                    passed=state.get("last_export_skus") == expected_skus,
                    expected=expected_skus,
                    actual=state.get("last_export_skus"),
                ),
                VerificationCheck(
                    name="fixture_unchanged",
                    passed=state.get("fixture_checksum") == fixture.pristine_checksum,
                    expected=fixture.pristine_checksum,
                    actual=state.get("fixture_checksum"),
                ),
                VerificationCheck(
                    name="no_database_mutation",
                    passed=state.get("database_mutations") == 0,
                    expected=0,
                    actual=state.get("database_mutations"),
                ),
            ]
        )
        passed = all(check.passed for check in checks)
        score = sum(check.passed for check in checks) / len(checks)
        evidence = sorted({ref for check in checks for ref in check.evidence_refs})
        return VerificationResult(
            verifier_id=self.verifier_id,
            verifier_version=self.verifier_version,
            task_id=task.task_id,
            run_id=run_id,
            passed=passed,
            score=score,
            checks=checks,
            evidence_refs=evidence,
            failure_type="none" if passed else "agent",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def _error(
        self,
        task: TaskSpec,
        run_id: str | None,
        started: float,
        failure_type: Literal["environment", "verifier"],
        error: str,
    ) -> VerificationResult:
        return VerificationResult(
            verifier_id=self.verifier_id,
            verifier_version=self.verifier_version,
            task_id=task.task_id,
            run_id=run_id,
            passed=False,
            score=0,
            failure_type=failure_type,
            error=error,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
