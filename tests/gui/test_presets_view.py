"""The Profiles screen: which profile is open, and what it saves.

The view is a form, so most of what matters is not visual — it is that
it cannot describe a profile that is not there. A screen showing the
previous profile's values while the picker says otherwise is how a name
or a key ends up saved onto the wrong profile, and nothing on screen
would show it.
"""

from __future__ import annotations

import pytest

WORK = {
    "id": "work",
    "name": "Work",
    "provider": "ollama",
    "model": "qwen3:8b",
    "base_url": "http://127.0.0.1:11434",
    "api_key": "",
    "mode": "clean",
    "custom_prompt": "",
}
LETTERS = {
    "id": "letters",
    "name": "Letters",
    "provider": "openai",
    "model": "gpt-5.4-mini",
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-secret",
    "mode": "formal",
    "custom_prompt": "",
}


@pytest.fixture
def view(qtbot):
    from app.gui.views.presets_view import PresetsView

    v = PresetsView()
    qtbot.addWidget(v)
    v.resize(1000, 700)
    v.show()
    return v


# ---- which profile is open --------------------------------------------


def test_the_screen_opens_on_the_active_profile(view):
    """Not on whichever row happens to be first, and not on whatever it
    had open before. Both were wrong: measured here as the picker showing
    "Work" with "Letters" in the fields after a reload with Letters
    active."""
    view.set_profiles([WORK, LETTERS], "letters")

    assert view._preset_combo.currentData() == "letters"
    assert view._name_edit.text() == "Letters"
    assert view._model_edit.text() == "gpt-5.4-mini"


def test_re_reading_the_list_keeps_the_open_profile(view):
    """The controller re-pushes the list after every change, so this
    fires constantly. It must not yank the user back to the default
    while they are on some other profile."""
    view.set_profiles([WORK, LETTERS], "letters")

    view.set_profiles([WORK, LETTERS], "letters")

    assert view._preset_combo.currentData() == "letters"
    assert view._name_edit.text() == "Letters"


def test_the_key_field_never_renders_its_value(view):
    """The one widget that must not show a secret on a shoulder.

    ``displayText()`` is not the check — it returns the real string even
    in Password mode; the masking happens at paint. What is worth
    pinning is the echo mode, and that the value still reaches the save.
    """
    from PySide6.QtWidgets import QLineEdit

    view.set_profiles([LETTERS], "letters")

    assert view._key_edit.echoMode() == QLineEdit.Password
    assert view.values()["api_key"] == "sk-secret"


# ---- nothing to edit ----------------------------------------------------


def test_an_empty_list_clears_the_editor(view):
    """The alternative is an editor full of the previous profile's
    values, which would then be saved onto whatever gets created next."""
    view.set_profiles([WORK], "work")
    assert view._name_edit.text() == "Work"

    view.set_profiles([], "")

    assert view._name_edit.text() == ""
    assert view.values() is None


def test_the_last_profile_cannot_be_deleted(view):
    """Deleting it leaves no way to post-process and no way back."""
    view.set_profiles([WORK], "work")

    assert view._delete_btn.isEnabled() is False


def test_deleting_is_possible_once_there_is_a_second(view):
    view.set_profiles([WORK, LETTERS], "work")

    assert view._delete_btn.isEnabled() is True


def test_an_empty_list_says_so_instead_of_showing_a_blank_column(view):
    view.set_profiles([], "")

    assert view._empty_state.isVisibleTo(view) is True
    assert "No presets left" in view._empty_state.text()


# ---- what the screen says about privacy --------------------------------


def test_a_loopback_profile_says_the_text_stays(view):
    view.set_profiles([WORK], "work")

    assert "does not leave" in view._privacy_hint.text()


def test_a_cloud_profile_says_the_text_is_sent(view):
    view.set_profiles([LETTERS], "letters")

    hint = view._privacy_hint.text()
    assert "remote server" in hint
    assert "key" in hint


def test_a_blank_server_is_read_against_the_chosen_provider(view):
    """An empty endpoint means the provider's default, so the warning has
    to be computed from that default — not from an empty string, which
    would read as local and say nothing about a cloud provider."""
    cloud = {**LETTERS, "base_url": ""}
    view.set_profiles([cloud], "letters")

    assert "remote server" in view._privacy_hint.text()


