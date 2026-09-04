"""multinode_aq web front end (Phase 8): JSON API + static pages, standard
library only.

    .venv/bin/python webapp.py --port 8501            # board (systemd unit, took over the old Streamlit port)
    uv run python webapp.py --db fixtures/sample.db   # PC, fixture data

Routes
    GET  /                    web/index.html   (SPA shell -- hash-routed screens)
    GET  /diagnosis           302 -> /#dx-regime (old page-2 bookmarks)
    GET  /static/<file>       web/<file> (incl. web/screens/*)
    GET  /api/status          sidebar / Home status (hub freshness, nodes, analyst runs, model)
    GET  /api/live            radar screen (+ node list for the series screen)
    GET  /api/stats           stats screen (28-day box stats, CO2 / VOC means per node)
    GET  /api/series?node=    series + records screens (60 buckets, records, vision panel)
    GET  /api/bounds          KST min / max for the range export (관리 screen)
    GET  /api/export?kind=all|merged|occupancy|range[&start=&end=]   CSV, built on request
    GET  /api/analysis        diagnosis bundle (analysis table + models/) -- dx-* + Home
    POST /api/reset           관리 screen: CSV backup then DELETE FROM readings
                              (body {"confirm": "DELETE"}) -- same behaviour as dashboard.py

--public (monitoring-only instance, e.g. the one behind Tailscale Funnel on 8502):
/api/export and /api/reset answer 403 and /api/status carries "public": true, so
the client hides the admin screens (최근기록 · 유효범위 · 모델이력 · 관리). The
admin instance (8501) runs without it.

The data layer is aq.webdata (read-only, memoised on the DB version). Reset is
the one write and lives here, not in aq/ (CI guard), exactly as page 1 keeps
its own read-write connection for section 6.
"""

from __future__ import annotations

import argparse
import gzip
import json
import mimetypes
import os
import sqlite3
import sys
import threading
from contextlib import closing
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from urllib.parse import parse_qs, urlparse

