# Parity: Settings (spec 006)

Qt reference: `app/gui/views/shortcuts_view.py` (all of it),
`_hotkey_validation.py`, `_accessibility_check.py`, `_microphone_check.py`,
`_section_card.py`, and in `app_controller.py` `_on_shortcuts_save`,
`_on_hotkeys_reset`, the mic-test handlers, `_refresh_shortcuts_devices`,
`_on_macos_permissions_changed`, `_on_restart_requested`.

Electron: `desktop/renderer/src/views/Settings.svelte` and
`components/settings/`, state in `lib/settings.js`, key capture rules in
`lib/hotkey.js`; runtime in `app/server/handlers/{settings,devices,permissions}.py`.

Persistence choice: **auto-save everywhere**, as in Qt (which had no Save
button). Each change is written when it is made: a capture or a mode change
saves at once, a switch on toggle, a select on choice, the numeric field on
change. A toast says "Saved" briefly (not for theme, palette, language and
text size, where the screen changing is the feedback); a failure is a toast
that stays, and the control goes back to the stored value.

## Page structure

| Qt | Electron |
| --- | --- |
| Page header "Settings" with purpose line | `PageHeader`, same strings |
| Jump links to six cards, row wraps | Sticky in-page anchor row with the current section marked (`aria-current`); real `<a href>` links; wraps. Four of the six: Storage and Hugging Face belong to the Models screen |
| Header and links outside the scroll, version footer always visible | Header and anchors scroll with the page (the anchor row stays pinned) so a large text size in a small window still has room; the version footer stays outside the scroll, always visible |
| Cards: Audio input, Hotkeys, Clipboard, Appearance | Same four, in the same order, as `SettingsSection` cards |
| Storage card, Hugging Face card | omitted: Models screen (other slice) |
| No Save button, no global reset, per-card resets | Same. Reset exists on Hotkeys only; Storage and token resets are in Models |
| Programmatic population does not save | The form reads from `settings.get`; nothing is written until a control changes |

## Audio input

| Qt | Electron |
| --- | --- |
| Microphone combo: "System default" then `[index] name`, preselected | `Select` with the same entries; an unplugged device that is still configured is listed as "(not connected)" instead of silently showing the default |
| Device change persists and applies to the recorder | `devices.select`: persisted and applied at once |
| Device list that fails to enumerate shows only "System default" | Same (`devices.list` returns an empty list) |
| Long device names: popup wider than the combo | The kit's popup, names truncated in the trigger |
| (none) | Added: refresh button for the device list (a microphone plugged in after the page opened) |
| Test microphone: 3 s, button disabled, meter, "Listening... speak now (3 s)" | Same; the meter is `LevelMeter`, the button shows a spinner while listening |
| Verdicts: silent (bad), very quiet (warn), "Looks good." (good); raw peak and rms in a tooltip | Same three, from the shared `app/mic_test.py`; the result is a `Notice` in danger / warning / success. Peak and rms are shown as small text next to the verdict as well as in a tooltip (an addition: nothing to hover for a bug report) |
| Test refused while not idle: "wait until current operation finishes"; failures as "Test failed: <reason>" | Same strings, from `RpcError` `busy` / `no_stack` / `no_recorder` and the `error` phase |
| A late tick must not repaint a frozen meter | `mic_level` events are ignored unless the phase is `running` |
| Focus hand-off before the button disables | omitted: the button is not removed from the tab order and focus is not moved by disabling it in a browser; the button shows a busy state instead of being replaced |
| Mute other sounds while recording, macOS only; not created elsewhere | `Switch`, built only when `capabilities.mute_output` |
| Skip silence (silero VAD), tooltip about the download | `Switch`, the hint is visible text; pushes to the backend through `models.push_vad` (the Models slice's function, so there is one code path) on a thread |
| macOS microphone banner, two states | `PermissionBanner` kind `microphone` (not_determined: "Grant access"; denied or restricted: "Open Settings") |
| (none) | Added: Sound cues switch (`audio_feedback.enabled`, live) |
| (none) | Added: Longest recording field (`audio.max_duration`, 0 means no limit, bounded 0..3600, live) |

## Hotkeys

| Qt | Electron |
| --- | --- |
| Recording mode combo, three entries | `RadioGroup` with a one-line explanation under each (the Qt tooltip said the same) |
| Start / Stop / Push-to-talk key / Cancel as text fields with example placeholders | `HotkeyCapture`: records the key press (physical key code, so Option on a Mac or another layout binds the key pressed, not a symbol). Solo right-hand modifiers are captured on release, and only in push-to-talk. Escape gives up, Tab leaves, Backspace or Delete clears the optional Cancel. Placeholders show "For example: ..." |
| (none) | Added: "Type it instead" opens a text field for what a browser cannot report (Fn on most keyboards); it goes through the same validation |
| Per-mode availability (Two keys / Toggle / Push to talk) | Same. Fields a mode does not use are disabled (Stop mirrored in toggle, Cancel in toggle and push to talk) or not shown (Start and Stop in push to talk, push-to-talk key elsewhere) |
| Validation: vocabulary, modifier required except F1..F24, duplicate or unknown modifier, empty part, final token a modifier, solo modifier only in push to talk, per-platform solo list | Same rules, one implementation: `app/hotkey_rules.py`, imported back by Qt's `_hotkey_validation.py` |
| Cross-field conflicts (Stop = Start points to Toggle; Cancel = Stop; Cancel = Start) | Same |
| Refusal: inline reason, invalid marker, tooltip, accessible description | Inline reason (`role="alert"`) under the field, danger border, `aria-invalid`, `aria-describedby`. The sentence is the Qt catalogue's, translated by the renderer |
| Invalid value never persisted; fallback is the last value valid in this session, else the default; other fields still save | Same, with the stored value as "last valid" (the runtime only ever stores valid values; a hand-edited invalid value falls back to the default) |
| Config on disk that fails validation is marked at load | `hotkey_errors` from `settings.get`, shown on load |
| Toggle: Stop mirrors Start live; leaving restores the Stop snapshot; Cancel persisted empty, text kept on screen | Same; the snapshot lives in a session store (`remembered`), and leaving toggle with no snapshot restores the platform default Stop rather than a Stop equal to Start |
| Legacy Start == Stop with `two_keys` shows Toggle | Same (`settings.get` reports `toggle`) |
| Push-to-talk minimum hold: no control | Added: slider 0..1 s, shown in push to talk, live through the listener |
| Reset hotkeys: mode, Start, Stop, Cancel, PTT key to the platform defaults; leaves auto-paste, storage, token | Same. **Fixed Qt bug:** it now reaches the running listener (Qt wrote the defaults to the file and the form and left the listener on the old bindings) |
| Saving pushes all five values to the listener in one batch; a listener failure is logged and does not lose the config | Same one batch. A failure is also reported (`live: false`) and shown as a "Saved, but not applied yet" toast |
| Hint: Cancel discards the current buffer | Shown as the Cancel row's hint in two-key mode; in the other modes it says Cancel is two-key only |
| macOS Accessibility banner; suppressed in push to talk on a solo modifier | `PermissionBanner` kind `accessibility`; same suppression, decided in the runtime |
| Qt VAD tick lost on reset (`set_values` rebuilt without `vad_enabled`) | **Fixed:** reset does not touch the VAD value; a test pins it |

## Clipboard

| Qt | Electron |
| --- | --- |
| Auto-paste checkbox, persisted and pushed to the live clipboard manager | `Switch`, same |
| Post-event banner: macOS only, auto-paste on, keystroke posting known shut; "Allow auto-paste access" | `PermissionBanner` kind `post_event`, same conditions (runtime) |
| (none) | Added: "Keep my clipboard" (`clipboard.preserve_clipboard`, live) |

## Appearance

| Qt | Electron |
| --- | --- |
| Text size: 100% (default), 115%, 130%, 150%, 175%, applied at once; a stored value between presets shows the nearest | `Select`, same five; same nearest-preset rule. Applied as the root font size, which scales type and rem-based spacing together (Qt scaled type only and kept radii and spacing); clamped to the same 0.85..1.75 |
| Theme: Follow the system (default), Light, Dark; `system` stays `system` | `Select`, same; applied at once; `system` follows the OS without a restart |
| Language: English, Russian shown in their own names | `Select`, same; strings switch at once |
| (none) | Added: Palette, one of the kit's six themes, as a card per palette showing its light and dark swatches (read from the kit's own table); stored as `ui.palette` (new key in `DEFAULT_CONFIG`, default `gruvbox`) |
| Unrecognised stored theme or language falls back | Same, from `app/ui_prefs.py`, also for the palette |
| Hint "Applies immediately. Radii and spacing keep their size" | Replaced by the per-control hints: radii and spacing do scale here, so the sentence would be false |

