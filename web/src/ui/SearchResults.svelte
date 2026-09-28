<script lang="ts">
  import { searchSections } from '../app/search';
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

  const sections = $derived(searchSections(options));
  /** The option Enter picks: the highlighted one, else the first. */
  const target = $derived(active >= 0 ? active : 0);
</script>

<!--
  Loaded with the search index on the first focus of the search field. Focus
  stays in the field (aria-activedescendant points at the highlighted option),
  so a press on an option must not take it away before the click lands. Each
  kind of result is a group under its heading; the list is one run of options
  for the arrow keys, in the order shown.
-->
<div class="results">
  {#if options.length > 0}
    <div class="list" {id} role="listbox" aria-label={copy.search.results}>
      {#each sections as section (section.kind)}
        <div class="section" role="group" aria-labelledby="{id}-{section.kind}">
          <div class="heading" id="{id}-{section.kind}" aria-hidden="true">
            {copy.search.sections[section.kind]}
          </div>
          {#each section.options as option, n (option.id)}
            {@const index = section.start + n}
            <div
              id={option.id}
              class="option"
              class:is-target={index === target}
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
              <svg class="icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                {#if section.kind === 'city'}
                  <path
                    d="M8 14.25s4.25-3.9 4.25-7.5a4.25 4.25 0 0 0-8.5 0c0 3.6 4.25 7.5 4.25 7.5z"
                  />
                  <circle cx="8" cy="6.75" r="1.5" />
                {:else if section.kind === 'zip'}
                  <rect x="2.25" y="3.75" width="11.5" height="8.5" rx="1.5" />
                  <path d="M2.75 4.75L8 8.5l5.25-3.75" />
                {:else if section.kind === 'district'}
                  <path d="M3 6.25h10L8 2.75z" />
                  <path d="M4.75 6.25v5.5M8 6.25v5.5M11.25 6.25v5.5M2.25 13.25h11.5" />
                {:else}
                  <path d="M2.25 7.25L8 3.25l5.75 4" />
                  <path d="M3.75 6.25v7h8.5v-7" />
                  <path d="M6.75 13.25v-3h2.5v3" />
                {/if}
              </svg>
              <span class="text">
                <span class="name"
                  >{#each option.parts as part, at (at)}{#if part.match}<b>{part.text}</b
                      >{:else}{part.text}{/if}{/each}</span
                >
                {#if option.sub !== ''}
                  <span class="sub">{option.sub}</span>
                {/if}
              </span>
              <span class="enter" aria-hidden="true">
                <svg viewBox="0 0 12 12" focusable="false">
                  <path d="M9.25 2.75v3.5a1.5 1.5 0 0 1-1.5 1.5H3" />
                  <path d="M5 5.75l-2 2 2 2" />
                </svg>
              </span>
            </div>
          {/each}
        </div>
      {/each}
    </div>
  {:else}
    <p class="empty">{copy.search.noResults}</p>
  {/if}
</div>

<style>
  /*
    Under the search field; the shell sets where it starts and ends
    (--results-left, --results-right), as wide as the strip on a phone. It
    never runs past the bottom of the screen: what does not fit scrolls.
  */
  .results {
    position: absolute;
    top: calc(100% + 8px);
    right: var(--results-right, 0);
    left: var(--results-left, 0);
    z-index: 3;
    max-height: calc(
      100dvh - var(--inset-top, 0px) - var(--inset-bottom, 0px) - 2 * var(--edge, 20px) -
        var(--brand-stack, 0px) - var(--bar-height, 44px) - 8px
    );
    overflow-y: auto;
    overscroll-behavior: contain;
    scrollbar-width: thin;
    scrollbar-color: var(--border-2) transparent;
    /* Solid: a backdrop blur over the moving WebGL map makes some GPUs flicker. */
    background: var(--surface-1);
    border: 1px solid var(--border-2);
    border-radius: 16px;
    box-shadow: 0 16px 40px rgb(0 0 0 / 0.6);
  }

  .section {
    padding: 4px 6px 6px;
  }

  .section + .section {
    border-top: 1px solid var(--border-1);
  }

  .heading {
    padding: 8px 10px 4px;
    font-size: 12px;
    font-weight: 500;
    line-height: 16px;
    letter-spacing: 0.01em;
    color: var(--text-2);
    user-select: none;
  }

  .option {
    display: grid;
    grid-template-columns: 16px minmax(0, 1fr) 20px;
    column-gap: 12px;
    align-items: center;
    min-height: 44px;
    padding: 5px 10px;
    cursor: pointer;
    border-radius: 10px;
    outline: none;
  }

  /* Arrow keys scroll an option into view with its section's heading. */
  .heading + .option {
    scroll-margin-top: 32px;
  }

  /* The option Enter picks: the highlighted one, else the first. */
  .option.is-target {
    background: var(--border-1);
  }

  .icon {
    width: 16px;
    height: 16px;
    fill: none;
    stroke: var(--text-3);
    stroke-width: 1.25;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .option.is-target .icon {
    stroke: var(--text-2);
  }

  .text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  /* A long name wraps at its spaces, whole: no name is cut short. */
  .name {
    overflow-wrap: break-word;
    text-wrap: pretty;
  }

  .sub {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .name {
    font-size: 14px;
    font-weight: 400;
    line-height: 19px;
    color: var(--text-1);
  }

  /* What the text typed matched, a step heavier than the rest of the name. */
  .name b {
    font-weight: 600;
  }

  .sub {
    font-size: 12px;
    line-height: 16px;
    color: var(--text-2);
  }

  /* Enter's key on that option, where there is a keyboard to press it. */
  .enter {
    display: grid;
    place-items: center;
    width: 20px;
    height: 20px;
    visibility: hidden;
    color: var(--text-2);
    border: 1px solid var(--border-2);
    border-radius: 5px;
  }

  .option.is-target .enter {
    visibility: visible;
  }

  .enter svg {
    width: 12px;
    height: 12px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.25;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .empty {
    margin: 0;
    padding: 12px 16px;
    font-size: 14px;
    line-height: 20px;
    color: var(--text-2);
  }

  /* Touch: a thumb's height for each option, and no key to show. */
  @media (hover: none), (pointer: coarse) {
    .option {
      grid-template-columns: 16px minmax(0, 1fr);
      min-height: 52px;
    }

    .enter {
      display: none;
    }
  }
</style>
