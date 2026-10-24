"""Post-processing methods, against a config held in memory.

No test here opens a socket: the connection test is exercised with
``complete`` replaced, and the thread it starts is joined through the
event it emits.
"""

from __future__ import annotations

import queue
from types import SimpleNamespace

import pytest

from app.llm import LLMError
from app.server import rpc
from app.server.rpc import RpcError
from app.server.events import bus
from app.server.handlers import presets


class _Config:
    def __init__(self, llm=None):
        self.data = {"llm": dict(llm or {})}
        self.writes = []

    def get_section(self, name):
        return self.data.get(name, {})

    def update_user_setting(self, section, key, value):
        self.data.setdefault(section, {})[key] = value
        self.writes.append((section, key, value))


class _State:
    def __init__(self):
        self.override = ""

    def profile_override_id(self):
        return self.override

    def set_profile_override(self, profile_id=""):
        self.override = profile_id


def _rt(llm=None, state_manager=True):
    return SimpleNamespace(
        config=_Config(llm),
        state_manager=_State() if state_manager else None,
        stack_error="no audio" if not state_manager else None,
    )


def test_a_fresh_config_materialises_its_implicit_preset_once():
    rt = _rt({"provider": "ollama", "model": "qwen3:8b"})

    first = presets.get(rt, {})
    writes = len(rt.config.writes)
    second = presets.get(rt, {})

    assert [p["id"] for p in first["profiles"]] == ["default"]
    assert first["profiles"][0]["model"] == "qwen3:8b"
    assert first["enabled"] is False
    assert len(rt.config.writes) == writes
    assert second == first


def test_the_switch_is_one_key_and_never_touches_a_preset():
    rt = _rt()
    presets.get(rt, {})
    before = list(rt.config.data["llm"]["profiles"])

    out = presets.set_enabled(rt, {"enabled": True})

    assert out["enabled"] is True
    assert rt.config.data["llm"]["profiles"] == before
    with pytest.raises(rpc.RpcError) as err:
        presets.set_enabled(rt, {"enabled": "yes"})
    assert err.value.code == "bad_params"


def test_update_rewrites_the_preset_and_mirrors_the_active_one_to_the_flat_keys():
    rt = _rt()
    presets.get(rt, {})

    out = presets.update(
        rt,
        {"profile": {"id": "default", "name": "Work", "provider": "openai", "model": "gpt-5.4-mini",
                     "api_key": "sk-test", "timeout_s": 9999, "max_tokens": -4}},
    )

    saved = out["profiles"][0]
    assert saved["name"] == "Work"
    assert saved["timeout_s"] == 600  # clamped, as the dictation will read it
    assert saved["max_tokens"] == 0
    assert saved["remote"] is True
    assert rt.config.data["llm"]["model"] == "gpt-5.4-mini"
    assert rt.config.data["llm"]["api_key"] == "sk-test"


def test_updating_a_preset_that_does_not_exist_is_refused():
    rt = _rt()
    presets.get(rt, {})

    with pytest.raises(rpc.RpcError) as err:
        presets.update(rt, {"profile": {"id": "ghost"}})

    assert err.value.code == "not_found"


def test_create_copies_the_first_preset_and_reports_the_new_id():
    rt = _rt()
    presets.get(rt, {})

    out = presets.create(rt, {})

    assert out["created_id"] == "profile"
    assert [p["id"] for p in out["profiles"]] == ["default", "profile"]
    assert out["profiles"][1]["name"] == "Default copy"


def test_duplicate_keeps_the_credential_with_the_copy():
    rt = _rt()
    presets.get(rt, {})
    presets.update(rt, {"profile": {"id": "default", "api_key": "sk-test"}})

    out = presets.duplicate(rt, {"id": "default"})

    copy = next(p for p in out["profiles"] if p["id"] == out["created_id"])
    assert copy["api_key_set"] is True and "api_key" not in copy
    stored = {p["id"]: p for p in rt.config.data["llm"]["profiles"]}
    assert stored[out["created_id"]]["api_key"] == "sk-test"


def test_deleting_the_active_preset_moves_the_default_and_the_last_one_stays():
    rt = _rt()
    presets.get(rt, {})
    presets.create(rt, {})
    presets.activate(rt, {"id": "profile"})
    assert rt.config.data["llm"]["active_profile"] == "profile"

    out = presets.delete(rt, {"id": "profile"})

    assert out["active_id"] == "default"
    assert rt.config.data["llm"]["active_profile"] == "default"
    with pytest.raises(rpc.RpcError) as err:
        presets.delete(rt, {"id": "default"})
    assert err.value.code == "last_preset"


