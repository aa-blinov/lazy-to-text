import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { toasts, clearToasts } from '@monos/ui';
import { makeRpc } from './helpers/fakeRpc.js';

const rpc = makeRpc();
vi.mock('../renderer/src/lib/rpc.js', () => ({
  call: (...a) => rpc.call(...a),
  subscribe: (...a) => rpc.subscribe(...a),
}));

const hotkey = await import('../renderer/src/lib/hotkey.js');
const theme = await import('../renderer/src/lib/theme.js');
const { language } = await import('../renderer/src/lib/i18n.js');
const { permissions, micTest, settings, remembered } = await import('../renderer/src/lib/settings.js');
const Settings = (await import('../renderer/src/views/Settings.svelte')).default;
const HotkeyCapture = (await import('../renderer/src/components/settings/HotkeyCapture.svelte')).default;

const key = (code, extra = {}) => ({ code, key: extra.key ?? code, ...extra });

describe('hotkey capture rules', () => {
  const linux = { platform: 'linux' };

  it('writes a combination from the physical key, modifiers first', () => {
    expect(hotkey.interpretKeydown(key('KeyA', { ctrlKey: true, shiftKey: true }), linux))
      .toEqual({ kind: 'combo', text: 'ctrl+shift+a' });
    expect(hotkey.interpretKeydown(key('F8', { ctrlKey: true }), linux)).toEqual({ kind: 'combo', text: 'ctrl+f8' });
    expect(hotkey.interpretKeydown(key('Digit5', { altKey: true, key: '%' }), linux)).toEqual({ kind: 'combo', text: 'alt+5' });
    expect(hotkey.interpretKeydown(key('PageUp', { metaKey: true }), linux)).toEqual({ kind: 'combo', text: 'cmd+page_up' });
  });

  it('shows a held modifier and waits for the key', () => {
    expect(hotkey.interpretKeydown(key('ControlLeft', { ctrlKey: true }), linux))
      .toEqual({ kind: 'modifiers', mods: ['ctrl'] });
  });

  it('gives up on Escape, lets Tab leave, and clears only where empty is allowed', () => {
    expect(hotkey.interpretKeydown(key('Escape'), linux)).toEqual({ kind: 'cancel' });
    expect(hotkey.interpretKeydown(key('Tab'), linux)).toEqual({ kind: 'leave' });
    expect(hotkey.interpretKeydown(key('Backspace'), linux).kind).toBe('combo');
    expect(hotkey.interpretKeydown(key('Backspace'), { ...linux, allowEmpty: true })).toEqual({ kind: 'clear' });
    expect(hotkey.interpretKeydown(key('Escape', { ctrlKey: true }), linux)).toEqual({ kind: 'combo', text: 'ctrl+esc' });
  });

  it('ignores key repeat', () => {
    expect(hotkey.interpretKeydown(key('KeyA', { repeat: true }), linux)).toEqual({ kind: 'ignore' });
  });

  it('takes a right-hand modifier released alone, only where push-to-talk allows it', () => {
    const solo = { platform: 'darwin', allowSolo: true };
    expect(hotkey.interpretKeyup(key('MetaRight'), solo)).toBe('right_cmd');
    expect(hotkey.interpretKeyup(key('AltRight'), { ...solo, platform: 'win32' })).toBe('right_alt');
    expect(hotkey.interpretKeyup(key('MetaRight'), { platform: 'darwin' })).toBeNull();
    expect(hotkey.interpretKeyup(key('MetaRight'), { ...solo, sawOtherKey: true })).toBeNull();
  });

  it('passes a left-hand lone modifier on so the runtime can explain the refusal', () => {
    expect(hotkey.interpretKeyup(key('ControlLeft'), { platform: 'linux', allowSolo: true })).toBe('ctrl');
  });

  it('does not offer Fn on Windows, where no keyboard reports it', () => {
    expect(hotkey.interpretKeydown({ code: '', key: 'Fn' }, { platform: 'win32', allowSolo: true }).kind).toBe('ignore');
    expect(hotkey.interpretKeydown({ code: '', key: 'Fn' }, { platform: 'darwin', allowSolo: true })).toEqual({ kind: 'solo', text: 'fn' });
  });

  it('writes a binding as key caps in the platform words', () => {
    expect(hotkey.bindingParts('ctrl+f8', 'linux')).toEqual(['Ctrl', 'F8']);
    expect(hotkey.bindingParts('alt+cmd+a', 'darwin')).toEqual(['Option', 'Cmd', 'A']);
    expect(hotkey.bindingParts('right_alt', 'win32')).toEqual(['Right Alt']);
    expect(hotkey.bindingParts('', 'linux')).toEqual([]);
  });

  it('fills numbered placeholders', () => {
    expect(hotkey.fmt('%1 is not %2', 'a', 'b')).toBe('a is not b');
  });
});

