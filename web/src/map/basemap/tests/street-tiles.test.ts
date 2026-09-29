// @vitest-environment node
/**
 * A street tile in a worker: cut to the US by the mask, which the page sends
 * (mask/feed.ts). A tile wholly inside the US is asked of OpenFreeMap at
 * once; any other only once the mask is in, and none wholly outside the US
 * at all; while a tile waits for the mask, it says so, which wakes a retry of
 * the mask that is waiting.
 */
import type { GetResourceResponse, RequestParameters } from 'maplibre-gl';
import { describe, expect, it } from 'vitest';

import type { MaskSource } from '../mask/feed';
import type { ArchiveReader } from '../mask/pmtiles';
import { streetTileLoader } from '../street-tiles';

const TILE = new Uint8Array([0x1a, 0x00]).buffer;

/** A mask whose tiles are all inside the US, or all outside, that comes when `ready` is called. */
function mask(kind: 'inside' | 'outside') {
  let ready: () => void = () => undefined;
  const loaded = new Promise<void>((resolve) => {
    ready = resolve;
  });
  const reader = {
    start: async () => {
      await loaded;
      return { header: { maxZoom: 7 }, root: [] };
    },
    // An empty mask tile: no part of it outside the US.
    tile: async () => {
      await loaded;
      return kind === 'inside' ? new Uint8Array(0) : null;
    },
  } as unknown as ArchiveReader;
  let nudges = 0;
  const source: MaskSource = {
    reader: () => Promise.reject(new Error('read through the archive')),
    nudge: () => {
      nudges++;
    },
  };
  return {
    reader,
    source,
    nudges: () => nudges,
    ready: () => {
      ready();
    },
  };
}

/** A tile loader that notes each tile asked for. */
function loader() {
  const asked: { url: string; signal: AbortSignal }[] = [];
  const load = (url: string, signal: AbortSignal): Promise<GetResourceResponse<ArrayBuffer>> => {
    asked.push({ url, signal });
    return Promise.resolve({ data: TILE });
  };
  return { asked, load };
}

const request = (z: number, x: number, y: number): RequestParameters => ({
  url: `openfreemap://planet/${String(z)}/${String(x)}/${String(y)}`,
});

/** No tile is known to be wholly inside the US: each waits for the mask. */
const notInside = (): boolean => false;

/** Lets every settled promise's callbacks run. */
const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

describe('a street tile', () => {
  it('is asked for only once the mask is in', async () => {
    const { reader, source, ready } = mask('inside');
    const { asked, load } = loader();
    const serve = streetTileLoader(source, load, reader, notInside);
    const tile = serve(request(7, 30, 48), new AbortController());
    await flush();
    expect(asked).toEqual([]);
    ready();
    expect((await tile).data).toBe(TILE);
    expect(asked.map((one) => one.url)).toEqual(['openfreemap://planet/7/30/48']);
  });

  it('wholly inside the US is asked for at once, without waiting for the mask', async () => {
    const { reader, source, nudges } = mask('inside');
    const { asked, load } = loader();
    const serve = streetTileLoader(
      source,
      load,
      reader,
      (z, x, y) => z === 7 && x === 30 && y === 48,
    );
    expect((await serve(request(7, 30, 48), new AbortController())).data).toBe(TILE);
    expect(asked.map((one) => one.url)).toEqual(['openfreemap://planet/7/30/48']);
    expect(nudges()).toBe(0);
  });

  it('outside the US is never asked for', async () => {
    const { reader, source, ready } = mask('outside');
    const { asked, load } = loader();
    const serve = streetTileLoader(source, load, reader, notInside);
    const first = serve(request(7, 20, 40), new AbortController());
    ready();
    expect(((await first).data as ArrayBuffer).byteLength).toBe(0);
    const second = await serve(request(7, 21, 40), new AbortController());
    expect((second.data as ArrayBuffer).byteLength).toBe(0);
    expect(asked).toEqual([]);
  });

  it('that MapLibre gives up on while it waits for the mask is never asked for', async () => {
    const { reader, source, ready } = mask('inside');
    const { asked, load } = loader();
    const serve = streetTileLoader(source, load, reader, notInside);
    const controller = new AbortController();
    const tile = serve(request(7, 30, 48), controller);
    controller.abort();
    ready();
    await expect(tile).rejects.toThrow();
    expect(asked).toEqual([]);
  });

  it('says it waits for the mask, each one asked for: that wakes a retry of the mask', async () => {
    const { reader, source, nudges, ready } = mask('inside');
    const { load } = loader();
    const serve = streetTileLoader(source, load, reader, notInside);
    const tiles = [
      serve(request(7, 30, 48), new AbortController()),
      serve(request(7, 31, 48), new AbortController()),
    ];
    expect(nudges()).toBe(2);
    ready();
    await Promise.all(tiles);
  });
});