def test_reset_key_clears_that_preset_and_the_flat_key_only_when_it_is_active():
    rt = _rt()
    presets.get(rt, {})
    presets.update(rt, {"profile": {"id": "default", "api_key": "sk-test"}})
    presets.create(rt, {})
    presets.update(rt, {"profile": {"id": "profile", "api_key": "sk-other"}})

    out = presets.reset_key(rt, {"id": "profile"})

    by_id = {p["id"]: p for p in out["profiles"]}
    assert by_id["profile"]["api_key_set"] is False
    assert by_id["default"]["api_key_set"] is True
    stored = {p["id"]: p for p in rt.config.data["llm"]["profiles"]}
    assert stored["profile"]["api_key"] == ""
    assert rt.config.data["llm"]["api_key"] == "sk-test"


def test_the_override_lives_on_the_state_manager_and_is_not_persisted():
    rt = _rt()
    presets.get(rt, {})
    presets.create(rt, {})
    writes = len(rt.config.writes)

    out = presets.set_override(rt, {"id": "profile"})

    assert out["override_id"] == "profile"
    assert rt.state_manager.override == "profile"
    assert len(rt.config.writes) == writes
    assert presets.set_override(rt, {})["override_id"] == ""


def test_deleting_the_pinned_preset_unpins_it():
    rt = _rt()
    presets.get(rt, {})
    presets.create(rt, {})
    presets.set_override(rt, {"id": "profile"})

    presets.delete(rt, {"id": "profile"})

    assert rt.state_manager.override == ""


def test_privacy_answers_from_the_address_and_falls_back_to_the_provider_default():
    rt = _rt()

    assert presets.privacy(rt, {"base_url": "http://192.168.1.5:1234/v1"})["local"] is False
    assert presets.privacy(rt, {"base_url": "http://localhost:11434"})["local"] is True
    assert presets.privacy(rt, {"base_url": "", "provider": "openai"})["local"] is False
    assert presets.privacy(rt, {"base_url": "", "provider": "ollama"})["local"] is True


def test_the_catalogue_names_every_provider_mode_and_effort():
    out = presets.catalogue(_rt(), {})

    ids = [p["id"] for p in out["providers"]]
    assert "ollama" in ids
    assert ids[-1] == "custom"
    assert [m["id"] for m in out["modes"]] == ["clean", "concise", "formal"]
    assert out["efforts"][0] == "none"
    assert out["limits"]["timeout_max"] == 600


def _wait_for_test_event(sub):
    while True:
        item = sub.get(timeout=5)
        assert item is not None, "the connection test never answered"
        if item[0] == "llm_test":
            return item[1]


def test_the_connection_test_reports_a_failure_without_the_key(monkeypatch):
    rt = _rt()
    presets.get(rt, {})
    presets.update(rt, {"profile": {"id": "default", "model": "m", "api_key": "sk-secret"}})

    def boom(text, settings):
        raise LLMError("the server answered HTTP 401")

    monkeypatch.setattr(presets, "complete", boom)
    sub = bus.subscribe()
    try:
        started = presets.test(rt, {"id": "default", "test_id": "t1"})
        payload = _wait_for_test_event(sub)
    finally:
        sub.close()

    assert started == {"started": True, "test_id": "t1"}
    assert '"ok": false' in payload
    assert "HTTP 401" in payload
    assert "sk-secret" not in payload


def test_the_connection_test_succeeds_with_the_editors_unsaved_values(monkeypatch):
    rt = _rt()
    presets.get(rt, {})
    seen = queue.Queue()
    monkeypatch.setattr(
        presets, "complete", lambda text, settings: seen.put(settings) or "Hello."
    )
    sub = bus.subscribe()
    try:
        presets.test(rt, {"profile": {"id": "default", "model": "typed-not-saved"}, "test_id": "t2"})
        payload = _wait_for_test_event(sub)
    finally:
        sub.close()

    assert '"ok": true' in payload
    assert seen.get(timeout=1).model == "typed-not-saved"


