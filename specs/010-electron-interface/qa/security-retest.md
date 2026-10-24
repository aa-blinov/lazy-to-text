# QA re-test: security and privacy

Tester: security (re-test). Date: 2026-10-24. Platform: macOS 26 arm64 only.

What I ran: a copy of the current `app/` in a scratch tree (own `config.yaml`, logs, models, `HOME`) on port 18305; the PyInstaller
runtime shipped in `desktop/release/mac-arm64/Lazy to Text.app` (built 14:05 today, after the fixes) on 18305 with a scratch `HOME`;
the packaged Electron app with `--remote-debugging-port=18365`, `--l2t-selftest`, a scratch `--user-data-dir` and scratch `HOME`.
Helper servers (fake model endpoint, redirector, slow-drip, big/hostile/empty replies, a logging "proxy") on 18351-18360. Planted
secrets as before: `sk-PLANTED-SECRET-AAA`, `hf_PLANTEDTOKENBBB`, `URLPASSWORDCCC`. Dictations went through the real microphone.
Scripts and raw output: `evidence/security-retest/` (`evidence.txt` is the log of what each repro printed).

Side effects, all mine and none undone except where stated:
- My first dictation had auto-paste on: one keystroke pasted the text "CLEANED" into whatever window had focus. After that I turned it off.
  The system clipboard was overwritten by dictation results (the app copies even with auto-paste off) and holds a scratch phrase now.
- The microphone also picked up speech from other testers' sessions, so two history entries in my scratch tree are not what I said.
- Launching the packaged binary with `ELECTRON_RUN_AS_NODE=1` starts a normal app instance now (that is the fix); I used a scratch profile/HOME
  and killed it. I also killed the instances I started for the hooks and asar tests. Other testers' processes were left alone.
- I wrote `.txt` files into `/Applications` and into the app bundle's `Resources` to test QA-SEC-14, and deleted them;
  `codesign --verify --deep --strict` passes on the bundle afterwards. A 492 MB copy of the app used for the asar tamper test was deleted.
- Nothing is running and nothing under the repo was edited apart from `qa/`.

## Result per defect

Retest: PASS means the original repro, run by hand against the current code, no longer reproduces. The evidence line says what I ran.

