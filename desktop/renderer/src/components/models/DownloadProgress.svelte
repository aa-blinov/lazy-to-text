<script>
  // The progress of a model coming to life: a bar, the bytes and the seconds.
  // Used on the Models page and on the first-run screen so both say the same
  // thing. With no total yet the bar is indeterminate and the line shows the
  // bytes so far; a cached model being read shows seconds only.
  import { Progress, Spinner } from '@monos/ui';
  import { t } from '../../lib/i18n.js';
  import { fmt, formatBytes, formatElapsed } from './store.js';

  export let figures = { current: 0, total: 0, fraction: null, elapsed: 0 };
  /** 'download' while weights arrive, 'load' while a cached model is read, 'start' before any byte. */
  export let phase = 'download';
  export let elapsed = figures.elapsed;
  export let label = '';

  $: pct = figures.fraction === null ? null : Math.round(figures.fraction * 100);
  $: line = describe($t, phase, figures, pct);

  function describe(tt, kind, f, percent) {
    if (kind === 'load') return tt('Loading…');
    if (kind === 'start' || (f.current <= 0 && percent === null)) return tt('Starting…');
    if (percent !== null) {
      return fmt(tt('%1%  ·  %2 of %3'), percent, formatBytes(f.current), formatBytes(f.total));
    }
    return fmt(tt('Downloading… %1'), formatBytes(f.current));
  }
</script>

<div class="flex flex-col gap-2" data-testid="download-progress">
  {#if phase === 'load'}
    <div class="flex items-center gap-2 text-sm text-ink-soft">
      <Spinner size="sm" />
      <span>{line}</span>
      <span class="text-ink-faint">{formatElapsed(elapsed)}</span>
    </div>
  {:else}
    <Progress
      value={pct ?? 0}
      indeterminate={pct === null}
      label={label || $t('Model download progress')}
    />
    <div class="flex flex-wrap items-baseline gap-x-2 text-sm text-ink-soft">
      <span>{line}</span>
      <span class="text-ink-faint">{formatElapsed(elapsed)}</span>
    </div>
  {/if}
</div>
