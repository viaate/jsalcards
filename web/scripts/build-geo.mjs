#!/usr/bin/env node
/**
 * Builds the bundled continental US geometry that Snowlight draws below zoom 7.
 *
 * Input: us-atlas states-10m.json (Census Bureau cartographic state boundaries,
 * 2017 edition, as TopoJSON), simplified to a tolerance finer than a pixel at
 * every zoom the lines are drawn at, and the Census places the pipeline writes
 * for search (site-data/search/cities.jsonl). Output, all deterministic:
 *
 *   public/geo/us-lines.<hash>.json   GeoJSON for MapLibre: the land (its rings
 *                                      are the outline: coasts, lake shores,
 *                                      borders), the state lines and the city
 *                                      names of the national view.
 *   src/map/basemap/us-geo.ts          Bounds, file name and still-frame viewBox.
 *   src/map/basemap/us-reach.ts        Where the US has land in each band of
 *                                      latitude, which keeps the country on
 *                                      screen as the map pans, with every
 *                                      school in the directory inside it.
 *   index.html                         The inline SVG still between the
 *                                      geo:still markers, drawn in Web Mercator
 *                                      so it matches the WebGL map at the
 *                                      initial view.
 *
 * The reach also takes in every school in the school directory the pipeline
 * writes (site-data/schools/points.bin and meta.json), so the map can center
 * on each one at street zoom: the few the outline misses, such as Monhegan
 * School on its island off Maine, are kept in scripts/reach-schools.json.
 * When the directory is there, that file is rebuilt from it; without it (a
 * fresh checkout, CI), the file is read as committed.
 *
 * The city names come the same way: chosen from the pipeline's places when
 * they are there and kept in scripts/national-cities.json, read as committed
 * when they are not. They are the largest incorporated places, and the
 * largest of those far from any bigger one, so the plains and the mountains
 * have names too; MapLibre shows as many as fit, the largest first.
 *
 *   node scripts/build-geo.mjs                     write the files
 *   node scripts/build-geo.mjs --check             exit 1 if any file is stale
 *   node scripts/build-geo.mjs --site-data <dir>   read the directory and places from <dir>
 *                                                  (default ../pipeline/out/site-data)
 */
import { createHash } from 'node:crypto';
import { readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join, relative, resolve } from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { TextDecoder } from 'node:util';
import { gzipSync } from 'node:zlib';

import prettier from 'prettier';

/** @type {unknown} */
const loadedMapshaper = createRequire(import.meta.url)('mapshaper');
/**
 * mapshaper ships no type declarations; this is the one call used.
 * @typedef {{ applyCommands(commands: string, input: Record<string, string>): Promise<Record<string, string | Uint8Array>> }} Mapshaper
 */
const mapshaper = /** @type {Mapshaper} */ (loadedMapshaper);

/** @typedef {[number, number]} Point */
/** @typedef {Point[]} Line */
/** A polygon's rings, each closed: its last point is its first. @typedef {Line[]} Polygon */
/** The outline is every ring of the land, as lines. @typedef {{ land: Polygon[], outline: Line[], state: Line[] }} Kinds */
/** @typedef {[number, number, number, number]} Bounds */
/**
 * @typedef {object} LineFeature
 * @property {{ TYPE?: string }} properties
 * @property {{ type: 'LineString', coordinates: number[][] } | { type: 'MultiLineString', coordinates: number[][][] }} geometry
 */

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE = join(WEB, 'node_modules/us-atlas/states-10m.json');
const GEO_DIR = join(WEB, 'public/geo');
const META_FILE = join(WEB, 'src/map/basemap/us-geo.ts');
const REACH_FILE = join(WEB, 'src/map/basemap/us-reach.ts');
const REACH_SCHOOLS_FILE = join(WEB, 'scripts/reach-schools.json');
const CITIES_FILE = join(WEB, 'scripts/national-cities.json');
const INDEX_HTML = join(WEB, 'index.html');
/** Where the pipeline writes the site's data, schools/ among it. */
const DEFAULT_SITE_DATA = join(WEB, '../pipeline/out/site-data');

/** Alaska, Hawaii and the territories: outside the continental view. */
const EXCLUDED_FIPS = ['02', '15', '60', '66', '69', '72', '78'];
/** DC (11) is folded into Maryland (24) so it does not draw as a speck of lines. */
const DC_FIPS = '11';
const MD_FIPS = '24';

/** Degrees. 0.001 is about 0.1 px at zoom 6, finer than the source's own quantization. */
const PRECISION = 0.001;
/**
 * Douglas-Peucker tolerance, in meters on the ground. The bundled lines are
 * drawn at full strength up to zoom 7 and fade out by 7.5. At zoom 7 a pixel
 * spans 611.5 m x cos(latitude) (512 px tiles), 401 m at the 49th parallel,
 * the smallest in the lower 48; 200 m keeps every line within half a pixel of
 * the source there and within a twentieth of a pixel at the initial view. The
 * source is already generalized for 1:10,000,000, so this removes little.
 * Shared borders are one arc in the topology, so neighbouring states still meet.
 */
