"""The user's words on disk are readable by the user only (QA-SEC-F4, QA-RUNTIME-F3).

``app.log``, the history and the audio kept for a failed dictation used to be
created with the umask's default, readable by every local user, and the audio
outlived "Clear history".
"""

from __future__ import annotations

import logging
import os
import threading
from unittest.mock import MagicMock

import numpy as np
import pytest

posix_only = pytest.mark.skipif(os.name == "nt", reason="file modes are POSIX")


def _mode(path) -> int:
    return os.stat(path).st_mode & 0o777


@posix_only
def test_app_log_is_created_owner_only(tmp_path, monkeypatch):
    from app import bootstrap

    monkeypatch.setattr("app.utils.get_project_logs_path", lambda: str(tmp_path))
    old = os.umask(0o022)
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        path = bootstrap._install_file_logging(None)
        logging.getLogger("t").warning("a line")
        for h in root.handlers:
            h.flush()
        assert _mode(path) == 0o600
    finally:
        os.umask(old)
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
                h.close()


@posix_only
def test_the_history_file_is_owner_only_after_every_kind_of_write(tmp_path):
    from app.history_manager import HistoryManager

    old = os.umask(0o022)
    try:
        mgr = HistoryManager(max_entries=50, history_file=str(tmp_path / "h.jsonl"))
        mgr.add_entry("one", 1.0, "m", "ru")
        assert _mode(tmp_path / "h.jsonl") == 0o600
        mgr.add_entry("two", 1.0, "m", "ru")
        mgr._compact()
        assert _mode(tmp_path / "h.jsonl") == 0o600
        mgr.clear_history()
        assert _mode(tmp_path / "h.jsonl") == 0o600
    finally:
        os.umask(old)


def _keeper(tmp_path, monkeypatch):
    from app.state_manager import StateManager

    monkeypatch.setattr("app.utils.get_project_logs_path", lambda: str(tmp_path))
    sm = StateManager.__new__(StateManager)
    sm.logger = logging.getLogger("test.private")
    sm._state_lock = threading.Lock()
    return sm


@posix_only
def test_a_kept_recording_and_its_folder_are_owner_only(tmp_path, monkeypatch):
    sm = _keeper(tmp_path, monkeypatch)
    old = os.umask(0o022)
    try:
        path = sm._keep_recording(np.full(16_000, 0.1, dtype=np.float32))
    finally:
        os.umask(old)

    assert path and _mode(path) == 0o600
    assert _mode(tmp_path / "unprocessed-recordings") == 0o700


def test_clear_history_removes_the_audio_kept_for_failed_dictations(tmp_path, monkeypatch):
    from app.history_manager import HistoryManager

    sm = _keeper(tmp_path, monkeypatch)
    for _ in range(2):
        assert sm._keep_recording(np.full(16_000, 0.1, dtype=np.float32))
    mgr = HistoryManager(max_entries=50, history_file=str(tmp_path / "h.jsonl"))
    mgr.add_entry("one", 1.0, "m", "ru")
    assert list((tmp_path / "unprocessed-recordings").glob("*.wav"))

    mgr.clear_history()

    assert not list((tmp_path / "unprocessed-recordings").glob("*.wav"))
