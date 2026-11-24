/**
 * Backup plans, the ticket advice, the found flights (calendar and Gmail), the alert facts and
 * their words (flights spec D18, D19, D12) on SYNTHETIC files and made-up emails: nothing here
 * is a real day, a real email or a real airline page.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import {
  BACKUP_LEAD_S,
  NEARBY_LEAD_S,
  alertBody,
  alertEmail,
  alertRings,
  liveBackups,
  settingTime,
  tripWhen,
  tripsCopy,
  type AlertFacts,
} from '../../../copy-trips';
import type {
  FlightsAirportLive,
  FlightsRoutes,
  FlightsUsualFlight,
} from '../../../types/generated';
import { ALERT_CARRIED, readAlert } from '../alert';
import { instantOf } from '../chance';
import SENT from './alert-facts.json';
import {
  BACKUP_LEAD,
  NEARBY_LEAD,
  backupPlans,
  deadline,
  looksRisky,
  nearby,
  planChance,
  rankPlans,
  SAFER_POINTS,
  tripPlan,
  type Plan,
  type PlanKind,
  type PlanInputs,
  type TripLike,
} from '../backup';
import type { Airport, WaiverState } from '../data';
import { fromCalendar, matchFound, type FoundFlight } from '../found';
import { flightsInEmail, ticketOf } from '../gmail';
import { adviceFor } from '../ticket';
import { takeGoogleReturn, GOOGLE_RETURN_KEY } from '../trips';
import { airportLive, DEN, LAX, MCI } from './fixtures';

/** The value, or the test fails here. */
function must<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) throw new Error('missing');
  return value;
}

const MKC: Airport = {
  ...MCI,
  code: 'MKC',
  name: 'Downtown',
  lat: 39.1232,
  lon: -94.5928,
  perDay: 20,
};
const BUR: Airport = {
  ...LAX,
  code: 'BUR',
  name: 'Burbank',
  lat: 34.2007,
  lon: -118.3585,
  perDay: 120,
};
const AIRPORTS = new Map([MCI, MKC, LAX, BUR, DEN].map((a) => [a.code, a]));

/** Mon, Jan 5, 2026, 6 am in Kansas City. */
const NOW = Date.parse('2026-01-05T12:00:00Z');
const TODAY = '2026-01-05';
const DAY = '2026-01-06';

function f(
  carrier: string,
  number: number,
  to: string,
  leaves: number,
  lands: number,
  weekdays = 127,
): FlightsUsualFlight {
  return {
    carrier,
    number,
    to_airport: to,
    leaves,
    lands,
    weekdays,
    days: 20,
    cancelled: 0,
    late: 0,
  };
}

function routes(code: string, flights: FlightsUsualFlight[]): FlightsRoutes {
  return {
    schema_version: 1,
    generated_at: '2026-01-05T00:00:00Z',
    code,
    months: [{ month: '2025-09', flights }],
  };
}

/** MCI with a bad early block tomorrow (30% cancel), calm later. */
const RISKY_ROW: [number, number, number, number, number] = [300, 40, 20, 20, 20];
function live(): Map<string, FlightsAirportLive> {
  const calm = (code: string) => airportLive(code, TODAY);
  const mci = airportLive('MCI', TODAY, {
    dep_canc: [[10, 12, 15, 20, 18], RISKY_ROW, [10, 12, 15, 20, 18]],
  });
  return new Map([
    ['MCI', mci],
    ['MKC', calm('MKC')],
    ['LAX', calm('LAX')],
    ['BUR', calm('BUR')],
    ['DEN', calm('DEN')],
  ]);
}

const TRIP: TripLike = {
  carrier: 'WN',
  number: 1234,
  from: 'MCI',
  to: 'LAX',
  day: DAY,
  leaves: 370,
  lands: 470,
  needBy: null,
};

function inputs(trip: TripLike = TRIP): PlanInputs {
  return {
    trip,
    airports: AIRPORTS,
    now: NOW,
    live: live(),
    routes: new Map([
      [
        'MCI',
        routes('MCI', [
          f('WN', 1234, 'LAX', 370, 470),
          f('WN', 1500, 'LAX', 545, 645),
          f('AA', 2200, 'LAX', 600, 700),
          f('WN', 77, 'BUR', 615, 715),
          f('WN', 300, 'DEN', 420, 480),
          f('UA', 9, 'LAX', 400, 500, 0b1000000),
        ]),
      ],
      ['MKC', routes('MKC', [f('G4', 50, 'LAX', 700, 800)])],
      [
        'DEN',
        routes('DEN', [
          f('WN', 400, 'LAX', 600, 700),
          f('WN', 401, 'LAX', 510, 610),
          f('WN', 402, 'LAX', 930, 1030),
        ]),
      ],
    ]),
  };
}

