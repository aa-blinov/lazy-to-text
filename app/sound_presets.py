"""The sounds the start and stop cues can be set to.

A set is two files shipped under ``app/assets/sounds``. The settings store the
paths, as they always did, so a config written by an earlier build keeps working:
the default start and stop paths are the first set. A set is a pair made together,
so a start and an end never come from different families unless the person picks
two files of their own. A custom sound is a
WAV file the person chose; it is copied next to ``config.yaml`` (``sounds/``) so
that moving or deleting the original does not silence the cue.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app.translation_mark import mark

DEFAULT_START = "assets/sounds/record_start.wav"
DEFAULT_STOP = "assets/sounds/record_stop.wav"


@dataclass(frozen=True)
class SoundSet:
    """A start sound and its end sound, made as a pair: one family, mirrored."""

    id: str
    label: str
    start: str
    stop: str


_SETS = "assets/sounds/sets/"

SOUND_SETS: List[SoundSet] = [
    SoundSet("warm", mark("Sound", "Warm bell"), DEFAULT_START, DEFAULT_STOP),
    SoundSet("wood", mark("Sound", "Wood"), _SETS + "wood-start.wav", _SETS + "wood-stop.wav"),
    SoundSet("droplet", mark("Sound", "Droplet"), _SETS + "droplet-start.wav", _SETS + "droplet-stop.wav"),
    SoundSet("chime", mark("Sound", "Low chime"), _SETS + "chime-start.wav", _SETS + "chime-stop.wav"),
    SoundSet("chord", mark("Sound", "Soft chord"), _SETS + "chord-start.wav", _SETS + "chord-stop.wav"),
    SoundSet("tick", mark("Sound", "Soft tick"), _SETS + "tick-start.wav", _SETS + "tick-stop.wav"),
    SoundSet("glass", mark("Sound", "Glass"), _SETS + "glass-start.wav", _SETS + "glass-stop.wav"),
]

#: What a cue may be set to without being a file of the person's own.
SET_VALUES = frozenset(v for s in SOUND_SETS for v in (s.start, s.stop))

#: ``theme`` of a pair that is not one of the sets.
CUSTOM = "custom"


def theme_of(start: str, stop: str) -> str:
    """The id of the set whose start and stop these are, else ``"custom"``."""
    for sound_set in SOUND_SETS:
        if (start, stop) == (sound_set.start, sound_set.stop):
            return sound_set.id
    return CUSTOM


def custom_dir(config_dir: Path) -> Path:
    return Path(config_dir) / "sounds"


def is_custom(value: str, config_dir: Path) -> bool:
    """Whether ``value`` names a file inside the custom sounds folder."""
    if not value or not os.path.isabs(value):
        return False
    folder = os.path.realpath(custom_dir(config_dir))
    target = os.path.realpath(value)
    return os.path.dirname(target) == folder and os.path.isfile(target)


def accepted(value: str, config_dir: Path) -> Optional[str]:
    """The value if it may be stored for a cue, else ``None``.

    Empty means no sound for that cue.
    """
    if value == "" or value in SET_VALUES:
        return value
    if is_custom(value, config_dir):
        return os.path.realpath(value)
    return None
