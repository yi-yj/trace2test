"""Run a deterministic BrowserGym MiniWoB smoke test and save trace artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import browsergym.miniwob  # noqa: F401 - registers MiniWoB Gym environments
import gymnasium as gym
from browsergym.utils.obs import flatten_axtree_to_str
from dotenv import load_dotenv
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "browsergym/miniwob.click-test"
TASK_SEED = 42


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _lock_digest() -> str:
    return hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if hasattr(value, "tolist"):
        return value.tolist()
    return repr(value)


def main() -> None:
    load_dotenv(ROOT / ".env")
    if not os.getenv("MINIWOB_URL"):
        raise RuntimeError("MINIWOB_URL is missing; copy .env.example to .env and configure it")

    started_at = datetime.now(timezone.utc)
    run_id = started_at.strftime("miniwob-click-test-%Y%m%dT%H%M%SZ")
    artifact_root = Path(os.getenv("ARTIFACT_STORE_PATH", "./artifacts"))
    if not artifact_root.is_absolute():
        artifact_root = ROOT / artifact_root
    run_dir = artifact_root / "smoke" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    env = gym.make(TASK_ID, locale="en-US", timezone_id="UTC")
    try:
        observation, reset_info = env.reset(seed=TASK_SEED)
        screenshot = observation["screenshot"]
        Image.fromarray(screenshot).save(run_dir / "screenshot-before.png")

        axtree_text = flatten_axtree_to_str(observation["axtree_object"])
        match = re.search(
            r"^\s*\[(\d+)\].*button", axtree_text, re.MULTILINE | re.IGNORECASE
        )
        if match is None:
            raise RuntimeError("MiniWoB click-test button was not found in the A11y tree")
        action = f'click("{match.group(1)}")'

        observation_record = {
            "task_id": TASK_ID,
            "seed": TASK_SEED,
            "goal": _json_safe(observation.get("goal")),
            "url": _json_safe(observation.get("url")),
            "axtree_txt": axtree_text,
            "dom_object": _json_safe(observation.get("dom_object")),
            "open_pages_urls": _json_safe(observation.get("open_pages_urls")),
            "active_page_index": _json_safe(observation.get("active_page_index")),
            "focused_element_bid": _json_safe(observation.get("focused_element_bid")),
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
            json.dumps({"action": action}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        next_observation, reward, terminated, truncated, step_info = env.step(action)
        Image.fromarray(next_observation["screenshot"]).save(run_dir / "screenshot-after.png")

        result = {
            "reward": float(reward),
            "terminated": bool(terminated),
            "truncated": bool(truncated),
            "step_info": _json_safe(step_info),
            "screenshot_after": "screenshot-after.png",
        }
        (run_dir / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        env.close()

    finished_at = datetime.now(timezone.utc)
    manifest = {
        "run_id": run_id,
        "git_commit": _git_commit(),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "task": {"id": TASK_ID, "seed": TASK_SEED},
        "agent": {"type": "deterministic-oracle", "action": action},
        "model": {"provider": "none", "id": None, "reason": "environment smoke test"},
        "environment": {
            "browsergym": "0.14.3",
            "miniwob_commit": "7fd85d71a4b60325c6585396ec4f48377d049838",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "viewport": [int(screenshot.shape[1]), int(screenshot.shape[0])],
            "locale": "en-US",
            "timezone": "UTC",
        },
        "limits": {"max_steps": 1, "timeout_seconds": 60, "cost_budget": 0},
        "dependencies": {"uv_lock_sha256": _lock_digest()},
        "result": result,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"run_dir": str(run_dir), **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
