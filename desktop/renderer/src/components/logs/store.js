// The records the Logs screen shows. The runtime keeps the last 2000 in a
// ring and publishes each new one as a `log` event; this merges the two by
// id so a record that arrives while the list is loading is not shown twice.
// "Clear" empties the view only, and survives leaving the screen: it is a
// floor on the ids shown, not a deletion.

import { writable, get } from 'svelte/store';
import { call, subscribe } from '../../lib/rpc.js';

export const CAP = 2000;

export const records = writable([]);
export const clearedUpTo = writable(0);

function merge(existing, incoming) {
  const byId = new Map(existing.map((r) => [r.id, r]));
  for (const r of incoming) byId.set(r.id, r);
  const all = [...byId.values()].sort((a, b) => a.id - b.id);
  return all.length > CAP ? all.slice(all.length - CAP) : all;
}

export function clearView() {
  const all = get(records);
  clearedUpTo.set(all.length ? all[all.length - 1].id : 0);
  records.set([]);
}

/** Start following the runtime; returns the function that stops. */
export function attach() {
  const off = subscribe('log', (item) => {
    if (item.id > get(clearedUpTo)) records.update((r) => merge(r, [item]));
  });
  call('logs.list')
    .then(({ records: list }) => {
      const floor = get(clearedUpTo);
      const top = list.length ? list[list.length - 1].id : 0;
      // A restarted runtime numbers from 1 again; an old floor would hide it all.
      if (top < floor) clearedUpTo.set(0);
      const keep = list.filter((r) => r.id > get(clearedUpTo));
      records.update((r) => merge(r, keep));
    })
    .catch(() => {});
  return off;
}
