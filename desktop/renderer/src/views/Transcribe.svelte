<script>
  import { onMount } from 'svelte';
  import { PageHeader, EmptyState, Button, Notice, Spinner, Checkbox, Select, FieldControl, tooltip } from '@monos/ui';
  import { FileAudio, Upload } from 'lucide-svelte';
  import { t } from '../lib/i18n.js';
  import { state as engineState, modelLoaded } from '../lib/backend.js';
  import { goTo } from '../lib/nav.js';
  import { modelState, refreshState } from '../components/models/store.js';
  import { middleEllipsis } from '../lib/text.js';
  import {
    run, status, dragging, extensions, presets, diarize, diarizationReady,
    browse, copyText, saveText, edit, loadPresets, setOverride, setStatus,
    describeFile, formatSize, formatElapsed, baseName, cancelRun, clearRun, canRunAgain, transcribeAgain,
  } from '../lib/transcribe.js';

  const TONES = { busy: 'info', done: 'success', warning: 'warning', error: 'danger', info: 'info' };
  const EXAMPLES = ['MP3', 'WAV', 'M4A', 'MP4', 'MKV'];

  $: busy = $run.phase === 'busy';
  $: hasText = $run.phase === 'done' && $run.text.trim().length > 0;
  $: loaded = $run.path !== null;
  $: supported = $extensions.map((e) => e.slice(1).toUpperCase()).join(', ');

  // The line under the file name: what is happening while busy, the facts
  // once there is a result, and "Failed" when a run ended in an error.
  $: detail = busy
    ? [$t('Transcribing…'), formatSize($run.size), $run.elapsed >= 1 ? formatElapsed($run.elapsed) : '', $run.diarized ? $t('By speakers') : '']
        .filter(Boolean).join(', ')
    : $run.phase === 'error'
      ? $t('Failed')
      : $run.phase === 'done' && !hasText
        ? $t('No speech recognised in that file.')
        : describeFile($run);

  // The picker shows the pinned preset if there is one, else the default.
  let shown = '';
  $: pinned = $presets.override_id !== '';
  $: several = $presets.presets.length > 1;
  $: shown = $presets.override_id || shown || $presets.active_id;
  // A long name is shortened in the middle so near-identical names differ in the list.
  $: options = $presets.presets.map((p) => ({ value: p.id, label: middleEllipsis(p.name) }));
  $: shownName = $presets.presets.find((p) => p.id === shown)?.name ?? '';
  // Idle with nothing loaded: dropping a file cannot work, so say so up front.
  $: noModel = $engineState === 'idle' && !$modelLoaded;
  // A model that is on disk and only not running is not "no model".
  $: onDisk = Boolean($modelState.active && $modelState.cached?.[$modelState.active]);

  // The model has to be on disk before the box can be ticked: it is greyed out
  // until then and says why, and a tick is dropped if the model goes away. The
  // list of downloaded models is read after the screen opens; until it has been,
  // an empty list means "not known yet", not "not downloaded".
  $: canDiarize = diarizationReady($modelState);
  $: modelsKnown = Object.keys($modelState.cached || {}).length > 0;
  $: if (modelsKnown && !canDiarize && $diarize) diarize.set(false);
  // The file on screen was made differently from how the box says the next run
  // will be: offer to redo it, rather than guess that a tick meant that.
  $: again = canRunAgain($run, $diarize) && (canDiarize || !$diarize);

  function onToggle(event) {
    setOverride(event.target.checked ? shown : '');
  }

  function onPick(event) {
    shown = event.detail.value;
    // Choosing a row while the box is unticked is a decision about this
    // run, so it ticks the box rather than doing nothing visible.
    setOverride(shown);
  }

  onMount(() => {
    loadPresets();
    refreshState();
  });
</script>

