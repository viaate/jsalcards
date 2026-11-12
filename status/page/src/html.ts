/** From a view to HTML. Pure, and every value is escaped. */

import { CANONICAL_URL, HOME_URL, copy, fill } from './copy.ts';
import { MARK } from './mark.ts';
import { TILE } from './tile.ts';
import type { DayView, ProblemView, Shape, View } from './view.ts';

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

const SHAPES: Record<Shape, string> = {
  ok: '<circle cx="8" cy="8" r="6.5"/>',
  late: '<path d="M8 1.5 15.2 14H.8Z"/>',
  down: '<rect x="2" y="2" width="12" height="12" rx="1.5"/>',
  unknown: '<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="2"/>',
  wait: '<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="2"/>',
};

/** A state's shape. The word beside it says the same: color is never alone. */
export function shape(of: Shape): string {
  return (
    `<svg class="shape s-${of}" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" ` +
    `aria-hidden="true" focusable="false">${SHAPES[of]}</svg>`
  );
}

/** The small mark beside a part's name: a letter i in a ring. */
const INFO =
  '<svg class="i" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true" ' +
  'focusable="false"><path d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm0 1.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11Z"/>' +
  '<circle cx="8" cy="5.25" r="1"/><path d="M7.25 7h1.5v4.5h-1.5z"/></svg>';

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
  const { lead, more, stuck } = view.banner;
  const words =
    `<div><p class="lead">${esc(lead)}</p>` +
    (more === null ? '' : `<p class="more">${esc(more)}</p>`) +
    '</div>';
  // Drawn in the words' place by the stylesheet alone, when the script has not started in time.
  const body =
    stuck === null
      ? words
      : `<div class="swap">${words}<div class="stuck"><p class="lead">${esc(stuck.lead)}</p>` +
        `<p class="more">${esc(stuck.more)}</p></div></div>`;
  return `<section class="banner st-${view.banner.shape}" id="banner">${shape(view.banner.shape)}${body}</section>`;
}

function bars(block: View['history'][number]): string {
  // No day is known: an empty outline the height of the bars, and the row's "Not loaded".
  if (block.bars.every((bar) => bar.cls === 'unloaded')) {
    return `<div class="bars off" data-part="${block.part}" aria-hidden="true"></div>`;
  }
  const labelled = block.bars.some((bar) => bar.label !== null);
  const drawn = block.bars
    .map((bar, i) => {
      const cls = `bar b-${bar.cls}${bar.picked ? ' on' : ''}`;
      if (bar.label === null) return `<span class="${cls}"></span>`;
      return `<span class="${cls}" role="img" aria-label="${esc(bar.label)}" data-day="${i}"></span>`;
    })
    .join('');
  // The picked day's name, in a tip under its bar.
  const tip =
    block.note === null ? '' : `<p class="tip" id="tip" role="tooltip">${boxed(block.note)}</p>`;
  return `<div class="bars" data-part="${block.part}"${labelled ? '' : ' aria-hidden="true"'}>${drawn}${tip}</div>`;
}

function parts(view: View): string {
  const rows = view.parts
    .map((row, i) => {
      const block = view.history[i]!;
      const about = fill(copy.about, { part: row.name });
      return (
        `<li class="part"><p class="top"><span class="name">${named(row.name)}</span>` +
        `<span class="info" tabindex="0" role="img" aria-label="${esc(about)}">${INFO}` +
        `<span class="about" aria-hidden="true">${addressed(row.says)}</span></span>` +
        `<span class="state s-${row.shape}">${shape(row.shape)}${esc(row.word)}</span></p>` +
        `<p class="sr">${addressed(row.says)}</p>` +
        bars(block) +
        `<p class="axis" aria-hidden="true"><span>${esc(copy.share.axisStart)}</span>` +
        `<span class="mid">${esc(block.mid)}</span>` +
        `<span>${esc(copy.share.axisEnd)}</span></p>` +
        // The axis is drawn for the eye; its share is said to a screen reader here.
        (block.mid === '' ? '' : `<p class="sr">${esc(block.mid)}</p>`) +
        (row.file ? `<p class="upd">${esc(row.updated)}</p>` : '') +
        '</li>'
      );
    })
    .join('');
  return (
    `<section aria-labelledby="h-now"><h2 id="h-now">${esc(copy.heads.now)}</h2>` +
    `<ul class="card parts">${rows}</ul></section>`
  );
}

function problem(item: ProblemView): string {
  return (
    `<li class="prob"><p class="what k-${item.kind}">${boxed(item.what)}</p>` +
    `<p class="when">${boxed(item.when)}</p></li>`
  );
}

function day(item: DayView): string {
  return (
    `<li class="day"><h3><time>${esc(item.date)}</time></h3>` +
    (item.none === null
      ? `<ul class="probs">${item.problems.map(problem).join('')}</ul>`
      : `<p class="none">${esc(item.none)}</p>`) +
    (item.note === null ? '' : `<p class="none note">${esc(item.note)}</p>`) +
    '</li>'
  );
}

function problems(view: View): string {
  const { days, empty, older, button, expanded, began, cut } = view.problems;
  // Only problem days are listed: with none, and nothing to say in their place, no section.
  if (days.length === 0 && empty === null && button === null) return '';
  let list = '';
  if (days.length > 0) list = `<ol class="days">${days.map(day).join('')}</ol>`;
  else if (empty !== null) list = `<p class="empty">${esc(empty)}</p>`;
  const shown =
    expanded && older.length > 0 ? `<ol class="days older">${older.map(day).join('')}</ol>` : '';
  const more =
    button === null
      ? ''
      : `<p class="more-row"><button type="button" id="more" aria-expanded="${expanded}">${esc(button)}</button></p>`;
  const ends = [cut, began]
    .filter((line) => line !== null)
    .map((line) => `<p class="end">${boxed(line)}</p>`)
    .join('');
  return (
    `<section class="past" aria-labelledby="h-problems"><h2 id="h-problems">${esc(copy.heads.problems)}</h2>` +
    `${list}${shown}${more}${ends}</section>`
  );
}

/** What each color of bar means, each with a bar of its own color. */
function key(): string {
  const kinds = ['ok', 'late', 'down', 'none', 'before'] as const;
  const items = kinds
    .map((kind) => `<li><span class="sw b-${kind}"></span>${esc(copy.foot.key[kind])}</li>`)
    .join('');
  return `<ul class="key how">${items}</ul>`;
}

/** What goes in `<main>`. */
export function mainHtml(view: View): string {
  return banner(view) + parts(view) + problems(view);
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
    `<header><div class="bar-top"><h1>${TILE}<span class="brand">${esc(copy.brand)}</span> <span class="page">${esc(copy.page)}</span></h1>` +
    `<a class="go" href="${HOME_URL}">${esc(copy.foot.home)}</a></div></header>\n` +
    `<noscript><p class="noscript">${esc(copy.noscript)}</p></noscript>\n` +
    // The first paint is the page waiting: its footer is drawn once the page has filled in.
    `<main id="main" class="wait">${main}</main>\n` +
    '<p class="sr" id="said" role="status"></p>\n' +
    `<footer><div class="foot-in"><p class="how">${esc(copy.foot.how)}</p>${key()}` +
    `<p class="how">${esc(copy.foot.share)}</p><p class="privacy">${esc(copy.foot.privacy)}</p>` +
    `<p><a class="home" href="${HOME_URL}">${MARK}<span>${esc(copy.foot.home)}</span></a></p></div></footer>\n` +
    '</body>\n</html>\n'
  );
}
