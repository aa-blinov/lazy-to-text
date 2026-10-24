"""The macOS microphone-permission probe the runtime's permissions handler uses."""

from __future__ import annotations

import sys
import types

import pytest

from app import mic_check


def _fake_avfoundation(monkeypatch, status):
    class _Device:
        requested = []

        @staticmethod
        def authorizationStatusForMediaType_(_media):
            return status

        @classmethod
        def requestAccessForMediaType_completionHandler_(cls, media, handler):
            cls.requested.append(media)
            handler(True)

    module = types.SimpleNamespace(AVCaptureDevice=_Device, AVMediaTypeAudio="soun")
    monkeypatch.setitem(sys.modules, "AVFoundation", module)
    monkeypatch.setattr(sys, "platform", "darwin")
    return _Device


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_other_platforms_have_no_gate(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    assert mic_check.microphone_authorization_status() is None
    assert mic_check.request_microphone_access() is False
    assert mic_check.open_microphone_settings() is False


@pytest.mark.parametrize("code,name", [(0, "not_determined"), (1, "restricted"),
                                       (2, "denied"), (3, "authorized")])
def test_the_status_codes_are_named(monkeypatch, code, name):
    _fake_avfoundation(monkeypatch, code)
    assert mic_check.microphone_authorization_status() == name


def test_only_a_first_time_request_shows_the_prompt(monkeypatch):
    device = _fake_avfoundation(monkeypatch, 2)
    assert mic_check.request_microphone_access() is False
    assert device.requested == []

    device = _fake_avfoundation(monkeypatch, 0)
    seen = []
    assert mic_check.request_microphone_access(seen.append) is True
    assert seen == [True]
