"""Unified Trace2Test runner and adapter command line."""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

from dotenv import load_dotenv

from tracetotest.adapters import AgentLabAdapter, BrowserUseAdapter
from tracetotest.browser_fonts import configure_browser_fonts

ROOT = Path(__file__).resolve().parents[1]
BROWSER_USE_RUNTIME = ROOT / "integrations/browser_use/.venv/bin/python"


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--framework", choices=("agentlab", "browser-use"), required=True)
    parser.add_argument("--task-id", default="web-task")
    parser.add_argument("--start-url", default="https://example.com")
    parser.add_argument("--goal", default="Click the 'More information...' link once.")
    parser.add_argument("--expected-url-contains", default="iana.org")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-steps", type=int, default=5)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--record-video", action="store_true")
    parser.add_argument("--no-virtual-cursor", action="store_true")
    parser.add_argument("--cursor-move-ms", type=int, default=700)
    parser.add_argument("--click-display-ms", type=int, default=450)
    parser.add_argument("--storage-state", type=Path)
    parser.add_argument("--no-vision", action="store_true")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tracetotest")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run either AgentLab or Browser Use")
    _add_run_args(run_parser)
    adapt = subparsers.add_parser("adapt", help="Convert an existing framework run")
    adapt.add_argument("--framework", choices=("agentlab", "browser-use"), required=True)
    adapt.add_argument("--run-dir", type=Path, required=True)
    adapt.add_argument("--output-dir", type=Path)
    inventory = subparsers.add_parser(
        "inventory-e2e", help="Run the resettable inventory task with deterministic verification"
    )
    inventory.add_argument(
        "--task", type=Path, default=ROOT / "tasks/inventory/export_low_inventory.json"
    )
    inventory.add_argument("--output-root", type=Path)
    inventory.add_argument("--headed", action="store_true")
    inventory.add_argument("--slow-mo", type=int, default=0, metavar="MS")
    inventory.add_argument("--no-virtual-cursor", action="store_true")
    inventory.add_argument("--cursor-move-ms", type=int, default=700, metavar="MS")
    inventory.add_argument("--click-display-ms", type=int, default=450, metavar="MS")
    return parser


def _validate_run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    parsed = urlparse(args.start_url)
    local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    if (parsed.scheme != "https" and not local_http) or not parsed.hostname or parsed.username:
        parser.error("--start-url must be HTTPS, or HTTP on localhost, without embedded credentials")
    if args.max_steps < 1:
        parser.error("--max-steps must be at least 1")
    if min(args.cursor_move_ms, args.click_display_ms) < 0:
        parser.error("visualization delays must be zero or greater")
    if args.storage_state:
        args.storage_state = _path(str(args.storage_state))
        if not args.storage_state.is_file():
            parser.error(f"--storage-state does not exist: {args.storage_state}")


def _run_agentlab(args: argparse.Namespace) -> Path:
    from scripts.run_agentlab_web import main as run_agentlab_web

    argv = [
        "--start-url",
        args.start_url,
        "--task-id",
        args.task_id,
        "--goal",
        args.goal,
        "--expected-url-contains",
        args.expected_url_contains,
        "--seed",
        str(args.seed),
        "--max-steps",
        str(args.max_steps),
        "--cursor-move-ms",
        str(args.cursor_move_ms),
        "--click-display-ms",
        str(args.click_display_ms),
    ]
    if args.headed:
        argv.append("--headed")
    if args.record_video:
        argv.append("--record-video")
    if args.no_virtual_cursor:
        argv.append("--no-virtual-cursor")
    if args.storage_state:
        argv.extend(("--storage-state", str(args.storage_state)))
    if args.no_vision:
        argv.extend(("--config", str(ROOT / "configs/agents/agentlab_qwen_a11y.yaml")))
    return run_agentlab_web(argv)


def _chromium_executable() -> Path | None:
    candidates = sorted((ROOT / ".cache/ms-playwright").glob("chromium-*/chrome-linux/chrome"))
    candidates += sorted((ROOT / ".cache/ms-playwright").glob("chromium-*/chrome-linux64/chrome"))
    return candidates[-1] if candidates else None


