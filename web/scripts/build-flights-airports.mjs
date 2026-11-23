#!/usr/bin/env node
// @ts-check
/**
 * Writes public/flights/airports.json, the airports Flights mode draws until the live host
 * publishes flights/airports.json (the monthly job's first full build): the committed table
 * pipeline/data/flights/airports.json, cut to what the page shows (code, name, city, state,
 * place, time zone, departures per day), in the published file's shape. Run it again when the
 * pipeline's table changes; src/modes/flights/tests/airports-file.test.ts holds the two equal.
 *
 * Usage: node scripts/build-flights-airports.mjs
 */
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE = path.join(WEB, '../pipeline/data/flights/airports.json');
const TARGET = path.join(WEB, 'public/flights/airports.json');

/** @param {string} text */
export function shippedAirports(text) {
  /** @type {Array<Record<string, unknown>>} */
  const rows = JSON.parse(text);
  return {
    schema_version: 1,
    airports: rows.map((row) => ({
      code: row.code,
      name: row.name,
      city: row.city,
      state: row.state,
      lat: row.lat,
      lon: row.lon,
      tz: row.tz,
      per_day: row.per_day,
    })),
  };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const shipped = shippedAirports(readFileSync(SOURCE, 'utf8'));
  writeFileSync(TARGET, `${JSON.stringify(shipped)}\n`);
  console.log(`${TARGET}: ${String(shipped.airports.length)} airports`);
}
