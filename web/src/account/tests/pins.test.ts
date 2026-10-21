import { describe, expect, it } from 'vitest';

import type { PinStore } from '../../state/pin-store';
import type { SchoolId } from '../../types/generated';
import { syncPins, withSchool } from '../pins';
import type { AccountState, AccountStore, SavedSchool, User } from '../session';

function fakePins(initial: SchoolId | null): PinStore {
  let school = initial;
  const listeners = new Set<(id: SchoolId | null) => void>();
  return {
    get school() {
      return school;
    },
    saved: true,
    subscribe(listener) {
      listeners.add(listener);
      listener(school);
      return () => listeners.delete(listener);
    },
    pin(id) {
      school = id;
      for (const l of listeners) l(id);
    },
    unpin() {
      school = null;
      for (const l of listeners) l(null);
    },
    destroy() {
      listeners.clear();
    },
  };
}

function fakeAccount(): AccountStore & {
  login(schools: SavedSchool[]): void;
  saved: SavedSchool[][];
} {
  let state: AccountState = { available: true, ready: true, user: null };
  const listeners = new Set<(s: AccountState) => void>();
  const set = (user: User | null): void => {
    state = { ...state, user };
    for (const l of listeners) l(state);
  };
  const saved: SavedSchool[][] = [];
  const store = {
    get state() {
      return state;
    },
    saved,
    subscribe(listener: (s: AccountState) => void) {
      listeners.add(listener);
      listener(state);
      return () => listeners.delete(listener);
    },
    login(schools: SavedSchool[]) {
      set({
        id: 'u',
        name: 'N',
        email: 'n@e.co',
        role: 'user',
        schools,
        created_at: '',
        username: 'n_e',
        join_number: 2,
        username_required: false,
        renamed: false,
        needs_rekey: false,
      });
    },
    setSchools(schools: readonly SavedSchool[]) {
      saved.push([...schools]);
      if (state.user !== null) set({ ...state.user, schools: [...schools] });
      return Promise.resolve();
    },
  };
  return store as unknown as AccountStore & {
    login(s: SavedSchool[]): void;
    saved: SavedSchool[][];
  };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const nameOf = (id: SchoolId) => Promise.resolve(`School ${id}`);

describe('pin sync', () => {
  it('adds this device’s pin to the account on login', async () => {
    const account = fakeAccount();
    const pins = fakePins('390437801234');
    syncPins({ account, pins, nameOf });
    account.login([{ id: 'A1234567', name: 'Other' }]);
    await settle();
    expect(account.saved.at(-1)?.map((s) => s.id)).toEqual(['390437801234', 'A1234567']);
  });

  it('pins the first saved school on a device with no pin', async () => {
    const account = fakeAccount();
    const pins = fakePins(null);
    syncPins({ account, pins, nameOf });
    account.login([{ id: 'A1234567', name: 'Other' }]);
    await settle();
    expect(pins.school).toBe('A1234567');
    expect(account.saved).toEqual([]);
  });

  it('saves a school pinned while logged in', async () => {
    const account = fakeAccount();
    const pins = fakePins(null);
    syncPins({ account, pins, nameOf });
    account.login([]);
    pins.pin('390437801234');
    await settle();
    expect(account.saved.at(-1)).toEqual([{ id: '390437801234', name: 'School 390437801234' }]);
  });

  it('keeps at most five and never drops one to make room', () => {
    const five = Array.from({ length: 5 }, (_, i) => ({
      id: String(i).repeat(12),
      name: `S${String(i)}`,
    }));
    expect(withSchool(five, { id: '999999999999', name: 'New' })).toBeNull();
    expect(withSchool(five.slice(0, 2), { id: '000000000000', name: 'S0' })).toBeNull();
  });
});
