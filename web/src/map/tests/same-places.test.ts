// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  COVER_LOOK_EVERY,
  COVER_MS,
  LIST_EVERY,
  PLACES_PART,
  SLICE_MS,
  SamePlaceCovers,
  coveredBy,
  coveredNow,
  samePlaces,
  samePlacesNow,
  taskLoop,
} from '../same-places';
import type {
  Builders,
  CoverMarks,
  PlacesWorker,
  SamePlaces,
  StepKind,
  Tasks,
} from '../same-places';

/** No lit schools, for an ask that wants the index alone. */
const NONE_LIT = new Int32Array(0);

/** The directory's schools (2026-10 edition). */
const DIRECTORY_SCHOOLS = 118_211;

/**
 * SYNTHETIC places in millionths of a degree, as many as the directory's, over the lower 48:
 * one school in sixteen at the place of the one before it, so one in eight shares a place.
 */
function syntheticDirectory(count = DIRECTORY_SCHOOLS): Int32Array {
  const places = new Int32Array(count * 2);
  let seed = 7;
  // In 32-bit integers: a product in doubles past 2^53 loses its low bits, and the places
  // would fall on a few thousand spots.
  const next = (): number => {
    seed = (Math.imul(seed, 1_103_515_245) + 12_345) >>> 0;
    return seed / 4_294_967_296;
  };
  for (let i = 0; i < count; i++) {
    places[i * 2] = Math.round((-124 + next() * 57) * 1e6);
    places[i * 2 + 1] = Math.round((25 + next() * 24) * 1e6);
  }
  for (let i = 1; i < count; i += 16) {
    places[i * 2] = places[i * 2 - 2] ?? 0;
    places[i * 2 + 1] = places[i * 2 - 1] ?? 0;
  }
  return places;
}

/** A loop of tasks that counts and times them, and the gaps between them. */
function countedLoop(): Tasks & { readonly ran: number; readonly busyMs: number } {
  const loop = taskLoop();
  let ran = 0;
  let busyMs = 0;
  const timed = (task: () => void): void => {
    const start = performance.now();
    task();
    busyMs += performance.now() - start;
    ran++;
  };
  return {
    post(task) {
      loop.post(() => {
        timed(task);
      });
    },
    run(task) {
      loop.run(() => {
        timed(task);
      });
    },
    close() {
      loop.close();
    },
    get ran() {
      return ran;
    },
    get busyMs() {
      return busyMs;
    },
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('the index of the schools at one place, built on the page where no worker starts', () => {
  it('comes in on a page that is never idle and whose timers never come due', async () => {
    // A page that draws its map every frame gives an idle callback no time, and one there only
    // runs when its wait times out: the build must not wait on either.
    const idle = vi.fn();
    vi.stubGlobal('requestIdleCallback', idle);
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'setImmediate'],
    });
    const places = syntheticDirectory(20_000);
    const index = await new Promise<SamePlaces>((resolve) => {
      expect(samePlaces(places, NONE_LIT, resolve)).toBeNull();
    });
    expect(idle).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    expect(index).toEqual(samePlacesNow(places));
    // Asked again, it is there at once.
    expect(samePlaces(places, NONE_LIT, () => undefined)).toBe(index);
  });

  it('is in, on a directory the size of the real one, a few tasks after the light asks for it', async () => {
    const places = syntheticDirectory();
    const tasks = countedLoop();
    const asked = performance.now();
    const index = await new Promise<SamePlaces>((resolve) => {
      samePlaces(places, NONE_LIT, resolve, { tasks });
    });
    const wallMs = performance.now() - asked;
    expect(index.shared).toBeGreaterThan(DIRECTORY_SCHOOLS / 8);
    // Each slice but the last works its full SLICE_MS, so the tasks are as few as the work
    // allows (and one more, which tells the light it is in).
    expect(tasks.ran).toBeLessThanOrEqual(Math.ceil(tasks.busyMs / SLICE_MS) + 2);
    // And they run one after another, with no wait for idle time or a timer between them: the
    // wait between slices was 50 ms each when they waited for the page to be idle.
    expect((wallMs - tasks.busyMs) / tasks.ran).toBeLessThan(2);
  });

  it('waits on one build however many lights ask for it before it is in', async () => {
    const places = syntheticDirectory(5_000);
    const tasks = countedLoop();
    const told: SamePlaces[] = [];
    const first = new Promise<void>((resolve) => {
      samePlaces(
        places,
        NONE_LIT,
        (index) => {
          told.push(index);
          resolve();
        },
        { tasks },
      );
    });
    // The second light's own loop is never used: it waits on the first's build.
    const unused = countedLoop();
    expect(
      samePlaces(
        places,
        NONE_LIT,
        (index) => {
          told.push(index);
        },
        { tasks: unused },
      ),
    ).toBeNull();
    await first;
    expect(told).toHaveLength(2);
    expect(told[0]).toBe(told[1]);
    expect(unused.ran).toBe(0);
    unused.close();
  });
});

