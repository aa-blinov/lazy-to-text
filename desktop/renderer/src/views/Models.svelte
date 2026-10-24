<script>
  import { onMount } from 'svelte';
  import {
    PageHeader, SearchField, Select, Notice, Button, EmptyState, Skeleton, Grid, Drawer,
    AlertDialog, Separator, toast,
  } from '@monos/ui';
  import { call } from '../lib/rpc.js';
  import { t } from '../lib/i18n.js';
  import { state as appState, progress } from '../lib/backend.js';
  import {
    catalogue, languages, modelState, loaded, loadError, loadModels, wire, fmt, formatBytes,
    selectModel, downloadModel, cancelLoad, saveInference, downloadFigures,
  } from '../components/models/store.js';
  import {
    LANGUAGE_FILTERS, SORTS, ALL, visibleCards, familiesOf,
  } from '../components/models/filter.js';
  import ModelCard from '../components/models/ModelCard.svelte';
  import DownloadProgress from '../components/models/DownloadProgress.svelte';
  import StorageCard from '../components/models/StorageCard.svelte';
  import HfTokenCard from '../components/models/HfTokenCard.svelte';

  let query = '';
  let language = '';
  let family = ALL;
  let sort = 'order';
  let searchInput = null;
  let drawer = false;
  let pending = null; // the delete confirmation: {alias, name, size, shared}
  let deleteBusy = false;

  onMount(() => {
    wire();
    loadModels();
  });

  $: translate = (s) => $t(s);
  $: shown = visibleCards($catalogue, { query, language, family, sort }, translate);
  $: families = familiesOf($catalogue);
  $: filtering = Boolean(query.trim() || language || family !== ALL);
  $: locked = $appState !== 'idle';
  $: loading = $appState === 'model_loading';
  $: lockReason = {
    recording: $t('Recording is in progress. Models unlock when it ends.'),
    processing: $t('A dictation is being transcribed. Models unlock when it finishes.'),
    model_loading: $t('A model is loading. Cancel it or wait for it to finish.'),
  }[$appState] ?? '';

  $: active = $catalogue.find((c) => c.alias === $modelState.active) ?? null;
  $: figures = downloadFigures($progress, active);
  $: phase = !loading ? 'load' : figures.current > 0 ? 'download' : $modelState.cached[active?.alias] ? 'load' : 'start';

  // What the active card's pill says while it loads; Qt shows the percentage
  // (or bytes) there and keeps the elapsed seconds for the top bar.
  $: activeBadge = !loading
    ? null
    : figures.current > 0
      ? {
          tone: 'warning',
          label:
            figures.fraction === null
              ? fmt($t('Loading %1'), formatBytes(figures.current))
              : fmt($t('Loading %1%'), Math.round(figures.fraction * 100)),
        }
      : { tone: 'warning', label: $t('Loading…') };

  $: languageOptions = LANGUAGE_FILTERS.map((o) => ({ value: o.value, label: $t(o.label) }));
  $: sortOptions = SORTS.map((o) => ({ value: o.value, label: $t(o.label) }));
  $: familyOptions = [{ value: ALL, label: $t('All families') }, ...families.map((f) => ({ value: f, label: f }))];

  function toggleFamily(name) {
    family = family === name ? ALL : name;
  }

  function clearFilters() {
    query = '';
    language = '';
    family = ALL;
  }

  function choose(card) {
    return $modelState.cached[card.alias] ? selectModel(card.alias) : downloadModel(card.alias);
  }

  async function askDelete(card) {
    try {
      const info = await call('models.delete_info', { alias: card.alias });
      pending = {
        alias: card.alias,
        name: $t(card.display_name),
        // The measured size when there is one, the catalogue's otherwise.
        size: info.size_bytes || card.size_mb * 1024 * 1024,
        shared: info.shared_with,
      };
    } catch (err) {
      pending = null;
    }
  }

  async function confirmDelete() {
    const alias = pending.alias;
    deleteBusy = true;
    try {
      await call('models.delete', { alias });
    } catch (err) {
      toast({ title: $t('Delete failed'), description: err.message, tone: 'danger' });
    } finally {
      deleteBusy = false;
      pending = null;
    }
  }

  function onKeydown(event) {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'f') {
      event.preventDefault();
      searchInput?.focus();
    }
  }
</script>

<svelte:window on:keydown={onKeydown} />

