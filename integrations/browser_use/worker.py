"""Execute Browser Use with Qwen and emit a safe callback-level raw trace."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any, Sequence

from tracetotest.cursor_overlay import (
    INSTALL_CURSOR_SCRIPT,
    MOVE_TO_POINT_SCRIPT,
    SET_CURSOR_STATE_SCRIPT,
)
from tracetotest.trace.redaction import redact
from tracetotest.proxy import runtime_browser_proxy, runtime_browser_proxy_summary

CLICK_ACTIONS = frozenset({"click"})


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--task-id", default="web-task")
    parser.add_argument("--start-url", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--expected-url-contains", default="")
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--record-video", action="store_true")
    parser.add_argument("--no-virtual-cursor", action="store_true")
    parser.add_argument("--cursor-move-ms", type=int, default=700)
    parser.add_argument("--click-display-ms", type=int, default=450)
    parser.add_argument("--navigation-timeout-ms", type=int, default=30_000)
    parser.add_argument("--storage-state", type=Path)
    parser.add_argument("--browser-executable", type=Path)
    parser.add_argument("--no-vision", action="store_true")
    args = parser.parse_args(argv)
    if min(args.max_steps, args.navigation_timeout_ms) < 1:
        parser.error("--max-steps and --navigation-timeout-ms must be positive")
    return args


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(value), ensure_ascii=False, indent=2), encoding="utf-8")


def _save_screenshot(run_dir: Path, step: int, phase: str, encoded: str | None) -> str | None:
    if not encoded:
        return None
    if encoded.startswith("data:"):
        encoded = encoded.partition(",")[2]
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        return None
    relative = Path("screenshots") / f"step-{step}-{phase}.png"
    target = run_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative.as_posix()


def _git_state(root: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    return {"commit": commit, "dirty": dirty}


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


async def _run(args: argparse.Namespace) -> bool:
    # Browser Use initializes user config during import, so the parent command
    # points XDG_CONFIG_HOME/BROWSER_USE_CONFIG_DIR at the repository cache first.
    os.environ["BROWSER_USE_ACTION_TIMEOUT_S"] = str(args.navigation_timeout_ms / 1000)
    from browser_use import Agent, Browser
    from browser_use.llm.openai.like import ChatOpenAILike

    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured in .env")
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    started = datetime.now(timezone.utc)
    records: list[dict[str, Any]] = []

    browser_kwargs: dict[str, Any] = {
        "headless": not args.headed,
        "highlight_elements": True,
        "viewport": {"width": 1280, "height": 900},
        "keep_alive": False,
        "enable_default_extensions": False,
    }
    if args.browser_executable:
        browser_kwargs["executable_path"] = str(args.browser_executable.resolve())
    if args.storage_state:
        browser_kwargs["storage_state"] = str(args.storage_state.resolve())
    if args.record_video:
        browser_kwargs["record_video_dir"] = str((run_dir / "video").resolve())
    browser_proxy = runtime_browser_proxy()
    if browser_proxy:
        browser_kwargs["proxy"] = browser_proxy
    browser = Browser(**browser_kwargs)

    async def on_new_step(state: Any, output: Any, step_number: int) -> None:
        actions = [action.model_dump(exclude_none=True) for action in output.action]
        record = {
            "step": step_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url": state.url,
            "title": state.title,
            "dom": state.dom_state.llm_representation(),
            "recent_events": state.recent_events,
            "pending_network_requests": [asdict(request) for request in state.pending_network_requests],
            "screenshot_before": _save_screenshot(run_dir, step_number, "before", state.screenshot),
            "decision": {
                "evaluation_previous_goal": output.evaluation_previous_goal,
                "current_goal": output.next_goal,
                "expected_effect": output.next_goal,
            },
            "actions": actions,
            "results": [],
        }
        records.append(record)
        if not args.headed or args.no_virtual_cursor:
            return
        page = await browser.must_get_current_page()
        await page.evaluate(INSTALL_CURSOR_SCRIPT)
        for action in actions:
            if not action:
                continue
            name, parameters = next(iter(action.items()))
            if not isinstance(parameters, dict) or parameters.get("index") is None:
                continue
            try:
                node = state.dom_state.selector_map.get(int(parameters["index"]))
                rect = node.absolute_position if node else None
                if rect is None:
                    continue
                await page.evaluate(
                    MOVE_TO_POINT_SCRIPT,
                    {"x": rect.x + rect.width / 2, "y": rect.y + rect.height / 2, "durationMs": args.cursor_move_ms},
                )
                await asyncio.sleep((args.cursor_move_ms + 100) / 1000)
                if name in CLICK_ACTIONS:
                    await page.evaluate(SET_CURSOR_STATE_SCRIPT, "pressed")
                    await asyncio.sleep(args.click_display_ms / 1000)
                await page.evaluate(SET_CURSOR_STATE_SCRIPT, "idle")
            except Exception as error:
                print(f"Virtual cursor skipped {name}: {error}")

    async def on_step_end(agent: Any) -> None:
        if not records:
            return
        record = records[-1]
        record["results"] = [result.model_dump(exclude_none=True) for result in agent.state.last_result or []]
        try:
            page = await browser.must_get_current_page()
            record["url_after"] = await browser.get_current_page_url()
            record["title_after"] = await browser.get_current_page_title()
            record["screenshot_after"] = _save_screenshot(
                run_dir, int(record["step"]), "after", await page.screenshot()
            )
            if args.headed and not args.no_virtual_cursor:
                await page.evaluate(INSTALL_CURSOR_SCRIPT)
        except Exception as error:
            record["capture_error"] = str(error)

    llm = ChatOpenAILike(
        model=args.model,
        api_key=api_key,
        base_url=args.base_url,
        temperature=0,
        frequency_penalty=0,
        reasoning_effort=None,
        add_schema_to_system_prompt=True,
        dont_force_structured_output=True,
        max_completion_tokens=2048,
    )
    task = f"Open {args.start_url}. {args.goal}"
    agent = Agent(
        task=task,
        task_id=args.task_id,
        llm=llm,
        browser=browser,
        register_new_step_callback=on_new_step,
        use_vision=not args.no_vision,
        use_thinking=False,
        use_judge=False,
        max_actions_per_step=1,
        include_recent_events=True,
        calculate_cost=False,
        generate_gif=False,
    )
    history = None
    fatal_error = None
    try:
        history = await agent.run(max_steps=args.max_steps, on_step_end=on_step_end)
    except Exception as error:
        fatal_error = f"{type(error).__name__}: {error}"
    finally:
        try:
            await browser.stop()
        except Exception as error:
            fatal_error = fatal_error or f"BrowserStopError: {error}"

    finished = datetime.now(timezone.utc)
    final_url = str(records[-1].get("url_after") or records[-1].get("url") or "") if records else ""
    expected = args.expected_url_contains.strip()
    agent_success = bool(history and history.is_successful())
    success = expected.casefold() in final_url.casefold() if expected else agent_success
    failure_type = (
        "environment"
        if fatal_error and not records
        else "agent" if fatal_error or not success else "none"
    )
    usage_raw = history.usage.model_dump() if history and history.usage else {}
    usage = {
        "input_tokens": usage_raw.get("total_prompt_tokens", 0),
        "output_tokens": usage_raw.get("total_completion_tokens", 0),
        "total_tokens": usage_raw.get("total_tokens", 0),
        "total_cost": usage_raw.get("total_cost", 0),
    }
    raw_trace = {
        "framework": "browser-use",
        "steps": records,
        "final_result": history.final_result() if history else None,
        "errors": history.errors() if history else ([fatal_error] if fatal_error else []),
    }
    _write_json(run_dir / "raw_trace.json", raw_trace)
    manifest = {
        "framework": "Browser Use",
        "framework_version": version("browser-use"),
        "task_id": args.task_id,
        "suite_id": "web",
        "agent_id": "browser-use-qwen",
        "task": task,
        "start_url": args.start_url,
        "model": args.model,
        "seed": args.seed,
        "budget": {"max_steps": args.max_steps},
        "network": {
            "model_bypass_proxy": os.getenv("DASHSCOPE_BYPASS_PROXY", "true").casefold()
            == "true",
            "browser_proxy": runtime_browser_proxy_summary(),
            "navigation_timeout_ms": args.navigation_timeout_ms,
        },
        "visualization": {
            "headed": args.headed,
            "record_video": args.record_video,
            "virtual_cursor": args.headed and not args.no_virtual_cursor,
        },
        "authentication": {
            "storage_state": args.storage_state.name if args.storage_state else None,
            "state_contents_recorded": False,
        },
        "git": _git_state(root),
        "dependency_locks": {
            "root_uv_lock_sha256": _sha256(root / "uv.lock"),
            "browser_use_uv_lock_sha256": _sha256(root / "integrations/browser_use/uv.lock"),
        },
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "usage": usage,
        "result": {
            "success": success and fatal_error is None,
            "agent_success": agent_success,
            "final_url": final_url,
            "expected_url_contains": expected or None,
            "error": fatal_error,
            "failure_type": failure_type,
            "truncated": bool(history and not history.is_done() and len(records) >= args.max_steps),
        },
        "privacy": {
            "private_chain_of_thought_recorded": False,
            "credentials_recorded": False,
            "screenshots_require_review_before_sharing": True,
        },
    }
    _write_json(run_dir / "manifest.json", manifest)
    print(json.dumps({"run_dir": str(run_dir), "success": manifest["result"]["success"]}, ensure_ascii=False))
    return bool(manifest["result"]["success"])


def main(argv: Sequence[str] | None = None) -> None:
    success = asyncio.run(_run(_parse_args(argv)))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
