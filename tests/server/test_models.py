"""Model management handlers, against a runtime built from stand-ins.

No test loads a model or touches the network: the state manager, the backend
and the disk check are fakes, and the one real filesystem the tests use is a
temporary models root.
"""

from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

import pytest

from app.server import rpc
from app.server.events import bus
from app.server.handlers import firstrun, models

_FAKE_REPO_MULTIPLIER = 1

class _Config:
    def __init__(self, **sections):
        self.data = {
            "whisper": {"model": "", "compute_type": "float16"},
            "audio": {"vad_enabled": False},
            "onboarding": {"complete": False},
            "storage": {"models_dir": ""},
            "huggingface": {"token": ""},
            "hotkey": {"start_recording_hotkey": "ctrl+f2", "stop_recording_hotkey": "ctrl+f3"},
            "model_overrides": {},
        }
        self.data.update(sections)
        self.writes = []

    def get_setting(self, section, key):
        return self.data.get(section, {}).get(key)

    def get_section(self, section):
        return self.data.get(section, {})

    def update_user_setting(self, section, key, value):
        self.writes.append((section, key, value))
        self.data.setdefault(section, {})[key] = value


class _StateManager:
    def __init__(self, rt):
        self.rt = rt
        self.requests = []
        self.cancel_result = True
        self.accept = True

    def request_model_change(self, alias, compute):
        self.requests.append((alias, compute))
        if self.accept:
            self.rt.current_state = "model_loading"
        return self.accept

    def cancel_model_change(self):
        if self.cancel_result:
            self.rt.current_state = "idle"
        return self.cancel_result


class _Backend:
    def __init__(self):
        self.pushed = []
        self.vad = []
        self.in_flight = False
        self.status_value = "ready"

    def update_inference_settings(self, settings):
        self.pushed.append(settings)

    def set_vad_enabled(self, enabled):
        self.vad.append(enabled)

    def load_in_flight(self):
        return self.in_flight

    def status(self):
        return self.status_value


def _rt(cached=(), **sections):
    rt = SimpleNamespace(
        config=_Config(**sections),
        backend=_Backend(),
        current_state="idle",
        stack_error=None,
        has_model_on_disk=False,
    )
    rt.state = lambda: rt.current_state
    rt.state_manager = _StateManager(rt)
    return rt


@pytest.fixture
def disk(monkeypatch):
    """Which aliases count as downloaded."""
    present = set()
    monkeypatch.setattr(models, "_cached_map", lambda: {
        m.alias: m.alias in present for m in __import__("app.model_mapping", fromlist=["MODELS"]).MODELS
    })
    return present


@pytest.fixture(autouse=True)
def _quiet_storage(monkeypatch):
    # Size measurement walks the disk on a thread; the tests that care call it.
    monkeypatch.setattr(models, "_measure_storage", lambda rt: None)


def _join(thread):
    if thread is not None:
        thread.join(2)


def _events():
    sub = bus.subscribe()
    seen = []

    def drain(wait=0.2):
        while True:
            item = sub.get(wait)
            if item is None:
                return seen
            seen.append(item)

    return drain


# ---- catalogue ---------------------------------------------------------------


def test_the_catalogue_carries_every_card_field_in_display_order(disk):
    rt = _rt()

    result = models.list_models(rt, {})

    # Sixteen speech models, then the diarization model as a card of its own.
    assert result["models"][-1]["kind"] == "diarization"
    cards = result["models"][:-1]
    assert len(cards) == 16
    assert cards[0]["recommended"] is True
    assert cards[0]["alias"] == "gigaam-v3-ctc"
    rest = [c["size_mb"] for c in cards[1:]]
    assert rest == sorted(rest)
    card = cards[0]
    for key in ("canonical", "display_name", "size_mb", "speed", "quality",
                "languages", "description", "family", "onnx_family", "pitch", "url",
                "wer", "rtf", "shared_with", "inference"):
        assert key in card
    assert card["wer"] == 7.1 and card["rtf"] == "0.018"
    assert card["url"].startswith("https://huggingface.co/")
    assert {l["code"] for l in result["languages"]} >= {None, "ru", "en"}


def test_an_unmeasured_model_renders_blank_rather_than_zero(disk, monkeypatch):
    monkeypatch.setattr("app.model_mapping.MEASURED", {})
    rt = _rt()

    cards = models.list_models(rt, {})["models"]

    assert all(c["wer"] is None and c["rtf"] is None for c in cards)


def test_only_the_engines_with_knobs_carry_an_inference_panel(disk):
    kinds = {c["alias"]: c["inference"]["kind"] for c in models.list_models(_rt(), {})["models"]}

    assert kinds["whisper-base"] == "whisper"
    assert kinds["parakeet-tdt-v3"] == "parakeet"
    assert kinds["gigaam-v3-ctc"] is None
    assert kinds["vosk-ru"] is None


def test_active_is_the_configured_model_only_while_it_is_on_disk(disk):
    rt = _rt(whisper={"model": "vosk-ru", "compute_type": "int8"})

    assert models.state(rt, {})["active"] is None  # not downloaded: no active card
    disk.add("vosk-ru")
    assert models.state(rt, {})["active"] == "vosk-ru"


def test_a_retired_or_unknown_model_leaves_every_card_inactive(disk):
    disk.add("vosk-ru")
    rt = _rt(whisper={"model": "onnx-community/whisper-large-v3", "compute_type": "float16"})

    assert models.state(rt, {})["active"] is None


# ---- selection ---------------------------------------------------------------


def test_select_runs_the_whole_sequence_of_the_qt_controller(disk):
    disk.update({"vosk-ru", "gigaam-v3-ctc"})
    rt = _rt(whisper={"model": "gigaam-v3-ctc", "compute_type": "float16"})
    rt.config.data["model_overrides"]["whisper-base"] = {"language": "ru"}
    disk.add("whisper-base")

    result = models.select(rt, {"alias": "whisper-base"})

    assert result["downloading"] is False and result["noop"] is False
    assert ("whisper", "model", "whisper-base") in rt.config.writes
    from app.model_mapping import get_model

    hint = get_model("whisper-base").compute_type
    assert ("whisper", "compute_type", hint) in rt.config.writes
    assert rt.state_manager.requests == [("whisper-base", hint)]
    _join(_ctx_thread(rt))
    assert rt.backend.pushed and rt.backend.pushed[0].language == "ru"
    assert models._ctx(rt).selecting == "whisper-base"


