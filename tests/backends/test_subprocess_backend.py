"""Tests for SubprocessBackend — the IPC wrapper that hosts the
inference pipeline in a worker process.

The point of running ONNX inference in a worker process: when
``onnx_asr.load_model`` calls ``LoadLibrary`` for ORT op kernels
(Conv / MatMul / cuDNN / cuBLAS / …), it acquires the Win32 DLL
loader-lock.  In a single-process app that lock blocks every other
thread including the Qt main-thread message pump → window can't be
moved, scroll doesn't work, "(Not responding)".  Pushing the model
into a separate process means the loader-lock contention stays
inside that process; our Qt process is unaffected.

These tests don't spawn a real Python subprocess (slow + flaky in
CI).  They drive ``_worker_main`` synchronously through an
in-memory ``multiprocessing.Pipe`` and a real-thread reader, which
exercises the full command/response/progress flow.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from unittest.mock import MagicMock

import numpy as np
import pytest


# ---- _worker_main: command dispatch (in-process) ---------------------------


def _drive_worker(commands, *, init_kwargs=None):
    """Spin up ``_worker_main`` on a thread (NOT a subprocess) so we
    can exercise the dispatch logic without paying the spawn cost.

    Returns the parent-side ``Connection``, the worker thread handle,
    and a ``run_all()`` helper that ships every command + drains the
    matching responses.

    Streamed-command approach (vs. pre-load everything into the pipe
    buffer): Windows ``Pipe`` has a 64 KB buffer; large numpy audio
    arrays would deadlock if we tried to enqueue all commands before
    the worker drained the first batch.
    """
    from app.backends.subprocess_worker import _worker_main

    parent_conn, child_conn = multiprocessing.Pipe(duplex=True)

    t = threading.Thread(target=_worker_main, args=(child_conn,), daemon=True)
    t.start()

    if init_kwargs is not None:
        parent_conn.send(("init", init_kwargs))

    def run_all(timeout: float = 5.0):
        """Send every command, drain responses, return the list of
        non-progress responses (init included if present)."""
        out = []
        # Drain init ack first if it was sent.
        if init_kwargs is not None:
            out.append(_recv_response(parent_conn, timeout))
        for cmd in commands:
            parent_conn.send(cmd)
            if cmd[0] == "shutdown_worker":
                # Fire-and-forget, exactly as the parent treats it: it
                # joins the process rather than waiting for an ack, so
                # there is nothing on the wire to read back.
                continue
            out.append(_recv_response(parent_conn, timeout))
        return out

    return parent_conn, t, run_all


def _recv_response(conn, timeout):
    """Read one command response from ``conn``, skipping out-of-band
    messages (``progress`` from tqdm, ``log`` from the worker's log
    forwarder, ``status_change`` from the status broadcaster)."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = max(0.01, deadline - time.monotonic())
        if not conn.poll(timeout=remaining):
            raise TimeoutError(
                f"no response within {timeout}s"
            )
        msg = conn.recv()
        if msg and msg[0] in ("progress", "log", "status_change"):
            continue
        return msg


def _drain_responses(conn, count, *, timeout=5.0):
    """Pull ``count`` non-progress messages off the pipe (legacy helper
    kept for tests that pre-load all commands before driving — only
    safe for small payloads that fit in the pipe buffer)."""
    out = []
    for _ in range(count):
        out.append(_recv_response(conn, timeout))
    return out


def test_worker_init_creates_registry_backend(monkeypatch):
    """``init`` command must build a RegistryBackend with the kwargs
    forwarded from the parent — that's the whole "reuse existing
    chain in the worker" trick."""
    captured: dict = {}

    class _FakeBackend:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def status(self):
            return "stopped"

    import app.backends.subprocess_worker as worker_mod

    monkeypatch.setattr(worker_mod, "_RegistryBackend", _FakeBackend)

    parent, t, run_all = _drive_worker(
        [("shutdown_worker",)],
        init_kwargs={"model": "whisper-large-v3-turbo", "device": "auto"},
    )
    try:
        responses = run_all()
    finally:
        parent.close()
        t.join(timeout=2)

    assert responses[0] == ("ok", None)  # init ack
    assert captured["kwargs"] == {
        "model": "whisper-large-v3-turbo", "device": "auto",
    }


