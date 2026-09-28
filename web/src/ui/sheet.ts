/**
 * A school's detail panel as a phone's bottom sheet (DetailPanel.svelte).
 *
 * The sheet rests at one of three heights, its detents, each measured from
 * the foot of the screen:
 *
 * - open: where it opens, half the screen (sheet-geometry.ts): the school's
 *   name, today's status and the chance of a closure above the fold, and the
 *   school in the middle of the map above it (App.svelte frames it there);
 * - full: up to just under the search field, the rest of what it says a
 *   scroll away inside it;
 * - peek: the school's name alone, the most of the map in view.
 *
 * A drag moves it with the finger, anywhere on it but the scrolling part at
 * full height, where it scrolls instead (and still drags down from its top).
 * Let go, it glides to the detent nearest to where it was heading, one step
 * at most, and a flick always goes a step its way; down past the peek, it
 * goes and the school closes. The grip toggles between open and full for a
 * click, a key or a screen reader. It moves by a transform alone, so a drag
 * never lays out the page, and nothing is drawn over the map but the sheet.
 *
 * Touch drags are read from touch events rather than pointer events: a touch
 * that starts where the sheet scrolls can still be taken as a drag of the
 * sheet (pulled down from the top of its content) by holding back its first
 * move, which pointer events cannot do once the browser has the gesture.
 */

import { openHeight } from './sheet-geometry';

export type Detent = 'peek' | 'open' | 'full';

/** The detents from lowest to highest. */
export const DETENTS: readonly Detent[] = ['peek', 'open', 'full'];

/** How much of the sheet each detent shows, in CSS pixels from the foot of the screen. */
export interface Detents {
  readonly peek: number;
  readonly open: number;
  readonly full: number;
}

/** How far, in CSS pixels, a touch moves before it is a drag (or a scroll) rather than a tap. */
export const SLOP = 6;
/** A release faster than this, in CSS pixels a millisecond, goes at least one detent its way. */
export const FLICK = 0.4;
/** How far ahead of a release its speed carries it, in milliseconds, to pick where it rests. */
export const PROJECTION_MS = 180;
/** Let go below this share of the peek, the sheet closes. */
export const CLOSE_SHARE = 0.6;
/** How far past full height the sheet gives, at most, in CSS pixels, before it stops. */
export const OVERDRAG = 36;
/** Room kept under the school's name in the peek, in CSS pixels. */
const PEEK_GAP = 14;
/** How long the sheet takes to glide to a detent (index.html has the same); a little over, for the fallback. */
const GLIDE_MS = 420;
/** How far back a release's speed is read over, in milliseconds. */
const SPEED_WINDOW_MS = 90;
/** A click this soon after a drag ended was part of it. */
const CLICK_AFTER_DRAG_MS = 400;

export interface Release {
  /** How much of the sheet shows as it is let go. */
  readonly visible: number;
  /** Its speed, in CSS pixels a millisecond, rising positive. */
  readonly velocity: number;
  /** The detent the drag started from. */
  readonly from: Detent;
  readonly detents: Detents;
}

/** Where a sheet let go comes to rest: a detent, or 'close'. */
export function settle({ visible, velocity, from, detents }: Release): Detent | 'close' {
  const closeBelow = detents.peek * CLOSE_SHARE;
  if (visible < closeBelow) return 'close';
  const start = DETENTS.indexOf(from);
  // A flick down from the peek, or a throw that would carry it off: the school closes.
  const projected = visible + velocity * PROJECTION_MS;
  if (from === 'peek' && visible < detents.peek && (velocity < -FLICK || projected < closeBelow)) {
    return 'close';
  }
  let index = 0;
  DETENTS.forEach((detent, at) => {
    const best = DETENTS[index] ?? 'peek';
    if (Math.abs(detents[detent] - projected) < Math.abs(detents[best] - projected)) index = at;
  });
  if (velocity > FLICK) index = Math.max(index, start + 1);
  if (velocity < -FLICK) index = Math.min(index, start - 1);
  index = Math.min(Math.max(index, start - 1, 0), start + 1, DETENTS.length - 1);
  return DETENTS[index] ?? from;
}

/**
 * How much of the sheet shows for a drag that asks for `wanted`: as asked up
 * to full height, and past it a give that slows to a stop OVERDRAG further on.
 */
