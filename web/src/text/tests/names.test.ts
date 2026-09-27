import { describe, expect, it } from 'vitest';

import { casedName, displayName, nameLayout, shownRanges } from '../names';

describe('displayName', () => {
  it('shows a name written in capitals in title case', () => {
    expect(displayName('THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS')).toBe(
      'The Pembroke Hill School - Wornall Campus',
    );
    expect(displayName('BORDER STAR MONTESSORI')).toBe('Border Star Montessori');
    expect(displayName('CLEMENTINE MONTESSORI SCHOOL')).toBe('Clementine Montessori School');
  });

  it('keeps the case of a name with any lowercase letter', () => {
    for (const name of [
      'Kate D Smith DAR High School',
      'KIPP Endeavor Academy',
      'McKinley Elementary',
    ]) {
      expect(displayName(name)).toBe(name);
    }
  });

  it('spells out the shortenings the notes list, in place', () => {
    expect(displayName('Ross El Sch')).toBe('Ross Elementary School');
    expect(displayName('Lancaster Catholic HS')).toBe('Lancaster Catholic High School');
    expect(displayName('McCall Gen George A Sch')).toBe('McCall Gen George A School');
    expect(displayName('Philadelphia Performing Arts CS')).toBe(
      'Philadelphia Performing Arts Charter School',
    );
    expect(displayName('Penn View MS')).toBe('Penn View Middle School');
    expect(displayName('LINCOLN JHS')).toBe('Lincoln Junior High School');
    expect(displayName('Noble St Chtr-Rowe-Clark MS Acad')).toBe(
      'Noble St Charter-Rowe-Clark Middle School Academy',
    );
  });

  it('spells out the other standard NCES shortenings', () => {
    expect(displayName('SMITH EL')).toBe('Smith Elementary');
    expect(displayName('Lincoln Elem')).toBe('Lincoln Elementary');
    expect(displayName('BELLE ELEM.')).toBe('Belle Elementary');
    expect(displayName('WASHINGTON ES')).toBe('Washington Elementary School');
    expect(displayName('Friendship PCS - Collegiate Academy')).toBe(
      'Friendship Public Charter School - Collegiate Academy',
    );
    expect(displayName('Towanda Area JSHS')).toBe('Towanda Area Junior-Senior High School');
    expect(displayName('East Stroudsburg SHS North')).toBe(
      'East Stroudsburg Senior High School North',
    );
    expect(displayName('COLMESNEIL JH/HS')).toBe('Colmesneil Junior High/High School');
    expect(displayName('Drums El/MS')).toBe('Drums Elementary/Middle School');
    expect(displayName('ALVARADO EL-SOUTH')).toBe('Alvarado Elementary-South');
    expect(displayName('Hershey Intrmd El Sch')).toBe('Hershey Intermediate Elementary School');
    expect(displayName('BARBERS HILL INT')).toBe('Barbers Hill Intermediate');
    expect(displayName('LA VEGA PRI')).toBe('La Vega Primary');
    expect(displayName('Curtisville Pri Ctr')).toBe('Curtisville Primary Center');
    expect(displayName('MARTIN LUTHER KING JR LEARNING CTR')).toBe(
      'Martin Luther King Jr Learning Center',
    );
    expect(displayName('ST JOHN THE BAPTIST SCH')).toBe('St John the Baptist School');
    expect(displayName('Shaker Hts High School')).toBe('Shaker Heights High School');
    expect(displayName('PASEO ACAD. OF PERFORMING ARTS')).toBe('Paseo Academy of Performing Arts');
  });

  it('leaves words that only look like shortenings', () => {
    expect(displayName('EL DORADO HIGH SCHOOL')).toBe('El Dorado High School');
    expect(displayName('John Adams Academy - El Dorado Hills')).toBe(
      'John Adams Academy - El Dorado Hills',
    );
    expect(displayName('TEMPLE BETH EL SCHOOL')).toBe('Temple Beth El School');
    expect(displayName('RALEIGH PRIMARY/EL ACADEMY')).toBe('Raleigh Primary/El Academy');
    expect(displayName('CS Brown High - STEM Program')).toBe('CS Brown High - STEM Program');
    expect(displayName("SOUTHWEST PUBLIC SCHOOLS INT'L LEADERSHIP ACADEMY")).toBe(
      "Southwest Public Schools Int'l Leadership Academy",
    );
    expect(displayName('ACCELERATED INT CHARTER SCHOOL')).toBe('Accelerated Int Charter School');
    expect(displayName('Clark County Detention Ctr J-SHS')).toBe(
      'Clark County Detention Center J-SHS',
    );
    expect(displayName('NEX GEN ACADEMY')).toBe('Nex Gen Academy');
    // Lowercase letters are words, not shortenings.
    expect(displayName('Ms. Smith Preschool')).toBe('Ms. Smith Preschool');
  });

  it('keeps the letters of a numbered New York City school', () => {
    expect(displayName('PS 123 JOHN H GLENN')).toBe('PS 123 John H Glenn');
    expect(displayName('JHS 167 ROBERT F WAGNER')).toBe('JHS 167 Robert F Wagner');
    expect(displayName('MS 45 THOMAS C GIORDANO')).toBe('MS 45 Thomas C Giordano');
    expect(displayName('IS 289')).toBe('IS 289');
  });

  it('keeps MS as the state in Mississippi', () => {
    expect(displayName('MS School For The Blind', { state: 'MS' })).toBe('MS School For The Blind');
    expect(displayName('NORTHEAST MS REGIONAL ALTERNATIVE', { state: 'MS' })).toBe(
      'Northeast MS Regional Alternative',
    );
    expect(displayName('NORTHEAST MS REGIONAL ALTERNATIVE')).toBe(
      'Northeast Middle School Regional Alternative',
    );
  });

  it('keeps acronyms, initials and Roman numerals in capitals', () => {
    expect(displayName('KIPP:DELTA COLLEGE PREP SCHOOL')).toBe('KIPP:Delta College Prep School');
    expect(displayName('HOLY FAMILY ACADEMY II')).toBe('Holy Family Academy II');
    expect(displayName('IDEA STEM ACADEMY LLC')).toBe('IDEA STEM Academy LLC');
  });

  it('lowercases small words after the first', () => {
    expect(displayName('THE ACADEMY OF ARTS AND SCIENCES')).toBe(
      'The Academy of Arts and Sciences',
    );
  });

  it('handles Mc names, apostrophes and ordinals', () => {
    expect(displayName('MCKINLEY ELEMENTARY')).toBe('McKinley Elementary');
    expect(displayName("ST. MARY'S SCHOOL")).toBe("St. Mary's School");
    expect(displayName("O'NEILL INT'L ACADEMY")).toBe("O'Neill Int'l Academy");
    expect(displayName("GIRLS' PREP")).toBe("Girls' Prep");
    expect(displayName('21ST CENTURY 6TH GRADE CENTER')).toBe('21st Century 6th Grade Center');
  });

  it('keeps letters outside A to Z whole', () => {
    expect(displayName('ESCUELA ESPAÑOLA')).toBe('Escuela Española');
    expect(displayName('ÉCOLE FRANÇAISE')).toBe('École Française');
  });

  it('never adds, drops or moves a word', () => {
    const letters = (text: string): string => text.toUpperCase().replace(/[^A-Z0-9]/g, '');
    const names = [
      'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
      "O'NEILL INT'L ACADEMY",
      'Friendship PCS - Collegiate Academy',
      'Ross El Sch',
    ];
    for (const name of names) {
      const layout = nameLayout(name);
      // The pieces cover the written name in order, and only spelled-out pieces change letters.
      expect(layout.map((piece) => name.slice(piece.from, piece.to)).join('')).toBe(name);
      for (const piece of layout.filter((p) => !p.spelled)) {
        expect(letters(piece.text)).toBe(letters(name.slice(piece.from, piece.to)));
      }
    }
  });
});

