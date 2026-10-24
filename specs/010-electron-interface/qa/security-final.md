# QA final round: security and privacy

Tester: security (final). Date: 2026-10-24. Platform: macOS 26 arm64 only. Build under test: `desktop/release/mac-arm64/Lazy to Text.app`,
rebuilt 16:48 from commit `1ec7d86` (`/private/tmp/claude-501/rebuild.done` said `OK` before I started).

What I ran, all from `/private/tmp/claude-501/sec-final` (own `HOME` per run, own Electron profile, nothing real touched):
- the dev runtime (`python -m app.server`, `--data-dir`, port 18505), for the first pass and for the `--data-dir` cases;
- the packaged runtime `Contents/Resources/backend/lazy-to-text-server` on 18505 (`--allow-origin l2t-app://app`, scratch `HOME`);
- the packaged Electron app with `--user-data-dir`, `--remote-debugging-port=18565`, scratch `HOME`, `env -i`, driven through the DevTools protocol;
- helper servers: a fake OpenAI-style endpoint (18562, logs the `Authorization` header) and a server that accepts and never answers (18561).

Planted values: API key `sk-PLANTED-SECRET-AAA`, HF token `hf_PLANTEDTOKENBBB`, URL password `URLPASSWORDCCC` (hand-edited into the stored
address, because the runtime refuses to take it through the API), the launch token, and the dictated phrase "секретная фраза альбатрос номер семь"
(real microphone through `afplay`, plus `files.transcribe` of the same speech synthesised with `say -v Milena`).

Scripts and raw output: `evidence/security-final/` (27 files; `pkg-*.txt` are the packaged-runtime runs, `sweep*.txt`, `fuzz.txt`, `rpc-replies.txt`,
`events.log` are the secret sweep, `telemetry*.txt` the socket check).

Side effects, all mine unless stated:
- I wrote `zzq.txt` into `/Applications` and `/Users/Shared` while testing the case bypass (F1), and removed both at once; both are gone. Other
  probe files (in the checkout, in the scratch `HOME`) were removed after being accepted.
- Dictations overwrote the system clipboard (auto-paste was off for every packaged run; I turned it off through `settings.set` before the first one).
- Not mine: the dev runtime I started first still had auto-paste on (its default) and the global hotkeys live. Another tester's dictation, started
  with the hotkey, was received by it at 16:55:09 and a paste keystroke went to whatever window was focused. Two of that tester's history entries are in
  my `data-dev` folder. Every runtime listens to the same global hotkeys when the single-instance lock is skipped (`--no-single-instance`), so this is a
  test-setup hazard and not a product defect.
- The disk was at 100 % (3.7 GiB free) for the whole run. I cloned the model with `cp -Rc` and deleted the copies afterwards.
- Processes: I started and killed my own runtimes, three Electron instances, `fake.py`, `hang.py`, the event capture. `pgrep -f sec-final` is empty.
  Other testers' Electron and runtime processes were left alone.

## Result table

PASS means the original repro, run by hand against the rebuilt build, no longer reproduces. Rows marked "carried" were not re-run: the earlier
retest passed them and I spent the time on the failed and new items; where files under them changed I say so.

