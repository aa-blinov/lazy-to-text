<script>
  import { onMount, onDestroy } from 'svelte';
  import {
    PageHeader, EmptyState, Button, IconButton, SearchField, Table, Modal, AlertDialog,
    Notice, Skeleton, Chip, Kbd, toast,
  } from '@monos/ui';
  import { Copy, Trash2 } from 'lucide-svelte';
  import { t, language as uiLanguage } from '../lib/i18n.js';
  import { subscribe } from '../lib/rpc.js';
  import { subject } from '../lib/text.js';
  import {
    filterEntries, formatHotkey, formatDuration, countLabel, languageName,
    listEntries, deleteEntry, restoreEntry, clearAll, exportTo, copyEntry,
  } from '../lib/history.js';

  let entries = [];
  let enabled = true;
  let startHotkey = '';
  let loaded = false;
  let loadError = '';
  let query = '';
  let searchEl = null;
  let detail = null;
  let confirmOpen = false;
  let exporting = false;

  $: shown = filterEntries(entries, query);
  $: filtered = query.trim() !== '';
  $: hotkey = formatHotkey(startHotkey);
  $: columns = [
    { key: 'datetime', label: $t('Time') },
    { key: 'text', label: $t('Text') },
    { key: 'alias', label: $t('Model') },
    { key: 'language', label: $t('Language') },
    { key: 'duration', label: $t('Duration'), align: 'right' },
    { key: 'actions', label: '', align: 'right' },
  ];

  async function load() {
    try {
      const result = await listEntries();
      entries = result.entries;
      enabled = result.enabled;
      startHotkey = result.start_hotkey;
      loadError = '';
    } catch (err) {
      loadError = err.message;
    } finally {
      loaded = true;
    }
  }

  function fail(title, err) {
    toast({ title, description: $t(err.message), tone: 'danger', duration: 0 });
  }

  async function copy(entry) {
    if (!entry.text) return;
    await copyEntry(entry);
    toast({ title: $t('Copied to clipboard.'), tone: 'success', duration: 2000 });
  }

  async function remove(entry) {
    try {
      const { deleted } = await deleteEntry(entry.id);
      if (detail?.id === entry.id) detail = null;
      toast({
        title: $t('Transcription deleted'),
        description: deleted.text.length > 60 ? deleted.text.slice(0, 57) + '...' : deleted.text,
        duration: 8000,
        action: { label: $t('Undo'), onClick: () => undo(deleted) },
      });
    } catch (err) {
      fail($t('Could not delete'), err);
    }
  }

  async function undo(entry) {
    try {
      await restoreEntry(entry);
    } catch (err) {
      fail($t('Could not undo'), err);
    }
  }

  async function askClear() {
    if (!entries.length) return;
    const total = entries.length;
    const detailText = $t('Delete all %1 transcriptions? This cannot be undone.').replace('%1', String(total));
    if (window.l2t?.dialog?.confirm) {
      const answer = await window.l2t.dialog.confirm({
        type: 'warning',
        message: $t('Clear history?'),
        detail: detailText,
        buttons: [$t('Clear history'), $t('Cancel')],
        defaultId: 1,
        cancelId: 1,
      });
      if (answer === 0) await doClear();
    } else {
      confirmOpen = true;
    }
  }

  async function doClear() {
    try {
      const { cleared } = await clearAll();
      toast({
        title: $t('History cleared'),
        description: $t('%1 transcriptions deleted.').replace('%1', String(cleared)),
        tone: 'success',
      });
    } catch (err) {
      fail($t('Could not clear history'), err);
    }
  }

  async function doExport() {
    if (exporting || !entries.length) return;
    const save = window.l2t?.dialog?.saveFile;
    if (!save) {
      toast({ title: $t('Saving a file needs the desktop app.'), tone: 'warning' });
      return;
    }
    const path = await save({
      title: $t('Export history'),
      defaultPath: 'transcription_history.txt',
      filters: [
        { name: 'Text', extensions: ['txt'] },
        { name: $t('All files'), extensions: ['*'] },
      ],
    });
    if (!path) return;
    exporting = true;
    try {
      const result = await exportTo(path);
      toast({
        title: $t('History exported'),
        description: $t('Saved %1 transcriptions to: %2')
          .replace('%1', String(result.exported)).replace('%2', result.path),
        tone: 'success',
      });
    } catch (err) {
      fail($t('Export failed'), err);
    } finally {
      exporting = false;
    }
  }

  // Escape clears a search from anywhere in the view, and the platform Find
  // key goes to the search field, as in the Qt window.
  function onKeydown(event) {
    if (event.key === 'Escape' && query && !detail && !confirmOpen) {
      query = '';
      event.preventDefault();
    } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'f') {
      event.preventDefault();
      searchEl?.focus();
    }
  }

  let stop = () => {};
  onMount(() => {
    load();
    stop = subscribe('history', load);
    window.addEventListener('keydown', onKeydown);
  });
  onDestroy(() => {
    stop();
    window.removeEventListener('keydown', onKeydown);
  });
</script>

