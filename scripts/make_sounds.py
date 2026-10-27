"""Draw the three recording cues: ``app/assets/sounds/record_*.wav``.

Soft bell tones, not beeps: a sine with two quiet overtones, a short fade-in
so there is no click, an exponential decay, and a little room. The start cue
rises (a question answered: "I am listening"), the stop cue falls (a sentence
that ends), the cancel cue is one low, short note. Generated here instead of
taken from a sound library so the files carry no licence of anyone else's.

    uv run python scripts/make_sounds.py
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

RATE = 44100
OUT = Path(__file__).resolve().parent.parent / "app" / "assets" / "sounds"
PEAK = 0.45  # well under full scale: these are cues, not alerts

C5, E5, G5 = 523.25, 659.25, 783.99
C6, E6, G6 = 1046.50, 1318.51, 1567.98
A4 = 440.00


def bell(freq: float, seconds: float, decay: float) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    tone = (
        np.sin(2 * np.pi * freq * t)
        + 0.30 * np.sin(2 * np.pi * freq * 2.0 * t)
        + 0.10 * np.sin(2 * np.pi * freq * 3.01 * t)
    )
    attack = np.minimum(1.0, t / 0.008)
    return tone * attack * np.exp(-t * decay)


def place(notes: list[tuple[float, float]], length: float, decay: float) -> np.ndarray:
    """Mix ``(start second, frequency)`` notes into one buffer."""
    out = np.zeros(int(RATE * length))
    for start, freq in notes:
        voice = bell(freq, length - start, decay)
        at = int(RATE * start)
        out[at : at + len(voice)] += voice
    return out


def room(signal: np.ndarray) -> np.ndarray:
    """A few quiet, decaying echoes, so the note is not dry."""
    out = signal.copy()
    for delay, gain in ((0.043, 0.22), (0.071, 0.14), (0.113, 0.08)):
        at = int(RATE * delay)
        out[at:] += gain * signal[: len(signal) - at]
    return out


def finish(signal: np.ndarray) -> np.ndarray:
    fade = int(RATE * 0.03)
    signal[-fade:] *= np.linspace(1.0, 0.0, fade)
    signal = signal / np.max(np.abs(signal)) * PEAK
    return (signal * 32767).astype("<i2")


def write(name: str, samples: np.ndarray) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / name), "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(RATE)
        clip.writeframes(samples.tobytes())


def main() -> None:
    write("record_start.wav", finish(room(place([(0.0, C6), (0.11, G6)], 0.45, 9.0))))
    write("record_stop.wav", finish(room(place([(0.0, G6), (0.11, E6), (0.22, C6)], 0.60, 8.0))))
    write("record_cancel.wav", finish(room(place([(0.0, A4)], 0.28, 14.0))))


if __name__ == "__main__":
    main()
