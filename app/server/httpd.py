"""The loopback HTTP channel: ``POST /rpc`` and ``GET /events``.

Standard library only. The channel is bound to 127.0.0.1 and every request
has to carry the per-launch token, so another local program or a web page
open in a browser cannot drive the microphone. A page cannot read the
token, and the Host header is checked as well, which is what stops a DNS
rebinding attempt from reaching the socket under a name the attacker owns.
"""

from __future__ import annotations

import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from app.server import rpc
from app.server.events import bus

log = logging.getLogger(__name__)

_MAX_BODY = 4 * 1024 * 1024
_HEARTBEAT_S = 15.0


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, runtime: Any, token: str) -> None:
        super().__init__(address, handler)
        self.runtime = runtime
        self.token = token
        self.stopping = threading.Event()


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"

    # The default writes one line per request to stderr, which for the
    # event stream and a 200 ms poll is a log nobody can read.
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
        log.debug("http: " + fmt, *args)

    def handle(self) -> None:
        # A renderer closing its tab or the event stream resets the socket;
        # that is how every connection ends, not a failure to report.
        try:
            super().handle()
        except (ConnectionError, TimeoutError):
            pass

    # ---- guards ---------------------------------------------------------

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in ("127.0.0.1", "localhost", "::1")

    def _token_ok(self, query: dict) -> bool:
        supplied = ""
        header = self.headers.get("Authorization") or ""
        if header.startswith("Bearer "):
            supplied = header[7:]
        elif "token" in query:
            supplied = query["token"][0]
        return hmac.compare_digest(supplied, self.server.token)

    def _cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers",
                             "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, status: int, body: Any) -> None:
        raw = json.dumps(body, default=str, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    # ---- routes ---------------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802 — stdlib naming
        if not self._host_ok():
            self.send_error(403)
            return
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if not self._host_ok():
            self.send_error(403)
            return
        if url.path == "/health":
            self._json(200, {"ok": True})
            return
        if not self._token_ok(query):
            self._json(401, {"error": {"code": "unauthorized", "message": "bad token"}})
            return
        if url.path == "/events":
            self._stream_events()
            return
        self._json(404, {"error": {"code": "not_found", "message": url.path}})

    def do_POST(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        if not self._host_ok():
            self.send_error(403)
            return
        if not self._token_ok(parse_qs(url.query)):
            self._json(401, {"error": {"code": "unauthorized", "message": "bad token"}})
            return
        if url.path != "/rpc":
            self._json(404, {"error": {"code": "not_found", "message": url.path}})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > _MAX_BODY:
            self._json(400, {"error": {"code": "bad_request", "message": "body size"}})
            return
        try:
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            name = request["method"]
            params = request.get("params") or {}
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            self._json(400, {"error": {"code": "bad_request", "message": "not a request"}})
            return

        try:
            result = rpc.dispatch(self.server.runtime, str(name), params)
        except rpc.RpcError as exc:
            self._json(200, {"error": {"code": exc.code, "message": exc.message}})
            return
        except Exception as exc:  # a handler's bug must not end the server
            log.exception("RPC %s failed", name)
            self._json(200, {"error": {"code": "internal", "message": str(exc)}})
            return
        self._json(200, {"result": result})

    def _stream_events(self) -> None:
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        sub = bus.subscribe()
        try:
            self.wfile.write(b": open\n\n")
            self.wfile.flush()
            while not self.server.stopping.is_set():
                item = sub.get(_HEARTBEAT_S)
                if item is None:
                    self.wfile.write(b": ping\n\n")
                else:
                    name, payload = item
                    self.wfile.write(
                        f"event: {name}\ndata: {payload}\n\n".encode("utf-8")
                    )
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            sub.close()


class Channel:
    """The running server: bind, serve on a thread, stop."""

    def __init__(self, runtime: Any, token: str, port: int = 0) -> None:
        self._httpd = _Server(("127.0.0.1", port), _Handler, runtime, token)
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return int(self._httpd.server_address[1])

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="rpc-http", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._httpd.stopping.set()
        self._httpd.shutdown()
        self._httpd.server_close()
