/**
 * Keeps the glow in step with live/closings.json.
 *
 * The file is read at start, again every minute while the page is visible,
 * when the page comes back into view or wakes, when the device comes back
 * online, and whenever the service worker says it holds a newer copy. Each
 * minute is counted from the last read, whoever made it, so no read is ever
 * more than a minute after the one before while the page is seen. Only a
 * file newer than the one shown is taken: an older copy, from a cache or an
 * edge that has not caught up, is never shown after a newer one. The page
 * reads the file through one reader (closingsReader), which the school and
 * area panels share with the map: none of them shows a file older than one
 * another has taken, and a panel open beside the map adds no reads of its
 * own. The schools lit are worked out afresh each minute, since "today"
 * moves on even when the file does not. Schools that light up after the
 * first read pulse in once.
 *
 * A build without the file never asks for it. A read that fails keeps what
 * is shown: the last file read is still true as of its own time. A read of
 * the file, or of its directory, that takes longer than LIVE_READ_TIMEOUT_MS
 * holds no later read back.
 *
 * `onShown` hears the generated_at of the file the lit schools come from, for
 * the update time: a file is shown once it has been read against its
 * directory, or when it has no schools today. A file whose directory cannot be
 * had shows nothing, so no time is given for it either.
 *
 * `onCounts` hears how many schools are lit in each status, for the legend:
 * counted from the schools lit, so a count is only ever given for lights the
 * map shows, and none while nothing is lit.
 */

import { PUBLISHED_PATHS } from '../types/generated';
import type { ClosingsFile, DirectoryStamp, UtcInstant } from '../types/generated';
import {
  NOTHING_LIT,
  countStatuses,
  lightSchools,
  parseClosings,
  sameCounts,
  todayEverywhere,
} from './closings';
import type { LitSchools, StatusCounts } from './closings';
import type { Directory } from './directory';
import { wallClock, watchWake } from '../state/wake';
import type { WakeHost } from '../state/wake';
import { fetchJson } from './files';
import type { DataFiles, Fetch } from './files';

/** The parts of `window` the poller uses, so tests can hand it a fake. */
export interface LiveHost {
  readonly document: Pick<Document, 'visibilityState' | 'addEventListener' | 'removeEventListener'>;
  setInterval(handler: () => void, timeout: number): number;
  clearInterval(id: number | undefined): void;
}

export interface LiveOptions {
  readonly files: DataFiles;
  /** The directory a stamp names, or null; asked only when there are schools to light. */
  readonly directory: (stamp: DirectoryStamp) => Promise<Directory | null>;
  /** Called with the schools to light whenever they change. */
  readonly onLight: (lit: LitSchools) => void;
  /** Called with the shown file's generated_at whenever it changes; null when none is shown. */
  readonly onShown?: (generatedAt: UtcInstant | null) => void;
  /**
   * Called with how many schools are lit in each status whenever that
   * changes; null while none is lit (no file, none today, or overnight).
   */
  readonly onCounts?: (counts: StatusCounts | null) => void;
  readonly fetch?: Fetch;
  readonly now?: () => Date;
  /** performance.now(), the glow layer's clock. */
  readonly clock?: () => number;
  /** How often to read the file again while the page is visible. Default LIVE_POLL_MS. */
  readonly pollMs?: number;
  readonly host?: LiveHost;
}

export interface Live {
  /** Reads the file again and relights. Resolves when done; never rejects. */
  refresh(): Promise<void>;
  /** The last file read, or null. */
  readonly closings: ClosingsFile | null;
  stop(): void;
}

/** How often the live files are read again while the page is visible: a minute. */
export const LIVE_POLL_MS = 60_000;

