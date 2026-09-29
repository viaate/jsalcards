// @vitest-environment node
/**
 * A street tile in a worker: cut to the US by the mask, which comes whole
 * (mask/pmtiles.ts wholeFileReader). Until the mask is in, the tile is asked
 * of OpenFreeMap alongside it, so the first street tiles come no later for
 * waiting on the mask; once it is in, a tile outside the US is never asked for.
 */
import type { GetResourceResponse, RequestParameters } from 'maplibre-gl';
import { describe, expect, it } from 'vitest';

import type { ArchiveReader } from '../mask/pmtiles';
import { streetTileLoader } from '../street-tiles';

const TILE = new Uint8Array([0x1a, 0x00]).buffer;

/** A mask whose tiles are all inside the US, or all outside, and that comes when `ready` is called. */
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
  return {
    reader,
    ready: () => {
      ready();
    },
  };
}

/** A tile loader that notes each tile asked for, and whether it was then given up. */
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

describe('a street tile', () => {
  it('is asked for alongside the mask until the mask is in', async () => {
    const { reader, ready } = mask('inside');
    const { asked, load } = loader();
    const serve = streetTileLoader('https://site.test/mask.pmtiles', load, reader);
    const tile = serve(request(7, 30, 48), new AbortController());
    await Promise.resolve();
    expect(asked.map((one) => one.url)).toEqual(['openfreemap://planet/7/30/48']);
    ready();
    expect((await tile).data).toBe(TILE);
  });

  it('outside the US is given up once the mask says so, and never asked for after', async () => {
    const { reader, ready } = mask('outside');
    const { asked, load } = loader();
    const serve = streetTileLoader('https://site.test/mask.pmtiles', load, reader);
    const first = serve(request(7, 20, 40), new AbortController());
    ready();
    expect(((await first).data as ArrayBuffer).byteLength).toBe(0);
    expect(asked).toHaveLength(1);
    expect(asked[0]?.signal.aborted).toBe(true);
    // The mask is in now: a tile outside is answered without OpenFreeMap.
    const inside = await serve(request(7, 21, 40), new AbortController());
    expect((inside.data as ArrayBuffer).byteLength).toBe(0);
    expect(asked).toHaveLength(1);
  });

  it('that MapLibre gives up on is given up on OpenFreeMap too', async () => {
    const { reader, ready } = mask('inside');
    const { asked, load } = loader();
    const serve = streetTileLoader('https://site.test/mask.pmtiles', load, reader);
    const controller = new AbortController();
    const tile = serve(request(7, 30, 48), controller);
    await Promise.resolve();
    controller.abort();
    expect(asked[0]?.signal.aborted).toBe(true);
    ready();
    await tile;
  });
});
