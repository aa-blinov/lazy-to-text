"""Tests for the ShortcutsView."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QLineEdit, QPushButton


def _start_edit(view) -> QLineEdit:
    return view.findChild(QLineEdit, "StartHotkeyEdit")


def _stop_edit(view) -> QLineEdit:
    return view.findChild(QLineEdit, "StopHotkeyEdit")


def _auto_paste_cb(view) -> QCheckBox:
    return view.findChild(QCheckBox, "AutoPasteCheckbox")


def _reset_hotkeys_btn(view) -> QPushButton:
    return view.findChild(QPushButton, "ResetHotkeysButton")


def _clear_hf_token_btn(view) -> QPushButton:
    return view.findChild(QPushButton, "ClearHfTokenButton")


def test_shortcuts_view_has_expected_widgets(qtbot):
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    assert _start_edit(view) is not None
    assert _stop_edit(view) is not None
    assert _auto_paste_cb(view) is not None
    # Each card now owns its own reset/clear button — the global
    # footer button is gone.
    assert _reset_hotkeys_btn(view) is not None
    assert _clear_hf_token_btn(view) is not None


def test_global_reset_footer_button_no_longer_exists(qtbot):
    """Per-card buttons replaced the catch-all 'Reset to defaults'
    footer; that button used to mislead by only resetting hotkeys
    + auto_paste. Asserting it's gone keeps the migration honest."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    assert view.findChild(QPushButton, "ResetShortcutsButton") is None


def test_save_button_no_longer_exists(qtbot):
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    save_btn = view.findChild(QPushButton, "SaveShortcutsButton")
    assert save_btn is None


def test_set_values_prefills_fields(qtbot):
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    view.set_values(
        start_hotkey="ctrl+alt+r",
        stop_hotkey="ctrl+alt+s",
        auto_paste=True,
    )

    assert _start_edit(view).text() == "ctrl+alt+r"
    assert _stop_edit(view).text() == "ctrl+alt+s"
    assert _auto_paste_cb(view).isChecked() is True


def test_set_values_handles_false_auto_paste(qtbot):
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    view.set_values(
        start_hotkey="ctrl+f2",
        stop_hotkey="ctrl+f3",
        auto_paste=False,
    )

    assert _auto_paste_cb(view).isChecked() is False


def test_getters_return_current_values(qtbot):
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    view.set_values(
        start_hotkey="ctrl+f2",
        stop_hotkey="ctrl+f3",
        auto_paste=True,
    )

    assert view.start_hotkey() == "ctrl+f2"
    assert view.stop_hotkey() == "ctrl+f3"
    assert view.auto_paste() is True


def test_set_values_does_not_emit_save_requested(qtbot):
    """Programmatic prefill must not trigger persistence."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    emissions: list[dict] = []
    view.save_requested.connect(emissions.append)

    view.set_values(
        start_hotkey="ctrl+f2",
        stop_hotkey="ctrl+f3",
        auto_paste=True,
    )

    assert emissions == []


def test_editing_start_hotkey_emits_save_requested_on_finish(qtbot):
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()

    view.set_values(start_hotkey="ctrl+f2", stop_hotkey="ctrl+f3", auto_paste=False)

    start = _start_edit(view)
    start.clear()
    qtbot.keyClicks(start, "ctrl+alt+1")

    with qtbot.waitSignal(view.save_requested, timeout=1000) as blocker:
        # editingFinished fires on focus loss / Enter
        start.editingFinished.emit()

    payload = blocker.args[0]
    assert payload["start_hotkey"] == "ctrl+alt+1"
    assert payload["stop_hotkey"] == "ctrl+f3"
    assert payload["auto_paste"] is False


def test_editing_stop_hotkey_emits_save_requested(qtbot):
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()

    view.set_values(start_hotkey="ctrl+f2", stop_hotkey="ctrl+f3", auto_paste=False)

    stop = _stop_edit(view)
    stop.clear()
    qtbot.keyClicks(stop, "ctrl+alt+2")

    with qtbot.waitSignal(view.save_requested, timeout=1000) as blocker:
        stop.editingFinished.emit()

    assert blocker.args[0]["stop_hotkey"] == "ctrl+alt+2"


def test_toggling_auto_paste_emits_save_requested_immediately(qtbot):
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()

    view.set_values(start_hotkey="ctrl+f2", stop_hotkey="ctrl+f3", auto_paste=False)

    cb = _auto_paste_cb(view)
    with qtbot.waitSignal(view.save_requested, timeout=1000) as blocker:
        cb.setChecked(True)

    assert blocker.args[0]["auto_paste"] is True


def test_reset_hotkeys_button_emits_hotkeys_reset_requested(qtbot):
    """Per-card 'Reset to defaults' inside the Hotkeys card emits
    the new card-scoped signal. Replaces the global ``reset_requested``
    that used to also reset auto-paste."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()

    btn = _reset_hotkeys_btn(view)
    with qtbot.waitSignal(view.hotkeys_reset_requested, timeout=1000):
        qtbot.mouseClick(btn, Qt.LeftButton)


