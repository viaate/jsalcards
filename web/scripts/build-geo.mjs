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
 *   public/geo/us-names.<hash>.json   The same file's city and state names
 *                                      alone: what the page itself reads of it,
 *                                      and the names' own source on the map.
 *   public/geo/us-states.<hash>.json  Each state's shape, coarser: where a
 *                                      phone names the states in view closer
 *                                      in (state-areas.ts), loaded only then.
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
import { createRequire, registerHooks } from 'node:module';
import { dirname, join, relative, resolve } from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { TextDecoder } from 'node:util';
import { gunzipSync, gzipSync } from 'node:zlib';

import prettier from 'prettier';

// The US mask's reader is TypeScript shared with the site (readBorder). Node strips its types;
// this hook lets its extensionless relative imports resolve to .ts files.
registerHooks({
  resolve(specifier, context, nextResolve) {
    try {
      return nextResolve(specifier, context);
    } catch (error) {
      if (/^\.\.?\//.test(specifier) && !/\.[cm]?[jt]s$/.test(specifier)) {
        return nextResolve(`${specifier}.ts`, context);
      }
      throw error;
    }
  },
});

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
/** A state's name and every ring of its shape, islands and all. @typedef {{ name: string, rings: Line[] }} StateShape */
/**
 * A state's name, where it goes and how large it fits there (stateNames),
 * and where it is clear of the city names only at the small size, the zoom
 * its usual size is from.
 * @typedef {{ name: string, label: string, lon: number, lat: number, fit: number, usualFrom?: number }} StateName
 */
/** The outline is every ring of the land, as lines. @typedef {{ land: Polygon[], outline: Line[], state: Line[], shapes: StateShape[] }} Kinds */
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
/**
 * The national view's own lines, drawn below SIMPLE_LINES_UNTIL (style.ts)
 * and in the still: simplified so the coast reads as one hairline at zoom 3
 * to 5, where a pixel spans 5 to 20 km, and without the islands smaller than
 * SIMPLE_ISLAND_KM2 (the San Juans, the Keys, Maine's), which at that scale
 * draw as specks and knots. Shared borders are one arc, as in the lines drawn
 * closer in.
 */
const SIMPLE_METERS = 6000;
const SIMPLE_ISLAND_KM2 = 50;
/**
 * The states' shapes a phone names the states in view by, closer in than the
 * national view (src/map/basemap/state-areas.ts): 1 km, a few pixels at the
 * metro zoom they are named up to, well inside the room a name keeps from its
 * state's edge; on a grid of AREA_PRECISION degrees.
 */
const AREA_METERS = 1000;
const AREA_PRECISION = 0.005;
/** Budget for them: loaded after the map is up, on a phone, only where they are needed. */
const MAX_AREA_GZIP_BYTES = 48 * 1024;
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

/** Back from world units to degrees. @param {number} x */
const lngFromX = (x) => x * 360 - 180;
/** @param {number} y */
const latFromY = (y) =>
  (360 / Math.PI) * Math.atan(Math.exp(((180 - y * 360) * Math.PI) / 180)) - 90;
/** MapLibre's tiles are 512 px: the world is 512 * 2^zoom px wide. */
const TILE_PIXELS = 512;

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
 * Each state's name by its FIPS code, as the Census names it in the source.
 * @param {string} topology the source TopoJSON's text
 * @returns {Map<string, string>}
 */
function stateNamesByFips(topology) {
  const parsed = /** @type {{ objects?: { states?: { geometries?: unknown } } }} */ (
    JSON.parse(topology)
  );
  const geometries = parsed.objects?.states?.geometries;
  if (!Array.isArray(geometries)) throw new Error('build-geo: the source has no states');
  /** @type {Map<string, string>} */
  const names = new Map();
  for (const geometry of geometries) {
    const { id, properties } = /** @type {{ id?: unknown, properties?: { name?: unknown } }} */ (
      geometry
    );
    if (typeof id === 'string' && typeof properties?.name === 'string') {
      names.set(id, properties.name);
    }
  }
  return names;
}

/**
 * State names, set as the map sets them (style.ts reads these from
 * us-geo.ts): Geist Medium capitals STATE_NAME_TRACKING ems apart, lines
 * STATE_NAME_LEADING ems apart, STATE_NAME_SIZE.from px high at zoom
 * STATE_NAME_SIZE.fromZoom growing to STATE_NAME_SIZE.to at its toZoom.
 */
const STATE_NAME_TRACKING = 0.14;
const STATE_NAME_LEADING = 1.2;
const STATE_NAME_SIZE = Object.freeze({ fromZoom: 3, from: 9.25, toZoom: 6, to: 10.75 });
/**
 * The share of that size a state's name is set at where only that fits
 * inside its state (state-names.ts STATE_NAME_SMALL).
 */
const STATE_NAME_SMALL = 0.85;
/**
 * Geist Medium's advance widths, in ems, as Chromium measures them. A line's
 * width is its letters' advances and the spaces between them (MapLibre does
 * not kern); a character not listed counts as GEIST_WIDEST.
 * @type {Readonly<Record<string, number>>}
 */
const GEIST_MEDIUM_EMS = Object.freeze({
  A: 0.689,
  B: 0.688,
  C: 0.713,
  D: 0.701,
  E: 0.609,
  F: 0.595,
  G: 0.713,
  H: 0.716,
  I: 0.28,
  J: 0.607,
  K: 0.656,
  L: 0.583,
  M: 0.89,
  N: 0.745,
  O: 0.751,
  P: 0.657,
  Q: 0.745,
  R: 0.68,
  S: 0.654,
  T: 0.568,
  U: 0.694,
  V: 0.688,
  W: 0.968,
  X: 0.633,
  Y: 0.594,
  Z: 0.561,
  a: 0.565,
  b: 0.608,
  c: 0.563,
  d: 0.608,
  e: 0.576,
  f: 0.412,
  g: 0.607,
  h: 0.591,
  i: 0.256,
  j: 0.284,
  k: 0.609,
  l: 0.282,
  m: 0.885,
  n: 0.591,
  o: 0.588,
  p: 0.608,
  q: 0.608,
  r: 0.394,
  s: 0.537,
  t: 0.41,
  u: 0.586,
  v: 0.56,
  w: 0.829,
  x: 0.607,
  y: 0.553,
  z: 0.552,
  ' ': 0.243,
  '.': 0.213,
  '-': 0.418,
  "'": 0.186,
});
const GEIST_WIDEST = 0.97;
/** Clear space a state's name keeps from its state's lines, in ems of its size: across, then down. */
const STATE_NAME_MARGIN = [0.5, 0.35];
/**
 * The city names a state's name keeps clear of: the `cities` largest, the
 * ones the map shows from the zoom phones open at, as style.ts sets them on
 * a phone (the only screen that names the states): their size, spacing and
 * clear space, and the state name's own clear space. Its tests check these
 * against the style. A name is placed clear of them at the zoom it is first
 * shown at (stateNames).
 */
const STATE_NAMES_CLEAR_OF = Object.freeze({
  zoom: 3.8,
  cities: 34,
  size: Object.freeze({ fromZoom: 3, from: 10.5, toZoom: 6, to: 12 }),
  tracking: 0.02,
  padding: 8,
  ownPadding: 3,
});
/** Points tried across and down each state, before the best of them is looked at closer. */
const STATE_NAME_GRID = 56;
/** Points no worse than this share of the best one are as good: the name goes at their middle. */
const STATE_NAME_PLATEAU = 0.96;

/**
 * A line's width in ems, set with `tracking` ems between letters.
 * @param {string} line
 * @param {number} tracking
 */
function lineWidth(line, tracking) {
  const letters = [...line];
  const advances = letters.reduce(
    (sum, letter) => sum + (GEIST_MEDIUM_EMS[letter] ?? GEIST_WIDEST),
    0,
  );
  return advances + Math.max(0, letters.length - 1) * tracking;
}

/**
 * A name's size in CSS pixels at `zoom`, as the map sets it: `from` at
 * `fromZoom`, growing to `to` at `toZoom`.
 * @param {{ fromZoom: number, from: number, toZoom: number, to: number }} size
 * @param {number} zoom
 */