def _ctx_thread(rt):
    return models._ctx(rt).push_thread


def test_selecting_the_active_model_is_a_no_op(disk):
    disk.add("vosk-ru")
    rt = _rt(whisper={"model": "vosk-ru", "compute_type": "int8"})

    result = models.select(rt, {"alias": "vosk-ru"})

    assert result["noop"] is True
    assert rt.state_manager.requests == []
    assert rt.config.writes == []


def test_a_second_select_during_a_load_is_refused_and_writes_nothing(disk):
    rt = _rt()
    rt.current_state = "model_loading"

    with pytest.raises(rpc.RpcError) as err:
        models.select(rt, {"alias": "vosk-ru"})

    assert err.value.code == "busy"
    assert rt.config.writes == []


def test_a_refused_switch_puts_the_config_back(disk):
    disk.add("gigaam-v3-ctc")
    rt = _rt(whisper={"model": "gigaam-v3-ctc", "compute_type": "float16"})
    rt.state_manager.accept = False

    with pytest.raises(rpc.RpcError) as err:
        models.select(rt, {"alias": "vosk-ru"})

    assert err.value.code == "busy"
    assert rt.config.data["whisper"]["model"] == "gigaam-v3-ctc"
    assert rt.config.data["whisper"]["compute_type"] == "float16"


def test_an_unknown_alias_and_a_missing_stack_have_their_own_codes(disk):
    with pytest.raises(rpc.RpcError) as err:
        models.select(_rt(), {"alias": "nope"})
    assert err.value.code == "unknown_model"

    rt = _rt()
    rt.state_manager = None
    rt.stack_error = "no audio device"
    with pytest.raises(rpc.RpcError) as err:
        models.select(rt, {"alias": "vosk-ru"})
    assert err.value.code == "no_stack" and "no audio device" in err.value.message


def test_download_of_a_cached_model_is_refused_and_of_a_missing_one_selects(disk):
    disk.add("vosk-ru")
    rt = _rt()

    with pytest.raises(rpc.RpcError) as err:
        models.download(rt, {"alias": "vosk-ru"})
    assert err.value.code == "already_cached"

    result = models.download(rt, {"alias": "vosk-ru-small"})
    assert result["downloading"] is True
    assert rt.state_manager.requests[0][0] == "vosk-ru-small"


def test_the_selected_card_is_active_while_its_weights_arrive(disk):
    rt = _rt(whisper={"model": "", "compute_type": "float16"})

    models.select(rt, {"alias": "vosk-ru"})

    assert models.state(rt, {})["active"] == "vosk-ru"
    assert models.state(rt, {})["loading"] is True


# ---- cancel ------------------------------------------------------------------


def test_a_restore_the_state_manager_refuses_is_retried_not_dropped(disk, monkeypatch):
    """QA-RUNTIME-F1: the state manager answers False while it still reads a
    load in progress (the abandoned attempt, a status push on its way). The
    restore used to give up on the first refusal and leave the app on
    "Loading..." with nothing loading."""
    disk.add("gigaam-v3-ctc")
    rt = _rt(whisper={"model": "gigaam-v3-ctc", "compute_type": "float16"})
    models.select(rt, {"alias": "vosk-ru"})
    sm = rt.state_manager
    sm.requests.clear()
    answers = [False, False, True]

    def request(alias, compute):
        sm.requests.append((alias, compute))
        return answers.pop(0)

    monkeypatch.setattr(sm, "request_model_change", request)
    ctx = models._ctx(rt)
    monkeypatch.setattr(ctx, "stop", SimpleNamespace(wait=lambda t=None: False))

    models.cancel_load(rt, {})
    _join(models._ctx(rt).restore_thread)

    assert sm.requests == [("gigaam-v3-ctc", "float16")] * 3


def test_cancel_rolls_back_the_card_the_config_and_reloads_the_previous_model(disk):
    disk.add("gigaam-v3-ctc")
    rt = _rt(whisper={"model": "gigaam-v3-ctc", "compute_type": "float16"})
    models.select(rt, {"alias": "vosk-ru"})
    rt.state_manager.requests.clear()

    result = models.cancel_load(rt, {})

    assert result["cancelled"] is True and result["restored"] == "gigaam-v3-ctc"
    assert rt.config.data["whisper"]["model"] == "gigaam-v3-ctc"
    assert rt.config.data["whisper"]["compute_type"] == "float16"
    assert result["active"] == "gigaam-v3-ctc"
    _join(models._ctx(rt).restore_thread)
    assert rt.state_manager.requests == [("gigaam-v3-ctc", "float16")]


def test_cancel_with_no_previous_model_writes_an_empty_model(disk):
    rt = _rt(whisper={"model": "", "compute_type": "float16"})
    models.select(rt, {"alias": "vosk-ru"})

    result = models.cancel_load(rt, {})

    assert result["restored"] is None and result["active"] is None
    assert rt.config.data["whisper"]["model"] == ""
    assert models._ctx(rt).restore_thread is None


def test_cancel_after_the_load_finished_rolls_nothing_back(disk):
    disk.add("vosk-ru")
    rt = _rt(whisper={"model": "vosk-ru", "compute_type": "int8"})
    rt.state_manager.cancel_result = False
    writes = list(rt.config.writes)

    result = models.cancel_load(rt, {})

    assert result["cancelled"] is False
    assert rt.config.writes == writes


def test_the_restore_waits_for_the_abandoned_load_to_unwind(disk):
    disk.add("gigaam-v3-ctc")
    rt = _rt(whisper={"model": "gigaam-v3-ctc", "compute_type": "float16"})
    models.select(rt, {"alias": "vosk-ru"})
    rt.state_manager.requests.clear()
    rt.backend.in_flight = True

    models.cancel_load(rt, {})
    time.sleep(0.5)
    assert rt.state_manager.requests == []  # the backend would refuse it
    rt.backend.in_flight = False
    _join(models._ctx(rt).restore_thread)

    assert rt.state_manager.requests == [("gigaam-v3-ctc", "float16")]


