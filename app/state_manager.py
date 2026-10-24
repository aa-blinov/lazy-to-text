import logging
import time
import threading
from typing import Any, Optional, TYPE_CHECKING

from app.audio_recorder import AudioRecorder
from app.backends.base import TranscriptionError, user_reason
from app.clipboard_manager import ClipboardManager
from app.config_manager import ConfigManager
from app.audio_feedback import AudioFeedback
from app.llm import LLMError, LLMSettings, complete as llm_complete
from app.llm.profiles import resolve_profile, with_profile
from app.utils import OptionalComponent
from app.history_manager import HistoryManager

if TYPE_CHECKING:
    from app.backends.base import TranscriptionBackend


# One line per delivery outcome, for the log the user reads afterwards.
# Keyed by the vocabulary ``ClipboardManager.deliver_transcription``
# returns, so a new outcome shows up as a missing entry here rather
# than as a sentence about the wrong one.
_DELIVERY_LOG_TEXT = {
    "pasted": "sent — paste keystroke posted to the focused app",
    "copied": "copied — the text is in the clipboard, paste it yourself",
    "failed": "failed — the text never reached the clipboard",
}


#: How many recordings that failed to transcribe are kept on disk.
_KEPT_RECORDINGS = 3

#: Shorter than this is a double tap of the hotkey, not a dictation.
_MIN_RECORDING_S = 0.3

# A recording this quiet is the microphone's own floor, not a voice. The
# recogniser still answers it with a word (a small model turns silence into
# "а"), and a dictation app that pastes that into a document is worse than
# one that says nothing was heard. The peak gate is conservative on purpose:
# quiet speech peaks well above it.
_SILENT_PEAK = 0.01
# Below this level of average energy a one-word answer is the room, not a
# person: short fragments are dropped, anything longer is kept.
_QUIET_RMS = 0.01
_STRAY_MAX_CHARS_QUIET = 3
# A very short recording that comes back as a single character is a tap.
_STRAY_SHORT_S = 1.0


def _audio_levels(audio: Any) -> "tuple[Optional[float], Optional[float]]":
    """``(peak, rms)`` of a float recording, or ``(None, None)`` when it
    cannot be measured (nothing then gates on it)."""
    try:
        import numpy as np

        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return None, None
        return (float(np.max(np.abs(samples))),
                float(np.sqrt(np.mean(samples ** 2))))
    except Exception:
        return None, None


def _is_stray_fragment(text: str, duration: float, rms: Optional[float]) -> bool:
    """A one-token answer that is the noise floor, not something said."""
    words = text.split()
    if len(words) != 1:
        return False
    word = words[0]
    if len(word) <= 1 and duration < _STRAY_SHORT_S:
        return True
    return rms is not None and rms < _QUIET_RMS and len(word) <= _STRAY_MAX_CHARS_QUIET


