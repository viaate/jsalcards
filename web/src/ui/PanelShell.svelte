<script lang="ts">
  import { untrack } from 'svelte';
  import type { Snippet } from 'svelte';
  import type { Attachment } from 'svelte/attachments';

  import { copy } from '../copy';
  import { attachSheet } from './sheet';
  import type { Detent, Sheet } from './sheet';
  import { PHONE_QUERY } from './sheet-geometry';

  interface Props {
    /** The panel, for a screen reader. */
    label: string;
    /** True while what it shows is read. */
    busy?: boolean;
    /** True while it has nothing to show yet but its shape. */
    loading?: boolean;
    /** What it shows: a new one opens the sheet afresh, at its opening height. */
    shows: string;
    onclose: () => void;
    /** On a phone, the sheet came to rest at another height: the map's labels make room for it. */
    onsettle?: () => void;
    /** The panel's element, for the page to focus after a pick. */
    element?: HTMLElement | undefined;
    /** What the panel is, at its top, beside the close button: it drags the sheet. */
    head: Snippet;
    /** What the panel says, under its head. */
    children: Snippet;
  }

  let {
    label,
    busy = false,
    loading = false,
    shows,
    onclose,
    onsettle = () => undefined,
    element = $bindable(),
    head,
    children,
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

  // Something else in the same sheet (a nearby school picked): it opens afresh, at its opening height.
  let shown = untrack(() => shows);
  $effect(() => {
    const next = shows;
    if (next === shown) return;
    shown = next;
    sheet?.reset();
  });

  /** Closes the panel: a sheet glides away first. */
  function close(): void {
    if (sheet === null) onclose();
    else sheet.dismiss();
  }
</script>

<!--
  A panel over the map: beside it on a wide screen, a sheet over its foot on a
  phone (ui/sheet.ts), for a school (DetailPanel.svelte) or the schools around
  a ZIP code (AreaPanel.svelte). Its content starts with a .head, which drags
  the sheet.
-->
<aside
  class="detail"
  class:is-loading={loading}
  aria-label={label}
  aria-busy={busy}
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
      {@render head()}
      <button class="close" type="button" aria-label={copy.detail.close} onclick={close}>
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />
        </svg>
      </button>
    </header>
    {@render children()}
  </div>
</aside>

<style>
  /*
    Beside the map, under the wordmark, clear of the legend at the foot of the
    screen: a solid card like the search results (no backdrop blur over the
    moving WebGL map). What does not fit scrolls inside it.

    The panels' one type scale and one grid, for the chance section too
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

  /* What the panel is, at its top, clear of the close button. */
  .head {
    position: relative;
    padding-right: 40px;
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

  .close:focus-visible {
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

  /*
    A phone: a sheet over the foot of the screen (ui/sheet.ts). It is as tall
    as the screen under the search field, and shows as much of itself as its
    detent asks, moved down by a transform alone: open, half the screen, with
    what it shows in the middle of the map above it; full, up to just under
    the field; or its head alone. It covers the key and the locate button; the
    search results, when open, go over it. Solid, like the search field:
    nothing over the moving map is blurred.
  */
  @media (max-width: 719px) {
    .detail {
      /* The title a step larger on a phone. */
      --type-title: 600 24px / 29px var(--font-sans);

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

    /* The head drags the sheet even at full height. */
    .head {
      padding-right: 48px;
      touch-action: none;
    }

    /* The close button in the family of a phone's chips and pills: the same fill, border and round ends. */
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
    .detail::after,
    .close {
      animation: none;
      transition: none;
    }
  }
</style>
