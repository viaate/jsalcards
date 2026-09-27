#!/usr/bin/env node
/**
 * Builds the US mask: the part of the map outside the continental US and DC,
 * as vector tiles in a PMTiles archive the street tile workers read by byte
 * range from zoom 7 up (src/map/basemap/street-tiles.ts). Street tiles along
 * the border are cut against it, so nothing in Canada, Mexico or the islands
 * is drawn, and the border line is drawn along its edge.
 *
 * Sources, downloaded once into web/.cache/us-mask/ and checked against the
 * checksums below:
 *
 * - U.S. Census Bureau, TIGER/Line Shapefiles 2025, States
 *   (tl_2025_us_state.zip). The 48 states and DC are unioned. Their outline
 *   runs 3 nautical miles out to sea off most coasts (9 off Texas and the
 *   Gulf coast of Florida), so every US island and shore is inside it.
 * - International Boundary Commission, US-Canada boundary shapefile,
 *   version 1.3 (2018), from the boundary's monuments and turning points.
 *   Along the Canadian border the outline follows it: TIGER's line strays
 *   from it by up to 3 km in the Great Lakes and their rivers (94 m in the
 *   Detroit River), so within a corridor along the boundary (5 km wide each
 *   side through the Great Lakes, the St. Lawrence and their rivers, 1 km
 *   elsewhere) the boundary line replaces TIGER's.
 * - U.S. Census Bureau, TIGER/Line Shapefiles 2025, International Boundary
 *   (tl_2025_us_internationalboundary.zip), whose US-Mexico section comes
 *   from the International Boundary and Water Commission. The states' outline
 *   already follows it; it marks which edges are the border.
 *
 * Output, deterministic:
 *
 *   public/geo/us-mask.<hash>.pmtiles   The archive (format in src/map/basemap/mask/format.ts).
 *   src/map/basemap/us-mask.ts          Its file name, zooms and sources.
 *
 *   node scripts/build-us-mask.mjs           write the files
 *   node scripts/build-us-mask.mjs --check   exit 1 if any file is stale
 */
import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { createRequire, registerHooks } from 'node:module';
import { dirname, join, relative } from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { TextDecoder } from 'node:util';
import { gzipSync } from 'node:zlib';

import prettier from 'prettier';

// The tiling code is TypeScript shared with the site. Node strips its types;
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

// Imported after the hook is in place, so not as static imports.
const { BORDER_FLAG, buildPyramid } = await import('../src/map/basemap/mask/pyramid.ts');
const { writeArchive } = await import('../src/map/basemap/mask/pmtiles.ts');
const { MASK_MIN_ZOOM } = await import('../src/map/basemap/mask/format.ts');

/** @type {unknown} */
const loadedMapshaper = createRequire(import.meta.url)('mapshaper');
/**
 * mapshaper ships no type declarations; this is the one call used.
 * @typedef {{ applyCommands(commands: string, input: Record<string, string | Uint8Array>): Promise<Record<string, string | Uint8Array>> }} Mapshaper
 */
const mapshaper = /** @type {Mapshaper} */ (loadedMapshaper);

/** @typedef {[number, number]} LonLat */
/**
 * @typedef {object} Source
 * @property {string} url
 * @property {string} file
 * @property {string} sha256
 * @property {string} vintage
 * @property {string} publisher
 */

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..');
const CACHE_DIR = join(WEB, '.cache/us-mask');
const GEO_DIR = join(WEB, 'public/geo');
const META_FILE = join(WEB, 'src/map/basemap/us-mask.ts');

