"""Convert the Browser Use callback trace to the canonical schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tracetotest.adapters.common import parse_structured_action, parse_time, safe_number, stable_run_id
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


class BrowserUseAdapter:
    framework = "browser-use"

    def convert(self, run_dir: Path, output_dir: Path | None = None) -> CanonicalTrace:
        run_dir = Path(run_dir)
        trace_path = run_dir / "raw_trace.json"
        manifest_path = run_dir / "manifest.json"
        if not trace_path.is_file() or not manifest_path.is_file():
            raise FileNotFoundError("Browser Use adapter requires raw_trace.json and manifest.json")
        raw: dict[str, Any] = json.loads(trace_path.read_text(encoding="utf-8"))
        manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        started = parse_time(manifest.get("started_at"))
        finished = parse_time(manifest.get("finished_at"), started)
        run_id = stable_run_id(self.framework, run_dir.name, started.isoformat())
        canonical_dir = output_dir or run_dir / "canonical"
        store = LocalArtifactStore(canonical_dir / "artifacts", run_id)
        manifest_ref = store.add_json("raw/manifest.json", manifest, kind="manifest")
        store.add_json("raw/trace.json", raw, kind="raw_trace")

        steps: list[StepRecord] = []
        for index, item in enumerate(raw.get("steps", [])):
            before_ref = self._screenshot(store, run_dir, item.get("screenshot_before"), index, "before")
            after_ref = self._screenshot(store, run_dir, item.get("screenshot_after"), index, "after")
            dom_ref = (
                store.add_text(f"dom/step-{index}.txt", str(item["dom"]), kind="dom")
                if item.get("dom")
                else None
            )
            actions = item.get("actions") or [{}]
            action = parse_structured_action(actions[0])
            decision = item.get("decision") or {}
            results = item.get("results") or []
            error = next((str(result.get("error")) for result in results if result.get("error")), None)
            effect = next(
                (str(result.get("extracted_content")) for result in results if result.get("extracted_content")),
                None,
            )
            steps.append(
                StepRecord(
                    run_id=run_id,
                    step_index=index,
                    timestamp=parse_time(item.get("timestamp"), started),
                    observation=ObservationRecord(
                        url=redact_url(str(item.get("url") or "")),
                        title=str(item.get("title") or "") or None,
                        screenshot_ref=before_ref,
                        dom_ref=dom_ref,
                        a11y_ref=dom_ref,
                    ),
                    decision=DecisionRecord(
                        current_goal=decision.get("current_goal"),
                        evaluation_previous_goal=decision.get("evaluation_previous_goal"),
                        expected_effect=decision.get("expected_effect"),
                    ),
                    action=action,
                    after=AfterState(
                        url=redact_url(str(item.get("url_after") or "")) or None,
                        title=str(item.get("title_after") or "") or None,
                        screenshot_ref=after_ref,
                        observed_effect=effect,
                    ),
                    error=error,
                )
            )

        result = manifest.get("result") or {}
        usage = manifest.get("usage") or {}
        agent_finish = None
        for index, item in reversed(list(enumerate(raw.get("steps", [])))):
            done_params = next(
                (
                    action["done"]
                    for action in item.get("actions") or []
                    if isinstance(action, dict) and isinstance(action.get("done"), dict)
                ),
                None,
            )
            done_result = next(
                (
                    action_result
                    for action_result in item.get("results") or []
                    if action_result.get("is_done") is True
                ),
                None,
            )
            if done_params is not None or done_result is not None:
                done_params = done_params or {}
                done_result = done_result or {}
                agent_finish = {
                    "step_index": index,
                    "timestamp": parse_time(item.get("timestamp"), started),
                    "declared_success": done_result.get(
                        "success", done_params.get("success")
                    ),
                    "reason": done_params.get("text")
                    or done_result.get("extracted_content")
                    or "",
                }
                break
        success = bool(result.get("success"))
        status = "error" if result.get("error") else "succeeded" if success else "failed"
        if result.get("truncated") and not result.get("error"):
            status = "truncated"
        failure_type = str(result.get("failure_type") or ("none" if success else "agent"))
        if failure_type not in {"none", "agent", "environment", "verifier"}:
            failure_type = "verifier"
        if failure_type == "environment":
            termination_reason = "environment_error"
        elif result.get("error"):
            termination_reason = "agent_error"
        elif result.get("truncated"):
            termination_reason = "max_steps"
        elif agent_finish:
            termination_reason = "agent_finish"
        else:
            termination_reason = "verified"
        verification = VerificationResult(
            verifier_id="url_contains" if result.get("expected_url_contains") else "agent_result",
            verifier_version="1.0.0",
            task_id=str(manifest.get("task_id", "web-task")),
            run_id=run_id,
            passed=success,
            score=1.0 if success else 0.0,
            checks=[
                VerificationCheck(
                    name="url_contains" if result.get("expected_url_contains") else "agent_result",
                    passed=success,
                    expected=result.get("expected_url_contains", True),
                    actual=result.get("final_url", result.get("agent_success")),
                )
            ],
            failure_type=failure_type,
            error=str(result.get("error") or "") or None,
        )
        events = []
        if agent_finish:
            events.append(
                EventRecord(
                    event_id="evt_agent_finish",
                    run_id=run_id,
                    step_index=agent_finish["step_index"],
                    timestamp_ns=int(
                        agent_finish["timestamp"].timestamp() * 1_000_000_000
                    ),
                    event_type="agent_finish",
                    payload=redact(
                        {
                            "declared_success": agent_finish["declared_success"],
                            "reason": agent_finish["reason"],
                        }
                    ),
                )
            )
        events.append(
            EventRecord(
                event_id="evt_verification",
                run_id=run_id,
                step_index=len(steps) - 1 if steps else None,
                timestamp_ns=int(finished.timestamp() * 1_000_000_000),
                event_type="verification",
                payload=redact(result),
            )
        )
        for step_index, item in enumerate(raw.get("steps", [])):
            timestamp_ns = int(parse_time(item.get("timestamp"), started).timestamp() * 1_000_000_000)
            if item.get("recent_events"):
                events.append(
                    EventRecord(
                        event_id=f"evt_{step_index:04d}_browser",
                        run_id=run_id,
                        step_index=step_index,
                        timestamp_ns=timestamp_ns,
                        event_type="browser_event_summary",
                        payload={"summary": redact(str(item["recent_events"]))},
                    )
                )
            for event_index, request in enumerate(item.get("pending_network_requests") or []):
                events.append(
                    EventRecord(
                        event_id=f"evt_{step_index:04d}_network_{event_index:03d}",
                        run_id=run_id,
                        step_index=step_index,
                        timestamp_ns=timestamp_ns,
                        event_type="network_request",
                        payload=redact(request),
                    )
                )
            for result_index, action_result in enumerate(item.get("results") or []):
                for file_index, attachment in enumerate(action_result.get("attachments") or []):
                    events.append(
                        EventRecord(
                            event_id=f"evt_{step_index:04d}_file_{result_index:03d}_{file_index:03d}",
                            run_id=run_id,
                            step_index=step_index,
                            timestamp_ns=timestamp_ns,
                            event_type="file_artifact",
                            payload={"path": redact(str(attachment))},
                        )
                    )
        trace = CanonicalTrace(
            run=RunRecord(
                run_id=run_id,
                task_id=str(manifest.get("task_id", "web-task")),
                suite_id=str(manifest.get("suite_id", "web")),
                agent_id=str(manifest.get("agent_id", "browser-use-qwen")),
                framework=self.framework,
                status=status,
                reward=1.0 if success else 0.0,
                started_at=started,
                duration_ms=max(0, int((finished - started).total_seconds() * 1000)),
                steps=len(steps),
                input_tokens=safe_number(usage.get("input_tokens"), int),
                output_tokens=safe_number(usage.get("output_tokens"), int),
                estimated_cost=safe_number(usage.get("total_cost"), float),
                manifest_ref=manifest_ref,
                termination_reason=termination_reason,
            ),
            steps=steps,
            events=events,
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
