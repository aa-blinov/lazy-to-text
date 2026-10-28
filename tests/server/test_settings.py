"""Settings, devices and permissions handlers against stand-ins.

No microphone is opened, no listener is started and nothing reads the real
config: the runtime is a namespace of fakes.
"""

from __future__ import annotations

import copy
import sys
import threading
from types import SimpleNamespace

import pytest

from app import hotkey_rules, mic_test, ui_prefs
from app.config_manager import DEFAULT_CONFIG
from app.server import rpc
from app.server.events import bus
from app.server.handlers import devices, permissions, settings


class _Config:
    def __init__(self):
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        self.writes = []

    def get_section(self, name):
        value = self.data.get(name)
        return dict(value) if isinstance(value, dict) else {}

    def get_setting(self, section, key):
        return self.data.get(section, {}).get(key)

    def update_user_setting(self, section, key, value):
        self.data.setdefault(section, {})[key] = value
        self.writes.append((section, key, value))


class _Listener:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail
        self.stops = 0
        self.starts = 0

    def change_hotkey_configs(self, updates):
        if self.fail:
            raise RuntimeError("no tap")
        self.calls.append(dict(updates))

    def stop_listening(self):
        self.stops += 1

    def start_listening(self):
        self.starts += 1


class _Recorder:
    max_duration = 300
    device = None

    def __init__(self, peak=0.5, rms=0.1, error=None):
        self.peak, self.rms, self.error = peak, rms, error
        self.gate = threading.Event()
        self.gate.set()

    def list_input_devices(self):
        return [(1, "Built-in"), (4, "USB mic")]

    def set_device(self, raw):
        self.device = raw
        return raw

    def test_input_level(self, seconds):
        self.gate.wait(2)
        if self.error:
            raise RuntimeError(self.error)
        return {"peak": self.peak, "rms": self.rms}

    def current_input_level(self):
        return 0.3


def _rt(**over):
    clipboard = SimpleNamespace(updated=[])
    clipboard.update_auto_paste = clipboard.updated.append
    sm = SimpleNamespace(
        clipboard_manager=clipboard,
        audio_recorder=_Recorder(),
        audio_feedback=SimpleNamespace(_component=SimpleNamespace(enabled=True)),
    )
    base = dict(
        config=_Config(), state_manager=sm, hotkey_listener=_Listener(),
        state=lambda: "idle", stack_error=None, backend=SimpleNamespace(),
    )
    base.update(over)
    return SimpleNamespace(**base)


def _hk(rt, **params):
    return settings.set_hotkeys(rt, params)


# ---- the shared hotkey rules ------------------------------------------------


def test_the_shared_rules_name_the_problem_with_a_template_and_values():
    issue = hotkey_rules.check_hotkey("foo+f2")
    assert issue.template.startswith("%1 is not a recognised modifier")
    assert issue.args == ("'foo'",)
    assert "'foo' is not a recognised modifier" in issue.english()


def test_a_solo_modifier_is_only_accepted_in_push_to_talk():
    assert hotkey_rules.check_hotkey("right_alt") is not None
    assert hotkey_rules.check_hotkey("right_alt", push_to_talk=True, platform="linux") is None
    assert hotkey_rules.check_hotkey("fn", push_to_talk=True, platform="win32") is not None


def test_mic_verdicts_follow_the_thresholds():
    assert mic_test.classify_input_level(0.0) == mic_test.SILENT
    assert mic_test.classify_input_level(mic_test.SILENT_BELOW) == mic_test.QUIET
    assert mic_test.classify_input_level(mic_test.QUIET_BELOW) == mic_test.GOOD


def test_ui_preferences_fall_back_instead_of_raising():
    assert ui_prefs.normalise_theme("purple") == "system"
    assert ui_prefs.normalise_palette("nope") == "gruvbox"
    assert ui_prefs.normalise_language("de") == "en"
    assert ui_prefs.clamp_text_scale("junk") == 1.0
    assert ui_prefs.clamp_text_scale(9) == ui_prefs.TEXT_SCALE_MAX
    assert ui_prefs.clamp_text_scale(0.1) == ui_prefs.TEXT_SCALE_MIN
    assert ui_prefs.clamp_text_scale(float("nan")) == 1.0


def test_a_new_palette_key_is_in_the_defaults():
    assert DEFAULT_CONFIG["ui"]["palette"] == "gruvbox"


# ---- settings.get ------------------------------------------------------------


def test_get_reports_every_value_the_screen_shows():
    out = settings.get(_rt(), {})

    assert out["hotkey"]["mode"] == "two_keys"
    assert out["ui"] == {"theme": "system", "palette": "gruvbox", "language": "en",
                         "text_scale": 1.0, "start_at_login": False}
    assert out["audio"]["vad_enabled"] is False
    assert out["clipboard"]["auto_paste"] is False
    assert out["choices"]["palettes"] == list(ui_prefs.PALETTES)
    assert out["hotkey_errors"] == {}


