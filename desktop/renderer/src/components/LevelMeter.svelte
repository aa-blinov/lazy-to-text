<script>
  // A live input level, drawn as a row of segments. Rises at once and falls
  // away over a few updates, so a quiet sample does not flicker it off.
  export let level = 0;
  export let segments = 12;
  export let label = 'Microphone level';
  export let active = true;

  const DECAY = 0.85;
  let shown = 0;

  $: {
    const next = Math.max(0, Math.min(1, Number(level) || 0));
    shown = active ? Math.max(next, shown * DECAY) : 0;
  }
  $: lit = Math.round(shown * segments);

  // Signal fills, not text roles: these are dots and bars, never words.
  function tone(index) {
    const at = (index + 1) / segments;
    if (at <= 0.5) return 'bg-success';
    if (at <= 0.85) return 'bg-warning';
    return 'bg-danger';
  }
</script>

<div class="flex h-4 items-end gap-0.5" role="meter" aria-label={label} aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(shown * 100)}>
  {#each Array(segments) as _, i}
    <span class="w-1 rounded-ui transition-colors duration-fast {i < lit ? tone(i) : 'bg-surface-2'}" style="height: {35 + (i * 65) / segments}%"></span>
  {/each}
</div>
