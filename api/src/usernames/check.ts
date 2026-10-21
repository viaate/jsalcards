/**
 * Username rules and the blocklist check, shared by the Worker (the authority)
 * and the browser (instant feedback on the sign-up form).
 *
 * A username is 3-20 characters of a-z, 0-9 and underscore, compared without
 * case, not all digits, with no leading, trailing or double underscore.
 *
 * The blocklist (blocklist.ts) is matched against several readings of the
 * whole name, so that spelling tricks do not get past it:
 * - leet digits read as letters (0 o, 1 i or l, each 1 either way, 3 e, 4 a,
 *   5 s, 6 g, 7 t, 8 b, 9 g; a year standing apart is a number, but a 19xx
 *   next to a letter, or one underscore from a part of one or two letters, is
 *   read as letters too, since n1994 and n_1993_r spell a slur), and
 *   separately the letters alone with digits and underscores dropped;
 * - look-alike letters: an l read as i (not beside an i), ph read as f, and
 *   for the reserved names rn read as m. A reading with such a letter counts
 *   a substring match only over one of them (the rest is read as typed);
 * - at most 16 readings of a name's 1s and ls, however many it has, and the
 *   letters alone, ph as f and rn as m besides;
 * - stretched letters: a term matches where the name has the same letters in
 *   the same order with each run at least as long as the term's (fuuuuck, and
 *   boobs inside booooobs, but not boobs inside bobs);
 * - substring terms anywhere, also spelled backwards; whole-token terms as a
 *   whole part (between underscores or digits; each digit is a part of its
 *   own), as neighboring parts joined (a word spelled one letter at a time),
 *   as the whole name, or typed in one part with common affixes and short
 *   words (blocklist.ts tokenAffixes: my, the, big, lord, boy, gang and so
 *   on) filling the rest of it on either side (mybigterm, termlord), unless
 *   that part (or the term with its stretched letters) is allowlisted;
 * - an allowlist of innocent words (scunthorpe, cocktail, grape): a substring
 *   match is excused only when it lies wholly inside an allowlisted word typed
 *   in letters, with no underscore or digit at either edge of the term inside
 *   it, and only when the word stands as itself: on each side of the term
 *   where the word has fewer than 3 more letters (or on both sides, when it
 *   has 3 or fewer in all), the word must meet the name's edge, an underscore
 *   or a digit. So grape_juice and sussex_snow pass, while gangrape, lovessex
 *   (essex) or bigdicke (dicke) do not: the word's extra letters there would
 *   be read as part of the next word;
 * - number codes (1488 and its kin) in the name with its underscores removed.
 *
 * Reserved names (staff words, the site's name, the admin's name) are refused
 * whole, as any part of a name, typed with the same affixes (themod,
 * modteam, staffbot), and the long ones anywhere in a name, also
 * backwards (except inside an allowed word such as badminton), through the
 * same readings and the same stretched rule (staaaff, supportt, moddd), except
 * for the few real words that collide (mood, teem).
 *
 * CPU budget (the free Workers plan gives 10 ms per request): the file's lists
 * compile into an Aho-Corasick automaton and a trie over letter runs once per
 * isolate, and the Worker does that at startup (prepareBlocklist in
 * index.ts), never inside a request, then runs the check's code enough times
 * that a fresh isolate's first request runs compiled code (warmUp). The
 * admin's extra terms (at most MAX_ADMIN_TERMS of a kind, of at most 20
 * letters) are only filed, by their first two letters and in a small map
 * trie, once per isolate for each set of terms (compiledExtra). One check is
 * then at most 19 readings of at most 20 letters, each scanned once and
 * walked from each part's start in the trie: tens of microseconds, and about
 * a tenth of a millisecond for the slowest names anyone can register
 * (usernames.test.ts measures them, cold and with the most admin terms).
 */

import { BLOCKLIST } from './blocklist.ts';

export const MIN_USERNAME = 3;
export const MAX_USERNAME = 20;

/**
 * The most usernames one moderation scan request checks, and the most terms
 * the admin may keep of each kind. A page also ends early by the work it
 * holds (scanPage): sized from usernames.test.ts, a fresh isolate's first
 * page of the slowest names anyone can register, with this many terms of
 * every kind (each of the longest length) compiled inside the request, stays
 * under 5 ms of the free plan's 10 ms of CPU.
 */
export const SCAN_PAGE = 5;
export const MAX_ADMIN_TERMS = 50;

/**
 * A scan page's work budget, in readings (a check's work grows with the
 * readings of the name, at most 19), and what compiling the admin's terms
 * costs in the same units when the isolate has not compiled this set yet.
 */
export const SCAN_BUDGET = 40;
export const COMPILE_COST = 20;

/** The readings a check of the name makes, at most (parse): its 1s and ls read each way, and 3 more. */
export function checkCost(name: string): number {
  let bits = 0;
  for (const c of name) if (c === '1' || c === 'l' || c === 'L') bits++;
  return Math.min(MAX_READINGS, 2 ** bits) + 3;
}

/**
 * How many of the next `names` (at most SCAN_PAGE) one scan request checks:
 * as many as fit in SCAN_BUDGET after compiling the admin's terms if this
 * isolate has not yet (`extra`), and always at least one, so a scan always
 * moves on.
 */
export function scanPage(names: readonly string[], extra: ExtraTerms | null): number {
  let budget = SCAN_BUDGET - (extra !== null && !extraKnown(extra) ? COMPILE_COST : 0);
  let count = 0;
  for (const name of names.slice(0, SCAN_PAGE)) {
    const cost = checkCost(name);
    if (count > 0 && cost > budget) break;
    budget -= cost;
    count++;
  }
  return count;
}

export type UsernameProblem =
  | 'username_length'
  | 'username_chars'
  | 'username_digits'
  | 'username_underscores'
  | 'username_reserved'
  | 'username_blocked';

/** Extra terms the admin keeps in D1, applied on top of the file's lists. */
export interface ExtraTerms {
  readonly substring?: readonly string[];
  readonly token?: readonly string[];
  readonly allow?: readonly string[];
  /** Number codes, matched like the file's raw codes. */
  readonly raw?: readonly string[];
}

