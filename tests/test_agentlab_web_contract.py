import pytest

from scripts.run_agentlab_web import _parse_args
from scripts.capture_browser_state import _parse_args as parse_capture_args


def test_real_site_demo_has_safe_bounded_defaults() -> None:
    args = _parse_args([])
    assert args.start_url == "https://example.com"
    assert args.max_steps == 1
    assert args.expected_url_contains == "iana.org"
    assert args.no_virtual_cursor is False


def test_real_site_demo_rejects_non_https_url() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--start-url", "http://example.com"])


def test_real_site_demo_accepts_existing_storage_state(tmp_path) -> None:
    state = tmp_path / "state.json"
    state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    args = _parse_args(["--storage-state", str(state)])
    assert args.storage_state == state


def test_capture_state_uses_named_https_profile() -> None:
    args = parse_capture_args(["--url", "https://login.taobao.com/", "--name", "taobao"])
    assert args.name == "taobao"
    with pytest.raises(SystemExit):
        parse_capture_args(["--url", "http://example.com", "--name", "unsafe/name"])