describe('Backup plans (D18)', () => {
  it('finds nearby airports by straight line within 120 miles, nearest first', () => {
    const near = nearby(AIRPORTS, 'MCI');
    expect(near.map((row) => row.code)).toEqual(['MKC']);
    expect(near[0]?.miles).toBeGreaterThan(10);
    expect(near[0]?.miles).toBeLessThan(20);
    expect(nearby(AIRPORTS, 'LAX').map((row) => row.code)).toEqual(['BUR']);
  });

  it('builds same-airline, other-airline, nearby and one-stop plans, and never the trip itself', () => {
    const plans = backupPlans(inputs());
    const keys = plans.map(
      (plan) =>
        `${plan.kind}:${plan.legs.map((l) => `${l.carrier}${String(l.number)}@${l.day}`).join('+')}`,
    );
    expect(keys).toContain(`same:WN1500@${DAY}`);
    // The day before's WN 1234 leaves 10 minutes from now: too soon to change to (TRAV-R3-B3).
    expect(keys).not.toContain(`same:WN1234@${TODAY}`);
    const early = backupPlans({ ...inputs(), now: Date.parse(`${TODAY}T09:00:00Z`) });
    expect(early.some((plan) => plan.legs[0]?.number === 1234 && plan.legs[0].day === TODAY)).toBe(
      true,
    );
    expect(keys).toContain(`other:AA2200@${DAY}`);
    expect(keys).toContain(`nearby:WN77@${DAY}`);
    expect(keys).toContain(`nearby:G450@${DAY}`);
    expect(keys).not.toContain(`same:WN1234@${DAY}`);
    // A flight that does not fly that weekday is no plan (UA 9 flies Sundays only).
    expect(keys.some((key) => key.includes('UA9'))).toBe(false);
  });

  it('keeps only legal layovers of 1 to 4 hours', () => {
    const hubs = backupPlans(inputs()).filter((plan) => plan.kind === 'hub');
    // WN 300 lands at DEN 8:00 am DEN time: WN 400 at 10:00 (2 h) is legal, 8:30 (30 min) and
    // 3:30 pm (7.5 h) are not.
    expect(hubs.map((plan) => plan.legs.map((l) => l.number))).toEqual([[300, 400]]);
  });

  it('ranks the safer plans same airline first, then by chance (D11), as the alerts do', () => {
    const plans = backupPlans(inputs());
    const own = must(tripPlan(inputs()));
    const order: Record<PlanKind, number> = { same: 0, other: 1, nearby: 2, hub: 3 };
    const safer = plans.filter((plan) => plan.chance >= own.chance + SAFER_POINTS);
    const rest = plans.slice(safer.length);
    expect(plans.slice(0, safer.length)).toEqual(safer);
    for (let i = 1; i < safer.length; i += 1) {
      const [a, b] = [must(safer[i - 1]), must(safer[i])];
      expect(order[a.kind] < order[b.kind] || (a.kind === b.kind && a.chance >= b.chance)).toBe(
        true,
      );
    }
    for (let i = 1; i < rest.length; i += 1)
      expect(must(rest[i - 1]).chance >= must(rest[i]).chance).toBe(true);
  });

  it('lists a same-airline plan 1 point lower before another airline (the case flights_rules.py shares)', () => {
    const plan = (kind: PlanKind, carrier: string, number: number, chance: number): Plan => ({
      kind,
      legs: [
        {
          carrier,
          number,
          from: 'MCI',
          to: kind === 'nearby' ? 'BUR' : 'LAX',
          day: DAY,
          leaves: 600,
          lands: 700,
          arrives: 0,
          cancel: 1,
          late: 1,
        },
      ],
      chance,
      dayBefore: false,
      miles: null,
    });
    const ranked = rankPlans(
      [
        plan('other', 'AA', 88, 92),
        plan('hub', 'WN', 300, 93),
        plan('same', 'WN', 1500, 91),
        plan('other', 'DL', 5, 72),
        plan('nearby', 'WN', 77, 92),
        plan('same', 'WN', 1, 70),
      ],
      65,
    );
    expect(ranked.map((p) => `${p.legs[0]?.carrier ?? ''}${String(p.legs[0]?.number)}`)).toEqual([
      'WN1500',
      'AA88',
      'WN77',
      'WN300',
      'DL5',
      'WN1',
    ]);
  });

  it('ranks by the rough chance, from the shown percents multiplied across legs', () => {
    const plans = backupPlans(inputs());
    const own = tripPlan(inputs());
    expect(own?.legs[0]?.cancel).toBe(31);
    expect(looksRisky(own)).toBe(true);
    expect(plans[0]?.chance).toBeGreaterThan(own?.chance ?? 100);
    expect(planChance([{ ...must(must(own).legs[0]), cancel: 0, late: 0 }])).toBe(99);
    const hub = plans.find((plan) => plan.kind === 'hub');
    const [a, b] = hub?.legs ?? [];
    expect(hub?.chance).toBe(
      Math.round(
        ((100 - must(a).cancel) / 100) *
          ((100 - must(a).late) / 100) *
          ((100 - must(b).cancel) / 100) *
          ((100 - must(b).late) / 100) *
          100,
      ),
    );
  });

  it('with a need-by time, drops plans that land too late', () => {
    const due = `${DAY}T10:45`;
    const plans = backupPlans(inputs({ ...TRIP, needBy: due }));
    const limit = deadline(due, LAX.tz) ?? 0;
    expect(plans.length).toBeGreaterThan(0);
    for (const plan of plans)
      expect(plan.legs.at(-1)?.arrives ?? Infinity).toBeLessThanOrEqual(limit);
    expect(plans.some((plan) => plan.legs[0]?.number === 77)).toBe(false);
  });

  it('offers only flights that leave 2 hours on, 3 from a nearby airport (TRAV-R3-B3)', () => {
    const lead = (plan: { legs: readonly { day: string; leaves: number; from: string }[] }) => {
      const first = plan.legs[0];
      const zone = first?.from === 'MKC' ? MCI.tz : first?.from === 'DEN' ? DEN.tz : MCI.tz;
      return first === undefined ? 0 : instantOf(first.day, first.leaves, zone).getTime();
    };
    // WN 1500 leaves Jan 6 at 9:05 am in Kansas City (15:05Z).
    const soon = { ...inputs(), now: Date.parse(`${DAY}T13:10:00Z`) };
    expect(backupPlans(soon).some((plan) => plan.legs[0]?.number === 1500)).toBe(false);
    const inTime = { ...inputs(), now: Date.parse(`${DAY}T13:00:00Z`) };
    expect(backupPlans(inTime).some((plan) => plan.legs[0]?.number === 1500)).toBe(true);
    for (const plan of backupPlans(inTime)) {
      const near = plan.legs[0]?.from !== 'MCI';
      expect(lead(plan) - inTime.now).toBeGreaterThanOrEqual((near ? 3 : 2) * 3_600_000);
    }
  });

  it('leaves out flights that have already left and days with no forecast', () => {
    const later = { ...inputs(), now: Date.parse(`${DAY}T16:00:00Z`) };
    expect(backupPlans(later).some((plan) => plan.legs[0]?.number === 1500)).toBe(false);
    const far = inputs({ ...TRIP, day: '2026-01-12' });
    expect(backupPlans(far)).toEqual([]);
    expect(tripPlan(far)).toBeNull();
  });
});

