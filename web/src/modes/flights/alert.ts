/**
 * A Flights alert's facts, read strictly (flights spec D12). The sender (pipeline/snowlight/notify
 * flights) sends facts, never words: the push worker (pwa/push.ts) and the accounts API's email
 * (api/src/google.ts) both read them here and say them in copy-trips.ts's words. Anything missing
 * or out of range reads as null, and nothing is said from it.
 */
import type { AlertBackup, AlertFacts, AlertKind, TicketKey } from '../../copy-trips.ts';

const KINDS: readonly AlertKind[] = ['chance', 'rise', 'fall', 'faa', 'safer', 'waiver', 'night'];
const PLAN_KINDS = ['same', 'other', 'nearby', 'hub'] as const;
const TICKETS: readonly TicketKey[] = ['basic', 'regular', 'premium', 'unsure'];
const LEVELS = ['low', 'delay', 'cancel'] as const;
const CARRIER = /^[A-Z0-9]{2}$/;
const AIRPORT = /^[A-Z0-9]{3}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const TRIP = /^[0-9a-f]{32}$/;
/**
 * At most this many backups ride in one alert, best first (flights_rules.py ALERT_CARRIED): a
 * push or email names the top live one or two (D18), so one shown late still has a later one.
 */
export const ALERT_CARRIED = 6;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function whole(value: unknown, min: number, max: number): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max
    ? value
    : null;
}

function text(value: unknown, pattern: RegExp): string | null {
  return typeof value === 'string' && pattern.test(value) ? value : null;
}

function backupOf(value: unknown): AlertBackup | null {
  if (!isRecord(value)) return null;
  const carrier = text(value.carrier, CARRIER);
  const number = whole(value.number, 1, 9999);
  const from = text(value.from, AIRPORT);
  const to = text(value.to, AIRPORT);
  const day = text(value.day, DAY);
  const leaves = whole(value.leaves, 0, 1439);
  const chance = whole(value.chance, 0, 100);
  if ([carrier, number, from, to, day, leaves, chance].includes(null)) return null;
  let via: AlertBackup['via'] = null;
  if (value.via !== null && value.via !== undefined) {
    if (!isRecord(value.via)) return null;
    const viaCarrier = text(value.via.carrier, CARRIER);
    const viaNumber = whole(value.via.number, 1, 9999);
    const hub = text(value.via.hub, AIRPORT);
    if (viaCarrier === null || viaNumber === null || hub === null) return null;
    via = { carrier: viaCarrier, number: viaNumber, hub };
  }
  const kind = PLAN_KINDS.find((key) => key === value.kind) ?? null;
  const miles =
    value.miles === null || value.miles === undefined ? null : whole(value.miles, 1, 500);
  if (miles === null && value.miles !== null && value.miles !== undefined) return null;
  return {
    carrier: carrier ?? '',
    number: number ?? 0,
    from: from ?? '',
    to: to ?? '',
    day: day ?? '',
    leaves: leaves ?? 0,
    chance: chance ?? 0,
    via,
    kind,
    miles,
    departs: whole(value.departs, 0, 2 ** 40) ?? 0,
  };
}

/** A Flights alert's facts (`kind: "flight"` payloads), or null. */
export function readAlert(data: unknown): AlertFacts | null {
  if (!isRecord(data) || data.v !== 1 || data.kind !== 'flight') return null;
  const alert = KINDS.find((kind) => kind === data.alert);
  const ticket = TICKETS.find((key) => key === data.ticket) ?? 'unsure';
  const trip = text(data.trip, TRIP);
  const carrier = text(data.carrier, CARRIER);
  const number = whole(data.number, 1, 9999);
  const from = text(data.from, AIRPORT);
  const to = text(data.to, AIRPORT);
  const day = text(data.day, DAY);
  const leaves = whole(data.leaves, 0, 1439);
  if (
    alert === undefined ||
    trip === null ||
    carrier === null ||
    number === null ||
    from === null ||
    to === null ||
    day === null ||
    leaves === null
  )
    return null;
  const cancel = data.cancel === null ? null : whole(data.cancel, 0, 100);
  const late = data.late === null ? null : whole(data.late, 0, 100);
  if (cancel === null && data.cancel !== null) return null;
  if (late === null && data.late !== null) return null;
  const level = data.level === null ? null : (LEVELS.find((key) => key === data.level) ?? null);
  const why = data.why === null || data.why === undefined ? null : whole(data.why, 0, 31);
  const whyAt = why === null ? null : text(data.why_at, AIRPORT);
  const at = whole(data.at, 0, 2 ** 40);
  let checked: AlertFacts['checked'] = null;
  if (isRecord(data.checked)) {
    const checkedDay = text(data.checked.day, DAY);
    const minute = whole(data.checked.minute, 0, 1439);
    if (checkedDay !== null && minute !== null) checked = { day: checkedDay, minute };
  }
  let faa: AlertFacts['faa'] = null;
  if (isRecord(data.faa)) {
    const airport = text(data.faa.airport, AIRPORT);
    const program = whole(data.faa.program, 0, 7);
    if (airport === null || program === null) return null;
    const until =
      data.faa.until === null || data.faa.until === undefined
        ? null
        : whole(data.faa.until, 0, 1439);
    if (until === null && data.faa.until !== null && data.faa.until !== undefined) return null;
    faa = { airport, program, until };
  }
  let waiver: AlertFacts['waiver'] = null;
  if (isRecord(data.waiver)) {
    const state = data.waiver.state;
    if (state !== 'waiver' && state !== 'unclear') return null;
    waiver = {
      state,
      basic: data.waiver.basic === true,
      airport: text(data.waiver.airport, AIRPORT),
    };
  }
  // An alert must carry what it is about: never a waiver or FAA alert with nothing to say.
  if (alert === 'faa' && faa === null) return null;
  if (alert === 'waiver' && waiver === null) return null;
  // An evening check may carry no chance (no current forecast: it says so, never an old one).
  if ((alert === 'chance' || alert === 'rise' || alert === 'fall') && cancel === null) return null;
  const backups: AlertBackup[] = [];
  // More plans past the ones read: only a plain false from the sender says there are none (a
  // missing flag, a cut list or a dropped plan never reads as "no safer flight left").
  let more = data.more !== false;
  if (Array.isArray(data.backups)) {
    const items = data.backups as unknown[];
    if (items.length > ALERT_CARRIED) more = true;
    for (const item of items.slice(0, ALERT_CARRIED)) {
      // A backup without its departure time is never named: it could have left.
      if (isRecord(item) && whole(item.departs, 0, 2 ** 40) === null) {
        more = true;
        continue;
      }
      const backup = backupOf(item);
      if (backup === null) return null;
      backups.push(backup);
    }
  }
  return {
    alert,
    trip,
    carrier,
    number,
    from,
    to,
    day,
    leaves,
    cancel,
    late,
    level,
    why,
    whyAt,
    at,
    checked,
    faa,
    waiver,
    backups,
    more,
    ticket,
    noForecast: alert === 'night' && cancel === null && data.no_forecast === true,
  };
}
