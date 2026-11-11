import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { root } from './harness.ts';

const css = readFileSync(join(root, 'page/src/style.css'), 'utf8');

/** The color tokens of a block of the stylesheet. */
function tokens(block: string): Record<string, string> {
  const found: Record<string, string> = {};
  for (const [, name, value] of block.matchAll(/--([a-z]+):\s*(#[0-9a-f]{3,6});/g)) {
    found[name!] =
      value!.length === 4 ? `#${[...value!.slice(1)].map((c) => c + c).join('')}` : value!;
  }
  return found;
}

const darkAt = css.indexOf('@media (prefers-color-scheme: dark)');
const light = tokens(css.slice(0, darkAt));
const dark = tokens(css.slice(darkAt, css.indexOf('}', css.indexOf('}', darkAt) + 1) + 1));

function luminance(hex: string): number {
  const channel = (i: number): number => {
    const v = parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

test('the tokens are the ones the page was designed with', () => {
  assert.deepEqual(light, {
    page: '#e9ecef',
    surface: '#ffffff',
    border: '#d2d6dc',
    text: '#0d1014',
    quiet: '#4a515a',
    ok: '#08794b',
    late: '#9a5600',
    down: '#b3261e',
    none: '#68707a',
  });
  assert.deepEqual(dark, {
    page: '#000000',
    surface: '#0a0a0a',
    border: '#2a2a2a',
    text: '#f5f5f5',
    quiet: '#a3a3a3',
    ok: '#6bffb0',
    late: '#ffc46b',
    down: '#ff8a80',
    none: '#6b6b6b',
  });
  assert.match(css, /color-scheme: light dark;/);
});

test('text reads on the page and on a surface, in both schemes', () => {
  for (const [name, scheme] of [
    ['light', light],
    ['dark', dark],
  ] as const) {
    for (const ink of ['text', 'quiet'] as const) {
      for (const ground of ['page', 'surface'] as const) {
        const ratio = contrast(scheme[ink]!, scheme[ground]!);
        assert.equal(ratio >= 4.5, true, `${name} ${ink} on ${ground}: ${ratio.toFixed(2)}`);
      }
    }
  }
});

test('each state color stands out from a surface, in both schemes', () => {
  for (const [name, scheme] of [
    ['light', light],
    ['dark', dark],
  ] as const) {
    for (const state of ['ok', 'late', 'down', 'none'] as const) {
      const ratio = contrast(scheme[state]!, scheme['surface']!);
      assert.equal(ratio >= 3, true, `${name} ${state}: ${ratio.toFixed(2)}`);
    }
  }
});

test('nothing in the stylesheet comes from elsewhere', () => {
  assert.equal(/url\(|@import|@font-face|https?:/.test(css), false);
  assert.match(
    css.replace(/\s+/g, ' '),
    /font: 1rem\/1\.4 system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;/,
  );
});

/** The selectors of each rule that sets a property, media rules flattened. */
function rulesWith(property: string): string[] {
  const found: string[] = [];
  for (const [, selectors, body] of css
    .replace(/\/\*[^]*?\*\//g, '')
    .matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (body!.includes(property)) found.push(selectors!.trim().replace(/\s+/g, ' '));
  }
  return found;
}

test('tabular numbers are only on the lines whose numbers change in place', () => {
  // Never on the body or on a line that holds a part's name: in some system fonts tabular
  // numbers also widen the hyphen, and "Snow-day" was drawn "Snow - day".
  assert.deepEqual(rulesWith('font-variant-numeric'), ['.more, .upd, .share, .when']);
  assert.deepEqual(rulesWith('font-feature-settings'), []);
});

test('with scripts off only the line that says so is shown', () => {
  // The boxes cannot fill in, and the footer does not explain bars that are not there.
  assert.match(
    css.replace(/\s+/g, ' '),
    /@media \(scripting: none\) \{ main, \.how \{ display: none; \} \}/,
  );
});

test('no text of the page ends in a line of one word', () => {
  // The headline, the banner's second line, the line under each part's name and the one line
  // of an empty problems box are balanced: short lines of near one length.
  // So are a row's state, a name in the key and the footer's one sentence, where very large
  // text wraps them.
  assert.deepEqual(rulesWith('text-wrap: balance'), [
    '.lead',
    '.more',
    '.state',
    '.says',
    '.key span',
    '.probs.none',
    '.privacy',
  ]);
  // The longer texts keep their own breaks and only pull a word down to the last line: a
  // problem's heading reads better broken late ("… not working for" / "25 minutes.") than in
  // the middle. The pictures script checks every visible text at nine widths.
  assert.deepEqual(rulesWith('text-wrap: pretty'), [
    '.share',
    '.note',
    '.what',
    '.when',
    'footer p',
  ]);
});

test('large text on a narrow phone: the banner keeps its words whole and its key wraps', () => {
  const flat = css.replace(/\/\*[^]*?\*\//g, '').replace(/\s+/g, ' ');
  // The shape goes above the words when they would have under 12rem beside it, and both sit at
  // the top of the banner's reserved size.
  assert.match(
    flat,
    /\.banner \{ display: flex; flex-wrap: wrap; gap: 0\.75rem; align-items: flex-start; align-content: flex-start;/,
  );
  assert.match(flat, /\.banner > div \{ flex: 1 1 12rem; min-inline-size: 0; \}/);
  // The headline grows with the reader's text and is never held to its column's width: a name
  // that does not fit at the end of a line moves down whole in its own box.
  assert.match(flat, /\.lead \{ font-size: 1\.125rem; font-weight: 600; line-height: 1\.5rem;/);
  assert.match(flat, /\.nm, \.nb \{ display: inline-block; \}/);
  // The rows' words wrap where they do not fit, so nothing pushes the page wider than the screen.
  assert.match(
    flat,
    /\.state \{ display: flex; align-items: center; gap: 0\.4rem; min-block-size: 1\.5rem; text-wrap: balance; \}/,
  );
  assert.match(flat, /\.upd \{ min-block-size: 1\.25rem; \}/);
  // A word wider than the line breaks inside it, and only then: never to balance two lines.
  assert.match(flat, /\.says \{ text-wrap: balance; overflow-wrap: break-word; \}/);
  assert.equal(flat.includes('anywhere'), false);
  assert.equal(
    /cq[iwhb]|vw|vmin|clamp\(|min\(\d/.test(flat.replace(/minmax\(min\(100%/g, '')),
    false,
  );
  // The key has two columns, or one where a name would not fit in half.
  assert.match(
    flat,
    /\.key \{ display: grid; grid-template-columns: repeat\(auto-fit, minmax\(min\(100%, 7rem\), 1fr\)\);/,
  );
});

test('large text on a tablet: what goes side by side asks for room in text units', () => {
  const flat = css.replace(/\/\*[^]*?\*\//g, '').replace(/\s+/g, ' ');
  // Every wide layout asks <main> how much room it has in rem, never the screen in pixels: at
  // 150% text a 768 px tablet has the room of a 512 px phone, and lays out as one.
  assert.match(flat, /main \{ container-type: inline-size; \}/);
  assert.equal(/@media \([a-z-]*width/.test(flat), false);
  const rooms = [...flat.matchAll(/@container \(([^)]*)\)/g)].map((m) => m[1]!);
  for (const room of rooms) assert.match(room, /^min-width: \d+(\.\d+)?rem$/);
  assert.deepEqual(rooms.slice(-2), ['min-width: 21.75rem', 'min-width: 38rem']);
  // The banner's reserve steps down as its room grows (scripts/shots.cjs checks each holds the
  // longest copy at every 2 px of room), and the side gutters stay 16 px at every text size.
  const steps = [
    ...flat.matchAll(
      /@container \(min-width: ([\d.]+)rem\) \{ \.banner \{ min-block-size: ([\d.]+)rem; \} \}/g,
    ),
  ].map((m) => [Number(m[1]), Number(m[2])] as const);
  assert.equal(steps.length >= 8, true);
  for (let i = 1; i < steps.length; i += 1) {
    assert.equal(steps[i]![0] > steps[i - 1]![0], true);
    assert.equal(steps[i]![1] < steps[i - 1]![1], true);
  }
  assert.match(
    flat,
    /main, footer, \.noscript \{ max-inline-size: 44rem; margin-inline: auto; padding-inline: 16px; \}/,
  );
  // One column grows no wider than its row, so a long word or box wraps instead.
  assert.match(flat, /\.row \{ display: grid; grid-template-columns: minmax\(0, 1fr\);/);
  assert.match(flat, /\.slot \{ display: grid; grid-template-columns: minmax\(0, 1fr\);/);
  // Side by side, the time column never takes more than 45% of a problem's row.
  assert.match(
    flat,
    /\.slot \{ grid-template-columns: minmax\(0, 1fr\) fit-content\(45%\); column-gap: 1\.5rem;/,
  );
  // The axis labels keep half a line apart, or "Today" goes down a line and ends under the
  // last bar.
  assert.match(
    flat,
    /\.axis \{ display: flex; flex-wrap: wrap; column-gap: 0\.5rem;[^}]*\} \.axis span:last-child \{ margin-inline-start: auto; \}/,
  );
});

test('a page whose script never starts stops saying Checking, by the stylesheet alone', () => {
  const flat = css.replace(/\/\*[^]*?\*\//g, '').replace(/\s+/g, ' ');
  // Hidden until 10 s have passed without the script's mark on <main>, then drawn in the
  // lead's own grid cell; gone for good once the script has started.
  assert.match(flat, /\.swap \{ display: grid; \} \.swap > \* \{ grid-area: 1 \/ 1; \}/);
  assert.match(flat, /\.stuck \{ visibility: hidden; \} main\.on \.stuck \{ display: none; \}/);
  assert.match(flat, /main:not\(\.on\) \.stuck \{ animation: shown 0\.01s 10s forwards; \}/);
  assert.match(
    flat,
    /main:not\(\.on\) \.swap > :not\(\.stuck\), main:not\(\.on\) \.state \{ animation: gone 0\.01s 10s forwards; \}/,
  );
  assert.match(flat, /@keyframes shown \{ to \{ visibility: visible; \} \}/);
  assert.match(flat, /@keyframes gone \{ to \{ visibility: hidden; \} \}/);
  // The script's first act is the mark, before any fetch.
  const app = readFileSync(join(root, 'page/src/app.ts'), 'utf8');
  assert.match(app, /const said = [^\n]*\n\/\/[^\n]*\nmain\.classList\.add\('on'\);/);
});
