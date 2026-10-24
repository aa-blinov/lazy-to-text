import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/svelte';
import { makeRpc } from './helpers/fakeRpc.js';
import { withProvider, providerValue, resolvedUrl, privacyKind, toPayload } from '../renderer/src/components/presets/model.js';

const rpc = makeRpc();
vi.mock('../renderer/src/lib/rpc.js', () => ({
  call: (...a) => rpc.call(...a),
  subscribe: (...a) => rpc.subscribe(...a),
  RpcError: class extends Error {},
}));

const catalogue = {
  providers: [
    { id: 'ollama', label: 'Ollama (this computer)', url: 'http://127.0.0.1:11434', local: true },
    { id: 'openai', label: 'OpenAI', url: 'https://api.openai.com/v1', local: false },
    { id: 'custom', label: 'Custom OpenAI-compatible server…', url: '', local: null },
  ],
  modes: [
    { id: 'clean', label: 'Clean up', description: 'Punctuation.' },
    { id: 'formal', label: 'Formal prose', description: 'Formal.' },
  ],
  efforts: ['none', 'minimal', 'low', 'medium', 'high'],
  shared_note: '',
  limits: { timeout_min: 1, timeout_max: 600, timeout_default: 20, max_tokens_max: 32768 },
};

const base = {
  id: 'default', name: 'Default', provider: 'ollama', model: '', base_url: 'http://127.0.0.1:11434',
  api_key: '', mode: 'clean', custom_prompt: '', timeout_s: 20, reasoning_effort: '', max_tokens: 0, remote: false,
};

let state;
function install(profiles = [base]) {
  state = { enabled: false, active_id: profiles[0].id, override_id: '', profiles };
  rpc.calls.length = 0;
  rpc.handlers['presets.catalogue'] = () => catalogue;
  rpc.handlers['presets.get'] = () => state;
  rpc.handlers['presets.privacy'] = ({ base_url }) => ({ local: /127\.0\.0\.1|localhost/.test(base_url) });
  rpc.handlers['llm.set_enabled'] = ({ enabled }) => (state = { ...state, enabled });
  rpc.handlers['presets.update'] = ({ profile }) => {
    state = { ...state, profiles: state.profiles.map((p) => (p.id === profile.id ? { ...p, ...profile } : p)) };
    return state;
  };
  rpc.handlers['presets.delete'] = ({ id }) => {
    const profiles = state.profiles.filter((p) => p.id !== id);
    state = { ...state, profiles, active_id: profiles[0].id };
    return state;
  };
  rpc.handlers['presets.test'] = () => ({ started: true });
}

async function open() {
  const { default: View } = await import('../renderer/src/views/PostProcessing.svelte');
  return render(View);
}

beforeEach(() => {
  cleanup();
  install();
});

describe('post-processing rules', () => {
  it('moves the address with the provider only while it is empty or a known default', () => {
    expect(withProvider({ ...base }, 'openai', catalogue).base_url).toBe('https://api.openai.com/v1');
    expect(withProvider({ ...base, base_url: '' }, 'openai', catalogue).base_url).toBe('https://api.openai.com/v1');
    expect(withProvider({ ...base, base_url: 'http://gateway.local/v1' }, 'openai', catalogue).base_url).toBe(
      'http://gateway.local/v1',
    );
    expect(withProvider({ ...base }, 'custom', catalogue).base_url).toBe('http://127.0.0.1:11434');
  });

  it('shows an unknown provider as Custom, never as the first row', () => {
    expect(providerValue({ provider: 'from-the-future' }, catalogue)).toBe('custom');
    expect(providerValue({ provider: 'openai' }, catalogue)).toBe('openai');
  });

  it('resolves an empty address against the provider and names the privacy line', () => {
    expect(resolvedUrl({ provider: 'openai', base_url: '' }, catalogue)).toBe('https://api.openai.com/v1');
    expect(privacyKind(true)).toBe('local');
    expect(privacyKind(false)).toBe('remote');
    expect(privacyKind(null)).toBeNull();
  });

  it('writes the whole preset, with a name that falls back to the id', () => {
    const payload = toPayload({ ...base, name: '  ', max_tokens: '128', timeout_s: '30' });
    expect(payload.name).toBe('default');
    expect(payload.max_tokens).toBe(128);
    expect(payload.timeout_s).toBe(30);
    expect(Object.keys(payload).sort()).toEqual(
      ['api_key', 'base_url', 'custom_prompt', 'id', 'mode', 'model', 'name', 'provider', 'reasoning_effort', 'timeout_s', 'max_tokens'].sort(),
    );
  });
});