| ID | Retest | Evidence |
| --- | --- | --- |
| QA-SEC-1 telemetry | PASS | Waited 32 s with `lsof`. `ortprobe.py` alone: device id and an ESTABLISHED TLS socket to Microsoft. With `import app.privacy_env`, and with only `import app.backends.onnx_backend`: no device id, no database, no socket (`ORT_DISABLE_TELEMETRY=1` in the environment). The dev runtime (I set no variable) and the packaged runtime, each with a model loaded, 25 to 36 s, runtime plus both children: no non-loopback socket, no Microsoft folder in `HOME`. The shell's own `ORT_DISABLE_TELEMETRY=1` is a second layer. |
| QA-SEC-2 bad server URL | PASS | `presets.privacy` and `presets.update` refuse `http://[::1:11434`, `http://[localhost]:1234`, `ftp://`, `file://`, userinfo, `http://`, control characters, with a message and nothing saved. With the bad value hand-edited into `config.yaml`: `presets.get`, `presets.update`, `llm.set_enabled` work, and the dictation delivered the raw text (history entry, warning in the log). |
| QA-SEC-3 history | PASS | File with two valid lines, a `"model":["x"]` line, a wrong-types line and a last line cut after `0xd1`: `history.list` returns the entries, no exception; `history.delete` rewrote the file and the two unreadable lines are still in it byte for byte. Minor: the `["x"]` line is accepted with `model` coerced to `""`, so that one field is lost on rewrite. |
| QA-SEC-4 proxy | PASS | Runtime started with `HTTP_PROXY`, `http_proxy`, `HTTPS_PROXY`, `ALL_PROXY` pointing at a listener. `presets.test` to `127.0.0.1` and `localhost`, and a real dictation: the model server was reached directly, the listener saw nothing (dev and packaged). Control: a `.invalid` host did go to the proxy (remote hosts follow the user's proxy by design), a 192.168 address went direct. |
| QA-SEC-5 words on stderr | PASS | Dictations in the dev and packaged runtime: no `Transcribed:` line and none of the words in stderr or `app.log`. |
| QA-SEC-6 API key to the renderer | PASS | Planted key and HF token: 0 occurrences in the replies of `presets.*`, `app.snapshot`, `settings.get`, `logs.list`, `app.last_events`, `models.*`, `history.list`, `files.results`, nor in the event stream. Same from the Electron page through its own bridge. Replies carry `api_key_set` / `set`. |
| QA-SEC-7 URL password in logs | PASS | New value refused. A password hand-edited into the stored address: `app.log`, stderr, event stream, `logs.list`: 0 hits; the change log shows `http://<redacted>@...`; the test and the dictation refuse it with a message. |
| QA-SEC-8 navigation to file:// | PASS | Packaged app: `location.href` to `file://`, `http://`, `https://`, `data:`, `javascript:`, the splash page, another host, `blob:` in the main window and in the capsule: no navigation; `window.open` returns null. Forcing a foreign `file://` page into the window through the DevTools protocol (which skips `will-navigate`): the page does get `window.l2t`, but `connection`, `backend.restart`, `shell.openExternal` and `dialog.saveFile` all reject with `Not allowed.` See QA-SEC-R5. |
| QA-SEC-9 fuses | PASS | `@electron/fuses read --app`: RunAsNode, NodeOptions variable, `--inspect` arguments and file-protocol privileges Disabled; ASAR integrity and OnlyLoadAppFromAsar Enabled. `ELECTRON_RUN_AS_NODE=1 ... -e "writeFileSync(...)"`: no file, a normal instance started. A flipped byte in `app.asar`'s header: `FATAL ... Integrity check failed for asar archive entry '<header>'` and exit. |
| QA-SEC-10 redirect | PASS | A 302 to another host: "the server answered HTTP 302 (a redirect; redirects are not followed)", the second server saw 0 requests (key not forwarded). `file://` and `ftp://` base URLs refused before any request. |
| QA-SEC-11 total deadline | PASS | Server sending one byte per second, `timeout_s: 2`: `presets.test` ended at 2.0 s; a real dictation had its raw-text history entry 2.5 s after Stop. A blackhole address: 2.0 s. |
| QA-SEC-12 idle connections | PASS | 3000 idle connections: RSS 224 to 228 MB (was +100 MB), all closed by the server within 12 s, CPU peak 0.8 % afterwards (was 970 %), `/health` answers at once. Oversize and malformed bodies: 400 without reading (4 MiB+1, 10^12, -1, chunked), a valid 4 MiB body 200, header flood 431. Slowloris is a different case and does stall it: QA-SEC-R1. |
| QA-SEC-13 non-ASCII token | PASS | `Authorization: Bearer caf\xe9` gives 401 and no traceback (none in the whole run). |
| QA-SEC-14 file writes | PASS (residual in QA-SEC-R2) | Symlink, fifo, folder, relative path, `~`, `.plist`, no extension, `.txt.sh`, the app's own folders (dev layout and the packaged `Application Support`, `Logs`, `models`) are refused; a new `.txt` is written atomically. The chain that mattered (plant a LaunchAgent or shell profile) is closed. The original "Expected" (the main process mediates the dialog) is not what was built: the runtime still trusts any path with a text extension. |
| QA-SEC-15 DEBUG logging | PASS | `logging.level: DEBUG`, one dictation, event stream open: the history line is `Added history entry (43 characters)`, the stream line is `GET /events?ticket=<hidden>`; no words, no token in `app.log` or stderr. |
| QA-SEC-16 licences | PASS | The packaged app has `LICENSE`, `THIRD_PARTY_NOTICES.md` (ffmpeg GPL with configure flags and a source offer, three OFL fonts, Svelte, lucide, `@monos/ui`, Electron and Chromium, Python summary), `licenses/GPL-2.0.txt` and the three OFL texts, `LICENSE.electron.txt`, `LICENSES.chromium.html`. No `mouseinfo` in the runtime. |
| QA-SEC-17 certifi | PASS | `uv.lock` pins 2026.10.23; the bundled `cacert.pem` (the built runtime already has the bump) has no `emSign ECC Root CA - G3`. |
| QA-SEC-18 workflows | PASS | `contents: read` at the top of every workflow, `write` only in `desktop-release` and `publish-qt`. `gh api` resolves `astral-sh/setup-uv@v7`, `softprops/action-gh-release@v3` and `aa-blinov/golden-repo@v1.0.13` to exactly the pinned SHAs. GitHub's own `actions/*` stay on tags (Dependabot covers them). `npm audit`: 0 with `--omit=dev`, 16 in dev tooling, unchanged. |
| QA-SEC-19 smaller items | FAIL | Fixed and re-verified: the `L2T_*` hooks (with `L2T_BACKEND_CMD`, `L2T_SCREENSHOT`, `L2T_DEV`, `L2T_SELFTEST_X` in the environment and no `--l2t-selftest`, nothing ran), CSP on all four pages, exact dev origin, foreign `Origin` 403 with no CORS headers, `l2t-app://app` allowed, the renderer's stream uses one-time tickets, `files.transcribe` needs a full path. Still open: `Origin: null` and `file://` are still accepted with CORS headers (QA-SEC-R3); `/events?token=` still accepted; `app.log` and `transcription_history.jsonl` are 0644 (`~/Library` is 0700 here, so macOS is covered, Linux not tested); dictations still go on the clipboard without the concealed-type hint. |

## Checks that came back fine (new coverage beyond the original repros)

- Ticket endpoint: first use 200, second 401, expired after 31 s 401, empty or non-ASCII 401, a ticket never opens `/rpc`, minting needs the token,
  a request refused for its `Origin` does not spend the ticket, 70 more tickets evict the oldest (authenticated callers only).
- `l2t-app://` scheme handler: `..`, `%2e%2e`, `..%2f`, `%5c`, `%00`, `%252e`, `//`, `/assets/` and the directory root all answer an empty 403 or 404 page; nothing outside the renderer build is
  served (`splash.html` and `splash.js` are, by design). I navigated through the DevTools protocol because the page's own CSP (`connect-src http://127.0.0.1:*`) blocks `fetch` to the scheme.
- Error text: `presets.test` replies reduce a hostile 401 body to `HTTP 401`, a 2 MB reply to "too large to be text", a non-JSON reply to "not JSON", an empty reply to "no text";
  `files.transcribe` on `/etc/passwd`, a fake wav, a fifo, `/dev/zero`: only "may be damaged", no content. Internal errors say the exception type only.
- Electron: no `require`/`process` in the page, microphone denied in the page, `localStorage` empty, the launch token is in no process's argv or environment and not in the profile.
- `presets.update` clamps `timeout_s` to 600 and `max_tokens` to 32768; `custom_prompt` over 20000 and `name` over 80 characters are refused.

## New defects

### QA-SEC-R1  A trickle of bytes holds the loopback channel down for as long as it lasts
Severity: S3 (any local process, no token; the fix for QA-SEC-12 closes the idle case, not this one)
Where: `app/server/httpd.py`: `_Handler.timeout = 10` is a limit per socket read, `_MAX_CONNECTIONS = 96`.
Steps: 1. `evidence/security-retest/slow.py`: open 110 connections, send `POST /rpc HTTP/1.1\r\nHost: 127.0.0.1\r\nX-a: ` on each, then one byte every 5 s.
2. Probe `/health` every 5 s.
Expected: a request that has not finished its headers in a few seconds is dropped, whatever it is sending.
Actual: every probe in 40 s was `Connection reset by peer` or `RemoteDisconnected`; the channel answered again at once when the script closed. The renderer's RPC and events stall for the whole time. 1 run; deterministic by construction.
Suspected cause: the timeout restarts at every received byte; there is no deadline for the whole request.
Status: FIXED - `app/server/httpd.py`: the whole request (line, headers, body) has an 8 s deadline enforced by a reaper thread that cuts the socket, so a byte every few seconds no longer extends it; with all 96 slots taken the connection that has waited longest for its request is shed to make room for the next caller instead of refusing it (all clients are one loopback address, so a per-IP cap would add nothing); a running call or event stream is never shed; verified by `test_a_request_that_is_still_arriving_after_the_deadline_is_cut`, `test_a_slow_request_does_not_take_the_slot_of_the_next_caller` and `test_110_trickling_connections_do_not_take_the_channel_down` (8 `/health` probes over 3 s with 110 trickling connections, all 200; fails on the old channel with 8 of 8 failures).

### QA-SEC-R2  The write checks still allow the installation directory and any existing `.txt`/`.md`, with no confirmation
Severity: S3 (needs the token, so a compromised page; the LaunchAgent scenario of QA-SEC-14 is closed)
Where: `app/server/safe_paths.py`, `files.save_text`, `history.export`.
Steps: packaged runtime, `files.save_text` with `path` = `<app>/Contents/Resources/zz-probe.txt`, `.../backend/zz-probe.txt`, `/Applications/x.txt`, `<HOME>/Library/Caches/LazyToText/x.txt`, and an existing `victim.txt`.
Expected: the constitution says nothing writes into the installation directory; an overwrite of an existing user file is confirmed by a dialog the page cannot fake.
Actual: all five written (2 of 2 runs); `victim.txt` replaced silently, also through a path with `..` and one whose parent folder is a symlink. A file added inside the signed bundle would be unsealed; I did not measure that.
Suspected cause: the policy is a denylist of the app's own data folders plus an extension allowlist, with no dialog grant behind it (the report's "Expected").
Status: renderer side FIXED - `files.save_text` and `history.export` are called with `overwrite: true` after the operating system's save dialog returned the path (the dialog asked about replacing), and a refusal is shown with the runtime's sentence (`exists`, `bad_path`), translated; verified by `tests/transcribe.test.js` ('passes overwrite ...') and `tests/history.test.js` (export call). The runtime half is the Python fixer's; the contract now lists `overwrite`.
Status: FIXED (runtime side) - `app/server/safe_paths.py`: refuses the interpreter's folder (and the whole `.app` around it), PyInstaller's `_MEIPASS`, the `app` package, any folder named `*.app`, `/Applications`, `/Library`, `/System`, `/usr`, `/bin`, `/sbin`, `/etc` and the Windows Program Files / ProgramData / Windows folders; an existing file is replaced only with `overwrite: true`, otherwise error `exists` (`files.save_text`, `history.export`; the check is on the resolved path, so `..` and a linked folder do not hide it); verified by `tests/server/test_safe_paths.py` (`test_an_existing_file_is_not_replaced_unless_the_caller_says_so`, `test_a_path_through_dots_or_a_linked_folder_is_still_an_existing_file`, `test_the_applications_own_installation_is_refused`, `test_the_system_roots_are_refused_before_anything_is_touched`, ...). The renderer already sends `overwrite: true` (`lib/history.js`, `lib/transcribe.js`); the packaged build was not rebuilt or re-probed here.

