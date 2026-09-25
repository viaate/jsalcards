/**
 * What a Snowlight link carries, and how it reads and writes the query string.
 *
 *   ?school=<NCES school id>   a public (12 digits) or private (8 characters) school
 *   ?district=<LEAID>          a school district (7 digits)
 *   ?zip=<ZIP code>            a ZIP code (5 digits)
 *   ?at=<lat>,<lon>,<zoom>     the map view
 *
 * One selection at a time: when a link names several, the most specific wins
 * (school, then district, then ZIP). Values that do not parse are ignored, as
 * are parameters this module does not know; those are kept, untouched, when
 * the address bar is rewritten, so other features can add their own.
 */

import type { DistrictId, SchoolId } from '../types/generated';
import { parseDistrictId, parseSchoolId, parseZipCode } from './ids';

export type Selection =
  | { readonly kind: 'school'; readonly id: SchoolId }
  | { readonly kind: 'district'; readonly id: DistrictId }
  | { readonly kind: 'zip'; readonly id: string };

export type SelectionKind = Selection['kind'];

/** A map view: the center in degrees and the zoom level. */
export interface View {
  readonly lat: number;
  readonly lon: number;
  readonly zoom: number;
}

export interface UrlState {
  readonly selection: Selection | null;
  readonly view: View | null;
}

export const EMPTY_STATE: UrlState = Object.freeze({ selection: null, view: null });

/** Query parameters this module owns, in the order they are written. */
export const PARAMS = Object.freeze({
  school: 'school',
  district: 'district',
  zip: 'zip',
  at: 'at',
} as const);

const SELECTION_ORDER: readonly SelectionKind[] = ['school', 'district', 'zip'];
const OWNED = new Set<string>(Object.values(PARAMS));

/**
 * Limits of a view. Latitude stops where Web Mercator does; zoom matches the
 * map's own minZoom and maxZoom (src/map/basemap/index.ts).
 */
export const VIEW_LIMITS = Object.freeze({
  maxLat: 85.051129,
  minZoom: 1,
  maxZoom: 16,
});

/** A plain decimal: no exponent, hex, Infinity or stray characters. */
const DECIMAL = /^[-+]?(?:\d{1,4}(?:\.\d{0,12})?|\.\d{1,12})$/;

