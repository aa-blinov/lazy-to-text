<script>
  // A label with its explanation and the control beside it. The two sides
  // are flex items that wrap, not grid columns: when the window is narrow or
  // the text size is large the control drops under the label instead of
  // squeezing it, so the page never needs a horizontal scrollbar.
  export let label = '';
  export let hint = '';
  export let forId = '';
  export let wide = false;
  export let controlEnd = false;
</script>

<div class="flex flex-wrap items-start gap-x-6 gap-y-2 py-3 first:pt-1 last:pb-1">
  {#if label || hint}
    <div class="min-w-0 {wide ? 'basis-full' : 'flex-1 basis-[13rem]'}">
      {#if label}
        {#if forId}
          <label for={forId} class="block text-sm text-ink">{label}</label>
        {:else}
          <div class="text-sm text-ink">{label}</div>
        {/if}
      {/if}
      {#if hint}<p class="mt-0.5 text-xs text-ink-faint">{hint}</p>{/if}
    </div>
  {/if}
  <div class="min-w-0 {wide || !(label || hint) ? 'basis-full' : 'max-w-[22rem] flex-1 basis-[18rem]'} {controlEnd ? 'flex justify-end' : ''}"><slot /></div>
</div>