const SIMPLIFY_METERS = 200;
/** Still-frame grid: the bounds are 8000 units wide, so rounding moves a vertex at most 1/16000 of the width. */
const STILL_WIDTH = 8000;
/** Budget from the spec: the bundled GeoJSON stays at or under 60 KB gzipped. */
const MAX_GZIP_BYTES = 60 * 1024;
/** Height of a reach band, in degrees: about 11 km of latitude. */
const REACH_STEP = 0.1;
/** Lines of latitude sampled in each reach band. */
const REACH_SCANLINES = 4;
/** Water narrower than this many degrees of longitude counts as land in the reach (Lake Michigan is 1.9). */
const REACH_GAP = 2;
/** Places this near a city count toward its people (chooseCities). */
const CITY_AREA_KM = 40;
/** A city this far from any with more people ranks as if it had more (chooseCities)... */
const CITY_ISOLATION_KM = 200;
/** ...up to this many times its people. */
const CITY_ISOLATION_MAX = 3;
/** The cities with the most people named at the national view; MapLibre shows as many as fit. */
const CITY_TOP = 250;
/** A smaller place is one too when no bigger candidate is within this many kilometres of it. */
const CITY_REGION_KM = 250;
/** A ZIP code a city's school district serves at least this share of is the city's (districtCenter). */
const CITY_DISTRICT_SHARE = 0.5;
/** How far off the land a city's point can be for its name to go on the nearest shore (shoreNear)... */
const CITY_SHORE_KM = 8;
/** ...and how far inside that shore it then goes. */
const CITY_SHORE_INSET_KM = 2;
/** The capital's state: its one city ranks with the largest (chooseCities). */
const CAPITAL_STATE = 'DC';
/** No place smaller than this is named, however remote. */
const CITY_MIN_POPULATION = 20_000;
/** Census place kinds that are not a city, town or other incorporated place. */
const NOT_A_CITY = ['CDP'];
/** States outside the continental view. */
const EXCLUDED_STATES = ['AK', 'HI', 'PR'];

const STILL_START = '<!-- geo:still:start -->';
const STILL_END = '<!-- geo:still:end -->';

/** Web Mercator, in world units [0, 1], the same formulas MapLibre uses. */
/** @param {number} lng */
const mercatorX = (lng) => (180 + lng) / 360;
/** @param {number} lat */
const mercatorY = (lat) =>
  (180 - (180 / Math.PI) * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))) / 360;

/** @param {number} value */
const round = (value) => Math.round(value / PRECISION) * PRECISION;
/**
 * Fixed-precision number text with no trailing zeros and no negative zero.
 * @param {number} value
 * @param {number} [digits]
 */
const num = (value, digits = 3) => {
  const text = value.toFixed(digits).replace(/\.?0+$/, '');
  return text === '-0' ? '0' : text;
};

/**
 * A line's coordinates on the lines' grid, with repeated points dropped.
 * @param {number[][]} coordinates
 * @returns {Line}
 */
function gridLine(coordinates) {
  /** @type {Line} */
  const line = [];
  for (const [lng = NaN, lat = NaN] of coordinates) {
    /** @type {Point} */
    const point = [round(lng), round(lat)];
    const last = line.at(-1);
    if (last?.[0] !== point[0] || last[1] !== point[1]) line.push(point);
  }
  return line;
}

/** @param {string | Uint8Array | undefined} text */
function parseOutput(text) {
  if (text === undefined) throw new Error('build-geo: mapshaper wrote no output');
  /** @type {unknown} */
  const parsed = JSON.parse(typeof text === 'string' ? text : new TextDecoder().decode(text));
  return parsed;
}

/**
 * Runs mapshaper on the TopoJSON and returns the land's polygons and the
 * lines grouped by kind: the outline (every ring of the land) and the state
 * lines. The land is the states dissolved after simplifying, so its rings
 * are exactly the national outline and meet the state lines.
 * @returns {Promise<Kinds>}
 */
async function extractGeometry() {
  const topology = await readFile(SOURCE, 'utf8');
  const commands = [
    '-i states.json id-field=fips',
    '-target states',
    `-filter '!${JSON.stringify(EXCLUDED_FIPS)}.includes(fips)'`,
    `-each 'fips = fips === "${DC_FIPS}" ? "${MD_FIPS}" : fips'`,
    '-dissolve fips',
    `-simplify dp interval=${String(SIMPLIFY_METERS)}m keep-shapes`,
    // The whole country as one layer of polygons, from the simplified states.
    '-dissolve + name=land',
    // Polygon rings become lines; TYPE is "inner" for shared state borders ("outer" is the land's edge).
    '-lines target=states',
    '-o target=states,land format=geojson',
  ].join(' ');
  const output = await mapshaper.applyCommands(commands, { 'states.json': topology });
  const lines = /** @type {{ features: LineFeature[] }} */ (parseOutput(output['states.json']));
  const land = /** @type {{ geometries: { type: string, coordinates: number[][][][] }[] }} */ (
    parseOutput(output['land.json'])
  );

  /** @type {Kinds} */
  const kinds = { land: [], outline: [], state: [] };
  for (const feature of lines.features) {
    if (feature.properties.TYPE === 'outer') continue;
    const geometry = feature.geometry;
    const parts = geometry.type === 'LineString' ? [geometry.coordinates] : geometry.coordinates;
    for (const part of parts) {
      const line = gridLine(part);
      if (line.length >= 2) kinds.state.push(line);
    }
  }
  for (const geometry of land.geometries) {
    if (geometry.type !== 'MultiPolygon')
      throw new Error('build-geo: the land is not a MultiPolygon');
    for (const polygon of geometry.coordinates) {
      /** @type {Polygon} */
      const rings = [];
      for (const ring of polygon) {
        const line = gridLine(ring);
        // A closed ring needs three corners and its closing point.
        if (line.length >= 4) rings.push(line);
      }
      if (rings.length > 0) kinds.land.push(rings);
    }
  }
  // Stable order regardless of mapshaper's internal ordering.
  /** @param {Line} line */
  const key = (line) => {
    const [lng = NaN, lat = NaN] = line[0] ?? [];
    return `${num(lng)},${num(lat)},${String(line.length)}`;
  };
  kinds.state.sort((a, b) => key(a).localeCompare(key(b)));
  kinds.land.sort((a, b) => key(a[0] ?? []).localeCompare(key(b[0] ?? [])));
  kinds.outline = kinds.land.flat();
  return kinds;
}

/**
 * @param {Kinds} kinds
 * @returns {Bounds}
 */
function boundsOf(kinds) {
  let [west, south, east, north] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const lines of [kinds.outline, kinds.state]) {
    for (const line of lines) {
      for (const [lng, lat] of line) {
        west = Math.min(west, lng);
        south = Math.min(south, lat);
        east = Math.max(east, lng);
        north = Math.max(north, lat);
      }
    }
  }
  return [Number(num(west)), Number(num(south)), Number(num(east)), Number(num(north))];
}