const LEET: Readonly<Record<string, string>> = {
  '0': 'o',
  '1': 'i',
  '3': 'e',
  '4': 'a',
  '5': 's',
  '6': 'g',
  '7': 't',
  '8': 'b',
  '9': 'g',
};

/** A list term as stored: lowercase letters only, leet digits read as letters, other marks dropped. */
export function termOf(text: string): string {
  const lower = text.toLowerCase();
  let out = '';
  for (let i = 0; i < lower.length; i++) {
    const c = LEET[lower[i]!] ?? lower[i]!;
    if (c >= 'a' && c <= 'z') out += c;
  }
  return out;
}

/** A number code as stored and matched: lowercase letters and digits, other marks dropped. */
export function rawOf(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]/g, '');
}

/** The name as stored and compared: trimmed and lowercased. */
export function canonicalUsername(name: string): string {
  return name.trim().toLowerCase();
}

/** The format rules alone (no lists): what is wrong, or null. */
export function usernameFormat(name: string): UsernameProblem | null {
  const text = canonicalUsername(name);
  if (text.length < MIN_USERNAME || text.length > MAX_USERNAME) return 'username_length';
  if (!/^[a-z0-9_]+$/.test(text)) return 'username_chars';
  if (/^\d+$/.test(text)) return 'username_digits';
  if (/^_|_$|__/.test(text)) return 'username_underscores';
  return null;
}

/** Runs of one letter longer than `keep` cut to `keep`. */
export function squeeze(text: string, keep: number): string {
  let out = '';
  let run = 0;
  for (let i = 0; i < text.length; i++) {
    run = i > 0 && text[i] === text[i - 1] ? run + 1 : 1;
    if (run <= keep) out += text[i];
  }
  return out;
}

/**
 * A name's skeleton: its letters with leet digits read as letters (1 as i),
 * l read as i, other digits and underscores dropped, and runs cut to one. Two
 * spellings of one name (Mean_Name, meanname, m3an_nam3) share it. The
 * Worker holds a released name by its skeleton's hash.
 */
export function usernameSkeleton(name: string): string {
  let out = '';
  for (const c of canonicalUsername(name)) out += c === 'l' ? 'i' : (LEET[c] ?? c);
  return squeeze(out.replace(/[^a-z]/g, ''), 1);
}

/**
 * Every skeleton a name is held or looked up by: usernameSkeleton (leet read
 * as letters), its letters alone (every digit and underscore dropped, l as
 * i, runs cut to one: meanname1, mean_name_2010 and 9meanname all give the
 * skeleton of meanname), and leet read only between two letters with other
 * digits dropped (m3anname7). The first is always the leet one.
 */
export function usernameSkeletons(name: string): string[] {
  const text = canonicalUsername(name);
  let letters = '';
  let mixed = '';
  for (let i = 0; i < text.length; i++) {
    const c = text[i]!;
    if (isLetter(c)) {
      const letter = c === 'l' ? 'i' : c;
      letters += letter;
      mixed += letter;
    } else if (LEET[c] !== undefined && isLetter(text[i - 1]) && isLetter(text[i + 1]))
      mixed += LEET[c];
  }
  const out = [usernameSkeleton(text), squeeze(letters, 1), squeeze(mixed, 1)];
  return [...new Set(out)].filter((skeleton) => skeleton.length > 0);
}

/**
 * The word an admin rename may add to the blocklist for everyone, from the
 * name it took away: its letters alone (digits and underscores dropped) with
 * runs cut to one, matched anywhere in a name when it has 4 letters or more,
 * as a whole word (alone or with an affix) when it has 3, and not at all
 * when it has fewer (too short to block on its own).
 */
export function renameTerm(name: string): { term: string; kind: 'substring' | 'token' } | null {
  const term = squeeze(canonicalUsername(name).replace(/[^a-z]/g, ''), 1);
  if (term.length >= 4) return { term: term.slice(0, MAX_USERNAME), kind: 'substring' };
  if (term.length === 3) return { term, kind: 'token' };
  return null;
}

const isLetter = (c: string | undefined): boolean => c !== undefined && c >= 'a' && c <= 'z';

/** Where a reading's letter came from, when not a letter of the name as typed. */
const DIGIT = -1;
const CONVERTED = -3;

/**
 * One reading of a name: its letters, and for each letter the run of letters
 * of the name as typed it came from (its index), DIGIT for a leet digit or
 * CONVERTED for a look-alike letter read as another, and its part.
 */
interface Reading {
  readonly text: string;
  readonly from: readonly number[];
  /** The part of the name each letter is in (parts are split at underscores and digits). */
  readonly unit: readonly number[];
  /** Has look-alike letters read as others: its substring matches count only over one of them. */
  readonly converted: boolean;
  /** Read for the reserved lists only (rn as m). */
  readonly reservedOnly: boolean;
  /** Counts a substring match only when it starts with a look-alike (ph as f: phuck, not gramophone). */
  readonly leadOnly: boolean;
  /** 1 where a whole-token match may start: a part's start, or just after an affix at its start (my+term). */
  readonly tokenStart: Uint8Array;
  /** 1 where a whole-token match may end: a part's end, or just before an affix at its end (term+lord). */
  readonly tokenEnd: Uint8Array;
}

/** The most readings of one name. */
const MAX_READINGS = 16;

/**
 * The digits of a year read only as a number. A year standing apart (2009,
 * snow_1999) is a number. A 19xx next to a letter, or one underscore from a
 * part of one or two letters, is read as letters too (n1994 and n_1993_r spell
 * a slur); 20xx never spells one (2 is no letter), so it is always a year.
 */
function yearDigits(text: string): boolean[] {
  const year = new Array<boolean>(text.length).fill(false);
  const near = (at: number, step: number): boolean => {
    if (isLetter(text[at])) return true;
    if (text[at] !== '_') return false;
    let letters = 0;
    for (let i = at + step; isLetter(text[i]); i += step) letters++;
    return letters >= 1 && letters <= 2;
  };
  for (const match of text.matchAll(/(?<!\d)(?:19|20)\d\d(?!\d)/g)) {
    const at = match.index;
    if (match[0].startsWith('19') && (near(at - 1, -1) || near(at + 4, 1))) continue;
    for (let i = at; i < at + 4; i++) year[i] = true;
  }
  return year;
}

