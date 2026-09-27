/**
 * The national city and state names the screen's edges would cut.
 *
 * MapLibre places a label that runs off the screen as readily as one inside
 * it. At a phone's home view the country runs off both sides of the screen,
 * and a name cut in half at the edge of the first screen reads as a fault:
 * the map leaves those names out there (style.ts), and brings them back once
 * someone moves it, when names come and go at the edges as on any map.
 */
import { mercatorXFromLng, mercatorYFromLat } from '../glow/mercator';
import type { MapView } from './bounds';
import {
  STATE_NAME_LEADING,
  STATE_NAME_TRACKING,
  stateNameShown,
  stateNameSize,
} from './state-names';
import type { StateName } from './state-names';
import { CITY_NAME_BANDS, CITY_NAME_HALO, CITY_NAME_LETTER_SPACING, cityNameSize } from './style';
import type { UsLinesData } from './style';

/** A national city name, where the map puts it and its rank (0 for the largest city). */
export interface CityName {
  readonly name: string;
  readonly rank: number;
  readonly lon: number;
  readonly lat: number;
}

/** The width, in CSS pixels, of `text` set `size` pixels high in the city names' face. */
export type MeasureText = (text: string, size: number) => number;

/** A screen size in CSS pixels. */
interface Screen {
  readonly width: number;
  readonly height: number;
}

/** MapLibre's tiles are 512 px: the world is 512 * 2^zoom px wide. */
const TILE_SIZE = 512;

/** A line of a city name, as tall as its size times this. */
const LINE_HEIGHT = 1.2;

/** A name as the map sets it at a view: its lines, where on the screen, and how. */
interface Label {
  readonly name: string;
  readonly lines: readonly string[];
  /** Its middle, in CSS pixels from the screen's top left corner. */
  readonly x: number;
  readonly y: number;
  readonly size: number;
  /** Space between letters and between lines, in ems of the size. */
  readonly tracking: number;
  readonly leading: number;
}

/** Pixels kept between a name and the screen's edge, beyond its halo. */
const EDGE_GAP = 2;

/**
 * A name's width in ems per character, at most: wider than Geist Medium sets
 * any of the names. Names whose box at this width is wholly on screen or
 * wholly off it are never measured; a name near an edge whose face cannot be
 * measured is taken to be this wide, and left out rather than cut.
 */
const WIDEST_EM_PER_CHARACTER = 0.8;

/** The city names in the bundled file, in its order. */
export function cityNamesOf(usLines: UsLinesData): CityName[] {
  const names: CityName[] = [];
  for (const feature of usLines.features) {
    const { properties, geometry } = (feature ?? {}) as {
      properties?: { kind?: unknown; name?: unknown; rank?: unknown };
      geometry?: { type?: unknown; coordinates?: unknown };
    };
    if (properties?.kind !== 'city' || geometry?.type !== 'Point') continue;
    const { name, rank } = properties;
    const [lon, lat]: readonly unknown[] = Array.isArray(geometry.coordinates)
      ? (geometry.coordinates as readonly unknown[])
      : [];
    if (typeof name !== 'string' || typeof rank !== 'number') continue;
    if (typeof lon !== 'number' || typeof lat !== 'number') continue;
    names.push({ name, rank, lon, lat });
  }
  return names;
}

/**
 * Measures text as MapLibre sets a city name: each glyph's advance in the
 * medium weight of Geist, which the page's own face already has loaded, added
 * up (MapLibre draws its own glyphs and does not kern them). Until that face
 * is loaded, and where there is no canvas, a generous width per character.
 */
export function textMeasure(
  doc: Pick<Document, 'createElement'> & { readonly fonts?: Pick<FontFaceSet, 'check'> } = document,
): MeasureText {
  const context = doc.createElement('canvas').getContext('2d');
  /** The face the canvas is set in, once it has been found loaded. */
  let set = '';
  return (text, size) => {
    const face = `500 ${String(size)}px "Geist Variable"`;
    if (context === null) return text.length * size * WIDEST_EM_PER_CHARACTER;
    if (face !== set) {
      if (doc.fonts?.check(face) !== true) return text.length * size * WIDEST_EM_PER_CHARACTER;
      context.font = face;
      set = face;
    }
    let width = 0;
    for (const character of text) width += context.measureText(character).width;
    return width;
  };
}

