/**
 * The school a search pick or a link opens: what its detail panel shows,
 * worked out from the data this build ships and nothing else.
 *
 * `watchSchool` reads the school's record (src/data/details.ts), then the
 * live files (closings, covered, predictions) this build ships, and hands
 * the panel a view each time something new is known: at once from what a
 * search pick already knows (the name and the town), then the record, then
 * the day. The live files are read again every few minutes while the panel
 * is open, and the view is worked out again as the day moves on.
 *
 * `schoolView` turns what is known into the panel's lines, every word from
 * src/copy.ts or the directory itself. A status line shows only where the
 * live files state one (or confirm the school open today), on the school's
 * own today (its district's time zone, from the predictions file); a chance
 * only where the district has a forecast for a day not yet under way, and
 * nothing where the files cannot say for now. A day's chance never shows
 * beside a status the school decided for that day (closed, delayed, remote,
 * early dismissal): the fact beats the forecast. "Open today" is no decision,
 * only that no closing is posted yet, and the chance stays beside it.
 */

import { DISTRICT_NAME_FIXES, SCHOOL_NAME_FIXES } from 'virtual:snowlight/school-names';

import { REASON_KEYS, STATUS_KEYS, copy, format } from '../copy';
import type { StatusKey } from '../copy';
import { parseClosings } from '../data/closings';
import { createDetailsSource } from '../data/details';
import { DETAILS_INDEX_PATH } from '../data/details-format';
import type { DetailsSource, SchoolRecord } from '../data/details';
import { fetchJson } from '../data/files';
import type { DataFiles } from '../data/files';
import { LIVE_POLL_MS } from '../data/live';
import {
  NO_STATUS,
  parseCovered,
  parsePredictions,
  schoolOutlook,
  schoolStatus,
} from '../data/school-day';
import type { Outlook, SchoolStatus, StatusRow } from '../data/school-day';
import type { Directory } from '../data/directory';
import { casedName, displayName } from '../text/names';
import { stateOfId } from '../text/school-names';
import { PUBLISHED_PATHS, Status } from '../types/generated';
import type {
  ClosingsFile,
  CoveredFile,
  DirectoryStamp,
  PredictionsFile,
  Reason,
  SchoolId,
} from '../types/generated';
import { chanceView, shortDistrictName } from './chance';
import type { ChanceView, Names } from './chance';

/** What a search pick already knows about a school: its shown name and its town. */
export interface SchoolHint {
  readonly id: SchoolId;
  readonly name: string;
  /** "Kansas City, MO", or ''. */
  readonly sub: string;
}

/** One line of the status block. */
export interface StatusLineView {
  /** The status's key, for its glyph and color; "open" for a school confirmed open. */
  readonly tone: StatusKey | 'open';
  /** "Closed today", "Delayed start tomorrow", "Open today". */
  readonly headline: string;
  /** "2-hour delay · Starts at 10:00 AM", or null. */
  readonly detail: string | null;
  /** "Winter storm · Posted 5:12 AM", or null. */
  readonly note: string | null;
}

/** A school near this one, as the panel lists it. */
export interface NearbyView {
  readonly id: SchoolId;
  /** Its name as the map shows it. */
  readonly name: string;
  /** "0.4 mi". */
  readonly distance: string;
  /** Its status today, where the live file states one; null otherwise. */
  readonly tone: StatusKey | null;
  /** Where it is, for the map to go there. */
  readonly lon: number;
  readonly lat: number;
}

/** One fact about the school, with its label: a value on one or more lines. */
export interface FactView {
  readonly label: string;
  readonly lines: readonly string[];
  /** A link the value opens (a phone number's tel: link), or null. */
  readonly href: string | null;
}

/** Everything the panel shows, as text. */
export interface SchoolView {
  readonly id: SchoolId;
  /** The school's name, as the map and search show it, up to a campus written after it. */
  readonly name: string;
  /** The campus, from after a spaced dash ("Wornall Campus"), or null. */
  readonly campus: string | null;
  /** "Private school · PK–12", "Public school · K–5", …; null until the record is read. */
  readonly kind: string | null;
  /** "Kansas City, MO · Jackson County", or null. */
  readonly place: string | null;
  /** The status block's lines, today first; empty when the files state nothing. */
  readonly status: readonly StatusLineView[];
  /**
   * The chance section (app/chance.ts): the chance of no school for the first
   * day not decided or under way, with the status lines above it; null when
   * there is no chance to give, and the panel shows the status lines alone.
   */
  readonly chance: ChanceView | null;
  readonly facts: readonly FactView[];
  /** The schools nearest it, nearest first; empty until its record is read, or where none is near. */
  readonly nearby: readonly NearbyView[];
  /** True until the school's record is read. */
  readonly loading: boolean;
}