describe('theme helpers', () => {
  afterEach(() => {
    document.documentElement.removeAttribute('data-theme');
    document.documentElement.style.fontSize = '';
  });

  it('applies the chosen palette and falls back to the default one', () => {
    theme.applyTheme('dark', theme.normalisePalette('nord'));
    expect(document.documentElement.dataset.theme).toBe('nord');
    expect(document.documentElement.dataset.mode).toBe('dark');
    expect(theme.normalisePalette('nope')).toBe('gruvbox');
    expect(theme.normalisePalette(undefined)).toBe('gruvbox');
  });

  it('scales the text within the same bounds as the Qt interface', () => {
    expect(theme.applyTextScale(1.3)).toBe(1.3);
    expect(document.documentElement.style.fontSize).toBe('130%');
    expect(theme.applyTextScale(9)).toBe(1.75);
    expect(theme.applyTextScale(0.1)).toBe(0.85);
    expect(theme.applyTextScale('junk')).toBe(1);
    expect(document.documentElement.style.fontSize).toBe('');
  });
});

describe('HotkeyCapture', () => {
  it('proposes the combination that was pressed', async () => {
    const changes = [];
    const { component } = render(HotkeyCapture, { props: { value: 'ctrl+f8', label: 'Start recording', platform: 'linux' } });
    component.$on('change', (e) => changes.push(e.detail));
    const field = screen.getByRole('button', { name: /^Start recording:/ });

    await fireEvent.click(field);
    await fireEvent.keyDown(field, key('KeyK', { ctrlKey: true, shiftKey: true }));

    expect(changes).toEqual(['ctrl+shift+k']);
  });

  it('leaves the value alone when capture is cancelled', async () => {
    const changes = [];
    const { component } = render(HotkeyCapture, { props: { value: 'ctrl+f8', label: 'Start recording', platform: 'linux' } });
    component.$on('change', (e) => changes.push(e.detail));
    const field = screen.getByRole('button', { name: /^Start recording:/ });

    await fireEvent.click(field);
    await fireEvent.keyDown(field, key('Escape'));

    expect(changes).toEqual([]);
  });

  it('captures a right-hand modifier on release in push-to-talk', async () => {
    const changes = [];
    const { component } = render(HotkeyCapture, { props: { value: '', label: 'Push-to-talk key', platform: 'darwin', allowSolo: true } });
    component.$on('change', (e) => changes.push(e.detail));
    const field = screen.getByRole('button', { name: /^Push-to-talk key:/ });

    await fireEvent.click(field);
    await fireEvent.keyDown(field, key('MetaRight', { metaKey: true }));
    await fireEvent.keyUp(field, key('MetaRight'));

    expect(changes).toEqual(['right_cmd']);
  });

  it('clears an optional binding with Backspace', async () => {
    const changes = [];
    const { component } = render(HotkeyCapture, { props: { value: 'ctrl+f10', label: 'Cancel recording', allowEmpty: true } });
    component.$on('change', (e) => changes.push(e.detail));
    const field = screen.getByRole('button', { name: /^Cancel recording:/ });

    await fireEvent.click(field);
    await fireEvent.keyDown(field, key('Backspace'));

    expect(changes).toEqual(['']);
  });

  it('says why a binding is refused, and keeps that reason reachable', () => {
    render(HotkeyCapture, { props: { value: 'a', label: 'Start recording', error: 'Add a modifier.' } });

    const field = screen.getByRole('button', { name: /^Start recording:/ });
    expect(screen.getByRole('alert').textContent).toBe('Add a modifier.');
    expect(field.getAttribute('aria-invalid')).toBe('true');
    expect(field.getAttribute('aria-describedby')).toBe(screen.getByRole('alert').id);
  });

  it('takes typed text for keys a browser cannot see', async () => {
    const changes = [];
    const { component } = render(HotkeyCapture, { props: { value: 'right_cmd', label: 'Push-to-talk key' } });
    component.$on('change', (e) => changes.push(e.detail));

    await fireEvent.click(screen.getByRole('button', { name: /^Type it instead/ }));
    const input = screen.getByLabelText('Push-to-talk key');
    await fireEvent.input(input, { target: { value: 'fn' } });
    await fireEvent.keyDown(input, { key: 'Enter' });

    expect(changes).toEqual(['fn']);
  });
});

