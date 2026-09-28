import { describe, expect, it } from 'vitest';

import { displayName, nameLayout, shownRanges } from '../names';
import { isGenericName, nameFixes, stateOfId } from '../school-names';
import type { DirectoryNames } from '../school-names';

/** A directory of `names` in Missouri, each its own school id, with `extra` names to fill it. */
function directory(
  schools: readonly (readonly [id: string, name: string, district: number])[],
  districts: readonly (readonly [id: string, name: string])[] = [],
): DirectoryNames {
  return {
    ids: schools.map(([id]) => id),
    names: schools.map(([, name]) => name),
    districtOf: schools.map(([, , district]) => district),
    districts: { ids: districts.map(([id]) => id), names: districts.map(([, name]) => name) },
  };
}

/** Schools that make the words of a directory: each word used before another, several times. */
function filler(words: readonly string[], from: number): [string, string, number][] {
  return words.flatMap((word, w) =>
    [0, 1, 2].map((n): [string, string, number] => [
      `29000000${String(from + w * 3 + n).padStart(4, '0')}`,
      `${word} PARK ${String(n)}`,
      -1,
    ]),
  );
}

describe('generic names', () => {
  it('are names of only generic words of a level', () => {
    for (const name of [
      'ELEMENTARY SCHOOL',
      'Middle School',
      'The Academy',
      'Early Childhood Center',
      'INTERMEDIATE SCH.',
      'Upper School',
      'LOWER ELEMENTARY',
      'Primary',
      // Of the kind of school, or its number after a school word.
      'Virtual Academy',
      'ALTERNATIVE SCHOOL',
      'Community Day',
      'STEM Academy',
      'Prep Academy',
      'School 16',
      'SCHOOL 8',
      'School #532',
      'School No. 1',
      'Middle School # 4',
    ]) {
      expect(isGenericName(name)).toBe(true);
    }
    for (const name of [
      'Pembroke Hill School',
      'The',
      'Academy 360',
      '5280 High School',
      'MS 131',
      'PS 15',
      'No School',
      '',
    ]) {
      expect(isGenericName(name)).toBe(false);
    }
  });
});

