/** Input checks. Everything from a request is untrusted until it passes one of these. */

/** base64url of the 32-byte key the browser derives (PBKDF2-SHA256, 600,000 iterations). */
const KEY = /^[A-Za-z0-9_-]{43}$/;
const EMAIL = /^[^\s@<>"]{1,64}@[^\s@<>"]+\.[^\s@<>".]{2,}$/;
/** NCES CCD school id (12 digits) or PSS PPIN (8 capitals or digits); see web/src/state/ids.ts. */
const SCHOOL_ID = /^(?:\d{12}|[0-9A-Z]{8})$/;
const DISTRICT_ID = /^\d{7}$/;
const LOCAL_TIME = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
// Control characters and angle brackets: names and notes are plain text only.
// eslint-disable-next-line no-control-regex
const NOT_PLAIN = /[\u0000-\u001f\u007f-\u009f<>\u2028\u2029]/;

export const STATUSES = ['closed', 'delayed', 'early_dismissal', 'open'] as const;
export type Status = (typeof STATUSES)[number];
export const SCOPES = ['district', 'school'] as const;
export type Scope = (typeof SCOPES)[number];

export const MAX_SCHOOLS = 5;

/** base64url of the 16 random bytes the browser salts a key with. */
const CLIENT_SALT = /^[A-Za-z0-9_-]{22}$/;

export function clientSalt(value: unknown): string | null {
  return typeof value === 'string' && CLIENT_SALT.test(value) ? value : null;
}

export function key(value: unknown): string | null {
  return typeof value === 'string' && KEY.test(value) ? value : null;
}

export function email(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const text = value.trim().toLowerCase();
  return text.length <= 254 && EMAIL.test(text) ? text : null;
}

/** Plain text, trimmed, inner runs of space collapsed, `min`..`max` characters. */
export function plain(value: unknown, min: number, max: number): string | null {
  if (typeof value !== 'string') return null;
  if (NOT_PLAIN.test(value)) return null;
  const text = value.trim().replace(/\s+/g, ' ');
  const length = [...text].length;
  return length >= min && length <= max ? text : null;
}

export function name(value: unknown): string | null {
  return plain(value, 1, 40);
}

export function schoolId(value: unknown): string | null {
  return typeof value === 'string' && SCHOOL_ID.test(value) ? value : null;
}

export function targetId(scope: Scope, value: unknown): string | null {
  if (typeof value !== 'string') return null;
  return scope === 'district' ? (DISTRICT_ID.test(value) ? value : null) : schoolId(value);
}

export function localTime(value: unknown): string | null {
  return typeof value === 'string' && LOCAL_TIME.test(value) ? value : null;
}

export function oneOf<T extends string>(options: readonly T[], value: unknown): T | null {
  return typeof value === 'string' && (options as readonly string[]).includes(value)
    ? (value as T)
    : null;
}

/** An ISO-8601 instant with an explicit zone, as Unix ms, or null. */
export function instant(value: unknown): number | null {
  if (typeof value !== 'string' || value.length > 40) return null;
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?(?:Z|[+-]\d{2}:\d{2})$/.test(value))
    return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