// ---- the screen ---------------------------------------------------------------

function settingsPayload(over = {}) {
  const base = {
    platform: 'darwin',
    version: '9.9.9',
    hotkey: { mode: 'two_keys', start: 'ctrl+f8', stop: 'ctrl+f9', cancel: 'ctrl+f10', push_to_talk_key: 'right_cmd', push_to_talk_min_hold_seconds: 0.2 },
    hotkey_errors: {},
    defaults: { mode: 'two_keys', start: 'ctrl+f8', stop: 'ctrl+f9', cancel: 'ctrl+f10', push_to_talk_key: 'right_cmd' },
    audio: { device: null, mute_output_on_record: false, vad_enabled: false, max_duration: 300 },
    clipboard: { auto_paste: true },
    audio_feedback: { enabled: true },
    ui: { theme: 'system', palette: 'gruvbox', language: 'en', text_scale: 1.0, start_at_login: false },
    capabilities: { mute_output: true, recording_stack: true },
    choices: {
      text_scales: [1.0, 1.15, 1.3, 1.5, 1.75],
      palettes: ['gruvbox', 'github', 'dracula', 'nord', 'solarized', 'catppuccin'],
      languages: [{ code: 'en', name: 'English' }, { code: 'ru', name: 'Русский' }],
      themes: ['system', 'light', 'dark'], modes: ['two_keys', 'toggle', 'push_to_talk'],
      ptt_solo_keys: [], max_duration_cap: 3600, min_hold_range: [0, 2],
    },
  };
  return { ...base, ...over };
}

let stored;
let soundState;
beforeEach(() => {
  rpc.calls.length = 0;
  for (const k of Object.keys(rpc.handlers)) delete rpc.handlers[k];
  clearToasts();
  language.set('en');
  remembered.stop = null;
  remembered.cancel = null;
  permissions.set(null);
  micTest.set({ phase: 'idle', level: 0 });
  settings.set(null);
  stored = settingsPayload();
  rpc.handlers['settings.get'] = () => stored;
  rpc.handlers['devices.list'] = () => ({ devices: [{ index: 0, name: 'Built-in' }, { index: 3, name: 'USB mic' }], current: null });
  rpc.handlers['permissions.refresh'] = () => ({ banners: { accessibility: 'hidden', microphone: 'hidden', post_event: 'hidden' } });
  rpc.handlers['app.snapshot'] = () => ({ config: {} });
  rpc.handlers['settings.set'] = ({ key: k, value }) => ({ key: k, value, live_error: null });
  rpc.handlers['settings.set_hotkeys'] = (p) => ({ live: true, live_error: null, errors: {}, settings: stored });
  rpc.handlers['settings.reset_hotkeys'] = () => ({ live: true, live_error: null, settings: stored });
  rpc.handlers['devices.select'] = ({ device }) => ({ device });
  rpc.handlers['devices.test'] = () => ({ started: true, seconds: 3 });
  rpc.handlers['permissions.request'] = () => ({ action: 'prompt' });
  soundState = {
    presets: [
      { id: 'warm-rise', label: 'Warm rise', value: 'assets/sounds/record_start.wav' },
      { id: 'warm-fall', label: 'Warm fall', value: 'assets/sounds/record_stop.wav' },
      { id: 'wood', label: 'Wood', value: 'assets/sounds/presets/wood.wav' },
    ],
    custom: [],
    start: 'assets/sounds/record_start.wav',
    stop: 'assets/sounds/record_stop.wav',
  };
  rpc.handlers['sounds.list'] = () => soundState;
  rpc.handlers['sounds.set'] = ({ slot, value }) => ({ slot, value, save_error: null });
  rpc.handlers['sounds.preview'] = () => ({ played: true, seconds: 0.4 });
});