/**
 * How far past the device's clock the worker's kept copy of the closings file
 * may be stamped and still stand against an older copy: ten minutes. The
 * ingest stamps no file more than a minute ahead (S8 spec G12c), and a
 * device's clock may run a few minutes slow. A kept copy stamped further ahead
 * says one of the two clocks is wrong. When it is also far past the network's
 * answer (LIVE_AHEAD_OF_ANSWER_MS), the publisher's was: kept on that stamp,
 * it would stand in for every later file, across reloads, so the worker gives
 * it up for the answer (pwa/config.ts keepNewerClosings). Otherwise the
 * device's clock is slow, and the kept copy stands, newer only.
 *
 * The page's own reader sets no file against the device's clock: a clock set
 * back, or one that runs slow, never holds a newer file off (newerClosings).
 */
export const LIVE_AHEAD_MS = 10 * 60_000;

/**
 * How far past the network's answer the worker's kept copy may be stamped and
 * still stand against it, when the kept copy is also past the device's clock
 * (LIVE_AHEAD_MS): an hour. An edge behind serves a copy at most its cache
 * life (ten minutes on GitHub Pages) older than the newest, so a sound kept
 * copy is never this far past a sound answer, on any device clock; one that
 * is, is stamped by a publisher clock that was wrong.
 */
export const LIVE_AHEAD_OF_ANSWER_MS = 60 * 60_000;

/**
 * How long one read of the closings file may take before it is given up, so
 * a read that never settles cannot hold every later one: well under a poll.
 */
export const LIVE_READ_TIMEOUT_MS = 20_000;

/**
 * The closings file to show: `next` when it is newer than `prev` (or there
 * is no `prev`), else `prev`. Newer is a later generated_at, which, as a
 * UtcInstant of fixed form, compares as text. A file no newer than the one
 * shown, a copy a cache or an edge still serves, or a failed read (null),
 * leaves `prev` shown.
 *
 * Only the files' own stamps, from the ingest's one clock, are compared; the
 * device's clock has no say. A device clock set back, or one that runs slow,
 * so never holds off a newer file (a blank still darkens the map), and a file
 * is never given up for an older one (a closing called off never lights
 * again). The update line, not this rule, says how old the file is.
 */
export function newerClosings(
  prev: ClosingsFile | null,
  next: ClosingsFile | null,
): ClosingsFile | null {
  if (next === null) return prev;
  return prev === null || next.generated_at > prev.generated_at ? next : prev;
}

/**
 * The predictions file to show: `next` when it was made later than `prev` (or
 * there is no `prev`), else `prev`, by the files' own generated_at. A copy an
 * edge still serves after a newer one was read (S8-A saw a Fastly node serve
 * the old copy 15 s after a deploy), or a failed read (null), never steps an
 * open panel back to a superseded chance.
 */
export function newerPredictions<T extends { readonly generated_at: string }>(
  prev: T | null,
  next: T | null,
): T | null {
  if (next === null) return prev;
  if (prev === null) return next;
  return Date.parse(next.generated_at) > Date.parse(prev.generated_at) ? next : prev;
}

/**
 * How often an open panel reads live/covered.json and live/predictions.json
 * again: five minutes, as every live file was read before the closings file
 * was read each minute. S8 publishes neither (spec section 1), so their reads
 * stay off the minute's one read of the closings file (spec section 13).
 */
export const LIVE_SIDE_POLL_MS = 5 * 60_000;

/**
 * The share of a poll within which a read gets the file the last read took.
 * The map and an open panel each poll once a period, at their own offsets;
 * whichever asks first once this much of a period has passed reads for both,
 * so the two make one read a period at any offset, with room for timers
 * that fire late.
 */
const READ_REUSE = 0.9;

/** The page's clocks: the wall clock, and one that only moves forward. */
export interface Clocks {
  /** Date.now(): what the device says the time is; it can be set back or jump ahead. */
  readonly wall: () => number;
  /**
   * performance.now(): only moves forward, whatever the device's clock is set
   * to, though it may stand still while the device sleeps.
   */
  readonly monotonic: () => number;
}

const PAGE_CLOCKS: Clocks = { wall: wallClock, monotonic: () => performance.now() };

