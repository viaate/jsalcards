/**
 * A small IndexedDB in memory for the alert note tests, as far as alert-store.ts and push.ts use
 * it. Like a browser, it runs transactions one after another in the order they were made, the
 * requests of one transaction in order, and a transaction commits once no request is left.
 *
 * `broken`: every open fails; `throws`: every open throws at once; `hung`: every open never
 * answers; `wait`: each request takes that many ms; `puts`: the ms each put in turn takes.
 */

interface Request {
  result: unknown;
  error: Error | null;
  onsuccess: (() => void) | null;
  onerror: (() => void) | null;
  onupgradeneeded?: (() => void) | null;
  onblocked?: (() => void) | null;
}

export function fakeIdb({
  broken = false,
  throws = false,
  hung = false,
  wait = 0,
  puts = [] as number[],
} = {}) {
  /** The notes, as JSON, by key. */
  const notes = new Map<string, string>();
  /** What happened, in order: `put <at>`, `delete <key>`, `drop`. */
  const log: string[] = [];
  let made = false;
  let tail: Promise<void> = Promise.resolve();
  let putCount = 0;
  const connections = new Set<{ onversionchange: (() => void) | null; closed: boolean }>();
  const later = (ms: number): Promise<void> => new Promise((done) => setTimeout(done, ms));

  function connection() {
    const db = {
      onversionchange: null as (() => void) | null,
      onclose: null as (() => void) | null,
      closed: false,
      objectStoreNames: { contains: () => made },
      createObjectStore: () => {
        made = true;
      },
      close: () => {
        db.closed = true;
        connections.delete(db);
      },
      transaction: (_name: string, mode: 'readonly' | 'readwrite') => {
        if (db.closed) throw new Error('The connection is closed.');
        const ready = tail;
        let finish = (): void => undefined;
        tail = new Promise((done) => (finish = done));
        let steps: Promise<void> = ready;
        let pending = 0;
        let over = false;
        const transaction = {
          oncomplete: null as (() => void) | null,
          onerror: null as (() => void) | null,
          onabort: null as (() => void) | null,
          error: null,
          objectStore: () => store,
        };
        const ask = (work: () => unknown, ms = wait): Request => {
          const asked: Request = { result: undefined, error: null, onsuccess: null, onerror: null };
          pending += 1;
          steps = steps.then(async () => {
            await later(ms);
            asked.result = work();
            pending -= 1;
            asked.onsuccess?.();
            if (pending === 0 && !over) {
              over = true;
              transaction.oncomplete?.();
              finish();
            }
          });
          return asked;
        };
        const writable = (): void => {
          if (mode !== 'readwrite') throw new Error('A readonly transaction.');
        };
        const store = {
          get: (key: string) =>
            ask(() => {
              const note = notes.get(key);
              return note === undefined ? undefined : (JSON.parse(note) as unknown);
            }),
          getAll: () => ask(() => [...notes.values()].map((note) => JSON.parse(note) as unknown)),
          getAllKeys: () => ask(() => [...notes.keys()]),
          put: (value: unknown, key: string) => {
            writable();
            const ms = puts[putCount] ?? wait;
            putCount += 1;
            return ask(() => {
              notes.set(key, JSON.stringify(value));
              log.push(`put ${String((value as { at?: unknown }).at)}`);
              return key;
            }, ms);
          },
          delete: (key: string) => {
            writable();
            return ask(() => {
              if (notes.delete(key)) log.push(`delete ${key}`);
            });
          },
        };
        return transaction;
      },
    };
    return db;
  }

  const factory = {
    open: () => {
      if (throws) throw new Error('No storage.');
      const asked: Request = {
        result: undefined,
        error: null,
        onsuccess: null,
        onerror: null,
        onupgradeneeded: null,
      };
      void later(wait).then(() => {
        if (hung) return;
        if (broken) {
          asked.error = new Error('No storage.');
          asked.onerror?.();
          return;
        }
        const db = connection();
        connections.add(db);
        asked.result = db;
        if (!made) asked.onupgradeneeded?.();
        asked.onsuccess?.();
      });
      return asked;
    },
    deleteDatabase: () => {
      if (throws) throw new Error('No storage.');
      const asked: Request = {
        result: undefined,
        error: null,
        onsuccess: null,
        onerror: null,
        onblocked: null,
      };
      // Open connections hear of it and close; the drop waits for what is under way.
      for (const db of [...connections]) db.onversionchange?.();
      const ready = tail;
      tail = ready.then(async () => {
        await later(wait);
        if (hung) return new Promise<void>(() => undefined);
        if (broken) {
          asked.error = new Error('No storage.');
          asked.onerror?.();
          return;
        }
        notes.clear();
        made = false;
        log.push('drop');
        asked.onsuccess?.();
      });
      return asked;
    },
  };
  /** The `at` of each note kept. */
  const kept = (): number[] =>
    [...notes.values()].map((note) => (JSON.parse(note) as { at: number }).at);
  return { db: factory as unknown as IDBFactory, notes, log, kept };
}
