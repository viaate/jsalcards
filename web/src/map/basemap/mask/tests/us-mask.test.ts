// @vitest-environment node
/**
 * The US mask as built (public/geo/us-mask.*.pmtiles, from
 * scripts/build-us-mask.mjs), read the way the street tile workers read it.
 *
 * Along the border with Canada and Mexico, a point 25 m inside the US is left
 * uncovered and a point 25 m outside is covered, at street zoom, in rivers,
 * lakes and on land; and the mask's edge passes within a few meters of the
 * official boundary there. The boundary points are taken from the build's
 * sources: the International Boundary Commission's US-Canada boundary
 * (version 1.3) and TIGER/Line 2025's international boundary, whose US-Mexico
 * section comes from the International Boundary and Water Commission.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { gunzipSync } from 'node:zlib';

import { describe, expect, it } from 'vitest';

import { US_MASK_FILE, US_MASK_MAX_ZOOM, US_MASK_MIN_ZOOM } from '../../us-mask';
import { MASK_BOX } from '../format';
import { MaskIndex } from '../geometry';
import { EXTENT } from '../mvt';
import { ArchiveReader, decodeHeader } from '../pmtiles';
import { tileMask } from '../source';
import type { TileMask } from '../source';

const bytes = readFileSync(resolve(import.meta.dirname, '../../../../../public', US_MASK_FILE));
const reader = new ArchiveReader(
  (offset, length) => Promise.resolve(bytes.subarray(offset, offset + length)),
  (data) => Promise.resolve(gunzipSync(data)),
);

type LonLat = readonly [lon: number, lat: number];

/** A place in the world as a tile and its tile units at zoom z. */
function locate(lonLat: LonLat, z: number): { x: number; y: number; px: number; py: number } {
  const [lon, lat] = lonLat;
  const world = 2 ** z;
  const sin = Math.sin((lat * Math.PI) / 180);
  const mx = ((lon + 180) / 360) * world;
  const my = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * world;
  const x = Math.floor(mx);
  const y = Math.floor(my);
  return { x, y, px: (mx - x) * EXTENT, py: (my - y) * EXTENT };
}

/** Whether the mask covers a place, read at zoom z as a street tile there would be. */
async function covered(lonLat: LonLat, z: number): Promise<boolean> {
  const { x, y, px, py } = locate(lonLat, z);
  const mask = await tileMask(reader, z, x, y);
  if (mask.kind !== 'mixed') return mask.kind === 'outside';
  return new MaskIndex(mask.rings, MASK_BOX).contains(px, py);
}

/** Meters from a place to the nearest edge of the mask in its street tile, and to the border line. */
async function distances(lonLat: LonLat, z: number): Promise<{ edge: number; line: number }> {
  const { x, y, px, py } = locate(lonLat, z);
  const mask: TileMask = await tileMask(reader, z, x, y);
  const metersPerUnit = (40_075_016.686 / 2 ** z / EXTENT) * Math.cos((lonLat[1] * Math.PI) / 180);
  const nearest = (parts: readonly (readonly number[])[], closed: boolean): number => {
    let best = Infinity;
    for (const part of parts) {
      const n = part.length;
      for (let i = closed ? 0 : 2; i < n; i += 2) {
        const j = i === 0 ? n - 2 : i - 2;
        const ax = part[j] ?? 0;
        const ay = part[j + 1] ?? 0;
        const dx = (part[i] ?? 0) - ax;
        const dy = (part[i + 1] ?? 0) - ay;
        const length = dx * dx + dy * dy;
        let t = length === 0 ? 0 : ((px - ax) * dx + (py - ay) * dy) / length;
        t = Math.max(0, Math.min(1, t));
        best = Math.min(best, Math.hypot(ax + t * dx - px, ay + t * dy - py));
      }
    }
    return best * metersPerUnit;
  };
  return { edge: nearest(mask.rings, true), line: nearest(mask.border, false) };
}

/**
 * [place, a point on the official boundary, 25 m into the US, 25 m out of it].
 * Canada: IBC boundary v1.3 turning points and lines; Mexico: TIGER/Line 2025
 * international boundary (IBWC).
 */