describe('name fixes', () => {
  it("name a school called only a level with its district or charter first, in that name's words", () => {
    const fixes = nameFixes(
      directory(
        [
          ['290061203286', 'ELEMENTARY SCHOOL', 0],
          ['290061203365', 'MIDDLE SCHOOL', 0],
          ['481332000832', 'CENTER EL', 1],
          ['290000000001', 'LINCOLN ELEMENTARY SCHOOL', 0],
          ['A1902690', 'THE ACADEMY', -1],
        ],
        [
          ['2900612', 'CITIZENS OF THE WORLD CHARTER'],
          ['4813320', 'CENTER ISD'],
        ],
      ),
    );
    expect(fixes.schools).toEqual({
      '290061203286': { district: 'Citizens of the World Charter' },
      '290061203365': { district: 'Citizens of the World Charter' },
    });
    expect(displayName('ELEMENTARY SCHOOL', { state: 'MO' }, fixes.schools['290061203286'])).toBe(
      'Citizens of the World Charter - Elementary School',
    );
  });

  it('name a numbered school, and one only of its kind, with its district first', () => {
    const fixes = nameFixes(
      directory(
        [
          ['341269004888', 'School 8', 0],
          ['270002504467', 'School #532', 1],
          ['063417014659', 'Virtual Academy', 2],
          ['010114000819', 'Alternative School', 3],
          // A charter named as its school says it already.
          ['040039902325', 'Montessori Academy', 4],
        ],
        [
          ['3412690', 'Paterson Public School District'],
          ['2700025', 'Intermediate School District 287'],
          ['0634170', 'San Bernardino City Unified'],
          ['0101140', 'DeKalb County'],
          ['0400399', 'Montessori Academy Inc. (80011)'],
        ],
      ),
    );
    const shown = (id: string, name: string): string => displayName(name, {}, fixes.schools[id]);
    expect(shown('341269004888', 'School 8')).toBe('Paterson Public School District - School 8');
    // A district named only for what it is keeps its whole name, its number too.
    expect(shown('270002504467', 'School #532')).toBe(
      'Intermediate School District 287 - School #532',
    );
    expect(shown('063417014659', 'Virtual Academy')).toBe(
      'San Bernardino City Unified - Virtual Academy',
    );
    expect(shown('010114000819', 'Alternative School')).toBe('DeKalb County - Alternative School');
    expect(fixes.schools['040039902325']).toBeUndefined();
  });

  it('name the district first by its name proper, without the number or county after it', () => {
    const fixes = nameFixes(
      directory(
        [
          ['080291000001', 'Campus Middle School', 0],
          ['171743000002', 'Early Childhood', 1],
        ],
        [
          ['0802910', 'Cherry Creek School District No. 5 in the county of Arapah'],
          ['1717430', 'Quincy School District 172'],
        ],
      ),
    );
    expect(fixes.schools['080291000001']).toEqual({ district: 'Cherry Creek School District' });
    expect(fixes.schools['171743000002']).toEqual({ district: 'Quincy School District' });
  });

  it('end a name NCES cut off mid-word with its last whole word, or the one word it can be', () => {
    const width = 30;
    const cut = [
      // 30 characters each: Missouri's width.
      ['290002502748', 'ALLEN VILLAGE ELEMENTARY ACADE'],
      ['290000000002', 'NORTH SIDE ELEMENTARY SCHOO'.padEnd(width - 1, ' ') + 'X'],
      ['290000000003', 'WEST RIVERSIDE ACADEMY MAGNE'.padStart(width, 'A')],
      ['290000000004', 'SOUTH CENTRAL ELEM-KINMUNDY'.padStart(width, 'B')],
    ] as const;
    for (const [, name] of cut) expect(name).toHaveLength(width);
    const fixes = nameFixes(
      directory([
        ...cut.map(([id, name]): [string, string, number] => [id, name, -1]),
        ...filler(['ACADEMY', 'ACADEMIC', 'MAGNET', 'SCHOOL'], 100),
      ]),
    );
    // "Acade" is Academy's start and Academic's: left off, never guessed.
    expect(fixes.schools['290002502748']).toEqual({ end: 24 });
    expect(displayName(cut[0][1], {}, fixes.schools['290002502748'])).toBe(
      'Allen Village Elementary',
    );
    // "Magne" can only be Magnet.
    const magnet = fixes.schools['290000000003'];
    expect(magnet?.word).toBe('Magnet');
    expect(displayName(cut[2][1], {}, magnet)).toMatch(/ Academy Magnet$/);
    // A single letter is an initial; a word no word starts is a word of its own.
    expect(fixes.schools['290000000002']).toBeUndefined();
    expect(fixes.schools['290000000004']).toBeUndefined();
  });

  it("complete a cut word with the one word of its own district's names it can be", () => {
    const allen = (districts: readonly (readonly [string, string, number])[]) =>
      nameFixes(
        directory(
          [
            // Allen Village's schools, as the directory has them; three more fill Missouri's width.
            ['290002502748', 'ALLEN VILLAGE ELEMENTARY ACADE', 0],
            ['290002503325', 'ALLEN VILLAGE JUNIOR ACADEMY', 0],
            ['290002503327', 'ALLEN VILLAGE PRIMARY ACADEMY', 0],
            ['290002503233', 'ALLEN VILLAGE HIGH SCHOOL', 0],
            ...districts,
            ['290000000002', 'A'.repeat(30), -1],
            ['290000000003', 'B'.repeat(30), -1],
            ...filler(['ACADEMY', 'ACADEMIC'], 100),
          ],
          [['2900025', 'ALLEN VILLAGE']],
        ),
      );
    const fixes = allen([]);
    expect(fixes.schools['290002502748']).toEqual({ end: 25, word: 'Academy' });
    expect(displayName('ALLEN VILLAGE ELEMENTARY ACADE', {}, fixes.schools['290002502748'])).toBe(
      'Allen Village Elementary Academy',
    );
    // Two words of the district it could be: left off, never guessed.
    const both = allen([['290002503400', 'ALLEN VILLAGE ACADEMIC CENTER', 0]]);
    expect(both.schools['290002502748']).toEqual({ end: 24 });
  });

  it('leave names shorter than their field alone', () => {
    const fixes = nameFixes(
      directory([
        ['290000000001', 'ROSS ACADE', -1],
        ['290000000002', 'A'.repeat(30), -1],
        ['290000000003', 'B'.repeat(30), -1],
        ['290000000004', 'C'.repeat(30), -1],
        ...filler(['ACADEMY'], 100),
      ]),
    );
    expect(fixes.schools['290000000001']).toBeUndefined();
  });

  it("read a public school's or district's state from its id", () => {
    expect(stateOfId('290002502748')).toBe('MO');
    expect(stateOfId('2900612')).toBe('MO');
    expect(stateOfId('A1902690')).toBeNull();
    expect(stateOfId('020000000001')).toBeNull();
    expect(stateOfId(null)).toBeNull();
  });
});

describe('a fixed name', () => {
  const ranges = (
    raw: string,
    fix: Parameters<typeof nameLayout>[2],
    marked: [number, number][],
  ) => {
    const layout = nameLayout(raw, {}, fix);
    const shown = layout.map((piece) => piece.text).join('');
    return { shown, marked: shownRanges(layout, raw, marked).map(([a, b]) => shown.slice(a, b)) };
  };

  it('keeps a match in the written name on the shown one, the district before it', () => {
    expect(
      ranges('ELEMENTARY SCHOOL', { district: 'Citizens of the World Charter' }, [[0, 10]]),
    ).toEqual({
      shown: 'Citizens of the World Charter - Elementary School',
      marked: ['Elementary'],
    });
  });

  it('shows nothing of a match in what it leaves off, and the word it ends with for one there', () => {
    expect(
      ranges('ALLEN VILLAGE ELEMENTARY ACADE', { end: 24 }, [
        [0, 5],
        [25, 30],
      ]),
    ).toEqual({
      shown: 'Allen Village Elementary',
      marked: ['Allen'],
    });
    expect(ranges('LINCOLN MAGNE', { end: 8, word: 'Magnet' }, [[8, 13]])).toEqual({
      shown: 'Lincoln Magnet',
      marked: ['Magnet'],
    });
  });
});
