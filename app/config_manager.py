import copy
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


# macOS reserves ``Ctrl+F1`` through ``Ctrl+F7`` for keyboard
# navigation (Move focus to menu bar / Dock / window / toolbar /
# floating window …). Pynput never sees the events because macOS
# captures them first, so the same defaults that work on Windows
# silently fail on Mac. Pick free-of-conflict combos per platform.
if sys.platform == "darwin":
    _DEFAULT_START_HOTKEY = "ctrl+f8"
    _DEFAULT_STOP_HOTKEY = "ctrl+f9"
    _DEFAULT_CANCEL_HOTKEY = "ctrl+f10"
    # Push-to-talk default: right Cmd is the canonical "thumb"
    # key on Apple keyboards and rarely used in real shortcuts —
    # most apps that read Cmd+X look at the modifier mask, not
    # which physical key produced it, so binding right_cmd alone
    # to push-to-talk doesn't interfere with regular Cmd+letter
    # shortcuts (you press left Cmd for those by muscle memory).
    _DEFAULT_PUSH_TO_TALK_KEY = "right_cmd"
else:
    _DEFAULT_START_HOTKEY = "ctrl+f2"
    _DEFAULT_STOP_HOTKEY = "ctrl+f3"
    _DEFAULT_CANCEL_HOTKEY = "ctrl+f6"
    # Windows/Linux push-to-talk: right Alt is the equivalent
    # "thumb" key — easy to reach, rarely the target of an
    # existing shortcut.  Right Win is also free but on Linux it
    # often opens the activities overlay (GNOME / KDE), so we
    # avoid it.
    _DEFAULT_PUSH_TO_TALK_KEY = "right_alt"

# Setting keys that hold a credential. ``update_user_setting`` logs the
# old and new value of everything it writes, and the root logger runs at
# INFO with a plain FileHandler — so a Hugging Face bearer token was
# copied into ``app.log`` in *both* directions: pasting one logged
# ``hf_… -> hf_…``, and clicking "Clear token" logged the old one. The
# file is surfaced in the Logs view and nothing ever scrubs it.
#
# Matched by section+key rather than by a value shape, so the next
# credential someone adds is covered by the same test rather than by
# someone's memory.
_REDACTED_SETTINGS = frozenset({("huggingface", "token"), ("llm", "api_key")})

#: Names that are credentials wherever they appear, at any depth.
#:
#: The table above matches on section+key, which is exact but only for a
#: key that sits directly in its section — and the post-processing
#: profiles broke that. A profile carries its own ``api_key`` inside
#: ``llm.profiles``, a list of dicts, so saving a profile logged
#: ``('llm', 'profiles')``, missed the table entirely, and wrote every
#: credential in every profile into ``app.log`` via a plain ``repr``.
#:
#: So the table stays as the explicit statement of intent, and this
#: covers the shape the table cannot: a new credential nested in a new
#: structure is covered by the scrubber rather than by remembering to
#: add a tuple.
_SECRET_KEYS = frozenset({"api_key", "token", "password", "secret"})


