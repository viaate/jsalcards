/**
 * SYNTHETIC benchmark points for the glow renderer.
 *
 * Nothing here is a real school, closing or place. Points are drawn from a
 * seeded PRNG: synthetic "towns" are dropped at a random spot inside a
 * randomly chosen county (from the bundled us-atlas boundaries, so towns
 * bunch up where counties are small and thin out where they are large), sized
 * by a Zipf law so a few are dense metros and most are small. Synthetic
 * "storms" then hand out statuses so neighbours tend to agree and storm edges
 * mix. The same seed always gives the same points.
 *
 * This module lives in web/bench/ and must never be imported by app code.
 */
import type { MultiPolygon, Polygon, Position } from 'geojson';

export const SYNTHETIC_SEED = 0x5eed_2026;

/** Mulberry32: a tiny, fast, well-mixed 32-bit PRNG. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Standard normal sample by Box-Muller. */
function gaussian(random: () => number): number {
  const u = Math.max(random(), 1e-12);
  const v = random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/**
 * Point-in-land test by scanline: for each thin latitude band, the sorted
 * longitudes where the band's center line crosses a polygon edge. A point is
 * on land when an odd number of crossings lie west of it.
 */
export class LandMask {
  readonly west: number;
  readonly east: number;
  readonly south: number;
  readonly north: number;
  private readonly rowHeight: number;
  private readonly rows: Float64Array[];

  constructor(land: MultiPolygon, rowHeight = 0.02) {
    let west = Infinity;
    let east = -Infinity;
    let south = Infinity;
    let north = -Infinity;
    const edges: [Position, Position][] = [];
    for (const polygon of land.coordinates) {
      for (const ring of polygon) {
        for (let i = 0; i < ring.length - 1; i++) {
          const a = ring[i];
          const b = ring[i + 1];
          if (a === undefined || b === undefined) continue;
          edges.push([a, b]);
          const [x, y] = a as [number, number];
          west = Math.min(west, x);
          east = Math.max(east, x);
          south = Math.min(south, y);
          north = Math.max(north, y);
        }
      }
    }
    this.west = west;
    this.east = east;
    this.south = south;
    this.north = north;
    this.rowHeight = rowHeight;
    const count = Math.ceil((north - south) / rowHeight);
    const buckets: number[][] = Array.from({ length: count }, () => []);
    for (const [a, b] of edges) {
      const [ax, ay] = a as [number, number];
      const [bx, by] = b as [number, number];
      const lo = Math.max(0, Math.floor((Math.min(ay, by) - south) / rowHeight - 0.5));
      const hi = Math.min(count - 1, Math.ceil((Math.max(ay, by) - south) / rowHeight - 0.5));
      for (let r = lo; r <= hi; r++) {
        const y = south + (r + 0.5) * rowHeight;
        if (ay <= y !== by <= y) buckets[r]?.push(ax + ((y - ay) * (bx - ax)) / (by - ay));
      }
    }
    this.rows = buckets.map((xs) => Float64Array.from(xs).sort());
  }

  contains(lng: number, lat: number): boolean {
    const row = this.rows[Math.floor((lat - this.south) / this.rowHeight)];
    if (row === undefined) return false;
    let lo = 0;
    let hi = row.length;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if ((row[mid] ?? Infinity) < lng) lo = mid + 1;
      else hi = mid;
    }
    return lo % 2 === 1;
  }
}

export interface SyntheticPoints {
  /** Interleaved lng, lat. */
  readonly lngLat: Float32Array;
  readonly status: Uint8Array;
  /** Center of the densest synthetic town, for the metro screenshot. */
  readonly densest: readonly [lng: number, lat: number];
}

interface Town {
  lng: number;
  lat: number;
  sigma: number;
  weight: number;
}

interface Storm {
  lng: number;
  lat: number;
  radius: number;
  /** Cumulative weights for closed, delayed, remote, early dismissal. */
  mix: readonly [number, number, number, number];
}

const TOWN_COUNT = 3000;
/** Town sizes follow rank^-ZIPF_EXPONENT. */
const ZIPF_EXPONENT = 0.85;
const STORM_COUNT = 9;
/** Share of points reported open; they never glow and show as gray dots up close. */
const OPEN_SHARE = 0.07;
/** Share of points scattered outside any town. */
const RURAL_SHARE = 0.12;

/** A random spot in a random county, on land. */
function sampleCounty(
  mask: LandMask,
  counties: readonly Polygon[],
  random: () => number,
): [number, number] {
  for (;;) {
    const county = counties[Math.floor(random() * counties.length)];
    const spot = county === undefined ? null : sampleInPolygon(county, random);
    if (spot !== null && mask.contains(spot[0], spot[1])) return spot;
  }
}

/** Even-odd point-in-polygon test over every ring. */
function inPolygon(polygon: Polygon, lng: number, lat: number): boolean {
  let inside = false;
  for (const ring of polygon.coordinates) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i] as [number, number];
      const [xj, yj] = ring[j] as [number, number];
      if (yi > lat !== yj > lat && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi)
        inside = !inside;
    }
  }
  return inside;
}