const BORDER: readonly [string, LonLat, LonLat, LonLat][] = [
  // IBC: Lake Erie, Detroit and St. Clair Rivers.
  [
    'Detroit River at Hart Plaza',
    [-83.0448359, 42.3226561],
    [-83.044937, 42.3228681],
    [-83.0447347, 42.3224441],
  ],
  [
    'Detroit River at the Ambassador Bridge',
    [-83.074534, 42.3115165],
    [-83.0747187, 42.3116951],
    [-83.0743493, 42.3113379],
  ],
  [
    'Lake Erie off Erie, Pennsylvania',
    [-80.0974153, 42.3908572],
    [-80.0973531, 42.3906371],
    [-80.0974775, 42.3910773],
  ],
  // IBC: Lake Huron, Saint Marys River and Lake Superior.
  [
    'St. Clair River at the Blue Water Bridge',
    [-82.4230411, 42.9992509],
    [-82.4233091, 42.9993611],
    [-82.4227732, 42.9991406],
  ],
  // IBC: Lake Ontario and Niagara River.
  [
    'Niagara River at the Rainbow Bridge',
    [-79.0679478, 43.0899645],
    [-79.0677225, 43.0898113],
    [-79.0681731, 43.0901177],
  ],
  // IBC: St. Lawrence River.
  [
    'St. Lawrence River at Ogdensburg',
    [-75.4956433, 44.710325],
    [-75.4954529, 44.7101454],
    [-75.4958336, 44.7105046],
  ],
  // IBC: 49th Parallel (Pacific to Columbia Valley).
  [
    '49th parallel at Blaine',
    [-122.7500001, 49.0020887],
    [-122.7499999, 49.0018638],
    [-122.7500003, 49.0023135],
  ],
  [
    '49th parallel at Point Roberts',
    [-123.0600001, 49.0020703],
    [-123.0599998, 49.0018455],
    [-123.0600003, 49.0022951],
  ],
  // IBC: Meridian and 49th Parallel (MB/MN).
  [
    'Northwest Angle meridian',
    [-95.1532959, 49.2],
    [-95.1529518, 49.2000001],
    [-95.1536399, 49.1999999],
  ],
  // TIGER/Line 2025 international boundary, US-Mexico section (IBWC).
  [
    'Rio Grande at El Paso',
    [-106.4698003, 31.754956],
    [-106.4700562, 31.7550124],
    [-106.4695443, 31.7548996],
  ],
  [
    'Land border at San Ysidro',
    [-117.0302859, 32.5423777],
    [-117.0303127, 32.5426014],
    [-117.030259, 32.542154],
  ],
  [
    'Rio Grande at Laredo',
    [-99.5098267, 27.4991776],
    [-99.5098733, 27.4993986],
    [-99.5097801, 27.4989566],
  ],
  [
    'Rio Grande at Brownsville',
    [-97.4880272, 25.8853592],
    [-97.4881165, 25.8855692],
    [-97.4879379, 25.8851492],
  ],
  [
    'Land border at Nogales',
    [-110.9400073, 31.3327507],
    [-110.9400094, 31.3329755],
    [-110.9400051, 31.3325259],
  ],
];

/** Places well away from the border, and whether each is in the US. */
const PLACES: readonly [string, boolean, LonLat][] = [
  ['Detroit', true, [-83.0458, 42.3314]],
  ['Windsor', false, [-83.0364, 42.3149]],
  ['Niagara Falls, New York', true, [-79.0377, 43.0962]],
  ['Niagara Falls, Ontario', false, [-79.0849, 43.0896]],
  ['San Ysidro', true, [-117.04, 32.555]],
  ['Tijuana', false, [-117.03, 32.525]],
  ['El Paso', true, [-106.485, 31.76]],
  ['Ciudad Juarez', false, [-106.46, 31.72]],
  ['Key West', true, [-81.78, 24.555]],
  ['Bimini', false, [-79.28, 25.73]],
  ['Havana', false, [-82.37, 23.13]],
  ['Nassau', false, [-77.34, 25.06]],
  ['Toronto', false, [-79.38, 43.65]],
  ['Vancouver', false, [-123.12, 49.28]],
  ['Monterrey', false, [-100.31, 25.67]],
  ['Kansas City', true, [-94.593, 39.036]],
];

describe('the US mask archive', () => {
  it('is small, and holds tiles from zoom 7 to the zoom the border needs', () => {
    expect(bytes.length).toBeLessThanOrEqual(2 * 1024 * 1024);
    const header = decodeHeader(bytes);
    expect(header.minZoom).toBe(US_MASK_MIN_ZOOM);
    expect(header.maxZoom).toBe(US_MASK_MAX_ZOOM);
    expect(US_MASK_MIN_ZOOM).toBe(7);
  });

  describe.each(BORDER)('%s', (_name, border, inside, outside) => {
    it.each([15, 14, 12])(
      'leaves 25 m inside uncovered and covers 25 m outside at zoom %i',
      async (z) => {
        // Street tiles stop at zoom 14; deeper zooms draw zoom 14's.
        const zoom = Math.min(z, 14);
        expect(await covered(inside, zoom)).toBe(false);
        expect(await covered(outside, zoom)).toBe(true);
      },
    );

    it('runs its edge and its border line within 3 m of the official boundary', async () => {
      const { edge, line } = await distances(border, 14);
      expect(edge).toBeLessThan(3);
      expect(line).toBeLessThan(3);
    });
  });

  it.each(PLACES)('counts %s as inside the US: %s', async (_name, inUs, lonLat) => {
    for (const z of [7, 10, 14]) expect(await covered(lonLat, z), `zoom ${String(z)}`).toBe(!inUs);
  });
});
