<script>
  // The language-model settings card. The post-processing switch is inside
  // it, next to the fields it governs: it is a property of these settings,
  // not a card of its own.
  import { createEventDispatcher } from 'svelte';
  import { Card, Switch, TextField, TextArea, Select, Button, Notice, Spinner } from '@monos/ui';
  import { t, formatNumber } from '../../lib/i18n.js';
  import { providerValue, privacyKind } from './model.js';

  export let enabled = false;
  export let draft = null;
  export let catalogue = { providers: [], modes: [], efforts: [], limits: {} };
  export let local = null;
  /** {field: sentence} from a refused save. */
  export let fieldErrors = {};
  /** Why the address being typed is not acceptable, from the privacy check. */
  export let addressNote = '';
  export let testing = false;
  export let testResult = null;

  const dispatch = createEventDispatcher();

  $: providerOptions = catalogue.providers.map((p) => ({ value: p.id, label: $t(p.label) }));
  $: modeOptions = catalogue.modes.map((m) => ({ value: m.id, label: $t(m.label) }));
  $: mode = catalogue.modes.find((m) => m.id === draft?.mode);
  $: effortOptions = [
    { value: '', label: $t('Provider default') },
    ...catalogue.efforts.map((e) => ({ value: e, label: effortLabel(e, $t) })),
  ];
  $: privacy = privacyKind(local);
  // What the runtime refused beats what it says while typing, which beats a
  // stored value it already knew to be bad.
  $: serverError = fieldErrors.base_url || addressNote || draft?.base_url_error || '';
  $: limits = catalogue.limits ?? {};
  $: off = !draft;

  function effortLabel(effort, tr) {
    if (effort === 'none') return tr('Off (fastest)');
    if (effort === 'minimal') return tr('Minimal');
    if (effort === 'low') return tr('Low');
    if (effort === 'medium') return tr('Medium');
    if (effort === 'high') return tr('High');
    return effort;
  }

  const commit = () => dispatch('commit');
  const touch = () => dispatch('touch');
</script>