def test_worker_status_load_transcribe_dispatch(monkeypatch):
    """Standard read-side commands forward to the backend."""
    fake = MagicMock()
    fake.status.return_value = "ready"
    fake.health_check.return_value = True
    fake.current_model.return_value = "x/y"
    fake.current_language.return_value = "ru"
    fake.transcribe.return_value = "hello"

    import app.backends.subprocess_worker as worker_mod

    monkeypatch.setattr(
        worker_mod, "_RegistryBackend", lambda **_kw: fake,
    )

    # 1 second of mono float32 (4 KB) — comfortably fits the pipe
    # buffer with the streamed-command driver.
    audio = np.zeros(1000, dtype=np.float32)
    parent, t, run_all = _drive_worker(
        [
            ("status",),
            ("health_check",),
            ("current_model",),
            ("current_language",),
            ("load",),
            ("transcribe", audio, 16000),
            ("shutdown_worker",),
        ],
        init_kwargs={"model": "x"},
    )
    try:
        responses = run_all()
    finally:
        parent.close()
        t.join(timeout=2)

    # init ack + 7 commands
    assert responses[0] == ("ok", None)
    assert responses[1] == ("ok", "ready")
    assert responses[2] == ("ok", True)
    assert responses[3] == ("ok", "x/y")
    assert responses[4] == ("ok", "ru")
    assert responses[5] == ("ok", None)
    assert responses[6] == ("ok", "hello")
    fake.transcribe.assert_called_once()
    # Numpy array round-trips through pickle — verify shape preserved.
    audio_arg = fake.transcribe.call_args.args[0]
    assert audio_arg.shape == (1000,)


def test_worker_change_model_dispatch(monkeypatch):
    fake = MagicMock()

    import app.backends.subprocess_worker as worker_mod

    monkeypatch.setattr(
        worker_mod, "_RegistryBackend", lambda **_kw: fake,
    )

    parent, t, run_all = _drive_worker(
        [
            ("change_model", "new/model", "int8"),
            ("shutdown_worker",),
        ],
        init_kwargs={"model": "old/model"},
    )
    try:
        run_all()
    finally:
        parent.close()
        t.join(timeout=2)

    fake.change_model.assert_called_once_with(
        "new/model", compute_type="int8",
    )


def test_worker_uninitialised_returns_error(monkeypatch):
    """Sanity: commands sent before ``init`` get back an error tuple
    rather than crashing the worker — defensive against pipe protocol
    misuse."""
    parent, t, run_all = _drive_worker(
        [("status",), ("shutdown_worker",)],
    )
    try:
        responses = run_all()
    finally:
        parent.close()
        t.join(timeout=2)

    assert responses[0][0] == "error"
    assert "not initialised" in responses[0][1].lower()


def test_worker_command_exception_returns_error(monkeypatch):
    """Backend method raising must surface as an ``("error", str)``
    tuple, not bring the worker down."""
    fake = MagicMock()
    fake.status.side_effect = RuntimeError("simulated crash")

    import app.backends.subprocess_worker as worker_mod

    monkeypatch.setattr(
        worker_mod, "_RegistryBackend", lambda **_kw: fake,
    )

    parent, t, run_all = _drive_worker(
        [("status",), ("shutdown_worker",)],
        init_kwargs={"model": "x"},
    )
    try:
        responses = run_all()
    finally:
        parent.close()
        t.join(timeout=2)

    assert responses[0] == ("ok", None)  # init
    kind, payload = responses[1]
    assert kind == "error"
    assert "simulated crash" in payload


def test_worker_progress_callback_forwards_to_pipe(monkeypatch):
    """``set_progress_callback`` is called once at worker start with
    a function that pushes ``("progress", current, total, desc)``
    over the pipe.  When tqdm fires, the parent must see the event
    in the pipe stream."""
    captured_cb = []

    fake_set_cb = MagicMock(side_effect=lambda cb: captured_cb.append(cb))

    import app.backends.subprocess_worker as worker_mod

    monkeypatch.setattr(worker_mod, "_set_progress_callback", fake_set_cb)
    monkeypatch.setattr(
        worker_mod, "_RegistryBackend", lambda **_kw: MagicMock(),
    )

    parent, t, _run_all = _drive_worker(
        [],
        init_kwargs={"model": "x"},
    )
    try:
        # Drain init ack — registering the progress callback happens
        # at worker startup, before any command is processed, so the
        # init response is enough to know it's wired.
        ack = _recv_response(parent, 5.0)
        assert ack == ("ok", None)
        assert captured_cb, "worker did not call set_progress_callback"

        # Now invoke the worker's progress callback from the test
        # (simulating tqdm) and confirm it lands on the parent pipe.
        cb = captured_cb[0]
        cb(50, 100, "model.bin")

        assert parent.poll(timeout=2.0)
        msg = parent.recv()
        assert msg[0] == "progress"
        assert msg[1] == 50
        assert msg[2] == 100
        assert msg[3] == "model.bin"

        # Cleanly shut down the worker. ``shutdown_worker`` is
        # fire-and-forget — the parent joins the process rather than
        # waiting for an ack — so assert on the exit, not on a reply.
        parent.send(("shutdown_worker",))
        t.join(timeout=5)
        assert not t.is_alive(), "воркер не завершился после shutdown_worker"
    finally:
        parent.close()
        t.join(timeout=2)


