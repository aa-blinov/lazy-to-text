<script>
  // The About dialog of the Qt app: name, version, what the engines are, and
  // the project link.
  import { Modal, Button } from '@monos/ui';
  import { t } from '../../lib/i18n.js';
  import { fmt } from '../../lib/hotkey.js';

  export let open = false;
  export let version = '';

  const URL = 'https://github.com/aa-blinov/lazy-to-text';

  function openLink(event) {
    if (window.l2t?.shell?.openExternal) {
      event.preventDefault();
      window.l2t.shell.openExternal(URL);
    }
  }
</script>

<Modal bind:open title={$t('About Lazy to Text')} size="sm" closeLabel={$t('Close')}>
  <div class="flex flex-col gap-3 text-sm text-ink-soft">
    <p class="text-ink">{fmt($t('Lazy to Text %1'), version)}</p>
    <p>
      {$t('Local speech recognition with Whisper, Parakeet and GigaAM on ONNX Runtime. Apple Silicon uses CoreML (Neural Engine and GPU). NVIDIA GPUs use CUDA or TensorRT.')}
    </p>
    <p><a href={URL} class="text-accent-text underline" on:click={openLink}>github.com/aa-blinov/lazy-to-text</a></p>
  </div>
  <svelte:fragment slot="footer">
    <Button variant="secondary" on:click={() => (open = false)}>{$t('Close')}</Button>
  </svelte:fragment>
</Modal>
