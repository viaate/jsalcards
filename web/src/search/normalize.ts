/**
 * Text normalization shared by the index builder, the worker's index loader
 * and the query parser. The builder and the worker must produce identical
 * tokens for the same text, so this module is the single definition, and
 * NORMALIZER_VERSION is written into every index: a worker refuses an index
 * built with different rules.
 *
 * Rules:
 * - Case and accents fold away: "Cañon City" and "canon city" are the same.
 * - Letters and digits of any script make up tokens; everything else splits.
 * - Apostrophes join ("O'Neill" is "oneill"); "&" is the word "and".
 * - A period joins single letters ("P.S. 123" is "ps 123", "U.S." is "us")
 *   and otherwise splits ("St.Louis" is "st louis").
 *
 * This module has no imports, so Node can load it directly from the builder.
 */

/** Bump whenever a change here would tokenize any text differently. */
export const NORMALIZER_VERSION = 1;

/** Longest token kept, in UTF-16 code units. Longer runs are cut. */
export const MAX_TOKEN_LENGTH = 40;

const SEP = 0;
const KEEP = 1;
const UPPER = 2;
const DROP = 3;
const PERIOD = 4;
const AMP = 5;

const ASCII_CLASS = new Uint8Array(128);
for (let c = 0x30; c <= 0x39; c++) ASCII_CLASS[c] = KEEP;
for (let c = 0x61; c <= 0x7a; c++) ASCII_CLASS[c] = KEEP;
for (let c = 0x41; c <= 0x5a; c++) ASCII_CLASS[c] = UPPER;
ASCII_CLASS[0x27] = DROP; // '
ASCII_CLASS[0x60] = DROP; // `
ASCII_CLASS[0x2e] = PERIOD; // .
ASCII_CLASS[0x26] = AMP; // &

/** Code points that act as apostrophes and join the letters around them. */
const APOSTROPHES = new Set([0x2018, 0x2019, 0x201b, 0x02bc, 0x02b9, 0x00b4, 0xff07, 0x2032]);

/** Letters that Unicode decomposition leaves alone but people type in ASCII. */
const SPECIAL_FOLDS: Readonly<Record<string, string>> = {
  ß: 'ss',
  ẞ: 'ss',
  æ: 'ae',
  œ: 'oe',
  ø: 'o',
  ł: 'l',
  đ: 'd',
  ð: 'd',
  þ: 'th',
  ı: 'i',
  ħ: 'h',
  ŧ: 't',
  ŋ: 'n',
  ĸ: 'k',
  ſ: 's',
};

const LETTER_OR_DIGIT = /[\p{L}\p{N}]/u;
const MARK = /\p{M}/u;
const FORMAT = /\p{Cf}/u;

/**
 * How one non-ASCII code point folds: a string of token characters, '' when
 * the code point vanishes (marks, joiners, apostrophes) or ' ' when it splits
 * tokens. Results can mix, such as '1 2' for '½'.
 */
const foldCache = new Map<number, string>();

function foldCodePoint(cp: number): string {
  const cached = foldCache.get(cp);
  if (cached !== undefined) return cached;
  let out: string;
  if (APOSTROPHES.has(cp)) {
    out = '';
  } else {
    const ch = String.fromCodePoint(cp);
    if (MARK.test(ch) || FORMAT.test(ch)) {
      out = '';
    } else {
      out = '';
      for (const part of ch.normalize('NFKD').toLowerCase()) {
        if (MARK.test(part)) continue;
        const special = SPECIAL_FOLDS[part];
        if (special !== undefined) out += special;
        else if (LETTER_OR_DIGIT.test(part)) out += part;
        else out += ' ';
      }
      if (out.length === 0) out = ' ';
    }
  }
  foldCache.set(cp, out);
  return out;
}

// Every UTF-16 unit below 128 is ASCII, control characters included.
// eslint-disable-next-line no-control-regex
const PURE_ASCII = /^[\x00-\x7f]*$/;

/**
 * Splits text into normalized tokens, in order, duplicates kept.
 *
 * `spans`, when given, receives for each token its UTF-16 start in `text`
 * followed by, for each token character, the index just past the source
 * character it came from. Highlighting uses it to map a matched prefix back
 * onto the original string.
 */
