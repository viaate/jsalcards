/**
 * The area a ZIP code opens (ui/AreaPanel.svelte): the schools around it, as
 * the area files give them (data/areas-format.ts), and, when the live files
 * give a chance for a day not yet decided or under way, one chance of no
 * school for the area and how it is made.
 *
 * The area's day is the first day any of its schools would show a chance for
 * in its own panel (chance.ts headlineDay): today, until today is decided or
 * under way, then tomorrow. On that day each school counts as the live files
 * say, and as nothing else:
 *
 * - a status posted for that day decides it: closed or remote is no school
 *   (100, as a chance of no school counts both), a delayed start or an early
 *   dismissal is school (0);
 * - otherwise its district's chance, where its own panel shows that chance
 *   for that day;
 * - otherwise it is not counted, and the panel says how many are not.
 *
 * The area's chance is the average of the counted schools' chances, each
 * weighed by its students: the chance for a student picked at random from
 * them. It shows only where a chance is given for at least one school, so
 * the posted statuses alone never make a number, and with no predictions
 * file nothing of it shows. Under it, who decides: each district (or school
 * deciding for itself) with its number and how many of the area's schools it
 * decides for, so the rows' numbers, weighed by the students under each, make
 * the headline to its rounding; then the night ahead, as the chance section draws it,
 * for the district with the most students counted with a chance.
 *
 * The list is every school of the area, its own first and then the others
 * taken in, each nearest the ZIP code's point first, with today's status
 * where the live file states one, as the map lights it.
 *
 * Every word comes from src/copy.ts, src/copy-chance.ts and src/copy-area.ts.
 */

import { STATUS_KEYS } from '../copy';
import type { StatusKey } from '../copy';
import { areaFormat } from '../copy-area';
import { chanceFormat } from '../copy-chance';
import type { Zones } from '../copy-chance';
import { format } from '../copy-format';
import { AREA_MIN_SCHOOLS, AREA_NEAR_MILES } from '../data/areas-format';
import type { AreaRecord, AreaSchoolEntry, AreaSource } from '../data/areas';
import type { DetailsSource, SchoolRecord } from '../data/details';
import type { DataFiles } from '../data/files';
import { LIVE_POLL_MS } from '../data/live';
import { nextDay, schoolOutlook, schoolStatus, schoolToday } from '../data/school-day';
import type { Outlook, StatusRow } from '../data/school-day';
import { PUBLISHED_PATHS, Status } from '../types/generated';
import type { DirectoryStamp, LocalDate, SchoolId } from '../types/generated';
import { chartView, headlineDay } from './chance';
import type { ChartView } from './chance';
import { districtShown, kindOf, readLiveFiles, shownName, townOf, viewerTimeZone } from './school';
import type { LiveFiles } from './school';

/** What a pick of a ZIP code already knows: the states search names it by. */
export interface AreaHint {
  readonly zip: string;
  /** "Missouri", or ''. */
  readonly sub: string;
}

/** A school of the area, as its row shows it. */
export interface AreaSchoolView {
  readonly id: SchoolId;
  /** Its name as the map shows it. */
  readonly name: string;
  /** "Private school · PK–12". */
  readonly kind: string;
  /** "0.4 mi" from the ZIP code's point. */
  readonly distance: string;
  /** Its status today, where the live file states one, as the map lights it; null otherwise. */
  readonly tone: StatusKey | null;
  readonly lon: number;
  readonly lat: number;
}

/** One row of who decides: its number and its sentence. */
export interface AreaWhyRow {
  readonly key: string;
  /** "64%", "100%". */
  readonly number: string;
  readonly text: string;
}

export interface AreaChanceView {
  /** The day the chance is for. */
  readonly day: LocalDate;
  /** "64", "<1". */
  readonly number: string;
  /** "Chance of no school Tuesday". */
  readonly meaning: string;
  /** Who decides, most students first. */
  readonly why: readonly AreaWhyRow[];
  /** How many of the area's schools the chance leaves out, and why; null when it counts them all. */
  readonly left: string | null;
  /** The night ahead, as the chance section draws it; null without one. */
  readonly chart: ChartView | null;
  /** The chart's words at the announcement's line as the clock reads `now`, or null without one. */
  readonly announces: (now: Date) => string | null;
}

/** How many of the area's schools hold a status today, in the legend's order. */
export interface AreaCountView {
  readonly status: StatusKey;
  /** "9 closed". */
  readonly text: string;
}

