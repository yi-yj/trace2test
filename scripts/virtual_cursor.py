"""Non-interactive cursor overlay for headed browser evaluation runs."""

from __future__ import annotations

import threading
from typing import Any


_INSTALL_SCRIPT = r"""
() => {
  const hostId = "__tracetotest_virtual_cursor";
  if (document.getElementById(hostId)) return;

  const host = document.createElement("tracetotest-cursor");
  host.id = hostId;
  host.setAttribute("aria-hidden", "true");
  host.style.cssText = [
    "position:fixed", "left:0", "top:0", "width:0", "height:0",
    "pointer-events:none", "z-index:2147483647", "transform:translate(24px,24px)",
    "transition:transform 0ms linear", "will-change:transform"
  ].join(";");

  const shadow = host.attachShadow({mode: "open"});
  shadow.innerHTML = `
    <style>
      :host { --idle: #00c8ff; --moving: #ffd60a; --pressed: #ff3b30; }
      .cursor { position:absolute; left:-14px; top:-14px; width:28px; height:28px; }
      .dot {
        position:absolute; inset:4px; border:3px solid white; border-radius:50%;
        background:var(--idle); box-shadow:0 0 0 2px #00384a, 0 3px 10px #0009;
        transition:background 100ms ease, transform 100ms ease;
      }
      .ring { position:absolute; inset:0; border:3px solid var(--idle); border-radius:50%; }
      .label {
        position:absolute; left:22px; top:18px; padding:2px 6px; border-radius:4px;
        color:white; background:#00384ae8; font:700 11px/16px sans-serif;
        letter-spacing:.5px; white-space:nowrap; box-shadow:0 2px 6px #0007;
      }
      :host([data-state="moving"]) .dot { background:var(--moving); }
      :host([data-state="moving"]) .ring { border-color:var(--moving); }
      :host([data-state="moving"]) .label { color:#111; background:#ffd60ae8; }
      :host([data-state="pressed"]) .dot { background:var(--pressed); transform:scale(.68); }
      :host([data-state="pressed"]) .ring {
        border-color:var(--pressed); animation:pulse 500ms ease-out infinite;
      }
      :host([data-state="pressed"]) .label { background:#ff3b30ed; }
      @keyframes pulse {
        from { opacity:1; transform:scale(.65); }
        to { opacity:0; transform:scale(1.65); }
      }
    </style>
    <div class="cursor"><div class="ring"></div><div class="dot"></div><div class="label">IDLE</div></div>
  `;
  host.dataset.state = "idle";
  document.documentElement.appendChild(host);
}
"""

_MOVE_SCRIPT = r"""
({bid, durationMs}) => {
  const host = document.getElementById("__tracetotest_virtual_cursor");
  if (!host) throw new Error("Trace2Test virtual cursor is not installed");
  const element = document.querySelector(`[bid="${CSS.escape(bid)}"]`);
  if (!element) throw new Error(`Cannot locate element with bid=${bid}`);
  const rect = element.getBoundingClientRect();
  const x = Math.round(rect.left + rect.width / 2);
  const y = Math.round(rect.top + rect.height / 2);
  host.dataset.state = "moving";
  host.shadowRoot.querySelector(".label").textContent = "MOVE";
  host.style.transitionDuration = `${durationMs}ms`;
  host.style.transitionTimingFunction = "cubic-bezier(.22,.8,.25,1)";
  host.style.transform = `translate(${x}px,${y}px)`;
  return {x, y};
}
"""

_STATE_SCRIPT = r"""
(state) => {
  const host = document.getElementById("__tracetotest_virtual_cursor");
  if (!host) throw new Error("Trace2Test virtual cursor is not installed");
  host.dataset.state = state;
  host.shadowRoot.querySelector(".label").textContent = state === "pressed" ? "CLICK" : "IDLE";
}
"""

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
