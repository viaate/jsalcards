/**
 * The why, step by step, on a storm-class day (WHY-TRANSPARENT): the district's own record
 * first, then every step the chance took with its points, each with its details folded under
 * it (ui/ChanceSection.svelte). Every number comes from the predictions file's why or the
 * standing file it names (data/standing.ts); where a number is missing, a step would not add,
 * or the day is one the steps do not cover, the panel keeps today's why (whyView).
 */

import { chanceFormat } from '../copy-chance';
import type {
  HeldStage,
  LeftOut,
  ReadInput,
  StepClass,
  StepClause,
  StepWho,
  UsualInput,
  Zones,
} from '../copy-chance';
import type { ForecastDetail, ReasonDetail } from '../data/forecast-detail';
import type { LocalDate, StandingFile } from '../types/generated';

const steps = chanceFormat.steps;

/** One step: its label, its sentence and its folded details (none: no fold). */
export interface StepRowView {
  readonly key: string;
  readonly number: string;
  readonly text: string;
  readonly help: readonly string[];
  /** What the row's fold button is for, said to a screen reader after its words. */
  readonly name: string;
}

export interface StepsView {
  /** DIST-whole, where several schools decide. */
  readonly whole: string | null;
  /** The record note: first, no label, not in the sum. */
  readonly record: { readonly text: string; readonly help: readonly string[] };
  readonly rows: readonly StepRowView[];
  /** The delay line's fold (DL-h), where its numbers give the published delay. */
  readonly delayHelp: string | null;
}

/** Whose steps: a district by its directory position, or a private school by its place in
 * predictions/latest.json's `schools`. */
export type StepsUnit =
  | { readonly kind: 'district'; readonly index: number }
  | { readonly kind: 'school'; readonly index: number };

export interface StepsSource {
  readonly file: StandingFile;
  readonly unit: StepsUnit;
  /** The file's clauses the forecast broke (its `forecast_check`). */
  readonly forecastCheck: readonly string[];
}

const CLASSES = ['advisory', 'warning', 'cold'] as const;
const CLASS_OF: Readonly<Record<string, StepClass>> = {
  winter_storm_warning: 'warning',
  winter_weather_advisory: 'advisory',
  ice_storm_warning: 'warning',
  blizzard_warning: 'warning',
  extreme_cold_warning: 'cold',
  advisory: 'advisory',
  cold: 'cold',
  lake_snow: 'warning',
  tropical: 'warning',
};

const BORROWED = 1;
const MIXED = 2;
const ONE = 4;
const POOL_REGION = { advisory: 8, warning: 32 } as const;
const POOL_NONE = { advisory: 16, warning: 64 } as const;
const CLAMP = { advisory: 128, warning: 256 } as const;
const CAPPED = { advisory: 512, warning: 1024, cold: 2048 } as const;
const PRIVATE_TROPICAL = 1;
const PRIVATE_CAPPED = { advisory: 2, warning: 4, cold: 8 } as const;
const CLAUSES = new Set(['advisory_mean', 'advisory_p99', 'advisory_warning_mean', 'district_max']);

/** The line kinds the forecast step's rows say; any other keeps today's why. */
const READ_KINDS = new Set(['snow_total', 'ice', 'wind_chill']);

function clauseOf(name: string | undefined): StepClause | null {
  return name !== undefined && CLAUSES.has(name) ? (name as StepClause) : null;
}

type Row4 = readonly [number, number, number, number];
type Row5 = readonly [number, number, number, number, number];
type Row3 = readonly [number, number, number];

/** A held row's mask: the stages that moved the chance at all (pipeline standing.py). */
const ACTED_DISTRICT = 1;
const ACTED_NATIONAL = 2;

function rowFor<T extends readonly number[]>(
  rows: readonly T[] | undefined,
  index: number,
): T | null {
  return rows?.find((row) => row[0] === index) ?? null;
}

/** The window's end on the day: 18:00 UTC (as chance.ts says the lines' "by 1 PM"). */
function windowEnd(day: LocalDate): Date {
  return new Date(`${day}T18:00:00Z`);
}