def test_clear_hf_token_button_emits_request(qtbot):
    """The HF card's 'Clear token' button emits its own signal —
    controller wipes the token from config + env."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()

    btn = _clear_hf_token_btn(view)
    with qtbot.waitSignal(view.hf_token_reset_requested, timeout=1000):
        qtbot.mouseClick(btn, Qt.LeftButton)


# ---- Microphone permission banner -----------------------------------------


def test_mic_banner_hides_after_grant(qtbot, monkeypatch):
    """Granting microphone access mid-session should clear the banner
    and notify the controller that runtime resources may be refreshed
    in-process."""
    import app.gui.views.shortcuts_view as shortcuts_module
    from app.gui.views.shortcuts_view import ShortcutsView

    status = {"value": "not_determined"}
    monkeypatch.setattr(shortcuts_module, "microphone_authorization_status", lambda: status["value"])

    view = ShortcutsView()
    qtbot.addWidget(view)

    assert view._mic_state == "not_determined"
    assert view._mic_banner_button.text() == "Grant access"

    status["value"] = "authorized"
    with qtbot.waitSignal(view.mac_permissions_changed, timeout=1000):
        view._on_mic_request_completed(True)

    qtbot.waitUntil(
        lambda: view._mic_state == "hidden"
        and not view._mic_banner.isVisible(),
        timeout=1000,
    )


def test_accessibility_banner_hides_after_grant(qtbot, monkeypatch):
    import app.gui.views.shortcuts_view as shortcuts_module
    from app.gui.views.shortcuts_view import ShortcutsView

    trusted = {"value": False}
    monkeypatch.setattr(
        shortcuts_module,
        "is_accessibility_trusted",
        lambda: trusted["value"],
    )

    view = ShortcutsView()
    qtbot.addWidget(view)

    assert view._accessibility_state == "untrusted"
    assert view._accessibility_banner_button.text() == "Grant access"

    trusted["value"] = True
    with qtbot.waitSignal(view.mac_permissions_changed, timeout=1000):
        view._refresh_accessibility_banner()

    assert view._accessibility_state == "hidden"
    assert view._accessibility_banner.isVisible() is False


def test_accessibility_banner_falls_back_to_settings_when_request_stays_denied(
    qtbot, monkeypatch
):
    import app.gui.views.shortcuts_view as shortcuts_module
    from app.gui.views.shortcuts_view import ShortcutsView

    opened = []
    monkeypatch.setattr(
        shortcuts_module,
        "is_accessibility_trusted",
        lambda: False,
    )
    monkeypatch.setattr(
        shortcuts_module,
        "request_accessibility_access",
        lambda: False,
    )
    monkeypatch.setattr(
        shortcuts_module,
        "open_accessibility_settings",
        lambda: opened.append(True) or True,
    )

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()

    qtbot.mouseClick(view._accessibility_banner_button, Qt.LeftButton)

    assert opened == [True]


def test_accessibility_banner_hides_for_modifier_push_to_talk_mode(
    qtbot, monkeypatch
):
    import app.gui.views.shortcuts_view as shortcuts_module
    from app.gui.views.shortcuts_view import ShortcutsView

    monkeypatch.setattr(
        shortcuts_module,
        "is_accessibility_trusted",
        lambda: False,
    )

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.set_values(
        start_hotkey="ctrl+f8",
        stop_hotkey="ctrl+f9",
        auto_paste=False,
        mode="push_to_talk",
        push_to_talk_key="right_cmd",
    )
    view.refresh_macos_permission_banners()

    assert view._accessibility_state == "hidden"
    assert view._accessibility_banner.isVisible() is False


def test_post_event_banner_tracks_auto_paste_permission(qtbot, monkeypatch):
    import app.gui.views.shortcuts_view as shortcuts_module
    from app.gui.views.shortcuts_view import ShortcutsView

    monkeypatch.setattr(
        shortcuts_module,
        "is_post_event_access_trusted",
        lambda: False,
    )

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()
    view.set_values(
        start_hotkey="ctrl+f2",
        stop_hotkey="ctrl+f3",
        auto_paste=True,
    )
    view.refresh_macos_permission_banners()

    assert view._post_event_state == "untrusted"
    assert view._post_event_banner_button.text() == "Allow auto-paste access"
    assert view._post_event_banner.isVisible() is True

    view.set_values(
        start_hotkey="ctrl+f2",
        stop_hotkey="ctrl+f3",
        auto_paste=False,
    )
    view.refresh_macos_permission_banners()

    assert view._post_event_state == "hidden"
    assert view._post_event_banner.isVisible() is False


def test_post_event_banner_falls_back_to_settings_when_request_stays_denied(
    qtbot, monkeypatch
):
    import app.gui.views.shortcuts_view as shortcuts_module
    from app.gui.views.shortcuts_view import ShortcutsView

    opened = []
    monkeypatch.setattr(
        shortcuts_module,
        "is_post_event_access_trusted",
        lambda: False,
    )
    monkeypatch.setattr(
        shortcuts_module,
        "request_post_event_access",
        lambda: False,
    )
    monkeypatch.setattr(
        shortcuts_module,
        "open_accessibility_settings",
        lambda: opened.append(True) or True,
    )

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()
    view.set_values(
        start_hotkey="ctrl+f2",
        stop_hotkey="ctrl+f3",
        auto_paste=True,
    )
    view.refresh_macos_permission_banners()

    qtbot.mouseClick(view._post_event_banner_button, Qt.LeftButton)

    assert opened == [True]


def test_post_event_banner_stays_hidden_when_probe_is_unavailable(
    qtbot, monkeypatch
):
    import app.gui.views.shortcuts_view as shortcuts_module
    from app.gui.views.shortcuts_view import ShortcutsView

    monkeypatch.setattr(
        shortcuts_module,
        "is_post_event_access_trusted",
        lambda: None,
    )

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()
    view.set_values(
        start_hotkey="ctrl+f2",
        stop_hotkey="ctrl+f3",
        auto_paste=True,
    )
    view.refresh_macos_permission_banners()

    assert view._post_event_state == "hidden"
    assert view._post_event_banner.isVisible() is False


# ---- Storage card ----------------------------------------------------------


def _change_storage_btn(view) -> QPushButton:
    return view.findChild(QPushButton, "ChangeStorageButton")


def _reset_storage_btn(view) -> QPushButton:
    return view.findChild(QPushButton, "ResetStorageButton")


def _storage_path_label(view):
    from PySide6.QtWidgets import QLabel

    return view.findChild(QLabel, "StoragePathLabel")


def test_shortcuts_view_has_storage_widgets(qtbot):
    """Settings tab carries a Storage card so the user can move
    downloaded weights off the system drive without editing
    ``config.yaml`` by hand."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    assert _change_storage_btn(view) is not None
    assert _reset_storage_btn(view) is not None
    assert _storage_path_label(view) is not None


