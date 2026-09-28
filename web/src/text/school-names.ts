/**
 * The school and district names the directory itself says to show another
 * way (names.ts NameFix), worked out once from the whole directory when the
 * site is built (tools/school-names.ts).
 *
 * Cut names. NCES keeps a name to a fixed number of characters, which varies
 * by state and survey (30 in Missouri, 60 in most states), and cuts a longer
 * one off where the field ends, often in the middle of a word ("ALLEN VILLAGE
 * ELEMENTARY ACADE"). A name is taken to be cut when it is exactly as long as
 * the longest names from its state and survey, and at least CUT_AT_WIDTH of
 * them are. Its last word, when it is not a word the directory uses anywhere
 * else, is a cut-off word: it is shown as the one word of the directory it can
 * be the start of, if there is exactly one, or else as the one word of its own
 * district's names it can be ("ALLEN VILLAGE ELEMENTARY ACADE", beside the
 * district's "JUNIOR ACADEMY" and "PRIMARY ACADEMY", is "Allen Village
 * Elementary Academy"), and left off otherwise, with any mark or joining word
 * left hanging before it. Nothing is guessed.
 *
 * Generic names. A public school whose own name is only generic words of its
 * level or of the kind of school it is ("ELEMENTARY SCHOOL", "Middle School",
 * "The Academy", "Virtual Academy", "Alternative School"), or a school word
 * and its number ("School 8", "School No. 1"), is named with its district or
 * charter first, in that name's own words, unless that name already starts
 * the school's ("CENTER EL" of Center ISD).
 */
import { displayName, isShortening } from './names.ts';
import type { NameFix, NameHint } from './names.ts';

/** What the directory says about its names (meta.json, points.bin). */
export interface DirectoryNames {
  /** School ids and names, in the directory's order. */
  readonly ids: readonly string[];
  readonly names: readonly string[];
  /** Each school's district, as a position in `districts`; -1 for none. */
  readonly districtOf: ArrayLike<number>;
  readonly districts: { readonly ids: readonly string[]; readonly names: readonly string[] };
}

/** The fixes, by school id and by district id. */
export interface NameFixes {
  readonly schools: Readonly<Record<string, NameFix>>;
  readonly districts: Readonly<Record<string, NameFix>>;
}

/** Names at least this many must share the longest length for it to be the field's width. */
export const CUT_AT_WIDTH = 3;
/** A word used at least this many times before another word is a word. */
export const WORD_USES = 3;
/**
 * A word that ends at least ENDING_USES names NCES did not cut is a word,
 * while it is used at least 1 / ENDING_SHARE as often as the words it starts.
 */
export const ENDING_USES = 2;
export const ENDING_SHARE = 100;

/**
 * Words that say only what level a school is, or what kind of school, with
 * the words that join them. A name of these alone says nothing of which
 * school it is.
 */
const GENERIC_WORDS: ReadonlySet<string> = new Set([
  'ACAD',
  'ACADEMY',
  'ALT',
  'ALTERNATIVE',
  'CAMPUS',
  'CENTER',
  'CHARTER',
  'CHILDHOOD',
  'CNTR',
  'COMMUNITY',
  'CONTINUATION',
  'CTR',
  'CYBER',
  'DAY',
  'DIGITAL',
  'EARLY',
  'EL',
  'ELEM',
  'ELEMENTARY',
  'ES',
  'EVENING',
  'GRADE',
  'HIGH',
  'HOMEBOUND',
  'HS',
  'INT',
  'INTERM',
  'INTERMED',
  'INTERMEDIATE',
  'JH',
  'JHS',
  'JR',
  'JUNIOR',
  'K',
  'KDGN',
  'KINDERGARTEN',
  'LEARNING',
  'LOWER',
  'LRNG',
  'MAGNET',
  'MIDDLE',
  'MONTESSORI',
  'MS',
  'NIGHT',
  'ONLINE',
  'OPPORTUNITY',
  'PRE',
  'PREK',
  'PREP',
  'PREPARATORY',
  'PRI',
  'PRIMARY',
  'SCH',
  'SCHL',
  'SCHOOL',
  'SCHOOLS',
  'SECONDARY',
  'SENIOR',
  'SHS',
  'SR',
  'STEAM',
  'STEM',
  'UPPER',
  'VIRTUAL',
]);
/** Words a school's number follows, and the words that can stand between them ("School No. 1"). */
const NUMBERED_WORDS: ReadonlySet<string> = new Set(['SCH', 'SCHL', 'SCHOOL']);
const NUMBER_WORDS: ReadonlySet<string> = new Set(['NO', 'NUMBER']);
const NUMBER = /^\d+$/u;
/** Words that only join others. */
const JOINING_WORDS: ReadonlySet<string> = new Set([
  'AND',
  'AT',
  'DBA',
  'FOR',
  'IN',
  'OF',
  'THE',
  'TO',
]);

