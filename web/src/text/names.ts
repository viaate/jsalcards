/**
 * School, district and place names as the page shows them.
 *
 * About four in ten names in the school directory are written in capitals
 * ("THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS"). Those are shown in title case
 * ("The Pembroke Hill School - Wornall Campus"). Only the case of letters
 * changes: no word is added, dropped, reordered or spelled out, and the text
 * keeps its length, so match ranges found in the raw name still fit the shown
 * one. A name that has any lowercase letter is shown exactly as written.
 *
 * Within a capitalized name:
 * - acronyms stay in capitals: words with no vowel (PS, HS, JHS, LLC), a list
 *   of common ones that have vowels (KIPP, STEM, ES, ISD), and Roman numerals;
 * - single letters stay capitals (initials such as the H in JOHN H GLENN);
 * - the usual short forms with no vowel are title-cased (ST, JR, CTR, SCH);
 * - "of", "the", "and", "at", "for", "in", "on" and "to" are lowercase after
 *   the first word;
 * - McX names become McX (MCKINLEY: McKinley);
 * - after an apostrophe, one or two letters are lowercase (MARY'S, INT'L)
 *   and a longer word is title-cased (O'NEILL: O'Neill);
 * - ordinal endings after a number are lowercase (21ST: 21st).
 */

/** Capital letter runs. */
const WORD = /\p{Lu}+/gu;
const LOWER = /\p{Ll}/u;
const ONE_LETTER = /^\p{Lu}$/u;
const VOWEL = /[AEIOUYÀ-ÖØ-Ý]/u;
const APOSTROPHE = /['’`]/u;
const DIGIT = /\d/u;
const ROMAN = /^(?:X{0,3})(?:IX|IV|V?I{0,3})$/u;

/** Acronyms with a vowel, common in school names, kept in capitals. */
const ACRONYMS: ReadonlySet<string> = new Set([
  'ALC',
  'AME',
  'CTE',
  'DAEP',
  'DAR',
  'DBA',
  'ES',
  'ESD',
  'IB',
  'IDEA',
  'IS',
  'ISD',
  'JJAEP',
  'KIPP',
  'NYC',
  'ROTC',
  'JROTC',
  'SDA',
  'STEAM',
  'STEM',
  'USA',
  'USD',
  'YMCA',
  'YWCA',
]);

/** Short forms with no vowel that are words, not acronyms: title-cased. */
const SHORT_FORMS: ReadonlySet<string> = new Set([
  'BLVD',
  'CH',
  'CNTR',
  'CTR',
  'DR',
  'DRS',
  'FT',
  'HTRS',
  'JR',
  'KDGN',
  'LRN',
  'LRNG',
  'LTD',
  'MC',
  'MT',
  'MTN',
  'RCH',
  'RD',
  'SCH',
  'SCHL',
  'SCHS',
  'SGT',
  'SR',
  'ST',
  'STS',
  'WM',
]);

/** Lowercase after the first word. */
const SMALL_WORDS: ReadonlySet<string> = new Set([
  'AND',
  'AT',
  'FOR',
  'IN',
  'OF',
  'ON',
  'THE',
  'TO',
]);

/** Ordinal endings after a number. */
const ORDINALS: ReadonlySet<string> = new Set(['ST', 'ND', 'RD', 'TH']);

/** `text` in lowercase, character by character, keeping any character whose lowercase is longer. */
function lower(text: string): string {
  let out = '';
  for (const char of text) {
    const small = char.toLowerCase();
    out += small.length === char.length ? small : char;
  }
  return out;
}

/** First letter kept, the rest lowercase. */
function title(word: string): string {
  const first = String.fromCodePoint(word.codePointAt(0) ?? 0);
  return first + lower(word.slice(first.length));
}

function caseWord(word: string, before: string, first: boolean): string {
  if (APOSTROPHE.test(before)) return word.length <= 2 ? lower(word) : title(word);
  if (DIGIT.test(before)) return ORDINALS.has(word) ? lower(word) : word;
  if (ONE_LETTER.test(word)) return word;
  // McKinley: the M, a lowercase c, then the rest title-cased.
  if (word.length > 3 && word.startsWith('MC')) {
    return title(word.slice(0, 2)) + title(word.slice(2));
  }
  if (ACRONYMS.has(word) || ROMAN.test(word)) return word;
  if (SHORT_FORMS.has(word)) return title(word);
  if (!VOWEL.test(word)) return word;
  if (!first && SMALL_WORDS.has(word)) return lower(word);
  return title(word);
}

/** A name as shown: title case when it is written in capitals, else as written. */
export function displayName(raw: string): string {
  if (LOWER.test(raw)) return raw;
  let first = true;
  return raw.replace(WORD, (word: string, at: number) => {
    const shown = caseWord(word, raw.charAt(at - 1), first);
    first = false;
    return shown;
  });
}
