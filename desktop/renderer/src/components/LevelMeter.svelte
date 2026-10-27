<script>
  // A live input level, drawn as a row of segments on a decibel scale (see
  // lib/level.js). Rises at once and falls away over a few updates, so a quiet
  // syllable does not flicker the bar off.
  import { position, toDb, toneAt } from '../lib/level.js';

  export let level = 0;
  export let segments = 12;
  export let label = 'Microphone level';
  export let active = true;

  const DECAY = 0.88;
  let shown = 0;

  $: {
    const next = position(level);
    shown = active ? Math.max(next, shown * DECAY) : 0;
  }
  $: lit = Math.round(shown * segments);
  $: db = toDb(level);
  $: valueText = Number.isFinite(db) && shown > 0 ? `${Math.round(db)} dB` : '';

  // Signal fills, not text roles: these are dots and bars, never words.
  const FILL = { ok: 'bg-success', loud: 'bg-warning', clip: 'bg-danger' };
</script>

<div
  class="flex h-4 items-end gap-0.5"
  role="meter"
  aria-label={label}
  aria-valuemin="0"
  aria-valuemax="100"
  aria-valuenow={Math.round(shown * 100)}
  aria-valuetext={valueText || undefined}
>
  {#each Array(segments) as _, i}
    <span class="w-1 rounded-ui transition-colors duration-fast {i < lit ? FILL[toneAt(i, segments)] : 'bg-line'}" style="height: {35 + (i * 65) / segments}%"></span>
  {/each}
</div>