/** @type {Record<'states' | 'canada' | 'international', Source>} */
const SOURCES = {
  states: {
    url: 'https://www2.census.gov/geo/tiger/TIGER2025/STATE/tl_2025_us_state.zip',
    file: 'tl_2025_us_state.zip',
    sha256: '59a220888a8d9be8117c4fcd38f542bd02d81abf0d198c78113595ad540dd957',
    vintage: 'TIGER/Line Shapefiles 2025, States (published 2025-09-23)',
    publisher: 'U.S. Census Bureau',
  },
  canada: {
    url: 'https://www.internationalboundarycommission.org/uploads/shapefile/us-canada-boundary-v1-3.zip',
    file: 'us-canada-boundary-v1-3.zip',
    sha256: 'eb327459528b87cbc27e55ccc6bfd6982562c75559823a00b6dc50c04abcaab1',
    vintage: 'US-Canada boundary shapefile, version 1.3 (2018)',
    publisher: 'International Boundary Commission',
  },
  international: {
    url: 'https://www2.census.gov/geo/tiger/TIGER2025/INTERNATIONALBOUNDARY/tl_2025_us_internationalboundary.zip',
    file: 'tl_2025_us_internationalboundary.zip',
    sha256: '8da3c40ae83160178e979c59b26860af39f0c4bc11afa4e9d868785437ecac8e',
    vintage:
      'TIGER/Line Shapefiles 2025, International Boundary (US-Mexico section from the IBWC; published 2025-09-23)',
    publisher: 'U.S. Census Bureau and International Boundary and Water Commission',
  },
};

/** Alaska, Hawaii and the territories. */
const EXCLUDED_FIPS = ['02', '15', '60', '66', '69', '72', '78'];

/**
 * IBC sections from Passamaquoddy Bay (1) to the Strait of Juan de Fuca (26):
 * the boundary of the lower 48 with Canada, one continuous line from east to
 * west. Section 0 is the Gulf of Maine, out at sea; 27 on are Alaska's.
 */
const FIRST_SECTION = 1;
const LAST_SECTION = 26;
/** The Great Lakes, the St. Lawrence and their rivers, where TIGER strays furthest. */
const LAKE_SECTIONS = [13, 14, 15, 16];
/** Meters either side of the boundary it replaces TIGER's line within. */
const LAKE_CORRIDOR_METERS = 5000;
const CORRIDOR_METERS = 1000;
/** A vertex this close to the Canadian or Mexican boundary, in meters, is on it. */
const BORDER_METERS = 1;

/** Zooms and simplification (tile units: 4096 across a tile, 8 to a pixel at 512 px tiles). */
const BORDER_MAX_ZOOM = 12;
const SEA_MAX_ZOOM = 11;
/** @param {number} z */
const borderTolerance = (z) => (z >= BORDER_MAX_ZOOM ? 0.5 : 1);
/** Out at sea, two pixels: 5 km or more from any shore, nothing is drawn on either side. */
const seaTolerance = () => 16;
/** Budget from the spec: a small asset, read by range. */
const MAX_BYTES = 2 * 1024 * 1024;

/**
 * Places the mask must get right, checked on the unioned outline before it is
 * tiled: [name, lon, lat, inside the US].
 * @type {[string, number, number, boolean][]}
 */
