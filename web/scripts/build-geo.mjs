#!/usr/bin/env node
/**
 * Builds the bundled continental US geometry that Snowlight draws below zoom 7.
 *
 * Input: us-atlas states-10m.json (Census Bureau cartographic state boundaries,
 * 2017 edition, as TopoJSON), simplified to a tolerance finer than a pixel at
 * every zoom the lines are drawn at. Output, all deterministic:
 *
 *   public/geo/us-lines.<hash>.json   GeoJSON for MapLibre: the outline (coasts,
 *                                      lake shores, borders) and the state lines.
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
 *   node scripts/build-geo.mjs                     write the files
 *   node scripts/build-geo.mjs --check             exit 1 if any file is stale
 *   node scripts/build-geo.mjs --site-data <dir>   read the directory from <dir>
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
/** @typedef {{ outline: Line[], state: Line[] }} Kinds */
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
 * Runs mapshaper on the TopoJSON and returns line strings grouped by kind.
 * @returns {Promise<Kinds>}
 */
async function extractLines() {
  const topology = await readFile(SOURCE, 'utf8');
  const commands = [
    '-i states.json id-field=fips',
    '-target states',
    `-filter '!${JSON.stringify(EXCLUDED_FIPS)}.includes(fips)'`,
    `-each 'fips = fips === "${DC_FIPS}" ? "${MD_FIPS}" : fips'`,
    '-dissolve fips',
    `-simplify dp interval=${String(SIMPLIFY_METERS)}m keep-shapes`,
    // Polygon rings become lines; TYPE is "outer" for the national outline and "inner" for shared state borders.
    '-lines',
    '-o out.json format=geojson',
  ].join(' ');
  const output = await mapshaper.applyCommands(commands, { 'states.json': topology });
  const text = output['out.json'];
  if (text === undefined) throw new Error('build-geo: mapshaper wrote no output');
  /** @type {unknown} */
  const parsed = JSON.parse(typeof text === 'string' ? text : new TextDecoder().decode(text));
  const collection = /** @type {{ features: LineFeature[] }} */ (parsed);

  /** @type {Kinds} */
  const kinds = { outline: [], state: [] };
  for (const feature of collection.features) {
    const kind = feature.properties.TYPE === 'outer' ? 'outline' : 'state';
    const geometry = feature.geometry;
    const parts = geometry.type === 'LineString' ? [geometry.coordinates] : geometry.coordinates;
    for (const part of parts) {
      /** @type {Line} */
      const line = [];
      for (const [lng = NaN, lat = NaN] of part) {
        /** @type {Point} */
        const point = [round(lng), round(lat)];
        const last = line.at(-1);
        if (last?.[0] !== point[0] || last[1] !== point[1]) line.push(point);
      }
      if (line.length >= 2) kinds[kind].push(line);
    }
  }
  // Stable order regardless of mapshaper's internal ordering.
  /** @param {Line} line */
  const key = (line) => {
    const [lng = NaN, lat = NaN] = line[0] ?? [];
    return `${num(lng)},${num(lat)},${String(line.length)}`;
  };
  for (const lines of Object.values(kinds)) lines.sort((a, b) => key(a).localeCompare(key(b)));
  return kinds;
}

/**
 * @param {Kinds} kinds
 * @returns {Bounds}
 */
function boundsOf(kinds) {
  let [west, south, east, north] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const lines of Object.values(kinds)) {
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
function geojsonText(kinds) {
  /** @param {keyof Kinds} kind */
  const feature = (kind) =>
    `{"type":"Feature","properties":{"kind":"${kind}"},"geometry":{"type":"MultiLineString","coordinates":[${kinds[
      kind
    ]
      .map((line) => `[${line.map(([lng, lat]) => `[${num(lng)},${num(lat)}]`).join(',')}]`)
      .join(',')}]}}`;
  // State lines first so the outline draws on top where they meet.
  return `{"type":"FeatureCollection","features":[${feature('state')},${feature('outline')}]}\n`;
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

  /** @param {Line[]} lines */
  const pathData = (lines) => {
    let d = '';
    for (const line of lines) {
      /** @type {Point | undefined} */
      let previous;
      let first = true;
      for (const [lng, lat] of line) {
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
    }
    return d;
  };

  const viewBox = `0 0 ${String(STILL_WIDTH)} ${num(height, 2)}`;
  const svg =
    `<svg class="still" viewBox="${viewBox}" preserveAspectRatio="xMidYMid meet" aria-hidden="true" focusable="false">` +
    `<path class="still-state" d="${pathData(kinds.state)}"/>` +
    `<path class="still-outline" d="${pathData(kinds.outline)}"/>` +
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
  const kinds = await extractLines();
  const bounds = boundsOf(kinds);
  const geojson = await format(geojsonText(kinds), join(GEO_DIR, 'us-lines.json'));
  const gzipBytes = gzipSync(geojson, { level: 9 }).length;
  if (gzipBytes > MAX_GZIP_BYTES) {
    throw new Error(
      `build-geo: GeoJSON is ${String(gzipBytes)} B gzipped, over the ${String(MAX_GZIP_BYTES)} B budget`,
    );
  }
  const hash = createHash('sha256').update(geojson).digest('hex').slice(0, 10);
  const fileName = `us-lines.${hash}.json`;
  const points = Object.values(kinds).reduce(
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
  const directory = await readSchools(siteArg === undefined ? DEFAULT_SITE_DATA : resolve(siteArg));
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
  const summary = `${String(points)} vertices, ${String(geojson.length)} B raw, ${String(gzipBytes)} B gzipped, still ${String(svg.length)} B; ${schools}`;
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
