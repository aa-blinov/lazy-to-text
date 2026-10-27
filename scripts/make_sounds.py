"""Draw the recording cues: ``app/assets/sounds/*.wav`` and ``presets/*.wav``.

Soft bell and wood tones, not beeps: a sine with quiet overtones, a short
fade-in so there is no click, an exponential decay, and a little room. The
defaults sit in the middle of the voice range, lower and lighter than the first
set (which stays on the list as "Glass"): a start cue that rises, a stop cue
that falls, a cancel cue that is one short low note. Generated here instead of
taken from a sound library so the files carry no licence of anyone else's.

    uv run python scripts/make_sounds.py
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

RATE = 44100
ROOT = Path(__file__).resolve().parent.parent / "app" / "assets" / "sounds"
PEAK = 0.34  # well under full scale: these are cues, not alerts

A3, D4, E4, A4, D5, E5 = 220.00, 293.66, 329.63, 440.00, 587.33, 659.25
C6, E6, G6 = 1046.50, 1318.51, 1567.98


def bell(freq: float, seconds: float, decay: float, bright: float = 0.18) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    tone = (
        np.sin(2 * np.pi * freq * t)
        + bright * np.sin(2 * np.pi * freq * 2.0 * t)
        + 0.5 * bright * np.sin(2 * np.pi * freq * 3.01 * t)
    )
    attack = np.minimum(1.0, t / 0.012)
    return tone * attack * np.exp(-t * decay)


def place(notes: list[tuple[float, float]], length: float, decay: float, bright: float = 0.18) -> np.ndarray:
    """Mix ``(start second, frequency)`` notes into one buffer."""
    out = np.zeros(int(RATE * length))
    for start, freq in notes:
        voice = bell(freq, length - start, decay, bright)
        at = int(RATE * start)
        out[at : at + len(voice)] += voice
    return out


def knock(freq: float, seconds: float, decay: float, seed: int) -> np.ndarray:
    """A woody tap: a short sine body with a breath of filtered noise at the front."""
    t = np.arange(int(RATE * seconds)) / RATE
    body = np.sin(2 * np.pi * freq * t) * np.exp(-t * decay)
    noise = np.random.default_rng(seed).standard_normal(len(t))
    noise = np.convolve(noise, np.ones(24) / 24, mode="same") * np.exp(-t * decay * 3.5)
    return body + 0.45 * noise


def droplet() -> np.ndarray:
    t = np.arange(int(RATE * 0.32)) / RATE
    freq = 360 + 380 * np.exp(-t * 16)  # a glide down, like a drop into water
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    return np.sin(phase) * np.minimum(1.0, t / 0.006) * np.exp(-t * 13)


def pad() -> np.ndarray:
    t = np.arange(int(RATE * 0.55)) / RATE
    swell = np.sin(np.pi * t / t[-1]) ** 2
    chord = np.sin(2 * np.pi * A3 * t) + 0.8 * np.sin(2 * np.pi * E4 * t) + 0.6 * np.sin(2 * np.pi * A4 * t)
    return chord * swell


def room(signal: np.ndarray) -> np.ndarray:
    """A few quiet, decaying echoes, so the note is not dry."""
    out = signal.copy()
    for delay, gain in ((0.043, 0.2), (0.071, 0.12), (0.113, 0.07)):
        at = int(RATE * delay)
        out[at:] += gain * signal[: len(signal) - at]
    return out


def finish(signal: np.ndarray) -> np.ndarray:
    fade = int(RATE * 0.03)
    signal[-fade:] *= np.linspace(1.0, 0.0, fade)
    signal = signal / np.max(np.abs(signal)) * PEAK
    return (signal * 32767).astype("<i2")


def write(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(RATE)
        clip.writeframes(samples.tobytes())


def two_knocks() -> np.ndarray:
    out = np.zeros(int(RATE * 0.36))
    for start, freq, seed in ((0.0, 392.0, 1), (0.13, 523.25, 2)):
        tap = knock(freq, 0.23, 36, seed)
        at = int(RATE * start)
        out[at : at + len(tap)] += tap
    return out


def main() -> None:
    # The three that the settings point at by default.
    write(ROOT / "record_start.wav", finish(room(place([(0.0, A4), (0.12, E5)], 0.5, 8.0))))
    write(ROOT / "record_stop.wav", finish(room(place([(0.0, E5), (0.12, A4)], 0.5, 8.0))))
    write(ROOT / "record_cancel.wav", finish(room(place([(0.0, D4)], 0.26, 16.0))))
    # The rest of the list.
    presets = ROOT / "presets"
    write(presets / "soft-tick.wav", finish(room(place([(0.0, 392.0)], 0.2, 24.0, 0.1))))
    write(presets / "wood.wav", finish(room(two_knocks())))
    write(presets / "droplet.wav", finish(room(droplet())))
    write(presets / "low-chime.wav", finish(room(place([(0.0, D4), (0.0, A4)], 0.55, 6.0, 0.22))))
    write(presets / "pad.wav", finish(pad()))
    write(presets / "glass-rise.wav", finish(room(place([(0.0, C6), (0.11, G6)], 0.45, 9.0, 0.3))))
    write(presets / "glass-fall.wav", finish(room(place([(0.0, G6), (0.11, E6), (0.22, C6)], 0.6, 8.0, 0.3))))


if __name__ == "__main__":
    main()
