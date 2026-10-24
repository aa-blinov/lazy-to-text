<script>
  // What the app is doing, in order. Records come from the runtime's ring
  // and its `log` event; everything here is view state: filters, the cut
  // made by Clear, and whether the list follows the newest line.
  import { onMount, onDestroy, tick } from 'svelte';
  import {
    PageHeader, Button, SearchField, SegmentedControl, Select, FilterChip, Switch, EmptyState, AlertDialog, toast,
  } from '@monos/ui';
  import { t } from '../lib/i18n.js';
  import { snapshot } from '../lib/backend.js';
  import { records, attach, clearView } from '../components/logs/store.js';
  import {
    LEVELS, visibleRecords, loggerNames, recordText, levelClass, messageClass, isOwn,
  } from '../components/logs/model.js';

  const SEARCH_DEBOUNCE_MS = 200;

  let query = '';
  let applied = '';
  let timer = null;
  let showNetwork = false;
  let minLevel = 'DEBUG';
  let logger = '';
  let onlyUser = false;
  let follow = true;
  let confirmClear = false;
  let listEl;
  let detach = () => {};

  // Re-filter once typing pauses, rather than on every keystroke.
  function onSearch() {
    clearTimeout(timer);
    timer = setTimeout(() => (applied = query), SEARCH_DEBOUNCE_MS);
  }

  $: shown = visibleRecords($records, { query: applied, showNetwork, minLevel, logger, onlyUser });
  $: loggers = loggerNames($records);
  $: loggerOptions = [{ value: '', label: $t('All loggers') }, ...loggers.map((n) => ({ value: n, label: n }))];
  $: levelOptions = [
    { value: 'DEBUG', label: $t('All') },
    { value: 'INFO', label: $t('Info') },
    { value: 'WARNING', label: $t('Warnings') },
    { value: 'ERROR', label: $t('Errors') },
  ];
  $: logPath = $snapshot?.log_path || '';
  $: canReveal = Boolean(logPath && typeof window !== 'undefined' && window.l2t?.shell?.showItemInFolder);
  $: if (shown && follow) scrollToEnd();

  async function scrollToEnd() {
    await tick();
    if (listEl) listEl.scrollTop = listEl.scrollHeight;
  }

  // Scrolling away from the bottom pauses following; coming back resumes it.
  function onScroll() {
    if (!listEl) return;
    const gap = listEl.scrollHeight - listEl.scrollTop - listEl.clientHeight;
    const atEnd = gap < 24;
    if (follow && !atEnd) follow = false;
    else if (!follow && atEnd) follow = true;
  }

  function resume() {
    follow = true;
    scrollToEnd();
  }

  async function copy() {
    const text = shown.map(recordText).join('\n');
    try {
      if (window.l2t?.clipboard) await window.l2t.clipboard.writeText(text);
      else await navigator.clipboard.writeText(text);
      toast({ title: $t('Copied'), description: $t('Lines: {count}', { count: shown.length }), tone: 'success' });
    } catch (error) {
      toast({ title: $t('Could not copy'), description: error.message, tone: 'danger' });
    }
  }

  function reveal() {
    window.l2t.shell.showItemInFolder(logPath);
  }

  function clear() {
    clearView();
    confirmClear = false;
  }

  onMount(() => { detach = attach(); });
  onDestroy(() => { detach(); clearTimeout(timer); });
</script>

<div class="flex h-full flex-col p-6">
  <PageHeader
    title={$t('Logs')}
    description={$t('What the app is doing, in order. Useful when a model misbehaves.')}
  >
    <svelte:fragment slot="actions">
      <Button variant="text" size="sm" disabled={!shown.length} on:click={copy}>{$t('Copy')}</Button>
      {#if canReveal}
        <Button variant="text" size="sm" on:click={reveal}>{$t('Show log file')}</Button>
      {/if}
      <Button variant="danger" size="sm" disabled={!$records.length} on:click={() => (confirmClear = true)}>
        {$t('Clear logs')}
      </Button>
    </svelte:fragment>
  </PageHeader>

  <div class="mt-4 flex flex-wrap items-end gap-x-4 gap-y-3">
    <div class="w-64 max-w-full">
      <SearchField
        bind:value={query}
        label={$t('Search logs')}
        placeholder={$t('Search logs…')}
        clearLabel={$t('Clear')}
        on:input={onSearch}
        on:clear={() => { query = ''; applied = ''; }}
      />
    </div>
    <SegmentedControl size="sm" label={$t('Level')} options={levelOptions} bind:value={minLevel} />
    <Select class="w-56 max-w-full" size="sm" label={$t('Logger')} options={loggerOptions} bind:value={logger} />
    <FilterChip active={onlyUser} on:click={() => (onlyUser = !onlyUser)}>{$t('Messages for you')}</FilterChip>
    <span title={$t('Adds requests to the model server and the internet to the log. Not needed for everyday use.')}>
      <Switch bind:checked={showNetwork}>{$t('Show network logs')}</Switch>
    </span>
  </div>

  <div class="mt-4 flex items-center justify-between gap-3 text-whisper-lg text-ink-faint">
    <span data-testid="count">{$t('Lines: {shown} of {total}', { shown: shown.length, total: $records.length })}</span>
    <Switch checked={follow} on:change={(e) => (e.detail ? resume() : (follow = false))}>
      {follow ? $t('Following the newest line') : $t('Paused')}
    </Switch>
  </div>

  <!-- A scroll area has to take focus so the keyboard can scroll it. -->
  <!-- svelte-ignore a11y-no-noninteractive-tabindex -->
  <div
    bind:this={listEl}
    on:scroll={onScroll}
    role="log"
    aria-label={$t('Application log')}
    tabindex="0"
    class="relative mt-2 min-h-0 flex-1 overflow-auto rounded-ui border border-line bg-surface py-2 text-whisper-lg leading-relaxed"
  >
    {#if !$records.length}
      <EmptyState
        title={$t('No entries yet')}
        description={$t('The app logs what it does as it runs. Entries appear here within a second of launch.')}
      />
    {:else if !shown.length}
      <EmptyState title={$t('Nothing matches')} description={$t('Change the search or the filters to see more lines.')} />
    {:else}
      {#each shown as r (r.id)}
        <div
          class="flex gap-x-2 border-l-2 px-3 py-px {r.user_message ? 'border-accent' : 'border-transparent'}"
          data-level={r.level}
          data-user={r.user_message ? 'true' : 'false'}
        >
          <span class="shrink-0 text-ink-faint">{r.time}</span>
          <span class="w-16 shrink-0 font-bold {levelClass(r.level)}">{r.level}</span>
          <span class="hidden shrink-0 md:inline {isOwn(r.logger) ? 'text-ink-soft' : 'text-ink-faint'}">{r.logger}:</span>
          <span class="min-w-0 whitespace-pre-wrap break-words {messageClass(r)}">{r.message}</span>
        </div>
      {/each}
    {/if}
  </div>
</div>

<AlertDialog
  bind:open={confirmClear}
  title={$t('Clear logs?')}
  description={$t('Discard the buffered lines ({count})? The log file on disk is not touched.', { count: $records.length })}
  confirmLabel={$t('Clear logs')}
  cancelLabel={$t('Keep logs')}
  on:confirm={clear}
/>