function sizeAt({ fromZoom, from, toZoom, to }, zoom) {
  return from + (to - from) * Math.min(1, Math.max(0, (zoom - fromZoom) / (toZoom - fromZoom)));
}

/** The street map takes over from the bundled lines and names at this zoom (style.ts). */
const STATE_NAMES_UNTIL = 7;

/**
 * The zoom a state name of `fit` first fits at: where its size, growing
 * slower than the map, is fit * 2^zoom.
 * @param {number} fit
 */
function zoomOfFit(fit) {
  const known = fitZooms.get(fit);
  if (known !== undefined) return known;
  let [low, high] = [-4, 24];
  while (high - low > 1e-6) {
    const middle = (low + high) / 2;
    if (sizeAt(STATE_NAME_SIZE, middle) > fit * 2 ** middle) low = middle;
    else high = middle;
  }
  fitZooms.set(fit, high);
  return high;
}
/** zoomOfFit's answers, by fit: it is asked the same few again and again. @type {Map<number, number>} */
const fitZooms = new Map();

/**
 * The ways a name can be set: on one line, and for a name of more than one
 * word, on two, broken at the space that leaves the shorter longest line.
 * @param {string} name
 * @returns {{ label: string, width: number, height: number }[]}
 */
function nameLayouts(name) {
  /** @param {string} line */
  const width = (line) => lineWidth(line.toUpperCase(), STATE_NAME_TRACKING);
  const layouts = [{ label: name, width: width(name), height: STATE_NAME_LEADING }];
  const words = name.split(' ');
  /** @type {{ label: string, width: number, height: number } | undefined} */
  let two;
  for (let i = 1; i < words.length; i++) {
    const first = words.slice(0, i).join(' ');
    const second = words.slice(i).join(' ');
    const longest = Math.max(width(first), width(second));
    if (two === undefined || longest < two.width) {
      two = { label: `${first}\n${second}`, width: longest, height: 2 * STATE_NAME_LEADING };
    }
  }
  if (two !== undefined) layouts.push(two);
  return layouts;
}

/**
 * The distance from (px, py) to the segment from (ax, ay) to (bx, by) by the
 * larger of the two axes' distances: half the side of the largest square
 * centered on the point that the segment does not cross. The larger axis
 * distance along the segment is convex and piecewise linear, so its least
 * value is at an end or where an axis distance is zero or both are equal.
 * @param {number} px @param {number} py @param {number} ax @param {number} ay @param {number} bx @param {number} by
 */
function squareDistance(px, py, ax, ay, bx, by) {
  const ux = ax - px;
  const uy = ay - py;
  const vx = bx - ax;
  const vy = by - ay;
  /** @param {number} t */
  const at = (t) => Math.max(Math.abs(ux + t * vx), Math.abs(uy + t * vy));
  let least = Math.min(at(0), at(1));
  for (const t of [-ux / vx, -uy / vy, (uy - ux) / (vx - vy), -(ux + uy) / (vx + vy)]) {
    if (t > 0 && t < 1) least = Math.min(least, at(t));
  }
  return least;
}

/**
 * The national city names as style.ts sets them: Geist Medium, `size.from`
 * px at `size.fromZoom` growing to `size.to` at `size.toZoom`, `tracking` ems
 * between letters, with a `halo` px wide. Its tests check these against the
 * style.
 */
const CITY_NAME_SET = Object.freeze({
  size: Object.freeze({ fromZoom: 3, from: 10.5, toZoom: 6, to: 12 }),
  tracking: 0.02,
  halo: 1,
  // Clear space around each name, as a laptop or tablet sets it (a phone's is less).
  padding: 12,
});
/**
 * The zooms a name set off its point is kept from running into the largest
 * cities' names at (as many as STATE_NAMES_CLEAR_OF.cities): from a tablet's
 * national view in, across the national view.
 */
const CITY_NAMES_APART_ZOOMS = Object.freeze([3, 3.5, 3.8, 4, 4.5, 5]);
/**
 * How many of the largest cities the map names from each zoom, as style.ts
 * CITY_NAME_BANDS names them: every band, the last naming the rest.
 */
const CITY_NAMES_SHOWN = Object.freeze([
  Object.freeze({ zoom: 3, names: 14 }),
  Object.freeze({ zoom: 3.3, names: 21 }),
  Object.freeze({ zoom: 3.8, names: 34 }),
  Object.freeze({ zoom: 4.3, names: 54 }),
  Object.freeze({ zoom: 4.8, names: 85 }),
  Object.freeze({ zoom: 5.3, names: 134 }),
  Object.freeze({ zoom: 5.8, names: 212 }),
  Object.freeze({ zoom: 6.3, names: Infinity }),
]);
/** Half a city name's height, in ems: its letters' reach above and below their middle. */
const CITY_NAME_HALF_HEIGHT = 0.45;
/** Pixels a city name keeps clear of a line, beyond its halo. */
const CITY_NAME_CLEAR = 2;
/**
 * The zooms a city name is checked against the lines at, from the one the
 * map first names it at: every screen's national view (a tablet's from about
 * 3, a phone's about 3.85, a laptop's about 4, the widest screens' below
 * HOME_VIEWS_UNTIL) and on to the handover to the street map's names, below
 * SIMPLE_LINES_UNTIL against the simplified lines and from it against the
 * detailed ones, as each is drawn there. The national views, the map as most
 * see it, count twice.
 */
const CITY_NAME_ZOOMS = Object.freeze([
  3, 3.3, 3.5, 3.85, 4, 4.25, 4.5, 4.75, 5, 5.25, 5.5, 5.75, 6, 6.25, 6.5, 6.75,
]);
const HOME_VIEWS_UNTIL = 5;
/**
 * What a line under a name costs, at each zoom: the outline (a coast or the
 * border, the brightest line) OUTLINE_COST a segment, a state line, a step
 * dimmer, STATE_LINE_COST. Moving the name costs MOVE_COST an em, so a name
 * stays on its point unless moving it takes a line out from under it.
 */
const OUTLINE_COST = 3;
const STATE_LINE_COST = 1;
const MOVE_COST = 0.25;
/**
 * How far a name may go from its point, in ems: it still marks its city, the
 * point never more than ANCHOR_EMS beyond the end of the name, nor more than
 * CITY_NAME_MOST_RISE above or below its middle. Offsets are tried every
 * OFFSET_STEP ems.
 */
const ANCHOR_EMS = 0.5;
const CITY_NAME_MOST_RISE = 1.2;
const OFFSET_STEP = 0.2;
/**
 * A name may run out past the land over water, the sea's or a lake's, only on
 * the US side of the border with Canada and Mexico: each point of it off the
 * land nearer the outline than the border by BORDER_MARGIN_KM at least.
 */
const BORDER_MARGIN_KM = 10;
/**
 * What a name wholly out over the water costs, at each zoom: less than a
 * segment of the coast under it, more than a state line, so a name goes out
 * over the water beside its city only where the land has no clear place.
 */
const WATER_COST = 2;
/** What a name wholly past the border costs, at each zoom: more than any line under it. */
const ACROSS_COST = 12;
/** Below this zoom the map draws the simplified lines, from it the detailed (style.ts). */
const SIMPLE_LINES_UNTIL = 5.75;
/** The Earth's circumference at the equator, in km. */
const EQUATOR_KM = 40_075.017;

/**
 * A line segment's box test: whether the segment from (ax, ay) to (bx, by)
 * crosses the box from (x0, y0) to (x1, y1).
 * @param {number} ax @param {number} ay @param {number} bx @param {number} by
 * @param {number} x0 @param {number} y0 @param {number} x1 @param {number} y1
 */
