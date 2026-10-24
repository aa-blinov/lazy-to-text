"""Controller wiring views to the domain layer (config, state, backends)."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from typing import Any, Optional, Protocol

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from app.gui.theme import (
    TEXT_SCALE_MAX,
    TEXT_SCALE_MIN,
    normalise_theme,
)
from app.gui.widgets.dialogs import confirm, notify
from app.language import normalise_language, tr_format, tr_text

# QApplication is imported above for the clipboard helper; reuse it for
# explicit ``quit()`` calls from tray actions.

from app.gui.main_window import MainWindow
from app.inference_settings import InferenceSettings, ParakeetInferenceSettings
from app.model_mapping import MODELS, alias_for, get_model
# NB: ``cached_models_size``, ``get_models_root``, and
# ``move_cached_dir`` are not used directly in this file any more —
# the storage logic moved to ``_storage_mixin``.  Kept in the import
# block because the mixin looks them up via this module
# (``app_controller.get_models_root`` etc.) so ``monkeypatch.setattr
# (controller_module, …)`` calls in the test suite still land.  See
# ``_storage_mixin._ctrl_module`` for the dispatch.
from app.utils import (  # noqa: F401  (re-export for tests + storage mixin)
    cached_models_size,
    delete_cached_for_info,
    get_models_root,
    is_cached_for_info,
    move_cached_dir,
)


log = logging.getLogger(__name__)


def _resolve_macos_bundle_path(executable: str) -> Optional[str]:
    """Return the enclosing ``.app`` bundle for a frozen macOS binary.

    py2app bundles expose helper executables under
    ``Contents/MacOS`` (notably ``python`` and the app-named launcher).
    Relaunching the helper directly is brittle; the stable unit is the
    bundle itself, which LaunchServices knows how to open correctly.

    The path is normalised *lexically* — absolute, ``..`` collapsed —
    and symlinks are deliberately NOT followed. They have to be: inside
    a real bundle ``Contents/MacOS/python`` is a symlink to the
    interpreter, so ``Path.resolve()`` walks straight out of the bundle
    and lands on that interpreter, and the ``.app`` it was supposed to
    find is gone. This is not hypothetical — it is what a shipped
    py2app bundle looks like, and it sent every frozen macOS restart
    down the ``execv`` fallback this function exists to avoid.
    """
    if not executable:
        return None
    path = Path(os.path.abspath(executable))
    for candidate in (path, *path.parents):
        if candidate.suffix == ".app":
            return str(candidate)
    return None


def _apply_hf_token_to_env(configured: Optional[str]) -> bool:
    """Mirror the user's HF token into the live environment.

    huggingface_hub reads ``HF_TOKEN`` (and the legacy alias
    ``HUGGING_FACE_HUB_TOKEN``) on every download — setting them
    here makes the change effective without a restart.

    Returns True iff a non-empty token was applied.
    """
    import os as _os

    if configured and str(configured).strip():
        token = str(configured).strip()
        _os.environ["HF_TOKEN"] = token
        _os.environ["HUGGING_FACE_HUB_TOKEN"] = token
        return True
    _os.environ.pop("HF_TOKEN", None)
    _os.environ.pop("HUGGING_FACE_HUB_TOKEN", None)
    return False


# ``_apply_env_for_models_root`` and ``_human_size`` live in the
# storage mixin module now — re-imported here so legacy test fixtures
# (e.g. ``import app.gui.controllers.app_controller as mod; mod.
# _apply_env_for_models_root``) keep finding them.  See ``_storage_mixin.py``
# for the actual implementations.
from app.gui.controllers._history_mixin import HistoryMixin
from app.gui.controllers._storage_mixin import (  # noqa: E402, F401
    StorageMixin,
    _apply_env_for_models_root,
    _human_size,
)
from app.gui.controllers._transcribe_mixin import TranscribeMixin
from app.gui.controllers._tray_mixin import TrayMixin
from app.llm.client import clamp_timeout, normalise_effort, normalise_max_tokens
from app.llm.profiles import Profile, profiles_to_config


def _profile_from_dict(data: dict) -> Profile:
    """Rebuild a profile from stored fields.

    Kept as a module function rather than reaching for ``Profile(**data)``
    because the view's payload may be a subset —
    and a strict constructor would raise on exactly the edit that the
    user makes most often. Fields the editor does not own are merged in
    by the caller from the stored profile before this is called.
    """
    return Profile(
        id=data.get("id") or "default",
        name=data.get("name") or data.get("id") or "Default",
        provider=data.get("provider") or "ollama",
        model=data.get("model") or "",
        base_url=data.get("base_url") or "",
        api_key=data.get("api_key") or "",
        mode=data.get("mode") or "clean",
        custom_prompt=data.get("custom_prompt") or "",
        timeout_s=clamp_timeout(data.get("timeout_s")),
        reasoning_effort=normalise_effort(data.get("reasoning_effort")),
        max_tokens=normalise_max_tokens(data.get("max_tokens")),
    )


def _presets_to_dicts(profiles) -> list:
    return profiles_to_config(tuple(profiles))


class _ConfigLike(Protocol):
    def get_setting(self, section: str, key: str) -> Any: ...
    def update_user_setting(self, section: str, key: str, value: Any) -> None: ...


class _HistoryLike(Protocol):
    def get_entries(self) -> list: ...
    def clear_history(self) -> None: ...
    def export_to_text(self, filepath: str) -> bool: ...


class _RecordingLike(Protocol):
    state_changed: Any
    history_updated: Any

    def request_model_change(self, canonical: str) -> bool: ...


class _TrayLike(Protocol):
    show_requested: Any
    quit_requested: Any

    def set_state(self, state: str) -> None: ...


class AppController(
    HistoryMixin,
    StorageMixin,
    TranscribeMixin,
    TrayMixin,
    QObject,
):
    # Worker threads emit these to push results back onto the main
    # Qt thread (auto-queued thanks to the cross-thread connection).
    _mic_test_completed = Signal(float, float)
    _mic_test_failed = Signal(str)
    _storage_size_ready = Signal(str)
    _history_export_finished = Signal(object)
    _model_delete_finished = Signal(object)
    _storage_probe_finished = Signal(object)
    _storage_move_finished = Signal(object)

    def __init__(
        self,
        config: _ConfigLike,
        window: MainWindow,
        history: Optional[_HistoryLike] = None,
        recording: Optional[_RecordingLike] = None,
        tray: Optional[_TrayLike] = None,
    ) -> None:
        super().__init__(parent=window)
        self._config = config
        self._window = window
        self._history = history
        self._recording = recording
        self._tray = tray
        # Drives the elapsed-seconds counter shown in the loading pill
        # while the backend is in model_loading. Started/stopped from
        # ``_on_recording_state_changed``.
        self._loading_elapsed_s = 0
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(1000)
        self._loading_timer.timeout.connect(self._on_loading_tick)
        # Engine pill follows the backend's ``active_provider()`` —
        # the SubprocessBackend caches it from a push-based
        # ``provider_change`` message so this is a cheap dict read,
        # not an IPC round-trip.  We poll on a slow timer (500 ms)
        # rather than only on ``state_changed`` because the worker's
        # ``status_change`` and ``provider_change`` push events can
        # arrive in either order — a sole ``state_changed`` listener
        # would sometimes read a stale (still-``None``) cache for one
        # tick after the model goes ready.
        self._engine_pill_timer = QTimer(self)
        self._engine_pill_timer.setInterval(500)
        self._engine_pill_timer.timeout.connect(self._refresh_engine_pill)
        self._engine_pill_timer.start()
        # Mic test worker bookkeeping.
        self._mic_test_in_progress = False
        self._mic_test_completed.connect(self._on_mic_test_completed)
        self._mic_test_failed.connect(self._on_mic_test_failed)
        self._storage_size_ready.connect(self._on_storage_size_ready)
        # Polls the live audio level for the topbar VU meter while the
        # recording pipeline is in the ``recording`` state.  Tick
        # cadence matches the display refresh — but capped at 60 Hz
        # because the audio buffer behind the meter is only sampled
        # every ~10 ms, so >60 Hz updates render duplicate frames.
        # On 60 Hz monitors that's the legacy ~30 Hz feel; on 144 Hz
        # monitors the bar moves smoothly instead of jumping every 5
        # display frames.
        from app.gui.refresh_rate import tick_interval_ms

        vu_interval = tick_interval_ms(max_rate=60)
        self._vu_timer = QTimer(self)
        self._vu_timer.setInterval(vu_interval)
        self._vu_timer.timeout.connect(self._on_vu_tick)
        # Independent polling timer for the mic-test VU meter on the
        # Settings card. Separate from the recording one so a mic
        # test can run while the recording state is anything other
        # than ``recording`` (idle, processing, model_loading, …)
        # without us trying to feed two meters from one tick with
        # divergent on/off conditions.
        self._mic_test_vu_timer = QTimer(self)
        self._mic_test_vu_timer.setInterval(vu_interval)
        self._mic_test_vu_timer.timeout.connect(self._on_mic_test_vu_tick)
        # Snapshot of the pre-click state, captured in
        # ``_on_model_selected`` and consumed by
        # ``_on_cancel_load_requested`` to roll the active card +
        # config + topbar pill back when the user bails out of a load.
        # Cleared once the load actually succeeds (in
        # ``_on_recording_state_changed`` when state goes to idle and
        # the backend reports ``ready``).
        self._pre_select_snapshot: Optional[dict] = None
        # Expected weights size for the model currently loading, in
        # bytes. Set from ``ModelInfo.size_mb`` at the moment of click
        # (and at app startup for the persisted active model). Used as
        # a fallback ``total`` in ``_on_download_progress`` when the
        # backend's tqdm fires with ``total=0`` — NeMo's downloader
        # streams via plain ``requests`` with no Content-Length, so
        # without this the topbar would show raw bytes the entire
        # download instead of a climbing percentage. Reset once the
        # load settles (state goes idle).
        self._loading_expected_bytes: int = 0
        self._history_export_in_progress = False
        self._storage_change_in_progress = False
        self._model_delete_in_progress: set[str] = set()
        self._pending_inference_settings = None
        self._backend_settings_push_thread: Optional[threading.Thread] = None
        self._backend_settings_push_lock = threading.Lock()
        self._history_export_finished.connect(self._on_history_export_finished)
        self._model_delete_finished.connect(self._on_model_delete_finished)
        self._storage_probe_finished.connect(self._on_storage_probe_finished)
        self._storage_move_finished.connect(self._on_storage_move_finished)
        self._wire_models()
        self._wire_first_run()
        self._wire_window()
        self._wire_shortcuts()
        self._wire_history()
        self._wire_transcribe()
        if recording is not None:
            self._wire_recording(recording)
        if tray is not None:
            self._wire_tray(tray)

    def _wire_first_run(self) -> None:
        """Connect the first-run screen, if the window has one.

        Duck-typed like ``download_progress``: a window built by a test
        double, by the screenshot generator or by anything else that
        predates the screen simply does not have the attribute, and that
        is not a reason to refuse to start.

        The chosen alias goes out through ``ModelsView.model_selected``
        rather than into ``_on_model_selected`` directly, so the model
        switch, the topbar pill, the card states and the config write
        are the same code the catalogue button runs. One download
        implementation, not two.
        """
        view = getattr(self._window, "first_run_view", None)
        if view is None:
            return
        try:
            view.model_chosen.connect(
                lambda alias: self._window.models_view.model_selected.emit(
                    alias
                )
            )
            view.catalogue_requested.connect(self._on_catalogue_requested)
            view.completed.connect(self._on_first_run_completed)
        except Exception:  # pragma: no cover — defensive
            log.warning("First-run screen could not be wired", exc_info=True)

        hotkey = None
        try:
            hotkey = self._config.get_setting("hotkey", "start_recording_hotkey")
            stop = self._config.get_setting("hotkey", "stop_recording_hotkey")
        except Exception:  # pragma: no cover — defensive
            stop = ""
        try:
            view.set_hotkey(hotkey, stop)
        except Exception:  # pragma: no cover — defensive
            log.warning("First-run hotkey could not be set", exc_info=True)

    def _on_catalogue_requested(self) -> None:
        """"See all models instead" — step aside, do not block.

        The catalogue is the honest answer for someone who does not want
        the app's recommendation, and it is a normal page rather than a
        dead end: picking a model there loads it, which finishes setup
        the same way finishing here would.
        """
        self._window.set_first_run(False)
        try:
            self._window.sidebar.set_active("models")
        except Exception:  # pragma: no cover — defensive
            pass

    def _on_first_run_completed(self) -> None:
        """First run is over, and only because it actually worked."""
        self._window.set_first_run(False)
        try:
            self._config.update_user_setting("onboarding", "complete", True)
        except Exception:  # pragma: no cover — defensive
            log.warning("Could not persist onboarding completion",
                        exc_info=True)

    def _wire_models(self) -> None:
        view = self._window.models_view
        raw = self._config.get_setting("whisper", "model")
        active_info = None
        if isinstance(raw, str) and raw:
            alias = alias_for(raw)
            try:
                info = get_model(alias)
            except KeyError:
                log.warning(
                    "Model %r from config is not in the registry — leaving inactive",
                    raw,
                )
            else:
                # Only restore the persisted "active" state if the
                # weights are already on disk. If they aren't, we'd be
                # showing the green Active pill while the backend has
                # nothing loaded — and the Select/Download button stays
                # hidden, leaving the user with no way to trigger the
                # download. Force a deliberate click in that case.
                if is_cached_for_info(info):
                    view.set_active(alias)
                    active_info = info
                else:
                    log.info(
                        "Persisted model %s is not cached — leaving "
                        "inactive until the user clicks Download.",
                        info.canonical,
                    )

        # Pre-populate the fallback total for an auto-loading
        # persisted model — same rationale as ``_on_model_selected``.
        if active_info is not None:
            self._loading_expected_bytes = (
                int(active_info.size_mb) * 1024 * 1024
            )

        self._sync_topbar_model(active_info)

        # Pre-fill every card's inference panel from saved per-alias
        # overrides so the user sees the values they last picked
        # when activating a card.
        for alias in self._all_known_aliases():
            view.set_inference_settings(
                alias, self._load_inference_settings(alias)
            )
        if active_info is not None:
            # Push the *active* card's overrides into the live backend
            # so the first transcription respects the saved values.
            self._push_inference_to_backend(
                self._load_inference_settings(active_info.alias)
            )
        # The VAD is a global switch, not a per-model one: the saved
        # value has to reach the live backend too, or the first
        # dictation of the session would ignore it.
        self._push_vad_to_backend(
            bool(self._config.get_setting("audio", "vad_enabled"))
        )

        view.model_selected.connect(self._on_model_selected)
        view.model_delete_requested.connect(self._on_model_delete_requested)
        view.inference_settings_changed.connect(
            self._on_inference_settings_changed
        )

    def _on_model_selected(self, alias: str) -> None:
        if self._window.models_view.active_alias() == alias:
            return

        info = None
        try:
            info = get_model(alias)
        except KeyError:
            pass

        # Snapshot the pre-click state before we mutate anything. If
        # the user clicks Cancel before this load finishes, the
        # cancel handler restores the active card / config / topbar
        # pill from this dict — without it the half-clicked card
        # stays marked Active forever.
        prev_alias = self._window.models_view.active_alias()
        prev_info = None
        if prev_alias:
            try:
                prev_info = get_model(prev_alias)
            except KeyError:
                prev_info = None
        self._pre_select_snapshot = {
            "alias": prev_alias,
            "info": prev_info,
            "config_model": self._config.get_setting("whisper", "model"),
            "config_compute": self._config.get_setting(
                "whisper", "compute_type"
            ),
        }

        self._config.update_user_setting("whisper", "model", alias)
        if info is not None:
            self._config.update_user_setting(
                "whisper", "compute_type", info.compute_type
            )
            # Pre-populate the fallback total so the topbar can show
            # percentages even when the backend's tqdm doesn't carry
            # a Content-Length (NeMo's case — see field doc).
            self._loading_expected_bytes = (
                int(info.size_mb) * 1024 * 1024
            )
        else:
            self._loading_expected_bytes = 0
        self._window.models_view.set_active(alias)
        # Paint the Loading pill on the card immediately — otherwise
        # there is a ~200 ms window where the green Active pill flashes
        # before the recording-state poll catches up and switches it to
        # Loading. The state poll's later set_loading(True) is
        # idempotent.
        self._window.models_view.set_loading(True)
        # Same race for the topbar pill: ``request_model_change``
        # below kicks off an async load and the
        # ``state_changed("model_loading")`` signal arrives a tick
        # later — without an immediate flip the topbar would briefly
        # render the new model as Active.  Push ``model_loading``
        # before ``_sync_topbar_model`` so the new alias goes
        # straight into the yellow loading pill instead of flashing
        # green for a frame.
        self._window.topbar.set_recording_state("model_loading")
        # Push this card's persisted inference overrides into the
        # live backend so the first transcription on the new model
        # honours the saved values.
        self._push_inference_to_backend(self._load_inference_settings(alias))
        self._sync_topbar_model(info)
        if self._recording is not None:
            compute_type = info.compute_type if info else None
            # Defer the backend request to the next event loop tick.
            # Even though request_model_change spawns a thread, the
            # initial handshake / state prep can take a few ms.
            # Moving it to the next tick ensures the UI repaints
            # the "Loading" pill immediately.
            QTimer.singleShot(
                0,
                lambda: self._recording.request_model_change(
                    alias, compute_type
                )
            )

    def _sync_topbar_model(self, info) -> None:
        # Use ``alias`` for the topbar pill — ``display_name``
        # carries the marketing parenthetical (e.g.
        # "T-One (Russian, telephony-tuned)") which crowds the
        # engine / cancel widgets on the same row. Aliases are
        # already short (``t-one``, ``vosk-ru``, ``parakeet-tdt-v3``,
        # ``whisper-large-v3-turbo``) and unique per model.
        self._window.topbar.set_active_model(info.alias if info else None)

    def _on_model_delete_requested(self, alias: str) -> None:
        """Confirm with the user, then drop the cached weights for
        ``alias`` and refresh the Models view so the buttons reflect
        the new state.

        Several aliases can share the same Hugging Face canonical
        (``turbo`` and ``turbo-int8`` both point at
        ``deepdml/faster-whisper-large-v3-turbo-ct2``). Deleting the
        cache for one wipes weights for the other too — surface that
        in the confirmation text so the user isn't surprised when
        the sibling card flips back to 'Download'."""
        try:
            info = get_model(alias)
        except KeyError:
            log.warning("delete requested for unknown alias %s — ignoring", alias)
            return

        siblings = [
            m.alias for m in MODELS
            if m.canonical == info.canonical and m.alias != alias
        ]
        sibling_note = ""
        if siblings:
            sibling_note = "\n\n" + tr_format(
                "AppController",
                "This cache is shared with other variants and they will also "
                "flip to 'Download' after deletion: %1.",
                ", ".join(siblings),
            )

        if not confirm(
            self._window,
            tr_text("AppController", "Delete cached model?"),
            (
                tr_format(
                    "AppController",
                    "Remove the downloaded weights for %1 (%2 GB)?",
                    tr_text("ModelInfo", info.display_name),
                    f"{info.size_mb / 1000:.1f}",
                )
                + "\n\n"
                + tr_text(
                    "AppController",
                    "You'll need to download them again the next time "
                    "this model is selected.",
                )
                + sibling_note
            ),
            yes_label=tr_text("AppController", "Delete"),
        ):
            return

        if alias in self._model_delete_in_progress:
            return
        self._model_delete_in_progress.add(alias)
        self._window.models_view.set_delete_busy(alias, True)

        def worker() -> None:
            try:
                deleted = bool(delete_cached_for_info(info))
            except Exception as exc:  # pragma: no cover — defensive
                payload = {
                    "alias": alias,
                    "deleted": False,
                    "error": str(exc),
                    "display_name": info.display_name,
                }
            else:
                payload = {
                    "alias": alias,
                    "deleted": deleted,
                    "error": "",
                    "display_name": info.display_name,
                }
            try:
                self._model_delete_finished.emit(payload)
            except RuntimeError:
                pass

        threading.Thread(
            target=worker,
            daemon=True,
            name=f"delete-model:{alias}",
        ).start()

    def _on_model_delete_finished(self, payload: dict) -> None:
        alias = str(payload.get("alias", ""))
        deleted = bool(payload.get("deleted"))
        error = str(payload.get("error", "") or "")
        display_name = str(payload.get("display_name", alias) or alias)
        self._model_delete_in_progress.discard(alias)
        if alias:
            self._window.models_view.set_delete_busy(alias, False)
        if deleted:
            log.info("Deleted cached weights for %s", alias)
        else:
            log.warning(
                "Delete returned False for %s — see earlier log for the "
                "filesystem error, or the cache was already empty",
                alias,
            )
            notify(
                self._window,
                tr_text("AppController", "Delete failed"),
                tr_format(
                    "AppController",
                    "Could not delete the cached weights for %1.",
                    tr_text("ModelInfo", display_name),
                ),
                informative=error or None,
                kind="warning",
            )
        self._window.models_view.refresh_cache_state()
        # Recompute the Storage card size — the just-deleted weights
        # were typically the largest single chunk.
        self._refresh_storage_size()

    def _push_start_hotkey(self, value: str) -> None:
        """Tell both empty states which key actually starts a recording.

        Duck-typed on ``set_start_hotkey`` for the same reason the Find
        accelerator duck-types on ``focus_search``: a view that prints a
        key cap grows the setter, and the controller does not carry a
        table of which views those are.
        """
        for view in (
            self._window.history_view,
            self._window.transcribe_view,
        ):
            setter = getattr(view, "set_start_hotkey", None)
            if callable(setter):
                setter(value)

    def _wire_window(self) -> None:
        """Window-level wiring: where it was, and files the OS hands it.

        Not part of ``_wire_shortcuts``. The window's position and the
        OS's file-open requests have nothing to do with hotkeys, and
        burying them in the one function that touches every screen made
        them invisible to anyone reading that function — which is how the
        first version of this code came to reference ``window`` before
        assigning it, and to raise ``NameError`` on every launch.

        Both halves are the same shape as everything else here: the
        window emits or reports, the controller owns the config.
        """
        window = self._window

        # A file the OS asked us to open. Goes through exactly the same
        # handler as a drag from Finder, because it is the same job: the
        # Transcribe view runs, the recording stack transcribes, the
        # result lands in the window. A second path into the pipeline
        # would be a second set of things to get right.
        file_open = getattr(window, "file_open_requested", None)
        if file_open is not None:
            file_open.connect(self._on_file_opened_by_os)

        state_changed = getattr(window, "window_state_changed", None)
        if state_changed is None:
            # A window double that predates either signal — a screenshot
            # generator, a stub — still starts. Duck-typed like every
            # other optional window capability in this class.
            return
        state_changed.connect(self._on_window_state_changed)

        # Read back, not just written: this is the one piece of window
        # state that has to be pushed *into* the window at startup rather
        # than pulled out of it on the way down. An empty or unreadable
        # blob is ``restore_window_state``'s problem to reject, and it
        # does, so nothing is checked here beyond "is there one".
        geometry = self._config.get_setting("window", "geometry") or ""
        screen = self._config.get_setting("window", "screen") or ""
        if geometry:
            window.restore_window_state(geometry, screen)

    def _wire_shortcuts(self) -> None:
        view = self._window.shortcuts_view
        start = self._config.get_setting("hotkey", "start_recording_hotkey") or ""
        stop = self._config.get_setting("hotkey", "stop_recording_hotkey") or ""
        cancel = self._config.get_setting("hotkey", "cancel_recording_hotkey") or ""
        auto_paste = bool(self._config.get_setting("clipboard", "auto_paste"))
        mode = self._config.get_setting("hotkey", "mode") or "two_keys"
        ptt_key = self._config.get_setting("hotkey", "push_to_talk_key") or ""
        mute_output = bool(
            self._config.get_setting("audio", "mute_output_on_record")
        )
        vad_enabled = bool(self._config.get_setting("audio", "vad_enabled"))
        view.set_values(
            start_hotkey=start,
            stop_hotkey=stop,
            auto_paste=auto_paste,
            cancel_hotkey=cancel,
            mode=mode,
            push_to_talk_key=ptt_key,
            mute_output_on_record=mute_output,
            vad_enabled=vad_enabled,
        )
        # Text scale is applied in ``build_application`` before the first
        # paint; this only mirrors the stored value into the combo so
        # the control shows the truth. ``set_text_scale`` is
        # suspend-guarded and will not echo back as a user edit.
        view.set_text_scale(self._text_scale())
        # The theme follows the same path: read from config into the
        # combo under ``_suspend_emit`` so loading it is not mistaken
        # for the user choosing it.
        view.set_theme(
            normalise_theme(self._config.get_setting("ui", "theme"))
        )
        view.set_language(
            normalise_language(self._config.get_setting("ui", "language"))
        )

        # The two empty states print a key cap telling the user what to
        # press, and both used to hardcode ``Ctrl+F2`` — the wrong key
        # on macOS, and stale the moment anyone rebound it. Push the
        # configured value out to them.
        self._push_start_hotkey(start)

        # Populate the microphone dropdown if a recording stack is wired in.
        if self._recording is not None and hasattr(self._recording, "list_input_devices"):
            self._refresh_shortcuts_devices()

        view.save_requested.connect(self._on_shortcuts_save)
        view.hotkeys_reset_requested.connect(self._on_hotkeys_reset)
        view.hf_token_reset_requested.connect(self._on_hf_token_reset)

        presets_view = getattr(self._window, "presets_view", None)
        if presets_view is not None:
            # The post-processing switch lives on the Post-processing screen.
            presets_view.set_llm_values(self._config.get_section("llm"))
            presets_view.llm_changed.connect(self._on_llm_changed)
            presets_view.preset_changed.connect(self._on_preset_changed)
            presets_view.preset_activated.connect(
                self._on_preset_activated
            )
            presets_view.preset_create_requested.connect(
                self._on_preset_create_requested
            )
            presets_view.preset_duplicate_requested.connect(
                self._on_preset_duplicate_requested
            )
            presets_view.preset_delete_requested.connect(
                self._on_preset_delete_requested
            )
            presets_view.preset_key_reset_requested.connect(
                self._on_preset_key_reset
            )

        transcribe_view = getattr(self._window, "transcribe_view", None)
        if transcribe_view is not None:
            transcribe_view.preset_override_changed.connect(
                self._on_preset_override_changed
            )

        # Materialise the implicit profile before painting, so the
        # screen opens on the user's own settings rather than an empty
        # list it would have to explain.
        self._ensure_first_preset()
        self._refresh_presets_ui()
        view.test_mic_requested.connect(self._on_test_mic_requested)
        view.mac_permissions_changed.connect(
            self._on_macos_permissions_changed
        )

        # Storage card — connect signals + paint resolved path / size.
        # The whole behaviour lives in ``StorageMixin``; calling
        # ``_wire_storage`` is the single coupling point with this
        # method.
        self._wire_storage()

        # Hugging Face card — paint the persisted token + apply to
        # env (in case ``app.py``'s startup hook missed something).
        view.hf_token_changed.connect(self._on_hf_token_changed)
        persisted_token = self._config.get_setting("huggingface", "token") or ""
        view.set_hf_token(persisted_token)
        _apply_hf_token_to_env(persisted_token)

    def _on_hf_token_changed(self, token: str) -> None:
        """Persist the new token, mirror into env, and re-evaluate
        every GigaAM card's warning so the user gets immediate
        feedback that the warning has cleared."""
        token = (token or "").strip()
        self._config.update_user_setting("huggingface", "token", token)
        _apply_hf_token_to_env(token)
        self._window.models_view.refresh_hf_token_state()

    def _text_scale(self) -> float:
        """Stored text scale, normalised to the supported band.

        A hand-edited ``config.yaml`` can hold anything, so the value is
        clamped through the same bounds ``theme.set_text_scale`` uses.
        """
        return self._text_scale_from(
            self._config.get_setting("ui", "text_scale")
        )

    @staticmethod
    def _text_scale_from(value) -> float:
        try:
            candidate = float(value)
        except (TypeError, ValueError):
            return 1.0
        if candidate != candidate:  # NaN
            return 1.0
        return max(
            TEXT_SCALE_MIN, min(TEXT_SCALE_MAX, candidate),
        )

    def _on_shortcuts_save(self, payload: dict) -> None:
        self._config.update_user_setting(
            "hotkey", "start_recording_hotkey", payload["start_hotkey"]
        )
        self._config.update_user_setting(
            "hotkey", "stop_recording_hotkey", payload["stop_hotkey"]
        )
        # ``cancel_hotkey`` may be missing if a legacy view emits the
        # old payload shape — default to empty rather than raising.
        self._config.update_user_setting(
            "hotkey",
            "cancel_recording_hotkey",
            payload.get("cancel_hotkey", ""),
        )
        # Recording mode + PTT key — added with the push-to-talk
        # feature; ``payload.get`` keeps legacy callers (tests built
        # against the old view contract) working with the previous
        # 4-field bundle.
        new_mode = payload.get("mode", "two_keys")
        new_ptt_key = payload.get("push_to_talk_key", "") or ""
        self._config.update_user_setting("hotkey", "mode", new_mode)
        self._config.update_user_setting(
            "hotkey", "push_to_talk_key", new_ptt_key,
        )
        self._config.update_user_setting(
            "clipboard", "auto_paste", payload["auto_paste"]
        )
        # ``get`` keeps legacy callers (tests built against the old
        # view contract) working — the key is simply left alone.
        if "mute_output_on_record" in payload:
            self._config.update_user_setting(
                "audio", "mute_output_on_record",
                bool(payload["mute_output_on_record"]),
            )
        if "vad_enabled" in payload:
            vad_enabled = bool(payload["vad_enabled"])
            self._config.update_user_setting("audio", "vad_enabled", vad_enabled)
            # Live: the worker may have to download the VAD model, and
            # that must not happen on the thread that saves the form.
            self._push_vad_to_backend(vad_enabled)
        # Keep the empty states' key caps in step with the binding that
        # was just written. Without this a rebind is live everywhere
        # except the one place that tells the user what to press.
        self._push_start_hotkey(payload["start_hotkey"])
        # Text scale. The view has already re-resolved the stylesheet by
        # the time this fires, so this is purely the persistence half.
        if "text_scale" in payload:
            self._config.update_user_setting(
                "ui", "text_scale", self._text_scale_from(payload["text_scale"]),
            )
        if "language" in payload:
            # Applied by the view when the user picks it; persisted here.
            self._config.update_user_setting(
                "ui", "language", normalise_language(payload["language"]),
            )
        if "theme" in payload:
            # Persisted, but not applied here: the view already repainted
            # itself when the user picked the value, and re-applying from
            # here would build the stylesheet a second time for the same
            # change.
            self._config.update_user_setting(
                "ui", "theme", normalise_theme(payload["theme"]),
            )
        # Push the new auto-paste flag into the running ClipboardManager
        # too — without this the checkbox visually toggles but the
        # actual delivery path keeps the value it had at startup.
        clipboard = self._resolve_clipboard_manager()
        if clipboard is not None and hasattr(clipboard, "update_auto_paste"):
            try:
                clipboard.update_auto_paste(bool(payload["auto_paste"]))
            except Exception as exc:  # pragma: no cover — defensive
                log.warning("Failed to push auto_paste live: %s", exc)
        # Push hotkey changes into the live HotkeyListener — without
        # this the user has to restart the app for a mode switch /
        # rebind to take effect.  Each ``change_hotkey_config`` call
        # re-runs ``stop_listening`` + ``start_listening`` internally,
        # so order doesn't matter and we don't have to rebuild the
        # listener manually.
        listener = self._resolve_hotkey_listener()
        if listener is not None:
            try:
                batch = getattr(listener, "change_hotkey_configs", None)
                if callable(batch):
                    batch({
                        "mode": new_mode,
                        "push_to_talk_key": new_ptt_key,
                        "start_recording_hotkey": payload["start_hotkey"],
                        "stop_recording_hotkey": payload["stop_hotkey"],
                        "cancel_combination": payload.get("cancel_hotkey") or None,
                    })
                else:
                    listener.change_hotkey_config("mode", new_mode)
                    listener.change_hotkey_config(
                        "push_to_talk_key", new_ptt_key,
                    )
                    listener.change_hotkey_config(
                        "start_recording_hotkey", payload["start_hotkey"],
                    )
                    listener.change_hotkey_config(
                        "stop_recording_hotkey", payload["stop_hotkey"],
                    )
                    listener.change_hotkey_config(
                        "cancel_combination",
                        payload.get("cancel_hotkey") or None,
                    )
            except Exception as exc:
                log.warning("Failed to push hotkey changes live: %s", exc)
        if "device" in payload:
            self._config.update_user_setting("audio", "device", payload["device"])
            if self._recording is not None and hasattr(self._recording, "set_input_device"):
                try:
                    self._recording.set_input_device(payload["device"])
                except Exception as exc:
                    log.warning("Failed to switch input device: %s", exc)

    def _resolve_hotkey_listener(self):
        """Find the live ``HotkeyListener`` instance to push setting
        changes into.  Returns ``None`` when no recording stack is
        wired (e.g. unit tests building AppController without a
        recording controller).

        ``RecordingController`` keeps the listener under
        ``_hotkey_listener`` (underscore-prefixed by convention).
        Accept either name in case a future refactor exposes it as
        a public property.
        """
        recording = self._recording
        if recording is None:
            return None
        return getattr(recording, "_hotkey_listener", None) or getattr(
            recording, "hotkey_listener", None
        )

    def _on_test_mic_requested(self) -> None:
        if self._mic_test_in_progress:
            return
        if self._recording is None:
            self._window.shortcuts_view.show_mic_test_error(
                "no recording stack"
            )
            return
        # Don't poke the device while transcription is running — both
        # would try to open the same input simultaneously.
        try:
            current = self._recording.current_state()
        except Exception:
            current = None
        if current and current != "idle":
            self._window.shortcuts_view.show_mic_test_error(
                "wait until current operation finishes"
            )
            return
        recorder = self._resolve_audio_recorder()
        if recorder is None:
            self._window.shortcuts_view.show_mic_test_error(
                "audio recorder unavailable"
            )
            return

        self._mic_test_in_progress = True
        self._window.shortcuts_view.show_mic_test_running()
        # Start the live-level poll right when the worker thread
        # spins up — first audio block lands ~50 ms in, which is
        # before the worker's first level update could otherwise be
        # picked up.
        if not self._mic_test_vu_timer.isActive():
            self._mic_test_vu_timer.start()

        def worker():
            try:
                result = recorder.test_input_level(3.0)
            except Exception as exc:  # pragma: no cover — surfaces in UI
                self._mic_test_failed.emit(str(exc))
                return
            self._mic_test_completed.emit(
                float(result.get("peak", 0.0)),
                float(result.get("rms", 0.0)),
            )

        threading.Thread(
            target=worker, daemon=True, name="mic-test"
        ).start()

    def _on_mic_test_completed(self, peak: float, rms: float) -> None:
        self._mic_test_in_progress = False
        self._mic_test_vu_timer.stop()
        self._window.shortcuts_view.show_mic_test_result(peak, rms)

    def _on_mic_test_failed(self, reason: str) -> None:
        self._mic_test_in_progress = False
        self._mic_test_vu_timer.stop()
        self._window.shortcuts_view.show_mic_test_error(reason)

    def _on_mic_test_vu_tick(self) -> None:
        """Poll the live audio level while a mic test is running and
        push it into the Settings-card VU meter. Mirrors the topbar
        VU pump but routed to a different sink."""
        recorder = self._resolve_audio_recorder()
        if recorder is None:
            return
        getter = getattr(recorder, "current_input_level", None)
        if getter is None:
            return
        try:
            level = float(getter())
        except Exception:  # pragma: no cover — defensive
            return
        try:
            self._window.shortcuts_view.set_mic_test_level(level)
        except Exception:  # pragma: no cover — defensive
            pass

    # ---- Inference-settings plumbing ---------------------------------------

    def _all_known_aliases(self) -> list:
        from app.model_mapping import aliases
        return aliases()

    def _settings_class_for(self, alias: str):
        """Pick the inference-settings dataclass that matches the
        model's backend kind. Whisper → ``InferenceSettings`` (5
        knobs); Parakeet/NeMo-style → ``ParakeetInferenceSettings`` (just
        ``timestamps``); unknown alias defaults to Whisper since that's
        the most common case for raw HF ids."""
        try:
            info = get_model(alias)
        except KeyError:
            return InferenceSettings
        if getattr(info, "onnx_family", "") == "parakeet":
            return ParakeetInferenceSettings
        return InferenceSettings

    def _load_inference_settings(self, alias: str):
        try:
            raw = self._config.get_setting("model_overrides", alias)
        except Exception:
            raw = None
        return self._settings_class_for(alias).from_mapping(raw)

    def _save_inference_settings(self, alias: str, settings) -> None:
        self._config.update_user_setting(
            "model_overrides", alias, settings.to_mapping()
        )

    def _push_inference_to_backend(self, settings) -> None:
        if self._recording is None:
            return
        with self._backend_settings_push_lock:
            self._pending_inference_settings = settings
            thread = self._backend_settings_push_thread
            if thread is not None and thread.is_alive():
                return
            thread = threading.Thread(
                target=self._drain_inference_pushes,
                daemon=True,
                name="push-inference-settings",
            )
            self._backend_settings_push_thread = thread
        thread.start()

    def _drain_inference_pushes(self) -> None:
        while True:
            with self._backend_settings_push_lock:
                settings = self._pending_inference_settings
                if settings is None:
                    self._backend_settings_push_thread = None
                    return
                self._pending_inference_settings = None
            sm = getattr(self._recording, "state_manager", None)
            backend = getattr(sm, "backend", None) if sm is not None else None
            target = getattr(backend, "update_inference_settings", None)
            if target is None:
                with self._backend_settings_push_lock:
                    self._backend_settings_push_thread = None
                return
            try:
                target(settings)
            except Exception as exc:  # pragma: no cover — defensive
                log.warning("Live inference-settings push raised: %s", exc)

    def _push_vad_to_backend(self, enabled: bool) -> None:
        """Turn the VAD on or off in the running backend, off the UI thread.

        The first time this runs with the VAD on, the worker downloads
        the model — a couple of megabytes — so the call belongs on a
        background thread.  A failure is logged and leaves the feature
        off; a dictation without the VAD still works.
        """
        sm = getattr(self._recording, "state_manager", None)
        backend = getattr(sm, "backend", None) if sm is not None else None
        target = getattr(backend, "set_vad_enabled", None)
        if target is None:
            return

        def _run() -> None:
            try:
                target(bool(enabled))
            except Exception as exc:  # pragma: no cover — defensive
                log.warning("Live VAD push raised: %s", exc)

        threading.Thread(
            target=_run, daemon=True, name="push-vad-setting",
        ).start()

    def _on_inference_settings_changed(self, alias: str, settings) -> None:
        # Persist for next launch.
        self._save_inference_settings(alias, settings)
        # Live-apply only if the change was made on the *active*
        # card — otherwise the user is configuring something they
        # haven't picked yet.
        if self._window.models_view.active_alias() == alias:
            self._push_inference_to_backend(settings)

    def _resolve_state_manager(self):
        """The StateManager behind the recording controller.

        Same indirection as ``_resolve_audio_recorder`` and
        ``_resolve_clipboard_manager``: the controller is handed a
        recording protocol, not the manager, and the profile override is
        a piece of manager state rather than a Qt signal — it has to be
        read on the pipeline thread, not when the button was pressed.
        """
        sm = getattr(self._recording, "state_manager", None)
        if sm is None:
            return None
        if not hasattr(sm, "set_profile_override"):
            return None
        return sm

    def _resolve_audio_recorder(self):
        """The state_manager owns the AudioRecorder; reach for it
        through whichever recording-controller protocol the controller
        was given."""
        sm = getattr(self._recording, "state_manager", None)
        if sm is None:
            return None
        return getattr(sm, "audio_recorder", None)

    def _resolve_clipboard_manager(self):
        """Same indirection for the ClipboardManager so settings can
        push live updates (auto_paste toggle) without the user having
        to restart the app for the change to take effect."""
        sm = getattr(self._recording, "state_manager", None)
        if sm is None:
            return None
        return getattr(sm, "clipboard_manager", None)

    def _refresh_shortcuts_devices(self) -> None:
        if self._recording is None or not hasattr(
            self._recording, "list_input_devices"
        ):
            return
        try:
            devices = self._recording.list_input_devices()
            current = self._recording.current_input_device()
        except Exception:
            devices, current = [], None
        self._window.shortcuts_view.set_devices(devices, current)

    def _on_macos_permissions_changed(self) -> None:
        """Refresh macOS runtime pieces that can start working
        immediately after a TCC permission grant."""
        self._refresh_shortcuts_devices()
        listener = self._resolve_hotkey_listener()
        if listener is None:
            return
        try:
            listener.stop_listening()
            listener.start_listening()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Failed to refresh macOS hotkey listener: %s", exc)

    def _on_restart_requested(self) -> None:
        """Clean-shutdown + relaunch the process.

        Nothing in the UI calls this. It was written for a "granted,
        but restart the app" state in the macOS Accessibility banner,
        and ``CLAUDE.md`` used to describe that banner as shipped;
        neither the state nor the button exists — the only two banner
        states are ``hidden`` and ``untrusted``.

        The situation it was meant to cover is handled elsewhere:
        ``_on_macos_permissions_changed`` stops and re-starts the
        hotkey listener on the False→True transition, and on macOS
        ``start_listening`` builds a fresh ``MacHotkeyMonitor``, so
        the event tap is rebuilt against the new TCC state without a
        relaunch. If that ever proves not to be enough, the banner is
        where this should be wired back in.

        Kept as a working relaunch helper, with tests. The mechanics
        below are the reason it was written down at all.

        We tear down the recording stack synchronously (so the
        worker process exits, audio device is released, etc.).

        In dev / non-frozen runs we can safely ``os.execv`` the
        current interpreter. For a py2app bundle on macOS we must
        relaunch the bundle via LaunchServices (``open -n``) instead
        of exec'ing the inner helper binary directly — that helper
        does not have a stable standalone loader layout and can die
        at launch with a missing ``libpython`` error.
        """
        import sys

        log.info("Restart requested — relaunching")
        # Best-effort teardown of recording-side resources.  A
        # failure here shouldn't block the relaunch; the new
        # process will recreate them anyway.
        if self._recording is not None:
            shutdown = getattr(self._recording, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception as exc:  # pragma: no cover — defensive
                    log.warning("recording shutdown raised on restart: %s", exc)
        # Drop the single-instance lock file the parent process
        # holds so the relaunched copy can take it.  ``QApplication``
        # stores the handle on itself in ``app.py::main``.
        try:
            qt_app = QApplication.instance()
            if qt_app is not None:
                handle = getattr(qt_app, "_instance_mutex", None)
                if handle is not None and hasattr(handle, "release"):
                    handle.release()
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("instance lock release raised on restart: %s", exc)
        if sys.platform == "darwin" and getattr(sys, "frozen", False):
            bundle_path = _resolve_macos_bundle_path(sys.executable)
            if bundle_path:
                try:
                    subprocess.Popen(
                        ["/usr/bin/open", "-n", bundle_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except OSError as exc:
                    log.error("bundle relaunch failed: %s", exc)
                else:
                    if self._window is not None:
                        self._window.request_quit()
                    qt_app = QApplication.instance()
                    if qt_app is not None:
                        qt_app.quit()
                    return
            log.warning(
                "Could not resolve .app bundle from %s; falling back to execv",
                sys.executable,
            )
        # ``execv`` replaces the current process image — never
        # returns on success. ``sys.executable`` + ``sys.argv``
        # gives us the same launch line uv used originally.
        try:
            os.execv(sys.executable, [sys.executable, *sys.argv])
        except OSError as exc:
            log.error("os.execv failed on restart: %s", exc)

    def _on_hotkeys_reset(self) -> None:
        """Reset hotkey fields + recording mode to built-in defaults
        — leaves auto-paste, storage, HF token alone.  Per-card
        reset replaces the old global 'Reset to defaults' footer
        button which conflated unrelated settings."""
        from app.config_manager import DEFAULT_CONFIG

        defaults_hotkey = DEFAULT_CONFIG.get("hotkey", {})
        start = defaults_hotkey.get("start_recording_hotkey", "")
        stop = defaults_hotkey.get("stop_recording_hotkey", "")
        cancel = defaults_hotkey.get("cancel_recording_hotkey", "")
        mode = defaults_hotkey.get("mode", "two_keys")
        ptt_key = defaults_hotkey.get("push_to_talk_key", "") or ""

        self._config.update_user_setting(
            "hotkey", "start_recording_hotkey", start
        )
        self._config.update_user_setting(
            "hotkey", "stop_recording_hotkey", stop
        )
        self._config.update_user_setting(
            "hotkey", "cancel_recording_hotkey", cancel
        )
        self._config.update_user_setting("hotkey", "mode", mode)
        self._config.update_user_setting(
            "hotkey", "push_to_talk_key", ptt_key,
        )
        # Same reason as on save: the key caps in the two empty states
        # have to follow a reset, or they keep naming a binding the
        # user just gave up.
        self._push_start_hotkey(start)
        # Refresh the fields without disturbing the rest of the
        # form (current auto-paste / device / HF token / storage path
        # all stay where they are). ``set_values`` is suspend-guarded
        # so this won't bounce ``save_requested`` back at us.
        view = self._window.shortcuts_view
        view.set_values(
            start_hotkey=start,
            stop_hotkey=stop,
            auto_paste=view.auto_paste(),
            cancel_hotkey=cancel,
            mode=mode,
            push_to_talk_key=ptt_key,
            mute_output_on_record=view.mute_output_on_record(),
        )

    def _on_llm_changed(self, payload: dict) -> None:
        """Persist the post-processing switch.

        One key, written through ``update_user_setting`` rather than
        dumped with ``update_section`` so that it goes through the same
        change log every other setting does.

        This used to write six keys and then a second handler mirrored
        the same edit into whichever profile was active — two writers
        for one setting, which is what made the card confusing enough to
        need a word invented to explain it. The five fields moved to the
        Presets screen and this card keeps only the switch.
        """
        if not isinstance(payload, dict):
            return
        if "enabled" in payload:
            self._config.update_user_setting(
                "llm", "enabled", bool(payload["enabled"])
            )

    def _on_file_opened_by_os(self, path: str) -> None:
        """Finder said open this; run it.

        Brings the window forward first. The user double-clicked a file,
        so the outcome they expect is a window that appears with the
        transcript in it — and if the app was sitting in the tray the
        request has to raise it, or the work happens invisibly.

        Raises before checking the file, so the error is on a window
        somebody can see. An app that swallows a bad path behind a tray
        icon looks exactly like an app that did nothing.

        Logged, because this path is the one part of the app that the
        desktop starts rather than the user: if a double-click in Finder
        silently does nothing, there is no other trace of it, and the log
        line is the difference between "macOS never delivered it" and
        "we delivered it and dropped it on the floor".
        """
        logger = logging.getLogger(__name__)
        window = self._window

        if not os.path.isfile(path):
            logger.warning("OS asked to open a file that is not there: %r", path)
            window.show_window_if_hidden()
            window.transcribe_view.set_error("That file is no longer there.")
            return

        logger.info("OS opened a file: %s", path)
        window.show_window_if_hidden()
        self._on_transcribe_file_picked(path)

    def _on_window_state_changed(self, geometry: str, screen: str) -> None:
        """Remember where the window was.

        Key by key rather than as a section, so both writes go through
        the change log like every other setting. Neither value is a
        credential and neither is large enough to be a problem in a log
        line: the geometry is Qt's own opaque blob, about 140 bytes.
        """
        self._config.update_user_setting("window", "geometry", geometry)
        self._config.update_user_setting("window", "screen", screen)

    def _on_hf_token_reset(self) -> None:
        """Per-card 'Clear token' on the Hugging Face card. Routes
        through the same path the textbox-edit handler uses so the
        env var, model-card warnings, and view all update."""
        self._on_hf_token_changed("")
        self._window.shortcuts_view.set_hf_token("")

    # ---- profiles -------------------------------------------------------
    #
    # A profile is written as one ``llm.profiles`` list plus the flat
    # keys mirrored from whichever is active. Both halves are deliberate:
    # the flat keys are what every pre-profiles code path reads, and
    # syncing them on activation is what keeps "what a dictation uses"
    # answerable from either representation. The mirror is written key by
    # key through ``update_user_setting`` so the change log still scrubs
    # the credential — see ``_on_llm_changed``.

    def _llm_section(self) -> dict:
        return self._config.get_section("llm") or {}

    def _refresh_presets_ui(self) -> None:
        """Push the stored list into both screens that show it.

        Called after every change rather than from the view's own state,
        because a preset edited on one screen and picked on the other is
        the normal case, not the edge one.
        """
        from app.llm import active_profile_id, is_local_url, profiles_from_config

        section = self._llm_section()
        profiles = profiles_from_config(section)
        active_id = active_profile_id(section)
        active = next((p for p in profiles if p.id == active_id), None)

        window = self._window
        if hasattr(window, "presets_view"):
            window.presets_view.set_profiles(
                [dict(p.__dict__) for p in profiles], active_id
            )
        sm = self._resolve_state_manager()
        if hasattr(window, "transcribe_view"):
            window.transcribe_view.set_profiles(
                [(p.id, p.name) for p in profiles],
                active_id,
                sm.profile_override_id() if sm else "",
            )
        if hasattr(window, "presets_view"):
            window.presets_view.set_llm_values(dict(section))

    def _on_preset_changed(self, payload: dict) -> None:
        """One field of one profile changed.

        The whole profile is rewritten rather than merged key by key:
        a profile is a value, and a partial merge is how a field the
        editor stopped showing survives invisibly into the next save.
        """
        from app.llm import profiles_from_config

        if not isinstance(payload, dict) or not payload.get("id"):
            return

        profiles = list(profiles_from_config(self._llm_section()))
        updated = dict(payload)
        found = False
        for index, existing in enumerate(profiles):
            if existing.id == updated["id"]:
                # Keep whatever the editor does not own, such as timeout.
                merged = dict(existing.__dict__)
                merged.update(updated)
                profiles[index] = _profile_from_dict(merged)
                found = True
                break
        if not found:
            profiles.append(_profile_from_dict(updated))

        self._config.update_user_setting(
            "llm", "profiles", _presets_to_dicts(profiles)
        )
        self._sync_flat_keys_to_active(profiles)
        self._refresh_presets_ui()

    def _sync_flat_keys_to_active(self, profiles=None) -> None:
        from app.llm import active_profile_id, profiles_from_config, with_profile

        if profiles is None:
            profiles = profiles_from_config(self._llm_section())
        section = self._llm_section()
        chosen = next(
            (p for p in profiles if p.id == active_profile_id(section)), None
        )
        if chosen is None:
            return
        flat = with_profile(section, chosen)
        for key in ("provider", "model", "base_url", "api_key", "mode",
                    "timeout_s", "reasoning_effort", "max_tokens"):
            self._config.update_user_setting("llm", key, flat[key])

    def _on_preset_activated(self, profile_id: str) -> None:
        from app.llm import profiles_from_config

        profiles = profiles_from_config(self._llm_section())
        if profile_id not in {p.id for p in profiles}:
            return
        self._config.update_user_setting("llm", "active_profile", profile_id)
        self._sync_flat_keys_to_active(profiles)
        self._refresh_presets_ui()

    def _ensure_first_preset(self) -> None:
        """Write the implicit profile out as a real one, once.

        A config with no ``profiles`` key describes one profile through
        the flat keys. That is enough to run a dictation and it is what
        every existing install has — but it means the Presets screen
        opens on an empty list, and the user's own configuration is the
        one thing on it that is *not* listed. Asking somebody to press
        New to see what they already have is backwards, and the empty
        state had to grow a paragraph explaining the concept, which is
        the same problem in a second place.

        So the first launch materialises it: one profile, named, holding
        exactly what was already configured. Nothing is asked for, and
        nothing about the stored settings changes — the flat keys are
        untouched, so a user who never opens the screen notices nothing
        except one more line in a file they do not read.
        """
        from app.llm import profiles_from_config

        section = self._llm_section()
        if isinstance(section.get("profiles"), list) and section["profiles"]:
            return

        profiles = list(profiles_from_config(section))
        self._config.update_user_setting(
            "llm", "profiles", _presets_to_dicts(profiles)
        )

    def _on_preset_key_reset(self, profile_id: str) -> None:
        """Discard one preset's key.

        Routed through the preset editor rather than the flat keys: the
        key belongs to the preset, and clearing whichever one happens to
        be active would be clearing a different credential than the one
        the button is under.
        """
        from app.llm import active_profile_id, profiles_from_config

        if not profile_id:
            return
        profiles = [
            _profile_from_dict({**p.__dict__, "api_key": ""})
            if p.id == profile_id
            else p
            for p in profiles_from_config(self._llm_section())
        ]
        self._config.update_user_setting(
            "llm", "profiles", _presets_to_dicts(profiles)
        )
        if profile_id == active_profile_id(self._llm_section()):
            self._sync_flat_keys_to_active(profiles)
        self._refresh_presets_ui()

    def _on_preset_create_requested(self) -> None:
        """Add another preset beside the rest, starting from the first.

        Copying rather than starting blank: a new preset almost always
        differs from an existing one by a server and a model name, and
        those are the two fields somebody cannot recall from memory.
        Starting empty would send them back to the default card for the
        parts they already had right.
        """
        from app.llm import next_profile_id, profiles_from_config

        section = self._llm_section()
        existing = list(profiles_from_config(section))
        created_id = next_profile_id(tuple(existing))
        base = existing[0]
        profiles = existing + [
            _profile_from_dict(
                {
                    **base.__dict__,
                    "id": created_id,
                    "name": f"{base.name} copy",
                }
            )
        ]

        self._config.update_user_setting(
            "llm", "profiles", _presets_to_dicts(profiles)
        )
        self._sync_flat_keys_to_active(profiles)
        self._refresh_presets_ui()
        # Open the new one. The screen otherwise re-opens whichever is
        # active, so pressing New would appear to do nothing at all.
        self._window.presets_view.set_profiles(
            [dict(p.__dict__) for p in profiles],
            self._config.get_setting("llm", "active_profile") or "",
        )
        self._window.presets_view.open_preset(created_id)


    def _on_preset_duplicate_requested(self, profile_id: str) -> None:
        from app.llm import next_profile_id, profiles_from_config

        profiles = list(profiles_from_config(self._llm_section()))
        source = next((p for p in profiles if p.id == profile_id), None)
        if source is None:
            return

        new_id = next_profile_id(tuple(profiles), base=profile_id)
        copy = _profile_from_dict(
            {
                **source.__dict__,
                "id": new_id,
                "name": f"{source.name} copy",
            }
        )
        # The credential goes with the copy on purpose: a duplicated
        # profile that silently lost its key would fail at request time
        # with a 401, which reads like the key was revoked.
        profiles.append(copy)

        self._config.update_user_setting(
            "llm", "profiles", _presets_to_dicts(profiles)
        )
        self._refresh_presets_ui()

    def _on_preset_delete_requested(self, profile_id: str) -> None:
        from app.llm import active_profile_id, profiles_from_config

        section = self._llm_section()
        profiles = list(profiles_from_config(section))
        remaining = [p for p in profiles if p.id != profile_id]
        if not remaining:
            # Deleting the last one leaves no way to post-process and no
            # way back. The Delete button is disabled in that state; this
            # is the check behind it, and it is the *only* one — an
            # earlier ``len(profiles) <= 1`` guard sat directly above
            # this one and covered the same case, so a mutation removing
            # it changed nothing and the test could not kill it.
            return

        self._config.update_user_setting(
            "llm", "profiles", _presets_to_dicts(remaining)
        )
        if active_profile_id(section) == profile_id:
            # The default cannot name something that no longer exists;
            # ``active_profile_id`` would fall back anyway, but leaving
            # the stale id in the file means the next profile added
            # could inherit it.
            self._config.update_user_setting(
                "llm", "active_profile", remaining[0].id
            )
        self._sync_flat_keys_to_active(remaining)
        self._refresh_presets_ui()

    def _on_preset_override_changed(self, profile_id: str) -> None:
        """Pin a profile for the next dictation without persisting it.

        Never written to ``config.yaml`` — see
        :meth:`StateManager.set_profile_override`.
        """
        sm = self._resolve_state_manager()
        if sm is not None:
            sm.set_profile_override(profile_id)


    def _wire_recording(self, recording: _RecordingLike) -> None:
        recording.state_changed.connect(self._window.topbar.set_recording_state)
        # Sidebar bottom-left slot owns the recording pill + VU meter
        # since they moved out of the topbar (where they overlapped
        # the resource graphs). Same state vocab, fanned out.
        recording.state_changed.connect(
            self._window.sidebar.recording_status.set_recording_state
        )
        recording.state_changed.connect(self._window.recording_overlay.set_state)
        recording.state_changed.connect(self._on_recording_state_changed)
        recording.history_updated.connect(self._on_history_updated_signal)
        # Optional: download progress (only the real RecordingController
        # exposes it; fakes in tests can omit it).
        progress_signal = getattr(recording, "download_progress", None)
        if progress_signal is not None:
            try:
                progress_signal.connect(self._on_download_progress)
            except Exception:  # pragma: no cover — defensive
                pass
        # Optional for the same reason: fakes in tests may not expose it.
        delivery_signal = getattr(recording, "delivery_reported", None)
        if delivery_signal is not None:
            try:
                delivery_signal.connect(self._on_delivery_reported)
            except Exception:  # pragma: no cover — defensive
                pass
        # Topbar's Cancel button → recording controller's cancel.
        # Wrapped in a thin lambda so we can keep recording strictly
        # typed against the protocol (which only declares request_*).
        self._window.topbar.cancel_load_requested.connect(
            self._on_cancel_load_requested
        )
        try:
            current_state = recording.current_state()
        except Exception:
            current_state = "idle"
        self._window.recording_overlay.set_state(current_state)

    def _on_delivery_reported(self, outcome: str, detail: str, text: str) -> None:
        """Answer "did it go in?" where the user is actually looking.

        While dictating, the main window is behind the app being typed
        into — that is the normal case, not an edge case. So the answer,
        with the text it was about, goes to the always-on-top overlay.
        """
        self._window.recording_overlay.show_delivery(outcome, detail, text)

    def _on_cancel_load_requested(self) -> None:
        if self._recording is None:
            return
        target = getattr(self._recording, "cancel_model_change", None)
        if target is None:
            return
        try:
            cancelled = bool(target())
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("cancel_model_change forward raised: %s", exc)
            return

        # If nothing was actually loading (cancel raced a finished
        # load), don't roll back — the active card / config reflect a
        # successfully loaded model that we shouldn't undo.
        if not cancelled:
            return

        snapshot = self._pre_select_snapshot
        self._pre_select_snapshot = None
        if snapshot is None:
            return

        prev_alias = snapshot.get("alias")
        prev_info = snapshot.get("info")
        if prev_alias:
            self._window.models_view.set_active(prev_alias)
        else:
            self._window.models_view.set_active(None)
        self._sync_topbar_model(prev_info)
        # Reset the fallback total to the previous active model's
        # size (or 0 if there was no prior active card) — a future
        # progress event from a stale tqdm bar shouldn't render
        # a percentage scaled to the cancelled model.
        if prev_info is not None:
            self._loading_expected_bytes = (
                int(prev_info.size_mb) * 1024 * 1024
            )
        else:
            self._loading_expected_bytes = 0

        # Roll back config too, otherwise next launch picks the
        # cancelled model up as the persisted active one.
        prev_model = snapshot.get("config_model")
        if prev_model is not None:
            self._config.update_user_setting("whisper", "model", prev_model)
        else:
            self._config.update_user_setting("whisper", "model", "")
        prev_compute = snapshot.get("config_compute")
        if prev_compute is not None:
            self._config.update_user_setting(
                "whisper", "compute_type", prev_compute
            )

    def _on_download_progress(self, current: int, total: int, _desc: str) -> None:
        # Mirror progress in two places: the small pill in the topbar
        # and the larger pill on the active model card. The card is
        # where the user just clicked, so it's the most discoverable
        # spot to surface byte-by-byte feedback.
        # When the backend's tqdm fires without a usable total (NeMo's
        # streaming download has no Content-Length), substitute the
        # expected size we cached at click time. Real totals (Whisper /
        # GigaAM via huggingface_hub.snapshot_download) take priority.
        effective_total = int(total)
        if effective_total <= 0 and self._loading_expected_bytes > 0:
            effective_total = self._loading_expected_bytes
        try:
            self._window.topbar.set_loading_progress(
                int(current), effective_total
            )
        except Exception:  # pragma: no cover — defensive
            pass
        try:
            self._window.models_view.set_loading_progress(
                int(current), effective_total
            )
        except Exception:  # pragma: no cover — defensive
            pass
        # And on the first-run screen, which is showing the download and
        # nothing else — the catalogue is not on screen there, so the
        # card's own pill is not a place the user is looking.
        try:
            first_run = getattr(self._window, "first_run_view", None)
            if first_run is not None and self._window.is_first_run():
                first_run.set_download_progress(int(current), effective_total)
        except Exception:  # pragma: no cover — defensive
            pass

    def _on_recording_state_changed(self, state: str) -> None:
        # Live VU meter follows the recording state — start polling as
        # soon as we enter "recording", stop the moment we leave.
        if state == "recording":
            if not self._vu_timer.isActive():
                self._vu_timer.start()
        else:
            self._vu_timer.stop()
            try:
                self._window.sidebar.recording_status.set_input_level(0.0)
            except Exception:  # pragma: no cover — defensive
                pass

        # Engine pill follows the backend's actual EP — clear while
        # loading, populate once the model goes ready (or back to
        # unloaded after a model swap / error).  ``active_provider``
        # is push-cached on the SubprocessBackend side so this is a
        # cheap dict read, not an IPC round-trip.
        self._refresh_engine_pill()
        # Block destructive interactions while not idle.
        self._window.models_view.set_locked(state != "idle")
        # Reflect the model-loading state on the active card's pill so it
        # doesn't say "Active" while the topbar shows "Loading model…".
        self._window.models_view.set_loading(state == "model_loading")
        # While loading, tick an elapsed-seconds counter so the pill has
        # something to show even when no tqdm download progress fires
        # (cached models deserialise silently for ~15 s).
        if state == "model_loading":
            self._loading_elapsed_s = 0
            if not self._loading_timer.isActive():
                self._loading_timer.start()
        else:
            self._loading_timer.stop()
            self._loading_elapsed_s = 0
        # When the backend transitions back to idle, a download (if any)
        # has finished — refresh per-card cache state so the button on
        # the previously-undownloaded model switches to "Select".
        if state == "idle":
            try:
                self._window.models_view.refresh_cache_state()
            except Exception:  # pragma: no cover — defensive
                pass
            # The first-run screen is the one consumer that has to know
            # whether loading stopped because the weights arrived or
            # because they did not, and it can only find out by asking
            # the card whose disk check it just re-armed.
            try:
                first_run = getattr(self._window, "first_run_view", None)
                if first_run is not None and self._window.is_first_run():
                    first_run.begin_settle_check()
            except Exception:  # pragma: no cover — defensive
                pass
            # Clear the fallback total so a future load whose tqdm
            # legitimately reports total=0 (e.g. a small misc file
            # in some unrelated download) doesn't inherit a stale
            # 1.2 GB expectation from the previous Parakeet load.
            self._loading_expected_bytes = 0
            # Explicitly refresh the engine pill again now that we are idle/ready.
            self._refresh_engine_pill()
        if self._tray is not None:
            self._tray.set_state(state)

    def _on_vu_tick(self) -> None:
        recorder = self._resolve_audio_recorder()
        if recorder is None:
            return
        getter = getattr(recorder, "current_input_level", None)
        if getter is None:
            return
        try:
            level = float(getter())
        except Exception:  # pragma: no cover — defensive
            return
        try:
            self._window.sidebar.recording_status.set_input_level(level)
        except Exception:  # pragma: no cover — defensive
            pass

    def _on_loading_tick(self) -> None:
        self._loading_elapsed_s += 1
        # Topbar pill owns the elapsed-seconds display.  We deliberately
        # don't push the same number into the models view — duplicating
        # "Loading 5s" on the active card alongside "Loading: <name> 5s"
        # in the topbar was redundant noise.  ``ModelCard.set_loading_elapsed``
        # still records the value for any future card-level use, but
        # doesn't render it.
        try:
            self._window.topbar.set_loading_elapsed(self._loading_elapsed_s)
        except Exception:  # pragma: no cover — defensive
            pass

    def _refresh_engine_pill(self) -> None:
        """Pull the current EP from the backend (via ``RecordingController.active_provider``)
        and push it into the sidebar's engine pill.  Idempotent —
        safe to call from any state transition or timer tick.
        ``None`` clears the pill back to its empty / muted state.

        While the recording stack is in ``model_loading``, the
        backend's active_provider is still ``None`` (the EP is
        bound by ``onnx_asr.load_model`` only after the load
        finishes).  Render the pill as "Loading…" in that window
        so the chip doesn't sit at ``—`` for the entire compile
        time and contradict the STATUS pill right below it.
        """
        sidebar = getattr(self._window, "sidebar", None)
        target = (
            getattr(sidebar.recording_status, "set_active_provider", None)
            if sidebar is not None else None
        )
        if not callable(target):
            return

        recording = self._recording
        if recording is None:
            try:
                target(None)
            except Exception:  # pragma: no cover — defensive
                pass
            return

        # Loading-priority: show "Loading…" while the backend is
        # bringing a model up.  Once the load completes, fall
        # through to ``active_provider`` which has the real EP.
        current_state_getter = getattr(recording, "current_state", None)
        current_state = None
        if callable(current_state_getter):
            try:
                current_state = current_state_getter()
            except Exception:  # pragma: no cover — defensive
                current_state = None
        if current_state == "model_loading":
            try:
                target("Loading…")
            except Exception:  # pragma: no cover — defensive
                pass
            return

        getter = getattr(recording, "active_provider", None)
        provider = None
        if callable(getter):
            try:
                provider = getter()
            except Exception:  # pragma: no cover — defensive
                provider = None

        log.debug("Refreshing engine pill. Provider from backend: %s", provider)
        try:
            target(provider)
        except Exception:  # pragma: no cover — defensive
            pass
