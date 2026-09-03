from pathlib import Path

from scripts.list_miniwob_tasks import collect_tasks
from scripts.run_qwen_miniwob import _extract_click_tool_call


ROOT = Path(__file__).resolve().parents[1]


def test_required_local_configuration_is_ignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert "artifacts/" in gitignore
    assert ".benchmarks/" in gitignore


def test_smoke_runner_records_required_artifacts() -> None:
    source = (ROOT / "scripts/run_miniwob_smoke.py").read_text(encoding="utf-8")
    for required_name in (
        "observation.json",
        "action.json",
        "result.json",
        "screenshot-before.png",
        "screenshot-after.png",
        "manifest.json",
    ):
        assert required_name in source


def test_installed_miniwob_catalog_is_complete() -> None:
    tasks = collect_tasks()
    assert len(tasks) == 125
    assert any(task.task_id == "browsergym/miniwob.click-test" for task in tasks)


def test_qwen_click_tool_call_is_validated() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {"name": "click", "arguments": '{"bid":"13"}'},
                        }
                    ]
                }
            }
        ]
    }
    assert _extract_click_tool_call(response, {"13"}) == {
        "id": "call-1",
        "name": "click",
        "bid": "13",
    }