const CHECKS = [
  ['Detroit, Hart Plaza', -83.0445, 42.3285, true],
  ['Windsor riverfront', -83.0345, 42.3195, false],
  ['Belle Isle, Detroit River', -82.98, 42.341, true],
  ['Port Huron', -82.425, 42.975, true],
  ['Sarnia', -82.395, 42.97, false],
  ['Niagara Falls, New York', -79.045, 43.09, true],
  ['Niagara Falls, Ontario', -79.08, 43.09, false],
  ['Buffalo', -78.878, 42.886, true],
  ['Fort Erie', -78.92, 42.905, false],
  ['Lake Erie, US waters', -81.5, 41.9, true],
  ['Lake Erie, Canadian waters', -81.5, 42.5, false],
  ['Pelee Island', -82.66, 41.78, false],
  ['Kelleys Island', -82.7, 41.6, true],
  ['Lake Ontario, US waters', -77.5, 43.4, true],
  ['Lake Ontario, Canadian waters', -77.5, 43.8, false],
  ['Wolfe Island', -76.35, 44.18, false],
  ['Cape Vincent', -76.33, 44.125, true],
  ['Sault Ste. Marie, Michigan', -84.35, 46.49, true],
  ['Sault Ste. Marie, Ontario', -84.33, 46.52, false],
  ['Northwest Angle', -95.08, 49.33, true],
  ['Lake of the Woods, Canadian side', -94.9, 49.5, false],
  ['Blaine', -122.75, 48.995, true],
  ['White Rock', -122.8, 49.02, false],
  ['Point Roberts', -123.06, 48.98, true],
  ['Tsawwassen', -123.07, 49.01, false],
  ['Lubec', -66.99, 44.86, true],
  ['Campobello Island', -66.95, 44.88, false],
  ['Calais', -67.28, 45.19, true],
  ['St. Stephen', -67.28, 45.2, false],
  ['San Ysidro', -117.04, 32.545, true],
  ['Tijuana', -117.03, 32.53, false],
  ['El Paso', -106.48, 31.765, true],
  ['Ciudad Juarez', -106.48, 31.73, false],
  ['Laredo', -99.505, 27.51, true],
  ['Nuevo Laredo', -99.51, 27.48, false],
  ['Brownsville', -97.49, 25.905, true],
  ['Matamoros', -97.5, 25.87, false],
  ['Nogales, Arizona', -110.94, 31.345, true],
  ['Nogales, Sonora', -110.94, 31.31, false],
  ['Key West', -81.78, 24.555, true],
  ['Dry Tortugas', -82.87, 24.63, true],
  ['Bimini', -79.28, 25.73, false],
  ['Havana', -82.37, 23.13, false],
  ['Grand Bahama', -78.7, 26.6, false],
  ['Monhegan Island', -69.315, 43.765, true],
  ['San Clemente Island', -118.5, 32.9, true],
  ['Ocean, 20 km off Cape Hatteras', -75.3, 35.2, false],
];

/**
 * @param {Source} source
 * @returns {Promise<Buffer>}
 */
async function cached(source) {
  const path = join(CACHE_DIR, source.file);
  let bytes = await readFile(path).catch(() => null);
  if (bytes === null) {
    process.stdout.write(`build-us-mask: downloading ${source.url}\n`);
    const response = await fetch(source.url);
    if (!response.ok) throw new Error(`${source.url}: HTTP ${String(response.status)}`);
    bytes = Buffer.from(await response.arrayBuffer());
    await mkdir(CACHE_DIR, { recursive: true });
    await writeFile(path, bytes);
  }
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  if (sha256 !== source.sha256) {
    throw new Error(
      `build-us-mask: ${source.file} has sha256 ${sha256}, expected ${source.sha256}; the source changed`,
    );
  }
  return bytes;
}

/**
 * Runs mapshaper and returns the output file's parsed GeoJSON.
 * @param {string} commands
 * @param {Record<string, string | Uint8Array>} input
 * @param {string} output
 * @returns {Promise<any>}
 */
async function run(commands, input, output) {
  const files = await mapshaper.applyCommands(commands, input);
  const text = files[output];
  if (text === undefined) throw new Error(`build-us-mask: mapshaper wrote no ${output}`);
  return JSON.parse(typeof text === 'string' ? text : new TextDecoder().decode(text));
}

/**
 * Geometries of a GeoJSON FeatureCollection or GeometryCollection.
 * @param {any} geojson
 * @returns {any[]}
 */
function geometries(geojson) {
  if (geojson.type === 'GeometryCollection') return geojson.geometries;
  if (geojson.type === 'FeatureCollection')
    return geojson.features.map((/** @type {any} */ f) => f.geometry);
  return [geojson];
}

/**
 * Polygons of a GeoJSON geometry, each a list of rings.
 * @param {any} geometry
 * @returns {LonLat[][][]}
 */
