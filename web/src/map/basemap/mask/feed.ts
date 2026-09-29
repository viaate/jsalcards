/**
 * The US mask, fetched once, by the page, and handed to MapLibre's workers.
 *
 * A street tile near a border or a coast is cut by the mask (street-tiles.ts)
 * and cannot be drawn before it is in; one wholly inside the US (us-inside.ts)
 * needs none. So the mask is asked for as soon as someone shows they are
 * going to streets that need it, and not otherwise, never on a plain visit:
 * when their search shows such a place first (once its index is in: until
 * then the search needs the link), when they press on a school there, or
 * when a flight or the map itself first needs such tiles (index.ts,
 * App.svelte). It is fetched whole (pmtiles.ts loadWholeArchive), once, and
 * each worker is sent a copy over a channel of this page's own (maskFeed); a
 * worker asks on it when it needs the mask, and again with each tile it is
 * asked for while it waits, which wakes a retry that is waiting (at most once
 * every NUDGE_GAP_MS), as does the browser coming back online.
 *
 * A worker with no such channel fetches the mask itself (ownMaskSource). A
 * page from an older build asks for a mask file the site no longer has: the
 * mask is also published under a name that never changes (US_MASK_ALIAS),
 * asked for once the file's own name answers 404. That copy may be a newer
 * mask than the page's list of the tiles wholly inside the US was made from,
 * so a worker given it trusts that list no more (MaskSource insideListHolds).
 * Used on the page and in the workers: it must not touch the DOM beyond the
 * global scope's events.
 */
import { Alarm } from '../retry';
import { ArchiveReader, loadWholeArchive, memoryReader } from './pmtiles';
import type { RangeReader, WholeFileOptions } from './pmtiles';
import { tileMask } from './source';

/** What the page and its workers say about the mask on the page's channel. */
export type MaskMessage =
  | { readonly type: 'need' }
  | {
      readonly type: 'mask';
      readonly url: string;
      readonly bytes: Uint8Array;
      /** Whether it came from its own URL, not the copy under the name that never changes. */
      readonly own: boolean;
    };

function isMaskMessage(data: unknown): data is MaskMessage {
  if (typeof data !== 'object' || data === null) return false;
  const { type, url, bytes, own } = data as Record<string, unknown>;
  return (
    type === 'need' ||
    (type === 'mask' &&
      typeof url === 'string' &&
      bytes instanceof Uint8Array &&
      typeof own === 'boolean')
  );
}

/**
 * The least time, in milliseconds, between a try at the mask and one that
 * a worker's asking wakes early: a map asking for tile after tile while the
 * site is out of reach asks for the mask no more often than this.
 */
export const NUDGE_GAP_MS = 3000;

/** Where the global scope's `online` event is heard: the page's window, or a worker's scope. */
interface Online {
  addEventListener(type: 'online', listener: () => void): void;
  removeEventListener(type: 'online', listener: () => void): void;
}

/** The mask, once in, and whether it came from its own URL. */
interface Loaded {
  readonly bytes: Uint8Array;
  readonly own: boolean;
}

/** A load of the whole mask that a nudge, or the network coming back, wakes as it waits. */
function wakeableLoad(
  url: string,
  options: WholeFileOptions,
): {
  readonly file: () => Promise<Loaded>;
  readonly nudge: () => void;
  readonly stop: () => void;
} {
  const alarm = new Alarm();
  const get = options.fetch ?? ((input: string, init: RequestInit) => fetch(input, init));
  let lastTry = Number.NEGATIVE_INFINITY;
  let lastUrl = url;
  let file: Promise<Loaded> | undefined;
  let done = false;
  const scope = globalThis as unknown as Partial<Online>;
  const online = (): void => {
    alarm.ring();
  };
  scope.addEventListener?.('online', online);
  const stop = (): void => {
    scope.removeEventListener?.('online', online);
  };
  return {
    file: () => {
      file ??= loadWholeArchive(url, {
        ...options,
        fetch: (input, init) => {
          lastTry = Date.now();
          lastUrl = input;
          return get(input, init);
        },
        sleep: (ms) => alarm.sleep(ms),
      }).then((bytes) => {
        done = true;
        stop();
        return { bytes, own: lastUrl === url };
      });
      return file;
    },
    nudge: () => {
      if (!done && Date.now() - lastTry >= NUDGE_GAP_MS) alarm.ring();
    },
    stop,
  };
}

/** A tile: zoom, column, row. */
type Tile = readonly [z: number, x: number, y: number];

