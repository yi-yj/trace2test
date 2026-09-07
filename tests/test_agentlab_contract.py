from pathlib import Path

from scripts.run_agentlab_miniwob import (
    DEFAULT_CONFIG,
    _load_agent_config,
    _make_agent_args,
    _parse_args,
    _task_id,
)
from tracetotest.agentlab_qwen import QwenLiteLLMModelArgs
from tracetotest.agent_completion import AgentCompletionActionSet


ROOT = Path(__file__).resolve().parents[1]


def test_agentlab_runner_defaults_to_vision_and_click_test() -> None:
    args = _parse_args([])
    assert args.config == DEFAULT_CONFIG
    assert _task_id(args.task) == "miniwob.click-test"
    assert _load_agent_config(args.config)["observation"]["use_screenshot"] is True
    assert args.no_virtual_cursor is False
    assert args.cursor_move_ms == 700
    assert args.click_display_ms == 450


def test_agentlab_a11y_config_uses_bid_actions_without_screenshot() -> None:
    config = _load_agent_config(ROOT / "configs/agents/agentlab_qwen_a11y.yaml")
    assert config["observation"]["use_screenshot"] is False
    assert config["observation"]["use_axtree"] is True
    assert config["action_subsets"] == ["bid"]


def test_real_site_action_set_has_agent_controlled_finish() -> None:
    action_set = AgentCompletionActionSet(("bid",), multiaction=False)
    tools = action_set.to_tool_description()

    assert "finish_task" in action_set.action_set
    finish_tool = next(tool for tool in tools if tool["name"] == "finish_task")
    assert finish_tool["parameters"]["required"] == ["reason"]
    code = action_set.to_python_code('finish_task("goal verified")')
    messages = []
    exec(code, {"DEMO_MODE": False, "send_message_to_user": messages.append})
    assert messages == ["TRACE2TEST_TASK_COMPLETE: goal verified"]


def test_real_site_runner_enables_finish_without_changing_miniwob() -> None:
    config = _load_agent_config(DEFAULT_CONFIG)
    web_args, _ = _make_agent_args(
        config, "qwen-test", "https://example.test/v1", enable_finish=True
    )
    miniwob_args, _ = _make_agent_args(config, "qwen-test", "https://example.test/v1")

    assert "finish_task" in web_args.action_set.action_set
    assert miniwob_args.action_set is None


def test_agentlab_runner_records_raw_and_readable_traces() -> None:
    source = (ROOT / "scripts/run_agentlab_miniwob.py").read_text(encoding="utf-8")
    for artifact in (
        "step_*.pkl.gz",
        "trace.json",
        "manifest.json",
        "screenshot_step_",
        "last_action_error",
    ):
        assert artifact in source


def test_qwen_model_args_do_not_persist_api_key() -> None:
    args = QwenLiteLLMModelArgs(
        model_name="openai/qwen-test", base_url="https://example.test/v1", api_key=None
    )
    assert args.api_key is None


def test_qwen_unknown_price_is_warning_only(caplog) -> None:
    args = QwenLiteLLMModelArgs(
        model_name="openai/qwen-unmapped-test",
        base_url="https://example.test/v1",
        api_key=None,
    )
    with caplog.at_level("WARNING"):
        model = args.make_model()
    assert model.pricing_available is False
    assert model.get_effective_cost(None) == 0
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "WARNING"
    assert "effective_cost=0" in caplog.records[0].message
