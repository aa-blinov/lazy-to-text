import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, fireEvent, cleanup } from '@testing-library/svelte';
import { tick } from 'svelte';
import SlideDrawer from '../renderer/src/components/SlideDrawer.svelte';

afterEach(() => cleanup());

// The panel's own close button is the first button inside the panel; the backdrop
// button is outside it and carries the same label.
const closeButton = (container) => container.querySelector('.ui-drawer button');

describe('SlideDrawer', () => {
  it('stays in the page while it slides out, and leaves once the exit has run', async () => {
    const { container } = render(SlideDrawer, { props: { open: true, title: 'Storage', closeLabel: 'Close' } });
    const panel = () => container.querySelector('.ui-drawer');
    expect(panel()).not.toBeNull();

    await fireEvent.click(closeButton(container));

    // Closing starts the exit: the panel is still there, marked as leaving.
    expect(panel()).not.toBeNull();
    expect(panel().classList.contains('leaving')).toBe(true);

    // The exit's end removes it.
    await fireEvent.animationEnd(panel());
    expect(panel()).toBeNull();
  });

  it('closes on Escape', async () => {
    const { container } = render(SlideDrawer, { props: { open: true, title: 'x' } });

    await fireEvent.keyDown(window, { key: 'Escape' });

    expect(container.querySelector('.ui-drawer').classList.contains('leaving')).toBe(true);
  });

  it('removes the panel after a fallback delay when no animation end is reported', async () => {
    vi.useFakeTimers();
    try {
      const { container } = render(SlideDrawer, { props: { open: true, title: 'x' } });
      await fireEvent.click(closeButton(container));
      expect(container.querySelector('.ui-drawer')).not.toBeNull();

      vi.advanceTimersByTime(300);
      await tick();
      expect(container.querySelector('.ui-drawer')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('opens again cleanly after a close', async () => {
    const { container, rerender } = render(SlideDrawer, { props: { open: true, title: 'x' } });
    await fireEvent.click(closeButton(container));
    await fireEvent.animationEnd(container.querySelector('.ui-drawer'));
    expect(container.querySelector('.ui-drawer')).toBeNull();

    await rerender({ open: true, title: 'x' });
    expect(container.querySelector('.ui-drawer')).not.toBeNull();
    expect(container.querySelector('.ui-drawer').classList.contains('leaving')).toBe(false);
  });
});
