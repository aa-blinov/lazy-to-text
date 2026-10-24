<script>
  // Post-processing: the language-model settings (with the switch inside the
  // card), and the preset picker, which is always on screen. Edits commit on
  // focus-out for text and at once for pickers, as the Qt screen does, and a
  // field that is still being typed is flushed when the screen is left.
  import { onMount, onDestroy } from 'svelte';
  import { PageHeader, Skeleton, Notice, AlertDialog, toast } from '@monos/ui';
  import { t } from '../lib/i18n.js';
  import { call, subscribe } from '../lib/rpc.js';
  import LanguageModelCard from '../components/presets/LanguageModelCard.svelte';
  import PresetPicker from '../components/presets/PresetPicker.svelte';
  import { withProvider, toPayload, resolvedUrl, sameDraft } from '../components/presets/model.js';

  let catalogue = null;
  let state = null;
  let currentId = '';
  let draft = null;
  let loadError = '';
  let local = null;
  let testing = false;
  let testResult = null;
  let testId = '';
  let confirmDelete = false;
  let dirty = false;
  let privacyTimer = null;
  let unsubscribe = [];

  $: current = state?.profiles.find((p) => p.id === currentId) ?? null;

  function say(error) {
    toast({ title: $t('Could not save the preset'), description: error?.message || String(error), tone: 'danger', duration: 0 });
  }

  function open(id) {
    const profile = state?.profiles.find((p) => p.id === id);
    currentId = profile ? id : '';
    draft = profile ? { ...profile } : null;
    dirty = false;
    testResult = null;
    refreshPrivacy();
  }

  function adopt(next, openId) {
    state = next;
    const wanted = openId ?? currentId;
    const exists = next.profiles.some((p) => p.id === wanted);
    if (!exists) open(next.active_id);
    else if (wanted !== currentId) open(wanted);
    else if (!dirty) open(wanted);
  }

  async function run(method, params, openId) {
    try {
      adopt(await call(method, params), openId);
      return true;
    } catch (error) {
      say(error);
      return false;
    }
  }

  async function load() {
    try {
      [catalogue, state] = await Promise.all([call('presets.catalogue'), call('presets.get')]);
      open(state.profiles.some((p) => p.id === state.active_id) ? state.active_id : state.profiles[0]?.id);
    } catch (error) {
      loadError = error.message;
    }
  }

  // ---- editor ---------------------------------------------------------

  async function commit() {
    if (!draft || !dirty) return;
    const payload = toPayload(draft);
    if (!(await run('presets.update', { profile: payload }))) return;
    // The runtime clamps and trims; show what it kept, unless the user has
    // already moved on to another field while the write was in flight.
    if (draft && sameDraft(draft, payload)) {
      const stored = state.profiles.find((p) => p.id === payload.id);
      if (stored) {
        draft = { ...stored };
      }
      dirty = false;
    }
  }

  const touch = () => { dirty = true; };

  function pick(field, value) {
    draft = { ...draft, [field]: value };
    dirty = true;
    commit();
  }

  function changeProvider(providerId) {
    draft = withProvider(draft, providerId, catalogue);
    dirty = true;
    refreshPrivacy();
    commit();
  }

  function refreshPrivacy() {
    clearTimeout(privacyTimer);
    if (!draft || !catalogue) { local = null; return; }
    privacyTimer = setTimeout(async () => {
      try {
        local = (await call('presets.privacy', { base_url: draft?.base_url ?? '', provider: draft?.provider })).local;
      } catch {
        local = null;
      }
    }, 120);
  }

  async function toggle(enabled) {
    const ok = await run('llm.set_enabled', { enabled });
    if (!ok) state = { ...state };
  }

  // ---- picker ---------------------------------------------------------

  async function select(id) {
    await flush();
    open(id);
  }

  async function flush() {
    if (dirty) await commit();
  }

  async function create() {
    await flush();
    try {
      const next = await call('presets.create');
      adopt(next, next.created_id);
    } catch (error) { say(error); }
  }

  async function duplicate() {
    await flush();
    try {
      const next = await call('presets.duplicate', { id: currentId });
      adopt(next, currentId);
      toast({ title: $t('Preset duplicated'), tone: 'success' });
    } catch (error) { say(error); }
  }

  async function remove() {
    confirmDelete = false;
    await run('presets.delete', { id: currentId }, '');
  }

  async function activate() {
    await flush();
    await run('presets.activate', { id: currentId });
  }

  async function resetKey() {
    await run('presets.reset_key', { id: currentId });
    if (draft) draft = { ...draft, api_key: '' };
  }

  // ---- connection test ------------------------------------------------

  async function test() {
    await flush();
    testId = String(Date.now());
    testing = true;
    testResult = null;
    try {
      await call('presets.test', { profile: toPayload(draft), test_id: testId });
    } catch (error) {
      testing = false;
      testResult = { ok: false, message: error.message };
    }
  }

  onMount(() => {
    load();
    unsubscribe = [
      subscribe('llm_test', (d) => {
        if (d.test_id !== testId) return;
        testing = false;
        testResult = d;
      }),
      // Another screen or the other interface changed the list.
      subscribe('presets', async () => {
        try { adopt(await call('presets.get')); } catch { /* the next action reports it */ }
      }),
    ];
  });

  onDestroy(() => {
    clearTimeout(privacyTimer);
    unsubscribe.forEach((off) => off());
    if (dirty) commit();
  });
</script>

<div class="mx-auto max-w-4xl p-6">
  <PageHeader title={$t('Post-processing')} description={$t('Rewrite dictated text before it is pasted.')} />

  {#if loadError}
    <div class="mt-6"><Notice tone="danger">{loadError}</Notice></div>
  {:else if !state || !catalogue}
    <div class="mt-6 flex flex-col gap-4">
      <Skeleton height="9rem" />
      <Skeleton height="22rem" />
    </div>
  {:else}
    <div class="mt-6 flex flex-col gap-4">
      <PresetPicker
        profiles={state.profiles}
        {currentId}
        activeId={state.active_id}
        on:select={(e) => select(e.detail)}
        on:activate={activate}
        on:create={create}
        on:duplicate={duplicate}
        on:delete={() => (confirmDelete = true)}
      />
      <LanguageModelCard
        enabled={state.enabled}
        bind:draft
        {catalogue}
        {local}
        {testing}
        {testResult}
        on:toggle={(e) => toggle(e.detail)}
        on:touch={touch}
        on:commit={commit}
        on:address={refreshPrivacy}
        on:provider={(e) => changeProvider(e.detail)}
        on:mode={(e) => pick('mode', e.detail)}
        on:effort={(e) => pick('reasoning_effort', e.detail)}
        on:resetKey={resetKey}
        on:test={test}
      />
    </div>
  {/if}
</div>

<AlertDialog
  bind:open={confirmDelete}
  title={$t('Delete this preset?')}
  description={current ? $t('The preset "{name}" and its key will be removed.', { name: current.name }) : ''}
  confirmLabel={$t('Delete')}
  cancelLabel={$t('Cancel')}
  on:confirm={remove}
/>
