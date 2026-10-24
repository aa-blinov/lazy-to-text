"""Microphone devices and the three-second microphone test.

The Qt reference is ``AppController._refresh_shortcuts_devices``,
``_on_test_mic_requested`` and the ``show_mic_test_*`` methods of the view.

The test records on its own thread, so ``devices.test`` returns at once and
everything else is reported by event:

``mic_test``   sticky   ``{"phase": "running", "seconds"}``, then one of
                        ``{"phase": "done", "verdict", "peak", "rms"}`` or
                        ``{"phase": "error", "reason"}``
``mic_level``           ``{"level": 0..1}`` at 20 Hz while the test runs
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict

from app.mic_test import classify_input_level
from app.server.events import bus
from app.server.rpc import RpcError, method

log = logging.getLogger(__name__)

TEST_SECONDS = 3.0
_LEVEL_PERIOD_S = 0.05

bus.add_sticky("mic_test")

_lock = threading.Lock()
_running = False


def _recorder(rt: Any) -> Any:
    return getattr(getattr(rt, "state_manager", None), "audio_recorder", None)


def _listing(rt: Any) -> Dict[str, Any]:
    recorder = _recorder(rt)
    devices = []
    current = None
    if recorder is not None:
        try:
            devices = [
                {"index": int(index), "name": str(name)}
                for index, name in recorder.list_input_devices()
            ]
        except Exception as exc:
            # A device list that cannot be read leaves only "system default".
            log.warning("Could not list the input devices: %s", exc)
        current = getattr(recorder, "device", None)
    return {"devices": devices, "current": current}


@method("devices.list")
def list_devices(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """``{devices: [{index, name}], current}``; ``current`` null is the system default."""
    return _listing(rt)


@method("devices.select")
def select(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Switch the recorder to a listed device and persist ``audio.device``.

    The device has to be one ``devices.list`` offers, or null for the system
    default. A saved index that no longer exists (an unplugged headset, an
    index that shifted) is exactly what a stale or crafted call looks like,
    and storing it leaves the app unable to open the microphone, so it is
    refused with ``device_failed`` and nothing is written. The recorder is
    switched first and the setting follows, so a switch that fails leaves
    the stored choice as it was.
    """
    device = params.get("device")
    if device is not None and (isinstance(device, bool) or not isinstance(device, int)):
        raise RpcError("bad_params", "device must be an index or null", field="device")
    recorder = _recorder(rt)
    if device is not None:
        if recorder is None:
            raise RpcError(
                "device_failed",
                "The microphone cannot be checked while the recording stack "
                "is not running. Choose the system default, or restart the app.",
                field="device",
            )
        known = {entry["index"] for entry in _listing(rt)["devices"]}
        if device not in known:
            raise RpcError(
                "device_failed",
                "That input device is not available. Pick one from the list, "
                "or use the system default.",
                field="device",
            )
    if recorder is not None:
        try:
            recorder.set_device(device)
        except Exception as exc:
            log.warning("Failed to switch input device: %s", exc)
            raise RpcError("device_failed", str(exc), field="device") from exc
    rt.config.update_user_setting("audio", "device", device)
    bus.emit("settings", {"keys": ["audio.device"]})
    return {"device": getattr(recorder, "device", device)}


def _run_test(recorder: Any) -> None:
    global _running
    done = threading.Event()

    def poll_level() -> None:
        getter = getattr(recorder, "current_input_level", None)
        while not done.wait(_LEVEL_PERIOD_S):
            if callable(getter):
                try:
                    bus.emit("mic_level", {"level": float(getter())})
                except Exception:  # pragma: no cover - defensive
                    pass

    poller = threading.Thread(target=poll_level, name="mic-test-level", daemon=True)
    poller.start()
    try:
        result = recorder.test_input_level(TEST_SECONDS)
        peak = float(result.get("peak", 0.0))
        rms = float(result.get("rms", 0.0))
        payload = {
            "phase": "done", "verdict": classify_input_level(peak),
            "peak": peak, "rms": rms,
        }
    except Exception as exc:
        payload = {"phase": "error", "reason": str(exc)}
    finally:
        done.set()
        poller.join(timeout=1.0)
        with _lock:
            _running = False
    bus.emit("mic_test", payload)


@method("devices.test")
def test(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Record three seconds from the selected device and report the level.

    Refused while a dictation is in progress (two openers of the same input)
    and while another test runs.
    """
    global _running
    if rt.state_manager is None:
        raise RpcError("no_stack", rt.stack_error or "no recording stack")
    recorder = _recorder(rt)
    if recorder is None:
        raise RpcError("no_recorder", "audio recorder unavailable")
    if rt.state() != "idle":
        raise RpcError("busy", "wait until current operation finishes")
    with _lock:
        if _running:
            raise RpcError("busy", "a microphone test is already running")
        _running = True
    bus.emit("mic_test", {"phase": "running", "seconds": TEST_SECONDS})
    threading.Thread(
        target=_run_test, args=(recorder,), name="mic-test", daemon=True
    ).start()
    return {"started": True, "seconds": TEST_SECONDS}
