<script>
  // The optional Hugging Face token. The runtime never sends the stored value
  // back, so the field is for entering a new one and the card says only
  // whether one is saved.
  import { onMount } from 'svelte';
  import { Button, TextField } from '@monos/ui';
  import { toast } from '../../lib/toast.js';
  import { call } from '../../lib/rpc.js';
  import { t } from '../../lib/i18n.js';

  let saved = false;
  let token = '';
  let working = false;

  const TOKENS_URL = 'https://huggingface.co/settings/tokens';

  function openTokens(event) {
    if (window.l2t?.shell?.openExternal) {
      event.preventDefault();
      window.l2t.shell.openExternal(TOKENS_URL);
    }
  }

  onMount(async () => {
    try {
      saved = (await call('models.hf_token.get')).set;
    } catch {
      // A card that cannot read it just offers to set one.
    }
  });

  async function save() {
    working = true;
    try {
      saved = (await call('models.hf_token.set', { token })).set;
      token = '';
      toast({ title: $t('Token saved'), tone: 'success' });
    } catch (err) {
      toast({ title: $t('The token was not saved'), description: err.message, tone: 'danger' });
    } finally {
      working = false;
    }
  }

  async function clear() {
    working = true;
    try {
      saved = (await call('models.hf_token.reset')).set;
      token = '';
      toast({ title: $t('Token cleared'), tone: 'neutral' });
    } catch (err) {
      toast({ title: $t('The token was not cleared'), description: err.message, tone: 'danger' });
    } finally {
      working = false;
    }
  }
</script>

<section class="flex flex-col gap-3" aria-label={$t('Hugging Face')} data-testid="hf-card">
  <h3 class="text-lg font-bold">{$t('Hugging Face')}</h3>
  <p class="text-xs text-ink-soft">
    {$t('Optional API token. Only needed to download gated or private repositories; the models in the catalogue are open.')}
    <a
      href={TOKENS_URL}
      target="_blank"
      rel="noopener noreferrer"
      class="text-accent-text underline underline-offset-2"
      data-testid="hf-token-link"
      on:click={openTokens}
    >{$t('Get a token on huggingface.co')}</a>
  </p>
  <TextField
    label={$t('API token')}
    type="password"
    autocomplete="off"
    placeholder={saved ? $t('A token is saved') : 'hf_…'}
    bind:value={token}
    on:keydown={(e) => e.detail?.key === 'Enter' && token.trim() && save()}
  />
  <div class="flex flex-wrap gap-2">
    <Button variant="secondary" disabled={working || !token.trim()} on:click={save}>
      {$t('Save token')}
    </Button>
    <Button variant="secondary" disabled={working || !saved} on:click={clear}>{$t('Clear token')}</Button>
  </div>
</section>