def test_set_storage_path_updates_label_with_path(qtbot):
    """``set_storage_path(path, is_default=False)`` shows the chosen
    directory verbatim — no truncation. The user copy-pastes this
    into Explorer to verify the weights ended up where they expected."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    view.set_storage_path("D:/lazy-to-text-models", is_default=False)
    label = _storage_path_label(view)
    assert "D:/lazy-to-text-models" in label.text()


def test_set_storage_path_marks_default_explicitly(qtbot):
    """When the user hasn't picked a custom path, the label still
    shows the resolved default path AND a ``(default)`` marker so it's
    clear nothing is overridden."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    view.set_storage_path("C:/project/models", is_default=True)
    text = _storage_path_label(view).text()
    assert "C:/project/models" in text
    assert "default" in text.lower()


def _storage_size_label(view):
    from PySide6.QtWidgets import QLabel
    return view.findChild(QLabel, "StorageSizeLabel")


def _open_storage_btn(view):
    from PySide6.QtWidgets import QPushButton
    return view.findChild(QPushButton, "OpenStorageButton")


def test_storage_card_has_size_label(qtbot):
    """The Storage card carries a label that shows total bytes used
    by downloaded weights — without it the user has no idea how much
    disk the cache eats and whether they should move it to a bigger
    drive.  Starts blank until the controller computes the size."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    label = _storage_size_label(view)
    assert label is not None


def test_set_storage_size_updates_label(qtbot):
    """``set_storage_size(text)`` writes the human-readable size into
    the label.  The controller does the formatting (bytes → ``"3.4 GB"``)
    so the view stays free of locale rules."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    view.set_storage_size("3.4 GB")
    text = _storage_size_label(view).text()
    assert "3.4 GB" in text


