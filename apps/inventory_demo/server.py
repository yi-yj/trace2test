"""Local resettable admin application used by the Phase 2 benchmark."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from tracetotest.fixtures import JsonFixture

FAULTS = frozenset({"response-delay", "inventory-500", "missing-export", "corrupt-export"})


def _csv(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


class InventoryStore:
    def __init__(self, fixture_path: Path, faults: list[str] | None = None):
        self.fixture = JsonFixture(fixture_path)
        self._faults = set(faults or [])
        unknown = self._faults - FAULTS
        if unknown:
            raise ValueError(f"Unknown fault injection(s): {', '.join(sorted(unknown))}")
        self._lock = threading.RLock()
        self.reset()

    @property
    def fixture_id(self) -> str:
        return self.fixture.fixture_id

    @property
    def fixture_version(self) -> str:
        return self.fixture.fixture_version

    def reset(self) -> None:
        with self._lock:
            self.fixture.reset()
            self._active_max_stock: int | None = None
            self._active_order_status: str | None = None
            self._active_order_query: str | None = None
            self._export_count = 0
            self._last_export_kind: str | None = None
            self._last_export_skus: list[str] = []
            self._last_export_orders: list[str] = []
            self._database_mutations = 0
            self._authenticated_user: str | None = None
            self._login_count = 0
            self._failed_login_count = 0
            self._logout_count = 0
            self._fault_events: list[dict[str, str]] = []

    def products(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self.fixture.mutable_state()["products"]]

    def orders(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self.fixture.mutable_state().get("orders", [])]

    def filtered_products(self, max_stock: int | None) -> list[dict[str, Any]]:
        with self._lock:
            self._active_max_stock = max_stock
            rows = self.products()
            return rows if max_stock is None else [item for item in rows if item["stock"] < max_stock]

    def filtered_orders(self, status: str | None, query: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._active_order_status = status
            self._active_order_query = query
            rows = self.orders()
            if status:
                rows = [item for item in rows if item["status"] == status]
            if query:
                needle = query.casefold()
                rows = [item for item in rows if needle in str(item["order_id"]).casefold() or needle in str(item["customer"]).casefold()]
            return rows

    def login(self, email: str, password: str) -> bool:
        with self._lock:
            user = next((item for item in self.fixture.mutable_state().get("users", []) if item["email"] == email and item["password"] == password), None)
            if not user:
                self._failed_login_count += 1
                return False
            self._authenticated_user = str(user["email"])
            self._login_count += 1
            return True

    def logout(self) -> None:
        with self._lock:
            self._authenticated_user = None
            self._logout_count += 1

    def update_stock(self, sku: str, stock: int) -> bool:
        with self._lock:
            product = next((item for item in self.fixture.mutable_state()["products"] if item["sku"] == sku), None)
            if product is None:
                return False
            product["stock"] = stock
            self._database_mutations += 1
            return True

    def update_order(self, order_id: str, status: str) -> bool:
        with self._lock:
            order = next((item for item in self.fixture.mutable_state().get("orders", []) if item["order_id"] == order_id), None)
            if order is None:
                return False
            order["status"] = status
            self._database_mutations += 1
            return True

    def export_inventory_csv(self, max_stock: int) -> str:
        rows = self.filtered_products(max_stock)
        with self._lock:
            self._export_count += 1
            self._last_export_kind = "inventory"
            self._last_export_skus = [str(item["sku"]) for item in rows]
        if self.has_fault("corrupt-export", "/export.csv"):
            rows = rows[:-1]
        return _csv(rows, ("sku", "name", "stock"))

    def export_csv(self, max_stock: int) -> str:
        return self.export_inventory_csv(max_stock)

    def export_orders_csv(self, status: str | None) -> str:
        rows = self.filtered_orders(status)
        with self._lock:
            self._export_count += 1
            self._last_export_kind = "orders"
            self._last_export_orders = [str(item["order_id"]) for item in rows]
        if self.has_fault("corrupt-export", "/orders.csv"):
            rows = rows[:-1]
        return _csv(rows, ("order_id", "customer", "status", "total"))

    def set_stock_for_test(self, sku: str, stock: int) -> None:
        if not self.update_stock(sku, stock):
            raise KeyError(sku)

    def has_fault(self, fault: str, route: str) -> bool:
        if fault not in self._faults:
            return False
        with self._lock:
            self._fault_events.append({"fault": fault, "route": route})
        return True

    def checksum(self) -> str:
        return self.fixture.checksum()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            data = self.fixture.snapshot()
            truth = sorted(self._faults)
            return {
                "fixture_id": self.fixture_id,
                "fixture_version": self.fixture_version,
                "fixture_checksum": self.checksum(),
                "pristine_checksum": self.fixture.pristine_checksum,
                "active_max_stock": self._active_max_stock,
                "active_order_status": self._active_order_status,
                "active_order_query": self._active_order_query,
                "export_count": self._export_count,
                "last_export_kind": self._last_export_kind,
                "last_export_skus": list(self._last_export_skus),
                "last_export_orders": list(self._last_export_orders),
                "database_mutations": self._database_mutations,
                "authenticated_user": self._authenticated_user,
                "login_count": self._login_count,
                "failed_login_count": self._failed_login_count,
                "logout_count": self._logout_count,
                "products": data["products"],
                "orders": data.get("orders", []),
                "fault_truth": {
                    "configured": truth,
                    "events": list(self._fault_events),
                    "truth_sha256": hashlib.sha256(json.dumps(truth).encode()).hexdigest(),
                },
            }


def _layout(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font:16px/1.45 sans-serif;max-width:1050px;margin:32px auto;color:#17202a}}nav{{display:flex;gap:16px;margin-bottom:24px}}form{{display:flex;gap:10px;align-items:end;margin:16px 0}}label{{display:grid;gap:4px}}input,select,button,a{{font:inherit;padding:7px 10px}}table{{width:100%;border-collapse:collapse;margin:18px 0}}th,td{{border:1px solid #bac3cc;padding:8px;text-align:left}}th{{background:#edf3f7}}.error{{color:#a40000}}</style></head>
<body><nav><a href="/inventory">Inventory</a><a href="/orders">Orders</a><a href="/login">Login</a><a href="/logout">Log out</a></nav>{body}</body></html>"""