/**
 * The land along one line of latitude, as sorted [west, east] intervals: the
 * outline's crossings of the line, paired up (even-odd), so lakes and bays
 * the outline goes around are gaps.
 * @param {Line[]} lines the outline: closed rings, cut into pieces
 * @param {number} lat never on the lines' 0.001 degree grid, so no vertex sits on it
 * @returns {[number, number][]}
 */
function landAlong(lines, lat) {
  /** @type {number[]} */
  const crossings = [];
  for (const line of lines) {
    for (let i = 1; i < line.length; i++) {
      const [lng0 = NaN, lat0 = NaN] = line[i - 1] ?? [];
      const [lng1 = NaN, lat1 = NaN] = line[i] ?? [];
      if (lat0 < lat === lat1 < lat) continue;
      crossings.push(lng0 + ((lat - lat0) / (lat1 - lat0)) * (lng1 - lng0));
    }
  }
  if (crossings.length % 2 !== 0) {
    throw new Error(`build-geo: the outline is not closed along latitude ${String(lat)}`);
  }
  crossings.sort((a, b) => a - b);
  /** @type {[number, number][]} */
  const land = [];
  for (let i = 0; i < crossings.length; i += 2) {
    land.push([crossings[i] ?? NaN, crossings[i + 1] ?? NaN]);
  }
  return land;
}

/** @typedef {[number, number, number, number]} Piece west, east, south, north, in degrees */
/** @typedef {{ start: number, runs: number[][] }} Reach */
/** @typedef {{ id: string, lon: number, lat: number }} School */

/**
 * The band of latitude `lat` falls in, of `count` bands from `start`.
 * @param {number} start
 * @param {number} count
 * @param {number} lat
 */
const bandOf = (start, count, lat) =>
  Math.min(count - 1, Math.max(0, Math.floor((lat - start) / REACH_STEP)));

/**
 * Where the continental US has land, band by band of latitude, as pieces not
 * yet merged: the land along a few lines of latitude in each band, and every
 * vertex of the outline, so an island or a shore between those lines counts.
 * @param {Line[]} lines the outline
 * @param {Bounds} bounds
 * @returns {{ start: number, pieces: Piece[][] }}
 */
function landPieces(lines, bounds) {
  const [, south, , north] = bounds;
  const start = Math.floor(south / REACH_STEP) * REACH_STEP;
  const count = Math.ceil((north - start) / REACH_STEP);
  const spacing = REACH_STEP / REACH_SCANLINES;
  /** @type {Piece[][]} */
  const pieces = Array.from({ length: count }, () => []);
  for (let band = 0; band < count; band++) {
    const bandSouth = start + band * REACH_STEP;
    for (let line = 0; line < REACH_SCANLINES; line++) {
      const lat = bandSouth + (line + 0.5) * spacing;
      // A scanline stands for the strip of latitude around it.
      const low = Math.max(bandSouth, lat - spacing / 2);
      const high = Math.min(bandSouth + REACH_STEP, lat + spacing / 2);
      for (const [west, east] of landAlong(lines, lat)) pieces[band]?.push([west, east, low, high]);
    }
  }
  for (const line of lines) {
    for (const [lng = NaN, lat = NaN] of line) {
      pieces[bandOf(start, count, lat)]?.push([lng, lng, lat, lat]);
    }
  }
  return { start, pieces };
}

/**
 * The pieces of each band merged across gaps narrower than REACH_GAP (lakes,
 * bays, sounds, the water between a shore and its islands) and rounded
 * outward to the lines' grid, as flat west, east, south, north runs.
 * @param {Piece[][]} pieces
 * @returns {number[][]}
 */
function mergeRuns(pieces) {
  return pieces.map((band) => {
    const sorted = [...band].sort((a, b) => a[0] - b[0]);
    /** @type {Piece[]} */
    const merged = [];
    for (const piece of sorted) {
      const last = merged.at(-1);
      if (last !== undefined && piece[0] - last[1] <= REACH_GAP) {
        last[1] = Math.max(last[1], piece[1]);
        last[2] = Math.min(last[2], piece[2]);
        last[3] = Math.max(last[3], piece[3]);
      } else {
        merged.push([...piece]);
      }
    }
    if (merged.length === 0) throw new Error('build-geo: a reach band holds no land');
    return merged.flatMap(([west, east, low, high]) => [
      Math.floor(west / PRECISION) * PRECISION,
      Math.ceil(east / PRECISION) * PRECISION,
      Math.floor(low / PRECISION) * PRECISION,
      Math.ceil(high / PRECISION) * PRECISION,
    ]);
  });
}

/**
 * Whether a point lies inside the reach, edges included, as the map reads it:
 * the runs' numbers as written to us-reach.ts. A run stays within a grid step
 * of its own band, so only the point's band and its neighbours can hold it.
 * @param {Reach} reach
 * @param {number} lon
 * @param {number} lat
 */
function reaches({ start, runs }, lon, lat) {
  const band = bandOf(start, runs.length, lat);
  for (let b = Math.max(0, band - 1); b <= Math.min(runs.length - 1, band + 1); b++) {
    const run = (runs[b] ?? []).map((value) => Number(num(value)));
    for (let i = 0; i + 3 < run.length; i += 4) {
      const [west = NaN, east = NaN, south = NaN, north = NaN] = run.slice(i, i + 4);
      if (lon >= west && lon <= east && lat >= south && lat <= north) return true;
    }
  }
  return false;
}

/**
 * Where the continental US is, band by band of latitude: the land in the
 * outline, and every school in the directory, each on its own island if need be.
 * @param {Line[]} lines the outline
 * @param {Bounds} bounds
 * @param {readonly School[]} outlying schools the outline's land misses
 * @returns {Reach}
 */