/** Where a name's campus starts: after a spaced dash, as the map's labels break it (schools.ts). */
const CAMPUS_MARK = ' - ';
const DOT = ' · ';

function statusKey(status: Status): StatusKey {
  return STATUS_KEYS[status] ?? 'closed';
}

function reasonName(reason: Reason): string | null {
  const key = REASON_KEYS[reason];
  return key === undefined ? null : copy.reason[key];
}

/** The shown name and its campus, cut where the map's label breaks it. */
function splitName(shown: string): { name: string; campus: string | null } {
  const cut = shown.indexOf(CAMPUS_MARK);
  if (cut <= 0) return { name: shown, campus: null };
  const campus = shown.slice(cut + CAMPUS_MARK.length).trim();
  return campus === '' ? { name: shown, campus: null } : { name: shown.slice(0, cut), campus };
}

/** What the school is, and its grades: "Private school · PK–12". */
function kindOf(record: SchoolRecord): string {
  const kind = record.private
    ? copy.detail.privateSchool
    : record.virtual
      ? copy.detail.virtualSchool
      : record.charter
        ? copy.detail.charterSchool
        : copy.detail.publicSchool;
  if (record.grades === null) return kind;
  try {
    return `${kind}${DOT}${format.grades(record.grades.low, record.grades.high)}`;
  } catch {
    // A grade code the page does not know: the kind alone rather than wrong grades.
    return kind;
  }
}

function townOf(record: SchoolRecord): string | null {
  return record.city === null ? null : `${casedName(record.city)}, ${record.state}`;
}

function statusLine(
  row: StatusRow,
  day: 'today' | 'tomorrow',
  now: Date,
  timeZone: string,
): StatusLineView {
  const key = statusKey(row.status);
  const detail =
    row.status === Status.delayed
      ? format.delay(row.shiftMinutes, row.clockMinute)
      : row.status === Status.early_dismissal
        ? format.dismissal(row.shiftMinutes, row.clockMinute)
        : null;
  const notes: string[] = [];
  const reason = row.reason === null ? null : reasonName(row.reason);
  if (reason !== null) notes.push(reason);
  if (row.announcedAt !== null) notes.push(format.posted(row.announcedAt, timeZone, now));
  return {
    tone: key,
    headline: copy.statusLine[key][day],
    detail,
    note: notes.length > 0 ? notes.join(DOT) : null,
  };
}

function statusLines(status: SchoolStatus, now: Date, timeZone: string): StatusLineView[] {
  const lines: StatusLineView[] = [];
  if (status.today === 'open') {
    lines.push({ tone: 'open', headline: copy.open.today, detail: null, note: null });
  } else if (status.today !== null) {
    lines.push(statusLine(status.today, 'today', now, timeZone));
  }
  if (status.tomorrow !== null) lines.push(statusLine(status.tomorrow, 'tomorrow', now, timeZone));
  return lines;
}

function factsOf(record: SchoolRecord): FactView[] {
  const facts: FactView[] = [];
  if (record.district !== null) {
    const { id, name } = record.district;
    facts.push({
      label: copy.detail.district,
      lines: [
        displayName(name, { state: stateOfId(id), district: true }, DISTRICT_NAME_FIXES[id] ?? {}),
      ],
      href: null,
    });
  }
  if (record.enrollment !== null && record.enrollment > 0) {
    facts.push({
      label: copy.detail.students,
      lines: [format.number(record.enrollment)],
      href: null,
    });
  }
  const town = townOf(record);
  const address = [
    ...(record.street === null ? [] : [casedName(record.street)]),
    ...(town === null ? [] : [record.zip === null ? town : `${town} ${record.zip}`]),
  ];
  if (address.length > 0) facts.push({ label: copy.detail.address, lines: address, href: null });
  if (record.phone !== null) {
    facts.push({
      label: copy.detail.phone,
      lines: [format.phone(record.phone)],
      href: `tel:+1${record.phone}`,
    });
  }
  return facts;
}

/** A district's name as the panel shows it, then short, as a family says it: "Shawnee Mission". */
function districtShortName(id: string, name: string): string {
  return shortDistrictName(
    displayName(name, { state: stateOfId(id), district: true }, DISTRICT_NAME_FIXES[id] ?? {}),
  );
}

