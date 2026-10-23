"""Mute the system output while the app records, and put it back after.

Dictation is a listening task: anything the machine plays while the
microphone is open — a music player, a chat notification, a video call —
is both a distraction and, if it comes out of the speakers, part of the
recording. This module mutes the default output device for the duration
of a recording and restores it afterwards.

macOS only. The mute is CoreAudio's own per-device property
(``kAudioDevicePropertyMute``), which is what a system volume slider
changes, so the user sees the volume icon go muted and the state is the
one macOS itself keeps. Windows has no equivalent without a WASAPI
mixer, so :meth:`SystemOutputMute.mute` there is a no-op.

Two things the module is careful about:

- **A mute the user asked for is not ours to undo.** If the output was
  already muted when the recording started, the module leaves it alone
  and does not unmute it at the end.
- **A crash must not leave the machine silent.** The device that was
  muted is written to a state file *before* it is muted, and the file
  is removed when the mute is undone. On the next launch the file is
  read back and the device unmuted — so a crash during a recording
  costs the user one launch, not their sound.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import logging
import sys
from pathlib import Path
from typing import Optional


log = logging.getLogger(__name__)

# CoreAudio object ids and property addresses. The four-character
# selectors are the ones Apple's headers use; they are not
# interchangeable with anything that looks similar.
_SYSTEM_OBJECT = 1
_SELECTOR_DEVICES = "dev#"
_SELECTOR_STREAMS = "stm#"
_SELECTOR_MUTE = "mute"
_SCOPE_GLOBAL = "glob"
# kAudioObjectPropertyScopeOutput. Note the four characters: "outp", not
# "out " — the latter is a different constant and CoreAudio answers
# "who?" (kAudioHardwareUnknownPropertyError) for the whole property.
_SCOPE_OUTPUT = "outp"

#: The state file name inside the config directory.
STATE_FILE_NAME = "output-mute.json"


def _fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


def system_output_mute_supported() -> bool:
    """True when this platform can mute the system output.

    macOS only: the mute is a CoreAudio device property, and Windows
    has no equivalent without a WASAPI mixer. The UI uses this to hide
    the control rather than show a box that does nothing.
    """
    return sys.platform == "darwin"


class _PropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


class _CoreAudio:
    """The CoreAudio calls this module needs, through ``ctypes``.

    ``ctypes`` rather than a binding package: the app already depends
    on ``sounddevice``, but nothing on CoreAudio, and a handful of
    property reads are not worth a framework binding.
    """

    def __init__(self) -> None:
        self._lib = None

    def _library(self):
        if self._lib is None:
            path = ctypes.util.find_library("CoreAudio")
            if not path:
                raise OSError("CoreAudio framework not found")
            lib = ctypes.CDLL(path)
            lib.AudioObjectGetPropertyData.argtypes = [
                ctypes.c_uint32, ctypes.POINTER(_PropertyAddress),
                ctypes.c_uint32, ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
            ]
            lib.AudioObjectGetPropertyData.restype = ctypes.c_int32
            lib.AudioObjectGetPropertyDataSize.argtypes = [
                ctypes.c_uint32, ctypes.POINTER(_PropertyAddress),
                ctypes.c_uint32, ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint32),
            ]
            lib.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
            lib.AudioObjectSetPropertyData.argtypes = [
                ctypes.c_uint32, ctypes.POINTER(_PropertyAddress),
                ctypes.c_uint32, ctypes.c_void_p,
                ctypes.c_uint32, ctypes.c_void_p,
            ]
            lib.AudioObjectSetPropertyData.restype = ctypes.c_int32
            self._lib = lib
        return self._lib

    def _address(self, selector: str, scope: str) -> _PropertyAddress:
        return _PropertyAddress(_fourcc(selector), _fourcc(scope), 0)

    def _raw(self, obj: int, selector: str, scope: str):
        """The raw bytes of a property, or ``(status, None)``."""
        lib = self._library()
        address = self._address(selector, scope)
        size = ctypes.c_uint32(0)
        status = lib.AudioObjectGetPropertyDataSize(
            obj, ctypes.byref(address), 0, None, ctypes.byref(size))
        if status != 0:
            return status, None
        buffer = ctypes.create_string_buffer(size.value)
        actual = ctypes.c_uint32(size.value)
        status = lib.AudioObjectGetPropertyData(
            obj, ctypes.byref(address), 0, None,
            ctypes.byref(actual), buffer)
        if status != 0:
            return status, None
        return status, buffer.raw[:size.value]

    def output_devices(self) -> list:
        """Every device that has an output stream.

        Not just the default one. Measured on this machine: the default
        output was a Bluetooth headset whose output channel was already
        muted at the device level, while the sound the user actually
        heard came from another device — so muting only the default
        would have been a no-op exactly where it was needed.
        """
        lib = self._library()
        address = self._address(_SELECTOR_DEVICES, _SCOPE_GLOBAL)
        size = ctypes.c_uint32(4)
        count = ctypes.c_uint32(0)
        status = lib.AudioObjectGetPropertyData(
            _SYSTEM_OBJECT, ctypes.byref(address), 0, None,
            ctypes.byref(size), ctypes.byref(count))
        if status != 0:
            raise OSError(f"CoreAudio device list failed: {status}")

        devices = []
        for device in range(1, count.value + 1):
            status, raw = self._raw(device, _SELECTOR_STREAMS, _SCOPE_OUTPUT)
            if status == 0 and raw and len(raw) >= 4:
                devices.append(device)
        return devices

    def is_muted(self, device: int):
        """The device's mute state, or ``None`` when it has no such control."""
        status, raw = self._raw(device, _SELECTOR_MUTE, _SCOPE_OUTPUT)
        if status != 0 or raw is None or len(raw) < 4:
            return None
        return bool(int.from_bytes(raw[:4], "little"))

    def set_muted(self, device: int, muted: bool) -> bool:
        """Set the device's mute state. False when it has no such control."""
        lib = self._library()
        address = self._address(_SELECTOR_MUTE, _SCOPE_OUTPUT)
        value = ctypes.c_uint32(1 if muted else 0)
        status = lib.AudioObjectSetPropertyData(
            device, ctypes.byref(address), 0, None,
            ctypes.sizeof(value), ctypes.byref(value))
        return status == 0


