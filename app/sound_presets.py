"""The sounds the start and stop cues can be set to.

A preset is a file shipped under ``app/assets/sounds``. The settings store the
path, as they always did, so a config written by an earlier build keeps working:
the default start and stop paths are the first two presets. A custom sound is a
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
class Preset:
    id: str
    label: str
    value: str


PRESETS: List[Preset] = [
    Preset("warm-rise", mark("Sound", "Warm rise"), DEFAULT_START),
    Preset("warm-fall", mark("Sound", "Warm fall"), DEFAULT_STOP),
    Preset("soft-tick", mark("Sound", "Soft tick"), "assets/sounds/presets/soft-tick.wav"),
    Preset("wood", mark("Sound", "Wood"), "assets/sounds/presets/wood.wav"),
    Preset("droplet", mark("Sound", "Droplet"), "assets/sounds/presets/droplet.wav"),
    Preset("low-chime", mark("Sound", "Low chime"), "assets/sounds/presets/low-chime.wav"),
    Preset("pad", mark("Sound", "Soft chord"), "assets/sounds/presets/pad.wav"),
    Preset("glass-rise", mark("Sound", "Glass rise"), "assets/sounds/presets/glass-rise.wav"),
    Preset("glass-fall", mark("Sound", "Glass fall"), "assets/sounds/presets/glass-fall.wav"),
]

PRESET_VALUES = frozenset(p.value for p in PRESETS)


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
    if value == "" or value in PRESET_VALUES:
        return value
    if is_custom(value, config_dir):
        return os.path.realpath(value)
    return None