# ---- SubprocessBackend client (mocked process) -----------------------------


class _FakeProcess:
    """Stand-in for ``multiprocessing.Process`` so tests don't fork."""

    def __init__(self, *_a, **_kw):
        self._alive = True

    def start(self):
        pass

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        self._alive = False

    def terminate(self):
        self._alive = False


class _ScriptedConn:
    """Bidirectional pipe stub.  Test scripts an ordered list of
    responses and provides a callback to invoke when ``send`` is
    called — keeps the test deterministic without race conditions."""

    def __init__(self, on_send):
        self._on_send = on_send
        self._lock = threading.Lock()
        self._inbox: list = []
        self._scripted: list = []
        self._auto_ack = True
        self._cond = threading.Condition(self._lock)
        self._closed = False

    # parent side
    def send(self, payload):
        self._on_send(payload, self)

    def recv(self):
        with self._cond:
            while not self._inbox and not self._closed:
                self._cond.wait()
            if self._closed and not self._inbox:
                raise EOFError()
            return self._inbox.pop(0)

    def close(self):
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    # test side: enqueue an unsolicited worker push (``status_change``,
    # ``progress``, …). These are NOT command replies — the reader
    # dispatches them on their tag alone — so they go out untagged.
    def push(self, msg):
        with self._cond:
            self._inbox.append(msg)
            self._cond.notify_all()

    # test side: arm the reply for the NEXT command. The real worker
    # echoes the sequence number the parent allocated, and the test has
    # no way to know it in advance, so ``on_send`` does the tagging.
    # Use this instead of ``push`` for anything that answers a command —
    # a bare ("ok", …) pushed straight to the inbox is read as a
    # malformed reply and its caller times out.
    def script_next(self, kind, payload):
        with self._cond:
            self._scripted.append((kind, payload))

    def take_scripted(self):
        with self._cond:
            if not self._scripted:
                return None
            return self._scripted.pop(0)

    # test side: stop answering commands automatically. Used by the tests
    # that need a command to stay parked in ``get()`` — with the default
    # ack on, every command returns instantly and there is nothing to
    # block behind.
    def silence(self):
        with self._cond:
            self._auto_ack = False


@pytest.fixture
def patched_subprocess(monkeypatch):
    """Wire SubprocessBackend so it doesn't actually spawn a process —
    each ``send`` invokes the test-supplied callback, which decides
    what to push onto the recv side.
    """
    import app.backends.subprocess_backend as mod

    sent: list = []

    def on_send(payload, conn):
        sent.append(payload)
        # ``init`` is sent untagged at construction and acked with a bare
        # ("ok", None) — the reader recognises it as the init ack because
        # it is the first reply and no sequence number has been handed
        # out yet.
        if payload[0] == "init":
            conn.push(("ok", None))
            return
        # Every other command carries its sequence number and gets a
        # reply tagged with it. A test can override what comes back by
        # arming ``script_next``; the default is a plain ack, which is
        # why most tests need to do nothing at all.
        if payload[0] == "cmd":
            _, seq = payload[0], payload[1]
            scripted = conn.take_scripted()
            if scripted is None:
                if not conn._auto_ack:
                    return
                kind, value = "ok", None
            else:
                kind, value = scripted
            conn.push(("resp", seq, kind, value))

    conn_holder = {}

    def fake_pipe(duplex=True):
        c = _ScriptedConn(on_send)
        conn_holder["conn"] = c
        return c, c  # parent and child are the same object — tests
                     # write to ``conn``, both sides see it

    # Production code switched from ``multiprocessing.Pipe()`` /
    # ``multiprocessing.Process()`` to ``ctx = multiprocessing.get_context("spawn")``
    # + ``ctx.Pipe()`` / ``ctx.Process()`` in the macOS-bundle fix
    # (commit d05d275).  The context object isn't the same as the
    # ``multiprocessing`` module — patches on the module never reach
    # the context's bound methods — so we have to intercept
    # ``get_context`` itself and return a fake whose ``Pipe`` /
    # ``Process`` we control.  Patches on the module stay too as a
    # safety net for any future code path that goes through the
    # bare module API directly.
    class _FakeCtx:
        Pipe = staticmethod(fake_pipe)
        Process = _FakeProcess

    monkeypatch.setattr(mod.multiprocessing, "Pipe", fake_pipe)
    monkeypatch.setattr(mod.multiprocessing, "Process", _FakeProcess)
    monkeypatch.setattr(
        mod.multiprocessing, "get_context", lambda _method=None: _FakeCtx
    )

    return {"sent": sent, "conn_holder": conn_holder}


