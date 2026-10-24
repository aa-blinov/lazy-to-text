"""The loopback HTTP channel: ``POST /rpc`` and ``GET /events``.

Standard library only. The channel is bound to 127.0.0.1 and every request
has to carry the per-launch token, so another local program or a web page
open in a browser cannot drive the microphone. A page cannot read the
token, and the Host header is checked as well, which is what stops a DNS
rebinding attempt from reaching the socket under a name the attacker owns.

Hardening, each item the answer to a measured failure:

* a read timeout on every connection and a bounded number of them, so idle
  sockets opened by another local process cannot starve the renderer;
* the token goes in the ``Authorization`` header; only ``GET /events`` also
  takes it (or a one-time ticket) in the query string, because
  ``EventSource`` cannot send headers, and that URL is never logged;
* a page whose ``Origin`` is not one of the application's own is refused
  outright, and CORS headers are never echoed for an arbitrary origin;
* the token is compared as bytes, so a non-ASCII value is a 401 and not a
  traceback.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable, Optional
from urllib.parse import parse_qs, urlsplit

from app.server import rpc, tickets
from app.server.events import bus

log = logging.getLogger(__name__)

_MAX_BODY = 4 * 1024 * 1024
_HEARTBEAT_S = 15.0
#: Seconds a connection may sit without delivering the bytes the server is
#: waiting for (a request line, a header, the body) before it is dropped.
_IO_TIMEOUT_S = 10.0
#: Connections served at once, event streams included. Beyond this a new
#: connection is closed unanswered instead of getting a thread.
_MAX_CONNECTIONS = 96
#: Of those, how many may be event streams (a window and the capsule hold one
#: each; the rest is room for a reload that has not been noticed yet).
_MAX_STREAMS = 12

#: Origins a packaged window has: ``file://`` pages report ``null``.
_PACKAGED_ORIGINS = ("null", "file://")

_SECRET_IN_TEXT = re.compile(r"((?:token|ticket)=)[^&\s\"']+", re.IGNORECASE)


def dev_origins(port: int) -> tuple[str, str]:
    """The two spellings of the Vite dev server's origin."""
    return (f"http://127.0.0.1:{port}", f"http://localhost:{port}")


