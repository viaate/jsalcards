/**
 * The same-place index of a directory (same-places-build.ts), built once for
 * each directory at the page's first light with schools lit, off the page's
 * thread where it can be, and the schools each light covers with it
 * (SamePlaceCovers): found and marked in short tasks of their own, so no task
 * of the page's does work that grows with the schools a light covers. A page
 * with nothing lit makes no worker and builds nothing.
 */
import { SamePlacesBuild } from './same-places-build';
import type { SamePlaces } from './same-places-build';

export {
  SAME_PLACE_METRES,
  SamePlacesBuild,
  atOnePlace,
  coveredBy,
  coveredNow,
  samePlacesNow,
} from './same-places-build';
export type { SamePlaces } from './same-places-build';

/**
 * How long a slice of a build on the page runs, in milliseconds: well under
 * a frame, so a tap or a frame waits on one no longer than that, and a stop
 * of V8's own in it (a collection or a compile, 2 to 3 ms) still leaves it
 * under the 5 ms the page may be kept busy at once.
 */
export const SLICE_MS = 1.5;

/**
 * How long a task of the page's for a light's covered schools runs, in
 * milliseconds: as many steps as it gets through in that (a step lists, finds
 * or marks at most a fixed few, COVER_LOOK_EVERY marks), then the next in a
 * task of its own. Each task is a hop the page may wait a frame for, so a
 * millisecond rather than less: a big day's light takes a few of them.
 */
export const COVER_MS = 1;
export const COVER_LOOK_EVERY = 16;

/** The lit schools a step lists, from the light's set into a list for the worker or the finding. */
export const LIST_EVERY = 2_048;

/**
 * Tasks run one after another, each a task of its own; close drops those not yet run. `run` runs
 * one in the event the page is in already (a worker's answer), so no hop is added for it, and it
 * is the loop's all the same (the bench times every task of the loop's).
 */
export interface Tasks {
  post(task: () => void): void;
  run(task: () => void): void;
  close(): void;
}

/**
 * A loop of tasks that run as soon as the page is free, one after another:
 * not when it is idle, which a page drawing its map every frame seldom is
 * (an idle callback there gets no time and comes only when its wait times
 * out, so a build of thirty milliseconds took seconds), and not on a timer,
 * which nested calls slow to 4 ms apart. A message to its own port is such a
 * task, and the page draws and takes taps between them. The port is let go
 * whenever no task is left, and opened again for the next.
 */
export function taskLoop(): Tasks {
  const run = (task: () => void): void => {
    task();
  };
  if (typeof MessageChannel === 'undefined') {
    // Each close starts another round: a task posted before it is dropped.
    let round = 0;
    return {
      post(task) {
        const posted = round;
        setTimeout(() => {
          if (posted === round) task();
        }, 0);
      },
      run,
      close() {
        round++;
      },
    };
  }
  let channel: MessageChannel | null = null;
  const queue: (() => void)[] = [];
  const shut = (): void => {
    channel?.port1.close();
    channel?.port2.close();
    channel = null;
  };
  return {
    post(task) {
      queue.push(task);
      if (channel === null) {
        const opened = new MessageChannel();
        opened.port1.onmessage = () => {
          const next = queue.shift();
          // Each message has its task, so with none left none is on its way.
          if (queue.length === 0 && channel === opened) shut();
          next?.();
        };
        channel = opened;
      }
      channel.port2.postMessage(null);
    },
    run,
    close() {
      queue.length = 0;
      shut();
    },
  };
}

/** The part of a Worker the build uses (a test gives its own). */
export interface PlacesWorker {
  postMessage(message: unknown, transfer: Transferable[]): void;
  onmessage: ((event: MessageEvent<unknown>) => void) | null;
  onerror: ((event: Event) => void) | null;
  onmessageerror: ((event: MessageEvent<unknown>) => void) | null;
  terminate(): void;
}

/** The worker that builds an index off the page's thread (same-places-worker.ts), or null. */
function placesWorker(): PlacesWorker | null {
  if (typeof Worker === 'undefined') return null;
  try {
    return new Worker(new URL('./same-places-worker.ts', import.meta.url), {
      type: 'module',
      name: 'snowlight-same-places',
    }) as unknown as PlacesWorker;
  } catch {
    return null;
  }
}