function segmentCrossesBox(ax, ay, bx, by, x0, y0, x1, y1) {
  // Liang-Barsky: clip the segment to the box; it crosses when anything is left.
  let t0 = 0;
  let t1 = 1;
  const dx = bx - ax;
  const dy = by - ay;
  for (const [p, q] of [
    [-dx, ax - x0],
    [dx, x1 - ax],
    [-dy, ay - y0],
    [dy, y1 - ay],
  ]) {
    const pp = p ?? 0;
    const qq = q ?? 0;
    if (pp === 0) {
      if (qq < 0) return false;
    } else {
      const t = qq / pp;
      if (pp < 0) t0 = Math.max(t0, t);
      else t1 = Math.min(t1, t);
      if (t0 > t1) return false;
    }
  }
  return true;
}

/**
 * Whether the segments from (ax, ay) to (bx, by) and from (cx, cy) to (dx, dy) cross.
 * @param {number} ax @param {number} ay @param {number} bx @param {number} by
 * @param {number} cx @param {number} cy @param {number} dx @param {number} dy
 */
function segmentsCross(ax, ay, bx, by, cx, cy, dx, dy) {
  const side = (
    /** @type {number} */ px,
    /** @type {number} */ py,
    /** @type {number} */ qx,
    /** @type {number} */ qy,
    /** @type {number} */ rx,
    /** @type {number} */ ry,
  ) => Math.sign((qx - px) * (ry - py) - (qy - py) * (rx - px));
  return (
    side(ax, ay, bx, by, cx, cy) * side(ax, ay, bx, by, dx, dy) < 0 &&
    side(cx, cy, dx, dy, ax, ay) * side(cx, cy, dx, dy, bx, by) < 0
  );
}

/**
 * The distance from (px, py) to the segment from (ax, ay) to (bx, by).
 * @param {number} px @param {number} py @param {number} ax @param {number} ay @param {number} bx @param {number} by
 */
function segmentDistance(px, py, ax, ay, bx, by) {
  const vx = bx - ax;
  const vy = by - ay;
  const length = vx * vx + vy * vy;
  const t = length === 0 ? 0 : Math.min(1, Math.max(0, ((px - ax) * vx + (py - ay) * vy) / length));
  return Math.hypot(ax + t * vx - px, ay + t * vy - py);
}

/**
 * Lines as flat [x0, y0, x1, y1, ...] segments in world units (Web Mercator, 0 to 1).
 * @param {readonly Line[]} lines
 */
function segmentsOf(lines) {
  /** @type {number[]} */
  const segments = [];
  for (const line of lines) {
    for (let i = 1; i < line.length; i++) {
      const [lngA = NaN, latA = NaN] = line[i - 1] ?? [];
      const [lngB = NaN, latB = NaN] = line[i] ?? [];
      segments.push(mercatorX(lngA), mercatorY(latA), mercatorX(lngB), mercatorY(latB));
    }
  }
  return segments;
}

/**
 * Whether (x, y) is inside the rings whose segments are `segments`: whether
 * an odd number of them cross the ray east of it. In world units, where the
 * map draws each segment straight.
 * @param {readonly number[]} segments @param {number} x @param {number} y
 */
function insideSegments(segments, x, y) {
  let within = false;
  for (let i = 0; i < segments.length; i += 4) {
    const ax = segments[i] ?? NaN;
    const ay = segments[i + 1] ?? NaN;
    const bx = segments[i + 2] ?? NaN;
    const by = segments[i + 3] ?? NaN;
    if (ay < y === by < y) continue;
    if (x < ax + ((y - ay) / (by - ay)) * (bx - ax)) within = !within;
  }
  return within;
}

/**
 * The segments of `segments` with a point within `reach` of (x, y), by box.
 * @param {readonly number[]} segments @param {number} x @param {number} y @param {number} reach
 */
function segmentsNear(segments, x, y, reach) {
  /** @type {number[]} */
  const kept = [];
  for (let i = 0; i < segments.length; i += 4) {
    const ax = segments[i] ?? NaN;
    const ay = segments[i + 1] ?? NaN;
    const bx = segments[i + 2] ?? NaN;
    const by = segments[i + 3] ?? NaN;
    if (Math.max(ax, bx) < x - reach || Math.min(ax, bx) > x + reach) continue;
    if (Math.max(ay, by) < y - reach || Math.min(ay, by) > y + reach) continue;
    kept.push(ax, ay, bx, by);
  }
  return kept;
}

/**
 * The border with Canada and Mexico on land and inland water, as the US mask
 * draws it (src/map/basemap/mask/format.ts BORDER_LAYER), read from the
 * committed mask archive at its first zoom: flat segments in world units.
 * @returns {Promise<number[]>}
 */
async function readBorder() {
  const { US_MASK_FILE } = await import('../src/map/basemap/us-mask.ts');
  const { ArchiveReader } = await import('../src/map/basemap/mask/pmtiles.ts');
  const { maskFromTile } = await import('../src/map/basemap/mask/source.ts');
  const { MASK_MIN_ZOOM } = await import('../src/map/basemap/mask/format.ts');
  const { EXTENT } = await import('../src/map/basemap/mask/mvt.ts');
  const bytes = new Uint8Array(await readFile(join(WEB, 'public', US_MASK_FILE)));
  const archive = new ArchiveReader(
    (offset, length) => Promise.resolve(bytes.subarray(offset, offset + length)),
    (zipped) => Promise.resolve(new Uint8Array(gunzipSync(zipped))),
  );
  const tiles = 2 ** MASK_MIN_ZOOM;
  // The continental US, and a tile to spare each way.
  const [x0, x1] = [mercatorX(-126), mercatorX(-66)].map((x) => Math.floor(x * tiles));
  const [y0, y1] = [mercatorY(50), mercatorY(24)].map((y) => Math.floor(y * tiles));
  /** @type {number[]} */
  const segments = [];
  for (let x = x0 ?? 0; x <= (x1 ?? -1); x++) {
    for (let y = y0 ?? 0; y <= (y1 ?? -1); y++) {
      const tile = await archive.tile(MASK_MIN_ZOOM, x, y);
      if (tile === null) continue;
      for (const part of maskFromTile(tile).border) {
        for (let i = 2; i + 1 < part.length; i += 2) {
          segments.push(
            (x + (part[i - 2] ?? NaN) / EXTENT) / tiles,
            (y + (part[i - 1] ?? NaN) / EXTENT) / tiles,
            (x + (part[i] ?? NaN) / EXTENT) / tiles,
            (y + (part[i + 1] ?? NaN) / EXTENT) / tiles,
          );
        }
      }
    }
  }
  if (segments.length === 0) throw new Error('build-geo: the US mask has no border');
  return segments;
}

/**
 * Where each national city name goes, in ems of its size from its city's
 * point: on the point, unless a line runs under it there at some zoom it is
 * named at (CITY_NAME_ZOOMS, each line as drawn there), and then the place
 * near the point where the lines under it cost least: the outline (a coast or
 * the border) OUTLINE_COST a segment, a state line STATE_LINE_COST, and
 * moving MOVE_COST an em. Seattle on the Sound, Los Angeles on the shore,
 * El Paso on the border, New York among its rivers and Miami on its narrow
 * shore: each name is set off the line work, over the land or out over the
 * water beside it, never across the border (BORDER_MARGIN_KM), and never
 * moved into a state's name, or further into one, as a phone sets them (New
 * York's toward Pennsylvania's), nor into one of the largest cities' names or
 * further into one (Houston's toward Dallas's), where MapLibre would leave
 * one out. Where no place near the point is clear, the name takes the one
 * with the least under it, parted from it by its halo.
 * @param {readonly City[]} cities
 * @param {Kinds} detailed the lines drawn closer in, and the states' shapes
 * @param {Kinds} simple the lines drawn at the national view
 * @param {readonly StateName[]} stateNamesPlaced the state names, placed with every city name on its point
 * @param {readonly number[]} border the border with Canada and Mexico (readBorder)
 * @returns {[number, number][]} in the cities' order
 */
