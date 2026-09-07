"""Convert AgentLab's readable/raw experiment files to canonical traces."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from tracetotest.adapters.common import parse_agentlab_action, parse_time, stable_run_id
from tracetotest.trace import (
    AfterState,
    CanonicalTrace,
    DecisionRecord,
    EventRecord,
    LocalArtifactStore,
    ObservationRecord,
    RunRecord,
    StepRecord,
    export_trace,
)
from tracetotest.trace.redaction import redact, redact_url
from tracetotest.verification import VerificationCheck, VerificationResult


def _failure_type(verifier: dict[str, Any], summary: dict[str, Any], succeeded: bool) -> str:
    explicit = str(verifier.get("failure_type") or "")
    if explicit in {"none", "agent", "environment", "verifier"}:
        return explicit
    error = str(summary.get("err_msg") or "")
    if "EnvironmentNavigationError" in error or (
        not summary.get("n_steps") and "Page.goto" in error and "TimeoutError" in error
    ):
        return "environment"
    return "none" if succeeded else "agent"


class AgentLabAdapter:
    framework = "agentlab"

    def convert(self, run_dir: Path, output_dir: Path | None = None) -> CanonicalTrace:
        run_dir = Path(run_dir)
        trace_path = run_dir / "trace.json"
        manifest_path = run_dir / "manifest.json"
        if not trace_path.is_file() or not manifest_path.is_file():
            raise FileNotFoundError("AgentLab adapter requires trace.json and manifest.json")
        raw_steps: list[dict[str, Any]] = json.loads(trace_path.read_text(encoding="utf-8"))
        manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        started = parse_time(manifest.get("started_at"))
        finished = parse_time(manifest.get("finished_at"), started)
        run_id = stable_run_id(self.framework, run_dir.name, started.isoformat())
        canonical_dir = output_dir or run_dir / "canonical"
        store = LocalArtifactStore(canonical_dir / "artifacts", run_id)
        manifest_ref = store.add_json("raw/manifest.json", manifest, kind="manifest")
        store.add_json("raw/trace.json", raw_steps, kind="raw_trace")

        actionable = [(position, item) for position, item in enumerate(raw_steps) if item.get("action")]
        steps: list[StepRecord] = []
        elapsed_ms = 0.0
        for index, (position, item) in enumerate(actionable):
            observation = item.get("observation") or {}
            next_item = raw_steps[position + 1] if position + 1 < len(raw_steps) else {}
            after_observation = next_item.get("observation") or {}
            before_ref = self._screenshot(store, run_dir, observation.get("screenshot"), index, "before")
            after_ref = self._screenshot(
                store, run_dir, after_observation.get("screenshot"), index, "after"
            )
            a11y_ref = (
                store.add_text(f"a11y/step-{index}.txt", observation["axtree_txt"], kind="a11y")
                if observation.get("axtree_txt")
                else None
            )
            dom_ref = (
                store.add_text(f"dom/step-{index}.html", observation["pruned_html"], kind="dom")
                if observation.get("pruned_html")
                else None
            )
            timestamp = started + timedelta(milliseconds=elapsed_ms)
            step_elapsed = float((item.get("stats") or {}).get("step_elapsed", 0) or 0)
            elapsed_ms += step_elapsed * 1000
            steps.append(
                StepRecord(
                    run_id=run_id,
                    step_index=index,
                    timestamp=timestamp,
                    observation=ObservationRecord(
                        url=redact_url(str(observation.get("url") or "")),
                        screenshot_ref=before_ref,
                        dom_ref=dom_ref,
                        a11y_ref=a11y_ref,
                    ),
                    decision=DecisionRecord(current_goal=str(manifest.get("goal") or "") or None),
                    action=parse_agentlab_action(item["action"]),
                    after=AfterState(
                        url=redact_url(str(after_observation.get("url") or "")) or None,
                        screenshot_ref=after_ref,
                        observed_effect=str(after_observation.get("last_action_error") or "") or None,
                        reward=float(next_item.get("reward", item.get("reward", 0)) or 0),
                    ),
                    error=str(after_observation.get("last_action_error") or "") or None,
                )
            )

        summary = manifest.get("summary") or {}
        verifier = manifest.get("verifier") or {}
        error = summary.get("err_msg")
        truncated = bool(summary.get("truncated"))
        succeeded = bool(verifier.get("success")) if verifier else float(summary.get("cum_reward", 0) or 0) > 0
        status = "error" if error else "truncated" if truncated else "succeeded" if succeeded else "failed"
        failure_type = _failure_type(verifier, summary, succeeded)
        verification = (
            VerificationResult(
                verifier_id=str(verifier.get("type") or "agentlab-result"),
                verifier_version=str(verifier.get("version") or "1.0.0"),
                task_id=str(manifest.get("task_id", "unknown")),
                run_id=run_id,
                passed=succeeded,
                score=1.0 if succeeded else 0.0,
                checks=[
                    VerificationCheck(
                        name=str(verifier.get("type") or "task_success"),
                        passed=succeeded,
                        expected=verifier.get("expected", True),
                        actual=verifier.get("actual", succeeded),
                    )
                ],
                failure_type=failure_type,
                error=str(verifier.get("error") or "") or None,
            )
            if verifier
            else None
        )
        trace = CanonicalTrace(
            run=RunRecord(
                run_id=run_id,
                task_id=str(manifest.get("task_id", "unknown")),
                suite_id="browsergym" if str(manifest.get("task_id", "")).startswith("miniwob.") else "web",
                agent_id=str((manifest.get("config") or {}).get("name", "agentlab")),
                framework=self.framework,
                status=status,
                reward=float(summary.get("cum_reward", 1 if succeeded else 0) or 0),
                started_at=started,
                duration_ms=max(0, int((finished - started).total_seconds() * 1000)),
                steps=len(steps),
                input_tokens=int(summary.get("stats.cum_input_tokens", 0) or 0),
                output_tokens=int(summary.get("stats.cum_output_tokens", 0) or 0),
                estimated_cost=float(summary.get("stats.cum_cost", 0) or 0),
                manifest_ref=manifest_ref,
                termination_reason=(
                    "environment_error"
                    if failure_type == "environment"
                    else "agent_error" if error else "max_steps" if truncated else "verified"
                ),
            ),
            steps=steps,
            events=[
                EventRecord(
                    event_id="evt_verification",
                    run_id=run_id,
                    step_index=len(steps) - 1 if steps else None,
                    timestamp_ns=int(finished.timestamp() * 1_000_000_000),
                    event_type="verification",
                    payload=redact(verifier or {"success": succeeded}),
                )
            ],
            artifacts=store.records,
            verification=verification,
        )
        export_trace(trace, canonical_dir)
        return trace

    @staticmethod
    def _screenshot(
        store: LocalArtifactStore, run_dir: Path, filename: Any, index: int, phase: str
    ) -> str | None:
        if not filename:
            return None
        source = run_dir / str(filename)
        if not source.is_file():
            return None
        return store.add_file(
            f"screenshots/step-{index}-{phase}.png",
            source,
            kind="screenshot",
            content_type="image/png",
            redacted=False,
        )
