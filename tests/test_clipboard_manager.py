import logging


def _manager():
    from app.clipboard_manager import ClipboardManager

    manager = ClipboardManager.__new__(ClipboardManager)
    manager.logger = logging.getLogger("test.clipboard")
    manager.key_simulation_delay = 0.0
    manager.auto_paste = True
    manager.preserve_clipboard = False
    # Mirrors ``__init__``. ``execute_auto_paste`` clears and sets this,
    # and ``deliver_transcription`` reads it to tell "the text is waiting
    # on the clipboard" from "the text never got there".
    manager.copied_before_paste = False
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


# ---- deliver_transcription: the three-way answer ---------------------------


def _deliver(monkeypatch, *, auto_paste, copy_ok, keystroke_sent,
             copied_before_paste):
    """Drive ``deliver_transcription`` down both paste paths."""
    manager = _manager()
    manager.auto_paste = auto_paste

    def fake_execute(text, preserve):
        manager.copied_before_paste = copied_before_paste and copy_ok
        return keystroke_sent

    monkeypatch.setattr(manager, "execute_auto_paste", fake_execute)
    monkeypatch.setattr(manager, "copy_with_notification", lambda t: copy_ok)
    return manager


def test_deliver_reports_pasted_when_the_keystroke_went_out(monkeypatch):
    manager = _deliver(
        monkeypatch, auto_paste=True, copy_ok=True, keystroke_sent=True,
        copied_before_paste=True,
    )

    assert manager.deliver_transcription("привет") == "pasted"


def test_deliver_reports_copied_when_only_the_clipboard_worked(monkeypatch):
    """The text is on the clipboard and the user has one action left.
    Reporting this as a failure is what told them to give up on a
    dictation that was sitting right there."""
    manager = _deliver(
        monkeypatch, auto_paste=True, copy_ok=True, keystroke_sent=False,
        copied_before_paste=True,
    )

    assert manager.deliver_transcription("привет") == "copied"


def test_deliver_reports_failure_when_nothing_reached_anything(monkeypatch):
    manager = _deliver(
        monkeypatch, auto_paste=True, copy_ok=False, keystroke_sent=False,
        copied_before_paste=False,
    )

    assert manager.deliver_transcription("привет") == "failed"


def test_deliver_reports_failure_when_the_clipboard_itself_refuses(monkeypatch):
    """With auto-paste off, a refused copy is still a refusal — not a
    quiet success."""
    manager = _deliver(
        monkeypatch, auto_paste=False, copy_ok=False, keystroke_sent=False,
        copied_before_paste=False,
    )

    assert manager.deliver_transcription("привет") == "failed"


def test_deliver_copies_without_auto_paste(monkeypatch):
    manager = _deliver(
        monkeypatch, auto_paste=False, copy_ok=True, keystroke_sent=False,
        copied_before_paste=False,
    )

    assert manager.deliver_transcription("привет") == "copied"


def test_deliver_with_auto_enter_never_returns_none(monkeypatch):
    """The auto-enter path used to fall off the end of its branch and
    return ``None`` — a fourth value the docstring never mentioned and
    no caller could render. The user would have seen nothing at all."""
    manager = _manager()
    manager.auto_paste = True

    def failing_execute(text, preserve):
        manager.copied_before_paste = True  # copy landed, keystroke did not
        return False

    monkeypatch.setattr(manager, "execute_auto_paste", failing_execute)

    outcome = manager.deliver_transcription("привет", use_auto_enter=True)

    assert outcome in ("pasted", "copied", "failed")
    assert outcome == "copied"


def test_deliver_with_auto_enter_reports_a_total_failure(monkeypatch):
    manager = _manager()
    manager.auto_paste = True

    def failing_execute(text, preserve):
        manager.copied_before_paste = False
        return False

    monkeypatch.setattr(manager, "execute_auto_paste", failing_execute)

    assert manager.deliver_transcription("привет", use_auto_enter=True) == (
        "failed"
    )


def test_deliver_survives_an_exception(monkeypatch):
    manager = _manager()
    manager.auto_paste = True

    def boom(text, preserve):
        raise RuntimeError("clipboard is on fire")

    monkeypatch.setattr(manager, "execute_auto_paste", boom)

    assert manager.deliver_transcription("привет") == "failed"


def test_paste_combo_matches_the_platform(monkeypatch):
    """The hardcoded "Ctrl+V" was wrong on one of the two platforms
    this ships on."""
    import app.clipboard_manager as clipboard_module
    from app.clipboard_manager import ClipboardManager

    monkeypatch.setattr(clipboard_module.sys, "platform", "darwin")
    assert ClipboardManager.paste_combo() == "Cmd+V"

    monkeypatch.setattr(clipboard_module.sys, "platform", "win32")
    assert ClipboardManager.paste_combo() == "Ctrl+V"