/** The page's side: the mask, fetched once, for its workers. */
export interface MaskFeed {
  /** Asks for the mask, if it has not been asked for yet. */
  start(): void;
  /** Whether the mask has been asked for. */
  readonly started: boolean;
  /** Resolves once the mask is in, and has gone to the workers. */
  readonly loaded: Promise<void>;
  /** Once the mask is in: `tiles` but those it says are wholly outside the US. */
  inUs<T extends Tile>(tiles: readonly T[]): Promise<T[]>;
  /** Stops answering the workers and waking the retry. */
  destroy(): void;
}

/**
 * Fetches the mask at `url` once, when first started (or first asked for by
 * a worker on `channel`), and sends it to every worker on `channel`: as it
 * comes, and again to each worker that asks after.
 */
export function maskFeed(url: string, channel: string, options: WholeFileOptions = {}): MaskFeed {
  const port = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel(channel);
  let mask: Loaded | null = null;
  let load: ReturnType<typeof wakeableLoad> | null = null;
  let markLoaded: () => void = () => undefined;
  const loaded = new Promise<void>((resolve) => {
    markLoaded = resolve;
  });
  const reader = new ArchiveReader(
    memoryReader(url, async () => {
      await loaded;
      return mask?.bytes ?? new Uint8Array(0);
    }),
  );
  const send = (): void => {
    if (mask === null) return;
    port?.postMessage({ type: 'mask', url, ...mask } satisfies MaskMessage);
  };
  const start = (): void => {
    if (load !== null) return;
    load = wakeableLoad(url, options);
    void load.file().then((file) => {
      mask = file;
      send();
      markLoaded();
    });
  };
  if (port !== null) {
    port.onmessage = (event: MessageEvent) => {
      if (!isMaskMessage(event.data) || event.data.type !== 'need') return;
      if (mask !== null) {
        send();
        return;
      }
      start();
      load?.nudge();
    };
  }
  return {
    start,
    get started() {
      return load !== null;
    },
    loaded,
    inUs: async (tiles) => {
      const kinds = await Promise.all(tiles.map(([z, x, y]) => tileMask(reader, z, x, y)));
      return tiles.filter((_tile, i) => kinds[i]?.kind !== 'outside');
    },
    destroy: () => {
      port?.close();
      load?.stop();
    },
  };
}

/** The mask as a worker reads it, and how it says it is still waiting for it. */
export interface MaskSource {
  readonly reader: RangeReader;
  /** A tile is waiting on the mask: asks for it again, which wakes a retry that is waiting. */
  nudge(): void;
  /**
   * Whether the list of the tiles wholly inside the US (us-inside.ts) goes
   * with this mask: until a copy under the name that never changes comes in
   * its place, which may be a newer mask than the list.
   */
  readonly insideListHolds: boolean;
}

/** The mask at `url`, fetched by this worker itself: for a worker the page does not feed. */
export function ownMaskSource(url: string, options: WholeFileOptions = {}): MaskSource {
  const load = wakeableLoad(url, options);
  let holds = true;
  const file = async (): Promise<Uint8Array> => {
    const { bytes, own } = await load.file();
    holds = own;
    return bytes;
  };
  return {
    reader: memoryReader(url, file),
    nudge: load.nudge,
    get insideListHolds() {
      return holds;
    },
  };
}

/**
 * The mask at `url`, as the page sends it on `channel` (maskFeed): asked for
 * with the first read, and again with each nudge until it comes. With no
 * channel to ask on, the worker fetches it itself (ownMaskSource).
 */
export function pageMaskSource(
  url: string,
  channel: string,
  options: WholeFileOptions = {},
): MaskSource {
  if (typeof BroadcastChannel === 'undefined') return ownMaskSource(url, options);
  const port = new BroadcastChannel(channel);
  let bytes: Uint8Array | null = null;
  let holds = true;
  let arrive: (file: Uint8Array) => void = () => undefined;
  const arrived = new Promise<Uint8Array>((resolve) => {
    arrive = resolve;
  });
  port.onmessage = (event: MessageEvent) => {
    const message: unknown = event.data;
    if (!isMaskMessage(message) || message.type !== 'mask' || message.url !== url) return;
    if (bytes !== null) return;
    bytes = message.bytes;
    holds = message.own;
    port.close();
    arrive(bytes);
  };
  const ask = (): void => {
    if (bytes === null) port.postMessage({ type: 'need' } satisfies MaskMessage);
  };
  return {
    reader: memoryReader(url, () => {
      ask();
      return arrived;
    }),
    nudge: ask,
    get insideListHolds() {
      return holds;
    },
  };
}