def test_storage_card_has_open_folder_button(qtbot):
    """A direct-to-Explorer button is the user's escape hatch — once
    they know how much is used, they want to inspect / clean up."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    btn = _open_storage_btn(view)
    assert btn is not None


def test_open_folder_button_emits_request(qtbot):
    """Same delegation pattern as Change/Reset — the view emits, the
    controller actually opens the folder (so we can mock subprocess
    in tests)."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()

    btn = _open_storage_btn(view)
    with qtbot.waitSignal(view.storage_open_requested, timeout=1000):
        qtbot.mouseClick(btn, Qt.LeftButton)


def test_change_storage_button_emits_request(qtbot):
    """The view delegates path-picking to the controller — the
    button itself just emits a request signal and the controller
    opens the QFileDialog. Keeps the view free of dialogs and easier
    to test."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()

    btn = _change_storage_btn(view)
    with qtbot.waitSignal(view.storage_path_change_requested, timeout=1000):
        qtbot.mouseClick(btn, Qt.LeftButton)


def test_reset_storage_button_emits_request(qtbot):
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()

    # Reset is disabled until the user has actually customised the
    # path — set a non-default before clicking.
    view.set_storage_path("D:/elsewhere", is_default=False)

    btn = _reset_storage_btn(view)
    with qtbot.waitSignal(view.storage_reset_requested, timeout=1000):
        qtbot.mouseClick(btn, Qt.LeftButton)


def test_reset_storage_button_disabled_when_already_on_default(qtbot):
    """No point clicking Reset when there's nothing to reset to —
    fire the disabled state from ``set_storage_path`` so the user
    doesn't get an info dialog saying 'already on default'."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    view.set_storage_path("C:/project/models", is_default=True)
    assert not _reset_storage_btn(view).isEnabled()

    view.set_storage_path("D:/elsewhere", is_default=False)
    assert _reset_storage_btn(view).isEnabled()


# ---- Hugging Face card -----------------------------------------------------


def _hf_token_edit(view):
    return view.findChild(QLineEdit, "HfTokenEdit")


def test_shortcuts_view_has_hf_token_widgets(qtbot):
    """Settings tab carries a Hugging Face card with a token field
    so users don't have to set ``HF_TOKEN`` env var by hand for
    GigaAM long-form."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    assert _hf_token_edit(view) is not None


def test_hf_token_field_is_password_masked(qtbot):
    """Tokens are sensitive — render as bullets, not plaintext, so
    the value isn't shoulder-surfed during a screenshare."""
    from PySide6.QtWidgets import QLineEdit
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    assert _hf_token_edit(view).echoMode() == QLineEdit.Password


def test_set_hf_token_prefills_field(qtbot):
    """The view's own setter — used by the controller on init to
    paint the persisted value into the field without firing the
    save signal back."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.set_hf_token("hf_persisted_value")
    assert _hf_token_edit(view).text() == "hf_persisted_value"


def test_hf_token_field_emits_signal_on_edit(qtbot):
    """Edit → focus loss → controller saves. Same auto-save pattern
    as the hotkey fields."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()

    edit = _hf_token_edit(view)
    edit.setText("hf_new_value")

    with qtbot.waitSignal(view.hf_token_changed, timeout=1000) as blocker:
        edit.editingFinished.emit()
    assert blocker.args == ["hf_new_value"]


