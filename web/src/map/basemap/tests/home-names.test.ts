// @vitest-environment node
/**
 * The national city names the screen's edges would cut at the home view: the
 * ones whose label runs part on, part off the screen, and no others.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { mercatorXFromLng, mercatorYFromLat } from '../../glow/mercator';
import type { MapView } from '../bounds';
import { cityNamesOf, namesCutByEdges, textMeasure } from '../home-names';
import type { CityName, MeasureText } from '../home-names';
import { WHOLE_COUNTRY, viewLimits } from '../limits';
import { CITY_NAME_BANDS, CITY_NAME_HALO, cityNameSize } from '../style';
import type { UsLinesData } from '../style';
import { US_LINES_FILE } from '../us-geo';

const US_LINES = JSON.parse(
  readFileSync(
    fileURLToPath(new URL(`../../../../public/${US_LINES_FILE}`, import.meta.url)),
    'utf8',
  ),
) as UsLinesData;

/** Every letter half a size wide: a name of n letters at size s is n * s / 2 wide. */
const HALF_EM: MeasureText = (text, size) => (text.length * size) / 2;

const SCREEN = { width: 400, height: 800 };
const VIEW: MapView = { lat: 38, lon: -90, zoom: 4 };

/** A city at a screen point of VIEW on SCREEN. */
function cityAt(name: string, x: number, y: number, rank = 0): CityName {
  const scale = 512 * 2 ** VIEW.zoom;
  const worldX = mercatorXFromLng(VIEW.lon) + (x - SCREEN.width / 2) / scale;
  const worldY = mercatorYFromLat(VIEW.lat) + (y - SCREEN.height / 2) / scale;
  const lon = worldX * 360 - 180;
  const lat = (Math.atan(Math.sinh(Math.PI * (1 - 2 * worldY))) * 180) / Math.PI;
  return { name, rank, lon, lat };
}

describe('the city names', () => {
  it('are read from the bundled file: every city, with its name, rank and place', () => {
    const cities = cityNamesOf(US_LINES);
    expect(cities.length).toBeGreaterThan(200);
    expect(cities[0]).toMatchObject({ name: 'New York', rank: 0 });
    for (const city of cities) {
      expect(city.name).not.toBe('');
      expect(Number.isInteger(city.rank)).toBe(true);
      expect(city.lon).toBeGreaterThan(-125);
      expect(city.lon).toBeLessThan(-66);
      expect(city.lat).toBeGreaterThan(24);
      expect(city.lat).toBeLessThan(50);
    }
    // Anything else in the file, or anything malformed, is not a city.
    expect(
      cityNamesOf({
        type: 'FeatureCollection',
        features: [
          { type: 'Feature', properties: { kind: 'land' }, geometry: { type: 'Point' } },
          { type: 'Feature', properties: { kind: 'city', name: 'Nowhere', rank: 1 } },
          {
            type: 'Feature',
            properties: { kind: 'city', name: 'Halfway', rank: 2 },
            geometry: { type: 'Point', coordinates: ['a', 3] },
          },
          null,
        ],
      }),
    ).toEqual([]);
  });
});

describe('names cut by the edges', () => {
  const size = cityNameSize(VIEW.zoom);
  // "Edgeton" is 7 letters: 3.5 sizes wide, plus letter spacing, halo and a gap.
  const half = (7 * size) / 4;

  it("leaves out a name the screen's left or right edge runs through", () => {
    const cities = [
      cityAt('Edgeton', 2, 400),
      cityAt('Farside', SCREEN.width - 3, 300),
      cityAt('Midland', 200, 400),
    ];
    expect(namesCutByEdges(cities, VIEW, SCREEN, HALF_EM)).toEqual(['Edgeton', 'Farside']);
  });

  it('keeps a name wholly on screen, however near the edge, and ignores one wholly off it', () => {
    const margin = half + CITY_NAME_HALO + 4;
    const cities = [
      cityAt('Edgeton', margin, 400),
      cityAt('Edgeton', SCREEN.width - margin, 400),
      cityAt('Edgeton', -margin, 400),
      cityAt('Edgeton', SCREEN.width + margin, 400),
    ];
    expect(namesCutByEdges(cities, VIEW, SCREEN, HALF_EM)).toEqual([]);
  });

  it('measures only the names near an edge', () => {
    const measured: string[] = [];
    const spy: MeasureText = (text, size) => {
      measured.push(text);
      return HALF_EM(text, size);
    };
    const cities = [
      cityAt('Midland', 200, 400),
      cityAt('Edgeton', 2, 300),
      cityAt('Faraway', -300, 400),
      cityAt('Farside', SCREEN.width - 3, 500),
    ];
    expect(namesCutByEdges(cities, VIEW, SCREEN, spy)).toEqual(['Edgeton', 'Farside']);
    expect(measured).toEqual(['Edgeton', 'Farside']);
  });

  it('leaves out a name the top or bottom edge runs through', () => {
    const cities = [cityAt('Edgeton', 200, 1), cityAt('Farside', 200, SCREEN.height - 1)];
    expect(namesCutByEdges(cities, VIEW, SCREEN, HALF_EM)).toEqual(['Edgeton', 'Farside']);
  });

  it('only weighs the names the map shows at that zoom', () => {
    const shown = CITY_NAME_BANDS.filter((band) => band.zoom <= VIEW.zoom).at(-1)?.names ?? 0;
    const cities = [cityAt('Shown', 1, 400, shown - 1), cityAt('Unshown', 1, 500, shown)];
    expect(namesCutByEdges(cities, VIEW, SCREEN, HALF_EM)).toEqual(['Shown']);
    // Below the first band, no name at all.
    const far = { ...VIEW, zoom: (CITY_NAME_BANDS[0]?.zoom ?? 3) - 0.5 };
    expect(namesCutByEdges(cities, far, SCREEN, HALF_EM)).toEqual([]);
  });

  it("at a laptop's national view cuts none: the whole country is inside the frame", () => {
    const screen = { width: 1440, height: 900 };
    const limits = viewLimits(screen, { top: 88, right: 48, bottom: 48, left: 48 }, WHOLE_COUNTRY);
    const wide: MeasureText = (text, size) => text.length * size * 0.66;
    expect(namesCutByEdges(cityNamesOf(US_LINES), limits.home, screen, wide)).toEqual([]);
  });

  it('measures each letter in the face once it is loaded, and generously before', () => {
    const widths: Record<string, number> = { B: 7, o: 6, s: 5, t: 4, n: 6 };
    let loaded = false;
    const fonts: string[] = [];
    const context = {
      font: '',
      measureText: (character: string) => {
        fonts.push(context.font);
        return { width: widths[character] ?? 0 };
      },
    };
    const doc = {
      createElement: () => ({ getContext: () => context }),
      fonts: { check: () => loaded },
    } as unknown as Parameters<typeof textMeasure>[0];
    const measure = textMeasure(doc);
    // Not loaded: four fifths of the size for every letter, wider than Geist sets any name.
    expect(measure('Boston', 10)).toBeCloseTo(6 * 10 * 0.8, 9);
    loaded = true;
    expect(measure('Boston', 10)).toBe(7 + 6 + 5 + 4 + 6 + 6);
    expect(new Set(fonts)).toEqual(new Set(['500 10px "Geist Variable"']));
    // No canvas, or no font set to ask: generous again.
    const bare = { createElement: () => ({ getContext: () => null }) } as unknown as Parameters<
      typeof textMeasure
    >[0];
    expect(textMeasure(bare)('Boston', 10)).toBeCloseTo(6 * 10 * 0.8, 9);
  });
});