export interface AreaView {
  readonly zip: string;
  /** "Kansas City, MO" where most of its own schools say so, else its states: "Missouri". */
  readonly place: string | null;
  /** "Schools around 64112", for a screen reader. */
  readonly label: string;
  /** "Back to 64112", for a school its list opens. */
  readonly back: string;
  readonly chance: AreaChanceView | null;
  readonly counts: readonly AreaCountView[];
  /** "14 schools in 64111". */
  readonly heading: string;
  readonly own: readonly AreaSchoolView[];
  /** "4 more within 2 miles", over the others taken in; null when none are. */
  readonly nearHeading: string | null;
  readonly near: readonly AreaSchoolView[];
  /** "No others within 2 miles", where the ZIP code has few schools and none are near. */
  readonly noneNear: string | null;
  /** [west, south, east, north] around its schools and its point; null until it is read. */
  readonly bounds: readonly [number, number, number, number] | null;
  /** True until the area and its schools are read. */
  readonly loading: boolean;
}

/** One school of the area, read: where the file puts it, and its record. */
interface Member {
  readonly entry: AreaSchoolEntry;
  readonly record: SchoolRecord;
  readonly own: boolean;
}

/** What one school counts as on the area's day. */
type Counted =
  | { readonly how: 'forecast'; readonly chance: number }
  | { readonly how: 'posted'; readonly status: StatusKey; readonly chance: number };

export interface AreaInput {
  readonly zip: string;
  readonly hint: AreaHint | null;
  /** The area; null when it is not read yet, or there is none. */
  readonly area: AreaRecord | null;
  /** Each school's record by id, once read (null for one that cannot be); null before. */
  readonly records: ReadonlyMap<string, SchoolRecord | null> | null;
  /** Whether reading the area and its schools is done. */
  readonly settled: boolean;
  readonly live: LiveFiles;
  /** Whether this build ships a predictions file. */
  readonly shipped: boolean;
  readonly now: Date;
  /** The viewer's time zone, for the chart's times. */
  readonly timeZone: string;
}

function sameStamp(a: DirectoryStamp, b: DirectoryStamp): boolean {
  return (
    a.generated_on === b.generated_on && a.schools === b.schools && a.districts === b.districts
  );
}

function statusKey(status: Status): StatusKey {
  return STATUS_KEYS[status] ?? 'closed';
}

/** Whether a posted status is no school: closed or remote, as a chance of no school counts them. */
function noSchool(status: Status): boolean {
  return status === Status.closed || status === Status.remote;
}

/** The town most of its own schools give, where more than half give one; else null. */
function townOfMost(records: readonly SchoolRecord[]): string | null {
  const towns = new Map<string, number>();
  for (const record of records) {
    const town = townOf(record);
    if (town !== null) towns.set(town, (towns.get(town) ?? 0) + 1);
  }
  for (const [town, n] of towns) if (n * 2 > records.length) return town;
  return null;
}

function rowView(member: Member, tone: StatusKey | null): AreaSchoolView {
  const { entry, record } = member;
  return {
    id: record.id,
    name: shownName(record.id, record.name),
    kind: kindOf(record),
    distance: format.miles(entry.metres),
    tone,
    lon: entry.lon,
    lat: entry.lat,
  };
}

/** Today's status a school's light shows, as the map's and the school panel's nearby list read it. */
function todayTone(record: SchoolRecord, live: LiveFiles, now: Date): StatusKey | null {
  const today = schoolStatus({
    school: record.index,
    directory: record.directory,
    closings: live.closings,
    covered: null,
    now,
  }).today;
  return today === null || today === 'open' ? null : statusKey(today.status);
}

