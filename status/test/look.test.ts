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
    page: '#f4f6f8',
    surface: '#ffffff',
    border: '#dde1e6',
    text: '#1c2127',
    quiet: '#59626d',
    link: '#0b5cba',
    ok: '#1b7f40',
    late: '#a65c00',
    down: '#cf2c2c',
    none: '#8c949e',
    before: '#e6e9ed',
    bar: '#34a35a',
    bok: '#1f8442',
    blate: '#a35400',
    bdown: '#c42b2b',
    bnone: '#5e6873',
    on: '#ffffff',
  });
  assert.deepEqual(dark, {
    page: '#0c0f13',
    surface: '#151a20',
    border: '#2a313a',
    text: '#e9edf1',
    quiet: '#9ba5b0',
    link: '#79b4ff',
    ok: '#3ccf6e',
    late: '#f0a83a',
    down: '#ff6b63',
    none: '#6c7682',
    before: '#262d36',
    bar: '#34b862',
    bok: '#1f8442',
    blate: '#a35400',
    bdown: '#c42b2b',
    bnone: '#4f5965',
    on: '#ffffff',
  });
  assert.match(css, /color-scheme: light dark;/);
});

const SCHEMES = [
  ['light', light],
  ['dark', dark],
] as const;

test('text reads on the page and on a surface, in both schemes', () => {
  for (const [name, scheme] of SCHEMES) {
    // The state words and a problem's heading are drawn in their state's color.
    for (const ink of ['text', 'quiet', 'link', 'ok', 'late', 'down'] as const) {
      for (const ground of ['page', 'surface'] as const) {
        const ratio = contrast(scheme[ink]!, scheme[ground]!);
        assert.equal(ratio >= 4.5, true, `${name} ${ink} on ${ground}: ${ratio.toFixed(2)}`);
      }
    }
  }
});

test("the banner's white words read on each of its colors", () => {
  for (const [name, scheme] of SCHEMES) {
    for (const ground of ['bok', 'blate', 'bdown', 'bnone'] as const) {
      const ratio = contrast(scheme['on']!, scheme[ground]!);
      assert.equal(ratio >= 4.5, true, `${name} on ${ground}: ${ratio.toFixed(2)}`);
    }
  }
});

test('each bar of a state stands out from a surface, and a day with nothing to show does not', () => {
  for (const [name, scheme] of SCHEMES) {
    for (const state of ['bar', 'late', 'down', 'none'] as const) {
      const ratio = contrast(scheme[state]!, scheme['surface']!);
      assert.equal(ratio >= 2.9, true, `${name} ${state}: ${ratio.toFixed(2)}`);
    }
    // Before the checks began: a light grey bar, quieter than any state.
    const before = contrast(scheme['before']!, scheme['surface']!);
    assert.equal(before > 1.1 && before < 1.5, true, `${name} before: ${before.toFixed(2)}`);
  }
});

