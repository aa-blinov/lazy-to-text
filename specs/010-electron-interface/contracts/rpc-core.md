# Contract: core (shell, recording, resources, logs)

Transport and envelope: see `plan.md`. All parameters are JSON objects.

## Methods

| Method | Params | Result |
| --- | --- | --- |
| `app.ping` | none | `{pong: true}` |
| `app.snapshot` | none | `{version, platform, state, engine, stack_error, first_run, hotkey_defaults{start,stop,cancel}, config{whisper,hotkey,audio,clipboard,audio_feedback,history,storage,llm,ui,onboarding,window}, log_path}`. **No credential is in it:** every `api_key` and `token` in `config` (the flat `llm.api_key` and each of `llm.profiles[]`) is replaced by `api_key_set` / `token_set` (bool) |
| `app.last_events` | none | `{events: {name: {at, data}}}`: the last payload, and the epoch second it was sent, of `delivery`, `model_load`, `model_delete` and `llm_test`. A name that has not happened since the runtime started is absent. For a window that was not listening when the event went out (reload, reconnect after sleep). File runs have their own methods (`rpc-transcribe-history.md`); `models.state.last_load` carries the last load |
| `app.events_ticket` | none | `{ticket, ttl_s}`: a one-time ticket for `GET /events?ticket=<ticket>`; valid for `ttl_s` seconds and for one stream. See "Transport rules" |
| `app.quit` | none | `{quitting: true}`; the runtime then exits |
| `recording.toggle` | none | `{state}`. Starts a recording when idle and ready, stops it when recording. With no model ready, an idle toggle is refused with `not_ready` and a sentence for the situation: a load in progress ("A model is still loading..."), no model on disk ("No speech model is installed yet. Open Models and download one."), or a model on disk that is not loaded ("No model is loaded. Open Models and choose one.") |
| `recording.stop` | none | `{stopped, state}` |
| `recording.cancel` | none | `{cancelled, state}` |
| `resources.sample` | none | CPU / RAM / GPU figures |
| `logs.list` | none | `{records: [{id, time, level, logger, message, user_message}]}` (last 2000) |

Errors: `no_stack` when the recording stack failed to build (the message is the reason), `not_ready` (`recording.toggle` with no model), `unknown_method`, `bad_params`, `internal`.

The error envelope is `{error: {code, message, field?}}`. `field` is present when
the refusal is about one parameter (`bad_params`, `bad_path`, `device_failed`), so a
form can mark that input. `internal` never carries the exception's text, only its
type and a pointer to the Logs.

## Transport rules

- **Token.** `POST /rpc` takes the launch token only in `Authorization: Bearer`
  (a token in the query string of a POST is a 401). `GET /events` also accepts
  `?token=` or `?ticket=`, because `EventSource` cannot send a header. A ticket
  (from `app.events_ticket`) is the narrower thing to put in a URL: random, valid
  for 30 seconds, spent by the first stream that presents it; an automatic
  reconnect therefore needs a new one, which the renderer fetches before it
  re-creates the `EventSource`. The query string is never logged. A non-ASCII
  token is a 401.
- **Origin.** A request that carries an `Origin` other than the application's
  own is refused with 403 and gets no CORS headers: `null` and `file://` (the
  packaged window), plus `http://127.0.0.1:<port>` and `http://localhost:<port>`
  of the Vite dev server only when the runtime is started with
  `--dev [--dev-port N]`; `--allow-origin <origin>` (repeatable) adds one more.
  A request with no `Origin` (the main process, a script) is unaffected.
- **Limits.** A connection that does not deliver its request line, headers or
  body within 10 seconds is closed; at most 96 connections are served at once
  (the rest are closed unanswered) and at most 12 of them are event streams
  (the 13th gets 503 `busy`). A body is at most 4 MiB; a body nested deeper than
  the JSON parser allows is a 400.

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
| `settings` | no | `{keys: [string]}`: a setting was written by a call (`settings.set` names its key, a hotkey save or reset says `hotkey`, `devices.select` says `audio.device`). A screen that is open re-reads `settings.get`, so a change made by another client is followed instead of overwritten by the next edit |

## Rules for handler authors

- A handler is `fn(rt, params)` registered with `@method("area.name")` in `app/server/handlers/<area>.py`; the module is imported automatically.
- Never block the channel thread: slow work (downloads, file transcription, mic test) starts a thread, returns at once, and reports by event.
- Persist through `rt.config.update_user_setting(section, key, value)`, then apply live exactly as the Qt controller does (`app/gui/controllers/app_controller.py` is the reference for each side effect).
- Never put a credential or the user's words into a log record.
