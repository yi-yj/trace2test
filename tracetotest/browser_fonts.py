"""Configure CJK fallback fonts for Linux Chromium running inside WSL."""

from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WSL_FONTCONFIG = ROOT / "configs/fontconfig-wsl.conf"
WINDOWS_CJK_FONT = Path("/mnt/c/Windows/Fonts/msyh.ttc")


def configure_browser_fonts() -> dict[str, str | bool]:
    """Use installed Windows CJK fonts without copying licensed font files."""
    enabled = WINDOWS_CJK_FONT.is_file() and WSL_FONTCONFIG.is_file()
    if enabled:
        os.environ.setdefault("FONTCONFIG_FILE", str(WSL_FONTCONFIG))
    return {
        "wsl_windows_fonts": enabled,
        "fontconfig_file": os.environ.get("FONTCONFIG_FILE", ""),
    }