/** A name taken apart once: its parts and its readings. */
interface Parsed {
  readonly text: string;
  /** Each part of the name as typed, and whether it is all letters. */
  readonly unitText: readonly string[];
  readonly unitPlain: readonly boolean[];
  readonly readings: readonly Reading[];
}

/** Every subset of `count` bits, or only none and all when there are too many. */
const masks = (count: number, full: boolean): number[] =>
  count === 0
    ? [0]
    : full
      ? Array.from({ length: 1 << count }, (_, m) => m)
      : [0, (1 << count) - 1];

/** A trie over words with runs cut to one, and which nodes end a word. */
interface WordTrie {
  readonly next: Int32Array;
  readonly end: Uint8Array;
}

function wordTrie(words: readonly string[]): WordTrie {
  const table = new Table(1 + words.reduce((sum, w) => sum + w.length, 0));
  const ends = words.map((word) => table.insert(squeeze(word, 1)));
  const end = new Uint8Array(table.size);
  for (const node of ends) end[node] = 1;
  return { next: table.next.slice(0, table.size * 26), end };
}

/**
 * Where a whole-token match may start and end in a reading: at each part's
 * start and end, and inside a part next to one of the file's tokenAffixes
 * that fills the rest of the part on that side (my+term, term+lord), or
 * several in a row (my+big+term), read with stretched letters. Walks of a
 * small trie from each part's two ends and from where an affix ends.
 */
function affixBounds(
  text: string,
  unit: readonly number[],
): { tokenStart: Uint8Array; tokenEnd: Uint8Array } {
  const n = text.length;
  const tokenStart = new Uint8Array(n);
  const tokenEnd = new Uint8Array(n);
  const { affix, affixBack } = file();
  for (let us = 0; us < n; us++) {
    if (us > 0 && unit[us] === unit[us - 1]) continue;
    let ue = us;
    while (ue + 1 < n && unit[ue + 1] === unit[us]) ue++;
    tokenStart[us] = 1;
    tokenEnd[ue] = 1;
    // Affixes may follow one another (my+big+term): walk again from each place one ends.
    for (let q = us; q < ue; q++) {
      if (tokenStart[q] !== 1) continue;
      let node = 0;
      let previous = -1;
      for (let p = q; p < ue; p++) {
        const c = text.charCodeAt(p) - 97;
        if (c !== previous) {
          node = affix.next[node * 26 + c]!;
          if (node === -1) break;
          previous = c;
        }
        if (affix.end[node] === 1) tokenStart[p + 1] = 1;
      }
    }
    for (let q = ue; q > us; q--) {
      if (tokenEnd[q] !== 1) continue;
      let node = 0;
      let previous = -1;
      for (let p = q; p > us; p--) {
        const c = text.charCodeAt(p) - 97;
        if (c !== previous) {
          node = affixBack.next[node * 26 + c]!;
          if (node === -1) break;
          previous = c;
        }
        if (affixBack.end[node] === 1) tokenEnd[p - 1] = 1;
      }
    }
  }
  return { tokenStart, tokenEnd };
}

function parse(text: string): Parsed {
  const n = text.length;
  const run = new Array<number>(n).fill(-1);
  const unitOf = new Array<number>(n).fill(-1);
  let runs = -1;
  let units = -1;
  for (let i = 0; i < n; i++) {
    const c = text[i]!;
    if (isLetter(c)) {
      if (!isLetter(text[i - 1])) {
        runs++;
        units++;
      }
      run[i] = runs;
      unitOf[i] = units;
    } else if (c !== '_') unitOf[i] = ++units;
  }
  const unitText = new Array<string>(units + 1).fill('');
  for (let i = 0; i < n; i++) if (unitOf[i]! >= 0) unitText[unitOf[i]!] += text[i]!;
  const unitPlain = unitText.map((t) => /^[a-z]+$/.test(t));
  const year = yearDigits(text);
  // Bits: each 1 (i or l), and each l not beside an i (l or i) nor in a word
  // whose l is never an i (blotch).
  const plainL = new Array<boolean>(n).fill(false);
  for (const word of file().lookAlikeAllow)
    for (let at = text.indexOf(word); at !== -1; at = text.indexOf(word, at + 1))
      plainL.fill(true, at, at + word.length);
  const oneBit = new Map<number, number>();
  const lBit = new Map<number, number>();
  for (let i = 0; i < n; i++) {
    if (text[i] === '1' && !year[i]) oneBit.set(i, oneBit.size);
    if (text[i] === 'l' && text[i - 1] !== 'i' && text[i + 1] !== 'i' && !plainL[i])
      lBit.set(i, lBit.size);
  }
  let ones: number[];
  let ls: number[];
  if (oneBit.size + lBit.size <= 4) {
    ones = masks(oneBit.size, true);
    ls = masks(lBit.size, true);
  } else {
    ones = masks(oneBit.size, oneBit.size <= 3);
    ls = masks(lBit.size, false);
    if (ones.length * ls.length > MAX_READINGS) ones = masks(oneBit.size, false);
  }
  const out = new Map<string, Reading>();
  const read = (
    one: number,
    l: number,
    options: { digits?: boolean; ph?: boolean; rn?: boolean } = {},
  ): void => {
    let letters = '';
    const from: number[] = [];
    const unit: number[] = [];
    let converted = false;
    const push = (c: string, origin: number, at: number): void => {
      letters += c;
      from.push(origin);
      unit.push(unitOf[at]!);
    };
    for (let i = 0; i < n; i++) {
      const c = text[i]!;
      if (run[i]! >= 0) {
        const pair = run[i + 1] === run[i] ? text[i + 1] : undefined;
        if (options.ph === true && c === 'p' && pair === 'h') {
          push('f', CONVERTED, i++);
          converted = true;
        } else if (options.rn === true && c === 'r' && pair === 'n') {
          push('m', CONVERTED, i++);
          converted = true;
        } else if (lBit.has(i) && ((l >> lBit.get(i)!) & 1) === 1) {
          push('i', CONVERTED, i);
          converted = true;
        } else push(c, run[i]!, i);
      } else if (options.digits === false || year[i] || c === '_') {
        // Dropped.
      } else if (c === '1') push(((one >> oneBit.get(i)!) & 1) === 1 ? 'l' : 'i', DIGIT, i);
      else if (LEET[c] !== undefined) push(LEET[c], DIGIT, i);
    }
    if (letters.length > 0 && !out.has(letters))
      out.set(letters, {
        text: letters,
        from,
        unit,
        converted,
        reservedOnly: options.rn === true,
        leadOnly: options.ph === true,
        ...affixBounds(letters, unit),
      });
  };
  // Read as typed first, so that a reading equal to it keeps its plain origins.
  for (const l of ls) for (const one of ones) read(one, l);
  read(0, 0, { digits: false });
  if (text.includes('ph')) read(0, 0, { ph: true });
  if (text.includes('rn')) read(0, ls.at(-1)!, { rn: true });
  return { text, unitText, unitPlain, readings: [...out.values()] };
}

