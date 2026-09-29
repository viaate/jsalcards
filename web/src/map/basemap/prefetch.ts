/**
 * The street tiles a flight ends on, worked out before it starts, so they can
 * be asked for at once (openfreemap.ts) and be in the browser's cache by the
 * time the map needs them. A search pick flies from the whole country to a
 * street in a couple of seconds: MapLibre asks for each zoom's tiles only as
 * the camera reaches it, so without them the map would be empty from zoom 7
 * until the last tiles arrive.
 *
 * The tiles are the ones covering the screen at the view's own tile zoom,
 * and the ones covering it at each zoom the flight stops at on its way in
 * (flight.ts flightZooms): a flight asks for street tiles only where it stops
 * (index.ts), and goes on once they cover the screen, drawing them scaled up
 * until the closer ones are in. These are the only street tiles a flight
 * asks for. Plain math on Web Mercator tile numbers, as MapLibre counts
 * them: 512 px tiles, a view at zoom 13.2 drawn from zoom 13 tiles.
 *
 * Before any flight, the tiles where one would stop (stopTiles) tell whether
 * the streets there need the US mask, for a school pressed on or a place a
 * search keeps first (firstPlace), so it can come while the person chooses
 * (index.ts prepareStreets).
 */
import { mercatorXFromLng, mercatorYFromLat } from '../glow/mercator';
import type { MapView } from './bounds';
import { FLIGHT_STOP_ZOOM, flightZooms } from './flight';
import type { Size } from './limits';
import { OPENFREEMAP_MAX_ZOOM, OPENFREEMAP_MIN_ZOOM } from './openfreemap';
import { US_BOUNDS } from './us-geo';

/** A tile: zoom, column, row. */
export type TileId = readonly [z: number, x: number, y: number];

/** MapLibre's vector tiles are 512 px. */
const TILE_SIZE = 512;

/** At most this many tiles for one flight: a large screen at street zoom and the steps above it. */
export const MAX_FLIGHT_TILES = 48;

/**
 * At most this many on a slow link, for its stop and for where it ends: the
 * tiles it needs first come sooner for the others not sharing the link.
 */
export const SLOW_LINK_FLIGHT_TILES = 24;

/** What the browser says of its link, where it says (the Network Information API). */
export interface LinkInfo {
  readonly saveData?: boolean;
  readonly effectiveType?: string;
  /** Megabits a second, as the browser estimates them. */
  readonly downlink?: number;
}

/** The link this page is on, where the browser says. */
function pageLink(): LinkInfo | undefined {
  return (globalThis.navigator as { connection?: LinkInfo } | undefined)?.connection;
}

/**
 * Whether the link may be slow: the browser says so (data saving on, less
 * than 4G, or under 5 Mbit/s), or says nothing of it (Safari and Firefox
 * have no Network Information API).
 */
export function slowLink(link: LinkInfo | undefined = pageLink()): boolean {
  return (
    link === undefined ||
    link.saveData === true ||
    (link.effectiveType !== undefined && link.effectiveType !== '4g') ||
    (link.downlink !== undefined && link.downlink > 0 && link.downlink < 5)
  );
}

/**
 * How many tiles a flight asks for ahead, for its stop and for where it
 * ends: MAX_FLIGHT_TILES, or SLOW_LINK_FLIGHT_TILES on a link that may be
 * slow (slowLink).
 */
export function flightTileLimit(link: LinkInfo | undefined = pageLink()): number {
  return slowLink(link) ? SLOW_LINK_FLIGHT_TILES : MAX_FLIGHT_TILES;
}

/** Tile columns (or rows) from `lo` to `hi` world units at zoom `z`, inside the world. */
function span(lo: number, hi: number, z: number): number[] {
  const count = 2 ** z;
  const first = Math.max(0, Math.floor(lo * count));
  const last = Math.min(count - 1, Math.floor(hi * count));
  const out: number[] = [];
  for (let i = first; i <= last; i++) out.push(i);
  return out;
}

