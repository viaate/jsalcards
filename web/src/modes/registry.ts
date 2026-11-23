/**
 * The modes the page can show, in the order the switch lists them (flights spec D2).
 *
 * Each entry says what the switch needs to know about a mode: its key (and so its address,
 * `?mode=<key>`; the first mode, Schools, is the bare address so every old link keeps working),
 * its label (its own words, from a copy module), its glyph, the address parameters it owns
 * (taken off when another mode shows), and how to start it. Schools is the page itself, so it has no module;
 * every other mode is a module of its own, loaded only when it is first shown, that mounts its
 * map layer, its panels and its search over the shared map and takes them away when it stops.
 * Adding a mode (Boats) is one more entry here and its own module; nothing in Schools or Flights
 * changes. A mode's own menu, search results and update line carry the shared classes
 * `mode-menu`, `mode-results` and `mode-updated` beside their own, so every theme draws them as
 * Schools' menu, results and update line (theme/snowball.ts SNOWBALL_SIBLINGS).
 *
 * Every function here takes the list of modes, the registry's own by default, so a test can run
 * the switch with a mode this build does not have (modes/tests/host.test.ts adds a Boats mode).
 * Its only imports are words and parameter names, so the switch, its tests and Node can read it.
 */
import { modesCopy } from '../copy-modes';
import type { Basemap } from '../map/basemap';
import { FLIGHTS_PARAMS } from './flights/address';

/** What a mode is started with. */
export interface ModeContext {
  /** The shared map. */
  readonly map: Basemap;
  /** The strip at the top of the page, where the mode's search and menu go. */
  readonly header: HTMLElement;
  /** The page, where the mode's key and panels go. */
  readonly stage: HTMLElement;
  /** Aborted when the mode stops: everything the mode put on the page goes with it. */
  readonly signal: AbortSignal;
}

/** A started mode. */
export interface ModeModule {
  start(context: ModeContext): void;
}

export interface ModeEntry {
  readonly key: string;
  /** Its label in the switch: its own words, from a copy module scripts/check-copy.mjs reads. */
  readonly label: string;
  /** Its glyph: one path on a 16 by 16 box, drawn as the page's other glyphs are (a 1.25 stroke). */
  readonly glyph: string;
  /** The address parameters it owns, taken off the address when another mode shows. */
  readonly params: readonly string[];
  /** Loads its module; null for Schools, which is the page itself. */
  readonly load: (() => Promise<ModeModule>) | null;
}

export const MODES: readonly ModeEntry[] = Object.freeze([
  {
    key: 'schools',
    label: modesCopy.schools,
    glyph: 'M2.25 7.25L8 3.25l5.75 4M3.75 6.25v7h8.5v-7M6.75 13.25v-3h2.5v3',
    // Schools' own (state/url.ts PARAMS): a school, a district or a ZIP open.
    params: ['school', 'district', 'zip'],
    load: null,
  },
  {
    key: 'flights',
    label: modesCopy.flights,
    glyph: 'M8 1.75v12.5M8 5.5L2.25 9v1.25L8 8.5l5.75 1.75V9zM5.75 14.25L8 13l2.25 1.25',
    params: FLIGHTS_PARAMS,
    load: () => import('./flights/index').then((module) => module.flightsMode),
  },
]);

/** The mode a list opens on with no `mode` in its address: its first. */
export function firstMode(modes: readonly ModeEntry[] = MODES): ModeEntry {
  const first = modes[0];
  if (first === undefined) throw new Error('Snowlight: no modes');
  return first;
}

/** The registry's first mode, Schools. */
export const FIRST_MODE: ModeEntry = firstMode(MODES);

/** The address's own parameter. */
export const MODE_PARAM = 'mode';

/** Where the last mode shown is kept on this device. */
export const MODE_STORAGE_KEY = 'snowlight:mode';

export function modeByKey(
  key: string | null | undefined,
  modes: readonly ModeEntry[] = MODES,
): ModeEntry | null {
  return modes.find((mode) => mode.key === key) ?? null;
}

/** The mode an address names, or null: none named, or one this build does not have. */
export function modeOfSearch(
  search: string,
  modes: readonly ModeEntry[] = MODES,
): ModeEntry | null {
  const value = new URLSearchParams(search).get(MODE_PARAM);
  return value === null ? null : modeByKey(value, modes);
}

/**
 * The mode to open on: the one the address names; else, at the bare address only, the one kept
 * on this device; else the first. An address with anything else in it is a link to the first
 * mode (a school, a view), so a kept mode never takes it over.
 */
export function openingMode(
  search: string,
  kept: string | null,
  modes: readonly ModeEntry[] = MODES,
): ModeEntry {
  const named = modeOfSearch(search, modes);
  if (named !== null) return named;
  if (search === '' || search === '?') return modeByKey(kept, modes) ?? firstMode(modes);
  return firstMode(modes);
}

/** The parameters every mode but `mode` owns: what goes from the address as `mode` shows. */
export function otherParams(mode: ModeEntry, modes: readonly ModeEntry[] = MODES): string[] {
  const own = new Set(mode.params);
  const others = new Set<string>();
  for (const entry of modes) {
    if (entry.key === mode.key) continue;
    for (const name of entry.params) if (!own.has(name)) others.add(name);
  }
  return [...others];
}

/** The address for `mode` from `href`: `mode` set, or taken off for the first mode. */
export function modeHref(
  href: string,
  mode: ModeEntry,
  drop: readonly string[] = [],
  modes: readonly ModeEntry[] = MODES,
): string {
  const url = new URL(href);
  for (const name of drop) url.searchParams.delete(name);
  if (mode.key === firstMode(modes).key) url.searchParams.delete(MODE_PARAM);
  else url.searchParams.set(MODE_PARAM, mode.key);
  return url.href;
}

/** The mode kept on this device, or null where storage is off or empty. */
export function keptMode(storage: Pick<Storage, 'getItem'> | null): string | null {
  try {
    return storage?.getItem(MODE_STORAGE_KEY) ?? null;
  } catch {
    return null;
  }
}

/** Keeps `mode` on this device; nothing where storage is off. */
export function keepMode(storage: Pick<Storage, 'setItem'> | null, mode: ModeEntry): void {
  try {
    storage?.setItem(MODE_STORAGE_KEY, mode.key);
  } catch {
    // Storage off or full: the address still carries the mode.
  }
}
