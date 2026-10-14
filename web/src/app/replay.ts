/**
 * Replay mode: a past school day on the map in place of live.
 *
 * Entering is two-phase. The day's file is read, checked and lit against the
 * directory first, with nothing on screen changed; only once all of that
 * succeeds does the page switch, in one task: live is held (app/data.ts), the
 * replay's schools light, the update line and counts become the replay's, the
 * page is told the day, and the address gains `replay=<day>`. A day that
 * cannot be shown (not shipped, not read, another directory's, not yet over)
 * leaves the page as it was.
 *
 * Each enter or exit takes a ticket; a read that comes back under an older
 * one is dropped, so the page always ends in the state last asked for.
 * Entering and leaving push a history entry each, so Back and Forward move
 * between live and the replay; Back and Forward themselves add none. The page
 * (app/boot.ts) hears them from its start, and passes each on as sync() once
 * this code is in, so none is missed while it loads.
 *
 * Loaded on the first replay asked for: a menu row, or a link with replay=.
 * Each day is read once a page: the menu warms its first days as its replay
 * page opens, and any it is about to be pressed, so a press shows the day
 * without waiting for its file; one that could not be shown is read again
 * the next time it is asked for.
 */

import { filterLit } from '../data/closings';
import type { LitSchools, StatusCounts } from '../data/closings';
import { countShown } from '../data/closings';
import { fetchJson } from '../data/files';
import type { Fetch } from '../data/files';
import { isPast, isReplayDay, lightReplay, parseReplay, replayLookup } from '../data/replay';
import type { ReplayLookup, ReplayOn } from '../data/replay';
import type { Component } from 'svelte';

import type { Glow } from '../map/glow-mount';
import type { MapFilter } from '../state/filter';
import type { LocalDate, UtcInstant } from '../types/generated';
import type { AppData } from './data';

/** The query parameter a replay is kept in. */
export const REPLAY_PARAM = 'replay';

/** A replay read and lit, ready to show. */
export interface Opened {
  readonly day: LocalDate;
  readonly lit: LitSchools;
  readonly lookup: ReplayLookup;
}

/** The file of each replay day, under its plain name. */
export function replayPath(day: LocalDate): string {
  return `replays/${day}.json`;
}

/**
 * Reads a replay day and lights it against the directory it is stamped for;
 * null when this build does not ship it, it cannot be read, it breaks its
 * rules, it is for another directory, or its day is not over everywhere in
 * the US at `now`. Changes nothing.
 */
export async function openReplay(
  data: AppData,
  day: LocalDate,
  now: Date,
  fetchImpl?: Fetch,
): Promise<Opened | null> {
  if (!isReplayDay(day) || !isPast(day, now)) return null;
  const path = replayPath(day);
  if (!data.files.has(path)) return null;
  try {
    const replay = parseReplay(await fetchJson(data.files, path, {}, fetchImpl));
    if (replay?.id !== day) return null;
    const directory = await (await data.directories())?.get(replay.directory);
    if (directory === undefined || directory === null) return null;
    const lit = lightReplay(replay, directory);
    if (lit.status.length === 0) return null;
    return { day, lit, lookup: replayLookup(replay, directory) };
  } catch {
    return null;
  }
}

/** The replay shown now. */
export type Active = ReplayOn;

export interface ControllerOptions {
  /** Holds live (true) or lets it go (false): app/data.ts LiveGlow.hold. */
  readonly hold: (held: boolean) => void;
  readonly glow: Promise<Glow | null>;
  /** The menu's filter now. */
  readonly filter: () => MapFilter;
  /** Reads and lights a day: openReplay, bound to the page's data and clock. */
  readonly open: (day: LocalDate) => Promise<Opened | null>;
  /** The replay's counts, for the legend and the menu: delivered only while it is still on. */
  readonly onCounts: (day: LocalDate, counts: StatusCounts | null) => void;
  /** Clears the update line as a replay comes on. */
  readonly onUpdated: (generatedAt: UtcInstant | null) => void;
  /** The day shown, or null for live: called as the page switches. */
  readonly onReplay: (active: Active | null) => void;
  /** Defaults to `window`. */
  readonly host?: Pick<Window, 'location' | 'history'>;
}

export interface Controller {
  /**
   * Shows `day`: `push` adds a history entry; `boot` (a link opened with it)
   * and `history` (Back or Forward) add none, and if it cannot be shown the
   * address is put back to what is: replay= stripped, or the day still on.
   * Resolves to whether it is on.
   */
  enter(day: LocalDate, how: 'push' | 'boot' | 'history'): Promise<boolean>;
  /** Back to live; `history` touches the address not at all. */
  exit(how?: 'push' | 'history'): void;
  /** Follows the address: the day replay= names, or live (Back and Forward, heard by the page). */
  sync(): void;
  /**
   * Reads and lights `day` ahead of a press on it, with nothing on screen
   * changed; resolves to whether it could be shown.
   */
  warm(day: LocalDate): Promise<boolean>;
  /** The menu's filter changed: the replay shows what it keeps. */
  filter(filter: MapFilter): void;
  /** The replay shown now, or null. */
  readonly active: Active | null;
  stop(): void;
}

/** `href` with replay= set to `day`, or removed for null; everything else as it is. */
export function replayHref(href: string, day: LocalDate | null): string {
  const url = new URL(href);
  if (day === null) url.searchParams.delete(REPLAY_PARAM);
  else url.searchParams.set(REPLAY_PARAM, day);
  return url.href;
}

