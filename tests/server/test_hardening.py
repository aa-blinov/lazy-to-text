"""The loopback channel under hostile or careless callers (QA-SEC-12/13/19, QA-RUNTIME-19).

Every test here fails against the channel as it was: no read timeout, no
connection limit, an ``Origin`` echoed back to any page, a token compared
as text, the token in a POST's query string and in the log.
"""

from __future__ import annotations

import http.client
import json
import logging
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from app.server import httpd, rpc, tickets
from app.server.httpd import Channel

TOKEN = "t" * 32


@pytest.fixture(scope="module", autouse=True)
def _handlers():
    if "test.echo2" not in rpc.method_names():
        @rpc.method("test.echo2")
        def echo(rt, params):
            return {"echo": params}

        @rpc.method("test.field")
        def field(rt, params):
            raise rpc.RpcError("bad_params", "no good", field="path")

        @rpc.method("test.leaky")
        def leaky(rt, params):
            raise ValueError("secret detail /Users/x/build/onnx.cc:42")
    yield


def _channel(monkeypatch=None, origins=httpd._PACKAGED_ORIGINS, **tweaks):
    if monkeypatch is not None:
        for name, value in tweaks.items():
            monkeypatch.setattr(httpd, name, value)
    ch = Channel(object(), TOKEN, 0, origins)
    ch.start()
    return ch


@pytest.fixture()
def channel():
    ch = _channel()
    yield ch
    ch.stop()


def _request(channel, method, path, *, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", channel.port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def _rpc(channel, body, headers=None):
    merged = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    merged.update(headers or {})
    return _request(channel, "POST", "/rpc", headers=merged, body=json.dumps(body))


# ---- idle and abusive connections ---------------------------------------------


def test_an_idle_connection_is_dropped_after_the_read_timeout(monkeypatch):
    monkeypatch.setattr(httpd._Handler, "timeout", 0.4)
    ch = _channel()
    try:
        idle = socket.create_connection(("127.0.0.1", ch.port))
        idle.settimeout(3)
        started = time.monotonic()
        assert idle.recv(1) == b""  # the server closed it
        assert time.monotonic() - started < 2.5
        idle.close()
    finally:
        ch.stop()


_WINDOWS_SHEDDING = pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "Winsock's shutdown() does not wake a thread blocked in recv(), so the "
        "channel's cut of a slow connection takes effect only when the "
        "per-read timeout ends; the shedding behaviour is asserted on POSIX "
        "and listed under Known Gaps in specs/010-electron-interface/plan.md"
    ),
)


@_WINDOWS_SHEDDING
def test_a_burst_of_idle_connections_does_not_starve_the_channel(monkeypatch):
    monkeypatch.setattr(httpd._Handler, "timeout", 0.5)
    ch = _channel(monkeypatch, _MAX_CONNECTIONS=8)
    held = []
    try:
        for _ in range(60):
            try:
                held.append(socket.create_connection(("127.0.0.1", ch.port), timeout=2))
            except OSError:
                break
        # Past the limit the extra connections are closed without an answer.
        closed = 0
        for sock in held:
            sock.settimeout(0.05)
            try:
                if sock.recv(1) == b"":
                    closed += 1
            except socket.timeout:
                pass
            except OSError:
                # Windows reports a connection the server closed as a reset
                # where POSIX reports end-of-file; both mean it was closed.
                closed += 1
        assert closed >= 40
        # And once the idle ones time out the channel answers again.
        deadline = time.monotonic() + 5
        status = None
        while time.monotonic() < deadline and status != 200:
            try:
                status, _, _ = _request(ch, "GET", "/health")
            except OSError:
                time.sleep(0.1)
        assert status == 200
    finally:
        for sock in held:
            sock.close()
        ch.stop()


def test_too_many_event_streams_are_refused(monkeypatch):
    ch = _channel(monkeypatch, _MAX_STREAMS=2)
    streams = []
    try:
        for _ in range(2):
            req = urllib.request.Request(f"http://127.0.0.1:{ch.port}/events?ticket={tickets.issue()}")
            streams.append(urllib.request.urlopen(req, timeout=5))
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(
                urllib.request.Request(f"http://127.0.0.1:{ch.port}/events?ticket={tickets.issue()}"),
                timeout=5,
            )
        assert err.value.code == 503
    finally:
        for stream in streams:
            stream.close()
        ch.stop()


# ---- the token ----------------------------------------------------------------


