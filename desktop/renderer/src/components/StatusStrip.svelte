<script>
  // The persistent status strip: what the engine is doing, which model and
  // on what, how loaded the machine is, and, while a model loads, how far
  // it has got, with a way out.
  import { createEventDispatcher, onMount } from 'svelte';
  import { Badge, Progress, Button } from '@monos/ui';
  import { toast } from '../lib/toast.js';
  import { t } from '../lib/i18n.js';
  import { call, subscribe } from '../lib/rpc.js';
  import { state, engine, resources, progress, level, modelLoaded } from '../lib/backend.js';
  import { modelState, refreshState, selectModel } from './models/store.js';
  import LevelMeter from './LevelMeter.svelte';
  import { loadingDetail, percent, isAccelerator, resourceItems, loadTone } from './statusFormat.js';

  const dispatch = createEventDispatcher();
  let cancelling = false;
  let loadingNow = false;

  // What is on disk matters for the wording: a model that is there but not
  // running is a different state from having none, and has its own action.
  onMount(() => {
    refreshState();
    const stops = [subscribe('models', () => refreshState()), subscribe('model_load', () => refreshState())];
    return () => stops.forEach((stop) => stop());
  });
  $: if ($state === 'idle' && !$modelLoaded) refreshState();
  $: onDisk = Boolean($modelState.active && $modelState.cached?.[$modelState.active]);

  $: loading = $state === 'model_loading';
  $: recording = $state === 'recording';
  $: pct = percent($progress.current, $progress.total);
  $: detail = loadingDetail($progress);
  $: items = resourceItems($resources);
  $: provider = $engine.provider;
  $: label = {
    idle: $t('Idle'),
    recording: $t('Recording'),
    processing: $t('Processing'),
    model_loading: $t('Loading model…'),
    disconnected: $t('Engine stopped'),
  }[$state] ?? $state;
  $: tone = { recording: 'danger', processing: 'accent', model_loading: 'warning', disconnected: 'danger' }[$state] ?? 'neutral';
  $: down = $state === 'disconnected';

  async function loadActive() {
    loadingNow = true;
    try {
      await selectModel($modelState.active, { expectLoad: true });
    } finally {
      loadingNow = false;
    }
  }

  async function cancel() {
    cancelling = true;
    try {
      await call('models.cancel_load');
    } catch (error) {
      // The method belongs to the Models area; until it exists the strip says so.
      toast({
        title: $t('Could not cancel the load'),
        description: error.code === 'unknown_method' ? $t('Cancelling a load is not available in this build.') : error.message,
        tone: 'danger',
      });
    } finally {
      cancelling = false;
    }
  }
</script>

<footer
  class="flex h-9 shrink-0 items-center gap-4 border-t border-line bg-surface px-4 text-xs text-ink-soft"
  aria-label={$t('Status')}
  data-testid="status-strip"
>
  <span role="status" class="shrink-0" data-testid="state-pill">
    <Badge {tone} dot>{label}</Badge>
  </span>

  {#if loading}
    <div class="flex min-w-0 flex-1 items-center gap-3" data-testid="loading">
      <span class="hidden shrink-0 truncate sm:inline">{$engine.alias || $t('model')}</span>
      <div class="w-40 shrink-0">
        <Progress
          size="sm"
          value={pct ?? 0}
          indeterminate={pct === null}
          label={$t('Model loading progress')}
        />
      </div>
      <span class="min-w-0 truncate tabular-nums text-ink-faint">{detail}</span>
      <Button variant="text" size="sm" loading={cancelling} on:click={cancel}>{$t('Cancel')}</Button>
    </div>
  {:else}
    {#if down}
      <span class="min-w-0 truncate" data-testid="model">{$t('The engine is not running.')}</span>
    {:else if $modelLoaded}
      <span class="min-w-0 truncate" data-testid="model" title={$engine.alias}>
        {$t('Current model: %1').replace('%1', $engine.alias)}
      </span>
      <span
        class="shrink-0 {isAccelerator(provider) ? 'text-success-text' : 'text-ink-faint'}"
        title={$t('ONNX Runtime execution provider used by the loaded model')}
        data-testid="engine"
      >
        {$t('Engine')}: {provider}
      </span>
    {:else if onDisk}
      <!-- On disk and chosen, but the engine runs nothing: offer to load it. -->
      <span class="min-w-0 truncate" data-testid="model" title={$modelState.active}>{$t('Model not loaded')}</span>
      <Button
        variant="text"
        size="sm"
        loading={loadingNow}
        aria-label={$t('Load %1').replace('%1', $modelState.active)}
        on:click={loadActive}
      >
        {$t('Load')}
      </Button>
    {:else}
      <!-- Nothing on disk to run; only a loaded model is one the app can use. -->
      <span class="min-w-0 truncate" data-testid="model">{$t('No model yet')}</span>
      <Button variant="text" size="sm" on:click={() => dispatch('models')}>{$t('Open Models')}</Button>
    {/if}
    {#if recording}
      <LevelMeter level={$level} label={$t('Microphone level')} />
    {/if}
    <span class="flex-1"></span>
    {#if items.length}
      <ul class="hidden shrink-0 items-center gap-4 tabular-nums md:flex" aria-label={$t('Resources')} data-testid="resources">
        {#each items as item (item.key)}
          <li>
            <span class="text-ink-faint">{item.key}</span>
            <span class={loadTone(item.percent)}>{item.value}</span>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</footer>
