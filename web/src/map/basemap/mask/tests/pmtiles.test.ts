// @vitest-environment node
/**
 * The PMTiles writer and reader, checked against the reference
 * implementation (the pmtiles package): tile ids, a small archive, and one
 * large enough to need leaf directories.
 */
import { gunzipSync, gzipSync } from 'node:zlib';

import { PMTiles, zxyToTileId as referenceTileId } from 'pmtiles';
import type { RangeResponse, Source } from 'pmtiles';
import { describe, expect, it, vi } from 'vitest';

import {
  ArchiveReader,
  RANGE_TRIES,
  READ_STALL_MS,
  ROOT_BYTES,
  WHOLE_FILE_BACKOFF,
  checkWholeArchive,
  decodeHeader,
  httpRangeReader,
  wholeFileReader,
  writeArchive,
  zxyToTileId,
} from '../pmtiles';
import type { ArchiveTile } from '../pmtiles';

const OPTIONS = {
  metadata: { name: 'test' },
  bounds: [-125, 24, -66, 50] as const,
  center: [-98, 39, 7] as const,
  gzip: (bytes: Uint8Array) => gzipSync(bytes),
};

function source(bytes: Uint8Array): Source {
  return {
    getKey: () => 'memory',
    getBytes: (offset: number, length: number): Promise<RangeResponse> =>
      Promise.resolve({ data: bytes.slice(offset, offset + length).buffer }),
  };
}

function reader(bytes: Uint8Array): ArchiveReader {
  return new ArchiveReader(
    (offset, length) => Promise.resolve(bytes.subarray(offset, offset + length)),
    (data) => Promise.resolve(gunzipSync(data)),
  );
}

describe('tile ids', () => {
  it('match the reference implementation', () => {
    for (let z = 0; z <= 14; z++) {
      const n = 2 ** z;
      for (const [x, y] of [
        [0, 0],
        [n - 1, 0],
        [0, n - 1],
        [n - 1, n - 1],
        [Math.floor(n / 3), Math.floor((2 * n) / 3)],
        [Math.floor(n * 0.27), Math.floor(n * 0.37)],
      ] as const) {
        expect(zxyToTileId(z, x, y), `${String(z)}/${String(x)}/${String(y)}`).toBe(
          referenceTileId(z, x, y),
        );
      }
    }
  });
});

