// @vitest-environment node
import { describe, expect, it } from 'vitest';

import {
  EMPTY_STATE,
  VIEW_LIMITS,
  coordinateDecimals,
  formatView,
  mergeHref,
  mergeQuery,
  parseUrlState,
  parseView,
  roundView,
  sameState,
  shareHref,
  stateQuery,
} from '../url';
import type { UrlState, View } from '../url';

const SCHOOL = '010000500870';
const PRIVATE = 'A9106011';
const DISTRICT = '0100005';

describe('parseUrlState', () => {
  it('reads each selection and the view', () => {
    expect(parseUrlState(`?school=${SCHOOL}`)).toEqual({
      selection: { kind: 'school', id: SCHOOL },
      view: null,
    });
    expect(parseUrlState(`?school=${PRIVATE.toLowerCase()}`).selection).toEqual({
      kind: 'school',
      id: PRIVATE,
    });
    expect(parseUrlState(`district=${DISTRICT}`).selection).toEqual({
      kind: 'district',
      id: DISTRICT,
    });
    expect(parseUrlState('?zip=02139').selection).toEqual({ kind: 'zip', id: '02139' });
    expect(parseUrlState('?at=41.8781,-87.6298,10.25').view).toEqual({
      lat: 41.8781,
      lon: -87.6298,
      zoom: 10.25,
    });
  });

  it('reads nothing from an empty or junk query', () => {
    for (const search of ['', '?', '?&&', '?=', '?school', '?school=', '?foo=bar', '?%zz=1']) {
      expect(parseUrlState(search)).toEqual(EMPTY_STATE);
    }
  });

  it('prefers the most specific selection', () => {
    const state = parseUrlState(`?zip=02139&district=${DISTRICT}&school=${SCHOOL}`);
    expect(state.selection).toEqual({ kind: 'school', id: SCHOOL });
    expect(parseUrlState(`?zip=02139&district=${DISTRICT}`).selection?.kind).toBe('district');
  });

  it('falls through to the next kind when a value is junk', () => {
    expect(parseUrlState('?school=nope&zip=02139').selection).toEqual({ kind: 'zip', id: '02139' });
  });

  it('takes the first valid value of a repeated parameter', () => {
    expect(parseUrlState(`?school=bad&school=${SCHOOL}&school=${PRIVATE}`).selection).toEqual({
      kind: 'school',
      id: SCHOOL,
    });
  });

  it('decodes percent-escapes and never throws on bad ones', () => {
    expect(parseUrlState(`?school=%20${SCHOOL}%20`).selection?.id).toBe(SCHOOL);
    expect(parseUrlState('?at=41.5%2C-87.5%2C9').view).toEqual({ lat: 41.5, lon: -87.5, zoom: 9 });
    expect(() => parseUrlState('?school=%E0%A4%A&at=%')).not.toThrow();
    expect(parseUrlState('?school=%E0%A4%A').selection).toBeNull();
  });

  it('ignores parameter names in another case', () => {
    expect(parseUrlState(`?School=${SCHOOL}&AT=1,2,3`)).toEqual(EMPTY_STATE);
  });
});

describe('parseView', () => {
  it('clamps latitude and zoom and wraps longitude', () => {
    expect(parseView('89,0,5')).toEqual({ lat: VIEW_LIMITS.maxLat, lon: 0, zoom: 5 });
    expect(parseView('-95,10,5')?.lat).toBe(-VIEW_LIMITS.maxLat);
    expect(parseView('40,190,5')?.lon).toBeCloseTo(-170, 10);
    expect(parseView('40,-540,5')?.lon).toBe(-180);
    expect(parseView('40,-100,0')?.zoom).toBe(VIEW_LIMITS.minZoom);
    expect(parseView('40,-100,99')?.zoom).toBe(VIEW_LIMITS.maxZoom);
  });

  it.each([
    '',
    '40',
    '40,-100',
    '40,-100,5,1',
    '40,,5',
    ',,',
    'NaN,-100,5',
    'Infinity,-100,5',
    '1e2,-100,5',
    '0x10,-100,5',
    '40,-100,5z',
    '40;-100;5',
    '40 ,-100,5x',
    '12345,-100,5',
    '4.0.1,-100,5',
    `${'1'.repeat(70)},0,5`,
  ])('rejects %j', (raw) => {
    expect(parseView(raw)).toBeNull();
  });

  it('accepts signs, spaces around numbers and leading dots', () => {
    expect(parseView(' 40.5 , -100.25 , 4 ')).toEqual({ lat: 40.5, lon: -100.25, zoom: 4 });
    expect(parseView('.5,-.5,3.')).toEqual({ lat: 0.5, lon: -0.5, zoom: 3 });
  });
});