/** The day the address asks for, or null; malformed days are kept as asked, to be refused. */
export function replayAsked(href: string): string | null {
  return new URL(href).searchParams.get(REPLAY_PARAM);
}

export function createController(options: ControllerOptions): Controller {
  const host = options.host ?? window;
  let ticket = 0;
  let shown: { readonly day: LocalDate; readonly lit: LitSchools; lookup: ReplayLookup } | null =
    null;

  const write = (day: LocalDate | null, mode: 'push' | 'replace'): void => {
    const target = replayHref(host.location.href, day);
    if (target === host.location.href) return;
    try {
      if (mode === 'push') host.history.pushState(null, '', target);
      else host.history.replaceState(host.history.state, '', target);
    } catch {
      // A history the browser refuses to write (rate limits): the page is right, the address waits.
    }
  };

  const paint = (lit: LitSchools): void => {
    const picked = filterLit(lit, options.filter(), false);
    void options.glow.then((layer) => {
      if (shown?.lit === lit) layer?.light(picked);
    });
  };

  const show = (opened: Opened): void => {
    options.hold(true);
    shown = { day: opened.day, lit: opened.lit, lookup: opened.lookup };
    paint(opened.lit);
    options.onUpdated(null);
    options.onCounts(opened.day, countShown(opened.lit, options.filter()));
    options.onReplay({ day: opened.day, lookup: opened.lookup });
  };

  const controller: Controller = {
    get active() {
      return shown === null ? null : { day: shown.day, lookup: shown.lookup };
    },
    async enter(day, how) {
      const mine = ++ticket;
      if (shown?.day === day) {
        if (how === 'push') write(day, 'push');
        return true;
      }
      const opened = await options.open(day).catch(() => null);
      if (mine !== ticket) return false;
      if (opened === null) {
        // Live is never left held with no replay shown (a link's day, held for from the start).
        if (shown === null) options.hold(false);
        // A link's day, or Back or Forward onto one: the address goes back to what is shown.
        if (how !== 'push') write(shown?.day ?? null, 'replace');
        return false;
      }
      show(opened);
      if (how === 'push') write(day, 'push');
      return true;
    },
    sync() {
      const asked = replayAsked(host.location.href);
      if (asked === null) controller.exit('history');
      else if (asked !== shown?.day) void controller.enter(asked, 'history');
    },
    warm(day) {
      return options.open(day).then(
        (opened) => opened !== null,
        () => false,
      );
    },
    exit(how = 'push') {
      ticket += 1;
      if (shown === null) {
        options.hold(false);
        if (how === 'push') write(null, 'replace');
        return;
      }
      shown = null;
      options.onReplay(null);
      options.hold(false);
      if (how === 'push') write(null, 'push');
    },
    filter(next) {
      if (shown === null) return;
      paint(shown.lit);
      options.onCounts(shown.day, countShown(shown.lit, next));
    },
    stop() {
      ticket += 1;
    },
  };
  return controller;
}

/** The bar that names the day in the update time's place (ui/ReplayBar.svelte). */
export type ReplayBar = Component<{ day: LocalDate; onexit: () => void }>;

export interface StartOptions {
  readonly data: AppData;
  readonly glow: Promise<Glow | null>;
  readonly hold: (held: boolean) => void;
  readonly filter: () => MapFilter;
  /** Passes counts on once the page's face is in, if `still` holds then. */
  readonly deliver: (counts: StatusCounts | null, still: () => boolean) => void;
  readonly onUpdated?: ((generatedAt: UtcInstant | null) => void) | undefined;
  /** The day shown, and the day with the bar that names it for the page; null for live. */
  readonly onReplay: (
    active: Active | null,
    shown: { readonly day: LocalDate; readonly bar: ReplayBar } | null,
  ) => void;
}

/**
 * `open`, each day read once: a day it shows is kept for the page's life, and
 * one it could not show (offline, a deploy in flight) is read again next time.
 */
export function readOnce(
  open: (day: LocalDate) => Promise<Opened | null>,
): (day: LocalDate) => Promise<Opened | null> {
  const kept = new Map<LocalDate, Promise<Opened | null>>();
  return (day) => {
    let reading = kept.get(day);
    if (reading === undefined) {
      reading = open(day).then(
        (opened) => {
          if (opened === null) kept.delete(day);
          return opened;
        },
        () => {
          kept.delete(day);
          return null;
        },
      );
      kept.set(day, reading);
    }
    return reading;
  };
}

/**
 * Replay mode for the page (app/boot.ts): days read against its data and
 * clock, the bar that names a day loaded with it, so no day is shown
 * without it, and each day's counts passed on only while it is still on.
 */
export function startReplays(options: StartOptions): Controller {
  let bar: ReplayBar | null = null;
  const read = readOnce((day) => openReplay(options.data, day, new Date()));
  const controller: Controller = createController({
    hold: options.hold,
    glow: options.glow,
    filter: options.filter,
    // The bar's code once it is in, so a later press waits on no task: a busy page (a frame
    // being drawn) would hold a fresh import's answer back.
    open: async (day) => {
      const [opened, loaded] = await Promise.all([
        read(day),
        bar ?? import('../ui/ReplayBar.svelte').then((module) => module.default),
      ]);
      bar = loaded;
      return opened;
    },
    onCounts: (day, counts) => {
      options.deliver(counts, () => controller.active?.day === day);
    },
    onUpdated: (generatedAt) => options.onUpdated?.(generatedAt),
    onReplay: (active) => {
      if (bar !== null) options.onReplay(active, active === null ? null : { day: active.day, bar });
    },
  });
  return controller;
}