### QA-SEC-R3  The runtime still answers `Origin: null` and `file://` although the window is `l2t-app://app`
Severity: S4
Where: `app/server/httpd.py` `_PACKAGED_ORIGINS = ("null", "file://")`, always in the allow-list.
Steps: `curl -i -H 'Origin: null' http://127.0.0.1:<port>/health`.
Expected: only the origins the shell names with `--allow-origin`.
Actual: 200 with `Access-Control-Allow-Origin: null`; `null` is also the origin of every sandboxed iframe, `data:` page and `file://` page on any web site, so such a page that finds the port can read `/health` and preflight `/rpc`. The token still gates everything else. 3 of 3.
Suspected cause: the packaged defaults were not removed when the window moved off `file://`.
Status: FIXED - `_PACKAGED_ORIGINS` is empty; the only origins are the ones the shell names with `--allow-origin` (`l2t-app://app`) and the dev server with `--dev`; `Origin: null` and `file://` get 403 without CORS headers on RPC, `/events`, `/health` and the preflight; verified by `test_the_null_and_file_origins_are_refused_even_with_the_app_origin_named`, `test_only_the_named_origins_get_cors`, `test_a_runtime_started_without_arguments_names_no_origin`; repro re-run on a real runtime: `Origin: null` on `/health` is 403.

