/**
 * MapLibre's worker pool, sized to the device: one worker for each four
 * cores, one or two.
 */
import { describe, expect, it } from 'vitest';

import { workerCount } from '../workers';

describe('the worker pool', () => {
  it('has one worker on a phone of four cores or fewer', () => {
    expect(workerCount(1)).toBe(1);
    expect(workerCount(2)).toBe(1);
    expect(workerCount(4)).toBe(1);
    expect(workerCount(6)).toBe(1);
  });

  it('has two from eight cores up, and never more', () => {
    expect(workerCount(8)).toBe(2);
    expect(workerCount(12)).toBe(2);
    expect(workerCount(64)).toBe(2);
  });

  it('has one where the browser does not say', () => {
    expect(workerCount(Number.NaN)).toBe(1);
    expect(workerCount(0)).toBe(1);
  });
});