export function stretch(wanted: number, detents: Detents): number {
  if (wanted <= detents.full) return Math.max(0, wanted);
  const over = wanted - detents.full;
  return detents.full + (over * OVERDRAG) / (over + OVERDRAG);
}

/** The speed of a drag from its last moves, in CSS pixels a millisecond, rising positive. */
export function speed(samples: readonly { readonly t: number; readonly y: number }[]): number {
  const last = samples.at(-1);
  if (last === undefined) return 0;
  const first = samples.find((sample) => last.t - sample.t <= SPEED_WINDOW_MS) ?? last;
  const time = last.t - first.t;
  return time > 0 ? (first.y - last.y) / time : 0;
}

export interface SheetOptions {
  /** The sheet: the panel itself. */
  readonly sheet: HTMLElement;
  /** The part of it that scrolls, at full height. */
  readonly body: HTMLElement;
  /** Where a drag always moves the sheet, even at full height: the grip and the school's name. */
  readonly handles: () => readonly (Element | null | undefined)[];
  /** The school's name and what it is: the peek shows it and no more. */
  readonly head: () => Element | null | undefined;
  /** The sheet went down past its peek: the school closes. */
  readonly onclose: () => void;
  /** The sheet came to rest at a detent (the map's labels make room for it). */
  readonly onsettle?: (detent: Detent) => void;
  /** The sheet is on its way to a detent. */
  readonly onchange?: (detent: Detent) => void;
}

export interface Sheet {
  /** The detent it rests at, or is on its way to. */
  readonly detent: Detent;
  /** Opens it again at its opening height, its content at the top: for another school. */
  reset(): void;
  /** The grip pressed: open goes to full, anything else to open. */
  toggle(): void;
  /** Glides it off the foot of the screen, and the school closes. */
  dismiss(): void;
  /** Leaves the element as it was. */
  destroy(): void;
}

interface Gesture {
  /** Where the drag is measured from. */
  y0: number;
  x0: number;
  /** How much of the sheet showed then. */
  visible0: number;
  from: Detent;
  /** A touch starts undecided; it becomes a drag of the sheet, a scroll of its content, or neither. */
  mode: 'pending' | 'drag' | 'scroll';
  /** Whether it started on a handle (the grip or the name). */
  onHandle: boolean;
  samples: { t: number; y: number }[];
  /** The pointer, for a mouse or a pen; null for a touch. */
  pointer: number | null;
}