## Permissions

| Qt | Electron |
| --- | --- |
| Three banners re-evaluated when Settings is shown and when the window is activated | `permissions.refresh` on mount, on window focus and on page visibility |
| Accessibility button: ask; if refused open the pane; re-check after 250 ms | `permissions.request`: same sequence in the runtime |
| Microphone not determined: system prompt, banner re-rendered on completion (GUI thread bridge) | Same; the completion refreshes and publishes a `permissions` event, no thread bridge is needed |
| Microphone denied or restricted: "Open Settings" opens the pane | Same |
| False to True: re-enumerate microphones, restart the hotkey listener, no restart of the app | Runtime restarts the listener; the renderer re-lists the devices when the screen is shown |
| Two "Grant access" buttons differ by accessible name and description | Same (`aria-label` and `title`) |
| Button capped at half the banner width | The banner wraps: the sentence has a minimum width and the button drops under it when there is no room |
| `_on_restart_requested` (wired to nothing) | omitted: there is no restart flow; everything applies live |
| Not macOS: no banner ever | Same: every state is `hidden` |

## Version and About

| Qt | Electron |
| --- | --- |
| Footer "Lazy to Text <version>", always visible, selectable | Same, in a footer outside the scroll |
| (none) | Added: "Copy version" button |
| About dialog (app menu): icon, version, description, project link | "About" button opens the same text in a `Modal`; the link opens in the OS browser. The application icon is omitted (the dialog is a page, not a native sheet) |
| Cmd+, / Ctrl+, opens Settings from anywhere | `App.svelte` handles the key and shows Settings |

## Deliberate differences, in short

* Reset hotkeys applies live; reset no longer touches VAD (Qt bugs).
* Hotkey capture instead of typed text, with a typed fallback.
* Auto-save with a toast; a failed write reverts the control.
* Added: palette, minimum hold, sound cues, longest recording, keep clipboard, refresh devices, copy version.
* Text size scales spacing as well as type.
* Storage and the Hugging Face token are not here: Models screen.
