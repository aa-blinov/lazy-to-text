# QA release candidate 0.2.0

Tester: RC QA. Date: 2026-10-24. Platform: macOS 26 arm64 only; Windows and Linux are code review.
Build under test: `desktop/release/mac-arm64/Lazy to Text.app` (rebuild.done `OK`), version 0.2.0, signed with
the local certificate, hardened runtime, designated requirement `identifier "ai.eora.lazytotext" and certificate root = H"b632..."`.

Every launch used a scratch `HOME`, its own `--user-data-dir`, a CDP port (19002), `--l2t-selftest`; model symlinked.

## Result table (written incrementally)

| Check | Result | Evidence |
| --- | --- | --- |
| Start-when-I-log-in: switch exists, default off | PASS | Settings > Startup, `aria-checked=false` on a fresh profile |
| ... turning it on applies live, persists | PASS | After the click: System Events login items gained `Lazy to Text` (path = the packaged .app), `start_at_login: true` in config.yaml, log line `Updated setting ui.start_at_login: False -> True`. After a restart the switch read true. |
| ... turning it off removes the item | PASS | Login item list back to the 12 baseline names; config false |
| ... cleanup | PASS | The only item I created was removed (list equals the baseline recorded before the test) |
| `--hidden` launch | PASS | System Events: 0 windows of the process, process alive, menu bar present; the page loaded and answered over CDP |
| About entry (macOS app menu) | PASS (partial) | `About Lazy to Text` opened the native panel: name, `Версия 0.2.0 (0.2.0)`. The credits text (description, licence, repository) is not exposed to System Events and I did not capture the screen, so it is checked in code (`aboutOptions`, main.cjs:463). Windows/Linux entry: code and tests only |
| Forced colours | PASS (emulated) | CDP `Emulation.setEmulatedMedia forced-colors: active` on the packaged window, Settings screenshot: system palette, framed buttons, visible focus rings, switch on/off distinguishable, current row marked. Not on Windows |
| Cmd+F on Logs | PASS | Synthetic Meta+F (CDP key event) with Logs open: focus moved to `input[type=search]` `Search logs`. 1 run, synthetic key |
| Hugging Face token link | PASS | In the Models > "Storage and access" drawer: `Get a token on huggingface.co`, href `https://huggingface.co/settings/tokens`, `_blank`, `noopener noreferrer`. Not clicked (would open the user's browser) |
| Tooltip on Clear logs | PASS | Mouse move over the button: a `role=tooltip` reading `Empty the log buffer. The log file on disk is not touched.` |
| Model card accessible description | PASS | `role=group`, `aria-labelledby` the title, `aria-describedby` = figures + description (both resolve to text), 16 cards |
| Capsule bottom right | PASS | While recording, the overlay window was at x=1528, y=1171, 520 x 96 on a 2056 x 1329 screen whose work area ends at y=1267 (Dock): right edge 2048 (8 px from the edge), bottom edge on the work area. The capsule showed `RECORDING / Speak now / 00:14` (timer read late, osascript calls were slow). No pixel screenshot: a full-screen capture shows the user's other windows, so none was kept |
| File associations vs `app/audio_formats.py` | PASS | Info.plist `CFBundleDocumentTypes`: 24 extensions, set-equal to `AUDIO_EXTS` (24), role Editor, rank Alternate. Not registered with Launch Services here |
| Cold start with a file argument | PASS | Fresh profile, `short.wav` (49 s, 109 words) on argv: transcribed after start-up, 109 words. Second instance with a file forwarded to the first and exited |
| First-run file hold | PARTIAL | With no model cached, the first-run page came up with `short.wav` on argv: nothing in app.log about a transcription while it was up, nothing on the Transcribe screen. After `Set up later` the shell showed the "No model is loaded yet" note; I could not tell a replay from a drop, because first-run only appears when no model exists, and without a model the replay has nothing to do. Only the unit test (`transcribe.test.js`) proves the replay |
| Real hotkey dictation (ctrl+alt+f11/f12, Quartz) | PASS | State RECORDING -> IDLE, history entry `сегодня хорошая погода я проверяю диктовку в рилис кандидате ноль два ноль`, delivery `copied` (auto_paste false). Side effect: the real clipboard now holds the last dictation |
| 30 s dictation | PASS | 29.4 s of Milena speech (about 55 words): 31.6 s recorded, whole text in history from the first sentence to `конец проверки` |
| File drop longer than 67 s (CDP drag, `--l2t-selftest`) | PASS | 49 s file: 109 words, all three markers; 118 s file: 263 words, all markers but one spelt differently, status IDLE, 0.4 s |
| Too-short double tap | PASS with a wording note | Two start/stop pairs inside 0.1 s: no crash, back to IDLE, log `Nothing was recorded: no audio came from the microphone` (see QA-RC-3) |
| Kill the inference worker, dictate again | PASS | `kill -9` of the worker: next dictation delivered normally, a new worker process appeared (2 runs of the first kill, 1 of the dictation) |
| Engine stopped after `kill -9` of the runtime | PASS | Page showed `ENGINE STOPPED / The engine is not running... Your history and settings are safe`, no runtime or worker left; `Restart` brought IDLE and a new runtime |
| Runtime with PySide6 blocked | PASS | meta-path blocker raising for PySide6/shiboken6/PyQt5/6, ran `app.server.__main__.main`: ready line, hotkeys active, recording stack built, no import attempt |
| `uv run --frozen lazy-to-text-server` | PASS | `--port 19001 --data-dir <scratch>`: `{"ready": true, "port": 19001, "token": ..., "pid": ...}`, config and logs created under the data dir, listening on 127.0.0.1 |
| Packaged runtime start | PASS | Every launch above; `build_server.py` smoke run `ready line printed, app.snapshot answered` in the build log |
| `scripts/check_translations.py` | PASS | `769 entries; 451 renderer and 45 runtime strings; 0 missing` |
| Relative links README / docs / md | PASS | script over `]( )`, `href`, `src`: 0 broken in 13 files, plus backticked repo paths in README, docs/*.md, AGENTS.md: only CLAUDE.md (see QA-RC-4) |
| Processes after quit | PASS | SIGTERM to the app: app, runtime, worker all gone in under 6 s (3 runs) |
