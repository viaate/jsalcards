<script lang="ts">
  import type { NearbyView, SchoolView } from '../app/school';
  import { cardOffered } from '../app/share-offer';
  import { copy } from '../copy';
  import { shareCopy } from '../copy-share';
  import type { CardKind } from '../copy-share';
  import ChanceSection from './ChanceSection.svelte';
  import PanelShell from './PanelShell.svelte';
  import { COPIED_MS } from './share';
  import type * as ShareCards from './share-cards';
  import type { CardSharer, ShareOutcome } from './share-cards';

  interface Props {
    view: SchoolView;
    /** Whether this school is the pinned one ("My school"). */
    pinned: boolean;
    onclose: () => void;
    onpin: () => void;
    /**
     * The link to the school (`?school=ID`), for Copy link and the share cards; none while the
     * page cannot write a link yet: the panel has no Share then.
     */
    link?: (() => string | null) | undefined;
    /** Loads the share cards' code (ui/share-cards.ts), on the first press of Share. */
    loadCards?: () => Promise<typeof ShareCards>;
    /** Opens a school from the nearby list. */
    onnearby?: (school: NearbyView) => void;
    /** Back to the area whose list opened the school ("Back to 64112"), or none. */
    back?: { readonly label: string; readonly onback: () => void } | null;
    /** On a phone, the sheet came to rest at another height: the map's labels make room for it. */
    onsettle?: () => void;
    /** The panel's element, for the page to focus after a pick. */
    element?: HTMLElement | undefined;
  }

  let {
    view,
    pinned,
    onclose,
    onpin,
    link,
    loadCards = () => import('./share-cards'),
    onnearby = () => undefined,
    back = null,
    onsettle = () => undefined,
    element = $bindable(),
  }: Props = $props();

  /** The glyph's class for a status line's tone, as the legend draws each status. */
  const GLYPHS = {
    closed: 'is-closed',
    delayed: 'is-delayed',
    remote: 'is-remote',
    earlyDismissal: 'is-early-dismissal',
    open: 'is-open',
  } as const;

  /** A share that ended without the sheet, said on its button: the outcomes, and the link instead. */
  type Said = Exclude<ShareOutcome, 'shared' | 'cancelled'> | 'linkInstead';
  /** The school whose share options are open under the Share button, or null. */
  let sharingFor = $state<string | null>(null);
  /** The options are open, for the school the panel shows. */
  const sharing = $derived(sharingFor !== null && sharingFor === view.id);
  /** The share cards' code, once loaded (on the first press of Share). */
  let sharer = $state<CardSharer | null>(null);
  /** What the last card's share did, said on its button for a moment. */
  let shared = $state<{ id: string; kind: CardKind; outcome: Said } | null>(null);
  /** The feedback, for the school the panel shows. */
  const done = $derived(shared !== null && shared.id === view.id ? shared : null);
  let sharedTimer: ReturnType<typeof setTimeout> | undefined;
  /** A share under way: a second tap waits for it. */
  let busy = false;
  /** The school whose link was just copied, for a moment, or null. */
  let copiedFor = $state<string | null>(null);
  const copied = $derived(copiedFor !== null && copiedFor === view.id);
  let copiedTimer: ReturnType<typeof setTimeout> | undefined;
  /**
   * The device shares through a sheet for a thumb (a phone's): the link option opens it with
   * the link, as Share did before the cards, rather than copying it.
   */
  let sheet = $state(false);

  function hasSheet(): boolean {
    try {
      return (
        typeof navigator.share === 'function' && window.matchMedia('(pointer: coarse)').matches
      );
    } catch {
      return false;
    }
  }

  /** Copies the link to the school; whether it was copied. */
  async function writeLink(url: string): Promise<boolean> {
    try {
      await navigator.clipboard.writeText(url);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * The link option: on a phone, the share sheet with the link; elsewhere (or where the sheet
   * will not open) the link copied, and said so on its button for a moment.
   */
  async function shareLink(): Promise<void> {
    const url = link?.() ?? null;
    if (url === null) return;
    const id = view.id;
    if (hasSheet()) {
      try {
        await navigator.share({ title: view.name, url });
        return;
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        // A sheet that would not open: the link copied instead.
      }
    }
    if (!(await writeLink(url))) return;
    copiedFor = id;
    clearTimeout(copiedTimer);
    copiedTimer = setTimeout(() => {
      copiedFor = null;
    }, COPIED_MS);
  }

  /**
   * Cards for a school's current day, offered only where a tap makes one (app/share-offer.ts):
   * none while it loads, for a past day, with nothing to say of its day, or without a link;
   * once the cards' code is here, its own model decides too.
   */
  const cardable = $derived(
    link !== undefined && cardOffered(view) && (sharer === null || sharer.available()),
  );

  function toggleShare(): void {
    sharingFor = sharing ? null : view.id;
    shared = null;
    sheet = hasSheet();
    if (sharingFor === null || !cardable || link === undefined) return;
    if (sharer !== null) {
      sharer.prepare();
      return;
    }
    const linkOf = link;
    void loadCards()
      .then((cards) => {
        sharer = cards.createCardSharer({ view: () => view, url: linkOf });
        if (sharingFor !== null) sharer.prepare();
      })
      .catch(() => undefined);
  }

  // A panel that changes while its options are open (a newer file, the day turning): its cards
  // are made again, so a tap shares what it shows.
  $effect(() => {
    if (sharing && sharer !== null && view.share !== undefined) sharer.prepare();
  });

  $effect(() => () => {
    clearTimeout(sharedTimer);
    clearTimeout(copiedTimer);
  });

  async function shareCard(kind: CardKind): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      const id = view.id;
      let outcome: ShareOutcome | 'linkInstead';
      try {
        const cards = sharer ?? (link === undefined ? null : await loadAndMake(link));
        outcome = cards === null ? 'failed' : await cards.share(kind);
      } catch {
        outcome = 'failed';
      }
      if (outcome === 'failed') {
        // No image: the link copied in its place, and said so, never a tap that does nothing.
        const url = link?.() ?? null;
        outcome = url !== null && (await writeLink(url)) ? 'linkInstead' : 'failed';
      }
      if (outcome === 'shared' || outcome === 'cancelled') return;
      shared = { id, kind, outcome };
      clearTimeout(sharedTimer);
      sharedTimer = setTimeout(() => {
        shared = null;
      }, COPIED_MS);
    } finally {
      busy = false;
    }
  }

  async function loadAndMake(linkOf: () => string | null): Promise<CardSharer> {
    const cards = await loadCards();
    sharer ??= cards.createCardSharer({ view: () => view, url: linkOf });
    return sharer;
  }

  /** What a card's button says once its share has ended without the sheet. */
  const OUTCOME_WORDS = {
    saved: shareCopy.saved,
    imageSaved: shareCopy.imageSaved,
    linkInstead: shareCopy.linkInstead,
    failed: shareCopy.failed,
  } as const;

  /** A card's button's words: its kind, or what its share just did. */
  function cardLabel(kind: CardKind): string {
    if (done?.kind !== kind) return shareCopy[kind];
    return OUTCOME_WORDS[done.outcome];
  }
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
<PanelShell
  label={copy.detail.label}
  busy={view.loading}
  loading={view.loading && view.name === ''}
  shows={view.id}
  {onclose}
  {onsettle}
  bind:element
