<script>
  // One cue's sound: a list to pick from, a button to hear it, and a way to add
  // a WAV file of one's own. Picking a sound plays it, so the choice is heard.
  import { Select, IconButton, Button } from '@monos/ui';
  import { Play } from 'lucide-svelte';
  import { t, translateRuntime } from '../../lib/i18n.js';
  import { toast } from '../../lib/toast.js';
  import {
    soundList, soundOptions, chooseSound, previewSound, addSound, removeSound, isCustom, ADD,
  } from '../../lib/sounds.js';
  import SettingRow from './SettingRow.svelte';

  /** 'start' or 'stop'. */
  export let cue;
  export let label = '';
  export let hint = '';

  $: value = $soundList[cue] ?? '';
  $: options = soundOptions($soundList, $t);
  $: own = isCustom($soundList, value);
  // The list is controlled by the store; a refused pick has to put the control back.
  let shown = '';
  $: shown = value;

  function failed(title, err) {
    toast({ title, description: translateRuntime(err.message), tone: 'danger', duration: 0 });
  }

  async function pick(next) {
    try {
      const result = await chooseSound(cue, next);
      if (result.save_error) {
        toast({ title: $t('Not saved to disk'), description: translateRuntime(result.save_error), tone: 'danger', duration: 0 });
      }
      await previewSound(next);
    } catch (err) {
      shown = value;
      failed($t('Could not save'), err);
    }
  }

  async function onChange(event) {
    const next = event.detail.value;
    if (next !== ADD) return pick(next);
    shown = value;
    const open = window.l2t?.dialog?.openFile;
    if (!open) {
      toast({ title: $t('Choosing a file needs the desktop app.'), tone: 'warning', duration: 4000 });
      return;
    }
    const path = await open({
      title: $t('Choose a sound'),
      filters: [{ name: $t('WAV sound'), extensions: ['wav'] }],
    });
    if (!path) return;
    try {
      const added = await addSound(path);
      await pick(added.value);
    } catch (err) {
      failed($t('Could not use that file'), err);
    }
  }

  async function onRemove() {
    try {
      await removeSound(value);
      toast({ title: $t('Sound removed'), tone: 'success', duration: 1500 });
    } catch (err) {
      failed($t('Could not remove the sound'), err);
    }
  }
</script>

<SettingRow {label} {hint}>
  <div class="flex items-center gap-2">
    <Select
      class="min-w-0 flex-1"
      size="sm"
      placeholder={label}
      value={shown}
      {options}
      on:change={onChange}
    />
    <IconButton label={$t('Play the sound')} size="sm" disabled={!value} on:click={() => previewSound(value).catch(() => {})}>
      <Play size={14} strokeWidth="1.7" />
    </IconButton>
    {#if own}
      <Button variant="text" size="sm" on:click={onRemove}>{$t('Remove')}</Button>
    {/if}
  </div>
</SettingRow>