describe('archives', () => {
  const tile = (text: string): Uint8Array => new TextEncoder().encode(text);

  it('are read back by the reference reader and by ours', async () => {
    const tiles: ArchiveTile[] = [
      { z: 7, x: 30, y: 45, bytes: tile('a') },
      { z: 7, x: 31, y: 45, bytes: tile('b') },
      { z: 8, x: 60, y: 90, bytes: tile('a') },
      { z: 12, x: 1103, y: 1515, bytes: tile('mixed') },
    ];
    const archive = writeArchive(tiles, OPTIONS);
    const header = decodeHeader(archive);
    expect(header.minZoom).toBe(7);
    expect(header.maxZoom).toBe(12);
    expect(header.tileContents).toBe(3);
    const reference = new PMTiles(source(archive));
    expect(await reference.getMetadata()).toEqual({ name: 'test' });
    const ours = reader(archive);
    for (const { z, x, y, bytes } of tiles) {
      const got = await reference.getZxy(z, x, y);
      expect(new Uint8Array(got?.data ?? new ArrayBuffer(0))).toEqual(bytes);
      expect(await ours.tile(z, x, y)).toEqual(bytes);
    }
    expect(await reference.getZxy(7, 29, 45)).toBeUndefined();
    expect(await ours.tile(7, 29, 45)).toBeNull();
    expect(await ours.tile(13, 0, 0)).toBeNull();
  });

  it('split their directory into leaves when it would not fit in the first read', async () => {
    const tiles: ArchiveTile[] = [];
    for (let x = 0; x < 512; x++) {
      for (let y = 0; y < 512; y++) {
        // Scattered tiles of scattered sizes, none alike: a directory that compresses badly.
        if ((x * 7919 + y * 104_729) % 7 > 2) continue;
        tiles.push({
          z: 9,
          x,
          y,
          bytes: tile(`${String(x)},${String(y)}`.repeat(1 + ((x * 31 + y * 17) % 13))),
        });
      }
    }
    const archive = writeArchive(tiles, OPTIONS);
    const header = decodeHeader(archive);
    expect(header.leafLength).toBeGreaterThan(0);
    expect(header.rootOffset + header.rootLength).toBeLessThanOrEqual(ROOT_BYTES);
    const reference = new PMTiles(source(archive));
    const ours = reader(archive);
    for (const [x, y] of [
      [0, 0],
      [511, 511],
      [64, 3],
      [6, 99],
    ] as const) {
      const expected = tile(`${String(x)},${String(y)}`.repeat(1 + ((x * 31 + y * 17) % 13)));
      expect(new Uint8Array((await reference.getZxy(9, x, y))?.data ?? new ArrayBuffer(0))).toEqual(
        expected,
      );
      expect(await ours.tile(9, x, y)).toEqual(expected);
    }
    expect(await ours.tile(9, 3, 0)).toBeNull();
  });

  it('are read with gzipped tiles unzipped, as the school tiles are', async () => {
    const plain = tile('school tile');
    const archive = writeArchive([{ z: 11, x: 480, y: 780, bytes: gzipSync(plain) }], OPTIONS);
    // The writer stores tiles as given: mark them gzipped in the header, as tippecanoe does.
    archive[98] = 2;
    expect(decodeHeader(archive).tileCompression).toBe(2);
    const reference = new PMTiles(source(archive));
    expect(
      new Uint8Array((await reference.getZxy(11, 480, 780))?.data ?? new ArrayBuffer(0)),
    ).toEqual(plain);
    const read = await reader(archive).tile(11, 480, 780);
    expect(new TextDecoder().decode(read ?? new Uint8Array())).toBe('school tile');
  });

  it('keep each tile once read, unless told not to', async () => {
    const archive = writeArchive([{ z: 7, x: 30, y: 45, bytes: tile('a') }], OPTIONS);
    const reads: number[] = [];
    const counting = (keepTiles: boolean): ArchiveReader =>
      new ArchiveReader(
        (offset, length) => {
          reads.push(offset);
          return Promise.resolve(archive.subarray(offset, offset + length));
        },
        (data) => Promise.resolve(gunzipSync(data)),
        { keepTiles },
      );
    const keeping = counting(true);
    await keeping.tile(7, 30, 45);
    await keeping.tile(7, 30, 45);
    // The header and root in one read, then the tile once.
    expect(reads).toHaveLength(2);
    reads.length = 0;
    const passing = counting(false);
    await passing.tile(7, 30, 45);
    await passing.tile(7, 30, 45);
    expect(reads).toHaveLength(3);
  });

  it('refuse tiles compressed any other way', async () => {
    const archive = writeArchive([{ z: 7, x: 30, y: 45, bytes: tile('a') }], OPTIONS);
    archive[98] = 3;
    await expect(reader(archive).tile(7, 30, 45)).rejects.toThrow(/tile compression 3/);
  });

  it('store a tile repeated along the curve once, as one run', () => {
    const same = tile('same');
    const tiles: ArchiveTile[] = [];
    for (let x = 0; x < 4; x++) for (let y = 0; y < 4; y++) tiles.push({ z: 2, x, y, bytes: same });
    const header = decodeHeader(writeArchive(tiles, OPTIONS));
    expect(header.tileContents).toBe(1);
    expect(header.tileEntries).toBe(1);
    expect(header.addressedTiles).toBe(16);
  });
});

/** A request as a reader over HTTP makes it: its Range, and how it uses the browser's cache. */
interface Asked {
  readonly range: string | null;
  readonly cache: RequestCache | undefined;
}

/**
 * `file` served as GitHub Pages' CDN serves it once it holds the file gzipped
 * (and as a browser cache holding that gzip answers a range): a whole answer
 * is the file, unzipped by the browser, and a range is that range of the
 * gzip, marked gzip, measured against the gzip's size.
 */
function gzipServer(file: Uint8Array, asked: Asked[] = []) {
  const zipped = gzipSync(file);
  return (_url: string, init: RequestInit): Promise<Response> => {
    const range = new Headers(init.headers).get('range');
    asked.push({ range, cache: init.cache });
    if (range === null) return Promise.resolve(new Response(file.slice()));
    const [, from = '0', to = '0'] = /bytes=(\d+)-(\d+)/.exec(range) ?? [];
    const first = Number(from);
    const last = Math.min(Number(to), zipped.length - 1);
    return Promise.resolve(
      new Response(zipped.subarray(first, last + 1), {
        status: 206,
        headers: {
          'content-encoding': 'gzip',
          'content-range': `bytes ${String(first)}-${String(last)}/${String(zipped.length)}`,
        },
      }),
    );
  };
}