def test_a_legacy_config_with_start_equal_to_stop_reads_as_toggle():
    rt = _rt()
    rt.config.data["hotkey"]["stop_recording_hotkey"] = rt.config.data["hotkey"]["start_recording_hotkey"]

    assert settings.get(rt, {})["hotkey"]["mode"] == "toggle"


def test_an_unusable_binding_on_disk_is_marked_at_load():
    rt = _rt()
    rt.config.data["hotkey"]["start_recording_hotkey"] = "ctrl+"

    errors = settings.get(rt, {})["hotkey_errors"]

    assert "start" in errors and "Empty part" in errors["start"]["message"]


def test_stored_junk_in_ui_settings_is_normalised_on_the_way_out():
    rt = _rt()
    rt.config.data["ui"].update(theme="neon", language="xx", text_scale="big", palette="?")

    assert settings.get(rt, {})["ui"] == {
        "theme": "system", "palette": "gruvbox", "language": "en", "text_scale": 1.0,
        "start_at_login": False,
    }


# ---- hotkeys -----------------------------------------------------------------


def test_a_valid_binding_is_saved_and_reaches_the_listener():
    rt = _rt()

    out = _hk(rt, mode="two_keys", start="ctrl+f8", stop="ctrl+f9", cancel="ctrl+f10")

    assert out["errors"] == {} and out["live"] is True
    assert rt.config.data["hotkey"]["start_recording_hotkey"] == "ctrl+f8"
    pushed = rt.hotkey_listener.calls[-1]
    assert pushed["start_recording_hotkey"] == "ctrl+f8"
    assert pushed["mode"] == "two_keys"


def test_a_refused_binding_is_never_written_and_the_old_one_stays():
    rt = _rt()
    before = rt.config.data["hotkey"]["start_recording_hotkey"]

    out = _hk(rt, mode="two_keys", start="ctrl+", stop="ctrl+f9", cancel="")

    assert "Empty part" in out["errors"]["start"]["message"]
    assert rt.config.data["hotkey"]["start_recording_hotkey"] == before
    assert all(value != "ctrl+" for _s, _k, value in rt.config.writes)


def test_other_fields_still_save_when_one_is_refused():
    rt = _rt()

    _hk(rt, mode="two_keys", start="ctrl+", stop="ctrl+shift+9", cancel="")

    assert rt.config.data["hotkey"]["stop_recording_hotkey"] == "ctrl+shift+9"


def test_a_refused_field_falls_back_to_the_default_when_the_stored_one_is_unusable():
    rt = _rt()
    rt.config.data["hotkey"]["start_recording_hotkey"] = "junk+"
    defaults = settings._defaults()

    _hk(rt, mode="two_keys", start="also bad", stop=defaults["stop"], cancel="")

    assert rt.config.data["hotkey"]["start_recording_hotkey"] == defaults["start"]


def test_stop_equal_to_start_points_at_the_one_key_mode():
    out = _hk(_rt(), mode="two_keys", start="ctrl+f8", stop="ctrl+f8", cancel="")

    assert "One key: press to start and stop" in out["errors"]["stop"]["message"]


def test_cancel_may_not_equal_start_in_any_mode():
    out = _hk(_rt(), mode="two_keys", start="ctrl+f8", stop="ctrl+f9", cancel="ctrl+f8")

    assert "Cancel matches Start" in out["errors"]["cancel"]["message"]


def test_toggle_mode_mirrors_start_into_stop_and_empties_cancel():
    rt = _rt()

    out = _hk(rt, mode="toggle", start="ctrl+f7", stop="whatever", cancel="ctrl+f10")

    hotkey = rt.config.data["hotkey"]
    assert out["errors"] == {}
    assert hotkey["stop_recording_hotkey"] == "ctrl+f7"
    assert hotkey["cancel_recording_hotkey"] == ""
    assert rt.hotkey_listener.calls[-1]["cancel_combination"] is None


def test_push_to_talk_accepts_a_solo_modifier_and_leaves_start_and_stop_alone():
    rt = _rt()
    start = rt.config.data["hotkey"]["start_recording_hotkey"]
    key = "fn" if sys.platform != "win32" else "right_alt"

    out = _hk(rt, mode="push_to_talk", push_to_talk_key=key)

    hotkey = rt.config.data["hotkey"]
    assert out["errors"] == {}
    assert hotkey["push_to_talk_key"] == key
    assert hotkey["start_recording_hotkey"] == start
    assert hotkey["mode"] == "push_to_talk"


def test_a_solo_modifier_is_refused_outside_push_to_talk():
    out = _hk(_rt(), mode="two_keys", start="right_alt", stop="ctrl+f9", cancel="")

    assert "start" in out["errors"]


def test_a_bad_push_to_talk_key_is_reported_on_its_own_field():
    out = _hk(_rt(), mode="push_to_talk", push_to_talk_key="a")

    assert list(out["errors"]) == ["ptt"]


