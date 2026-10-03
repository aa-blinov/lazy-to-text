"""Motion preference and the app's one authored entrance.

Two jobs live here.

**The preference.** Both operating systems ship a user-facing switch for
"less movement" and this app ignored it while running a 400 ms spatial
tween on every wheel notch:

- macOS: System Settings → Accessibility → Display → Reduce motion,
  read as ``NSWorkspace.accessibilityDisplayShouldReduceMotion()``.
- Windows: Settings → Accessibility → Visual effects → Animation
  effects, read as ``SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION)``.

PySide6 6.11's ``QStyleHints`` reports neither, exactly as it fails to
report forced colours, so both are read the same defensive way
``theme.is_high_contrast`` reads its own: one guarded platform call,
wrapped so a detection failure degrades to the full-motion path instead
of breaking startup.

**The sequence.** A transient confirmation that appears and vanishes
without a temporal edge is a flicker in peripheral vision, and the user
here is usually looking at a *different* window — they pressed a hotkey
blind, spoke, and the banner is how the app says the text landed. So
the toast gets one authored arrival: it rises out of the corner it
already occupies while fading in, and it leaves faster than it came.

Reduce Motion drops the rise and keeps the fade. That is the iOS rule
("crossfade instead of parallax and large slides") and the Material
one ("crossfade or instant cut") arriving at the same place from two
directions: the *arrival* carries meaning, the *travel* does not.
"""

from __future__ import annotations

import sys
import time
from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


# How long a piece of motion may run before the OS preference behind it
# is re-read. Two seconds is the shortest window that keeps the answer
# honest across a Settings switch while staying invisible in the wheel
# path, which calls ``reduce_motion()`` on every notch.
_RECHECK_S = 2.0

# The reduced path's own budget: long enough to read as a transition,
# short enough that a three-second toast still spends most of its life
# on screen.
_REDUCED_FADE_MS = 90

_cache: Optional[bool] = None
_checked_at: float = 0.0


def _query_reduce_motion() -> bool:
    """One platform read, guarded three ways."""
    if sys.platform == "darwin":
        try:
            from AppKit import NSWorkspace

            return bool(
                NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion()
            )
        except Exception:
            return False
    if sys.platform == "win32":
        try:
            import ctypes

            SPI_GETCLIENTAREAANIMATION = 0x1042
            enabled = ctypes.c_int()
            ok = ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
            )
            return bool(ok) and bool(enabled.value)
        except Exception:
            return False
    return False


def reduce_motion() -> bool:
    """True when the user has asked the OS for less movement.

    Cached for :data:`_RECHECK_S` seconds. The wheel path calls this per
    notch and the underlying call crosses into Objective-C or user32,
    so the answer is reused between checks rather than paid per event.
    """
    global _cache, _checked_at
    now = time.monotonic()
    if _cache is not None and (now - _checked_at) < _RECHECK_S:
        return _cache
    _cache = _query_reduce_motion()
    _checked_at = now
    return _cache


def refresh_reduce_motion() -> bool:
    """Drop the cache and re-read. For tests and for explicit resyncs."""
    global _cache, _checked_at
    _cache = None
    _checked_at = 0.0
    return reduce_motion()


def motion_duration_ms(base_ms: int) -> int:
    """``base_ms`` normally; the short crossfade under Reduce Motion."""
    return _REDUCED_FADE_MS if reduce_motion() else int(base_ms)


def motion_offset(px: int) -> int:
    """``px`` of travel normally; none at all under Reduce Motion."""
    return 0 if reduce_motion() else int(px)


def _opacity_effect(widget: QWidget) -> QGraphicsOpacityEffect:
    """The widget's opacity effect, installing one if it has none.

    Idempotent, and it adopts an effect the widget already carries
    rather than stacking a second one — ``setGraphicsEffect`` replaces,
    which would silently detach a caller's effect.
    """
    existing = widget.graphicsEffect()
    if isinstance(existing, QGraphicsOpacityEffect):
        return existing
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    return effect


def rise_and_fade(
    widget: QWidget,
    *,
    offset_px: int = 12,
    duration_ms: int = 180,
) -> QParallelAnimationGroup:
    """Author the arrival: rise ``offset_px`` from rest while fading in.

    The widget must already be positioned at its resting place; this
    reads that position as the destination and starts the animation
    below it. Under Reduce Motion the rise is dropped and only the fade
    runs, so the confirmation still arrives — it just stops moving.

    Returns the group so the caller can stop it. Interruption is the
    caller's job: stopping a running group leaves the widget wherever it
    had reached, so a caller that re-shows mid-flight should finish the
    last step itself rather than assume a clean rest state.
    """
    duration = motion_duration_ms(duration_ms)
    offset = motion_offset(offset_px)
    effect = _opacity_effect(widget)

    final = QPoint(widget.x(), widget.y())
    start = QPoint(final.x(), final.y() + offset)

    group = QParallelAnimationGroup(widget)
    # OutQuart is the closest stock curve to a natural decelerating
    # arrival: fast commit, soft landing, and no overshoot. Elastic and
    # bounce are reflex answers to "make it feel physical" and read as
    # toy-like at 180 ms.
    easing = QEasingCurve.Type.OutQuart

    if offset:
        move = QPropertyAnimation(widget, b"pos", group)
        move.setStartValue(start)
        move.setEndValue(final)
        move.setDuration(duration)
        move.setEasingCurve(easing)
        group.addAnimation(move)

    fade = QPropertyAnimation(effect, b"opacity", group)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setDuration(duration)
    fade.setEasingCurve(easing)
    group.addAnimation(fade)

    widget.move(start)
    effect.setOpacity(0.0)
    group.start()
    return group


def fade_out(
    widget: QWidget,
    *,
    duration_ms: int = 120,
) -> Optional[QParallelAnimationGroup]:
    """Leave faster than the entrance: opacity only, then the caller hides.

    Returns ``None`` when the caller should hide immediately — under
    Reduce Motion a fade that short is indistinguishable from a cut, so
    running it would only add a frame of latency to a disappearing
    banner.
    """
    if reduce_motion():
        return None
    effect = _opacity_effect(widget)
    group = QParallelAnimationGroup(widget)
    fade = QPropertyAnimation(effect, b"opacity", group)
    fade.setStartValue(effect.opacity())
    fade.setEndValue(0.0)
    fade.setDuration(max(1, int(duration_ms)))
    # InQuad on the way out: the banner is leaving, nothing is arriving,
    # and a decelerating exit reads as the app hesitating.
    fade.setEasingCurve(QEasingCurve.Type.InQuad)
    group.addAnimation(fade)
    group.start()
    return group