export function tokenize(text: string, spans?: number[][]): string[] {
  const tokens: string[] = [];
  const n = text.length;
  let cur = '';
  let run = 0; // token characters since the last split or joining period
  let map: number[] | null = null;

  const finish = (): void => {
    if (cur.length > 0) {
      tokens.push(cur.length > MAX_TOKEN_LENGTH ? cur.slice(0, MAX_TOKEN_LENGTH) : cur);
      if (spans && map) spans.push(map.slice(0, MAX_TOKEN_LENGTH + 1));
    }
    cur = '';
    run = 0;
    map = null;
  };
  const append = (chars: string, start: number, end: number): void => {
    if (cur.length === 0 && spans) map = [start];
    cur += chars;
    run += chars.length;
    if (map) for (let k = chars.length; k > 0; k--) map.push(end);
  };

  if (PURE_ASCII.test(text) && !spans) {
    // Fast path for the common case: ASCII, no highlight spans needed.
    const lower = text.toLowerCase();
    let segStart = -1;
    for (let i = 0; i < n; i++) {
      const cls = ASCII_CLASS[text.charCodeAt(i)] ?? SEP;
      if (cls === KEEP || cls === UPPER) {
        if (segStart < 0) segStart = i;
        run++;
        continue;
      }
      if (segStart >= 0) {
        cur += lower.slice(segStart, i);
        segStart = -1;
      }
      if (cls === DROP) continue;
      if (cls === PERIOD) {
        if (run === 1) {
          run = 0;
          continue;
        }
        finish();
        continue;
      }
      finish();
      if (cls === AMP) tokens.push('and');
    }
    if (segStart >= 0) cur += lower.slice(segStart, n);
    finish();
    return tokens;
  }

  for (let i = 0; i < n;) {
    const cp = text.codePointAt(i) ?? 0;
    const width = cp > 0xffff ? 2 : 1;
    const next = i + width;
    if (cp < 128) {
      const cls = ASCII_CLASS[cp] ?? SEP;
      if (cls === KEEP) append(text[i] ?? '', i, next);
      else if (cls === UPPER) append(String.fromCharCode(cp + 32), i, next);
      else if (cls === PERIOD) {
        if (run === 1) run = 0;
        else finish();
      } else if (cls === SEP) finish();
      else if (cls === AMP) {
        finish();
        tokens.push('and');
        if (spans) spans.push([i, next, next, next]);
      }
      // DROP: nothing
    } else {
      const folded = foldCodePoint(cp);
      for (const ch of folded) {
        if (ch === ' ') finish();
        else append(ch, i, next);
      }
    }
    i = next;
  }
  finish();
  return tokens;
}

/** Receives tokens from scanAscii. */
export interface TokenSink {
  /** A token's characters are chars[0, length); the buffer is reused for the next token. */
  token(chars: Uint16Array, length: number): void;
}

/** Character codes of "and", which "&" stands for. */
const AND_CHARS = Uint16Array.of(0x61, 0x6e, 0x64);

/**
 * Tokenizes text[start, end) exactly as tokenize() does, but for ASCII text
 * only and without making strings: each token's character codes go to
 * `sink` through `buf` (at least MAX_TOKEN_LENGTH long). Returns false as
 * soon as it meets a non-ASCII character; tokens already sent should then be
 * discarded and the text passed to tokenize() instead.
 */
export function scanAscii(
  text: string,
  start: number,
  end: number,
  buf: Uint16Array,
  sink: TokenSink,
): boolean {
  let len = 0;
  let run = 0;
  for (let i = start; i < end; i++) {
    const c = text.charCodeAt(i);
    if (c >= 128) return false;
    const cls = ASCII_CLASS[c] ?? SEP;
    if (cls === KEEP || cls === UPPER) {
      if (len < MAX_TOKEN_LENGTH) buf[len] = cls === UPPER ? c + 32 : c;
      len++;
      run++;
    } else if (cls === DROP) {
      // Apostrophes join.
    } else if (cls === PERIOD && run === 1) {
      run = 0;
    } else {
      if (len > 0) sink.token(buf, len < MAX_TOKEN_LENGTH ? len : MAX_TOKEN_LENGTH);
      len = 0;
      run = 0;
      if (cls === AMP) sink.token(AND_CHARS, 3);
    }
  }
  if (len > 0) sink.token(buf, len < MAX_TOKEN_LENGTH ? len : MAX_TOKEN_LENGTH);
  return true;
}

/** Normalized text: tokens joined by single spaces. */
export function normalizeText(text: string): string {
  return tokenize(text).join(' ');
}

/** True when a normalized token is all ASCII digits. */
export function isNumericToken(token: string): boolean {
  if (token.length === 0) return false;
  for (let i = 0; i < token.length; i++) {
    const c = token.charCodeAt(i);
    if (c < 0x30 || c > 0x39) return false;
  }
  return true;
}

/**
 * Abbreviations common in school, district and place names, with what they
 * stand for. Names are indexed with both forms, and a query abbreviation also
 * matches the full words, so "Lancaster HS", "lancaster high school" and
 * "lancaster hs" all find each other.
 */
const ABBREVIATION_RULES: readonly (readonly [string, string])[] = [
  ['hs', 'high school'],
  ['ms', 'middle school'],
  ['es', 'elementary school'],
  ['jhs', 'junior high school'],
  ['shs', 'senior high school'],
  ['jshs', 'junior senior high school'],
  ['el sch', 'elementary school'],
  ['elem', 'elementary'],
  ['sch', 'school'],
  ['schl', 'school'],
  ['ps', 'public school'],
  ['is', 'intermediate school'],
  ['cs', 'charter school'],
  ['st', 'saint'],
  ['st', 'street'],
  ['ste', 'sainte'],
  ['mt', 'mount'],
  ['mtn', 'mountain'],
  ['ft', 'fort'],
  ['pt', 'point'],
  ['jr', 'junior'],
  ['sr', 'senior'],
  ['acad', 'academy'],
  ['ctr', 'center'],
  ['cntr', 'center'],
  ['intermed', 'intermediate'],
  ['prep', 'preparatory'],
  ['tech', 'technical'],
  ['tech', 'technology'],
  ['voc', 'vocational'],
  ['alt', 'alternative'],
  ['comm', 'community'],
  ['educ', 'education'],
  ['univ', 'university'],
  ['hts', 'heights'],
  ['twp', 'township'],
  ['co', 'county'],
  ['cnty', 'county'],
  ['dist', 'district'],
  ['sd', 'school district'],
  ['isd', 'independent school district'],
  ['usd', 'unified school district'],
  ['cisd', 'consolidated independent school district'],
  ['cusd', 'community unit school district'],
  ['ccsd', 'community consolidated school district'],
];

