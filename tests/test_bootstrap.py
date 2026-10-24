"""The start-up helpers the runtime shares: persisted-model autoload, storage
path, the onnx-asr pre-import and the rotating log file (``app/bootstrap.py``).

Re-homed from the Qt entry-point tests; nothing here needs a display.
"""

import os

import pytest


# ---- Persisted-model auto-load --------------------------------------------


class _FakeBackend:
    """Minimal backend stub: records load() and current_model()."""

    def __init__(self, model: str) -> None:
        self._model = model
        self.load_called = 0
        self.changed_to: list[str] = []

    def current_model(self) -> str:
        return self._model

    def load(self) -> None:
        self.load_called += 1

    def change_model(self, model: str) -> None:
        self.changed_to.append(model)


def test_autoload_kicks_off_load_when_model_is_cached(monkeypatch):
    """When the persisted model is in the registry AND its weights are
    already on disk, the helper must call ``backend.load()`` so the
    backend transitions ``stopped → loading → ready`` in the
    background — otherwise the topbar shows the model name but the
    hotkey listener rejects every press with 'Model is not ready yet'."""
    import app.bootstrap as app_module

    backend = _FakeBackend("whisper-large-v3-turbo")
    monkeypatch.setattr(app_module, "is_cached_for_info", lambda info: True)

    app_module._autoload_persisted_model(backend)
    assert backend.load_called == 1


def test_autoload_skips_load_when_model_not_cached(monkeypatch):
    """If the configured model isn't downloaded yet, don't auto-load —
    force the user to click Download deliberately so they see the
    progress bar and aren't surprised by a 1.5 GB silent transfer."""
    import app.bootstrap as app_module

    backend = _FakeBackend("whisper-large-v3-turbo")
    monkeypatch.setattr(app_module, "is_cached_for_info", lambda info: False)

    app_module._autoload_persisted_model(backend)
    assert backend.load_called == 0


def test_autoload_falls_back_to_canonical_check_for_unknown_model(monkeypatch):
    """If the configured model isn't in the registry (legacy entry,
    user-pasted HF id), the helper still tries the lenient HF cache
    check and loads if anything is on disk."""
    import app.bootstrap as app_module

    backend = _FakeBackend("some/unknown-model")
    monkeypatch.setattr(app_module, "is_model_cached", lambda canonical: True)
    # is_cached_for_info shouldn't even be reached for an unknown model.
    monkeypatch.setattr(
        app_module,
        "is_cached_for_info",
        lambda info: pytest.fail("should not call is_cached_for_info for unknown id"),
    )

    app_module._autoload_persisted_model(backend)
    assert backend.load_called == 1


def test_autoload_prefers_persisted_alias_over_backend_canonical(monkeypatch):
    """Shared-canonical presets such as GigaAM CTC/RNN-T must keep the
    persisted alias when deciding what is cached + what to log. The
    backend only surfaces the HF canonical, which would otherwise map
    back to the registry's first alias and lose the decoder choice."""
    import app.bootstrap as app_module

    class _Config:
        def get_setting(self, section, key):
            if (section, key) == ("whisper", "model"):
                return "gigaam-v3-rnnt"
            return None

    backend = _FakeBackend("istupakov/gigaam-v3-onnx")

    def _is_cached(info):
        return info.alias == "gigaam-v3-rnnt"

    monkeypatch.setattr(app_module, "is_cached_for_info", _is_cached)
    monkeypatch.setattr(
        app_module,
        "is_model_cached",
        lambda canonical: pytest.fail("should use registry alias path"),
    )

    app_module._autoload_persisted_model(backend, config=_Config())
    assert backend.load_called == 1


