"""Two log channels on one logger: what lands in ``app.log``, what the user sees.

``_install_file_logging`` owns three things the app gets wrong when they
drift apart:

* the ``logging`` section of ``config.yaml`` — declared in
  ``DEFAULT_CONFIG`` and, until recently, read by nothing, which is why
  ``app.log`` grew without bound for the life of an install;
* a filter on the file handler alone, so a dictated sentence shows up
  in the Logs view and stays out of the file on disk;
* the root logger's global state, which it mutates and never undoes.

That last one shapes the file: every test here runs under a fixture
that puts the root logger back the way it found it, handlers, level and
warnings-capture included.
"""

from __future__ import annotations

import copy
import logging
import os
import threading
import warnings
from logging.handlers import RotatingFileHandler
from unittest.mock import MagicMock

import pytest


# ---- global logging state, saved and restored ------------------------------
#
# ``_install_file_logging`` attaches to the ROOT logger, sets its level
# and calls ``logging.captureWarnings(True)``. It offers no way back, and
# a leaked handler outlives the tmp directory it points into — every
# later test that logs would then write to a deleted path. So the
# cleanup restores the whole picture rather than closing one file
# handler: handlers the test did not add get closed *and* removed, the
# handler list itself is restored (pytest's own capture handlers come
# and go around it), and the level goes back to what it was.


@pytest.fixture(autouse=True)
def isolated_root_logger():
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_warnings_hook = logging._warnings_showwarning
    saved_showwarning = warnings.showwarning

    yield root

    for handler in list(root.handlers):
        if handler not in saved_handlers:
            root.removeHandler(handler)
            handler.close()
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    # ``captureWarnings(True)`` rewrites ``warnings.showwarning``; pytest
    # has its own hook installed inside its per-test context, so this
    # has to be put back the way it was found or warning reporting for
    # the rest of the run is silently rerouted.
    logging._warnings_showwarning = saved_warnings_hook
    warnings.showwarning = saved_showwarning


def _config():
    """A ``ConfigManager`` carrying a private copy of the shipped defaults.

    Built from ``DEFAULT_CONFIG`` on purpose: the tests below override
    ``rotation.enabled`` / ``max_bytes`` / ``level`` by *config key*, so
    a handler that stopped reading the section — or started reading a
    differently-named key — fails here instead of quietly passing
    against defaults that happen to match.
    """
    from app.config_manager import DEFAULT_CONFIG, ConfigManager

    cm = ConfigManager.__new__(ConfigManager)
    cm.config = copy.deepcopy(DEFAULT_CONFIG)
    return cm


def _handler_for(path: str):
    """The root handler serving ``path``, or ``None``.

    Matched by ``baseFilename`` rather than assumed to be the only
    handler: pytest attaches its own capture handlers to the root.
    """
    for handler in logging.getLogger().handlers:
        if getattr(handler, "baseFilename", None) == os.path.abspath(path):
            return handler
    return None


# ---- 6. the logging section drives the handler -----------------------------


