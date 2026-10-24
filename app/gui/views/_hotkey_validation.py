"""Hotkey validation for the Qt Settings view, translated.

The vocabulary and the rules are in :mod:`app.hotkey_rules`, which has no Qt
and is shared with the Electron interface. This module only turns each
refusal into a sentence in the current language, so the view and its tests
keep the API they have always had.
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional

from app.hotkey_rules import (
    Issue,
    check_all,
    check_hotkey,
    find_conflicts,
    is_push_to_talk_solo_key,
    ptt_solo_keys_for_platform as _ptt_solo_keys_for_platform,
)
from app.language import tr_format

__all__ = [
    "find_hotkey_conflicts",
    "is_push_to_talk_solo_key",
    "validate_all",
    "validate_hotkey",
]


def _say(issue: Issue) -> str:
    return tr_format("HotkeyValidation", issue.template, *issue.args)


def validate_hotkey(
    text: str,
    *,
    allow_empty: bool = False,
    push_to_talk: bool = False,
    platform: str | None = None,
) -> Optional[str]:
    """``None`` for a usable binding, otherwise a sentence saying why not."""
    issue = check_hotkey(
        text, allow_empty=allow_empty, push_to_talk=push_to_talk, platform=platform
    )
    return _say(issue) if issue else None


def find_hotkey_conflicts(
    start: str, stop: str, cancel: str, *, mode: str = "two_keys"
) -> Dict[str, str]:
    """Cross-field conflicts as ``field -> sentence``."""
    return {
        field: _say(issue)
        for field, issue in find_conflicts(start, stop, cancel, mode=mode).items()
    }


def validate_all(
    *,
    start: str,
    stop: str,
    cancel: str,
    mode: str = "two_keys",
    platform: str | None = None,
) -> Mapping[str, str]:
    """One check over the three fields as ``field -> sentence``."""
    return {
        field: _say(issue)
        for field, issue in check_all(
            start=start, stop=stop, cancel=cancel, mode=mode, platform=platform
        ).items()
    }
