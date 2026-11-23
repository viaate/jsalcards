/** Flights mode's search and its addresses. */
import { describe, expect, it } from 'vitest';

import { backOf, backState, hrefOfView, viewOfSearch } from '../address';
import type { FlightsView } from '../address';
import { findAirports, searchFlights } from '../search';
import { AIRPORTS } from './fixtures';

describe('search', () => {
  it('finds an airport by its code, its city or its name', () => {
    expect(findAirports(AIRPORTS, 'mci')[0]?.code).toBe('MCI');
    expect(findAirports(AIRPORTS, 'Kansas')[0]?.code).toBe('MCI');
    expect(findAirports(AIRPORTS, 'o’hare')[0]?.code).toBe('ORD');
    expect(findAirports(AIRPORTS, 'zzz')).toEqual([]);
  });

  it('reads a route in the ways people type it', () => {
    for (const text of [
      'MCI to LAX',
      'mci lax',
      'MCI-LAX',
      'MCI > LAX',
      'Kansas City to Los Angeles',
    ]) {
      expect(searchFlights(AIRPORTS, text)[0]?.hit, text).toEqual({
        kind: 'route',
        from: 'MCI',
        to: 'LAX',
      });
    }
  });

  it('reads an airline by its name as its code', () => {
    expect(searchFlights(AIRPORTS, 'Southwest 2510 MCI')[0]?.hit).toEqual({
      kind: 'flight',
      carrier: 'WN',
      number: 2510,
      from: 'MCI',
    });
    expect(searchFlights(AIRPORTS, 'delta airlines 12', 'MCI')[0]?.hit).toEqual({
      kind: 'flight',
      carrier: 'DL',
      number: 12,
      from: 'MCI',
    });
  });

  it('reads a flight number, with the airport typed after it or the one open', () => {
    expect(searchFlights(AIRPORTS, 'WN 1234')[0]?.hit).toEqual({
      kind: 'flight',
      carrier: 'WN',
      number: 1234,
      from: null,
    });
    expect(searchFlights(AIRPORTS, 'wn1234 mci')[0]?.hit).toMatchObject({ from: 'MCI' });
    expect(searchFlights(AIRPORTS, 'AA 12 from DEN')[0]?.hit).toMatchObject({ from: 'DEN' });
    expect(searchFlights(AIRPORTS, 'B6 400', 'ORD')[0]?.hit).toMatchObject({
      carrier: 'B6',
      from: 'ORD',
    });
  });

  it('finds nothing in an empty field', () => {
    expect(searchFlights(AIRPORTS, '   ')).toEqual([]);
  });
});

describe('addresses', () => {
  const views: FlightsView[] = [
    { kind: 'home' },
    { kind: 'airport', code: 'MCI' },
    { kind: 'route', from: 'MCI', to: 'LAX', day: 0 },
    { kind: 'route', from: 'MCI', to: 'LAX', day: 1 },
    { kind: 'flight', carrier: 'WN', number: 1234, from: 'MCI', day: 2 },
    { kind: 'storm', id: 'MCI-2025-01-05' },
    { kind: 'storms' },
    { kind: 'record' },
  ];

  it.each(views)('gives every screen a link of its own: %o', (view) => {
    const href = hrefOfView('https://snowlightmap.com/?mode=flights&at=39,-94,5', view);
    expect(new URL(href).searchParams.get('mode')).toBe('flights');
    expect(new URL(href).searchParams.get('at')).toBe('39,-94,5');
    expect(viewOfSearch(new URL(href).search)).toEqual(view);
  });

  it('reads a bad link as the map alone', () => {
    expect(viewOfSearch('?airport=KANSAS')).toEqual({ kind: 'home' });
    expect(viewOfSearch('?route=MCI-MCI')).toEqual({ kind: 'home' });
    expect(viewOfSearch('?flight=WN-MCI')).toEqual({ kind: 'home' });
    expect(viewOfSearch('?route=mci-lax&day=9')).toEqual({
      kind: 'route',
      from: 'MCI',
      to: 'LAX',
      day: 0,
    });
  });
});

describe('a route entry’s picked cell (TRAV-R13-S2)', () => {
  it('keeps the cell and row in the history state, beside what else it holds', () => {
    const back = { day: 1, block: 2, row: 3 };
    const state = backState({ other: 'kept' }, back);
    expect(state).toEqual({ other: 'kept', flightsBack: back });
    expect(backOf(state)).toEqual(back);
    expect(backOf(backState(null, back))).toEqual(back);
  });

  it('reads no cell from a state it did not write, or a bad one', () => {
    for (const state of [
      null,
      undefined,
      'flightsBack',
      {},
      { flightsBack: null },
      { flightsBack: { day: 1, block: 2 } },
      { flightsBack: { day: -1, block: 0, row: 0 } },
      { flightsBack: { day: 4, block: 0, row: 0 } },
      { flightsBack: { day: 0, block: 5, row: 0 } },
      { flightsBack: { day: 0, block: 1.5, row: 0 } },
      { flightsBack: { day: '0', block: 0, row: 0 } },
    ])
      expect(backOf(state)).toBeNull();
  });
});