describe('the money words and no price or seat claims (D18)', () => {
  const words = [
    tripsCopy.backup.money,
    ...tripsCopy.backup.rules,
    tripsCopy.backup.mustGo,
    tripsCopy.backup.hint,
    ...Object.values(tripsCopy.advice),
  ];
  it('says we see no prices or seats, and the plain rules', () => {
    expect(tripsCopy.backup.money).toBe(
      'We don’t see prices or seats. Check with the airline before you switch.',
    );
    expect(tripsCopy.backup.rules.join(' ')).toMatch(/money back/);
  });
  it('never claims a seat, a fare, a sale or a sure thing', () => {
    for (const line of words) {
      expect(line).not.toMatch(
        /\$\d|seats? (?:left|open|available)|on sale|guarantee|sure to|will make it/i,
      );
    }
  });
});

const W = (state: WaiverState['state']): WaiverState =>
  state === 'not_checked'
    ? { state, airline: 'Southwest' }
    : { state, airline: 'Southwest', minutes: 12 };

describe('the advice by ticket type (D19) and the waiver (W8)', () => {
  it('regular and premium: no change fee, pay the difference', () => {
    for (const ticket of ['regular', 'premium'] as const) {
      const advice = adviceFor(ticket, [W('none_found')]);
      expect(advice.lines[0]).toBe(tripsCopy.advice.regular);
      expect(advice.lines).toContain(tripsCopy.advice.watching);
      expect(advice.mustGo).toBe(false);
    }
  });
  it('basic: leads with waiting for a waiver or a cancel, and the must-get-there backup', () => {
    const advice = adviceFor('basic', [W('none_found')]);
    expect(advice.lines[0]).toBe(tripsCopy.advice.basic);
    expect(advice.mustGo).toBe(true);
  });
  it('not sure: both', () => {
    expect(adviceFor('unsure', [W('none_found')]).lines[0]).toBe(tripsCopy.advice.unsure);
  });
  it('a waiver found leads with a free change, but never for basic economy unless the waiver says so', () => {
    expect(adviceFor('regular', [W('waiver')]).lines[0]).toMatch(/^You can change for free\./);
    expect(adviceFor('regular', [W('waiver')]).free).toBe(true);
    const basic = adviceFor('basic', [W('waiver')]);
    expect(basic.free).toBe(false);
    expect(basic.lines.join(' ')).not.toMatch(/You can change for free/);
    expect(adviceFor('basic', [W('waiver')], true).lines[0]).toMatch(/even for basic economy/);
  });
  it('unclear and not checked never read as none found', () => {
    expect(adviceFor('regular', [W('not_checked')]).lines).not.toContain(tripsCopy.advice.watching);
    expect(adviceFor('regular', [W('not_checked')]).lines[1]).toMatch(/could not check Southwest/);
    expect(adviceFor('regular', [W('unclear')]).lines[1]).toMatch(/could not tell if it covers/);
  });
});

describe('found flights (calendar, Gmail) matched to the usual flights', () => {
  const mci = inputs().routes.get('MCI') ?? null;
  it('reads a calendar event and matches it by its time', () => {
    const found = fromCalendar(
      {
        summary: 'Flight to Los Angeles (WN 1234)',
        location: 'Kansas City MCI',
        description: '',
        start: '2026-01-06T06:10:00-06:00',
        start_day: null,
        zone: 'America/Chicago',
        end: null,
      },
      AIRPORTS,
    );
    expect(found).toMatchObject({
      carrier: 'WN',
      number: 1234,
      from: 'MCI',
      day: DAY,
      minute: 370,
    });
    const match = matchFound(must(found), mci);
    expect(match.state).toBe('matched');
    if (match.state === 'matched')
      expect(match.trip).toMatchObject({ to: 'LAX', leaves: 370, lands: 470, source: 'calendar' });
  });
  it('ignores an event that names no flight', () => {
    expect(
      fromCalendar(
        {
          summary: 'Dentist',
          location: 'MCI',
          description: '',
          start: null,
          start_day: DAY,
          zone: null,
          end: null,
        },
        AIRPORTS,
      ),
    ).toBeNull();
  });
  it('asks which leg when one number makes more than one stop that day', () => {
    const twoLegs = routes('MCI', [f('WN', 88, 'DEN', 400, 460), f('WN', 88, 'LAX', 400, 560)]);
    const found: FoundFlight = {
      carrier: 'WN',
      number: 88,
      from: 'MCI',
      to: null,
      day: DAY,
      minute: null,
      ticket: 'unsure',
      source: 'gmail',
    };
    const match = matchFound(found, twoLegs);
    expect(match.state).toBe('pick');
    if (match.state === 'pick') expect(match.options.map((o) => o.to)).toEqual(['DEN', 'LAX']);
    expect(matchFound({ ...found, to: 'LAX' }, twoLegs).state).toBe('matched');
  });
  it('says plainly when it cannot match', () => {
    expect(
      matchFound(
        {
          carrier: 'WN',
          number: 9999,
          from: 'MCI',
          to: null,
          day: DAY,
          minute: null,
          ticket: 'unsure',
          source: 'gmail',
        },
        mci,
      ).state,
    ).toBe('none');
    expect(
      matchFound(
        {
          carrier: 'WN',
          number: 1234,
          from: null,
          to: null,
          day: DAY,
          minute: null,
          ticket: 'unsure',
          source: 'gmail',
        },
        mci,
      ).state,
    ).toBe('none');
  });
});

/** A made-up confirmation email with schema.org FlightReservation markup. */
function email(reservations: object[], text: string): string {
  return `<html><head><script type="application/ld+json">${JSON.stringify(reservations)}</script></head><body><p>${text}</p></body></html>`;
}
function reservation(
  carrier: string,
  number: string,
  from: string,
  to: string,
  at: string,
  seat?: string,
): object {
  return {
    '@context': 'http://schema.org',
    '@type': 'FlightReservation',
    reservationNumber: 'XXXXXX',
    ...(seat === undefined ? {} : { airplaneSeatClass: seat }),
    reservationFor: {
      '@type': 'Flight',
      flightNumber: number,
      airline: { '@type': 'Airline', iataCode: carrier },
      departureAirport: { '@type': 'Airport', iataCode: from },
      arrivalAirport: { '@type': 'Airport', iataCode: to },
      departureTime: at,
    },
  };
}

