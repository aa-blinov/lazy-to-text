<script>
  // Per-model knobs, shown inside the active card. Whisper cards have a
  // language, a VAD flag, beam size, temperature and a prompt; Parakeet cards
  // have one timestamps flag; the rest have none (the card does not render
  // this component for them).
  import { createEventDispatcher } from 'svelte';
  import { Select, Checkbox, TextField, TextArea } from '@monos/ui';
  import { t } from '../../lib/i18n.js';
  import { fmt } from './store.js';

  export let model;
  export let languages = [];
  export let disabled = false;

  const dispatch = createEventDispatcher();

  $: kind = model.inference?.kind;
  $: saved = model.inference?.values ?? {};

  // Local edit copies; they follow the saved values when those change from
  // outside (another window, a normalised value coming back), and are not
  // written back until the user changes something.
  let language = 'auto';
  let vad = true;
  let beam = '5';
  let temperature = '0';
  let prompt = '';
  let timestamps = false;

  $: syncFrom(saved);
  function syncFrom(values) {
    language = values.language ?? 'auto';
    vad = values.vad_filter ?? true;
    beam = String(values.beam_size ?? 5);
    temperature = String(values.temperature ?? 0);
    prompt = values.initial_prompt ?? '';
    timestamps = Boolean(values.timestamps);
  }

  $: languageOptions = languages.map((l) => ({
    value: l.code ?? 'auto',
    label: $t(l.label),
  }));

  $: defaultLanguage = model.auto_language
    ? $t(languages.find((l) => l.code === model.auto_language)?.label ?? model.auto_language)
    : '';

  // A stored code the list does not offer shows as Auto-detect, as in Qt.
  $: languageValue = languageOptions.some((o) => o.value === language) ? language : 'auto';

  function emit(values) {
    dispatch('change', values);
  }

  function commitNumber(key, raw, min, max, fallback) {
    const n = Number(raw);
    const value = Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
    emit({ [key]: value });
  }
</script>

<section
  class="mt-4 border-t border-line pt-4"
  aria-label={$t('Inference settings')}
  data-testid="inference-settings"
>
  <h4 class="text-whisper-lg font-bold uppercase tracking-widest text-ink-soft">
    {$t('Inference settings')}
  </h4>

  {#if kind === 'whisper'}
    <div class="mt-3 grid gap-x-6 gap-y-3 sm:grid-cols-2">
      <Select
        label={$t('Language')}
        options={languageOptions}
        value={languageValue}
        {disabled}
        on:change={(e) => emit({ language: e.detail.value === 'auto' ? null : e.detail.value })}
      />
      <div class="flex items-end pb-1">
        <Checkbox
          checked={vad}
          {disabled}
          on:change={(e) => emit({ vad_filter: e.target.checked })}
        >
          {$t('VAD filter (skip silence)')}
        </Checkbox>
      </div>
      <TextField
        label={$t('Beam size')}
        type="number"
        bind:value={beam}
        {disabled}
        on:change={() => commitNumber('beam_size', beam, 1, 20, 5)}
      />
      <TextField
        label={$t('Temperature')}
        type="number"
        bind:value={temperature}
        {disabled}
        on:change={() => commitNumber('temperature', temperature, 0, 1, 0)}
      />
      <div class="sm:col-span-2">
        <TextArea
          label={$t('Initial prompt')}
          rows={3}
          placeholder={$t('Names, terms and context Whisper should recognise, for example "Anthropic, Claude, ctranslate2. Speakers: Алексей."')}
          bind:value={prompt}
          {disabled}
          on:change={() => emit({ initial_prompt: prompt.trim() === '' ? null : prompt })}
        />
      </div>
    </div>
    {#if defaultLanguage && languageValue === 'auto'}
      <p class="mt-3 text-xs text-ink-faint">
        {fmt($t('Auto-detect uses %1 for this model; pick a language to override it.'), defaultLanguage)}
      </p>
    {/if}
    <p class="mt-3 text-xs text-ink-faint">
      {$t('Saved for this model. The engine applies the language today; the other fields are stored for when it can use them.')}
    </p>
  {:else if kind === 'parakeet'}
    <div class="mt-3">
      <Checkbox
        checked={timestamps}
        {disabled}
        on:change={(e) => emit({ timestamps: e.target.checked })}
      >
        {$t('Include word + segment timestamps in output')}
      </Checkbox>
      <p class="mt-2 text-xs text-ink-faint">
        {$t('NeMo detects the language by itself and decodes greedily. There are no language, beam or temperature settings. Turn on timestamps if you need word offsets in the result.')}
      </p>
    </div>
  {/if}
</section>