/** `file` served as it is: a range is that range of the file. */
function plainServer(file: Uint8Array, asked: Asked[] = []) {
  return (_url: string, init: RequestInit): Promise<Response> => {
    const range = new Headers(init.headers).get('range');
    asked.push({ range, cache: init.cache });
    if (range === null) return Promise.resolve(new Response(file.slice()));
    const [, from = '0', to = '0'] = /bytes=(\d+)-(\d+)/.exec(range) ?? [];
    const first = Number(from);
    const last = Math.min(Number(to), file.length - 1);
    return Promise.resolve(
      new Response(file.slice(first, last + 1), {
        status: 206,
        headers: {
          'content-range': `bytes ${String(first)}-${String(last)}/${String(file.length)}`,
        },
      }),
    );
  };
}

describe('the US mask, fetched whole', () => {
  const tile = (text: string): Uint8Array => new TextEncoder().encode(text);
  const tiles: ArchiveTile[] = [
    { z: 7, x: 30, y: 45, bytes: tile('inside') },
    { z: 8, x: 60, y: 90, bytes: tile('mixed') },
  ];
  const archive = writeArchive(tiles, OPTIONS);
  const unzip = (data: Uint8Array): Promise<Uint8Array> => Promise.resolve(gunzipSync(data));
  /** As the browser unzips: to plain bytes. */
  const unzipped = (data: Uint8Array): Promise<Uint8Array> =>
    Promise.resolve(new Uint8Array(gunzipSync(data)));
  const noWait = (): Promise<void> => Promise.resolve();

  it('is asked for once, without a Range, when first read, and read from memory after', async () => {
    const asked: Asked[] = [];
    const read = wholeFileReader('https://site.test/geo/us-mask.pmtiles', {
      fetch: gzipServer(archive, asked),
      sleep: noWait,
    });
    expect(asked).toEqual([]);
    const reader = new ArchiveReader(read, unzip);
    for (const { z, x, y, bytes } of tiles) expect(await reader.tile(z, x, y)).toEqual(bytes);
    expect(await reader.tile(7, 29, 45)).toBeNull();
    expect(asked).toEqual([{ range: null, cache: undefined }]);
  });

  it('is the one read that CDN cannot spoil: ranges of its gzip are not the file', async () => {
    // What the map read before: byte ranges, which that CDN answers from the gzip.
    const ranges = new ArchiveReader(
      httpRangeReader('https://site.test/mask', {
        fetch: gzipServer(archive),
        sleep: noWait,
      }),
      unzip,
    );
    await expect(ranges.tile(7, 30, 45)).rejects.toThrow(/gzip copy/);
    const whole = new ArchiveReader(
      wholeFileReader('https://site.test/mask', {
        fetch: gzipServer(archive),
        sleep: noWait,
      }),
      unzip,
    );
    expect(await whole.tile(7, 30, 45)).toEqual(tile('inside'));
  });

  it('is asked for again, past the cache, until the whole file comes', async () => {
    const zipped = gzipSync(archive);
    const answers = [
      // A gzip cut short; a copy cut short; an error page; a network failure; then the file.
      () => new Response(zipped.subarray(0, zipped.length >> 1)),
      () => new Response(archive.slice(0, archive.length - 10)),
      () => new Response('<html>busy</html>', { status: 503 }),
      () => Promise.reject(new TypeError('Failed to fetch')),
      () => new Response(archive.slice()),
    ];
    const asked: (RequestCache | undefined)[] = [];
    const waits: number[] = [];
    const read = wholeFileReader('https://site.test/mask', {
      gunzip: unzipped,
      fetch: (_url, init) => {
        asked.push(init.cache);
        const answer = answers[asked.length - 1] ?? answers[answers.length - 1];
        return Promise.resolve((answer as () => Response | Promise<Response>)());
      },
      sleep: (ms) => {
        waits.push(ms);
        return Promise.resolve();
      },
      random: () => 0.5,
    });
    const reader = new ArchiveReader(read, unzip);
    expect(await reader.tile(8, 60, 90)).toEqual(tile('mixed'));
    expect(asked).toEqual([undefined, 'reload', 'reload', 'reload', 'reload']);
    // Each wait longer than the last.
    expect(waits).toEqual(WHOLE_FILE_BACKOFF.slice(0, 4));
    // Once in, it is kept: no more requests.
    await reader.tile(7, 30, 45);
    expect(asked).toHaveLength(5);
  });

  it('handed over still gzipped, is unzipped and taken', async () => {
    let calls = 0;
    const read = wholeFileReader('https://site.test/mask', {
      gunzip: unzipped,
      fetch: () => {
        calls++;
        return Promise.resolve(new Response(gzipSync(archive)));
      },
      sleep: noWait,
    });
    expect(await new ArchiveReader(read, unzip).tile(7, 30, 45)).toEqual(tile('inside'));
    expect(calls).toBe(1);
  });

  it('that stalls is given up on and asked for again', async () => {
    vi.useFakeTimers();
    try {
      const asked: (RequestCache | undefined)[] = [];
      const read = wholeFileReader('https://site.test/mask', {
        gunzip: unzipped,
        fetch: (_url, init) => {
          asked.push(init.cache);
          if (asked.length > 1) return Promise.resolve(new Response(archive.slice()));
          // Held without an answer until given up on.
          return new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => {
              reject(init.signal?.reason as Error);
            });
          });
        },
      });
      const tileRead = new ArchiveReader(read, unzip).tile(7, 30, 45);
      await vi.advanceTimersByTimeAsync(READ_STALL_MS - 1);
      expect(asked).toEqual([undefined]);
      await vi.advanceTimersByTimeAsync(1 + (WHOLE_FILE_BACKOFF[0] ?? 0) * 2);
      expect(await tileRead).toEqual(tile('inside'));
      expect(asked).toEqual([undefined, 'reload']);
    } finally {
      vi.useRealTimers();
    }
  });

  it('is only taken whole: every byte its header counts', () => {
    expect(() => {
      checkWholeArchive(archive);
    }).not.toThrow();
    expect(() => {
      checkWholeArchive(archive.slice(0, archive.length - 1));
    }).toThrow(/bytes of/);
    expect(() => {
      checkWholeArchive(gzipSync(archive));
    }).toThrow(/not a PMTiles archive/);
  });
});

