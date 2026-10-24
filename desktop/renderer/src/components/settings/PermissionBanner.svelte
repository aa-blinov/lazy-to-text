<script>
  // A macOS permission warning: one paragraph that names the exact System
  // Settings pane, and the one action that fixes it. The visible verb is
  // short ("Grant access") on two banners, so the accessible name carries
  // what the sentence above it says.
  import { createEventDispatcher } from 'svelte';
  import { Notice, Button } from '@monos/ui';
  import { t } from '../../lib/i18n.js';

  export let kind; // accessibility | microphone | post_event
  export let state; // untrusted | not_determined | denied

  const dispatch = createEventDispatcher();

  $: copy = describe(kind, state, $t);

  function describe(k, s, tr) {
    if (k === 'accessibility') {
      return {
        text: tr("Global hotkeys won't fire until you allow Lazy to Text under System Settings → Privacy & Security → Accessibility."),
        action: tr('Grant access'),
        name: tr('Grant accessibility access'),
        description: tr('Opens the system settings page for accessibility access.'),
      };
    }
    if (k === 'microphone' && s === 'denied') {
      return {
        text: tr('Microphone is blocked, so recordings come back empty. Enable Lazy to Text under System Settings → Privacy & Security → Microphone.'),
        action: tr('Open Settings'),
        name: tr('Open microphone settings'),
        description: tr('Opens the system settings page for microphone access.'),
      };
    }
    if (k === 'microphone') {
      return {
        text: tr('macOS has not asked for microphone access yet. Without it, recordings come back empty with no warning.'),
        action: tr('Grant access'),
        name: tr('Grant microphone access'),
        description: tr('Opens the system settings page for microphone access.'),
      };
    }
    return {
      text: tr('macOS has not allowed keyboard control yet. The app can still copy text to the clipboard, but Cmd+V auto-paste will not reach the focused window until you allow Lazy to Text under System Settings → Privacy & Security → Accessibility.'),
      action: tr('Allow auto-paste access'),
      name: tr('Allow auto-paste access'),
      description: tr('Opens the system settings page for accessibility access.'),
    };
  }
</script>

<div data-permission={kind} class="py-3 first:pt-1">
  <Notice tone="warning">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <p class="min-w-0 flex-1 basis-64 text-sm">{copy.text}</p>
      <Button
        variant="secondary"
        size="sm"
        aria-label={copy.name}
        title={copy.description}
        on:click={() => dispatch('act', { kind, state })}
      >
        {copy.action}
      </Button>
    </div>
  </Notice>
</div>
