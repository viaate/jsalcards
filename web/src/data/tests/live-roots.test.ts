import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { KEPT_HEADER } from '../../pwa/config';
import { fetchFile } from '../files';
import type { Fetch } from '../files';
import {
  LIVE_ROOT_KEY,
  LIVE_ROOT_OFF_KEY,
  LIVE_ROOT_RETRY_MS,
  LIVE_ROOT_SECOND_EVERY_MS,
  LIVE_ROOT_WAIT_MS,
  answered,
  liveFetch,
  rootedFetch,
} from '../live-roots';
import type { RootStore } from '../live-roots';

const FIRST = 'https://live.snow.test/v1/';
const SECOND = 'https://status.snow.test/live/v1/';
const PATH = 'live/closings.json';
/** SYNTHETIC: a made-up closings file. */
const FILE = '{"schema_version":1,"generated_at":"2026-01-12T12:42:00Z","days":[]}';

type Step = 'file' | 'kept' | 'closed' | 'hang' | 'page' | 403 | 404 | 410 | 429 | 500 | 502 | 503;

/** A made-up network: each root answers its steps in turn (the last one again after that). */
function network(plan: Record<string, Step[]>) {
  const asked: string[] = [];
  const aborted: string[] = [];
  const fetch: Fetch = (input, init) => {
    asked.push(input);
    const root = input.startsWith(SECOND) ? SECOND : input.startsWith(FIRST) ? FIRST : 'other';
    const steps = plan[root] ?? ['file'];
    const step = steps.length > 1 ? (steps.shift() ?? 'file') : (steps[0] ?? 'file');
    const signal = init?.signal;
    return new Promise<Response>((resolve, reject) => {
      const abort = (): void => {
        aborted.push(input);
        reject(new DOMException('The operation was aborted.', 'AbortError'));
      };
      if (signal?.aborted === true) {
        abort();
        return;
      }
      signal?.addEventListener('abort', abort, { once: true });
      const json = { 'content-type': 'application/json; charset=utf-8' };
      switch (step) {
        case 'file':
          resolve(new Response(FILE, { headers: json }));
          return;
        case 'kept':
          resolve(new Response(FILE, { headers: { ...json, [KEPT_HEADER]: '1' } }));
          return;
        case 'closed':
          reject(new TypeError('Failed to fetch'));
          return;
        case 'page':
          resolve(
            new Response('<html>Blocked</html>', { headers: { 'content-type': 'text/html' } }),
          );
          return;
        case 'hang':
          return;
        default:
          resolve(new Response('', { status: step }));
      }
    });
  };
  return { fetch, asked, aborted };
}

function memoryStore(): RootStore & { items: Map<string, string> } {
  const items = new Map<string, string>();
  return {
    items,
    getItem: (key) => items.get(key) ?? null,
    setItem: (key, value) => {
      items.set(key, value);
    },
    removeItem: (key) => {
      items.delete(key);
    },
  };
}

beforeEach(() => {
  vi.useFakeTimers({ now: new Date('2026-01-12T12:53:00Z') });
});
afterEach(() => {
  vi.useRealTimers();
});

function setup(plan: Record<string, Step[]>, store: RootStore | null = memoryStore()) {
  const net = network(plan);
  const read = rootedFetch({
    primary: FIRST,
    fallback: SECOND,
    fetch: net.fetch,
    store,
    now: () => Date.now(),
  });
  return { ...net, read, store };
}

const rootsOf = (urls: readonly string[]): string[] =>
  urls.map((url) => (url.startsWith(SECOND) ? 'second' : url.startsWith(FIRST) ? 'first' : url));

