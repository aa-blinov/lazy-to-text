"""The hotkey vocabulary and the rules a binding has to satisfy, without Qt.

Both interfaces validate a typed or captured binding with the same rules,
so the rules live here and neither interface carries a copy. A problem is
reported as an :class:`Issue`: the English source sentence with its ``%1``
placeholders, plus the values that fill them. Each interface translates the
source in its own way (Qt through the catalogue, the Electron renderer
through ``ru.json``) and fills the placeholders itself, which is why the
sentence is not formatted here.

``mark`` does nothing at run time; ``scripts/update_translations.py`` reads
its two literals to keep each sentence in the catalogue.
"""

from __future__ import annotations

import sys
from typing import Dict, NamedTuple, Optional, Tuple

from app.translation_mark import mark


class Issue(NamedTuple):
    """One refusal: a source sentence with ``%1``... placeholders and its values."""

    template: str
    args: Tuple[str, ...] = ()

    def english(self) -> str:
        text = self.template
        for index, value in enumerate(self.args, start=1):
            text = text.replace(f"%{index}", str(value))
        return text


_MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "option": "alt",
    "cmd": "cmd",
    "command": "cmd",
    "win": "cmd",
    "windows": "cmd",
    "super": "cmd",
}
_MODIFIERS = frozenset(_MODIFIER_ALIASES.values())

# Solo keys allowed only in push-to-talk mode.  The listener
# tracks press + release events directly there, so we don't have
# to worry about a held key swallowing an active typing session
# (the user is voluntarily holding it).  Right-side modifiers
# are the safest pick: they're rarely the target of an existing
# shortcut on any platform, and the user keeps a free left-hand
# modifier for normal Cmd+letter / Ctrl+letter shortcuts.
_NON_WINDOWS_PTT_SOLO_KEYS = frozenset({
    "right_cmd", "cmd_r", "right_command", "command_r",
    "right_win", "win_r", "right_windows", "windows_r",
    "right_super", "super_r",
    "right_option", "option_r", "right_alt", "alt_r",
    "right_shift", "shift_r",
    "right_ctrl", "ctrl_r", "right_control", "control_r",
    "fn",
})

_WINDOWS_PTT_SOLO_KEYS = frozenset({
    "right_cmd", "cmd_r", "right_command", "command_r",
    "right_win", "win_r", "right_windows", "windows_r",
    "right_super", "super_r",
    "right_window",
    "right_option", "option_r", "right_alt", "alt_r",
    "right_menu",
    "right_shift", "shift_r",
    "right_ctrl", "ctrl_r", "right_control", "control_r",
})

_NAMED_KEY_ALIASES = {
    "return": "enter",
    "esc": "esc",
    "escape": "esc",
    "pageup": "page_up",
    "pagedown": "page_down",
    "del": "delete",
}

_NAMED_KEYS = frozenset({
    "space", "enter",
    "esc",
    "tab", "backspace", "delete", "insert",
    "home", "end", "page_up", "page_down",
    "up", "down", "left", "right",
    *(f"f{i}" for i in range(1, 25)),
})

MODES = ("two_keys", "toggle", "push_to_talk")


def _is_function_key(key: str) -> bool:
    """``f1`` ... ``f24`` (lowercase)."""
    if len(key) < 2 or key[0] != "f":
        return False
    rest = key[1:]
    if not rest.isdigit():
        return False
    return 1 <= int(rest) <= 24


def _is_letter(key: str) -> bool:
    return len(key) == 1 and "a" <= key <= "z"


def _is_digit(key: str) -> bool:
    return len(key) == 1 and "0" <= key <= "9"


def ptt_solo_keys_for_platform(platform: str) -> frozenset[str]:
    if platform == "win32":
        return _WINDOWS_PTT_SOLO_KEYS
    return _NON_WINDOWS_PTT_SOLO_KEYS


def is_push_to_talk_solo_key(text: str, *, platform: str | None = None) -> bool:
    """Whether ``text`` is one of the platform's solo push-to-talk modifiers.

    Kept apart from :func:`check_hotkey` so a screen can branch on the shape
    of the active binding without running the whole validation.
    """
    raw = (text or "").strip().lower()
    if not raw:
        return False
    return raw in ptt_solo_keys_for_platform(platform or sys.platform)