function polygonsOf(geometry) {
  if (geometry === null) return [];
  if (geometry.type === 'Polygon') return [geometry.coordinates];
  if (geometry.type === 'MultiPolygon') return geometry.coordinates;
  throw new Error(`build-us-mask: expected polygons, got ${String(geometry.type)}`);
}

/**
 * The IBC boundary as one line from Passamaquoddy Bay to the Pacific, and its sections.
 * @param {Buffer} zip
 */
async function canadaBoundary(zip) {
  const collection = await run(
    '-i boundary.zip encoding=latin1 -o boundary.json format=geojson precision=0.0000001',
    { 'boundary.zip': zip },
    'boundary.json',
  );
  /** @type {{ section: number, name: string, line: LonLat[] }[]} */
  const sections = [];
  for (const feature of collection.features) {
    const section = Number(feature.properties.SectionNum);
    if (section < FIRST_SECTION || section > LAST_SECTION) continue;
    const { type, coordinates } = feature.geometry;
    const parts = type === 'LineString' ? [coordinates] : coordinates;
    if (parts.length !== 1)
      throw new Error(`build-us-mask: IBC section ${String(section)} is in pieces`);
    sections.push({ section, name: String(feature.properties.SectionEng), line: parts[0] });
  }
  sections.sort((a, b) => a.section - b.section);
  if (sections.length !== LAST_SECTION - FIRST_SECTION + 1) {
    throw new Error('build-us-mask: IBC sections missing');
  }
  /** @type {LonLat[]} */
  const chain = [];
  for (const { section, line } of sections) {
    const last = chain.at(-1);
    const first = line[0];
    if (last !== undefined && first !== undefined) {
      if (Math.abs(last[0] - first[0]) > 1e-6 || Math.abs(last[1] - first[1]) > 1e-6) {
        throw new Error(`build-us-mask: IBC section ${String(section)} does not continue the line`);
      }
      chain.push(...line.slice(1));
    } else {
      chain.push(...line);
    }
  }
  return { sections, chain };
}

/**
 * The polygon between the boundary line and a far line of latitude: everything
 * on one side of the boundary, from the Pacific end to the Atlantic end.
 * @param {LonLat[]} chain east to west
 * @param {number} farLat
 * @returns {LonLat[]}
 */
function sideOf(chain, farLat) {
  const east = chain[0];
  const west = chain.at(-1);
  if (east === undefined || west === undefined) throw new Error('build-us-mask: empty boundary');
  const lons = chain.map(([lon]) => lon);
  const eastLon = Math.max(...lons) + 1;
  const westLon = Math.min(...lons) - 1;
  /** @type {LonLat[]} */
  const closure = [
    west,
    [westLon, west[1]],
    [westLon, farLat],
    [eastLon, farLat],
    [eastLon, east[1]],
    east,
  ];
  // The way round must not cross the boundary, or the polygon would fold over itself.
  for (let i = 1; i < closure.length; i++) {
    for (let k = 1; k < chain.length; k++) {
      const [a, b, c, d] = [closure[i - 1], closure[i], chain[k - 1], chain[k]];
      if (a === undefined || b === undefined || c === undefined || d === undefined) continue;
      if (a === c || a === d || b === c || b === d) continue;
      if (segmentsCross(a, b, c, d))
        throw new Error('build-us-mask: the way round crosses the boundary');
    }
  }
  return [...chain, ...closure.slice(1)];
}

/**
 * @param {LonLat} a
 * @param {LonLat} b
 * @param {LonLat} c
 * @param {LonLat} d
 */
function segmentsCross(a, b, c, d) {
  /** @param {LonLat} p @param {LonLat} q @param {LonLat} r */
  const turn = (p, q, r) =>
    Math.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]));
  return turn(a, b, c) !== turn(a, b, d) && turn(c, d, a) !== turn(c, d, b);
}

/** @param {LonLat[]} ring */
function polygon(ring) {
  return JSON.stringify({
    type: 'Feature',
    properties: {},
    geometry: { type: 'Polygon', coordinates: [ring] },
  });
}