/** The directory's district names and each school's district, for the chance section. */
export function namesOf(directory: Directory): Names {
  const { ids, names } = directory.meta.districts;
  const stamp: DirectoryStamp = {
    generated_on: directory.meta.generated_on,
    schools: directory.count,
    districts: ids.length,
  };
  const short = new Map<number, string | null>();
  return {
    stamp,
    districtOf: (school) => directory.district[school] ?? -1,
    name: (district) => {
      if (!short.has(district)) {
        const id = ids[district];
        const name = names[district];
        short.set(
          district,
          id === undefined || name === undefined ? null : districtShortName(id, name),
        );
      }
      return short.get(district) ?? null;
    },
  };
}

/** A school's name as the map and search show it. */
function shownName(id: string, name: string): string {
  return displayName(name, { state: stateOfId(id) }, SCHOOL_NAME_FIXES[id] ?? {});
}

function nearbyOf(record: SchoolRecord, closings: ClosingsFile | null, now: Date): NearbyView[] {
  return record.nearby.map((near) => {
    const today = schoolStatus({
      school: near.index,
      directory: record.directory,
      closings,
      covered: null,
      now,
    }).today;
    return {
      id: near.id,
      name: shownName(near.id, near.name),
      distance: format.miles(near.metres),
      tone: today === null || today === 'open' ? null : statusKey(today.status),
      lon: near.lon,
      lat: near.lat,
    };
  });
}

export interface ViewInput {
  readonly id: SchoolId;
  readonly hint: SchoolHint | null;
  /** The school's record; null when it is not read yet or there is none. */
  readonly record: SchoolRecord | null;
  /** Whether reading the record is done. */
  readonly settled: boolean;
  readonly status: SchoolStatus;
  readonly outlook: Outlook;
  /** The live closings file, for the nearby schools' statuses; null when there is none. */
  readonly closings?: ClosingsFile | null;
  /** The directory's district names, for the districts next door; null until read. */
  readonly names?: Names | null;
  readonly now: Date;
  /** The viewer's time zone, for posted times. */
  readonly timeZone: string;
}

/** The panel's view, or null when there is nothing to show for this id (no such school). */
export function schoolView(input: ViewInput): SchoolView | null {
  const { id, record, settled, now, timeZone } = input;
  const hint = input.hint?.id === id ? input.hint : null;
  if (record === null) {
    if (hint === null) return settled ? null : loadingView(id);
    // What the pick knew: the name and the town, until the record is read (or for good, without one).
    const { name, campus } = splitName(hint.name);
    return {
      id,
      name,
      campus,
      kind: null,
      place: hint.sub === '' ? null : hint.sub,
      status: [],
      chance: null,
      facts: [],
      nearby: [],
      loading: !settled,
    };
  }
  const shown = shownName(id, record.name);
  const { name, campus } = splitName(shown);
  const town = townOf(record) ?? (hint === null || hint.sub === '' ? null : hint.sub);
  const place = [town, record.county].filter((part): part is string => part !== null);
  let status: StatusLineView[] = [];
  try {
    status = statusLines(input.status, now, timeZone);
  } catch {
    // A time zone or a value the formatters refuse: no status rather than a wrong one.
  }
  // Each day's decided status, where its line shows (none does where the formatters refuse
  // them); "open" says only that no closing is posted, and decides nothing.
  const decided = {
    today: input.status.today !== null && input.status.today !== 'open' && status.length > 0,
    tomorrow: input.status.tomorrow !== null && status.length > 0,
  };
  return {
    id,
    name,
    campus,
    kind: kindOf(record),
    place: place.length > 0 ? place.join(DOT) : null,
    status,
    // A private school has no district, and no district forecast: no chance section.
    chance:
      record.district === null
        ? null
        : chanceView({
            outlook: input.outlook,
            decided,
            status,
            district: districtShortName(record.district.id, record.district.name),
            closings: input.closings ?? null,
            names: input.names ?? null,
            now,
            timeZone,
          }),
    facts: factsOf(record),
    nearby: nearbyOf(record, input.closings ?? null, now),
    loading: false,
  };
}

function loadingView(id: SchoolId): SchoolView {
  return {
    id,
    name: '',
    campus: null,
    kind: null,
    place: null,
    status: [],
    chance: null,
    facts: [],
    nearby: [],
    loading: true,
  };
}

