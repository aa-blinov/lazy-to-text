# Backlog from the baseline specs

Behaviour found inconsistent, dead or surprising while the baseline specs
(001 to 009) were written from the code on 2026-10-24. None of it is
fixed here. Each item is a candidate for its own spec; the spec number says
where the current behaviour is recorded.

## Dead or misleading controls and settings

- 002: "Set up later" on the first-run screen had no handler in the Qt interface (the Electron interface implements it). Beam size, temperature, initial prompt and the per-model VAD checkbox are saved and never read.
- 002: `onboarding.complete` is set only by the "Start dictating" button, though its comment says "once a model is ready".
- 002: the delete dialog shows "0.0 GB" for small models; a failed load does not roll the card back, only a cancel does.
- 002: `whisper.model` empty falls back to `whisper-large-v3-turbo` while the default is `gigaam-v3-ctc`; `storage.models_dir` is documented as `<exe-dir>/models` when frozen, the code uses the per-user cache dir.
- 002: a storage path or token changed at runtime probably does not reach the already-spawned worker process.
- 006: `ui.text_scale`, `audio.device`, `whisper.device`, `whisper.compute_type` and `model_overrides` are read but absent from `DEFAULT_CONFIG`; `system_tray` and `logging.console` are declared and never read.
- 006: Reset hotkeys unticks VAD on screen while the config keeps it on, and does not reach the live listener; the text-scale combo starts at 100% though 0.85 is allowed; "Follow the system" theme is not live; the "Very quiet" message mentions Windows sound settings on macOS.
- 007: the Windows dark title bar is applied once, so a runtime theme change can leave it wrong.

## Behaviour that contradicts its own copy

- 003: the preset checkbox says "Preset for this file" but file transcription never runs post-processing; the pin never expires though its tooltip says "next dictation only". A no-speech result takes the error path, not the warning path built for it.
- 004: the subtitle says every dictation and transcription is listed, but file transcriptions never reach History; `history.enabled` and `max_entries` have no control; with history disabled Clear and Export do nothing; a `state_manager` comment says the stored text is the raw text, it is the post-processed text.
- 005: the presets view docstring says Settings names the preset in use, it does not; duplicating a preset does not mirror the flat keys the way create does.

## Diagnostics

- 008: the worker's log level is fixed at INFO regardless of `logging.level`; records forwarded from the worker lose their `sensitive` tag and could reach `app.log`.
- 008: several storage dialogs, transcribe-view errors and the second-instance dialog are not translated.

## Packaging and process

- 009: `.github/workflows/ci.yml` is an unfilled template that only echoes; `CLAUDE.md` says `release.yml` builds the macOS bundle, it builds Windows only; `build-windows-cuda.ps1` adds `--frozen` only when `uv.lock` exists; the test-count tables in `CLAUDE.md` and `AGENTS.md` disagree.
- 009: `scripts/prune_bundle.py` quotes measured sizes in its docstring, against the repository rule.
- The py2app bundle and `scripts/build-macos.sh` assume Python 3.12 throughout; a checkout whose `.venv` was created with 3.13 builds a bundle whose inference worker cannot start. `.python-version` now pins 3.12.
