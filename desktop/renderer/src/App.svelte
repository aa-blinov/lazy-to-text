<script>
  import { onMount } from 'svelte';
  import { Sidebar, SidebarItem, Toaster, Spinner, Notice, Button, AlertDialog } from '@monos/ui';
  import { views } from './views/index.js';
  import { t, language, normaliseLanguage } from './lib/i18n.js';
  import { applyTheme, applyTextScale, normalisePalette, watchSystemTheme } from './lib/theme.js';
  import { start, retryStart, snapshot, connected, startError, epoch } from './lib/backend.js';
  import { installFileInbox, discardAsk, answerDiscard } from './lib/transcribe.js';
  import { requestedView, shellShown, aboutRequested } from './lib/nav.js';
  import { focusScreen } from './lib/focus.js';
  import { toast } from './lib/toast.js';
  import { subscribe } from './lib/rpc.js';
  import { translateRuntime } from './lib/i18n.js';
  import DropOverlay from './components/transcribe/DropOverlay.svelte';
  import StatusStrip from './components/StatusStrip.svelte';
  import EngineDown from './components/EngineDown.svelte';
  import FirstRun from './views/FirstRun.svelte';

  let current = 'transcribe';
  let ready = false;
  // Decided once from the first snapshot: with no model on disk the setup
  // screen replaces the shell until it is finished or set aside.
  let firstRun = null;

  $: active = views.find((v) => v.id === current) ?? views[0];
  $: ui = $snapshot?.config?.ui ?? {};
  $: if ($snapshot && firstRun === null) firstRun = Boolean($snapshot.first_run);
  // Files handed to the app wait for this (lib/transcribe.js).
  $: shellShown.set(ready && firstRun === false);
  $: if ($requestedView) {
    if (!firstRun && views.some((v) => v.id === $requestedView)) current = $requestedView;
    requestedView.set(null);
  }
  $: if ($snapshot) {
    language.set(normaliseLanguage(ui.language));
    // A screen reader picks its voice from this, so it follows the interface.
    document.documentElement.lang = normaliseLanguage(ui.language);
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
      focusScreen();
      return;
    }
    const view = views[Number(event.key) - 1];
    if (!view) return;
    event.preventDefault();
    current = view.id;
    focusScreen();
  }

  // A runtime that is not up yet is asked again, not given up on.
  let bootTimer = null;
  function boot() {
    start()
      .then(() => (ready = true))
      .catch(() => {
        ready = true;
        bootTimer = setTimeout(boot, 2500);
      });
  }

  onMount(() => {
    boot();
    const stopWatch = watchSystemTheme(() => applyTheme(ui.theme || 'system', normalisePalette(ui.palette)));
    window.l2t?.onNavigate?.((id) => {
      if (firstRun) return;
      if (id === 'about') {
        // The About entry of the menu (Windows and Linux): the dialog lives on Settings.
        current = 'settings';
        aboutRequested.update((n) => n + 1);
        return;
      }
      current = id;
      focusScreen();
    });
    // A dictation that ended without text names the reason on screen as well
    // as in the capsule, which is a separate window that may be out of sight.
    const stopDelivery = subscribe('delivery', (d) => {
      if (d?.outcome !== 'failed' || !d.detail) return;
      toast({
        id: 'delivery-failed',
        title: d.kind === 'too_short' ? $t('Recording too short') : $t('Delivery failed'),
        description: translateRuntime(d.detail),
        tone: 'warning',
      });
    });
    // Drop anywhere and OS file opens bring the Transcribe screen forward.
    installFileInbox({ navigate: () => (current = 'transcribe') });
    return () => {
      stopWatch();
      stopDelivery();
      clearTimeout(bootTimer);
    };
  });
</script>

<svelte:window on:keydown={onKeydown} />

{#if !ready}
  <!-- Before the first answer from the runtime nothing says whether this is
       the setup screen or the shell, so neither is drawn: no sidebar that is
       replaced a moment later. -->
  <div class="flex h-full items-center justify-center bg-canvas" data-testid="booting"><Spinner /></div>
{:else if ready && $connected && firstRun}
  <FirstRun
    on:done={() => (firstRun = false)}
    on:catalogue={() => ((firstRun = false), (current = 'models'))}
  />
{:else}
<div class="flex h-full flex-col bg-canvas text-ink">
<!-- First Tab stop: jumps past the sidebar into the screen. -->
<a
  href="#main"
  class="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded-ui focus:border focus:border-line focus:bg-canvas focus:px-3 focus:py-2 focus:text-sm focus:font-bold focus:text-ink focus:shadow-overlay"
  on:click|preventDefault={() => focusScreen({ tries: 0 })}
>{$t('Skip to content')}</a>
<div class="flex min-h-0 flex-1">
  <!-- Capped by the window as well: at a large text size 14rem is most of it. -->
  <Sidebar label={$t('Navigation')} width="min(14rem, 30vw)">
    <div class="drag h-8 shrink-0"></div>
    <nav class="flex flex-col gap-1 p-2">
      {#each views as view (view.id)}
        <SidebarItem title={$t(view.label)} active={current === view.id} on:click={() => (current = view.id)}>
          {$t(view.label)}
        </SidebarItem>
      {/each}
    </nav>
  </Sidebar>

  <main id="main" class="min-w-0 flex-1 overflow-auto">
    {#if !$connected}
      <div class="flex flex-col items-start gap-3 p-6">
        <Notice tone="danger" class="w-full">{$startError ? $t($startError) : $t('The backend is not running.')}</Notice>
        <Button variant="secondary" on:click={() => retryStart().catch(() => {})}>{$t('Try again')}</Button>
      </div>
    {:else}
      {#key $epoch}
        <svelte:component this={active.component} />
      {/key}
    {/if}
  </main>
</div>
{#if $connected}<StatusStrip on:models={() => (current = 'models')} />{/if}
</div>
{/if}
<DropOverlay />
<EngineDown />
<AlertDialog
  open={$discardAsk !== null}
  title={$t('Replace the edited transcript?')}
  description={$t('You changed the text by hand. Transcribing another file discards those changes.')}
  confirmLabel={$t('Replace')}
  cancelLabel={$t('Keep editing')}
  on:confirm={() => answerDiscard(true)}
  on:cancel={() => answerDiscard(false)}
/>
<!-- Above the status strip (h-9), so a toast never hides the load figures. -->
<Toaster class="!bottom-9" max={3} dismissLabel={$t('Dismiss')} />
