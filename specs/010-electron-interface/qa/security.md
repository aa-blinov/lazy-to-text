# QA: security and privacy

Tester: security. Date: 2026-10-24. Platform: macOS 26 arm64 only.

What I ran: the dev runtime (`.venv` python, `python -m app.server`, port 18105, scratch `HOME`), and the
PyInstaller runtime that ships in `desktop/release/mac-arm64/Lazy to Text.app/Contents/Resources/backend`
(built 11:21 today, may not equal HEAD) on 18105 with scratch `HOME`; the renderer through Vite on 18106
and the Browser pane; the packaged Electron app with `--remote-debugging-port=18107` and a scratch
`--user-data-dir` (its backend takes an ephemeral port, which I could not pin). A fake OpenAI-style
server, a redirecting server, a slow-drip server and a logging HTTP proxy on 18115-18119. Dictations went
through the real microphone (speech played with `say`), with auto-paste off. Planted secrets:
`sk-PLANTED-SECRET-AAA` (API key), `hf_PLANTEDTOKENBBB` (HF token), `URLPASSWORDCCC` (password in a URL).
Scripts and raw outputs: `evidence/security/evidence.txt`, `ortprobe.py`, `cdp.mjs`, `rpc.py`.

Side effects I could not undo: the dev runtime writes its `logs/` into the worktree (`logs/app.log`,
`logs/transcription_history.jsonl`, both ignored by git, shared with other testers), so a few of my test
dictations and log lines are in them. Nothing else outside the scratch dir and `qa/` was written
(`/tmp/relative-leak.txt` from one test was deleted). The clipboard was overwritten by dictations and
restored from a backup at the end. All my processes are stopped.

## Defects

### QA-SEC-1  onnxruntime sends telemetry to Microsoft on every model load, and nothing in the app turns it off
Severity: S1 (breaks the documented promise "no telemetry by design", PRODUCT.md lines 123-125 and 217, and
Status: FIXED - app/privacy_env.py sets ORT_DISABLE_TELEMETRY=1 on import, imported first by onnx_backend, subprocess_worker/backend, bootstrap, cuda_bootstrap, server.runtime; verified by tests/test_privacy_env.py and ortprobe.py re-run in a fresh HOME (without: deviceid True; with the import: no deviceid, no db, no sockets)
Constitution I; what is sent is not audio or words as far as I can tell, but I could not read the TLS payload)
Where: `app/backends/onnx_backend.py` and `app/backends/subprocess_worker.py` (no call anywhere); the wheel
`onnxruntime 1.30.0` in `uv.lock`; the PyInstaller runtime.
Steps:
1. Fresh empty `HOME`. `python ortprobe.py <any .onnx>` (one `InferenceSession`, wait 20 s).
2. Look at the process's sockets and at `$HOME/Library/Application Support/Microsoft/DeveloperTools/.onnxruntime/`.
3. Repeat under `sandbox-exec` denying outbound :443, with `ort.disable_telemetry_events()`, and with `ORT_DISABLE_TELEMETRY=1`.
Expected: no network and no files outside the app's own directories (PRODUCT.md, spec.md privacy statements).
Actual: a persistent device id (`deviceid`), `onnxruntime.db` (SQLite queue with a `tenant_token` column) and an
ESTABLISHED TLS connection to `20.184.175.13:443`, which is exactly what `mobile.events.data.microsoft.com`
resolves to (`strings` on the dylib shows `https://mobile.events.data.microsoft.com/OneCollector/1.0`). 3 of 3
runs without the variable connected; the sandboxed run did not (so the connection is the telemetry);
`disable_telemetry_events()` called from Python was not enough (device id created, connection made);
`ORT_DISABLE_TELEMETRY=1` removed both the files and the socket (2 of 2). The packaged runtime created the same
files in its scratch profile. The connection bypasses `HTTP(S)_PROXY` (native code), which is why a proxy
saw nothing. The device id lives in a Microsoft-named directory in the user's profile, shared with any other
ORT program, and survives uninstalling the app.
Evidence: `evidence/security/evidence.txt` [SEC-1].
Suspected cause: ORT 1.30 enables native telemetry by default on macOS; the app never sets
`ORT_DISABLE_TELEMETRY=1` in the worker/server environment before importing onnxruntime. The Qt build is
affected the same way (same worker).
Status: PARTLY - the shell starts the runtime with `ORT_DISABLE_TELEMETRY=1` in its environment (`backend.cjs`; `test_the_runtime_child_starts_with_onnxruntime_telemetry_off`), which covers the Electron path; the runtime and the worker should set it themselves before importing onnxruntime, which is the runtime area. (shell fixer)

