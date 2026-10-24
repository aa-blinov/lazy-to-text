// The one way this interface raises a toast. The library's own queue keeps a
// message until the user closes it when `duration` is 0, and keeps four: an
// error from a model load sat in the corner for ten minutes, and three failed
// exports stacked over the bottom of a form. A message here always ends by
// itself, and the stack is capped, so neither can happen.

import { get } from 'svelte/store';
import { toast as raise, toasts, dismissToast } from '@monos/ui';

/** How long a message stays, by what it says. A problem is read slower than a confirmation. */
export const TOAST_MS = { success: 4000, neutral: 4000, info: 4000, warning: 8000, danger: 8000 };
export const TOAST_MAX = 3;

export function toast(options) {
  const value = typeof options === 'string' ? { title: options } : { ...options };
  const tone = value.tone ?? 'neutral';
  const fallback = TOAST_MS[tone] ?? 4000;
  // 0 means "until closed" to the library; here it means "the long wait for this tone".
  if (!value.duration || value.duration < 0) value.duration = fallback;
  const id = raise(value);
  const list = get(toasts);
  for (const old of list.slice(0, Math.max(0, list.length - TOAST_MAX))) dismissToast(old.id);
  return id;
}
