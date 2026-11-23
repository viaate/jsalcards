/** The mode registry (flights spec D2): its order, its addresses and the mode kept on a device. */
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { modesCopy } from '../../copy-modes';
import {
  FIRST_MODE,
  MODES,
  MODE_STORAGE_KEY,
  keepMode,
  keptMode,
  modeHref,
  modeOfSearch,
  openingMode,
  otherParams,
} from '../registry';
import { FLIGHTS_PARAMS } from '../flights/address';
import { RING_LAYER_IDS, isSchoolLayer } from '../schools-layers';

const flights = MODES.find((mode) => mode.key === 'flights');

describe('the modes', () => {
  it('lists Schools first, then Flights, each with a label and a glyph', () => {
    expect(MODES.map((mode) => mode.key)).toEqual(['schools', 'flights']);
    expect(FIRST_MODE.key).toBe('schools');
    for (const mode of MODES) {
      expect(mode.label).toMatch(/^[A-Z]/);
      expect(mode.glyph).toMatch(/^M[\d.]/);
    }
    expect(MODES.map((mode) => mode.label)).toEqual([modesCopy.schools, modesCopy.flights]);
    expect(FIRST_MODE.load).toBeNull();
    expect(flights?.load).toBeTypeOf('function');
  });

  it('reads the mode from the address, and Schools from the bare one', () => {
    expect(modeOfSearch('')).toBeNull();
    expect(modeOfSearch('?mode=flights')?.key).toBe('flights');
    expect(modeOfSearch('?school=1234&mode=flights')?.key).toBe('flights');
    expect(modeOfSearch('?mode=boats')).toBeNull();
  });

  it('opens on the kept mode only at the bare address', () => {
    expect(openingMode('', 'flights').key).toBe('flights');
    expect(openingMode('?', 'flights').key).toBe('flights');
    expect(openingMode('', null).key).toBe('schools');
    expect(openingMode('', 'boats').key).toBe('schools');
    // Every old link (a school, a view) is a link to Schools, whatever mode was kept.
    expect(openingMode('?school=0100001', 'flights').key).toBe('schools');
    expect(openingMode('?at=39.1,-94.6,9', 'flights').key).toBe('schools');
    // The address wins over the kept mode.
    expect(openingMode('?mode=schools', 'flights').key).toBe('schools');
    expect(openingMode('?mode=flights', 'schools').key).toBe('flights');
  });

  it('writes Schools as the bare address and keeps every other parameter', () => {
    if (flights === undefined) throw new Error('no Flights');
    const page = 'https://snowlightmap.com/?at=39.1,-94.6,9&school=0100001';
    const there = modeHref(page, flights, ['school']);
    expect(new URL(there).searchParams.get('mode')).toBe('flights');
    expect(new URL(there).searchParams.get('school')).toBeNull();
    expect(new URL(there).searchParams.get('at')).toBe('39.1,-94.6,9');
    const back = modeHref(`${there}&airport=MCI`, FIRST_MODE, ['airport']);
    expect(new URL(back).search).toBe('?at=39.1%2C-94.6%2C9');
  });

  it('takes off only what other modes own as a mode shows', () => {
    if (flights === undefined) throw new Error('no Flights');
    expect(otherParams(flights)).toEqual(['school', 'district', 'zip']);
    expect(otherParams(FIRST_MODE)).toEqual([...FLIGHTS_PARAMS]);
    const boats = { key: 'boats', label: 'Boats', glyph: 'M1 1h1', params: ['harbor'], load: null };
    const modes = [...MODES, boats];
    expect(otherParams(boats, modes)).toEqual(['school', 'district', 'zip', ...FLIGHTS_PARAMS]);
    expect(otherParams(flights, modes)).toEqual(['school', 'district', 'zip', 'harbor']);
    expect(openingMode('?mode=boats', null, modes).key).toBe('boats');
    expect(openingMode('', 'boats', modes).key).toBe('boats');
  });

  it('keeps the mode on the device, and works with storage off', () => {
    const kept = new Map<string, string>();
    const storage = {
      getItem: (key: string) => kept.get(key) ?? null,
      setItem: (key: string, value: string) => {
        kept.set(key, value);
      },
    };
    if (flights === undefined) throw new Error('no Flights');
    keepMode(storage, flights);
    expect(kept.get(MODE_STORAGE_KEY)).toBe('flights');
    expect(keptMode(storage)).toBe('flights');
    const broken = {
      getItem: (): string | null => {
        throw new Error('SecurityError');
      },
      setItem: (): void => {
        throw new Error('QuotaExceededError');
      },
    };
    expect(keptMode(broken)).toBeNull();
    expect(() => {
      keepMode(broken, flights);
    }).not.toThrow();
    expect(keptMode(null)).toBeNull();
  });
});

describe('Schools’ layers while another mode shows', () => {
  it('names the later rings as the rings module does', () => {
    const rings = readFileSync(path.join(process.cwd(), 'src/map/later-rings.ts'), 'utf8');
    expect(rings).toMatch(
      /LATER_RING_LAYERS = \[LATER_RINGS, LATER_RINGS_NEAR, LATER_RINGS_CLOSE\]/,
    );
    const named = ['LATER_RINGS', 'LATER_RINGS_NEAR', 'LATER_RINGS_CLOSE'].map(
      (name) => new RegExp(`export const ${name} = '([a-z-]+)'`).exec(rings)?.[1],
    );
    expect([...RING_LAYER_IDS]).toEqual(named);
  });

  it('hides the glow, the school layers and anything on the school tiles, never the basemap', () => {
    expect(isSchoolLayer({ id: 'snowlight-glow' })).toBe(true);
    expect(isSchoolLayer({ id: 'school-dots' })).toBe(true);
    expect(isSchoolLayer({ id: 'later-rings-near' })).toBe(true);
    expect(isSchoolLayer({ id: 'anything', source: 'schools' })).toBe(true);
    expect(isSchoolLayer({ id: 'us-states' })).toBe(false);
    expect(isSchoolLayer({ id: 'flights-airport-dots', source: 'flights-airports' })).toBe(false);
  });
});

describe('the first script', () => {
  it('never imports the modes: the app starts them from its lazy services', () => {
    const app = readFileSync(path.join(process.cwd(), 'src/App.svelte'), 'utf8');
    const main = readFileSync(path.join(process.cwd(), 'src/main.ts'), 'utf8');
    expect(app).not.toMatch(/modes\//);
    expect(main).not.toMatch(/modes\//);
    const boot = readFileSync(path.join(process.cwd(), 'src/app/boot.ts'), 'utf8');
    expect(boot).toMatch(/import\('\.\.\/modes\/host'\)/);
    expect(boot).not.toMatch(/^import .*modes\//m);
  });
});
