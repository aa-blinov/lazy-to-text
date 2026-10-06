"""Render the Qt UI offscreen and dump per-section PNG screenshots.

Run with::

    uv run python scripts/generate_screenshots.py

Drops files into ``docs/screenshots/``. Used to populate the README
and the docs site (``docs/index.html``).
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

# NB: do NOT force offscreen here — that platform plugin has no link to the
# native font subsystem on Windows, so every label renders as tofu (□).
# We use the real "windows" platform and rely on widget.grab() to capture
# off-screen anyway.
os.environ.pop("QT_QPA_PLATFORM", None)

# Project root must be on sys.path so we can import app.* directly.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

from PySide6.QtCore import QSize  # noqa: E402

from app.gui.app import build_application  # noqa: E402
from app.gui.log_bridge import QtLogBridge  # noqa: E402
from app.history_manager import TranscriptionEntry  # noqa: E402


OUT_DIR = _ROOT / "docs" / "screenshots"
WINDOW_SIZE = QSize(1100, 720)


class _FakeHistory:
    """Stand-in for HistoryManager with a realistic ONNX-era dataset."""

    def __init__(self) -> None:
        now = time.time()
        self._entries = [
            TranscriptionEntry(
                timestamp=now - 60,
                text=(
                    "Quick reminder: ship the ONNX-only refactor this week — "
                    "saves us four gigabytes on every install."
                ),
                duration=4.1,
                model="parakeet-tdt-v3",
                language=None,
            ),
            TranscriptionEntry(
                timestamp=now - 1200,
                text=(
                    "Customer feedback summary: the Transcribe tab handles "
                    "MP4 / MKV / WebM out of the box now thanks to the "
                    "bundled ffmpeg fallback."
                ),
                duration=11.7,
                model="whisper-large-v3-turbo",
                language="en",
            ),
            TranscriptionEntry(
                timestamp=now - 3600,
                text=(
                    "Action item: reproduce the case-sensitive T-One "
                    "loader bug on a brand-new install before Friday."
                ),
                duration=4.9,
                model="t-one",
                language="ru",
            ),
            TranscriptionEntry(
                timestamp=now - 7200,
                text=(
                    "Daily standup notes — keeping Parakeet warm at "
                    "1.4 GB VRAM, comfortable on a 4 GB card."
                ),
                duration=6.2,
                model="parakeet-tdt-v3",
                language=None,
            ),
            TranscriptionEntry(
                timestamp=now - 86400,
                text=(
                    "Tested Vosk RU on the netbook yesterday — usable "
                    "transcription on a CPU-only laptop, fifty megs total."
                ),
                duration=4.0,
                model="vosk-ru",
                language="ru",
            ),
        ]

    def get_entries(self):
        return list(self._entries)

    def clear_history(self):
        self._entries.clear()


class _FakeConfig:
    def __init__(self) -> None:
        self._data = {
            "whisper": {"model": "parakeet-tdt-v3"},
            "hotkey": {
                "start_recording_hotkey": "ctrl+f2",
                "stop_recording_hotkey": "ctrl+f3",
                "cancel_recording_hotkey": "ctrl+f6",
            },
            "clipboard": {"auto_paste": True},
        }

    def get_setting(self, section: str, key: str):
        return self._data.get(section, {}).get(key)

    def update_user_setting(self, section: str, key: str, value):
        self._data.setdefault(section, {})[key] = value


def _seed_logs(window) -> None:
    """Push a handful of realistic-looking log lines into the LogsView.

    On the structured signal, not the legacy ``line_received`` one: the
    view has a single entry point, and this is it. The screenshots come
    out the same as the running app's — coloured by level, tagged with
    the logger — rather than as a flat column of unstyled text.
    """
    bridge = QtLogBridge(parent=window)
    bridge.record_received.connect(window.logs_view.append_record)

    logger = logging.getLogger("lazy_to_text")
    logger.addHandler(bridge.handler())
    logger.setLevel(logging.DEBUG)
    try:
        logger.info("Audio feedback enabled...")
        logger.info(
            "Recording stack built: model=istupakov/parakeet-tdt-0.6b-v3-onnx "
            "kind=onnx_asr device=auto compute_type=float32"
        )
        logger.info("Primary instance acquired mutex LazyToTextQt_SingleInstance")
        logger.info("Hotkeys registered: ctrl+f2 (start) / ctrl+f3 (stop) / ctrl+f6 (cancel)")
        logger.info(
            "Loading ONNX model istupakov/parakeet-tdt-0.6b-v3-onnx "
            "(load_id=nemo-parakeet-tdt-0.6b-v3, family=parakeet, "
            "providers=None, quantization=None)…"
        )
        logger.info("OnnxAsr model istupakov/parakeet-tdt-0.6b-v3-onnx ready")
        logger.warning("Container log buffer at 80% — consider rotating soon.")
        logger.info(
            "Transcription complete (4.1s) — 'Quick reminder: ship the ONNX-only refactor this week…'"
        )
        logger.debug("[Pipeline] Audio data memory freed")
    finally:
        logger.removeHandler(bridge.handler())


def _seed_resource_metrics(window) -> None:
    """Push a realistic synthetic sample into the topbar's resource
    widget. Without this the screenshot is captured before the real
    ``ResourceMonitor`` has produced its first sample (it polls every
    2 s), so CPU/RAM render as 0% — and on machines without an NVIDIA
    driver the GPU/VRAM blocks would also be hidden, leaving a half-
    empty bar that misrepresents what the app actually shows in use."""
    window.topbar.set_resource_metrics(
        {
            "cpu_percent": 18.0,
            "ram_percent": 32.4,
            "ram_used_mb": 10_600.0,
            "ram_total_mb": 32_768.0,
            "gpu_util_percent": 4.0,
            "gpu_vram_used_mb": 1_900.0,
            "gpu_vram_total_mb": 16_384.0,
        }
    )


def _seed_transcribe_view(window) -> None:
    """Pre-fill the Transcribe view with a sample result so the
    screenshot shows the populated state instead of the empty placeholder.

    The file is a real one on disk. That used to be a literal
    ``C:\\Users\\you\\Desktop\\...`` string, which does not exist on
    either shipping platform — and now that the collapsed zone reports a
    measured file size, a missing path would render the size blank and
    quietly turn the screenshot into a picture of a lie.

    It also has a name worth printing. ``mkstemp`` gave us
    ``interview-60yijing6.m4a``, and a random token is a poor thing to
    put in a README; the temp directory moves out of sight instead.
    """
    import tempfile

    sample_text = (
        "Yeah, so the move to ONNX runtime really paid off — we shipped "
        "the install size from four gigabytes down to about seven "
        "hundred megs, and cold start dropped from a minute and a half "
        "to about four seconds. The Transcribe tab handles M4A and MP4 "
        "out of the box now, no separate codec install. Russian quality "
        "on T-One is noticeably better than Whisper for noisy audio."
    )
    sample_dir = tempfile.mkdtemp(prefix="l2t-screenshot-")
    sample_path = os.path.join(sample_dir, "interview-2026-10-05.m4a")
    try:
        with open(sample_path, "wb") as fh:
            fh.write(b"\0" * (6 * 1024 * 1024))
    except OSError:  # pragma: no cover — a temp dir we cannot write to
        pass
    view = window.transcribe_view
    view.set_busy(sample_path)
    # Nothing is actually transcribed here, so the elapsed field would
    # render the real measured cost of doing nothing — "1 ms" printed
    # next to a 6 MB file, in a picture whose job is to look like the
    # app doing work. Wind the clock back by the same 4.1 s the Logs
    # and History seeds claim, so the three screenshots agree.
    view._started_at -= 4.1
    view.set_result(sample_text)


def _capture(window, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.png"
    pixmap = window.grab()
    pixmap.save(str(path), "PNG")
    print(f"  wrote {path.relative_to(_ROOT)} ({pixmap.width()}x{pixmap.height()})")
    return path


def _seed_granted_permissions() -> None:
    """Present the Settings page as a user who has already said yes.

    The permission banners are truthful and they are useful in the
    product — but in a screenshot they read as "the app is broken",
    where what is really shown is "macOS asked and the user granted".
    Two orange warning strips across the Settings page also push every
    card down by a few hundred pixels, so the page stops looking like
    the page.

    The probes are answered ``granted`` here and nothing in ``app/`` is
    touched: this is a seeding decision about what the picture shows,
    not a change to what the app does. The banners still appear for
    anyone who has not granted access.

    Must run before the window is built — ``ShortcutsView.__init__``
    reads these probes once and keeps the answer in
    ``_last_*_trusted``, so a patch applied afterwards would not change
    what is on screen.
    """
    import app.gui.views.shortcuts_view as shortcuts_view

    shortcuts_view.is_accessibility_trusted = lambda: True
    shortcuts_view.is_post_event_access_trusted = lambda: True
    shortcuts_view.microphone_authorization_status = lambda: "authorized"


def main() -> int:
    _seed_granted_permissions()

    config = _FakeConfig()
    history = _FakeHistory()

    app, window = build_application(
        config=config,
        history=history,
        install_logs=False,
    )
    window.resize(WINDOW_SIZE)
    window.show()
    app.processEvents()

    _seed_logs(window)
    _seed_resource_metrics(window)
    _seed_transcribe_view(window)

    # Force one initial paint so the layout settles before we grab.
    for _ in range(5):
        app.processEvents()

    sections = ("models", "transcribe", "history", "logs", "shortcuts")
    for key in sections:
        window.sidebar.set_active(key)
        # Repeatedly drain events; the window/layout sometimes needs
        # several ticks before the new active view paints.
        for _ in range(8):
            app.processEvents()
        _capture(window, key)

    # Restore default and capture a "hero" shot showing Models from a fresh
    # angle.
    window.sidebar.set_active("models")
    for _ in range(8):
        app.processEvents()
    _capture(window, "hero")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