/** Makes `sheet` a bottom sheet that opens at once; returns what moves it. */
export function attachSheet(options: SheetOptions): Sheet {
  const { sheet, body } = options;
  let detents: Detents = { peek: 0, open: 0, full: 0 };
  let detent: Detent = 'open';
  let visible = 0;
  let gesture: Gesture | null = null;
  let closing = false;
  let draggedAt = -Infinity;
  let settleTimer: ReturnType<typeof setTimeout> | undefined;
  let destroyed = false;

  const measure = (): void => {
    const full = sheet.offsetHeight;
    const open = openHeight(window.innerHeight, full);
    const head = options.head();
    let peek = open;
    if (head) {
      // The sheet's own bottom padding is the screen's inset for the home indicator.
      const inset = Number.parseFloat(getComputedStyle(sheet).paddingBottom) || 0;
      const top = sheet.getBoundingClientRect().top;
      const bottom = head.getBoundingClientRect().bottom + body.scrollTop;
      peek = Math.min(open, Math.round(bottom - top + PEEK_GAP + inset));
    }
    detents = { peek, open, full };
  };

  /** Shows `height` of the sheet: at once while it follows a finger, else gliding there. */
  const show = (height: number, glide: boolean): void => {
    visible = height;
    if (glide) delete sheet.dataset.dragging;
    else sheet.dataset.dragging = '';
    const offset = `${String(Math.round((detents.full - height) * 100) / 100)}px`;
    sheet.style.transform = `translate3d(0, ${offset}, 0)`;
    // How far below the screen its foot is: what is drawn at the screen's foot moves back up by it.
    sheet.style.setProperty('--sheet-offset', offset);
  };

  const finish = (): void => {
    clearTimeout(settleTimer);
    settleTimer = undefined;
    sheet.removeEventListener('transitionend', onGlideEnd);
    if (destroyed) return;
    if (closing) {
      options.onclose();
      return;
    }
    options.onsettle?.(detent);
  };

  function onGlideEnd(event: TransitionEvent): void {
    if (event.target === sheet && event.propertyName === 'transform') finish();
  }

  /** Glides to `target`, and says so once it is there. */
  const go = (target: Detent | 'close'): void => {
    clearTimeout(settleTimer);
    sheet.removeEventListener('transitionend', onGlideEnd);
    if (target === 'close') {
      closing = true;
      show(0, true);
    } else {
      const leaving = detent === 'full' && target !== 'full';
      detent = target;
      sheet.dataset.detent = target;
      options.onchange?.(target);
      if (leaving && body.scrollTop > 0) body.scrollTo({ top: 0, behavior: 'smooth' });
      show(detents[target], true);
    }
    sheet.addEventListener('transitionend', onGlideEnd);
    // A glide that goes nowhere never ends, and reduced motion has none (it is there at once):
    // said all the same.
    const still = getComputedStyle(sheet).transitionDuration === '0s';
    settleTimer = setTimeout(finish, still ? 0 : GLIDE_MS + 80);
  };

  const onHandle = (target: EventTarget | null): boolean =>
    target instanceof Node && options.handles().some((handle) => handle?.contains(target) === true);

  const begin = (x: number, y: number, target: EventTarget | null, pointer: number | null) => {
    if (closing) return;
    measure();
    // Caught mid-glide, it is taken from where it is on screen, not where it was going.
    visible = window.innerHeight - sheet.getBoundingClientRect().top;
    gesture = {
      x0: x,
      y0: y,
      visible0: visible,
      from: detent,
      mode: 'pending',
      onHandle: onHandle(target),
      samples: [],
      pointer,
    };
  };

  /** Moves the sheet with the finger; returns whether the move is the sheet's. */
  const move = (x: number, y: number, time: number): boolean => {
    if (gesture === null) return false;
    const dy = y - gesture.y0;
    if (gesture.mode === 'pending') {
      const dx = x - gesture.x0;
      if (Math.abs(dy) < SLOP && Math.abs(dx) < SLOP) return false;
      const scrolls = detent === 'full' && !gesture.onHandle && !(body.scrollTop <= 0 && dy > 0);
      if (Math.abs(dx) > Math.abs(dy) || scrolls) {
        gesture.mode = 'scroll';
        return false;
      }
      gesture.mode = 'drag';
      // From here on, so the sheet does not jump by the slop.
      gesture.y0 = y;
      gesture.visible0 = visible;
    }
    if (gesture.mode !== 'drag') return false;
    show(stretch(gesture.visible0 - (y - gesture.y0), detents), false);
    gesture.samples.push({ t: time, y });
    if (gesture.samples.length > 12) gesture.samples.shift();
    return true;
  };

  const end = (cancelled: boolean): void => {
    const done = gesture;
    gesture = null;
    if (done?.mode !== 'drag') return;
    draggedAt = performance.now();
    if (cancelled) {
      go(done.from);
      return;
    }
    go(settle({ visible, velocity: speed(done.samples), from: done.from, detents }));
  };

  // Touch: every move of a drag held back, so the page and the content never scroll with it.
  const onTouchStart = (event: TouchEvent): void => {
    const touch = event.touches[0];
    if (event.touches.length !== 1 || touch === undefined) {
      end(true);
      return;
    }
    begin(touch.clientX, touch.clientY, event.target, null);
  };
  const onTouchMove = (event: TouchEvent): void => {
    const touch = event.touches[0];
    if (gesture?.pointer !== null || touch === undefined) return;
    const pending = gesture.mode === 'pending';
    if (move(touch.clientX, touch.clientY, event.timeStamp)) {
      if (event.cancelable) event.preventDefault();
      else if (pending && gesture.from === 'full') {
        // The content already scrolls: it keeps the gesture.
        gesture.mode = 'scroll';
        show(detents.full, true);
      }
    }
  };
  const onTouchEnd = (): void => {
    if (gesture?.pointer === null) end(false);
  };
  const onTouchCancel = (): void => {
    if (gesture?.pointer === null) end(true);
  };

  // A mouse or a pen: the same drags, by pointer events.
  const onPointerDown = (event: PointerEvent): void => {
    if (event.pointerType === 'touch' || event.button !== 0) return;
    // At full height a mouse scrolls the content with its wheel; it drags the sheet by a handle.
    if (detent === 'full' && !onHandle(event.target)) return;
    begin(event.clientX, event.clientY, event.target, event.pointerId);
  };
  const onPointerMove = (event: PointerEvent): void => {
    if (gesture?.pointer !== event.pointerId) return;
    const pending = gesture.mode === 'pending';
    if (move(event.clientX, event.clientY, event.timeStamp)) {
      if (pending) sheet.setPointerCapture(event.pointerId);
      event.preventDefault();
    }
  };
  const onPointerUp = (event: PointerEvent): void => {
    if (gesture?.pointer === event.pointerId) end(event.type === 'pointercancel');
  };

  // What a drag let go over is not also a click.
  const onClick = (event: MouseEvent): void => {
    if (performance.now() - draggedAt < CLICK_AFTER_DRAG_MS) {
      event.preventDefault();
      event.stopPropagation();
    }
  };

  // A wheel turned down over the sheet below full height takes it up first.
  const onWheel = (event: WheelEvent): void => {
    if (detent === 'full' || closing || event.deltaY <= 0) return;
    event.preventDefault();
    measure();
    go('full');
  };

  // Tabbing to something below the fold takes the sheet up to show it.
  const onFocusIn = (event: FocusEvent): void => {
    if (detent === 'full' || closing || !(event.target instanceof Element)) return;
    if (!body.contains(event.target)) return;
    if (event.target.getBoundingClientRect().bottom > window.innerHeight) {
      measure();
      go('full');
    }
  };

  const onResize = (): void => {
    if (closing) return;
    measure();
    show(detents[detent], false);
  };

  sheet.addEventListener('touchstart', onTouchStart, { passive: true });
  sheet.addEventListener('touchmove', onTouchMove, { passive: false });
  sheet.addEventListener('touchend', onTouchEnd);
  sheet.addEventListener('touchcancel', onTouchCancel);
  sheet.addEventListener('pointerdown', onPointerDown);
  sheet.addEventListener('pointermove', onPointerMove);
  sheet.addEventListener('pointerup', onPointerUp);
  sheet.addEventListener('pointercancel', onPointerUp);
  sheet.addEventListener('click', onClick, true);
  sheet.addEventListener('wheel', onWheel, { passive: false });
  sheet.addEventListener('focusin', onFocusIn);
  window.addEventListener('resize', onResize);

  // It rises from the foot of the screen to its opening height.
  measure();
  sheet.dataset.detent = detent;
  show(0, false);
  // Laid out where it starts, so the glide up has somewhere to start from.
  sheet.getBoundingClientRect();
  go('open');

  return {
    get detent() {
      return detent;
    },
    reset() {
      closing = false;
      gesture = null;
      body.scrollTop = 0;
      measure();
      go('open');
    },
    toggle() {
      if (closing) return;
      measure();
      go(detent === 'open' ? 'full' : 'open');
    },
    dismiss() {
      if (closing) return;
      gesture = null;
      go('close');
    },
    destroy() {
      destroyed = true;
      clearTimeout(settleTimer);
      sheet.removeEventListener('transitionend', onGlideEnd);
      sheet.removeEventListener('touchstart', onTouchStart);
      sheet.removeEventListener('touchmove', onTouchMove);
      sheet.removeEventListener('touchend', onTouchEnd);
      sheet.removeEventListener('touchcancel', onTouchCancel);
      sheet.removeEventListener('pointerdown', onPointerDown);
      sheet.removeEventListener('pointermove', onPointerMove);
      sheet.removeEventListener('pointerup', onPointerUp);
      sheet.removeEventListener('pointercancel', onPointerUp);
      sheet.removeEventListener('click', onClick, true);
      sheet.removeEventListener('wheel', onWheel);
      sheet.removeEventListener('focusin', onFocusIn);
      window.removeEventListener('resize', onResize);
      sheet.style.removeProperty('transform');
      sheet.style.removeProperty('--sheet-offset');
      delete sheet.dataset.detent;
      delete sheet.dataset.dragging;
    },
  };
}
