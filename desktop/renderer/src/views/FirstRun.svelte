<script>
  // First run: choose, download, learn the key. Shown instead of the shell
  // while there is no model on disk; see spec 002. Three steps, one job each.
  import { createEventDispatcher, onMount, onDestroy } from 'svelte';
  import { PageHeader, Stepper, Button, Notice, Kbd, Skeleton } from '@monos/ui';
  import { call } from '../lib/rpc.js';
  import { t } from '../lib/i18n.js';
  import { state as appState, progress, snapshot } from '../lib/backend.js';
  import {
    catalogue, languages, modelState, quietReady, loadModels, refreshState, wire, fmt,
    downloadModel, cancelLoad, downloadFigures,
  } from '../components/models/store.js';
  import ModelCard from '../components/models/ModelCard.svelte';
  import DownloadProgress from '../components/models/DownloadProgress.svelte';

  /** How often to ask whether loading is over; a prop so a test need not wait. */
  export let pollMs = 500;

  const dispatch = createEventDispatcher();

  let status = null;
  let step = 'choose';
  let failed = false;
  let startedAt = 0;
  let elapsed = 0;
  let run = 0;
  let settling = false;
  let timer = null;
  let problem = '';

  onMount(async () => {
    wire();
    quietReady.set(true);
    await Promise.all([loadModels(), loadStatus()]);
    // A window opened in the middle of the download picks the screen up where it is.
    if ($appState === 'model_loading') {
      begin(Date.now() - ($progress.elapsed || 0) * 1000);
      track();
    }
  });
  onDestroy(() => {
    clearInterval(timer);
    quietReady.set(false);
  });

  async function loadStatus() {
    try {
      status = await call('firstrun.status');
    } catch (err) {
      problem = err.message;
    }
  }

  // This screen has no sidebar and so no Logs; the file itself is the way to the reason.
  $: logPath = $snapshot?.log_path || '';
  $: canReveal = Boolean(logPath && typeof window !== 'undefined' && window.l2t?.shell?.showItemInFolder);

  $: candidate = status ? $catalogue.find((c) => c.alias === status.candidate) ?? null : null;
  $: steps = [
    { id: 'choose', label: $t('Choose') },
    { id: 'download', label: $t('Download') },
    { id: 'hotkey', label: $t('Learn the key') },
  ];
  $: figures = downloadFigures($progress, candidate);
  $: phase = figures.current > 0 ? 'download' : 'start';
  $: keys = (combo) => (combo ? combo.split('+').map((part) => part.trim()).filter(Boolean).map(label) : []);

  function label(part) {
    if (part.length <= 1) return part.toUpperCase();
    return part[0].toUpperCase() + part.slice(1);
  }

  function begin(at = Date.now()) {
    step = 'download';
    failed = false;
    problem = '';
    startedAt = at;
    run += 1;
    clearInterval(timer);
    timer = setInterval(() => (elapsed = Math.max(0, (Date.now() - startedAt) / 1000)), 250);
  }

  async function download() {
    // A retry after a failure: a runtime that still believes it is loading
    // would answer "busy", so it is asked to let go first.
    if (failed) await call('models.cancel_load').catch(() => {});
    begin();
    const result = await downloadModel(candidate.alias);
    if (!result) {
      fail();
      return;
    }
    await track();
  }

  function fail() {
    clearInterval(timer);
    failed = true;
  }

  // Waits for the runtime to say loading is over, by asking rather than by
  // watching the pushed state: a load that ends between two state polls is
  // never announced as a state, and a screen that waited for the
  // announcement would wait forever.
  async function track() {
    const mine = run;
    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, pollMs));
      if (mine !== run || step !== 'download') return;
      try {
        const now = await call('models.state');
        if (!now.loading) break;
        // A failure the runtime reported while it still says "loading" is a
        // failure: the screen must not sit on "Starting…" waiting for a
        // state that is not coming.
        if (failedSince(now.last_load)) {
          clearInterval(timer);
          failed = true;
          return;
        }
      } catch {
        // A hiccup in the channel is not the end of the download.
      }
    }
    await settle();
  }

  /** A load that ended in an error after this attempt began. */
  function failedSince(last) {
    return Boolean(last && last.outcome === 'error' && Number(last.at) * 1000 >= startedAt - 1000);
  }

  // Loading stopping only says loading stopped, which is what a failed fetch
  // looks like too. Advance only when the weights are on disk.
  async function settle() {
    if (settling || step !== 'download') return;
    settling = true;
    try {
      await refreshState();
      clearInterval(timer);
      if (candidate && $modelState.cached[candidate.alias]) step = 'hotkey';
      else failed = true;
    } finally {
      settling = false;
    }
  }

  async function cancel() {
    run += 1;
    step = 'choose';
    clearInterval(timer);
    await cancelLoad();
  }

  async function later() {
    try {
      await call('firstrun.defer', { reason: 'later' });
    } catch {
      // Leaving the screen does not depend on the runtime having heard about it.
    }
    dispatch('done');
  }

  async function catalogueInstead() {
    try {
      await call('firstrun.defer', { reason: 'catalogue' });
    } catch {
      // As above.
    }
    dispatch('catalogue');
  }

  async function finish() {
    try {
      await call('firstrun.complete');
    } catch (err) {
      problem = err.message;
      return;
    }
    dispatch('done');
  }

  $: header = {
    choose: {
      title: $t('Start dictating'),
      text: candidate
        ? fmt(
            $t('One download, then a hotkey puts what you say into whatever window you are typing in. No account, and speech never goes to a cloud. %1 is the model the app suggests as a starting point.'),
            $t(candidate.display_name),
          )
        : '',
    },
    download: {
      title: candidate ? fmt($t('Downloading %1'), $t(candidate.display_name)) : '',
      text: candidate ? fmt($t('%1 MB, once. Then it works offline.'), candidate.size_mb) : '',
    },
    hotkey: {
      title: $t('That is the whole setup'),
      text: $t('The key is the product. Everything else is configuration you will not touch again.'),
    },
  }[step];