<div class="mx-auto w-full max-w-6xl flex h-full min-h-0 flex-col gap-4 p-6">
  <PageHeader
    title={$t('Transcribe')}
    description={$t('Turn an audio or video file into text you can edit.')}
  >
    <svelte:fragment slot="actions">
      <Button variant={hasText ? 'secondary' : 'primary'} disabled={busy} on:click={browse}>
        {$t('Browse…')}
      </Button>
    </svelte:fragment>
  </PageHeader>

  <!-- One voice: a refused run already says it, with the same button. -->
  {#if noModel && $status?.action !== 'models'}
    <div class="shrink-0" data-testid="no-model">
      <Notice tone="warning" title={onDisk ? $t('Model not loaded') : $t('No model yet')}>
        {$t('Transcribing needs a model. Download one, or load the one you chose, in Models.')}
        <Button variant="text" size="sm" on:click={() => goTo('models')}>{$t('Open Models')}</Button>
      </Notice>
    </div>
  {/if}

  <div
    class="shrink-0 rounded-ui border-2 border-dashed px-6 py-4 transition-colors duration-fast
      {$dragging ? 'border-accent bg-surface' : 'border-line'}"
    data-testid="drop-zone"
    data-state={$dragging ? 'active' : 'idle'}
  >
    {#if !loaded}
      <button
        type="button"
        class="flex min-h-24 w-full flex-col items-center justify-center gap-1 text-center disabled:cursor-not-allowed"
        title={$t('Supported: %1').replace('%1', supported)}
        disabled={busy}
        on:click={browse}
      >
        <Upload size={20} aria-hidden="true" class="text-ink-faint" />
        <span class="text-sm text-ink">{$t('Drop an audio or video file here')}</span>
        <span class="text-xs text-ink-faint">{EXAMPLES.join(', ')}</span>
      </button>
    {:else}
      <div class="flex items-center gap-3" aria-live="polite">
        <FileAudio size={20} aria-hidden="true" class="shrink-0 text-ink-faint" />
        <div class="min-w-0 flex-1">
          <div class="truncate text-sm text-ink" data-testid="file-name" title={$run.path}>
            {baseName($run.path)}
          </div>
          <div class="truncate text-xs text-ink-faint" data-testid="file-detail">{detail}</div>
        </div>
        {#if busy}
          <Spinner size="sm" label={$t('Transcribing…')} />
          <Button variant="secondary" size="sm" on:click={cancelRun}>{$t('Cancel')}</Button>
        {:else}
          <Button variant="text" size="sm" on:click={clearRun}>{$t('Clear')}</Button>
        {/if}
      </div>
    {/if}
  </div>

  <div class="flex shrink-0 flex-wrap items-center gap-3">
    <span
      data-testid="diarize-option"
      use:tooltip={canDiarize
        ? ''
        : $t('Download the diarization model in Models to split a file by speakers.')}
    >
      <Checkbox
        checked={$diarize}
        disabled={!canDiarize}
        on:change={(e) => diarize.set(e.target.checked)}
      >
        {$t('Split by speakers (diarization)')}
      </Checkbox>
    </span>
    {#if !canDiarize && modelsKnown}
      <Button variant="text" size="sm" on:click={() => goTo('models')}>{$t('Get the model')}</Button>
    {:else if again}
      <Button variant="secondary" size="sm" data-testid="transcribe-again" on:click={transcribeAgain}>
        {$diarize ? $t('Transcribe again, split by speakers') : $t('Transcribe again, as one text')}
      </Button>
    {:else if busy}
      <span class="text-xs text-ink-faint" data-testid="diarize-hint">{$t('Applies to the next file.')}</span>
    {/if}
    {#if hasText}
      <Button on:click={copyText}>{$t('Copy')}</Button>
      <Button variant="secondary" on:click={saveText}>{$t('Save .txt')}</Button>
    {/if}
    {#if several}
      <div
        class="ml-auto flex min-w-0 max-w-full flex-wrap items-end gap-x-3 gap-y-2"
        title={$t('Use the chosen preset for the next dictation only, without changing the default.')}
      >
        <Checkbox class="[&>span:first-child]:shrink-0" checked={pinned} on:change={onToggle}>{$t('Preset for this file')}</Checkbox>
        <span class="min-w-0 max-w-[24rem]" title={shownName}>
        <Select
          size="sm"
          class="min-w-32 max-w-full"
          value={shown}
          {options}
          label={$t('Preset')}
          on:change={onPick}
        />
        </span>
      </div>
    {/if}
  </div>

  {#if $status}
    <div class="shrink-0" data-testid="status" data-kind={$status.kind}>
      <Notice tone={TONES[$status.kind] ?? 'info'} dismissible dismissLabel={$t('Dismiss')} on:dismiss={() => setStatus('')}>
        {$status.text}
        {#if $status.action === 'models'}
          <Button variant="text" size="sm" on:click={() => goTo('models')}>{$t('Open Models')}</Button>
        {/if}
      </Notice>
    </div>
  {/if}

  <div class="min-h-0 flex-1">
    {#if hasText}
      <FieldControl
        as="textarea"
        variant="boxed"
        bare={false}
        class="h-full w-full resize-none py-3 leading-relaxed"
        value={$run.text}
        aria-label={$t('Transcript')}
        data-testid="transcript"
        on:input={(e) => edit(e.detail.currentTarget.value)}
      />
    {:else}
      <EmptyState
        title={$run.phase === 'done' ? $t('No speech recognised in that file.') : $t('No transcript yet')}
        description={$run.phase === 'done' ? '' : $t('The text appears here once you drop a file, ready to edit.')}
      />
    {/if}
  </div>
</div>