describe('the Gmail parser (D19, demo only, on the device)', () => {
  it('reads the markup first, and the airline’s fare words from the checked table', () => {
    const found = flightsInEmail(
      {
        html: email(
          [reservation('AA', '2200', 'MCI', 'LAX', '2026-01-06T10:00:00-06:00')],
          'Your trip. Fare: Main Cabin.',
        ),
      },
      AIRPORTS,
    );
    expect(found).toEqual([
      {
        carrier: 'AA',
        number: 2200,
        from: 'MCI',
        to: 'LAX',
        day: DAY,
        minute: 600,
        ticket: 'regular',
        source: 'gmail',
      },
    ]);
    expect(ticketOf('AA', null, 'Basic Economy ticket')).toBe('basic');
  });
  it('gives Not sure for a word not in the table, or two answers at once', () => {
    expect(ticketOf('WN', null, 'Wanna Get Away fare')).toBe('unsure');
    expect(ticketOf('AA', null, 'Main Cabin. Want Basic Economy next time?')).toBe('unsure');
  });
  it('takes a premium cabin from the markup whatever the fare is called', () => {
    expect(ticketOf('DL', 'First', '')).toBe('premium');
    expect(ticketOf('DL', 'Economy', '')).toBe('unsure');
  });
  it('reads a two-leg trip as two flights', () => {
    const found = flightsInEmail(
      {
        html: email(
          [
            reservation('WN', 'WN300', 'MCI', 'DEN', '2026-01-06T07:00:00-06:00'),
            reservation('WN', '400', 'DEN', 'LAX', '2026-01-06T10:00:00-07:00'),
          ],
          'Itinerary',
        ),
      },
      AIRPORTS,
    );
    expect(
      found.map(
        (leg) =>
          `${leg.carrier}${String(leg.number)} ${leg.from ?? ''}-${leg.to ?? ''} ${String(leg.minute)}`,
      ),
    ).toEqual(['WN300 MCI-DEN 420', 'WN400 DEN-LAX 600']);
  });
  it('ignores an email that is not an airline confirmation', () => {
    expect(
      flightsInEmail(
        { html: '<p>Your order has shipped. WN 1234 is not a flight here.</p>' },
        AIRPORTS,
      ),
    ).toEqual([]);
    expect(
      flightsInEmail(
        {
          html: email(
            [{ '@type': 'LodgingReservation', reservationFor: { name: 'Hotel' } }],
            'Hotel',
          ),
        },
        AIRPORTS,
      ),
    ).toEqual([]);
    expect(
      flightsInEmail({ html: '<script type="application/ld+json">{not json</script>' }, AIRPORTS),
    ).toEqual([]);
  });
});

const FACTS = {
  v: 1,
  kind: 'flight',
  alert: 'chance',
  trip: '0123456789abcdef0123456789abcdef',
  carrier: 'WN',
  number: 1234,
  from: 'MCI',
  to: 'LAX',
  day: DAY,
  leaves: 370,
  cancel: 31,
  late: 12,
  level: 'cancel',
  why: 0,
  faa: null,
  waiver: null,
  backups: [
    {
      carrier: 'WN',
      number: 1500,
      from: 'MCI',
      to: 'LAX',
      day: DAY,
      leaves: 545,
      chance: 88,
      via: null,
    },
  ],
  ticket: 'basic',
};