>
  {#snippet head()}
    {#if back !== null}
      <button class="back" type="button" onclick={back.onback}>
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M10 3.5L5.5 8l4.5 4.5" />
        </svg>
        {back.label}
      </button>
    {/if}
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
  {/snippet}

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
      {#if link !== undefined}
        <button
          class="action"
          class:is-on={sharing}
          type="button"
          aria-expanded={sharing}
          aria-controls="detail-share"
          onclick={toggleShare}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path d="M8 2.5v7.25M5.25 5.25L8 2.5l2.75 2.75" />
            <path d="M4.75 7.75h-.5v5.75h7.5V7.75h-.5" />
          </svg>
          {copy.actions.share}
        </button>
      {/if}
    </div>
    {#if sharing && link !== undefined}
      <!-- The share options: a Story card, a Post card (ui/share-cards.ts), and the link. -->
      <div class="share-options" id="detail-share" role="group" aria-label={shareCopy.options}>
        {#if cardable}
          {#each ['story', 'post'] as const as kind (kind)}
            <button
              class="option"
              class:is-done={done?.kind === kind && done.outcome !== 'failed'}
              type="button"
              data-card={kind}
              onclick={() => void shareCard(kind)}
            >
              <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                {#if done?.kind === kind && done.outcome !== 'failed'}
                  <path d="M3.5 8.5l3 3 6-6.5" />
                {:else if kind === 'story'}
                  <rect x="4.75" y="1.75" width="6.5" height="12.5" rx="1.5" />
                {:else}
                  <rect x="3" y="3" width="10" height="11" rx="1.5" />
                {/if}
              </svg>
              {cardLabel(kind)}
            </button>
          {/each}
        {/if}
        <button
          class="option"
          class:is-done={copied}
          type="button"
          data-link
          onclick={() => void shareLink()}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            {#if copied}
              <path d="M3.5 8.5l3 3 6-6.5" />
            {:else}
              <path d="M6.75 9.25l2.5-2.5" />
              <path
                d="M7.25 4.75l1-1a2.47 2.47 0 013.5 3.5l-1 1M8.75 11.25l-1 1a2.47 2.47 0 01-3.5-3.5l1-1"
              />
            {/if}
          </svg>
          {copied ? copy.share.copied : sheet ? shareCopy.shareLink : shareCopy.copyLink}
        </button>
      </div>
    {/if}
  {/if}

  {#if view.chance !== null}
    <!-- A chance to give: the section says the status, then the chance (ChanceSection.svelte). -->
    <ChanceSection chance={view.chance} />
  {:else if view.status.length > 0}
    <section class="block status" aria-label={copy.detail.status}>
      {#each view.status as line, n (n)}
        <div class="line">
          <p class="headline">
            {line.headline}<span
              class="glyph {GLYPHS[line.tone]}"
              class:is-later={line.later === true}
              aria-hidden="true"
            ></span>
          </p>
          {#if line.detail !== null}
            <p class="line-detail">{line.detail}</p>
          {/if}
          {#if line.note !== null}
            <p class="line-note">{line.note}</p>
          {/if}
          {#if line.said !== null}
            <p class="line-said">{line.said}</p>
          {/if}
        </div>
      {/each}
    </section>
  {/if}

  {#if view.season !== undefined && view.season !== null}
    <!-- The school's days this school year, as the season file counts them (data/season.ts). -->
    <p class="block season">{view.season}</p>
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
                  <span class="sr-only">{copy.status[school.tone]}</span>
                {/if}
              </span>
            </button>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
</PanelShell>

<style>
  /*
    A school's panel, in the panels' shell (PanelShell.svelte): its type scale,
    grid and spacing are the shell's.
  */
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

  /* The season line: one plain sentence in the panel's secondary gray. */
  .season {
    font: var(--type-small);
    color: var(--text-2);
    text-wrap: pretty;
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

  /* What the school is, then its name, the one heading, then where it is. */
  .kind {
    margin-bottom: 4px;
    font: var(--type-small);
    color: var(--text-2);
  }

  /* Back to the area its list opened the school from: words with their mark, over the rest. */
  .back {
    display: flex;
    gap: 4px;
    align-items: center;
    height: 32px;
    margin: -6px 0 4px;
    padding: 0;
    font: var(--type-body);
    color: var(--text-2);
    cursor: pointer;
    background: transparent;
    border: 0;
    border-radius: 4px;
    transition: color 120ms linear;
  }

  .back:hover {
    color: var(--text-1);
  }

  /* The mark's ink at the panel's left edge, where every line starts. */
  .back svg {
    flex: none;
    width: 16px;
    height: 16px;
    margin-left: -5px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
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

  .back:focus-visible,
  .action:focus-visible,
  .facts a:focus-visible {
    outline: 1px solid var(--text-2);
    outline-offset: 2px;
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

  /* The share options under the buttons: words with their marks, as the buttons are. */
  .share-options {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 24px;
    margin: 4px 0 -5px;
  }

  .option {
    display: flex;
    gap: 8px;
    align-items: center;
    height: 32px;
    padding: 0;
    font: var(--type-body);
    color: var(--text-2);
    white-space: nowrap;
    cursor: pointer;
    background: transparent;
    border: 0;
    border-radius: 4px;
    transition: color 120ms linear;
  }

  .option:hover,
  .option.is-done {
    color: var(--text-1);
  }

  .option:focus-visible {
    outline: 1px solid var(--text-2);
    outline-offset: 2px;
  }

  .option svg {
    flex: none;
    width: 16px;
    height: 16px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.4;
    stroke-linecap: round;
    stroke-linejoin: round;
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

  /*
    A later day's line (the map's later-day ring, map/later-rings.ts): the
    ring as the map draws it, thin and dashed in the second gray with no
    glow, around a small, see-through mark of its status. Here and in the
    chance section's status lines (ChanceSection.svelte), which it holds.
  */
  :global(.headline .glyph.is-later) {
    position: relative;
    box-sizing: border-box;
    width: 11px;
    height: 11px;
    margin: -1.5px;
    background: none;
    border: 1px dashed var(--text-2);
    border-radius: 50%;
    box-shadow: none;
    transform: none;
  }

  :global(.headline .glyph.is-later)::after {
    position: absolute;
    inset: 2.5px;
    content: '';
    border-radius: 50%;
    opacity: 0.7;
  }

  :global(.headline .glyph.is-later.is-closed)::after {
    background: var(--status-closed);
  }

  :global(.headline .glyph.is-later.is-delayed)::after {
    box-shadow: inset 0 0 0 1px var(--status-delayed);
  }

  :global(.headline .glyph.is-later.is-remote)::after {
    inset: 3px;
    background: var(--status-remote);
    border-radius: 0.5px;
    transform: rotate(45deg);
  }

  :global(.headline .glyph.is-later.is-early-dismissal)::after {
    background: linear-gradient(90deg, var(--status-early-dismissal) 50%, transparent 50%);
    box-shadow: inset 0 0 0 1px var(--status-early-dismissal);
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

  /*
    How far: within the label column, as every row's label is. A distance in
    miles never breaks (copy-format.ts joins it with a no-break space); words
    wider than the column ("Same place") wrap at their space, never into the
    name beside them.
  */
  .near-distance {
    min-width: 0;
    overflow-wrap: normal;
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

  /* A phone: the panel is a sheet (PanelShell.svelte). */
  @media (max-width: 719px) {
    /*
      A phone's own header: what the school is on a chip, its name a step
      larger (the title on a phone), then where it is; and after the answer,
      the two buttons as pills. The chip, the pills and the shell's close
      button are one family: the same fill, border and round ends.
    */
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

    /* The options after the buttons, as pills of their own in a row. */
    .share-options {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(0, 1fr));
      gap: 8px;
      order: 1;
      margin: 8px 0 0;
    }

    .option {
      justify-content: center;
      height: 44px;
      padding: 0 12px;
      color: var(--text-1);
      background: var(--surface-1);
      border: 1px solid var(--border-2);
      border-radius: 999px;
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
  }

  @media (prefers-reduced-motion: reduce) {
    .back,
    .action,
    .option {
      transition: none;
    }
  }
</style>