/** An abbreviation and what it stands for, as token sequences. */
export interface AbbreviationRule<T = string> {
  readonly short: readonly T[];
  readonly long: readonly T[];
}

export const ABBREVIATIONS: readonly AbbreviationRule[] = ABBREVIATION_RULES.map(
  ([short, long]) => ({ short: short.split(' '), long: long.split(' ') }),
);

/** Rules keyed by the first token of their short form. */
const RULES_BY_FIRST = new Map<string, AbbreviationRule[]>();
for (const rule of ABBREVIATIONS) {
  const first = rule.short[0] ?? '';
  const list = RULES_BY_FIRST.get(first);
  if (list) list.push(rule);
  else RULES_BY_FIRST.set(first, [rule]);
}

/** Single-token abbreviations and the word lists a query token also stands for. */
const QUERY_EXPANSIONS = new Map<string, (readonly string[])[]>();
for (const rule of ABBREVIATIONS) {
  if (rule.short.length !== 1) continue;
  const key = rule.short[0] ?? '';
  const list = QUERY_EXPANSIONS.get(key);
  if (list) list.push(rule.long);
  else QUERY_EXPANSIONS.set(key, [rule.long]);
}

/** Rules whose short form starts with a token, or undefined. */
export type RuleLookup<T> = (token: T) => readonly AbbreviationRule<T>[] | undefined;

function matchesAt<T>(tokens: ArrayLike<T>, to: number, at: number, words: readonly T[]): boolean {
  if (at + words.length > to) return false;
  for (let k = 0; k < words.length; k++) if (tokens[at + k] !== words[k]) return false;
  return true;
}

/**
 * Appends to `out` the tokens a name is indexed under: its own tokens
 * (tokens[from, to)), deduplicated, plus the full words of every
 * abbreviation in it. Generic so the worker can run the same rules over
 * token ids.
 */
export function expandTokens<T>(
  tokens: ArrayLike<T>,
  from: number,
  to: number,
  rulesFor: RuleLookup<T>,
  out: T[],
): void {
  for (let i = from; i < to; i++) {
    const t = tokens[i] as T;
    if (!out.includes(t)) out.push(t);
    const rules = rulesFor(t);
    if (!rules) continue;
    for (const rule of rules) {
      if (!matchesAt(tokens, to, i, rule.short)) continue;
      for (const w of rule.long) if (!out.includes(w)) out.push(w);
    }
  }
}

/**
 * Word count of tokens[from, to) once abbreviations are spelled out, so
 * "Lancaster HS" and "lancaster high school" both count 3. Capped at 255.
 */
export function expandedLength<T>(
  tokens: ArrayLike<T>,
  from: number,
  to: number,
  rulesFor: RuleLookup<T>,
): number {
  let count = 0;
  for (let i = from; i < to;) {
    const rules = rulesFor(tokens[i] as T);
    let step = 1;
    let words = 1;
    if (rules) {
      for (const rule of rules) {
        if (matchesAt(tokens, to, i, rule.short)) {
          step = rule.short.length;
          words = rule.long.length;
          break;
        }
      }
    }
    count += words;
    i += step;
  }
  return Math.min(count, 255);
}

/** Abbreviation rules whose short form starts with a normalized token. */
export const rulesStartingWith: RuleLookup<string> = (t) => RULES_BY_FIRST.get(t);
const stringRules = rulesStartingWith;

/** expandTokens over normalized token strings. */
export function indexTokens(tokens: readonly string[]): string[] {
  const out: string[] = [];
  expandTokens(tokens, 0, tokens.length, stringRules, out);
  return out;
}

/** expandedLength over normalized token strings. */
export function canonicalLength(tokens: readonly string[]): number {
  return expandedLength(tokens, 0, tokens.length, stringRules);
}

/** The full-word forms a query token also stands for ("hs" gives [["high", "school"]]). */
export function queryExpansions(token: string): readonly (readonly string[])[] {
  return QUERY_EXPANSIONS.get(token) ?? [];
}

/**
 * Typo budget for a query token: 1 edit from 4 characters, 2 from 8, none
 * below 4 or for numbers (a ZIP one digit off is a different place).
 */
export function typoBudget(token: string): number {
  if (isNumericToken(token)) return 0;
  const n = token.length;
  if (n >= 8) return 2;
  if (n >= 4) return 1;
  return 0;
}
