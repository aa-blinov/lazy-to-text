# Contract: core (shell, recording, resources, logs)

Transport and envelope: see `plan.md`. All parameters are JSON objects.

## Methods

| Method | Params | Result |
| --- | --- | --- |
| `app.ping` | none | `{pong: true}` |
| `app.snapshot` | none | `{version, platform, state, engine, stack_error, first_run, hotkey_defaults{start,stop,cancel}, config{whisper,hotkey,audio,clipboard,audio_feedback,history,storage,llm,ui,onboarding,window}, log_path}` |
| `app.quit` | none | `{quitting: true}`; the runtime then exits |
| `recording.toggle` | none | `{state}`. Starts a recording when idle and ready, stops it when recording |
| `recording.stop` | none | `{stopped, state}` |
| `recording.cancel` | none | `{cancelled, state}` |
| `resources.sample` | none | CPU / RAM / GPU figures |
| `logs.list` | none | `{records: [{id, time, level, logger, message, user_message}]}` (last 2000) |

Errors: `no_stack` when the recording stack failed to build (the message is the reason), `unknown_method`, `bad_params`, `internal`.

## Events

| Event | Sticky | Payload |
| --- | --- | --- |
| `state` | yes | `{state: "idle"\|"recording"\|"processing"\|"model_loading"}` |
| `engine` | yes | `{provider: string\|null, model, alias}`; `provider` is `"Loading…"` while loading |
| `resources` | yes | `{cpu_percent, ram_used_mb, ram_total_mb, ram_percent, gpu_*?}` every 2 s |
| `progress` | yes | `{current, total, desc, elapsed}` while a model loads; zeros otherwise |
| `level` | no | `{level: 0..1}` at 20 Hz while recording |
| `delivery` | no | `{outcome: "pasted"\|"copied"\|"failed", detail, text}` |
| `history` | no | `{}`: the history changed |
| `log` | no | one record, same shape as `logs.list` items |

## Rules for handler authors

- A handler is `fn(rt, params)` registered with `@method("area.name")` in `app/server/handlers/<area>.py`; the module is imported automatically.
- Never block the channel thread: slow work (downloads, file transcription, mic test) starts a thread, returns at once, and reports by event.
- Persist through `rt.config.update_user_setting(section, key, value)`, then apply live exactly as the Qt controller does (`app/gui/controllers/app_controller.py` is the reference for each side effect).
- Never put a credential or the user's words into a log record.