function reachOf(lines, bounds, outlying) {
  const { start, pieces } = landPieces(lines, bounds);
  for (const { lon, lat } of outlying) {
    pieces[bandOf(start, pieces.length, lat)]?.push([lon, lon, lat, lat]);
  }
  return { start, runs: mergeRuns(pieces) };
}

/**
 * The schools in `schools` that the outline's land alone misses.
 * @param {Line[]} lines the outline
 * @param {Bounds} bounds
 * @param {readonly School[]} schools
 * @returns {School[]}
 */
function outlyingSchools(lines, bounds, schools) {
  const land = reachOf(lines, bounds, []);
  return schools
    .filter((school) => !reaches(land, school.lon, school.lat))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

/** points.bin: a 16-byte header, then 13 bytes per school (see pipeline/snowlight/directory/points.py). */
const POINTS_MAGIC = 'SLPT';
const POINTS_VERSION = 1;
const POINTS_HEADER = 16;
const POINTS_RECORD = 13;

/**
 * Every school in the directory under `site`, with its id and location, or
 * null when the directory has not been built there.
 * @param {string} site
 * @returns {Promise<School[] | null>}
 */
async function readSchools(site) {
  const points = await readFile(join(site, 'schools/points.bin')).catch(() => null);
  if (points === null) return null;
  /** @type {unknown} */
  const parsed = JSON.parse(await readFile(join(site, 'schools/meta.json'), 'utf8'));
  const ids = /** @type {{ ids?: unknown }} */ (parsed).ids;
  const view = new DataView(points.buffer, points.byteOffset, points.byteLength);
  const count = points.length >= POINTS_HEADER ? view.getUint32(8, true) : -1;
  if (
    points.subarray(0, 4).toString('latin1') !== POINTS_MAGIC ||
    view.getUint16(4, true) !== POINTS_VERSION ||
    view.getUint16(6, true) !== POINTS_RECORD ||
    points.length !== POINTS_HEADER + POINTS_RECORD * count
  ) {
    throw new Error(
      `build-geo: ${join(site, 'schools/points.bin')} is not a points.bin it can read`,
    );
  }
  if (!Array.isArray(ids) || ids.length !== count) {
    throw new Error('build-geo: schools/meta.json does not list the schools in points.bin');
  }
  /** @type {School[]} */
  const schools = [];
  for (let i = 0; i < count; i++) {
    const at = POINTS_HEADER + POINTS_RECORD * i;
    schools.push({
      id: String(ids[i]),
      lon: view.getInt32(at, true) / 1e6,
      lat: view.getInt32(at + 4, true) / 1e6,
    });
  }
  return schools;
}

/**
 * The committed list of schools the outline misses.
 * @returns {Promise<School[]>}
 */
async function readReachSchools() {
  /** @type {unknown} */
  const parsed = JSON.parse(await readFile(REACH_SCHOOLS_FILE, 'utf8'));
  const schools = /** @type {{ schools?: unknown }} */ (parsed).schools;
  if (!Array.isArray(schools)) throw new Error(`build-geo: ${REACH_SCHOOLS_FILE} lists no schools`);
  return schools.map((entry) => {
    const { id, lon, lat } = /** @type {Partial<School>} */ (entry);
    if (typeof id !== 'string' || typeof lon !== 'number' || typeof lat !== 'number') {
      throw new Error(`build-geo: ${REACH_SCHOOLS_FILE} has an entry without id, lon and lat`);
    }
    return { id, lon, lat };
  });
}

/**
 * scripts/reach-schools.json: the schools the outline misses, by federal id.
 * @param {readonly School[]} schools
 */
function reachSchoolsText(schools) {
  return `${JSON.stringify({ schools: schools.map(({ id, lon, lat }) => ({ id, lon, lat })) })}\n`;
}

/**
 * @typedef {object} City
 * @property {string} name as the map shows it
 * @property {string} state postal code
 * @property {number} lon
 * @property {number} lat
 * @property {number} population its own
 * @property {number} people its own and its surroundings' (chooseCities)
 */

/** Census place kinds of consolidated city-county governments. */
const GOVERNMENTS = [
  'unified government',
  'consolidated government',
  'urban county',
  'metropolitan government',
];

/**
 * Census places whose legal name is not the one the city goes by, by name and
 * state: Boise, Idaho, is incorporated as "Boise City".
 * @type {ReadonlyMap<string, string>}
 */
const CITY_NAMES_IN_USE = new Map([['Boise City, ID', 'Boise']]);

/**
 * A Census place's name as a map names the city. Consolidated city-county
 * governments carry their county and legal form in the name, "Nashville-Davidson
 * metropolitan government (balance)" or "Indianapolis city (balance)": the
 * city's own name is the part before them. A city incorporated under another
 * name than the one it goes by (CITY_NAMES_IN_USE) takes that one. Every other
 * name is kept as it is.
 * @param {string} name
 * @param {string | null} kind
 * @param {string} state
 */
function cityName(name, kind, state) {
  const inUse = CITY_NAMES_IN_USE.get(`${name}, ${state}`);
  if (inUse !== undefined) return inUse;
  const legal =
    (kind !== null && GOVERNMENTS.includes(kind)) ||
    /\(balance\)$| County\b|government$/.test(name);
  if (!legal) return name;
  const bare = name.replace(/ \(balance\)$/, '').replace(/ city$/, '');
  const city = bare.split(/[-/,]/)[0] ?? bare;
  return city
    .replace(/ (?:unified|consolidated|metropolitan|metro) government$/, '')
    .replace(/ County$/, '')
    .trim();
}

/**
 * Whether a point lies on the land: inside an odd number of its rings.
 * @param {Line[]} rings
 * @param {number} lon
 * @param {number} lat
 */
function onLand(rings, lon, lat) {
  let inside = false;
  for (const ring of rings) {
    for (let i = 1; i < ring.length; i++) {
      const [x0 = NaN, y0 = NaN] = ring[i - 1] ?? [];
      const [x1 = NaN, y1 = NaN] = ring[i] ?? [];
      if (y0 < lat === y1 < lat) continue;
      if (lon < x0 + ((lat - y0) / (y1 - y0)) * (x1 - x0)) inside = !inside;
    }
  }
  return inside;
}

/**
 * @typedef {object} Zip
 * @property {number} lon
 * @property {number} lat
 * @property {string[]} states
 * @property {{ name: string, share: number }[]} districts
 */

/**
 * Where a city's name goes. A Census place's point is inside the place, but
 * a city whose limits take in open water can have it out on the water (San
 * Francisco's is 48 km out at sea, with the Farallon Islands), and the
 * outline, drawn for the whole country, smooths away small peninsulas
 * (Portland, Maine's). The name goes at the city's Census point when that is
 * on the land; else at the middle of the ZIP codes the city's own school
 * district serves (the district named after the city: "San Francisco
 * Unified School District"); else, when either point is within
 * CITY_SHORE_KM of the land, just inside the nearest shore; else nowhere.
 * @param {Line[]} rings the land's
 * @param {readonly Zip[]} zips
 * @param {{ name: string, state: string, lon: number, lat: number }} city
 * @returns {{ lon: number, lat: number } | null}
 */
function namePoint(rings, zips, city) {
  if (onLand(rings, city.lon, city.lat)) return { lon: city.lon, lat: city.lat };
  const center = districtCenter(zips, city);
  if (center !== null && onLand(rings, center.lon, center.lat)) return center;
  return (center === null ? null : shoreNear(rings, center)) ?? shoreNear(rings, city);
}

/**
 * The middle of the ZIP codes a city's own school district serves (its
 * share of them at least CITY_DISTRICT_SHARE), or null when there are none.
 * @param {readonly Zip[]} zips
 * @param {{ name: string, state: string }} city
 * @returns {{ lon: number, lat: number } | null}
 */
function districtCenter(zips, city) {
  const prefix = `${city.name} `;
  const served = zips.filter(
    (zip) =>
      zip.states.includes(city.state) &&
      zip.districts.some(
        (district) => district.name.startsWith(prefix) && district.share >= CITY_DISTRICT_SHARE,
      ),
  );
  if (served.length === 0) return null;
  return {
    lon: Number(num(round(served.reduce((sum, zip) => sum + zip.lon, 0) / served.length))),
    lat: Number(num(round(served.reduce((sum, zip) => sum + zip.lat, 0) / served.length))),
  };
}

/** Kilometres per degree of latitude. */
const KM_PER_DEGREE = 6371 * (Math.PI / 180);

/**
 * A point CITY_SHORE_INSET_KM inside the shore nearest to `point`, on from
 * the water it lies on, or null when that shore is more than CITY_SHORE_KM
 * away or the point past it is not on the land.
 * @param {Line[]} rings the land's
 * @param {{ lon: number, lat: number }} point
 * @returns {{ lon: number, lat: number } | null}
 */
function shoreNear(rings, point) {
  // Flat kilometres around the point: close enough over these distances.
  const kx = KM_PER_DEGREE * Math.cos((point.lat * Math.PI) / 180);
  const ky = KM_PER_DEGREE;
  let best = { distance: Infinity, x: 0, y: 0 };
  for (const ring of rings) {
    for (let i = 1; i < ring.length; i++) {
      const [lon0 = NaN, lat0 = NaN] = ring[i - 1] ?? [];
      const [lon1 = NaN, lat1 = NaN] = ring[i] ?? [];
      const ax = (lon0 - point.lon) * kx;
      const ay = (lat0 - point.lat) * ky;
      const bx = (lon1 - point.lon) * kx;
      const by = (lat1 - point.lat) * ky;
      const length = (bx - ax) ** 2 + (by - ay) ** 2;
      const t =
        length === 0 ? 0 : Math.max(0, Math.min(1, -(ax * (bx - ax) + ay * (by - ay)) / length));
      const x = ax + t * (bx - ax);
      const y = ay + t * (by - ay);
      const distance = Math.hypot(x, y);
      if (distance < best.distance) best = { distance, x, y };
    }
  }
  if (best.distance > CITY_SHORE_KM || best.distance === 0) return null;
  const on = (best.distance + CITY_SHORE_INSET_KM) / best.distance;
  const lon = Number(num(round(point.lon + (best.x * on) / kx)));
  const lat = Number(num(round(point.lat + (best.y * on) / ky)));
  return onLand(rings, lon, lat) ? { lon, lat } : null;
}

/**
 * The ZIP codes the pipeline writes for search, or null when they have not
 * been built under `site`.
 * @param {string} site
 * @returns {Promise<Zip[] | null>}
 */
async function readZips(site) {
  const text = await readFile(join(site, 'search/zips.jsonl'), 'utf8').catch(() => null);
  if (text === null) return null;
  return text
    .split('\n')
    .filter((line) => line.trim() !== '')
    .map((line) => {
      const { lon, lat, states, districts } = /** @type {Partial<Zip>} */ (JSON.parse(line));
      if (
        typeof lon !== 'number' ||
        typeof lat !== 'number' ||
        !Array.isArray(states) ||
        !Array.isArray(districts)
      ) {
        throw new Error(
          'build-geo: search/zips.jsonl has a ZIP code without location, states and districts',
        );
      }
      return { lon, lat, states, districts };
    });
}

/** Great-circle distance in kilometres. */
function kilometres(/** @type {City} */ a, /** @type {City} */ b) {
  const rad = Math.PI / 180;
  const h =
    Math.sin(((b.lat - a.lat) * rad) / 2) ** 2 +
    Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(((b.lon - a.lon) * rad) / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
}

/**
 * The places the pipeline writes for search, or null when they have not been
 * built under `site`.
 * @param {string} site
 * @returns {Promise<{ name: string, kind: string | null, state: string, lon: number, lat: number, population: number | null }[] | null>}
 */
async function readPlaces(site) {
  const text = await readFile(join(site, 'search/cities.jsonl'), 'utf8').catch(() => null);
  if (text === null) return null;
  return text
    .split('\n')
    .filter((line) => line.trim() !== '')
    .map((line) => {
      const place = /** @type {Record<string, unknown>} */ (JSON.parse(line));
      const { name, kind, state, lon, lat, population } = place;
      if (
        typeof name !== 'string' ||
        typeof state !== 'string' ||
        typeof lon !== 'number' ||
        typeof lat !== 'number'
      ) {
        throw new Error(
          'build-geo: search/cities.jsonl has a place without name, state and location',
        );
      }
      return {
        name,
        kind: typeof kind === 'string' ? kind : null,
        state,
        lon,
        lat,
        population: typeof population === 'number' ? population : null,
      };
    });
}

/**
 * The cities named at the national view, in the order MapLibre places them.
 *
 * A city's people are its own and those of every incorporated place around
 * it (within CITY_AREA_KM) with no larger city within reach: Atlanta counts
 * Sandy Springs and Marietta, Boston counts Cambridge and Quincy, so the
 * cities a country map names first are the centres of its largest urban
 * areas, not the largest city limits. (Census-designated places carry no
 * population in the places file, so they count for nothing.)
 *
 * They are ranked by their people, raised for a city far from any with more
 * (up to CITY_ISOLATION_MAX times, from CITY_ISOLATION_KM away), since its
 * name is the only one for its region: Albuquerque and Boise come before
 * the suburbs of Dallas; the capital, Washington, ranks with the largest. The CITY_TOP first are named, and each one after
 * them with no named city within CITY_REGION_KM, so the plains and the
 * mountains have names up close too. Each is named at namePoint.
 * @param {NonNullable<Awaited<ReturnType<typeof readPlaces>>>} places
 * @param {readonly Zip[]} zips
 * @param {Line[]} outline
 * @returns {City[]}
 */
function chooseCities(places, zips, outline) {
  const counted = places.filter(
    (place) => place.population !== null && !EXCLUDED_STATES.includes(place.state),
  );
  /** @type {Map<(typeof counted)[number], City>} */
  const named = new Map();
  for (const place of counted) {
    const population = place.population ?? 0;
    if (population < CITY_MIN_POPULATION) continue;
    if (place.kind !== null && NOT_A_CITY.includes(place.kind)) continue;
    const city = {
      name: cityName(place.name, place.kind, place.state),
      state: place.state,
      lon: Number(num(round(place.lon))),
      lat: Number(num(round(place.lat))),
      population,
      people: 0,
    };
    const at = namePoint(outline, zips, city);
    if (at !== null) named.set(place, { ...city, lon: at.lon, lat: at.lat });
  }
  const candidates = [...named.values()].sort(
    (a, b) => b.population - a.population || a.name.localeCompare(b.name),
  );

  // Candidates by whole degree of latitude and longitude; CITY_AREA_KM is under a degree of either.
  /** @type {Map<string, City[]>} */
  const cells = new Map();
  /** @param {number} lon @param {number} lat */
  const cellKey = (lon, lat) => `${String(Math.floor(lon))},${String(Math.floor(lat))}`;
  for (const city of candidates) {
    const key = cellKey(city.lon, city.lat);
    const cell = cells.get(key) ?? [];
    cell.push(city);
    cells.set(key, cell);
  }
  for (const place of counted) {
    // A named city counts where it is named.
    const at = named.get(place) ?? place;
    /** @type {City | undefined} */
    let largest;
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        for (const city of cells.get(cellKey(at.lon + dx, at.lat + dy)) ?? []) {
          if (largest !== undefined && city.population <= largest.population) continue;
          if (kilometres(at, city) <= CITY_AREA_KM) largest = city;
        }
      }
    }
    if (largest !== undefined) largest.people += place.population ?? 0;
  }

  const byPeople = [...candidates].sort(
    (a, b) => b.people - a.people || b.population - a.population || a.name.localeCompare(b.name),
  );
  /** @type {Map<City, number>} */
  const score = new Map();
  byPeople.forEach((city, index) => {
    let isolation = Infinity;
    for (const other of byPeople.slice(0, index)) {
      isolation = Math.min(isolation, kilometres(city, other));
    }
    const lift = Math.min(CITY_ISOLATION_MAX, Math.max(1, isolation / CITY_ISOLATION_KM));
    score.set(city, city.people * lift);
  });
  // The capital ranks with the largest: level with the first, and after it, the larger city.
  const top = Math.max(...score.values());
  for (const city of byPeople) if (city.state === CAPITAL_STATE) score.set(city, top);
  const ranked = [...byPeople].sort(
    (a, b) =>
      (score.get(b) ?? 0) - (score.get(a) ?? 0) ||
      b.population - a.population ||
      a.name.localeCompare(b.name),
  );

  /** @type {City[]} */
  const chosen = [];
  for (const city of ranked) {
    if (
      chosen.length < CITY_TOP ||
      chosen.every((other) => kilometres(city, other) > CITY_REGION_KM)
    ) {
      chosen.push(city);
    }
  }
  return chosen;
}

