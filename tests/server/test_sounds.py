"""The start and stop sounds: the list, the choice, files of one's own."""

from __future__ import annotations

import copy
import os
import wave
from types import SimpleNamespace

import pytest

from app import sound_presets
from app.config_manager import DEFAULT_CONFIG
from app.server.handlers import sounds
from app.server.rpc import RpcError


class _Config:
    def __init__(self, base_dir):
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        self.base_dir = base_dir
        self.config_path = base_dir / "config.yaml"
        self.writes = []

    def get_setting(self, section, key):
        return self.data.get(section, {}).get(key)

    def update_user_setting(self, section, key, value):
        self.data.setdefault(section, {})[key] = value
        self.writes.append((section, key, value))


class _Player:
    def __init__(self):
        self.set_calls = []
        self.previewed = []

    def set_sounds(self, **kw):
        self.set_calls.append(kw)

    def preview(self, value):
        self.previewed.append(value)
        return 0.4 if value else 0.0


@pytest.fixture
def rt(tmp_path):
    player = _Player()
    return SimpleNamespace(
        config=_Config(tmp_path),
        state_manager=SimpleNamespace(audio_feedback=SimpleNamespace(_component=player)),
        player=player,
    )


def _wav(path, seconds=0.3, rate=8000):
    with wave.open(str(path), "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(rate)
        clip.writeframes(b"\x00\x00" * int(rate * seconds))
    return str(path)


def test_the_shipped_defaults_are_the_first_two_presets():
    assert sound_presets.PRESETS[0].value == sound_presets.DEFAULT_START
    assert sound_presets.PRESETS[1].value == sound_presets.DEFAULT_STOP
    assert DEFAULT_CONFIG["audio_feedback"]["start_sound"] == sound_presets.DEFAULT_START
    assert DEFAULT_CONFIG["audio_feedback"]["stop_sound"] == sound_presets.DEFAULT_STOP


def test_every_preset_file_ships_and_is_a_short_wav():
    from app.utils import resolve_asset_path

    assert len(sound_presets.PRESETS) >= 8
    for preset in sound_presets.PRESETS:
        path = resolve_asset_path(preset.value)
        assert os.path.isfile(path), preset.id
        with wave.open(path, "rb") as clip:
            assert 0.1 < clip.getnframes() / clip.getframerate() < 1.0, preset.id


def test_the_list_carries_the_presets_the_current_choice_and_the_custom_files(rt, tmp_path):
    custom = sounds.add(rt, {"path": _wav(tmp_path / "mine.wav")})

    listing = sounds.list_sounds(rt, {})

    assert [p["id"] for p in listing["presets"]][:2] == ["warm-rise", "warm-fall"]
    assert listing["start"] == sound_presets.DEFAULT_START
    assert listing["stop"] == sound_presets.DEFAULT_STOP
    assert listing["custom"] == [{"value": custom["value"], "name": "mine"}]


def test_choosing_a_preset_is_stored_and_applied_at_once(rt):
    result = sounds.set_sound(rt, {"slot": "start", "value": "assets/sounds/presets/wood.wav"})

    assert result["value"] == "assets/sounds/presets/wood.wav"
    assert rt.config.writes == [("audio_feedback", "start_sound", "assets/sounds/presets/wood.wav")]
    assert rt.player.set_calls == [{"start": "assets/sounds/presets/wood.wav"}]


def test_a_cue_can_be_silenced_by_an_empty_value(rt):
    sounds.set_sound(rt, {"slot": "stop", "value": ""})

    assert rt.config.writes == [("audio_feedback", "stop_sound", "")]
    assert rt.player.set_calls == [{"stop": ""}]


@pytest.mark.parametrize("value", ["/etc/passwd", "../../x.wav", "assets/sounds/presets/nope.wav", 5, None])
def test_a_value_that_is_not_on_the_list_is_refused_and_never_stored(rt, value):
    with pytest.raises(RpcError) as err:
        sounds.set_sound(rt, {"slot": "start", "value": value})

    assert err.value.code == "bad_params"
    assert rt.config.writes == []


def test_a_wav_elsewhere_on_disk_cannot_be_chosen_without_being_added_first(rt, tmp_path):
    outside = _wav(tmp_path / "outside.wav")

    with pytest.raises(RpcError):
        sounds.set_sound(rt, {"slot": "start", "value": outside})


def test_an_added_file_is_copied_and_can_then_be_chosen(rt, tmp_path):
    original = _wav(tmp_path / "my sound.wav")

    added = sounds.add(rt, {"path": original})
    os.remove(original)
    sounds.set_sound(rt, {"slot": "stop", "value": added["value"]})

    assert os.path.isfile(added["value"]), "the copy outlives the original"
    assert os.path.dirname(added["value"]) == str(sound_presets.custom_dir(rt.config.base_dir).resolve())
    assert rt.config.writes[-1] == ("audio_feedback", "stop_sound", added["value"])


def test_the_same_name_gets_a_new_file_not_an_overwrite(rt, tmp_path):
    first = sounds.add(rt, {"path": _wav(tmp_path / "a.wav", 0.3)})
    second = sounds.add(rt, {"path": _wav(tmp_path / "a.wav", 0.5)})

    assert first["value"] != second["value"]


@pytest.mark.parametrize("make, why", [
    (lambda p: p.write_bytes(b"not audio") or str(p), "not a WAV"),
    (lambda p: _wav(p, seconds=9.0, rate=4000), "too long"),
])
def test_files_that_are_not_short_wav_sounds_are_refused(rt, tmp_path, make, why):
    path = make(tmp_path / "bad.wav")

    with pytest.raises(RpcError) as err:
        sounds.add(rt, {"path": path})

    assert err.value.code == "bad_params", why


def test_only_wav_files_are_taken(rt, tmp_path):
    other = tmp_path / "song.mp3"
    other.write_bytes(b"ID3")

    with pytest.raises(RpcError) as err:
        sounds.add(rt, {"path": str(other)})

    assert err.value.code == "bad_params"


def test_preview_plays_a_listed_sound_and_refuses_others(rt):
    result = sounds.preview(rt, {"value": "assets/sounds/presets/droplet.wav"})

    assert result == {"played": True, "seconds": 0.4}
    assert rt.player.previewed == ["assets/sounds/presets/droplet.wav"]
    with pytest.raises(RpcError):
        sounds.preview(rt, {"value": "/etc/hosts"})


def test_removing_a_custom_sound_resets_the_cues_that_used_it(rt, tmp_path):
    added = sounds.add(rt, {"path": _wav(tmp_path / "mine.wav")})
    sounds.set_sound(rt, {"slot": "start", "value": added["value"]})

    result = sounds.remove(rt, {"value": added["value"]})

    assert result == {"removed": True, "reset": ["start"]}
    assert not os.path.exists(added["value"])
    assert rt.config.data["audio_feedback"]["start_sound"] == sound_presets.DEFAULT_START


def test_a_shipped_preset_cannot_be_removed(rt):
    with pytest.raises(RpcError):
        sounds.remove(rt, {"value": "assets/sounds/presets/wood.wav"})


def test_an_unknown_slot_is_refused(rt):
    with pytest.raises(RpcError):
        sounds.set_sound(rt, {"slot": "cancel", "value": ""})
