/**
 * The status page's script. It only fetches `/api/status`, keeps what was last answered, which
 * problems are shown and which bar is picked, and writes `<main>` from the pure view.
 */

import type { Part, Summary } from '../../shared/types.ts';
import { mainHtml } from './html.ts';
import { RETRY_AFTER, elapsed, nextDelay, readAnswer, viewOf } from './view.ts';
import type { Input, Marks, Picked } from './view.ts';

const FETCH_TIMEOUT_MS = 10000;
const REDRAW_MS = 30000;

const main = document.getElementById('main') as HTMLElement;
const said = document.getElementById('said') as HTMLElement;
// The script has started: the stylesheet's "did not finish loading" line is never shown now.
main.classList.add('on');

/** The last good answer, and the device's clocks when it arrived. */
let answer: { served: number; summary: Summary | null; at: Marks } | null = null;
/** The last refresh failed. */
let failed = false;
/** When the last try ended, and how many seconds after it the next is due. */
let tried: Marks | null = null;
let dueAfter = 0;
let busy = false;
let expanded = false;
let picked: Picked | null = null;
let timer = 0;
let lead = '';

function marks(): Marks {
  return { perf: performance.now(), date: Date.now() };
}

function input(): Input {
  if (answer === null) return failed ? { kind: 'unreachable' } : { kind: 'wait' };
  const clock = answer.served + elapsed(answer.at, marks());
  return { kind: 'data', summary: answer.summary, clock, kept: failed, expanded, picked };
}

function draw(): void {
  const view = viewOf(input());
  const focused = document.activeElement?.id === 'more';
  main.innerHTML = mainHtml(view);
  if (focused) document.getElementById('more')?.focus();
  const first = view.banner.lead[0] ?? '';
  if (first !== lead) {
    lead = first;
    said.textContent = first;
  }
}

function schedule(): void {
  window.clearTimeout(timer);
  if (document.visibilityState !== 'visible' || tried === null) return;
  const left = dueAfter - elapsed(tried, marks());
  timer = window.setTimeout(refresh, Math.max(0, left) * 1000);
}

async function refresh(): Promise<void> {
  if (busy || document.visibilityState !== 'visible') return;
  busy = true;
  let good: ReturnType<typeof readAnswer> = null;
  try {
    // Never from the browser's cache: the page's clock counts from the answer's `served`.
    const response = await fetch('/api/status', {
      cache: 'no-store',
      credentials: 'omit',
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
    good = readAnswer(response.status, await response.json());
  } catch {
    good = null;
  }
  busy = false;
  tried = marks();
  if (good === null) {
    failed = true;
    dueAfter = RETRY_AFTER;
  } else {
    failed = false;
    answer = { served: good.served, summary: good.summary, at: tried };
    dueAfter = nextDelay(true, good.summary, good.served);
  }
  draw();
  schedule();
}

/** Starts a fetch that is due on the clock: a timer set before a sleep is not trusted. */
function refreshIfDue(after: number): void {
  if (tried === null || elapsed(tried, marks()) >= after) void refresh();
  else schedule();
}

function barAt(event: MouseEvent): Picked | null {
  const bars = (event.target as Element | null)?.closest?.('.bars');
  if (!(bars instanceof HTMLElement) || bars.getAttribute('aria-hidden') === 'true') return null;
  const box = bars.getBoundingClientRect();
  const count = bars.children.length;
  if (box.width <= 0 || count === 0) return null;
  const day = Math.min(
    count - 1,
    Math.max(0, Math.floor(((event.clientX - box.left) / box.width) * count)),
  );
  return { part: bars.dataset['part'] as Part, day };
}

function pick(event: MouseEvent): void {
  const found = barAt(event);
  if (found === null) return;
  if (picked !== null && picked.part === found.part && picked.day === found.day) return;
  picked = found;
  draw();
}

main.addEventListener('click', (event) => {
  if ((event.target as Element | null)?.closest?.('#more')) {
    expanded = !expanded;
    draw();
    return;
  }
  pick(event);
});
main.addEventListener('pointermove', pick);

window.setInterval(() => {
  if (document.visibilityState !== 'visible') return;
  draw();
  refreshIfDue(dueAfter);
}, REDRAW_MS);
/**
 * Back on screen. What is shown is drawn again on the clock first, so an old answer says its
 * age at once and not only when the fetch settles; then a fetch that is due starts.
 */
function back(): void {
  draw();
  refreshIfDue(Math.min(dueAfter, RETRY_AFTER));
}

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') back();
  else window.clearTimeout(timer);
});
window.addEventListener('pageshow', back);
void refresh();
