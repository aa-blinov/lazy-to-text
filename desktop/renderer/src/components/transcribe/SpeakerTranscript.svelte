<script>
  // The transcript of a file split by speakers, read as a conversation: a
  // coloured name where the voice changes, the speech beside it. Each turn is
  // editable in place, and a name is renamed everywhere by clicking it.
  import { createEventDispatcher, tick } from 'svelte';
  import { t } from '../../lib/i18n.js';
  import { joinTurns, renameSpeaker, speakerList, speakerRole } from '../../lib/speakers.js';

  export let turns = [];

  const dispatch = createEventDispatcher();
  let renaming = null;
  let draft = '';

  $: list = speakerList(turns);
  const TEXT = { accent: 'text-accent-text', warning: 'text-warning-text', success: 'text-success-text', danger: 'text-danger-text', info: 'text-info-text' };
  const BAR = { accent: 'bg-accent', warning: 'bg-warning', success: 'bg-success', danger: 'bg-danger', info: 'bg-info' };

  function setText(index, text) {
    dispatch('change', joinTurns(turns.map((turn, i) => (i === index ? { ...turn, text } : turn))));
  }

  async function startRename(speaker) {
    renaming = speaker;
    draft = speaker;
    await tick();
    document.querySelector('[data-testid=speaker-rename]')?.select();
  }

  function commitRename() {
    if (renaming === null) return;
    const from = renaming;
    renaming = null;
    const next = renameSpeaker(turns, from, draft);
    if (next !== turns) dispatch('change', joinTurns(next));
  }

  function grow(node) {
    const fit = () => {
      node.style.height = 'auto';
      node.style.height = `${node.scrollHeight}px`;
    };
    fit();
    node.addEventListener('input', fit);
    return { update: fit, destroy: () => node.removeEventListener('input', fit) };
  }
</script>

<div
  class="h-full overflow-y-auto rounded-ui border border-line bg-surface px-4 py-3"
  data-testid="speaker-transcript"
  role="group"
  aria-label={$t('Transcript')}
>
  {#each turns as turn, i (i)}
    {@const role = speakerRole(list, turn.speaker)}
    {@const first = i === 0 || turns[i - 1].speaker !== turn.speaker}
    <div class="grid grid-cols-[9rem_minmax(0,1fr)] gap-x-4 {first ? (i === 0 ? '' : 'mt-4') : 'mt-1'}" data-testid="speaker-turn">
      <div class="pt-1.5">
        {#if first}
          {#if renaming === turn.speaker}
            <input
              class="h-7 w-full rounded-ui border border-line bg-canvas px-2 text-xs text-ink"
              data-testid="speaker-rename"
              aria-label={$t('Speaker name')}
              maxlength="40"
              bind:value={draft}
              on:blur={commitRename}
              on:keydown={(e) => {
                if (e.key === 'Enter') e.currentTarget.blur();
                if (e.key === 'Escape') { renaming = null; }
              }}
            />
          {:else}
            <button
              type="button"
              class="flex max-w-full items-center gap-2 rounded-ui text-left text-xs font-medium {TEXT[role]} hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              data-testid="speaker-name"
              title={$t('Click to rename this speaker everywhere')}
              on:click={() => startRename(turn.speaker)}
            >
              <span class="h-3 w-1 shrink-0 rounded-full {BAR[role]}" aria-hidden="true"></span>
              <span class="truncate">{turn.speaker}</span>
            </button>
          {/if}
        {/if}
      </div>
      <textarea
        class="w-full resize-none overflow-hidden bg-transparent py-1 text-sm leading-relaxed text-ink outline-none focus-visible:rounded-ui focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        rows="1"
        aria-label={`${turn.speaker}`}
        value={turn.text}
        use:grow={turn.text}
        on:input={(e) => setText(i, e.currentTarget.value)}
      ></textarea>
    </div>
  {/each}
</div>