describe('alert facts and their words (D12)', () => {
  it('reads strictly', () => {
    expect(readAlert(FACTS)).not.toBeNull();
    expect(readAlert({ ...FACTS, v: 2 })).toBeNull();
    expect(readAlert({ ...FACTS, cancel: 101 })).toBeNull();
    expect(readAlert({ ...FACTS, carrier: 'wn' })).toBeNull();
    expect(readAlert({ ...FACTS, alert: 'faa', faa: null })).toBeNull();
    expect(readAlert({ ...FACTS, alert: 'waiver' })).toBeNull();
    expect(readAlert({ ...FACTS, backups: [{ carrier: 'WN', departs: 1 }] })).toBeNull();
    // A backup without its departure time is never named (it could have left).
    const undated: Record<string, unknown> = { ...SENT.chance.backups[0] };
    delete undated.departs;
    expect(must(readAlert({ ...SENT.chance, backups: [undated] })).backups).toEqual([]);
  });
  it('a late push never names a backup that has left or is about to (TRAV-R3-B3)', () => {
    const facts = must(readAlert(SENT.chance_day_early));
    const first = facts.backups[0];
    if (first === undefined) throw new Error('no backup');
    const sentAt = facts.at ?? 0;
    // The sender names only flights 2 hours on: shown on time, the backup is said.
    expect(first.departs - sentAt).toBeGreaterThanOrEqual(2 * 3600);
    expect(alertBody(facts, sentAt + 60)).toContain(
      `Leave a day early: WN ${String(first.number)},`,
    );
    // Shown under 2 hours before it leaves, or after: never named (the sender's own lead).
    const late = first.departs - 119 * 60;
    expect(liveBackups(facts, late).map((b) => b.number)).not.toContain(first.number);
    expect(liveBackups(facts, first.departs - 120 * 60)).toHaveLength(facts.backups.length);
    expect(alertBody(facts, first.departs + 300)).not.toContain(`WN ${String(first.number)},`);
    // A nearby airport needs 3 hours.
    const near = { ...facts, backups: [{ ...first, from: 'MKC' }] };
    expect(liveBackups(near, first.departs - 179 * 60)).toEqual([]);
    expect(liveBackups(near, first.departs - 180 * 60)).toHaveLength(1);
    // The email, sent at once, says the same backups; read later, it drops the gone ones.
    expect(alertEmail(facts, 'https://snowlightmap.com/', first.departs).text).not.toContain(
      `WN ${String(first.number)},`,
    );
  });
  it('a push shown 30 or 45 minutes late drops a backup that was 2 h 05 min out when sent, and says none is left (TRAV-R4-B1, B2)', () => {
    const sent = must(readAlert(SENT.chance));
    const at = must(sent.at);
    const first = must(sent.backups[0]);
    const facts: AlertFacts = { ...sent, backups: [{ ...first, departs: at + 125 * 60 }] };
    const name = `WN ${String(first.number)} at`;
    // On time: named, with the money words.
    expect(alertBody(facts, at)).toContain(name);
    for (const lateBy of [10, 30, 45]) {
      const body = alertBody(facts, at + lateBy * 60);
      expect(body).not.toContain(name);
      expect(body).not.toContain(tripsCopy.backup.money);
      expect(body).toContain(tripsCopy.alert.noBackup);
      const mail = alertEmail(facts, 'https://snowlightmap.com/', at + lateBy * 60);
      expect(mail.text).not.toContain(name);
      expect(mail.text).toContain(tripsCopy.alert.noBackup);
      expect(mail.html).toContain(tripsCopy.alert.noBackup);
    }
    // A nearby airport's 3 hours: 3 h 05 min out when sent, gone 10 minutes later.
    const near: AlertFacts = {
      ...sent,
      backups: [{ ...first, from: 'MKC', departs: at + 185 * 60 }],
    };
    expect(liveBackups(near, at)).toHaveLength(1);
    expect(liveBackups(near, at + 10 * 60)).toEqual([]);
  });
  it('a trip at risk with no backup says so; a safer alert whose flight is gone never says safer (TRAV-R4-B2)', () => {
    const none = (name: keyof typeof SENT): AlertFacts => ({
      ...must(readAlert(SENT[name])),
      backups: [],
    });
    for (const name of ['chance', 'rise', 'night'] as const) {
      const facts = none(name);
      if (facts.level !== 'delay' && facts.level !== 'cancel') continue;
      expect(alertBody(facts)).toContain(tripsCopy.alert.noBackup);
      expect(alertBody(facts)).not.toContain(tripsCopy.backup.money);
      const mail = alertEmail(facts, 'https://snowlightmap.com/');
      expect(mail.text).toContain(`${tripsCopy.email.backups}:\n${tripsCopy.alert.noBackup}`);
      expect(mail.html).toContain(tripsCopy.alert.noBackup);
    }
    // A fall, a waiver and a low trip say nothing of backups.
    expect(alertBody(none('fall'))).not.toContain(tripsCopy.alert.noBackup);
    expect(alertBody(none('waiver_basic'))).not.toContain(tripsCopy.alert.noBackup);
    expect(alertBody({ ...none('chance'), level: 'low' })).not.toContain(tripsCopy.alert.noBackup);
    // Named backups: no such line.
    expect(alertBody(must(readAlert(SENT.chance)))).not.toContain(tripsCopy.alert.noBackup);
    // A safer alert shown after its safer flights left reads as the trip's chance, never "safer".
    const safer = must(readAlert(SENT.safer));
    const lastDeparts = Math.max(...safer.backups.map((b) => b.departs));
    const gone = alertBody(safer, lastDeparts);
    expect(gone).not.toContain(tripsCopy.alert.safer);
    expect(gone).toContain('Leaves Tue, Jan 6 at 10:00 am. 31% chance');
    expect(gone).toContain(tripsCopy.alert.noBackup);
    const goneMail = alertEmail(safer, 'https://snowlightmap.com/', lastDeparts);
    expect(goneMail.text).not.toContain(tripsCopy.alert.safer);
    expect(goneMail.text).toContain(tripsCopy.alert.noBackup);
    // Shown on time it still says safer, and names the flight.
    expect(alertBody(safer, must(safer.at))).toMatch(/^Another usual flight looks safer\./);
  });
  it('a push or email shown 21 to 45 minutes late, whose top two have left, names a later safer flight, never "none left" (TRAV-R5-B1)', () => {
    // The sender's own facts: its top two (same airline) leave 2 h 05 min and 2 h 20 min on; it
    // carries the next best and says it found more.
    const sent = must(readAlert(SENT.chance_late));
    const at = must(sent.at);
    expect(sent.backups.length).toBeGreaterThanOrEqual(3);
    expect(sent.more).toBe(true);
    expect(sent.backups.slice(0, 2).map((b) => [b.number, b.departs - at])).toEqual([
      [1500, 125 * 60],
      [1600, 140 * 60],
    ]);
    const today = (n: number): string => `WN ${String(n)}, Mon, Jan 5`;
    // On time: the top one, today.
    expect(alertBody(sent, at)).toContain(`Leave a day early: ${today(1500)} at 3:00 pm`);
    for (const alert of ['chance', 'safer'] as const) {
      const facts: AlertFacts = { ...sent, alert };
      for (const lateBy of [21, 25, 30, 40, 45]) {
        const now = at + lateBy * 60;
        const body = alertBody(facts, now);
        expect(body).not.toContain(tripsCopy.alert.noBackup);
        expect(body).not.toContain(tripsCopy.alert.backupsGone);
        expect(body).not.toContain(today(1500));
        expect(body).not.toContain(today(1600));
        // The same airline still comes first: WN 1500 the trip's own day, safer and still ahead.
        expect(body).toContain('Safer: WN 1500 at 3:00 pm, 91% chance to get there on time.');
        expect(body).toContain(tripsCopy.backup.money);
        // A safer alert whose new flight (the best of its top two) has left names an older one,
        // often one the last alert named: it reads as the chance, without a sound (TRAV-R6-S2).
        expect(body).not.toContain(tripsCopy.alert.safer);
        expect(alertRings(facts, now)).toBe(alert !== 'safer');
        const mail = alertEmail(facts, 'https://snowlightmap.com/', now);
        for (const text of [mail.text, mail.html]) {
          expect(text).not.toContain(tripsCopy.alert.noBackup);
          expect(text).toContain('WN 1500 at 3:00 pm');
          expect(text).toContain('WN 1600 at 3:15 pm');
        }
      }
    }
  });
  it('rings a late safer alert only while the flight that made it can still be caught (TRAV-R6-S2)', () => {
    const sent = must(readAlert(SENT.chance_late));
    const at = must(sent.at);
    const [first, second, ...rest] = sent.backups;
    // The same airline first at 80%, then another airline at 91%: the 91% one made the alert.
    const named = [
      { ...must(first), chance: 80, departs: at + 125 * 60 },
      { ...must(second), carrier: 'AA', number: 77, chance: 91, departs: at + 160 * 60 },
    ];
    const safer: AlertFacts = { ...sent, alert: 'safer', backups: [...named, ...rest] };
    // On time, and once the same airline's has left while the new one is still ahead: it rings
    // and says a safer flight.
    for (const lateBy of [0, 10, 30]) {
      expect(alertRings(safer, at + lateBy * 60)).toBe(true);
      expect(alertBody(safer, at + lateBy * 60)).toMatch(/^Another usual flight looks safer\./);
    }
    expect(alertBody(safer, at + 30 * 60)).toContain('AA 77, Mon, Jan 5 at 3:15 pm, 91%');
    // Once the new one has left (under 2 h before it leaves), even with the older one still
    // ahead: no sound, worded as the chance, and never as a safer flight.
    const swapped: AlertFacts = {
      ...safer,
      backups: [
        { ...named[0], departs: at + 160 * 60 },
        { ...named[1], departs: at + 125 * 60 },
        ...rest,
      ] as typeof safer.backups,
    };
    for (const lateBy of [6, 30, 45]) {
      const now = at + lateBy * 60;
      expect(alertRings(swapped, now)).toBe(false);
      const body = alertBody(swapped, now);
      expect(body).not.toContain(tripsCopy.alert.safer);
      expect(body).not.toContain('AA 77');
      expect(alertEmail(swapped, 'https://snowlightmap.com/', now).text).not.toContain(
        tripsCopy.alert.safer,
      );
    }
    // Any other alert rings when shown late: each is a real change.
    for (const alert of ['chance', 'rise', 'fall', 'night', 'faa', 'waiver'] as const)
      expect(alertRings({ ...swapped, alert }, at + 45 * 60)).toBe(true);
  });
  it('says no safer flight is left only when the sender found none past the ones that left (TRAV-R5-B1)', () => {
    const sent = must(readAlert(SENT.chance_late));
    const last = Math.max(...sent.backups.map((b) => b.departs));
    // Every carried plan gone, and the sender found more: it says so and points to the trip.
    for (const alert of ['chance', 'safer', 'rise'] as const) {
      const facts: AlertFacts = { ...sent, alert };
      const body = alertBody(facts, last);
      expect(body).toContain(tripsCopy.alert.backupsGone);
      expect(body).not.toContain(tripsCopy.alert.noBackup);
      expect(body).not.toContain(tripsCopy.alert.safer);
      const mail = alertEmail(facts, 'https://snowlightmap.com/', last);
      expect(mail.text).toContain(`${tripsCopy.email.backups}:\n${tripsCopy.alert.backupsGone}`);
      expect(mail.text).not.toContain(tripsCopy.alert.noBackup);
      expect(mail.html).toContain(tripsCopy.alert.backupsGone);
    }
    // Every plan it found gone, and no more: none left is so.
    const all: AlertFacts = { ...sent, more: false };
    expect(alertBody(all, last)).toContain(tripsCopy.alert.noBackup);
    expect(alertBody(all, last)).not.toContain(tripsCopy.alert.backupsGone);
    // The sender's own list was empty: none left.
    expect(alertBody({ ...sent, backups: [], more: false }, must(sent.at))).toContain(
      tripsCopy.alert.noBackup,
    );
    // A missing flag, a cut list or an undated plan never reads as none left.
    const noFlag: Record<string, unknown> = { ...SENT.chance_late };
    delete noFlag.more;
    expect(must(readAlert(noFlag)).more).toBe(true);
    expect(must(readAlert({ ...SENT.chance_late, more: false })).more).toBe(false);
    const seven = [...SENT.chance_late.backups, SENT.chance_late.backups[0]];
    const cut = must(readAlert({ ...SENT.chance_late, backups: seven, more: false }));
    expect(cut.backups).toHaveLength(6);
    expect(cut.more).toBe(true);
    const undated: Record<string, unknown> = { ...SENT.chance.backups[0] };
    delete undated.departs;
    const dropped = must(readAlert({ ...SENT.chance, backups: [undated], more: false }));
    expect(dropped.more).toBe(true);
    expect(alertBody(dropped)).not.toContain(tripsCopy.alert.noBackup);
  });
  it('a safer push names the plan that made it when that plan is not the first (TRAV-R7-S1)', () => {
    // The sender's own safer fixture: WN 1500 (91%, same airline) ranks first, and AA 88 on Mon
    // at 6:00 pm (92%) is the plan that made the alert.
    const safer = must(readAlert(SENT.safer));
    const at = must(safer.at);
    const wn = 'Safer: WN 1500 at 3:00 pm, 91% chance to get there on time.';
    const aa = 'Leave a day early: AA 88, Mon, Jan 5 at 6:00 pm, 92% chance to get there on time.';
    const body = alertBody(safer, at);
    expect(body).toBe(
      `Another usual flight looks safer. Leaves Tue, Jan 6 at 10:00 am. 31% chance of a cancel. Snow in the forecast at MCI. ${wn} ${aa} ${tripsCopy.backup.money}`,
    );
    // Same airline stays first; the money words come after both.
    expect(body.indexOf(wn)).toBeLessThan(body.indexOf(aa));
    // The email names the same two.
    const mail = alertEmail(safer, 'https://snowlightmap.com/', at).text;
    expect(mail).toContain(`${wn}\n${aa}`);
    // Once AA 88 is inside its lead the alert reads as the trip's chance and names WN 1500 alone.
    const after = alertBody(safer, must(safer.backups[1]).departs - BACKUP_LEAD_S + 1);
    expect(after).not.toContain(tripsCopy.alert.safer);
    expect(after).toContain(wn);
    expect(after).not.toContain('AA 88');
    // Shown late while AA 88 can still be caught: both, after the checked line.
    const later = {
      ...safer,
      backups: safer.backups.map((b, i) => (i === 1 ? { ...b, departs: at + 5 * 3600 } : b)),
    };
    const late = alertBody(later, at + 70 * 60);
    expect(late).toMatch(/^Checked Mon, Jan 5 at 4:00 pm, MCI time\. Another usual flight/);
    expect(late).toContain(`${wn} ${aa} ${tripsCopy.backup.money}`);
    expect(alertRings(later, at + 70 * 60)).toBe(true);
    // When the first plan is the one that made it, the push names it alone.
    const top = {
      ...safer,
      backups: safer.backups.map((b, i) => (i === 0 ? { ...b, chance: 95 } : b)),
    };
    expect(alertBody(top, at)).toContain(
      `Safer: WN 1500 at 3:00 pm, 95% chance to get there on time. ${tripsCopy.backup.money}`,
    );
    expect(alertBody(top, at)).not.toContain('AA 88');
    // Every other kind still names one backup in the push.
    expect(alertBody(must(readAlert(SENT.chance)), at)).not.toContain('AA 88');
    // The facts are unchanged: the sender's safer payload stays under 3,000 bytes.
    expect(new TextEncoder().encode(JSON.stringify(SENT.safer)).length).toBeLessThan(3000);
  });
  it('a safer alert shown after its safer flights left never rings again (TRAV-R5-S1)', () => {
    const safer = must(readAlert(SENT.safer));
    const at = must(safer.at);
    expect(alertRings(safer, at)).toBe(true);
    const last = Math.max(...safer.backups.map((b) => b.departs));
    expect(alertRings(safer, last)).toBe(false);
    // Every other kind is a real change and rings, late or not.
    for (const name of ['chance', 'rise', 'fall', 'night', 'faa', 'waiver_basic'] as const)
      expect(alertRings(must(readAlert(SENT[name])), last)).toBe(true);
  });
  it('the shown lead is the sender’s own and the page’s (one rule)', () => {
    expect(BACKUP_LEAD_S).toBe(2 * 3600);
    expect(NEARBY_LEAD_S).toBe(3 * 3600);
    expect(BACKUP_LEAD).toBe(BACKUP_LEAD_S * 1000);
    expect(NEARBY_LEAD).toBe(NEARBY_LEAD_S * 1000);
    const rules = readFileSync(
      path.resolve(
        path.dirname(fileURLToPath(import.meta.url)),
        '../../../../../pipeline/snowlight/notify/flights_rules.py',
      ),
      'utf8',
    );
    const hours = (name: string): number =>
      Number(new RegExp(`^${name}: Final = timedelta\\(hours=(\\d+)\\)`, 'm').exec(rules)?.[1]);
    expect(hours('BACKUP_LEAD') * 3600).toBe(BACKUP_LEAD_S);
    expect(hours('NEARBY_LEAD') * 3600).toBe(NEARBY_LEAD_S);
    // The plans an alert carries: the sender's count is the reader's.
    expect(Number(/^ALERT_CARRIED: Final = (\d+)$/m.exec(rules)?.[1])).toBe(ALERT_CARRIED);
  });
  it('says the flight, the chance, why and the safer flight, from the sender’s own facts', () => {
    const facts = (name: keyof typeof SENT): AlertFacts => must(readAlert(SENT[name]));
    expect(alertBody(facts('chance'))).toBe(
      `Leaves Tue, Jan 6 at 10:00 am. 31% chance of a cancel. Snow in the forecast at MCI. Safer: WN 1500 at 3:00 pm, 91% chance to get there on time. ${tripsCopy.backup.money}`,
    );
    // D11: a backup the day before says so in words.
    expect(alertBody(facts('chance_day_early'))).toContain(
      'Leave a day early: WN 1234, Mon, Jan 5 at 10:00 am, 92% chance to get there on time.',
    );
    expect(alertBody(facts('rise'))).toMatch(
      /^The risk for this trip went up\. Leaves Tue, Jan 6 at 10:00 am\. 60% chance/,
    );
    expect(alertBody(facts('fall'))).toBe(
      'The risk for this trip went down. Leaves Tue, Jan 6 at 10:00 am. 2% chance of a cancel. 6% chance of a 45+ minute delay.',
    );
    expect(alertBody(facts('safer'))).toMatch(
      /^Another usual flight looks safer\. Leaves Tue, Jan 6 at 10:00 am\. 31% chance/,
    );
    // The evening check names the day, never "Tomorrow" (a push left in the tray, a late email).
    expect(alertBody(facts('night'))).toMatch(/^Evening check: Tue, Jan 6 at 10:00 am\. 11%/);
    expect(alertBody(facts('faa'))).toBe(
      'The FAA has a ground stop at MCI until 7:30 am. Leaves Mon, Jan 5 at 10:00 am.',
    );
    // W8: a basic ticket hears "free" only when the waiver says basic economy is in it.
    expect(alertBody(facts('waiver_basic'))).toBe(
      'Southwest posted a travel waiver for MCI. We could not tell if it covers basic economy. Check Southwest’s page. Leaves Tue, Jan 6 at 10:00 am.',
    );
    const regular = must(readAlert({ ...SENT.waiver_basic, ticket: 'regular' }));
    expect(alertBody(regular)).toBe(
      'Southwest posted a travel waiver for MCI. You can change this flight for free. Leaves Tue, Jan 6 at 10:00 am.',
    );
    const covered = must(
      readAlert({ ...SENT.waiver_basic, waiver: { ...SENT.waiver_basic.waiver, basic: true } }),
    );
    expect(alertBody(covered)).toContain('You can change this flight for free.');
  });
  it('every push says the trip’s day and time, whatever changed (TRAV-R2-B1)', () => {
    for (const raw of Object.values(SENT)) {
      const facts = must(readAlert(raw));
      const when = tripWhen(facts.day, facts.leaves);
      expect(alertBody(facts)).toContain(when);
      expect(alertBody(facts, must(facts.at) + 3 * 3600)).toContain(when);
      for (const kind of ['chance', 'rise', 'fall', 'safer', 'night'] as const) {
        // A chance, rise or fall always carries a chance (an evening check may not).
        if (raw.cancel === null && kind !== 'safer' && kind !== 'night') continue;
        const as = must(readAlert({ ...raw, alert: kind, faa: null, waiver: null }));
        expect(alertBody(as)).toContain(when);
      }
    }
  });
  it('an FAA end at the other airport names its clock (TRAV-R2-S3)', () => {
    const there = must(readAlert({ ...SENT.faa, faa: { airport: 'LAX', program: 0, until: 450 } }));
    expect(alertBody(there)).toContain('The FAA has a ground stop at LAX until 7:30 am, LAX time.');
    expect(alertBody(must(readAlert(SENT.faa)))).toContain('at MCI until 7:30 am.');
  });
  it('an evening check with no current forecast says so, never a number', () => {
    const none = must(
      readAlert({ ...SENT.night, cancel: null, late: null, level: null, why: null, backups: [] }),
    );
    expect(alertBody(none)).toBe(
      `Evening check: Tue, Jan 6 at 10:00 am. ${tripsCopy.alert.nightNone}`,
    );
    expect(alertEmail(none, 'https://snowlightmap.com/').text).toContain(tripsCopy.alert.nightNone);
    expect(alertBody(must(readAlert(SENT.night_none)))).toBe(
      `Evening check: Tue, Jan 6 at 10:00 am. ${tripsCopy.alert.nightNone}`,
    );
  });
  it('an evening check whose forecast has no chance for the flight says so (TRAV-R3-S1)', () => {
    const usual = must(readAlert(SENT.night_usual));
    expect(usual.noForecast).toBe(true);
    expect(alertBody(usual)).toBe(
      `Evening check: Tue, Jan 6 at 10:00 am. ${tripsCopy.alert.nightUsual}`,
    );
    // Only an evening check with no chance says it.
    expect(must(readAlert({ ...SENT.night, no_forecast: true })).noForecast).toBe(false);
  });
  it('says Settings times in the alerts’ own style (TRAV-R3-S3)', () => {
    expect(settingTime('20:00')).toBe('8:00 pm');
    expect(settingTime('05:00')).toBe('5:00 am');
    expect(settingTime('00:30')).toBe('12:30 am');
  });
  it('a nearby airport says how far, in a straight line (D18)', () => {
    const near = must(
      readAlert({
        ...SENT.chance,
        backups: [{ ...SENT.chance.backups[0], to: 'BUR', kind: 'nearby', miles: 18, number: 77 }],
      }),
    );
    expect(alertBody(near)).toContain(
      'Safer: WN 77 at 3:00 pm to BUR, 91% chance to get there on time. BUR is about 18 miles away.',
    );
  });
  it('never claims a seat, a fare, a booking or a flight on sale (D11, D18)', () => {
    for (const raw of Object.values(SENT)) {
      const facts = must(readAlert(raw));
      const mail = alertEmail(facts, 'https://snowlightmap.com/');
      for (const words of [alertBody(facts), mail.text]) {
        const said = words
          .replace(tripsCopy.backup.money, '')
          .replace(`${tripsCopy.email.open}:`, '')
          .toLowerCase();
        expect(said).not.toMatch(/\b(open|seats?|fares?|book(ed|ing)?|on sale|available)\b/);
      }
      // The money words ride with every backup named (D18).
      if (facts.backups.length > 0) {
        expect(alertBody(facts)).toContain(tripsCopy.backup.money);
        expect(mail.text).toContain(tripsCopy.backup.money);
      }
    }
  });
  it('a push that arrives late says when it was checked first', () => {
    const faa = must(readAlert(SENT.faa));
    const at = must(faa.at);
    expect(alertBody(faa, at + 29 * 60)).toBe(
      'The FAA has a ground stop at MCI until 7:30 am. Leaves Mon, Jan 5 at 10:00 am.',
    );
    expect(alertBody(faa, at + 31 * 60)).toBe(
      'Checked Mon, Jan 5 at 6:00 am, MCI time. The FAA has a ground stop at MCI until 7:30 am. Leaves Mon, Jan 5 at 10:00 am.',
    );
  });
  it('the email reads as Snowlight, with the day, the advice, the money words and when it was checked', () => {
    const mail = alertEmail(
      must(readAlert(SENT.chance)),
      'https://snowlightmap.com/?mode=flights&page=trips',
    );
    expect(mail.subject).toBe('WN 1234 · MCI to LAX: 31% chance of a cancel.');
    const lines = mail.text.split('\n');
    expect(lines.slice(0, 4)).toEqual([
      tripsCopy.email.brand,
      '',
      'WN 1234 · MCI to LAX',
      'Tue, Jan 6 at 10:00 am',
    ]);
    expect(mail.text).toContain(tripsCopy.advice.regular);
    expect(mail.text).toContain(tripsCopy.backup.money);
    expect(mail.text).toContain('Checked Mon, Jan 5 at 4:00 pm, MCI time.');
    expect(mail.html).toContain(`>${tripsCopy.email.brand}</p>`);
    expect(mail.html).toContain('prefers-color-scheme: dark');
    expect(mail.html).not.toMatch(/<script/i);
    const basic = alertEmail(
      must(readAlert({ ...SENT.chance, ticket: 'basic' })),
      'https://snowlightmap.com/',
    );
    expect(basic.text).toContain(tripsCopy.advice.basic);
  });
});

describe('Google’s answer from /google.html', () => {
  it('is taken once', () => {
    const kept = new Map([[GOOGLE_RETURN_KEY, JSON.stringify({ code: 'c', state: 's' })]]);
    const storage = {
      getItem: (k: string) => kept.get(k) ?? null,
      removeItem: (k: string) => void kept.delete(k),
    };
    expect(takeGoogleReturn(storage)).toEqual({ code: 'c', state: 's', error: null });
    expect(takeGoogleReturn(storage)).toBeNull();
    expect(takeGoogleReturn(null)).toBeNull();
  });
});
