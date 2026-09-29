<script lang="ts">
  import { onMount, tick } from 'svelte';

  import type { MenuSection, MenuView, RecordTable } from '../app/menu';
  import { STATUS_KEYS, copy } from '../copy';
  import { format } from '../copy-format';
  import type { StatusKey } from '../copy';
  import type { StatusCounts } from '../data/closings';
  import { SCHOOL_KINDS, withKind, withStatus } from '../state/filter';
  import type { MapFilter, SchoolKind } from '../state/filter';
  import type { Status } from '../types/generated';

  interface Props {
    /** What the published files give: the season, the track record, what the map holds. */
    view: MenuView;
    /** The panel's id, which the menu button names as what it opens. */
    id: string;
    /** What the map shows now: all four statuses or one, and which schools. */
    filter: MapFilter;
    /**
     * How many schools the map lights in each status today, of the kinds it
     * shows; null while none is lit, and then no count is given.
     */
    counts?: StatusCounts | null;
    /** The button that opens and closes it: a press on it is the button's, not a press elsewhere. */
    button?: HTMLElement | undefined;
    /** Asks the page to show what the menu now picks. */
    onfilter?: (filter: MapFilter) => void;
    /**
     * Asks the page to close the menu: on Escape, or a press anywhere else.
     * `refocus` says the keyboard was in the menu and goes back to its button.
     */
    onclose?: (refocus: boolean) => void;
  }

  let {
    view,
    id,
    filter,
    counts = null,
    button,
    onfilter = () => undefined,
    onclose = () => undefined,
  }: Props = $props();

  let element = $state<HTMLElement>();

  /** The page shown: the list, or one of the pages it opens. */
  type Page = 'list' | 'season' | 'record' | 'about';
  let page = $state<Page>('list');

  /** Whether the keyboard is in the menu (or nowhere, as after a press inside it). */
  function holdsFocus(): boolean {
    const active = document.activeElement;
    return active === null || active === document.body || element?.contains(active) === true;
  }

  /**
   * Open, it takes focus, so the keyboard and a screen reader start in it.
   * Escape closes it, before anything else Escape does on the page (closing a
   * school), and so does a press anywhere else (the map, the key, the field)
   * or the keyboard going anywhere else (the search field, by its "/" key).
   */
  onMount(() => {
    element?.focus({ preventScroll: true });
    const onKey = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape' || event.defaultPrevented || event.isComposing) return;
      event.preventDefault();
      onclose(holdsFocus());
    };
    const onElsewhere = (event: Event): void => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (element?.contains(target) === true || button?.contains(target) === true) return;
      onclose(false);
    };
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('pointerdown', onElsewhere, true);
    window.addEventListener('focusin', onElsewhere, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      window.removeEventListener('pointerdown', onElsewhere, true);
      window.removeEventListener('focusin', onElsewhere, true);
    };
  });

  /** The legend's mark for each status, by code. */
  const GLYPHS = ['is-closed', 'is-delayed', 'is-remote', 'is-early-dismissal'] as const;

  /** The mark of each status a season row counts. */
  const TONES: Readonly<Record<StatusKey, string>> = {
    closed: 'is-closed',
    delayed: 'is-delayed',
    remote: 'is-remote',
    earlyDismissal: 'is-early-dismissal',
  };

  /** A status's count today, written out; empty with none to give. */
  function countOf(code: number): string {
    const n = counts?.[code] ?? 0;
    return n > 0 ? format.number(n) : '';
  }

  const total = $derived(counts === null ? 0 : counts.reduce((sum, n) => sum + n, 0));

  /** The pages the list opens, each only when its file has something to show. */
  const pages = $derived(
    [
      view.season === null ? null : ('season' as const),
      view.record === null ? null : ('record' as const),
      'about' as const,
    ].filter((item) => item !== null),
  );

  const TITLES: Readonly<Record<Exclude<Page, 'list'>, string>> = {
    season: copy.nav.seasonStats,
    record: copy.nav.trackRecord,
    about: copy.nav.about,
  };

  /** Opens a page of the menu, or goes back to its list; the keyboard follows. */
  async function go(next: Page): Promise<void> {
    const from = page;
    page = next;
    await tick();
    const target =
      next === 'list'
        ? element?.querySelector<HTMLElement>(`[data-page="${from}"]`)
        : element?.querySelector<HTMLElement>('.back');
    target?.focus({ preventScroll: true });
  }

  function pickStatus(status: Status | null): void {
    onfilter(withStatus(filter, status));
  }

  function showKind(kind: SchoolKind, shown: boolean): void {
    onfilter(withKind(filter, kind, shown));
  }

  /** The season's rows, or the map's, on a page of their own. */
  const pageRows = $derived.by((): MenuSection | null => {
    if (page === 'season') return view.season;
    if (page === 'about') return view.map;
    return null;
  });
  const record = $derived<RecordTable | null>(page === 'record' ? view.record : null);
