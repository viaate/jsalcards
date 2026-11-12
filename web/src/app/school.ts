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
 * own today (its district's time zone, or a private school's own, from the
 * predictions file); a chance only where the district (or the private school
 * itself) has a forecast for a day not yet under way, and
 * nothing where the files cannot say for now. A day's chance never shows
 * beside a status the school decided for that day (closed, delayed, remote,
 * early dismissal): the fact beats the forecast. "Open today" is no decision,
 * only that no closing is posted yet: before today is under way on the school's
 * clock (7:30 AM, or its buses before that: chance.ts underWay, the rule that
 * spends today's chance) most districts have not called it, so the panel says
 * no "Open today" before then, whatever the forecast (a stale or missing file,
 * or no threat, included), and today's chance shows alone where there is one;
 * from then "Open today" shows beside the next day's. Without the file's zone
 * the school's clock is the latest any part of its state keeps (chance.ts
 * latestZone), and "Open today" shows only while today is still its today there.
 * An open panel shows again at the minute its day turns (chance.ts nextTurn).
 */

import { ALIKE_DISTRICTS } from 'virtual:snowlight/district-names';
import { DISTRICT_NAME_FIXES, SCHOOL_NAME_FIXES } from 'virtual:snowlight/school-names';

import { REASON_KEYS, STATUS_KEYS, copy } from '../copy';
import { detailsFormat } from '../copy-details';
import { format } from '../copy-format';
import { seasonFormat } from '../copy-season';
import type { StatusKey } from '../copy';
import type { NearbyReasonKey } from '../copy-format';
import { decodeDay, litStatus } from '../data/closings';
import { createDetailsSource } from '../data/details';
import { sameDirectory } from '../data/directory';
import { DETAILS_INDEX_PATH } from '../data/details-format';
import type { DetailsSource, SchoolRecord } from '../data/details';
import { fetchJson } from '../data/files';
import type { DataFiles } from '../data/files';
import {
  LIVE_POLL_MS,
  LIVE_SIDE_POLL_MS,
  closingsReader,
  dueEvery,
  newerClosings,
  newerPredictions,
  pollWhileVisible,
  predictionsReader,
  toldZones,
  turnTimer,
} from '../data/live';
import { mapDay, nextTurnOf, schoolZone, unreadZoneOf, zoneOf } from '../data/map-day';
import type { ToldZones } from '../data/map-day';
import {
  NO_STATUS,
  nextDay,
  parseCovered,
  schoolOutlook,
  schoolStatus,
  schoolToday,
} from '../data/school-day';
import type { Outlook, SchoolStatus, StatusRow } from '../data/school-day';
import type { Directory } from '../data/directory';
import type { ReplayOn } from '../data/replay';
import { readSeason, schoolSeason } from '../data/season';
import { parseInstant } from '../state/instant';
import { casedName, displayName } from '../text/names';
import { stateOfId } from '../text/school-names';
import { PUBLISHED_PATHS, Reason, Status } from '../types/generated';
import type {
  ClosingsFile,
  CoveredFile,
  DirectoryStamp,
  LocalDate,
  PredictionsFile,
  SchoolId,
  SeasonFile,
} from '../types/generated';
import { chanceView, latestZone, nextTurn, shortDistrictName, todayUnderWay } from './chance';
import type { ChanceView, DistrictNaming, Names } from './chance';

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
  /** "Students and staff. Buses run snow routes. No breakfast.", or null (src/copy-details.ts). */
  readonly said: string | null;
  /**
   * The school's own day the line is for, by the clock its status was read by; null for a
   * line with no day of the school's clock to name (a past day's, which names its own).
   * The share cards (app/share-card.ts) name it.
   */
  readonly day?: LocalDate | null;
  /** The reason in the note ("Winter storm"), or null: the share cards show it alone. */
  readonly reason?: string | null;
  /**
   * Whether the line is for a day after the one the map shows for the school (its later-day
   * ring's day, map/later-rings.ts): its glyph is the ring's, not the light's.
   */
  readonly later?: boolean;
  /** Whether the headline names its own date ("Closed Fri, Nov 13"): the share cards add none. */
  readonly dated?: boolean;
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
  /**
   * The season line: the school's closed, delayed, remote and early-dismissal
   * days this school year (data/season.ts); null or absent when the season
   * file counts none for it, or does not speak for now.
   */
  readonly season?: string | null;
  /**
   * What the share cards (app/share-card.ts) need beyond the panel's words, from the same
   * files at the same moment: absent or null where the panel offers no card (a past day).
   */
  readonly share?: ShareFacts | null;
}

