<script>
  // Shown over everything when the runtime stops answering. It cannot be
  // dismissed: nothing in the window works without the engine, and a window
  // that looks alive is what made a dead engine easy to miss. It reconnects
  // by itself when the engine is back; Restart is for when it is not.
  import { Modal, Button, Notice } from '@monos/ui';
  import { t } from '../lib/i18n.js';
  import { snapshot, engineDown, restarting, restartError, restartEngine, lastLogPath } from '../lib/backend.js';

  $: logPath = $snapshot?.log_path || lastLogPath();
  $: canRestart = typeof window !== 'undefined' && typeof window.l2t?.backend?.restart === 'function';
  $: canReveal = Boolean(logPath && typeof window !== 'undefined' && window.l2t?.shell?.showItemInFolder);

  function reveal() {
    window.l2t.shell.showItemInFolder(logPath);
  }
</script>

<Modal
  open={$engineDown}
  title={$t('The engine stopped')}
  description={$t('Dictation and file transcription are off until it runs again. Your history and settings are safe.')}
  closeLabel={$t('Close')}
  closeOnBackdrop={false}
  closeOnEscape={false}
  showClose={false}
  role="alertdialog"
>
  <div class="flex flex-col gap-3 text-xs text-ink-soft" data-testid="engine-down">
    <p>{$t('The window is trying to reconnect by itself.')}</p>
    {#if logPath}
      <p class="break-all text-xs text-ink-faint">
        {$t('The log with the reason is at: {path}', { path: logPath })}
      </p>
    {/if}
    {#if $restartError}
      <Notice tone="danger">{$t($restartError)}</Notice>
    {/if}
  </div>
  <svelte:fragment slot="footer">
    {#if canReveal}
      <Button variant="secondary" on:click={reveal}>{$t('Show log file')}</Button>
    {/if}
    <Button loading={$restarting} on:click={restartEngine}>
      {canRestart ? $t('Restart') : $t('Try again')}
    </Button>
  </svelte:fragment>
</Modal>
