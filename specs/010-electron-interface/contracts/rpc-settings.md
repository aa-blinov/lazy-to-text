# Contract: settings, devices, permissions

Transport and envelope: see `plan.md`. Handlers: `app/server/handlers/settings.py`,
`devices.py`, `permissions.py`. The Qt reference for each rule is
`ShortcutsView` and `AppController` (`_on_shortcuts_save`, `_on_hotkeys_reset`,
`_on_test_mic_requested`, `_on_macos_permissions_changed`).

Shared, Qt-free rules extracted for both interfaces: `app/hotkey_rules.py`
(vocabulary and validation), `app/mic_test.py` (verdict thresholds),
`app/ui_prefs.py` (theme, palette, language, text-scale bounds and fallbacks).

## Methods: settings

| Method | Params | Result |
| --- | --- | --- |
| `settings.get` | none | See "Settings object" below |
| `settings.validate_hotkeys` | `{mode, start?, stop?, cancel?, push_to_talk_key?}` | `{errors: {field: Issue}}`; nothing is saved |
| `settings.set_hotkeys` | `{mode, start?, stop?, cancel?, push_to_talk_key?}` | `{saved, live, live_error, save_error, errors: {field: Issue}, settings}` |
| `settings.reset_hotkeys` | none | `{live, live_error, save_error, settings}` |
| `settings.set` | `{key, value}` | `{key, value, live_error, save_error}` (`value` is the stored, normalised value) |

`save_error` is `null`, or a sentence when the settings file cannot be written
(the change is applied in the running app but will be lost at quit). It is
checked from the destination's permissions, because the config manager writes in
the background and only logs a failure.

`field` is `start`, `stop`, `cancel` or `ptt`. An `Issue` is
`{message, template, args}`: `template` is the English source sentence with
`%1`, `%2` placeholders (the same string the Qt catalogue translates), `args`
fill them, `message` is the sentence already filled in English.

### `settings.set_hotkeys`

Missing text fields default to what is stored. Only the fields the mode uses
are checked: in `toggle` Stop mirrors Start and Cancel is stored empty; in
`push_to_talk` the push-to-talk key is checked against the solo-modifier
vocabulary, Start and Stop are left as stored, Cancel is stored empty.

Two kinds of refusal, in `errors` either way:

- **A field that is not a valid binding on its own** (`Hotkey cannot be empty`,
  an unknown key) is never written: it keeps the stored value if that is itself
  valid, otherwise the shipped default. The other fields still save.
- **Two bindings that would be the same key** (Start = Stop in two-key mode,
  Cancel = Start or Stop, and the push-to-talk key = any binding sent with it)
  refuse the **whole request**: nothing is written, nothing reaches the
  listener, `saved: false`, `live: false`, `live_error: null`, and `settings` is
  what was stored before. Equality is of the keys, not of the spelling:
  `shift+ctrl+a` = `ctrl+shift+a`, `cmd` = `command`, `alt` = `option`,
  `return` = `enter`, `right_ctrl` = `ctrl_r`. It is decided on the values that
  would be stored, after a refused field has fallen back, so the fallback
  cannot produce the conflict either. This is what makes a capture field that
  sends only the key just pressed safe: `settings.set_hotkeys {mode, start:
  "<Stop's key>"}` is refused, not saved with the message under another field.
  The conflict messages are keyed as before (`stop`, `cancel`; a push-to-talk
  duplicate is keyed `ptt`).

`saved` is true when the request was written. `live` is false when the running
listener could not take the change (the config is saved anyway); `live_error`
says why. Reaches the listener in one `change_hotkey_configs` batch.

### `settings.reset_hotkeys`

Mode and the four bindings back to the shipped platform defaults, applied to the
running listener (the Qt screen forgot this half). Auto-paste, the push-to-talk
minimum hold and VAD are untouched.

### `settings.set` keys

| Key | Value | Live effect |
| --- | --- | --- |
| `clipboard.auto_paste` | bool | `ClipboardManager.update_auto_paste` |
| `clipboard.preserve_clipboard` | bool | `ClipboardManager.preserve_clipboard` |
| `audio.mute_output_on_record` | bool; `unsupported` off macOS | read at the start of each recording |
| `audio.vad_enabled` | bool | `models.push_vad` (backend `set_vad_enabled`, on a thread) |
| `audio.max_duration` | int seconds, 0..3600 | `AudioRecorder.max_duration` |
| `audio_feedback.enabled` | bool | the sound player's `enabled` |
| `hotkey.push_to_talk_min_hold_seconds` | number 0..2 | listener batch |
| `ui.theme` | `system` / `light` / `dark` | renderer applies |
| `ui.palette` | one of the kit's six | renderer applies |
| `ui.language` | `en` / `ru` | renderer applies |
| `ui.text_scale` | number, clamped to 0.85..1.75 | renderer applies |