def test_set_hf_token_does_not_re_emit(qtbot):
    """Programmatic prefill via ``set_hf_token`` must not echo back
    a signal — would cause an infinite save loop on init."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    emissions: list = []
    view.hf_token_changed.connect(emissions.append)
    view.set_hf_token("hf_persisted_value")
    assert emissions == []


# ---- Cancel-recording hotkey -----------------------------------------------


def _cancel_edit(view) -> QLineEdit:
    return view.findChild(QLineEdit, "CancelHotkeyEdit")


def test_shortcuts_view_has_cancel_hotkey_field(qtbot):
    """The Hotkeys card carries a third row for the "discard buffer
    without transcribing" hotkey — the runtime supports it via
    ``StateManager.cancel_active_recording`` but until now it was
    never exposed to the user."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    assert _cancel_edit(view) is not None


def test_set_values_prefills_cancel_hotkey(qtbot):
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.set_values(
        start_hotkey="ctrl+f2",
        stop_hotkey="ctrl+f3",
        auto_paste=True,
        cancel_hotkey="ctrl+f6",
    )
    assert _cancel_edit(view).text() == "ctrl+f6"


def test_cancel_hotkey_returns_via_getter(qtbot):
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.set_values(
        start_hotkey="ctrl+f2",
        stop_hotkey="ctrl+f3",
        auto_paste=True,
        cancel_hotkey="ctrl+shift+x",
    )
    assert view.cancel_hotkey() == "ctrl+shift+x"


