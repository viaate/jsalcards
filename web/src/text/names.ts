/**
 * School, district and place names as the page shows them.
 *
 * NCES writes about four in ten school names in capitals ("THE PEMBROKE HILL
 * SCHOOL - WORNALL CAMPUS") and shortens many ("Ross El Sch", "Lancaster
 * Catholic HS"). The page shows them in title case, with the standard
 * shortenings spelled out ("The Pembroke Hill School - Wornall Campus",
 * "Ross Elementary School", "Lancaster Catholic High School"). No word is
 * added, dropped or moved: each shortening becomes the words it stands for,
 * in its place. Search matches the names as NCES writes them; `shownRanges`
 * carries a match in the written name over to the shown one.
 *
 * Case (`casedName`, the only change for places): a name written in capitals
 * is shown in title case; a name with any lowercase letter keeps its case.
 * Within a capitalized name:
 * - acronyms stay in capitals: words with no vowel (PS, HS, JHS, LLC), a list
 *   of common ones that have vowels (KIPP, STEM, ISD), and Roman numerals;
 * - single letters stay capitals (initials such as the H in JOHN H GLENN);
 * - the usual short forms with no vowel are title-cased (ST, JR, CTR, SCH);
 * - "of", "the", "and", "at", "for", "in", "on" and "to" are lowercase after
 *   the first word;
 * - McX names become McX (MCKINLEY: McKinley);
 * - after an apostrophe, one or two letters are lowercase (MARY'S, INT'L)
 *   and a longer word is title-cased (O'NEILL: O'Neill);
 * - ordinal endings after a number are lowercase (21ST: 21st).
 *
 * Shortenings (school and district names, `displayName`), each only where
 * NCES uses it for these words:
 * - Sch, Schl: School; Elem: Elementary; Acad: Academy; Ctr: Center;
 *   Chtr: Charter; Intrmd: Intermediate; Lrng: Learning; Hts: Heights;
 * - El: Elementary before School or another school, or at the end of a name
 *   or part of one ("Ross El Sch", "SMITH EL", "Drums El/MS"), never in "El
 *   Dorado" or "Beth El";
 * - in capitals: HS, MS, JHS, JH, SHS, JSHS, ES, CS (Charter School), PCS
 *   (Public Charter School); INT (Intermediate) and PRI (Primary) where a
 *   name ends with them;
 * - a numbered New York City school keeps its letters ("PS 15", "MS 45",
 *   "JHS 22"), and Mississippi's names keep MS, its state.
 * A period that ends a shortening goes with it ("ELEM." is "Elementary").
 */