def test_validate_hotkeys_checks_without_saving():
    rt = _rt()

    out = settings.validate_hotkeys(rt, {"mode": "two_keys", "start": "ctrl+", "stop": "ctrl+f3", "cancel": ""})

    assert "start" in out["errors"]
    assert rt.config.writes == []


def test_a_listener_that_fails_does_not_lose_the_saved_config():
    rt = _rt(hotkey_listener=_Listener(fail=True))

    out = _hk(rt, mode="two_keys", start="ctrl+f8", stop="ctrl+f9", cancel="")

    assert out["live"] is False and "no tap" in out["live_error"]
    assert rt.config.data["hotkey"]["start_recording_hotkey"] == "ctrl+f8"


def test_without_a_listener_the_save_still_happens():
    rt = _rt(hotkey_listener=None, stack_error="no audio")

    out = _hk(rt, mode="two_keys", start="ctrl+f8", stop="ctrl+f9", cancel="")

    assert out["live"] is False and out["live_error"] == "no audio"
    assert rt.config.data["hotkey"]["start_recording_hotkey"] == "ctrl+f8"


def test_a_bad_mode_is_a_bad_request():
    with pytest.raises(rpc.RpcError) as err:
        _hk(_rt(), mode="chord")
    assert err.value.code == "bad_params"


def test_reset_restores_the_defaults_and_reaches_the_listener():
    rt = _rt()
    _hk(rt, mode="two_keys", start="ctrl+f8", stop="ctrl+f9", cancel="")
    rt.hotkey_listener.calls.clear()

    out = settings.reset_hotkeys(rt, {})

    defaults = settings._defaults()
    assert rt.config.data["hotkey"]["start_recording_hotkey"] == defaults["start"]
    assert out["live"] is True
    assert rt.hotkey_listener.calls[-1]["start_recording_hotkey"] == defaults["start"]


def test_reset_leaves_vad_auto_paste_and_the_minimum_hold_alone():
    rt = _rt()
    rt.config.data["audio"]["vad_enabled"] = True
    rt.config.data["clipboard"]["auto_paste"] = False
    rt.config.data["hotkey"]["push_to_talk_min_hold_seconds"] = 0.5

    out = settings.reset_hotkeys(rt, {})

    assert out["settings"]["audio"]["vad_enabled"] is True
    assert out["settings"]["clipboard"]["auto_paste"] is False
    assert out["settings"]["hotkey"]["push_to_talk_min_hold_seconds"] == 0.5


# ---- single values -----------------------------------------------------------


def _set(rt, key, value):
    return settings.set_value(rt, {"key": key, "value": value})


def test_auto_paste_is_applied_to_the_live_clipboard_manager():
    rt = _rt()

    _set(rt, "clipboard.auto_paste", False)

    assert rt.config.data["clipboard"]["auto_paste"] is False
    assert rt.state_manager.clipboard_manager.updated == [False]


def test_the_vad_switch_is_pushed_to_the_backend(monkeypatch):
    from app.server.handlers import models

    seen = []
    monkeypatch.setattr(models, "push_vad", lambda rt, value: seen.append(value))
    rt = _rt()

    _set(rt, "audio.vad_enabled", True)

    assert rt.config.data["audio"]["vad_enabled"] is True and seen == [True]


def test_muting_the_output_is_refused_where_the_platform_cannot(monkeypatch):
    monkeypatch.setattr("app.system_audio.system_output_mute_supported", lambda: False)

    with pytest.raises(rpc.RpcError) as err:
        _set(_rt(), "audio.mute_output_on_record", True)

    assert err.value.code == "unsupported"


def test_muting_the_output_is_stored_where_the_platform_can(monkeypatch):
    monkeypatch.setattr("app.system_audio.system_output_mute_supported", lambda: True)
    rt = _rt()

    _set(rt, "audio.mute_output_on_record", True)

    assert rt.config.data["audio"]["mute_output_on_record"] is True


def test_max_duration_reaches_the_recorder_and_is_bounded():
    rt = _rt()
    _set(rt, "audio.max_duration", 120)
    assert rt.state_manager.audio_recorder.max_duration == 120
    with pytest.raises(rpc.RpcError):
        _set(rt, "audio.max_duration", 99999)


def test_audio_feedback_switches_the_sound_player():
    rt = _rt()
    _set(rt, "audio_feedback.enabled", False)
    assert rt.state_manager.audio_feedback._component.enabled is False


def test_the_minimum_hold_goes_to_the_listener():
    rt = _rt()
    _set(rt, "hotkey.push_to_talk_min_hold_seconds", 0.4)
    assert rt.hotkey_listener.calls[-1] == {"push_to_talk_min_hold_seconds": 0.4}


@pytest.mark.parametrize("key,value", [
    ("ui.theme", "neon"), ("ui.palette", "nope"), ("ui.language", "de"),
    ("clipboard.auto_paste", "yes"), ("audio.vad_enabled", 1), ("nope.nope", True),
])
def test_a_value_outside_the_allowed_set_is_refused(key, value):
    rt = _rt()
    with pytest.raises(rpc.RpcError) as err:
        _set(rt, key, value)
    assert err.value.code == "bad_params"
    assert rt.config.writes == []