/** The worker's index, if it is one for `count` schools. */
function indexFrom(data: unknown, count: number): SamePlaces | null {
  if (typeof data !== 'object' || data === null) return null;
  const { start, near, shared } = data as Partial<Record<keyof SamePlaces, unknown>>;
  if (!(start instanceof Int32Array) || !(near instanceof Int32Array)) return null;
  if (typeof shared !== 'number' || start.length !== count + 1) return null;
  if (start[count] !== near.length) return null;
  return { start, near, shared };
}

/**
 * The worker's first answer, the schools the asking light covers, if it is that. Each is checked
 * as it is marked (SamePlaceCovers), not here, so taking it does no work that grows with them.
 */
function coveredFrom(data: unknown): Int32Array | null {
  if (typeof data !== 'object' || data === null || 'start' in data) return null;
  const { covered } = data as { covered?: unknown };
  return covered instanceof Int32Array ? covered : null;
}

/**
 * The places are sent the worker in parts of this many numbers (32,768 schools): as many in a
 * task as SEND_MS lets it send, so on a slow page no task copies the whole directory.
 */
export const PLACES_PART = 65_536;

/**
 * How long the task that asks for the index may go on sending the places, in milliseconds: all
 * of them in it (a copy of under a megabyte: under a millisecond, a few on a phone four times
 * slower), as on a page drawing its first tiles each part left for a task after it waits a
 * frame or more, a hundred milliseconds or two on such a phone.
 */
export const SEND_MS = 8;

/** How the index is built: in a worker where one starts, else in slices on the page's tasks. */
export interface Builders {
  /** The worker, or null to build in slices (default: same-places-worker.ts where workers run). */
  readonly worker?: () => PlacesWorker | null;
  /** The loop the page's tasks run on (default: taskLoop; the bench times each). */
  readonly tasks?: Tasks;
  /** Told each time the schools a light covers are all marked (for tests and the bench). */
  readonly covered?: () => void;
  /**
   * Told after each step of the page's work, which step it was and how many schools it looked
   * at (listed, sent, stamped, found or marked): an operation count, not a clock, so a test can
   * show that no step's work grows with the schools a light lights or covers (tests, the bench).
   */
  readonly steps?: (step: StepKind, looked: number) => void;
}

/** The steps of the page's work for a light (Builders.steps). */
export type StepKind =
  | 'fit'
  | 'listing'
  | 'ask'
  | 'send'
  | 'stamping'
  | 'finding'
  | 'wanting'
  | 'uncovering'
  | 'covering';

/** Told the index once it is in. */
export type IndexReady = (index: SamePlaces) => void;

/** Told the schools the lit ones the index was asked with cover, where the worker finds them first. */
export type CoveredFirst = (covered: Int32Array) => void;

interface Pending {
  done: SamePlaces | null;
  readonly waiting: ((index: SamePlaces) => void)[];
}

const built = new WeakMap<Int32Array, Pending>();

/**
 * The index for a directory's places when it is built, else null, and then
 * `ready` is called with it once it is: the first ask starts the build, later
 * asks wait on the same one. It is built in a worker, off the page's thread,
 * so neither its work nor the stops V8 makes in it (a collection, a compile)
 * keep the page busy: the page makes the worker and, in the task that asks
 * (until `until`, then in tasks after it), hands it copies of the places and
 * the list `lit` itself (the schools of the light that asked: the caller lets
 * it go, so it is handed over, not copied), and takes back, each in the event
 * of its answer, the schools that light covers (told `covered`) a few
 * milliseconds on, then the index; the worker is let go then. Where no worker
 * starts, or one fails, it is built on the page in slices of SLICE_MS, each a
 * task of its own, run one after another, and `covered` is never told: the
 * caller finds them with the index.
 */
