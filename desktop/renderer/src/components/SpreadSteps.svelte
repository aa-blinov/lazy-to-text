<script>
  // A row of steps that uses the whole width: three equal columns, each with
  // its own stretch of the connecting line, so the first circle sits at the
  // left edge, the last at the right edge, the middle one exactly between
  // them, and the line is unbroken from circle to circle. The kit's Stepper
  // gives every step an equal share and draws a line only after a step, which
  // leaves the right part of the row empty and cannot align the last label to
  // the edge. The look is the kit's: same circle, same tokens.
  export let steps = [];
  export let value = '';
  export let label = '';

  $: current = Math.max(0, steps.findIndex((step) => step.id === value));
  $: last = steps.length - 1;

  const align = (index, count) =>
    index === 0 ? 'items-start text-left' : index === count - 1 ? 'items-end text-right' : 'items-center text-center';
</script>

<ol
  aria-label={label || undefined}
  class="grid"
  style:grid-template-columns="repeat({steps.length}, minmax(0, 1fr))"
>
  {#each steps as step, index (step.id)}
    <li class="flex min-w-0 flex-col gap-2 {align(index, steps.length)}">
      <div class="flex w-full items-center gap-2" aria-hidden="true">
        {#if index > 0}<span class="h-px flex-1 bg-line"></span>{/if}
        <span
          class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-xs font-bold {index ===
          current
            ? 'border-ink bg-ink text-canvas'
            : index < current
              ? 'border-ink text-ink'
              : 'border-line text-ink-faint'}"
        >
          {#if index < current}
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none">
              <polyline
                points="20 6 9 17 4 12"
                stroke="currentColor"
                stroke-width="1.7"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          {:else}
            {index + 1}
          {/if}
        </span>
        {#if index < last}<span class="h-px flex-1 bg-line"></span>{/if}
      </div>
      <span
        class="min-w-0 pt-1 text-sm font-bold {index === current ? 'text-ink' : 'text-ink-soft'}"
        aria-current={index === current ? 'step' : undefined}
      >
        {step.label}
      </span>
    </li>
  {/each}
</ol>
