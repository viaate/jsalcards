<script lang="ts">
  import { untrack } from 'svelte';
  import type { Attachment } from 'svelte/attachments';

  import type { NearbyView, SchoolView } from '../app/school';
  import { copy } from '../copy';
  import ChanceSection from './ChanceSection.svelte';
  import { attachSheet } from './sheet';
  import type { Detent, Sheet } from './sheet';
  import { PHONE_QUERY } from './sheet-geometry';

  interface Props {
    view: SchoolView;
    /** Whether this school is the pinned one ("My school"). */
    pinned: boolean;
    /** True for a moment after the link was copied. */
    copied: boolean;
    onclose: () => void;
    onpin: () => void;
    /** None while the page cannot write a link yet: the panel has no Share then. */
    onshare?: (() => void) | undefined;
    /** Opens a school from the nearby list. */
    onnearby?: (school: NearbyView) => void;
    /** On a phone, the sheet came to rest at another height: the map's labels make room for it. */
    onsettle?: () => void;
    /** The panel's element, for the page to focus after a pick. */
    element?: HTMLElement | undefined;
  }

  let {
    view,
    pinned,
    copied,
    onclose,
    onpin,
    onshare,
    onnearby = () => undefined,
    onsettle = () => undefined,
    element = $bindable(),
  }: Props = $props();

  /** On a phone, the sheet's detent: where it rests, or is going; null beside the map on a wide screen. */
  let detent = $state<Detent | null>(null);
  /** What moves the sheet, while the panel is one (a phone). */
  let sheet: Sheet | null = null;

  /**
   * On a phone the panel is a bottom sheet (ui/sheet.ts), and beside the map
   * again once the screen is wide (a phone turned on its side).
   */
  const asSheet: Attachment<HTMLElement> = (node) => {
    if (typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia(PHONE_QUERY);
    const body = node.querySelector<HTMLElement>('.body');
    const follow = (): void => {
      if (query.matches && sheet === null && body !== null) {
        sheet = attachSheet({
          sheet: node,
          body,
          handles: () => [node.querySelector('.grip'), node.querySelector('.head')],
          head: () => node.querySelector('.head'),
          onclose: () => {
            onclose();
          },
          onsettle: () => {
            onsettle();
          },
          onchange: (next) => {
            detent = next;
          },
        });
      } else if (!query.matches && sheet !== null) {
        sheet.destroy();
        sheet = null;
        detent = null;
      }
    };
    untrack(follow);
    query.addEventListener('change', follow);
    return () => {
      query.removeEventListener('change', follow);
      sheet?.destroy();
      sheet = null;
    };
  };

  // Another school in the same sheet (a nearby one picked): it opens afresh, at its opening height.
  let shownId = untrack(() => view.id);
  $effect(() => {
    const id = view.id;
    if (id === shownId) return;
    shownId = id;
    sheet?.reset();
  });

  /** The glyph's class for a status line's tone, as the legend draws each status. */
  const GLYPHS = {
    closed: 'is-closed',
    delayed: 'is-delayed',
    remote: 'is-remote',
    earlyDismissal: 'is-early-dismissal',
    open: 'is-open',
  } as const;
</script>

<!--
  A school's detail panel: where a search pick or a link to a school lands.
  What it answers first is the school's day, when the live files state it;
  then the chance of a weather closure, when the district's history gives
  one; then what the directory says about the school. Beside the map on a
  wide screen, a sheet over its foot on a phone (ui/sheet.ts), where the
  answer comes before the buttons. Every line comes from the view
  (app/school.ts); nothing here is made up or filled in.
-->
<aside
  class="detail"
  class:is-loading={view.loading && view.name === ''}
  aria-label={copy.detail.label}
  aria-busy={view.loading}
  tabindex="-1"
  bind:this={element}
  {@attach asSheet}
>
  <!-- The sheet's grip, on a phone: a drag moves the sheet, a press takes it up or back. -->
  <button
    class="grip"
    type="button"
    aria-label={detent === 'full' ? copy.detail.less : copy.detail.more}
    aria-expanded={detent === 'full'}
    onclick={() => {
      sheet?.toggle();
    }}
  ></button>
  <div class="body">
    <header class="head">
      {#if view.name === ''}
        <div class="skeleton" aria-hidden="true">
          <span class="bone is-short"></span>
          <span class="bone is-title"></span>
          <span class="bone is-line"></span>
        </div>
      {:else}
        {#if view.kind !== null}
          <p class="kind">{view.kind}</p>
        {:else if view.loading}
          <!-- The chip's place while the record is read: the name stays where it is when it comes. -->
          <span class="bone is-kind" aria-hidden="true"></span>
        {/if}
        <h2 class="name">
          {view.name}{#if view.campus !== null}<span class="campus">{view.campus}</span>{/if}
        </h2>
        {#if view.place !== null}
          <p class="place">{view.place}</p>
        {/if}
      {/if}
      <button
        class="close"
        type="button"
        aria-label={copy.detail.close}
        onclick={() => {
          // A sheet glides away first.
          if (sheet === null) onclose();
          else sheet.dismiss();
        }}
      >
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />
        </svg>
      </button>
    </header>

    {#if view.name !== ''}
      <div class="actions">
        <button
          class="action"
          class:is-on={pinned}
          type="button"
          aria-pressed={pinned}
          onclick={onpin}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path d="M5.75 2.25h4.5l-.6 4.1 2.1 2.15v1.25h-7.5V8.5l2.1-2.15z" />
            <path d="M8 9.75v4" />
          </svg>
          {pinned ? copy.pin.mySchool : copy.actions.pin}
        </button>
        {#if onshare !== undefined}
          <button class="action" class:is-on={copied} type="button" onclick={onshare}>
            <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
              {#if copied}
                <path d="M3.5 8.5l3 3 6-6.5" />
              {:else}
                <path d="M8 2.5v7.25M5.25 5.25L8 2.5l2.75 2.75" />
                <path d="M4.75 7.75h-.5v5.75h7.5V7.75h-.5" />
              {/if}
            </svg>
            {copied ? copy.share.copied : copy.actions.share}
          </button>
        {/if}
      </div>
    {/if}

    {#if view.chance !== null}
      <!-- A chance to give: the section says the status, then the chance (ChanceSection.svelte). -->
      <ChanceSection chance={view.chance} />
    {:else if view.status.length > 0}
      <section class="block status" aria-label={copy.detail.status}>
        {#each view.status as line, n (n)}
          <div class="line">
            <p class="headline">
              {line.headline}<span class="glyph {GLYPHS[line.tone]}" aria-hidden="true"></span>
            </p>
            {#if line.detail !== null}
              <p class="line-detail">{line.detail}</p>
            {/if}
            {#if line.note !== null}
              <p class="line-note">{line.note}</p>
            {/if}
          </div>
        {/each}
      </section>
    {/if}

    {#if view.facts.length > 0}
      <dl class="block rows facts">
        {#each view.facts as fact (fact.label)}
          <div class="row fact">
            <dt class="label">{fact.label}</dt>
            <dd>
              {#if fact.href !== null}
                <a href={fact.href}>{fact.lines.join(' ')}</a>
              {:else}
                {#each fact.lines as text, n (n)}
                  <span class="fact-line">{text}</span>
                {/each}
              {/if}
            </dd>
          </div>
        {/each}
      </dl>
    {/if}

    {#if view.nearby.length > 0}
      <section class="block nearby" aria-labelledby="detail-nearby">
        <h3 class="heading" id="detail-nearby">{copy.detail.nearby}</h3>
        <ul class="near-list">
          {#each view.nearby as school (school.id)}
            <li>
              <button
                class="row near"
                type="button"
                onclick={() => {
                  onnearby(school);
                }}
              >
                <span class="label near-distance">{school.distance}</span>
                <span class="near-text">
                  <span class="near-name">{school.name}</span>
                  {#if school.tone !== null}
                    <span class="glyph {GLYPHS[school.tone]}" aria-hidden="true"></span>
                  {/if}
                </span>
              </button>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
  </div>
</aside>

<style>
  /*
    Beside the map, under the wordmark, clear of the legend at the foot of the
    screen: a solid card like the search results (no backdrop blur over the
    moving WebGL map). What does not fit scrolls inside it.

    The panel's one type scale and one grid, for the chance section too
    (ChanceSection.svelte, ChanceChart.svelte): the chance's number, then
    three sizes (title, body, small) in two weights, and one gray. Every list
    is a row of two columns, a fixed one at the left for times, points and
    labels, and one for the words; sections part at one hairline, 24px each
    side, and everything starts at the left.
  */
  .detail {
    --type-number: 600 60px / 60px var(--font-sans);
    --type-title: 600 20px / 26px var(--font-sans);
    --type-strong: 600 15px / 22px var(--font-sans);
    --type-body: 400 15px / 22px var(--font-sans);
    --type-small: 400 13px / 18px var(--font-sans);
    /* The rows' first column, and the room after it. */
    --column: 64px;
    --gutter: 16px;
    /* Between rows, and each side of the hairline between sections. */
    --row: 16px;
    --section: 24px;

    position: absolute;
    top: calc(var(--inset-top) + var(--edge) + var(--bar-height) + 16px);
    left: calc(var(--inset-left) + var(--edge));
    z-index: 2;
    display: flex;
    flex-direction: column;
    width: 368px;
    max-height: calc(
      100dvh - var(--inset-top) - var(--inset-bottom) - 2 * var(--edge) - var(--bar-height) - 16px -
        var(--control-height) - 16px
    );
    overflow: hidden;
    font: var(--type-body);
    color: var(--text-1);
    background: var(--surface-1);
    border: 1px solid var(--border-2);
    border-radius: 18px;
    outline: none;
    box-shadow:
      inset 0 1px 0 rgb(255 255 255 / 0.04),
      0 0 0 1px var(--bg),
      0 20px 48px rgb(0 0 0 / 0.65);
    animation: arrive 200ms cubic-bezier(0.2, 0.7, 0.2, 1) both;
  }

  /*
    Wider on a wide screen, so the chance section's chart is bigger and its
    lines wrap less: still one column (app/frame.ts PANEL_WIDTHS).
  */
  @media (min-width: 1024px) {
    .detail {
      width: 420px;
    }
  }

  @media (min-width: 1280px) {
    .detail {
      width: 460px;
    }
  }

  /* What the panel says, in one column; what does not fit scrolls inside it. */
  .body {
    display: flex;
    flex: 1 1 auto;
    flex-direction: column;
    min-height: 0;
    padding: 20px;
    overflow-y: auto;
    overscroll-behavior: contain;
    scrollbar-width: thin;
    scrollbar-color: var(--border-2) transparent;
  }

  p,
  h3 {
    margin: 0;
  }

  /* A section: under one hairline, the same room each side of it. */
  .block {
    margin: var(--section) 0 0;
    padding-top: var(--section);
    border-top: 1px solid var(--border-1);
  }

  .heading {
    margin-bottom: var(--row);
    font: var(--type-strong);
    color: var(--text-1);
  }

  /* A list: rows of the two columns, the first in gray. */
  .rows {
    display: flex;
    flex-direction: column;
    gap: var(--row);
  }

  .row {
    display: grid;
    grid-template-columns: var(--column) minmax(0, 1fr);
    column-gap: var(--gutter);
    align-items: start;
    /* No word left alone on a last line. */
    text-wrap: pretty;
  }

  .label {
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }

  /* The sheet's grip: a phone's alone. */
  .grip {
    display: none;
  }

  @keyframes arrive {
    from {
      opacity: 0;
      transform: translateY(6px);
    }
  }

  /* What the school is, then its name, the one heading, then where it is. */
  .head {
    position: relative;
    padding-right: 40px;
  }

  .kind {
    margin-bottom: 4px;
    font: var(--type-small);
    color: var(--text-2);
  }

  .name {
    margin: 0;
    font: var(--type-title);
    letter-spacing: -0.01em;
    color: var(--text-1);
    text-wrap: balance;
    overflow-wrap: break-word;
  }

  /* A campus on a line of its own, in gray. */
  .campus {
    display: block;
    font: var(--type-body);
    color: var(--text-2);
  }

  .place {
    font: var(--type-body);
    color: var(--text-2);
  }

  .close {
    position: absolute;
    top: -6px;
    right: -6px;
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    padding: 0;
    color: var(--text-2);
    cursor: pointer;
    background: transparent;
    border: 0;
    border-radius: 50%;
    transition: color 120ms linear;
  }

  .close:hover,
  .close:focus-visible {
    color: var(--text-1);
  }

  .close:focus-visible,
  .action:focus-visible,
  .facts a:focus-visible {
    outline: 1px solid var(--text-2);
    outline-offset: 2px;
  }

  .close svg {
    width: 16px;
    height: 16px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
  }

  /* Pin and share under the name: words with their marks, from the left, no boxes. */
  .actions {
    display: flex;
    gap: 24px;
    /* The words a row under the place, in the button's taller target. */
    margin: calc(var(--row) - 5px) 0 -5px;
  }

  .action {
    display: flex;
    gap: 8px;
    align-items: center;
    min-width: 0;
    height: 32px;
    padding: 0;
    font: var(--type-body);
    color: var(--text-1);
    text-align: left;
    white-space: nowrap;
    cursor: pointer;
    background: transparent;
    border: 0;
    border-radius: 4px;
    transition: color 120ms linear;
  }

  .action:hover {
    color: var(--text-2);
  }

  .action svg {
    flex: none;
    width: 16px;
    height: 16px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.4;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .action.is-on svg path:first-child {
    fill: currentColor;
  }

  /* The day's status, when there is no chance to give: its line first, then the details. */
  .status {
    display: flex;
    flex-direction: column;
    gap: var(--row);
  }

  .headline {
    display: flex;
    gap: 8px;
    align-items: center;
    font: var(--type-title);
    letter-spacing: -0.01em;
    color: var(--text-1);
  }

  .glyph.is-open {
    box-shadow: inset 0 0 0 1.5px var(--text-2);
  }

  .line-note {
    color: var(--text-2);
  }

  /* What the directory says about the school: a label and its value, a row each. */
  .facts {
    margin-bottom: 0;
  }

  .fact dd {
    display: flex;
    flex-direction: column;
    min-width: 0;
    margin: 0;
    overflow-wrap: break-word;
  }

  .facts a {
    color: inherit;
    text-decoration: none;
    border-radius: 2px;
  }

  .facts a:hover {
    text-decoration: underline;
    text-decoration-color: var(--text-2);
    text-underline-offset: 3px;
  }

  /* The schools nearest this one, each a row that opens it: how far, its name, its status. */
  .near-list {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  /* The rows' own gap is inside each button, so the whole of it opens the school. */
  .near {
    width: calc(100% + 16px);
    margin: 0 -8px;
    padding: calc(var(--row) / 2) 8px;
    font: var(--type-body);
    color: var(--text-1);
    text-align: left;
    cursor: pointer;
    background: transparent;
    border: 0;
    border-radius: 8px;
  }

  li:first-child > .near {
    margin-top: calc(var(--row) / -2);
  }

  li:last-child > .near {
    margin-bottom: calc(var(--row) / -2);
  }

  .near:hover,
  .near:focus-visible {
    background: var(--surface-2);
    outline: none;
  }

  .near:focus-visible {
    box-shadow: inset 0 0 0 1px var(--text-3);
  }

  .near-distance {
    white-space: nowrap;
  }

  .near-text {
    display: flex;
    gap: 8px;
    align-items: center;
    min-width: 0;
  }

  .near-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* A school with a status today: the legend's glyph for it, after its name. */
  .near .glyph.is-remote {
    width: 7px;
    height: 7px;
  }

  /* Until the school's record is read: the shape of what is coming, without words. */
  .skeleton {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .bone {
    display: block;
    height: 12px;
    background: var(--surface-2);
    border-radius: 6px;
  }

  /* The kind's size, so the name below it does not move when the words come. */
  .bone.is-short,
  .bone.is-kind {
    width: 30%;
    height: 18px;
  }

  .bone.is-kind {
    margin-bottom: 4px;
  }

  .bone.is-title {
    width: 80%;
    height: 26px;
  }

  .bone.is-line {
    width: 55%;
  }

  /*
    A phone: a sheet over the foot of the screen (ui/sheet.ts). It is as tall
    as the screen under the search field, and shows as much of itself as its
    detent asks, moved down by a transform alone: open, half the screen, with
    the school in the middle of the map above it; full, up to just under the
    field; or the name alone. Its name first, then the answer (today's status
    and the chance of a closure), then the buttons, then the rest. It covers
    the key and the locate button; the search results, when open, go over it.
    Solid, like the search field: nothing over the moving map is blurred.
  */
  @media (max-width: 719px) {
    .detail {
      top: calc(var(--inset-top) + var(--edge) + var(--brand-stack) + var(--bar-height) + 12px);
      right: 0;
      bottom: 0;
      left: 0;
      width: auto;
      max-height: none;
      /* The home indicator's room: the sheet's content ends above it. */
      padding-bottom: var(--inset-bottom);
      border-width: 1px 0 0;
      border-radius: 24px 24px 0 0;
      /*
        A lit top edge, a shadow over the map above it, and a skirt of its own
        surface under its foot, for the give past full height.
      */
      box-shadow:
        inset 0 1px 0 rgb(255 255 255 / 0.05),
        0 -12px 40px rgb(0 0 0 / 0.55),
        0 40px 0 0 var(--surface-1);
      /* Off the foot of the screen until the sheet takes over, and rises. */
      transform: translate3d(0, 100%, 0);
      transition: transform 420ms cubic-bezier(0.32, 0.72, 0, 1);
      animation: none;
      /* Every drag on it is the sheet's; only its content at full height scrolls. */
      touch-action: none;
      will-change: transform;
    }

    /*
      What runs on below the fold fades into the sheet at the foot of the
      screen, over the home indicator's room: held there against the sheet's
      own move, gliding as it glides.
    */
    .detail::after {
      position: absolute;
      right: 0;
      bottom: 0;
      left: 0;
      z-index: 1;
      height: calc(24px + var(--inset-bottom));
      pointer-events: none;
      content: '';
      background: linear-gradient(transparent, var(--surface-1) 24px);
      transform: translate3d(0, calc(-1 * var(--sheet-offset, 0px)), 0);
      transition: transform 420ms cubic-bezier(0.32, 0.72, 0, 1);
    }

    .detail:global([data-dragging]),
    .detail:global([data-dragging])::after {
      transition: none;
    }

    /*
      The grip: a short pill at the top edge, in a target a thumb finds, over
      the sheet's own top padding.
    */
    .grip {
      position: absolute;
      top: 0;
      left: 50%;
      z-index: 1;
      display: block;
      width: 120px;
      height: 36px;
      margin: 0 0 0 -60px;
      padding: 0;
      cursor: grab;
      touch-action: none;
      background: transparent;
      border: 0;
      border-radius: 0 0 18px 18px;
    }

    .grip::before {
      position: absolute;
      top: 8px;
      left: 50%;
      width: 36px;
      height: 5px;
      margin-left: -18px;
      content: '';
      background: var(--text-3);
      border-radius: 3px;
      opacity: 0.72;
      transition: opacity 120ms linear;
    }

    .grip:hover::before,
    .grip:focus-visible::before {
      opacity: 1;
    }

    .grip:focus-visible {
      outline: none;
      box-shadow: inset 0 0 0 1px var(--text-3);
    }

    .detail:global([data-dragging]) .grip {
      cursor: grabbing;
    }

    .body {
      height: 100%;
      padding: 28px calc(var(--inset-right) + 16px) 24px calc(var(--inset-left) + 16px);
      overflow: hidden;
      touch-action: none;
    }

    .detail:global([data-detent='full']) .body {
      overflow-y: auto;
      touch-action: pan-y;
    }

    /*
      A phone's own header: what the school is on a chip, its name a step
      larger (the title on a phone), then where it is; and after the answer,
      the two buttons as pills. The chip, the pills and the close button are
      one family: the same fill, border and round ends.
    */
    .detail {
      --type-title: 600 24px / 29px var(--font-sans);
    }

    /* The name drags the sheet even at full height. */
    .head {
      padding-right: 48px;
      touch-action: none;
    }

    .kind {
      width: fit-content;
      max-width: 100%;
      margin-bottom: 8px;
      padding: 3px 10px;
      font-weight: 600;
      color: var(--text-1);
      background: var(--surface-2);
      border: 1px solid var(--border-2);
      border-radius: 999px;
    }

    .place {
      margin-top: 4px;
    }

    /* The answer first, a thumb's reach under the name; the buttons after it, a section of their own. */
    .actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      order: 1;
      margin: var(--section) 0 0;
      padding-top: var(--section);
      border-top: 1px solid var(--border-1);
    }

    .facts,
    .nearby {
      order: 2;
    }

    .action {
      justify-content: center;
      height: 44px;
      padding: 0 16px;
      background: var(--surface-2);
      border: 1px solid var(--border-2);
      border-radius: 999px;
      transition:
        background-color 120ms linear,
        border-color 120ms linear;
    }

    .action:hover {
      color: var(--text-1);
      background: var(--border-1);
      border-color: var(--text-3);
    }

    /* A phone number to tap: the whole row's height, not just its line. */
    .facts a {
      display: block;
      margin: calc(var(--row) / -2) 0;
      padding: calc(var(--row) / 2) 0;
    }

    .close {
      top: -6px;
      right: -4px;
      width: 40px;
      height: 40px;
      background: var(--surface-2);
      border: 1px solid var(--border-2);
    }

    /* A thumb's target around the button. */
    .close::after {
      position: absolute;
      inset: -4px;
      content: '';
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .detail,
    .detail::after {
      animation: none;
      transition: none;
    }

    .close,
    .action {
      transition: none;
    }
  }
</style>