def test_theme_palette_language_and_scale_are_stored():
    rt = _rt()
    _set(rt, "ui.theme", "dark")
    _set(rt, "ui.palette", "nord")
    _set(rt, "ui.language", "ru")
    out = _set(rt, "ui.text_scale", 3.0)

    assert rt.config.data["ui"]["theme"] == "dark"
    assert rt.config.data["ui"]["palette"] == "nord"
    assert rt.config.data["ui"]["language"] == "ru"
    assert out["value"] == ui_prefs.TEXT_SCALE_MAX


def test_a_live_failure_keeps_the_saved_value_and_reports_it(monkeypatch):
    rt = _rt()

    def boom(_v):
        raise RuntimeError("clipboard gone")

    rt.state_manager.clipboard_manager.update_auto_paste = boom
    out = _set(rt, "clipboard.auto_paste", False)

    assert rt.config.data["clipboard"]["auto_paste"] is False
    assert "clipboard gone" in out["live_error"]


# ---- devices -----------------------------------------------------------------


def test_devices_are_listed_with_the_current_one():
    rt = _rt()
    rt.state_manager.audio_recorder.device = 4

    out = devices.list_devices(rt, {})

    assert out["devices"] == [{"index": 1, "name": "Built-in"}, {"index": 4, "name": "USB mic"}]
    assert out["current"] == 4


def test_a_device_list_that_cannot_be_read_is_empty_not_an_error():
    rt = _rt()

    def boom():
        raise OSError("no portaudio")

    rt.state_manager.audio_recorder.list_input_devices = boom

    assert devices.list_devices(rt, {})["devices"] == []


def test_selecting_a_device_persists_and_switches_the_recorder():
    rt = _rt()

    devices.select(rt, {"device": 4})

    assert rt.config.data["audio"]["device"] == 4
    assert rt.state_manager.audio_recorder.device == 4
    devices.select(rt, {"device": None})
    assert rt.config.data["audio"]["device"] is None


def test_a_refresh_rebuilds_the_audio_device_list_only_when_asked():
    rt = _rt()
    calls = []
    rt.state_manager.audio_recorder.refresh_devices = lambda: calls.append(1) or True

    plain = devices.list_devices(rt, {})
    asked = devices.list_devices(rt, {"refresh": True})

    assert calls == [1]
    assert plain["refreshed"] is False
    assert asked["refreshed"] is True


def test_a_refresh_that_is_refused_during_a_recording_still_lists_the_devices():
    rt = _rt()
    rt.state_manager.audio_recorder.refresh_devices = lambda: False

    out = devices.list_devices(rt, {"refresh": True})

    assert out["refreshed"] is False
    assert out["devices"], "the list is still returned"


def test_the_name_of_the_chosen_microphone_is_saved_with_its_index():
    rt = _rt()
    rt.state_manager.audio_recorder.set_device = lambda raw: setattr(
        rt.state_manager.audio_recorder, "device_name", "USB mic") or raw

    devices.select(rt, {"device": 4})

    assert rt.config.data["audio"]["device_name"] == "USB mic"
    devices.select(rt, {"device": None})


def test_a_device_must_be_an_index_or_null():
    with pytest.raises(rpc.RpcError):
        devices.select(_rt(), {"device": "USB"})


def _events():
    sub = bus.subscribe()
    seen = []
    # A sticky event from an earlier test is replayed on subscribe.
    while sub.get(0.01) is not None:
        pass

    def drain(timeout=0.01):
        while True:
            item = sub.get(timeout)
            if item is None:
                return seen
            seen.append(item)

    return sub, drain


def _wait_for(drain, phase, tries=100):
    for _ in range(tries):
        for name, payload in drain(0.05):
            if name == "mic_test" and f'"{phase}"' in payload:
                return payload
    raise AssertionError(f"no mic_test {phase} event")


def test_a_microphone_test_reports_a_verdict_by_event():
    rt = _rt()
    sub, drain = _events()
    try:
        assert devices.test(rt, {})["started"] is True
        payload = _wait_for(drain, "done")
    finally:
        sub.close()
    assert '"verdict": "good"' in payload


def test_a_silent_microphone_is_classified_silent():
    rt = _rt()
    rt.state_manager.audio_recorder.peak = 0.0
    sub, drain = _events()
    try:
        devices.test(rt, {})
        payload = _wait_for(drain, "done")
    finally:
        sub.close()
    assert '"verdict": "silent"' in payload


def test_a_failing_test_says_why():
    rt = _rt()
    rt.state_manager.audio_recorder.error = "device busy"
    sub, drain = _events()
    try:
        devices.test(rt, {})
        payload = _wait_for(drain, "error")
    finally:
        sub.close()
    assert "device busy" in payload


