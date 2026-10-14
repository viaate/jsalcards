import { createHash } from 'node:crypto';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

// scripts/edition.mjs is a plain Node module (staging runs it); this is the slice the tests use.
interface EditionModule {
  checkEdition: (
    bytes: Uint8Array,
    metaBytes: Uint8Array,
    pointsBytes: Uint8Array,
    meta: { generated_on: string; count: number; districts: { ids: unknown[] } },
  ) => void;
  checkEditionPresent: (
    manifest: { outputs?: Record<string, unknown> } | null,
    present: boolean,
  ) => void;
  EditionError: new (message: string) => Error;
}
const editionModule = path.join(import.meta.dirname, '..', 'scripts', 'edition.mjs');
const { checkEdition, checkEditionPresent, EditionError } = (await import(
  /* @vite-ignore */ editionModule
)) as EditionModule;

// A synthetic directory, written as the pipeline writes meta.json: compact, keys sorted.
const meta = {
  count: 2,
  districts: { ids: ['0100005'], names: ['Synthetic District'] },
  generated_on: '2026-10-13',
  ids: ['010000500870', '0000000A'],
  names: ['Synthetic Middle School', 'Synthetic Academy'],
  schema_version: 1,
  school_years: { private: '2023-24', public: '2024-25' },
};
const metaBytes = Buffer.from(JSON.stringify(meta));
// Two schools: a 16-byte header and 13 bytes each (pipeline/snowlight/directory/points.py).
const pointsBytes = Buffer.alloc(16 + 2 * 13, 7);

function digest(metaText: Buffer, points: Buffer): string {
  const blanked = Buffer.from(
    metaText.toString('utf8').replace('"generated_on":"2026-10-13"', '"generated_on":""'),
  );
  return createHash('sha256')
    .update(Buffer.concat([blanked, points]))
    .digest('hex');
}

const edition = {
  content_sha256: digest(metaBytes, pointsBytes),
  districts: 1,
  generated_on: '2026-10-13',
  schema_version: 1,
  schools: 2,
};

function check(
  value: unknown,
  options: { meta?: Buffer; points?: Buffer; raw?: string } = {},
): void {
  const bytes = Buffer.from(options.raw ?? JSON.stringify(value));
  checkEdition(bytes, options.meta ?? metaBytes, options.points ?? pointsBytes, meta);
}

describe('the staged edition', () => {
  it('is accepted when it names the meta.json and points.bin beside it', () => {
    expect(() => {
      check(edition);
    }).not.toThrow();
  });

  it.each([
    ['another digest', { content_sha256: '0'.repeat(64) }],
    ['another date', { generated_on: '2026-10-12' }],
    ['another school count', { schools: 3 }],
    ['another district count', { districts: 2 }],
    ['a count written as text', { schools: '2' }],
    ['another schema version', { schema_version: 2 }],
    ['an upper-case digest', { content_sha256: edition.content_sha256.toUpperCase() }],
  ])('is refused with %s', (_name, change) => {
    expect(() => {
      check({ ...edition, ...change });
    }).toThrow(
      new EditionError(
        'schools/edition.json does not name the schools/meta.json and points.bin beside it',
      ),
    );
  });

  it('is refused when points.bin differs: a school in another district is other content', () => {
    const moved = Buffer.from(pointsBytes);
    moved[16 + 8] = 0;
    expect(() => {
      check(edition, { points: moved });
    }).toThrow(EditionError);
  });

  it('is refused with a key the pipeline does not write, or without one it does', () => {
    expect(() => {
      check({ ...edition, note: 'x' });
    }).toThrow(/has the keys content_sha256, districts, generated_on, note/);
    const short = Object.fromEntries(
      Object.entries(edition).filter(([key]) => key !== 'districts'),
    );
    expect(() => {
      check(short);
    }).toThrow(EditionError);
  });

  it('is refused when it is not JSON, or not an object', () => {
    expect(() => {
      check(null, { raw: '<!doctype html>' });
    }).toThrow(new EditionError('schools/edition.json is not JSON'));
    for (const raw of ['[]', 'null', '"text"']) {
      expect(() => {
        check(null, { raw });
      }).toThrow(new EditionError('schools/edition.json is not an object'));
    }
  });

  it('is refused when meta.json writes its date other than once', () => {
    const twice = Buffer.from(
      JSON.stringify({ ...meta, names: ['x', 'y'], school_years: meta.school_years }).replace(
        '"ids"',
        '"generated_on":"2026-10-13","ids"',
      ),
    );
    expect(() => {
      check(edition, { meta: twice });
    }).toThrow(/its date is not written once/);
    const pretty = Buffer.from(JSON.stringify(meta, null, 1));
    expect(() => {
      check(edition, { meta: pretty });
    }).toThrow(/its date is not written once/);
  });
});

describe('an edition the build recorded', () => {
  it('must be staged', () => {
    const recorded = { outputs: { 'edition.json': { sha256: 'x' } } };
    expect(() => {
      checkEditionPresent(recorded, false);
    }).toThrow(
      new EditionError(
        'schools/edition.json is missing, but the directory build that wrote schools/meta.json wrote one',
      ),
    );
    expect(() => {
      checkEditionPresent(recorded, true);
    }).not.toThrow();
  });

  it('may be absent from a build older than editions, or one that kept no record', () => {
    expect(() => {
      checkEditionPresent({ outputs: { 'meta.json': {} } }, false);
    }).not.toThrow();
    expect(() => {
      checkEditionPresent(null, false);
    }).not.toThrow();
  });
});
