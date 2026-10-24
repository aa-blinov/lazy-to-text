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
    assert copy["api_key"] == "sk-test"


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
    assert by_id["profile"]["api_key"] == ""
    assert by_id["default"]["api_key"] == "sk-test"
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

    assert out["providers"][0]["id"] == "ollama"
    assert out["providers"][-1]["id"] == "custom"
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