/**
 * The committed list of cities named at the national view.
 * @returns {Promise<City[]>}
 */
async function readCities() {
  /** @type {unknown} */
  const parsed = JSON.parse(await readFile(CITIES_FILE, 'utf8'));
  const cities = /** @type {{ cities?: unknown }} */ (parsed).cities;
  if (!Array.isArray(cities)) throw new Error(`build-geo: ${CITIES_FILE} lists no cities`);
  return cities.map((entry) => {
    const { name, state, lon, lat, population, people } = /** @type {Partial<City>} */ (entry);
    if (
      typeof name !== 'string' ||
      typeof state !== 'string' ||
      typeof lon !== 'number' ||
      typeof lat !== 'number' ||
      typeof population !== 'number' ||
      typeof people !== 'number'
    ) {
      throw new Error(
        `build-geo: ${CITIES_FILE} has an entry without name, state, location and population`,
      );
    }
    return { name, state, lon, lat, population, people };
  });
}

/**
 * scripts/national-cities.json: the cities named at the national view, in rank order.
 * @param {readonly City[]} cities
 */
function citiesText(cities) {
  return `${JSON.stringify({
    cities: cities.map(({ name, state, lon, lat, population, people }) => ({
      name,
      state,
      lon,
      lat,
      population,
      people,
    })),
  })}\n`;
}

