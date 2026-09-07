"""Non-interactive cursor overlay for headed browser evaluation runs."""

from __future__ import annotations

import threading
from typing import Any

from tracetotest.cursor_overlay import (
    INSTALL_CURSOR_SCRIPT as _INSTALL_SCRIPT,
    MOVE_TO_BID_SCRIPT as _MOVE_SCRIPT,
    SET_CURSOR_STATE_SCRIPT as _STATE_SCRIPT,
)

_INSTALL_CLOSE_CONTROL_SCRIPT = r"""
() => {
  window.__tracetotestCloseRequested = false;
  window.__tracetotestRequestClose = () => {
    window.__tracetotestCloseRequested = true;
    const button = document.getElementById("__tracetotest_close_hint");
    if (button) {
      button.textContent = "Closing Chromium...";
      button.disabled = true;
    }
  };
  if (!window.__tracetotestCloseListenerInstalled) {
    const requestClose = event => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      window.__tracetotestRequestClose();
    };
    window.addEventListener("keydown", requestClose, true);
    window.addEventListener("keypress", requestClose, true);
    window.addEventListener("keyup", requestClose, true);
    window.__tracetotestCloseListenerInstalled = true;
  }

  let button = document.getElementById("__tracetotest_close_hint");
  if (!button) {
    button = document.createElement("button");
    button.id = "__tracetotest_close_hint";
    button.type = "button";
    button.textContent = "CLOSE CHROMIUM - Press Enter or click here";
    button.addEventListener("click", () => window.__tracetotestRequestClose());
    button.style.cssText = [
    "position:fixed", "left:50%", "bottom:18px", "transform:translateX(-50%)",
    "z-index:2147483647", "pointer-events:auto", "padding:8px 14px",
    "border:2px solid #00c8ff", "border-radius:8px", "background:#071d27ee",
    "color:white", "font:700 13px/20px sans-serif", "white-space:nowrap", "cursor:pointer",
    "box-shadow:0 4px 16px #0009", "outline:3px solid #ffd60a", "outline-offset:2px"
    ].join(";");
    document.documentElement.appendChild(button);
  }
  button.focus({preventScroll: true});
}
"""

def install_virtual_cursor(page: Any) -> None:
    """Install a pointer-events-free cursor overlay in the active page."""
    page.evaluate(_INSTALL_SCRIPT)


def move_virtual_cursor_to_bid(page: Any, bid: str, duration_ms: int = 700) -> dict[str, int]:
    """Animate the overlay to the center of a BrowserGym bid."""
    position = page.evaluate(_MOVE_SCRIPT, {"bid": bid, "durationMs": duration_ms})
    page.wait_for_timeout(duration_ms + 100)
    page.evaluate(_STATE_SCRIPT, "idle")
    return {"x": int(position["x"]), "y": int(position["y"])}


def set_virtual_cursor_pressed(page: Any, pressed: bool) -> None:
    """Switch the overlay between red CLICK and blue IDLE states."""
    page.evaluate(_STATE_SCRIPT, "pressed" if pressed else "idle")


def wait_for_visual_close(page: Any) -> str:
    """Wait until Enter is pressed in either the browser or the launch terminal."""
    page.evaluate(_INSTALL_CLOSE_CONTROL_SCRIPT)
    terminal_enter = threading.Event()

    def wait_for_terminal_enter() -> None:
        try:
            input("Single scenario complete; press Enter here or in Chromium to close...")
        except EOFError:
            print("Terminal input is unavailable; press Enter in Chromium to close.")
            return
        terminal_enter.set()

    threading.Thread(target=wait_for_terminal_enter, daemon=True).start()
    while not terminal_enter.is_set():
        if page.evaluate("() => Boolean(window.__tracetotestCloseRequested)"):
            return "browser"
        page.wait_for_timeout(100)
    return "terminal"