/**
 * The street tiles a flight to `view` on a screen of `size`, paced from tiles
 * of zoom `from`, asks for: the ones covering the screen at the view, at its
 * tile zoom, and at each zoom it stops at on the way (flightZooms), with the
 * camera there, from OpenFreeMap's first zoom up: the furthest zoom first,
 * since the flight passes it first, and within a zoom, the middle of the
 * screen first. Only tiles that reach the continental US's box: the rest
 * would be cut away whole (street-tiles.ts). None below OpenFreeMap's first
 * zoom, where nothing is fetched at all.
 */
export function flightTiles(view: MapView, size: Size, from: number = FLIGHT_STOP_ZOOM): TileId[] {
  const top = Math.min(Math.floor(view.zoom), OPENFREEMAP_MAX_ZOOM);
  if (top < OPENFREEMAP_MIN_ZOOM) return [];
  const cx = mercatorXFromLng(view.lon);
  const cy = mercatorYFromLat(view.lat);
  const [west, south, east, north] = US_BOUNDS;
  const usX = [mercatorXFromLng(west), mercatorXFromLng(east)] as const;
  const usY = [mercatorYFromLat(north), mercatorYFromLat(south)] as const;
  const tiles: TileId[] = [];
  const seen = new Set<number>();
  for (const z of flightZooms(top, from)) {
    if (z < OPENFREEMAP_MIN_ZOOM || seen.has(z)) continue;
    seen.add(z);
    // Half the screen in world units, with the camera where it stops at this zoom, or at the view.
    const world = TILE_SIZE * 2 ** (z === top ? view.zoom : z);
    const halfX = size.width / 2 / world;
    const halfY = size.height / 2 / world;
    const count = 2 ** z;
    const zoomTiles: { tile: TileId; away: number }[] = [];
    for (const x of span(Math.max(cx - halfX, usX[0]), Math.min(cx + halfX, usX[1]), z)) {
      for (const y of span(Math.max(cy - halfY, usY[0]), Math.min(cy + halfY, usY[1]), z)) {
        const away = Math.hypot((x + 0.5) / count - cx, (y + 0.5) / count - cy);
        zoomTiles.push({ tile: [z, x, y], away });
      }
    }
    zoomTiles.sort((a, b) => a.away - b.away);
    tiles.push(...zoomTiles.map(({ tile }) => tile));
  }
  return tiles.slice(0, MAX_FLIGHT_TILES);
}

/**
 * The street tiles covering a screen of `size` over `view` at the street
 * tiles' first zoom, where a flight there from further out stops
 * (FLIGHT_STOP_ZOOM): every street tile a flight to `view` asks for is under
 * one of them. None for a view short of the streets: a flight there asks for
 * no street tiles at all.
 */
export function stopTiles(view: MapView, size: Size): TileId[] {
  if (Math.floor(view.zoom) < OPENFREEMAP_MIN_ZOOM) return [];
  return flightTiles({ ...view, zoom: FLIGHT_STOP_ZOOM }, size, FLIGHT_STOP_ZOOM);
}

/** A search's first place, waited on until it stays first (firstPlace). */
export interface FirstPlace {
  /** The place the search shows first now, or null for none: a new one's wait starts over. */
  show(view: MapView | null): void;
  /**
   * The map is going somewhere: a wait still running ends, never heard of,
   * and its place is not waited on again while the search keeps it first.
   */
  cancel(): void;
}

/**
 * Hands `settled` the place a search shows first once it has stayed first for
 * `ms`: results that keep it first leave its wait running, however often they
 * come, so a place shown on the way to another as someone types is never
 * handed on, and one they stop at is, typing on or not.
 */
export function firstPlace(ms: number, settled: (view: MapView) => void): FirstPlace {
  let first: MapView | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const cancel = (): void => {
    clearTimeout(timer);
  };
  return {
    show(view) {
      const same =
        view !== null &&
        first !== null &&
        view.lat === first.lat &&
        view.lon === first.lon &&
        view.zoom === first.zoom;
      if (same) return;
      cancel();
      first = view;
      if (view === null) return;
      timer = setTimeout(() => {
        settled(view);
      }, ms);
    },
    cancel,
  };
}