/**
 * Whether `ms` or more have passed since `since` (both clocks' readings): by
 * the clock that only moves forward, or by the wall clock, which also counts
 * the time the device slept. A wall clock set back counts nothing.
 */
function elapsed(clocks: Clocks, since: { wall: number; monotonic: number }, ms: number): boolean {
  return clocks.monotonic() - since.monotonic >= ms || clocks.wall() - since.wall >= ms;
}

/**
 * A gate that is open at the first ask, and then once most of `ms`
 * (READ_REUSE of it) has passed since it was last open, by the clock that
 * only moves forward or by the wall clock (which counts a sleep). Asked at
 * each poll, it opens every `ms` the polls step through, whatever their
 * offset from the first ask and however late their timers fire, never a
 * poll later.
 */
export function dueEvery(ms: number, clocks: Clocks = PAGE_CLOCKS): () => boolean {
  let last: { wall: number; monotonic: number } | null = null;
  return () => {
    if (last !== null && !elapsed(clocks, last, ms * READ_REUSE)) return false;
    last = { wall: clocks.wall(), monotonic: clocks.monotonic() };
    return true;
  };
}

/**
 * What a poll keeps time by: the reader it reads through, which the map and
 * every open panel share. Each read that goes out through it, whoever made
 * it, runs every paced poll's own work at once (the poll's read joins the one
 * on its way, so no second request goes out) and starts every poll's period
 * again. So no read is more than a period after the last while the page is
 * seen, the polls still make one read a period between them, and each poll's
 * own work runs at least once a period: it works out its view again against
 * the time, which moves on even when the file does not, and reads its own
 * files when they are due.
 */
export interface PollPace {
  /** Hears each read that goes out, as it begins. Returns the function that stops it. */
  onRead(listener: () => void): () => void;
  /**
   * Gives up what the last read holds, as the device comes back online: a
   * read on its way is given up (it may hang on the lost connection) and
   * the next ask reads. `cause` is the event that called for it: each
   * poll's handler hands on the same event, and only the first gives up.
   */
  renew(cause?: object): void;
}

export interface PollOptions {
  /** The window, or a fake for tests. */
  readonly host?: Pick<LiveHost, 'document' | 'setInterval' | 'clearInterval'> &
    Partial<Pick<WakeHost, 'addEventListener' | 'removeEventListener'>>;
  readonly clocks?: Clocks;
  /** The reader the poll reads through, which runs and paces it (PollPace). */
  readonly pace?: PollPace;
}

/**
 * Calls `read` every `ms` while the page is visible, and at once when it is
 * shown again, or wakes, `ms` or more after the last call, by the clock that
 * only moves forward or by the wall clock (which counts a sleep). A device
 * clock set back never holds a read off. When the device comes back online,
 * it reads at once, past what `pace` holds.
 *
 * The next call comes a full `ms` after the last one, however it came: a
 * call made on show or wake starts the period again. With `pace`, every read
 * that goes out through it, from this poll or another, calls `read` (while
 * visible) and starts the period again. Returns the function that stops it.
 */
