/** District names as a family says them: their own words, the kind and the state's ids left out. */

/** Words before a district's kind that only say what kind of district it is. */
const KIND_WORDS = [
  'community unit',
  'community consolidated',
  'community high',
  'township high',
  'regional high',
  'regional vocational',
  'regional',
  'geographic',
  'k-12',
  'unified union',
  'union free',
  'exempted village',
  'joint union high',
  'joint union elementary',
  'union high',
  'union elementary',
  'reorganized',
  'common',
  'unified',
  'independent',
  'consolidated',
  'community',
  'area',
  'public',
  'local',
  'joint',
  'unit',
  'high',
  'middle',
  'grade',
  'elementary',
  // "Township" only as Illinois writes "Township High School District": "Township HSD".
  'township(?=\\s+(?:hsd|h\\.s\\.d\\.?|chsd)\\b)',
].join('|');
/** What a district is called as a district: "School District", "CUSD". */
const KIND_NOUNS = [
  'school district',
  'school dist',
  'school corp(?:oration)?',
  'schl corp',
  'school system',
  // Not "School": a district of one school is its name.
  'schools',
  'district',
  'dist',
  's/d',
  'cted',
  'cusd',
  'cud',
  'sud',
  'ed',
  'ccsd',
  'chsd',
  'cuhsd',
  'uhsd',
  'jusd',
  'cesd',
  'hsd',
  'esd',
  'psd',
  'gsd',
  'chd',
  'msd',
  'usd',
  'ud',
  'isd',
  'cisd',
  'ufsd',
  'csd',
  'sd',
].join('|');
/** What can end a district's name with no noun after it: "Union High", "Unified". */
const KIND_ENDINGS = [
  '(?:joint\\s+)?union\\s+high\\s+school',
  'regional vocational technical',
  'community city',
  'joint union high',
  'joint union elementary',
  'union high',
  'union elementary',
  'union free',
  'exempted village',
  'joint unified',
  'unified',
  'independent',
  'community',
  'consolidated',
  'local',
  'area',
  'joint',
  'regional',
  'k-12',
].join('|');
/** A name's last kind: "Community Unit School District", "Union High", "ISD". */
function kindOf(words: string): RegExp {
  return new RegExp(`(?:^|\\s+)(?:(?:${words})\\s+)*(?:${KIND_NOUNS}|${KIND_ENDINGS})$`, 'i');
}
const KIND = kindOf(KIND_WORDS);
/** New York's central school districts: "Dolgeville Central School District"; elsewhere "Central" is a name. */
const KIND_NY = kindOf(`central high|central|${KIND_WORDS}`);
/** What New York adds after a district's kind: "(Marcus Whitman)", "at Delhi"; elsewhere a county that tells two apart. */
const ALIAS_NY = new RegExp(`(?<=\\b(?:${KIND_NOUNS}))\\s+(?:\\([^)]*\\)|at\\s+.+)$`, 'i');
/** A district's number: "204", "No. 196", "#1", "Re-1J", "127-5", "6-J", "R- 5", "10Jt-R", "R-IV". */
const NUMBER_TEXT =
  '(?:(?:[a-z]{1,2}-?\\s?)?\\d+[a-z]{0,2}|[a-z]{1,2}-\\s?[ivxl]+)(?:-[a-z\\d]{1,2})*';
/** A district's number after its kind, and "Jt." (joint) after it. */
const NUMBER = new RegExp(
  `\\s+(?:re:\\s*)?(?:no?\\.?\\s*|#\\s*)?(${NUMBER_TEXT})(?:\\s+jt\\.?)?$`,
  'i',
);
/** A number of digits alone after its kind, read first: "Massac UD 1", never "UD 1". */
const DIGITS = /\s+(?:no?\.?\s*|#\s*)?(\d+[a-z]{0,2}(?:-[a-z\d]{1,2})*)(?:\s+jt\.?)?$/i;
/** A name that leads with its kind and number, then its place: "School District No. Re-2 Brush". */
const LEADING = new RegExp(
  `^(?:(?:${KIND_WORDS})\\s+)*(?:school district|district)\\s+(?:no?\\.?\\s*|#\\s*)?(${NUMBER_TEXT})(?:\\s+(.+))?$`,
  'i',
);
/** Colorado's "in the county of El Paso and State of Colorado", cut short or not. */
const COUNTY_TAIL =
  /(?<=\d[a-z\d-]*(?:\s+jt\.?)?)\s+(?:in|of)\s+(?:the\s+)?co(?:u(?:n(?:ty?|ties)?)?)?\b.*$/i;
/** The county a Colorado name says, in its capitalized words: "Denver", "El Paso". */
const COUNTY = /\bcount(?:y|ies)\s+of\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)/;
/** Michigan's "School District of the City of", its place cut off after it. */
const CITY_TAIL = /\s+of\s+the\s+city\s+of$/i;
const KIND_WORD = new RegExp(`\\b(?:${KIND_WORDS})\\b`, 'i');
/** What joins words of a name, never ends one: "Arts and", "Academy -". */
const JOINER = /\s*(?:[-:,&]|\band)$/i;
/** A word that cannot end a name: "Superintendent of". */
const DANGLING = /\s(?:of|for|at|in|to|on|by|with)$/i;
/** Arizona's id after a name: " (4192)". */
const STATE_ID = /\s*\(\d+\)$/;
/** A name with nothing left but kinds. */
const KIND_ONLY = new RegExp(
  `^(?:(?:${KIND_WORDS}|${KIND_NOUNS}|township|regional|high|elementary|unit|union)(?:\\s+|$))+$`,
  'i',
);

