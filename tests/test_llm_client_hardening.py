"""The LLM client against hostile and broken servers, over real sockets.

QA-RUNTIME-1, QA-SEC-4, QA-SEC-10, QA-SEC-11, QA-RUNTIME-9: an exception
that was not an ``LLMError`` took the dictation down, the system proxy
received the words and the key of a "local" request, a redirect carried
the key to another host, and a slow server held the words past the
configured timeout. Real loopback servers here, no mocks of ``urllib``.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.llm import LLMError, LLMSettings, complete

KEY = "sk-HARDENING-KEY-1234"


class _Server:
    def __init__(self, handler_cls):
        self.hits: list[dict] = []
        outer = self

        class Handler(handler_cls):
            def log_message(self, *a):
                pass

            def record(self, body=b""):
                outer.hits.append({
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "body": body,
                })

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def serve():
    started: list[_Server] = []

    def make(handler_cls):
        server = _Server(handler_cls)
        started.append(server)
        return server

    yield make
    for server in started:
        server.close()


def _settings(base_url, **over):
    cfg = {
        "enabled": True, "provider": "openai", "model": "m",
        "base_url": base_url, "api_key": KEY, "timeout_s": 3,
    }
    cfg.update(over)
    return LLMSettings.from_config(cfg)


class _Ok(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.record(body)
        out = json.dumps({"choices": [{"message": {"content": "готово"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


# ---- anything that can go wrong is an LLMError ------------------------------


@pytest.mark.parametrize(
    "base_url",
    ["myserver", "127.0.0.1", "http://[::1", "http://127.0.0.1:99999", "ftp://127.0.0.1/x",
     "file:///etc/passwd", "http://a b/", "http://127.0.0.1:1/\nx", "http://"],
)
def test_a_malformed_address_is_an_llm_error_and_never_another_type(base_url):
    settings = _settings(base_url)

    assert not settings.configured
    with pytest.raises(LLMError):
        complete("привет", settings)


@pytest.mark.parametrize("key", ["abc\ndef", "ключ", "a\x00b"])
def test_a_key_that_cannot_be_a_header_is_refused_without_quoting_it(key):
    settings = _settings("https://api.example.com/v1", api_key=key)

    with pytest.raises(LLMError) as caught:
        complete("привет", settings)

    assert key not in str(caught.value)
    assert "API key" in str(caught.value)


def test_a_key_with_a_trailing_newline_is_trimmed_and_works(serve):
    server = serve(_Ok)

    assert complete("привет", _settings(server.url, api_key=KEY + "\n")) == "готово"
    assert server.hits[0]["auth"] == f"Bearer {KEY}"


def test_a_non_ascii_path_is_encoded_and_works(serve):
    server = serve(_Ok)

    assert complete("привет", _settings(server.url + "/ё")) == "готово"


def test_a_server_that_does_not_speak_http_is_an_llm_error(serve):
    class Garbage(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.wfile.write(b"GARBAGE\r\n\r\n")
            self.close_connection = True

    server = serve(Garbage)

    with pytest.raises(LLMError) as caught:
        complete("привет", _settings(server.url))
    assert KEY not in str(caught.value)


def test_a_cut_off_reply_is_an_llm_error(serve):
    class Cut(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b"{")
            self.wfile.flush()

    server = serve(Cut)

    with pytest.raises(LLMError):
        complete("привет", _settings(server.url))


# ---- the key does not follow a redirect -------------------------------------


def test_a_redirect_is_refused_and_the_key_goes_nowhere_else(serve):
    stolen = serve(_Ok)

    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.record()
            self.send_response(302)
            self.send_header("Location", stolen.url + "/stolen")
            self.send_header("Content-Length", "0")
            self.end_headers()

    origin = serve(Redirect)

    with pytest.raises(LLMError) as caught:
        complete("привет", _settings(origin.url))

    assert "redirect" in str(caught.value)
    assert stolen.hits == []


# ---- one wall-clock budget ---------------------------------------------------


def test_a_server_that_drips_bytes_cannot_hold_the_dictation(serve):
    class Drip(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(200)
            self.send_header("Content-Length", "100000")
            self.end_headers()
            for _ in range(60):
                try:
                    self.wfile.write(b" ")
                    self.wfile.flush()
                except OSError:
                    return
                time.sleep(0.3)

    server = serve(Drip)
    started = time.monotonic()

    with pytest.raises(LLMError):
        complete("привет", _settings(server.url, timeout_s=1))

    assert time.monotonic() - started < 3.0


def test_a_server_that_never_answers_is_abandoned_at_the_deadline():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        started = time.monotonic()
        with pytest.raises(LLMError):
            complete(
                "привет",
                _settings(f"http://127.0.0.1:{listener.getsockname()[1]}", timeout_s=1),
            )
        assert time.monotonic() - started < 3.0
    finally:
        listener.close()


# ---- proxy policy ------------------------------------------------------------


@pytest.fixture
def proxy_env(monkeypatch):
    """A listening 'proxy' that records whatever reaches it."""
    received: list[bytes] = []
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)

    def accept():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            conn.settimeout(1)
            try:
                received.append(conn.recv(65536))
            except OSError:
                pass
            conn.close()

    threading.Thread(target=accept, daemon=True).start()
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy",
                 "HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(name, url)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    yield received
    listener.close()


def test_a_loopback_endpoint_is_never_sent_through_a_proxy(serve, proxy_env):
    server = serve(_Ok)

    assert complete("привет", _settings(server.url)) == "готово"
    assert proxy_env == []
    assert server.hits and server.hits[0]["auth"] == f"Bearer {KEY}"


def test_a_private_lan_address_bypasses_the_proxy_too():
    from app.llm.client import _bypasses_proxy

    for url in ("http://192.168.1.5:1234/v1", "http://10.0.0.2/v1",
                "http://localhost:11434", "http://[::1]:11434", "http://box.local/v1"):
        assert _bypasses_proxy(url), url


def test_a_remote_host_uses_the_proxy_the_environment_names(proxy_env):
    """The one case where a proxy is allowed: the user's environment named
    one and the host is not on this computer or its network."""
    with pytest.raises(LLMError):
        complete("привет", _settings("http://api.example.invalid/v1", timeout_s=2))

    assert proxy_env and proxy_env[0].startswith(b"POST http://api.example.invalid/")