def test_the_connection_test_needs_a_model_and_never_calls_out_without_one(monkeypatch):
    rt = _rt()
    presets.get(rt, {})
    monkeypatch.setattr(presets, "complete", lambda *a: pytest.fail("must not call out"))
    sub = bus.subscribe()
    try:
        presets.test(rt, {"id": "default", "test_id": "t3"})
        payload = _wait_for_test_event(sub)
    finally:
        sub.close()

    assert '"ok": false' in payload
    assert "no model" in payload


# ---- what a preset may hold (QA-SEC-2, QA-RUNTIME-4/6/18) ----------------------

BAD_ADDRESSES = [
    "http://[::1",                       # the one that bricked every call
    "http://[localhost]:1234",
    "myserver",                          # no scheme
    "127.0.0.1:11434",
    "ftp://example.com/v1",
    "file:///etc/passwd",
    "http://",
    "http://host:notaport/v1",
    "http://user:PLANTEDPW@127.0.0.1:18191",
    "http://127.0.0.1:18191/a b",
    "http://127.0.0.1:18191/a\nb",
    "http://127.0.0.1\r\nX-Evil: 1",
    "http://" + "a" * 3000,
]


@pytest.mark.parametrize("address", BAD_ADDRESSES)
def test_a_malformed_address_is_refused_and_nothing_is_saved(address):
    rt = _rt()
    presets.get(rt, {})
    writes = len(rt.config.writes)

    with pytest.raises(rpc.RpcError) as err:
        presets.update(rt, {"profile": {"id": "default", "base_url": address}})

    assert err.value.code == "bad_params" and err.value.field == "base_url"
    assert "PLANTEDPW" not in err.value.message
    assert len(rt.config.writes) == writes
    assert presets.get(rt, {})["profiles"][0]["base_url"] == ""  # still usable


@pytest.mark.parametrize("address", [
    "", "http://localhost:11434", "https://api.openai.com/v1", "http://[::1]:1234/v1",
    "http://192.168.1.5:8080",
])
def test_a_proper_address_is_saved(address):
    rt = _rt()
    presets.get(rt, {})

    out = presets.update(rt, {"profile": {"id": "default", "base_url": address}})

    assert out["profiles"][0]["base_url"] == address
    assert out["profiles"][0]["base_url_error"] is None


def test_a_bad_stored_address_cannot_make_every_call_fail():
    """What the old build left behind: the value is already in the file."""
    rt = _rt({"profiles": [{"id": "default", "name": "Default", "provider": "ollama",
                            "base_url": "http://[::1", "model": "m"}]})

    state = presets.get(rt, {})

    profile = state["profiles"][0]
    assert profile["base_url"] == "http://[::1"
    assert profile["base_url_error"] and "brackets" in profile["base_url_error"]
    assert profile["remote"] is True  # the safe direction
    # and every other call works, including saving something else
    presets.update(rt, {"profile": {"id": "default", "model": "other"}})
    presets.create(rt, {})
    presets.activate(rt, {"id": "default"})
    presets.set_enabled(rt, {"enabled": True})
    assert presets.privacy(rt, {"base_url": "http://[::1"})["valid"] is False
    # it can be repaired from the screen
    fixed = presets.update(rt, {"profile": {"id": "default", "base_url": "http://localhost:11434"}})
    assert fixed["profiles"][0]["base_url_error"] is None


def test_privacy_says_when_the_address_is_not_valid_instead_of_failing():
    rt = _rt()

    out = presets.privacy(rt, {"base_url": "http://[::1"})
    assert out["valid"] is False and out["local"] is False and out["message"]
    assert presets.privacy(rt, {"base_url": "http://localhost:1"})["valid"] is True
    assert presets.privacy(rt, {"base_url": 5})["valid"] is True  # not text: the default


@pytest.mark.parametrize("key", ["abc\ndef", "ключ", "has space", "tab\tkey", "x" * 2000])
def test_an_api_key_that_cannot_be_sent_is_refused_and_never_echoed(key):
    rt = _rt()
    presets.get(rt, {})
    writes = len(rt.config.writes)

    with pytest.raises(rpc.RpcError) as err:
        presets.update(rt, {"profile": {"id": "default", "api_key": key}})

    assert err.value.field == "api_key"
    assert key.strip()[:5] not in err.value.message or key.startswith("x")
    assert len(rt.config.writes) == writes


