from pathlib import Path

from scripts.run_agentlab_miniwob import DEFAULT_CONFIG, _load_agent_config, _parse_args, _task_id


ROOT = Path(__file__).resolve().parents[1]


def test_agentlab_runner_defaults_to_vision_and_click_test() -> None:
    args = _parse_args([])
    assert args.config == DEFAULT_CONFIG
    assert _task_id(args.task) == "miniwob.click-test"
    assert _load_agent_config(args.config)["observation"]["use_screenshot"] is True


def test_agentlab_a11y_config_uses_bid_actions_without_screenshot() -> None:
    config = _load_agent_config(ROOT / "configs/agents/agentlab_qwen_a11y.yaml")
    assert config["observation"]["use_screenshot"] is False
    assert config["observation"]["use_axtree"] is True
    assert config["action_subsets"] == ["bid"]


def test_agentlab_runner_records_raw_and_readable_traces() -> None:
    source = (ROOT / "scripts/run_agentlab_miniwob.py").read_text(encoding="utf-8")
    for artifact in ("step_*.pkl.gz", "trace.json", "manifest.json", "screenshot_step_"):
        assert artifact in source