/**
 * The union of the 48 states and DC, with the IBC boundary in place of
 * TIGER's line along the Canadian border.
 * @param {Buffer} statesZip
 * @param {Awaited<ReturnType<typeof canadaBoundary>>} canada
 */
async function usOutline(statesZip, canada) {
  const north = polygon(sideOf(canada.chain, 75));
  const south = polygon(sideOf(canada.chain, 15));
  const sections = JSON.stringify({
    type: 'FeatureCollection',
    features: canada.sections.map(({ section, line }) => ({
      type: 'Feature',
      properties: {
        radius: LAKE_SECTIONS.includes(section) ? LAKE_CORRIDOR_METERS : CORRIDOR_METERS,
      },
      geometry: { type: 'LineString', coordinates: line },
    })),
  });
  const commands = [
    `-i states.zip name=states`,
    `-filter '!${JSON.stringify(EXCLUDED_FIPS)}.includes(STATEFP)'`,
    '-dissolve',
    `-i sections.json name=corridor`,
    `-buffer radius='radius' target=corridor`,
    '-dissolve target=corridor',
    '-i north.json name=north',
    '-i south.json name=south',
    // Canada's side of the boundary off TIGER's outline...
    '-erase north target=states name=cut',
    // ...and the US side of the boundary, near it, onto it.
    '-clip corridor target=south name=near',
    '-merge-layers target=cut,near name=us force',
    '-dissolve target=us',
    '-o us.json target=us format=geojson precision=0.0000001',
  ].join(' ');
  const collection = await run(
    commands,
    {
      'states.zip': statesZip,
      'sections.json': sections,
      'north.json': north,
      'south.json': south,
    },
    'us.json',
  );
  return geometries(collection).flatMap(polygonsOf);
}

/**
 * The Mexico border's lines from TIGER's international boundary.
 * @param {Buffer} zip
 * @returns {Promise<LonLat[][]>}
 */
async function mexicoBoundary(zip) {
  const collection = await run(
    `-i boundary.zip -filter 'IBTYPE === "M"' -o boundary.json format=geojson precision=0.0000001`,
    { 'boundary.zip': zip },
    'boundary.json',
  );
  return collection.features.flatMap((/** @type {any} */ feature) =>
    feature.geometry.type === 'LineString'
      ? [feature.geometry.coordinates]
      : feature.geometry.coordinates,
  );
}

const EARTH_RADIUS = 6_371_008.8;

/**
 * Meters from a point to a segment, on a plane fitted at the point.
 * @param {LonLat} p
 * @param {LonLat} a
 * @param {LonLat} b
 */
function metersToSegment(p, a, b) {
  const k = Math.cos((p[1] * Math.PI) / 180);
  const ax = (a[0] - p[0]) * k;
  const ay = a[1] - p[1];
  const dx = (b[0] - a[0]) * k;
  const dy = b[1] - a[1];
  const length = dx * dx + dy * dy;
  let t = length === 0 ? 0 : -(ax * dx + ay * dy) / length;
  t = Math.max(0, Math.min(1, t));
  return (Math.hypot(ax + t * dx, ay + t * dy) * Math.PI * EARTH_RADIUS) / 180;
}

/**
 * A lookup of whether a point is on any of the lines, through a grid of cells.
 * @param {LonLat[][]} lines
 */