/** @param {Reach} reach */
function reachText({ start, runs }) {
  const rows = runs.map((run) => `[${run.map((value) => num(value)).join(', ')}]`).join(', ');
  return `// Generated by scripts/build-geo.mjs from the outline in the bundled US lines
// and the schools in scripts/reach-schools.json. Do not edit by hand: run
// "npm run build:geo".

/**
 * Where the continental US is, band by band of latitude. Band i runs from
 * start + i * step to start + (i + 1) * step degrees north; runs[i] lists the
 * pieces of land in it as west, east, south, north quadruples in degrees,
 * islands included and gaps under ${num(REACH_GAP)} degrees (lakes, bays, sounds) closed.
 * Every school in the directory lies inside a piece, the few on islands the
 * outline leaves out too.
 */
export const US_LAND: {
  readonly start: number;
  readonly step: number;
  readonly runs: readonly (readonly number[])[];
} = { start: ${num(start)}, step: ${num(REACH_STEP)}, runs: [${rows}] };
`;
}

/** @param {Kinds} kinds */
function geojsonText(kinds, /** @type {readonly City[]} */ cities) {
  /** @param {Line} line */
  const coordinates = (line) =>
    `[${line.map(([lng, lat]) => `[${num(lng)},${num(lat)}]`).join(',')}]`;
  const state = `{"type":"Feature","properties":{"kind":"state"},"geometry":{"type":"MultiLineString","coordinates":[${kinds.state
    .map(coordinates)
    .join(',')}]}}`;
  const land = `{"type":"Feature","properties":{"kind":"land"},"geometry":{"type":"MultiPolygon","coordinates":[${kinds.land
    .map((polygon) => `[${polygon.map(coordinates).join(',')}]`)
    .join(',')}]}}`;
  // Rank 0 is the largest city: MapLibre places the lowest rank first.
  const names = cities.map(
    ({ name, lon, lat }, rank) =>
      `{"type":"Feature","properties":{"kind":"city","name":${JSON.stringify(name)},"rank":${String(rank)}},"geometry":{"type":"Point","coordinates":[${num(lon)},${num(lat)}]}}`,
  );
  return `{"type":"FeatureCollection","features":[${[land, state, ...names].join(',')}]}\n`;
}