test('nothing in the stylesheet comes from elsewhere', () => {
  assert.equal(/url\(|@import|@font-face|https?:/.test(css), false);
  assert.match(
    css.replace(/\s+/g, ' '),
    /font: 1rem\/1\.5 system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;/,
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

const flat = css.replace(/\/\*[^]*?\*\//g, '').replace(/\s+/g, ' ');

test('tabular numbers are only on the lines whose numbers change in place', () => {
  // Never on the body or on a line that holds a part's name: in some system fonts tabular
  // numbers also widen the hyphen, and "Snow-day" was drawn "Snow - day".
  assert.deepEqual(rulesWith('font-variant-numeric'), ['.more, .upd, .mid, .when']);
  assert.deepEqual(rulesWith('font-feature-settings'), []);
});

test('with scripts off only the line that says so is shown', () => {
  // The boxes cannot fill in, and the footer does not explain bars that are not there.
  assert.match(flat, /@media \(scripting: none\) \{ main, \.how \{ display: none; \} \}/);
});

test('no text of the page ends in a line of one word', () => {
  // The headline, the banner's second line, a state, the share on its own line and the
  // footer's one sentence are balanced: short lines of near one length.
  assert.deepEqual(rulesWith('text-wrap: balance'), [
    '.lead',
    '.more',
    '.state',
    '.tip',
    '.mid',
    '.none, .empty',
    '.privacy',
  ]);
  // The longer texts keep their own breaks and only pull a word down to the last line. The
  // pictures script checks every visible text at nine widths.
  assert.deepEqual(rulesWith('text-wrap: pretty'), ['.end', '.what', '.when', 'footer p']);
});

test('one banner: a solid bar in the state color, its words centred, its size kept', () => {
  assert.match(
    flat,
    /\.banner \{ display: flex; flex-wrap: wrap; align-items: center; align-content: center; gap: 0\.75rem;[^}]*background: var\(--bnone\); color: var\(--on\); min-block-size: 14\.5rem; \}/,
  );
  for (const [state, token] of [
    ['ok', 'bok'],
    ['late', 'blate'],
    ['down', 'bdown'],
  ])
    assert.match(flat, new RegExp(`\\.st-${state} \\{ background: var\\(--${token}\\); \\}`));
  // Its reserve steps down as its room grows (scripts/shots.cjs checks each holds every copy
  // at every 2 px of room), to one bar's height when its two lines go side by side.
  const steps = [
    ...flat.matchAll(
      /@container \(min-width: ([\d.]+)rem\) \{ \.banner \{ (?:padding-inline: 20px; )?min-block-size: ([\d.]+)rem; \} \}/g,
    ),
  ].map((m) => [Number(m[1]), Number(m[2])] as const);
  assert.equal(steps.length >= 8, true);
  for (let i = 1; i < steps.length; i += 1) {
    assert.equal(steps[i]![0] > steps[i - 1]![0], true);
    assert.equal(steps[i]![1] < steps[i - 1]![1], true);
  }
  assert.deepEqual(steps.at(-1), [45, 3.5]);
  // Its words grow with the reader's text; a name never splits.
  assert.match(flat, /\.lead \{ font-size: 1\.125rem; font-weight: 600; line-height: 1\.5rem;/);
  assert.match(flat, /\.nm, \.nb \{ display: inline-block; \}/);
});

test('ninety bars fill each row, and the tip of a day stays inside it', () => {
  assert.match(
    flat,
    /\.bars \{ position: relative; display: grid; grid-template-columns: repeat\(90, 1fr\);/,
  );
  assert.match(flat, /\.bar \{ border-radius: 1px; background: var\(--before\); \}/);
  assert.match(
    flat,
    /\.tip \{ position: absolute;[^}]*inset-inline-start: calc\(var\(--at, 0\) \* 100%\);[^}]*max-inline-size: 100%;[^}]*transform: translateX\(calc\(var\(--at, 0\) \* -100%\)\);/,
  );
  // The list of past problems is as long as its days: no screen-tall hold under a short one.
  assert.equal(/100vh|min-block-size: 100/.test(flat), false);
  // While the page waits the footer is not drawn, so it never moves when the list fills in.
  assert.match(flat, /main\.wait ~ footer \{ display: none; \}/);
  assert.match(flat, /@media \(scripting: none\) \{ main\.wait ~ footer \{ display: block; \} \}/);
  // With no share the rule between the axis labels runs whole.
  assert.match(flat, /\.mid:empty \{ gap: 0; \}/);
  // On a narrow row the share has a line of its own under the rule, kept while the page waits;
  // from 21.5rem it sits in the middle of the rule.
  assert.match(flat, /\.mid \{ grid-row: 2; grid-column: 1 \/ -1; min-block-size: 1\.125rem;/);
  assert.match(flat, /@container \(min-width: 21\.5rem\) \{ \.axis \{ display: flex; \}/);
});

test('what goes side by side asks for room in text units', () => {
  // Every wide layout asks <main> how much room it has in rem, never the screen in pixels: at
  // 150% text a 768 px tablet has the room of a 512 px phone, and lays out as one.
  assert.match(flat, /main \{ container-type: inline-size;/);
  assert.equal(/@media \([a-z-]*width/.test(flat), false);
  const rooms = [...flat.matchAll(/@container \(([^)]*)\)/g)].map((m) => m[1]!);
  for (const room of rooms) assert.match(room, /^min-width: \d+(\.\d+)?rem$/);
  assert.equal(/cq[iwhb]|vw|vmin|clamp\(/.test(flat), false);
  // The side gutters stay 16 px at every text size.
  assert.match(
    flat,
    /\.bar-top, main, \.foot-in, \.noscript \{ max-inline-size: 61\.25rem; margin-inline: auto; padding-inline: 16px; \}/,
  );
  // One column grows no wider than its row, so a long word or box wraps instead.
  assert.match(flat, /\.parts \{ display: grid; grid-template-columns: minmax\(0, 1fr\);/);
  assert.match(flat, /\.parts \{ grid-template-columns: repeat\(2, minmax\(0, 1fr\)\); \}/);
});

test('a page whose script never starts stops saying Checking, by the stylesheet alone', () => {
  const flat = css.replace(/\/\*[^]*?\*\//g, '').replace(/\s+/g, ' ');
  // Hidden until 10 s have passed without the script's mark on <main>, then drawn in the
  // lead's own grid cell; gone for good once the script has started.
  assert.match(flat, /\.swap \{ display: grid;[^}]*\} \.swap > \* \{ grid-area: 1 \/ 1; \}/);
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
