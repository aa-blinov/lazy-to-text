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


def test_the_shipped_defaults_are_the_first_set():
    first = sound_presets.SOUND_SETS[0]
    assert (first.start, first.stop) == (sound_presets.DEFAULT_START, sound_presets.DEFAULT_STOP)
    assert DEFAULT_CONFIG["audio_feedback"]["start_sound"] == sound_presets.DEFAULT_START
    assert DEFAULT_CONFIG["audio_feedback"]["stop_sound"] == sound_presets.DEFAULT_STOP


def test_every_set_ships_both_of_its_sounds_as_short_wavs():
    from app.utils import resolve_asset_path

    assert len(sound_presets.SOUND_SETS) >= 6
    for sound_set in sound_presets.SOUND_SETS:
        assert sound_set.start != sound_set.stop, sound_set.id
        for value in (sound_set.start, sound_set.stop):
            path = resolve_asset_path(value)
            assert os.path.isfile(path), (sound_set.id, value)
            with wave.open(path, "rb") as clip:
                assert 0.1 < clip.getnframes() / clip.getframerate() < 1.0, (sound_set.id, value)


def test_a_pair_is_recognised_as_its_set_and_a_mixed_pair_is_custom():
    wood, glass = sound_presets.SOUND_SETS[1], sound_presets.SOUND_SETS[6]

    assert sound_presets.theme_of(wood.start, wood.stop) == "wood"
    assert sound_presets.theme_of(wood.start, glass.stop) == sound_presets.CUSTOM
    assert sound_presets.theme_of("", "") == sound_presets.CUSTOM


def test_the_list_carries_the_sets_the_current_pair_and_the_custom_files(rt, tmp_path):
    custom = sounds.add(rt, {"path": _wav(tmp_path / "mine.wav")})

    listing = sounds.list_sounds(rt, {})

    assert [x["id"] for x in listing["sets"]][:2] == ["warm", "wood"]
    assert listing["sets"][1]["start"].endswith("wood-start.wav")
    assert listing["start"] == sound_presets.DEFAULT_START
    assert listing["stop"] == sound_presets.DEFAULT_STOP
    assert listing["theme"] == "warm"
    assert listing["custom"] == [{"value": custom["value"], "name": "mine"}]


def test_choosing_a_set_changes_both_cues_together_and_applies_them_at_once(rt):
    result = sounds.set_theme(rt, {"theme": "wood"})

    assert result["theme"] == "wood"
    assert rt.config.writes == [
        ("audio_feedback", "start_sound", "assets/sounds/sets/wood-start.wav"),
        ("audio_feedback", "stop_sound", "assets/sounds/sets/wood-stop.wav"),
    ]
    assert rt.player.set_calls == [{"start": "assets/sounds/sets/wood-start.wav", "stop": "assets/sounds/sets/wood-stop.wav"}]
    assert sounds.list_sounds(rt, {})["theme"] == "wood"


def test_an_unknown_set_is_refused(rt):
    with pytest.raises(RpcError):
        sounds.set_theme(rt, {"theme": "nope"})
    assert rt.config.writes == []


def test_one_cue_set_to_a_file_of_its_own_makes_the_pair_custom(rt, tmp_path):
    sounds.set_theme(rt, {"theme": "wood"})
    added = sounds.add(rt, {"path": _wav(tmp_path / "mine.wav")})

    sounds.set_sound(rt, {"slot": "stop", "value": added["value"]})

    assert sounds.list_sounds(rt, {})["theme"] == "custom"


def test_choosing_one_shipped_sound_for_one_cue_is_stored_and_applied_at_once(rt):
    result = sounds.set_sound(rt, {"slot": "start", "value": "assets/sounds/sets/wood-start.wav"})

    assert result["value"] == "assets/sounds/sets/wood-start.wav"
    assert rt.config.writes == [("audio_feedback", "start_sound", "assets/sounds/sets/wood-start.wav")]
    assert rt.player.set_calls == [{"start": "assets/sounds/sets/wood-start.wav"}]


def test_a_cue_can_be_silenced_by_an_empty_value(rt):
    sounds.set_sound(rt, {"slot": "stop", "value": ""})

    assert rt.config.writes == [("audio_feedback", "stop_sound", "")]
    assert rt.player.set_calls == [{"stop": ""}]


@pytest.mark.parametrize("value", ["/etc/passwd", "../../x.wav", "assets/sounds/sets/nope.wav", 5, None])
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
    result = sounds.preview(rt, {"value": "assets/sounds/sets/droplet-start.wav"})

    assert result == {"played": True, "seconds": 0.4}
    assert rt.player.previewed == ["assets/sounds/sets/droplet-start.wav"]
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
        sounds.remove(rt, {"value": "assets/sounds/sets/wood-start.wav"})


def test_an_unknown_slot_is_refused(rt):
    with pytest.raises(RpcError):
        sounds.set_sound(rt, {"slot": "cancel", "value": ""})


def test_a_file_that_no_cue_uses_any_more_is_deleted(rt, tmp_path):
    first = sounds.add(rt, {"path": _wav(tmp_path / "first.wav")})
    sounds.set_sound(rt, {"slot": "start", "value": first["value"]})
    second = sounds.add(rt, {"path": _wav(tmp_path / "second.wav")})

    sounds.set_sound(rt, {"slot": "start", "value": second["value"]})

    assert not os.path.exists(first["value"]), "replaced, so no longer kept"
    assert os.path.exists(second["value"])


def test_choosing_a_set_clears_the_own_files_of_both_cues(rt, tmp_path):
    a = sounds.add(rt, {"path": _wav(tmp_path / "a.wav")})
    b = sounds.add(rt, {"path": _wav(tmp_path / "b.wav")})
    sounds.set_sound(rt, {"slot": "start", "value": a["value"]})
    sounds.set_sound(rt, {"slot": "stop", "value": b["value"]})

    sounds.set_theme(rt, {"theme": "wood"})

    assert sounds.list_sounds(rt, {})["custom"] == []


def test_a_file_kept_by_the_other_cue_survives_a_change_to_one_cue(rt, tmp_path):
    a = sounds.add(rt, {"path": _wav(tmp_path / "a.wav")})
    sounds.set_sound(rt, {"slot": "start", "value": a["value"]})
    sounds.set_sound(rt, {"slot": "stop", "value": a["value"]})

    sounds.set_sound(rt, {"slot": "start", "value": ""})

    assert os.path.exists(a["value"])