/**
 * SVG path data in a Mercator grid whose origin is the north-west corner of the bounds.
 * @param {Kinds} kinds
 * @param {Bounds} bounds
 */
function stillSvg(kinds, bounds) {
  const [west, south, east, north] = bounds;
  const x0 = mercatorX(west);
  const y0 = mercatorY(north);
  const scale = STILL_WIDTH / (mercatorX(east) - x0);
  const height = (mercatorY(south) - y0) * scale;

  /**
   * @param {Line[]} lines
   * @param {boolean} closed each line a ring, closed with "z" in place of its last point
   */
  const pathData = (lines, closed) => {
    let d = '';
    for (const line of lines) {
      /** @type {Point | undefined} */
      let previous;
      let first = true;
      for (const [lng, lat] of closed ? line.slice(0, -1) : line) {
        const x = Math.round((mercatorX(lng) - x0) * scale);
        const y = Math.round((mercatorY(lat) - y0) * scale);
        if (previous === undefined) {
          d += `M${String(x)} ${String(y)}`;
        } else {
          const dx = x - previous[0];
          const dy = y - previous[1];
          if (dx === 0 && dy === 0) continue;
          d += `${first ? 'l' : dx < 0 ? '' : ' '}${String(dx)}${dy < 0 ? '' : ' '}${String(dy)}`;
          first = false;
        }
        previous = [x, y];
      }
      if (closed) d += 'z';
    }
    return d;
  };

  const viewBox = `0 0 ${String(STILL_WIDTH)} ${num(height, 2)}`;
  // The land's shape is drawn twice from one path: filled under the state lines, and its
  // edge (the outline) stroked over them, as the WebGL map draws them.
  const svg =
    `<svg class="still" viewBox="${viewBox}" preserveAspectRatio="xMidYMid meet" aria-hidden="true" focusable="false">` +
    `<defs><path id="still-land" vector-effect="non-scaling-stroke" d="${pathData(kinds.outline, true)}"/></defs>` +
    `<use class="still-land" href="#still-land"/>` +
    `<path class="still-state" d="${pathData(kinds.state, false)}"/>` +
    `<use class="still-outline" href="#still-land"/>` +
    `</svg>`;
  return { svg, viewBox };
}

/**
 * @param {{ bounds: Bounds, file: string, viewBox: string, gzipBytes: number }} meta
 */
function metaText({ bounds, file, viewBox, gzipBytes }) {
  return `// Generated by scripts/build-geo.mjs from us-atlas states-10m (Census Bureau
// cartographic state boundaries, 2017 edition). Do not edit by hand: run
// "npm run build:geo".

/** West, south, east, north of the bundled continental US lines, in degrees. */
export const US_BOUNDS = [${bounds.map((value) => num(value)).join(', ')}] as const;

/** The bundled GeoJSON, relative to the site base URL. */
export const US_LINES_FILE = '${file}';

/** viewBox of the inline still in index.html: Web Mercator, north-west corner at 0 0. */
export const STILL_VIEWBOX = '${viewBox}';

/** Gzipped size of the bundled GeoJSON, in bytes. */
export const US_LINES_GZIP_BYTES = ${String(gzipBytes)};

`;
}