/** The area's chance, and who decides, or null where no chance is given for its day. */
export function areaChance(
  members: readonly Member[],
  input: Pick<AreaInput, 'live' | 'shipped' | 'now' | 'timeZone'>,
): AreaChanceView | null {
  const { live, shipped, now } = input;
  if (!shipped || live.predictions === null || members.length === 0) return null;
  const outlooks: Outlook[] = members.map(({ record }) =>
    schoolOutlook({
      district: record.district?.index ?? null,
      directory: record.directory,
      shipped,
      predictions: live.predictions,
      now,
    }),
  );
  // A school outside a district has no time zone of its own: the area's, from its districts.
  const areaZone = outlooks.find((outlook) => outlook !== null)?.timeZone ?? null;
  if (areaZone === null) return null;
  const days = members.map(({ record }, i) => {
    const zone = outlooks[i]?.timeZone ?? areaZone;
    const status = schoolStatus({
      school: record.index,
      directory: record.directory,
      closings: live.closings,
      covered: null,
      now,
      timeZone: zone,
    });
    const today = schoolToday(now, zone);
    const posted = (day: LocalDate): StatusRow | null => {
      if (day === today) return status.today === 'open' ? null : status.today;
      return today !== null && day === nextDay(today) ? status.tomorrow : null;
    };
    const decided = { today: posted(today ?? '') !== null, tomorrow: status.tomorrow !== null };
    const shown = headlineDay(outlooks[i] ?? null, decided, now);
    return { posted, shown };
  });
  // The first day any school would show a chance for.
  const day = days
    .map(({ shown }) => shown?.day ?? null)
    .filter((found): found is LocalDate => found !== null)
    .sort()[0];
  if (day === undefined) return null;

  const counted: (Counted | null)[] = days.map(({ posted, shown }) => {
    const row = posted(day);
    if (row !== null) {
      return { how: 'posted', status: statusKey(row.status), chance: noSchool(row.status) ? 1 : 0 };
    }
    return shown?.day === day ? { how: 'forecast', chance: shown.noSchool } : null;
  });
  let students = 0;
  let sum = 0;
  members.forEach(({ record }, i) => {
    const count = counted[i];
    if (count === null || count === undefined) return;
    const weight = record.enrollment ?? 0;
    students += weight;
    sum += weight * count.chance;
  });
  if (students <= 0) return null;
  const chance = sum / students;

  // Who decides: a district, or a school outside one deciding for itself, and what it counts as.
  interface Decider {
    key: string;
    name: string;
    school: boolean;
    counted: Counted;
    schools: number;
    students: number;
    order: number;
  }
  const deciders = new Map<string, Decider>();
  members.forEach(({ record }, i) => {
    const count = counted[i];
    if (count === null || count === undefined) return;
    const district = record.district;
    const by = district === null ? `school ${record.id}` : `district ${String(district.index)}`;
    const key = `${by} ${count.how === 'posted' ? count.status : 'forecast'}`;
    const found = deciders.get(key);
    if (found !== undefined) {
      found.schools += 1;
      found.students += record.enrollment ?? 0;
      return;
    }
    deciders.set(key, {
      key,
      name:
        district === null
          ? shownName(record.id, record.name)
          : districtShown(district.id, district.name),
      school: district === null,
      counted: count,
      schools: 1,
      students: record.enrollment ?? 0,
      order: i,
    });
  });
  const of = members.length;
  let why: AreaWhyRow[];
  let number: string;
  let meaning: string;
  try {
    number = chanceFormat.chanceNumber(chance);
    meaning = chanceFormat.chanceOn(day);
    why = [...deciders.values()]
      .sort((a, b) => b.students - a.students || a.order - b.order)
      .map((decider) => {
        const { counted: count } = decider;
        if (count.how === 'forecast') {
          return {
            key: decider.key,
            number: format.chance(count.chance),
            text: areaFormat.decides(decider.name, decider.schools, of),
          };
        }
        return {
          key: decider.key,
          number: areaFormat.postedShare(count.status),
          text: decider.school
            ? areaFormat.schoolPosted(decider.name, count.status, day)
            : areaFormat.districtPosted(decider.name, count.status, decider.schools, of, day),
        };
      });
  } catch {
    // A value the words refuse: no chance rather than a wrong one.
    return null;
  }
  const missing = counted.filter((count) => count === null).length;
  let left: string | null = null;
  if (missing > 0) {
    try {
      left = areaFormat.notCounted(missing, of, day);
    } catch {
      return null;
    }
  }

  // The night ahead: the district with the most students counted with a chance.
  const forecasts = [...deciders.values()].filter((d) => d.counted.how === 'forecast');
  const lead = forecasts.sort((a, b) => b.students - a.students || a.order - b.order)[0];
  const leadShown = lead === undefined ? null : (days[lead.order]?.shown ?? null);
  const zones: Zones = {
    school: outlooks[lead?.order ?? -1]?.timeZone ?? areaZone,
    viewer: input.timeZone,
  };
  let chart: ChartView | null = null;
  if (leadShown?.detail !== undefined) {
    try {
      chart = chartView(leadShown.detail, now, zones);
    } catch {
      chart = null;
    }
  }
  // When the district usually announces is its own: said only where it alone decides by chance.
  if (chart !== null && forecasts.length > 1) {
    chart = { ...chart, announces: null, key: chart.key.filter((row) => row.mark !== 'announces') };
  }
  const announcement = chart?.key.find((row) => row.mark === 'announces');
  return {
    day,
    number,
    meaning,
    why,
    left,
    chart,
    announces: (clock) => {
      if (announcement?.mark !== 'announces') return null;
      try {
        return chanceFormat.announcesKey(announcement.at, zones, clock);
      } catch {
        return announcement.text;
      }
    },
  };
}

