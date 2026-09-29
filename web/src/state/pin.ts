/**
 * The pinned school ("My school"), kept in localStorage: reading it. The
 * page's first script reads the pin as it starts, and nothing more; the store
 * that keeps and changes it (state/pin-store.ts) comes with the app's
 * services.
 *
 * Storage is optional. Reading `window.localStorage` itself throws where site
 * data is blocked, and writes throw when storage is full; every access is
 * guarded, and when storage fails the pin still works for as long as the page
 * is open. Other tabs pick up a pin through the storage event.
 */

import type { SchoolId } from '../types/generated';
import { isSchoolId } from './ids';

export const PIN_KEY = 'snowlight:pin';
const VERSION = 1;

interface StoredPin {
  readonly v: typeof VERSION;
  readonly school: SchoolId;
}

/** The parts of `window` the pin uses, so tests can hand it a fake. */
export interface PinHost extends EventTarget {
  readonly localStorage: Storage;
}

/** window.localStorage, or null where the browser refuses access. */
export function storageOf(host: PinHost): Storage | null {
  try {
    return host.localStorage;
  } catch {
    return null;
  }
}

/** The school a stored value names, or null for anything else. */
export function decodePin(raw: string | null): SchoolId | null {
  if (raw === null || raw.length > 256) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== 'object' || value === null) return null;
    const { v, school } = value as Partial<Record<keyof StoredPin, unknown>>;
    return v === VERSION && isSchoolId(school) ? school : null;
  } catch {
    return null;
  }
}

export function encodePin(school: SchoolId): string {
  const stored: StoredPin = { v: VERSION, school };
  return JSON.stringify(stored);
}

/** The saved pin; null when there is none, it is unreadable, or storage is unavailable. */
export function readPin(storage: Storage | null): SchoolId | null {
  if (storage === null) return null;
  try {
    return decodePin(storage.getItem(PIN_KEY));
  } catch {
    return null;
  }
}

/** The school pinned on this device, read once without a store; null when there is none. */
export function pinnedSchool(host: PinHost = window): SchoolId | null {
  return readPin(storageOf(host));
}
