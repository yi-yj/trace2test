"""Run a bounded AgentLab + Qwen demonstration on a public HTTPS website."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

from dotenv import load_dotenv

from scripts.run_agentlab_miniwob import (
    DEFAULT_CONFIG,
    ROOT,
    _git_state,
    _load_agent_config,
    _make_agent_args,
    _model_environment,
    _sha256_file,
    _write_readable_trace,
)
from tracetotest.browser_fonts import configure_browser_fonts
from tracetotest.agent_completion import COMPLETION_ACTION_VERSION
from tracetotest.browser_tasks import TASK_ID as WEB_TASK_ID
from tracetotest.browser_tasks import ensure_browser_tasks_registered
from tracetotest.proxy import browser_proxy_environment, resolve_browser_proxy


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-url", default="https://example.com")
    parser.add_argument("--task-id", default="web-task")
    parser.add_argument(
        "--goal",
        default="Click the 'More information...' link once.",
        help="Use a read-only, non-destructive goal for public-site demonstrations.",
    )
    parser.add_argument("--expected-url-contains", default="iana.org")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-steps", type=int, default=1)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--storage-state",
        type=Path,
        help="Private Playwright state captured under .auth/ (cookies and localStorage).",
    )
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--slow-mo", type=int, default=0, metavar="MS")
    parser.add_argument("--record-video", action="store_true")
    parser.add_argument("--no-virtual-cursor", action="store_true")
    parser.add_argument("--cursor-move-ms", type=int, default=700, metavar="MS")
    parser.add_argument("--click-display-ms", type=int, default=450, metavar="MS")
    parser.add_argument("--navigation-timeout-ms", type=int, default=30_000, metavar="MS")
    parser.add_argument("--return-run-dir-on-failure", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    parsed_url = urlparse(args.start_url)
    local_http = parsed_url.scheme == "http" and parsed_url.hostname in {"127.0.0.1", "localhost"}
    if (parsed_url.scheme != "https" and not local_http) or not parsed_url.hostname or parsed_url.username:
        parser.error("--start-url must be HTTPS, or HTTP on localhost, without embedded credentials")
    if min(args.max_steps, args.navigation_timeout_ms) < 1:
        parser.error("--max-steps and --navigation-timeout-ms must be positive")
    if min(args.slow_mo, args.cursor_move_ms, args.click_display_ms) < 0:
        parser.error("visualization delays must be zero or greater")
    if args.storage_state is not None:
        state_path = args.storage_state if args.storage_state.is_absolute() else ROOT / args.storage_state
        if not state_path.is_file():
            parser.error(f"--storage-state does not exist: {state_path}")
        args.storage_state = state_path
    return args


def _last_url(exp_dir: Path) -> str:
    trace = json.loads((exp_dir / "trace.json").read_text(encoding="utf-8"))
    urls = [item["observation"].get("url") for item in trace]
    return next((str(url) for url in reversed(urls) if url), "")


def _failure_type(summary: dict, verifier_success: bool) -> str:
    error = str(summary.get("err_msg") or "")
    if error and (
        "EnvironmentNavigationError" in error
        or (not summary.get("n_steps") and "Page.goto" in error and "TimeoutError" in error)
    ):
        return "environment"
    if error or not verifier_success:
        return "agent"
    return "none"


def main(argv: Sequence[str] | None = None) -> Path:
    args = _parse_args(argv)
    load_dotenv(ROOT / ".env")
    font_config = configure_browser_fonts()
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    base_url = os.getenv("DASHSCOPE_BASE_URL", "").rstrip("/")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured in .env")
    if not base_url.startswith("https://"):
        raise RuntimeError("DASHSCOPE_BASE_URL must use HTTPS")

    config = _load_agent_config(args.config)
    uses_vision = bool(config["observation"].get("use_screenshot", False))
    model_env = "QWEN_VISION_MODEL" if uses_vision else "QWEN_TOOL_MODEL"
    model = os.getenv(model_env, "qwen3-vl-plus" if uses_vision else "qwen-plus")
    agent_args, provider_model = _make_agent_args(
        config, model, base_url, enable_finish=True
    )
    browser_proxy = resolve_browser_proxy()
    ensure_browser_tasks_registered()

    from agentlab.experiments.loop import ExpArgs
    from tracetotest.agentlab_visualization import VisualEnvArgs

    started_at = datetime.now(timezone.utc)
    artifact_root = Path(os.getenv("ARTIFACT_STORE_PATH", "./artifacts"))
    if not artifact_root.is_absolute():
        artifact_root = ROOT / artifact_root
    exp_root = artifact_root / "agentlab-web"
    exp_root.mkdir(parents=True, exist_ok=True)
    bypass_proxy = os.getenv("DASHSCOPE_BYPASS_PROXY", "true").casefold() == "true"

    with browser_proxy_environment(browser_proxy), _model_environment(api_key, bypass_proxy):
        env_args = VisualEnvArgs(
            task_name=WEB_TASK_ID,
            task_seed=args.seed,
            max_steps=args.max_steps,
            headless=not args.headed,
            record_video=args.record_video,
            slow_mo=args.slow_mo or None,
            task_kwargs={
                "start_url": args.start_url,
                "goal": args.goal,
                "navigation_timeout_ms": args.navigation_timeout_ms,
            },
            storage_state=str(args.storage_state) if args.storage_state else None,
            virtual_cursor=args.headed and not args.no_virtual_cursor,
            cursor_move_duration_ms=args.cursor_move_ms,
            click_display_ms=args.click_display_ms,
            browser_proxy_enabled=browser_proxy.configured,
        )
        experiment = ExpArgs(agent_args=agent_args, env_args=env_args, save_screenshot=True)
        experiment.prepare(exp_root)
        experiment.run()

    exp_dir = Path(experiment.exp_dir)
    summary = _write_readable_trace(exp_dir)
    final_url = _last_url(exp_dir)
    verifier_success = args.expected_url_contains.casefold() in final_url.casefold()
    verifier = {
        "type": "url_contains",
        "version": "1.0.0",
        "expected": args.expected_url_contains,
        "actual": final_url,
        "success": verifier_success,
        "failure_type": _failure_type(summary, verifier_success),
        "error": summary.get("err_msg"),
        "note": "BrowserGym openended reward is always 0; use this deterministic verifier.",
    }
    (exp_dir / "verification.json").write_text(
        json.dumps(verifier, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = {
        "framework": "AgentLab",
        "framework_version": version("agentlab"),
        "browsergym_version": version("browsergym-core"),
        "task_id": args.task_id,
        "task_seed": args.seed,
        "start_url": args.start_url,
        "goal": args.goal,
        "model": model,
        "provider_model": provider_model,
        "config": config,
        "config_sha256": _sha256_file(args.config if args.config.is_absolute() else ROOT / args.config),
        "dependency_locks": {"uv_lock_sha256": _sha256_file(ROOT / "uv.lock")},
        "dataset": {"name": "live-https-site", "versioned": False},
        "browser_fonts": font_config,
        "network": {
            "model_bypass_proxy": bypass_proxy,
            "browser_proxy": browser_proxy.safe_summary(),
            "navigation_timeout_ms": args.navigation_timeout_ms,
        },
        "authentication": {
            "storage_state": args.storage_state.name if args.storage_state else None,
            "state_contents_recorded": False,
        },
        "git": _git_state(),
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "verifier": verifier,
        "completion": {
            "action": "finish_task",
            "version": COMPLETION_ACTION_VERSION,
            "controlled_by": "agent",
            "verifier_timing": "post_run",
        },
        "visualization": {
            "headed": args.headed,
            "record_video": args.record_video,
            "virtual_cursor": args.headed and not args.no_virtual_cursor,
        },
    }
    (exp_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    from tracetotest.adapters import AgentLabAdapter

    canonical = AgentLabAdapter().convert(exp_dir)
    print(
        json.dumps(
            {
                "experiment_dir": str(exp_dir),
                "canonical_trace": str(exp_dir / "canonical/canonical_trace.json"),
                "status": canonical.run.status,
                "verifier": verifier,
            },
            indent=2,
        )
    )
    if (summary.get("err_msg") or not verifier["success"]) and not args.return_run_dir_on_failure:
        raise RuntimeError(f"Real-site demo failed; inspect {exp_dir}")
    return exp_dir


if __name__ == "__main__":
    main()