/** The panel's view, or null when there is no area for this ZIP code. */
export function areaView(input: AreaInput): AreaView | null {
  const { zip, hint, area, records, settled, live, now } = input;
  const label = areaFormat.label(zip);
  const back = areaFormat.backTo(zip);
  if (area === null || records === null) {
    if (settled && area === null) return null;
    return {
      zip,
      place: hint?.zip === zip && hint.sub !== '' ? hint.sub : null,
      label,
      back,
      chance: null,
      counts: [],
      heading: '',
      own: [],
      nearHeading: null,
      near: [],
      noneNear: null,
      bounds: null,
      loading: true,
    };
  }
  // A school is listed by the record the file names, from the same directory: else not at all.
  const read = (entry: AreaSchoolEntry, own: boolean): Member[] => {
    const record = records.get(entry.id) ?? null;
    return record !== null &&
      record.index === entry.index &&
      sameStamp(record.directory, area.directory)
      ? [{ entry, record, own }]
      : [];
  };
  const own = area.own.flatMap((entry) => read(entry, true));
  const near = area.near.flatMap((entry) => read(entry, false));
  const members = [...own, ...near];
  const tones = members.map(({ record }) => todayTone(record, live, now));
  const rows = members.map((member, i) => rowView(member, tones[i] ?? null));

  const counts: AreaCountView[] = [];
  for (const status of STATUS_KEYS) {
    const n = tones.filter((tone) => tone === status).length;
    if (n > 0) counts.push({ status, text: areaFormat.statusCount(status, n) });
  }
  // Every school the file names must be read for the chance to stand for the area.
  const whole = members.length === area.own.length + area.near.length;
  const chance = whole ? areaChance(members, input) : null;

  const lons = [area.lon, ...members.map(({ entry }) => entry.lon)];
  const lats = [area.lat, ...members.map(({ entry }) => entry.lat)];
  const few = area.own.length < AREA_MIN_SCHOOLS;
  return {
    zip,
    place:
      townOfMost(own.map(({ record }) => record)) ??
      (area.states.length > 0 ? areaFormat.states(area.states) : null),
    label,
    back,
    chance,
    counts,
    heading: areaFormat.schoolsIn(own.length, zip),
    own: rows.slice(0, own.length),
    nearHeading:
      near.length > 0 ? areaFormat.nearOthers(near.length, own.length, AREA_NEAR_MILES) : null,
    near: rows.slice(own.length),
    noneNear:
      few && area.near.length === 0 ? areaFormat.noneNear(own.length, AREA_NEAR_MILES) : null,
    bounds: [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)],
    loading: false,
  };
}

export interface WatchAreaOptions {
  readonly files: DataFiles;
  readonly areas: AreaSource;
  readonly details: DetailsSource;
  readonly zip: string;
  readonly hint: AreaHint | null;
  /** Called with each new view; null when there is no area for this ZIP code. */
  readonly onView: (view: AreaView | null) => void;
  readonly now?: () => Date;
  readonly timeZone?: () => string;
  /** How often to read the live files again. Default LIVE_POLL_MS. */
  readonly pollMs?: number;
}

/** Reads a ZIP code's area and its day, and keeps its view current. Returns the function that stops it. */
export function watchArea(options: WatchAreaOptions): () => void {
  const { files, areas, details, zip, hint, onView } = options;
  const now = options.now ?? (() => new Date());
  const timeZone = options.timeZone ?? viewerTimeZone;
  let stopped = false;
  let area: AreaRecord | null = null;
  let records: Map<string, SchoolRecord | null> | null = null;
  let settled = false;
  const live: LiveFiles = { closings: null, covered: null, predictions: null };

  const show = (): void => {
    if (stopped) return;
    onView(
      areaView({
        zip,
        hint,
        area,
        records,
        settled,
        live,
        shipped: files.has(PUBLISHED_PATHS.predictions),
        now: now(),
        timeZone: timeZone(),
      }),
    );
  };
  const readLive = async (): Promise<void> => {
    const read = await readLiveFiles(files);
    // A read that fails keeps what was read before: it is still true as of its own time.
    live.closings = read.closings ?? live.closings;
    live.predictions = read.predictions ?? live.predictions;
  };

  // Nothing to read: no area here, and no panel, not even for a moment.
  if (!areas.shipped) {
    onView(null);
    return () => undefined;
  }
  show();
  const reading = areas
    .get(zip)
    .catch(() => null)
    .then(async (found) => {
      area = found;
      if (found === null) return;
      const entries = [...found.own, ...found.near];
      const read = await Promise.all(entries.map(({ id }) => details.get(id).catch(() => null)));
      records = new Map(entries.map(({ id }, i) => [id, read[i] ?? null]));
    });
  void Promise.all([reading, readLive()]).then(() => {
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
