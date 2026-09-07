"""Manually sign in once and save private Playwright authentication state."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from scripts.run_agentlab_miniwob import ROOT
from tracetotest.browser_fonts import configure_browser_fonts
from tracetotest.proxy import resolve_browser_proxy


AUTH_ROOT = ROOT / ".auth"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="HTTPS login page to open.")
    parser.add_argument("--name", required=True, help="Profile name, for example taobao.")
    parser.add_argument("--force", action="store_true", help="Replace an existing state file.")
    args = parser.parse_args(argv)
    parsed = urlparse(args.url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        parser.error("--url must be an HTTPS URL without embedded credentials")
    if not args.name.replace("-", "").replace("_", "").isalnum():
        parser.error("--name may contain only letters, digits, '-' and '_'")
    return args


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    load_dotenv(ROOT / ".env")
    configure_browser_fonts()
    output = AUTH_ROOT / f"{args.name}.json"
    if output.exists() and not args.force:
        raise FileExistsError(f"State already exists: {output}; use --force to refresh it")
    output.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        proxy = resolve_browser_proxy().playwright()
        launch_options = {"headless": False}
        if proxy:
            launch_options["proxy"] = proxy
        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
        page = context.new_page()
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=30_000)
            print("请在打开的浏览器中手动完成登录和必要的人机验证。")
            input("确认页面已显示登录成功后，回到此终端按 Enter 保存状态：")
            state = context.storage_state(path=output)
            try:
                os.chmod(output, 0o600)
            except OSError:
                pass
        finally:
            context.close()
            browser.close()

    domains = sorted({str(cookie.get("domain", "")) for cookie in state.get("cookies", [])})
    print(
        json.dumps(
            {
                "saved": str(output),
                "cookies": len(state.get("cookies", [])),
                "origins": len(state.get("origins", [])),
                "domains": domains,
                "warning": "该文件包含登录凭据，仅限本机使用，禁止提交或分享。",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