def _inventory_page(store: InventoryStore, max_stock: int | None) -> str:
    products = store.filtered_products(max_stock)
    rows = "".join(
        f"<tr><td>{html.escape(str(p['sku']))}</td><td>{html.escape(str(p['name']))}</td><td>{int(p['stock'])}</td><td>"
        f"<form method='post' action='/inventory/update'><input type='hidden' name='sku' value='{html.escape(str(p['sku']))}'>"
        f"<label>Stock for {html.escape(str(p['sku']))}<input name='stock' type='number' min='0' value='{int(p['stock'])}'></label>"
        f"<button type='submit'>Save {html.escape(str(p['sku']))}</button></form></td></tr>" for p in products
    )
    value = "" if max_stock is None else str(max_stock)
    export = f'<a id="export-csv" download="low-inventory.csv" href="/export.csv?max_stock={max_stock}">Export filtered CSV</a>' if max_stock is not None and not store.has_fault("missing-export", "/inventory") else '<span id="export-hint">Apply a filter before exporting.</span>'
    return _layout("Trace2Test Inventory", f"""<h1>Inventory</h1><form method="get" action="/inventory"><label for="max-stock">Stock less than<input id="max-stock" name="max_stock" type="number" min="0" value="{value}" required></label><button id="apply-filter" type="submit">Apply filter</button></form><p id="result-count">{len(products)} products shown</p><table id="inventory-table"><thead><tr><th>SKU</th><th>Name</th><th>Stock</th><th>Update</th></tr></thead><tbody>{rows}</tbody></table>{export}""")


def _orders_page(store: InventoryStore, status: str | None, query: str | None) -> str:
    orders = store.filtered_orders(status, query)
    rows = "".join(
        f"<tr><td>{html.escape(str(o['order_id']))}</td><td>{html.escape(str(o['customer']))}</td><td>{html.escape(str(o['status']))}</td><td>{html.escape(str(o['total']))}</td><td><form method='post' action='/orders/update'><input type='hidden' name='order_id' value='{html.escape(str(o['order_id']))}'><input type='hidden' name='status' value='shipped'><button type='submit'>Mark {html.escape(str(o['order_id']))} shipped</button></form></td></tr>" for o in orders
    )
    return _layout("Trace2Test Orders", f"""<h1>Orders</h1><form method="get" action="/orders"><label>Status<select name="status"><option value="">All</option><option value="pending" {'selected' if status == 'pending' else ''}>Pending</option><option value="shipped" {'selected' if status == 'shipped' else ''}>Shipped</option></select></label><label>Customer or order<input name="query" value="{html.escape(query or '')}"></label><button type="submit">Apply order filter</button></form><p id="order-count">{len(orders)} orders shown</p><table><thead><tr><th>Order</th><th>Customer</th><th>Status</th><th>Total</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table><a download="orders.csv" href="/orders.csv?{urlencode({'status': status or ''})}">Export orders CSV</a>""")


