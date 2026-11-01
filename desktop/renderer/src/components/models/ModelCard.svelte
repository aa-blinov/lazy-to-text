<script context="module">
  // Ids tie a card to its own heading and figures (a model can be drawn twice:
  // in the catalogue and on the first-run page).
  let cardCounter = 0;
</script>

<script>
  // One model in the catalogue. Presentational: the page decides what the
  // badge says and whether the card is locked, the card draws it and reports
  // what the user pressed.
  import { createEventDispatcher } from 'svelte';
  import { Card, Badge, Button, tooltip } from '@monos/ui';
  import { t, language, formatNumber, localizeFigures } from '../../lib/i18n.js';
  import { fmt, formatSize } from './store.js';
  import DownloadProgress from './DownloadProgress.svelte';

  export let model;
  export let languages = [];
  export let active = false;
  export let cached = false;
  /** Loading state of the active card: null, or {tone, label}. */
  export let badge = null;
  export let locked = false;
  /** Chosen while another model loads: Select and Download stay usable and replace that load. */
  export let switchable = false;
  export let deleting = false;
  /** The first-run card leads with the pitch and has no Delete or settings. */
  export let compact = false;
  /** Active and on disk, but the engine runs nothing: offer to load it. */
  export let unloaded = false;
  /** The diarization card only: its weights are arriving, with the figures to draw. */
  export let downloading = false;
  export let figures = { current: 0, total: 0, fraction: null, elapsed: 0 };

  const dispatch = createEventDispatcher();
  const uid = `model-card-${++cardCounter}`;

  $: name = $t(model.display_name);
  // "Name (a, b, 30 MB)": the parenthesis is characteristics, so they move
  // under the name with the figures; a size inside it is shown once.
  $: parts = /^(.*?)\s*\(([^()]*)\)\s*$/.exec(name);
  $: title = parts ? parts[1] : name;
  $: notes = parts
    ? parts[2].split(',').map((n) => n.trim()).filter((n) => n && !/^\d+(\.\d+)?\s*(MB|GB|МБ|ГБ)$/i.test(n))
    : [];

  // The speaker-diarization model is listed with the speech models but is never
  // the active one: no Select, no WER, no speech-model figures.
  $: auxiliary = model.kind === 'diarization';
  $: loading = badge?.tone === 'warning';
  $: canDelete = cached && !active && !loading && !compact;
  $: primaryLabel = cached ? $t('Select') : $t('Download');
  $: hasSettings = active && !compact && model.inference?.kind && !loading;

  // One line under the name: what tells the models apart, separated by commas.
  $: about = notes.length ? notes : [$t(model.languages)];
  $: facts = (auxiliary
    ? [...about, formatSize(model.size_mb)]
    : [
        ...about,
        model.wer != null ? fmt($t('WER %1%'), formatNumber(model.wer)) : fmt($t('WER %1'), '—'),
        model.rtf ? fmt($t('RTF %1'), formatNumber(model.rtf)) : fmt($t('RTF %1'), '—'),
        formatSize(model.size_mb),
      ]).join(', ');
  $: factHints = auxiliary
    ? $t('Download size.')
    : [
        $t('Word error rate on our Russian test set. Lower is better.'),
        $t('Real-time factor: processing seconds per second of audio. Lower is faster.'),
        $t('Download size.'),
      ].join(' ');
  // Unlocked for a switch even while a load holds the rest of the page.
  $: open = !locked || switchable;

  function openLink(event) {
    if (window.l2t?.shell?.openExternal) {
      event.preventDefault();
      window.l2t.shell.openExternal(model.url);
    }
  }
</script>

<!-- The card is one group: named by its heading, described by the figures and the
     description, so a screen reader announces a model as one sentence's worth
     instead of leaving the user to walk its parts. -->
