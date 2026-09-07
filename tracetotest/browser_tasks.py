"""Trace2Test-owned BrowserGym tasks with explicit environment controls."""

from __future__ import annotations

from urllib.parse import urlsplit

import gymnasium as gym
from browsergym.core.registration import register_task
from browsergym.core.task import OpenEndedTask
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

TASK_ID = "tracetotest.openended"
GYM_ID = f"browsergym/{TASK_ID}"


class EnvironmentNavigationError(RuntimeError):
    """The browser environment could not establish its initial page."""


class Trace2TestOpenEndedTask(OpenEndedTask):
    @classmethod
    def get_task_id(cls) -> str:
        return TASK_ID

    def __init__(
        self,
        seed: int,
        start_url: str,
        goal: str | None = None,
        navigation_timeout_ms: int = 30_000,
    ) -> None:
        super().__init__(seed=seed, start_url=start_url, goal=goal)
        if navigation_timeout_ms < 1:
            raise ValueError("navigation_timeout_ms must be positive")
        self.navigation_timeout_ms = navigation_timeout_ms

    def setup(self, page: Page) -> tuple[str | None, dict]:
        try:
            page.goto(self.start_url, timeout=self.navigation_timeout_ms, wait_until="load")
        except PlaywrightTimeoutError as error:
            host = urlsplit(self.start_url).hostname or "unknown host"
            raise EnvironmentNavigationError(
                f"Initial navigation to {host} exceeded {self.navigation_timeout_ms} ms"
            ) from error
        except PlaywrightError as error:
            host = urlsplit(self.start_url).hostname or "unknown host"
            raise EnvironmentNavigationError(f"Initial navigation to {host} failed") from error
        return self.goal, {"navigation_timeout_ms": self.navigation_timeout_ms}


def ensure_browser_tasks_registered() -> None:
    if GYM_ID not in gym.registry:
        register_task(TASK_ID, Trace2TestOpenEndedTask)
