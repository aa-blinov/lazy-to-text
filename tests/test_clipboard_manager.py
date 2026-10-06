import logging


def _manager():
    from app.clipboard_manager import ClipboardManager

    manager = ClipboardManager.__new__(ClipboardManager)
    manager.logger = logging.getLogger("test.clipboard")
    manager.key_simulation_delay = 0.0
    manager.auto_paste = True
    manager.preserve_clipboard = False
    return manager


def test_send_paste_combo_prefers_accessibility_path_on_macos(monkeypatch):
    import app.clipboard_manager as clipboard_module

    manager = _manager()
    calls = []
    monkeypatch.setattr(clipboard_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        manager,
        "_send_mac_accessibility_key_sequence",
        lambda steps, label: calls.append((label, steps)) or True,
    )
    monkeypatch.setattr(
        manager,
        "_send_mac_keystroke_with_cmd",
        lambda key_code, label: calls.append(("quartz", key_code, label)),
    )

    manager._send_paste_combo()

    assert calls == [
        (
            "Cmd+V",
            [
                (0, clipboard_module._MAC_KEYCODE_LEFT_COMMAND, True),
                (ord("v"), clipboard_module._MAC_KEYCODE_V, True),
                (ord("v"), clipboard_module._MAC_KEYCODE_V, False),
                (0, clipboard_module._MAC_KEYCODE_LEFT_COMMAND, False),
            ],
        )
    ]


def test_send_paste_combo_falls_back_to_quartz_on_macos(monkeypatch):
    import app.clipboard_manager as clipboard_module

    manager = _manager()
    calls = []
    monkeypatch.setattr(clipboard_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        manager,
        "_send_mac_accessibility_key_sequence",
        lambda steps, label: False,
    )
    monkeypatch.setattr(
        manager,
        "_send_mac_keystroke_with_cmd",
        lambda key_code, label: calls.append((key_code, label)),
    )

    manager._send_paste_combo()

    assert calls == [(clipboard_module._MAC_KEYCODE_V, "Cmd+V")]


def test_send_enter_prefers_accessibility_path_on_macos(monkeypatch):
    import app.clipboard_manager as clipboard_module

    manager = _manager()
    calls = []
    monkeypatch.setattr(clipboard_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        manager,
        "_send_mac_accessibility_key_sequence",
        lambda steps, label: calls.append((label, steps)) or True,
    )
    monkeypatch.setattr(
        manager,
        "_send_mac_keystroke",
        lambda key_code, label: calls.append(("quartz", key_code, label)),
    )

    manager._send_enter()

    assert calls == [
        (
            "Enter",
            [
                (0x0D, clipboard_module._MAC_KEYCODE_RETURN, True),
                (0x0D, clipboard_module._MAC_KEYCODE_RETURN, False),
            ],
        )
    ]


# --- what the log is allowed to claim ---------------------------------------


def test_a_paste_that_could_not_be_sent_is_not_called_a_paste(
    monkeypatch, caplog
):
    """The message used to say "Auto-pasted" whatever happened.

    ``_send_paste_combo`` returned nothing and swallowed every failure,
    ``execute_auto_paste`` then returned ``True`` unconditionally, and
    the log said the text was pasted. With Accessibility revoked macOS
    drops the keystroke silently, so the user was told it worked.

    ``True`` still does not mean "the target app pasted" — nothing in
    the platform API can confirm that — so the message claims the
    keystroke and nothing more.
    """
    manager = _manager()
    monkeypatch.setattr(manager, "copy_text", lambda _t: True)
    monkeypatch.setattr(manager, "_send_paste_combo", lambda: False)

    with caplog.at_level(logging.INFO, logger="test.clipboard"):
        sent = manager.execute_auto_paste("hello", preserve_clipboard=False)

    assert sent is False
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Auto-pasted" not in text, "a dropped keystroke must not be called a paste"
    assert "not sent" in text, "the user needs to be told to paste manually"


def test_a_sent_keystroke_claims_the_keystroke_only(monkeypatch, caplog):
    manager = _manager()
    monkeypatch.setattr(manager, "copy_text", lambda _t: True)
    monkeypatch.setattr(manager, "_send_paste_combo", lambda: True)

    with caplog.at_level(logging.INFO, logger="test.clipboard"):
        sent = manager.execute_auto_paste("hello", preserve_clipboard=False)

    assert sent is True
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Paste keystroke sent" in text
    assert "Auto-pasted" not in text, (
        "sending the keystroke is not proof the app pasted"
    )


def test_the_enter_path_reports_the_same_way(monkeypatch, caplog):
    manager = _manager()
    monkeypatch.setattr(manager, "_send_enter", lambda: False)

    with caplog.at_level(logging.INFO, logger="test.clipboard"):
        assert manager.send_enter_key() is False

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Text submitted" not in text
    assert "was not sent" in text


def test_send_paste_combo_returns_whether_it_sent(monkeypatch):
    """Every branch has to answer, not just the macOS one."""
    import app.clipboard_manager as clipboard_module

    manager = _manager()
    monkeypatch.setattr(clipboard_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        manager,
        "_send_mac_accessibility_key_sequence",
        lambda steps, label: False,
    )
    monkeypatch.setattr(
        manager,
        "_send_mac_keystroke_with_cmd",
        lambda key_code, label: True,
    )
    assert manager._send_paste_combo() is True, "the fallback counts"

    monkeypatch.setattr(
        manager,
        "_send_mac_keystroke_with_cmd",
        lambda key_code, label: False,
    )
    assert manager._send_paste_combo() is False, "and so does its failure"
