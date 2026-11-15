<script lang="ts">
  import type { LegalBlock } from '../copy-legal';

  interface Props {
    blocks: readonly LegalBlock[];
    /** The page's opening words, under its title: a step larger. */
    lead?: boolean;
  }

  let { blocks, lead = false }: Props = $props();
</script>

<!--
  The blocks of the privacy policy or the terms of use (ui/LegalPage.svelte), in order: a
  paragraph, a list (an item's bold lead, where it has one, before its words), or a table.
-->
{#each blocks as block, index (index)}
  {#if 'p' in block}
    <p class:lead>{block.p}</p>
  {:else if 'list' in block}
    <ul>
      {#each block.list as item, at (at)}
        <li>
          <!-- A space between the lead and its words, but none before a comma. -->
          {#if item.lead !== undefined}<strong>{item.lead}</strong>{item.text.startsWith(',')
              ? ''
              : ' '}{/if}{item.text}
        </li>
      {/each}
    </ul>
  {:else if 'table' in block}
    <table>
      <thead>
        <tr>
          {#each block.table.head as cell, at (at)}<th scope="col">{cell}</th>{/each}
        </tr>
      </thead>
      <tbody>
        {#each block.table.rows as row, at (at)}
          <tr>
            {#each row as cell, column (column)}
              {#if column === 0}<th scope="row">{cell}</th>{:else}<td>{cell}</td>{/if}
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
{/each}

<style>
  p,
  li {
    color: var(--text-2);
    font-size: 15px;
    line-height: 24px;
  }

  p {
    margin: 12px 0 0;
  }

  p.lead {
    margin-top: 16px;
    font-size: 17px;
    line-height: 27px;
  }

  ul {
    margin: 12px 0 0;
    padding-left: 20px;
  }

  li + li {
    margin-top: 8px;
  }

  strong {
    color: var(--text-1);
    font-weight: 600;
  }

  table {
    width: 100%;
    margin-top: 16px;
    table-layout: fixed;
    border-collapse: collapse;
    font-size: 14px;
    line-height: 21px;
  }

  th,
  td {
    padding: 10px 12px 10px 0;
    text-align: left;
    vertical-align: top;
    overflow-wrap: break-word;
    border-bottom: 1px solid var(--border-1);
  }

  th:last-child,
  td:last-child {
    padding-right: 0;
  }

  thead th {
    color: var(--text-2);
    font-weight: 500;
  }

  thead th:first-child {
    width: 26%;
  }

  thead th:nth-child(2) {
    width: 44%;
  }

  tbody th {
    color: var(--text-1);
    font-weight: 500;
  }

  td {
    color: var(--text-2);
  }

  @media (max-width: 480px) {
    table {
      font-size: 13px;
      line-height: 19px;
    }

    th,
    td {
      padding-right: 8px;
    }
  }
</style>
