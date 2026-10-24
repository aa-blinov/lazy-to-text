<script>
  // The capsule. The window that holds it is shown and hidden by the main
  // process from the same events; this page only draws what they say. The
  // confirmation survives the state returning to idle (the pipeline reaches
  // idle milliseconds after reporting delivery) and is cancelled by a new
  // recording.
  import { onMount, onDestroy } from 'svelte';
  import { start, refresh, snapshot, state, level } from './lib/backend.js';
  import { subscribe } from './lib/rpc.js';
  import { t, language, normaliseLanguage, translateRuntime } from './lib/i18n.js';
  import { applyTheme, normalisePalette, watchSystemTheme } from './lib/theme.js';
  import LevelMeter from './components/LevelMeter.svelte';
  import { capsuleCopy, clampMiddle, clock, DELIVERY_VISIBLE_MS } from './components/capsule/copy.js';

  let delivery = null;
  let deliveryTimer = null;
  let startedAt = 0;
  let now = Date.now();
  let ticker = null;
  let unsubscribe = [];

  $: ui = $snapshot?.config?.ui ?? {};
  // The capsule is its own window and its own page: it takes the palette,
  // the mode and the language from the same config as the main window.
  $: if ($snapshot) {
    language.set(normaliseLanguage(ui.language));
    applyTheme(ui.theme || 'system', normalisePalette(ui.palette));
    document.documentElement.lang = normaliseLanguage(ui.language);
  }

  // The config is read at start; a theme changed since then is picked up when
  // the next recording begins, which is when the capsule is next seen.
  $: if ($state === 'recording') refresh().catch(() => {});

  // A new recording or processing run ends any confirmation still up.
  $: if ($state === 'recording' || $state === 'processing') dropDelivery();
  $: if ($state === 'recording') beginClock(); else endClock();

  $: copy = capsuleCopy({ state: $state, delivery }, $t, (x) => ($language, translateRuntime(x)));
  $: elapsed = clock(now - startedAt);

  function dropDelivery() {
    clearTimeout(deliveryTimer);
    delivery = null;
  }

  function beginClock() {
    if (ticker) return;
    startedAt = Date.now();
    now = startedAt;
    ticker = setInterval(() => (now = Date.now()), 250);
  }

  function endClock() {
    clearInterval(ticker);
    ticker = null;
  }

  onMount(() => {
    document.documentElement.style.background = 'transparent';
    // The window is a fixed size, so the capsule is not part of the interface
    // text scale (boot.js skips it on this page; this covers a size already set).
    document.documentElement.style.fontSize = '';
    start().catch(() => {});
    const stopWatch = watchSystemTheme(() => applyTheme(ui.theme || 'system', normalisePalette(ui.palette)));
    unsubscribe = [
      stopWatch,
      subscribe('delivery', (d) => {
        delivery = d;
        clearTimeout(deliveryTimer);
        deliveryTimer = setTimeout(() => (delivery = null), DELIVERY_VISIBLE_MS);
      }),
    ];
  });

  onDestroy(() => {
    endClock();
    clearTimeout(deliveryTimer);
    unsubscribe.forEach((off) => off());
  });

  const dots = {
    danger: 'bg-danger',
    accent: 'bg-accent',
    success: 'bg-success',
    info: 'bg-info',
  };
</script>

<!-- Against the right edge: the window sits in the bottom-right corner of the display. -->
<div class="capsule-stage flex h-screen items-center justify-end px-2">
  {#if copy}
    <div
      class="flex h-14 w-fit max-w-full items-center gap-3 rounded-ui border border-line bg-surface px-4 text-ink shadow-lift"
      role="status"
      aria-label={$t('Recording status')}
      data-kind={copy.kind}
    >
      <span
        class="h-3.5 w-3.5 shrink-0 rounded-ui border border-ink-soft {dots[copy.tone]} {copy.kind === 'recording' || copy.kind === 'processing' ? 'motion-safe:animate-pulse' : ''}"
        data-testid="dot"
        data-tone={copy.tone}
        aria-hidden="true"
      ></span>
      <div class="min-w-0">
        <div class="truncate text-xs font-bold uppercase tracking-widest">{copy.title}</div>
        <div class="text-xs text-ink-soft {copy.kind === 'failed' ? 'line-clamp-2' : 'truncate'}" title={copy.kind === 'failed' ? copy.body : undefined}>{copy.kind === 'failed' ? clampMiddle(copy.body) : copy.body}</div>
      </div>
      {#if copy.kind === 'recording'}
        <div class="flex shrink-0 items-center gap-3 pl-1">
          <span class="text-xs tabular-nums text-ink-soft" data-testid="clock">{elapsed}</span>
          <LevelMeter level={$level} label={$t('Microphone level')} />
        </div>
      {/if}
    </div>
  {/if}
</div>
