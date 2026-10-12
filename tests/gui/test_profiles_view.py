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
    from app.gui.views.profiles_view import ProfilesView

    v = ProfilesView()
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

    assert view._profile_combo.currentData() == "letters"
    assert view._name_edit.text() == "Letters"
    assert view._model_edit.text() == "gpt-5.4-mini"


def test_re_reading_the_list_keeps_the_open_profile(view):
    """The controller re-pushes the list after every change, so this
    fires constantly. It must not yank the user back to the default
    while they are on some other profile."""
    view.set_profiles([WORK, LETTERS], "letters")

    view.set_profiles([WORK, LETTERS], "letters")

    assert view._profile_combo.currentData() == "letters"
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
    assert "default profile" in view._empty_state.text()


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
    view.profile_changed.connect(announced.append)
    view.set_profiles([WORK], "work")

    view._model_edit.setText("qwen3:14b")

    assert announced == []


def test_committing_a_field_saves_the_whole_profile(view, qtbot):
    """The full profile rather than a diff: a controller merging field by
    field is how a field the editor stopped showing survives into the
    next save."""
    view.set_profiles([WORK], "work")

    with qtbot.waitSignal(view.profile_changed, timeout=1000):
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
    view.profile_changed.connect(emitted.append)

    view.set_profiles([WORK, LETTERS], "letters")

    assert emitted == []


# ---- switching the default ---------------------------------------------


def test_the_default_button_is_ticked_for_the_active_profile(view):
    view.set_profiles([WORK, LETTERS], "letters")

    assert view._active_radio.isChecked() is True
    assert "The default" in view._active_radio.text()


def test_the_default_button_is_unticked_for_the_others(view):
    view.set_profiles([WORK, LETTERS], "letters")
    view._profile_combo.setCurrentIndex(0)

    assert view._active_radio.isChecked() is False
    assert "Make this the default" in view._active_radio.text()


def test_ticking_it_announces_the_new_default(view, qtbot):
    view.set_profiles([WORK, LETTERS], "letters")
    view._profile_combo.setCurrentIndex(0)

    with qtbot.waitSignal(view.active_changed, timeout=1000):
        view._active_radio.setChecked(True)

    assert view._active_radio.isChecked() is True
    assert "The default" in view._active_radio.text()


def test_unticking_the_default_announces_nothing(view):
    """Only one profile can be the default. Unticking the button for the
    profile that already is would mean "no default", which the app has no
    way to represent."""
    announced: list = []
    view.active_changed.connect(announced.append)
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