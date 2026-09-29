/**
 * The pinned school's store ("My school"): it keeps the pin in localStorage
 * (state/pin.ts reads it), changes it, and hears when another tab does.
 */

import type { SchoolId } from '../types/generated';
import { isSchoolId } from './ids';
import { PIN_KEY, encodePin, readPin, storageOf } from './pin';
import type { PinHost } from './pin';

export type PinListener = (school: SchoolId | null) => void;

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
