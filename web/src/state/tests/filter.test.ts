import { describe, expect, it } from 'vitest';

import { Status } from '../../types/generated';
import {
  PRIVATE_FLAG,
  SHOW_ALL,
  sameFilter,
  showsAll,
  showsBothKinds,
  showsSchool,
  showsStatus,
  withKind,
  withStatus,
} from '../filter';

describe('the map filter', () => {
  it('shows everything as the map opens', () => {
    expect(SHOW_ALL).toEqual({ status: null, public: true, private: true });
    expect(Object.isFrozen(SHOW_ALL)).toBe(true);
    expect(showsAll(SHOW_ALL)).toBe(true);
    for (const status of Object.values(Status)) expect(showsStatus(SHOW_ALL, status)).toBe(true);
    expect(showsSchool(SHOW_ALL, 0)).toBe(true);
    expect(showsSchool(SHOW_ALL, PRIVATE_FLAG)).toBe(true);
  });

  it('shows one status, or all four again', () => {
    const closed = withStatus(SHOW_ALL, Status.closed);
    expect(showsAll(closed)).toBe(false);
    expect(showsBothKinds(closed)).toBe(true);
    expect([0, 1, 2, 3].map((status) => showsStatus(closed, status))).toEqual([
      true,
      false,
      false,
      false,
    ]);
    expect(sameFilter(withStatus(closed, null), SHOW_ALL)).toBe(true);
    // A new filter each time; the one it came from stays as it was.
    expect(SHOW_ALL.status).toBeNull();
    expect(Object.isFrozen(closed)).toBe(true);
  });

  it('tells a private school by its kind flags, charter and virtual schools public', () => {
    const publicOnly = withKind(SHOW_ALL, 'private', false);
    expect(showsBothKinds(publicOnly)).toBe(false);
    expect(showsSchool(publicOnly, 0)).toBe(true);
    expect(showsSchool(publicOnly, 0x02)).toBe(true);
    expect(showsSchool(publicOnly, 0x06)).toBe(true);
    expect(showsSchool(publicOnly, PRIVATE_FLAG)).toBe(false);
    expect(showsSchool(publicOnly, PRIVATE_FLAG | 0x04)).toBe(false);
    const privateOnly = withKind(SHOW_ALL, 'public', false);
    expect(showsSchool(privateOnly, 0)).toBe(false);
    expect(showsSchool(privateOnly, PRIVATE_FLAG)).toBe(true);
    expect(sameFilter(withKind(publicOnly, 'private', true), SHOW_ALL)).toBe(true);
    expect(sameFilter(publicOnly, privateOnly)).toBe(false);
  });
});