/** When the panel's day was current, and by which clock, for the share cards. */
export interface ShareFacts {
  /** The school's own clock, the one its status lines and chance are told by; null without one. */
  readonly zone: string | null;
  /** When the live closings file the status lines come from was made; null without one. */
  readonly statusAt: Date | null;
  /** When the predictions file the chance comes from was made; null without a chance. */
  readonly chanceAt: Date | null;
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
export function kindOf(record: SchoolRecord): string {
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

/** "Kansas City, MO", or null where the directory gives no town. */
export function townOf(record: SchoolRecord): string | null {
  return record.city === null ? null : `${casedName(record.city)}, ${record.state}`;
}

/**
 * What districts next door said of a day, for a status line whose own row names no reason:
 * the one reason any row of theirs in `day`'s group of the closings file names, when it is the
 * weather of an area (never a power outage) and at least one of them stands whole with it
 * (every school the directory gives it listed that day, each row naming it). Worded by how
 * many stand so: "A district nearby said flooding", "Districts nearby said flooding". Null
 * otherwise, and wherever the file's directory is not the one `names` comes from.
 */
export function nearbyReason(
  closings: ClosingsFile | null,
  day: LocalDate,
  neighbors: readonly number[],
  names: Names | null,
): string | null {
  if (closings === null || names === null || neighbors.length === 0) return null;
  const { stamp } = names;
  const same =
    closings.directory.generated_on === stamp.generated_on &&
    closings.directory.schools === stamp.schools &&
    closings.directory.districts === stamp.districts;
  const group = closings.days.find((item) => item.day === day);
  if (!same || group === undefined) return null;
  const next = new Set(neighbors);
  const rows = decodeDay(group);
  const said = new Set<Reason>();
  const found = new Map<number, { listed: number; reasons: Set<Reason | null> }>();
  rows.schools.forEach((school, i) => {
    const district = names.districtOf(school);
    if (!next.has(district)) return;
    const reason = group.reasons[i] ?? null;
    if (reason !== null) said.add(reason);
    const seen = found.get(district);
    if (seen === undefined) found.set(district, { listed: 1, reasons: new Set([reason]) });
    else {
      seen.listed++;
      seen.reasons.add(reason);
    }
  });
  const [reason] = said;
  if (said.size !== 1 || reason === undefined || reason === Reason.power_outage) return null;
  const key = REASON_KEYS[reason];
  if (key === undefined || key === 'powerOutage') return null;
  let whole = 0;
  for (const [district, { listed, reasons }] of found) {
    if (listed === names.schools(district) && reasons.size === 1 && reasons.has(reason)) whole++;
  }
  if (whole === 0) return null;
  const area: NearbyReasonKey = key;
  return format.reasonNearby(area, whole);
}

function statusLine(
  row: StatusRow,
  day: 'today' | 'tomorrow',
  now: Date,
  timeZone: string,
  nearby: string | null = null,
  date: LocalDate | null = null,
): StatusLineView {
  const key = statusKey(row.status);
  const detail =
    row.status === Status.delayed
      ? format.delay(row.shiftMinutes, row.clockMinute)
      : row.status === Status.early_dismissal
        ? format.dismissal(row.shiftMinutes, row.clockMinute)
        : null;
  const notes: string[] = [];
  // The school's own reason; with none, what districts nearby said, in its place.
  const reason = row.reason === null ? nearby : reasonName(row.reason);
  if (row.manual) notes.push(copy.detail.confirmed);
  if (reason !== null) notes.push(reason);
  if (row.announcedAt !== null) notes.push(format.posted(row.announcedAt, timeZone, now));
  return {
    tone: key,
    headline: copy.statusLine[key][day],
    detail,
    note: notes.length > 0 ? notes.join(DOT) : null,
    said: detailsFormat.said(row.details),
    day: date,
    reason,
  };
}

/**
 * A school's line on a replay's day: one, dated with its year, for a school
 * the replay lights; none for any other, never "Open".
 */
function replayLines(id: SchoolId, replay: ReplayOn): StatusLineView[] {
  const found = replay.lookup(id);
  if (found === null) return [];
  const key = statusKey(found.status);
  return [
    {
      tone: key,
      headline: format.replayStatus(key, replay.day),
      detail: null,
      note: found.reason === null ? null : reasonName(found.reason as Reason),
      said: null,
      day: null,
    },
  ];
}

/** What districts nearby said of the school's today and tomorrow (see nearbyReason). */
interface NearbySaid {
  readonly today: string | null;
  readonly tomorrow: string | null;
}

const NOTHING_SAID: NearbySaid = { today: null, tomorrow: null };

function statusLines(
  status: SchoolStatus,
  now: Date,
  timeZone: string,
  said: NearbySaid = NOTHING_SAID,
  today: LocalDate | null = null,
  shown: LocalDate | null = null,
): StatusLineView[] {
  const lines: StatusLineView[] = [];
  if (status.today === 'open') {
    lines.push({
      tone: 'open',
      headline: copy.open.today,
      detail: null,
      note: null,
      day: today,
      reason: null,
      said: null,
    });
  } else if (status.today !== null) {
    lines.push(statusLine(status.today, 'today', now, timeZone, said.today, today));
  }
  if (status.tomorrow !== null) {
    const next = today === null ? null : nextDay(today);
    const line = statusLine(status.tomorrow, 'tomorrow', now, timeZone, said.tomorrow, next);
    // Before the map turns to tomorrow (3:30 PM), tomorrow is a later day on it: a ring.
    lines.push(next !== null && shown !== null && next > shown ? { ...line, later: true } : line);
  }
  // Each day after tomorrow, dated in the site's words ("Closed Fri, Nov 13"), with its ring.
  for (const { day, row } of status.later ?? []) {
    const line = statusLine(row, 'tomorrow', now, timeZone, null, day);
    lines.push({
      ...line,
      headline: format.statusDated(statusKey(row.status), day),
      later: true,
      dated: true,
    });
  }
  return lines;
}

/** Whether a day's row is a status that names no reason of its own. */
function unnamed(row: StatusRow | 'open' | null): boolean {
  return row !== null && row !== 'open' && row.reason === null;
}

/**
 * What districts next door said of each day a status line shows without a reason of its own:
 * the school's today (the same day schoolStatus reads, by the outlook's zone) from today's
 * group, its tomorrow from tomorrow's; the school's own district never counts.
 */
function nearbySaid(input: ViewInput, own: number | null): NearbySaid {
  const neighbors = (input.outlook?.neighbors ?? []).filter((district) => district !== own);
  const closings = input.closings ?? null;
  const names = input.names ?? null;
  if (neighbors.length === 0 || closings === null || names === null) return NOTHING_SAID;
  const today = schoolToday(input.now, viewZone(input));
  if (today === null) return NOTHING_SAID;
  return {
    today: unnamed(input.status.today) ? nearbyReason(closings, today, neighbors, names) : null,
    tomorrow: unnamed(input.status.tomorrow)
      ? nearbyReason(closings, nextDay(today), neighbors, names)
      : null,
  };
}

/** A district's name as the panel shows it whole: "Shawnee Mission Public Schools". */
export function districtShown(id: string, name: string): string {
  return displayName(name, { state: stateOfId(id), district: true }, DISTRICT_NAME_FIXES[id] ?? {});
}

function factsOf(record: SchoolRecord): FactView[] {
  const facts: FactView[] = [];
  if (record.district !== null) {
    const { id, name } = record.district;
    facts.push({ label: copy.detail.district, lines: [districtShown(id, name)], href: null });
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

let alike: ReadonlySet<string> | null = null;

/** How the panel names a district: whole as it shows it, its state, and whether another reads the same. */
function districtNaming(id: string, name: string): DistrictNaming {
  alike ??= new Set(ALIKE_DISTRICTS);
  const state = stateOfId(id);
  return {
    shown: displayName(name, { state, district: true }, DISTRICT_NAME_FIXES[id] ?? {}),
    state,
    alike: alike.has(id),
  };
}

/** The school's own district for the chance section: its short name, as a family says it, and its state. */
function ownDistrict(id: string, name: string): { district: string; state: string | null } {
  const { shown, state, alike: same } = districtNaming(id, name);
  return { district: shortDistrictName(shown, same, state), state };
}

/**
 * A private school's own name for the chance section, where a district's short name would
 * stand: its shown name without a leading "The", so it reads within a sentence ("Private
 * schools near Pembroke Hill School closed ...").
 */
export function ownSchool(name: string): string {
  return name.replace(/^The\s+/u, '');
}

/** The directory's district names and each school's district, for the chance section. */
export function namesOf(directory: Directory): Names {
  const { ids, names } = directory.meta.districts;
  const stamp: DirectoryStamp = {
    generated_on: directory.meta.generated_on,
    schools: directory.count,
    districts: ids.length,
  };
  const named = new Map<number, DistrictNaming | null>();
  let sizes: Uint32Array | null = null;
  return {
    stamp,
    districtOf: (school) => directory.district[school] ?? -1,
    schools: (district) => {
      if (sizes === null) {
        sizes = new Uint32Array(ids.length);
        for (const d of directory.district) {
          if (d >= 0 && d < ids.length) sizes[d] = (sizes[d] ?? 0) + 1;
        }
      }
      return sizes[district] ?? 0;
    },
    naming: (district) => {
      if (!named.has(district)) {
        const id = ids[district];
        const name = names[district];
        named.set(
          district,
          id === undefined || name === undefined ? null : districtNaming(id, name),
        );
      }
      return named.get(district) ?? null;
    },
  };
}

/** A school's name as the map and search show it. */
export function shownName(id: string, name: string): string {
  return displayName(name, { state: stateOfId(id) }, SCHOOL_NAME_FIXES[id] ?? {});
}

/**
 * The zones the nearby schools' lights are told by (live.ts toldZones), and
 * each school's district, by its position, where the directory is read (a
 * district's zone is its schools'); null before it is.
 */
export interface NearbyZones {
  readonly told: ToldZones;
  readonly districtOf: ((school: number) => number) | null;
}

/** With no zones given: every nearby school by the day that is today everywhere. */
const NO_ZONES: NearbyZones = { told: null, districtOf: null };

/**
 * The status a nearby school's light shows (closings.ts litStatus), so its glyph is always its
 * light: its row on its own map day, by the clock the map tells it by; none where that clock
 * cannot be told yet (its district not read).
 */
function nearbyStatus(
  near: SchoolRecord['nearby'][number],
  directory: DirectoryStamp,
  closings: ClosingsFile | null,
  zones: NearbyZones,
  now: Date,
): Status | null {
  const zone = nearbyZone(near, zones);
  return zone === undefined ? null : litStatus(closings, directory, near.index, zone, now);
}

/**
 * The clock a nearby school's light is told by (map-day.ts schoolZone); undefined where it
 * cannot be told yet (its district not read).
 */
function nearbyZone(
  near: SchoolRecord['nearby'][number],
  zones: NearbyZones,
): string | null | undefined {
  const { told, districtOf } = zones;
  let district = -1;
  if (told !== null && told !== undefined) {
    if (districtOf === null) return undefined;
    district = districtOf(near.index);
  }
  return schoolZone(told, near.index, district, near.lon, near.lat);
}

/**
 * The next instant a light the panel shows can change by the clock alone: the next turn
 * (map-day.ts nextMapTurn: 3:30 PM, midnight) of the school's own clock and of each nearby
 * school's, so its glyphs turn with the map's lights at that minute, not at the next read.
 */
export function nearbyTurn(
  record: SchoolRecord,
  zone: string | null,
  zones: NearbyZones,
  now: Date,
): Date | null {
  const clocks = new Set<string | null>([zone]);
  for (const near of record.nearby) {
    const found = nearbyZone(near, zones);
    if (found !== undefined) clocks.add(found);
  }
  return nextTurnOf(now, [...clocks]);
}

/** The earlier of two instants, either of which may be none. */
export function earlier(a: Date | null, b: Date | null): Date | null {
  if (a === null) return b;
  if (b === null) return a;
  return a < b ? a : b;
}

function nearbyOf(
  record: SchoolRecord,
  closings: ClosingsFile | null,
  now: Date,
  replay: ReplayOn | null,
  zones: NearbyZones,
): NearbyView[] {
  return record.nearby.map((near) => {
    if (replay !== null) {
      const found = replay.lookup(near.id);
      return {
        id: near.id,
        name: shownName(near.id, near.name),
        distance: format.apart(near.metres),
        tone: found === null ? null : statusKey(found.status),
        lon: near.lon,
        lat: near.lat,
      };
    }
    const status = nearbyStatus(near, record.directory, closings, zones, now);
    return {
      id: near.id,
      name: shownName(near.id, near.name),
      distance: format.apart(near.metres),
      tone: status === null ? null : statusKey(status),
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
  /**
   * The school's own clock, the one its status was read by: its zone from the
   * predictions file for its directory, however old (data/map-day.ts, as the
   * map tells its day by). Absent: the outlook's.
   */
  readonly zone?: string | null;
  /** The live closings file, for the nearby schools' statuses; null when there is none. */
  readonly closings?: ClosingsFile | null;
  /**
   * The zones the nearby schools' lights are told by, so each glyph is its
   * light. Absent: each by the day that is today everywhere.
   */
  readonly nearbyZones?: NearbyZones;
  /** The directory's district names, for the districts next door; null until read. */
  readonly names?: Names | null;
  readonly now: Date;
  /** The viewer's time zone, for posted times. */
  readonly timeZone: string;
  /** A past day on the map: the status is that day's, and no chance is given. */
  readonly replay?: ReplayOn | null;
  /** The season file (data/season.ts), checked; null or absent when there is none. */
  readonly season?: SeasonFile | null;
}

/** The season line for a school, or null where the file says nothing that holds now. */
function seasonLine(file: SeasonFile | null, record: SchoolRecord, now: Date): string | null {
  if (file === null) return null;
  const found = schoolSeason(file, record.index, record.directory, now);
  if (found === null) return null;
  try {
    return seasonFormat.line(found.days, found.since);
  } catch {
    // A count the formatter refuses: no line rather than a wrong one.
    return null;
  }
}

/** The day the map shows for a school by its clock (map-day.ts mapDay), or null for none. */
function shownDay(now: Date, zone: string | null): LocalDate | null {
  try {
    return mapDay(now, zone);
  } catch {
    return null;
  }
}

/** The clock a view reads the school's today by: the one its status was read by. */
function viewZone(input: ViewInput): string | null {
  return input.zone === undefined ? (input.outlook?.timeZone ?? null) : input.zone;
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
  const replay = input.replay ?? null;
  // The school's today by the clock its status was read by, which each line names.
  const zone = viewZone(input);
  const today = schoolToday(now, zone);
  let status: StatusLineView[] = [];
  try {
    status =
      replay === null
        ? statusLines(
            input.status,
            now,
            timeZone,
            nearbySaid(input, record.district?.index ?? null),
            today,
            shownDay(now, zone),
          )
        : replayLines(id, replay);
  } catch {
    // A time zone or a value the formatters refuse: no status rather than a wrong one.
  }
  // Each day's decided status, where its line shows (none does where the formatters refuse
  // them); "open" says only that no closing is posted, and decides nothing.
  const decided = {
    today: input.status.today !== null && input.status.today !== 'open' && status.length > 0,
    tomorrow: input.status.tomorrow !== null && status.length > 0,
  };
  // Before today is under way on the school's clock it is not called yet: no "Open today".
  if (replay === null && input.status.today === 'open') {
    if (today === null || !todayUnderWay(today, input.outlook, latestZone(record.state), now)) {
      status = status.filter((line) => line.tone !== 'open');
    }
  }
  // A private school has no district: its own chance, its own short name where the
  // district's would stand (contract C3). A past day gives no chance.
  const chance =
    replay !== null
      ? null
      : chanceView({
          outlook: input.outlook,
          decided,
          status,
          ...(record.district === null
            ? { district: ownSchool(name), state: record.state }
            : ownDistrict(record.district.id, record.district.name)),
          closings: input.closings ?? null,
          names: input.names ?? null,
          now,
          timeZone,
        });
  return {
    id,
    name,
    campus,
    kind: kindOf(record),
    place: place.length > 0 ? place.join(DOT) : null,
    status,
    chance,
    facts: factsOf(record),
    nearby: nearbyOf(record, input.closings ?? null, now, replay, input.nearbyZones ?? NO_ZONES),
    loading: false,
    // A past day on the map is that day's: the season so far is not.
    season: replay === null ? seasonLine(input.season ?? null, record, now) : null,
    // A past day's card is not offered: the cards say what is current, as of when.
    share:
      replay === null
        ? {
            zone,
            statusAt: status.length > 0 ? closingsAt(input.closings ?? null) : null,
            chanceAt: chance === null ? null : (input.outlook?.generatedAt ?? null),
          }
        : null,
  };
}

/** When a live closings file was made, or null without one or a time it can be read by. */
function closingsAt(closings: ClosingsFile | null): Date | null {
  return closings === null ? null : parseInstant(closings.generated_at);
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
export interface LiveFiles {
  closings: ClosingsFile | null;
  covered: CoveredFile | null;
  predictions: PredictionsFile | null;
}

/**
 * The live files this build ships, read now; each null where it ships none,
 * cannot be read, or is not asked for (`sides`: covered and predictions, both
 * by default). The closings file comes from the page's one reader
 * (data/live.ts closingsReader): the newest the page has taken, the map's
 * reads or a panel's, read again only when the last read began most of a
 * poll (`pollMs`, default LIVE_POLL_MS) ago or more. The predictions file
 * comes from the page's one reader of it too (predictionsReader), which the
 * map reads each school's zone from: read again when its last read began
 * most of LIVE_SIDE_POLL_MS ago, or at once for 'fresh' (a panel opening).
 */
export async function readLiveFiles(
  files: DataFiles,
  pollMs?: number,
  sides: { readonly covered: boolean; readonly predictions: boolean | 'fresh' } = {
    covered: true,
    predictions: true,
  },
): Promise<LiveFiles> {
  const read = async <T>(path: string, parse: (value: unknown) => T | null): Promise<T | null> => {
    if (!files.has(path)) return null;
    try {
      // no-cache: past the HTTP cache to the server (or the worker's revalidation), as live.ts reads.
      return parse(await fetchJson(files, path, { cache: 'no-cache' }));
    } catch {
      return null;
    }
  };
  const [closings, covered, predictions] = await Promise.all([
    closingsReader(files).read({ pollMs }),
    sides.covered ? read(PUBLISHED_PATHS.covered, parseCovered) : null,
    // The page's one reader of the predictions file: the map reads it too, for each school's zone.
    sides.predictions === false
      ? null
      : predictionsReader(files).read({ force: sides.predictions === 'fresh' }),
  ]);
  return { closings, covered, predictions };
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
   * door; asked only for a district that has neighbors, when a chance is shown
   * or a status line names no reason of its own (what they said may fill it).
   */
  readonly directory?: (stamp: DirectoryStamp) => Promise<Directory | null>;
  /**
   * A past day on the map: the panel shows that day's status from it, and no
   * live file is read (nothing is polled).
   */
  readonly replay?: ReplayOn | null;
  /**
   * Whether the panel reads the season file (data/season.ts readSeason) for
   * its season line, as it opens. The page's panel does; off by default.
   */
  readonly seasons?: boolean;
}

export function viewerTimeZone(): string {
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
  const replay = options.replay ?? null;
  let stopped = false;
  let record: SchoolRecord | null = null;
  let settled = false;
  /** The season file, once read (a past day reads none). */
  let season: SeasonFile | null = null;
  // The page's one reader of the closings file: the panel's first read gets at least the file
  // the map holds, and never one older than it. A past day takes none.
  const reader = replay === null ? closingsReader(files) : null;
  const live: LiveFiles = { closings: null, covered: null, predictions: null };
  /** The directory, once asked for and read: the districts' names, and each school's district. */
  let directory: Directory | null = null;
  let askedDirectory = false;
  /** The directory's names, once asked for and read. */
  let names: Names | null = null;
  let wantNames = false;
  /** Each school's district, from the directory, for the nearby schools' zones; null till read. */
  let districtOf: ((school: number) => number) | null = null;
  // The minute the school's day turns under way: shown again then, not at the next read.
  const turn = turnTimer(
    () => {
      show();
    },
    () => now().getTime(),
  );

  const show = (): void => {
    if (stopped) return;
    const at = now();
    const outlook =
      record === null
        ? null
        : schoolOutlook({
            district: record.district?.index ?? null,
            school: record.district === null ? record.index : null,
            directory: record.directory,
            shipped: files.has(PUBLISHED_PATHS.predictions),
            predictions: live.predictions,
            now: at,
          });
    // The school's own today: its district's time zone (a private school's own), where the
    // predictions file for its directory gives it, however old the file (a district's clock does
    // not age), as the map tells the school's day by (data/map-day.ts): its words always agree
    // with its light.
    // The zones the map lights the school by (live.ts toldZones): those it holds, or this
    // panel's own read, or the page's newest; while none can be had, the day every contiguous US
    // clock agrees on, as the map's (map-day.ts UNREAD_ZONE), and none outside it.
    const told: ToldZones =
      record === null ? null : toldZones(files, record.directory, live.predictions);
    let zone: string | null = null;
    if (record !== null) {
      zone =
        told === undefined
          ? unreadZoneOf(record.state)
          : told === null
            ? null
            : zoneOf(told, record.index, record.district?.index ?? -1);
    }
    const status =
      record === null
        ? NO_STATUS
        : schoolStatus({
            school: record.index,
            directory: record.directory,
            closings: live.closings,
            covered: live.covered,
            now: at,
            timeZone: zone,
          });
    const view = schoolView({
      id,
      hint,
      record,
      settled,
      status,
      outlook,
      zone,
      closings: live.closings,
      nearbyZones: { told, districtOf },
      names,
      now: at,
      timeZone: timeZone(),
      replay,
      season,
    });
    onView(view);
    if (replay === null && record !== null) {
      // The chance's turn (7:30 AM, or the buses), and the map's (3:30 PM, midnight) of each
      // light the panel shows: the earlier of the two.
      const lights = nearbyTurn(record, zone, { told, districtOf }, at);
      turn.set(earlier(nextTurn(outlook, latestZone(record.state), at), lights), at);
    }
    // Nearby schools' glyphs by the zones the map lights them by: a district's zone is its
    // schools', so the directory says each one's district. A chance for a district with
    // neighbors, or a status line with no reason of its own: their names come from it too. It
    // is read once, for both (the glow has most often read it already).
    const listed = live.closings !== null && live.closings.days.length > 0;
    const nearbyNeed =
      replay === null &&
      record !== null &&
      record.nearby.length > 0 &&
      listed &&
      told !== null &&
      told !== undefined;
    const neighbors = outlook?.neighbors ?? [];
    const namesNeed =
      view !== null &&
      (view.chance !== null || unnamed(status.today) || unnamed(status.tomorrow)) &&
      neighbors.length > 0;
    if (namesNeed && !wantNames) {
      wantNames = true;
      if (directory !== null) {
        names = namesOf(directory);
        show();
        return;
      }
    }
    const stamp = live.closings?.directory ?? live.predictions?.directory ?? null;
    if (!askedDirectory && (nearbyNeed || namesNeed) && stamp !== null) {
      askedDirectory = true;
      void options
        .directory?.(stamp)
        .then((found) => {
          if (found === null || stopped) return;
          directory = found;
          if (wantNames) names = namesOf(found);
          // Its districts, only for the directory the record points into.
          if (record !== null && sameDirectory(found, record.directory)) {
            districtOf = (school) => found.district[school] ?? -1;
          }
          show();
        })
        .catch(() => undefined);
    }
  };

  const pollMs = options.pollMs ?? LIVE_POLL_MS;
  // Covered and predictions, which S8 does not publish live, are read as often as before it.
  const sidesDue = dueEvery(LIVE_SIDE_POLL_MS);
  let readOnce = false;
  const readLive = async (): Promise<void> => {
    const due = sidesDue();
    // The first read of a panel just opened reads its chance afresh; later ones share the page's.
    const predictions = due && !readOnce ? 'fresh' : due;
    readOnce = true;
    const read = await readLiveFiles(files, pollMs, { covered: due, predictions });
    // A read that fails keeps what was read before: it is still true as of its own time. The
    // reader takes only a newer closings file; newerClosings here holds the panel to that too,
    // in depth, so a panel never steps back whatever the reader hands it.
    live.closings = newerClosings(live.closings, read.closings);
    live.covered = read.covered ?? live.covered;
    live.predictions = newerPredictions(live.predictions, read.predictions);
  };

  // Nothing to read and nothing known: no such school here, and no panel, not even for a moment.
  if (hint === null && !files.has(DETAILS_INDEX_PATH)) {
    onView(null);
    return () => undefined;
  }
  show();
  // The season file, read as the panel opens (at most once a SEASON_READ_MS for every panel).
  if (replay === null && options.seasons === true) {
    void readSeason(files)
      .then((file) => {
        season = file;
        if (settled && file !== null) show();
      })
      .catch(() => undefined);
  }
  const loading = details.get(id).then(
    (found) => {
      record = found;
    },
    () => undefined,
  );
  // A past day reads no live file: the replay holds all the panel says of the day.
  void Promise.all([loading, replay === null ? readLive() : null]).then(() => {
    settled = true;
    show();
  });
  // Live, read again while the page is seen, and as soon as it is seen again.
  const stopPolling =
    reader === null
      ? () => undefined
      : pollWhileVisible(
          () => {
            // The view at once by the clock as it reads now (a phone just woken: a chart past its
            // window, a day under way), then again with what the read brings.
            if (settled) show();
            void readLive().then(show);
          },
          pollMs,
          // Paced by the page's one reader: a read the map makes runs the panel's work too, and
          // starts its period again.
          { pace: reader },
        );
  // A newer closings file the map read: shown now, not at the panel's next read.
  const stopHearing =
    reader === null
      ? () => undefined
      : reader.subscribe((file) => {
          live.closings = newerClosings(live.closings, file);
          if (settled) show();
        });

  return () => {
    stopped = true;
    turn.stop();
    stopPolling();
    stopHearing();
  };
}

export { createDetailsSource };