`ui.palette` is a new key in `DEFAULT_CONFIG` (default `gruvbox`); the Qt
interface does not read it.

A value that is not in the allowed set is `bad_params` and nothing is written:
a wrong type (`1` for a boolean, `"300"` for a number, `null`), `NaN`, infinity
and numbers too large for a float are all refused, and so is a key that is not in
the table above.
A failure of only the live half does not undo the save: `live_error` is set.

### Settings object (`settings.get`)

```
platform, version,
hotkey:   {mode, start, stop, cancel, push_to_talk_key, push_to_talk_min_hold_seconds}
hotkey_errors: {field: Issue}        # what is on disk but would not validate
defaults: {mode, start, stop, cancel, push_to_talk_key}
audio:    {device, mute_output_on_record, vad_enabled, max_duration}
clipboard: {auto_paste, preserve_clipboard}
audio_feedback: {enabled}
ui:       {theme, palette, language, text_scale}   # normalised, never raises
capabilities: {mute_output, recording_stack}
choices:  {text_scales, palettes, languages[{code,name}], themes, modes,
           ptt_solo_keys, max_duration_cap, min_hold_range}
```

A legacy config with `mode: two_keys` and Start equal to Stop reads as
`toggle`. In `toggle`, `hotkey.stop` is Start.

`settings.get` never fails on what the file holds: a value of the wrong type
(`audio.max_duration: abc`, a number where a hotkey string belongs, a string where
a boolean belongs) reads as its default, clamped to its range.

## Methods: devices

| Method | Params | Result |
| --- | --- | --- |
| `devices.list` | none | `{devices: [{index, name}], current}`; `current` null is the system default. A list that cannot be read is empty |
| `devices.select` | `{device: int \| null}` | `{device}`; applied to the recorder, then persisted to `audio.device`. The device must be one `devices.list` returns, or `null`; anything else (an index that no longer exists, any index while there is no recording stack) is `device_failed` with `field: "device"` and **nothing is stored or switched**. `device_failed` also when the recorder refuses; nothing is stored then either |
| `devices.test` | none | `{started: true, seconds}` at once; the result arrives by event |

`devices.test` errors: `no_stack`, `no_recorder`, `busy` (a recording or
transcription is in progress, or another test is running).

## Methods: permissions

Every gate reads `null` off macOS and every banner is `hidden`.

| Method | Params | Result |
| --- | --- | --- |
| `permissions.status` | none | `{platform, applicable, listen, post_event, microphone, banners}` |
| `permissions.refresh` | none | same; applies and publishes a grant made since the last call |
| `permissions.request` | `{kind}` | `{action: "prompt" \| "opened_settings" \| "none"}` |
| `permissions.open_settings` | `{kind}` | `{opened}` |

`kind` is `accessibility` (listening to hotkeys), `post_event` (the auto-paste
keystrokes) or `microphone`. `banners` is
`{accessibility: hidden|untrusted, microphone: hidden|not_determined|denied,
post_event: hidden|untrusted}`. The accessibility banner is hidden for push-to-talk
on a solo modifier (the path known to work); the post-event banner needs
auto-paste on.

`permissions.request` asks the OS; when it refuses without a prompt it opens the
right System Settings pane, so the click is never a no-op, and re-reads the
state 250 ms later. The renderer calls `permissions.refresh` when Settings is
shown and when the window regains focus. A False to True flip rebuilds the
hotkey listener: no restart.

## Events

| Event | Sticky | Payload |
| --- | --- | --- |
| `mic_test` | yes | `{phase: "running", seconds}`, then `{phase: "done", verdict: "silent"\|"quiet"\|"good", peak, rms}` or `{phase: "error", reason}` |
| `mic_level` | no | `{level: 0..1}` at 20 Hz while a test runs |
| `permissions` | yes | the `permissions.status` payload, when a refresh finds a change |
| `settings` | no | `{keys}`; see `rpc-core.md`. Emitted after `settings.set`, `settings.set_hotkeys`, `settings.reset_hotkeys` and `devices.select` |

Verdict thresholds are in `app/mic_test.py` (peak below the first is silent,
below the second is quiet).

Errors: `bad_params`, `unsupported`, `no_stack`, `no_recorder`, `busy`,
`device_failed`, `unknown_method`, `internal`.
