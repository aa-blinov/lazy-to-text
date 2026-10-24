<script>
  // A field that records the key press itself instead of parsing typed text.
  // Activate it (click, Enter, Space), press the combination, and the binding
  // is proposed to the parent, which validates it with the runtime's rules.
  // Solo modifiers are captured on release, and only where push-to-talk
  // allows them. "Type it instead" is the way in for keys a browser never
  // reports (Fn on most keyboards).
  import { createEventDispatcher, tick } from 'svelte';
  import { Kbd, Button, FieldControl } from '@monos/ui';
  import { t } from '../../lib/i18n.js';
  import { interpretKeydown, interpretKeyup, bindingParts, heldModifiers } from '../../lib/hotkey.js';

  export let value = '';
  export let label = '';
  export let platform = 'linux';
  export let allowEmpty = false;
  export let allowSolo = false;
  export let disabled = false;
  export let error = '';
  export let hint = '';
  export let placeholder = '';
  export let id = `hk-${Math.random().toString(36).slice(2, 8)}`;

  const dispatch = createEventDispatcher();

  let listening = false;
  let typing = false;
  let typed = '';
  let preview = [];
  let sawOtherKey = false;
  let announce = '';
  let button;
  let textEl;

  $: parts = bindingParts(value, platform);
  $: describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;

  function begin() {
    if (disabled || listening) return;
    listening = true;
    sawOtherKey = false;
    preview = [];
    announce = $t('Press the keys');
  }

  function end(message = '') {
    listening = false;
    preview = [];
    announce = message;
  }

  function commit(text) {
    end(text ? '' : $t('Cleared'));
    if (text !== value) dispatch('change', text);
  }

  function onKeydown(event) {
    if (!listening) return;
    const result = interpretKeydown(event, { platform, allowEmpty, allowSolo });
    if (result.kind === 'leave') {
      end();
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    switch (result.kind) {
      case 'cancel': end(); break;
      case 'clear': commit(''); break;
      case 'modifiers': preview = result.mods; break;
      case 'solo':
      case 'combo':
        sawOtherKey = true;
        commit(result.text);
        break;
      default: break;
    }
  }

  function onKeyup(event) {
    if (!listening) return;
    const text = interpretKeyup(event, { platform, allowSolo, sawOtherKey });
    if (text) {
      event.preventDefault();
      commit(text);
      return;
    }
    preview = heldModifiers(event);
  }

  async function startTyping() {
    typing = true;
    typed = value;
    await tick();
    textEl?.focus();
  }

  function finishTyping() {
    typing = false;
    const text = typed.trim();
    if (text !== value) dispatch('change', text);
    tick().then(() => button?.focus());
  }

  function onTypedKey(event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      finishTyping();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      typing = false;
      tick().then(() => button?.focus());
    }
  }
</script>

<div class="flex flex-col gap-1">
  {#if typing}
    <div class="flex items-end gap-2">
      <FieldControl
        id={`${id}-text`}
        size="sm"
        variant="boxed"
        class="flex-1"
        {placeholder}
        aria-label={label || $t('Hotkey')}
        bind:value={typed}
        bind:inputEl={textEl}
        on:keydown={onTypedKey}
        on:blur={finishTyping}
      />
    </div>
  {:else}
    <div class="flex flex-wrap items-center gap-2">
      <button
        bind:this={button}
        {id}
        type="button"
        {disabled}
        aria-label={label ? `${label}: ${value || placeholder || $t('Not set')}` : undefined}
        aria-describedby={describedBy}
        aria-invalid={error ? 'true' : undefined}
        class="flex min-h-9 min-w-[12rem] flex-1 items-center gap-1.5 rounded-ui border px-3 py-1.5 text-left text-sm transition-colors duration-fast focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 {error
          ? 'border-danger'
          : listening
            ? 'border-ink'
            : 'border-line hover:border-line-strong'} {disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'} bg-canvas text-ink"
        on:click={begin}
        on:keydown={onKeydown}
        on:keyup={onKeyup}
        on:blur={() => listening && end()}
      >
        {#if listening}
          {#if preview.length}
            {#each bindingParts(preview.join('+'), platform) as part, i}
              {#if i > 0}<span class="text-ink-faint" aria-hidden="true">+</span>{/if}
              <Kbd>{part}</Kbd>
            {/each}
            <span class="text-ink-faint">{allowSolo ? $t('release to use it alone, or press another key') : $t('now press a key')}</span>
          {:else}
            <span class="text-ink-soft">{$t('Press the keys')}</span>
            {#if allowEmpty}<span class="text-ink-faint">{$t('Backspace clears')}</span>{/if}
          {/if}
        {:else if parts.length}
          {#each parts as part, i}
            {#if i > 0}<span class="text-ink-faint" aria-hidden="true">+</span>{/if}
            <Kbd>{part}</Kbd>
          {/each}
        {:else}
          <span class="text-ink-faint">{placeholder || $t('Not set')}</span>
        {/if}
      </button>
      <Button variant="quiet" size="sm" {disabled} on:click={startTyping}>{$t('Type it instead')}</Button>
    </div>
  {/if}

  <div class="sr-only" aria-live="polite">{announce}</div>
  {#if error}
    <p id="{id}-error" class="text-xs text-danger-text" role="alert">{error}</p>
  {:else if hint}
    <p id="{id}-hint" class="text-xs text-ink-faint">{hint}</p>
  {/if}
</div>
