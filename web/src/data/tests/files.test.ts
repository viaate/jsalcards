import { describe, expect, it, vi } from 'vitest';

import { createDataFiles, dataRootFor, fetchBytes, fetchData, fetchJson } from '../files';
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
