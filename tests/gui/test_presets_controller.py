"""The controller side of presets: what gets written, and when.

Three rules carry this file.

The first preset is materialised at launch, from the settings the user
already has. Not on request — an empty list with a paragraph explaining
the concept is the interface explaining itself, which is the symptom.

Settings owns the switch and nothing else. Five fields living in two
editors is what made "what a profile is" a question worth asking; the
card now writes one key and never touches the list.

An override from the Transcribe strip reaches **neither** the presets
list nor the active one. It is a per-dictation choice, and persisting it
would change every later dictation while the label said it was for one.
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


def _ids(config) -> List[str]:
    return [p["id"] for p in config.get_setting("llm", "profiles") or []]


# ---- the first preset appears by itself --------------------------------


def test_the_first_preset_is_the_existing_settings(qtbot):
    """Not a blank preset, and not something the user has to ask for.

    The screen used to open on an empty list with a paragraph explaining
    what a preset was, while the one configuration the user actually had
    was not in it.
    """
    _controller, config, _window = _build(qtbot, {**ON, "api_key": "sk-existing"})

    stored = config.get_setting("llm", "profiles")
    assert len(stored) == 1
    assert stored[0]["api_key"] == "sk-existing"
    assert stored[0]["model"] == "qwen3:8b"


def test_the_preset_screen_opens_on_that_first_preset(qtbot):
    _controller, _config, window = _build(qtbot, dict(ON))

    assert window.presets_view._preset_combo.count() == 1
    assert window.presets_view._name_edit.text() == "Default"


def test_an_existing_list_is_left_alone_on_launch(qtbot):
    """A launch is not a reason to rewrite the user's config every time."""
    two = {
        "profiles": [
            {**ON, "id": "work", "name": "Work"},
            {**ON, "id": "letters", "name": "Letters", "provider": "openai"},
        ],
        "active_profile": "letters",
    }
    _controller, config, _window = _build(qtbot, two)
    config.writes.clear()

    _controller._ensure_first_preset()

    assert config.writes == []


def test_new_adds_a_second_preset(qtbot):
    controller, config, _window = _build(qtbot, dict(ON))

    controller._on_preset_create_requested()

    assert len(_ids(config)) == 2


def test_the_new_preset_starts_as_a_copy_of_the_first(qtbot):
    """A new preset almost always differs by a server and a model name,
    and those are the two fields nobody can recall from memory."""
    controller, config, _window = _build(qtbot, {**ON, "api_key": "sk-first"})

    controller._on_preset_create_requested()

    stored = config.get_setting("llm", "profiles")
    assert stored[0] == stored[1] or stored[1]["api_key"] == "sk-first"
    assert stored[1]["id"] != stored[0]["id"]


def test_new_does_not_change_the_default(qtbot):
    controller, config, _window = _build(qtbot, dict(ON))
    before = config.get_setting("llm", "active_profile")

    controller._on_preset_create_requested()

    assert config.get_setting("llm", "active_profile") == before


# ---- Settings owns the switch and nothing else -------------------------


def test_clearing_a_key_clears_that_preset_and_not_another(qtbot):
    """The key belongs to a preset. Clearing whichever happens to be
    active would discard a different credential than the button is
    under."""
    controller, config, _window = _build(qtbot, {**ON, "api_key": "sk-work"})
    controller._on_preset_create_requested()
    config.writes.clear()

    controller._on_preset_key_reset(_ids(config)[1])

    stored = config.get_setting("llm", "profiles")
    assert stored[1]["api_key"] == ""
    assert stored[0]["api_key"] == "sk-work"


def test_clearing_the_active_presets_key_moves_the_flat_key_too(qtbot):
    """The flat keys are what a pre-presets code path reads, so they
    have to stop carrying a credential that is no longer stored."""
    controller, config, _window = _build(qtbot, {**ON, "api_key": "sk-work"})

    controller._on_preset_key_reset(_ids(config)[0])

    assert config.get_setting("llm", "api_key") == ""


# ---- duplicate and delete -----------------------------------------------


def test_a_duplicate_carries_the_credential(qtbot):
    """A copy that silently lost its key fails at request time with a
    401, which reads like the key was revoked."""
    controller, config, _window = _build(qtbot, {**ON, "api_key": "sk-work"})

    controller._on_preset_duplicate_requested(_ids(config)[0])

    stored = config.get_setting("llm", "profiles")
    assert len(stored) == 2
    assert stored[1]["api_key"] == "sk-work"


def test_deleting_the_last_preset_is_refused(qtbot):
    """No way to post-process afterwards, and no way back."""
    controller, config, _window = _build(qtbot, dict(ON))
    only = _ids(config)[0]

    controller._on_preset_delete_requested(only)

    assert len(_ids(config)) == 1


