"""Muting the system output for the duration of a recording.

The feature is one checkbox, but it changes a *system* setting, so the
tests are about the things that can go wrong: leaving the machine
silent, and unmuting something the user had muted on purpose.
"""

import json


from app.system_audio import (
    STATE_FILE_NAME,
    SystemOutputMute,
    _fourcc,
    system_output_mute_supported,
)


class _FakeBackend:
    """Stands in for CoreAudio: remembers the mute state per device."""

    def __init__(self, devices=(71,), muted=(), unsupported=()):
        self.devices = list(devices)
        self.muted = {device: device in muted for device in self.devices}
        self.unsupported = set(unsupported)
        self.calls = []

    def output_devices(self):
        self.calls.append("output_devices")
        return list(self.devices)

    def is_muted(self, device):
        self.calls.append(("is_muted", device))
        if device in self.unsupported:
            return None
        return self.muted.get(device, False)

    def set_muted(self, device, muted):
        self.calls.append(("set_muted", device, muted))
        if device in self.unsupported:
            return False
        self.muted[device] = muted
        return True


def _mute(backend, tmp_path, **kwargs):
    """A mute object wired to the fake backend."""
    mute = SystemOutputMute(state_path=tmp_path / STATE_FILE_NAME, **kwargs)
    mute._backend = backend
    return mute


# ---- the mute itself -------------------------------------------------------


def test_a_recording_mutes_every_output_device(tmp_path):
    backend = _FakeBackend(devices=(57, 71))
    mute = _mute(backend, tmp_path)

    assert mute.mute() is True
    assert backend.muted == {57: True, 71: True}
    assert mute.muted_devices == [57, 71]


def test_a_device_that_is_already_muted_is_left_alone(tmp_path):
    """The user muted it. Not ours to undo."""
    backend = _FakeBackend(devices=(57, 71), muted=(71,))
    mute = _mute(backend, tmp_path)

    assert mute.mute() is True
    assert backend.muted == {57: True, 71: True}

    mute.restore()

    # 71 was muted before the recording and stays muted; 57 goes back.
    assert backend.muted == {57: False, 71: True}


def test_the_output_is_unmuted_when_the_recording_stops(tmp_path):
    backend = _FakeBackend()
    mute = _mute(backend, tmp_path)
    mute.mute()

    mute.restore()

    assert backend.muted[71] is False
    assert mute.muted_devices == []


def test_a_device_without_a_mute_control_is_skipped(tmp_path):
    """A virtual or aggregate device has no mute property."""
    backend = _FakeBackend(devices=(67, 71), unsupported=(67,))
    mute = _mute(backend, tmp_path)

    assert mute.mute() is True
    assert mute.muted_devices == [71]


def test_nothing_to_mute_is_not_a_failure(tmp_path):
    backend = _FakeBackend(muted=(71,))
    mute = _mute(backend, tmp_path)

    assert mute.mute() is False
    assert backend.muted[71] is True


def test_restoring_without_a_mute_does_nothing(tmp_path):
    backend = _FakeBackend()
    mute = _mute(backend, tmp_path)

    mute.restore()

    assert backend.calls == []


def test_a_second_mute_does_not_mute_twice(tmp_path):
    backend = _FakeBackend()
    mute = _mute(backend, tmp_path)

    mute.mute()
    mute.mute()

    assert [call for call in backend.calls if call[0] == "set_muted"] == [
        ("set_muted", 71, True),
    ]


# ---- a crash must not leave the machine silent ------------------------------


def test_the_muted_devices_are_recorded_before_the_mute(tmp_path):
    """The state file is what makes an unclean exit recoverable."""
    backend = _FakeBackend(devices=(57, 71))
    state = tmp_path / STATE_FILE_NAME
    mute = _mute(backend, tmp_path)

    mute.mute()

    assert json.loads(state.read_text()) == {"devices": [57, 71]}


def test_the_state_file_is_removed_when_the_output_is_restored(tmp_path):
    backend = _FakeBackend()
    state = tmp_path / STATE_FILE_NAME
    mute = _mute(backend, tmp_path)
    mute.mute()

    mute.restore()

    assert not state.exists()


def test_a_run_that_died_with_the_output_muted_unmutes_it_on_the_next_start(
    tmp_path,
):
    """The crash case: the state file survives, the mute does not."""
    backend = _FakeBackend(devices=(57, 71))
    state = tmp_path / STATE_FILE_NAME
    state.write_text(json.dumps({"devices": [57, 71]}))
    backend.muted[57] = True
    backend.muted[71] = True
    mute = _mute(backend, tmp_path)

    assert mute.recover_if_left_muted() is True
    assert backend.muted == {57: False, 71: False}
    assert not state.exists()


def test_a_state_file_from_the_first_version_is_understood(tmp_path):
    """It named one device; the format changed to a list."""
    backend = _FakeBackend(devices=(71,))
    state = tmp_path / STATE_FILE_NAME
    state.write_text(json.dumps({"device": 71}))
    backend.muted[71] = True
    mute = _mute(backend, tmp_path)

    assert mute.recover_if_left_muted() is True
    assert backend.muted[71] is False


def test_a_state_file_with_a_broken_device_is_dropped(tmp_path):
    """A device that is gone is not a reason to keep the file around."""
    backend = _FakeBackend()
    state = tmp_path / STATE_FILE_NAME
    state.write_text(json.dumps({"devices": [999]}))
    mute = _mute(backend, tmp_path)

    assert mute.recover_if_left_muted() is True
    assert not state.exists()