function decimal(text: string | undefined): number | null {
  if (text === undefined) return null;
  const trimmed = text.trim();
  if (!DECIMAL.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

/** Longitude folded into [-180, 180); a longitude already in range is returned as is. */
function wrapLongitude(lon: number): number {
  if (lon >= -180 && lon < 180) return lon === 0 ? 0 : lon;
  return ((((lon + 180) % 360) + 360) % 360) - 180;
}

/** A view with its latitude and zoom clamped and its longitude wrapped; null if not finite. */
export function normalizeView(view: View): View | null {
  const { lat, lon, zoom } = view;
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(zoom)) return null;
  return {
    lat: clamp(lat, -VIEW_LIMITS.maxLat, VIEW_LIMITS.maxLat),
    lon: wrapLongitude(lon),
    zoom: clamp(zoom, VIEW_LIMITS.minZoom, VIEW_LIMITS.maxZoom),
  };
}

/** Parses "lat,lon,zoom". Out-of-range numbers are clamped; anything malformed is null. */
export function parseView(raw: string | null | undefined): View | null {
  if (typeof raw !== 'string' || raw.length > 64) return null;
  const parts = raw.split(',');
  if (parts.length !== 3) return null;
  const [lat = null, lon = null, zoom = null] = parts.map(decimal);
  if (lat === null || lon === null || zoom === null) return null;
  return normalizeView({ lat, lon, zoom });
}

/**
 * Decimal places that keep a coordinate within about a pixel at this zoom:
 * one 512-pixel tile spans 360 / 2^zoom degrees.
 */
export function coordinateDecimals(zoom: number): number {
  const pixelsPerDegree = (512 * 2 ** zoom) / 360;
  return clamp(Math.ceil(Math.log10(pixelsPerDegree)), 2, 6);
}

/** A number at a fixed number of decimals, with trailing zeros and "-0" dropped. */
function fixed(value: number, decimals: number): string {
  const text = value.toFixed(decimals);
  const trimmed = text.includes('.') ? text.replace(/\.?0+$/, '') : text;
  return trimmed === '-0' ? '0' : trimmed;
}

/** "41.8781,-87.6298,10.25": the form ?at= carries. */
export function formatView(view: View): string {
  const normal = normalizeView(view);
  if (normal === null) throw new RangeError('url: a view needs finite numbers');
  const zoom = fixed(normal.zoom, 2);
  const decimals = coordinateDecimals(Number(zoom));
  // Rounding can carry 179.999 up to 180, which is -180 on the map, and a
  // latitude past the Mercator limit; that one is cut toward the equator instead.
  const lon = fixed(wrapLongitude(Number(fixed(normal.lon, decimals))), decimals);
  const scale = 10 ** decimals;
  const lat =
    Math.abs(Number(fixed(normal.lat, decimals))) > VIEW_LIMITS.maxLat
      ? Math.trunc(normal.lat * scale) / scale
      : normal.lat;
  return [fixed(lat, decimals), lon, zoom].join(',');
}

/** A view rounded the way a link stores it, so equal links mean equal views. */
export function roundView(view: View): View | null {
  const normal = normalizeView(view);
  if (normal === null) return null;
  const [lat, lon, zoom] = formatView(normal).split(',').map(Number);
  return { lat: lat ?? normal.lat, lon: lon ?? normal.lon, zoom: zoom ?? normal.zoom };
}

function parseSelectionValue(kind: SelectionKind, raw: string): Selection | null {
  switch (kind) {
    case 'school': {
      const id = parseSchoolId(raw);
      return id === null ? null : { kind, id };
    }
    case 'district': {
      const id = parseDistrictId(raw);
      return id === null ? null : { kind, id };
    }
    case 'zip': {
      const id = parseZipCode(raw);
      return id === null ? null : { kind, id };
    }
  }
}

/** One query parameter as written in the URL, and its decoded name and value. */
interface RawParam {
  readonly raw: string;
  readonly name: string;
  readonly value: string;
}

function decode(text: string): string | null {
  try {
    return decodeURIComponent(text.replace(/\+/g, ' '));
  } catch {
    return null;
  }
}

/** Splits a query string ("?a=1&b=2" or "a=1&b=2") without re-encoding anything. */
function rawParams(search: string): RawParam[] {
  const query = search.startsWith('?') ? search.slice(1) : search;
  if (query === '') return [];
  const params: RawParam[] = [];
  for (const raw of query.split('&')) {
    if (raw === '') continue;
    const equals = raw.indexOf('=');
    const name = decode(equals === -1 ? raw : raw.slice(0, equals));
    const value = decode(equals === -1 ? '' : raw.slice(equals + 1));
    // An undecodable pair is junk; it is kept only if its name is not one of ours.
    params.push({ raw, name: name ?? '', value: value ?? '' });
  }
  return params;
}

/** Reads the state from a query string. Never throws; junk reads as nothing. */
export function parseUrlState(search: string): UrlState {
  const params = rawParams(search);
  const first = <T>(name: string, parse: (value: string) => T | null): T | null => {
    for (const param of params) {
      if (param.name !== name) continue;
      const parsed = parse(param.value);
      if (parsed !== null) return parsed;
    }
    return null;
  };
  let selection: Selection | null = null;
  for (const kind of SELECTION_ORDER) {
    selection = first(PARAMS[kind], (value) => parseSelectionValue(kind, value));
    if (selection !== null) break;
  }
  return { selection, view: first(PARAMS.at, parseView) };
}

/** The owned parameters for a state, in canonical order, e.g. "school=…&at=…". */
export function stateQuery(state: UrlState): string {
  const parts: string[] = [];
  const { selection, view } = state;
  // Every value is validated to [0-9A-Z.,-], so nothing needs escaping, and commas stay readable.
  if (selection !== null) {
    const parsed = parseSelectionValue(selection.kind, selection.id);
    if (parsed === null) throw new RangeError(`url: "${selection.id}" is not a ${selection.kind}`);
    parts.push(`${PARAMS[parsed.kind]}=${parsed.id}`);
  }
  if (view !== null) parts.push(`${PARAMS.at}=${formatView(view)}`);
  return parts.join('&');
}

/**
 * The query string for `state`, keeping every parameter in `search` this
 * module does not own, byte for byte and in order, after the owned ones.
 * Returns "" or a string starting with "?".
 */
export function mergeQuery(search: string, state: UrlState): string {
  const kept = rawParams(search)
    .filter((param) => !OWNED.has(param.name))
    .map((param) => param.raw);
  const own = stateQuery(state);
  const all = own === '' ? kept : [own, ...kept];
  return all.length === 0 ? '' : `?${all.join('&')}`;
}

/** `href` with its query rewritten for `state`; the path and hash are kept. */
export function mergeHref(href: string, state: UrlState): string {
  const url = new URL(href);
  const query = mergeQuery(url.search, state);
  return `${url.origin}${url.pathname}${query}${url.hash}`;
}

/** A clean link to `state` on the page at `href`: only the owned parameters, no hash. */
export function shareHref(href: string, state: UrlState): string {
  const url = new URL(href);
  const query = stateQuery(state);
  return `${url.origin}${url.pathname}${query === '' ? '' : `?${query}`}`;
}

export function sameSelection(a: Selection | null, b: Selection | null): boolean {
  if (a === null || b === null) return a === b;
  return a.kind === b.kind && a.id === b.id;
}

export function sameView(a: View | null, b: View | null): boolean {
  if (a === null || b === null) return a === b;
  return formatView(a) === formatView(b);
}

export function sameState(a: UrlState, b: UrlState): boolean {
  return sameSelection(a.selection, b.selection) && sameView(a.view, b.view);
}