def test_save_payload_includes_cancel_hotkey(qtbot):
    """Edits to the cancel field must surface through the same
    ``save_requested`` payload the controller already listens on —
    otherwise a typed value never reaches config."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()

    view.set_values(
        start_hotkey="ctrl+f2",
        stop_hotkey="ctrl+f3",
        auto_paste=False,
        cancel_hotkey="ctrl+f6",
    )

    edit = _cancel_edit(view)
    edit.clear()
    qtbot.keyClicks(edit, "ctrl+alt+x")

    with qtbot.waitSignal(view.save_requested, timeout=1000) as blocker:
        edit.editingFinished.emit()

    assert blocker.args[0]["cancel_hotkey"] == "ctrl+alt+x"


def test_set_values_handles_legacy_callers_without_cancel_kw(qtbot):
    """Callers that still pass only the old three kwargs must keep
    working — controller tests + any external code shouldn't need a
    flag day to upgrade. Cancel field stays empty in that case."""
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.set_values(
        start_hotkey="ctrl+f2",
        stop_hotkey="ctrl+f3",
        auto_paste=True,
    )
    assert _cancel_edit(view).text() == ""


# ---- Permission banner: the button must not starve the paragraph ----
#
# Measured before the fix at text scale 1.75 in a 900px window: the
# microphone banner gave its button 53% of the row, the message wrapped
# into eight lines, and the banner stood 246px tall for one sentence.
# The numbers below are the regression fence for that.


def _banners_in_worst_state(view):
    """Force both macOS banners into their longest state."""
    import app.gui.views.shortcuts_view as shortcuts_module

    shortcuts_module.microphone_authorization_status = lambda: "denied"
    shortcuts_module.is_accessibility_trusted = lambda: False
    view._refresh_mic_banner()
    view._refresh_accessibility_banner()
    view._mic_banner.setVisible(True)
    view._accessibility_banner.setVisible(True)
    return view._mic_banner, view._accessibility_banner


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 1.75])
@pytest.mark.parametrize("size", [(1000, 780), (900, 620)])
def test_permission_banner_button_never_takes_half_the_row(
    qtbot, qapp, monkeypatch, scale, size
):
    """The verb may not outgrow the sentence it belongs to.

    ``_PermissionBanner`` caps the button at half the banner width. The
    cap only exists for a label long enough to want more than that, so
    this test hands the banner a deliberately greedy one — measuring
    the shipped "Open Settings" would pass with the cap deleted, which
    is exactly the kind of green that means nothing.

    The old copy is the honest starting point, but it is only greedy
    where it actually misbehaved — at 1.75 it wanted 53% of a 590px
    row, at 1.0 only 28% of a 690px one. So the label is stretched
    until it is greedy at *every* scale and width under test; otherwise
    the cap would go unexercised at the easy sizes and the test would
    quietly stop testing anything.
    """
    import app.gui.views.shortcuts_view as shortcuts_module
    from app.gui.main_window import MainWindow
    from app.gui.theme import apply_theme, set_text_scale

    monkeypatch.setattr(
        shortcuts_module, "microphone_authorization_status", lambda: "denied"
    )
    monkeypatch.setattr(
        shortcuts_module, "is_accessibility_trusted", lambda: False
    )

    set_text_scale(scale)
    try:
        apply_theme(qapp)
        win = MainWindow()
        qtbot.addWidget(win)
        win.resize(*size)
        win.show()
        win._activate_nav("shortcuts")
        for _ in range(12):
            qtbot.wait(10)

        view = win._views["shortcuts"]
        for banner in _banners_in_worst_state(view):
            banner.setVisible(True)
        for _ in range(12):
            qtbot.wait(10)

        # Grow the label until it wants more than its share, at this
        # scale and this width. Doubling converges in a few steps.
        greedy = "Open Microphone settings"
        for _ in range(6):
            if all(
                b.button.sizeHint().width() > b.width() / 2
                for b in (view._mic_banner, view._accessibility_banner)
            ):
                break
            greedy += " and then some"
            for banner in (view._mic_banner, view._accessibility_banner):
                banner.button.setText(greedy)
            for _ in range(6):
                qtbot.wait(10)

        for banner in (view._mic_banner, view._accessibility_banner):
            assert banner.width() > 0
            # The cap has to actually bind for this to mean anything.
            assert banner.button.sizeHint().width() > banner.width() / 2, (
                f"{banner.objectName()}: the greedy label is not greedy "
                f"anymore — this test is no longer testing the cap"
            )
            share = banner.button.width() / banner.width()
            # 0.5 as a literal, not ``banner._BUTTON_SHARE``: the test
            # pins the policy, so raising the constant to make the
            # assertion vacuous has to fail here rather than pass.
            assert share <= 0.51, (
                f"{banner.objectName()}: button took {share:.0%} of the row"
            )
    finally:
        set_text_scale(1.0)
        apply_theme(qapp)


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 1.75])
@pytest.mark.parametrize("size", [(1000, 780), (900, 620)])
def test_permission_banner_button_label_never_elides(
    qtbot, qapp, monkeypatch, scale, size
):
    """The cap must never actually bind.

    If the button's own width needs more than its share, Qt elides the
    label — which is a clipped control, the one thing the cap is
    supposed to prevent. So the shipped labels have to stay inside the
    share on their own, and this is the test that says so.
    """
    import app.gui.views.shortcuts_view as shortcuts_module
    from app.gui.main_window import MainWindow
    from app.gui.theme import apply_theme, set_text_scale

    monkeypatch.setattr(
        shortcuts_module, "microphone_authorization_status", lambda: "denied"
    )
    monkeypatch.setattr(
        shortcuts_module, "is_accessibility_trusted", lambda: False
    )

    set_text_scale(scale)
    try:
        apply_theme(qapp)
        win = MainWindow()
        qtbot.addWidget(win)
        win.resize(*size)
        win.show()
        win._activate_nav("shortcuts")
        for _ in range(12):
            qtbot.wait(10)

        view = win._views["shortcuts"]
        for banner in _banners_in_worst_state(view):
            banner.setVisible(True)
        for _ in range(12):
            qtbot.wait(10)

        for banner in (view._mic_banner, view._accessibility_banner):
            button = banner.button
            assert button.width() >= button.sizeHint().width(), (
                f"{banner.objectName()}: button {button.width()}px is under "
                f"its own sizeHint {button.sizeHint().width()}px — "
                f"{button.text()!r} is being elided"
            )
    finally:
        set_text_scale(1.0)
        apply_theme(qapp)


def test_permission_banner_labels_stay_short(qtbot, monkeypatch):
    """The paragraph names the System Settings pane, so the button
    does not repeat it. This pins that decision: the labels are verbs,
    not sentences, and a rewrite that pastes the pane back into the
    button fails here rather than at text scale 1.75 in the field."""
    import app.gui.views.shortcuts_view as shortcuts_module
    from app.gui.views.shortcuts_view import ShortcutsView

    monkeypatch.setattr(
        shortcuts_module, "microphone_authorization_status", lambda: "denied"
    )
    monkeypatch.setattr(
        shortcuts_module, "is_accessibility_trusted", lambda: False
    )

    view = ShortcutsView()
    qtbot.addWidget(view)

    for banner in (view._mic_banner, view._accessibility_banner):
        label = banner.button.text()
        assert label, "banner button must carry a verb"
        assert len(label) <= 14, f"{banner.objectName()}: {label!r} is a sentence"
        # The pane path belongs to the paragraph, not the button.
        assert "microphone" not in label.lower()
        assert "hotkey" not in label.lower()
        # …and the paragraph still has to name where to go.
        assert "System Settings" in banner.text.text()


def test_device_popup_widens_on_open_not_in_the_layout(qtbot):
    """The 420px device popup must not be a static minimum.

    ``view()`` is a child widget of the combo, so a width constraint on
    it counts against the combo's own geometry and walks up through the
    form row and the card into the page — measured, that put a 15px
    horizontal overflow on the Settings view at text scale 1.75.

    So the width is applied when the popup opens. Both halves matter:
    wide enough to show a long device name, and out of the layout the
    rest of the time.
    """
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.show()
    for _ in range(8):
        qtbot.wait(10)

    combo = view._device_combo
    assert combo.view().minimumWidth() == 0, (
        "the popup reserves width while closed — that is the overflow"
    )

    combo.showPopup()
    for _ in range(8):
        qtbot.wait(10)
    assert combo.view().minimumWidth() == 420
    combo.hidePopup()


@pytest.mark.parametrize("scale", [1.0, 1.75])
def test_settings_view_does_not_overflow_at_the_window_floor(
    qtbot, qapp, explain_width, scale
):
    """900×620 is the pinned floor; below it the Settings view gains a
    horizontal scrollbar. This pins the floor from the side that broke
    — a text-scaled settings page, which is why the floor is 900 and
    not the 650×532 Qt claims.
    """
    from PySide6.QtWidgets import QScrollArea
    from app.gui.main_window import MainWindow
    from app.gui.theme import apply_theme, set_text_scale

    set_text_scale(scale)
    try:
        apply_theme(qapp)
        win = MainWindow()
        qtbot.addWidget(win)
        win.resize(900, 620)
        win.show()
        win._activate_nav("shortcuts")
        for _ in range(12):
            qtbot.wait(10)

        for sa in win.findChildren(QScrollArea):
            if not sa.isVisible():
                continue  # hidden pages are not laid out
            over = sa.horizontalScrollBar().maximum()
            assert over == 0, (
                f"settings view overflows by {over}px at the floor"
                # The whole ladder, not just the size: this overflow
                # appears on Windows CI and not on a Mac, and "2px" is
                # not something anyone can act on.
                f" (widest child: {explain_width(sa.widget())})"
            )
    finally:
        set_text_scale(1.0)
        apply_theme(qapp)


# ---- what a screen reader actually hears ----------------------------------
#
# Visible labels and accessible names are two different surfaces, and
# the Settings view is where they had drifted apart: a visible
# "Grant access" that is fine because the banner above it names the
# permission, and an accessible name that is "Grant access" for two
# different permissions.


def _a11y_name(widget) -> str:
    from PySide6.QtGui import QAccessible

    iface = QAccessible.queryAccessibleInterface(widget)
    return iface.text(QAccessible.Text.Name) if iface else ""


def test_hf_token_field_has_an_accessible_name(qtbot):
    """The audit's finding.

    The card's caption is a plain QLabel, not a buddy, so Qt resolves
    no name for the field at all — and the placeholder is not a name
    either. "hf_…" says what a value looks like, never what the field
    is for. A sighted user reads the caption above; without this they
    get "edit, hf_…" and stop there.
    """
    from PySide6.QtWidgets import QLineEdit

    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    field = view.findChild(QLineEdit, "HfTokenEdit")
    assert field is not None

    name = _a11y_name(field)
    assert name, "the token field resolves to no accessible name at all"
    assert "token" in name.lower()
    # And it must not be the placeholder doing the work.
    assert field.placeholderText() not in (name, "")


def test_token_field_description_says_why_it_is_asked_for(qtbot):
    from PySide6.QtGui import QAccessible
    from PySide6.QtWidgets import QLineEdit

    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    field = view.findChild(QLineEdit, "HfTokenEdit")
    iface = QAccessible.queryAccessibleInterface(field)
    desc = iface.text(QAccessible.Text.Description)
    assert "gated" in desc.lower(), (
        f"the description should say when the token is needed: {desc!r}"
    )


def test_the_two_grant_buttons_are_not_announced_identically(qtbot, monkeypatch):
    """Two permissions, two buttons, one shared visible label.

    The visible "Grant access" is right — the banner text above each one
    says which permission it is, and the button is capped at half the
    banner width. The accessible name has no such neighbour to lean on,
    so two buttons both announced as "Grant access, button" left a
    screen-reader user no way to tell the microphone from Accessibility.

    Both permissions are forced into the state that puts a verb on the
    button. ``_PermissionBanner`` builds its button with an empty label
    and only fills it when the banner is restated, which happens for
    ``not_determined`` and ``denied`` and not for ``authorized`` or for
    the non-macOS ``None``. So this assertion used to be a statement
    about the machine it ran on: it passed on a Mac where the terminal
    had never been asked about the microphone, and failed on both CI
    runners — where the microphone question has a different answer, and
    on Windows there is no TCC gate at all.
    """
    from app.gui.views import shortcuts_view as module
    from app.gui.views.shortcuts_view import ShortcutsView

    monkeypatch.setattr(
        module, "microphone_authorization_status", lambda: "not_determined"
    )
    monkeypatch.setattr(module, "is_accessibility_trusted", lambda: False)

    view = ShortcutsView()
    qtbot.addWidget(view)

    mic = view.findChild(QPushButton, "MicrophoneActionButton")
    access = view.findChild(QPushButton, "AccessibilityActionButton")
    assert mic is not None and access is not None

    mic_name = _a11y_name(mic)
    access_name = _a11y_name(access)
    assert mic_name != access_name, (
        f"both permission buttons announce as {mic_name!r}"
    )
    assert "microphone" in mic_name.lower()
    assert "accessibility" in access_name.lower()
    # The visible label is unchanged — it is not wrong on screen.
    assert mic.text() == access.text() == "Grant access"


def test_the_permission_buttons_say_where_they_lead(qtbot):
    """Neither button grants anything itself — both open a settings page."""
    from PySide6.QtGui import QAccessible

    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    for name in ("MicrophoneActionButton", "AccessibilityActionButton"):
        btn = view.findChild(QPushButton, name)
        iface = QAccessible.queryAccessibleInterface(btn)
        desc = iface.text(QAccessible.Text.Description)
        assert "settings" in desc.lower(), f"{name}: {desc!r}"


def test_storage_controls_name_their_object(qtbot):
    """"Change…" and "Open folder" name a gesture, not a target.

    The Storage card titles them, so a sighted user is covered. The
    accessible names put the two missing words back.
    """
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)

    change = _a11y_name(view.findChild(QPushButton, "ChangeStorageButton"))
    open_folder = _a11y_name(view.findChild(QPushButton, "OpenStorageButton"))
    reset = _a11y_name(view.findChild(QPushButton, "ResetStorageButton"))
    for name in (change, open_folder, reset):
        assert "storage" in name.lower(), name


def test_the_two_reset_buttons_are_worded_the_same(qtbot):
    """"Reset to default" and "Reset to defaults" on one screen.

    The Hotkeys card said the plural and the Storage card the singular,
    for the same kind of action. Nothing distinguished them but a
    plural, which reads as a typo rather than a rule.
    """
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    hotkeys = view.findChild(QPushButton, "ResetHotkeysButton")
    storage = view.findChild(QPushButton, "ResetStorageButton")
    assert hotkeys.text() == storage.text()
