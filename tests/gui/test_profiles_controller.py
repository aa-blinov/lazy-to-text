"""The controller side of profiles: what gets written, and when.

Two rules carry this file. A profile change must reach **both**
representations — the list the Profiles screen edits and the flat keys
Settings reads — or the next activation discards half of the edit from
the other screen. And an override from the Transcribe strip must reach
**neither**: it is a per-dictation choice, and persisting it would
change every later dictation while the label says it was for one.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


class FakeConfig:
    """Minimal stand-in for ConfigManager, as in the controller suite."""

    def __init__(self, initial: Optional[Dict[str, Dict[str, Any]]] = None):
        self._data: Dict[str, Dict[str, Any]] = {
            section: dict(values) for section, values in (initial or {}).items()
        }
        self.writes: List[Tuple[str, str, Any]] = []

    def get_setting(self, section: str, key: str) -> Any:
        return self._data.get(section, {}).get(key)

    def get_section(self, section: str) -> Dict[str, Any]:
        return dict(self._data.get(section, {}))

    def update_user_setting(self, section: str, key: str, value: Any) -> None:
        self._data.setdefault(section, {})[key] = value
        self.writes.append((section, key, value))


class FakeStateManager:
    """Just the two methods the controller reaches for."""

    def __init__(self) -> None:
        self.override = ""
        self.calls: List[str] = []

    def profile_override_id(self) -> str:
        return self.override

    def set_profile_override(self, profile_id: str = "") -> None:
        self.override = profile_id
        self.calls.append(profile_id)


class FakeRecording:
    """A recording protocol out of the box.

    ``AppController`` connects half a dozen signals on whatever it is
    handed, so a hand-rolled double has to implement all of them to be
    useful — which is why the suite's other recording tests use a
    ``MagicMock`` and only pin the one attribute under test.
    """

    def __init__(self, state_manager=None) -> None:
        from unittest.mock import MagicMock

        mock = MagicMock()
        mock.state_manager = state_manager
        self._mock = mock

    def __getattr__(self, name):
        return getattr(self._mock, name)


ON = {
    "enabled": True,
    "provider": "ollama",
    "model": "qwen3:8b",
    "base_url": "http://127.0.0.1:11434",
    "api_key": "",
    "mode": "clean",
}


def _build(qtbot, llm: dict, state_manager=None):
    """A controller on a real MainWindow, as the suite does elsewhere."""
    from app.gui.controllers.app_controller import AppController
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    config = FakeConfig({"llm": dict(llm)})
    controller = AppController(
        config=config,
        window=window,
        recording=FakeRecording(state_manager),
    )
    return controller, config, window


# ---- the first profile is the settings you already have ----------------


def test_the_first_profile_is_the_existing_settings(qtbot):
    """Not a blank profile. Making somebody re-enter a working provider
    and key to start using a feature for editing their settings is
    backwards."""
    controller, config, _window = _build(
        qtbot, {**ON, "api_key": "sk-existing"}
    )

    controller._on_profile_create_requested()

    stored = config.get_setting("llm", "profiles")
    assert len(stored) == 1
    assert stored[0]["api_key"] == "sk-existing"
    assert stored[0]["model"] == "qwen3:8b"


def test_creating_a_profile_also_moves_the_flat_keys(qtbot):
    """Settings reads the flat keys, so a list that disagrees with them
    is two truths.

    ``active_profile`` is deliberately left empty on this first write.
    There is only one profile, so the id would name nothing the reader
    cannot already see, and writing it would put a redundant key into
    every file the moment somebody opens the screen once.
    """
    controller, config, _window = _build(qtbot, dict(ON))

    controller._on_profile_create_requested()

    assert config.get_setting("llm", "model") == "qwen3:8b"
    assert ("llm", "active_profile") not in [
        (s, k) for s, k, _v in config.writes
    ]


def test_the_second_profile_leaves_the_first_alone(qtbot):
    controller, config, _window = _build(qtbot, dict(ON))
    controller._on_profile_create_requested()

    controller._on_profile_create_requested()

    stored = config.get_setting("llm", "profiles")
    assert len(stored) == 2
    assert stored[0]["model"] == "qwen3:8b"
    # A new profile starts from the existing one so the server is not
    # empty, and gets its own id.
    assert stored[1]["id"] != stored[0]["id"]
    assert stored[1]["model"] == "qwen3:8b"


# ---- editing ------------------------------------------------------------


def test_editing_a_profile_writes_the_whole_profile(qtbot):
    controller, config, _window = _build(qtbot, dict(ON))
    controller._on_profile_create_requested()
    profile_id = config.get_setting("llm", "profiles")[0]["id"]

    controller._on_profile_changed({
        "id": profile_id,
        "name": "Work",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5.4-mini",
        "api_key": "sk-new",
        "mode": "formal",
        "custom_prompt": "",
    })

    stored = config.get_setting("llm", "profiles")[0]
    assert stored["provider"] == "openai"
    assert stored["mode"] == "formal"
    # And the flat keys follow, because Settings shows those.
    assert config.get_setting("llm", "provider") == "openai"
    assert config.get_setting("llm", "api_key") == "sk-new"


def test_a_settings_edit_reaches_the_profile_too(qtbot):
    """Otherwise the edit is overwritten by the next activation, from the
    other screen, with nothing saying so."""
    controller, config, _window = _build(qtbot, dict(ON))
    controller._on_profile_create_requested()
    controller._on_profile_active_changed(
        config.get_setting("llm", "profiles")[0]["id"]
    )

    # Through the signal, not by calling the handler: the mirror is a
    # second connection to the same signal, and calling one handler by
    # hand skips the wiring that is the whole point.
    _window.shortcuts_view.llm_changed.emit({"model": "qwen3:14b"})

    stored = config.get_setting("llm", "profiles")[0]
    assert stored["model"] == "qwen3:14b"


def test_a_settings_edit_writes_nothing_when_there_is_no_list(qtbot):
    """Before the Profiles screen has ever been opened the flat keys are
    the whole truth, and there is nothing to mirror into."""
    controller, config, window = _build(qtbot, dict(ON))

    window.shortcuts_view.llm_changed.emit({"model": "qwen3:14b"})

    assert config.get_setting("llm", "model") == "qwen3:14b"
    assert config.get_setting("llm", "profiles") is None


def test_only_ticking_the_master_switch_writes_no_profile(qtbot):
    """The switch is the app's, above every profile. Mirroring it would
    make two profiles disagree about whether the step runs at all."""
    controller, config, window = _build(qtbot, dict(ON))
    controller._on_profile_create_requested()
    controller._on_profile_active_changed(
        config.get_setting("llm", "profiles")[0]["id"]
    )
    config.writes.clear()

    window.shortcuts_view.llm_changed.emit({"enabled": False})

    assert not any(key == "profiles" for _s, key, _v in config.writes)


# ---- the default --------------------------------------------------------


def test_activating_a_profile_moves_the_flat_keys(qtbot):
    controller, config, _window = _build(qtbot, dict(ON))
    controller._on_profile_create_requested()
    controller._on_profile_create_requested()
    ids = [p["id"] for p in config.get_setting("llm", "profiles")]
    controller._on_profile_active_changed(ids[0])

    assert config.get_setting("llm", "active_profile") == ids[0]


def test_activating_an_unknown_profile_writes_nothing(qtbot):
    controller, config, _window = _build(qtbot, dict(ON))
    controller._on_profile_create_requested()
    config.writes.clear()

    controller._on_profile_active_changed("nope")

    assert config.writes == []


# ---- duplicate and delete ------------------------------------------------


def test_a_duplicate_carries_the_credential(qtbot):
    """A copy that silently lost its key fails at request time with a
    401, which reads like the key was revoked."""
    controller, config, _window = _build(qtbot, {**ON, "api_key": "sk-work"})
    controller._on_profile_create_requested()
    source = config.get_setting("llm", "profiles")[0]["id"]

    controller._on_profile_duplicate_requested(source)

    stored = config.get_setting("llm", "profiles")
    assert len(stored) == 2
    assert stored[1]["api_key"] == "sk-work"
    assert stored[1]["id"] != source


def test_deleting_the_last_profile_is_refused(qtbot):
    """No way to post-process afterwards, and no way back."""
    controller, config, _window = _build(qtbot, dict(ON))
    controller._on_profile_create_requested()
    only = config.get_setting("llm", "profiles")[0]["id"]

    controller._on_profile_delete_requested(only)

    assert len(config.get_setting("llm", "profiles")) == 1


def test_deleting_the_active_profile_moves_the_default(qtbot):
    """The default cannot name something that no longer exists. Left
    stale, the next profile added could inherit it."""
    controller, config, _window = _build(qtbot, dict(ON))
    controller._on_profile_create_requested()
    controller._on_profile_create_requested()
    ids = [p["id"] for p in config.get_setting("llm", "profiles")]
    controller._on_profile_active_changed(ids[1])

    controller._on_profile_delete_requested(ids[1])

    remaining = config.get_setting("llm", "profiles")
    assert len(remaining) == 1
    assert config.get_setting("llm", "active_profile") == remaining[0]["id"]


def test_deleting_a_non_active_profile_leaves_the_default(qtbot):
    controller, config, _window = _build(qtbot, dict(ON))
    controller._on_profile_create_requested()
    controller._on_profile_create_requested()
    ids = [p["id"] for p in config.get_setting("llm", "profiles")]
    controller._on_profile_active_changed(ids[0])

    controller._on_profile_delete_requested(ids[1])

    assert config.get_setting("llm", "active_profile") == ids[0]


# ---- the override -------------------------------------------------------


def test_the_override_reaches_the_state_manager_and_not_the_file(qtbot):
    """It is read on the pipeline thread, not when the button was
    pressed, so it lives on the manager — and never in the config."""
    state = FakeStateManager()
    controller, config, _window = _build(qtbot, dict(ON), state_manager=state)
    controller._on_profile_create_requested()
    config.writes.clear()

    controller._on_profile_override_changed("letters")

    assert state.override == "letters"
    assert config.writes == []


def test_clearing_the_override_reaches_the_manager(qtbot):
    state = FakeStateManager()
    controller, config, _window = _build(qtbot, dict(ON), state_manager=state)
    controller._on_profile_override_changed("letters")

    controller._on_profile_override_changed("")

    assert state.override == ""


def test_the_strip_shows_the_override_the_manager_is_holding(qtbot):
    state = FakeStateManager()
    controller, config, window = _build(qtbot, dict(ON), state_manager=state)
    controller._on_profile_create_requested()
    controller._on_profile_create_requested()
    ids = [p["id"] for p in config.get_setting("llm", "profiles")]
    state.override = ids[1]

    controller._refresh_profiles_ui()

    strip = window.transcribe_view
    assert strip._profile_override_check.isChecked() is True
    assert strip._profile_combo.currentData() == ids[1]

def test_a_settings_edit_does_not_delete_the_other_profiles(qtbot):
    """The mirror writes the profile it edited, not a one-element list
    containing it.

    This is the worst bug the feature had: with two profiles, editing a
    single field in Settings replaced the whole list with the edited
    profile alone, deleting the other one and its API key with nothing on
    screen saying so. The one-profile test beside it passed throughout.
    """
    controller, config, window = _build(qtbot, {**ON, "api_key": "sk-first"})
    controller._on_profile_create_requested()
    controller._on_profile_create_requested()
    before = config.get_setting("llm", "profiles")
    assert len(before) == 2
    other = dict(before[1])
    other_id = other["id"]

    window.shortcuts_view.llm_changed.emit({"model": "qwen3:14b"})

    after = config.get_setting("llm", "profiles")
    assert len(after) == 2, after
    survivors = next(p for p in after if p["id"] == other_id)
    assert survivors == other


def test_a_settings_edit_mirrors_before_any_default_is_named(qtbot):
    """The case the empty ``active_profile`` window creates.

    The first profile is created without an ``active_profile`` — there
    is only one and its id would name nothing — so a Settings edit
    arriving in that window has to resolve the active profile the same
    way everything else does. Reading the raw field found no match and
    the edit silently stopped at the flat keys, so the next activation
    put it back.
    """
    controller, config, window = _build(qtbot, dict(ON))
    controller._on_profile_create_requested()
    assert config.get_setting("llm", "active_profile") in (None, "")

    window.shortcuts_view.llm_changed.emit({"model": "qwen3:14b"})

    stored = config.get_setting("llm", "profiles")[0]
    assert stored["model"] == "qwen3:14b"
