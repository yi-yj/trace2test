from pathlib import Path

from scripts.list_miniwob_tasks import collect_tasks
from scripts.run_qwen_miniwob import _extract_click_tool_call, _parse_args


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


def test_qwen_visualization_arguments() -> None:
    defaults = _parse_args([])
    assert defaults.headed is False
    assert defaults.slow_mo == 1000
    assert defaults.click_display_ms == 450
    assert defaults.no_pause is False
    assert defaults.no_virtual_cursor is False

    visual = _parse_args(
        [
            "--headed",
            "--slow-mo",
            "250",
            "--click-display-ms",
            "300",
            "--no-pause",
            "--no-virtual-cursor",
        ]
    )
    assert visual.headed is True
    assert visual.slow_mo == 250
    assert visual.click_display_ms == 300
    assert visual.no_pause is True
    assert visual.no_virtual_cursor is True

    source = (ROOT / "scripts/run_qwen_miniwob.py").read_text(encoding="utf-8")
    assert "virtual-cursor-idle.png" in source
    assert "virtual-cursor-click.png" in source