def test_deleting_the_active_preset_moves_the_default(qtbot):
    """The default cannot name something that no longer exists. Left
    stale, the next preset added could inherit it."""
    controller, config, _window = _build(qtbot, dict(ON))
    controller._on_preset_create_requested()
    ids = _ids(config)
    controller._on_preset_activated(ids[1])

    controller._on_preset_delete_requested(ids[1])

    remaining = config.get_setting("llm", "profiles")
    assert len(remaining) == 1
    assert config.get_setting("llm", "active_profile") == remaining[0]["id"]


def test_deleting_a_non_active_preset_leaves_the_default(qtbot):
    controller, config, _window = _build(qtbot, dict(ON))
    controller._on_preset_create_requested()
    ids = _ids(config)
    controller._on_preset_activated(ids[0])

    controller._on_preset_delete_requested(ids[1])

    assert config.get_setting("llm", "active_profile") == ids[0]


def test_activating_an_unknown_preset_writes_nothing(qtbot):
    controller, config, _window = _build(qtbot, dict(ON))
    config.writes.clear()

    controller._on_preset_activated("nope")

    assert config.writes == []


# ---- the override -------------------------------------------------------


def test_the_override_reaches_the_state_manager_and_not_the_file(qtbot):
    """It is read on the pipeline thread, not when the button was
    pressed, so it lives on the manager — and never in the config."""
    state = FakeStateManager()
    controller, config, _window = _build(qtbot, dict(ON), state_manager=state)
    controller._on_preset_create_requested()
    config.writes.clear()

    controller._on_preset_override_changed(_ids(config)[1])

    assert state.override == _ids(config)[1]
    assert config.writes == []


def test_clearing_the_override_reaches_the_manager(qtbot):
    state = FakeStateManager()
    controller, config, _window = _build(qtbot, dict(ON), state_manager=state)
    target = _ids(config)[0]
    controller._on_preset_override_changed(target)

    controller._on_preset_override_changed("")

    assert state.override == ""


def test_the_strip_shows_the_override_the_manager_is_holding(qtbot):
    state = FakeStateManager()
    controller, config, window = _build(qtbot, dict(ON), state_manager=state)
    controller._on_preset_create_requested()
    ids = _ids(config)
    state.override = ids[1]

    controller._refresh_presets_ui()

    strip = window.transcribe_view
    assert strip._preset_override_check.isChecked() is True
    assert strip._preset_combo.currentData() == ids[1]


def test_clearing_the_key_writes_an_empty_string_and_nothing_else(qtbot):
    """Only the key changes. Not the whole preset, and not the flat keys
    of whatever happens to be active.

    Kept from the controller suite, where the clear button used to live:
    the action moved rather than disappearing, so its property moved with
    it. It could not stay there — that suite's controller stub has no
    window, and the handler repaints after writing.
    """
    controller, config, _window = _build(qtbot, {**ON, "api_key": "sk-x"})
    controller._on_preset_create_requested()
    target = _ids(config)[0]
    config.writes.clear()

    controller._on_preset_key_reset(target)

    section, key, value = config.writes[0]
    assert (section, key) == ("llm", "profiles")
    assert value[0]["api_key"] == ""


def test_the_post_processing_switch_lives_on_the_presets_screen(qtbot):
    from PySide6.QtWidgets import QCheckBox

    _controller, _config, window = _build(qtbot, {"profiles": [dict(ON)]})

    assert window.presets_view._llm_enabled_cb is not None
    assert window.shortcuts_view.findChild(QCheckBox, "LlmEnabledCheck") is None


def test_the_switch_stores_only_enabled(qtbot):
    _controller, config, window = _build(qtbot, {"profiles": [dict(ON)]})
    config.writes.clear()

    # A payload with the old card's keys on purpose: the handler has to
    # write the switch and nothing else, whatever else arrives.
    window.presets_view.llm_changed.emit({
        "enabled": False,
        "provider": "openai",
        "api_key": "sk-leaked",
    })

    assert [key for _s, key, _v in config.writes] == ["enabled"]
    assert config.get_setting("llm", "enabled") is False


def test_stored_switch_is_shown_without_being_written_back(qtbot):
    _controller, config, window = _build(qtbot, {"profiles": [dict(ON)]})
    config.writes.clear()

    window.presets_view.set_llm_values({"enabled": True})

    assert window.presets_view._llm_enabled_cb.isChecked() is True
    assert config.writes == []


def test_speed_controls_are_stored_on_the_profile_and_the_flat_keys(qtbot):
    _controller, config, window = _build(qtbot, {"profiles": [dict(ON)]})
    config.writes.clear()

    view = window.presets_view
    view._effort_combo.setCurrentIndex(view._effort_combo.findData("minimal"))
    view._max_tokens_spin.setValue(256)
    view._timeout_spin.setValue(90)

    stored = config.get_setting("llm", "profiles")[0]
    assert (stored["reasoning_effort"], stored["max_tokens"], stored["timeout_s"]) == (
        "minimal", 256, 90)
    # The flat keys are what the dictation pipeline reads for the active one.
    assert config.get_setting("llm", "reasoning_effort") == "minimal"
    assert config.get_setting("llm", "max_tokens") == 256
    assert config.get_setting("llm", "timeout_s") == 90