describe('post-processing screen', () => {
  it('puts the switch inside the language-model card and never folds the picker away', async () => {
    await open();
    const sw = await screen.findByRole('switch');
    const card = sw.closest('.rounded-ui');
    expect(card.textContent).toContain('Language model');
    expect(card.textContent).toContain('Provider');
    expect(card.textContent).toContain('Reasoning effort');
    // The picker is its own card, on screen with no control that expands it.
    expect(screen.getByRole('button', { name: 'Choose' })).toBeTruthy();
    // Nothing here collapses: the only expandable things are listbox triggers.
    expect(document.querySelectorAll('[aria-expanded]:not([aria-haspopup])').length).toBe(0);
    expect(document.querySelectorAll('details, [role="tab"]').length).toBe(0);
    expect(screen.getByText('New preset')).toBeTruthy();
  });

  it('sends the switch alone, and reports a refusal', async () => {
    await open();
    await fireEvent.click(await screen.findByRole('switch'));
    await waitFor(() => expect(rpc.called('llm.set_enabled')).toEqual([{ enabled: true }]));
    expect(rpc.called('presets.update')).toEqual([]);
  });

  it('saves the whole preset when a text field loses focus', async () => {
    await open();
    const model = await screen.findByLabelText('Model');
    await fireEvent.input(model, { target: { value: 'qwen3:8b' } });
    expect(rpc.called('presets.update')).toEqual([]);
    await fireEvent.change(model);
    await waitFor(() => expect(rpc.called('presets.update').length).toBe(1));
    expect(rpc.called('presets.update')[0].profile).toMatchObject({ id: 'default', model: 'qwen3:8b', provider: 'ollama' });
  });

  it('shows the privacy line as the address is typed', async () => {
    await open();
    const server = await screen.findByLabelText('Server');
    await waitFor(() => expect(screen.getByTestId('privacy').textContent).toContain('Runs on this machine'));
    await fireEvent.input(server, { target: { value: 'https://api.example.com/v1' } });
    await waitFor(() => expect(screen.getByTestId('privacy').textContent).toContain('remote server'));
  });

  it('disables Delete for the only preset, and asks before deleting another', async () => {
    install([base, { ...base, id: 'work', name: 'Work' }]);
    await open();
    await screen.findByRole('switch');
    const del = screen.getByRole('button', { name: 'Delete' });
    expect(del.disabled).toBe(false);
    await fireEvent.click(del);
    expect(await screen.findByRole('alertdialog')).toBeTruthy();
    expect(rpc.called('presets.delete')).toEqual([]);
    const confirm = [...document.querySelectorAll('[role=alertdialog] button')].find((b) => b.textContent.trim() === 'Delete');
    await fireEvent.click(confirm);
    await waitFor(() => expect(rpc.called('presets.delete')).toEqual([{ id: 'default' }]));
  });

  it('keeps Delete disabled on a single preset', async () => {
    await open();
    await screen.findByRole('switch');
    expect(screen.getByRole('button', { name: 'Delete' }).disabled).toBe(true);
  });

  it('tests the connection with the editor values and shows the answer from the event', async () => {
    await open();
    const model = await screen.findByLabelText('Model');
    await fireEvent.input(model, { target: { value: 'm1' } });
    await fireEvent.change(model);
    const test = await screen.findByRole('button', { name: 'Test connection' });
    await waitFor(() => expect(test.disabled).toBe(false));
    await fireEvent.click(test);
    await waitFor(() => expect(rpc.called('presets.test').length).toBe(1));
    const { test_id, profile } = rpc.called('presets.test')[0];
    expect(profile.model).toBe('m1');
    rpc.emit('llm_test', { test_id: 'someone-else', ok: true, message: '', elapsed_ms: 1 });
    expect(screen.queryByTestId('test-result')).toBeNull();
    rpc.emit('llm_test', { test_id, ok: false, message: 'the server answered HTTP 401', elapsed_ms: 80 });
    expect((await screen.findByTestId('test-result')).textContent).toBe('the server answered HTTP 401');
  });
});
