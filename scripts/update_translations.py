"""Collect UI strings into the Russian catalogue and compile it.

Sources are the literal calls ``bind(obj, "setter", "Context", "Source")`` and
``tr_text("Context", "Source")`` in ``app/``, plus any ``translate`` call Qt's
own tools would see. Entries already in ``app/i18n/app_ru.ts`` keep their
translation. New ones are added unfinished, and listed, so nothing ships in
English by accident.

    uv run python scripts/update_translations.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
TS = ROOT / "app" / "i18n" / "app_ru.ts"
QM = ROOT / "app" / "i18n" / "app_ru.qm"

_CALL = re.compile(
    r'(?:bind\(\s*[\w.\[\]()]+\s*,\s*"\w+"\s*,|tr_text\(|translate\()\s*'
    r'"(?P<ctx>[^"]+)"\s*,\s*"(?P<src>(?:[^"\\]|\\.)*)"',
    re.S,
)
_MESSAGE = re.compile(
    r"<message>\s*<source>(?P<src>.*?)</source>\s*"
    r"<translation(?P<attr>[^>]*)>(?P<tr>.*?)</translation>\s*</message>",
    re.S,
)
_CONTEXT = re.compile(r"<context>\s*<name>(?P<name>.*?)</name>(?P<body>.*?)</context>", re.S)


_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "'": "'", "\\": "\\"}


def _python_unescape(raw: str) -> str:
    """Undo Python string escapes only. Non-ASCII text is already correct."""
    raw = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), raw)
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), raw)


def _join_adjacent_literals(text: str) -> str:
    """``"a "`` newline ``"b"`` is one Python literal; join it before matching.

    A comma between two literals is a separate item, so it is never joined.
    """
    return re.sub(r'"[ \t]*\n[ \t]*"', "", text)


def _source_calls() -> dict[str, list[str]]:
    """Every literal source passed to a translation call, read with ``ast``.

    Recognised: ``bind(obj, setter, ctx, src)``, ``tr_text(ctx, src)``,
    ``tr_format(ctx, src, ...)``, ``tr_count(ctx, n, one=, few=, many=)``, and
    Qt's ``translate(ctx, src)``. ``ast`` joins implicit string concatenation
    and decodes escapes, so the text matches what the program passes at run time.
    """
    import ast

    found: dict[str, list[str]] = {}

    def add(ctx: str, src: str) -> None:
        bucket = found.setdefault(ctx, [])
        if src not in bucket:
            bucket.append(src)

    def const(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    for path in (ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            args = node.args
            if name == "bind" and len(args) >= 4:
                ctx, src = const(args[2]), const(args[3])
                if ctx and src:
                    add(ctx, src)
            elif name in {"tr_text", "tr_format", "translate", "mark"} and len(args) >= 2:
                ctx, src = const(args[0]), const(args[1])
                if ctx and src:
                    add(ctx, src)
            elif name == "tr_count" and args:
                ctx = const(args[0])
                forms = {kw.arg: const(kw.value) for kw in node.keywords}
                if ctx:
                    for key in ("one", "few", "many"):
                        if forms.get(key):
                            add(ctx, forms[key])
    return found


def _existing() -> dict[str, dict[str, tuple[str, str]]]:
    out: dict[str, dict[str, tuple[str, str]]] = {}
    if not TS.exists():
        return out
    text = TS.read_text(encoding="utf-8")
    for ctx in _CONTEXT.finditer(text):
        msgs = {}
        for m in _MESSAGE.finditer(ctx.group("body")):
            msgs[_unescape(m.group("src"))] = (_unescape(m.group("tr")), m.group("attr"))
        out[_unescape(ctx.group("name"))] = msgs
    return out


def _unescape(s: str) -> str:
    return (s.replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&amp;", "&"))


def main() -> int:
    existing = _existing()
    sources = _source_calls()
    unfinished: list[tuple[str, str]] = []

    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<!DOCTYPE TS>",
             '<TS version="2.1" language="ru_RU" sourcelanguage="en_US">']
    contexts = sorted(set(existing) | set(sources))
    for ctx in contexts:
        # Existing translations are kept even when the extractor does not see
        # their call site (runtime sources such as translate(ctx, var)).
        messages = dict(existing.get(ctx, {}))
        for src in sources.get(ctx, []):
            if src not in messages:
                messages[src] = ("", ' type="unfinished"')
                unfinished.append((ctx, src))
        if not messages:
            continue
        lines.append("<context>")
        lines.append(f"    <name>{escape(ctx)}</name>")
        for src in sorted(messages, key=lambda s: sources.get(ctx, []).index(s)
                          if s in sources.get(ctx, []) else 10**6):
            tr, attr = messages[src]
            lines.append("    <message>")
            lines.append(f"        <source>{escape(src)}</source>")
            lines.append(f"        <translation{attr}>{escape(tr)}</translation>")
            lines.append("    </message>")
        lines.append("</context>")
    lines.append("</TS>")
    TS.write_text("\n".join(lines) + "\n", encoding="utf-8")

    subprocess.run(
        [str(ROOT / ".venv" / "bin" / "pyside6-lrelease"), str(TS), "-qm", str(QM)],
        check=True, capture_output=True,
    )
    print(f"{sum(len(v) for v in sources.values())} source calls, "
          f"{len(unfinished)} new and unfinished:")
    for ctx, src in unfinished:
        print(f"  [{ctx}] {src}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