def test_a_restore_does_not_override_a_newer_choice(disk):
    disk.add("gigaam-v3-ctc")
    rt = _rt(whisper={"model": "gigaam-v3-ctc", "compute_type": "float16"})
    models.select(rt, {"alias": "vosk-ru"})
    rt.state_manager.requests.clear()
    rt.backend.in_flight = True
    models.cancel_load(rt, {})

    models._ctx(rt).generation += 1  # the user picked something else
    rt.backend.in_flight = False
    _join(models._ctx(rt).restore_thread)

    assert rt.state_manager.requests == []


# ---- state changes ------------------------------------------------------------


def test_a_load_that_ends_reports_how_and_refreshes_the_cache(disk):
    rt = _rt(whisper={"model": "vosk-ru", "compute_type": "int8"})
    drain = _events()
    models.on_state_change(rt, "idle", "model_loading")
    disk.add("vosk-ru")
    rt.backend.status_value = "ready"

    models.on_state_change(rt, "model_loading", "idle")

    names = {n: __import__("json").loads(p) for n, p in drain()}
    assert names["model_load"] == {"alias": "vosk-ru", "outcome": "ready"}
    assert names["models"]["cached"]["vosk-ru"] is True
    assert rt.has_model_on_disk is True


@pytest.mark.parametrize("status,outcome", [("error", "error"), ("stopped", "cancelled")])
def test_a_failed_or_cancelled_load_is_named(disk, status, outcome):
    rt = _rt(whisper={"model": "vosk-ru", "compute_type": "int8"})
    rt.backend.status_value = status
    drain = _events()
    models.on_state_change(rt, "idle", "model_loading")
    models.on_state_change(rt, "model_loading", "idle")

    got = [__import__("json").loads(p) for n, p in drain() if n == "model_load"]

    assert got[0]["outcome"] == outcome
    # QA-JOURNEYS-R3: a failed load carries a sentence for the user, and no
    # runtime exception text.
    assert ("reason" in got[0]) == (outcome == "error")
    assert ("reason" in models.state(rt, {})["last_load"]) == (outcome == "error")
    if outcome == "error":
        assert "Traceback" not in got[0]["reason"] and "Exception" not in got[0]["reason"]


def test_a_failed_download_does_not_leave_a_card_claiming_to_be_loaded(disk):
    rt = _rt(whisper={"model": "", "compute_type": "float16"})
    models.select(rt, {"alias": "vosk-ru"})
    rt.backend.status_value = "error"
    rt.current_state = "idle"

    models.on_state_change(rt, "model_loading", "idle")

    assert models.state(rt, {})["active"] is None


# ---- deletion ----------------------------------------------------------------


def _fake_repo(root, canonical, payload=b"x" * 1000):
    global _FAKE_REPO_MULTIPLIER
    repo = root / "hub" / f"models--{canonical.replace('/', '--')}"
    (repo / "blobs").mkdir(parents=True)
    (repo / "snapshots" / "abc").mkdir(parents=True)
    (repo / "blobs" / "w").write_bytes(payload)
    snapshot_model = repo / "snapshots" / "abc" / "model.onnx"
    blob = repo / "blobs" / "w"
    try:
        snapshot_model.symlink_to(blob)
    except OSError as exc:
        # Windows denies symlink creation when the test account lacks
        # SeCreateSymbolicLinkPrivilege; HF also copies in that situation.
        if os.name != "nt" or getattr(exc, "winerror", None) != 1314:
            raise
        import shutil

        shutil.copy2(blob, snapshot_model)
        _FAKE_REPO_MULTIPLIER = 2
    return repo


