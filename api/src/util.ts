/**
 * Small helpers: encoding, hashing, random tokens and constant-time compares.
 *
 * CPU budget: the free Workers plan allows 10 ms of CPU per request (error 1102
 * beyond it). Nothing here is slow on purpose: the only hashing is one SHA-256
 * over a few dozen bytes. Slow password hashing happens in the browser (and,
 * for the admin, once in the deploy runner), never in the Worker.
 */

const encoder = new TextEncoder();

export function b64url(bytes: Uint8Array): string {
  let text = '';
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function fromB64url(text: string): Uint8Array {
  const padded =
    text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
  const raw = atob(padded);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function randomBytes(length: number): Uint8Array {
  const out = new Uint8Array(length);
  crypto.getRandomValues(out);
  return out;
}

export function randomHex(length: number): string {
  return [...randomBytes(length)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

export async function sha256(data: Uint8Array | string): Promise<Uint8Array> {
  const bytes = typeof data === 'string' ? encoder.encode(data) : data;
  return new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
}

export function concat(a: Uint8Array, b: Uint8Array): Uint8Array {
  const out = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

/** Equal-length byte arrays compared without an early exit. */
export function bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i]! ^ b[i]!;
  return diff === 0;
}

/**
 * Constant-time equality of two strings: both are hashed first, so the compare
 * runs over 32 bytes whatever their lengths, and leaks nothing about either.
 */
export async function secretEqual(a: string, b: string): Promise<boolean> {
  const [da, db] = await Promise.all([sha256(a), sha256(b)]);
  return bytesEqual(da, db);
}

export function isoSeconds(ms: number): string {
  return new Date(Math.floor(ms / 1000) * 1000).toISOString().replace('.000Z', 'Z');
}
