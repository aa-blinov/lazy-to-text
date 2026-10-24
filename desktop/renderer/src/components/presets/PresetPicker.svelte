<script>
  // The preset picker. Always on screen: nothing on this screen folds it
  // away, because the preset in use is what a dictation will run.
  import { createEventDispatcher } from 'svelte';
  import { Card, Select, Button } from '@monos/ui';
  import { t } from '../../lib/i18n.js';

  export let profiles = [];
  export let currentId = '';
  export let activeId = '';

  const dispatch = createEventDispatcher();

  $: options = profiles.map((p) => ({ value: p.id, label: p.name || p.id }));
  $: inUse = currentId && currentId === activeId;
  $: onlyOne = profiles.length <= 1;
</script>

<Card>
  <h2 class="text-sm font-bold uppercase tracking-widest text-ink">{$t('Preset')}</h2>
  <div class="mt-4 flex flex-wrap items-end gap-x-6 gap-y-3">
    <Select
      class="w-64 max-w-full"
      label={$t('Choose')}
      value={currentId}
      {options}
      on:change={(e) => dispatch('select', e.detail.value)}
    />
    <Button
      variant="secondary"
      size="sm"
      disabled={!currentId || inUse}
      title={inUse ? $t('This preset is already the default.') : undefined}
      on:click={() => dispatch('activate')}
    >
      {inUse ? $t('In use by default') : $t('Use this one by default')}
    </Button>
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
