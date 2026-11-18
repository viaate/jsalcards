import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { KEPT_HEADER } from '../../pwa/config';
import { fetchFile } from '../files';
import type { Fetch } from '../files';
import {
  LIVE_ROOT_KEY,
  LIVE_ROOT_RETRY_MS,
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

type Step = 'file' | 'kept' | 'closed' | 'hang' | 'page' | 404 | 502;

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
    await read(`${FIRST}${PATH}`);
    await read(`${FIRST}predictions/latest.json`);
    expect(rootsOf(asked.slice(2))).toEqual(['second', 'second']);
    expect(asked.at(-1)).toBe(`${SECOND}predictions/latest.json`);
  });

  for (const step of ['kept', 'page', 404, 502] as const) {
    it(`asks the second when the first gives ${String(step)} in place of the file`, async () => {
      const { read, asked } = setup({ [FIRST]: [step], [SECOND]: ['file'] });
      const response = await read(`${FIRST}${PATH}`);
      expect(answered(response)).toBe(true);
      expect(await response.text()).toBe(FILE);
      expect(rootsOf(asked)).toEqual(['first', 'second']);
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
    expect((kept.store as ReturnType<typeof memoryStore>).items.size).toBe(0);
    // An error from the first, though the second fails too.
    const missing = setup({ [FIRST]: [404], [SECOND]: [502] });
    expect((await missing.read(`${FIRST}${PATH}`)).status).toBe(404);
    // The first's failure, as the read failed with one root.
    const closed = setup({ [FIRST]: ['closed'], [SECOND]: [502] });
    await expect(closed.read(`${FIRST}${PATH}`)).rejects.toThrow('Failed to fetch');
    // The second's kept copy, when the first has nothing at all to give.
    const secondKept = setup({ [FIRST]: ['closed'], [SECOND]: ['kept'] });
    const copy = await secondKept.read(`${FIRST}${PATH}`);
    expect(copy.headers.get(KEPT_HEADER)).toBe('1');
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
