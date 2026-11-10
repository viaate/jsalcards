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

test('the lines read first are balanced, so none ends in a line of one word', () => {
  assert.deepEqual(rulesWith('text-wrap: balance'), ['.lead', '.what', '.probs.none']);
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
