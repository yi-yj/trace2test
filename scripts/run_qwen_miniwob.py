"""Run one visual Qwen tool-calling step in BrowserGym MiniWoB."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import platform
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any, Sequence

import browsergym.miniwob  # noqa: F401 - registers MiniWoB environments
import gymnasium as gym
from browsergym.utils.obs import flatten_axtree_to_str
from dotenv import load_dotenv
from PIL import Image

from scripts.run_miniwob_smoke import _json_safe, _miniwob_base_url
from scripts.virtual_cursor import (
    install_virtual_cursor,
    move_virtual_cursor_to_bid,
    set_virtual_cursor_pressed,
    wait_for_visual_close,
)


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "browsergym/miniwob.click-test"
TASK_SEED = 42
PROMPT_VERSION = "qwen-visual-click-v1"
SYSTEM_PROMPT = (
    "You are a GUI agent. Inspect the screenshot and accessibility tree, then call the "
    "provided click tool exactly once to complete the user's task. Only use a bid present "
    "in the accessibility tree. Do not describe an action instead of calling the tool."
)
CLICK_TOOL = {
    "type": "function",
    "function": {
        "name": "click",
        "description": "Click one visible page element using its BrowserGym bid.",
        "parameters": {
            "type": "object",
            "properties": {
                "bid": {
                    "type": "string",
                    "description": "The exact element bid from the accessibility tree.",
                }
            },
            "required": ["bid"],
            "additionalProperties": False,
        },
    },
}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the Chromium window through WSLg instead of running headless.",
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=1000,
        metavar="MS",
        help="Pause at the target before clicking in headed mode (default: 1000).",
    )
    parser.add_argument(
        "--click-display-ms",
        type=int,
        default=450,
        metavar="MS",
        help="Show the red CLICK state for this many milliseconds (default: 450).",
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="Do not wait for Enter before closing Chromium in headed mode.",
    )
    parser.add_argument(
        "--no-virtual-cursor",
        action="store_true",
        help="Hide the colored virtual cursor overlay in headed mode.",
    )
    args = parser.parse_args(argv)
    if args.slow_mo < 0 or args.click_display_ms < 0:
        parser.error("visualization delays must be zero or greater")
    return args


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _png_data_url(screenshot: Any) -> tuple[str, bytes]:
    buffer = io.BytesIO()
    Image.fromarray(screenshot).save(buffer, format="PNG")
    png = buffer.getvalue()
    encoded = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{encoded}", png


def _post_json(
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
    bypass_proxy: bool,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}) if bypass_proxy else urllib.request.ProxyHandler()
        )
        with opener.open(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Qwen API returned HTTP {error.code}: {body[:1000]}") from error


def _extract_click_tool_call(response: dict[str, Any], valid_bids: set[str]) -> dict[str, str]:
    try:
        tool_calls = response["choices"][0]["message"]["tool_calls"]
        tool_call = tool_calls[0]
        function = tool_call["function"]
        arguments = json.loads(function["arguments"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("Qwen did not return a valid tool call") from error

    if len(tool_calls) != 1 or function.get("name") != "click":
        raise RuntimeError("Qwen must return exactly one click tool call")
    bid = str(arguments.get("bid", ""))
    if bid not in valid_bids:
        raise RuntimeError(f"Qwen returned an unknown bid: {bid!r}")
    return {"id": str(tool_call.get("id", "")), "name": "click", "bid": bid}


def _safe_model_response(response: dict[str, Any]) -> dict[str, Any]:
    choice = response["choices"][0]
    message = choice["message"]
    return {
        "id": response.get("id"),
        "model": response.get("model"),
        "created": response.get("created"),
        "finish_reason": choice.get("finish_reason"),
        "message": {
            "role": message.get("role"),
            "content": message.get("content"),
            "tool_calls": message.get("tool_calls", []),
        },
        "usage": response.get("usage", {}),
    }


def main() -> None:
    args = _parse_args()
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    base_url = os.getenv("DASHSCOPE_BASE_URL", "").rstrip("/")
    model = os.getenv("QWEN_VISION_MODEL", "qwen3-vl-plus")
    temperature = float(os.getenv("QWEN_TEMPERATURE", "0"))
    timeout = float(os.getenv("QWEN_TIMEOUT_SECONDS", "120"))
    bypass_proxy = os.getenv("DASHSCOPE_BYPASS_PROXY", "false").casefold() == "true"
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured in .env")
    if not base_url.startswith("https://"):
        raise RuntimeError("DASHSCOPE_BASE_URL must use HTTPS")
    if not os.getenv("MINIWOB_ROOT"):
        raise RuntimeError("MINIWOB_ROOT is not configured in .env")

    started_at = datetime.now(timezone.utc)
    run_id = started_at.strftime("qwen-miniwob-click-test-%Y%m%dT%H%M%SZ")
    artifact_root = Path(os.getenv("ARTIFACT_STORE_PATH", "./artifacts"))
    if not artifact_root.is_absolute():
        artifact_root = ROOT / artifact_root
    run_dir = artifact_root / "qwen" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    cursor_enabled = args.headed and not args.no_virtual_cursor

    with _miniwob_base_url() as miniwob_url:
        env = gym.make(
            TASK_ID,
            task_kwargs={"base_url": miniwob_url},
            locale="en-US",
            timezone_id="UTC",
            headless=not args.headed,
            slow_mo=None,
        )
        try:
            observation, reset_info = env.reset(seed=TASK_SEED)
            chromium_version = env.unwrapped.browser.version
            screenshot = observation["screenshot"]
            Image.fromarray(screenshot).save(run_dir / "screenshot-before.png")
            if cursor_enabled:
                install_virtual_cursor(env.unwrapped.page)
            axtree_text = flatten_axtree_to_str(observation["axtree_object"])
            valid_bids = set(re.findall(r"^\s*\[([^]]+)\]", axtree_text, re.MULTILINE))
            image_url, png = _png_data_url(screenshot)
            user_text = f"Task: {observation['goal']}\n\nAccessibility tree:\n{axtree_text}"
            prompt_sha256 = hashlib.sha256(
                f"{PROMPT_VERSION}\n{SYSTEM_PROMPT}\n{user_text}".encode("utf-8")
            ).hexdigest()
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    },
                ],
                "tools": [CLICK_TOOL],
                "tool_choice": {"type": "function", "function": {"name": "click"}},
                "temperature": temperature,
                "max_tokens": 512,
                "enable_thinking": False,
            }
            response = _post_json(
                f"{base_url}/chat/completions",
                api_key=api_key,
                payload=payload,
                timeout=timeout,
                bypass_proxy=bypass_proxy,
            )
            tool_call = _extract_click_tool_call(response, valid_bids)
            action = f'click({json.dumps(tool_call["bid"])})'
            cursor_position = None
            if cursor_enabled:
                cursor_position = move_virtual_cursor_to_bid(
                    env.unwrapped.page, tool_call["bid"], duration_ms=700
                )
                env.unwrapped.page.screenshot(path=run_dir / "virtual-cursor-idle.png")
                time.sleep(args.slow_mo / 1000)
                set_virtual_cursor_pressed(env.unwrapped.page, True)
                time.sleep(args.click_display_ms / 1000)
                env.unwrapped.page.screenshot(path=run_dir / "virtual-cursor-click.png")
                set_virtual_cursor_pressed(env.unwrapped.page, False)

            request_record = {
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "prompt_sha256": prompt_sha256,
                "system_prompt": SYSTEM_PROMPT,
                "user_text": user_text,
                "image": {
                    "path": "screenshot-before.png",
                    "sha256": hashlib.sha256(png).hexdigest(),
                    "bytes": len(png),
                },
                "tools": [CLICK_TOOL],
                "tool_choice": payload["tool_choice"],
                "temperature": temperature,
                "max_tokens": payload["max_tokens"],
                "enable_thinking": False,
            }
            (run_dir / "model-request.json").write_text(
                json.dumps(request_record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            safe_response = _safe_model_response(response)
            (run_dir / "model-response.json").write_text(
                json.dumps(safe_response, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            observation_record = {
                "task_id": TASK_ID,
                "seed": TASK_SEED,
                "goal": _json_safe(observation.get("goal")),
                "url": _json_safe(observation.get("url")),
                "axtree_txt": axtree_text,
                "valid_bids": sorted(valid_bids),
                "screenshot": {
                    "path": "screenshot-before.png",
                    "shape": list(screenshot.shape),
                    "dtype": str(screenshot.dtype),
                },
                "observation_keys": sorted(observation.keys()),
                "reset_info": _json_safe(reset_info),
            }
            (run_dir / "observation.json").write_text(
                json.dumps(observation_record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (run_dir / "action.json").write_text(
                json.dumps(
                    {
                        "tool_call": tool_call,
                        "browsergym_action": action,
                        "virtual_cursor_position": cursor_position,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            next_observation, reward, terminated, truncated, step_info = env.step(action)
            if cursor_enabled:
                env.unwrapped.page.screenshot(path=run_dir / "screenshot-after.png")
            else:
                Image.fromarray(next_observation["screenshot"]).save(
                    run_dir / "screenshot-after.png"
                )
            result = {
                "reward": float(reward),
                "terminated": bool(terminated),
                "truncated": bool(truncated),
                "step_info": _json_safe(step_info),
                "screenshot_after": "screenshot-after.png",
                "visualization": {
                    "virtual_cursor": cursor_enabled,
                    "idle_screenshot": "virtual-cursor-idle.png"
                    if cursor_enabled
                    else None,
                    "click_screenshot": "virtual-cursor-click.png"
                    if cursor_enabled
                    else None,
                },
            }
            (run_dir / "result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        finally:
            if args.headed and not args.no_pause:
                wait_for_visual_close(env.unwrapped.page)
            env.close()

    finished_at = datetime.now(timezone.utc)
    manifest = {
        "run_id": run_id,
        "git_commit": _git_commit(),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "task": {"id": TASK_ID, "seed": TASK_SEED},
        "agent": {"type": "qwen-visual-tool-agent", "version": "0.1.0"},
        "model": {
            "provider": "alibaba-bailian",
            "configured_id": model,
            "response_id": safe_response.get("model"),
            "request_id": safe_response.get("id"),
            "temperature": temperature,
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": prompt_sha256,
            "usage": safe_response.get("usage", {}),
            "proxy_bypassed": bypass_proxy,
        },
        "environment": {
            "browsergym_core": version("browsergym-core"),
            "browsergym_miniwob": version("browsergym-miniwob"),
            "playwright": version("playwright"),
            "chromium": chromium_version,
            "miniwob_commit": "7fd85d71a4b60325c6585396ec4f48377d049838",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "viewport": [int(screenshot.shape[1]), int(screenshot.shape[0])],
            "locale": "en-US",
            "timezone": "UTC",
            "headed": args.headed,
            "action_preview_delay_ms": args.slow_mo if args.headed else 0,
            "click_display_ms": args.click_display_ms if cursor_enabled else 0,
            "virtual_cursor": cursor_enabled,
        },
        "limits": {"max_steps": 1, "timeout_seconds": timeout},
        "dependencies": {
            "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()
        },
        "result": result,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if result["reward"] != 1.0 or not result["terminated"] or result["truncated"]:
        raise RuntimeError(f"Qwen MiniWoB task failed; artifacts: {run_dir}")
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "model": safe_response.get("model"),
                "tool_call": tool_call,
                "usage": safe_response.get("usage", {}),
                **result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
