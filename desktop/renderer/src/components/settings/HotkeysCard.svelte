<script>
  // Recording mode and the bindings it uses. The form keeps its own draft:
  // a binding the runtime refuses stays on screen with the reason beside it,
  // while the runtime keeps the last value that was valid. Every change is
  // saved as it is made; there is no Save button.
  import { createEventDispatcher } from 'svelte';
  import { RadioGroup, Button, Slider, toast } from '@monos/ui';
  import { t } from '../../lib/i18n.js';
  import { fmt } from '../../lib/hotkey.js';
  import { saveHotkeys, resetHotkeys, saveValue, remembered } from '../../lib/settings.js';
  import SettingRow from './SettingRow.svelte';
  import HotkeyCapture from './HotkeyCapture.svelte';

  export let hotkey; // settings.hotkey from settings.get
  export let defaults;
  export let platform = 'linux';
  export let storedErrors = {};
  export let ready = true;

  const dispatch = createEventDispatcher();

  let draft = fromStored(hotkey);
  let errors = {};
  let held = hotkey.push_to_talk_min_hold_seconds;
  let seq = 0;
  let resetting = false;

  render(storedErrors);

  function fromStored(h) {
    return { mode: h.mode, start: h.start, stop: h.stop, cancel: h.cancel, ptt: h.push_to_talk_key };
  }

  function render(raw) {
    const next = {};
    for (const [field, issue] of Object.entries(raw || {})) {
      next[field] = fmt($t(issue.template), ...(issue.args || [])) || issue.message;
    }
    errors = next;
  }

  $: ptt = draft.mode === 'push_to_talk';
  $: toggle = draft.mode === 'toggle';

  $: modes = [
    { value: 'two_keys', label: $t('Two keys (Start + Stop)'), description: $t('Separate hotkeys to start and to stop.') },
    { value: 'toggle', label: $t('One key: press to start and stop'), description: $t('One hotkey switches between idle and recording.') },
    { value: 'push_to_talk', label: $t('Push to talk: hold to record'), description: $t('Hold one key (for example, right Cmd) to record, release it to transcribe. Best for short dictation.') },
  ];

  async function save({ quiet = false } = {}) {
    const mine = ++seq;
    try {
      const result = await saveHotkeys(draft);
      if (mine !== seq) return;
      render(result.errors);
      if (result.save_error) {
        toast({ title: $t('Not saved to disk'), description: $t(result.save_error), tone: 'danger', duration: 0 });
      } else if (!result.live) {
        toast({
          title: $t('Saved, but not applied yet'),
          description: result.live_error ? $t(result.live_error) : '',
          tone: 'warning',
          duration: 6000,
        });
      } else if (!quiet && Object.keys(result.errors).length === 0) {
        toast({ title: $t('Saved'), tone: 'success', duration: 1500 });
      }
    } catch (err) {
      if (mine === seq) toast({ title: $t('Could not save'), description: err.message, tone: 'danger', duration: 0 });
    }
  }

  function setMode(next) {
    if (next === draft.mode) return;
    if (next === 'toggle') {
      remembered.stop = draft.stop;
      draft.stop = draft.start;
    } else if (draft.mode === 'toggle') {
      const back = remembered.stop;
      draft.stop = back && back.toLowerCase() !== draft.start.toLowerCase() ? back : defaults.stop;
      remembered.stop = null;
    }
    draft.mode = next;
    draft = draft;
    save();
  }

  function setField(field, text) {
    draft[field] = text;
    if (field === 'start' && toggle) draft.stop = text;
    draft = draft;
    save();
  }

  async function reset() {
    resetting = true;
    try {
      const result = await resetHotkeys();
      draft = fromStored(result.settings.hotkey);
      held = result.settings.hotkey.push_to_talk_min_hold_seconds;
      render(result.settings.hotkey_errors);
      toast({ title: $t('Hotkeys reset to defaults'), tone: 'success', duration: 2500 });
      if (!result.live) {
        toast({ title: $t('Saved, but not applied yet'), description: result.live_error || '', tone: 'warning', duration: 6000 });
      }
    } catch (err) {
      toast({ title: $t('Could not reset hotkeys'), description: err.message, tone: 'danger', duration: 0 });
    } finally {
      resetting = false;
    }
  }

  async function saveHold(event) {
    const value = event.detail;
    try {
      await saveValue('hotkey.push_to_talk_min_hold_seconds', value);
      toast({ title: $t('Saved'), tone: 'success', duration: 1500 });
    } catch (err) {
      held = hotkey.push_to_talk_min_hold_seconds;
      toast({ title: $t('Could not save'), description: err.message, tone: 'danger', duration: 0 });
    }
  }

  const example = (key) => fmt($t('For example: %1'), key);