/**
 * @param {string} html
 * @param {string} svg
 */
function spliceStill(html, svg) {
  const start = html.indexOf(STILL_START);
  const end = html.indexOf(STILL_END);
  if (start === -1 || end === -1 || end < start) {
    throw new Error(`build-geo: index.html needs ${STILL_START} and ${STILL_END} markers`);
  }
  return html.slice(0, start + STILL_START.length) + svg + html.slice(end);
}

/**
 * Formats generated text the way "npm run format" would, so format:check stays clean.
 * @param {string} text
 * @param {string} path
 */
async function format(text, path) {
  const config = (await prettier.resolveConfig(path)) ?? {};
  return prettier.format(text, { ...config, filepath: path });
}

async function main() {
  const check = process.argv.includes('--check');
  const siteFlag = process.argv.indexOf('--site-data');
  const siteArg = siteFlag === -1 ? undefined : process.argv[siteFlag + 1];
  if (siteFlag !== -1 && siteArg === undefined)
    throw new Error('build-geo: --site-data needs a directory');
  const site = siteArg === undefined ? DEFAULT_SITE_DATA : resolve(siteArg);
  const kinds = await extractGeometry();
  const bounds = boundsOf(kinds);
  // The cities: chosen afresh from the pipeline's places when they are here, read as committed when not.
  const places = await readPlaces(site);
  if (places === null && siteArg !== undefined) {
    throw new Error(`build-geo: no search/cities.jsonl under ${siteArg}`);
  }
  const zips = places === null ? null : await readZips(site);
  if (places !== null && zips === null) {
    throw new Error(`build-geo: search/cities.jsonl but no search/zips.jsonl under ${site}`);
  }
  const cities =
    places === null || zips === null
      ? await readCities()
      : chooseCities(places, zips, kinds.outline);
  const geojson = await format(geojsonText(kinds, cities), join(GEO_DIR, 'us-lines.json'));
  const gzipBytes = gzipSync(geojson, { level: 9 }).length;
  if (gzipBytes > MAX_GZIP_BYTES) {
    throw new Error(
      `build-geo: GeoJSON is ${String(gzipBytes)} B gzipped, over the ${String(MAX_GZIP_BYTES)} B budget`,
    );
  }
  const hash = createHash('sha256').update(geojson).digest('hex').slice(0, 10);
  const fileName = `us-lines.${hash}.json`;
  const points = [kinds.outline, kinds.state].reduce(
    (sum, lines) => sum + lines.reduce((n, line) => n + line.length, 0),
    0,
  );
  const { svg, viewBox } = stillSvg(kinds, bounds);
  const meta = await format(
    metaText({ bounds, file: `geo/${fileName}`, viewBox, gzipBytes }),
    META_FILE,
  );
  const html = await format(spliceStill(await readFile(INDEX_HTML, 'utf8'), svg), INDEX_HTML);
  // The schools the outline misses: found afresh in the directory when it is
  // here, read as committed when it is not.
  const directory = await readSchools(site);
  if (directory === null && siteArg !== undefined) {
    throw new Error(`build-geo: no schools/points.bin under ${siteArg}`);
  }
  const outlying =
    directory === null
      ? await readReachSchools()
      : outlyingSchools(kinds.outline, bounds, directory);
  const reachData = reachOf(kinds.outline, bounds, outlying);
  const missed = (directory ?? []).filter(({ lon, lat }) => !reaches(reachData, lon, lat));
  if (missed.length > 0) {
    throw new Error(`build-geo: the reach misses ${String(missed.length)} schools`);
  }
  const reach = await format(reachText(reachData), REACH_FILE);
  const reachSchools = await format(reachSchoolsText(outlying), REACH_SCHOOLS_FILE);
  const citiesJson = await format(citiesText(cities), CITIES_FILE);

  /** @type {string[]} */
  const stale = [];
  /** @param {string} path */
  const readOr = async (path) => readFile(path, 'utf8').catch(() => null);
  const existing = (await readdir(GEO_DIR).catch(() => /** @type {string[]} */ ([]))).filter(
    (name) => /^us-lines\.[0-9a-f]+\.json$/.test(name),
  );
  /** @type {[string, string][]} */
  const wanted = [
    [join(GEO_DIR, fileName), geojson],
    [META_FILE, meta],
    [REACH_FILE, reach],
    ...(directory === null
      ? []
      : [/** @type {[string, string]} */ ([REACH_SCHOOLS_FILE, reachSchools])]),
    ...(places === null ? [] : [/** @type {[string, string]} */ ([CITIES_FILE, citiesJson])]),
    [INDEX_HTML, html],
  ];
  for (const [path, text] of wanted) {
    if ((await readOr(path)) !== text) stale.push(path);
  }
  const extra = existing.filter((name) => name !== fileName).map((name) => join(GEO_DIR, name));
  stale.push(...extra);

  const schools =
    directory === null
      ? `${String(outlying.length)} schools off the outline, as committed (no directory here)`
      : `${String(directory.length)} schools, ${String(outlying.length)} off the outline`;
  const named =
    places === null
      ? `${String(cities.length)} cities, as committed (no places here)`
      : `${String(cities.length)} cities`;
  const summary = `${String(points)} vertices, ${String(geojson.length)} B raw, ${String(gzipBytes)} B gzipped, still ${String(svg.length)} B; ${schools}; ${named}`;
  if (check) {
    if (stale.length > 0) {
      process.stderr.write(
        `build-geo: stale, run "npm run build:geo":\n${stale.map((p) => `  ${relative(WEB, p)}\n`).join('')}`,
      );
      process.exit(1);
    }
    process.stdout.write(`build-geo: up to date (${summary})\n`);
    return;
  }
  for (const path of extra) await rm(path);
  for (const [path, text] of wanted) {
    if (stale.includes(path)) await writeFile(path, text);
  }
  process.stdout.write(`build-geo: wrote ${fileName} (${summary})\n`);
}

await main();