/**
 * A worker that answers as `answer` says, each message of an answer on a task of its own as a
 * worker's answers come.
 */
class FakeWorker implements PlacesWorker {
  onmessage: ((event: MessageEvent<unknown>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessageerror: ((event: MessageEvent<unknown>) => void) | null = null;
  /** What it was sent, the places put together from their parts. */
  sent: { places: Int32Array; lit: Int32Array }[] = [];
  /** The parts, as many as were sent, and each part's length. */
  parts: number[] = [];
  handedOver: Transferable[] = [];
  terminated = false;
  private places: Int32Array[] = [];
  constructor(
    private readonly answer: (message: { places: Int32Array; lit: Int32Array }) => unknown,
  ) {}
  postMessage(message: unknown, transfer: Transferable[]): void {
    this.handedOver.push(...transfer);
    // Structured clone, as a worker's: the worker gets a copy, and what is handed over is gone
    // from the page.
    const { part, lit } = structuredClone(message, { transfer }) as {
      part?: Int32Array;
      lit?: Int32Array;
    };
    if (part !== undefined) {
      this.parts.push(part.length);
      this.places.push(part.slice());
      return;
    }
    if (lit === undefined) return;
    const places = new Int32Array(this.places.reduce((sum, part) => sum + part.length, 0));
    let at = 0;
    for (const part of this.places) {
      places.set(part, at);
      at += part.length;
    }
    const copy = { places, lit: lit.slice() };
    this.sent.push(copy);
    const answered = this.answer(copy);
    // An answer of several messages, each on a task of its own, in order.
    for (const data of Array.isArray(answered) ? (answered as unknown[]) : [answered]) {
      setTimeout(() => {
        if (this.terminated) return;
        if (data instanceof Event) this.onerror?.(data);
        else this.onmessage?.(new MessageEvent('message', { data }));
      }, 0);
    }
  }
  terminate(): void {
    this.terminated = true;
  }
}

/** same-places-worker.ts's own handler, with what it answers each message. */
async function realWorker(): Promise<{
  send(data: unknown): void;
  readonly answers: unknown[];
  close(): void;
}> {
  const scope = globalThis as unknown as {
    onmessage: ((event: MessageEvent<unknown>) => void) | null;
    postMessage: unknown;
  };
  const before = { onmessage: scope.onmessage, postMessage: scope.postMessage };
  const answers: unknown[] = [];
  scope.postMessage = (message: unknown) => {
    answers.push(message);
  };
  vi.resetModules();
  await import('../same-places-worker');
  const handler = scope.onmessage;
  return {
    send(data) {
      handler?.(new MessageEvent('message', { data }));
    },
    answers,
    close() {
      scope.onmessage = before.onmessage;
      scope.postMessage = before.postMessage;
    },
  };
}

/** What same-places-worker.ts answers for these places, sent in parts, and lit schools. */
async function workerAnswer(message: { places: Int32Array; lit: Int32Array }): Promise<unknown[]> {
  const worker = await realWorker();
  try {
    const { places, lit } = message;
    for (let at = 0; at < places.length; at += PLACES_PART) {
      worker.send({ part: places.slice(at, at + PLACES_PART), at, length: places.length });
    }
    worker.send({ lit });
    return worker.answers;
  } finally {
    worker.close();
  }
}

describe('the schools a light covers, worked out straight from the places', () => {
  it('are the ones the index gives, near the edges of its cells too', () => {
    // SYNTHETIC: the directory's own, and pairs a metre or so apart at every side of a cell's
    // edge (cells of 256 by 128 millionths), some just under 2 m and some just over.
    const base = syntheticDirectory(30_000);
    const extra: number[] = [];
    let seed = 11;
    const next = (): number => {
      seed = (seed * 1_103_515_245 + 12_345) % 2_147_483_648;
      return seed / 2_147_483_648;
    };
    for (let n = 0; n < 3_000; n++) {
      const x = (Math.floor((-120 + next() * 50) * 1e6) >> 8) << 8;
      const y = (Math.floor((26 + next() * 20) * 1e6) >> 7) << 7;
      const dx = Math.round((next() - 0.5) * 40);
      const dy = Math.round((next() - 0.5) * 30);
      extra.push(x, y, x + dx, y + dy);
    }
    const places = Int32Array.from([...base, ...extra]);
    const count = places.length >> 1;
    const index = samePlacesNow(places);
    for (const every of [1, 2, 3, 7, 10, 200]) {
      for (const offset of [0, 1]) {
        const lit = Int32Array.from(
          { length: Math.floor((count - offset) / every) },
          (_, n) => offset + n * every,
        );
        const sorted = (list: Int32Array): number[] => [...list].sort((a, b) => a - b);
        expect(sorted(coveredNow(places, lit))).toEqual(sorted(coveredBy(index, lit)));
      }
    }
    expect(coveredNow(places, new Int32Array(0))).toHaveLength(0);
    // A school lit twice, or one out of the directory, counted once or not at all.
    const twice = Int32Array.of(0, 0, 1, -1, count + 5);
    expect([...coveredNow(places, twice)].sort()).toEqual([...coveredBy(index, twice)].sort());
  });
});

describe('the index of the schools at one place, built in a worker', () => {
  it('answers with the schools the asking light covers, then the same index, built off the page', async () => {
    const places = syntheticDirectory(80_000);
    // Every hundredth school lit, the first of a shared place among them.
    const lit = Int32Array.from({ length: 200 }, (_, n) => n * 100);
    const answers = await workerAnswer({ places, lit });
    const worker = new FakeWorker(() => answers);
    const tasks = countedLoop();
    const told: string[] = [];
    // The list handed over, not copied: gone from the page once sent.
    const handed = lit.slice();
    let covered: Int32Array | null = null;
    const index = await new Promise<SamePlaces>((resolve) => {
      expect(
        samePlaces(
          places,
          handed,
          (ready) => {
            told.push('index');
            resolve(ready);
          },
          { worker: () => worker, tasks },
          // No time to spare: the first part sent in the call that asks, the rest in a task
          // after it.
          -Infinity,
          (first) => {
            told.push('covered');
            covered = first;
          },
        ),
      ).toBeNull();
    });
    // Compared number by number: a deep compare of lists this long takes seconds.
    const same = (a: Int32Array | undefined | null, b: Int32Array): boolean =>
      a?.length === b.length && a.every((value, i) => value === b[i]);
    const now = samePlacesNow(places);
    expect(same(index.start, now.start) && same(index.near, now.near)).toBe(true);
    expect(index.shared).toBe(now.shared);
    expect(told).toEqual(['covered', 'index']);
    const sorted = (list: Int32Array | null): number[] => [...(list ?? [])].sort((a, b) => a - b);
    expect(sorted(covered)).toEqual(sorted(coveredBy(now, lit)));
    expect(sorted(covered).length).toBeGreaterThan(0);
    // Copies of the places handed over to it a part at a time, then the lit ones' list itself;
    // the worker let go once it answers.
    expect(worker.sent).toHaveLength(1);
    expect(same(worker.sent[0]?.places, places) && same(worker.sent[0]?.lit, lit)).toBe(true);
    expect(handed.length).toBe(0);
    expect(worker.parts).toHaveLength(Math.ceil((80_000 * 2) / PLACES_PART));
    expect(worker.parts.length).toBeGreaterThan(1);
    expect(Math.max(...worker.parts)).toBeLessThanOrEqual(PLACES_PART);
    expect(worker.handedOver).toHaveLength(worker.parts.length + 1);
    expect(worker.terminated).toBe(true);
    // Of the build, only the task that sends it the places after the first part, and the
    // events of its two answers, ran on the page.
    expect(tasks.ran).toBe(3);
    tasks.close();
  });

  it('is sent the places whole in the task that asks when there is time for them', async () => {
    const places = syntheticDirectory(80_000);
    const lit = Int32Array.of(0, 16);
    const answers = await workerAnswer({ places, lit });
    const worker = new FakeWorker(() => answers);
    const tasks = countedLoop();
    await new Promise<void>((resolve) => {
      samePlaces(
        places,
        lit,
        () => {
          resolve();
        },
        { worker: () => worker, tasks },
        Infinity,
      );
      // Every part and the lit ones out before the call returns.
      expect(worker.parts.length).toBeGreaterThan(1);
      expect(worker.sent).toHaveLength(1);
    });
    // The answers taken in their own events: no task of the loop's posted for them.
    expect(tasks.ran).toBe(2);
    tasks.close();
  });

  it('is built on the page instead when the worker fails or answers with something else', async () => {
    const answers: ((message: { places: Int32Array; lit: Int32Array }) => unknown)[] = [
      () => new Event('error'),
      () => null,
      () => ({ start: new Int32Array(3), near: new Int32Array(0), shared: 0 }),
      ({ places }) => {
        const { start, near } = samePlacesNow(places);
        return [{ covered: new Int32Array(0) }, { start, near: near.subarray(1), shared: 1 }];
      },
      ({ places }) => ({ ...samePlacesNow(places), start: [1, 2] }),
      () => [{ covered: [1, 2] }, { refused: true }],
    ];
    for (const answer of answers) {
      const places = syntheticDirectory(3_000);
      const worker = new FakeWorker(answer);
      const tasks = countedLoop();
      const told: Int32Array[] = [];
      const index = await new Promise<SamePlaces>((resolve) => {
        samePlaces(places, NONE_LIT, resolve, { worker: () => worker, tasks }, undefined, (c) => {
          told.push(c);
        });
      });
      expect(index).toEqual(samePlacesNow(places));
      // Built on the page, it leaves the covered schools to the page to find (a first answer
      // that is a list is told as one, and the index built on the page all the same).
      expect(told.every((list) => list instanceof Int32Array)).toBe(true);
      expect(worker.terminated).toBe(true);
      expect(tasks.ran).toBeGreaterThan(1);
    }
  });

  it('refuses places sent out of order or not whole, and builds from parts that are', async () => {
    const places = syntheticDirectory(10_000);
    const lit = Int32Array.of(0, 16);
    const whole = await workerAnswer({ places, lit });
    expect(whole).toHaveLength(2);
    const [first, second] = whole as [{ covered: Int32Array }, SamePlaces];
    expect([...first.covered].sort((a, b) => a - b)).toEqual(
      [...coveredBy(samePlacesNow(places), lit)].sort((a, b) => a - b),
    );
    expect(second).toEqual(samePlacesNow(places));
    const worker = await realWorker();
    try {
      // The lit schools before any place, a part out of order, and one too long.
      worker.send({ lit });
      worker.send({ part: places.slice(0, 4), at: 0, length: places.length });
      worker.send({ part: places.slice(8, 12), at: 8, length: places.length });
      worker.send({ part: places.slice(0, 4), at: 0, length: 2 });
      expect(worker.answers).toEqual([{ refused: true }, { refused: true }, { refused: true }]);
      // A part short of the rest: refused when the lit ones come.
      worker.send({ part: places.slice(0, 4), at: 0, length: places.length });
      worker.send({ lit });
      expect(worker.answers.at(-1)).toEqual({ refused: true });
    } finally {
      worker.close();
    }
  });

  it('is built on the page where no worker starts', async () => {
    const places = syntheticDirectory(3_000);
    const tasks = countedLoop();
    const index = await new Promise<SamePlaces>((resolve) => {
      samePlaces(places, NONE_LIT, resolve, { worker: () => null, tasks });
    });
    expect(index).toEqual(samePlacesNow(places));
    expect(tasks.ran).toBeGreaterThan(0);
  });
});

/** Marks that keep which schools are covered, and every call made on them, task by task. */
class Marks implements CoverMarks {
  readonly on = new Set<number>();
  calls = 0;
  inTask = 0;
  mostInATask = 0;
  canMark = true;
  ready(): boolean {
    return this.canMark;
  }
  cover(school: number, on: boolean): void {
    // Never covered twice, nor uncovered while not covered.
    expect(this.on.has(school)).toBe(!on);
    if (on) this.on.add(school);
    else this.on.delete(school);
    this.calls++;
    this.inTask++;
    this.mostInATask = Math.max(this.mostInATask, this.inTask);
  }
  sorted(): number[] {
    return [...this.on].sort((a, b) => a - b);
  }
}

/** A loop whose tasks reset the marks' count of calls in a task. */
function markedLoop(marks: Marks): Tasks & { readonly ran: number } {
  const loop = countedLoop();
  const reset = (task: () => void) => () => {
    marks.inTask = 0;
    task();
  };
  return {
    post(task) {
      loop.post(reset(task));
    },
    run(task) {
      loop.run(reset(task));
    },
    close() {
      loop.close();
    },
    get ran() {
      return loop.ran;
    },
  };
}

/** Covers on `marks`, and a promise of each time a light's are all marked. */
function coversOn(marks: Marks, builders: Omit<Builders, 'covered' | 'tasks'> = {}) {
  let done: (() => void)[] = [];
  const tasks = markedLoop(marks);
  const covers = new SamePlaceCovers(marks, {
    worker: () => null,
    ...builders,
    tasks,
    covered: () => {
      for (const call of done.splice(0)) call();
    },
  });
  const settled = (): Promise<void> =>
    covers.settled
      ? Promise.resolve()
      : new Promise<void>((resolve) => {
          done.push(resolve);
        });
  return { covers, tasks, settled, reset: () => (done = []) };
}

/** The schools covered for a light, as the index says: sorted. */
function expected(places: Int32Array, lit: readonly number[]): number[] {
  return [...coveredBy(samePlacesNow(places), Int32Array.from(lit))].sort((a, b) => a - b);
}

describe('the schools a light covers', () => {
  it('are covered in tasks after the light, on a page never idle, and uncovered when it goes', async () => {
    vi.stubGlobal('requestIdleCallback', vi.fn());
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'setImmediate'],
    });
    const places = syntheticDirectory(20_000);
    const marks = new Marks();
    const { covers, settled } = coversOn(marks);
    const lit = Array.from({ length: 2_000 }, (_, n) => n * 10);
    covers.light(places, new Set(lit));
    // The light's own call marks nothing.
    expect(marks.calls).toBe(0);
    await settled();
    expect(marks.sorted()).toEqual(expected(places, lit));
    expect(marks.sorted().length).toBeGreaterThan(100);
    expect([...covers.covered].sort((a, b) => a - b)).toEqual(marks.sorted());
    // Nothing lit: every one uncovered.
    covers.light(undefined, new Set());
    await settled();
    expect(marks.on.size).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('are marked a few at a time, each task stopping at its time', async () => {
    const places = syntheticDirectory(20_000);
    const lit = Array.from({ length: 4_000 }, (_, n) => n * 5);
    const marks = new Marks();
    const { covers, tasks, settled } = coversOn(marks);
    covers.light(places, new Set(lit));
    // The index in, and the light's schools covered, at the page's own pace.
    await settled();
    const covering = marks.calls;
    expect(covering).toBeGreaterThan(400);
    // A clock that runs out after one look: one step, COVER_LOOK_EVERY schools, per task.
    let now = 0;
    const clock = vi.spyOn(performance, 'now').mockImplementation(() => (now += COVER_MS + 0.1));
    try {
      const before = tasks.ran;
      marks.mostInATask = 0;
      covers.light(places, new Set(lit.slice(1)));
      await settled();
      covers.light(undefined, new Set());
      await settled();
      expect(marks.on.size).toBe(0);
      expect(marks.mostInATask).toBeLessThanOrEqual(COVER_LOOK_EVERY);
      // Every one uncovered at the end, COVER_LOOK_EVERY a task at most.
      expect(tasks.ran - before).toBeGreaterThanOrEqual(covering / COVER_LOOK_EVERY);
    } finally {
      clock.mockRestore();
    }
  });

  it('follow the light shown, however often it changes while they are worked out', async () => {
    const places = syntheticDirectory(20_000);
    const marks = new Marks();
    const { covers, settled } = coversOn(marks);
    const lights = [
      Array.from({ length: 3_000 }, (_, n) => n * 6),
      Array.from({ length: 3_000 }, (_, n) => n * 6 + 1),
      Array.from({ length: 1_000 }, (_, n) => n * 16),
    ];
    // Changed before the index is in, then each before the one before it is all marked.
    covers.light(places, new Set(lights[0]));
    covers.light(places, new Set(lights[1]));
    for (let round = 0; round < 6; round++) {
      const shown = lights[round % 3] ?? [];
      covers.light(places, new Set(shown));
      for (let n = 0; n < round; n++) await new Promise((resolve) => setTimeout(resolve, 0));
    }
    const last = lights[5 % 3] ?? [];
    await settled();
    expect(marks.sorted()).toEqual(expected(places, last));
    // No school it lights is covered.
    expect(last.some((school) => marks.on.has(school))).toBe(false);
  });

  it('are marked only once the marks can be put on', async () => {
    const places = syntheticDirectory(5_000);
    const lit = Array.from({ length: 500 }, (_, n) => n * 10);
    const marks = new Marks();
    marks.canMark = false;
    const { covers, settled } = coversOn(marks);
    covers.light(places, new Set(lit));
    for (let n = 0; n < 200; n++) await new Promise((resolve) => setTimeout(resolve, 0));
    expect(marks.calls).toBe(0);
    expect(covers.settled).toBe(false);
    marks.canMark = true;
    covers.resume();
    await settled();
    expect(marks.sorted()).toEqual(expected(places, lit));
  });

  it('come from the worker for the light that asked, with none looked up on the page', async () => {
    const places = syntheticDirectory(5_000);
    const lit = [0, 16, 32];
    // A worker that answers its own index and, to tell its list from one the page finds, only
    // the school beside the first.
    const worker = new FakeWorker(({ places: sent }) => [
      { covered: Int32Array.of(1) },
      samePlacesNow(sent),
    ]);
    const marks = new Marks();
    const { covers, settled } = coversOn(marks, { worker: () => worker });
    covers.light(places, new Set(lit));
    await settled();
    expect(marks.sorted()).toEqual([1]);
    expect(worker.sent[0]?.lit).toEqual(Int32Array.from(lit));
    // The next light's are found on the page, from the index the worker gave.
    covers.light(places, new Set([16, 32]));
    await settled();
    expect(marks.sorted()).toEqual(expected(places, [16, 32]));
  });

  it('are found on the page for a light shown after the one the worker was asked for', async () => {
    const places = syntheticDirectory(5_000);
    const worker = new FakeWorker(({ places: sent }) => [
      { covered: Int32Array.of(1) },
      samePlacesNow(sent),
    ]);
    const marks = new Marks();
    const { covers, settled } = coversOn(marks, { worker: () => worker });
    covers.light(places, new Set([0]));
    // Let the ask go out, then another light before the answer comes.
    while (worker.sent.length === 0) await new Promise((resolve) => setTimeout(resolve, 0));
    covers.light(places, new Set([16]));
    await settled();
    expect(worker.sent).toHaveLength(1);
    expect(marks.sorted()).toEqual(expected(places, [16]));
  });

  it('make no worker until a light has schools lit, and let it go once it answers', async () => {
    const places = syntheticDirectory(5_000);
    const made: FakeWorker[] = [];
    const factory = (): FakeWorker => {
      const worker = new FakeWorker(({ places: sent, lit }) => [
        { covered: coveredNow(sent, lit) },
        samePlacesNow(sent),
      ]);
      made.push(worker);
      return worker;
    };
    const marks = new Marks();
    const { covers, tasks, settled } = coversOn(marks, { worker: factory });
    // Nothing lit, or no directory: no worker, nothing built, no task left.
    covers.light(undefined, new Set());
    await settled();
    covers.light(places, new Set());
    await settled();
    covers.light(undefined, new Set([0]));
    await settled();
    expect(made).toHaveLength(0);
    // A light with schools lit: made in its call, to start on its own thread while the page
    // lists them, and sent nothing until the task after it.
    const before = tasks.ran;
    covers.light(places, new Set([0, 16]));
    expect(made).toHaveLength(1);
    expect(made[0]?.parts).toHaveLength(0);
    // Another light, or none, before then makes no other.
    covers.light(places, new Set([0]));
    covers.light(places, new Set([0, 16]));
    expect(made).toHaveLength(1);
    await settled();
    expect(made).toHaveLength(1);
    expect(made[0]?.sent).toHaveLength(1);
    // Marked from the first answer, before the index is in; the worker let go once it is.
    expect(made[0]?.terminated).toBe(false);
    expect(marks.sorted()).toEqual(expected(places, [0, 16]));
    while (made[0]?.terminated !== true) await new Promise((resolve) => setTimeout(resolve, 0));
    // Listed, asked and the places sent in one task; marked in the event of the first answer,
    // the index taken in the event of the second.
    expect(tasks.ran - before).toBe(3);
    expect(marks.sorted()).toEqual(expected(places, [0, 16]));
    // Later lights are found with the index, with no worker.
    covers.light(places, new Set([16]));
    await settled();
    expect(made).toHaveLength(1);
    expect(marks.sorted()).toEqual(expected(places, [16]));
    // One that fails builds nothing; the page builds the index itself.
    const other = new Marks();
    const failing = coversOn(other, {
      worker: () => {
        const worker = new FakeWorker(() => new Event('error'));
        made.push(worker);
        return worker;
      },
    });
    const elsewhere = syntheticDirectory(5_000);
    failing.covers.light(elsewhere, new Set([0, 16]));
    await failing.settled();
    expect(made.at(-1)?.terminated).toBe(true);
    expect(other.sorted()).toEqual(expected(elsewhere, [0, 16]));
  });

  it('are none after close', async () => {
    const places = syntheticDirectory(5_000);
    const marks = new Marks();
    const { covers } = coversOn(marks);
    covers.light(places, new Set([0, 16]));
    covers.close();
    for (let n = 0; n < 50; n++) await new Promise((resolve) => setTimeout(resolve, 0));
    expect(marks.calls).toBe(0);
    // A worker made at the light and not yet asked is let go, sent nothing.
    const worker = new FakeWorker(({ places: sent, lit }) => [
      { covered: coveredNow(sent, lit) },
      samePlacesNow(sent),
    ]);
    const other = coversOn(new Marks(), { worker: () => worker });
    other.covers.light(places, new Set([0, 16]));
    other.covers.close();
    for (let n = 0; n < 50; n++) await new Promise((resolve) => setTimeout(resolve, 0));
    expect(worker.terminated).toBe(true);
    expect(worker.parts).toHaveLength(0);
  });
});

/**
 * The lead's ruling R4-B1-MEASURE, gate B: what each task of the page's work for a light does,
 * counted, not timed, so it holds on any machine.
 */
describe('the page’s work for a light, counted rather than timed', () => {
  /** What a day's lights did, task by task: the most a task looked at, by step, and marked. */
  interface Counted {
    readonly covered: number;
    readonly tasks: number;
    readonly marked: number;
    readonly looked: Partial<Record<StepKind, number>>;
    readonly tasksOf: Partial<Record<StepKind, number>>;
  }

  /**
   * SYNTHETIC: a directory where each sixteenth school shares its place with the one before it,
   * `shared` of those pairs lit by their first school, so as many covered, and eleven lit schools
   * at places of their own after each: a light of 12 x `shared` lit schools. Then a light with
   * every other of those pairs and as many others, and then none lit; on a clock that runs out
   * at every look, so a task is one step.
   */
  async function countDay(places: Int32Array, shared: number): Promise<Counted> {
    const count = places.length >> 1;
    const own: number[] = [];
    for (let i = 0; i < count && own.length < shared * 11 * 2; i++) if (i % 16 > 1) own.push(i);
    const light = (pairs: readonly number[], from: number): Set<number> => {
      const lit = new Set<number>();
      pairs.forEach((pair, n) => {
        lit.add(pair * 16);
        for (let k = 0; k < 11; k++) lit.add(own[from + n * 11 + k] ?? -1);
      });
      return lit;
    };
    const first = Array.from({ length: shared }, (_, n) => n);
    const second = Array.from({ length: shared }, (_, n) => (n % 2 === 0 ? n : shared + n));
    const worker = (): FakeWorker =>
      new FakeWorker(({ places: sent, lit }) => [
        { covered: coveredNow(sent, lit) },
        samePlacesNow(sent),
      ]);
    const marks = new Marks();
    let looked: Partial<Record<StepKind, number>> = {};
    const most: Partial<Record<StepKind, number>> = {};
    const tasksOf: Partial<Record<StepKind, number>> = {};
    let tasks = 0;
    let marked = 0;
    const loop = taskLoop();
    const counted = (task: () => void) => () => {
      marks.inTask = 0;
      looked = {};
      task();
      tasks++;
      marked = Math.max(marked, marks.inTask);
      for (const [kind, n] of Object.entries(looked) as [StepKind, number][]) {
        most[kind] = Math.max(most[kind] ?? 0, n);
        tasksOf[kind] = (tasksOf[kind] ?? 0) + 1;
      }
    };
    let done: (() => void) | null = null;
    const covers = new SamePlaceCovers(marks, {
      worker,
      tasks: {
        post(task) {
          loop.post(counted(task));
        },
        run(task) {
          counted(task)();
        },
        close() {
          loop.close();
        },
      },
      steps(kind, n) {
        looked[kind] = (looked[kind] ?? 0) + n;
      },
      covered: () => {
        done?.();
      },
    });
    const shown = async (lit: Set<number>): Promise<void> => {
      const settled = new Promise<void>((resolve) => {
        done = resolve;
      });
      covers.light(lit.size > 0 ? places : undefined, lit);
      await settled;
    };
    let now = 0;
    const clock = vi.spyOn(performance, 'now').mockImplementation(() => (now += COVER_MS + 0.1));
    try {
      const firstLit = light(first, 0);
      await shown(firstLit);
      const covered = marks.on.size;
      expect(marks.sorted()).toEqual(expected(places, [...firstLit]));
      const secondLit = light(second, shared * 11);
      await shown(secondLit);
      expect(marks.sorted()).toEqual(expected(places, [...secondLit]));
      await shown(new Set());
      expect(marks.on.size).toBe(0);
      return { covered, tasks, marked, looked: most, tasksOf };
    } finally {
      clock.mockRestore();
      covers.close();
    }
  }

  it('looks at and marks no more in a task on a day that covers ten times the schools, only in more tasks', async () => {
    // A directory of its own each day, so each builds its index from the first light on.
    const usual = await countDay(syntheticDirectory(100_000), 300);
    const big = await countDay(syntheticDirectory(100_000), 3_000);
    expect(usual.covered).toBe(300);
    expect(big.covered).toBe(3_000);
    // The same most in a task, step by step, whichever the day: no step's work grows with the
    // schools a light covers or lights; the fixed bounds of same-places.ts.
    expect(big.looked).toEqual(usual.looked);
    expect(big.marked).toBe(usual.marked);
    expect(usual.marked).toBe(COVER_LOOK_EVERY);
    const bound: Record<StepKind, number> = {
      fit: 0,
      listing: LIST_EVERY,
      ask: 0,
      // The directory's places, a part at a time: as many whatever the day.
      send: 100_000,
      stamping: COVER_LOOK_EVERY * 16,
      // Each lit school looked at, and the others at its place: one here.
      finding: COVER_LOOK_EVERY * 4 * 2,
      wanting: COVER_LOOK_EVERY * 16,
      uncovering: COVER_LOOK_EVERY * 16,
      covering: COVER_LOOK_EVERY * 16,
    };
    for (const [kind, n] of Object.entries(usual.looked) as [StepKind, number][]) {
      expect(n, kind).toBeLessThanOrEqual(bound[kind]);
    }
    // At the bound on both days where the day has that many to look at.
    for (const kind of ['listing', 'stamping', 'wanting'] as const) {
      expect(usual.looked[kind], kind).toBe(bound[kind]);
    }
    // Every step of the page's path ran on both days.
    expect(Object.keys(usual.looked).sort()).toEqual([
      'ask',
      'covering',
      'finding',
      'fit',
      'listing',
      'send',
      'stamping',
      'uncovering',
      'wanting',
    ]);
    // Ten times the lit and covered schools in more tasks of the same size.
    for (const kind of [
      'listing',
      'stamping',
      'finding',
      'wanting',
      'uncovering',
      'covering',
    ] as const) {
      expect(big.tasksOf[kind] ?? 0, kind).toBeGreaterThanOrEqual(5 * (usual.tasksOf[kind] ?? 0));
    }
    expect(big.tasks).toBeGreaterThan(5 * usual.tasks);
  });
});