def test_subprocess_backend_init_sends_init(patched_subprocess):
    from app.backends.subprocess_backend import SubprocessBackend

    SubprocessBackend(model="whisper-large-v3-turbo", device="auto")

    sent = patched_subprocess["sent"]
    assert sent[0][0] == "init"
    kwargs = sent[0][1]
    assert kwargs["model"] == "whisper-large-v3-turbo"
    assert kwargs["device"] == "auto"


def test_subprocess_backend_status_served_from_cache(patched_subprocess):
    """``status()`` no longer round-trips through the pipe — it reads
    a local cache populated by ``status_change`` push messages from
    the worker.  RecordingController polls status() every 200 ms; an
    IPC round-trip per poll contended with the worker's tqdm + log
    forwarding stream and stuttered the UI during a model load.

    Verifies:
    1. Initial status is ``"stopped"`` even before the worker sends
       anything (sane default — UI shows the right pill on boot).
    2. After a ``("status_change", "loading")`` arrives on the pipe,
       the next ``status()`` returns ``"loading"`` without any new
       command being sent.
    """
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x")
    conn = patched_subprocess["conn_holder"]["conn"]
    sent_before = list(patched_subprocess["sent"])

    # Default cache before any push.
    assert backend.status() == "stopped"

    # Worker pushes a status change.
    conn.push(("status_change", "loading"))

    # Reader thread is async — give it a moment.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if backend.status() == "loading":
            break
        time.sleep(0.01)

    assert backend.status() == "loading"
    # No new pipe send for the status() call itself — only the
    # init that fired in __init__.
    assert patched_subprocess["sent"] == sent_before

    backend.shutdown()


def test_subprocess_backend_health_check_served_from_cache(patched_subprocess):
    """``health_check()`` is just ``status() == "ready"`` and shares
    the same cache fast-path.  No IPC."""
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x")
    conn = patched_subprocess["conn_holder"]["conn"]

    # No "ready" yet — health_check should be False.
    assert backend.health_check() is False

    conn.push(("status_change", "ready"))

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if backend.health_check():
            break
        time.sleep(0.01)

    assert backend.health_check() is True
    backend.shutdown()


def test_subprocess_backend_progress_routes_to_callback(patched_subprocess):
    """When the worker pushes a ``("progress", ...)`` message onto the
    pipe, the registered callback must fire on the parent side."""
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x")
    conn = patched_subprocess["conn_holder"]["conn"]

    received: list = []
    backend.set_progress_callback(
        lambda c, t, d: received.append((c, t, d))
    )

    conn.push(("progress", 100, 1000, "weights.onnx"))

    # Reader thread is async; give it a moment.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not received:
        time.sleep(0.01)

    assert received == [(100, 1000, "weights.onnx")]
    backend.shutdown()


def test_subprocess_backend_error_response_raises(patched_subprocess):
    """An ``("error", "msg")`` from worker must surface as a
    RuntimeError on the calling thread — otherwise the parent is
    silently broken.

    Uses ``current_language()`` rather than ``status()`` because
    ``status()`` and ``current_model()`` are now served from local
    caches (no IPC) and can't surface a worker-side error.
    """
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x")
    conn = patched_subprocess["conn_holder"]["conn"]

    conn.script_next("error", "RuntimeError: boom")
    with pytest.raises(RuntimeError, match="boom"):
        backend.current_language()


def test_subprocess_backend_change_model_sync(patched_subprocess):
    """change_model forwards args correctly through the pipe."""
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x")
    conn = patched_subprocess["conn_holder"]["conn"]
    conn.script_next("ok", None)

    backend.change_model("new/model", compute_type="int8")

    assert ("cmd", 1, "change_model", "new/model", "int8") in patched_subprocess["sent"]


def test_subprocess_backend_shutdown_terminates_process(patched_subprocess):
    """shutdown sends ``shutdown_worker`` and joins the process.
    Idempotent — calling twice doesn't blow up."""
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x")
    conn = patched_subprocess["conn_holder"]["conn"]
    conn.script_next("ok", None)

    backend.shutdown()
    # Second call must not raise (process already dead).
    backend.shutdown()


# ---- worker readiness: the signal the frozen-macOS backend choice rests on

from app.backends.subprocess_backend import SubprocessBackend  # noqa: E402


def test_wait_for_worker_is_true_once_the_worker_acks(patched_subprocess):
    """``main()`` picks a backend off this, so a healthy worker has to
    read as success without the caller sending anything first."""
    backend = SubprocessBackend(model="x")

    assert backend.wait_for_worker(timeout=2.0) is True


def test_wait_for_worker_is_false_when_the_worker_never_acks(
    patched_subprocess,
):
    """Silence is not success: the reader thread leaves the event unset
    when the child dies before saying anything."""
    backend = SubprocessBackend(model="x")
    # Let the scripted ack land first — clearing before the reader has
    # run would race it and the reader would set the event again.
    assert backend.wait_for_worker(timeout=2.0) is True
    backend._init_event.clear()

    assert backend.wait_for_worker(timeout=0.2) is False


