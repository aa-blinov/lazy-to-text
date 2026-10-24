"""Hotkey rules that are not about spelling."""

from __future__ import annotations

import pytest

from app import hotkey_rules




# ---- QA-RUNTIME-20: combinations the operating system takes first -----------------


@pytest.mark.parametrize("combo", ["cmd+q", "Command+Q", "cmd+tab", "cmd+space", "ctrl+cmd+q"])
def test_a_combination_macos_reserves_is_refused(combo):
    issue = hotkey_rules.check_hotkey(combo, platform="darwin")
    assert issue is not None and "reserved by the operating system" in issue.template


@pytest.mark.parametrize("combo", ["alt+f4", "alt+tab", "cmd+l"])
def test_a_combination_windows_reserves_is_refused(combo):
    assert hotkey_rules.check_hotkey(combo, platform="win32") is not None


@pytest.mark.parametrize("combo,platform", [
    ("cmd+shift+q", "darwin"), ("ctrl+f8", "darwin"), ("cmd+q", "win32"),
    ("alt+f4", "darwin"), ("ctrl+shift+space", "darwin"),
])
def test_other_combinations_are_not_called_reserved(combo, platform):
    assert hotkey_rules.check_hotkey(combo, platform=platform) is None