function cityOffsets(cities, detailed, simple, stateNamesPlaced, border) {
  const lines = {
    simple: { outline: segmentsOf(simple.outline), state: segmentsOf(simple.state) },
    detailed: { outline: segmentsOf(detailed.outline), state: segmentsOf(detailed.state) },
  };
  // The largest cities' names, the ones a name set off its point must not run into.
  const largest = cities.slice(0, STATE_NAMES_CLEAR_OF.cities).map((other) => ({
    x: mercatorX(other.lon),
    y: mercatorY(other.lat),
    half: lineWidth(other.name, CITY_NAME_SET.tracking) / 2,
  }));
  // The state names as placed: where, how wide, on how many lines, and from which zooms they
  // are named at their usual size and at the small one.
  const stateLabels = stateNamesPlaced.map((state) => {
    const labelLines = state.label.split('\n');
    return {
      name: state.name,
      x: mercatorX(state.lon),
      y: mercatorY(state.lat),
      width: Math.max(
        ...labelLines.map((line) => lineWidth(line.toUpperCase(), STATE_NAME_TRACKING)),
      ),
      lines: labelLines.length,
      usualFrom: Math.max(zoomOfFit(state.fit), state.usualFrom ?? -Infinity),
      smallFrom: zoomOfFit(state.fit / STATE_NAME_SMALL),
    };
  });
  /** @type {[number, number][]} */
  const placed = [];
  for (const [rank, city] of cities.entries()) placed.push(cityOffset(rank, city));
  return placed;

  /**
   * @param {number} rank
   * @param {City} city
   * @returns {[number, number]}
   */
  function cityOffset(rank, city) {
    const cx = mercatorX(city.lon);
    const cy = mercatorY(city.lat);
    const width = lineWidth(city.name, CITY_NAME_SET.tracking);
    const half = width / 2;
    const firstNamed = CITY_NAMES_SHOWN.find((band) => rank < band.names)?.zoom ?? Infinity;
    const zooms = CITY_NAME_ZOOMS.filter((zoom) => zoom >= firstNamed - 1e-9);
    if (zooms.length === 0) return [0, 0];
    // Whether the city's point is on the land as each set of lines draws it: a shore city's
    // point can be off the simplified coast.
    const pointOnLand = {
      simple: insideSegments(lines.simple.outline, cx, cy),
      detailed: insideSegments(lines.detailed.outline, cx, cy),
    };
    // BORDER_MARGIN_KM in world units at the city's latitude.
    const margin = BORDER_MARGIN_KM / (EQUATOR_KM * Math.cos((city.lat * Math.PI) / 180));
    // Each zoom's scale, the name's size and half its box (halo and clear space in), and the
    // lines drawn there as far as any name set near the point reaches.
    const levels = zooms.map((zoom) => {
      const scale = TILE_PIXELS * 2 ** zoom;
      const size = sizeAt(CITY_NAME_SET.size, zoom);
      const set = zoom < SIMPLE_LINES_UNTIL ? 'simple' : 'detailed';
      const reach = ((2 * half + ANCHOR_EMS + CITY_NAME_MOST_RISE) * size + 8) / scale;
      return {
        scale,
        size,
        set,
        weight: zoom < HOME_VIEWS_UNTIL ? 4 : 1,
        hw: (half * size + CITY_NAME_SET.halo + CITY_NAME_CLEAR) / scale,
        hh: (CITY_NAME_HALF_HEIGHT * size + CITY_NAME_SET.halo + CITY_NAME_CLEAR) / scale,
        outline: segmentsNear(lines[set].outline, cx, cy, reach),
        state: segmentsNear(lines[set].state, cx, cy, reach),
        border: segmentsNear(border, cx, cy, reach + 2 * margin),
      };
    });
    const weights = levels.reduce((sum, { weight }) => sum + weight, 0);
    /** What the lines under the name at `offset` cost, on average over its zooms. */
    const lineCost = (/** @type {[number, number]} */ [ox, oy]) => {
      let cost = 0;
      for (const { scale, size, weight, hw, hh, outline, state } of levels) {
        const x = cx + (ox * size) / scale;
        const y = cy + (oy * size) / scale;
        for (const [segments, each] of /** @type {const} */ ([
          [outline, OUTLINE_COST],
          [state, STATE_LINE_COST],
        ])) {
          for (let i = 0; i < segments.length; i += 4) {
            if (
              segmentCrossesBox(
                segments[i] ?? NaN,
                segments[i + 1] ?? NaN,
                segments[i + 2] ?? NaN,
                segments[i + 3] ?? NaN,
                x - hw,
                y - hh,
                x + hw,
                y + hh,
              )
            ) {
              cost += each * weight;
            }
          }
        }
      }
      return cost / weights;
    };
    /**
     * What the name at `offset` costs off the land, on average over its zooms: WATER_COST
     * for a name wholly out over the water, ACROSS_COST for one wholly past the border, over
     * Canada or Mexico or their water. A point of it is off the land where the line from it
     * to the city's point crosses the outline an odd number of times from a point on the
     * land (an even number from one off it), and past the border where it is no nearer the
     * outline than the border by the margin.
     * @param {[number, number]} offset
     */
    const offLand = ([ox, oy]) => {
      let cost = 0;
      for (const { scale, size, set, weight, hw, hh, outline, border: nearBorder } of levels) {
        const x = cx + (ox * size) / scale;
        const y = cy + (oy * size) / scale;
        const step = (0.5 * size) / scale;
        let points = 0;
        let over = 0;
        let across = 0;
        for (let px = x - hw; px < x + hw + step / 2; px += step) {
          for (const py of [y - hh, y, y + hh]) {
            const qx = Math.min(px, x + hw);
            points++;
            let crossings = 0;
            for (let i = 0; i < outline.length; i += 4) {
              if (
                segmentsCross(
                  qx,
                  py,
                  cx,
                  cy,
                  outline[i] ?? NaN,
                  outline[i + 1] ?? NaN,
                  outline[i + 2] ?? NaN,
                  outline[i + 3] ?? NaN,
                )
              ) {
                crossings++;
              }
            }
            if ((crossings % 2 === 0) === pointOnLand[set]) continue;
            let toOutline = Infinity;
            let toBorder = Infinity;
            if (nearBorder.length > 0) {
              for (let i = 0; i < outline.length; i += 4) {
                toOutline = Math.min(
                  toOutline,
                  segmentDistance(
                    qx,
                    py,
                    outline[i] ?? NaN,
                    outline[i + 1] ?? NaN,
                    outline[i + 2] ?? NaN,
                    outline[i + 3] ?? NaN,
                  ),
                );
              }
              for (let i = 0; i < nearBorder.length; i += 4) {
                toBorder = Math.min(
                  toBorder,
                  segmentDistance(
                    qx,
                    py,
                    nearBorder[i] ?? NaN,
                    nearBorder[i + 1] ?? NaN,
                    nearBorder[i + 2] ?? NaN,
                    nearBorder[i + 3] ?? NaN,
                  ),
                );
              }
            }
            if (toBorder !== Infinity && toBorder <= toOutline + margin) across++;
            else over++;
          }
        }
        cost += (weight * (WATER_COST * over + ACROSS_COST * across)) / points;
      }
      return cost / weights;
    };
    /**
     * How far the name at `offset` runs into each state name, at the zoom phones open at and
     * the national views closer in (to HOME_VIEWS_UNTIL), as a phone sets them
     * (STATE_NAMES_CLEAR_OF): each where it is placed and at the size it is named at there,
     * with both names' clear space. Keyed by name and zoom; the pixels the two would have to
     * part by, for each it runs into.
     * @param {[number, number]} offset
     */
    const stateNamesHit = ([ox, oy]) => {
      /** @type {Map<string, number>} */
      const hit = new Map();
      for (const zoom of [STATE_NAMES_CLEAR_OF.zoom, ...zooms]) {
        // A phone's national views, from the zoom it opens at: where the state names matter.
        if (zoom < firstNamed - 1e-9 || zoom < STATE_NAMES_CLEAR_OF.zoom) continue;
        if (zoom >= HOME_VIEWS_UNTIL) continue;
        const scale = TILE_PIXELS * 2 ** zoom;
        const size = sizeAt(CITY_NAME_SET.size, zoom);
        const x = cx + (ox * size) / scale;
        const y = cy + (oy * size) / scale;
        const halfWidth = half * size + STATE_NAMES_CLEAR_OF.padding;
        const halfHeight = (STATE_NAME_LEADING * size) / 2 + STATE_NAMES_CLEAR_OF.padding;
        for (const state of stateLabels) {
          // Named at this zoom at its usual size, or at the small one, or not at all.
          const own = state.usualFrom <= zoom ? 1 : STATE_NAME_SMALL;
          if (own !== 1 && state.smallFrom > zoom) continue;
          const stateSize = own * sizeAt(STATE_NAME_SIZE, zoom);
          const dx = Math.abs(state.x - x) * scale;
          const dy = Math.abs(state.y - y) * scale;
          const reachX =
            halfWidth + (state.width * stateSize) / 2 + STATE_NAMES_CLEAR_OF.ownPadding;
          const reachY =
            halfHeight +
            (state.lines * STATE_NAME_LEADING * stateSize) / 2 +
            STATE_NAMES_CLEAR_OF.ownPadding;
          const into = Math.min(reachX - dx, reachY - dy);
          if (into > 0) hit.set(`${state.name} at ${String(zoom)}`, into);
        }
      }
      return hit;
    };
    /**
     * The largest cities' names MapLibre shows at `zoom` (CITY_NAMES_SHOWN), this one's on its
     * point: each where it goes (a larger city's as set off already, a smaller one's on its
     * point), placed in rank order, each left out where it would meet one placed before it. A
     * name hidden already, as Long Beach's by Los Angeles', is no name to keep clear of.
     * @param {number} zoom
     */
    const shownAt = (zoom) => {
      const scale = TILE_PIXELS * 2 ** zoom;
      const size = sizeAt(CITY_NAME_SET.size, zoom);
      const count = CITY_NAMES_SHOWN.filter((band) => band.zoom <= zoom).at(-1)?.names ?? 0;
      /** @type {{ other: number, x: number, y: number, half: number }[]} */
      const shown = [];
      for (const [other, name] of largest.slice(0, count).entries()) {
        const [px = 0, py = 0] = other < rank ? (placed[other] ?? [0, 0]) : [0, 0];
        const x = name.x * scale + px * size;
        const y = name.y * scale + py * size;
        const meets = shown.some(
          (before) =>
            Math.abs(before.x - x) < (before.half + name.half) * size + 2 * CITY_NAME_SET.padding &&
            Math.abs(before.y - y) < STATE_NAME_LEADING * size + 2 * CITY_NAME_SET.padding,
        );
        if (!meets) shown.push({ other, x, y, half: name.half });
      }
      return shown.filter(({ other }) => other !== rank);
    };
    // At the zooms the map names this city at.
    const shownNames = CITY_NAMES_APART_ZOOMS.filter((zoom) => zoom >= firstNamed - 1e-9).map(
      (zoom) => ({ zoom, shown: shownAt(zoom) }),
    );
    /**
     * How far the name at `offset` runs into each of those names, at each zoom checked, with
     * both names' clear space. Keyed by city and zoom.
     * @param {[number, number]} offset
     */
    const cityNamesHit = ([ox, oy]) => {
      /** @type {Map<string, number>} */
      const hit = new Map();
      for (const { zoom, shown } of shownNames) {
        const scale = TILE_PIXELS * 2 ** zoom;
        const size = sizeAt(CITY_NAME_SET.size, zoom);
        const x = cx * scale + ox * size;
        const y = cy * scale + oy * size;
        for (const name of shown) {
          const reachX = (half + name.half) * size + 2 * CITY_NAME_SET.padding;
          const reachY = STATE_NAME_LEADING * size + 2 * CITY_NAME_SET.padding;
          const into = Math.min(reachX - Math.abs(name.x - x), reachY - Math.abs(name.y - y));
          if (into > 0) hit.set(`${String(name.other)} at ${String(zoom)}`, into);
        }
      }
      return hit;
    };
    const cityHitOnPoint = cityNamesHit([0, 0]);
    /**
     * Whether the name at `offset` runs further into a larger or smaller city's name, at some
     * zoom, than on its point: MapLibre would then leave one of the two out.
     * @param {[number, number]} offset
     */
    const intoCityName = (offset) =>
      [...cityNamesHit(offset)].some(([key, into]) => into > (cityHitOnPoint.get(key) ?? 0));
    const hitOnPoint = stateNamesHit([0, 0]);
    /**
     * Whether the name at `offset` runs further into a state name, at some zoom, than it does
     * on its point: into one it clears there, or deeper into one it already meets.
     * @param {[number, number]} offset
     */
    const intoStateName = (offset) =>
      [...stateNamesHit(offset)].some(([key, into]) => into > (hitOnPoint.get(key) ?? 0));

    const onPoint = lineCost([0, 0]) + offLand([0, 0]);
    if (onPoint === 0) return [0, 0];
    // Every offset that keeps the name at its city, nearest first, so the search can stop
    // where moving alone costs more than the best found.
    /** @type {[number, number][]} */
    const candidates = [];
    const across = half + ANCHOR_EMS;
    for (let i = -Math.floor(across / OFFSET_STEP); i * OFFSET_STEP <= across + 1e-9; i++) {
      for (
        let j = -Math.round(CITY_NAME_MOST_RISE / OFFSET_STEP);
        j * OFFSET_STEP <= CITY_NAME_MOST_RISE + 1e-9;
        j++
      ) {
        if (i !== 0 || j !== 0) candidates.push([i * OFFSET_STEP, j * OFFSET_STEP]);
      }
    }
    candidates.sort(
      (a, b) => Math.hypot(a[0], a[1]) - Math.hypot(b[0], b[1]) || a[1] - b[1] || a[0] - b[0],
    );
    let clear = /** @type {[number, number] | undefined} */ (undefined);
    let best = onPoint;
    for (const candidate of candidates) {
      const moving = MOVE_COST * Math.hypot(candidate[0], candidate[1]);
      if (moving >= best) break;
      const lined = lineCost(candidate) + moving;
      if (lined >= best) continue;
      const score = lined + offLand(candidate);
      if (score >= best) continue;
      if (intoStateName(candidate) || intoCityName(candidate)) continue;
      best = score;
      clear = candidate;
    }
    const [ox = 0, oy = 0] = clear ?? [0, 0];
    return [Number(num(ox, 2)), Number(num(oy, 2))];
  }
}

