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


@pytest.fixture(autouse=True)
def _leave_the_variable_as_found(monkeypatch):
    """The runtime's flag writes the variable into the process environment
    itself, outside monkeypatch's reach, and a test that follows in the same
    process (Windows runs the suite in one) would read the leftover path as
    its own data directory. Registering the original state first makes
    monkeypatch put it back."""
    monkeypatch.setenv(DATA_DIR_ENV, "placeholder")
    monkeypatch.delenv(DATA_DIR_ENV)


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


# ---- QA-RUNTIME-F5/F6: a named data folder is never swapped for another profile ----


def _start(entry, *argv):
    return entry.main(["--no-single-instance", "--no-stdin-watch", *argv])


def test_a_data_dir_that_is_a_file_ends_the_start_with_a_message(tmp_path, monkeypatch, capsys):
    from app.server import __main__ as entry

    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    target = tmp_path / "afile"
    target.write_text("x")

    assert _start(entry, "--data-dir", str(target)) == 2
    out = capsys.readouterr()
    assert '"bad_data_dir"' in out.out and "is a file" in out.err
    assert "Traceback" not in out.err
    assert DATA_DIR_ENV not in os.environ


def test_an_empty_data_dir_value_is_refused_not_ignored(monkeypatch, capsys):
    from app.server import __main__ as entry

    monkeypatch.delenv(DATA_DIR_ENV, raising=False)

    assert _start(entry, "--data-dir", "") == 2
    assert "empty" in capsys.readouterr().err


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs POSIX modes, not root")
def test_a_read_only_data_dir_ends_the_start(tmp_path, monkeypatch, capsys):
    from app.server import __main__ as entry

    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        assert _start(entry, "--data-dir", str(ro)) == 2
    finally:
        ro.chmod(0o755)
    assert "not writable" in capsys.readouterr().err


def test_an_unusable_logs_folder_does_not_fall_back_to_the_real_profile(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "logs").write_text("a file where the folder should be")
    monkeypatch.setenv(DATA_DIR_ENV, str(data))

    with pytest.raises(OSError):
        get_project_logs_path()


def test_the_default_models_folder_is_inside_the_data_dir(tmp_path, monkeypatch):
    from app.utils import get_models_root

    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "mine"))

    assert Path(get_models_root("")) == (tmp_path / "mine" / "models").resolve()


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_the_logs_folder_is_owner_only(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "mine"))

    logs = Path(get_project_logs_path())

    assert (logs.stat().st_mode & 0o777) == 0o700
