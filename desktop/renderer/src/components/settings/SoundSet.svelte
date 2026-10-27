<script>
  // The start and end sounds, chosen as a pair. A set is a start and its end made
  // together; "Your own files" lets the two be any WAV files, which is the only
  // way for them to come from different places. Picking a set plays it.
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

  function failed(title, err) {
    toast({ title, description: translateRuntime(err.message), tone: 'danger', duration: 0 });
  }

  async function pickFile(title) {
    const open = window.l2t?.dialog?.openFile;
    if (!open) {
      toast({ title: $t('Choosing a file needs the desktop app.'), tone: 'warning', duration: 4000 });
      return null;
    }
    return open({ title, filters: [{ name: $t('WAV sound'), extensions: ['wav'] }] });
  }

  async function useFile(slot, title) {
    const path = await pickFile(title);
    if (!path) return false;
    try {
      const added = await addSound(path);
      const result = await chooseFile(slot, added.value);
      if (result.save_error) {
        toast({ title: $t('Not saved to disk'), description: translateRuntime(result.save_error), tone: 'danger', duration: 0 });
      }
      await previewSound(added.value);
      return true;
    } catch (err) {
      failed($t('Could not use that file'), err);
      return false;
    }
  }

  async function onChange(event) {
    const next = event.detail.value;
    if (next === CUSTOM) {
      // Two files, start first; leaving the first dialog empty changes nothing.
      shown = theme;
      if (await useFile('start', $t('Choose the start sound'))) await useFile('stop', $t('Choose the end sound'));
      return;
    }
    try {
      const result = await chooseSet(next);
      if (result.save_error) {
        toast({ title: $t('Not saved to disk'), description: translateRuntime(result.save_error), tone: 'danger', duration: 0 });
      }
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
    <IconButton label={$t('Play the start sound')} size="sm" disabled={!$soundList.start} on:click={() => play($soundList.start)}>
      <Play size={14} strokeWidth="1.7" />
    </IconButton>
    <IconButton label={$t('Play the end sound')} size="sm" disabled={!$soundList.stop} on:click={() => play($soundList.stop)}>
      <Play size={14} strokeWidth="1.7" class="rotate-90" />
    </IconButton>
  </div>
</SettingRow>

{#if theme === CUSTOM}
  {#each [['start', $t('Start sound'), $t('Choose the start sound')], ['stop', $t('End sound'), $t('Choose the end sound')]] as [slot, label, title]}
    <SettingRow {label}>
      <div class="flex items-center gap-2">
        <span class="min-w-0 flex-1 truncate text-sm text-ink" data-testid="sound-name-{slot}">
          {soundName($soundList, $soundList[slot], $t)}
        </span>
        <Button variant="secondary" size="sm" on:click={() => useFile(slot, title)}>{$t('Choose a file…')}</Button>
        {#if isOwn($soundList, $soundList[slot])}
          <Button variant="text" size="sm" on:click={() => onRemove($soundList[slot])}>{$t('Remove')}</Button>
        {/if}
      </div>
    </SettingRow>
  {/each}
{/if}