async function open() {
  render(Settings);
  await screen.findByText('Audio input', { selector: 'h2' });
}

describe('sound pickers', () => {
  afterEach(() => { delete window.l2t; });

  it('offers a start and an end sound, each showing the current one', async () => {
    await open();

    expect(await screen.findByRole('button', { name: /Start sound/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /End sound/ })).toBeTruthy();
    expect(screen.getAllByText('Warm rise').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Warm fall').length).toBeGreaterThan(0);
  });

  it('saves a chosen sound for that cue and plays it so the choice is heard', async () => {
    await open();

    await fireEvent.click(await screen.findByRole('button', { name: /End sound/ }));
    await fireEvent.click(await screen.findByRole('option', { name: 'Wood' }));

    await waitFor(() => expect(rpc.called('sounds.set')).toEqual([{ slot: 'stop', value: 'assets/sounds/presets/wood.wav' }]));
    await waitFor(() => expect(rpc.called('sounds.preview')).toEqual([{ value: 'assets/sounds/presets/wood.wav' }]));
  });

  it('adds a WAV file of one\'s own, chooses it and plays it', async () => {
    window.l2t = { dialog: { openFile: vi.fn(async () => '/Users/me/my click.wav') } };
    rpc.handlers['sounds.add'] = () => {
      soundState = { ...soundState, custom: [{ value: '/cfg/sounds/my click.wav', name: 'my click' }] };
      return { value: '/cfg/sounds/my click.wav', name: 'my click', seconds: 0.3 };
    };
    await open();

    await fireEvent.click(await screen.findByRole('button', { name: /Start sound/ }));
    await fireEvent.click(await screen.findByRole('option', { name: 'Choose a file…' }));

    await waitFor(() => expect(rpc.called('sounds.add')).toEqual([{ path: '/Users/me/my click.wav' }]));
    await waitFor(() => expect(rpc.called('sounds.set')).toEqual([{ slot: 'start', value: '/cfg/sounds/my click.wav' }]));
    expect(window.l2t.dialog.openFile.mock.calls[0][0].filters[0].extensions).toEqual(['wav']);
    await waitFor(() => expect(rpc.called('sounds.preview')).toEqual([{ value: '/cfg/sounds/my click.wav' }]));
  });

  it('says why a file was refused and leaves the choice alone', async () => {
    window.l2t = { dialog: { openFile: vi.fn(async () => '/Users/me/song.mp3') } };
    rpc.handlers['sounds.add'] = () => { throw new Error('Only WAV files can be used as a sound.'); };
    await open();

    await fireEvent.click(await screen.findByRole('button', { name: /Start sound/ }));
    await fireEvent.click(await screen.findByRole('option', { name: 'Choose a file…' }));

    await waitFor(() => expect(get(toasts).some((t) => t.title === 'Could not use that file' && t.tone === 'danger')).toBe(true));
    expect(rpc.called('sounds.set')).toEqual([]);
  });
});

describe('Settings screen', () => {
  it('shows the five grouped sections with jump links and the version footer', async () => {
    await open();

    const nav = screen.getByRole('navigation', { name: 'Settings sections' });
    expect(within(nav).getAllByRole('link').map((a) => a.textContent.trim()))
      .toEqual(['Audio input', 'Hotkeys', 'Clipboard', 'Appearance', 'Startup']);
    for (const title of ['Audio input', 'Hotkeys', 'Clipboard', 'Appearance', 'Startup']) {
      expect(screen.getByRole('heading', { name: title })).toBeTruthy();
    }
    expect(screen.getByText('Lazy to Text 9.9.9')).toBeTruthy();
  });

  it('lists the microphones and switches the device at once', async () => {
    await open();

    const picker = screen.getByRole('button', { name: 'Microphone' });
    await fireEvent.click(picker);
    await fireEvent.click(await screen.findByRole('option', { name: '[3] USB mic' }));

    await waitFor(() => expect(rpc.called('devices.select')).toEqual([{ device: 3 }]));
  });

  it('saves a switch the moment it is flipped and says so', async () => {
    await open();

    await fireEvent.click(screen.getByRole('switch', { name: /Skip silence/ }));

    await waitFor(() => expect(rpc.called('settings.set')).toContainEqual({ key: 'audio.vad_enabled', value: true }));
    expect(get(toasts).some((t) => t.title === 'Saved')).toBe(true);
  });

  it('puts a switch back and says why when the write fails', async () => {
    rpc.handlers['settings.set'] = () => {
      throw Object.assign(new Error('disk full'), { code: 'internal' });
    };
    await open();

    const vad = screen.getByRole('switch', { name: /Skip silence/ });
    await fireEvent.click(vad);

    await waitFor(() => expect(get(toasts).some((t) => t.title === 'Could not save' && t.description === 'disk full')).toBe(true));
    await waitFor(() => expect(vad.getAttribute('aria-checked')).toBe('false'));
  });

  it('warns when a value was saved but could not be applied to the running app', async () => {
    rpc.handlers['settings.set'] = ({ key: k, value }) => ({ key: k, value, live_error: 'clipboard gone' });
    await open();

    await fireEvent.click(screen.getByRole('switch', { name: /Auto-paste/ }));

    await waitFor(() => expect(get(toasts).some((t) => t.tone === 'warning' && t.description === 'clipboard gone')).toBe(true));
  });

  it('hides the mute control where the platform cannot mute', async () => {
    stored = settingsPayload({ capabilities: { mute_output: false, recording_stack: true } });
    await open();

    expect(screen.queryByRole('switch', { name: /Mute other sounds/ })).toBeNull();
  });

  it('saves a capture at once and shows the reason when the runtime refuses it', async () => {
    rpc.handlers['settings.set_hotkeys'] = () => ({
      live: true, live_error: null, settings: stored,
      errors: { start: { template: '%1 is not a recognised key', args: ["'blah'"], message: "'blah' is not a recognised key" } },
    });
    await open();

    const field = screen.getByRole('button', { name: /^Start recording:/ });
    await fireEvent.click(field);
    await fireEvent.keyDown(field, key('KeyA', { ctrlKey: true }));

    await waitFor(() => expect(rpc.called('settings.set_hotkeys')[0]).toMatchObject({ mode: 'two_keys', start: 'ctrl+a', stop: 'ctrl+f9' }));
    expect((await screen.findByRole('alert')).textContent).toContain("'blah' is not a recognised key");
  });

  it('switches to push-to-talk, shows its key and hides Start and Stop', async () => {
    await open();

    await fireEvent.click(screen.getByRole('radio', { name: /Push to talk/ }));

    await waitFor(() => expect(rpc.called('settings.set_hotkeys')[0].mode).toBe('push_to_talk'));
    expect(screen.getByRole('button', { name: /^Push-to-talk key:/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^Start recording:/ })).toBeNull();
    expect(screen.getByRole('slider')).toBeTruthy();
  });

  it('mirrors Start into Stop in toggle mode and restores Stop on the way back', async () => {
    await open();

    await fireEvent.click(screen.getByRole('radio', { name: /One key/ }));
    await waitFor(() => expect(rpc.called('settings.set_hotkeys')[0]).toMatchObject({ mode: 'toggle', stop: 'ctrl+f8' }));
    expect(screen.getByRole('button', { name: /^Stop recording:/ }).disabled).toBe(true);

    await fireEvent.click(screen.getByRole('radio', { name: /Two keys/ }));
    await waitFor(() => expect(rpc.called('settings.set_hotkeys')[1]).toMatchObject({ mode: 'two_keys', stop: 'ctrl+f9' }));
  });

  it('resets the hotkeys through the runtime and rereads what it stored', async () => {
    rpc.handlers['settings.reset_hotkeys'] = () => ({
      live: true, live_error: null,
      settings: settingsPayload({ hotkey: { ...stored.hotkey, start: 'ctrl+f1' } }),
    });
    await open();

    await fireEvent.click(screen.getByRole('button', { name: 'Reset hotkeys to defaults' }));

    await waitFor(() => expect(rpc.called('settings.reset_hotkeys')).toHaveLength(1));
    await waitFor(() => expect(screen.getByRole('button', { name: /^Start recording:/ }).getAttribute('aria-label')).toContain('ctrl+f1'));
  });

  it('marks a binding on disk that no longer validates', async () => {
    stored = settingsPayload({
      hotkey_errors: { start: { template: 'Empty part in %1. Remove the extra \'+\' or the trailing space', args: ["'ctrl+'"], message: '' } },
    });
    await open();

    expect((await screen.findByRole('alert')).textContent).toContain("Empty part in 'ctrl+'");
  });

  it('runs the microphone test: live level while it listens, then a verdict', async () => {
    await open();

    await fireEvent.click(screen.getByRole('button', { name: 'Test microphone' }));
    rpc.emit('mic_test', { phase: 'running', seconds: 3 });
    rpc.emit('mic_level', { level: 0.6 });

    expect(await screen.findByText('Listening… speak now (3 s)')).toBeTruthy();
    expect(screen.getByRole('meter').getAttribute('aria-valuenow')).not.toBe('0');
    expect(screen.getByRole('button', { name: 'Test microphone' }).disabled).toBe(true);

    rpc.emit('mic_test', { phase: 'done', verdict: 'quiet', peak: 0.05, rms: 0.01 });
    expect(await screen.findByText(/Very quiet/)).toBeTruthy();
    expect(screen.getByText(/peak 0.050, rms 0.010/)).toBeTruthy();
  });

  it('says why a microphone test could not start', async () => {
    rpc.handlers['devices.test'] = () => {
      throw Object.assign(new Error('wait until current operation finishes'), { code: 'busy' });
    };
    await open();

    await fireEvent.click(screen.getByRole('button', { name: 'Test microphone' }));

    expect(await screen.findByText('Test failed: wait until current operation finishes')).toBeTruthy();
  });

  it('shows no permission banner when nothing is missing, and each one that is', async () => {
    await open();
    expect(document.querySelector('[data-permission]')).toBeNull();

    permissions.set({ banners: { accessibility: 'untrusted', microphone: 'denied', post_event: 'untrusted' } });
    await waitFor(() => expect(document.querySelectorAll('[data-permission]')).toHaveLength(3));
    expect(screen.getByRole('button', { name: 'Grant accessibility access' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Open microphone settings' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Allow auto-paste access' })).toBeTruthy();
  });

  it('asks the runtime to fix a permission from the banner', async () => {
    rpc.handlers['permissions.refresh'] = () => ({ banners: { accessibility: 'untrusted', microphone: 'hidden', post_event: 'hidden' } });
    await open();

    await fireEvent.click(await screen.findByRole('button', { name: 'Grant accessibility access' }));

    await waitFor(() => expect(rpc.called('permissions.request')).toEqual([{ kind: 'accessibility' }]));
  });

  it('clears a banner when a grant arrives, without a restart', async () => {
    rpc.handlers['permissions.refresh'] = () => ({ banners: { accessibility: 'untrusted', microphone: 'hidden', post_event: 'hidden' } });
    await open();
    await screen.findByRole('button', { name: 'Grant accessibility access' });

    rpc.emit('permissions', { banners: { accessibility: 'hidden', microphone: 'hidden', post_event: 'hidden' } });

    await waitFor(() => expect(screen.queryByRole('button', { name: 'Grant accessibility access' })).toBeNull());
  });

  it('picks the palette, theme, language and text size', async () => {
    await open();

    await fireEvent.click(screen.getByRole('radio', { name: /Nord/ }));
    await fireEvent.click(screen.getByRole('button', { name: 'Text size' }));
    await fireEvent.click(await screen.findByRole('option', { name: '130%' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Theme' }));
    await fireEvent.click(await screen.findByRole('option', { name: 'Dark' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Language' }));
    await fireEvent.click(await screen.findByRole('option', { name: 'Русский' }));

    await waitFor(() => {
      const sent = rpc.called('settings.set').map((p) => [p.key, p.value]);
      expect(sent).toEqual(expect.arrayContaining([
        ['ui.palette', 'nord'], ['ui.text_scale', 1.3], ['ui.theme', 'dark'], ['ui.language', 'ru'],
      ]));
    });
  });

  it('keeps the longest-recording field inside its bounds', async () => {
    await open();
    const field = screen.getByRole('textbox', { name: /Longest recording/ });

    await fireEvent.input(field, { target: { value: '99999' } });
    await fireEvent.change(field);

    expect(rpc.called('settings.set').some((p) => p.key === 'audio.max_duration')).toBe(false);
    expect(get(toasts).some((t) => t.title.includes('0 to 3600'))).toBe(true);

    await fireEvent.input(field, { target: { value: '120' } });
    await fireEvent.change(field);
    await waitFor(() => expect(rpc.called('settings.set')).toContainEqual({ key: 'audio.max_duration', value: 120 }));
  });

  it('does not turn an emptied longest-recording field into "no limit"', async () => {
    await open();
    const field = screen.getByRole('textbox', { name: /Longest recording/ });

    await fireEvent.input(field, { target: { value: '' } });
    await fireEvent.change(field);

    expect(rpc.called('settings.set').some((p) => p.key === 'audio.max_duration')).toBe(false);
    expect(field.value).toBe('300');

    // Zero typed on purpose still means no limit.
    await fireEvent.input(field, { target: { value: '0' } });
    await fireEvent.change(field);
    await waitFor(() => expect(rpc.called('settings.set')).toContainEqual({ key: 'audio.max_duration', value: 0 }));
  });

  it('gives each "Type it instead" the name of the field it belongs to', async () => {
    await open();
    const names = screen.getAllByRole('button', { name: /^Type it instead/ }).map((b) => b.getAttribute('aria-label'));
    expect(names.length).toBeGreaterThan(1);
    expect(new Set(names).size).toBe(names.length);
  });

  it('warns when a setting is applied but the file could not be written', async () => {
    rpc.handlers['settings.set'] = ({ key, value }) => ({ key, value, live_error: null, save_error: 'The settings file could not be written.' });
    await open();
    await fireEvent.click(screen.getByRole('switch', { name: 'Sound cues' }));
    await waitFor(() => expect(get(toasts).some((t) => t.title === 'Not saved to disk' && t.tone === 'danger')).toBe(true));
    expect(get(toasts).some((t) => t.title === 'Saved')).toBe(false);
  });

  it('reads the settings again when another client changed one', async () => {
    await open();
    const before = rpc.called('settings.get').length;
    rpc.emit('settings', { keys: ['clipboard.auto_paste'] });
    await waitFor(() => expect(rpc.called('settings.get').length).toBe(before + 1));
  });

  it('has a Start when I log in switch, off by default, saved the moment it is flipped', async () => {
    await open();
    const row = screen.getByRole('switch', { name: 'Start when I log in' });
    expect(row.getAttribute('aria-checked')).toBe('false');

    await fireEvent.click(row);

    await waitFor(() => expect(rpc.called('settings.set')).toContainEqual({ key: 'ui.start_at_login', value: true }));
  });

  it('shows the switch on when the stored value is on, and puts it back when the write fails', async () => {
    stored = settingsPayload({ ui: { ...settingsPayload().ui, start_at_login: true } });
    await open();
    const row = screen.getByRole('switch', { name: 'Start when I log in' });
    expect(row.getAttribute('aria-checked')).toBe('true');

    rpc.handlers['settings.set'] = () => { throw Object.assign(new Error('nope'), { code: 'internal' }); };
    await fireEvent.click(row);

    await waitFor(() => expect(row.getAttribute('aria-checked')).toBe('true'));
    expect(get(toasts).some((t) => t.title === 'Could not save')).toBe(true);
  });

  it('opens About when the application menu asks for it (Windows and Linux)', async () => {
    const { aboutRequested } = await import('../renderer/src/lib/nav.js');
    await open();
    expect(screen.queryByRole('dialog')).toBeNull();

    aboutRequested.update((n) => n + 1);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Lazy to Text 9.9.9')).toBeTruthy();
    expect(within(dialog).getByText('Released under the MIT licence.')).toBeTruthy();
    expect(dialog.textContent).not.toMatch(/CUDA|NVIDIA/);
  });

  it('opens About with the version', async () => {
    await open();

    await fireEvent.click(screen.getByRole('button', { name: 'About' }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Lazy to Text 9.9.9')).toBeTruthy();
    expect(within(dialog).getByRole('link').textContent).toContain('github.com/aa-blinov/lazy-to-text');
  });

  it('says so and offers a retry when the settings cannot be loaded', async () => {
    rpc.handlers['settings.get'] = () => {
      throw Object.assign(new Error('runtime is down'), { code: 'internal' });
    };
    render(Settings);

    expect(await screen.findByText('runtime is down')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
  });

  it('is read in Russian from the catalogue', async () => {
    language.set('ru');
    render(Settings);

    expect(await screen.findByRole('heading', { name: 'Ввод звука' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Горячие клавиши' })).toBeTruthy();
  });

  it('does not say "Saved" when the runtime refused the whole change, and puts the field back', async () => {
    rpc.handlers['settings.set_hotkeys'] = () => ({
      saved: false, live: false, live_error: null, save_error: null, settings: stored,
      errors: { stop: { template: 'Stop is the same as Start (%1).', args: ['ctrl+f9'], message: 'Stop is the same as Start (ctrl+f9).' } },
    });
    await open();

    const field = screen.getByRole('button', { name: /^Start recording:/ });
    await fireEvent.click(field);
    await fireEvent.keyDown(field, key('F9', { ctrlKey: true }));

    await waitFor(() => expect(rpc.called('settings.set_hotkeys').length).toBe(1));
    await waitFor(() => expect(get(toasts).some((t) => t.tone === 'danger' && t.description.includes('Stop is the same as Start'))).toBe(true));
    const titles = get(toasts).map((t) => t.title);
    expect(titles).not.toContain('Saved');
    expect(titles).not.toContain('Saved, but not applied yet');
    // The field shows what is in force, not the refused binding.
    expect(screen.getByRole('button', { name: /^Start recording:/ }).textContent).toContain('F8');
    expect(screen.getByRole('button', { name: /^Start recording:/ }).textContent).not.toContain('F9');
  });

  it('follows a microphone chosen elsewhere, on the settings event and when the window regains focus', async () => {
    let current = null;
    rpc.handlers['devices.list'] = () => ({ devices: [{ index: 0, name: 'Built-in' }, { index: 3, name: 'USB mic' }], current });
    await open();
    expect(screen.getByRole('button', { name: 'Microphone' }).textContent).toContain('System default');

    current = 3;
    rpc.emit('settings', { keys: ['audio.device'] });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Microphone' }).textContent).toContain('[3] USB mic'));

    current = 0;
    window.dispatchEvent(new Event('focus'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Microphone' }).textContent).toContain('[0] Built-in'));
  });

  it('does not re-list the devices for a setting that is not the microphone', async () => {
    await open();
    const before = rpc.called('devices.list').length;
    rpc.emit('settings', { keys: ['ui.theme'] });
    await waitFor(() => expect(rpc.called('settings.get').length).toBeGreaterThan(1));
    expect(rpc.called('devices.list').length).toBe(before);
  });
});
