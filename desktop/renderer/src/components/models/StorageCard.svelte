<script>
  // Where the weights live: the folder, its size, Change, Reset and Open. The
  // same card is used in the Models drawer and can be placed in Settings.
  import { onMount } from 'svelte';
  import { Button, Modal, Notice, Progress, TextField, toast } from '@monos/ui';
  import { call, subscribe } from '../../lib/rpc.js';
  import { t } from '../../lib/i18n.js';
  import { fmt, formatBytes } from './store.js';

  let info = null;
  let size = null;
  let error = '';
  let busy = false;
  let moving = null; // {done, total} while a move runs
  let result = null; // the last 'done' event, shown as a summary
  let plan = null; // the pending Move / Leave / Cancel question
  let manualPath = '';
  let askManual = false;

  const inElectron = typeof window !== 'undefined' && Boolean(window.l2t?.dialog?.openDirectory);

  async function refresh() {
    try {
      info = await call('models.storage.get');
      busy = info.busy;
      error = '';
    } catch (err) {
      error = err.message;
    }
  }

  onMount(() => {
    refresh();
    const off = subscribe('storage', (d) => {
      if (d.phase === 'size') {
        size = d.size_bytes;
      } else if (d.phase === 'moving') {
        busy = true;
        moving = { done: d.done_bytes, total: d.total_bytes };
      } else if (d.phase === 'done') {
        busy = false;
        moving = null;
        result = d;
        refresh();
      } else if (d.phase === 'error') {
        busy = false;
        moving = null;
        error = d.message;
      }
    });
    return off;
  });

  async function choose() {
    if (inElectron) {
      const chosen = await window.l2t.dialog.openDirectory({
        title: $t('Choose models folder'),
        defaultPath: info?.path,
      });
      const path = typeof chosen === 'string' ? chosen : (chosen?.filePaths?.[0] ?? chosen?.path ?? '');
      if (path) await propose(path);
    } else {
      askManual = true;
    }
  }

  async function propose(path) {
    result = null;
    try {
      const p = await call('models.storage.plan', { path });
      if (p.same) {
        toast({ title: $t('That is already the models folder.'), tone: 'neutral' });
        return;
      }
      if (p.old_size > 0) plan = p;
      else await apply(p.path, false);
    } catch (err) {
      toast({ title: $t('That folder cannot be used'), description: err.message, tone: 'danger' });
    }
  }

  async function apply(path, move) {
    plan = null;
    askManual = false;
    busy = true;
    try {
      await call('models.storage.apply', { path, move });
    } catch (err) {
      busy = false;
      toast({ title: $t('The folder was not changed'), description: err.message, tone: 'danger' });
    }
  }

  async function reset() {
    busy = true;
    result = null;
    try {
      await call('models.storage.reset');
    } catch (err) {
      busy = false;
      toast({ title: $t('The folder was not changed'), description: err.message, tone: 'danger' });
    }
  }

  async function open() {
    try {
      await call('models.storage.open');
    } catch (err) {
      toast({ title: $t('Could not open the folder'), description: err.message, tone: 'danger' });
    }
  }

  const reasons = {
    destination_exists: 'The new folder already has cached models.',
    copy_failed: 'The copy was interrupted. The old weights are still intact.',
    in_use: 'Some files are in use. Restart the app and try again, or delete the old weights by hand.',
  };

  $: summary = result && result.changed ? describe(result) : '';
  function describe(r) {
    const lines = [fmt($t('Models folder set to: %1'), r.path)];
    if (r.moved) lines.push(fmt($t('Moved %1.'), formatBytes(r.moved_bytes)));
    else if (r.skipped) lines.push($t(reasons[r.skipped] ?? r.reason));
    else if (r.left_bytes > 0) lines.push(fmt($t('Existing %1 of weights left at: %2'), formatBytes(r.left_bytes), r.old_root));
    lines.push($t('New downloads will land at the new location immediately.'));
    return lines.join(' ');
  }
