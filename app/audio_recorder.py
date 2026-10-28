import logging
import sys
import threading
import time
import traceback
from typing import Optional, Union

import numpy as np
import sounddevice as sd

def _where_sound_is_muted() -> str:
    """The operating system's own name for where an input is muted."""
    if sys.platform == "win32":
        return "muted in Windows Sound settings"
    if sys.platform == "darwin":
        return "muted in System Settings > Sound"
    return "muted in the system sound settings"


class AudioRecorder:
    WHISPER_SAMPLE_RATE = 16000
    THREAD_JOIN_TIMEOUT = 2.0
    # A press that ends sooner than this with no frames at all was too short
    # for the stream to deliver a block; later than this it is a dead stream.
    NO_FRAMES_GRACE_S = 0.5
    ABORT_TIMEOUT = 1.0
    RECORDING_SLEEP_INTERVAL = 100
    START_CONFIRM_TIMEOUT = 2.0
    STREAM_DTYPE = np.float32

    def __init__(self,
                 channels: int = 1,
                 dtype: str = "float32",
                 max_duration: int = 30,
                 on_max_duration_reached: callable = None,
                 device: Optional[Union[int, str]] = None):

        self.sample_rate = self.WHISPER_SAMPLE_RATE
        self.channels = channels
        self.dtype = dtype
        self.max_duration = max_duration
        self.on_max_duration_reached = on_max_duration_reached
        # ``device`` may be ``None`` (use system default), an int index, or a
        # case-insensitive substring of the device name. Resolved to an int
        # at __init__ time so the rest of the code only deals with integers.
        self.device: Optional[int] = self._resolve_device(device)
        self.is_recording = False
        self.audio_data = []
        self.recording_thread = None
        # The input stream the recording thread owns. Kept here so a thread
        # that will not finish can still be aborted from outside it.
        self._stream = None
        self.recording_start_time = None
        # Why the last stop returned no audio: "too_short" when the press
        # ended before the stream delivered its first block, "no_frames" when
        # it ran long enough to have delivered some and delivered none, None
        # when it did return audio. Read by the state manager to word the
        # failure.
        self.empty_reason: Optional[str] = None
        self._capture_sample_rate: Optional[int] = None
        # Updated from the audio callback on the recording thread; read
        # by the UI poller. Plain float assignment is atomic under the
        # GIL — no lock needed for the worst-case stale-by-one-tick read.
        self._current_input_level: float = 0.0
        self.logger = logging.getLogger(__name__)
        # Why the last start or recording failed, as a sentence a person
        # can read; ``None`` while nothing is wrong.
        self.last_error: Optional[str] = None
        # Set by the owner. Called from the recording thread when the
        # input stream breaks after ``start_recording`` returned True and
        # nothing usable was captured, so the failure still gets an outcome.
        self.on_recording_failed: Optional[callable] = None
        # Set once the recording thread has opened the stream or failed to.
        self._stream_event = threading.Event()
        # True once ``start_recording`` has answered "started"; a later
        # failure is reported by callback, an earlier one by the return value.
        self._start_returned = False

        self._test_microphone()

    def _wait_for_thread_finish(self):
        thread = self.recording_thread
        if thread is None:
            self.logger.info("Audio stop found no capture thread")
            return
        started = time.monotonic()
        thread.join(timeout=self.THREAD_JOIN_TIMEOUT)
        if thread.is_alive():
            self._release_stuck_recording(thread)
        self.logger.info(
            "Audio capture thread joined in %.2f s (alive=%s)",
            time.monotonic() - started, thread.is_alive(),
        )

    def _release_stuck_recording(self, thread: threading.Thread) -> bool:
        """Abort the input stream of a recording thread that will not finish.

        The thread owns the input stream, and the stream holds the device for
        as long as the thread is alive, so the next recording gets no audio.
        Log where the thread is blocked, then abort the stream. Returns True
        once the thread has finished.
        """
        frame = sys._current_frames().get(thread.ident)
        where = "".join(traceback.format_stack(frame)) if frame is not None else "(no frame)\n"
        self.logger.warning(
            "Recording thread is still alive after stopping; aborting its input stream. Blocked at:\n%s",
            where,
        )
        stream = self._stream
        if stream is not None:
            self._abort_stream(stream)
        thread.join(timeout=self.ABORT_TIMEOUT)
        if thread.is_alive():
            self.logger.error("Recording thread is still alive after aborting its input stream")
            return False
        self.logger.info("Recording thread finished after its input stream was aborted")
        return True

    def _abort_stream(self, stream):
        # Abort from a helper thread, so an abort that blocks does not block
        # the caller with it.
        def abort():
            try:
                stream.abort()
            except Exception as e:
                self.logger.error("Aborting the input stream failed: %s", e)

        aborter = threading.Thread(target=abort, daemon=True, name="audio-abort")
        aborter.start()
        aborter.join(timeout=self.ABORT_TIMEOUT)
        if aborter.is_alive():
            self.logger.error("Aborting the input stream did not return within %.1f s", self.ABORT_TIMEOUT)

    @staticmethod
    def list_input_devices() -> list:
        """Return ``[(index, name), ...]`` for every input-capable device.

        On Windows the MME host API truncates device names to 32 characters
        ("Микрофон (Razer BlackShark V2 P" instead of "Pro"). Prefer WASAPI
        if it's available — same hardware, full names, modern API. Falls
        back to listing every input across every host API on platforms
        where WASAPI is not present (Linux, macOS).
        """
        out = []
        try:
            preferred_hostapi = AudioRecorder._find_hostapi(("WASAPI",))
            for idx, info in enumerate(sd.query_devices()):
                if info.get("max_input_channels", 0) <= 0:
                    continue
                if preferred_hostapi is not None and info.get("hostapi") != preferred_hostapi:
                    continue
                out.append((idx, info.get("name", "<unnamed>")))
        except Exception:
            pass
        return out

    @staticmethod
    def _find_hostapi(needles) -> Optional[int]:
        """Return the index of the first matching host API, or None."""
        try:
            for i, ha in enumerate(sd.query_hostapis()):
                name = (ha.get("name") or "").upper()
                if any(n.upper() in name for n in needles):
                    return i
        except Exception:
            pass
        return None

    def set_device(self, raw: Optional[Union[int, str]]) -> Optional[int]:
        """Switch the input device used for the next recording. Returns the
        resolved index (or ``None`` for system default)."""
        resolved = self._resolve_device(raw)
        if resolved is not None and not self._input_device_exists(resolved):
            raise ValueError(
                "That microphone is not available. Pick another one or "
                "use the system default."
            )
        self.device = resolved
        return self.device

    @staticmethod
    def _input_device_exists(index: int) -> bool:
        try:
            info = sd.query_devices(index)
            return int(info.get("max_input_channels", 0)) > 0
        except Exception:
            return False

    def _fall_back_to_default_device(self) -> None:
        """Use the system default input because the saved device is gone.

        An unplugged USB or Bluetooth microphone leaves its index in the
        config. That must cost the user a line in the log, not the whole
        recording stack.
        """
        self.logger.warning(
            "The saved microphone (device %s) is not available - using the "
            "system default input instead. Pick a microphone in Settings to "
            "choose another.",
            self.device,
            extra={'user_message': True},
        )
        self.device = None

    def test_input_level(self, duration_s: float = 3.0) -> dict:
        """Synchronous mic check — capture from the selected device for
        ``duration_s`` seconds and report peak / RMS amplitude.

        Uses ``sd.InputStream`` instead of the simpler blocking
        ``sd.rec`` so the per-block callback can update
        ``self._current_input_level`` in real time — the UI's VU
        meter polls that field and follows the level live during
        the test, same as during a real recording. Without this the
        meter sat at zero for the whole 3 s window.

        Captures at the device's native sample rate (so WASAPI
        doesn't complain about 16 kHz like it does for the real
        recording path); we only want amplitude statistics so no
        resampling is needed.

        Returns ``{"peak": float, "rms": float, "duration_s": float}``.
        Both amplitudes are normalised to the [0, 1] range. Raises
        any underlying ``sounddevice`` error so the caller can
        surface a readable message.
        """
        device_idx = self.device
        if device_idx is not None:
            try:
                info = sd.query_devices(device_idx)
                rate = int(info.get("default_samplerate", self.sample_rate))
            except Exception:
                rate = self.sample_rate
        else:
            rate = self.sample_rate

        # ~50 ms blocks — fast enough to feel responsive on the
        # VU meter (~20 Hz updates) without piling up Python
        # callbacks. Floor at 256 frames so very low rates don't
        # trip sounddevice's minimum block size.
        blocksize = max(256, int(rate * 0.05))
        chunks: list = []

        def _on_block(indata, frames, time_info, status):  # noqa: ARG001
            chunks.append(np.asarray(indata).copy())
            flat = np.asarray(indata).flatten()
            if flat.size:
                # Per-block PEAK amplitude rather than RMS so the
                # value matches the meter's 0–1 scale and the
                # post-test frozen reading. RMS for speech is 3–5×
                # smaller than peak — feeding RMS made the meter
                # barely twitch even on yelling, then jump on the
                # frozen-peak overlay after the test ended. The UI
                # widget applies its own peak-and-decay envelope so
                # we don't need any smoothing here.
                self._current_input_level = float(
                    np.abs(flat).max()
                )

        try:
            with sd.InputStream(
                samplerate=rate,
                channels=self.channels,
                device=device_idx,
                dtype=self.STREAM_DTYPE,
                blocksize=blocksize,
                callback=_on_block,
            ):
                # Block the calling (worker) thread for the test
                # window — sounddevice runs the callback on its own
                # thread, so this sleep doesn't starve the audio
                # pipeline.
                time.sleep(float(duration_s))
        finally:
            # Reset the live level so the meter doesn't keep
            # showing the last reading after the test ends.
            self._current_input_level = 0.0

        if not chunks:
            return {"peak": 0.0, "rms": 0.0, "duration_s": float(duration_s)}
        audio = np.concatenate(chunks, axis=0)
        flat = audio.flatten()
        if flat.size == 0:
            return {"peak": 0.0, "rms": 0.0, "duration_s": float(duration_s)}
        peak = float(np.abs(flat).max())
        rms = float(np.sqrt(np.mean(flat ** 2)))
        return {
            "peak": peak,
            "rms": rms,
            "duration_s": float(duration_s),
        }

    def _resolve_device(self, raw: Optional[Union[int, str]]) -> Optional[int]:
        if raw is None or raw == "":
            return None
        try:
            if isinstance(raw, int) or (isinstance(raw, str) and raw.lstrip("-").isdigit()):
                return int(raw)
            needle = str(raw).lower()
            for idx, info in enumerate(sd.query_devices()):
                if info.get("max_input_channels", 0) <= 0:
                    continue
                if needle in str(info.get("name", "")).lower():
                    return idx
        except Exception:
            pass
        return None

    def _test_microphone(self):
        try:
            # List every input device so the user can pick one if the
            # default is wrong.
            for idx, info in enumerate(sd.query_devices()):
                if info.get("max_input_channels", 0) <= 0:
                    continue
                self.logger.info(
                    "Input device [%d]: %s (%s)",
                    idx,
                    info.get("name", "<unnamed>"),
                    info.get("hostapi_name") or info.get("hostapi", ""),
                )

            if self.device is not None and not self._input_device_exists(self.device):
                self._fall_back_to_default_device()

            if self.device is not None:
                info = sd.query_devices(self.device)
                self.logger.info(
                    "Recording from device [%d]: %s",
                    self.device, info.get("name", "<unnamed>"),
                )
            else:
                default_input = sd.query_devices(kind="input")
                self.logger.info(
                    "Recording from system default: %s",
                    default_input.get("name", "<unnamed>"),
                )
        except Exception as e:
            # No usable input right now. The recorder is still built: a
            # microphone plugged in later works without a restart, and
            # every start reports what is wrong until then.
            self.last_error = f"No microphone is available: {e}"
            self.logger.error("Microphone test failed: %s", e)

    def start_recording(self):
        if self.is_recording:
            return False

        previous = self.recording_thread
        if previous is not None and previous.is_alive():
            if not self._release_stuck_recording(previous):
                self.logger.error(
                    "Microphone is still held by the previous recording. Restart the app.",
                    extra={'user_message': True},
                )
                return False

        try:
            self.logger.info("Starting audio recording...")
            self.last_error = None
            self.empty_reason = None
            if self.device is not None and not self._input_device_exists(self.device):
                self._fall_back_to_default_device()
            self._stream_event.clear()
            self._start_returned = False
            self.is_recording = True
            self.audio_data = []
            self.recording_start_time = time.time()

            self.recording_thread = threading.Thread(target=self._record_audio)
            self.recording_thread.daemon = True  # Thread will close when main program closes
            self.recording_thread.start()

            # Wait briefly for the stream to open: a device that cannot be
            # opened used to fail on the thread, after this method had
            # already said "started". A slow open (a permission prompt)
            # is not a failure; it is reported by ``on_recording_failed``
            # if it fails later.
            self._stream_event.wait(timeout=self.START_CONFIRM_TIMEOUT)
            if not self.is_recording and self.last_error:
                self.logger.error(
                    "Could not start recording: %s", self.last_error,
                    extra={'user_message': True},
                )
                return False
            self._start_returned = True

            self.logger.info("Recording started! Speak now...", extra={'user_message': True})
            return True

        except Exception as e:
            self.logger.error("Failed to start audio recording: %s", e)
            self.last_error = str(e)
            self.logger.error("Failed to start recording!", extra={'user_message': True})
            self.is_recording = False
            return False

    def stop_recording(self) -> Optional[np.ndarray]:
        if not self.is_recording:
            self.logger.warning("Audio stop requested while the recorder was not recording")
            return None

        self.is_recording = False
        started = time.monotonic()
        self.logger.info("Stopping microphone capture (%d buffered blocks)", len(self.audio_data))
        self._wait_for_thread_finish()
        # Reset the live level so the UI's VU meter doesn't keep
        # showing the last chunk's reading after the user lets go.
        self._current_input_level = 0.0

        audio = self._process_audio_data()
        self.logger.info(
            "Audio buffer preparation finished in %.2f s (samples=%d)",
            time.monotonic() - started, 0 if audio is None else len(audio),
        )
        return audio

    def current_input_level(self) -> float:
        """Most-recent RMS amplitude (0..1) of the live audio stream.

        Updated from the recording callback while ``is_recording`` is
        True; reset to 0 on stop. Polled by the UI's VU meter at a
        few dozen Hz.
        """
        return self._current_input_level

    def _process_audio_data(self) -> Optional[np.ndarray]:
        if len(self.audio_data) == 0:
            # A press that ended before the stream's first block arrived has
            # no frames either, and that is the press being short, not the
            # microphone being dead.
            started = self.recording_start_time
            held = (time.time() - started) if started else None
            if held is not None and held < self.NO_FRAMES_GRACE_S:
                self.empty_reason = "too_short"
                self.logger.warning(
                    "The recording was too short: it ended before the "
                    "microphone delivered any audio.",
                    extra={'user_message': True},
                )
            else:
                self.empty_reason = "no_frames"
                self.logger.warning(
                    "No audio from the microphone. Restart the app if this keeps happening.",
                    extra={'user_message': True},
                )
            return None

        # Convert list of audio chunks into a single numpy array (still at
        # the device's native sample rate at this point).
        audio_array = np.concatenate(self.audio_data, axis=0)

        # Whisper expects 16 kHz mono float32. Resample if the device gave
        # us anything else (typically 44.1 / 48 kHz on WASAPI).
        capture_sr = self._capture_sample_rate or self.WHISPER_SAMPLE_RATE
        if capture_sr != self.WHISPER_SAMPLE_RATE:
            audio_array = self._resample_to(audio_array, capture_sr, self.WHISPER_SAMPLE_RATE)

        # If the recorder ran in stereo, average to mono so Whisper sees a
        # 1-D buffer.
        if audio_array.ndim == 2 and audio_array.shape[1] > 1:
            audio_array = audio_array.mean(axis=1)
        elif audio_array.ndim == 2:
            audio_array = audio_array[:, 0]

        duration = self.get_audio_duration(audio_array)
        # Peak / RMS amplitude is the cheapest "did the mic actually pick
        # anything up?" check. Whisper returning empty on a quiet recording
        # is impossible to debug without this.
        try:
            peak = float(np.max(np.abs(audio_array)))
            rms = float(np.sqrt(np.mean(audio_array.astype(np.float32) ** 2)))
        except Exception:
            peak = 0.0
            rms = 0.0
        self.logger.info(
            "Recorded %.2f seconds of audio (peak=%.3f, rms=%.4f, captured @ %d Hz)",
            duration, peak, rms, capture_sr,
        )
        if peak < 0.01:
            self.logger.warning(
                "Audio looks silent (peak<0.01). Wrong microphone selected, "
                "%s, or input gain too low?", _where_sound_is_muted(),
                extra={'user_message': True},
            )
        return audio_array

    @staticmethod
    def _resample_to(audio: np.ndarray, source_sr: int, target_sr: int) -> np.ndarray:
        """Resample a numpy audio buffer to ``target_sr``.

        Uses ``scipy.signal.resample_poly`` (polyphase FIR) instead of
        linear interpolation for two reasons:

        1. **Memory** — linear interpolation required two float64 arrays of
           ``len(audio)`` samples as coordinate vectors (x_old, x_new),
           inflating peak RAM by ~4× the audio size during downsampling.
           ``resample_poly`` uses a fixed-size FIR filter kernel regardless
           of audio length — O(filter_len), not O(N).

        2. **Quality** — polyphase filtering applies a proper anti-aliasing
           low-pass before decimation; linear interpolation has no such
           filter, allowing content above the target Nyquist to alias back
           into the speech band.

        For multi-channel (stereo) input the resampling is done along the
        time axis (axis=0), preserving channel count.  The caller
        (``_process_audio_data``) is responsible for the subsequent
        stereo-to-mono mix-down.
        """
        if source_sr == target_sr or len(audio) == 0:
            return audio.astype(np.float32)

        from math import gcd

        try:
            from scipy.signal import resample_poly as _resample_poly
        except ImportError:
            # scipy is a listed dependency (pyproject.toml) but guard here
            # in case the environment is missing it.  Fall back to linear
            # interpolation — lower quality (aliasing possible) but
            # functional.  Install scipy to restore polyphase quality:
            #   pip install scipy
            import logging
            logging.getLogger(__name__).warning(
                "scipy not available — falling back to linear resampler. "
                "Run 'pip install scipy' for better audio quality."
            )
            length_in = audio.shape[0]
            length_out = int(length_in * target_sr / source_sr)
            x_old = np.linspace(0.0, 1.0, length_in)
            x_new = np.linspace(0.0, 1.0, length_out)
            if audio.ndim == 2:
                return np.stack(
                    [np.interp(x_new, x_old, audio[:, ch]) for ch in range(audio.shape[1])],
                    axis=1,
                ).astype(np.float32)
            return np.interp(x_new, x_old, audio).astype(np.float32)

        g = gcd(int(source_sr), int(target_sr))
        up = int(target_sr) // g    # e.g. 48 kHz → 16 kHz: up=1, down=3
        down = int(source_sr) // g

        axis = 0 if audio.ndim == 2 else -1
        return _resample_poly(audio, up, down, axis=axis).astype(np.float32)

    def cancel_recording(self):
        if not self.is_recording:
            return

        self.is_recording = False
        self._wait_for_thread_finish()

        self.audio_data = []
        self.recording_start_time = None

    def _record_audio(self):
        try:
            def audio_callback(audio_data, frames, time, status):
                if self.is_recording:
                    self.audio_data.append(audio_data.copy())

                # Compute RMS amplitude of this chunk for the live VU
                # meter. Cheap (numpy on a few hundred samples) and
                # decoupled from the UI thread that polls the value.
                try:
                    flat = np.asarray(audio_data).flatten()
                    if flat.size:
                        # Peak rather than RMS — see comment in
                        # ``test_input_level`` for the rationale.
                        # Same scale as the post-recording UI
                        # treatments (color thresholds calibrated
                        # for peak amplitude).
                        self._current_input_level = float(
                            np.abs(flat).max()
                        )
                except Exception:
                    pass

                if status:
                    self.logger.debug("Audio callback status: %s", status)

            # Many devices (especially WASAPI) only support their native rate
            # — opening at 16 kHz raises ``Invalid sample rate`` (PaErrorCode
            # -9997). Probe the device's default rate, capture there, and
            # resample to Whisper's 16 kHz in ``_process_audio_data``.
            try:
                if self.device is not None:
                    info = sd.query_devices(self.device)
                else:
                    info = sd.query_devices(kind="input")
                native_sr = int(info.get("default_samplerate", self.WHISPER_SAMPLE_RATE))
            except Exception:
                native_sr = self.WHISPER_SAMPLE_RATE
            if native_sr <= 0:
                native_sr = self.WHISPER_SAMPLE_RATE
            self._capture_sample_rate = native_sr
            self.logger.info(
                "Capturing at %d Hz (target: %d Hz)",
                native_sr, self.WHISPER_SAMPLE_RATE,
            )

            stream = sd.InputStream(samplerate=native_sr,
                                    channels=self.channels,
                                    callback=audio_callback,
                                    dtype=self.STREAM_DTYPE,
                                    device=self.device)
            self._stream = stream
            try:
                with stream:
                    self._stream_event.set()

                    while self.is_recording:
                        if self._check_max_duration_exceeded():
                            break

                        sd.sleep(self.RECORDING_SLEEP_INTERVAL)
            finally:
                # A stream that was aborted and replaced must not be cleared
                # by the thread that owned it.
                if self._stream is stream:
                    self._stream = None

        except Exception as e:
            self.logger.error("Error during audio recording: %s", e)
            self.last_error = str(e)
            was_recording = self.is_recording
            self.is_recording = False
            self._stream_event.set()
            if self._start_returned and (was_recording or self.audio_data):
                self._report_stream_failure()

    def _report_stream_failure(self) -> None:
        """The stream broke after start: hand over what was captured, or say so."""
        audio = self._process_audio_data() if self.audio_data else None
        try:
            if audio is not None and self.on_max_duration_reached:
                # Same hand-off as reaching the time limit: the words
                # captured so far still get transcribed.
                self.logger.warning(
                    "The microphone stopped; transcribing what was recorded.",
                    extra={'user_message': True},
                )
                self.on_max_duration_reached(audio)
            elif self.on_recording_failed:
                self.on_recording_failed(self.last_error or "The microphone stopped")
        except Exception:
            self.logger.exception("Reporting the recording failure raised")

    def _check_max_duration_exceeded(self) -> bool:
        if self.max_duration > 0 and self.recording_start_time:
            elapsed_time = time.time() - self.recording_start_time
            if elapsed_time >= self.max_duration:
                self.logger.info("Maximum recording duration of %ss reached", self.max_duration)
                self.logger.info("Maximum recording duration of %ss reached - stopping recording", self.max_duration, extra={'user_message': True})

                self.is_recording = False
                audio_data = self._process_audio_data()

                if self.on_max_duration_reached:
                    self.on_max_duration_reached(audio_data)
                return True
        return False

    def get_recording_status(self) -> bool:
        return self.is_recording

    def has_stuck_recording_thread(self) -> bool:
        """True when a recording thread is still alive after its stop.

        The thread owns the input stream, so a thread that outlives its
        stop holds the microphone and keeps the GIL. It is the state the
        app must not exit through: ``Pa_Terminate`` deadlocks on the
        same lock, which leaves a windowless process holding the
        single-instance lock, and every later launch is refused.
        """
        thread = self.recording_thread
        return thread is not None and thread.is_alive()

    def get_audio_duration(self, audio_data: np.ndarray) -> float:
        if audio_data is None or len(audio_data) == 0:
            return 0.0
        return len(audio_data) / self.sample_rate
