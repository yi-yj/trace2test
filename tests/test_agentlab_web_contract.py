import pytest

from scripts.run_agentlab_web import _parse_args


def test_real_site_demo_has_safe_bounded_defaults() -> None:
    args = _parse_args([])
    assert args.start_url == "https://example.com"
    assert args.max_steps == 1
    assert args.expected_url_contains == "iana.org"
    assert args.no_virtual_cursor is False


def test_real_site_demo_rejects_non_https_url() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--start-url", "http://example.com"])