export function samePlaces(
  places: Int32Array,
  lit: Int32Array,
  ready: IndexReady,
  builders: Builders = {},
  until: number = performance.now() + COVER_MS,
  covered?: CoveredFirst,
): SamePlaces | null {
  const known = built.get(places);
  if (known !== undefined && known.done !== null) return known.done;
  if (known !== undefined) {
    known.waiting.push(ready);
    return null;
  }
  const pending: Pending = { done: null, waiting: [] };
  built.set(places, pending);
  const loop = builders.tasks ?? taskLoop();
  const finish = (done: SamePlaces): void => {
    if (pending.done !== null) return;
    pending.done = done;
    ready(done);
    for (const call of pending.waiting.splice(0)) call(done);
  };
  const inSlices = (): void => {
    // Made in the first slice, not the task that asks.
    let build: SamePlacesBuild | null = null;
    const slice = (): void => {
      const end = performance.now() + SLICE_MS;
      build ??= new SamePlacesBuild(places);
      const done = build.step(() => performance.now() >= end);
      if (done === null) {
        loop.post(slice);
        return;
      }
      // The lights waiting on it are told in a task of their own, not this slice's.
      loop.post(() => {
        finish(done);
      });
    };
    loop.post(slice);
  };
  const worker = (builders.worker ?? placesWorker)();
  if (worker === null) {
    inSlices();
    return null;
  }
  let answered = false;
  let toldCovered = false;
  const fail = (): void => {
    if (answered) return;
    answered = true;
    worker.terminate();
    inSlices();
  };
  // Each answer taken in the event it comes in, as a task of the loop's: the schools the light
  // covers first, then the index, and the worker let go.
  worker.onmessage = (event) => {
    loop.run(() => {
      if (answered) return;
      const first = coveredFrom(event.data);
      if (first !== null) {
        if (!toldCovered) {
          toldCovered = true;
          covered?.(first);
        }
        return;
      }
      const index = indexFrom(event.data, places.length >> 1);
      if (index === null) {
        fail();
        return;
      }
      answered = true;
      worker.terminate();
      finish(index);
    });
  };
  worker.onerror = () => {
    loop.run(fail);
  };
  worker.onmessageerror = () => {
    loop.run(fail);
  };
  // The places a part at a time, then the lit schools: copies handed over, as the directory keeps
  // its places and the caller its list. As many parts as the time lets this task send, the rest
  // in tasks after it.
  const send = (from: number, end: number): void => {
    if (answered) return;
    try {
      for (let at = from; at < places.length; at += PLACES_PART) {
        if (at > from && performance.now() >= end) {
          loop.post(() => {
            send(at, performance.now() + COVER_MS);
          });
          return;
        }
        const part = places.slice(at, at + PLACES_PART);
        builders.steps?.('send', part.length >> 1);
        worker.postMessage({ part, at, length: places.length }, [part.buffer]);
      }
      worker.postMessage({ lit }, lit.byteLength > 0 ? [lit.buffer] : []);
    } catch {
      fail();
    }
  };
  send(0, until);
  return null;
}

/** What a light's covered schools are marked on: their dots and their dust (glow-mount.ts). */
export interface CoverMarks {
  /** Whether marks can be put on now (the map's school tiles are in). */
  ready(): boolean;
  /** Covers this school's marks, or takes the cover off. */
  cover(school: number, on: boolean): void;
  /** Told once the marks for the light shown are all put on (the dust is drawn again once then). */
  settled?(): void;
}

const NO_SCHOOLS = new Int32Array(0);

type Phase =
  | 'idle'
  | 'listing'
  | 'ask'
  | 'waiting'
  | 'stamping'
  | 'finding'
  | 'wanting'
  | 'uncovering'
  | 'covering';

/**
 * The schools covered by each light the glow shows (the schools it does not
 * light at the place of one it does), marked and unmarked on `marks` in
 * tasks of COVER_MS each, so no task of the page's does work that grows with
 * the schools a light covers. The light's own call only notes it, but for
 * the first light of a directory with schools lit, whose call makes the
 * worker for its index (none on a page with nothing lit), so the worker
 * starts on its own thread while the page goes on; that light then lists
 * them in tasks after it and asks for the index, and the worker answers with
 * the schools that light covers, which are marked from the event of that
 * answer on. A light after it lists its own and finds them with
 * the index, a few at a time. Then the schools no longer covered are
 * uncovered and those newly covered covered, a few at a time. A later light
 * takes over at once from where the work for the one before it stands: what
 * is covered is always known exactly (`onList`), so nothing is left covered
 * by a light gone, and no school it lights or does not cover is covered once
 * its work is done.
 */