def _scrub(value: Any) -> Any:
    return _SECRET_IN_TEXT.sub(r"\1<hidden>", value) if isinstance(value, str) else value


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128

    def __init__(
        self,
        address,
        handler,
        runtime: Any,
        token: str,
        allowed_origins: Iterable[str] = _PACKAGED_ORIGINS,
    ) -> None:
        super().__init__(address, handler)
        self.runtime = runtime
        self.token = token
        self.token_bytes = token.encode("utf-8")
        self.allowed_origins = frozenset(allowed_origins)
        self.stopping = threading.Event()
        self._slots = threading.BoundedSemaphore(_MAX_CONNECTIONS)
        self._streams = 0
        self._streams_lock = threading.Lock()

    # A connection that cannot get a slot is closed at once: answering it
    # would need a thread, which is the thing that ran out.
    def process_request(self, request, client_address) -> None:
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def open_stream(self) -> bool:
        with self._streams_lock:
            if self._streams >= _MAX_STREAMS:
                return False
            self._streams += 1
            return True

    def close_stream(self) -> None:
        with self._streams_lock:
            self._streams = max(0, self._streams - 1)


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"
    timeout = _IO_TIMEOUT_S

    # The default writes one line per request to stderr, which for the
    # event stream and a 200 ms poll is a log nobody can read. What does get
    # written never carries a token: the stream's URL holds one.
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
        log.debug("http: " + _scrub(fmt), *[_scrub(a) for a in args])

    def handle(self) -> None:
        # A renderer closing its tab or the event stream resets the socket;
        # that is how every connection ends, not a failure to report.
        try:
            super().handle()
        except (ConnectionError, TimeoutError, OSError):
            pass

    # ---- guards ---------------------------------------------------------

    def _host_ok(self) -> bool:
        raw = (self.headers.get("Host") or "").strip()
        if raw.startswith("["):
            host = raw[1:].split("]", 1)[0]
        else:
            host = raw.split(":", 1)[0]
        return host in ("127.0.0.1", "localhost", "::1")

    def _origin(self) -> Optional[str]:
        return self.headers.get("Origin")

    def _origin_ok(self) -> bool:
        origin = self._origin()
        return origin is None or origin in self.server.allowed_origins

    def _token_ok(self, query: dict, *, allow_query: bool) -> bool:
        """Header always; the query string only where the caller says so."""
        header = self.headers.get("Authorization") or ""
        if header.startswith("Bearer "):
            return self._same(header[7:])
        if allow_query:
            if "token" in query and self._same(query["token"][0]):
                return True
            if "ticket" in query and tickets.redeem(query["ticket"][0]):
                return True
        return False

    def _same(self, supplied: str) -> bool:
        # Bytes, not str: ``compare_digest`` raises on a non-ASCII string.
        return hmac.compare_digest(
            supplied.encode("utf-8", "replace"), self.server.token_bytes
        )

    def _cors(self) -> None:
        origin = self._origin()
        if origin and origin in self.server.allowed_origins:
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

    def _refuse(self, status: int, code: str, message: str) -> None:
        self._json(status, {"error": {"code": code, "message": message}})

    def _gate(self) -> bool:
        """Host and Origin; the answer has been sent when this is False."""
        if not self._host_ok():
            self._refuse(403, "forbidden", "bad host")
            return False
        if not self._origin_ok():
            self._refuse(403, "forbidden", "origin not allowed")
            return False
        return True

    # ---- routes ---------------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802 — stdlib naming
        if not self._gate():
            return
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if not self._gate():
            return
        if url.path == "/health":
            self._json(200, {"ok": True})
            return
        if not self._token_ok(query, allow_query=url.path == "/events"):
            self._refuse(401, "unauthorized", "bad token")
            return
        if url.path == "/events":
            self._stream_events()
            return
        self._refuse(404, "not_found", url.path)

    def do_POST(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        if not self._gate():
            return
        if not self._token_ok({}, allow_query=False):
            self._refuse(401, "unauthorized", "bad token")
            return
        if url.path != "/rpc":
            self._refuse(404, "not_found", url.path)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > _MAX_BODY:
            self._refuse(400, "bad_request", "body size")
            return
        try:
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            name = request["method"]
            params = request.get("params") or {}
        except (ValueError, KeyError, TypeError, AttributeError,
                UnicodeDecodeError, RecursionError):
            self._refuse(400, "bad_request", "not a request")
            return

        try:
            result = rpc.dispatch(self.server.runtime, str(name), params)
        except rpc.RpcError as exc:
            error = {"code": exc.code, "message": exc.message}
            if exc.field:
                error["field"] = exc.field
            self._json(200, {"error": error})
            return
        except Exception as exc:  # a handler's bug must not end the server
            log.exception("RPC %s failed", name)
            self._json(200, {"error": {
                "code": "internal",
                "message": f"Something went wrong inside the app "
                           f"({type(exc).__name__}). The Logs have the details.",
            }})
            return
        self._json(200, {"result": result})

    def _stream_events(self) -> None:
        if not self.server.open_stream():
            self._refuse(503, "busy", "too many event streams")
            return
        try:
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
        finally:
            self.server.close_stream()


class Channel:
    """The running server: bind, serve on a thread, stop."""

    def __init__(
        self,
        runtime: Any,
        token: str,
        port: int = 0,
        allowed_origins: Iterable[str] = _PACKAGED_ORIGINS,
    ) -> None:
        self._httpd = _Server(
            ("127.0.0.1", port), _Handler, runtime, token, allowed_origins
        )
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
