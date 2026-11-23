/**
 * Made-up flights files for these tests: the airports' chances, the FAA programs and the
 * waivers are SYNTHETIC, invented here, never read from a real day.
 */
import type { FlightsAirportLive, FlightsBlockRow, FlightsLive } from '../../../types/generated';
import type { Airport } from '../data';

export const ROW_LOW: FlightsBlockRow = [10, 12, 15, 20, 18];
export const ROW_NONE: FlightsBlockRow = [null, null, null, null, null];

export function airportLive(
  code: string,
  today: string,
  overrides: Partial<FlightsAirportLive> = {},
): FlightsAirportLive {
  return {
    code,
    today,
    dep_canc: [ROW_LOW, ROW_LOW, ROW_LOW],
    dep_late: [
      [40, 50, 60, 80, 70],
      [40, 50, 60, 80, 70],
      [40, 50, 60, 80, 70],
    ],
    arr_canc: [ROW_LOW, ROW_LOW, ROW_LOW],
    arr_late: [
      [40, 50, 60, 80, 70],
      [40, 50, 60, 80, 70],
      [40, 50, 60, 80, 70],
    ],
    rough: [10, 10, 10],
    runs: ['2026-01-04T00:00:00Z', '2026-01-04T00:00:00Z', '2026-01-04T00:00:00Z'],
    usual: [
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
    ],
    rough_usual: 0,
    why: [[], [], []],
    programs: [],
    alerts: [],
    now: null,
    ...overrides,
  };
}

export function liveFile(
  airports: readonly FlightsAirportLive[],
  generatedAt: string,
  stamp = '20260105T1200Z',
): FlightsLive {
  return {
    schema_version: 1,
    generated_at: generatedAt,
    slot: 'slot-0',
    stamp,
    run: '2026-01-05T00:00:00Z',
    programs_at: generatedAt,
    alerts_at: generatedAt,
    weather_at: generatedAt,
    observed_at: '2026-01-05T00:00:00Z',
    airports,
  };
}

export const MCI: Airport = {
  code: 'MCI',
  name: 'Kansas City International Airport',
  city: 'Kansas City',
  state: 'MO',
  lat: 39.2976,
  lon: -94.7139,
  tz: 'America/Chicago',
  perDay: 160,
};

export const LAX: Airport = {
  code: 'LAX',
  name: 'Los Angeles International Airport',
  city: 'Los Angeles',
  state: 'CA',
  lat: 33.9425,
  lon: -118.4081,
  tz: 'America/Los_Angeles',
  perDay: 600,
};

export const DEN: Airport = {
  code: 'DEN',
  name: 'Denver International Airport',
  city: 'Denver',
  state: 'CO',
  lat: 39.86,
  lon: -104.6738,
  tz: 'America/Denver',
  perDay: 870,
};

export const ORD: Airport = {
  code: 'ORD',
  name: 'Chicago O’Hare International Airport',
  city: 'Chicago',
  state: 'IL',
  lat: 41.9786,
  lon: -87.9048,
  tz: 'America/Chicago',
  perDay: 1000,
};

export const AIRPORTS: readonly Airport[] = [MCI, LAX, DEN, ORD];
