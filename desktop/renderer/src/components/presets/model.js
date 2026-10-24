// Pure rules of the post-processing screen, kept out of the components so
// they can be tested without drawing anything.

/**
 * The draft after the provider changed.
 *
 * The address follows the provider only while it is empty or one of the
 * defaults the picker itself offers: an address the user typed is theirs,
 * and rewriting it is the same bug as overwriting a saved model name.
 * Custom has no default to move to.
 */
export function withProvider(draft, providerId, catalogue) {
  const providers = catalogue?.providers ?? [];
  const chosen = providers.find((p) => p.id === providerId);
  const current = (draft.base_url || '').trim();
  const known = new Set(providers.map((p) => p.url).filter(Boolean));
  const next = { ...draft, provider: providerId };
  if (chosen && chosen.url && (!current || known.has(current))) {
    next.base_url = chosen.url;
  }
  return next;
}

/** A provider this build does not know lands on Custom, never on the first row. */
export function providerValue(draft, catalogue) {
  const providers = catalogue?.providers ?? [];
  return providers.some((p) => p.id === draft.provider) ? draft.provider : 'custom';
}

/** The address a request would really go to, for the privacy line. */
export function resolvedUrl(draft, catalogue) {
  const typed = (draft.base_url || '').trim();
  if (typed) return typed;
  const provider = (catalogue?.providers ?? []).find((p) => p.id === draft.provider);
  return provider?.url || '';
}

/** Which of the two privacy lines applies, or null while there is nothing to say. */
export function privacyKind(local) {
  if (local === null || local === undefined) return null;
  return local ? 'local' : 'remote';
}

/** The fields the editor owns, as the runtime stores them. */
export function toPayload(draft) {
  return {
    id: draft.id,
    name: (draft.name || '').trim() || draft.id,
    provider: draft.provider || 'ollama',
    base_url: (draft.base_url || '').trim(),
    model: (draft.model || '').trim(),
    api_key: draft.api_key || '',
    mode: draft.mode || 'clean',
    custom_prompt: draft.custom_prompt || '',
    reasoning_effort: draft.reasoning_effort || '',
    max_tokens: Number(draft.max_tokens) || 0,
    timeout_s: Number(draft.timeout_s) || 0,
  };
}

/** Whether two drafts would write the same thing. */
export function sameDraft(a, b) {
  return JSON.stringify(toPayload(a)) === JSON.stringify(toPayload(b));
}