def _scrub_secrets(value: Any) -> Any:
    """Replace credential values at any depth, keeping the shape.

    Structure is preserved on purpose. ``<set>`` in place of an id makes
    a change log unreadable, and the whole point of logging a save is
    being able to see which profile moved to which provider.
    """
    if isinstance(value, dict):
        return {
            key: (
                ("<set>" if item else "<empty>")
                if str(key).lower() in _SECRET_KEYS
                else _scrub_secrets(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub_secrets(item) for item in value]
    if isinstance(value, str):
        # An address can carry ``user:password@``; the change log is
        # not allowed to quote it.
        from app.log_redaction import redact

        return redact(value)
    return value


def _fits_default(value: Any, default: Any) -> bool:
    """Whether *value* is the kind of thing the default is.

    Only the four scalar kinds and lists are checked; a default of ``None``
    or any other type accepts what it is given. Numbers must be finite,
    and a bool is never a number (``True`` is not a beam size).
    """
    import math

    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(default, list):
        return isinstance(value, list)
    return True


def _redact_for_log(section: str, key: str, value: Any) -> str:
    """Render a setting's value for the change log, credential or not."""
    if (section, key) in _REDACTED_SETTINGS:
        return "<set>" if value else "<empty>"
    return repr(_scrub_secrets(value))


DEFAULT_CONFIG: Dict[str, Any] = {
    "whisper": {
        # Active model alias (or full HF canonical id). The registry
        # maps user-friendly aliases to the actual HF repo path — see
        # ``app/model_mapping.py``.
        #
        # ``gigaam-v3-ctc`` is the default because it is the measured
        # one: 7.1% WER and RTF 0.018 against 16.2% and 0.457 for the
        # Whisper Large v3 Turbo this used to carry. Every card, the
        # README and the landing page already called GigaAM "the
        # default" while the app was quietly loading Whisper — a fresh
        # install got a model 2.3x less accurate and 25x slower than
        # the one documented. ``test_the_configured_default_model_is_the_
        # one_the_docs_call_default`` holds the two together now.
        #
        # It is Russian-only, which is the one reason to prefer Whisper
        # instead; if that trade ever flips, flip it in the docs too,
        # because the docs and this line have to say the same thing.
        "model": "gigaam-v3-ctc",
        "language": "auto",
        "beam_size": 5,
    },
    "hotkey": {
        # Recording mode:
        #   "two_keys" — separate start / stop bindings (default;
        #     classical fire-and-forget: tap once to start, tap
        #     stop to transcribe).
        #   "toggle" — single ``start_recording_hotkey`` flips
        #     between idle ↔ recording on each press.
        #   "push_to_talk" — hold ``push_to_talk_key`` to record,
        #     release to stop and transcribe.  Only mode that lets
        #     you bind a solo modifier (``right_cmd`` / ``right_alt``
        #     etc.) — the listener tracks the press and release
        #     events directly so the key doesn't have to be a
        #     standalone non-modifier.
        "mode": "two_keys",
        # Defaults chosen per-platform — see the constants above.
        # Windows: ``ctrl+f2`` / ``ctrl+f3`` / ``ctrl+f6`` (the
        # original muscle-memory set; nothing else uses them on
        # Win 10/11). macOS: ``ctrl+f8`` / ``ctrl+f9`` / ``ctrl+f10``
        # (lower F-keys are claimed by the system's keyboard
        # navigation). 'cancel' discards the current buffer
        # without transcribing — empty string disables the binding.
        "start_recording_hotkey": _DEFAULT_START_HOTKEY,
        "stop_recording_hotkey": _DEFAULT_STOP_HOTKEY,
        "cancel_recording_hotkey": _DEFAULT_CANCEL_HOTKEY,
        # Push-to-talk binding — meaningful only when ``mode`` is
        # ``"push_to_talk"``.  Solo right-side modifier on macOS
        # (``right_cmd``) / Windows + Linux (``right_alt``).  Empty
        # string disables PTT (UI guards against switching to
        # push_to_talk mode with an empty binding).
        "push_to_talk_key": _DEFAULT_PUSH_TO_TALK_KEY,
        # Minimum time (seconds) the PTT key must stay held for
        # the recording to actually start.  Filters out accidental
        # taps — without it, a glancing right-Cmd press starts +
        # stops a recording in the same frame, producing empty
        # transcriptions and noise.  200 ms is the threshold most
        # voice apps converge on (Discord PTT, Spokenly).
        "push_to_talk_min_hold_seconds": 0.2,
    },
    "audio": {
        "channels": 1,
        "dtype": "float32",
        "max_duration": 300,
        # Mute the system output while a recording is running, so music
        # and notifications do not end up in the microphone and do not
        # compete with the dictation. macOS only — see
        # ``app/system_audio.py``. Off by default: it changes a system
        # setting the user did not ask to change.
        "mute_output_on_record": False,
        # Recognise the speech only, skipping the silences — the
        # silero VAD, applied to the recording before it reaches the
        # model. Off by default: it costs a second model (a couple of
        # megabytes, downloaded on the first use) and it can cut a soft
        # onset, so it is the user's choice.
        "vad_enabled": False,
    },
    "clipboard": {
        "auto_paste": True,
        "preserve_clipboard": False,
        "key_simulation_delay": 0.05,
    },
    "logging": {
        "level": "INFO",
        "file": {
            "enabled": True,
            "filename": "app.log",
            "rotation": {
                "enabled": True,
                "max_bytes": 1048576,
                "backup_count": 5,
                "encoding": "utf-8",
            },
        },
        "console": {"enabled": True, "level": "WARNING"},
    },
    "audio_feedback": {
        "enabled": True,
        "start_sound": "assets/sounds/record_start.wav",
        "stop_sound": "assets/sounds/record_stop.wav",
        "cancel_sound": "assets/sounds/record_cancel.wav",
    },
    "system_tray": {"enabled": True, "tooltip": "Lazy to text"},
    "onboarding": {
        # Set once a model is actually ready — not when the first-run
        # screen was dismissed. The screen exists to get the user to a
        # working dictation, so "done" has to mean a working dictation;
        # anything looser and a user who clicked "set up later" and
        # never came back would have the screen waiting for them
        # forever.
        #
        # Deliberately one flag and not a "dismissed" one: if no model
        # is cached there is nothing to dictate with, so coming back to
        # the setup screen is the honest answer, not nagging.
        "complete": False,
    },
    "history": {
        "enabled": True,
        # History is bounded by entry count alone. It used to also
        # advertise ``auto_cleanup_days: 30``, which nothing ever read —
        # no consumer in ``app/``, and no control for it in the UI — so
        # the key described a deletion policy the app never performed.
        # A setting that silently promises it will erase your dictations
        # is worse than no setting, so it is gone rather than invented.
        "max_entries": 1000,
    },
    "storage": {
        # Where downloaded model weights live. Empty string = use the
        # built-in default (``<project>/models`` in dev,
        # ``<exe-dir>/models`` when frozen). Settings → Storage card
        # writes here. Both Whisper (HF hub) and GigaAM (.ckpt) live
        # under this root, in ``hub/`` and ``gigaam/`` subdirs
        # respectively.
        "models_dir": "",
    },
    "llm": {
        # Optional text post-processing, between the recogniser and the
        # clipboard — see ``app/llm/``. Off by default.
        #
        # The default provider is the local one and the default
        # ``base_url`` is bound to loopback, because the window title
        # says "Local-first speech-to-text" and a cloud default would
        # make that untrue for anyone who ticked the box without
        # reading this. Someone who chooses ``openai`` is choosing to
        # send their dictation off the machine, and the Settings card
        # says so in words while they are choosing.
        #
        # ``model`` is empty on purpose: there is no correct answer
        # that holds across a MacBook and a workstation, and an empty
        # one fails as "not configured" rather than as a 404 from
        # whatever happened to be default upstream.
        "enabled": False,
        "provider": "ollama",
        "model": "",
        "base_url": "http://127.0.0.1:11434",
        # Credential. Covered by ``_REDACTED_SETTINGS`` below — remove
        # it from there and the key lands in app.log in both
        # directions, on save and on clear.
        "api_key": "",
        "mode": "clean",
        "timeout_s": 20,
        # Speed controls. ``reasoning_effort`` is empty (provider
        # default) or none / minimal / low / medium / high; lower is
        # faster on reasoning models. ``max_tokens`` caps the reply,
        # 0 meaning no cap is sent.
        "reasoning_effort": "",
        "max_tokens": 0,
        # Named bundles of the five settings above, plus ``profiles``
        # and ``active_profile`` — see ``app/llm/profiles.py``.
        #
        # Deliberately *not* given defaults here. A fresh install writes
        # the flat keys above and nothing else, and those keys are the
        # single truth until somebody opens the Profiles screen. Writing
        # an empty list would mean two sources for the same settings from
        # the first launch, and they would drift: Settings edits the
        # flat ones, the Profiles screen edits the list, and "what does
        # a dictation use" becomes answerable two ways.
        #
        # So the first profile materialises on the first save from that
        # screen, which also syncs the flat keys to it. No migration, no
        # rewritten file, and an old config loads unchanged.
        "active_profile": "",
    },
    "window": {
        # Where the window was, for the next launch.
        #
        # Both fields are stored together and neither is enough alone.
        # Qt's ``saveGeometry`` bakes an absolute position in, so a window
        # saved on a second monitor and restored after it is unplugged
        # comes back at coordinates that are off-screen — a window you
        # cannot reach, which is worse than not remembering at all. The
        # screen name is checked on the way back in; when it is gone the
        # size is kept and the window is centred on the primary display.
        "geometry": "",
        "screen": "",
    },
    "ui": {
        # ``system`` / ``light`` / ``dark``.
        #
        # ``system`` is the default rather than a fixed dark because a
        # user who has never expressed a preference should not have to:
        # the light and dark palettes are the same fifteen tokens with
        # different values, and ``base.qss`` is shared between them.
        # An unrecognised stored value falls back to this rather than
        # raising — see ``theme.resolve_theme``.
        "theme": "system",
        # UI language: "en" (source strings) or "ru". See app/language.py.
        "language": "en",
        # The Electron interface's colour palette, one of the six themes
        # of the @monos/ui kit (gruvbox, github, dracula, nord, solarized,
        # catppuccin). The Qt interface has its own two palettes and does
        # not read this key.
        "palette": "gruvbox",
    },
    "huggingface": {
        # Optional HF API token. Needed ONLY to download *gated* models:
        # of everything in the registry that is exactly one repo —
        # ``onnx-community/whisper-large-v3`` returns 401 from the Hub
        # without a token, while turbo, GigaAM, Parakeet, T-One, Vosk
        # and Canary are all open. Empty = no token, which is the state
        # every other model works in.
        #
        # This comment used to say the token was required for GigaAM
        # long-form audio (>25 s) "which routes through pyannote VAD".
        # That was left over from the pre-ONNX GigaAM-Python path and
        # has been false for a while: nothing in the app imports
        # pyannote, and GigaAM v3 e2e needs no VAD at all — measured
        # 87 s of Russian through it, 1.4 s, fully punctuated. The
        # accessible description on the Settings field already said the
        # right thing ("Only needed to download gated models"); the two
        # halves of the same card contradicted each other.
        # Settings → "Hugging Face" card writes here.
        "token": "",
    },
}


def default_start_hotkey() -> str:
    """The shipped start hotkey for this platform, in config form.

    The empty states print a key cap telling the user what to press, and
    they used to hardcode ``Ctrl+F2`` — which is simply the wrong key on
    macOS, where ``Ctrl+F1..F7`` belong to the system and the default is
    ``Ctrl+F8``. A cap that names a shortcut this platform cannot
    receive is worse than no cap.
    """
    return _DEFAULT_START_HOTKEY


def default_stop_hotkey() -> str:
    """The shipped stop hotkey for this platform — see
    :func:`default_start_hotkey` for why these are functions."""
    return _DEFAULT_STOP_HOTKEY


def default_cancel_hotkey() -> str:
    """The shipped cancel hotkey for this platform — see
    :func:`default_start_hotkey` for why these are functions."""
    return _DEFAULT_CANCEL_HOTKEY


class ConfigManager:
    def __init__(self, config_filename: str = "config.yaml"):
        self.logger = logging.getLogger(__name__)
        self.base_dir = self._resolve_base_dir()
        self.config_path = self.base_dir / config_filename
        self.config: Dict[str, Any] = {}
        # Serialises concurrent ``_write_config_file`` calls — the
        # async writer thread we spawn from ``update_user_setting``
        # would otherwise race itself when the user clicks Select on
        # a model card (two writes, model + compute_type, fired ~5 ms
        # apart on the Qt main thread).
        self._write_lock = threading.Lock()
        # Writer threads started by ``update_user_setting`` and not yet known to
        # have finished; ``flush_pending_writes`` waits on these.
        self._writers: list[threading.Thread] = []
        # Why the last write to ``config.yaml`` failed, or ``None``. The
        # in-memory value changes either way, so a caller that wants to
        # tell the user "this will not survive a restart" reads it here.
        self.last_write_error: Optional[str] = None
        self._load_or_create()
        self.logger.info("Configuration loaded: %s", self.config_path)

    def _resolve_base_dir(self) -> Path:
        """Where ``config.yaml`` is read from and written to.

        - **Frozen (py2app / PyInstaller)**: per-user config dir
          (``~/Library/Application Support/LazyToText`` on macOS,
          ``%APPDATA%\\LazyToText`` on Windows).  The bundle itself
          may be in ``/Applications`` which is read-only without
          admin, so config writes have to go somewhere user-
          writable that survives across reinstalls.
        - **Dev**: walks up from CWD to the nearest
          ``pyproject.toml`` so a developer running ``uv run …``
          from anywhere in the repo still reads the project's
          ``config.yaml``.
        - Final fallback: CWD when no ``pyproject.toml`` is found.
        """
        import sys

        if getattr(sys, "frozen", False):
            from platformdirs import user_config_dir

            base = Path(user_config_dir("LazyToText", appauthor=False))
            base.mkdir(parents=True, exist_ok=True)
            return base

        cwd = Path.cwd()
        for p in [cwd, *cwd.parents]:
            if (p / 'pyproject.toml').exists():
                return p
        return cwd

    def _load_or_create(self):
        path = self.config_path
        if not path.exists():
            self.logger.warning("config.yaml not found, creating with defaults")
            # deepcopy, not copy: ``update_user_setting`` writes into
            # ``self.config[section][key]`` in place, so a shallow copy
            # would hand it the very dicts ``DEFAULT_CONFIG`` is made of
            # and the first setting a user ever changes would rewrite
            # the module-level defaults for the rest of the process —
            # which the next ``ConfigManager`` (and every test after it)
            # then inherits. Only the fresh-install and the
            # unreadable-file path are affected; the normal path goes
            # through ``_fill_defaults``, which builds new dicts.
            self.config = copy.deepcopy(DEFAULT_CONFIG)
            self._write_config_file()
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self.config = self._fill_defaults(data, DEFAULT_CONFIG)
        except Exception as e:
            self.logger.error("Failed to load %s: %s. Recreating defaults.",
                              path, e)
            self._quarantine_unreadable_config(path)
            self.config = copy.deepcopy(DEFAULT_CONFIG)
            self._write_config_file()

    def _quarantine_unreadable_config(self, path: Path) -> None:
        """Move an unparseable ``config.yaml`` aside instead of erasing it.

        One stray tab, a hand-edit typo or a truncated write used to send
        the whole file straight to the bin: defaults were written over
        the top of it, taking the user's hotkeys, storage path, model
        choice and Hugging Face token with no trace. Renaming the bad
        file to a timestamped ``.corrupt-N`` sibling keeps it recoverable
        and makes the cause visible, without ever *re-reading* it — a
        parse failure here means we have no idea what is in there.
        """
        try:
            n = 1
            while True:
                cand = path.with_name(f"{path.name}.corrupt-{n}")
                if not cand.exists():
                    break
                n += 1
            path.replace(cand)
            self.logger.error(
                "Unreadable config kept at %s — move it back by hand to "
                "recover your settings", cand,
            )
        except OSError as exc:
            self.logger.error(
                "Could not preserve the unreadable config at %s: %s",
                path, exc,
            )

    def _fill_defaults(
        self, current: Dict[str, Any], defaults: Dict[str, Any], path: str = ""
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for k, dv in defaults.items():
            cv = current.get(k)
            if isinstance(dv, dict):
                if isinstance(cv, dict):
                    result[k] = self._fill_defaults(cv, dv, f"{path}{k}.")
                else:
                    # deepcopy, not a bare reference: an older or partial
                    # config.yaml has no ``storage`` section at all, and
                    # handing the result ``DEFAULT_CONFIG["storage"]``
                    # itself would let the next ``update_user_setting``
                    # rewrite the module-level defaults process-wide.
                    # This is the *common* path, not just the
                    # fresh-install one, so it is the one that bites.
                    result[k] = copy.deepcopy(dv)
            elif cv is None:
                result[k] = dv
            elif _fits_default(cv, dv):
                result[k] = cv
            else:
                # A wrongly typed leaf (``beam_size: abc``, a hotkey that
                # is a number) used to reach ``int()`` or ``.strip()``
                # somewhere in start-up and take the whole recording
                # stack down. The default is used instead, and the file
                # is corrected by the next save.
                self.logger.warning(
                    "Setting %s%s has the wrong type (%s) - using the "
                    "default instead.", path, k, type(cv).__name__,
                    extra={'user_message': True},
                )
                result[k] = copy.deepcopy(dv)
        # Keep extra keys from current (do not prune)
        for extra_k, extra_v in current.items():
            if extra_k not in result:
                result[extra_k] = extra_v
        return result

    def flush_pending_writes(self, timeout: float = 5.0) -> bool:
        """Block until any in-flight async writer thread has finished.

        Daemon threads spawned by ``update_user_setting`` write the
        YAML file at their own pace.  Production code rarely needs
        this — the in-memory ``self.config`` already reflects the
        change before the disk catches up — but tests that read the
        file back immediately after a write call this to drain the
        queue.  Returns True iff the writer completed within
        ``timeout``; False on timeout (the caller can decide whether
        to error out or just retry).
        """
        deadline = time.monotonic() + timeout
        for writer in list(self._writers):
            writer.join(max(0.0, deadline - time.monotonic()))
            if writer.is_alive():
                return False
        # A thread that has been started but has not yet taken the lock looks
        # idle to the lock alone, which is why the threads themselves are joined.
        if self._write_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            self._write_lock.release()
            return True
        return False

    def _write_config_file_locked(self):
        """Run on the writer daemon thread — serialised by ``_write_lock``.

        Takes a snapshot of ``self.config`` *under* the lock to defend
        against the Qt main thread mutating the dict mid-serialisation
        when several ``update_user_setting`` calls fire in quick
        succession (Select-button click writes both ``whisper.model``
        and ``whisper.compute_type`` ~5 ms apart).
        """
        with self._write_lock:
            snapshot = copy.deepcopy(self.config)
            self._write_config_file(snapshot)

    def _write_config_file(self, payload: Dict[str, Any] | None = None):
        """Synchronous YAML write + atomic rename.

        ``payload`` defaults to ``self.config`` for the legacy code path
        (``_load_or_create`` after seeding defaults).  When called from
        the writer thread, the caller passes a deep-copied snapshot so
        the dict can't change under our feet during ``yaml.safe_dump``.
        """
        if payload is None:
            payload = self.config
        # Write to a .tmp sibling first, then rename atomically so a crash
        # mid-write never leaves a half-written (corrupted) config file.
        tmp = self.config_path.with_name(self.config_path.name + ".tmp")
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    payload, f,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
            # ``config.yaml`` holds the Hugging Face token, so it must not
            # land at the umask default of world-readable (measured: the
            # released app created it 0644). ``open()`` has no mode
            # argument for the *existing* staging file, so the only
            # correct place is before the rename — chmod-ing the target
            # afterwards would leave a window where the secret is on
            # disk at 0644. Best-effort: Windows has no POSIX mode and
            # inherits its ACL from the parent directory instead.
            try:
                os.chmod(tmp, 0o600)
            except (OSError, NotImplementedError):
                pass
            os.replace(tmp, self.config_path)
            self.last_write_error = None
            self.logger.info("Saved configuration to %s", self.config_path)
        except Exception as e:
            self.last_write_error = str(e)
            self.logger.error("Error writing configuration: %s", e)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


    # --- Public accessors (return live copies) ---
    def get_setting(self, section: str, key: str):
        return self.config.get(section, {}).get(key)

    def get_section(self, section: str) -> Dict[str, Any]:
        """A whole config section as a copy, or ``{}`` when it is absent.

        ``get_setting`` returns one leaf, which is not enough for the
        nested blocks the app reads whole — the ``logging`` section drives
        the file handler's level, name and rotation caps off four
        different leaves.
        """
        value = self.config.get(section)
        return value if isinstance(value, dict) else {}

    def update_user_setting(self, section: str, key: str, value: Any):
        if section not in self.config or not isinstance(self.config[section], dict):
            self.config[section] = {}
        old = self.config[section].get(key)
        if old == value:
            return
        self.config[section][key] = value
        # YAML serialise + atomic os.replace can take 100-500 ms when
        # the file is on a slow disk or under antivirus inspection.
        # Calling this from the Qt main thread (model-card Select
        # click triggers two writes back-to-back) freezes the UI
        # noticeably — wheel-scroll events back up while the main
        # thread is blocked on libc writes.  Spawn a daemon writer
        # so the caller returns immediately; the lock inside
        # ``_write_config_file_locked`` keeps concurrent writers
        # from racing.
        writer = threading.Thread(
            target=self._write_config_file_locked,
            daemon=True,
            name="config-write",
        )
        self._writers = [t for t in self._writers if t.is_alive()] + [writer]
        writer.start()
        self.logger.info(
            "Updated setting %s.%s: %s -> %s",
            section,
            key,
            _redact_for_log(section, key, old),
            _redact_for_log(section, key, value),
        )

    # For backward compatibility with existing code expecting dict copies
    def get_whisper_config(self) -> Dict[str, Any]:
        return self.config.get("whisper", {}).copy()

    def get_hotkey_config(self) -> Dict[str, Any]:
        return self.config.get("hotkey", {}).copy()

    def get_audio_config(self) -> Dict[str, Any]:
        return self.config.get("audio", {}).copy()

    def get_clipboard_config(self) -> Dict[str, Any]:
        return self.config.get("clipboard", {}).copy()

    def get_audio_feedback_config(self) -> Dict[str, Any]:
        return self.config.get("audio_feedback", {}).copy()

    def get_history_config(self) -> Dict[str, Any]:
        return self.config.get("history", {}).copy()

    # Deprecated method kept for minimal surface compatibility (no-op now)
    def print_stop_instructions_based_on_config(self):
        pass