class SystemOutputMute:
    """Mutes the system output for the duration of a recording.

    Use it as a pair: :meth:`mute` when the recording starts and
    :meth:`restore` when it stops. :meth:`restore` is idempotent and
    safe to call when nothing was muted.

    Every output device is covered, not only the default one. The
    default output can be a device that is already muted at the device
    level — a Bluetooth headset whose output channel is off while its
    microphone works — while the sound the user actually hears comes
    from somewhere else. Muting only the default would then do nothing
    at all, in exactly the situation the feature is for.
    """

    def __init__(self, logger=None, state_path: Optional[Path] = None) -> None:
        self._logger = logger or log
        self._state_path = Path(state_path) if state_path else None
        self._backend = _CoreAudio() if system_output_mute_supported() else None
        self._muted_devices: list = []

    @property
    def supported(self) -> bool:
        """True when this platform can mute the system output."""
        return self._backend is not None

    @property
    def muted_devices(self) -> list:
        """The devices this object muted."""
        return list(self._muted_devices)

    def mute(self) -> bool:
        """Mute every output device that is currently audible.

        Returns True when *this* call muted something. A device that
        was already muted is left as it is and is not ours to undo: the
        user muted it, and unmuting it at the end of the recording
        would be the app changing a setting it was not asked to change.
        """
        if self._backend is None:
            return False
        if self._muted_devices:
            return True
        try:
            candidates = []
            for device in self._backend.output_devices():
                muted = self._backend.is_muted(device)
                if muted is None:
                    # No mute control on this device (a virtual or
                    # aggregate one) — there is nothing to do with it.
                    continue
                if muted:
                    continue
                candidates.append(device)
            if not candidates:
                self._logger.debug(
                    "Every output device is already muted — leaving them alone"
                )
                return False
            # The state file goes first: if the app dies between the
            # write and the mute, the next launch unmutes devices that
            # were never muted, which is harmless. The other order
            # leaves the machine silent with nothing to undo it.
            self._write_state(candidates)
            muted = []
            for device in candidates:
                if self._backend.set_muted(device, True):
                    muted.append(device)
        except Exception as exc:
            self._logger.warning("Could not mute the system output: %s", exc)
            self._clear_state()
            return False
        if not muted:
            self._logger.warning(
                "Could not mute any output device — leaving them as they are"
            )
            self._clear_state()
            return False
        self._muted_devices = muted
        self._logger.info(
            "Muted %d output device(s) for the recording", len(muted),
        )
        return True

    def restore(self) -> None:
        """Unmute what :meth:`mute` muted. Safe to call twice."""
        devices = self._muted_devices
        self._muted_devices = []
        if not devices:
            return
        try:
            if self._backend is not None:
                for device in devices:
                    self._backend.set_muted(device, False)
                self._logger.info("System output unmuted")
        except Exception as exc:
            self._logger.warning("Could not unmute the system output: %s", exc)
        finally:
            self._clear_state()

    def recover_if_left_muted(self) -> bool:
        """Unmute devices a previous run muted and never restored.

        The app can die between muting and restoring — a crash, a
        forced quit. The state file is what makes that recoverable, so
        it is read once at startup.
        """
        if self._backend is None or self._state_path is None:
            return False
        if not self._state_path.exists():
            return False
        devices = []
        try:
            data = json.loads(self._state_path.read_text())
            if "devices" in data:
                devices = [int(device) for device in data["devices"]]
            elif "device" in data:
                # The first version of this file named one device.
                devices = [int(data["device"])]
        except Exception as exc:
            self._logger.warning(
                "Could not read the mute state file %s: %s",
                self._state_path, exc,
            )
            self._clear_state()
            return False
        if not devices:
            self._clear_state()
            return False
        try:
            for device in devices:
                self._backend.set_muted(device, False)
            self._logger.info(
                "Restored %d output device(s) after an unclean exit",
                len(devices),
            )
            return True
        except Exception as exc:
            self._logger.warning(
                "Could not unmute the output devices after an unclean exit: %s",
                exc,
            )
            return False
        finally:
            self._clear_state()

    # ---- state file -----------------------------------------------------

    def _write_state(self, devices: list) -> None:
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({"devices": list(devices)}))
        except Exception as exc:
            self._logger.warning("Could not write the mute state file: %s", exc)

    def _clear_state(self) -> None:
        if self._state_path is None:
            return
        try:
            self._state_path.unlink(missing_ok=True)
        except Exception as exc:
            self._logger.warning("Could not remove the mute state file: %s", exc)