def test_a_test_is_refused_while_a_dictation_runs():
    with pytest.raises(rpc.RpcError) as err:
        devices.test(_rt(state=lambda: "recording"), {})
    assert err.value.code == "busy"


def test_a_second_test_is_refused_while_one_runs():
    rt = _rt()
    rt.state_manager.audio_recorder.gate.clear()
    sub, drain = _events()
    try:
        devices.test(rt, {})
        with pytest.raises(rpc.RpcError) as err:
            devices.test(rt, {})
        assert err.value.code == "busy"
    finally:
        rt.state_manager.audio_recorder.gate.set()
        _wait_for(drain, "done")
        sub.close()


def test_a_test_without_a_stack_says_why():
    with pytest.raises(rpc.RpcError) as err:
        devices.test(_rt(state_manager=None, stack_error="no audio"), {})
    assert err.value.code == "no_stack"


# ---- permissions -------------------------------------------------------------


def _mac(monkeypatch, listen=True, post=True, mic="authorized"):
    state = {"listen": listen, "post": post, "mic": mic}
    monkeypatch.setattr(permissions.macos_permissions, "is_listen_event_access_trusted", lambda: state["listen"])
    monkeypatch.setattr(permissions.macos_permissions, "is_post_event_access_trusted", lambda: state["post"])
    monkeypatch.setattr(permissions, "_mic_status", lambda: state["mic"])
    return state


def test_off_macos_no_banner_is_ever_shown(monkeypatch):
    _mac(monkeypatch, listen=None, post=None, mic=None)

    out = permissions.status(_rt())

    assert set(out["banners"].values()) == {"hidden"}


def test_each_missing_grant_gets_its_own_banner(monkeypatch):
    _mac(monkeypatch, listen=False, post=False, mic="not_determined")
    rt = _rt()
    rt.config.data["clipboard"]["auto_paste"] = True

    banners = permissions.status(rt)["banners"]

    assert banners == {
        "accessibility": "untrusted", "microphone": "not_determined", "post_event": "untrusted",
    }


def test_a_blocked_microphone_offers_the_settings_pane(monkeypatch):
    _mac(monkeypatch, mic="restricted")
    assert permissions.status(_rt())["banners"]["microphone"] == "denied"


def test_the_post_event_banner_needs_auto_paste_on(monkeypatch):
    _mac(monkeypatch, post=False)
    rt = _rt()
    rt.config.data["clipboard"]["auto_paste"] = False

    assert permissions.status(rt)["banners"]["post_event"] == "hidden"


def test_the_generic_hotkey_banner_is_suppressed_for_solo_push_to_talk(monkeypatch):
    _mac(monkeypatch, listen=False)
    rt = _rt()
    rt.config.data["hotkey"].update(mode="push_to_talk", push_to_talk_key="right_cmd")

    assert permissions.status(rt)["banners"]["accessibility"] == "hidden"


def test_a_grant_since_the_last_look_restarts_the_listener_and_publishes(monkeypatch):
    state = _mac(monkeypatch, listen=False)
    rt = _rt()
    sub = bus.subscribe()
    try:
        permissions.refresh(rt)
        state["listen"] = True
        permissions.refresh(rt)
        names = []
        while True:
            item = sub.get(0.05)
            if item is None:
                break
            names.append(item[0])
    finally:
        sub.close()

    assert (rt.hotkey_listener.stops, rt.hotkey_listener.starts) == (1, 1)
    assert "permissions" in names


def test_an_unchanged_state_publishes_nothing_and_restarts_nothing(monkeypatch):
    _mac(monkeypatch)
    rt = _rt()
    permissions.refresh(rt)
    sub = bus.subscribe()
    try:
        while sub.get(0.01) is not None:
            pass
        permissions.refresh(rt)
        assert sub.get(0.05) is None
    finally:
        sub.close()
    assert rt.hotkey_listener.stops == 0


def test_a_request_off_macos_does_nothing(monkeypatch):
    monkeypatch.setattr(permissions.sys, "platform", "linux")
    assert permissions.request(_rt(), {"kind": "microphone"}) == {"action": "none"}


def test_an_unknown_kind_is_a_bad_request():
    with pytest.raises(rpc.RpcError):
        permissions.request(_rt(), {"kind": "camera"})


def test_the_accessibility_button_opens_the_pane_when_the_os_will_not_ask(monkeypatch):
    _mac(monkeypatch, listen=False)
    monkeypatch.setattr(permissions.sys, "platform", "darwin")
    opened = []
    monkeypatch.setattr(permissions.macos_permissions, "request_listen_event_access", lambda: False)
    monkeypatch.setattr(permissions.macos_permissions, "open_accessibility_settings", lambda: opened.append(1) or True)
    monkeypatch.setattr(permissions, "_recheck_later", lambda rt: None)

    out = permissions.request(_rt(), {"kind": "accessibility"})

    assert out == {"action": "opened_settings"} and opened == [1]