/**
 * A district's name proper, as shown: up to the first words that make it a
 * district ("School District", "Public Schools", "ISD"), leaving off the
 * number, county or city after them, so a school named first by its district
 * reads short ("Cherry Creek School District No. 5 in the county of Arapah"
 * is "Cherry Creek School District"; "Quincy School District 172", "Quincy
 * School District"). A district whose name before those words says nothing
 * of which one it is keeps its whole name ("Intermediate School District
 * 287"). The first group is the name before those words.
 */
const DISTRICT_PROPER =
  /^(.*?)\b(?:(?:Unified |Community |Consolidated |Independent |Union |City |County )?School District|Public Schools|Schools|ISD|CISD|USD|CUSD|Unified|District)\b/u;

/** Words of a name, in capitals: runs of letters and digits. */
function words(name: string): string[] {
  return (name.toUpperCase().match(/[\p{L}\p{N}]+/gu) ?? []).map((word) => word);
}

/** Whether a word at `i` is a school's number, or a word before one, after a school word. */
function numbers(all: readonly string[], i: number): boolean {
  let at = i;
  if (NUMBER_WORDS.has(all[at] ?? '')) {
    if (!NUMBER.test(all[at + 1] ?? '')) return false;
  } else if (!NUMBER.test(all[at] ?? '')) return false;
  while (at > 0 && !NUMBERED_WORDS.has(all[at - 1] ?? '')) {
    if (!NUMBER_WORDS.has(all[at - 1] ?? '')) return false;
    at--;
  }
  return at > 0;
}

/**
 * Whether a name is only generic words of a school's level or kind, with at
 * least one of them, and any number only right after a school word.
 */
export function isGenericName(name: string): boolean {
  const all = words(name);
  return (
    all.every((word, i) => GENERIC_WORDS.has(word) || JOINING_WORDS.has(word) || numbers(all, i)) &&
    all.some((word) => GENERIC_WORDS.has(word))
  );
}

/** USPS codes of the continental states and DC by FIPS code, for the names' hints. */
const STATE_BY_FIPS: Readonly<Record<string, string>> = {
  '01': 'AL',
  '04': 'AZ',
  '05': 'AR',
  '06': 'CA',
  '08': 'CO',
  '09': 'CT',
  '10': 'DE',
  '11': 'DC',
  '12': 'FL',
  '13': 'GA',
  '16': 'ID',
  '17': 'IL',
  '18': 'IN',
  '19': 'IA',
  '20': 'KS',
  '21': 'KY',
  '22': 'LA',
  '23': 'ME',
  '24': 'MD',
  '25': 'MA',
  '26': 'MI',
  '27': 'MN',
  '28': 'MS',
  '29': 'MO',
  '30': 'MT',
  '31': 'NE',
  '32': 'NV',
  '33': 'NH',
  '34': 'NJ',
  '35': 'NM',
  '36': 'NY',
  '37': 'NC',
  '38': 'ND',
  '39': 'OH',
  '40': 'OK',
  '41': 'OR',
  '42': 'PA',
  '44': 'RI',
  '45': 'SC',
  '46': 'SD',
  '47': 'TN',
  '48': 'TX',
  '49': 'UT',
  '50': 'VT',
  '51': 'VA',
  '53': 'WA',
  '54': 'WV',
  '55': 'WI',
  '56': 'WY',
};

/**
 * The USPS code of the state a public school (12 digits) or district (7
 * digits) is in, from its NCES id, which starts with the state's FIPS code;
 * null for a private school, whose id does not say.
 */
export function stateOfId(id: string | null | undefined): string | null {
  if (id === null || id === undefined || !/^\d{7}(?:\d{5})?$/u.test(id)) return null;
  return STATE_BY_FIPS[id.slice(0, 2)] ?? null;
}

/** Where a survey's names come from: public schools by state, private schools, districts by state. */
function sourceOf(id: string, district: boolean): string {
  const state = stateOfId(id);
  if (district) return `district ${state ?? '?'}`;
  return state === null ? 'private' : `public ${state}`;
}

/** Each source's field width: its longest names' length, where enough names share it. */
function fieldWidths(names: readonly { name: string; source: string }[]): Map<string, number> {
  const longest = new Map<string, { length: number; count: number }>();
  for (const { name, source } of names) {
    const seen = longest.get(source);
    if (seen === undefined || name.length > seen.length) {
      longest.set(source, { length: name.length, count: 1 });
    } else if (name.length === seen.length) seen.count++;
  }
  const widths = new Map<string, number>();
  for (const [source, { length, count }] of longest) {
    if (count >= CUT_AT_WIDTH) widths.set(source, length);
  }
  return widths;
}

