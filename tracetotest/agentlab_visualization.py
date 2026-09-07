"""AgentLab environment adapter for Trace2Test's shared virtual cursor."""

from __future__ import annotations

from dataclasses import dataclass

from agentlab.experiments.loop import EnvArgs

from tracetotest.proxy import runtime_browser_proxy
from tracetotest.visualization import wrap_env_with_virtual_cursor


@dataclass
class VisualEnvArgs(EnvArgs):
    virtual_cursor: bool = False
    cursor_move_duration_ms: int = 700
    click_display_ms: int = 450
    browser_proxy_enabled: bool = False

    def make_env(
        self,
        action_mapping,
        exp_dir,
        exp_task_kwargs: dict = {},
        use_raw_page_output=True,
    ):
        env = super().make_env(
            action_mapping,
            exp_dir,
            exp_task_kwargs=exp_task_kwargs,
            use_raw_page_output=use_raw_page_output,
        )
        proxy = runtime_browser_proxy() if self.browser_proxy_enabled else None
        if proxy:
            env.unwrapped.pw_chromium_kwargs = {
                **env.unwrapped.pw_chromium_kwargs,
                "proxy": proxy,
            }
        return wrap_env_with_virtual_cursor(
            env,
            enabled=self.virtual_cursor,
            move_duration_ms=self.cursor_move_duration_ms,
            click_display_ms=self.click_display_ms,
        )
