"""Tests for ConfigManager — base-dir resolution + first-launch behaviour.

ConfigManager always reads / writes ``config.yaml`` at the project
root (resolved by walking up from CWD to the nearest
``pyproject.toml``). The previous PyInstaller-bundle paths
(``%APPDATA%/LazyToText/`` + bundled-defaults seed-copy) were
removed when the source-only distribution was adopted; this test
file now covers only the dev-mode resolver and the atomic-write
contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fake_project(monkeypatch, tmp_path):
    """Each test gets a clean fake project root (``pyproject.toml``
    + empty CWD chdir) so the ``_resolve_base_dir`` walk hits a
    deterministic location instead of climbing up to the actual
    repo root and clobbering the developer's ``config.yaml``."""
    project_root = tmp_path / "fake_project"
    project_root.mkdir()
    (project_root / "pyproject.toml").touch()
    monkeypatch.chdir(project_root)
    return project_root


# ---- _resolve_base_dir ------------------------------------------------------


def test_dev_mode_uses_project_root(fake_project):
    """The resolver walks up from CWD until it finds a
    ``pyproject.toml``. Default behaviour preserved."""
    from app.config_manager import ConfigManager

    cm = ConfigManager()
    assert cm.base_dir == fake_project
    assert cm.config_path == fake_project / "config.yaml"


# ---- First-launch defaults --------------------------------------------------


def test_first_launch_writes_defaults_when_no_user_config(fake_project):
    """No existing config.yaml → write the in-code ``DEFAULT_CONFIG``
    to the project root."""
    from app.config_manager import ConfigManager, DEFAULT_CONFIG

    cm = ConfigManager()
    assert cm.config_path.exists()
    # Verify a known default field round-tripped.
    assert cm.get_setting("hotkey", "start_recording_hotkey") == \
        DEFAULT_CONFIG["hotkey"]["start_recording_hotkey"]


def test_subsequent_writes_round_trip_through_disk(fake_project):
    """``update_user_setting`` must persist the new value to the
    ``config.yaml`` on disk so the next launch picks it up. Async
    writer is synchronously drained via ``flush_pending_writes`` so
    the read-back below sees the new value."""
    from app.config_manager import ConfigManager

    cm = ConfigManager()
    cm.update_user_setting("hotkey", "start_recording_hotkey", "ctrl+f5")
    cm.flush_pending_writes()

    text = cm.config_path.read_text(encoding="utf-8")
    assert "ctrl+f5" in text
    assert cm.config_path.parent == fake_project


# ---- atomic write ----------------------------------------------------------


def test_write_leaves_no_tmp_file(fake_project):
    """Atomic write must clean up the ``.tmp`` staging file regardless
    of outcome — a leftover ``.tmp`` means the swap never completed
    and the previous file should still be intact."""
    from app.config_manager import ConfigManager

    cm = ConfigManager()
    cm.update_user_setting("audio", "channels", 2)
    cm.flush_pending_writes()

    tmp = cm.config_path.with_suffix(".tmp")
    assert not tmp.exists(), ".tmp staging file must be removed after a successful write"


def test_config_round_trips_through_yaml(fake_project):
    """Values written by ConfigManager must survive a YAML round-trip —
    read back from disk and compare to what was stored in-memory."""
    import yaml
    from app.config_manager import ConfigManager

    cm = ConfigManager()
    cm.update_user_setting("clipboard", "key_simulation_delay", 0.07)
    cm.update_user_setting("whisper", "language", "ru")
    cm.flush_pending_writes()

    on_disk = yaml.safe_load(cm.config_path.read_text(encoding="utf-8"))
    assert on_disk["clipboard"]["key_simulation_delay"] == pytest.approx(0.07)
    assert on_disk["whisper"]["language"] == "ru"


# ---- DEFAULT_CONFIG must stay a constant ------------------------------------
#
# ``DEFAULT_CONFIG`` is a module-level dict of nested dicts, and
# ``update_user_setting`` writes into ``self.config[section][key]`` in
# place. If a ConfigManager ever holds *those* dicts rather than copies,
# the first setting a user changes rewrites the defaults for the rest of
# the process — and every later ConfigManager, test or real, inherits
# the mutation. Both paths below shipped doing exactly that.


@pytest.fixture
def pristine_defaults():
    """Restore ``DEFAULT_CONFIG`` after a test that may corrupt it.

    Without this, a failing run would poison every test that comes
    after it, which is a far more confusing failure than the one being
    tested.
    """
    import copy as _copy

    from app.config_manager import DEFAULT_CONFIG

    snapshot = _copy.deepcopy(DEFAULT_CONFIG)
    yield DEFAULT_CONFIG
    DEFAULT_CONFIG.clear()
    DEFAULT_CONFIG.update(snapshot)


def test_writing_a_setting_does_not_rewrite_the_module_defaults(
    fake_project, pristine_defaults
):
    """Fresh install: no ``config.yaml`` on disk at all.

    This is the ``DEFAULT_CONFIG.copy()`` path — a shallow copy, so the
    nested section dicts are shared with the module-level original.
    """
    from app.config_manager import ConfigManager

    before = pristine_defaults["storage"]["models_dir"]

    cm = ConfigManager()  # seeds from the defaults
    cm.update_user_setting("storage", "models_dir", "/somewhere/else")
    cm.flush_pending_writes()

    assert cm.get_setting("storage", "models_dir") == "/somewhere/else"
    assert pristine_defaults["storage"]["models_dir"] == before, (
        "a user's storage choice rewrote the module-level DEFAULT_CONFIG"
    )


def test_a_partial_config_does_not_alias_the_module_defaults(
    fake_project, pristine_defaults
):
    """The common path: a real ``config.yaml`` that is missing a section.

    ``_fill_defaults`` fills the gap from ``DEFAULT_CONFIG``. Handing the
    result the default's own dict instead of a copy is the same aliasing
    bug as above, and this is the one users actually hit — every config
    written before a section existed is missing it.
    """
    from app.config_manager import ConfigManager

    (fake_project / "config.yaml").write_text(
        "hotkey:\n  start_recording_hotkey: ctrl+f5\n", encoding="utf-8"
    )
    before = pristine_defaults["storage"]["models_dir"]

    cm = ConfigManager()
    assert cm.get_setting("hotkey", "start_recording_hotkey") == "ctrl+f5"
    cm.update_user_setting("storage", "models_dir", "/somewhere/else")
    cm.flush_pending_writes()

    assert cm.get_setting("storage", "models_dir") == "/somewhere/else"
    assert pristine_defaults["storage"]["models_dir"] == before, (
        "filling a missing section aliased DEFAULT_CONFIG instead of copying it"
    )


def test_no_section_dict_is_the_same_object_as_the_default(
    fake_project, pristine_defaults
):
    """The aliasing itself, stated as an identity check.

    A second ConfigManager reading a fresh ``config.yaml`` *should*
    see the first one's writes — it reads them back off disk. So the
    inheritance that proves the bug is not observable that way, and
    asserting it is would be asserting the wrong thing. The invariant
    that actually holds, and that the bug breaks, is identity: a
    manager must never hold the default's own dicts.
    """
    from app.config_manager import ConfigManager

    cm = ConfigManager()  # fresh install — seeds straight from defaults
    for section, value in cm.config.items():
        if isinstance(value, dict):
            assert value is not pristine_defaults.get(section), (
                f"section {section!r} is the DEFAULT_CONFIG dict itself"
            )
