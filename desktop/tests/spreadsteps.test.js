import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import SpreadSteps from '../renderer/src/components/SpreadSteps.svelte';

const steps = [
  { id: 'a', label: 'Choose' },
  { id: 'b', label: 'Download' },
  { id: 'c', label: 'Learn the key' },
];

describe('SpreadSteps', () => {
  it('names the current step and shows a check on the finished ones', () => {
    const { container, getByText } = render(SpreadSteps, { steps, value: 'b', label: 'Setup steps' });

    expect(container.querySelector('ol').getAttribute('aria-label')).toBe('Setup steps');
    expect(getByText('Download').getAttribute('aria-current')).toBe('step');
    expect(getByText('Choose').getAttribute('aria-current')).toBeNull();
    expect(container.querySelectorAll('svg polyline')).toHaveLength(1);
  });

  it('gives every circle its line on both sides but the ends, and aligns the ends to the edges', () => {
    const { container } = render(SpreadSteps, { steps, value: 'a' });
    const items = [...container.querySelectorAll('li')];
    const linesIn = (li) => li.querySelectorAll('span.h-px').length;

    expect(items.map(linesIn)).toEqual([1, 2, 1]);
    expect(items[0].className).toContain('items-start');
    expect(items[1].className).toContain('items-center');
    expect(items[2].className).toContain('items-end');
  });
});
