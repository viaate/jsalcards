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
 *   index.html                         The inline SVG still between the
 *                                      geo:still markers, drawn in Web Mercator
 *                                      so it matches the WebGL map at the
 *                                      initial view.
 *
 *   node scripts/build-geo.mjs          write the files
 *   node scripts/build-geo.mjs --check  exit 1 if any file is stale
 */
import { createHash } from 'node:crypto';
import { readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join, relative } from 'node:path';
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
const INDEX_HTML = join(WEB, 'index.html');

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
    [INDEX_HTML, html],
  ];
  for (const [path, text] of wanted) {
    if ((await readOr(path)) !== text) stale.push(path);
  }
  const extra = existing.filter((name) => name !== fileName).map((name) => join(GEO_DIR, name));
  stale.push(...extra);

  const summary = `${String(points)} vertices, ${String(geojson.length)} B raw, ${String(gzipBytes)} B gzipped, still ${String(svg.length)} B`;
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
