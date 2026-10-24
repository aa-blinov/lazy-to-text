"""``L2T_DATA_DIR`` / ``--data-dir`` keep a run's data to itself (QA-JOURNEYS-12).

Every dev runtime used to read and write the checkout's ``config.yaml``,
``logs/app.log`` and ``logs/transcription_history.jsonl``, so a tester saw
another run's history and a hotkey change in one run reached the next.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.utils import DATA_DIR_ENV, data_dir_override, get_project_logs_path


def test_without_the_variable_nothing_changes(monkeypatch):
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    assert data_dir_override() is None


def test_logs_and_history_follow_the_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "mine"))

    logs = Path(get_project_logs_path())

    assert logs == (tmp_path / "mine" / "logs").resolve()
    assert logs.is_dir()


def test_the_config_follows_the_data_dir(tmp_path, monkeypatch):
    from app.config_manager import ConfigManager

    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "mine"))

    manager = ConfigManager()

    assert Path(manager.config_path).parent == (tmp_path / "mine").resolve()
    assert Path(manager.config_path).exists()


def test_the_runtime_flag_sets_the_variable_before_anything_reads_it(tmp_path, monkeypatch):
    from app.server import __main__ as entry
    from app.server import runtime

    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    seen = {}

    class _Stop(Exception):
        pass

    class _Runtime:
        def __init__(self):
            seen["env"] = os.environ.get(DATA_DIR_ENV)
            raise _Stop

    monkeypatch.setattr(runtime, "Runtime", _Runtime)
    with pytest.raises(_Stop):
        entry.main(["--no-single-instance", "--no-stdin-watch",
                    "--data-dir", str(tmp_path / "d")])
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)

    assert seen["env"] == str(tmp_path / "d")
