<script>
  import { onMount } from 'svelte';
  import { Sidebar, SidebarItem, Toaster, Spinner, Notice } from '@monos/ui';
  import { views } from './views/index.js';
  import { t, language, normaliseLanguage } from './lib/i18n.js';
  import { applyTheme, applyTextScale, normalisePalette, watchSystemTheme } from './lib/theme.js';
  import { start, snapshot, connected, startError } from './lib/backend.js';
  import { installFileInbox } from './lib/transcribe.js';
  import DropOverlay from './components/transcribe/DropOverlay.svelte';
  import StatusStrip from './components/StatusStrip.svelte';
  import FirstRun from './views/FirstRun.svelte';

  let current = 'transcribe';
  let ready = false;
  // Decided once from the first snapshot: with no model on disk the setup
  // screen replaces the shell until it is finished or set aside.
  let firstRun = null;

  $: active = views.find((v) => v.id === current) ?? views[0];
  $: ui = $snapshot?.config?.ui ?? {};
  $: if ($snapshot && firstRun === null) firstRun = Boolean($snapshot.first_run);
  $: if ($snapshot) {
    language.set(normaliseLanguage(ui.language));
    applyTheme(ui.theme || 'system', normalisePalette(ui.palette));
    applyTextScale(ui.text_scale);
  }

  // Cmd/Ctrl+1..6 jump to the screens in sidebar order (FR-012).
  function onKeydown(event) {
    if (firstRun || !(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
    // Cmd/Ctrl+, opens Settings from anywhere, as in the Qt app menu.
    if (event.key === ',') {
      event.preventDefault();
      current = 'settings';
      return;
    }
    const view = views[Number(event.key) - 1];
    if (!view) return;
    event.preventDefault();
    current = view.id;
  }

  onMount(() => {
    start()
      .then(() => (ready = true))
      .catch(() => (ready = true));
    const stopWatch = watchSystemTheme(() => applyTheme(ui.theme || 'system', normalisePalette(ui.palette)));
    window.l2t?.onNavigate?.((id) => {
      if (!firstRun) current = id;
    });
    // Drop anywhere and OS file opens bring the Transcribe screen forward.
    installFileInbox({ navigate: () => (current = 'transcribe') });
    return stopWatch;
  });
</script>

<svelte:window on:keydown={onKeydown} />

{#if ready && $connected && firstRun}
  <FirstRun
    on:done={() => (firstRun = false)}
    on:catalogue={() => ((firstRun = false), (current = 'models'))}
  />
{:else}
<div class="flex h-full flex-col bg-canvas text-ink">
<div class="flex min-h-0 flex-1">
  <Sidebar label={$t('Navigation')} width="14rem">
    <div class="drag h-8 shrink-0"></div>
    <nav class="flex flex-col gap-1 p-2">
      {#each views as view (view.id)}
        <SidebarItem active={current === view.id} on:click={() => (current = view.id)}>
          {$t(view.label)}
        </SidebarItem>
      {/each}
    </nav>
  </Sidebar>

  <main class="min-w-0 flex-1 overflow-auto">
    {#if !ready}
      <div class="flex h-full items-center justify-center"><Spinner /></div>
    {:else if !$connected}
      <div class="p-6"><Notice tone="danger">{$startError || $t('The backend is not running.')}</Notice></div>
    {:else}
      <svelte:component this={active.component} />
    {/if}
  </main>
</div>
{#if $connected}<StatusStrip />{/if}
</div>
{/if}
<DropOverlay />
<Toaster />
