/** From a view to HTML. Pure, and every value is escaped. */

import { CANONICAL_URL, HOME_URL, copy } from './copy.ts';
import { MARK } from './mark.ts';
import { TILE } from './tile.ts';
import type { Shape, View } from './view.ts';

/** The join between the two parts of a length (`copy.dur.two`). */
const PART = /\u202f/g;

function escaped(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** A text as HTML: escaped, and a length's two parts tied by a no-break space. */
export function esc(text: string): string {
  return escaped(text).replace(PART, '\u00a0');
}

const SHAPES: Record<Shape | 'none' | 'before', string> = {
  ok: '<circle cx="8" cy="8" r="6.5"/>',
  late: '<path d="M8 1.5 15.2 14H.8Z"/>',
  down: '<rect x="2" y="2" width="12" height="12" rx="1.5"/>',
  unknown: '<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="2"/>',
  wait: '<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="2"/>',
  // The two bars that are not a state, drawn as a run of them looks in the history.
  none: '<path d="M1 9h4v6H1zM6 9h4v6H6zM11 9h4v6h-4z"/>',
  before: '<path d="M1 13h4v2H1zM6 13h4v2H6zM11 13h4v2h-4z"/>',
};

/** A state's shape. The word beside it says the same: color is never alone. */
export function shape(of: Shape | 'none' | 'before'): string {
  return (
    `<svg class="shape s-${of}" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" ` +
    `aria-hidden="true" focusable="false">${SHAPES[of]}</svg>`
  );
}

/** Each part's name as the copy spells it, longest first, as a pattern. */
const NAMES = Object.values(copy.parts)
  .map((part) => part.name)
  .sort((a, b) => b.length - a.length)
  .map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  .join('|');
/** A name, with the "and" before it and the comma, colon or full stop after it. */
const NAMED = new RegExp(`(\u00a0and )?((?:${NAMES})[,.:]?)`, 'g');

/**
 * A text with each part's name in a box of its own, wherever a name is drawn. A box moves to the next line whole
 * when it does not fit at the end of one, and breaks between its words only when it is wider
 * than the whole line (very large text on a narrow phone), so the text never has to shrink
 * and never runs off the side. "and" goes in the box of the name after it, never alone.
 */
export function named(line: string): string {
  return nameBoxes(esc(line));
}

function nameBoxes(html: string): string {
  return html.replace(
    NAMED,
    (_, and: string | undefined, name: string) =>
      `${and === undefined ? '' : ' '}<span class="nm">${and === undefined ? '' : 'and '}` +
      `${name.replace(/\u00a0/g, ' ')}</span>`,
  );
}

/**
 * A text with each part's name in its box, and every other run the copy or the view ties with
 * no-break spaces (a date, a time, a length: "1 hour 10 minutes.") in a box of its own, with
 * the stop or comma after it. Like a name's, the box moves to the next line whole and breaks
 * between its words only when it is wider than the whole line. A length of two parts is a box
 * of two boxes, so where it is wider than the line it breaks between its parts ("23 hours" and
 * "55 minutes."), never between a number and its unit.
 */
export function boxed(line: string): string {
  const box = (words: string): string => `<span class="nb">${words.replace(/\u00a0/g, ' ')}</span>`;
  return nameBoxes(escaped(line)).replace(/[^ \n<>\u00a0\u202f]*[\u00a0\u202f][^ \n<>]*/g, (run) =>
    run.includes('\u202f')
      ? `<span class="nb">${run.split('\u202f').map(box).join(' ')}</span>`
      : box(run),
  );
}

/**
 * A row's line, with an address ("snowlightmap.com.") in a box that breaks only at its dot,
 * and only where it is wider than the whole line.
 */
function addressed(line: string): string {
  return esc(line).replace(
    /([A-Za-z0-9-]+)(\.[a-z]{2,}[.,]?)(?=\s|$)/g,
    '<span class="nb">$1<wbr>$2</span>',
  );
}

function banner(view: View): string {
  const lead = view.banner.lead.map((line) => `<p class="lead">${named(line)}</p>`).join('');
  const more = view.banner.more === null ? '' : `<p class="more">${esc(view.banner.more)}</p>`;
  // Drawn in the lead's place by the stylesheet alone, when the script has not started in time.
  const stuck =
    view.banner.stuck === null ? '' : `<p class="lead stuck">${esc(view.banner.stuck)}</p>`;
  return (
    `<section class="banner card" id="banner">${shape(view.banner.shape)}` +
    `<div${stuck === '' ? '' : ' class="swap"'}>${lead}${more}${stuck}</div></section>`
  );
}

function now(view: View): string {
  const rows = view.parts
    .map(
      (row) =>
        `<li class="row"><span class="name">${named(row.name)}</span>` +
        `<span class="state">${shape(row.shape)}${esc(row.word)}</span>` +
        `<span class="says">${addressed(row.says)}</span>` +
        (row.file
          ? `<span class="upd">${row.updated === null ? '' : esc(row.updated)}</span>`
          : '') +
        '</li>',
    )
    .join('');
  return (
    `<section aria-labelledby="h-now"><h2 id="h-now">${esc(copy.heads.now)}</h2>` +
    `<ul class="card rows">${rows}</ul></section>`
  );
}

function history(view: View): string {
  const key =
    (['ok', 'late', 'down'] as const)
      .map((state) => `<span>${shape(state)}${esc(copy.state[state])}</span>`)
      .join('') +
    `<span>${shape('none')}${esc(copy.share.keyNone)}</span>` +
    `<span>${shape('before')}${esc(copy.share.keyBefore)}</span>`;
  const blocks = view.history
    .map((block) => {
      const labelled = block.bars.some((bar) => bar.label !== null);
      const bars = block.bars
        .map((bar, i) => {
          const cls = `bar b-${bar.cls}${bar.picked ? ' on' : ''}`;
          if (bar.label === null) return `<span class="${cls}"></span>`;
          const label = esc(bar.label);
          return `<span class="${cls}" role="img" aria-label="${label}" title="${label}" data-day="${i}"></span>`;
        })
        .join('');
      return (
        `<li class="hist"><p class="hist-top"><span class="name">${named(block.name)}</span>` +
        `<span class="share">${esc(block.share)}</span></p>` +
        `<div class="bars" data-part="${block.part}"${labelled ? '' : ' aria-hidden="true"'}>${bars}</div>` +
        `<p class="axis" aria-hidden="true"><span>${esc(copy.share.axisStart)}</span><span>${esc(copy.share.axisEnd)}</span></p>` +
        `<p class="note${block.hint ? ' hint' : ''}">${esc(block.note)}</p></li>`
      );
    })
    .join('');
  return (
    `<section aria-labelledby="h-history"><div class="head"><h2 id="h-history">${esc(copy.heads.history)}</h2>` +
    `<p class="key">${key}</p></div><ul class="card hists">${blocks}</ul></section>`
  );
}

function problems(view: View): string {
  const { slots, empty, button } = view.problems;
  let list: string;
  if (slots.every((slot) => slot === null)) {
    list = `<div class="probs none"><p>${empty === null ? '' : esc(empty)}</p></div>`;
  } else {
    const items = slots
      .map((slot) =>
        slot === null
          ? '<li class="slot" aria-hidden="true"></li>'
          : `<li class="slot"><span class="what">${boxed(slot.what)}</span><span class="when">${boxed(slot.when)}</span></li>`,
      )
      .join('');
    list = `<ol class="probs">${items}</ol>`;
  }
  const more =
    button === null
      ? ''
      : `<button type="button" id="more" aria-expanded="${view.problems.expanded}">${esc(button)}</button>`;
  return (
    `<section aria-labelledby="h-problems"><h2 id="h-problems">${esc(copy.heads.problems)}</h2>` +
    `<div class="card">${list}<p class="more-row">${more}</p></div></section>`
  );
}

/** What goes in `<main>`. */
export function mainHtml(view: View): string {
  return banner(view) + now(view) + history(view) + problems(view);
}

/** The whole page, with `main` in `<main>`: the first paint before the script runs. */
export function pageHtml(main: string): string {
  return (
    '<!doctype html>\n<html lang="en">\n<head>\n' +
    '<meta charset="utf-8">\n' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n' +
    `<title>${esc(copy.title)}</title>\n` +
    `<meta name="description" content="${esc(copy.description)}">\n` +
    '<meta name="color-scheme" content="light dark">\n' +
    `<link rel="canonical" href="${CANONICAL_URL}">\n` +
    '<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">\n' +
    '<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png">\n' +
    '<link rel="stylesheet" href="/style.css">\n' +
    '<script src="/app.js" defer></script>\n' +
    '</head>\n<body>\n' +
    `<header><h1>${TILE}<span class="brand">${esc(copy.brand)}</span> <span class="page">${esc(copy.page)}</span></h1></header>\n` +
    `<noscript><p class="noscript">${esc(copy.noscript)}</p></noscript>\n` +
    `<main id="main">${main}</main>\n` +
    '<p class="sr" id="said" role="status"></p>\n' +
    `<footer><p class="how">${esc(copy.foot.how)}</p><p>${esc(copy.foot.privacy)}</p>` +
    `<p><a class="home" href="${HOME_URL}">${MARK}<span>${esc(copy.foot.home)}</span></a></p></footer>\n` +
    '</body>\n</html>\n'
  );
}
