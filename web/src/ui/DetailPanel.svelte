<script lang="ts">
  import type { NearbyView, SchoolView } from '../app/school';
  import { copy } from '../copy';

  interface Props {
    view: SchoolView;
    /** Whether this school is the pinned one ("My school"). */
    pinned: boolean;
    /** True for a moment after the link was copied. */
    copied: boolean;
    onclose: () => void;
    onpin: () => void;
    onshare: () => void;
    /** Opens a school from the nearby list. */
    onnearby?: (school: NearbyView) => void;
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

  /** The outlook's days, or null for "not enough data" (or no outlook at all). */
  const outlookDays = $derived(
    view.outlook === null || view.outlook === 'not_enough_data' ? null : view.outlook,
  );
</script>

<!--
  A school's detail panel: where a search pick or a link to a school lands.
  What it answers first is the school's day, when the live files state it;
  then the chance of a weather closure, when the district's history gives
  one; then what the directory says about the school. Beside the map on a
  wide screen, a sheet over its foot on a phone. Every line comes from the
  view (app/school.ts); nothing here is made up or filled in.
-->
<aside
  class="detail"
  class:is-loading={view.loading && view.name === ''}
  aria-label={copy.detail.label}
  aria-busy={view.loading}
  tabindex="-1"
  bind:this={element}
>
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
      {/if}
      <h2 class="name">
        {view.name}{#if view.campus !== null}<span class="campus">{view.campus}</span>{/if}
      </h2>
      {#if view.place !== null}
        <p class="place">{view.place}</p>
      {/if}
    {/if}
    <button class="close" type="button" aria-label={copy.detail.close} onclick={onclose}>
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
    </div>
  {/if}

  {#if view.status.length > 0}
    <section class="card status" aria-label={copy.detail.status}>
      {#each view.status as line, n (n)}
        <div class="line">
          <span class="glyph {GLYPHS[line.tone]}" aria-hidden="true"></span>
          <div class="line-text">
            <p class="headline">{line.headline}</p>
            {#if line.detail !== null}
              <p class="line-detail">{line.detail}</p>
            {/if}
            {#if line.note !== null}
              <p class="line-note">{line.note}</p>
            {/if}
          </div>
        </div>
      {/each}
    </section>
  {/if}

  {#if view.outlook !== null}
    <section class="card outlook" aria-labelledby="detail-outlook">
      <h3 class="card-title" id="detail-outlook">{copy.predictions.title}</h3>
      {#if outlookDays === null}
        <p class="quiet">{copy.empty.notEnoughData}</p>
      {:else}
        <div class="days">
          {#each outlookDays as day (day.label)}
            <div class="day">
              <p class="day-label">{day.label}</p>
              {#if day.chance !== null}
                <p class="chance">{day.chance}</p>
                <p class="day-line">{day.line}</p>
                <span class="meter" aria-hidden="true">
                  <span class="meter-fill" style:transform="scaleX({day.share ?? 0})"></span>
                </span>
                {#if day.delay !== null}
                  <p class="day-more">{day.delay}</p>
                {/if}
                {#if day.reasons !== null}
                  <p class="day-more">{day.reasons}</p>
                {/if}
              {:else}
                <p class="day-line is-plain">{day.line}</p>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </section>
  {/if}

  {#if view.facts.length > 0}
    <dl class="facts">
      {#each view.facts as fact (fact.label)}
        <div class="fact">
          <dt>{fact.label}</dt>
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
    <section class="nearby" aria-labelledby="detail-nearby">
      <h3 class="card-title" id="detail-nearby">{copy.detail.nearby}</h3>
      <ul class="near-list">
        {#each view.nearby as school (school.id)}
          <li>
            <button
              class="near"
              type="button"
              onclick={() => {
                onnearby(school);
              }}
            >
              <span
                class="near-dot {school.tone === null ? '' : `glyph ${GLYPHS[school.tone]}`}"
                aria-hidden="true"
              ></span>
              <span class="near-name">{school.name}</span>
              <span class="near-distance">{school.distance}</span>
            </button>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
</aside>

<style>
  /*
    Beside the map, under the wordmark, clear of the legend at the foot of the
    screen: a solid card like the search results (no backdrop blur over the
    moving WebGL map). What does not fit scrolls inside it.
  */
  .detail {
    position: absolute;
    top: calc(var(--inset-top) + var(--edge) + var(--bar-height) + 16px);
    left: calc(var(--inset-left) + var(--edge));
    z-index: 2;
    display: flex;
    flex-direction: column;
    gap: 16px;
    width: 368px;
    max-height: calc(
      100dvh - var(--inset-top) - var(--inset-bottom) - 2 * var(--edge) - var(--bar-height) - 16px -
        var(--control-height) - 16px
    );
    padding: 20px;
    overflow-y: auto;
    overscroll-behavior: contain;
    scrollbar-width: thin;
    scrollbar-color: var(--border-2) transparent;
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

  @keyframes arrive {
    from {
      opacity: 0;
      transform: translateY(6px);
    }
  }

  /* The school's name, what it is and where: the one heading, then two quiet lines. */
  .head {
    position: relative;
    padding-right: 40px;
  }

  .kind {
    margin: 0 0 6px;
    font-size: 12px;
    font-weight: 500;
    line-height: 16px;
    letter-spacing: 0.01em;
    color: var(--text-2);
  }

  .name {
    margin: 0;
    font-size: 22px;
    font-weight: 600;
    line-height: 27px;
    letter-spacing: -0.02em;
    color: var(--text-1);
    text-wrap: balance;
    overflow-wrap: break-word;
  }

  /* A campus on a line of its own, a step down, as the map's label sets it. */
  .campus {
    display: block;
    margin-top: 2px;
    font-size: 16px;
    font-weight: 500;
    line-height: 21px;
    letter-spacing: -0.01em;
    color: var(--text-2);
  }

  .place {
    margin: 8px 0 0;
    font-size: 13px;
    line-height: 18px;
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
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: 50%;
    transition:
      color 120ms linear,
      border-color 120ms linear;
  }

  .close:hover,
  .close:focus-visible {
    color: var(--text-1);
    border-color: var(--text-3);
  }

  .close:focus-visible,
  .action:focus-visible,
  .facts a:focus-visible {
    outline: 1px solid var(--text-2);
    outline-offset: 2px;
  }

  .close svg {
    width: 14px;
    height: 14px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
  }

  /* Pin and share, side by side under the name. */
  .actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .action {
    display: flex;
    gap: 8px;
    align-items: center;
    justify-content: center;
    min-width: 0;
    height: 36px;
    padding: 0 12px;
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    line-height: 16px;
    color: var(--text-1);
    white-space: nowrap;
    cursor: pointer;
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: 18px;
    transition:
      background-color 120ms linear,
      border-color 120ms linear;
  }

  .action:hover {
    background: var(--border-1);
    border-color: var(--text-3);
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

  /* A card within the panel: the day's status, and the chance of a closure. */
  .card {
    margin: 0;
    padding: 14px 16px;
    background: var(--surface-2);
    border: 1px solid var(--border-1);
    border-radius: 12px;
  }

  .card-title {
    margin: 0;
    font-size: 12px;
    font-weight: 500;
    line-height: 16px;
    letter-spacing: 0.01em;
    color: var(--text-2);
  }

  .quiet {
    margin: 6px 0 0;
    font-size: 14px;
    line-height: 20px;
    color: var(--text-1);
  }

  .status {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .line {
    display: grid;
    grid-template-columns: 12px minmax(0, 1fr);
    column-gap: 12px;
    align-items: start;
  }

  /* The legend's glyphs, a step larger, beside the line they key. */
  .line .glyph {
    width: 11px;
    height: 11px;
    margin-top: 6px;
  }

  .line .glyph.is-remote {
    width: 9px;
    height: 9px;
    margin: 7px 0 0 1px;
  }

  .glyph.is-open {
    box-shadow: inset 0 0 0 1.5px var(--text-2);
  }

  .headline {
    margin: 0;
    font-size: 17px;
    font-weight: 600;
    line-height: 23px;
    letter-spacing: -0.01em;
    color: var(--text-1);
  }

  .line-detail {
    margin: 2px 0 0;
    font-size: 14px;
    line-height: 20px;
    color: var(--text-1);
  }

  .line-note {
    margin: 2px 0 0;
    font-size: 13px;
    line-height: 18px;
    color: var(--text-2);
  }

  .days {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-top: 10px;
  }

  .day-label {
    margin: 0;
    font-size: 13px;
    font-weight: 500;
    line-height: 18px;
    color: var(--text-1);
  }

  .chance {
    margin: 4px 0 0;
    font-size: 28px;
    font-weight: 600;
    line-height: 32px;
    letter-spacing: -0.03em;
    color: var(--text-1);
  }

  .day-line {
    margin: 0;
    font-size: 12px;
    line-height: 16px;
    color: var(--text-2);
  }

  .day-line.is-plain {
    margin-top: 4px;
    font-size: 13px;
    line-height: 18px;
  }

  /* The chance as a share of a hairline track (not .bar: that is the page's top strip). */
  .meter {
    display: block;
    height: 3px;
    margin: 10px 0 8px;
    overflow: hidden;
    background: var(--border-2);
    border-radius: 2px;
  }

  .meter-fill {
    display: block;
    height: 100%;
    background: var(--text-1);
    border-radius: inherit;
    transform-origin: left center;
  }

  .day-more {
    margin: 2px 0 0;
    font-size: 12px;
    line-height: 16px;
    color: var(--text-2);
  }

  /* What the directory says about the school: a label and its value, on a hairline grid. */
  .facts {
    display: flex;
    flex-direction: column;
    margin: 0;
    border-top: 1px solid var(--border-1);
  }

  .fact {
    display: grid;
    grid-template-columns: 76px minmax(0, 1fr);
    column-gap: 12px;
    padding: 10px 0;
    border-bottom: 1px solid var(--border-1);
  }

  .fact:last-child {
    padding-bottom: 0;
    border-bottom: 0;
  }

  .fact dt {
    font-size: 13px;
    line-height: 19px;
    color: var(--text-2);
  }

  .fact dd {
    display: flex;
    flex-direction: column;
    min-width: 0;
    margin: 0;
    font-size: 13px;
    line-height: 19px;
    color: var(--text-1);
    overflow-wrap: break-word;
  }

  .facts a {
    color: inherit;
    text-decoration: none;
    border-radius: 2px;
  }

  .facts a:hover {
    text-decoration: underline;
    text-decoration-color: var(--text-3);
    text-underline-offset: 3px;
  }

  /* The schools nearest this one, each a row that opens it: a dot as the map draws it, its name, how far. */
  .nearby {
    margin: 0;
    padding-top: 14px;
    border-top: 1px solid var(--border-1);
  }

  .near-list {
    margin: 6px -8px 0;
    padding: 0;
    list-style: none;
  }

  .near {
    display: grid;
    grid-template-columns: 8px minmax(0, 1fr) auto;
    column-gap: 12px;
    align-items: center;
    width: 100%;
    min-height: 34px;
    padding: 6px 8px;
    font: inherit;
    font-size: 13px;
    line-height: 18px;
    color: var(--text-1);
    text-align: left;
    cursor: pointer;
    background: transparent;
    border: 0;
    border-radius: 8px;
  }

  .near:hover,
  .near:focus-visible {
    background: var(--surface-2);
    outline: none;
  }

  .near:focus-visible {
    box-shadow: inset 0 0 0 1px var(--text-3);
  }

  /* A school with no status today: a plain dot, as the map draws it. */
  .near-dot:not(.glyph) {
    width: 6px;
    height: 6px;
    margin-left: 1px;
    background: var(--text-2);
    border-radius: 50%;
  }

  /* A school with a status today: the legend's glyph for it. */
  .near-dot.glyph.is-remote {
    width: 7px;
    height: 7px;
  }

  .near-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .near-distance {
    color: var(--text-2);
    white-space: nowrap;
  }

  /* Until the school's record is read: the shape of what is coming, without words. */
  .skeleton {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .bone {
    display: block;
    height: 12px;
    background: var(--surface-2);
    border-radius: 6px;
  }

  .bone.is-short {
    width: 30%;
  }

  .bone.is-title {
    width: 80%;
    height: 22px;
  }

  .bone.is-line {
    width: 55%;
  }

  /*
    A phone: a sheet over the foot of the screen, the map above it, its name
    first and what does not fit a thumb's scroll away. It covers the key and
    the locate button; the search results, when open, go over it.
  */
  @media (max-width: 719px) {
    .detail {
      top: auto;
      right: 0;
      bottom: 0;
      left: 0;
      width: auto;
      max-height: min(64dvh, 520px);
      padding: 20px calc(var(--inset-right) + 16px) calc(var(--inset-bottom) + 20px)
        calc(var(--inset-left) + 16px);
      border-width: 1px 0 0;
      border-radius: 20px 20px 0 0;
      box-shadow: 0 -12px 40px rgb(0 0 0 / 0.6);
      animation-name: rise;
    }

    .action {
      height: 44px;
      border-radius: 22px;
    }

    .near {
      min-height: 44px;
    }

    .close {
      width: 40px;
      height: 40px;
      top: -8px;
      right: -4px;
    }
  }

  @keyframes rise {
    from {
      transform: translateY(24px);
      opacity: 0;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .detail {
      animation: none;
    }

    .close,
    .action {
      transition: none;
    }
  }
</style>