function lineIndex(lines) {
  const cell = 0.01;
  /** @type {Map<string, [LonLat, LonLat][]>} */
  const grid = new Map();
  for (const line of lines) {
    for (let i = 1; i < line.length; i++) {
      const a = line[i - 1];
      const b = line[i];
      if (a === undefined || b === undefined) continue;
      for (
        let x = Math.floor(Math.min(a[0], b[0]) / cell);
        x <= Math.floor(Math.max(a[0], b[0]) / cell);
        x++
      ) {
        for (
          let y = Math.floor(Math.min(a[1], b[1]) / cell);
          y <= Math.floor(Math.max(a[1], b[1]) / cell);
          y++
        ) {
          const key = `${String(x)},${String(y)}`;
          const list = grid.get(key);
          if (list === undefined) grid.set(key, [[a, b]]);
          else list.push([a, b]);
        }
      }
    }
  }
  /** @param {LonLat} p @param {number} meters */
  return (p, meters) => {
    const cx = Math.floor(p[0] / cell);
    const cy = Math.floor(p[1] / cell);
    for (let x = cx - 1; x <= cx + 1; x++) {
      for (let y = cy - 1; y <= cy + 1; y++) {
        for (const [a, b] of grid.get(`${String(x)},${String(y)}`) ?? []) {
          if (metersToSegment(p, a, b) <= meters) return true;
        }
      }
    }
    return false;
  };
}

/**
 * Whether a point is inside the polygons (even-odd over every ring).
 * @param {LonLat[][][]} polygons
 * @param {LonLat} p
 */
function inside(polygons, p) {
  let odd = false;
  for (const rings of polygons) {
    for (const ring of rings) {
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const a = ring[i];
        const b = ring[j];
        if (a === undefined || b === undefined) continue;
        if (
          a[1] > p[1] !== b[1] > p[1] &&
          p[0] < ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]
        ) {
          odd = !odd;
        }
      }
    }
  }
  return odd;
}

/**
 * @param {string} text
 * @param {string} path
 */
async function format(text, path) {
  const config = (await prettier.resolveConfig(path)) ?? {};
  return prettier.format(text, { ...config, filepath: path });
}

/**
 * @param {{ file: string, bytes: number, tiles: number, minZoom: number, maxZoom: number }} info
 */
function metaText(info) {
  const sources = Object.values(SOURCES)
    .map(
      (source) => `  {
    publisher: ${JSON.stringify(source.publisher)},
    vintage: ${JSON.stringify(source.vintage)},
    url: ${JSON.stringify(source.url)},
    sha256: ${JSON.stringify(source.sha256)},
  },`,
    )
    .join('\n');
  return `// Generated by scripts/build-us-mask.mjs. Do not edit by hand: run
// "npm run build:mask".

/** The US mask archive (mask/format.ts), relative to the site base URL. */
export const US_MASK_FILE = '${info.file}';

/** Its size in bytes, and the tiles it addresses. */
export const US_MASK_BYTES = ${String(info.bytes)};
export const US_MASK_TILES = ${String(info.tiles)};

/** The zooms it holds tiles for; deeper tiles take their ancestor's shape. */
export const US_MASK_MIN_ZOOM = ${String(info.minZoom)};
export const US_MASK_MAX_ZOOM = ${String(info.maxZoom)};

/** What it was built from. */
export const US_MASK_SOURCES = [
${sources}
] as const;
`;
}