/** 9 PM on the school's clock the evening before the day, and that evening's weekday. */
function snapshotOf(day: LocalDate, zone: string): { at: Date; weekday: string } {
  const noon = new Date(`${day}T12:00:00Z`);
  const before = new Date(noon.getTime() - 86_400_000);
  const local = new Intl.DateTimeFormat('en-CA', {
    timeZone: zone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(before);
  // 21:00 local: find the UTC instant whose local wall time is 21:00 on that date.
  let at = new Date(`${local}T21:00:00Z`);
  for (let i = 0; i < 3; i += 1) {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: zone,
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).formatToParts(at);
    const hour = Number(parts.find((part) => part.type === 'hour')?.value ?? '21');
    const minute = Number(parts.find((part) => part.type === 'minute')?.value ?? '0');
    const off = (hour - 21) * 60 + minute;
    if (off === 0) break;
    at = new Date(at.getTime() - off * 60_000);
  }
  return { at, weekday: chanceFormat.weekday(local) };
}

interface Unit {
  readonly winter: readonly [number, number, number] | null;
  readonly borrowed: boolean;
  readonly who: StepWho;
  readonly region: number;
  readonly clipped: boolean;
  readonly held: readonly [number, number, number];
  /** The held stages that moved the chance at all, under a point too (ACTED_*). */
  readonly acted: number;
  readonly capped: boolean;
  readonly tropical: boolean;
  readonly record: { closed: number; delayed: number; of: number } | null;
  readonly sum: { closed: number; of: number } | null;
}

/** What the standing file says of one unit and class, or null where it says it wrong. */
function unitOf(
  source: StepsSource,
  klass: StepClass,
  name: string,
  tropical: boolean,
): Unit | null {
  const { file, unit } = source;
  if (unit.kind === 'district') {
    const i = unit.index;
    const flags = file.flags[i];
    if (flags === undefined || i < 0 || i >= file.winter.length) return null;
    const winter = file.winter[i] ?? null;
    const region = rowFor(file.region[klass] as readonly Row3[], i);
    const held = rowFor(file.held[klass] as readonly Row5[], i);
    const record = rowFor(file.record[klass] as readonly Row4[], i);
    const sum = file.record_sum[klass];
    return {
      winter,
      borrowed: (flags & BORROWED) !== 0,
      who: { name, school: false, set: { mixed: (flags & MIXED) !== 0, one: (flags & ONE) !== 0 } },
      region: region?.[1] ?? 0,
      clipped: region?.[2] === 1,
      held: held === null ? [0, 0, 0] : [held[1], held[2], held[3]],
      acted: held?.[4] ?? 0,
      capped: (flags & CAPPED[klass]) !== 0,
      tropical,
      record: record === null ? null : { closed: record[1], delayed: record[2], of: record[3] },
      sum: { closed: sum[0], of: sum[2] },
    };
  }
  const privateFile = file.private;
  const row = privateFile.of[unit.index];
  if (row === undefined || row < 0) return null;
  const found = privateFile.rows[row];
  if (found === undefined) return null;
  const [winter, advisoryRegion, bits] = found as unknown as readonly [
    readonly [number, number, number] | null,
    number,
    number,
  ];
  const held = rowFor(privateFile.held[klass] as readonly Row5[], row);
  const record = rowFor(privateFile.record[klass] as readonly Row4[], unit.index);
  const sum = privateFile.record_sum[klass];
  return {
    winter,
    borrowed: true,
    who: { name, school: true, set: { mixed: false, one: true } },
    region: klass === 'advisory' ? advisoryRegion : 0,
    clipped: false,
    held: held === null ? [0, 0, 0] : [held[1], held[2], held[3]],
    acted: held?.[4] ?? 0,
    capped: (bits & PRIVATE_CAPPED[klass]) !== 0,
    tropical: (bits & PRIVATE_TROPICAL) !== 0 || tropical,
    record: record === null ? null : { closed: record[1], delayed: record[2], of: record[3] },
    sum: { closed: sum[0], of: sum[2] },
  };
}

export interface StepsInput {
  readonly detail: ForecastDetail;
  readonly chance: number;
  readonly delay: number;
  readonly day: LocalDate;
  /** The district's short name, or the private school's own. */
  readonly district: string;
  readonly zones: Zones;
  readonly source: StepsSource;
  /** The panel shows the night chart above (FC-wait's fold). */
  readonly nightChart: boolean;
  /** Today's sentence for each of the why's lines, in its order (a day the bus hour timing
   * served shows them as the forecast's rows). */
  readonly lines?: readonly string[];
}

/**
 * The steps of a storm-class day, or null: today's why then stands. Null for a pooled day, a
 * day said open, one with a night-before outlook line, a number the files do not give, or
 * steps that would not add to the chance.
 */
export function stepsView(input: StepsInput): StepsView | null {
  try {
    return stepsOf(input);
  } catch {
    return null;
  }
}

function stepsOf(input: StepsInput): StepsView | null {
  const { detail, chance, source } = input;
  const why = detail.why;
  if (why === null) return null;
  const base = why.base;
  if (base.kind !== 'class') return null;
  const named = base.alert ?? base.weather ?? null;
  if (named === null) return null;
  const klass = CLASS_OF[named];
  if (klass === undefined) return null;
  const reasons = why.reasons;
  if (reasons.some((reason) => reason.kind === 'said_open' || reason.kind === 'outlook')) {
    return null;
  }
  const file = source.file;
  const percent = Math.round(chance * 100);
  const school = base.of === 'private_schools';
  if (school !== (source.unit.kind === 'school')) return null;
  const unit = unitOf(source, klass, input.district, base.tropical === true);
  if (unit === null) return null;
  const level = file.levels[klass];
  const ref = file.ref[klass];
  const j = CLASSES.indexOf(klass);
  const heldSum = unit.held[0] + unit.held[1] + unit.held[2];
  const standingPoints = base.points - level.now - unit.region - heldSum;
  const lines = reasons.reduce((sum, reason) => sum + reason.points, 0);
  if (base.points + lines !== percent) return null;
  const who = unit.who;
  const rows: StepRowView[] = [];

  // The start.
  const start = steps.startStep({
    who,
    alert: named,
    klass,
    now: level.now,
    prior: level.prior,
    fit: level.fit,
    storms: level.storms,
    shrunk: clauseOf((level.shrunk ?? [])[0]),
    ref,
  });
  rows.push({
    key: 'start',
    number: steps.startLabel(level.now),
    text: start.main,
    help: start.help,
    name: steps.foldName.start,
  });

  // The standing: what is left of the start's move, always on a class day.
  const days = unit.winter === null ? null : (unit.winter[j] ?? null);
  const standing = steps.standingStep({
    who,
    klass,
    days,
    county: unit.borrowed && !school,
    ref,
    points: standingPoints,
    first: file.winters[0],
    last: file.winters[1],
    tropical: unit.tropical,
  });
  if (days === null && standingPoints !== 0) return null;
  rows.push({
    key: 'standing',
    number: steps.stepPoints(standingPoints),
    text: standing.main,
    help: standing.help,
    name: steps.foldName.standing,
  });

  // The region, where it moves a point.
  if (unit.region !== 0) {
    if (klass !== 'advisory') return null;
    const region = steps.regionStep({ who, points: unit.region, clipped: unit.clipped });
    rows.push({
      key: 'region',
      number: steps.stepPoints(unit.region),
      text: region.main,
      help: region.help,
      name: steps.foldName.region,
    });
  }

  // Each hold that acted: at "0" where it moved the chance under a point.
  const stages: readonly (readonly [HeldStage, number, number])[] = [
    [unit.capped ? 'cap' : 'pull', unit.held[0], ACTED_DISTRICT],
    ['nation', unit.held[1], ACTED_NATIONAL],
    ['round', unit.held[2], 0],
  ];
  for (const [stage, moved, bit] of stages) {
    if (moved === 0 && (unit.acted & bit) === 0) continue;
    const clause = stage === 'nation' ? clauseOf(file.held_clauses?.[0]) : null;
    if (stage === 'nation' && clause === null) return null;
    rows.push({
      key: `held-${stage}`,
      number: steps.stepPoints(moved),
      text: steps.heldStep({ who, stage, clause }),
      help: [],
      name: steps.foldName.held,
    });
  }

  // The forecast.
  const forecast = forecastRows({ ...input, klass, named, unit, reasons });
  if (forecast === null) return null;
  rows.push(...forecast);

  // The column adds to the title, by construction and checked again here.
  const column =
    level.now +
    rows
      .filter((row) => row.key !== 'start')
      .reduce(
        (sum, row) => sum + (row.number === '0' ? 0 : Number(row.number.replace('−', '-'))),
        0,
      );
  if (column !== percent) return null;

  const record = steps.recordNote({
    who,
    klass,
    first: file.record_winters[0],
    last: file.record_winters[1],
    record: unit.record,
    sum: unit.sum,
    region: unit.region !== 0,
  });
  const q = level.q;
  const delayHelp =
    Math.round((1 - chance) * q * 100) === Math.round(input.delay * 100) &&
    Math.round(input.delay * 100) >= 1
      ? steps.delayHelp({ alert: named, q, p: chance, delay: input.delay })
      : null;
  return {
    whole: !school && !who.set.one ? steps.wholeLine(who.name) : null,
    record: { text: record.main, help: record.help },
    rows,
    delayHelp,
  };
}

interface ForecastInput extends StepsInput {
  readonly klass: StepClass;
  readonly named: string;
  readonly unit: Unit;
  readonly reasons: readonly ReasonDetail[];
}

/** The forecast step's rows by its state (WHY-TRANSPARENT 3c), or null to keep today's why. */
function forecastRows(input: ForecastInput): StepRowView[] | null {
  const { klass, named, unit, reasons, detail, source, zones, day } = input;
  const who = unit.who;
  const read = detail.why?.read ?? null;
  const left = (kind: LeftOut): StepRowView[] => {
    const said = steps.forecastLeftOut(kind, who, zones);
    return [
      {
        key: 'forecast',
        number: '0',
        text: said.main,
        help: said.help,
        name: steps.foldName.forecast,
      },
    ];
  };
  if (who.school) return reasons.length === 0 ? left({ kind: 'private' }) : null;
  if (klass === 'cold') return reasons.length === 0 ? left({ kind: 'cold' }) : null;
  if (named === 'blizzard_warning') return reasons.length === 0 ? left({ kind: 'blizzard' }) : null;
  if (named === 'tropical') return reasons.length === 0 ? left({ kind: 'tropical' }) : null;
  if (read === null) return null;
  const file = source.file;
  if (source.unit.kind !== 'district') return null;
  const i = source.unit.index;
  const snowKlass = klass;
  if (read.fc !== null) {
    if (read.fc === 6) {
      // The bus hour timing served: today's sentence for each line, with its points.
      const lines = input.lines ?? [];
      if (reasons.length === 0 || lines.length !== reasons.length) return null;
      return reasons.map((reason, k) => ({
        key: `forecast-line-${String(k)}`,
        number: steps.stepPoints(reason.points),
        text: lines[k] ?? '',
        help: [],
        name: steps.foldName.forecast,
      }));
    }
    if (reasons.length > 0) return null;
    switch (read.fc) {
      case 0: {
        const { at, weekday } = snapshotOf(day, zones.school);
        return left({ kind: 'wait', at, weekday, chart: input.nightChart });
      }
      case 1:
        return left({ kind: 'fit' });
      case 2:
        return left({ kind: 'unread' });
      case 3:
        return left({ kind: 'school' });
      case 4:
        return left({ kind: 'check' });
      case 5:
        return left({ kind: 'nation', clause: clauseOf(source.forecastCheck[0]) });
      case 7:
        return left({ kind: 'off' });
      case 8:
        return left({ kind: 'noclimate' });
      case 9: {
        const usual = usualOf(file, snowKlass, i, who, input.detail.why?.base.points ?? 0);
        return usual === null
          ? null
          : left({ kind: 'nobalance', days: steps.usualDays(usual), p0: usual.p0 });
      }
      default:
        return null;
    }
  }
  if (read.snow === null) return null;
  if (!reasons.every((reason) => READ_KINDS.has(reason.kind))) return null;
  const usual = usualOf(file, snowKlass, i, who, input.detail.why?.base.points ?? 0);
  if (usual === null) return null;
  const said: ReadInput = {
    snow: read.snow,
    ice: read.ice,
    feels: read.feels,
    held: read.held,
    end: windowEnd(day),
  };
  const snowLine = reasons.find((reason) => reason.kind === 'snow_total');
  const iceLine = reasons.find((reason) => reason.kind === 'ice');
  const coldLine = reasons.find((reason) => reason.kind === 'wind_chill');
  if (iceLine !== undefined && read.ice === null) return null;
  if (coldLine !== undefined && read.feels === null) return null;
  const total = reasons.reduce((sum, reason) => sum + reason.points, 0);
  if (read.held === 'low' || read.held === 'floor') {
    if (read.held === 'floor' && usual.alone === null) return null;
    return [
      {
        key: 'forecast',
        number: steps.stepPoints(total),
        text: steps.netLine(said, who, zones),
        help: steps.netHelp(usual, said, named),
        name: steps.foldName.forecast,
      },
    ];
  }
  if (reasons.length === 0) {
    return [
      {
        key: 'forecast',
        number: '0',
        text: steps.netLine(said, who, zones),
        help: steps.snowHelp(usual, said, true),
        name: steps.foldName.forecast,
      },
    ];
  }
  const rows: StepRowView[] = [];
  // In the published order, the snow row always there (at "0" where its line is not).
  const shown: ReasonDetail[] = [...reasons];
  if (snowLine === undefined)
    shown.unshift({ kind: 'snow_total', points: 0 } as unknown as ReasonDetail);
  for (const reason of shown) {
    if (reason.kind === 'snow_total') {
      rows.push({
        key: 'forecast-snow',
        number: steps.stepPoints(reason.points),
        text: steps.snowLine(said, who, zones),
        help: steps.snowHelp(usual, said, reason.points === 0),
        name: steps.foldName.snow,
      });
    } else if (reason.kind === 'ice') {
      const ice = steps.iceLine(said, who, zones);
      rows.push({
        key: 'forecast-ice',
        number: steps.stepPoints(reason.points),
        text: ice.main,
        help: ice.help,
        name: steps.foldName.ice,
      });
    } else if (reason.kind === 'wind_chill' && read.feels !== null) {
      const cold = steps.coldLine(read.feels, who, true);
      rows.push({
        key: 'forecast-cold',
        number: steps.stepPoints(reason.points),
        text: cold.main,
        help: cold.help,
        name: steps.foldName.cold,
      });
    }
  }
  if (coldLine === undefined && read.feels !== null) {
    const cold = steps.coldLine(read.feels, who, false);
    rows.push({
      key: 'forecast-cold',
      number: '0',
      text: cold.main,
      help: cold.help,
      name: steps.foldName.cold,
    });
  }
  if (read.held === 'cap') {
    const last = rows.at(-1);
    if (last === undefined) return null;
    rows[rows.length - 1] = { ...last, help: [...last.help, steps.capHelp] };
  }
  return rows;
}

/** The usual snow's inputs for a district and class, or null where the file gives none. */
function usualOf(
  file: StandingFile,
  klass: 'advisory' | 'warning',
  i: number,
  who: StepWho,
  p0: number,
): UsualInput | null {
  const usual = file.usual[klass][i];
  if (usual === undefined || usual === null) return null;
  const alone = file.alone[klass][i] ?? null;
  const flags = file.flags[i] ?? 0;
  const own = file.own[klass][i];
  if (own === undefined) return null;
  return {
    who,
    klass,
    usual: usual / 100,
    alone: alone === null ? null : alone / 100,
    clamped: (flags & CLAMP[klass]) !== 0,
    p0,
    own,
    pool:
      (flags & POOL_NONE[klass]) !== 0
        ? 'none'
        : (flags & POOL_REGION[klass]) !== 0
          ? 'region'
          : 'county',
    since: file.climate_winters[0],
    whole: file.climate_window === 'whole',
  };
}
