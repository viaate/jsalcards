/**
 * Tries a download that can fail, or hang without failing, until one try
 * works. The next try starts a while after one fails, or after one has gone
 * `deadline` without an answer; a slow try still counts if it comes first.
 * Each wait doubles, up to `longest`.
 */

export interface TryTimes {
  /** How long a try has before the next one is set going beside it. */
  readonly deadline: number;
  /** The wait before the second try; each later one doubles. */
  readonly wait: number;
  readonly longest: number;
}

export const TRY_TIMES: TryTimes = { deadline: 2_000, wait: 1_000, longest: 30_000 };

export interface Tries<T> {
  /** What the first try to work brings. */
  readonly won: Promise<T>;
  /** Settles once the first try has worked, failed or gone past its deadline. */
  readonly first: Promise<void>;
  /** No more tries, and none heard from. */
  readonly stop: () => void;
}

export function tries<T>(attempt: (count: number) => Promise<T>, times = TRY_TIMES): Tries<T> {
  let over = false;
  const timers = new Set<ReturnType<typeof setTimeout>>();
  const later = (ms: number, run: () => void): void => {
    const timer = setTimeout(() => {
      timers.delete(timer);
      if (!over) run();
    }, ms);
    timers.add(timer);
  };
  const stop = (): void => {
    over = true;
    for (const timer of timers) clearTimeout(timer);
    timers.clear();
  };
  let win: (value: T) => void = () => undefined;
  const won = new Promise<T>((resolve) => {
    win = resolve;
  });
  let firstOver: () => void = () => undefined;
  const first = new Promise<void>((resolve) => {
    firstOver = resolve;
  });

  const run = (count: number, wait: number): void => {
    let moved = false;
    const next = (): void => {
      if (moved) return;
      moved = true;
      if (count === 0) firstOver();
      later(wait, () => {
        run(count + 1, Math.min(wait * 2, times.longest));
      });
    };
    later(times.deadline, next);
    attempt(count).then(
      (value) => {
        if (over) return;
        stop();
        // Before `first`: what waits on the first try finds what it brought.
        win(value);
        firstOver();
      },
      () => {
        if (!over) next();
      },
    );
  };
  run(0, times.wait);
  return { won, first, stop };
}