/**
 * Where each state's name goes, and how large it can be set there.
 *
 * A name goes where the largest box of its shape (its lines of capitals and
 * the clear space around them) fits inside its state, crossing no state line
 * or shore, reckoned in Web Mercator as the map draws it, and where it keeps
 * clear of the city names shown from the zoom phones open at
 * (STATE_NAMES_CLEAR_OF), so both show. Among the points where that box is
 * near its largest, the name takes the middle one, so a square state is
 * named at its middle. A name of two or more words goes on two lines where
 * that lets it be set larger.
 *
 * `fit` is the largest size, in CSS pixels at zoom 0, the name can be set at
 * there; at zoom z it is fit * 2^z. The map names a state from the zoom its
 * name fits at (state-names.ts).
 * @param {readonly StateShape[]} shapes
 * @param {readonly City[]} cities in rank order
 * @param {readonly [number, number][]} offsets where each city's name goes from its point, in ems
 * @returns {StateName[]}
 */
function stateNames(shapes, cities, offsets) {
  const clear = STATE_NAMES_CLEAR_OF;
  const shown = cities.slice(0, clear.cities);
  return shapes.map(({ name, rings }) => {
    // The rings in world units, y growing southward, as flat [x0, y0, x1, y1, ...] segments.
    /** @type {number[]} */
    const segments = [];
    let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
    for (const ring of rings) {
      for (let i = 1; i < ring.length; i++) {
        const [lngA = NaN, latA = NaN] = ring[i - 1] ?? [];
        const [lngB = NaN, latB = NaN] = ring[i] ?? [];
        segments.push(mercatorX(lngA), mercatorY(latA), mercatorX(lngB), mercatorY(latB));
      }
      for (const [lng = NaN, lat = NaN] of ring) {
        x0 = Math.min(x0, mercatorX(lng));
        x1 = Math.max(x1, mercatorX(lng));
        y0 = Math.min(y0, mercatorY(lat));
        y1 = Math.max(y1, mercatorY(lat));
      }
    }
    /** Whether a point is inside the state: an odd number of its ring edges cross the ray east of it. */
    const inside = (/** @type {number} */ x, /** @type {number} */ y) => {
      let crossings = 0;
      for (let i = 0; i < segments.length; i += 4) {
        const ax = segments[i] ?? NaN;
        const ay = segments[i + 1] ?? NaN;
        const bx = segments[i + 2] ?? NaN;
        const by = segments[i + 3] ?? NaN;
        if (ay > y !== by > y && x < ax + ((y - ay) / (by - ay)) * (bx - ax)) crossings++;
      }
      return crossings % 2 === 1;
    };

    /** @type {StateName | undefined} */
    let best;
    for (const layout of nameLayouts(name)) {
      const boxWidth = layout.width + 2 * (STATE_NAME_MARGIN[0] ?? 0);
      const boxHeight = layout.height + 2 * (STATE_NAME_MARGIN[1] ?? 0);
      // Down is squeezed by the box's shape, so the box is a square to squareDistance.
      const squeeze = boxWidth / boxHeight;

      /**
       * Where the name's middle may not go with the city names as they are set
       * at `zoom`, the name set `own` times its usual size: so near a city
       * name that the two would meet.
       * @param {number} zoom
       * @param {number} own
       */
      const blockedAt = (zoom, own) => {
        const scale = TILE_PIXELS * 2 ** zoom;
        const citySize = sizeAt(clear.size, zoom);
        const ownSize = own * sizeAt(STATE_NAME_SIZE, zoom);
        const ownHalfWidth = ((layout.width * ownSize) / 2 + clear.ownPadding) / scale;
        const ownHalfHeight = ((layout.height * ownSize) / 2 + clear.ownPadding) / scale;
        return shown
          .map((city, rank) => {
            const [ox = 0, oy = 0] = offsets[rank] ?? [];
            const x = mercatorX(city.lon) + (ox * citySize) / scale;
            const y = mercatorY(city.lat) + (oy * citySize) / scale;
            const halfWidth =
              ((lineWidth(city.name, clear.tracking) * citySize) / 2 + clear.padding) / scale +
              ownHalfWidth;
            const halfHeight =
              ((STATE_NAME_LEADING * citySize) / 2 + clear.padding) / scale + ownHalfHeight;
            return { x0: x - halfWidth, x1: x + halfWidth, y0: y - halfHeight, y1: y + halfHeight };
          })
          .filter((box) => box.x1 > x0 && box.x0 < x1 && box.y1 > y0 && box.y0 < y1);
      };
      /**
       * Half the width of the largest box of this shape centered on a point, in world units,
       * with no city name in the way: worked out once a point, as each place() asks again.
       * @type {Map<string, number>}
       */
      const rooms = new Map();
      const openRoom = (/** @type {number} */ x, /** @type {number} */ y) => {
        const key = `${String(x)},${String(y)}`;
        const known = rooms.get(key);
        if (known !== undefined) return known;
        let least = 0;
        if (inside(x, y)) {
          least = Infinity;
          for (let i = 0; i < segments.length; i += 4) {
            const ax = segments[i] ?? NaN;
            const ay = (segments[i + 1] ?? NaN) * squeeze;
            const bx = segments[i + 2] ?? NaN;
            const by = (segments[i + 3] ?? NaN) * squeeze;
            least = Math.min(least, squareDistance(x, y * squeeze, ax, ay, bx, by));
          }
        }
        rooms.set(key, least);
        return least;
      };
      /** Whether a point is in any of `boxes`. @param {ReturnType<typeof blockedAt>} boxes */
      const blocks = (boxes, /** @type {number} */ x, /** @type {number} */ y) =>
        boxes.some((box) => x > box.x0 && x < box.x1 && y > box.y0 && y < box.y1);

      /**
       * Where the name fits largest, clear of the city names as they are set
       * at `zoom` (or of none, with null), the name set `own` times its usual
       * size: its place, and its fit there; null where no place is clear.
       * @param {number | null} zoom
       * @param {number} [own]
       */
      const place = (zoom, own = 1) => {
        const blocked = zoom === null ? [] : blockedAt(zoom, own);
        /** Half the width of the largest box of this shape centered on a point, in world units. */
        const room = (/** @type {number} */ x, /** @type {number} */ y) =>
          blocks(blocked, x, y) ? 0 : openRoom(x, y);
        /**
         * The points of a grid over a box, each with its room.
         * @param {number} left @param {number} top @param {number} right @param {number} bottom @param {number} steps
         */
        const grid = (left, top, right, bottom, steps) => {
          /** @type {{ x: number, y: number, room: number }[]} */
          const points = [];
          for (let i = 0; i <= steps; i++) {
            for (let j = 0; j <= steps; j++) {
              const x = left + ((right - left) * i) / steps;
              const y = top + ((bottom - top) * j) / steps;
              points.push({ x, y, room: room(x, y) });
            }
          }
          return points;
        };
        const coarse = grid(x0, y0, x1, y1, STATE_NAME_GRID);
        const peak = coarse.reduce((a, b) => (b.room > a.room ? b : a));
        if (!(peak.room > 0)) return null;
        // A closer look around the best point, a grid step either way.
        const stepX = (x1 - x0) / STATE_NAME_GRID;
        const stepY = (y1 - y0) / STATE_NAME_GRID;
        const fine = grid(peak.x - stepX, peak.y - stepY, peak.x + stepX, peak.y + stepY, 12);
        const points = [...coarse, ...fine];
        const most = Math.max(...points.map((point) => point.room));
        // The near-best points, and the one of them nearest their middle.
        const good = points.filter((point) => point.room >= STATE_NAME_PLATEAU * most);
        const midX = good.reduce((sum, point) => sum + point.x, 0) / good.length;
        const midY = good.reduce((sum, point) => sum + point.y, 0) / good.length;
        const chosen = good.reduce((a, b) =>
          Math.hypot(b.x - midX, b.y - midY) < Math.hypot(a.x - midX, a.y - midY) ? b : a,
        );
        // A name set s px high is s * boxWidth / 2 px wide either side: it fits while that is its room.
        return { x: chosen.x, y: chosen.y, fit: (2 * chosen.room * TILE_PIXELS) / boxWidth };
      };

      // Clear of the city names at the zoom it is first named at, or where phones open if that
      // is later: the first zoom from there at which a place clear of them fits the name.
      // Closer in, the city names cover less of the country, so a name fits sooner.
      // At its usual size, or else at the small size (STATE_NAME_SMALL), as the map names it.
      /** @param {number} zoom */
      const clearAt = (zoom) => {
        for (const own of [1, STATE_NAME_SMALL]) {
          const placed = place(zoom, own);
          if (placed !== null && zoomOfFit(placed.fit / own) <= zoom) return { ...placed, own };
        }
        return null;
      };
      let clearFrom = clear.zoom;
      let placed = clearAt(clearFrom);
      if (placed === null && clearAt(STATE_NAMES_UNTIL) !== null) {
        let [low, high] = [clear.zoom, STATE_NAMES_UNTIL];
        while (high - low > 0.01) {
          const middle = (low + high) / 2;
          if (clearAt(middle) === null) low = middle;
          else high = middle;
        }
        clearFrom = high;
        placed = clearAt(high);
      }
      // A name clear of them there only at the small size keeps to it until its usual size is
      // clear of them too, at a zoom closer in (or never, before the street map takes over).
      /** @type {number | undefined} */
      let usualFrom;
      if (placed !== null && placed.own !== 1) {
        const { x, y } = placed;
        const usualClear = (/** @type {number} */ zoom) => !blocks(blockedAt(zoom, 1), x, y);
        let [low, high] = [clearFrom, STATE_NAMES_UNTIL];
        if (usualClear(high)) {
          while (high - low > 0.001) {
            const middle = (low + high) / 2;
            if (usualClear(middle)) high = middle;
            else low = middle;
          }
        }
        // In hundredths, as the map reckons the zoom its usual size fits from (state-names.ts).
        const from = Math.ceil(high * 100) / 100;
        const fits = Math.ceil(zoomOfFit(Number(placed.fit.toPrecision(4))) * 100) / 100;
        if (from > fits) usualFrom = from;
      }
      // A name that fits nowhere clear of them before the street map takes over goes where it
      // fits largest, and shows where the city names leave it room.
      const spot = placed ?? place(null);
      if (spot === null) continue;
      if (best === undefined || spot.fit > best.fit) {
        best = {
          name,
          label: layout.label,
          lon: Number(num(round(lngFromX(spot.x)))),
          lat: Number(num(round(latFromY(spot.y)))),
          fit: Number(spot.fit.toPrecision(4)),
          ...(usualFrom === undefined ? {} : { usualFrom }),
        };
      }
    }
    if (best === undefined) throw new Error(`build-geo: no place for the name of ${name}`);
    return best;
  });
}

