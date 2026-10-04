import { afterEach, describe, expect, it, vi } from 'vitest';

import { CACHE_NAMES } from '../../pwa/config';
import { FakeCaches } from '../../pwa/tests/fakes';
import {
  createDataFiles,
  dataRootFor,
  fetchBytes,
  fetchData,
  fetchFile,
  fetchJson,
  readsPastWorker,
} from '../files';
import type { Fetch } from '../files';
import { jsonResponse } from './builders';

const ROOT = 'https://snow.test/repo/data/';

describe('the files a build ships', () => {
  it('resolves shipped files under the data root and nothing else', () => {
    const files = createDataFiles(['live/closings.json', 'search-index.bin'], ROOT);
    expect(files.has('live/closings.json')).toBe(true);
    expect(files.url('live/closings.json')).toBe(`${ROOT}live/closings.json`);
    expect(files.has('schools/meta.json')).toBe(false);
    expect(files.url('schools/meta.json')).toBeNull();
  });

  it('finds a file published under a hashed name by its plain name', () => {
    const files = createDataFiles(
      [
        'live/closings.json',
        'schools/meta.0123456789.json',
        'schools/schools.abcdef0123.pmtiles',
        'search-index.9876543210.bin',
      ],
      ROOT,
    );
    expect(files.url('schools/meta.json')).toBe(`${ROOT}schools/meta.0123456789.json`);
    expect(files.url('schools/schools.pmtiles')).toBe(`${ROOT}schools/schools.abcdef0123.pmtiles`);
    expect(files.url('search-index.bin')).toBe(`${ROOT}search-index.9876543210.bin`);
    expect(files.url('live/closings.json')).toBe(`${ROOT}live/closings.json`);
    expect(files.has('schools/meta.0123456789.json')).toBe(false);
    expect(files.has('schools/points.bin')).toBe(false);
  });

  it('finds the data root for a site at the domain root or on a project path', () => {
    expect(dataRootFor('/', 'https://snow.test/?at=1,2,3')).toBe('https://snow.test/data/');
    expect(dataRootFor('/repo/', 'https://x.test/repo/')).toBe('https://x.test/repo/data/');
  });
});

