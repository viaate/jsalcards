/**
 * Formats of the ids a share link or a pin can carry.
 *
 * The patterns are the ones the pipeline's schemas publish (SchoolId and
 * DistrictId in schemas/school-directory.schema.json); src/state/tests/ids.test.ts keeps
 * them equal. A well-formed id is not necessarily a school on the map: the
 * directory decides that when the id is looked up.
 */

import type { DistrictId, SchoolId } from '../types/generated';

/** NCES CCD school id: 7-digit LEAID then a 5-digit school number. */
export const PUBLIC_SCHOOL_ID = /^\d{12}$/;
/** NCES PSS PPIN: 8 capital letters or digits. */
export const PRIVATE_SCHOOL_ID = /^[0-9A-Z]{8}$/;
/** NCES LEAID: 2-digit state code then a 5-digit district number. */
export const DISTRICT_ID = /^\d{7}$/;
/** A 5-digit ZIP code (ZCTA). */
export const ZIP_CODE = /^\d{5}$/;

/** Longest text worth looking at: ZIP+4 ("12345-6789") is the longest accepted form. */
const MAX_INPUT = 16;

function clean(raw: string | null | undefined): string | null {
  if (typeof raw !== 'string') return null;
  const text = raw.trim();
  return text.length === 0 || text.length > MAX_INPUT ? null : text;
}

export function isSchoolId(value: unknown): value is SchoolId {
  return (
    typeof value === 'string' && (PUBLIC_SCHOOL_ID.test(value) || PRIVATE_SCHOOL_ID.test(value))
  );
}

export function isDistrictId(value: unknown): value is DistrictId {
  return typeof value === 'string' && DISTRICT_ID.test(value);
}

export function isZipCode(value: unknown): value is string {
  return typeof value === 'string' && ZIP_CODE.test(value) && value !== '00000';
}

/**
 * A school id from untrusted text, or null. Surrounding space is dropped and a
 * private school id is upper-cased, since people retype them by hand.
 */
export function parseSchoolId(raw: string | null | undefined): SchoolId | null {
  const text = clean(raw);
  if (text === null) return null;
  if (PUBLIC_SCHOOL_ID.test(text)) return text;
  const upper = text.toUpperCase();
  return PRIVATE_SCHOOL_ID.test(upper) ? upper : null;
}

/** A district id (LEAID) from untrusted text, or null. */
export function parseDistrictId(raw: string | null | undefined): DistrictId | null {
  const text = clean(raw);
  return text !== null && DISTRICT_ID.test(text) ? text : null;
}

/** A ZIP code from untrusted text, or null. ZIP+4 keeps its first five digits. */
export function parseZipCode(raw: string | null | undefined): string | null {
  const text = clean(raw);
  if (text === null) return null;
  const zip = /^(\d{5})(?:-\d{4})?$/.exec(text)?.[1];
  return zip !== undefined && isZipCode(zip) ? zip : null;
}