def test_wait_for_worker_is_false_when_init_reported_an_error(
    patched_subprocess,
):
    """The trap this guards: the reader thread sets the same event on EOF
    as on a clean ack, so a worker that died before sending anything
    would otherwise read as a live backend — and the caller would ship
    a dictation app with no engine."""
    backend = SubprocessBackend(model="x")
    backend._init_error = "Worker pipe closed before init"

    assert backend.wait_for_worker(timeout=0.2) is False


# ---- the bundle spawn environment ------------------------------------------


def test_child_spawn_env_is_a_no_op_outside_a_frozen_bundle():
    """Dev and Windows must be untouched: no env is rewritten, and
    ``sys.frozen`` is not cleared, because nothing about them needs it."""
    import os

    import app.backends.subprocess_backend as mod

    before = dict(os.environ)
    with mod._child_spawn_env():
        assert dict(os.environ) == before
    assert dict(os.environ) == before


def test_child_spawn_env_gives_a_zipped_stdlib_bundle_a_working_python(
    monkeypatch, tmp_path,
):
    """A self-contained bundle ships the stdlib as
    ``Resources/lib/python312.zip``; the spawn child gets no
    ``__boot__.py`` to sort out its own ``sys.path``, so it is handed
    ``PYTHONHOME`` / ``PYTHONPATH`` — and only for the spawn.

    ``sys.platform`` is forced to ``darwin`` because the repair is scoped
    to py2app: everything ``_child_spawn_env`` undoes is damage a ``.app``
    bundle does, and PyInstaller's Windows target has its own protocol.
    Without the forcing this test passed on macOS and raised ``KeyError``
    on the two legs where the code is deliberately a no-op — which is the
    same "passes only in company" shape as the history-view segfault.
    """
    import os
    import sys

    import app.backends.subprocess_backend as mod

    resources = tmp_path / "Contents" / "Resources"
    lib = resources / "lib"
    lib.mkdir(parents=True)
    (lib / "python312.zip").write_bytes(b"")
    exe = tmp_path / "Contents" / "MacOS" / "exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))

    with mod._child_spawn_env():
        assert os.environ["PYTHONHOME"] == str(resources)
        assert str(lib / "python312.zip") in os.environ["PYTHONPATH"]
        assert str(lib / "python3.12") in os.environ["PYTHONPATH"]
        # The frozen-executable protocol has to be off, or the child is
        # launched with `--multiprocessing-fork`, which CPython rejects
        # with "unknown option" and exits 2.
        assert getattr(sys, "frozen", False) is False

    assert "PYTHONHOME" not in os.environ
    assert "PYTHONPATH" not in os.environ
    assert getattr(sys, "frozen", False) is True


def test_child_spawn_env_does_not_feed_an_alias_build_a_broken_home(
    monkeypatch, tmp_path,
):
    """An alias build has no zipped stdlib — its child already resolves
    the venv. Pointing ``PYTHONHOME`` at ``Resources`` there breaks the
    child's stdlib and the worker dies with "Worker pipe closed before
    init"; measured, so it gets a test.

    Runs the bundle shape on every platform (see the sibling test) —
    otherwise the "no-op" half of this would be satisfied by the test
    never entering the bundle branch at all.
    """
    import os
    import sys

    import app.backends.subprocess_backend as mod

    resources = tmp_path / "Contents" / "Resources"
    (resources / "lib").mkdir(parents=True)
    exe = tmp_path / "Contents" / "MacOS" / "exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))

    with mod._child_spawn_env():
        assert "PYTHONHOME" not in os.environ


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_child_spawn_env_leaves_a_frozen_bundle_on_another_platform_alone(
    monkeypatch, tmp_path, platform,
):
    """The bundle repair is py2app's damage, so it must not touch a
    frozen Windows build.

    This is why the two tests above force ``sys.platform``: without this
    gate being pinned here, dropping the ``darwin`` half of the
    condition would quietly start rewriting ``PYTHONHOME`` for a
    PyInstaller bundle, where the child has its own runtime layout.
    """
    import os
    import sys

    import app.backends.subprocess_backend as mod

    resources = tmp_path / "Contents" / "Resources"
    lib = resources / "lib"
    lib.mkdir(parents=True)
    (lib / "python312.zip").write_bytes(b"")
    exe = tmp_path / "Contents" / "MacOS" / "exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))

    with mod._child_spawn_env():
        assert "PYTHONHOME" not in os.environ
        assert "PYTHONPATH" not in os.environ
        assert getattr(sys, "frozen", False) is True, (
            "sys.frozen is only cleared for a py2app bundle"
        )


