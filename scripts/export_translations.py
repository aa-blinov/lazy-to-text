"""Export the Russian catalogue for the Electron interface.

Reads ``app/i18n/app_ru.ts`` (the Qt catalogue, the single place a
translation is written) and writes ``desktop/renderer/src/i18n/ru.json``,
a flat ``{"English source": "Russian"}`` table. Contexts are dropped: the
renderer looks a string up by its English text, and where two contexts
translate one source differently the first finished entry wins.

    uv run python scripts/export_translations.py
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TS = ROOT / "app" / "i18n" / "app_ru.ts"
OUT = ROOT / "desktop" / "renderer" / "src" / "i18n" / "ru.json"


def export() -> dict[str, str]:
    table: dict[str, str] = {}
    for message in ET.parse(TS).getroot().iter("message"):
        source = message.findtext("source") or ""
        node = message.find("translation")
        text = (node.text or "") if node is not None else ""
        if not source or not text or (node is not None and node.get("type") == "unfinished"):
            continue
        table.setdefault(source, text)
    return table


def main() -> int:
    table = export()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(table, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{len(table)} strings -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
