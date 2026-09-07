import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from integrations.browser_use.worker import _parse_args as parse_browser_use_args
from tracetotest.cli import _parser as unified_parser
from tracetotest.agent_completion import COMPLETION_MESSAGE_PREFIX
from tracetotest.browser_tasks import EnvironmentNavigationError, Trace2TestOpenEndedTask
from tracetotest.proxy import (
    install_browser_proxy_environment,
    resolve_browser_proxy,
    runtime_browser_proxy,
)


class FakePage:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def goto(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error


def test_browser_proxy_defaults_to_https_proxy_without_exposing_it() -> None:
    settings = resolve_browser_proxy(
        {
            "HTTPS_PROXY": "http://user:password@127.0.0.1:7890",
            "NO_PROXY": "localhost,127.0.0.1",
        }
    )
    assert settings.playwright() == {
        "server": "http://127.0.0.1:7890",
        "bypass": "localhost,127.0.0.1",
        "username": "user",
        "password": "password",
    }
    assert settings.safe_summary() == {
        "enabled": True,
        "configured": True,
        "source": "HTTPS_PROXY",
        "credentials_configured": True,
    }
    assert "127.0.0.1" not in str(settings.safe_summary())


def test_browser_proxy_handoff_survives_model_proxy_removal() -> None:
    settings = resolve_browser_proxy({"HTTPS_PROXY": "http://127.0.0.1:7890"})
    environment = {"HTTPS_PROXY": "http://127.0.0.1:7890"}
    install_browser_proxy_environment(environment, settings)
    environment.pop("HTTPS_PROXY")
    assert runtime_browser_proxy(environment)["server"] == "http://127.0.0.1:7890"


def test_browser_proxy_can_be_disabled_independently() -> None:
    settings = resolve_browser_proxy(
        {"BROWSER_PROXY_ENABLED": "false", "HTTPS_PROXY": "http://127.0.0.1:7890"}
    )
    assert settings.playwright() is None
    assert settings.safe_summary()["source"] == "disabled"


def test_unified_and_browser_use_navigation_timeout_defaults() -> None:
    unified = unified_parser().parse_args(["run", "--framework", "agentlab"])
    worker = parse_browser_use_args(
        [
            "--run-dir",
            "run",
            "--start-url",
            "https://example.com",
            "--goal",
            "inspect",
            "--model",
            "qwen",
            "--base-url",
            "https://example.com/v1",
        ]
    )
    assert unified.navigation_timeout_ms == 30_000
    assert worker.navigation_timeout_ms == 30_000


def test_configurable_openended_task_uses_navigation_timeout() -> None:
    task = Trace2TestOpenEndedTask(
        seed=42,
        start_url="https://example.com",
        goal="inspect",
        navigation_timeout_ms=30_000,
    )
    page = FakePage()
    goal, info = task.setup(page)
    assert goal == "inspect"
    assert info == {"navigation_timeout_ms": 30_000}
    assert page.calls == [
        ("https://example.com", {"timeout": 30_000, "wait_until": "load"})
    ]


def test_initial_navigation_timeout_is_an_environment_error() -> None:
    task = Trace2TestOpenEndedTask(seed=42, start_url="https://example.com")
    with pytest.raises(EnvironmentNavigationError, match="30000 ms"):
        task.setup(FakePage(PlaywrightTimeoutError("timed out")))


def test_openended_task_stops_only_on_agent_completion_declaration() -> None:
    task = Trace2TestOpenEndedTask(seed=42, start_url="https://example.com")

    assert task.validate(None, [])[1] is False
    assert task.validate(
        None,
        [{"role": "user", "message": f"{COMPLETION_MESSAGE_PREFIX}not the agent"}],
    )[1] is False

    reward, done, message, info = task.validate(
        None,
        [{"role": "assistant", "message": f"{COMPLETION_MESSAGE_PREFIX}goal verified"}],
    )
    assert (reward, done, message) == (0, True, "")
    assert info == {
        "agent_declared_complete": True,
        "completion_reason": "goal verified",
    }