/** The letter readings of a (lowercase) name: leet with each 1 as i or l, look-alikes, and the letters alone. */
export function readings(text: string): string[] {
  return parse(text).readings.map((r) => r.text);
}

/** The parts of a name between underscores, and between underscores or digits. */
export function tokens(text: string): string[] {
  const parts = new Set<string>([...text.split('_'), ...text.split(/[_0-9]+/)]);
  parts.delete('');
  return [...parts];
}

const reverse = (text: string): string => {
  let out = '';
  for (let i = text.length - 1; i >= 0; i--) out += text[i];
  return out;
};

/**
 * A string as letter runs: the letters with runs cut to one, each run's
 * length and first letter's index, whether it holds a look-alike letter read
 * as another, and for each letter of the string the run of letters of the
 * name it was typed in (below 0: a digit or a look-alike).
 */
interface Runs {
  /** The string itself. */
  readonly text: string;
  readonly letters: string;
  readonly counts: readonly number[];
  readonly starts: readonly number[];
  readonly converted: readonly boolean[];
  readonly source: readonly number[];
}

function runsOf(text: string, source?: readonly number[]): Runs {
  let letters = '';
  const counts: number[] = [];
  const starts: number[] = [];
  const converted: boolean[] = [];
  for (let i = 0; i < text.length; i++) {
    if (i === 0 || text[i] !== text[i - 1]) {
      letters += text[i];
      counts.push(0);
      starts.push(i);
      converted.push(false);
    }
    counts[counts.length - 1]!++;
    if (source?.[i] === CONVERTED) converted[converted.length - 1] = true;
  }
  return { text, letters, counts, starts, converted, source: source ?? [] };
}

/** The runs from `start` in `text` are each at least as long as the pattern's. */
function longEnough(text: Runs, start: number, pattern: Runs): boolean {
  for (let j = 0; j < pattern.counts.length; j++)
    if ((text.counts[start + j] ?? 0) < pattern.counts[j]!) return false;
  return true;
}

// Pattern kinds: a blocked term and the allowlisted words that excuse it, and
// a reserved word and the words that may hold it (badminton).
const BAD = 0;
const ALLOW = 1;
const RESERVED = 2;
const HOLDS_RESERVED = 3;

interface Pattern {
  readonly kind: number;
  readonly term: string;
  readonly runs: Runs;
}

interface Automaton {
  /** The trie: next[node * 26 + letter] = child node, or -1. */
  readonly next: Int32Array;
  /** Each node's fail link (the longest proper suffix that is a node). */
  readonly fail: Int32Array;
  /** Pattern indexes ending at a node (after following fail links). */
  readonly out: readonly (readonly number[])[];
  readonly patterns: readonly Pattern[];
}

/** A trie over letters as a flat table (-1: no child), grown as needed. */
class Table {
  next: Int32Array;
  size = 1;

  /** Room for `nodes` nodes (it grows past them if need be). */
  constructor(nodes: number) {
    this.next = new Int32Array(26 * Math.max(nodes, 1)).fill(-1);
  }

  child(node: number, letter: number): number {
    const at = node * 26 + letter;
    let child = this.next[at]!;
    if (child === -1) {
      child = this.size++;
      if (this.size * 26 > this.next.length) {
        const grown = new Int32Array(this.next.length * 2).fill(-1);
        grown.set(this.next);
        this.next = grown;
      }
      this.next[at] = child;
    }
    return child;
  }

  /** The node a word's letters lead to, made as needed. */
  insert(word: string): number {
    let node = 0;
    for (let i = 0; i < word.length; i++) node = this.child(node, word.charCodeAt(i) - 97);
    return node;
  }
}

/**
 * Aho-Corasick over the patterns' letters. Only the trie's own edges are
 * kept (a scan follows fail links), so that compiling is linear in the
 * patterns' letters: the admin's terms compile inside a request.
 */
function compile(patterns: readonly Pattern[]): Automaton {
  const table = new Table(1 + patterns.reduce((sum, p) => sum + p.runs.letters.length, 0));
  const out: number[][] = [[]];
  const kids: number[][] = [[]];
  patterns.forEach((pattern, index) => {
    let node = 0;
    for (let i = 0; i < pattern.runs.letters.length; i++) {
      const letter = pattern.runs.letters.charCodeAt(i) - 97;
      const size = table.size;
      const parent = node;
      node = table.child(node, letter);
      if (table.size > size) {
        out.push([]);
        kids.push([]);
        kids[parent]!.push(letter);
      }
    }
    out[node]!.push(index);
  });
  const size = table.size;
  const next = table.next;
  // Breadth-first fail links; a node's outputs include its fail link's.
  const fail = new Int32Array(size);
  const queue = new Int32Array(size);
  let tail = 0;
  for (const c of kids[0]!) queue[tail++] = next[c]!;
  for (let head = 0; head < tail; head++) {
    const node = queue[head]!;
    for (const c of kids[node]!) {
      const child = next[node * 26 + c]!;
      let link = fail[node]!;
      while (link !== 0 && next[link * 26 + c] === -1) link = fail[link]!;
      const target = next[link * 26 + c]!;
      fail[child] = target > 0 && target !== child ? target : 0;
      const inherited = out[fail[child]!]!;
      if (inherited.length > 0) out[child] = [...out[child]!, ...inherited];
      queue[tail++] = child;
    }
  }
  return { next, fail, out, patterns };
}

interface Hit {
  readonly kind: number;
  /** Run indexes [start, end) in the reading. */
  readonly start: number;
  readonly end: number;
  readonly term: string;
  readonly runs: Runs;
}