def test_autoload_fallback_changes_to_candidate_alias(monkeypatch):
    """Fallback auto-load must preserve alias-level semantics when it
    asks the backend to switch. Using the candidate canonical would
    lose per-alias ``load_id`` differences for shared-canonical
    presets."""
    import app.bootstrap as app_module

    class _Config:
        def get_setting(self, section, key):
            if (section, key) == ("whisper", "model"):
                return "missing-model"
            return None

    backend = _FakeBackend("missing-model")
    monkeypatch.setattr(
        app_module, "is_model_cached", lambda canonical: False
    )
    monkeypatch.setattr(
        app_module,
        "is_cached_for_info",
        lambda info: info.alias == "gigaam-v3-rnnt",
    )

    app_module._autoload_persisted_model(backend, config=_Config())
    assert backend.changed_to == ["gigaam-v3-rnnt"]


def test_autoload_no_op_when_backend_is_none():
    """Sanity: helper must accept None backend without raising — main()
    can be called with backend=None during early shutdown / tests."""
    import app.bootstrap as app_module

    # Must not raise.
    app_module._autoload_persisted_model(None)


def test_apply_storage_path_silences_hf_symlinks_warning(monkeypatch, tmp_path):
    """Without HF_HUB_DISABLE_SYMLINKS_WARNING set, every model
    download spams the Logs view with the same one-line warning
    about Windows symlinks needing Developer Mode / admin.  We
    suppress it once during startup."""
    import os

    monkeypatch.delenv("HF_HUB_DISABLE_SYMLINKS_WARNING", raising=False)

    from app.bootstrap import _apply_storage_path

    _apply_storage_path(str(tmp_path))
    assert os.environ.get("HF_HUB_DISABLE_SYMLINKS_WARNING") == "1"


def test_apply_storage_path_does_not_overwrite_user_symlinks_setting(
    monkeypatch, tmp_path,
):
    """If the user (or a parent process) explicitly set the env var
    to something else, leave it alone — they may have a reason."""
    import os

    monkeypatch.setenv("HF_HUB_DISABLE_SYMLINKS_WARNING", "0")

    from app.bootstrap import _apply_storage_path

    _apply_storage_path(str(tmp_path))
    assert os.environ.get("HF_HUB_DISABLE_SYMLINKS_WARNING") == "0"



# ---- onnx_asr preimport (Option A: dodge Windows DLL loader-lock freeze) ----


def test_preload_onnx_asr_returns_daemon_thread():
    """``_preload_onnx_asr_async`` must return a daemon Thread so the
    process exits cleanly even if the import is still in flight when
    the user quits — non-daemon threads block interpreter teardown.
    """
    import threading

    from app.bootstrap import _preload_onnx_asr_async

    t = _preload_onnx_asr_async()
    try:
        assert isinstance(t, threading.Thread)
        assert t.daemon is True, "preimport thread must be daemon"
    finally:
        # Wait for the thread, capped — if it deadlocks the test
        # would hang otherwise. 30 s is generous; a real onnx_asr
        # import takes ~1.5 s on the dev box.
        t.join(timeout=30)


def test_preload_onnx_asr_thread_has_descriptive_name():
    """Named threads make ``psutil`` / Logs view diagnostics readable
    when a user reports a hang. Without a name the listener shows
    ``Thread-N`` and we lose the context."""
    from app.bootstrap import _preload_onnx_asr_async

    t = _preload_onnx_asr_async()
    try:
        assert "onnx" in t.name.lower(), (
            f"expected 'onnx' in thread name for diagnostics, got {t.name!r}"
        )
    finally:
        t.join(timeout=30)


@pytest.mark.timing
def test_preload_onnx_asr_does_not_block_caller(monkeypatch):
    """The caller thread must return immediately — the whole point is
    to overlap the heavy import with QApplication / window construction.
    If we block here, we've lost the latency win."""
    import threading
    import time

    # Stub out the import target so the worker blocks deterministically.
    started = threading.Event()
    release = threading.Event()

    def slow_import():
        started.set()
        # Hold the worker until the test releases it. If the caller
        # were waiting on us, the assertion below would time out.
        release.wait(5)

    import app.bootstrap as app_module

    monkeypatch.setattr(app_module, "_do_onnx_asr_preimport", slow_import)

    t0 = time.monotonic()
    t = app_module._preload_onnx_asr_async()
    elapsed = time.monotonic() - t0
    try:
        assert elapsed < 0.5, (
            f"caller blocked for {elapsed:.2f}s — preimport must run "
            f"on a background thread"
        )
        assert started.wait(2.0), "preimport worker did not start"
    finally:
        release.set()
        t.join(timeout=5)