/**
 * `words` null for a name of nothing but its kind and number (CUSD 300); `whole` keeps the kind,
 * `named` all of it but its last noun ("Franklin Regional"), where that still names a place.
 */
export interface DistrictName {
  readonly words: string | null;
  readonly number: string | null;
  readonly whole: string;
  readonly named: string;
}

/** A word that names no place alone: "Central Local" stays whole, never "Central". */
const PLACELESS =
  /^(?:north|south|east|west|northern|southern|eastern|western|northeast|northwest|southeast|southwest|central|united|union|valley|county|city|community|region)$/i;
/** A name's kind noun at its end, alone: "Valley Central School District" to "Valley Central". */
const NOUN_END = new RegExp(`\\s+(?:public\\s+)?(?:${KIND_NOUNS})$`, 'i');
/** A kind noun anywhere: "Custer County School District Consolidate 1" is no place and number. */
const NOUN_ANY = new RegExp(`\\b(?:${KIND_NOUNS})\\b`, 'i');
/** Maine's kinds, said with their numbers: "RSU 16" is a name, never "RSU". */
const UNIT_KINDS = /^(?:rsu|msad|sad|sau|aos|boces)$/i;

/** The whole name but its last noun, where that still names a place: "Valley Central". */
function namedOf(whole: string): string {
  const named = whole.replace(NOUN_END, '');
  return PLACELESS.test(named) || KIND_ONLY.test(named) ? whole : named;
}

/** Its words and number; the whole name where its words alone would say no place. */
function parts(words: string | null, number: string | null, whole: string): DistrictName {
  const named = namedOf(whole);
  if (words === null || words.replace(/[^a-z]/gi, '').length < 3 || KIND_ONLY.test(words)) {
    // Its number's district only where it says it is one: "CUSD 300", never "Community R-VI".
    const district = number !== null && NOUN_ANY.test(whole);
    return { words: district ? null : whole, number: district ? number : null, whole, named };
  }
  if (!PLACELESS.test(words)) return { words, number, whole, named };
  if (number !== null) return { words: `${words} ${number}`, number: null, whole, named };
  return { words: named, number: null, whole, named };
}

/** Words a number can follow with no kind between: a place's, never a kind's or another number's. */
function numbered(words: string): boolean {
  const trimmed = words.trim();
  return (
    trimmed.replace(/[^a-z]/gi, '').length >= 3 &&
    !/\d/.test(trimmed) &&
    !/\b(?:school|academy|charter|center)$/i.test(trimmed) &&
    !NOUN_ANY.test(trimmed) &&
    !UNIT_KINDS.test(trimmed) &&
    !KIND_ONLY.test(trimmed)
  );
}

/** A district's name apart: "Indian Prairie" and "204" for Indian Prairie CUSD 204. */
export function districtName(shown: string, state: string | null = null): DistrictName {
  let name = shown
    .replace(STATE_ID, '')
    // A name run into its kind: "GreeleySchool District No. 6".
    .replace(/([a-z])(School District)/g, '$1 $2');
  const county = COUNTY.exec(name)?.[1] ?? null;
  name = name.replace(COUNTY_TAIL, '').replace(CITY_TAIL, '');
  if (state === 'NY') name = name.replace(ALIAS_NY, '');
  name = name.trim();
  const whole = name;
  const leading = LEADING.exec(name);
  if (leading !== null) return parts(leading[2]?.trim() ?? county, leading[1] ?? null, whole);
  const kind = state === 'NY' ? KIND_NY : KIND;
  let number: string | null = null;
  for (const after of [DIGITS.exec(name), NUMBER.exec(name)]) {
    if (after !== null && kind.test(name.slice(0, after.index))) {
      number = after[1] ?? null;
      name = name.slice(0, after.index);
      break;
    }
  }
  let cut = false;
  for (let found = kind.exec(name); found !== null; found = kind.exec(name)) {
    name = name.slice(0, found.index);
    cut = true;
  }
  // A number with no kind at all: "Blue Springs R-IV", "Kansas City 33".
  const bare = cut ? null : NUMBER.exec(name);
  if (bare !== null && numbered(name.slice(0, bare.index))) {
    number = bare[1] ?? null;
    name = name.slice(0, bare.index);
    cut = true;
  }
  if (!cut) return { words: whole, number: null, whole, named: whole };
  const left = name.trim().replace(/\s+the$/i, '');
  // Kind words after a joiner were the name's own: "Arts and Community District", "- Middle District".
  if ((JOINER.test(left) && KIND_WORD.test(whole.slice(name.length))) || DANGLING.test(left)) {
    const named = namedOf(whole);
    const kept = JOINER.test(named) || DANGLING.test(named) ? whole : named;
    return { words: kept, number: null, whole, named: kept };
  }
  return parts(left.replace(JOINER, ''), number, whole);
}

/** Districts whose words another district of the state shares (Hinsdale 86, Hinsdale 181): they keep their numbers. */
export function alikeDistricts(
  districts: readonly {
    readonly id: string;
    readonly state: string | null;
    readonly shown: string;
  }[],
): string[] {
  const byName = new Map<string, string[]>();
  for (const { id, state, shown } of districts) {
    const { words } = districtName(shown, state);
    if (words === null) continue;
    const key = `${state ?? ''}\n${words.toLowerCase()}`;
    const ids = byName.get(key);
    if (ids === undefined) byName.set(key, [id]);
    else ids.push(id);
  }
  return [...byName.values()].filter((ids) => ids.length > 1).flat();
}
