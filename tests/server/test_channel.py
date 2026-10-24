"""The runtime's wire layer: registry, event bus and the loopback channel.

No domain stack is built here. The channel is driven with a stand-in
runtime, which is what makes the security properties testable: the token,
the Host check, the size limit, and a handler's failure staying a response
instead of a dead server.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from app.server import rpc
from app.server.events import EventBus
from app.server.httpd import Channel

TOKEN = "t" * 32


class _Runtime:
    pass


@pytest.fixture(scope="module", autouse=True)
def _handlers():
    # A module-level fixture: methods are registered once per process, and
    # registering twice is deliberately an error.
    @rpc.method("test.echo")
    def echo(rt, params):
        return {"echo": params}

    @rpc.method("test.fail")
    def fail(rt, params):
        raise rpc.RpcError("nope", "refused on purpose")

    @rpc.method("test.crash")
    def crash(rt, params):
        raise ZeroDivisionError("boom")

    rpc.load_handlers()
    yield


@pytest.fixture()
def channel():
    ch = Channel(_Runtime(), TOKEN)
    ch.start()
    yield ch
    ch.stop()


def _post(channel, body, token=TOKEN, host=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if host:
        headers["Host"] = host
    request = urllib.request.Request(
        f"http://127.0.0.1:{channel.port}/rpc",
        data=json.dumps(body).encode(),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def test_a_call_returns_its_result(channel):
    status, body = _post(channel, {"method": "test.echo", "params": {"a": 1}})

    assert status == 200
    assert body == {"result": {"echo": {"a": 1}}}


def test_a_wrong_or_missing_token_is_refused_before_any_handler_runs(channel):
    assert _post(channel, {"method": "test.echo"}, token="x" * 32)[0] == 401
    assert _post(channel, {"method": "test.echo"}, token=None)[0] == 401


def test_a_foreign_host_header_is_refused(channel):
    """DNS rebinding: a page on a name the attacker owns, resolving to
    127.0.0.1, must not be able to reach the socket."""
    status, _ = _post(channel, {"method": "test.echo"}, host="evil.example")

    assert status == 403


def test_an_rpc_error_keeps_its_code(channel):
    _, body = _post(channel, {"method": "test.fail"})

    assert body["error"] == {"code": "nope", "message": "refused on purpose"}


def test_a_handler_crash_is_a_response_and_the_server_survives(channel):
    _, body = _post(channel, {"method": "test.crash"})
    assert body["error"]["code"] == "internal"

    assert _post(channel, {"method": "test.echo"})[0] == 200


def test_an_unknown_method_and_a_malformed_request(channel):
    assert _post(channel, {"method": "no.such"})[1]["error"]["code"] == "unknown_method"
    assert _post(channel, {"nothing": True})[0] == 400
    assert _post(channel, {"method": "test.echo", "params": [1]})[1]["error"]["code"] == "bad_params"


def test_the_event_stream_replays_sticky_events_to_a_new_subscriber(channel):
    from app.server.events import bus

    bus.add_sticky("test.sticky")
    bus.emit("test.sticky", {"n": 7})

    request = urllib.request.Request(
        f"http://127.0.0.1:{channel.port}/events?token={TOKEN}"
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        seen = []
        while len(seen) < 4:
            line = response.readline().decode()
            seen.append(line)
            if line.startswith("data: ") and "7" in line:
                break

    assert "event: test.sticky\n" in seen
    assert any(line.strip() == 'data: {"n": 7}' for line in seen)


def test_the_event_stream_needs_the_token(channel):
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(f"http://127.0.0.1:{channel.port}/events", timeout=5)

    assert err.value.code == 401


# ---- registry and bus -------------------------------------------------------


def test_registering_a_method_twice_is_an_error():
    with pytest.raises(RuntimeError):
        rpc.method("test.echo")(lambda rt, p: None)


def test_every_registered_method_is_namespaced():
    names = rpc.method_names()

    assert names, "no handlers were loaded"
    assert all("." in name for name in names), names


def test_the_bus_drops_the_oldest_event_for_a_reader_that_stopped_reading():
    bus = EventBus()
    sub = bus.subscribe()

    for n in range(2000):
        bus.emit("tick", {"n": n})

    first = sub.get(0.1)
    assert first is not None and json.loads(first[1])["n"] > 0
    sub.close()
    assert bus.subscribers == 0


def test_emit_is_safe_from_many_threads():
    bus = EventBus()
    sub = bus.subscribe()
    threads = [
        threading.Thread(target=lambda: [bus.emit("x", {}) for _ in range(100)])
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sub.get(0.1) is not None