### QA-SEC-R4  `presets.test` has no cap on concurrent tests
Severity: S4 (needs the token)
Steps: 300 `presets.test` calls in 0.5 s against a server that never answers, `timeout_s: 30`.
Actual: all 300 accepted, 925 threads in the runtime for the next 30 s (each test starts two); `timeout_s` can be 600. 1 run.
Expected: one test per preset in flight, or a small cap.
Status: FIXED - `presets.test` allows 3 tests in flight; the slot is held until the request thread ends (not until the test gave up waiting), a fourth is `busy`; so at most 6 threads; verified by `test_connection_tests_in_flight_are_capped_and_the_slot_outlives_the_deadline` (20 calls against a server that never answers: 3 accepted, 17 `busy`, and slots return after the thread ends). The new sentence "Too many connection tests are running. Wait for one to finish." has no Russian entry yet (NEEDS renderer: `ru.runtime.json`).

### QA-SEC-R5  The bridge and the restart event reach any page that ends up in a window
Severity: S4 (not reachable today: I could only get a foreign page into the window through the DevTools protocol)
Where: `desktop/electron/windows.cjs:267` (`broadcast` sends to every renderer web contents), `main.cjs:294` (`l2t:backend-restarted` carries `{port, token}`); the preload is attached to whatever the web contents loads.
Observed: a `file://` page forced into the main window had the `l2t` object; every invoke was refused by the sender check. Not observed: the restart event reaching it (my restart call returned the same connection and fired no event). Code-evidenced only.
Suggestion: the broadcast should check each contents' current URL with `guard.isRendererUrl`, like the handlers.
Status: FIXED (shell, 2026-10-24) - `windows.broadcast` and the new `windows.sendToApp` send only to a web contents whose committed page passes `guard.isRendererUrl`; the file-open and navigate sends in `main.cjs` use it too; every handler already goes through `handle()`, which checks the sender frame, and `l2t:connection` is one of them (re-checked: `main-ipc.test.js` "who may call" lists it). Verified by `shell-main-flow.test.js` "does not send the connection or the exit to a window that shows a page that is not the app's" (page forced to `file://`: no exit event, no restart event with the token, `connection` refused; the capsule still gets both).
Status: NEEDS shell - `desktop/electron/windows.cjs` `broadcast` and `main.cjs` restart event; not a runtime change.