function scan(substrings: Substrings, text: Runs, hits: Hit[], allowOnly = false): void {
  const add = (pattern: Pattern, at: number): void => {
    if ((!allowOnly || pattern.kind === ALLOW) && longEnough(text, at, pattern.runs))
      hits.push({
        kind: pattern.kind,
        start: at,
        end: at + pattern.runs.letters.length,
        term: pattern.term,
        runs: pattern.runs,
      });
  };
  const letters = text.letters;
  if ('buckets' in substrings) {
    for (let i = 0; i < letters.length; i++) {
      const c = letters.charCodeAt(i) - 97;
      for (const pattern of substrings.single)
        if (pattern.runs.letters.charCodeAt(0) - 97 === c) add(pattern, i);
      if (i + 1 === letters.length) break;
      for (const pattern of substrings.buckets[c * 26 + letters.charCodeAt(i + 1) - 97] ?? [])
        if (letters.startsWith(pattern.runs.letters, i)) add(pattern, i);
    }
    return;
  }
  const automaton = substrings;
  const { next, fail } = automaton;
  let node = 0;
  for (let i = 0; i < text.letters.length; i++) {
    const c = text.letters.charCodeAt(i) - 97;
    while (node !== 0 && next[node * 26 + c] === -1) node = fail[node]!;
    node = Math.max(0, next[node * 26 + c]!);
    for (const index of automaton.out[node]!) {
      const pattern = automaton.patterns[index]!;
      if (allowOnly && pattern.kind !== ALLOW) continue;
      const start = i + 1 - pattern.runs.letters.length;
      if (longEnough(text, start, pattern.runs))
        hits.push({
          kind: pattern.kind,
          start,
          end: i + 1,
          term: pattern.term,
          runs: pattern.runs,
        });
    }
  }
}

/** Terms (and their reversals, for 4 letters or more, unless in `noReverse`) and the words that excuse them, as patterns. */
function patternsOf(
  terms: readonly string[],
  allow: readonly string[],
  noReverse: ReadonlySet<string> = new Set(),
  kinds: readonly [number, number] = [BAD, ALLOW],
): Pattern[] {
  const patterns: Pattern[] = [];
  for (const term of terms.map(termOf)) {
    if (term.length === 0) continue;
    patterns.push({ kind: kinds[0], term, runs: runsOf(term) });
    if (term.length >= 4 && !noReverse.has(term))
      patterns.push({ kind: kinds[0], term, runs: runsOf(reverse(term)) });
  }
  for (const word of allow.map(termOf))
    if (word.length > 0) patterns.push({ kind: kinds[1], term: word, runs: runsOf(word) });
  return patterns;
}

/**
 * An allowlisted match `word` may excuse the term match `term` it holds:
 * every letter of it was typed as a letter; no underscore or digit falls at
 * either edge of the term inside it (s_ before a term, or _ake after one,
 * leaves the term standing apart; class_clown does not); and the word stands
 * as itself. On a side of the term where the word has fewer than 3 more
 * letters, or on both sides when it has 3 or fewer in all, the word must meet
 * the name's edge, an underscore or a digit there: otherwise those letters
 * read as part of the next word (gang+rape in gangrape, sex+tonight in
 * sextonight), or as noise beside the term (my+dick+e).
 */
function holds(text: Runs, word: Hit, term: Hit): boolean {
  const w = word.runs.counts;
  const t = term.runs.counts;
  const { counts, starts, source } = text;
  // The letters each match takes: of a stretched run at its start, the last
  // ones; at its end, the first ones.
  const firstOf = (hit: Hit, own: readonly number[]): number =>
    starts[hit.start]! + counts[hit.start]! - own[0]!;
  const lastOf = (hit: Hit, own: readonly number[]): number =>
    hit.end - hit.start === 1
      ? starts[hit.start]! + counts[hit.start]! - 1
      : starts[hit.end - 1]! + own[own.length - 1]! - 1;
  const wordFirst = firstOf(word, w);
  const wordLast = lastOf(word, w);
  for (let k = wordFirst; k <= wordLast; k++) if (source[k]! < 0) return false;
  // No underscore or digit at either edge of the term inside the word.
  const termFirst = firstOf(term, t);
  const termLast = lastOf(term, t);
  if (termFirst > wordFirst && source[termFirst - 1] !== source[termFirst]) return false;
  if (termLast < wordLast && source[termLast + 1] !== source[termLast]) return false;
  // The word's own letters on each side of the term.
  const left = termFirst - wordFirst;
  const right = wordLast - termLast;
  const long = left + right >= 4;
  // The word meets the name's edge, an underscore or a digit (or another
  // part's letter): not more letters typed with it (gang+rape, essex+xx).
  const edgeLeft = wordFirst === 0 || source[wordFirst - 1] !== source[wordFirst];
  const edgeRight = wordLast === text.text.length - 1 || source[wordLast + 1] !== source[wordLast];
  return (edgeLeft || (long && left >= 3)) && (edgeRight || (long && right >= 3));
}

/** A match covers a look-alike letter read as another. */
function overConverted(text: Runs, hit: Hit): boolean {
  for (let j = hit.start; j < hit.end; j++) if (text.converted[j] === true) return true;
  return false;
}

/**
 * The first `bad` match that no `allow` match holds (see holds). In a reading
 * with look-alike letters, only a match over one of them counts (the others
 * are judged in the reading as typed), and with ph read as f, only one that
 * starts with it.
 */
function unexcused(
  hits: readonly Hit[],
  text: Runs,
  reading: Reading,
  bad = BAD,
  allow = ALLOW,
): Hit | null {
  for (const hit of hits) {
    if (hit.kind !== bad) continue;
    if (reading.converted && !overConverted(text, hit)) continue;
    if (reading.leadOnly && text.converted[hit.start] !== true) continue;
    const excused = hits.some(
      (a) => a.kind === allow && a.start <= hit.start && a.end >= hit.end && holds(text, a, hit),
    );
    if (!excused) return hit;
  }
  return null;
}

/** A whole-token or reserved term in a trie, with its runs. */
interface TokenEntry {
  readonly kind: number;
  readonly term: string;
  readonly counts: readonly number[];
}