export class SamePlaceCovers {
  private readonly marks: CoverMarks;
  private readonly builders: Builders;
  private readonly tasks: Tasks;
  /** The light now: the directory's places and the schools it lights; its turn, one per light. */
  private places: Int32Array | null = null;
  private lit: ReadonlySet<number> = new Set();
  private turn = 0;
  /** The index of `places`, once in, and the places whose index is asked for. */
  private index: SamePlaces | null = null;
  private asked: Int32Array | null = null;
  /** Each school's turn it is covered in (a school is wanted when its entry is the turn now). */
  private wanted = new Int32Array(0);
  /**
   * 1 for each school covered now, and the list of them, `onCount` long: as long as the
   * directory, as a school is in it once at most, so it never grows while schools are covered.
   */
  private on = new Uint8Array(0);
  private onList = new Int32Array(0);
  private onCount = 0;
  /**
   * The schools the light now covers, `targetCount` of them, once found (into `found`, as long
   * as the directory, as each is found once) or told (the worker's list).
   */
  private target: Int32Array = NO_SCHOOLS;
  private targetCount = 0;
  private found = new Int32Array(0);
  /** The schools the step now running looked at (Builders.steps). */
  private looked = 0;
  /** The lit schools listed (for the worker, or to find their places' others), and their turn. */
  private litList: Int32Array = NO_SCHOOLS;
  private litListed = 0;
  private litValues: Iterator<number> | null = null;
  private listedTurn = 0;
  /** Each school's turn it is lit in, for the finding. */
  private litTurn = new Int32Array(0);
  private phase: Phase = 'idle';
  /** What comes once the lit schools are listed: the ask for the index, or the finding. */
  private afterListing: 'ask' | 'stamping' = 'stamping';
  /** Where the work of the phase is: a place in a list. */
  private at = 0;
  private posted = false;
  private running = false;
  private closed = false;
  /** Whether the tables are as long as the directory at `places`. */
  private fitted = true;
  /**
   * The worker for the index, made in the call of the first light with schools lit (null where
   * none starts), so it starts while the page lists the lit schools for it; handed to the ask.
   */
  private early: { readonly worker: PlacesWorker | null } | null = null;

  constructor(marks: CoverMarks, builders: Builders = {}) {
    this.marks = marks;
    this.builders = builders;
    this.tasks = builders.tasks ?? taskLoop();
  }

  /** The schools covered now, by their places in the directory (for tests and the bench). */
  get covered(): Int32Array {
    return this.onList.slice(0, this.onCount);
  }

  /** Whether the work for the light now is done. */
  get settled(): boolean {
    return this.phase === 'idle';
  }

  /**
   * Covers the schools at the places of `lit` (schools of the directory at
   * `places`) and no others, in tasks after this one; with no places or none
   * lit, none.
   */
  light(places: Int32Array | undefined, lit: ReadonlySet<number>): void {
    if (this.closed) return;
    this.turn++;
    this.lit = lit;
    if (places === undefined || lit.size === 0) {
      this.target = NO_SCHOOLS;
      this.targetCount = 0;
      this.phase = 'uncovering';
      this.at = this.onCount;
    } else {
      if (places !== this.places) {
        this.places = places;
        this.index = null;
        // Its tables grown in steps of their own, not this call.
        this.fitted = false;
      }
      // The first light of a directory lists its lit schools for the worker that builds the
      // index, and asks for it; a light while it is built waits for it.
      if (this.asked === places && this.index === null) this.phase = 'waiting';
      else this.listing(this.index === null ? 'ask' : 'stamping');
      // Its worker made now, which takes no longer than a task's start: it loads and starts on
      // its own thread while the page lists the lit schools it is sent.
      if (this.index === null && this.asked !== places && this.early === null) {
        this.early = { worker: (this.builders.worker ?? placesWorker)() };
      }
    }
    this.post();
  }

  /** Marks what is covered once the marks can be put on (the map's style came in). */
  resume(): void {
    this.post();
  }

  close(): void {
    this.closed = true;
    this.tasks.close();
    // A worker made and never asked is let go too.
    this.early?.worker?.terminate();
    this.early = null;
  }

  /** One table grown to a directory of `count` schools (what it holds kept); true once all are. */
  private fit(count: number): boolean {
    const grown = <T extends Int32Array | Uint8Array>(table: T, made: T): T => {
      if (table.length > 0) made.set(table);
      return made;
    };
    if (this.wanted.length < count) {
      this.wanted = grown(this.wanted, new Int32Array(count));
      return false;
    }
    if (this.on.length < count) {
      this.on = grown(this.on, new Uint8Array(count));
      return false;
    }
    if (this.litTurn.length < count) {
      this.litTurn = grown(this.litTurn, new Int32Array(count));
      return false;
    }
    if (this.onList.length < count) {
      this.onList = grown(this.onList, new Int32Array(count));
      return false;
    }
    if (this.found.length < count) {
      this.found = new Int32Array(count);
      return false;
    }
    return true;
  }

