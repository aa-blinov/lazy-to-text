"""Check that every translatable string has a Russian entry.

The Russian catalogue is ``desktop/renderer/src/i18n/*.json``: a flat
``{"English source": "Russian"}`` table split by area, merged by
``lib/i18n.js``. There is no other source of truth.

Two kinds of string reach it:

* the renderer's own: ``$t('...')``, ``tr('...')`` and ``t('...')`` calls in
  ``desktop/renderer/src`` (a literal, with ``{name}`` placeholders);
* the runtime's: ``mark(context, "...")`` calls in ``app/``, the English
  sentences Python builds (hotkey refusals, model descriptions) that the
  renderer translates by whole string or by ``%1`` template.

A string with no entry is shown in English, which is the right failure at
run time and the wrong one to ship, so this script exits 1 listing them.

    uv run python scripts/check_translations.py
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOGUE = ROOT / "desktop" / "renderer" / "src" / "i18n"
RENDERER = ROOT / "desktop" / "renderer" / "src"
PYTHON = ROOT / "app"

# A call to $t / tr / t whose first argument is a plain string literal.
_CALL = re.compile(
    r"""(?<![\w.$])\$?(?:t|tr)\(\s*
        (?: '((?:[^'\\\n]|\\.)*)' | "((?:[^"\\\n]|\\.)*)" | `((?:[^`\\$]|\\.|\$(?!\{))*)` )""",
    re.X,
)
_ESCAPES = {"n": "\n", "t": "\t", "'": "'", '"': '"', "`": "`", "\\": "\\", "$": "$"}


def _unescape(text: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), text)


def catalogue() -> dict[str, str]:
    table: dict[str, str] = {}
    for path in sorted(CATALOGUE.glob("ru*.json")):
        table.update(json.loads(path.read_text(encoding="utf-8")))
    return table


def renderer_strings() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(RENDERER.rglob("*")):
        if path.suffix not in {".svelte", ".js"} or CATALOGUE in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        for match in _CALL.finditer(text):
            source = _unescape(next(g for g in match.groups() if g is not None))
            if source.strip():
                found.setdefault(source, []).append(str(path.relative_to(ROOT)))
    return found


def python_strings() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(PYTHON.rglob("*.py")):
        if path.name == "translation_mark.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "mark"):
                continue
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                    and isinstance(node.args[1].value, str):
                found.setdefault(node.args[1].value, []).append(
                    f"{path.relative_to(ROOT)}:{node.lineno}"
                )
    return found


def missing() -> dict[str, list[str]]:
    table = catalogue()
    absent: dict[str, list[str]] = {}
    for found in (renderer_strings(), python_strings()):
        for source, where in found.items():
            if not table.get(source):
                absent.setdefault(source, []).extend(where)
    return absent


def unreferenced() -> list[str]:
    """Catalogue entries that no literal call names (informational only).

    A runtime template can be live without appearing literally, so this list
    is never a reason to delete an entry on its own.
    """
    used = set(renderer_strings()) | set(python_strings())
    return sorted(s for s in catalogue() if s not in used)


def main() -> int:
    absent = missing()
    for source, where in sorted(absent.items()):
        print(f"no Russian entry: {source!r}  ({where[0]})")
    print(
        f"{len(catalogue())} entries; {len(renderer_strings())} renderer and "
        f"{len(python_strings())} runtime strings; {len(absent)} missing; "
        f"{len(unreferenced())} entries not named literally"
    )
    return 1 if absent else 0


if __name__ == "__main__":
    sys.exit(main())
