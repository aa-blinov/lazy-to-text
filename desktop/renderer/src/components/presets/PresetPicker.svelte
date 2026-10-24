<script>
  // The preset picker. Always on screen: nothing on this screen folds it
  // away, because the preset in use is what a dictation will run.
  import { createEventDispatcher } from 'svelte';
  import { Card, Select, Button } from '@monos/ui';
  import { t } from '../../lib/i18n.js';
  import { middleEllipsis } from '../../lib/text.js';

  export let profiles = [];
  export let currentId = '';
  export let activeId = '';

  const dispatch = createEventDispatcher();

  // Shortened in the middle: presets copied from one another share their start.
  $: options = profiles.map((p) => ({ value: p.id, label: middleEllipsis(p.name || p.id, 56) }));
  $: currentName = profiles.find((p) => p.id === currentId)?.name ?? '';
  $: inUse = currentId && currentId === activeId;
  $: onlyOne = profiles.length <= 1;
</script>

<Card>
  <h2 class="text-sm font-bold uppercase tracking-widest text-ink">{$t('Preset')}</h2>
  <div class="mt-4 flex flex-wrap items-end gap-x-6 gap-y-3">
    <span class="block w-full max-w-xl min-w-0 sm:w-[28rem]" title={currentName}>
      <Select
        label={$t('Choose')}
        value={currentId}
        {options}
        on:change={(e) => dispatch('select', e.detail.value)}
      />
    </span>
    {#if inUse}
      <!-- A state to read, not a control that is off: a disabled button fades
           its label to a contrast nobody can read. -->
      <span class="inline-flex h-8 items-center gap-1.5 text-xs font-bold text-ink-soft" data-testid="preset-in-use" title={$t('This preset is already the default.')}>
        {$t('In use by default')}
      </span>
    {:else}
      <Button variant="secondary" size="sm" disabled={!currentId} on:click={() => dispatch('activate')}>
        {$t('Use this one by default')}
      </Button>
    {/if}
  </div>
  <div class="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
    <Button variant="text" size="sm" on:click={() => dispatch('create')}>{$t('New preset')}</Button>
    <Button variant="text" size="sm" disabled={!currentId} on:click={() => dispatch('duplicate')}>
      {$t('Duplicate')}
    </Button>
    <Button
      variant="danger"
      size="sm"
      disabled={onlyOne}
      title={onlyOne ? $t('This is the only preset. Add another one before you delete it.') : undefined}
      on:click={() => dispatch('delete')}
    >
      {$t('Delete')}
    </Button>
  </div>
</Card>