### QA-SEC-2  A mistyped server address saves, then breaks the whole Post-processing screen, and the next dictation is lost
Severity: S1
Status: FIXED (core) - is_local_url never raises, malformed address means not configured with a user-facing line, dictation delivers raw text; verified by tests/test_state_manager_failure_outcomes.py. NEEDS handlers - presets.update must refuse a bad address before saving
Where: `app/llm/providers.py:147` (`is_local_url` calls `urlsplit` with no guard), reached through
`Profile.remote` -> `app/server/handlers/presets.py` `_profile_dict`, and `app/state_manager.py:_postprocess_with_llm`.
Steps:
1. Runtime up, post-processing on. `presets.update` with `base_url: "http://[::1:11434"` (a missing bracket; also
   `http://[localhost]:1234`). It answers `internal: Invalid IPv6 URL`, but the value is already in `config.yaml`.
2. Call `presets.get`, `presets.update` with a correct URL, `llm.set_enabled`, `presets.delete`.
3. Dictate a phrase with `llm.enabled: true`.
Expected: the field is refused with a message and nothing is saved; a dictation never depends on how the
address looks (Constitution II: a failing optional step delivers the original text).
Actual: every call in step 2 returns `internal "Invalid IPv6 URL"`, so the screen cannot load and cannot be
repaired from the interface (only by editing `config.yaml`). Step 3: `ERROR app.state_manager: Error processing
recording: Invalid IPv6 URL`; nothing was pasted, no history entry, the fake LLM saw 0 requests. The words are
gone. `presets.privacy`, which the screen calls while the user types, fails the same way on each keystroke
that makes a bad URL. Reproduced 3 times (dev and packaged runtime).
Evidence: `evidence/security/evidence.txt` [SEC-2].
Suspected cause: `ValueError` from `urlsplit` is not an `LLMError`, so the "deliver the raw text" fallback does not
see it; `update` writes before it validates.
Status: Handler side FIXED, NEEDS core for the dictation - the address is validated before saving and read tolerantly, so the Post-processing screen cannot be bricked (see QA-RUNTIME-6; same tests and live repro: a stored `http://[::1` no longer breaks `presets.get`/`update`/`llm.set_enabled`/`delete`; `presets.privacy` answers `{valid: false}` instead of failing). `_postprocess_with_llm` must still fall back to the raw text on any exception (core).

### QA-SEC-3  One undecodable byte in the history file hides all of it, and the next rewrite deletes it; one wrongly typed field kills History
Severity: S1 (likelihood low: needs a damaged or hand-edited file, for example a cut-off Cyrillic character after a kill)
Status: FIXED - tolerant line-by-line load, rejected lines kept byte for byte on rewrite, no rewrite when the file could not be read, append after a cut line; verified by tests/test_history_damaged_file.py
Where: `app/history_manager.py` `load_history` (`read_text(encoding="utf-8")` for the whole file inside one
try), `_compact`; `app/server/handlers/history.py:_entry`.
Steps:
1. History file with two valid lines and a last line ending in half a UTF-8 character (`\xd1`), start the runtime.
2. `history.list`, then `history.restore` (or `history.delete`) of any entry.
3. Separately: one line with `"model": ["x"]` and everything else valid.
Expected: skip the bad bytes or line, keep the rest; never rewrite a file the loader could not read.
Actual: step 2: `ERROR Failed to load history ... can't decode byte 0xd1`, `history.list` returns 0 entries;
after `history.restore` the file contained only the new entry, the two valid dictations were destroyed.
Step 3: `history.list` returns `internal "unhashable type: 'list'"` for the whole screen (and `alias_for` is hit
by export too). Types are not validated on load (`TranscriptionEntry(**json.loads(ln))` only catches missing
keys). Reproduced once per case; both deterministic code paths. The 200000-deep `[[[` line and bad JSON are
handled (skipped).
Evidence: [SEC-3].

