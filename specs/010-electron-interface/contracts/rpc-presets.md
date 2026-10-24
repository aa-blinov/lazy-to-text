# Contract: post-processing (presets and the language-model switch)

Transport and envelope: see `plan.md`. Format as `rpc-core.md`. Handler:
`app/server/handlers/presets.py`. Reference for every write:
`AppController._on_llm_changed` and the `_on_preset_*` family.

A preset is stored as the `llm.profiles` list plus the flat keys
(`provider`, `model`, `base_url`, `api_key`, `mode`, `timeout_s`,
`reasoning_effort`, `max_tokens`) mirrored from the active one, exactly as
the Qt controller writes them, so either interface reads what the other
saved. The flat keys are re-mirrored whenever the active preset is edited,
activated, deleted, or has its key reset.

## Methods

Every method that changes something answers with the **state** object, so a
screen never merges a partial reply:

```
state = {
  enabled:      bool,        // llm.enabled, the global switch
  active_id:    string,      // the default preset
  override_id:  string,      // pinned for the next dictation, "" for none; never persisted
  profiles: [{id, name, provider, model, base_url, api_key_set, base_url_error, mode,
              custom_prompt, timeout_s, reasoning_effort, max_tokens, remote}]
}
```

**The key never crosses the channel.** No reply carries `api_key`; `api_key_set`
(bool) says whether the preset holds one. The key is written by `presets.update`
and removed by `presets.reset_key`, and nothing reads it back. The same holds for
`app.snapshot` (see `rpc-core.md`) and, as before, for the Hugging Face token
(`models.hf_token.get` answers `{set}`).

`remote` is derived (`not is_local_url(resolved address)`), never stored. An
address that cannot be parsed counts as remote. `base_url_error` is `null`, or
the sentence saying why the stored address is not usable (a value written by a
hand edit or an older build; a new one is refused at save time). A preset with a
bad stored address is still returned and every `presets.*` call keeps working,
so the screen can show the sentence and let the user correct the field.

| Method | Params | Result |
| --- | --- | --- |
| `presets.catalogue` | none | `{providers: [{id, label, url, local}], modes: [{id, label, description}], efforts: [...], shared_note, limits: {timeout_min, timeout_max, timeout_default, max_tokens_max}}`. Labels are English source text, translated by the renderer |
| `presets.get` | none | `state`. Writes the implicit preset out as the first real one when `llm.profiles` is empty (once; the flat keys are untouched) |
| `presets.privacy` | `{base_url, provider}` | `{local, valid, message}`. An empty address resolves to the provider's default, as a request would. `valid: false` (with the sentence in `message`, `local: false`) for an address that is not acceptable; it is a normal answer while the user types, never an error |
| `llm.set_enabled` | `{enabled: bool}` | `state`. Writes `llm.enabled` and nothing else |
| `presets.update` | `{profile: {id, ...fields}}` | `state`. Rewrites the preset: stored fields merged under the fields that were sent, which are checked first (see "What a field may hold"). Nothing is written when any field is refused |
| `presets.create` | none | `state` plus `created_id`. A copy of the first preset named "<name> copy" with a fresh id, **without its key** (the new preset is pointed somewhere new; the key must not follow it) |
| `presets.duplicate` | `{id}` | `state` plus `created_id`. A copy of that preset including its key |
| `presets.delete` | `{id}` | `state`. If it was the active one the first remaining becomes active; an override naming it is dropped |
| `presets.activate` | `{id}` | `state` |
| `presets.reset_key` | `{id}` | `state`. Clears that preset's key; the flat `api_key` only when it is the active one. The only way to remove a key |
| `presets.set_override` | `{id}` or `{}` | `state`. Pins a preset on the state manager for the next dictation; `""` or absent unpins. Not written to the config |
| `presets.test` | `{profile}` or `{id}`, `test_id?` | `{started: true, test_id}` at once; the answer is the `llm_test` event. At most 3 tests run at once (the slot is held until the request thread has ended, past the deadline too); another is `busy` "Too many connection tests are running. Wait for one to finish." |

### What a field may hold (`presets.update`, and the `profile` of `presets.test`)

A refusal is `bad_params` with `error.field` naming the field and a sentence in
`message`; the sentence never repeats the value.

| Field | Rule |
| --- | --- |
| `base_url` | `""` (the provider's own address) or an `http://` / `https://` URL with a host; no spaces or line breaks, no `user:password@`, at most 2048 characters, a parsable port and brackets |
| `api_key` | **Only a non-empty string replaces the stored key.** Absent, `null`, `""` and whitespace all keep it (the screen does not hold the key, so a draft that was not typed into sends nothing). No spaces, control characters or characters outside Latin-1; at most 1024 |
| `provider` | one of `presets.catalogue.providers[].id` |
| `mode` | one of `presets.catalogue.modes[].id` |
| `reasoning_effort` | `""` or one of `presets.catalogue.efforts` |
| `timeout_s` | a finite number, clamped to 1..600 (0 and -1 become 1) |
| `max_tokens` | a finite number, clamped to 0..32768 |
| `name` | text, at most 80 characters, no control characters |
| `model` | text, at most 200 characters, no control characters |
| `custom_prompt` | text, at most 20000 characters (line breaks allowed) |

A field of the wrong type, or `NaN` / infinity, is refused, not replaced by a
default. Fields not listed (the derived `remote`, `api_key_set`,
`base_url_error`) are ignored, so a screen may send back what it was given.
A field that was not sent keeps its stored value even if that value would be
refused today.

### The connection test

It sends a fixed sentence, never the user's words, with the preset's own
provider, address, model, key, wording, effort, cap and timeout (the editor's
current values when `profile` is given, so an unsaved field is what gets
tested). When `profile.id` names a stored preset and no key is sent, the stored
key is used: the screen never has it. A field that is not acceptable does not
fail the call; the test starts and `llm_test` says why (`ok: false`, the
sentence in `message`), so the screen has one place to look. The request has an
overall deadline of `timeout_s` plus three seconds, after which `llm_test` says
the server did not finish answering. Nothing about the request or the reply is
logged.

Errors: `bad_params` (with `field`), `not_found` (no such preset), `last_preset`
(`presets.delete` on the only preset), `no_stack` (`presets.set_override`
without a recording stack).

## Events

| Event | Sticky | Payload |
| --- | --- | --- |
| `presets` | no | `{}`: the list, the active id or the switch changed (any screen or process); re-read with `presets.get` |
| `llm_test` | no (last one kept, see `app.last_events`) | `{test_id, id, ok, message, elapsed_ms}`. `message` is the failure in the client's own words (HTTP status, "could not reach <url> (ConnectionRefusedError)", "no model is named"); it never contains the key |