def test_delete_info_measures_the_real_bytes_without_following_links(disk, tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    from app.model_mapping import get_model

    info = get_model("vosk-ru-small")
    _fake_repo(tmp_path, info.canonical, b"x" * 4096)
    if _FAKE_REPO_MULTIPLIER == 2:
        pytest.skip("Windows without symlink privilege uses distinct cache copies")
    disk.add("vosk-ru-small")

    result = models.delete_info(_rt(), {"alias": "vosk-ru-small"})

    assert result["size_bytes"] == 4096  # once, not once per link
    assert result["catalogue_mb"] == info.size_mb
    assert result["cached"] is True


def test_delete_removes_the_cache_reports_the_freed_size_and_refreshes(disk, tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    from app.model_mapping import get_model

    info = get_model("vosk-ru-small")
    repo = _fake_repo(tmp_path, info.canonical, b"x" * 2048)
    disk.add("vosk-ru-small")
    rt = _rt()
    drain = _events()

    assert models.delete(rt, {"alias": "vosk-ru-small"}) == {"started": True}
    deadline = time.time() + 3
    while repo.exists() and time.time() < deadline:
        time.sleep(0.02)
    got = [(n, __import__("json").loads(p)) for n, p in drain(0.4)]

    done = [p for n, p in got if n == "model_delete"][0]
    assert done["deleted"] is True and done["freed_bytes"] == 2048 * _FAKE_REPO_MULTIPLIER
    assert not repo.exists()


def test_delete_refuses_the_active_model_and_a_missing_one(disk):
    disk.add("vosk-ru")
    rt = _rt(whisper={"model": "vosk-ru", "compute_type": "int8"})

    with pytest.raises(rpc.RpcError) as err:
        models.delete(rt, {"alias": "vosk-ru"})
    assert err.value.code == "in_use"
    with pytest.raises(rpc.RpcError) as err:
        models.delete(rt, {"alias": "whisper-base"})
    assert err.value.code == "not_cached"


def test_delete_refuses_a_variant_that_shares_files_with_the_active_model(disk, monkeypatch):
    from app.model_mapping import ModelInfo, MODELS

    base = MODELS[0]
    sibling = ModelInfo(
        alias="twin", canonical=base.canonical, display_name="Twin", size_mb=1,
        speed="fast", quality="good", languages="Russian", description="d", family="GigaAM",
        onnx_family="gigaam",
    )
    monkeypatch.setattr("app.model_mapping.MODELS", MODELS + (sibling,))
    monkeypatch.setattr("app.model_mapping._BY_ALIAS", {**{m.alias: m for m in MODELS}, "twin": sibling})
    monkeypatch.setattr(models, "_cached_map", lambda: {m.alias: True for m in MODELS + (sibling,)})
    rt = _rt(whisper={"model": base.alias, "compute_type": "float16"})

    with pytest.raises(rpc.RpcError) as err:
        models.delete(rt, {"alias": "twin"})

    assert err.value.code == "in_use"


# ---- inference settings --------------------------------------------------------


def test_whisper_settings_persist_under_the_alias_and_push_only_when_active(disk):
    disk.update({"whisper-base", "vosk-ru"})
    rt = _rt(whisper={"model": "vosk-ru", "compute_type": "int8"})

    inactive = models.inference_set(rt, {"alias": "whisper-base", "values": {"language": "en", "beam_size": 99}})

    assert inactive["pushed"] is False and rt.backend.pushed == []
    assert inactive["values"]["language"] == "en"
    assert inactive["values"]["beam_size"] == 20  # clamped, as the Qt value object does
    assert rt.config.data["model_overrides"]["whisper-base"]["language"] == "en"

    rt.config.data["whisper"]["model"] = "whisper-base"
    active = models.inference_set(rt, {"alias": "whisper-base", "values": {"temperature": 5}})

    assert active["pushed"] is True
    _join(models._ctx(rt).push_thread)
    assert rt.backend.pushed[-1].temperature == 1.0
    assert rt.backend.pushed[-1].language == "en"  # the earlier field survived


def test_a_partial_update_does_not_reset_its_neighbours(disk):
    rt = _rt()
    models.inference_set(rt, {"alias": "whisper-base", "values": {"initial_prompt": "Anthropic"}})

    out = models.inference_set(rt, {"alias": "whisper-base", "values": {"language": "ru"}})

    assert out["values"]["initial_prompt"] == "Anthropic"


def test_auto_detect_is_stored_as_none(disk):
    rt = _rt()

    out = models.inference_set(rt, {"alias": "whisper-base", "values": {"language": ""}})

    assert out["values"]["language"] is None


def test_parakeet_has_one_flag_and_gigaam_has_none(disk):
    rt = _rt()

    out = models.inference_set(rt, {"alias": "parakeet-tdt-v3", "values": {"timestamps": True}})
    assert out["kind"] == "parakeet" and out["values"] == {"timestamps": True}

    with pytest.raises(rpc.RpcError) as err:
        models.inference_set(rt, {"alias": "gigaam-v3-ctc", "values": {}})
    assert err.value.code == "no_settings"


def test_a_bad_stored_override_falls_back_to_defaults_per_field(disk):
    rt = _rt()
    rt.config.data["model_overrides"]["whisper-base"] = {"beam_size": "many", "temperature": "hot", "language": "ru"}

    out = models.inference_get(rt, {"alias": "whisper-base"})

    assert out["values"]["beam_size"] == 5 and out["values"]["temperature"] == 0.0
    assert out["values"]["language"] == "ru"


def test_a_burst_of_pushes_collapses_to_the_latest(disk):
    rt = _rt()
    gate = threading.Event()
    seen = []

    def slow(settings):
        seen.append(settings)
        gate.wait(2)

    rt.backend.update_inference_settings = slow
    for n in range(5):
        models.push_inference(rt, n)
        time.sleep(0.02)
    gate.set()
    _join(models._ctx(rt).push_thread)

    assert seen[0] == 0 and seen[-1] == 4 and len(seen) <= 3


def test_startup_pushes_the_active_overrides_and_the_vad_switch(disk):
    disk.add("whisper-base")
    rt = _rt(whisper={"model": "whisper-base", "compute_type": "float32"}, audio={"vad_enabled": True})
    rt.config.data["model_overrides"]["whisper-base"] = {"language": "ru"}
    models.stop_watcher(rt)

    models.apply_startup(rt)
    _join(models._ctx(rt).push_thread)
    _join(models._ctx(rt).watcher)
    time.sleep(0.1)

    assert rt.backend.pushed[0].language == "ru"
    assert rt.backend.vad == [True]


# ---- storage ----------------------------------------------------------------------


def _storage_rt(tmp_path, monkeypatch, configured=""):
    monkeypatch.setattr("app.utils.get_project_models_path", lambda: str(tmp_path / "default"))
    # The apply step plants these in the process; registering them here makes
    # the monkeypatch put the environment back.
    monkeypatch.setenv("HF_HOME", "")
    monkeypatch.setenv("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    return _rt(storage={"models_dir": configured})


def _wait_done(drain):
    deadline = time.time() + 5
    got = []
    while time.time() < deadline:
        got = [(n, __import__("json").loads(p)) for n, p in drain(0.2)]
        done = [p for n, p in got if n == "storage" and p["phase"] in ("done", "error")]
        if done:
            return got, done[0]
    raise AssertionError("storage change never finished")


def test_storage_get_names_the_default_folder(tmp_path, monkeypatch):
    rt = _storage_rt(tmp_path, monkeypatch)

    out = models.storage_get(rt, {})

    assert out["is_default"] is True and out["path"] == str(tmp_path / "default")
    assert out["size_bytes"] is None  # arrives as an event


def test_plan_says_what_a_choice_would_do_and_rejects_a_non_folder(tmp_path, monkeypatch):
    old = tmp_path / "old"
    _fake_repo(old, "a/b", b"x" * 300)
    new = tmp_path / "new"
    new.mkdir()
    rt = _storage_rt(tmp_path, monkeypatch, configured=str(old))

    plan = models.storage_plan(rt, {"path": str(new)})

    assert plan["same"] is False and plan["old_size"] == 300 * _FAKE_REPO_MULTIPLIER
    assert models.storage_plan(rt, {"path": str(old)})["same"] is True
    with pytest.raises(rpc.RpcError) as err:
        models.storage_plan(rt, {"path": str(tmp_path / "nope")})
    assert err.value.code == "bad_path"


def test_leave_redirects_new_downloads_and_keeps_old_weights(tmp_path, monkeypatch):
    old = tmp_path / "old"
    _fake_repo(old, "a/b", b"x" * 300)
    new = tmp_path / "new"
    new.mkdir()
    rt = _storage_rt(tmp_path, monkeypatch, configured=str(old))
    drain = _events()

    models.storage_apply(rt, {"path": str(new), "move": False})
    _, done = _wait_done(drain)

    assert done["changed"] is True and done["moved"] is False and done["left_bytes"] == 300 * _FAKE_REPO_MULTIPLIER
    assert rt.config.data["storage"]["models_dir"] == str(new)
    assert os.environ["HF_HOME"] == str(new)
    assert (old / "hub").exists()


def test_move_relocates_the_hub_folder_and_reports_progress(tmp_path, monkeypatch):
    old = tmp_path / "old"
    _fake_repo(old, "a/b", b"x" * 300)
    new = tmp_path / "new"
    new.mkdir()
    rt = _storage_rt(tmp_path, monkeypatch, configured=str(old))
    drain = _events()

    models.storage_apply(rt, {"path": str(new), "move": True})
    got, done = _wait_done(drain)

    assert done["moved"] is True and done["moved_bytes"] == 300 * _FAKE_REPO_MULTIPLIER
    assert (new / "hub").is_dir() and not (old / "hub").exists()
    assert any(p["phase"] == "moving" and p["total_bytes"] == 300 * _FAKE_REPO_MULTIPLIER for n, p in got if n == "storage")


def test_move_onto_existing_weights_is_skipped_with_a_code(tmp_path, monkeypatch):
    old = tmp_path / "old"
    _fake_repo(old, "a/b", b"x" * 300)
    new = tmp_path / "new"
    _fake_repo(new, "c/d", b"y" * 10)
    rt = _storage_rt(tmp_path, monkeypatch, configured=str(old))
    drain = _events()

    models.storage_apply(rt, {"path": str(new), "move": True})
    _, done = _wait_done(drain)

    assert done["moved"] is False and done["skipped"] == "destination_exists"
    assert rt.config.data["storage"]["models_dir"] == str(new)


def test_reset_returns_to_the_default(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    rt = _storage_rt(tmp_path, monkeypatch, configured=str(other))
    drain = _events()

    models.storage_reset(rt, {})
    _, done = _wait_done(drain)

    assert rt.config.data["storage"]["models_dir"] == ""
    assert done["is_default"] is True and done["path"] == str(tmp_path / "default")


def test_a_second_storage_change_is_refused_while_one_runs(tmp_path, monkeypatch):
    rt = _storage_rt(tmp_path, monkeypatch)
    models._ctx(rt).storage_busy = True

    with pytest.raises(rpc.RpcError) as err:
        models.storage_reset(rt, {})

    assert err.value.code == "busy"


def test_a_storage_change_during_a_load_is_refused(tmp_path, monkeypatch):
    rt = _storage_rt(tmp_path, monkeypatch)
    rt.current_state = "model_loading"

    with pytest.raises(rpc.RpcError) as err:
        models.storage_reset(rt, {})

    assert err.value.code == "busy"


# ---- Hugging Face token --------------------------------------------------------------


def test_the_token_is_stored_applied_to_the_environment_and_never_returned(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    rt = _rt()

    out = models.hf_token_set(rt, {"token": "  hf_secret  "})

    assert out == {"set": True}
    assert rt.config.data["huggingface"]["token"] == "hf_secret"
    assert os.environ["HF_TOKEN"] == "hf_secret"
    assert os.environ["HUGGING_FACE_HUB_TOKEN"] == "hf_secret"
    assert "hf_secret" not in repr(models.hf_token_get(rt, {}))

    assert models.hf_token_reset(rt, {}) == {"set": False}
    assert "HF_TOKEN" not in os.environ and "HUGGING_FACE_HUB_TOKEN" not in os.environ


# ---- first run ---------------------------------------------------------------------------


def test_first_run_shows_only_with_no_model_and_no_flag(monkeypatch):
    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: False)
    rt = _rt()

    out = firstrun.status(rt, {})

    assert out["show"] is True and out["candidate"] == "gigaam-v3-ctc"
    assert out["hotkeys"] == {"start": "ctrl+f2", "stop": "ctrl+f3"}

    rt.config.data["onboarding"]["complete"] = True
    assert firstrun.status(rt, {})["show"] is False


def test_a_model_on_disk_suppresses_first_run_whatever_the_flag_says(monkeypatch):
    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: info.alias == "vosk-ru")
    rt = _rt()

    assert firstrun.status(rt, {})["show"] is False
    assert rt.has_model_on_disk is True


def test_set_up_later_ends_first_run_for_the_session_and_leaves_the_flag_alone(monkeypatch):
    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: False)
    rt = _rt()

    assert firstrun.defer(rt, {"reason": "later"}) == {"deferred": True}

    assert firstrun.status(rt, {})["show"] is False
    assert rt.config.data["onboarding"]["complete"] is False  # it returns next launch
    assert rt.config.writes == []


def test_the_snapshot_honours_the_deferral(monkeypatch):
    from app.server.handlers import core

    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: False)
    rt = _rt()
    rt.engine = lambda: {}
    rt.phase = lambda: ""
    rt.log_path = ""
    rt.config.get_section = lambda s: {}

    assert core.snapshot(rt, {})["first_run"] is True
    firstrun.defer(rt, {})
    assert core.snapshot(rt, {})["first_run"] is False


def test_start_dictating_writes_the_flag_exactly_once():
    rt = _rt()

    firstrun.complete(rt, {})
    firstrun.complete(rt, {})

    assert [w for w in rt.config.writes if w[:2] == ("onboarding", "complete")] == [
        ("onboarding", "complete", True)
    ]


def test_every_method_is_registered():
    rpc.load_handlers()
    names = set(rpc.method_names())

    assert {"models.list", "models.state", "models.select", "models.download",
            "models.cancel_load", "models.delete", "models.delete_info",
            "models.inference.get", "models.inference.set", "models.storage.get",
            "models.storage.plan", "models.storage.apply", "models.storage.reset",
            "models.storage.open", "models.hf_token.get", "models.hf_token.set",
            "models.hf_token.reset", "firstrun.status", "firstrun.complete",
            "firstrun.defer"} <= names


# ---- a destination inside the models folder must not destroy it (QA-RUNTIME-2) --


def _root_with_weights(tmp_path):
    root = tmp_path / "models"
    _fake_repo(root, "a/b", b"x" * 300)
    return root


def _tree_bytes(root):
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink())


