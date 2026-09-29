// @vitest-environment node
/**
 * The US mask, fetched once by the page and sent to its workers: never
 * before someone heads for the streets, once however many workers ask, and
 * asked for again soon after the network comes back.
 */
import { gzipSync } from 'node:zlib';

import { afterEach, describe, expect, it, vi } from 'vitest';

import { NUDGE_GAP_MS, maskFeed, ownMaskSource, pageMaskSource } from '../feed';
import { ArchiveReader, WHOLE_FILE_BACKOFF, writeArchive } from '../pmtiles';

const URL_NOW = 'https://site.test/geo/us-mask.0123456789.pmtiles';
const ALIAS = 'https://site.test/geo/us-mask.pmtiles';
const tile = (text: string): Uint8Array => new TextEncoder().encode(text);
const ARCHIVE = writeArchive([{ z: 7, x: 30, y: 45, bytes: tile('inside') }], {
  metadata: { name: 'test' },
  bounds: [-125, 24, -66, 50],
  center: [-98, 39, 7],
  gzip: (bytes: Uint8Array) => gzipSync(bytes),
});
const unzip = (): Promise<Uint8Array> => Promise.reject(new Error('nothing to unzip'));

interface Asked {
  readonly url: string;
  readonly init: RequestInit;
}

/** A network answering with `answers` in turn, the last repeated; notes each request. */
function network(answers: readonly (() => Response)[] = [() => new Response(ARCHIVE.slice())]) {
  const asked: Asked[] = [];
  const fetch = (url: string, init: RequestInit): Promise<Response> => {
    asked.push({ url, init });
    const answer = answers[Math.min(asked.length - 1, answers.length - 1)];
    return Promise.resolve((answer ?? (() => new Response(null, { status: 500 })))());
  };
  return { asked, fetch };
}

/** Waits for the channels' messages to be delivered, and what they start to settle. */
const deliver = async (): Promise<void> => {
  for (let i = 0; i < 20; i++) await new Promise((resolve) => setTimeout(resolve, 1));
};

let channels = 0;
/** A channel name of the test's own, as each page has. */
const channelName = (): string => `snowlight-mask-test-${String(++channels)}`;

const stops: (() => void)[] = [];
afterEach(() => {
  for (const stop of stops.splice(0)) stop();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('the mask, fed to the workers by the page', () => {
  it('is not asked for until someone heads for the streets', async () => {
    const { asked, fetch } = network();
    const feed = maskFeed(URL_NOW, channelName(), { fetch, gunzip: unzip });
    stops.push(() => {
      feed.destroy();
    });
    await deliver();
    expect(asked).toEqual([]);
    expect(feed.started).toBe(false);
    feed.start('low');
    await feed.loaded;
    expect(asked).toHaveLength(1);
    expect(asked[0]?.init.priority).toBe('low');
    expect(asked[0]?.init.headers).toBeUndefined();
  });

  it('is fetched once, whole, however many workers ask for it, and sent to each', async () => {
    const name = channelName();
    const { asked, fetch } = network();
    const feed = maskFeed(URL_NOW, name, { fetch, gunzip: unzip });
    stops.push(() => {
      feed.destroy();
    });
    const workers = [pageMaskSource(URL_NOW, name), pageMaskSource(URL_NOW, name)];
    const tiles = await Promise.all(
      workers.map((worker) => new ArchiveReader(worker.reader).tile(7, 30, 45)),
    );
    expect(tiles).toEqual([tile('inside'), tile('inside')]);
    expect(asked.map(({ url }) => url)).toEqual([URL_NOW]);
    // A worker that asks once it is in gets it at once.
    const late = pageMaskSource(URL_NOW, name);
    expect(await new ArchiveReader(late.reader).tile(7, 30, 45)).toEqual(tile('inside'));
    expect(asked).toHaveLength(1);
  });

  it("is not asked for by another page's workers", async () => {
    const { asked, fetch } = network();
    const feed = maskFeed(URL_NOW, channelName(), { fetch, gunzip: unzip });
    stops.push(() => {
      feed.destroy();
    });
    const elsewhere = pageMaskSource(URL_NOW, channelName());
    void elsewhere.reader(0, 10);
    await deliver();
    expect(asked).toEqual([]);
  });

  it('is asked for under the name that never changes once its own answers 404', async () => {
    const { asked, fetch } = network([
      () => new Response('not found', { status: 404 }),
      () => new Response(ARCHIVE.slice()),
    ]);
    const feed = maskFeed(URL_NOW, channelName(), {
      fetch,
      gunzip: unzip,
      fallbackUrl: ALIAS,
      sleep: () => Promise.resolve(),
    });
    stops.push(() => {
      feed.destroy();
    });
    feed.start();
    await feed.loaded;
    expect(asked.map(({ url }) => url)).toEqual([URL_NOW, ALIAS]);
  });
});

describe('the mask, asked for again', () => {
  it('waits no more than about ten seconds between tries', () => {
    expect(Math.max(...WHOLE_FILE_BACKOFF) * 1.25).toBeLessThanOrEqual(12_500);
  });

  it('at once when a tile waiting on it asks, but not twice within NUDGE_GAP_MS', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    let failing = true;
    const { asked, fetch } = network([
      () => (failing ? new Response('busy', { status: 503 }) : new Response(ARCHIVE.slice())),
    ]);
    const source = ownMaskSource(URL_NOW, { fetch, gunzip: unzip, random: () => 0.5 });
    const read = new ArchiveReader(source.reader).tile(7, 30, 45);
    // Tries 1 to 5 fail, 0.5 + 1 + 2 + 4 s apart: the next waits 8 s.
    await vi.advanceTimersByTimeAsync(7_500);
    expect(asked).toHaveLength(5);
    failing = false;
    source.nudge();
    // Too soon after the last try: it waits on.
    await vi.advanceTimersByTimeAsync(0);
    expect(asked).toHaveLength(5);
    await vi.advanceTimersByTimeAsync(NUDGE_GAP_MS);
    source.nudge();
    await vi.advanceTimersByTimeAsync(0);
    expect(asked).toHaveLength(6);
    expect(await read).toEqual(tile('inside'));
  });

  it('at once when the network comes back', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    const online = new EventTarget();
    vi.stubGlobal('addEventListener', online.addEventListener.bind(online));
    vi.stubGlobal('removeEventListener', online.removeEventListener.bind(online));
    let failing = true;
    const { asked, fetch } = network([
      () => (failing ? new Response('busy', { status: 503 }) : new Response(ARCHIVE.slice())),
    ]);
    const source = ownMaskSource(URL_NOW, { fetch, gunzip: unzip, random: () => 0.5 });
    const read = new ArchiveReader(source.reader).tile(7, 30, 45);
    await vi.advanceTimersByTimeAsync(7_500);
    expect(asked).toHaveLength(5);
    failing = false;
    online.dispatchEvent(new Event('online'));
    await vi.advanceTimersByTimeAsync(0);
    expect(asked).toHaveLength(6);
    expect(await read).toEqual(tile('inside'));
  });
});
