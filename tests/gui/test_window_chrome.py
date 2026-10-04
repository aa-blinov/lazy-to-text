"""Tests for the Windows title-bar request.

This is the one code path in the app that has never executed: it is
hard-gated behind ``sys.platform == "win32"``, and the project has never
produced a Windows build it could run under CI. Every branch below is
monkeypatched into existence rather than skipped, because the branch
that matters most is the one that *fails* — a DWM call that throws
during startup costs a blank window, and a light title bar costs
nothing but a seam.

The shape mirrors ``tests/gui/test_theme.py``'s high-contrast tests:
the same three-way guard, the same refusal to let a platform probe
break startup, tested the same way.
"""

import pytest

from app.gui import window_chrome


class _FakeWidget:
    """Stands in for the QWidget whose native handle we ask for."""

    def __init__(self, hwnd=0x1234, raises=None):
        self._hwnd = hwnd
        self._raises = raises
        self.calls = 0

    def winId(self):  # noqa: N802 (Qt naming)
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._hwnd


class _FakeDwm:
    """``DwmSetWindowAttribute`` that accepts the listed attributes.

    An attribute id that is not in ``accepts`` returns a non-zero
    ``HRESULT``, which is how Windows says "I do not know this one" —
    not an error, and not something to raise over.

    The attribute arrives as a ``wintypes.DWORD``, so it is read with
    ``.value`` rather than ``int()``: on this LP64 host ``c_ulong`` is
    8 bytes wide and ``int()`` on it raises, where the 4-byte Windows
    ``DWORD`` would not. The attribute id is a Windows detail and the
    test should not depend on how wide a C long is here.
    """

    def __init__(self, accepts, boom=False):
        self.accepts = set(accepts)
        self.boom = boom
        self.seen = []

    def DwmSetWindowAttribute(self, hwnd, attribute, value, size):  # noqa: N802
        self.seen.append(int(attribute.value))
        if self.boom:
            raise OSError("no dwmapi here")
        return 0 if int(attribute.value) in self.accepts else -2147024809


class _FakeUxTheme:
    def __init__(self, boom=False):
        self.boom = boom
        self.themes = []

    def SetWindowTheme(self, hwnd, theme, subtitle):  # noqa: N802
        if self.boom:
            raise OSError("no uxtheme here")
        self.themes.append(theme)
        return 0


def _windll(monkeypatch, dwm, uxtheme=None):
    """Install fake ``ctypes.windll`` — it only exists on Windows."""
    import ctypes

    uxtheme = uxtheme if uxtheme is not None else _FakeUxTheme()
    monkeypatch.setattr(
        ctypes,
        "windll",
        type("W", (), {"dwmapi": dwm, "uxtheme": uxtheme})(),
        raising=False,
    )
    return uxtheme


# ---- the guard that keeps this off macOS -----------------------------------


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_is_a_no_op_off_windows(monkeypatch, platform):
    """macOS draws its own unified toolbar from the app's material, and
    there is nothing to ask for. This must not even import ctypes."""
    monkeypatch.setattr(window_chrome.sys, "platform", platform)
    widget = _FakeWidget()
    assert window_chrome.apply_dark_title_bar(widget) is False
    assert widget.calls == 0, "must not ask for a native handle it will not use"


def test_is_a_no_op_without_a_widget(monkeypatch):
    """A None widget is a caller mistake, not a reason to raise."""
    monkeypatch.setattr(window_chrome.sys, "platform", "win32")
    assert window_chrome.apply_dark_title_bar(None) is False


# ---- the attribute negotiation ---------------------------------------------


def test_stops_at_the_first_attribute_windows_accepts(monkeypatch):
    """Windows 11 22H2 takes 20. Trying 19 afterwards would be a second
    API call for a question already answered."""
    monkeypatch.setattr(window_chrome.sys, "platform", "win32")
    dwm = _FakeDwm(accepts={20, 19})
    _windll(monkeypatch, dwm)

    assert window_chrome.apply_dark_title_bar(_FakeWidget()) is True
    assert dwm.seen == [20]