@pytest.mark.parametrize("where", ["hub", "hub/models--a--b", "newfolder/deeper"])
def test_a_folder_inside_the_models_folder_is_refused_by_plan_and_apply(tmp_path, monkeypatch, where):
    root = _root_with_weights(tmp_path)
    inside = root / where
    inside.mkdir(parents=True, exist_ok=True)
    rt = _storage_rt(tmp_path, monkeypatch, configured=str(root))

    for call in (models.storage_plan, lambda r, p: models.storage_apply(r, {**p, "move": True})):
        with pytest.raises(rpc.RpcError) as err:
            call(rt, {"path": str(inside)})
        assert err.value.code == "bad_path" and "inside" in err.value.message

    assert _tree_bytes(root) == 300 * _FAKE_REPO_MULTIPLIER
    assert models._ctx(rt).storage_busy is False
    assert rt.config.data["storage"]["models_dir"] == str(root)


def test_a_parent_of_the_models_folder_is_refused_too(tmp_path, monkeypatch):
    root = _root_with_weights(tmp_path)
    rt = _storage_rt(tmp_path, monkeypatch, configured=str(root))

    with pytest.raises(rpc.RpcError) as err:
        models.storage_apply(rt, {"path": str(tmp_path), "move": True})

    assert err.value.code == "bad_path" and "contains" in err.value.message
    assert _tree_bytes(root) == 300 * _FAKE_REPO_MULTIPLIER