/** A uniformly random spot inside `polygon`, by rejection from its bounding box. */
function sampleInPolygon(polygon: Polygon, random: () => number): [number, number] | null {
  let west = Infinity;
  let east = -Infinity;
  let south = Infinity;
  let north = -Infinity;
  for (const [x, y] of (polygon.coordinates[0] ?? []) as [number, number][]) {
    west = Math.min(west, x);
    east = Math.max(east, x);
    south = Math.min(south, y);
    north = Math.max(north, y);
  }
  for (let tries = 0; tries < 64; tries++) {
    const lng = west + random() * (east - west);
    const lat = south + random() * (north - south);
    if (inPolygon(polygon, lng, lat)) return [lng, lat];
  }
  return null;
}

/**
 * Generates `count` SYNTHETIC points on the continental US land mask. Pure
 * function of (`mask`, `count`, `seed`).
 */
export function generateSyntheticPoints(
  mask: LandMask,
  counties: readonly Polygon[],
  count: number,
  seed = SYNTHETIC_SEED,
): SyntheticPoints {
  const random = mulberry32(seed);

  // Towns: a random spot in a random county.
  const towns: Town[] = [];
  while (towns.length < TOWN_COUNT) {
    const spot = sampleCounty(mask, counties, random);
    const rank = towns.length + 1;
    towns.push({ lng: spot[0], lat: spot[1], sigma: 0, weight: 1 / rank ** ZIPF_EXPONENT });
  }
  // Shuffle so rank (and so size) is independent of the acceptance order.
  for (let i = towns.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    const a = towns[i];
    const b = towns[j];
    if (a === undefined || b === undefined) continue;
    const { weight } = a;
    a.weight = b.weight;
    b.weight = weight;
  }
  const maxWeight = Math.max(...towns.map((town) => town.weight));
  let totalWeight = 0;
  for (const town of towns) {
    // Degrees; a dense metro spreads about half a degree, a hamlet a few hundredths.
    town.sigma = 0.02 + 0.22 * Math.sqrt(town.weight / maxWeight);
    totalWeight += town.weight;
  }
  const cumulative = new Float64Array(towns.length);
  let running = 0;
  towns.forEach((town, i) => {
    running += town.weight / totalWeight;
    cumulative[i] = running;
  });
  const densest = towns.reduce((best, town) => (town.weight > best.weight ? town : best));

  const storms: Storm[] = Array.from({ length: STORM_COUNT }, () => {
    const raw = [random() * 3 + 0.5, random() * 2, random() * 1.2, random() * 0.8];
    const sum = raw.reduce((a, b) => a + b, 0);
    let acc = 0;
    const mix = raw.map((w) => (acc += w / sum)) as [number, number, number, number];
    return {
      lng: -122 + random() * 54,
      lat: 27 + random() * 20,
      radius: 3 + random() * 6,
      mix,
    };
  });

  const lngLat = new Float32Array(count * 2);
  const status = new Uint8Array(count);
  for (let i = 0; i < count; i++) {
    let lng: number;
    let lat: number;
    if (random() < RURAL_SHARE) {
      [lng, lat] = sampleCounty(mask, counties, random);
    } else {
      const pick = random();
      let lo = 0;
      let hi = cumulative.length - 1;
      while (lo < hi) {
        const mid = (lo + hi) >>> 1;
        if ((cumulative[mid] ?? 1) < pick) lo = mid + 1;
        else hi = mid;
      }
      const town = towns[lo] ?? densest;
      let tries = 0;
      do {
        lng = town.lng + gaussian(random) * town.sigma * 1.25;
        lat = town.lat + gaussian(random) * town.sigma;
        tries++;
      } while (!mask.contains(lng, lat) && tries < 8);
      if (!mask.contains(lng, lat)) [lng, lat] = [town.lng, town.lat];
    }
    lngLat[i * 2] = lng;
    lngLat[i * 2 + 1] = lat;

    if (random() < OPEN_SHARE) {
      status[i] = 4;
      continue;
    }
    // The storm with the strongest pull sets the status mix, with a little
    // noise so storm edges blend.
    let best: Storm | undefined;
    let bestPull = -Infinity;
    for (const storm of storms) {
      const d2 = ((lng - storm.lng) ** 2 + (lat - storm.lat) ** 2) / (storm.radius * storm.radius);
      const pull = -d2 + gaussian(random) * 0.35;
      if (pull > bestPull) {
        bestPull = pull;
        best = storm;
      }
    }
    const roll = random();
    const mix = best?.mix ?? [1, 1, 1, 1];
    status[i] = roll < mix[0] ? 0 : roll < mix[1] ? 1 : roll < mix[2] ? 2 : 3;
  }

  return { lngLat, status, densest: [densest.lng, densest.lat] };
}