/**
 * Whole-token terms in a trie over their letters with runs cut to one: the
 * file's as a flat table, the admin's (few) with their edges in a map, which
 * takes next to no time to make inside a request.
 */
interface Trie {
  /** next[node * 26 + letter] = child, or -1 (the file's). */
  readonly next: Int32Array | null;
  /** The same edges in a map (the admin's). */
  readonly edges: ReadonlyMap<number, number> | null;
  readonly entries: readonly (readonly TokenEntry[] | undefined)[];
}

function trieOf(terms: readonly { kind: number; term: string }[], flat: boolean): Trie {
  const table = flat ? new Table(1 + terms.reduce((sum, t) => sum + t.term.length, 0)) : null;
  const edges = new Map<number, number>();
  let size = 1;
  const entries: TokenEntry[][] = [];
  for (const { kind, term } of terms) {
    const word = termOf(term);
    if (word.length === 0) continue;
    const runs = runsOf(word);
    let node = 0;
    if (table !== null) node = table.insert(runs.letters);
    else
      for (let i = 0; i < runs.letters.length; i++) {
        const key = node * 26 + runs.letters.charCodeAt(i) - 97;
        let child = edges.get(key);
        if (child === undefined) edges.set(key, (child = size++));
        node = child;
      }
    (entries[node] ??= []).push({ kind, term: word, counts: runs.counts });
  }
  return {
    next: table === null ? null : table.next.slice(0, table.size * 26),
    edges: table === null ? edges : null,
    entries,
  };
}

/**
 * The first `kind` term of the trie that a run of whole parts of the reading
 * spells (one part, neighboring parts joined, or the whole name), or that
 * one part spells with a common affix typed with it on either side or both
 * (my+term, term+lord; Reading.tokenStart and tokenEnd), stretched runs
 * allowed, unless `excused` lets a match inside one part off (given the part
 * and the match's first and last letter). Walks the trie from each place a
 * match may start, so the work is bounded by the parts and the trie.
 */
function tokenMatch(
  reading: Reading,
  trie: Trie,
  kind: number,
  excused: (unit: number, first: number, last: number) => boolean,
): string | null {
  const { text, unit, tokenStart, tokenEnd } = reading;
  const n = text.length;
  const counts: number[] = [];
  for (let s = 0; s < n; s++) {
    if (tokenStart[s] !== 1) continue;
    let node = 0;
    let depth = 0;
    let previous = -1;
    for (let i = s; i < n; i++) {
      const c = text.charCodeAt(i) - 97;
      if (c === previous) counts[depth - 1]!++;
      else {
        node =
          trie.next !== null ? trie.next[node * 26 + c]! : (trie.edges!.get(node * 26 + c) ?? -1);
        if (node === -1) break;
        counts[depth++] = 1;
        previous = c;
      }
      if (tokenEnd[i] !== 1) continue;
      const found = trie.entries[node];
      if (found === undefined) continue;
      for (const entry of found) {
        if (entry.kind !== kind) continue;
        let enough = true;
        for (let j = 0; j < depth; j++) if (counts[j]! < entry.counts[j]!) enough = false;
        if (!enough || (unit[s] === unit[i] && excused(unit[s]!, s, i))) continue;
        return entry.term;
      }
    }
  }
  return null;
}

export interface Lists {
  readonly substring: readonly string[];
  readonly token: readonly string[];
  readonly allow: readonly string[];
  /** Substring terms never matched backwards (their reversal is inside common words). */
  readonly noReverse?: readonly string[];
  /** Matched in the name with its underscores removed (number codes). */
  readonly raw?: readonly string[];
}

/**
 * Substring terms and allowlisted words: the file's compiled into an
 * automaton at startup, the admin's (at most MAX_ADMIN_TERMS of a kind) only
 * filed by their first two letters, which takes next to no time inside a
 * request.
 */
type Substrings = Automaton | Bigrams;

interface Bigrams {
  /** Patterns of two letters or more by their first two (first * 26 + second). */
  readonly buckets: readonly (readonly Pattern[] | undefined)[];
  /** Patterns of one letter (a run such as "zz"). */
  readonly single: readonly Pattern[];
}

function bigrams(patterns: readonly Pattern[]): Bigrams {
  const buckets = new Array<Pattern[] | undefined>(26 * 26).fill(undefined);
  const single: Pattern[] = [];
  for (const pattern of patterns) {
    const word = pattern.runs.letters;
    if (word.length < 2) single.push(pattern);
    else (buckets[(word.charCodeAt(0) - 97) * 26 + word.charCodeAt(1) - 97] ??= []).push(pattern);
  }
  return { buckets, single };
}

/** One set of lists, compiled: the file's, or the admin's extra terms. */
export interface Compiled {
  readonly substring: Substrings;
  readonly token: Trie;
  /** Allowlisted words: a part that is one of them as typed is never a whole-token match. */
  readonly allow: ReadonlySet<string>;
  readonly raw: readonly string[];
}

function compileLists(
  lists: Lists,
  more: { patterns?: readonly Pattern[]; tokens?: readonly string[]; automaton?: boolean } = {},
): Compiled {
  const patterns = [
    ...patternsOf(lists.substring, lists.allow, new Set(lists.noReverse ?? [])),
    ...(more.patterns ?? []),
  ];
  return {
    substring: more.automaton === true ? compile(patterns) : bigrams(patterns),
    token: trieOf(
      [
        ...lists.token.map((term) => ({ kind: BAD, term })),
        ...(more.tokens ?? []).map((term) => ({ kind: RESERVED, term })),
      ],
      more.automaton === true,
    ),
    allow: new Set(lists.allow.map(termOf)),
    raw: (lists.raw ?? []).map(rawOf).filter((code) => code.length > 0),
  };
}

/** The reserved lists, compiled (the long words matched anywhere and the tokens are in the file's lists). */
interface Reserved {
  /** Refused as the whole name, keyed by their letters with runs cut to one. */
  readonly whole: ReadonlyMap<string, readonly { counts: readonly number[] }[]>;
  readonly affixes: ReadonlySet<string>;
  /** Real words that a stretched reserved word would catch (mood for mod). */
  readonly stretchAllow: ReadonlySet<string>;
}

