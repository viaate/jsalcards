/**
 * The school and district names the staged directory says to show another
 * way (src/text/school-names.ts), worked out when the site is built and
 * listed as the module `virtual:snowlight/school-names`: the map's school
 * tiles and search show them (src/text/names.ts NameFix).
 *
 * They come from the directory staged in public/data/ (npm run stage):
 * schools/meta.<hash>.json and schools/points.<hash>.bin. With no directory
 * staged, or a build that ships no data, there are none.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';

import type { Plugin } from 'vite';

import { plainPath } from '../src/data/paths.ts';
import { alikeDistricts } from '../src/text/district-names.ts';
import { displayName } from '../src/text/names.ts';
import { nameFixes, stateOfId } from '../src/text/school-names.ts';
import type { DirectoryNames, NameFixes } from '../src/text/school-names.ts';
import { listDataFiles } from './data-files.ts';

export const SCHOOL_NAMES_MODULE = 'virtual:snowlight/school-names';
const RESOLVED_ID = `\0${SCHOOL_NAMES_MODULE}`;
/** The districts whose short names keep their numbers (src/text/district-names.ts), for the panel. */
export const DISTRICT_NAMES_MODULE = 'virtual:snowlight/district-names';
const RESOLVED_DISTRICTS_ID = `\0${DISTRICT_NAMES_MODULE}`;

const META = 'schools/meta.json';
const POINTS = 'schools/points.bin';
/** points.bin (src/data/directory.ts): a 16-byte header, then 13 bytes a school. */
const POINTS_HEADER = 16;
const POINTS_RECORD = 13;
const NO_DISTRICT = 0xffffffff;

const NONE: NameFixes = { schools: {}, districts: {} };

/** The directory's names from its two files, or null when they are not one directory. */
export function directoryNames(meta: unknown, points: Uint8Array): DirectoryNames | null {
  if (typeof meta !== 'object' || meta === null) return null;
  const { ids, names, districts } = meta as Record<string, unknown>;
  const strings = (value: unknown): value is string[] =>
    Array.isArray(value) && value.every((item) => typeof item === 'string');
  if (!strings(ids) || !strings(names) || ids.length !== names.length) return null;
  if (typeof districts !== 'object' || districts === null) return null;
  const { ids: districtIds, names: districtNames } = districts as Record<string, unknown>;
  if (!strings(districtIds) || !strings(districtNames)) return null;
  if (districtIds.length !== districtNames.length) return null;
  if (points.byteLength !== POINTS_HEADER + POINTS_RECORD * ids.length) return null;
  const view = new DataView(points.buffer, points.byteOffset, points.byteLength);
  const districtOf = new Int32Array(ids.length);
  for (let i = 0; i < ids.length; i++) {
    const d = view.getUint32(POINTS_HEADER + POINTS_RECORD * i + 8, true);
    districtOf[i] = d === NO_DISTRICT || d >= districtIds.length ? -1 : d;
  }
  return { ids, names, districtOf, districts: { ids: districtIds, names: districtNames } };
}

/** The module's source. */
export function schoolNamesModule(fixes: NameFixes): string {
  return [
    `export const SCHOOL_NAME_FIXES = Object.freeze(${JSON.stringify(fixes.schools)});`,
    `export const DISTRICT_NAME_FIXES = Object.freeze(${JSON.stringify(fixes.districts)});`,
    '',
  ].join('\n');
}

/** The district module's source. */
export function districtNamesModule(alike: readonly string[]): string {
  return `export const ALIKE_DISTRICTS = Object.freeze(${JSON.stringify(alike)});\n`;
}

/** The directory's districts whose names, as the page shows them, another of the state shares. */
export function alikeDistrictIds(directory: DirectoryNames, fixes: NameFixes): string[] {
  const { ids, names } = directory.districts;
  return alikeDistricts(
    ids.map((id, i) => {
      const state = stateOfId(id);
      const shown = displayName(names[i] ?? '', { state, district: true }, fixes.districts[id]);
      return { id, state, shown };
    }),
  );
}

/** The directory staged in `dir` (public/data/), or null. */
function stagedNames(dir: string): DirectoryNames | null {
  const files = listDataFiles(dir);
  const meta = files.find((file) => plainPath(file) === META);
  const points = files.find((file) => plainPath(file) === POINTS);
  if (meta === undefined || points === undefined) return null;
  return directoryNames(
    JSON.parse(readFileSync(path.join(dir, meta), 'utf8')) as unknown,
    readFileSync(path.join(dir, points)),
  );
}

/** The fixes for the directory staged in `dir` (public/data/), or none. */
export function stagedNameFixes(dir: string): NameFixes {
  const names = stagedNames(dir);
  return names === null ? NONE : nameFixes(names);
}

export interface SchoolNamesOptions {
  /** False to ship no data, whatever is staged. Default true. */
  readonly ship?: boolean;
}

/** The plugin, for data published under `dataDir` ("data/") of the site. */
export function schoolNames(dataDir: string, options: SchoolNamesOptions = {}): Plugin {
  const ship = options.ship ?? true;
  let dir = '';
  let staged: { fixes: NameFixes; alike: string[] } | null = null;
  const read = (): { fixes: NameFixes; alike: string[] } => {
    if (staged !== null) return staged;
    const names = dir === '' || !ship ? null : stagedNames(dir);
    const fixes = names === null ? NONE : nameFixes(names);
    staged = { fixes, alike: names === null ? [] : alikeDistrictIds(names, fixes) };
    return staged;
  };
  return {
    name: 'snowlight:school-names',
    configResolved(config) {
      dir = config.publicDir === '' ? '' : path.join(config.publicDir, dataDir);
    },
    resolveId(id) {
      if (id === SCHOOL_NAMES_MODULE) return RESOLVED_ID;
      return id === DISTRICT_NAMES_MODULE ? RESOLVED_DISTRICTS_ID : null;
    },
    load(id) {
      if (id === RESOLVED_ID) return schoolNamesModule(read().fixes);
      return id === RESOLVED_DISTRICTS_ID ? districtNamesModule(read().alike) : null;
    },
    configureServer(server) {
      if (dir === '') return;
      // Staging a directory while the dev server runs: work the fixes out again for it.
      const onChange = (file: string): void => {
        if (!path.resolve(file).startsWith(path.resolve(dir) + path.sep)) return;
        staged = null;
        for (const resolved of [RESOLVED_ID, RESOLVED_DISTRICTS_ID]) {
          const module = server.moduleGraph.getModuleById(resolved);
          if (module !== undefined) server.moduleGraph.invalidateModule(module);
        }
      };
      server.watcher.on('add', onChange);
      server.watcher.on('unlink', onChange);
    },
  };
}