def test_a_non_ascii_token_is_a_401_and_the_server_keeps_answering(channel):
    with socket.create_connection(("127.0.0.1", channel.port), timeout=3) as sock:
        sock.sendall(
            "POST /rpc HTTP/1.1\r\nHost: 127.0.0.1\r\n".encode()
            + "Authorization: Bearer café\r\n".encode("latin-1")
            + b"Content-Length: 2\r\n\r\n{}"
        )
        reply = sock.recv(4096)
    assert reply.startswith(b"HTTP/1.1 401")

    status, _, _ = _request(channel, "GET", "/events?token=%C3%A9")
    assert status == 401
    assert _request(channel, "GET", "/health")[0] == 200


def test_a_post_does_not_take_the_token_from_the_query_string(channel):
    status, _, _ = _request(
        channel, "POST", f"/rpc?token={TOKEN}",
        headers={"Content-Type": "application/json"},
        body=json.dumps({"method": "test.echo2"}),
    )
    assert status == 401
    assert _rpc(channel, {"method": "test.echo2"})[0] == 200


def test_the_event_stream_does_not_take_the_token_in_its_url(channel):
    """QA-SEC-R6: the launch token in a URL ends up in histories and proxy
    logs. The stream takes the header or a one-time ticket, nothing else."""
    assert _request(channel, "GET", f"/events?token={TOKEN}")[0] == 401
    req = urllib.request.Request(
        f"http://127.0.0.1:{channel.port}/events",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        assert response.status == 200


def test_a_ticket_opens_one_stream_and_then_it_is_spent(channel):
    ticket = tickets.issue()
    url = f"http://127.0.0.1:{channel.port}/events?ticket={ticket}"
    with urllib.request.urlopen(url, timeout=5) as response:
        assert response.status == 200
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(url, timeout=5)
    assert err.value.code == 401


def test_an_expired_ticket_is_refused(monkeypatch):
    ticket = tickets.issue()
    real = time.monotonic
    monkeypatch.setattr(tickets.time, "monotonic", lambda: real() + 3600)
    assert tickets.redeem(ticket) is False


def test_the_token_never_reaches_a_log_record(channel, caplog):
    caplog.set_level(logging.DEBUG)
    ticket = tickets.issue()
    req = urllib.request.Request(f"http://127.0.0.1:{channel.port}/events?ticket={ticket}")
    with urllib.request.urlopen(req, timeout=5):
        pass
    _request(channel, "GET", f"/events?token={TOKEN}")
    time.sleep(0.1)
    assert caplog.records, "the request was not logged at all"
    assert all(TOKEN not in record.getMessage() for record in caplog.records)
    assert all(ticket not in record.getMessage() for record in caplog.records)


# ---- who may talk to it -------------------------------------------------------


def test_a_foreign_origin_is_refused_and_never_echoed(channel):
    for method, path in (("OPTIONS", "/rpc"), ("GET", "/health"), ("POST", "/rpc")):
        status, headers, _ = _request(
            channel, method, path,
            headers={"Origin": "https://evil.example",
                     "Authorization": f"Bearer {TOKEN}"},
            body=json.dumps({"method": "test.echo2"}) if method == "POST" else None,
        )
        assert status == 403, (method, path)
        assert "Access-Control-Allow-Origin" not in headers


APP_ORIGIN = "l2t-app://app"


def test_only_the_named_origins_get_cors(monkeypatch):
    app = _channel(origins=[APP_ORIGIN])
    dev = _channel(origins=[APP_ORIGIN] + list(httpd.dev_origins(5173)))
    try:
        status, headers, _ = _request(app, "GET", "/health", headers={"Origin": APP_ORIGIN})
        assert status == 200 and headers["Access-Control-Allow-Origin"] == APP_ORIGIN
        assert _request(app, "GET", "/health",
                        headers={"Origin": "http://127.0.0.1:5173"})[0] == 403
        status, headers, _ = _request(dev, "GET", "/health",
                                      headers={"Origin": "http://127.0.0.1:5173"})
        assert status == 200
        assert headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
        assert _request(dev, "GET", "/health",
                        headers={"Origin": "http://127.0.0.1:5174"})[0] == 403
    finally:
        app.stop()
        dev.stop()


@pytest.mark.parametrize("origin", ["null", "file://"])
@pytest.mark.parametrize("method, path", [("GET", "/health"), ("OPTIONS", "/rpc"), ("POST", "/rpc")])
def test_the_null_and_file_origins_are_refused_even_with_the_app_origin_named(origin, method, path):
    """QA-SEC-R3: ``null`` is the origin of every sandboxed frame, ``data:``
    page and local file on any site; it was in the allow-list by default."""
    ch = _channel(origins=[APP_ORIGIN])
    try:
        status, headers, _ = _request(
            ch, method, path,
            headers={"Origin": origin, "Authorization": f"Bearer {TOKEN}"},
            body=json.dumps({"method": "test.echo2"}) if method == "POST" else None,
        )
        assert status == 403
        assert "Access-Control-Allow-Origin" not in headers
    finally:
        ch.stop()


def test_a_runtime_started_without_arguments_names_no_origin():
    assert httpd._PACKAGED_ORIGINS == ()


def test_a_call_without_an_origin_is_not_affected(channel):
    status, _, body = _rpc(channel, {"method": "test.echo2", "params": {"a": 1}})
    assert status == 200 and json.loads(body)["result"] == {"echo": {"a": 1}}


# ---- bodies and errors --------------------------------------------------------


def test_a_deeply_nested_body_is_a_400_not_a_dropped_connection(channel):
    body = '{"method": "test.echo2", "params": ' + "[" * 100_000 + "]" * 100_000 + "}"
    status, _, _ = _request(
        channel, "POST", "/rpc",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        body=body,
    )
    assert status == 400
    assert _request(channel, "GET", "/health")[0] == 200


def test_the_envelope_names_the_field_a_refusal_is_about(channel):
    _, _, body = _rpc(channel, {"method": "test.field"})
    assert json.loads(body)["error"] == {
        "code": "bad_params", "message": "no good", "field": "path"}


def test_an_unexpected_failure_does_not_put_its_text_on_the_screen(channel):
    _, _, body = _rpc(channel, {"method": "test.leaky"})
    error = json.loads(body)["error"]
    assert error["code"] == "internal"
    assert "secret detail" not in error["message"]
    assert "/Users/" not in error["message"]
    assert "ValueError" in error["message"]


# ---- a trickle of bytes (QA-SEC-R1) -------------------------------------------


def _trickle(port, interval, stop, held):
    """One connection that starts a request and never finishes it."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=3)
    sock.sendall(b"POST /rpc HTTP/1.1\r\nHost: 127.0.0.1\r\nX-a: ")
    held.append(sock)

    def drip():
        while not stop.is_set():
            try:
                sock.sendall(b"x")
            except OSError:
                return
            stop.wait(interval)

    t = threading.Thread(target=drip, daemon=True)
    t.start()
    return sock


def test_a_request_that_is_still_arriving_after_the_deadline_is_cut(monkeypatch):
    monkeypatch.setattr(httpd, "_REQUEST_DEADLINE_S", 0.6)
    monkeypatch.setattr(httpd, "_REAP_EVERY_S", 0.1)
    ch = _channel()
    stop = threading.Event()
    held = []
    try:
        # Every byte arrives well inside the per-read timeout.
        sock = _trickle(ch.port, 0.1, stop, held)
        started = time.monotonic()
        sock.settimeout(4)
        data = b"x"
        try:
            while data:
                data = sock.recv(1)
        except OSError:
            pass
        assert time.monotonic() - started < 3
    finally:
        stop.set()
        for sock in held:
            sock.close()
        ch.stop()


def test_a_slow_request_does_not_take_the_slot_of_the_next_caller(monkeypatch):
    monkeypatch.setattr(httpd, "_REQUEST_DEADLINE_S", 60.0)
    ch = _channel(monkeypatch, _MAX_CONNECTIONS=6)
    stop = threading.Event()
    held = []
    try:
        for _ in range(6):
            _trickle(ch.port, 0.2, stop, held)
        time.sleep(0.3)
        assert _rpc(ch, {"method": "test.echo2", "params": {"a": 1}})[0] == 200
        assert _request(ch, "GET", "/health")[0] == 200
    finally:
        stop.set()
        for sock in held:
            sock.close()
        ch.stop()


@_WINDOWS_SHEDDING
def test_110_trickling_connections_do_not_take_the_channel_down():
    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(max(soft, 2048), hard), hard))
    except (ImportError, ValueError, OSError):  # pragma: no cover - Windows
        pass
    ch = _channel()
    stop = threading.Event()
    held = []
    try:
        for _ in range(110):
            _trickle(ch.port, 1.0, stop, held)
        failures = 0
        for _ in range(8):
            try:
                if _request(ch, "GET", "/health")[0] != 200:
                    failures += 1
            except OSError:
                failures += 1
            time.sleep(0.4)
        assert failures == 0
        assert _rpc(ch, {"method": "test.echo2"})[0] == 200
    finally:
        stop.set()
        for sock in held:
            sock.close()
        ch.stop()