/** A name's last word, when the name ends with it: where it starts and its letters. */
function lastWord(name: string): { at: number; word: string } | null {
  const match = /\p{L}+$/u.exec(name);
  if (match === null) return null;
  return { at: match.index, word: match[0].toUpperCase() };
}

/** Where a name ends once `at` onwards is left off, with any mark or joining word left hanging. */
function endBefore(name: string, at: number): number {
  let end = at;
  for (;;) {
    const trimmed = name.slice(0, end).replace(/[\s\-/&@(,:;.+]+$/u, '');
    const joining = /(?:^|[^\p{L}\p{N}])(\p{L}+)$/u.exec(trimmed);
    const word = joining?.[1];
    if (word !== undefined && JOINING_WORDS.has(word.toUpperCase()) && joining !== null) {
      end = trimmed.length - word.length;
      continue;
    }
    return trimmed.length;
  }
}

/**
 * The fix for a cut name, or null when it ends with a whole word: a word
 * the directory uses, a shortening the page spells out, or a word no word of
 * the directory starts with (a place's own name, "Kinmundy").
 */
function cutFix(name: string, vocabulary: Vocabulary): NameFix | null {
  const last = lastWord(name);
  if (last === null) return null;
  const before = words(name.slice(0, last.at));
  const joined = JOINING_WORDS.has(before[before.length - 1] ?? '');
  const starting = wordsStarting(vocabulary, last.word);
  const inside = vocabulary.inside.get(last.word) ?? 0;
  const ending = vocabulary.ending.get(last.word) ?? 0;
  const longer = starting.reduce((sum, [, uses]) => sum + uses, 0);
  // A single letter is an initial, unless it hangs off a joining word ("State of C"). A word
  // used before others is a word, and so is one that ends other names, unless far more names
  // have a word it starts ("Summer Session" is whole; "Scho", which ends a few names cut
  // shorter, is the start of "School").
  if (last.word.length === 1) {
    if (!joined) return null;
  } else if (
    inside >= WORD_USES ||
    (ending >= ENDING_USES && (inside + ending) * ENDING_SHARE >= longer)
  ) {
    return null;
  }
  if (last.word.length > 1 && isShortening(last.word)) return null;
  const could = starting.filter(([, uses]) => uses >= WORD_USES).map(([word]) => word);
  // No word of the directory starts so: a word of its own, used too rarely to count
  // ("Kinmundy", "Summer Session").
  if (could.length === 0 && last.word.length > 1) return null;
  // What every word it could be starts with, when that is itself the word most of them are:
  // "SCHOO" of "SCHOOL", "SCHOOLS" and "SCHOOLHOUSE" is "School"; "ACADE" of "ACADEMY" and
  // "ACADEMIC" is no word, and "INNOV" of "INNOVATION" and "INNOVA" is not "Innova".
  const shared = could.reduce((common, word) => {
    let n = 0;
    while (n < common.length && common[n] === word[n]) n++;
    return common.slice(0, n);
  }, could[0] ?? '');
  const uses = (word: string): number => vocabulary.inside.get(word) ?? 0;
  const all = could.reduce((sum, word) => sum + uses(word), 0);
  if (
    last.word.length > 1 &&
    shared.length > last.word.length &&
    uses(shared) >= WORD_USES &&
    uses(shared) * 2 >= all
  ) {
    return { end: last.at, word: displayName(shared) };
  }
  // "Non-Res": a short word joined to the cut one goes with it.
  let at = last.at;
  const joinedTo = /(?:^|[^\p{L}])(\p{L}{1,3})-$/u.exec(name.slice(0, at));
  if (joinedTo?.[1] !== undefined) at -= joinedTo[1].length + 1;
  const end = endBefore(name, at);
  return end > 0 ? { end } : null;
}

/** The words used before others that start with `start` and are longer, with their uses. */
function wordsStarting(vocabulary: Vocabulary, start: string): [string, number][] {
  const { sorted } = vocabulary;
  let low = 0;
  let high = sorted.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if ((sorted[middle] ?? '') <= start) low = middle + 1;
    else high = middle;
  }
  const found: [string, number][] = [];
  for (let i = low; i < sorted.length; i++) {
    const word = sorted[i] ?? '';
    if (!word.startsWith(start)) break;
    found.push([word, vocabulary.inside.get(word) ?? 0]);
  }
  return found;
}

/** The directory's words and how often each is used. */
interface Vocabulary {
  /**
   * Where a word is followed by another: a word NCES cut off ends its name,
   * sometimes with a number after it ("Liberty Arts Acade (90334)"), and is
   * never followed by one.
   */
  readonly inside: ReadonlyMap<string, number>;
  /** Where a word ends a name NCES did not cut: whole words too ("Summer Session"). */
  readonly ending: ReadonlyMap<string, number>;
  /** The words of `inside`, sorted. */
  readonly sorted: readonly string[];
}

