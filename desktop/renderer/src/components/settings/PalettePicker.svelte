<script>
  // The kit's six palettes as a choice you can see: each card shows its
  // page, surface, ink and accent colours in light and dark. The swatches
  // are read from the kit's own theme table, so this file names no colour.
  import { createEventDispatcher } from 'svelte';
  import { themes } from '@monos/ui';
  import { t } from '../../lib/i18n.js';

  export let value = 'gruvbox';
  export let choices = Object.keys(themes);
  export let label = '';

  const dispatch = createEventDispatcher();
  const strip = (mode) => ['bg', 'surface', 'ink', 'accent'].map((k) => mode[k]);

  function onKeydown(event, index) {
    const last = choices.length - 1;
    let next = null;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = index === last ? 0 : index + 1;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = index === 0 ? last : index - 1;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = last;
    if (next === null) return;
    event.preventDefault();
    dispatch('change', choices[next]);
    event.currentTarget.parentElement.children[next]?.focus();
  }
</script>

<div role="radiogroup" aria-label={label || $t('Palette')} class="grid grid-cols-2 gap-2 sm:grid-cols-3">
  {#each choices as name, index (name)}
    {@const t_ = themes[name]}
    <button
      type="button"
      role="radio"
      aria-checked={value === name}
      tabindex={value === name || (!choices.includes(value) && index === 0) ? 0 : -1}
      class="flex flex-col gap-1.5 rounded-ui border p-2 text-left text-xs transition-colors duration-fast focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 {value === name
        ? 'border-ink bg-surface'
        : 'border-line hover:border-line-strong'}"
      on:click={() => dispatch('change', name)}
      on:keydown={(e) => onKeydown(e, index)}
    >
      <span class="text-ink">{t_.name}</span>
      {#each [t_.light, t_.dark] as mode}
        <span class="flex h-3 overflow-hidden rounded-ui border border-line" aria-hidden="true">
          {#each strip(mode) as color}
            <span class="flex-1" style="background-color: {color}"></span>
          {/each}
        </span>
      {/each}
    </button>
  {/each}
</div>