_JUNK = [
    ("timeout_s", "abc"), ("timeout_s", float("inf")), ("timeout_s", True),
    ("max_tokens", float("inf")), ("max_tokens", "9"), ("max_tokens", [1]),
    ("provider", "nonsense"), ("provider", 5), ("mode", "nonsense"),
    ("reasoning_effort", "extreme"), ("name", "x" * 500), ("name", "a\x00b"),
    ("model", {"a": 1}), ("custom_prompt", "x" * 100_000), ("base_url", 5),
]


# Ids are written out: pytest puts a parameter's text in an environment
# variable, and Windows refuses one longer than 32767 characters, which the
# 100 000 character prompt above is.
@pytest.mark.parametrize(
    "field, value", _JUNK, ids=[f"{n}-{i}" for i, (n, _) in enumerate(_JUNK)]
)
def test_junk_in_any_field_is_refused_with_the_field_named(field, value):
    rt = _rt()
    presets.get(rt, {})

    with pytest.raises(rpc.RpcError) as err:
        presets.update(rt, {"profile": {"id": "default", field: value}})

    assert err.value.code == "bad_params" and err.value.field == field


def test_numbers_outside_the_range_are_clamped_not_replaced_by_the_default():
    rt = _rt()
    presets.get(rt, {})

    low = presets.update(rt, {"profile": {"id": "default", "timeout_s": 0, "max_tokens": -1}})
    assert (low["profiles"][0]["timeout_s"], low["profiles"][0]["max_tokens"]) == (1, 0)
    high = presets.update(rt, {"profile": {"id": "default", "timeout_s": -5 + 10**6,
                                           "max_tokens": 10**9}})
    assert (high["profiles"][0]["timeout_s"], high["profiles"][0]["max_tokens"]) == (600, 32768)


# ---- the key is a flag, not a value (QA-SEC-6) ----------------------------------


def _assert_no_secret(value, secret):
    assert secret not in repr(value)


def test_no_reply_carries_the_key_only_a_flag():
    secret = "sk-PLANTED-SECRET-AAA"
    rt = _rt()
    presets.get(rt, {})

    replies = [
        presets.update(rt, {"profile": {"id": "default", "api_key": secret}}),
        presets.get(rt, {}),
        presets.duplicate(rt, {"id": "default"}),
        presets.create(rt, {}),
        presets.activate(rt, {"id": "default"}),
        presets.set_enabled(rt, {"enabled": True}),
    ]

    for reply in replies:
        _assert_no_secret(reply, secret)
        assert all("api_key" not in p for p in reply["profiles"])
    assert replies[0]["profiles"][0]["api_key_set"] is True
    assert rt.config.data["llm"]["api_key"] == secret  # the dictation still has it


def test_an_edit_that_does_not_type_a_key_keeps_the_stored_one():
    rt = _rt()
    presets.get(rt, {})
    presets.update(rt, {"profile": {"id": "default", "api_key": "sk-keep"}})

    for payload in ({}, {"api_key": None}, {"api_key": ""}, {"api_key": "   "}):
        out = presets.update(rt, {"profile": {"id": "default", "model": "m", **payload}})
        assert out["profiles"][0]["api_key_set"] is True
    assert rt.config.data["llm"]["profiles"][0]["api_key"] == "sk-keep"
    assert rt.config.data["llm"]["api_key"] == "sk-keep"


def test_a_typed_key_replaces_and_reset_key_is_the_only_way_to_remove_one():
    rt = _rt()
    presets.get(rt, {})
    presets.update(rt, {"profile": {"id": "default", "api_key": "sk-old"}})

    presets.update(rt, {"profile": {"id": "default", "api_key": "sk-new"}})
    assert rt.config.data["llm"]["profiles"][0]["api_key"] == "sk-new"

    out = presets.reset_key(rt, {"id": "default"})
    assert out["profiles"][0]["api_key_set"] is False
    assert rt.config.data["llm"]["api_key"] == ""


def test_the_screen_may_send_back_the_fields_it_was_given():
    rt = _rt()
    state = presets.get(rt, {})

    out = presets.update(rt, {"profile": {**state["profiles"][0], "model": "m"}})

    assert out["profiles"][0]["model"] == "m"


def test_a_new_preset_does_not_inherit_the_first_ones_key():
    rt = _rt()
    presets.get(rt, {})
    presets.update(rt, {"profile": {"id": "default", "api_key": "sk-first"}})

    out = presets.create(rt, {})

    copy = next(p for p in out["profiles"] if p["id"] == out["created_id"])
    assert copy["api_key_set"] is False


