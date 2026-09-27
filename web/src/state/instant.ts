/**
 * The published files' UtcInstant, read strictly. In a module of its own so
 * code that only reads files does not pull in the copy formatters.
 */

const UTC_INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

/** A UtcInstant as a Date, or null when it is not one. */
export function parseInstant(value: unknown): Date | null {
  if (typeof value !== 'string' || !UTC_INSTANT.test(value)) return null;
  const instant = new Date(value);
  // Date accepts 2026-02-30 and rolls it over; a real instant prints back the same.
  return Number.isNaN(instant.getTime()) || instant.toISOString() !== value.replace('Z', '.000Z')
    ? null
    : instant;
}
