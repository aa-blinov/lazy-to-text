<script>
  import { Upload } from 'lucide-svelte';
  import { t } from '../../lib/i18n.js';
  import { dragging } from '../../lib/transcribe.js';
</script>

<!-- Drop anywhere: shown over whatever screen is open while a file is dragged
     over the window. It takes no pointer events, so the drop still lands on
     the window listener in lib/transcribe.js. -->
{#if $dragging}
  <div
    class="pointer-events-none fixed inset-2 z-50 flex items-center justify-center rounded-ui border-2 border-dashed border-accent bg-canvas/90"
    data-testid="drop-overlay"
    role="status"
  >
    <div class="flex flex-col items-center gap-2 text-ink">
      <Upload size={24} aria-hidden="true" />
      <span class="text-sm">{$t('Drop an audio or video file here')}</span>
    </div>
  </div>
{/if}