/** The live files a school's day is read from, as last read. */
interface LiveFiles {
  closings: ClosingsFile | null;
  covered: CoveredFile | null;
  predictions: PredictionsFile | null;
}

export interface WatchOptions {
  readonly files: DataFiles;
  readonly details: DetailsSource;
  readonly id: SchoolId;
  readonly hint: SchoolHint | null;
  /** Called with each new view; null when there is no such school. */
  readonly onView: (view: SchoolView | null) => void;
  readonly now?: () => Date;
  readonly timeZone?: () => string;
  /** How often to read the live files again. Default LIVE_POLL_MS. */
  readonly pollMs?: number;
  /**
   * The directory a stamp names, or null, for the names of the districts next
   * door; asked only when a chance is shown for a district that has neighbors.
   */
  readonly directory?: (stamp: DirectoryStamp) => Promise<Directory | null>;
}

function viewerTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return 'UTC';
  }
}

/** Reads a school and its day, and keeps its view current. Returns the function that stops it. */
export function watchSchool(options: WatchOptions): () => void {
  const { files, details, id, hint, onView } = options;
  const now = options.now ?? (() => new Date());
  const timeZone = options.timeZone ?? viewerTimeZone;
  let stopped = false;
  let record: SchoolRecord | null = null;
  let settled = false;
  const live: LiveFiles = { closings: null, covered: null, predictions: null };
  /** The directory's names, once asked for and read. */
  let names: Names | null = null;
  let askedNames = false;

  const show = (): void => {
    if (stopped) return;
    const at = now();
    const outlook =
      record === null
        ? null
        : schoolOutlook({
            district: record.district?.index ?? null,
            directory: record.directory,
            shipped: files.has(PUBLISHED_PATHS.predictions),
            predictions: live.predictions,
            now: at,
          });
    // The school's own today: its district's time zone, where the predictions file gives it.
    const status =
      record === null
        ? NO_STATUS
        : schoolStatus({
            school: record.index,
            directory: record.directory,
            closings: live.closings,
            covered: live.covered,
            now: at,
            timeZone: outlook?.timeZone ?? null,
          });
    const view = schoolView({
      id,
      hint,
      record,
      settled,
      status,
      outlook,
      closings: live.closings,
      names,
      now: at,
      timeZone: timeZone(),
    });
    onView(view);
    // A chance for a district with neighbors: their names, and their schools' districts, come
    // from the directory, read once (the glow has most often read it already).
    const neighbors = outlook?.neighbors ?? [];
    const stamp = live.closings?.directory ?? live.predictions?.directory ?? null;
    if (
      !askedNames &&
      view !== null &&
      view.chance !== null &&
      neighbors.length > 0 &&
      stamp !== null
    ) {
      askedNames = true;
      void options
        .directory?.(stamp)
        .then((directory) => {
          if (directory === null || stopped) return;
          names = namesOf(directory);
          show();
        })
        .catch(() => undefined);
    }
  };

  const readLive = async (): Promise<void> => {
    const read = async <T>(
      path: string,
      parse: (value: unknown) => T | null,
    ): Promise<T | null> => {
      if (!files.has(path)) return null;
      try {
        // no-cache: past the HTTP cache to the server (or the worker's revalidation), as live.ts reads.
        return parse(await fetchJson(files, path, { cache: 'no-cache' }));
      } catch {
        return null;
      }
    };
    const [closings, covered, predictions] = await Promise.all([
      read(PUBLISHED_PATHS.closings, parseClosings),
      read(PUBLISHED_PATHS.covered, parseCovered),
      read(PUBLISHED_PATHS.predictions, parsePredictions),
    ]);
    // A read that fails keeps what was read before: it is still true as of its own time.
    live.closings = closings ?? live.closings;
    live.covered = covered ?? live.covered;
    live.predictions = predictions ?? live.predictions;
  };

  // Nothing to read and nothing known: no such school here, and no panel, not even for a moment.
  if (hint === null && !files.has(DETAILS_INDEX_PATH)) {
    onView(null);
    return () => undefined;
  }
  show();
  const loading = details.get(id).then(
    (found) => {
      record = found;
    },
    () => undefined,
  );
  void Promise.all([loading, readLive()]).then(() => {
    settled = true;
    show();
  });
  const timer = setInterval(() => {
    void readLive().then(show);
  }, options.pollMs ?? LIVE_POLL_MS);

  return () => {
    stopped = true;
    clearInterval(timer);
  };
}

export { createDetailsSource };
