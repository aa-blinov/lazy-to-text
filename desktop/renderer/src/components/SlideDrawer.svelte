<script>
  // A panel that slides in from the right and slides back out when it closes.
  // The kit's Drawer removes itself the moment it closes, so the panel vanished
  // instead of going back where it came from. This keeps the same markup and
  // look, and leaves the DOM only once the exit has run. It is a modal dialog:
  // focus is held, Escape and a click on the backdrop close it, and focus goes
  // back to whatever opened it.
  import { createEventDispatcher, onDestroy, tick } from 'svelte';
  import { IconButton } from '@monos/ui';

  export let open = false;
  export let title = '';
  export let closeLabel = 'Close';

  const dispatch = createEventDispatcher();
  const titleId = `slide-drawer-title-${Math.random().toString(36).slice(2, 8)}`;
  // Enough for the 200 ms exit, with margin for a slow frame.
  const EXIT_FALLBACK_MS = 260;

  let mounted = false;
  let leaving = false;
  let panel;
  let lastFocused = null;
  let previousOverflow = '';
  let fallback = null;

  $: if (open && !mounted) show();
  $: if (!open && mounted && !leaving) hide();

  async function show() {
    clearTimeout(fallback);
    mounted = true;
    leaving = false;
    lastFocused = typeof document !== 'undefined' ? document.activeElement : null;
    previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    await tick();
    panel?.focus();
  }

  function hide() {
    leaving = true;
    if (reducedMotion()) {
      finish();
      return;
    }
    // The exit animation's end removes the panel; the timer covers a platform
    // that does not report that end.
    fallback = setTimeout(finish, EXIT_FALLBACK_MS);
  }

  function finish() {
    clearTimeout(fallback);
    mounted = false;
    leaving = false;
    document.body.style.overflow = previousOverflow;
    if (lastFocused && typeof lastFocused.focus === 'function') lastFocused.focus();
    lastFocused = null;
  }

  function onAnimationEnd(event) {
    if (leaving && event.target === event.currentTarget) finish();
  }

  function requestClose() {
    if (!open) return;
    open = false;
    dispatch('close');
  }

  function reducedMotion() {
    return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  }

  function focusables() {
    if (!panel) return [];
    return [
      ...panel.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      ),
    ].filter((el) => el.offsetParent !== null || el === document.activeElement);
  }

  function onKeydown(event) {
    if (!mounted || leaving) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      requestClose();
      return;
    }
    if (event.key !== 'Tab') return;
    // Keep Tab inside the panel, as the kit's Drawer does.
    const all = focusables();
    if (!all.length) {
      event.preventDefault();
      panel?.focus();
      return;
    }
    const first = all[0];
    const last = all[all.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === panel)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  onDestroy(() => {
    clearTimeout(fallback);
    if (mounted && typeof document !== 'undefined') document.body.style.overflow = previousOverflow;
  });
</script>

<svelte:window on:keydown={onKeydown} />

{#if mounted}
  <div class="fixed inset-0 z-modal">
    <button
      type="button"
      tabindex="-1"
      aria-label={closeLabel}
      class="absolute inset-0 h-full w-full cursor-default bg-black/20 backdrop-blur-sm"
      on:click={requestClose}
    ></button>
    <section
      bind:this={panel}
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? titleId : undefined}
      tabindex="-1"
      class="ui-drawer absolute inset-y-0 right-0 w-full max-w-md overflow-y-auto border-l border-line bg-canvas p-6 text-ink shadow-overlay outline-none"
      class:leaving
      on:animationend={onAnimationEnd}
    >
      <IconButton
        label={closeLabel}
        variant="ghost"
        size="sm"
        tooltipText=""
        class="absolute right-3 top-3"
        on:click={requestClose}
      >
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="m6 6 12 12M18 6 6 18" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
        </svg>
      </IconButton>

      {#if title}
        <h2 id={titleId} class="pr-10 text-lg font-bold tracking-tight">{title}</h2>
      {/if}

      <div class="mt-4">
        <slot />
      </div>
    </section>
  </div>
{/if}

<style>
  .ui-drawer {
    animation: slide-drawer-in 200ms cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  .ui-drawer.leaving {
    animation: slide-drawer-out 200ms cubic-bezier(0.4, 0, 1, 1) forwards;
  }
  @keyframes slide-drawer-in {
    from {
      opacity: 0.6;
      transform: translateX(100%);
    }
    to {
      opacity: 1;
      transform: translateX(0);
    }
  }
  @keyframes slide-drawer-out {
    from {
      opacity: 1;
      transform: translateX(0);
    }
    to {
      opacity: 0.6;
      transform: translateX(100%);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .ui-drawer,
    .ui-drawer.leaving {
      animation: none;
    }
  }
</style>
