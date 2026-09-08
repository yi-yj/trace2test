"""SQLite result database shared by every runner and framework adapter."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tracetotest.trace import CanonicalTrace

SCHEMA_VERSION = 1


class ResultStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def from_url(cls, value: str, project_root: Path) -> "ResultStore":
        prefix = "sqlite:///"
        if not value.startswith(prefix):
            raise ValueError("DATABASE_URL currently supports sqlite:/// URLs")
        path = Path(value.removeprefix(prefix))
        return cls(path if path.is_absolute() else project_root / path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, suite_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL, framework TEXT NOT NULL, status TEXT NOT NULL,
                    reward REAL NOT NULL, started_at TEXT NOT NULL, duration_ms INTEGER NOT NULL,
                    steps INTEGER NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
                    estimated_cost REAL NOT NULL, termination_reason TEXT, manifest_ref TEXT NOT NULL,
                    trace_path TEXT NOT NULL, payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS steps (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    step_index INTEGER NOT NULL, action_type TEXT NOT NULL,
                    screenshot_ref TEXT, payload_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, step_index)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    type TEXT NOT NULL, uri TEXT NOT NULL, sha256 TEXT NOT NULL, payload_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, artifact_id)
                );
                CREATE TABLE IF NOT EXISTS verifications (
                    run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
                    verifier_id TEXT NOT NULL, passed INTEGER NOT NULL, score REAL NOT NULL,
                    failure_type TEXT NOT NULL, payload_json TEXT NOT NULL
                );
            """)
            db.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    def record(self, trace: CanonicalTrace, trace_path: Path) -> None:
        run = trace.run
        with self._connect() as db:
            db.execute(
                """INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run.run_id, run.task_id, run.suite_id, run.agent_id, run.framework, run.status,
                 run.reward, run.started_at.isoformat(), run.duration_ms, run.steps, run.input_tokens,
                 run.output_tokens, run.estimated_cost, run.termination_reason, run.manifest_ref,
                 str(Path(trace_path).resolve()), run.model_dump_json(exclude_none=True)),
            )
            db.execute("DELETE FROM steps WHERE run_id=?", (run.run_id,))
            db.execute("DELETE FROM artifacts WHERE run_id=?", (run.run_id,))
            db.execute("DELETE FROM verifications WHERE run_id=?", (run.run_id,))
            db.executemany(
                "INSERT INTO steps VALUES (?, ?, ?, ?, ?)",
                [(run.run_id, step.step_index, step.action.type, step.observation.screenshot_ref,
                  step.model_dump_json(exclude_none=True)) for step in trace.steps],
            )
            db.executemany(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?)",
                [(item.artifact_id, run.run_id, item.type, item.uri, item.sha256,
                  item.model_dump_json(exclude_none=True)) for item in trace.artifacts],
            )
            if trace.verification:
                value = trace.verification
                db.execute("INSERT INTO verifications VALUES (?, ?, ?, ?, ?, ?)",
                           (run.run_id, value.verifier_id, int(value.passed), value.score,
                            value.failure_type, value.model_dump_json(exclude_none=True)))

    def runs(self) -> list[dict[str, object]]:
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                "SELECT run_id, task_id, framework, status, steps, trace_path FROM runs ORDER BY started_at"
            )]

    def count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
