import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { tries } from '../tries';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

/** Whether a promise has settled, without waiting for it. */
async function settled(promise: Promise<unknown>): Promise<boolean> {
  let done = false;
  void promise.then(
    () => (done = true),
    () => (done = true),
  );
  await vi.advanceTimersByTimeAsync(0);
  return done;
}

describe('tries', () => {
  it('brings what the first try brings, and tries no more', async () => {
    const counts: number[] = [];
    const attempts = tries((count) => {
      counts.push(count);
      return Promise.resolve('code');
    });
    await expect(attempts.won).resolves.toBe('code');
    await expect(attempts.first).resolves.toBeUndefined();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(counts).toEqual([0]);
  });

  it('after a failure, tries again a second later, then less and less often, up to every 30 seconds', async () => {
    const counts: number[] = [];
    const attempts = tries((count) => {
      counts.push(count);
      return Promise.reject(new TypeError('Failed to fetch'));
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(await settled(attempts.first)).toBe(true);
    await vi.advanceTimersByTimeAsync(999);
    expect(counts).toEqual([0]);
    await vi.advanceTimersByTimeAsync(1);
    expect(counts).toEqual([0, 1]);
    await vi.advanceTimersByTimeAsync(2_000 + 4_000 + 8_000 + 16_000);
    expect(counts).toEqual([0, 1, 2, 3, 4, 5]);
    await vi.advanceTimersByTimeAsync(29_999);
    expect(counts).toHaveLength(6);
    await vi.advanceTimersByTimeAsync(1);
    expect(counts).toHaveLength(7);
    attempts.stop();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(counts).toHaveLength(7);
    expect(await settled(attempts.won)).toBe(false);
  });

  it('when a try hangs, gives up waiting on it at its deadline and sets the next going, and a slow one still counts', async () => {
    const answers: ((value: string) => void)[] = [];
    const attempts = tries(
      () =>
        new Promise<string>((resolve) => {
          answers.push(resolve);
        }),
    );
    await vi.advanceTimersByTimeAsync(1_999);
    expect(await settled(attempts.first)).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(await settled(attempts.first)).toBe(true);
    expect(answers).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(answers).toHaveLength(2);
    // The first, late, before the second.
    answers[0]?.('slow');
    await expect(attempts.won).resolves.toBe('slow');
    answers[1]?.('second');
    await vi.advanceTimersByTimeAsync(60_000);
    expect(answers).toHaveLength(2);
  });

  it('settles the first try only after what waits on the win has heard it', async () => {
    const heard: string[] = [];
    const attempts = tries(() => Promise.resolve('code'));
    void attempts.won.then(() => heard.push('won'));
    void attempts.first.then(() => heard.push('first'));
    await vi.advanceTimersByTimeAsync(0);
    expect(heard).toEqual(['won', 'first']);
  });
});
