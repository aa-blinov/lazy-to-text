"""Which files the file-transcription screens accept.

Qt-free so the headless runtime and the Qt view share one list: the
screen's drop guard and the runtime's validation must never disagree
about what an audio or video file is.
"""

from __future__ import annotations

# ``soundfile`` covers the lossless / OGG family; ``imageio-ffmpeg`` (the
# bundled static ffmpeg) covers everything else, including the audio track
# of the video containers.
AUDIO_EXTS: tuple[str, ...] = (
    # libsndfile native
    ".wav", ".flac", ".ogg", ".oga", ".opus", ".aiff", ".aif",
    # ffmpeg fallback - audio
    ".mp3", ".m4a", ".aac", ".wma", ".amr", ".ac3", ".alac",
    # ffmpeg fallback - video containers
    ".mp4", ".mov", ".webm", ".mkv", ".avi", ".flv", ".3gp", ".m4v",
    ".wmv", ".ts",
)


def looks_like_audio(path: str) -> bool:
    return path.lower().endswith(AUDIO_EXTS)