def test_the_warning_follows_a_typed_address(view):
    view.set_profiles([WORK], "work")
    assert "does not leave" in view._privacy_hint.text()

    view._base_edit.setText("https://api.openai.com/v1")

    assert "remote server" in view._privacy_hint.text()


# ---- what it saves -----------------------------------------------------


def test_a_typed_field_does_not_save_on_every_keystroke(view):
    """``textChanged`` would spawn a config write — on its own thread —
    per character, for a value that is not finished yet. Every other
    auto-saving field in this app waits for focus-out and so does this
    one."""
    announced: list = []
    view.preset_changed.connect(announced.append)
    view.set_profiles([WORK], "work")

    view._model_edit.setText("qwen3:14b")

    assert announced == []


def test_committing_a_field_saves_the_whole_profile(view, qtbot):
    """The full profile rather than a diff: a controller merging field by
    field is how a field the editor stopped showing survives into the
    next save."""
    view.set_profiles([WORK], "work")

    with qtbot.waitSignal(view.preset_changed, timeout=1000):
        view._model_edit.setText("qwen3:14b")
        view._model_edit.editingFinished.emit()

    payload = view.values()
    assert payload["model"] == "qwen3:14b"
    assert payload["name"] == "Work"
    assert payload["provider"] == "ollama"
    assert payload["id"] == "work"


def test_the_custom_prompt_is_part_of_what_saves(view):
    view.set_profiles([WORK], "work")

    view._prompt_edit.setPlainText("Only fix commas.")

    assert view.values()["custom_prompt"] == "Only fix commas."


def test_nothing_is_saved_while_the_screen_is_being_filled(view):
    """A load is not an edit. If it were, opening the screen would
    rewrite every profile."""
    emitted: list = []
    view.preset_changed.connect(emitted.append)

    view.set_profiles([WORK, LETTERS], "letters")

    assert emitted == []


# ---- switching the default ---------------------------------------------


def test_the_default_button_is_ticked_for_the_active_profile(view):
    view.set_profiles([WORK, LETTERS], "letters")

    assert view._active_radio.isChecked() is True
    assert "In use by default" in view._active_radio.text()


def test_the_default_button_is_unticked_for_the_others(view):
    view.set_profiles([WORK, LETTERS], "letters")
    view._preset_combo.setCurrentIndex(0)

    assert view._active_radio.isChecked() is False
    assert "Use this one by default" in view._active_radio.text()


def test_ticking_it_announces_the_new_default(view, qtbot):
    view.set_profiles([WORK, LETTERS], "letters")
    view._preset_combo.setCurrentIndex(0)

    with qtbot.waitSignal(view.preset_activated, timeout=1000):
        view._active_radio.setChecked(True)

    assert view._active_radio.isChecked() is True
    assert "In use by default" in view._active_radio.text()


def test_unticking_the_default_announces_nothing(view):
    """Only one profile can be the default. Unticking the button for the
    profile that already is would mean "no default", which the app has no
    way to represent."""
    announced: list = []
    view.preset_activated.connect(announced.append)
    view.set_profiles([WORK, LETTERS], "work")

    view._active_radio.setChecked(False)

    assert announced == []


# ---- the address field -------------------------------------------------


def test_changing_provider_rewrites_an_untouched_default(view):
    view.set_profiles([WORK], "work")

    index = view._provider_combo.findData("openai")
    view._provider_combo.setCurrentIndex(index)

    assert view._base_edit.text() == "https://api.openai.com/v1"


def test_changing_provider_leaves_a_hand_typed_address_alone(view):
    """Silent replacement of somebody's endpoint with a cloud default is
    the same bug as overwriting a saved model name."""
    view.set_profiles([{**WORK, "base_url": "https://my-box.local:8080/v1"}], "work")

    index = view._provider_combo.findData("openai")
    view._provider_combo.setCurrentIndex(index)

    assert view._base_edit.text() == "https://my-box.local:8080/v1"


def test_the_prompt_editor_says_what_still_happens(view):
    """Somebody writing their own prompt has to know the two promises are
    not theirs to cancel, or they will promise a translation in here and
    be surprised."""
    view.set_profiles([WORK], "work")

    hint = view._prompt_hint.text()
    assert "digits" in hint
    assert "language" in hint