HUB = Path(__file__).resolve().parent
WEB = HUB / "web"
MIN_GZIP = 1024
PAGES = {"/": "index.html", "/index.html": "index.html"}
REDIRECTS = {"/diagnosis": "/#dx-regime", "/diagnosis.html": "/#dx-regime"}   # old page-2 bookmarks


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "multinode_aq/0.8"
    data = None          # aq.webdata.WebData, set by serve()
    quiet = False
    public = False       # --public: no export, no reset

    # ---- plumbing -----------------------------------------------------------------------
    def log_message(self, fmt, *args):     # default access log is noisy; perf lines instead
        if not self.quiet:
            _log(f"[http] {self.address_string()} {fmt % args}")

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None,
              cache: str = "no-cache") -> None:
        accept = self.headers.get("Accept-Encoding", "")
        if len(body) >= MIN_GZIP and "gzip" in accept:
            body = gzip.compress(body, compresslevel=5)
            enc = "gzip"
        else:
            enc = None
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        if enc:
            self.send_header("Content-Encoding", enc)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, allow_nan=False, default=_default).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, msg: str) -> None:
        self._json({"error": msg}, status)

    # ---- routing ------------------------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        t = perf_counter()
        try:
            if url.path.startswith("/api/"):
                self._api(url.path[5:], q)
            elif url.path in PAGES:
                self._static(PAGES[url.path])
            elif url.path in REDIRECTS:
                self.send_response(302)
                self.send_header("Location", REDIRECTS[url.path])
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif url.path.startswith("/static/"):
                self._static(url.path[8:])
            else:
                self._error(404, "not found")
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001 -- one bad request must not kill the server
            _log(f"[error] {url.path}: {e!r}")
            try:
                self._error(500, f"{type(e).__name__}: {e}")
            except Exception:  # noqa: BLE001
                pass
        finally:
            if url.path.startswith("/api/"):
                _log(f"[perf] {url.path} {perf_counter() - t:.3f}s")

    def do_POST(self):
        url = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self._error(400, "bad json")
        if url.path == "/api/reset":
            if self.public:
                return self._error(403, "reset is disabled on the public instance")
            return self._reset(body)
        self._error(404, "not found")

    # ---- static -------------------------------------------------------------------------
    def _static(self, rel: str) -> None:
        p = (WEB / rel).resolve()
        if WEB.resolve() not in p.parents or not p.is_file():     # no escape from web/
            return self._error(404, "not found")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        cache = "no-cache"          # css / js change with every deploy; a page load re-validates
        self._send(200, p.read_bytes(), ctype, cache=cache)

    # ---- api ----------------------------------------------------------------------------
    def _api(self, name: str, q: dict) -> None:
        d = self.data
        if name == "status":
            return self._json({**d.status(), "public": self.public})
        if name == "live":
            return self._json(d.live())
        if name == "stats":
            return self._json(d.stats())
        if name == "series":
            node = q.get("node")
            if not node:
                return self._error(400, "node required")
            return self._json(d.series(node))
        if name == "bounds":
            return self._json(d.time_bounds())
        if name == "analysis":
            return self._json(d.analysis())
        if name == "export":
            if self.public:
                return self._error(403, "export is disabled on the public instance")
            return self._export(q)
        self._error(404, "unknown endpoint")

    def _export(self, q: dict) -> None:
        kind = q.get("kind", "all")
        if kind not in ("all", "merged", "occupancy", "range"):
            return self._error(400, "kind must be all | merged | occupancy | range")
        if kind == "range":
            start, end = q.get("start"), q.get("end")
            try:
                if not (start and end) or datetime.fromisoformat(start) > datetime.fromisoformat(end):
                    return self._error(400, "start / end (KST, ISO) required, start <= end")
            except ValueError:
                return self._error(400, "start / end must be ISO datetimes")
        else:
            start = end = None
        name, df = self.data.export(kind, start, end)
        body = df.to_csv(index=False).encode("utf-8-sig") if not df.empty else b""
        self._send(200, body, "text/csv; charset=utf-8",
                   {"Content-Disposition": f'attachment; filename="{name}"',
                    "X-Rows": str(len(df))}, cache="no-store")

    def _reset(self, body: dict) -> None:
        """Section 6 of page 1: back the table up to a CSV next to the DB, then
        empty readings. hub.py keeps writing into the empty table."""
        if body.get("confirm") != "DELETE":
            return self._error(400, 'confirm must be "DELETE"')
        d = self.data
        _, df = d.export("all")
        if df.empty:
            return self._json({"rows": 0, "backup": None})
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = os.path.join(os.path.dirname(os.path.abspath(d.db_path)) or ".",
                              f"sensor_backup_{stamp}.csv")
        df.to_csv(backup, index=False, encoding="utf-8-sig")
        with closing(sqlite3.connect(d.db_path, timeout=5)) as con:
            con.execute("DELETE FROM readings")
            con.commit()
        try:
            with closing(sqlite3.connect(d.db_path, timeout=2)) as con:
                con.execute("VACUUM")
        except sqlite3.Error:
            pass
        d._cache.clear()
        _log(f"[reset] {len(df)} rows -> {backup}")
        self._json({"rows": int(len(df)), "backup": backup})


def _default(o):
    """json.dumps fallback for numpy scalars / arrays."""
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "tolist"):
        return o.tolist()
    raise TypeError(f"not serialisable: {type(o).__name__}")


def make_server(host: str, port: int, data, quiet: bool = False,
                public: bool = False) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"data": data, "quiet": quiet, "public": public})
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    return srv


def serve_in_thread(data, host: str = "127.0.0.1", port: int = 0, public: bool = False):
    """Tests: start on an ephemeral port, return (server, base_url)."""
    srv = make_server(host, port, data, quiet=True, public=public)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, f"http://{host}:{srv.server_address[1]}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8501)
    ap.add_argument("--db", default=str(HUB / "sensor_data.db"))
    ap.add_argument("--nodes", default=str(HUB / "nodes.json"))
    ap.add_argument("--models-dir", dest="models_dir", default=str(HUB / "models"))
    ap.add_argument("--quiet", action="store_true", help="no per-request access log")
    ap.add_argument("--public", action="store_true",
                    help="monitoring-only: no CSV export, no reset (pages hide sections 5-6)")
    a = ap.parse_args(argv)
    from aq.webdata import WebData

    data = WebData(a.db, a.nodes, a.models_dir)
    srv = make_server(a.host, a.port, data, quiet=a.quiet, public=a.public)
    _log(f"[webapp] serving {WEB} + /api on http://{a.host}:{a.port}  db={a.db}"
         f"{'  [public: no export / reset]' if a.public else ''}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