export function pollWhileVisible(
  read: () => void,
  ms: number,
  options: PollOptions = {},
): () => void {
  const host = options.host ?? window;
  const clocks = options.clocks ?? PAGE_CLOCKS;
  const { pace } = options;
  let last = { wall: clocks.wall(), monotonic: clocks.monotonic() };
  /** Whether `read` is running: a read it makes through `pace` is its own, not another's. */
  let reading = false;
  const visible = (): boolean => host.document.visibilityState === 'visible';
  const run = (): void => {
    last = { wall: clocks.wall(), monotonic: clocks.monotonic() };
    reading = true;
    try {
      read();
    } finally {
      reading = false;
    }
  };
  const tick = (): void => {
    if (visible()) run();
  };
  let interval = host.setInterval(tick, ms);
  /** Starts the period again from now. */
  const restart = (): void => {
    host.clearInterval(interval);
    interval = host.setInterval(tick, ms);
  };
  const due = (): void => {
    if (!visible() || !elapsed(clocks, last, ms)) return;
    run();
    restart();
  };
  // Back online: what is held may be older than a read could now get.
  const online = (event: Event): void => {
    if (!visible()) return;
    pace?.renew(event);
    run();
    restart();
  };
  let stopped = false;
  // Another's read: this poll's own work runs too, its read sharing the one on its way. Run
  // once the read has begun, never inside the asker's own call, whatever it was doing.
  const paced = (): void => {
    restart();
    if (reading) return;
    queueMicrotask(() => {
      if (!stopped && visible()) run();
    });
  };
  host.document.addEventListener('visibilitychange', due);
  host.addEventListener?.('online', online);
  const stopWake = watchWake(due, host, clocks.wall);
  const stopPace = pace?.onRead(paced) ?? (() => undefined);
  return () => {
    stopped = true;
    host.clearInterval(interval);
    host.document.removeEventListener('visibilitychange', due);
    host.removeEventListener?.('online', online);
    stopWake();
    stopPace();
  };
}

export interface ClosingsReadOptions {
  readonly force?: boolean;
  readonly fetch?: Fetch | undefined;
  /** The poll the asker reads at; LIVE_POLL_MS when not given. */
  readonly pollMs?: number | undefined;
}

/** The page's one reader of live/closings.json: the map's, and every panel's. */
export interface ClosingsReader extends PollPace {
  /** The newest file taken so far, or null. */
  readonly current: ClosingsFile | null;
  /**
   * Reads the file, and resolves to the newest file taken so far. A read
   * asked for while another is on its way gets that one's; one asked for
   * within most of a poll (READ_REUSE of `pollMs`) of the last read's start gets what is
   * held, unless `force` (the worker said it holds a newer copy). Never
   * rejects: a read that fails, or takes longer than LIVE_READ_TIMEOUT_MS,
   * leaves what is held. A read on its way that began longer ago than that,
   * by the wall clock (a device that slept) or the forward one, is given up
   * when another is asked for, and a new one made.
   */
  read(options?: ClosingsReadOptions): Promise<ClosingsFile | null>;
  /** Hears each newer file taken, whoever read it. Returns the function that stops it. */
  subscribe(listener: (file: ClosingsFile) => void): () => void;
}

export interface ClosingsReaderInit {
  readonly clocks?: Clocks;
  readonly timeoutMs?: number;
}

const readers = new WeakMap<DataFiles, ClosingsReader>();

/**
 * The reader of live/closings.json for `files`, one for the page: the map
 * and the panels are all handed the page's one DataFiles (app/data.ts), so
 * they share one newest file and one poll. Each file it takes is newer than
 * the last (newerClosings). `init` applies when the reader is made.
 */