def test_a_corrupt_state_file_does_not_stop_the_app(tmp_path):
    backend = _FakeBackend()
    state = tmp_path / STATE_FILE_NAME
    state.write_text("not json at all")
    mute = _mute(backend, tmp_path)

    assert mute.recover_if_left_muted() is False
    assert not state.exists()


# ---- the platform -----------------------------------------------------------


def test_a_platform_without_the_feature_reports_itself_unsupported(monkeypatch):
    monkeypatch.setattr("app.system_audio.sys.platform", "win32")

    assert system_output_mute_supported() is False
    mute = SystemOutputMute()
    assert mute.supported is False
    assert mute.mute() is False


# ---- the constants ----------------------------------------------------------


def test_the_coreaudio_selectors_are_the_ones_apple_defines():
    """The scope for the output is ``outp``.

    It is not ``out `` — that looks right, is a different constant, and
    CoreAudio answers "who?" (kAudioHardwareUnknownPropertyError) for
    the whole property when it is wrong. The mute then silently does
    nothing, which is exactly the kind of failure that looks like
    "the checkbox does not work".
    """
    from app import system_audio

    assert system_audio._fourcc("outp") == 0x6F757470
    assert system_audio._SCOPE_OUTPUT == "outp"
    assert system_audio._SELECTOR_MUTE == "mute"
    assert system_audio._SELECTOR_DEVICES == "dev#"
    assert system_audio._SELECTOR_STREAMS == "stm#"
    assert system_audio._SCOPE_GLOBAL == "glob"


def test_the_fourcc_helper_reads_the_headers_style_codes():
    assert _fourcc("glob") == 0x676C6F62


# ---- the device enumeration (the real CoreAudio call pattern) --------------

import ctypes
import struct
import types

from app.system_audio import _CoreAudio, _PropertyAddress, _SYSTEM_OBJECT


def _selector_name(field):
    """The four-character selector a property address carries, decoded."""
    return int(field).to_bytes(4, "big").decode("ascii")


class _FakeCoreAudioLib:
    """The slice of CoreAudio ``_CoreAudio`` uses, with the *array*
    semantics Apple defines for ``kAudioHardwarePropertyDevices``: the
    size call answers how many bytes the ``AudioDeviceID[]`` needs, and
    the get call fills a buffer of that size."""

    def __init__(self, device_ids, outputs):
        self.device_ids = list(device_ids)
        self.outputs = set(outputs)
        self.muted = {d: False for d in self.outputs}

    def _sel(self, addr):
        a = addr._obj
        return _selector_name(a.mSelector), _selector_name(a.mScope)

    def AudioObjectGetPropertyDataSize(self, obj, addr, _q, _qt, size_ptr):
        sel, scope = self._sel(addr)
        if obj == _SYSTEM_OBJECT and sel == "dev#" and scope == "glob":
            size_ptr._obj.value = 4 * len(self.device_ids)
            return 0
        if sel == "stm#" and scope == "outp" and obj in self.outputs:
            size_ptr._obj.value = 4
            return 0
        if sel == "mute" and scope == "outp" and obj in self.muted:
            size_ptr._obj.value = 4
            return 0
        return 0xFFFFFFFF  # !ok — 'who?'

    def AudioObjectGetPropertyData(self, obj, addr, _q, _qt, actual_ptr, buffer):
        sel, scope = self._sel(addr)
        if obj == _SYSTEM_OBJECT and sel == "dev#" and scope == "glob":
            raw = b"".join(struct.pack("<I", d) for d in self.device_ids)
            buffer[:len(raw)] = raw
            actual_ptr._obj.value = len(raw)
            return 0
        if sel == "stm#" and scope == "outp" and obj in self.outputs:
            buffer[:4] = struct.pack("<I", 1234)
            actual_ptr._obj.value = 4
            return 0
        if sel == "mute" and scope == "outp" and obj in self.muted:
            buffer[:4] = struct.pack("<I", 1 if self.muted[obj] else 0)
            actual_ptr._obj.value = 4
            return 0
        return 0xFFFFFFFF

    def AudioObjectSetPropertyData(self, obj, addr, _q, _qt, size, value):
        sel, scope = self._sel(addr)
        if sel == "mute" and scope == "outp" and obj in self.muted:
            self.muted[obj] = bool(int.from_bytes(
                ctypes.string_at(value, size), "little"))
            return 0
        return 0xFFFFFFFF


def _coreaudio(monkeypatch, device_ids, outputs):
    """A ``_CoreAudio`` wired to the fake library above."""
    backend = _CoreAudio()
    lib = _FakeCoreAudioLib(device_ids, outputs)
    monkeypatch.setattr(backend, "_library", lambda: lib)
    return backend, lib


def test_output_devices_reads_the_whole_device_array(monkeypatch):
    """``dev#`` answers with an array of ids, not a count. A single 4-byte
    buffer held only the first id, which the loop then read back as the
    number of devices — with several output devices the mute covered at
    most one of them, and the ids probed (1..first_id) were arbitrary
    objects, not devices at all."""
    backend, _ = _coreaudio(monkeypatch, device_ids=(47, 61, 91), outputs=(47, 61))

    assert backend.output_devices() == [47, 61]  # 91: no output stream


def test_the_mute_covers_every_device_the_array_reports(tmp_path, monkeypatch):
    backend, lib = _coreaudio(monkeypatch, device_ids=(47, 61, 91), outputs=(47, 61))
    mute = SystemOutputMute(state_path=tmp_path / STATE_FILE_NAME)
    mute._backend = backend

    assert mute.mute() is True
    assert lib.muted == {47: True, 61: True}

    mute.restore()
    assert lib.muted == {47: False, 61: False}
