"""One damaged line must not cost the history around it.

QA-SEC-3 / QA-RUNTIME-17: an undecodable byte emptied the history and the
next rewrite deleted the valid entries; a wrongly typed field made
``history.list`` fail for the whole screen.
"""

from __future__ import annotations

import json
import time

from app.history_manager import HistoryManager


def _line(text, ts, **over):
    obj = {"timestamp": ts, "text": text, "duration": 1.0, "model": "m", "language": "ru"}
    obj.update(over)
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _write(path, *lines):
    path.write_bytes(b"\n".join(lines) + b"\n")


def test_a_half_character_at_the_end_keeps_the_valid_lines(tmp_path):
    f = tmp_path / "h.jsonl"
    _write(f, _line("первая", 1000.0), _line("вторая", 2000.0), b'{"timestamp": 3000.0, "text": "\xd1')

    h = HistoryManager(history_file=str(f))

    assert [e.text for e in h.get_entries()] == ["вторая", "первая"]


def test_a_rewrite_keeps_the_valid_entries_and_the_damaged_line(tmp_path):
    f = tmp_path / "h.jsonl"
    damaged = b'{"timestamp": 3000.0, "text": "\xd1'
    _write(f, _line("первая", 1000.0), _line("вторая", 2000.0), damaged)
    h = HistoryManager(history_file=str(f))

    h.restore_entry(type(h.entries[0])(timestamp=5000.0, text="новая", duration=1, model="m", language="ru"))
    h.remove_by_timestamp(1000.0)

    raw = f.read_bytes()
    assert damaged in raw
    assert "вторая".encode() in raw and "новая".encode() in raw
    assert "первая".encode() not in raw


def test_an_undecodable_byte_inside_the_text_costs_one_character(tmp_path):
    f = tmp_path / "h.jsonl"
    _write(f, b'{"timestamp": 1000.0, "text": "ab\xffcd", "duration": 1, "model": "m", "language": "ru"}')

    h = HistoryManager(history_file=str(f))

    assert len(h.entries) == 1 and h.entries[0].text.startswith("ab") and h.entries[0].text.endswith("cd")


def test_a_wrongly_typed_description_does_not_fail_the_entry(tmp_path):
    f = tmp_path / "h.jsonl"
    _write(f, _line("слова", 1000.0, model=["x"], duration="long", language=5))

    h = HistoryManager(history_file=str(f))

    entry = h.entries[0]
    assert entry.text == "слова" and entry.model == "" and entry.duration == 0.0
    assert entry.language == "auto"
    hash(entry.model)  # what ``alias_for`` needs


def test_lines_without_words_or_time_are_skipped_and_kept(tmp_path):
    f = tmp_path / "h.jsonl"
    bad = [
        _line(["not text"], 1000.0),
        _line("x", "yesterday"),
        _line("x", 1e300),
        _line("x", float("nan")),
        _line("x", True),
        b"[1, 2]",
        b"[" * 200000,
    ]
    _write(f, *bad, _line("good", 2000.0))

    h = HistoryManager(history_file=str(f))
    h.add_entry("fresh", 1.0, "m", "ru")
    h.remove_by_timestamp(2000.0)

    assert [e.text for e in h.entries] == ["fresh"]
    raw = f.read_bytes()
    for line in bad[:6]:
        assert line in raw


def test_an_out_of_range_timestamp_cannot_be_restored_or_formatted(tmp_path):
    from app.history_manager import TranscriptionEntry

    h = HistoryManager(history_file=str(tmp_path / "h.jsonl"))
    for ts in (1e300, float("nan"), -5.0):
        entry = TranscriptionEntry(timestamp=ts, text="x", duration=1, model="m", language="ru")
        assert h.restore_entry(entry) is False
        if ts > 0:
            assert entry.datetime_str == ""
    assert h.entries == []


def test_a_file_that_cannot_be_read_is_never_overwritten(tmp_path, monkeypatch):
    f = tmp_path / "h.jsonl"
    _write(f, _line("keep me", 1000.0))
    original = f.read_bytes()
    real_read = type(f).read_bytes

    def refuse(self):
        if self == f:
            raise PermissionError("locked")
        return real_read(self)

    monkeypatch.setattr(type(f), "read_bytes", refuse)
    h = HistoryManager(history_file=str(f))
    monkeypatch.setattr(type(f), "read_bytes", real_read)

    h.restore_entry(type(h.entries[0]) if h.entries else __import__("app.history_manager", fromlist=["x"]).TranscriptionEntry(
        timestamp=time.time(), text="new", duration=1, model="m", language="ru"))
    h.remove_entry(0)

    assert f.read_bytes() == original


def test_an_append_after_a_cut_off_line_starts_a_new_line(tmp_path):
    f = tmp_path / "h.jsonl"
    f.write_bytes(_line("one", 1000.0) + b"\n" + b'{"timestamp": 2000.0, "te')
    h = HistoryManager(history_file=str(f))

    h.add_entry("two", 1.0, "m", "ru")

    h2 = HistoryManager(history_file=str(f))
    assert [e.text for e in h2.entries] == ["two", "one"]


def test_debug_logging_never_carries_the_dictated_words(tmp_path, caplog):
    import logging

    h = HistoryManager(history_file=str(tmp_path / "h.jsonl"))
    with caplog.at_level(logging.DEBUG, logger="app.history_manager"):
        h.add_entry("секретная фраза диктовки", 1.0, "m", "ru")
        h.remove_entry(0)

    assert "секретная" not in caplog.text