export function closingsReader(files: DataFiles, init: ClosingsReaderInit = {}): ClosingsReader {
  const known = readers.get(files);
  if (known !== undefined) return known;
  const clocks = init.clocks ?? PAGE_CLOCKS;
  const timeoutMs = init.timeoutMs ?? LIVE_READ_TIMEOUT_MS;
  let current: ClosingsFile | null = null;
  /** The read on its way, when it began by both clocks, and how to give it up; none at rest. */
  let inflight: {
    readonly done: Promise<void>;
    readonly began: { wall: number; monotonic: number };
    readonly giveUp: () => void;
  } | null = null;
  /** When the last read began, by both clocks; none yet. */
  let began: { wall: number; monotonic: number } | null = null;
  const listeners = new Set<(file: ClosingsFile) => void>();
  const readListeners = new Set<() => void>();
  /** The event the last renew was for. */
  let renewedFor: object | undefined;

  const take = (file: ClosingsFile | null): void => {
    const next = newerClosings(current, file);
    if (next === current || next === null) return;
    current = next;
    for (const listener of [...listeners]) listener(next);
  };

  const readNow = (fetch: Fetch | undefined): Promise<void> => {
    const at = { wall: clocks.wall(), monotonic: clocks.monotonic() };
    began = at;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let giveUp = (): void => undefined;
    const settle = (): void => {
      clearTimeout(timer);
      if (inflight?.done === done) inflight = null;
    };
    const done: Promise<void> = Promise.race([
      // no-cache: past the HTTP cache to the server (or to the worker's revalidation).
      fetchJson(
        files,
        PUBLISHED_PATHS.closings,
        { cache: 'no-cache', signal: controller.signal },
        fetch,
      ).then(parseClosings),
      new Promise<null>((resolve) => {
        giveUp = () => {
          controller.abort();
          resolve(null);
        };
        timer = setTimeout(giveUp, timeoutMs);
      }),
    ]).then(
      (file) => {
        settle();
        take(file);
      },
      // Reading is best effort; what is held stays.
      settle,
    );
    inflight = { done, began: at, giveUp };
    for (const listener of [...readListeners]) listener();
    return done;
  };

  const reader: ClosingsReader = {
    get current() {
      return current;
    },
    read(options = {}) {
      if (!files.has(PUBLISHED_PATHS.closings)) return Promise.resolve(null);
      const force = options.force === true;
      // A read that began longer ago than it may take, by either clock, is given up: its
      // timer may not have counted a sleep, and its connection may not have survived one.
      if (inflight !== null && elapsed(clocks, inflight.began, timeoutMs)) {
        inflight.giveUp();
        inflight = null;
        began = null;
      }
      let reading: Promise<void> | null = inflight?.done ?? null;
      if (reading !== null) {
        if (force) reading = reading.then(() => readNow(options.fetch));
      } else if (
        force ||
        began === null ||
        elapsed(clocks, began, (options.pollMs ?? LIVE_POLL_MS) * READ_REUSE)
      ) {
        reading = readNow(options.fetch);
      }
      return reading === null ? Promise.resolve(current) : reading.then(() => current);
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    onRead(listener) {
      readListeners.add(listener);
      return () => {
        readListeners.delete(listener);
      };
    },
    renew(cause) {
      // Another poll's handler for the same event: the read it made since stands.
      if (cause !== undefined && cause === renewedFor) return;
      renewedFor = cause;
      // A read on its way began before the device came back, and may hang on the lost connection.
      inflight?.giveUp();
      inflight = null;
      began = null;
    },
  };
  readers.set(files, reader);
  return reader;
}

/** The absolute URL the page reads live/closings.json from, or null when the build has none. */
export function closingsUrl(files: DataFiles): string | null {
  return files.url(PUBLISHED_PATHS.closings);
}

export function startLive(options: LiveOptions): Live {
  const { files } = options;
  const now = options.now ?? (() => new Date());
  const clock = options.clock ?? (() => performance.now());
  const pollMs = options.pollMs ?? LIVE_POLL_MS;
  const host: LiveHost = options.host ?? window;

  const reader = closingsReader(files);
  let closings: ClosingsFile | null = null;
  let lit: ReadonlySet<number> | null = null;
  /** What the lit schools were worked out from: the file's time and the day. */
  let shownKey = '';
  let stopped = false;
  let running: Promise<void> | null = null;
  let again = false;
  /** Whether the read on its way, or the one asked for after it, must reach the network. */
  let force = false;
  /** The generated_at last passed to onShown. */
  let shownAt: UtcInstant | null = null;
  /** The counts last passed to onCounts. */
  let shownCounts: StatusCounts | null = null;

  const report = (generatedAt: UtcInstant | null): void => {
    if (generatedAt === shownAt) return;
    shownAt = generatedAt;
    options.onShown?.(generatedAt);
  };

  const reportCounts = (counts: StatusCounts | null): void => {
    if (sameCounts(counts, shownCounts)) return;
    shownCounts = counts;
    options.onCounts?.(counts);
  };

  const relight = async (file: ClosingsFile): Promise<void> => {
    const today = todayEverywhere(now());
    const key = `${file.generated_at} ${String(today)}`;
    if (key === shownKey) return;
    const group = file.days.find((item) => item.day === today);
    let next: LitSchools = NOTHING_LIT;
    // With no schools today there is nothing to read against the directory.
    let shown = group === undefined;
    /** Whether the directory was still not read when its wait ran out: asked again next time. */
    let late = false;
    if (group !== undefined) {
      // A directory read that never settles must not hold every later file: past the read's
      // limit the map goes dark for this file, and lights it as soon as the directory comes.
      const reading = options.directory(file.directory);
      const directory = await new Promise<Directory | null | 'late'>((resolve, reject) => {
        const timer = setTimeout(() => {
          resolve('late');
          // Come at last: light the file with it, if it is still the one to show.
          reading.then(
            () => {
              if (!stopped && file === closings) void update(false);
            },
            () => undefined,
          );
        }, LIVE_READ_TIMEOUT_MS);
        reading.then(
          (read) => {
            clearTimeout(timer);
            resolve(read);
          },
          (error: unknown) => {
            clearTimeout(timer);
            reject(error instanceof Error ? error : new Error(String(error)));
          },
        );
      });
      if (stopped || file !== closings) return;
      late = directory === 'late';
      if (directory !== null && directory !== 'late') {
        next = lightSchools(file, directory, { now: now(), previous: lit, bornMs: clock() });
        shown = true;
      }
    }
    if (stopped) return;
    shownKey = late ? '' : key;
    report(shown ? file.generated_at : null);
    // Counted from the schools lit, so the counts are always the map's own.
    reportCounts(countStatuses(next));
    // Nothing lit before and nothing now: the layer has nothing to change.
    if (lit === null && next.schools.size === 0) return;
    lit = next.schools;
    options.onLight(next);
  };

  const read = async (): Promise<void> => {
    const forced = force;
    force = false;
    // The newest file the page has taken, the map's own reads, a panel's, or this one.
    const file = await reader.read({ force: forced, fetch: options.fetch, pollMs });
    if (stopped) return;
    closings = newerClosings(closings, file);
    if (closings !== null) await relight(closings);
  };

  /** Reads and relights; `network` reads past what the reader holds (refresh). */
  const update = (network: boolean): Promise<void> => {
    if (stopped || !files.has(PUBLISHED_PATHS.closings)) return Promise.resolve();
    if (network) force = true;
    if (running !== null) {
      again = true;
      // Asked while a read is on its way: the reader gives that read up if it began longer
      // ago than it may take (the device slept since), so this one is not held behind it.
      void reader.read({ fetch: options.fetch, pollMs });
      return running;
    }
    // Functions, so each check reads the flags afresh after an await.
    const more = (): boolean => again && !stopped;
    const run = async (): Promise<void> => {
      try {
        do {
          again = false;
          await read();
        } while (more());
      } catch {
        // Reading is best effort; what is shown stays.
      } finally {
        running = null;
      }
    };
    running = run();
    return running;
  };
  const refresh = (): Promise<void> => update(true);

  if (!files.has(PUBLISHED_PATHS.closings)) {
    return {
      refresh: () => Promise.resolve(),
      get closings() {
        return null;
      },
      stop: () => undefined,
    };
  }

  // A newer file a panel read: light it now, not at the next poll.
  const stopHearing = reader.subscribe((file) => {
    if (file !== closings) void update(false);
  });
  // Read again while the page is seen, and as soon as it is seen again.
  const stopPolling = pollWhileVisible(() => void update(false), pollMs, { host, pace: reader });
  void update(false);

  return {
    refresh,
    get closings() {
      return closings;
    },
    stop() {
      stopped = true;
      stopPolling();
      stopHearing();
    },
  };
}
