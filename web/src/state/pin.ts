/**
 * The pinned school ("My school"), kept in localStorage.
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

export type PinListener = (school: SchoolId | null) => void;

/** The parts of `window` the pin uses, so tests can hand it a fake. */
export interface PinHost extends EventTarget {
  readonly localStorage: Storage;
}

export interface PinStoreOptions {
  /** Defaults to `window`. */
  host?: PinHost;
}

export interface PinStore {
  /** The pinned school's id, or null. */
  readonly school: SchoolId | null;
  /** False when the pin cannot be saved and lasts only while the page is open. */
  readonly saved: boolean;
  /** Calls `listener` now and whenever the pin changes, here or in another tab. Also a Svelte store. */
  subscribe(listener: PinListener): () => void;
  pin(school: SchoolId): void;
  unpin(): void;
  destroy(): void;
}

/** window.localStorage, or null where the browser refuses access. */
function storageOf(host: PinHost): Storage | null {
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

/** Saves or clears the pin. False if storage refused. */
export function writePin(storage: Storage | null, school: SchoolId | null): boolean {
  if (storage === null) return false;
  try {
    if (school === null) storage.removeItem(PIN_KEY);
    else storage.setItem(PIN_KEY, encodePin(school));
    return true;
  } catch {
    return false;
  }
}

export function createPinStore(options: PinStoreOptions = {}): PinStore {
  const host: PinHost = options.host ?? window;
  const storage = storageOf(host);
  const listeners = new Set<PinListener>();
  let school = readPin(storage);
  let saved = storage !== null;

  const set = (next: SchoolId | null): void => {
    if (next === school) return;
    school = next;
    for (const listener of [...listeners]) listener(school);
  };

  const onStorage = (event: Event): void => {
    const { key, storageArea } = event as StorageEvent;
    // key is null when another tab cleared all of storage.
    if ((key === PIN_KEY || key === null) && (storageArea === storage || storageArea === null)) {
      set(readPin(storage));
    }
  };
  host.addEventListener('storage', onStorage);

  return {
    get school() {
      return school;
    },
    get saved() {
      return saved;
    },
    subscribe(listener) {
      listeners.add(listener);
      listener(school);
      return () => {
        listeners.delete(listener);
      };
    },
    pin(next) {
      if (!isSchoolId(next)) throw new RangeError(`pin: "${String(next)}" is not a school id`);
      saved = writePin(storage, next);
      set(next);
    },
    unpin() {
      saved = writePin(storage, null);
      set(null);
    },
    destroy() {
      listeners.clear();
      host.removeEventListener('storage', onStorage);
    },
  };
}