### QA-SEC-4  Dictation text and the API key go to the system proxy, even for a "local" address
Severity: S2
Status: FIXED - explicit proxy policy in llm/client.py (`_bypasses_proxy`: loopback, private, link-local, .local never proxied; remote only via the user's environment/OS); verified by tests/test_llm_client_hardening.py with a real listening proxy
Where: `app/llm/client.py:complete` uses `urllib.request.urlopen`, which honours `HTTP_PROXY`/`ALL_PROXY` and the macOS
and Windows system proxy, with no bypass for loopback; `presets.privacy` and the card's privacy line.
Steps: start the runtime with `HTTP_PROXY=http://127.0.0.1:18119`, preset on `http://127.0.0.1:18115/v1` (privacy
line says it stays on this computer), `presets.test` and a real dictation.
Expected: a loopback endpoint is contacted directly.
Actual: the proxy received `POST http://127.0.0.1:18115/v1/chat/completions` with the full JSON body (the user's
words) and the `Authorization` header, 3 of 3 times; the fake LLM got nothing and the test reported
`ConnectionRefusedError` once the proxy was gone. On a machine with a corporate or debugging proxy
(system-wide on macOS, so no env var is needed) the privacy line is false and the proxy operator reads the dictation.
I could not change the system proxy to confirm that path (prohibited), so it is code-evidenced
(`urllib.request.getproxies` reads `_scproxy` on macOS).
Suspected cause: no `ProxyHandler({})` for local hosts.
Status: NEEDS core - `app/llm/client.py` must bypass the proxy for loopback (core has `_bypasses_proxy`); nothing in the handlers builds the request.

### QA-SEC-5  The dictated text is written to stderr
Severity: S3
Status: FIXED - filter in app/server/__main__.py (present in tree) keeps Transcribed off stderr; redaction added for all sinks
Where: `app/server/__main__.py:logging.basicConfig(..., stream=sys.stderr)` has no `_NoSensitiveToFile` filter
(`app/bootstrap.py:330` is attached only to the file handler).
Steps: dictate "..."; read the runtime's stderr (dev and packaged binary).
Expected: Constitution I and spec 008 US4: the words stay in the Logs view only.
Actual: `INFO:app.state_manager:Transcribed: <the phrase, up to 80 chars>` on stderr, 4 of 4 dictations. Electron
keeps the last 60 stderr lines in memory (`backend.cjs` `stderrTail`) and prints all of them with `L2T_DEV`;
a runtime started from a terminal, a launcher or a journal writes them to disk. `app.log` correctly has none.
Evidence: [SEC-6].
Status: FIXED (wiring, not re-run end to end) - the runtime's stderr handler drops `sensitive` records with the same rule as the file handler (`app/server/__main__.py` `_NoSensitive`). No unit test covers it (it is `main()` setup) and I did not run a dictation in my live pass, so the stderr line was not re-observed.

### QA-SEC-6  The API key is sent to the renderer, including the capsule window
Severity: S3
Where: `app/server/handlers/presets.py:_profile_dict` (`presets.get` and every mutating preset call),
`app/server/handlers/core.py:snapshot` (the whole `llm` section: the flat `api_key` and each profile's).
Steps: `presets.get`; `app/snapshot`.
Expected: like the Hugging Face token (`models.hf_token.get` returns only `{"set": bool}`), the key stays in the runtime;
the editor needs "is a key set" and a way to replace it.
Actual: the key in clear text twice in the snapshot and once per preset in `presets.get`; `Overlay.svelte` loads the
snapshot too, so the always-on-top capsule window holds it. With QA-SEC-8 a foreign page gets it.
Evidence: [SEC-6].
Status: FIXED - responses carry `api_key_set` / `token_set`, never the key (`presets.*`, `app.snapshot`, `app/server/redact.py`); `presets.update` takes `api_key` only when a non-empty one is sent, `presets.reset_key` removes it; contracts updated (`rpc-presets.md`, `rpc-core.md`); verified by `tests/server/test_presets.py::test_no_reply_carries_the_key_only_a_flag`, `::test_an_edit_that_does_not_type_a_key_keeps_the_stored_one`, `::test_a_typed_key_replaces_and_reset_key_is_the_only_way_to_remove_one`, `tests/server/test_core_handlers.py::test_the_snapshot_carries_flags_instead_of_credentials`; live repro: planted key absent from every reply and from `app.snapshot`. The renderer has to adopt the new fields (see the report).
Status: FIXED (renderer side) - the editor keeps only `api_key_set`, shows dots as a placeholder, sends `api_key` only when a new one was typed, clears with `presets.reset_key`, and drops a key if an older reply still carries one (`components/presets/model.js`, `views/PostProcessing.svelte`, `LanguageModelCard.svelte`); the capsule reads the snapshot, which no longer holds a key (runtime). Verified by `tests/postprocessing.test.js` ('the API key stays in the runtime', 5 tests) and the repro: Clear removed the key, typing sent it and the field emptied again.
Status: NEEDS runtime - the API key is in the snapshot and `presets.get`; the shell cannot filter the runtime's replies. (shell fixer)

### QA-SEC-7  A password inside the server address is written to app.log, stderr and the Logs view
Severity: S3
Status: FIXED - see QA-RUNTIME-4; verified by tests/test_log_redaction.py
Where: `app/config_manager.py` `_redact_for_log` / `_scrub_secrets` (match key names only, not URL userinfo);
`app/llm/client.py:_safe_url` shows the code knows URLs carry credentials.
Steps: `presets.update` with `base_url: "https://bob:URLPASSWORDCCC@gw.example.invalid/v1"`; grep.
Actual: `Updated setting llm.base_url: ... -> 'https://bob:URLPASSWORDCCC@...'` and the `llm.profiles` line, 2 hits in
`app.log`, 2 on stderr, 2 in `log` events (packaged build). The key redaction itself works (`<set>`).
Note: `urllib` does not use userinfo for auth (the test failed with `InvalidURL`), so this is a leak of
what a user pastes rather than a working feature.
Status: FIXED for new values (see QA-RUNTIME-4); stored values NEEDS core (`_redact_for_log`).

### QA-SEC-8  The app window can be navigated to any `file://` page, which then receives the bridge and the backend token
Severity: S3 (needs a way to navigate the window: an XSS, a dropped link; none found, see Covered)
Where: `desktop/electron/windows.cjs` `will-navigate` handler allows every `file://` URL; the overlay window has no
handler; `desktop/electron/main.cjs` `l2t:connection` does not check the sender.
Steps: in the packaged app, `location.href = 'file:///<scratch>/evilpage/evil.html'`; the page calls `window.l2t.connection()`.
Expected: only the app's own `index.html`/`overlay.html` may load with the preload.
Actual: navigation allowed; the foreign page's title became `L2T-BRIDGE:<port>:32`, i.e. it got `window.l2t`
and the 32-character token. From there it can use the whole RPC surface (start the microphone, read history, read
the API key, write files, QA-SEC-14), quit, or open dialogs. 1 of 1.
Suspected cause: `url.startsWith('file://')`; compare against the exact app URL and set the same guard on the capsule.
Status: FIXED - see QA-SHELL-13: exact page allow-list on every window, no `file://`, the connection is handed only to frames of the app's own windows showing the app's own pages (`guard.cjs`, `main.cjs`; `shell-guard.test.js`, `main-ipc.test.js`). (shell fixer)

### QA-SEC-9  Electron fuses are all at their defaults in the packaged app
Severity: S3
Where: `desktop/electron-builder.yml` (no fuse configuration; no `afterPack`).
Steps: `electron-fuses read --app "release/mac-arm64/Lazy to Text.app"`;
`ELECTRON_RUN_AS_NODE=1 "<app>/Contents/MacOS/Lazy to Text" -e "console.log(...)"`.
Actual: RunAsNode, NodeOptions variable and `--inspect` arguments Enabled; ASAR integrity and
OnlyLoadAppFromAsar Disabled; GrantFileProtocolExtraPrivileges Enabled (the app loads from `file://`). The node-mode
command ran arbitrary JavaScript as the signed app, 1 of 1. The app holds the Microphone entitlement and its Accessibility
grant, so any local process can borrow them through the signed binary.
Expected: RunAsNode, NodeOptions, `--inspect` off; integrity on; OnlyLoadAppFromAsar on.
Status: FIXED - see QA-SHELL-12 (fuses flipped, read back on the rebuilt app; `ELECTRON_RUN_AS_NODE` is ignored). (shell fixer)

### QA-SEC-10  A redirect from the model server forwards the API key to another host
Severity: S3
Status: FIXED - redirects are never followed, only http/https schemes opened; verified by test_a_redirect_is_refused_and_the_key_goes_nowhere_else
Where: `app/llm/client.py:complete` (`urllib` follows 301/302/303 and keeps request headers).
Steps: preset on a server that answers `302 Location: http://localhost:18117/stolen`; `presets.test`.
Actual: the second server received `Authorization: Bearer sk-PLANTED-SECRET-AAA`, 1 of 1 (307 is refused by urllib
for POST; the redirected request is a GET, so the words are not forwarded). A gateway that redirects to another
domain, or a plain-`http` endpoint on a hostile network, gets the key.
Also: no scheme check, so `file://` and `ftp://` base URLs are attempted (blind: only the error type comes back,
nothing readable leaked).
Status: Partly FIXED, NEEDS core - the address must be `http`/`https` with a host and no credentials, so `file://` and `ftp://` are refused at save time and by `presets.test`; the redirect that forwards the key is in `app/llm/client.py` (core: refuse or strip on redirect). Verified by `tests/server/test_presets.py::test_a_malformed_address_is_refused_and_nothing_is_saved[ftp://...]`.

### QA-SEC-11  The post-processing step has no total deadline, so a slow endpoint holds the user's words
Severity: S3
Status: FIXED - see QA-RUNTIME-9
Where: `app/llm/client.py:complete`: `timeout=settings.timeout_s` is per socket operation.
Steps: server that sends one byte per second; `timeout_s: 2`; `presets.test`.
Actual: the test finished after 60.2 s (the server's own end), reply accepted; 1 of 1. A dictation through such an
endpoint stays in the pipeline until the reply ends (the cap is 2 MiB), the text not yet pasted. Constitution II.
Expected: an overall deadline of `timeout_s`, then the raw text is delivered.
Status: Partly FIXED, NEEDS core - `presets.test` has an overall deadline (see QA-RUNTIME-9); the dictation path's deadline is in `app/llm/client.py` (core).

### QA-SEC-12  The loopback server has no read timeout and no connection limit; an unauthenticated local client can stall it
Severity: S3 (any local process; the port is not secret, token not needed)
Where: `app/server/httpd.py` (`ThreadingHTTPServer`, `timeout` unset, one thread per connection, auth checked only after
the request line and headers are read).
Steps: open N idle TCP connections to the port.
Actual: 3000 idle connections: +100 MB RSS; closing them made the process spin at about 970 % CPU for about 8 s with
`/health` timing out, then it recovered (2 of 2 runs). 8000: `/health` answered `Connection reset by peer`.
Connections stayed open without a byte for more than 25 s. During that time the renderer's RPC and events stall.
SSE: no limit on subscribers (each holds a 512-item queue); code-evidenced, behind the token.
SECURITY.md excludes DoS "against your own instance"; this is by another local user or process.
Expected: a socket timeout on reads, a cap on connections.
Status: FIXED - 10 s read timeout on every connection, at most 96 connections and 12 event streams (the rest are closed unanswered), `app/server/httpd.py`; verified by `tests/server/test_hardening.py::test_an_idle_connection_is_dropped_after_the_read_timeout`, `::test_a_burst_of_idle_connections_does_not_starve_the_channel`, `::test_too_many_event_streams_are_refused`; live repro: 3000 idle connections left RSS +4 MB (was +100 MB), no CPU spin after they closed, `/health` answered 0.017 s after the idle ones timed out. Residual: while a local process holds all slots the channel refuses new connections for up to 10 s at a time (a local process can always do that); the per-IP limit is useless on loopback.

### QA-SEC-13  A non-ASCII token makes the handler crash with a traceback
Severity: S4
Status: NEEDS handlers - httpd._token_ok must compare bytes (app/server/httpd.py)
Where: `app/server/httpd.py:_token_ok` (`hmac.compare_digest` on `str` raises `TypeError` for non-ASCII).
Steps: `Authorization: Bearer caf\xe9` or `/events?token=%C3%A9`, no valid token needed.
Actual: empty reply (connection dropped) and a traceback on stderr per request, 2 of 2. Not a bypass; compare bytes instead.
Status: FIXED - the token is compared as bytes, a non-ASCII value is a 401; verified by `tests/server/test_hardening.py::test_a_non_ascii_token_is_a_401_and_the_server_keeps_answering` and live (`Authorization: Bearer caf\u00e9` -> `401`, `/events?token=%C3%A9` -> 401, no traceback).

### QA-SEC-14  `files.save_text`, `history.export` write to any path the user can write, with no check and no confirmation
Severity: S3 (reachable only with the token, see QA-SEC-8)
Where: `app/server/handlers/files.py:save_text`, `app/server/handlers/history.py:export`.
Steps: `files.save_text` to a path that is a symlink to an existing file; `history.export` over an existing file; a relative path.
Actual: both overwrote the symlink target and the existing file (`ORIGINAL` replaced), 2 of 2; a relative path was
written relative to the runtime's working directory (the packaged runtime's cwd is `resources/backend`, inside the
installation directory, which the constitution says nothing writes to). The content is attacker-chosen, so a
page with the token can plant a file such as a LaunchAgent or a shell profile.
Expected: the main process mediates the save dialog and the write, or the runtime accepts only a path returned by a dialog.
Checked and fine: odd file names for `files.transcribe` (QA-SEC covered below), `models.storage.apply` moving into
a subfolder of itself (the copy fails cleanly, source intact).
Status: FIXED - `files.save_text` and `history.export` accept only a full path, a text extension (`.txt .md .markdown .text`), an ordinary file or a new name in an existing folder (no link, folder, pipe, device), outside the app's own folders, and replace the file atomically - `app/server/safe_paths.py`; contracts updated; verified by `tests/server/test_safe_paths.py` (21 tests, among them the symlink, relative path, device and own-folder cases) and live (`ORIGINAL` kept, `rel_out.txt` not created, `.plist` and `logs/x.txt` refused, `ok.txt` written). The main process still does not mediate the dialog (shell area).
Status: NEEDS runtime - the shell now restricts `show-item` to absolute normalised paths and sanitises the save dialog's default path, but the write itself is the runtime's `files.save_text` and `history.export`, which still accept any path; the fix is the one the report names: the runtime accepts only a path that the main process returned from a save dialog (e.g. a one-time grant issued by `l2t:dialog:save-file`), which needs an agreed channel between `main.cjs` and the runtime. Not done in the shell alone. (shell fixer)

### QA-SEC-15  At `logging.level: DEBUG` the file log gets the user's words and the backend token
Severity: S3 (not the default; the level is a documented key of `config.yaml`)
Status: FIXED (core part) - history DEBUG lines carry only a length; verified by test_debug_logging_never_carries_the_dictated_words. NEEDS handlers - httpd.log_message must not log the query string with ?token=
Where: `app/history_manager.py` (`Added history entry: %s`, `Removed history entry: %s` at debug, so the
`sensitive` filter never sees it); `app/server/httpd.py:log_message` logs the request line, which for `/events` holds `?token=`.
Steps: set `logging.level: DEBUG`, restart, dictate, open the event stream.
Actual: `[DEBUG] app.history_manager: Added history entry: <the phrase>` in `app.log` (1 of 1), and
`[DEBUG] app.server.httpd: http: "GET /events?token=<token> HTTP/1.1" 200 -` in `app.log` and on stderr (1 of 1).
The token is only valid until the runtime exits, so the token line is minor; the words line breaks spec 008 US4.
Status: Partly FIXED, NEEDS core - the token no longer reaches any log record (`_scrub` in `app/server/httpd.py`; verified by `tests/server/test_hardening.py::test_the_token_never_reaches_a_log_record`); the DEBUG `Added history entry` line is in `app/history_manager.py` (core).

### QA-SEC-16  Licences that must travel with the package are missing
Severity: S3
Where: `desktop/release/.../Lazy to Text.app` and `desktop/electron-builder.yml`.
Actual (by listing the bundle):
- `imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1` is built `--enable-gpl --enable-libx264 --enable-libx265`
  (run `ffmpeg -version`). It ships inside an MIT application with no GPL text and no source offer.
- The renderer bundles Inter, JetBrains Mono and Source Serif 4 (`dist-renderer/assets/*.woff2`, SIL OFL 1.1). No
  OFL text in the package; the only font licence in the repo is `docs/fonts/LICENSE-jetbrains-mono.txt` for the website.
- No third-party notice for the bundled JavaScript (Svelte, lucide-svelte, `@monos/ui`), no copy of the app's own `LICENSE`.
Fine: `LICENSE.electron.txt`, `LICENSES.chromium.html`, and the Python packages' `*.dist-info/licenses` are present.
Status: FIXED - `THIRD_PARTY_NOTICES.md` (ffmpeg GPL with the configure flags, where the source is and a written offer; the three OFL fonts; Heroicons MIT; Electron and Chromium notices; the Python package summary with pynput's LGPL note) and `desktop/licenses/` (GPL-2.0, the three OFL texts) ship in Resources through `extraResources`, with the repository `LICENSE` (checked in the rebuilt app). `mouseinfo` (GPL-3.0-or-later, from pyautogui) is excluded from the runtime and the build fails if it appears. Tests: `test_the_licences_that_must_travel_are_in_the_package`, `test_the_runtime_leaves_out_what_an_mit_application_cannot_ship`. The GPL text was copied from a local copy of the unmodified licence (libksba's `COPYING.GPLv2`). (shell fixer)

### QA-SEC-17  The bundled `certifi` carries a root CA that has since been distrusted
Severity: S3
Where: `uv.lock` pins `certifi 2026.4.22`; `pip-audit` on `uv export --frozen` reports PYSEC-2026-4320 (fixed in
2026.10.19: the `emSign ECC Root CA - G3` root, with compromised intermediates). It is the trust store for model downloads
and cloud LLM endpoints made with `requests`/`httpx`; the app's own LLM client uses the system store through `ssl` defaults
unless certifi is injected, which I did not check. Other findings from the same run are not reachable in this app:
`anyio` (stderr pipe, IDNA), `filelock` (Windows soft locks, SQLite lock; the Windows instance lock is a mutex),
`fsspec` (Kerchunk templates, unused), `idna` (long labels), `setuptools` (build time).
Not changed, per the brief.
Status: FIXED - `uv.lock` pins certifi 2026.10.23 (`uv lock --upgrade-package certifi`; the same command also moved the project's own entry from 0.1.22 to 0.1.23, which the lock had missed); `test_certifi_is_past_the_distrusted_root`. The runtime in `dist/` was rebuilt before the bump and carries the old version until the next `scripts/build_server.py`. (shell fixer)

### QA-SEC-18  Release workflow: write token for every job, actions on mutable tags
Severity: S3
Where: `.github/workflows/release.yml:21-22` (`permissions: contents: write` for the whole workflow, including the
`build` job that installs the full dependency tree and runs PyInstaller); `actions/*@v7`, `astral-sh/setup-uv@v7`,
`softprops/action-gh-release@v3` (third party, holds the write token) pinned by tag, not SHA; only
`aa-blinov/golden-repo` is pinned by SHA. `dependabot.yml` covers the actions, which reduces but does not remove the risk.
Expected: `contents: write` on the two release-upload jobs only; SHA pins for third-party actions.
`@monos/ui` is pinned by commit in `package-lock.json` (`bda0b03...`), but a git dependency carries no integrity hash.
Status: FIXED - see QA-SHELL-16: `contents: write` only on `publish-qt` and `desktop-release`, third-party actions pinned by commit (`gh api` resolved `astral-sh/setup-uv@v7` and `softprops/action-gh-release@v3`; the GitHub-owned `actions/*` stay on tags, which Dependabot covers). The `@monos/ui` git dependency still has no integrity hash (not changed). (shell fixer)

### QA-SEC-19  Smaller items
Severity: S4, each code-evidenced or seen once
- `desktop/electron/backend.cjs` / `main.cjs`: `L2T_BACKEND_CMD` (runs any command at launch, in a packaged app too),
  `L2T_DEV` (loads `http://127.0.0.1:5173` with the preload, so any local listener on that port gets the bridge),
  `L2T_SCREENSHOT` (writes a PNG and the page text, `<file>.txt`, to a path), `L2T_SELFTEST_*` are live in production.
  They need control of the environment, so low. `startsWith('http://127.0.0.1:5173')` also matches `:51730`.
- No Content-Security-Policy in `index.html`, `overlay.html` or from the main process (no XSS found, so defence in depth).
- CORS reflects any `Origin`, also on `/health` and the token-less `OPTIONS` (any web page can fingerprint the app and its port
  after a port scan). The token still gates everything else; a missing `Access-Control-Allow-Private-Network` keeps current
  Chrome from reaching it from public pages. Allow only the app origin (`null` for `file://`, the Vite origin in dev).
- The token is in the `EventSource` URL (a browser limitation); the main process could use the header.
- `transcription_history.jsonl` and `app.log` are created 0644 (umask) while `config.yaml` is 0600. On macOS `~/Library` is
  0700 so it is covered; on Linux (`~/.local/state`) it depends on the home directory mode. Not tested on Linux.
- Dictations land on the clipboard without the `org.nspasteboard.ConcealedType` hint, so clipboard managers store them.
- `files.transcribe` and `l2t:shell:show-item` accept any absolute path (decode errors and reveal only).
Status: Partly FIXED - CORS no longer echoes an arbitrary `Origin`: a foreign `Origin` is a 403 with no CORS headers, `null`/`file://` are the packaged window's, the Vite origin only with `--dev [--dev-port]` (`tests/server/test_hardening.py::test_a_foreign_origin_is_refused_and_never_echoed`, `::test_the_packaged_origins_get_cors_and_the_dev_server_only_when_asked`; live: `https://evil.example` -> 403, `null` -> 200 + `Access-Control-Allow-Origin: null`, `127.0.0.1:5403` 200 only with `--dev-port 5403`). The `EventSource` token: `app.events_ticket` gives a one-time 30 s ticket for `/events?ticket=`, a POST no longer takes the token from the query string, and the query is never logged (`test_a_ticket_opens_one_stream_and_then_it_is_spent`); the renderer/main process must adopt tickets to stop putting the launch token in a URL. `files.transcribe` now needs a full path to an ordinary readable file. The remaining items of this entry are shell/renderer/core.
Status: PARTLY FIXED (renderer side) - the three pages carry the strict policy (shell) and the built renderer works under exactly that policy: no inline script, no eval, no remote asset, and the one font Vite folded into the CSS as a `data:` URI is now a file (`build.assetsInlineLimit: 0` in `desktop/vite.config.js`, otherwise `font-src 'self'` would have blocked it). Verified by `tests/build.test.js` (builds the real pages and reads them) and by loading the build in the browser under the policy as a header and as a meta tag: all six screens, RPC and the event stream work, an injected inline script does not run. `{@html}` is gone (`tests/contract.test.js`). The event stream now uses a one-time ticket instead of the token in its URL. The rest of the item is the shell's and the runtime's.
Status: FIXED for the shell items - the `L2T_*` hooks are gated (QA-SHELL-14), `startsWith('http://127.0.0.1:5173')` is an exact origin comparison, the pages carry a CSP, the runtime is started with `--allow-origin l2t-app://app` so its origin allow-list lets the window in and nothing else, and the child process gets `ORT_DISABLE_TELEMETRY=1`. NEEDS runtime for CORS on `/health`, the token in the `EventSource` URL, file modes and the clipboard hint (not shell items). (shell fixer)

## Covered, no defect
- Loopback channel: binds `127.0.0.1` only (IPv6 `::1` refused, curl rc 7); token and Host checks: no token, wrong token -> 401;
  `Host: evil.com`, `127.0.0.1.evil.com`, `localhost.evil.com`, `evil.com:18105` -> 403 (so a rebound name cannot reach it);
  constant-time compare; token is 192-bit random per launch; query token on POST accepted but needs the token anyway;
  oversize (> 4 MiB) and zero or invalid `Content-Length` -> 400 before reading; header obs-fold in `Origin` is not an injection.
  A page that cannot read the token can only read `/health`.
- Who can read the token: not in argv or environment of any process of the packaged app (`ps -axwwe`), not in the user-data
  directory, `config.yaml`, `app.log` or the Chromium profile (`grep -r`), not in any RPC reply except `l2t.connection()` in the app windows.
  In dev the `--token` flag is on the command line by design.
- Secrets: `config.yaml` and its temp file are 0600; the HF token is never returned over RPC; change log shows `<set>`/`<empty>`
  for `llm.api_key`, `huggingface.token` and nested `api_key` (profiles); neither planted secret is in `app.log`, stderr, `logs.list`,
  events or the Chromium profile; provider error text (`HTTP 401` with a hostile body containing `<img onerror>` and the key) is
  reduced to `the server answered HTTP 401`; the Electron profile stores nothing (`localStorage` unused).
- The user's words: not in `app.log` at the default level; with post-processing off, 0 requests reached the fake endpoint or the
  proxy and no non-loopback socket was opened by the runtime or its worker (lsof, one dictation); with it on, the one request
  goes to the configured URL only, with the header and body the code builds.
  Privacy line (`presets.privacy`): 28 spoofing tries (`localhost.evil.com`, `127.0.0.1@evil.com`, `evil.com#@127.0.0.1`, IPv4-mapped,
  `0.0.0.0`, decimal and short IPs, trailing dot, userinfo) all agree with where `urllib` connects, apart from malformed brackets
  (QA-SEC-2); odd forms such as `127.1` and `localhost.` are called remote (the safe direction).
- Injection: Svelte escapes everything I fed it: `<img onerror>`, `<script>`, `javascript:` links, `<svg onload>` and a 20000-character
  string in history text and model, and in a preset name and model: 0 elements injected, `window.__xss` never set (History, Logs,
  Post-processing, Models, Settings, 5 screens). The only `{@html}` renders a static i18n key.
  Command injection: `files.transcribe` on files named `-evil.wav`, `a; touch PWNED1; .wav`, `$(touch PWNED2).wav`, backticks, a newline,
  `-i evil;touch PWNED4.m4a` (ffmpeg is called with a list and `-i` first): 9 of 9 transcribed, no marker file created.
  YAML: `yaml.safe_load` only; a `!!python/object/apply:os.system` config did not execute, the file was moved to `config.yaml.corrupt-1`.
  No `pickle` outside the parent-child pipe of the worker. `presets.test` to `169.254.169.254`, `127.0.0.1:22`, the runtime's own port:
  only the error type is returned; 2 MiB reply cap held (`the reply was too large to be text`); not JSON replies are not echoed.
- `models.storage.apply` with a destination inside the source: copy fails, source intact, no recursion.
- Electron: `sandbox`, `contextIsolation` on, `nodeIntegration` off, `require` and `process` undefined in the page; the preload exposes
  only named capabilities; `openExternal` accepts only `http(s)` (file, javascript, custom scheme, ssh, smb all `false`); quit from the page exits cleanly
  and stops the runtime. No non-loopback socket from any Electron or runtime process in 12 s idle with no model (packaged app).
  `entitlements.mac.plist` (Developer ID) omits `disable-library-validation`, the local variants carry it, as designed.
- No network at start with the model cached: a logging proxy saw 0 requests from the runtime (HF hub honours the proxy).
  (The ORT connection of QA-SEC-1 does not honour it.)
- Supply chain: `npm audit` is 0 with `--omit=dev`; the 16 findings (13 moderate, 1 high `vite`, 2 critical `vitest` and `tinypool`) are all
  in the build and test tooling (dev server, test runner), none in the shipped renderer or Electron itself.
- `.github` workflows: `permissions: contents: read` on the others; no secrets referenced beyond `GITHUB_TOKEN`; `pull_request_target` unused;
  `uv sync --frozen` and `npm ci`.

## Not tested, and why
- Windows and Linux: no machine. Windows named mutex, `%APPDATA%` permissions, PowerShell packaging, `xdg-open`, Linux file modes untested.
- The content of the Microsoft telemetry payload (native TLS, no proxy hook, no root); only its existence, destination, files and the switch that stops it.
- The system-wide macOS proxy path of QA-SEC-4 (changing system settings is not allowed); shown with `HTTP_PROXY` only.
- Auto-paste and `preserve_clipboard` (a keystroke would go into the user's focused window); the Accessibility and Microphone permission banners.
- Electron `will-navigate` with a user drag of a link or file (the window-wide `drop` handler calls `preventDefault` for files; I did not drive a real drag).
- A real cloud endpoint over TLS, certificate validation behaviour of the LLM client, `https` downgrade through a redirect.
- Authenticated SSE flooding and memory growth, large authenticated bodies (up to the 4 MiB cap), many concurrent RPCs.
- The Qt interface; the notarisation and signing chain beyond the entitlement files; GitHub-side settings (branch protection, secrets, environments).
- The built `release/` app may differ from HEAD; I tested the dev tree and that build, and they agreed on every finding that touches both.

## Ranked summary
1. QA-SEC-1 (S1) onnxruntime phones Microsoft on every model load; fix: set `ORT_DISABLE_TELEMETRY=1` before the first import of onnxruntime in the server, the worker and the Qt app, and add a test that no device id is written.
2. QA-SEC-2 (S1) a mistyped server URL bricks the Post-processing screen and drops the next dictation; guard `is_local_url`, validate before saving, treat any exception in the step as a fallback to the raw text.
3. QA-SEC-3 (S1) history: tolerate bad bytes and bad types per line, never rewrite a file that did not load.
4. QA-SEC-4 (S2) bypass the proxy for loopback and local addresses; the privacy line is otherwise untrue.
5. QA-SEC-8, 9, 6, 14 (S3) Electron: exact navigation allow-list, flip the fuses, stop sending the API key, mediate file writes. These four decide what a compromised page can do.
6. QA-SEC-5, 7, 15 (S3) sinks that bypass the "no words, no credentials in logs" rule: stderr, URL userinfo, DEBUG.
7. QA-SEC-10, 11, 12 (S3) LLM client redirect and deadline, loopback server timeouts.
8. QA-SEC-16, 17, 18 (S3) licences to ship, `certifi` bump, workflow permissions and pins.
9. QA-SEC-13 and QA-SEC-19 (S4).

File: `/Users/justcomex/Documents/Проекты/pet/lazy-to-text/.claude/worktrees/llm-reasoning-tokens-config-624055/specs/010-electron-interface/qa/security.md`
Evidence: `/Users/justcomex/Documents/Проекты/pet/lazy-to-text/.claude/worktrees/llm-reasoning-tokens-config-624055/specs/010-electron-interface/qa/evidence/security/`
