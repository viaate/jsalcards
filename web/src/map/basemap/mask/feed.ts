/**
 * The US mask, fetched once, by the page, and handed to MapLibre's workers.
 *
 * A street tile near a border or a coast is cut by the mask (street-tiles.ts)
 * and cannot be drawn before it is in; one wholly inside the US (us-inside.ts)
 * needs none. So the mask is asked for as soon as someone shows they are
 * going to streets that need it, and not otherwise, never on a plain visit:
 * when they start a search on a link the browser does not call slow; on a
 * slow one, when the search shows such a place first (once its index is in:
 * until then the search needs the link more); when they press on a school
 * there; or when a flight or the map itself first needs such tiles
 * (index.ts, App.svelte).
 * It is fetched whole (pmtiles.ts loadWholeArchive), once, and each worker is
 * sent a copy over a channel of this page's own (maskFeed); a worker asks on
 * it when it needs the mask, and again with each tile it is asked for while
 * it waits, which wakes a retry that is waiting (at most once every
 * NUDGE_GAP_MS), as does the browser coming back online.
 *
 * A worker with no such channel fetches the mask itself (ownMaskSource). A
 * page from an older build asks for a mask file the site no longer has: the
 * mask is also published under a name that never changes (US_MASK_ALIAS),
 * asked for once the file's own name answers 404. Used on the page and in
 * the workers: it must not touch the DOM beyond the global scope's events.
 */
import { Alarm } from '../retry';
import { loadWholeArchive, memoryReader } from './pmtiles';
import type { RangeReader, WholeFileOptions } from './pmtiles';

/** What the page and its workers say about the mask on the page's channel. */
export type MaskMessage =
  | { readonly type: 'need' }
  | { readonly type: 'mask'; readonly url: string; readonly bytes: Uint8Array };

function isMaskMessage(data: unknown): data is MaskMessage {
  if (typeof data !== 'object' || data === null) return false;
  const { type, url, bytes } = data as Record<string, unknown>;
  return (
    type === 'need' || (type === 'mask' && typeof url === 'string' && bytes instanceof Uint8Array)
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

/** A load of the whole mask that a nudge, or the network coming back, wakes as it waits. */
function wakeableLoad(
  url: string,
  options: WholeFileOptions,
): {
  readonly file: () => Promise<Uint8Array>;
  readonly nudge: () => void;
  readonly stop: () => void;
} {
  const alarm = new Alarm();
  const get = options.fetch ?? ((input: string, init: RequestInit) => fetch(input, init));
  let lastTry = Number.NEGATIVE_INFINITY;
  let file: Promise<Uint8Array> | undefined;
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
          return get(input, init);
        },
        sleep: (ms) => alarm.sleep(ms),
      }).then((bytes) => {
        done = true;
        stop();
        return bytes;
      });
      return file;
    },
    nudge: () => {
      if (!done && Date.now() - lastTry >= NUDGE_GAP_MS) alarm.ring();
    },
    stop,
  };
}

/** The page's side: the mask, fetched once, for its workers. */
export interface MaskFeed {
  /**
   * Asks for the mask, if it has not been asked for yet: `priority` is the
   * first request's (a search asks with 'low', so the search index goes
   * first; a flight, a link or a worker with 'high').
   */
  start(priority?: RequestPriority): void;
  /** Whether the mask has been asked for. */
  readonly started: boolean;
  /** Resolves once the mask is in, and has gone to the workers. */
  readonly loaded: Promise<void>;
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
  let bytes: Uint8Array | null = null;
  let load: ReturnType<typeof wakeableLoad> | null = null;
  let markLoaded: () => void = () => undefined;
  const loaded = new Promise<void>((resolve) => {
    markLoaded = resolve;
  });
  const send = (): void => {
    if (bytes !== null) port?.postMessage({ type: 'mask', url, bytes } satisfies MaskMessage);
  };
  const start = (priority?: RequestPriority): void => {
    if (load !== null) return;
    load = wakeableLoad(url, { ...options, ...(priority === undefined ? {} : { priority }) });
    void load.file().then((file) => {
      bytes = file;
      send();
      markLoaded();
    });
  };
  if (port !== null) {
    port.onmessage = (event: MessageEvent) => {
      if (!isMaskMessage(event.data) || event.data.type !== 'need') return;
      if (bytes !== null) {
        send();
        return;
      }
      start('high');
      load?.nudge();
    };
  }
  return {
    start,
    get started() {
      return load !== null;
    },
    loaded,
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
}

/** The mask at `url`, fetched by this worker itself: for a worker the page does not feed. */
export function ownMaskSource(url: string, options: WholeFileOptions = {}): MaskSource {
  const load = wakeableLoad(url, options);
  return { reader: memoryReader(url, load.file), nudge: load.nudge };
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
  let arrive: (file: Uint8Array) => void = () => undefined;
  const arrived = new Promise<Uint8Array>((resolve) => {
    arrive = resolve;
  });
  port.onmessage = (event: MessageEvent) => {
    const message: unknown = event.data;
    if (!isMaskMessage(message) || message.type !== 'mask' || message.url !== url) return;
    if (bytes !== null) return;
    bytes = message.bytes;
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
  };
}
