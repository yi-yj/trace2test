"""Run a Qwen tool-calling agent through AgentLab on one MiniWoB task."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any, Iterator, Sequence

import yaml
from dotenv import load_dotenv

from scripts.run_miniwob_smoke import _json_safe, _miniwob_base_url


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/agents/agentlab_qwen_vision.yaml"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task",
        default="click-test",
        help="MiniWoB task name, with or without the miniwob. prefix (default: click-test).",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-steps", type=int, default=5)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Agent YAML configuration (default: AgentLab Qwen vision).",
    )
    parser.add_argument("--headed", action="store_true", help="Show the Chromium window.")
    parser.add_argument("--slow-mo", type=int, default=0, metavar="MS")
    parser.add_argument("--record-video", action="store_true")
    args = parser.parse_args(argv)
    if args.max_steps < 1:
        parser.error("--max-steps must be at least 1")
    if args.slow_mo < 0:
        parser.error("--slow-mo must be zero or greater")
    return args


def _task_id(value: str) -> str:
    task = value.removeprefix("browsergym/").removeprefix("miniwob.")
    if not task:
        raise ValueError("MiniWoB task name cannot be empty")
    return f"miniwob.{task}"


def _load_agent_config(path: Path) -> dict[str, Any]:
    config_path = path if path.is_absolute() else ROOT / path
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("observation"), dict):
        raise ValueError(f"Invalid AgentLab config: {config_path}")
    return config


def _git_state() -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return {"commit": commit, "dirty": dirty}


@contextmanager
def _model_environment(api_key: str, bypass_proxy: bool) -> Iterator[None]:
    """Expose the secret only through env; AgentLab pickles model args to its raw trace."""
    names = (
        "OPENAI_API_KEY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    )
    previous = {name: os.environ.get(name) for name in names}
    os.environ["OPENAI_API_KEY"] = api_key
    if bypass_proxy:
        for name in names[1:]:
            os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _make_agent_args(config: dict[str, Any], model: str, base_url: str):
    from copy import deepcopy

    from agentlab.agents.tool_use_agent import DEFAULT_PROMPT_CONFIG, ToolUseAgentArgs
    from tracetotest.agentlab_qwen import QwenLiteLLMModelArgs

    prompt_config = deepcopy(DEFAULT_PROMPT_CONFIG)
    obs = config["observation"]
    prompt_config.obs.use_screenshot = bool(obs.get("use_screenshot", False))
    prompt_config.obs.use_axtree = bool(obs.get("use_axtree", True))
    prompt_config.obs.use_dom = bool(obs.get("use_dom", False))
    prompt_config.obs.use_som = bool(obs.get("use_som", False))
    prompt_config.action_subsets = tuple(config.get("action_subsets", ["bid"]))
    prompt_config.task_hint.use_task_hint = False
    prompt_config.summarizer.do_summary = False

    provider_model = model if "/" in model else f"openai/{model}"
    model_args = QwenLiteLLMModelArgs(
        model_name=provider_model,
        base_url=base_url,
        api_key=None,
        max_new_tokens=int(config.get("max_new_tokens", 1024)),
        temperature=float(config.get("temperature", 0)),
        vision_support=prompt_config.obs.use_screenshot,
    )
    agent_args = ToolUseAgentArgs(model_args=model_args, config=prompt_config)
    agent_args.agent_name = str(config.get("name", agent_args.agent_name))
    return agent_args, provider_model


def _write_readable_trace(exp_dir: Path) -> dict[str, Any]:
    from agentlab.experiments.loop import get_exp_result

    result = get_exp_result(exp_dir)
    records = []
    for step in result.steps_info:
        obs = step.obs if isinstance(step.obs, dict) else {}
        records.append(
            {
                "step": step.step,
                "observation": {
                    "goal": _json_safe(obs.get("goal_object") or obs.get("goal")),
                    "url": _json_safe(obs.get("url")),
                    "axtree_txt": obs.get("axtree_txt"),
                    "pruned_html": obs.get("pruned_html"),
                    "screenshot": f"screenshot_step_{step.step}.png"
                    if (exp_dir / f"screenshot_step_{step.step}.png").exists()
                    else None,
                },
                "action": step.action,
                "reward": float(step.reward or 0),
                "raw_reward": _json_safe(step.raw_reward),
                "terminated": bool(step.terminated),
                "truncated": bool(step.truncated),
                "stats": _json_safe(step.stats),
            }
        )
    (exp_dir / "trace.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result.summary_info


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    base_url = os.getenv("DASHSCOPE_BASE_URL", "").rstrip("/")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured in .env")
    if not base_url.startswith("https://"):
        raise RuntimeError("DASHSCOPE_BASE_URL must use HTTPS")
    if not os.getenv("MINIWOB_ROOT"):
        raise RuntimeError("MINIWOB_ROOT is not configured in .env")

    config = _load_agent_config(args.config)
    uses_vision = bool(config["observation"].get("use_screenshot", False))
    model_env = "QWEN_VISION_MODEL" if uses_vision else "QWEN_TOOL_MODEL"
    model = os.getenv(model_env, "qwen3-vl-plus" if uses_vision else "qwen-plus")
    agent_args, provider_model = _make_agent_args(config, model, base_url)

    from agentlab.experiments.loop import EnvArgs, ExpArgs

    started_at = datetime.now(timezone.utc)
    artifact_root = Path(os.getenv("ARTIFACT_STORE_PATH", "./artifacts"))
    if not artifact_root.is_absolute():
        artifact_root = ROOT / artifact_root
    exp_root = artifact_root / "agentlab"
    exp_root.mkdir(parents=True, exist_ok=True)
    bypass_proxy = os.getenv("DASHSCOPE_BYPASS_PROXY", "false").casefold() == "true"

    with _miniwob_base_url() as miniwob_url, _model_environment(api_key, bypass_proxy):
        env_args = EnvArgs(
            task_name=_task_id(args.task),
            task_seed=args.seed,
            max_steps=args.max_steps,
            headless=not args.headed,
            record_video=args.record_video,
            slow_mo=args.slow_mo or None,
            task_kwargs={"base_url": miniwob_url},
        )
        experiment = ExpArgs(
            agent_args=agent_args,
            env_args=env_args,
            save_screenshot=True,
            save_som=bool(config["observation"].get("use_som", False)),
        )
        experiment.prepare(exp_root)
        experiment.run()

    exp_dir = Path(experiment.exp_dir)
    summary = _write_readable_trace(exp_dir)
    manifest = {
        "framework": "AgentLab",
        "framework_version": version("agentlab"),
        "browsergym_version": version("browsergym-core"),
        "task_id": _task_id(args.task),
        "task_seed": args.seed,
        "model": model,
        "provider_model": provider_model,
        "pricing": {
            "source": "litellm",
            "unknown_model_fallback": "effective_cost=0",
        },
        "config": config,
        "git": _git_state(),
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "raw_trace": {
            "exp_args": "exp_args.pkl",
            "steps": "step_*.pkl.gz",
            "readable": "trace.json",
        },
    }
    (exp_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"experiment_dir": str(exp_dir), "summary": summary}, indent=2))
    if summary.get("err_msg"):
        raise RuntimeError(f"AgentLab experiment failed; inspect {exp_dir / 'experiment.log'}")


if __name__ == "__main__":
    main()
