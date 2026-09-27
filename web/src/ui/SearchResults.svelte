<script lang="ts">
  import type { SearchOption } from '../app/search';
  import { copy } from '../copy';

  interface Props {
    /** The list's element id, which the search field names in aria-controls. */
    id: string;
    options: readonly SearchOption[];
    /** The highlighted option's index, or -1. */
    active: number;
    onpick: (option: SearchOption) => void;
    onactive: (index: number) => void;
  }

  let { id, options, active, onpick, onactive }: Props = $props();
</script>

<!--
  Loaded with the search index on the first focus of the search field. Focus
  stays in the field (aria-activedescendant points at the highlighted option),
  so a press on an option must not take it away before the click lands.
-->
<div class="results">
  {#if options.length > 0}
    <div class="list" {id} role="listbox" aria-label={copy.search.results}>
      {#each options as option, index (option.id)}
        <div
          id={option.id}
          class="option"
          class:is-active={index === active}
          class:starts-group={option.startsGroup}
          role="option"
          tabindex="-1"
          aria-selected={index === active}
          onpointerdown={(event) => {
            event.preventDefault();
          }}
          onpointermove={() => {
            if (index !== active) onactive(index);
          }}
          onclick={() => {
            onpick(option);
          }}
          onkeydown={(event) => {
            if (event.key === 'Enter') onpick(option);
          }}
        >
          <span class="text">
            <span class="name"
              >{#each option.parts as part, at (at)}{#if part.match}<b>{part.text}</b
                  >{:else}{part.text}{/if}{/each}</span
            >
            {#if option.sub !== ''}
              <span class="sub">{option.sub}</span>
            {/if}
          </span>
          <span class="kind">{copy.search.kind[option.hit.kind]}</span>
        </div>
      {/each}
    </div>
  {:else}
    <p class="empty">{copy.search.noResults}</p>
  {/if}
</div>

<style>
  .results {
    position: absolute;
    top: calc(100% + 8px);
    right: -1px;
    left: -1px;
    z-index: 3;
    max-height: min(60vh, 460px);
    padding: 6px 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    background: rgb(10 10 10 / 0.94);
    border: 1px solid var(--border-2);
    border-radius: 18px;
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
  }

  .list {
    margin: 0;
  }

  .option {
    display: flex;
    gap: 12px;
    align-items: center;
    min-height: 48px;
    padding: 7px 18px;
    cursor: pointer;
    outline: none;
  }

  .option.starts-group {
    margin-top: 6px;
    border-top: 1px solid var(--border-1);
    padding-top: 13px;
  }

  .option.is-active {
    background: var(--border-1);
  }

  .text {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-width: 0;
  }

  .name,
  .sub {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .name {
    font-size: 14px;
    line-height: 20px;
    color: var(--text-2);
  }

  .name b {
    font-weight: 600;
    color: var(--text-1);
  }

  .sub {
    font-size: 12px;
    line-height: 16px;
    color: var(--text-3);
  }

  .kind {
    flex: none;
    font-size: 12px;
    line-height: 16px;
    color: var(--text-3);
  }

  .empty {
    margin: 0;
    padding: 12px 18px;
    font-size: 14px;
    line-height: 20px;
    color: var(--text-3);
  }
</style>