# ---- the provider semantics, moved here from the Settings card ---------
#
# These five fields used to be editable in Settings and every test below
# used to live there. The behaviour did not change; the editor did. They
# are kept rather than dropped, because a green suite is supposed to
# mean the same thing it meant before the move.


@pytest.mark.parametrize("provider_id", ["openai", "openrouter", "groq"])
def test_a_cloud_preset_says_the_words_are_leaving(view, provider_id):
    """"Local-first" is in the window title. A cloud endpoint makes it
    untrue for whoever picks one, so the screen says so while the choice
    is being made rather than after.

    Three of them, deliberately not OpenAI alone: a card that warned for
    OpenAI and stayed quiet for Groq would be worse than no warning.
    """
    index = view._provider_combo.findData(provider_id)
    view._provider_combo.setCurrentIndex(index)

    hint = view._privacy_hint.text()
    assert "remote server" in hint
    assert "text is sent" in hint


def test_a_local_preset_raises_no_alarm(view):
    view.set_profiles([WORK], "work")

    hint = view._privacy_hint.text()
    assert "remote" not in hint
    assert "does not leave" in hint


def test_a_hand_written_loopback_endpoint_still_counts_as_local(view):
    """The address decides, not the picklist. Somebody pointing a custom
    entry back at their own machine must not be told their words are
    leaving it.

    Loopback and nothing else — ``is_local_url`` means *this machine*,
    not *a machine of yours*. A LAN hostname is somebody else's box and
    says so.
    """
    view.set_profiles([{**WORK, "provider": "custom",
                        "base_url": "http://127.0.0.1:8080/v1"}], "work")

    assert "remote server" not in view._privacy_hint.text()
    assert "does not leave" in view._privacy_hint.text()


def test_a_lan_address_is_still_a_remote_machine(view):
    """The counterpart, and the reason the first test is not a licence to
    treat any private-looking address as local."""
    view.set_profiles([{**WORK, "provider": "custom",
                        "base_url": "http://192.168.1.50:11434/v1"}], "work")

    assert "remote server" in view._privacy_hint.text()


def test_choosing_custom_leaves_the_address_alone(view):
    """Custom stands for an address typed by hand and has no default to
    move to — rewriting one would be overwriting the user's own."""
    view.set_profiles([WORK], "work")

    index = view._provider_combo.findData("custom")
    view._provider_combo.setCurrentIndex(index)

    assert view._base_edit.text() == "http://127.0.0.1:11434"


def test_switching_between_named_presets_carries_the_address(view):
    view.set_profiles([WORK], "work")
    before = view._base_edit.text()

    index = view._provider_combo.findData("openai")
    view._provider_combo.setCurrentIndex(index)

    assert view._base_edit.text() != before
    assert view._base_edit.text() == "https://api.openai.com/v1"


def test_a_provider_this_build_does_not_know_lands_on_custom(view):
    """Named by a newer build, or typed into the config by hand. Landing
    on Ollama instead would show a preset claiming the model runs on this
    machine and then post to somebody else's server."""
    view.set_profiles(
        [{**WORK, "provider": "gemini-cli",
          "base_url": "https://gemini.example/v1"}],
        "work",
    )

    assert view._provider_combo.currentData() == "custom"
    assert view._base_edit.text() == "https://gemini.example/v1"


def test_the_mode_picker_explains_what_the_mode_would_do(view):
    """A dropdown of three labels is a guess. Each mode's description is
    what tells the user which one they want."""
    from app.llm import mode_by_id

    index = view._mode_combo.findData("formal")
    view._mode_combo.setCurrentIndex(index)

    chosen = mode_by_id(view._mode_combo.currentData())
    assert view._mode_combo.currentText() == chosen.label


def test_the_mode_picker_offers_no_off(view):
    """The screen has no checkbox — the switch is in Settings, above
    every preset — so a second "Off" here would mean nothing at all.
    Measured with the switch on, an "Off" entry said the text was
    pasted exactly as recognised, stored ``mode: clean``, and sent the
    clean-up prompt anyway."""
    from app.llm import MODES

    combo = view._mode_combo
    labels = [combo.itemText(i) for i in range(combo.count())]

    assert labels == [mode.label for mode in MODES]
    assert "Off" not in labels