interface FileLists {
  readonly lists: Compiled;
  readonly reserved: Reserved;
  /** The tokenAffixes, forwards and backwards. */
  readonly affix: WordTrie;
  readonly affixBack: WordTrie;
  /** Words whose l is never read as i. */
  readonly lookAlikeAllow: readonly string[];
}

let fileLists: FileLists | null = null;

/**
 * Compiles the file's lists (once per isolate or page). The Worker calls this
 * at startup so that no request pays for it; the browser on its first check.
 * With `warm`, it also runs a few checks so that the code itself is compiled
 * at startup too (the first checks in a fresh isolate are otherwise several
 * times slower).
 */
export function prepareBlocklist(warm = false): void {
  if (fileLists !== null) return;
  const whole = new Map<string, { counts: readonly number[] }[]>();
  for (const word of BLOCKLIST.reserved.map(termOf)) {
    const runs = runsOf(word);
    whole.set(runs.letters, [...(whole.get(runs.letters) ?? []), { counts: runs.counts }]);
  }
  fileLists = {
    lists: compileLists(BLOCKLIST, {
      patterns: patternsOf(BLOCKLIST.reservedSubstring, BLOCKLIST.reservedAllow, new Set(), [
        RESERVED,
        HOLDS_RESERVED,
      ]),
      tokens: BLOCKLIST.reservedTokens,
      automaton: true,
    }),
    reserved: {
      whole,
      affixes: new Set(BLOCKLIST.reservedAffixes.map(termOf)),
      stretchAllow: new Set(BLOCKLIST.reservedStretchAllow.map(termOf)),
    },
    lookAlikeAllow: BLOCKLIST.lookAlikeAllow,
    affix: wordTrie(BLOCKLIST.tokenAffixes),
    affixBack: wordTrie(BLOCKLIST.tokenAffixes.map(reverse)),
  };
  if (warm) warmUp();
}

/**
 * Names that take every path of a check, among them the slowest shapes anyone
 * can register (many 1s and ls, many one-letter parts), for warmUp.
 */
const WARM_UP = [
  'snow_day_kid',
  'b1g_5n0w_2026',
  'x_y_z_fun',
  'player_0042',
  'l1l1_l1l1',
  'hello',
  'phil_born_1999',
  'a_1_b_1_c_1_d_1_e_ff',
  '1_1_1_1_a_b_c_d_e_fg',
  'l1l1_1l1l_x_y_z_w_qr',
  'n1_9_9_3_r_1_1_1_1aa',
  'grape_juice_99',
  // Two of the slowest registrable names a random search found (many 1s, ls and 5s, one-letter parts).
  'nn1_5n1caaaa_cllcccc',
  'c1n5_naa1_na5c5n11_c',
];

/** Rounds of WARM_UP that warmUp checks: enough for the engine to compile the hot code. */
const WARM_ROUNDS = 30;

/**
 * Runs the check's code enough times, with a full set of made-up admin terms
 * made anew each round, that a fresh isolate's first request runs compiled
 * code: the first checks in an isolate are otherwise several times slower.
 */
function warmUp(): void {
  let seed = 7;
  const word = (): string => {
    let out = '';
    for (let i = 0; i < MAX_USERNAME; i++) {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      out += String.fromCharCode(113 + (seed % 10));
    }
    return out;
  };
  const terms = (): string[] => Array.from({ length: MAX_ADMIN_TERMS }, word);
  let extra: ExtraTerms = {};
  for (let round = 0; round < WARM_ROUNDS; round++) {
    if (round % 6 === 0)
      extra = { substring: terms(), token: terms(), allow: terms(), raw: ['1312'] };
    for (const name of WARM_UP) checkUsername(name, { adminName: 'warm_up', extra });
  }
  extraByKey.clear();
}

function file(): FileLists {
  prepareBlocklist();
  return fileLists!;
}

/** The admin's extra terms, compiled once per isolate for each set of terms. */
const extraByObject = new WeakMap<ExtraTerms, Compiled>();
const extraByKey = new Map<string, Compiled>();

const extraKey = (extra: ExtraTerms): string =>
  JSON.stringify([extra.substring, extra.token, extra.allow, extra.raw]);

/** This isolate has compiled this set of terms already. */
function extraKnown(extra: ExtraTerms): boolean {
  return extraByObject.has(extra) || extraByKey.has(extraKey(extra));
}

export function compiledExtra(extra: ExtraTerms): Compiled {
  const known = extraByObject.get(extra);
  if (known !== undefined) return known;
  const key = extraKey(extra);
  let compiled = extraByKey.get(key);
  if (compiled === undefined) {
    compiled = compileLists({
      substring: extra.substring ?? [],
      token: extra.token ?? [],
      allow: extra.allow ?? [],
      raw: extra.raw ?? [],
    });
    // A few term sets at most: the admin edits them now and then.
    const oldest = extraByKey.keys().next();
    if (extraByKey.size >= 4 && oldest.done !== true) extraByKey.delete(oldest.value);
    extraByKey.set(key, compiled);
  }
  extraByObject.set(extra, compiled);
  return compiled;
}

/** The whole reading is a reserved word, stretched or not. */
function wholeReserved(reading: Runs, whole: Reserved['whole']): boolean {
  for (const { counts } of whole.get(reading.letters) ?? []) {
    let enough = true;
    for (let j = 0; j < counts.length; j++) if (reading.counts[j]! < counts[j]!) enough = false;
    if (enough) return true;
  }
  return false;
}

/** The admin's name with nothing, at most two letters, or an affix such as "real" on each side. */
function adminIn(reading: Runs, admin: string, affixes: ReadonlySet<string>): boolean {
  const near = (rest: string): boolean => rest.length <= 2 || affixes.has(rest);
  const forms = [reading.text];
  if (reading.counts.some((c) => c > 2)) forms.push(squeeze(reading.text, 2));
  if (squeeze(admin, 1) === admin) forms.push(reading.letters);
  for (const form of forms)
    for (let at = form.indexOf(admin); at !== -1; at = form.indexOf(admin, at + 1))
      if (near(form.slice(0, at)) && near(form.slice(at + admin.length))) return true;
  return false;
}

/** player_<number> (and its look-alikes) is the name the admin's rename hands out. */
function playerName(text: string): boolean {
  if (!/^p.*\d$/.test(text)) return false;
  const match = /^(.+?)(\d+)$/.exec(text.replace(/_/g, ''));
  if (match === null) return false;
  return readings(match[1]!).some((r) => squeeze(r, 1) === 'player');
}

