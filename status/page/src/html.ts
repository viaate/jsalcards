/** From a view to HTML. Pure, and every value is escaped. */

import { CANONICAL_URL, HOME_URL, copy } from './copy.ts';
import { MARK } from './mark.ts';
import { TILE } from './tile.ts';
import type { Shape, View } from './view.ts';

export function esc(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

const SHAPES: Record<Shape | 'none', string> = {
  ok: '<circle cx="8" cy="8" r="6.5"/>',
  late: '<path d="M8 1.5 15.2 14H.8Z"/>',
  down: '<rect x="2" y="2" width="12" height="12" rx="1.5"/>',
  unknown: '<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="2"/>',
  wait: '<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="2"/>',
  none: '<rect x="5" y="9" width="6" height="5" rx="1"/>',
};

/** A state's shape. The word beside it says the same: color is never alone. */
export function shape(of: Shape | 'none'): string {
  return (
    `<svg class="shape s-${of}" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" ` +
    `aria-hidden="true" focusable="false">${SHAPES[of]}</svg>`
  );
}

function banner(view: View): string {
  const lead = view.banner.lead.map((line) => `<p class="lead">${esc(line)}</p>`).join('');
  const more = view.banner.more === null ? '' : `<p class="more">${esc(view.banner.more)}</p>`;
  return `<section class="banner card" id="banner">${shape(view.banner.shape)}<div>${lead}${more}</div></section>`;
}

function now(view: View): string {
  const rows = view.parts
    .map(
      (row) =>
        `<li class="row"><span class="name">${esc(row.name)}</span>` +
        `<span class="state">${shape(row.shape)}${esc(row.word)}</span>` +
        `<span class="says">${esc(row.says)}</span>` +
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
      .join('') + `<span>${shape('none')}${esc(copy.share.keyNone)}</span>`;
  const blocks = view.history
    .map((block) => {
      const named = block.bars.some((bar) => bar.label !== null);
      const bars = block.bars
        .map((bar, i) => {
          const cls = `bar b-${bar.cls}${bar.picked ? ' on' : ''}`;
          if (bar.label === null) return `<span class="${cls}"></span>`;
          const label = esc(bar.label);
          return `<span class="${cls}" role="img" aria-label="${label}" title="${label}" data-day="${i}"></span>`;
        })
        .join('');
      return (
        `<li class="hist"><p class="hist-top"><span class="name">${esc(block.name)}</span>` +
        `<span class="share">${esc(block.share)}</span></p>` +
        `<div class="bars" data-part="${block.part}"${named ? '' : ' aria-hidden="true"'}>${bars}</div>` +
        `<p class="axis" aria-hidden="true"><span>${esc(copy.share.axisStart)}</span><span>${esc(copy.share.axisEnd)}</span></p>` +
        `<p class="note">${esc(block.note)}</p></li>`
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
          : `<li class="slot"><span class="what">${esc(slot.what)}</span><span class="when">${esc(slot.when)}</span></li>`,
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
    `<footer><p>${esc(copy.foot.how)}</p><p>${esc(copy.foot.privacy)}</p>` +
    `<p><a class="home" href="${HOME_URL}">${MARK}<span>${esc(copy.foot.home)}</span></a></p></footer>\n` +
    '</body>\n</html>\n'
  );
}
