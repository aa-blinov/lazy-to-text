"""Regenerate the Windows tray icons from the microphone glyph.

One PNG (32 px) and one multi-size ICO per state, coloured from the dark
palette in DESIGN.md: idle is the accent sage, recording the danger red,
processing the warning yellow. Run after changing those colours:

    uv run python scripts/generate_tray_icons.py
"""

from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLYPH = ROOT / "app" / "gui" / "styles" / "icons" / "microphone-solid.svg"
ASSETS = ROOT / "app" / "assets"

STATES = {
    "idle": "#83a598",        # DESIGN.md dark accent
    "recording": "#fb4934",   # dark danger
    "processing": "#d79921",  # dark warning
}
ICO_SIZES = (16, 24, 32, 48, 256)


def _render(size: int, colour: str) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(str(GLYPH))
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(image.rect(), QColor(colour))
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def _ico(frames: dict[int, bytes]) -> bytes:
    """ICO container with PNG-compressed frames (Windows Vista and later)."""
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = b""
    payload = b""
    for size, png in frames.items():
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        payload += png
    return header + entries + payload


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841 - Qt needs one
    for state, colour in STATES.items():
        (ASSETS / f"tray_{state}.png").write_bytes(_render(32, colour))
        frames = {size: _render(size, colour) for size in ICO_SIZES}
        (ASSETS / f"tray_{state}.ico").write_bytes(_ico(frames))
        print(f"wrote tray_{state}.png and tray_{state}.ico ({colour})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