# ---- the connection test (QA-SEC-10/11, QA-JOURNEYS-16) -------------------------


def test_the_test_of_a_stored_preset_uses_its_key_without_the_screen_having_it(monkeypatch):
    rt = _rt()
    presets.get(rt, {})
    presets.update(rt, {"profile": {"id": "default", "model": "m", "api_key": "sk-stored"}})
    seen = queue.Queue()
    monkeypatch.setattr(presets, "complete", lambda t, s: seen.put(s) or "ok")
    sub = bus.subscribe()
    try:
        presets.test(rt, {"profile": {"id": "default", "model": "typed"}, "test_id": "k1"})
        _wait_for_test_event(sub)
    finally:
        sub.close()

    settings = seen.get(timeout=1)
    assert settings.api_key == "sk-stored" and settings.model == "typed"


def test_a_test_with_a_bad_address_answers_with_the_reason_and_calls_nothing(monkeypatch):
    rt = _rt()
    presets.get(rt, {})
    monkeypatch.setattr(presets, "complete", lambda *a: pytest.fail("must not call out"))
    sub = bus.subscribe()
    try:
        presets.test(rt, {"profile": {"id": "default", "model": "m",
                                      "base_url": "not a url"}, "test_id": "b1"})
        payload = _wait_for_test_event(sub)
    finally:
        sub.close()

    assert '"ok": false' in payload and "spaces" in payload
    assert "ValueError" not in payload


def test_a_server_that_never_finishes_answering_ends_the_test_at_the_deadline(monkeypatch):
    import threading

    rt = _rt()
    presets.get(rt, {})
    presets.update(rt, {"profile": {"id": "default", "model": "m", "timeout_s": 1}})
    release = threading.Event()
    monkeypatch.setattr(presets, "_TEST_GRACE_S", 0.2)
    monkeypatch.setattr(presets, "complete", lambda t, s: release.wait(30) or "late")
    sub = bus.subscribe()
    try:
        started = __import__("time").monotonic()
        presets.test(rt, {"id": "default", "test_id": "d1"})
        payload = _wait_for_test_event(sub)
        elapsed = __import__("time").monotonic() - started
    finally:
        release.set()
        sub.close()

    assert '"ok": false' in payload and "within 1 seconds" in payload
    assert elapsed < 4


def test_connection_tests_in_flight_are_capped_and_the_slot_outlives_the_deadline(monkeypatch):
    """QA-SEC-R4: 300 calls against a server that never answers started 925
    threads. The slot is held by the request thread, so a test that gave up
    waiting does not free it while its thread is still running."""
    import threading
    import time

    rt = _rt()
    presets.get(rt, {})
    presets.update(rt, {"profile": {"id": "default", "model": "m", "timeout_s": 1}})
    release = threading.Event()
    monkeypatch.setattr(presets, "_TEST_GRACE_S", 0.05)
    monkeypatch.setattr(presets, "complete", lambda t, s: release.wait(30) or "late")
    sub = bus.subscribe()
    accepted = 0
    refused = 0
    try:
        for n in range(20):
            try:
                presets.test(rt, {"id": "default", "test_id": f"c{n}"})
                accepted += 1
            except RpcError as exc:
                assert exc.code == "busy"
                refused += 1
        assert accepted == presets._MAX_TESTS and refused == 20 - presets._MAX_TESTS
        # The tests give up after the deadline; their threads are still parked.
        time.sleep(1.5)
        with pytest.raises(RpcError):
            presets.test(rt, {"id": "default", "test_id": "late"})
        release.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                presets.test(rt, {"id": "default", "test_id": "after"})
                break
            except RpcError:
                time.sleep(0.05)
        else:  # pragma: no cover
            raise AssertionError("the slots were never given back")
    finally:
        release.set()
        sub.close()


def test_a_password_in_a_stored_address_is_not_sent_to_the_screen():
    """QA-RUNTIME-F7 / QA-SEC-F5: only a hand-edited config.yaml can hold one."""
    rt = _rt({"provider": "ollama", "model": "m",
              "base_url": "http://user:URLPASSWORDCCC@127.0.0.1:18562/v1"})

    out = presets.get(rt, {})

    assert "URLPASSWORDCCC" not in repr(out)
    shown = out["profiles"][0]
    assert shown["base_url"] == "http://127.0.0.1:18562/v1"
    assert shown["base_url_error"]