async function main() {
  const check = process.argv.includes('--check');
  const [statesZip, canadaZip, internationalZip] = await Promise.all([
    cached(SOURCES.states),
    cached(SOURCES.canada),
    cached(SOURCES.international),
  ]);
  const canada = await canadaBoundary(canadaZip);
  const mexico = await mexicoBoundary(internationalZip);
  const polygons = await usOutline(statesZip, canada);

  for (const [name, lon, lat, expected] of CHECKS) {
    if (inside(polygons, [lon, lat]) !== expected) {
      throw new Error(
        `build-us-mask: ${name} (${String(lon)}, ${String(lat)}) should be ${expected ? 'inside' : 'outside'} the US`,
      );
    }
  }

  const onBorder = lineIndex([canada.chain, ...mexico]);
  /** @type {{ coords: number[], flags: Uint8Array, hole: boolean }[]} */
  const rings = [];
  let vertices = 0;
  let borderVertices = 0;
  for (const rings_ of polygons) {
    rings_.forEach((ring, index) => {
      // GeoJSON repeats a ring's first point last; the tiles do not.
      const open = ring.slice(0, -1);
      const flags = new Uint8Array(open.length);
      open.forEach((point, i) => {
        if (onBorder(point, BORDER_METERS)) {
          flags[i] = BORDER_FLAG;
          borderVertices++;
        }
      });
      vertices += open.length;
      rings.push({ coords: open.flat(), flags, hole: index > 0 });
    });
  }

  const { tiles, stats } = buildPyramid(rings, {
    minZoom: MASK_MIN_ZOOM,
    borderMaxZoom: BORDER_MAX_ZOOM,
    seaMaxZoom: SEA_MAX_ZOOM,
    borderTolerance,
    seaTolerance,
  });
  const archive = writeArchive(tiles, {
    metadata: {
      name: 'Snowlight US mask',
      description:
        'The map outside the continental US and DC (layer us_mask) and the land and inland-water border with Canada and Mexico (layer us_border).',
      vector_layers: [
        { id: 'us_mask', fields: {}, minzoom: MASK_MIN_ZOOM, maxzoom: BORDER_MAX_ZOOM },
        { id: 'us_border', fields: {}, minzoom: MASK_MIN_ZOOM, maxzoom: BORDER_MAX_ZOOM },
      ],
      sources: Object.values(SOURCES),
      generator: 'web/scripts/build-us-mask.mjs',
    },
    bounds: [-125, 24.3, -66.8, 49.5],
    center: [-98.5, 39.5, MASK_MIN_ZOOM],
    gzip: (bytes) => gzipSync(bytes, { level: 9 }),
  });
  if (archive.length > MAX_BYTES) {
    throw new Error(
      `build-us-mask: the archive is ${String(archive.length)} B, over the ${String(MAX_BYTES)} B budget`,
    );
  }
  const hash = createHash('sha256').update(archive).digest('hex').slice(0, 10);
  const fileName = `us-mask.${hash}.pmtiles`;
  const meta = await format(
    metaText({
      file: `geo/${fileName}`,
      bytes: archive.length,
      tiles: tiles.length,
      minZoom: MASK_MIN_ZOOM,
      maxZoom: BORDER_MAX_ZOOM,
    }),
    META_FILE,
  );

  const existing = (await readdir(GEO_DIR).catch(() => /** @type {string[]} */ ([]))).filter(
    (name) => /^us-mask\.[0-9a-f]+\.pmtiles$/.test(name),
  );
  const archivePath = join(GEO_DIR, fileName);
  /** @type {string[]} */
  const stale = [];
  const current = await readFile(archivePath).catch(() => null);
  if (current === null || !current.equals(archive)) stale.push(archivePath);
  if ((await readFile(META_FILE, 'utf8').catch(() => null)) !== meta) stale.push(META_FILE);
  const extra = existing.filter((name) => name !== fileName).map((name) => join(GEO_DIR, name));
  stale.push(...extra);

  const byZoom = Object.entries(stats.tiles)
    .map(([key, n]) => `${key} ${String(n)}`)
    .join(', ');
  const summary = `${String(vertices)} vertices (${String(borderVertices)} on the border), ${String(tiles.length)} tiles, ${String(archive.length)} B`;
  if (check) {
    if (stale.length > 0) {
      process.stderr.write(
        `build-us-mask: stale, run "npm run build:mask":\n${stale.map((p) => `  ${relative(WEB, p)}\n`).join('')}`,
      );
      process.exit(1);
    }
    process.stdout.write(`build-us-mask: up to date (${summary})\n`);
    return;
  }
  for (const path of extra) await rm(path);
  if (stale.includes(archivePath)) await writeFile(archivePath, archive);
  if (stale.includes(META_FILE)) await writeFile(META_FILE, meta);
  process.stdout.write(`build-us-mask: wrote ${fileName} (${summary})\n  tiles: ${byZoom}\n`);
}

await main();