<Card
  selected={active}
  class="flex h-full flex-col gap-2 {auxiliary && !cached && !downloading ? 'opacity-60' : ''}"
  data-testid="model-card"
  data-alias={model.alias}
  aria-labelledby="{uid}-title"
  aria-describedby={compact && model.pitch ? `${uid}-facts ${uid}-pitch` : `${uid}-facts ${uid}-about`}
>
  <div class="flex items-center gap-2">
    <h3 id="{uid}-title" class="min-w-0 flex-1 truncate text-base font-bold" title={name}>{title}</h3>
    {#if model.recommended}
      <Badge tone="accent">{$t('Recommended')}</Badge>
    {/if}
    {#if auxiliary && downloading}
      <Badge tone="warning" dot>{$t('Downloading…')}</Badge>
    {:else if auxiliary && cached}
      <Badge tone="success" dot>{$t('Downloaded')}</Badge>
    {:else if active && unloaded}
      <Badge tone="warning" dot>{$t('Not loaded')}</Badge>
    {:else if active}
      <Badge tone={badge?.tone ?? 'success'} dot>{badge?.label ?? $t('Active')}</Badge>
    {/if}
  </div>

  <p id="{uid}-facts" class="line-clamp-2 min-h-8 text-xs text-ink-soft" title={factHints} use:tooltip={factHints}>{facts}</p>

  {#if compact && model.pitch}
    <p id="{uid}-pitch" class="text-sm" data-testid="model-pitch">{localizeFigures($t(model.pitch), $language)}</p>
  {:else if auxiliary && downloading}
    <div class="min-h-[3.75rem]">
      <DownloadProgress {figures} phase={figures.current > 0 ? 'download' : 'start'} elapsed={figures.elapsed} />
    </div>
    <span id="{uid}-about" class="sr-only">{localizeFigures($t(model.description), $language)}</span>
  {:else}
    <p id="{uid}-about" class="line-clamp-3 h-[3.75rem] text-sm text-ink-soft" title={localizeFigures($t(model.description), $language)}>{localizeFigures($t(model.description), $language)}</p>
  {/if}

  <div class="mt-auto flex min-h-9 items-center gap-3 pt-1">
    <a
      href={model.url}
      target="_blank"
      rel="noopener noreferrer"
      class="mr-auto text-xs text-accent-text underline underline-offset-2"
      title={model.canonical}
      aria-label={fmt($t('Public model files: %1 (%2). Opens %3 in your browser.'), model.alias, model.canonical, model.url)}
      on:click={openLink}
    >
      {$t('Public model files')}
    </a>
    {#if canDelete}
      <Button
        variant="danger"
        size="sm"
        aria-label={fmt($t('Delete %1'), name)}
        disabled={locked || deleting || downloading}
        loading={deleting}
        on:click={() => dispatch('delete')}
      >
        {deleting ? $t('Deleting…') : $t('Delete')}
      </Button>
    {/if}
    {#if hasSettings}
      <Button variant="secondary" size="sm" aria-label={fmt($t('Settings: %1'), name)} on:click={() => dispatch('settings')}>
        {$t('Settings')}
      </Button>
    {/if}
    {#if active && unloaded}
      <Button disabled={locked} aria-label={fmt($t('Load %1'), name)} on:click={() => dispatch('load')}>
        {$t('Load')}
      </Button>
    {:else if auxiliary}
      {#if !cached}
        {#if downloading}
          <Button variant="danger" size="sm" aria-label={fmt($t('Cancel download of %1'), name)} on:click={() => dispatch('cancel')}>
            {$t('Cancel')}
          </Button>
        {:else}
          <Button
            disabled={locked}
            aria-label={fmt($t('Download %1'), name)}
            on:click={() => dispatch('select')}
          >
            {$t('Download')}
          </Button>
        {/if}
      {/if}
    {:else if !active}
      <Button disabled={!open} aria-label={fmt(cached ? $t('Select %1') : $t('Download %1'), name)} on:click={() => dispatch('select')}>
        {primaryLabel}
      </Button>
    {/if}
  </div>
</Card>
