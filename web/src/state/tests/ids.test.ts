// @vitest-environment node
import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import {
  DISTRICT_ID,
  PRIVATE_SCHOOL_ID,
  PUBLIC_SCHOOL_ID,
  isDistrictId,
  isSchoolId,
  isZipCode,
  parseDistrictId,
  parseSchoolId,
  parseZipCode,
} from '../ids';

/** The id patterns the pipeline publishes, straight from the shared JSON Schema. */
function schemaPattern(name: string): string {
  const schema = JSON.parse(
    readFileSync(
      new URL('../../../../schemas/school-directory.schema.json', import.meta.url),
      'utf8',
    ),
  ) as { $defs: Record<string, { pattern?: string }> };
  const pattern = schema.$defs[name]?.pattern;
  if (pattern === undefined) throw new Error(`no pattern for ${name}`);
  return pattern;
}

describe('id formats', () => {
  it('match the patterns in the published schema', () => {
    expect(
      `^(?:${PUBLIC_SCHOOL_ID.source.slice(1, -1)}|${PRIVATE_SCHOOL_ID.source.slice(1, -1)})$`,
    ).toBe(schemaPattern('SchoolId'));
    expect(DISTRICT_ID.source).toBe(schemaPattern('DistrictId'));
  });

  it('accept public, private and district ids', () => {
    expect(isSchoolId('010000500870')).toBe(true);
    expect(isSchoolId('A9106011')).toBe(true);
    expect(isSchoolId('00000123')).toBe(true);
    expect(isDistrictId('0100005')).toBe(true);
    expect(isZipCode('02139')).toBe(true);
  });

  it.each([
    '',
    '01000050087',
    '0100005008701',
    'a9106011',
    'A910601',
    'A91060111',
    'A9106-11',
    '０１０００００５００８７０',
    ' 010000500870',
    null,
    12,
  ])('rejects %j as a school id', (value) => {
    expect(isSchoolId(value)).toBe(false);
  });
});

describe('parseSchoolId', () => {
  it('trims space and upper-cases a private id', () => {
    expect(parseSchoolId('  010000500870\n')).toBe('010000500870');
    expect(parseSchoolId('a9106011')).toBe('A9106011');
    expect(parseSchoolId(' bb000123 ')).toBe('BB000123');
  });

  it.each([
    null,
    undefined,
    '',
    '   ',
    '0100 0500870',
    '010000500870x',
    '<script>',
    'A9106011;',
    '1'.repeat(40),
    'ÄBCDEFGH',
  ])('rejects %j', (raw) => {
    expect(parseSchoolId(raw)).toBeNull();
  });
});

describe('parseDistrictId', () => {
  it('accepts exactly seven digits', () => {
    expect(parseDistrictId('0100005')).toBe('0100005');
    expect(parseDistrictId(' 3620580 ')).toBe('3620580');
  });

  it.each(['010000', '01000050', 'A100005', '', null, '0100005x'])('rejects %j', (raw) => {
    expect(parseDistrictId(raw)).toBeNull();
  });
});

describe('parseZipCode', () => {
  it('accepts five digits and ZIP+4', () => {
    expect(parseZipCode('02139')).toBe('02139');
    expect(parseZipCode('55401-1234')).toBe('55401');
    expect(parseZipCode(' 99501 ')).toBe('99501');
  });

  it.each(['0213', '021390', '00000', '02139-12', '02139 1234', 'ABCDE', '', null])(
    'rejects %j',
    (raw) => {
      expect(parseZipCode(raw)).toBeNull();
    },
  );

  it('rejects 00000 as a ZIP code', () => {
    expect(isZipCode('00000')).toBe(false);
  });
});