  /** The lit schools to list, then `next`. */
  private listing(next: 'ask' | 'stamping'): void {
    this.phase = 'listing';
    this.afterListing = next;
  }

  private post(): void {
    if (this.posted || this.closed || this.phase === 'idle') return;
    this.posted = true;
    this.tasks.post(() => {
      this.posted = false;
      this.run();
    });
  }

  /** Works for COVER_MS, then goes on in a task of its own if there is more. */
  private run(): void {
    if (this.closed || this.running || this.phase === 'idle') return;
    this.running = true;
    const until = performance.now() + COVER_MS;
    let more: boolean;
    try {
      // A step at least, then more until the time is up.
      do {
        more = this.step();
      } while (more && performance.now() < until);
    } finally {
      this.running = false;
    }
    if (more) this.post();
    else if (this.settled) {
      this.marks.settled?.();
      this.builders.covered?.();
    }
  }

  /**
   * The lit schools listed, LIST_EVERY a step, from the light's own set: its iterator kept from
   * one step to the next (a set's has no return, so a loop that stops early leaves it where it
   * stopped), as a light's set is never changed.
   */
  private list(): boolean {
    if (this.listedTurn !== this.turn) {
      this.listedTurn = this.turn;
      this.litList = new Int32Array(this.lit.size);
      this.litListed = 0;
      this.litValues = this.lit.values();
    }
    const list = this.litList;
    const values = this.litValues;
    let n = this.litListed;
    const from = n;
    if (values !== null && n < list.length) {
      const end = Math.min(list.length, n + LIST_EVERY);
      for (let next = values.next(); next.done !== true;) {
        list[n++] = next.value;
        if (n >= end) break;
        next = values.next();
      }
      this.litListed = n;
      this.looked = n - from;
      if (n < list.length && n === end) return true;
    }
    // A set that held fewer than its size said: the list as far as it went.
    if (n < list.length) this.litList = list.subarray(0, n);
    this.litValues = null;
    this.phase = this.afterListing;
    this.at = 0;
    return true;
  }

  /** The worker made at the light, taken by its ask (one made then where it was not). */
  private takeWorker(): PlacesWorker | null {
    const early = this.early;
    this.early = null;
    return early === null ? (this.builders.worker ?? placesWorker)() : early.worker;
  }

  /**
   * Asks for the index of the light's places, with its lit schools, in this task: the worker
   * (made at the light) sent the places for SEND_MS, the rest in tasks after it.
   */
  private ask(): boolean {
    const places = this.places;
    if (places === null) return false;
    const turn = this.turn;
    this.phase = 'waiting';
    if (this.asked === places) return false;
    this.asked = places;
    // The list handed over to the worker, not copied: listed again from the light's set if the
    // index is wanted for the finding (built on the page, or a light since).
    const lit = this.litList;
    this.litList = NO_SCHOOLS;
    this.listedTurn = -1;
    const index = samePlaces(
      places,
      lit,
      (ready) => {
        if (this.closed || this.places !== places) return;
        this.index = ready;
        // A light since, or none found first (built on the page): found with the index.
        if (this.phase !== 'waiting') return;
        this.listing('stamping');
        this.run();
      },
      { ...this.builders, tasks: this.tasks, worker: () => this.takeWorker() },
      performance.now() + SEND_MS,
      (covered) => {
        if (this.closed || this.places !== places) return;
        if (this.phase !== 'waiting' || this.turn !== turn) return;
        // The worker found them for this very light: none to look up on the page, and marked
        // from the event of its answer on, not a task after it.
        this.target = covered;
        this.targetCount = covered.length;
        this.phase = 'wanting';
        this.at = 0;
        this.run();
      },
    );
    if (index === null) return false;
    this.index = index;
    this.listing('stamping');
    return true;
  }

  /**
   * A step of the work: COVER_LOOK_EVERY marks at most, and a few hundred schools looked at;
   * false once there is none left.
   */
  private step(): boolean {
    this.looked = 0;
    if (!this.fitted && this.phase !== 'uncovering' && this.phase !== 'covering') {
      this.fitted = this.fit((this.places?.length ?? 0) >> 1);
      this.builders.steps?.('fit', 0);
      return true;
    }
    const kind = this.phase;
    const more = this.stepOf();
    if (kind !== 'idle' && kind !== 'waiting') this.builders.steps?.(kind, this.looked);
    return more;
  }