class StateManager:
    # Class-level default rather than only an ``__init__`` assignment,
    # because several suites build a half-real manager with
    # ``StateManager.__new__`` and set the attributes they need by hand.
    # Reading it on such an object would otherwise raise
    # ``AttributeError`` inside the dictation pipeline — which is
    # exactly the path whose failure this app is supposed to survive.
    _profile_override_id = ""
    delivery_reported_callback = None
    delivery_event_callback = None

    _model_change_seq = 0  # instance value set in __init__

    def __init__(self,
                 audio_recorder: AudioRecorder,
                 backend: "TranscriptionBackend",
                 clipboard_manager: ClipboardManager,
                 config_manager: ConfigManager,
                 system_tray: Optional[Any] = None,
                 audio_feedback: Optional[AudioFeedback] = None,
                 output_mute: Optional[Any] = None):

        self.audio_recorder = audio_recorder
        self.backend = backend
        self.clipboard_manager = clipboard_manager
        self.system_tray = OptionalComponent(system_tray)
        self.config_manager = config_manager
        self.audio_feedback = OptionalComponent(audio_feedback)
        # Mutes the system output while recording. Optional, because
        # the feature is macOS-only and the object is a no-op there.
        self.output_mute = OptionalComponent(output_mute)

        # The Transcribe screen's "for this one" profile choice. Empty
        # means the active profile runs, which is what it means on a
        # fresh install and after the user unticks the box.
        #
        # Read by the pipeline thread and written by the Qt thread, so it
        # is replaced wholesale rather than mutated — assigning an
        # immutable ``str`` is atomic under the GIL, and a dict or list
        # would not be.
        self._profile_override_id = ""

        # Initialize history manager
        from app.utils import get_project_logs_path
        import os
        history_config = self.config_manager.get_history_config()
        if history_config.get('enabled', True):
            try:
                history_file = os.path.join(get_project_logs_path(), "transcription_history.jsonl")
                max_entries = history_config.get('max_entries', 1000)
                self.history_manager = HistoryManager(max_entries=max_entries, history_file=history_file)
            except Exception as exc:
                # History is a convenience; a folder that cannot be made
                # must not take the recording stack with it.
                self.logger_early().warning(
                    "History is unavailable: %s", exc,
                    extra={'user_message': True},
                )
                self.history_manager = None
        else:
            self.history_manager = None

        # History update callback (to be set by UI)
        self.history_update_callback = None

        # Delivery report callback — ``(outcome, detail)``. The
        # transcription pipeline calls this on its worker thread once the
        # text has been handed to the clipboard, so the UI can say what
        # happened instead of the window simply going quiet. ``outcome``
        # is one of ``pasted`` / ``copied`` / ``failed``.
        self.delivery_reported_callback = None

        # A stream that breaks after "recording started" has no caller to
        # return an error to; the recorder reports it here.
        try:
            self.audio_recorder.on_recording_failed = self._on_recording_failed
        except Exception:  # pragma: no cover - a recorder that refuses attributes
            pass

        self.is_processing = False
        self.is_model_loading = False
        self.last_transcription = None
        self._pending_model_change = None  # Store pending model change request
        # Bumped by every model change and every cancel. A watcher belongs
        # to the change that started it; once the number moves it is
        # watching a load nobody asked for any more and must not report on
        # (or clear the loading flag of) the one that replaced it.
        self._model_change_seq = 0
        self._state_lock = threading.Lock()  # Thread safety for state operations

        self.logger = logging.getLogger(__name__)

    @staticmethod
    def logger_early() -> logging.Logger:
        return logging.getLogger(__name__)

    def handle_max_recording_duration_reached(self, audio_data):
        """Called when audio recorder reaches max duration with audio data."""
        self.logger.info("Max recording duration reached - starting transcription")
        # Acoustic feedback first, BEFORE the worker thread is given a
        # chance to run.  Mirrors stop_recording() so the user hears the
        # stop sound the moment max duration fires, regardless of how
        # busy the scheduler is.
        # The recording is over, so the output goes back first: the stop
        # hotkey path does the same, and this one used to leave it muted.
        self._restore_output()
        self.audio_feedback.play_stop_sound()
        # Mark busy before the thread starts to close the race window where the
        # hotkey listener could try to start a new recording immediately.
        with self._state_lock:
            self.is_processing = True
        try:
            threading.Thread(
                target=self._transcription_pipeline,
                args=(audio_data,),
                daemon=True,
                name="transcription-pipeline",
            ).start()
        except Exception:
            self.logger.exception("Failed to start transcription thread")
            with self._state_lock:
                self.is_processing = False

    def stop_recording(self, use_auto_enter: bool = False) -> bool:
        currently_recording = self.audio_recorder.get_recording_status()

        if currently_recording:
            # Restore the system output BEFORE the stop sound: the
            # recording is over, and the confirmation has to be audible.
            self._restore_output()
            # Play stop sound BEFORE closing the mic stream — closing
            # the SoundDevice stream blocks 50-200 ms on Windows, and
            # then the transcription pipeline runs on a worker thread
            # whose first scheduling slice can take another 10 ms+.
            # Stacking that latency on top of winsound's own first-call
            # delay is what made Ctrl+F3 feel sluggish.  Playing first
            # gives the user immediate acoustic confirmation that the
            # hotkey was caught.
            self.audio_feedback.play_stop_sound()
            # Set is_processing=True BEFORE the recorder is stopped.
            #
            # The recorder's stop blocks for 50-200 ms (the mic stream
            # close), and until it returns the state machine still
            # reports "recording" — the recorder says so. The moment it
            # returns, the state is "idle": the recording is over and the
            # pipeline has not started yet. The overlay reads that
            # state, hides itself, and the next state ("processing")
            # makes it appear again — re-anchored, and the fallback for
            # an unresolvable anchor is the *primary* screen. That is
            # the capsule jumping to the first screen while the
            # dictation is being processed.
            #
            # Marking the app busy first removes the dip: the state
            # goes recording → processing without passing through idle.
            # The flag is set before the pipeline exists, not only
            # before the thread that runs it — and the busy state is
            # what the hotkey listener and the overlay both read.
            with self._state_lock:
                self.is_processing = True
            audio_data = self.audio_recorder.stop_recording()
            try:
                threading.Thread(
                    target=self._transcription_pipeline,
                    args=(audio_data, use_auto_enter),
                    daemon=True,
                    name="transcription-pipeline",
                ).start()
            except Exception:
                self.logger.exception("Failed to start transcription thread")
                with self._state_lock:
                    self.is_processing = False
            return True
        else:
            return False

    def cancel_active_recording(self):
        # The recording is over, so the output goes back before the
        # cancellation sound plays.
        self._restore_output()
        self.audio_recorder.cancel_recording()
        self.audio_feedback.play_cancel_sound()
        self.system_tray.update_state("idle")

    def _mute_output_for_recording(self) -> None:
        """Mute the system output for the duration of a recording.

        Only when the user asked for it, and only where the platform
        can do it (macOS). A failure here must not stop the recording:
        the user wanted a quieter room, not a broken dictation.
        """
        try:
            audio_cfg = self.config_manager.get_audio_config()
        except Exception:  # pragma: no cover — defensive
            return
        if not audio_cfg.get("mute_output_on_record", False):
            return
        try:
            self.output_mute.mute()
        except Exception as exc:  # pragma: no cover — defensive
            self.logger.warning("Could not mute the system output: %s", exc)

    def _restore_output(self) -> None:
        """Put the system output back. Safe to call at any time."""
        try:
            self.output_mute.restore()
        except Exception as exc:  # pragma: no cover — defensive
            self.logger.warning("Could not restore the system output: %s", exc)

    def cancel_recording_hotkey_pressed(self) -> bool:
        current_state = self.get_current_state()

        if current_state == "recording":
            self.logger.info("Recording cancelled!", extra={'user_message': True})
            self.cancel_active_recording()
            return True
        else:
            return False

    def toggle_recording(self):
        was_recording = self.stop_recording(use_auto_enter=False)

        if not was_recording:
            current_state = self.get_current_state()
            can_start = self.can_start_recording()
            self.logger.debug(
                "toggle_recording: current_state=%s, can_start=%s",
                current_state, can_start,
            )

            if can_start:
                self._start_recording()
            else:
                # Acoustic feedback that the hotkey was actually caught even
                # when recording cannot start (backend not ready, busy, etc.).
                # Without this the user has no signal that the keypress arrived.
                self.audio_feedback.play_start_sound()
                if self.is_processing:
                    self.logger.info("Still processing previous recording...", extra={'user_message': True})
                elif self.is_model_loading:
                    self.logger.info("Still loading model...", extra={'user_message': True})
                elif current_state == "idle":
                    # Idle but unable to record: no model is loaded. This is
                    # not "wait" when nothing is loading, so it is reported
                    # as an outcome with the way out, not one log line.
                    self._fail_dictation(
                        "Cannot record",
                        "no speech model is loaded yet - pick or download "
                        "one in Models",
                    )
                else:
                    self.logger.info(
                        "Cannot record while %s...", current_state,
                        extra={'user_message': True},
                    )

    def _start_recording(self):
        # Play the start sound BEFORE opening the audio recorder — opening
        # the mic stream takes ~100 ms on Windows and stacking that delay on
        # top of winsound's first-call latency is what made the first
        # recording after launch silent. Playing first means the user always
        # gets immediate acoustic confirmation, even if the recorder fails.
        self.audio_feedback.play_start_sound()

        # Mute the system output after that sound and before the mic opens:
        # the confirmation has to be audible, and anything that starts
        # playing from here on must not reach the microphone.
        self._mute_output_for_recording()

        self.logger.debug("_start_recording: attempting to start audio recorder")
        try:
            success = self.audio_recorder.start_recording()
        except Exception as exc:
            # Whatever the recorder raised, the output has to come back
            # and the user has to be told: this is the path that left the
            # machine muted with no outcome at all.
            self.logger.error("Audio recorder raised on start: %s", exc, exc_info=True)
            self.audio_recorder.last_error = str(exc)
            success = False

        if success:
            self.logger.debug("_start_recording: audio recorder started successfully")
            self.config_manager.print_stop_instructions_based_on_config()
            self.system_tray.update_state("recording")
        else:
            self.logger.debug("_start_recording: audio recorder failed to start")
            # Nothing is being recorded, so the output stays where the
            # user left it.
            self._restore_output()
            reason = getattr(self.audio_recorder, "last_error", None)
            self._fail_dictation(
                "Could not start recording",
                reason if isinstance(reason, str) and reason else "the microphone did not open",
            )

    def _on_recording_failed(self, reason: str) -> None:
        """The input stream broke mid-recording and nothing was captured."""
        self._restore_output()
        self.system_tray.update_state("idle")
        self._fail_dictation("The recording stopped", reason)

    def _fail_dictation(self, what: str, reason: str, kept: str = "") -> None:
        """Say that a dictation did not happen, in the log and as an outcome.

        Every way a dictation can end has an outcome. A failure used to
        end in silence - the state returned to idle and the only trace
        was a log line - so the user could not tell a lost recording from
        one that was never made. ``detail`` is a sentence a person can
        read; the delivery callback is the channel both interfaces already
        show, so the failure reaches the capsule.
        """
        detail = f"{what}: {reason}." if reason else f"{what}."
        if kept:
            detail += f" The recording was kept at {kept}."
        self.logger.error(detail, extra={'user_message': True})
        self._report_delivery("failed", "", detail=detail)

    def _keep_recording(self, audio_data) -> str:
        """Save audio that could not be transcribed, so it is not lost.

        Written next to the logs, as 16 kHz mono WAV, the last
        ``_KEPT_RECORDINGS`` only. Returns the path, or ``""`` when it
        could not be written (never raises: this runs on a failure path).
        The audio never leaves the machine and is overwritten by later
        failures, which keeps the disk use bounded.
        """
        try:
            import os
            import wave

            import numpy as np
            from app.utils import get_project_logs_path

            from app.utils import UNPROCESSED_RECORDINGS_DIRNAME, restrict_to_owner

            folder = os.path.join(
                get_project_logs_path(), UNPROCESSED_RECORDINGS_DIRNAME
            )
            os.makedirs(folder, mode=0o700, exist_ok=True)
            restrict_to_owner(folder, directory=True)
            samples = np.asarray(audio_data, dtype=np.float32).reshape(-1)
            pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
            stamp = time.strftime("recording-%Y%m%d-%H%M%S")
            path = os.path.join(
                folder, f"{stamp}-{int(time.time() * 1000) % 1000:03d}.wav"
            )
            # Created owner-only from the first byte: this is the user's voice.
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            for attempt in range(100):
                try:
                    fd = os.open(path, flags, 0o600)
                    break
                except FileExistsError:
                    # Two failures inside one millisecond: keep both.
                    path = path[: -len(".wav")].rsplit("~", 1)[0] + f"~{attempt + 1}.wav"
            else:  # pragma: no cover - defensive
                raise FileExistsError(path)
            with os.fdopen(fd, "wb") as handle, wave.open(handle, "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(16_000)
                out.writeframes(pcm.tobytes())
            kept = sorted(
                name for name in os.listdir(folder) if name.endswith(".wav")
            )
            for stale in kept[:-_KEPT_RECORDINGS]:
                try:
                    os.remove(os.path.join(folder, stale))
                except OSError:
                    pass
            return path
        except Exception as exc:
            self.logger.warning("Could not keep the unprocessed recording: %s", exc)
            return ""

    def profile_override_id(self) -> str:
        """The profile the Transcribe screen pinned for this dictation.

        Empty means none — the active profile is used.
        """
        return self._profile_override_id

    def set_profile_override(self, profile_id: str = "") -> None:
        """Pin one profile for the next dictation, or unpin with ``""``.

        Deliberately not written to ``config.yaml``. An override that
        persisted to the active profile would silently change what every
        later dictation does, which is the opposite of what "for this one"
        says.
        """
        self._profile_override_id = (profile_id or "").strip()

    def _postprocess_with_llm(self, text: str, profile_override: str = "") -> str:
        """Run dictated text through the optional LLM step.

        Returns the text to deliver. **On any failure it returns the
        original.**

        That is the whole contract, and it is a deliberate choice.
        The alternative — refusing to deliver when post-processing
        fails — means a dropped Wi-Fi packet or an Ollama that is not
        running swallows the words somebody just spoke into a
        microphone. In a dictation tool the contract is "your words
        reach the window", and no optional feature gets to break it.

        The cost of that choice is that the user may get raw text when
        they asked for it tidied, silently. So every fallback logs at
        warning level *and* says it in the Logs view, rather than
        quietly delivering text that did not go through the step the
        user turned on. Same reasoning as ``TranscriptionError``: a
        failure must be nameable, not flattened into a result that
        looks like success.

        *profile_override* is the Transcribe screen's "for this one"
        choice. It is resolved per dictation rather than written to the
        config, so using it never quietly changes what the next one
        does — the whole point of an override is that it leaves the
        default alone.

        No user words are logged here — not the input and not the
        output. The step may be a cloud endpoint, and this line would
        otherwise be the one place the app writes the dictation to a
        file it does not clear.
        """
        try:
            section = self.config_manager.get_section("llm")
            profile = resolve_profile(section, profile_override)
            settings = LLMSettings.from_config(
                {
                    **with_profile(section, profile),
                    "system_prompt": profile.prompt(),
                }
            )
        except Exception as exc:
            self.logger.warning(
                "Post-processing is skipped: its settings could not be "
                "read (%s) - delivering the raw transcription.",
                type(exc).__name__,
                extra={'user_message': True},
            )
            return text
        if not settings.configured:
            if settings.enabled and settings.model.strip() and settings.problem:
                # Switched on and named, but not usable: say so, in words,
                # rather than delivering raw text as if nothing was asked.
                self.logger.warning(
                    "Post-processing is skipped: %s. Delivering the raw "
                    "transcription. Fix the preset, or turn the step off.",
                    settings.problem,
                    extra={'user_message': True},
                )
            return text

        started = time.monotonic()
        try:
            result = llm_complete(text, settings)
        except Exception as exc:
            # Any exception, not only ``LLMError``: the step is optional
            # and the dictation is not, so nothing it raises may leave
            # this method. Only the type is logged for a foreign
            # exception - its message may carry a header value.
            detail = str(exc) if isinstance(exc, LLMError) else type(exc).__name__
            self.logger.warning(
                "Post-processing failed (%s) - delivering the raw "
                "transcription instead. Check the post-processing preset, "
                "or turn the step off.", detail,
                extra={'user_message': True},
            )
            return text

        elapsed = time.monotonic() - started
        self.logger.info(
            "Post-processed by profile %s (%s/%s) in %.1fs: "
            "%d characters in, %d out.",
            profile.name, settings.provider, settings.model,
            elapsed, len(text), len(result),
            extra={'user_message': True},
        )
        return result

    def _transcription_pipeline(self, audio_data, use_auto_enter: bool = False):
        outcome_reported = False
        try:
            self.logger.debug("[Pipeline] Enter _transcription_pipeline (auto_enter=%s)" % use_auto_enter)
            # Prevent multiple threads from starting simultaneous transcription
            with self._state_lock:
                self.is_processing = True
                self.logger.debug(
                    "[Pipeline] is_processing set True; model_loading=%s",
                    self.is_model_loading,
                )

            # Stop sound is played by the caller (stop_recording /
            # handle_max_recording_duration_reached) BEFORE this thread
            # is even spawned, so there's no acoustic feedback to do
            # here.  See the comment in stop_recording() for why.

            if audio_data is None:
                self.logger.debug("[Pipeline] audio_data is None -> early return")
                self._fail_dictation(
                    "Nothing was recorded", "no audio came from the microphone"
                )
                return

            duration = self.audio_recorder.get_audio_duration(audio_data)
            if duration < _MIN_RECORDING_S:
                # A double tap of the hotkey, not speech. The model never
                # sees it: the answer is the length, not whatever a
                # recogniser would do with a few milliseconds.
                self.logger.warning(
                    "The recording was too short to transcribe (under %.1f "
                    "s) - nothing was pasted.", _MIN_RECORDING_S,
                    extra={'user_message': True},
                )
                self._report_delivery(
                    "failed", "",
                    detail="The recording was too short to transcribe. "
                           "Speak a little longer before you stop.",
                    kind="too_short",
                )
                return

            peak, rms = _audio_levels(audio_data)
            if peak is not None and peak < _SILENT_PEAK:
                self.logger.info(
                    "No speech detected - the recording is silent. Check "
                    "that the right microphone is selected and not muted.",
                    extra={'user_message': True},
                )
                return

            self.logger.info(
                "Recorded %.1f seconds! Transcribing...", duration,
                extra={'user_message': True},
            )
            self.logger.debug(
                "[Pipeline] Recorded duration=%.3fs; starting transcription",
                duration,
            )

            try:
                transcribed_text = self.backend.transcribe(audio_data)
            except Exception as exc:
                # Inference ran and failed (or the worker did). Saying
                # "no speech detected" here sent users hunting for a
                # microphone problem they did not have - the recording was
                # fine and the model was not. Name the failure, keep the
                # audio, and report an outcome.
                self.logger.error(
                    "Transcription failed: %s", exc, exc_info=True,
                )
                kept = self._keep_recording(audio_data)
                self._fail_dictation(
                    "Could not transcribe the recording (the speech model "
                    "failed, this was not silence)",
                    user_reason(exc),
                    kept,
                )
                return
            if transcribed_text and _is_stray_fragment(
                transcribed_text, duration, rms
            ):
                self.logger.info(
                    "Dropped a stray one-word result from a very short or "
                    "near-silent recording.",
                )
                transcribed_text = ""
            text_len = 0 if not transcribed_text else len(transcribed_text)
            self.logger.info(
                "Transcription returned %d characters", text_len,
                extra={'user_message': True},
            )

            if not transcribed_text:
                self.logger.info(
                    "No speech detected (empty transcription) — nothing to paste.",
                    extra={'user_message': True},
                )
                return

            preview = transcribed_text if len(transcribed_text) <= 80 else transcribed_text[:77] + "..."
            # ``sensitive`` keeps the preview in the Logs view and out of
            # app.log — see ``_NoSensitiveToFile`` in ``app/gui/app.py``.
            # This is the only place the app writes the user's own words
            # to a log, and a log file is not the clearable store the
            # history file is.
            self.logger.info(
                "Transcribed: %s", preview,
                extra={'user_message': True, 'sensitive': True},
            )

            self.system_tray.update_state("processing")

            # The optional LLM step, between the recogniser and the
            # clipboard. Placed after the tray says "processing" so the
            # wait is visible: on a cloud endpoint this is seconds, not
            # the sub-second the model itself takes. Falls back to the
            # raw text on any failure — see ``_postprocess_with_llm``.
            transcribed_text = self._postprocess_with_llm(
                transcribed_text, self._profile_override_id
            )

            # Append a trailing non-breaking space so consecutive
            # transcriptions paste in without sticking together
            # ("первая фразавторая фраза").  A regular space is trimmed
            # by some inputs (Chrome URL bar, search boxes, …) so we
            # use \u00A0 which looks identical but survives.
            # The history entry below stores the raw text without it.
            outcome = self.clipboard_manager.deliver_transcription(
                transcribed_text + "\u00A0", use_auto_enter
            )
            # Three outcomes, not a bool. A failed copy leaves the text
            # nowhere; a failed keystroke leaves it on the clipboard
            # waiting for the user. Reading either as "not delivered" hid
            # the dictation from history when the paste keystroke did
            # not go out, even though the text was sitting in the
            # clipboard ready to paste.
            delivered = outcome != "failed"
            self.logger.info(
                # "sent", not "pasted": nothing in the platform API can
                # confirm the target app pasted, and this is the record a
                # user reads afterwards to work out what happened.
                "Delivery %s",
                _DELIVERY_LOG_TEXT.get(outcome, outcome),
                extra={'user_message': True},
            )
            outcome_reported = True
            self._report_delivery(outcome, transcribed_text)

            if delivered:
                self.last_transcription = transcribed_text
                self.logger.debug("[Pipeline] last_transcription updated")

                # Add to history
                if self.history_manager:
                    try:
                        self.history_manager.add_entry(
                            text=transcribed_text,
                            duration=duration,
                            model=self.backend.current_model(),
                            language=self.backend.current_language() or "auto"
                        )
                        self.logger.debug("[Pipeline] Added entry to history")

                        # Notify UI to update history display
                        if self.history_update_callback:
                            self.history_update_callback()

                    except Exception as e:
                        self.logger.warning("Failed to add entry to history: %s", e)

        except Exception as e:
            self.logger.error("Error in processing workflow: %s", e, exc_info=True)
            if not outcome_reported:
                # The words never reached the clipboard and nothing said
                # so. Keep the audio and report the failure as an outcome.
                kept = (
                    self._keep_recording(audio_data)
                    if audio_data is not None else ""
                )
                self._fail_dictation(
                    "Error processing recording", user_reason(e), kept
                )
            else:
                self.logger.error(
                    "Error processing recording: %s", user_reason(e),
                    extra={'user_message': True},
                )

        finally:
            self.logger.debug("[Pipeline] Enter finally block")

            # Release the audio buffer. CPython's reference counting frees
            # the numpy array immediately when the refcount hits zero —
            # gc.collect() is only needed for cyclic references, which a
            # plain float32 buffer cannot have, so the explicit sweep was
            # just wasting 100-300 ms walking the entire object graph
            # (including loaded model weights) after every transcription.
            if audio_data is not None:
                del audio_data

            with self._state_lock:
                self.is_processing = False
                self.logger.debug(
                    "[Pipeline] is_processing set False; model_loading=%s",
                    self.is_model_loading,
                )
                pending = self._pending_model_change

            # Execute pending model change outside of lock to avoid deadlock.
            # Backward compat: ``pending`` is either ``(name, compute_type)``
            # tuple, a bare model name string (older callers), or None.
            if pending:
                if isinstance(pending, tuple):
                    pending_model, pending_compute = pending
                else:
                    pending_model, pending_compute = pending, None
                self.logger.info("Executing pending model change to: %s", pending_model)
                self.logger.info(
                    "Processing complete, now switching to %s model...",
                    pending_model, extra={'user_message': True},
                )
                self._execute_model_change(pending_model, pending_compute)
                self._pending_model_change = None
            else:
                self.system_tray.update_state("idle")
                self.logger.debug("[Pipeline] System tray set to idle; pipeline end")

    def _report_delivery(
        self, outcome: str, text: str, detail: Optional[str] = None,
        kind: str = "",
    ) -> None:
        """Tell the UI what happened — called on the transcription thread.

        The user is looking at their document, not at this app, so "did
        it go in?" has to be answered where they can see it without
        switching windows. The overlay owns that answer; this is the
        hand-off.

        ``detail`` is the paste shortcut, and only when the text is on the
        clipboard for the user to paste themselves. ``text`` is what was
        delivered, so the same popup can show it.

        A UI callback must not be able to take the pipeline down with it,
        so this catches its own exceptions. Letting one escape used to
        land in the pipeline's own ``except``, which then reported a
        delivered dictation as a processing error.
        """
        callback = self.delivery_reported_callback
        event_callback = self.delivery_event_callback
        if callback is None and event_callback is None:
            return
        if detail is None:
            detail = (
                self.clipboard_manager.paste_combo() if outcome == "copied" else ""
            )
        try:
            if event_callback is not None:
                # The runtime's variant: the same three values plus ``kind``
                # ("too_short"), so a screen can tell a double tap from a
                # failure. The Qt callback keeps its three-value signal.
                event_callback(outcome, detail, text, kind)
            else:
                callback(outcome, detail, text)
        except Exception as exc:
            self.logger.warning("Delivery report callback raised: %s", exc)

    def shutdown(self):
        self.logger.info("Lazy to text is shutting down... goodbye!", extra={'user_message': True})

        # A recording may be running at this point, and the app can be
        # quit mid-dictation. The output has to go back before the
        # process goes away, or the machine stays muted.
        self._restore_output()

        if self.audio_recorder.get_recording_status():
            self.audio_recorder.stop_recording()

        self.system_tray.stop()

    def set_model_loading(self, loading: bool):
        with self._state_lock:
            old_state = self.is_model_loading
            self.is_model_loading = loading

            if old_state != loading:
                if loading:
                    self.system_tray.update_state("processing")
                else:
                    self.system_tray.update_state("idle")
                    # Re-warm the Windows audio device so the first
                    # recording-start click after model load is heard.
                    # The OS releases idle devices after a few seconds;
                    # by the time any model finishes loading the device
                    # opened at startup is almost certainly closed again.
                    self.audio_feedback.prewarm()

    def can_start_recording(self) -> bool:
        with self._state_lock:
            basic_check = not (
                self.is_processing
                or self.is_model_loading
                or self.audio_recorder.get_recording_status()
            )
            if not basic_check:
                self.logger.debug(
                    "can_start_recording: basic_check failed "
                    "(processing=%s, model_loading=%s, recording=%s)",
                    self.is_processing,
                    self.is_model_loading,
                    self.audio_recorder.get_recording_status(),
                )
                return False

        # Outside the lock: backend.health_check has its own locking and we
        # don't want to block status polls behind state-machine work.
        try:
            ready = self.backend.health_check()
        except Exception as exc:
            self.logger.debug("backend.health_check raised: %s", exc)
            return False

        self.logger.debug("can_start_recording: backend ready=%s", ready)
        return ready

    def get_current_state(self) -> str:
        with self._state_lock:
            if self.is_model_loading:
                return "model_loading"
            if self.is_processing:
                return "processing"
            if self.audio_recorder.get_recording_status():
                return "recording"
        # Idle path: surface a backend-driven model load too (initial startup
        # download, or any reload triggered outside ``_execute_model_change``).
        try:
            if self.backend.status() == "loading":
                return "model_loading"
        except Exception:
            pass
        return "idle"

    def cancel_model_change(self) -> bool:
        """Abandon an in-flight model load.

        The user clicked Cancel on the topbar pill — almost always
        because they mis-picked a heavy model card (or NeMo's cold
        import deadlocked for half an hour). We tell the backend to
        drop its in-flight result, clear ``is_model_loading`` so the
        UI flips back to idle, and let the watcher thread exit on
        its next poll when it sees ``backend.status() == 'stopped'``.

        Returns ``True`` iff a load was actually cancelled, ``False``
        if there was nothing to cancel (cancel button can race with
        a load that already finished or failed).
        """
        with self._state_lock:
            if not self.is_model_loading:
                return False

        self.logger.info(
            "Cancelling model load…", extra={'user_message': True}
        )
        target = getattr(self.backend, "cancel_load", None)
        if target is not None:
            try:
                target()
            except Exception as exc:  # pragma: no cover — defensive
                self.logger.warning("backend.cancel_load raised: %s", exc)
        with self._state_lock:
            self._model_change_seq += 1
        self.set_model_loading(False)
        return True

    def request_model_change(
        self,
        new_model_size: str,
        compute_type: Optional[str] = None,
    ) -> bool:
        current_state = self.get_current_state()

        same_model = new_model_size == self.backend.current_model()
        same_compute = compute_type is None
        if same_model and same_compute:
            # Selecting the model that is already "current" is a no-op only
            # when it is actually loaded. A model that is on disk and named
            # in the config but never loaded (its folder was missing at
            # start) used to be unrecoverable from here: every pick said
            # "already selected".
            try:
                backend_status = self.backend.status()
            except Exception:
                backend_status = None
            if backend_status in ("stopped", "error") and current_state == "idle":
                self.logger.info(
                    "%s is selected but not loaded - loading it now.",
                    new_model_size, extra={'user_message': True},
                )
                self._execute_model_change(new_model_size, compute_type)
            return True

        if current_state == "model_loading":
            self.logger.info("Model already loading, please wait...", extra={'user_message': True})
            return False

        if current_state == "recording":
            self.logger.info(
                "Cancelling recording to switch to %s model...", new_model_size,
                extra={'user_message': True},
            )
            self.cancel_active_recording()
            self._execute_model_change(new_model_size, compute_type)
            return True

        if current_state == "processing":
            self.logger.info(
                "Queueing model change to %s until transcription completes...",
                new_model_size, extra={'user_message': True},
            )
            self._pending_model_change = (new_model_size, compute_type)
            return True

        if current_state == "idle":
            self._execute_model_change(new_model_size, compute_type)
            return True

        self.logger.warning("Unexpected state for model change: %s", current_state)
        return False

    def _execute_model_change(
        self,
        new_model_size: str,
        compute_type: Optional[str] = None,
    ):
        with self._state_lock:
            self._model_change_seq += 1
            seq = self._model_change_seq
        self.set_model_loading(True)
        self.logger.info(
            f"Switching to {new_model_size} model...", extra={'user_message': True}
        )

        # Run ``backend.change_model`` AND the status-poll watcher on the
        # same daemon thread.  Why both off the caller (= Qt main thread):
        # ``OnnxAsrBackend.change_model`` synchronously drops the old
        # ``self._model`` reference, which fires the ONNX session
        # destructor and the CUDA-memory release on the calling thread.
        # On a real model that destructor stalls the caller for
        # 300-800 ms — long enough for Windows to mark the window
        # "(Not responding)" and refuse to drag it.  Pushing the whole
        # change_model + watcher pair onto a worker thread means the
        # main thread returns immediately after just flipping the
        # ``is_model_loading`` flag, which the Qt UI uses to repaint
        # the Loading pill.
        threading.Thread(
            target=self._do_model_change_and_watch,
            args=(new_model_size, compute_type, seq),
            daemon=True,
            name=f"model-change-{new_model_size}",
        ).start()

    def _do_model_change_and_watch(
        self,
        new_model_size: str,
        compute_type: Optional[str] = None,
        seq: Optional[int] = None,
    ) -> None:
        """Worker-thread body: actually run ``backend.change_model`` and
        then poll ``backend.status()`` until the new model settles on
        ``ready`` / ``error``.  Spawned by ``_execute_model_change`` so
        the Qt main thread doesn't block on the synchronous ONNX
        session destructor inside ``change_model``."""
        try:
            self.backend.change_model(new_model_size, compute_type=compute_type)
        except Exception as e:
            self.logger.error("Failed to initiate model change: %s", e)
            self.logger.error(
                f"Failed to change model: {e}", extra={'user_message': True}
            )
            if seq is None or seq == self._model_change_seq:
                self.set_model_loading(False)
            return
        # Backend.change_model returns once the new inner backend is built
        # and its load() call has spawned its own thread.  Poll status()
        # to learn when the load finishes (or errors out) and clear the
        # ``is_model_loading`` flag accordingly.
        self._watch_model_change(new_model_size, seq=seq)

    def _watch_model_change(
        self, model_size: str, timeout: float = 1800.0,
        seq: Optional[int] = None,
    ) -> None:
        """Poll the backend until it settles on ``ready`` / ``error``.

        Default timeout is 30 minutes — generous on purpose. NeMo's
        first cold-load on a fresh install can run 4-6 minutes
        (PyTorch Lightning + hydra + lhotse imports, then ~1.2 GB
        of safetensors over the wire). The previous 2-minute cap
        fired during normal operation and made the model pill go
        stale even though the download was still progressing.

        While waiting, log a heartbeat every 30 s so the user can
        tell — at a glance in the Logs view — that the watcher is
        alive and the load is still going. Saves them having to
        toggle on the network-noise filter to see life signs.
        """
        deadline = time.monotonic() + timeout
        last_heartbeat = time.monotonic()
        start = time.monotonic()
        while time.monotonic() < deadline:
            if seq is not None and seq != self._model_change_seq:
                return  # cancelled or replaced: not this watcher's load any more
            status = self.backend.status()
            if status == "ready":
                self.logger.info(
                    f"Successfully switched to {model_size} model",
                    extra={'user_message': True},
                )
                self.set_model_loading(False)
                return
            if status == "error":
                self.logger.error(
                    f"Failed to load {model_size} model",
                    extra={'user_message': True},
                )
                self.set_model_loading(False)
                return
            if status == "stopped":
                # The user (or app teardown) cancelled the in-flight
                # load via ``cancel_model_change`` / backend
                # ``cancel_load``. Exit cleanly without the timeout
                # warning — the cancel path already logged the user-
                # facing message.
                self.set_model_loading(False)
                return
            now = time.monotonic()
            if now - last_heartbeat >= 30.0:
                elapsed = int(now - start)
                self.logger.info(
                    f"Still loading {model_size}… ({elapsed}s elapsed, "
                    f"backend status={status})"
                )
                last_heartbeat = now
            time.sleep(0.2)
        self.logger.warning(
            f"Model change watcher timed out for {model_size} "
            f"after {int(timeout)}s — load may still be in progress, "
            "check the backend status."
        )
        self.set_model_loading(False)
