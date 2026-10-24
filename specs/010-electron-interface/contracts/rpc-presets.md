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
  profiles: [{id, name, provider, model, base_url, api_key, mode, custom_prompt,
              timeout_s, reasoning_effort, max_tokens, remote}]
}
```

`remote` is derived (`not is_local_url(resolved address)`), never stored.

| Method | Params | Result |
| --- | --- | --- |
| `presets.catalogue` | none | `{providers: [{id, label, url, local}], modes: [{id, label, description}], efforts: [...], shared_note, limits: {timeout_min, timeout_max, timeout_default, max_tokens_max}}`. Labels are English source text, translated by the renderer |
| `presets.get` | none | `state`. Writes the implicit preset out as the first real one when `llm.profiles` is empty (once; the flat keys are untouched) |
| `presets.privacy` | `{base_url, provider}` | `{local: bool}`. An empty address resolves to the provider's default, as a request would |
| `llm.set_enabled` | `{enabled: bool}` | `state`. Writes `llm.enabled` and nothing else |
| `presets.update` | `{profile: {id, ...fields}}` | `state`. Rewrites the whole preset (stored fields merged under the given ones, then normalised: timeout clamped to 1..600, max tokens to 0..32768, effort to the known list, name falls back to the id) |
| `presets.create` | none | `state` plus `created_id`. A copy of the first preset named "<name> copy" with a fresh id |
| `presets.duplicate` | `{id}` | `state` plus `created_id`. A copy of that preset including its key |
| `presets.delete` | `{id}` | `state`. If it was the active one the first remaining becomes active; an override naming it is dropped |
| `presets.activate` | `{id}` | `state` |
| `presets.reset_key` | `{id}` | `state`. Clears that preset's key; the flat `api_key` only when it is the active one |
| `presets.set_override` | `{id}` or `{}` | `state`. Pins a preset on the state manager for the next dictation; `""` or absent unpins. Not written to the config |
| `presets.test` | `{profile}` or `{id}`, `test_id?` | `{started: true, test_id}` at once; the answer is the `llm_test` event |

The connection test sends a fixed sentence, never the user's words, with the
preset's own provider, address, model, key, wording, effort, cap and timeout
(the editor's current values when `profile` is given, so an unsaved field is
what gets tested). Nothing about the request or the reply is logged.

Errors: `bad_params`, `not_found` (no such preset), `last_preset`
(`presets.delete` on the only preset), `no_stack` (`presets.set_override`
without a recording stack).

## Events

| Event | Sticky | Payload |
| --- | --- | --- |
| `presets` | no | `{}`: the list, the active id or the switch changed (any screen or process); re-read with `presets.get` |
| `llm_test` | no | `{test_id, id, ok, message, elapsed_ms}`. `message` is the failure in the client's own words (HTTP status, "could not reach <url> (ConnectionRefusedError)", "no model is named"); it never contains the key |
