"""Draw the Electron app's icons in the Monos style.

The same microphone the Qt application has always used (Heroicons
`microphone-solid`, the file in `app/gui/styles/icons/`), on a tile of warm
paper instead of the old green: the capsule in the kit's accent, the cradle
in ink, one border line. The colours are the kit's Gruvbox light values
(`@monos/ui`, `src/themes.js`), written down here because an icon cannot read
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

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "desktop" / "build"
ASSETS = ROOT / "desktop" / "assets"

PAPER = "#fbf1c7"
LINE = "#d5c4a1"
INK = "#3c3836"
ACCENT = "#458588"
DANGER = "#cc241d"
WARNING = "#d65d0e"

# The two paths of the Heroicons glyph, in its 24x24 box: the capsule, then
# the cradle with its stand.
CAPSULE = "M8.25 4.5a3.75 3.75 0 1 1 7.5 0v8.25a3.75 3.75 0 1 1-7.5 0V4.5Z"
CRADLE = (
    "M6 10.5a.75.75 0 0 1 .75.75v1.5a5.25 5.25 0 1 0 10.5 0v-1.5a.75.75 0 0 1 "
    "1.5 0v1.5a6.751 6.751 0 0 1-6 6.709v2.291h3a.75.75 0 0 1 0 1.5h-7.5a.75.75 "
    "0 0 1 0-1.5h3v-2.291a6.751 6.751 0 0 1-6-6.709v-1.5A.75.75 0 0 1 6 10.5Z"
)

# Design units on a 1024 canvas: the macOS icon grid (824 inside 1024), the
# squircle the Qt Dock icon already uses, and a glyph about half the tile.
CANVAS = 1024
TILE = QRectF(100, 100, 824, 824)
SQUIRCLE_N = 5.0
BORDER = 8
GLYPH = 540


def _squircle(rect: QRectF, n: float = SQUIRCLE_N, steps: int = 240) -> QPainterPath:
    path = QPainterPath()
    cx, cy = rect.center().x(), rect.center().y()
    a, b = rect.width() / 2, rect.height() / 2
    import math

    for i in range(steps + 1):
        t = 2 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        x = cx + a * math.copysign(abs(c) ** (2 / n), c)
        y = cy + b * math.copysign(abs(s) ** (2 / n), s)
        (path.moveTo if i == 0 else path.lineTo)(QPointF(x, y))
    path.closeSubpath()
    return path


def _glyph(p: QPainter, rect: QRectF, capsule: str, cradle: str) -> None:
    for d, fill in ((CAPSULE, capsule), (CRADLE, cradle)):
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            f'<path fill="{fill}" d="{d}"/></svg>'
        )
        QSvgRenderer(svg.encode()).render(p, rect)


def _canvas(size: int) -> tuple[QImage, QPainter]:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.scale(size / CANVAS, size / CANVAS)
    return image, p


def draw_tile(size: int, dot: str | None = None) -> QImage:
    """The paper tile with the microphone, optionally with a status dot."""
    image, p = _canvas(size)
    inner = TILE.adjusted(BORDER / 2, BORDER / 2, -BORDER / 2, -BORDER / 2)
    p.setBrush(QColor(PAPER))
    p.setPen(QPen(QColor(LINE), BORDER))
    p.drawPath(_squircle(inner))
    p.setPen(Qt.NoPen)
    box = QRectF(CANVAS / 2 - GLYPH / 2, CANVAS / 2 - GLYPH / 2, GLYPH, GLYPH)
    _glyph(p, box, ACCENT, INK)
    if dot is not None:
        p.setBrush(QColor(PAPER))
        p.drawEllipse(QRectF(640, 640, 300, 300))
        p.setBrush(QColor(dot))
        p.drawEllipse(QRectF(676, 676, 228, 228))
    p.end()
    return image


def draw_template(size: int, mark: str) -> QImage:
    """A black-on-transparent microphone for the macOS menu bar, which recolours it."""
    image, p = _canvas(size)
    p.setPen(Qt.NoPen)
    box = QRectF(CANVAS / 2 - 470, CANVAS / 2 - 470, 940, 940)
    _glyph(p, box, "#000000", "#000000")
    if mark == "recording":
        p.setBrush(QColor("#000000"))
        p.drawEllipse(QRectF(700, 60, 250, 250))
    elif mark == "processing":
        p.setBrush(QColor("#000000"))
        for i in range(3):
            p.drawEllipse(QRectF(620 + i * 112, 90, 78, 78))
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

    # The project site's favicon: the same tile.
    docs = ROOT / "docs"
    if docs.is_dir():
        draw_tile(128).save(str(docs / "favicon.png"))
        write_ico(docs / "favicon.ico", [16, 32, 48])

    # Windows and Linux trays sit on any colour, so they carry the whole tile
    # with a status dot; macOS gets template glyphs.
    for name, dot in (("idle", None), ("recording", DANGER), ("processing", WARNING)):
        draw_tile(64, dot).save(str(ASSETS / f"tray_{name}.png"))
        draw_template(44, name).save(str(ASSETS / f"tray_{name}Template.png"))
    print("icons written to", BUILD.relative_to(ROOT), "and", ASSETS.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