describe('reading a file', () => {
  it('never asks for a file the build does not ship', async () => {
    const fetchImpl = vi.fn<(input: string) => Promise<Response>>();
    const files = createDataFiles([], ROOT);
    expect(await fetchData(files, 'live/closings.json', {}, fetchImpl)).toBeNull();
    expect(await fetchJson(files, 'live/closings.json', {}, fetchImpl)).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('comes back empty, quietly, for a missing file, a failed request or bad JSON', async () => {
    const warn = vi.spyOn(console, 'warn');
    const error = vi.spyOn(console, 'error');
    const files = createDataFiles(['live/closings.json'], ROOT);
    const answers: (() => Promise<Response>)[] = [
      () => Promise.resolve(jsonResponse({ missing: true }, 404)),
      () => Promise.reject(new TypeError('Failed to fetch')),
      () => Promise.resolve(new Response('{not json', { status: 200 })),
    ];
    for (const answer of answers) {
      expect(await fetchJson(files, 'live/closings.json', {}, answer)).toBeNull();
    }
    expect(warn).not.toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();
    warn.mockRestore();
    error.mockRestore();
  });

  it('passes the request options through and returns the parsed file', async () => {
    const files = createDataFiles(['live/closings.json'], ROOT);
    const fetchImpl = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.resolve(jsonResponse({ schema_version: 1 })),
    );
    const value = await fetchJson(files, 'live/closings.json', { cache: 'no-cache' }, fetchImpl);
    expect(value).toEqual({ schema_version: 1 });
    expect(fetchImpl).toHaveBeenCalledWith(`${ROOT}live/closings.json`, { cache: 'no-cache' });
  });

  it('reads binary files whole', async () => {
    const files = createDataFiles(['schools/points.bin'], ROOT);
    const bytes = await fetchBytes(files, 'schools/points.bin', {}, () =>
      Promise.resolve(new Response(new Uint8Array([1, 2, 3]))),
    );
    expect(bytes === null ? null : [...new Uint8Array(bytes)]).toEqual([1, 2, 3]);
  });

  it('still rejects when the caller aborts, so a cancelled read is not taken for a missing file', async () => {
    const files = createDataFiles(['live/closings.json'], ROOT);
    const controller = new AbortController();
    controller.abort();
    const aborted = fetchData(files, 'live/closings.json', { signal: controller.signal }, () =>
      Promise.reject(new DOMException('Aborted', 'AbortError')),
    );
    await expect(aborted).rejects.toThrow('Aborted');
  });
});

describe('reading before the service worker takes over', () => {
  // The site at the domain root, the base these tests build for.
  const SITE_ROOT = 'https://snow.test/data/';
  const META = `${SITE_ROOT}schools/meta.json`;
  const BODY = '{"schema_version":1}';

  /** A production page with Cache Storage and service workers; `controlled` once one has it. */
  function page(options: { controlled?: boolean; production?: boolean; status?: number } = {}) {
    vi.stubEnv('PROD', options.production ?? true);
    const caches = new FakeCaches();
    vi.stubGlobal('caches', caches);
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: { controller: options.controlled === true ? {} : null },
    });
    const network = vi.fn<Fetch>(() =>
      Promise.resolve(new Response(BODY, { status: options.status ?? 200 })),
    );
    vi.stubGlobal('fetch', network);
    return { caches, network };
  }

  /** What the static-data cache holds for `url` once any keep on its way is written. */
  async function heldAfterAWhile(caches: FakeCaches, url: string): Promise<string | undefined> {
    await new Promise((resolve) => setTimeout(resolve, 50));
    return caches.text(CACHE_NAMES.staticData, url);
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    Reflect.deleteProperty(navigator, 'serviceWorker');
  });

  it('keeps the file in the worker’s cache as it reads it, and hands the page the same file', async () => {
    const { caches, network } = page();
    expect(readsPastWorker()).toBe(true);
    const response = await fetchFile(META, { cache: 'no-cache' });
    expect(await response.text()).toBe(BODY);
    expect(network).toHaveBeenCalledOnce();
    expect(network).toHaveBeenCalledWith(META, { cache: 'no-cache' });
    await vi.waitFor(async () => {
      expect(await caches.text(CACHE_NAMES.staticData, META)).toBe(BODY);
    });
  });

  it('is how every data file is read', async () => {
    const { caches } = page();
    const files = createDataFiles(['schools/meta.json'], SITE_ROOT);
    expect(await fetchJson(files, 'schools/meta.json')).toEqual({ schema_version: 1 });
    await vi.waitFor(async () => {
      expect(await caches.text(CACHE_NAMES.staticData, META)).toBe(BODY);
    });
  });

  it('keeps nothing once a worker controls the page: what it fetches, it keeps itself', async () => {
    const { caches } = page({ controlled: true });
    expect(readsPastWorker()).toBe(false);
    expect(await (await fetchFile(META)).text()).toBe(BODY);
    expect(await heldAfterAWhile(caches, META)).toBeUndefined();
  });

  it('keeps nothing in a development build, which has no worker, nor an answer but a 200', async () => {
    const dev = page({ production: false });
    expect(readsPastWorker()).toBe(false);
    await fetchFile(META);
    expect(await heldAfterAWhile(dev.caches, META)).toBeUndefined();
    vi.unstubAllEnvs();
    const missing = page({ status: 404 });
    expect((await fetchFile(META)).status).toBe(404);
    expect(await heldAfterAWhile(missing.caches, META)).toBeUndefined();
  });

  it('keeps nothing where the browser has no service workers', () => {
    page();
    Reflect.deleteProperty(navigator, 'serviceWorker');
    expect(readsPastWorker()).toBe(false);
  });
});