def _run_browser_use(args: argparse.Namespace) -> Path:
    if not BROWSER_USE_RUNTIME.is_file():
        raise RuntimeError(
            "Browser Use runtime is missing; run: cd integrations/browser_use && "
            "../../.tools/uv sync --python ../../.venv/bin/python"
        )
    load_dotenv(ROOT / ".env")
    configure_browser_fonts()
    model_env = "QWEN_TOOL_MODEL" if args.no_vision else "QWEN_VISION_MODEL"
    model = os.getenv(model_env, "qwen-plus" if args.no_vision else "qwen3-vl-plus").strip()
    base_url = os.getenv("DASHSCOPE_BASE_URL", "").rstrip("/")
    if not os.getenv("DASHSCOPE_API_KEY", "").strip():
        raise RuntimeError("DASHSCOPE_API_KEY is not configured in .env")
    if not base_url.startswith("https://"):
        raise RuntimeError("DASHSCOPE_BASE_URL must use HTTPS")
    artifact_root = _path(os.getenv("ARTIFACT_STORE_PATH", "artifacts"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    run_dir = artifact_root / "browser-use" / f"{stamp}_{args.task_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    command = [
        str(BROWSER_USE_RUNTIME),
        "-m",
        "integrations.browser_use.worker",
        "--run-dir",
        str(run_dir),
        "--task-id",
        args.task_id,
        "--start-url",
        args.start_url,
        "--goal",
        args.goal,
        "--expected-url-contains",
        args.expected_url_contains,
        "--model",
        model,
        "--base-url",
        base_url,
        "--max-steps",
        str(args.max_steps),
        "--seed",
        str(args.seed),
        "--cursor-move-ms",
        str(args.cursor_move_ms),
        "--click-display-ms",
        str(args.click_display_ms),
    ]
    if args.headed:
        command.append("--headed")
    if args.record_video:
        command.append("--record-video")
    if args.no_virtual_cursor:
        command.append("--no-virtual-cursor")
    if args.no_vision:
        command.append("--no-vision")
    if args.storage_state:
        command.extend(("--storage-state", str(args.storage_state)))
    browser = _chromium_executable()
    if browser:
        command.extend(("--browser-executable", str(browser)))
    environment = os.environ.copy()
    environment["XDG_CONFIG_HOME"] = str(ROOT / ".cache/xdg")
    environment["BROWSER_USE_CONFIG_DIR"] = str(ROOT / ".cache/browseruse")
    environment["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / ".cache/ms-playwright")
    environment["PYTHONPATH"] = str(ROOT)
    environment["ANONYMIZED_TELEMETRY"] = "false"
    if environment.get("DASHSCOPE_BYPASS_PROXY", "false").casefold() == "true":
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            environment.pop(name, None)
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    if not (run_dir / "manifest.json").is_file():
        raise RuntimeError(f"Browser Use exited before writing a manifest; inspect {run_dir}")
    trace = BrowserUseAdapter().convert(run_dir)
    print(f"canonical_trace={run_dir / 'canonical/canonical_trace.json'}")
    if completed.returncode or trace.run.status != "succeeded":
        raise RuntimeError(f"Browser Use task did not pass its verifier; inspect {run_dir}")
    return run_dir


def main(argv: Sequence[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "adapt":
        adapter = AgentLabAdapter() if args.framework == "agentlab" else BrowserUseAdapter()
        run_dir = _path(str(args.run_dir))
        output_dir = _path(str(args.output_dir)) if args.output_dir else None
        adapter.convert(run_dir, output_dir)
        print(output_dir or run_dir / "canonical")
        return
    if args.command == "inventory-e2e":
        from scripts.run_inventory_e2e import run

        inventory_argv = [
            "--task",
            str(args.task),
            "--slow-mo",
            str(args.slow_mo),
            "--cursor-move-ms",
            str(args.cursor_move_ms),
            "--click-display-ms",
            str(args.click_display_ms),
        ]
        if args.output_root:
            inventory_argv.extend(("--output-root", str(args.output_root)))
        if args.headed:
            inventory_argv.append("--headed")
        if args.no_virtual_cursor:
            inventory_argv.append("--no-virtual-cursor")
        _, passed = run(inventory_argv)
        if not passed:
            raise SystemExit(1)
        return
    _validate_run(args, parser)
    run_dir = _run_agentlab(args) if args.framework == "agentlab" else _run_browser_use(args)
    print(f"run_dir={run_dir}")