def test_a_link_into_the_models_folder_is_the_same_as_the_folder_itself(tmp_path, monkeypatch):
    root = _root_with_weights(tmp_path)
    link = tmp_path / "shortcut"
    try:
        link.symlink_to(root / "hub", target_is_directory=True)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise
    rt = _storage_rt(tmp_path, monkeypatch, configured=str(root))

    with pytest.raises(rpc.RpcError):
        models.storage_apply(rt, {"path": str(link), "move": True})

    assert _tree_bytes(root) == 300 * _FAKE_REPO_MULTIPLIER


def test_the_worker_rechecks_a_destination_that_changed_after_the_call(tmp_path, monkeypatch):
    """The relation is decided again where the move happens."""
    root = _root_with_weights(tmp_path)
    inside = root / "hub"
    rt = _storage_rt(tmp_path, monkeypatch, configured=str(root))
    models._ctx(rt).storage_busy = True
    drain = _events()

    models._storage_worker(rt, str(inside), True)

    got = [__import__("json").loads(p) for n, p in drain() if n == "storage"]
    assert got[-1]["phase"] == "error"
    assert _tree_bytes(root) == 300 * _FAKE_REPO_MULTIPLIER
    assert rt.config.data["storage"]["models_dir"] == str(root)


def test_move_hub_refuses_overlapping_folders_before_touching_anything(tmp_path):
    root = _root_with_weights(tmp_path)

    for dst in (root / "hub" / "hub", root, tmp_path):
        out = models.move_hub(str(root / "hub"), str(dst))
        assert out["moved"] is False
    assert _tree_bytes(root) == 300 * _FAKE_REPO_MULTIPLIER


def test_a_copy_that_does_not_match_keeps_the_original_and_removes_the_partial_copy(tmp_path, monkeypatch):
    root = _root_with_weights(tmp_path)
    dst = tmp_path / "other" / "hub"
    monkeypatch.setattr(os, "rename", lambda a, b: (_ for _ in ()).throw(OSError(18, "cross-device")))
    real_copytree = models.shutil.copytree
    depth = []

    def short_copy(src, target, *a, **kw):
        if depth:  # copytree recurses through the module attribute
            return real_copytree(src, target, *a, **kw)
        depth.append(1)
        real_copytree(src, target, *a, **kw)
        for victim in list(__import__("pathlib").Path(target).rglob("w")):
            victim.write_bytes(b"x")  # a truncated file

    monkeypatch.setattr(models.shutil, "copytree", short_copy)

    out = models.move_hub(str(root / "hub"), str(dst))

    assert out["moved"] is False and "copy failed" in out["reason"]
    assert _tree_bytes(root) == 300 * _FAKE_REPO_MULTIPLIER
    assert not dst.exists()


def test_a_verified_copy_across_volumes_moves_the_tree_and_then_removes_the_source(tmp_path, monkeypatch):
    root = _root_with_weights(tmp_path)
    dst = tmp_path / "other" / "hub"
    monkeypatch.setattr(os, "rename", lambda a, b: (_ for _ in ()).throw(OSError(18, "cross-device")))

    out = models.move_hub(str(root / "hub"), str(dst))

    assert out == {"moved": True, "bytes": 300 * _FAKE_REPO_MULTIPLIER}
    assert _tree_bytes(tmp_path / "other") == 300 * _FAKE_REPO_MULTIPLIER and not (root / "hub").exists()


def test_a_copy_that_fails_midway_keeps_the_source(tmp_path, monkeypatch):
    root = _root_with_weights(tmp_path)
    dst = tmp_path / "other" / "hub"
    monkeypatch.setattr(os, "rename", lambda a, b: (_ for _ in ()).throw(OSError(18, "cross-device")))
    monkeypatch.setattr(models.shutil, "copytree",
                        lambda *a, **k: (_ for _ in ()).throw(OSError(28, "No space left")))

    out = models.move_hub(str(root / "hub"), str(dst))

    assert out["moved"] is False and models._friendly_reason(out["reason"]) == "copy_failed"
    assert _tree_bytes(root) == 300 * _FAKE_REPO_MULTIPLIER


def test_apply_refuses_a_folder_that_cannot_be_written(tmp_path, monkeypatch):
    rt = _storage_rt(tmp_path, monkeypatch)
    monkeypatch.setattr(os, "access", lambda p, mode: False)
    target = tmp_path / "ro"
    target.mkdir()

    with pytest.raises(rpc.RpcError) as err:
        models.storage_apply(rt, {"path": str(target), "move": False})

    assert err.value.code == "bad_path"
    assert rt.config.data["storage"]["models_dir"] == ""


# ---- conflicting operations are refused (QA-RUNTIME-12) -------------------------


def test_select_is_refused_while_the_same_model_is_being_deleted(disk):
    disk.add("vosk-ru")
    rt = _rt(whisper={"model": "gigaam-v3-ctc", "compute_type": "float16"})
    models._ctx(rt).deleting.add("vosk-ru")

    for call in (models.select, models.download):
        with pytest.raises(rpc.RpcError) as err:
            call(rt, {"alias": "vosk-ru"})
        assert err.value.code in ("busy", "already_cached")
    with pytest.raises(rpc.RpcError) as err:
        models.select(rt, {"alias": "vosk-ru"})
    assert err.value.code == "busy" and "deleted" in err.value.message
    assert rt.state_manager.requests == []
    assert rt.config.data["whisper"]["model"] == "gigaam-v3-ctc"


