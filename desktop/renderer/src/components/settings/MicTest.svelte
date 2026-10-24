<script>
  // The three-second microphone test: a live level while it listens, then a
  // verdict in plain words. Raw peak and rms are shown small for a bug report.
  import { createEventDispatcher } from 'svelte';
  import { Button, Notice } from '@monos/ui';
  import { t } from '../../lib/i18n.js';
  import { fmt } from '../../lib/hotkey.js';
  import LevelMeter from '../LevelMeter.svelte';

  export let test = { phase: 'idle', level: 0 };
  export let disabled = false;

  const dispatch = createEventDispatcher();

  $: running = test.phase === 'running';
  $: verdict = test.phase === 'done' ? test.verdict : null;

  const TONE = { silent: 'danger', quiet: 'warning', good: 'success' };

  function message(v, tr) {
    if (v === 'silent') return tr('No sound detected. Check the selected microphone.');
    if (v === 'quiet') return tr('Very quiet. Speak louder or raise the input level in Windows sound settings.');
    return tr('Looks good.');
  }
</script>

<div class="flex flex-col gap-2">
  <div class="flex flex-wrap items-center gap-3">
    <Button
      variant="secondary"
      size="sm"
      disabled={disabled || running}
      loading={running}
      title={$t('Records three seconds and shows the input level.')}
      on:click={() => dispatch('start')}
    >
      {$t('Test microphone')}
    </Button>
    {#if running || test.phase === 'done'}
      <LevelMeter level={test.phase === 'done' ? test.peak : test.level} active={running || test.phase === 'done'} label={$t('Microphone level')} />
    {/if}
    {#if running}
      <span class="text-xs text-ink-soft" role="status">{$t('Listening… speak now (3 s)')}</span>
    {/if}
  </div>

  {#if verdict}
    <Notice tone={TONE[verdict] ?? 'neutral'}>
      <span>{message(verdict, $t)}</span>
      <span class="ml-2 text-whisper text-ink-faint" title={$t('Amplitude on a 0–1 scale; peak is the loudest sample, rms the average power.')}>
        peak {test.peak.toFixed(3)}, rms {test.rms.toFixed(3)}
      </span>
    </Notice>
  {:else if test.phase === 'error'}
    <Notice tone="danger">{fmt($t('Test failed: %1'), test.reason)}</Notice>
  {/if}
</div>