describe('an archive read in byte ranges, as the school tiles are', () => {
  const tile = (text: string): Uint8Array => new TextEncoder().encode(text);
  const archive = writeArchive([{ z: 11, x: 480, y: 780, bytes: tile('schools') }], OPTIONS);
  const unzip = (data: Uint8Array): Promise<Uint8Array> => Promise.resolve(gunzipSync(data));
  const noWait = (): Promise<void> => Promise.resolve();

  it('reads each range past the browser cache, and takes exactly the bytes asked for', async () => {
    const asked: Asked[] = [];
    const reader = new ArchiveReader(
      httpRangeReader('https://site.test/schools.pmtiles', {
        fetch: plainServer(archive, asked),
        sleep: noWait,
      }),
      unzip,
    );
    expect(await reader.tile(11, 480, 780)).toEqual(tile('schools'));
    expect(asked.length).toBeGreaterThan(1);
    expect(asked.every((request) => request.range !== null && request.cache === 'no-store')).toBe(
      true,
    );
  });

  it('cuts a whole-file answer to the range', async () => {
    const read = httpRangeReader('https://site.test/a', {
      fetch: () => Promise.resolve(new Response(archive.slice())),
      sleep: noWait,
    });
    expect(await read(10, 20)).toEqual(archive.slice(10, 30));
  });

  it('asks again for a range of a compressed copy, one from elsewhere in the file, or one cut short', async () => {
    const good = plainServer(archive);
    const wrong: (() => Response)[] = [
      () =>
        new Response(gzipSync(archive).subarray(100, 120), {
          status: 206,
          headers: { 'content-encoding': 'gzip', 'content-range': 'bytes 100-119/999' },
        }),
      () =>
        new Response(archive.slice(0, 20), {
          status: 206,
          headers: { 'content-range': `bytes 0-19/${String(archive.length)}` },
        }),
      () =>
        new Response(archive.slice(100, 110), {
          status: 206,
          headers: { 'content-range': `bytes 100-109/${String(archive.length)}` },
        }),
    ];
    for (const answer of wrong) {
      let calls = 0;
      const read = httpRangeReader('https://site.test/a', {
        fetch: (url, init) => {
          calls++;
          return calls === 1 ? Promise.resolve(answer()) : good(url, init);
        },
        sleep: noWait,
      });
      expect(await read(100, 20)).toEqual(archive.slice(100, 120));
      expect(calls).toBe(2);
    }
  });

  it('fails a read that keeps coming back wrong, after RANGE_TRIES tries', async () => {
    let calls = 0;
    const read = httpRangeReader('https://site.test/a', {
      fetch: () => {
        calls++;
        return Promise.resolve(new Response('busy', { status: 503 }));
      },
      sleep: noWait,
    });
    await expect(read(0, 10)).rejects.toThrow(/HTTP 503/);
    expect(calls).toBe(RANGE_TRIES);
  });

  it('takes the end of the file as it is when the range runs past it', async () => {
    const read = httpRangeReader('https://site.test/a', {
      fetch: plainServer(archive),
      sleep: noWait,
    });
    expect(await read(archive.length - 5, 100)).toEqual(archive.slice(archive.length - 5));
  });
});
