// A screen asks the shell to show another one ("open Models") without
// knowing how the shell tracks the current screen.

import { writable } from 'svelte/store';

export const requestedView = writable(null);

export function goTo(id) {
  requestedView.set(id);
}