/** A reading's letters first..last when every one was typed as that letter, else the empty string. */
function typedCore(reading: Reading, first: number, last: number): string {
  for (let k = first; k <= last; k++) if (reading.from[k]! < 0) return '';
  return reading.text.slice(first, last + 1);
}

/** A name read once for all the lists. */
interface Seen extends Parsed {
  /** Each reading as runs. */
  readonly runs: readonly Runs[];
}

function see(text: string): Seen {
  const parsed = parse(text);
  return { ...parsed, runs: parsed.readings.map((r) => runsOf(r.text, r.from)) };
}

/** One layer of lists: all of it, or only its allowlist (to excuse another layer's terms). */
interface Layer {
  readonly lists: Compiled;
  readonly allowOnly?: boolean;
}

/** The substring and allowlist matches in each reading of the name, from every layer. */
function hitsIn(seen: Seen, layers: readonly Layer[]): Hit[][] {
  return seen.runs.map((runs) => {
    const hits: Hit[] = [];
    for (const { lists, allowOnly } of layers) scan(lists.substring, runs, hits, allowOnly);
    return hits;
  });
}

let lastAdmin: [string, string] = ['', ''];
const adminTerm = (name: string): string => {
  if (lastAdmin[0] !== name) lastAdmin = [name, termOf(name)];
  return lastAdmin[1];
};

function reservedIn(
  seen: Seen,
  hits: readonly Hit[][],
  { lists, reserved }: FileLists,
  adminName: string | null,
): boolean {
  const admin = adminName === null ? '' : adminTerm(adminName);
  const stretched = (unit: number, first: number, last: number, reading: Reading): boolean =>
    seen.unitPlain[unit] === true &&
    (reserved.stretchAllow.has(seen.unitText[unit]!) ||
      reserved.stretchAllow.has(typedCore(reading, first, last)));
  const wholeAllowed = reserved.stretchAllow.has(seen.text);
  for (let r = 0; r < seen.runs.length; r++) {
    const runs = seen.runs[r]!;
    const reading = seen.readings[r]!;
    if (!wholeAllowed && wholeReserved(runs, reserved.whole)) return true;
    if (admin.length > 0 && adminIn(runs, admin, reserved.affixes)) return true;
    if (unexcused(hits[r]!, runs, reading, RESERVED, HOLDS_RESERVED) !== null) return true;
    if (
      tokenMatch(reading, lists.token, RESERVED, (u, f, l) => stretched(u, f, l, reading)) !== null
    )
      return true;
  }
  return false;
}

function blockedIn(seen: Seen, hits: readonly Hit[][], layers: readonly Layer[]): string | null {
  const joined = seen.text.replace(/_/g, '');
  for (const { lists, allowOnly } of layers)
    if (allowOnly !== true) for (const code of lists.raw) if (joined.includes(code)) return code;
  for (let r = 0; r < seen.runs.length; r++) {
    if (seen.readings[r]!.reservedOnly) continue;
    const bad = unexcused(hits[r]!, seen.runs[r]!, seen.readings[r]!);
    if (bad !== null) return bad.term;
  }
  // An allowlisted word typed as it is (assess) is not a stretched whole-token term.
  // So is an allowlisted word with an affix (my+assess).
  const allowed = (unit: number, first: number, last: number, reading: Reading): boolean => {
    if (seen.unitPlain[unit] !== true) return false;
    const core = typedCore(reading, first, last);
    return layers.some(
      (layer) => layer.lists.allow.has(seen.unitText[unit]!) || layer.lists.allow.has(core),
    );
  };
  for (const reading of seen.readings) {
    if (reading.reservedOnly) continue;
    for (const { lists, allowOnly } of layers) {
      if (allowOnly === true) continue;
      const hit = tokenMatch(reading, lists.token, BAD, (u, f, l) => allowed(u, f, l, reading));
      if (hit !== null) return hit;
    }
  }
  return null;
}

export interface Verdict {
  readonly problem: UsernameProblem;
  /** For the admin's view: the list term that matched (never shown to the user). */
  readonly term?: string;
}

export interface CheckOptions {
  /** The admin's username (ADMIN_USERNAME): reserved like the staff words. */
  readonly adminName?: string | null;
  /** The admin's extra terms from D1 (compiled once per set, compiledExtra). */
  readonly extra?: ExtraTerms;
}

/** Everything wrong with a username, or null when it may be used (availability aside). */
export function checkUsername(name: string, options: CheckOptions = {}): Verdict | null {
  const format = usernameFormat(name);
  if (format !== null) return { problem: format };
  const text = canonicalUsername(name);
  const lists = file();
  const seen = see(text);
  const layers: Layer[] = [{ lists: lists.lists }];
  if (options.extra !== undefined) layers.push({ lists: compiledExtra(options.extra) });
  const hits = hitsIn(seen, layers);
  if (playerName(text) || reservedIn(seen, hits, lists, options.adminName ?? null))
    return { problem: 'username_reserved' };
  const term = blockedIn(seen, hits, layers);
  return term === null ? null : { problem: 'username_blocked', term };
}

/**
 * A test for whether one (new) admin term matches a name, honoring the file's
 * and the admin's allowlists: the scan that lists every existing username a
 * new term catches. Compiled once, then run over many names.
 */
export function termScanner(
  term: string,
  kind: 'substring' | 'token' | 'raw',
  allow: readonly string[] = [],
): (name: string) => boolean {
  const word = kind === 'raw' ? rawOf(term) : termOf(term);
  if (word.length === 0) return () => false;
  const own = compileLists({
    substring: kind === 'substring' ? [word] : [],
    token: kind === 'token' ? [word] : [],
    allow: [],
    raw: kind === 'raw' ? [word] : [],
  });
  const layers: Layer[] = [
    { lists: own },
    { lists: file().lists, allowOnly: true },
    { lists: compiledExtra({ allow }), allowOnly: true },
  ];
  return (name) => {
    const seen = see(canonicalUsername(name));
    return blockedIn(seen, hitsIn(seen, layers), layers) !== null;
  };
}

/** The file's list version, for the admin view. */
export const BLOCKLIST_VERSION = BLOCKLIST.version;
