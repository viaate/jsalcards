/**
 * Keeps the glow in step with live/closings.json.
 *
 * The file is read at start, again every few minutes while the page is
 * visible, when the page comes back into view, and whenever the service
 * worker says it holds a newer copy. The schools lit are worked out afresh
 * each time, since "today" moves on even when the file does not. Schools that
 * light up after the first read pulse in once.
 *
 * A build without the file never asks for it. A read that fails keeps what
 * is shown: the last file read is still true as of its own time.
 *
 * `onShown` hears the generated_at of the file the lit schools come from, for
 * the update time: a file is shown once it has been read against its
 * directory, or when it has no schools today. A file whose directory cannot be
 * had shows nothing, so no time is given for it either.
 */

import { PUBLISHED_PATHS } from '../types/generated';
import type { ClosingsFile, DirectoryStamp, UtcInstant } from '../types/generated';
import { NOTHING_LIT, lightSchools, parseClosings, todayEverywhere } from './closings';
import type { LitSchools } from './closings';
import type { Directory } from './directory';
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
  readonly fetch?: Fetch;
  readonly now?: () => Date;
  /** performance.now(), the glow layer's clock. */
  readonly clock?: () => number;
  /** How often to read the file again while the page is visible. Default 5 minutes. */
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

export const LIVE_POLL_MS = 5 * 60_000;

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

  let closings: ClosingsFile | null = null;
  let lit: ReadonlySet<number> | null = null;
  /** What the lit schools were worked out from: the file's time and the day. */
  let shownKey = '';
  let stopped = false;
  let running: Promise<void> | null = null;
  let again = false;
  let lastRead = -Infinity;
  /** The generated_at last passed to onShown. */
  let shownAt: UtcInstant | null = null;

  const report = (generatedAt: UtcInstant | null): void => {
    if (generatedAt === shownAt) return;
    shownAt = generatedAt;
    options.onShown?.(generatedAt);
  };

  const relight = async (file: ClosingsFile): Promise<void> => {
    const today = todayEverywhere(now());
    const key = `${file.generated_at} ${String(today)}`;
    if (key === shownKey) return;
    const group = file.days.find((item) => item.day === today);
    let next: LitSchools = NOTHING_LIT;
    // With no schools today there is nothing to read against the directory.
    let shown = group === undefined;
    if (group !== undefined) {
      const directory = await options.directory(file.directory);
      if (stopped || file !== closings) return;
      if (directory !== null) {
        next = lightSchools(file, directory, { now: now(), previous: lit, bornMs: clock() });
        shown = true;
      }
    }
    if (stopped) return;
    shownKey = key;
    report(shown ? file.generated_at : null);
    // Nothing lit before and nothing now: the layer has nothing to change.
    if (lit === null && next.schools.size === 0) return;
    lit = next.schools;
    options.onLight(next);
  };

  const read = async (): Promise<void> => {
    lastRead = Date.now();
    // no-cache: past the HTTP cache to the server (or to the worker's revalidation).
    const file = parseClosings(
      await fetchJson(files, PUBLISHED_PATHS.closings, { cache: 'no-cache' }, options.fetch),
    );
    if (stopped) return;
    if (file !== null && file.generated_at !== closings?.generated_at) closings = file;
    if (closings !== null) await relight(closings);
  };

  const refresh = (): Promise<void> => {
    if (stopped || !files.has(PUBLISHED_PATHS.closings)) return Promise.resolve();
    if (running !== null) {
      again = true;
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

  if (!files.has(PUBLISHED_PATHS.closings)) {
    return {
      refresh: () => Promise.resolve(),
      get closings() {
        return null;
      },
      stop: () => undefined,
    };
  }

  const visible = (): boolean => host.document.visibilityState === 'visible';
  const interval = host.setInterval(() => {
    if (visible()) void refresh();
  }, pollMs);
  const onVisibility = (): void => {
    if (visible() && Date.now() - lastRead >= pollMs) void refresh();
  };
  host.document.addEventListener('visibilitychange', onVisibility);
  void refresh();

  return {
    refresh,
    get closings() {
      return closings;
    },
    stop() {
      stopped = true;
      host.clearInterval(interval);
      host.document.removeEventListener('visibilitychange', onVisibility);
    },
  };
}