### QA-SEC-R6  The launch token is still accepted in the query string of `/events`
Severity: S4
Steps: `GET /events?token=<token>` returns 200 and opens a stream. Nothing in the app uses it any more (renderer: tickets; main process: header); it is scrubbed from logs.
Suggestion: accept only the header and tickets.
Status: NEEDS runtime for the refusal itself. Shell side DONE (2026-10-24): `desktop/electron/events.cjs` no longer sends any token on the stream: it calls `app.events_ticket` with the Authorization header and opens `GET /events?ticket=...`, asks for a new ticket on every reconnect, and uses the header (not a query) only if the runtime answers `unknown_method`; any other ticket failure counts as a lost stream and retries. Tests in `desktop/tests/shell-backend.test.js` against the stub runtime (`STUB_TICKETS=strict|legacy`). QA-SEC-R3: the shell already passes `--allow-origin l2t-app://app`, so removing `null`/`file://` from the runtime needs nothing here; the packaged app and `scripts/smoke.mjs` run against the current runtime and will against the stricter one.
Status: FIXED - `GET /events?token=` is a 401; the stream takes the header or a one-time `?ticket=` (`app/server/httpd.py`); `events.cjs` already asks for a ticket and falls back to the header, and `rpc.js` uses `app.events_ticket`, so nothing in the shell needed to change; verified by `test_the_event_stream_does_not_take_the_token_in_its_url` and the real-runtime check (`/events?token=devtoken` gave 401). A renderer whose ticket request fails now gets a 401 on the stream instead of a token in the URL.

## Not tested, and why

- Windows and Linux (no machine): the mutex, `%APPDATA%`, file modes on Linux, PowerShell packaging.
- The system-wide macOS proxy path of QA-SEC-4; shown with the environment variables only.
- The content of the Microsoft telemetry payload; only its absence (no file, no socket in 25 to 36 s).
- Whether an extra file in the signed bundle breaks `codesign --verify` (QA-SEC-R2); I did not leave one in to see.
- A real drag of a link or file onto the window; the Qt interface; notarisation; GitHub-side settings.
- The renderer's reconnect with a fresh ticket after a stream drop (the one-time rule was tested at the runtime, not through a forced drop in the UI).

## Final table

| ID | Retest |
| --- | --- |
| QA-SEC-1 | PASS |
| QA-SEC-2 | PASS |
| QA-SEC-3 | PASS |
| QA-SEC-4 | PASS |
| QA-SEC-5 | PASS |
| QA-SEC-6 | PASS |
| QA-SEC-7 | PASS |
| QA-SEC-8 | PASS |
| QA-SEC-9 | PASS |
| QA-SEC-10 | PASS |
| QA-SEC-11 | PASS |
| QA-SEC-12 | PASS (R1 is the case it does not cover) |
| QA-SEC-13 | PASS |
| QA-SEC-14 | PASS (R2 is the residual) |
| QA-SEC-15 | PASS |
| QA-SEC-16 | PASS |
| QA-SEC-17 | PASS |
| QA-SEC-18 | PASS |
| QA-SEC-19 | FAIL (null origin, file modes, clipboard hint, token in `/events` query) |

New defects, ranked: R1 (S3, slowloris on the channel), R2 (S3, write checks), R3 (S4, `null` origin), R4 (S4, `presets.test` concurrency), R5 (S4, bridge and restart event reach any page), R6 (S4, token in `/events` query).

Evidence: `/Users/justcomex/Documents/Проекты/pet/lazy-to-text/.claude/worktrees/llm-reasoning-tokens-config-624055/specs/010-electron-interface/qa/evidence/security-retest/`


QA-SEC-14 (shell): the runtime now refuses install directories and requires `overwrite: true`; the shell has nothing to do for it. The shell does not mediate the save path (the renderer asks the shell for a path with `dialog.saveFile`, then the runtime checks it).