describe('rootedFetch', () => {
  it('reads the first root alone while it answers, and never asks the second', async () => {
    const { read, asked, store } = setup({ [FIRST]: ['file'] });
    for (let i = 0; i < 3; i += 1) {
      const response = await read(`${FIRST}${PATH}`, { cache: 'no-cache' });
      expect(await response.text()).toBe(FILE);
    }
    expect(asked).toEqual([`${FIRST}${PATH}`, `${FIRST}${PATH}`, `${FIRST}${PATH}`]);
    expect((store as ReturnType<typeof memoryStore>).items.size).toBe(0);
  });

  it('asks the second when the first closes the connection, and keeps it for the visit', async () => {
    const { read, asked, store } = setup({ [FIRST]: ['closed'], [SECOND]: ['file'] });
    const response = await read(`${FIRST}${PATH}`);
    expect(await response.text()).toBe(FILE);
    expect(asked).toEqual([`${FIRST}${PATH}`, `${SECOND}${PATH}`]);
    expect((store as ReturnType<typeof memoryStore>).items.get(LIVE_ROOT_KEY)).toBe(
      String(Date.now()),
    );
    // Read second first from then on: the first is not asked.
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_SECOND_EVERY_MS);
    await read(`${FIRST}${PATH}`);
    await read(`${FIRST}predictions/latest.json`);
    expect(rootsOf(asked.slice(2))).toEqual(['second', 'second']);
    expect(asked.at(-1)).toBe(`${SECOND}predictions/latest.json`);
  });

  for (const step of ['kept', 'page'] as const) {
    it(`asks the second when the first gives ${step} in place of the file`, async () => {
      const { read, asked } = setup({ [FIRST]: [step], [SECOND]: ['file'] });
      const response = await read(`${FIRST}${PATH}`);
      expect(answered(response)).toBe(true);
      expect(await response.text()).toBe(FILE);
      expect(rootsOf(asked)).toEqual(['first', 'second']);
    });
  }

  for (const status of [403, 404, 500, 502, 503] as const) {
    it(`gives the first root own ${String(status)} as it came, and never asks the second`, async () => {
      const { read, asked, store } = setup({ [FIRST]: [status], [SECOND]: ['file'] });
      for (let i = 0; i < 3; i += 1) {
        const response = await read(`${FIRST}${PATH}`);
        expect(response.status).toBe(status);
      }
      await vi.advanceTimersByTimeAsync(LIVE_ROOT_WAIT_MS * 3);
      expect(rootsOf(asked)).toEqual(['first', 'first', 'first']);
      expect((store as ReturnType<typeof memoryStore>).items.size).toBe(0);
    });
  }

  it('asks the second when the first has not answered within the wait, and takes whichever answers', async () => {
    expect(LIVE_ROOT_WAIT_MS).toBe(4000);
    const { read, asked, aborted } = setup({ [FIRST]: ['hang'], [SECOND]: ['file'] });
    const reading = read(`${FIRST}${PATH}`);
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_WAIT_MS - 1);
    expect(rootsOf(asked)).toEqual(['first']);
    await vi.advanceTimersByTimeAsync(1);
    const response = await reading;
    expect(await response.text()).toBe(FILE);
    expect(rootsOf(asked)).toEqual(['first', 'second']);
    // The first's read is given up once the second answered.
    expect(rootsOf(aborted)).toEqual(['first']);
  });

  it('takes the first when it answers late, before the second, and keeps it first', async () => {
    const second = network({ [SECOND]: ['hang'] });
    const asked: string[] = [];
    let late: (() => void) | undefined;
    const store = memoryStore();
    const slow: Fetch = (input, init) => {
      asked.push(input);
      if (!input.startsWith(FIRST)) return second.fetch(input, init);
      return new Promise((resolve) => {
        late = () => {
          resolve(new Response(FILE));
        };
      });
    };
    const read = rootedFetch({ primary: FIRST, fallback: SECOND, fetch: slow, store });
    const reading = read(`${FIRST}${PATH}`);
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_WAIT_MS);
    expect(rootsOf(asked)).toEqual(['first', 'second']);
    late?.();
    expect(await (await reading).text()).toBe(FILE);
    // The second's read, still on its way, is given up; the first stays first.
    expect(rootsOf(second.aborted)).toEqual(['second']);
    expect(store.items.has(LIVE_ROOT_KEY)).toBe(false);
  });

  it('gives what the first gave when neither answers, as with one root', async () => {
    // The worker's kept copy from the first, though the second fails too.
    const kept = setup({ [FIRST]: ['kept'], [SECOND]: ['closed'] });
    const response = await kept.read(`${FIRST}${PATH}`);
    expect(response.headers.get(KEPT_HEADER)).toBe('1');
    expect(await response.text()).toBe(FILE);
    // The second is left alone for a while; nothing took over.
    expect([...(kept.store as ReturnType<typeof memoryStore>).items.keys()]).toEqual([
      LIVE_ROOT_OFF_KEY,
    ]);
    // The first's failure, as the read failed with one root.
    const closed = setup({ [FIRST]: ['closed'], [SECOND]: [502] });
    await expect(closed.read(`${FIRST}${PATH}`)).rejects.toThrow('Failed to fetch');
    // The second's kept copy, when the first has nothing at all to give.
    const secondKept = setup({ [FIRST]: ['closed'], [SECOND]: ['kept'] });
    const copy = await secondKept.read(`${FIRST}${PATH}`);
    expect(copy.headers.get(KEPT_HEADER)).toBe('1');
  });

  it('gives what the first root gave when neither answers, though the second was read first', async () => {
    const store = memoryStore();
    store.setItem(LIVE_ROOT_KEY, String(Date.now() - 60_000));
    const kept = setup({ [FIRST]: ['kept'], [SECOND]: [502] }, store);
    const response = await kept.read(`${FIRST}${PATH}`);
    expect(rootsOf(kept.asked)).toEqual(['second', 'first']);
    expect(response.headers.get(KEPT_HEADER)).toBe('1');
    store.removeItem(LIVE_ROOT_OFF_KEY);
    store.setItem(LIVE_ROOT_KEY, String(Date.now() - 60_000));
    const closed = setup({ [FIRST]: ['closed'], [SECOND]: [502] }, store);
    await expect(closed.read(`${FIRST}${PATH}`)).rejects.toThrow('Failed to fetch');
  });

  it('gives the worker kept copy within the wait when the second never answers', async () => {
    const { read, asked, aborted, store } = setup({ [FIRST]: ['kept'], [SECOND]: ['hang'] });
    let response: Response | undefined;
    void read(`${FIRST}${PATH}`).then((answer) => {
      response = answer;
    });
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_WAIT_MS - 1);
    expect(response).toBeUndefined();
    await vi.advanceTimersByTimeAsync(1);
    expect(response?.headers.get(KEPT_HEADER)).toBe('1');
    expect(await response?.text()).toBe(FILE);
    expect(rootsOf(asked)).toEqual(['first', 'second']);
    // The second's read is given up, and the second is left alone for a while.
    expect(rootsOf(aborted)).toEqual(['second']);
    const items = (store as ReturnType<typeof memoryStore>).items;
    expect(items.get(LIVE_ROOT_OFF_KEY)).toBe(String(Date.now()));
    expect(items.has(LIVE_ROOT_KEY)).toBe(false);
  });

  it('gives the kept copy the worker hands over at its own wait when the live host is silent and the second never answers', async () => {
    const asked: string[] = [];
    const slow: Fetch = (input) => {
      asked.push(input);
      if (input.startsWith(SECOND)) return new Promise<Response>(() => undefined);
      return new Promise<Response>((resolve) => {
        setTimeout(() => {
          resolve(new Response(FILE, { headers: { [KEPT_HEADER]: '1' } }));
        }, LIVE_ROOT_WAIT_MS);
      });
    };
    const read = rootedFetch({ primary: FIRST, fallback: SECOND, fetch: slow, store: null });
    let response: Response | undefined;
    void read(`${FIRST}${PATH}`).then((answer) => {
      response = answer;
    });
    await vi.advanceTimersByTimeAsync(2 * LIVE_ROOT_WAIT_MS);
    expect(rootsOf(asked)).toEqual(['first', 'second']);
    expect(response?.headers.get(KEPT_HEADER)).toBe('1');
  });

  it('waits for the first as long as it takes, as with one root, once the second has failed', async () => {
    let late: (() => void) | undefined;
    const second = network({ [SECOND]: [502] });
    const slow: Fetch = (input, init) => {
      if (!input.startsWith(FIRST)) return second.fetch(input, init);
      return new Promise<Response>((resolve) => {
        late = () => {
          resolve(new Response(FILE));
        };
      });
    };
    const read = rootedFetch({ primary: FIRST, fallback: SECOND, fetch: slow, store: null });
    let response: Response | undefined;
    void read(`${FIRST}${PATH}`).then((answer) => {
      response = answer;
    });
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_WAIT_MS * 4);
    expect(response).toBeUndefined();
    late?.();
    await vi.advanceTimersByTimeAsync(0);
    expect(await response?.text()).toBe(FILE);
  });

  it('gives the first root kept copy at once when the caller gives up while the second is asked', async () => {
    const { read, store } = setup({ [FIRST]: ['kept'], [SECOND]: ['hang'] });
    const controller = new AbortController();
    const reading = read(`${FIRST}${PATH}`, { signal: controller.signal });
    await vi.advanceTimersByTimeAsync(1);
    controller.abort();
    const response = await reading;
    expect(response.headers.get(KEPT_HEADER)).toBe('1');
    expect(await response.text()).toBe(FILE);
    // Not a failure of the second: it is asked again next time.
    expect((store as ReturnType<typeof memoryStore>).items.size).toBe(0);
  });

  it('leaves the second alone for 10 minutes once both failed, reading as with one root', async () => {
    const { read, asked, store } = setup({ [FIRST]: ['closed'], [SECOND]: [502, 'hang', 'file'] });
    const items = (store as ReturnType<typeof memoryStore>).items;
    await expect(read(`${FIRST}${PATH}`)).rejects.toThrow('Failed to fetch');
    expect(rootsOf(asked)).toEqual(['first', 'second']);
    const off = Date.now();
    expect(items.get(LIVE_ROOT_OFF_KEY)).toBe(String(off));
    // Nine minutes, a read a minute: the first alone, its failure as it came.
    for (let minute = 1; minute < 10; minute += 1) {
      await vi.advanceTimersByTimeAsync(60_000);
      await expect(read(`${FIRST}${PATH}`)).rejects.toThrow('Failed to fetch');
    }
    expect(rootsOf(asked)).toEqual(['first', 'second', ...Array<string>(9).fill('first')]);
    expect(items.get(LIVE_ROOT_OFF_KEY)).toBe(String(off));
    // Ten minutes on: the second again; it hangs, so the wait runs out and it is left alone again.
    await vi.advanceTimersByTimeAsync(60_000);
    const reading = expect(read(`${FIRST}${PATH}`)).rejects.toThrow('Failed to fetch');
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_WAIT_MS);
    await reading;
    expect(rootsOf(asked).slice(-2)).toEqual(['first', 'second']);
    expect(items.get(LIVE_ROOT_OFF_KEY)).toBe(String(Date.now()));
    // Ten more minutes: the second answers, takes over, and the pause is over.
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_RETRY_MS);
    expect(await (await read(`${FIRST}${PATH}`)).text()).toBe(FILE);
    expect(items.has(LIVE_ROOT_OFF_KEY)).toBe(false);
    expect(items.get(LIVE_ROOT_KEY)).toBe(String(Date.now()));
  });

  it('gives a second root that was answering one more try, then leaves it alone, and remembers that through the storage', async () => {
    const store = memoryStore();
    store.setItem(LIVE_ROOT_KEY, String(Date.now() - 60_000));
    const one = setup({ [FIRST]: ['kept'], [SECOND]: ['closed'] }, store);
    expect((await one.read(`${FIRST}${PATH}`)).headers.get(KEPT_HEADER)).toBe('1');
    expect(rootsOf(one.asked)).toEqual(['second', 'first']);
    // One failure of a root that was answering: no longer read first, but not left alone yet.
    expect([...store.items.keys()]).toEqual([]);
    // Another page of the visit reads the live host first, then the second once more.
    const two = setup({ [FIRST]: ['kept'], [SECOND]: [502] }, store);
    expect((await two.read(`${FIRST}${PATH}`)).headers.get(KEPT_HEADER)).toBe('1');
    expect(rootsOf(two.asked)).toEqual(['first', 'second']);
    // Two in a row: left alone for 10 minutes.
    expect([...store.items.keys()]).toEqual([LIVE_ROOT_OFF_KEY]);
    const three = setup({ [FIRST]: ['kept'], [SECOND]: ['file'] }, store);
    await three.read(`${FIRST}${PATH}`);
    expect(rootsOf(three.asked)).toEqual(['first']);
  });

  it('gives a second root that was answering and then once fails a minute later the live host read, and takes it again', async () => {
    // The blocked network: the live host closes every connection; the second answers, fails once, answers.
    const { read, asked, store } = setup({
      [FIRST]: ['closed'],
      [SECOND]: ['file', 502, 'file'],
    });
    const items = (store as ReturnType<typeof memoryStore>).items;
    expect(answered(await read(`${FIRST}${PATH}`))).toBe(true);
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_SECOND_EVERY_MS);
    await expect(read(`${FIRST}${PATH}`)).rejects.toThrow('Failed to fetch');
    expect(items.has(LIVE_ROOT_OFF_KEY)).toBe(false);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(answered(await read(`${FIRST}${PATH}`))).toBe(true);
    expect(rootsOf(asked)).toEqual(['first', 'second', 'second', 'first', 'first', 'second']);
    expect(items.get(LIVE_ROOT_KEY)).toBe(String(Date.now()));
  });

  it('tries the first again every 10 minutes, and goes back to it once it answers', async () => {
    const { read, asked, store } = setup({
      [FIRST]: ['closed', 'closed', 'file'],
      [SECOND]: ['file'],
    });
    const items = (store as ReturnType<typeof memoryStore>).items;
    await read(`${FIRST}${PATH}`);
    const took = Date.now();
    expect(items.get(LIVE_ROOT_KEY)).toBe(String(took));
    // Nine minutes on: the second alone.
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_RETRY_MS - 60_000);
    await read(`${FIRST}${PATH}`);
    expect(rootsOf(asked)).toEqual(['first', 'second', 'second']);
    expect(items.get(LIVE_ROOT_KEY)).toBe(String(took));
    // Ten minutes on: the first first; it still fails, so the second again, for 10 more minutes.
    await vi.advanceTimersByTimeAsync(60_000);
    await read(`${FIRST}${PATH}`);
    expect(rootsOf(asked)).toEqual(['first', 'second', 'second', 'first', 'second']);
    expect(items.get(LIVE_ROOT_KEY)).toBe(String(Date.now()));
    await read(`${FIRST}${PATH}`);
    expect(rootsOf(asked).at(-1)).toBe('second');
    // Ten minutes more: the first answers, and is read alone from then on.
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_RETRY_MS);
    await read(`${FIRST}${PATH}`);
    await read(`${FIRST}${PATH}`);
    expect(rootsOf(asked).slice(-2)).toEqual(['first', 'first']);
    expect(items.has(LIVE_ROOT_KEY)).toBe(false);
  });

  it('goes back to the first at once when the second stops answering', async () => {
    const { read, asked, store } = setup({ [FIRST]: ['closed', 'file'], [SECOND]: ['file', 502] });
    await read(`${FIRST}${PATH}`);
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_SECOND_EVERY_MS);
    const response = await read(`${FIRST}${PATH}`);
    expect(answered(response)).toBe(true);
    expect(rootsOf(asked)).toEqual(['first', 'second', 'second', 'first']);
    expect((store as ReturnType<typeof memoryStore>).items.has(LIVE_ROOT_KEY)).toBe(false);
  });

  it('remembers across pages of the visit through its storage, and reads a bad or future entry as none', async () => {
    const store = memoryStore();
    store.setItem(LIVE_ROOT_KEY, String(Date.now() - 60_000));
    const one = setup({ [SECOND]: ['file'] }, store);
    await one.read(`${FIRST}${PATH}`);
    expect(rootsOf(one.asked)).toEqual(['second']);
    for (const value of [
      'nonsense',
      String(Date.now() + 60_000),
      String(Date.now() - LIVE_ROOT_RETRY_MS),
    ]) {
      store.setItem(LIVE_ROOT_KEY, value);
      const fresh = setup({ [FIRST]: ['file'] }, store);
      await fresh.read(`${FIRST}${PATH}`);
      expect([value, rootsOf(fresh.asked)]).toEqual([value, ['first']]);
    }
  });

  it('keeps the choice for the page when storage cannot be had or throws', async () => {
    const broken: RootStore = {
      getItem: () => {
        throw new Error('denied');
      },
      setItem: () => {
        throw new Error('denied');
      },
      removeItem: () => {
        throw new Error('denied');
      },
    };
    for (const store of [null, broken]) {
      const { read, asked } = setup({ [FIRST]: ['closed'], [SECOND]: ['file'] }, store);
      await read(`${FIRST}${PATH}`);
      await vi.advanceTimersByTimeAsync(LIVE_ROOT_SECOND_EVERY_MS);
      await read(`${FIRST}${PATH}`);
      expect(rootsOf(asked)).toEqual(['first', 'second', 'second']);
    }
  });

  it('passes the request on as asked, and leaves URLs outside the first root alone', async () => {
    const seen: { url: string; cache: RequestCache | undefined }[] = [];
    const fetch: Fetch = (input, init) => {
      seen.push({ url: input, cache: init?.cache });
      return Promise.resolve(new Response(FILE));
    };
    const read = rootedFetch({ primary: FIRST, fallback: SECOND, fetch, store: null });
    await read(`${FIRST}${PATH}`, { cache: 'no-cache' });
    await read('https://snow.test/data/schools/meta.json', { cache: 'default' });
    await read(`${SECOND}${PATH}`);
    expect(seen).toEqual([
      { url: `${FIRST}${PATH}`, cache: 'no-cache' },
      { url: 'https://snow.test/data/schools/meta.json', cache: 'default' },
      { url: `${SECOND}${PATH}`, cache: undefined },
    ]);
  });

  it('gives the kept copy within the wait when the remembered second root stops answering, and leaves it alone', async () => {
    const store = memoryStore();
    store.setItem(LIVE_ROOT_KEY, String(Date.now() - 60_000));
    const { read, asked, aborted } = setup({ [FIRST]: ['kept'], [SECOND]: ['hang'] }, store);
    let response: Response | undefined;
    void read(`${FIRST}${PATH}`).then((answer) => {
      response = answer;
    });
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_WAIT_MS - 1);
    expect(response).toBeUndefined();
    // The second has had its wait: the live host is asked, and its kept copy given at once.
    await vi.advanceTimersByTimeAsync(1);
    expect(rootsOf(asked)).toEqual(['second', 'first']);
    expect(response?.headers.get(KEPT_HEADER)).toBe('1');
    expect(await response?.text()).toBe(FILE);
    expect(rootsOf(aborted)).toEqual(['second']);
    expect([...store.items.keys()]).toEqual([LIVE_ROOT_OFF_KEY]);
    // The next read, a minute on, is the live host alone.
    await vi.advanceTimersByTimeAsync(60_000);
    await read(`${FIRST}${PATH}`);
    expect(rootsOf(asked)).toEqual(['second', 'first', 'first']);
  });

  it('counts a second root that runs past its wait as failed though the caller gives up later', async () => {
    const { read, store } = setup({ [FIRST]: ['hang'], [SECOND]: ['hang'] });
    const controller = new AbortController();
    const reading = read(`${FIRST}${PATH}`, { signal: controller.signal });
    const failed = expect(reading).rejects.toThrow('aborted');
    await vi.advanceTimersByTimeAsync(2 * LIVE_ROOT_WAIT_MS);
    const items = (store as ReturnType<typeof memoryStore>).items;
    expect(items.get(LIVE_ROOT_OFF_KEY)).toBe(String(Date.now()));
    controller.abort();
    await failed;
    expect(items.has(LIVE_ROOT_OFF_KEY)).toBe(true);
  });

  for (const status of [404, 410] as const) {
    it(`gives the second root own ${String(status)} as it came, and keeps reading it first`, async () => {
      const { read, asked, store } = setup({
        [FIRST]: ['closed'],
        [SECOND]: ['file', status, 'file'],
      });
      const items = (store as ReturnType<typeof memoryStore>).items;
      await read(`${FIRST}${PATH}`);
      const took = items.get(LIVE_ROOT_KEY);
      const missing = await read(`${FIRST}live/season.json`);
      expect(missing.status).toBe(status);
      expect(items.get(LIVE_ROOT_KEY)).toBe(took);
      expect(items.has(LIVE_ROOT_OFF_KEY)).toBe(false);
      await vi.advanceTimersByTimeAsync(LIVE_ROOT_SECOND_EVERY_MS);
      expect(answered(await read(`${FIRST}${PATH}`))).toBe(true);
      expect(rootsOf(asked)).toEqual(['first', 'second', 'second', 'second']);
    });
  }

  for (const status of [403, 429] as const) {
    it(`counts the second root ${String(status)} as the second failing, and gives the live host kept copy`, async () => {
      const store = memoryStore();
      store.setItem(LIVE_ROOT_KEY, String(Date.now() - 60_000));
      const { read, asked } = setup({ [FIRST]: ['kept'], [SECOND]: [status] }, store);
      const response = await read(`${FIRST}${PATH}`);
      expect(rootsOf(asked)).toEqual(['second', 'first']);
      expect(response.status).toBe(200);
      expect(response.headers.get(KEPT_HEADER)).toBe('1');
      expect(store.items.has(LIVE_ROOT_KEY)).toBe(false);
    });
  }

  it('asks the second root for a file it does not have at most every 3 minutes', async () => {
    const { read, asked } = setup({ [FIRST]: ['closed'], [SECOND]: ['file', 404] });
    await read(`${FIRST}${PATH}`);
    expect((await read(`${FIRST}live/season.json`)).status).toBe(404);
    expect((await read(`${FIRST}live/season.json`)).status).toBe(404);
    expect(rootsOf(asked)).toEqual(['first', 'second', 'second']);
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_SECOND_EVERY_MS);
    expect((await read(`${FIRST}live/season.json`)).status).toBe(404);
    expect(rootsOf(asked)).toEqual(['first', 'second', 'second', 'second']);
  });

  it('gives a first-asked second root own 404 at once, before the live host is asked', async () => {
    const { read, asked, store } = setup({ [FIRST]: ['closed'], [SECOND]: [404] });
    const response = await read(`${FIRST}${PATH}`);
    expect(response.status).toBe(404);
    expect(rootsOf(asked)).toEqual(['first', 'second']);
    expect((store as ReturnType<typeof memoryStore>).items.has(LIVE_ROOT_KEY)).toBe(true);
  });

  it('gives the newer of two kept copies when both roots fail', async () => {
    const made = (at: string): string => FILE.replace('2026-01-12T12:42:00Z', at);
    const copies = (first: string, second: string): Fetch => {
      return (input) =>
        Promise.resolve(
          new Response(input.startsWith(SECOND) ? second : first, {
            headers: { 'content-type': 'application/json', [KEPT_HEADER]: '1' },
          }),
        );
    };
    for (const [first, second, given] of [
      [made('2026-01-12T07:00:00Z'), made('2026-01-12T12:40:00Z'), 'second'],
      [made('2026-01-12T12:40:00Z'), made('2026-01-12T07:00:00Z'), 'first'],
      [made('2026-01-12T12:40:00Z'), made('2026-01-12T12:40:00Z'), 'first'],
      [made('2026-01-12T12:40:00Z'), '{"days":[]}', 'first'],
    ] as const) {
      const read = rootedFetch({
        primary: FIRST,
        fallback: SECOND,
        fetch: copies(first, second),
        store: null,
      });
      const text = await (await read(`${FIRST}${PATH}`)).text();
      expect([given, text]).toEqual([given, given === 'second' ? second : first]);
    }
  });

  it('reads a file through the second root at most every 3 minutes, and at once on a new page', async () => {
    expect(LIVE_ROOT_SECOND_EVERY_MS).toBe(180_000);
    const store = memoryStore();
    const { read, asked } = setup({ [FIRST]: ['closed'], [SECOND]: ['file'] }, store);
    await read(`${FIRST}${PATH}`);
    // A poll a minute: the file the second gave, again, until 3 minutes have gone by.
    for (let minute = 1; minute < 3; minute += 1) {
      await vi.advanceTimersByTimeAsync(60_000);
      const again = await read(`${FIRST}${PATH}`, { cache: 'no-cache' });
      expect(answered(again)).toBe(true);
      expect(await again.text()).toBe(FILE);
    }
    expect(rootsOf(asked)).toEqual(['first', 'second']);
    // Another file is read as it comes.
    await read(`${FIRST}predictions/latest.json`);
    expect(rootsOf(asked)).toEqual(['first', 'second', 'second']);
    await vi.advanceTimersByTimeAsync(60_000);
    await read(`${FIRST}${PATH}`);
    expect(rootsOf(asked)).toEqual(['first', 'second', 'second', 'second']);
    // A reload: the new page reads the second at once.
    const reload = setup({ [SECOND]: ['file'] }, store);
    await reload.read(`${FIRST}${PATH}`);
    expect(rootsOf(reload.asked)).toEqual(['second']);
  });

  it('stops both reads when the caller gives up, and asks no root after that', async () => {
    const { read, asked, aborted } = setup({ [FIRST]: ['hang'], [SECOND]: ['hang'] });
    const controller = new AbortController();
    const reading = read(`${FIRST}${PATH}`, { signal: controller.signal });
    const failed = expect(reading).rejects.toThrow('aborted');
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_WAIT_MS);
    expect(rootsOf(asked)).toEqual(['first', 'second']);
    controller.abort();
    await failed;
    expect(rootsOf(aborted).sort()).toEqual(['first', 'second']);
    // Given up before the wait: the second is never asked.
    const early = setup({ [FIRST]: ['hang'], [SECOND]: ['file'] });
    const stop = new AbortController();
    const cut = early.read(`${FIRST}${PATH}`, { signal: stop.signal });
    stop.abort();
    await expect(cut).rejects.toThrow('aborted');
    await vi.advanceTimersByTimeAsync(LIVE_ROOT_WAIT_MS);
    expect(rootsOf(early.asked)).toEqual(['first']);
  });
});

describe('liveFetch', () => {
  it('is fetchFile itself in a build without a second root', () => {
    expect(import.meta.env.VITE_SNOWLIGHT_LIVE_FALLBACK ?? '').toBe('');
    expect(liveFetch).toBe(fetchFile);
  });
});