def test_select_is_refused_while_a_variant_sharing_the_files_is_being_deleted(disk):
    rt = _rt(whisper={"model": "", "compute_type": "float16"})
    models._ctx(rt).deleting.add("gigaam-v3-rnnt")

    with pytest.raises(rpc.RpcError) as err:
        models.select(rt, {"alias": "gigaam-v3-ctc"})
    assert err.value.code == "busy"


def test_select_and_delete_are_refused_while_the_folder_is_being_changed(disk):
    disk.add("vosk-ru")
    rt = _rt(whisper={"model": "gigaam-v3-ctc", "compute_type": "float16"})
    models._ctx(rt).storage_busy = True

    with pytest.raises(rpc.RpcError) as err:
        models.select(rt, {"alias": "vosk-ru"})
    assert err.value.code == "busy"
    with pytest.raises(rpc.RpcError) as err:
        models.delete(rt, {"alias": "vosk-ru"})
    assert err.value.code == "busy"


def test_a_storage_change_is_refused_while_a_model_is_being_deleted(tmp_path, monkeypatch):
    rt = _storage_rt(tmp_path, monkeypatch)
    models._ctx(rt).deleting.add("vosk-ru")

    with pytest.raises(rpc.RpcError) as err:
        models.storage_reset(rt, {})
    assert err.value.code == "busy"


# ---- cancel tells the truth (QA-RUNTIME-7) --------------------------------------


class _LoadingBackend(_Backend):
    """A backend that is still loading although the state manager's flag is down."""

    def __init__(self):
        super().__init__()
        self.status_value = "loading"
        self.cancelled = 0

    def cancel_load(self):
        self.cancelled += 1
        self.status_value = "stopped"


def test_a_load_the_state_manager_lost_track_of_is_still_cancelled(disk):
    disk.add("gigaam-v3-ctc")
    rt = _rt(whisper={"model": "gigaam-v3-ctc", "compute_type": "float16"})
    rt.backend = _LoadingBackend()
    models.select(rt, {"alias": "vosk-ru"})
    rt.state_manager.cancel_result = False  # its flag was cleared by the watcher
    cleared = []
    rt.state_manager.set_model_loading = cleared.append
    rt.current_state = "model_loading"

    result = models.cancel_load(rt, {})

    assert result["cancelled"] is True and rt.backend.cancelled == 1
    assert cleared == [False]
    assert result["restored"] == "gigaam-v3-ctc"
    assert rt.config.data["whisper"]["model"] == "gigaam-v3-ctc"


def test_a_cancel_with_nothing_loading_says_false_and_touches_nothing(disk):
    rt = _rt(whisper={"model": "vosk-ru", "compute_type": "int8"})
    rt.backend = _LoadingBackend()
    rt.backend.status_value = "ready"
    rt.state_manager.cancel_result = False
    writes = list(rt.config.writes)

    result = models.cancel_load(rt, {})

    assert result["cancelled"] is False and rt.backend.cancelled == 0
    assert rt.config.writes == writes


def test_the_outcome_of_the_last_load_is_part_of_the_state(disk):
    rt = _rt(whisper={"model": "vosk-ru", "compute_type": "int8"})
    assert models.state(rt, {})["last_load"] is None
    models.on_state_change(rt, "idle", "model_loading")
    rt.backend.status_value = "error"

    models.on_state_change(rt, "model_loading", "idle")

    last = models.state(rt, {})["last_load"]
    assert last["alias"] == "vosk-ru" and last["outcome"] == "error" and last["at"] > 0


# ---- junk values (QA-RUNTIME-18, QA-JOURNEYS-16) ---------------------------------


@pytest.mark.parametrize("values", [
    {"language": "xx"}, {"language": 5}, {"language": ["ru"]},
    {"beam_size": "abc"}, {"beam_size": None}, {"beam_size": float("inf")},
    {"temperature": "hot"}, {"vad_filter": "yes"}, {"initial_prompt": 5},
    {"initial_prompt": "a\x00b"},
])
def test_inference_settings_that_would_be_silently_replaced_are_refused(disk, values):
    rt = _rt()
    before = list(rt.config.writes)

    with pytest.raises(rpc.RpcError) as err:
        models.inference_set(rt, {"alias": "whisper-large-v3-turbo", "values": values})

    assert err.value.code == "bad_params" and err.value.field in values
    assert rt.config.writes == before


def test_numbers_out_of_range_and_the_auto_language_are_still_accepted(disk):
    rt = _rt()

    out = models.inference_set(rt, {"alias": "whisper-large-v3-turbo",
                                    "values": {"beam_size": 99, "temperature": -5,
                                               "language": "auto"}})

    assert out["values"]["beam_size"] == 20 and out["values"]["temperature"] == 0.0
    assert out["values"]["language"] is None
    assert models.inference_set(rt, {"alias": "whisper-large-v3-turbo",
                                     "values": {"language": "ru"}})["values"]["language"] == "ru"


@pytest.mark.parametrize("token", ["\x00", "abc\ndef", "with space", "ключ", "x" * 600])
def test_a_token_that_cannot_be_one_is_refused_before_it_is_saved(token):
    rt = _rt()

    with pytest.raises(rpc.RpcError) as err:
        models.hf_token_set(rt, {"token": token})

    assert err.value.code == "bad_params"
    assert rt.config.data["huggingface"]["token"] == ""


# ---- a model that is on disk and marked active but not loaded (QA-JOURNEYS-7) -----


def test_selecting_the_active_model_loads_it_when_the_backend_has_nothing_loaded(disk):
    disk.add("vosk-ru")
    rt = _rt(whisper={"model": "vosk-ru", "compute_type": "int8"})
    rt.backend.status_value = "stopped"  # the start skipped the load; the weights came back later

    state = models.state(rt, {})
    assert state["active"] == "vosk-ru" and state["ready"] is False

    result = models.select(rt, {"alias": "vosk-ru"})

    assert result["noop"] is False
    assert [alias for alias, _compute in rt.state_manager.requests] == ["vosk-ru"]