</script>

<!--
  The menu, opened from the button beside the search field, under the field
  and lined up with it. A list of what it sets and opens, each row an icon
  and its name, the one in use on a filled pill:

  - Today: which of today's lights the map shows, all four statuses or one,
    each with the legend's mark and, once schools are lit, how many.
  - Schools: public schools, private schools, or both.
  - The season so far and the track record, each only once its published
    file has something to count, and About: each opens a page of its own in
    the panel, its name beside the way back to the list. The season's page
    gives the season it counts under its name; About gives what the site is,
    how to read its lights, and what the map holds.

  Nothing here is made up, and nothing says it has nothing to show.
-->
<aside class="menu" {id} aria-label={copy.menu.label} tabindex="-1" bind:this={element}>
  <div class="body">
    {#if page === 'list'}
      <div class="group" role="radiogroup" aria-labelledby="{id}-today">
        <h2 class="label" id="{id}-today">{copy.menu.today}</h2>
        <label class="item" class:is-on={filter.status === null}>
          <input
            class="control"
            type="radio"
            name="{id}-status"
            checked={filter.status === null}
            onchange={() => {
              pickStatus(null);
            }}
          />
          <svg class="icon all" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <circle class="is-closed" cx="4.75" cy="4.75" r="2.5" />
            <circle class="is-delayed" cx="11.25" cy="4.75" r="2.5" />
            <circle class="is-remote" cx="4.75" cy="11.25" r="2.5" />
            <circle class="is-early-dismissal" cx="11.25" cy="11.25" r="2.5" />
          </svg>
          <span class="name">{copy.menu.all}</span>
          <span class="value">{total > 0 ? format.number(total) : ''}</span>
        </label>
        {#each STATUS_KEYS as key, code (key)}
          <label class="item" class:is-on={filter.status === code}>
            <input
              class="control"
              type="radio"
              name="{id}-status"
              checked={filter.status === code}
              onchange={() => {
                pickStatus(code as Status);
              }}
            />
            <span class="icon" aria-hidden="true"><span class="glyph {GLYPHS[code]}"></span></span>
            <span class="name">{copy.status[key]}</span>
            <span class="value">{countOf(code)}</span>
          </label>
        {/each}
      </div>

      <div class="group" role="group" aria-labelledby="{id}-kinds">
        <h2 class="label" id="{id}-kinds">{copy.menu.kinds}</h2>
        {#each SCHOOL_KINDS as kind (kind)}
          <label class="item check" class:is-off={!filter[kind]}>
            <input
              class="control"
              type="checkbox"
              checked={filter[kind]}
              onchange={(event) => {
                showKind(kind, event.currentTarget.checked);
              }}
            />
            <svg class="icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
              <path class="tick" d="M3.25 8.5l3.1 3 6.4-7" />
            </svg>
            <span class="name">{copy.menu[kind]}</span>
          </label>
        {/each}
      </div>

      <div class="group">
        {#each pages as item (item)}
          <button
            class="item"
            type="button"
            data-page={item}
            onclick={() => {
              void go(item);
            }}
          >
            <svg class="icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
              {#if item === 'season'}
                <path d="M3.25 13.25v-4M8 13.25v-10M12.75 13.25v-6.5" />
              {:else if item === 'record'}
                <circle cx="8" cy="8" r="5.75" />
                <circle cx="8" cy="8" r="2.25" />
              {:else}
                <circle cx="8" cy="8" r="6" />
                <path d="M8 7.25v3.75" />
                <circle class="point" cx="8" cy="4.9" r="0.4" />
              {/if}
            </svg>
            <span class="name">{TITLES[item]}</span>
            <svg class="more" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
              <path d="M6.25 3.75L10.5 8l-4.25 4.25" />
            </svg>
          </button>
        {/each}
      </div>
    {:else}
      <section class="group page" aria-labelledby="{id}-page">
        <button
          class="item back"
          type="button"
          aria-label={copy.detail.back}
          onclick={() => {
            void go('list');
          }}
        >
          <svg class="icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path d="M9.75 3.75L5.5 8l4.25 4.25" />
          </svg>
          <span class="name title" id="{id}-page">{TITLES[page]}</span>
        </button>

        {#if page === 'about'}
          <p class="line lead">{copy.about.what}</p>
          <p class="line text">{copy.about.glow}</p>
        {/if}

        {#if pageRows !== null}
          {@const label = page === 'season' ? pageRows.note : pageRows.title}
          {#if label !== null}
            <p class="line note" class:is-apart={page === 'about'}>{label}</p>
          {/if}
          <dl class="rows">
            {#each pageRows.rows as row (row.label)}
              <div class="row">
                <dt>
                  <span class="icon" aria-hidden="true">
                    {#if row.tone !== null}<span class="glyph {TONES[row.tone]}"></span>{/if}
                  </span>
                  {row.label}
                </dt>
                <dd>{row.value}</dd>
              </div>
            {/each}
          </dl>
        {/if}

        {#if record !== null}
          <p class="line note">{record.note}</p>
          <table class="record">
            <caption class="line caption">{record.caption}</caption>
            <thead>
              <tr>
                {#each record.columns as column, n (n)}
                  <th scope="col">{column}</th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each record.rows as row (row.label)}
                <tr>
                  <th scope="row">{row.label}</th>
                  {#each row.cells as cell, n (n)}
                    <td>
                      {#if cell !== null}{cell}{/if}
                    </td>
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </section>
    {/if}
  </div>
</aside>

<style>
  /*
    Under the search field, its left edge on the field's: a solid card like
    the field and the results list (no backdrop blur over the moving WebGL
    map). What does not fit scrolls inside it.
  */
  .menu {
    position: absolute;
    top: calc(var(--inset-top) + var(--edge) + var(--bar-height) + 8px);
    left: calc(var(--inset-left) + var(--edge) + var(--brand-width) + var(--brand-gap));
    z-index: 2;
    display: flex;
    flex-direction: column;
    width: 288px;
    max-height: calc(
      100dvh - var(--inset-top) - var(--inset-bottom) - 2 * var(--edge) - var(--bar-height) - 8px -
        var(--control-height) - 16px
    );
    overflow: hidden;
    background: var(--surface-1);
    border: 1px solid var(--border-2);
    border-radius: 16px;
    outline: none;
    box-shadow:
      inset 0 1px 0 rgb(255 255 255 / 0.04),
      0 0 0 1px var(--bg),
      0 16px 40px rgb(0 0 0 / 0.6);
    animation: arrive 180ms cubic-bezier(0.2, 0.7, 0.2, 1) both;
  }

  @keyframes arrive {
    from {
      opacity: 0;
      transform: translateY(-4px);
    }
  }

  /*
    One grid for every row: a 16px icon column and one text column after it,
    12px apart, each row's value or arrow at its right end. Rows sit 8px in
    from the panel's edge, so the pill around the one in use is inset like
    the search field's results.
  */
  .body {
    --row: 40px;
    --line: 20px;
    --pad: 12px;

    display: flex;
    flex: 1 1 auto;
    flex-direction: column;
    min-height: 0;
    padding: 8px;
    overflow-y: auto;
    overscroll-behavior: contain;
    scrollbar-width: thin;
    scrollbar-color: var(--border-2) transparent;
  }

  .group {
    display: flex;
    flex-direction: column;
    margin: 0;
  }

  /* Groups parted by a hairline across the text's width and the same space either side of it. */
  .group + .group {
    position: relative;
    margin-top: 8px;
    padding-top: 8px;
  }

  .group + .group::before {
    position: absolute;
    top: 0;
    right: var(--pad);
    left: var(--pad);
    height: 1px;
    content: '';
    background: var(--border-1);
  }

  /* Each group's heading: small capitals over the icon column, set apart by their shape. */
  .label,
  .note,
  .record thead th {
    margin: 0;
    font-size: 11px;
    font-weight: 500;
    line-height: 16px;
    letter-spacing: 0.06em;
    color: var(--text-2);
    text-transform: uppercase;
  }

  .label {
    padding: 8px var(--pad) 4px;
  }

  /* A row: a control, its icon and name, and what it counts at the right. */
  .item {
    position: relative;
    display: grid;
    grid-template-columns: 16px minmax(0, 1fr) auto;
    column-gap: 12px;
    align-items: center;
    width: 100%;
    min-height: var(--row);
    margin: 0;
    padding: 0 var(--pad);
    font: inherit;
    font-size: 14px;
    line-height: 20px;
    color: var(--text-1);
    text-align: left;
    cursor: pointer;
    user-select: none;
    background: transparent;
    border: 0;
    border-radius: calc(var(--row) / 2);
    outline: none;
    transition: background-color 120ms linear;
  }

  /* The one in use: a filled pill, its name a step heavier. */
  .item.is-on {
    background: var(--border-2);
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 0.05);
  }

  .item.is-on .name {
    font-weight: 500;
  }

  @media (hover: hover) {
    .item:not(.is-on):hover {
      background: var(--surface-2);
    }
  }

  .item:focus-visible,
  .item:has(.control:focus-visible) {
    box-shadow: inset 0 0 0 1px var(--text-3);
  }

  /* The radio or checkbox itself: there for the keyboard and a screen reader, drawn by its row. */
  .control {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: 0;
    opacity: 0;
    pointer-events: none;
  }

  .icon {
    display: grid;
    place-items: center;
    width: 16px;
    height: 16px;
    fill: none;
    stroke: var(--text-2);
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .item.is-on .icon,
  .item:hover .icon {
    stroke: var(--text-1);
  }

  .icon .point {
    fill: var(--text-2);
  }

  .item:hover .icon .point {
    fill: var(--text-1);
  }

  /* All four statuses: their four colors, one in each corner. */
  .all circle {
    stroke: none;
  }

  .all .is-closed {
    fill: var(--status-closed);
  }

  .all .is-delayed {
    fill: var(--status-delayed);
  }

  .all .is-remote {
    fill: var(--status-remote);
  }

  .all .is-early-dismissal {
    fill: var(--status-early-dismissal);
  }

  /* Each status's mark as the legend draws it, a size up in its 16px square. */
  .icon .glyph {
    width: 10px;
    height: 10px;
  }

  .icon .glyph.is-remote {
    width: 8px;
    height: 8px;
  }

  /* A kind of school shown has its tick; one not shown has none, and its name steps back. */
  .check .tick {
    stroke: var(--text-1);
    stroke-width: 1.75;
  }

  .check.is-off .tick {
    visibility: hidden;
  }

  .check.is-off .name {
    color: var(--text-2);
  }

  .name {
    min-width: 0;
    margin: 0;
    font-size: inherit;
    font-weight: 400;
    line-height: inherit;
    overflow-wrap: break-word;
  }

  /* How many, at the row's right end, in the numbers' own column. */
  .value {
    min-width: 0;
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
    text-align: right;
  }

  .value:empty {
    display: none;
  }

  .more {
    width: 16px;
    height: 16px;
    fill: none;
    stroke: var(--text-3);
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .item:hover .more {
    stroke: var(--text-2);
  }

  /* A page of the menu: its name beside the way back, then its lines and rows. */
  .page .back {
    grid-template-columns: 16px minmax(0, 1fr);
  }

  .title {
    font-weight: 500;
  }

  /* A line of words on a page: in the text column, like every name above it. */
  .line {
    margin: 0;
    padding: 0 var(--pad) 0 calc(var(--pad) + 28px);
    font-size: 14px;
    line-height: 20px;
    color: var(--text-1);
    text-wrap: pretty;
  }

  .back + .line {
    margin-top: 4px;
  }

  .lead + .text {
    margin-top: 4px;
    color: var(--text-2);
  }

  .line.note {
    margin-top: 4px;
    font-size: 11px;
    line-height: 16px;
    color: var(--text-2);
  }

  /* What the map holds, under About's two lines: a part of its own, a line's height below them. */
  .line.note.is-apart {
    margin-top: 20px;
  }

  /*
    Rows on a page: the season's, the map's. One row style, a status's mark
    in the icon column, a label in the text column and its value at the
    right, each row the same height, parted by hairlines across the text.
  */
  .rows {
    margin: 8px 0 0;
    padding: 0;
    font-size: 14px;
    line-height: 20px;
    font-variant-numeric: tabular-nums;
  }

  .row {
    position: relative;
    display: flex;
    flex-wrap: wrap;
    column-gap: 12px;
    align-items: center;
    min-height: var(--row);
    padding: calc((var(--row) - var(--line)) / 2) var(--pad);
  }

  .row + .row::before {
    position: absolute;
    top: 0;
    right: var(--pad);
    left: calc(var(--pad) + 28px);
    height: 1px;
    content: '';
    background: var(--border-1);
  }

  dt,
  .record tbody th {
    min-width: 0;
    padding: 0;
    font-weight: 400;
    color: var(--text-2);
    text-align: left;
  }

  /* The mark in the icon column, the label in the text column. */
  dt {
    display: grid;
    flex: none;
    grid-template-columns: 16px auto;
    column-gap: 12px;
    align-items: center;
    white-space: nowrap;
  }

  dd,
  .record td {
    min-width: 0;
    margin: 0;
    padding: 0;
    font-weight: 500;
    color: var(--text-1);
    text-align: right;
    overflow-wrap: break-word;
  }

  /* A value too long to sit beside its label (the busiest day) goes under it, still at the right. */
  dd {
    flex: 0 1 auto;
    margin-left: auto;
  }

  /*
    The track record: a table in the rows' style, in the text column: the
    chance given at the left, then a column for each lead, its counts ending
    at the right.
  */
  .record {
    width: calc(100% - 2 * var(--pad) - 28px);
    margin: 4px var(--pad) 0 calc(var(--pad) + 28px);
    font-size: 14px;
    line-height: 20px;
    font-variant-numeric: tabular-nums;
    border-collapse: collapse;
  }

  .record th,
  .record td {
    height: var(--row);
    padding: 0;
    vertical-align: middle;
  }

  .record th + th,
  .record th + td,
  .record td + td {
    padding-left: 12px;
  }

  .record thead th {
    height: auto;
    padding-top: 8px;
    padding-bottom: 4px;
    text-align: left;
    vertical-align: bottom;
  }

  .record thead th + th {
    text-align: right;
  }

  .record tbody tr + tr > * {
    border-top: 1px solid var(--border-1);
  }

  .caption {
    padding: 4px 0 0;
    color: var(--text-2);
    text-align: left;
  }

  /*
    A phone: under the search field, as wide as it, and down to the foot of the
    screen at most; the search results, when open, go over it. Each row a
    thumb's height.
  */
  @media (max-width: 719px) {
    .menu {
      top: calc(var(--inset-top) + var(--edge) + var(--brand-stack) + var(--bar-height) + 8px);
      right: calc(var(--inset-right) + var(--edge));
      left: calc(var(--inset-left) + var(--edge));
      width: auto;
      max-height: calc(
        100dvh - var(--inset-top) - var(--inset-bottom) - 2 * var(--edge) - var(--brand-stack) -
          var(--bar-height) - 8px
      );
    }

    .body {
      --row: 44px;
      --line: 22px;
    }

    .item,
    .line:not(.note),
    .rows,
    .record {
      font-size: 15px;
      line-height: 22px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .menu {
      animation: none;
    }

    .item {
      transition: none;
    }
  }
</style>
