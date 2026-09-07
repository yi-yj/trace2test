import hashlib
import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from tracetotest.adapters import AgentLabAdapter, BrowserUseAdapter
from tracetotest.trace import ActionRecord, CanonicalTrace, ObservationRecord, RunRecord, StepRecord
from tracetotest.trace.redaction import REDACTED, redact


def test_schema_enforces_step_count_and_utc() -> None:
    run = RunRecord(
        run_id="run_1",
        task_id="task",
        suite_id="suite",
        agent_id="agent",
        framework="test",
        status="succeeded",
        started_at=datetime.now(timezone.utc),
        duration_ms=1,
        steps=1,
        manifest_ref="artifact://manifest.json",
    )
    with pytest.raises(ValidationError, match="run.steps"):
        CanonicalTrace(run=run, steps=[])
    with pytest.raises(ValidationError, match="timezone"):
        StepRecord(
            run_id="run_1",
            step_index=0,
            timestamp=datetime(2026, 1, 1),
            observation=ObservationRecord(),
            action=ActionRecord(type="noop"),
        )


def test_redaction_removes_credentials_and_url_userinfo() -> None:
    cleaned = redact(
        {
            "Authorization": "Bearer abcdefghijklmnopqrstuvwxyz",
            "url": "https://user:password@example.com/path?token=secret&view=list",
            "nested": {"api_key": "sk-secretsecretsecret"},
        }
    )
    assert cleaned["Authorization"] == REDACTED
    assert cleaned["nested"]["api_key"] == REDACTED
    assert "user:password" not in cleaned["url"]
    assert f"token={REDACTED}" in cleaned["url"] or "token=%5BREDACTED%5D" in cleaned["url"]
    assert redact({"input_tokens": 123, "access_token": "secret"}) == {
        "input_tokens": 123,
        "access_token": REDACTED,
    }


def _assert_artifacts(trace: CanonicalTrace, canonical_dir) -> None:
    assert (canonical_dir / "canonical_trace.json").is_file()
    assert (canonical_dir / "steps.jsonl").read_text(encoding="utf-8").count("\n") == 1
    for artifact in trace.artifacts:
        path = canonical_dir / "artifacts" / artifact.uri.removeprefix("artifact://")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact.sha256


def test_agentlab_adapter_emits_canonical_trace(tmp_path) -> None:
    run_dir = tmp_path / "agentlab"
    run_dir.mkdir()
    (run_dir / "screenshot_step_0.png").write_bytes(b"before")
    (run_dir / "screenshot_step_1.png").write_bytes(b"after")
    (run_dir / "trace.json").write_text(
        json.dumps(
            [
                {
                    "step": 0,
                    "observation": {
                        "url": "https://example.com/?token=secret",
                        "axtree_txt": "button More information",
                        "pruned_html": "<button>More information</button>",
                        "screenshot": "screenshot_step_0.png",
                    },
                    "action": "click(bid='7')",
                    "reward": 0,
                    "stats": {"step_elapsed": 0.1},
                },
                {
                    "step": 1,
                    "observation": {
                        "url": "https://iana.org/",
                        "screenshot": "screenshot_step_1.png",
                    },
                    "action": None,
                    "reward": 1,
                },
            ]
        ),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "task_id": "web-task",
                "goal": "click",
                "config": {"name": "agentlab-test"},
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "summary": {"cum_reward": 1, "stats.cum_input_tokens": 10},
                "verifier": {"success": True},
            }
        ),
        encoding="utf-8",
    )
    trace = AgentLabAdapter().convert(run_dir)
    assert trace.run.framework == "agentlab"
    assert trace.run.status == "succeeded"
    assert trace.steps[0].action.type == "click"
    assert trace.steps[0].action.target_element_id == "7"
    assert "secret" not in trace.steps[0].observation.url
    _assert_artifacts(trace, run_dir / "canonical")


def test_browser_use_adapter_emits_same_schema_and_events(tmp_path) -> None:
    run_dir = tmp_path / "browser-use"
    (run_dir / "screenshots").mkdir(parents=True)
    (run_dir / "screenshots/step-1-before.png").write_bytes(b"before")
    (run_dir / "screenshots/step-1-after.png").write_bytes(b"after")
    (run_dir / "raw_trace.json").write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "timestamp": "2026-01-01T00:00:00Z",
                        "url": "https://example.com/",
                        "title": "Example",
                        "dom": "[7]<a>More information</a>",
                        "screenshot_before": "screenshots/step-1-before.png",
                        "screenshot_after": "screenshots/step-1-after.png",
                        "decision": {"current_goal": "click link"},
                        "actions": [{"click": {"index": 7}}],
                        "results": [{"extracted_content": "navigated", "attachments": ["result.txt"]}],
                        "pending_network_requests": [{"url": "https://example.com/api", "method": "GET"}],
                        "url_after": "https://iana.org/",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "task_id": "web-task",
                "agent_id": "browser-use-qwen",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "usage": {"input_tokens": 12, "output_tokens": 3},
                "result": {"success": True},
            }
        ),
        encoding="utf-8",
    )
    trace = BrowserUseAdapter().convert(run_dir)
    assert trace.run.framework == "browser-use"
    assert trace.steps[0].action.type == "click"
    assert {event.event_type for event in trace.events} == {
        "verification",
        "network_request",
        "file_artifact",
    }
    _assert_artifacts(trace, run_dir / "canonical")
