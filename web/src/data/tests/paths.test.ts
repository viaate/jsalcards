import { describe, expect, it } from 'vitest';

import { HASH_LENGTH, hashedPath, plainPath } from '../paths';

const HASH = 'b5c6259854d3383b35f36d1082025da82c7cfda3993280420c403ceab31378e8';

describe('published names', () => {
  it('carry the first digits of a content hash before the extension', () => {
    expect(HASH_LENGTH).toBe(10);
    expect(hashedPath('schools/meta.json', HASH)).toBe('schools/meta.b5c6259854.json');
    expect(hashedPath('schools/schools.pmtiles', HASH)).toBe('schools/schools.b5c6259854.pmtiles');
    expect(hashedPath('search-index.bin', HASH)).toBe('search-index.b5c6259854.bin');
  });

  it('are asked for by their plain names', () => {
    expect(plainPath('schools/meta.b5c6259854.json')).toBe('schools/meta.json');
    expect(plainPath('search-index.b5c6259854.bin')).toBe('search-index.bin');
    for (const plain of [
      'live/closings.json',
      'replays/2026-01-12.json',
      // A replay named by hex digits alone is its plain name.
      'replays/0123456789.json',
      'schools/meta.json',
      'schools/meta.B5C6259854.json',
      'schools/meta.b5c625985.json',
    ]) {
      expect(plainPath(plain)).toBe(plain);
    }
  });

  it('need an extension and a hex hash', () => {
    expect(() => hashedPath('search-index', HASH)).toThrow(/no extension/);
    expect(() => hashedPath('schools/.hidden', HASH)).toThrow(/no extension/);
    expect(() => hashedPath('search-index.bin', 'not hex at all')).toThrow(/not a hex hash/);
    expect(() => hashedPath('search-index.bin', 'abc')).toThrow(/not a hex hash/);
  });
});