function vocabularyOf(
  names: readonly { name: string; source: string }[],
  widths: ReadonlyMap<string, number>,
): Vocabulary {
  const inside = new Map<string, number>();
  const ending = new Map<string, number>();
  for (const { name, source } of names) {
    const all = words(name);
    const cut = name.length === widths.get(source);
    all.forEach((word, i) => {
      if (!/^\p{L}+$/u.test(word)) return;
      const next = all[i + 1];
      if (next === undefined) {
        if (!cut) ending.set(word, (ending.get(word) ?? 0) + 1);
      } else if (/^\p{L}/u.test(next)) inside.set(word, (inside.get(word) ?? 0) + 1);
    });
  }
  return { inside, ending, sorted: [...inside.keys()].sort() };
}

/** Every school and district name the directory says to show another way. */
export function nameFixes(directory: DirectoryNames): NameFixes {
  const { ids, names, districtOf, districts } = directory;
  const all = [
    ...ids.map((id, i) => ({ id, name: names[i] ?? '', source: sourceOf(id, false) })),
    ...districts.ids.map((id, i) => ({
      id,
      name: districts.names[i] ?? '',
      source: sourceOf(id, true),
    })),
  ];
  const widths = fieldWidths(all);
  const vocabulary = vocabularyOf(all, widths);
  const cut = (name: string, source: string): NameFix | null =>
    name.length === widths.get(source) ? cutFix(name, vocabulary) : null;

  const districtFixes: Record<string, NameFix> = {};
  districts.ids.forEach((id, d) => {
    const fix = cut(districts.names[d] ?? '', sourceOf(id, true));
    if (fix !== null) districtFixes[id] = fix;
  });
  /**
   * A district's name as shown before one of its schools' names, its own fix applied, up to
   * the words that make it a district (DISTRICT_PROPER).
   */
  const districtShown = (d: number): string => {
    const id = districts.ids[d] ?? '';
    const hint: NameHint = { state: stateOfId(id), district: true };
    const shown = displayName(districts.names[d] ?? '', hint, districtFixes[id]);
    const match = DISTRICT_PROPER.exec(shown);
    const own = match?.[1] ?? '';
    const proper =
      match !== null && words(own).length > 0 && !isGenericName(own) ? match[0] : shown;
    // "Hamtramck School District of the City of": a name that ends hanging, as NCES left it.
    return proper.slice(0, endBefore(proper, proper.length));
  };

  // The words of each district's own names, its schools' and its own, but for the words NCES
  // cut off: what a cut word of one of its schools can only be ("ACADE" of Allen Village's
  // "JUNIOR ACADEMY" and "PRIMARY ACADEMY").
  const districtWords = new Map<number, Set<string>>();
  const addWords = (d: number, name: string, cutOff: boolean): void => {
    const all = words(name).filter((word) => /^\p{L}+$/u.test(word));
    if (cutOff) all.pop();
    let known = districtWords.get(d);
    if (known === undefined) {
      known = new Set();
      districtWords.set(d, known);
    }
    for (const word of all) known.add(word);
  };
  districts.names.forEach((name, d) => {
    addWords(d, name, name.length === widths.get(sourceOf(districts.ids[d] ?? '', true)));
  });
  ids.forEach((id, i) => {
    const d = districtOf[i] ?? -1;
    const name = names[i] ?? '';
    if (d >= 0) addWords(d, name, name.length === widths.get(sourceOf(id, false)));
  });

  const schoolFixes: Record<string, NameFix> = {};
  ids.forEach((id, i) => {
    const name = names[i] ?? '';
    const fix: { end?: number; word?: string; district?: string } = {
      ...cut(name, sourceOf(id, false)),
    };
    const d = districtOf[i] ?? -1;
    // A cut word no word of the whole directory alone completes, that one word of its own
    // district's names does.
    const last = lastWord(name);
    if (fix.end !== undefined && fix.word === undefined && d >= 0 && last !== null) {
      const completions = [...(districtWords.get(d) ?? [])].filter(
        (word) => word.length > last.word.length && word.startsWith(last.word),
      );
      const [only] = completions;
      if (completions.length === 1 && only !== undefined) {
        fix.end = last.at;
        fix.word = displayName(only);
      }
    }
    if (d >= 0 && isGenericName(name)) {
      const district = districtShown(d);
      const first = (text: string): string | undefined =>
        words(text).find((word) => !JOINING_WORDS.has(word));
      // Center ISD's "CENTER EL", and a charter named as its school, say it already.
      if (district !== '' && first(name) !== first(district)) fix.district = district;
    }
    if (Object.keys(fix).length > 0) schoolFixes[id] = fix;
  });
  return { schools: schoolFixes, districts: districtFixes };
}
