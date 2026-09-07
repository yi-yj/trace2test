"""Small localhost-only inventory application with deterministic reset state."""

from __future__ import annotations

import csv
import html
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from tracetotest.fixtures import JsonFixture


class InventoryStore:
    def __init__(self, fixture_path: Path):
        self.fixture = JsonFixture(fixture_path)
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
            self._export_count = 0
            self._last_export_skus: list[str] = []
            self._database_mutations = 0

    def products(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self.fixture.mutable_state()["products"]]

    def filtered_products(self, max_stock: int | None) -> list[dict[str, Any]]:
        with self._lock:
            self._active_max_stock = max_stock
            products = self.products()
            return products if max_stock is None else [item for item in products if item["stock"] < max_stock]

    def export_csv(self, max_stock: int) -> str:
        rows = self.filtered_products(max_stock)
        with self._lock:
            self._export_count += 1
            self._last_export_skus = [str(item["sku"]) for item in rows]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=("sku", "name", "stock"), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue()

    def set_stock_for_test(self, sku: str, stock: int) -> None:
        """Test-only mutation used to prove reset reproducibility; not exposed over HTTP."""
        with self._lock:
            product = next(item for item in self.fixture.mutable_state()["products"] if item["sku"] == sku)
            product["stock"] = stock
            self._database_mutations += 1

    def checksum(self) -> str:
        return self.fixture.checksum()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "fixture_id": self.fixture_id,
                "fixture_version": self.fixture_version,
                "fixture_checksum": self.checksum(),
                "pristine_checksum": self.fixture.pristine_checksum,
                "active_max_stock": self._active_max_stock,
                "export_count": self._export_count,
                "last_export_skus": list(self._last_export_skus),
                "database_mutations": self._database_mutations,
            }


def _page(store: InventoryStore, max_stock: int | None) -> str:
    products = store.filtered_products(max_stock)
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item['sku']))}</td>"
        f"<td>{html.escape(str(item['name']))}</td>"
        f"<td>{int(item['stock'])}</td>"
        "</tr>"
        for item in products
    )
    value = "" if max_stock is None else str(max_stock)
    export = (
        f'<a id="export-csv" download="low-inventory.csv" href="/export.csv?max_stock={max_stock}">'
        "Export filtered CSV</a>"
        if max_stock is not None
        else '<span id="export-hint">Apply a filter before exporting.</span>'
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trace2Test Inventory</title>
  <style>
    body {{ font: 16px/1.45 sans-serif; max-width: 900px; margin: 40px auto; color: #17202a; }}
    form {{ display: flex; gap: 12px; align-items: end; margin: 24px 0; }}
    label {{ display: grid; gap: 5px; }} input, button, a {{ font: inherit; padding: 8px 12px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
    th, td {{ border: 1px solid #bac3cc; padding: 9px; text-align: left; }}
    th {{ background: #edf3f7; }} a {{ display: inline-block; background: #1261a0; color: white; }}
  </style>
</head>
<body>
  <h1>Inventory</h1>
  <p>Filter products by stock and export exactly the visible rows.</p>
  <form method="get" action="/inventory">
    <label for="max-stock">Stock less than
      <input id="max-stock" name="max_stock" type="number" min="0" value="{value}" required>
    </label>
    <button id="apply-filter" type="submit">Apply filter</button>
  </form>
  <p id="result-count">{len(products)} products shown</p>
  <table id="inventory-table">
    <thead><tr><th>SKU</th><th>Name</th><th>Stock</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  {export}
</body>
</html>"""


def _handler(store: InventoryStore):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/":
                self.send_response(302)
                self.send_header("Location", "/inventory")
                self.end_headers()
                return
            if parsed.path == "/health":
                self._send_json({"status": "ok"})
                return
            if parsed.path == "/api/state":
                self._send_json(store.snapshot())
                return
            if parsed.path == "/api/inventory":
                try:
                    threshold = self._threshold(query, required=False)
                except ValueError:
                    self.send_error(400, "max_stock must be a non-negative integer")
                    return
                self._send_json({"products": store.filtered_products(threshold)})
                return
            if parsed.path == "/inventory":
                try:
                    threshold = self._threshold(query, required=False)
                except ValueError:
                    self.send_error(400, "max_stock must be a non-negative integer")
                    return
                self._send(_page(store, threshold), "text/html; charset=utf-8")
                return
            if parsed.path == "/export.csv":
                try:
                    threshold = self._threshold(query, required=True)
                except ValueError:
                    self.send_error(400, "max_stock must be a non-negative integer")
                    return
                assert threshold is not None
                self._send(
                    store.export_csv(threshold),
                    "text/csv; charset=utf-8",
                    {"Content-Disposition": 'attachment; filename="low-inventory.csv"'},
                )
                return
            self.send_error(404)

        def _threshold(self, query: dict[str, list[str]], *, required: bool) -> int | None:
            raw = query.get("max_stock", [""])[0]
            if not raw and not required:
                return None
            try:
                value = int(raw)
                if value < 0:
                    raise ValueError
                return value
            except ValueError as error:
                raise ValueError("invalid max_stock") from error

        def _send_json(self, value: Any) -> None:
            self._send(json.dumps(value, ensure_ascii=False), "application/json; charset=utf-8")

        def _send(self, body: str, content_type: str, headers: dict[str, str] | None = None) -> None:
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


class InventoryDemoServer:
    def __init__(self, fixture_path: Path):
        self.store = InventoryStore(fixture_path)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self.store))
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def start(self) -> "InventoryDemoServer":
        self.store.reset()
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=5)

    def __enter__(self) -> "InventoryDemoServer":
        return self.start()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stop()
