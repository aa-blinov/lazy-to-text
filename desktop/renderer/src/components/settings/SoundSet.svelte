<script>
  // The start and end sounds. A set is a start and its end made together, so
  // choosing one sets both. Each cue can also take a WAV file of its own, on
  // its own: only the start, only the end, or both.
  import { Select, IconButton, Button } from '@monos/ui';
  import { Play } from 'lucide-svelte';
  import { t, translateRuntime } from '../../lib/i18n.js';
  import { toast } from '../../lib/toast.js';
  import {
    soundList, setOptions, chooseSet, chooseFile, previewSound, previewPair, addSound, removeSound,
    isOwn, soundName, CUSTOM,
  } from '../../lib/sounds.js';
  import SettingRow from './SettingRow.svelte';

  $: options = setOptions($soundList, $t);
  $: theme = $soundList.theme;
  // The control follows the store; a refused pick has to put it back.
  let shown = '';
  $: shown = theme;

  const CUES = [
    { slot: 'start', label: 'Start sound', hint: 'Played when a recording starts.', title: 'Choose the start sound' },
    { slot: 'stop', label: 'End sound', hint: 'Played when a recording ends.', title: 'Choose the end sound' },
  ];

  function failed(title, err) {
    toast({ title, description: translateRuntime(err.message), tone: 'danger', duration: 0 });
  }

  function savedWarning(result) {
    if (result?.save_error) {
      toast({ title: $t('Not saved to disk'), description: translateRuntime(result.save_error), tone: 'danger', duration: 0 });
    }
  }

  async function useFile(slot, title) {
    const open = window.l2t?.dialog?.openFile;
    if (!open) {
      toast({ title: $t('Choosing a file needs the desktop app.'), tone: 'warning', duration: 4000 });
      return;
    }
    const path = await open({ title: $t(title), filters: [{ name: $t('WAV sound'), extensions: ['wav'] }] });
    if (!path) return;
    try {
      const added = await addSound(path);
      savedWarning(await chooseFile(slot, added.value));
      await previewSound(added.value);
    } catch (err) {
      failed($t('Could not use that file'), err);
    }
  }

  async function onChange(event) {
    const next = event.detail.value;
    if (next === CUSTOM) return;
    try {
      savedWarning(await chooseSet(next));
      await previewPair($soundList);
    } catch (err) {
      shown = theme;
      failed($t('Could not save'), err);
    }
  }

  async function onRemove(value) {
    try {
      await removeSound(value);
      toast({ title: $t('Sound removed'), tone: 'success', duration: 1500 });
    } catch (err) {
      failed($t('Could not remove the sound'), err);
    }
  }

  const play = (value) => previewSound(value).catch(() => {});
</script>

<SettingRow
  label={$t('Sounds')}
  hint={$t('A matched pair: one sound when the recording starts and its counterpart when it ends.')}
>
  <div class="flex items-center gap-2">
    <Select
      class="min-w-0 flex-1"
      size="sm"
      placeholder={$t('Sounds')}
      value={shown}
      {options}
      on:change={onChange}
    />
    <IconButton label={$t('Play both sounds')} size="sm" disabled={!$soundList.start && !$soundList.stop} on:click={() => previewPair($soundList).catch(() => {})}>
      <Play size={14} strokeWidth="1.7" />
    </IconButton>
  </div>
</SettingRow>

{#each CUES as cue (cue.slot)}
  <SettingRow label={$t(cue.label)} hint={$t(cue.hint)}>
    <div class="flex items-center gap-2">
      <span class="min-w-0 flex-1 truncate text-sm text-ink" data-testid="sound-name-{cue.slot}">
        {soundName($soundList, $soundList[cue.slot], $t)}
      </span>
      <IconButton label={$t('Play') + ': ' + $t(cue.label)} size="sm" disabled={!$soundList[cue.slot]} on:click={() => play($soundList[cue.slot])}>
        <Play size={14} strokeWidth="1.7" />
      </IconButton>
      <Button variant="secondary" size="sm" aria-label={$t('Choose a file…') + ': ' + $t(cue.label)} on:click={() => useFile(cue.slot, cue.title)}>
        {$t('Choose a file…')}
      </Button>
      {#if isOwn($soundList, $soundList[cue.slot])}
        <Button variant="text" size="sm" on:click={() => onRemove($soundList[cue.slot])}>{$t('Remove')}</Button>
      {/if}
    </div>
  </SettingRow>
{/each}
