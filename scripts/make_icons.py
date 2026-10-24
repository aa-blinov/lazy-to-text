"""Draw the Electron app's icons in the Monos style.

Warm paper, ink, one corner and a single accent: a tile of Gruvbox paper
carrying three lines of text and a block cursor at the end of the last one.
The colours are the kit's Gruvbox light values (`@monos/ui`, `src/themes.js`)
and this file is where they are written down for the icons, which cannot read
CSS tokens.

Writes `desktop/build/icon.png`, `icon.icns` (macOS, needs `iconutil`),
`icon.ico`, and the tray images in `desktop/assets/`.

    uv run python scripts/make_icons.py
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "desktop" / "build"
ASSETS = ROOT / "desktop" / "assets"

PAPER = QColor("#fbf1c7")
LINE = QColor("#d5c4a1")
INK = QColor("#3c3836")
ACCENT = QColor("#458588")
DANGER = QColor("#cc241d")
WARNING = QColor("#d65d0e")

# Design units on a 1024 canvas. The tile is the macOS icon grid (824 inside
# a 1024 canvas); the corner is the kit's one radius scaled to that tile.
CANVAS = 1024
TILE = QRectF(100, 100, 824, 824)
TILE_RADIUS = 190
BORDER = 8
TEXT_LINES = [(220, 372, 520), (220, 492, 400), (220, 612, 240)]  # x, y, width
LINE_HEIGHT = 56
LINE_RADIUS = 14
CURSOR = QRectF(220 + 240 + 32, 588, 52, 104)


def _painter(image: QImage) -> QPainter:
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    return p


def _glyph(p: QPainter, ink: QColor, cursor: QColor) -> None:
    p.setBrush(ink)
    for x, y, w in TEXT_LINES:
        p.drawRoundedRect(QRectF(x, y, w, LINE_HEIGHT), LINE_RADIUS, LINE_RADIUS)
    p.setBrush(cursor)
    p.drawRoundedRect(CURSOR, LINE_RADIUS, LINE_RADIUS)


def draw_tile(size: int, dot: QColor | None = None) -> QImage:
    """The paper tile, optionally with a status dot in the lower right."""
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    p = _painter(image)
    p.scale(size / CANVAS, size / CANVAS)
    p.setBrush(PAPER)
    p.setPen(QPen(LINE, BORDER))
    inner = TILE.adjusted(BORDER / 2, BORDER / 2, -BORDER / 2, -BORDER / 2)
    p.drawRoundedRect(inner, TILE_RADIUS, TILE_RADIUS)
    p.setPen(Qt.NoPen)
    _glyph(p, INK, ACCENT)
    if dot is not None:
        p.setBrush(PAPER)
        p.drawEllipse(QRectF(640, 640, 300, 300))
        p.setBrush(dot)
        p.drawEllipse(QRectF(676, 676, 228, 228))
    p.end()
    return image


def draw_template(size: int, mark: str) -> QImage:
    """A black-on-transparent glyph for the macOS menu bar, which recolours it."""
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    p = _painter(image)
    p.scale(size / CANVAS, size / CANVAS)
    black = QColor("#000000")
    p.setBrush(black)
    # The tile is dropped: a menu-bar glyph is the lines alone, enlarged.
    p.translate(-60, -120)
    p.scale(1.12, 1.12)
    for x, y, w in TEXT_LINES:
        p.drawRoundedRect(QRectF(x, y, w, LINE_HEIGHT), LINE_RADIUS, LINE_RADIUS)
    if mark == "idle":
        p.drawRoundedRect(CURSOR, LINE_RADIUS, LINE_RADIUS)
    elif mark == "recording":
        p.drawEllipse(QRectF(220 + 240 + 20, 560, 150, 150))
    else:  # processing: three dots after the last line
        for i in range(3):
            p.drawEllipse(QRectF(220 + 240 + 24 + i * 70, 616, 44, 44))
    p.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    return bytes(data)


def write_ico(path: Path, sizes: list[int]) -> None:
    pngs = [(s, png_bytes(draw_tile(s))) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, blobs = b"", b""
    for size, blob in pngs:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    path.write_bytes(header + entries + blobs)


def write_icns(path: Path) -> None:
    if not shutil.which("iconutil"):
        print("iconutil not found: icon.icns left as it was", file=sys.stderr)
        return
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for base in (16, 32, 128, 256, 512):
            draw_tile(base).save(str(iconset / f"icon_{base}x{base}.png"))
            draw_tile(base * 2).save(str(iconset / f"icon_{base}x{base}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(path)], check=True)


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841
    BUILD.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)

    draw_tile(1024).save(str(BUILD / "icon.png"))
    write_ico(BUILD / "icon.ico", [16, 24, 32, 48, 64, 128, 256])
    write_icns(BUILD / "icon.icns")

    # Windows and Linux trays sit on any colour, so they carry the whole tile
    # with a status dot; macOS gets template glyphs.
    for name, dot in (("idle", None), ("recording", DANGER), ("processing", WARNING)):
        draw_tile(64, dot).save(str(ASSETS / f"tray_{name}.png"))
        draw_template(44, name).save(str(ASSETS / f"tray_{name}Template.png"))
    print("icons written to", BUILD.relative_to(ROOT), "and", ASSETS.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
