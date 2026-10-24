"""The History screen's methods, over a real store in a scratch directory."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.history_manager import HistoryManager
from app.server.events import bus
from app.server.handlers import history as handlers
from app.server.rpc import RpcError


@pytest.fixture
def store(tmp_path):
    h = HistoryManager(max_entries=5, history_file=str(tmp_path / "h.jsonl"))
    for i, text in enumerate(["first", "second", "third"]):
        h.add_entry(text, 1.5 + i, "gigaam-v3-ctc", "ru")
        # Distinct, ordered timestamps without sleeping.
        h.entries[0].timestamp = 1000.0 + i
    h._compact()
    return h


def _rt(store):
    return SimpleNamespace(
        history=store,
        config=SimpleNamespace(get_setting=lambda s, k: "ctrl+f8"),
    )


@pytest.fixture
def sub():
    s = bus.subscribe()
    yield s
    s.close()


def test_list_is_newest_first_with_the_alias_and_hotkey(store):
    result = handlers.list_entries(_rt(store), {})

    assert result["enabled"] is True
    assert [e["text"] for e in result["entries"]] == ["third", "second", "first"]
    assert result["entries"][0]["id"] == 1002.0
    assert result["entries"][0]["alias"]
    assert result["start_hotkey"] == "ctrl+f8"


def test_with_no_store_the_screen_is_told_it_is_disabled():
    rt = SimpleNamespace(history=None, config=SimpleNamespace(get_setting=lambda s, k: ""))
    assert handlers.list_entries(rt, {})["enabled"] is False
    with pytest.raises(RpcError) as err:
        handlers.clear(rt, {})
    assert err.value.code == "history_disabled"


def test_delete_removes_from_disk_at_once_and_announces(store, sub):
    result = handlers.delete(_rt(store), {"id": 1001.0})

    assert result["deleted"]["text"] == "second"
    assert result["total"] == 2
    on_disk = [json.loads(l)["text"] for l in open(store.history_file, encoding="utf-8")]
    assert "second" not in on_disk
    names = []
    while (item := sub.get(0.1)) is not None:
        names.append(item[0])
    assert "history" in names


def test_delete_names_the_entry_by_identity_not_position(store):
    # A dictation landing between the click and the request shifts every index.
    store.add_entry("newest", 1.0, "m", "ru")
    result = handlers.delete(_rt(store), {"id": 1001.0})
    assert result["deleted"]["text"] == "second"


def test_deleting_something_already_gone_is_an_error(store):
    with pytest.raises(RpcError) as err:
        handlers.delete(_rt(store), {"id": 5.0})
    assert err.value.code == "not_found"


def test_undo_puts_the_entry_back_in_its_place(store):
    rt = _rt(store)
    deleted = handlers.delete(rt, {"id": 1001.0})["deleted"]

    assert handlers.restore(rt, {"entry": deleted})["total"] == 3
    assert [e.text for e in store.get_entries()] == ["third", "second", "first"]
    reloaded = HistoryManager(max_entries=5, history_file=str(store.history_file))
    assert [e.text for e in reloaded.get_entries()] == ["third", "second", "first"]


def test_undoing_twice_does_not_duplicate(store):
    rt = _rt(store)
    deleted = handlers.delete(rt, {"id": 1001.0})["deleted"]
    handlers.restore(rt, {"entry": deleted})
    with pytest.raises(RpcError) as err:
        handlers.restore(rt, {"entry": deleted})
    assert err.value.code == "not_restored"
    assert len(store.get_entries()) == 3


def test_restore_refuses_what_the_cap_would_drop_at_once(tmp_path):
    h = HistoryManager(max_entries=2, history_file=str(tmp_path / "h.jsonl"))
    for i in range(2):
        h.add_entry(f"t{i}", 1.0, "m", "ru")
        h.entries[0].timestamp = 100.0 + i
    old = {"timestamp": 1.0, "text": "ancient", "duration": 1.0,
           "model": "m", "language": "ru"}
    with pytest.raises(RpcError) as err:
        handlers.restore(_rt(h), {"entry": old})
    assert err.value.code == "not_restored"


def test_restore_rejects_a_malformed_entry(store):
    with pytest.raises(RpcError) as err:
        handlers.restore(_rt(store), {"entry": {"text": "no timestamp"}})
    assert err.value.code == "bad_params"


def test_restore_does_not_put_python_wording_on_the_screen(store):
    with pytest.raises(RpcError) as err:
        handlers.restore(_rt(store), {"entry": {"timestamp": "abc", "text": "x"}})
    assert err.value.message == "That is not a valid history entry."
    assert "float" not in err.value.message


def test_clear_reports_how_many_and_empties_the_file(store):
    assert handlers.clear(_rt(store), {}) == {"cleared": 3}
    assert store.get_entries() == []
    assert open(store.history_file, encoding="utf-8").read() == ""


def test_export_writes_every_entry(store, tmp_path):
    target = tmp_path / "out.txt"
    result = handlers.export(_rt(store), {"path": str(target)})

    assert result["exported"] == 3
    text = target.read_text(encoding="utf-8")
    assert "first" in text and "third" in text


def test_export_of_nothing_and_to_nowhere_fail_with_a_code(store, tmp_path):
    with pytest.raises(RpcError) as err:
        handlers.export(_rt(store), {"path": str(tmp_path / "missing" / "o.txt")})
    assert err.value.code == "bad_path"

    store.clear_history()
    with pytest.raises(RpcError) as err:
        handlers.export(_rt(store), {"path": str(tmp_path / "o.txt")})
    assert err.value.code == "empty"


# ---- entries that could never be listed or deleted (QA-RUNTIME-17) -----------------


@pytest.mark.parametrize("entry", [
    {"timestamp": 1e300, "text": "x"},
    {"timestamp": float("nan"), "text": "x"},
    {"timestamp": float("inf"), "text": "x"},
    {"timestamp": -5.0, "text": "x"},
    {"timestamp": 0.0, "text": "x"},
    {"timestamp": 1500.0, "text": ""},
    {"timestamp": 1500.0, "text": "   "},
    {"timestamp": 1500.0, "text": "x" * 3_000_000},
    {"timestamp": 1500.0, "text": "x", "duration": float("nan")},
    {"timestamp": 1500.0, "text": "x", "duration": -1},
    {"timestamp": 1500.0, "text": "x", "model": "m" * 1000},
    {"timestamp": 10**400, "text": "x"},
])
def test_restore_refuses_an_entry_that_could_not_be_shown_or_found_again(store, entry):
    before = len(store.get_entries())

    with pytest.raises(RpcError) as err:
        handlers.restore(_rt(store), {"entry": entry})

    assert err.value.code == "bad_params" and err.value.field == "entry"
    assert len(store.get_entries()) == before
    handlers.list_entries(_rt(store), {})  # still lists


def test_delete_refuses_a_nan_id(store):
    with pytest.raises(RpcError) as err:
        handlers.delete(_rt(store), {"id": float("nan")})
    assert err.value.code == "bad_params"


def test_one_entry_that_cannot_be_shown_does_not_hide_the_others(store):
    class Broken:
        timestamp, text, duration, model, language = 5.0, "x", 1.0, "m", "ru"

        @property
        def datetime_str(self):
            raise OverflowError("timestamp out of range for platform time_t")

    store.entries.insert(0, Broken())

    result = handlers.list_entries(_rt(store), {})

    assert [e["text"] for e in result["entries"]] == ["third", "second", "first"]