# ---- protocol correlation: the three things a bare FIFO queue cannot do


def test_a_reply_to_an_abandoned_command_is_dropped_not_handed_on(
    patched_subprocess,
):
    """The stale-reply bug, pinned.

    Responses used to share one FIFO queue matched by arrival order. A
    command that timed out simply raised, leaving its eventual reply on
    the queue — where the *next* command, for a different caller asking
    something else entirely, popped it and returned it as its own
    payload. A ten-minute file that overran the transcribe cap was enough
    to make ``cancel_load`` answer with the previous transcript.

    Sequence numbers make a reply undeliverable instead: the waiter
    retires its sequence when it gives up, so the late reply has nowhere
    to go.
    """
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x")
    conn = patched_subprocess["conn_holder"]["conn"]

    conn.silence()
    # Command 1: nobody replies, so it gives up.
    with pytest.raises(RuntimeError, match="timed out"):
        backend._send_cmd(("current_language",), timeout=0.05)

    seq_of_abandoned = patched_subprocess["sent"][-1][1]
    assert seq_of_abandoned == 1

    # The worker finishes late and answers. Nobody should receive it.
    conn.push(("resp", seq_of_abandoned, "ok", "stale-transcript"))

    # Command 2 asks something different and must get its own answer.
    conn.script_next("ok", "ru")
    assert backend._send_cmd(("current_language",), timeout=2.0) == "ru"


def test_a_late_reply_does_not_satisfy_the_next_command(
    patched_subprocess,
):
    """The orphan must not land on a command that is already waiting.

    This is the overlapping case, and the one that actually bites: the
    first caller has given up, a *second* caller is already parked, and
    only then does the worker's late reply for the first arrive. A reader
    that "helpfully" hands an unanswered reply to whoever is waiting turns
    a timed-out transcription into the wrong answer to an unrelated
    question.

    (The non-overlapping ordering — orphan arrives while nobody is
    waiting — is covered by the test above.)
    """
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x")
    conn = patched_subprocess["conn_holder"]["conn"]
    conn.silence()

    with pytest.raises(RuntimeError, match="timed out"):
        backend._send_cmd(("transcribe", "audio"), timeout=0.05)

    # A second caller is now parked, waiting for its own answer. No
    # scripted reply for it — it must genuinely still be waiting when
    # the orphan lands, or there is nothing for the orphan to spoil.
    received: list = []

    def second_caller():
        try:
            received.append(
                backend._send_cmd(("current_language",), timeout=5.0)
            )
        except Exception as exc:  # pragma: no cover — diagnostic only
            received.append(exc)

    second = threading.Thread(target=second_caller, daemon=True)
    second.start()
    time.sleep(0.2)  # let it register its waiter

    with backend._send_lock:
        assert 2 in backend._waiters, "второй вызывающий не зарегистрирован"

    # The orphan for command 1 lands while command 2 is waiting.
    conn.push(("resp", 1, "ok", "orphan"))
    time.sleep(0.25)

    assert not received, (
        f"второй вызывающий получил ответ сиротской команды: {received!r}"
    )

    # Its own answer still arrives normally — the orphan cost nothing.
    conn.push(("resp", 2, "ok", "the-real-answer"))
    second.join(timeout=5)
    assert received == ["the-real-answer"]


def test_worker_death_unblocks_every_waiter_not_just_one(
    patched_subprocess,
):
    """A dead worker must wake *all* of them.

    EOF used to put exactly one sentinel on the one shared queue, so
    every other parked caller sat out its full timeout — up to the
    transcribe cap — and then reported "timed out" for a worker that had
    already died. The sentinel itself also stayed behind as an entry the
    next command would pop as its own result.
    """
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x")
    conn = patched_subprocess["conn_holder"]["conn"]

    conn.silence()
    results = []
    started = threading.Barrier(3)

    def waiter():
        started.wait(timeout=5)
        try:
            backend._send_cmd(("current_language",), timeout=30.0)
            results.append(("ok", None))
        except Exception as exc:
            results.append(("err", str(exc)))

    threads = [threading.Thread(target=waiter) for _ in range(2)]
    for t in threads:
        t.start()
    started.wait(timeout=5)
    time.sleep(0.15)  # let both register their waiters

    conn.close()  # simulate the worker process dying

    for t in threads:
        t.join(timeout=5)

    assert len(results) == 2, "не все ожидающие получили ответ"
    assert all(kind == "err" for kind, _ in results), results
    assert all("speech engine stopped" in msg for _, msg in results), results