</script>

<section class="flex flex-col gap-3" aria-label={$t('Storage')} data-testid="storage-card">
  <h3 class="text-lg font-bold">{$t('Storage')}</h3>
  <p class="text-xs text-ink-soft">
    {$t('Downloaded model weights live in this folder. A different drive is fine.')}
  </p>

  {#if error}
    <Notice tone="danger">{error}</Notice>
  {/if}

  {#if info}
    <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      <dt class="text-ink-soft">{$t('Folder')}</dt>
      <dd class="min-w-0 break-all" data-testid="storage-path">
        {info.path}{#if info.is_default}<span class="ml-1 text-ink-faint">{$t('(default)')}</span>{/if}
      </dd>
      <dt class="text-ink-soft">{$t('Used')}</dt>
      <dd data-testid="storage-size">{size === null ? $t('computing…') : formatBytes(size) || fmt($t('%1 MB'), 0)}</dd>
    </dl>
  {/if}

  {#if moving}
    <div class="flex flex-col gap-1">
      <Progress
        value={moving.total > 0 ? Math.round((moving.done * 100) / moving.total) : 0}
        label={$t('Moving cached models…')}
      />
      <span class="text-xs text-ink-soft">
        {$t('Moving cached models…')} {formatBytes(moving.done)} / {formatBytes(moving.total)}
      </span>
    </div>
  {:else if busy}
    <p class="text-xs text-ink-soft">{$t('Working…')}</p>
  {/if}

  {#if summary}
    <Notice tone="info" dismissible dismissLabel={$t('Dismiss')} on:dismiss={() => (result = null)}>{summary}</Notice>
  {/if}

  <div class="flex flex-wrap gap-2">
    <Button variant="secondary" disabled={busy} on:click={choose}>{$t('Change…')}</Button>
    <Button variant="secondary" disabled={busy || !info || info.is_default} on:click={reset}>
      {$t('Reset storage')}
    </Button>
    <Button variant="secondary" on:click={open}>{$t('Open folder')}</Button>
  </div>
</section>

<Modal
  open={plan !== null}
  title={$t('Move existing weights?')}
  description={plan ? fmt($t('You have %1 of cached models at %2.'), formatBytes(plan.old_size), plan.current) : ''}
  on:close={() => (plan = null)}
>
  {#if plan}
    <p class="text-sm text-ink-soft">{fmt($t('Move them to the new location? %1'), plan.path)}</p>
    <ul class="mt-3 list-disc pl-5 text-xs text-ink-soft">
      <li>{$t('Move: relocate now. On the same drive this is instant; across drives it can take several minutes.')}</li>
      <li>{$t('Leave: keep them in place; new downloads go to the new folder.')}</li>
      <li>{$t('Cancel: go back without changing anything.')}</li>
    </ul>
    {#if plan.destination_has_models}
      <Notice tone="warning" class="mt-3">{$t('The new folder already has cached models, so a move will be skipped.')}</Notice>
    {/if}
  {/if}
  <svelte:fragment slot="footer">
    <Button variant="secondary" on:click={() => (plan = null)}>{$t('Cancel')}</Button>
    <Button variant="secondary" on:click={() => apply(plan.path, false)}>{$t('Leave')}</Button>
    <Button on:click={() => apply(plan.path, true)}>{$t('Move')}</Button>
  </svelte:fragment>
</Modal>

<Modal open={askManual} title={$t('Choose models folder')} on:close={() => (askManual = false)}>
  <TextField label={$t('Folder')} bind:value={manualPath} placeholder="/path/to/models" />
  <svelte:fragment slot="footer">
    <Button variant="secondary" on:click={() => (askManual = false)}>{$t('Cancel')}</Button>
    <Button disabled={!manualPath.trim()} on:click={() => { askManual = false; propose(manualPath.trim()); }}>
      {$t('Choose')}
    </Button>
  </svelte:fragment>
</Modal>
