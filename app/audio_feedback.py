import logging
import os
import struct
import sys
import threading
import wave
from datetime import datetime
from typing import Callable, Optional

from app.utils import resolve_asset_path

if sys.platform == "win32":
    import winsound
else:
    winsound = None  # type: ignore[assignment]


def _build_silent_wav() -> bytes:
    """Return a minimal valid silent WAV buffer.

    Used to prewarm the Windows multimedia stack: the first
    ``winsound.PlaySound`` after process start spends 100-300 ms opening the
    audio device, and any SND_ASYNC sound issued during that window is
    silently dropped. Playing this buffer at startup forces the device open
    without any audible output (it is a fraction of a second of zero
    samples at low rate).
    """
    sample_rate = 8000
    bits_per_sample = 8
    channels = 1
    block_align = channels * (bits_per_sample // 8)
    byte_rate = sample_rate * block_align
    sample_count = 100  # ~12.5 ms of silence — inaudible
    data_size = sample_count * block_align
    file_size = 36 + data_size
    header = b"".join(
        [
            b"RIFF",
            struct.pack("<I", file_size),
            b"WAVE",
            b"fmt ",
            struct.pack("<I", 16),
            struct.pack("<H", 1),  # PCM
            struct.pack("<H", channels),
            struct.pack("<I", sample_rate),
            struct.pack("<I", byte_rate),
            struct.pack("<H", block_align),
            struct.pack("<H", bits_per_sample),
            b"data",
            struct.pack("<I", data_size),
        ]
    )
    # 8-bit unsigned PCM: silence is 0x80 (128).
    silence = bytes([0x80] * data_size)
    return header + silence


_SILENT_WAV = _build_silent_wav() if sys.platform == "win32" else b""


def parse_clock(text) -> Optional[int]:
    """``"HH:MM"`` (24 hour) as minutes after midnight, or ``None`` if it is not one."""
    if not isinstance(text, str) or len(text) != 5 or text[2] != ":":
        return None
    hours, minutes = text[:2], text[3:]
    if not (hours.isdigit() and minutes.isdigit()):
        return None
    h, m = int(hours), int(minutes)
    return h * 60 + m if h < 24 and m < 60 else None


def in_quiet_hours(now_minutes: int, start: str, end: str) -> bool:
    """Whether a time of day falls in the window from ``start`` up to ``end``.

    The window may run past midnight (22:00 to 08:00). Equal times, or a time
    that is not a clock time, make no window.
    """
    begin, finish = parse_clock(start), parse_clock(end)
    if begin is None or finish is None or begin == finish:
        return False
    if begin < finish:
        return begin <= now_minutes < finish
    return now_minutes >= begin or now_minutes < finish


class AudioFeedback:
    def __init__(self, enabled=True, start_sound='', stop_sound='', cancel_sound='',
                 quiet_hours=False, quiet_start='22:00', quiet_end='08:00',
                 clock: Optional[Callable[[], datetime]] = None):
        self.enabled = enabled
        # Quiet hours silence the cues without touching ``enabled``: the
        # person's own choice comes back by itself when the window ends.
        self.quiet_hours = bool(quiet_hours)
        self.quiet_start = quiet_start
        self.quiet_end = quiet_end
        self._clock = clock or datetime.now
        self.logger = logging.getLogger(__name__)

        self.start_sound_path = resolve_asset_path(start_sound)
        self.stop_sound_path = resolve_asset_path(stop_sound)
        self.cancel_sound_path = resolve_asset_path(cancel_sound)

        if not self.enabled:
            self.logger.info("Audio feedback disabled by configuration", extra={'user_message': True})
            self.logger.info("Audio feedback disabled", extra={'user_message': True})
        else:
            self._validate_sound_files()
            self.prewarm()
            self.logger.info("Audio feedback enabled...", extra={'user_message': True})

    def quiet_now(self) -> bool:
        """Whether the quiet-hours window is in force at this moment."""
        if not self.quiet_hours:
            return False
        now = self._clock()
        return in_quiet_hours(now.hour * 60 + now.minute, self.quiet_start, self.quiet_end)

    def sounding(self) -> bool:
        """Whether a cue would be heard now."""
        return bool(self.enabled) and not self.quiet_now()

    def prewarm(self) -> None:
        """Wake the Windows audio subsystem so the next play_*_sound call is
        heard rather than silently dropped during device-open latency.

        Windows releases an idle audio device after a few seconds.  The
        initial call happens at construction time; call this again whenever a
        long pause (e.g. model loading) may have caused the device to close.
        No-ops immediately if audio feedback is disabled, and on
        non-Windows platforms (``playsound3`` opens the device on
        every call without the silent-drop pathology).
        """
        if not self.enabled or sys.platform != "win32":
            return

        def warm():
            try:
                winsound.PlaySound(
                    _SILENT_WAV,
                    winsound.SND_MEMORY | winsound.SND_ASYNC,
                )
            except Exception as exc:
                self.logger.debug("Audio prewarm failed: %s", exc)

        threading.Thread(target=warm, daemon=True, name="audio-prewarm").start()

    def _validate_sound_files(self):
        if self.start_sound_path and not os.path.isfile(self.start_sound_path):
            self.logger.warning("Start sound file not found: %s", self.start_sound_path)

        if self.stop_sound_path and not os.path.isfile(self.stop_sound_path):
            self.logger.warning("Stop sound file not found: %s", self.stop_sound_path)

        if self.cancel_sound_path and not os.path.isfile(self.cancel_sound_path):
            self.logger.warning("Cancel sound file not found: %s", self.cancel_sound_path)

    def _play_sound_file_async(self, file_path: str):
        """Play ``file_path`` on a daemon thread.

        Windows: we deliberately do NOT pass ``winsound.SND_ASYNC``.
        With ``SND_ASYNC``, ``PlaySound`` returns immediately and
        Windows plays the buffer from a system worker — but if the
        calling thread exits before Windows finishes setting up that
        play, the sound is dropped silently.  We've seen this happen
        intermittently when the start sound fires right before the
        microphone stream opens (the recorder grabbing the audio
        device disrupts the still-pending async play).

        Synchronous ``PlaySound`` blocks the thread for the duration
        of the clip (~80-150 ms for our cues) — but the thread is
        daemon and isolated from the main loop, so the user-facing
        latency is identical: the start sound still kicks off in
        parallel with everything else, just without the racy
        Windows-side queue.

        macOS / Linux: delegates to ``playsound3.playsound`` with
        ``block=True`` on the daemon thread (same rationale — keep
        the play synchronous to avoid any interpreter-shutdown race
        on the underlying backend).
        """
        if not file_path:
            return

        if sys.platform == "win32":
            def play_sound():
                try:
                    winsound.PlaySound(file_path, winsound.SND_FILENAME)
                except Exception as e:
                    self.logger.warning(
                        "Failed to play sound file %s: %s", file_path, e
                    )
        else:
            def play_sound():
                try:
                    from playsound3 import playsound

                    playsound(file_path, block=True)
                except Exception as e:
                    self.logger.warning(
                        "Failed to play sound file %s: %s", file_path, e
                    )

        sound_thread = threading.Thread(target=play_sound, daemon=True)
        sound_thread.start()

    def set_sounds(self, start: Optional[str] = None, stop: Optional[str] = None) -> None:
        """Point the start and stop cues at other files, now. ``""`` is silence;
        ``None`` leaves a cue as it is."""
        if start is not None:
            self.start_sound_path = resolve_asset_path(start)
        if stop is not None:
            self.stop_sound_path = resolve_asset_path(stop)

    def preview(self, value: str) -> float:
        """Play a cue so it can be heard before it is chosen, whether or not the
        cues are switched on. Returns its length in seconds, 0 for silence."""
        path = resolve_asset_path(value)
        if not path or not os.path.isfile(path):
            return 0.0
        self._play_sound_file_async(path)
        return self._seconds_of(path)

    @staticmethod
    def _seconds_of(path: str) -> float:
        try:
            with wave.open(path, "rb") as clip:
                return clip.getnframes() / float(clip.getframerate())
        except Exception:
            return 0.0

    def start_sound_seconds(self) -> float:
        """How long the start cue lasts, so the caller can wait it out.

        0 when cues are off, the file is missing or it cannot be read.
        """
        if not self.sounding() or not self.start_sound_path:
            return 0.0
        return self._seconds_of(self.start_sound_path)

    def play_start_sound(self):
        if self.sounding():
            self._play_sound_file_async(self.start_sound_path)

    def play_stop_sound(self):
        if self.sounding():
            self._play_sound_file_async(self.stop_sound_path)

    def play_cancel_sound(self):
        if self.sounding():
            self._play_sound_file_async(self.cancel_sound_path)
