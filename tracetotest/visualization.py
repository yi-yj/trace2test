"""Framework-neutral browser visualization hooks for headed Agent runs."""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from typing import Any

import gymnasium as gym

from scripts.virtual_cursor import (
    install_virtual_cursor,
    move_virtual_cursor_to_bid,
    remove_virtual_cursor,
    set_virtual_cursor_pressed,
)


logger = logging.getLogger(__name__)
CLICK_ACTIONS = frozenset({"click", "dblclick"})
BID_TARGET_ACTIONS = frozenset(
    {
        "fill",
        "select_option",
        "click",
        "dblclick",
        "hover",
        "press",
        "focus",
        "clear",
        "drag_and_drop",
        "upload_file",
    }
)


@dataclass(frozen=True)
class VisualAction:
    name: str
    bid: str


def extract_visual_actions(action: str) -> list[VisualAction]:
    """Extract BrowserGym calls that target a bid without executing the action."""
    if not isinstance(action, str):
        return []
    try:
        tree = ast.parse(action)
    except SyntaxError:
        return []

    actions = []
    for statement in tree.body:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            continue
        call = statement.value
        if not isinstance(call.func, ast.Name):
            continue
        if call.func.id not in BID_TARGET_ACTIONS:
            continue
        bid_node = next((item.value for item in call.keywords if item.arg == "bid"), None)
        if bid_node is None and call.args:
            bid_node = call.args[0]
        if isinstance(bid_node, ast.Constant) and isinstance(bid_node.value, (str, int)):
            actions.append(VisualAction(call.func.id, str(bid_node.value)))
    return actions


def visualize_action(
    page: Any,
    action: str,
    move_duration_ms: int = 700,
    click_display_ms: int = 450,
) -> list[VisualAction]:
    """Animate all visible bid targets; CLICK is red and other actions stay blue."""
    actions = extract_visual_actions(action)
    for item in actions:
        try:
            install_virtual_cursor(page)
            move_virtual_cursor_to_bid(page, item.bid, duration_ms=move_duration_ms)
            if item.name in CLICK_ACTIONS:
                set_virtual_cursor_pressed(page, True)
                page.wait_for_timeout(click_display_ms)
                set_virtual_cursor_pressed(page, False)
        except Exception as error:
            logger.warning("Virtual cursor skipped %s(bid=%s): %s", item.name, item.bid, error)
    return actions


class VirtualCursorEnvWrapper(gym.Wrapper):
    """Add the same cursor lifecycle to any BrowserGym-compatible environment."""

    def __init__(self, env: gym.Env, move_duration_ms: int = 700, click_display_ms: int = 450):
        super().__init__(env)
        self.move_duration_ms = move_duration_ms
        self.click_display_ms = click_display_ms

    @property
    def _page(self):
        return self.env.unwrapped.page

    def reset(self, **kwargs):
        result = self.env.reset(**kwargs)
        try:
            install_virtual_cursor(self._page)
        except Exception as error:
            logger.warning("Virtual cursor initialization skipped: %s", error)
        return result

    def step(self, action):
        visualize_action(
            self._page,
            action,
            move_duration_ms=self.move_duration_ms,
            click_display_ms=self.click_display_ms,
        )
        try:
            remove_virtual_cursor(self._page)
        except Exception as error:
            logger.warning("Virtual cursor removal skipped: %s", error)
        try:
            # BrowserGym executes the action and extracts the next observation here.
            # Keeping the overlay detached prevents it from receiving synthetic bids
            # or appearing in the DOM/A11y representation given to the Agent.
            return self.env.step(action)
        finally:
            try:
                install_virtual_cursor(self._page)
            except Exception as error:
                logger.warning("Virtual cursor refresh skipped: %s", error)


def wrap_env_with_virtual_cursor(
    env: gym.Env,
    *,
    enabled: bool,
    move_duration_ms: int = 700,
    click_display_ms: int = 450,
) -> gym.Env:
    """Shared adapter entry point for every current and future Agent framework."""
    if not enabled:
        return env
    return VirtualCursorEnvWrapper(env, move_duration_ms, click_display_ms)