def _handler(store: InventoryStore):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if store.has_fault("response-delay", parsed.path):
                time.sleep(0.35)
            if parsed.path == "/": self._redirect("/inventory")
            elif parsed.path == "/health": self._send_json({"status": "ok", "fixture": store.fixture_id})
            elif parsed.path == "/api/state": self._send_json(store.snapshot())
            elif parsed.path == "/api/reset": store.reset(); self._send_json(store.snapshot())
            elif parsed.path == "/login":
                error = '<p class="error">Invalid credentials</p>' if query.get("error") else ""
                self._send(_layout("Trace2Test Login", f"""<h1>Login</h1>{error}<form method="post" action="/login"><label>Email<input name="email" type="email" required></label><label>Password<input name="password" type="password" required></label><button type="submit">Sign in</button></form>"""))
            elif parsed.path == "/logout": store.logout(); self._redirect("/login")
            elif parsed.path == "/inventory":
                if store.has_fault("inventory-500", parsed.path): self.send_error(500, "Injected inventory failure")
                else:
                    try: self._send(_inventory_page(store, self._threshold(query, required=False)))
                    except ValueError: self.send_error(400, "max_stock must be a non-negative integer")
            elif parsed.path == "/orders": self._send(_orders_page(store, query.get("status", [""])[0] or None, query.get("query", [""])[0] or None))
            elif parsed.path in {"/export.csv", "/export/inventory.csv"}:
                try:
                    threshold = self._threshold(query, required=True); assert threshold is not None
                    self._send(store.export_inventory_csv(threshold), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="low-inventory.csv"'})
                except ValueError: self.send_error(400, "max_stock must be a non-negative integer")
            elif parsed.path in {"/orders.csv", "/export/orders.csv"}:
                self._send(store.export_orders_csv(query.get("status", [""])[0] or None), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="orders.csv"'})
            else: self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8"))
            value = lambda name: form.get(name, [""])[0]
            if parsed.path == "/login":
                self._redirect("/inventory" if store.login(value("email"), value("password")) else "/login?error=1", 303)
            elif parsed.path == "/inventory/update":
                try: ok = store.update_stock(value("sku"), int(value("stock")))
                except ValueError: ok = False
                self._redirect("/inventory" if ok else "/inventory?error=update", 303)
            elif parsed.path == "/orders/update": self._redirect("/orders" if store.update_order(value("order_id"), value("status")) else "/orders?error=update", 303)
            else: self.send_error(404)

        def _threshold(self, query: dict[str, list[str]], *, required: bool) -> int | None:
            raw = query.get("max_stock", [""])[0]
            if not raw and not required: return None
            try:
                value = int(raw)
                if value < 0: raise ValueError
                return value
            except ValueError as error: raise ValueError("invalid max_stock") from error

        def _redirect(self, location: str, status: int = 302) -> None:
            self.send_response(status); self.send_header("Location", location); self.end_headers()

        def _send_json(self, value: Any) -> None:
            self._send(json.dumps(value, ensure_ascii=False), "application/json; charset=utf-8")

        def _send(self, body: str, content_type: str = "text/html; charset=utf-8", headers: dict[str, str] | None = None) -> None:
            data = body.encode("utf-8"); self.send_response(200); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store")
            for name, value in (headers or {}).items(): self.send_header(name, value)
            self.end_headers(); self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None: return

    return Handler


class InventoryDemoServer:
    def __init__(
        self,
        fixture_path: Path,
        faults: list[str] | None = None,
        port: int = 0,
        host: str = "127.0.0.1",
    ):
        self.store = InventoryStore(fixture_path, faults=faults)
        self._server = ThreadingHTTPServer((host, port), _handler(self.store))
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str: return f"http://127.0.0.1:{self._server.server_port}"
    def start(self) -> "InventoryDemoServer": self.store.reset(); self._thread = threading.Thread(target=self._server.serve_forever, daemon=True); self._thread.start(); return self
    def stop(self) -> None:
        self._server.shutdown(); self._server.server_close()
        if self._thread: self._thread.join(timeout=5)
    def __enter__(self) -> "InventoryDemoServer": return self.start()
    def __exit__(self, exc_type, exc_value, traceback) -> None: self.stop()