/** How many of the largest cities the map names at `zoom`: the bands in from there. */
function namedAt(zoom: number): number {
  let named = 0;
  for (const band of CITY_NAME_BANDS) if (zoom >= band.zoom) named = band.names;
  return named;
}

/** Where a point is on `screen` at `view`, in CSS pixels from its top left corner. */
function screenPoint(
  view: MapView,
  screen: Screen,
  lon: number,
  lat: number,
): readonly [x: number, y: number] {
  const scale = TILE_SIZE * 2 ** view.zoom;
  return [
    screen.width / 2 + (mercatorXFromLng(lon) - mercatorXFromLng(view.lon)) * scale,
    screen.height / 2 + (mercatorYFromLat(lat) - mercatorYFromLat(view.lat)) * scale,
  ];
}

/**
 * The city names the map would show at `view` on `screen` whose label, with
 * its halo, would cross an edge of the screen: part on screen, part off it.
 */
export function namesCutByEdges(
  cities: readonly CityName[],
  view: MapView,
  screen: Screen,
  measure: MeasureText,
): string[] {
  const named = namedAt(view.zoom);
  if (named === 0) return [];
  const size = cityNameSize(view.zoom);
  const labels = cities
    .filter((city) => city.rank < named)
    .map((city): Label => {
      const [x, y] = screenPoint(view, screen, city.lon, city.lat);
      const lines = [city.name];
      return {
        name: city.name,
        lines,
        x,
        y,
        size,
        tracking: CITY_NAME_LETTER_SPACING,
        leading: LINE_HEIGHT,
      };
    });
  return cutByEdges(labels, screen, measure);
}

/** The same for the state names, which the map sets in capitals, some over two lines. */
export function stateNamesCutByEdges(
  states: readonly StateName[],
  view: MapView,
  screen: Screen,
  measure: MeasureText,
): string[] {
  const size = stateNameSize(view.zoom);
  const labels = states
    .filter((state) => stateNameShown(state.fit, view.zoom))
    .map((state): Label => {
      const [x, y] = screenPoint(view, screen, state.lon, state.lat);
      const lines = state.label.toUpperCase().split('\n');
      return {
        name: state.name,
        lines,
        x,
        y,
        size,
        tracking: STATE_NAME_TRACKING,
        leading: STATE_NAME_LEADING,
      };
    });
  return cutByEdges(labels, screen, measure);
}

/** The names of the labels that run over an edge of `screen`. */
function cutByEdges(labels: readonly Label[], screen: Screen, measure: MeasureText): string[] {
  const cut: string[] = [];
  for (const { name, lines, x, y, size, tracking, leading } of labels) {
    const halfHeight = (size * leading * lines.length) / 2 + CITY_NAME_HALO + EDGE_GAP;
    // Clear of every edge even at the widest a name can be: no need to measure it.
    const longest = Math.max(...lines.map((line) => line.length));
    const widest =
      (longest * size * (WIDEST_EM_PER_CHARACTER + tracking)) / 2 + CITY_NAME_HALO + EDGE_GAP;
    const inside = x - widest >= 0 && x + widest <= screen.width;
    const outside = x + widest <= 0 || x - widest >= screen.width;
    const clearDown = !crosses(y - halfHeight, y + halfHeight, screen.height);
    if ((inside || outside) && clearDown) continue;
    // Letters as MapLibre spaces them: one glyph per UTF-16 unit, as the names are all Latin.
    const width = Math.max(
      ...lines.map((line) => measure(line, size) + Math.max(0, line.length - 1) * tracking * size),
    );
    const halfWidth = width / 2 + CITY_NAME_HALO + EDGE_GAP;
    const across = crosses(x - halfWidth, x + halfWidth, screen.width);
    const down = crosses(y - halfHeight, y + halfHeight, screen.height);
    const onScreen =
      x + halfWidth > 0 &&
      x - halfWidth < screen.width &&
      y + halfHeight > 0 &&
      y - halfHeight < screen.height;
    if (onScreen && (across || down)) cut.push(name);
  }
  return cut;
}

/** Whether a span from `low` to `high` runs over either end of 0 to `length`. */
function crosses(low: number, high: number, length: number): boolean {
  return (low < 0 && high > 0) || (low < length && high > length);
}
