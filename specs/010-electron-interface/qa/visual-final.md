# QA final round: visual (area: visual)

Tester: visual, round three. Date: 2026-10-24. Build: worktree `llm-reasoning-tokens-config-624055`, app 0.1.23, HEAD `9d7b70c` plus uncommitted changes. The working tree changed while I was testing: `desktop/renderer/src/views/FirstRun.svelte` (the stepper's last step is pushed to the right edge) was modified by someone else mid-run; everything below was observed with that change in place.

STATUS: COMPLETE.

## How this was run

- Runtime on 18502 (`--dev --dev-port 5802 --no-single-instance --no-stdin-watch --token devtoken --data-dir <scratch>/visfinal/data`, `HF_HUB_OFFLINE=1`), Vite on 5802, one own Browser tab (viewport reset to desktop and tab closed at the end). Models: one symlink to `models/hub/models--alphacep--vosk-model-small-ru` (no copy, no download). Scratch folder `visfinal` only, deleted at the end; every process I started was stopped (runtime, Vite, two small loopback helper servers).
- Seeded: 64 history entries (RU, EN, kk, de, multi-line, a 300-char URL, a 2000-word entry, a 320-char unbroken string, a 55-char model id), four presets (an 80-char Russian name, an 80-char unbroken name, one with a key), `vosk-ru-small` loaded; test audio made with `say -v Milena` (a 21 s clip, an 830 s file, a corrupt `.wav`).
- Instruments (copied to `qa/evidence/visual-final/tools/`, not part of the app): `audit.js` computes, per screen, per palette (6) x mode (2) x text size (100/130/175 %): WCAG contrast of every text node against its composited background (transitions off), horizontal overflow of html/main/scrollers, elements past the viewport edge, ellipsis text without a `title`, controls under 24 px, raw i18n keys. `capsule.js` drives the real `Overlay.svelte`. `fake_rt.py` is a loopback stand-in for the runtime that proxies to the real one and lets me push events (capsule states, permission banners, a first-run download with progress, a model load in progress). `csp_srv.py` serves a production build under the strict policy given in the brief.
- Viewports 900x600, 1120x760, 1600x1000; EN and RU; every audit ran 12 palette/mode pairs x 3 text sizes = 36 combinations per screen and state.
- Not Electron: no native window, tray, real overlay window, or packaged app (`rebuild.done` was never written while I worked, so I did not wait for it; the renderer was tested from source and from a production build of the same source).
- Environment notes (not product defects): the Browser pane is hidden, so a screenshot taken right after a change can show the previous frame (I waited a second before each shot); another tester's page navigated my first tab, and a stale tab of mine held the browser's six connections to the runtime, which left the page on its spinner until I closed it; `layout-shift` entries are not delivered to a hidden pane, so layout shift was judged by measuring, not by the observer.

## Part 1: the 14 earlier defects

| ID | Result | Evidence |
| --- | --- | --- |
| QA-VISUAL-1 long preset name on Transcribe | PASS | 80-char active preset, Transcribe empty and with a file loaded: `main` scrollWidth == clientWidth at 900x600 and 1120x760, 100/130/175 %, EN and RU, 12 palette/mode pairs. A neighbouring overflow with a short name is F5. |
| QA-VISUAL-2 History long strings | PASS (see F1) | 300-char URL, 320-char token, 55-char model id: table fits at 100 % (1120, 900); at 1120/100 % `scrollWidth 841 = clientWidth`; detail modal text box 444/444 at 900x600 (`f-history-...` not needed). The fix leaves the Text column unreadable at larger text: F1. |
| QA-VISUAL-3 preset list truncation | PASS | List rows `Очень длинное название пресета для п…выбора, версия номе` and `Supercalifragilisticexpialidocious_x…xxxxxxxxxxxxxxxxZZZ` are distinct; trigger shows the middle-shortened name. |
| QA-VISUAL-4 Models at large text, 900x600 | PASS | 36 combinations, EN and RU, no overflow at 130 and 175 %. |
| QA-VISUAL-5 Post-processing form at 175 % | PASS | One column, every field 482 px, API key 353 px next to Clear. |
| QA-VISUAL-6 Models titles at 1600 | PASS | Two columns of 544 px, 0 clipped titles. |
| QA-VISUAL-7 chip font | PASS | Computed 12 px (the kit token), 17 px high. Kit file still reads the undefined name; the `app.css` alias is what fixes it. |
| QA-VISUAL-8 capsule ignores palette | PASS | Real runtime set to nord / light / ru: `overlay.html` has `data-theme=nord data-mode=light lang=ru`; live through the `settings` event on a stand-in runtime (`f-capsule-too-short-nord-light-ru.jpg`). |
| QA-VISUAL-9 `<html lang>` | PASS | `lang=ru`, `aside aria-label="Навигация"`, History Language column `русский / английский / казахский / Автоопределение / немецкий`. |
| QA-VISUAL-10 scroll-spy at the end | PASS | Real wheel scroll in the pane: `aria-current=location` moves to Appearance at scrollTop 1138.5 of 1139 (`f-qa10-...jpg`). |
| QA-VISUAL-11 toast over the status strip | PASS | 1120x760: toast bottom 708, strip top 724 after a History delete (Undo restored the row). Settings: see F11. |
| QA-VISUAL-12 no-model state | PASS | Fresh profile after "Set up later": strip `No model yet / OPEN MODELS`, Transcribe notice `No model yet`; weights present but not loaded: `Model not loaded / LOAD` (strip) and `Model not loaded` (notice); a file dropped with no model: `No model is loaded yet. Download one or load the one you chose.` with Open Models, no "wait". |
| QA-VISUAL-13 raw engine error | PASS (text) | Corrupt `.wav`: `Could not read audio from corrupt.wav. The file may be damaged, cut short, or not an audio or video file.` No class names, no ONNX text, no paths. The 77 s failure did not reproduce: an 830 s file transcribed in 2.8 s (1605 words), a 21 s file in 95 ms (1 run each). |
| QA-VISUAL-14 smaller items | PASS for the items claimed fixed; the stated residuals remain | "Show more" only where text is clamped (16 of 16 cards, 0 mismatches at 1120); Spinner stops under reduced motion (rule present in the built CSS); Storage drawer buttons all upper case; one container, 1152 px on all six screens at 1600 (Settings content 1152 inside a full-width scroller; its sticky section bar is full-bleed); capsule within its 504 px at 100 % text (see F3 for larger text); first paint takes palette, mode and text size from `boot.js` under the strict policy (iframe: `nord/light/130%` while the document was still `loading`, 15 ms; the app then applied the real config at 46 ms); `windows.cjs` now uses `paperColor()` for the window background. Form-control borders: 1.68 to 2.18:1 against the card in all 12 pairs (stated design decision, not 3:1; listed again as F14). |

## Part 2: coverage matrix, what was checked on which screen

Results with no finding are in "Covered, no defect"; the findings are under "New defects".

| Screen / state | Checked |
| --- | --- |
| Transcribe | empty; no model (fresh); model not loaded; running (830 s file, "Transcribing... 25.3 MB", notice "Working. The window stays usable."); done (21 s file, 40 words); edited (`... 1604 words`, then `... 1605 words . Edited`); error (corrupt file); long preset name; preset row at 175 % |
| Models | 16 cards; active; not loaded (`NOT LOADED` + `LOAD`); loading (36 %, banner, card chip, strip); not downloaded (`DOWNLOAD`); storage drawer (EN) |
| History | empty; 64 rows; long rows; detail modal with the 300-char URL; delete + Undo; RU |
| Post-processing | key unset / set (`A key is saved. Type a new one to replace it.`, Clear enabled); long preset names; invalid server address (red border, message under the field); timeout, max tokens, reasoning effort controls; remote-server notice; light and dark |
| Settings | every section (Audio input, Hotkeys, Clipboard, Appearance); hotkey capture: listening (`Press the keys`), typed-in field, unrecognised key error, conflict error with the field-level message and a danger toast `Not saved`; permission banners (microphone denied, accessibility, post-event) in EN and RU at 900x600 and 175 % |
| Logs | 100 / 130 / 175 %, EN and RU |
| First-run | choose, download in progress (44 %), failure + Try again, success step "Learn the key", RU at 900x600 and 175 % for all three steps |
| Engine-stopped dialog | runtime killed under the page: `The engine stopped`, modal, focus inside; sizes 900x600 at 100/130/175 %; contrast in 12 pairs (lowest 5.22:1) |
| Toasts | Saved (success), Not saved (danger), Undo; stack of two; position over the strip at 100 and 175 % |
| Capsule | recording, processing, pasted, copied (with shortcut), failed (two-line detail), too short; 6 palettes x light/dark x EN/RU = 144 renders; prod build under the strict policy; text-size inheritance |
| Production build | `vite build` to a scratch folder, served with `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src http://127.0.0.1:*; img-src 'self' data:; font-src 'self'; object-src 'none'`: all six screens, Storage drawer, History modal, About dialog and the capsule loaded; 0 `securitypolicyviolation` events, 0 CSP or script errors in the console, `boot.js`, fonts and CSS all 200 |

## New defects

Ranked. Shape as in the README; "Evidence" files are in `qa/evidence/visual-final/` (prefix `f-`).

### QA-VISUAL-F1  History: the transcription column collapses to a few characters while the metadata columns keep their width
Severity: S3
Where: History table (`views/History.svelte`, text button and Model cell carry `[overflow-wrap:anywhere]`; automatic table layout)
Steps: 1. Seed a few normal entries (no long strings are needed). 2. Window 900x600. 3. Set Settings -> Text size to 115 %, then 130 %. 4. Open History.
Expected: the words of the dictation stay readable; at worst the table scrolls with the text column still wide.
Actual: Text column is 159 px at 100 %, 83 px at 115 %, 71 px at 130 % (`Ссы лк…`, two characters per line), 96 px at 175 %; Time (140), Language (111) and Duration (111) keep their width; the Model id breaks per character (`vosk / -ru- / smal / l`); at 130 % and 175 % the table also scrolls sideways (`624/560`, `841/538`), so Copy and Delete are off screen. Same in RU (`768/560`). At 1120 and 175 %: `841/692` EN, `1034/692` RU. Seen 5 times (3 sizes, 2 languages).
Evidence: `f-history-text-column-71px-900x600-scale130-dark.jpg`
Suspected cause: `overflow-wrap:anywhere` makes the min-content width of every cell one character, so the auto layout gives the leftover to the columns with fixed-size content; the Text column needs a floor (`min-w-[14rem]` or a fixed layout) and the Model cell `break-words` only.
Status: FIXED. Text button has a 14rem floor and the Model cell breaks at word boundaries; at 900x600 the Text column measures 322 px at 130 % and 434 px at 175 % (was 71 and 96), and the table scrolls inside its own frame, `main` no longer scrolls. Verified in the real UI.

### QA-VISUAL-F2  First-run step 3 labels the start key as the stop key
Severity: S3
Where: First-run, step "Learn the key" (`views/FirstRun.svelte`, the `hotkey-caps` block, the `to stop` span)
Steps: 1. Reach step 3 (download finished). 2. Read the line under the heading.
Expected: each key says what it does ("Ctrl F8 to start, Ctrl F9 to stop").
Actual: `[Ctrl][F8] to stop [Ctrl][F9]`; the start key has no label at all, so the line reads as if F8 stops. RU: `Ctrl F8 чтобы остановить Ctrl F9`. 2 runs (EN, RU).
Evidence: `f-firstrun-step3-ctrl-f8-to-stop-ctrl-f9-no-start-label-1120-dark.jpg`
Suspected cause: only the stop branch has a text node; the body line below says "Press it, say a sentence, press stop", which does not name the keys either.
Status: FIXED. Step 3 shows `Start: [keys]` and `Stop: [keys]` as two labelled groups (RU `Старт:` / `Стоп:`); the old `to stop` string is removed. Covered by a source and translation test; step 3 itself not reached in the real UI (needs a finished download).

### QA-VISUAL-F3  The capsule inherits the main window's text size and outgrows its fixed window
Severity: S3
Where: `renderer/overlay.html` loads `public/boot.js`, which sets the root font size from `localStorage l2t.scale`; the capsule never resets it (only `App.svelte` calls `applyTextScale`); window is 520x96 (`desktop/electron/windows.cjs` `OVERLAY_SIZE`)
Steps: 1. Set Settings -> Text size 175 % (the main window stores `l2t.scale`). 2. Open `overlay.html` (same origin as the main window) and push a failed delivery.
Expected: the capsule keeps its size; it is a 520x96 window, not part of the interface scale.
Actual: root font 28 px, capsule 98 px high in a 96 px window (top -1, bottom 97), the reason text wraps and clips (`The system refused the paste…`); at 130 and 150 % the capsule is larger than designed but fits. In a browser tab the stored value is shared with the main page exactly as it is between the two Electron windows. 1 run at 175 %, same origin.
Evidence: `f-capsule-inherits-text-scale-175-from-bootjs-clipped-in-520x96-window.jpg`
Suspected cause: `boot.js` is shared by all three pages; the capsule page should clear the font size or skip the scale.
Status: FIXED. `overlay.html` carries `data-fixed-scale` and `boot.js` skips the stored text scale for it; the capsule also clears any inline root size. Verified: stored scale 1.75, capsule root stays 16 px. The long reason is shortened in the middle (`clampMiddle`, 110 characters, head and tail kept), 2-line clamp and `title` stay. Tests: boot.test.js, capsule.test.js.

### QA-VISUAL-F4  Logs toolbar overflows at 175 % in Russian on the smallest window
Severity: S3
Where: Logs, level filter group (`Все / Информация / Предупреждения / Ошибки`)
Steps: 1. Window 900x600. 2. Text size 175 %, language Russian. 3. Open Logs.
Expected: the filter wraps or shrinks inside the column.
Actual: the group is 906 px wide in a 900 px window; the `Ошибки` button ends at 901 and is cut by the window edge; `main` scrolls sideways (`636/624`). EN at the same size does not overflow (only the log pane scrolls). 1 run, deterministic.
Evidence: `f-logs-ru-900x600-scale175-level-filter-clipped.jpg`
Status: FIXED. The level group may wrap (`!h-auto flex-wrap max-w-full`) with 24 px buttons. Verified RU, 900x600, 175 %: group 312 to 852 px on two lines, `main` 624/624.

### QA-VISUAL-F5  Transcribe: preset row overflows at 175 % once a file is loaded (short preset name)
Severity: S4
Where: Transcribe, row `Copy / Save .txt / Preset for this file / Preset select` (the select has `min-w-48`, so a short name cannot shrink it; the long-name case shrinks fine)
Steps: 1. Active preset `Default`. 2. Window 900x600, text 175 %. 3. Drop any file (done or failed).
Actual: the Select's right edge is at 913 px in a 900 px window, `main` scrolls sideways (`643/624`); also at 1024x768 the select protrudes about 12 px past the content column. At 1120x760 and 175 % no overflow. 3 runs (done, failed, 1024).
Evidence: `f-transcribe-done-175-preset-select-past-content-edge-1024.jpg`
Status: FIXED. The row wraps (`flex-wrap`) and the select floor is `min-w-32`. Verified with two presets at 100/130/175 %: no horizontal scroll.

### QA-VISUAL-F6  The "Preset for this file" checkbox is squeezed into a pill at 130 % and 175 %
Severity: S4
Where: Transcribe, preset row (the checkbox is a flex child with `flex-shrink: 1`)
Steps: window 900x600, text 130 % then 175 %, open Transcribe.
Actual: the box is 16x21 at 130 % and 15x28 at 175 % (EN), 19x28 at 1120x760 RU 175 %; a tall narrow capsule, not a square. Every palette. 6 runs.
Evidence: `f-checkbox-squashed-900x600-scale175-transcribe.jpg`
Status: FIXED. The checkbox box is `shrink-0`. Verified 16, 21 and 28 px squares at 100/130/175 %.

### QA-VISUAL-F7  Post-processing: the "In use by default" label is unreadable (1.5 to 1.8:1) in every palette
Severity: S4
Where: Post-processing, Preset card, a disabled Button (opacity 0.3) whose label is a status the user wants to read
Steps: open Post-processing with the first preset active.
Actual: contrast 1.47:1 (gruvbox light) to 1.81:1 (dracula dark); WCAG exempts disabled controls, but here the disabled button is the only place the state is written. Same in RU (`Используется по умолчанию`). Disabled `Export` and `Clear history` on the empty History are 1.5 to 1.8:1 as well (a disabled control there is expected).
Evidence: `f-postproc-in-use-by-default-disabled-label-1120-dark.jpg`
Suspected cause: should be plain text or a Badge, not a disabled button.
Status: FIXED. When the preset is the default, a plain text status (`data-testid=preset-in-use`, ink-soft with the old tooltip) replaces the disabled button. Test in visual-final.test.js.

### QA-VISUAL-F8  Engine-stopped dialog: the only action sits on the clipped bottom edge at 175 % on 900x600
Severity: S4
Where: engine-stopped AlertDialog (max height 488 px)
Steps: runtime killed, window 900x600, text 175 %.
Actual: dialog content 562 px in a 486 px box, it scrolls (a scrollbar is drawn) and the `TRY AGAIN` button (500-563) is cut by the dialog's bottom edge (544). Reachable by scrolling; at 100 and 130 % it fits (321/321, 417/417). 1 run.
Evidence: `f-engine-stopped-900x600-scale175-try-again-below-fold.jpg`
Status: FIXED. The engine dialog panel no longer scrolls as a whole: the body scrolls inside the viewport and the footer stays visible; padding reduced. Verified at 175 %, 900x600: button 445 to 508 inside a 56 to 544 dialog, no overflow.

### QA-VISUAL-F9  Sidebar label "Post-processing" is cut at 175 % on 900x600, without a tooltip
Severity: S4
Where: sidebar item (`min-w-0 flex-1 truncate`, 221/213 px), no `title`
Steps: window 900x600, text 175 %, any screen; read the fourth item.
Actual: `Post-processi…`. Russian `Постобработка` fits. Seen on all six screens, 12 palette/mode pairs.
Evidence: visible in `f-checkbox-squashed-900x600-scale175-transcribe.jpg`
Status: FIXED. Sidebar items carry `title`; verified (`Постобработка` etc.). Strip load detail and model name also carry `title`. Test: visual-final.test.js.

### QA-VISUAL-F10  Status strip: the load progress is truncated to 67 px at 175 % on 900x600, and the percent disagrees with the card
Severity: S4
Where: status strip while a model loads (`92.5 MB / 259.4 MB (35%) · 11 s`, 391 px of text in 67 px; 290/281 at 130 %), no `title`; the Models banner and card chip say 36 % for the same figures
Steps: start a download or load (here: a stand-in runtime pushing `progress` and `state` events), window 900x600, text 175 %.
Actual: ellipsis only; 35 % vs 36 % for 92.5 of 259.4 MB (floor in the strip, round elsewhere). 1 run, stand-in events.
Status: FIXED. One function (`percent` in statusFormat.js, rounded, held at 99) feeds the strip, `downloadFigures().percent`, the card chip and the banner; 92.5 of 259.4 MB now reads 36 % everywhere. Tests in visual-final.test.js.

### QA-VISUAL-F11  Settings on the smallest window at large text: a 120 px sticky footer, and toasts cover it
Severity: S4
Where: Settings (sticky section bar 92 px, footer `Lazy to Text 0.1.23 / Copy version / About`, status strip)
Steps: window 900x600, text 175 %, open Settings, flip any switch.
Actual: scroll area 417 px of 600, footer 120 px (two lines), strip 63 px; the `Saved` / `Not saved` toasts sit in front of the footer's Copy version and About (toast 431-517 over footer 417-537). At 100 % the toast also covers the footer links (`679-724` vs toast `608-716`). The toast offset keeps clear of the strip (8 to 20 px) but not of this footer. 3 runs.
Evidence: `f-settings-175-900x600-sticky-footer-120px-toasts-over-footer.jpg`, `f-settings-hotkey-conflict-error-and-danger-toast-1120-dark.jpg`
Status: FIXED. The version footer moved to the end of the scroll area (no longer pinned, with room under it for toasts), so the pinned 120 px is gone. Not re-measured with toasts in a browser.

### QA-VISUAL-F12  Capsule: the dot is under 3:1 in some palettes, and a long failure reason loses its tail
Severity: S4
Where: capsule dot (`bg-danger`, `bg-success` on `bg-surface`) and the two-line detail (`line-clamp-2`, the `title` cannot show in a click-through window)
Actual: dot contrast `nord/light` pasted 1.67, `nord/dark` recording 2.46, `gruvbox/light` pasted 2.26, `solarized/dark` 2.81, `solarized/light` pasted 2.62, `catppuccin/light` pasted 2.75 (the title states the outcome, so this is a non-essential cue); text contrast passes in all 144 renders. A realistic worst-case detail (`Could not transcribe the recording (...). The recording was kept at /Users/.../recordings/...wav.`) shows two lines and ends at `The…`, so the place the recording was kept is never visible (it is in the log). The two-line detail itself fits the 56 px capsule and 504 px width in EN and RU in every palette.
Evidence: `f-capsule-failed-detail-clamped-2-lines-gruvbox-dark-en.jpg`
Status: FIXED (dot and tail). The dot has a 1 px ink-soft border so it is not a colour-only cue under 3:1; the long reason keeps its tail (see F3).

### QA-VISUAL-F13  Small hit targets
Severity: S4
Where: Models family filter chips 17 px high; Logs level segment 22 px, `Messages for you` 17 px; History row text buttons 20 px high; radio and checkbox inputs 16 px (21 px at 130 %); inline links excluded
Actual: below the 24 px minimum of WCAG 2.2 AA (2.5.8). Most come from the kit's sizes. Counted by script on all screens.
Status: PARTLY FIXED. Family chips, `Messages for you`, the Logs level segment and the History text buttons now have `min-h-6`. The 16 px radio/checkbox boxes are the kit's own: their label row is already 24 px and clickable, so the target is not smaller; not changed.

### QA-VISUAL-F14  Form-control borders: still 1.68 to 2.18:1, and two control styles in one form
Severity: S4
Where: all text fields and selects (`--ui-line-strong`)
Actual: field border against the card 1.68 (gruvbox light) to 2.18:1 (dracula dark) in all 12 pairs, below the 3:1 of WCAG 1.4.11 (the earlier round named this a design call). In the same row the Select is a filled box with a full border and the inputs next to it are an underline only (`Reasoning effort` beside `Max tokens`, `Provider` beside `Name`): the border colour is consistent, the shape is the kit's two styles. Placeholders pass (4.58 to 6.78:1); the focus ring passes everywhere (3.49 to 11.70:1, lowest solarized light).
Status: NOT FIXED. Border contrast and the two control styles are the kit's design (a stated decision of the earlier round); changing them would restyle every input.

### QA-VISUAL-F15  Smaller polish
Severity: S4
- The skip link, when focused, sits over the first sidebar item (fixed at 8,8; 152x38) and hides `Transcribe` while focused. It is invisible otherwise (1x1) as intended.
- The focus ring on the screen heading after Enter on the skip link is a full-width box (428 px) that touches the subtitle under it; correct, but heavy.
- The Russian language names in History are lower case (`русский`, `английский`) next to `Автоопределение`.
- The status strip reads `IDLE` while a file is being transcribed (`Transcribing... 25.3 MB` in the page, strip unchanged).
- Content shifts 3 px sideways between screens that have a vertical scrollbar and those without (container left 109 vs 112 at 1600).
- Key save: the hint `A key is saved...` pushes the next form row down by about 27 px.
- The warning dot in a notice without a title (the no-model drop notice) sits above the text baseline.
Status: NOT FIXED. Not done for lack of scope; none of the items affects reading or operating the app.

## Covered, no defect

- Contrast: every text node on every screen and state above, 12 palette/mode pairs x 3 text sizes x 3 window sizes x EN/RU: no text under AA outside disabled controls (listed as F7). Lowest enabled-text values seen: 4.54:1 (solarized light, status strip), 5.22:1 (engine-stopped dialog). Placeholders >= 4.58:1. Focus ring >= 3.49:1 on bg and on card in all 12 pairs.
- Keyboard: skip link visible on focus only; Enter moves focus to the screen heading with a 2 px ring; focus rings are not clipped by any scroller or overflow ancestor on any of the six screens (195 focusable controls on History alone).
- Horizontal overflow: none on Transcribe (empty, running, done, edited, error, no model, model not loaded), Models (incl. loading), Post-processing (key set, invalid address), Settings (with all three permission banners), First-run, History empty, at 1120x760 and 1600x1000 in EN and RU, except the items under New defects.
- Russian lengths: all screens at 900x600 and 175 % fit except F1, F4, F9; `Используется по умолчанию`, permission banners and the hotkey conflict sentence wrap inside their cards.
- Raw keys, `undefined`, `[object`: none. (Logs lines contain logger names by design.)
- Errors under fields: server address (`The address cannot contain spaces or line breaks.`, red border, `aria-invalid`), hotkey (`'f8ctrl' is not a recognised modifier (use ctrl, shift, alt, cmd).`, `Stop is the same as Start (ctrl+f9). Choose "One key..."`), each in danger text that passes 4.5:1.
- Capsule: 144 renders (6 palettes x 2 modes x EN/RU x 6 states): no horizontal overflow, nothing taller than its 56 px, no text under 4.5:1, two-line detail fits; recording clock and meter present.
- Production build under the strict policy: no CSP violation, no console error from the page, all assets (3 pages, 4 font families, `boot.js`) load from `'self'`.
- Toasts: success and danger stack upward with an 8 px gap, danger stays until closed, none hides the status strip.

## Not tested, and why

- Electron windows, tray, native menus, the real capsule window, packaged app: not run in this area; a browser tab has no `window.l2t` (a stub was used for drops).
- Model download from the network, a real download failure mid-way, delete-model confirm (no second model on disk, downloads forbidden); the download and load screens were driven by a stand-in runtime pushing the runtime's own events.
- Real microphone, VU meter with live input, real permission prompts (banners were driven by a stand-in; the real runtime reports all permissions granted).
- Hover and pressed states by pixel (hidden pane does not advance transitions); only class and computed-style inspection.
- Layout shift by the browser's observer (hidden pane delivers no entries); a few shifts measured by hand are in F15.
- Reduced-motion by emulation (CSS rule read from the built file).
- History at 1600 in RU and the detail modal at 175 %.

## Ranked summary

1. F1 History text column unreadable at 115 %+ text on the smallest window (S3).
2. F2 First-run step 3 misnames the start key (S3).
3. F3 Capsule takes the main window's text size and outgrows its window at 175 % (S3).
4. F4 Logs level filter cut off at 175 % in Russian on 900x600 (S3).
5. F5 to F15: S4 items (preset row overflow, squeezed checkbox, unreadable "In use by default", engine dialog at 175 %, truncated labels without titles, Settings footer and toasts, capsule dot and clamp, small targets, border contrast, polish).

File: `specs/010-electron-interface/qa/visual-final.md`
