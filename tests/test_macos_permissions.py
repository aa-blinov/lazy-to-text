"""Tests for the macOS TCC permission probes.

The logic is platform-independent even though the answers are not, so
the probes are exercised by injecting a fake ``Quartz`` module and a
fixed answer from the Accessibility check. That keeps the coverage on
Linux and Windows CI, where the real PyObjC does not exist.

The point of these tests is the shape of ``is_post_event_access_trusted``:
it used to answer by calling the *listen* check and return whatever
that said, while this package's own docstring warned that the two
gates "are not the same and should not be conflated".
"""

from __future__ import annotations

import sys
import types

import pytest

import app.macos_permissions as macos_permissions


@pytest.fixture
def darwin(monkeypatch):
    monkeypatch.setattr(macos_permissions, "_is_darwin", lambda: True)


@pytest.fixture
def quartz(monkeypatch):
    """A fake ``Quartz`` carrying only the post-event preflight."""
    module = types.ModuleType("Quartz")
    state = {"result": False, "raises": False}

    def _preflight():
        if state["raises"]:
            raise RuntimeError("no window server")
        return state["result"]

    module.CGPreflightPostEventAccess = _preflight
    monkeypatch.setitem(sys.modules, "Quartz", module)
    return state


def _listen(monkeypatch, answer):
    monkeypatch.setattr(
        macos_permissions, "is_listen_event_access_trusted", lambda: answer
    )


def test_either_gate_open_is_enough_to_paste(darwin, quartz, monkeypatch):
    """The app has two paste paths; one open gate is enough for one of them."""
    _listen(monkeypatch, False)
    quartz["result"] = True

    assert macos_permissions.is_post_event_access_trusted() is True


def test_both_gates_shut_reports_shut(darwin, quartz, monkeypatch):
    _listen(monkeypatch, False)
    quartz["result"] = False

    assert macos_permissions.is_post_event_access_trusted() is False


def test_the_post_probe_does_not_simply_repeat_the_listen_answer(
    darwin, quartz, monkeypatch
):
    """The regression this file exists for.

    Before, a revoked Accessibility check meant the paste probe said
    "denied" even where the CoreGraphics gate was open — and the two
    gates are distinct enough that Apple ships them separately.
    """
    _listen(monkeypatch, False)
    quartz["result"] = True

    assert macos_permissions.is_listen_event_access_trusted() is False
    assert macos_permissions.is_post_event_access_trusted() is True, (
        "the post-event probe must read the post-event gate"
    )


def test_an_unavailable_coregraphics_probe_falls_back_to_the_listen_answer(
    darwin, monkeypatch
):
    """No ``Quartz`` at all — the Accessibility answer is still useful."""
    monkeypatch.setitem(sys.modules, "Quartz", types.ModuleType("Quartz"))
    _listen(monkeypatch, True)

    assert macos_permissions.is_post_event_access_trusted() is True


def test_a_probe_that_raises_is_treated_as_unknown_not_shut(
    darwin, quartz, monkeypatch
):
    _listen(monkeypatch, True)
    quartz["raises"] = True

    assert macos_permissions.is_post_event_access_trusted() is True, (
        "a broken probe must not overrule a granted one"
    )


def test_nothing_available_anywhere_is_unknown(darwin, monkeypatch):
    monkeypatch.setitem(sys.modules, "Quartz", types.ModuleType("Quartz"))
    _listen(monkeypatch, None)

    assert macos_permissions.is_post_event_access_trusted() is None


def test_off_darwin_the_probe_answers_nothing(monkeypatch):
    monkeypatch.setattr(macos_permissions, "_is_darwin", lambda: False)
    assert macos_permissions.is_post_event_access_trusted() is None
