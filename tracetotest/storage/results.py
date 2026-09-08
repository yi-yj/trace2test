"""PostgreSQL result store with a SQLite fallback for isolated unit tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from tracetotest.trace import CanonicalTrace, load_trace

SCHEMA_VERSION = 1
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, suite_id TEXT NOT NULL,
        agent_id TEXT NOT NULL, framework TEXT NOT NULL, status TEXT NOT NULL,
        reward DOUBLE PRECISION NOT NULL, started_at TEXT NOT NULL, duration_ms BIGINT NOT NULL,
        steps INTEGER NOT NULL, input_tokens BIGINT NOT NULL, output_tokens BIGINT NOT NULL,
        estimated_cost DOUBLE PRECISION NOT NULL, termination_reason TEXT, manifest_ref TEXT NOT NULL,
        trace_path TEXT NOT NULL, payload_json TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS steps (
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
        step_index INTEGER NOT NULL, action_type TEXT NOT NULL,
        screenshot_ref TEXT, payload_json TEXT NOT NULL,
        PRIMARY KEY (run_id, step_index)
    )""",
    """CREATE TABLE IF NOT EXISTS artifacts (
        artifact_id TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
        type TEXT NOT NULL, uri TEXT NOT NULL, sha256 TEXT NOT NULL, payload_json TEXT NOT NULL,
        PRIMARY KEY (run_id, artifact_id)
    )""",
    """CREATE TABLE IF NOT EXISTS verifications (
        run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
        verifier_id TEXT NOT NULL, passed BOOLEAN NOT NULL, score DOUBLE PRECISION NOT NULL,
        failure_type TEXT NOT NULL, payload_json TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS runs_task_framework_idx ON runs(task_id, framework, started_at)",
)


class ResultStore:
    def __init__(self, path: Path):
        """Create a SQLite store. Intended for unit tests and offline fallback only."""
        self.backend = "sqlite"
        self.path: Path | None = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._dsn: str | None = None
        self._initialize()

    @classmethod
    def from_url(cls, value: str, project_root: Path) -> "ResultStore":
        if value.startswith("sqlite:///"):
            path = Path(value.removeprefix("sqlite:///"))
            return cls(path if path.is_absolute() else project_root / path)
        if value.startswith(("postgresql://", "postgres://")):
            store = cls.__new__(cls)
            store.backend = "postgresql"
            store.path = None
            store._dsn = value
            store._initialize()
            return store
        raise ValueError("DATABASE_URL must use postgresql:// or sqlite:///")

    @property
    def location(self) -> str:
        if self.backend == "sqlite":
            return str(self.path)
        parts = urlsplit(self._dsn or "")
        host = parts.hostname or "localhost"
        port = f":{parts.port}" if parts.port else ""
        return f"postgresql://{host}{port}{parts.path}"

    def _connect(self):
        if self.backend == "sqlite":
            connection = sqlite3.connect(self.path, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            return connection
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:
            raise RuntimeError("PostgreSQL storage requires the psycopg[binary] dependency") from error
        return psycopg.connect(self._dsn, connect_timeout=10, row_factory=dict_row)

    def _sql(self, statement: str) -> str:
        return statement if self.backend == "sqlite" else statement.replace("?", "%s")

    def _initialize(self) -> None:
        with self._connect() as db:
            cursor = db.cursor()
            for statement in _SCHEMA:
                cursor.execute(statement)
            cursor.execute(
                self._sql("INSERT INTO metadata(key, value) VALUES ('schema_version', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value"),
                (str(SCHEMA_VERSION),),
            )

    def record(self, trace: CanonicalTrace, trace_path: Path) -> None:
        run = trace.run
        with self._connect() as db:
            cursor = db.cursor()
            cursor.execute(self._sql("DELETE FROM runs WHERE run_id=?"), (run.run_id,))
            cursor.execute(
                self._sql("""INSERT INTO runs (
                    run_id, task_id, suite_id, agent_id, framework, status, reward, started_at,
                    duration_ms, steps, input_tokens, output_tokens, estimated_cost,
                    termination_reason, manifest_ref, trace_path, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""),
                (run.run_id, run.task_id, run.suite_id, run.agent_id, run.framework, run.status,
                 run.reward, run.started_at.isoformat(), run.duration_ms, run.steps, run.input_tokens,
                 run.output_tokens, run.estimated_cost, run.termination_reason, run.manifest_ref,
                 str(Path(trace_path).resolve()), run.model_dump_json(exclude_none=True)),
            )
            cursor.executemany(
                self._sql("INSERT INTO steps VALUES (?, ?, ?, ?, ?)"),
                [(run.run_id, step.step_index, step.action.type, step.observation.screenshot_ref,
                  step.model_dump_json(exclude_none=True)) for step in trace.steps],
            )
            cursor.executemany(
                self._sql("INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?)"),
                [(item.artifact_id, run.run_id, item.type, item.uri, item.sha256,
                  item.model_dump_json(exclude_none=True)) for item in trace.artifacts],
            )
            if trace.verification:
                value = trace.verification
                cursor.execute(
                    self._sql("INSERT INTO verifications VALUES (?, ?, ?, ?, ?, ?)"),
                    (run.run_id, value.verifier_id, value.passed, value.score,
                     value.failure_type, value.model_dump_json(exclude_none=True)),
                )

    def runs(self) -> list[dict[str, object]]:
        with self._connect() as db:
            rows = db.cursor().execute(
                "SELECT run_id, task_id, framework, status, steps, trace_path FROM runs ORDER BY started_at"
            ).fetchall()
            return [dict(row) for row in rows]

    def count(self) -> int:
        with self._connect() as db:
            row = db.cursor().execute("SELECT COUNT(*) FROM runs").fetchone()
            return int(row[0] if self.backend == "sqlite" else row["count"])

    def migrate_from(self, source: "ResultStore") -> int:
        migrated = 0
        for row in source.runs():
            trace_path = Path(str(row["trace_path"]))
            if not trace_path.is_file():
                raise FileNotFoundError(f"Cannot migrate missing canonical trace: {trace_path}")
            self.record(load_trace(trace_path), trace_path)
            migrated += 1
        return migrated