def test_the_send_lock_is_not_held_while_waiting_for_a_reply(
    patched_subprocess,
):
    """A long command must not lock every other caller out of *sending*.

    ``_send_lock`` used to wrap the blocking ``queue.get`` as well as the
    pipe write, so a file transcription — up to its ten-minute cap —
    stopped the Qt thread from even issuing Cancel. Only the write
    itself needs serialising; a Connection is not safe against concurrent
    senders, but nothing about waiting for a reply is.
    """
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x")
    conn = patched_subprocess["conn_holder"]["conn"]

    conn.silence()
    slow = threading.Thread(
        target=lambda: _swallow(backend._send_cmd, ("transcribe", "a")),
        daemon=True,
    )
    slow.start()
    time.sleep(0.15)  # the slow command is now parked in get()

    # The send lock must be free. Acquiring it here is what a second
    # caller would have to do before it could even write its command.
    acquired = backend._send_lock.acquire(timeout=1.0)
    assert acquired, (
        "_send_lock удерживается во время ожидания ответа — второй "
        "вызывающий не может даже отправить команду"
    )
    backend._send_lock.release()

    # And a second command really does complete while the first is stuck.
    conn.script_next("ok", "second-wins")
    assert backend._send_cmd(("current_language",), timeout=2.0) == "second-wins"


def _swallow(fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except Exception:
        pass


def test_a_retry_that_fails_inside_one_poll_still_reports_the_failure(monkeypatch):
    """QA-JOURNEYS-R3: a load started after a failed one never finished.

    The worker's broadcaster compared against its own previous poll. After
    the first failure it remembered ``error``; the retry's ``loading`` went
    out with the command, the retry failed within one poll interval, and the
    broadcaster saw ``error`` again - "unchanged", nothing pushed. The parent
    had been told ``loading`` last and waited for a load that was over.
    """
    import app.backends.subprocess_worker as worker_mod

    class _Failing:
        """The retry's ``loading`` is visible only to the command's own push
        and the retry is over before the broadcaster polls again - the
        shape of a load that fails at once (offline, missing weights)."""

        def __init__(self, **_kw):
            self.state = "error"
            self.retrying = False

        def status(self):
            if self.retrying and threading.current_thread().name != "status-broadcaster":
                self.retrying = False
                self.state = "error"
                return "loading"
            return self.state

        def active_provider(self):
            return None

        def change_model(self, model, compute_type=None):
            self.retrying = True

        def shutdown(self):
            pass

    monkeypatch.setattr(worker_mod, "_RegistryBackend", _Failing)
    parent, t, _ = _drive_worker([], init_kwargs={"model": "x"})
    try:
        # Let the broadcaster record the first failure.
        statuses = []

        def drain(seconds):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                if parent.poll(0.05):
                    msg = parent.recv()
                    if msg and msg[0] == "status_change":
                        statuses.append(msg[1])

        drain(0.5)
        assert statuses and statuses[-1] == "error"
        parent.send(("cmd", 1, "change_model", "other", None))
        drain(0.8)
        assert statuses[-1] == "error", statuses
    finally:
        parent.send(("shutdown_worker",))
        parent.close()
        t.join(timeout=2)


def test_cancel_load_does_not_leave_the_cache_on_loading(patched_subprocess):
    """QA-RUNTIME-F1: the worker's "stopped" push arrives later; until then a
    cache that still says "loading" made the restore of the previous model
    read as "already loading" and be refused."""
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x", device="cpu")
    backend._status_cache = "loading"
    backend._send_cmd = lambda *a, **k: None
    backend.cancel_load()
    assert backend.status() == "stopped"


# ---- a dead worker is detected and replaced (QA-RUNTIME-F2) ---------------------


def _wait_for(predicate, timeout=3.0):
    import time as _t

    end = _t.monotonic() + timeout
    while _t.monotonic() < end:
        if predicate():
            return True
        _t.sleep(0.02)
    return predicate()


def _kill_worker(patched_subprocess, backend):
    """What ``kill -9`` does: the process is gone and the pipe reaches EOF."""
    conn = patched_subprocess["conn_holder"]["conn"]
    backend._proc._alive = False
    conn.close()
    return conn


def test_a_dead_worker_is_reported_as_error_and_replaced(patched_subprocess):
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="vosk-ru-small", device="cpu")
    assert backend.wait_for_worker(2)
    events = []
    backend.set_worker_event_callback(events.append)
    backend._status_cache = "ready"
    first_conn = _kill_worker(patched_subprocess, backend)

    assert _wait_for(lambda: "died" in events), events
    # A new worker came up and the model that was ready is loading again.
    assert _wait_for(lambda: "restarted" in events), events
    assert patched_subprocess["conn_holder"]["conn"] is not first_conn
    sent = list(patched_subprocess["sent"])
    inits = [m for m in sent if m[0] == "init"]
    assert len(inits) == 2 and inits[1][1]["model"] == "vosk-ru-small"
    assert any(m[0] == "cmd" and m[2] == "load" for m in sent[-3:]), sent[-3:]


