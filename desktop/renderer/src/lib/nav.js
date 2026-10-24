// A screen asks the shell to show another one ("open Models") without
// knowing how the shell tracks the current screen.

import { writable } from 'svelte/store';

export const requestedView = writable(null);

export function goTo(id) {
  requestedView.set(id);
}

/**
 * Whether the shell (sidebar and screens) is on screen. False while the
 * first-run page stands in for it, and before the first snapshot has said
 * which of the two it is. A file handed to the app is held until it is true.
 */
export const shellShown = writable(false);

/** The About dialog: the menu asks for it, the Settings screen draws it. */
export const aboutRequested = writable(0);
