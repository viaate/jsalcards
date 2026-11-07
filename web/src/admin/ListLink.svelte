<script lang="ts">
  interface Props {
    /** A source's id; null: none. */
    id: string | null;
    /** Its source type, shown after it; null: not shown. */
    kind: string | null;
    /** Each source's public link, by id: a source without one shows its id plainly. */
    links: Readonly<Record<string, string>>;
  }

  let { id, kind, links }: Props = $props();

  const href = $derived(id === null ? undefined : links[id]);
</script>

<!-- One source on the admin Lists tab: its id, linked to its public page when it has one, and its type. -->
{#if id !== null}
  {#if href === undefined}{id}{:else}<a {href} target="_blank" rel="noopener noreferrer">{id}</a
    >{/if}
{/if}
{#if kind !== null}<span class="muted">{kind}</span>{/if}
