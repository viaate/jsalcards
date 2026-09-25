import { afterEach, describe, expect, it, vi } from 'vitest';

import { PIN_KEY, createPinStore, decodePin, encodePin, readPin, writePin } from '../pin';
import type { PinHost } from '../pin';

const SCHOOL = '010000500870';
const PRIVATE = 'A9106011';

/** An in-memory Storage whose methods can be made to throw. */
class FakeStorage implements Storage {
  readonly data = new Map<string, string>();
  failGet = false;
  failSet = false;

  get length(): number {
    return this.data.size;
  }

  clear(): void {
    this.data.clear();
  }

  getItem(key: string): string | null {
    if (this.failGet) throw new DOMException('denied', 'SecurityError');
    return this.data.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.data.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    if (this.failSet) throw new DOMException('denied', 'SecurityError');
    this.data.delete(key);
  }

  setItem(key: string, value: string): void {
    if (this.failSet) throw new DOMException('The quota has been exceeded.', 'QuotaExceededError');
    this.data.set(key, value);
  }
}

class FakeWindow extends EventTarget implements PinHost {
  constructor(readonly storage: FakeStorage | 'throws') {
    super();
  }

  get localStorage(): Storage {
    // Where site data is blocked, merely reading window.localStorage throws.
    if (this.storage === 'throws') throw new DOMException('Access is denied', 'SecurityError');
    return this.storage;
  }

  /** What the browser fires here when another tab changes storage. */
  otherTab(key: string | null, newValue: string | null): void {
    const event = new Event('storage') as Event & {
      key: string | null;
      newValue: string | null;
      storageArea: Storage | null;
    };
    Object.assign(event, {
      key,
      newValue,
      storageArea: this.storage === 'throws' ? null : this.storage,
    });
    this.dispatchEvent(event);
  }
}

afterEach(() => {
  window.localStorage.clear();
});

describe('the stored value', () => {
  it('round-trips a public and a private school', () => {
    expect(decodePin(encodePin(SCHOOL))).toBe(SCHOOL);
    expect(decodePin(encodePin(PRIVATE))).toBe(PRIVATE);
    expect(encodePin(SCHOOL)).toBe(`{"v":1,"school":"${SCHOOL}"}`);
  });

  it.each([
    null,
    '',
    SCHOOL,
    `"${SCHOOL}"`,
    'null',
    '[]',
    '{',
    `{"school":"${SCHOOL}"}`,
    `{"v":2,"school":"${SCHOOL}"}`,
    `{"v":"1","school":"${SCHOOL}"}`,
    '{"v":1,"school":"12"}',
    '{"v":1,"school":"a9106011"}',
    `{"v":1,"school":"${SCHOOL}","pad":"${'x'.repeat(300)}"}`,
  ])('reads %j as no pin', (raw) => {
    expect(decodePin(raw)).toBeNull();
  });
});

describe('readPin and writePin', () => {
  it('save, read and clear the pin', () => {
    const storage = new FakeStorage();
    expect(writePin(storage, SCHOOL)).toBe(true);
    expect(storage.data.get(PIN_KEY)).toBe(encodePin(SCHOOL));
    expect(readPin(storage)).toBe(SCHOOL);
    expect(writePin(storage, null)).toBe(true);
    expect(storage.data.has(PIN_KEY)).toBe(false);
    expect(readPin(storage)).toBeNull();
  });

  it('never throw when storage does', () => {
    const storage = new FakeStorage();
    storage.failGet = true;
    storage.failSet = true;
    expect(readPin(storage)).toBeNull();
    expect(writePin(storage, SCHOOL)).toBe(false);
    expect(writePin(storage, null)).toBe(false);
    expect(readPin(null)).toBeNull();
    expect(writePin(null, SCHOOL)).toBe(false);
  });
});

describe('createPinStore', () => {
  it('restores the saved pin', () => {
    const storage = new FakeStorage();
    storage.data.set(PIN_KEY, encodePin(SCHOOL));
    const pins = createPinStore({ host: new FakeWindow(storage) });
    expect(pins.school).toBe(SCHOOL);
    expect(pins.saved).toBe(true);
  });

  it('pins, unpins and tells subscribers, now and on change', () => {
    const storage = new FakeStorage();
    const pins = createPinStore({ host: new FakeWindow(storage) });
    const seen: (string | null)[] = [];
    const stop = pins.subscribe((school) => seen.push(school));
    pins.pin(SCHOOL);
    pins.pin(SCHOOL);
    pins.pin(PRIVATE);
    pins.unpin();
    stop();
    pins.pin(SCHOOL);
    expect(seen).toEqual([null, SCHOOL, PRIVATE, null]);
    expect(storage.data.get(PIN_KEY)).toBe(encodePin(SCHOOL));
  });

  it('works for the visit when reading window.localStorage throws', () => {
    const pins = createPinStore({ host: new FakeWindow('throws') });
    expect(pins.school).toBeNull();
    expect(pins.saved).toBe(false);
    pins.pin(SCHOOL);
    expect(pins.school).toBe(SCHOOL);
    expect(pins.saved).toBe(false);
    pins.unpin();
    expect(pins.school).toBeNull();
  });

  it('works for the visit when storage is full, and says it was not saved', () => {
    const storage = new FakeStorage();
    const pins = createPinStore({ host: new FakeWindow(storage) });
    storage.failSet = true;
    pins.pin(SCHOOL);
    expect(pins.school).toBe(SCHOOL);
    expect(pins.saved).toBe(false);
    storage.failSet = false;
    pins.pin(PRIVATE);
    expect(pins.saved).toBe(true);
    expect(readPin(storage)).toBe(PRIVATE);
  });

  it('ignores a junk saved value', () => {
    const storage = new FakeStorage();
    storage.data.set(PIN_KEY, '{"v":1,"school":"<img>"}');
    expect(createPinStore({ host: new FakeWindow(storage) }).school).toBeNull();
  });

  it('follows a pin made or cleared in another tab', () => {
    const storage = new FakeStorage();
    const host = new FakeWindow(storage);
    const pins = createPinStore({ host });
    const listener = vi.fn();
    pins.subscribe(listener);

    storage.data.set(PIN_KEY, encodePin(SCHOOL));
    host.otherTab(PIN_KEY, encodePin(SCHOOL));
    expect(pins.school).toBe(SCHOOL);

    host.otherTab('something-else', 'x');
    storage.data.clear();
    host.otherTab(null, null);
    expect(pins.school).toBeNull();
    expect(listener.mock.calls).toEqual([[null], [SCHOOL], [null]]);

    pins.destroy();
    storage.data.set(PIN_KEY, encodePin(PRIVATE));
    host.otherTab(PIN_KEY, encodePin(PRIVATE));
    expect(listener).toHaveBeenCalledTimes(3);
  });

  it('refuses an id that is not a school id', () => {
    const pins = createPinStore({ host: new FakeWindow(new FakeStorage()) });
    expect(() => {
      pins.pin('0100005');
    }).toThrow(RangeError);
    expect(pins.school).toBeNull();
  });

  it('uses window.localStorage by default', () => {
    const pins = createPinStore();
    pins.pin(SCHOOL);
    expect(window.localStorage.getItem(PIN_KEY)).toBe(encodePin(SCHOOL));
    expect(createPinStore().school).toBe(SCHOOL);
    pins.destroy();
  });
});