<div class="flex min-h-full flex-col gap-4 p-6">
  <PageHeader
    title={$t('History')}
    description={$t('Every dictation and transcription, newest first.')}
  >
    <svelte:fragment slot="actions">
      <Button variant="secondary" disabled={!entries.length || exporting} loading={exporting} on:click={doExport}>
        {exporting ? $t('Exporting…') : $t('Export')}
      </Button>
      <Button variant="danger" disabled={!entries.length} on:click={askClear}>{$t('Clear history')}</Button>
    </svelte:fragment>
  </PageHeader>

  {#if loadError}
    <Notice tone="danger">{loadError}</Notice>
  {:else if !loaded}
    <div class="flex flex-col gap-2" aria-hidden="true">
      {#each [0, 1, 2, 3] as row (row)}<Skeleton height="2.5rem" />{/each}
    </div>
  {:else}
    {#if !enabled}
      <Notice tone="info">{$t('History is turned off, so nothing is being stored.')}</Notice>
    {/if}

    <div class="flex items-center gap-4">
      <div class="max-w-md flex-1">
        <SearchField
          bind:value={query}
          bind:inputEl={searchEl}
          label={$t('Search transcriptions…')}
          placeholder={$t('Search transcriptions…')}
          clearLabel={$t('Clear')}
          disabled={!entries.length}
        />
      </div>
      <span class="text-xs text-ink-faint" data-testid="count" aria-live="polite">
        {countLabel(shown.length, entries.length, filtered)}
      </span>
    </div>

    {#if !entries.length}
      <EmptyState
        title={$t('Nothing dictated yet')}
        description={$t('Press the start hotkey and speak. Every transcription lands here, newest first.')}
      >
        <svelte:fragment slot="actions">
          {#if hotkey}<Kbd>{hotkey}</Kbd>{/if}
        </svelte:fragment>
      </EmptyState>
    {:else if !shown.length}
      <EmptyState title={$t('No matching transcriptions')} description={$t('Nothing here contains that text.')}>
        <svelte:fragment slot="actions"><Kbd>{$t('Esc to clear')}</Kbd></svelte:fragment>
      </EmptyState>
    {:else}
      <Table {columns} rows={shown} rowKey="id" caption={$t('History')} density="compact">
        <svelte:fragment slot="cell" let:row let:column>
          {#if column.key === 'text'}
            <!-- anywhere: a URL or a token has no space to break at, and would
                 otherwise push the actions off the right edge. -->
            <button
              type="button"
              class="line-clamp-2 max-w-2xl whitespace-pre-line text-left text-ink [overflow-wrap:anywhere] hover:underline"
              title={row.text}
              on:click={() => (detail = row)}
            >
              {row.text}
            </button>
          {:else if column.key === 'alias'}
            <span class="[overflow-wrap:anywhere]" title={row.model}>{row.alias}</span>
          {:else if column.key === 'language'}
            {languageName(row.language, $uiLanguage, $t('Auto-detect'))}
          {:else if column.key === 'duration'}
            {formatDuration(row.duration)}
          {:else if column.key === 'actions'}
            <span class="inline-flex gap-1">
              <IconButton label={$t('Copy: %1').replace('%1', subject(row.text))} size="sm" variant="ghost" disabled={!row.text} on:click={() => copy(row)}>
                <Copy size={14} aria-hidden="true" />
              </IconButton>
              <IconButton label={$t('Delete: %1').replace('%1', subject(row.text))} size="sm" variant="ghost" on:click={() => remove(row)}>
                <Trash2 size={14} aria-hidden="true" />
              </IconButton>
            </span>
          {:else}
            {row[column.key]}
          {/if}
        </svelte:fragment>
      </Table>
    {/if}
  {/if}
</div>

<Modal
  open={detail !== null}
  title={$t('Transcription details')}
  closeLabel={$t('Close')}
  size="lg"
  on:close={() => (detail = null)}
>
  {#if detail}
    <div class="mb-3 flex min-w-0 flex-wrap gap-2">
      <Chip>{$t('Time')}: {detail.datetime}</Chip>
      <span class="min-w-0 max-w-full" title={detail.model}><Chip>{$t('Model')}: {detail.model}</Chip></span>
      <Chip>{$t('Language')}: {languageName(detail.language, $uiLanguage, $t('Auto-detect'))}</Chip>
      <Chip>{$t('Duration')}: {formatDuration(detail.duration)}</Chip>
    </div>
    <div
      class="max-h-96 overflow-auto whitespace-pre-wrap [overflow-wrap:anywhere] rounded-ui border border-line p-3 text-sm text-ink"
      data-testid="detail-text"
      tabindex="0"
    >{detail.text}</div>
  {/if}
  <svelte:fragment slot="footer">
    <Button variant="secondary" disabled={!detail?.text} on:click={() => copy(detail)}>{$t('Copy text')}</Button>
    <Button variant="secondary" on:click={() => remove(detail)}>{$t('Delete')}</Button>
    <Button on:click={() => (detail = null)}>{$t('Close')}</Button>
  </svelte:fragment>
</Modal>

<AlertDialog
  bind:open={confirmOpen}
  title={$t('Clear history?')}
  description={$t('Delete all %1 transcriptions? This cannot be undone.').replace('%1', String(entries.length))}
  confirmLabel={$t('Clear history')}
  cancelLabel={$t('Cancel')}
  on:confirm={doClear}
/>