def test_falls_through_to_the_older_attribute_on_windows_10(monkeypatch):
    """This is the case the loop exists for: Windows 10 rejects 20 and
    takes 19. A single hard-coded id would leave a pale strip on every
    Windows 10 machine."""
    monkeypatch.setattr(window_chrome.sys, "platform", "win32")
    dwm = _FakeDwm(accepts={19})
    uxtheme = _windll(monkeypatch, dwm)

    assert window_chrome.apply_dark_title_bar(_FakeWidget()) is True
    assert dwm.seen == [20, 19]
    assert uxtheme.themes == [], "the documented attribute worked; no fallback needed"


def test_falls_back_to_the_undocumented_theme_on_a_pre_1809_build(monkeypatch):
    """Neither attribute is known. The long-standing ``DarkMode_Explorer``
    window theme still darkens the bar, so the app tries it and reports
    False — the return means "DWM accepted", and it did not."""
    monkeypatch.setattr(window_chrome.sys, "platform", "win32")
    dwm = _FakeDwm(accepts=set())
    uxtheme = _windll(monkeypatch, dwm)

    assert window_chrome.apply_dark_title_bar(_FakeWidget()) is False
    assert dwm.seen == [20, 19]
    assert uxtheme.themes == ["DarkMode_Explorer"]


def test_skips_a_window_with_no_native_handle(monkeypatch):
    """``winId()`` returning 0 means there is no window to style yet.
    Calling DWM with a null HWND is at best wasted work."""
    monkeypatch.setattr(window_chrome.sys, "platform", "win32")
    dwm = _FakeDwm(accepts={20})
    _windll(monkeypatch, dwm)

    assert window_chrome.apply_dark_title_bar(_FakeWidget(hwnd=0)) is False
    assert dwm.seen == []


# ---- the branch that matters: failing without taking the app down ---------


def test_a_dwm_call_that_raises_costs_the_title_bar_and_nothing_else(monkeypatch):
    """The whole point of the blanket ``except``. A missing dwmapi —
    Wine, a stripped container, an API removed in a future Windows —
    must degrade to a light title bar, never to a startup crash."""
    monkeypatch.setattr(window_chrome.sys, "platform", "win32")
    _windll(monkeypatch, _FakeDwm(accepts={20}, boom=True))

    assert window_chrome.apply_dark_title_bar(_FakeWidget()) is False


def test_a_missing_uxtheme_does_not_take_down_the_fallback(monkeypatch):
    """The fallback is the last line of defence. If *it* raises, the
    blanket guard still has to catch it — there is nothing below."""
    monkeypatch.setattr(window_chrome.sys, "platform", "win32")
    _windll(
        monkeypatch,
        _FakeDwm(accepts=set()),
        uxtheme=_FakeUxTheme(boom=True),
    )

    assert window_chrome.apply_dark_title_bar(_FakeWidget()) is False


def test_no_user32_no_dwmapi_at_all_does_not_raise(monkeypatch):
    """``ctypes.windll`` itself missing is the earliest possible failure
    and the same story: cosmetic loss, working app."""
    import ctypes

    monkeypatch.setattr(window_chrome.sys, "platform", "win32")
    monkeypatch.delattr(ctypes, "windll", raising=False)

    assert window_chrome.apply_dark_title_bar(_FakeWidget()) is False


def test_a_widget_that_cannot_hand_over_a_handle_does_not_raise(monkeypatch):
    """``winId()`` can fail on a widget that was never shown. Same rule."""
    monkeypatch.setattr(window_chrome.sys, "platform", "win32")
    _windll(monkeypatch, _FakeDwm(accepts={20}))

    widget = _FakeWidget(raises=RuntimeError("no native window yet"))
    assert window_chrome.apply_dark_title_bar(widget) is False


# ---- the attribute list is the compatibility surface ----------------------


def test_the_attribute_list_leads_with_the_newest_id():
    """Order is the whole mechanism: 20 before 19, newest first. An
    append instead of a prepend would still return True on both, but
    would cost every Windows 11 machine a rejected call per launch."""
    assert window_chrome._dwm_dark_mode_attributes() == (20, 19)
