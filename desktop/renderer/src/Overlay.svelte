<script>
  import { onMount } from 'svelte';
  import { start, state, level } from './lib/backend.js';
  onMount(() => { start(); });
</script>

<div class="m-2 inline-flex items-center gap-2 rounded-ui bg-surface px-3 py-2 text-xs text-ink">
  <span>{$state}</span>
  <span>{Math.round($level * 100)}</span>
</div>