describe('formatView', () => {
  it('keeps about a pixel of precision at each zoom', () => {
    expect(coordinateDecimals(1)).toBe(2);
    expect(coordinateDecimals(4)).toBe(2);
    expect(coordinateDecimals(10)).toBe(4);
    expect(coordinateDecimals(16)).toBe(5);
    expect(formatView({ lat: 41.878113, lon: -87.629799, zoom: 4.126 })).toBe('41.88,-87.63,4.13');
    expect(formatView({ lat: 41.878113, lon: -87.629799, zoom: 12 })).toBe('41.8781,-87.6298,12');
  });

  it('drops trailing zeros and negative zero', () => {
    expect(formatView({ lat: 40, lon: -0.0001, zoom: 3 })).toBe('40,0,3');
    expect(formatView({ lat: 40.5, lon: -100.5, zoom: 5.5 })).toBe('40.5,-100.5,5.5');
  });

  it('wraps a longitude that rounds up to 180', () => {
    expect(formatView({ lat: 0, lon: 179.999, zoom: 3 })).toBe('0,-180,3');
  });

  it('throws on non-finite numbers', () => {
    expect(() => formatView({ lat: Number.NaN, lon: 0, zoom: 3 })).toThrow(RangeError);
  });

  it('round-trips: formatting a parsed view gives the same text', () => {
    let seed = 7;
    const random = (): number => {
      seed = (seed * 16807) % 2147483647;
      return seed / 2147483647;
    };
    for (let i = 0; i < 2000; i++) {
      const view: View = {
        lat: (random() - 0.5) * 200,
        lon: (random() - 0.5) * 800,
        zoom: random() * 20 - 2,
      };
      const text = formatView(view);
      const parsed = parseView(text);
      expect(parsed).not.toBeNull();
      if (parsed !== null) expect(formatView(parsed)).toBe(text);
      expect(roundView(view)).toEqual(parsed);
    }
  });
});

describe('writing', () => {
  const state: UrlState = {
    selection: { kind: 'school', id: SCHOOL },
    view: { lat: 41.8781, lon: -87.6298, zoom: 10 },
  };

  it('writes the owned parameters in a fixed order, commas unescaped', () => {
    expect(stateQuery(state)).toBe(`school=${SCHOOL}&at=41.8781,-87.6298,10`);
    expect(stateQuery({ selection: { kind: 'zip', id: '02139' }, view: null })).toBe('zip=02139');
    expect(stateQuery(EMPTY_STATE)).toBe('');
  });

  it('refuses to write a malformed id', () => {
    expect(() => stateQuery({ selection: { kind: 'school', id: '12' }, view: null })).toThrow(
      RangeError,
    );
    expect(() => stateQuery({ selection: { kind: 'district', id: SCHOOL }, view: null })).toThrow(
      RangeError,
    );
  });

  it('keeps foreign parameters byte for byte and in order', () => {
    const search = '?utm_source=a%20b&school=bad&x=1&x=2&flag&at=junk&q=%E2%9C%93';
    expect(mergeQuery(search, state)).toBe(
      `?school=${SCHOOL}&at=41.8781,-87.6298,10&utm_source=a%20b&x=1&x=2&flag&q=%E2%9C%93`,
    );
  });

  it('removes every owned parameter it replaces, junk or not', () => {
    expect(mergeQuery(`?zip=02139&district=${DISTRICT}&school=x&at=1,2`, EMPTY_STATE)).toBe('');
    expect(mergeQuery('?a=1&zip=02139', EMPTY_STATE)).toBe('?a=1');
  });

  it('keeps the path and hash of the page', () => {
    expect(mergeHref('https://example.org/snow/?a=1#legend', state)).toBe(
      `https://example.org/snow/?school=${SCHOOL}&at=41.8781,-87.6298,10&a=1#legend`,
    );
    expect(mergeHref('https://example.org/?school=1', EMPTY_STATE)).toBe('https://example.org/');
  });

  it('makes a clean share link: owned parameters only, no hash', () => {
    expect(shareHref('https://example.org/?utm_source=x&fbclid=y#z', state)).toBe(
      `https://example.org/?school=${SCHOOL}&at=41.8781,-87.6298,10`,
    );
    expect(shareHref('https://example.org/?a=1', EMPTY_STATE)).toBe('https://example.org/');
  });

  it('reads back what it writes', () => {
    const href = mergeHref('https://example.org/?keep=1', state);
    expect(sameState(parseUrlState(new URL(href).search), state)).toBe(true);
  });
});
