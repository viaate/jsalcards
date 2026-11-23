#!/usr/bin/env node
/**
 * The SYNTHETIC live file Flights mode is measured with (perf/lighthouse.mjs --mode=flights): made
 * up for the run in the data folder of the build under test, never published, every airport the
 * site ships in it.
 *
 * By default it is a storm map, the costly one to draw: a band of airports across the Midwest
 * and the Northeast at a high risk of a cancel, a wider band around it at some risk, two of them
 * with an FAA program, and every other airport calm. Every airport at risk takes a code tag with
 * its pip and a place found clear of the others' dots, on top of the calm tags the map shows at
 * every view, so the map's tag placement does the most work it does on any day. `calm` gives
 * every airport the same low forecast, the usual day.
 *
 * `node perf/flights-fixture.mjs <dist> [--calm]` writes one into a build by hand.
 */
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..');

/** A day's five blocks, each at `value` (tenths of a percent). */
const blocks = (value) => [value, value, value, value, value];

/** Where the made-up storm is: a high risk of a cancel inside `high`, some risk inside `some`. */
const HIGH = { south: 38, north: 46, west: -95, east: -72 };
const SOME = { south: 34, north: 48.5, west: -101, east: -67 };
const inside = (box, airport) =>
  airport.lat >= box.south &&
  airport.lat <= box.north &&
  airport.lon >= box.west &&
  airport.lon <= box.east;

/**
 * Writes the fixture into `dist`'s data folder, made now.
 * @param {string} dist
 * @param {{ calm?: boolean }} [options]
 */
export async function writeFlightsFixture(dist, options = {}) {
  const shipped = JSON.parse(await readFile(join(WEB, 'public/flights/airports.json'), 'utf8'));
  const at = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  const stamp = `${at.slice(0, 16).replace(/[-:]/g, '')}Z`;
  const today = at.slice(0, 10);
  const calm = options.calm === true;
  /** The two busiest airports in the high band carry an FAA program. */
  const programmed = new Set(
    shipped.airports
      .filter((airport) => !calm && inside(HIGH, airport))
      .sort((a, b) => b.per_day - a.per_day || (a.code < b.code ? -1 : 1))
      .slice(0, 2)
      .map((airport) => airport.code),
  );
  const airports = shipped.airports.map((airport) => {
    const high = !calm && inside(HIGH, airport);
    const some = !calm && !high && inside(SOME, airport);
    const cancel = high ? 300 : some ? 60 : 10;
    const late = high ? 400 : some ? 300 : 10;
    return {
      code: airport.code,
      today,
      dep_canc: [blocks(cancel), blocks(cancel), blocks(10)],
      dep_late: [blocks(late), blocks(late), blocks(10)],
      arr_canc: [blocks(cancel), blocks(cancel), blocks(10)],
      arr_late: [blocks(late), blocks(late), blocks(10)],
      rough: [cancel, cancel, 10],
      runs: [at, at, at],
      usual: [
        [0, 0, 0],
        [0, 0, 0],
        [0, 0, 0],
        [0, 0, 0],
      ],
      rough_usual: 0,
      why: high || some ? [[0], [0], []] : [[], [], []],
      // A ground stop at the busiest, a ground delay at the next.
      programs: programmed.has(airport.code)
        ? [{ program: [...programmed].indexOf(airport.code), why: 1, minutes: 60, until: null }]
        : [],
      alerts: [],
      now: null,
    };
  });
  const folder = join(dist, 'data/flights');
  await mkdir(join(folder, 'live'), { recursive: true });
  const latest = { schema_version: 1, generated_at: at, slot: 'slot-0', stamp };
  const live = {
    ...latest,
    run: at,
    programs_at: at,
    alerts_at: at,
    weather_at: at,
    observed_at: at,
    airports,
  };
  await writeFile(join(folder, 'latest.json'), JSON.stringify(latest));
  await writeFile(join(folder, 'live/slot-0.json'), JSON.stringify(live));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const dist = process.argv[2];
  if (dist === undefined) throw new Error('Usage: node perf/flights-fixture.mjs <dist> [--calm]');
  await writeFlightsFixture(dist, { calm: process.argv.includes('--calm') });
}