def test_the_configured_file_name_is_the_one_that_gets_written(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(
        "app.utils.get_project_logs_path", lambda: str(tmp_path),
    )
    import app.gui.app as app_module

    cm = _config()
    cm.config["logging"]["file"]["filename"] = "custom-app.log"

    path = app_module._install_file_logging(cm)

    assert os.path.basename(path) == "custom-app.log", path
    assert (tmp_path / "custom-app.log").exists()


def test_rotation_off_installs_a_plain_file_handler(monkeypatch, tmp_path):
    """``rotation.enabled: false`` is the honest answer for someone who
    wants every line kept — a plain handler never rotates anything out."""
    monkeypatch.setattr(
        "app.utils.get_project_logs_path", lambda: str(tmp_path),
    )
    import app.gui.app as app_module

    cm = _config()
    cm.config["logging"]["file"]["rotation"]["enabled"] = False

    path = app_module._install_file_logging(cm)
    handler = _handler_for(path)

    assert handler is not None, "no file handler was installed"
    assert isinstance(handler, logging.FileHandler)
    assert not isinstance(handler, RotatingFileHandler), (
        "rotation is disabled in the config; a rotating handler would "
        "still discard the oldest lines"
    )


def test_rotation_on_carries_the_configured_caps(monkeypatch, tmp_path):
    """Distinctive values rather than the defaults, so a hardcoded
    ``RotatingFileHandler(1048576, 5)`` cannot pass."""
    monkeypatch.setattr(
        "app.utils.get_project_logs_path", lambda: str(tmp_path),
    )
    import app.gui.app as app_module

    cm = _config()
    rotation = cm.config["logging"]["file"]["rotation"]
    rotation["enabled"] = True
    rotation["max_bytes"] = 1234567
    rotation["backup_count"] = 7

    path = app_module._install_file_logging(cm)
    handler = _handler_for(path)

    assert isinstance(handler, RotatingFileHandler), (
        f"got {type(handler).__name__} for a config with rotation on"
    )
    assert handler.maxBytes == 1234567
    assert handler.backupCount == 7


def test_file_logging_off_installs_nothing_and_says_so(monkeypatch, tmp_path):
    """``file.enabled: false`` is a real off switch — no handler, no
    empty path handed back as if a log had been opened."""
    monkeypatch.setattr(
        "app.utils.get_project_logs_path", lambda: str(tmp_path),
    )
    import app.gui.app as app_module

    cm = _config()
    cm.config["logging"]["file"]["enabled"] = False

    before = list(logging.getLogger().handlers)
    path = app_module._install_file_logging(cm)

    assert path == ""
    assert list(logging.getLogger().handlers) == before
    assert list(tmp_path.iterdir()) == []


def test_the_configured_level_lands_on_the_root_logger(monkeypatch, tmp_path):
    """A level of ``WARNING`` in the config has to silence INFO in the
    file too, not just be stored in a dict nobody reads."""
    monkeypatch.setattr(
        "app.utils.get_project_logs_path", lambda: str(tmp_path),
    )
    import app.gui.app as app_module

    cm = _config()
    cm.config["logging"]["level"] = "WARNING"

    path = app_module._install_file_logging(cm)

    assert logging.getLogger().level == logging.WARNING
    assert _handler_for(path).level == logging.WARNING


# ---- 5. the user's own words: Logs view yes, app.log no ---------------------


class _Collector(logging.Handler):
    """A handler that keeps what it was given, so a test can ask what
    reached it rather than what would have been formatted."""

    def __init__(self):
        super().__init__(level=logging.NOTSET)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@pytest.fixture
def two_channels():
    """One logger, two handlers: the filtered file side and the plain
    UI side. ``propagate = False`` keeps the records out of the root
    logger the fixture above is busy protecting.
    """
    import app.gui.app as app_module

    logger = logging.getLogger("test.file_logging.channels")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    to_view = _Collector()
    to_file = _Collector()
    to_file.addFilter(app_module._NoSensitiveToFile())
    logger.addHandler(to_view)
    logger.addHandler(to_file)
    try:
        yield logger, to_view, to_file
    finally:
        logger.removeHandler(to_view)
        logger.removeHandler(to_file)


def test_a_sensitive_record_reaches_the_view_and_not_the_file(two_channels):
    logger, to_view, to_file = two_channels

    logger.info(
        "Transcribed: %s", "четыре четыреста семь",
        extra={"user_message": True, "sensitive": True},
    )

    assert any("Transcribed" in m for m in to_view.messages), to_view.messages
    assert not any("Transcribed" in m for m in to_file.messages), to_file.messages


def test_an_ordinary_record_reaches_both(two_channels):
    logger, to_view, to_file = two_channels

    logger.info("Model loaded", extra={"user_message": False})

    assert "Model loaded" in to_view.messages
    assert "Model loaded" in to_file.messages


def test_an_explicitly_non_sensitive_record_reaches_both(two_channels):
    """The half of (a) that a filter dropping everything would pass:
    ``sensitive=False`` is a statement, not an absence, and it has to
    be believed."""
    logger, to_view, to_file = two_channels

    logger.info("Model loaded", extra={"sensitive": False})

    assert "Model loaded" in to_view.messages
    assert "Model loaded" in to_file.messages


def _pipeline(logger):
    """Half-real StateManager, wired like the sibling state-manager
    suites, reporting one delivered transcription."""
    from app.state_manager import StateManager

    sm = StateManager.__new__(StateManager)
    sm.audio_recorder = MagicMock()
    sm.audio_recorder.get_audio_duration.return_value = 1.5
    sm.backend = MagicMock()
    sm.backend.transcribe.return_value = "четыре четыреста семь"
    sm.backend.current_model.return_value = "test-model"
    sm.backend.current_language.return_value = None
    sm.clipboard_manager = MagicMock()
    sm.clipboard_manager.deliver_transcription.return_value = "pasted"
    sm.clipboard_manager.paste_combo.return_value = "Cmd+V"
    sm.history_manager = MagicMock()
    sm.history_update_callback = None
    sm.delivery_reported_callback = None
    sm.is_processing = False
    sm.is_model_loading = False
    sm.last_transcription = None
    sm._pending_model_change = None
    sm._state_lock = threading.Lock()
    sm.logger = logger
    sm.audio_feedback = MagicMock()
    sm.system_tray = MagicMock()
    return sm


def test_the_transcribed_line_is_the_one_that_is_tagged(two_channels):
    """The filter above is only worth anything if the record it drops
    is the one carrying the dictated text.

    Synthetic records prove the filter's behaviour; this drives the
    actual pipeline, because the tagging lives in ``state_manager``
    and a filter test cannot see whether anyone set the flag.
    """
    logger, to_view, to_file = two_channels

    _pipeline(logger)._transcription_pipeline(b"audio")

    transcribed = [m for m in to_view.messages if m.startswith("Transcribed:")]
    assert len(transcribed) == 1, to_view.messages
    assert "четыре четыреста семь" in transcribed[0]
    assert not [m for m in to_file.messages if m.startswith("Transcribed:")], (
        "the dictated text reached app.log"
    )

def test_the_production_call_site_actually_passes_a_config():
    """``_install_file_logging(config)`` reads the ``logging`` section, so
    calling it with no argument leaves that section decorative again —
    every knob falls back to the hardcoded defaults and ``app.log`` goes
    back to growing without bound.

    This is here because it is exactly the bug that survived the fix:
    the handler honoured the config in every unit test, while the one
    call that runs in production passed nothing. The unit tests could
    not see it, so something has to.
    """
    import ast
    import inspect
    from pathlib import Path

    import app.gui.app as app_mod

    src = Path(inspect.getsourcefile(app_mod)).read_text(encoding="utf-8")
    tree = ast.parse(src)

    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_install_file_logging"
    ]
    assert calls, "_install_file_logging is never called"

    for call in calls:
        assert call.args, (
            f"вызов на строке {call.lineno} не передаёт config — "
            "секция logging остаётся мёртвой"
        )

    # And the argument must actually be a ConfigManager, not None.
    assert not any(
        isinstance(a, ast.Constant) and a.value is None for a in calls[0].args
    ), "передан None вместо конфига"
