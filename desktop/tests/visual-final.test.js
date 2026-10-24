// Regression tests for the fourth QA round (visual-final): the figures and
// labels that can be checked without a layout engine.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/svelte';
import { percent, loadingDetail } from '../renderer/src/components/statusFormat.js';
import { downloadFigures } from '../renderer/src/components/models/store.js';
import PresetPicker from '../renderer/src/components/presets/PresetPicker.svelte';

const SRC = join(import.meta.dirname, '..', 'renderer', 'src');
const read = (p) => readFileSync(join(SRC, p), 'utf8');

afterEach(cleanup);

describe('one percent for every progress display', () => {
  it('the strip, the card and the banner read the same number', () => {
    const current = 92.5 * 1024 * 1024;
    const total = 259.4 * 1024 * 1024;
    const figures = downloadFigures({ current, total }, null);
    expect(figures.percent).toBe(percent(current, total));
    expect(figures.percent).toBe(36);
    expect(loadingDetail({ current, total })).toContain('(36%)');
  });

  it('is held under 100 until the load ends, and null with no total', () => {
    expect(percent(100, 100)).toBe(99);
    expect(downloadFigures({ current: 0, total: 0 }, null).percent).toBeNull();
  });
});

describe('the preset that is in use', () => {
  const profiles = [{ id: 'a', name: 'A' }, { id: 'b', name: 'B' }];

  it('is plain readable text, not a disabled button', () => {
    render(PresetPicker, { props: { profiles, currentId: 'a', activeId: 'a' } });
    expect(screen.getByTestId('preset-in-use').textContent).toContain('In use by default');
    expect(screen.queryByRole('button', { name: 'In use by default' })).toBeNull();
  });

  it('offers the action for a preset that is not in use', () => {
    render(PresetPicker, { props: { profiles, currentId: 'b', activeId: 'a' } });
    expect(screen.getByRole('button', { name: 'Use this one by default' })).toBeTruthy();
    expect(screen.queryByTestId('preset-in-use')).toBeNull();
  });
});

describe('first-run step 3 names each key', () => {
  it('labels the start key and the stop key separately, never "to stop" after the start key', () => {
    const src = read('views/FirstRun.svelte');
    expect(src).toContain("$t('Start:')");
    expect(src).toContain("$t('Stop:')");
    expect(src).not.toContain("$t('to stop')");
    const ru = JSON.parse(read('i18n/ru.json'));
    expect(ru['Start:']).toBe('Старт:');
    expect(ru['Stop:']).toBe('Стоп:');
  });
});

describe('truncated labels carry a title', () => {
  it('the sidebar items and the strip detail say the whole text on hover', () => {
    expect(read('App.svelte')).toMatch(/<SidebarItem title=\{\$t\(view\.label\)\}/);
    expect(read('components/StatusStrip.svelte')).toContain('title={detail}');
  });
});