| ID | Result | Evidence |
| --- | --- | --- |
| QA-SEC-1 telemetry | PASS | Fresh `HOME` and Electron profile, model loaded (`vosk-ru-small`, CPU). `lsof -i` on the whole process tree (8 processes: shell, helpers, runtime, workers) every 0.5 s for 45 s idle and for 42 s more while three files were transcribed: no socket to a non-loopback address, no UDP, no Microsoft folder in `HOME`. `telemetry.txt`, `telemetry2.txt`. |
| QA-SEC-2 bad server URL | PASS (carried) | `presets.py` changed (test cap only). Re-seen: a URL with a password is refused by `presets.update` with "Do not put a user name or password in the address". |
| QA-SEC-3 history | PASS (carried) | |
| QA-SEC-4 proxy | PASS (carried) | |
| QA-SEC-5 words on stderr | PASS | Packaged runtime, stderr kept: 94 lines, none with the phrase or a recognised word after two dictations and a file; `app.log` 0 hits. `sweep` section below. |
| QA-SEC-6 API key to the renderer | PASS | `rpc-replies.txt` (14 methods incl. `presets.get`, `settings.get`, `app.snapshot`, `logs.list`, `models.*`, `history.list`): 0 occurrences of the key, the HF token or the launch token. 34 hostile calls (secret in the wrong type, in an id, in a method name): the only echoes are the caller's own text coming back in "no such preset/model/method" (not stored values). The key reached only the configured fake endpoint as `Bearer`. See F5 for the URL password. |
| QA-SEC-7 URL password in logs | PASS | Password in the stored address: dictation and test both refuse ("the server address contains a user name or password"), `app.log` (DEBUG), stderr, events, `logs.list`, Electron profile: 0 hits. |
| QA-SEC-8 navigation to file:// | PASS (carried) | Re-seen with `windows.cjs` changed: a `file://` page forced into the main window through the DevTools protocol gets `window.l2t` and every call (`connection`, `backend.restart`, `dialog.saveFile`, `shell.openExternal`) rejects with `Not allowed.` See R5. |
| QA-SEC-9 fuses | PASS (carried) | |
| QA-SEC-10 redirect | PASS (carried) | |
| QA-SEC-11 total deadline | PASS (carried) | |
| QA-SEC-12 idle connections | PASS | With the reaper in: 500 idle connections held open, runtime 112 threads while they lasted, 17 ten seconds later, 16 after close (baseline 16); descriptors 59 before and 59 after a 300-connection trickle. `/health` 200 throughout. |
| QA-SEC-13 non-ASCII token | PASS (carried) | |
| QA-SEC-14 file writes | PASS | The LaunchAgent / shell-profile chain stays closed (extension allowlist, links, folders, fifos, app folders in exact case). See F1 and F2 for what is still open around it. |
| QA-SEC-15 DEBUG logging | PASS | `logging.level: DEBUG` through four dictations and the event streams: lines are `Added history entry (N characters)` and `GET /events?ticket=<hidden>`; no words, no token. |
| QA-SEC-16 licences | PASS (carried) | |
| QA-SEC-17 certifi | PASS (carried) | |
| QA-SEC-18 workflows | PASS (carried) | |
| QA-SEC-19 smaller items | FAIL | Fixed and re-verified: hooks (`L2T_BACKEND_CMD`, `L2T_SCREENSHOT`, `L2T_DEV`, `L2T_SELFTEST*` in the environment: no file, no command), CSP meta on `index.html` and `overlay.html`, `Origin: null` and `file://` refused, `/events?token=` refused, ticket-only streams. Still open, unchanged: `app.log` and `transcription_history.jsonl` are created 0644 (F4), and dictations go on the clipboard without a concealed-type hint (no `ConcealedType` anywhere in `app/` or `desktop/electron/`, no WON'T FIX line). |
| QA-SEC-R1 slowloris | PASS | 110 connections, one byte every 5 s, 40 s, packaged runtime: `/health` 16/16 and an authenticated `app.snapshot` 16/16, 0.00 s each (the retest had a reset on every probe). Harder variants all clean: 400 connections that reconnect when cut and send a byte every 0.3 s (10/10), 200 connections trickling a body under a valid token (8/8), 150 trickling a GET (8/8), 500 half-open POSTs at once with an event stream held: the stream still delivered an event, `/health` 200. Dev and packaged runtimes both. `pkg-slow.txt`. |
| QA-SEC-R2 save path and overwrite | FAIL | The original five paths are refused or need `overwrite` (installation, `/Applications`, `<HOME>/Library/Caches/LazyToText`, existing `victim.txt`: `exists` without the flag; `..` and a linked parent still `exists`; a symlink file refused). But the deny-list compares case-sensitively on a case-insensitive volume: `/applications/x.txt` is written (F1), and the "main process mediates the save dialog" expectation is not built: `overwrite` is whatever the caller says (F2). |
| QA-SEC-R3 `Origin: null` / `file://` | PASS | Packaged runtime: `/health`, `/rpc`, the preflight and `/events` answer 403 with no CORS headers for `null`, `file://` and a foreign origin; `l2t-app://app` gets 200/204 and `Access-Control-Allow-Origin: l2t-app://app`. From the renderer, a `fetch` with that origin works. `pkg-channel.txt`. |
| QA-SEC-R4 `presets.test` cap | PASS | 300 calls in parallel against a server that never answers: 3 `ok`, 297 `busy`; threads 15 before, 24 during, 14 after 35 s; the next test is accepted again. Dev and packaged. The new sentence is in `ru.runtime.json`. `pkg-cap.txt`. |
| QA-SEC-R5 bridge and restart event | PASS | Packaged app. A `file://` page forced into the main window (it hooks `onRestarted`, `onExit`, `onBackendExit`); runtime killed, then restarted from the capsule: the capsule received `exit` and `restarted` (`port,token`), the foreign page received nothing, and its `connection`, `restart`, `saveFile`, `openExternal` all rejected. The main window recovered with `Page.navigate` back to `l2t-app://app/index.html`. 1 run. |
| QA-SEC-R6 `/events?token=` | PASS | 401 on dev and packaged, with and without an `Origin`. Header and one-time ticket work. In the packaged app with DEBUG on, every stream line in `app.log` is `GET /events?ticket=<hidden>` (three after launch: main process, window, capsule; three more after each restart) and none is token-bearing, so both the renderer and the Electron main process use tickets. |

## Secret-planting sweep (end to end, packaged)

Where I looked, counts of the planted key / HF token / URL password / launch token, and of the phrase:

| Place | Secrets | Phrase |
| --- | --- | --- |
| `app.log` (DEBUG, 437 lines, four dictations, tests, a file) | 0 | 0 |
| runtime stderr (standalone packaged run, 94 lines) | 0 | 0 |
| Electron main process stdout/stderr | 0 | 0 |
| `logs.list` reply | 0 | 8 (by design: the Logs view shows what was just recognised) |
| event stream (449 lines) | 0 | 3 (`log`, `delivery`, `file.done`; same reason) |
| 14 RPC replies (`rpc-replies.txt`) | URL password 2 (F5), others 0 | 1 (`history.list`) |
| Electron user-data dir (`profile`, `profile2`) | 0 | 0 |
| everything else under the scratch `HOME` | only `config.yaml` (0600, by design) | only `transcription_history.jsonl` (by design) |
| argv and environment of the 8 Electron/runtime processes | launch token 0 | n/a |

The key was sent only to the endpoint the preset names (`Bearer sk-PLANTED-SECRET-AAA` three times in the fake server's log). With the password in
the stored address, the dictation delivered the raw text and said why.

## New defects, ranked

### QA-SEC-F1  The "installed application or system" check is case-sensitive; one changed letter writes into `/Applications`
Severity: S3 (needs the token; a text file only; the fix for R2 is defeated by a letter)
Where: `app/server/safe_paths.py` `installation_folders()`, `protected()`, `_inside()` (`Path` equality and `parents`, no case folding).
Steps: 1. Packaged runtime on 18505. 2. `files.save_text` with `path` = `/applications/zzq.txt`, `text` any.
3. Same with `/APPLICATIONS/zzq.txt`, `<HOME>/Library/Application Support/LAZYTOTEXT/zzq.txt`, `<HOME>/Library/logs/lazytotext/zzq.txt`,
`<HOME>/library/caches/lazytotext/models/hub/zzq.txt`; in a dev checkout `<repo>/APP/zzq.txt`.
Expected: refused like `/Applications/zzq.txt` (`bad_path`).
Actual: `{"saved": "/applications/zzq.txt"}` and the file exists in `/Applications`; the other four (and `APP/`) are written too (the second `/APPLICATIONS` call answered
`exists` because the first had created it). 2 of 2 runs. `/library`, `/system` answer `Permission denied` and `Operation not permitted` from the OS, not from the check.
Held: a bundle itself (`LAZY TO TEXT.app`, `lazy to text.APP`, a differently cased parent folder) is still refused, because the `.app` rule lower-cases the name.
Evidence: `evidence/security-final/pkg-save.txt`; dev run in my notes above.
Suspected cause: macOS and Windows volumes are case-insensitive by default; compare with `os.path.normcase` / `samefile`, or resolve through the real on-disk spelling.
Status: FIXED - see QA-RUNTIME-F4: case-folded and `samefile` comparison, `/applications/x.txt`, `/APPLICATIONS/...`, `<repo>/APP/...` are refused; verified by `test_the_system_roots_are_refused_whatever_the_case` and `test_the_apps_own_folders_are_refused_whatever_the_case`.

### QA-SEC-F2  `overwrite` is a flag the caller sets, so it is not a confirmation
Severity: S4 (needs the token)
Where: `files.save_text`, `history.export`, and the shell: `l2t:dialog:save-file` returns a path but grants nothing.
Steps: 1. Create `work/victim.txt`. 2. `files.save_text` `path` = it: `exists`. 3. Same with `"overwrite": true`: `{"saved": ...}` and the content is replaced; also through a `..` path.
Expected: the R2 text asks for an overwrite "confirmed by a dialog the page cannot fake".
Actual: the runtime cannot tell a dialog answer from a call that says `true`. The accident case is closed; a page that holds the token can replace any existing `.txt` or `.md` the user owns. 1 run.
Suggested: the main process remembers the path the save dialog returned and the runtime (or the shell) accepts `overwrite` only for that path. Not done and not marked WON'T FIX.
Status: WON'T FIX (documented) - the runtime cannot tell a dialog's answer from a call that says `true`; `contracts/rpc-transcribe-history.md` now says the renderer sets `overwrite` only after the native dialog and that the flag stops accidents, not a token holder. A real binding of `overwrite` to the dialog's path needs the shell: NEEDS shell - `l2t:dialog:save-file` would remember the path it returned and the runtime would accept `overwrite` only for it.

### QA-SEC-F3  `--data-dir`: a file as the value is a traceback, an empty value is silently ignored, a read-only folder starts and drops every save
Severity: S4 (development and test option, not passed by the shell)
Where: `app/server/__main__.py`, `app/utils.py:data_dir_override`, `app/config_manager.py` (`override.mkdir(parents=True, exist_ok=True)`).
Steps (runtime, `HOME` scratch, 9 runs, `dd.py`): `--data-dir <existing file>`; `--data-dir ""`; `--data-dir <dir with mode 555>`.
Actual: the file: exit 1 with `FileExistsError` and a raw traceback, no JSON line on stdout. The empty value: the runtime starts and uses the checkout or the current directory (a `config.yaml` appeared in my working directory), which is how a tester ends up on the real config while believing the flag is on. The read-only folder: ready line printed, then `Error writing configuration ... Permission denied` on every change, logs fall back to `~/Library/Logs`.
Fine: nested new folders, spaces and non-ASCII, a symlinked folder, `..`, a relative path, `~` all work and put `config.yaml` and `logs/` where asked; the config folder and the logs are protected from `files.save_text` as before.
Expected: a one-line refusal for a path that is not a writable folder, and for an empty value.
Status: FIXED - see QA-RUNTIME-F5: file, empty value and read-only folder end the start with exit code 2 and a message.

### QA-SEC-F4  The history and the log are world-readable files; the clipboard has no concealed hint (rest of QA-SEC-19)
Severity: S4 on macOS (`~/Library` is 0700 here), higher wherever the parent folder is shared
Where: `app/history_manager.py`, the log handler setup; `app/clipboard_manager.py`.
Steps: look at `home/Library/Logs/LazyToText/` after a dictation: `app.log` and `transcription_history.jsonl` are `-rw-r--r--` in a `drwxr-xr-x` folder; `config.yaml` is `-rw-------`. With `--data-dir` pointing under a shared parent (such as `/tmp`) the user's dictated words are readable by other local users.
Expected: 0600 for the history, 0700 for the folder (the config already does it).
Status of the other half: no `ConcealedType` / `org.nspasteboard` anywhere, so clipboard managers keep every dictation.
Status: FIXED (files) - `app.log` (also after rotation), the history file (append, compaction, clear) and their folder are `0600`/`0700`; verified by `test_app_log_is_created_owner_only`, `test_the_history_file_is_owner_only_after_every_kind_of_write`. Clipboard concealed hint: not done on purpose, `org.nspasteboard.ConcealedType` means "a password" and a dictation is not one; stated in the contract.

### QA-SEC-F5  A password hand-edited into the stored address comes back to the renderer
Severity: S4 (the API refuses to store one; only a hand-edited `config.yaml` has it)
Where: `presets.get` (and every reply that carries the preset).
Steps: stop the runtime, put `http://user:URLPASSWORDCCC@127.0.0.1:18562/v1` in `llm.base_url`, start it, call `presets.get`.
Actual: `"base_url": "http://user:URLPASSWORDCCC@127.0.0.1:18562/v1"` with `base_url_error` set. The logs redact it correctly; the reply does not. 2 occurrences in `rpc-replies.txt`.
Expected: the reply carries the address with the credential replaced, as the change log does (`http://<redacted>@...`).
Status: FIXED - see QA-RUNTIME-F7.

### QA-SEC-F6  Two new sentences have no Russian entry
Severity: S3 (text; found by lookup, not by seeing the rendered toast)
Where: `app/server/safe_paths.py` ("That folder belongs to an installed application or the system. Choose another place." and "That folder belongs to an installed application. Choose another place."); `app/state_manager.py` ("The recording was too short to transcribe. Speak a little longer before you stop.").
Steps: look both strings up in `desktop/renderer/src/i18n/ru.runtime.json`: no key. The other `bad_path`, `exists` and busy sentences are there.
Actual: a Russian UI shows these in English when a save dialog returns `/Applications/...` or a hotkey is double-tapped. Not rendered here; the second may also reach the screen through a path I did not trace.
Status: FIXED - both folder sentences and the too-short sentence are in `ru.runtime.json`, plus the other dictation-failure sentences the capsule and toast show. Verified by `i18n-runtime.test.js`.
Status: FIXED (runtime part) - the three sentences are in `desktop/renderer/src/i18n/ru.runtime.json` (see NEEDS in the developer report if the renderer fixer replaced the file); the extension list joined with an English "or" is the renderer's substitution (NEEDS renderer).

## Covered, no defect

- Ticket endpoint (packaged): first use 200, reuse 401, expired after 31 s 401, empty, `%00`, non-ASCII and garbage 401, a duplicated `ticket` parameter uses the first, a ticket does not open `/rpc`, minting needs the token (401 with a bad one), a refused origin spends nothing. 70 further tickets push the first out (an authenticated caller can do that; it has the token already). 300 garbage tickets against 64 pending: 0.05 s, no stall. Stream cap is 12: streams 13 to 15 answer 503, `/health` and `/rpc` stay up, and a slot is free again within 2.5 s of closing. A 40 s idle stream stayed open.
- Reaper: no descriptor or thread leak after the floods (above); an idle keep-alive connection is cut at about 8 s (a reused connection at 8.3 s gets a reset; at 7.9 s it works). Not a defect: browsers and Node retry or do not reuse a socket that long, and the old timeout was 10 s.
- `--data-dir` and L2T_DATA_DIR: see F3; the worker process inherits the variable.
- Hooks, token not in argv or environment of any of the 8 processes, none of the token in the profile or `HOME`.
- Error text: the new messages (`exists`, `bad_path`, `busy`, model-load reason, `write_failed` "Permission denied.") carry no path, no key, no server body; internal errors name the exception type only; no traceback in `app.log` or stderr after 34 hostile calls.
- Model-load failure reason is now one fixed sentence; the runtime's own text stays in the log.

## Not tested, and why

- Windows and Linux (no machine): file modes on Linux, the mutex, `%APPDATA%`.
- A real save dialog and a real drag onto the window; I called `files.save_text` directly with the dialog's possible outputs.
- The reconnect of the renderer's stream after a forced drop in the UI; I saw it re-open with a fresh ticket after a runtime restart (DEBUG log), not after a socket cut.
- `spctl` / notarisation; GitHub-side settings; QA-SEC-2 to 4, 8 to 11, 13, 16 to 18 beyond what the table says.

## Final table

| ID | Result |
| --- | --- |
| QA-SEC-1 | PASS |
| QA-SEC-2 | PASS (carried) |
| QA-SEC-3 | PASS (carried) |
| QA-SEC-4 | PASS (carried) |
| QA-SEC-5 | PASS |
| QA-SEC-6 | PASS (F5 is a stored-password case) |
| QA-SEC-7 | PASS |
| QA-SEC-8 | PASS (carried) |
| QA-SEC-9 | PASS (carried) |
| QA-SEC-10 | PASS (carried) |
| QA-SEC-11 | PASS (carried) |
| QA-SEC-12 | PASS |
| QA-SEC-13 | PASS (carried) |
| QA-SEC-14 | PASS (F1, F2 around it) |
| QA-SEC-15 | PASS |
| QA-SEC-16 | PASS (carried) |
| QA-SEC-17 | PASS (carried) |
| QA-SEC-18 | PASS (carried) |
| QA-SEC-19 | FAIL (F4: file modes, clipboard hint) |
| QA-SEC-R1 | PASS |
| QA-SEC-R2 | FAIL (F1 case bypass, F2 caller-set overwrite) |
| QA-SEC-R3 | PASS |
| QA-SEC-R4 | PASS |
| QA-SEC-R5 | PASS |
| QA-SEC-R6 | PASS |

New defects, ranked: F1 (S3, case-insensitive bypass of the installation check), F6 (S3, two untranslated sentences), F2 (S4, `overwrite` is not a confirmation), F4 (S4, world-readable history and log, no clipboard hint), F3 (S4, `--data-dir` edge cases), F5 (S4, stored URL password returned by `presets.get`).

Evidence: `/Users/justcomex/Documents/Проекты/pet/lazy-to-text/.claude/worktrees/llm-reasoning-tokens-config-624055/specs/010-electron-interface/qa/evidence/security-final/`