<Card>
  <h2 class="text-sm font-bold uppercase tracking-widest text-ink">{$t('Language model')}</h2>
  <p class="mt-2 text-xs leading-relaxed text-ink-soft">
    {$t('Optional. Rewrites dictated text before it is pasted. Speech stays on this computer; a cloud model receives your words.')}
  </p>

  <div class="mt-4">
    <Switch checked={enabled} on:change={(e) => dispatch('toggle', e.detail)}>
      {$t('Rewrite dictated text before it is pasted')}
    </Switch>
  </div>
  <p class="mt-2 text-xs text-ink-faint">
    {$t('In every mode, numbers are written as digits (42, not сорок два), and the language stays the same. Nothing is translated.')}
  </p>

  {#if draft}
    <!-- Columns follow the card's width, not the window's: a large text size
         narrows the card and a viewport breakpoint cannot see that. -->
    <div class="mt-5 grid grid-cols-[repeat(auto-fit,minmax(min(100%,18rem),1fr))] items-start gap-x-6 gap-y-4">
      <TextField
        label={$t('Name')}
        placeholder={$t('Work, Letters, Quick notes')}
        bind:value={draft.name}
        error={fieldErrors.name || ''}
        on:input={touch}
        on:change={commit}
        autocomplete="off"
      />
      <Select
        label={$t('Provider')}
        value={providerValue(draft, catalogue)}
        options={providerOptions}
        on:change={(e) => dispatch('provider', e.detail.value)}
      />
      <TextField
        label={$t('Server')}
        bind:value={draft.base_url}
        error={serverError}
        on:input={() => { draft.base_url_error = null; touch(); dispatch('address'); }}
        on:change={commit}
        autocomplete="off"
        spellcheck="false"
      />
      <TextField
        label={$t('Model')}
        placeholder={$t('qwen3:8b, or gpt-5.4-mini')}
        bind:value={draft.model}
        error={fieldErrors.model || ''}
        on:input={touch}
        on:change={commit}
        autocomplete="off"
        spellcheck="false"
      />
      <div class="flex items-end gap-2">
        <!-- The runtime never sends the saved key back. The field is for typing a
             new one; dots say one is saved, and nothing typed leaves it as it is. -->
        <TextField
          class="min-w-0 flex-1"
          label={$t('API key')}
          type="password"
          bind:value={draft.api_key}
          placeholder={draft.api_key_set ? '••••••••••' : ''}
          hint={draft.api_key_set && !draft.api_key ? $t('A key is saved. Type a new one to replace it.') : ''}
          error={fieldErrors.api_key || ''}
          on:input={touch}
          on:change={commit}
          autocomplete="off"
        />
        <Button
          variant="text"
          size="sm"
          disabled={!draft.api_key && !draft.api_key_set}
          on:click={() => dispatch('resetKey')}
        >
          {$t('Clear')}
        </Button>
      </div>
      <div>
        <Select
          label={$t('What it does')}
          value={draft.mode}
          options={modeOptions}
          on:change={(e) => dispatch('mode', e.detail.value)}
        />
        {#if mode}
          <p class="mt-1.5 text-xs text-ink-faint">{$t(mode.description)}</p>
        {/if}
      </div>
      <Select
        label={$t('Reasoning effort')}
        value={draft.reasoning_effort || ''}
        options={effortOptions}
        on:change={(e) => dispatch('effort', e.detail.value)}
      />
      <TextField
        label={$t('Max tokens')}
        type="number"
        min="0"
        max={limits.max_tokens_max}
        step="64"
        placeholder={$t('Provider default')}
        value={draft.max_tokens ? String(draft.max_tokens) : ''}
        on:input={(e) => { draft.max_tokens = e.detail.target.value; touch(); }}
        on:change={commit}
      />
      <TextField
        label={$t('Timeout')}
        type="number"
        min={limits.timeout_min}
        max={limits.timeout_max}
        hint={$t('seconds')}
        value={String(draft.timeout_s ?? '')}
        on:input={(e) => { draft.timeout_s = e.detail.target.value; touch(); }}
        on:change={commit}
      />
    </div>

    <div class="mt-4">
      <TextArea
        label={$t('Own wording')}
        placeholder={$t("Leave empty to use the mode's own wording.")}
        rows={4}
        bind:value={draft.custom_prompt}
        on:input={touch}
        on:change={commit}
      />
      <p class="mt-1.5 text-xs text-ink-faint">
        {$t('Your own instruction replaces the mode above. Numbers are still written as digits, and the language is still kept. Those two rules belong to the app, not to the mode.')}
      </p>
    </div>

    {#if privacy}
      <div class="mt-4" data-testid="privacy">
        <Notice tone={privacy === 'remote' ? 'warning' : 'info'}>
          {privacy === 'local'
            ? $t('Runs on this machine. No API key is needed and the text does not leave.')
            : $t('Runs on a remote server: the dictated text is sent there, along with the key.')}
        </Notice>
      </div>
    {/if}

    <div class="mt-4 flex flex-wrap items-center gap-3">
      <Button variant="secondary" size="sm" disabled={testing || !draft.model.trim()} on:click={() => dispatch('test')}>
        {$t('Test connection')}
      </Button>
      {#if testing}
        <Spinner size="sm" label={$t('Testing the connection')} />
      {:else if testResult}
        <span
          class="text-xs {testResult.ok ? 'text-success-text' : 'text-danger-text'}"
          role="status"
          data-testid="test-result"
        >
          {testResult.ok
            ? $t('The model answered in {seconds} s.', { seconds: formatNumber(testResult.elapsed_ms / 1000, 1) })
            : testResult.message}
        </span>
      {/if}
    </div>
  {:else if off}
    <p class="mt-4 text-sm text-ink-soft">
      {$t('No presets left. Post-processing goes back to its own settings, which use a local model on this computer.')}
    </p>
  {/if}
</Card>
