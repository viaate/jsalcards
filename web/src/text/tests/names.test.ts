import { describe, expect, it } from 'vitest';

import { displayName } from '../names';

describe('displayName', () => {
  it('shows a name written in capitals in title case', () => {
    expect(displayName('THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS')).toBe(
      'The Pembroke Hill School - Wornall Campus',
    );
    expect(displayName('BORDER STAR MONTESSORI')).toBe('Border Star Montessori');
    expect(displayName('CLEMENTINE MONTESSORI SCHOOL')).toBe('Clementine Montessori School');
  });

  it('leaves a name with any lowercase letter as written', () => {
    for (const name of ['Ross El Sch', 'Lancaster Catholic HS', 'Kate D Smith DAR High School']) {
      expect(displayName(name)).toBe(name);
    }
  });

  it('keeps acronyms, initials and Roman numerals in capitals', () => {
    expect(displayName('KIPP:DELTA COLLEGE PREP SCHOOL')).toBe('KIPP:Delta College Prep School');
    expect(displayName('PS 123 JOHN H GLENN')).toBe('PS 123 John H Glenn');
    expect(displayName('LINCOLN JHS')).toBe('Lincoln JHS');
    expect(displayName('HOLY FAMILY ACADEMY II')).toBe('Holy Family Academy II');
    expect(displayName('IDEA STEM ACADEMY LLC')).toBe('IDEA STEM Academy LLC');
    expect(displayName('WASHINGTON ES')).toBe('Washington ES');
  });

  it('title-cases the usual short forms, and lowercases small words after the first', () => {
    expect(displayName('ST JOHN THE BAPTIST SCH')).toBe('St John the Baptist Sch');
    expect(displayName('THE ACADEMY OF ARTS AND SCIENCES')).toBe(
      'The Academy of Arts and Sciences',
    );
    expect(displayName('MARTIN LUTHER KING JR LEARNING CTR')).toBe(
      'Martin Luther King Jr Learning Ctr',
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

  it('changes only case, so the text keeps its length and letters', () => {
    const names = [
      'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
      "O'NEILL INT'L ACADEMY",
      'İSTANBUL ACADEMY',
      '21ST CENTURY 6TH GRADE CENTER',
      '',
      '64113',
    ];
    for (const name of names) {
      const shown = displayName(name);
      expect(shown).toHaveLength(name.length);
      expect(shown.toUpperCase()).toBe(name.toUpperCase());
    }
  });
});