describe('casedName', () => {
  it('changes only case, so the text keeps its length and letters', () => {
    const names = [
      'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
      "O'NEILL INT'L ACADEMY",
      'İSTANBUL ACADEMY',
      '21ST CENTURY 6TH GRADE CENTER',
      'LANCASTER HS',
      '',
      '64113',
    ];
    for (const name of names) {
      const shown = casedName(name);
      expect(shown).toHaveLength(name.length);
      expect(shown.toUpperCase()).toBe(name.toUpperCase());
    }
    expect(casedName('KANSAS CITY')).toBe('Kansas City');
    expect(casedName('ST LOUIS')).toBe('St Louis');
    expect(casedName('Kansas City')).toBe('Kansas City');
  });
});

describe('shownRanges', () => {
  const ranges = (raw: string, marked: [number, number][]): string[] => {
    const layout = nameLayout(raw);
    const shown = layout.map((piece) => piece.text).join('');
    return shownRanges(layout, raw, marked).map(([start, end]) => shown.slice(start, end));
  };

  it('carries a match over to the shown name', () => {
    const raw = 'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS';
    expect(ranges(raw, [[4, 12]])).toEqual(['Pembroke']);
    expect(
      ranges(raw, [
        [4, 12],
        [13, 17],
      ]),
    ).toEqual(['Pembroke', 'Hill']);
  });

  it('marks the words a matched shortening stands for', () => {
    expect(ranges('Ross El Sch', [[0, 4]])).toEqual(['Ross']);
    expect(ranges('Ross El Sch', [[8, 11]])).toEqual(['School']);
    expect(ranges('Ross El Sch', [[8, 10]])).toEqual(['Sc']);
    expect(ranges('Lancaster Catholic HS', [[19, 21]])).toEqual(['High School']);
    expect(ranges('Lancaster Catholic HS', [[19, 20]])).toEqual(['High School']);
    expect(
      ranges('Ross El Sch', [
        [5, 7],
        [8, 11],
      ]),
    ).toEqual(['Elementary', 'School']);
  });

  it('keeps ranges after a spelled-out word in place', () => {
    expect(ranges('Lincoln Elem Magnet', [[13, 19]])).toEqual(['Magnet']);
    expect(ranges('PASEO ACAD. OF PERFORMING ARTS', [[15, 25]])).toEqual(['Performing']);
  });
});
