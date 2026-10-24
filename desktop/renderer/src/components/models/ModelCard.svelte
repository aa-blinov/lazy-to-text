<script>
  // One model in the catalogue. Presentational: the page decides what the
  // badge says and whether the card is locked, the card draws it and reports
  // what the user pressed.
  import { createEventDispatcher } from 'svelte';
  import { Card, Badge, Button, FilterChip, tooltip } from '@monos/ui';
  import { t } from '../../lib/i18n.js';
  import { fmt, formatSize } from './store.js';
  import InferenceSettings from './InferenceSettings.svelte';

  export let model;
  export let languages = [];
  export let active = false;
  export let cached = false;
  /** Loading state of the active card: null, or {tone, label}. */
  export let badge = null;
  export let locked = false;
  export let deleting = false;
  export let familyActive = false;
  /** The first-run card leads with the pitch and has no Delete or settings. */
  export let compact = false;

  const dispatch = createEventDispatcher();
  let expanded = false;

  $: loading = badge?.tone === 'warning';
  $: canDelete = cached && !active && !loading && !compact;
  $: primaryLabel = cached ? $t('Select') : $t('Download');
  $: hasSettings = active && !compact && model.inference?.kind;

  $: facts = [
    model.wer != null ? fmt($t('WER %1%'), model.wer) : fmt($t('WER %1'), '—'),
    model.rtf ? fmt($t('RTF %1'), model.rtf) : fmt($t('RTF %1'), '—'),
    formatSize(model.size_mb),
    fmt($t('%1 GB VRAM'), model.vram_gb.toFixed(1)),
  ];
  $: factHints = [
    $t('Word error rate on our Russian test set. Lower is better.'),
    $t('Real-time factor: processing seconds per second of audio. Lower is faster.'),
    $t('Download size.'),
    $t('Video memory the model needs to run.'),
  ];

  function openLink(event) {
    if (window.l2t?.shell?.openExternal) {
      event.preventDefault();
      window.l2t.shell.openExternal(model.url);
    }
  }
</script>

<Card selected={active} class="flex flex-col gap-3" data-testid="model-card" data-alias={model.alias}>
  <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
    {#if !compact}
      <FilterChip
        active={familyActive}
        title={fmt($t('Show only %1 models'), model.family)}
        aria-label={fmt($t('Filter to %1 models. Activate again to show all.'), model.family)}
        on:click={() => dispatch('family', model.family)}
      >
        {model.family}
      </FilterChip>
    {/if}
    <h3 class="min-w-0 flex-1 truncate text-lg font-bold" title={$t(model.display_name)}>
      {$t(model.display_name)}
    </h3>
    {#if model.recommended}
      <Badge tone="accent">{$t('Recommended')}</Badge>
    {/if}
    {#if active}
      <Badge tone={badge?.tone ?? 'success'} dot>{badge?.label ?? $t('Active')}</Badge>
    {/if}
  </div>

  <p class="text-xs text-ink-soft">
    <span class="text-accent-text">{model.alias}</span>
    <span class="mx-2">{model.canonical}</span>
    <a
      href={model.url}
      target="_blank"
      rel="noopener noreferrer"
      class="text-accent-text underline underline-offset-2"
      aria-label={fmt($t('%1, %2. Link opens %3 in your browser.'), model.alias, model.canonical, model.url)}
      on:click={openLink}
    >
      {$t('Hugging Face')}
    </a>
  </p>

  <ul class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-soft">
    {#each facts as fact, i}
      <li use:tooltip={factHints[i]}>{fact}</li>
    {/each}
    <li>{$t(model.languages)}</li>
  </ul>

  {#if compact && model.pitch}
    <p class="text-sm" data-testid="model-pitch">{$t(model.pitch)}</p>
  {:else}
    <p class="text-sm text-ink-soft {expanded ? '' : 'line-clamp-3'}">{$t(model.description)}</p>
    <div>
      <Button variant="text" size="sm" on:click={() => (expanded = !expanded)}>
        {expanded ? $t('Show less') : $t('Show more')}
      </Button>
    </div>
  {/if}

  {#if hasSettings}
    <InferenceSettings {model} {languages} on:change={(e) => dispatch('inference', e.detail)} />
  {/if}

  <div class="flex flex-wrap items-center justify-end gap-3">
    {#if canDelete}
      <Button
        variant="danger"
        size="sm"
        disabled={locked || deleting}
        loading={deleting}
        on:click={() => dispatch('delete')}
      >
        {deleting ? $t('Deleting…') : $t('Delete')}
      </Button>
    {/if}
    {#if !active}
      <Button disabled={locked} on:click={() => dispatch('select')}>
        {primaryLabel}
      </Button>
    {/if}
  </div>
</Card>