</script>

<div class="flex h-full flex-col overflow-auto bg-canvas text-ink" data-testid="first-run">
  <div class="drag h-8 shrink-0"></div>
  <div class="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 px-6 pb-8">
    <Stepper {steps} value={step} label={$t('Setup steps')} />
    <PageHeader title={header.title} description={header.text} />

    {#if problem}
      <Notice tone="danger">{problem}</Notice>
    {/if}

    <div class="flex flex-1 flex-col justify-center gap-4">
      {#if step === 'choose'}
        {#if candidate}
          <ModelCard model={candidate} languages={$languages} compact cached={false} on:select={download} />
        {:else}
          <Skeleton height="12rem" />
        {/if}
        <div>
          <Button variant="text" on:click={catalogueInstead} title={$t('Open the full model catalogue and pick one yourself')}>
            {$t('See all models instead')}
          </Button>
        </div>
      {:else if step === 'download'}
        {#if failed}
          <Notice tone="warning" title={$t('The download did not finish.')}>
            {$t('Nothing was saved. Check that this computer is online, then press Try again.')}
            {#if canReveal}{$t('The log file has the exact reason.')}{/if}
          </Notice>
          <div class="flex flex-wrap gap-3">
            <Button on:click={download}>{$t('Try again')}</Button>
            <Button variant="secondary" on:click={() => ((step = 'choose'), (failed = false))}>{$t('Back')}</Button>
            {#if canReveal}
              <Button variant="secondary" on:click={() => window.l2t.shell.showItemInFolder(logPath)}>{$t('Show log file')}</Button>
            {/if}
          </div>
        {:else}
          <DownloadProgress {figures} {phase} {elapsed} />
          <p class="text-xs text-ink-faint">{$t('This happens once. The app works offline from here on.')}</p>
          <div>
            <Button variant="danger" size="sm" on:click={cancel}>{$t('Cancel')}</Button>
          </div>
        {/if}
      {:else}
        <div class="flex flex-wrap items-center justify-center gap-2" data-testid="hotkey-caps">
          {#each keys(status?.hotkeys?.start) as key}<Kbd>{key}</Kbd>{/each}
          {#if status?.hotkeys?.stop}
            <span class="px-2 text-sm text-ink-soft">{$t('to stop')}</span>
            {#each keys(status.hotkeys.stop) as key}<Kbd>{key}</Kbd>{/each}
          {/if}
        </div>
        <p class="text-center text-sm text-ink-soft">
          {$t('Press it, say a sentence, press stop. The text appears wherever you were typing.')}
        </p>
      {/if}
    </div>

    <div class="flex items-center justify-between gap-3 border-t border-line pt-4">
      {#if step !== 'hotkey'}
        <Button
          variant="text"
          on:click={later}
          title={$t('Skip this and open the app. With no model downloaded there is nothing to dictate yet.')}
        >
          {$t('Set up later')}
        </Button>
      {:else}
        <span></span>
      {/if}
      {#if step === 'hotkey'}
        <Button on:click={finish}>{$t('Start dictating')}</Button>
      {/if}
    </div>
  </div>
</div>
