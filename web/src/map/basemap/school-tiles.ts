/**
 * The school tiles, served inside MapLibre's workers from schools.pmtiles.
 *
 * maplibre-worker.ts imports this module into each worker and calls
 * registerSchoolTiles there, so a school tile loads in the worker that parses
 * it: its bytes are read from the archive with a range request, unzipped,
 * and each school's name is put in the form the page shows
 * (src/text/names.ts: "THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS" is drawn
 * as "The Pembroke Hill School - Wornall Campus"). Nothing else in the tile
 * changes.
 *
 * The style names the archive in each tile's URL
 * ("snowlight-schools://https://.../schools.<hash>.pmtiles/{z}/{x}/{y}"), so a
 * worker reads any archive the page points it at, each through one reader.
 *
 * The page imports this module too, only for its URL (the chunk the workers
 * import), as it does street-tiles.ts. It must not touch the DOM.
 */
import type { AddProtocolAction } from 'maplibre-gl';

import { SCHOOL_NAME_FIXES } from 'virtual:snowlight/school-names';

import { displayName } from '../../text/names';
import type { NameFix } from '../../text/names';
import { stateOfId } from '../../text/school-names';
import { SCHOOLS_TILE_LAYER, SCHOOL_TILES_PROTOCOL } from './ids';
import { ArchiveReader, gunzipWithStreams, httpRangeReader } from './mask/pmtiles';
import { decodeTile, encodeTile } from './mask/mvt';
import type { Layer, LayerOutput } from './mask/mvt';
import { Writer } from './mask/protobuf';
import type { WorkerScope } from './street-tiles';

/** URL of this module's chunk, which each worker imports. */
export const SCHOOL_TILES_URL: string = import.meta.url;

const TILE_URL = new RegExp(`^${SCHOOL_TILES_PROTOCOL}://(.+)/(\\d+)/(\\d+)/(\\d+)$`);

/** Layer field of a property value; Value field of a string. */
const LAYER_VALUES = 4;
const VALUE_STRING = 1;

/** Public school ids are 12 digits and start with the state's FIPS code. */
const PUBLIC_SCHOOL = /^\d{12}$/;

/**
 * The state of a public school, from its id, for the parts of its name that
 * read by state (names.ts: MS stays in Mississippi's names, a state's own code
 * stays in capitals); null for a private school, whose id does not say.
 */
export function stateOf(id: string | null): string | null {
  return id !== null && PUBLIC_SCHOOL.test(id) ? stateOfId(id) : null;
}

/**
 * The schools layer with each name as the page shows it. Values are shared:
 * a name the same for every school using it is changed in place, and a
 * school whose name reads differently, or whose name is also another
 * property's value, gets a value of its own.
 */
function showNames(layer: Layer, fixes: Readonly<Record<string, NameFix>>): LayerOutput {
  const nameKey = layer.keys.indexOf('name');
  const idKey = layer.keys.indexOf('id');
  const features = layer.features.map((feature) => feature.raw);
  if (nameKey < 0) return { fields: layer.fields, features };
  const tagsOf = layer.features.map((feature) => feature.tags());
  /** Values some other property uses: never changed in place. */
  const shared = new Set<number>();
  for (const tags of tagsOf) {
    for (let i = 0; i + 1 < tags.length; i += 2) {
      if (tags[i] !== nameKey) shared.add(tags[i + 1] ?? -1);
    }
  }
  /** Value index to its shown name, as first shown. */
  const replaced = new Map<number, string>();
  /** Shown names that needed a value of their own, by name, as new value indices. */
  const added = new Map<string, number>();
  const valueCount = layer.values.length;
  layer.features.forEach((feature, f) => {
    const tags = tagsOf[f] ?? [];
    let nameAt = -1;
    let id: string | null = null;
    for (let i = 0; i + 1 < tags.length; i += 2) {
      if (tags[i] === nameKey) nameAt = i + 1;
      if (tags[i] === idKey) id = layer.values[tags[i + 1] ?? -1] ?? null;
    }
    const value = tags[nameAt] ?? -1;
    const raw = layer.values[value];
    if (nameAt < 0 || raw === null || raw === undefined) return;
    const shown = displayName(raw, { state: stateOf(id) }, fixes[id ?? ''] ?? {});
    // A value another property uses keeps its text for that property.
    const first = replaced.get(value) ?? (shared.has(value) ? raw : undefined);
    if (first === undefined) {
      replaced.set(value, shown);
      return;
    }
    if (first === shown) return;
    let own = added.get(shown);
    if (own === undefined) {
      own = valueCount + added.size;
      added.set(shown, own);
    }
    tags[nameAt] = own;
    features[f] = feature.withTags(tags);
  });
  const fields: Uint8Array[] = [];
  let value = 0;
  for (const field of layer.fields) {
    // Value fields are the ones whose position lines up with layer.values: count them as they pass.
    if ((field[0] ?? 0) === ((LAYER_VALUES << 3) | 2)) {
      const shown = replaced.get(value);
      fields.push(shown === undefined || shown === layer.values[value] ? field : valueField(shown));
      value++;
    } else fields.push(field);
  }
  for (const shown of added.keys()) fields.push(valueField(shown));
  return { fields, features };
}

/** A layer's value field holding a string. */
function valueField(text: string): Uint8Array {
  return new Writer()
    .bytes(LAYER_VALUES, new Writer().string(VALUE_STRING, text).finish())
    .finish();
}

/**
 * A school tile with every school's name as the page shows it, with the
 * directory's fixes for its names (school-names.ts; this build's by default).
 */
export function showSchoolNames(
  tile: Uint8Array,
  fixes: Readonly<Record<string, NameFix>> = SCHOOL_NAME_FIXES,
): Uint8Array {
  const layers = decodeTile(tile);
  return encodeTile(
    layers.map((layer) =>
      layer.name === SCHOOLS_TILE_LAYER
        ? showNames(layer, fixes)
        : { fields: layer.fields, features: layer.features.map((feature) => feature.raw) },
    ),
  );
}

/** Opens an archive by URL: reads byte ranges over HTTP, unzips tiles, keeps none. */
export type ArchiveOpener = (url: string) => ArchiveReader;

const openOverHttp: ArchiveOpener = (url) =>
  new ArchiveReader(httpRangeReader(url), gunzipWithStreams, { keepTiles: false });

/** The protocol handler: school tile z/x/y of the archive the URL names. */
export function schoolTileLoader(open: ArchiveOpener = openOverHttp): AddProtocolAction {
  const archives = new Map<string, ArchiveReader>();
  return async (request) => {
    const match = TILE_URL.exec(request.url);
    if (match === null) throw new Error(`School tiles: unexpected request ${request.url}`);
    const [archiveUrl = '', ...zxy] = match.slice(1);
    const [z, x, y] = zxy.map(Number) as [number, number, number];
    let archive = archives.get(archiveUrl);
    if (archive === undefined) {
      archive = open(archiveUrl);
      archives.set(archiveUrl, archive);
    }
    const tile = await archive.tile(z, x, y);
    if (tile === null) return { data: new ArrayBuffer(0) };
    const shown = showSchoolNames(tile);
    return { data: shown.buffer.slice(shown.byteOffset, shown.byteOffset + shown.byteLength) };
  };
}

/** Serves the style's school tiles in this worker. */
export function registerSchoolTiles(scope: WorkerScope): void {
  if (scope.addProtocol === undefined) throw new Error('School tiles: not in a MapLibre worker');
  scope.addProtocol(SCHOOL_TILES_PROTOCOL, schoolTileLoader());
}
