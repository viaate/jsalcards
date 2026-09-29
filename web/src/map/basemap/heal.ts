/**
 * The tiles a source failed to load, asked for again until they come.
 *
 * MapLibre asks for a tile once: one that fails (every try its worker makes,
 * openfreemap.ts, school-tiles.ts) stays failed, and the map draws nothing
 * there, for as long as it stays in view, however soon the network is back.
 * Here the page drops a source's failed tiles after a wait, and the map's next
 * frame asks for them afresh, as tiles it has never had; the wait grows each
 * round the source fails (HEAL_BACKOFF), and starts over once one of its
 * tiles comes. The network coming back asks for them all at once; someone
 * looking (the page shown again, or a hand on the map: a move, a zoom, a
 * tap) asks at once for one (PROBE_GAP_MS apart at most), and for the rest
 * as soon as it comes. So a failed tile comes as soon as the network lets it,
 * and is drawn the moment it does, with nobody moving the map or loading the
 * page again, and within seconds for someone who is looking.
 *
 * What a round costs the host: the first asks again for every failed tile,
 * each tried once by a worker that has seen the host fail (openfreemap.ts);
 * while the source keeps failing, each round after asks for one of them
 * only (a probe), and once a tile of the source comes while a probe is out,
 * the rest are asked for at once, each once, with nothing waiting on the map
 * coming to rest. So a host that turns the page away is asked about once a
 * minute, per tab, for as long as it does.
 */
import type { ErrorEvent, Map as MapLibreMap, MapSourceDataEvent } from 'maplibre-gl';

import { backoffDelay } from './retry';
import type { Backoff } from './retry';

/**
 * Waits before each round of asking again for a source's failed tiles, in
 * milliseconds, the last repeated while the source keeps failing. An answer
 * asking the page to wait longer (a Retry-After) is waited out besides
 * (openfreemap.ts).
 */
export const HEAL_BACKOFF: Backoff = [1000, 2000, 4000, 8000, 15_000, 30_000, 60_000];

/** The least time between two rounds that someone looking asks for at once, in milliseconds. */
export const PROBE_GAP_MS = 5000;

/** One source's rounds: how long to wait before the next, starting over once a tile comes. */
export class HealRounds {
  private round = 0;

  /** The wait before the next round, which counts it. */
  next(random?: () => number): number {
    const wait = backoffDelay(HEAL_BACKOFF, this.round, random);
    this.round++;
    return wait;
  }

  /** A tile came: the next failure waits the shortest again. */
  reset(): void {
    this.round = 0;
  }

  /** Rounds since a tile last came. */
  get count(): number {
    return this.round;
  }
}

/** The map's style, or undefined before it has one. */
export function styleOf(map: MapLibreMap): MapLibreMap['style'] | undefined {
  // Undefined until the map is given one, whatever its type says.
  const { style } = map as { style?: MapLibreMap['style'] };
  return style;
}

/** The ids of a source's tiles in view that failed to load. */
export function failedTiles(map: MapLibreMap, source: string): string[] {
  const tiles = styleOf(map)?.tileManagers[source];
  if (tiles === undefined) return [];
  return tiles.getIds().filter((id) => tiles.getTileByID(id)?.state === 'errored');
}

/** Asks again for the failed tiles of `sources` as long as the map lives; returns what stops it. */
export function healTiles(map: MapLibreMap, sources: readonly string[]): () => void {
  const rounds = new Map(sources.map((source) => [source, new HealRounds()]));
  const timers = new Map<string, number>();
  /** The sources with a probe out: one of their failed tiles asked for, the rest waiting on it. */
  const probes = new Set<string>();
  /**
   * Drops the source's failed tiles, or one of them while the source keeps
   * failing (a probe): the next frame asks for them as new tiles.
   */
  const retry = (source: string): void => {
    timers.delete(source);
    const ids = failedTiles(map, source);
    const tiles = styleOf(map)?.tileManagers[source];
    probes.delete(source);
    if (tiles === undefined || ids.length === 0) return;
    const probing = (rounds.get(source)?.count ?? 0) > 1 && ids.length > 1;
    if (probing) probes.add(source);
    for (const id of probing ? ids.slice(0, 1) : ids) tiles._removeTile(id);
    map._update(true);
  };
  /** Asks again after the source's next wait, or at once; a round already waiting stays. */
  const schedule = (source: string, now = false): void => {
    const waiting = timers.get(source);
    if (waiting !== undefined) {
      if (!now) return;
      window.clearTimeout(waiting);
    }
    const wait = now ? 0 : (rounds.get(source)?.next() ?? 0);
    timers.set(
      source,
      window.setTimeout(() => {
        retry(source);
      }, wait),
    );
  };
  const onError = (event: ErrorEvent): void => {
    const sourceId = (event as { sourceId?: unknown }).sourceId;
    if (typeof sourceId === 'string' && rounds.has(sourceId)) schedule(sourceId);
  };
  /**
   * A tile came: the source's next failure waits the shortest again. With a
   * probe out, the host answers again: the tiles waiting on the probe are
   * asked for now, in a round of their own that drops every failed tile.
   */
  const onData = (event: MapSourceDataEvent): void => {
    const source = event.sourceId;
    if (event.tile === undefined || !rounds.has(source)) return;
    if ((event.tile as { state?: unknown }).state !== 'loaded') return;
    rounds.get(source)?.reset();
    if (probes.delete(source)) schedule(source, true);
  };
  /** At rest, any tile still failed is asked for again in its turn. */
  const onIdle = (): void => {
    for (const source of sources) if (failedTiles(map, source).length > 0) schedule(source);
  };
  /** The network is back: every failed tile is asked for now. */
  const online = (): void => {
    for (const source of sources) {
      rounds.get(source)?.reset();
      if (failedTiles(map, source).length > 0) schedule(source, true);
    }
  };
  /** When someone looking last asked for a round at once. */
  let lastLook = Number.NEGATIVE_INFINITY;
  /**
   * Someone is looking (the page shown again, a hand on the map): the next
   * round now, a probe of one tile while the source keeps failing, its rounds
   * going on as they were.
   */
  const look = (): void => {
    if (document.visibilityState === 'hidden' || Date.now() - lastLook < PROBE_GAP_MS) return;
    lastLook = Date.now();
    for (const source of sources) {
      if (failedTiles(map, source).length > 0) schedule(source, true);
    }
  };
  const onMoveStart = (event: { originalEvent?: unknown }): void => {
    if (event.originalEvent !== undefined) look();
  };
  map.on('error', onError);
  map.on('sourcedata', onData);
  map.on('idle', onIdle);
  map.on('movestart', onMoveStart);
  map.on('mousedown', look);
  map.on('touchstart', look);
  map.on('wheel', look);
  window.addEventListener('online', online);
  document.addEventListener('visibilitychange', look);
  return () => {
    map.off('error', onError);
    map.off('sourcedata', onData);
    map.off('idle', onIdle);
    map.off('movestart', onMoveStart);
    map.off('mousedown', look);
    map.off('touchstart', look);
    map.off('wheel', look);
    window.removeEventListener('online', online);
    document.removeEventListener('visibilitychange', look);
    for (const timer of timers.values()) window.clearTimeout(timer);
    timers.clear();
  };
}