/** Capital letter runs. */
const WORD = /\p{Lu}+/gu;
const LOWER = /\p{Ll}/u;
const ONE_LETTER = /^\p{Lu}$/u;
const VOWEL = /[AEIOUYÀ-ÖØ-Ý]/u;
const APOSTROPHE = /['’`]/u;
const DIGIT = /\d/u;
const ROMAN = /^(?:X{0,3})(?:IX|IV|V?I{0,3})$/u;
/** Words, for shortenings: letters and digits; everything else separates them. */
const TOKEN = /[\p{L}\p{N}]+/gu;
const LETTER_OR_DIGIT = /[\p{L}\p{N}]/u;

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

/**
 * A name in the case the page shows: title case when it is written in
 * capitals, else as written. Only the case of letters changes, so the text
 * keeps its length.
 */
export function casedName(raw: string): string {
  if (LOWER.test(raw)) return raw;
  let first = true;
  return raw.replace(WORD, (word: string, at: number) => {
    const shown = caseWord(word, raw.charAt(at - 1), first);
    first = false;
    return shown;
  });
}

/** What is known about where a name is from. */
export interface NameHint {
  /** The USPS code of the state the school or district is in, when known. */
  readonly state?: string | null;
}

/** One stretch of a written name and how it is shown. */
export interface NamePiece {
  /** [from, to) in the written name. */
  readonly from: number;
  readonly to: number;
  /** The stretch as shown: the same letters in the shown case, or the words a shortening stands for. */
  readonly text: string;
  /** Whether `text` spells out a shortening. */
  readonly spelled: boolean;
}

interface Token {
  readonly text: string;
  readonly upper: string;
  readonly from: number;
  readonly to: number;
}

/** Words that mean school. */
const SCHOOL_WORDS: ReadonlySet<string> = new Set(['SCH', 'SCHL', 'SCHOOL']);
/**
 * Words before which El is Elementary: School, or another school sharing the
 * name ("Drums El/MS"). The search index reads El the same way
 * (src/search/normalize.ts).
 */
const EL_BEFORE: ReadonlySet<string> = new Set([
  ...SCHOOL_WORDS,
  'MS',
  'HS',
  'JH',
  'MIDDLE',
  'PRIMARY',
]);
/** Words after which PRI is Primary. */
const PRIMARY_BEFORE: ReadonlySet<string> = new Set([...SCHOOL_WORDS, 'CTR', 'CENTER']);
/** Words El follows as a name of its own ("Beth El"). */
const EL_AS_NAME: ReadonlySet<string> = new Set(['BET', 'BETH']);
/** Marks that end a part of a name, after which El is Elementary ("Drums El/MS"). */
const PART_END = /^[-/(),;]$/u;

/** Shortenings spelled out wherever NCES writes them, in any case. */
const ALWAYS: Readonly<Record<string, string>> = {
  SCH: 'School',
  SCHL: 'School',
  SCHS: 'Schools',
  ELEM: 'Elementary',
  ACAD: 'Academy',
  CTR: 'Center',
  CNTR: 'Center',
  CHTR: 'Charter',
  INTRMD: 'Intermediate',
  LRNG: 'Learning',
  HTS: 'Heights',
  HGTS: 'Heights',
};

/** The first character after a token that is not a space, past one period; '' at the end. */
function markAfter(raw: string, token: Token): string {
  let at = token.to;
  if (raw[at] === '.') at++;
  while (at < raw.length && /\s/u.test(raw[at] ?? '')) at++;
  return raw[at] ?? '';
}

/** What a word stands for, when it is a shortening here, else null. */
function spellOut(raw: string, tokens: readonly Token[], i: number, hint: NameHint): string | null {
  const token = tokens[i];
  if (token === undefined) return null;
  const { upper } = token;
  const always = ALWAYS[upper];
  if (always !== undefined) return always;
  const capitals = token.text === upper;
  const first = i === 0;
  const next = tokens[i + 1];
  const last = next === undefined;
  const before = tokens[i - 1];
  // "PS 15", "MS 45", "JHS 22": a numbered school keeps its letters.
  const numbered =
    next !== undefined && /^\d/u.test(next.text) && /^\s+$/u.test(raw.slice(token.to, next.from));
  switch (upper) {
    case 'EL': {
      if (first || (before !== undefined && EL_AS_NAME.has(before.upper))) return null;
      if (last || PART_END.test(markAfter(raw, token))) return 'Elementary';
      return EL_BEFORE.has(next.upper) ? 'Elementary' : null;
    }
    case 'ES':
      return capitals && !first ? 'Elementary School' : null;
    case 'HS':
      return capitals && !numbered ? 'High School' : null;
    case 'MS':
      return capitals && !numbered && hint.state !== 'MS' && !SCHOOL_WORDS.has(next?.upper ?? '')
        ? 'Middle School'
        : null;
    case 'JHS':
      return capitals && !numbered ? 'Junior High School' : null;
    case 'JH':
      return capitals && !first ? 'Junior High' : null;
    case 'SHS':
      // "J-SHS" is a shortening of its own.
      return capitals && !first && /\s/u.test(raw[token.from - 1] ?? '')
        ? 'Senior High School'
        : null;
    case 'JSHS':
      return capitals && !first ? 'Junior-Senior High School' : null;
    case 'CS':
      return capitals && !first && !numbered ? 'Charter School' : null;
    case 'PCS':
      return capitals && !first ? 'Public Charter School' : null;
    case 'INT':
      return capitals && last && raw[token.to] !== "'" && !first ? 'Intermediate' : null;
    case 'PRI':
      return !first && (last || PRIMARY_BEFORE.has(next.upper)) ? 'Primary' : null;
    default:
      return null;
  }
}

/**
 * A name cut into the stretches the page shows it as: the written text in its
 * shown case, and each shortening spelled out. The pieces cover the written
 * name in order.
 */
export function nameLayout(raw: string, hint: NameHint = {}): NamePiece[] {
  const cased = casedName(raw);
  const tokens: Token[] = [];
  for (const match of raw.matchAll(TOKEN)) {
    const from = match.index;
    tokens.push({
      text: match[0],
      upper: match[0].toUpperCase(),
      from,
      to: from + match[0].length,
    });
  }
  const pieces: NamePiece[] = [];
  let at = 0;
  tokens.forEach((token, i) => {
    const words = spellOut(raw, tokens, i, hint);
    if (words === null) return;
    // "ELEM." is "Elementary": the period goes with the shortening, unless a word follows it at once.
    const to =
      raw[token.to] === '.' && !LETTER_OR_DIGIT.test(raw[token.to + 1] ?? '')
        ? token.to + 1
        : token.to;
    if (token.from > at) {
      pieces.push({ from: at, to: token.from, text: cased.slice(at, token.from), spelled: false });
    }
    pieces.push({ from: token.from, to, text: words, spelled: true });
    at = to;
  });
  if (at < raw.length) {
    pieces.push({ from: at, to: raw.length, text: cased.slice(at), spelled: false });
  }
  return pieces;
}

/** A school or district name as the page shows it. */
export function displayName(raw: string, hint: NameHint = {}): string {
  return nameLayout(raw, hint)
    .map((piece) => piece.text)
    .join('');
}

/**
 * Ranges of a written name ([start, end), such as the parts a search matched)
 * as ranges of the shown name. Within a spelled-out shortening, a match of
 * its first letters marks the same letters of the words when they start the
 * same way ("Sc" of "Sch" is "Sc" of "School"), and the whole words otherwise.
 */
export function shownRanges(
  layout: readonly NamePiece[],
  raw: string,
  ranges: readonly (readonly [number, number])[],
): [number, number][] {
  const out: [number, number][] = [];
  for (const [start, end] of ranges) {
    let shownAt = 0;
    for (const piece of layout) {
      const from = Math.max(start, piece.from);
      const to = Math.min(end, piece.to);
      if (to > from) {
        if (!piece.spelled) {
          out.push([shownAt + from - piece.from, shownAt + to - piece.from]);
        } else {
          const written = raw.slice(piece.from, piece.to).replace(/\.$/u, '');
          const prefix =
            from === piece.from &&
            to - from < written.length &&
            piece.text.toUpperCase().startsWith(written.toUpperCase());
          out.push([shownAt, shownAt + (prefix ? to - from : piece.text.length)]);
        }
      }
      shownAt += piece.text.length;
    }
  }
  out.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const merged: [number, number][] = [];
  for (const range of out) {
    const previous = merged[merged.length - 1];
    if (previous !== undefined && range[0] <= previous[1]) {
      previous[1] = Math.max(previous[1], range[1]);
    } else merged.push([range[0], range[1]]);
  }
  return merged;
}
