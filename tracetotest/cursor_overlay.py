"""Dependency-free virtual-cursor overlay shared by every browser adapter."""

INSTALL_CURSOR_SCRIPT = r"""
() => {
  const id = "__tracetotest_virtual_cursor";
  if (document.getElementById(id)) return true;
  const host = document.createElement("tracetotest-cursor");
  host.id = id;
  host.setAttribute("aria-hidden", "true");
  host.style.cssText = ["position:fixed","left:0","top:0","width:0","height:0",
    "pointer-events:none","z-index:2147483647","transform:translate(24px,24px)",
    "transition:transform 0ms linear","will-change:transform"].join(";");
  const shadow = host.attachShadow({mode: "open"});
  shadow.innerHTML = `<style>
    :host{--idle:#00c8ff;--moving:#ffd60a;--pressed:#ff3b30}
    .cursor{position:absolute;left:-14px;top:-14px;width:28px;height:28px}
    .dot{position:absolute;inset:4px;border:3px solid white;border-radius:50%;background:var(--idle);box-shadow:0 0 0 2px #00384a,0 3px 10px #0009;transition:background 100ms ease,transform 100ms ease}
    .ring{position:absolute;inset:0;border:3px solid var(--idle);border-radius:50%}
    .label{position:absolute;left:22px;top:18px;padding:2px 6px;border-radius:4px;color:white;background:#00384ae8;font:700 11px/16px sans-serif;letter-spacing:.5px;white-space:nowrap;box-shadow:0 2px 6px #0007}
    :host([data-state="moving"]) .dot{background:var(--moving)}
    :host([data-state="moving"]) .ring{border-color:var(--moving)}
    :host([data-state="moving"]) .label{color:#111;background:#ffd60ae8}
    :host([data-state="pressed"]) .dot{background:var(--pressed);transform:scale(.68)}
    :host([data-state="pressed"]) .ring{border-color:var(--pressed);animation:pulse 500ms ease-out infinite}
    :host([data-state="pressed"]) .label{background:#ff3b30ed}
    @keyframes pulse{from{opacity:1;transform:scale(.65)}to{opacity:0;transform:scale(1.65)}}
  </style><div class="cursor"><div class="ring"></div><div class="dot"></div><div class="label">IDLE</div></div>`;
  host.dataset.state = "idle";
  document.documentElement.appendChild(host);
  return true;
}
"""

MOVE_TO_BID_SCRIPT = r"""
({bid, durationMs}) => {
  const host = document.getElementById("__tracetotest_virtual_cursor");
  if (!host) throw new Error("Trace2Test virtual cursor is not installed");
  const element = document.querySelector(`[bid="${CSS.escape(bid)}"]`);
  if (!element) throw new Error(`Cannot locate element with bid=${bid}`);
  const rect = element.getBoundingClientRect();
  const x = Math.round(rect.left + rect.width / 2), y = Math.round(rect.top + rect.height / 2);
  host.dataset.state = "moving";
  host.shadowRoot.querySelector(".label").textContent = "MOVE";
  host.style.transitionDuration = `${durationMs}ms`;
  host.style.transitionTimingFunction = "cubic-bezier(.22,.8,.25,1)";
  host.style.transform = `translate(${x}px,${y}px)`;
  return {x, y};
}
"""

MOVE_TO_POINT_SCRIPT = r"""
({x, y, durationMs}) => {
  const host = document.getElementById("__tracetotest_virtual_cursor");
  if (!host) throw new Error("Trace2Test virtual cursor is not installed");
  const viewportX = Math.round(x - window.scrollX), viewportY = Math.round(y - window.scrollY);
  host.dataset.state = "moving";
  host.shadowRoot.querySelector(".label").textContent = "MOVE";
  host.style.transitionDuration = `${durationMs}ms`;
  host.style.transitionTimingFunction = "cubic-bezier(.22,.8,.25,1)";
  host.style.transform = `translate(${viewportX}px,${viewportY}px)`;
  return {x: viewportX, y: viewportY};
}
"""

SET_CURSOR_STATE_SCRIPT = r"""
(state) => {
  const host = document.getElementById("__tracetotest_virtual_cursor");
  if (!host) throw new Error("Trace2Test virtual cursor is not installed");
  host.dataset.state = state;
  host.shadowRoot.querySelector(".label").textContent = state === "pressed" ? "CLICK" : "IDLE";
  return true;
}
"""
