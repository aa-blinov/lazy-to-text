"""A wrongly typed leaf in config.yaml falls back to the default.

QA-RUNTIME-14: ``beam_size: abc``, ``max_duration: abc``, a numeric hotkey
or ``storage.models_dir: 5`` raised in ``int()`` or ``.strip()`` during
start-up and took the whole recording stack (or the runtime) down.
"""

from __future__ import annotations

import logging

import pytest
import yaml

from app.config_manager import ConfigManager, DEFAULT_CONFIG
from tests.test_config_manager import fake_project  # noqa: F401  (fixture)


def _load(project, section, key, value):
    (project / "config.yaml").write_text(
        yaml.safe_dump({section: {key: value}}), encoding="utf-8"
    )
    return ConfigManager()


@pytest.mark.parametrize(
    "section, key, bad",
    [
        ("whisper", "beam_size", "abc"),
        ("whisper", "beam_size", True),
        ("audio", "max_duration", "abc"),
        ("audio", "max_duration", float("nan")),
        ("audio", "mute_output_on_record", "yes please"),
        ("hotkey", "start_recording_hotkey", 5),
        ("hotkey", "stop_recording_hotkey", [1]),
        ("hotkey", "push_to_talk_min_hold_seconds", "abc"),
        ("storage", "models_dir", 5),
    ],
)
def test_a_wrong_type_is_replaced_by_the_default(fake_project, key, section, bad, caplog):
    with caplog.at_level(logging.WARNING, logger="app.config_manager"):
        cm = _load(fake_project, section, key, bad)

    assert cm.get_setting(section, key) == DEFAULT_CONFIG[section][key]
    assert any(key in r.getMessage() for r in caplog.records)


def test_a_right_type_is_kept_and_an_int_may_stand_for_a_float(fake_project):
    cm = _load(fake_project, "hotkey", "push_to_talk_min_hold_seconds", 1)

    assert cm.get_setting("hotkey", "push_to_talk_min_hold_seconds") == 1


def test_the_recording_stack_numbers_survive_a_hand_edited_file(fake_project):
    cm = _load(fake_project, "whisper", "beam_size", "abc")

    assert int(cm.get_whisper_config().get("beam_size", 5)) == 5
    assert cm.get_setting("storage", "models_dir") == ""


def test_an_unwritable_logs_folder_falls_back_to_the_user_log_folder(tmp_path, monkeypatch):
    from app import utils

    blocker = tmp_path / "logs"
    blocker.write_text("a file where the folder should be")
    monkeypatch.setattr(utils, "_is_frozen", lambda: False)
    monkeypatch.setattr(utils, "is_installed_package", lambda: True)
    monkeypatch.chdir(tmp_path)
    fallback = tmp_path / "userlogs"
    monkeypatch.setattr("platformdirs.user_log_dir", lambda *a, **k: str(fallback))

    assert utils.get_project_logs_path() == str(fallback)
    assert fallback.is_dir()