<div class="flex min-h-full flex-col gap-4 p-6">
  <PageHeader
    title={$t('Models')}
    description={$t("Pick what the app listens with. Bigger is more accurate and slower to load; the app's own starting point is first.")}
  />

  {#if loading && active}
    <div
      class="sticky top-0 z-10 flex flex-col gap-3 rounded-ui border border-line bg-surface p-4 shadow-rest"
      data-testid="load-banner"
    >
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="text-sm font-bold">
          {fmt($t(phase === 'download' || phase === 'start' ? 'Downloading %1' : 'Loading: %1'), $t(active.display_name))}
        </p>
        <Button variant="danger" size="sm" on:click={cancelLoad}>{$t('Cancel')}</Button>
      </div>
      <DownloadProgress {figures} {phase} elapsed={$progress.elapsed} />
      <p class="text-xs text-ink-faint">{$t('The other models are locked until this one finishes.')}</p>
    </div>
  {:else if locked && lockReason}
    <Notice tone="info">{lockReason}</Notice>
  {/if}

  <div class="flex flex-col gap-3" role="search">
    <SearchField
      bind:value={query}
      bind:inputEl={searchInput}
      label={$t('Search models')}
      placeholder={$t('Search models by name, alias, language…')}
      clearLabel={$t('Clear')}
    />
    <div class="flex flex-wrap items-end gap-3">
      <Select label={$t('Filter by language')} options={languageOptions} bind:value={language} />
      <Select label={$t('Filter by family')} options={familyOptions} bind:value={family} />
      <Select label={$t('Sort models')} options={sortOptions} bind:value={sort} />
      <span class="ml-auto">
        <Button variant="quiet" on:click={() => (drawer = true)}>{$t('Storage and access')}</Button>
      </span>
    </div>
  </div>

  {#if $loadError}
    <Notice tone="danger" title={$t('The catalogue could not be loaded')}>
      {$loadError}
      <Button variant="text" size="sm" on:click={loadModels}>{$t('Try again')}</Button>
    </Notice>
  {:else if !$loaded}
    <div class="flex flex-col gap-4" aria-busy="true">
      {#each [0, 1, 2] as n (n)}
        <Skeleton height="9rem" />
      {/each}
    </div>
  {:else if shown.length === 0}
    <EmptyState
      title={$t('No models match your filters')}
      description={$t('Clear the search box or pick a different family chip.')}
    >
      <svelte:fragment slot="actions">
        <Button variant="secondary" on:click={clearFilters}>{$t('Clear filters')}</Button>
      </svelte:fragment>
    </EmptyState>
  {:else}
    <p class="text-xs text-ink-faint" aria-live="polite">
      {fmt($t('Showing %1 of %2 models'), shown.length, $catalogue.length)}
    </p>
    <Grid min="26rem" gap="lg" class="items-start">
      {#each shown as card (card.alias)}
        <ModelCard
          model={card}
          languages={$languages}
          active={$modelState.active === card.alias}
          cached={Boolean($modelState.cached[card.alias])}
          badge={$modelState.active === card.alias ? activeBadge : null}
          {locked}
          deleting={$modelState.deleting.includes(card.alias)}
          familyActive={family === card.family}
          on:select={() => choose(card)}
          on:delete={() => askDelete(card)}
          on:family={(e) => toggleFamily(e.detail)}
          on:inference={(e) => saveInference(card.alias, e.detail)}
        />
      {/each}
    </Grid>
  {/if}
</div>

<Drawer open={drawer} title={$t('Storage and access')} on:close={() => (drawer = false)}>
  <div class="flex flex-col gap-6">
    <StorageCard />
    <Separator />
    <HfTokenCard />
  </div>
</Drawer>

<AlertDialog
  open={pending !== null}
  title={$t('Delete cached model?')}
  confirmLabel={$t('Delete')}
  cancelLabel={$t('Cancel')}
  loading={deleteBusy}
  closeOnConfirm={false}
  on:confirm={confirmDelete}
  on:cancel={() => (pending = null)}
>
  {#if pending}
    <p>{fmt($t('Remove the downloaded weights for %1 (%2)?'), pending.name, formatBytes(pending.size))}</p>
    <p class="mt-2">{$t("You'll need to download them again the next time this model is selected.")}</p>
    {#if pending.shared.length}
      <p class="mt-2">
        {fmt($t("This cache is shared with other variants and they will also flip to 'Download' after deletion: %1."), pending.shared.join(', '))}
      </p>
    {/if}
  {/if}
</AlertDialog>