/**
 * Runs mapshaper on the TopoJSON and returns the land's polygons and the
 * lines grouped by kind: the outline (every ring of the land) and the state
 * lines. The land is the states dissolved after simplifying, so its rings
 * are exactly the national outline and meet the state lines. Simplified to
 * `meters`, without islands under `islandKm2` square kilometres.
 * @param {number} [meters]
 * @param {number} [islandKm2]
 * @returns {Promise<Kinds>}
 */
async function extractGeometry(meters = SIMPLIFY_METERS, islandKm2 = 0) {
  const topology = await readFile(SOURCE, 'utf8');
  const commands = [
    '-i states.json id-field=fips',
    '-target states',
    `-filter '!${JSON.stringify(EXCLUDED_FIPS)}.includes(fips)'`,
    `-each 'fips = fips === "${DC_FIPS}" ? "${MD_FIPS}" : fips'`,
    '-dissolve fips',
    // The national view's lines let small islands go as they simplify away; closer in, every
    // island keeps its shape.
    `-simplify ${islandKm2 > 0 ? 'weighted' : 'dp'} interval=${String(meters)}m${islandKm2 > 0 ? '' : ' keep-shapes'}`,
    ...(islandKm2 > 0 ? [`-filter-islands min-area=${String(islandKm2)}km2 remove-empty`] : []),
    // The whole country as one layer of polygons, from the simplified states.
    '-dissolve + name=land',
    // Each state's own shape, kept for its name (stateNames).
    '-filter true target=states + name=shapes',
    // Polygon rings become lines; TYPE is "inner" for shared state borders ("outer" is the land's edge).
    '-lines target=states',
    '-o target=states,land,shapes format=geojson',
  ].join(' ');
  const output = await mapshaper.applyCommands(commands, { 'states.json': topology });
  const lines = /** @type {{ features: LineFeature[] }} */ (parseOutput(output['states.json']));
  const land = /** @type {{ geometries: { type: string, coordinates: number[][][][] }[] }} */ (
    parseOutput(output['land.json'])
  );
  const shapes =
    /** @type {{ features: { properties: { fips: string }, geometry: { type: string, coordinates: number[][][] | number[][][][] } }[] }} */ (
      parseOutput(output['shapes.json'])
    );
  const names = stateNamesByFips(topology);

  /** @type {Kinds} */
  const kinds = { land: [], outline: [], state: [], shapes: [] };
  for (const { properties, geometry } of shapes.features) {
    const name = names.get(properties.fips);
    if (name === undefined) throw new Error(`build-geo: no name for state ${properties.fips}`);
    const polygons =
      geometry.type === 'Polygon'
        ? [/** @type {number[][][]} */ (geometry.coordinates)]
        : /** @type {number[][][][]} */ (geometry.coordinates);
    kinds.shapes.push({ name, rings: polygons.flatMap((polygon) => polygon.map(gridLine)) });
  }
  kinds.shapes.sort((a, b) => a.name.localeCompare(b.name));
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

/**
 * @param {Kinds} kinds
 * @param {Kinds} simple the national view's lines
 * @param {readonly City[]} cities
 * @param {readonly [number, number][]} offsets
 * @param {readonly StateName[]} states
 */
function geojsonText(kinds, simple, cities, offsets, states) {
  /** @param {Line} line */
  const coordinates = (line) =>
    `[${line.map(([lng, lat]) => `[${num(lng)},${num(lat)}]`).join(',')}]`;
  const state = `{"type":"Feature","properties":{"kind":"state"},"geometry":{"type":"MultiLineString","coordinates":[${kinds.state
    .map(coordinates)
    .join(',')}]}}`;
  const land = `{"type":"Feature","properties":{"kind":"land"},"geometry":{"type":"MultiPolygon","coordinates":[${kinds.land
    .map((polygon) => `[${polygon.map(coordinates).join(',')}]`)
    .join(',')}]}}`;
  // The national view's own land and lines, simplified.
  const simpleState = `{"type":"Feature","properties":{"kind":"state-simple"},"geometry":{"type":"MultiLineString","coordinates":[${simple.state
    .map(coordinates)
    .join(',')}]}}`;
  const simpleLand = `{"type":"Feature","properties":{"kind":"land-simple"},"geometry":{"type":"MultiPolygon","coordinates":[${simple.land
    .map((polygon) => `[${polygon.map(coordinates).join(',')}]`)
    .join(',')}]}}`;
  // Rank 0 is the largest city: MapLibre places the lowest rank first. A name set off its point
  // carries where it goes, in ems.
  const names = cities.map(({ name, lon, lat }, rank) => {
    const [ox = 0, oy = 0] = offsets[rank] ?? [];
    const offset = ox === 0 && oy === 0 ? '' : `,"offset":[${num(ox, 2)},${num(oy, 2)}]`;
    return `{"type":"Feature","properties":{"kind":"city","name":${JSON.stringify(name)},"rank":${String(rank)}${offset}},"geometry":{"type":"Point","coordinates":[${num(lon)},${num(lat)}]}}`;
  });
  // Each state's name where it fits best, and how large it fits there.
  const stateNameFeatures = states.map(
    ({ name, label, lon, lat, fit, usualFrom }) =>
      `{"type":"Feature","properties":{"kind":"state-name","name":${JSON.stringify(name)},"label":${JSON.stringify(label)},"fit":${String(fit)}${usualFrom === undefined ? '' : `,"usualFrom":${num(usualFrom, 2)}`}},"geometry":{"type":"Point","coordinates":[${num(lon)},${num(lat)}]}}`,
  );
  return `{"type":"FeatureCollection","features":[${[land, state, simpleLand, simpleState, ...names, ...stateNameFeatures].join(',')}]}\n`;
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
/**
 * The states' shapes as state-areas.ts reads them: for each state, its name
 * and its rings, each a flat list of longitude, latitude pairs on the
 * AREA_PRECISION grid, closed.
 * @param {readonly StateShape[]} shapes
 */
function areasText(shapes) {
  const scale = 1 / AREA_PRECISION;
  const states = shapes.map(({ name, rings }) => ({
    name,
    rings: rings
      .map((ring) => {
        /** @type {number[]} */
        const flat = [];
        for (const [lon, lat] of ring) {
          const x = Math.round(lon * scale) / scale;
          const y = Math.round(lat * scale) / scale;
          if (flat.at(-2) === x && flat.at(-1) === y) continue;
          flat.push(x, y);
        }
        return flat;
      })
      // A ring gone to a point or a line at this grid holds no room for a name.
      .filter((flat) => flat.length >= 8),
  }));
  return `${JSON.stringify({ states: states.filter((state) => state.rings.length > 0) })}\n`;
}

/**
 * The city and state names of the bundled GeoJSON alone, as a GeoJSON file of
 * their own.
 * @param {string} geojson
 */
function namesText(geojson) {
  /** @type {{ features: { properties: { kind: string } }[] }} */
  const { features } = JSON.parse(geojson);
  const names = features.filter(({ properties }) => NAME_KINDS.includes(properties.kind));
  return `${JSON.stringify({ type: 'FeatureCollection', features: names })}\n`;
}

/** The kinds of feature in the bundled GeoJSON that are names. */
const NAME_KINDS = ['city', 'state-name'];

function metaText({ bounds, file, namesFile, areasFile, viewBox, gzipBytes }) {
  return `// Generated by scripts/build-geo.mjs from us-atlas states-10m (Census Bureau
// cartographic state boundaries, 2017 edition). Do not edit by hand: run
// "npm run build:geo".

/** West, south, east, north of the bundled continental US lines, in degrees. */
export const US_BOUNDS = [${bounds.map((value) => num(value)).join(', ')}] as const;

/** The bundled GeoJSON, relative to the site base URL. */
export const US_LINES_FILE = '${file}';

/** Its city and state names alone, relative to the site base URL. */
export const US_NAMES_FILE = '${namesFile}';

/** The states' shapes a phone names the states in view by (state-areas.ts), relative to the site base URL. */
export const US_STATES_FILE = '${areasFile}';

/** viewBox of the inline still in index.html: Web Mercator, north-west corner at 0 0. */
export const STILL_VIEWBOX = '${viewBox}';

/** Gzipped size of the bundled GeoJSON, in bytes. */
export const US_LINES_GZIP_BYTES = ${String(gzipBytes)};

/**
 * How the state names in it are set, as their places and sizes were worked
 * out for: the space between letters and between lines, in ems of their size,
 * and their size in CSS pixels, \`from\` at \`fromZoom\` growing to \`to\` at \`toZoom\`.
 */
export const STATE_NAME_TRACKING = ${num(STATE_NAME_TRACKING)};
export const STATE_NAME_LEADING = ${num(STATE_NAME_LEADING)};
export const STATE_NAME_SIZE = {
  fromZoom: ${num(STATE_NAME_SIZE.fromZoom)},
  from: ${num(STATE_NAME_SIZE.from)},
  toZoom: ${num(STATE_NAME_SIZE.toZoom)},
  to: ${num(STATE_NAME_SIZE.to)},
} as const;

/** The share of that size a name is set at where only that fits inside its state. */
export const STATE_NAME_SMALL = ${num(STATE_NAME_SMALL, 2)};

/**
 * The city names each state's name was placed clear of, as a phone's map
 * sets them: the first \`cities\` of them, shown from \`zoom\`, \`size\` px high,
 * \`tracking\` ems apart, with \`padding\` px of clear space; and \`ownPadding\`
 * px around the state's name.
 */
export const STATE_NAMES_CLEAR_OF = {
  zoom: ${num(STATE_NAMES_CLEAR_OF.zoom)},
  cities: ${String(STATE_NAMES_CLEAR_OF.cities)},
  size: {
    fromZoom: ${num(STATE_NAMES_CLEAR_OF.size.fromZoom)},
    from: ${num(STATE_NAMES_CLEAR_OF.size.from)},
    toZoom: ${num(STATE_NAMES_CLEAR_OF.size.toZoom)},
    to: ${num(STATE_NAMES_CLEAR_OF.size.to)},
  },
  tracking: ${num(STATE_NAMES_CLEAR_OF.tracking)},
  padding: ${num(STATE_NAMES_CLEAR_OF.padding)},
  ownPadding: ${num(STATE_NAMES_CLEAR_OF.ownPadding)},
} as const;

/**
 * How the city names were set off the line work, as a map sets them: their
 * size, spacing, halo and clear space, the bands of names the map shows, the
 * zooms they were checked at, and the zoom below which the simplified lines
 * are drawn and from which the detailed ones.
 */
export const CITY_NAMES_SET_OFF = {
  size: {
    fromZoom: ${num(CITY_NAME_SET.size.fromZoom)},
    from: ${num(CITY_NAME_SET.size.from)},
    toZoom: ${num(CITY_NAME_SET.size.toZoom)},
    to: ${num(CITY_NAME_SET.size.to)},
  },
  tracking: ${num(CITY_NAME_SET.tracking)},
  halo: ${num(CITY_NAME_SET.halo)},
  padding: ${num(CITY_NAME_SET.padding)},
  shown: [${CITY_NAMES_SHOWN.map(({ zoom, names }) => `{ zoom: ${num(zoom)}, names: ${String(names)} }`).join(', ')}],
  zooms: [${CITY_NAME_ZOOMS.map((zoom) => num(zoom)).join(', ')}],
  simpleLinesUntil: ${num(SIMPLE_LINES_UNTIL)},
} as const;

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
  const simple = await extractGeometry(SIMPLE_METERS, SIMPLE_ISLAND_KM2);
  const areas = await format(
    areasText((await extractGeometry(AREA_METERS)).shapes),
    join(GEO_DIR, 'us-states.json'),
  );
  const areaGzipBytes = gzipSync(areas, { level: 9 }).length;
  if (areaGzipBytes > MAX_AREA_GZIP_BYTES) {
    throw new Error(
      `build-geo: the states' shapes are ${String(areaGzipBytes)} B gzipped, over the ${String(MAX_AREA_GZIP_BYTES)} B budget`,
    );
  }
  const areasFile = `us-states.${createHash('sha256').update(areas).digest('hex').slice(0, 10)}.json`;
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
  // The state names with every city name on its point; the city names set off the outline clear
  // of those; the state names placed again clear of the city names where they are set.
  const onPoints = cities.map(() => /** @type {[number, number]} */ ([0, 0]));
  const offsets = cityOffsets(
    cities,
    kinds,
    simple,
    stateNames(kinds.shapes, cities, onPoints),
    await readBorder(),
  );
  const states = stateNames(kinds.shapes, cities, offsets);
  const geojson = await format(
    geojsonText(kinds, simple, cities, offsets, states),
    join(GEO_DIR, 'us-lines.json'),
  );
  const gzipBytes = gzipSync(geojson, { level: 9 }).length;
  if (gzipBytes > MAX_GZIP_BYTES) {
    throw new Error(
      `build-geo: GeoJSON is ${String(gzipBytes)} B gzipped, over the ${String(MAX_GZIP_BYTES)} B budget`,
    );
  }
  const hash = createHash('sha256').update(geojson).digest('hex').slice(0, 10);
  const fileName = `us-lines.${hash}.json`;
  const names = await format(namesText(geojson), join(GEO_DIR, 'us-names.json'));
  const namesFile = `us-names.${createHash('sha256').update(names).digest('hex').slice(0, 10)}.json`;
  const points = [kinds.outline, kinds.state].reduce(
    (sum, lines) => sum + lines.reduce((n, line) => n + line.length, 0),
    0,
  );
  // The still is the national view: its own simplified lines, as the map draws them there.
  const { svg, viewBox } = stillSvg(simple, bounds);
  const meta = await format(
    metaText({
      bounds,
      file: `geo/${fileName}`,
      namesFile: `geo/${namesFile}`,
      areasFile: `geo/${areasFile}`,
      viewBox,
      gzipBytes,
    }),
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
    (name) => /^us-(lines|names|states)\.[0-9a-f]+\.json$/.test(name),
  );
  /** @type {[string, string][]} */
  const wanted = [
    [join(GEO_DIR, fileName), geojson],
    [join(GEO_DIR, namesFile), names],
    [join(GEO_DIR, areasFile), areas],
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
  const extra = existing
    .filter((name) => name !== fileName && name !== namesFile && name !== areasFile)
    .map((name) => join(GEO_DIR, name));
  stale.push(...extra);

  const schools =
    directory === null
      ? `${String(outlying.length)} schools off the outline, as committed (no directory here)`
      : `${String(directory.length)} schools, ${String(outlying.length)} off the outline`;
  const named =
    places === null
      ? `${String(cities.length)} cities, as committed (no places here)`
      : `${String(cities.length)} cities`;
  const smallest = states.reduce((a, b) => (b.fit < a.fit ? b : a));
  const moved = offsets.filter(([ox, oy]) => ox !== 0 || oy !== 0).length;
  const summary = `${String(points)} vertices, ${String(geojson.length)} B raw, ${String(gzipBytes)} B gzipped, states' shapes ${String(areaGzipBytes)} B gzipped, still ${String(svg.length)} B; ${schools}; ${named}, ${String(moved)} set off a line; ${String(states.length)} state names (${smallest.name} fits last)`;
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