</script>

<SettingRow label={$t('Recording mode')} wide>
  <RadioGroup
    value={draft.mode}
    options={modes}
    label={$t('Recording mode')}
    disabled={!ready}
    on:change={(e) => setMode(e.detail)}
  />
</SettingRow>

{#if !ptt}
  <SettingRow label={$t('Start recording')}>
    <HotkeyCapture
      label={$t('Start recording')}
      value={draft.start}
      {platform}
      error={errors.start || ''}
      placeholder={example(defaults.start)}
      disabled={!ready}
      on:change={(e) => setField('start', e.detail)}
    />
  </SettingRow>

  <SettingRow label={$t('Stop recording')} hint={toggle ? $t('Same key as Start in this mode.') : ''}>
    <HotkeyCapture
      label={$t('Stop recording')}
      value={toggle ? draft.start : draft.stop}
      {platform}
      error={errors.stop || ''}
      placeholder={example(defaults.stop)}
      disabled={!ready || toggle}
      on:change={(e) => setField('stop', e.detail)}
    />
  </SettingRow>
{:else}
  <SettingRow label={$t('Push-to-talk key')} hint={$t('A lone modifier works in push-to-talk mode. Hold it to record, let go to transcribe.')}>
    <HotkeyCapture
      label={$t('Push-to-talk key')}
      value={draft.ptt}
      {platform}
      allowSolo
      error={errors.ptt || ''}
      placeholder={$t('For example: right_cmd, right_alt or fn. A lone modifier works in push-to-talk mode.')}
      disabled={!ready}
      on:change={(e) => setField('ptt', e.detail)}
    />
  </SettingRow>

  <SettingRow label={$t('Minimum hold')} forId="settings-min-hold" hint={$t('A tap shorter than this is ignored, so a glancing touch does not start a recording.')}>
    <Slider
      min={0}
      max={1}
      step={0.05}
      id="settings-min-hold"
      bind:value={held}
      format={(v) => $t('%1 ms').replace('%1', String(Math.round(v * 1000)))}
      disabled={!ready}
      on:change={saveHold}
    />
  </SettingRow>
{/if}

<SettingRow
  label={$t('Cancel recording')}
  hint={toggle || ptt ? $t('Cancel is available in two-key mode only.') : $t('Cancel discards the current buffer instead of transcribing.')}
>
  <HotkeyCapture
    label={$t('Cancel recording')}
    value={draft.cancel}
    {platform}
    allowEmpty
    error={!toggle && !ptt ? errors.cancel || '' : ''}
    placeholder={fmt($t('For example: %1. Leave it empty to turn this off.'), defaults.cancel)}
    disabled={!ready || toggle || ptt}
    on:change={(e) => setField('cancel', e.detail)}
  />
</SettingRow>

<div class="flex justify-end pt-3">
  <Button variant="secondary" size="sm" loading={resetting} aria-label={$t('Reset hotkeys to defaults')} on:click={reset}>
    {$t('Reset hotkeys')}
  </Button>
</div>
