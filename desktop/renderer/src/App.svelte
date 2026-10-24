<script>
  import { onMount } from 'svelte';
  import { Sidebar, SidebarItem, Toaster, Spinner, Notice } from '@monos/ui';
  import { views } from './views/index.js';
  import { t, language, normaliseLanguage } from './lib/i18n.js';
  import { applyTheme, watchSystemTheme } from './lib/theme.js';
  import { start, snapshot, connected, startError, state, engine } from './lib/backend.js';

  let current = 'transcribe';
  let ready = false;

  $: active = views.find((v) => v.id === current) ?? views[0];
  $: ui = $snapshot?.config?.ui ?? {};
  $: if ($snapshot) {
    language.set(normaliseLanguage(ui.language));
    applyTheme(ui.theme || 'system');
  }

  onMount(() => {
    start()
      .then(() => (ready = true))
      .catch(() => (ready = true));
    const stopWatch = watchSystemTheme(() => applyTheme(ui.theme || 'system'));
    window.l2t?.onNavigate?.((id) => (current = id));
    return stopWatch;
  });
</script>

<div class="flex h-full bg-canvas text-ink">
  <Sidebar label={$t('Navigation')} width="14rem">
    <div class="drag h-8 shrink-0"></div>
    <nav class="flex flex-col gap-1 p-2">
      {#each views as view (view.id)}
        <SidebarItem active={current === view.id} on:click={() => (current = view.id)}>
          {$t(view.label)}
        </SidebarItem>
      {/each}
    </nav>
    <div class="mt-auto p-3 text-xs text-ink-soft">
      <div>{$state}</div>
      <div class="truncate">{$engine.alias || ''}</div>
    </div>
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
<Toaster />
