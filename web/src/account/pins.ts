/**
 * The local "My school" pin and the account's saved schools, kept in step.
 * On logging in, the pin this device holds joins the saved schools when it is
 * missing (while there is room for it); on a device with no pin, the first
 * saved school becomes the pin. Pinning a school while logged in saves it too.
 */

import type { PinStore } from '../state/pin-store';
import type { SchoolId } from '../types/generated';
import { MAX_SCHOOLS, type AccountStore, type SavedSchool } from './session';

/** The saved schools with `school` added first, or null when it is there already or there is no room. */
export function withSchool(
  schools: readonly SavedSchool[],
  school: SavedSchool,
): SavedSchool[] | null {
  if (schools.some((s) => s.id === school.id)) return null;
  if (schools.length >= MAX_SCHOOLS) return null;
  return [school, ...schools];
}

export function withoutSchool(schools: readonly SavedSchool[], id: string): SavedSchool[] {
  return schools.filter((s) => s.id !== id);
}

export interface PinSyncOptions {
  readonly account: AccountStore;
  readonly pins: PinStore;
  /** A school's name as the map shows it, or null when it cannot be read. */
  readonly nameOf: (id: SchoolId) => Promise<string | null>;
}

/** Keeps the pin and the saved schools in step. Returns the function that stops it. */
export function syncPins({ account, pins, nameOf }: PinSyncOptions): () => void {
  let userId: string | null = null;
  let stopped = false;

  const save = async (id: SchoolId): Promise<void> => {
    const user = account.state.user;
    if (user === null || user.schools.some((s) => s.id === id)) return;
    const name = await nameOf(id);
    const current = account.state.user;
    if (stopped || name === null || current?.id !== user.id) return;
    const next = withSchool(current.schools, { id, name });
    if (next !== null) await account.setSchools(next).catch(() => undefined);
  };

  const stopAccount = account.subscribe((state) => {
    const id = state.user?.id ?? null;
    if (id === userId) return;
    userId = id;
    if (state.user === null) return;
    // Just logged in (or the page opened logged in).
    const pinned = pins.school;
    if (pinned !== null) void save(pinned);
    else {
      const first = state.user.schools[0];
      if (first !== undefined) pins.pin(first.id);
    }
  });

  let first = true;
  const stopPins = pins.subscribe((id) => {
    // The subscription's first call is the pin as it stands, handled above.
    if (first) {
      first = false;
      return;
    }
    if (id !== null) void save(id);
  });

  return () => {
    stopped = true;
    stopAccount();
    stopPins();
  };
}