def test_preload_onnx_asr_swallows_import_error(monkeypatch):
    """If onnx_asr is missing (test env without the heavy dep), or
    import dies on a broken install, the preimport thread must not
    propagate — startup should continue normally and the user discovers
    the problem only when they try to load a model."""
    import threading

    failure_seen = threading.Event()

    def boom():
        failure_seen.set()
        raise ImportError("simulated broken install")

    import app.bootstrap as app_module

    monkeypatch.setattr(app_module, "_do_onnx_asr_preimport", boom)

    t = app_module._preload_onnx_asr_async()
    t.join(timeout=5)
    assert failure_seen.is_set(), "stub must have been called"
    # Reaching this line means the exception didn't escape the thread.



def test_preload_onnx_asr_warms_up_ort_providers():
    """``_do_onnx_asr_preimport`` must create a dummy InferenceSession
    so OnnxRuntime loads its execution-provider DLLs (DirectML, CUDA,
    CPU) on this daemon thread.  The real symptom if this is skipped:
    the first model load acquires the Win32 DLL loader-lock while the
    Qt main thread also needs it — window cannot be moved / is marked
    (Not responding).

    We verify the side-effect: ``onnxruntime.InferenceSession`` must
    have been called at least once after ``_do_onnx_asr_preimport``
    runs.
    """
    import sys
    from unittest.mock import MagicMock, patch

    # Stub onnx_asr so we don't need the heavy install.
    sys.modules.setdefault("onnx_asr", MagicMock())

    import app.bootstrap as app_module

    session_calls: list = []

    class _FakeSession:
        def __init__(self, *_a, **_kw):
            session_calls.append(True)

        def run(self, *_a, **_kw):
            return [None]

    fake_ort = MagicMock()
    fake_ort.InferenceSession = _FakeSession
    fake_ort.SessionOptions.return_value = MagicMock()
    # get_available_providers must return an iterable so the warmup loop runs.
    fake_ort.get_available_providers.return_value = ["CPUExecutionProvider"]

    with patch.dict(sys.modules, {"onnxruntime": fake_ort}):
        app_module._do_onnx_asr_preimport()

    assert session_calls, (
        "_do_onnx_asr_preimport must create an InferenceSession "
        "to force provider DLL loading"
    )



def test_install_file_logging_writes_records_to_the_log_file(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(
        "app.utils.get_project_logs_path", lambda: str(tmp_path),
    )
    import logging as _logging

    import app.bootstrap as app_module

    path = app_module._install_file_logging()
    try:
        _logging.getLogger("test.probe").info("a line that must land")
        for handler in _logging.getLogger().handlers:
            handler.flush()
        text = (tmp_path / "app.log").read_text(encoding="utf-8")
    finally:
        _remove_log_handler(path)

    assert "a line that must land" in text


def test_install_file_logging_does_not_attach_a_second_handler(
    monkeypatch, tmp_path,
):
    """Installing twice would otherwise double every later line — and
    the function is reachable from more than one call path."""
    monkeypatch.setattr(
        "app.utils.get_project_logs_path", lambda: str(tmp_path),
    )
    import logging as _logging

    import app.bootstrap as app_module

    path = app_module._install_file_logging()
    try:
        app_module._install_file_logging()
        _logging.getLogger("test.probe").info("only once")
        for handler in _logging.getLogger().handlers:
            handler.flush()
        text = (tmp_path / "app.log").read_text(encoding="utf-8")
    finally:
        _remove_log_handler(path)

    assert text.count("only once") == 1, text


def _remove_log_handler(path: str) -> None:
    """Drop the file handler a test attached, keeping the root logger as
    the suite found it."""
    import os

    import logging as _logging

    root = _logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "baseFilename", None) == os.path.abspath(path):
            root.removeHandler(handler)
            handler.close()