def test_selecting_the_active_model_is_still_a_noop_when_it_is_loaded(disk):
    disk.add("vosk-ru")
    rt = _rt(whisper={"model": "vosk-ru", "compute_type": "int8"})

    assert models.state(rt, {})["ready"] is True
    assert models.select(rt, {"alias": "vosk-ru"})["noop"] is True
    assert rt.state_manager.requests == []


def test_downloading_a_model_that_is_being_deleted_is_busy_not_already_cached(disk):
    """QA-RUNTIME-F8: the files are still on disk while the delete runs."""
    rt = _rt()
    disk.add("vosk-ru")
    models._ctx(rt).deleting.add("vosk-ru")

    with pytest.raises(rpc.RpcError) as err:
        models.download(rt, {"alias": "vosk-ru"})

    assert err.value.code == "busy"


# ---- the diarization model ----------------------------------------------------


@pytest.fixture
def diar(monkeypatch):
    """Whether the diarization weights are on disk, and what a fetch does."""
    from app import diarization_models

    state = SimpleNamespace(cached=False, fetches=0, fail=None, gate=None, deleted=0)

    def download(progress=None):
        state.fetches += 1
        if state.gate is not None:
            state.gate.wait(5)
        if progress:
            progress(5, 10)
        if state.fail:
            raise RuntimeError(state.fail)
        state.cached = True

    def delete():
        state.deleted += 1
        state.cached = False
        return True

    monkeypatch.setattr(diarization_models, "is_cached", lambda: state.cached)
    monkeypatch.setattr(diarization_models, "download", download)
    monkeypatch.setattr(diarization_models, "delete", delete)
    monkeypatch.setattr(diarization_models, "cached_size", lambda: 123)
    return state


def _wait_downloaded(rt, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if not models._ctx(rt).diarization_downloading:
            return
        time.sleep(0.01)
    raise AssertionError("the download did not finish")


def test_the_diarization_card_is_listed_last_and_is_not_a_speech_model(disk):
    result = models.list_models(_rt(), {})

    card = result["models"][-1]
    assert card["alias"] == "diarization" and card["kind"] == "diarization"
    assert card["wer"] is None and card["rtf"] is None
    assert card["size_mb"] > 0 and card["url"].startswith("https://huggingface.co/")
    assert result["diarization_downloading"] is False
    assert all("kind" not in c for c in result["models"][:-1])


def test_the_diarization_model_never_becomes_the_active_one(monkeypatch, diar):
    diar.cached = True
    rt = _rt()

    snapshot = models._state(rt)

    assert snapshot["cached"]["diarization"] is True
    assert snapshot["active"] is None
    # Alone on disk, it does not make the app think it has a speech model.
    assert models._any_speech_model(snapshot["cached"]) is False
    with pytest.raises(rpc.RpcError) as err:
        models.select(rt, {"alias": "diarization"})
    assert err.value.code == "unknown_model"


def test_downloading_it_runs_on_a_thread_and_reports_progress_and_the_end(monkeypatch, diar):
    rt = _rt()
    drain = _events()

    result = models.download(rt, {"alias": "diarization"})
    _wait_downloaded(rt)

    assert result["downloading"] is True and diar.fetches == 1
    seen = dict((name, data) for name, data in
                ((n, __import__("json").loads(d)) for n, d in drain()))
    assert seen["diarization_progress"]["current"] == 5
    assert seen["diarization_download"] == {"outcome": "ready", "reason": ""}
    assert seen["models"]["cached"]["diarization"] is True
    # It did not touch the speech model's configuration or the state manager.
    assert rt.state_manager.requests == [] and rt.config.writes == []


def test_a_failed_download_says_so_and_frees_the_slot(monkeypatch, diar):
    diar.fail = "no route to host"
    rt = _rt()
    drain = _events()

    models.download(rt, {"alias": "diarization"})
    _wait_downloaded(rt)

    seen = {n: __import__("json").loads(d) for n, d in drain()}
    assert seen["diarization_download"]["outcome"] == "error"
    assert "no route" in seen["diarization_download"]["reason"]
    assert models._ctx(rt).diarization_downloading is False


def test_downloads_do_not_overlap(monkeypatch, diar):
    diar.gate = threading.Event()
    rt = _rt()
    models.download(rt, {"alias": "diarization"})
    try:
        with pytest.raises(rpc.RpcError) as again:
            models.download(rt, {"alias": "diarization"})
        assert again.value.code == "busy"
        # A speech-model switch waits for it too.
        with pytest.raises(rpc.RpcError) as sw:
            models.select(rt, {"alias": "vosk-ru"})
        assert sw.value.code == "busy"
    finally:
        diar.gate.set()
        _wait_downloaded(rt)


def test_it_is_refused_while_a_speech_model_loads(monkeypatch, diar):
    rt = _rt()
    rt.current_state = "model_loading"

    with pytest.raises(rpc.RpcError) as err:
        models.download(rt, {"alias": "diarization"})

    assert err.value.code == "busy" and diar.fetches == 0


def test_downloading_a_model_that_is_there_is_refused(monkeypatch, diar):
    diar.cached = True

    with pytest.raises(rpc.RpcError) as err:
        models.download(_rt(), {"alias": "diarization"})

    assert err.value.code == "already_cached"


def test_deleting_it_reports_and_removes_it(monkeypatch, diar):
    diar.cached = True
    rt = _rt()
    drain = _events()

    info = models.delete_info(rt, {"alias": "diarization"})
    assert info["cached"] is True and info["size_bytes"] == 123 and info["in_use"] is False
    assert models.delete(rt, {"alias": "diarization"}) == {"started": True}
    end = time.time() + 3
    while diar.cached and time.time() < end:
        time.sleep(0.01)

    seen = {n: __import__("json").loads(d) for n, d in drain(0.5)}
    assert seen["model_delete"]["deleted"] is True and seen["model_delete"]["alias"] == "diarization"
    assert diar.deleted == 1


def test_deleting_it_when_it_is_not_there_is_refused(monkeypatch, diar):

    with pytest.raises(rpc.RpcError) as err:
        models.delete(_rt(), {"alias": "diarization"})

    assert err.value.code == "not_cached"
