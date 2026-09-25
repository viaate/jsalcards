// @vitest-environment node
import { describe, expect, it } from 'vitest';

import {
  MAX_TOKEN_LENGTH,
  canonicalLength,
  indexTokens,
  isNumericToken,
  normalizeText,
  queryExpansions,
  scanAscii,
  tokenize,
  typoBudget,
} from '../normalize';
import { mulberry32 } from './random';

describe('tokenize', () => {
  it.each([
    ['Lancaster High School', ['lancaster', 'high', 'school']],
    ['  LANCASTER   high\tSCHOOL \n', ['lancaster', 'high', 'school']],
    ['Cañon City', ['canon', 'city']],
    ['Española', ['espanola']],
    ['École Française', ['ecole', 'francaise']],
    ['Müller Straße', ['muller', 'strasse']],
    ['Æsop Œuvre Øre', ['aesop', 'oeuvre', 'ore']],
    ["O'Neill", ['oneill']],
    ['O’Neill', ['oneill']],
    ["St. Mary's", ['st', 'marys']],
    ['St.Louis', ['st', 'louis']],
    ['P.S. 123', ['ps', '123']],
    ['U.S.A.', ['usa']],
    ['J.F.K. Middle', ['jfk', 'middle']],
    ['Arts & Sciences', ['arts', 'and', 'sciences']],
    ['Winston-Salem', ['winston', 'salem']],
    ['Lancaster, PA', ['lancaster', 'pa']],
    ['Jr./Sr. High', ['jr', 'sr', 'high']],
    ['K-8 School', ['k', '8', 'school']],
    ['17601-1234', ['17601', '1234']],
    ['#1 School (North)', ['1', 'school', 'north']],
    ['🙂', []],
    ['🏫 School 🏫', ['school']],
    ['👨\u200d👩\u200d👧 family', ['family']],
    ['学校 school', ['学校', 'school']],
    ['İstanbul', ['istanbul']],
    ['½ Moon', ['1', '2', 'moon']],
    ['non\u00a0breaking', ['non', 'breaking']],
    ['soft\u00adhyphen', ['softhyphen']],
    ['', []],
    ['   ', []],
    ['---', []],
    ['...', []],
  ])('%j gives %j', (text, tokens) => {
    expect(tokenize(text)).toEqual(tokens);
  });

  it('cuts very long tokens', () => {
    const tokens = tokenize('x'.repeat(500));
    expect(tokens).toEqual(['x'.repeat(MAX_TOKEN_LENGTH)]);
  });

  it('gives the same tokens on the fast and the span paths', () => {
    const random = mulberry32(7);
    const alphabet = "abcXYZ019 .,'&-/()#\t";
    for (let n = 0; n < 2000; n++) {
      let text = '';
      const len = Math.floor(random() * 30);
      for (let i = 0; i < len; i++) text += alphabet[Math.floor(random() * alphabet.length)] ?? '';
      expect(tokenize(text, [])).toEqual(tokenize(text));
    }
  });

  it('maps each token back onto the source text', () => {
    const spans: number[][] = [];
    const text = "Hans O'Neill-Straße";
    const tokens = tokenize(text, spans);
    expect(tokens).toEqual(['hans', 'oneill', 'strasse']);
    expect(spans[0]).toEqual([0, 1, 2, 3, 4]);
    // "oneill": the apostrophe is skipped, so "on" ends after "O'N".
    expect(spans[1]?.[0]).toBe(5);
    expect(spans[1]?.[2]).toBe(8);
    // "ß" becomes two characters that both end after the ß.
    const strasse = spans[2] ?? [];
    expect(text.slice(strasse[0], strasse[7])).toBe('Straße');
    expect(strasse[5]).toBe(strasse[6]);
  });
});

describe('scanAscii', () => {
  it('matches tokenize on random ASCII text', () => {
    const random = mulberry32(11);
    const alphabet = "abcdeXYZ0189 .,.'`&-_/()#\t\n";
    const buf = new Uint16Array(MAX_TOKEN_LENGTH);
    for (let n = 0; n < 3000; n++) {
      let text = '';
      const len = Math.floor(random() * 60);
      for (let i = 0; i < len; i++) text += alphabet[Math.floor(random() * alphabet.length)] ?? '';
      if (random() < 0.05) text += 'q'.repeat(50);
      const scanned: string[] = [];
      const ok = scanAscii(text, 0, text.length, buf, {
        token(chars, length) {
          scanned.push(String.fromCharCode(...chars.subarray(0, length)));
        },
      });
      expect(ok).toBe(true);
      expect(scanned).toEqual(tokenize(text));
    }
  });

  it('gives up on non-ASCII text', () => {
    const buf = new Uint16Array(MAX_TOKEN_LENGTH);
    const ok = scanAscii('Cañon', 0, 5, buf, { token: () => undefined });
    expect(ok).toBe(false);
  });

  it('scans only the given range', () => {
    const buf = new Uint16Array(MAX_TOKEN_LENGTH);
    const seen: string[] = [];
    scanAscii('aa bb cc', 3, 5, buf, {
      token(chars, length) {
        seen.push(String.fromCharCode(...chars.subarray(0, length)));
      },
    });
    expect(seen).toEqual(['bb']);
  });
});

describe('abbreviations', () => {
  it.each([
    ['Lancaster HS', ['lancaster', 'hs', 'high', 'school'], 3],
    ['Hans Herr El Sch', ['hans', 'herr', 'el', 'elementary', 'school', 'sch'], 4],
    ['El Paso', ['el', 'paso'], 2],
    ["St. Mary's", ['st', 'saint', 'street', 'marys'], 2],
    ['Lincoln Elem', ['lincoln', 'elem', 'elementary'], 2],
    ['Lancaster ISD', ['lancaster', 'isd', 'independent', 'school', 'district'], 4],
    ['Walla Walla', ['walla'], 2],
    ['Lancaster High School', ['lancaster', 'high', 'school'], 3],
  ])('%j indexes as %j and counts %i words', (name, tokens, words) => {
    const t = tokenize(name);
    expect(indexTokens(t)).toEqual(tokens);
    expect(canonicalLength(t)).toBe(words);
  });

  it('expands query abbreviations', () => {
    expect(queryExpansions('hs')).toEqual([['high', 'school']]);
    expect(queryExpansions('st')).toEqual([['saint'], ['street']]);
    expect(queryExpansions('lancaster')).toEqual([]);
  });
});

describe('typo budget', () => {
  it.each([
    ['abc', 0],
    ['abcd', 1],
    ['abcdefg', 1],
    ['abcdefgh', 2],
    ['lancaster', 2],
    ['17601', 0],
    ['12345678', 0],
  ])('%j allows %i edits', (token, edits) => {
    expect(typoBudget(token)).toBe(edits);
  });

  it('knows numbers', () => {
    expect(isNumericToken('17601')).toBe(true);
    expect(isNumericToken('ps1')).toBe(false);
    expect(isNumericToken('')).toBe(false);
  });

  it('normalizes text for display comparisons', () => {
    expect(normalizeText('  Lancaster,  PA ')).toBe('lancaster pa');
  });
});