def test_the_settings_handlers_import_without_qt():
    import subprocess

    code = (
        "import sys\n"
        "from app.server.handlers import settings, devices, permissions\n"
        "assert 'PySide6' not in sys.modules, 'Qt was imported'\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


# ---- two bindings on one key are refused whole (QA-JOURNEYS-3, QA-RUNTIME-10) ----


def _two_keys(rt, start="ctrl+f8", stop="ctrl+f9", cancel="ctrl+f10"):
    out = _hk(rt, mode="two_keys", start=start, stop=stop, cancel=cancel)
    assert out["errors"] == {} and out["saved"] is True
    rt.config.writes.clear()
    rt.hotkey_listener.calls.clear()


def _nothing_happened(rt, out):
    assert out["saved"] is False and out["live"] is False and out["live_error"] is None
    assert rt.config.writes == []
    assert rt.hotkey_listener.calls == []


def test_capturing_the_stop_key_into_start_is_refused_and_nothing_changes():
    """The capture field sends only the edited field; the refusal used to land
    on the other one while the new Start was written."""
    rt = _rt()
    _two_keys(rt)

    out = _hk(rt, mode="two_keys", start="ctrl+f9")

    _nothing_happened(rt, out)
    message = out["errors"]["stop"]["message"]
    assert "Stop is the same as Start" in message
    # QA-JOURNEYS-R8: name the mode as the screen does, not as a code did.
    assert "One key: press to start and stop" in message and "Toggle" not in message
    hotkey = rt.config.data["hotkey"]
    assert (hotkey["start_recording_hotkey"], hotkey["stop_recording_hotkey"]) == ("ctrl+f8", "ctrl+f9")
    assert out["settings"]["hotkey"]["mode"] == "two_keys"


def test_capturing_the_cancel_key_into_start_is_refused_and_nothing_changes():
    rt = _rt()
    _two_keys(rt)

    out = _hk(rt, mode="two_keys", start="ctrl+f10")

    _nothing_happened(rt, out)
    assert "Cancel matches Start" in out["errors"]["cancel"]["message"]


@pytest.mark.parametrize("start, stop, cancel", [
    ("ctrl+shift+a", "shift+ctrl+a", ""),
    ("cmd+f8", "command+f8", ""),
    ("alt+a", "option+a", ""),
    ("ctrl+f8", "ctrl+f9", "control+f8"),
    ("ctrl+f8", "ctrl+f9", "CTRL+F9"),
    ("ctrl+return", "ctrl+enter", ""),
])
def test_other_spellings_of_the_same_key_are_the_same_conflict(start, stop, cancel):
    rt = _rt()

    out = _hk(rt, mode="two_keys", start=start, stop=stop, cancel=cancel)

    assert out["saved"] is False and out["errors"]
    assert rt.config.writes == []
    assert settings.validate_hotkeys(rt, {"mode": "two_keys", "start": start,
                                          "stop": stop, "cancel": cancel})["errors"]


def test_a_swap_in_one_request_is_not_a_conflict():
    rt = _rt()
    _two_keys(rt)

    out = _hk(rt, mode="two_keys", start="ctrl+f9", stop="ctrl+f8", cancel="ctrl+f10")

    assert out["saved"] is True and out["errors"] == {}
    assert rt.config.data["hotkey"]["start_recording_hotkey"] == "ctrl+f9"


def test_leaving_toggle_with_an_empty_stop_does_not_store_stop_equal_to_start():
    rt = _rt()
    _hk(rt, mode="toggle", start="ctrl+f8")
    rt.config.writes.clear()

    out = _hk(rt, mode="two_keys", start="ctrl+f8", stop="", cancel="ctrl+f10")

    assert out["saved"] is False and "stop" in out["errors"]
    assert rt.config.writes == []
    assert out["settings"]["hotkey"]["mode"] == "toggle"
    assert out["settings"]["hotkey"]["cancel"] == ""


def test_a_fallback_cannot_create_the_conflict_either():
    rt = _rt()
    _two_keys(rt)

    out = _hk(rt, mode="two_keys", start="ctrl+f9", stop="not a key", cancel="ctrl+f10")

    assert out["saved"] is False
    assert {"stop"} <= set(out["errors"])
    assert rt.config.writes == []


def test_the_push_to_talk_key_may_not_repeat_a_binding_sent_with_it():
    rt = _rt()

    out = _hk(rt, mode="push_to_talk", push_to_talk_key="right_ctrl", start="ctrl_r")
    assert out["saved"] is False and "ptt" in out["errors"]
    assert _hk(rt, mode="push_to_talk", push_to_talk_key="right_ctrl")["saved"] is True
    out = _hk(rt, mode="two_keys", start="ctrl+f8", stop="ctrl+f9", cancel="",
              push_to_talk_key="ctrl+f8")
    assert out["saved"] is False and "ptt" in out["errors"]


def test_a_refusal_with_a_conflict_reaches_neither_disk_nor_listener_when_nothing_else_is_wrong():
    rt = _rt()
    before = dict(rt.config.data["hotkey"])

    out = _hk(rt, mode="two_keys", start="ctrl+f8", stop="ctrl+f8", cancel="")

    assert out["saved"] is False
    assert rt.config.data["hotkey"] == before
    assert rt.hotkey_listener.calls == []


def test_equivalent_spellings_are_one_key_to_the_shared_rules():
    canon = hotkey_rules.canonical
    assert canon("Shift+Ctrl+A") == canon("ctrl+shift+a")
    assert canon("command+f8") == canon("cmd+F8") == canon("win+f8")
    assert canon("option+a") == canon("alt+a")
    assert canon("ctrl+return") == canon("ctrl+enter")
    assert canon("ctrl_r") == canon("right_control") == canon("right_ctrl")
    assert canon("cmd_r") == canon("right_command")
    assert canon("ctrl+f8") != canon("ctrl+f9")
    assert canon("ctrl+") == "ctrl+"  # garbage stays itself, and is refused elsewhere


# ---- the screen is told when something changed elsewhere (QA-JOURNEYS-13) ---------


def _seen_settings_events(sub):
    out = []
    while True:
        item = sub.get(0.05)
        if item is None:
            return out
        if item[0] == "settings":
            out.append(item[1])


def test_changes_are_announced_so_an_open_screen_can_follow():
    rt = _rt()
    sub = bus.subscribe()
    try:
        while sub.get(0.01) is not None:
            pass
        settings.set_value(rt, {"key": "ui.language", "value": "ru"})
        _hk(rt, mode="two_keys", start="ctrl+f8", stop="ctrl+f9", cancel="")
        settings.reset_hotkeys(rt, {})
        devices.select(rt, {"device": 4})
        seen = _seen_settings_events(sub)
    finally:
        sub.close()

    assert '"ui.language"' in seen[0] and '"hotkey"' in seen[1]
    assert len(seen) == 4 and '"audio.device"' in seen[3]


# ---- junk (QA-RUNTIME-14/18, QA-RUNTIME-11) ---------------------------------------


@pytest.mark.parametrize("key, value", [
    ("audio.max_duration", float("inf")), ("audio.max_duration", 10**400),
    ("audio.max_duration", float("nan")), ("audio.max_duration", "300"),
    ("audio.max_duration", None), ("audio.max_duration", [1]),
    ("hotkey.push_to_talk_min_hold_seconds", float("inf")),
    ("hotkey.push_to_talk_min_hold_seconds", "abc"),
    ("ui.text_scale", float("inf")), ("ui.text_scale", 10**400), ("ui.text_scale", True),
    ("ui.theme", None), ("ui.theme", ["dark"]), ("ui.palette", 5), ("ui.language", {}),
    ("clipboard.auto_paste", 1),
    ("audio.vad_enabled", None), ("audio_feedback.enabled", 0),
    ("history.max_entries", 5), ("llm.api_key", "x"), ("nope", 1), ("", 1),
])
def test_junk_for_any_key_is_refused_and_never_stored_or_an_internal_error(key, value):
    rt = _rt()

    with pytest.raises(rpc.RpcError) as err:
        settings.set_value(rt, {"key": key, "value": value})

    assert err.value.code in ("bad_params", "unsupported")
    assert rt.config.writes == []


def test_a_stored_value_of_the_wrong_type_does_not_break_settings_get():
    rt = _rt()
    data = rt.config.data
    data["audio"].update(max_duration="abc", device="usb", mute_output_on_record="yes",
                         vad_enabled=3)
    data["hotkey"].update(push_to_talk_min_hold_seconds="abc", start_recording_hotkey=5,
                          stop_recording_hotkey=[1], cancel_recording_hotkey={"a": 1},
                          push_to_talk_key=7, mode=9)
    data["clipboard"].update(auto_paste="no")
    data["audio_feedback"]["enabled"] = "off"

    out = settings.get(rt, {})

    assert out["audio"]["max_duration"] == 300 and out["audio"]["device"] is None
    assert out["audio"]["mute_output_on_record"] is False
    assert out["hotkey"]["push_to_talk_min_hold_seconds"] == 0.2
    assert out["hotkey"]["start"] == "" and out["hotkey"]["mode"] in hotkey_rules.MODES
    assert out["clipboard"]["auto_paste"] is False
    assert out["audio_feedback"]["enabled"] is True
    # and a hotkey change still reaches the listener with usable values
    _hk(rt, mode="two_keys", start="ctrl+f8", stop="ctrl+f9", cancel="")
    assert rt.hotkey_listener.calls[-1]["start_recording_hotkey"] == "ctrl+f8"


def test_a_change_that_cannot_be_written_to_disk_says_so(tmp_path):
    import os

    folder = tmp_path / "ro"
    folder.mkdir()
    path = folder / "config.yaml"
    path.write_text("x: 1")
    os.chmod(path, 0o444)
    os.chmod(folder, 0o555)
    try:
        if os.access(folder, os.W_OK):
            pytest.skip("this account can write through permissions")
        rt = _rt()
        rt.config.config_path = path

        out = settings.set_value(rt, {"key": "ui.theme", "value": "dark"})
        hotkeys = _hk(rt, mode="two_keys", start="ctrl+f8", stop="ctrl+f9", cancel="")
    finally:
        os.chmod(folder, 0o755)
    assert "lost when the app closes" in out["save_error"]
    assert "lost when the app closes" in hotkeys["save_error"]


def test_a_writable_config_reports_no_save_error(tmp_path):
    rt = _rt()
    rt.config.config_path = tmp_path / "config.yaml"

    assert settings.set_value(rt, {"key": "ui.theme", "value": "dark"})["save_error"] is None


# ---- devices: only a listed microphone may be chosen (QA-JOURNEYS-2) ----------------


@pytest.mark.parametrize("device", [99, -1, 0, 2**40])
def test_an_unknown_device_is_refused_and_nothing_is_stored_or_switched(device):
    rt = _rt()
    recorder = rt.state_manager.audio_recorder
    recorder.device = 1

    with pytest.raises(rpc.RpcError) as err:
        devices.select(rt, {"device": device})

    assert err.value.code == "device_failed" and err.value.field == "device"
    assert rt.config.writes == [] and recorder.device == 1


def test_a_listed_device_and_the_system_default_are_accepted():
    rt = _rt()

    assert devices.select(rt, {"device": 1})["device"] == 1
    assert devices.select(rt, {"device": None})["device"] is None
    assert rt.config.data["audio"]["device"] is None


def test_a_device_cannot_be_validated_without_a_recorder_but_the_default_can_be_chosen():
    rt = _rt()
    rt.state_manager = None

    with pytest.raises(rpc.RpcError) as err:
        devices.select(rt, {"device": 4})
    assert err.value.code == "device_failed"
    assert devices.select(rt, {"device": None}) == {"device": None}


def test_a_device_the_recorder_refuses_is_not_saved():
    rt = _rt()

    def refuse(raw):
        raise RuntimeError("device busy")

    rt.state_manager.audio_recorder.set_device = refuse

    with pytest.raises(rpc.RpcError) as err:
        devices.select(rt, {"device": 4})

    assert err.value.code == "device_failed"
    assert rt.config.writes == []


# ---- start at login ------------------------------------------------------------


def test_start_at_login_is_off_until_the_user_turns_it_on():
    from app.config_manager import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["ui"]["start_at_login"] is False
    rt = _rt()
    assert settings.get(rt, {})["ui"]["start_at_login"] is False


def test_start_at_login_is_stored_and_announced_for_the_shell_to_apply():
    rt = _rt()
    sub, drain = _events()
    try:
        out = _set(rt, "ui.start_at_login", True)
        seen = drain()
    finally:
        sub.close()

    assert out["value"] is True and out["live_error"] is None
    assert rt.config.data["ui"]["start_at_login"] is True
    assert settings.get(rt, {})["ui"]["start_at_login"] is True
    assert ("settings", '{"keys": ["ui.start_at_login"]}') in seen


@pytest.mark.parametrize("value", ["yes", 1, None, "true"])
def test_start_at_login_takes_only_a_boolean(value):
    rt = _rt()
    with pytest.raises(rpc.RpcError) as err:
        _set(rt, "ui.start_at_login", value)
    assert err.value.code == "bad_params"
    assert rt.config.writes == []


def test_a_stored_junk_value_reads_as_off():
    rt = _rt()
    rt.config.data.setdefault("ui", {})["start_at_login"] = "maybe"
    assert settings.get(rt, {})["ui"]["start_at_login"] is False


def test_the_config_no_longer_carries_the_keys_nothing_reads():
    from app.config_manager import DEFAULT_CONFIG

    # Qt kept the window position and a tray switch here; the Electron shell
    # keeps its own window state, and nothing reads either key.
    assert "window" not in DEFAULT_CONFIG
    assert "system_tray" not in DEFAULT_CONFIG


def test_enabling_auto_paste_asks_for_accessibility_on_macos(monkeypatch):
    asked = []
    monkeypatch.setattr(settings.sys, "platform", "darwin")
    monkeypatch.setattr(settings.macos_permissions, "is_post_event_access_trusted", lambda: False)
    monkeypatch.setattr(settings.macos_permissions, "request_post_event_access",
                        lambda: asked.append("request") or True)
    monkeypatch.setattr(settings.macos_permissions, "open_accessibility_settings",
                        lambda: asked.append("open"))

    _set(_rt(), "clipboard.auto_paste", True)

    assert asked == ["request"]


def test_disabling_auto_paste_does_not_ask(monkeypatch):
    monkeypatch.setattr(settings.sys, "platform", "darwin")
    monkeypatch.setattr(settings.macos_permissions, "is_post_event_access_trusted",
                        lambda: pytest.fail("must not probe"))

    _set(_rt(), "clipboard.auto_paste", False)