def test_a_respawn_comes_back_on_the_model_the_user_switched_to(patched_subprocess):
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="vosk-ru-small", device="cpu")
    assert backend.wait_for_worker(2)
    backend.change_model("gigaam-v3-ctc", "float16")
    events = []
    backend.set_worker_event_callback(events.append)
    _kill_worker(patched_subprocess, backend)

    assert _wait_for(lambda: "restarted" in events), events
    inits = [m for m in patched_subprocess["sent"] if m[0] == "init"]
    assert inits[-1][1]["model"] == "gigaam-v3-ctc"


def test_status_reads_error_while_the_worker_is_gone(patched_subprocess, monkeypatch):
    from app.backends import subprocess_backend as mod

    monkeypatch.setattr(mod, "_MAX_AUTO_RESPAWNS", 0)   # no automatic restart
    backend = mod.SubprocessBackend(model="vosk-ru-small", device="cpu")
    assert backend.wait_for_worker(2)
    backend._status_cache = "ready"
    _kill_worker(patched_subprocess, backend)

    assert _wait_for(lambda: backend.status() == "error")
    assert backend.health_check() is False
    assert backend.active_provider() is None


def test_transcribing_on_a_dead_worker_says_the_engine_stopped(patched_subprocess, monkeypatch):
    from app.backends import subprocess_backend as mod
    from app.backends.base import TranscriptionError, user_reason

    monkeypatch.setattr(mod, "_MAX_AUTO_RESPAWNS", 0)
    backend = mod.SubprocessBackend(model="vosk-ru-small", device="cpu")
    assert backend.wait_for_worker(2)
    _kill_worker(patched_subprocess, backend)
    assert _wait_for(lambda: backend.status() == "error")

    with pytest.raises(TranscriptionError) as caught:
        backend.transcribe(np.zeros(16000, dtype=np.float32))
    assert "Broken pipe" not in user_reason(caught.value)
    assert "speech engine" in user_reason(caught.value)


def test_selecting_a_model_on_a_dead_worker_respawns_it(patched_subprocess, monkeypatch):
    """Re-selecting the same model must reload when the worker is dead."""
    from app.backends import subprocess_backend as mod

    monkeypatch.setattr(mod, "_MAX_AUTO_RESPAWNS", 0)
    backend = mod.SubprocessBackend(model="vosk-ru-small", device="cpu")
    assert backend.wait_for_worker(2)
    backend._status_cache = "ready"
    _kill_worker(patched_subprocess, backend)
    assert _wait_for(lambda: backend.status() == "error")

    backend.change_model("vosk-ru-small", "float16")

    assert backend.worker_alive()
    inits = [m for m in patched_subprocess["sent"] if m[0] == "init"]
    assert len(inits) == 2
    assert any(m[0] == "cmd" and m[2] == "change_model" for m in patched_subprocess["sent"])


def test_automatic_restarts_are_bounded(patched_subprocess):
    from app.backends import subprocess_backend as mod

    backend = mod.SubprocessBackend(model="vosk-ru-small", device="cpu")
    assert backend.wait_for_worker(2)
    events = []
    backend.set_worker_event_callback(events.append)
    for _ in range(mod._MAX_AUTO_RESPAWNS + 2):
        _kill_worker(patched_subprocess, backend)
        _wait_for(lambda: events and events[-1] in ("died", "restarted") and backend._recovering is False)
        events.append("x")
    inits = [m for m in patched_subprocess["sent"] if m[0] == "init"]
    assert len(inits) <= 1 + mod._MAX_AUTO_RESPAWNS


def test_a_cancel_is_answered_while_a_file_is_being_transcribed(monkeypatch):
    """QA-JOURNEYS-F5: the command loop ran the transcription inline, so a
    Cancel of a model load waited for the whole file."""
    release = threading.Event()
    fake = MagicMock()
    fake.status.return_value = "ready"

    def slow_file(_path):
        release.wait(5)
        return "done"

    fake.transcribe_file.side_effect = slow_file

    import app.backends.subprocess_worker as worker_mod

    monkeypatch.setattr(worker_mod, "_RegistryBackend", lambda **_kw: fake)
    parent, t, _run_all = _drive_worker([], init_kwargs={"model": "x"})
    try:
        assert _recv_response(parent, 5) == ("ok", None)
        parent.send(("cmd", 1, "transcribe_file", "/x.wav"))
        parent.send(("cmd", 2, "cancel_load"))
        first = _recv_response(parent, 2)       # must be the cancel, not the file
        assert first == ("resp", 2, "ok", None)
        fake.cancel_load.assert_called_once()
        release.set()
        assert _recv_response(parent, 5) == ("resp", 1, "ok", "done")
    finally:
        release.set()
        parent.close()
        t.join(timeout=2)
