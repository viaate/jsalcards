/**
 * SYNTHETIC search records for benchmarking the search engine.
 *
 * Nothing here is a real school, district, city or ZIP code. Every name is a
 * pseudo-word built from syllables by a seeded PRNG ("Branmoor", "Tessaly
 * Elementary School"), combined with generic English words and the naming
 * patterns US schools use, so the vocabulary, abbreviations, accents and
 * weight skew look like the real directory to the engine while no record can
 * be mistaken for a real one. Only the state codes are real, and each state's
 * records are scattered inside its bounding box from the bundled us-atlas
 * boundaries so neighbouring records sit near each other, as real ones do.
 *
 * The same seed always gives the same records. This module lives in
 * web/bench/ and must never be imported by app code.
 */
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

import { STATES } from '../../src/search/states';
import type { SearchRecord } from '../../src/search/types';

export const SYNTHETIC_SEARCH_SEED = 0x5ea2_c417;

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

type Random = () => number;

function gaussian(random: Random): number {
  const u = Math.max(random(), 1e-12);
  const v = random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function pick<T>(random: Random, list: readonly T[]): T {
  const item = list[Math.floor(random() * list.length)];
  if (item === undefined) throw new Error('pick from an empty list');
  return item;
}

/** Picks an index with probability proportional to cumulative weights. */
function pickWeighted(random: Random, cumulative: Float64Array): number {
  const total = cumulative[cumulative.length - 1] ?? 0;
  const x = random() * total;
  let lo = 0;
  let hi = cumulative.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((cumulative[mid] ?? 0) > x) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}

function cumulate(weights: readonly number[]): Float64Array {
  const out = new Float64Array(weights.length);
  let sum = 0;
  weights.forEach((w, i) => {
    sum += w;
    out[i] = sum;
  });
  return out;
}

// prettier-ignore
const ONSETS = [
  'b', 'br', 'bl', 'c', 'ch', 'cl', 'cr', 'd', 'dr', 'f', 'fl', 'fr', 'g', 'gl', 'gr', 'h', 'j',
  'k', 'l', 'm', 'n', 'p', 'pl', 'pr', 'qu', 'r', 's', 'sc', 'sh', 'sl', 'sp', 'st', 't', 'th',
  'tr', 'v', 'w', 'wh', 'y', 'z', '', '',
];
// prettier-ignore
const VOWELS = ['a', 'e', 'i', 'o', 'u', 'a', 'e', 'o', 'ai', 'ea', 'ee', 'oa', 'ou', 'ie', 'y'];
// prettier-ignore
const CODAS = [
  '', '', '', 'n', 'r', 'l', 's', 't', 'm', 'nd', 'rt', 'ck', 'ng', 'x', 'll', 'ss', 'th', 'rn',
  'ld', 'nt', 'st', 'sk',
];
// prettier-ignore
const PLACE_ENDINGS = [
  '', '', '', 'ville', 'ton', 'burg', 'field', 'wood', 'dale', 'ford', 'port', 'view', 'land',
  'mont', 'haven', 'brook', 'ridge', 'wick', 'ley', 'by', 'stead', 'boro', 'ham', 'well', 'worth',
];
// prettier-ignore
const PLACE_PREFIXES = [
  'North', 'South', 'East', 'West', 'New', 'Fort', 'Mount', 'Saint', 'Lake', 'Port', 'Glen',
  'Cedar', 'Pine', 'Oak', 'Red', 'Green', 'Little', 'Upper', 'Lower', 'Old',
];
// prettier-ignore
const PLACE_SUFFIX_WORDS = [
  'Springs', 'Falls', 'City', 'Heights', 'Hills', 'Park', 'Creek', 'Valley', 'Beach', 'Junction',
  'Center', 'Grove', 'Village', 'Harbor', 'Point', 'Crossing', 'Station', 'Mills', 'Bluff', 'Township',
];
// prettier-ignore
const NATURE = [
  'Oak', 'Pine', 'Maple', 'Cedar', 'Willow', 'Birch', 'Elm', 'Aspen', 'Ridge', 'Hill', 'Valley',
  'Creek', 'River', 'Lake', 'Meadow', 'Park', 'Grove', 'Spring', 'Brook', 'Forest', 'Prairie',
  'Summit', 'Harbor', 'Bay', 'Sunset', 'Sunrise', 'Eagle', 'Hawk', 'Fox', 'Deer', 'Bear',
  'Liberty', 'Freedom', 'Heritage', 'Pioneer', 'Frontier', 'Discovery', 'Horizon', 'Vista',
  'Legacy', 'Unity', 'Harmony', 'Hope', 'Faith', 'Grace', 'Trinity', 'Cornerstone', 'Gateway',
  'Central', 'Lakeview', 'Hillcrest', 'Fairview', 'Riverside', 'Parkview', 'Highland', 'Woodland',
  'Greenfield', 'Clearview', 'Sunnyside', 'Brookside', 'Oakwood', 'Pinecrest', 'Silver', 'Golden',
  'Crystal', 'Stone', 'Mill', 'Orchard', 'Garden', 'Hollow', 'Canyon', 'Mesa', 'Desert',
  'Mountain', 'Bayside', 'Prospect', 'Independence', 'Victory', 'Monarch', 'Compass', 'Beacon',
];
// prettier-ignore
const NATURE_SECOND = [
  'Hill', 'Ridge', 'Grove', 'Park', 'View', 'Creek', 'Valley', 'Crest', 'Wood', 'Meadow',
  'Point', 'Trail', 'Glen', 'Hollow', 'Springs', 'Lake', 'Heights', 'Forest', 'Field', 'Run',
];
const ACCENTS: readonly (readonly [string, string])[] = [
  ['n', 'ñ'],
  ['e', 'é'],
  ['u', 'ü'],
  ['a', 'á'],
  ['o', 'ó'],
  ['i', 'í'],
];

function capitalize(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

/** A pronounceable pseudo-word of 2 or 3 syllables. */
function pseudoWord(random: Random): string {
  const syllables = random() < 0.7 ? 2 : 3;
  let w = '';
  for (let i = 0; i < syllables; i++) {
    w += pick(random, ONSETS) + pick(random, VOWELS);
    if (i === syllables - 1 || random() < 0.35) w += pick(random, CODAS);
  }
  return w.length < 3 ? w + pick(random, ['ton', 'ley', 'ard']) : w;
}

/** `count` distinct capitalized pseudo-words, some with an accented letter. */
function lexicon(random: Random, count: number, ending = false, accentRate = 0.004): string[] {
  const out = new Set<string>();
  while (out.size < count) {
    let w = pseudoWord(random);
    if (ending) w += pick(random, PLACE_ENDINGS);
    if (random() < accentRate) {
      const [plain, accented] = pick(random, ACCENTS);
      const at = w.indexOf(plain, 1);
      if (at > 0) w = w.slice(0, at) + accented + w.slice(at + 1);
    }
    out.add(capitalize(w));
  }
  return [...out];
}

interface Box {
  readonly west: number;
  readonly south: number;
  readonly east: number;
  readonly north: number;
}

interface TopoJson {
  readonly transform: { readonly scale: [number, number]; readonly translate: [number, number] };
  readonly arcs: readonly (readonly [number, number][])[];
  readonly objects: {
    readonly states: {
      readonly geometries: readonly {
        readonly properties: { readonly name: string };
        readonly arcs: unknown;
      }[];
    };
  };
}

/** Bounding boxes of the 48 contiguous states and DC, from us-atlas. */
function stateBoxes(): Map<string, Box> {
  const require = createRequire(import.meta.url);
  const path = require.resolve('us-atlas/states-10m.json');
  const topo = JSON.parse(readFileSync(path, 'utf8')) as TopoJson;
  const [sx, sy] = topo.transform.scale;
  const [tx, ty] = topo.transform.translate;
  const arcBoxes = topo.arcs.map((arc) => {
    let x = 0;
    let y = 0;
    const box = { west: 180, south: 90, east: -180, north: -90 };
    for (const [dx, dy] of arc) {
      x += dx;
      y += dy;
      const lon = x * sx + tx;
      const lat = y * sy + ty;
      box.west = Math.min(box.west, lon);
      box.east = Math.max(box.east, lon);
      box.south = Math.min(box.south, lat);
      box.north = Math.max(box.north, lat);
    }
    return box;
  });
  const byName = new Map(STATES.map(([code, name]) => [name, code]));
  const boxes = new Map<string, Box>();
  for (const geometry of topo.objects.states.geometries) {
    const code = byName.get(geometry.properties.name);
    if (!code || ['AK', 'HI', 'PR', 'GU', 'VI', 'AS', 'MP'].includes(code)) continue;
    const box = { west: 180, south: 90, east: -180, north: -90 };
    const visit = (node: unknown): void => {
      if (typeof node === 'number') {
        const a = arcBoxes[node < 0 ? ~node : node];
        if (!a) return;
        box.west = Math.min(box.west, a.west);
        box.east = Math.max(box.east, a.east);
        box.south = Math.min(box.south, a.south);
        box.north = Math.max(box.north, a.north);
      } else if (Array.isArray(node)) {
        for (const child of node as unknown[]) visit(child);
      }
    };
    visit(geometry.arcs);
    boxes.set(code, box);
  }
  return boxes;
}

export interface SyntheticCounts {
  readonly schools: number;
  readonly districts: number;
  readonly cities: number;
  readonly zips: number;
}

/** Roughly the real directory's mix, 200,000 records in all. */
export const DEFAULT_SYNTHETIC_COUNTS: SyntheticCounts = {
  schools: 118_000,
  districts: 18_000,
  cities: 31_000,
  zips: 33_000,
};

interface City {
  readonly name: string;
  readonly state: string;
  readonly lat: number;
  readonly lon: number;
  readonly population: number | null;
  district: number;
}

function schoolName(random: Random, pools: NamePools, city: City): string {
  const surname = (): string => pick(random, pools.surnames);
  const place = (): string => (random() < 0.7 ? city.name : pick(random, pools.places));
  const nature = (): string =>
    random() < 0.5
      ? pick(random, NATURE)
      : `${pick(random, NATURE)} ${pick(random, NATURE_SECOND)}`;
  const x = random() * 100;
  if (x < 20) return `${surname()} Elementary School`;
  if (x < 25) return `${pick(random, pools.firstNames)} ${surname()} Elementary School`;
  if (x < 35) return `${place()} Elementary School`;
  if (x < 44) return `${nature()} Elementary School`;
  if (x < 51) return `${place()} High School`;
  if (x < 54) return `${surname()} High School`;
  if (x < 55) return `${place()} Senior High School`;
  if (x < 60) return `${place()} Middle School`;
  if (x < 64) return `${surname()} Middle School`;
  if (x < 65) return `${place()} Junior High School`;
  if (x < 67) return `${place()} Intermediate School`;
  if (x < 68) return `${nature()} Primary School`;
  if (x < 70) return `${place()} Academy`;
  if (x < 72) return `${nature()} Academy`;
  if (x < 73.5) return `${place()} Charter School`;
  if (x < 74.5) return `${nature()} Charter Academy`;
  if (x < 77.5) return `St. ${pick(random, pools.firstNames)} School`;
  if (x < 79.5) return `St. ${pick(random, pools.firstNames)} Catholic School`;
  if (x < 81.5) return `${nature()} Christian School`;
  if (x < 83) return `${place()} Christian Academy`;
  if (x < 84) return `${place()} Montessori School`;
  if (x < 84.5) return `${place()} Early College High School`;
  if (x < 85.5) return `${place()} Alternative School`;
  if (x < 86.5) return `${place()} Learning Center`;
  if (x < 87) return `${place()} Virtual Academy`;
  if (x < 88) return `P.S. ${String(1 + Math.floor(random() * 400))} ${surname()}`;
  if (x < 88.4) return `I.S. ${String(1 + Math.floor(random() * 400))}`;
  if (x < 88.8) return `M.S. ${String(1 + Math.floor(random() * 400))}`;
  if (x < 89.3) return `${place()} Jr./Sr. High School`;
  if (x < 90.3) return `${place()} K-8 School`;
  if (x < 91.3) return `${place()} Elem`;
  if (x < 92.8) return `${surname()} El Sch`;
  if (x < 93.3) return `${surname()} MS`;
  if (x < 93.8) return `${place()} HS`;
  if (x < 95) return `${place()} ${pick(random, NATURE)} School`;
  if (x < 96) return `${surname()}-${surname()} Elementary School`;
  if (x < 97) return `${pick(random, pools.firstNames)} O'${surname()} School`;
  if (x < 98) return `${place()} School of the Arts`;
  if (x < 99) return `${place()} Technical & Career Center`;
  return `${place()} Preparatory Academy`;
}

function districtName(random: Random, pools: NamePools, city: City): string {
  const x = random() * 100;
  if (x < 35) return `${city.name} School District`;
  if (x < 43) return `${city.name} Unified School District`;
  if (x < 51) return `${city.name} ISD`;
  if (x < 61) return `${pick(random, pools.counties)} County Schools`;
  if (x < 69) return `${pick(random, pools.counties)} County School District`;
  if (x < 72) return `School District of ${city.name}`;
  if (x < 84) return `${city.name} Public Schools`;
  if (x < 89) return `${city.name} City Schools`;
  if (x < 94) return `${city.name} Community School District`;
  if (x < 97) return `${city.name} Area School District`;
  return `${city.name} Consolidated School District ${String(1 + Math.floor(random() * 90))}`;
}

interface NamePools {
  readonly places: readonly string[];
  readonly surnames: readonly string[];
  readonly firstNames: readonly string[];
  readonly counties: readonly string[];
}

/**
 * Generates SYNTHETIC records: schools, districts, cities and ZIP codes with
 * pseudo-word names. Deterministic for a given seed and counts.
 */
export function syntheticSearchRecords(
  counts: SyntheticCounts = DEFAULT_SYNTHETIC_COUNTS,
  seed = SYNTHETIC_SEARCH_SEED,
): SearchRecord[] {
  const random = mulberry32(seed);
  const boxes = stateBoxes();
  const states = [...boxes.keys()].sort();
  // A skewed, seeded share of places per state.
  const stateWeights = states.map(() => Math.exp(gaussian(random) * 0.8));
  const stateCumulative = cumulate(stateWeights);

  const cityRoots = lexicon(random, Math.round(counts.cities * 0.9), true);
  const pools: NamePools = {
    places: lexicon(random, 6000, true),
    surnames: lexicon(random, 14_000),
    firstNames: lexicon(random, 1500),
    counties: lexicon(random, 2500),
  };

  const cities: City[] = [];
  const cityKeys = new Set<string>();
  for (let i = 0; cities.length < counts.cities; i++) {
    const state = states[pickWeighted(random, stateCumulative)] ?? 'PA';
    const root = cityRoots[i % cityRoots.length] ?? 'Brenton';
    const x = random();
    let name = root;
    if (x < 0.12) name = `${pick(random, PLACE_PREFIXES)} ${root}`;
    else if (x < 0.22) name = `${root} ${pick(random, PLACE_SUFFIX_WORDS)}`;
    const key = `${name}|${state}`;
    if (cityKeys.has(key)) continue;
    cityKeys.add(key);
    const box = boxes.get(state);
    if (!box) continue;
    const incorporated = random() < 0.6;
    const population = incorporated
      ? Math.max(50, Math.round(Math.exp(7 + gaussian(random) * 1.6)))
      : null;
    cities.push({
      name,
      state,
      lat: box.south + random() * (box.north - box.south),
      lon: box.west + random() * (box.east - box.west),
      population,
      district: -1,
    });
  }

  const byState = new Map<string, number[]>();
  cities.forEach((c, i) => {
    const list = byState.get(c.state);
    if (list) list.push(i);
    else byState.set(c.state, [i]);
  });

  // Districts: each takes a home city; the remaining cities join a district in their state.
  const records: SearchRecord[] = [];
  interface District {
    readonly id: string;
    readonly city: City;
    enrollment: number;
    schools: number;
    readonly name: string;
  }
  const districts: District[] = [];
  const cityCumulative = cumulate(cities.map((c) => Math.pow(c.population ?? 300, 0.6)));
  const stateSeq = new Map<string, number>();
  while (districts.length < counts.districts) {
    const ci = pickWeighted(random, cityCumulative);
    const city = cities[ci];
    if (!city) continue;
    // A city hosts one district, and now and then a second.
    if (city.district >= 0 && random() >= 0.02) continue;
    const seq = (stateSeq.get(city.state) ?? 0) + 1;
    stateSeq.set(city.state, seq);
    const stateNo = String(states.indexOf(city.state) + 1).padStart(2, '0');
    const id = `${stateNo}${String(seq * 7 + 100).padStart(5, '0')}`;
    if (city.district < 0) city.district = districts.length;
    districts.push({
      id,
      city,
      enrollment: 0,
      schools: 0,
      name: districtName(random, pools, city),
    });
  }
  for (const [, list] of byState) {
    const own = list.filter((ci) => (cities[ci]?.district ?? -1) >= 0);
    for (const ci of list) {
      const city = cities[ci];
      if (!city || city.district >= 0) continue;
      const host = own.length > 0 ? cities[pick(random, own)] : undefined;
      city.district = host ? host.district : Math.floor(random() * districts.length);
    }
  }

  // Schools.
  const schoolCityCumulative = cumulate(cities.map((c) => 1 + Math.pow(c.population ?? 400, 0.75)));
  const perDistrictSeq = new Map<number, number>();
  let privateSeq = 0;
  const schoolKeys = new Set<string>();
  while (records.length < counts.schools) {
    const ci = pickWeighted(random, schoolCityCumulative);
    const city = cities[ci];
    if (!city) continue;
    const spread = 0.01 + 0.06 * Math.min(1, (city.population ?? 500) / 200_000);
    const enrollment = random() < 0.05 ? 0 : Math.round(Math.exp(6.1 + gaussian(random) * 0.7));
    let id: string;
    if (random() < 0.82) {
      const d = districts[city.district];
      if (!d) continue;
      const seq = (perDistrictSeq.get(city.district) ?? 0) + 1;
      perDistrictSeq.set(city.district, seq);
      id = `${d.id}${String(seq * 3 + 10).padStart(5, '0')}`;
      d.enrollment += enrollment;
      d.schools++;
    } else {
      privateSeq++;
      id = `S${String(privateSeq * 13 + 1000).padStart(7, '0')}`;
    }
    const name = schoolName(random, pools, city);
    const key = `${name}|${city.name}|${city.state}`;
    if (schoolKeys.has(key) && random() < 0.7) continue;
    schoolKeys.add(key);
    records.push({
      kind: 'school',
      id,
      name,
      sub: `${city.name}, ${city.state}`,
      state: city.state,
      lat: round6(city.lat + gaussian(random) * spread),
      lon: round6(city.lon + gaussian(random) * spread * 1.3),
      weight: enrollment,
    });
  }

  for (const d of districts) {
    records.push({
      kind: 'district',
      id: d.id,
      name: d.name,
      sub: `${d.city.name}, ${d.city.state}`,
      state: d.city.state,
      lat: round6(d.city.lat),
      lon: round6(d.city.lon),
      weight: d.enrollment,
    });
  }

  const stateName = new Map(STATES.map(([code, name]) => [code, name]));
  cities.forEach((c, i) => {
    records.push({
      kind: 'city',
      id: `${String(states.indexOf(c.state) + 1).padStart(2, '0')}${String(i).padStart(5, '0')}`,
      name: c.name,
      sub: stateName.get(c.state) ?? c.state,
      state: c.state,
      lat: round6(c.lat),
      lon: round6(c.lon),
      weight: c.population ?? 0,
    });
  });

  // ZIP codes: numbered in runs per state, each run near one city, so
  // neighbouring codes sit near each other.
  const zipCityCumulative = cumulate(cities.map((c) => 1 + Math.pow(c.population ?? 200, 0.5)));
  const zipPlaces: { city: City; lat: number; lon: number }[] = [];
  for (let i = 0; i < counts.zips; i++) {
    const city = cities[pickWeighted(random, zipCityCumulative)];
    if (!city) continue;
    zipPlaces.push({
      city,
      lat: round6(city.lat + gaussian(random) * 0.05),
      lon: round6(city.lon + gaussian(random) * 0.07),
    });
  }
  zipPlaces.sort(
    (a, b) =>
      states.indexOf(a.city.state) - states.indexOf(b.city.state) ||
      a.city.lat - b.city.lat ||
      a.lon - b.lon,
  );
  const zipStep = 99_000 / Math.max(1, zipPlaces.length);
  zipPlaces.forEach((z, i) => {
    const code = String(1000 + Math.floor(i * zipStep)).padStart(5, '0');
    records.push({
      kind: 'zip',
      id: code,
      name: code,
      sub: stateName.get(z.city.state) ?? z.city.state,
      state: z.city.state,
      lat: z.lat,
      lon: z.lon,
      weight: 0,
    });
  });
  return records;
}

function round6(x: number): number {
  return Math.round(x * 1e6) / 1e6;
}