def check_hotkey(
    text: str,
    *,
    allow_empty: bool = False,
    push_to_talk: bool = False,
    platform: str | None = None,
) -> Optional[Issue]:
    """``None`` when ``text`` is a usable binding, otherwise the reason.

    ``allow_empty`` accepts an empty string (the optional Cancel field).
    ``push_to_talk`` additionally accepts a solo right-side modifier, which
    is only safe where the listener tracks press and release: in any other
    mode a lone modifier would swallow the next keystroke.
    """
    raw = (text or "").strip()
    if not raw:
        return None if allow_empty else Issue(
            mark("HotkeyValidation", "Hotkey cannot be empty")
        )
    resolved_platform = platform or sys.platform

    # The solo vocabulary is accepted before the text is split on ``+``:
    # ``right_cmd`` has no separator, and the modifier check below would
    # refuse it because nothing precedes the key.
    if push_to_talk and is_push_to_talk_solo_key(raw, platform=resolved_platform):
        return None

    raw_parts = [p.strip().lower() for p in raw.split("+")]
    if any(not p for p in raw_parts):
        return Issue(
            mark(
                "HotkeyValidation",
                "Empty part in %1. Remove the extra '+' or the trailing space",
            ),
            (repr(raw),),
        )

    parts = [
        _MODIFIER_ALIASES.get(part, _NAMED_KEY_ALIASES.get(part, part))
        for part in raw_parts
    ]
    *mods, key = parts
    *raw_mods, raw_key = raw_parts

    if len(mods) != len(set(mods)):
        return Issue(
            mark("HotkeyValidation", "Duplicate modifier in %1"), (repr(raw),)
        )

    for raw_modifier, modifier in zip(raw_mods, mods):
        if modifier not in _MODIFIERS:
            return Issue(
                mark(
                    "HotkeyValidation",
                    "%1 is not a recognised modifier (use ctrl, shift, alt, cmd)",
                ),
                (repr(raw_modifier),),
            )

    if key in _MODIFIERS:
        return Issue(
            mark(
                "HotkeyValidation",
                "%1 is a modifier. The combination needs a final key "
                "(a letter, a digit, an F key or a named key like 'space')",
            ),
            (repr(raw_key),),
        )

    if not (
        _is_letter(key) or _is_digit(key) or _is_function_key(key) or key in _NAMED_KEYS
    ):
        return Issue(
            mark("HotkeyValidation", "%1 is not a recognised key"), (repr(raw_key),)
        )

    # A key other than F1..F24 without a modifier would intercept normal
    # typing globally: ``space`` would block every space, ``enter`` every
    # submit. The F keys are the only ones nobody types.
    if not mods and not _is_function_key(key):
        return Issue(
            mark(
                "HotkeyValidation",
                "Add a modifier (ctrl, alt, shift or cmd). A lone key "
                "would fire every time you press it, in any "
                "app. Only F1..F24 can be used alone.",
            )
        )
    return None


def find_conflicts(
    start: str, stop: str, cancel: str, *, mode: str = "two_keys"
) -> Dict[str, Issue]:
    """Cross-field conflicts, keyed by ``start`` / ``stop`` / ``cancel``.

    In two-key mode Stop equal to Start points at Toggle mode, and Cancel
    may not equal Stop. In every mode Cancel may not equal Start.
    """
    errors: Dict[str, Issue] = {}
    s = start.strip().lower()
    p = stop.strip().lower()
    c = cancel.strip().lower()

    if mode == "two_keys":
        if s and p and s == p:
            errors["stop"] = Issue(
                mark(
                    "HotkeyValidation",
                    "Stop is the same as Start (%1). Switch to Toggle mode if "
                    "one hotkey should do both.",
                ),
                (s,),
            )
        if c and p and c == p:
            errors["cancel"] = Issue(
                mark("HotkeyValidation", "Cancel matches Stop (%1)"), (p,)
            )

    if c and s and c == s and "cancel" not in errors:
        errors["cancel"] = Issue(
            mark("HotkeyValidation", "Cancel matches Start (%1)"), (s,)
        )
    return errors


def check_all(
    *,
    start: str,
    stop: str,
    cancel: str,
    mode: str = "two_keys",
    platform: str | None = None,
) -> Dict[str, Issue]:
    """Every problem across the three fields, first error wins per field.

    In push-to-talk mode ``start`` is the push-to-talk key and is checked
    against the looser solo-modifier vocabulary; ``stop`` is only checked in
    two-key mode.
    """
    errors: Dict[str, Issue] = {}

    issue = check_hotkey(start, push_to_talk=(mode == "push_to_talk"), platform=platform)
    if issue:
        errors["start"] = issue

    if mode == "two_keys":
        issue = check_hotkey(stop, platform=platform)
        if issue:
            errors["stop"] = issue

    issue = check_hotkey(cancel, allow_empty=True, platform=platform)
    if issue:
        errors["cancel"] = issue

    # A conflict between two fields is only worth saying when each of them
    # parsed on its own.
    if not errors:
        errors.update(find_conflicts(start, stop, cancel, mode=mode))
    return errors