def test_the_clear_button_only_offers_to_discard_a_key_that_exists(view):
    """A red button that cannot lose anything is noise, and the field is
    empty on a fresh install."""
    view.set_profiles([WORK], "work")

    assert view._clear_key_btn.isEnabled() is False

    view.set_profiles([LETTERS], "letters")
    assert view._clear_key_btn.isEnabled() is True


def test_clearing_the_key_announces_which_preset(view, qtbot):
    """The key belongs to a preset, so the write has to name the one the
    button is under rather than whichever happens to be active."""
    # LETTERS, not WORK: the button is disabled when there is no key to
    # discard, and WORK has none.
    view.set_profiles([WORK, LETTERS], "letters")

    with qtbot.waitSignal(view.preset_key_reset_requested, timeout=1000) as block:
        view._clear_key_btn.click()

    assert block.args == ["letters"]

    assert view._key_edit.text() == ""
    assert view.values()["api_key"] == ""


# ---- layout containers are not surfaces ------------------------------------
#
# Both of these are one-line guards on properties that are invisible in
# the source and obvious on screen. The stylesheet paints every bare
# QWidget the window ground, so a QWidget that exists only to line two
# controls up in a row paints a rectangle of bg_primary inside whatever
# card holds it — which is how a darker panel appeared under the API key
# field with nothing in the code to account for it.


def test_the_key_row_does_not_paint_a_slab_behind_itself(qapp):
    from app.gui.views.presets_view import PresetsView

    view = PresetsView()
    qapp.processEvents()

    assert view._key_edit.parentWidget().property("role") == "plain"


def test_the_button_row_is_not_a_slab_either(qapp):
    from app.gui.views.presets_view import PresetsView

    view = PresetsView()
    qapp.processEvents()

    assert view._new_btn.parentWidget().property("role") == "plain"


def test_the_action_buttons_are_farther_apart_than_their_own_corner_radius(qapp):
    """An 8px gap between 8px-radius corners reads as touching.

    At the vertical centre the straight edges are 8px apart, but the
    corners eat the rest of it — measured on a card wide enough that the
    buttons were each 375px, which is what the complaint was about.
    """
    from app.gui.theme import TOKENS
    from app.gui.views.presets_view import PresetsView

    view = PresetsView()
    view.resize(1360, 700)
    view.show()
    qapp.processEvents()

    buttons = [view._new_btn, view._duplicate_btn, view._delete_btn]
    layout = buttons[0].parentWidget().layout()
    assert layout.spacing() >= TOKENS.radius["sm"] * 2

    for left, right in zip(buttons, buttons[1:]):
        gap = right.geometry().left() - left.geometry().right() - 1
        assert gap == layout.spacing()


# ---- speed controls and the switch's home ------------------------------


def test_the_switch_sits_in_the_settings_card_and_nothing_folds(view):
    """The checkbox belongs to the model settings, not a card of its own,
    and there is no button hiding the preset picker."""
    from PySide6.QtWidgets import QCheckBox, QPushButton

    assert view._llm_enabled_cb.parentWidget() is view._provider_combo.parentWidget()
    assert view.findChild(QPushButton, "PresetVariantsToggle") is None
    assert view._variants_card.isVisible()
    assert view._name_edit.isVisible()
    assert len(view.findChildren(QCheckBox)) == 1


def test_speed_controls_load_and_save(view, qtbot):
    profile = dict(WORK, reasoning_effort="low", max_tokens=200, timeout_s=75)
    view.set_profiles([profile], "work")

    assert view._effort_combo.currentData() == "low"
    assert view._max_tokens_spin.value() == 200
    assert view._timeout_spin.value() == 75
    assert view.values()["timeout_s"] == 75

    with qtbot.waitSignal(view.preset_changed) as sig:
        view._timeout_spin.setValue(120)
    assert sig.args[0]["timeout_s"] == 120
    assert sig.args[0]["reasoning_effort"] == "low"
    assert sig.args[0]["max_tokens"] == 200


def test_old_profiles_show_the_defaults(view):
    view.set_profiles([WORK], "work")

    assert view._effort_combo.currentData() == ""
    assert view._max_tokens_spin.value() == 0
    assert view._timeout_spin.value() == 20