  private stepOf(): boolean {
    switch (this.phase) {
      case 'listing':
        return this.list();
      case 'ask':
        return this.ask();
      case 'stamping':
        return this.stamp();
      case 'finding':
        return this.find();
      case 'wanting':
        return this.want();
      case 'uncovering':
        return this.uncover();
      case 'covering':
        return this.coverNext();
      default:
        return false;
    }
  }

  /** The lit schools marked lit this turn, for the finding. */
  private stamp(): boolean {
    const { litTurn, litList, turn } = this;
    const end = Math.min(litList.length, this.at + COVER_LOOK_EVERY * 16);
    for (let i = this.at; i < end; i++) {
      const school = litList[i] ?? -1;
      if (school >= 0 && school < litTurn.length) litTurn[school] = turn;
    }
    this.looked = end - this.at;
    this.at = end;
    if (end < litList.length) return true;
    this.phase = 'finding';
    this.at = 0;
    this.target = this.found;
    this.targetCount = 0;
    return true;
  }

  /** The schools at the lit ones' places from the index, each once, those lit left out. */
  private find(): boolean {
    const index = this.index;
    if (index === null) {
      this.phase = 'waiting';
      return false;
    }
    const { start, near } = index;
    const { wanted, turn, litTurn, litList, target } = this;
    // The found list is as long as the directory, and each school is in it once at most.
    const count = Math.min(wanted.length, target.length);
    const end = Math.min(litList.length, this.at + COVER_LOOK_EVERY * 4);
    let looked = end - this.at;
    for (let i = this.at; i < end; i++) {
      const school = litList[i] ?? -1;
      const to = start[school + 1] ?? 0;
      const from = start[school] ?? 0;
      looked += Math.max(0, to - from);
      for (let k = from; k < to; k++) {
        const other = near[k] ?? -1;
        if (other < 0 || other >= count || wanted[other] === turn || litTurn[other] === turn) {
          continue;
        }
        wanted[other] = turn;
        target[this.targetCount++] = other;
      }
    }
    this.looked = looked;
    this.at = end;
    if (end < litList.length) return true;
    this.phase = 'uncovering';
    this.at = this.onCount;
    return true;
  }

  /** The schools the worker found, each wanted this turn. */
  private want(): boolean {
    const { wanted, turn, target } = this;
    const end = Math.min(this.targetCount, this.at + COVER_LOOK_EVERY * 16);
    for (let i = this.at; i < end; i++) {
      const school = target[i] ?? -1;
      if (school >= 0 && school < wanted.length) wanted[school] = turn;
    }
    this.looked = end - this.at;
    this.at = end;
    if (end < this.targetCount) return true;
    this.phase = 'uncovering';
    this.at = this.onCount;
    return true;
  }

  /**
   * The schools covered and not wanted this turn uncovered, from the end of the list back:
   * each taken out by the list's last, which is looked at already, so the list holds exactly
   * the schools covered whenever the work stops.
   */
  private uncover(): boolean {
    if (!this.marks.ready()) return false;
    const { wanted, turn, on, onList } = this;
    const stop = Math.max(0, this.at - COVER_LOOK_EVERY * 16);
    const from = this.at;
    for (let n = 0; n < COVER_LOOK_EVERY && this.at > stop;) {
      const i = --this.at;
      const school = onList[i] ?? 0;
      if (wanted[school] === turn) continue;
      this.marks.cover(school, false);
      n++;
      on[school] = 0;
      onList[i] = onList[--this.onCount] ?? 0;
    }
    this.looked = from - this.at;
    if (this.at > 0) return true;
    this.phase = 'covering';
    this.at = 0;
    return true;
  }

  /** The schools wanted and not covered covered. */
  private coverNext(): boolean {
    if (!this.marks.ready()) return false;
    const { on, onList, target, wanted, turn } = this;
    const stop = Math.min(this.targetCount, this.at + COVER_LOOK_EVERY * 16);
    const from = this.at;
    let n = 0;
    while (this.at < stop && n < COVER_LOOK_EVERY) {
      const school = target[this.at++] ?? -1;
      // The covered list is as long as the directory, and each school is in it once at most.
      if (school < 0 || school >= onList.length || school >= on.length) continue;
      if (on[school] === 1 || wanted[school] !== turn) continue;
      this.marks.cover(school, true);
      n++;
      on[school] = 1;
      onList[this.onCount++] = school;
    }
    this.looked = this.at - from;
    if (this.at < this.targetCount) return true;
    this.phase = 'idle';
    return false;
  }
}
