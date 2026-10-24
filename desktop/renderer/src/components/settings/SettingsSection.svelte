<script>
  // One card of the page. The id is the in-page anchor the jump links and
  // the keyboard use; the heading is what a screen reader lists.
  import { Card } from '@monos/ui';

  export let id;
  export let title;
  export let description = '';
</script>

<section {id} class="scroll-mt-16" aria-labelledby="{id}-title">
  <Card padding="md">
    <h2 id="{id}-title" class="text-lg text-ink">{title}</h2>
    {#if description}<p class="mt-1 text-xs text-ink-faint">{description}</p>{/if}
    <div class="mt-2 flex flex-col divide-y divide-line">
      <slot />
    </div>
  </Card>
</section>
